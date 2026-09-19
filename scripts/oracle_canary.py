#!/usr/bin/env python3
"""CANARIO de costo/calidad para el "Oracle" del scouting — NO es producción.

Mide con llamadas reales lo que hoy solo se estimaba (memoria: "medir costos
reales, no proyectar sin evidencia"):
  0. Sondeo GRATIS de qué fuentes públicas de quejas/datos abiertos responden
     desde el runner de CI (varias fuentes bloquean IPs de cloud).
  B. Minería de quejas por país con búsqueda web REAL (1 LatAm + 1 no-inglés
     del mundo, para ver si el costo/calidad varía por ecosistema).
  C. Consejo de críticos: puntúa cada "semilla" de idea con el rubric y
     decide qué entra al Vault (umbral >= 6/10, igual que el Oracle de Alex).

Solo usa fuentes PÚBLICAS — nada personal de GBrain (el repo es público y los
logs de Actions también lo son). Guardrail de gasto propio.
"""
from __future__ import annotations

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

COST_CEILING = 2.0  # aborta si el canario completo pasa de esto
MAX_SEARCHES_PER_COUNTRY = 4
COUNTRIES = [
    ("México", "Profeco, Condusef/Buró de Entidades Financieras, reseñas de apps, foros y prensa"),
    ("Alemania", "Verbraucherzentrale, Stiftung Warentest, Trustpilot, reseñas de apps, foros y prensa"),
]

# Rubric adaptado del Oracle de Alex (25/25/20/20/10) a ideas de negocio.
WEIGHTS = {
    "fit_fundador": 0.25,
    "evidencia_dolor": 0.25,
    "por_que_ahora": 0.20,
    "hueco_vs_incumbentes": 0.20,
    "testeabilidad": 0.10,
}
VAULT_THRESHOLD = 6.0

PROBES = [
    ("CFPB complaints API (EEUU)", "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/?size=1&format=json"),
    ("Profeco datos abiertos (MX)", "https://datos.gob.mx/busca/dataset?q=profeco"),
    ("consumidor.gov.br dados abertos (BR)", "https://dados.gov.br/dados/conjuntos-dados/reclamacoes-do-consumidor-gov-br"),
    ("Reclame Aqui (BR)", "https://www.reclameaqui.com.br/"),
    ("Trustpilot categorías (global)", "https://www.trustpilot.com/categories"),
    ("Reddit r/mexico JSON", "https://www.reddit.com/r/mexico/top.json?t=month&limit=1"),
    ("SERNAC (CL)", "https://www.sernac.cl/"),
    ("INDECOPI (PE)", "https://www.indecopi.gob.pe/"),
]

MINING_SYSTEM = """Sos un investigador de dolores de consumidores y pymes. Buscás
QUEJAS REALES y recurrentes (no opiniones de expertos) y las agrupás en dolores
concretos. Verificás con búsqueda web real; cero cifras o fuentes inventadas.

Reglas de formato: texto plano, citás fuentes como "(fuente: nombre, año)" —
NUNCA tags XML/HTML tipo cite. Respondé EXCLUSIVAMENTE un objeto JSON:
{"dolores": [{"dolor": "...", "quien_sufre": "...", "evidencia": "cifras/citas reales con fuente",
 "fuente_url": "...", "solucion_existente": "quién ya lo resuelve, o 'no encontré'",
 "hueco_hipotesis": "qué capa adyacente queda sin cubrir"}]}
Máximo 4 dolores, los más específicos y accionables. Preferí dolores B2B/pyme o
de alto ticket sobre quejas triviales de consumo."""

COUNCIL_SYSTEM = """Sos un consejo de 3 críticos que evalúa 'semillas' de idea de negocio
para un fundador. Críticos: (1) VC escéptico, (2) operador/cliente típico del país,
(3) abogado/regulador. Cada uno da UNA objeción concreta de una línea. Después puntuás
cada semilla de 0 a 10 en: fit_fundador, evidencia_dolor, por_que_ahora,
hueco_vs_incumbentes, testeabilidad (qué tan barato es testear el supuesto más frágil).
Sé duro: 5 es 'mediocre', 8+ es excepcional. Sin evidencia real en el input, evidencia_dolor <= 4.

{FOUNDER_CONTEXT}

Respondé EXCLUSIVAMENTE JSON: {"semillas": [{"id": <int>, "objeciones": ["...","...","..."],
"fit_fundador": n, "evidencia_dolor": n, "por_que_ahora": n, "hueco_vs_incumbentes": n,
"testeabilidad": n, "veredicto_una_linea": "..."}]}"""


