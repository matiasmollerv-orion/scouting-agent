"""Estadística NUMÉRICA del Vault (sin contenido de semillas — los logs de Actions son públicos).

Uso: python -m scripts.vault_stats [run_month]   # por defecto: todos los meses
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from dashboard.db import get_client, VAULT_TABLE


def main() -> int:
    month = sys.argv[1] if len(sys.argv) > 1 else ""
    q = get_client().table(VAULT_TABLE).select("*")
    rows = (q.eq("run_month", month) if month else q).execute().data
    print(f"[vault] {len(rows)} semillas" + (f" de {month}" if month else ""))
    for key in ("status", "url_estado", "lens"):
        c: dict = defaultdict(list)
        for r in rows:
            c[r.get(key)].append(r.get("score"))
        for k, v in sorted(c.items(), key=lambda kv: -len(kv[1])):
            sc = [x for x in v if x is not None]
            print(f"[vault] {key}={k}: n={len(v)}" + (f" score_medio={st.mean(sc):.1f} max={max(sc):.1f}" if sc else ""))
    crit = ("s_evidencia", "s_tamano", "s_ahora", "s_hueco", "s_testeabilidad", "bonus_fit", "score")
    by: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get("score") is not None:
            for k in crit:
                if r.get(k) is not None:
                    by[r["lens"]][k].append(r[k])
    print("[vault] medias por criterio (evid, tamaño, ahora, hueco, testeab, bonus, score) por lente:")
    for lens, d in by.items():
        print(f"[vault]   {lens[:34]:34} n={len(d['score'])} " + " ".join(f"{st.mean(d[k]):.1f}" for k in crit if d[k]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
