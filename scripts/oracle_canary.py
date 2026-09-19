#!/usr/bin/env python3
"""CANARIO v2 del "Oracle" — Haiku vs Sonnet en minería de NECESIDADES por
país×lente. NO es producción.

v1 (2026-09-19) midió costo pero tuvo dos errores míos: (a) el consejo
puntuaba `fit_fundador` con 25% y violaba la regla dura de score.md (no bajar
puntajes por falta de experiencia/red del fundador); (b) la minería era solo de
"quejas" genéricas. v2 corrige ambos:
  - Necesidades = queja | brecha | fuerza_externa | oferta, guiadas por LENTE.
  - Consejo sin penalización de fit (bonus 0-1 como máximo), y juzga A CIEGAS
    las semillas de Haiku y de Sonnet (mismo juez, sin saber quién las generó).
  - 2 búsquedas por combinación (supuesto de costo a calibrar).
  - Chequeo de URLs citadas (proxy barato de alucinación).

Solo fuentes públicas (repo y logs de Actions públicos). Guardrail de gasto.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import httpx  # noqa: E402
from anthropic import Anthropic  # noqa: E402

from scripts.market_analysis import _founder_context, _parse_object  # noqa: E402
from src import config  # noqa: E402
from src.pipeline.score import _call_direct, web_search_tool  # noqa: E402

COST_CEILING = 1.5
SEARCHES_PER_PAIR = 2
MODELS = [("haiku", config.MODEL_TRIAGE), ("sonnet", config.MODEL_DEEP)]

LENSES = {
    "futuro_trabajo": (
        "Futuro del trabajo",
        "Actores: pymes y scale-ups de 5-300 personas, equipos remotos, freelancers "
        "(NO solo grandes corporaciones). Necesidad: hacer más con menos gente — agentes "
        "de IA que absorben tareas administrativas, gestionar y coordinar equipos sin RRHH "
        "ni PMO, medir output. Señales típicas: brecha (procesos manuales, cargos "
        "administrativos repetidos en ofertas de empleo), queja (reseñas 1-3 estrellas de "
        "herramientas de gestión de equipos), oferta (startups nuevas).",
    ),
    "fintech": (
        "Fintech y seguros (amplio)",
        "Actores: personas (incl. no bancarizadas), independientes, pymes, empresas y quienes "
        "las atienden. Necesidad: hábitos financieros sanos, acceso a crédito e inversión, "
        "pagos, seguros, gasto corporativo, y modelos genuinamente nuevos (crédito "
        "comunitario, datos alternativos de crédito para quien no tiene historial). Señales: "
        "queja (reguladores/ombudsman), brecha (bancarización, penetración de seguros e "
        "inversión), oferta (modelos nuevos), fuerza externa (open finance, regulación de "
        "pagos). Excluir 'otro neobank o app de trading más' sin modelo distinto.",
    ),
    "ia_real": (
        "IA aplicada al mundo real",
        "Actores: negocios con operación física o conversación presencial (tiendas, plantas, "
        "faenas, clínicas, flotas, hogares) y sus supervisores. Necesidad: eficiencia o "
        "calidad donde hoy se depende de supervisión humana o intuición — coaching a "
        "vendedores por audio, seguridad laboral, productividad de línea, control de "
        "calidad, mermas — usando cámaras, audio, wearables o sensores. Señales: oferta "
        "(startups y pilotos con clientes reales), brecha (procesos supervisados a mano), "
        "fuerza externa (leyes de grabación y privacidad: barrera clave). Excluir dev tools "
        "y software de oficina puro.",
    ),
}

# Variedad de idioma/ecosistema/tipo de señal dominante.
PAIRS = [
    ("Chile", "futuro_trabajo"),
    ("Brasil", "fintech"),
    ("Corea del Sur", "ia_real"),
    ("Alemania", "futuro_trabajo"),
]

MINING_SYSTEM = """Sos un investigador de NECESIDADES de mercado para un fundador. Una necesidad puede
estar EXPRESADA (queja) o LATENTE: brecha (algo que debería existir o usarse y no está),
fuerza_externa (regulación o cambio que obliga a actuar) u oferta (algo nuevo que ya funciona
en otro país). Buscás con búsqueda web REAL, en el país indicado y dentro del lente indicado.
Verificás; cero cifras, fuentes o empresas inventadas — si algo no lo pudiste verificar,
escribí 'no verificado'.

