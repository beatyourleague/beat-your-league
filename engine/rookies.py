"""The rookie report: a draft class in plain facts, for keeper and dynasty
managers above all.

Three things, each a record of what happened:

- **The class**, in draft order: where NFL teams took each player, the college,
  age and size. Draft order is the NFL's, and the report says so. It is not a
  ranking of ours.
- **The room**: how much of the team's targets and carries at his position last
  season went to players no longer there, who is still there, and who arrived
  from another team. A vacancy with no arrivals in it would read as more open
  than it is: Mendoza's Raiders lost 96% of their passes and signed Kirk Cousins.
- **This season so far**, once a class has played: games and points a game.
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
# Below this, an arrival is depth rather than part of the room's story.
MIN_ARRIVAL_TOUCHES = 30
ARRIVALS_SHOWN = 2
GONE_STATUSES = ("RET", "CUT")
# players.csv status -> what a reader needs to know. Active says nothing.
STATUS_WORDS = {"DEV": "On the practice squad", "RES": "On the reserve list",
                "RSR": "On the reserve list", "RSN": "On the reserve list",
                "CUT": "Released"}


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
        drafted_by = player.get("draft_team")
        rookies.append({
            "player_id": player.get("gsis_id"), "name": player.get("display_name"),
            "position": player["position"], "round": _int(player.get("draft_round")),
            # Where he is now: a rookie traded or claimed since the draft
            # plays beside this team's players, not the team that took him.
            "pick": pick, "team": player.get("latest_team") or drafted_by,
            "drafted_by": drafted_by,
            "status": STATUS_WORDS.get(player.get("status") or ""),
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
    # Everyone with last-season usage who is on a team now: the arrivals are
    # the ones who did none of that usage for the team they're on.
    usage: dict[tuple[str, str], float] = {}
    for (_team, position), touches in used.items():
        for pid, count in touches.items():
            usage[(pid, position)] = usage.get((pid, position), 0.0) + count
    joined: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
    for (pid, position), count in usage.items():
        player = now.get(pid) or {}
        team = player.get("latest_team")
        if (team and count >= MIN_ARRIVAL_TOUCHES and pid not in used.get((team, position), {})
                and player.get("status") not in GONE_STATUSES):
            joined.setdefault((team, position), []).append(
                (count, pid, player.get("display_name") or pid))
    rooms: dict[tuple[str, str], dict[str, Any]] = {}
    for (team, position), touches in used.items():
        total = sum(touches.values())
        if total <= 0:
            continue
        stayed = {pid: n for pid, n in touches.items()
                  if (now.get(pid) or {}).get("latest_team") == team
                  and (now.get(pid) or {}).get("status") not in GONE_STATUSES}
        lead = max(stayed, key=lambda pid: (stayed[pid], pid), default=None)
        arrived = sorted(joined.get((team, position), []), reverse=True)[:ARRIVALS_SHOWN]
        rooms[(team, position)] = {
            "left_share": round(100 * (total - sum(stayed.values())) / total),
            "lead": (now[lead].get("display_name") if lead else None),
            "arrived": [name for _count, _pid, name in arrived],
            "shares": {pid: round(100 * n / total) for pid, n in touches.items()}}
    return rooms


def this_season(player_id: str, weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
                rule: ScoringRule) -> dict[str, Any] | None:
    """A rookie's games so far, or None before his first. ``games`` counts stat
    rows, so a game he missed isn't a zero."""
    scores = [score(weekly[week][player_id], rule) for week in sorted(weekly)
              if player_id in weekly[week]]
    if not scores:
        return None
    return {"games": len(scores), "per_game": round(sum(scores) / len(scores), 1),
            "recent": [round(s, 1) for s in scores[-3:]]}


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
    """Rookies who landed on a team and position a subscriber already holds,
    with what each of their players did in that room last season. ``roster``
    rows carry player_id, name, position and team. One player on two of a
    subscriber's teams is one line, and a rookie is not beside himself."""
    out = []
    for rookie in rookies:
        room = rookie.get("room") or {}
        shares = room.get("shares") or {}
        mates = {r["player_id"]: r["name"] for r in roster
                 if r.get("team") == rookie["team"] and r.get("position") == rookie["position"]
                 and r.get("player_id") != rookie.get("player_id")}
        if mates:
            ordered = sorted(mates.items(), key=lambda kv: (-shares.get(kv[0], -1), kv[1]))
            out.append({"rookie": rookie["name"], "position": rookie["position"],
                        "team": rookie["team"], "round": rookie["round"],
                        "pick": rookie["pick"], "left_share": room.get("left_share"),
                        "yours": [name for _pid, name in ordered],
                        "usage": [{"name": name, "share": shares.get(pid)}
                                  for pid, name in ordered]})
    return out


def base_rate(rows: Sequence[Mapping[str, Any]], position: str,
              draft_round: int | None) -> dict[str, Any] | None:
    """The history row a rookie belongs to: his position, his round."""
    label = next((name for name, low, high in ROUNDS if low <= (draft_round or 0) <= high), None)
    row = next((r for r in rows if r["position"] == position and r["round"] == label), None)
    return ({"round": label, "drafted": row["drafted"], "rookie_hits": row["rookie_hits"]}
            if row else None)


def build(players: Sequence[Mapping[str, str]], last_season: Mapping[int, Mapping[str, Mapping]],
          seasons: Mapping[int, Mapping[int, Mapping[str, Mapping[str, Any]]]],
          rule: ScoringRule, year: int, as_of: str = "",
          current: Mapping[int, Mapping[str, Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    """The whole report, the same for everyone but ``near_your_players``.
    ``current`` is the class's own season so far, empty until it has played.
    ``as_of`` is the day the data was read, in words."""
    rooms = team_rooms(players, last_season)
    rookies = draft_class(players, year)
    current = current or {}
    rows = history(players, seasons, rule, year)
    for rookie in rookies:
        rookie["room"] = rooms.get((rookie["team"], rookie["position"]))
        rookie["season"] = this_season(rookie["player_id"], current, rule)
        rookie["base_rate"] = base_rate(rows, rookie["position"], rookie["round"])
    return {"year": year, "as_of": as_of, "rookies": rookies,
            "through_week": max(current, default=None), "history": rows}
