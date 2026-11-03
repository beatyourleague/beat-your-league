"""The rookie report: the published sample (`make rookies`) and the email.

Both come from one ``engine.rookies.build``. The class is in draft order, which
is the NFL's order, and every page and email says so: this is not a ranking.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from engine.rookies import GOOD_GAME, POSITIONS, build, load_players
from engine.scoring import preset
from render.email import BASE, SMALL
from render.live_sample import with_via_carry
from render.report import (CHECK_LABEL, FAVICON_LINK, NFLVERSE_LINE, PAGE_META, SITE_BAR_CSS, SITE_FOOTER_CSS,
                           SITE_ORIGIN, SOCIAL_IMAGE_TAGS, esc, font_preloads, sample_cta,
                           seat_stop_href, site_bar, site_footer, with_counter)
from render.sender import sender_line
from render.team_mail import _shell
from run.delivery import Message

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PAGE = "rookie-report.html"
EASTERN = ZoneInfo("America/New_York")
# A class this thin isn't in the file yet: keep last year's page up.
MIN_SKILL_ROOKIES = 40
POSITION_NAMES = {"QB": "Quarterbacks", "RB": "Running backs", "WR": "Wide receivers",
                  "TE": "Tight ends"}
ORDER_NOTE = ("Listed in draft order. That's where NFL teams took them, not a ranking of ours, "
              "and nothing here says how a rookie will do.")
HISTORY_NOTE = ("Rookies drafted since 2014, under full PPR. A \"good pace\" is {qb}+ points a "
                "game for a QB, {rb}+ for an RB or WR and {te}+ for a TE, over at least 6 games. "
                "This is what happened to past classes, not a forecast for this one.")
STOP = "Don't want these? Reply with the word stop."
ASK_HEAD = "Not a member?"
ASK_BODY = ("Get the next rookie report by email. One email after the NFL Draft, and nothing "
            "else unless you ask.")
ASK_BUTTON = "Send me the next one"
PITCH = "In season, one email decides your lineup every Wednesday."
FORM_SCRIPT = '<script src="/rookie-form.js" defer></script>\n'


def class_year(today: date) -> int:
    """The newest draft class: this year's from May, last year's before it."""
    return today.year if today.month >= 5 else today.year - 1


# The longest ordinary answer, for the launch check's width and sender audit.
ROOKIE_SAMPLE = {
    "year": 2026, "as_of": "Nov 1, 2026", "through_week": 8,
    "rookies": [{"name": "Fernando Mendoza", "position": "QB", "round": 1, "pick": 1, "team": "LV",
                 "drafted_by": "LV", "status": None, "college": "Indiana", "age": 22,
                 "height": "6'5\"", "weight": 225,
                 "room": {"left_share": 96, "lead": "Aidan O'Connell",
                          "arrived": ["Kirk Cousins"]},
                 "season": {"games": 7, "per_game": 14.2, "recent": [12.1, 16.4, 13.0]},
                 "base_rate": {"round": "Round 1", "drafted": 40, "rookie_hits": 13}}],
    "history": [],
    "near": [{"rookie": "Fernando Mendoza", "position": "QB", "team": "LV", "round": 1, "pick": 1,
              "left_share": 96, "yours": ["Aidan O'Connell"],
              "usage": [{"name": "Aidan O'Connell", "share": 4}]}]}
EMAIL_ROUNDS = 4


def _room(rookie: Mapping[str, Any], year: int) -> str:
    room = rookie.get("room")
    if not room:
        return f"No {rookie['position']} usage for this team in {year - 1}."
    noun = "pass attempts" if rookie["position"] == "QB" else "targets and carries"
    arrived = room.get("arrived") or []
    # A name can end in its own period ("Harold Fannin Jr."): one stop, never two.
    joined = f" Arrived: {', '.join(arrived).rstrip('.')}." if arrived else ""
    lead = f" Still there: {room['lead'].rstrip('.')}." if room.get("lead") else ""
    return (f"{room['left_share']}% of the team's {year - 1} {rookie['position']} {noun} "
            f"have left.{joined}{lead}")


def _where(rookie: Mapping[str, Any]) -> str:
    """His team now, and how he got there when it isn't the team that took him."""
    now = str(rookie.get("team") or "")
    was = rookie.get("drafted_by")
    moved = f", drafted by {was}" if was and was != now else ""
    return f"{now}{moved}, round {rookie['round']}"


