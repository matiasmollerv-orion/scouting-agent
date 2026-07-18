from __future__ import annotations

from datetime import date

from jinja2 import Template

from ..models import ScoredItem

TEMPLATE = Template(
    """# Reporte de Scouting — Semana {{ week }} ({{ today }})

{% if not ideas %}
No hubo candidatos con análisis profundo esta semana ({{ total_evaluados }} evaluados en triage).
{% else %}
**{{ ideas|length }} candidato(s) analizados en profundidad** de {{ total_evaluados }} evaluados en triage esta semana. **{{ gate_count }}** superaron el gate (score objetivo ≥ {{ min_objetivo }}/40) — se listan TODOS los analizados en profundidad, no solo los que pasan gate: son inteligencia de mercado igual.

{% for idea in ideas %}
## {{ loop.index }}. {{ "✅ " if idea.passes_gate(min_objetivo) else "" }}{{ idea.title }} — {{ idea.objetivo_total }}/40
{% if idea.tipo_candidato %}*[{{ idea.tipo_candidato }}]*
{% endif %}
{{ idea.resumen }}

**Fuente:** [{{ idea.source }}]({{ idea.url }})
{% if idea.valida_idea_propia %}**🎯 Valida idea propia:** {{ idea.valida_idea_propia }}
{% endif %}
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
**Ficha:** {{ idea.b2b_o_b2c }} · IA: {{ "Sí" if idea.componente_ia else "No" }} · Mercado actual: {{ idea.mercado_actual }}{% if idea.fit_tesis %} · Tesis: {{ idea.fit_tesis }}{% endif %}{% if idea.fit_yc %} · Fit YC: {{ idea.fit_yc }}{% endif %}
**Fundador ideal:** {{ idea.tipo_fundador }}{% if idea.fundadores and idea.fundadores != 'no identificados' %} · **Fundadores:** {{ idea.fundadores }}{% endif %}{% if idea.redes_sociales %} · **Redes:** {{ idea.redes_sociales }}{% endif %}
{% if idea.next_step %}**👉 Próximo paso:** {{ idea.next_step }}{% endif %}

---
{% endfor %}
{% endif %}
{% if panorama %}
## Panorama completo de la semana (triage)

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
    panorama: list[dict] | None = None, gate_count: int = 0,
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
        gate_count=gate_count,
        week=today.isocalendar().week,
        today=today.isoformat(),
    )
