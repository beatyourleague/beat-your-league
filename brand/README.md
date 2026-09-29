# Beat Your League — logo and brand kit

The logo is a flat gold football on the diagonal, with navy stripes near the
tips and a free-standing check in the middle: *your lineup, decided*.
There is **one** drawing, in `render/report.py` (`mark_svg`, `icon_svg`); every
file below is rendered from it by `make brand`. Never redraw or trace it.

## Which file, where

| Use | File | Notes |
|---|---|---|
| **Default — anything on navy or dark** | `site/brand/mark-gold.svg` | The logo. Use it everywhere you can. |
| **White or cream backgrounds** | `site/brand/mark-light.svg`, `site/brand/logo-light.png` | Deeper gold, so it doesn't wash out. |
| **Small / square spots** — browser tab, phone home screen, Google, social profile picture, Stripe icon | `site/brand/icon.png`, `site/brand/icon.svg`, `site/favicon.*`, `site/apple-touch-icon.png` | The mark on a navy rounded square. |
| **Name + mark** | `site/brand/logo.png` (navy), `site/brand/logo-light.png` (cream) | Stripe invoice header, email signatures, partner pages. |
| **One-colour print on light** — b/w documents, stamps, engraving, one-colour stickers or embroidery | `site/brand/mark-black.svg` | Stripes and check are cut out. |
| **On photos or dark one-colour print** — video watermark, navy t-shirt | `site/brand/mark-white.svg` | Stripes and check are cut out. |

## Rules
- **Flat, always.** No shadows, glows, bevels or gradients baked into the logo.
  If a page wants depth, the page adds it around the logo.
- **Never on a mid-tone or busy background** (grey, a photo, a bright colour) in
  gold — use the white version there.
- Don't stretch, recolour, rotate, outline, or put the check anywhere else.
- Clear space: at least half the mark's width on every side.
- Smallest size: 16px as the icon (navy square); 24px for the bare mark.

## Colours
Navy `#101E33` · logo gold `#F0B62A` · deeper gold for light grounds `#E3A21A` ·
paper `#F6F4EE`. Stripe gets navy as its brand colour, never gold (gold on white
is 1.68:1 — unreadable as a link or under white text).

Regenerate everything with `make brand` (macOS, needs Chrome).