def _season(rookie: Mapping[str, Any], year: int) -> str:
    """"2026: 7 games, 11.0 a game. Last 3: …", or who hasn't played yet. Empty
    before the class has played a game."""
    played = rookie.get("season")
    if not played:
        return f"{year}: no games yet."
    if played["games"] == 1:
        return f"{year}: 1 game, {played['per_game']:.1f} points."
    recent = ", ".join(f"{float(p):.1f}" for p in played["recent"])
    return (f"{year}: {played['games']} games, {played['per_game']:.1f} a game. "
            f"Last {len(played['recent'])}: {recent}.")


def _bio(rookie: Mapping[str, Any]) -> str:
    size = " ".join(x for x in (rookie.get("height"),
                                f"{rookie['weight']} lb" if rookie.get("weight") else None) if x)
    age = f"age {rookie['age']}" if rookie.get("age") else None
    return " · ".join(x for x in (rookie.get("college"), age, size, rookie.get("status")) if x)


def _base_rate(rookie: Mapping[str, Any]) -> str:
    """The history table's row, on the rookie it describes. A record of past
    classes, and it says so."""
    rate = rookie.get("base_rate")
    if not rate:
        return ""
    return (f"Past {rookie['position']}s taken in {rate['round']}: {rate['rookie_hits']} of "
            f"{rate['drafted']} reached a good pace as rookies.")


def _pace_note() -> str:
    return HISTORY_NOTE.format(qb=int(GOOD_GAME["QB"]), rb=int(GOOD_GAME["RB"]),
                               te=int(GOOD_GAME["TE"]))


def _beside(near: Mapping[str, Any], year: int, repeat: bool = False) -> str:
    """One rookie beside a subscriber's players, and where that leaves them.
    ``repeat``: the line above already gave this room's figures."""
    if repeat:
        return (f"{near['rookie']} ({near['position']}, {near['team']}, round {near['round']}, "
                f"pick {near['pick']}) joins the same room.")
    noun = "pass attempts" if near["position"] == "QB" else "targets and carries"
    usage = near.get("usage") or [{"name": name, "share": None} for name in near["yours"]]
    uses = [(f"{u['name']} had {u['share']}% of the team's {year - 1} {near['position']} {noun}."
             if u.get("share") is not None
             else f"{u['name']} had none of that usage here in {year - 1}.") for u in usage]
    left = (f" {near['left_share']}% of that room has left."
            if near.get("left_share") is not None else "")
    return (f"{near['rookie']} ({near['position']}, {near['team']}, round {near['round']}, "
            f"pick {near['pick']}) joins your {', '.join(near['yours'])}. {' '.join(uses)}{left}")


def _history_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{**row, "position_round": f"{row['position']}, {row['round']}"}
            for row in report["history"]]


