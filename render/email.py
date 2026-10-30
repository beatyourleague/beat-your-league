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

from render.report import buyer_slots, note_gates

import os
import re
from typing import Any, Mapping

from render.sender import sender_line
from render.report import cancel_html, cancel_lines, is_seat, stop_route
from render.report import SATURDAY_LINE, SATURDAY_LINE_HEAD, saturday_line
from render.report import (NOT_CALLING_IT, ODDS_DEFINITION, RISING_HEAD,
                           bar_from_even, rising_intro)
from render.report import regret_tossup, regret_verdict
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

from render import anatomy
from render.anatomy import short_usage  # noqa: F401  (its long-standing home)

# The template's palette (:root in rival-report-template.html), as literals —
# email clients do not resolve var(). Roles are fixed (contract C6): navy for
# names, values, card heads and the masthead; ink2 for every fact line; slate
# for labels only; gold is a FILL, never text on paper; brick flags and unmet
# deadlines; turf met ones.
NAVY = "#101E33"
PAPER = "#F6F4EE"
CARD = "#FFFFFF"
LINE = "#E2DDD0"          # a card's border
DIVIDER = "#EEEAE1"       # rows inside a card
TRACK = "#E9E5DA"         # a bar's empty half
INK2 = "#33445C"
SLATE = "#5A6B80"
TURF = "#1E7A46"
BRICK = "#B3402F"
FLAG = "#F2C230"
FLAG_TINT = "#FBF3D9"
FLAG_EDGE = "#EBDDAE"
BRICK_TINT = "#F7E3DE"
BRICK_EDGE = "#E7BDB3"
TURF_TINT = "#DFF0E4"
CHIP_OK = "#E3F2E8"       # turf on this: 4.62:1
CHIP_DUE = "#F9E6E1"      # brick on this: 4.72:1
ON_NAVY = "#B9C2D0"       # text on navy: 9.31:1
MUTED_ON_NAVY = "#8FA3BC" # the stamp on navy, as the web and the phone: 6.48:1
LEAGUE_GOLD = "#F0B62A"   # only "League" in the lockup

FONT = "Arial,Helvetica,sans-serif"
# The condensed display face, from fonts the reader's device already has —
# an email may fetch nothing (tests/test_email_safety.py). Arial Narrow FIRST:
# Outlook's Word engine ignores a stack whose first face is missing and falls
# to Times, and Arial Narrow ships with Windows and macOS. Phones have neither,
# and fell to plain Arial, which wrapped "WEEK 7 · YOUR / REPORT" at 390px
# (pre-launch review D13): Apple's Helvetica Neue Condensed Bold and Avenir
# Next Condensed, then Android's Roboto Condensed, read as Barlow Condensed does.
DISPLAY = ("'Arial Narrow','HelveticaNeue-CondensedBold','Helvetica Neue Condensed',"
           "'Avenir Next Condensed','Roboto Condensed',Arial,Helvetica,sans-serif")
BASE = f"font-family:{FONT};font-size:14px;line-height:1.55;color:{NAVY};"
SMALL = f"font-family:{FONT};font-size:12px;line-height:1.5;color:{SLATE};"
# A fact line: what the engine says about a row, in ink2 (contract C8).
FACT = f"font-family:{FONT};font-size:13px;line-height:1.45;color:{INK2};"
# The lockup, as the site's nav draws it (render.report.site_bar): "Beat Your"
# in paper and "League" in the logo's gold, condensed italic capitals.
LOCKUP = (f'<span style="font-family:{DISPLAY};font-size:15px;font-weight:bold;'
          f'font-style:italic;letter-spacing:0.5px;text-transform:uppercase;'
          f'color:{PAPER};">Beat Your <span style="color:{LEAGUE_GOLD};">League</span></span>')
# A hairline between rows inside a card: a 1px cell, the one rule every
# client draws (a border on a <tr> is dropped by Outlook).
def _rule(cols: int = 1) -> str:
    span = f' colspan="{cols}"' if cols > 1 else ""
    return (f'<tr><td{span} style="height:1px;font-size:0;line-height:0;'
            f'background:{DIVIDER};">&nbsp;</td></tr>')


TRIAL_HEAD = "Your free report"
TRIAL_INTRO = "This one's on us, built from the roster you sent."
# "You won't hear from us again" was untrue across seasons (the limit is one
# per address per SEASON), and terms §4 promises the free report can be
# stopped by replying "stop" while the email never said so (final review
# COPY-2). The stop list is checked before every send (run/delivery.send_all).
TRIAL_ONLY = ("This is the only email we'll send you unless you sign up. Didn't "
              "ask for it? Reply \"stop\" and we won't send another, ever.")
# The free report's one ask (panel review I2). It was an unlinked URL inside
# the grey legal footer, after the data-source and no-betting lines, on the
# email whose whole job is to convert. No price here: the join page states
# the prices with their renewal terms beside them, which an email ask can't.
TRIAL_ASK_HEAD = "Want this every Tuesday?"
TRIAL_ASK = ("Your lineup decided like this one, every Tuesday, plus the "
             "Saturday check when injury news changes it.")
TRIAL_BUTTON = "Get next Tuesday's report"
# The channel tag the join page reads (^[a-z0-9-]{1,24}$), so a signup that
# came from a free report is counted as one (`make stats`).
TRIAL_VIA = "trial"


# The season's last week (EMAILS-69): there is no next Tuesday's report, and
# checkout closes once that week kicks off (D9), so the ask is next season's.
TRIAL_LAST_ASK_HEAD = "Want this next season?"
TRIAL_LAST_ASK = ("Your lineup decided like this one, every Tuesday from Week 1, "
                  "plus the Saturday check when injury news changes it.")
TRIAL_LAST_BUTTON = "Tell me when it opens"

# The free report's price line, at the TOP (pre-launch review M5): the one ask
# sat after the whole report with no price, so a reader who stopped at the
# lineup never learned what it costs. 2026 sells one-time passes, whose terms
# are short enough to sit beside the price — one payment, nothing renews, the
# refund window — worded as the landing's price card words them. From the
# week the join page may sell the $19 Playoff Pass instead (the landing's and
# join page's PLAYOFF_FROM_WEEK) the line names no price: the email cannot see
# whether that link is live, and a price the join page doesn't charge is
# worse than none. Nothing in the season's last week: there is no next one.
TRIAL_PLAYOFF_FROM_WEEK = 13
TRIAL_REFUND = ("Full refund, no questions, until your first weekly report's "
                "week kicks off. One per person.")


