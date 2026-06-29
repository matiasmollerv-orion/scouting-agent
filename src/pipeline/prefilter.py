from __future__ import annotations

from .. import config
from ..models import Item


def prefilter(items: list[Item]) -> list[Item]:
    """Reduce el universo a candidatos SIN llamar al LLM (control de costo).

    Pasos: dedup por URL -> filtro de relevancia (engagement o keywords)
    -> tope MAX_CANDIDATES ordenado por engagement.
    """
    deduped = _dedup(items)
    relevant = [it for it in deduped if _is_relevant(it)]
    # Show HN primero (lanzamientos reales), luego el resto por engagement.
    relevant.sort(
        key=lambda it: (0 if it.title.lower().startswith("show hn:") else 1, -it.engagement)
    )
    return relevant[: config.MAX_CANDIDATES]


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
