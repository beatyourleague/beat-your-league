"""Render ``week_report.json`` into the v2 report design.

Usage:
    python -m render.report [--input data/processed/week_report.json] [--output PATH]

The design is not re-implemented here: the ``<style>`` block and font links are
lifted verbatim from ``rival-report-template.html`` at render time, so the
template file stays the single source of the product's look. This module only
generates the *content* markup, using the template's own class names.

Two rules enforced throughout (CLAUDE.md security + principle 3):
- Every data-derived string passes through ``html.escape`` — fetched data is
  untrusted and flows into markup escaped, never executed.
- A gap in the JSON (``*_gate`` / ``meta.gaps``) renders as an explicit
  *coming in v0.3* marker. The renderer never fills a hole with a plausible
  number; it can only display what the engine computed.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ingest.nflverse import ATTRIBUTION

REPO_ROOT = Path(__file__).resolve().parent.parent

# What every HTML email's <head> carries beyond charset/viewport. Apple Mail
# and Outlook.com invert an email that doesn't say it handles both colour
# schemes, turning the navy header and gold rules into something nobody
# designed; these tell them the email is light-only, and stop iOS reflowing it.
EMAIL_META = (
    '<meta name="color-scheme" content="light only">\n'
    '<meta name="supported-color-schemes" content="light only">\n'
    '<meta name="x-apple-disable-message-reformatting">\n'
    '<meta name="format-detection" content="telephone=no,date=no,address=no,email=no">\n')


# What a generated report PAGE's <head> carries (samples, the live sample, a
# subscriber's archive, the roster report). The pages are paper-light by
# design and said nothing, so a phone in dark mode drew dark native scrollbars
# and controls over a cream page and Safari left its bar untinted (launch
# review I12, Oct 2026). Light only, and the masthead's navy for the bar.
PAGE_META = ('<meta name="color-scheme" content="light">\n'
             '<meta name="theme-color" content="#101E33">\n')

# The faces above the fold on every report page: the masthead's condensed
# display face and the body face. Preloaded so the first paint already has
# them; read out of fonts.css rather than named here, so the filenames live in
# one place (site/fonts/fonts.css) and a renamed file cannot leave a preload
# fetching a 404 beside the real one.
FONTS_CSS = REPO_ROOT / "site" / "fonts" / "fonts.css"
PRELOAD_FACES = (("Barlow Condensed", "800"), ("Barlow", "400"))


def font_preloads(css_path: Path | None = None) -> str:
    """<link rel="preload"> tags for PRELOAD_FACES, page-relative like the
    stylesheet link the template carries. Empty when fonts.css is absent or
    names neither face: a preload is an optimisation, never a dependency."""
    path = css_path or FONTS_CSS
    try:
        css = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    found: dict[tuple[str, str], str] = {}
    for block in re.findall(r"@font-face\s*{([^}]*)}", css):
        family = re.search(r"font-family\s*:\s*['\"]?([^;'\"]+)", block)
        weight = re.search(r"font-weight\s*:\s*(\d+)", block)
        style = re.search(r"font-style\s*:\s*(\w+)", block)
        src = re.search(r"url\(\s*['\"]?([^'\")]+\.woff2)['\"]?\s*\)", block)
        if not (family and weight and src) or (style and style.group(1) != "normal"):
            continue
        key = (family.group(1).strip(), weight.group(1))
        url = src.group(1).strip()
        if not url.startswith(("/", "http:", "https:")):
            import posixpath
            url = posixpath.normpath(posixpath.join("fonts", url))
        found.setdefault(key, url)
    return "".join(
        f'<link rel="preload" href="{esc(found[face])}" as="font" '
        f'type="font/woff2" crossorigin>\n'
        for face in PRELOAD_FACES if face in found)


def preheader_html(text: str) -> str:
    """The inbox preview line, padded. Without the filler an inbox continues
    the preview into whatever comes next in the body ("BEAT YOUR LEAGUE WEEK
    4…"), which reads as clutter where the promise should be."""
    return ('<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;'
            'font-size:1px;line-height:1px;color:#F6F4EE;">'
            f'{esc(text)}{"&#847;&zwnj;&nbsp;" * 90}</div>\n')


# Slot codes are the engine's identifiers ("SUPER_FLEX"); a buyer reads the
# name their league app uses. Translated once, at every surface's OUTPUT, so
# the code keeps meaning one thing everywhere it is compared (eligibility, the
# ledger, the Saturday plan) and no internal spelling reaches an inbox — the
# proving run found "SUPER_FLEX" breaking the plain-text table's columns.
SLOT_DISPLAY = {"SUPER_FLEX": "SFLEX", "WRRB_FLEX": "W/R", "REC_FLEX": "W/T",
                "IDP_FLEX": "IDP"}


def buyer_slots(fn):
    """Decorator: a renderer's text, with every internal slot code named."""
    import functools

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        out = fn(*args, **kwargs)
        for code, name in SLOT_DISPLAY.items():
            out = out.replace(code, name)
        return out
    return wrapped
TEMPLATE_PATH = REPO_ROOT / "rival-report-template.html"
# What a withheld number says to a BUYER. Version numbers, file paths and cost
# telemetry are operator vocabulary and never appear in a report someone paid
# for — a customer reading "v0.3" reasonably concludes they bought unfinished
# software, when the truth is the opposite: we refuse to print what we can't
# stand behind.
NO_CALL = "no call"          # in a tight column
NOT_CALLING_IT = "Heads up"   # as a label above the reason

# The logo mark, single-sourced (redrawn Sep 29 2026, owner-approved after three
# rounds). A flat gold football on the 45-degree diagonal, two navy stripes set
# in from the tips — the one cue only a football has — and a free-standing check
# in the middle: "your lineup, decided". Rules the drawing keeps:
#   * FLAT. No gradients, shadows or highlights: they die at 16px and cannot be
#     printed in one colour. Depth, where wanted, is added by the page around it.
#   * The check touches nothing. It stands clear of both stripes and the edge,
#     so it reads as a tick at a glance.
#   * Stripes and check share one stroke weight (4.0 on the 64 grid).
#   * Tips softly blunted (a same-colour stroke with a round join), so they
#     survive being rasterised small.
#   * A clear gold tip shows beyond each stripe; without it the ball reads as a
#     capsule.
# Variants: "gold" (dark grounds, the default), "light" (a deeper gold for white
# and cream), "black" and "white" (one-colour print, stripes and check cut out).
# ``uid`` namespaces the clip/mask ids so several marks can share a document.
MARK_PATH = "M-26.5 0A33.5 33.5 0 0 1 26.5 0A33.5 33.5 0 0 1-26.5 0Z"
# The stroked lens's true outline: two r=35 arcs, used to clip the stripes.
_MARK_CLIP = "M-28.37 0A35 35 0 0 1 28.37 0A35 35 0 0 1-28.37 0Z"
_MARK_FRAME = "translate(32 32) rotate(-45)"
_MARK_CHECK = "M24.3 31.7l5.5 5.5 10.7-11.2"
_MARK_STRIPES = ('<rect x="-19.5" y="-20" width="4" height="40" transform="{f}"/>'
                 '<rect x="15.5" y="-20" width="4" height="40" transform="{f}"/>')
MARK_COLOURS = {
    "gold": ("#F0B62A", "#101E33"),
    "light": ("#E3A21A", "#101E33"),
    "black": ("#000000", None),
    "white": ("#FFFFFF", None),
}
ICON_GROUND = "#101E33"


def _mark_body(uid: str, variant: str) -> str:
    """The drawing on the 64-unit grid, without the <svg> wrapper."""
    ball, ink = MARK_COLOURS[variant]
    lens = (f'<path d="{MARK_PATH}" transform="{_MARK_FRAME}" fill="{ball}" '
            f'stroke="{ball}" stroke-width="3" stroke-linejoin="round"/>')
    stripes = _MARK_STRIPES.format(f=_MARK_FRAME)
    check = (f'<path d="{_MARK_CHECK}" fill="none" stroke-width="4" '
             f'stroke-linecap="round" stroke-linejoin="round"')
    clip = (f'<clipPath id="{uid}Clip"><path d="{_MARK_CLIP}" '
            f'transform="{_MARK_FRAME}"/></clipPath>')
    if ink:
        return (f'<defs>{clip}</defs>{lens}'
                f'<g clip-path="url(#{uid}Clip)" fill="{ink}">{stripes}</g>'
                f'{check} stroke="{ink}"/>')
    # One colour: the stripes and the check are CUT OUT of the ball, so the
    # ground shows through them — the same shape in any single ink.
    return (f'<defs>{clip}<mask id="{uid}Knock"><rect width="64" height="64" '
            f'fill="#fff"/><g clip-path="url(#{uid}Clip)" fill="#000">{stripes}'
            f'</g>{check} stroke="#000"/></mask></defs>'
            f'<g mask="url(#{uid}Knock)">{lens}</g>')


def mark_svg(uid: str = "byl", klass: str = "mark", variant: str = "gold") -> str:
    """The football mark as standalone inline SVG. Decorative: the wordmark
    beside it carries the name, so this is aria-hidden."""
    return (f'<svg class="{klass}" viewBox="0 0 64 64" aria-hidden="true" '
            f'focusable="false">{_mark_body(uid, variant)}</svg>')


def icon_svg(uid: str = "bylt", standalone: bool = False) -> str:
    """The small-size form: the gold mark on a navy rounded square, enlarged to
    fill it. For the browser tab, phone home screens, Google's result icon and
    Stripe — places where a floating tilted ball would look tiny."""
    xmlns = ' xmlns="http://www.w3.org/2000/svg"' if standalone else ""
    return (f'<svg{xmlns} viewBox="0 0 64 64"><rect width="64" height="64" '
            f'rx="14" fill="{ICON_GROUND}"/><g transform="translate(32 32) '
            f'scale(1.04) translate(-32 -32)">{_mark_body(uid, "gold")}</g></svg>')


def mark_file(variant: str) -> str:
    """A standalone .svg file of the mark, for the brand kit."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'{_mark_body("m", variant)}</svg>\n')


# The tab icon. A deliberately bolder cut of the mark — at 16px the lockup's
# gradients and hairlines vanish — and NOT an emoji, which the OS renders so
# the most repeated brand impression would differ per visitor.
# The social preview card. Every buyer-facing page points at ONE image, and the
# per-page og:title is what differentiates them — a second card would be a second
# thing to regenerate, for a difference nobody scrolling X would notice.
#
# The origin is stated here rather than read from SITE_URL because these pages
# are GENERATED AND COMMITTED: an env var that happened to be unset during a
# regeneration would silently strip the tag from every page, and a preview image
# that quietly stops appearing is exactly the failure nobody notices. A test ties
# this to site/CNAME, which is the domain GitHub Pages actually serves, so the two
# cannot drift.
SITE_ORIGIN = "https://beatyourleague.com"
OG_IMAGE = f"{SITE_ORIGIN}/og.png"

# summary_large_image, not summary: `summary` renders a small square thumbnail
# and crops a 1.91:1 card to a stamp, which throws away the file card that is the
# whole point of having an image.
# The grading pages stay public and unlinked from anything that sells, and
# out of search results (owner direction, Sep 29 2026).
NOINDEX_TAG = '<meta name="robots" content="noindex">\n'

SOCIAL_IMAGE_TAGS = (
    '<meta name="twitter:card" content="summary_large_image">\n'
    f'<meta property="og:image" content="{OG_IMAGE}">\n'
    '<meta property="og:image:width" content="1200">\n'
    '<meta property="og:image:height" content="630">\n'
    '<meta property="og:image:alt" content="A Beat Your League lineup report: '
    'four roster slots, three with a percentage, one marked questionable.">\n'
)

FAVICON_LINK = ('<link rel="icon" href="/favicon.ico" sizes="32x32">\n'
                '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
                '<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
                '<link rel="manifest" href="/site.webmanifest">')

# Every surface that shows the wordmark styles the mark the same way.
MARK_CSS = (".brand svg.mark{width:22px;height:22px;flex:none;}"
            ".brand{display:inline-flex;align-items:center;gap:9px;}")

# Sentences shared verbatim between the browser report (this module) and the
# email digest (render/email.py). Single-sourced so the pinned consumer
# protections and the buyer voice cannot drift apart between the two surfaces.
# Updated Aug 18 2026 with the Sleeper decision (PLAN §0). The old line —
# "built around your rival, not just your roster" — described a product that
# read the league and tracked a named opponent. Neither is true any more, and
# this constant renders in the report footer, the email footer AND the launch
# announcement, so a stale promise here is a false claim on every surface at
# once.
BRAND_LINE = ("the weekly scouting report for your fantasy roster, "
              "every Tuesday of the season.")
NO_BETTING_LINE = ("Projections are analysis, not guarantees — no betting "
                   "picks, no staking advice. Fantasy decisions are yours to make.")
SLEEPER_LINE = ("Built from your league's own record on Sleeper. "
                "Not affiliated with Sleeper or the NFL.")
# RULE N1: CC-BY-4.0 grants commercial use IN EXCHANGE FOR attribution, so this
# is a licence term rather than a courtesy — ingest/nflverse.py says it is
# "rendered on every report and every public page", and until now no report
# rendered it at all. Both renderers printed the Sleeper line instead, which on
# a solo report credits a source the run never touched while omitting the one
# whose grant the product depends on.
NFLVERSE_LINE = ATTRIBUTION + " Not affiliated with the NFL."


def source_line(meta: Mapping[str, Any]) -> str:
    """Where this report's numbers came from.

    Solo reports are built entirely from nflverse (PLAN §0); the historical
    demo and the backtest still run on the league record they were always built
    from, and keep the Sleeper disclaimer that goes with it.
    """
    return NFLVERSE_LINE if meta.get("solo") else SLEEPER_LINE
CANCEL_HEAD = "Done with this?"
# What cancelling does to the reports. Terms §4 keeps access to the end of the
# period already paid for, and run/subscriptions.py keeps a cancel_at_period_end
# subscription entitled until then — so the text half's old "the reports stop
# on their own once you do" was false for every cancel (launch audit C13,
# Oct 15 2026). One sentence: in CANCEL_BODY (so every surface that prints
# it), the text half's CANCEL_TEXT, and the welcome.
CANCEL_PERIOD = ("Reports continue to the end of the period you've already "
                 "paid for, then stop.")
# The real flow (launch audit L4): Stripe's billing page emails a sign-in LINK,
# and the whole thing takes about a minute — "fifteen seconds" and "a sign-in
# code" were misstatements of how the reader gets out.
# Names only what the block links (COPY:F14): "the exact steps are on our
# terms page" rode every paid footer while the only link was the billing
# page, and on the public samples nothing was linked at all. The steps are
# given right here; the link after the body (cancel_html) is the one place
# named, and on a sample it is the terms page's steps.
# D3 (owner decision, Oct 18 2026): Stripe's billing page, opened by email,
# shows only the NEWEST customer at that address, so the older of two
# subscriptions on one address can't be reached there. That one case is the
# only time a subscriber needs us to stop a charge, and every cancel route says
# so — terms §3 carves out exactly this.
TWO_PURCHASES = ("Bought twice with one email? Your billing page shows only the "
                 "newest purchase, so reply to any of our emails and we'll "
                 "cancel the older one for you.")
CANCEL_BODY = ("Cancel it yourself from your own billing page — enter your email, "
               "open the link Stripe sends, press Cancel. About a minute, and no "
               "further charges. "
               "Unsubscribing from emails alone does not stop a subscription, "
               "so cancel there if you want the charges to end. " + CANCEL_PERIOD
               + " " + TWO_PURCHASES)
# The plain-text half's own wording of the same block (it shouts the NOT,
# because a text client has no bold to carry it).
CANCEL_TEXT = ("DONE WITH THIS? Cancel it yourself from your own billing page — "
               "enter your email, open the link Stripe sends, press Cancel. About "
               "a minute, and no further charges. Note that unsubscribing from "
               "emails alone does NOT stop a subscription; cancel there if you "
               "want the charges to end. " + CANCEL_PERIOD + " " + TWO_PURCHASES)
# A League Pass SEAT pays nothing and has no Stripe subscription, yet every
# surface sent it to a billing page where its address finds no customer — the
# welcome, every weekly footer, the Saturday check and the List-Unsubscribe
# header (launch audit C4, Oct 15 2026). A seat had no working way out at all,
# in an email that also said "nothing bills you for this seat, ever". Its way
# out is the one any unpaid reader has: say stop, and the address goes on the
# suppression list run/delivery.py checks before every send (run/suppress.py).
# Ten business days is CAN-SPAM's ceiling. The operator is in this loop only
# because no money is: a PAID subscription still cancels itself.
# "Your league's pass", never "your commissioner's": any manager may buy the
# League Pass (league-pass.html), and a seat told it belongs to the
# commissioner's pass goes looking for the wrong person (panel review LP-D7).
SEAT_STOP_BODY = ("Reply \"stop\" to any of our emails, or use your mail app's "
                  "unsubscribe — you're off within 10 business days. Your "
                  "league's pass isn't affected.")
# On a registry row, and so in a report's meta["plan"] (run/tuesday.py), this
# word means a SEAT; the pass PAYER is "pass" (PASS_PLAN below — before Oct
# 2026 a payer's row was flattened to "season"). The welcome email has its own
# vocabulary, where a seat is "seat" and "league_pass" is the payer — so the
# helpers below take a yes/no, never a plan word that means opposite things in
# two places.
SEAT_PLAN = "league_pass"
# A ONE-TIME pass (the 2026 rest-of-season passes) has no subscription either:
# nothing renews, so there is nothing to cancel, and "cancel from your billing
# page" would send its buyer looking for a charge that will never come. Its way
# out is the seat's: say stop.
ONCE_STOP_BODY = ("Nothing renews and nothing more is charged: your pass covers "
                  "this season and ends on its own. To stop the emails before "
                  "then, reply \"stop\" to any of our emails, or use your mail "
                  "app's unsubscribe — you're off within 10 business days.")
ONCE = "once"
# What the site sells this season (owner decision, Oct 18 2026): one-time
# passes. Flip with the payment links when subscriptions return (2027).
SELLING_ONE_TIME = True


def is_seat(meta: Mapping[str, Any]) -> bool:
    """A weekly report addressed to a League Pass seat holder."""
    return meta.get("plan") == SEAT_PLAN


def stop_route(meta: Mapping[str, Any]) -> "bool | str":
    """Which way out a report's footer gives: True for a seat, ``ONCE`` for a
    one-time pass's own buyer, False for a subscription (its billing page)."""
    if is_seat(meta):
        return True
    # A published sample shows what a buyer gets today, and 2026 sells only
    # one-time passes (SELLING_ONE_TIME): its footer is the one-time way out.
    if meta.get("anonymized_demo") and SELLING_ONE_TIME:
        return ONCE
    return ONCE if meta.get("one_time") else False


def seat_stop_href() -> str:
    """The seat's List-Unsubscribe target: a stop request to the inbox that
    reads it. mailto, so it works with no endpoint of ours."""
    from render.sender import CONTACT
    return f"mailto:{CONTACT}?subject=stop"


def unsubscribe_target(seat: bool = False) -> str | None:
    """The List-Unsubscribe header for a report or a Saturday check. For a
    PAID subscription unsubscribing and cancelling are the same act, so it is
    where the money stops; a seat has no money to stop."""
    if seat:
        return seat_stop_href()
    return cancel_destination()[0] or None


def cancel_html(seat: bool = False, link_style: str = "", sample: bool = False) -> str:
    """The footer's way out, as an HTML fragment — one block, every surface.
    No mailto anchor for a seat: every href in an email is https
    (tests/test_email_safety.py), and "reply" needs no link.

    ``sample``: a published sample page, which sits beside terms.html on the
    site and is built with no billing portal or site address configured. It
    printed the whole block with no link at all (COPY:F14); it links the
    steps, relative, so the page it names is one a reader can open."""
    if seat == ONCE:
        return f'<b>{esc(CANCEL_HEAD)}</b> {esc(ONCE_STOP_BODY)}'
    if seat:
        return f'<b>{esc(CANCEL_HEAD)}</b> {esc(SEAT_STOP_BODY)}'
    href, label = cancel_destination()
    if not href and sample:
        href, label = SAMPLE_CANCEL_HREF, CANCEL_STEPS_LABEL
    style = f' style="{link_style}"' if link_style else ""
    return (f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}'
            + (f' <a href="{esc(href)}"{style}>{esc(label)}</a>.' if href else ""))


