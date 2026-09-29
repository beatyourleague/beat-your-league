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
from typing import Any, Mapping

from ingest.nflverse import ATTRIBUTION

REPO_ROOT = Path(__file__).resolve().parent.parent
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
              "every Tuesday.")
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
CANCEL_BODY = ("Cancel it yourself from your own billing page — it takes about "
               "fifteen seconds and stops the billing immediately; the exact "
               "steps are on our terms page. "
               "Unsubscribing from emails alone does not stop a subscription, "
               "so cancel there if you want the charges to end.")
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
        return f"{site}/terms.html#cancel", "the exact steps, on our terms page"
    return "", ""


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
    """
    return (f"The % is the chance your starter outscores your best bench "
            f"player at that spot, and the bar starts at 50% (a toss-up). We only "
            f"give odds when both players are confirmed to play. Rows without "
            f"odds this week: {listed}.")


# §5 of the early-season method (Grade B): the seed moves every number in the
# lineup — seating, projections, edges — not only the calls that carry a
# row-level flag, so the section says so once, in the buyer's words.
SEEDED_SECTION_LINE = ("This early in the season, last season is counted into "
                       "every number here; each call that leans on it says so "
                       "on its row. Three weeks in, the numbers stand on this "
                       "season alone.")


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
    ("availability in doubt", "one of the two players is questionable"),
    ("not a live head-to-head", "one of the two players is out"),
    ("nobody on your bench", "no bench player at that position"),
    ("not enough games", "not enough games played yet"),
    ("we don't put odds on defenses", "defenses get a projection only"),
    ("no eligible player", "no eligible player with a scoring record"),
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
    if gate.startswith("we don't put odds on defenses"):
        return "projection only"
    if gate.startswith("not enough games"):
        return "odds after 3 games"
    if gate.startswith("nobody on your bench"):
        return f"no bench {slot.get('slot', '')}".strip()
    if gate.startswith("no eligible player") or not gate:
        return ""
    if starter_ok and alt:
        # "waiting on", not "questionable": the row belongs to the STARTER,
        # and the plain fact is that his odds wait on the bench player's news.
        return f"start · waiting on {alt}"
    if gate.startswith("availability in doubt"):
        return "questionable · see if/then"
    return "status open · see if/then"


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
    if gate.startswith("no eligible player"):
        return NO_CALL
    return f"{NO_CALL} · status unconfirmed"


def availability_basis(meta: Mapping[str, Any]) -> str:
    """The data-age sentence (principle 3), shared by both renderers.

    The engine names the information set itself ("the week 9 injury report,
    the last complete one before this file goes out"), which is true of a
    live Tuesday file and of a replayed sample alike. A bare timestamp is
    humanised if one ever arrives: a raw ISO stamp on a buyer surface — a 2026
    download time on a 2024 report — made a cold reader doubt what year they
    were looking at.
    """
    availability = meta.get("availability_as_of")
    if availability:
        try:
            stamp = datetime.fromisoformat(str(availability)).astimezone(timezone.utc)
            availability = stamp.strftime("%a %b %d, %H:%M UTC")
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
    """The one honest way a missing number renders (principle 3)."""
    return (f'<div class="withheld"><span class="lab">{esc(NOT_CALLING_IT)}</span>'
            f'{esc(reason)}</div>')


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

def header(meta: Mapping[str, Any]) -> str:
    chips = [
        f'<span class="chip"><b>{esc(meta["league_name"])}</b>'
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
    banner = ""
    if meta.get("historical_demo") and meta.get("solo"):
        # The solo sample is built from the nflverse record, where past-season
        # injury reports ARE available — so confidences print, and the old
        # "numbers are left off" sentence would be false of the page it sits on.
        banner = (
            '<div class="regret-note" style="margin:0;border-left:none;">'
            f'SAMPLE REPORT — a real week from the {esc(meta["season"])} NFL season, '
            f'built exactly the way yours will be: one roster, scored its league\'s '
            f'way, from that week\'s box scores and injury reports.</div>'
        )
    elif meta.get("historical_demo"):
        banner = (
            '<div class="regret-note" style="margin:0;border-left:none;">'
            f'SAMPLE REPORT — real data from the {esc(meta["season"])} season of '
            f'{esc(meta["league_name"])}, built to show exactly what lands in your inbox '
            f'on a Tuesday. Because it\'s a past season we can\'t check who was hurt or '
            f'inactive back then, so the confidence numbers are left off — in a live week '
            f'you get them on every slot where both players are confirmed active.'
            + (' Team and manager names here are placeholders; every number is that '
               'league\'s real record.' if meta.get("anonymized_demo") else "")
            + '</div>'
        )
    brand = f'<div class="brand">{mark_svg("bylm")}<span>Beat Your League</span></div>'
    if meta.get("anonymized_demo"):
        # The published samples are site pages a visitor reaches from the
        # landing page, and they had no way back to it. A subscriber's own
        # report is opened from their inbox and keeps the plain masthead.
        brand = (
            '<div style="display:flex;align-items:center;justify-content:space-between;'
            'gap:12px;flex-wrap:wrap;">'
            f'<a class="brand" href="index.html" style="text-decoration:none;">'
            f'{mark_svg("bylm")}<span>Beat Your League</span></a>'
            '<a class="home" href="index.html" style="font-family:\'Barlow\',sans-serif;'
            'font-weight:600;font-size:14px;line-height:1;white-space:nowrap;'
            'text-decoration:none;color:var(--paper);padding:8px 15px;'
            'border:1.5px solid rgba(246,244,238,.45);border-radius:999px;">'
            '← Home</a></div>'
        )
    return (
        f'<header class="bug">{brand}'
        f'<h1>Week {esc(meta["week"])} · {"Your Report" if meta.get("solo") else "Rival Report"}</h1>'
        f'<div class="chips">{"".join(chips)}</div></header>{banner}'
    )


def _generated_stamp(meta: Mapping[str, Any]) -> str:
    raw = meta.get("generated_at", "")
    try:
        stamp = datetime.fromisoformat(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return "Generated (timestamp unavailable)"
    if meta.get("historical_demo"):
        # The sample is a replay: say so in the stamp itself, or the build
        # date and the season it replays look like a contradiction.
        return stamp.strftime(f"Rebuilt %b %d, %Y from the {meta.get('season')} "
                              f"season archive")
    return stamp.strftime("Generated %a %b %d · %H:%M UTC")


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
        bits = []
        edge = edge_phrase(slot)
        if edge:
            bits.append(edge)
        if slot.get("usage"):
            bits.append(str(slot["usage"]))
        flags = [f["text"] for f in (slot.get("flags") or [])]
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
        elif (mixed and slot.get("player_name")
                and not is_structural_gate(slot.get("confidence_gate"))):
            shown_marker = True
            call = f'<span class="tsub">{esc(row_label(slot))}</span>'
        else:
            call = ""
        rows.append(
            f'<tr class="trow"><td class="tslot">{esc(slot["slot"])}</td>'
            f'<td class="tside you"><span class="tname">{esc(name)}</span>'
            + (f'<span class="tflag">{esc(" · ".join(flags))}</span>' if flags else "")
            + (f'<span class="tsub">{esc(" · ".join(bits))}</span>' if bits else "")
            + f'</td><td class="tpts you">{proj}</td>'
            f'<td class="tcall">{call}</td></tr>')
    head = ('<tr class="thead"><td></td><td>Your lineup</td>'
            '<td style="text-align:right">Proj</td><td>Call</td></tr>')
    note = ""
    gates = {s["confidence_gate"] for s in slots if s.get("confidence_gate")}
    if gates:
        head_text = no_call_head(shown_marker, mixed)
        note = (f'<div class="withheld"><b>{esc(head_text)}</b> '
                f'{esc(no_call_explainer(gate_list(gates)))}</div>')
    seeded_note = (f'<div class="withheld">{esc(SEEDED_SECTION_LINE)}</div>'
                   if report["meta"].get("seeded") else "")
    return _section("The Lineup", 3,
                    f'<table class="tape">{LINEUP_COLS}{head}'
                    f'{"".join(rows)}</table>{_bench_table(report)}'
                    f'{seeded_note}{note}')


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
               f'<span class="trank">{esc(rank)} last season</span>'
               if entry.get("notable") and rank else "")
        rows.append(
            f'<tr class="trow bench"><td class="tslot">{esc(entry["position"])}</td>'
            f'<td class="tside you"><span class="tname">{esc(entry["name"])}</span>'
            f'{tag}'
            + ("" if entry.get("out")
               else f'<span class="tsub">{esc(bench_phrase(entry))}</span>')
            + '</td>'
            f'<td class="tpts you">{proj}</td><td class="tcall"></td></tr>')
    head = (f'<tr class="thead"><td></td><td>{esc(BENCH_HEAD)}</td>'
            '<td style="text-align:right">Proj</td><td></td></tr>')
    return f'<table class="tape benchtape">{LINEUP_COLS}{head}{"".join(rows)}</table>'


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
                f'<div class="yards">{you["floor"]:.0f} – {you["ceiling"]:.0f} '
                f'realistic range</div></div>')
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


def section_regret(regret: Mapping[str, Any]) -> str:
    if "gate" in regret:
        # No .call frame: a heavy navy card whose only content is an absence
        # reads as broken software rather than restraint.
        return _section("The Week's Closest Call", 6, gate_note(regret["gate"]))
    confidence = _pct(regret["confidence"])
    drivers = "".join(
        f'<span class="drv">{esc(d["label"])} <b>{esc(d["value"])}</b></span>'
        for d in regret["drivers"]
    )
    body = (
        f'<div class="call"><div class="verdict">Start {esc(regret["start_name"])} '
        f'<span class="over">over</span> {esc(regret["over_name"])}</div>'
        f'<div class="conf"><div class="bar"><i style="width:{confidence}%"></i></div>'
        f'<div class="num">{confidence}%</div></div>'
        f'<div class="drivers">{drivers}</div>'
        f'<p class="why">{esc(regret["definition"])}</p></div>'
    )
    return _section("The Week's Closest Call", 6, body)


def section_pivots(plans: list[Mapping[str, Any]]) -> str:
    if not plans:
        body = gate_note("no pivots this week — no starter we can check is "
                         "listed questionable")
    else:
        rows = "".join(
            f'<div class="pivot"><div class="if">If</div>'
            f'<div class="cond">{esc(p["condition"])}</div>'
            f'<div class="then">{esc(p["action"])}</div></div>'
            for p in plans
        )
        body = f'<div class="pivots">{rows}</div>'
    return _section("If/Then for Gameday", 7, body)


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
        return "can't play this week"
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
        inner = (f'{esc(receipts.get("note", ""))}'
                 f'<br><span class="stamp">Results · from next week</span>')
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


def demo_band(meta: Mapping[str, Any]) -> str:
    """The public sample's closing ask. DEMO SURFACES ONLY.

    The sample report is the highest-intent page in the funnel — a reader here
    has just finished due diligence — and it used to end at a footer with zero
    links to the picker. Never rendered in a live subscriber report: selling a
    subscriber the thing they already own reads as spam.
    """
    if not meta.get("anonymized_demo"):
        return ""
    if meta.get("solo"):
        season = esc(str(meta.get("season", "a past")))
        # The two published samples point at each other on purpose. A buyer
        # decides on a mid-season file and then receives a WEEK ONE file, which
        # carries no number anywhere by design — and a gap between what was
        # sold and what arrives is a refund with a stamp on it. Each page says
        # what the other one shows.
        companion = (
            'A mid-season report, once the season has a record to read, looks '
            'like <a href="sample-report.html" style="color:var(--brick);'
            'font-weight:700;">this</a>. '
            if meta.get("first_week_demo") else
            ''
        )
        return (
            '<div class="regret-note" style="margin:14px 0 0;text-align:center;">'
            f'This report is from the {season} season. {companion}'
            'Yours is built from your own '
            'roster, scored your league\'s way — '
            '<a href="join/index.html" style="color:var(--brick);font-weight:700;">'
            'set it up</a> and your first report lands the day you join.</div>'
        )
    return (
        '<div class="regret-note" style="margin:14px 0 0;text-align:center;">'
        'This file is from a 2018 sample league. Yours is about <b>your</b> rival — '
        '<a href="join/index.html" style="color:var(--brick);font-weight:700;">'
        'pick them</a> and the first one lands Tuesday.</div>'
    )


def _forward_line() -> str:
    """The standing acquisition line, above the cancellation block.

    A forwarded report is the one organic touch with the eleven best prospects
    a subscriber knows. Gated on SITE_URL (set at launch, with the domain):
    a call to action with nowhere to go is worse than none.
    """
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if not site:
        return ""
    return (f'Got this from a leaguemate? Every manager gets their own report, '
            f'built from their own roster — {esc(site)}/join.<br>')


UPDATE_HEAD = "Roster changed?"
UPDATE_BODY = ("Update it here by Saturday morning — your final check and your next "
               "report use it. We'll email you a button to confirm:")
UPDATE_REPLY = ("Reply to this email with your updated roster and your next report "
                "follows it.")


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
    if not meta.get("solo") or meta.get("historical_demo"):
        return ""
    if not url:
        return f'<b>{esc(UPDATE_HEAD)}</b> {esc(UPDATE_REPLY)}<br>'
    return (f'<b>{esc(UPDATE_HEAD)}</b> {esc(UPDATE_BODY)} '
            f'<a href="{esc(url)}">{esc(url)}</a><br>')


def update_lines(meta: Mapping[str, Any]) -> list[str]:
    """The plain-text twin."""
    if not meta.get("solo") or meta.get("historical_demo"):
        return []
    url = meta.get("update_url")
    return ["", f"{UPDATE_HEAD.upper()} "
            + (f"{UPDATE_BODY} {url}" if url else UPDATE_REPLY)]


def footer(meta: Mapping[str, Any]) -> str:
    basis = availability_basis(meta)
    demo = ("Sample report built from a real past season, to show what you get. "
            if meta.get("historical_demo") else "")
    # The gap COUNT is operator bookkeeping; a buyer only needs to know that
    # anything unproven was withheld, which the report already says in place.
    gap_line = ""
    _cancel_href, _cancel_label = cancel_destination()
    return (
        f'{demo_band(meta)}'
        f'<footer><b>Beat Your League</b> — {esc(BRAND_LINE)}'
        f'<br>{esc(demo)}{esc(basis)}{esc(gap_line)}<br>'
        f'{update_line(meta)}'
        f'{_forward_line()}'
        f'{esc(NO_BETTING_LINE)}<br>'
        f'{esc(source_line(meta))}<br>'
        # Every commercial email needs a working way out. It points at the
        # self-serve cancel because that costs the reader ~15 seconds and the
        # operator nothing — no inbox to watch. The unsubscribe-vs-cancel
        # distinction stays: stopping emails while billing continues is how you
        # earn a chargeback and deserve it.
        f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}'
        + (f' <a href="{esc(_cancel_href)}">{esc(_cancel_label)}</a>.'
           if _cancel_href else "")
        + '</footer>'
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
            header(meta),
            section_checklist(report["checklist"]),
            section_your_week(report["matchup"], report.get("no_opponent")),
            section_your_lineup(report),
            section_regret(report["regret"]),
            section_pivots(report["pivots"]),
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
        section_pivots(report["pivots"]),
        section_hype(report["hype"], report.get("waiver_market")),
        section_receipts(report["receipts"]),
        footer(meta),
    ]


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
        desc = (("A complete weekly report built from a real NFL season — every "
                 "number from actual box scores, nothing invented.")
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
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>{esc(title)}</title>\n{social}{favicon}{links}\n<style>{style}</style>\n'
        f'</head>\n<body>\n<div class="report">\n{body}\n</div>\n</body>\n</html>\n'
    )


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
