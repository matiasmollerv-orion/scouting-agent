from __future__ import annotations

from datetime import date

from jinja2 import Template

from ..models import ScoredItem

TEMPLATE = Template(
    """# Reporte de Scouting — Semana {{ week }} ({{ today }})

{% if not ideas %}
No hubo ideas que superaran el gate esta semana ({{ total_evaluados }} candidatos evaluados).
{% else %}
**{{ ideas|length }} idea(s)** superaron el gate (score objetivo ≥ {{ min_objetivo }}/40), de {{ total_evaluados }} candidatos evaluados.

{% for idea in ideas %}
## {{ loop.index }}. {{ idea.title }} — {{ idea.objetivo_total }}/40

{{ idea.resumen }}

**Fuente:** [{{ idea.source }}]({{ idea.url }})

| Criterio | Resultado |
|---|---|
| Señal de problema real | {{ idea.problema_score }}/25 |
| Barrera de entrada razonable | {{ idea.barrera_score }}/15 |
| **Score objetivo** | **{{ idea.objetivo_total }}/40** |
| Replicabilidad en Chile | {{ idea.replicabilidad.nivel }} — {{ idea.replicabilidad.evidencia }} |
| Ventana de tiempo | {{ idea.ventana.nivel }} — {{ idea.ventana.evidencia }} |
| Tamaño de mercado | {{ idea.tamano_mercado.nivel }} — {{ idea.tamano_mercado.evidencia }} |
{% if idea.por_que_ahora %}| ¿Por qué ahora? | {{ idea.por_que_ahora }} |
{% endif %}{% if idea.modelo_negocio %}| Modelo de negocio | {{ idea.modelo_negocio }} |
{% endif %}{% if idea.competencia_local %}| Competencia local | {{ idea.competencia_local }} |
{% endif %}
**Ficha:** {{ idea.b2b_o_b2c }} · IA: {{ "Sí" if idea.componente_ia else "No" }} · Mercado actual: {{ idea.mercado_actual }}{% if idea.fit_tesis %} · Tesis: {{ idea.fit_tesis }}{% endif %}
**Fundador ideal:** {{ idea.tipo_fundador }}
{% if idea.next_step %}**👉 Próximo paso:** {{ idea.next_step }}{% endif %}

---
{% endfor %}
{% endif %}
{% if panorama %}
## Panorama completo de la semana

Todas las evaluaciones del triage, incluidas las descartadas — inteligencia de
mercado para análisis posteriores (patrones por industria, ideas combinables).

| Triage | Título | Fuente |
|---|---|---|
{% for p in panorama -%}
| {{ p.total if p.total is not none else '—' }}/40 | [{{ p.title }}]({{ p.url }}) | {{ p.source }} |
{% endfor %}
{% endif %}

*Generado automáticamente. Las señales cualitativas son juicio del modelo, no métricas verificadas.*
"""
)


def render(
    ideas: list[ScoredItem], total_evaluados: int, min_objetivo: int,
    panorama: list[dict] | None = None,
) -> str:
    today = date.today()
    # Orden en Python (Jinja sort no maneja None): sin score al final.
    panorama = sorted(
        panorama or [],
        key=lambda p: p.get("total") if p.get("total") is not None else -1,
        reverse=True,
    )
    return TEMPLATE.render(
        ideas=ideas,
        total_evaluados=total_evaluados,
        min_objetivo=min_objetivo,
        panorama=panorama,
        week=today.isocalendar().week,
        today=today.isoformat(),
    )
