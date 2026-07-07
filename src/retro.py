"""Retro trimestral: ¿qué pasó con las ideas que destacamos?

Junta las mejores ideas del trimestre desde reports/*-full.json y usa Sonnet
con web search para verificar su estado actual (¿levantaron? ¿crecieron?
¿murieron?). El objetivo es calibrar el gate: si las ideas que destacamos
sistemáticamente mueren, el criterio está malo y hay que ajustarlo.

Corre el día 1 de enero/abril/julio/octubre (quarterly.yml) o a mano.
Costo: ~$0.35-0.50 por trimestre (tope de 20 búsquedas web por diseño).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from anthropic import Anthropic

from . import config
from .pipeline.score import PRICES, _loads_forgiving
from .render.mailer import send_html

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
MAX_IDEAS = 12
MAX_SEARCHES = 20
PRICE_WEB_SEARCH = 0.01  # USD por búsqueda ($10 / 1000)
LOOKBACK_DAYS = 92

SYSTEM = """Sos un analista de venture capital haciendo la retrospectiva trimestral
de un sistema de scouting de ideas de negocio para un fundador chileno.

Recibís las ideas destacadas del trimestre con su score original. Tu trabajo:
1. Para CADA idea, buscá en la web su estado ACTUAL: ¿levantó capital nuevo?
   ¿creció (usuarios, contrataciones, expansión)? ¿está estancada? ¿murió/pivoteó?
   Usá 1-2 búsquedas por idea, priorizando las de mayor score. Si no encontrás
   nada, decilo: "sin novedades encontradas".
2. Después hacé la meta-síntesis:
   - temas_ganadores: qué categorías de la tesis produjeron las ideas que mejor
     evolucionaron
   - calibracion: ¿las ideas que pasaron el gate (marcadas) evolucionaron mejor
     que las que no? Sé honesto — si el gate no discrimina, decilo.
   - ajustes_tesis: máximo 3 ajustes concretos al criterio de scoring, basados
     en la evidencia.

