#!/usr/bin/env python3
"""Test de consistencia: evalúa UN candidato solo, sin nada al lado, para
verificar si el score cambia por el contexto del lote o por otra razón.
Caso: Frida (modernretail) puntuó 13/40 en un lote de 25, y 10/40 en un
lote de 35 — ¿es el lote, o es variación real del modelo?
"""
from __future__ import annotations

import sys
from pathlib import Path

import feedparser

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.models import Item  # noqa: E402
from src.pipeline.score import score  # noqa: E402

TARGET_URL_FRAGMENT = "frida-aims-to-solve-personal-care-gap"


def find_frida() -> Item | None:
    parsed = feedparser.parse("https://www.modernretail.co/feed/?paged=8")
    for e in parsed.entries:
        if TARGET_URL_FRAGMENT in e.get("link", ""):
            return Item(source="modernretail", title=e.get("title", ""),
                        url=e.get("link", ""), text=e.get("summary", "")[:2000])
    return None


def main() -> None:
    item = find_frida()
    if not item:
        print("No se encontró Frida en la página probada — probando páginas cercanas...")
        for p in (6, 7, 9, 10):
            parsed = feedparser.parse(f"https://www.modernretail.co/feed/?paged={p}")
            for e in parsed.entries:
                if TARGET_URL_FRAGMENT in e.get("link", ""):
                    item = Item(source="modernretail", title=e.get("title", ""),
                                url=e.get("link", ""), text=e.get("summary", "")[:2000])
                    break
            if item:
                break
    if not item:
        print("No se pudo encontrar Frida. Abortando.")
        return

    print(f"Item encontrado: {item.title}")
    print(f"Texto ({len(item.text)} chars): {item.text[:300]}...\n")

    for run in (1, 2, 3):
        result = score([item])
        if result.deep:
            s = result.deep[0]
            print(f"--- Corrida {run} (sola, sin nada al lado) ---")
            print(f"  Score: {s.objetivo_total}/40 (problema={s.problema_score}, barrera={s.barrera_score})")
            print(f"  fit_tesis: {s.fit_tesis}")
            print(f"  resumen: {s.resumen}")
            print(f"  costo: ${result.cost_usd:.4f}\n")
        else:
            print(f"--- Corrida {run}: sin resultado válido ---\n")


if __name__ == "__main__":
    main()
