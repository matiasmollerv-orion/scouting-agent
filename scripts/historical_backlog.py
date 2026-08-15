#!/usr/bin/env python3
"""Consulta ad-hoc: backfill histórico de ecommerce/tendencias + bienestar
financiero, más allá del lookback semanal normal (7 días). Los items que el
filtro VIEJO descartaba nunca se guardaron en ningún lado (se filtraban
antes del triage) — para recuperarlos hay que re-fetchear directo de la
fuente con paginación, no desde reports/*-full.json.

No toca estado persistente (seen_urls, pool, stats, email) — solo imprime
al log de Actions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import feedparser

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src import config  # noqa: E402
from src.pipeline.normalize import normalize  # noqa: E402
from src.pipeline.pool import load_newsletter_items, load_pool_items  # noqa: E402
from src.pipeline.prefilter import _dedup  # noqa: E402
from src.pipeline.score import score  # noqa: E402
from src.sources_factory import build_sources  # noqa: E402
from src.models import RawItem  # noqa: E402

ECOMMERCE_KWS = set(config.THEME_KEYWORDS["Ecommerce/DTC"]) | set(config.THEME_KEYWORDS["Tendencias consumo"])
FINTECH_KWS = set(config.THEME_KEYWORDS["Fintech/Clase media"]) | set(config.THEME_KEYWORDS["Bienestar financiero"])

# Fuentes con paginación WordPress real (?paged=N) que cubren hacia atrás
# hasta el inicio del proyecto (~2026-07-04).
PAGINATED = {
    "modernretail": ("https://www.modernretail.co/feed/", 13),
    "techcrunch": ("https://techcrunch.com/feed/", 38),
}


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
    print(f"  [{name}] {len(items)} items en {pages} páginas")
    return items


def matches(it, kws: set[str]) -> bool:
    haystack = f"{it.title} {it.text}".lower()
    return any(kw in haystack for kw in kws)


def main() -> None:
    print("Fetch histórico paginado...")
    raw = []
    for name, (url, pages) in PAGINATED.items():
        raw.extend(fetch_paginated(name, url, pages))

    print("\nFetch fuentes normales (feed vivo)...")
    for src in build_sources():
        items = src.fetch()
        raw.extend(items)
        print(f"  [{src.name}] {len(items)}")

    merged = _dedup(normalize(raw) + load_pool_items() + load_newsletter_items())
    print(f"\nTotal combinado (dedup): {len(merged)}")

    ecommerce = [it for it in merged if it.source in ("modernretail", "retaildive") or matches(it, ECOMMERCE_KWS)]
    fintech = [it for it in merged if matches(it, FINTECH_KWS)]
    print(f"Candidatos ecommerce/tendencias: {len(ecommerce)}")
    print(f"Candidatos bienestar financiero/fintech: {len(fintech)}")

    # Top 20 de cada categoría (por engagement, luego orden de aparición) para
    # que ninguna se coma todos los cupos de triage. ~40 candidatos, más que
    # el TOP normal de 30 porque esta es una consulta especial de catch-up.
    ecommerce.sort(key=lambda it: -it.engagement)
    fintech.sort(key=lambda it: -it.engagement)
    seen_urls = set()
    candidates = []
    for it in ecommerce[:20] + fintech[:20]:
        key = it.dedup_key()
        if key not in seen_urls:
            seen_urls.add(key)
            candidates.append(it)
    print(f"Enviando a Claude: {len(candidates)}\n")

    result = score(candidates)
    scored = result.deep
    scored.sort(key=lambda s: s.objetivo_total, reverse=True)

    print(f"\n=== COSTO REAL: ${result.cost_usd:.4f} ===\n")
    print(f"{len(scored)} analizadas en profundidad, ordenadas por score:\n")
    for s in scored:
        gate = "PASA_GATE" if s.passes_gate(config.MIN_OBJETIVO) else "bajo_gate"
        print(f"[{gate}] {s.objetivo_total:2}/40  [{s.tipo_candidato or '?'}]  [{s.fit_tesis}]  {s.title}")
        print(f"  url: {s.url}")
        print(f"  resumen: {s.resumen}")
        print(f"  competencia_local: {s.competencia_local}")
        print(f"  competencia_global: {s.competencia_global}")
        print()


if __name__ == "__main__":
    main()
