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
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.preseason import NO_RECORD
from render.report import (EMAIL_META, BRAND_LINE, CANCEL_BODY, CANCEL_HEAD, FAVICON_LINK,
                           MARK_CSS, NFLVERSE_LINE, NO_BETTING_LINE, ONCE, PAGE_META,
                           SECTION_MARK, SELLING_ONE_TIME, TEMPLATE_PATH,
                           cancel_destination, esc,
                           extract_design, font_preloads, landmarks, mark_svg,
                           number_sections, sender_html, cancel_html,
                           cancel_lines, stop_route, unsubscribe_target)
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

# Before the season's record exists. Three forms, because a Week-1 buyer —
# next season's peak buying window — was told "Your season doesn't start for
# a couple of weeks" two days before kickoff and after it (COPY:F5): the run
# calls the season started only from Week 2, and nothing here knew the date.
# Each form is true whenever it is used; the undated one is for a schedule
# that cannot be read.
_OPENER_TAIL = ("we don't put a number on a guess. What it does instead is tell "
                "you the two things already decided: where the schedule leaves "
                "you short, and what your roster actually did last season under "
                "your scoring.")
OPENER = ("This season hasn't played enough yet to base a call on, so this "
          "report makes none — and " + _OPENER_TAIL)
OPENER_DATED = ("Week 1 kicks off {day}, so this report makes no calls — "
                "there's nothing played this season to base one on, and "
                + _OPENER_TAIL)
OPENER_UNDER_WAY = ("Week 1 is under way, but one week isn't a record, so this "
                    "report makes no calls — " + _OPENER_TAIL)
# Within this long of the first kickoff the report is no longer "pre-season":
# it is the roster report a Week-1 buyer keeps all season.
WEEK_ONE_WINDOW = timedelta(days=7)

WEEKLY_PROMISE = ("From your first Tuesday you get the weekly report: your lineup "
                  "set slot by slot, and the odds on every call we'll stand "
                  "behind — each one recorded before kickoff and graded in "
                  "public afterwards.")

BYE_HEAD = "Where the schedule leaves you short"
# Pre-season the check is positional (today's reserve list says nothing about
# a week months away), so the sentence says what was checked (EMAILS-127).
BYE_NONE = ("No week leaves a starting slot empty — every bye is covered by "
            "somebody else on your roster who plays that position.")
# Sent after the season has started, the report covers only the weeks still
# ahead (launch audit C7), and says so — including when every bye is behind.
BYE_NONE_AHEAD = ("No week from here on leaves a starting slot empty — every "
                  "bye still ahead on your roster is covered by somebody else "
                  "who can fill in.")
# The same, when the run could not read today's reserve list.
BYE_NONE_AHEAD_POSITION = ("No week from here on leaves a starting slot empty — "
                           "every bye still ahead is covered by somebody else on "
                           "your roster who plays that position.")
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
    if not meta.get("season_started"):
        return BYE_NONE
    return BYE_NONE_AHEAD if meta.get("roster_status") else BYE_NONE_AHEAD_POSITION


BYE_BASIS = ("Straight off the published NFL schedule, so these are fixed. A "
             "week is only listed when nobody else on your roster can fill the "
             "slot — a bye somebody else covers isn't your problem.")
# In-season, today's reserve list counts (EMAILS-119/126/128): the weekly
# report shows those players OUT, so this one may not count them as cover.
BYE_STATUS = ("Anyone on injured reserve, suspended or released today doesn't "
              "count as cover.")


def bye_basis(meta: Mapping[str, Any]) -> str:
    """BYE_BASIS, plus the reserve-list rule when it was applied."""
    return BYE_BASIS + (" " + BYE_STATUS if meta.get("roster_status") else "")


def out_note(entry: Mapping[str, Any]) -> str:
    """'out today: Name (on injured reserve)' for the players a bye or a
    thin spot would have leaned on, or ""."""
    out = entry.get("out") or []
    return f"out today: {', '.join(out)}" if out else ""

def bye_names(hit: Mapping[str, Any]) -> list[str]:
    """Who is on bye in a hole: only the players who play the emptied slot
    (``short``), as the weekly report's byes-ahead line names them — "Week 9:
    no one to start at K / on bye: Chris Boswell, Tyjae Spears" put a running
    back under a kicker hole (final review GROWTH-2)."""
    return list(hit.get("short") or hit["players"])


