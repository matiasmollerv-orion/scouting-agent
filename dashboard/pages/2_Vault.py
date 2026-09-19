"""Vault del Oracle — semillas de idea minadas cada mes por país × lente y
puntuadas por el consejo (src/oracle, scripts/oracle_run.py).

Es también donde vive el aprendizaje: cada veredicto de un clic (Profundizar /
Guardar / Descartar) con su motivo se guarda en scouting_lessons y el consejo lo
lee en la próxima corrida para calibrar tu gusto. "Profundizar" encola solo el
análisis de mercado (sin gastar: eso sigue siendo un paso manual aparte).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
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

from dashboard.db import (
    add_lesson, fetch_oracle_runs, fetch_vault, queue_market_analysis, update_vault,
)
from dashboard import style
from dashboard.textutils import clean

st.set_page_config(page_title="Vault de ideas", page_icon=":material/inventory_2:", layout="wide")
st.title(":material/inventory_2: Vault de ideas")
st.caption(
    "Necesidades detectadas cada mes por país × lente (quejas, brechas, fuerzas externas y "
    "ofertas de otros mercados) y puntuadas por un consejo de críticos. Tu veredicto de un "
    "clic — con motivo — calibra las próximas corridas."
)

STATUS_LABEL = {
    "nueva": "sin puntuar", "en_vault": "en vault", "guardada": "guardada",
    "elegida": "elegida", "descartada": "descartada", "descartada_consejo": "bajo umbral",
}
STATUS_KIND = {"sin puntuar": "warn", "en vault": "ok", "guardada": "info",
               "elegida": "info", "descartada": "neutral", "bajo umbral": "neutral"}
SENAL_LABEL = {"queja": "Queja", "brecha": "Brecha", "fuerza_externa": "Fuerza externa", "oferta": "Oferta"}
REASONS = ["—", "Ya está resuelto / mucha competencia", "Mercado muy chico", "No me interesa el tema",
           "Difícil de ejecutar", "Poca evidencia", "No se puede transferir a Chile/LatAm", "Otro"]


@st.cache_data(ttl=30)
def _load() -> list[dict]:
    return fetch_vault()


try:
    rows = _load()
except Exception as e:  # noqa: BLE001
    st.error(
        "No pude leer el Vault. Lo más probable: falta crear las tablas del Oracle en Supabase "
        "(`scouting_vault`, `scouting_lessons`, `scouting_oracle_runs`, al final de "
        "`dashboard/schema.sql`)."
    )
    st.caption(f"Detalle: {str(e)[:300]}")
    st.stop()

with st.expander(":material/event_repeat: Corridas del Oracle"):
    try:
        runs = fetch_oracle_runs()
        if runs:
            st.dataframe(pd.DataFrame(runs)[["month_key", "status", "pairs", "seeds", "cost_usd", "finished_at"]],
                         hide_index=True, use_container_width=True)
        else:
            st.caption("Todavía no hay corridas.")
    except Exception:  # noqa: BLE001
        st.caption("Sin registro de corridas todavía.")

if not rows:
    st.info("El Vault está vacío — la primera corrida del Oracle todavía no ocurrió.")
    st.stop()

df = pd.DataFrame(rows)
for _c in ("score", "s_evidencia", "s_tamano", "s_ahora", "s_hueco", "s_testeabilidad", "bonus_fit"):
    df[_c] = pd.to_numeric(df[_c], errors="coerce")
df["estado"] = df["status"].map(lambda s: STATUS_LABEL.get(s, s))
df["señal"] = df["tipo_senal"].map(lambda s: SENAL_LABEL.get(s, s or "—"))

c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
default_status = [s for s in ("en_vault", "guardada", "nueva") if s in set(df["status"])]
sel_status = c1.multiselect("Estado", list(STATUS_LABEL), default=default_status,
                            format_func=lambda s: STATUS_LABEL[s])
sel_lens = c2.multiselect("Lente", sorted(df["lens"].dropna().unique()))
sel_country = c3.multiselect("País", sorted(df["country"].dropna().unique()))
min_score = c4.number_input("Score mín.", 0.0, 10.0, 0.0, 0.5)

f = df[df["status"].isin(sel_status)] if sel_status else df
if sel_lens:
    f = f[f["lens"].isin(sel_lens)]
if sel_country:
    f = f[f["country"].isin(sel_country)]
f = f[f["score"].fillna(0) >= min_score].sort_values("score", ascending=False, na_position="last").reset_index(drop=True)

st.caption(f"{len(f)} de {len(df)} semillas")
if f.empty:
    st.info("Nada con esos filtros.")
    st.stop()

view = f[["score", "country", "lens", "señal", "necesidad", "estado"]].copy()
view["necesidad"] = view["necesidad"].str.slice(0, 110)
view.columns = ["Score", "País", "Lente", "Señal", "Necesidad", "Estado"]
styled = (view.style
          .map(lambda v: style.status_cell_css(style.score_kind(v)) if pd.notna(v) else "", subset=["Score"])
          .map(lambda v: style.status_cell_css(STATUS_KIND.get(v, "neutral")), subset=["Estado"])
          .format({"Score": lambda v: f"{v:.1f}" if pd.notna(v) else "—"}))
event = st.dataframe(styled, hide_index=True, use_container_width=True,
                     height=min(420, 40 + 35 * len(view)),
                     on_select="rerun", selection_mode="single-row")
selected = event.selection.rows if event and event.selection else []
if not selected or selected[0] >= len(f):
    st.info("Selecciona una semilla para ver el detalle y darle veredicto.")
    st.stop()

row = f.iloc[selected[0]]


def g(k):
    """Valor de la fila o None (los nulos de la tabla llegan como NaN, que es truthy)."""
    v = row.get(k)
    return None if (v is None or (not isinstance(v, str) and pd.isna(v))) else v


sid = int(row["id"])
st.divider()
st.subheader(clean(row["necesidad"]))
style.meta(row["country"], row["lens"], f"señal: {row['señal']}", row["run_month"], g("modelo"),
           pills=[(row["estado"], STATUS_KIND.get(row["estado"], "neutral"))])

if pd.notna(g("score")):
    sc, bars = st.columns([1, 4], gap="large")
    sc.metric("Score", f"{row['score']:.1f}")
    for col, (lbl, key) in zip(bars.columns(5), [("Evidencia", "s_evidencia"), ("Tamaño", "s_tamano"),
                                                 ("Ahora", "s_ahora"), ("Hueco", "s_hueco"),
                                                 ("Testeable", "s_testeabilidad")]):
        col.markdown(style.bar(lbl, row[key] if pd.notna(g(key)) else None), unsafe_allow_html=True)
    if pd.notna(g("bonus_fit")) and row["bonus_fit"] > 0:
        st.caption(f"El score incluye +{row['bonus_fit']:.1f} por encaje con tu perfil (solo suma, nunca resta). "
                   "Ahora = por qué ahora; Hueco = espacio libre frente a los incumbentes.")

with style.card():
    style.label("Quién y evidencia")
    st.markdown(f"**Quién:** {clean(g('quien')) or '—'}")
    st.markdown(clean(g("evidencia")) or "—")
    url = g("fuente_url")
    if url:
        badge = {"ok": style.pill("la fuente resuelve", "ok"),
                 "bloqueada": style.pill("el sitio bloquea la verificación", "neutral"),
                 "rota": style.pill("la fuente no resuelve", "warn")}.get(g("url_estado"), "")
        st.markdown(f"[Fuente]({url}) &nbsp; {badge}", unsafe_allow_html=True)

with style.card():
    style.label("Ya existe y transferencia a Chile y LatAm")
    c1, c2 = st.columns(2, gap="medium")
    c1.markdown(style.sub_box("Quién ya lo resuelve", style.esc(g("solucion_existente") or "—")),
                unsafe_allow_html=True)
    c2.markdown(style.sub_box("Transferencia", style.esc(g("transferencia") or "—")),
                unsafe_allow_html=True)

if g("objeciones"):
    with style.card():
        style.label("Objeciones del consejo")
        for o in str(row["objeciones"]).split(" | "):
            if o.strip():
                st.markdown(f"- {clean(o)}")
        if g("veredicto_consejo"):
            st.caption(f"Veredicto: {clean(row['veredicto_consejo'])}")

st.divider()
if g("human_verdict"):
    st.info(f"Ya le diste veredicto: **{row['human_verdict']}**"
            + (f" — {clean(row['human_reason'])}" if g("human_reason") else "")
            + ". Puedes cambiarlo abajo.")

style.label("Tu veredicto")
r1, r2 = st.columns([1, 2])
reason_choice = r1.selectbox("Motivo (alimenta al consejo)", REASONS, key=f"rc_{sid}")
reason_free = r2.text_input("Detalle (opcional)", key=f"rf_{sid}")
reason = " — ".join(x for x in (reason_choice if reason_choice != "—" else "", reason_free.strip()) if x)
snapshot = f"{row['necesidad']} ({row['country']} × {row['lens']})"[:300]


def _verdict(kind: str, status: str, **extra) -> None:
    update_vault(sid, status=status, human_verdict=kind, human_reason=reason or None,
                 verdict_at=datetime.now(timezone.utc).isoformat(), **extra)
    add_lesson(kind, reason, snapshot)
    st.cache_data.clear()
    st.rerun()


b1, b2, b3 = st.columns(3)
if b1.button("Profundizar", icon=":material/target:", key=f"b1_{sid}", use_container_width=True):
    hint = (f"Semilla del Oracle ({row['country']} × {row['lens']}, señal: {row['señal']}).\n\n"
            f"- Necesidad: {row['necesidad']}\n- Quién: {g('quien') or '—'}\n"
            f"- Evidencia: {g('evidencia') or '—'}\n"
            f"- Transferencia a Chile/LatAm: {g('transferencia') or '—'}")
    mid = queue_market_analysis(
        market_name=str(row["necesidad"])[:200], origen="vault", beachhead_hint=hint,
        context_note=f"Fuente: {g('fuente_url') or '—'}. Consejo: {g('veredicto_consejo') or '—'}",
    )
    _verdict("elegida", "elegida", market_analysis_id=mid)
if b2.button("Guardar", icon=":material/bookmark:", key=f"b2_{sid}", use_container_width=True):
    _verdict("guardada", "guardada")
if b3.button("Descartar", icon=":material/delete:", key=f"b3_{sid}", use_container_width=True):
    _verdict("descartada", "descartada")
st.caption("Profundizar solo encola el análisis de mercado (gratis); correrlo sigue siendo un paso manual aparte.")