def cancel_lines(seat: bool = False) -> list[str]:
    """The plain-text twin. The route is spelled out as a URL because a text
    half cannot carry an anchor (found Aug 24 2026: the footer promised a
    cancel with no way to reach it, on either half)."""
    if seat == ONCE:
        return [f"{CANCEL_HEAD.upper()} {ONCE_STOP_BODY}"]
    if seat:
        return [f"{CANCEL_HEAD.upper()} {SEAT_STOP_BODY}"]
    href, label = cancel_destination()
    return ([f"CANCEL: {label} — {href}", ""] if href else []) + [CANCEL_TEXT]


def sender_html() -> str:
    """Who sent this, with a postal address once one is configured (CASL and
    CAN-SPAM identification; render/sender.py). Empty until then."""
    from render.sender import sender_line
    line = sender_line()
    return f"{esc(line)}<br>" if line else ""


def cancel_destination() -> tuple[str, str]:
    """(href, label) for the self-serve cancel route — one route, every surface.

    Lived in render/welcome.py, so the WEEKLY report — ~18 emails a season
    against the welcome's one — told every subscriber the steps were "on our
    legal page" and never linked it, on either half. Found Aug 24 2026 by
    reading a delivered draft: the HTML carried exactly one href, the roster
    update link. A promise to make cancelling easy, made eighteen times, with
    no way to act on it.
    """
    portal = os.environ.get("BILLING_PORTAL_URL", "").strip()
    if portal:
        return portal, "your billing page"
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if site:
        return f"{site}/terms.html#cancel", CANCEL_STEPS_LABEL
    return "", ""


CANCEL_STEPS_LABEL = "the exact steps, on our terms page"
# A published sample sits at the site root beside terms.html.
SAMPLE_CANCEL_HREF = "terms.html#cancel"


AS_SET_HEAD = "Your lineup, exactly as set."
AS_SET_BODY = ("Start-sit calls begin once your league has box scores to "
               "compare against — from next week, this grid shows the lineup "
               "we would set and why.")


def no_call_explainer(listed: str) -> str:
    """Why gated slots say "no call" — one definition, both renderers.

    Grade C of the frozen method (reports/nflverse-backtest-method.md §1):
    the definition stays, "every one goes on the public record and gets
    graded" stays, and the old closing clause — "otherwise we'd be guessing,
    and you can guess for free" — is gone, because it asserted that a shown
    number is not a guess, which is exactly the claim the grade withholds.

    "When both players are confirmed to play" overstated what a Tuesday report
    can know (launch review SS-D1): the live sample printed it above odds
    against a practice-squad player. The sentence now names what the gate
    checks — both teams play, and neither player carried a designation on last
    week's injury report. "Only when": the live week's extra checks (reserve
    lists, the practice squad) only ever withhold more.
    """
    return (f"The % is the chance your starter outscores your best bench "
            f"player at that spot, and the bar starts at 50% (a toss-up). We only "
            f"give odds when both players' teams play this week and neither was "
            f"listed questionable, doubtful or out last week. Rows without "
            f"odds this week: {listed}.")


# §5 of the early-season method (Grade B): the seed moves every number in the
# lineup — seating, projections, edges — not only the calls that carry a
# row-level flag, so the section says so once, in the buyer's words.
# "Three weeks in, the numbers stand on this season alone" was false: in
# weeks 4-16 the anchor (reports/anchor-method.md) still counts a player's own
# last season, at half the early-season weight, with no row flag (EMAILS-27).
SEEDED_SECTION_LINE = ("This early in the season, last season is counted into "
                       "every number here; each call that leans on it says so "
                       "on its row. From Week 4 it counts for less and isn't "
                       "flagged row by row; from Week 17 this season stands "
                       "alone.")


# A gate is STRUCTURAL when it would print identically every week for this
# roster: the QB slot with no backup quarterback, the kicker with no backup
# kicker, the defense the model does not score yet. It states the shape of the
# lineup, not anything about this week, so after the first read it carries no
# information. A CONTINGENT gate — "status unconfirmed", "too few games yet" —
# is the honesty feature doing its job: we could have called this slot and held
# back for a reason specific to this player, this week.
#
# Measured on the published sample (Aug 24 2026): SIX of nine rows read
# "no call" and THREE of those six were structural, so the three genuine
# holds — and the three real calls — read as a table full of refusals. Both
# kinds are still explained in full in the note under the table; what changes
# is which ones spend a row. This is the same rule the mixed-week test already
# applies: a marker that says nothing the note does not say once has not
# earned a row of its own.
STRUCTURAL_GATES = ("nobody on your bench", "no eligible player")


def is_structural_gate(gate: str | None) -> bool:
    """True when this gate is a permanent fact about the roster's shape."""
    return bool(gate) and gate.startswith(STRUCTURAL_GATES)


def no_call_head(shown_any_marker: bool, mixed: bool) -> str:
    """The note's opening, matched to what the rows above it actually show.

    Three states, because there are three: some rows carry a marker; calls
    were published but every withheld slot was structural (no markers at all);
    or nothing was called this week.
    """
    if shown_any_marker or mixed:
        return "How to read the odds."
    return "No odds this week."


# The reasons a slot carries no odds, in the buyer's words. The engine's own
# strings are precise and stay precise (the ledger and tests read them); this is
# only how a reader is told. Order matters: first match wins.
_GATE_PHRASES = (
    # Dated (launch audit F5): the designation is LAST week's report — the
    # only one out on a Tuesday — and "is questionable" stated it as this
    # week's news, including about players who had played through it.
    ("availability in doubt", "one of the two players was questionable last week"),
    ("not a live head-to-head", "one of the two players is out"),
    # Launch audit F11: the bench HAS a player there, out or not yet cleared;
    # "no bench player at that position" sat beside his bench row.
    ("bench option not cleared", "your bench player at that position isn't cleared to play"),
    # Method §15 C9: the practice squad plays only if elevated.
    ("not confirmed to play", "a player in that pair is on the practice squad"),
    ("held: the lineup changed", "the lineup changed around a player who can't play this week"),
    # D11: a later flex swap started the player the odds were figured against.
    ("held: the bench changed",
     "a flex swap changed who your best bench player there is"),
    # A graded lineup whose week lacked an input its arm's model needs.
    ("held: an input", "odds are held this week: something they need didn't come in"),
    ("nobody on your bench", "no bench player at that position"),
    ("not enough games", "not enough games played yet"),
    ("we don't put odds on defenses", "defenses get a projection only"),
    ("no eligible player", "no eligible player with a scoring record"),
    # Week 1 (panel review RQ2-02): the note read "a player's status isn't
    # confirmed yet" above a lineup with no injury report to be confirmed by —
    # the true reason is that nobody has played.
    ("no game record yet", "nobody has played a game this season yet"),
    # Contract C8: a lineup shape no preregistered arm has graded prints no
    # odds at all. Without its own phrase it fell through to "a player's
    # status isn't confirmed yet" — false about a confirmed starter.
    ("odds once this lineup shape is graded",
     "your lineup shape hasn't been graded yet, so it carries no odds"),
)


def gate_phrase(gate: str) -> str:
    """One engine gate reason, as the note under the lineup states it."""
    for prefix, phrase in _GATE_PHRASES:
        if gate.startswith(prefix):
            return phrase
    # Anything else is an availability reason from engine/availability.py
    # (no report yet, bye status unknown): the player's status is open.
    return "a player's status isn't confirmed yet"


def gate_list(gates) -> str:
    """The note's list of reasons: phrased, de-duplicated, stable order."""
    return " · ".join(sorted({gate_phrase(g) for g in gates}))