def trial_price_line(meta: Mapping[str, Any] | None) -> str | None:
    """The free report's offer, said once near the top, or None in the
    season's last week."""
    meta = meta or {}
    if _is_final_week(meta):
        return None
    from render.welcome import SEASON_PRICE
    week = meta.get("week")
    if isinstance(week, int) and week + 1 >= TRIAL_PLAYOFF_FROM_WEEK:
        offer = ("Every Tuesday through your title game: one payment, nothing "
                 "renews. The join page shows this week's price.")
    else:
        offer = (f"Every Tuesday through your title game: the {SEASON_PRICE} "
                 f"Rest-of-Season Pass, one payment, nothing renews.")
    return f"{offer} {TRIAL_REFUND}"


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
            f'<td style="background:{FLAG};border-radius:8px;">'
            f'<a href="{esc(url)}" style="display:inline-block;padding:14px 24px;'
            f'font-family:{DISPLAY};font-size:16px;font-weight:bold;'
            f'letter-spacing:1px;text-transform:uppercase;color:{NAVY};'
            f'text-decoration:none;">{esc(label)}</a></td></tr></table>')
    return (
        f'<tr><td style="padding:12px 0 0 0;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{NAVY};border-radius:12px;"><tr>'
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
    """The checklist's empty box: an 18px square, 2px navy, corners of 4. A
    table cell rather than a sized <div>: Outlook's Word engine ignores a
    div's height and draws it a line tall. The 14px cell inside plus the 2px
    border either side is the 18px box."""
    return (f'<table role="presentation" width="18" height="18" cellpadding="0" '
            f'cellspacing="0" border="0" style="border:2px solid {NAVY};'
            f'border-radius:4px;background:{CARD};"><tr><td width="14" height="14" '
            f'style="font-size:0;line-height:0;">&nbsp;</td></tr></table>')


def _chip(text: str, tone: str) -> str:
    """A deadline as a chip: turf once it is in hand, brick while it is still
    to meet (the web report's .chip.ok / .chip.due)."""
    color, ground = (TURF, CHIP_OK) if tone == "ok" else (BRICK, CHIP_DUE)
    return (f'<span style="display:inline-block;font-family:{FONT};font-size:11px;'
            f'font-weight:bold;line-height:1.4;text-transform:uppercase;'
            f'letter-spacing:.5px;color:{color};background:{ground};border-radius:4px;'
            f'padding:2px 6px;">{esc(text)}</span>')


def _section_row(key: str, html: str) -> str:
    """One block of the email, on the paper between cards. The comment names
    the block for the phone↔email parity check; Gmail strips it harmlessly."""
    return f'<tr><td style="padding:12px 0 0 0;"><!--sec:{key}-->{html}</td></tr>'


def _card(number: int, title: str, body: str) -> str:
    """A numbered card: a navy head with the title and its number, a white
    body. ``number`` says only WHETHER the card is numbered; the value is
    filled in positionally by number_sections() once the page is assembled,
    so the two surfaces cannot disagree and a merged section cannot leave a
    hole."""
    mark = (f'<td align="right" valign="middle" style="font-family:{DISPLAY};'
            f'font-size:13px;font-weight:bold;letter-spacing:1.5px;color:{FLAG};'
            f'white-space:nowrap;padding-left:12px;">{SECTION_MARK}</td>'
            if number else "")
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{CARD};border:1px solid {LINE};border-radius:12px;">'
        f'<tr><td style="background:{NAVY};border-radius:11px 11px 0 0;padding:10px 14px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0"><tr><td valign="middle" style="font-family:{DISPLAY};font-size:13px;'
        f'font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;color:{PAPER};">'
        f'{esc(title)}</td>{mark}</tr></table></td></tr>'
        f'<tr><td style="padding:6px 14px 14px 14px;">{body}</td></tr></table>')


def _sec(number: int, title: str, body: str, key: str = "") -> str:
    """One report section: a card, as a row of the email."""
    return _section_row(key or re.sub(r"[^a-z]+", "-", title.lower()).strip("-"),
                        _card(number, title, body))


def _gate(reason: str) -> str:
    """A withheld number, in the one honest form (principle 3)."""
    return (
        f'<div style="{BASE}font-size:13px;background:{FLAG_TINT};'
        f'border:1px solid {FLAG_EDGE};border-radius:8px;padding:10px 12px;'
        f'margin:10px 0 0 0;"><b>{esc(NOT_CALLING_IT)}:</b> {esc(reason)}</div>'
    )


def _bar(fill_pct: float, width: str, height: int = 6, align: str = "") -> str:
    """A bar as a two-cell table — the one bar every mail client draws: solid
    gold for the share, the track for the rest, rounded ends. ``fill_pct`` is
    the filled share, 0-100 (render.report.bar_from_even of the printed %)."""
    fill = max(0, min(100, round(fill_pct)))
    cell = f'height:{height}px;font-size:0;line-height:0;'
    end = height // 2
    filled = (f'<td width="{fill}%" style="{cell}background:{FLAG};'
              f'border-radius:{end}px {"0 0" if fill < 100 else f"{end}px {end}px"} '
              f'{end}px;">&nbsp;</td>' if fill else "")
    rest = (f'<td style="{cell}background:{TRACK};border-radius:'
            f'{"0" if fill else f"{end}px"} {end}px {end}px {"0" if fill else f"{end}px"};">'
            f'&nbsp;</td>' if fill < 100 else "")
    side = f' align="{align}"' if align else ""
    return (f'<table role="presentation"{side} width="{width}" cellpadding="0" '
            f'cellspacing="0" border="0" style="width:{width};"><tr>'
            f'{filled}{rest}</tr></table>')


def _note(inner_html: str) -> str:
    return (
        f'<div style="{FACT}margin:10px 0 0 0;">{inner_html}</div>'
    )


def _band(head: str, text_html: str) -> str:
    """A notice above the cards — the sample's, the free report's, the
    season's end: the task tint, a 1px edge, round corners. Information,
    never an alarm."""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="background:{FLAG_TINT};border:1px solid {FLAG_EDGE};'
            f'border-radius:12px;"><tr><td style="font-family:{FONT};font-size:13px;'
            f'line-height:1.5;color:{NAVY};padding:12px 14px;">'
            + (f'<b>{esc(head)}</b> ' if head else "") + f'{text_html}</td></tr></table>')


