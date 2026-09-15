#!/usr/bin/env python3
"""Encola UNA empresa/mercado para análisis, vía inputs de GitHub Actions —
el canal para que Matías le dé una empresa a Claude Code directo en el chat
("te debo poder entregar la empresa por acá") sin que Claude toque la
key de Supabase ni la de Anthropic. Solo encola (status='queued'); no
analiza nada — eso lo hace scripts/market_analysis.py, siempre aparte.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dashboard.db import queue_market_analysis  # noqa: E402


def main() -> None:
    company_name = os.environ["COMPANY_NAME"]
    company_url = os.environ.get("COMPANY_URL", "")
    beachhead_hint = os.environ.get("BEACHHEAD_HINT", "")
    context_note = os.environ.get("CONTEXT_NOTE", "")

    queue_market_analysis(
        company_name=company_name, company_url=company_url,
        origen="chat", beachhead_hint=beachhead_hint, context_note=context_note,
    )
    print(f"[queue] encolada: {company_name!r} (origen=chat)")


if __name__ == "__main__":
    main()
