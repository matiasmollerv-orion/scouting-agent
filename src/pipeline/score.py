from __future__ import annotations

import json
import time
from pathlib import Path

from anthropic import Anthropic
from json_repair import repair_json

from .. import config
from ..models import Item, ScoredItem

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# USD por millón de tokens (input, output). Actualizar si cambian los modelos.
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
}
BATCH_DISCOUNT = 0.5  # Batch API: 50% off input y output


def score(items: list[Item]) -> tuple[list[ScoredItem], float]:
    """Scoring en dos etapas. Retorna (scored, costo_usd_real).

    Etapa 1 (triage, Haiku): puntúa TODOS los candidatos con output mínimo
    (~30 tokens/item). Etapa 2 (deep, Sonnet): análisis completo solo de los
    TOP_DEEP mejores. Ambas intentan Batch API (50% off) con fallback a
    llamada directa. Guardrail: si el costo acumulado supera COST_LIMIT_USD,
    se aborta lo que falte.
    """
    if not items:
        return [], 0.0

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    cost = 0.0

    # --- Etapa 1: triage ---
    triage_system = (PROMPTS_DIR / "triage.md").read_text(encoding="utf-8")
    triage_user = (
        f"Candidatos ({len(items)}):\n\n{_serialize(items, text_chars=400)}\n\n"
        f"Puntuá los {len(items)} sin excepción."
    )
    text, c = _call(client, config.MODEL_TRIAGE, triage_system, triage_user, max_tokens=4000)
    cost += c
    ranked = _rank_from_triage(text, items)
    if not ranked:
        print("[score] triage sin resultados — fallback: top por orden de prefilter")
        ranked = items[: config.TOP_DEEP]
    top = ranked[: config.TOP_DEEP]
    print(f"[score] triage: {len(items)} candidatos -> top {len(top)} a análisis profundo")

    if cost >= config.COST_LIMIT_USD:
        print(f"[score] GUARDRAIL: ${cost:.3f} ≥ ${config.COST_LIMIT_USD} — se aborta etapa deep")
        return [], cost

    # --- Etapa 2: análisis profundo ---
    deep_system = (PROMPTS_DIR / "score.md").read_text(encoding="utf-8")
    deep_user = (
        f"Candidatos de esta semana ({len(top)} en total):\n\n{_serialize(top, text_chars=1200)}\n\n"
        f"IMPORTANTE: evaluá los {len(top)} candidatos sin excepción."
    )
    for attempt in (1, 2):
        text, c = _call(client, config.MODEL_DEEP, deep_system, deep_user, max_tokens=8000)
        cost += c
        scored = _parse(text)
        if scored:
            return scored, cost
        if cost >= config.COST_LIMIT_USD:
            print(f"[score] GUARDRAIL: ${cost:.3f} — sin reintento")
            break
        print(f"[score] deep intento {attempt} sin resultados válidos"
              + (", reintentando" if attempt == 1 else " — abortando"))
    return [], cost


def _call(client: Anthropic, model: str, system: str, user: str,
          max_tokens: int) -> tuple[str, float]:
    """Una llamada al modelo: intenta Batch API (50% off), cae a directa."""
    if config.USE_BATCH:
        try:
            return _call_batch(client, model, system, user, max_tokens)
        except Exception as e:  # noqa: BLE001 — batch nunca debe matar el run
            print(f"[score] batch falló ({e}) — fallback a llamada directa")
    return _call_direct(client, model, system, user, max_tokens)


def _call_batch(client: Anthropic, model: str, system: str, user: str,
                max_tokens: int) -> tuple[str, float]:
    batch = client.messages.batches.create(
        requests=[
            {
                "custom_id": "scouting",
                "params": {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            }
        ]
    )
    deadline = time.time() + config.BATCH_TIMEOUT_MIN * 60
    while time.time() < deadline:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            for entry in client.messages.batches.results(batch.id):
                if entry.result.type != "succeeded":
                    raise RuntimeError(f"batch result: {entry.result.type}")
                msg = entry.result.message
                cost = _cost(model, msg.usage.input_tokens, msg.usage.output_tokens,
                             discount=BATCH_DISCOUNT)
                text = "".join(bl.text for bl in msg.content if bl.type == "text")
                print(f"[score] batch {model}: in={msg.usage.input_tokens} "
                      f"out={msg.usage.output_tokens} costo=${cost:.4f} (50% off)")
                return text, cost
            raise RuntimeError("batch sin resultados")
        time.sleep(20)
    raise TimeoutError(f"batch no terminó en {config.BATCH_TIMEOUT_MIN} min")


def _call_direct(client: Anthropic, model: str, system: str, user: str,
                 max_tokens: int) -> tuple[str, float]:
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    cost = _cost(model, msg.usage.input_tokens, msg.usage.output_tokens)
    text = "".join(bl.text for bl in msg.content if bl.type == "text")
    print(f"[score] directo {model}: stop={msg.stop_reason} "
          f"in={msg.usage.input_tokens} out={msg.usage.output_tokens} costo=${cost:.4f}")
    return text, cost


def _cost(model: str, input_tokens: int, output_tokens: int,
          discount: float = 1.0) -> float:
    p_in, p_out = PRICES.get(model, (3.00, 15.00))  # default conservador
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000 * discount


def _rank_from_triage(text: str, items: list[Item]) -> list[Item]:
    """Ordena los items según los scores del triage (mayor a menor)."""
    data = _loads_forgiving(text)
    if not data:
        return []
    by_url = {it.url: it for it in items}
    scores: dict[str, int] = {}
    for obj in data:
        try:
            url = obj["url"]
            total = int(obj.get("problema_score", 0)) + int(obj.get("barrera_score", 0))
            if url in by_url:
                scores[url] = total
        except Exception:  # noqa: BLE001
            continue
    ranked = sorted(scores, key=scores.get, reverse=True)
    # Excluidos (total=0) no pasan al deep aunque haya cupo.
    return [by_url[u] for u in ranked if scores[u] > 0]


def _serialize(items: list[Item], text_chars: int) -> str:
    payload = [
        {
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "engagement": it.engagement,
            "text": it.text[:text_chars],
        }
        for it in items
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse(text: str) -> list[ScoredItem]:
    data = _loads_forgiving(text)
    scored: list[ScoredItem] = []
    for obj in data:
        try:
            scored.append(ScoredItem.model_validate(obj))
        except Exception as e:  # noqa: BLE001 — un item malo no tumba el resto
            print(f"[score] item descartado por validación: {e}")
    print(f"[score] {len(data)} recibidos del modelo, {len(scored)} válidos")
    return scored


def _loads_forgiving(text: str) -> list:
    """json.loads con recorte de ruido y reparación automática."""
    raw = _extract_json_array(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[score] JSON con errores, intentando reparar: {e}")
        try:
            data = json.loads(repair_json(raw))
            print("[score] JSON reparado exitosamente")
        except Exception as e2:  # noqa: BLE001
            print(f"[score] JSON irreparable: {e2}")
            return []
    return data if isinstance(data, list) else []


def _extract_json_array(text: str) -> str:
    """Recorta al primer '[' y último ']' por si el modelo agrega ruido."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return "[]"
    return text[start : end + 1]