# --------------------------------------------------------------------- #
# the masthead every email opens with
# --------------------------------------------------------------------- #

def masthead_html(label: str, big: str, meta_html: str, stamp: str | None = None,
                  big_size: int = 30) -> str:
    """The navy masthead (contract C4/C8): the lockup with what this email is
    at its right, the big line, one meta line, and a stamp. Shared by every
    email the product sends, so the report, the Saturday check and the roster
    report open the same way. ``meta_html`` is escaped by the caller."""
    right = (f'<td align="right" valign="middle" style="padding-left:12px;">'
             f'<div style="font-family:{DISPLAY};font-size:12px;font-weight:bold;'
             # No nowrap: with a wide fallback font (DejaVu on Linux and
             # some Androids) lockup + label on one line made every email
             # 325px wide on a 320px phone (CI, Oct 25 2026). The label wraps.
             f'letter-spacing:1px;text-transform:uppercase;line-height:1.2;'
             f'color:{ON_NAVY};">{esc(label)}</div></td>' if label else "")
    return (
        f'<tr><td style="background:{NAVY};border-radius:12px;padding:18px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0"><tr><td valign="middle" style="white-space:nowrap;">{LOCKUP}</td>'
        f'{right}</tr></table>'
        f'<div style="font-family:{DISPLAY};font-size:{big_size}px;font-weight:bold;'
        f'text-transform:uppercase;line-height:1.05;color:#FFFFFF;padding:12px 0 6px;">'
        f'{esc(big)}</div>'
        f'<div style="font-family:{FONT};font-size:13px;line-height:1.45;color:{ON_NAVY};">'
        f'{meta_html}</div>'
        + (f'<div style="font-family:{FONT};font-size:12px;line-height:1.45;'
           f'color:{MUTED_ON_NAVY};padding-top:2px;">{esc(stamp)}</div>' if stamp else "")
        + '</td></tr>')


def _header(meta: Mapping[str, Any], team: str | None = None) -> str:
    """The masthead and the notices under it (render.anatomy.masthead,
    .bands). ``team`` names a subscriber's roster (render.report.team_name) so
    two teams' emails can be told apart."""
    head = anatomy.masthead({"meta": meta, "lineup": []})
    extra = "".join(f' · {esc(lead)}<b style="color:#FFFFFF;">{esc(value)}</b>'
                    if lead else f' · <b style="color:{FLAG};">{esc(value)}</b>'
                    for lead, value in head["extra"])
    meta_html = (f'<b style="color:#FFFFFF;">{esc(team or head["team"])}</b> · '
                 f'{esc(head["meta"])}{extra}')
    out = [masthead_html(head["label"], head["week"], meta_html, head["stamp"])]
    for band in anatomy.bands({"meta": meta}):
        words = esc(band["text"])
        if band.get("price"):
            words += f'<br><br>{esc(band["price"])}'
            if band.get("link"):
                href, label = band["link"]
                words += (f' <a href="{esc(href)}" style="color:{NAVY};'
                          f'font-weight:bold;">{esc(label)}</a>')
        out.append(_section_row(f"band-{band['kind']}", _band(band["head"], words)))
    return "".join(out)


# --------------------------------------------------------------------- #
# the plan: one item, every surface's anatomy (render.anatomy.item)
# --------------------------------------------------------------------- #

def _item_cells(model: Mapping[str, Any], *, detail: bool = True,
                head_color: str = NAVY) -> str:
    """An item's words: the bold head and its plain rest, why, the chip."""
    return (
        f'<div style="font-family:{FONT};font-size:15px;line-height:1.4;color:{head_color};">'
        f'<b>{esc(model["head"])}</b>{esc(model["rest"])}</div>'
        + (f'<div style="{FACT}padding-top:3px;">{esc(model["detail"])}</div>'
           if detail and model.get("detail") else "")
        + (f'<div style="padding-top:6px;">{_chip(model["deadline"], model["tone"])}</div>'
           if model.get("deadline") else ""))


def _item_row(model: Mapping[str, Any], *, rule: bool, head_color: str = NAVY) -> str:
    """One plan item as two cells: the tick box, then its words. An item with
    nothing to do has no box, and its words take both columns."""
    out = _rule(2) if rule else ""
    if model.get("box", True):
        return out + (
            f'<tr><td width="18" valign="top" style="padding:12px 10px 10px 0;">'
            f'{tick_box()}</td><td valign="top" style="padding:10px 0;">'
            f'{_item_cells(model, head_color=head_color)}</td></tr>')
    return out + (f'<tr><td colspan="2" valign="top" style="padding:10px 0;">'
                  f'{_item_cells(model, head_color=head_color)}</td></tr>')


def _items_table(models: list[Mapping[str, Any]], head_color: str = NAVY) -> str:
    rows = "".join(_item_row(m, rule=i > 0, head_color=head_color)
                   for i, m in enumerate(models))
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0">{rows}</table>')


def _plan_body(model: Mapping[str, Any]) -> str:
    body = _items_table(model["items"])
    if model.get("saturday"):
        body += (f'<table role="presentation" width="100%" cellpadding="0" '
                 f'cellspacing="0" border="0">{_rule()}<tr><td style="{FACT}'
                 f'padding:10px 0 0 0;"><b style="color:{NAVY};">'
                 f'{esc(SATURDAY_LINE_HEAD)}:</b> {esc(model["saturday"])}</td></tr></table>')
    return body


def _alert(model: Mapping[str, Any]) -> str:
    """An empty spot, above the lineup: still a task to tick, in the alert
    tint, its head in brick."""
    return _section_row("alert", (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{BRICK_TINT};border:1px solid {BRICK_EDGE};'
        f'border-radius:12px;"><tr><td style="padding:2px 14px;">'
        f'{_items_table([model], head_color=BRICK)}</td></tr></table>'))


def _checklist(items: list[Mapping[str, Any]],
               meta: Mapping[str, Any] | None = None) -> str:
    """The game plan as the league product's emails carry it: every item."""
    model = {"items": [anatomy.item(i) for i in items],
             "saturday": SATURDAY_LINE if saturday_line(meta) else None}
    return _sec(1, "Your Game Plan", _plan_body(model), "plan")


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
        gates = note_gates(mine)
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


