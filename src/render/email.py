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
  .card { background: white; margin-top: 12px; border-radius: 8px;
          border: 1px solid #e8e8e8; overflow: hidden; }
  .card.passed { border-left: 4px solid #16a34a; }
  .card.not-passed { border-left: 4px solid #d1d5db; opacity: 0.85; }
  .card-header { padding: 18px 22px 12px; border-bottom: 1px solid #f0f0f0; }
  .rank { display: inline-block; background: #1a1a1a; color: white;
          font-size: 11px; font-weight: 700; padding: 2px 8px;
          border-radius: 3px; margin-bottom: 8px; margin-right: 6px; }
  .gate-badge { display: inline-block; font-size: 10px; font-weight: 700;
                padding: 2px 7px; border-radius: 3px; margin-bottom: 8px;
                vertical-align: middle; }
  .gate-badge.passed { background: #dcfce7; color: #15803d; }
  .gate-badge.not-passed { background: #f3f4f6; color: #6b7280; }
  .card-header h2 { margin: 0 0 6px; font-size: 17px; line-height: 1.3; }
  .card-header h2 a { color: #1a1a1a; text-decoration: none; }
  .card-header h2 a:hover { text-decoration: underline; }
  .score-badge { display: inline-block; background: #f0fdf4; color: #166534;
                 border: 1px solid #bbf7d0; font-size: 13px; font-weight: 700;
                 padding: 3px 10px; border-radius: 4px; margin-right: 8px; }
  .score-badge.low { background: #f9fafb; color: #6b7280; border-color: #e5e7eb; }
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
  .footer { margin-top: 20px; text-align: center; font-size: 11px; color: #9ca3af;
            padding-bottom: 20px; }
  .legend { background: white; border-radius: 8px; margin-top: 12px;
            padding: 10px 18px; font-size: 12px; color: #6b7280; }
  .error-banner { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b;
                  border-radius: 8px; margin-top: 12px; padding: 14px 18px;
                  font-size: 13px; font-weight: 600; }
  .next-step { background: #fffbeb; border-left: 3px solid #f59e0b;
               padding: 8px 12px; margin-top: 12px; font-size: 13px;
               color: #78350f; border-radius: 0 4px 4px 0; }
  .pill.tesis { background: #ecfdf5; color: #047857; font-weight: 600; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🔍 Scouting Semanal — Semana {{ week }}</h1>
    <p>{{ today }} · {{ n_passed }} sobre el gate · {{ total_evaluados }} candidatos evaluados · top {{ ideas|length }} mostradas</p>
  </div>

  {% if error %}
  <div class="error-banner">
    ⚠️ El scoring falló esta semana (JSON inválido tras 2 intentos). Esto NO significa
    que no hubo ideas — revisá los logs del workflow en GitHub Actions.
  </div>
  {% endif %}

  {% for idea in ideas %}
  {% set passed = idea.url in passing_ids %}
  <div class="card {{ 'passed' if passed else 'not-passed' }}">
    <div class="card-header">
      <div class="rank">#{{ loop.index }}</div>
      <span class="gate-badge {{ 'passed' if passed else 'not-passed' }}">
        {{ '✓ Gate' if passed else 'Bajo gate' }}
      </span>
      <h2>
        {% if idea.company_url %}
          <a href="{{ idea.company_url }}" target="_blank">{{ idea.title }}</a>
        {% else %}
          <a href="{{ idea.url }}" target="_blank">{{ idea.title }}</a>
        {% endif %}
      </h2>
      <span class="score-badge {{ '' if passed else 'low' }}">{{ idea.objetivo_total }}/40</span>
      {% if idea.fit_tesis and idea.fit_tesis != 'Otro' %}
        <span class="pill tesis">{{ idea.fit_tesis }}</span>
      {% endif %}
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
        {% if idea.por_que_ahora %}
        <div class="sig-row">
          <div class="sig-label">¿Por qué ahora?</div>
          <div class="sig-val">{{ idea.por_que_ahora }}</div>
        </div>
        {% endif %}
        {% if idea.modelo_negocio %}
        <div class="sig-row">
          <div class="sig-label">Modelo de negocio</div>
          <div class="sig-val">{{ idea.modelo_negocio }}</div>
        </div>
        {% endif %}
        {% if idea.competencia_local %}
        <div class="sig-row">
          <div class="sig-label">Competencia local</div>
          <div class="sig-val">{{ idea.competencia_local }}</div>
        </div>
        {% endif %}
      </div>
      {% if idea.next_step %}
      <div class="next-step">👉 <strong>Próximo paso:</strong> {{ idea.next_step }}</div>
      {% endif %}
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

  <div class="legend">
    <strong>✓ Gate</strong> = score ≥ 24/40 + replicabilidad ≠ Baja + al menos una señal Alta.
    Las ideas "Bajo gate" se muestran igual para que puedas juzgar si el criterio es correcto.
    {% if warnings %}
    <br>⚠️ <strong>Salud de fuentes:</strong>
    {% for w in warnings %}{{ w }}{{ ' · ' if not loop.last }}{% endfor %}
    — si se repite 2+ semanas, revisar/reemplazar.
    {% endif %}
  </div>

  <div class="footer">
    Generado automáticamente con Claude Haiku · Las señales cualitativas son juicio del modelo, no métricas verificadas.
    {% if cost_usd %}<br>💰 Costo real de este reporte: <strong>${{ "%.3f"|format(cost_usd) }} USD</strong> (tokens medidos, no proyección) · anualizado ×52: ${{ "%.2f"|format(cost_usd * 52) }}{% endif %}
  </div>
</div>
</body>
</html>
""")


def render_html(ideas: list[ScoredItem], passing_ids: set[str],
                total_evaluados: int, min_objetivo: int,
                error: bool = False, cost_usd: float = 0.0,
                warnings: list[str] | None = None) -> str:
    today = date.today()
    return HTML_TEMPLATE.render(
        ideas=ideas,
        passing_ids=passing_ids,
        n_passed=sum(1 for i in ideas if i.url in passing_ids),
        total_evaluados=total_evaluados,
        min_objetivo=min_objetivo,
        error=error,
        cost_usd=cost_usd,
        warnings=warnings or [],
        week=today.isocalendar().week,
        today=today.strftime("%d %b %Y"),
    )
