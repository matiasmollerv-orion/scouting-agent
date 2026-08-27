from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from anthropic import Anthropic
from json_repair import repair_json

from .. import config
from ..models import Item, ScoredItem

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass
class ScoreResult:
    """Resultado completo del scoring — incluye el triage de TODOS los
    candidatos, no solo los que pasaron al análisis profundo. Las ideas
    descartadas son inteligencia de mercado para el segundo cerebro."""

    deep: list[ScoredItem] = field(default_factory=list)
    triage: list[dict] = field(default_factory=list)  # {title, url, source, total}
    cost_usd: float = 0.0
    truncated: bool = False  # el deep chocó max_tokens y se rescató con repair

# USD por millón de tokens (input, output). Actualizar si cambian los modelos.
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
}
BATCH_DISCOUNT = 0.5  # Batch API: 50% off input y output
PRICE_WEB_SEARCH = 0.01  # USD por búsqueda ($10 / 1000) — sin descuento batch

def web_search_tool(max_uses: int) -> list[dict]:
    """Tool de búsqueda web REAL — sin esto, competencia_local/competencia_global/
    ventana se completaban desde el prior de entrenamiento del modelo, sin
    verificar nada. Server-side (Anthropic ejecuta y sigue generando en la
    misma llamada), no requiere loop manual de tool_use/tool_result.

    Uso deliberadamente la variante BÁSICA (web_search_20250305), no
    web_search_20260209 (la vigente para Sonnet 5, con filtrado dinámico).
    La `20260209` corre code execution por debajo, lo que suma iteraciones
    al loop server-side de tools (tope de 10 antes de stop_reason=pause_turn)
    — en Batch API un pause_turn no se puede resumir, el resultado queda
    incompleto. La básica ya está probada en retro.py y evita ese riesgo."""
    return [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}]


WEB_SEARCH_TOOL = web_search_tool(config.MAX_WEB_SEARCHES_DEEP)  # deep semanal (8 items)