def _closest_body(model: Mapping[str, Any]) -> str:
    """Card 02: the label, the verdict, a full-width bar with the big % (drawn
    from 50%, like every bar in the report), the drivers, why, and the closer
    after a hairline. No title inside the card: its head already says "The
    Week's Closest Call" (panel review D8). With no call, one plain line."""
    if "gate" in model:
        return f'<p style="{BASE}margin:10px 0 0 0;">{esc(model["gate"])}</p>'
    before, joiner, after = model["verdict"]
    drivers = " · ".join(f'{esc(label)} <b style="color:{NAVY};">{esc(value)}</b>'
                         for label, value in model.get("drivers") or [])
    return (
        (f'<div style="{SMALL}font-size:11px;font-weight:bold;letter-spacing:1px;'
         f'text-transform:uppercase;padding-top:8px;">{esc(model["label"])}</div>'
         if model.get("label") else "")
        + f'<div style="font-family:{FONT};font-size:17px;font-weight:bold;line-height:1.35;'
          f'color:{NAVY};padding-top:4px;">{esc(before)} <span style="font-weight:normal;'
          f'color:{SLATE};">{esc(joiner)}</span> {esc(after)}</div>'
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
          f'border="0"><tr><td valign="middle" style="padding:6px 12px 0 0;">'
          f'{_bar(model["bar"], "100%", 8)}</td>'
          f'<td width="64" align="right" valign="middle" style="font-family:{DISPLAY};'
          f'font-size:28px;font-weight:bold;font-style:normal;color:{NAVY};'
          f'white-space:nowrap;padding-top:4px;">{model["pct"]}%</td></tr></table>'
        + (f'<div style="{FACT}padding-top:6px;">{drivers}</div>' if drivers else "")
        + "".join(f'<div style="{FACT}padding-top:6px;">{esc(line)}</div>'
                  for line in model.get("lines") or [])
        + (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           f'border="0" style="margin-top:10px;">{_rule()}<tr><td style="{FACT}'
           f'padding-top:10px;">{esc(model["closer"])}</td></tr></table>'
           if model.get("closer") else ""))


def _regret(regret: Mapping[str, Any]) -> str:
    return _sec(6, "The Week's Closest Call",
                _closest_body(anatomy.closest({"regret": regret})), "closest")


def _ifthen_body(model: Mapping[str, Any]) -> str:
    """Card 04: "If …" in brick capitals, then the move in bold, then why."""
    if not model["plans"]:
        return f'<p style="{BASE}margin:10px 0 0 0;">{esc(model["empty"])}</p>'
    rows = []
    for i, plan in enumerate(model["plans"]):
        if i:
            rows.append(_rule())
        rows.append(
            f'<tr><td style="padding:10px 0;">'
            f'<div style="font-family:{FONT};font-size:12px;font-weight:bold;'
            f'letter-spacing:.5px;text-transform:uppercase;color:{BRICK};">'
            f'{esc(plan["if"])}</div>'
            f'<div style="font-family:{FONT};font-size:15px;font-weight:bold;'
            f'line-height:1.4;color:{NAVY};padding-top:3px;">{esc(plan["then"])}</div>'
            + (f'<div style="{FACT}padding-top:3px;">{esc(plan["rest"])}</div>'
               if plan.get("rest") else "") + '</td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0">{"".join(rows)}</table>')


def _pivots(plans: list[Mapping[str, Any]],
            meta: Mapping[str, Any] | None = None,
            note: str | None = None) -> str:
    model = anatomy.ifthen({"pivots": plans, "meta": meta or {}, "pivots_note": note})
    return _sec(7, "If/Then for Gameday", _ifthen_body(model), "ifthen")


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


def _rising_body(model: Mapping[str, Any]) -> str:
    """Card 06: the intro, then one player a row — the name set apart, what
    he is getting beneath it — split by hairlines."""
    rows = []
    for i, (who, what) in enumerate(model["rows"]):
        if i:
            rows.append(_rule())
        rows.append(f'<tr><td style="{FACT}padding:9px 0;">'
                    + (f'<span style="font-size:14px;color:{NAVY};"><b>{esc(who)}</b>'
                       f'</span><br>' if who else "")
                    + f'{esc(what)}</td></tr>')
    return (f'<p style="{FACT}margin:10px 0 2px 0;">{esc(model["intro"])}</p>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0">{"".join(rows)}</table>')


def _rising(rows) -> str:
    model = anatomy.rising({"rising": rows})
    return _sec(8, RISING_HEAD, _rising_body(model), "rising") if model else ""


def _receipts_body(receipts: Mapping[str, Any]) -> str:
    """Card 07, content as it has always been."""
    stamp_style = (f'display:inline-block;font-family:{FONT};font-size:11px;'
                   f'font-weight:bold;text-transform:uppercase;letter-spacing:1px;'
                   f'color:{SLATE};background:{DIVIDER};border-radius:4px;padding:2px 6px;')
    record = receipts.get("record")
    if not record:
        # D12: the stamp only where this report has odds and a next report.
        stamp = receipts.get("stamp", "Results · from next week")
        inner = (f'{esc(receipts.get("note", ""))}'
                 + (f'<br><span style="{stamp_style}margin-top:8px;">{esc(stamp)}</span>'
                    if stamp else ""))
    elif receipts.get("last_week_calls") is not None:
        from engine.own_record import HIT, MISS, call_line
        mark = {HIT: (TURF, "✓"), MISS: (BRICK, "✗")}
        rows = "".join(
            f'<div style="{FACT}color:{NAVY};padding:3px 0;">'
            f'<b style="color:{mark.get(c["outcome"], (NAVY, "–"))[0]};">'
            f'{mark.get(c["outcome"], (NAVY, "–"))[1]}</b> {esc(call_line(c))}</div>'
            for c in receipts["last_week_calls"])
        ask = (f'<div style="{BASE}margin-top:10px;">{esc(receipts["ask"])}</div>'
               if receipts.get("ask") else "")
        inner = (f'{esc(receipts.get("note", ""))}'
                 f'<div style="margin-top:8px;">{rows}</div>'
                 f'<span style="{stamp_style}">Graded on real box scores</span>{ask}')
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
                 + f'<br><span style="{stamp_style}margin-top:8px;">Graded on real box '
                   f'scores</span>')
    return f'<p style="{BASE}margin:10px 0 0 0;">{inner}</p>'


