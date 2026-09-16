#!/usr/bin/env python3
"""Lista TODAS las filas de scouting_market_analysis (id, status, market_name)
— solo lectura, para poder apuntar update_market_queue.py a un id concreto sin
tener que abrir el dashboard. Nunca imprime ni toca contenido sensible.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dashboard.db import fetch_market_analyses  # noqa: E402


def main() -> None:
    rows = fetch_market_analyses()
    if not rows:
        print("[list] cola vacía")
        return
    for r in rows:
        print(f"[row] id={r['id']} status={r['status']} market_name={r['market_name']!r}")


if __name__ == "__main__":
    main()
