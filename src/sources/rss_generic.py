from __future__ import annotations

import time
from datetime import datetime, timezone

import feedparser
import httpx
from dateutil import parser as dateparser

from ..models import RawItem
from .base import Source

DEFAULT_HEADERS = {"User-Agent": "scouting-agent/1.0 (github.com/matiasmollerv-orion/scouting-agent)"}


class RSSFeed(Source):
    """Fuente RSS genérica. Reutilizable para cualquier feed RSS/Atom.

    Usa httpx para el fetch (permite headers personalizados — necesario para
    Reddit, que bloquea requests sin User-Agent).
    """

    def __init__(self, name: str, url: str, lookback_days: int = 7,
                 extra_headers: dict | None = None, pre_fetch_delay: int = 0):
        self.name = name
        self.url = url
        self.lookback_days = lookback_days
        self.headers = {**DEFAULT_HEADERS, **(extra_headers or {})}
        self.pre_fetch_delay = pre_fetch_delay  # segundos a esperar antes de fetch

    def fetch(self) -> list[RawItem]:
        if self.pre_fetch_delay:
            time.sleep(self.pre_fetch_delay)
        try:
            resp = httpx.get(self.url, headers=self.headers, timeout=20,
                             follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
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


class MultiFeed(Source):
    """Varias consultas RSS fusionadas en UNA fuente (Google Noticias con consultas simples).

    Dedup por título normalizado y tope `max_items` para no inflar el pool diario.
    """

    def __init__(self, name: str, urls: list[str], lookback_days: int = 7, max_items: int = 40,
                 delay: float = 0.4):
        self.name = name
        self.feeds = [RSSFeed(name=name, url=u, lookback_days=lookback_days) for u in urls]
        self.max_items = max_items
        self.delay = delay

    def fetch(self) -> list[RawItem]:
        import re
        per_query: list[list[RawItem]] = []
        for i, feed in enumerate(self.feeds):
            if i:
                time.sleep(self.delay)
            per_query.append(feed.fetch())
        # Intercala las consultas (1 de cada una por turno, en el orden de relevancia de Google):
        # ninguna consulta monopoliza el cupo, y no se ordena por fecha porque eso sube el ruido
        # de "ayer" (incendios, ofertas de empleo) por sobre lo relevante.
        seen: set[str] = set()
        out: list[RawItem] = []
        for rank in range(max((len(q) for q in per_query), default=0)):
            for q in per_query:
                if rank < len(q):
                    key = re.sub(r"\W+", "", q[rank].title.lower())[:80]
                    if key and key not in seen:
                        seen.add(key)
                        out.append(q[rank])
        out = out[: self.max_items]
        for it in out:  # Google Noticias repite el titular como "resumen": no gastar tokens en eso
            if it.text and it.text[:40] == it.title[:40]:
                it.text = ""
        return out