def row_label(slot: Mapping[str, Any]) -> str:
    """What a lineup row without odds says in its call column.

    It says what is TRUE of this row. The old label, "no call · status
    unconfirmed", printed on Saquon Barkley in the published sample when the
    doubt was about his bench alternative, Tony Pollard (listed Questionable):
    Barkley was confirmed and was the start either way, and the row read as if
    he were the problem. So: when the starter is confirmed, the row says start,
    and names who is in doubt.
    """
    gate = slot.get("confidence_gate") or ""
    alt = slot.get("alternative_name")
    starter_ok = slot.get("status") == "active"
    # Only a row whose player the if/then actually names may send the reader
    # there (launch audit R7). Reports built before the field existed, and the
    # league product, keep the old wording.
    see = " · see if/then" if slot.get("if_then", True) else ""
    # C8: a shape-level reason is never about this row's players — "waiting
    # on" a bench player whose news decides nothing would be a false reason.
    if gate.startswith(("we don't put odds on defenses",
                        "odds once this lineup shape is graded",
                        "held: an input")):
        return "projection only"
    if gate.startswith("not enough games"):
        # Name who is short (launch audit F11): "odds after 3 games" sat beside
        # a starter with five games and a usage line counting four of them —
        # the short record was his bench alternative's.
        short = list(slot.get("short_games") or [])
        if len(short) == 1:
            return f"odds once {short[0]} has 3 games"
        if len(short) == 2:
            return "odds once both have 3 games"
        return "odds after 3 games"
    if gate.startswith("bench option not cleared"):
        held = slot.get("bench_held") or {}
        name = held.get("name") or "your bench player"
        return {"bye": f"{name} on bye", "roster": f"{name} can't play"}.get(
            held.get("kind"), f"{name} not cleared yet")
    if gate.startswith("not confirmed to play"):
        # Method §15 C9: "not confirmed to play (Zach Ertz: on the practice
        # squad)" — the row names who.
        who = gate[len("not confirmed to play"):].strip(" ()").split(":")[0]
        return f"{who} on practice squad" if who else "practice squad"
    if gate.startswith(("held: the lineup changed", "held: the bench changed")):
        return "held this week"
    if gate.startswith("nobody on your bench"):
        return f"no bench {slot.get('slot', '')}".strip()
    if gate.startswith("no eligible player") or not gate:
        return ""
    if starter_ok and alt:
        # The row belongs to the STARTER, who starts either way: a bench
        # player who projects below him never takes the slot. "Start · waiting
        # on Jonathan Mingo" beside a 17.2-to-4.7 gap said otherwise (launch
        # review RQ-18), and never said WHY (BE-D3) — the plain fact is last
        # week's designation, dated, and the bench row prints it in full.
        if gate.startswith("availability in doubt"):
            return f"start · {alt} was questionable"
        return f"start · {alt} not confirmed"
    if gate.startswith("availability in doubt"):
        return f"questionable{see}"
    return f"status open{see}"


def short_gate(gate: str | None, slot: str) -> str:
    """The per-row reason a slot carries no number, short enough for the call
    column. The note under the table used to lump every reason into one
    "·"-separated line, so a reader could not tell which applied to which row
    — three of nine rows in the published sample read "no call" with the
    reasons pooled underneath. A bare "no call" on the only QB on the roster
    reads as a defect; "no bench QB" reads as what it is.

    Structural gates no longer reach here — see is_structural_gate.
    """
    if not gate:
        return NO_CALL
    if gate.startswith("nobody on your bench"):
        return f"{NO_CALL} · no bench {slot}"
    if gate.startswith("not enough games"):
        return f"{NO_CALL} · too few games yet"
    if gate.startswith("we don't put a number on defenses"):
        return f"{NO_CALL} · defenses not graded yet"
    if gate.startswith("odds once this lineup shape is graded"):
        return f"{NO_CALL} · lineup shape not graded yet"
    if gate.startswith("held: an input"):
        return f"{NO_CALL} · held this week"
    if gate.startswith("no eligible player"):
        return NO_CALL
    return f"{NO_CALL} · status unconfirmed"


def availability_basis(meta: Mapping[str, Any]) -> str:
    """The data-age sentence (principle 3), shared by both renderers.

    The engine names the information set itself ("the week 9 injury report,
    the last complete one before this report goes out"), which is true of a
    live Tuesday file and of a replayed sample alike. A bare timestamp is
    humanised if one ever arrives: a raw ISO stamp on a buyer surface — a 2026
    download time on a 2024 report — made a cold reader doubt what year they
    were looking at.
    """
    availability = meta.get("availability_as_of")
    rebuilt = re.match(r"the week (\d+) injury report", str(availability or ""))
    if meta.get("rebuilt_after_kickoff") and rebuilt:
        # Rebuilt after kickoff from Tuesday's information: "the last complete
        # one before this report goes out" was false of it (INFO-117).
        return (f"Injury and inactive data as of the week {rebuilt.group(1)} "
                f"injury report, the one this week's Tuesday report was built on; "
                f"this rebuild doesn't read later injury news.")
    if availability:
        try:
            stamp = datetime.fromisoformat(str(availability))
            # The buyer's clock, the one every kickoff in the report uses.
            availability = eastern(stamp)
        except (TypeError, ValueError):
            pass
        return f"Injury and inactive data as of {availability}."
    return ("We couldn't confirm injuries or inactives for this week, so "
            "some calls are left unmade rather than guessed.")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _pct(value: float) -> int:
    return max(0, min(100, round(value * 100)))


def _bar_from_even(value: float) -> int:
    """Bar width for a head-to-head probability, drawn from 50% (a coin
    flip) to 100%: 0.58 -> 16, 0.66 -> 32, 1.0 -> 100."""
    return max(0, min(100, round((value - 0.5) * 200)))


def extract_design(template_html: str) -> tuple[str, str]:
    """Pull the <style> block and font <link> tags out of the template."""
    style = re.search(r"<style>(.*?)</style>", template_html, re.DOTALL)
    if not style:
        raise ValueError(f"no <style> block found in {TEMPLATE_PATH}")
    links = "\n".join(re.findall(r'<link[^>]+>', template_html))
    return style.group(1), links


def gate_note(reason: str) -> str:
    """The one honest way a missing number renders (principle 3).

    The label sits on its own line above the reason, so the reason is a
    sentence and starts like one (launch review D10: "Heads up" over "no
    projected totals yet…" on the week-1 sample)."""
    reason = reason[:1].upper() + reason[1:]
    return (f'<div class="withheld"><span class="lab">{esc(NOT_CALLING_IT)}</span>'
            f'{esc(reason)}</div>')


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

def is_subscriber_report(meta: Mapping[str, Any]) -> bool:
    """A weekly report addressed to one subscriber: solo, and neither a
    published sample nor a free report. The chrome that names a team, counts
    seats or dates a roster belongs only here."""
    return bool(meta.get("solo")) and not (
        meta.get("historical_demo") or meta.get("live_demo") or meta.get("trial"))


# Slots that make a poor name for a team: "the Denver Broncos's team".
_UNNAMED_SLOTS = ("K", "DEF")


def team_name(report: Mapping[str, Any]) -> str | None:
    """"Josh Allen's team" — the roster named by its highest-projected starter.

    A manager with two teams got two identical emails, "Week 6: your lineup,
    decided" over "Your league · 12 teams · Full PPR", and could not tell which
    league either was for (panel review BE-I5, Oct 2026). The join flow asks
    for no team name, so the name is one every manager already uses for a
    team: its best player. Facts only: he is on the roster and he leads its
    projections. Week 1 has no projections, so the first starter named in
    lineup order stands in (the quarterback, on every template). Kickers and
    defenses never name a team. Subscriber reports only: a sample or a free
    report goes to nobody with two teams.
    """
    meta = report.get("meta") or {}
    if not is_subscriber_report(meta):
        return None
    if meta.get("team_lead"):
        # Fixed by the roster on file (engine.solo_report.team_lead, panel
        # review RQ2-06): the same subscription keeps the same name every
        # week. The projection rule below is for reports built before it.
        return f"{meta['team_lead']}'s team"
    starters = [s for s in (report.get("lineup") or [])
                if s.get("player_name") and s.get("slot") not in _UNNAMED_SLOTS]
    if not starters:
        return None
    projected = [s for s in starters if s.get("projected") is not None]
    lead = (max(projected, key=lambda s: s["projected"]) if projected
            else starters[0])
    return f"{lead['player_name']}'s team"


def _site_bar() -> str:
    """The published samples' masthead row: the wordmark home, the site's own
    routes, and the labelled Home button every site page carries above its
    headline (tests/test_site.py). Relative links: the samples sit at the site
    root, and the live sample's ?via= carry rewrites exactly these."""
    return (
        '<div class="sitebar">'
        f'<a class="brand" href="index.html">{mark_svg("bylm")}'
        '<span>Beat Your League</span></a>'
        '<nav class="sitenav" aria-label="Site">'
        '<a href="how-it-works.html">How it works</a>'
        '<a href="index.html#pricing">Pricing</a>'
        '<a class="home" href="index.html">← Home</a></nav></div>')


# The samples' one ask, at the top and at the end. It follows the landing's
# CHECKOUT_OPEN, read from site/index.html when the page is rendered (promise
# audit INFO-4, D15): open, "Get this for your team" goes to the join page;
# closed, the button says what it does and goes to the landing's email capture,
# like every closed CTA there. It never names a price (the hero rule).
SAMPLE_CTA = "Get this for your team"
SAMPLE_CTA_CLOSED = "Tell me when it opens"
LANDING_PAGE = REPO_ROOT / "site" / "index.html"
_CHECKOUT_FLAG = re.compile(r"^const CHECKOUT_OPEN = (true|false);", re.M)


def checkout_open(landing: Path | None = None) -> bool:
    """The landing page's CHECKOUT_OPEN. Unreadable or absent reads as closed:
    a closed ask on an open checkout costs a click, an open one on a closed
    checkout is a dead end."""
    try:
        text = Path(landing or LANDING_PAGE).read_text(encoding="utf-8")
    except OSError:
        return False
    match = _CHECKOUT_FLAG.search(text)
    return bool(match and match.group(1) == "true")


def sample_cta() -> str:
    if checkout_open():
        return f'<a class="btn" href="join/index.html">{esc(SAMPLE_CTA)}</a>'
    return f'<a class="btn" href="index.html#watch-form">{esc(SAMPLE_CTA_CLOSED)}</a>'


def header(meta: Mapping[str, Any], team: str | None = None) -> str:
    """The masthead. ``team`` names a subscriber's roster (``team_name``), so
    a manager with two teams can tell the two reports apart."""
    chips = [
        f'<span class="chip"><b>{esc(team or meta["league_name"])}</b>'
        f' · {esc(meta["num_teams"])} teams'
        + (f' · {esc(meta["scoring"])}' if meta.get("scoring") else "") + "</span>",
        f'<span class="chip">{esc(_generated_stamp(meta))}</span>',
    ]
    # A solo report has no opponent, so there is no "this week" to name. The
    # chip printed "This week: None" — an absent value rendered as a word.
    if not meta.get("solo"):
        chips.insert(1, f'<span class="chip">This week: '
                        f'<b>{esc(meta["rival_label"])}</b></span>')
    if meta.get("rivalry_week"):
        chips.insert(1, '<span class="chip" style="border-color:var(--flag);'
                        'color:var(--flag)"><b>RIVALRY WEEK</b></span>')
    elif meta.get("named_rival_label"):
        chips.insert(2, f'<span class="chip">Rival: '
                        f'<b>{esc(meta["named_rival_label"])}</b></span>')
    # Notices, not alarms: these wore .regret-note's brick alert tint, so the
    # most-linked page of the site opened on what read as an error box.
    banner = ""
    if meta.get("live_demo"):
        # The live sample (render/live_sample.py): this week's report for the
        # published sample roster, rebuilt every Tuesday by the weekly cron.
        # A rebuild after the week's first kickoff is NOT the way a
        # subscriber's report is built (it withholds, and it still reads
        # Tuesday's injury report), so it says what it is (INFO-100, INFO-117).
        if meta.get("rebuilt_after_kickoff"):
            banner = (
                '<div class="notice">'
                f'<b>THIS WEEK\'S REPORT</b> — Week {esc(meta["week"])} of the '
                f'{esc(meta["season"])} season for a sample roster, rebuilt '
                f'{esc(_built_on(meta))} from this week\'s Tuesday information '
                f'(the week {esc(int(meta["week"]) - 1)} injury report); later '
                f'injury news is not in it.</div>')
        else:
            banner = (
                '<div class="notice">'
                f'<b>THIS WEEK\'S REPORT</b> — Week {esc(meta["week"])} of the '
                f'{esc(meta["season"])} season, built {esc(_built_on(meta))} for a '
                f'sample roster, exactly the way yours is built. Rebuilt every '
                f'Tuesday of the season.</div>')
    elif meta.get("historical_demo") and meta.get("solo"):
        # The solo sample is built from the nflverse record, where past-season
        # injury reports ARE available — so confidences print, and the old
        # "numbers are left off" sentence would be false of the page it sits on.
        # One banner per sample (INFO-99): Week 1 has no box score and no
        # injury report behind it, and a mid-season week is built from what
        # was out BEFORE its games, never from its own box scores.
        scoring = str(meta.get("scoring") or "")
        scored = (f"scored {scoring[:1].lower()}{scoring[1:]}" if scoring
                  else "one scoring setting")
        if meta.get("first_week_demo"):
            banner = (
                '<div class="notice">'
                f'<b>SAMPLE REPORT</b> — Week 1 of the {esc(meta["season"])} NFL '
                f'season, built the way yours will be: one roster, {esc(scored)}. '
                f'Before Week 1 no game has been played and no injury report '
                f'exists, so the slots are ordered by last season\'s scoring and '
                f'no odds print.</div>')
        else:
            banner = (
                '<div class="notice">'
                f'<b>SAMPLE REPORT</b> — a real week from the {esc(meta["season"])} NFL '
                f'season, built the way yours will be: one roster, {esc(scored)}, '
                f'from the box scores and injury report out before that week\'s '
                f'games.</div>')
    elif meta.get("historical_demo"):
        banner = (
            '<div class="notice">'
            f'SAMPLE REPORT — real data from the {esc(meta["season"])} season of '
            f'{esc(meta["league_name"])}, built to show exactly what lands in your inbox '
            f'on a Tuesday. Because it\'s a past season we can\'t check who was hurt or '
            f'inactive back then, so the confidence numbers are left off — in a live week '
            f'you get them on every slot where both players are confirmed active.'
            + (' Team and manager names here are placeholders; every number is that '
               'league\'s real record.' if meta.get("anonymized_demo") else "")
            + '</div>'
        )
    if season_end_lines(meta):
        banner += ('<div class="notice">'
                   f'<b>{esc(SEASON_END_HEAD)}.</b> '
                   f'{esc(" ".join(season_end_lines(meta)))}</div>')
    brand = f'<div class="brand">{mark_svg("bylm")}<span>Beat Your League</span></div>'
    cta = ""
    if meta.get("anonymized_demo"):
        # The published samples are site pages a visitor reaches from the
        # landing page or a shared link, and they offered no way back and no
        # route to pricing or setup — only a Home pill (panel review I3, I5).
        # A subscriber's own report is opened from their inbox and keeps the
        # plain masthead.
        brand = _site_bar()
        if meta.get("solo"):
            cta = f'<p class="headcta">{sample_cta()}</p>'
    return (
        f'<header class="bug">{brand}'
        f'<h1>Week {esc(meta["week"])} · {"Your Report" if meta.get("solo") else "Rival Report"}</h1>'
        f'<div class="chips">{"".join(chips)}</div>{cta}</header>{banner}'
    )


