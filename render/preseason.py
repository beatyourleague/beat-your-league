"""Render the pre-season report — the same design system, in both dialects.

Two surfaces, like every other report here: the browser-grade HTML that goes to
disk as the archive, and the table-based, inline-styled email that actually
lands in an inbox. Every pinned sentence comes from ``render.report`` rather
than being retyped, because a copy per entry point is how two surfaces drift.

The register is deliberately not the weekly report's. This report makes no calls
and states no odds, so nothing in it should sound like one: it says what
happened last season and what the schedule already says about this one. The
verbs are past tense on purpose.
"""

from __future__ import annotations

from render.report import buyer_slots

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.preseason import NO_RECORD
from render.report import (EMAIL_META, BRAND_LINE, CANCEL_BODY, CANCEL_HEAD, FAVICON_LINK,
                           MARK_CSS, NFLVERSE_LINE, NO_BETTING_LINE, PAGE_META,
                           SECTION_MARK, TEMPLATE_PATH, cancel_destination, esc,
                           extract_design, font_preloads, landmarks, mark_svg,
                           number_sections, sender_html, cancel_html,
                           cancel_lines, unsubscribe_target)
from render.sender import sender_line

REPO_ROOT = Path(__file__).resolve().parent.parent

# The one sentence that sets expectations for everything after it. It has to do
# real work: a buyer who paid for weekly start/sit calls is opening a report that
# deliberately contains none, and if that reads as "the product is broken" the
# refund it prevents becomes the refund it causes.
IN_SEASON_OPENER = (
    "This is the standing report on your roster: what the schedule already says "
    "about the weeks ahead, and what your players did last season under your "
    "scoring. No calls in here — those come in your weekly report, where they "
    "can be graded.")

OPENER = ("Your season doesn't start for a couple of weeks, so this report makes "
          "no calls — there's nothing played to base one on, and we don't put a "
          "number on a guess. What it does instead is tell you the two things "
          "already decided: where the schedule leaves you short, and what your "
          "roster actually did last season under your scoring.")

WEEKLY_PROMISE = ("From your first Tuesday you get the weekly report: your lineup "
                  "set slot by slot, and the odds on every call we'll stand "
                  "behind — each one recorded before kickoff and graded in "
                  "public afterwards.")

BYE_HEAD = "Where the schedule leaves you short"
BYE_NONE = ("No week leaves a starting slot empty — every bye on your roster is "
            "covered by somebody else who can fill in.")
# Sent after the season has started, the report covers only the weeks still
# ahead (launch audit C7), and says so — including when every bye is behind.
BYE_NONE_AHEAD = ("No week from here on leaves a starting slot empty — every "
                  "bye still ahead on your roster is covered by somebody else "
                  "who can fill in.")
BYE_ALL_BEHIND = ("Every bye week on your roster is behind you, so the schedule "
                  "leaves no week short from here on.")


def _byes_behind(meta: Mapping[str, Any]) -> bool:
    """Season under way and no bye on the roster still to come."""
    return bool(meta.get("season_started") and meta.get("from_week")
                and meta.get("byes_ahead") is False)


def bye_none(meta: Mapping[str, Any]) -> str:
    """What the bye section says when no week ahead leaves a slot empty."""
    if _byes_behind(meta):
        return BYE_ALL_BEHIND
    return BYE_NONE_AHEAD if meta.get("season_started") else BYE_NONE


BYE_BASIS = ("Straight off the published NFL schedule, so these are fixed. A "
             "week is only listed when nothing on your roster can fill the "
             "slot — a bye somebody else covers isn't your problem.")

THIN_HEAD = "One deep"
THIN_BASIS = ("Positions where everyone who can play the slot is already "
              "starting. That's fine until it isn't: a bye, a knock or a bad "
              "matchup and there's nobody behind him.")

FORM_HEAD = "Last season, under your rules"
FORM_BASIS = ("Where each of your players finished last season at his position, "
              "and what he averaged — both scored under your league's own "
              "settings, so the rank is yours rather than a generic one. Per "
              "game he actually played, not per week, so time missed isn't "
              "punished twice. Anyone under eight games has no rank: too few "
              "to be a fact. This is a record of what happened, not a forecast "
              "for this year.")


# The same content is useful all season — a Week-6 buyer still wants to know
# their Week 11 leaves two slots empty — but a report headed "Pre-Season" in
# October is the small wrongness that makes a reader distrust the rest of it.
PRESEASON_TITLE = "Your Pre-Season Report"
INSEASON_TITLE = "Your Roster Report"


def file_title(report: Mapping[str, Any]) -> str:
    return (INSEASON_TITLE if report["meta"].get("season_started")
            else PRESEASON_TITLE)