# Mid-season this report is the buyer's FIRST email whenever they pay between
# a week's kickoff and Tuesday (final review, business #2): it opens with the
# day the thing they bought arrives.
def next_report_line(meta: Mapping[str, Any]) -> str:
    """'Your Week 8 report lands Tuesday, Oct 27.' or "" (not certain)."""
    nxt = meta.get("next_report") or {}
    try:
        from datetime import date
        day = date.fromisoformat(str(nxt.get("lands_on")))
        week = int(nxt["week"])
    except (KeyError, TypeError, ValueError):
        return ""
    return f"Your Week {week} report lands {day:%A}, {day:%b} {day.day}."


CANT_PLAY_HEAD = "Can't play right now"
CANT_PLAY_BASIS = ("Today's NFL roster status: injured reserve, the PUP or "
                   "non-football injury list, suspended, exempt or released. "
                   "Your weekly report shows each of them out until that changes.")


def cant_play_line(entry: Mapping[str, Any]) -> str:
    """'De'Von Achane · RB · MIA · on injured reserve'."""
    bits = [entry["name"], entry.get("position") or "", entry.get("team") or "",
            entry.get("why") or ""]
    return " · ".join(b for b in bits if b)


# This season's record beside last season's (business #2): the figures the
# weekly report's row prints, so the two emails never disagree about a game.
SEASON_HEAD = "This season"
FORM_HEAD_INSEASON = "Your roster, under your rules"
SEASON_BASIS = ("This season counts every game he's played through Week {week} "
                "under your scoring: his average and his last three, the same "
                "figures your weekly report prints.")
NO_GAME_YET = "no games yet"


def season_cell(row: Mapping[str, Any]) -> tuple[str, str]:
    """(this season's average, his last three) as text, or (absence, "")."""
    so_far = row.get("season_so_far")
    if not so_far:
        return ("—" if row.get("position") == "DEF" else NO_GAME_YET), ""
    last = ", ".join(f"{v:.1f}" for v in so_far.get("last_three") or [])
    return (f'{so_far["per_game"]:.1f} a game over {so_far["games"]}',
            f"last {len(so_far.get('last_three') or [])}: {last}" if last else "")


def season_line(row: Mapping[str, Any], season: str) -> str:
    """'2026: 22.3 a game over 6 · last 3: 19.6, 16.2, 17.4' — this season's
    record under the name, named by its season as the weekly row names it.
    A line rather than a fourth column: four columns at 390px wrapped every
    figure onto its own line. Empty for a defense (not scored here)."""
    if row.get("position") == "DEF":
        return ""
    lead, recent = season_cell(row)
    return f"{season}: {lead}" + (f" · {recent}" if recent else "")


def _unbroken(line: str) -> str:
    """Each '·'-separated figure on its own line, a count never parted from
    its number — wrapped as one run it broke mid-figure at 390px ("2026: 22.3
    a game over" / "6 · last 3"). No nowrap: a whole figure held on one line
    widened the email past a 320px phone."""
    glue = lambda part: re.sub(r"\b(over|last) (\d)", "\\1\u00a0\\2", part)
    return "<br>".join(esc(glue(part)) for part in line.split(" · "))


def prior_label(meta: Mapping[str, Any]) -> str:
    """'2025' — the season last season's column is about, by name, beside a
    line named '2026'."""
    season = str(meta.get("season") or "")
    return str(meta.get("prior_season")
               or (str(int(season) - 1) if season.isdigit() else "last season"))


def form_head(meta: Mapping[str, Any]) -> str:
    return FORM_HEAD_INSEASON if meta.get("through_week") else FORM_HEAD


def form_basis(meta: Mapping[str, Any]) -> str:
    week = meta.get("through_week")
    return (SEASON_BASIS.format(week=week) + " " + FORM_BASIS) if week else FORM_BASIS


