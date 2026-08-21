"""Read cached Sleeper JSON into typed league-season structures.

Reads ``data/raw/`` only: no network, no LLM. A missing file is reported as
missing rather than silently treated as an empty week (CLAUDE.md principle 3).

Two shapes worth knowing about, both verified against the live API:

- ``matchups/{week}`` returns one record per roster, and its ``starters`` array
  is positionally aligned with the league's ``roster_positions`` minus ``BN``.
  So ``starters[3]`` sits in ``starting_slots[3]``. Verified across 17x12
  roster-weeks of the sample league (1836 slots, 0 length mismatches).
- ``players_points`` covers bench players too, which is what makes start/sit
  grading possible from league data alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

BENCH_SLOT = "BN"
# Slots that hold a player but are never a start/sit decision we grade.
NON_STARTING_SLOTS = frozenset({BENCH_SLOT, "IR", "TAXI"})

# Which positions may fill a multi-position slot. Anything not listed is a
# single-position slot that only its own position can fill (QB, RB, TE, K, DEF).
FLEX_ELIGIBILITY: Mapping[str, frozenset[str]] = {
    "FLEX": frozenset({"RB", "WR", "TE"}),
    "WRRB_FLEX": frozenset({"RB", "WR"}),
    "REC_FLEX": frozenset({"WR", "TE"}),
    "SUPER_FLEX": frozenset({"QB", "RB", "WR", "TE"}),
    "IDP_FLEX": frozenset({"DL", "LB", "DB"}),
}

# Sleeper writes an unfilled starting slot as "0" (and very rarely "").
EMPTY_SLOT_IDS = frozenset({"0", "", "null"})


class HistoryError(RuntimeError):
    """Raised when the cache is missing data a caller explicitly asked for."""


# --------------------------------------------------------------------- #
# players
# --------------------------------------------------------------------- #

@dataclass(frozen=True)
class PlayerInfo:
    """The slice of Sleeper's player record the engine actually uses."""

    player_id: str
    name: str
    positions: frozenset[str]

    def eligible_for(self, slot: str) -> bool:
        allowed = FLEX_ELIGIBILITY.get(slot)
        if allowed is not None:
            return bool(self.positions & allowed)
        return slot in self.positions

    @property
    def primary_position(self) -> str:
        """One position for grouping. Deterministic for multi-position players."""
        if not self.positions:
            return "UNK"
        return sorted(self.positions)[0]


class PlayerIndex:
    """Lookup over the cached ``/players/nfl`` table.

    Caveat worth stating once: this table is a *current* snapshot. Names and
    positions can drift from what they were in a past season (a 2018 WR listed
    as a TE today), and ``injury_status`` describes today, not a historical
    week — so it must never be applied to a backtest (CLAUDE.md principle 3).
    """

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self._players: dict[str, PlayerInfo] = {}
        for player_id, record in raw.items():
            if not isinstance(record, dict):
                continue
            positions = {p for p in (record.get("fantasy_positions") or []) if p}
            position = record.get("position")
            if position:
                positions.add(position)
            name = (
                record.get("full_name")
                or " ".join(
                    p for p in (record.get("first_name"), record.get("last_name")) if p
                )
                or player_id
            )
            self._players[str(player_id)] = PlayerInfo(
                player_id=str(player_id),
                name=str(name).strip(),
                positions=frozenset(positions),
            )

    def __contains__(self, player_id: str) -> bool:
        return player_id in self._players

    def __len__(self) -> int:
        return len(self._players)

    def get(self, player_id: str) -> PlayerInfo | None:
        return self._players.get(player_id)

    def name(self, player_id: str) -> str:
        info = self._players.get(player_id)
        return info.name if info else f"player {player_id}"

    def position(self, player_id: str) -> str:
        info = self._players.get(player_id)
        return info.primary_position if info else "UNK"


def load_players(raw_dir: Path) -> PlayerIndex:
    path = Path(raw_dir) / "players" / "nfl.json"
    if not path.is_file():
        raise HistoryError(
            f"players table not cached at {path} — run `python -m ingest.pull` first"
        )
    with path.open(encoding="utf-8") as fh:
        return PlayerIndex(json.load(fh))


