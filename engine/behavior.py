"""Per-manager behavioral profiles from a league's transaction log.

Phase 3 requires every behavioral line in a report to cite its evidence
("started questionable players 7 of 9 chances, league log weeks 3-14"). So each
metric here carries the week range and sample size it was computed from, and
anything the cache cannot support is returned as ``None`` with a stated reason
rather than as a plausible-looking number (CLAUDE.md principle 3).

What the transaction log genuinely supports:
- FAAB aggression: bids placed, won, lost, spent, top bid, median bid.
- Waiver activity rate: claims per active week.
- Free-agent churn: adds and drops outside the waiver process.
- Trade volume.
- A *timing proxy*: the share of adds made on NFL game days. Labeled a proxy
  because it measures roster churn timing, not lineup-setting time.

What it does not support, and why:
- ``questionable`` start rate. Sleeper's players table carries a single current
  injury_status, not a per-week history, so a past season simply has no injury
  state to read. Applying today's status to a 2018 lineup would be fabrication.
  This metric starts accumulating the moment weekly snapshots begin.
- Lineup-setting lateness. Lineup changes are not transactions and are absent
  from the public API entirely; no amount of cached data recovers them.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from engine.history import Season

# NFL games are scheduled in US Eastern; a "game day" classification only means
# anything in that timezone.
LEAGUE_TZ = ZoneInfo("America/New_York")

# Thu/Sun/Mon are NFL game days (0=Mon ... 6=Sun in datetime.weekday()).
GAME_WEEKDAYS = frozenset({0, 3, 6})

COMPLETE = "complete"
FAILED = "failed"


@dataclass(frozen=True)
class Unavailable:
    """A metric we deliberately do not compute, and the reason."""

    metric: str
    reason: str


@dataclass
class BehaviorProfile:
    """One manager's habits, with the evidence each number rests on."""

    roster_id: int
    team_label: str
    season: str
    weeks_observed: tuple[int, ...] = ()

    waiver_bids_placed: int = 0
    waiver_bids_won: int = 0
    waiver_bids_lost: int = 0
    faab_spent: int = 0
    faab_budget: int | None = None
    bid_amounts: list[int] = field(default_factory=list)
    winning_bid_amounts: list[int] = field(default_factory=list)

    free_agent_adds: int = 0
    drops: int = 0
    trades: int = 0

    adds_on_game_day: int = 0
    adds_with_timestamp: int = 0

    unavailable: tuple[Unavailable, ...] = ()

    # Set by rank_by_aggression: where this manager sits among their own
    # leaguemates, 0.0 (quietest) to 1.0 (most aggressive).
    aggression_percentile: float | None = None
    aggression_rank: int | None = None
    league_size: int | None = None

    # ---- derived ---------------------------------------------------- #

    @property
    def week_span(self) -> str:
        if not self.weeks_observed:
            return "no weeks"
        return f"weeks {min(self.weeks_observed)}-{max(self.weeks_observed)}"

    @property
    def active_weeks(self) -> int:
        return len(self.weeks_observed)

    @property
    def total_moves(self) -> int:
        return self.waiver_bids_won + self.free_agent_adds + self.trades

    @property
    def moves_per_week(self) -> float | None:
        return self.total_moves / self.active_weeks if self.active_weeks else None

    @property
    def bid_win_rate(self) -> float | None:
        return (
            self.waiver_bids_won / self.waiver_bids_placed
            if self.waiver_bids_placed
            else None
        )

    @property
    def median_bid(self) -> float | None:
        return statistics.median(self.bid_amounts) if self.bid_amounts else None

    @property
    def max_bid(self) -> int | None:
        return max(self.bid_amounts) if self.bid_amounts else None

    @property
    def faab_spent_share(self) -> float | None:
        if not self.faab_budget:
            return None
        return self.faab_spent / self.faab_budget

    @property
    def budget_exceeded(self) -> bool:
        """Spent more than the league's recorded budget.

        Observed in real data (a manager spending 140 against a stated budget of
        100), because a commissioner can raise budgets mid-season and the league
        settings only ever report the current value. When this is true the
        *share* is not meaningful — the raw spend still is.
        """
        return bool(self.faab_budget) and self.faab_spent > self.faab_budget

    @property
    def game_day_add_share(self) -> float | None:
        """Proxy only: share of adds made on Thu/Sun/Mon, league timezone."""
        if not self.adds_with_timestamp:
            return None
        return self.adds_on_game_day / self.adds_with_timestamp

    def aggression_label(self) -> str:
        """Waiver aggression *relative to this manager's own leaguemates*.

        Deliberately not an absolute threshold. Two reasons, both from real
        data: the recorded FAAB budget can be wrong (see ``budget_exceeded``),
        and league cultures differ so widely that a fixed cutoff labelled 8 of
        12 managers in the sample league "very aggressive" — a classifier that
        separates nobody. What a subscriber actually needs to know is where
        their rival sits in *their* league, which is what this measures.
        """
        percentile = self.aggression_percentile
        if percentile is None:
            return "unranked"
        if percentile >= 0.80:
            return "very aggressive"
        if percentile >= 0.60:
            return "aggressive"
        if percentile >= 0.35:
            return "selective"
        return "quiet"

    def aggression_evidence(self) -> str:
        """The citation Phase 3 requires next to any behavioral claim."""
        if self.aggression_rank is None or not self.league_size:
            return f"{self.season}, {self.week_span}"
        return (
            f"#{self.aggression_rank} of {self.league_size} on waiver spend, "
            f"{self.season} {self.week_span}"
        )


