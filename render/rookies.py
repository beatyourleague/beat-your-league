"""The rookie report: the published sample (`make rookies`) and the email.

Both come from one ``engine.rookies.build``. The class is in draft order, which
is the NFL's order, and every page and email says so: this is not a ranking.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.rookies import POSITIONS, build, load_players
from engine.scoring import preset
from render.email import BASE, SMALL
from render.report import (FAVICON_LINK, NFLVERSE_LINE, PAGE_META, SITE_BAR_CSS, SITE_FOOTER_CSS,
                           SITE_ORIGIN, SOCIAL_IMAGE_TAGS, esc, font_preloads, sample_cta,
                           seat_stop_href, site_bar, site_footer, with_counter)
from render.sender import sender_line
from render.team_mail import _shell
from run.delivery import Message

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PAGE = "rookie-report.html"
POSITION_NAMES = {"QB": "Quarterbacks", "RB": "Running backs", "WR": "Wide receivers",
                  "TE": "Tight ends"}
ORDER_NOTE = ("Listed in draft order. That's where NFL teams took them, not a ranking of ours, "
              "and nothing here says how a rookie will do.")
HISTORY_NOTE = ("Rookies drafted since 2014, under full PPR. A \"good pace\" is {qb}+ points a "
                "game for a QB, {rb}+ for an RB or WR and {te}+ for a TE, over at least 6 games. "
                "This is what happened to past classes, not a forecast for this one.")
STOP = "Don't want these? Reply with the word stop."
# The longest ordinary answer, for the launch check's width and sender audit.
ROOKIE_SAMPLE = {
    "year": 2026,
    "rookies": [{"name": "Fernando Mendoza", "position": "QB", "round": 1, "pick": 1, "team": "LV",
                 "college": "Indiana", "age": 22, "height": "6'5\"", "weight": 225,
                 "room": {"left_share": 96, "lead": "Aidan O'Connell"}}],
    "history": [],
    "near": [{"rookie": "Fernando Mendoza", "position": "QB", "team": "LV", "round": 1, "pick": 1,
              "yours": ["Aidan O'Connell"]}]}
EMAIL_ROUNDS = 4


def _room(rookie: Mapping[str, Any], year: int) -> str:
    room = rookie.get("room")
    if not room:
        return f"No {rookie['position']} usage for this team in {year - 1}."
    noun = "pass attempts" if rookie["position"] == "QB" else "targets and carries"
    lead = f" Still there: {room['lead']}." if room.get("lead") else ""
    return f"{room['left_share']}% of the team's {year - 1} {rookie['position']} {noun} have left.{lead}"


def _bio(rookie: Mapping[str, Any]) -> str:
    size = " ".join(x for x in (rookie.get("height"),
                                f"{rookie['weight']} lb" if rookie.get("weight") else None) if x)
    age = f"age {rookie['age']}" if rookie.get("age") else None
    return " · ".join(x for x in (rookie.get("college"), age, size) if x)


def _history_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{**row, "position_round": f"{row['position']}, {row['round']}"}
            for row in report["history"]]


def rookie_email(report: Mapping[str, Any], near: Sequence[Mapping[str, Any]], email: str,
                 key: str, page_url: str | None = None) -> Message:
    """One subscriber's copy: the rookies beside their players first, then the
    first four rounds. The whole class is on the page."""
    year = report["year"]
    subject = f"The {year} rookie report"
    blocks: list[tuple[str, list[str]]] = []
    if near:
        blocks.append(("Landed beside your players", [
            f"{n['rookie']} ({n['position']}, {n['team']}, round {n['round']}, pick {n['pick']}) "
            f"joins your {', '.join(n['yours'])}." for n in near]))
    for position in POSITIONS:
        rows = [r for r in report["rookies"]
                if r["position"] == position and (r["round"] or 9) <= EMAIL_ROUNDS]
        if rows:
            blocks.append((POSITION_NAMES[position], [
                f"{r['pick']}. {r['name']}, {r['team']} ({_bio(r)}). {_room(r, year)}"
                for r in rows]))
    body = (f'<p style="{BASE}margin:0 0 14px 0;">{esc(ORDER_NOTE)}</p>'
            + "".join(f'<p style="{BASE}margin:0 0 6px 0;"><b>{esc(head)}</b></p>'
                      + "".join(f'<p style="{BASE}margin:0 0 6px 0;">{esc(line)}</p>'
                                for line in lines)
                      + f'<p style="{SMALL}margin:0 0 8px 0;">&nbsp;</p>'
                      for head, lines in blocks))
    if page_url:
        body += (f'<p style="{BASE}margin:0 0 12px 0;">The whole class, and how past rookies '
                 f'scored by round: <a href="{esc(page_url)}">{esc(page_url)}</a></p>')
    sender = sender_line()
    body += (f'<p style="{SMALL}margin:0;">{esc(STOP)}</p>'
             + (f'<p style="{SMALL}margin:8px 0 0 0;">{esc(sender)}</p>' if sender else ""))
    html = _shell(subject, "Where the new class landed, and who joined your players.", body)
    text: list[str] = [subject.upper(), "", ORDER_NOTE, ""]
    for head, lines in blocks:
        text += [head.upper(), *lines, ""]
    if page_url:
        text += [f"The whole class, and how past rookies scored by round: {page_url}", ""]
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
  .ask{margin:26px 0 0;}
  .btn{display:inline-block;padding:12px 20px;border-radius:6px;font-weight:700;text-decoration:none;}
  .btn.gold{background:#F0B62A;color:#101E33;}
  footer{background:#101E33;color:#C9D4E2;font-size:13px;padding:24px 0;}
  footer a{color:#C9D4E2;}
"""


