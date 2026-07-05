from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..models import RawItem
from .base import Source

# API comunitaria (yc-oss/api): JSON estático en GitHub Pages con todas las
# empresas de YC por batch. Sin auth, sin rate limit, sin riesgo de bloqueo CI.
BATCH_URL = "https://yc-oss.github.io/api/batches/{slug}.json"

SEASONS = ["winter", "spring", "summer", "fall"]


def _current_batch_slugs() -> list[str]:
    """Batch en curso + anterior, derivados del mes actual (YC corre 4 al año)."""
    now = datetime.now(timezone.utc)
    idx = (now.month - 1) // 3  # 0=winter, 1=spring, 2=summer, 3=fall
    current = f"{SEASONS[idx]}-{now.year}"
    if idx == 0:
        previous = f"fall-{now.year - 1}"
    else:
        previous = f"{SEASONS[idx - 1]}-{now.year}"
    return [current, previous]


class YCombinator(Source):
    name = "yc"

    def __init__(self, lookback_days: int = 7):
        self.lookback_days = lookback_days

    def fetch(self) -> list[RawItem]:
        cutoff = datetime.now(timezone.utc).timestamp() - self.lookback_days * 86400
        items: list[RawItem] = []
        for slug in _current_batch_slugs():
            for c in self._fetch_batch(slug):
                launched = c.get("launched_at") or 0
                if launched < cutoff:
                    continue
                one_liner = c.get("one_liner") or ""
                long_desc = c.get("long_description") or ""
                items.append(
                    RawItem(
                        source=self.name,
                        title=f"{c.get('name', '?')} (YC {c.get('batch', slug)}) – {one_liner}",
                        url=c.get("website") or f"https://www.ycombinator.com/companies/{c.get('slug', '')}",
                        published_at=datetime.fromtimestamp(launched, tz=timezone.utc),
                        text=f"{one_liner}\n{long_desc}"[:1200],
                        engagement=0,
                        raw_id=str(c.get("id", "")),
                    )
                )
        return items

    def _fetch_batch(self, slug: str) -> list[dict]:
        try:
            resp = httpx.get(BATCH_URL.format(slug=slug), timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001 — batch inexistente aún no es error
            print(f"[yc/{slug}] fetch falló: {e}")
            return []
