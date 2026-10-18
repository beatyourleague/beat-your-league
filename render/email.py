"""Render ``week_report.json`` as email-safe HTML — what actually gets sent.

The browser report (``render/report.py``) is the archival artifact; THIS is
the deliverable that lands in an inbox. Email clients are a hostile rendering
target — Outlook uses Word's engine, Gmail strips ``<style>`` in forwards,
and none of them can be trusted with grid, flexbox, custom properties or
loaded fonts. So this module speaks the only dialect they all render:

- tables (``role="presentation"``) for all layout, never grid/flex;
- every style inline, every color a literal hex from the template's palette;
- web-safe font stacks only (the brand's Barlow degrades to Arial);
- self-contained — per-subscriber reports are private, so there is no hosted
  copy to link to; the email must carry the whole report.

Content decisions are NOT re-made here. Every sentence that is pinned by a
test — the cancel/unsubscribe distinction, the no-betting line, the data-age
basis, the as-set explainer — is imported from ``render.report`` so the two
surfaces can never drift apart. All data is escaped on the way in.
"""

from __future__ import annotations

from render.report import buyer_slots

import os
import re
from typing import Any, Mapping

from render.sender import sender_line
from render.report import cancel_html, cancel_lines, is_seat
# The row and section bodies (launch review, Oct 2026), one implementation each.
from render.report import (NO_PIVOTS, SLOT_DISPLAY, call_bits, form_phrase,
                           no_call_line, projection_note, row_marked)
from render.report import (
    EMAIL_META,
    sender_html,
    SEASON_END_HEAD,
    season_end_lines,
    preheader_html,
    AS_SET_BODY,
    AS_SET_HEAD,
    BENCH_HEAD,
    bench_form,
    bench_phrase,
    bench_shows_form,
    pivot_action,
    rising_parts,
    BRAND_LINE,
    NO_BETTING_LINE,
    NO_CALL,
    NOT_CALLING_IT,
    SECTION_MARK,
    source_line,
    _forward_line,
    _forward_text,
    seats_line,
    seats_text,
    team_name,
    range_text,
    RANGE_DEFINITION,
    RANGE_LABEL,
    SEEDED_SECTION_LINE,
    update_line,
    update_lines,
    read_line,
    read_lines,
    _generated_stamp,
    _pct,
    availability_basis,
    edge_phrase,
    esc,
    no_call_explainer,
    no_call_head,
    number_sections,
    short_gate,
    row_label,
    gate_list,
    who_can_cover,
)

# The template's palette (:root in rival-report-template.html), as literals —
# email clients do not resolve var().
NAVY = "#101E33"
PAPER = "#F6F4EE"
CARD = "#FFFFFF"
LINE = "#D8D3C6"
SLATE = "#5A6B80"
TURF = "#1E7A46"
BRICK = "#B3402F"
FLAG = "#F2C230"
FLAG_TINT = "#FBF3D9"
BRICK_TINT = "#F7E3DE"
TURF_TINT = "#DFF0E4"

FONT = "Arial,Helvetica,sans-serif"
DISPLAY = "'Arial Narrow',Arial,Helvetica,sans-serif"
BASE = f"font-family:{FONT};font-size:14px;line-height:1.55;color:{NAVY};"
SMALL = f"font-family:{FONT};font-size:12px;line-height:1.5;color:{SLATE};"


TRIAL_HEAD = "Your free report"
TRIAL_INTRO = "This one's on us, built from the roster you sent."
TRIAL_ONLY = ("This is the only email we'll send you unless you sign up. Didn't "
              "ask for it? Ignore it — you won't hear from us again.")
# The free report's one ask (panel review I2). It was an unlinked URL inside
# the grey legal footer, after the data-source and no-betting lines, on the
# email whose whole job is to convert. No price here: the join page states
# the prices with their renewal terms beside them, which an email ask can't.
TRIAL_ASK_HEAD = "Want this every Tuesday?"
TRIAL_ASK = ("Your lineup decided like this one, every Tuesday, plus a final "
             "check on Saturday when injury news changes it.")
TRIAL_BUTTON = "Get next Tuesday's report"
# The channel tag the join page reads (^[a-z0-9-]{1,24}$), so a signup that
# came from a free report is counted as one (`make stats`).
TRIAL_VIA = "trial"


# The season's last week (EMAILS-69): there is no next Tuesday's report, and
# checkout closes once that week kicks off (D9), so the ask is next season's.
TRIAL_LAST_ASK_HEAD = "Want this next season?"
TRIAL_LAST_ASK = ("Your lineup decided like this one, every Tuesday from Week 1, "
                  "plus a final check on Saturday when injury news changes it.")
TRIAL_LAST_BUTTON = "Tell me when it opens"


def _is_final_week(meta: Mapping[str, Any] | None) -> bool:
    meta = meta or {}
    last = meta.get("last_week")
    return isinstance(last, int) and meta.get("week") == last


def trial_join_url(meta: Mapping[str, Any] | None = None) -> str | None:
    """Where the free report's button goes, or None with no site to send
    anyone to — a button with nowhere to go is worse than none. In the
    season's last week it is the landing's waitlist, never the join page."""
    site = os.environ.get("SITE_URL", "").rstrip("/")
    if not site.startswith("https://"):
        return None
    if _is_final_week(meta):
        return f"{site}/?via={TRIAL_VIA}#watch-form"
    return f"{site}/join/?via={TRIAL_VIA}"


def _trial_words(meta: Mapping[str, Any] | None) -> tuple[str, str, str]:
    """(head, ask, button) — the season's last week asks about next season."""
    if _is_final_week(meta):
        return TRIAL_LAST_ASK_HEAD, TRIAL_LAST_ASK, TRIAL_LAST_BUTTON
    return TRIAL_ASK_HEAD, TRIAL_ASK, TRIAL_BUTTON


def _trial_cta(meta: Mapping[str, Any] | None = None) -> str:
    """The free report's call to action: one line and a bulletproof button
    (a padded table cell, the one button every mail client draws, Outlook
    included), with the only-email promise beneath it."""
    url = trial_join_url(meta)
    head, ask, label = _trial_words(meta)
    button = ""
    if url:
        button = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'align="center" style="margin:14px auto 0 auto;"><tr>'
            f'<td style="background:{FLAG};border-radius:3px;">'
            f'<a href="{esc(url)}" style="display:inline-block;padding:13px 24px;'
            f'font-family:{DISPLAY};font-size:16px;font-weight:bold;'
            f'letter-spacing:1.5px;text-transform:uppercase;color:{NAVY};'
            f'text-decoration:none;">{esc(label)}</a></td></tr></table>')
    return (
        f'<tr><td style="padding:26px 28px 0 28px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{NAVY};"><tr>'
        f'<td style="padding:22px 20px 22px 20px;text-align:center;">'
        f'<div style="font-family:{DISPLAY};font-size:20px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{CARD};">'
        f'{esc(head)}</div>'
        f'<div style="font-family:{FONT};font-size:14px;line-height:1.5;'
        f'color:#C9D4E2;padding-top:6px;">{esc(ask)}</div>'
        f'{button}'
        f'<div style="font-family:{FONT};font-size:12px;line-height:1.5;'
        f'color:#B9C2D0;padding-top:14px;">{esc(TRIAL_ONLY)}</div>'
        f'</td></tr></table></td></tr>')


def _trial_cta_lines(meta: Mapping[str, Any] | None = None) -> list[str]:
    """The plain-text twin: the URL spelled out, since text has no button."""
    url = trial_join_url(meta)
    head, ask, label = _trial_words(meta)
    return (["", head.upper(), ask]
            + ([f"{label}: {url}"] if url else [])
            + [TRIAL_ONLY])


def tick_box() -> str:
    """The checklist's empty box. A table cell rather than a sized <div>:
    Outlook's Word engine ignores a div's height and draws it a line tall."""
    return (f'<table role="presentation" width="14" height="14" cellpadding="0" '
            f'cellspacing="0" border="0" style="border:2px solid {NAVY};'
            f'background:{CARD};margin-top:2px;"><tr><td width="14" height="14" '
            f'style="font-size:0;line-height:0;">&nbsp;</td></tr></table>')


def _sec(number: int, title: str, body: str) -> str:
    """One report section: numbered case-file title bar, then the body.

    ``number`` says only WHETHER the section is numbered; the value is filled
    in positionally by number_sections() once the page is assembled, so the
    two surfaces cannot disagree and a merged section cannot leave a hole.
    """
    marker = (f'<span style="color:{SLATE};">{SECTION_MARK}</span> · '
              if number else "")
    return (
        f'<tr><td style="padding:26px 28px 0 28px;">'
        f'<div style="font-family:{DISPLAY};font-size:14px;font-weight:bold;'
        f'letter-spacing:2.5px;text-transform:uppercase;color:{NAVY};'
        f'border-bottom:2px solid {NAVY};padding-bottom:6px;">'
        f'{marker}{esc(title)}</div></td></tr>'
        f'<tr><td style="padding:12px 28px 0 28px;">{body}</td></tr>'
    )


