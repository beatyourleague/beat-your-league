"""site/sitemap.xml and the canonical URL of every indexable page.

Usage:
    python -m render.sitemap            # write site/sitemap.xml
    python -m render.sitemap --check    # fail if it is stale

A page is INDEXABLE when it carries no noindex and is not a redirect stub. That
is the same rule the site already applies by hand (the grading pages, thanks
and the confirm page say noindex on purpose), so the sitemap is derived from
the pages rather than kept as a second list to drift. No <lastmod>: a date we
would have to invent or keep true by hand is a claim the crawler trusts.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from render.report import SITE_ORIGIN

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
OUT = SITE / "sitemap.xml"
NOT_PAGES = {"404.html"}


def url_for(path: Path) -> str:
    """The public URL a page is served at."""
    rel = path.relative_to(SITE).as_posix()
    if rel == "index.html":
        return f"{SITE_ORIGIN}/"
    if rel.endswith("/index.html"):
        return f"{SITE_ORIGIN}/{rel[:-len('index.html')]}"
    return f"{SITE_ORIGIN}/{rel}"


def is_indexable(html: str) -> bool:
    return not (re.search(r'<meta name="robots" content="[^"]*noindex', html)
                or 'http-equiv="refresh"' in html)


def indexable_pages() -> list[Path]:
    return [p for p in sorted(SITE.rglob("*.html"))
            if p.name not in NOT_PAGES
            and is_indexable(p.read_text(encoding="utf-8"))]


def build() -> str:
    urls = sorted(url_for(p) for p in indexable_pages())
    body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n</urlset>\n")


def main(argv: list[str] | None = None) -> int:
    check = "--check" in (argv or sys.argv[1:])
    text = build()
    if check:
        ok = OUT.is_file() and OUT.read_text(encoding="utf-8") == text
        print("sitemap is current" if ok else "sitemap is stale — run `make sitemap`")
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT} · {text.count('<loc>')} url(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
