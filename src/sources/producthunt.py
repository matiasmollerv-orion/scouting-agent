from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from dateutil import parser as dateparser

from ..models import RawItem
from .base import Source

# GraphQL API v2. Requiere developer token (PRODUCTHUNT_TOKEN).
# Módulo OPCIONAL: solo corre si hay token configurado.
PH_URL = "https://api.producthunt.com/v2/api/graphql"

QUERY = """
query ($first: Int!) {
  posts(order: VOTES, first: $first) {
    edges {
      node {
        name
        tagline
        url
        votesCount
        createdAt
      }
    }
  }
}
"""


class ProductHunt(Source):
    name = "producthunt"

    def __init__(self, lookback_days: int = 7):
        self.lookback_days = lookback_days
        self.token = os.environ.get("PRODUCTHUNT_TOKEN", "")

    def fetch(self) -> list[RawItem]:
        if not self.token:
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - self.lookback_days * 86400
        try:
            resp = httpx.post(
                PH_URL,
                json={"query": QUERY, "variables": {"first": 50}},
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30,
            )
            resp.raise_for_status()
            edges = resp.json()["data"]["posts"]["edges"]
        except Exception as e:  # noqa: BLE001
            print(f"[producthunt] fetch falló: {e}")
            return []

        items: list[RawItem] = []
        for edge in edges:
            node = edge["node"]
            published = dateparser.parse(node["createdAt"])
            if published and published.timestamp() < cutoff:
                continue
            items.append(
                RawItem(
                    source=self.name,
                    title=node["name"],
                    url=node["url"],
                    published_at=published,
                    text=node.get("tagline", ""),
                    engagement=int(node.get("votesCount") or 0),
                    raw_id=node["url"],
                )
            )
        return items