# The scoring preset in the buyer's words. The plain-text half printed the raw
# code ("Your Team · ppr") while the HTML said "Full PPR" (panel review BE-D5);
# one mapping now serves all three surfaces.
SCORING_NAMES = {"ppr": "Full PPR", "half_ppr": "Half PPR", "standard": "Standard"}


def scoring_name(meta: Mapping[str, Any]) -> str:
    code = meta.get("scoring")
    return SCORING_NAMES.get(code, code or "")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%a %d %b %Y")


def rank_phrase(row: Mapping[str, Any]) -> str:
    """"WR3 of 159" — the context that makes the per-game number mean anything.

    A reader cannot tell whether 18.7 a game is good. WR3 they can tell
    instantly, because it is the vocabulary they already think in.
    """
    rank = row.get("rank")
    if not rank:
        return ""
    position, place, pool = rank
    return f"{position}{place} of {pool}"


def _record_cell(row: Mapping[str, Any]) -> str:
    record = row.get("record")
    if not record:
        # RULE P1, and the two absences are different facts.
        return f'<span class="tsub">{esc(row.get("no_record_reason") or NO_RECORD)}</span>'
    rank = rank_phrase(row)
    lead = f'<b>{esc(rank)}</b> · ' if rank else ""
    return (f'{lead}<span class="tsub">{record["per_game"]} a game over '
            f'{record["games"]}</span>')


def section_byes(report: Mapping[str, Any]) -> str:
    collisions = report["collisions"]
    if not collisions:
        body = f'<p class="withheldline">{esc(bye_none(report["meta"]))}</p>'
    else:
        items = []
        for hit in collisions:
            slots = ", ".join(hit["slots"])
            who = ", ".join(hit["players"])
            items.append(
                f'<tr class="trow"><td class="tslot">W{esc(hit["week"])}</td>'
                f'<td class="tside you"><span class="tname">'
                f'No one to start at {esc(slots)}</span>'
                f'<span class="tsub">on bye: {esc(who)}</span></td></tr>')
        body = (f'<table class="tape"><colgroup><col style="width:14%">'
                f'<col style="width:86%"></colgroup>{"".join(items)}</table>')
    body += f'<div class="withheld">{esc(BYE_BASIS)}</div>'
    return _pre_section(BYE_HEAD, body)


def section_thin(report: Mapping[str, Any]) -> str:
    thin = report["thin"]
    if not thin:
        return ""
    rows = []
    for spot in thin:
        rows.append(
            f'<tr class="trow"><td class="tslot">{esc(spot["slot"])}</td>'
            f'<td class="tside you"><span class="tname">'
            f'{esc(", ".join(spot["players"]) or "nobody")}</span>'
            f'<span class="tsub">'
            f'{esc(spot["have"])} on the roster, {esc(spot["start"])} starting'
            f'</span></td></tr>')
    body = (f'<table class="tape"><colgroup><col style="width:14%">'
            f'<col style="width:86%"></colgroup>{"".join(rows)}</table>'
            f'<div class="withheld">{esc(THIN_BASIS)}</div>')
    return _pre_section(THIN_HEAD, body)


def section_form(report: Mapping[str, Any]) -> str:
    rows = []
    for row in report["roster"]:
        bye = f'bye W{row["bye"]}' if row.get("bye") else "no bye listed"
        team = row.get("team") or "—"
        rows.append(
            f'<tr class="trow"><td class="tslot">{esc(row["position"])}</td>'
            f'<td class="tside you"><span class="tname">{esc(row["name"])}</span>'
            f'<span class="tsub">{esc(team)} · {esc(bye)}</span></td>'
            f'<td class="tcall">{_record_cell(row)}</td></tr>')
    head = ('<tr class="thead"><td></td><td>Your roster</td>'
            '<td style="text-align:right">Last season</td></tr>')
    body = (f'<table class="tape"><colgroup><col style="width:11%">'
            f'<col style="width:59%"><col style="width:30%"></colgroup>'
            f'{head}{"".join(rows)}</table>'
            f'<div class="withheld">{esc(FORM_BASIS)}</div>')
    return _pre_section(FORM_HEAD, body)


def _pre_section(title: str, body: str) -> str:
    return (f'<section><div class="eyebrow"><span class="tag">{esc(title)}</span>'
            f'<span class="n">{SECTION_MARK}</span></div>{body}</section>')


