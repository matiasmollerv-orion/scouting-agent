"""Fábrica de fuentes — separada de main.py para que collect.py (job diario
sin API) no arrastre imports de anthropic."""
from __future__ import annotations

from . import config
from .sources.base import Source
from .sources.hackernews import HackerNews
from .sources.producthunt import ProductHunt
from .sources.rss_generic import RSSFeed
from .sources.yc import YCombinator


def build_sources() -> list[Source]:
    sources: list[Source] = [
        HackerNews(
            lookback_days=config.LOOKBACK_DAYS,
            min_points=config.MIN_ENGAGEMENT["hackernews"],
        )
    ]
    for name, url in config.RSS_FEEDS.items():
        sources.append(RSSFeed(name=name, url=url, lookback_days=config.LOOKBACK_DAYS))
    for name, url in config.REDDIT_FEEDS.items():
        sources.append(RSSFeed(name=name, url=url, lookback_days=config.LOOKBACK_DAYS))
    if config.ENABLE_PRODUCTHUNT:
        sources.append(ProductHunt(lookback_days=config.LOOKBACK_DAYS))
    if config.ENABLE_YC:
        sources.append(YCombinator(lookback_days=config.LOOKBACK_DAYS))
    return sources
