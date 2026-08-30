from __future__ import annotations

import json
import os
import subprocess
from datetime import date
from pathlib import Path

from . import config
from .models import RawItem
from .pipeline.normalize import normalize
from .pipeline.pool import load_newsletter_items, load_pool_items, reset_pool
from .pipeline.prefilter import prefilter
from .pipeline.score import score
from .render.email import render_html
from .render.mailer import send_html
from .render.report import render
from .sources_factory import build_sources

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
SEEN_FILE = REPORTS_DIR / "seen_urls.json"
SEEN_MAX = 1000  # cap del historial de URLs evaluadas


def _load_seen(current_week: str) -> set[str]:
    """URLs ya evaluadas en semanas ANTERIORES (re-runs de la misma semana no filtran)."""
    if not SEEN_FILE.exists():
        return set()
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return {url for url, week in data.items() if week != current_week}
    except Exception as e:  # noqa: BLE001 — un archivo corrupto no tumba el run
        print(f"[seen] archivo ilegible, se ignora: {e}")
        return set()


def _save_seen(candidates, current_week: str) -> None:
    data: dict[str, str] = {}
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    for it in candidates:
        data[it.dedup_key()] = current_week
    # Conserva solo las entradas más recientes (dict preserva orden de inserción).
    if len(data) > SEEN_MAX:
        data = dict(list(data.items())[-SEEN_MAX:])
    SEEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def run() -> Path:
    raw: list[RawItem] = []
    for src in build_sources():
        items = src.fetch()
        print(f"[{src.name}] {len(items)} items")
        raw.extend(items)

    today = date.today()
    week = today.isocalendar().week
    week_key = f"{today.year}-W{week:02d}"

    # Fetch fresco + pool acumulado por el job diario (prefilter dedup-ea)
    # + newsletters empujados desde GBrain por el LaunchAgent del Mac.
    pool_items = load_pool_items()
    newsletter_items = load_newsletter_items()
    print(f"[pool] {len(pool_items)} items acumulados + {len(newsletter_items)} newsletters GBrain")

    merged = normalize(raw) + pool_items + newsletter_items
    source_counts: dict[str, int] = {}
    for it in merged:
        source_counts[it.source] = source_counts.get(it.source, 0) + 1

    warnings = _source_health(source_counts)
    for w in warnings:
        print(f"[salud] {w}")

    themes = _count_themes(merged)
    momentum = _theme_momentum(themes)
    print(f"[temas] {themes}")
    for m in momentum:
        print(f"[momentum] {m}")
    dead = _dead_themes(themes)
    warnings.extend(dead)
    for d in dead:
        print(f"[salud-tema] {d}")

    candidates = prefilter(merged, seen_urls=_load_seen(week_key))
    print(f"[prefilter] {len(candidates)} candidatos a Claude")

    result = score(candidates)
    scored = result.deep
    scored.sort(key=lambda s: s.objetivo_total, reverse=True)
    scoring_failed = bool(candidates) and not scored
    if result.truncated:
        warnings.append(
            f"análisis truncado a max_tokens ({len(scored)} de {config.TOP_DEEP} ideas "
            "rescatadas) — subir max_tokens si se repite")
    if result.triage_truncated:
        sin_score = sum(1 for t in result.triage if t.get("total") is None)
        warnings.append(
            f"⚠️ triage truncado a max_tokens — {sin_score} de {len(candidates)} candidatos "
            "quedaron SIN evaluar esta semana (silenciosamente excluidos, no por criterio)")

    # Ideas que pasaron el gate (para el reporte Markdown del repo)
    passing = [s for s in scored if s.passes_gate(config.MIN_OBJETIVO)]
    top_gate = passing[: config.MAX_IDEAS]

    # Email separado en dos secciones: empresas concretas (estudiables,
    # replicables) vs tendencias/reflexiones (señal de mercado, sin un jugador
    # único). Sin este split, las tendencias — que suelen puntuar alto por
    # agregar señal de varias empresas — desplazaban a las empresas del top 5.
    # Rellenar el cupo con ideas bajo el gate es diseño intencional (Matías:
    # "está bien que igual traiga esas empresas") — el problema real cuando
    # esto se ve mal (2026-W35) no es el relleno, es que el prompt zombie el
    # problema_score de candidatos interesantes por una barrera de ejecución
    # alta. Fix real: prompts/score.md + triage.md, no acá.
    TENDENCIA_TYPES = {"Tendencia", "Reflexión"}
    empresas_scored = [s for s in scored if s.tipo_candidato not in TENDENCIA_TYPES]
    tendencias_scored = [s for s in scored if s.tipo_candidato in TENDENCIA_TYPES]
    top_empresas = empresas_scored[: config.MAX_IDEAS_EMPRESA]
    top_tendencias = tendencias_scored[: config.MAX_IDEAS_TENDENCIA]
    top_email = top_empresas + top_tendencias

    # El reporte .md (el que se captura a GBrain) lleva TODAS las ideas con
    # análisis profundo, no solo las que pasan el gate — así el segundo cerebro
    # ve la inteligencia completa, no solo el recorte que llega por email.
    report = render(scored, total_evaluados=len(candidates), min_objetivo=config.MIN_OBJETIVO,
                    panorama=result.triage, gate_count=len(top_gate), warnings=warnings)

    out = REPORTS_DIR / f"{week_key}.md"
    out.write_text(report, encoding="utf-8")
    if scored:
        _save_seen(candidates, week_key)  # solo marca vistos si el scoring funcionó
        reset_pool()  # el pool ya fue evaluado; el job diario vuelve a llenarlo
        # Dataset completo para el segundo cerebro: TODAS las evaluaciones,
        # incluidas las descartadas — son inteligencia de mercado, no basura.
        _write_full_dataset(week_key, result, top_gate)
        _append_stats(week_key, source_counts, len(candidates), len(scored),
                      len(top_gate), result.cost_usd, themes)
    print(f"[done] {len(top_gate)} sobre gate, top-5 email: {[s.objetivo_total for s in top_email]} -> {out}")

    _capture_to_gbrain(out)

    # --- Envío de email HTML (empresas + tendencias, marcando cuáles pasaron el gate) ---
    _send_email(top_empresas, top_tendencias, passing_ids={s.url for s in top_gate},
                total_evaluados=len(scored), week=week,
                error=scoring_failed, cost_usd=result.cost_usd,
                warnings=warnings, momentum=momentum)

    return out