def _receipts(receipts: Mapping[str, Any]) -> str:
    return _sec(9, "The Receipts", _receipts_body(receipts), "receipts")


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
    """Plain-text digest of the report — the text half of every email.

    Same order, same rows and same words as the HTML (contract C1/C2,
    render.anatomy): the masthead, the notices, any empty spot, then the
    seven cards. Flags travel on every surface or none."""
    if not report["meta"].get("solo"):
        return _league_text(report)
    return _solo_text(report)


def _closest_text(regret: Mapping[str, Any]) -> list[str]:
    """The closest call's plain-text lines, today's words."""
    if "gate" in regret:
        return [f"THE WEEK'S CLOSEST CALL: {no_call_line(regret)}"]
    before, joiner, after = regret_verdict(regret)
    if not regret_tossup(regret):
        # "Start X" reads "start X" after the colon; a toss-up's head is
        # the bare NAME, which keeps its capital ("george Pickens or ...").
        before = before[:1].lower() + before[1:]
    lines = [f"THE WEEK'S CLOSEST CALL: {before} {joiner} "
             f"{after} ({regret['confidence']:.0%})"
             + (f" — {regret['label'].lower()}" if regret.get("label") else "")]
    drivers = " · ".join(f"{d['label']} {d['value']}" for d in regret.get("drivers") or [])
    if drivers:
        lines.append(f"  {drivers}")
    for key in ("definition", "reason", "closer"):
        if regret.get(key):
            lines.append(f"  {regret[key]}")
    return lines


def _solo_text(report: Mapping[str, Any]) -> str:
    meta = report["meta"]
    head = anatomy.masthead(report)
    lines = [f"BEAT YOUR LEAGUE — {head['week'].upper()} — {head['label'].upper()}",
             f"{head['team']} · {head['meta']}", head["stamp"], ""]
    if meta.get("trial"):
        lines += [f"{TRIAL_HEAD.upper()}. {TRIAL_INTRO}"]
        if trial_price_line(meta):
            lines.append(trial_price_line(meta)
                         + (f" {TRIAL_BUTTON}: {trial_join_url(meta)}"
                            if trial_join_url(meta) else ""))
        lines.append("")
    if season_end_lines(meta):
        lines += [f"{SEASON_END_HEAD.upper()}. " + " ".join(season_end_lines(meta)), ""]
    for item in report.get("checklist") or []:
        if anatomy.is_certain_zero(item):
            lines.append(f"[ ] {item['action']}  ({item['deadline']})")
            if item.get("detail"):
                lines.append(f"    {item['detail']}")
            lines.append("")
    # 01 — every starter, decided.
    lineup = anatomy.lineup(report)
    lines.append(lineup["title"].upper())
    if lineup["week"]:
        week = lineup["week"]
        lines.append(f"  {week['total']} projected · {week['range_label']} {week['range']}")
    elif lineup["gate"]:
        lines.append(f"  {NOT_CALLING_IT}: {lineup['gate']}")
    for extra in (lineup["basis"], lineup["note"]):
        if extra:
            lines.append(f"  {extra}")
    if lineup["heads"]:
        lines.append(f"  {'':<6} {'':<24} {'PROJ':>5}"
                     + ("  ODDS" if lineup["heads"] == "proj+odds" else ""))
    for row in lineup["rows"]:
        call = f"{row['pct']}%" if row["pct"] is not None else (row["label"] or "")
        lines.append(f"  {row['slot']:<6} {row['name']:<24} {row['proj'] or '—':>5}  "
                     f"{call}".rstrip())
    set_item = next((i for i in report.get("checklist") or [] if anatomy.is_set_lineup(i)),
                    None)
    if set_item:
        # The lineup's own list stays here: plain text has no rows to tick.
        lines.append(f"  [ ] {set_item['action']}  ({set_item['deadline']})")
        if set_item.get("detail"):
            lines.append(f"      {set_item['detail']}")
    if any(r["pct"] is not None for r in lineup["rows"]):
        # Plain text draws no bars, so the clause about the bar goes.
        lines.append("  " + ODDS_DEFINITION.replace(
            ", and the bar starts at 50% (a toss-up)", ""))
    if lineup["week"]:
        lines.append(f"  {RANGE_LABEL.capitalize()}: {RANGE_DEFINITION}")
    checked = anatomy.checked_line(report)
    if checked:
        lines.append(f"  {anatomy.CHECKED_HEAD} {checked}")
    # 02 — the closest call.
    lines += ["", *_closest_text(report.get("regret") or {})]
    # 03 — what to do and by when.
    plan = anatomy.plan(report)
    plan_items = [i for i in report.get("checklist") or []
                  if not anatomy.is_set_lineup(i) and not anatomy.is_certain_zero(i)]
    if plan_items or plan["saturday"]:
        lines += ["", "YOUR GAME PLAN"]
        for item, model in zip(plan_items, plan["items"]):
            lines.append(f"  {'[ ]' if model['box'] else ' - '} {item['action']}  "
                         f"({item['deadline']})")
            if item.get("detail"):
                lines.append(f"      {item['detail']}")
        if saturday_line(meta):
            lines.append(f"  {saturday_line(meta)}")
    # 04 — the if/then. The game plan's late-news line says "your if/then
    # below already has the answer" — so it is always here, plans or not.
    lines += ["", "IF/THEN FOR GAMEDAY"]
    if report.get("pivots"):
        for entry in report["pivots"]:
            lines.append(f"  If {entry['condition']}: {pivot_action(entry, meta)}")
    else:
        lines.append(f"  {anatomy.ifthen(report)['empty']}")
    # 05 — the reasoning behind every slot, and the rest of the roster.
    slots = anatomy.slots(report)
    lines += ["", "SLOT BY SLOT"]
    for row in slots["rows"]:
        # Name first, so a slot code starts only the lineup's own rows above.
        lines.append(f"  {row['name']} ({row['slot']}) · proj {row['proj'] or '—'}")
        for extra in (row["game"], " · ".join(row["flags"]) or None, row["call"],
                      row["form"], row["usage"], row["reason"]):
            if extra:
                lines.append(f"    {extra}")
    if slots["bench"]:
        lines += ["", BENCH_HEAD.upper()]
        for entry in slots["bench"]:
            said = " · ".join(t for t in (entry["form"], entry["note"], entry["rank"]) if t)
            lines.append(f"  {entry['position']:<6} {entry['name']:<24} "
                         f"{entry['proj'] or '—':>5}  {said}".rstrip())
            if entry["game"]:
                lines.append(f"  {'':<6} {entry['game']}")
    for note in slots["notes"]:
        lines.append("  " + (f"{note['head']} " if note["head"] else "") + note["text"])
    # 06 — rising roles.
    if report.get("rising"):
        lines += ["", RISING_HEAD.upper(), f"  {rising_intro(report['rising'])}"]
        lines += [f"  - {r['line']}" for r in report["rising"]]
    if meta.get("trial"):
        # The free report is the one email that reaches a non-customer and it
        # ends on how to buy, so it carries who sent it like every other
        # commercial email (CAN-SPAM, CASL; launch audit C14). The ask comes
        # BEFORE the fine print (panel review I2), and the data-age sentence
        # (principle 3) rides the text half too (final review PIPE-7).
        lines += [*_trial_cta_lines(meta),
                  "", NO_BETTING_LINE,
                  source_line(meta),
                  availability_basis(meta),
                  *([sender_line()] if sender_line() else [])]
        return "\n".join(lines) + "\n"
    # 07 — the receipts.
    lines += ["", f"RECEIPTS: {report['receipts'].get('note', '')}"]
    if report["receipts"].get("last_week_calls"):
        from engine.own_record import call_line
        lines += [f"  - {call_line(c)}" for c in report["receipts"]["last_week_calls"]]
    if report["receipts"].get("ask"):
        lines.append(report["receipts"]["ask"])
    lines += ["", NO_BETTING_LINE,
              source_line(meta),
              availability_basis(meta),
              *read_lines(meta),
              *update_lines(meta),
              *_forward_lines(meta),
              "",
              *cancel_lines(stop_route(meta)),
              *([sender_line()] if sender_line() else [])]
    return "\n".join(lines) + "\n"


