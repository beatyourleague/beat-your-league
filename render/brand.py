"""Every logo file the business needs — `make brand`.

One drawing of the mark lives in `render/report.py` (`mark_svg`, `icon_svg`,
`mark_file`); everything here is rendered FROM it, so there is no second copy of
the logo to drift from the first. Committed like `site/og.png`: generated
locally, deliberately, and never in CI (it needs a local Chrome, and `sips` on
macOS for the small icon sizes).

What it writes, and where each one is used (the full usage note is
`brand/README.md`):

  site/favicon.svg, site/favicon.ico      browser tab (ico: 16/32/48 for old
                                          browsers and Google's crawler)
  site/apple-touch-icon.png  180          iPhone/iPad home screen
  site/icon-192.png, site/icon-512.png    Android home screen, via the manifest
  site/site.webmanifest                   names the two above
  site/brand/icon.png        512          Google's logo, Stripe's icon, social avatars
  site/brand/logo.png        1024x256     mark + name on navy (Stripe invoice header)
  site/brand/logo-light.png  1024x256     mark + name on cream
  site/brand/mark-{gold,light,black,white}.svg, site/brand/icon.svg
                                          the masters, for print and anyone who asks

Stripe gets NAVY as its brand colour, never gold: gold on white measures
1.68:1, and Stripe decides for itself whether a colour ends up as a link on
white or under white text.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from render.og import find_chrome, png_size, render_png
from render.report import ICON_GROUND, icon_svg, mark_file, mark_svg

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
OUT_DIR = SITE / "brand"

# The palette, and WHERE each colour may be used. The contrast ratios are
# measured, not judged: WCAG AA wants 4.5:1 for body text and 3:1 for large
# text and UI.
#
#   white on navy   16.73:1   safe as a background under white text
#   navy  on paper  15.21:1   safe as text
#   brick on white   5.69:1   safe as text AND as a background
#   navy  on gold    9.98:1   gold is safe ONLY under dark text
#   gold  on white   1.68:1   fails — never a link colour, never text
COLOURS = {
    "brand": "#101E33",     # --navy
    "accent": "#B3402F",    # --brick, the site's own link colour on paper
    "paper": "#F6F4EE",
    "gold": "#F0B62A",      # the logo's gold; not for Stripe
}

ICON = 512
LOGO_W, LOGO_H = 1024, 256
SMALL_ICONS = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}
ICO_SIZES = (16, 32, 48)


def _page(body: str, width: int, height: int, ground: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:ital,wght@1,900&display=swap">
<style>
  *{{margin:0;padding:0;box-sizing:border-box;}}
  html,body{{width:{width}px;height:{height}px;overflow:hidden;}}
  body{{background:{ground};display:flex;align-items:center;justify-content:center;
    gap:{int(height * 0.12)}px;}}
  svg{{display:block;}}
  /* nowrap is load-bearing: "Beat Your League" is three words and an early
     render broke it across two lines inside a 4:1 lockup. */
  .word{{font-family:'Barlow Condensed',Arial,sans-serif;font-weight:900;font-style:italic;
    text-transform:uppercase;white-space:nowrap;font-size:{int(height * 0.34)}px;
    letter-spacing:.01em;line-height:1;}}
</style></head><body>{body}</body></html>
"""


def icon_html(size: int = ICON) -> str:
    """The navy tile, full bleed. The ground is navy too, so the rounded
    corners fill in: iOS and Android round the icon themselves."""
    tile = icon_svg("bi").replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)
    return _page(tile, size, size, ICON_GROUND)


def logo_html(light: bool = False) -> str:
    """Mark + name. Mark at 1.4x the capital height, one letter-width apart."""
    variant, ground, ink, accent = (
        ("light", COLOURS["paper"], "#101E33", "#C98F0E") if light
        else ("gold", COLOURS["brand"], COLOURS["paper"], COLOURS["gold"]))
    mark = mark_svg("bl", "m", variant).replace(
        '<svg class="m"', f'<svg class="m" width="{int(LOGO_H * 0.46)}" '
                          f'height="{int(LOGO_H * 0.46)}"', 1)
    word = (f'<span class="word" style="color:{ink}">Beat Your '
            f'<span style="color:{accent}">League</span></span>')
    return _page(mark + word, LOGO_W, LOGO_H, ground)