def _gate(reason: str) -> str:
    """A withheld number, in the one honest form (principle 3)."""
    return (
        f'<div style="{BASE}font-size:13px;background:{FLAG_TINT};'
        f'border-left:3px solid {FLAG};padding:10px 12px;margin:8px 0 0 0;">'
        f'<b>{esc(NOT_CALLING_IT)}:</b> {esc(reason)}</div>'
    )


def _bar(fill_pct: float, width: str, height: int = 6, align: str = "") -> str:
    """A bar as a two-cell table — the one bar every mail client draws.

    ``fill_pct`` is the filled share, 0-100. Callers decide the scale: the
    lineup's odds run from 50 (a coin flip) like the site's, the closest call
    shows the pick's whole share of the head-to-head."""
    fill = max(0, min(100, round(fill_pct)))
    cell = f'height:{height}px;font-size:0;line-height:0;'
    filled = (f'<td width="{fill}%" style="{cell}background:{FLAG};">&nbsp;</td>'
              if fill else "")
    rest = (f'<td style="{cell}background:{LINE};">&nbsp;</td>'
            if fill < 100 else "")
    side = f' align="{align}"' if align else ""
    return (f'<table role="presentation"{side} width="{width}" cellpadding="0" '
            f'cellspacing="0" border="0" style="width:{width};"><tr>'
            f'{filled}{rest}</tr></table>')


def _note(inner_html: str) -> str:
    return (
        f'<div style="{BASE}font-size:13px;background:{PAPER};'
        f'border-left:3px solid {LINE};padding:10px 12px;margin:10px 0 0 0;">'
        f'{inner_html}</div>'
    )


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

def _header(meta: Mapping[str, Any], team: str | None = None,
            tagline: str = "Your lineup, decided.") -> str:
    """The navy masthead. ``team`` names a subscriber's roster
    (render.report.team_name) so two teams' emails can be told apart;
    ``tagline`` is the subject's promise, said again under the week."""
    scoring = f' · {esc(meta["scoring"])}' if meta.get("scoring") else ""
    lines = [
        f'<b>{esc(team or meta["league_name"])}</b> · {esc(meta["num_teams"])} '
        f'teams{scoring}',
    ]
    # A solo report has no opponent, so there is nothing to name here. The line
    # used to render "This week: None" — an absent value printed as a word.
    if not meta.get("solo"):
        lines.append(f'This week: <b>{esc(meta["rival_label"])}</b>')
    if meta.get("rivalry_week"):
        lines.insert(1, f'<span style="color:{FLAG};font-weight:bold;'
                        f'letter-spacing:1px;">RIVALRY WEEK</span>')
    elif meta.get("named_rival_label"):
        lines.append(f'Rival: <b>{esc(meta["named_rival_label"])}</b>')
    lines.append(esc(_generated_stamp(meta)))
    banner = ""
    if meta.get("trial"):
        banner = (
            f'<tr><td style="padding:0 28px;">'
            f'<div style="{BASE}font-size:13px;background:{FLAG_TINT};'
            f'border-left:3px solid {FLAG};padding:10px 12px;margin-top:16px;">'
            f'<b>{esc(TRIAL_HEAD)}.</b> {esc(TRIAL_INTRO)}</div></td></tr>')
    season_end = season_end_lines(meta)
    if season_end:
        banner += (
            f'<tr><td style="padding:0 28px;">'
            f'<div style="{BASE}font-size:13px;background:{FLAG_TINT};'
            f'border-left:3px solid {FLAG};padding:10px 12px;margin-top:16px;">'
            f'<b>{esc(SEASON_END_HEAD)}.</b> {esc(" ".join(season_end))}'
            f'</div></td></tr>')
    if meta.get("historical_demo"):
        banner = (
            f'<tr><td style="padding:0 28px;">'
            f'<div style="{BASE}font-size:13px;background:{FLAG_TINT};'
            f'border-left:3px solid {FLAG};padding:10px 12px;margin-top:16px;">'
            f'SAMPLE REPORT — real data from the {esc(meta["season"])} season of '
            f'{esc(meta["league_name"])}, built to show exactly what lands in your '
            f'inbox on a Tuesday.</div></td></tr>'
        )
    return (
        f'<tr><td style="background:{NAVY};padding:26px 28px;'
        f'border-left:4px solid {FLAG};">'
        f'<div style="font-family:{DISPLAY};font-size:13px;font-weight:bold;'
        f'letter-spacing:4px;text-transform:uppercase;color:{FLAG};">'
        f'Beat Your League</div>'
        f'<div style="font-family:{DISPLAY};font-size:32px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;'
        f'color:{CARD};padding:6px 0 2px 0;">Week {esc(meta["week"])} · '
        f'{"Your Report" if meta.get("solo") else "Rival Report"}</div>'
        + (f'<div style="font-family:{FONT};font-size:15px;font-weight:bold;'
           f'color:{FLAG};padding:0 0 10px 0;">{esc(tagline)}</div>'
           if meta.get("solo") else '<div style="padding:0 0 8px 0;"></div>')
        + f'<div style="font-family:{FONT};font-size:12px;color:#B9C2D0;">'
        f'{" &nbsp;—&nbsp; ".join(lines)}</div></td></tr>{banner}'
    )


def _checklist(items: list[Mapping[str, Any]]) -> str:
    # A box to tick beside every item: the site promises "tick the boxes,
    # done in ninety seconds", so the file carries the boxes.
    rows = []
    for i, item in enumerate(items, 1):
        color = TURF if item.get("urgency") in ("now", "done") else SLATE
        rule = f'border-top:1px solid {LINE};' if i > 1 else ""
        rows.append(
            f'<tr><td style="padding:10px 12px 10px 0;vertical-align:top;width:18px;'
            f'{rule}">{tick_box()}</td>'
            f'<td style="{BASE}padding:10px 0;{rule}">'
            f'<b>{esc(item["action"])}</b><br>'
            + (f'<span style="{SMALL}color:{NAVY};">{esc(item["detail"])}</span><br>'
               if item.get("detail") else "")
            + f'<span style="{SMALL}color:{color};">{esc(item["deadline"])}</span>'
            f'</td></tr>'
        )
    body = (f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0" style="background:{FLAG_TINT};'
            f'border-left:4px solid {FLAG};"><tr><td style="padding:4px 14px;">'
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{"".join(rows)}</table>'
            f'</td></tr></table>')
    return _sec(1, "Your Game Plan", body)


def _last_week(last: Mapping[str, Any] | None) -> str:
    """Same section, email-safe. The scoreline leads; the counts follow."""
    if not last:
        return ""
    chips = " &nbsp;·&nbsp; ".join([
        f'you <b>{last["points"]:.1f}</b>',
        f'them <b>{last["opponent_points"]:.1f}</b>',
        f'best you had <b>{last["best_possible"]:.1f}</b>',
    ])
    return _sec(2, f'Week {esc(last["week"])} — How It Ended',
                f'<p style="{BASE}margin:0;">{esc(last["headline"])}</p>'
                f'<p style="{SMALL}margin:8px 0 0 0;">{chips}</p>')


def _gap_cell(matchup: Mapping[str, Any]) -> str:
    """The gap and its swing, exactly as the browser report states them: the
    gap never travels without the swing, and never in a verdict colour."""
    margin, swing = matchup.get("margin"), matchup.get("margin_swing")
    if matchup.get("range_gate") or margin is None or swing is None:
        return (f'<td width="10%" style="{BASE}font-weight:bold;color:{SLATE};'
                f'text-align:center;">VS</td>')
    side = "ahead" if margin >= 0 else "behind"
    return (
        f'<td width="10%" style="text-align:center;padding:12px 2px;">'
        f'<div style="font-family:{DISPLAY};font-size:22px;font-weight:bold;'
        f'color:#33445C;">{abs(margin):.1f}</div>'
        f'<div style="font-family:{FONT};font-size:9px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{SLATE};">'
        f'projected {side}</div>'
        f'<div style="font-family:{FONT};font-size:9px;color:{SLATE};">'
        f'swings &plusmn;{swing}</div></td>'
    )