def _league_text(report: Mapping[str, Any]) -> str:
    """The retired league product's text half, as it was."""
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
        lines += [f"{TRIAL_HEAD.upper()}. {TRIAL_INTRO}"]
        if trial_price_line(meta):
            lines.append(trial_price_line(meta)
                         + (f" {TRIAL_BUTTON}: {trial_join_url(meta)}"
                            if trial_join_url(meta) else ""))
        lines.append("")
    if season_end_lines(meta):
        lines += [f"{SEASON_END_HEAD.upper()}. " + " ".join(season_end_lines(meta)), ""]
    lines += ["GAME PLAN"]
    for item in report["checklist"]:
        lines.append(f"  [ ] {item['action']}  ({item['deadline']})")
        if item.get("detail"):
            lines.append(f"      {item['detail']}")
    if saturday_line(meta):
        lines.append(f"  {saturday_line(meta)}")
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
    gates = sorted(note_gates(report["lineup"]))
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
        before, joiner, after = regret_verdict(regret)
        if not regret_tossup(regret):
            # "Start X" reads "start X" after the colon; a toss-up's head is
            # the bare NAME, which keeps its capital ("george Pickens or ...").
            before = before[:1].lower() + before[1:]
        lines.append(
            f"THE WEEK'S CLOSEST CALL: {before} {joiner} "
            f"{after} ({regret['confidence']:.0%})"
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
        # The data-age sentence (principle 3) rides the text half too: the
        # HTML footer has always printed it and this half never did, so the
        # version `run.trial --print` pastes into a group chat carried no
        # "as of" and no box-score line (final review PIPE-7).
        lines += [*_trial_cta_lines(meta),
                  "", NO_BETTING_LINE,
                  source_line(meta),
                  availability_basis(meta),
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
    lines += ["", NO_BETTING_LINE,
              source_line(meta),
              availability_basis(meta),
              *read_lines(meta),
              *update_lines(meta),
              *_forward_lines(meta),
              "",
              # A seat's way out is a stop request, a subscriber's is the
              # billing page (render/report.cancel_lines; launch audit C4).
              *cancel_lines(stop_route(meta)),
              *([sender_line()] if sender_line() else [])]
    return "\n".join(lines) + "\n"

def empty_spots(report: Mapping[str, Any]) -> int:
    """How many starting spots score zero this week unless the reader acts — a
    bye or a reserve list with nobody eligible behind him, or nobody rostered
    there at all (the game plan's certain zero lines, engine.week_report)."""
    return sum(len((item.get("zero") or {}).get("slots") or [])
               for item in report.get("checklist") or []
               if (item.get("zero") or {}).get("certain"))


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
    # A spot that scores zero unless they act outranks any close call (pre-
    # launch review F6): a bye week with four empty spots previewed as
    # "Closest call: start Michael Wilson over Rachaad White, 55%".
    hole = next((item for item in report.get("checklist") or []
                 if (item.get("zero") or {}).get("certain")), None)
    if hole is not None:
        return f"{str(hole['action']).rstrip('.')}. Your whole lineup is inside."
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
        if regret_tossup(regret):
            where = f" at {SLOT_DISPLAY.get(regret['slot'], regret['slot'])}" \
                if regret.get("slot") else ""
            return (f"{label}: {regret['start_name']} or {regret['over_name']}"
                    f"{where}, either is fine. Your whole lineup is inside.")
        return (f"{label}: start {regret['start_name']} over "
                f"{regret['over_name']}, {_pct(regret['confidence'])}%. "
                f"Your whole lineup is inside.")
    # The first thing to DO, never the lineup itself (the preview would only
    # repeat the subject) and never an item with nothing to do (Week 1's
    # basis line is a paragraph, not an action).
    first = next((item.get("action") for item in report.get("checklist") or []
                  if item.get("action") and not anatomy.is_set_lineup(item)
                  and item.get("urgency") != "done"), None)
    if first:
        return f"{str(first).rstrip('.')}. Your whole lineup is inside."
    if not anatomy.any_projection(report):
        # True by the engine's own placement rule (engine.solo_report:
        # Week 1 places by last season's points per appearance).
        return "Your opening lineup, every slot filled in last season's scoring order."
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
        # The subject leads with an empty spot when there is one (F6): it is
        # the one thing in the report that costs points if left unread.
        holes = empty_spots(report)
        if holes:
            spots = "an empty spot" if holes == 1 else f"{holes} empty spots"
            return f"{week}: {spots} to fill before kickoff"
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
            f'<tr><td style="background:{PAPER};padding:20px 4px 8px 4px;">'
            f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — '
            f'{esc(BRAND_LINE)}<br>{esc(basis)}<br>'
            f'{esc(NO_BETTING_LINE)}<br>{esc(source_line(meta))}'
            + (f'<br>{esc(sender_line())}' if sender_line() else "")
            + '</p></td></tr>')
    return (
        f'<tr><td style="background:{PAPER};padding:20px 4px 8px 4px;">'
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
        f'{cancel_html(stop_route(meta), f"color:{NAVY};")}'
        '</p></td></tr>'
    )


def _lineup_body(model: Mapping[str, Any]) -> str:
    """Card 01, every starter decided: the week's total and range on top,
    then one line a slot — slot, name, projection, the bar and the % where
    odds print — then the one box to tick, then what the % and the range
    mean.

    Built for a phone first. The scan line is slot, name, projection, odds;
    a reason a row has no % rides a short second line under the name, never
    a column (launch audit F6: a sentence in a nowrap call cell pushed the
    email to 413px on a 390px phone). Lean inline styles on purpose: these
    rows repeat per player, and the email has to stay far under Gmail's
    ~102 KB clip."""
    out = []
    week = model.get("week")
    if week:
        out.append(
            f'<div style="padding:10px 0 4px 0;font-family:{FONT};color:{NAVY};">'
            f'<b style="font-family:{DISPLAY};font-size:28px;line-height:1;">'
            f'{esc(week["total"])}</b>'
            # The same lowercase unit as "realistic range" beside it, as the
            # web report and the landing's phone print it (contract C8).
            f'<span style="font-size:12px;color:{SLATE};"> proj</span>&nbsp; '
            f'<b style="font-size:15px;color:{INK2};white-space:nowrap;">{esc(week["range"])}</b>'
            f'<span style="font-size:12px;color:{SLATE};"> {esc(week["range_label"])}</span></div>')
    elif model.get("gate"):
        out.append(f'<p style="{FACT}margin:10px 0 4px 0;"><b style="color:{NAVY};">'
                   f'{esc(NOT_CALLING_IT)}:</b> {esc(model["gate"])}</p>')
    if model.get("basis"):
        out.append(f'<p style="{SMALL}margin:4px 0 0 0;">{esc(model["basis"])}</p>')
    if model.get("note"):
        out.append(f'<p style="{FACT}font-size:12px;margin:6px 0 0 0;">'
                   f'{esc(model["note"])}</p>')
    heads = model.get("heads")
    cols = 5 if heads == "proj+odds" else 3 if heads == "proj" else 2
    rows = []
    if heads:
        # 11px, the smallest any email text is drawn (a phone's legibility
        # floor in the launch check's probe).
        th = (f'font-family:{FONT};font-size:11px;font-weight:bold;letter-spacing:1px;'
              f'text-transform:uppercase;color:{SLATE};padding:8px 0 4px 0;')
        rows.append(
            f'<tr><td width="34"></td><td></td>'
            f'<td width="38" align="right" style="{th}">Proj</td>'
            + (f'<td colspan="2" align="right" style="{th}">Odds</td>'
               if cols == 5 else "") + '</tr>')
    for row in model["rows"]:
        label = row.get("label") if row.get("pct") is None else None
        below = "1px" if label else "9px"
        rows.append(_rule(cols))
        cells = [
            f'<td width="34" valign="top" style="font-family:{FONT};font-size:11px;'
            f'font-weight:bold;letter-spacing:1px;color:{SLATE};padding:11px 0 {below} 0;">'
            f'{esc(row["slot"])}</td>',
            f'<td valign="top" style="font-family:{FONT};font-size:15px;font-weight:bold;'
            f'line-height:1.3;color:{NAVY};padding:9px 8px {below} 0;">{esc(row["name"])}</td>',
        ]
        if cols >= 3:
            cells.append(
                f'<td width="38" align="right" valign="top" style="font-family:{FONT};'
                f'font-size:14px;color:{INK2};padding:10px 0 {below} 0;">'
                f'{esc(row["proj"] or "—")}</td>')
        if cols == 5:
            if row.get("pct") is not None:
                cells.append(f'<td width="34" valign="top" style="padding:16px 0 0 6px;">'
                             f'{_bar(row["bar"], "100%")}</td>'
                             f'<td width="40" align="right" valign="top" style="font-family:'
                             f'Arial,Helvetica,sans-serif;font-size:16px;font-weight:bold;'
                             f'color:{NAVY};'
                             f'padding:8px 0 9px 0;white-space:nowrap;">{row["pct"]}%</td>')
            else:
                cells.append('<td width="34"></td><td width="40"></td>')
        rows.append(f'<tr>{"".join(cells)}</tr>')
        if label:
            if row.get("tone") == "basis":
                style = f'{FACT}padding:1px 0 9px 0;'
            else:
                # Sentence case like the web row (.fnc); only a red flag
                # keeps its capitals (review: tracked capitals read as error
                # codes).
                style = (f'font-family:{FONT};font-size:12px;font-weight:bold;line-height:1.4;'
                         + (f'letter-spacing:.5px;text-transform:uppercase;color:{BRICK};'
                            if row.get("tone") == "flag" else f'color:{SLATE};')
                         + 'padding:1px 0 9px 0;')
            rows.append(f'<tr><td></td><td colspan="{cols - 1}" style="{style}">'
                        f'{esc(label)}</td></tr>')
    out.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
               f'border="0">{"".join(rows)}</table>')
    task = model.get("task")
    if task:
        # The rows ARE the lineup the task names, so its list is not repeated
        # here (the plain-text half, which has no rows to point at, keeps it).
        out.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="background:{FLAG_TINT};border:1px solid {FLAG_EDGE};'
            f'border-radius:8px;margin-top:10px;"><tr>'
            f'<td width="18" valign="top" style="padding:12px 10px 10px 12px;">{tick_box()}</td>'
            f'<td valign="top" style="padding:10px 12px 10px 0;">'
            f'{_item_cells(task, detail=False)}</td></tr></table>')
    for line in model.get("legend") or []:
        head = (f'<b style="color:{NAVY};">{esc(line["head"])}</b> '
                if line.get("head") else "")
        out.append(f'<p style="font-family:{FONT};font-size:12px;line-height:1.5;'
                   f'color:{INK2};margin:8px 0 0 0;">{head}{esc(line["text"])}</p>')
    return "".join(out)


