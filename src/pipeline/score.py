from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic
from json_repair import repair_json

from .. import config
from ..models import Item, ScoredItem

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "score.md"

# Precios Haiku 4.5 (USD por millón de tokens). Actualizar si cambia el modelo.
PRICE_INPUT_PER_MTOK = 1.00
PRICE_OUTPUT_PER_MTOK = 5.00


def score(items: list[Item]) -> tuple[list[ScoredItem], float]:
    """Manda los candidatos a Claude en una sola llamada y parsea el resultado.

    Retorna (scored, costo_usd) — el costo se calcula de los tokens REALES
    consumidos, acumulando reintentos, para reportarlo en el email.

    Una llamada con todos los candidatos (en vez de una por item) abarata el
    costo y deja que el modelo compare entre sí. Si el JSON sale irreparable,
    reintenta UNA vez (solo paga el retry en semanas con falla).

    Nota: sin prompt caching a propósito — con 1 llamada por semana nunca hay
    cache hit y escribir al cache cuesta +25%.
    """
    if not items:
        return [], 0.0

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    candidates = _serialize(items)
    cost_usd = 0.0

    for attempt in (1, 2):
        # Streaming requerido por el SDK con max_tokens alto (>~10 min posibles).
        with client.messages.stream(
            model=config.MODEL,
            max_tokens=20000,
            system=system_prompt,
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

        cost_usd += (
            msg.usage.input_tokens * PRICE_INPUT_PER_MTOK
            + msg.usage.output_tokens * PRICE_OUTPUT_PER_MTOK
        ) / 1_000_000
        text = "".join(block.text for block in msg.content if block.type == "text")
        print(f"[score] intento {attempt}: stop_reason={msg.stop_reason} "
              f"input={msg.usage.input_tokens} output={msg.usage.output_tokens} "
              f"costo_acum=${cost_usd:.4f}")
        scored = _parse(text)
        if scored:
            return scored, cost_usd
        print(f"[score] intento {attempt} sin resultados válidos"
              + (", reintentando" if attempt == 1 else " — abortando"))
    return [], cost_usd


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