def _count_themes(items) -> dict[str, int]:
    """Menciones por tema de la tesis sobre todo lo fetcheado esta semana."""
    counts: dict[str, int] = {}
    for cat, kws in config.THEME_KEYWORDS.items():
        n = 0
        for it in items:
            haystack = f"{it.title} {it.text}".lower()
            if any(kw in haystack for kw in kws):
                n += 1
        counts[cat] = n
    return counts


def _theme_momentum(themes: dict[str, int]) -> list[str]:
    """Temas acelerando vs las últimas 4 semanas — la ola importa más que el número.

    Requiere ≥2 semanas de historial con temas para no dar falsos positivos.
    """
    history = [h for h in _load_stats()[-4:] if h.get("themes")]
    if len(history) < 2:
        return []
    msgs: list[str] = []
    for cat, n in themes.items():
        past = [h["themes"].get(cat, 0) for h in history]
        avg = sum(past) / len(past)
        if n >= 5 and avg > 0 and n >= 1.6 * avg:
            msgs.append(f"{cat}: {n} menciones esta semana (promedio: {avg:.0f})")
    return msgs


STATS_FILE = REPORTS_DIR / "stats.json"


def _source_health(counts: dict[str, int]) -> list[str]:
    """Detecta fuentes muertas (0 items) y caídas bruscas vs las últimas 4 semanas.

    Una fuente rota no lanza error: simplemente deja de aportar. Sin este
    chequeo, muere en silencio (le pasó a WorkLife y casi a TechInAsia).

    2pml estuvo en 0 seis semanas seguidas (2026-08) antes de que alguien lo
    notara — la alerta existía pero se repetía sin escalar, fácil de ignorar.
    Ahora una racha de 3+ semanas muertas se marca 🚨 en vez de repetir el
    mismo aviso genérico cada semana.
    """
    expected = {"hackernews", *config.RSS_FEEDS, *config.REDDIT_FEEDS}
    if config.ENABLE_YC:
        expected.add("yc")
    if config.ENABLE_PRODUCTHUNT:
        expected.add("producthunt")

    all_history = _load_stats()
    recent = all_history[-4:]
    warnings: list[str] = []
    for src in sorted(expected):
        n = counts.get(src, 0)
        if n == 0:
            streak = _dead_streak(all_history, "sources", src)
            if streak >= 3:
                warnings.append(
                    f"🚨 {src}: 0 items por {streak}+ semanas seguidas — no es un bache, "
                    "está MUERTA. Reemplazar o quitar, no solo avisar de nuevo.")
            else:
                warnings.append(f"{src}: 0 items (¿fuente muerta?)")
            continue
        past = [h["sources"].get(src, 0) for h in recent if h.get("sources")]
        if len(past) >= 2:
            avg = sum(past) / len(past)
            if avg >= 5 and n < 0.4 * avg:
                warnings.append(f"{src}: cayó a {n} items (promedio 4 semanas: {avg:.0f})")
    return warnings


