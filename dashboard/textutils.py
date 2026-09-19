"""Limpieza de texto generado por modelos antes de mostrarlo en Streamlit.

Dos bugs reales encontrados con datos pagados (2026-09-16): st.markdown lee
"$...$" como fórmula LaTeX (cualquier monto en dólares rompe el render) y las
citas de búsqueda web llegan como tags crudos <cite index="...">. Ver la misma
lógica en pages/1_Analisis_de_Mercado.py (_clean) — esta es la versión
compartida para las páginas nuevas.
"""
from __future__ import annotations

import re

_CITE_RE = re.compile(r"</?cite[^>]*>", re.IGNORECASE)


def clean(text) -> str:
    """Texto listo para st.markdown/st.caption: sin tags de cita y con "$" escapado."""
    if not text:
        return ""
    return _CITE_RE.sub("", str(text)).replace("$", "\\$")
