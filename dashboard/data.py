"""Consolida todos los reports/*-full.json del repo en un dataset único.

Cada semana ya guarda TODO lo evaluado (30 triage + hasta 8 deep), no solo
las 5 que muestra el email. Este módulo junta todas las semanas en un solo
DataFrame para que el dashboard pueda filtrar/buscar sobre el historial
completo.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"

DEEP_COLS = [
    "fit_tesis", "resumen", "company_url", "next_step", "por_que_ahora",
    "modelo_negocio", "competencia_local", "stage", "funding_raised",
    "mercado_actual", "valida_idea_propia", "fundadores", "redes_sociales",
    "fit_yc", "tipo_candidato",
]

_WEEK_RE = re.compile(r"(\d{4})-W(\d{2})")


def week_to_date(week_str: str) -> date | None:
    """Lunes de la semana ISO (ej: '2026-W28' -> 2026-07-06)."""
    m = _WEEK_RE.match(str(week_str))
    if not m:
        return None
    try:
        return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def load_all_weeks() -> pd.DataFrame:
    rows: list[dict] = []
    for f in sorted(REPORTS_DIR.glob("*-full.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        week = data.get("week", f.stem.replace("-full", ""))
        gate_urls = set(data.get("gate_urls", []))
        deep_by_url = {d["url"]: d for d in data.get("deep", [])}

        for t in data.get("triage", []):
            url = t["url"]
            deep = deep_by_url.get(url, {})
            has_deep = url in deep_by_url
            row = {
                "week": week,
                "url": url,
                "title": t["title"],
                "source": t["source"],
                "text": t.get("text", ""),
                "triage_total": t.get("total"),
                "has_deep": has_deep,
                "passes_gate": url in gate_urls,
                "objetivo_total": (
                    deep["problema_score"] + deep["barrera_score"] if has_deep else None
                ),
            }
            for col in DEEP_COLS:
                row[col] = deep.get(col, "")
            rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["week_date"] = df["week"].apply(week_to_date)
    return df
