"""The Trade Check's answer (run/trades.py). It goes only to the address on the
plan, and it reports what changes without saying whether to make the deal."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from render.email import BASE, FLAG, FONT, NAVY, SMALL
from render.report import NFLVERSE_LINE, NO_BETTING_LINE, esc
from render.team_mail import _shell

SUBJECT = "Your trade check"
LIMITS = ("This compares this week's lineup and the byes ahead. It doesn't rate the trade, "
          "and it can't see the other team or your league, so the decision is yours. "
          "Your roster on file hasn't changed.")
NOT_ASKED = "Didn't ask for this? Ignore it. Nothing changed."
MADE_IT = "Made the deal? Update your roster here so your next report uses it:"
MADE_IT_BUTTON = "Update my roster"
# It prints this week's projections and how each player has scored, so it
# carries what every report does (launch review LEG-M2, LEG-3): principle 4's
# disclaimer, and RULE N1's CC-BY-4.0 credit, a licence term.
SOURCE_LINES = (NO_BETTING_LINE, NFLVERSE_LINE)


# The longest ordinary answer, for the launch check's width and sender audit.
TRADE_SAMPLE = {"week": 10, "total_before": 118.4, "total_after": 121.2, "change": 2.8,
                "moves": [{"slot": "RB", "was": "Saquon Barkley", "was_points": 17.6,
                           "now": "Bijan Robinson", "now_points": 15.1}],
                "gone": [{"name": "Saquon Barkley", "projected": 17.6, "per_game": 22.1,
                          "recent": [26.7, 12.1, 32.9]}],
                "added": [{"name": "Bijan Robinson", "projected": 15.1, "per_game": 18.0,
                           "recent": [12.0, 20.4, 16.1]}],
                "byes_before": ["Week 12: QB, TE"], "byes_after": []}


def _points(value: Any) -> str:
    return "no projection" if value is None else f"{value:.1f}"


def _player(row: Mapping[str, Any]) -> str:
    bits = [f"this week {_points(row.get('projected'))}"]
    if row.get("per_game") is not None:
        bits.append(f"{row['per_game']:.1f} a game this season")
    recent = row.get("recent") or []
    if recent:
        bits.append("last three: " + ", ".join(f"{float(p):.1f}" for p in recent))
    return f"{row.get('name')} ({', '.join(bits)})"


def _sections(change: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    week = change.get("week")
    total = []
    if change.get("total_before") is not None and change.get("total_after") is not None:
        total = [f"Now: {change['total_before']:.1f}", f"After: {change['total_after']:.1f}"]
    if change.get("change") is None:
        total.append("One of these lineups has a player with no projection, so we're "
                     "not comparing points.")
    else:
        delta = change["change"]
        total.append("Change: about the same" if abs(delta) < 0.1
                     else f"Change: {'+' if delta > 0 else '−'}{abs(delta):.1f}")
    moves = [f"{m['slot']}: {m['was']} ({_points(m['was_points'])}) → {m['now']} "
             f"({_points(m['now_points'])})" for m in change.get("moves") or []]
    return [(f"Week {week} projected points", total),
            ("Lineup changes", moves or ["Nobody changes in this week's lineup."]),
            ("Byes that empty a spot, now", change.get("byes_before") or ["None ahead."]),
            ("Byes that empty a spot, after", change.get("byes_after") or ["None ahead."]),
            ("Coming in", [_player(r) for r in change.get("added") or []] or ["Nobody."]),
            ("Going out", [_player(r) for r in change.get("gone") or []] or ["Nobody."])]


def trade_email(change: Mapping[str, Any], team: str = "",
                update_url: str | None = None) -> tuple[str, str, str]:
    """(subject, html, text)."""
    named = "" if team in ("", "Your Team") else team
    subject = f"{SUBJECT}: {named}" if named else SUBJECT
    sections = _sections(change)
    body = "".join(
        f'<p style="{BASE}margin:0 0 4px 0;"><b>{esc(head)}</b></p>'
        + "".join(f'<p style="{BASE}margin:0 0 4px 0;">{esc(line)}</p>' for line in lines)
        + f'<p style="{SMALL}margin:0 0 10px 0;">&nbsp;</p>' for head, lines in sections)
    if update_url:
        # A button, like the confirmation emails', in place of a raw URL in
        # the client's default blue (launch review EM-10).
        body += (f'<p style="{BASE}margin:0 0 8px 0;">{esc(MADE_IT)}</p>'
                 f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                 f'style="margin:0 0 14px 0;"><tr>'
                 f'<td style="background:{FLAG};border-radius:4px;">'
                 f'<a href="{esc(update_url)}" style="display:inline-block;padding:12px 22px;'
                 f'font-family:{FONT};font-size:15px;font-weight:bold;color:{NAVY};'
                 f'text-decoration:none;">{esc(MADE_IT_BUTTON)}</a></td></tr></table>')
    body += (f'<p style="{SMALL}margin:0 0 8px 0;">{esc(LIMITS)}</p>'
             + "".join(f'<p style="{SMALL}margin:0 0 8px 0;">{esc(line)}</p>'
                       for line in SOURCE_LINES)
             + f'<p style="{SMALL}margin:0;">{esc(NOT_ASKED)}</p>')
    html = _shell(subject, "What the deal does to your lineup and byes.", body)
    text: list[str] = [subject.upper(), ""]
    for head, lines in sections:
        text += [head.upper(), *lines, ""]
    if update_url:
        text += [f"{MADE_IT} {update_url}", ""]
    text += [LIMITS, "", *SOURCE_LINES, "", NOT_ASKED, ""]
    return subject, html, "\n".join(text)
