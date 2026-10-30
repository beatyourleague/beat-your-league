"""The social preview card — `site/og.png`, generated, never drawn by hand.

Marketing is organic posts on X, so every link we post is rendered as a card.
With no `og:image` that card is a grey box with a domain in it, which reads as a
link somebody is wary of clicking. This is the one asset that is seen by more
people than the site itself.

**The figures on it are READ from the landing page, never typed here.** The hero
phone's card 01 is generated from the published sample (render/phone.py) and
tests hold it there (`test_site.py`'s `.filecard` sweep, `test_truth_landing.py`'s
staleness check), so lifting the rows out of the page inherits that pin: an OG
card cannot advertise a number the product stopped producing. The card shows
`og_rows` of them — every row with odds and the first flagged row. Typing them again would be a third copy of the same four numbers, and
this repo keeps finding that the third copy is the one that goes stale. If the
rows cannot be found the build REFUSES rather than falling back to something
invented — an unfindable card is a missing image, a wrong one is a false claim.

Rendered by headless Chrome because the page is real HTML with the site's own
type and palette, and because the alternatives all lose something: there is no
image library in requirements.txt (adding Pillow to draw one PNG a year is a
dependency we would carry forever), and X does not render SVG previews at all.
The PNG is COMMITTED. GitHub Pages serves it as a static file, and site/og.png
is regenerated locally and deliberately, like `make sample`.

**A second card IS rendered in CI: this week's (G2, Oct 2026).** Every Tuesday
post links this-week.html, and its preview was og.png, whose alt describes a
2024 lineup. ``python -m render.og --week`` draws the week's recorded closest
call (site/week.json ``closest``, contract C9) as that page's preview, at
site/og/this-week-<season>-wNN.png, in the weekly workflow's ``share-card``
job — a job with NO secrets, after the job that holds the registry has
finished, using the runner image's own Chrome. It refuses (exit 0, nothing
drawn, the page keeps og.png) unless the call is recorded at both levels, is
not a toss-up, and the page's own closest-call card prints the same verdict,
percentage and projection — so the card can only ever repeat the page.
"""

from __future__ import annotations

import argparse
import base64
import html
import re
import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
LANDING = SITE / "index.html"
OUT = SITE / "og.png"

# The card everyone renders at: 1.91:1 is what X, Facebook, LinkedIn and Slack
# all crop to, and 1200x630 is the size each of them documents. Going bigger
# buys nothing and costs file size on a preview most people see at ~500px wide.
WIDTH, HEIGHT = 1200, 630

# X drops a preview image over 5 MB. We are nowhere near it, but a generated
# asset with no ceiling is how a 12 MB screenshot ships one day unnoticed.
MAX_BYTES = 1_000_000

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
)


class OgError(RuntimeError):
    pass


# --------------------------------------------------------------------- #
# the type: the site's own self-hosted faces, embedded
# --------------------------------------------------------------------- #

FONT_DIR = SITE / "fonts"
# The faces the card sets, as (family, weight, style, file stem in FONT_DIR).
CARD_FACES = (
    ("Barlow", "500", "normal", "barlow-500"),
    ("Barlow", "700", "normal", "barlow-700"),
    ("Barlow Condensed", "800", "normal", "barlow-condensed-800"),
    ("Barlow Condensed", "900", "normal", "barlow-condensed-900"),
    ("Barlow Condensed", "900", "italic", "barlow-condensed-900i"),
)


def embedded_fonts(faces=CARD_FACES, font_dir: Path | None = None) -> str:
    """@font-face rules carrying the site's own woff2 files as data: URIs.

    The card renders from a file in a temp directory, and Chrome refuses a
    font loaded from file:// into a file:// page (an opaque origin, so the
    CORS check fails). Embedding is what lets the card use exactly the type
    every page serves — it used to fetch Google Fonts mid-render, a third-
    party request and a network race on every build. Fails closed: a card set
    in Arial stops looking like the product, so a missing face refuses.
    """
    folder = font_dir or FONT_DIR
    rules = []
    for family, weight, style, stem in faces:
        path = folder / f"{stem}.woff2"
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise OgError(f"font file {path.name} is missing — the card would "
                          f"render in a fallback face") from exc
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:{style};"
            f"font-weight:{weight};font-display:block;src:url(data:font/woff2;"
            f"base64,{base64.b64encode(data).decode('ascii')}) format('woff2');}}")
    return "\n".join(rules)


# --------------------------------------------------------------------- #
# the figures, lifted from the page that is already pinned to the sample
# --------------------------------------------------------------------- #

