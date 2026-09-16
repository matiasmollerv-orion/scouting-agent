#!/usr/bin/env python3
"""Encola UN mercado/oportunidad para análisis, vía inputs de GitHub Actions
— el canal para que Matías le dé una empresa/mercado a Claude Code directo
en el chat ("te debo poder entregar la empresa por acá") sin que Claude
toque la key de Supabase ni la de Anthropic. Solo encola (status='queued');
no analiza nada — eso lo hace scripts/market_analysis.py, siempre aparte.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dashboard.db import queue_market_analysis  # noqa: E402


def main() -> None:
    market_name = os.environ["MARKET_NAME"]
    empresas_referentes = os.environ.get("EMPRESAS_REFERENTES", "")
    beachhead_hint = os.environ.get("BEACHHEAD_HINT", "")
    context_note = os.environ.get("CONTEXT_NOTE", "")

    queue_market_analysis(
        market_name=market_name, empresas_referentes=empresas_referentes,
        origen="chat", beachhead_hint=beachhead_hint, context_note=context_note,
    )
    print(f"[queue] encolado: {market_name!r} (origen=chat)")


if __name__ == "__main__":
    main()
