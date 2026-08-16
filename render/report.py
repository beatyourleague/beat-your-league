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

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "rival-report-template.html"
# What a withheld number says to a BUYER. Version numbers, file paths and cost
# telemetry are operator vocabulary and never appear in a report someone paid
# for — a customer reading "v0.3" reasonably concludes they bought unfinished
# software, when the truth is the opposite: we refuse to print what we can't
# stand behind.
NO_CALL = "no call"          # in a tight column
NOT_CALLING_IT = "Not calling it"   # as a label above the reason

# The logo mark, single-sourced. It shipped on the landing hero and NOWHERE
# else — not on the report the subscriber actually pays for, not on the ledger
# or the backtest a skeptic is sent to. One shape, one file, every surface.
#
# The silhouette is a VESICA (two circular arcs meeting at points), not an
# ellipse: a football is a prolate spheroid and the ellipse is what made the
# old mark read as a sticker. Radius is derived from the half-length L and
# half-height H as (L^2+H^2)/2H — at L=11.4, H=6.6 that is 13.145. Depth is
# three layers on one path (form gradient, specular bloom, edge vignette) and
# the -18 degree tilt is what stops it reading as inert.
# ``uid`` namespaces the gradient ids so two marks can share a document.
MARK_PATH = "M-11.4 0A13.145 13.145 0 0 1 11.4 0A13.145 13.145 0 0 1-11.4 0Z"


def mark_svg(uid: str = "byl", klass: str = "mark") -> str:
    """The football mark as standalone inline SVG. Decorative: the wordmark
    beside it carries the name, so this is aria-hidden."""
    return (
        f'<svg class="{klass}" viewBox="0 0 26 17" aria-hidden="true" focusable="false">'
        f'<defs>'
        f'<linearGradient id="{uid}Body" x1=".12" y1="0" x2=".72" y2="1">'
        f'<stop offset="0" stop-color="#C57F45"/><stop offset=".34" stop-color="#9A5228"/>'
        f'<stop offset=".72" stop-color="#63321A"/><stop offset="1" stop-color="#381B0D"/>'
        f'</linearGradient>'
        f'<radialGradient id="{uid}Spec" cx=".34" cy=".24" r=".40">'
        f'<stop offset="0" stop-color="#FFE0B4" stop-opacity=".58"/>'
        f'<stop offset="1" stop-color="#FFE0B4" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="{uid}Vig" cx=".5" cy=".5" r=".60">'
        f'<stop offset=".42" stop-color="#25120A" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="#25120A" stop-opacity=".62"/></radialGradient>'
        f'</defs>'
        f'<g transform="translate(13 8.5) rotate(-18)">'
        f'<path id="{uid}Path" d="{MARK_PATH}" fill="url(#{uid}Body)" '
        f'stroke="#F2C230" stroke-width=".9"/>'
        f'<use href="#{uid}Path" fill="url(#{uid}Spec)" stroke="none"/>'
        f'<use href="#{uid}Path" fill="url(#{uid}Vig)" stroke="none"/>'
        f'<g stroke="#F6F4EE" stroke-linecap="round" fill="none">'
        f'<path d="M-7.4 .30Q0-.95 7.4 .30" stroke-width=".8" opacity=".92"/>'
        f'<path d="M-3.18-1.36L-2.82 .91M-1.07-1.73L-.93 1.10M1.07-1.73L.93 1.10'
        f'M3.18-1.36L2.82 .91" stroke-width="1"/>'
        f'</g></g></svg>'
    )


# Every surface that shows the wordmark styles the mark the same way.
MARK_CSS = (".brand svg.mark{width:22px;height:15px;flex:none;}"
            ".brand{display:inline-flex;align-items:center;gap:9px;}")

# Sentences shared verbatim between the browser report (this module) and the
# email digest (render/email.py). Single-sourced so the pinned consumer
# protections and the buyer voice cannot drift apart between the two surfaces.
BRAND_LINE = ("the weekly scouting report built around your rival, "
              "not just your roster.")
NO_BETTING_LINE = ("Projections are analysis, not guarantees — no betting "
                   "picks, no staking advice. Fantasy decisions are yours to make.")
SLEEPER_LINE = ("Built from your league's own record on Sleeper. "
                "Not affiliated with Sleeper or the NFL.")
CANCEL_HEAD = "Done with this?"
CANCEL_BODY = ("Cancel it yourself in your Substack account — it takes about "
               "fifteen seconds and stops the billing immediately. "
               "Unsubscribing from emails alone does not stop a subscription, "
               "so cancel there if you want the charges to end.")
