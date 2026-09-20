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
from dashboard.db import (
    WEEKLY_CAP, add_favorite, count_this_week, fetch_favorites, fetch_market_analyses,
    fetch_ondemand, remove_favorite, save_ondemand,
)
from dashboard import style
from dashboard.deep_single import analyze_one
from dashboard.textutils import clean
from src.models import Item

st.set_page_config(page_title="Scouting de ideas", page_icon=":material/search:", layout="wide")
st.title(":material/search: Scouting de ideas de negocio")
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


@st.cache_data(ttl=30)
def _load_favorites() -> tuple[dict, str | None]:
    """(favoritas, error). El error NO se traga: 2026-09-20 se descubrió que la tabla
    scouting_favorites nunca se había creado y la página lo ocultaba en silencio, así
    que marcar favoritas parecía "no funcionar" sin ningún aviso."""
    try:
        return fetch_favorites(), None
    except Exception as e:  # noqa: BLE001
        return {}, f"{type(e).__name__}: {str(e)[:220]}"


@st.cache_data(ttl=30)
def _load_market_by_source_url() -> dict:
    """Indexado por source_url (no por id) — así una fila de la tabla
    principal sabe si YA tiene un análisis de mercado pedido, sea cual sea
    su estado (queued/analizando/listo/error)."""
    try:
        rows = fetch_market_analyses()
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        su = r.get("source_url")
        if su and su not in out:  # más reciente primero, ya viene ordenado así
            out[su] = r
    return out


df = _load()
ondemand = _load_ondemand()
favorites, fav_load_error = _load_favorites()
market_by_url = _load_market_by_source_url()

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
                "modelo_negocio", "competencia_local", "competencia_global",
                "stage", "funding_raised", "company_url", "mercado_actual",
                "valida_idea_propia", "fundadores", "redes_sociales",
                "fit_yc", "tipo_candidato"]:
        df.loc[mask, col] = row.get(col, "")

# Columnas derivadas (sobre TODO el df, así la lista y el detalle las comparten).
df["score_mostrado"] = df["objetivo_total"].where(df["has_deep"], df["triage_total"])
df["analizado"] = df["has_deep"].map({True: "Profundo", False: "Triage"})
df["favorita"] = df["url"].isin(favorites)
_MARKET_BADGE = {"queued": "en cola", "analizando": "analizando",
                 "listo": "listo", "error": "error"}
_MARKET_KIND = {"queued": "warn", "analizando": "info", "listo": "ok", "error": "bad"}

if fav_load_error:
    st.warning(
        "Las favoritas no están disponibles: no pude leer la tabla `scouting_favorites` en "
        f"Supabase (¿falta crearla? el SQL está en `dashboard/schema.sql`). Detalle: {fav_load_error}",
        icon=":material/warning:",
    )
if st.session_state.get("fav_error"):
    st.error(f"No pude guardar la favorita. {st.session_state.pop('fav_error')}")


def _toggle_fav(url: str, title: str, is_fav: bool) -> None:
    try:
        remove_favorite(url) if is_fav else add_favorite(url, title)
    except Exception as e:  # noqa: BLE001
        st.session_state["fav_error"] = f"{type(e).__name__}: {str(e)[:220]}"
        st.rerun()
    st.cache_data.clear()
    st.rerun()


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

# "Tipo" (tipo_candidato) SOLO lo llena el análisis profundo — un candidato
# que quedó en triage (la mayoría: ~8 de 150/semana pasan a profundo) nunca
# tiene tipo_candidato, no es que falte poblarlo. Se filtra igual que
# fit_tesis; las filas solo-triage sin tipo quedan afuera si se elige algo acá.
tipo_options = sorted(t for t in df["tipo_candidato"].dropna().unique() if t)
tipo_sel = st.sidebar.multiselect(
    "Tipo", tipo_options,
    help="Solo lo tienen las ideas con análisis PROFUNDO — las de solo-triage "
         "quedan sin tipo porque esa etapa no lo calcula.",
)

source_options = sorted(df["source"].dropna().unique())
source_sel = st.sidebar.multiselect("Fuente", source_options)

score_range = st.sidebar.slider("Score objetivo (0-40)", 0, 40, (0, 40))

