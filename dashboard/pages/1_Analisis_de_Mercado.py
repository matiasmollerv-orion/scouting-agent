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
import re
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

from dashboard import style
from dashboard.db import fetch_market_analyses, queue_market_analysis

st.set_page_config(page_title="Análisis de mercado", page_icon=":material/analytics:", layout="wide")
st.title(":material/analytics: Análisis de mercado")
st.caption(
    "No es análisis de UNA empresa — es del MERCADO/oportunidad que una o más "
    "empresas de referencia ilustran. Metodología fija de 8 pasos: beachhead "
    "(Aulet) → TAM bottom-up + top-down → competencia (Porter) → dolor (JTBD) "
    "→ WTP → fit fundador → RAT → regulación."
)

STATUS_BADGE = {"queued": "en cola", "analizando": "analizando",
                "listo": "listo", "error": "error"}
STATUS_KIND = {"en cola": "warn", "analizando": "info", "listo": "ok", "error": "bad"}

FIELD_LABELS = {
    "beachhead_definido": "1. Beachhead definido",
    "tam_bottom_up": "2a. TAM bottom-up (el número que manda)",
    "tam_top_down": "2b. TAM top-down (sanity check)",
    "discrepancia_tam": "Discrepancia TAM (si aplica)",
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

# TAM y WTP se renderizan aparte (número grande + metodología colapsable) —
# el resto de los campos usa la card de texto genérica. Ver _render_money_field.
GENERIC_FIELD_GROUPS = [
    ("1 · Beachhead", ["beachhead_definido"]),
    ("3 · Competencia", ["competencia_global", "competencia_local", "competencia_en_beachhead_especifico"]),
    ("4 · Dolor (JTBD)", ["dolor_jtbd"]),
    ("6 · Fit fundador", ["fit_fundador"]),
    ("7 · RAT", ["rat_supuesto", "rat_prueba_barata"]),
    ("8 · Regulación", ["regulacion"]),
]

# --- Limpieza y extracción de texto generado por el modelo -----------------
# Dos bugs reales encontrados 2026-09-16 con datos pagados reales:
# (1) Streamlit interpreta "$..$" como fórmula LaTeX por default — cualquier
#     monto en dólares en el texto ("US$12-13M/año") rompe el render entero.
#     Se escapa "$" ANTES de pasar por st.markdown/st.caption (st.metric no
#     necesita esto, su value nunca se interpreta como markdown).
# (2) El texto trae tags crudos <cite index="50-1">...</cite> de las citas
#     de búsqueda web — se sacan los tags, se deja el texto citado.
_CITE_RE = re.compile(r"</?cite[^>]*>", re.IGNORECASE)


def _clean(text) -> str:
    """Texto listo para st.markdown/st.caption/st.info — sin tags de cita,
    sin que Streamlit intente leer los montos en dólares como LaTeX."""
    if not text:
        return ""
    text = _CITE_RE.sub("", str(text))
    return text.replace("$", "\\$")


# Convención NUEVA para corridas futuras (ver prompts/market_analysis.md):
# el campo debe arrancar con "**Número: <valor>**" en su propia línea — eso
# hace la extracción exacta, sin adivinar. Para los 5 análisis ya pagados el
# 2026-09-16 (corridos ANTES de este fix) no existe esa línea, así que cae
# al heurístico de regex — mejor esfuerzo, no perfecto, pero no amerita
# volver a gastar en la API solo para reformatear texto que ya existe.
_HEADLINE_RE = re.compile(r"^\*\*Número:\s*(.+?)\*\*", re.IGNORECASE | re.MULTILINE)
_MONEY_USD_RE = re.compile(
    r"(?:USD?\$|US\s?\$|USD)\s?[\d][\d.,]*(?:\s?[-–a]\s?[\d][\d.,]*)?\s?[kKmMbB]?"
    r"(?:/(?:año|mes|year|month))?"
)
_MONEY_ANY_RE = re.compile(
    r"(?:CLP|EUR|€|USD?\$|US\s?\$|USD)\s?[\d][\d.,]*(?:\s?[-–a]\s?[\d][\d.,]*)?\s?[kKmMbB]?"
    r"(?:/(?:año|mes|year|month))?"
)


def _headline(text) -> str | None:
    """Mejor esfuerzo para sacar EL número de un campo largo — prioriza la
    línea explícita "**Número: ...**" (formato nuevo), si no existe busca el
    ÚLTIMO monto en USD mencionado (el modelo suele cerrar con el total: "...
    TOTAL BOTTOM-UP: ~US$15-16M/año"), si no hay USD cae a cualquier moneda."""
    if not text:
        return None
    text = str(text)
    m = _HEADLINE_RE.search(text)
    if m:
        return m.group(1).strip()
    usd = _MONEY_USD_RE.findall(text)
    if usd:
        return usd[-1].strip()
    any_money = _MONEY_ANY_RE.findall(text)
    return any_money[-1].strip() if any_money else None


def _short(name: str, n: int = 42) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


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
label = (":material/add: Nuevo análisis de mercado" if not prefill
         else ":material/add: Nuevo análisis de mercado (con referente pre-cargado)")
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
        if st.form_submit_button("Encolar"):
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

tab_lista, tab_comparar = st.tabs([":material/list: Lista", ":material/compare_arrows: Comparar"])

with tab_lista:
    display = df[["estado", "market_name", "empresas_referentes", "origen", "requested_at", "cost_usd"]].copy()
    display.columns = ["Estado", "Mercado/oportunidad", "Referentes", "Origen", "Pedido", "Costo USD"]
    styled = display.style.map(
        lambda v: style.status_cell_css(STATUS_KIND.get(v, "neutral")), subset=["Estado"])
    event = st.dataframe(
        styled, hide_index=True, use_container_width=True,
        on_select="rerun", selection_mode="single-row",
    )
    selected = event.selection.rows if event and event.selection else []
    if not selected or selected[0] >= len(df):
        st.info("Selecciona una fila para ver el detalle completo.")
    else:
        row = df.iloc[selected[0]]
        st.markdown(f"### {_clean(row['market_name'])}")
        state = STATUS_BADGE.get(row["status"], row["status"])
        bits = [f"pedido {str(row['requested_at'])[:10]}"]
        if pd.notna(row.get("cost_usd")):
            bits.append(f"costo ${row['cost_usd']:.2f}")
        if row.get("empresas_referentes"):
            bits.append(f"referentes: {row['empresas_referentes']}")
        style.meta(*bits, pills=[(state, STATUS_KIND.get(state, "neutral"))])

        if row.get("beachhead_hint"):
            with style.card():
                style.label("Hipótesis de beachhead dada")
                st.markdown(_clean(row["beachhead_hint"]))
        if row.get("context_note"):
            with style.card():
                style.label("Contexto adicional dado")
                st.markdown(_clean(row["context_note"]))

        if row["status"] == "error":
            st.error(f"Error: {_clean(row.get('error_detail', 'sin detalle'))}")
        elif row["status"] in ("queued", "analizando"):
            st.warning("Todavía no tiene resultado — falta correr "
                       "`scripts/market_analysis.py` (siempre manual).")
        else:
            st.divider()

            # --- 1. Beachhead (genérico) ---
            group_label, fields = GENERIC_FIELD_GROUPS[0]
            with style.card():
                style.label(group_label)
                st.markdown(_clean(row.get(fields[0])) or "—")

            # --- 2. TAM — número grande primero, metodología colapsada ---
            with style.card():
                style.label("2 · TAM")
                c1, c2 = st.columns(2)
                with c1:
                    st.metric("Bottom-up (el número que manda)", _headline(row.get("tam_bottom_up")) or "—")
                with c2:
                    st.metric("Top-down (sanity check)", _headline(row.get("tam_top_down")) or "—")
                if row.get("discrepancia_tam"):
                    st.warning(_clean(row["discrepancia_tam"]))
                with st.expander("Ver cómo se calculó"):
                    st.markdown("**Bottom-up:**")
                    st.markdown(_clean(row.get("tam_bottom_up")) or "—")
                    st.markdown("**Top-down:**")
                    st.markdown(_clean(row.get("tam_top_down")) or "—")

            # --- 3-4. Competencia + Dolor (genéricos) ---
            for group_label, fields in GENERIC_FIELD_GROUPS[1:3]:
                with style.card():
                    style.label(group_label)
                    for field in fields:
                        if len(fields) > 1:
                            st.markdown(f"**{FIELD_LABELS[field].split('. ', 1)[-1]}**")
                        st.markdown(_clean(row.get(field)) or "—")

            # --- 5. WTP — número grande primero, metodología colapsada ---
            with style.card():
                style.label("5 · Disposición a pagar")
                st.metric("WTP estimado (por comparables)", _headline(row.get("wtp_estimado")) or "—")
                with st.expander("Ver cómo se estimó"):
                    st.markdown(_clean(row.get("wtp_estimado")) or "—")
                st.markdown("**WTP validado (30-50 entrevistas)**")
                if row.get("wtp_validado"):
                    st.markdown(_clean(row["wtp_validado"]))
                else:
                    st.caption("Vacío — pendiente de entrevistas reales (Customer Development).")

            # --- 6-8. Fit fundador + RAT + Regulación (genéricos) ---
            for group_label, fields in GENERIC_FIELD_GROUPS[3:]:
                with style.card():
                    style.label(group_label)
                    for field in fields:
                        if len(fields) > 1:
                            st.markdown(f"**{FIELD_LABELS[field].split('. ', 1)[-1]}**")
                        st.markdown(_clean(row.get(field)) or "—")

with tab_comparar:
    listas = df[df["status"] == "listo"]
    if listas.empty:
        st.info("Necesitás al menos un análisis con estado 'listo' para comparar.")
    else:
        opciones = listas["market_name"].tolist()
        elegidas = st.multiselect("Elegí 2 o más para comparar lado a lado", opciones)
        if len(elegidas) >= 2:
            by_name = {r["market_name"]: r for r in listas[listas["market_name"].isin(elegidas)].to_dict("records")}

            style.label("Números clave, lado a lado")
            cols = st.columns(len(elegidas))
            for col, name in zip(cols, elegidas):
                row = by_name[name]
                with col:
                    st.markdown(f"**{_clean(_short(name))}**")
                    st.metric("TAM bottom-up", _headline(row.get("tam_bottom_up")) or "—")
                    st.metric("TAM top-down", _headline(row.get("tam_top_down")) or "—")
                    st.metric("WTP estimado", _headline(row.get("wtp_estimado")) or "—")

            st.divider()
            style.label("Comparar un paso específico en detalle")
            campo = st.selectbox(
                "Elegí qué campo comparar", list(FIELD_LABELS.keys()),
                format_func=lambda k: FIELD_LABELS[k],
            )
            cols2 = st.columns(len(elegidas))
            for col, name in zip(cols2, elegidas):
                row = by_name[name]
                with col:
                    st.markdown(f"**{_clean(_short(name))}**")
                    with style.card():
                        val = row.get(campo)
                        st.markdown(_clean(val) if val else "—")
        elif elegidas:
            st.caption("Elegí al menos 2 para comparar.")
