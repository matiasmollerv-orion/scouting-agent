from __future__ import annotations

from collections import defaultdict

from .. import config
from ..models import Item

# Slots máximos por fuente antes del corte global.
# Garantiza diversidad geográfica — sin esto una sola fuente llena todo.
MAX_PER_SOURCE = {
    "hackernews": 10,   # Show HN primero (lanzamientos reales)
    "default":     7,   # todas las demás fuentes
}


def prefilter(items: list[Item], seen_urls: set[str] | None = None) -> list[Item]:
    """Reduce el universo a candidatos SIN llamar al LLM (control de costo).

    Pasos: dedup -> excluir vistos en semanas previas -> filtro de relevancia
    -> cap por fuente -> interleave round-robin (diversidad garantizada)
    -> tope MAX_CANDIDATES global.
    """
    seen_urls = seen_urls or set()
    deduped = _dedup(items)
    fresh = [it for it in deduped if it.dedup_key() not in seen_urls]
    skipped = len(deduped) - len(fresh)
    if skipped:
        print(f"[prefilter] {skipped} items ya evaluados en semanas previas, omitidos")
    relevant = [it for it in fresh if _is_relevant(it)]

    # Agrupar por fuente, ordenar internamente y aplicar cap.
    by_source: dict[str, list[Item]] = defaultdict(list)
    for it in relevant:
        by_source[it.source].append(it)

    pools: list[list[Item]] = []
    for source, src_items in by_source.items():
        cap = MAX_PER_SOURCE.get(source, MAX_PER_SOURCE["default"])
        # HN: Show HN primero, luego por engagement. Resto: por engagement.
        src_items.sort(
            key=lambda it: (0 if it.title.lower().startswith("show hn:") else 1, -it.engagement)
        )
        pools.append(src_items[:cap])

    # Round-robin entre fuentes: toma 1 de cada una por turno.
    # Así ninguna fuente monopoliza los cupos aunque tenga más engagement.
    result: list[Item] = []
    idx = 0
    while len(result) < config.MAX_CANDIDATES and any(idx < len(p) for p in pools):
        for pool in pools:
            if idx < len(pool) and len(result) < config.MAX_CANDIDATES:
                result.append(pool[idx])
        idx += 1
    return result


def _dedup(items: list[Item]) -> list[Item]:
    seen: dict[str, Item] = {}
    for it in items:
        key = it.dedup_key()
        # Ante duplicado, conserva el de mayor engagement.
        if key not in seen or it.engagement > seen[key].engagement:
            seen[key] = it
    return list(seen.values())


def _is_relevant(it: Item) -> bool:
    # "Show HN:" son lanzamientos de productos en HN — pasan directo,
    # sin necesitar keyword match. Engagement solo no alcanza: un post
    # viral sin señal de negocio no es candidato.
    if it.title.lower().startswith("show hn:"):
        return True
    haystack = f"{it.title} {it.text}".lower()
    return any(kw in haystack for kw in config.RELEVANCE_KEYWORDS)