ASSETS = (("icon.png", icon_html, (ICON, ICON)),
          ("logo.png", logo_html, (LOGO_W, LOGO_H)),
          ("logo-light.png", lambda: logo_html(light=True), (LOGO_W, LOGO_H)))

MANIFEST = {
    "name": "Beat Your League",
    "short_name": "Beat Your League",
    "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    "theme_color": COLOURS["brand"],
    "background_color": COLOURS["brand"],
    "display": "browser",
}


def ico_bytes(pngs: dict[int, bytes]) -> bytes:
    """A .ico holding PNG images (valid since Windows Vista; every browser and
    Google's favicon crawler read it). No image library needed."""
    sizes = sorted(pngs)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for size in sizes:
        data = pngs[size]
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                               len(data), offset + len(blobs))
        blobs += data
    return header + entries + blobs


def _shrink(src: Path, size: int, dest: Path) -> Path:
    """Downscale with macOS `sips` — a clean resample from the 512 render.
    Chrome refuses windows narrower than ~500px, so small sizes cannot be
    rendered directly."""
    if not shutil.which("sips"):
        raise SystemExit("`sips` not found — small icon sizes are made on macOS")
    subprocess.run(["sips", "-z", str(size), str(size), str(src), "--out", str(dest)],
                   check=True, capture_output=True)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    expected = ([(OUT_DIR / n, size) for n, _, size in ASSETS]
                + [(SITE / n, (s, s)) for n, s in SMALL_ICONS.items()])
    if args.check:
        bad = 0
        for path, size in expected:
            if not path.is_file():
                print(f"MISSING {path.relative_to(REPO_ROOT)} — run `make brand`",
                      file=sys.stderr)
                bad += 1
                continue
            got = png_size(path.read_bytes())
            print(f"  {path.relative_to(REPO_ROOT)}: {got[0]}x{got[1]}")
            bad += got != size
        for path in (SITE / "favicon.ico", SITE / "favicon.svg", SITE / "site.webmanifest"):
            if not path.is_file():
                print(f"MISSING {path.relative_to(REPO_ROOT)}", file=sys.stderr)
                bad += 1
        return 1 if bad else 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    for name, build, (width, height) in ASSETS:
        path = render_png(build(), OUT_DIR / name, width, height, chrome=chrome)
        print(f"wrote {path.relative_to(REPO_ROOT)} ({width}x{height})")

    master = OUT_DIR / "icon.png"
    for name, size in SMALL_ICONS.items():
        dest = SITE / name
        if size == ICON:
            dest.write_bytes(master.read_bytes())
        else:
            _shrink(master, size, dest)
        print(f"wrote {dest.relative_to(REPO_ROOT)} ({size}x{size})")
    with tempfile.TemporaryDirectory() as tmp:
        pngs = {s: _shrink(master, s, Path(tmp) / f"{s}.png").read_bytes()
                for s in ICO_SIZES}
    (SITE / "favicon.ico").write_bytes(ico_bytes(pngs))
    (SITE / "favicon.svg").write_text(icon_svg("fi", standalone=True) + "\n")
    (SITE / "site.webmanifest").write_text(json.dumps(MANIFEST, indent=2) + "\n")
    (OUT_DIR / "icon.svg").write_text(icon_svg("ki", standalone=True) + "\n")
    for variant in ("gold", "light", "black", "white"):
        (OUT_DIR / f"mark-{variant}.svg").write_text(mark_file(variant))
    print("wrote site/favicon.ico (16/32/48), site/favicon.svg, site/site.webmanifest,"
          " site/brand/*.svg")

    print("\nStripe (Settings -> Business -> Branding):")
    print(f"  Brand color   {COLOURS['brand']}   Accent color  {COLOURS['accent']}")
    print("  Icon          site/brand/icon.png     Logo  site/brand/logo.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