def _header(meta: Mapping[str, Any]) -> str:
    scoring = scoring_name(meta)
    return (
        f'<header class="bug"><div class="brand">{mark_svg()}'
        f'<span>Beat Your League</span></div>'
        f'<h1>{esc(meta["season"])} · '
        f'{esc(INSEASON_TITLE if meta.get("season_started") else PRESEASON_TITLE)}'
        f'</h1>'
        f'<div class="sub">{esc(meta.get("label") or "Your Team")} · '
        f'{esc(scoring)} · {esc(len(meta.get("slots") or []))} starting spots'
        f' &nbsp;—&nbsp; built {esc(_stamp())}</div></header>'
        f'<section><p class="read">'
        f'{esc(IN_SEASON_OPENER if meta.get("season_started") else OPENER)}'
        f'</p></section>'
    )


def _footer(meta: Mapping[str, Any]) -> str:
    if meta.get("seat"):
        # A League Pass seat has no billing to cancel (launch review C4).
        return (
            f'<footer><b>Beat Your League</b> — {esc(BRAND_LINE)}<br>'
            f'{esc(WEEKLY_PROMISE)}<br>'
            f'{esc(NO_BETTING_LINE)}<br>{esc(NFLVERSE_LINE)}<br>'
            f'{sender_html()}{cancel_html(seat=True)}</footer>'
        )
    href, label = cancel_destination()
    cancel = (f' <a href="{esc(href)}">{esc(label)}</a>.' if href else "")
    return (
        f'<footer><b>Beat Your League</b> — {esc(BRAND_LINE)}<br>'
        f'{esc(WEEKLY_PROMISE)}<br>'
        f'{esc(NO_BETTING_LINE)}<br>{esc(NFLVERSE_LINE)}<br>'
        f'{sender_html()}'
        f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}{cancel}</footer>'
    )


def compose(report: Mapping[str, Any]) -> list[str]:
    """Byes first: it is the only thing here a manager can still act on."""
    return [
        _header(report["meta"]),
        section_byes(report),
        section_thin(report),
        section_form(report),
        _footer(report["meta"]),
    ]


@buyer_slots
def render(report: Mapping[str, Any], template_html: str) -> str:
    style, links = extract_design(template_html)
    style += MARK_CSS
    body = number_sections("".join(compose(report)))
    title = (f'Beat Your League — {report["meta"]["season"]} '
             f'{file_title(report)}')
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{PAGE_META}<title>{esc(title)}</title>\n{FAVICON_LINK}\n'
        f'{font_preloads()}{links}\n'
        f'<style>{style}</style>\n</head>\n<body>\n'
        f'<div class="report">\n{landmarks(body)}\n</div>\n</body>\n</html>\n'
    )


# --------------------------------------------------------------------- #
# the plain-text half — what a text-only client and every screen reader get
# --------------------------------------------------------------------- #

