#!/usr/bin/env python3
"""Re-corrida real de 2026-W35 con el fix de max_tokens del triage.

El run original (sábado) truncó el triage a max_tokens=4000: 85/150
candidatos (57%) quedaron sin score, silenciosamente — commit 557f87d.
Este script re-evalúa los MISMOS 150 candidatos que ya se fetchearon ese
día (guardados en reports/2026-W35-full.json -> "triage", con su texto),
pero con el fix (max_tokens=16000) ya aplicado en score.py.

Deliberadamente NO usa src.main.run(): eso re-fetchearía RSS fresco (datos
distintos a los del sábado) y tocaría seen_urls.json/stats.json/pool como
si fuera la corrida oficial de la semana — esto es un diagnóstico, no un
reemplazo del reporte ya enviado. Solo llama a score() sobre el mismo
candidate set y escribe un reporte aparte para revisar.

Costo: ~igual a una corrida semanal normal (triage + deep de 8, batch
50% off) — tope real dado por COST_LIMIT_USD.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.models import Item  # noqa: E402
from src.pipeline.score import score  # noqa: E402
from src.render.report import render  # noqa: E402

SRC_FULL = REPO / "reports" / "2026-W35-full.json"
OUT_MD = REPO / "reports" / "2026-W35-rerun.md"
OUT_JSON = REPO / "reports" / "2026-W35-rerun-full.json"


def load_candidates() -> list[Item]:
    data = json.loads(SRC_FULL.read_text(encoding="utf-8"))
    items = []
    for t in data["triage"]:
        items.append(Item(
            source=t["source"], title=t["title"], url=t["url"],
            text=t.get("text", ""), engagement=0,
        ))
    return items


def main() -> None:
    items = load_candidates()
    print(f"[rerun] {len(items)} candidatos cargados desde {SRC_FULL.name} "
          f"(mismo set que el run original del sábado)")

    result = score(items)

    sin_score = sum(1 for t in result.triage if t.get("total") is None)
    print(f"[rerun] cobertura triage: {len(items) - sin_score}/{len(items)} con score "
          f"({sin_score} sin score) — vs. 65/150 en el run original truncado")

    scored = sorted(result.deep, key=lambda s: s.objetivo_total, reverse=True)
    passing = [s for s in scored if s.passes_gate(24)]

    print(f"\n[rerun] {len(scored)} candidatos con análisis profundo, "
          f"{len(passing)} sobre el gate\n")
    for s in scored:
        gate = "✅" if s.passes_gate(24) else "  "
        print(f"{gate} {s.objetivo_total:2d}/40  [{s.fit_tesis or s.tipo_candidato or '?'}]  {s.title[:70]}")
        if s.resumen:
            print(f"        {s.resumen[:140]}")

    warnings = []
    if result.triage_truncated:
        warnings.append(f"⚠️ triage aún con cobertura baja: {sin_score}/{len(items)} sin score")

    md = render(scored, total_evaluados=len(items), min_objetivo=24,
                panorama=result.triage, gate_count=len(passing), warnings=warnings)
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_JSON.write_text(json.dumps({
        "triage": result.triage,
        "deep": [s.model_dump(mode="json") for s in result.deep],
        "gate_urls": [s.url for s in passing],
        "cost_usd": round(result.cost_usd, 4),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n[rerun] costo real: ${result.cost_usd:.4f}")
    print(f"[rerun] reporte -> {OUT_MD}")


if __name__ == "__main__":
    main()
