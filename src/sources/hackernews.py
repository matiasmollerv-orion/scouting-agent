from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..models import RawItem
from .base import Source

# Algolia: API pública, sin auth, sin rate limit agresivo.
ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNews(Source):
    name = "hackernews"

    def __init__(self, lookback_days: int = 7, min_points: int = 50):
        self.lookback_days = lookback_days
        self.min_points = min_points

    def fetch(self) -> list[RawItem]:
        cutoff = int(
            datetime.now(timezone.utc).timestamp() - self.lookback_days * 86400
        )
        # Pool 1: Show HN — lanzamientos de productos reales, umbral bajo
        # porque son relevantes por definición (el autor muestra lo que construyó).
        show_hn = self._query(tags="show_hn", cutoff=cutoff, min_points=5)

        # Pool 2: stories genéricas — umbral alto para filtrar ruido político/viral.
        stories = self._query(tags="story", cutoff=cutoff, min_points=self.min_points)

        seen: set[str] = {h.get("objectID") for h in show_hn}
        combined = show_hn + [h for h in stories if h.get("objectID") not in seen]
        return [self._to_item(h) for h in combined]

    def _query(self, tags: str, cutoff: int, min_points: int) -> list[dict]:
        params = {
            "tags": tags,
            "numericFilters": f"created_at_i>{cutoff},points>{min_points}",
            "hitsPerPage": 200,
        }
        try:
            resp = httpx.get(ALGOLIA_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json().get("hits", [])
        except Exception as e:  # noqa: BLE001
            print(f"[hackernews/{tags}] fetch falló: {e}")
            return []

    def _to_item(self, h: dict) -> RawItem:
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
        return RawItem(
            source=self.name,
            title=h.get("title") or "",
            url=url,
            published_at=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
            text=h.get("story_text") or "",
            engagement=int(h.get("points") or 0) + int(h.get("num_comments") or 0),
            raw_id=str(h.get("objectID")),
        )
