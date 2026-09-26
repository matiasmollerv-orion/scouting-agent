#!/usr/bin/env python3
"""Prueba OFFLINE ($0) de la lectura y la verificación del Oracle.

Recolecta titulares reales (RSS público) pero reemplaza el Batch de Anthropic y Supabase por
falsos que responden como respondería el modelo. Valida: armado del prompt, filtrado, parseo,
citas por número -> URL, estados de URL, y los cambios que la verificación escribe al Vault.

Uso: python tests/oracle_offline.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import scripts.oracle_run as run  # noqa: E402
import src.oracle.batch as batch  # noqa: E402

SEEN: dict = {}
UPDATES: dict[int, dict] = {}


def fake_run_batch(client, reqs, log_prefix="", **_):
    out = {}
    for r in reqs:
        cid, user = r["custom_id"], r["params"]["messages"][0]["content"]
        SEEN[cid] = user
        if cid.startswith("v"):  # verificación: alterna veredictos
            n = int(cid[1:])
            v = ["confirmada", "parcial", "no_confirmada", "basura"][n % 4]
            out[cid] = {"text": json.dumps({"veredicto": v, "evidencia": f"hecho verificado {n} (fuente: X, 2026)",
                                            "fuente_url": "https://example.com/nota", "solucion_existente": "nadie en CL",
                                            "nota": "sin cifra de facturación"}), "cost": 0.05, "truncated": False}
        else:  # lectura
            out[cid] = {"text": json.dumps({"necesidades": [
                {"necesidad": f"Necesidad A de {cid}", "quien": "pymes", "tipo_senal": "oferta", "evidencia": "titulares (fuente: Medio)",
                 "items": [1, 3, 999], "solucion_existente": "no aparece", "transferencia_chile_latam": "adaptar"},
                {"necesidad": f"Necesidad B de {cid}", "quien": "hogares", "tipo_senal": "rara", "evidencia": "x", "items": [],
                 "solucion_existente": "", "transferencia_chile_latam": ""}]}), "cost": 0.03, "truncated": False}
    return out


batch.run_batch = fake_run_batch
batch.direct_call = lambda c, r: {"error": "no debería llamarse"}
run.lens_feedback = lambda: {}
import dashboard.db as _db  # noqa: E402
_db.fetch_vault = lambda: [{"id": 1, "country": "Chile", "lens": "Negocios tradicionales reinventados",
                            "necesidad": "Tema ya conocido de prueba"}] + [
    {"id": 100 + i, "country": "Brasil", "lens": "Logística, bodegaje y fulfillment", "necesidad": "x",
     "cluster_id": 7, "cluster_label": "Tema saturado de prueba"} for i in range(3)] + [
    {"id": 200, "country": "Brasil", "lens": "Logística, bodegaje y fulfillment", "necesidad": "y",
     "cluster_id": 8, "cluster_label": "Tema con una sola semilla"}]
run.url_states = lambda urls: {u: "ok" for u in urls}

pairs = [("CL", "tradicional"), ("US", "logistica")]
rows, cost, stats = run.read_mine(None, pairs, "claude-sonnet-5", None, "2026-09-test")
print("stats:", dict(stats), "costo:", round(cost, 3))
assert len(rows) == 4, rows
assert all(r["fuente_url"].startswith("http") for r in rows[::2]), "la cita [1] debe traer la URL del titular 1"
assert rows[0]["url_estado"] == "titular" and rows[1]["url_estado"] == "sin_url"
assert rows[1]["tipo_senal"] is None, "un tipo de señal inválido no debe colarse"
assert rows[0]["country"] == "Chile" and rows[0]["lens"] == "Negocios tradicionales reinventados"
assert "Tema ya conocido de prueba" in SEEN["CL-tradicional"], "el tema ya en el Vault debe ir en el prompt"
assert "Tema saturado de prueba (3 semillas)" in SEEN["US-logistica"], "los temas saturados del lente van a todos los países"
assert "Tema con una sola semilla" not in SEEN["US-logistica"], "solo temas con >= 3 semillas"
assert "Temas que YA están" not in SEEN["US-logistica"], "solo se listan los temas del MISMO país y lente"
for cid, user in SEEN.items():
    n = user.count("\n[")
    print(f"prompt {cid}: {len(user)} caracteres (≈{len(user)//4} tokens), {n} titulares numerados")
    assert 30 <= n <= 90, "cantidad de titulares fuera de rango"

# verificación
db = _db
seeds = [{"id": i, "run_month": "2026-09-test", "url_estado": "titular", "score": 9 - i, "country": "Chile",
          "lens": "X", "necesidad": "n", "quien": "q", "evidencia": "e", "solucion_existente": "s", "objeciones": "obj"}
         for i in range(4)]
db.fetch_vault_status = lambda s: seeds
db.update_vault = lambda i, **f: UPDATES.__setitem__(i, f)
vcost, vstats = run.verify(None, "claude-sonnet-5", None, "2026-09-test")
print("verificación:", dict(vstats), "costo:", round(vcost, 3))
assert UPDATES[0]["url_estado"] == "verificada" and UPDATES[0]["fuente_url"] == "https://example.com/nota"
assert UPDATES[1]["url_estado"] == "parcial"
assert UPDATES[2]["url_estado"] == "no_confirmada" and UPDATES[2]["status"] == "descartada_consejo"
assert "Verificación" in UPDATES[2]["objeciones"] and 3 not in UPDATES, "una respuesta ilegible no debe escribir nada"
assert vstats["ilegibles"] == 1

# un solo semilla por tema y ningún tema ya verificado/decidido
from collections import Counter  # noqa: E402
st = Counter()
cand = [{"id": 10, "score": 7.0, "cluster_id": 1}, {"id": 11, "score": 6.5, "cluster_id": 1},
        {"id": 12, "score": 6.8, "cluster_id": 2}, {"id": 13, "score": 6.2, "cluster_id": None},
        {"id": 14, "score": 6.1, "cluster_id": 3}]
vault = [{"id": 99, "cluster_id": 2, "url_estado": "verificada"},          # tema 2 ya verificado antes
         {"id": 98, "cluster_id": 3, "url_estado": "titular", "human_verdict": "descartada"}]  # tema 3 ya decidido
got = [x["id"] for x in run.pick_to_verify(cand, vault, st)]
assert got == [10, 13], got
assert st["omitidas_tema_ya_verificado"] == 2 and st["omitidas_mismo_tema_en_esta_corrida"] == 1, dict(st)
# a igual puntaje se prefiere Chile > México > resto de LatAm > otros; un mejor puntaje siempre gana
tie = [{"id": 20, "score": 7.3, "cluster_id": 5, "country": "Estados Unidos"},
       {"id": 21, "score": 7.3, "cluster_id": 5, "country": "Chile"},
       {"id": 22, "score": 7.3, "cluster_id": 6, "country": "México"},
       {"id": 23, "score": 7.3, "cluster_id": 6, "country": "España"},
       {"id": 24, "score": 7.4, "cluster_id": 7, "country": "Reino Unido"}]
got = [x["id"] for x in run.pick_to_verify(tie, [], Counter())]
assert got == [24, 21, 22], got   # 7.4 primero; en cada tema de 7.3 gana el latinoamericano
print("=== OK: lectura y verificación validadas offline ($0) ===")
