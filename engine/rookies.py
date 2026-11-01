"""The rookie report: a draft class in plain facts, for keeper and dynasty
managers above all.

Three things, each a record of what happened:

- **The class**, in draft order: where NFL teams took each player, the college,
  age and size. Draft order is the NFL's, and the report says so. It is not a
  ranking of ours.
- **The room**: how much of the team's targets and carries at his position last
  season went to players no longer there, and who is still there.
- **The history**: how rookies taken in the same round have scored. It's a base
  rate from past classes, under one stated scoring rule, never a forecast.

Everything comes from nflverse's ``players`` and ``stats_player`` releases. The
``draft_picks`` release is Pro-Football-Reference data, so RULE N2 keeps it out;
``players.csv`` carries the round, pick and team itself. No ranking, no
projection and no probability appear here, because none of them could be graded
(principle 1).
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from engine.scoring import ScoringRule, score

POSITIONS = ("QB", "RB", "WR", "TE")
MIN_GAMES = 6
# The scoring line that means "a starter's week" at each position.
GOOD_GAME = {"QB": 15.0, "RB": 10.0, "WR": 10.0, "TE": 8.0}
ROUNDS = (("Round 1", 1, 1), ("Round 2", 2, 2), ("Round 3", 3, 3), ("Rounds 4–7", 4, 7))
FIRST_CLASS = 2014
YEARS_OUT = 3
# A class is complete enough to publish once this many picks are in the file.
MIN_PICKS = 200


def load_players(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _height(inches: Any) -> str | None:
    total = _int(inches)
    return f"{total // 12}'{total % 12}\"" if total else None


def _age(birth: str, year: int) -> int | None:
    """Age on May 1 of the draft year: the week after the draft."""
    try:
        born = date.fromisoformat(birth)
    except (TypeError, ValueError):
        return None
    return year - born.year - ((5, 1) < (born.month, born.day))


def picks_in(players: Iterable[Mapping[str, str]], year: int) -> int:
    return sum(1 for p in players
               if _int(p.get("draft_year")) == year and _int(p.get("draft_pick")))


def draft_class(players: Iterable[Mapping[str, str]], year: int) -> list[dict[str, Any]]:
    """The class's skill players, in draft order."""
    rookies = []
    for player in players:
        pick = _int(player.get("draft_pick"))
        if (_int(player.get("draft_year")) != year or not pick
                or player.get("position") not in POSITIONS):
            continue
        rookies.append({
            "player_id": player.get("gsis_id"), "name": player.get("display_name"),
            "position": player["position"], "round": _int(player.get("draft_round")),
            "pick": pick, "team": player.get("draft_team"),
            # A transfer's colleges are listed newest first.
            "college": (player.get("college_name") or "").split(";")[0].strip() or None,
            "age": _age(player.get("birth_date") or "", year),
            "height": _height(player.get("height")), "weight": _int(player.get("weight"))})
    return sorted(rookies, key=lambda r: r["pick"])


def _touches(row: Mapping[str, Any], position: str) -> float:
    def number(key: str) -> float:
        try:
            return float(row.get(key) or 0)
        except ValueError:
            return 0.0
    return number("attempts") if position == "QB" else number("targets") + number("carries")


def team_rooms(players: Iterable[Mapping[str, str]],
               weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
               ) -> dict[tuple[str, str], dict[str, Any]]:
    """(team, position) -> last season's usage there and who has left it.

    ``weekly`` is last season with every column kept. A player's team is the
    one in that week's row; where he is now comes from the players file."""
    now = {p.get("gsis_id"): p for p in players}
    used: dict[tuple[str, str], dict[str, float]] = {}
    for rows in weekly.values():
        for pid, row in rows.items():
            position = row.get("position")
            if position not in POSITIONS or not row.get("team"):
                continue
            slot = used.setdefault((row["team"], position), {})
            slot[pid] = slot.get(pid, 0.0) + _touches(row, position)
    rooms: dict[tuple[str, str], dict[str, Any]] = {}
    for (team, position), touches in used.items():
        total = sum(touches.values())
        if total <= 0:
            continue
        stayed = {pid: n for pid, n in touches.items()
                  if (now.get(pid) or {}).get("latest_team") == team
                  and (now.get(pid) or {}).get("status") not in ("RET", "CUT")}
        lead = max(stayed, key=lambda pid: (stayed[pid], pid), default=None)
        rooms[(team, position)] = {
            "left_share": round(100 * (total - sum(stayed.values())) / total),
            "lead": (now[lead].get("display_name") if lead else None)}
    return rooms


def _per_game(player_id: str, weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
              rule: ScoringRule) -> float | None:
    games = [score(rows[player_id], rule) for rows in weekly.values() if player_id in rows]
    return sum(games) / len(games) if len(games) >= MIN_GAMES else None


def history(players: Sequence[Mapping[str, str]],
            seasons: Mapping[int, Mapping[int, Mapping[str, Mapping[str, Any]]]],
            rule: ScoringRule, year: int) -> list[dict[str, Any]]:
    """How past rookies scored, by position and round. ``seasons`` is season ->
    week -> gsis -> row. A class counts toward "within three seasons" only once
    it has had three seasons, so recent classes can't drag that figure down."""
    rows = []
    for position in POSITIONS:
        line = GOOD_GAME[position]
        for label, low, high in ROUNDS:
            taken = [p for p in players
                     if p.get("position") == position
                     and FIRST_CLASS <= (_int(p.get("draft_year")) or 0) < year
                     and low <= (_int(p.get("draft_round")) or 0) <= high]
            rookie_hits = 0
            for player in taken:
                first = int(player["draft_year"])
                pace = _per_game(player["gsis_id"], seasons.get(first) or {}, rule)
                rookie_hits += pace is not None and pace >= line
            mature = [p for p in taken if int(p["draft_year"]) + YEARS_OUT - 1 < year]
            later = 0
            for player in mature:
                first = int(player["draft_year"])
                paces = [_per_game(player["gsis_id"], seasons.get(first + n) or {}, rule)
                         for n in range(YEARS_OUT)]
                later += any(p is not None and p >= line for p in paces)
            if taken:
                rows.append({"position": position, "round": label, "line": line,
                             "drafted": len(taken), "rookie_hits": rookie_hits,
                             "mature": len(mature), "within_three": later})
    return rows


def near_your_players(rookies: Sequence[Mapping[str, Any]],
                      roster: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rookies who landed on a team and position a subscriber already holds.
    ``roster`` rows carry name, position and team."""
    out = []
    for rookie in rookies:
        mates = sorted(r["name"] for r in roster
                       if r.get("team") == rookie["team"]
                       and r.get("position") == rookie["position"])
        if mates:
            out.append({"rookie": rookie["name"], "position": rookie["position"],
                        "team": rookie["team"], "round": rookie["round"],
                        "pick": rookie["pick"], "yours": mates})
    return out


def build(players: Sequence[Mapping[str, str]], last_season: Mapping[int, Mapping[str, Mapping]],
          seasons: Mapping[int, Mapping[int, Mapping[str, Mapping[str, Any]]]],
          rule: ScoringRule, year: int) -> dict[str, Any]:
    """The whole report, the same for everyone but ``near_your_players``."""
    rooms = team_rooms(players, last_season)
    rookies = draft_class(players, year)
    for rookie in rookies:
        rookie["room"] = rooms.get((rookie["team"], rookie["position"]))
    return {"year": year, "rookies": rookies, "history": history(players, seasons, rule, year)}
