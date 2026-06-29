from __future__ import annotations

from datetime import date
from pathlib import Path

from . import config
from .models import RawItem
from .pipeline.normalize import normalize
from .pipeline.prefilter import prefilter
from .pipeline.score import score
from .render.report import render
from .sources.base import Source
from .sources.hackernews import HackerNews
from .sources.producthunt import ProductHunt
from .sources.rss_generic import RSSFeed

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"


def build_sources() -> list[Source]:
    sources: list[Source] = [
        HackerNews(
            lookback_days=config.LOOKBACK_DAYS,
            min_points=config.MIN_ENGAGEMENT["hackernews"],
        )
    ]
    for name, url in config.RSS_FEEDS.items():
        sources.append(RSSFeed(name=name, url=url, lookback_days=config.LOOKBACK_DAYS))
    if config.ENABLE_PRODUCTHUNT:
        sources.append(ProductHunt(lookback_days=config.LOOKBACK_DAYS))
    return sources


def run() -> Path:
    raw: list[RawItem] = []
    for src in build_sources():
        items = src.fetch()
        print(f"[{src.name}] {len(items)} items")
        raw.extend(items)

    candidates = prefilter(normalize(raw))
    print(f"[prefilter] {len(candidates)} candidatos a Claude")

    scored = score(candidates)
    passing = [s for s in scored if s.passes_gate(config.MIN_OBJETIVO)]
    passing.sort(key=lambda s: s.objetivo_total, reverse=True)
    top = passing[: config.MAX_IDEAS]

    report = render(top, total_evaluados=len(scored), min_objetivo=config.MIN_OBJETIVO)

    today = date.today()
    out = REPORTS_DIR / f"{today.year}-W{today.isocalendar().week:02d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"[done] {len(top)} ideas -> {out}")
    return out


if __name__ == "__main__":
    run()