def _timestamp(transaction: Mapping[str, Any]) -> datetime | None:
    raw = transaction.get("status_updated") or transaction.get("created")
    if not isinstance(raw, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc).astimezone(LEAGUE_TZ)
    except (OverflowError, OSError, ValueError):
        return None


def _rosters_involved(transaction: Mapping[str, Any]) -> set[int]:
    rosters: set[int] = set()
    for mapping_key in ("adds", "drops"):
        mapping = transaction.get(mapping_key)
        if isinstance(mapping, dict):
            for roster_id in mapping.values():
                if isinstance(roster_id, int):
                    rosters.add(roster_id)
    for roster_id in transaction.get("roster_ids") or []:
        if isinstance(roster_id, int):
            rosters.add(roster_id)
    return rosters


def _adds_for(transaction: Mapping[str, Any], roster_id: int) -> int:
    adds = transaction.get("adds")
    if isinstance(adds, dict):
        return sum(1 for target in adds.values() if target == roster_id)
    return 0


def _drops_for(transaction: Mapping[str, Any], roster_id: int) -> int:
    drops = transaction.get("drops")
    if isinstance(drops, dict):
        return sum(1 for target in drops.values() if target == roster_id)
    return 0


UNAVAILABLE_METRICS: tuple[Unavailable, ...] = (
    Unavailable(
        metric="questionable-start rate",
        reason=(
            "Sleeper's players table carries only a current injury_status, not "
            "per-week history, so a past season has no injury state to read. "
            "Starts accumulating once weekly snapshots begin."
        ),
    ),
    Unavailable(
        metric="lineup-setting lateness",
        reason=(
            "Lineup changes are not transactions and are not exposed by the "
            "public API; no cached data recovers them."
        ),
    ),
)


