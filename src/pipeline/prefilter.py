from __future__ import annotations

from .. import config
from ..models import Item

# Máximo de items que puede aportar HN al pool final.
# Sin este cap, Show HN llena todos los slots y Reddit/newsletters quedan fuera.
HN_CAP = 20


def prefilter(items: list[Item]) -> list[Item]:
    """Reduce el universo a candidatos SIN llamar al LLM (control de costo).

    Pasos: dedup -> filtro de relevancia -> cap por fuente HN para garantizar
    diversidad -> tope MAX_CANDIDATES global.
    """
    deduped = _dedup(items)
    relevant = [it for it in deduped if _is_relevant(it)]

    # Separar HN (priorizar Show HN) del resto (ordenar por engagement).
    hn = [it for it in relevant if it.source == "hackernews"]
    others = [it for it in relevant if it.source != "hackernews"]

    hn.sort(key=lambda it: (0 if it.title.lower().startswith("show hn:") else 1, -it.engagement))
    others.sort(key=lambda it: -it.engagement)

    combined = hn[:HN_CAP] + others
    # Shuffle suave: intercalar HN y otros para que Claude vea variedad.
    # En la práctica es suficiente concatenar — Claude evalúa todos.
    return combined[: config.MAX_CANDIDATES]


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
