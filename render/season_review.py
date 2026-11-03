"""The season review email (run/season_review.py): one email per address, one
section per team. It reports what the reports said and what happened, misses
beside hits, and predicts nothing about next season.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from render.email import BASE, FLAG, FONT, NAVY, SMALL
from render.report import NFLVERSE_LINE, NO_BETTING_LINE, esc, seat_stop_href
from render.sender import sender_line
from render.team_mail import _shell
from run.delivery import Message

ROOKIE_HEAD = "The rookie report"
ROOKIE_BODY = ("After the NFL Draft we'll put together a report on the new class: where each "
               "player landed, who he joins, and any who landed beside your players. It's "
               "free and nothing bills. Want it?")
ROOKIE_BUTTON = "Send me the rookie report"
NOTHING_BILLS = "Nothing bills from this email."
STOP = "Don't want these? Reply with the word stop."
# The odds it graded and the box scores it graded them on (launch review
# LEG-3): RULE N1's CC-BY-4.0 credit is a licence term, and principle 4's
# disclaimer rides every render.
SOURCE_LINES = (NO_BETTING_LINE, NFLVERSE_LINE)


# The longest ordinary section, for the launch check's width and sender audit.
REVIEW_SAMPLE = {"weeks": 12, "first_week": 7, "last_week": 18, "calls": 31, "hits": 20,
                 "no_result": 1,
                 "bands": [{"label": "70% or higher", "calls": 9, "hits": 7},
                           {"label": "60–69%", "calls": 14, "hits": 9},
                           {"label": "Under 60%", "calls": 8, "hits": 4}],
                 "best_call": {"week": 11, "pick": "Amon-Ra St. Brown", "over": "Tony Pollard",
                               "percent": 80, "got": 32.1, "other": 9.4},
                 "worst_miss": {"week": 14, "pick": "George Kittle", "over": "Sam LaPorta",
                                "percent": 72, "got": 3.2, "other": 21.0},
                 "top_scorers": [{"name": "Josh Allen", "points": 240.5, "starts": 11}],
                 "rookies": [{"name": "Jeremiyah Love", "position": "RB",
                              "season": {"games": 14, "per_game": 12.3, "recent": [9.1, 14.0, 11.2]}},
                             {"name": "Jordyn Tyson", "position": "WR", "season": None}]}


def _lines(name: str, team: Mapping[str, Any]) -> list[str]:
    lines = [f"Reports covered Weeks {team['first_week']}–{team['last_week']} "
             f"({team['weeks']} of them)."]
    if team["calls"]:
        extra = (f", plus {team['no_result']} with no result" if team["no_result"] else "")
        lines.append(f"Calls with odds: {team['hits']} of {team['calls']} came in{extra}.")
        lines += [f"{band['label']}: {band['hits']} of {band['calls']}"
                  for band in team["bands"]]
    else:
        lines.append("No calls with odds were graded for this team.")
    best = team.get("best_call")
    if best:
        lines.append(f"Best call: Week {best['week']}, {best['pick']} over {best['over']} "
                     f"at {best['percent']}%. {best['got']:.1f} to {best['other']:.1f}.")
    worst = team.get("worst_miss")
    if worst:
        lines.append(f"Biggest miss: Week {worst['week']}, {worst['pick']} over {worst['over']} "
                     f"at {worst['percent']}%. {worst['got']:.1f} to {worst['other']:.1f}.")
    for row in team.get("top_scorers") or []:
        lines.append(f"{row['name']}: {row['points']:.1f} points in {row['starts']} starts "
                     f"in the lineups we set.")
    rookies = team.get("rookies") or []
    if rookies:
        lines.append("Your rookies:")
        lines += [_rookie(row) for row in rookies]
    return lines


def _rookie(row: Mapping[str, Any]) -> str:
    played = row.get("season")
    who = f"{row['name']}, {row['position']}"
    if not played:
        return f"{who}: no games."
    if played["games"] == 1:
        return f"{who}: 1 game, {played['per_game']:.1f} points."
    return f"{who}: {played['games']} games, {played['per_game']:.1f} a game."


def review_message(email: str, season: str, teams: Sequence[tuple[str, Mapping[str, Any]]],
                   key: str, rookie_url: str | None = None) -> Message:
    """``teams`` is (name, engine.season_review.review_team) per team."""
    subject = f"Your {season} season review"
    sections = [(name, _lines(name, team)) for name, team in teams]
    body = "".join(
        f'<p style="{BASE}margin:0 0 6px 0;"><b>{esc(name)}</b></p>'
        + "".join(f'<p style="{BASE}margin:0 0 4px 0;">{esc(line)}</p>' for line in lines)
        + f'<p style="{SMALL}margin:0 0 10px 0;">&nbsp;</p>' for name, lines in sections)
    if rookie_url:
        body += (f'<p style="{BASE}margin:0 0 6px 0;"><b>{esc(ROOKIE_HEAD)}</b></p>'
                 f'<p style="{BASE}margin:0 0 12px 0;">{esc(ROOKIE_BODY)}</p>'
                 f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
                 f'<td style="background:{FLAG};border-radius:4px;">'
                 f'<a href="{esc(rookie_url)}" style="display:inline-block;padding:12px 22px;'
                 f'font-family:{FONT};font-size:15px;font-weight:bold;color:{NAVY};'
                 f'text-decoration:none;">{esc(ROOKIE_BUTTON)}</a></td></tr></table>')
    sender = sender_line()
    body += "".join(f'<p style="{SMALL}margin:14px 0 0 0;">{esc(line)}</p>'
                    for line in SOURCE_LINES)
    body += (f'<p style="{SMALL}margin:14px 0 0 0;">{esc(NOTHING_BILLS)} {esc(STOP)}</p>'
             + (f'<p style="{SMALL}margin:8px 0 0 0;">{esc(sender)}</p>' if sender else ""))
    html = _shell(subject, "How your calls landed this season, misses included.", body)
    text: list[str] = [subject.upper(), ""]
    for name, lines in sections:
        text += [name, *lines, ""]
    if rookie_url:
        text += [ROOKIE_HEAD.upper(), ROOKIE_BODY, f"{ROOKIE_BUTTON}: {rookie_url}", ""]
    text += [*SOURCE_LINES, "", f"{NOTHING_BILLS} {STOP}", *([sender] if sender else []), ""]
    return Message(to=email, subject=subject, html=html, text="\n".join(text), key=key,
                   unsubscribe=seat_stop_href())