_ROW = re.compile(
    r'<div class="frow"(?: data-i="\d+")?>'
    r'<span class="fslot">([^<]+)</span>'
    r'<span class="fname">([^<]+)</span>'
    r'(?:<span class="fproj">([\d.]+)</span>)?'
    r'(?:<span class="fbar"><i style="width:(\d+)%"></i></span>'
    r'<span class="fpct">(\d+)%</span>'
    r'|<span class="fnc(?: (flag|basis))?">([^<]+)</span>)?'
    r'</div>',
    re.S)


def _lineup_card(page: str) -> str:
    """Card 01 of the hero phone: the first real-report file card on the
    page, and in it the section the report itself calls the lineup."""
    start = page.find('<div class="filecard')
    if start < 0:
        raise OgError("no hero file card on the landing page — refusing to "
                      "invent rows for the social card")
    end = page.find("<!--/card-->", start)
    card = page[start:end if end > 0 else len(page)]
    lineup = card.find('data-sec="lineup"')
    if lineup < 0:
        raise OgError("the hero file card carries no lineup card")
    close = card.find("</section>", lineup)
    return card[lineup:close if close > 0 else len(card)]


def real_label(page: str) -> str:
    """"2024 sample report · Week 10": the season and week of the hero's file
    card, read from its data-real marker (render.phone.real_tag) and said the
    way the landing's caption says it, the year first (sales review: a bare
    "Week 10" read as this season's week). The card read only "Real output", so
    posted on X in 2026 it passed 2024 odds off as this week's (review
    BUYER-7). No marker, no card: the year is never guessed."""
    found = re.search(r'<div class="filecard"[^>]*data-real="(\d{4})-w(\d{1,2})"', page)
    if not found:
        raise OgError("the hero file card names no season and week (data-real) — "
                      "refusing to draw a card that cannot say which week it shows")
    return f"{found.group(1)} sample report · Week {int(found.group(2))}"


def hero_rows(page: str) -> list[dict[str, str]]:
    """The hero phone's lineup rows, exactly as the landing page states them.

    The phone is generated from the pinned sample (render/phone.py), and its
    card 01 is the report's own: every starter, his projection, and either
    his odds or the reason a row carries none. Fails closed. A card whose rows
    we cannot read is not quietly replaced with plausible-looking ones: those
    numbers are the product's own output and inventing them here would be the
    fabrication principle 3 forbids, on the single most-forwarded surface we
    own.
    """
    body = _lineup_card(page)
    rows: list[dict[str, str]] = []
    for slot, name, proj, width, pct, tone, nocall in _ROW.findall(body):
        rows.append({"slot": html.unescape(slot.strip()),
                     "name": html.unescape(name.strip()),
                     "proj": proj, "width": width, "pct": pct,
                     "nocall": html.unescape(nocall.strip()), "tone": tone})
    if not rows:
        raise OgError("the hero file card carried no rows we could read")
    # A regex that stops matching drops a row SILENTLY, and a card showing
    # three of four slots is not obviously broken to anyone — least of all
    # here, where nobody views the output; it is seen inside other people's
    # timelines. Counting what the card DECLARES turns a parser that has
    # fallen behind the markup into a refusal instead of a quieter lie. The
    # no-call row is the one most likely to go: it is the only row with a
    # different shape, and it is the row that carries the honesty.
    declared = len(re.findall(r'<div class="frow"', body))
    if len(rows) != declared:
        raise OgError(
            f"the hero file card declares {declared} rows and only "
            f"{len(rows)} could be read — refusing to publish a card that "
            f"drops one")
    return rows


def og_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """The rows the share card shows: every row with odds, and the first row
    the report flags (the questionable starter) — the decided lineup at a
    glance, honesty included, in a card a timeline renders at ~500px. Order
    is the report's own. Refuses a selection with no odds: a share card of
    reasons alone would sell nothing the product does."""
    picked: list[dict[str, str]] = []
    flagged = False
    for row in rows:
        if row["pct"]:
            picked.append(row)
        elif row["nocall"] and row["tone"] == "flag" and not flagged:
            picked.append(row)
            flagged = True
    if not any(row["pct"] for row in picked):
        raise OgError("the hero card prints no odds — nothing for the share "
                      "card to show")
    return picked


