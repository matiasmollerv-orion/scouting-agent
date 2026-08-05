"""Análisis profundo on-demand de UNA idea.

Llamada directa (no Batch API): el usuario está esperando en el dashboard,
no puede esperar los ~20-40 min que tarda un batch. Reusa el mismo prompt,
precios y parsing que el pipeline semanal (src/pipeline/score.py) para no
duplicar lógica ni criterio de evaluación.
"""
from __future__ import annotations

from anthropic import Anthropic

from src import config
from src.models import Item, ScoredItem
from src.pipeline.score import (
    PRICE_WEB_SEARCH, PROMPTS_DIR, _cost, _parse, _search_count, _serialize,
    web_search_tool,
)

MAX_SEARCHES_ONDEMAND = 3  # 1 sola idea, no 8 — tope más chico que el deep semanal


def analyze_one(item: Item) -> tuple[ScoredItem | None, float]:
    """Analiza un solo candidato en profundidad. Retorna (resultado, costo_usd)."""
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    ideas_propias = (PROMPTS_DIR / "ideas_propias.md").read_text(encoding="utf-8")
    system = (PROMPTS_DIR / "score.md").read_text(encoding="utf-8") + "\n\n" + ideas_propias
    user = (
        f"Candidato a analizar (1 en total):\n\n{_serialize([item], text_chars=1200)}\n\n"
        "Sé conciso: máximo ~120 palabras por objeto JSON."
    )
    with client.messages.stream(
        model=config.MODEL_DEEP,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=web_search_tool(MAX_SEARCHES_ONDEMAND),
    ) as stream:
        msg = stream.get_final_message()
    searches = _search_count(msg)
    cost = _cost(config.MODEL_DEEP, msg.usage.input_tokens, msg.usage.output_tokens) + searches * PRICE_WEB_SEARCH
    text = "".join(bl.text for bl in msg.content if bl.type == "text")
    scored = _parse(text)
    return (scored[0] if scored else None), cost
