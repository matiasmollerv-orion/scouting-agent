"""Persistencia de análisis on-demand en Supabase.

Streamlit Cloud no tiene filesystem durable entre reinicios de la app, y
escribir/pushear JSON a git desde una app pública expondría un token de
escritura. Se usa Supabase (misma cuenta que Financial Dashboard) para
guardar cada análisis pedido desde el dashboard.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from supabase import Client, create_client

TABLE = "scouting_deep_ondemand"
WEEKLY_CAP = 15  # guardrail: tope de análisis on-demand por semana


def _get_secret(key: str) -> str:
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val:
            return val
    except Exception:
        pass
    return os.getenv(key, "")


def get_client() -> Client:
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("Faltan SUPABASE_URL o SUPABASE_KEY")
    return create_client(url, key)


def fetch_ondemand() -> dict[str, dict]:
    """Todos los análisis on-demand ya hechos, indexados por url."""
    sb = get_client()
    rows = sb.table(TABLE).select("*").execute().data
    return {r["url"]: r for r in rows}


def count_this_week() -> int:
    sb = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    result = (
        sb.table(TABLE).select("id", count="exact").gte("requested_at", cutoff).execute()
    )
    return result.count or 0


def save_ondemand(week: str, item, scored, cost_usd: float) -> None:
    sb = get_client()
    row = {
        "url": item.url,
        "week": week,
        "title": scored.title,
        "source": scored.source,
        "problema_score": scored.problema_score,
        "barrera_score": scored.barrera_score,
        "replicabilidad_nivel": scored.replicabilidad.nivel.value,
        "replicabilidad_evidencia": scored.replicabilidad.evidencia,
        "ventana_nivel": scored.ventana.nivel.value,
        "ventana_evidencia": scored.ventana.evidencia,
        "tamano_mercado_nivel": scored.tamano_mercado.nivel.value,
        "tamano_mercado_evidencia": scored.tamano_mercado.evidencia,
        "resumen": scored.resumen,
        "b2b_o_b2c": scored.b2b_o_b2c,
        "componente_ia": scored.componente_ia,
        "tipo_fundador": scored.tipo_fundador,
        "mercado_actual": scored.mercado_actual,
        "company_url": scored.company_url,
        "funding_raised": scored.funding_raised,
        "stage": scored.stage,
        "por_que_ahora": scored.por_que_ahora,
        "modelo_negocio": scored.modelo_negocio,
        "competencia_local": scored.competencia_local,
        "fit_tesis": scored.fit_tesis,
        "next_step": scored.next_step,
        "valida_idea_propia": scored.valida_idea_propia,
        "fundadores": scored.fundadores,
        "redes_sociales": scored.redes_sociales,
        "fit_yc": scored.fit_yc,
        "tipo_candidato": scored.tipo_candidato,
        "cost_usd": round(cost_usd, 5),
    }
    sb.table(TABLE).upsert(row, on_conflict="url").execute()
