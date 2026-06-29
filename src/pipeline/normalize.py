from __future__ import annotations

from ..models import Item, RawItem


def normalize(raw_items: list[RawItem]) -> list[Item]:
    """RawItem -> Item, descartando los que no tienen URL o título usable."""
    items: list[Item] = []
    for r in raw_items:
        if not r.url or not r.title.strip():
            continue
        items.append(
            Item(
                source=r.source,
                title=r.title.strip(),
                url=r.url.strip(),
                published_at=r.published_at,
                text=r.text.strip(),
                engagement=r.engagement,
            )
        )
    return items
