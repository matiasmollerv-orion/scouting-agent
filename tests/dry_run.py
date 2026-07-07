#!/usr/bin/env python3
"""Ensayo general del run semanal — $0 de API.

Ejecuta src.main.run() COMPLETO con datos reales (fetch, pool, newsletters)
pero con un cliente Anthropic FALSO que responde como respondería Claude.
Valida todo el código del sábado excepto la llamada HTTP real:
fetch → prefilter → triage → deep → gate → reporte → full.json → stats → email.

La persistencia se redirige a un sandbox: NO contamina seen_urls, pool ni
stats del run real del sábado. El email de muestra llega de verdad (Gmail),
marcado [ENSAYO $0].

Uso:
  python tests/dry_run.py batch     # valida el camino Batch API
  python tests/dry_run.py fallback  # valida batch caído -> llamada directa
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

MODE = sys.argv[1] if len(sys.argv) > 1 else "batch"
assert MODE in ("batch", "fallback"), "modo: batch | fallback"

# Credenciales Gmail locales (mismas del Financial Dashboard) para que el
# email de ensayo llegue de verdad. Sin ellas, el envío solo se omite.
import os  # noqa: E402

env_file = Path.home() / "Documents/Claude/FinancialDashboard/.env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            if k.strip() in ("GMAIL_USER", "GMAIL_APP_PASSWORD"):
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


# ---------- Cliente Anthropic falso ----------

def _payload_items(user_content: str) -> list[dict]:
    start, end = user_content.find("["), user_content.rfind("]")
    return json.loads(user_content[start:end + 1])


def _fake_response_text(system: str, user_content: str) -> str:
    items = _payload_items(user_content)
    if "TRIAGE" in system:
        # Scores descendentes con algunos excluidos (0) — determinista.
        out = []
        for i, it in enumerate(items):
            total = max(0, 32 - i * 2) if i % 7 != 3 else 0
            out.append({"url": it["url"],
                        "problema_score": min(25, int(total * 0.65)),
                        "barrera_score": min(15, total - int(total * 0.65))})
        return json.dumps(out, ensure_ascii=False)
    # Deep: ScoredItem completo y válido por candidato.
    out = []
    for i, it in enumerate(items):
        out.append({
            "title": it["title"], "url": it["url"], "source": it["source"],
            "problema_score": 20 - i, "barrera_score": 11,
            "replicabilidad": {"nivel": "Alta", "evidencia": "sin player local identificado"},
            "ventana": {"nivel": "Media" if i % 2 else "Alta", "evidencia": "12-18 meses estimados"},
            "tamano_mercado": {"nivel": "Alta", "evidencia": "mercado B2B amplio en LatAm"},
            "resumen": f"[ENSAYO] Análisis simulado de «{it['title'][:60]}» con acentos y ñ para validar encoding.",
            "b2b_o_b2c": "B2B", "componente_ia": True,
            "tipo_fundador": "comercial con cofundador técnico",
            "mercado_actual": "EEUU",
            "company_url": "https://ejemplo.com", "funding_raised": "$2M seed",
            "stage": "Seed", "por_que_ahora": "costo de agentes IA cayó 10x en 2025",
            "modelo_negocio": "SaaS USD 99/mes por equipo",
            "competencia_local": "no identificada",
            "fit_tesis": "Futuro del trabajo",
            "next_step": "hablar con 5 gerentes de operaciones esta semana",
        })
    return json.dumps(out, ensure_ascii=False)


def _fake_msg(system: str, user_content: str) -> SimpleNamespace:
    text = _fake_response_text(system, user_content)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=9000, output_tokens=len(text) // 4,
                              server_tool_use=None),
        stop_reason="end_turn",
    )


class FakeBatches:
    def __init__(self):
        self._reqs: dict[str, dict] = {}

    def create(self, requests):
        if MODE == "fallback":
            raise RuntimeError("simulación: Batch API caída")
        params = requests[0]["params"]
        self._reqs["b1"] = params
        print("  [fake] batch creado OK (formato de request aceptado)")
        return SimpleNamespace(id="b1")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended")

    def results(self, batch_id):
        p = self._reqs[batch_id]
        msg = _fake_msg(p["system"], p["messages"][0]["content"])
        yield SimpleNamespace(result=SimpleNamespace(type="succeeded", message=msg))


class FakeStream:
    def __init__(self, system, user_content):
        self._msg = _fake_msg(system, user_content)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._msg


class FakeMessages:
    def __init__(self):
        self.batches = FakeBatches()

    def stream(self, *, model, max_tokens, system, messages):
        print(f"  [fake] llamada directa a {model}")
        return FakeStream(system, messages[0]["content"])


class FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = FakeMessages()


# ---------- Sandbox + ejecución ----------

def main() -> None:
    import src.main as M
    import src.pipeline.score as S

    sandbox = Path(tempfile.mkdtemp(prefix="scouting-dry-"))
    print(f"=== ENSAYO GENERAL modo={MODE} · sandbox={sandbox} ===\n")

    S.Anthropic = FakeAnthropic                      # sin API real
    M.REPORTS_DIR = sandbox                          # reportes al sandbox
    M.SEEN_FILE = sandbox / "seen_urls.json"         # no contamina el real
    M.STATS_FILE = sandbox / "stats.json"
    M.reset_pool = lambda: print("[dry] reset_pool omitido (pool real intacto)")
    M._capture_to_gbrain = lambda p: print("[dry] captura a gbrain omitida")
    _orig_send = M.send_html
    M.send_html = lambda subject, html, **kw: _orig_send(f"[ENSAYO $0 · {MODE}] {subject}", html, **kw)

    out = M.run()

    # Verificación de artefactos
    week_md = out
    full = list(sandbox.glob("*-full.json"))
    stats = sandbox / "stats.json"
    seen = sandbox / "seen_urls.json"
    ok = True
    for label, cond in [
        ("reporte .md con panorama", week_md.exists() and "Panorama completo" in week_md.read_text()),
        ("dataset full.json", bool(full) and len(json.loads(full[0].read_text())["triage"]) > 0),
        ("stats.json con temas", stats.exists() and "themes" in stats.read_text()),
        ("seen_urls.json (sandbox)", seen.exists()),
    ]:
        print(f"  {'✅' if cond else '❌'} {label}")
        ok = ok and cond
    print(f"\n=== {'ENSAYO OK' if ok else 'ENSAYO CON FALLAS'} (modo {MODE}) — costo API: $0.00 ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
