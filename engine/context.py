"""Game context for a projection (reports/context-method.md §2).

Three things the trailing-form model cannot see, each computed from data the
product already reads and handed to ``ProjectionModel`` as optional inputs:

- **A** ``excused_weeks``: byes and announced absences, which are neither an
  appearance nor a miss when availability is measured.
- **M** ``matchup``: how many fantasy points the opponent has allowed to the
  player's position, shrunk toward the league with six games of average.
- **V** ``market``: the team's expected score from the schedule's spread and
  total, as a square-root ratio to the week's average.

Pure functions of their inputs, so the harness and the product compute them
the same way. The market is an input only: nothing here is shown to a buyer.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable, Mapping

from engine.scoring import ScoringRule, score

# The schedule archive spells relocated franchises with the code they had THAT
# year (OAK until 2019, SD until 2016, STL until 2015) while the stat rows use
# today's (LV, LAC, LA). Compared raw, every player on one of those teams read as
# "on bye" all season in 2014-2019 and the market lookup missed the team (found by
# the adversarial review, Sep 29 2026: it inflated the fitted recalibration).
# Everything here speaks the STAT ROW vocabulary.
SCHEDULE_TEAM_ALIASES = {"OAK": "LV", "SD": "LAC", "STL": "LA"}


def team_code(code: str | None) -> str:
    return SCHEDULE_TEAM_ALIASES.get((code or "").strip(), (code or "").strip())


MATCHUP_K = 6.0           # §2 M: games of league average in the shrink
MARKET_POWER = 0.5        # §2 V: square root
ADJUSTED = frozenset({"QB", "RB", "WR", "TE", "K"})
OUT = "Out"               # ingest.injuries' normalised out designation


def _float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def games_by_week(schedule: Iterable[Mapping[str, str]], season: str
                  ) -> dict[int, list[Mapping[str, str]]]:
    out: dict[int, list[Mapping[str, str]]] = defaultdict(list)
    for row in schedule:
        if str(row.get("season")) != str(season):
            continue
        if (row.get("game_type") or "REG").upper() != "REG":
            continue
        try:
            out[int(row.get("week") or 0)].append(row)
        except ValueError:
            continue
    return dict(out)


def _teams_playing(games: Iterable[Mapping[str, str]]) -> set[str]:
    return {team_code(t) for g in games
            for t in (g.get("home_team"), g.get("away_team")) if t}


def team_in_week(player_id: str, week: int,
                 weekly: Mapping[int, Mapping[str, Mapping[str, Any]]]) -> str | None:
    """§2 A: his team on his most recent stat row at or before ``week``,
    else his first stat row after it."""
    if player_id.startswith("DEF-"):
        return player_id.split("-", 1)[1]
    for w in range(week, 0, -1):
        row = (weekly.get(w) or {}).get(player_id)
        if row and row.get("team"):
            return str(row["team"])
    for w in sorted(k for k in weekly if k > week):
        row = weekly[w].get(player_id)
        if row and row.get("team"):
            return str(row["team"])
    return None


def carry_forward_team(player_id: str, week: int,
                       weekly: Mapping[int, Mapping[str, Mapping[str, Any]]]) -> str | None:
    """The gate's team: most recent stat row strictly before ``week``."""
    if player_id.startswith("DEF-"):
        return player_id.split("-", 1)[1]
    for w in range(week - 1, 0, -1):
        row = (weekly.get(w) or {}).get(player_id)
        if row and row.get("team"):
            return str(row["team"])
    return None


