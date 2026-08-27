"""The social preview card (render/og.py, site/og.png).

Marketing is organic posts on X, so this image is seen by more people than the
site is. It is also the one asset with no reader on our side: nobody opens
og.png, they see it inside somebody else's timeline, so a wrong number on it
would be invisible here and public everywhere.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

from render import og
from render.report import OG_IMAGE, SITE_ORIGIN, SOCIAL_IMAGE_TAGS

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
SAMPLE = (SITE / "sample-report.html").read_text(encoding="utf-8")
CARD = SITE / "og.png"

PAGES = sorted(SITE.rglob("*.html"))


def test_the_card_exists_and_is_the_size_every_platform_crops_to() -> None:
    """1200x630 is what X, Facebook, LinkedIn and Slack all document. A card of
    another shape is not rejected, it is CROPPED — in a different place by each
    of them, which is how a headline loses its last word on one network only."""
    assert CARD.is_file(), "site/og.png is missing — run `make og`"
    data = CARD.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (og.WIDTH, og.HEIGHT) == (1200, 630)


def test_the_card_is_small_enough_to_be_fetched() -> None:
    assert CARD.stat().st_size <= og.MAX_BYTES


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SITE)))
def test_every_public_page_carries_the_card(page: Path) -> None:
    """Including the generated ones. A page whose og:image is missing renders on
    X as a grey box with a domain in it, which reads as a link to be wary of."""
    text = page.read_text(encoding="utf-8")
    assert f'<meta property="og:image" content="{OG_IMAGE}">' in text
    assert '<meta name="twitter:card" content="summary_large_image">' in text, (
        "summary crops a 1.91:1 card to a small square thumbnail, which throws "
        "away the file card that is the whole point of having an image")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SITE)))
def test_no_page_still_carries_the_placeholder(page: Path) -> None:
    assert "YOUR-DOMAIN" not in page.read_text(encoding="utf-8")


def test_the_image_url_matches_the_domain_github_pages_actually_serves() -> None:
    """One source of truth. site/CNAME is what Pages serves; an og:image on any
    other host silently fails to render and nothing here would notice."""
    cname = (SITE / "CNAME").read_text(encoding="utf-8").strip()
    assert SITE_ORIGIN == f"https://{cname}"
    assert OG_IMAGE == f"https://{cname}/og.png"
    assert (SITE / OG_IMAGE.rsplit("/", 1)[1]).is_file(), (
        "the og:image URL points at a file that is not in site/")


def test_the_tags_are_one_constant_not_a_copy_per_generator() -> None:
    """Three renderers emit this block. Copies drift — this repo's own history
    is a list of the third copy going stale."""
    for name in ("render/backtest_site.py", "render/ledger_site.py"):
        source = (REPO / name).read_text(encoding="utf-8")
        assert "SOCIAL_IMAGE_TAGS" in source, f"{name} hardcodes its own tags"
        assert "og:image" not in source, f"{name} still writes og:image by hand"


# --------------------------------------------------------------------- #
# the figures on the card
# --------------------------------------------------------------------- #

def test_the_card_quotes_the_landing_page_rather_than_inventing_numbers() -> None:
    """The rows are READ from the hero file card, which a separate test already
    pins to the published sample. So the card inherits that pin and cannot
    advertise a number the product stopped producing."""
    rows = og.hero_rows(LANDING)
    assert len(rows) >= 3, "too few rows to be the real card"
    flat = re.sub(r"<[^>]+>", " ", SAMPLE)
    for row in rows:
        assert row["name"] in LANDING
        if row["pct"]:
            assert f'{row["pct"]}%' in flat or f'{row["pct"]}%' in SAMPLE, (
                f'{row["name"]} is shown at {row["pct"]}% on the card, and that '
                f"figure is nowhere in the published sample")


def test_a_card_whose_rows_cannot_be_read_refuses_to_build() -> None:
    """Fails closed. Those numbers are the product's own output; inventing them
    on the most-forwarded surface we own is the fabrication principle 3 bans."""
    with pytest.raises(og.OgError):
        og.hero_rows("<html><body>no file card here</body></html>")
    with pytest.raises(og.OgError):
        og.headline("<html><body>no headline</body></html>")


def test_the_headline_is_the_landing_pages_own() -> None:
    assert og.headline(LANDING) == "Know who to start."


def test_the_built_page_carries_every_row_and_no_stray_markup() -> None:
    page = og.build_html(LANDING)
    for row in og.hero_rows(LANDING):
        assert row["slot"] in page
        # The name is escaped on the way in — Ja'Marr Chase has an apostrophe.
        assert row["name"].replace("'", "&#x27;") in page or row["name"] in page
    assert f"{og.WIDTH}px" in page and f"{og.HEIGHT}px" in page


def test_a_wrong_sized_render_is_rejected_rather_than_published() -> None:
    """A headless render that loses its viewport still writes a perfectly valid
    PNG, just the wrong shape. Trusting the exit code would publish it."""
    with pytest.raises(og.OgError):
        og.png_size(b"not a png at all, but bytes")
    header = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
              + struct.pack(">II", 640, 480))
    assert og.png_size(header) == (640, 480) != (og.WIDTH, og.HEIGHT)


def test_the_alt_text_describes_what_is_actually_on_the_card() -> None:
    """Read aloud by a screen reader, and shown by clients that decline images."""
    alt = re.search(r'og:image:alt" content="([^"]+)"', SOCIAL_IMAGE_TAGS).group(1)
    assert "no call" in alt, (
        "the honesty the card is built around is missing from its description")
    rows = og.hero_rows(LANDING)
    assert str(len(rows)) in alt or "four" in alt.lower()
