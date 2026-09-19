"""Entry point del dashboard — SOLO declara las páginas y las corre.

2026-09: antes dependíamos del auto-scan de la carpeta `pages/` (la
convención "mágica" de Streamlit) — dejó de detectarse en Streamlit Cloud
(la página nueva no aparecía ni con reboot/rerun). Con `st.navigation` +
`st.Page` las páginas se declaran explícitas acá, sin depender de que
Streamlit escanee el árbol de archivos solo.

El estilo (tema + tarjetas, métricas, pills) es único para todas las páginas:
.streamlit/config.toml + dashboard/style.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import streamlit as st  # noqa: E402

from dashboard import style  # noqa: E402

style.inject()

pg = st.navigation([
    st.Page(DASHBOARD_DIR / "main_page.py", title="Scouting de ideas",
            icon=":material/search:", default=True),
    st.Page(DASHBOARD_DIR / "pages" / "1_Analisis_de_Mercado.py",
            title="Análisis de mercado", icon=":material/analytics:"),
    st.Page(DASHBOARD_DIR / "pages" / "2_Vault.py",
            title="Vault de ideas", icon=":material/inventory_2:"),
])
pg.run()