def _matchup(matchup: Mapping[str, Any]) -> str:
    you, rival = matchup["you"], matchup["rival"]
    gated = matchup.get("range_gate")

    def side(team: Mapping[str, Any], sub: str, align: str,
             tone: str = NAVY) -> str:
        pts = ("" if gated or "projected_total" not in team else
               f'<div style="font-family:{DISPLAY};font-size:34px;font-weight:bold;'
               f'color:{tone};padding-top:4px;">{team["projected_total"]:.1f} '
               f'<span style="font-size:11px;color:{SLATE};">PROJ</span></div>')
        return (
            f'<td width="45%" style="text-align:{align};padding:12px;'
            f'background:{PAPER};">'
            f'<div style="{BASE}font-weight:bold;">{esc(team["label"])}</div>'
            f'<div style="{SMALL}">{esc(sub)}</div>{pts}</td>'
        )

    board = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0"><tr>{side(you, "Your best lineup this week", "left", TURF)}'
        f'{_gap_cell(matchup)}'
        f'{side(rival, "Lineup as currently set", "right", BRICK)}</tr></table>'
    )
    prob = matchup.get("win_probability")
    if prob is not None:
        field = (f'<p style="{BASE}margin:12px 0 0 0;">'
                 f'<b style="color:{TURF};">{_pct(prob)}% win probability.</b> '
                 f'The odds your best lineup outscores the lineup they have set.</p>')
    else:
        # The gate sentence names its own subject; prefixing it repeated the
        # words and read as a field label with an error in it.
        field = _gate(matchup.get("win_probability_gate", "gated"))

    if gated:
        return _sec(2, "The Matchup", board + field
                    + _gate(f"projected totals and ranges — {gated}"))

    def band(team: Mapping[str, Any]) -> str:
        return (f'<tr><td style="{BASE}padding:5px 0;border-bottom:1px solid {LINE};">'
                f'<b>{esc(team["label"])}</b> — realistic range</td>'
                f'<td style="{BASE}padding:5px 0;border-bottom:1px solid {LINE};'
                f'text-align:right;white-space:nowrap;">floor {team["floor"]:.0f} · '
                f'proj <b>{team["projected_total"]:.1f}</b> · '
                f'ceiling {team["ceiling"]:.0f}</td></tr>')

    basis = matchup.get("range_basis")
    basis_html = f'<p style="{SMALL}margin:6px 0 0 0;">{esc(basis)}</p>' if basis else ""
    ranges = (f'<table role="presentation" width="100%" cellpadding="0" '
              f'cellspacing="0" border="0" style="margin-top:10px;">'
              f'{band(you)}{band(rival)}</table>{basis_html}')
    return _sec(2, "The Matchup", board + field + ranges)


def _rival_watch(watch: Mapping[str, Any] | None) -> str:
    if watch is None:
        return ""
    if "gate" in watch:
        return _sec(0, "Rival Watch", _gate(watch["gate"]))
    h2h = watch.get("head_to_head") or {}
    stats = (f'their record <b>{esc(watch.get("their_record", "—"))}</b> · '
             f'you vs them all-time <b>{esc(h2h.get("wins", 0))}-'
             f'{esc(h2h.get("losses", 0))}</b>')
    if watch.get("rivalry_week"):
        body = (f'<p style="{BASE}margin:0;"><b style="color:{TURF};">It\'s Rivalry '
                f'Week.</b> {esc(watch["label"])} is this week\'s opponent — the '
                f'whole report above is the scouting file.</p>'
                f'<p style="{SMALL}margin:8px 0 0 0;">{stats}</p>')
    else:
        # Mirrors render.report.section_rival_watch's line construction exactly.
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
        text = (" ".join(lines) if lines
                else "no matchup data for them this week.")
        body = (f'<p style="{BASE}margin:0;"><b>{esc(watch["label"])}</b> — '
                f'{text}</p>'
                f'<p style="{SMALL}margin:8px 0 0 0;">{stats} · '
                f'{esc(h2h.get("evidence", ""))} · '
                f'record {esc(watch.get("record_evidence", ""))}</p>')
    return _sec(0, "Rival Watch", body)


def _tape_cells(slot: Mapping[str, Any], mine: bool, tint: str,
                mixed: bool = False) -> str:
    """One half of a tape row: name over its sub-line, then the projection.

    The sub-line carries scouting facts — the point gap on your side, the
    fragility flag on theirs — never our methodology.
    """
    name = slot.get("player_name") or "—"
    proj = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
    # Both halves — see render.report._tape_side. A bye-week starter of YOUR
    # own is the flag the reader can still act on.
    flags = [esc(f["text"]) for f in (slot.get("flags") or [])]
    bits: list[str] = []
    if mine:
        edge = edge_phrase(slot)
        if edge:
            bits.append(esc(edge))
        confidence = slot.get("confidence")
        if confidence is not None:
            bits.append(f"{_pct(confidence)}%")
        elif mixed and slot.get("player_name") and slot.get("confidence_gate"):
            # Mixed weeks only — see render.report._tape_side for the reason.
            bits.append(esc(NO_CALL))
    align = "left" if mine else "right"
    cell = (f'{BASE}padding:7px 8px;border-bottom:1px solid {LINE};'
            f'text-align:{align};background-color:{tint};')
    flag = (f'<br><span style="{SMALL}color:{BRICK};font-weight:bold;">'
            f'{" · ".join(flags)}</span>' if flags else "")
    sub = (f'<br><span style="{SMALL}">{" · ".join(bits)}</span>' if bits else "")
    return (f'<td style="{cell}"><b>{esc(name)}</b>{flag}{sub}</td>'
            f'<td style="{cell}white-space:nowrap;font-weight:bold;'
            f'text-align:right;">{proj}</td>')


def _tape(report: Mapping[str, Any]) -> str:
    """Both lineups on one centre spine — the same grid the browser renders.

    Two stacked nine-row tables made the reader hold your RB in their head
    while scrolling to find theirs. Here the comparison is the row, and the
    tint says who wins the slot so no sentence has to.
    """
    mine, theirs = report["lineup"], report["rival_lineup"]
    as_set = report["meta"].get("lineup_as_set")
    mixed = any(s.get("confidence") is not None for s in mine)
    rows = []
    for index, slot in enumerate(mine):
        other = theirs[index] if index < len(theirs) else {}
        a, b = slot.get("projected"), other.get("projected")
        # Only claimed when BOTH sides have a projection — tinting a row on
        # one number would call a slot we could not compare.
        atint = TURF_TINT if (a is not None and b is not None and a > b) else CARD
        btint = BRICK_TINT if (a is not None and b is not None and b > a) else CARD
        rows.append(
            f'<tr>{_tape_cells(slot, True, atint, mixed)}'
            f'<td style="{SMALL}padding:7px 4px;border-bottom:1px solid {LINE};'
            f'text-align:center;font-weight:bold;color:{SLATE};'
            f'white-space:nowrap;">{esc(slot["slot"])}</td>'
            f'{_tape_cells(other, False, btint)}</tr>'
        )
    matchup = report["matchup"]
    you_total = matchup["you"].get("projected_total")
    rival_total = matchup["rival"].get("projected_total")
    total = ""
    if you_total is not None and rival_total is not None:
        tcell = f'{BASE}font-weight:bold;padding:9px 8px;border-top:2px solid {NAVY};'
        total = (f'<tr><td style="{tcell}">TOTAL</td>'
                 f'<td style="{tcell}text-align:right;">{you_total:.1f}</td>'
                 f'<td style="{tcell}"></td><td style="{tcell}"></td>'
                 f'<td style="{tcell}text-align:right;">{rival_total:.1f}</td></tr>')
    th = (f'{SMALL}font-weight:bold;text-transform:uppercase;letter-spacing:1px;'
          f'color:{NAVY};padding:0 8px 5px 8px;border-bottom:2px solid {NAVY};')
    head = (f'<tr><td style="{th}" colspan="2">You</td><td style="{th}"></td>'
            f'<td style="{th}text-align:right;" colspan="2">'
            f'{esc(report["meta"]["rival_label"])}</td></tr>')
    note = ""
    if as_set:
        note = _note(f'<b>{esc(AS_SET_HEAD)}</b> {esc(AS_SET_BODY)}')
    else:
        gates = {s["confidence_gate"] for s in mine if s.get("confidence_gate")}
        if gates:
            head_text = (f'Why some slots say "{NO_CALL}":' if mixed
                         else f'{NO_CALL.capitalize()} on any slot this week:')
            note = _note(f'<b>{esc(head_text)}</b> '
                         f'{esc(no_call_explainer(" · ".join(sorted(gates))))}')
    table = (f'<table role="presentation" width="100%" cellpadding="0" '
             f'cellspacing="0" border="0">{head}{"".join(rows)}{total}</table>')
    return _sec(4, "The Tape — As Set" if as_set else "The Tape", table + note)