def rookie_email(report: Mapping[str, Any], near: Sequence[Mapping[str, Any]], email: str,
                 key: str, page_url: str | None = None, join_url: str | None = None) -> Message:
    """One subscriber's copy: the rookies beside their players first, then the
    first four rounds. The whole class is on the page."""
    year = report["year"]
    subject = f"The {year} rookie report"
    played = bool(report.get("through_week"))
    blocks: list[tuple[str, list[str]]] = []
    if near:
        blocks.append(("Landed beside your players", [
            _beside(n, year, i > 0 and (n["team"], n["position"]) ==
                    (near[i - 1]["team"], near[i - 1]["position"]))
            for i, n in enumerate(near)]))
    for position in POSITIONS:
        rows = [r for r in report["rookies"]
                if r["position"] == position and (r["round"] or 9) <= EMAIL_ROUNDS]
        if rows:
            blocks.append((POSITION_NAMES[position], [
                f"{r['pick']}. {r['name']}, {_where(r)} ({_bio(r)}). {_room(r, year)}"
                + (f" {_base_rate(r)}" if _base_rate(r) else "")
                + (f" {_season(r, year)}" if played else "")
                for r in rows]))
    dated = f"Data as of {report['as_of']}." if report.get("as_of") else ""
    pace = _pace_note() if any(r.get("base_rate") for r in report["rookies"]) else ""
    body = (f'<p style="{BASE}margin:0 0 14px 0;">{esc(ORDER_NOTE)} {esc(dated)} {esc(pace)}</p>'
            + "".join(f'<p style="{BASE}margin:0 0 6px 0;"><b>{esc(head)}</b></p>'
                      + "".join(f'<p style="{BASE}margin:0 0 6px 0;">{esc(line)}</p>'
                                for line in lines)
                      + f'<p style="{SMALL}margin:0 0 8px 0;">&nbsp;</p>'
                      for head, lines in blocks))
    if page_url:
        body += (f'<p style="{BASE}margin:0 0 12px 0;">The whole class, and how past rookies '
                 f'scored by round: <a href="{esc(page_url)}">{esc(page_url)}</a></p>')
    if join_url:
        body += (f'<p style="{BASE}margin:0 0 12px 0;">{esc(PITCH)} '
                 f'<a href="{esc(join_url)}">{esc(CHECK_LABEL)}</a></p>')
    sender = sender_line()
    body += (f'<p style="{SMALL}margin:0;">{esc(STOP)}</p>'
             + (f'<p style="{SMALL}margin:8px 0 0 0;">{esc(sender)}</p>' if sender else ""))
    html = _shell(subject, "Where the new class landed, and who joined your players.", body)
    text: list[str] = [subject.upper(), "", " ".join(x for x in (ORDER_NOTE, dated, pace) if x), ""]
    for head, lines in blocks:
        text += [head.upper(), *lines, ""]
    if page_url:
        text += [f"The whole class, and how past rookies scored by round: {page_url}", ""]
    if join_url:
        text += [f"{PITCH} {CHECK_LABEL}: {join_url}", ""]
    text += [STOP, *([sender] if sender else []), NFLVERSE_LINE, ""]
    return Message(to=email, subject=subject, html=html, text="\n".join(text), key=key,
                   unsubscribe=seat_stop_href())


STYLE = """
  body{margin:0;background:#F6F4EE;color:#101E33;font-family:'Barlow','Barlow Fallback',Arial,sans-serif;font-size:16px;line-height:1.55;}
  .wrap{max-width:820px;margin:0 auto;padding:0 16px;}
  header{background:#101E33;color:#F6F4EE;padding:14px 0 30px;}
  header h1{font-family:'Barlow Condensed','Barlow Condensed Fallback','Arial Narrow',sans-serif;font-size:40px;font-weight:800;text-transform:uppercase;line-height:1.05;margin:22px 0 10px;}
  header p{color:#C9D4E2;margin:0;max-width:620px;}
  .skip{position:absolute;left:-999px;}.skip:focus{left:8px;top:8px;background:#fff;padding:6px;z-index:9;}
  main{padding:10px 0 34px;}
  h2{font-family:'Barlow Condensed','Barlow Condensed Fallback','Arial Narrow',sans-serif;font-size:26px;font-weight:800;text-transform:uppercase;margin:30px 0 8px;}
  .note{color:#33445C;font-size:15px;}
  .scroll{overflow-x:auto;}
  table{border-collapse:collapse;width:100%;font-size:14px;background:#fff;}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #D8D3C6;vertical-align:top;}
  th{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#5A6B80;}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;}
  td.n{white-space:nowrap;}
  .who{font-weight:700;}.sub{color:#5A6B80;font-size:13px;}
  .played{font-size:13px;font-weight:600;}
  .ask{margin:26px 0 0;}
  .btn{display:inline-block;padding:12px 20px;border-radius:6px;font-weight:700;text-decoration:none;}
  .btn.gold{background:#F0B62A;color:#101E33;}
  .ask-form{margin:18px 0 0;padding:14px;background:#fff;border:1px solid #D8D3C6;border-radius:12px;}
  .ask-form label{display:block;font-size:15px;margin-bottom:10px;}
  .ask-row{display:flex;flex-wrap:wrap;gap:8px;}
  .ask-row[hidden]{display:none;}
  .ask-row input{flex:1 1 200px;min-width:0;padding:11px 12px;border:1px solid #D8D3C6;border-radius:6px;font:inherit;}
  .ask-row button{border:0;cursor:pointer;font:inherit;}
  .ask-msg{margin:8px 0 0;font-size:14px;}
  .ask-msg:empty{display:none;}
  footer{background:#101E33;color:#C9D4E2;font-size:13px;padding:24px 0;}
  footer a{color:#C9D4E2;}
"""