# --------------------------------------------------------------------- #
# league seasons
# --------------------------------------------------------------------- #

@dataclass(frozen=True)
class Team:
    roster_id: int
    team_name: str
    owner_name: str
    owner_id: str | None

    @property
    def label(self) -> str:
        if self.team_name and self.team_name != self.owner_name:
            return f"{self.team_name} ({self.owner_name})"
        return self.team_name or self.owner_name


@dataclass(frozen=True)
class TeamWeek:
    """One roster's week: who started where, and what everyone scored."""

    roster_id: int
    week: int
    matchup_id: int | None
    starters: tuple[str, ...]
    starters_points: tuple[float, ...]
    players: tuple[str, ...]
    players_points: Mapping[str, float]
    points: float
    # Who actually took the field, when we can know it independently of what
    # they scored. None means "we cannot tell" and the points convention below
    # applies — which is the Sleeper case, where 0.0 was the ONLY absence
    # signal the feed ever gave us.
    appeared: frozenset[str] | None = None

    def did_appear(self, player_id: str) -> bool:
        """Did this player play, as distinct from scoring nothing?

        The two are not the same and conflating them is measurable: 15.2% of
        2024 fantasy stat rows score exactly 0.00, and the rate is strongly
        position-dependent — 20.5% of WR rows and 21.7% of TE rows against 1.2%
        of QB rows. Reading those as absences understates receivers' appearance
        rate specifically, which feeds straight into the availability gate.

        Sleeper never offered anything better, so a None ``appeared`` falls back
        to the old convention and the historical backtest is unaffected.
        nflverse does: a stat row exists or it does not.
        """
        if self.appeared is not None:
            return player_id in self.appeared
        points = self.players_points.get(player_id)
        return points is not None and points != 0.0

    def bench(self) -> tuple[str, ...]:
        """Rostered players not in a starting slot this week."""
        started = set(self.starters)
        return tuple(p for p in self.players if p not in started)

    def actual_points(self, player_id: str) -> float | None:
        value = self.players_points.get(player_id)
        return None if value is None else float(value)


@dataclass
class Season:
    """One league-season assembled from cache."""

    league_id: str
    season: str
    name: str
    status: str
    roster_positions: tuple[str, ...]
    playoff_week_start: int | None
    scoring_settings: Mapping[str, Any]
    waiver_budget: int | None
    teams: dict[int, Team] = field(default_factory=dict)
    weeks: dict[int, dict[int, TeamWeek]] = field(default_factory=dict)
    transactions: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def starting_slots(self) -> tuple[str, ...]:
        return tuple(p for p in self.roster_positions if p not in NON_STARTING_SLOTS)

    @property
    def graded_weeks(self) -> list[int]:
        return sorted(self.weeks)

    def team_weeks(self) -> Iterator[TeamWeek]:
        for week in self.graded_weeks:
            for roster_id in sorted(self.weeks[week]):
                yield self.weeks[week][roster_id]

    def team_label(self, roster_id: int) -> str:
        team = self.teams.get(roster_id)
        return team.label if team else f"roster {roster_id}"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _team_table(users: list[dict[str, Any]], rosters: list[dict[str, Any]]) -> dict[int, Team]:
    """Same team-name fallback as Phase 1: ``metadata.team_name`` is unset until
    an owner customizes it, and a roster can be orphaned (``owner_id: null``)."""
    users_by_id = {u.get("user_id"): u for u in users}
    teams: dict[int, Team] = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        owner = users_by_id.get(owner_id) or {}
        owner_name = owner.get("display_name") or "(no owner)"
        metadata = owner.get("metadata") or {}
        team_name = metadata.get("team_name") or owner_name
        roster_id = int(roster.get("roster_id", 0))
        teams[roster_id] = Team(
            roster_id=roster_id,
            team_name=str(team_name),
            owner_name=str(owner_name),
            owner_id=str(owner_id) if owner_id else None,
        )
    return teams