def score(items: list[Item]) -> ScoreResult:
    """Scoring en dos etapas.

    Etapa 1 (triage, Haiku): puntúa TODOS los candidatos con output mínimo
    (~30 tokens/item). Etapa 2 (deep, Sonnet): análisis completo solo de los
    TOP_DEEP mejores. Ambas intentan Batch API (50% off) con fallback a
    llamada directa. Guardrail: si el costo acumulado supera COST_LIMIT_USD,
    se aborta lo que falte.
    """
    result = ScoreResult()
    if not items:
        return result

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # --- Etapa 1: triage ---
    triage_system = (PROMPTS_DIR / "triage.md").read_text(encoding="utf-8")
    triage_user = (
        f"Candidatos ({len(items)}):\n\n{_serialize(items, text_chars=400)}\n\n"
        f"Puntuá los {len(items)} sin excepción."
    )
    text, c, _ = _call(client, config.MODEL_TRIAGE, triage_system, triage_user, max_tokens=4000)
    result.cost_usd += c
    ranked, scores_by_url = _rank_from_triage(text, items)
    # Se guarda el texto (mismo largo que usa el deep) aunque el item no
    # llegue a análisis profundo automático: es lo que el dashboard necesita
    # para poder pedir el análisis on-demand más adelante sin re-fetchear.
    result.triage = [
        {"title": it.title, "url": it.url, "source": it.source,
         "total": scores_by_url.get(it.url), "text": it.text[:1200]}
        for it in items
    ]
    if not ranked:
        print("[score] triage sin resultados — fallback: top por orden de prefilter")
        ranked = items[: config.TOP_DEEP]
    top = ranked[: config.TOP_DEEP]
    print(f"[score] triage: {len(items)} candidatos -> top {len(top)} a análisis profundo")

    if result.cost_usd >= config.COST_LIMIT_USD:
        print(f"[score] GUARDRAIL: ${result.cost_usd:.3f} ≥ ${config.COST_LIMIT_USD} — se aborta etapa deep")
        return result

    # --- Etapa 2: análisis profundo ---
    # Las ideas propias solo se inyectan en el deep (no en el triage barato):
    # es contexto que solo importa para el análisis rico, no para descartar rápido.
    ideas_propias = (PROMPTS_DIR / "ideas_propias.md").read_text(encoding="utf-8")
    deep_system = (PROMPTS_DIR / "score.md").read_text(encoding="utf-8") + "\n\n" + ideas_propias
    deep_user = (
        f"Candidatos de esta semana ({len(top)} en total):\n\n{_serialize(top, text_chars=1200)}\n\n"
        f"IMPORTANTE: evaluá los {len(top)} candidatos sin excepción. "
        "Sé conciso: máximo ~120 palabras por objeto JSON."
    )
    for attempt in (1, 2):
        # 16k tokens: el run 2026-W28 truncó a 8k con newsletters de contenido
        # rico (~1000 tokens/item). Solo se paga lo generado, no el tope.
        text, c, truncated = _call(client, config.MODEL_DEEP, deep_system, deep_user,
                                   max_tokens=16000, tools=WEB_SEARCH_TOOL)
        result.cost_usd += c
        result.deep = _parse(text)
        if result.deep:
            # Truncación rescatada por json-repair: no es falla, pero se avisa
            # para no perder items en silencio si el output crece más.
            if truncated:
                result.truncated = True
                print(f"[score] ⚠️ deep truncado a max_tokens — {len(result.deep)} "
                      f"items rescatados de {len(top)}; subir max_tokens si se repite")
            return result
        if result.cost_usd >= config.COST_LIMIT_USD:
            print(f"[score] GUARDRAIL: ${result.cost_usd:.3f} — sin reintento")
            break
        print(f"[score] deep intento {attempt} sin resultados válidos"
              + (", reintentando" if attempt == 1 else " — abortando"))
    return result


def _call(client: Anthropic, model: str, system: str, user: str,
          max_tokens: int, tools: list[dict] | None = None,
          log_prefix: str = "[score]") -> tuple[str, float, bool]:
    """Una llamada al modelo: intenta Batch API (50% off), cae a directa.

    Retorna (texto, costo_usd, truncado) — truncado=True si el modelo cortó
    la salida por max_tokens (stop_reason). `tools` (ej: web_search) solo se
    pasa cuando corresponde — la etapa de triage nunca lo recibe (costo).
    `log_prefix` es solo cosmético (logs), para que otros callers — ej:
    retro.py, que reusa esta función — no salgan etiquetados "[score]".
    """
    if config.USE_BATCH:
        try:
            return _call_batch(client, model, system, user, max_tokens, tools, log_prefix)
        except Exception as e:  # noqa: BLE001 — batch nunca debe matar el run
            print(f"{log_prefix} batch falló ({e}) — fallback a llamada directa")
    return _call_direct(client, model, system, user, max_tokens, tools, log_prefix)