def probe_sources() -> None:
    print("[canary] === 0. Sondeo de fuentes desde el runner (gratis) ===")
    with httpx.Client(timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (scouting-agent canary)"}) as c:
        for name, url in PROBES:
            try:
                r = c.get(url)
                print(f"[canary] probe {r.status_code} {len(r.content):>7}B  {name}")
            except Exception as e:  # noqa: BLE001
                print(f"[canary] probe ERR  {name}: {type(e).__name__}")


def main() -> None:
    probe_sources()

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    tools = web_search_tool(MAX_SEARCHES_PER_COUNTRY)
    total = 0.0
    seeds: list[dict] = []

    for country, sources in COUNTRIES:
        if total >= COST_CEILING:
            print(f"[canary] GUARDRAIL ${total:.2f} — se corta")
            break
        print(f"\n[canary] === B. Minería de quejas: {country} ===")
        user = (f"País: {country}. Fuentes sugeridas: {sources}. Buscá las quejas "
                f"recurrentes más fuertes de los últimos 6 meses y devolvé el JSON.")
        t0 = time.time()
        text, cost, truncated = _call_direct(
            client, config.MODEL_DEEP, MINING_SYSTEM, user,
            max_tokens=5000, tools=tools, log_prefix=f"[canary:{country}]",
        )
        total += cost
        obj = _parse_object(text) or {}
        found = obj.get("dolores", []) if isinstance(obj, dict) else []
        print(f"[canary] {country}: {len(found)} dolores, costo=${cost:.4f}, "
              f"{time.time() - t0:.0f}s{' TRUNCADO' if truncated else ''}")
        for d in found:
            d["pais"] = country
            d["id"] = len(seeds) + 1
            seeds.append(d)
            print(f"[canary]   #{d['id']} {d.get('dolor', '?')[:110]}")

    if not seeds:
        print("[canary] sin semillas — no se corre el consejo")
        print(f"[canary] === COSTO TOTAL: ${total:.4f} ===")
        return

    print("\n[canary] === C. Consejo de críticos ===")
    system = COUNCIL_SYSTEM.replace("{FOUNDER_CONTEXT}", _founder_context())
    brief = "\n\n".join(
        f"[{s['id']}] ({s['pais']}) DOLOR: {s.get('dolor')}\nQuién: {s.get('quien_sufre')}\n"
        f"Evidencia: {s.get('evidencia')}\nSolución existente: {s.get('solucion_existente')}\n"
        f"Hueco: {s.get('hueco_hipotesis')}" for s in seeds
    )
    text, cost, truncated = _call_direct(
        client, config.MODEL_DEEP, system, brief, max_tokens=5000, log_prefix="[canary:council]",
    )
    total += cost
    obj = _parse_object(text) or {}
    by_id = {s["id"]: s for s in seeds}
    print(f"[canary] council costo=${cost:.4f}{' TRUNCADO' if truncated else ''}")
    for r in obj.get("semillas", []):
        score = sum(float(r.get(k, 0)) * w for k, w in WEIGHTS.items())
        verdict = "VAULT" if score >= VAULT_THRESHOLD else "descarta"
        s = by_id.get(r.get("id"), {})
        print(f"[canary] {verdict:8} {score:4.1f}  #{r.get('id')} ({s.get('pais')}) {s.get('dolor', '')[:80]}")
        print(f"[canary]           → {r.get('veredicto_una_linea', '')[:160]}")

    print(f"\n[canary] === COSTO TOTAL CANARIO: ${total:.4f} "
          f"({len(seeds)} semillas de {len(COUNTRIES)} países) ===")


if __name__ == "__main__":
    main()
