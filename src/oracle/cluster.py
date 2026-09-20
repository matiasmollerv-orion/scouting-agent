"""Agrupa semillas que expresan la MISMA necesidad de fondo, aunque salgan de países,
lentes o fuentes distintos. Que un tema aparezca en varios países es señal en sí misma,
y evita profundizar (y pagar) dos veces lo mismo.

Incremental: cada corrida asigna solo las semillas sin cluster, contra los clusters ya
existentes. Usa Haiku (barato: ~40 semillas por llamada) — agrupar es clasificar, no
razonar. Ante la duda NO agrupa: un falso positivo esconde una idea distinta.

Privacidad: solo imprime conteos (logs de Actions públicos).
"""
from __future__ import annotations

from collections import Counter

CHUNK = 40
MAX_CLUSTERS_IN_PROMPT = 250
CLUSTER_MAX_TOKENS = 4000
DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM = """Agrupás "semillas" de necesidad de negocio que son la MISMA necesidad de fondo: mismo
problema y mismo tipo de actor, aunque cambien el país, la redacción o la fuente.

Reglas:
- Agrupá SOLO si resolver una resolvería la otra. Compartir el lente o el tema amplio ("fintech",
  "IA en empresas") NO alcanza.
- Ante la duda, NO agrupes: es peor esconder una idea distinta que dejar dos separadas.
- Cada semilla va a un cluster existente (por su id) o abre uno nuevo. Las semillas de este mismo
  pedido que sean el mismo tema nuevo comparten EXACTAMENTE la misma etiqueta.
- La etiqueta nombra la necesidad de fondo en máx. 12 palabras, sin país ni nombres de empresas.

Respondé EXCLUSIVAMENTE JSON, sin texto fuera de él:
{"asignaciones": [{"id": 123, "cluster_id": 17}, {"id": 124, "nuevo": "etiqueta corta"}]}
Incluí TODAS las semillas del pedido."""


def plan_assignments(unassigned: list[dict], clusters: dict[int, dict],
                     assignments: list[dict], next_id: int) -> tuple[list[tuple[int, int, str]], int, Counter]:
    """Lógica pura (testeable sin API): traduce la respuesta del modelo a
    [(id_semilla, cluster_id, etiqueta)]. Devuelve también el próximo id libre.

    Una semilla que el modelo omitió o cuyo cluster_id no existe queda SIN asignar y se
    reintenta en la próxima corrida — nunca se inventa una asignación."""
    valid_ids = {s["id"] for s in unassigned}
    stats: Counter = Counter()
    labels_new: dict[str, int] = {}
    plan: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    for a in assignments:
        try:
            sid = int(a.get("id"))
        except (TypeError, ValueError):
            stats["id_invalido"] += 1
            continue
        if sid not in valid_ids or sid in seen:
            stats["id_desconocido_o_repetido"] += 1
            continue
        seen.add(sid)
        cid = a.get("cluster_id")
        if cid is not None:
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                cid = None
        if cid is not None and cid in clusters:
            plan.append((sid, cid, clusters[cid]["label"]))
            stats["a_cluster_existente"] += 1
            continue
        label = str(a.get("nuevo") or "").strip()[:120]
        if not label:
            stats["sin_asignar"] += 1
            continue
        if label not in labels_new:
            labels_new[label] = next_id
            clusters[next_id] = {"label": label, "n": 0, "countries": set()}
            next_id += 1
        plan.append((sid, labels_new[label], label))
        stats["a_cluster_nuevo"] += 1
    stats["omitidas"] = len(valid_ids - seen)
    return plan, next_id, stats


def cluster_seeds(client, model: str = DEFAULT_MODEL) -> tuple[float, Counter]:
    """Asigna cluster a las semillas que aún no tienen. Devuelve (costo, conteos)."""
    from dashboard.db import fetch_vault, update_vault
    from scripts.market_analysis import _parse_object
    from src.oracle.batch import direct_call, make_request

    rows = fetch_vault()
    unassigned = [r for r in rows if r.get("cluster_id") is None]
    stats: Counter = Counter()
    if not unassigned:
        return 0.0, stats

    clusters: dict[int, dict] = {}
    for r in rows:
        cid = r.get("cluster_id")
        if cid is None:
            continue
        info = clusters.setdefault(int(cid), {"label": r.get("cluster_label") or "", "n": 0, "countries": set()})
        info["n"] += 1
        info["countries"].add(r["country"])
    next_id = max(clusters, default=0) + 1
    cost = 0.0

    for i in range(0, len(unassigned), CHUNK):
        chunk = unassigned[i:i + CHUNK]
        # los clusters más grandes primero: son los que más probablemente reciban semillas nuevas
        top = sorted(clusters.items(), key=lambda kv: -kv[1]["n"])[:MAX_CLUSTERS_IN_PROMPT]
        existing = "\n".join(f"[{cid}] {info['label']} ({info['n']} semillas: "
                             f"{', '.join(sorted(info['countries']))})" for cid, info in top) or "(ninguno todavía)"
        seeds = "\n".join(f"[{s['id']}] ({s['country']} · {s['lens']}) {s['necesidad'][:170]}" for s in chunk)
        req = make_request(f"k{i}", model, SYSTEM,
                           f"Clusters existentes:\n{existing}\n\nSemillas a asignar:\n{seeds}",
                           CLUSTER_MAX_TOKENS)
        try:
            res = direct_call(client, req)
        except Exception as e:  # noqa: BLE001 — un chunk fallido no debe tumbar la corrida
            stats["chunks_fallidos"] += 1
            print(f"[oracle:cluster] chunk {i // CHUNK} falló ({type(e).__name__})")
            continue
        cost += res.get("cost", 0.0)
        obj = _parse_object(res["text"]) or {}
        plan, next_id, s2 = plan_assignments(chunk, clusters, obj.get("asignaciones", []) if isinstance(obj, dict) else [], next_id)
        stats.update(s2)
        by_id = {s["id"]: s for s in chunk}
        for sid, cid, label in plan:
            update_vault(sid, cluster_id=cid, cluster_label=label)
            info = clusters.setdefault(cid, {"label": label, "n": 0, "countries": set()})
            info["n"] += 1
            info["countries"].add(by_id[sid]["country"])
    multi = sum(1 for c in clusters.values() if len(c["countries"]) >= 2)
    stats["clusters_en_2_o_mas_paises"] = multi
    stats["clusters_total"] = len(clusters)
    return cost, stats
