from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic
from json_repair import repair_json

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

    # Streaming requerido por el SDK cuando max_tokens puede superar ~10 min de generación.
    with client.messages.stream(
        model=config.MODEL,
        max_tokens=20000,  # 30 items × ~400 tokens + margen amplio
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
                "content": (
                    f"Candidatos de esta semana ({len(items)} en total):\n\n{candidates}\n\n"
                    f"IMPORTANTE: evaluá los {len(items)} candidatos sin excepción. "
                    "Los irrelevantes reciben scores bajos pero deben aparecer en el JSON."
                ),
            }
        ],
    ) as stream:
        msg = stream.get_final_message()

    text = "".join(block.text for block in msg.content if block.type == "text")
    print(f"[score] stop_reason={msg.stop_reason} output_tokens={msg.usage.output_tokens}")
    return _parse(text)


def _serialize(items: list[Item]) -> str:
    payload = [
        {
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "engagement": it.engagement,
            "text": it.text[:800],
        }
        for it in items
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse(text: str) -> list[ScoredItem]:
    raw = _extract_json_array(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[score] JSON con errores, intentando reparar: {e}")
        try:
            data = json.loads(repair_json(raw))
            print("[score] JSON reparado exitosamente")
        except Exception as e2:
            print(f"[score] JSON irreparable: {e2}")
            return []

    scored: list[ScoredItem] = []
    for obj in data:
        try:
            scored.append(ScoredItem.model_validate(obj))
        except Exception as e:  # noqa: BLE001 — un item malo no tumba el resto
            print(f"[score] item descartado por validación: {e}")
    print(f"[score] {len(data)} recibidos del modelo, {len(scored)} válidos")
    return scored


def _extract_json_array(text: str) -> str:
    """Recorta al primer '[' y último ']' por si el modelo agrega ruido."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return "[]"
    return text[start : end + 1]
