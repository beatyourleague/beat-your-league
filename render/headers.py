"""site/_headers — the security headers every page is served with, derived
from the pages (SEC-10 / INFRA-04/10/12, pre-launch review Oct 2026).

Usage:
    python -m render.headers            # write site/_headers   (make headers)
    python -m render.headers --check    # fail if it is stale   (the suite does)

The live site sent no HSTS, no Content-Security-Policy, no anti-framing header,
no nosniff and no Referrer-Policy, and could be framed by any page (reproduced
with the live /join/ inside a foreign page). GitHub Pages cannot set response
headers at all, so this file does nothing there; it is Cloudflare Pages' own
format and takes effect the day the site moves (LAUNCH.md, "The repo and the
host"), with no further code change.

What it says:

- On EVERY path (``/*``): HSTS for a year including subdomains (every one is
  HTTPS: forms. is a Worker, send. carries only mail records), nosniff,
  ``strict-origin-when-cross-origin`` (a confirm link's ``?c=`` code never
  leaves in a Referer), a Permissions-Policy that turns off the device APIs no
  page uses, and ``X-Frame-Options: DENY`` for browsers that predate
  ``frame-ancestors``.
- On each PAGE, its own Content-Security-Policy: scripts only from this origin
  plus the exact inline scripts that page carries, by sha256 — so an injected
  script, even one that slipped past escaping, does not run — fetches only to
  this origin and the form Worker, no framing, no plugins, no <base> rewrite.
  Styles keep 'unsafe-inline': pages carry hundreds of style attributes and
  CSSOM writes, and a hash per attribute would make every copy edit a
  security-header edit. Scripts are the part that matters.
- The policy is per page and never on ``/*`` because Cloudflare JOINS two
  matching rules' values for one header with a comma, and two CSPs joined are
  enforced together — the page would get the intersection, i.e. neither
  page's hashes, and every script would stop.

Why not also a ``<meta http-equiv="Content-Security-Policy">`` in each page,
which GitHub Pages WOULD honour today: decided against. A meta policy cannot
carry ``frame-ancestors`` (framing is the one live hazard the review
reproduced), HSTS or any other header here; and it would put a hash inside
every page that must change whenever that page's script changes — the crons
rebuild pages every week and many hands edit them — so one forgotten
regeneration would silently stop the join page's checkout script on the live
site. In ``_headers`` a stale hash is caught by the suite before it ships, and
the crons regenerate this file in the same commit as the pages they rebuild.
"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from render.report import SITE_ORIGIN

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"
OUT = SITE / "_headers"
FORMS_ORIGIN = f"https://forms.{urlparse(SITE_ORIGIN).hostname}"
# Cloudflare Pages' own limits for _headers.
MAX_RULES = 100
MAX_LINE = 2000

COMMON = (
    ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
                           "magnetometer=(), microphone=(), payment=(), usb=()"),
    ("X-Frame-Options", "DENY"),
)
SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
EXECUTABLE_TYPES = {"", "text/javascript", "application/javascript", "module"}


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf'\b{name}\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))', attrs, re.I)
    if not match:
        return None
    return next(g for g in match.groups()[1:] if g is not None)


def inline_scripts(html: str) -> list[str]:
    """The text of every inline script a browser would EXECUTE: no src, and a
    JavaScript type (or none). JSON-LD and other data blocks never run, so
    they need no hash."""
    out = []
    for match in SCRIPT.finditer(html):
        attrs, body = match.group(1), match.group(2)
        if _attr(attrs, "src") is not None:
            continue
        kind = (_attr(attrs, "type") or "").strip().lower()
        if kind in EXECUTABLE_TYPES:
            out.append(body)
    return out


def script_hash(body: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'"


def csp_for(html: str) -> str:
    hashes = sorted(dict.fromkeys(script_hash(b) for b in inline_scripts(html)))
    return "; ".join([
        "default-src 'self'",
        " ".join(["script-src 'self'", *hashes]),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        f"connect-src 'self' {FORMS_ORIGIN}",
        "manifest-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
        "upgrade-insecure-requests",
    ])


def paths_for(page: Path) -> list[str]:
    """Every path Cloudflare Pages may answer this page at: it serves
    ``x.html`` at ``/x`` and ``d/index.html`` at ``/d/`` (redirecting the
    other spelling), so both get the rule."""
    rel = page.relative_to(SITE).as_posix()
    if rel == "index.html":
        return ["/", "/index.html"]
    if rel.endswith("/index.html"):
        return [f"/{rel[:-len('index.html')]}", f"/{rel}"]
    return [f"/{rel[:-len('.html')]}", f"/{rel}"]


def pages() -> list[Path]:
    return sorted(SITE.rglob("*.html"))


def build() -> str:
    lines = ["# GENERATED by `make headers` (render/headers.py) from the pages. Do not edit:",
             "# `python -m render.headers --check` (and the suite) fail when it is stale.",
             "# Cloudflare Pages reads this file; GitHub Pages ignores it.",
             "", "/*"]
    lines += [f"  {name}: {value}" for name, value in COMMON]
    for page in pages():
        policy = csp_for(page.read_text(encoding="utf-8"))
        for path in paths_for(page):
            lines += ["", path, f"  Content-Security-Policy: {policy}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    text = build()
    if check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print("site/_headers is stale: a page's inline script changed. "
                  "Run `make headers` and commit it.", file=sys.stderr)
            return 1
        print("site/_headers is current.")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote site/{OUT.name} ({len(pages())} pages).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
