"""Cobertura de fuentes del Oracle — SIN LLM, costo $0.

Recolecta (gratis) lo que el Oracle leería para cada país × lente y reporta
CONTEOS: cuántos artículos únicos, cuántos medios distintos y de qué capa vienen.
No imprime títulos ni contenido (los logs de Actions son públicos).

Uso:
  python -m scripts.oracle_sources_check                  # las 147 combinaciones
  python -m scripts.oracle_sources_check --countries CL,BR --lenses fintech
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict

import httpx

from src.oracle import sources
from src.oracle.matrix import COUNTRIES, LENS_BY_KEY, SCHEDULE

MIN_OK = 15  # bajo esto, el par tiene cobertura floja


def _relevantes(items: list[dict], cc: str, lens_key: str) -> int:
    """Proxy barato de relevancia: items cuyo título/fragmento nombra algo del lente."""
    kws = [k.strip('"').lower() for k in sources.lang_terms(cc, lens_key, "keywords")[1]]
    return sum(any(k in f"{i['title']} {i['snippet']}".lower() for k in kws) for i in items)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", default="")
    ap.add_argument("--lenses", default="")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    ccs = set(filter(None, a.countries.split(",")))
    lens = set(filter(None, a.lenses.split(",")))
    pairs = [(cc, lk) for (cc, lk) in SCHEDULE if (not ccs or cc in ccs) and (not lens or lk in lens)]

    cache: dict = {}
    rows = []
    with httpx.Client(headers=sources._UA, follow_redirects=True) as client:
        for cc, lk in pairs:
            items = sources.fetch_pair(cc, lk, client, a.days, cache)
            pool = sources.pool_items(lk)
            via = Counter(i["via"] for i in items)
            media = {i["domain"] or i["source"] for i in items if i["domain"] or i["source"]}
            rel = _relevantes(items, cc, lk)
            rows.append((cc, lk, len(items), len(media), via["abierta"], via["curada"], len(pool)))
            print(f"[fuentes] {cc:<2} {lk:<16} items={len(items):>4} medios={len(media):>3} "
                  f"abiertas={via['abierta']:>3} curadas={via['curada']:>3} global={via['global']:>3} pool={len(pool):>3} "
                  f"con_palabra_del_lente={rel:>3}", flush=True)

    weak = [r for r in rows if r[2] < MIN_OK]
    print(f"\n[fuentes] combinaciones={len(rows)} | flojas(<{MIN_OK})={len(weak)} | "
          f"consultas={len(cache)} | costo=$0.00")
    by_c: dict[str, list[int]] = defaultdict(list)
    by_l: dict[str, list[int]] = defaultdict(list)
    for cc, lk, n, *_ in rows:
        by_c[cc].append(n)
        by_l[lk].append(n)
    print("[fuentes] mediana de items por PAÍS: " + " ".join(
        f"{c}={sorted(v)[len(v)//2]}" for c, v in sorted(by_c.items())))
    print("[fuentes] mediana de items por LENTE: " + " ".join(
        f"{k}={sorted(v)[len(v)//2]}" for k, v in sorted(by_l.items())))
    for cc, lk, n, m, *_ in weak:
        print(f"[fuentes] FLOJA {COUNTRIES[cc][0]} × {LENS_BY_KEY[lk].name}: {n} items, {m} medios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
