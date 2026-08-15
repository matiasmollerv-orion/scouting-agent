#!/usr/bin/env python3
"""Consulta ad-hoc: ideas de ecommerce/tendencias de consumo evaluadas AHORA,
sin esperar al sábado. No toca estado persistente (seen_urls, pool, stats,
email) — solo imprime resultados al log de Actions.

Uso: gh workflow run ecommerce-backlog.yml (o `python -m scripts.ecommerce_backlog` con ANTHROPIC_API_KEY en el entorno).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src import config  # noqa: E402
from src.pipeline.normalize import normalize  # noqa: E402
from src.pipeline.pool import load_newsletter_items, load_pool_items  # noqa: E402
from src.pipeline.prefilter import _dedup  # noqa: E402
from src.pipeline.score import score  # noqa: E402
from src.sources_factory import build_sources  # noqa: E402

ECOMMERCE_KWS = set(config.THEME_KEYWORDS["Ecommerce/DTC"]) | set(config.THEME_KEYWORDS["Tendencias consumo"])


def is_ecommerce(it) -> bool:
    if it.source in ("modernretail", "retaildive"):
        return True
    haystack = f"{it.title} {it.text}".lower()
    return any(kw in haystack for kw in ECOMMERCE_KWS)


def main() -> None:
    print("Fetcheando fuentes...")
    raw = []
    for src in build_sources():
        items = src.fetch()
        raw.extend(items)
        print(f"  [{src.name}] {len(items)}")

    merged = _dedup(normalize(raw) + load_pool_items() + load_newsletter_items())
    print(f"\nTotal combinado (dedup): {len(merged)}")

    candidates = [it for it in merged if is_ecommerce(it)][: config.MAX_CANDIDATES]
    print(f"Candidatos ecommerce/tendencias: {len(candidates)}\n")

    result = score(candidates)
    scored = result.deep
    scored.sort(key=lambda s: s.objetivo_total, reverse=True)

    print(f"\n=== COSTO REAL: ${result.cost_usd:.4f} ===\n")
    print(f"{len(scored)} analizadas en profundidad, ordenadas por score:\n")
    for s in scored:
        gate = "PASA_GATE" if s.passes_gate(config.MIN_OBJETIVO) else "bajo_gate"
        print(f"[{gate}] {s.objetivo_total:2}/40  [{s.tipo_candidato or '?'}]  {s.title}")
        print(f"  url: {s.url}")
        print(f"  resumen: {s.resumen}")
        print(f"  competencia_local: {s.competencia_local}")
        print(f"  competencia_global: {s.competencia_global}")
        print()


if __name__ == "__main__":
    main()
