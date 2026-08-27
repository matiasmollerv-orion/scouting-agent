"""Análisis profundo on-demand de UNA idea.

Llamada directa (no Batch API): el usuario está esperando en el dashboard,
no puede esperar los ~20-40 min que tarda un batch. Reusa el mismo prompt,
precios y parsing que el pipeline semanal (src/pipeline/score.py) para no
duplicar lógica ni criterio de evaluación.

2026-08: system prompt con cache_control. A diferencia del pipeline semanal
(1 llamada por prompt, sin repetición — cachear ahí solo pagaría el premium
de escritura sin nunca leer), acá SÍ hay repetición real: cada click en el
dashboard manda el MISMO system (score.md + ideas_propias.md, ~2-3k tokens)
de nuevo. Si Matías analiza varias ideas en una sesión (caso real: pasó en
esta misma conversación), las llamadas 2+ leen del caché a ~10% del costo
de esa porción en vez de pagarla entera cada vez.
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
    # Bloque con cache_control: mismo texto siempre (sin fecha/UUID inyectado
    # — precondición para que el prefix-match del caché funcione, ver
    # shared/prompt-caching.md "silent invalidators"). TTL default 5 min:
    # cubre el caso real de "reviso varias ideas seguidas" sin pagar el
    # premium de 1h TTL si termina siendo 1 sola idea por sesión.
    system = [{
        "type": "text",
        "text": (PROMPTS_DIR / "score.md").read_text(encoding="utf-8") + "\n\n" + ideas_propias,
        "cache_control": {"type": "ephemeral"},
    }]
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
    cache_write = getattr(msg.usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(msg.usage, "cache_read_input_tokens", 0) or 0
    cost = (_cost(config.MODEL_DEEP, msg.usage.input_tokens, msg.usage.output_tokens,
                  cache_write_tokens=cache_write, cache_read_tokens=cache_read)
            + searches * PRICE_WEB_SEARCH)
    print(f"[dashboard] directo {config.MODEL_DEEP}: in={msg.usage.input_tokens} "
          f"out={msg.usage.output_tokens} cache_write={cache_write} "
          f"cache_read={cache_read} búsquedas={searches} costo=${cost:.4f}")
    text = "".join(bl.text for bl in msg.content if bl.type == "text")
    scored = _parse(text)
    return (scored[0] if scored else None), cost