def _call_batch(client: Anthropic, model: str, system: str, user: str,
                max_tokens: int, tools: list[dict] | None = None,
                log_prefix: str = "[score]") -> tuple[str, float, bool]:
    params = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if tools:
        params["tools"] = tools
    batch = client.messages.batches.create(
        requests=[{"custom_id": "scouting", "params": params}]
    )
    deadline = time.time() + config.BATCH_TIMEOUT_MIN * 60
    while time.time() < deadline:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            for entry in client.messages.batches.results(batch.id):
                if entry.result.type != "succeeded":
                    raise RuntimeError(f"batch result: {entry.result.type}")
                msg = entry.result.message
                if msg.stop_reason == "pause_turn":
                    # El loop server-side de tools llegó a su tope de
                    # iteraciones sin terminar — batch no puede resumirlo
                    # (a diferencia de una llamada directa). Se levanta para
                    # que _call() caiga a _call_direct, que sí puede seguir.
                    raise RuntimeError("pause_turn en batch — loop de tools sin terminar")
                cost = _cost(model, msg.usage.input_tokens, msg.usage.output_tokens,
                             discount=BATCH_DISCOUNT)
                searches = _search_count(msg)
                cost += searches * PRICE_WEB_SEARCH  # búsquedas no llevan descuento batch
                text = "".join(bl.text for bl in msg.content if bl.type == "text")
                print(f"{log_prefix} batch {model}: stop={msg.stop_reason} "
                      f"in={msg.usage.input_tokens} out={msg.usage.output_tokens} "
                      f"búsquedas={searches} costo=${cost:.4f} (50% off en tokens)")
                return text, cost, msg.stop_reason == "max_tokens"
            raise RuntimeError("batch sin resultados")
        time.sleep(20)
    raise TimeoutError(f"batch no terminó en {config.BATCH_TIMEOUT_MIN} min")


def _call_direct(client: Anthropic, model: str, system: str, user: str,
                 max_tokens: int, tools: list[dict] | None = None,
                 log_prefix: str = "[score]") -> tuple[str, float, bool]:
    kwargs = {"tools": tools} if tools else {}
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        **kwargs,
    ) as stream:
        msg = stream.get_final_message()
    searches = _search_count(msg)
    cost = _cost(model, msg.usage.input_tokens, msg.usage.output_tokens) + searches * PRICE_WEB_SEARCH
    text = "".join(bl.text for bl in msg.content if bl.type == "text")
    print(f"{log_prefix} directo {model}: stop={msg.stop_reason} "
          f"in={msg.usage.input_tokens} out={msg.usage.output_tokens} "
          f"búsquedas={searches} costo=${cost:.4f}")
    return text, cost, msg.stop_reason == "max_tokens"


def _cost(model: str, input_tokens: int, output_tokens: int,
          discount: float = 1.0, cache_write_tokens: int = 0,
          cache_read_tokens: int = 0) -> float:
    """cache_write/read solo los pasa dashboard/deep_single.py (única llamada
    de este proyecto con prompt caching real — ver su docstring). El pipeline
    semanal y retro.py llaman con los defaults (0), sin cambio de comportamiento.
    Cache write ~1.25x precio input (TTL 5 min), cache read ~0.1x — no llevan
    el descuento de Batch API porque caching solo se usa en la llamada directa
    del dashboard, nunca junto a `discount` (batch)."""
    p_in, p_out = PRICES.get(model, (3.00, 15.00))  # default conservador
    base = (input_tokens * p_in + output_tokens * p_out) / 1_000_000 * discount
    cache = (cache_write_tokens * p_in * 1.25 + cache_read_tokens * p_in * 0.1) / 1_000_000
    return base + cache


def _search_count(msg) -> int:
    """Búsquedas web reales usadas en la llamada (0 si no hubo tool o no se usó)."""
    server_tool_use = getattr(msg.usage, "server_tool_use", None)
    return getattr(server_tool_use, "web_search_requests", 0) or 0


def _rank_from_triage(text: str, items: list[Item]) -> tuple[list[Item], dict[str, int]]:
    """Ordena los items según los scores del triage. Retorna (ranked, scores_por_url)."""
    data = _loads_forgiving(text)
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
    return [by_url[u] for u in ranked if scores[u] > 0], scores


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
    """Recorta al primer '[' y último ']' por si el modelo agrega ruido.

    Si no hay ']' (output truncado por max_tokens), devuelve desde '[' hasta
    el final: json_repair cierra el array y rescata los items completos.
    En 2026-W28 devolver "[]" aquí botó 8 análisis pagados.
    """
    start = text.find("[")
    if start == -1:
        return "[]"
    end = text.rfind("]")
    if end == -1 or end < start:
        return text[start:]
    return text[start : end + 1]
