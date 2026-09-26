#!/usr/bin/env python3
"""Corrida MENSUAL del Oracle: minería de necesidades por país × lente →
chequeo de fuentes → consejo de críticos → Vault (Supabase, privado).

Agenda: src/oracle/matrix.py decide qué combinaciones tocan este mes (17 países,
13 lentes, frecuencia por lente, matriz parcial). Todo va por Batch API (-50% en
tokens); las búsquedas web no llevan descuento.

Flujo (rediseño 2026-09-21): 1) recolección GRATIS de titulares por país × lente
(src/oracle/sources.py) → 2) el modelo LEE los titulares (src/oracle/read.py, sin búsqueda
web) → 3) consejo de críticos → 4) VERIFICACIÓN con búsqueda web solo de las mejores
semillas → 5) agrupamiento de temas repetidos entre países. `--legacy-search` vuelve a la
minería con búsqueda web a ciegas (más cara, sin lista de fuentes).

Privacidad: el repo y los logs de Actions son PÚBLICOS. Este script nunca imprime
contenido de semillas ni lessons, solo conteos y costos. La materia prima interna
de Matías (GBrain) NO entra acá — solo fuentes públicas.

Uso:
  python -m scripts.oracle_run --dry-run              # agenda + costo estimado, sin API
  python -m scripts.oracle_run --tag test --max-pairs 6   # humo chico, no bloquea el mes real
  python -m scripts.oracle_run                        # corrida real del mes actual
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.oracle.matrix import (  # noqa: E402
    COUNTRIES, LENS_BY_KEY, SENALES_OFERTA, due_pairs, month_index,
)

PROMPTS = REPO / "prompts"
SEARCHES_PER_PAIR = 2            # solo modo --legacy-search
READ_MAX_TOKENS = 8000           # lectura de titulares: holgado por el razonamiento de Sonnet
VERIFY_TOP = int(os.environ.get("ORACLE_VERIFY_TOP") or 25)  # semillas del consejo a verificar con búsqueda web
VERIFY_MAX_SEARCHES = 2
VERIFY_MAX_TOKENS = 6000
MINING_MAX_TOKENS = 12000        # holgado: el razonamiento de Sonnet cuenta acá
COUNCIL_MAX_TOKENS = 16000
COUNCIL_CHUNK = 8                # semillas por llamada (el canario v2 truncó con 20)
VAULT_THRESHOLD = 6.0
MONTH_COST_CEILING = 9.0         # guardrail de la corrida completa
MAX_DIRECT_FALLBACK = 8
DEFAULT_MODEL = "claude-sonnet-5"
# Costo estimado por combinación con Batch y 2 búsquedas — medido en el canario v2.
EST_PAIR_COST = {"sonnet": 0.065, "haiku": 0.035}
# Estimación de la lectura de titulares (Batch, ~4k tokens de entrada + salida con razonamiento).
# MEDIDA en 5 corridas reales (2026-09-22/25): $0.011-0.016 por combinación (Sonnet, Batch).
EST_READ_PAIR_COST = {"sonnet": 0.013, "haiku": 0.005}
WEIGHTS = {"evidencia_necesidad": 0.30, "tamano_gravedad": 0.20, "por_que_ahora": 0.20,
           "hueco_vs_incumbentes": 0.20, "testeabilidad": 0.10}
SENALES_VALIDAS = {"queja", "brecha", "fuerza_externa", "oferta"}


MAX_FEEDBACK_PER_KIND = 5


def lens_feedback() -> dict[str, str]:
    """Bloque de feedback del fundador por lente, armado con sus veredictos reales
    (Vault). Afina QUÉ se busca en cada lente: más de lo que le interesó, menos de
    lo que descartó y por qué. Nunca se imprime (los logs de Actions son públicos)."""
    from dashboard.db import fetch_verdicts
    by_lens: dict[str, dict[str, list[str]]] = {}
    for v in fetch_verdicts():
        kind = "interes" if v["human_verdict"] in ("elegida", "guardada") else "descarte"
        bucket = by_lens.setdefault(v["lens"], {"interes": [], "descarte": []})
        if len(bucket[kind]) < MAX_FEEDBACK_PER_KIND:
            reason = f" — motivo: {v['human_reason']}" if v.get("human_reason") else ""
            bucket[kind].append(f"- ({v['country']}) {v['necesidad'][:110]}{reason}")
    out = {}
    for lens, b in by_lens.items():
        parts = []
        if b["interes"]:
            parts.append("Le INTERESÓ (buscá más de este tipo):\n" + "\n".join(b["interes"]))
        if b["descarte"]:
            parts.append("DESCARTÓ (evitá este tipo, salvo evidencia nueva):\n" + "\n".join(b["descarte"]))
        out[lens] = ("\nFeedback previo del fundador sobre ESTE lente — usalo para afinar qué buscás. "
                     "Los motivos reflejan sus intereses, no su falta de experiencia:\n" + "\n".join(parts))
    return out


def mining_user(cc: str, lens_key: str, feedback: str = "") -> str:
    name, _ = COUNTRIES[cc]
    lens = LENS_BY_KEY[lens_key]
    extra = ("\nPriorizá señales de tipo 'oferta' (qué se financia, lanza y crece): las quejas "
             "locales de este país son poco accesibles." if cc in SENALES_OFERTA else "")
    return (f"País: {name}\nLente: {lens.name}\nDefinición del lente: {lens.definition}{extra}\n"
            f"Buscá las necesidades más fuertes y recientes (últimos 12 meses). "
            f"Una sola URL por necesidad: la mejor fuente, completa.{feedback}")


def first_url(raw: str) -> str:
    for tok in re.split(r"\s+", (raw or "").strip()):
        tok = tok.strip("|;,/()")
        if tok.startswith("http"):
            return tok
    return ""


def dedupe_key(country: str, lens: str, necesidad: str) -> str:
    norm = re.sub(r"\W+", " ", necesidad.lower()).strip()[:100]
    return hashlib.sha1(f"{country}|{lens}|{norm}".encode()).hexdigest()


def url_states(urls: list[str]) -> dict[str, str]:
    """ok | bloqueada (inconclusa: el sitio bloquea IPs de cloud) | rota | sin_url."""
    import httpx
    from concurrent.futures import ThreadPoolExecutor

    def chk(u: str) -> tuple[str, str]:
        if not u:
            return u, "sin_url"
        try:
            r = httpx.get(u, timeout=10, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (scouting-agent oracle)"})
        except Exception:  # noqa: BLE001
            return u, "rota"
        if r.status_code < 400:
            return u, "ok"
        return u, "bloqueada" if r.status_code in (401, 403, 406, 429, 999) else "rota"

    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(chk, urls))


def mine(client, pairs, model: str, effort: str | None, month_key: str) -> tuple[list[dict], float, Counter]:
    from scripts.market_analysis import _parse_object
    from src.oracle.batch import direct_call, make_request, run_batch
    from src.pipeline.score import web_search_tool

    system = (PROMPTS / "oracle_mining.md").read_text(encoding="utf-8")
    tools = web_search_tool(SEARCHES_PER_PAIR)
    fb = lens_feedback()
    reqs = [make_request(f"{cc}-{lk}", model, system,
                         mining_user(cc, lk, fb.get(LENS_BY_KEY[lk].name, "")), MINING_MAX_TOKENS,
                         tools, effort) for cc, lk in pairs]
    res = run_batch(client, reqs, log_prefix="[oracle:minería]")

    stats: Counter = Counter()
    failed = [r for r in reqs if "error" in res.get(r["custom_id"], {"error": "faltante"})]
    for r in failed[:MAX_DIRECT_FALLBACK]:
        try:
            res[r["custom_id"]] = direct_call(client, r)
            stats["reintento_directo_ok"] += 1
        except Exception as e:  # noqa: BLE001
            res[r["custom_id"]] = {"error": type(e).__name__}
    cost = sum(v.get("cost", 0.0) for v in res.values())

    rows: list[dict] = []
    for cc, lk in pairs:
        r = res.get(f"{cc}-{lk}", {"error": "faltante"})
        if "error" in r:
            stats["pares_fallidos"] += 1
            continue
        if r.get("truncated"):
            stats["truncados"] += 1
        obj = _parse_object(r["text"]) or {}
        items = obj.get("necesidades", []) if isinstance(obj, dict) else []
        if not items:
            stats["sin_necesidades"] += 1
        country, lens_name = COUNTRIES[cc][0], LENS_BY_KEY[lk].name
        for it in items[:3]:
            nec = (it.get("necesidad") or "").strip()
            if not nec:
                continue
            tipo = (it.get("tipo_senal") or "").strip().lower()
            rows.append({
                "run_month": month_key, "country": country, "lens": lens_name,
                "tipo_senal": tipo if tipo in SENALES_VALIDAS else None,
                "necesidad": nec, "quien": it.get("quien"), "evidencia": it.get("evidencia"),
                "fuente_url": first_url(it.get("fuente_url", "")),
                "solucion_existente": it.get("solucion_existente"),
                "transferencia": it.get("transferencia_chile_latam"),
                "modelo": model, "dedupe_key": dedupe_key(country, lens_name, nec),
            })
    states = url_states(sorted({r["fuente_url"] for r in rows}))
    for r in rows:
        r["url_estado"] = states.get(r["fuente_url"], "sin_url")
    stats["semillas"] = len(rows)
    return rows, cost, stats


MAX_KNOWN_TOPICS = 20


def known_topics(vault_rows: list[dict]) -> dict[tuple[str, str], str]:
    """Bloque 'temas que YA están en el Vault' por (país, lente), para que la lectura de este mes no
    vuelva a extraer (y a pagar consejo y verificación por) lo mismo con otras palabras. El chequeo
    exacto de dedupe_key solo ve textos idénticos; esto evita el duplicado antes de generarlo."""
    by: dict[tuple[str, str], list[str]] = {}
    for r in sorted(vault_rows, key=lambda r: r.get("id") or 0, reverse=True):
        by.setdefault((r["country"], r["lens"]), []).append(str(r.get("necesidad") or "")[:110])
    return {k: ("\n\nTemas que YA están en el Vault para este país y lente (NO los repitas: devolvé solo "
                "señales NUEVAS, o una novedad MATERIAL sobre alguno de ellos y en ese caso decilo en "
                "`necesidad`):\n" + "\n".join(f"- {t}" for t in v[:MAX_KNOWN_TOPICS]))
            for k, v in by.items() if v}


def saturated_topics(vault_rows: list[dict], min_n: int = 3, top: int = 8) -> dict[str, str]:
    """Por lente: temas que YA tienen >= min_n semillas (en cualquier país). Sin esto, cada país vuelve a
    extraer el mismo tema obvio (p. ej. contabilidad de pymes en AI-native) y el Vault se llena de
    semillas casi iguales. El modelo recibe la lista y prioriza otros huecos."""
    by: dict[str, dict[int, dict]] = {}
    for r in vault_rows:
        cid = r.get("cluster_id")
        if cid is None:
            continue
        d = by.setdefault(r["lens"], {}).setdefault(int(cid), {"label": r.get("cluster_label") or "", "n": 0})
        d["n"] += 1
    out = {}
    for lens, clusters in by.items():
        big = sorted((v for v in clusters.values() if v["n"] >= min_n and v["label"]), key=lambda v: -v["n"])[:top]
        if big:
            out[lens] = ("\n\nTemas YA MUY REPETIDOS en el Vault para este lente (en otros países): no los "
                         "vuelvas a extraer salvo que un titular muestre un ángulo local claramente distinto; "
                         "preferí otras verticales u otros huecos:\n"
                         + "\n".join(f"- {v['label']} ({v['n']} semillas)" for v in big))
    return out


def read_mine(client, pairs, model: str, effort: str | None, month_key: str) -> tuple[list[dict], float, Counter]:
    """Lee titulares recolectados gratis (sin búsqueda web) y extrae las mejores señales."""
    import httpx
    from scripts.market_analysis import _parse_object
    from src.oracle import read, sources
    from src.oracle.batch import direct_call, make_request, run_batch

    from dashboard.db import fetch_vault

    system = (PROMPTS / "oracle_read.md").read_text(encoding="utf-8")
    fb = lens_feedback()
    vault_rows = fetch_vault()
    known = known_topics(vault_rows)
    saturated = saturated_topics(vault_rows)
    stats: Counter = Counter()
    reqs, ranked_by_id = [], {}
    cache: dict = {}
    with httpx.Client(headers=sources._UA, follow_redirects=True) as http:
        for cc, lk in pairs:
            ranked = read.rank(read.gather(cc, lk, http, cache), cc, lk)
            if len(ranked) < 5:
                stats["sin_titulares"] += 1
                continue
            ranked_by_id[f"{cc}-{lk}"] = ranked
            name, _ = COUNTRIES[cc]
            lens = LENS_BY_KEY[lk]
            extra = ("\nPriorizá señales de tipo 'oferta': las quejas locales de este país son poco "
                     "accesibles." if cc in SENALES_OFERTA else "")
            user = (f"País: {name}\nLente: {lens.name}\nDefinición del lente: {lens.definition}{extra}\n\n"
                    f"Titulares ({len(ranked)}):\n{read.render(ranked)}\n\n"
                    f"Extraé las señales más específicas y accionables.{fb.get(lens.name, '')}"
                    f"{known.get((name, lens.name), '')}{saturated.get(lens.name, '')}")
            reqs.append(make_request(f"{cc}-{lk}", model, system, user, READ_MAX_TOKENS, None, effort))
    stats["titulares_leidos"] = sum(len(v) for v in ranked_by_id.values())
    res = run_batch(client, reqs, log_prefix="[oracle:lectura]")
    for r in [r for r in reqs if "error" in res.get(r["custom_id"], {"error": "faltante"})][:MAX_DIRECT_FALLBACK]:
        try:
            res[r["custom_id"]] = direct_call(client, r)
            stats["reintento_directo_ok"] += 1
        except Exception as e:  # noqa: BLE001
            res[r["custom_id"]] = {"error": type(e).__name__}
    cost = sum(v.get("cost", 0.0) for v in res.values())

    rows: list[dict] = []
    for cc, lk in pairs:
        cid = f"{cc}-{lk}"
        if cid not in ranked_by_id:
            continue
        r = res.get(cid, {"error": "faltante"})
        if "error" in r:
            stats["pares_fallidos"] += 1
            continue
        if r.get("truncated"):
            stats["truncados"] += 1
        obj = _parse_object(r["text"]) or {}
        items = obj.get("necesidades", []) if isinstance(obj, dict) else []
        if not items:
            stats["sin_necesidades"] += 1
        country, lens_name = COUNTRIES[cc][0], LENS_BY_KEY[lk].name
        ranked = ranked_by_id[cid]
        for it in items[:3]:
            nec = (it.get("necesidad") or "").strip()
            if not nec:
                continue
            cited = [n for n in (_as_int(x) for x in (it.get("items") or [])) if n and 1 <= n <= len(ranked)]
            tipo = (it.get("tipo_senal") or "").strip().lower()
            rows.append({
                "run_month": month_key, "country": country, "lens": lens_name,
                "tipo_senal": tipo if tipo in SENALES_VALIDAS else None,
                "necesidad": nec, "quien": it.get("quien"), "evidencia": it.get("evidencia"),
                "fuente_url": ranked[cited[0] - 1]["url"] if cited else "",
                # Solo titular de prensa: se verifica con búsqueda si pasa el consejo.
                "url_estado": "titular" if cited else "sin_url",
                "solucion_existente": it.get("solucion_existente"),
                "transferencia": it.get("transferencia_chile_latam"),
                "modelo": model, "dedupe_key": dedupe_key(country, lens_name, nec),
            })
    stats["semillas"] = len(rows)
    return rows, cost, stats


def pick_to_verify(candidates: list[dict], vault_rows: list[dict], stats: Counter) -> list[dict]:
    """Cada verificación cuesta ~$0.045 (búsqueda web), la etapa más cara por semilla. Se verifica
    UNA semilla por tema (la de mejor score) y ninguna si el tema ya tiene una semilla verificada o con
    veredicto humano — de un mes anterior o de otro país. Sin cluster asignado, cada semilla es un tema."""
    done = {}
    for r in vault_rows:
        cid = r.get("cluster_id")
        if cid is not None and (r.get("url_estado") in ("verificada", "parcial", "no_confirmada")
                                or r.get("human_verdict")):
            done.setdefault(cid, set()).add(r["id"])
    picked, taken = [], set()
    for x in sorted(candidates, key=lambda x: x.get("score") or 0, reverse=True):
        cid = x.get("cluster_id")
        if cid is not None:
            if done.get(cid, set()) - {x["id"]}:
                stats["omitidas_tema_ya_verificado"] += 1
                continue
            if cid in taken:
                stats["omitidas_mismo_tema_en_esta_corrida"] += 1
                continue
            taken.add(cid)
        picked.append(x)
    return picked


def verify(client, model: str, effort: str | None, month_key: str) -> tuple[float, Counter]:
    """Verifica con búsqueda web REAL las mejores semillas del consejo del mes (basadas en titulares)."""
    from dashboard.db import fetch_vault, fetch_vault_status, update_vault
    from scripts.market_analysis import _parse_object
    from src.oracle.batch import direct_call, make_request, run_batch
    from src.pipeline.score import web_search_tool

    stats: Counter = Counter()
    seeds = [x for x in fetch_vault_status("en_vault")
             if x.get("run_month") == month_key and x.get("url_estado") == "titular"]
    seeds = pick_to_verify(seeds, fetch_vault(), stats)[:VERIFY_TOP]
    if not seeds:
        return 0.0, stats
    system = (PROMPTS / "oracle_verify.md").read_text(encoding="utf-8")
    tools = web_search_tool(VERIFY_MAX_SEARCHES)
    reqs = [make_request(f"v{x['id']}", model, system,
                         f"País: {x['country']} · Lente: {x['lens']}\nNecesidad: {x['necesidad']}\n"
                         f"Quién: {x.get('quien')}\nEvidencia detectada en titulares: {x.get('evidencia')}\n"
                         f"Solución existente según los titulares: {x.get('solucion_existente')}",
                         VERIFY_MAX_TOKENS, tools, effort) for x in seeds]
    res = run_batch(client, reqs, log_prefix="[oracle:verificación]")
    for r in [r for r in reqs if "error" in res.get(r["custom_id"], {"error": "faltante"})][:MAX_DIRECT_FALLBACK]:
        try:
            res[r["custom_id"]] = direct_call(client, r)
        except Exception as e:  # noqa: BLE001
            res[r["custom_id"]] = {"error": type(e).__name__}
    cost = sum(v.get("cost", 0.0) for v in res.values())

    urls = [_first for x in seeds
            if (_first := first_url((_parse_object(res.get(f"v{x['id']}", {}).get("text", "")) or {})
                                    .get("fuente_url", "")))]
    states = url_states(sorted(set(urls))) if urls else {}
    for x in seeds:
        r = res.get(f"v{x['id']}", {"error": "faltante"})
        if "error" in r:
            stats["fallidas"] += 1
            continue
        obj = _parse_object(r["text"]) or {}
        verdict = (obj.get("veredicto") or "").strip().lower()
        if verdict not in ("confirmada", "parcial", "no_confirmada"):
            stats["ilegibles"] += 1
            continue
        stats[verdict] += 1
        url = first_url(obj.get("fuente_url", ""))
        fields: dict = {"url_estado": {"confirmada": "verificada", "parcial": "parcial",
                                      "no_confirmada": "no_confirmada"}[verdict]}
        if obj.get("evidencia"):
            fields["evidencia"] = obj["evidencia"]
        if url:
            fields["fuente_url"] = url
            if states.get(url) == "rota":
                fields["url_estado"] = fields["url_estado"] if verdict != "confirmada" else "parcial"
        if obj.get("solucion_existente"):
            fields["solucion_existente"] = obj["solucion_existente"]
        if verdict == "no_confirmada":
            fields["status"] = "descartada_consejo"
            fields["objeciones"] = ((x.get("objeciones") or "") + " | Verificación: no se pudo confirmar"
                                    + (f" — {obj['nota']}" if obj.get("nota") else "")).strip(" |")
        elif obj.get("nota"):
            fields["objeciones"] = ((x.get("objeciones") or "") + f" | Verificación: {obj['nota']}").strip(" |")
        update_vault(x["id"], **fields)
    return cost, stats


def _as_float(x) -> float:
    """Puntajes del modelo: tolera '7', '7/10', None — un formato raro no debe tumbar la corrida."""
    try:
        return float(str(x).split("/")[0].strip())
    except (TypeError, ValueError):
        return 0.0


def _as_int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def lessons_block() -> str:
    from dashboard.db import fetch_lessons
    ls = fetch_lessons(25)
    if not ls:
        return "Veredictos previos del fundador: todavía no hay ninguno."
    lines = [f"- [{l['verdict'].upper()}] {(l.get('seed_snapshot') or '')[:140]} — motivo: "
             f"{l.get('reason') or 'sin motivo'}" for l in ls]
    return ("Veredictos previos del fundador, el más reciente primero. Usalos para calibrar su "
            "GUSTO e intereses; NO para penalizar falta de experiencia (eso sigue prohibido):\n"
            + "\n".join(lines))


def council(client, model: str, effort: str | None) -> tuple[int, float, Counter]:
    from dashboard.db import fetch_vault_status, update_vault
    from scripts.market_analysis import _founder_context, _parse_object
    from src.oracle.batch import direct_call, make_request, run_batch

    seeds = fetch_vault_status("nueva")
    stats: Counter = Counter()
    if not seeds:
        return 0, 0.0, stats
    system = ((PROMPTS / "oracle_council.md").read_text(encoding="utf-8")
              .replace("{FOUNDER_CONTEXT}", _founder_context())
              .replace("{LESSONS}", lessons_block()))
    chunks = [seeds[i:i + COUNCIL_CHUNK] for i in range(0, len(seeds), COUNCIL_CHUNK)]

    def brief(s: dict) -> str:
        url = {"titular": "titular de prensa, sin el texto completo — puntuá el POTENCIAL de la señal; "
                          "si pasa el umbral se verifica después con búsqueda web",
               "ok": "resuelve (ok)", "bloqueada": "no verificable (el sitio bloquea)",
               "rota": "NO resuelve — tratá la evidencia como NO verificable",
               "sin_url": "sin URL — tratá la evidencia como NO verificable"}.get(s.get("url_estado"), "?")
        return (f"[{s['id']}] ({s['country']} × {s['lens']}) NECESIDAD: {s['necesidad']}\n"
                f"Quién: {s.get('quien')}\nTipo de señal: {s.get('tipo_senal')}\n"
                f"Evidencia: {s.get('evidencia')}\nFuente citada: {url}\n"
                f"Solución existente: {s.get('solucion_existente')}\n"
                f"Transferencia a Chile/LatAm: {s.get('transferencia')}")

    reqs = [make_request(f"c{i}", model, system, "\n\n".join(brief(s) for s in ch),
                         COUNCIL_MAX_TOKENS, None, effort) for i, ch in enumerate(chunks)]
    res = run_batch(client, reqs, log_prefix="[oracle:consejo]")
    for r in [r for r in reqs if "error" in res.get(r["custom_id"], {"error": "x"})][:4]:
        try:
            res[r["custom_id"]] = direct_call(client, r)
        except Exception as e:  # noqa: BLE001
            res[r["custom_id"]] = {"error": type(e).__name__}
    cost = sum(v.get("cost", 0.0) for v in res.values())

    by_id = {s["id"]: s for s in seeds}
    for i, ch in enumerate(chunks):
        r = res.get(f"c{i}", {"error": "faltante"})
        if "error" in r:
            stats["chunks_fallidos"] += 1
            continue
        if r.get("truncated"):
            stats["chunks_truncados"] += 1
        obj = _parse_object(r["text"]) or {}
        for v in obj.get("semillas", []) if isinstance(obj, dict) else []:
            sid = _as_int(v.get("id"))
            if sid not in by_id:
                continue
            num = lambda k: _as_float(v.get(k))  # noqa: E731
            score = sum(num(k) * w for k, w in WEIGHTS.items()) + min(max(num("bonus_fit"), 0.0), 1.0)
            update_vault(
                sid, s_evidencia=num("evidencia_necesidad"), s_tamano=num("tamano_gravedad"),
                s_ahora=num("por_que_ahora"), s_hueco=num("hueco_vs_incumbentes"),
                s_testeabilidad=num("testeabilidad"), bonus_fit=min(max(num("bonus_fit"), 0.0), 1.0),
                score=round(score, 2), objeciones=" | ".join(v.get("objeciones") or []),
                veredicto_consejo=v.get("veredicto"),
                status="en_vault" if score >= VAULT_THRESHOLD else "descartada_consejo",
            )
            stats["puntuadas"] += 1
            stats["en_vault" if score >= VAULT_THRESHOLD else "descartadas"] += 1
    return stats["puntuadas"], cost, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="agenda y costo estimado, sin API ni DB")
    ap.add_argument("--month", help="YYYY-MM (por defecto el mes actual, UTC)")
    ap.add_argument("--tag", default="", help="sufijo del run (ej: test) — no bloquea el mes real")
    ap.add_argument("--max-pairs", type=int, default=0, help="limita combinaciones (pruebas)")
    ap.add_argument("--force", action="store_true", help="correr aunque el mes ya esté 'listo'")
    ap.add_argument("--legacy-search", action="store_true",
                    help="minería con búsqueda web a ciegas (diseño anterior, más cara)")
    ap.add_argument("--no-verify", action="store_true", help="omitir la verificación con búsqueda web")
    ap.add_argument("--pairs", default="", help="lista PAÍS-lente a correr (ej: CL-tradicional,US-logistica); "
                                                "reemplaza la agenda del mes")
    ap.add_argument("--cluster-only", action="store_true",
                    help="solo agrupar semillas repetidas entre países (sin minería ni consejo)")
    args = ap.parse_args()

    if args.cluster_only:
        from anthropic import Anthropic
        from src import config
        from src.oracle.cluster import cluster_seeds
        cost, kstats = cluster_seeds(Anthropic(api_key=config.ANTHROPIC_API_KEY),
                                     os.environ.get("SCOUTING_MODEL_CLUSTER", "claude-haiku-4-5"))
        print(f"[oracle:cluster] {dict(kstats)} costo=${cost:.4f}")
        return

    now = datetime.now(timezone.utc)
    y, m = (int(x) for x in args.month.split("-")) if args.month else (now.year, now.month)
    month_key = f"{y}-{m:02d}" + (f"-{args.tag}" if args.tag else "")
    mining_model = os.environ.get("SCOUTING_MODEL_MINING", DEFAULT_MODEL)
    council_model = os.environ.get("SCOUTING_MODEL_COUNCIL", DEFAULT_MODEL)
    effort = os.environ.get("ORACLE_EFFORT", "medium") or None

    pairs = sorted(due_pairs(month_index(y, m)))
    if args.pairs:
        wanted = {tuple(p.split("-", 1)) for p in args.pairs.split(",") if "-" in p}
        pairs = sorted(p for p in ((c, lk) for c in COUNTRIES for lk in LENS_BY_KEY) if p in wanted)
    elif args.max_pairs:
        # Muestra REPARTIDA (mezcla fija), no las primeras N por orden alfabético: la
        # corrida de humo del 2026-09-19 tomó las primeras 6 y fueron todas Argentina.
        random.Random(7).shuffle(pairs)
        pairs = sorted(pairs[: args.max_pairs])
    kind = "haiku" if "haiku" in mining_model else "sonnet"
    est = len(pairs) * (EST_PAIR_COST if args.legacy_search else EST_READ_PAIR_COST)[kind]
    print(f"[oracle] {month_key}: {len(pairs)} combinaciones — "
          f"{'minería con búsqueda web' if args.legacy_search else 'lectura de titulares'} {mining_model}, "
          f"consejo {council_model}, effort={effort}, costo estimado minería ≈ ${est:.2f} "
          f"(+ consejo ≈ ${len(pairs) * 0.01:.2f})")
    if args.dry_run:
        print("[oracle] por país:", dict(Counter(COUNTRIES[c][0] for c, _ in pairs)))
        print("[oracle] por lente:", dict(Counter(LENS_BY_KEY[l].name for _, l in pairs)))
        return
    if est > MONTH_COST_CEILING:
        raise SystemExit(f"[oracle] estimado ${est:.2f} > tope ${MONTH_COST_CEILING} — abortado")

    from anthropic import Anthropic
    from dashboard.db import get_oracle_run, insert_vault_seeds, save_oracle_run
    from src import config
    from src.oracle.batch import effort_supported

    run = get_oracle_run(month_key)
    if run and run["status"] == "listo" and not args.force:
        print(f"[oracle] {month_key} ya está 'listo' (costo ${run.get('cost_usd')}) — nada que hacer")
        return
    save_oracle_run(month_key, status="corriendo", pairs=len(pairs),
                    started_at=now.isoformat())
    try:
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        if effort and not (effort_supported(client, mining_model, effort)
                           and effort_supported(client, council_model, effort)):
            effort = None
        miner = mine if args.legacy_search else read_mine
        rows, mining_cost, mstats = miner(client, pairs, mining_model, effort, month_key)
        insert_vault_seeds(rows)
        print(f"[oracle] minería: {dict(mstats)} costo=${mining_cost:.4f}")
        # Agrupar temas repetidos ANTES del consejo y la verificación: la verificación usa los
        # grupos para no pagar dos veces el mismo tema. Un fallo acá no debe perder la corrida.
        cluster_cost = 0.0
        try:
            from src.oracle.cluster import cluster_seeds
            cluster_cost, kstats = cluster_seeds(
                client, os.environ.get("SCOUTING_MODEL_CLUSTER", "claude-haiku-4-5"))
            print(f"[oracle] temas: {dict(kstats)} costo=${cluster_cost:.4f}")
        except Exception as e:  # noqa: BLE001
            print(f"[oracle] agrupamiento omitido ({type(e).__name__}) — ¿falta la migración de columnas?")
        council_cost = 0.0
        cstats: Counter = Counter()
        if mining_cost < MONTH_COST_CEILING:
            _, council_cost, cstats = council(client, council_model, effort)
        else:
            print("[oracle] GUARDRAIL: minería pasó el tope — se omite el consejo")
        verify_cost = 0.0
        vstats: Counter = Counter()
        if (not args.legacy_search and not args.no_verify and VERIFY_TOP > 0
                and mining_cost + council_cost < MONTH_COST_CEILING):
            verify_cost, vstats = verify(client, council_model, effort, month_key)
            print(f"[oracle] verificación: {dict(vstats)} costo=${verify_cost:.4f}")
        total = mining_cost + council_cost + verify_cost + cluster_cost
        print(f"[oracle] consejo: {dict(cstats)} costo=${council_cost:.4f}")
        print(f"[oracle] === COSTO TOTAL {month_key}: ${total:.4f} ===")
        save_oracle_run(month_key, status="listo", seeds=len(rows), cost_usd=round(total, 4),
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        note=f"minería={dict(mstats)} consejo={dict(cstats)} verificación={dict(vstats)}"[:500])
    except Exception as e:  # noqa: BLE001
        save_oracle_run(month_key, status="error", note=f"{type(e).__name__}: {str(e)[:300]}",
                        finished_at=datetime.now(timezone.utc).isoformat())
        raise


if __name__ == "__main__":
    main()
