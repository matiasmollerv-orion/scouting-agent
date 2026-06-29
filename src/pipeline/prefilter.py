from __future__ import annotations

from collections import defaultdict

from .. import config
from ..models import Item

# Slots máximos por fuente antes del corte global.
# Garantiza diversidad geográfica — sin esto una sola fuente llena todo.
MAX_PER_SOURCE = {
    "hackernews": 15,   # Show HN primero (lanzamientos reales)
    "default":     7,   # todas las demás fuentes
}


def prefilter(items: list[Item]) -> list[Item]:
    """Reduce el universo a candidatos SIN llamar al LLM (control de costo).

    Pasos: dedup -> filtro de relevancia -> cap por fuente (diversidad
    geográfica) -> tope MAX_CANDIDATES global.
    """
    deduped = _dedup(items)
    relevant = [it for it in deduped if _is_relevant(it)]

    # Agrupar por fuente y aplicar cap + orden interno.
    by_source: dict[str, list[Item]] = defaultdict(list)
    for it in relevant:
        by_source[it.source].append(it)

    pool: list[Item] = []
    for source, src_items in by_source.items():
        cap = MAX_PER_SOURCE.get(source, MAX_PER_SOURCE["default"])
        # HN: Show HN primero, luego por engagement.
        # Resto: por engagement.
        src_items.sort(
            key=lambda it: (0 if it.title.lower().startswith("show hn:") else 1, -it.engagement)
        )
        pool.extend(src_items[:cap])

    # Orden final: Show HN al tope, resto por engagement.
    pool.sort(
        key=lambda it: (0 if it.title.lower().startswith("show hn:") else 1, -it.engagement)
    )
    return pool[: config.MAX_CANDIDATES]


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