def way_out(meta: Mapping[str, Any]) -> "bool | str":
    """The roster report's way out, by render.report.stop_route's rule: a seat
    says stop, a one-time pass says stop (nothing renews), a subscription
    cancels on its billing page. The first email of every 2026 buyer who paid
    after a week's kickoff told a one-time pass holder to cancel a
    subscription they don't have, and its List-Unsubscribe was a billing page
    with nothing to cancel (final review COPY-1/GROWTH-1)."""
    return True if meta.get("seat") else stop_route(meta)


THIN_HEAD = "One deep"
THIN_BASIS = ("Positions where everyone who can play the slot is already "
              "starting. That's fine until it isn't: a bye, a knock or a bad "
              "matchup and there's nobody behind him.")

FORM_HEAD = "Last season, under your rules"
# "Your league's own settings" was one of three presets (EMAILS-131).
FORM_BASIS = ("Where each of your players finished last season at his position, "
              "and what he averaged — both scored under the scoring you picked, "
              "so the rank fits your league rather than a generic list. Per "
              "game he actually played, not per week, so time missed isn't "
              "punished twice. Anyone under eight games has no rank: too few "
              "to be a fact. This is a record of what happened, not a forecast "
              "for this year.")


# The same content is useful all season — a Week-6 buyer still wants to know
# their Week 11 leaves two slots empty — but a report headed "Pre-Season" in
# October is the small wrongness that makes a reader distrust the rest of it.
PRESEASON_TITLE = "Your Pre-Season Report"
INSEASON_TITLE = "Your Roster Report"


def first_kickoff(meta: Mapping[str, Any]) -> datetime | None:
    """The season's first kickoff, as ``preseason_message`` stamped it on the
    meta (an aware ISO time), or None."""
    raw = meta.get("first_kickoff")
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def week_one_near(meta: Mapping[str, Any], now: datetime | None = None) -> bool:
    """Week 1 is under way, or kicks off within WEEK_ONE_WINDOW."""
    kick = first_kickoff(meta)
    now = now or datetime.now(timezone.utc)
    return kick is not None and kick - now <= WEEK_ONE_WINDOW


def in_season(meta: Mapping[str, Any], now: datetime | None = None) -> bool:
    """Whether this report is the in-season roster report: the run says the
    season has started (Week 2 on), or Week 1's games are days away or
    being played."""
    return bool(meta.get("season_started")) or week_one_near(meta, now)


def opener(meta: Mapping[str, Any], now: datetime | None = None) -> str:
    """The sentence that sets expectations, true on the day it is sent."""
    if meta.get("season_started"):
        return IN_SEASON_OPENER
    kick = first_kickoff(meta)
    if kick is None:
        return OPENER
    if (now or datetime.now(timezone.utc)) >= kick:
        return OPENER_UNDER_WAY
    from zoneinfo import ZoneInfo
    local = kick.astimezone(ZoneInfo("America/New_York"))
    return OPENER_DATED.format(day=f"{local:%A}, {local:%b} {local.day}")


def file_title(report: Mapping[str, Any], now: datetime | None = None) -> str:
    return INSEASON_TITLE if in_season(report["meta"], now) else PRESEASON_TITLE


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
            who = ", ".join(bye_names(hit))
            note = out_note(hit)
            items.append(
                f'<tr class="trow"><td class="tslot">W{esc(hit["week"])}</td>'
                f'<td class="tside you"><span class="tname">'
                f'No one to start at {esc(slots)}</span>'
                f'<span class="tsub">on bye: {esc(who)}'
                + (f' · {esc(note)}' if note else "") + '</span></td></tr>')
        body = (f'<table class="tape"><colgroup><col style="width:14%">'
                f'<col style="width:86%"></colgroup>{"".join(items)}</table>')
    body += f'<div class="withheld">{esc(bye_basis(report["meta"]))}</div>'
    return _pre_section(BYE_HEAD, body)


