from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

from .. import config
from ..models import Item, ScoredItem

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "score.md"


def score(items: list[Item]) -> list[ScoredItem]:
    """Manda los candidatos a Claude en una sola llamada y parsea el resultado.

    Una llamada con todos los candidatos (en vez de una por item) abarata el
    costo y deja que el modelo compare entre sí. El system prompt se cachea.
    """
    if not items:
        return []

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    candidates = _serialize(items)

    resp = client.messages.create(
        model=config.MODEL,
        max_tokens=8000,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Candidatos de esta semana:\n\n{candidates}",
            }
        ],
    )

    text = "".join(block.text for block in resp.content if block.type == "text")
    return _parse(text)


def _serialize(items: list[Item]) -> str:
    payload = [
        {
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "engagement": it.engagement,
            "text": it.text[:600],
        }
        for it in items
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse(text: str) -> list[ScoredItem]:
    raw = _extract_json_array(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[score] JSON inválido del modelo: {e}")
        return []

    scored: list[ScoredItem] = []
    for obj in data:
        try:
            scored.append(ScoredItem.model_validate(obj))
        except Exception as e:  # noqa: BLE001 — un item malo no tumba el resto
            print(f"[score] item descartado por validación: {e}")
    return scored


def _extract_json_array(text: str) -> str:
    """Recorta al primer '[' y último ']' por si el modelo agrega ruido."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return "[]"
    return text[start : end + 1]