def _fragility(items: list[Mapping[str, Any]], rival_label: str) -> str:
    if not items:
        body = _gate("nothing in their lineup we can call fragile this week")
    else:
        rows = "".join(
            f'<tr><td style="{BASE}font-weight:bold;color:{BRICK};'
            f'padding:8px 10px 8px 0;vertical-align:top;width:20px;">{i + 1}</td>'
            f'<td style="{BASE}padding:8px 0;border-bottom:1px solid {LINE};">'
            f'<b>{esc(item["title"])}</b><br>{esc(item["detail"])} '
            f'<i style="color:{SLATE};">({esc(item["evidence"])})</i></td></tr>'
            for i, item in enumerate(items)
        )
        body = (f'<table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0">{rows}</table>')
    return _sec(5, f"Where {rival_label} Is Fragile", body)


def _regret(regret: Mapping[str, Any]) -> str:
    if "gate" in regret:
        # One plain line, no Heads-up box (RQ-19): no call, then the closest
        # decision and why it has no odds (RQ-06).
        return _sec(6, "The Week's Closest Call",
                    f'<p style="{BASE}margin:0;">{esc(no_call_line(regret))}</p>')
    confidence = _pct(regret["confidence"])
    drivers = " · ".join(
        f'{esc(d["label"])} <b>{esc(d["value"])}</b>' for d in regret["drivers"])
    # No title bar inside the card: the section title right above it already
    # says "The Week's Closest Call", and the email printed it twice, stacked
    # (panel review D8). The browser report prints it once.
    # SS-D2: what the card IS — the closest call WITH ODDS — rides as a small
    # label inside it, because a dead-even decision with no odds can sit in
    # the lineup above it; a narrower decision is named in ``closer``.
    label = (f'<div style="{SMALL}font-weight:bold;letter-spacing:1px;'
             f'text-transform:uppercase;color:{SLATE};margin:0 0 4px 0;">'
             f'{esc(regret["label"])}</div>' if regret.get("label") else "")
    extra = "".join(f'<p style="{SMALL}margin:6px 0 0 0;">{esc(regret[key])}</p>'
                    for key in ("reason", "closer") if regret.get(key))
    body = (
        f'<div style="background:{PAPER};border:1px solid {LINE};'
        f'border-top:3px solid {NAVY};">'
        f'<div style="padding:14px 16px;">{label}'
        f'<div style="font-family:{FONT};font-size:18px;font-weight:bold;'
        f'color:{NAVY};">Start {esc(regret["start_name"])} '
        f'<span style="color:{SLATE};font-weight:normal;">over</span> '
        f'{esc(regret["over_name"])}</div>'
        f'<div style="padding:12px 0 4px 0;">{_bar(confidence, "100%", 10)}</div>'
        f'<div style="font-family:{DISPLAY};font-size:26px;font-weight:bold;'
        f'font-style:italic;color:{NAVY};padding:2px 0 6px 0;">{confidence}%</div>'
        f'<p style="{SMALL}margin:0 0 6px 0;">{drivers}</p>'
        f'<p style="{SMALL}margin:0;">{esc(regret["definition"])}</p>{extra}</div></div>'
    )
    return _sec(6, "The Week's Closest Call", body)


def _pivots(plans: list[Mapping[str, Any]],
            meta: Mapping[str, Any] | None = None,
            note: str | None = None) -> str:
    if not plans:
        body = _gate(note or NO_PIVOTS)
    else:
        rows = "".join(
            f'<tr><td style="{BASE}font-weight:bold;color:{SLATE};'
            f'padding:7px 10px 7px 0;vertical-align:top;">If</td>'
            f'<td style="{BASE}padding:7px 0;border-bottom:1px solid {LINE};">'
            f'{esc(p["condition"])}<br><b>→ {esc(pivot_action(p, meta))}</b></td></tr>'
            for p in plans
        )
        body = (f'<table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0">{rows}</table>')
    return _sec(7, "If/Then for Gameday", body)


def _bid_line(entry: Mapping[str, Any]) -> str:
    bid = entry.get("bid_to_beat")
    if not bid:
        return ""
    who = who_can_cover(entry.get("rivals_who_can_pay"),
                        entry.get("league_others"))
    if entry.get("affordable") is False:
        left = entry.get("my_remaining")
        return (f'<p style="{BASE}color:{BRICK};margin:6px 0 0 0;">→ It takes '
                f'<b>{esc(bid)}</b> to top the highest bid he\'s drawn, and you '
                f'have <b>{esc(left)}</b> left. You can\'t win this one — keep '
                f'your budget for a player you can actually land.</p>')
    appetite = entry.get("league_top_appetite")
    tail = ""
    if appetite and appetite > bid:
        tail = (f' If someone really wants him, the biggest bid anyone still '
                f'funded has ever made is {esc(appetite)}.')
    return (f'<p style="{BASE}color:{TURF};margin:6px 0 0 0;">→ Bid '
            f'<b>{esc(bid)}</b> or more to top the highest bid he has drawn '
            f'here — {esc(who)}.{tail}</p>')


def _hype(entries: list[Mapping[str, Any]],
          market: Mapping[str, Any] | None) -> str:
    if not entries:
        body = _gate("a quiet waiver week — no sign of a league-wide chase "
                     "in your league's transaction log")
    else:
        gates = [entry.get("verdict_gate") for entry in entries]
        shared_gate = gates[0] if len(set(gates)) == 1 and gates[0] else None
        cards = []
        for entry in entries:
            bid = entry.get("top_bid")
            bid_text = (f'top bid {bid}' + (
                f' of {entry["faab_budget"]} FAAB'
                if entry.get("faab_budget") else "")
                if bid is not None else "no FAAB bids recorded")
            gate_line = ("" if shared_gate else
                         f'<p style="{BASE}margin:6px 0 0 0;">'
                         f'→ {esc(entry["verdict_gate"])}</p>')
            usage_html = (f'<p style="{BASE}margin:6px 0 0 0;font-weight:bold;">'
                          f'{esc(entry["usage"])}</p>' if entry.get("usage") else "")
            cards.append(
                f'<div style="background:{PAPER};padding:12px 14px;'
                f'margin-top:10px;">'
                f'<div style="{BASE}font-weight:bold;">'
                f'{esc(entry["player_name"])} · {esc(entry["position"])} '
                f'<span style="{SMALL}font-weight:normal;">— '
                f'{esc(entry["managers_chasing"])} managers chasing</span></div>'
                f'<p style="{BASE}margin:6px 0 0 0;">{esc(entry["bids"])} claims '
                f'filed, {esc(entry["completed_adds"])} completed, '
                f'{esc(bid_text)} ({esc(entry["evidence"])}).</p>'
                f'{usage_html}{gate_line}{_bid_line(entry)}</div>'
            )
        note = _note(esc(shared_gate)) if shared_gate else ""
        body = "".join(cards) + note
    return _sec(8, "Waiver Hype Meter", body) + _waiver_market(market)


def _waiver_market(market: Mapping[str, Any] | None) -> str:
    if not market:
        return ""
    bits = []
    if market.get("going_rate") is not None:
        bits.append(f'Going rate <b>{esc(market["going_rate"])} FAAB</b>')
    if market.get("top_winning_bid") is not None:
        bits.append(f'Priciest win <b>{esc(market["top_winning_bid"])}</b>')
    if market.get("my_remaining") is not None:
        bits.append(f'You have <b>{esc(market["my_remaining"])}</b> left')
    if market.get("rival_remaining") is not None:
        bits.append(f'{esc(market["rival_label"])} has '
                    f'<b>{esc(market["rival_remaining"])}</b>')
    if market.get("rival_top_bid_shown"):
        bits.append(f'They\'ve gone as high as '
                    f'<b>{esc(market["rival_top_bid_shown"])}</b>')
    if not bits:
        return ""
    parts = [f'<p style="{BASE}margin:0;">{" · ".join(bits)}</p>']
    lost = market.get("rival_claims_lost") or 0
    if lost:
        parts.append(
            f'<p style="{BASE}margin:8px 0 0 0;">{esc(market["rival_label"])} '
            f'has lost <b>{esc(lost)}</b> claim{"s" if lost != 1 else ""} this '
            f'season — every one of those is a price they were willing to pay '
            f'and didn\'t get.</p>')
    if market.get("budget_note"):
        parts.append(f'<p style="{SMALL}margin:8px 0 0 0;">'
                     f'{esc(market["budget_note"])}</p>')
    parts.append(f'<p style="{SMALL}margin:8px 0 0 0;">'
                 f'{esc(market.get("evidence", ""))}</p>')
    return _sec(0, "The Waiver Market In Your League", "".join(parts))