def section_cant_play(report: Mapping[str, Any]) -> str:
    out = report.get("cant_play") or []
    if not out:
        return ""
    rows = "".join(
        f'<tr class="trow"><td class="tslot">{esc(e.get("position") or "")}</td>'
        f'<td class="tside you"><span class="tname">{esc(e["name"])}</span>'
        f'<span class="tsub">{esc(" · ".join(b for b in (e.get("team"), e.get("why")) if b))}'
        f'</span></td></tr>' for e in out)
    body = (f'<table class="tape"><colgroup><col style="width:14%">'
            f'<col style="width:86%"></colgroup>{rows}</table>'
            f'<div class="withheld">{esc(CANT_PLAY_BASIS)}</div>')
    return _pre_section(CANT_PLAY_HEAD, body)


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
            + (f' · {esc(out_note(spot))}' if out_note(spot) else "")
            + '</span></td></tr>')
    body = (f'<table class="tape"><colgroup><col style="width:14%">'
            f'<col style="width:86%"></colgroup>{"".join(rows)}</table>'
            f'<div class="withheld">{esc(THIN_BASIS)}</div>')
    return _pre_section(THIN_HEAD, body)


def section_form(report: Mapping[str, Any]) -> str:
    meta = report["meta"]
    current = bool(meta.get("through_week"))
    rows = []
    for row in report["roster"]:
        bye = f'bye W{row["bye"]}' if row.get("bye") else "no bye listed"
        team = row.get("team") or "—"
        now = season_line(row, meta["season"]) if current else ""
        rows.append(
            f'<tr class="trow"><td class="tslot">{esc(row["position"])}</td>'
            f'<td class="tside you"><span class="tname">{esc(row["name"])}</span>'
            f'<span class="tsub">{esc(team)} · {esc(bye)}</span>'
            + (f'<span class="tsub">{_unbroken(now)}</span>' if now else "")
            + f'</td><td class="tcall">{_record_cell(row)}</td></tr>')
    head = ('<tr class="thead"><td></td><td>Your roster'
            + (f' · {esc(SEASON_HEAD.lower())}' if current else "")
            + '</td><td style="text-align:right">Last season</td></tr>')
    cols = ('<col style="width:11%"><col style="width:59%">'
            '<col style="width:30%">')
    body = (f'<table class="tape"><colgroup>{cols}</colgroup>'
            f'{head}{"".join(rows)}</table>'
            f'<div class="withheld">{esc(form_basis(meta))}</div>')
    return _pre_section(form_head(meta), body)


def _pre_section(title: str, body: str) -> str:
    return (f'<section><div class="eyebrow"><span class="tag">{esc(title)}</span>'
            f'<span class="n">{SECTION_MARK}</span></div>{body}</section>')


def _header(meta: Mapping[str, Any]) -> str:
    scoring = scoring_name(meta)
    return (
        f'<header class="bug"><div class="brand">{mark_svg()}'
        f'<span>Beat Your League</span></div>'
        f'<h1>{esc(meta["season"])} · '
        f'{esc(INSEASON_TITLE if in_season(meta) else PRESEASON_TITLE)}'
        f'</h1>'
        f'<div class="sub">{esc(meta.get("label") or "Your Team")} · '
        f'{esc(scoring)} · {esc(len(meta.get("slots") or []))} starting spots'
        f' &nbsp;—&nbsp; built {esc(_stamp())}</div></header>'
        f'<section>'
        + (f'<p class="read" style="margin-bottom:10px;">'
           f'<b>{esc(next_report_line(meta))}</b></p>'
           if next_report_line(meta) else "")
        + f'<p class="read">{esc(opener(meta))}</p></section>'
    )