def eastern(stamp: datetime) -> str:
    """'Thu Oct 15 · 7:02 AM ET' — the buyer's clock, the one every kickoff in
    the report is printed in. A naive stamp is read as UTC."""
    from zoneinfo import ZoneInfo
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    local = stamp.astimezone(ZoneInfo("America/New_York"))
    return (local.strftime("%a %b ") + f"{local.day} · "
            + local.strftime("%I:%M %p ET").lstrip("0"))


def _built_on(meta: Mapping[str, Any]) -> str:
    try:
        stamp = datetime.fromisoformat(meta.get("generated_at", ""))
        from zoneinfo import ZoneInfo
        stamp = stamp.astimezone(ZoneInfo("America/New_York"))   # the buyer's clock
    except (TypeError, ValueError, KeyError):
        return "this week"
    return stamp.strftime("%A, %B ") + str(stamp.day)


def _generated_stamp(meta: Mapping[str, Any]) -> str:
    """When this report was built, in the buyer's words and on the buyer's
    clock. A subscriber's report said "Generated Thu Oct 15 · 18:51 UTC" — the
    operator's word on the operator's clock, above kickoffs printed in ET
    (panel review BE-I10, I11, RQ-19)."""
    raw = meta.get("generated_at", "")
    try:
        stamp = datetime.fromisoformat(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return "Built this week"
    if meta.get("historical_demo"):
        # The sample is a replay: say so in the stamp itself, or the build
        # date and the season it replays look like a contradiction. Dated on
        # the buyer's clock like every other stamp (recheck ENG-10): read off
        # UTC, a build after 8 PM ET was dated tomorrow.
        from zoneinfo import ZoneInfo
        local = stamp.astimezone(ZoneInfo("America/New_York"))
        return local.strftime(f"Rebuilt %b %d, %Y from the {meta.get('season')} "
                              f"season archive")
    return "Built " + eastern(stamp)


def section_checklist(items: list[Mapping[str, Any]]) -> str:
    tasks = []
    for item in items:
        klass = "dl ok" if item.get("urgency") in ("now", "done") else "dl"
        tasks.append(
            f'<div class="task"><div class="box"></div><div>'
            f'<div class="do">{esc(item["action"])}</div>'
            + (f'<div class="why">{esc(item["detail"])}</div>'
               if item.get("detail") else "")
            + f'<div class="{klass}">{esc(item["deadline"])}</div></div></div>'
        )
    return _section("Your Game Plan", 1, f'<div class="plan">{"".join(tasks)}</div>')


def section_last_week(last: Mapping[str, Any] | None) -> str:
    """The week just gone, closed out. Empty string in week 1.

    The scoreline is the headline and the counts sit under it as chips. No
    verdict colour on a loss: this section exists to resolve the week, not to
    score the reader.
    """
    if not last:
        return ""
    tone = "win" if last.get("won") else "loss"
    chips = [
        f'<span class="drv">you <b>{last["points"]:.1f}</b></span>',
        f'<span class="drv">them <b>{last["opponent_points"]:.1f}</b></span>',
        f'<span class="drv">best you had <b>{last["best_possible"]:.1f}</b></span>',
    ]
    return _section(
        f'Week {esc(last["week"])} — How It Ended', 2,
        f'<p class="lastread {tone}">{esc(last["headline"])}</p>'
        f'<div class="drivers">{"".join(chips)}</div>')


def section_matchup(matchup: Mapping[str, Any]) -> str:
    you, rival = matchup["you"], matchup["rival"]
    # A side without a published total renders VS with the names only — a
    # "0.0 PROJ" is a fabricated number wearing a scoreboard font.
    gated = matchup.get("range_gate")

    def pts(team: Mapping[str, Any]) -> str:
        if gated or "projected_total" not in team:
            return ""
        return f'<div class="pts">{team["projected_total"]:.1f} <small>PROJ</small></div>'

    # The gap is the number the week turns on, and the board printed both totals
    # and left the subtraction to the reader. It is stated as the PROJECTION GAP,
    # never as a predicted final margin — win probability is gated off precisely
    # because we cannot stand behind a likelihood, and the overlapping floor and
    # ceiling bands sit directly beneath it so the closeness stays visible.
    centre = "VS"
    margin, swing = matchup.get("margin"), matchup.get("margin_swing")
    if not gated and margin is not None and swing is not None:
        # Neutral, never a verdict colour, and never without the swing beside
        # it: on a typical week the gap is a tenth of how far the week moves,
        # and a bare figure in turf green one line above "we won't publish a
        # win probability" would be claiming with colour what we refuse to
        # claim in words. No odds word is attached — the matchup backtest
        # found favourites won MORE often than stated, so we cannot narrate it.
        side = "ahead" if margin >= 0 else "behind"
        centre = (f'<div class="gap"><span class="gnum">{abs(margin):.1f}</span>'
                  f'<span class="glab">projected {side}</span>'
                  f'<span class="gswing">week swings &plusmn;{swing}</span></div>')
    board = (
        f'<div class="board">'
        f'<div class="team you"><div class="name">{esc(you["label"])}</div>'
        f'<div class="sub">Your best lineup this week</div>{pts(you)}</div>'
        f'<div class="vs">{centre}</div>'
        f'<div class="team rival"><div class="name">{esc(rival["label"])}</div>'
        f'<div class="sub">Lineup as currently set</div>{pts(rival)}</div>'
        f'</div>'
    )
    prob = matchup.get("win_probability")
    if prob is not None:
        # Higher win probability drives the ball INTO rival territory (right);
        # the template's sample pairs 61% with left:61%.
        ball_left = _pct(prob)
        field = (
            f'<div class="field-wrap"><div class="field-label">'
            f'<span class="l">Your territory</span><span class="r">Rival territory</span></div>'
            f'<div class="field"><div class="endzone l"></div><div class="endzone r"></div>'
            f'<div class="ball" style="left:{ball_left}%">'
            f'{mark_svg("bylf", "fieldball")}</div></div>'
            f'<p class="field-read"><b class="win">{_pct(prob)}% win probability.</b> '
            f'The odds your best lineup outscores the lineup they have set.</p></div>'
        )
    else:
        # Deliberately NOT in the scoreboard slot — see below.
        field = ""

    # Ranges carry their own backtest evidence (band coverage), so they render
    # independently of the win-probability gate — but only when the engine
    # published them. A gated week renders the reason, never a zeroed band.
    if gated:
        ranges = gate_note(f"projected totals and ranges — {gated}")
        return _section("The Matchup", 2, board + field + ranges)

    lo = min(you["floor"], rival["floor"])
    hi = max(you["ceiling"], rival["ceiling"])
    span = (hi - lo) or 1.0

    # ONE axis, not two. Scaled to the union of both bands, each team's range
    # fills 91-96% of its own track, so two separate tracks showed two nearly
    # identical full-width bars and the comparison the section exists to make
    # was invisible. Stacked on a shared axis, the thing you actually see is
    # the OVERLAP — 87% on the sample week — which is the honest reading and
    # the same one the gap's ±swing gives.
    def row(team: Mapping[str, Any], side: str) -> str:
        left = _pct((team["floor"] - lo) / span)
        right = 100 - _pct((team["ceiling"] - lo) / span)
        med = _pct((team["projected_total"] - lo) / span)
        return (f'<span class="rband {side}" style="left:{left}%;right:{right}%">'
                f'</span><span class="rmed {side}" style="left:{med}%"></span>')

    over_lo = max(you["floor"], rival["floor"])
    over_hi = min(you["ceiling"], rival["ceiling"])
    over_html, over_share = "", None
    if over_hi > over_lo:
        ol = _pct((over_lo - lo) / span)
        orr = 100 - _pct((over_hi - lo) / span)
        over_share = round((over_hi - over_lo) / span * 100)
        over_html = f'<span class="rover" style="left:{ol}%;right:{orr}%"></span>' 
    basis = matchup.get("range_basis")
    basis_html = (f'<div class="yards" style="justify-content:flex-end">'
                  f'{esc(basis)}</div>' if basis else "")
    read = ""
    if over_share is not None:
        read = (f'<p class="rread">Their realistic week and yours overlap by '
                f'<b>{over_share}%</b> — which is why the gap above is small '
                f'next to the swing.</p>')
    withheld = ""
    if matchup.get("win_probability") is None and matchup.get("win_probability_gate"):
        withheld = (f'<p class="withheldline">'
                    f'{esc(matchup["win_probability_gate"])}.</p>')
    # Each team's own floor-ceiling sits beside its own name. The axis ends are
    # the UNION of both bands, so on the sample week the left end reads 86 —
    # the rival's floor, not yours (89.6) — and it was the only pair of numerals
    # on a block captioned "Your realistic high and low". Moving to one shared
    # axis had dropped the per-team numerals without replacing them, so the
    # buyer's own floor and ceiling appeared nowhere in the browser report while
    # the email printed both. Every score shown gets a definition (principle 5).
    def label(team: Mapping[str, Any], side: str) -> str:
        return (f'<span class="{side}">{esc(team["label"])} '
                f'<b>{team["floor"]:.0f}–{team["ceiling"]:.0f}</b></span>')

    ranges = (
        f'<div class="rangeaxis">'
        f'<div class="rlab">{label(you, "you")}{label(rival, "rival")}</div>'
        f'<div class="rtrack">{over_html}{row(you, "you")}{row(rival, "rival")}</div>'
        f'<div class="rends"><span>{lo:.0f}</span><span>{hi:.0f}</span></div>'
        f'{read}</div>{withheld}{basis_html}'
    )

    return _section("The Matchup", 2, board + field + ranges)


def section_rival_watch(watch: Mapping[str, Any] | None) -> str:
    """The named rival's weekly strip. Empty string when not configured."""
    if watch is None:
        return ""
    if "gate" in watch:
        return _section("Rival Watch", 0, gate_note(watch["gate"]))
    h2h = watch.get("head_to_head") or {}
    chips = [
        f'<span class="drv">their record <b>{esc(watch.get("their_record", "—"))}</b></span>',
        f'<span class="drv">you vs them all-time '
        f'<b>{esc(h2h.get("wins", 0))}-{esc(h2h.get("losses", 0))}</b></span>',
    ]
    if watch.get("rivalry_week"):
        body = (
            f'<p class="field-read"><b class="win">It\'s Rivalry Week.</b> '
            f'{esc(watch["label"])} is this week\'s opponent — the whole report '
            f'above is the scouting file.</p>'
            f'<div class="drivers">{"".join(chips)}</div>'
        )
    else:
        lines = []
        if watch.get("their_opponent"):
            lines.append(f'They play {esc(watch["their_opponent"])} this week.')
        if watch.get("fragile_spots"):
            top = watch.get("top_fragility")
            lines.append(f'{esc(watch["fragile_spots"])} fragile spot'
                         f'{"s" if watch["fragile_spots"] != 1 else ""} in their '
                         f'current lineup'
                         + (f' — e.g. {esc(top)}' if top else "") + ".")
        elif watch.get("fragile_spots") == 0:
            lines.append("No fragile spots visible in their current lineup.")
        evidence = h2h.get("evidence", "")
        body = (
            f'<p class="field-read"><b>{esc(watch["label"])}</b> — '
            f'{" ".join(lines) if lines else "no matchup data for them this week."}</p>'
            f'<div class="drivers">{"".join(chips)}</div>'
            f'<p class="mkt">{esc(evidence)} · record {esc(watch.get("record_evidence", ""))}</p>'
        )
    return _section("Rival Watch", 0, body)


def _tape_side(slot: Mapping[str, Any], mine: bool, mixed: bool = False) -> str:
    """One half of a row. The name leads; the sub-line carries scouting facts,
    not our methodology — every product in this market uses that line for what
    the player is getting, and we were spending it on "8 games of form"."""
    name = slot.get("player_name") or "—"
    proj = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
    # BOTH halves carry availability flags. optimal_lineup deliberately seats an
    # OUT player when nothing eligible remains, so reading flags on the rival's
    # side only meant we flagged their bye-week starter and said nothing about
    # yours — the one player the reader can still do something about.
    flags = [f["text"] for f in (slot.get("flags") or [])]
    bits = []
    if mine:
        edge = edge_phrase(slot)
        if edge:
            bits.append(edge)
        conf = slot.get("confidence")
        if conf is not None:
            bits.append(f"{_pct(conf)}%")
        elif mixed and slot.get("player_name") and slot.get("confidence_gate"):
            # Only in a MIXED week. Where some rows carry a percentage, silence
            # on the others would read as a call we forgot to make. Where NO
            # row does, nine identical "no call" markers say nothing the note
            # under the table does not say once, properly, with the reason.
            bits.append(NO_CALL)
    flag_html = (f'<span class="tflag">{esc(" · ".join(flags))}</span>'
                 if flags else "")
    sub = (f'<span class="tsub">{esc(" · ".join(bits))}</span>' if bits else "")
    side = "you" if mine else "rival"
    return (f'<td class="tside {side}"><span class="tname">{esc(name)}</span>'
            f'{flag_html}{sub}</td><td class="tpts {side}">{proj}</td>')


# Explicit column widths. The header row spans two cells per side, so a bare
# table-layout:fixed reads its widths off a colspan and lands nowhere near
# symmetric; on auto layout the rival's long fragility flag pulled its column
# wide and squeezed yours, so identical text wrapped on your side and not on
# theirs — in a grid whose whole argument is that the two sides compare
# directly. The colgroup is the only thing that makes the halves equal.
# Widths live in the template CSS, not inline here: inline styles beat a media
# query, and at 375px the fixed desktop split clipped "123.2" out of the points
# column on both sides.
TAPE_COLS = "<colgroup>" + "<col>" * 5 + "</colgroup>"


# The solo lineup grid. Same table furniture as the Tape so the two products
# look like one brand, but three columns instead of five: with no opponent there
# is no centre spine and no tint, because a tint IS a comparison and there is
# nothing to compare against. Emphasis comes from the slot order instead, which
# is the order a manager reads their own lineup in anyway.
LINEUP_COLS = ('<colgroup><col style="width:9%"><col style="width:58%">'
               '<col style="width:12%"><col style="width:21%"></colgroup>')


def section_your_lineup(report: Mapping[str, Any]) -> str:
    """The lineup we would set, and what each call is worth.

    GRADE C (reports/nflverse-backtest.md): the confidence numeral is a
    recorded prediction, not an accuracy claim. Nothing here may describe it as
    tested, calibrated or accurate — the note under the table says what it is
    and the receipts section says it gets graded.
    """
    slots = report["lineup"]
    mixed = any(s.get("confidence") is not None for s in slots)
    shown_marker = False
    rows = []
    for slot in slots:
        name = slot.get("player_name") or "—"
        proj = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
        # One fact a line: the call's own facts, his games this season, then
        # the counted usage; and a reason sentence where one is owed.
        lines = [" · ".join(call_bits(slot)), form_phrase(slot),
                 str(slot.get("usage") or ""), str(slot.get("reason") or "")]
        subs = "".join(f'<span class="tsub">{esc(line)}</span>' for line in lines if line)
        flags = [f["text"] for f in (slot.get("flags") or [])]
        # Opponent and kickoff (launch audit F7), straight under the name: it
        # is the fact a manager checks first, and the one that says a starter
        # plays Thursday night.
        game = (f'<span class="tgame">{esc(slot["game"])}</span>'
                if slot.get("game") else "")
        confidence = slot.get("confidence")
        if confidence is not None:
            # The bar runs from 50% to 100%, not from zero: every number is a
            # head-to-head against the best bench option, so 50 is a coin flip
            # and the floor. Drawn from zero, a 58% lean looked nearly as long
            # as a 66% call; drawn from 50 the reader who skims sees the same
            # call as the reader who reads. Grade C: still a recorded
            # prediction, not accuracy.
            call = (f'<b>{_pct(confidence)}%</b>'
                    f'<span class="cbar" title="Bar starts at 50%, a coin flip">'
                    f'<i style="width:{_bar_from_even(confidence)}%"></i></span>')
        elif slot.get("player_name") and row_marked(slot, mixed):
            shown_marker = True
            call = f'<span class="tsub">{esc(row_label(slot))}</span>'
        else:
            call = ""
        rows.append(
            f'<tr class="trow"><td class="tslot">{esc(slot["slot"])}</td>'
            f'<td class="tside you"><span class="tname">{esc(name)}</span>{game}'
            + (f'<span class="tflag">{esc(" · ".join(flags))}</span>' if flags else "")
            + subs
            + f'</td><td class="tpts you">{proj}</td>'
            f'<td class="tcall">{call}</td></tr>')
    head = ('<tr class="thead"><td></td><td>Your lineup</td>'
            '<td style="text-align:right">Proj</td><td>Call</td></tr>')
    note = ""
    gates = {s["confidence_gate"] for s in slots if s.get("confidence_gate")}
    if gates:
        head_text = no_call_head(shown_marker and mixed, mixed)
        note = (f'<div class="withheld"><b>{esc(head_text)}</b> '
                f'{esc(no_call_explainer(gate_list(gates)))}</div>')
    hot = projection_note(slots)
    if hot:
        note += f'<div class="withheld">{esc(hot)}</div>'
    seeded_note = (f'<div class="withheld">{esc(SEEDED_SECTION_LINE)}</div>'
                   if report["meta"].get("seeded") else "")
    return _section("The Lineup", 3,
                    f'<table class="tape">{LINEUP_COLS}{head}'
                    f'{"".join(rows)}</table>{_bench_table(report)}'
                    f'{seeded_note}{note}')


def row_marked(slot: Mapping[str, Any], mixed: bool) -> bool:
    """Does a row without odds say why in its own call cell?

    In a MIXED week every one does (launch review I16): the structural rows
    — the only quarterback, the only kicker — used to show an empty cell
    beside rows reading 70%, which read as a value we forgot; "no bench QB"
    reads as what it is. A defense always says "projection only" (RQ-15): its
    pick rests on a number we don't put odds on, in any week. In a week with
    no odds anywhere, the note under the table says it once instead."""
    gate = slot.get("confidence_gate") or ""
    if not gate or not row_label(slot):
        return False
    # So does a lineup shape with no graded arm (contract C8): every row of it
    # is a projection only, every week, and says so.
    return mixed or gate.startswith(("we don't put odds on defenses",
                                     "odds once this lineup shape is graded"))


def _bench_table(report: Mapping[str, Any]) -> str:
    """Every rostered player who is not starting — nobody vanishes.

    The lineup names each starter and one bench alternative per slot, so any
    other bench player used to disappear from the file entirely; on a real
    2026 week-4 roster that was Saquon Barkley, mentioned on no surface at all.
    Same table idiom as the lineup, so it reads as the rest of the roster
    rather than as an appendix.
    """
    bench = report.get("bench") or []
    if not bench:
        return ""
    rows = []
    for entry in bench:
        proj = (f'{entry["projected"]:.1f}' if entry.get("projected") is not None
                else "—")
        rank = entry.get("last_season_rank")
        # NOT .tflag: that is brick, reserved for "cannot play", and a benched
        # star must not read as an injury. Out players DO take the flag.
        tag = (f'<span class="tflag">{esc(bench_phrase(entry))}</span>'
               if entry.get("out") else
               (f'<span class="tflag">{esc(entry["note"])}</span>'
                if entry.get("note") else "")
               + (f'<span class="trank">{esc(rank)} last season</span>'
                  if entry.get("notable") and rank else ""))
        game = (f'<span class="tgame">{esc(entry["game"])}</span>'
                if entry.get("game") else "")
        rows.append(
            f'<tr class="trow bench"><td class="tslot">{esc(entry["position"])}</td>'
            f'<td class="tside you"><span class="tname">{esc(entry["name"])}</span>'
            f'{game}{tag}'
            + (f'<span class="tsub">{esc(bench_form(entry))}</span>'
               if bench_shows_form(entry) else "")
            + '</td>'
            f'<td class="tpts you">{proj}</td><td class="tcall"></td></tr>')
    head = (f'<tr class="thead"><td></td><td>{esc(BENCH_HEAD)}</td>'
            '<td style="text-align:right">Proj</td><td></td></tr>')
    return f'<table class="tape benchtape">{LINEUP_COLS}{head}{"".join(rows)}</table>'


# Principle 5: every number shown has a definition. "94 – 158 realistic range"
# printed on every report with none, anywhere (panel review SS-I1). This says
# what engine.week_report._team_range computes — the starters' projections
# summed, plus or minus 1.28 times their combined spread — in the buyer's
# words, and claims no coverage: the frozen method (§10.8) withholds the
# "about 78%" sentence until the band is measured on this data, so the
# definition may not smuggle one back in as "8 weeks in 10".
RANGE_LABEL = "realistic range"
RANGE_DEFINITION = ("your projected total, give or take the week-to-week swing "
                    "in your starters' scoring, combined. It shows how far the "
                    "week can move, not where it will land.")


def range_text(team: Mapping[str, Any]) -> str:
    """"94 – 158": the band, rounded the way every surface prints it."""
    return f'{team["floor"]:.0f} – {team["ceiling"]:.0f}'


def section_your_week(matchup: Mapping[str, Any], no_opponent: str | None) -> str:
    """Your projected week — a total and a band, with no opponent to beat.

    The head-to-head board would be half empty here, and half a scoreboard reads
    as a broken scoreboard. So this is your number and its range, and one plain
    sentence saying why there is no other side, stated once.
    """
    you = matchup["you"]
    gate = matchup.get("range_gate")
    if gate:
        body = gate_note(gate)
    else:
        body = (f'<div class="team"><div class="name">{esc(you["label"])}</div>'
                f'<div class="pts">{you["projected_total"]:.1f} <small>PROJ</small></div>'
                f'<div class="wkrange">{range_text(you)} '
                f'<span>{esc(RANGE_LABEL)}</span></div></div>'
                f'<p class="rangedef"><b>{esc(RANGE_LABEL.capitalize())}:</b> '
                f'{esc(RANGE_DEFINITION)}</p>')
        basis = matchup.get("range_basis")
        if basis:
            body += f'<div class="yards">{esc(basis)}</div>'
    if no_opponent:
        body += f'<p class="withheldline">{esc(no_opponent)}</p>'
    return _section("Your Week", 2, body)


def section_tape(report: Mapping[str, Any]) -> str:
    """Both lineups, one row per slot, your player against theirs.

    This replaces two stacked nine-row tables and the prose that restated them.
    Sleeper's own matchup screen — the one this buyer already lives in — is a
    centre-spine list with no prose at all, and Fantasy Life's head-to-head
    comparison contains two words of English. The tint says who wins the slot,
    so nothing has to say it.
    """
    mine, theirs = report["lineup"], report["rival_lineup"]
    as_set = report["meta"].get("lineup_as_set")
    mixed = any(s.get("confidence") is not None for s in mine)
    rows = []
    for index, slot in enumerate(mine):
        other = theirs[index] if index < len(theirs) else {}
        a = slot.get("projected")
        b = other.get("projected")
        # The tint is the verdict. It is only claimed when BOTH sides have a
        # projection — a one-sided comparison would tint on missing data.
        lead = "" if a is None or b is None else (" alead" if a > b else
                                                  " blead" if b > a else "")
        rows.append(
            f'<tr class="trow{lead}">{_tape_side(slot, True, mixed)}'
            f'<td class="tslot">{esc(slot["slot"])}</td>'
            f'{_tape_side(other, False)}</tr>'
        )
    matchup = report["matchup"]
    you_total = matchup["you"].get("projected_total")
    rival_total = matchup["rival"].get("projected_total")
    total_row = ""
    if you_total is not None and rival_total is not None:
        total_row = (f'<tr class="trow ttotal"><td class="tside you">TOTAL</td>'
                     f'<td class="tpts you">{you_total:.1f}</td>'
                     f'<td class="tslot"></td>'
                     f'<td class="tside rival"></td>'
                     f'<td class="tpts rival">{rival_total:.1f}</td></tr>')
    head = (f'<tr class="thead"><td colspan="2">You</td><td></td>'
            f'<td colspan="2">{esc(report["meta"]["rival_label"])}</td></tr>')
    note = ""
    if as_set:
        note = (f'<div class="benchnote"><b>{esc(AS_SET_HEAD)}</b> '
                f'{esc(AS_SET_BODY)}</div>')
    else:
        gates = {s["confidence_gate"] for s in mine if s.get("confidence_gate")}
        if gates:
            head_text = (f'Why some slots say "{NO_CALL}":' if mixed
                         else f'{NO_CALL.capitalize()} on any slot this week:')
            note = (f'<div class="withheld"><b>{esc(head_text)}</b> '
                    f'{esc(no_call_explainer(" · ".join(sorted(gates))))}</div>')
    title = "The Tape — As Set" if as_set else "The Tape"
    return _section(title, 4,
                    f'<table class="tape">{TAPE_COLS}{head}{"".join(rows)}'
                    f'{total_row}</table>{note}')


def section_fragility(items: list[Mapping[str, Any]], rival_label: str) -> str:
    if not items:
        body = gate_note("nothing in their lineup we can call fragile this week")
    else:
        rows = "".join(
            f'<div class="srow"><div class="x">{i + 1}</div><div>'
            f'<div class="who">{esc(item["title"])}</div>'
            f'<div class="why">{esc(item["detail"])} '
            f'<em>({esc(item["evidence"])})</em></div></div></div>'
            for i, item in enumerate(items)
        )
        body = f'<div class="scout">{rows}</div>'
    return _section(f"Where {rival_label} Is Fragile", 5, body)


def no_call_line(regret: Mapping[str, Any]) -> str:
    """The closest-call section when nothing carries odds: ONE plain line —
    that there is no call, then the closest decision and why it has none
    (RQ-06). Every surface prints this same line (launch review RQ-19: a
    whole section with a "Heads up" box, for an absence, was the longest way
    to say the shortest thing)."""
    line = " ".join(t for t in (regret.get("gate"), regret.get("closest")) if t)
    # The league product's gate starts lowercase ("no coin-flip call…"); a
    # line on its own starts like a sentence (D10).
    return line[:1].upper() + line[1:]


def section_regret(regret: Mapping[str, Any]) -> str:
    if "gate" in regret:
        # No .call frame: a heavy navy card whose only content is an absence
        # reads as broken software rather than restraint — and no Heads-up box
        # either (RQ-19): the body is the one line.
        return _section("The Week's Closest Call", 6,
                        f'<p class="field-read">{esc(no_call_line(regret))}</p>')
    confidence = _pct(regret["confidence"])
    # SS-D2: the card says it is the closest call WITH ODDS, and a narrower
    # decision without odds is named beneath it rather than passed over.
    label = (f'<span class="drv">{esc(regret["label"])}</span>'
             if regret.get("label") else "")
    drivers = label + "".join(
        f'<span class="drv">{esc(d["label"])} <b>{esc(d["value"])}</b></span>'
        for d in regret["drivers"]
    )
    extra = "".join(f'<p class="why">{esc(regret[key])}</p>'
                    for key in ("reason", "closer") if regret.get(key))
    body = (
        f'<div class="call"><div class="verdict">Start {esc(regret["start_name"])} '
        f'<span class="over">over</span> {esc(regret["over_name"])}</div>'
        # Drawn from 50%, like the lineup bars, so "the bar starts at 50%"
        # is true of every bar in the report (promise audit LANDING-35).
        f'<div class="conf"><div class="bar"><i style="width:{_bar_from_even(regret["confidence"])}%"></i></div>'
        f'<div class="num">{confidence}%</div></div>'
        f'<div class="drivers">{drivers}</div>'
        f'<p class="why">{esc(regret["definition"])}</p>{extra}</div>'
    )
    return _section("The Week's Closest Call", 6, body)


# Said after a cleared-player plan, and only on a Sunday game (the engine sets
# "saturday" on the plan): the Saturday check reads Friday's final report and
# mails a swap when he is cleared, and stays quiet when he is not (RULE F3) —
# hence "if he is", never "either way". Never on a free report: there is no
# Saturday check behind one.
SATURDAY_FOLLOWUP = "If he is, Saturday's final check will tell you."


def pivot_action(plan: Mapping[str, Any], meta: Mapping[str, Any] | None = None) -> str:
    """One plan's "then", as every surface states it."""
    action = str(plan["action"])
    if plan.get("saturday") and not (meta or {}).get("trial"):
        action = f"{action}. {SATURDAY_FOLLOWUP}"
    return action


# The league product's empty if/then. The solo report carries its own reason
# (engine.solo_report.pivots_note) — this sentence was printed beside a
# questionable starter the report itself was flagging (launch review SS-D3).
NO_PIVOTS = "No pivots this week — no starter we can check is listed questionable."


def section_pivots(plans: list[Mapping[str, Any]],
                   meta: Mapping[str, Any] | None = None,
                   note: str | None = None) -> str:
    if not plans:
        body = gate_note(note or NO_PIVOTS)
    else:
        rows = "".join(
            f'<div class="pivot"><div class="if">If</div>'
            f'<div class="cond">{esc(p["condition"])}</div>'
            f'<div class="then">{esc(pivot_action(p, meta))}</div></div>'
            for p in plans
        )
        body = f'<div class="pivots">{rows}</div>'
    return _section("If/Then for Gameday", 7, body)


RISING_HEAD = "Rising Roles"
RISING_INTRO = ("Players getting more of the ball lately. Check whether any is "
                "free in your league.")
# When one of the risers is already the subscriber's (launch review BE-I7).
RISING_INTRO_MINE = ("Players getting more of the ball lately — yours first. "
                     "Check whether the others are free in your league.")


def rising_intro(rows: Sequence[Mapping[str, Any]]) -> str:
    """The section's opening line, true of the rows under it."""
    mine = [r for r in rows if r.get("on_roster")]
    if mine and len(mine) == len(rows):
        return "Players on your roster getting more of the ball lately."
    return RISING_INTRO_MINE if mine else RISING_INTRO


def rising_parts(row: Mapping[str, Any]) -> tuple[str, str]:
    """(who, what) — "Braelon Allen (NYJ, RB)" and the counted-usage clause —
    so both renderers can set the name apart. Split on the engine's own
    "name (team, pos): ..." line; anything else is shown whole."""
    line = str(row.get("line") or "")
    who, sep, what = line.partition(": ")
    return (who, what) if sep else ("", line)


def section_rising(rows: Sequence[Mapping[str, Any]]) -> str:
    """Counted usage, reported (RULE U1). Empty means the section is absent —
    an empty 'rising roles' block would advertise a feature that found nothing.

    Its own classes (launch audit W7): it borrowed ``ul.receipts``, whose rules
    are scoped to the navy ledger card, so on the published samples the
    bullets hung outside the section and the intro rendered as bare text."""
    if not rows:
        return ""
    items = []
    for row in rows:
        who, what = rising_parts(row)
        items.append(f'<li><b>{esc(who)}</b> {esc(what)}</li>' if who
                     else f'<li>{esc(what)}</li>')
    return _section(RISING_HEAD, 8, f'<p class="risingintro">{esc(rising_intro(rows))}</p>'
                                     f'<ul class="rising">{"".join(items)}</ul>')


def section_hype(entries: list[Mapping[str, Any]],
                 market: Mapping[str, Any] | None = None) -> str:
    if not entries:
        body = gate_note("a quiet waiver week — no sign of a league-wide chase "
                         "in your league's transaction log")
    else:
        gates = [entry.get("verdict_gate") for entry in entries]
        shared_gate = gates[0] if len(set(gates)) == 1 and gates[0] else None
        cards = []
        for entry in entries:
            bid = entry.get("top_bid")
            bid_text = f'top bid {bid}' + (
                f' of {entry["faab_budget"]} FAAB' if entry.get("faab_budget") else ""
            ) if bid is not None else "no FAAB bids recorded"
            # Visual only; the honest number (managers chasing) is in the label.
            fomo = min(100, entry["managers_chasing"] * 20)
            gate_line = ("" if shared_gate else
                         f'<div class="action no">→ {esc(entry["verdict_gate"])}</div>')
            usage_line_html = (f'<p class="usage">{esc(entry["usage"])}</p>'
                               if entry.get("usage") else "")
            cards.append(
                f'<div class="hcard"><div class="top">'
                f'<span class="player">{esc(entry["player_name"])} · {esc(entry["position"])}</span>'
                f'</div>'
                f'<div class="gauge g2"><i style="width:{fomo}%"></i></div>'
                f'<div class="gauge-label"><span>League-wide FOMO</span>'
                f'<span>{esc(entry["managers_chasing"])} managers chasing</span></div>'
                f'<p class="read">{esc(entry["bids"])} claims filed, '
                f'{esc(entry["completed_adds"])} completed, {esc(bid_text)} '
                f'({esc(entry["evidence"])}).</p>'
                f'{usage_line_html}'
                f'{gate_line}'
                f'{_bid_line(entry)}</div>'
            )
        note = (f'<div class="withheld"><span class="lab">Why no verdict</span>'
                f'{esc(shared_gate)}</div>' if shared_gate else "")
        body = f'<div class="hype">{"".join(cards)}</div>{note}'
    return _section("Waiver Hype Meter", 8, body) + section_waiver_market(market)


BENCH_HEAD = "On your bench"


def bench_phrase(entry: Mapping[str, Any]) -> str:
    """One bench player, as every surface names him.

    Shared by both renderers for the same reason edge_phrase is: three copies
    of one sentence is how the browser file, the email and the plain text end
    up describing a player three different ways.
    """
    if entry.get("out"):
        # The engine's own words for WHY (engine.solo_report.absence): a bye, a
        # reserve list, or last week's Out — which is not "can't play" (F2).
        return entry.get("out_text") or "can't play this week"
    # A questionable designation, dated (launch review BE-D3), or the practice
    # squad: wherever a lineup row names him, his own row says why.
    form = bench_form(entry)
    return f"{entry['note']} · {form}" if entry.get("note") else form


def bench_shows_form(entry: Mapping[str, Any]) -> bool:
    """A player who certainly cannot play shows only why; one out on last
    week's report may play, so his recent games stay beside his number."""
    return not entry.get("out") or entry.get("out_kind") == "designation"


def bench_form(entry: Mapping[str, Any]) -> str:
    """The bench player's recent games (or, before any, last season's rate)."""
    games = entry.get("games") or []
    if not games:
        # Before a game is played, last season is the reason he sits — the same
        # basis the week-1 lineup rows print. Nothing at all is a rookie or a
        # player the archive never saw: absent, never zero (RULE P1).
        per_game = entry.get("last_season_per_game")
        return (f"last season: {per_game:.1f} a game" if per_game is not None
                else "no games yet this season")
    shown = ", ".join(f"{v:.1f}" for v in games[-3:])
    return f"last {min(len(games), 3)}: {shown}"


def edge_phrase(slot: Mapping[str, Any]) -> str:
    """What this start beats, and by how much. ONE implementation, imported by
    the email renderer — the two surfaces had written it differently, and the
    longer wording wrapped every row of the email tape onto two lines.

    "on your bench" is load-bearing. The Tape's row grammar is *your player |
    position | their player*, so a bare "vs Larry Fitzgerald" named a third
    person in neither lineup — and since the calibrated unit is per-slot, the
    same bench player is legitimately named on four consecutive rows, which
    read as four openings against one man. It also disambiguates the number
    from the row's tint: the tint compares you to THEM, this compares your
    start to your own bench, and the two can honestly disagree.
    """
    edge = slot.get("edge")
    name = slot.get("alternative_name")
    if edge is None or not name:
        return ""
    # A gap inside rounding distance of zero must not print "-0.0 over" — the
    # sign of a hair's difference reads as a bug, and the honest fact is a
    # dead heat.
    if round(edge, 1) == 0:
        return f"even with {name} on your bench"
    return f"{edge:+.1f} over {name} on your bench"


def call_bits(slot: Mapping[str, Any]) -> list[str]:
    """What this start beats and how to read it, every surface's sub-line:
    the edge, then — launch review, Oct 2026 — the higher-projected bench
    player the odds skipped because he was questionable (BE-I1), and "toss-up"
    where either start is as good as the other (RQ-14/RQ-15; the % still
    prints). Engine facts only; nothing here computes a number."""
    bits = [b for b in (edge_phrase(slot),) if b]
    doubtful = slot.get("doubtful_alternative_name")
    # Only beside odds that print (recheck ENG-7): a row whose number a later
    # hold withheld — the practice squad, a held lineup, an ungraded shape —
    # read "…was questionable, so the odds are against Zach Ertz" with no odds.
    if doubtful and slot.get("alternative_name") and slot.get("confidence") is not None:
        value = slot.get("doubtful_alternative_projected")
        number = f" ({value:.1f})" if value is not None else ""
        why = slot.get("doubtful_alternative_why") or "was questionable"
        bits.append(f"{doubtful}{number} {why}, so the odds are against "
                    f"{slot['alternative_name']}")
    if slot.get("tossup"):
        bits.append("toss-up: either is fine")
    return bits


def form_phrase(slot: Mapping[str, Any]) -> str:
    """"2026: 17.2 a game · last 3: 22.1, 18.0, 9.4" — a starter's own games
    under the subscriber's scoring (launch review F8/SS-I9: bench rows printed
    their last three and starters never did, and a 15.3 projection sat beside
    no sign of a 27.5-a-game start). A record, never a projection. Named by
    its season — "this season" on a replayed 2024 sample would be read as now."""
    per_game = slot.get("season_per_game")
    if per_game is None:
        return ""
    last = list(slot.get("last_three") or [])
    shown = ", ".join(f"{v:.1f}" for v in last)
    season = slot.get("season_label")
    return (f"{season + ': ' if season else 'This season: '}{per_game:.1f} a game"
            + (f" · last {len(last)}: {shown}" if last else ""))


# Launch review F8: a hot start projected well below its average, with nothing
# saying why. The model is unchanged; this states what it does, in the
# buyer's words, true of every setup the product ships.
PROJECTION_NOTE = ("Why a projection can sit below a hot start: it leans toward "
                   "what his position usually scores, and allows for the chance "
                   "he misses time.")
HOT_START_GAP = 3.0


def projection_note(slots: Sequence[Mapping[str, Any]]) -> str:
    """PROJECTION_NOTE, only in a week where a starter's season average sits
    HOT_START_GAP or more above his projection — the week the question comes up."""
    for slot in slots:
        per_game, projected = slot.get("season_per_game"), slot.get("projected")
        if per_game is not None and projected is not None \
                and per_game - projected >= HOT_START_GAP:
            return PROJECTION_NOTE
    return ""


def who_can_cover(rivals: int | None, others: int | None) -> str:
    """Who else can afford the bid. ONE implementation, imported by the email
    renderer too — this sentence used to exist in three copies and the
    denominator was only ever added to one of them."""
    if rivals is None:
        return "we can't tell what anyone has left — see the note below"
    if rivals == 0:
        return "nobody else in your league can even cover that"
    # "11 of the other 11 teams can cover that" is a machine counting; a person
    # says everyone. The denominator earns its place only when it narrows.
    if others and rivals >= others:
        return "every other team in your league can cover that"
    # With a denominator the noun is always plural ("one OF the other 11
    # teams"); without one it agrees with the count ("one team").
    if others:
        noun = "teams"
        return f"{'one' if rivals == 1 else rivals} of the other {others} {noun} can cover that"
    return f"one team can cover that" if rivals == 1 else f"{rivals} teams can cover that"


def _bid_line(entry: Mapping[str, Any]) -> str:
    """What it takes to win this player HERE — the part rankings can't do."""
    bid = entry.get("bid_to_beat")
    if not bid:
        return ""
    who = who_can_cover(entry.get("rivals_who_can_pay"),
                        entry.get("league_others"))

    if entry.get("affordable") is False:
        left = entry.get("my_remaining")
        return (f'<div class="action no">→ It takes <b>{esc(bid)}</b> to top the highest '
                f'bid he\'s drawn, and you have <b>{esc(left)}</b> left. You can\'t win '
                f'this one — keep your budget for a player you can actually land.</div>')

    appetite = entry.get("league_top_appetite")
    tail = ""
    if appetite and appetite > bid:
        tail = (f' If someone really wants him, the biggest bid anyone still funded has '
                f'ever made is {esc(appetite)}.')
    return (f'<div class="action go">→ Bid <b>{esc(bid)}</b> or more to top the highest bid '
            f'he has drawn here — {esc(who)}.{tail}</div>')


def section_waiver_market(market: Mapping[str, Any] | None) -> str:
    """The league's waiver economy: what things cost, and who can still pay."""
    if not market:
        return ""
    rows = []
    if market.get("going_rate") is not None:
        # The unit rides on the FIRST chip only; the rest of the strip reads as
        # the same currency, and repeating "FAAB" five times is noise.
        rows.append(f'<span class="drv">Going rate '
                    f'<b>{esc(market["going_rate"])} FAAB</b></span>')
    if market.get("top_winning_bid") is not None:
        rows.append(f'<span class="drv">Priciest win <b>{esc(market["top_winning_bid"])}</b></span>')
    if market.get("my_remaining") is not None:
        rows.append(f'<span class="drv">You have <b>{esc(market["my_remaining"])}</b> left</span>')
    if market.get("rival_remaining") is not None:
        rows.append(f'<span class="drv">{esc(market["rival_label"])} has '
                    f'<b>{esc(market["rival_remaining"])}</b></span>')
    if market.get("rival_top_bid_shown"):
        rows.append(f'<span class="drv">They\'ve gone as high as '
                    f'<b>{esc(market["rival_top_bid_shown"])}</b></span>')
    if not rows:
        return ""
    note = ""
    if market.get("budget_note"):
        note = f'<p class="mkt">{esc(market["budget_note"])}</p>'
    lost = market.get("rival_claims_lost") or 0
    tell = ""
    if lost:
        tell = (f'<p class="mkt">{esc(market["rival_label"])} has lost <b>{esc(lost)}</b> '
                f'claim{"s" if lost != 1 else ""} this season — every one of those is a '
                f'price they were willing to pay and didn\'t get.</p>')
    return _section("The Waiver Market In Your League", 0,
                    f'<div class="drivers">{"".join(rows)}</div>{tell}{note}'
                    f'<p class="mkt">{esc(market.get("evidence", ""))}</p>')


def section_receipts(receipts: Mapping[str, Any]) -> str:
    record = receipts.get("record")
    if not record:
        # D12: the stamp promises next week only where this report has odds
        # and a next report exists; the league product's dict carries none.
        stamp = receipts.get("stamp", "Results · from next week")
        inner = (f'{esc(receipts.get("note", ""))}'
                 + (f'<br><span class="stamp">{esc(stamp)}</span>' if stamp else ""))
    elif receipts.get("last_week_calls") is not None:
        from engine.own_record import call_line
        rows = "".join(f'<li>{esc(call_line(c))}</li>'
                       for c in receipts["last_week_calls"])
        ask = (f'<br>{esc(receipts["ask"])}' if receipts.get("ask") else "")
        inner = (f'{esc(receipts.get("note", ""))}<ul class="receipts">{rows}</ul>'
                 f'<span class="stamp">Graded on real box scores</span>{ask}')
    else:
        parts = [esc(receipts.get("note", ""))]
        best, worst = receipts.get("best_call"), receipts.get("worst_call")
        if best:
            parts.append(
                f' Best call: <b>{esc(best["recommended"])} over {esc(best["over"])}</b> '
                f'(week {esc(best["week"])}, +{best["margin"]:.1f}).')
        if worst:
            parts.append(
                f' Worst: {esc(worst["recommended"])} over {esc(worst["over"])} '
                f'(week {esc(worst["week"])}, {worst["margin"]:.1f}). '
                f'Both stay on the ledger.')
        inner = "".join(parts) + '<br><span class="stamp">Graded on real box scores</span>'
    return _section("The Receipts", 9, f'<div class="ledger">{inner}</div>')


# What a sample promises a buyer (INFO-113): three scoring settings, not every
# league's rules, and the day-one report is this week's only from Week 2 and
# before the week's games start (run/intake._first_file).
JOIN_PROMISE = ("Yours is built from your own roster, under the scoring you pick "
                "(full PPR, half PPR or standard). Your first report lands the day "
                "you join: this week's lineup, or your roster report if it's before "
                "Week 2 or the week's games are underway. Then a new one every "
                "Tuesday of the season.")


def demo_band(meta: Mapping[str, Any]) -> str:
    """The public sample's closing ask. DEMO SURFACES ONLY.

    The sample report is the highest-intent page in the funnel — a reader here
    has just finished due diligence — and it used to end at a footer with zero
    links to the picker. Never rendered in a live subscriber report: selling a
    subscriber the thing they already own reads as spam.

    A navy card with the landing's gold button (panel review I3): the ask used
    to be one underlined "set it up" inside a box tinted like an error.
    """
    if not meta.get("anonymized_demo"):
        return ""
    if meta.get("solo") and meta.get("live_demo"):
        return (
            '<div class="ctacard"><p>This is this week\'s report for a sample '
            f'roster. {esc(JOIN_PROMISE)}</p>'
            f'{sample_cta()}</div>')
    if meta.get("solo"):
        season = esc(str(meta.get("season", "a past")))
        # The two published samples point at each other on purpose. A buyer
        # decides on a mid-season file and then receives a WEEK ONE file, which
        # carries no number anywhere by design — and a gap between what was
        # sold and what arrives is a refund with a stamp on it. Each page says
        # what the other one shows.
        companion = (
            'A mid-season report, once the season has a record to read, looks '
            'like <a href="sample-report.html">this</a>. '
            if meta.get("first_week_demo") else
            ''
        )
        return (
            f'<div class="ctacard"><p>This report is from the {season} season. '
            f'{companion}{esc(JOIN_PROMISE)}</p>'
            f'{sample_cta()}</div>'
        )
    return (
        '<div class="regret-note" style="margin:14px 0 0;text-align:center;">'
        'This file is from a 2018 sample league. Yours is about <b>your</b> rival — '
        '<a href="join/index.html" style="color:var(--brick);font-weight:700;">'
        'pick them</a> and the first one lands Tuesday.</div>'
    )


# On a registry row, and so in meta["plan"] (run/tuesday.py), this word means
# the League Pass PAYER: billed $99 a year, covering their league's seats.
# Before Oct 2026 a payer's row was flattened to "season" and their report
# could not tell (panel review LP-D3); SEAT_PLAN above is the seat.
PASS_PLAN = "pass"


def in_pass_league(meta: Mapping[str, Any]) -> bool:
    """A weekly report for somebody in a league its League Pass covers: the
    payer, or a seat."""
    return meta.get("plan") in (PASS_PLAN, SEAT_PLAN)


def _site() -> str:
    return os.environ.get("SITE_URL", "").rstrip("/")


def league_seat_link(meta: Mapping[str, Any]) -> str | None:
    """Where a leaguemate claims the seat their league's pass already paid
    for — while the pass still has a seat to give.

    Only the per-pass link (``meta["seat_link"]``, set by the run when it can
    sign one): it is the ONLY way a seat is claimed (contract C3 — the generic
    ``?pass=1`` page that matched a seat by the buyer's typed address is
    closed, so the "you'll need the email the pass was bought with" note that
    rode beside it is gone too). D10: that generic page rendered exactly when
    UPDATE_SECRET was unset — the one state in which no seat claim can be
    confirmed. And a full pass (``meta["seats_full"]``) has no seat to offer."""
    link = meta.get("seat_link")
    if (isinstance(link, str) and link.startswith("https://")
            and not meta.get("seats_full")):
        return link
    return None


def _forward_text(meta: Mapping[str, Any]) -> str:
    """The forward line's words, shared by every surface (both HTML footers
    escape it; the text half prints it as is). Empty when there is nowhere to
    send anyone."""
    site = _site()
    link = league_seat_link(meta) if in_pass_league(meta) else None
    if link:
        # A seat's or a payer's report, forwarded to the league: the reader's
        # seat is already paid for. It used to send them to the $39 checkout
        # (panel review LP-D2). Only while the pass has a seat left (D10);
        # a full pass falls back to the plain line, which is true of anyone.
        return ("Got this from a leaguemate? Your league's pass already covers "
                f"your seat — claim it, free, with your own roster: {link}")
    if not site:
        return ""
    return (f"Got this from a leaguemate? Every manager gets their own report, "
            f"built from their own roster — {site}/join.")


def _linked(words: str, link: str | None = None) -> str:
    """``words`` escaped, with ``link`` (when it appears) made tappable: a
    seat link a leaguemate has to copy out of running text is one fewer seat
    claimed. Every href here is https (tests/test_email_safety.py)."""
    text = esc(words)
    if link and link.startswith("https://") and esc(link) in text:
        text = text.replace(esc(link), f'<a href="{esc(link)}">{esc(link)}</a>', 1)
    return text


def _forward_line(meta: Mapping[str, Any] | None = None) -> str:
    """The standing acquisition line, above the cancellation block.

    A forwarded report is the one organic touch with the eleven best prospects
    a subscriber knows. Gated on SITE_URL (set at launch, with the domain):
    a call to action with nowhere to go is worse than none. A pass payer whose
    report carries the seat count already shows the seat link there.
    """
    meta = meta or {}
    if seats_text(meta) or meta.get("historical_demo") or meta.get("live_demo"):
        # A published sample is not forwarded by anybody: its own ask is the
        # closing card (demo_band).
        return ""
    words = _forward_text(meta)
    if not words:
        return ""
    seat = league_seat_link(meta) if in_pass_league(meta) else None
    link = seat or f"{_site()}/join"
    return f"{_linked(words, link)}<br>"


def seats_text(meta: Mapping[str, Any]) -> str:
    """The League Pass payer's one count line (``meta["seats_claimed"]``, set
    by the run): how many of the pass's seats are claimed, and where the rest
    claim theirs. Counts only — never a name or an address. Empty for
    anybody but a payer, or when the count is unreadable.

    D10: the count is SEATS ONLY (the payer's own team is not one) against the
    pass's seat cap, the way the cap is enforced — it used to add the payer and
    compare with the league size, so one seat still open read "12 of 12" with
    the link gone, and the designed full state read as an error."""
    seats = meta.get("seats_claimed")
    if meta.get("plan") != PASS_PLAN or not isinstance(seats, Mapping):
        return ""
    claimed, size = seats.get("claimed"), seats.get("size")
    if (not isinstance(claimed, int) or not isinstance(size, int)
            or isinstance(claimed, bool) or isinstance(size, bool)
            or claimed < 0 or size < 1):
        return ""
    count = f"League Pass: {claimed} of {size} seats claimed."
    # The buyer's one control over WHO holds the seats (APPSEC-2): the link
    # is forwardable, the count names nobody (C2), so a reset — the link
    # changes, every seat is released, the league claims again — is the
    # remedy for seats they don't recognize (run/seat_resets.py).
    reset = SEAT_RESET_LINE if claimed else ""
    if claimed >= size:
        return f"League Pass: Every seat is claimed.{reset}"
    link = league_seat_link(meta)
    if not link:
        return f"{count}{reset}"
    return (f"{count} Your leaguemates claim theirs, free, with their own "
            f"roster: {link}{reset}")


# What a payer whose seats are held by people they don't know can do. No
# colon in it: the footers split the line on its first ": ".
SEAT_RESET_LINE = (" Seats you don't recognize? Reply \"reset seats\" and we'll "
                   "change your league's link and clear every seat, so your league "
                   "claims again with the new one.")


def seats_line(meta: Mapping[str, Any]) -> str:
    """The HTML twin of seats_text, for the footer."""
    words = seats_text(meta)
    if not words:
        return ""
    seat = league_seat_link(meta)
    label, _, rest = words.partition(": ")
    return (f"<b>{esc(label)}:</b> "
            f"{_linked(rest, seat)}<br>")


def read_line(meta: Mapping[str, Any]) -> str:
    """A subscriber's first report can be a lot of new words at once ("proj",
    "touches", "if/then"). The glossary lives on the How it works page; this
    puts it one tap from the report, for subscribers only — never the samples,
    where the reader is not yet a subscriber and the page itself explains. Gated
    on SITE_URL like the forward line: a link with nowhere to go is worse than
    none."""
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if not site or not meta.get("solo") or meta.get("historical_demo") \
            or meta.get("live_demo") or meta.get("trial"):
        return ""
    return (f'<b>New to this report?</b> What each part means: '
            f'<a href="{esc(site)}/how-it-works.html#read">'
            f'{esc(site)}/how-it-works.html#read</a><br>')


def read_lines(meta: Mapping[str, Any]) -> list[str]:
    """The plain-text twin."""
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if not site or not meta.get("solo") or meta.get("historical_demo") \
            or meta.get("live_demo") or meta.get("trial"):
        return []
    return ["", f"NEW TO THIS REPORT? What each part means: {site}/how-it-works.html#read"]


SEASON_END_HEAD = "The season's end"

# What the season's last report says about money and next season, per plan
# (meta["plan"], render/report.PASS_PLAN and SEAT_PLAN). Each is that plan's
# own promise, repeated. A League Pass seat is CLAIMED, each season, with that
# season's roster — so a seat is never told its reports simply start again
# (panel review LP-D3, LP-D5).
SEASON_END_BILLING = {
    # D1: the monthly plan's final paid month is the one the season's last
    # weekly report falls in — this report's — and nothing bills after it.
    "monthly": "Your monthly plan stops billing on its own: this report falls "
               "in your last paid month, so there's nothing to cancel.",
    # D8: a derived Week 1 is never built before run.solo.week_one_due (9 days
    # before its first kickoff), so Week 1 arrives in kickoff week, September.
    "season": "Your season pass renews once a year, on the day you bought it, "
              "and we email you before it does. Reports start again with "
              "Week 1 next September.",
    PASS_PLAN: "Your League Pass renews once a year, on the day you bought it, "
               "and we email you before it does. Your league's seats come back "
               "with it: each manager claims theirs again next season, with "
               "their new roster.",
    # The payer's sentence, from the seat's side (COPY:F6). "Reports for this
    # seat end here" was a promise nothing kept: a claim lives as a form row
    # for 400 days and the intake honours it while the payer holds a pass, so
    # a renewed pass carried this season's roster into next season's reports.
    # Both lines now say the same thing — the seat follows the pass, and the
    # claim with a new roster is made again — which is true either way.
    SEAT_PLAN: "Your seat follows your league's pass: if it renews, claim your "
               "seat again next season with your new roster.",
}


ONCE_END = ("Your pass covered this season through this report: nothing renews "
            "and nothing more is charged.")
ONCE_SEAT_END = ("Your seat came with your league's pass for this season, and "
                 "this is its last report.")


# Week 1 next season is built from the roster on file — last season's, until
# it is changed. Said only where this report carries a route that works.
NEW_ROSTER = ("After your draft, send us your new roster from the update link "
              "in this email.")


def season_end_lines(meta: Mapping[str, Any]) -> list[str]:
    """What a report says in the season's last two weeks (both renderers).

    Week 17 is championship week under ESPN's, Yahoo's and Sleeper's default
    playoffs, so a subscriber may be reading their last report a week early
    without knowing whether another is coming. Week 18 is when teams with
    nothing left to play for rest starters — news that mostly lands after the
    Friday injury report the Saturday check reads — and nothing told a
    subscriber the reports were ending or what happens to their billing.
    The billing sentence is the plan's own promise, repeated; it renders only
    for a subscriber (``meta["plan"]``, set by run/tuesday.py), never on a
    sample or a free report."""
    week, last = meta.get("week"), meta.get("last_week")
    if not meta.get("solo") or meta.get("historical_demo") \
            or not isinstance(week, int) or not isinstance(last, int):
        return []
    if week == last - 1:
        # A free report's reader gets no Tuesday report (EMAILS-58).
        follow = (f"subscribers get a report for it too, the season's last."
                  if meta.get("trial") else
                  f"next Tuesday's report covers it, and it's the season's last.")
        return [f"Week {week} is championship week under ESPN's, Yahoo's and "
                f"Sleeper's default settings. If your league plays Week {last}, "
                + follow]
    if week != last:
        return []
    lines = [f"Week {last} is when NFL teams with nothing left to play for rest "
             f"starters, and many of those calls come after Friday's injury "
             f"report. Check each team's inactives, posted 90 minutes before "
             f"kickoff."]
    billing = SEASON_END_BILLING.get(meta.get("plan"))
    if billing and meta.get("one_time"):
        # A one-time pass ends here; there is no renewal to describe.
        billing = (ONCE_SEAT_END if is_seat(meta) else ONCE_END)
    if billing:
        # Renewing plans start again next season from the roster on file
        # (EMAILS-62): the update link is how a new one reaches us.
        if (meta.get("plan") in ("season", PASS_PLAN) and meta.get("update_url")
                and not meta.get("one_time")):
            billing += " " + NEW_ROSTER
        lines.append("This is the season's last report. Thanks for playing it "
                     "with us. " + billing)
    return lines


UPDATE_HEAD = "Roster changed?"
# The Saturday check runs at 16:17 UTC with no intake of its own, and a change
# takes two hourly intakes (the code out, the press in), so "by Saturday
# morning" missed for anyone after about 10:47 AM ET (EMAILS-43/44).
UPDATE_BODY = ("Update it here by Friday night (ET) — your final check and your "
               "next report use it. We'll email you a button to confirm:")
UPDATE_REPLY = ("Reply to this email with your updated roster and your next report "
                "follows it.")
# The season's last report has no next report to follow a change, so the reply
# route goes and the link keeps only what is still true of it.
UPDATE_BODY_LAST = ("Update it here by Friday night (ET) — your final check uses "
                    "it. We'll email you a button to confirm:")


def reply_update_works() -> bool:
    """Can a roster emailed to us be applied? Only through ``make
    roster-update``, which needs the form backend and the signing secret
    (run/updates.main) — without them "reply and your next report follows
    it" was a promise nobody could keep (EMAILS-45), so it is not made."""
    return bool(os.environ.get("UPDATE_SECRET", "").strip()
                and os.environ.get("FORM_ENDPOINT", "").strip())


def _last_report(meta: Mapping[str, Any]) -> bool:
    return meta.get("last_week") is not None and meta.get("week") == meta.get("last_week")


def roster_as_of(meta: Mapping[str, Any]) -> str:
    """"This report used your roster as of Oct 3." — the day the roster in use
    was set (``meta["roster_as_of"]``: the signup, or the last confirmed
    update). A subscriber whose trade has not reached us can see at a glance
    that this report predates it, beside the route that fixes it. Empty when
    the run did not say, or said something that is not a date.

    The year prints when it is not the report's season (LP2-D3): a renewed
    season pass keeps the roster from its purchase day, and "as of Aug 20"
    on a 2026 report read as last week's roster when it was last season's."""
    from datetime import date
    raw = meta.get("roster_as_of")
    try:
        day = date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        day = None
    if day is None or not is_subscriber_report(meta):
        return ""
    season = str(meta.get("season") or "")
    year = f", {day.year}" if season.isdigit() and int(season) != day.year else ""
    return f"This report used your roster as of {day:%b} {day.day}{year}."


# The update link is PUBLIC and grants nothing (run/updates.py, confirm-by-
# email). The tokenised link it replaced sat right under the forward line and
# asked subscribers to forward a credential to the league it was framed
# against (removed Aug 27 2026). This one may be forwarded: a leaguemate who
# uses it only sends the real subscriber a confirmation they can ignore.
def update_line(meta: Mapping[str, Any]) -> str:
    """Shared by both HTML renderers. The link renders only when the whole
    flow can work (site, backend, secret — run/updates.public_update_url);
    until then, the reply route the FAQ already promises."""
    url = meta.get("update_url")
    if (not meta.get("solo") or meta.get("historical_demo")
            or meta.get("live_demo") or meta.get("trial")):
        return ""
    as_of = roster_as_of(meta)
    dated = f" {esc(as_of)}" if as_of else ""
    if not url:
        if _last_report(meta) or not reply_update_works():
            return f"{esc(as_of)}<br>" if as_of else ""
        return f'<b>{esc(UPDATE_HEAD)}</b>{dated} {esc(UPDATE_REPLY)}<br>'
    body = UPDATE_BODY_LAST if _last_report(meta) else UPDATE_BODY
    return (f'<b>{esc(UPDATE_HEAD)}</b>{dated} {esc(body)} '
            f'<a href="{esc(url)}">{esc(url)}</a><br>')


def update_lines(meta: Mapping[str, Any]) -> list[str]:
    """The plain-text twin."""
    if (not meta.get("solo") or meta.get("historical_demo")
            or meta.get("live_demo") or meta.get("trial")):
        return []
    url = meta.get("update_url")
    as_of = roster_as_of(meta)
    dated = f" {as_of}" if as_of else ""
    if not url and (_last_report(meta) or not reply_update_works()):
        return ["", as_of] if as_of else []
    body = UPDATE_BODY_LAST if _last_report(meta) else UPDATE_BODY
    return ["", f"{UPDATE_HEAD.upper()}{dated} "
            + (f"{body} {url}" if url else UPDATE_REPLY)]


def footer(meta: Mapping[str, Any]) -> str:
    basis = availability_basis(meta)
    demo = ("Sample report built from a real past season, to show what you get. "
            if meta.get("historical_demo") else "")
    # The gap COUNT is operator bookkeeping; a buyer only needs to know that
    # anything unproven was withheld, which the report already says in place.
    gap_line = ""
    return (
        f'{demo_band(meta)}'
        f'<footer><b>Beat Your League</b> — {esc(BRAND_LINE)}'
        f'<br>{esc(demo)}{esc(basis)}{esc(gap_line)}<br>'
        f'{read_line(meta)}'
        f'{update_line(meta)}'
        f'{seats_line(meta)}'
        f'{_forward_line(meta)}'
        f'{esc(NO_BETTING_LINE)}<br>'
        f'{esc(source_line(meta))}<br>'
        f'{sender_html()}'
        # Every commercial email needs a working way out. For a paid
        # subscription it is the self-serve cancel, which costs the reader
        # about a minute and the operator nothing — no inbox to watch. The
        # unsubscribe-vs-cancel distinction stays: stopping emails while
        # billing continues is how you earn a chargeback and deserve it. A
        # seat has nothing to cancel, so it gets its stop route instead.
        f'{cancel_html(stop_route(meta), sample=bool(meta.get("anonymized_demo")))}'
        '</footer>'
    )


# A numbered section emits this instead of a literal number; ``number_sections``
# fills them in document order once the page is assembled. NUL cannot appear in
# the rendered HTML, so the substitution can never hit real content.
SECTION_MARK = "\x00SECTION\x00"


def _section(title: str, n: int, body: str) -> str:
    # Zero-padded, not "§n": the section sign is legal/academic citation
    # register. "01" reads like a case file, which is the register the product
    # actually sells ("the file on Mike"). ``n`` now says only WHETHER the
    # section is numbered — see number_sections for why.
    marker = f'<span class="n">{SECTION_MARK}</span>' if n else ""
    return (
        f'<section><div class="eyebrow"><span class="tag">{esc(title)}</span>'
        f'{marker}</div>{body}</section>'
    )


def number_sections(html: str) -> str:
    """Number the numbered sections by POSITION, once the page is assembled.

    Each section used to carry its own hardcoded number, which meant the
    sequence was only correct as long as nobody added or merged one. Merging
    the two lineup grids into the Tape took the rival grid's 04 and orphaned
    03, and adding last week's result had already duplicated 02 — so the
    shipped report read 01, 02, 02, 04. A case file that skips a page reads as
    broken software, on a product sold on numeric discipline. Position is the
    only source that cannot drift from what is actually on the page.
    """
    count = 0

    def fill(_match: "re.Match[str]") -> str:
        nonlocal count
        count += 1
        return f"{count:02d}"

    return re.sub(re.escape(SECTION_MARK), fill, html)


# --------------------------------------------------------------------- #
# page assembly
# --------------------------------------------------------------------- #

def anonymize_for_public(report: Mapping[str, Any]) -> dict[str, Any]:
    """Swap real league identities for neutral labels, for the PUBLIC demo only.

    A live subscriber report names the rival on purpose — it goes to the one
    person entitled to see it. The demo on the marketing site is a different
    thing: it would put a real stranger's name, habits and weak spots on a
    sales page they never agreed to appear on. Numbers are untouched; only the
    labels change, and the banner says so.
    """
    import copy
    out = copy.deepcopy(dict(report))
    meta = out["meta"]
    swaps = {
        str(meta.get("my_label") or ""): "Your Team",
        str(meta.get("rival_label") or ""): "Rival Manager",
        str(meta.get("named_rival_label") or ""): "Your Named Rival",
    }
    # LAST WEEK'S opponent is a different manager from this week's, and their
    # name is baked into a prose headline. Every label that can reach the page
    # has to be in this map or the scrub misses it — which it did, and the
    # public-naming guard caught it.
    prior = out.get("last_week") or {}
    if prior.get("opponent_label"):
        swaps[str(prior["opponent_label"])] = "Last Week's Opponent"
    swaps.pop("", None)
    meta["my_label"] = "Your Team"
    meta["rival_label"] = "Rival Manager"
    if meta.get("named_rival_label"):
        meta["named_rival_label"] = "Your Named Rival"
    meta["league_name"] = "a 12-team Sleeper league"
    meta["anonymized_demo"] = True

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for real, fake in swaps.items():
                value = value.replace(real, fake)
            return value
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        return value

    return scrub(out)


def compose(report: Mapping[str, Any]) -> list[str]:
    """The sections, in order, for whichever product this report came from.

    A SOLO report has no opponent (PLAN §0), so the sections that describe one
    are not gated here — they are absent. Rendering an empty Tape half or a
    permanently withheld fragility list would advertise a feature we removed on
    purpose, and CLAUDE.md's rule is that a stated omission reads as focus while
    a silent one reads as unfinished. The site states it; the report just does
    not carry it.
    """
    meta = report["meta"]
    if meta.get("solo"):
        return [
            header(meta, team_name(report)),
            section_checklist(report["checklist"]),
            section_your_week(report["matchup"], report.get("no_opponent")),
            section_your_lineup(report),
            section_regret(report["regret"]),
            section_pivots(report["pivots"], report["meta"], report.get("pivots_note")),
            section_rising(report.get("rising") or []),
            section_receipts(report["receipts"]),
            footer(meta),
        ]
    return [
        header(meta),
        section_checklist(report["checklist"]),
        section_last_week(report.get("last_week")),
        section_matchup(report["matchup"]),
        section_rival_watch(report.get("rival_watch")),
        section_tape(report),
        section_fragility(report["fragility"], meta["rival_label"]),
        section_regret(report["regret"]),
        section_pivots(report["pivots"], report["meta"], report.get("pivots_note")),
        section_hype(report["hype"], report.get("waiver_market")),
        section_receipts(report["receipts"]),
        footer(meta),
    ]


@buyer_slots
def render(report: Mapping[str, Any], template_html: str) -> str:
    style, links = extract_design(template_html)
    style += MARK_CSS
    meta = report["meta"]
    body = "".join(compose(report))
    body = number_sections(body)
    title = (f'Beat Your League — {meta["season"]} Week {meta["week"]} '
             + ("Report" if meta.get("solo") else "Rival Report"))
    # Only the public demo gets share meta: it is the one render of this
    # template that lives on the open web. Subscriber reports are private —
    # share tags on them would just invite pasting a paid report around.
    social = ""
    if meta.get("anonymized_demo"):
        # Said of THIS sample (INFO-99): a mid-season week is built from what
        # was out before its games; Week 1 has only last season behind it.
        desc = (("Week 1 of a real NFL season, built the way yours will be: "
                 "slots ordered by last season's box scores, nothing invented.")
                if meta.get("solo") and meta.get("first_week_demo") else
                ("A complete weekly report for a real NFL week, built from the box "
                 "scores and injury report out before its games — nothing invented.")
                if meta.get("solo") else
                ("A complete Rival Report built from a real league's season — "
                 "every number from actual box scores, nothing invented."))
        social = (
            f'<meta name="description" content="{desc}">\n'
            + ('<meta property="og:title" content="Beat Your League — a real weekly report">\n'
               if meta.get("solo") else
               '<meta property="og:title" content="Beat Your League — a real Rival Report">\n')
            + f'<meta property="og:description" content="{desc}">\n'
            '<meta property="og:type" content="website">\n'
            '<meta property="og:site_name" content="Beat Your League">\n'
            + SOCIAL_IMAGE_TAGS
        )
    favicon = FAVICON_LINK + '\n'
    # The three public samples are indexable pages with one address each; a
    # subscriber's private archive is neither, so it carries no canonical.
    if meta.get("anonymized_demo"):
        page = ("sample-first-week.html" if meta.get("first_week_demo")
                else "this-week.html" if meta.get("live_demo") else "sample-report.html")
        favicon += f'<link rel="canonical" href="{SITE_ORIGIN}/{page}">\n'
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{PAGE_META}<title>{esc(title)}</title>\n{social}{favicon}'
        f'{font_preloads()}{links}\n<style>{style}</style>\n'
        f'</head>\n<body>\n<div class="report">\n{landmarks(body)}\n</div>\n'
        f'</body>\n</html>\n'
    )