AS_SET_TITLE = "Your Lineup — As Set"
OPTIMAL_TITLE = "Your Optimal Lineup"
AS_SET_HEAD = "Your lineup, exactly as set."
AS_SET_BODY = ("Start-sit calls begin once your league has box scores to "
               "compare against — from next week, this grid shows the lineup "
               "we would set and why.")


def no_call_explainer(listed: str) -> str:
    """Why gated slots say "no call" — one definition, both renderers."""
    return (f"{listed}. When we do put a number on a slot, it means: the odds "
            f"this guy outscores the best option on your bench. We only show it once "
            f"we've confirmed both players are active — otherwise we'd be guessing, "
            f"and you can guess for free.")


def availability_basis(meta: Mapping[str, Any]) -> str:
    """The data-age sentence (principle 3), shared by both renderers."""
    availability = meta.get("availability_as_of")
    return (f"Injury and inactive data as of {availability}." if availability
            else "We couldn't confirm injuries or inactives for this week, so "
                 "some calls are left unmade rather than guessed.")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _pct(value: float) -> int:
    return max(0, min(100, round(value * 100)))


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
        f'<span class="chip">This week: <b>{esc(meta["rival_label"])}</b></span>',
        f'<span class="chip">{esc(_generated_stamp(meta))}</span>',
    ]
    if meta.get("rivalry_week"):
        chips.insert(1, '<span class="chip" style="border-color:var(--flag);'
                        'color:var(--flag)"><b>RIVALRY WEEK</b></span>')
    elif meta.get("named_rival_label"):
        chips.insert(2, f'<span class="chip">Rival: '
                        f'<b>{esc(meta["named_rival_label"])}</b></span>')
    banner = ""
    if meta.get("historical_demo"):
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
    return (
        f'<header class="bug"><div class="brand">{mark_svg("bylm")}'
        f'<span>Beat Your League</span></div>'
        f'<h1>Week {esc(meta["week"])} · Rival Report</h1>'
        f'<div class="chips">{"".join(chips)}</div></header>{banner}'
    )


def _generated_stamp(meta: Mapping[str, Any]) -> str:
    raw = meta.get("generated_at", "")
    try:
        stamp = datetime.fromisoformat(raw).astimezone(timezone.utc)
        return stamp.strftime("Generated %a %b %d · %H:%M UTC")
    except (TypeError, ValueError):
        return "Generated (timestamp unavailable)"


def section_checklist(items: list[Mapping[str, Any]]) -> str:
    tasks = []
    for item in items:
        klass = "dl ok" if item.get("urgency") in ("now", "done") else "dl"
        tasks.append(
            f'<div class="task"><div class="box"></div><div>'
            f'<div class="do">{esc(item["action"])}</div>'
            f'<div class="{klass}">{esc(item["deadline"])}</div></div></div>'
        )
    return _section("The 30-Second Game Plan", 1, f'<div class="plan">{"".join(tasks)}</div>')


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
    if not gated and "projected_total" in you and "projected_total" in rival:
        gap = you["projected_total"] - rival["projected_total"]
        side = "ahead" if gap >= 0 else "behind"
        klass = "gap up" if gap >= 0 else "gap down"
        centre = (f'<div class="{klass}"><span class="gnum">{abs(gap):.1f}</span>'
                  f'<span class="glab">projected<br>{side}</span></div>')
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
        field = gate_note(f'win probability — {matchup.get("win_probability_gate", "gated")}')

    # Ranges carry their own backtest evidence (band coverage), so they render
    # independently of the win-probability gate — but only when the engine
    # published them. A gated week renders the reason, never a zeroed band.
    if gated:
        ranges = gate_note(f"projected totals and ranges — {gated}")
        return _section("The Matchup", 2, board + field + ranges)

    lo = min(you["floor"], rival["floor"])
    hi = max(you["ceiling"], rival["ceiling"])
    span = (hi - lo) or 1.0

    def band(team: Mapping[str, Any], side: str) -> str:
        left = _pct((team["floor"] - lo) / span)
        right = 100 - _pct((team["ceiling"] - lo) / span)
        med = _pct((team["projected_total"] - lo) / span)
        return (
            f'<div class="range {side}"><div class="rl">'
            f'<span>{esc(team["label"])} — realistic range</span>'
            f'<span>proj {team["projected_total"]:.1f}</span></div>'
            f'<div class="track"><span class="band" style="left:{left}%;right:{right}%"></span>'
            f'<span class="med" style="left:{med}%"></span></div>'
            f'<div class="nums"><span>floor {team["floor"]:.0f}</span>'
            f'<span>ceiling {team["ceiling"]:.0f}</span></div></div>'
        )
    basis = matchup.get("range_basis")
    basis_html = (f'<div class="yards" style="justify-content:flex-end">'
                  f'{esc(basis)}</div>' if basis else "")
    ranges = f'<div class="ranges">{band(you, "you")}{band(rival, "rival")}</div>{basis_html}'

    return _section("The Matchup", 2, board + field + ranges)