def _footer(meta: Mapping[str, Any]) -> str:
    route = way_out(meta)
    if route:
        # A League Pass seat has no billing to cancel (launch review C4), and
        # neither has a one-time pass (COPY-1/GROWTH-1).
        return (
            f'<footer><b>Beat Your League</b> — {esc(BRAND_LINE)}<br>'
            f'{esc(WEEKLY_PROMISE)}<br>'
            f'{esc(NO_BETTING_LINE)}<br>{esc(NFLVERSE_LINE)}<br>'
            f'{sender_html()}{cancel_html(seat=route)}</footer>'
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
        # Who can't play today leads in-season: it is about THIS week.
        section_cant_play(report),
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
             *([next_report_line(meta), ""] if next_report_line(meta) else []),
             opener(meta)]
    if report.get("cant_play"):
        lines += ["", CANT_PLAY_HEAD.upper(),
                  *[f"  {cant_play_line(e)}" for e in report["cant_play"]],
                  "", f"  {CANT_PLAY_BASIS}"]
    lines += ["", BYE_HEAD.upper()]
    if not report["collisions"]:
        lines.append(f"  {bye_none(meta)}")
    else:
        for hit in report["collisions"]:
            lines.append(f'  Week {hit["week"]}: no one to start at '
                         f'{", ".join(hit["slots"])}')
            lines.append(f'    on bye: {", ".join(bye_names(hit))}')
            if out_note(hit):
                lines.append(f"    {out_note(hit)}")
    lines += ["", f"  {bye_basis(meta)}"]

    if report["thin"]:
        lines += ["", THIN_HEAD.upper()]
        for spot in report["thin"]:
            lines.append(f'  {spot["slot"]:<5} {", ".join(spot["players"]) or "nobody"} '
                         f'({spot["have"]} on the roster, {spot["start"]} starting)'
                         + (f' · {out_note(spot)}' if out_note(spot) else ""))
        lines += ["", f"  {THIN_BASIS}"]

    lines += ["", form_head(meta).upper()]
    current = bool(meta.get("through_week"))
    for row in report["roster"]:
        record = row.get("record")
        if record:
            rank = rank_phrase(row)
            last = ((f"{rank} · " if rank else "")
                    + f'{record["per_game"]} a game over {record["games"]}')
        else:
            last = row.get("no_record_reason") or NO_RECORD
        bye = f'bye W{row["bye"]}' if row.get("bye") else "no bye listed"
        if current:
            # This season first, then last (business #2), one fact a line.
            now = season_line(row, meta["season"])
            lines += [f'  {row["position"]:<5} {row["name"]:<24} '
                      f'{(row.get("team") or "—"):<4} {bye}',
                      *([f"        {now}"] if now else []),
                      f"        {prior_label(meta)}: {last}"]
        else:
            lines.append(f'  {row["position"]:<5} {row["name"]:<24} '
                         f'{(row.get("team") or "—"):<4} {bye:<14} {last}')
    lines += ["", f"  {form_basis(meta)}", "", WEEKLY_PROMISE, "",
              NO_BETTING_LINE, NFLVERSE_LINE]
    route = way_out(report["meta"])
    if route:
        lines += ["", *cancel_lines(seat=route)]
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
    kick = _season_first_kickoff(str(season), args.cache)
    if kick is not None:
        report["meta"]["first_kickoff"] = kick.isoformat()
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
            f'<span style="{SMALL}">on bye: {esc(", ".join(bye_names(hit)))}'
            + (f' · {esc(out_note(hit))}' if out_note(hit) else "")
            + '</span></td></tr>'
            for hit in report["collisions"])
    else:
        bye_rows = (f'<tr><td style="{cell}">{esc(bye_none(meta))}</td></tr>')

    thin_rows = "".join(
        f'<tr><td style="{slot_cell}">{esc(spot["slot"])}</td>'
        f'<td style="{cell}"><b>{esc(", ".join(spot["players"]) or "nobody")}</b>'
        f'<br><span style="{SMALL}">{esc(spot["have"])} on the roster, '
        f'{esc(spot["start"])} starting'
        + (f' · {esc(out_note(spot))}' if out_note(spot) else "")
        + '</span></td></tr>'
        for spot in report["thin"])

    current = bool(meta.get("through_week"))
    cant_rows = "".join(
        f'<tr><td style="{slot_cell}">{esc(e.get("position") or "")}</td>'
        f'<td style="{cell}"><b>{esc(e["name"])}</b><br>'
        f'<span style="{SMALL}">'
        f'{esc(" · ".join(b for b in (e.get("team"), e.get("why")) if b))}'
        f'</span></td></tr>'
        for e in report.get("cant_play") or [])
    form_rows = ""
    if current:
        form_rows += (f'<tr><td style="{SMALL}padding:0 10px 6px 10px;"></td>'
                      f'<td style="{SMALL}padding:0 10px 6px 10px;">Your roster · '
                      f'{esc(SEASON_HEAD.lower())}</td>'
                      f'<td style="{SMALL}padding:0 10px 6px 10px;text-align:right;">'
                      f'Last season</td></tr>')
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
        now = season_line(row, meta["season"]) if current else ""
        form_rows += (
            f'<tr><td style="{slot_cell}">{esc(row["position"])}</td>'
            f'<td style="{cell}"><b>{esc(row["name"])}</b><br>'
            f'<span style="{SMALL}">{esc(row.get("team") or "—")} · {esc(bye)}'
            f'</span>'
            + (f'<br><span style="{SMALL}color:{NAVY};">{_unbroken(now)}</span>'
               if now else "")
            + f'</td>'
            f'<td style="{cell}text-align:right;">{last}</td>'
            f'</tr>')

    href, label = cancel_destination()
    cancel = (f' <a href="{esc(href)}" style="color:{NAVY};">{esc(label)}</a>.'
              if href else "")
    route = way_out(meta)
    exit_html = (cancel_html(seat=route) if route else
                 f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}{cancel}')
    lede = next_report_line(meta)
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
        + (f'<tr><td style="{BASE}font-size:17px;font-weight:bold;color:{NAVY};'
           f'padding:20px 26px 0 26px;">{esc(lede)}</td></tr>' if lede else "")
        + f'<tr><td style="{BASE}padding:20px 26px 0 26px;">'
        f'{esc(opener(meta))}'
        f'</td></tr>'
        + (block(CANT_PLAY_HEAD, cant_rows, CANT_PLAY_BASIS) if cant_rows else "")
        + block(BYE_HEAD, bye_rows, bye_basis(meta))
        + (block(THIN_HEAD, thin_rows, THIN_BASIS) if thin_rows else "")
        + block(form_head(meta), form_rows, form_basis(meta))
        + f'<tr><td style="background:{PAPER};padding:20px 26px 26px 26px;">'
        f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — {esc(BRAND_LINE)}'
        f'<br>{esc(WEEKLY_PROMISE)}<br>{esc(NO_BETTING_LINE)}<br>'
        f'{esc(NFLVERSE_LINE)}<br>{sender_html()}{exit_html}</p></td></tr>'
        f'</table></td></tr></table></body></html>'
    )