Reglas: texto plano; citás como "(fuente: nombre, año)"; NUNCA tags XML/HTML. Excluí dev tools
para programadores sin comprador no técnico, marketplaces genéricos que compiten con MeLi/Rappi
y gigantes que ya son el status quo. Para cada necesidad incluí una hipótesis de TRANSFERENCIA
a Chile/LatAm (qué habría que adaptar y si ya hay alguien allá).

Respondé EXCLUSIVAMENTE un objeto JSON:
{"necesidades":[{"necesidad":"...","quien":"...","tipo_senal":"queja|brecha|fuerza_externa|oferta",
"evidencia":"cifras/hechos reales con fuente","fuente_url":"...","solucion_existente":"quién ya lo
resuelve o 'no encontré'","transferencia_chile_latam":"..."}]}
Máximo 3 necesidades, las más específicas y accionables."""

COUNCIL_SYSTEM = """Sos un consejo de 3 críticos (VC escéptico, operador/cliente del mercado,
abogado/regulador) que evalúa 'semillas' de idea de negocio. Cada crítico da UNA objeción de
máximo 20 palabras. Puntuás de 0 a 10: evidencia_necesidad (¿evidencia verificable o es opinión?),
tamano_gravedad, por_que_ahora, hueco_vs_incumbentes (si la idea viene de otro país: ¿es creíble la
transferencia a Chile/LatAm y queda hueco local?), testeabilidad (¿el supuesto más frágil se puede
probar barato?). Sé duro: 5 = mediocre, 8+ = excepcional; sin evidencia real,
evidencia_necesidad <= 4.

REGLA DURA del fundador (no negociable): NO bajes ningún puntaje porque la idea quede lejos del
perfil, la red o la experiencia del fundador — siempre puede sumar un socio con la expertise que
falte. El encaje con el fundador solo puede SUMAR: `bonus_fit` de 0 a 1 (0 si no hay encaje
evidente; nunca negativo).

{FOUNDER_CONTEXT}

Respondé EXCLUSIVAMENTE JSON: {"semillas":[{"id":n,"objeciones":["...","...","..."],
"evidencia_necesidad":n,"tamano_gravedad":n,"por_que_ahora":n,"hueco_vs_incumbentes":n,
"testeabilidad":n,"bonus_fit":n,"veredicto":"máx 20 palabras"}]}"""

WEIGHTS = {"evidencia_necesidad": 0.30, "tamano_gravedad": 0.20, "por_que_ahora": 0.20,
           "hueco_vs_incumbentes": 0.20, "testeabilidad": 0.10}
VAULT_THRESHOLD = 6.0


def check_url(client: httpx.Client, url: str) -> str:
    if not url or not url.startswith("http"):
        return "sin_url"
    try:
        r = client.get(url)
    except Exception:  # noqa: BLE001
        return "error"
    if r.status_code < 400:
        return "ok"
    if r.status_code in (401, 403, 429, 999):
        return "bloqueada"  # inconclusa: el sitio bloquea IPs de cloud
    return f"rota_{r.status_code}"


def main() -> None:
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    tools = web_search_tool(SEARCHES_PER_PAIR)
    total = 0.0
    seeds: list[dict] = []
    per_model = {m: {"cost": 0.0, "items": 0, "fail": 0} for m, _ in MODELS}

    for country, lens_key in PAIRS:
        lens_name, lens_def = LENSES[lens_key]
        for tag, model in MODELS:
            if total >= COST_CEILING:
                print(f"[canary] GUARDRAIL ${total:.2f} — se corta")
                break
            print(f"\n[canary] === {tag.upper()} · {country} × {lens_name} ===")
            user = (f"País: {country}\nLente: {lens_name}\nDefinición del lente: {lens_def}\n"
                    f"Buscá las necesidades más fuertes y recientes (últimos 12 meses).")
            t0 = time.time()
            try:
                text, cost, truncated = _call_direct(
                    client, model, MINING_SYSTEM, user, max_tokens=6000, tools=tools,
                    log_prefix=f"[canary:{tag}]",
                )
            except Exception as e:  # noqa: BLE001
                print(f"[canary] ERROR {tag}: {type(e).__name__}: {str(e)[:200]}")
                per_model[tag]["fail"] += 1
                continue
            total += cost
            per_model[tag]["cost"] += cost
            obj = _parse_object(text) or {}
            items = obj.get("necesidades", []) if isinstance(obj, dict) else []
            if not items:
                per_model[tag]["fail"] += 1
            print(f"[canary] {tag}: {len(items)} necesidades, costo=${cost:.4f}, "
                  f"{time.time() - t0:.0f}s{' TRUNCADO' if truncated else ''}")
            for it in items:
                per_model[tag]["items"] += 1
                it.update(modelo=tag, pais=country, lente=lens_name, id=len(seeds) + 1)
                seeds.append(it)
                print(f"[canary]  ({it['tipo_senal']}) {it.get('necesidad', '')[:230]}")
                print(f"[canary]     evidencia: {it.get('evidencia', '')[:260]}")
                print(f"[canary]     url: {it.get('fuente_url', '')}")
                print(f"[canary]     transfer: {it.get('transferencia_chile_latam', '')[:200]}")

    if not seeds:
        print("[canary] sin semillas")
        return

    print("\n[canary] === Chequeo de URLs citadas ===")
    with httpx.Client(timeout=10, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (scouting-agent canary)"}) as hc:
        for s in seeds:
            s["url_estado"] = check_url(hc, s.get("fuente_url", ""))

    print("\n[canary] === Consejo (rubric sin penalizar fit), semillas a CIEGAS ===")
    order = seeds[:]
    random.Random(7).shuffle(order)
    brief = "\n\n".join(
        f"[{s['id']}] NECESIDAD: {s.get('necesidad')}\nQuién: {s.get('quien')}\n"
        f"Tipo de señal: {s.get('tipo_senal')}\nEvidencia: {s.get('evidencia')}\n"
        f"Solución existente: {s.get('solucion_existente')}\n"
        f"Transferencia a Chile/LatAm: {s.get('transferencia_chile_latam')}"
        for s in order
    )
    system = COUNCIL_SYSTEM.replace("{FOUNDER_CONTEXT}", _founder_context())
    text, cost, truncated = _call_direct(
        client, config.MODEL_DEEP, system, brief, max_tokens=8000, log_prefix="[canary:council]",
    )
    total += cost
    obj = _parse_object(text) or {}
    by_id = {s["id"]: s for s in seeds}
    scored: dict[str, list[float]] = {m: [] for m, _ in MODELS}
    urls: dict[str, dict[str, int]] = {m: {} for m, _ in MODELS}
    for s in seeds:
        urls[s["modelo"]][s["url_estado"]] = urls[s["modelo"]].get(s["url_estado"], 0) + 1
    for r in obj.get("semillas", []):
        s = by_id.get(r.get("id"))
        if not s:
            continue
        base = sum(float(r.get(k, 0)) * w for k, w in WEIGHTS.items())
        score = base + min(max(float(r.get("bonus_fit", 0)), 0.0), 1.0)
        s["score"] = score
        scored[s["modelo"]].append(score)
        verdict = "VAULT" if score >= VAULT_THRESHOLD else "descarta"
        print(f"[canary] {verdict:8} {score:4.1f} [{s['modelo']:6}] ({s['pais']}, {s['tipo_senal']}) "
              f"{s.get('necesidad', '')[:90]}")
        print(f"[canary]           → {r.get('veredicto', '')[:150]}")

    print("\n[canary] === RESUMEN POR MODELO ===")
    for tag, _ in MODELS:
        sc = scored[tag]
        avg = sum(sc) / len(sc) if sc else 0.0
        vault = sum(1 for x in sc if x >= VAULT_THRESHOLD)
        print(f"[canary] {tag:6} costo=${per_model[tag]['cost']:.4f} necesidades={per_model[tag]['items']} "
              f"fallas={per_model[tag]['fail']} score_medio={avg:.2f} vault={vault}/{len(sc)} "
              f"urls={urls[tag]}")
    print(f"[canary] === COSTO TOTAL CANARIO v2: ${total:.4f} (incluye consejo ${cost:.4f}) ===")


if __name__ == "__main__":
    main()