Salida: EXCLUSIVAMENTE un objeto JSON (sin texto extra):
{
  "ideas": [{"title": "...", "url": "...", "estado": "levantó|creciendo|estancada|muerta|desconocido",
             "detalle": "1-2 frases con lo que encontraste", "gate": true}],
  "temas_ganadores": "...",
  "calibracion": "...",
  "ajustes_tesis": ["...", "..."]
}
"""


def gather_quarter_ideas() -> list[dict]:
    """Ideas deep del trimestre, dedup por URL, ordenadas por score."""
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    best: dict[str, dict] = {}
    for f in sorted(REPORTS_DIR.glob("*-full.json")):
        try:
            year, week = f.name.split("-full")[0].split("-W")
            file_date = date.fromisocalendar(int(year), int(week), 6)
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        gate_urls = set(data.get("gate_urls", []))
        for idea in data.get("deep", []):
            total = idea.get("problema_score", 0) + idea.get("barrera_score", 0)
            entry = {
                "title": idea.get("title", ""),
                "url": idea.get("url", ""),
                "company_url": idea.get("company_url", ""),
                "resumen": idea.get("resumen", "")[:300],
                "fit_tesis": idea.get("fit_tesis", ""),
                "score": total,
                "gate": idea.get("url") in gate_urls,
                "semana": data.get("week", ""),
            }
            key = entry["url"]
            if key and (key not in best or total > best[key]["score"]):
                best[key] = entry
    ideas = sorted(best.values(), key=lambda x: (x["gate"], x["score"]), reverse=True)
    return ideas[:MAX_IDEAS]


def run() -> None:
    ideas = gather_quarter_ideas()
    today = date.today()
    q = (today.month - 2) // 3 + 1  # trimestre ANTERIOR al mes actual
    quarter = f"{today.year - 1}-Q4" if q <= 0 else f"{today.year}-Q{q}"
    if not ideas:
        print("[retro] sin ideas acumuladas en el trimestre — nada que revisar")
        return
    print(f"[retro] {quarter}: revisando {len(ideas)} ideas "
          f"({sum(1 for i in ideas if i['gate'])} pasaron el gate)")

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    with client.messages.stream(
        model=config.MODEL_DEEP,
        max_tokens=6000,
        system=SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search",
                "max_uses": MAX_SEARCHES}],
        messages=[{
            "role": "user",
            "content": f"Ideas destacadas del trimestre {quarter}:\n\n"
                       + json.dumps(ideas, ensure_ascii=False, indent=1),
        }],
    ) as stream:
        msg = stream.get_final_message()

    searches = getattr(getattr(msg.usage, "server_tool_use", None),
                       "web_search_requests", 0) or 0
    p_in, p_out = PRICES.get(config.MODEL_DEEP, (3.0, 15.0))
    cost = ((msg.usage.input_tokens * p_in + msg.usage.output_tokens * p_out)
            / 1_000_000 + searches * PRICE_WEB_SEARCH)
    print(f"[retro] in={msg.usage.input_tokens} out={msg.usage.output_tokens} "
          f"búsquedas={searches} costo=${cost:.3f}")

    text = "".join(b.text for b in msg.content if b.type == "text")
    result = _parse_object(text)
    if not result:
        print("[retro] respuesta no parseable — se guarda cruda")
        result = {"ideas": [], "temas_ganadores": "", "calibracion": text[:2000],
                  "ajustes_tesis": []}

    md = _render_md(quarter, ideas, result, cost)
    out = REPORTS_DIR / f"{quarter}-retro.md"
    out.write_text(md, encoding="utf-8")
    print(f"[retro] reporte -> {out}")

    send_html(f"🔄 Retro Trimestral {quarter} — ¿qué pasó con las ideas?",
              _render_html(quarter, result, len(ideas), cost),
              sender_name="Scouting Retro")


def _parse_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    data = _loads_forgiving(f"[{text[start:end + 1]}]")
    return data[0] if data and isinstance(data[0], dict) else {}


ESTADO_EMOJI = {"levantó": "🚀", "creciendo": "📈", "estancada": "😐",
                "muerta": "💀", "desconocido": "❓"}


def _render_md(quarter: str, ideas: list[dict], r: dict, cost: float) -> str:
    lines = [f"# Retro Trimestral {quarter}", "",
             f"{len(ideas)} ideas revisadas con búsqueda web.", "", "## Estado de las ideas", ""]
    for i in r.get("ideas", []):
        e = ESTADO_EMOJI.get(i.get("estado", "desconocido"), "❓")
        gate = " ✓gate" if i.get("gate") else ""
        lines.append(f"- {e} **{i.get('title', '?')}**{gate} — {i.get('estado')}: {i.get('detalle', '')}")
    lines += ["", "## Temas ganadores", "", r.get("temas_ganadores", "—"),
              "", "## Calibración del gate", "", r.get("calibracion", "—"),
              "", "## Ajustes sugeridos a la tesis", ""]
    lines += [f"1. {a}" for a in r.get("ajustes_tesis", [])] or ["—"]
    lines += ["", f"*Costo real: ${cost:.3f} USD (tokens + búsquedas medidas).*"]
    return "\n".join(lines)


def _render_html(quarter: str, r: dict, n: int, cost: float) -> str:
    rows = ""
    for i in r.get("ideas", []):
        e = ESTADO_EMOJI.get(i.get("estado", "desconocido"), "❓")
        gate = " <span style='color:#15803d;font-size:11px'>✓ gate</span>" if i.get("gate") else ""
        rows += (f"<tr><td style='padding:6px 10px'>{e}</td>"
                 f"<td style='padding:6px 10px'><strong>{i.get('title', '?')}</strong>{gate}<br>"
                 f"<span style='color:#6b7280;font-size:13px'>{i.get('detalle', '')}</span></td></tr>")
    ajustes = "".join(f"<li>{a}</li>" for a in r.get("ajustes_tesis", []))
    return f"""
<div style="font-family:-apple-system,sans-serif;max-width:680px;margin:0 auto;color:#1a1a1a">
  <div style="background:#1a1a1a;color:#fff;padding:20px 24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:19px">🔄 Retro Trimestral {quarter}</h1>
    <p style="margin:6px 0 0;color:#aaa;font-size:13px">{n} ideas revisadas con búsqueda web</p>
  </div>
  <div style="background:#fff;padding:16px 24px;border:1px solid #e8e8e8">
    <table style="border-collapse:collapse;font-size:14px">{rows}</table>
    <h3 style="margin:18px 0 6px">Temas ganadores</h3>
    <p style="font-size:14px;color:#374151">{r.get('temas_ganadores', '—')}</p>
    <h3 style="margin:18px 0 6px">Calibración del gate</h3>
    <p style="font-size:14px;color:#374151">{r.get('calibracion', '—')}</p>
    <h3 style="margin:18px 0 6px">Ajustes sugeridos a la tesis</h3>
    <ol style="font-size:14px;color:#374151">{ajustes or '<li>—</li>'}</ol>
  </div>
  <p style="text-align:center;font-size:11px;color:#9ca3af;margin-top:14px">
    💰 Costo real: ${cost:.3f} USD (tokens + búsquedas medidas, no proyección)
  </p>
</div>"""


if __name__ == "__main__":
    run()