# Fixed widths for the narrow columns, so the detail column gets whatever is
# left. Nothing but the detail cell carries words (launch audit F6).
_SLOT_W, _PROJ_W = 40, 40


def _slots_body(model: Mapping[str, Any]) -> str:
    """Card 05, the reasoning behind every slot: the slot, then one fact a
    line — name, game, availability, the call, his games, his usage, why —
    then the projection. No % here: the odds are card 01's."""
    rows = []
    for i, row in enumerate(model["rows"]):
        if i:
            rows.append(_rule(3))
        lines = [f'<b style="font-size:15px;color:{NAVY};">{esc(row["name"])}</b>']
        if row.get("game"):
            lines.append(f'<span style="color:{NAVY};">{esc(row["game"])}</span>')
        if row.get("flags"):
            lines.append(f'<b style="color:{BRICK};">{esc(" · ".join(row["flags"]))}</b>')
        if row.get("call"):
            lines.append(f'<b style="color:{NAVY};">{esc(row["call"])}</b>')
        lines += [esc(row[key]) for key in ("form", "usage", "reason") if row.get(key)]
        rows.append(
            f'<tr><td width="{_SLOT_W}" valign="top" style="font-family:{FONT};font-size:11px;'
            f'font-weight:bold;letter-spacing:1px;color:{SLATE};padding:12px 0 10px 0;">'
            f'{esc(row["slot"])}</td>'
            f'<td valign="top" style="{FACT}padding:9px 8px 10px 0;">{"<br>".join(lines)}</td>'
            f'<td width="{_PROJ_W}" align="right" valign="top" style="font-family:{FONT};'
            f'font-size:14px;font-weight:bold;color:{NAVY};padding:10px 0;">'
            f'{esc(row["proj"] or "—")}</td></tr>')
    out = [f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           f'border="0">{"".join(rows)}</table>']
    bench = _bench_rows(model.get("bench") or [], model.get("bench_head") or BENCH_HEAD)
    if bench:
        out.append(bench)
    for note in model.get("notes") or []:
        head = (f'<b style="color:{NAVY};">{esc(note["head"])}</b> '
                if note.get("head") else "")
        out.append(f'<p style="{FACT}margin:10px 0 0 0;">{head}{esc(note["text"])}</p>')
    return "".join(out)