def excused_weeks(players: Iterable[str],
                  weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
                  schedule_weeks: Mapping[int, list[Mapping[str, str]]],
                  injuries: Mapping[int, Any], through_week: int
                  ) -> dict[str, frozenset[int]]:
    """§2 A, for weeks 1..through_week-1: byes and out designations."""
    playing = {w: _teams_playing(games) for w, games in schedule_weeks.items()}
    # Only weeks BEFORE the report week exist for the product; the backtest
    # passes the whole season, and team_in_week's "first row after" fallback
    # would then hand a player a team from a future week that the product could
    # never have (103-140 players a season differed).
    weekly = {w: rows for w, rows in weekly.items() if w < through_week}
    out: dict[str, frozenset[int]] = {}
    for pid in players:
        skip = set()
        for w in range(1, through_week):
            team = team_in_week(pid, w, weekly)
            if team and w in playing and team not in playing[w]:
                skip.add(w)
                continue
            report = injuries.get(w)
            if report is not None and report.by_gsis.get(pid) == OUT:
                skip.add(w)
        if skip:
            out[pid] = frozenset(skip)
    return out


def _position(player_id: str, weekly, week: int) -> str | None:
    for w in range(week - 1, 0, -1):
        row = (weekly.get(w) or {}).get(player_id)
        if row and row.get("position"):
            return str(row["position"]).upper()
    return None


def matchup_table(weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
                  rule: ScoringRule, before_week: int
                  ) -> tuple[dict[tuple[str, str], float], dict[str, int], dict[str, float]]:
    """(allowed[(opponent, position)], games[opponent], league[position])."""
    allowed: dict[tuple[str, str], float] = defaultdict(float)
    played: dict[str, set[int]] = defaultdict(set)
    for w in range(1, before_week):
        for row in (weekly.get(w) or {}).values():
            opp = str(row.get("opponent_team") or "").strip()
            pos = str(row.get("position") or "").strip().upper()
            if not opp or pos not in ADJUSTED:
                continue
            played[opp].add(w)
            allowed[(opp, pos)] += score(row, rule)
    games = {team: len(weeks) for team, weeks in played.items()}
    league: dict[str, float] = {}
    for pos in ADJUSTED:
        rates = [allowed.get((team, pos), 0.0) / n for team, n in games.items() if n]
        if rates:
            league[pos] = sum(rates) / len(rates)
    return dict(allowed), games, league


def market_table(games: Iterable[Mapping[str, str]]) -> dict[str, float]:
    """§2 V: team -> (implied / week mean) ** 0.5, for games with lines."""
    implied: dict[str, float] = {}
    for g in games:
        spread, total = _float(g.get("spread_line")), _float(g.get("total_line"))
        home, away = team_code(g.get("home_team")), team_code(g.get("away_team"))
        if spread is None or total is None or not home or not away:
            continue
        implied[home] = (total + spread) / 2
        implied[away] = (total - spread) / 2
    if not implied:
        return {}
    mean = sum(implied.values()) / len(implied)
    return {team: (max(value, 1.0) / mean) ** MARKET_POWER
            for team, value in implied.items()} if mean > 0 else {}


def multiplier_for(week: int, weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
                   rule: ScoringRule, week_games: Iterable[Mapping[str, str]],
                   use_matchup: bool, use_market: bool
                  ) -> Callable[[str, int], float]:
    """The (player_id, week) -> multiplier the model applies in ``week``."""
    games = list(week_games)
    opponent: dict[str, str] = {}
    for g in games:
        home, away = team_code(g.get("home_team")), team_code(g.get("away_team"))
        if home and away:
            opponent[home], opponent[away] = away, home
    allowed, played, league = (matchup_table(weekly, rule, week)
                               if use_matchup else ({}, {}, {}))
    market = market_table(games) if use_market else {}

    def multiplier(player_id: str, asked_week: int) -> float:
        if asked_week != week or player_id.startswith("DEF-"):
            return 1.0
        position = _position(player_id, weekly, week)
        if position not in ADJUSTED:
            return 1.0
        team = carry_forward_team(player_id, week, weekly)
        value = 1.0
        if use_matchup and team in opponent:
            opp = opponent[team]
            base = league.get(position)
            if base:
                n = played.get(opp, 0)
                value *= ((allowed.get((opp, position), 0.0) + MATCHUP_K * base)
                          / ((n + MATCHUP_K) * base))
        if use_market and team in market:
            value *= market[team]
        return value

    return multiplier
