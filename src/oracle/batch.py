"""Llamadas al modelo para el Oracle: Batch con MUCHAS solicitudes en un solo
batch (score._call_batch manda una por batch) + llamada directa de respaldo.

Lecciones del canario v2 (2026-09-19) incorporadas acá:
- Sonnet 5 corre con razonamiento adaptativo por defecto: en el canario sacó
  4-6 mil tokens de salida para 1-3 necesidades, y 2 de 4 llamadas se cortaron
  por max_tokens. `effort` acota ese razonamiento y max_tokens va holgado.
- Un `max_tokens` justo trunca el JSON a mitad: la respuesta se pierde entera.
- Los logs de Actions son públicos: acá nunca se imprime contenido, solo costos.
"""
from __future__ import annotations

import time

from anthropic import Anthropic

from src.pipeline.score import BATCH_DISCOUNT, PRICE_WEB_SEARCH, _cost, _search_count

DEFAULT_TIMEOUT_MIN = 150  # la corrida de sept-2026 (93 pares) tardó ~2 h con 3 batches; el job mensual no tiene apuro


def _extra(effort: str | None) -> dict:
    return {"output_config": {"effort": effort}} if effort else {}


def effort_supported(client: Anthropic, model: str, effort: str) -> bool:
    """Preflight barato (~$0.0001): confirma que el modelo acepta `effort`. Si el
    API lo rechaza, el Batch entero saldría con errores por solicitud."""
    try:
        client.messages.create(
            model=model, max_tokens=16, messages=[{"role": "user", "content": "ok"}],
            extra_body=_extra(effort),
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[oracle] effort={effort} no aceptado por {model} ({type(e).__name__}) — se omite")
        return False


def make_request(custom_id: str, model: str, system: str, user: str, max_tokens: int,
                 tools: list[dict] | None = None, effort: str | None = None) -> dict:
    params = {"model": model, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": user}], **_extra(effort)}
    if tools:
        params["tools"] = tools
    return {"custom_id": custom_id, "params": params}


def run_batch(client: Anthropic, requests: list[dict],
              timeout_min: int = DEFAULT_TIMEOUT_MIN, log_prefix: str = "[oracle]") -> dict[str, dict]:
    """Un batch con todas las solicitudes. Devuelve {custom_id: {text, cost, truncated}}
    o {custom_id: {error}} por solicitud fallida (para reintentar en directo)."""
    if not requests:
        return {}
    batch = client.messages.batches.create(requests=requests)
    print(f"{log_prefix} batch {batch.id}: {len(requests)} solicitudes")
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            break
        time.sleep(30)
    else:
        raise TimeoutError(f"batch {batch.id} no terminó en {timeout_min} min")

    model_by_id = {r["custom_id"]: r["params"]["model"] for r in requests}
    out: dict[str, dict] = {}
    for entry in client.messages.batches.results(batch.id):
        cid = entry.custom_id
        if entry.result.type != "succeeded":
            out[cid] = {"error": entry.result.type}
            continue
        msg = entry.result.message
        if msg.stop_reason == "pause_turn":
            out[cid] = {"error": "pause_turn"}  # Batch no puede resumir el loop de tools
            continue
        cost = _cost(model_by_id[cid], msg.usage.input_tokens, msg.usage.output_tokens,
                     discount=BATCH_DISCOUNT)
        cost += _search_count(msg) * PRICE_WEB_SEARCH  # búsquedas sin descuento batch
        text = "".join(bl.text for bl in msg.content if bl.type == "text")
        out[cid] = {"text": text, "cost": cost, "truncated": msg.stop_reason == "max_tokens"}
    return out


def direct_call(client: Anthropic, request: dict) -> dict:
    """Respaldo directo (sin descuento) para una solicitud que falló en el batch."""
    p = request["params"]
    extra = {"extra_body": {"output_config": p["output_config"]}} if "output_config" in p else {}
    tools = {"tools": p["tools"]} if "tools" in p else {}
    with client.messages.stream(model=p["model"], max_tokens=p["max_tokens"], system=p["system"],
                                messages=p["messages"], **tools, **extra) as stream:
        msg = stream.get_final_message()
    cost = _cost(p["model"], msg.usage.input_tokens, msg.usage.output_tokens)
    cost += _search_count(msg) * PRICE_WEB_SEARCH
    text = "".join(bl.text for bl in msg.content if bl.type == "text")
    return {"text": text, "cost": cost, "truncated": msg.stop_reason == "max_tokens"}
