from __future__ import annotations

from datetime import date

from jinja2 import Template

from ..models import ScoredItem

HTML_TEMPLATE = Template("""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f5f5; margin: 0; padding: 20px; color: #1a1a1a; }
  .container { max-width: 680px; margin: 0 auto; }
  .header { background: #1a1a1a; color: white; padding: 24px 28px;
            border-radius: 8px 8px 0 0; }
  .header h1 { margin: 0; font-size: 20px; font-weight: 600; }
  .header p  { margin: 6px 0 0; color: #aaa; font-size: 13px; }
  .meta { background: white; padding: 14px 28px; border-bottom: 1px solid #eee;
          font-size: 13px; color: #666; }
  .card { background: white; margin-top: 12px; border-radius: 8px;
          border: 1px solid #e8e8e8; overflow: hidden; }
  .card-header { padding: 18px 22px 12px; border-bottom: 1px solid #f0f0f0; }
  .rank { display: inline-block; background: #1a1a1a; color: white;
          font-size: 11px; font-weight: 700; padding: 2px 8px;
          border-radius: 3px; margin-bottom: 8px; }
  .card-header h2 { margin: 0 0 6px; font-size: 17px; line-height: 1.3; }
  .card-header h2 a { color: #1a1a1a; text-decoration: none; }
  .card-header h2 a:hover { text-decoration: underline; }
  .score-badge { display: inline-block; background: #f0fdf4; color: #166534;
                 border: 1px solid #bbf7d0; font-size: 13px; font-weight: 700;
                 padding: 3px 10px; border-radius: 4px; margin-right: 8px; }
  .pills { margin-top: 8px; }
  .pill { display: inline-block; background: #f3f4f6; color: #374151;
          font-size: 11px; padding: 2px 8px; border-radius: 3px;
          margin: 2px 4px 2px 0; }
  .pill.ia { background: #eff6ff; color: #1d4ed8; }
  .pill.funded { background: #fefce8; color: #854d0e; }
  .pill.stage { background: #fdf4ff; color: #7e22ce; }
  .card-body { padding: 14px 22px; }
  .resumen { font-size: 14px; line-height: 1.6; color: #374151; margin: 0 0 14px; }
  .signals { display: table; width: 100%; border-collapse: collapse;
             font-size: 13px; }
  .sig-row { display: table-row; }
  .sig-label { display: table-cell; width: 150px; font-weight: 600;
               color: #6b7280; padding: 4px 12px 4px 0; vertical-align: top; }
  .sig-val { display: table-cell; vertical-align: top; padding: 4px 0; }
  .alta  { color: #15803d; font-weight: 700; }
  .media { color: #b45309; font-weight: 700; }
  .baja  { color: #dc2626; font-weight: 700; }
  .card-footer { padding: 10px 22px 14px; background: #fafafa;
                 border-top: 1px solid #f0f0f0; font-size: 12px; color: #9ca3af; }
  .card-footer a { color: #6b7280; }
  .empty { background: white; border-radius: 8px; padding: 32px 28px;
           text-align: center; color: #6b7280; font-size: 14px; }
  .footer { margin-top: 20px; text-align: center; font-size: 11px; color: #9ca3af;
            padding-bottom: 20px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🔍 Scouting Semanal — Semana {{ week }}</h1>
    <p>{{ today }} · {{ ideas|length }} idea{{ 's' if ideas|length != 1 }} sobre el gate · {{ total_evaluados }} candidatos evaluados</p>
  </div>

  {% if not ideas %}
  <div class="empty">
    <p>No hubo ideas que superaran el gate esta semana.<br>
    Se evaluaron {{ total_evaluados }} candidatos.</p>
  </div>
  {% else %}
  {% for idea in ideas %}
  <div class="card">
    <div class="card-header">
      <div class="rank">#{{ loop.index }}</div>
      <h2>
        {% if idea.company_url %}
          <a href="{{ idea.company_url }}" target="_blank">{{ idea.title }}</a>
        {% else %}
          <a href="{{ idea.url }}" target="_blank">{{ idea.title }}</a>
        {% endif %}
      </h2>
      <span class="score-badge">{{ idea.objetivo_total }}/40</span>
      <span class="pill">{{ idea.b2b_o_b2c }}</span>
      {% if idea.componente_ia %}<span class="pill ia">IA</span>{% endif %}
      {% if idea.funding_raised and idea.funding_raised != 'desconocido' %}
        <span class="pill funded">{{ idea.funding_raised }}</span>
      {% endif %}
      {% if idea.stage and idea.stage != 'Desconocido' %}
        <span class="pill stage">{{ idea.stage }}</span>
      {% endif %}
      <div class="pills">
        <span class="pill">{{ idea.mercado_actual }}</span>
      </div>
    </div>
    <div class="card-body">
      <p class="resumen">{{ idea.resumen }}</p>
      <div class="signals">
        <div class="sig-row">
          <div class="sig-label">Replicabilidad</div>
          <div class="sig-val">
            <span class="{{ idea.replicabilidad.nivel.lower() }}">{{ idea.replicabilidad.nivel }}</span>
            — {{ idea.replicabilidad.evidencia }}
          </div>
        </div>
        <div class="sig-row">
          <div class="sig-label">Ventana de tiempo</div>
          <div class="sig-val">
            <span class="{{ idea.ventana.nivel.lower() }}">{{ idea.ventana.nivel }}</span>
            — {{ idea.ventana.evidencia }}
          </div>
        </div>
        <div class="sig-row">
          <div class="sig-label">Tamaño mercado</div>
          <div class="sig-val">
            <span class="{{ idea.tamano_mercado.nivel.lower() }}">{{ idea.tamano_mercado.nivel }}</span>
            — {{ idea.tamano_mercado.evidencia }}
          </div>
        </div>
      </div>
    </div>
    <div class="card-footer">
      Fundador ideal: {{ idea.tipo_fundador }} ·
      <a href="{{ idea.url }}" target="_blank">Ver fuente ({{ idea.source }})</a>
      {% if idea.company_url %} ·
        <a href="{{ idea.company_url }}" target="_blank">Web de la empresa</a>
      {% endif %}
    </div>
  </div>
  {% endfor %}
  {% endif %}

  <div class="footer">
    Generado automáticamente con Claude Haiku · Las señales cualitativas son juicio del modelo, no métricas verificadas.
  </div>
</div>
</body>
</html>
""")


def render_html(ideas: list[ScoredItem], total_evaluados: int, min_objetivo: int) -> str:
    today = date.today()
    return HTML_TEMPLATE.render(
        ideas=ideas,
        total_evaluados=total_evaluados,
        min_objetivo=min_objetivo,
        week=today.isocalendar().week,
        today=today.strftime("%d %b %Y"),
    )
