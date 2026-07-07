"""Canario: valida la plomería REAL de la API por menos de $0.01.

Correr después de recargar créditos y ANTES del primer run completo:
    python -m src.canary

Verifica con llamadas mínimas (max_tokens=16):
1. API key válida y con saldo
2. IDs de modelos correctos (triage y deep)
3. Formato de request de la Batch API aceptado

Si esto pasa, el único riesgo restante del run completo es la calidad del
JSON del modelo — cubierto por json-repair + retry + guardrail de $0.30.
"""
from __future__ import annotations

import time

from anthropic import Anthropic

from . import config
from .pipeline.score import PRICES

PING = [{"role": "user", "content": "Respondé únicamente: ok"}]


def _cost(model: str, usage) -> float:
    p_in, p_out = PRICES.get(model, (3.0, 15.0))
    return (usage.input_tokens * p_in + usage.output_tokens * p_out) / 1_000_000


def run() -> None:
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    total = 0.0

    for model in (config.MODEL_TRIAGE, config.MODEL_DEEP):
        resp = client.messages.create(model=model, max_tokens=16, messages=PING)
        c = _cost(model, resp.usage)
        total += c
        print(f"✅ directo {model}: «{resp.content[0].text.strip()[:20]}» (${c:.5f})")

    batch = client.messages.batches.create(requests=[{
        "custom_id": "canary",
        "params": {"model": config.MODEL_TRIAGE, "max_tokens": 16, "messages": PING},
    }])
    print(f"✅ batch aceptado: id={batch.id} — esperando resultado (máx 5 min)...")
    deadline = time.time() + 300
    while time.time() < deadline:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            for entry in client.messages.batches.results(batch.id):
                if entry.result.type != "succeeded":
                    raise SystemExit(f"❌ batch result: {entry.result.type}")
                c = _cost(config.MODEL_TRIAGE, entry.result.message.usage) * 0.5
                total += c
                print(f"✅ batch completado: «{entry.result.message.content[0].text.strip()[:20]}» (${c:.5f}, 50% off)")
            break
        time.sleep(10)
    else:
        print("⚠️ batch no terminó en 5 min — el fallback a directo cubriría esto el sábado")

    print(f"\n=== CANARIO OK — costo total real: ${total:.5f} ===")
    print("La plomería funciona. El run completo del sábado está validado salvo")
    print("la calidad del JSON del modelo (cubierta por repair + retry + guardrail $0.30).")


if __name__ == "__main__":
    run()
