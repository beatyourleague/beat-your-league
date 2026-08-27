"""The social preview card — `site/og.png`, generated, never drawn by hand.

Marketing is organic posts on X, so every link we post is rendered as a card.
With no `og:image` that card is a grey box with a domain in it, which reads as a
link somebody is wary of clicking. This is the one asset that is seen by more
people than the site itself.

**The figures on it are READ from the landing page, never typed here.** The hero
file card already quotes the published sample verbatim and a test pins it there
(`test_site.py`, the `.filecard` sweep), so lifting the rows out of the page
inherits that pin: an OG card cannot advertise a number the product stopped
producing. Typing them again would be a third copy of the same four numbers, and
this repo keeps finding that the third copy is the one that goes stale. If the
rows cannot be found the build REFUSES rather than falling back to something
invented — an unfindable card is a missing image, a wrong one is a false claim.

Rendered by headless Chrome because the page is real HTML with the site's own
type and palette, and because the alternatives all lose something: there is no
image library in requirements.txt (adding Pillow to draw one PNG a year is a
dependency we would carry forever), and X does not render SVG previews at all.
The PNG is COMMITTED. GitHub Pages serves it as a static file, so CI never needs
a browser — regeneration is a local, deliberate act, like `make sample`.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
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
# the figures, lifted from the page that is already pinned to the sample
# --------------------------------------------------------------------- #

_ROW = re.compile(
    r'<div class="frow">'
    r'<span class="fslot">([^<]+)</span>'
    r'<span class="fname">([^<]+)</span>\s*'
    r'(?:<span class="fbar"><i style="width:(\d+)%"></i></span>'
    r'<span class="fpct">([\d.]+)%</span>'
    r'<span class="fproj">([\d.]+)</span>'
    r'|<span class="fnc">([^<]+)</span>)',
    re.S)


def hero_rows(page: str) -> list[dict[str, str]]:
    """The hero file card's rows, exactly as the landing page states them.

    Fails closed. A card whose rows we cannot read is not quietly replaced with
    plausible-looking ones: those numbers are the product's own output and
    inventing them here would be the fabrication principle 3 forbids, on the
    single most-forwarded surface we own.
    """
    start = page.find('<div class="filecard">')
    if start < 0:
        raise OgError("no hero file card on the landing page — refusing to "
                      "invent rows for the social card")
    body = page[start:page.find("</div>", page.find('class="fcap"', start))]
    rows: list[dict[str, str]] = []
    for slot, name, width, pct, proj, nocall in _ROW.findall(body):
        rows.append({"slot": slot.strip(), "name": name.strip(),
                     "width": width, "pct": pct, "proj": proj,
                     "nocall": nocall.strip()})
    if not rows:
        raise OgError("the hero file card carried no rows we could read")
    return rows


def headline(page: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if not match:
        raise OgError("no <h1> on the landing page")
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    return html.unescape(" ".join(text.split()))


# --------------------------------------------------------------------- #
# the page
# --------------------------------------------------------------------- #

def _row_html(row: dict[str, str]) -> str:
    slot = html.escape(row["slot"])
    name = html.escape(row["name"])
    if row["nocall"]:
        return (f'<div class="frow"><span class="fslot">{slot}</span>'
                f'<span class="fname">{name}</span>'
                f'<span class="fnc">{html.escape(row["nocall"])}</span></div>')
    return (f'<div class="frow"><span class="fslot">{slot}</span>'
            f'<span class="fname">{name}</span>'
            f'<span class="fbar"><i style="width:{html.escape(row["width"])}%"></i></span>'
            f'<span class="fpct">{html.escape(row["pct"])}%</span></div>')


def build_html(page: str) -> str:
    """The card, in the site's own palette and type."""
    rows = "\n        ".join(_row_html(row) for row in hero_rows(page))
    head = html.escape(headline(page))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:ital,wght@0,600;0,800;0,900;1,900&family=Barlow:wght@400;500;700;800&display=swap">
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;}}
  body{{background:#05090F;color:#F6F4EE;font-family:'Barlow',Arial,sans-serif;
    display:flex;align-items:center;gap:46px;padding:0 60px;position:relative;}}
  /* One warm source of light behind the card, so the paper reads as lit rather
     than pasted on. Same gold as the accent, nothing new introduced. */
  body::before{{content:"";position:absolute;inset:0;
    background:radial-gradient(1100px 620px at 74% 40%,rgba(242,194,48,.14),transparent 62%),
               radial-gradient(760px 520px at 6% 96%,rgba(30,122,70,.16),transparent 68%);}}
  .left{{position:relative;width:556px;flex:none;}}
  .mark{{display:flex;align-items:center;gap:12px;margin-bottom:26px;}}
  .mark i{{display:block;width:44px;height:4px;background:#F2C230;border-radius:2px;}}
  .mark span{{font-family:'Barlow Condensed';font-weight:900;font-size:23px;
    letter-spacing:.2em;text-transform:uppercase;color:#F2C230;}}
  h1{{font-family:'Barlow Condensed';font-weight:900;font-size:92px;line-height:.93;
    letter-spacing:-.005em;text-wrap:balance;}}
  .sub{{margin-top:24px;font-size:26px;line-height:1.42;color:#BCC9DB;font-weight:500;
    max-width:520px;}}
  .sub b{{color:#F6F4EE;font-weight:700;}}
  .right{{position:relative;flex:none;}}
  .filecard{{width:452px;background:#F6F4EE;color:#101E33;border:1px solid #D8D3C6;
    box-shadow:0 40px 90px -28px rgba(0,0,0,.9),0 0 0 1px rgba(242,194,48,.22);
    transform:rotate(1.4deg);}}
  .filehead{{display:flex;justify-content:space-between;align-items:center;gap:10px;
    background:linear-gradient(180deg,#182A45,#101E33);color:#F6F4EE;padding:15px 20px;
    font-family:'Barlow Condensed';font-weight:800;font-size:17px;letter-spacing:.14em;
    text-transform:uppercase;}}
  .filehead span{{color:#F2C230;font-size:13px;letter-spacing:.1em;}}
  .fbody{{padding:8px 20px 16px;}}
  .frow{{display:grid;grid-template-columns:40px 1fr 84px 56px;gap:12px;align-items:center;
    padding:13px 0;border-bottom:1px solid #EDEAE1;font-size:20px;}}
  .frow:last-child{{border-bottom:0;}}
  .fslot{{font-family:'Barlow Condensed';font-weight:800;font-size:17px;color:#5A6B80;
    letter-spacing:.06em;}}
  .fname{{font-weight:700;white-space:nowrap;}}
  .fbar{{height:10px;background:#EDEAE1;border-radius:99px;overflow:hidden;}}
  .fbar i{{display:block;height:100%;border-radius:99px;
    background:linear-gradient(90deg,#D9A81B,#F2C230);}}
  .fpct{{font-family:'Barlow Condensed';font-weight:900;font-style:italic;font-size:25px;
    text-align:right;font-variant-numeric:tabular-nums;}}
  .fnc{{grid-column:3 / 5;font-size:14px;font-weight:700;letter-spacing:.05em;
    color:#5A6B80;text-align:right;text-transform:uppercase;}}
</style></head>
<body>
  <div class="left">
    <div class="mark"><i></i><span>Beat Your League</span></div>
    <h1>{head}</h1>
    <div class="sub">Your lineup, decided every Tuesday — computed from
      <b>your exact roster</b> and your league's scoring.</div>
  </div>
  <div class="right">
    <div class="filecard">
      <div class="filehead">Your lineup · decided <span>Real output</span></div>
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


def render(page: str, out: Path, chrome: str | None = None) -> Path:
    binary = chrome or find_chrome()
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "og.html"
        source.write_text(build_html(page), encoding="utf-8")
        shot = Path(work) / "og.png"
        process = subprocess.Popen(
            [binary, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--disable-crash-reporter",
             f"--screenshot={shot}", f"--window-size={WIDTH},{HEIGHT}",
             # Google Fonts has to arrive before the shutter, or the card ships
             # in Helvetica and stops looking like the product it advertises.
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

    width, height = png_size(data)
    if (width, height) != (WIDTH, HEIGHT):
        raise OgError(f"the card rendered {width}x{height}, expected "
                      f"{WIDTH}x{HEIGHT} — the viewport did not take")
    if len(data) > MAX_BYTES:
        raise OgError(f"the card is {len(data)} bytes, over the "
                      f"{MAX_BYTES}-byte ceiling")
    Path(out).write_bytes(data)
    return Path(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--check", action="store_true",
                        help="verify the committed card without rendering")
    args = parser.parse_args(argv)

    page = LANDING.read_text(encoding="utf-8")
    out = Path(args.out)

    if args.check:
        if not out.is_file():
            print(f"MISSING {out} — run `make og`", file=sys.stderr)
            return 1
        width, height = png_size(out.read_bytes())
        print(f"{out.relative_to(REPO_ROOT)}: {width}x{height}, "
              f"{out.stat().st_size:,} bytes")
        return 0 if (width, height) == (WIDTH, HEIGHT) else 1

    rows = hero_rows(page)
    render(page, out)
    print(f"wrote {out.relative_to(REPO_ROOT)} "
          f"({out.stat().st_size:,} bytes, {WIDTH}x{HEIGHT})")
    print(f"  headline: {headline(page)}")
    for row in rows:
        figure = row["nocall"] or f'{row["pct"]}%'
        print(f"  {row['slot']:<4} {row['name']:<22} {figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
