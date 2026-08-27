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


def test_the_committed_card_was_built_from_the_landing_page_as_it_stands() -> None:
    """The staleness this cannot be allowed to have.

    The card's figures are read from the hero file card, so editing that hero
    and not running `make og` leaves the committed image advertising numbers
    the page no longer shows — and nobody on our side ever LOOKS at og.png,
    because it is only ever seen inside other people's timelines. A Makefile
    comment saying "regenerate after editing the hero" is a rule enforced by
    memory, and this repo's own history records exactly that failing on the
    demo report, which was re-rendered from a stale JSON for weeks.

    So `make og` stamps a digest of its source into the PNG and this compares
    it. Reproduction: change any figure in the landing hero card and this test
    fails until the card is rebuilt.
    """
    stamped = og.source_digest(CARD.read_bytes())
    assert stamped is not None, (
        "site/og.png carries no source fingerprint — rebuild it with `make og`")
    assert stamped == og.page_digest(LANDING), (
        "site/og.png was built from an older landing page, so it may be "
        "advertising figures the product no longer produces. Run `make og`.")


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


WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def test_the_alt_text_describes_what_is_actually_on_the_card() -> None:
    """Read aloud by a screen reader, and shown by clients that decline images.

    DERIVED from the rows, not checked for a word. The first version asserted
    `str(len(rows)) in alt or "four" in alt.lower()` against a sentence that
    contains the word "four" — a membership check where the needle is a word
    from the haystack tests nothing, and it passed with the Saquon Barkley row
    deleted from the landing page.
    """
    alt = re.search(r'og:image:alt" content="([^"]+)"', SOCIAL_IMAGE_TAGS).group(1)
    rows = og.hero_rows(LANDING)
    called = [r for r in rows if r["pct"]]
    nocall = [r for r in rows if r["nocall"]]
    assert alt == (
        f"A Beat Your League lineup file: {WORDS[len(rows)]} roster slots, "
        f"{WORDS[len(called)]} with a percentage, "
        f"{WORDS[len(nocall)]} reading no call."), (
        "the alt text no longer describes the card the landing page defines")


def test_a_dropped_row_refuses_rather_than_shipping_a_shorter_card() -> None:
    """Nobody on our side ever looks at og.png — it is seen inside other
    people's timelines. A card quietly showing three of four slots would never
    be noticed here, and the row most likely to be dropped is the no-call one,
    which is the only differently-shaped row and the one carrying the honesty."""
    broken = LANDING.replace('<span class="fnc">', '<span class="fnc muted">', 1)
    assert broken != LANDING, "the no-call row markup moved; update this test"
    with pytest.raises(og.OgError, match="drops one"):
        og.hero_rows(broken)


def test_the_card_copy_is_swept_for_banned_words_like_every_other_surface() -> None:
    """The card is a buyer surface that no page-level sweep can see: it is a
    PNG, and its source lives in a generator rather than under site/. At Grade C
    the frozen method bans calibrated/tested/proven/accurate/"we hit X%" on
    every surface, and og:image:alt sits in <head>, which the page sweeps strip
    before they look."""
    from tests.test_site import _DEV_SPEAK

    # Imported, never retyped — a second copy of the banned list is exactly the
    # drift this repo keeps finding.
    grade_c = r"\b(calibrated|tested|proven|accurate)\b|we hit \d"

    surface = re.sub(r"<style>.*?</style>", " ", og.build_html(LANDING), flags=re.S)
    surface = re.sub(r"<[^>]+>", " ", surface) + " " + SOCIAL_IMAGE_TAGS
    hit = re.search(grade_c, surface, re.I)
    assert not hit, f"the social card carries a Grade-C banned word: {hit.group(0)!r}"
    for pattern in _DEV_SPEAK:
        hit = re.search(pattern, surface, re.I)
        assert not hit, f"the social card carries developer vocabulary: {hit.group(0)!r}"


# --------------------------------------------------------------------- #
# the brand assets Stripe renders on surfaces we do not control
# --------------------------------------------------------------------- #

def test_the_colours_handed_to_stripe_are_legible_both_ways() -> None:
    """Stripe applies the brand and accent colours to buttons, links and header
    bands without telling us which is which. So a colour is only safe to hand
    over if it works as TEXT and as a GROUND — measured, not judged.

    This is why the brand's own gold is deliberately absent: #F2C230 on white
    is 1.68:1, so as a link colour or under white text it is invisible. It
    stays on our surfaces, where we control what sits on it.
    """
    from render.brand import COLOURS

    def luminance(value: str) -> float:
        value = value.lstrip("#")
        parts = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        parts = [p / 12.92 if p <= 0.04045 else ((p + 0.055) / 1.055) ** 2.4
                 for p in parts]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    def contrast(a: str, b: str) -> float:
        la, lb = luminance(a), luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    for role in ("brand", "accent"):
        colour = COLOURS[role]
        assert contrast(colour, "#FFFFFF") >= 4.5, (
            f"{role} {colour} is {contrast(colour, '#FFFFFF'):.2f}:1 on white — "
            f"unreadable if Stripe uses it for link text")
        assert contrast(colour, "#FFFFFF") >= 4.5 or contrast(colour, "#000000") >= 4.5
    assert contrast(COLOURS["gold"], "#FFFFFF") < 4.5, (
        "gold now passes on white — the comment explaining its exclusion is stale")


def test_the_brand_assets_exist_at_the_sizes_stripe_expects() -> None:
    from render.brand import ASSETS, OUT_DIR

    for name, _build, size in ASSETS:
        path = OUT_DIR / name
        assert path.is_file(), f"{name} is missing — run `make brand`"
        assert og.png_size(path.read_bytes()) == size


def test_the_logo_is_drawn_from_the_same_mark_as_every_page() -> None:
    """One drawing of the logo. A second copy is how the invoice header and the
    site's own header end up subtly different."""
    source = (REPO / "render" / "brand.py").read_text(encoding="utf-8")
    assert "from render.report import mark_svg" in source
    # Check for the GEOMETRY, not for "<svg" — brand.py legitimately names the
    # opening tag as a replace() target when it sizes the imported mark.
    for drawing in ("linearGradient", "radialGradient", "<path", "stop-color"):
        assert drawing not in source, (
            f"brand.py contains {drawing!r} — it is drawing its own mark "
            f"instead of importing the one every page uses")


def test_one_chrome_pipeline_serves_both_generators() -> None:
    """The Chrome-does-not-exit workaround is exactly the kind of hard-won
    detail that gets fixed in one copy and not the other."""
    brand = (REPO / "render" / "brand.py").read_text(encoding="utf-8")
    assert "render_png" in brand
    assert "subprocess" not in brand, "brand.py spawns its own browser"
