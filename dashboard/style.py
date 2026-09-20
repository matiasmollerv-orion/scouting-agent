"""Estilo único del dashboard — el diseño aprobado del Vault aplicado a todo.

Tokens (plano, sin sombras, bordes finos, un solo acento azul):
  página #FFFFFF · tarjeta #FFFFFF (separada por borde fino) · superficie sutil #F5F4EF · borde #E3E1D8
  texto #141413 / #5F5E5A / #87867F · acento #185FA5
  esquinas: 8px controles y métricas, 12px tarjetas
  pills: verde (bueno), azul (medio), ámbar (ojo), rojo (problema), gris (neutro)

El tema base (fuente, colores, radios) está en .streamlit/config.toml; acá van
los retoques que el tema no cubre (tarjetas, métricas, pills, barras) y los
helpers para armar esas piezas con el mismo HTML en todas las páginas.
"""
from __future__ import annotations

import html
import math

import streamlit as st

CSS = """
<style>
:root{
  --v-card:#FFFFFF; --v-sub:#F5F4EF; --v-border:#E3E1D8; --v-border-strong:#CFCDC3;
  --v-text:#141413; --v-text2:#5F5E5A; --v-muted:#87867F; --v-accent:#185FA5;
}
.block-container{padding-top:2.2rem; padding-bottom:3rem; max-width:1240px}
[data-testid="stHeader"]{background:transparent}

/* Tarjetas: contenedores creados con style.card() (clave st-key-vcard_N — el
   nombre interno de los contenedores con borde cambia entre versiones de Streamlit) */
[class*="st-key-vcard_"]{
  background:var(--v-card) !important; border-radius:12px !important;
  border:0.5px solid var(--v-border-strong) !important;
}

/* Métricas: superficie sutil sin borde */
div[data-testid="stMetric"]{
  background:var(--v-sub); border-radius:8px; padding:0.7rem 0.9rem;
}
div[data-testid="stMetricLabel"] p{font-size:0.86rem; color:var(--v-text2)}
div[data-testid="stMetricValue"]{font-size:1.45rem; font-weight:500}
div[data-testid="stMetricValue"] > div{white-space:normal !important; overflow:visible !important;
  text-overflow:clip !important; line-height:1.2}

/* Etiquetas de los multiselect: pills claras en vez del azul sólido del tema */
span[data-baseweb="tag"]{background:#E6F1FB !important; color:#0C447C !important; border-radius:8px !important}
span[data-baseweb="tag"] span, span[data-baseweb="tag"] svg{color:#0C447C !important; fill:#0C447C !important}

/* Botones: contorno fino, sin relleno */
.stButton>button, .stDownloadButton>button, [data-testid="stFormSubmitButton"]>button{
  border:0.5px solid var(--v-border-strong); background:var(--v-card);
  font-weight:400; min-height:2.4rem; box-shadow:none;
}
.stButton>button:hover{background:var(--v-sub); border-color:var(--v-border-strong); color:var(--v-text)}
.stButton>button:active{transform:scale(0.98)}

/* Expanders, alertas, tabs */
div[data-testid="stExpander"] details{
  border:0.5px solid var(--v-border-strong); border-radius:12px; background:var(--v-card);
}
div[data-testid="stAlert"]{border-radius:8px; border:0}
button[data-baseweb="tab"]{font-weight:400}
hr{border-color:var(--v-border) !important; margin:1.1rem 0}

/* Sidebar */
section[data-testid="stSidebar"]{border-right:0.5px solid var(--v-border)}

/* Piezas propias */
.v-lbl{font-size:0.86rem; color:var(--v-text2); margin:0 0 0.3rem}
.v-meta{font-size:0.86rem; color:var(--v-text2); margin:0 0 0.9rem}
.v-pill{display:inline-block; padding:1px 9px; border-radius:8px; font-size:0.86rem;
        font-weight:500; line-height:1.55; white-space:nowrap}
.v-ok{background:#EAF3DE; color:#27500A}
.v-info{background:#E6F1FB; color:#0C447C}
.v-warn{background:#FAEEDA; color:#633806}
.v-bad{background:#FCEBEB; color:#791F1F}
.v-neutral{background:#F1EFE8; color:#444441}
/* Streamlit resta 1rem al último bloque de un st.markdown y pisa su margin-bottom:
   el aire inferior va como padding del envoltorio (1rem compensa + 0.9rem de aire) */
.v-sub-wrap{padding-bottom:1.9rem}
.v-sub{background:var(--v-sub); border-radius:8px; padding:0.65rem 0.8rem}
.v-sub p{margin:0; font-size:0.93rem; overflow-wrap:anywhere}
.v-row-title{margin:0 0 0.2rem; font-weight:500; font-size:1rem; line-height:1.4; overflow-wrap:anywhere}
.v-row-meta{margin:0 !important}
.v-lead{text-align:center; margin:0}
.v-bar{height:6px; border-radius:3px; background:var(--v-sub); overflow:hidden}
.v-bar i{display:block; height:100%; background:var(--v-accent); border-radius:3px}
.v-kv{display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; margin:0 0 0.6rem}
</style>
"""


def inject() -> None:
    """Una vez por ejecución, desde dashboard/app.py (aplica a todas las páginas)."""
    st.session_state["_vcard_n"] = 0  # las claves de card() se reinician en cada ejecución
    st.markdown(CSS, unsafe_allow_html=True)


def card():
    """Tarjeta: contenedor con borde y fondo blanco. Reemplaza st.container(border=True).
    La clave numerada es determinista por orden de creación, así es estable entre reruns."""
    n = st.session_state.get("_vcard_n", 0) + 1
    st.session_state["_vcard_n"] = n
    return st.container(border=True, key=f"vcard_{n}")


