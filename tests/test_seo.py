"""Search visibility: a sitemap derived from the pages, canonical URLs that agree
with it, and a 404 that works from any depth.

The sitemap is generated from what the pages themselves say (noindex, redirect
stubs), never from a second hand-kept list, so a new page cannot be forgotten
and a grading page cannot be published by accident."""

from __future__ import annotations

import re
from pathlib import Path

from render import sitemap

SITE = Path(__file__).resolve().parent.parent / "site"


def test_the_sitemap_is_current_and_lists_exactly_the_indexable_pages() -> None:
    xml = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    assert xml == sitemap.build(), "site/sitemap.xml is stale — run `python -m render.sitemap`"
    listed = set(re.findall(r"<loc>([^<]+)</loc>", xml))
    for path in sorted(SITE.rglob("*.html")):
        html = path.read_text(encoding="utf-8")
        url = sitemap.url_for(path)
        if path.name == "404.html" or not sitemap.is_indexable(html):
            assert url not in listed, f"{url} says noindex (or is a stub) but is in the sitemap"
        else:
            assert url in listed, f"{url} is indexable but missing from the sitemap"
    for grading in ("backtest", "confidence", "projections", "no-call", "ledger", "compare"):
        assert not any(f"/{grading}" in u for u in listed), grading


def test_every_indexable_page_names_its_own_canonical_url() -> None:
    for path in sitemap.indexable_pages():
        html = path.read_text(encoding="utf-8")
        found = re.findall(r'<link rel="canonical" href="([^"]+)"', html)
        assert found == [sitemap.url_for(path)], \
            f"{path.relative_to(SITE)} canonical is {found}, wanted {sitemap.url_for(path)}"


def test_robots_points_at_the_sitemap() -> None:
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://beatyourleague.com/sitemap.xml" in robots
    assert "Disallow: /\n" not in robots


def test_the_404_page_works_from_any_depth() -> None:
    """GitHub Pages serves it for a mistyped /join/x too, so a relative link
    would resolve against the wrong folder."""
    html = (SITE / "404.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in html
    for href in re.findall(r'href="([^"]+)"', html):
        assert href.startswith(("/", "https://", "mailto:")) or "fonts" in href, \
            f"404 links {href!r}, which breaks from a nested URL"
    assert 'href="/"' in html and "/how-it-works.html" in html