def rookie_page(report: Mapping[str, Any]) -> str:
    year = report["year"]
    title = f"{year} NFL rookie report for dynasty and keeper leagues — Beat Your League"
    desc = (f"The {year} rookie class in draft order: where each player landed, how much of "
            f"his position's usage left that team, and how past rookies scored by round.")
    good = {r["position"]: int(r["line"]) for r in report["history"]}
    history = "".join(
        f'<tr><td>{esc(r["position_round"])}</td><td class="n">{r["drafted"]}</td>'
        f'<td class="n">{r["rookie_hits"]}</td>'
        f'<td class="n">{r["within_three"]} of {r["mature"]}</td></tr>'
        for r in _history_rows(report))
    classes = ""
    for position in POSITIONS:
        rows = "".join(
            f'<tr><td class="n">{r["pick"]}</td><td><span class="who">{esc(r["name"])}</span> '
            f'<span class="sub">{esc(r["team"] or "")}, round {r["round"]}</span><br>'
            f'<span class="sub">{esc(_bio(r))}</span></td><td>{esc(_room(r, year))}</td></tr>'
            for r in report["rookies"] if r["position"] == position)
        classes += (f'<h2>{esc(POSITION_NAMES[position])}</h2><div class="scroll"><table>'
                    f'<thead><tr><th class="n">Pick</th><th>Player</th><th>The room</th></tr>'
                    f'</thead><tbody>{rows}</tbody></table></div>')
    return with_counter(f"""<!DOCTYPE html>
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
  <p>Every drafted QB, RB, WR and TE: where he landed, how much of his position's usage left
  that team, and how past rookies taken in the same round scored.</p>
</div></header>
<main id="main"><div class="wrap">
  <p class="note">{esc(ORDER_NOTE)} Teams and the room are as the data stands now.</p>
  <p class="note">Plan members can ask for it by email after each NFL Draft, with the rookies who
  landed beside their own players at the top.</p>
  <h2>How past rookies scored</h2>
  <p class="note">{esc(HISTORY_NOTE.format(qb=good.get("QB", 15), rb=good.get("RB", 10), te=good.get("TE", 8)))}</p>
  <div class="scroll"><table><thead><tr><th>Position, round</th><th class="n">Drafted</th>
  <th class="n">Good pace, Year 1</th><th class="n">Within 3 years</th></tr></thead>
  <tbody>{history}</tbody></table></div>
  {classes}
  <div class="ask">{sample_cta()}</div>
</div></main>
<footer><div class="wrap">{site_footer("")}
  <b>Beat Your League</b> — analysis, not betting picks. {esc(NFLVERSE_LINE)}</div></footer>
</body>
</html>
""")


def load_report(cache: Path, year: int, *, live: bool = False) -> dict[str, Any]:
    """Everything the class needs, from the nflverse cache."""
    from ingest.nflverse import fetch, season_rows
    players = load_players(fetch("players", "players.csv", cache, live=live))
    seasons = {y: season_rows(cache, str(y), columns=None) for y in range(2014, year)}
    return build(players, seasons[year - 1], seasons, preset("ppr"), year)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--cache", type=Path, default=ROOT / "data" / "raw" / "nflverse")
    args = parser.parse_args(argv)
    (SITE / PAGE).write_text(rookie_page(load_report(args.cache, args.year)), encoding="utf-8")
    print(f"wrote site/{PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