def _rising(rows) -> str:
    """The template's ``.rising`` card, inline: one bordered row per player
    with the name set apart (launch audit W7). A table, because a div's
    border-left is one of the things Outlook's Word engine drops."""
    if not rows:
        return ""
    from render.report import RISING_HEAD, rising_intro
    items = []
    for row in rows:
        who, what = rising_parts(row)
        items.append(
            f'<tr><td style="{BASE}font-size:13px;background:{CARD};'
            f'border:1px solid {LINE};border-left:4px solid {TURF};'
            f'padding:8px 12px;">'
            + (f'<b>{esc(who)}</b><br>' if who else "")
            + f'{esc(what)}</td></tr>'
            f'<tr><td style="height:6px;font-size:0;line-height:0;">&nbsp;</td></tr>')
    table = (f'<table role="presentation" width="100%" cellpadding="0" '
             f'cellspacing="0" border="0">{"".join(items)}</table>')
    return _sec(8, RISING_HEAD,
                f'<p style="{BASE}margin:0 0 10px 0;">{esc(rising_intro(rows))}</p>{table}')


def _receipts(receipts: Mapping[str, Any]) -> str:
    record = receipts.get("record")
    if not record:
        inner = (f'{esc(receipts.get("note", ""))}<br>'
                 f'<span style="{SMALL}text-transform:uppercase;'
                 f'letter-spacing:1px;">Results · from next week</span>')
    elif receipts.get("last_week_calls") is not None:
        from engine.own_record import HIT, call_line
        rows = "".join(
            f'<div style="{SMALL}color:{NAVY};padding:3px 0;">'
            f'<b style="color:{TURF if c["outcome"] == HIT else BRICK};">'
            f'{"✓" if c["outcome"] == HIT else "✗"}</b> {esc(call_line(c))}</div>'
            for c in receipts["last_week_calls"])
        ask = (f'<div style="{BASE}margin-top:10px;">{esc(receipts["ask"])}</div>'
               if receipts.get("ask") else "")
        inner = (f'{esc(receipts.get("note", ""))}'
                 f'<div style="margin-top:8px;">{rows}</div>'
                 f'<span style="{SMALL}text-transform:uppercase;letter-spacing:1px;">'
                 f'Graded on real box scores</span>{ask}')
    else:
        parts = [esc(receipts.get("note", ""))]
        best, worst = receipts.get("best_call"), receipts.get("worst_call")
        if best:
            parts.append(
                f' Best call: <b>{esc(best["recommended"])} over '
                f'{esc(best["over"])}</b> (week {esc(best["week"])}, '
                f'+{best["margin"]:.1f}).')
        if worst:
            parts.append(
                f' Worst: {esc(worst["recommended"])} over {esc(worst["over"])} '
                f'(week {esc(worst["week"])}, {worst["margin"]:.1f}). '
                f'Both stay on the ledger.')
        inner = ("".join(parts)
                 + f'<br><span style="{SMALL}text-transform:uppercase;'
                   f'letter-spacing:1px;">Graded on real box scores</span>')
    return _sec(9, "The Receipts", f'<p style="{BASE}margin:0;">{inner}</p>')


# --------------------------------------------------------------------- #
# the plain-text half of every email
# --------------------------------------------------------------------- #
#
# This lived in run/week.py, which imports ingest.pull — so every runner that
# wanted the text summary imported a Sleeper client through it, including the
# one whose entire claim is that no league platform is involved. A pure
# function of a report belongs with the renderers; run/week.py re-exports it so
# its own callers are unchanged.

def _forward_lines(meta: Mapping[str, Any] | None = None) -> list[str]:
    """The standing acquisition line for the plain-text email, above the
    cancellation block. A forwarded report reaches the eleven best prospects a
    subscriber knows; gated on SITE_URL exactly like the HTML footer. Same
    words as the HTML (render.report._forward_text), so a League Pass
    league's copy points at the seat, not the checkout; a payer's seat count
    carries the seat link instead (render.report.seats_text)."""
    meta = meta or {}
    seats = seats_text(meta)
    if seats:
        label, _, rest = seats.partition(": ")
        return ["", f"{label.upper()}: {rest}"]
    words = _forward_text(meta)
    if not words:
        return []
    lead = "Got this from a leaguemate?"
    return ["", words.replace(lead, lead.upper(), 1)]


