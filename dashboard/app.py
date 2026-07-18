"""Dashboard de Scouting de Ideas — consolida todas las semanas evaluadas.

El email semanal solo muestra el top 5. Todo lo demás (30 candidatos/semana
con triage, hasta 8 con análisis profundo) ya se guarda en
reports/*-full.json pero nadie lo mira. Este dashboard lo hace navegable y
permite pedir análisis profundo on-demand de cualquier idea que solo tenga
triage, sin esperar a que el pipeline semanal la elija.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Los secrets de Streamlit Cloud deben pasar a variables de entorno ANTES de
# importar src.config, que las lee vía os.environ.get() a nivel de módulo.
try:
    import streamlit as st
    for _key in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"):
        if _key in st.secrets and not os.environ.get(_key):
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass

import pandas as pd
import streamlit as st

from dashboard.data import DEEP_COLS, load_all_weeks
from dashboard.db import WEEKLY_CAP, count_this_week, fetch_ondemand, save_ondemand
from dashboard.deep_single import analyze_one
from src.models import Item

st.set_page_config(page_title="Scouting de Ideas", page_icon="🔍", layout="wide")
st.title("🔍 Scouting de Ideas de Negocio")
st.caption("Todo lo evaluado por el pipeline semanal, no solo el top 5 del email.")


@st.cache_data(ttl=300)
def _load() -> pd.DataFrame:
    return load_all_weeks()


@st.cache_data(ttl=60)
def _load_ondemand() -> dict:
    try:
        return fetch_ondemand()
    except Exception:
        return {}


df = _load()
ondemand = _load_ondemand()

if df.empty:
    st.info("Todavía no hay datos — corre el pipeline semanal al menos una vez.")
    st.stop()

# Streamlit Cloud usa warm deployments: st.cache_data puede servir un
# DataFrame cacheado de una versión anterior del código, sin las columnas
# nuevas. Se garantizan todas antes de usarlas — nunca KeyError por caché vieja.
for _col in DEEP_COLS:
    if _col not in df.columns:
        df[_col] = ""

# Los análisis on-demand pisan lo que venía del repo (mismo url).
for url, row in ondemand.items():
    mask = df["url"] == url
    if not mask.any():
        continue
    df.loc[mask, "has_deep"] = True
    df.loc[mask, "objetivo_total"] = row.get("problema_score", 0) + row.get("barrera_score", 0)
    for col in ["fit_tesis", "resumen", "next_step", "por_que_ahora",
                "modelo_negocio", "competencia_local", "stage",
                "funding_raised", "company_url", "mercado_actual",
                "valida_idea_propia", "fundadores", "redes_sociales",
                "fit_yc", "tipo_candidato"]:
        df.loc[mask, col] = row.get(col, "")

# --- Filtros ---
st.sidebar.header("Filtros")

# Rango de fechas — por defecto TODO el historial (no solo semanas recientes).
valid_dates = df["week_date"].dropna()
date_range = None
if not valid_dates.empty:
    min_d, max_d = valid_dates.min(), valid_dates.max()
    date_range = st.sidebar.date_input(
        "Rango de fechas", value=(min_d, max_d), min_value=min_d, max_value=max_d,
    )

fit_options = sorted(f for f in df["fit_tesis"].dropna().unique() if f)
fit_sel = st.sidebar.multiselect("Vertical / Industria (fit tesis)", fit_options)

source_options = sorted(df["source"].dropna().unique())
source_sel = st.sidebar.multiselect("Fuente", source_options)

score_range = st.sidebar.slider("Score objetivo (0-40)", 0, 40, (0, 40))

incluir_triage = st.sidebar.checkbox(
    "Incluir ideas solo-triage (sin análisis profundo)", value=True
)
solo_gate = st.sidebar.checkbox("Solo sobre el gate", value=False)
busqueda = st.sidebar.text_input("Buscar en título")

cap_used = 0
try:
    cap_used = count_this_week()
except Exception as e:
    st.sidebar.warning(f"Supabase no disponible: {e}")
st.sidebar.metric("Análisis on-demand esta semana", f"{cap_used}/{WEEKLY_CAP}")

f = df.copy()
if date_range and len(date_range) == 2:
    start, end = date_range
    f = f[f["week_date"].isna() | f["week_date"].between(start, end)]
if fit_sel:
    f = f[f["fit_tesis"].isin(fit_sel)]
if source_sel:
    f = f[f["source"].isin(source_sel)]
if not incluir_triage:
    f = f[f["has_deep"]]
if score_range != (0, 40):
    scored = f["objetivo_total"].notna() & f["objetivo_total"].between(*score_range)
    unscored = f["objetivo_total"].isna()
    f = f[scored | (unscored & incluir_triage)]
if solo_gate:
    f = f[f["passes_gate"]]
if busqueda:
    f = f[f["title"].str.contains(busqueda, case=False, na=False)]

f = f.sort_values(
    ["has_deep", "objetivo_total", "triage_total"], ascending=[False, False, False]
)

st.caption(f"{len(f)} ideas mostradas · {len(df)} evaluadas en total desde que corre el sistema")

# --- Tabla compacta: una fila por idea, columnas para escanear de un vistazo ---
if f.empty:
    st.info("Ningún resultado con estos filtros.")
    st.stop()

f = f.reset_index(drop=True)
f["score_mostrado"] = f["objetivo_total"].where(f["has_deep"], f["triage_total"])
f["analizado"] = f["has_deep"].map({True: "Profundo", False: "Triage"})

DISPLAY_COLS = [
    "passes_gate", "score_mostrado", "analizado", "tipo_candidato", "title",
    "source", "fit_tesis", "stage", "mercado_actual", "funding_raised",
    "fit_yc", "valida_idea_propia", "week", "url", "company_url",
]
COLUMN_CONFIG = {
    "passes_gate": st.column_config.CheckboxColumn("Gate", width="small"),
    "score_mostrado": st.column_config.ProgressColumn(
        "Score", min_value=0, max_value=40, format="%d", width="small"
    ),
    "analizado": st.column_config.TextColumn("Análisis", width="small"),
    "tipo_candidato": st.column_config.TextColumn("Tipo", width="small"),
    "title": st.column_config.TextColumn("Idea", width="large"),
    "source": st.column_config.TextColumn("Fuente", width="small"),
    "fit_tesis": st.column_config.TextColumn("Vertical / Industria", width="medium"),
    "stage": st.column_config.TextColumn("Etapa", width="small"),
    "mercado_actual": st.column_config.TextColumn("País", width="small"),
    "funding_raised": st.column_config.TextColumn("Ronda / Funding", width="medium"),
    "fit_yc": st.column_config.TextColumn("Fit YC", width="small"),
    "valida_idea_propia": st.column_config.TextColumn("🎯 Valida idea propia", width="medium"),
    "week": st.column_config.TextColumn("Semana", width="small"),
    "url": st.column_config.LinkColumn("Fuente", width="small", display_text="🔗"),
    "company_url": st.column_config.LinkColumn("Web", width="small", display_text="🌐"),
}

st.caption("Click en una fila para ver el detalle completo abajo. Click en el header de una columna para ordenar.")
event = st.dataframe(
    f[DISPLAY_COLS],
    column_config=COLUMN_CONFIG,
    hide_index=True,
    use_container_width=True,
    height=600,
    on_select="rerun",
    selection_mode="single-row",
)

selected = event.selection.rows if event and event.selection else []
if not selected:
    st.info("👆 Selecciona una idea de la tabla para ver el detalle.")
    st.stop()

row = f.iloc[selected[0]]

# --- Detalle de la idea seleccionada ---
st.divider()
gate_badge = "✅ " if row["passes_gate"] else ""
st.subheader(f"{gate_badge}{row['title']}")
st.caption(f"[{row['source']}] · {row['week']}")

cols = st.columns([3, 1])
with cols[0]:
    st.markdown(f"[Ver original]({row['url']})")
    if row.get("company_url"):
        st.markdown(f"[Web de la empresa]({row['company_url']})")
    if row["has_deep"]:
        if row.get("tipo_candidato"):
            st.caption(f"Tipo: {row['tipo_candidato']}")
        st.write(row["resumen"])
        if row.get("valida_idea_propia"):
            st.warning(f"🎯 **Valida idea propia:** {row['valida_idea_propia']}")
        st.markdown(
            f"**Vertical:** {row['fit_tesis']}  ·  "
            f"**Etapa:** {row.get('stage', '')}  ·  "
            f"**País:** {row.get('mercado_actual', '')}  ·  "
            f"**Funding:** {row.get('funding_raised', '')}"
            + (f"  ·  **Fit YC:** {row['fit_yc']}" if row.get("fit_yc") else "")
        )
        if row.get("fundadores") and row["fundadores"] != "no identificados":
            st.markdown(f"**Fundadores:** {row['fundadores']}")
        if row.get("redes_sociales"):
            st.markdown(f"**Redes:** {row['redes_sociales']}")
        st.markdown(f"**Por qué ahora:** {row.get('por_que_ahora', '')}")
        st.markdown(f"**Modelo de negocio:** {row.get('modelo_negocio', '')}")
        st.markdown(f"**Competencia local:** {row.get('competencia_local', '')}")
        st.markdown(f"**Next step:** {row.get('next_step', '')}")
    else:
        st.caption("Solo triage — sin análisis profundo todavía.")
with cols[1]:
    if not row["has_deep"]:
        disabled = cap_used >= WEEKLY_CAP
        if st.button("🔍 Analizar en profundidad", key=f"deep_{row['url']}", disabled=disabled):
            with st.spinner("Analizando con Claude..."):
                item = Item(
                    source=row["source"], title=row["title"],
                    url=row["url"], text=row.get("text") or "",
                )
                scored, cost = analyze_one(item)
            if scored:
                save_ondemand(row["week"], item, scored, cost)
                st.success(f"Listo (${cost:.4f}). Recargando...")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("El modelo no devolvió un resultado válido.")
        if disabled:
            st.caption("Tope semanal alcanzado")