def _h1(page: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if not match:
        raise OgError("no <h1> on the landing page")
    return match.group(1)


def _text(fragment: str) -> str:
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", fragment).split()))


def headline(page: str) -> str:
    return _text(_h1(page))


def headline_html(page: str) -> str:
    """The landing's headline in the landing's own treatment: the words, and
    the one phrase it sets on the gold slab (its <em>). Rebuilt from TEXT, so
    nothing but the two words and an <em> of ours reaches the card's markup
    (launch review I13: the card set "Know who to start." in sentence case,
    unlike the page it advertises, which weakened recall between X and the
    landing)."""
    inner = _h1(page)
    match = re.search(r"<em\b[^>]*>(.*?)</em>", inner, re.S)
    if not match:
        return html.escape(headline(page))
    before, slab = _text(inner[:match.start()]), _text(match.group(1))
    after = _text(inner[match.end():])
    return " ".join(part for part in (
        html.escape(before), f"<em><span>{html.escape(slab)}</span></em>",
        html.escape(after)) if part)


# --------------------------------------------------------------------- #
# the page
# --------------------------------------------------------------------- #

def _row_html(row: dict[str, str]) -> str:
    slot = html.escape(row["slot"])
    name = html.escape(row["name"])
    proj = (f'<span class="fproj">{html.escape(row["proj"])}</span>'
            if row.get("proj") else "")
    if row["nocall"]:
        tone = " flag" if row.get("tone") == "flag" else ""
        return (f'<div class="frow"><span class="fslot">{slot}</span>'
                f'<span class="fname">{name}</span>{proj}'
                f'<span class="fnc{tone}">{html.escape(row["nocall"])}</span></div>')
    return (f'<div class="frow"><span class="fslot">{slot}</span>'
            f'<span class="fname">{name}</span>{proj}'
            f'<span class="fbar"><i style="width:{html.escape(row["width"])}%"></i></span>'
            f'<span class="fpct">{html.escape(row["pct"])}%</span></div>')


def build_html(page: str) -> str:
    """The card, in the site's own palette and type."""
    rows = "\n        ".join(_row_html(row) for row in og_rows(hero_rows(page)))
    head = headline_html(page)
    # The logo, from the one drawing every page uses (imported here, not at the
    # top, so render.og stays importable on its own).
    from render.report import mark_svg
    mark = mark_svg("og", "ogmark")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<style>{embedded_fonts()}</style>
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;}}
  body{{background:#05090F;color:#F6F4EE;font-family:'Barlow',Arial,sans-serif;
    display:flex;align-items:center;gap:40px;padding:0 60px;position:relative;}}
  /* One warm source of light behind the card, so the paper reads as lit rather
     than pasted on. Same gold as the accent, nothing new introduced. */
  body::before{{content:"";position:absolute;inset:0;
    background:radial-gradient(1100px 620px at 74% 40%,rgba(242,194,48,.14),transparent 62%),
               radial-gradient(760px 520px at 6% 96%,rgba(30,122,70,.16),transparent 68%);}}
  .left{{position:relative;width:540px;flex:none;}}
  .mark{{display:flex;align-items:center;gap:12px;margin-bottom:26px;}}
  .mark svg.ogmark{{display:block;width:40px;height:40px;flex:none;margin:0;}}
  /* The official lockup (render/brand.py logo_html, contract C2): heavy
     italic capitals, "Beat Your" in paper and "League" in the logo's gold.
     It was tracked gold caps, upright — an eyebrow, not the logo (D10). */
  .mark span{{font-family:'Barlow Condensed';font-weight:900;font-size:23px;
    font-style:italic;letter-spacing:.01em;text-transform:uppercase;color:#F6F4EE;}}
  .mark span .lg{{color:#F0B62A;}}
  /* The landing hero's own treatment (launch review I13): heavy italic
     capitals, the payoff phrase on the tilted slab — flat gold, as the page
     draws it now (contract C6: no gradient, no glow). */
  h1{{font-family:'Barlow Condensed';font-weight:900;font-style:italic;font-size:96px;
    line-height:.92;text-transform:uppercase;}}
  h1 em{{font-style:italic;color:#101E33;display:inline-block;margin-top:10px;
    background:#F2C230;padding:0 16px 5px;transform:rotate(-1.5deg);}}
  h1 em span{{display:inline-block;}}
  .sub{{margin-top:24px;font-size:26px;line-height:1.42;color:#BCC9DB;font-weight:500;
    max-width:520px;}}
  .sub b{{color:#F6F4EE;font-weight:700;}}
  .right{{position:relative;flex:none;}}
  /* The report's own card 01 (render.report.card_html, contract C3): white
     paper, a navy head, hairline rows, flat gold bars drawn from 50%,
     upright numerals — the same object as the phone on the page. */
  .filecard{{width:500px;background:#FFFFFF;color:#101E33;border:1px solid #E2DDD0;
    border-radius:16px;overflow:hidden;box-shadow:0 40px 90px -28px rgba(0,0,0,.9);}}
  .filehead{{display:flex;justify-content:space-between;align-items:center;gap:10px;
    background:#101E33;color:#F6F4EE;padding:16px 22px;
    font-family:'Barlow Condensed';font-weight:800;font-size:18px;letter-spacing:.08em;
    text-transform:uppercase;}}
  .filehead span{{color:#F2C230;font-size:14px;letter-spacing:.08em;}}
  .fbody{{padding:6px 22px 14px;}}
  .frow{{display:grid;grid-template-columns:40px minmax(0,1fr) 46px 60px 58px;column-gap:12px;
    align-items:center;padding:14px 0;border-bottom:1px solid #EEEAE1;font-size:21px;}}
  .frow:last-child{{border-bottom:0;}}
  .fslot{{font-family:'Barlow Condensed';font-weight:800;font-size:16px;color:#5A6B80;
    letter-spacing:.06em;}}
  .fname{{font-weight:700;white-space:nowrap;}}
  .fproj{{font-size:19px;color:#33445C;text-align:right;font-variant-numeric:tabular-nums;}}
  .fbar{{height:9px;background:#E9E5DA;border-radius:999px;overflow:hidden;}}
  .fbar i{{display:block;height:100%;border-radius:999px;background:#F2C230;}}
  .fpct{{font-family:'Barlow Condensed';font-weight:800;font-size:27px;
    text-align:right;font-variant-numeric:tabular-nums;}}
  .fnc{{grid-column:2 / -1;grid-row:2;font-size:14px;font-weight:700;letter-spacing:.06em;
    color:#5A6B80;text-transform:uppercase;margin-top:2px;}}
  .fnc.flag{{color:#B3402F;}}
</style></head>
<body>
  <div class="left">
    <div class="mark">{mark}<span>Beat Your <span class="lg">League</span></span></div>
    <h1>{head}</h1>
    <div class="sub">Your lineup, decided every Tuesday — from <b>your exact
      roster</b>, scored PPR, half-PPR or standard.</div>
  </div>
  <div class="right">
    <div class="filecard">
      <div class="filehead">Your lineup, decided <span>{html.escape(real_label(page))}</span></div>
      <div class="fbody">
        {rows}
      </div>
    </div>
  </div>
</body></html>
"""


# --------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------- #

def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if "/" in candidate:
            if Path(candidate).is_file():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    raise OgError(
        "no Chrome or Chromium found to render the card. This is only needed "
        "when regenerating site/og.png; the committed PNG is what ships.")


# The fingerprint key stamped into the PNG. The card's figures are read from
# the landing page, so an edit to the hero file card leaves the committed image
# advertising numbers the page no longer shows — and NOBODY on our side ever
# looks at og.png, because it is only ever seen inside other people's
# timelines. A Makefile comment saying "regenerate after editing the hero" is a
# rule enforced by memory, which this repo's own history records failing on the
# demo report. So the source is stamped into the file and a test compares it.
SOURCE_KEY = b"byl-source-sha256"


def _text_chunk(key: bytes, value: bytes) -> bytes:
    payload = b"tEXt" + key + b"\x00" + value
    return (struct.pack(">I", len(payload) - 4) + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF))


def stamp_source(data: bytes, digest: str) -> bytes:
    """Insert the source fingerprint straight after IHDR."""
    end = 8 + 8 + struct.unpack(">I", data[8:12])[0] + 4     # sig + IHDR + crc
    return data[:end] + _text_chunk(SOURCE_KEY, digest.encode("ascii")) + data[end:]


def source_digest(data: bytes) -> str | None:
    """The fingerprint a stamped card carries, or None if it has none."""
    marker = b"tEXt" + SOURCE_KEY + b"\x00"
    at = data.find(marker)
    if at < 0:
        return None
    # The length field precedes the 4-byte type, and counts the chunk's DATA
    # only — so the data runs from `at + 4` to `at + 4 + length`.
    length = struct.unpack(">I", data[at - 4:at])[0]
    value = data[at + len(marker):at + 4 + length]
    return value.decode("ascii", "replace")


def page_digest(page: str) -> str:
    """What the card WOULD be built from, right now."""
    return hashlib.sha256(build_html(page).encode("utf-8")).hexdigest()


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height straight out of the IHDR chunk.

    Worth checking rather than trusting: a headless render that fails its
    viewport still writes a perfectly valid PNG, just the wrong shape, and a
    wrong-shape card is cropped by every platform in a different place.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise OgError("the render did not produce a PNG")
    return struct.unpack(">II", data[16:24])


# How long to wait for the shutter, and how long the file has to stop growing
# before we believe it is complete.
RENDER_TIMEOUT = 120.0
SETTLE_SECONDS = 1.0


def _wait_for_shot(process: subprocess.Popen, shot: Path,
                   timeout: float = RENDER_TIMEOUT) -> bytes:
    """Wait for the PNG, not for Chrome.

    Chrome 152 writes the screenshot and then does not exit — measured here,
    twice, hanging past two minutes with a complete, correct file already on
    disk. Waiting on the process instead of the artefact is what turned a
    working render into a timeout. So: poll for the file, wait for its size to
    stop moving (a half-written PNG is a truncated PNG), then kill the browser
    ourselves.
    """
    deadline = time.monotonic() + timeout
    size = -1
    stable_since = None
    while time.monotonic() < deadline:
        if shot.is_file():
            current = shot.stat().st_size
            if current and current == size:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= SETTLE_SECONDS:
                    return shot.read_bytes()
            else:
                size, stable_since = current, None
        elif process.poll() is not None:
            break                      # exited without ever writing one
        time.sleep(0.25)
    return b""


def render_png(html: str, out: Path, width: int, height: int,
               chrome: str | None = None) -> Path:
    """One headless-Chrome pipeline, shared by every generated image.

    Extracted so render/brand.py cannot grow a second copy of the shutter
    logic — the Chrome-does-not-exit workaround below is exactly the kind of
    hard-won detail that gets fixed in one copy and not the other.
    """
    binary = chrome or find_chrome()
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "page.html"
        source.write_text(html, encoding="utf-8")
        shot = Path(work) / "shot.png"
        process = subprocess.Popen(
            [binary, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--disable-crash-reporter",
             f"--screenshot={shot}", f"--window-size={width},{height}",
             # Every face is embedded, but decoding still has to finish
             # before the shutter, or the image ships in a fallback face and
             # stops looking like the product.
             "--virtual-time-budget=8000",
             "--force-device-scale-factor=1",
             f"--user-data-dir={Path(work) / 'profile'}",
             source.as_uri()],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            data = _wait_for_shot(process, shot)
        finally:
            process.kill()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:      # pragma: no cover
                pass
        if not data:
            detail = (process.stderr.read() or b"").decode("utf-8", "replace")[-400:]
            raise OgError(f"Chrome wrote no screenshot in {RENDER_TIMEOUT:.0f}s. "
                          f"{detail}")

    got = png_size(data)
    if got != (width, height):
        raise OgError(f"rendered {got[0]}x{got[1]}, expected {width}x{height} "
                      f"— the viewport did not take")
    if len(data) > MAX_BYTES:
        raise OgError(f"the image is {len(data)} bytes, over the "
                      f"{MAX_BYTES}-byte ceiling")
    Path(out).write_bytes(data)
    return Path(out)


def render(page: str, out: Path, chrome: str | None = None) -> Path:
    """The social card specifically: render, then stamp its source digest."""
    written = render_png(build_html(page), Path(out), WIDTH, HEIGHT, chrome=chrome)
    written.write_bytes(stamp_source(written.read_bytes(), page_digest(page)))
    return written


def _shown(path: Path) -> str:
    """A path for the log: repo-relative when it is in the repo. --out may
    point anywhere (a scratch render to look at), and printing it must not
    raise after the card has already been written."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------- #
# this week's card (G2): the recorded closest call, as this-week.html's preview
# --------------------------------------------------------------------- #

WEEK_DIR_NAME = "og"
_WEEK_CARD = re.compile(r"^this-week-\d{4}-w\d{2}\.png$")
# The section of this-week.html the card must match, by the heading the
# report prints over it (render.report.section_regret).
_CLOSEST_HEADS = ("The Week&#x27;s Closest Call", "The Week's Closest Call")


def week_card_name(closest: dict) -> str:
    return f"this-week-{closest['season']}-w{int(closest['week']):02d}.png"


def week_card_url(closest: dict) -> str:
    from render.report import SITE_ORIGIN
    return f"{SITE_ORIGIN}/{WEEK_DIR_NAME}/{week_card_name(closest)}"


def week_card_alt(closest: dict) -> str:
    """The card's alt text, said as the card says it."""
    return (f"Week {closest['week']}'s closest call with odds, for a sample roster: "
            f"Start {closest['start']} over {closest['over']}, {closest['pct']}%.")


def _closest_section(page: str) -> str | None:
    for head in _CLOSEST_HEADS:
        at = page.find(head)
        if at >= 0:
            end = page.find("</section>", at)
            return page[at:end if end >= 0 else len(page)]
    return None


def week_card_problems(clock: dict, page: str) -> list[str]:
    """Why this week's card may NOT be drawn ([] when it may): the clock must
    carry a recorded closest call naming its own week (render.live_sample's
    reader rule), not a toss-up (the card would say "start X" where the page
    says "either is fine"), and this-week.html's own closest-call card must
    print the same verdict, percentage and projection — escaped exactly as
    the page escapes them. The card repeats the page or it is not drawn."""
    from render.live_sample import closest_from_clock
    closest = closest_from_clock(clock)
    if closest is None:
        return ["site/week.json carries no recorded closest call for its week"]
    if closest.get("tossup") is not False:
        return ["this week's closest call is a toss-up — the page says either is fine"]
    section = _closest_section(page)
    if section is None:
        return ["this-week.html has no closest-call card"]
    # Each figure as the card prints it: the card stack (contract C3) prints
    # the percentage as <b class="cpct">; a page built before it, which a
    # --restamp leaves in its own markup until Tuesday's rebuild, as
    # <div class="num">. Either is the page's own number.
    need = [(f"Start {html.escape(closest['start'])} <span class=\"over\">over</span> "
             f"{html.escape(closest['over'])}",),
            (f'<b class="cpct">{closest["pct"]}%</b>',
             f'<div class="num">{closest["pct"]}%</div>')]
    if closest.get("proj"):
        need.append((f"proj <b>{html.escape(str(closest['proj']))}</b>",))
    return [f"this-week.html's closest-call card does not print {forms[0]!r}"
            for forms in need if not any(f in section for f in forms)]


def _built_day(clock: dict) -> str | None:
    """'Tue, Oct 20' — the day the page's report was built, in Eastern time."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        built = datetime.fromisoformat(str(clock.get("built_at")).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    local = built.astimezone(ZoneInfo("America/New_York")) if built.tzinfo else built
    return f"{local:%a}, {local:%b} {local.day}"


def _verdict_size(*lines: str) -> int:
    """A font size at which the longer verdict line fits the card on one
    line (Barlow Condensed 900 italic capitals run about half an em wide)."""
    longest = max((len(line) for line in lines), default=1)
    return max(40, min(88, int(1000 / (0.47 * longest))))


def week_card_html(closest: dict, meta: dict) -> str:
    """This week's card: the logo lockup, which week it is, the verdict, the
    odds bar drawn from 50% beside the printed %, the projection chip when
    the page prints one, and where it comes from. Text only — every value is
    the clock's recorded call, escaped."""
    from render.report import mark_svg
    esc = html.escape
    start = f"Start {closest['start']}"
    over = str(closest["over"])
    size = _verdict_size(start, f"over {over}")
    pct = int(closest["pct"])
    width = max(0, min(100, (pct - 50) * 2))
    chip = (f'<span class="chip">proj <b>{esc(str(closest["proj"]))}</b></span>'
            if closest.get("proj") else "")
    built = _built_day(meta)
    foot = ("The closest call with odds, for a sample roster"
            + (f" · built {built}" if built else ""))
    mark = mark_svg("ogw", "ogmark")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<style>{embedded_fonts()}</style>
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;}}
  body{{background:#05090F;color:#F6F4EE;font-family:'Barlow',Arial,sans-serif;
    padding:44px 60px 40px;position:relative;display:flex;flex-direction:column;}}
  body::before{{content:"";position:absolute;inset:0;
    background:radial-gradient(1000px 560px at 80% 30%,rgba(242,194,48,.16),transparent 62%),
               radial-gradient(760px 520px at 4% 100%,rgba(30,122,70,.18),transparent 68%);}}
  .top,.card,.foot{{position:relative;}}
  .top{{display:flex;align-items:center;justify-content:space-between;gap:24px;}}
  .mark{{display:flex;align-items:center;gap:12px;}}
  .mark svg.ogmark{{display:block;width:40px;height:40px;flex:none;margin:0;}}
  .mark span{{font-family:'Barlow Condensed';font-weight:900;font-size:24px;
    font-style:italic;letter-spacing:.01em;text-transform:uppercase;color:#F6F4EE;}}
  .mark span .lg{{color:#F0B62A;}}
  .kicker{{font-family:'Barlow Condensed';font-weight:800;font-size:19px;letter-spacing:.14em;
    text-transform:uppercase;color:#F2C230;border:1.5px solid rgba(242,194,48,.55);
    padding:8px 16px 7px;}}
  .card{{margin:auto 0;background:#F6F4EE;color:#101E33;border:1px solid #D8D3C6;
    box-shadow:0 40px 90px -30px rgba(0,0,0,.9),0 0 0 1px rgba(242,194,48,.22);}}
  .head{{background:linear-gradient(180deg,#182A45,#101E33);color:#F6F4EE;padding:13px 30px;
    font-family:'Barlow Condensed';font-weight:800;font-size:18px;letter-spacing:.16em;
    text-transform:uppercase;display:flex;justify-content:space-between;}}
  .head span{{color:#F2C230;font-size:15px;letter-spacing:.12em;}}
  .body{{padding:22px 30px 22px;}}
  .verdict{{font-family:'Barlow Condensed';font-weight:900;font-style:italic;
    text-transform:uppercase;font-size:{size}px;line-height:.98;white-space:nowrap;}}
  .verdict .over{{color:#5A6B80;font-size:.62em;letter-spacing:.02em;margin-right:.18em;}}
  .conf{{display:flex;align-items:center;gap:26px;margin-top:14px;}}
  .scale{{flex:1;}}
  .bar{{height:18px;background:#EAE7DE;border:1px solid #D8D3C6;}}
  .bar i{{display:block;height:100%;width:{width}%;
    background:linear-gradient(90deg,#D9A81B,#F2C230);}}
  /* The bar starts at 50%, as every bar in the report does: said on it, so a
     reader in a timeline does not read a short bar as a weak call. */
  .ticks{{display:flex;justify-content:space-between;margin-top:6px;font-size:14px;
    font-weight:700;letter-spacing:.06em;color:#5A6B80;}}
  .num{{font-family:'Barlow Condensed';font-weight:900;font-style:italic;font-size:92px;
    line-height:.9;font-variant-numeric:tabular-nums;}}
  .chips{{margin-top:8px;min-height:34px;}}
  .chip{{display:inline-block;font-size:17px;font-weight:800;letter-spacing:.07em;
    text-transform:uppercase;color:#33445C;border:1px solid #D8D3C6;background:#fff;
    padding:6px 12px;}}
  .chip b{{color:#1E7A46;font-variant-numeric:tabular-nums;}}
  .top{{margin-bottom:22px;}}
  .foot{{margin-top:22px;display:flex;justify-content:space-between;align-items:baseline;
    gap:24px;font-size:19px;color:#BCC9DB;font-weight:500;}}
  .foot b{{font-family:'Barlow Condensed';font-weight:800;font-size:24px;letter-spacing:.06em;
    color:#F2C230;}}
</style></head>
<body>
  <div class="top">
    <div class="mark">{mark}<span>Beat Your <span class="lg">League</span></span></div>
    <div class="kicker">This week&#x27;s report · Week {int(closest['week'])} of {esc(str(closest['season']))}</div>
  </div>
  <div class="card">
    <div class="head">The week&#x27;s closest call <span>{esc(str(closest.get('slot') or ''))}</span></div>
    <div class="body">
      <div class="verdict">{esc(start)}<br><span class="over">over</span>{esc(over)}</div>
      <div class="conf"><div class="scale"><div class="bar"><i></i></div>
        <div class="ticks"><span>50%</span><span>100%</span></div></div>
        <div class="num">{pct}%</div></div>
      <div class="chips">{chip}</div>
    </div>
  </div>
  <div class="foot"><span>{esc(foot)}</span><b>beatyourleague.com</b></div>
</body></html>
"""


def week_digest(card_html: str) -> str:
    return hashlib.sha256(card_html.encode("utf-8")).hexdigest()


_TAG = {"og:image": re.compile(r'<meta property="og:image" content="[^"]*">'),
        "og:image:alt": re.compile(r'<meta property="og:image:alt" content="[^"]*">'),
        "twitter:image": re.compile(r'<meta name="twitter:image" content="[^"]*">\n?')}


def with_week_card(page: str, closest: dict | None) -> str:
    """this-week.html's preview tags: the week's card (its absolute URL, its
    alt, and a twitter:image beside them) or, with ``closest`` None, the
    site's own card exactly as render.report.SOCIAL_IMAGE_TAGS states it."""
    from render.report import OG_IMAGE, SOCIAL_IMAGE_TAGS
    generic_alt = re.search(r'og:image:alt" content="([^"]*)"', SOCIAL_IMAGE_TAGS).group(1)
    image = week_card_url(closest) if closest else OG_IMAGE
    alt = html.escape(week_card_alt(closest), quote=True) if closest else generic_alt
    page = _TAG["twitter:image"].sub("", page)
    page = _TAG["og:image"].sub(lambda _m: f'<meta property="og:image" content="{image}">',
                                page, count=1)
    alt_tag = f'<meta property="og:image:alt" content="{alt}">'
    twitter = f'\n<meta name="twitter:image" content="{image}">' if closest else ""
    return _TAG["og:image:alt"].sub(lambda _m: alt_tag + twitter, page, count=1)


def build_week_card(site: Path = SITE, chrome: str | None = None) -> tuple[str, str]:
    """Draw this week's card and point this-week.html at it -> (outcome,
    detail): "written", "current" (already drawn from the same source),
    "refused" or "skipped" (no Chrome, or the render failed). Anything but a
    card that matches the page leaves the page on the site's own card and no
    week card on disk, so a stale week's card can never stand."""
    import json
    site = Path(site)
    page_path = site / "this-week.html"
    folder = site / WEEK_DIR_NAME
    try:
        clock = json.loads((site / "week.json").read_text(encoding="utf-8"))
        page = page_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return "refused", f"site/week.json or this-week.html unreadable ({exc})"
    clock = clock if isinstance(clock, dict) else {}

    def stand_down(outcome: str, detail: str) -> tuple[str, str]:
        _clear_week_cards(folder, keep=None)
        restored = with_week_card(page, None)
        if restored != page:
            page_path.write_text(restored, encoding="utf-8")
        return outcome, detail

    problems = week_card_problems(clock, page)
    if problems:
        return stand_down("refused", "; ".join(problems))
    from render.live_sample import closest_from_clock
    closest = closest_from_clock(clock)
    card = week_card_html(closest, clock)
    digest = week_digest(card)
    out = folder / week_card_name(closest)
    outcome = "current"
    if not (out.is_file() and source_digest(out.read_bytes()) == digest):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            render_png(card, out, WIDTH, HEIGHT, chrome=chrome)
            out.write_bytes(stamp_source(out.read_bytes(), digest))
        except OgError as exc:
            out.unlink(missing_ok=True)
            return stand_down("skipped", str(exc))
        outcome = "written"
    _clear_week_cards(folder, keep=out.name)
    pointed = with_week_card(page, closest)
    if pointed != page:
        page_path.write_text(pointed, encoding="utf-8")
    return outcome, f"{_shown(out)} · {week_card_alt(closest)}"


def _clear_week_cards(folder: Path, keep: str | None) -> None:
    """Delete every week card but ``keep``: only this week's may stand."""
    if not folder.is_dir():
        return
    for old in folder.iterdir():
        if _WEEK_CARD.match(old.name) and old.name != keep:
            old.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--check", action="store_true",
                        help="verify the committed card without rendering")
    parser.add_argument("--week", action="store_true",
                        help="draw this week's card for this-week.html from site/week.json")
    parser.add_argument("--site", default=str(SITE), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.week:
        # Never fails the run: a missing card means the page keeps og.png.
        outcome, detail = build_week_card(Path(args.site))
        if outcome in ("written", "current"):
            print(f"this week's card: {outcome} — {detail}")
        else:
            print(f"::notice::this week's card was not drawn ({outcome}): {detail}. "
                  f"this-week.html keeps the site's own card.")
        return 0

    page = LANDING.read_text(encoding="utf-8")
    out = Path(args.out)

    if args.check:
        if not out.is_file():
            print(f"MISSING {out} — run `make og`", file=sys.stderr)
            return 1
        data = out.read_bytes()
        width, height = png_size(data)
        stale = source_digest(data) != page_digest(page)
        print(f"{_shown(out)}: {width}x{height}, "
              f"{out.stat().st_size:,} bytes, "
              f"{'STALE — run `make og`' if stale else 'current'}")
        return 0 if ((width, height) == (WIDTH, HEIGHT) and not stale) else 1

    rows = hero_rows(page)
    render(page, out)
    print(f"wrote {_shown(out)} "
          f"({out.stat().st_size:,} bytes, {WIDTH}x{HEIGHT})")
    print(f"  headline: {headline(page)}")
    for row in rows:
        figure = row["nocall"] or f'{row["pct"]}%'
        print(f"  {row['slot']:<4} {row['name']:<22} {figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
