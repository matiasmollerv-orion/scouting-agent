"""Recolección diaria SIN LLM — $0 de API.

Fetchea todas las fuentes y acumula candidatos en data/pool.json para que
el scoring del sábado vea la semana completa (los feeds RSS de alto volumen
como TechCrunch rotan en ~1-2 días y un solo fetch semanal pierde el resto).

Este módulo NO importa anthropic ni necesita ANTHROPIC_API_KEY.
"""
from __future__ import annotations

from .models import RawItem
from .pipeline.normalize import normalize
from .pipeline.pool import merge_into_pool
from .sources_factory import build_sources


def collect() -> None:
    raw: list[RawItem] = []
    for src in build_sources():
        items = src.fetch()
        print(f"[{src.name}] {len(items)} items")
        raw.extend(items)

    added, total = merge_into_pool(normalize(raw))
    print(f"[collect] +{added} nuevos -> pool con {total} items")


if __name__ == "__main__":
    collect()