@buyer_slots
def text_summary(report: Mapping[str, Any]) -> str:
    """Plain-text digest of the report — the text half of every email."""
    meta = report["meta"]
    # A solo report has no opponent and never will (PLAN §0). Both renderers
    # already branch on this; the plain-text half did not, and it is the half
    # that goes in every email — it printed "Your Team vs None", then raised
    # KeyError on matchup['rival'] before any of it could be sent.
    solo = bool(meta.get("solo"))
    lines = [
        f"BEAT YOUR LEAGUE — {meta['league_name']} — "
        f"season {meta['season']} week {meta['week']}",
        # A subscriber's team by name (render.report.team_name), so two
        # teams' plain-text halves differ from their first lines.
        (team_name(report) or meta['my_label']) if solo
        else f"{meta['my_label']} vs {meta['rival_label']}",
        "",
    ]
    if meta.get("trial"):
        lines += [f"{TRIAL_HEAD.upper()}. {TRIAL_INTRO}", ""]
    if season_end_lines(meta):
        lines += [f"{SEASON_END_HEAD.upper()}. " + " ".join(season_end_lines(meta)), ""]
    lines += ["GAME PLAN"]
    for item in report["checklist"]:
        lines.append(f"  [ ] {item['action']}  ({item['deadline']})")
        if item.get("detail"):
            lines.append(f"      {item['detail']}")
    matchup = report["matchup"]
    head = "YOUR WEEK" if solo else "MATCHUP"
    if matchup.get("range_gate"):
        lines += ["", f"{head}: {matchup['range_gate']}"]
    elif solo:
        you = matchup["you"]
        # The band is labelled and defined here too (principle 5): the
        # plain-text half printed "(94.5–157.7)" with no name at all.
        lines += ["", f"{head}: {you['projected_total']:.1f} projected · "
                      f"{RANGE_LABEL} {range_text(you)}",
                  f"  {RANGE_LABEL.capitalize()}: {RANGE_DEFINITION}"]
    else:
        lines += [
            "",
            f"{head}: you {matchup['you']['projected_total']:.1f} proj vs "
            f"rival {matchup['rival']['projected_total']:.1f} proj",
        ]
    if matchup.get("win_probability") is not None:
        lines.append(f"  win probability: {matchup['win_probability']:.0%}")
    elif matchup.get("win_probability_gate"):
        lines.append(f"  {matchup['win_probability_gate']}.")
    # A solo report has neither, and `f"  {None}."` printed a literal "None" —
    # the same class of bug as the inbox preheader that read "the file on None".
    lines += ["", "YOUR BEST LINEUP"]
    # Same rule as the two HTML surfaces: the per-row marker earns its place
    # only in a MIXED week. With nothing published, nine identical "no call"s
    # said less than one line saying why — and plain text has no note under the
    # table to carry the reason, so it goes here.
    mixed = any(s.get("confidence") is not None for s in report["lineup"])
    for slot in report["lineup"]:
        name = slot.get("player_name") or "(empty)"
        projected = f"{slot['projected']:.1f}" if slot.get("projected") is not None else "—"
        if slot.get("confidence") is not None:
            confidence = f"{slot['confidence']:.0%} vs {slot.get('alternative_name')}"
        elif slot.get("player_name") and row_marked(slot, mixed):
            # The same words the HTML rows use ("start · X was questionable",
            # "no bench QB", "projection only") — this half said "no call"
            # after both HTML surfaces had moved on (found Sep 29 2026 on a
            # live 2026 build), and left structural rows blank (I16).
            confidence = row_label(slot)
        elif mixed:
            confidence = ""
        elif (meta.get("lineup_as_set") and slot.get("projected") is None
                and slot.get("usage")):
            # Week 1. The checklist says the slots are filled in last season's
            # scoring order and that the figure is "shown on each line" — true
            # of both HTML surfaces, and it was NOT true here, which made that
            # sentence a false statement in the half that goes in every email.
            # Week 1 only: mid-season, a starter on injured reserve has no
            # projection either, and his counted usage printed in the call
            # column ("De'Von Achane — last 2 games: 7 targets…" over "OUT").
            confidence = slot["usage"]
        else:
            confidence = ""
        # Availability flags travel on EVERY surface or none. The HTML grid has
        # printed "OUT — LV on bye (NFL schedule)" per row since the Tape
        # merge; this half never read slot["flags"], so the plain-text
        # alternative — what Apple Mail's plain-text mode and every screen
        # reader show — dropped the one field a wrong answer is unrecoverable
        # from. An HTML/text disagreement on availability is the drift the
        # shared-constant rule exists to prevent.
        # The opponent and kickoff ride the same sub-line (launch audit F7):
        # plain text is what a phone previews, and "@ DEN · Thu 8:15 PM ET" is
        # the one fact there that changes WHEN the lineup has to be set.
        under = " · ".join(([slot["game"]] if slot.get("game") else [])
                           + [f["text"] for f in (slot.get("flags") or [])])
        # The slot as the buyer reads it BEFORE padding (RQ-08): "SUPER_FLEX"
        # overran the six-character column and @buyer_slots then shortened it
        # to "SFLEX", leaving that row's name and number one column left.
        label = SLOT_DISPLAY.get(slot["slot"], slot["slot"])
        lines.append(
            f"  {label:<6} {name:<24} {projected:>6}  {confidence}".rstrip())
        if under:
            lines.append(f"  {'':<6} {under}")
        # The call's own facts, his games, and the reason line — what the two
        # HTML rows carry, so the plain-text half is not the thinner report.
        bits = call_bits(slot)
        if slot.get("confidence") is not None and edge_phrase(slot):
            bits = bits[1:]               # "70% vs Chase Brown" already names him
        for extra in (" · ".join(bits), form_phrase(slot), slot.get("reason") or ""):
            if extra:
                lines.append(f"  {'':<6} {extra}")
    # Plain text has no note under the table, so every reason a slot carries no
    # number has to arrive here — including the structural ones whose per-row
    # markers were dropped above. Printing them only in the all-gated case left
    # a mixed week's blank cells unexplained.
    gates = sorted({s["confidence_gate"] for s in report["lineup"]
                    if s.get("confidence_gate")})
    if gates:
        shown_marker = any(
            s.get("confidence") is None and s.get("player_name")
            and row_marked(s, mixed) for s in report["lineup"])
        # Plain text draws no bars, so the sentence about the bar goes.
        explain = no_call_explainer(gate_list(gates)).replace(
            ", and the bar starts at 50% (a toss-up)", "")
        lines.append(f"  {no_call_head(shown_marker and mixed, mixed)} {explain}")
    if projection_note(report["lineup"]):
        lines.append(f"  {projection_note(report['lineup'])}")
    # The rest of the roster. Plain text is what many phones preview and what a
    # screen reader reads, so a benched player missing here is missing, full
    # stop — the HTML table beside it does not help.
    bench = report.get("bench") or []
    if bench:
        lines += ["", BENCH_HEAD.upper()]
        for entry in bench:
            projected = (f"{entry['projected']:.1f}"
                         if entry.get("projected") is not None else "—")
            rank = (f"  [{entry['last_season_rank']} last season]"
                    if entry.get("notable") and entry.get("last_season_rank") else "")
            lines.append(f"  {entry['position']:<6} {entry['name']:<24} "
                         f"{projected:>6}  {bench_phrase(entry)}{rank}".rstrip())
            if entry.get("game"):
                lines.append(f"  {'':<6} {entry['game']}")
    regret = report["regret"]
    lines.append("")
    if "gate" in regret:
        lines.append(f"THE WEEK'S CLOSEST CALL: {no_call_line(regret)}")
    else:
        lines.append(
            f"THE WEEK'S CLOSEST CALL: start {regret['start_name']} over "
            f"{regret['over_name']} ({regret['confidence']:.0%})"
            + (f" — {regret['label'].lower()}" if regret.get("label") else ""))
        for key in ("definition", "reason", "closer"):
            if regret.get(key):
                lines.append(f"  {regret[key]}")
    # The if/then plan. The checklist's late-news line says "your if/then below
    # already has the answer" — and this half had no if/then at all until
    # Sep 29 2026, so in plain text that sentence pointed at nothing.
    if report.get("pivots"):
        lines += ["", "IF/THEN FOR GAMEDAY"]
        for plan in report["pivots"]:
            lines.append(f"  If {plan['condition']}: {pivot_action(plan, meta)}")
    if report.get("rising"):
        from render.report import RISING_HEAD, rising_intro
        lines += ["", RISING_HEAD.upper(), f"  {rising_intro(report['rising'])}"]
        lines += [f"  - {r['line']}" for r in report["rising"]]
    if meta.get("trial"):
        # The free report is the one email that reaches a non-customer and it
        # ends on how to buy, so it carries who sent it like every other
        # commercial email (CAN-SPAM, CASL; launch audit C14). It returned
        # before the paid footer's sender line, so it never printed one.
        # The ask comes BEFORE the fine print (panel review I2): it used to
        # be the last line, after the data source and the no-betting line.
        lines += [*_trial_cta_lines(meta),
                  "", "Projections are analysis, not guarantees — no betting "
                      "picks, no staking advice. Your decisions are yours.",
                  source_line(meta),
                  *([sender_line()] if sender_line() else [])]
        return "\n".join(lines) + "\n"
    lines += ["", f"RECEIPTS: {report['receipts'].get('note', '')}"]
    if report["receipts"].get("last_week_calls"):
        from engine.own_record import call_line
        lines += [f"  - {call_line(c)}" for c in report["receipts"]["last_week_calls"]]
    if report["receipts"].get("ask"):
        lines.append(report["receipts"]["ask"])
    # The gap list is operator bookkeeping (field names, internal reasons) and
    # never goes in a subscriber's email — the report already says, in place and
    # in plain words, wherever it declined to call something.
    lines += ["", "Projections are analysis, not guarantees — no betting picks, "
                  "no staking advice. Your decisions are yours.",
              source_line(meta),
              *read_lines(meta),
              *update_lines(meta),
              *_forward_lines(meta),
              "",
              # A seat's way out is a stop request, a subscriber's is the
              # billing page (render/report.cancel_lines; launch audit C4).
              *cancel_lines(is_seat(meta)),
              *([sender_line()] if sender_line() else [])]
    return "\n".join(lines) + "\n"

def solo_promise(report: Mapping[str, Any]) -> str:
    """What a solo report promises, in the subject and under the masthead.

    Week 1 carries an ORDERING, not a decision (CLAUDE.md: placement by last
    season's scoring, no projection, no confidence). "Decided" on that body
    oversells it by the body's own words."""
    if not any(s.get("projected") is not None for s in report.get("lineup", [])):
        return "your opening lineup"
    return "your lineup, decided"


def preheader_for(report: Mapping[str, Any]) -> str:
    """The inbox preview line, built from THIS report (panel review RQ-05).

    It was one fixed sentence promising "the one call worth arguing about" —
    above weeks 1-3 and every report whose closest-call section reads "No
    coin-flip call published". It names the closest call when there is one,
    and otherwise the game plan's first action; both are already in the body.
    """
    meta = report["meta"]
    if not meta.get("solo"):
        return (f'The file on {meta["rival_label"]}: your lineup, their fragile '
                f'spots, and the one call that matters.')
    regret = report.get("regret") or {}
    if "gate" not in regret and regret.get("start_name") and \
            regret.get("over_name") and regret.get("confidence") is not None:
        # The card's own label (COPY:F4): when it names a narrower decision
        # without odds (``closer``), "Closest call" in the preview was false
        # of the very card it previews.
        label = "Closest call with odds" if regret.get("closer") else "Closest call"
        # A toss-up reads "either is fine" on the card and the row; the
        # preview said "start X over Y, 51%" — an instruction the report
        # itself declines to give.
        from engine.solo_report import TOSSUP_PERCENT, TOSSUP_SENTENCE
        if (_pct(regret["confidence"]) <= TOSSUP_PERCENT
                or TOSSUP_SENTENCE in str(regret.get("reason") or "")):
            where = f" at {SLOT_DISPLAY.get(regret['slot'], regret['slot'])}" \
                if regret.get("slot") else ""
            return (f"{label}: {regret['start_name']} or {regret['over_name']}"
                    f"{where}, either is fine. Your whole lineup is inside.")
        return (f"{label}: start {regret['start_name']} over "
                f"{regret['over_name']}, {_pct(regret['confidence'])}%. "
                f"Your whole lineup is inside.")
    first = next((item.get("action") for item in report.get("checklist") or []
                  if item.get("action")), None)
    if first:
        return f"{str(first).rstrip('.')}. Your whole lineup is inside."
    return f"Week {meta['week']}: {solo_promise(report)}."


