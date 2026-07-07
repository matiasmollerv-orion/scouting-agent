#!/usr/bin/env python3
"""Empuja newsletters recientes de GBrain al scouting (corre en el Mac, no en CI).

Lee páginas `newsletters/*` del brain vía CLI gbrain, las convierte a items
del pipeline y las mergea en data/newsletters.json (archivo que CI solo lee,
nunca escribe — cero conflictos). Después commitea y pushea.

Costo API: $0 — los newsletters entran a la misma llamada semanal del sábado.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.models import Item  # noqa: E402
from src.pipeline.pool import NEWSLETTERS_FILE, merge_into_pool  # noqa: E402

GBRAIN = os.path.expanduser("~/.bun/bin/gbrain")
LOOKBACK_DAYS = 8
MAX_TEXT = 2000


def _gbrain(*args: str) -> str:
    result = subprocess.run([GBRAIN, *args], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"gbrain {' '.join(args)}: {result.stderr.strip()[:200]}")
    return result.stdout


def recent_newsletter_pages() -> list[tuple[str, str]]:
    """[(slug, título)] de páginas newsletters/* de los últimos LOOKBACK_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).date()
    pages: list[tuple[str, str]] = []
    for line in _gbrain("list", "-n", "200").splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[0].startswith("newsletters/"):
            continue
        slug, _type, date_str, title = parts[0], parts[1], parts[2], parts[3]
        try:
            if datetime.strptime(date_str.strip(), "%Y-%m-%d").date() < cutoff:
                continue
        except ValueError:
            continue
        pages.append((slug.strip(), title.strip()))
    return pages


def page_to_item(slug: str, title: str) -> Item | None:
    try:
        body = _gbrain("get", slug)
    except RuntimeError as e:
        print(f"  SKIP {slug}: {e}")
        return None
    # Quita frontmatter YAML si existe.
    body = re.sub(r"\A---\n.*?\n---\n", "", body, flags=re.DOTALL)
    return Item(
        source="newsletters",
        title=title,
        # URL sintética estable para dedup/seen; el contenido vive en el brain.
        url=f"gbrain://{slug}",
        published_at=datetime.now(timezone.utc),
        text=body.strip()[:MAX_TEXT],
    )


def main() -> None:
    pages = recent_newsletter_pages()
    print(f"[newsletters] {len(pages)} páginas recientes en el brain")
    items = [it for slug, title in pages if (it := page_to_item(slug, title))]
    if not items:
        print("[newsletters] nada que empujar")
        return

    subprocess.run(["git", "-C", str(REPO), "pull", "--rebase", "--quiet", "origin", "main"], check=True)
    added, total = merge_into_pool(items, file=NEWSLETTERS_FILE)
    print(f"[newsletters] +{added} nuevos -> {total} en {NEWSLETTERS_FILE.name}")
    if added == 0:
        return

    subprocess.run(["git", "-C", str(REPO), "add", "data/newsletters.json"], check=True)
    subprocess.run(
        ["git", "-C", str(REPO), "commit", "--quiet", "-m",
         f"newsletters: +{added} desde GBrain {datetime.now().date()}"],
        check=True,
    )
    subprocess.run(["git", "-C", str(REPO), "push", "--quiet"], check=True)
    print("[newsletters] pusheado")


if __name__ == "__main__":
    main()