def _lineup_row(slot: Mapping[str, Any], calls: bool = True) -> str:
    name = slot.get("player_name") or "(empty)"
    meta_bits = [b for b in (slot.get("position"),
                             f'{slot["form_games"]} games of form' if slot.get("form_games") is not None else None)
                 if b]
    flags = slot.get("flags") or []
    flip = ' flip' if flags else ""
    fliptags = "".join(f'<span class="fliptag">{esc(f["text"])}</span>' for f in flags)
    projected = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
    confidence = slot.get("confidence")
    if confidence is not None:
        conf_cell = (f'<span class="cwrap"><span class="cbar">'
                     f'<i style="width:{_pct(confidence)}%"></i></span>'
                     f'<span class="clab">{_pct(confidence)} · vs {esc(slot.get("alternative_name") or "bench")}</span></span>')
    elif calls:
        conf_cell = f'<span class="cwrap"><span class="clab">{esc(NO_CALL)}</span></span>'
    else:
        conf_cell = '<span class="cwrap"></span>'
    return (
        f'<div class="lrow{flip}"><span class="slot">{esc(slot["slot"])}</span>'
        f'<span class="pl"><span class="pname">{esc(name)}</span>'
        f'<span class="pmeta">{esc(" · ".join(meta_bits))}</span>{fliptags}</span>'
        f'<span class="proj">{projected}</span>{conf_cell}</div>'
    )


def _lineup_grid(slots: list[Mapping[str, Any]], total: float | None,
                 total_label: str, note_html: str = "", calls: bool = True) -> str:
    """``total`` comes from the matchup section so the board and the grid can
    never disagree (summing per-row rounded values drifts). ``None`` means the
    engine gated the totals — the row is omitted rather than printing a 0.0
    that no game produced."""
    conf_head = "Conf" if calls else ""
    head = ('<div class="lrow head"><span>Slot</span><span>Player</span>'
            '<span style="text-align:right">Proj</span>'
            f'<span style="text-align:right">{conf_head}</span></div>')
    rows = "".join(_lineup_row(s, calls=calls) for s in slots)
    total_row = ""
    if total is not None:
        total_row = (
            f'<div class="lrow total"><span class="slot"></span>'
            f'<span class="pl"><span class="pname">Projected Total</span></span>'
            f'<span class="proj">{total:.1f}</span>'
            f'<span class="cwrap"><span class="clab">{esc(total_label)}</span></span></div>'
        )
    return f'<div class="lineup">{head}{rows}{total_row}{note_html}</div>'


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


def section_lineup(report: Mapping[str, Any]) -> str:
    slots = report["lineup"]
    as_set = report["meta"].get("lineup_as_set")
    gates = {s["confidence_gate"] for s in slots if s.get("confidence_gate")}
    note = ""
    if as_set:
        # Week 1: the grid is the subscriber's own lineup, untouched. Claiming
        # "optimal" for a lineup nobody optimized would be a fabricated
        # endorsement; nine empty rows would read as broken software. This is
        # the honest middle: their lineup, plainly labeled, calls dated.
        note = (f'<div class="benchnote"><b>{esc(AS_SET_HEAD)}</b> '
                f'{esc(AS_SET_BODY)}</div>')
    elif gates:
        listed = " · ".join(sorted(gates))
        note = (f'<div class="benchnote"><b>Why some slots say "no call":</b> '
                f'{esc(no_call_explainer(listed))}</div>')
    matchup = report["matchup"]
    # When totals are gated (week 1: nothing to project from), the grid total
    # row is omitted rather than showing a 0.0 that no game produced.
    you_total = matchup["you"].get("projected_total")
    rival_total = matchup["rival"].get("projected_total")
    grid = _lineup_grid(slots, you_total,
                        f"vs {rival_total:.1f}" if rival_total is not None else "",
                        note_html=note)
    title = AS_SET_TITLE if as_set else OPTIMAL_TITLE
    return _section(title, 3, grid)


