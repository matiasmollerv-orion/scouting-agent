from __future__ import annotations

import smtplib
import ssl
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

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
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        print("[email] GMAIL_USER / GMAIL_APP_PASSWORD no configuradas — se omite el envío")
        return

    html = render_html(top, total_evaluados=total_evaluados, min_objetivo=config.MIN_OBJETIVO)
    subject = (
        f"🔍 Scouting Semanal — Semana {week} · "
        f"{len(top)} idea{'s' if len(top) != 1 else ''} sobre el gate"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = formataddr(("Scouting Semanal", config.GMAIL_USER))
    msg["To"]      = config.EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_USER, [config.EMAIL_TO], msg.as_string())
        print(f"[email] enviado a {config.EMAIL_TO}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"[email] error de autenticación Gmail: {e}")
    except Exception as e:
        print(f"[email] error SMTP: {e}")


if __name__ == "__main__":
    run()
