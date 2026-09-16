"""Entry point del dashboard — SOLO declara las páginas y las corre.

2026-09: antes dependíamos del auto-scan de la carpeta `pages/` (la
convención "mágica" de Streamlit) — dejó de detectarse en Streamlit Cloud
(la página nueva no aparecía ni con reboot/rerun). Con `st.navigation` +
`st.Page` las páginas se declaran explícitas acá, sin depender de que
Streamlit escanee el árbol de archivos solo.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import streamlit as st  # noqa: E402

# Toque de legibilidad global, no animación — Streamlit no da control fino
# de transiciones/CSS por componente sin meter componentes custom, y ambas
# páginas usan layout="wide" a propósito (tablas de candidatos, comparador
# lado a lado) — así que NO forzamos un max-width que las rompería. Solo
# consistencia de borde entre las cards (st.container(border=True)).
st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

pg = st.navigation([
    st.Page(DASHBOARD_DIR / "main_page.py", title="Scouting de Ideas",
            icon="🔍", default=True),
    st.Page(DASHBOARD_DIR / "pages" / "1_Analisis_de_Mercado.py",
            title="Análisis de Mercado", icon="📊"),
])
pg.run()