@buyer_slots
def subject_for(report: Mapping[str, Any]) -> str:
    """What lands in the inbox.

    Lives here rather than in a runner because it is part of the email surface,
    and there is now more than one runner: a copy per entry point is how the
    two surfaces drift, which is the whole reason render/report.py holds the
    shared sentences.

    A rival's name was the reason they opened it, and a solo report has no rival
    to name — "the file on None" would be the subject line.
    """
    meta = report["meta"]
    if meta.get("solo"):
        # A subscriber's team by name (render.report.team_name): a manager
        # with two teams got two identical subjects (panel review BE-I5).
        team = team_name(report)
        week = f"Week {meta['week']}" + (f" — {team}" if team else "")
        return f"{week}: {solo_promise(report)}"
    if meta.get("rivalry_week"):
        return f"Week {meta['week']}: RIVALRY WEEK vs {meta['rival_label']}"
    return f"Week {meta['week']}: the file on {meta['rival_label']}"


def _footer(meta: Mapping[str, Any]) -> str:
    basis = availability_basis(meta)
    if meta.get("trial"):
        # Sender identity on the free report too (launch audit C14): it is
        # the one email to a non-customer, and it ends on how to buy.
        return (
            f'<tr><td style="background:{PAPER};padding:20px 28px 26px 28px;">'
            f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — '
            f'{esc(BRAND_LINE)}<br>{esc(basis)}<br>'
            f'{esc(NO_BETTING_LINE)}<br>{esc(source_line(meta))}'
            + (f'<br>{esc(sender_line())}' if sender_line() else "")
            + '</p></td></tr>')
    return (
        f'<tr><td style="background:{PAPER};padding:20px 28px 26px 28px;'
        f'margin-top:24px;">'
        # A seat link is one long unbroken string: it wraps rather than
        # widening a phone's email.
        f'<p style="{SMALL}margin:0;overflow-wrap:anywhere;word-break:break-word;">'
        f'<b>Beat Your League</b> — '
        f'{esc(BRAND_LINE)}<br>{esc(basis)}<br>'
        f'{read_line(meta)}'
        f'{update_line(meta)}'
        f'{seats_line(meta)}'
        f'{_forward_line(meta)}'
        f'{esc(NO_BETTING_LINE)}<br>'
        f'{esc(source_line(meta))}<br>'
        f'{sender_html()}'
        f'{cancel_html(is_seat(meta), f"color:{NAVY};")}'
        '</p></td></tr>'
    )


def _your_week(matchup: Mapping[str, Any], no_opponent: str | None) -> str:
    """Your projected week. Half a scoreboard reads as a broken scoreboard, so
    a solo report shows one number and its range rather than an empty VS."""
    you = matchup["you"]
    gate = matchup.get("range_gate")
    if gate:
        body = _gate(gate)
    else:
        body = (
            f'<div style="{BASE}"><b>{esc(you["label"])}</b></div>'
            f'<div style="font-family:{DISPLAY};font-size:34px;font-weight:bold;'
            f'color:{TURF};line-height:1.1;">{you["projected_total"]:.1f}'
            f'<span style="{SMALL}font-size:12px;color:{SLATE};"> PROJ</span></div>'
            f'<div style="{BASE}font-weight:bold;color:#33445C;">{range_text(you)} '
            f'<span style="{SMALL}">{esc(RANGE_LABEL)}</span></div>'
            f'<p style="{SMALL}color:#33445C;margin:8px 0 0 0;">'
            f'<b style="color:{NAVY};">{esc(RANGE_LABEL.capitalize())}:</b> '
            f'{esc(RANGE_DEFINITION)}</p>')
        if matchup.get("range_basis"):
            body += f'<div style="{SMALL}margin-top:6px;">{esc(matchup["range_basis"])}</div>'
    if no_opponent:
        body += f'<p style="{SMALL}margin:12px 0 0 0;">{esc(no_opponent)}</p>'
    return _sec(2, "Your Week", body)


_USAGE_LINE = re.compile(r"last (\d+) games?: (.+)")


# A clause below this per-game rate is dropped from the SHORT line when
# another clause remains: "1 carry" over four games printed "0.2 car/g" on a
# receiver's row, clutter that reads as a role (panel review I11). The full
# line, every clause, stays on the browser report.
MIN_SHOWN_RATE = 0.5


def short_usage(text: str | None) -> str | None:
    """engine.usage.usage_line, said in a phone's width and a buyer's words:
    "last 4 games: 34 targets (8.5 a game), 21 carries" ->
    "last 4: 8.5 targets · 5.2 carries a game".

    The same counts over the same window, as per-game rates (launch audit F6),
    spelled out: "tgt/g" and "car/g" were our shorthand, not the reader's
    (panel review I11). A clause it does not recognise returns the whole line
    unchanged. A clause under MIN_SHOWN_RATE goes only when another stays, so
    a line never empties. Week 1's "last season: ..." basis is not a usage
    line and passes through untouched."""
    match = _USAGE_LINE.fullmatch(text or "")
    if not match:
        return text
    games = int(match.group(1))
    parts: list[tuple[float, str]] = []
    for clause in match.group(2).split(", "):
        targets = re.fullmatch(r"\d+ targets? \(([\d.]+) a game\)", clause)
        attempts = re.fullmatch(r"\d+ pass attempts? \(([\d.]+) a game\)", clause)
        carries = re.fullmatch(r"(\d+) carr(?:y|ies)", clause)
        if targets:
            rate = float(targets.group(1))
            parts.append((rate, f"{targets.group(1)} targets"))
        elif attempts:
            # A quarterback's volume (RQ-07): his throws, not a trick-play target.
            rate = float(attempts.group(1))
            parts.append((rate, f"{attempts.group(1)} pass attempts"))
        elif carries and games:
            rate = int(carries.group(1)) / games
            parts.append((rate, f"{rate:.1f} carries"))
        else:
            return text
    shown = [words for rate, words in parts if rate >= MIN_SHOWN_RATE]
    if not shown:
        shown = [max(parts)[1]]
    return f"last {games}: " + " · ".join(shown) + " a game"


# Fixed widths for the narrow columns, so the PLAYER column gets whatever is
# left. The call column used to be nowrap with "start · waiting on Rashid
# Shaheed" in it, which pushed the table past a phone's width and squeezed
# every name onto four to eight lines at 390px (launch audit F6).
_SLOT_W, _PROJ_W, _CALL_W = 40, 44, 60