def profile_season(season: Season) -> dict[int, BehaviorProfile]:
    """Build a behavioral profile for every roster in a league-season."""
    weeks = sorted(season.transactions)
    profiles: dict[int, BehaviorProfile] = {
        roster_id: BehaviorProfile(
            roster_id=roster_id,
            team_label=season.team_label(roster_id),
            season=season.season,
            weeks_observed=tuple(weeks),
            faab_budget=season.waiver_budget,
            unavailable=UNAVAILABLE_METRICS,
        )
        for roster_id in season.teams
    }

    def profile_for(roster_id: int) -> BehaviorProfile:
        existing = profiles.get(roster_id)
        if existing is None:
            existing = BehaviorProfile(
                roster_id=roster_id,
                team_label=season.team_label(roster_id),
                season=season.season,
                weeks_observed=tuple(weeks),
                faab_budget=season.waiver_budget,
                unavailable=UNAVAILABLE_METRICS,
            )
            profiles[roster_id] = existing
        return existing

    for week in weeks:
        for transaction in season.transactions[week]:
            kind = transaction.get("type")
            status = transaction.get("status")
            settings = transaction.get("settings") or {}
            bid = settings.get("waiver_bid")
            when = _timestamp(transaction)

            for roster_id in _rosters_involved(transaction):
                profile = profile_for(roster_id)
                adds = _adds_for(transaction, roster_id)
                drops = _drops_for(transaction, roster_id)

                if kind == "waiver":
                    # A failed claim still reveals intent and price, which is
                    # exactly what makes FAAB aggression readable.
                    profile.waiver_bids_placed += 1
                    if isinstance(bid, int):
                        profile.bid_amounts.append(bid)
                    if status == COMPLETE:
                        profile.waiver_bids_won += 1
                        if isinstance(bid, int):
                            profile.faab_spent += bid
                            profile.winning_bid_amounts.append(bid)
                    elif status == FAILED:
                        profile.waiver_bids_lost += 1
                elif kind == "free_agent" and status == COMPLETE:
                    profile.free_agent_adds += adds
                elif kind == "trade" and status == COMPLETE:
                    profile.trades += 1

                if status == COMPLETE:
                    profile.drops += drops
                    if adds and when is not None:
                        profile.adds_with_timestamp += adds
                        if when.weekday() in GAME_WEEKDAYS:
                            profile.adds_on_game_day += adds

    return profiles


def rank_by_aggression(profiles: Iterable[BehaviorProfile]) -> list[BehaviorProfile]:
    """Rank managers against their own leaguemates, most aggressive first.

    Mutates each profile to record its percentile and rank, so the label and
    its evidence string stay consistent with the ordering shown.
    """
    ordered = sorted(
        profiles, key=lambda p: (p.faab_spent, p.total_moves, p.roster_id)
    )
    size = len(ordered)
    for index, profile in enumerate(ordered):
        profile.league_size = size
        # A one-team league has nobody to compare against, so it stays unranked
        # rather than being declared the most aggressive manager in it.
        profile.aggression_percentile = index / (size - 1) if size > 1 else None
        profile.aggression_rank = size - index
    return list(reversed(ordered))


# --------------------------------------------------------------------- #
# manager lineup quality — the other half of a rival profile
# --------------------------------------------------------------------- #

@dataclass(frozen=True)
class LineupRecord:
    """How well a manager actually set lineups, from graded calls."""

    roster_id: int
    team_label: str
    calls: int
    manager_correct: int
    points_left_on_bench: float

    @property
    def accuracy(self) -> float | None:
        return self.manager_correct / self.calls if self.calls else None


def lineup_records(
    season: Season, calls: Sequence[Any]
) -> list[LineupRecord]:
    """Per-roster start/sit accuracy, measured on the same graded call set.

    "Correct" means the player the manager started outscored the alternative —
    judged on outcomes, so this measures the human, not the engine.
    """
    by_roster: dict[int, list[Any]] = {}
    for call in calls:
        by_roster.setdefault(call.roster_id, []).append(call)

    records: list[LineupRecord] = []
    for roster_id, roster_calls in by_roster.items():
        decided = [c for c in roster_calls if c.actual_started != c.actual_alternative]
        correct = sum(1 for c in decided if c.actual_started > c.actual_alternative)
        records.append(
            LineupRecord(
                roster_id=roster_id,
                team_label=season.team_label(roster_id),
                calls=len(decided),
                manager_correct=correct,
                points_left_on_bench=sum(
                    c.manager_points_left_on_bench for c in roster_calls
                ),
            )
        )
    return sorted(records, key=lambda r: r.accuracy or 0.0, reverse=True)