def _dead_themes(themes: dict[str, int]) -> list[str]:
    """Categorías de la tesis casi sin señal por varias semanas seguidas.

    No asume que "no hay nada" — asume que el FILTRO puede estar mal
    calibrado (le pasó a "Tendencias consumo": la señal existía en
    modernretail, pero las keywords eran vocabulario de trend-report que
    ningún titular real usa — se perdía en el prefiltro, no en la fuente).
    Umbral bajo (<2) y racha larga (4+ semanas) para no generar ruido con
    variación normal semana a semana.
    """
    all_history = _load_stats()
    warnings: list[str] = []
    for cat in config.THEME_KEYWORDS:
        if themes.get(cat, 0) >= 2:
            continue
        streak = _dead_streak(all_history, "themes", cat, threshold=2)
        if streak >= 4:
            warnings.append(
                f"🚨 '{cat}': casi sin señal hace {streak}+ semanas — revisar si las "
                "keywords calzan con cómo se escribe realmente sobre esto, antes de "
                "asumir que simplemente no hay nada que reportar.")
    return warnings


def _dead_streak(history: list[dict], field: str, key: str, threshold: int = 1) -> int:
    """Semanas consecutivas (incluida la actual) con {field}[{key}] < threshold."""
    streak = 1  # la semana actual ya cumple la condición (por eso se llama esta función)
    for h in reversed(history):
        if h.get(field, {}).get(key, 0) < threshold:
            streak += 1
        else:
            break
    return streak


def _load_stats() -> list[dict]:
    if not STATS_FILE.exists():
        return []
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _append_stats(week_key: str, sources: dict[str, int], candidates: int,
                  scored: int, gate: int, cost_usd: float,
                  themes: dict[str, int] | None = None) -> None:
    stats = [s for s in _load_stats() if s.get("week") != week_key]
    stats.append({
        "week": week_key,
        "sources": sources,
        "candidates": candidates,
        "scored": scored,
        "gate": gate,
        "cost_usd": round(cost_usd, 4),
        "themes": themes or {},
    })
    STATS_FILE.write_text(json.dumps(stats[-52:], ensure_ascii=False, indent=1),
                          encoding="utf-8")


def _write_full_dataset(week_key: str, result, top_gate) -> None:
    """JSON con todas las evaluaciones de la semana — insumo para GBrain."""
    out = REPORTS_DIR / f"{week_key}-full.json"
    out.write_text(json.dumps({
        "week": week_key,
        "triage": result.triage,
        "deep": [s.model_dump(mode="json") for s in result.deep],
        "gate_urls": [s.url for s in top_gate],
        "cost_usd": round(result.cost_usd, 4),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def _capture_to_gbrain(report_path: Path) -> None:
    gbrain = os.path.expanduser("~/.bun/bin/gbrain")
    if not os.path.exists(gbrain):
        return
    try:
        result = subprocess.run(
            [gbrain, "capture", "--file", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"[gbrain] capturado: {report_path.name}")
        else:
            print(f"[gbrain] error: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        print("[gbrain] timeout al capturar reporte")
    except Exception as e:
        print(f"[gbrain] no disponible: {e}")


def _send_email(empresas: list, tendencias: list, passing_ids: set, total_evaluados: int,
                week: int, error: bool = False, cost_usd: float = 0.0,
                warnings: list[str] | None = None,
                momentum: list[str] | None = None) -> None:
    html = render_html(empresas, tendencias, passing_ids=passing_ids,
                       total_evaluados=total_evaluados, min_objetivo=config.MIN_OBJETIVO,
                       error=error, cost_usd=cost_usd,
                       warnings=warnings or [], momentum=momentum or [])
    n_passed = len(passing_ids)
    if error:
        subject = f"⚠️ Scouting Semanal — Semana {week} · falló el scoring, revisar logs"
    else:
        subject = (
            f"🔍 Scouting Semanal — Semana {week} · "
            f"{n_passed} idea{'s' if n_passed != 1 else ''} sobre el gate · "
            f"{len(empresas)} empresa{'s' if len(empresas) != 1 else ''} · "
            f"{len(tendencias)} tendencia{'s' if len(tendencias) != 1 else ''}"
        )
    send_html(subject, html)


if __name__ == "__main__":
    run()
