#!/usr/bin/env python3
"""Corrida MENSUAL del Oracle: minería de necesidades por país × lente →
chequeo de fuentes → consejo de críticos → Vault (Supabase, privado).

Agenda: src/oracle/matrix.py decide qué combinaciones tocan este mes (17 países,
11 lentes, frecuencia por lente, matriz parcial). Todo va por Batch API (-50% en
tokens); las búsquedas web no llevan descuento.

Privacidad: el repo y los logs de Actions son PÚBLICOS. Este script nunca imprime
contenido de semillas ni lessons, solo conteos y costos. La materia prima interna
de Matías (GBrain) NO entra acá — solo fuentes públicas.

Uso:
  python -m scripts.oracle_run --dry-run              # agenda + costo estimado, sin API
  python -m scripts.oracle_run --tag test --max-pairs 6   # humo chico, no bloquea el mes real
  python -m scripts.oracle_run                        # corrida real del mes actual
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.oracle.matrix import (  # noqa: E402
    COUNTRIES, LENS_BY_KEY, SENALES_OFERTA, due_pairs, month_index,
)

PROMPTS = REPO / "prompts"
SEARCHES_PER_PAIR = 2            # supuesto de costo/precisión — el canario lo calibra
MINING_MAX_TOKENS = 12000        # holgado: el razonamiento de Sonnet cuenta acá
COUNCIL_MAX_TOKENS = 16000
COUNCIL_CHUNK = 8                # semillas por llamada (el canario v2 truncó con 20)
VAULT_THRESHOLD = 6.0
MONTH_COST_CEILING = 9.0         # guardrail de la corrida completa
MAX_DIRECT_FALLBACK = 8
DEFAULT_MODEL = "claude-sonnet-5"
# Costo estimado por combinación con Batch y 2 búsquedas — medido en el canario v2.
EST_PAIR_COST = {"sonnet": 0.065, "haiku": 0.035}
WEIGHTS = {"evidencia_necesidad": 0.30, "tamano_gravedad": 0.20, "por_que_ahora": 0.20,
           "hueco_vs_incumbentes": 0.20, "testeabilidad": 0.10}
SENALES_VALIDAS = {"queja", "brecha", "fuerza_externa", "oferta"}


MAX_FEEDBACK_PER_KIND = 5


def lens_feedback() -> dict[str, str]:
    """Bloque de feedback del fundador por lente, armado con sus veredictos reales
    (Vault). Afina QUÉ se busca en cada lente: más de lo que le interesó, menos de
    lo que descartó y por qué. Nunca se imprime (los logs de Actions son públicos)."""
    from dashboard.db import fetch_verdicts
    by_lens: dict[str, dict[str, list[str]]] = {}
    for v in fetch_verdicts():
        kind = "interes" if v["human_verdict"] in ("elegida", "guardada") else "descarte"
        bucket = by_lens.setdefault(v["lens"], {"interes": [], "descarte": []})
        if len(bucket[kind]) < MAX_FEEDBACK_PER_KIND:
            reason = f" — motivo: {v['human_reason']}" if v.get("human_reason") else ""
            bucket[kind].append(f"- ({v['country']}) {v['necesidad'][:110]}{reason}")
    out = {}
    for lens, b in by_lens.items():
        parts = []
        if b["interes"]:
            parts.append("Le INTERESÓ (buscá más de este tipo):\n" + "\n".join(b["interes"]))
        if b["descarte"]:
            parts.append("DESCARTÓ (evitá este tipo, salvo evidencia nueva):\n" + "\n".join(b["descarte"]))
        out[lens] = ("\nFeedback previo del fundador sobre ESTE lente — usalo para afinar qué buscás. "
                     "Los motivos reflejan sus intereses, no su falta de experiencia:\n" + "\n".join(parts))
    return out


def mining_user(cc: str, lens_key: str, feedback: str = "") -> str:
    name, _ = COUNTRIES[cc]
    lens = LENS_BY_KEY[lens_key]
    extra = ("\nPriorizá señales de tipo 'oferta' (qué se financia, lanza y crece): las quejas "
             "locales de este país son poco accesibles." if cc in SENALES_OFERTA else "")
    return (f"País: {name}\nLente: {lens.name}\nDefinición del lente: {lens.definition}{extra}\n"
            f"Buscá las necesidades más fuertes y recientes (últimos 12 meses). "
            f"Una sola URL por necesidad: la mejor fuente, completa.{feedback}")


def first_url(raw: str) -> str:
    for tok in re.split(r"\s+", (raw or "").strip()):
        tok = tok.strip("|;,/()")
        if tok.startswith("http"):
            return tok
    return ""


def dedupe_key(country: str, lens: str, necesidad: str) -> str:
    norm = re.sub(r"\W+", " ", necesidad.lower()).strip()[:100]
    return hashlib.sha1(f"{country}|{lens}|{norm}".encode()).hexdigest()


def url_states(urls: list[str]) -> dict[str, str]:
    """ok | bloqueada (inconclusa: el sitio bloquea IPs de cloud) | rota | sin_url."""
    import httpx
    from concurrent.futures import ThreadPoolExecutor

    def chk(u: str) -> tuple[str, str]:
        if not u:
            return u, "sin_url"
        try:
            r = httpx.get(u, timeout=10, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (scouting-agent oracle)"})
        except Exception:  # noqa: BLE001
            return u, "rota"
        if r.status_code < 400:
            return u, "ok"
        return u, "bloqueada" if r.status_code in (401, 403, 406, 429, 999) else "rota"

    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(chk, urls))


def mine(client, pairs, model: str, effort: str | None, month_key: str) -> tuple[list[dict], float, Counter]:
    from scripts.market_analysis import _parse_object
    from src.oracle.batch import direct_call, make_request, run_batch
    from src.pipeline.score import web_search_tool

    system = (PROMPTS / "oracle_mining.md").read_text(encoding="utf-8")
    tools = web_search_tool(SEARCHES_PER_PAIR)
    fb = lens_feedback()
    reqs = [make_request(f"{cc}-{lk}", model, system,
                         mining_user(cc, lk, fb.get(LENS_BY_KEY[lk].name, "")), MINING_MAX_TOKENS,
                         tools, effort) for cc, lk in pairs]
    res = run_batch(client, reqs, log_prefix="[oracle:minería]")

    stats: Counter = Counter()
    failed = [r for r in reqs if "error" in res.get(r["custom_id"], {"error": "faltante"})]
    for r in failed[:MAX_DIRECT_FALLBACK]:
        try:
            res[r["custom_id"]] = direct_call(client, r)
            stats["reintento_directo_ok"] += 1
        except Exception as e:  # noqa: BLE001
            res[r["custom_id"]] = {"error": type(e).__name__}
    cost = sum(v.get("cost", 0.0) for v in res.values())

    rows: list[dict] = []
    for cc, lk in pairs:
        r = res.get(f"{cc}-{lk}", {"error": "faltante"})
        if "error" in r:
            stats["pares_fallidos"] += 1
            continue
        if r.get("truncated"):
            stats["truncados"] += 1
        obj = _parse_object(r["text"]) or {}
        items = obj.get("necesidades", []) if isinstance(obj, dict) else []
        if not items:
            stats["sin_necesidades"] += 1
        country, lens_name = COUNTRIES[cc][0], LENS_BY_KEY[lk].name
        for it in items[:3]:
            nec = (it.get("necesidad") or "").strip()
            if not nec:
                continue
            tipo = (it.get("tipo_senal") or "").strip().lower()
            rows.append({
                "run_month": month_key, "country": country, "lens": lens_name,
                "tipo_senal": tipo if tipo in SENALES_VALIDAS else None,
                "necesidad": nec, "quien": it.get("quien"), "evidencia": it.get("evidencia"),
                "fuente_url": first_url(it.get("fuente_url", "")),
                "solucion_existente": it.get("solucion_existente"),
                "transferencia": it.get("transferencia_chile_latam"),
                "modelo": model, "dedupe_key": dedupe_key(country, lens_name, nec),
            })
    states = url_states(sorted({r["fuente_url"] for r in rows}))
    for r in rows:
        r["url_estado"] = states.get(r["fuente_url"], "sin_url")
    stats["semillas"] = len(rows)
    return rows, cost, stats


def _as_float(x) -> float:
    """Puntajes del modelo: tolera '7', '7/10', None — un formato raro no debe tumbar la corrida."""
    try:
        return float(str(x).split("/")[0].strip())
    except (TypeError, ValueError):
        return 0.0


def _as_int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def lessons_block() -> str:
    from dashboard.db import fetch_lessons
    ls = fetch_lessons(25)
    if not ls:
        return "Veredictos previos del fundador: todavía no hay ninguno."
    lines = [f"- [{l['verdict'].upper()}] {(l.get('seed_snapshot') or '')[:140]} — motivo: "
             f"{l.get('reason') or 'sin motivo'}" for l in ls]
    return ("Veredictos previos del fundador, el más reciente primero. Usalos para calibrar su "
            "GUSTO e intereses; NO para penalizar falta de experiencia (eso sigue prohibido):\n"
            + "\n".join(lines))


def council(client, model: str, effort: str | None) -> tuple[int, float, Counter]:
    from dashboard.db import fetch_vault_status, update_vault
    from scripts.market_analysis import _founder_context, _parse_object
    from src.oracle.batch import direct_call, make_request, run_batch

    seeds = fetch_vault_status("nueva")
    stats: Counter = Counter()
    if not seeds:
        return 0, 0.0, stats
    system = ((PROMPTS / "oracle_council.md").read_text(encoding="utf-8")
              .replace("{FOUNDER_CONTEXT}", _founder_context())
              .replace("{LESSONS}", lessons_block()))
    chunks = [seeds[i:i + COUNCIL_CHUNK] for i in range(0, len(seeds), COUNCIL_CHUNK)]

    def brief(s: dict) -> str:
        url = {"ok": "resuelve (ok)", "bloqueada": "no verificable (el sitio bloquea)",
               "rota": "NO resuelve — tratá la evidencia como NO verificable",
               "sin_url": "sin URL — tratá la evidencia como NO verificable"}.get(s.get("url_estado"), "?")
        return (f"[{s['id']}] ({s['country']} × {s['lens']}) NECESIDAD: {s['necesidad']}\n"
                f"Quién: {s.get('quien')}\nTipo de señal: {s.get('tipo_senal')}\n"
                f"Evidencia: {s.get('evidencia')}\nFuente citada: {url}\n"
                f"Solución existente: {s.get('solucion_existente')}\n"
                f"Transferencia a Chile/LatAm: {s.get('transferencia')}")

    reqs = [make_request(f"c{i}", model, system, "\n\n".join(brief(s) for s in ch),
                         COUNCIL_MAX_TOKENS, None, effort) for i, ch in enumerate(chunks)]
    res = run_batch(client, reqs, log_prefix="[oracle:consejo]")
    for r in [r for r in reqs if "error" in res.get(r["custom_id"], {"error": "x"})][:4]:
        try:
            res[r["custom_id"]] = direct_call(client, r)
        except Exception as e:  # noqa: BLE001
            res[r["custom_id"]] = {"error": type(e).__name__}
    cost = sum(v.get("cost", 0.0) for v in res.values())

    by_id = {s["id"]: s for s in seeds}
    for i, ch in enumerate(chunks):
        r = res.get(f"c{i}", {"error": "faltante"})
        if "error" in r:
            stats["chunks_fallidos"] += 1
            continue
        if r.get("truncated"):
            stats["chunks_truncados"] += 1
        obj = _parse_object(r["text"]) or {}
        for v in obj.get("semillas", []) if isinstance(obj, dict) else []:
            sid = _as_int(v.get("id"))
            if sid not in by_id:
                continue
            num = lambda k: _as_float(v.get(k))  # noqa: E731
            score = sum(num(k) * w for k, w in WEIGHTS.items()) + min(max(num("bonus_fit"), 0.0), 1.0)
            update_vault(
                sid, s_evidencia=num("evidencia_necesidad"), s_tamano=num("tamano_gravedad"),
                s_ahora=num("por_que_ahora"), s_hueco=num("hueco_vs_incumbentes"),
                s_testeabilidad=num("testeabilidad"), bonus_fit=min(max(num("bonus_fit"), 0.0), 1.0),
                score=round(score, 2), objeciones=" | ".join(v.get("objeciones") or []),
                veredicto_consejo=v.get("veredicto"),
                status="en_vault" if score >= VAULT_THRESHOLD else "descartada_consejo",
            )
            stats["puntuadas"] += 1
            stats["en_vault" if score >= VAULT_THRESHOLD else "descartadas"] += 1
    return stats["puntuadas"], cost, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="agenda y costo estimado, sin API ni DB")
    ap.add_argument("--month", help="YYYY-MM (por defecto el mes actual, UTC)")
    ap.add_argument("--tag", default="", help="sufijo del run (ej: test) — no bloquea el mes real")
    ap.add_argument("--max-pairs", type=int, default=0, help="limita combinaciones (pruebas)")
    ap.add_argument("--force", action="store_true", help="correr aunque el mes ya esté 'listo'")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    y, m = (int(x) for x in args.month.split("-")) if args.month else (now.year, now.month)
    month_key = f"{y}-{m:02d}" + (f"-{args.tag}" if args.tag else "")
    mining_model = os.environ.get("SCOUTING_MODEL_MINING", DEFAULT_MODEL)
    council_model = os.environ.get("SCOUTING_MODEL_COUNCIL", DEFAULT_MODEL)
    effort = os.environ.get("ORACLE_EFFORT", "medium") or None

    pairs = sorted(due_pairs(month_index(y, m)))
    if args.max_pairs:
        # Muestra REPARTIDA (mezcla fija), no las primeras N por orden alfabético: la
        # corrida de humo del 2026-09-19 tomó las primeras 6 y fueron todas Argentina.
        random.Random(7).shuffle(pairs)
        pairs = sorted(pairs[: args.max_pairs])
    kind = "haiku" if "haiku" in mining_model else "sonnet"
    est = len(pairs) * EST_PAIR_COST[kind]
    print(f"[oracle] {month_key}: {len(pairs)} combinaciones — minería {mining_model}, "
          f"consejo {council_model}, effort={effort}, costo estimado minería ≈ ${est:.2f} "
          f"(+ consejo ≈ ${len(pairs) * 0.01:.2f})")
    if args.dry_run:
        print("[oracle] por país:", dict(Counter(COUNTRIES[c][0] for c, _ in pairs)))
        print("[oracle] por lente:", dict(Counter(LENS_BY_KEY[l].name for _, l in pairs)))
        return
    if est > MONTH_COST_CEILING:
        raise SystemExit(f"[oracle] estimado ${est:.2f} > tope ${MONTH_COST_CEILING} — abortado")

    from anthropic import Anthropic
    from dashboard.db import get_oracle_run, insert_vault_seeds, save_oracle_run
    from src import config
    from src.oracle.batch import effort_supported

    run = get_oracle_run(month_key)
    if run and run["status"] == "listo" and not args.force:
        print(f"[oracle] {month_key} ya está 'listo' (costo ${run.get('cost_usd')}) — nada que hacer")
        return
    save_oracle_run(month_key, status="corriendo", pairs=len(pairs),
                    started_at=now.isoformat())
    try:
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        if effort and not (effort_supported(client, mining_model, effort)
                           and effort_supported(client, council_model, effort)):
            effort = None
        rows, mining_cost, mstats = mine(client, pairs, mining_model, effort, month_key)
        insert_vault_seeds(rows)
        print(f"[oracle] minería: {dict(mstats)} costo=${mining_cost:.4f}")
        council_cost = 0.0
        cstats: Counter = Counter()
        if mining_cost < MONTH_COST_CEILING:
            _, council_cost, cstats = council(client, council_model, effort)
        else:
            print("[oracle] GUARDRAIL: minería pasó el tope — se omite el consejo")
        total = mining_cost + council_cost
        print(f"[oracle] consejo: {dict(cstats)} costo=${council_cost:.4f}")
        print(f"[oracle] === COSTO TOTAL {month_key}: ${total:.4f} ===")
        save_oracle_run(month_key, status="listo", seeds=len(rows), cost_usd=round(total, 4),
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        note=f"minería={dict(mstats)} consejo={dict(cstats)}"[:500])
    except Exception as e:  # noqa: BLE001
        save_oracle_run(month_key, status="error", note=f"{type(e).__name__}: {str(e)[:300]}",
                        finished_at=datetime.now(timezone.utc).isoformat())
        raise


if __name__ == "__main__":
    main()
