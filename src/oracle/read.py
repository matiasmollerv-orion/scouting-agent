"""Etapa de LECTURA del Oracle: el modelo lee titulares ya recolectados (gratis) en vez de
salir a buscar a la web a ciegas.

Flujo por combinación país × lente:
  1. recolectar (src.oracle.sources: abiertas + curadas + global + pool) — $0
  2. filtrar y acotar a N titulares balanceados (por palabra del lente, diversidad de medios)
  3. UNA llamada barata (Batch) que lee la lista numerada y extrae las mejores señales

Límite honesto: Google Noticias entrega el TITULAR y el medio, no el artículo. Alcanza para
detectar QUÉ está pasando (negocios que abren y crecen, reguladores que actúan, quejas), no
para verificar cifras — de eso se encarga la etapa de verificación (búsqueda web) sobre las
mejores semillas después del consejo.
"""
from __future__ import annotations

import re
from collections import Counter

import httpx

from . import sources

MAX_ITEMS = 80            # titulares por combinación que lee el modelo (≈ 3k tokens de entrada)
MAX_PER_DOMAIN = 3        # diversidad: un medio no llena la lista
MAX_PER_QUERY = 6         # diversidad: una consulta (p. ej. contabilidad) no llena la lista
MAX_POOL = 10             # señales globales del scouting semanal (sin país)
LAYER_BONUS = {"rotacion": 2.0, "curada": 1.0, "global": 0.5, "abierta": 0.0, "pool": -0.5}


def _norm(t: str) -> str:
    return re.sub(r"\W+", "", t.lower())[:80]


WINDOW_DAYS = 35  # corridas cada 4-5 semanas (último viernes de cada mes): 35 días no deja huecos entre corridas


def gather(cc: str, lens_key: str, client: httpx.Client, cache: dict, days: int = WINDOW_DAYS) -> list[dict]:
    items = sources.fetch_pair(cc, lens_key, client, days, cache)
    seen = {_norm(i["title"]) for i in items}
    pool = [p for p in sources.pool_items(lens_key) if _norm(p["title"]) not in seen][:MAX_POOL]
    return items + pool


def rank(items: list[dict], cc: str, lens_key: str, n: int = MAX_ITEMS) -> list[dict]:
    """Los n titulares más útiles: palabra del lente + capa curada primero, sin que un medio domine."""
    kws = [k.strip('"').lower() for k in sources.lang_terms(cc, lens_key, "keywords")[1]]

    def score(i: dict) -> float:
        hit = any(k in f"{i['title']} {i['snippet']}".lower() for k in kws)
        return (2.0 if hit else 0.0) + LAYER_BONUS.get(i["via"], 0.0)

    per_domain: Counter = Counter()
    per_query: Counter = Counter()
    out: list[dict] = []
    for it in sorted(items, key=score, reverse=True):
        dom = it["domain"] or it["source"]
        q = it.get("q") or ""
        if per_domain[dom] >= MAX_PER_DOMAIN or (q and per_query[q] >= MAX_PER_QUERY):
            continue
        per_domain[dom] += 1
        per_query[q] += 1
        out.append(it)
        if len(out) >= n:
            break
    if len(out) < n:  # relleno: si los topes por consulta dejaron la lista corta, se completan con lo que sobró
        chosen = {id(x) for x in out}
        for it in sorted(items, key=score, reverse=True):
            dom = it["domain"] or it["source"]
            if id(it) in chosen or per_domain[dom] >= MAX_PER_DOMAIN:
                continue
            per_domain[dom] += 1
            out.append(it)
            if len(out) >= n:
                break
    return out


def render(items: list[dict]) -> str:
    """Lista numerada compacta: [n] titular — medio (capa). El modelo cita por número."""
    lines = []
    for n, it in enumerate(items, 1):
        outlet = it["source"] or it["domain"] or "?"
        tag = " (global)" if it["via"] in ("pool", "global") else ""
        lines.append(f"[{n}] {it['title'][:200]} — {outlet}{tag}")
    return "\n".join(lines)
