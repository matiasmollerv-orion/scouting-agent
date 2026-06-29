from __future__ import annotations

from datetime import date
from pathlib import Path

import resend

from . import config
from .models import RawItem
from .pipeline.normalize import normalize
from .pipeline.prefilter import prefilter
from .pipeline.score import score
from .render.email import render_html
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
    for name, url in config.REDDIT_FEEDS.items():
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
    week = today.isocalendar().week
    out = REPORTS_DIR / f"{today.year}-W{week:02d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"[done] {len(top)} ideas -> {out}")

    # --- Envío de email HTML ---
    _send_email(top, total_evaluados=len(scored), week=week)

    return out


def _send_email(top, total_evaluados: int, week: int) -> None:
    if not config.RESEND_API_KEY:
        print("[email] RESEND_API_KEY no configurada — se omite el envío")
        return

    html = render_html(top, total_evaluados=total_evaluados, min_objetivo=config.MIN_OBJETIVO)
    resend.api_key = config.RESEND_API_KEY

    params: resend.Emails.SendParams = {
        "from": "Scouting Semanal <onboarding@resend.dev>",
        "to": [config.EMAIL_TO],
        "subject": f"🔍 Scouting Semanal — Semana {week} · {len(top)} idea{'s' if len(top) != 1 else ''} sobre el gate",
        "html": html,
    }
    resp = resend.Emails.send(params)
    print(f"[email] enviado a {config.EMAIL_TO} — id={resp['id']}")


if __name__ == "__main__":
    run()
