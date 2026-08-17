"""Historical NFL injury reports, so the shipping gate can finally be tested.

THE PROBLEM THIS SOLVES. The product only publishes a confidence when both
players are confirmed active, and that gate has never been backtested — weekly
availability snapshots can only be captured live and ours start this season. So
the only calibration number we may honestly publish is the UNCONDITIONAL one
(ECE 7.2%, 1 of 6 buckets calibrated), which measures a model with no gate at
all. The availability-controlled table in reports/backtest.md is explicitly a
diagnostic, not a result, because it conditions on an outcome nobody knows at
call time ("both players actually scored").

An injury REPORT is different: it is published before kickoff, so conditioning
on it is legitimate. nflverse archives them per season.

  https://github.com/nflverse/nflverse-data — CC-BY-4.0, attribution required.
  injuries_{season}.csv, plain HTTPS, no auth, no key, ~665KB for 2018.

WHAT THIS DELIBERATELY DOES NOT PROVIDE. There is no function here that emits a
week in the shape ``engine.availability`` reads. That consumer treats a player
missing from a snapshot as UNKNOWN, but an injury report lists who is in doubt,
so a player missing from IT is fine. Handing a report-shaped snapshot to that
loader would invert the meaning and gate away nearly every call while looking
like it worked. ``gate_backtest.apply_gate`` carries the correct reading.

Nothing derived here is ever written into ``data/raw/availability/`` either:
that store holds snapshots captured live and is the one dataset the product
cannot rebuild.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import requests

RELEASE = ("https://github.com/nflverse/nflverse-data/releases/download/"
           "injuries/injuries_{season}.csv")
# Credit required by CC-BY-4.0 wherever a number derived from this appears.
ATTRIBUTION = "Injury history: nflverse (nflverse-data), CC-BY-4.0."

# The report designation, mapped onto the engine's own vocabulary. Anything
# that is not a designation at all means the player appeared on no report that
# week, which is the league's way of saying nothing was wrong with him.
OUT_WORDS = {"out", "injured reserve", "ir", "physically unable to perform",
             "pup", "doubtful", "suspended"}
DOUBT_WORDS = {"questionable", "limited"}


@dataclass(frozen=True)
class InjuryWeek:
    """One week of report designations, keyed by nflverse gsis id."""

    season: str
    week: int
    by_gsis: dict[str, str]      # gsis_id -> normalised designation
    teams: dict[str, str]        # gsis_id -> team abbreviation


def fetch(season: str, cache_dir: Path,
          session: requests.Session | None = None) -> Path:
    """Download one season's archive, or reuse the cached copy.

    A completed season's injury history is final, so it is cached forever —
    the same rule the rest of the ingest layer applies to finished seasons.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"injuries_{season}.csv"
    if path.is_file() and path.stat().st_size > 0:
        return path
    client = session or requests
    response = client.get(RELEASE.format(season=season), timeout=60)
    response.raise_for_status()
    path.write_text(response.text, encoding="utf-8")
    return path


def _normalise(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text in OUT_WORDS:
        return "Out"
    if text in DOUBT_WORDS:
        return "Questionable"
    return None


def load_weeks(path: Path, season: str) -> dict[int, InjuryWeek]:
    """Parse the archive into one entry per week.

    ``report_status`` is the game-day designation; ``practice_status`` is only
    a practice note and is deliberately ignored — treating a limited practice
    as a game designation would invent doubt the league never published.
    """
    weeks: dict[int, dict[str, str]] = {}
    teams: dict[int, dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season") or "") != str(season):
                continue
            try:
                week = int(row.get("week") or 0)
            except ValueError:
                continue
            gsis = (row.get("gsis_id") or "").strip()
            if not week or not gsis:
                continue
            teams.setdefault(week, {})[gsis] = (row.get("team") or "").strip()
            designation = _normalise(row.get("report_status"))
            if designation:
                weeks.setdefault(week, {})[gsis] = designation
    return {
        week: InjuryWeek(season=str(season), week=week,
                         by_gsis=weeks.get(week, {}), teams=teams.get(week, {}))
        for week in sorted(teams)
    }