def _season_first_kickoff(season: str, cache_dir: Path | None = None) -> datetime | None:
    """Week 1's first kickoff off the cached schedule, or None when it cannot
    be read — then the undated opener, which is true either way, is used."""
    try:
        from run.solo import CACHE_DIR
        from run.trials import season_start
        return season_start(cache_dir or CACHE_DIR, season) if season else None
    except Exception:  # noqa: BLE001 — a missing schedule must not stop a send
        return None


def preseason_message(email: str, slug: str, report: Mapping[str, Any],
                      purchased_at: str = "", seat: "bool | str" = False,
                      one_time: "bool | None" = None):
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

    ``one_time``: a one-time pass (a ``pi_`` purchase — run/intake's
    _welcome rule), whose way out is a stop request: nothing renews, so there
    is nothing to cancel. ``seat=ONCE`` says the same (render.report's own
    vocabulary). Left unsaid, it is what the site sells this season
    (SELLING_ONE_TIME): every 2026 purchase is one payment, and the
    subscription footer told each of those buyers "Reports continue to the
    end of the period you've already paid for" (COPY-1/GROWTH-1).
    """
    from run.delivery import Message

    if seat == ONCE:
        seat, one_time = False, True
    if one_time is None:
        one_time = SELLING_ONE_TIME
    if one_time and not seat:
        report = {**report, "meta": {**report["meta"], "one_time": True}}
    if seat:
        # ``seat``: a League Pass seat's roster report, sent when the claim
        # lands outside the Tuesday-to-kickoff window (LP-I4). A seat pays
        # nothing, so its way out is the stop route, never a billing page.
        report = {**report, "meta": {**report["meta"], "seat": True}}
    if not report["meta"].get("season_started") and "first_kickoff" not in report["meta"]:
        # Read when the message is built — the moment it is sent — so the
        # opener and the title are true on the day it lands (COPY:F5).
        kick = _season_first_kickoff(str(report["meta"].get("season", "")))
        if kick is not None:
            report = {**report, "meta": {**report["meta"], "first_kickoff": kick.isoformat()}}
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
        # The mailto stop for a seat or a one-time pass (unsubscribe_target
        # takes ONCE as truthy), the billing page only for a subscription.
        unsubscribe=unsubscribe_target(way_out(meta)),
    )
