#!/usr/bin/env python3
"""Test de validación del fix de madurez (score.md/triage.md, 2026-09).

Dos casos en la misma corrida, para confirmar que el eje quedó bien
calibrado ("¿sigue disrumpiendo, o ya ES el status quo?"), no solo
"grande vs. chica":

1. Whatnot — disruptor probado a escala (GMV $8B+, creciendo 100%+/año,
   privada) — debería puntuar ALTO, sin que su tamaño le reste `ventana`.
2. Amazon — gigante archi-conocido, ya ES el status quo de su industria —
   debería quedar excluido (problema_score≈0), pese a ser noticia real y
   con números grandes, porque el fundador corrigió explícitamente:
   "lo que no puede ocurrir es que me empieces a traer Walmart/Amazon/Nike".

Textos tomados de fuentes reales usadas en esta conversación (CNBC,
PYMNTS, Sacra) y de una noticia genérica de Amazon del estilo de las que
sí aparecen en supplychaindive/retaildive.
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

AMAZON_TEXT = (
    "Amazon Shipping readies 2026 holiday delivery surcharges. The peak "
    "season fees, which are more expensive than last year's, will reach "
    "their highest rate between Nov. 22 and Dec. 26. Amazon says the "
    "surcharges reflect higher operational costs during the busiest "
    "shipping period of the year, and will apply across its logistics "
    "network to third-party sellers using Fulfillment by Amazon."
)

items = [
    Item(source="pymnts", title="Whatnot Raises $545M at $20B Valuation as Live Commerce Booms",
         url="https://example.com/whatnot-test", text=WHATNOT_TEXT, engagement=0),
    Item(source="supplychaindive", title="Amazon Shipping readies 2026 holiday delivery surcharges",
         url="https://example.com/amazon-test", text=AMAZON_TEXT, engagement=0),
]


def main() -> None:
    result = score(items)

    print("=== TRIAGE (todos los candidatos, lleguen o no a deep) ===")
    for t in result.triage:
        print(f"  {t['title'][:55]:55s} total={t['total']}")

    print("\n=== DEEP (solo los que pasaron triage con score > 0) ===")
    if not result.deep:
        print("  ninguno llegó a deep")
    for s in result.deep:
        print(f"\n--- {s.title} ---")
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
