"""Análisis de MERCADO (no de empresa) — metodología de 8 pasos (Aulet
beachhead, TAM bottom-up+top-down, Porter, JTBD, WTP, fit fundador, RAT,
regulación). Ver prompts/market_analysis.md. Corre siempre manual, disparado
desde una sesión de Claude Code (scripts/market_analysis.py) — esta pantalla
solo encola y muestra resultados, nunca llama a la API directo.

El sujeto de cada fila es el MERCADO/oportunidad, no una empresa — una
empresa de referencia (ej: Decade) solo ilustra que el mercado existe.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    import streamlit as st
    for _key in ("SUPABASE_URL", "SUPABASE_KEY"):
        if _key in st.secrets and not os.environ.get(_key):
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass

import pandas as pd
import streamlit as st

from dashboard.db import fetch_market_analyses, queue_market_analysis

st.set_page_config(page_title="Análisis de Mercado", page_icon="📊", layout="wide")
st.title("📊 Análisis de Mercado")
st.caption(
    "No es análisis de UNA empresa — es del MERCADO/oportunidad que una o más "
    "empresas de referencia ilustran. Metodología fija de 8 pasos: beachhead "
    "(Aulet) → TAM bottom-up + top-down → competencia (Porter) → dolor (JTBD) "
    "→ WTP → fit fundador → RAT → regulación."
)

STATUS_BADGE = {"queued": "⏳ en cola", "analizando": "🔬 analizando",
                 "listo": "✅ listo", "error": "⚠️ error"}

FIELD_LABELS = {
    "beachhead_definido": "1. Beachhead definido",
    "tam_bottom_up": "2a. TAM bottom-up (el número que manda)",
    "tam_top_down": "2b. TAM top-down (sanity check)",
    "discrepancia_tam": "⚠️ Discrepancia TAM (si aplica)",
    "competencia_global": "3a. Competencia global",
    "competencia_local": "3b. Competencia local/LatAm",
    "competencia_en_beachhead_especifico": "3c. Competencia EN el beachhead específico",
    "dolor_jtbd": "4. Dolor real (JTBD)",
    "wtp_estimado": "5a. WTP estimado (por comparables)",
    "wtp_validado": "5b. WTP validado (30-50 entrevistas — vacío hasta que lo hagas vos)",
    "fit_fundador": "6. Fit fundador-mercado",
    "rat_supuesto": "7a. RAT — supuesto más frágil",
    "rat_prueba_barata": "7b. RAT — prueba más barata",
    "regulacion": "8. Regulación/barreras estructurales",
}


@st.cache_data(ttl=30)
def _load() -> list[dict]:
    try:
        return fetch_market_analyses()
    except Exception as e:
        st.error(f"Supabase no disponible: {e}")
        return []


rows = _load()

# --- Encolar mercado nuevo — llegando desde un botón del dashboard
# principal ("usar como referente") viene con empresas_referentes/source_url
# pre-cargados en session_state; el nombre del MERCADO lo definís siempre acá,
# nunca se asume automático del título del candidato.
prefill = st.session_state.pop("market_prefill", {})
expanded = bool(prefill)
label = "➕ Nuevo análisis de mercado" if not prefill else "➕ Nuevo análisis de mercado (con referente pre-cargado)"
with st.expander(label, expanded=expanded):
    if prefill:
        st.info(f"Referente pre-cargado desde el dashboard: **{prefill.get('empresas_referentes', '')}**. "
                "Definí el MERCADO/oportunidad real que representa — no el nombre de la empresa.")
    with st.form("manual_queue"):
        c1, c2 = st.columns(2)
        with c1:
            market_name = st.text_input(
                "Mercado/oportunidad (NO un nombre de empresa)",
                placeholder='ej: "asesoría de inversión con IA para clase media chilena que ya invierte"',
            )
            empresas = st.text_input(
                "Empresas de referencia (opcional, separadas por coma)",
                value=prefill.get("empresas_referentes", ""),
            )
        with c2:
            hint = st.text_area(
                "Hipótesis de beachhead (opcional, recomendado)",
                placeholder="Si ya tenés una idea del segmento angosto real, ponela acá.",
            )
            note = st.text_area("Contexto adicional (opcional)")
        if st.form_submit_button("📊 Encolar"):
            if not market_name.strip():
                st.error("Falta definir el mercado/oportunidad.")
            else:
                queue_market_analysis(
                    market_name=market_name.strip(), empresas_referentes=empresas.strip(),
                    source_url=prefill.get("source_url", ""), origen=prefill.get("origen", "manual"),
                    beachhead_hint=hint.strip(), context_note=note.strip(),
                )
                st.success(f"'{market_name}' encolado — corre en la próxima corrida manual.")
                st.cache_data.clear()
                st.rerun()

if not rows:
    st.info("Todavía no hay análisis de mercado pedidos. Encolá uno arriba, "
            "o usá una idea del dashboard principal como referente.")
    st.stop()

df = pd.DataFrame(rows)
df["estado"] = df["status"].map(lambda s: STATUS_BADGE.get(s, s))

st.divider()
st.subheader("Cola y resultados")

tab_lista, tab_comparar = st.tabs(["📋 Lista", "⚖️ Comparar"])

with tab_lista:
    display = df[["estado", "market_name", "empresas_referentes", "origen", "requested_at", "cost_usd"]].copy()
    display.columns = ["Estado", "Mercado/oportunidad", "Referentes", "Origen", "Pedido", "Costo USD"]
    event = st.dataframe(
        display, hide_index=True, use_container_width=True,
        on_select="rerun", selection_mode="single-row",
    )
    selected = event.selection.rows if event and event.selection else []
    if not selected or selected[0] >= len(df):
        st.info("👆 Seleccioná una fila para ver el detalle completo.")
    else:
        row = df.iloc[selected[0]]
        st.markdown(f"### {row['market_name']}")
        st.caption(f"{STATUS_BADGE.get(row['status'], row['status'])} · pedido {row['requested_at']}"
                   + (f" · costo ${row['cost_usd']:.4f}" if pd.notna(row.get("cost_usd")) else ""))
        if row.get("empresas_referentes"):
            st.markdown(f"**Empresas de referencia:** {row['empresas_referentes']}")
        if row.get("beachhead_hint"):
            st.info(f"**Hipótesis de beachhead dada:** {row['beachhead_hint']}")
        if row["status"] == "error":
            st.error(f"Error: {row.get('error_detail', 'sin detalle')}")
        elif row["status"] in ("queued", "analizando"):
            st.warning("Todavía no tiene resultado — falta correr "
                       "`scripts/market_analysis.py` (siempre manual).")
        else:
            for field, field_label in FIELD_LABELS.items():
                val = row.get(field)
                st.markdown(f"**{field_label}**")
                if field == "discrepancia_tam" and not val:
                    st.caption("Sin discrepancia significativa entre bottom-up y top-down.")
                elif field == "wtp_validado" and not val:
                    st.caption("Vacío — pendiente de entrevistas reales (30-50, Customer Development).")
                else:
                    st.write(val or "—")

with tab_comparar:
    listas = df[df["status"] == "listo"]
    if listas.empty:
        st.info("Necesitás al menos un análisis con estado 'listo' para comparar.")
    else:
        opciones = listas["market_name"].tolist()
        elegidas = st.multiselect("Elegí 2 o más para comparar lado a lado", opciones)
        if len(elegidas) >= 2:
            subset = listas[listas["market_name"].isin(elegidas)].set_index("market_name")
            comp = subset[list(FIELD_LABELS.keys())].T
            comp.index = [FIELD_LABELS[k] for k in FIELD_LABELS]
            st.dataframe(comp, use_container_width=True, height=560)
        elif elegidas:
            st.caption("Elegí al menos 2 para comparar.")