def _bench_rows(bench: list[Mapping[str, Any]], head: str = BENCH_HEAD) -> str:
    """The rest of the roster under its own subhead: every rostered player is
    named. An OUT player takes the brick flag the lineup rows use, a benched
    starter-calibre player navy: a star the report chose to sit must not read
    as an injury."""
    if not bench:
        return ""
    rows = [f'<tr><td colspan="3" style="font-family:{FONT};font-size:11px;'
            f'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
            f'white-space:nowrap;color:{SLATE};border-top:2px solid {NAVY};'
            f'padding:14px 0 4px 0;">{esc(head)}</td></tr>']
    for i, entry in enumerate(bench):
        if i:
            rows.append(_rule(3))
        said = " · ".join(t for t in (
            esc(entry["form"]) if entry.get("form") else "",
            f'<b style="color:{BRICK};">{esc(entry["note"])}</b>' if entry.get("note") else "",
            (f'<b style="color:{NAVY};text-transform:uppercase;">{esc(entry["rank"])}</b>'
             if entry.get("rank") else "")) if t)
        lines = [f'<span style="font-size:14px;color:{NAVY};">{esc(entry["name"])}</span>']
        if entry.get("game"):
            lines.append(esc(entry["game"]))
        if said:
            lines.append(said)
        rows.append(
            f'<tr><td width="{_SLOT_W}" valign="top" style="font-family:{FONT};font-size:11px;'
            f'font-weight:bold;letter-spacing:1px;color:{SLATE};padding:10px 0 8px 0;">'
            f'{esc(entry["position"])}</td>'
            f'<td valign="top" style="{FACT}padding:8px 8px 8px 0;">{"<br>".join(lines)}</td>'
            f'<td width="{_PROJ_W}" align="right" valign="top" style="font-family:{FONT};'
            f'font-size:14px;color:{INK2};padding:8px 0;">'
            f'{esc(entry["proj"] or "—")}</td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="margin-top:6px;">{"".join(rows)}</table>')


def _bench(report: Mapping[str, Any]) -> str:
    """The rest of the roster, on its own (render.anatomy.slots)."""
    model = anatomy.slots({"lineup": [], "bench": report.get("bench") or [],
                           "meta": report.get("meta") or {}})
    return _bench_rows(model["bench"], model["bench_head"])


_BODIES = {"lineup": _lineup_body, "closest": _closest_body, "plan": _plan_body,
           "ifthen": _ifthen_body, "slots": _slots_body, "rising": _rising_body,
           "receipts": lambda model: _receipts_body(model["data"])}


def card_rows(report: Mapping[str, Any]) -> list[str]:
    """Any empty spot, then the numbered cards, as rows of the email — in the
    order every surface draws them (contract C1)."""
    return ([_alert(a) for a in anatomy.alerts(report)]
            + [_section_row(key, _card(1, model.get("title") or anatomy.TITLES[key],
                                       _BODIES[key](model)))
               for key, model in anatomy.cards(report)])


def _compose(report: Mapping[str, Any]) -> list[str]:
    """Sections in order, per product — the email twin of render.report.compose.

    One model (render.anatomy) and one order (contract C1): the masthead and
    its notices, any empty spot, then 01 Your Lineup, Decided · 02 The Week's
    Closest Call · 03 Your Game Plan · 04 If/Then for Gameday · 05 Slot by Slot
    · 06 Rising Roles · 07 The Receipts. The phone on the landing page is a
    copy of this email's first screens.
    """
    meta = report["meta"]
    if meta.get("solo"):
        return [_header(meta, team_name(report)), *card_rows(report)]
    return [
        _header(meta),
        _checklist(report["checklist"], meta),
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
        _footer(meta),
    ])
    sections = number_sections(sections)
    title = (f'Beat Your League — Week {esc(meta["week"])} '
             f'{"Report" if meta.get("solo") else "Rival Report"}')
    # Cards on paper (contract C4): no white page wrapper, a 12px gap between
    # cards, an 8px side gutter on a phone.
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{EMAIL_META}<title>{title}</title>\n</head>\n'
        f'<body style="margin:0;padding:0;background:{PAPER};">\n'
        f'{preheader_html(preheader)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:12px 8px 24px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:600px;width:100%;background:{PAPER};">'
        f'{sections}</table></td></tr></table>\n</body>\n</html>\n'
    )

