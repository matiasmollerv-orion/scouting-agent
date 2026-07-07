from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..models import Item

# Pool de candidatos acumulados por el job diario de recolección (sin LLM).
# El sábado, el run semanal lo une con el fetch fresco y lo resetea.
POOL_FILE = Path(__file__).resolve().parents[2] / "data" / "pool.json"
MAX_AGE_DAYS = 10  # margen sobre la semana por si un run falla


def load_pool_items() -> list[Item]:
    """Items acumulados durante la semana, como objetos Item."""
    items: list[Item] = []
    for d in _load().values():
        try:
            items.append(Item.model_validate({k: v for k, v in d.items() if k != "added_at"}))
        except Exception as e:  # noqa: BLE001 — un item corrupto no tumba el run
            print(f"[pool] item ilegible, omitido: {e}")
    return items


def merge_into_pool(items: list[Item]) -> tuple[int, int]:
    """Agrega items nuevos al pool (dedup por URL) y poda los viejos.

    Retorna (nuevos_agregados, tamaño_pool).
    """
    pool = _load()
    now = datetime.now(timezone.utc)
    added = 0
    for it in items:
        key = it.dedup_key()
        if key in pool:
            # Conserva la fecha de entrada original; actualiza si sube engagement.
            if it.engagement > pool[key].get("engagement", 0):
                added_at = pool[key]["added_at"]
                pool[key] = it.model_dump(mode="json")
                pool[key]["added_at"] = added_at
        else:
            pool[key] = it.model_dump(mode="json")
            pool[key]["added_at"] = now.isoformat()
            added += 1

    cutoff = now.timestamp() - MAX_AGE_DAYS * 86400
    pool = {
        k: v for k, v in pool.items()
        if datetime.fromisoformat(v["added_at"]).timestamp() >= cutoff
    }
    _save(pool)
    return added, len(pool)


def reset_pool() -> None:
    """Vacía el pool tras un scoring exitoso (los items ya quedaron en seen_urls)."""
    _save({})


def _load() -> dict[str, dict]:
    if not POOL_FILE.exists():
        return {}
    try:
        return json.loads(POOL_FILE.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[pool] archivo ilegible, se parte de cero: {e}")
        return {}


def _save(pool: dict[str, dict]) -> None:
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