def _parse_team_week(record: dict[str, Any], week: int) -> TeamWeek | None:
    if not isinstance(record, dict) or record.get("roster_id") is None:
        return None
    raw_points = record.get("players_points") or {}
    players_points = {
        str(k): float(v)
        for k, v in raw_points.items()
        if isinstance(v, (int, float))
    }
    starters = tuple(str(s) for s in (record.get("starters") or []))
    players = tuple(str(p) for p in (record.get("players") or []))
    # A starter missing from `players` still belongs to the roster that week;
    # keep the union so bench detection can't accidentally promote a starter.
    for starter in starters:
        if starter not in players and starter not in EMPTY_SLOT_IDS:
            players = players + (starter,)
    matchup_id = record.get("matchup_id")
    return TeamWeek(
        roster_id=int(record["roster_id"]),
        week=week,
        matchup_id=int(matchup_id) if matchup_id is not None else None,
        starters=starters,
        starters_points=tuple(
            float(p) for p in (record.get("starters_points") or []) if isinstance(p, (int, float))
        ),
        players=players,
        players_points=players_points,
        points=float(record.get("points") or 0.0),
    )


def load_season(raw_dir: Path, league_id: str, max_week: int = 18) -> Season:
    """Load one league-season from the Phase 1 cache.

    Weeks with no cached file, or cached as an empty list, are simply absent
    from ``season.weeks`` — the report says "13 weeks graded", never pretends
    to 17.
    """
    league_dir = Path(raw_dir) / "league" / str(league_id)
    league_path = league_dir / "league.json"
    if not league_path.is_file():
        raise HistoryError(
            f"league {league_id} not cached at {league_path} — "
            "run `python -m ingest.pull` first"
        )
    league = _read_json(league_path)
    settings = league.get("settings") or {}

    users = _read_json(league_dir / "users.json") if (league_dir / "users.json").is_file() else []
    rosters = _read_json(league_dir / "rosters.json") if (league_dir / "rosters.json").is_file() else []

    season = Season(
        league_id=str(league.get("league_id", league_id)),
        season=str(league.get("season", "?")),
        name=str(league.get("name", "?")),
        status=str(league.get("status", "?")),
        roster_positions=tuple(league.get("roster_positions") or []),
        playoff_week_start=(
            int(settings["playoff_week_start"])
            if isinstance(settings.get("playoff_week_start"), int)
            else None
        ),
        scoring_settings=league.get("scoring_settings") or {},
        waiver_budget=(
            int(settings["waiver_budget"])
            if isinstance(settings.get("waiver_budget"), int)
            else None
        ),
        teams=_team_table(users, rosters),
    )

    for week in range(1, max_week + 1):
        matchup_path = league_dir / "matchups" / f"week_{week:02d}.json"
        if matchup_path.is_file():
            records = _read_json(matchup_path) or []
            parsed = {}
            for record in records:
                team_week = _parse_team_week(record, week)
                if team_week is not None:
                    parsed[team_week.roster_id] = team_week
            if parsed:
                season.weeks[week] = parsed

        transaction_path = league_dir / "transactions" / f"week_{week:02d}.json"
        if transaction_path.is_file():
            entries = _read_json(transaction_path) or []
            if entries:
                season.transactions[week] = [e for e in entries if isinstance(e, dict)]

    return season


def load_season_chain(raw_dir: Path, league_id: str, max_seasons: int = 4) -> list[Season]:
    """Load a league and its ancestors by walking ``previous_league_id``.

    Stops at the first season that isn't cached — Phase 1 pulls two seasons, so
    asking for four here yields two, not an error.
    """
    seasons: list[Season] = []
    seen: set[str] = set()
    current_id: str | None = str(league_id)
    while current_id and current_id not in seen and len(seasons) < max_seasons:
        seen.add(current_id)
        try:
            season = load_season(raw_dir, current_id)
        except HistoryError:
            break
        seasons.append(season)
        league_path = Path(raw_dir) / "league" / current_id / "league.json"
        previous = _read_json(league_path).get("previous_league_id")
        current_id = str(previous) if previous else None
    if not seasons:
        raise HistoryError(
            f"no cached seasons found for league {league_id} — "
            "run `python -m ingest.pull` first"
        )
    return seasons