def _your_lineup(report: Mapping[str, Any]) -> str:
    """The solo lineup: slot, player, projection, call. No tint, because a tint
    is a comparison and there is no opponent to compare against.

    Built for a phone first (launch audit F6). The call column carries only a
    percentage and its bar, never a sentence; the scan line is slot, name,
    projection, odds; and everything else — opponent and kickoff, any
    availability flag, why a row has no odds, the bench gap and usage — runs
    in a sub-row beneath the name that spans the projection and call columns
    too, instead of wrapping four to eight lines deep inside the player cell."""
    slots = report["lineup"]
    mixed = any(s.get("confidence") is not None for s in slots)
    shown_marker = False
    rows = []
    for slot in slots:
        name = slot.get("player_name") or "—"
        proj = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
        bits = call_bits(slot)
        # His games and his usage on lines of their own: joined, the row read
        # "2026: 20.4 a game · last 3: 15.4, 25.8, 14.6 · last 3: 8.3 targets"
        # — two "last 3"s, one of points and one of a usage window.
        record = form_phrase(slot)
        usage = short_usage(slot.get("usage"))
        flags = [esc(f["text"]) for f in (slot.get("flags") or [])]
        confidence = slot.get("confidence")
        label = ""
        if confidence is not None:
            # The number with the site's bar under it: 50% (a coin flip)
            # is the empty end, because every call is a head-to-head.
            call = (f'<b style="font-size:16px;color:{NAVY};">{_pct(confidence)}%</b>'
                    f'<div style="padding-top:4px;">'
                    f'{_bar((_pct(confidence) - 50) * 2, f"{_CALL_W - 8}px", align="right")}'
                    f'</div>')
        else:
            call = ""
            if slot.get("player_name") and row_marked(slot, mixed):
                shown_marker = True
                label = row_label(slot)
        # Everything but the name runs full width beneath it, one fact a line:
        # kickoff, availability, why no odds, the bench gap, his games and
        # usage, and a reason where one is owed.
        details = [
            (f'<span style="color:{NAVY};">{esc(slot["game"])}</span>'
             if slot.get("game") else ""),
            (f'<span style="color:{BRICK};font-weight:bold;">{" · ".join(flags)}</span>'
             if flags else ""),
            f'<b>{esc(label)}</b>' if label else "",
            esc(" · ".join(bits)) if bits else "",
            esc(record) if record else "",
            esc(usage) if usage else "",
            esc(slot["reason"]) if slot.get("reason") else "",
        ]
        details = [d for d in details if d]
        # Lean inline styles on purpose: these rows repeat per player, and a
        # 30-player roster has to stay far under Gmail's ~102 KB clip.
        line = f'border-bottom:1px solid {LINE};'
        pad = (f'padding:7px 8px {"1px" if details else "7px"} 8px;'
               f'{"" if details else line}vertical-align:top;')
        # The call spans the name row AND the detail row (launch review D7):
        # in the name row alone, the % and its bar made that row taller than
        # every other, opening a gap between a player's name and his kickoff
        # on exactly the rows that carry odds.
        span = call and details
        call_cell = (f'<td width="{_CALL_W}" rowspan="2" style="{BASE}padding:7px 8px '
                     f'7px 8px;{line}vertical-align:top;text-align:right;">{call}</td>'
                     if span else
                     f'<td width="{_CALL_W}" style="{BASE if call else ""}{pad}'
                     f'text-align:right;">{call}</td>')
        rows.append(
            f'<tr><td width="{_SLOT_W}" style="{SMALL}{pad}font-weight:bold;'
            f'white-space:nowrap;">{esc(slot["slot"])}</td>'
            f'<td style="{BASE}{pad}"><b>{esc(name)}</b></td>'
            f'<td width="{_PROJ_W}" style="{BASE}{pad}text-align:right;'
            f'font-weight:bold;white-space:nowrap;">{proj}</td>'
            f'{call_cell}</tr>')
        if details:
            rows.append(
                f'<tr><td style="{line}"></td>'
                f'<td colspan="{2 if span else 3}" style="{SMALL}padding:0 8px 7px 8px;'
                f'{line}">{"<br>".join(details)}</td></tr>')
    th = (f'{SMALL}font-weight:bold;text-transform:uppercase;letter-spacing:1px;'
          f'color:{NAVY};padding:0 8px 5px 8px;border-bottom:2px solid {NAVY};')
    head = (f'<tr><td width="{_SLOT_W}" style="{th}"></td>'
            f'<td style="{th}">Your lineup</td>'
            f'<td width="{_PROJ_W}" style="{th}text-align:right;">Proj</td>'
            f'<td width="{_CALL_W}" style="{th}text-align:right;">Call</td></tr>')
    note = ""
    gates = {s["confidence_gate"] for s in slots if s.get("confidence_gate")}
    if gates:
        head_text = no_call_head(shown_marker and mixed, mixed)
        note = _note(f'<b>{esc(head_text)}</b> '
                     f'{esc(no_call_explainer(gate_list(gates)))}')
    if projection_note(slots):
        note += _note(esc(projection_note(slots)))
    table = (f'<table role="presentation" width="100%" cellpadding="0" '
             f'cellspacing="0" border="0">{head}{"".join(rows)}</table>')
    seeded_note = (_note(esc(SEEDED_SECTION_LINE))
                   if report["meta"].get("seeded") else "")
    return _sec(3, "The Lineup", table + _bench(report) + seeded_note + note)


def _bench(report: Mapping[str, Any]) -> str:
    """The rest of the roster — the email twin of render.report._bench_table.

    Every rostered player is named. Muted against the lineup so the starters
    stay what the eye lands on, and an OUT player takes the brick flag the
    lineup rows use, while a benched starter-calibre player takes navy: a star
    the file chose to sit must not read as an injury.
    """
    bench = report.get("bench") or []
    if not bench:
        return ""
    rows = []
    for entry in bench:
        proj = (f'{entry["projected"]:.1f}' if entry.get("projected") is not None
                else "—")
        line = f'border-bottom:1px solid {LINE};'
        rank = entry.get("last_season_rank")
        tag = ""
        if entry.get("out"):
            tag = (f'<span style="color:{BRICK};font-weight:bold;">'
                   f'{esc(bench_phrase(entry))}</span>')
        else:
            # Dated questionable or the practice squad (BE-D3), then the rank.
            tag = " · ".join(t for t in (
                (f'<span style="color:{BRICK};font-weight:bold;">'
                 f'{esc(entry["note"])}</span>' if entry.get("note") else ""),
                (f'<span style="color:{NAVY};font-weight:bold;text-transform:'
                 f'uppercase;">{esc(rank)} last season</span>'
                 if entry.get("notable") and rank else "")) if t)
        game = (f'<span style="color:{NAVY};">{esc(entry["game"])}</span>'
                if entry.get("game") else "")
        sub = esc(bench_form(entry)) if bench_shows_form(entry) else ""
        details = [d for d in (game, tag, sub) if d]
        # Same shape as the lineup above (F6): the name on the scan line, the
        # why underneath at full width rather than four lines deep in a cell.
        pad = (f'padding:6px 8px {"1px" if details else "6px"} 8px;'
               f'{"" if details else line}vertical-align:top;')
        rows.append(
            f'<tr><td width="{_SLOT_W}" style="{SMALL}{pad}font-weight:bold;'
            f'white-space:nowrap;">{esc(entry["position"])}</td>'
            f'<td style="{SMALL}{pad}">{esc(entry["name"])}</td>'
            f'<td width="{_PROJ_W}" style="{SMALL}{pad}text-align:right;'
            f'white-space:nowrap;">{proj}</td><td width="{_CALL_W}" style="{pad}"></td></tr>')
        if details:
            rows.append(
                f'<tr><td style="{line}"></td>'
                f'<td colspan="3" style="{SMALL}padding:0 8px 6px 8px;{line}">'
                f'{"<br>".join(details)}</td></tr>')
    th = (f'{SMALL}font-weight:bold;text-transform:uppercase;letter-spacing:1px;'
          f'color:{SLATE};padding:14px 8px 5px 8px;border-bottom:1px solid {LINE};')
    head = (f'<tr><td width="{_SLOT_W}" style="{th}"></td>'
            f'<td style="{th}">{esc(BENCH_HEAD)}</td>'
            f'<td width="{_PROJ_W}" style="{th}text-align:right;">Proj</td>'
            f'<td width="{_CALL_W}" style="{th}"></td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{head}{"".join(rows)}</table>')


def _compose(report: Mapping[str, Any]) -> list[str]:
    """Sections in order, per product — the email twin of render.report.compose.

    Kept as a mirror rather than shared code because the two renderers speak
    different dialects (one has CSS, the other cannot), but the SECTION LIST
    must not diverge: a subscriber's email dropping a section the archived HTML
    carries is the drift `test_the_email_carries_what_the_browser_report_carries`
    exists to catch.
    """
    meta = report["meta"]
    if meta.get("solo"):
        team = team_name(report)
        promise = solo_promise(report)
        return [
            _header(meta, team, f"{team}: {promise}." if team
                    else f"{promise[:1].upper()}{promise[1:]}."),
            _checklist(report["checklist"]),
            _your_week(report["matchup"], report.get("no_opponent")),
            _your_lineup(report),
            _regret(report["regret"]),
            _pivots(report["pivots"], report["meta"], report.get("pivots_note")),
            _rising(report.get("rising") or []),
            "" if meta.get("trial") else _receipts(report["receipts"]),
        ]
    return [
        _header(meta),
        _checklist(report["checklist"]),
        _last_week(report.get("last_week")),
        _matchup(report["matchup"]),
        _rival_watch(report.get("rival_watch")),
        _tape(report),
        _fragility(report["fragility"], meta["rival_label"]),
        _regret(report["regret"]),
        _pivots(report["pivots"], report["meta"], report.get("pivots_note")),
        _hype(report["hype"], report.get("waiver_market")),
        _receipts(report["receipts"]),
    ]


@buyer_slots
def render_email(report: Mapping[str, Any]) -> str:
    """The full report as a self-contained, email-safe HTML document."""
    meta = report["meta"]
    # The preheader is the preview line an inbox shows BEFORE the mail is
    # opened, so it is the most-read sentence the product ships. The solo
    # version used to read "The file on None: your lineup, their fragile
    # spots..." — an absent value printed as a word, promising two things this
    # product does not do. It is built from the report now (preheader_for).
    preheader = preheader_for(report)
    sections = "".join(_compose(report) + [
        # The free report's ask sits ABOVE the footer, never in it.
        _trial_cta(meta) if meta.get("trial") else "",
        # breathing room between the last section and the footer band
        '<tr><td style="padding:12px;"></td></tr>',
        _footer(meta),
    ])
    sections = number_sections(sections)
    title = (f'Beat Your League — Week {esc(meta["week"])} '
             f'{"Report" if meta.get("solo") else "Rival Report"}')
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{EMAIL_META}<title>{title}</title>\n</head>\n'
        f'<body style="margin:0;padding:0;background:{PAPER};">\n'
        f'{preheader_html(preheader)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:18px 8px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:600px;width:100%;background:{CARD};">'
        f'{sections}</table></td></tr></table>\n</body>\n</html>\n'
    )
