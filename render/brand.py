"""Brand assets for the surfaces we do not control — `make brand`.

Stripe renders its own invoices, receipts, checkout page and customer portal,
and a buyer sees several of them before they ever see a report. Left at the
defaults those pages carry a grey placeholder and Stripe's own blue, so the
moment somebody pays is the moment the product stops looking like itself.

Two PNGs, because that is what Stripe's branding settings take:

- `icon.png`   square, the football mark alone — the avatar on emails.
- `logo.png`   the mark with the wordmark — the header on invoices.

Rendered from `render/report.py:mark_svg`, the SAME mark every page uses, so
there is no second drawing of the logo to drift from the first. On the navy
ground, because gold on white measures 1.68:1 and is unreadable — see
COLOURS below, which is the palette a human has to paste into Stripe by hand.

Committed like `site/og.png`: generated locally, deliberately, and never in CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from render.og import OgError, find_chrome, png_size, render_png
from render.report import mark_svg

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "site" / "brand"

# The palette, and WHERE each colour may be used. The contrast ratios are
# measured, not judged: WCAG AA wants 4.5:1 for body text and 3:1 for large
# text and UI. Stripe applies these to buttons, links and header bands without
# telling us which is which, so only colours that are safe BOTH ways go in.
#
#   white on navy   16.73:1   safe as a background under white text
#   navy  on paper  15.21:1   safe as text
#   brick on white   5.69:1   safe as text AND as a background
#   navy  on gold    9.98:1   gold is safe ONLY under dark text
#   white on gold    1.68:1   fails
#   gold  on white   1.68:1   fails — never a link colour, never text
#
# So: navy is the brand colour and brick is the accent. Gold stays out of
# Stripe entirely, because the one thing we cannot control there is whether it
# ends up behind white text or as a link on white.
COLOURS = {
    "brand": "#101E33",     # --navy
    "accent": "#B3402F",    # --brick, the site's own link colour on paper
    "paper": "#F6F4EE",
    "gold": "#F2C230",      # brand accent on OUR surfaces; not for Stripe
}

ICON = 512
LOGO_W, LOGO_H = 1024, 256


def _page(body: str, width: int, height: int) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@800;900&display=swap">
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:{width}px;height:{height}px;overflow:hidden;}}
  body{{background:{COLOURS['brand']};display:flex;align-items:center;
    justify-content:center;gap:{int(height * 0.14)}px;}}
  svg.mark{{display:block;}}
  /* nowrap is load-bearing: "Beat Your League" is three words and the first
     render broke it across two lines inside a 4:1 lockup. */
  .word{{font-family:'Barlow Condensed',Arial,sans-serif;font-weight:900;
    color:{COLOURS['paper']};text-transform:uppercase;white-space:nowrap;
    font-size:{int(height * 0.30)}px;letter-spacing:.05em;line-height:1;}}
</style></head><body>{body}</body></html>
"""


def icon_html() -> str:
    mark = mark_svg("bylicon").replace(
        '<svg class="mark"', f'<svg class="mark" width="{int(ICON * 0.72)}"')
    return _page(mark, ICON, ICON)


def logo_html() -> str:
    mark = mark_svg("byllogo").replace(
        '<svg class="mark"', f'<svg class="mark" width="{int(LOGO_H * 0.86)}"')
    return _page(f'{mark}<span class="word">Beat Your League</span>',
                 LOGO_W, LOGO_H)


ASSETS = (("icon.png", icon_html, (ICON, ICON)),
          ("logo.png", logo_html, (LOGO_W, LOGO_H)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)

    if args.check:
        missing = [n for n, _, _ in ASSETS if not (out_dir / n).is_file()]
        if missing:
            print(f"MISSING {', '.join(missing)} — run `make brand`", file=sys.stderr)
            return 1
        for name, _, size in ASSETS:
            got = png_size((out_dir / name).read_bytes())
            print(f"  {name}: {got[0]}x{got[1]}"
                  f"{'' if got == size else f'  EXPECTED {size[0]}x{size[1]}'}")
            if got != size:
                return 1
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    for name, build, (width, height) in ASSETS:
        path = render_png(build(), out_dir / name, width, height, chrome=chrome)
        print(f"wrote {path.relative_to(REPO_ROOT)} "
              f"({path.stat().st_size:,} bytes, {width}x{height})")

    print("\nPaste these into Stripe (Settings -> Business -> Branding):")
    print(f"  Brand color   {COLOURS['brand']}   (navy — white text on it is 16.7:1)")
    print(f"  Accent color  {COLOURS['accent']}   (brick — 5.7:1 as text AND as a ground)")
    print(f"  Logo          site/brand/logo.png")
    print(f"  Icon          site/brand/icon.png")
    print(f"\n  NOT the gold {COLOURS['gold']}: 1.68:1 on white, so if Stripe uses "
          f"it for a link\n  or under white text it is unreadable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
