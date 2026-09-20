#!/usr/bin/env python3
"""Diagnóstico de favoritas: prueba el ciclo completo contra Supabase (leer, agregar,
leer, quitar) con una fila de prueba que se borra. Solo imprime OK/error por paso."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dashboard.db import add_favorite, fetch_favorites, remove_favorite  # noqa: E402

TEST_URL = "https://diagnostico.invalid/favorita-de-prueba"


def step(name, fn):
    try:
        out = fn()
        print(f"[fav] OK    {name}" + (f" -> {out}" if out is not None else ""))
        return True, out
    except Exception as e:  # noqa: BLE001
        print(f"[fav] ERROR {name}: {type(e).__name__}: {str(e)[:300]}")
        return False, None


def main() -> None:
    step("leer tabla scouting_favorites", lambda: f"{len(fetch_favorites())} filas")
    step("agregar favorita de prueba", lambda: add_favorite(TEST_URL, "prueba"))
    ok, present = step("leer y confirmar que aparece", lambda: TEST_URL in fetch_favorites())
    step("quitar favorita de prueba", lambda: remove_favorite(TEST_URL))
    step("confirmar que ya no está", lambda: TEST_URL not in fetch_favorites())


if __name__ == "__main__":
    main()