@buyer_slots
def text_summary(report: Mapping[str, Any]) -> str:
    meta = report["meta"]
    lines = [f'{meta["season"]} · {file_title(report).upper()}',
             f'{meta.get("label") or "Your Team"} · {scoring_name(meta)}',
             "",
             (IN_SEASON_OPENER if meta.get("season_started") else OPENER),
             "", BYE_HEAD.upper()]
    if not report["collisions"]:
        lines.append(f"  {bye_none(meta)}")
    else:
        for hit in report["collisions"]:
            lines.append(f'  Week {hit["week"]}: no one to start at '
                         f'{", ".join(hit["slots"])}')
            lines.append(f'    on bye: {", ".join(hit["players"])}')
    lines += ["", f"  {BYE_BASIS}"]

    if report["thin"]:
        lines += ["", THIN_HEAD.upper()]
        for spot in report["thin"]:
            lines.append(f'  {spot["slot"]:<5} {", ".join(spot["players"]) or "nobody"} '
                         f'({spot["have"]} on the roster, {spot["start"]} starting)')
        lines += ["", f"  {THIN_BASIS}"]

    lines += ["", FORM_HEAD.upper()]
    for row in report["roster"]:
        record = row.get("record")
        if record:
            rank = rank_phrase(row)
            last = ((f"{rank} · " if rank else "")
                    + f'{record["per_game"]} a game over {record["games"]}')
        else:
            last = row.get("no_record_reason") or NO_RECORD
        bye = f'bye W{row["bye"]}' if row.get("bye") else "no bye listed"
        lines.append(f'  {row["position"]:<5} {row["name"]:<24} '
                     f'{(row.get("team") or "—"):<4} {bye:<14} {last}')
    lines += ["", f"  {FORM_BASIS}", "", WEEKLY_PROMISE, "",
              NO_BETTING_LINE, NFLVERSE_LINE]
    if report["meta"].get("seat"):
        lines += ["", *cancel_lines(seat=True)]
    else:
        href, label = cancel_destination()
        if href:
            lines += ["", f"CANCEL: {label} — {href}"]
        lines += ["", f"{CANCEL_HEAD.upper()} {CANCEL_BODY}"]
    # Who sent it (CAN-SPAM, CASL; launch audit L3, GATE-9).
    if sender_line():
        lines += ["", sender_line()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Build one pre-season report from a roster, for eyeballing it locally."""
    from engine.nflverse_backtest import TEMPLATE_T1
    from engine.preseason import build_preseason_report
    from engine.subscriber import RosterSpec
    from run.solo import CACHE_DIR, current_season, load_week_data

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", required=True,
                        help="comma-separated player ids")
    parser.add_argument("--scoring", default="ppr")
    parser.add_argument("--season", default=None)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--print", action="store_true", dest="show")
    args = parser.parse_args(argv)

    season = args.season or current_season(args.cache)
    data = load_week_data(args.cache, str(int(season) - 1), 10, live=False)
    spec = RosterSpec(player_ids=tuple(x.strip() for x in args.roster.split(",")),
                      slots=TEMPLATE_T1, scoring=args.scoring, label="Your Team")
    report = build_preseason_report(spec, data.directory, data.prior, str(season),
                                    args.cache, prior_season=str(int(season) - 1))
    if args.show:
        print(text_summary(report))
    out = args.out or (REPO_ROOT / "reports" / f"preseason-{season}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(report, TEMPLATE_PATH.read_text(encoding="utf-8")),
                   encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --------------------------------------------------------------------- #
# delivery
# --------------------------------------------------------------------- #

def email_html(report: Mapping[str, Any]) -> str:
    """The email-safe rendering — tables and inline styles, nothing else.

    NOT the browser render above. Outlook lays email out with Word's engine and
    Gmail strips <style> on forward, so mailing the browser-grade file ships
    soup; run/batch.py learned that the hard way and a test pins it for the
    weekly report. Same palette, same words, a dialect every client renders.
    """
    from render.email import (BASE, CARD, DISPLAY, FLAG, LINE, NAVY, PAPER,
                              SLATE, SMALL, TURF)

    meta = report["meta"]
    title = file_title(report)
    cell = f'{BASE}padding:8px 10px;border-bottom:1px solid {LINE};'
    slot_cell = (f'{SMALL}padding:8px 10px;border-bottom:1px solid {LINE};'
                 f'font-weight:bold;white-space:nowrap;')

    def block(heading: str, rows_html: str, basis: str) -> str:
        return (
            f'<tr><td style="padding:22px 26px 0 26px;">'
            f'<div style="font-family:{DISPLAY};font-size:13px;font-weight:bold;'
            f'letter-spacing:2.5px;text-transform:uppercase;color:{NAVY};'
            f'border-bottom:2px solid {NAVY};padding-bottom:6px;">{esc(heading)}'
            f'</div></td></tr>'
            f'<tr><td style="padding:10px 26px 0 26px;">'
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{rows_html}</table>'
            f'<div style="{BASE}font-size:13px;background:{PAPER};'
            f'border-left:3px solid {LINE};padding:10px 12px;margin:10px 0 0 0;">'
            f'{esc(basis)}</div></td></tr>')

    if report["collisions"]:
        bye_rows = "".join(
            f'<tr><td style="{slot_cell}">W{esc(hit["week"])}</td>'
            f'<td style="{cell}"><b>No one to start at '
            f'{esc(", ".join(hit["slots"]))}</b><br>'
            f'<span style="{SMALL}">on bye: {esc(", ".join(hit["players"]))}'
            f'</span></td></tr>'
            for hit in report["collisions"])
    else:
        bye_rows = (f'<tr><td style="{cell}">{esc(bye_none(meta))}</td></tr>')

    thin_rows = "".join(
        f'<tr><td style="{slot_cell}">{esc(spot["slot"])}</td>'
        f'<td style="{cell}"><b>{esc(", ".join(spot["players"]) or "nobody")}</b>'
        f'<br><span style="{SMALL}">{esc(spot["have"])} on the roster, '
        f'{esc(spot["start"])} starting</span></td></tr>'
        for spot in report["thin"])

    form_rows = ""
    for row in report["roster"]:
        record = row.get("record")
        rank = rank_phrase(row)
        # The rank over its rate, each unbroken but the cell free to wrap
        # between them: as one nowrap line ("QB2 of 39 23.7 a game over 16")
        # it pushed the email 9px past a 390px phone and squeezed every name
        # onto three lines (Oct 2026, GATE-2).
        last = ((f'<b style="color:{TURF};white-space:nowrap;">{esc(rank)}</b><br>'
                 if rank else "")
                + f'<span style="{SMALL}white-space:nowrap;">{record["per_game"]} '
                f'a game over {record["games"]}</span>'
                if record else
                f'<span style="{SMALL}">'
                f'{esc(row.get("no_record_reason") or NO_RECORD)}</span>')
        bye = f'bye W{row["bye"]}' if row.get("bye") else "no bye listed"
        form_rows += (
            f'<tr><td style="{slot_cell}">{esc(row["position"])}</td>'
            f'<td style="{cell}"><b>{esc(row["name"])}</b><br>'
            f'<span style="{SMALL}">{esc(row.get("team") or "—")} · {esc(bye)}'
            f'</span></td>'
            f'<td style="{cell}text-align:right;">{last}</td>'
            f'</tr>')

    href, label = cancel_destination()
    cancel = (f' <a href="{esc(href)}" style="color:{NAVY};">{esc(label)}</a>.'
              if href else "")
    way_out = (cancel_html(seat=True) if meta.get("seat") else
               f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}{cancel}')
    scoring = scoring_name(meta)
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'{EMAIL_META}<title>{esc(title)}</title></head>'
        f'<body style="margin:0;padding:0;background:{PAPER};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center">'
        f'<table role="presentation" width="640" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:640px;width:100%;background:{CARD};">'
        f'<tr><td style="background:{NAVY};padding:24px 26px;'
        f'border-left:4px solid {FLAG};">'
        f'<div style="font-family:{DISPLAY};font-size:12px;font-weight:bold;'
        f'letter-spacing:4px;text-transform:uppercase;color:{FLAG};">'
        f'Beat Your League</div>'
        f'<div style="font-family:{DISPLAY};font-size:30px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{CARD};'
        f'padding:6px 0 8px 0;">{esc(meta["season"])} · {esc(title)}</div>'
        f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        f'color:#B9C2D0;">{esc(meta.get("label") or "Your Team")} · {esc(scoring)}'
        f'</div></td></tr>'
        f'<tr><td style="{BASE}padding:20px 26px 0 26px;">'
        f'{esc(IN_SEASON_OPENER if meta.get("season_started") else OPENER)}'
        f'</td></tr>'
        + block(BYE_HEAD, bye_rows, BYE_BASIS)
        + (block(THIN_HEAD, thin_rows, THIN_BASIS) if thin_rows else "")
        + block(FORM_HEAD, form_rows, FORM_BASIS)
        + f'<tr><td style="background:{PAPER};padding:20px 26px 26px 26px;">'
        f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — {esc(BRAND_LINE)}'
        f'<br>{esc(WEEKLY_PROMISE)}<br>{esc(NO_BETTING_LINE)}<br>'
        f'{esc(NFLVERSE_LINE)}<br>{sender_html()}{way_out}</p></td></tr>'
        f'</table></td></tr></table></body></html>'
    )


def preseason_message(email: str, slug: str, report: Mapping[str, Any],
                      purchased_at: str = "", seat: bool = False):
    """The pre-season report as a Message, keyed so it can only be sent once.

    Keyed on the PURCHASE, exactly like the welcome and for the same reason: a
    season-keyed idempotency key moves every August, and the sender's recipient
    set is a projection of an append-only signup log that is never pruned — so
    a season roll would mail this to everybody the product ever had, cancelled
    subscribers included. A genuine re-purchase is a new key and does get a new
    report, which is right: new byes, new prior season.

    Once the season has started the subject counts only the weeks still ahead,
    the same ones the body lists (launch audit C7: a Week-6 buyer's subject
    counted Week 5).
    """
    from run.delivery import Message

    if seat:
        # ``seat``: a League Pass seat's roster report, sent when the claim
        # lands outside the Tuesday-to-kickoff window (LP-I4). A seat pays
        # nothing, so its way out is the stop route, never a billing page.
        report = {**report, "meta": {**report["meta"], "seat": True}}
    meta = report["meta"]
    hits = len(report["collisions"])
    ahead = " ahead" if meta.get("season_started") else ""
    subject = (f'Your {meta["season"]} roster: '
               + ("every bye week is behind you" if _byes_behind(meta) else
                  f"every bye{ahead} is covered" if not hits else
                  f"one week{ahead} leaves a slot empty" if hits == 1 else
                  f"{hits} weeks{ahead} leave a slot empty"))
    return Message(
        to=email,
        subject=subject,
        html=email_html(report),
        text=text_summary(report),
        key=f"preseason-{purchased_at or meta['season']}-{slug}",
        unsubscribe=unsubscribe_target(seat),
    )
