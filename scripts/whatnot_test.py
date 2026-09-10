#!/usr/bin/env python3
"""Test de validación: ¿el fix del sesgo anti-madurez (score.md/triage.md,
2026-09) realmente saca a una empresa grande/consolidada del pozo de
`ventana` baja? Caso real: Whatnot (comercio en vivo, US$20B valorización,
GMV US$8B+ en 2025, #1 app de shopping en EEUU/UK) — el ejemplo que
Matías dio como "por qué nunca detectamos esto".

No usa datos inventados: mismo texto que usé para investigar Whatnot en
esta conversación, tomado de fuentes reales (CNBC, PYMNTS, Sacra).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.models import Item  # noqa: E402
from src.pipeline.score import score  # noqa: E402

WHATNOT_TEXT = (
    "Whatnot, the live-auction shopping app, raised $545 million in a "
    "Series G at a $20 billion valuation, nearly doubling its October 2025 "
    "mark. Live GMV more than doubled year over year to over $8 billion in "
    "2025, crossing $1 billion in cumulative revenue and one billion "
    "cumulative orders in August 2026. Whatnot is now the #1 shopping app "
    "in both the US and UK app stores, hosting 550,000+ hours of live "
    "shows weekly. Sellers livestream auctions for collectibles, fashion "
    "and more; buyers bid and buy in real time, peer-to-peer. One in "
    "eight sellers is now full-time, up 20% year over year. The company "
    "remained unprofitable as of mid-2025 despite the scale."
)

item = Item(
    source="pymnts", title="Whatnot Raises $545M at $20B Valuation as Live Commerce Booms",
    url="https://example.com/whatnot-20b-valuation-test", text=WHATNOT_TEXT, engagement=0,
)


def main() -> None:
    result = score([item])
    if not result.deep:
        print("[test] sin resultado — revisar output crudo")
        return
    s = result.deep[0]
    print(f"objetivo_total: {s.objetivo_total}/40  (problema={s.problema_score} barrera={s.barrera_score})")
    print(f"tipo_candidato: {s.tipo_candidato}")
    print(f"fit_tesis: {s.fit_tesis}")
    print(f"replicabilidad: {s.replicabilidad.nivel} — {s.replicabilidad.evidencia}")
    print(f"ventana: {s.ventana.nivel} — {s.ventana.evidencia}")
    print(f"tamano_mercado: {s.tamano_mercado.nivel} — {s.tamano_mercado.evidencia}")
    print(f"resumen: {s.resumen}")
    print(f"funding_raised: {s.funding_raised!r}  stage: {s.stage!r}")
    print(f"\ncosto real: ${result.cost_usd:.4f}")


if __name__ == "__main__":
    main()
