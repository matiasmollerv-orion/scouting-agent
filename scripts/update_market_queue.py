#!/usr/bin/env python3
"""Edita campos de encolado (market_name/empresas_referentes/beachhead_hint/
context_note) de UNA fila existente de scouting_market_analysis, vía inputs
de GitHub Actions — mismo canal/patrón que queue_market_analysis.py, para
corregir texto ANTES de correr el análisis caro, sin tocar Supabase a mano.
No toca nada si la fila ya no está en 'queued' (evita pisar un análisis en
curso o ya terminado por error).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dashboard.db import fetch_market_analyses, update_market_analysis  # noqa: E402

EDITABLE_FIELDS = ("market_name", "empresas_referentes", "beachhead_hint", "context_note")


def main() -> None:
    market_id = int(os.environ["MARKET_ID"])
    row = next((r for r in fetch_market_analyses() if r["id"] == market_id), None)
    if row is None:
        raise SystemExit(f"[update] no existe fila id={market_id}")
    if row["status"] != "queued":
        raise SystemExit(
            f"[update] fila id={market_id} está en status={row['status']!r}, "
            f"no 'queued' — abortado para no pisar un análisis en curso/listo."
        )

    fields = {k: os.environ[f"NEW_{k.upper()}"] for k in EDITABLE_FIELDS if os.environ.get(f"NEW_{k.upper()}")}
    if not fields:
        raise SystemExit("[update] no se pasó ningún campo nuevo — nada que hacer")

    update_market_analysis(market_id, **fields)
    print(f"[update] id={market_id} actualizado: {sorted(fields.keys())}")


if __name__ == "__main__":
    main()
