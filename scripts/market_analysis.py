#!/usr/bin/env python3
"""Procesa TODA la cola de scouting_market_analysis (status='queued') —
metodología de 8 pasos (beachhead, TAM bottom-up+top-down, Porter, JTBD,
WTP, fit fundador, RAT, regulación). Ver prompts/market_analysis.md.

Disparo siempre MANUAL (Matías o Claude Code vía `gh workflow run`) —
nunca automático ni programado. Procesa todo lo que esté en cola en una
sola corrida (Matías: "quiero correrlas todas de una").

No usa Batch API a propósito: son pocas corridas, poco frecuentes, y la
confiabilidad de la búsqueda web agentica importa más acá que el 50% de
descuento — mismo tradeoff que ya documentó dashboard/deep_single.py para
el análisis on-demand (usuario esperando, no corrida masiva).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from anthropic import Anthropic  # noqa: E402

from json_repair import repair_json  # noqa: E402

from dashboard.db import fetch_market_analyses, update_market_analysis  # noqa: E402
from src import config  # noqa: E402
from src.pipeline.score import _call_direct, web_search_tool  # noqa: E402

PROMPTS_DIR = REPO / "prompts"
MAX_SEARCHES = 15  # bastante más que el deep semanal (4) — 8 pasos con verificación real
MAX_TOKENS = 6000  # 13 campos con evidencia embebida, no resúmenes cortos
RUN_COST_CEILING = 8.0  # guardrail de seguridad para esta corrida completa, no por-análisis

OUTPUT_FIELDS = [
    "beachhead_definido", "tam_bottom_up", "tam_top_down", "discrepancia_tam",
    "competencia_global", "competencia_local", "competencia_en_beachhead_especifico",
    "dolor_jtbd", "wtp_estimado", "wtp_validado", "fit_fundador",
    "rat_supuesto", "rat_prueba_barata", "regulacion",
]


def _founder_context() -> str:
    """Extrae SOLO la sección de contexto del fundador de score.md (entre
    '# Tesis del fundador' y la siguiente regla dura sobre madurez) — no
    duplica el prompt entero, no vive un texto paralelo separado que se
    puede desincronizar."""
    text = (PROMPTS_DIR / "score.md").read_text(encoding="utf-8")
    start_marker = "# Tesis del fundador"
    end_marker = "**Regla dura sobre madurez"
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        print("[market] ⚠️ no encontré los marcadores de contexto del fundador en "
              "score.md — score.md se debe haber reestructurado. Usando fallback mínimo.")
        return ("# Contexto del fundador\n\nMatías Möller, 31, Sales Ops en Mercado "
                "Pago Chile, perfil comercial, usa IA para construir MVPs.")
    return text[start:end].strip()


def build_system() -> str:
    template = (PROMPTS_DIR / "market_analysis.md").read_text(encoding="utf-8")
    return template.replace("{FOUNDER_CONTEXT}", _founder_context())


def _parse_object(text: str) -> dict | None:
    """Extrae el objeto JSON de la respuesta — misma disciplina que
    score.py's _loads_forgiving pero para un objeto {...}, no un array
    (el modelo devuelve un solo objeto acá, no una lista de candidatos)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    raw = text[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(repair_json(raw))
        except Exception:
            return None
    return data if isinstance(data, dict) else None


def build_user(row: dict) -> str:
    parts = [f"Mercado/oportunidad a analizar: {row['market_name']}"]
    if row.get("empresas_referentes"):
        parts.append(
            f"Empresas de referencia (ilustran que el mercado existe — el "
            f"análisis es del MERCADO, no de estas empresas puntuales): "
            f"{row['empresas_referentes']}"
        )
    if row.get("beachhead_hint"):
        parts.append(
            f"\nHipótesis de beachhead YA discutida con el fundador (partí de "
            f"acá, validala/refinala con datos — ver Paso 1):\n{row['beachhead_hint']}"
        )
    if row.get("context_note"):
        parts.append(f"\nContexto adicional del fundador:\n{row['context_note']}")
    return "\n".join(parts)


def main() -> None:
    queue = [r for r in fetch_market_analyses() if r["status"] == "queued"]
    if not queue:
        print("[market] cola vacía — nada que procesar")
        return
    print(f"[market] {len(queue)} en cola: {[r['market_name'] for r in queue]}")

    system = build_system()
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    tools = web_search_tool(MAX_SEARCHES)

    total_cost = 0.0
    for row in queue:
        if total_cost >= RUN_COST_CEILING:
            print(f"[market] GUARDRAIL: ${total_cost:.2f} ≥ ${RUN_COST_CEILING} — "
                  f"se aborta el resto de la cola ({row['market_name']} y siguientes quedan 'queued')")
            break

        print(f"\n[market] === {row['market_name']} (id={row['id']}) ===")
        update_market_analysis(row["id"], status="analizando")
        user = build_user(row)
        try:
            text, cost, truncated = _call_direct(
                client, config.MODEL_DEEP, system, user,
                max_tokens=MAX_TOKENS, tools=tools, log_prefix="[market]",
            )
            total_cost += cost
            obj = _parse_object(text)
            if not obj:
                raise ValueError(f"respuesta no parseable como objeto: {text[:300]!r}")
            fields = {k: obj.get(k, "") for k in OUTPUT_FIELDS}
            fields["wtp_validado"] = ""  # nunca lo llena el análisis automático, ver Paso 5
            update_market_analysis(
                row["id"], status="listo", cost_usd=round(cost, 4),
                completed_at=datetime.now(timezone.utc).isoformat(), **fields,
            )
            print(f"[market] ✅ listo — costo=${cost:.4f}"
                  f"{' (truncado, revisar)' if truncated else ''}")
        except Exception as e:  # noqa: BLE001 — un error no debe tumbar el resto de la cola
            print(f"[market] ❌ error en '{row['market_name']}': {e}")
            update_market_analysis(row["id"], status="error", error_detail=str(e)[:2000])
        time.sleep(2)  # cortesía con rate limits entre análisis pesados

    print(f"\n[market] === COSTO TOTAL DE LA CORRIDA: ${total_cost:.4f} ===")


if __name__ == "__main__":
    main()