incluir_triage = st.sidebar.checkbox(
    "Incluir ideas solo-triage (sin análisis profundo)", value=True
)
solo_gate = st.sidebar.checkbox("Solo sobre el gate", value=False)
solo_favoritas = st.sidebar.checkbox("Solo favoritas", value=False)
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
if tipo_sel:
    f = f[f["tipo_candidato"].isin(tipo_sel)]
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
if solo_favoritas:
    f = f[f["url"].isin(favorites)]
if busqueda:
    f = f[f["title"].str.contains(busqueda, case=False, na=False)]


def _dash(v) -> str:
    return clean(v) if v not in (None, "") else "—"


def show_detail(row) -> None:
    """Detalle de una idea (tarjetas, mismo diseño que el Vault)."""
    if st.button("Volver a la lista", icon=":material/arrow_back:", key="scout_back"):
        st.session_state.pop("scout_sel", None)
        st.rerun()
    left, right = st.columns([3, 1], gap="medium")
    with left:
        st.subheader(clean(row["title"]))
        style.meta(row["source"], row["week"],
                   pills=[("sobre el gate", "ok")] if row["passes_gate"] else [])
        score = row["score_mostrado"]
        m = st.columns(4)
        m[0].metric("Score", f"{score:.0f}/40" if pd.notna(score) else "—")
        for col, (lbl, val) in zip(m[1:], [("Análisis", row["analizado"]), ("Fit YC", row.get("fit_yc")),
                                           ("País", row.get("mercado_actual"))]):
            col.markdown(style.sub_box(lbl, style.esc(val or "—")), unsafe_allow_html=True)
        links = [f"[Ver original]({row['url']})"]
        if row.get("company_url"):
            links.append(f"[Web de la empresa]({row['company_url']})")
        st.markdown("  ·  ".join(links))

        if row["has_deep"]:
            with style.card():
                style.label("Resumen")
                st.write(clean(row["resumen"]))
                if row.get("valida_idea_propia"):
                    st.info(f"Valida idea propia: {clean(row['valida_idea_propia'])}",
                            icon=":material/target:")

            c1, c2 = st.columns(2, gap="medium")
            with c1, style.card():
                style.label("Contexto")
                st.markdown(f"**Vertical:** {_dash(row['fit_tesis'])}")
                st.markdown(f"**Etapa:** {_dash(row.get('stage'))}")
                st.markdown(f"**Funding:** {_dash(row.get('funding_raised'))}")
                if row.get("tipo_candidato"):
                    st.markdown(f"**Tipo:** {_dash(row['tipo_candidato'])}")
                if row.get("fundadores") and row["fundadores"] != "no identificados":
                    st.markdown(f"**Fundadores:** {_dash(row['fundadores'])}")
                if row.get("redes_sociales"):
                    st.markdown(f"**Redes:** {_dash(row['redes_sociales'])}")
            with c2, style.card():
                style.label("Mercado y competencia")
                st.markdown(f"**Por qué ahora:** {_dash(row.get('por_que_ahora'))}")
                st.markdown(f"**Modelo de negocio:** {_dash(row.get('modelo_negocio'))}")
                st.markdown(f"**Competencia local:** {_dash(row.get('competencia_local'))}")
                comp_global = row.get("competencia_global", "")
                if comp_global and comp_global not in ("no identificada", "no verificado"):
                    st.error(f"Competencia global real: {clean(comp_global)} — no es blue ocean.",
                             icon=":material/warning:")
                elif comp_global:
                    st.markdown(f"**Competencia global:** {_dash(comp_global)}")

            with style.card():
                style.label("Siguiente paso")
                st.write(clean(row.get("next_step", "")) or "—")
        else:
            st.caption("Solo triage — sin análisis profundo todavía.")

    with right, style.card():
        style.label("Acciones")
        es_favorita = row["url"] in favorites
        if st.button("Quitar de favoritas" if es_favorita else "Marcar favorita",
                     icon=":material/star:", key=f"fav_{row['url']}", use_container_width=True,
                     type="primary" if es_favorita else "secondary"):
            _toggle_fav(row["url"], row["title"], es_favorita)
        if not row["has_deep"]:
            disabled = cap_used >= WEEKLY_CAP
            if st.button("Analizar en profundidad", icon=":material/manage_search:",
                         key=f"deep_{row['url']}", disabled=disabled, use_container_width=True):
                with st.spinner("Analizando con Claude..."):
                    item = Item(
                        source=row["source"], title=row["title"],
                        url=row["url"], text=row.get("text") or "",
                    )
                    scored, cost = analyze_one(item)
                if scored:
                    save_ondemand(row["week"], item, scored, cost)
                    st.success(f"Listo (\\${cost:.4f}). Recargando...")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("El modelo no devolvió un resultado válido.")
            if disabled:
                st.caption("Tope semanal alcanzado")

        st.divider()
        existing_market = market_by_url.get(row["url"])
        if existing_market:
            status = existing_market["status"]
            style.label("Ya usada como referente en un análisis de mercado")
            st.markdown(style.pill(_MARKET_BADGE.get(status, status), _MARKET_KIND.get(status, "neutral")),
                        unsafe_allow_html=True)
            st.caption(clean(existing_market["market_name"]))
            st.page_link("pages/1_Analisis_de_Mercado.py", label="Ver en Análisis de mercado",
                         icon=":material/arrow_forward:")
        else:
            st.caption("El análisis de mercado no es sobre esta empresa puntual: es sobre el mercado "
                       "que representa. Se define en la pantalla dedicada.")
            if st.button("Usar como referente", icon=":material/analytics:",
                         key=f"market_{row['url']}", use_container_width=True):
                st.session_state["market_prefill"] = {
                    "empresas_referentes": row["title"],
                    "source_url": row["url"],
                    "origen": "dashboard",
                }
                st.switch_page("pages/1_Analisis_de_Mercado.py")