def _ask_form(endpoint: str) -> str:
    """The box for anyone who isn't a member. Nothing renders until the form
    Worker exists: a box that saves nothing is worse than no box."""
    if not endpoint:
        return ""
    return (f'<form class="ask-form" id="rookie-ask" data-endpoint="{esc(endpoint)}" novalidate>'
            f'<label for="rookie-email"><b>{esc(ASK_HEAD)}</b> {esc(ASK_BODY)}</label>'
            f'<div class="ask-row"><input type="email" id="rookie-email" autocomplete="email" '
            f'placeholder="you@example.com"><button type="submit" class="btn gold">'
            f'{esc(ASK_BUTTON)}</button></div>'
            f'<p class="ask-msg" id="rookie-msg" role="status" aria-live="polite"></p></form>')


def join_endpoint(join: Path | None = None) -> str:
    """Where the site's forms post: the join page's FORM_ENDPOINT, empty until
    the Worker is deployed. One setting, so this page can't drift from it."""
    text = Path(join or SITE / "join" / "index.html").read_text(encoding="utf-8")
    found = re.search(r'^const FORM_ENDPOINT = "([^"]*)";', text, re.M)
    return found.group(1) if found else ""


def rookie_page(report: Mapping[str, Any], endpoint: str | None = None) -> str:
    year = report["year"]
    endpoint = join_endpoint() if endpoint is None else endpoint
    title = f"{year} NFL rookie report for dynasty and keeper leagues — Beat Your League"
    desc = (f"The {year} rookie class in draft order: where each player landed, how much of "
            f"his position's usage left that team, and how past rookies scored by round.")
    played = bool(report.get("through_week"))
    through = (f" {year} games are through Week {report['through_week']}, in full PPR."
               if played else "")
    history = "".join(
        f'<tr><td>{esc(r["position_round"])}</td><td class="n">{r["drafted"]}</td>'
        f'<td class="n">{r["rookie_hits"]}</td>'
        f'<td class="n">{r["within_three"]} of {r["mature"]}</td></tr>'
        for r in _history_rows(report))
    classes = ""
    for position in POSITIONS:
        rows = "".join(
            f'<tr><td class="n">{r["pick"]}</td><td><span class="who">{esc(r["name"])}</span> '
            f'<span class="sub">{esc(_where(r))}</span><br>'
            f'<span class="sub">{esc(_bio(r))}</span>'
            + (f'<br><span class="played">{esc(_season(r, year))}</span>' if played else "")
            + f'</td><td>{esc(_room(r, year))}'
            + (f'<br><span class="sub">{esc(_base_rate(r))}</span>' if _base_rate(r) else "")
            + '</td></tr>'
            for r in report["rookies"] if r["position"] == position)
        classes += (f'<h2>{esc(POSITION_NAMES[position])}</h2><div class="scroll"><table>'
                    f'<thead><tr><th class="n">Pick</th><th>Player</th><th>The room</th></tr>'
                    f'</thead><tbody>{rows}</tbody></table></div>')
    return with_counter(with_via_carry(f"""<!DOCTYPE html>
<!-- GENERATED by `make rookies` (render/rookies.py). Do not edit by hand. -->
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<link rel="canonical" href="{SITE_ORIGIN}/{PAGE}">
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Beat Your League">
{SOCIAL_IMAGE_TAGS}{FAVICON_LINK}
{PAGE_META}{font_preloads()}<link rel="stylesheet" href="fonts/fonts.css">
<style>{STYLE}{SITE_BAR_CSS}{SITE_FOOTER_CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header><div class="wrap">
  {site_bar("")}
  <h1>The {year} rookie report</h1>
  <p>Every drafted QB, RB, WR and TE: where he is now, how much of his position's usage left
  that team, who arrived, and how past rookies taken in the same round scored.</p>
</div></header>
<main id="main"><div class="wrap">
  <p class="note">{esc(ORDER_NOTE)} Data as of {esc(report.get("as_of") or "")}.{esc(through)}</p>
  <p class="note">Plan members can ask for it by email after each NFL Draft, with the rookies who
  landed beside their own players at the top.</p>
  {_ask_form(endpoint)}
  <h2>How past rookies scored</h2>
  <p class="note">{esc(_pace_note())}</p>
  <div class="scroll"><table><thead><tr><th>Position, round</th><th class="n">Drafted</th>
  <th class="n">Good pace, Year 1</th><th class="n">Within 3 years</th></tr></thead>
  <tbody>{history}</tbody></table></div>
  {classes}
  <div class="ask">{sample_cta()}</div>
</div></main>
<footer><div class="wrap">{site_footer("")}
  <b>Beat Your League</b> — analysis, not betting picks. {esc(NFLVERSE_LINE)}</div></footer>
{FORM_SCRIPT if endpoint else ""}</body>
</html>
"""))