def section_rival_lineup(report: Mapping[str, Any]) -> str:
    matchup = report["matchup"]
    you_total = matchup["you"].get("projected_total")
    rival_total = matchup["rival"].get("projected_total")
    grid = _lineup_grid(report["rival_lineup"], rival_total,
                        f"vs you {you_total:.1f}" if you_total is not None else "",
                        calls=False)
    return _section(f'{report["meta"]["rival_label"]} — Lineup As Set', 4, grid)


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
        return _section("Your Regret Score", 6, gate_note(regret["gate"]))
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
    return _section("Your Regret Score", 6, body)


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
    return _section("Pivot Plan — Set It, Forget It", 7, body)


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
                f'{gate_line}'
                f'{_bid_line(entry)}</div>'
            )
        note = (f'<div class="withheld"><span class="lab">Why no verdict</span>'
                f'{esc(shared_gate)}</div>' if shared_gate else "")
        body = f'<div class="hype">{"".join(cards)}</div>{note}'
    return _section("Waiver Hype Meter", 8, body) + section_waiver_market(market)


def _bid_line(entry: Mapping[str, Any]) -> str:
    """What it takes to win this player HERE — the part rankings can't do."""
    bid = entry.get("bid_to_beat")
    if not bid:
        return ""
    rivals = entry.get("rivals_who_can_pay")
    if rivals is None:
        who = "we can't tell what anyone has left — see the note below"
    elif rivals == 0:
        who = "nobody else in your league can even cover that"
    elif rivals == 1:
        who = "one other team can cover that"
    else:
        who = f"{rivals} other teams can cover that"

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
        rows.append(f'<span class="drv">Going rate <b>{esc(market["going_rate"])}</b></span>')
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
                 f'<br><span class="stamp">Ledger opens · this week</span>')
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
    return (f'Got this from a leaguemate? Every manager gets their own file, aimed '
            f'at their own rival — {esc(site)}/join. The record we\'re graded on '
            f'is public: {esc(site)}/ledger.<br>')


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
        f'{_forward_line()}'
        f'{esc(NO_BETTING_LINE)}<br>'
        f'{esc(SLEEPER_LINE)}<br>'
        # Every commercial email needs a working way out. It points at the
        # self-serve cancel because that costs the reader ~15 seconds and the
        # operator nothing — no inbox to watch. The unsubscribe-vs-cancel
        # distinction stays: stopping emails while billing continues is how you
        # earn a chargeback and deserve it.
        f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}</footer>'
    )


def _section(title: str, n: int, body: str) -> str:
    # Zero-padded, not "§n": the section sign is legal/academic citation
    # register. "01" reads like a case file, which is the register the product
    # actually sells ("the file on Mike").
    marker = f'<span class="n">{n:02d}</span>' if n else ""
    return (
        f'<section><div class="eyebrow"><span class="tag">{esc(title)}</span>'
        f'{marker}</div>{body}</section>'
    )


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


def render(report: Mapping[str, Any], template_html: str) -> str:
    style, links = extract_design(template_html)
    style += MARK_CSS
    meta = report["meta"]
    body = "".join([
        header(meta),
        section_checklist(report["checklist"]),
        section_matchup(report["matchup"]),
        section_rival_watch(report.get("rival_watch")),
        section_lineup(report),
        section_rival_lineup(report),
        section_fragility(report["fragility"], meta["rival_label"]),
        section_regret(report["regret"]),
        section_pivots(report["pivots"]),
        section_hype(report["hype"], report.get("waiver_market")),
        section_receipts(report["receipts"]),
        footer(meta),
    ])
    title = (f'Beat Your League — {meta["season"]} Week {meta["week"]} '
             f'Rival Report')
    # Only the public demo gets share meta: it is the one render of this
    # template that lives on the open web. Subscriber reports are private —
    # share tags on them would just invite pasting a paid report around.
    social = ""
    if meta.get("anonymized_demo"):
        desc = ("A complete Rival Report built from a real league's season — "
                "every number from actual box scores, nothing invented.")
        social = (
            f'<meta name="description" content="{desc}">\n'
            '<meta property="og:title" content="Beat Your League — a real Rival Report">\n'
            f'<meta property="og:description" content="{desc}">\n'
            '<meta property="og:type" content="website">\n'
            '<meta property="og:site_name" content="Beat Your League">\n'
            '<meta name="twitter:card" content="summary">\n'
            '<!-- og:image needs the live absolute URL. After the domain exists, add:\n'
            '     <meta property="og:image" content="https://YOUR-DOMAIN/og.png"> -->\n'
        )
    favicon = ('<link rel="icon" href="data:image/svg+xml,'
               '<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22>'
               '<text y=%22.9em%22 font-size=%2290%22>🧾</text></svg>">\n')
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
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"{args.input} not found — run `python -m engine.week_report` first",
              file=sys.stderr)
        return 1
    report = json.loads(args.input.read_text(encoding="utf-8"))
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
