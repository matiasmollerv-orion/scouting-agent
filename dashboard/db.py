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
FAVORITES_TABLE = "scouting_favorites"
MARKET_TABLE = "scouting_market_analysis"
VAULT_TABLE = "scouting_vault"
LESSONS_TABLE = "scouting_lessons"
ORACLE_RUNS_TABLE = "scouting_oracle_runs"
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
        "competencia_global": scored.competencia_global,
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


def fetch_favorites() -> dict[str, dict]:
    """Todas las favoritas, indexadas por url."""
    sb = get_client()
    rows = sb.table(FAVORITES_TABLE).select("*").execute().data
    return {r["url"]: r for r in rows}


def add_favorite(url: str, title: str, note: str = "") -> None:
    sb = get_client()
    sb.table(FAVORITES_TABLE).upsert(
        {"url": url, "title": title, "note": note}, on_conflict="url",
    ).execute()


def remove_favorite(url: str) -> None:
    sb = get_client()
    sb.table(FAVORITES_TABLE).delete().eq("url", url).execute()


# --- Análisis de mercado (metodología 8 pasos, ver prompts/market_analysis.md) ---

def fetch_market_analyses() -> list[dict]:
    """Todas las filas de la cola, sin importar estado, más recientes primero."""
    sb = get_client()
    return (
        sb.table(MARKET_TABLE).select("*")
        .order("requested_at", desc=True).execute().data
    )


def queue_market_analysis(
    market_name: str, empresas_referentes: str = "", source_url: str = "",
    origen: str = "manual", beachhead_hint: str = "", context_note: str = "",
) -> int | None:
    """Encola un MERCADO/oportunidad para análisis — no una empresa (ver
    docstring de la tabla en schema.sql). NO lo corre, solo lo marca. El
    paso caro lo dispara scripts/market_analysis.py, siempre a mano."""
    sb = get_client()
    res = sb.table(MARKET_TABLE).insert({
        "market_name": market_name,
        "empresas_referentes": empresas_referentes or None,
        "source_url": source_url or None,
        "origen": origen,
        "beachhead_hint": beachhead_hint or None,
        "context_note": context_note or None,
        "status": "queued",
    }).execute()
    return res.data[0]["id"] if res.data else None


def update_market_analysis(row_id: int, **fields) -> None:
    """Actualiza cualquier subconjunto de columnas de una fila — usado por
    scripts/market_analysis.py para marcar 'analizando'/'listo'/'error' y
    escribir el resultado."""
    sb = get_client()
    sb.table(MARKET_TABLE).update(fields).eq("id", row_id).execute()


# --- Oracle: Vault de semillas, lessons y registro de corridas (ver schema.sql) ---

def fetch_vault() -> list[dict]:
    """Todas las semillas, mejor score primero (las sin score al final)."""
    sb = get_client()
    return (
        sb.table(VAULT_TABLE).select("*")
        .order("score", desc=True, nullsfirst=False).limit(2000).execute().data
    )


def fetch_vault_status(status: str) -> list[dict]:
    """Semillas en un estado (de cualquier mes) — el consejo procesa las 'nueva'."""
    sb = get_client()
    return sb.table(VAULT_TABLE).select("*").eq("status", status).order("id").execute().data


def insert_vault_seeds(rows: list[dict]) -> None:
    """Inserta ignorando duplicados exactos (dedupe_key) — una corrida repetida
    no duplica semillas."""
    if not rows:
        return
    sb = get_client()
    sb.table(VAULT_TABLE).upsert(rows, on_conflict="dedupe_key", ignore_duplicates=True).execute()


def update_vault(row_id: int, **fields) -> None:
    sb = get_client()
    sb.table(VAULT_TABLE).update(fields).eq("id", row_id).execute()


def add_lesson(verdict: str, reason: str, seed_snapshot: str) -> None:
    sb = get_client()
    sb.table(LESSONS_TABLE).insert({
        "verdict": verdict, "reason": reason or None, "seed_snapshot": seed_snapshot,
    }).execute()


def fetch_lessons(limit: int = 25) -> list[dict]:
    """Últimos veredictos activos, más recientes primero."""
    sb = get_client()
    return (
        sb.table(LESSONS_TABLE).select("*").eq("active", True)
        .order("created_at", desc=True).limit(limit).execute().data
    )


def get_oracle_run(month_key: str) -> dict | None:
    sb = get_client()
    rows = sb.table(ORACLE_RUNS_TABLE).select("*").eq("month_key", month_key).execute().data
    return rows[0] if rows else None


def save_oracle_run(month_key: str, **fields) -> None:
    sb = get_client()
    sb.table(ORACLE_RUNS_TABLE).upsert({"month_key": month_key, **fields}, on_conflict="month_key").execute()


def fetch_oracle_runs() -> list[dict]:
    sb = get_client()
    return sb.table(ORACLE_RUNS_TABLE).select("*").order("month_key", desc=True).limit(12).execute().data
