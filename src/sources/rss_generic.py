from __future__ import annotations

from datetime import datetime, timezone

import feedparser
from dateutil import parser as dateparser

from ..models import RawItem
from .base import Source


class RSSFeed(Source):
    """Fuente RSS genérica. Reutilizable para TechCrunch, Wired, MIT, etc."""

    def __init__(self, name: str, url: str, lookback_days: int = 7):
        self.name = name
        self.url = url
        self.lookback_days = lookback_days

    def fetch(self) -> list[RawItem]:
        try:
            feed = feedparser.parse(self.url)
        except Exception as e:  # noqa: BLE001
            print(f"[{self.name}] fetch falló: {e}")
            return []

        cutoff = datetime.now(timezone.utc).timestamp() - self.lookback_days * 86400
        items: list[RawItem] = []
        for entry in feed.entries:
            published = _parse_date(entry)
            if published and published.timestamp() < cutoff:
                continue
            summary = entry.get("summary", "") or ""
            items.append(
                RawItem(
                    source=self.name,
                    title=entry.get("title", "") or "",
                    url=entry.get("link", "") or "",
                    published_at=published,
                    text=_strip_html(summary),
                    engagement=0,  # RSS no expone métrica fiable
                    raw_id=entry.get("id", entry.get("link", "")),
                )
            )
        return items


def _parse_date(entry) -> datetime | None:
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = dateparser.parse(val)
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                continue
    return None


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text).strip()
