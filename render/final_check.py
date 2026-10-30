"""The Saturday final check email — both halves, and its subject line.

Short on purpose. It arrives the day before games, usually on a phone, and it
exists to say one thing: what to change before kickoff. Same palette and the
same email-safe dialect as the Tuesday report (``render/email.py``), same
shared footer sentences, and no number that Tuesday did not already print:
projections only, never a probability (``engine/final_check.py``).
"""

from __future__ import annotations

from render.report import buyer_slots

from datetime import datetime
from typing import Any, Mapping

from engine.final_check import (BACK, CLEARED, NO_FILL, REMINDER, SWAP,
                                UNBLOCKED, WATCH, Change)
from render.email import (FACT, NAVY, PAPER, SMALL, _items_table, _sec,
                          masthead_html)
# Re-exported for callers that drew their own box from here.
from render.email import tick_box  # noqa: F401
from render.report import (EMAIL_META, preheader_html, NFLVERSE_LINE,
                           NO_BETTING_LINE, cancel_html, cancel_lines, esc,
                           sender_html)
from render.sender import sender_line

ACT = (SWAP, NO_FILL, BACK)
KEEP_AN_EYE = (WATCH, REMINDER)
PREHEADER = "Friday's injury report, applied to your lineup."
# The one name every surface uses for this email (review, Oct 30 2026).
CHECK_NAME = "The Saturday check"
STANDS = ("Everything else in Tuesday's report stands. We only send this "
          "when something changes.")
HEADS = {"act": "Make these changes", "watch": "Keep an eye on",
         "good": "Good news"}


def _eastern(at: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        local = at.astimezone(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001 — a stamp must never sink a send
        return at.strftime("%a %b %-d, %H:%M UTC")
    return local.strftime("%a %b %-d, %-I:%M %p ET")


def checked_line(at: datetime) -> str:
    """The run's own clock, said as what it is (EMAILS-77): nflverse's
    injury file carries no timestamp of its own, so "injury news as of <now>"
    dated the data with the hour we happened to read it."""
    return (f"Checked {_eastern(at)} against the latest published injury "
            f"report")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


@buyer_slots
def subject_for_check(week: int, changes: list[Change]) -> str:
    moves = [c for c in changes if c.kind in (SWAP, BACK)]
    holes = [c for c in changes if c.kind == NO_FILL]
    # Every hole is counted: the subscriber reads only the subject in an
    # inbox, and "a hole" over two empty slots hid one (EMAILS-73/74).
    hole_words = "a hole" if len(holes) == 1 else f"{len(holes)} holes"
    if moves and holes:
        # A swap must not hide an unfilled slot either.
        return (f"Week {week}: {len(moves)} change{'s' if len(moves) > 1 else ''} "
                f"and {hole_words} in your lineup before kickoff")
    if len(moves) == 1:
        return (f"Week {week}: one change before kickoff — "
                f"{_lower_first(moves[0].action)}")
    if moves:
        return f"Week {week}: {len(moves)} changes before kickoff"
    if holes:
        return f"Week {week}: {hole_words} in your lineup before kickoff"
    cleared = [c for c in changes if c.kind == UNBLOCKED]
    if cleared:
        return (f"Week {week}: {cleared[0].action.split(' is cleared')[0]} is "
                f"cleared — no pickup needed" if len(cleared) == 1 else
                f"Week {week}: {len(cleared)} starters cleared — no pickups needed")
    return f"Week {week}: a starter is questionable — here's your plan"


def _groups(changes: list[Change]) -> list[tuple[str, list[Change]]]:
    return [(key, [c for c in changes if c.kind in kinds])
            for key, kinds in (("act", ACT), ("watch", KEEP_AN_EYE),
                               ("good", (UNBLOCKED, CLEARED)))
            if any(c.kind in kinds for c in changes)]


# The change's kind as its chip (contract A7): what kind of change it is, in
# the buyer's words — the item's own sentence still says what to do.
CHIPS = {SWAP: "swap", NO_FILL: "no cover", BACK: "back in", WATCH: "newly questionable",
         REMINDER: "still questionable", CLEARED: "cleared", UNBLOCKED: "cleared"}


def _model(change: Change, key: str) -> dict[str, Any]:
    """One change, in the plan-item anatomy the Tuesday report uses
    (render.anatomy.item): the action bold, why beneath, the kind as a chip.
    Only a change to make carries a box."""
    return {"head": change.action, "rest": "", "detail": change.detail or None,
            "deadline": CHIPS.get(change.kind, ""),
            "tone": "ok" if key == "good" else "due", "box": key == "act"}


@buyer_slots
def render_final_check(plan: Mapping[str, Any], changes: list[Change],
                       at: datetime, seat: bool = False) -> str:
    """``seat``: a League Pass seat holder, who has no billing to cancel, so
    the footer gives a stop route instead (render.report.cancel_html).

    The Tuesday report's shell (contract A7): the same navy masthead — the
    week big, then what this is, by its one name ("the Saturday check"), and
    each group a card of plan items, on paper. No label beside the lockup:
    "Saturday" is one unbreakable word, and in a wide fallback font it pushed
    the masthead a pixel past a 320px phone ("Final check" wrapped)."""
    week = esc(plan["week"])
    header = masthead_html(
        "", f"Week {plan['week']}",
        f'<b style="color:#FFFFFF;">{esc(CHECK_NAME)}</b> — {esc(PREHEADER)}',
        checked_line(at))
    sections = [_sec(0, HEADS[key], _items_table([_model(c, key) for c in items]), key)
                for key, items in _groups(changes)]
    footer = (
        f'<tr><td style="padding:12px 4px 0 4px;"><p style="{FACT}margin:0;">'
        f'{esc(STANDS)}</p></td></tr>'
        f'<tr><td style="background:{PAPER};padding:20px 4px 8px 4px;">'
        f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — injury '
        f'designations from each team\'s official report, as published.<br>'
        f'{esc(NO_BETTING_LINE)}<br>{esc(NFLVERSE_LINE)}<br>'
        # Who sent it, like the Tuesday report (CAN-SPAM, CASL; launch audit
        # L3, GATE-9): the Saturday check carried no sender block at all.
        f'{sender_html()}'
        f'{cancel_html(seat, f"color:{NAVY};")}'
        '</p></td></tr>')
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{EMAIL_META}<title>Beat Your League — Week {week} Saturday Check</title>\n</head>\n'
        f'<body style="margin:0;padding:0;background:{PAPER};">\n'
        f'{preheader_html(PREHEADER)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:12px 8px 24px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:600px;width:100%;background:{PAPER};">'
        f'{header}{"".join(sections)}{footer}</table></td></tr></table>\n'
        f'</body>\n</html>\n')


@buyer_slots
def text_for_check(plan: Mapping[str, Any], changes: list[Change],
                   at: datetime, seat: bool = False) -> str:
    lines = [f"BEAT YOUR LEAGUE — WEEK {plan['week']} SATURDAY CHECK",
             PREHEADER, checked_line(at), ""]
    for key, items in _groups(changes):
        lines.append(HEADS[key].upper())
        for item in items:
            lines.append(f"{'[ ] ' if key == 'act' else '- '}{item.action}")
            lines.append(f"    {item.detail}")
        lines.append("")
    lines += [STANDS, "", NO_BETTING_LINE, NFLVERSE_LINE, "",
              *cancel_lines(seat),
              *([sender_line()] if sender_line() else [])]
    return "\n".join(lines) + "\n"