def esc(text) -> str:
    return html.escape(str(text)) if text not in (None, "") else ""


def pill(text: str, kind: str = "neutral") -> str:
    """HTML de una pill — kind: ok | info | warn | bad | neutral. Usar con
    st.markdown(..., unsafe_allow_html=True)."""
    return f'<span class="v-pill v-{kind}">{esc(text)}</span>'


def score_kind(score: float | None, hi: float = 7.0, mid: float = 6.0) -> str:
    if score is None:
        return "neutral"
    return "ok" if score >= hi else "info" if score >= mid else "neutral"


def label(text: str) -> None:
    """Etiqueta chica y gris que encabeza el contenido de una tarjeta (como en el boceto)."""
    st.markdown(f'<p class="v-lbl">{esc(text)}</p>', unsafe_allow_html=True)


def meta(*parts, pills: list[tuple[str, str]] | None = None) -> None:
    """Línea de metadatos bajo un título: texto gris con pills opcionales al final."""
    txt = " · ".join(esc(p) for p in parts if p not in (None, ""))
    extra = " ".join(pill(t, k) for t, k in (pills or []))
    st.markdown(f'<p class="v-meta">{txt} {extra}</p>', unsafe_allow_html=True)


def bar(label_text: str, value: float | None, maximum: float = 10.0) -> str:
    """Barra fina con etiqueta (sub-puntajes del consejo)."""
    if value is None:
        return f'<p class="v-lbl">{esc(label_text)} —</p><div class="v-bar"></div>'
    pct = max(0.0, min(100.0, value / maximum * 100))
    return (f'<p class="v-lbl">{esc(label_text)} {value:.0f}</p>'
            f'<div class="v-bar"><i style="width:{pct:.0f}%"></i></div>')


def sub_box(title: str, body_html: str) -> str:
    """Caja gris sutil con título chico — para pares lado a lado dentro de una tarjeta."""
    return (f'<div class="v-sub-wrap"><div class="v-sub"><p class="v-lbl">{esc(title)}</p>'
            f'<p>{body_html}</p></div></div>')


def status_cell_css(kind: str) -> str:
    """CSS de una celda de tabla (pandas Styler) con los colores de las pills."""
    colors = {"ok": ("#EAF3DE", "#27500A"), "info": ("#E6F1FB", "#0C447C"),
              "warn": ("#FAEEDA", "#633806"), "bad": ("#FCEBEB", "#791F1F"),
              "neutral": ("#F1EFE8", "#444441")}
    bg, fg = colors.get(kind, colors["neutral"])
    return f"background-color:{bg};color:{fg};font-weight:500"


# --- Lista de filas-tarjeta (reemplaza las tablas: una tabla de Streamlit no puede
# envolver texto ni alargar filas, así que el texto largo siempre salía cortado) ----

def pager(key: str, total: int, page_size: int = 15, sig: str = "", pos: str = "top") -> tuple[int, int]:
    """Paginador. `sig` identifica el filtro/orden actual: si cambia vuelve a la página 1.
    Devuelve (inicio, fin) para cortar la lista. `pos` distingue el paginador de arriba
    y el de abajo (los dos comparten estado)."""
    pages = max(1, math.ceil(total / page_size))
    skey, gkey = f"{key}_page", f"{key}_sig"
    if st.session_state.get(gkey) != sig:
        st.session_state[gkey] = sig
        st.session_state[skey] = 0
    page = max(0, min(st.session_state.get(skey, 0), pages - 1))
    if pages > 1:
        c1, c2, c3 = st.columns([1, 2, 1], vertical_alignment="center")
        if c1.button("Anterior", icon=":material/chevron_left:", key=f"{key}_prev_{pos}",
                     disabled=page == 0, use_container_width=True):
            st.session_state[skey] = page - 1
            st.rerun()
        c2.markdown(f'<p class="v-meta" style="text-align:center;margin:0">Página {page + 1} de {pages}'
                    f' · {total} en total</p>', unsafe_allow_html=True)
        if c3.button("Siguiente", icon=":material/chevron_right:", key=f"{key}_next_{pos}",
                     disabled=page >= pages - 1, use_container_width=True):
            st.session_state[skey] = page + 1
            st.rerun()
    return page * page_size, min(total, (page + 1) * page_size)


def row(key: str, *, title: str, meta: str = "", lead_html: str = "",
        pills: list[tuple[str, str]] | None = None, fav: bool | None = None,
        open_label: str = "Abrir") -> str | None:
    """Fila-tarjeta con el TEXTO COMPLETO (envuelve, la fila crece). Devuelve "open",
    "fav" o None según el botón que se apretó. `fav` = None oculta la estrella."""
    action = None
    with card():
        widths = [1, 9, 2] if fav is None else [1, 8, 1.6, 1.6]
        cols = st.columns(widths, vertical_alignment="center")
        cols[0].markdown(f'<p class="v-lead">{lead_html}</p>', unsafe_allow_html=True)
        chips = " ".join(pill(t, k) for t, k in (pills or []))
        cols[1].markdown(f'<p class="v-row-title">{esc(title)}</p>'
                         f'<p class="v-meta v-row-meta">{esc(meta)} {chips}</p>', unsafe_allow_html=True)
        if fav is not None and cols[2].button(
                "Favorita" if fav else "Marcar", icon=":material/star:", key=f"{key}_fav",
                type="primary" if fav else "secondary", use_container_width=True):
            action = "fav"
        if cols[-1].button(open_label, key=f"{key}_open", use_container_width=True):
            action = "open"
    return action
