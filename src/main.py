from __future__ import annotations

import json
import os
import smtplib
import ssl
import subprocess
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from . import config
from .models import RawItem
from .pipeline.normalize import normalize
from .pipeline.pool import load_pool_items, reset_pool
from .pipeline.prefilter import prefilter
from .pipeline.score import score
from .render.email import render_html
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

    # Fetch fresco + pool acumulado por el job diario (prefilter dedup-ea).
    pool_items = load_pool_items()
    print(f"[pool] {len(pool_items)} items acumulados durante la semana")

    merged = normalize(raw) + pool_items
    source_counts: dict[str, int] = {}
    for it in merged:
        source_counts[it.source] = source_counts.get(it.source, 0) + 1

    warnings = _source_health(source_counts)
    for w in warnings:
        print(f"[salud] {w}")

    candidates = prefilter(merged, seen_urls=_load_seen(week_key))
    print(f"[prefilter] {len(candidates)} candidatos a Claude")

    result = score(candidates)
    scored = result.deep
    scored.sort(key=lambda s: s.objetivo_total, reverse=True)
    scoring_failed = bool(candidates) and not scored

    # Ideas que pasaron el gate (para el reporte Markdown del repo)
    passing = [s for s in scored if s.passes_gate(config.MIN_OBJETIVO)]
    top_gate = passing[: config.MAX_IDEAS]

    # Top 5 por score para el email (con o sin gate — siempre hay algo que ver)
    top_email = scored[: config.MAX_IDEAS]

    report = render(top_gate, total_evaluados=len(scored), min_objetivo=config.MIN_OBJETIVO,
                    panorama=result.triage)

    out = REPORTS_DIR / f"{week_key}.md"
    out.write_text(report, encoding="utf-8")
    if scored:
        _save_seen(candidates, week_key)  # solo marca vistos si el scoring funcionó
        reset_pool()  # el pool ya fue evaluado; el job diario vuelve a llenarlo
        # Dataset completo para el segundo cerebro: TODAS las evaluaciones,
        # incluidas las descartadas — son inteligencia de mercado, no basura.
        _write_full_dataset(week_key, result, top_gate)
        _append_stats(week_key, source_counts, len(candidates), len(scored),
                      len(top_gate), result.cost_usd)
    print(f"[done] {len(top_gate)} sobre gate, top-5 email: {[s.objetivo_total for s in top_email]} -> {out}")

    _capture_to_gbrain(out)

    # --- Envío de email HTML (siempre top 5, marcando cuáles pasaron el gate) ---
    _send_email(top_email, passing_ids={s.url for s in top_gate},
                total_evaluados=len(scored), week=week,
                error=scoring_failed, cost_usd=result.cost_usd,
                warnings=warnings)

    return out


STATS_FILE = REPORTS_DIR / "stats.json"


def _source_health(counts: dict[str, int]) -> list[str]:
    """Detecta fuentes muertas (0 items) y caídas bruscas vs las últimas 4 semanas.

    Una fuente rota no lanza error: simplemente deja de aportar. Sin este
    chequeo, muere en silencio (le pasó a WorkLife y casi a TechInAsia).
    """
    expected = {"hackernews", *config.RSS_FEEDS, *config.REDDIT_FEEDS}
    if config.ENABLE_YC:
        expected.add("yc")
    if config.ENABLE_PRODUCTHUNT:
        expected.add("producthunt")

    history = _load_stats()[-4:]
    warnings: list[str] = []
    for src in sorted(expected):
        n = counts.get(src, 0)
        if n == 0:
            warnings.append(f"{src}: 0 items (¿fuente muerta?)")
            continue
        past = [h["sources"].get(src, 0) for h in history if h.get("sources")]
        if len(past) >= 2:
            avg = sum(past) / len(past)
            if avg >= 5 and n < 0.4 * avg:
                warnings.append(f"{src}: cayó a {n} items (promedio 4 semanas: {avg:.0f})")
    return warnings


def _load_stats() -> list[dict]:
    if not STATS_FILE.exists():
        return []
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _append_stats(week_key: str, sources: dict[str, int], candidates: int,
                  scored: int, gate: int, cost_usd: float) -> None:
    stats = [s for s in _load_stats() if s.get("week") != week_key]
    stats.append({
        "week": week_key,
        "sources": sources,
        "candidates": candidates,
        "scored": scored,
        "gate": gate,
        "cost_usd": round(cost_usd, 4),
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


def _send_email(top, passing_ids: set, total_evaluados: int, week: int,
                error: bool = False, cost_usd: float = 0.0,
                warnings: list[str] | None = None) -> None:
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        print("[email] GMAIL_USER / GMAIL_APP_PASSWORD no configuradas — se omite el envío")
        return

    html = render_html(top, passing_ids=passing_ids, total_evaluados=total_evaluados,
                       min_objetivo=config.MIN_OBJETIVO, error=error, cost_usd=cost_usd,
                       warnings=warnings or [])
    n_passed = len(passing_ids)
    if error:
        subject = f"⚠️ Scouting Semanal — Semana {week} · falló el scoring, revisar logs"
    else:
        subject = (
            f"🔍 Scouting Semanal — Semana {week} · "
            f"{n_passed} idea{'s' if n_passed != 1 else ''} sobre el gate · top {len(top)} mostradas"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = formataddr(("Scouting Semanal", config.GMAIL_USER))
    msg["To"]      = config.EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_USER, [config.EMAIL_TO], msg.as_string())
        print(f"[email] enviado a {config.EMAIL_TO}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"[email] error de autenticación Gmail: {e}")
    except Exception as e:
        print(f"[email] error SMTP: {e}")


if __name__ == "__main__":
    run()
