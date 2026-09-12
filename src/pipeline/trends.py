"""Tendencias sintetizadas desde el pool crudo — 2026-09.

Antes, "temas en aceleración" solo contaba menciones de keyword sobre TODO
el pool crudo, sin distinguir señal real (varios medios reporteando lo
mismo) de ruido (un solo medio con formato de columna publicando varias
piezas sobre lo mismo). Matías lo detectó con un caso real: "Fintech/Clase
media" marcó 101 menciones una semana, pero gran parte venía de una sola
fuente (fintechtimes, contribuyentes externos rotativos, no redacción
propia) — el conteo crudo no distinguía eso de 101 medios distintos
reportando la misma historia.

Fix acordado con Matías: peso por fuente (config.SOURCE_WEIGHT) + mínimo
de fuentes distintas (config.TREND_MIN_SOURCES) antes de sintetizar un
sub-tema como "tendencia real". Una sola llamada barata a Haiku agrupa
los items crudos que ya pasaron el umbral en sub-temas concretos, citando
SOLO sub-temas con evidencia de 2+ fuentes — no inventa, no hace lo mismo
para un tema con una sola fuente detrás aunque tenga mucho volumen.
"""
from __future__ import annotations

import json

from .. import config
from . import score
from .score import _call, _loads_forgiving

MAX_ITEMS_PER_THEME = 15  # cap de items mandados por tema — costo bajo control

SYSTEM = """Sos un analista de tendencias de mercado. Te doy, por tema, una
lista de titulares de prensa con su fuente. Tu trabajo: agrupar esos
titulares en SUB-TEMAS concretos y accionables (más específico que el
tema general — no "Fintech", sino algo como "bancos automatizan disputas
de fraude con agentes de IA").

Regla dura: un sub-tema SOLO cuenta si tiene evidencia de AL MENOS 2
FUENTES DISTINTAS entre los titulares que te doy (ya vienen filtrados por
peso editorial — no vuelvas a filtrar por credibilidad, ya está hecho).
Si dentro de un tema no hay ningún grupo de titulares de 2+ fuentes
distintas sobre el mismo sub-tema concreto, ESE TEMA NO VA en la salida —
no fuerces un sub-tema con 1 sola fuente por más volumen que tenga.

No inventes datos que no estén en los titulares. El resumen debe basarse
solo en lo que ves, con evidencia concreta (qué fuentes, qué dice cada
una), no especulación genérica sobre la industria.

# Salida

EXCLUSIVAMENTE un array JSON, sin texto extra:
[{"tema": "<tema general tal como te lo pasé>",
  "subtema": "<sub-tema específico y accionable>",
  "fuentes": ["fuente1", "fuente2"],
  "resumen": "1-2 frases con evidencia concreta de los titulares"}]

Array vacío [] si ningún tema tiene un sub-tema con 2+ fuentes reales.
"""


def synthesize_trends(theme_items: dict[str, list]) -> tuple[list[dict], float]:
    """Filtra por peso+fuentes mínimas, y sintetiza con UNA llamada barata a
    Haiku. Retorna (tendencias, costo_usd) — ([], 0.0) si nada pasa el
    umbral (no gasta nada en ese caso, ni siquiera llama al modelo)."""
    qualifying: dict[str, list] = {}
    for tema, items in theme_items.items():
        by_source: dict[str, list] = {}
        for it in items:
            by_source.setdefault(it.source, []).append(it)
        distinct_sources = len(by_source)
        weight = sum(
            config.SOURCE_WEIGHT.get(src, config.SOURCE_WEIGHT_DEFAULT)
            for src in by_source
        )
        if distinct_sources >= config.TREND_MIN_SOURCES and weight >= config.TREND_MIN_WEIGHT:
            # Top items por peso de fuente, tope MAX_ITEMS_PER_THEME.
            ranked = sorted(
                items,
                key=lambda it: -config.SOURCE_WEIGHT.get(it.source, config.SOURCE_WEIGHT_DEFAULT),
            )
            qualifying[tema] = ranked[:MAX_ITEMS_PER_THEME]

    if not qualifying:
        return [], 0.0

    payload = {
        tema: [{"fuente": it.source, "titulo": it.title} for it in items]
        for tema, items in qualifying.items()
    }
    user = (
        f"Temas que pasaron el umbral de fuentes/peso ({len(qualifying)}):\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=1)}"
    )

    # score.Anthropic (no una importación propia) — así el monkeypatch de
    # tests/dry_run.py (S.Anthropic = FakeAnthropic) también cubre esto.
    client = score.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    text, cost, _truncated = _call(
        client, config.MODEL_TRIAGE, SYSTEM, user, max_tokens=3000, log_prefix="[trends]",
    )
    data = _loads_forgiving(text)
    trends = [d for d in data if isinstance(d, dict) and d.get("subtema") and d.get("fuentes")]
    print(f"[trends] {len(qualifying)} temas sobre umbral -> {len(trends)} tendencias sintetizadas, costo=${cost:.4f}")
    return trends, cost
