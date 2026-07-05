from __future__ import annotations

import json
import os
import smtplib
import ssl
import subprocess
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
SEEN_FILE = REPORTS_DIR / "seen_urls.json"
SEEN_MAX = 1000  # cap del historial de URLs evaluadas


def _load_seen(current_week: str) -> set[str]:
    """URLs ya evaluadas en semanas ANTERIORES (re-runs de la misma semana no filtran)."""
    if not SEEN_FILE.exists():
        return set()
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return {url for url, week in data.items() if week != current_week}
    except Exception as e:  # noqa: BLE001 — un archivo corrupto no tumba el run
        print(f"[seen] archivo ilegible, se ignora: {e}")
        return set()


def _save_seen(candidates, current_week: str) -> None:
    data: dict[str, str] = {}
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    for it in candidates:
        data[it.dedup_key()] = current_week
    # Conserva solo las entradas más recientes (dict preserva orden de inserción).
    if len(data) > SEEN_MAX:
        data = dict(list(data.items())[-SEEN_MAX:])
    SEEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


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

    today = date.today()
    week = today.isocalendar().week
    week_key = f"{today.year}-W{week:02d}"

    candidates = prefilter(normalize(raw), seen_urls=_load_seen(week_key))
    print(f"[prefilter] {len(candidates)} candidatos a Claude")

    scored = score(candidates)
    scored.sort(key=lambda s: s.objetivo_total, reverse=True)
    scoring_failed = bool(candidates) and not scored

    # Ideas que pasaron el gate (para el reporte Markdown del repo)
    passing = [s for s in scored if s.passes_gate(config.MIN_OBJETIVO)]
    top_gate = passing[: config.MAX_IDEAS]

    # Top 5 por score para el email (con o sin gate — siempre hay algo que ver)
    top_email = scored[: config.MAX_IDEAS]

    report = render(top_gate, total_evaluados=len(scored), min_objetivo=config.MIN_OBJETIVO)

    out = REPORTS_DIR / f"{week_key}.md"
    out.write_text(report, encoding="utf-8")
    if scored:
        _save_seen(candidates, week_key)  # solo marca vistos si el scoring funcionó
    print(f"[done] {len(top_gate)} sobre gate, top-5 email: {[s.objetivo_total for s in top_email]} -> {out}")

    _capture_to_gbrain(out)

    # --- Envío de email HTML (siempre top 5, marcando cuáles pasaron el gate) ---
    _send_email(top_email, passing_ids={s.url for s in top_gate},
                total_evaluados=len(scored), week=week,
                error=scoring_failed)

    return out


def _capture_to_gbrain(report_path: Path) -> None:
    gbrain = os.path.expanduser("~/.bun/bin/gbrain")
    if not os.path.exists(gbrain):
        return
    try:
        result = subprocess.run(
            [gbrain, "capture", "--file", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"[gbrain] capturado: {report_path.name}")
        else:
            print(f"[gbrain] error: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        print("[gbrain] timeout al capturar reporte")
    except Exception as e:
        print(f"[gbrain] no disponible: {e}")


def _send_email(top, passing_ids: set, total_evaluados: int, week: int,
                error: bool = False) -> None:
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        print("[email] GMAIL_USER / GMAIL_APP_PASSWORD no configuradas — se omite el envío")
        return

    html = render_html(top, passing_ids=passing_ids, total_evaluados=total_evaluados,
                       min_objetivo=config.MIN_OBJETIVO, error=error)
    n_passed = len(passing_ids)
    if error:
        subject = f"⚠️ Scouting Semanal — Semana {week} · falló el scoring, revisar logs"
    else:
        subject = (
            f"🔍 Scouting Semanal — Semana {week} · "
            f"{n_passed} idea{'s' if n_passed != 1 else ''} sobre el gate · top {len(top)} mostradas"
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
