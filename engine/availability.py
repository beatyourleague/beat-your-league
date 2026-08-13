"""Player availability for a specific week: snapshot + schedule, classified.

The Phase 2 backtest's headline finding: the engine's error source is not
scoring math but not knowing who will play. This module is the fix, and its
honesty contract (CLAUDE.md principles 1 and 3) is enforced here in one place:

- Statuses come only from a snapshot *taken during the week in question* (see
  ``ingest/availability.py``) and byes only from the cached NFL schedule.
- A week with no snapshot yields UNKNOWN for every player — never a guess.
  Historical seasons before snapshotting began are therefore all UNKNOWN,
  which is true.
- The published confidence number is gated on availability being known for
  BOTH players in a head-to-head (``may_publish_confidence``). The calibration
  evidence only supports the model when availability is visible; outside that,
  the report renders "coming in v0.3", never a number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ingest.availability import snapshot_path

# Game designations that mean "will not play" vs "in doubt". Sleeper's
# injury_status values observed on the live players table.
OUT_DESIGNATIONS = frozenset({"Out", "IR", "Sus", "PUP", "NA", "COV", "DNR"})
DOUBTFUL_DESIGNATIONS = frozenset({"Questionable", "Doubtful"})


class Status(str, Enum):
    ACTIVE = "active"            # rostered, no designation, not on bye
    QUESTIONABLE = "questionable"  # Q/D designation: in genuine doubt
    OUT = "out"                  # designated out / off an NFL roster / bye
    UNKNOWN = "unknown"          # no snapshot covers this week


@dataclass(frozen=True)
class PlayerStatus:
    status: Status
    reason: str          # human-readable basis, citable in the report
    as_of: str | None    # snapshot timestamp, None when UNKNOWN


@dataclass(frozen=True)
class WeekAvailability:
    """Everything known about availability for one (season, week)."""

    season: str
    week: int
    snapshot_as_of: str | None
    statuses: Mapping[str, Mapping[str, Any]] | None
    bye_teams: frozenset[str] | None   # None = schedule not cached

    @property
    def has_snapshot(self) -> bool:
        return self.statuses is not None

    def classify(self, player_id: str) -> PlayerStatus:
        # Bye weeks are decidable from the schedule alone, snapshot or not —
        # but only when we can resolve the player's team, which itself comes
        # from the snapshot (the players table is current-day, not historical).
        if not self.has_snapshot:
            return PlayerStatus(
                Status.UNKNOWN,
                f"no availability snapshot for {self.season} week {self.week}",
                None,
            )
        assert self.statuses is not None
        record = self.statuses.get(player_id)
        if record is None:
            return PlayerStatus(
                Status.UNKNOWN, "player absent from availability snapshot",
                self.snapshot_as_of,
            )
        team = record.get("team")
        position = record.get("position")
        if self.bye_teams is not None and team and team in self.bye_teams:
            return PlayerStatus(
                Status.OUT, f"{team} on bye (NFL schedule)", self.snapshot_as_of
            )
        # OUT/QUESTIONABLE are decidable without the schedule — decide them first.
        if position != "DEF" and (not record.get("active") or not team):
            return PlayerStatus(
                Status.OUT, "not on an NFL roster", self.snapshot_as_of
            )
        designation = record.get("injury_status")
        if designation in OUT_DESIGNATIONS:
            return PlayerStatus(
                Status.OUT, f"designated {designation}", self.snapshot_as_of
            )
        if designation in DOUBTFUL_DESIGNATIONS:
            return PlayerStatus(
                Status.QUESTIONABLE, f"designated {designation}", self.snapshot_as_of
            )
        if designation:
            # An unrecognized designation is doubt, not a green light.
            return PlayerStatus(
                Status.QUESTIONABLE, f"designated {designation} (unrecognized)",
                self.snapshot_as_of,
            )
        # ACTIVE requires knowing the player is NOT on bye. Without the
        # schedule that is unknowable, and unknowable never means "cleared"
        # (principle 1) — a clean injury report on a bye week is still a zero.
        if self.bye_teams is None:
            return PlayerStatus(
                Status.UNKNOWN,
                f"bye status unknown — NFL schedule unavailable for "
                f"{self.season} week {self.week}",
                self.snapshot_as_of,
            )
        # Team defenses have no injury designation; the bye check above is
        # their only gate.
        if position == "DEF":
            return PlayerStatus(Status.ACTIVE, "team defense", self.snapshot_as_of)
        return PlayerStatus(Status.ACTIVE, "no injury designation", self.snapshot_as_of)


def may_publish_confidence(a: PlayerStatus, b: PlayerStatus) -> tuple[bool, str | None]:
    """The gate on every published probability (CLAUDE.md principle 1).

    Confidence prints only when both players are ACTIVE: that is the regime the
    calibration evidence supports (backtest: 5/5 buckets calibrated, ECE 3.1%).
    QUESTIONABLE blocks the number too — v0.2 has no calibrated model of how a
    Q designation discounts availability, so printing one would be a guess.
    """
    for status in (a, b):
        if status.status is Status.UNKNOWN:
            return False, status.reason
        if status.status is Status.QUESTIONABLE:
            return False, f"availability in doubt ({status.reason})"
        if status.status is Status.OUT:
            return False, f"not a live head-to-head ({status.reason})"
    return True, None


# --------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------- #

def load_schedule_weeks(raw_dir: Path, season: str) -> dict[int, frozenset[str]] | None:
    """week -> teams playing that week, from the cached schedule. None if not cached."""
    path = Path(raw_dir) / "schedule" / f"nfl_regular_{season}.json"
    if not path.is_file():
        return None
    try:
        games = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    weeks: dict[int, set[str]] = {}
    for game in games if isinstance(games, list) else []:
        if not isinstance(game, dict):
            continue
        week = game.get("week")
        if not isinstance(week, int):
            continue
        for side in ("home", "away"):
            team = game.get(side)
            if isinstance(team, str) and team:
                weeks.setdefault(week, set()).add(team)
    return {week: frozenset(teams) for week, teams in weeks.items()}


def bye_teams_for_week(
    schedule_weeks: Mapping[int, frozenset[str]] | None, week: int
) -> frozenset[str] | None:
    """Teams NOT playing in ``week``. None when the schedule can't say."""
    if not schedule_weeks or week not in schedule_weeks:
        return None
    all_teams = frozenset().union(*schedule_weeks.values())
    return all_teams - schedule_weeks[week]


def load_week_availability(raw_dir: Path, season: str, week: int) -> WeekAvailability:
    """Availability for (season, week) from the snapshot taken that week.

    Only the ``regular`` season snapshot for that exact week counts. If it does
    not exist (historical seasons, or ingestion not yet run this week), every
    classification is UNKNOWN — the report then gates rather than guesses.
    """
    schedule_weeks = load_schedule_weeks(raw_dir, season)
    byes = bye_teams_for_week(schedule_weeks, week)

    path = snapshot_path(raw_dir, season, "regular", week)
    if not path.is_file():
        return WeekAvailability(season=str(season), week=week, snapshot_as_of=None,
                                statuses=None, bye_teams=byes)
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        statuses = snapshot["statuses"]
        if not isinstance(statuses, dict):
            raise ValueError("statuses is not an object")
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return WeekAvailability(season=str(season), week=week, snapshot_as_of=None,
                                statuses=None, bye_teams=byes)
    return WeekAvailability(
        season=str(season),
        week=week,
        snapshot_as_of=snapshot.get("as_of"),
        statuses=statuses,
        bye_teams=byes,
    )