def data_date(path: Path) -> str:
    """The day the players file was read, in Eastern time: "Nov 1, 2026"."""
    when = datetime.fromtimestamp(Path(path).stat().st_mtime, EASTERN)
    return f"{when:%b} {when.day}, {when.year}"


def load_report(cache: Path, year: int, *, live: bool = False) -> dict[str, Any]:
    """Everything the class needs, from the nflverse cache. Only the players
    file and the class's own season can move, so only those revalidate."""
    from ingest.nflverse import NflverseError, fetch, season_rows
    players_csv = fetch("players", "players.csv", cache, live=live)
    players = load_players(players_csv)
    seasons = {y: season_rows(cache, str(y), columns=None) for y in range(2014, year)}
    try:
        current = season_rows(cache, str(year), live=live, columns=None)
    except NflverseError:
        current = {}                 # no stats file until the class has played
    return build(players, seasons[year - 1], seasons, preset("ppr"), year,
                 as_of=data_date(players_csv), current=current,
                 playing=schedule_teams(cache, year, live=live))


def schedule_teams(cache: Path, year: int, *, live: bool = False) -> dict[int, set[str]] | None:
    """week -> the teams with a regular-season game that week, from games.csv,
    or None when the schedule can't be read (engine.rookies.build then counts
    every week with rows, as it did before SITE-5)."""
    import csv
    from ingest.nflverse import NflverseError, fetch
    try:
        path = fetch("schedules", "games.csv", cache, live=live)
    except NflverseError:
        return None
    weeks: dict[int, set[str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season") or "") != str(year):
                continue
            if (row.get("game_type") or "REG").upper() != "REG":
                continue
            try:
                week = int(row.get("week") or 0)
            except ValueError:
                continue
            for side in ("home_team", "away_team"):
                team = (row.get(side) or "").strip()
                if week and team:
                    weeks.setdefault(week, set()).add(team)
    return weeks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=None,
                        help="the draft class (default: the newest one out)")
    parser.add_argument("--cache", type=Path, default=ROOT / "data" / "raw" / "nflverse")
    parser.add_argument("--live", action="store_true",
                        help="the weekly run: revalidate, and keep the last page on a failure")
    args = parser.parse_args(argv)
    year = args.year or class_year(datetime.now(EASTERN).date())
    try:
        report = load_report(args.cache, year, live=args.live)
    except Exception as exc:  # noqa: BLE001 — this page must never stop the weekly run
        if not args.live:
            raise
        print(f"Rookie page: kept as it is, this week's data couldn't be read ({exc!r}).")
        return 0
    if len(report["rookies"]) < MIN_SKILL_ROOKIES:
        print(f"Rookie page: kept as it is, the {year} class isn't in the data yet.")
        return 0
    (SITE / PAGE).write_text(rookie_page(report), encoding="utf-8")
    print(f"wrote site/{PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
