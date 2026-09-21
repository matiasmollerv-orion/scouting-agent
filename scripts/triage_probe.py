"""Sonda REAL y barata (Haiku, ~$0.03-0.06): ¿el triage con el prompt nuevo puntúa bien las
historias de negocios tradicionales y logística?

Puntúa ~15 titulares de cada fuente dedicada (gn_*) más 15 de fuentes de control (las de
industria que hoy alimentan estas categorías) y compara. Imprime SOLO puntajes y titulares
públicos de prensa — nada personal (los logs de Actions son públicos).

Uso: python -m scripts.triage_probe
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from anthropic import Anthropic

from src import config
from src.pipeline import score
from src.pipeline.normalize import normalize
from src.pipeline.prefilter import _dedup
from src.sources_factory import build_sources

PER_SOURCE = 15
CONTROL = {"modernretail", "retaildive", "grocerydive", "nrn", "manufacturingdive", "supplychaindive"}


def main() -> int:
    items = []
    for src in build_sources():
        if src.name.startswith("gn_") or src.name in CONTROL:
            items.extend(normalize(src.fetch())[:PER_SOURCE])
    items = _dedup(items)
    print(f"[sonda] {len(items)} titulares a puntuar")
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system = (score.PROMPTS_DIR / "triage.md").read_text(encoding="utf-8")
    user = (f"Candidatos ({len(items)}):\n\n{score._serialize(items, text_chars=400)}\n\n"
            f"Puntuá los {len(items)} sin excepción.")
    text, cost, truncated = score._call(client, config.MODEL_TRIAGE, system, user, max_tokens=32000)
    _, by_url = score._rank_from_triage(text, items)
    by_src: dict[str, list[int]] = defaultdict(list)
    for it in items:
        by_src[it.source].append(by_url.get(it.url) or 0)
    print(f"[sonda] costo=${cost:.4f} truncado={truncated} | fuente n media max >=15 >=24")
    for s, v in sorted(by_src.items(), key=lambda kv: -st.mean(kv[1])):
        tag = "CONTROL" if s in CONTROL else "NUEVA  "
        print(f"[sonda] {tag} {s:24} n={len(v):>2} media={st.mean(v):4.1f} max={max(v):>2} "
              f">=15:{sum(a >= 15 for a in v):>2} >=24:{sum(a >= 24 for a in v):>2}")
    print("[sonda] mejores titulares de las fuentes NUEVAS:")
    new = sorted((it for it in items if it.source not in CONTROL), key=lambda i: -(by_url.get(i.url) or 0))
    for it in new[:12]:
        print(f"[sonda]   {by_url.get(it.url) or 0:>2}/40 {it.source:24} {it.title[:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
