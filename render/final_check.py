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

from engine.final_check import (BACK, CLEARED, NO_FILL, REMINDER, SWAP, WATCH,
                                Change)
from render.email import (tick_box, BASE, CARD, DISPLAY, FLAG, FLAG_TINT, FONT, LINE,
                          NAVY, PAPER, SLATE, SMALL, TURF, TURF_TINT, _sec)
from render.report import (EMAIL_META, preheader_html, CANCEL_BODY, CANCEL_HEAD, NFLVERSE_LINE,
                           NO_BETTING_LINE, cancel_destination, esc)

ACT = (SWAP, NO_FILL, BACK)
KEEP_AN_EYE = (WATCH, REMINDER)
PREHEADER = "Friday's injury report, applied to your lineup."
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


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


@buyer_slots
def subject_for_check(week: int, changes: list[Change]) -> str:
    moves = [c for c in changes if c.kind in (SWAP, BACK)]
    if len(moves) == 1:
        return (f"Week {week}: one change before kickoff — "
                f"{_lower_first(moves[0].action)}")
    if moves:
        return f"Week {week}: {len(moves)} changes before kickoff"
    if any(c.kind == NO_FILL for c in changes):
        return f"Week {week}: a hole in your lineup before kickoff"
    return f"Week {week}: a starter is questionable — here's your plan"


def _groups(changes: list[Change]) -> list[tuple[str, list[Change]]]:
    return [(key, [c for c in changes if c.kind in kinds])
            for key, kinds in (("act", ACT), ("watch", KEEP_AN_EYE),
                               ("good", (CLEARED,)))
            if any(c.kind in kinds for c in changes)]


def _items(items: list[Change], tint: str, rule_colour: str, box: bool) -> str:
    rows = []
    for i, item in enumerate(items):
        rule = f"border-top:1px solid {LINE};" if i else ""
        tick = (f'<td style="padding:10px 12px 10px 0;vertical-align:top;'
                f'width:18px;{rule}">{tick_box()}</td>' if box else "")
        rows.append(
            f'<tr>{tick}<td style="{BASE}padding:10px 0;{rule}">'
            f'<b>{esc(item.action)}</b><br>'
            f'<span style="{SMALL}color:{NAVY};">{esc(item.detail)}</span>'
            f'</td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0" style="background:{tint};'
            f'border-left:4px solid {rule_colour};"><tr><td style="padding:4px 14px;">'
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{"".join(rows)}</table></td></tr></table>')


@buyer_slots
def render_final_check(plan: Mapping[str, Any], changes: list[Change],
                       at: datetime) -> str:
    week = esc(plan["week"])
    header = (
        f'<tr><td style="background:{NAVY};padding:24px 28px;'
        f'border-left:4px solid {FLAG};">'
        f'<div style="font-family:{DISPLAY};font-size:13px;font-weight:bold;'
        f'letter-spacing:4px;text-transform:uppercase;color:{FLAG};">'
        f'Beat Your League</div>'
        f'<div style="font-family:{DISPLAY};font-size:30px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{CARD};'
        f'padding:6px 0 2px 0;">Week {week} · Final Check</div>'
        f'<div style="font-family:{FONT};font-size:15px;font-weight:bold;'
        f'color:{FLAG};padding:0 0 8px 0;">{esc(PREHEADER)}</div>'
        f'<div style="font-family:{FONT};font-size:12px;color:#B9C2D0;">'
        f'Injury news as of {esc(_eastern(at))}</div></td></tr>')
    sections = []
    for key, items in _groups(changes):
        if key == "act":
            body = _items(items, FLAG_TINT, FLAG, box=True)
        elif key == "watch":
            body = _items(items, PAPER, LINE, box=False)
        else:
            body = _items(items, TURF_TINT, TURF, box=False)
        sections.append(_sec(0, HEADS[key], body))
    href, label = cancel_destination()
    footer = (
        f'<tr><td style="padding:18px 28px 0 28px;"><p style="{BASE}margin:0;">'
        f'{esc(STANDS)}</p></td></tr>'
        f'<tr><td style="padding:12px;"></td></tr>'
        f'<tr><td style="background:{PAPER};padding:20px 28px 26px 28px;">'
        f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — injury '
        f'designations from each team\'s official report, as published.<br>'
        f'{esc(NO_BETTING_LINE)}<br>{esc(NFLVERSE_LINE)}<br>'
        f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}'
        + (f' <a href="{esc(href)}" style="color:{NAVY};">{esc(label)}</a>.'
           if href else "")
        + '</p></td></tr>')
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{EMAIL_META}<title>Beat Your League — Week {week} Final Check</title>\n</head>\n'
        f'<body style="margin:0;padding:0;background:{PAPER};">\n'
        f'{preheader_html(PREHEADER)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:18px 8px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:600px;width:100%;background:{CARD};">'
        f'{header}{"".join(sections)}{footer}</table></td></tr></table>\n'
        f'</body>\n</html>\n')


@buyer_slots
def text_for_check(plan: Mapping[str, Any], changes: list[Change],
                   at: datetime) -> str:
    lines = [f"BEAT YOUR LEAGUE — WEEK {plan['week']} FINAL CHECK",
             PREHEADER, f"Injury news as of {_eastern(at)}", ""]
    for key, items in _groups(changes):
        lines.append(HEADS[key].upper())
        for item in items:
            lines.append(f"{'[ ] ' if key == 'act' else '- '}{item.action}")
            lines.append(f"    {item.detail}")
        lines.append("")
    lines += [STANDS, "", NO_BETTING_LINE, NFLVERSE_LINE,
              f"{CANCEL_HEAD} {CANCEL_BODY}"]
    href, label = cancel_destination()
    if href:
        lines.append(f"CANCEL: {label} — {href}")
    return "\n".join(lines) + "\n"