def landmarks(body: str) -> str:
    """The page body with its landmarks: the masthead stays the banner, the
    footer the contentinfo, and everything between them is <main>.

    The generated pages had no <main> at all, so a screen reader's "skip to
    main content" had nowhere to go and axe flagged every section as content
    outside a landmark (panel review D9). The notices and the closing ask sit
    inside main: they are the page's content, not its chrome."""
    head, sep, rest = body.partition("</header>")
    if not sep:
        return f'<main id="main">{body}</main>'
    middle, foot_sep, foot = rest.rpartition("<footer>")
    if not foot_sep:
        return f'{head}{sep}<main id="main">{rest}</main>'
    return f'{head}{sep}<main id="main">{middle}</main>{foot_sep}{foot}'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=REPO_ROOT / "data" / "processed" / "week_report.json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--public", action="store_true",
        help="anonymise league identities (the marketing demo, never a live report)")
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"{args.input} not found — run `python -m engine.week_report` first",
              file=sys.stderr)
        return 1
    report = json.loads(args.input.read_text(encoding="utf-8"))
    if args.public:
        report = anonymize_for_public(report)
    template_html = TEMPLATE_PATH.read_text(encoding="utf-8")

    meta = report["meta"]
    output = args.output or (
        REPO_ROOT / "reports" /
        f'rival-report-{meta["season"]}-w{int(meta["week"]):02d}-r{meta["my_roster_id"]}.html'
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(report, template_html), encoding="utf-8")
    print(f"report rendered to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