# --- Detalle (si hay una idea abierta) o lista de tarjetas ---
selected_url = st.session_state.get("scout_sel")
if selected_url:
    hit = df[df["url"] == selected_url]
    if hit.empty:
        st.session_state.pop("scout_sel", None)
    else:
        show_detail(hit.iloc[0])
        st.stop()

orden_col, _ = st.columns([1, 3])
orden = orden_col.selectbox("Ordenar por", ["Mayor score", "Más recientes"], key="scout_order")
if orden == "Más recientes":
    f = f.sort_values(["week_date", "objetivo_total"], ascending=[False, False], na_position="last")
else:
    f = f.sort_values(["has_deep", "objetivo_total", "triage_total"], ascending=[False, False, False])
f = f.reset_index(drop=True)

st.caption(f"{len(f)} ideas mostradas · {len(df)} evaluadas en total desde que corre el sistema")
if f.empty:
    st.info("Ningún resultado con estos filtros.")
    st.stop()

sig = str((orden, date_range, fit_sel, tipo_sel, source_sel, score_range, incluir_triage,
           solo_gate, solo_favoritas, busqueda))
start_i, end_i = style.pager("scout", len(f), 15, sig, "top")
for i in range(start_i, end_i):
    r = f.iloc[i]
    score = r["score_mostrado"]
    lead = style.pill(f"{score:.0f}", "ok" if score >= 28 else "info" if score >= 24 else "neutral") \
        if pd.notna(score) else style.pill("—")
    chips = [(r["analizado"], "info" if r["has_deep"] else "neutral")]
    if r["passes_gate"]:
        chips.append(("sobre el gate", "ok"))
    market = market_by_url.get(r["url"])
    if market:
        chips.append((f"mercado: {_MARKET_BADGE.get(market['status'], market['status'])}",
                      _MARKET_KIND.get(market["status"], "neutral")))
    meta = " · ".join(x for x in (r["source"], r["week"], r["fit_tesis"] or "", r["mercado_actual"] or "") if x)
    action = style.row(f"scout_{i}", title=r["title"], meta=meta, lead_html=lead, pills=chips,
                       fav=bool(r["favorita"]))
    if action == "open":
        st.session_state["scout_sel"] = r["url"]
        st.rerun()
    elif action == "fav":
        _toggle_fav(r["url"], r["title"], bool(r["favorita"]))
style.pager("scout", len(f), 15, sig, "bottom")
