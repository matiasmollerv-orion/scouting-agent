#!/usr/bin/env python3
"""Consulta ad-hoc: backfill de ~4 semanas para las fuentes agregadas esta
semana (2026-08-29 a 2026-09-05), más allá del lookback normal de 7 días.
Como son fuentes nuevas, el pool diario recién las viene fetcheando desde
que se agregaron — no hay 4 semanas de historial acumulado todavía. Se
re-fetchea cada una con paginación WordPress (?paged=N) donde exista;
si la fuente no soporta paginación, simplemente devuelve la misma página 1
varias veces y _dedup() lo colapsa sin costo.

No usa filtro de keywords (la arquitectura de este año ya no lo tiene —
el juicio de relevancia es 100% de Haiku en el triage). No toca estado
persistente (seen_urls, pool, stats, email) — solo imprime al log.
"""
from __future__ import annotations

import sys
from pathlib import Path

import feedparser

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.pipeline.normalize import normalize  # noqa: E402
from src.pipeline.prefilter import _dedup  # noqa: E402
from src.pipeline.score import score  # noqa: E402
from src.models import RawItem  # noqa: E402

# Fuentes agregadas 2026-08-29..09-05, con la URL base de su feed. 4 páginas
# alcanza ~4 semanas para publicaciones de cadencia diaria/semanal-alta.
NEW_SOURCES: dict[str, str] = {
    "aqua":            "https://www.aqua.cl/feed/",
    "mch":             "https://www.mch.cl/feed/",
    "redagricola":     "https://redagricola.com/feed/",
    "grocerydive":     "https://www.grocerydive.com/feeds/news/",
    "nrn":             "https://www.nrn.com/rss.xml",
    "skift":           "https://skift.com/feed/",
    "supplychaindive": "https://www.supplychaindive.com/feeds/news/",
    "saastr":          "https://www.saastr.com/feed/",
    "finovate":        "https://finovate.com/feed/",
    "glossy":          "https://www.glossy.co/feed/",
    "statnews":        "https://www.statnews.com/feed/",
    "creatorscience":  "https://creatorscience.com/rss/",
}
PAGES = 4  # ~4 semanas


def fetch_paginated(name: str, url: str, pages: int) -> list[RawItem]:
    items: list[RawItem] = []
    for p in range(1, pages + 1):
        feed_url = url if p == 1 else f"{url}?paged={p}"
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:  # noqa: BLE001
            print(f"  [{name}] página {p} falló: {e}")
            continue
        for e in parsed.entries:
            items.append(RawItem(
                source=name, title=e.get("title", ""), url=e.get("link", ""),
                text=e.get("summary", "")[:2000], engagement=0,
            ))
    print(f"  [{name}] {len(items)} items en {pages} páginas (antes de dedup)")
    return items


def main() -> None:
    print("Fetch histórico de fuentes nuevas...")
    raw: list[RawItem] = []
    for name, url in NEW_SOURCES.items():
        raw.extend(fetch_paginated(name, url, PAGES))

    merged = _dedup(normalize(raw))
    print(f"\nTotal combinado (dedup): {len(merged)}")

    # Todo entra a triage — sin cap de keywords, el juicio es de Haiku.
    # Tope duro de 150 (MAX_CANDIDATES normal) por costo, priorizando
    # engagement (todos en 0 acá, así que queda el orden de aparición).
    candidates = merged[:150]
    print(f"Enviando a Claude: {len(candidates)}\n")

    result = score(candidates)
    scored = result.deep
    scored.sort(key=lambda s: s.objetivo_total, reverse=True)

    print(f"\n=== COSTO REAL: ${result.cost_usd:.4f} ===\n")
    print(f"{len(scored)} analizadas en profundidad, ordenadas por score:\n")
    for s in scored:
        gate = "PASA_GATE" if s.passes_gate(24) else "bajo_gate"
        print(f"[{gate}] {s.objetivo_total:2}/40  [{s.tipo_candidato or '?'}]  [{s.fit_tesis}]  {s.title}")
        print(f"  url: {s.url}")
        print(f"  resumen: {s.resumen}")
        print()


if __name__ == "__main__":
    main()
