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

# Fuentes 100% curadas/on-topic por definición — no necesitan matchear
# keyword para tener prioridad de sort (yc: lanzamientos; newsletters/
# brain-inbox: el propio usuario las curó; el resto son feeds dedicados
# a UNA categoría de la tesis, verificados con contenido real 2026-08).
TRUSTED_SOURCES = {
    "yc", "newsletters", "brain-inbox",
    "modernretail", "retaildive",                      # ecommerce
    "finextra", "tearsheet", "fintechtimes",            # bienestar financiero
    "geekestate",                                       # inmobiliario
    "creatoreconomy",                                   # creadores de contenido
    "glossy", "statnews",                               # wellness/estética
    "stratechery",                                      # ia ejecutivos
}


def prefilter(items: list[Item], seen_urls: set[str] | None = None) -> list[Item]:
    """Reduce el universo a candidatos SIN llamar al LLM (control de costo).

    2026-08: se sacó el filtro DURO de keywords. Un match de texto literal
    siempre va a tener puntos ciegos (frases reales no anticipadas — pasó con
    "sold out"/"went viral" vs "breakout brand"). Ahora las keywords solo
    desempatan orden DENTRO de cada fuente cuando hay más items que cupo;
    nada se descarta por no matchear una palabra. El juicio de relevancia
    real es 100% de Haiku en el triage (semántico, no de texto literal).

    Pasos: dedup -> excluir vistos en semanas previas -> cap por fuente
    (keyword-match como desempate, no como filtro) -> interleave round-robin
    (diversidad garantizada) -> tope MAX_CANDIDATES global.
    """
    seen_urls = seen_urls or set()
    deduped = _dedup(items)
    fresh = [it for it in deduped if it.dedup_key() not in seen_urls]

    print(f"[funnel] entrada={len(items)} | dup=-{len(items) - len(deduped)} | "
          f"vistos=-{len(deduped) - len(fresh)} | disponibles={len(fresh)} "
          f"(sin filtro de keywords — el juicio de relevancia es de Haiku ahora)")

    # Agrupar por fuente, ordenar internamente y aplicar cap.
    by_source: dict[str, list[Item]] = defaultdict(list)
    for it in fresh:
        by_source[it.source].append(it)

    pools: list[list[Item]] = []
    for source, src_items in by_source.items():
        cap = MAX_PER_SOURCE.get(source, MAX_PER_SOURCE["default"])
        # Orden: Show HN primero, luego match de keyword (desempate, no
        # filtro), luego engagement. Si una fuente tiene menos items que su
        # cupo, TODOS entran igual — nadie se pierde por no matchear.
        src_items.sort(key=lambda it: (
            0 if it.title.lower().startswith("show hn:") else 1,
            0 if _matches_keyword(it) else 1,
            -it.engagement,
        ))
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
    print(f"[funnel] {len(result)} candidatos a triage (round-robin, tope {config.MAX_CANDIDATES})")
    return result


def _dedup(items: list[Item]) -> list[Item]:
    seen: dict[str, Item] = {}
    for it in items:
        key = it.dedup_key()
        # Ante duplicado, conserva el de mayor engagement.
        if key not in seen or it.engagement > seen[key].engagement:
            seen[key] = it
    return list(seen.values())


def _matches_keyword(it: Item) -> bool:
    """Ya NO decide inclusión/exclusión — solo desempate de orden dentro de
    una fuente sobre-suscrita. Ver docstring de prefilter()."""
    if it.source in TRUSTED_SOURCES:
        return True
    haystack = f"{it.title} {it.text}".lower()
    return any(kw in haystack for kw in config.RELEVANCE_KEYWORDS)
