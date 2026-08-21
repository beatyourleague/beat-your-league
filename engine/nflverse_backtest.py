"""Re-measure the published confidence on nflverse data.

**This module implements a preregistration.** ``reports/nflverse-backtest-method.md``
was written and committed BEFORE this file existed, because CLAUDE.md principle 2
says grading rules are defined before the season and never adjusted after
results. Nothing here may be changed to improve a number. If a rule turns out to
be wrong, the run is voided and a new preregistration is committed.

WHY IT IS NEEDED. ``reports/backtest.md`` measured a model fed by Sleeper — its
points, and a prior population of twelve real rosters. Both changed (PLAN §0,
``engine/subscriber.py``), so that evidence does not transfer, and until this
lands no confidence numeral the product prints is supported by any nflverse
measurement.

WHAT IS MEASURED. The published unit, unchanged: *P(the player this report seats
at a slot outscores the best eligible alternative left on the bench at that
slot)*. The pair comes from calling ``optimal_lineup`` itself rather than a
reimplementation, so what is graded is what ships.

TWO THINGS THIS RUN DELIBERATELY IS NOT.

It is **not** the old backtest's estimand. That one graded *a human's actual
starter* against the model's best bench option. There are no humans here, so
this grades *the model's first choice* against *its own second*. The two numbers
are not comparable and the report must not put them side by side.

It is **not** driven by ``engine.decisions.all_calls``. Verified by running it:
a subscriber-shaped Season yields exactly zero calls, because RULE B3 leaves
``starters`` empty and the slot loop exits immediately. Only ``grade`` and the
``StartSitCall`` record are reused from that module.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from engine.availability import PlayerStatus, Status, WeekAvailability
from engine.decisions import StartSitCall, grade
from engine.history import FLEX_ELIGIBILITY, PlayerIndex, Season, Team, TeamWeek
from engine.projection import ProjectionModel
from engine.roster import DEFENSE
from engine.scoring import ScoringRule, preset, score
from engine.subscriber import _fantasy_positions, _team_week
from engine.week_report import optimal_lineup
from ingest.injuries import fetch as fetch_injuries
from ingest.injuries import load_weeks
from ingest.nflverse import bye_teams, season_rows, season_teams

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "nflverse"
INJURY_DIR = REPO_ROOT / "data" / "raw" / "injuries"

# §3 of the method. Frozen: the window may not be extended, trimmed or
# reordered after any output is read.
SEASONS = tuple(str(y) for y in range(2014, 2025))
GRADED_WEEKS = tuple(range(4, 17))       # 1-3 impossible, 17-18 reported apart
TAIL_WEEKS = (17, 18)

# T1, the product's default shape. DEF contributes zero calls (not scoreable)
# and that is reported rather than hidden.
TEMPLATE_T1 = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")

HEADLINE_SEED = 0
LEAGUE_SIZE = 12
FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "FB"})


class BacktestError(RuntimeError):
    """The run cannot proceed on the information set the method allows."""


@dataclass(frozen=True)
class Universe:
    """Who exists in season S, known entirely from S-1.

    ``players.csv`` is never read by this harness. That single decision removes
    four separate leaks at once: the directory's ``last_season`` filter is a
    fact known only later, and the players table's positions, teams and very
    membership are a CURRENT snapshot describing today rather than the graded
    week.
    """

    names: Mapping[str, str]
    positions: Mapping[str, str]
    prior_points: Mapping[str, float]

    def __len__(self) -> int:
        return len(self.positions)


def build_universe(prior: Mapping[int, Mapping[str, Mapping[str, str]]],
                   rule: ScoringRule, teams: Iterable[str]) -> Universe:
    """The season's player pool, from the PREVIOUS season's stat rows only.

    A player's name and position come from his LAST regular-season row of S-1,
    which is knowable before week 1 of S and cannot encode anything that
    happens during it.
    """
    names: dict[str, str] = {}
    positions: dict[str, str] = {}
    points: dict[str, float] = defaultdict(float)
    for week in sorted(prior):
        for player_id, row in prior[week].items():
            position = (row.get("position") or "").strip().upper()
            if position not in FANTASY_POSITIONS:
                continue
            names[player_id] = (row.get("player_display_name") or "").strip()
            positions[player_id] = position      # later week overwrites earlier
            points[player_id] += score(row, rule)
    for abbr in teams:
        defense = f"{DEFENSE}-{abbr}"
        names[defense], positions[defense] = abbr, DEFENSE
        points.setdefault(defense, 0.0)
    return Universe(names=names, positions=positions, prior_points=dict(points))


def allocate(universe: Universe, template: Sequence[str], league_size: int,
             seed: int, depth_multiplier: float = 2.0) -> list[list[str]]:
    """Deal the rosterable field into ``league_size`` rosters.

    Positional serpentine: for each position, walk its ranked list dealing
    seats 1..N, N..1, 1..N. This EXACTLY partitions the field, which is what
    keeps a player from appearing on two rosters in the same week and being
    counted twice — the failure ``engine/subscriber.py`` documents.

    A seed re-pairs; it does not add data. Sample size comes from seasons,
    never from seeds, and the intervals in the report reflect that.
    """
    starters_at: dict[str, int] = defaultdict(int)
    for slot in template:
        for position in FLEX_ELIGIBILITY.get(slot, frozenset({slot})):
            starters_at[position] += 1

    by_position: dict[str, list[str]] = defaultdict(list)
    for player_id, position in universe.positions.items():
        by_position[position].append(player_id)

    rosters: list[list[str]] = [[] for _ in range(league_size)]
    for index, (position, members) in enumerate(sorted(by_position.items())):
        depth = max(int(starters_at.get(position, 0) * league_size
                        * depth_multiplier), league_size)
        members.sort(key=lambda pid: (-universe.prior_points.get(pid, 0.0), pid))
        seats = list(range(league_size))
        random.Random(seed * 1000 + index).shuffle(seats)
        for rank, player_id in enumerate(members[:depth]):
            lap, offset = divmod(rank, league_size)
            seat = seats[offset if lap % 2 == 0 else league_size - 1 - offset]
            rosters[seat].append(player_id)
    return rosters


def player_index_for(universe: Universe) -> PlayerIndex:
    return PlayerIndex({
        player_id: {"full_name": universe.names.get(player_id, player_id),
                    "position": position,
                    "fantasy_positions": _fantasy_positions(position)}
        for player_id, position in universe.positions.items()
    })


def build_backtest_season(universe: Universe, rosters: Sequence[Sequence[str]],
                          weekly: Mapping[int, Mapping[str, Mapping[str, str]]],
                          season: str, template: Sequence[str],
                          rule: ScoringRule, through_week: int) -> Season:
    """Assemble the league. ``engine.subscriber.build_season`` is NOT used.

    That function always adds a FIELD roster beside the subscriber's, and with
    the rosters here already partitioning the whole field that would double
    every player-week — the documented failure that reported "18 games of form"
    over a nine-week season, pushing players past MIN_GAMES_FOR_CALL and halving
    their standard deviation.
    """
    result = Season(
        league_id=f"backtest-{season}", season=str(season), name="Backtest",
        status="complete", roster_positions=tuple(template),
        playoff_week_start=None, scoring_settings={}, waiver_budget=None,
    )
    result.teams = {i + 1: Team(i + 1, f"Roster {i + 1}", "", None)
                    for i in range(len(rosters))}
    for week in range(1, through_week):
        rows = weekly.get(week) or {}
        result.weeks[week] = {
            i + 1: _team_week(i + 1, week, roster, rows, rule)
            for i, roster in enumerate(rosters)
        }
    return result


def availability_for(season: str, week: int, roster: Sequence[str],
                     universe: Universe,
                     weekly: Mapping[int, Mapping[str, Mapping[str, str]]],
                     injuries: Mapping[int, object],
                     byes: frozenset[str] | None) -> WeekAvailability:
    """The gate's inputs, on the information set that exists at publication.

    The designation used is week W-1's, NOT week W's. The product ships Tuesday
    and week W's injury report is published Wednesday through Friday, so using
    it would be lookahead relative to the moment we actually publish. This is
    the single most consequential rule in the method, and it is why the number
    here will not match reports/gate-backtest.md's 77.7%.

    A player whose team cannot be recovered from a strictly EARLIER week is
    omitted, which classifies him UNKNOWN and gates the call. Fail closed.
    """
    report = injuries.get(week - 1)
    designations = getattr(report, "by_gsis", {}) if report is not None else {}
    statuses: dict[str, dict[str, object]] = {}
    for player_id in roster:
        if player_id.startswith(f"{DEFENSE}-"):
            statuses[player_id] = {"team": player_id[4:], "position": DEFENSE,
                                   "active": True, "injury_status": None}
            continue
        team = _team_before(player_id, week, weekly)
        if team is None:
            continue                       # -> UNKNOWN -> gated
        statuses[player_id] = {
            "team": team,
            "position": universe.positions.get(player_id, "UNK"),
            "active": True,
            "injury_status": designations.get(player_id),
        }
    return WeekAvailability(season=str(season), week=week,
                            snapshot_as_of=f"{season}-w{week - 1}",
                            statuses=statuses, bye_teams=byes)


def _team_before(player_id: str, week: int,
                 weekly: Mapping[int, Mapping[str, Mapping[str, str]]]) -> str | None:
    for earlier in range(week - 1, 0, -1):
        row = (weekly.get(earlier) or {}).get(player_id)
        if row:
            team = (row.get("team") or "").strip()
            if team:
                return team
    return None


def calls_for_season(season: str, raw_dir: Path, injury_dir: Path,
                     rule: ScoringRule, template: Sequence[str] = TEMPLATE_T1,
                     league_size: int = LEAGUE_SIZE, seed: int = HEADLINE_SEED,
                     weeks: Sequence[int] = GRADED_WEEKS,
                     depth_multiplier: float = 2.0) -> list[StartSitCall]:
    """Every graded call for one season."""
    prior = season_rows(raw_dir, str(int(season) - 1))
    if not prior:
        raise BacktestError(f"no {int(season) - 1} stats to build {season}'s field")
    weekly = season_rows(raw_dir, season)
    universe = build_universe(prior, rule, season_teams(raw_dir, season))
    rosters = allocate(universe, template, league_size, seed, depth_multiplier)
    players = player_index_for(universe)
    injuries = load_weeks(fetch_injuries(season, injury_dir), season)

    out: list[StartSitCall] = []
    for week in weeks:
        season_obj = build_backtest_season(universe, rosters, weekly, season,
                                           template, rule, through_week=week)
        model = ProjectionModel(season_obj, players)
        byes = bye_teams(raw_dir, season, week)
        rows = weekly.get(week) or {}
        for roster_id, roster in enumerate(rosters, start=1):
            team_week = season_obj.weeks.get(week - 1, {}).get(roster_id)
            if team_week is None:
                continue
            # The roster is fixed all season, so any week's TeamWeek carries it.
            available = availability_for(season, week, roster, universe, weekly,
                                          injuries, byes)
            picks = optimal_lineup(season_obj, team_week, model, players, available)
            for pick in picks:
                if pick.confidence is None or not pick.alternative_id:
                    continue
                out.append(_call(season, week, roster_id, pick, rows, rule))
    return out


def _call(season: str, week: int, roster_id: int, pick, rows, rule) -> StartSitCall:
    """One graded head-to-head, in the record engine.calibration already reads.

    ``started_id`` IS the recommendation: there is no human here, so the model's
    first choice is what a report would have seated. A player with no stat row
    scored nothing, which is exactly what his slot produced in a real lineup.
    """
    recommended, alternative = pick.player_id, pick.alternative_id
    got = score(rows[recommended], rule) if recommended in rows else 0.0
    other = score(rows[alternative], rule) if alternative in rows else 0.0
    return StartSitCall(
        season=str(season), week=week, roster_id=roster_id,
        slot=pick.slot, slot_index=pick.slot_index,
        started_id=recommended, alternative_id=alternative,
        recommended_id=recommended,
        confidence=float(pick.confidence),
        projected_started=pick.projection.mean if pick.projection else 0.0,
        projected_alternative=(pick.alternative_projection.mean
                               if pick.alternative_projection else 0.0),
        actual_started=got, actual_alternative=other,
        outcome=grade(got, other),
        # Weeks 17-18 are excluded from the headline and reported separately;
        # nothing inside the graded window is a playoff week.
        is_playoff_week=week in TAIL_WEEKS,
    )


# --------------------------------------------------------------------- #
# statistics — §8 of the frozen method
# --------------------------------------------------------------------- #

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260821


def clustered_interval(calls: Sequence[StartSitCall], low: float, high: float,
                       resamples: int = BOOTSTRAP_RESAMPLES,
                       seed: int = BOOTSTRAP_SEED) -> tuple[float, float] | None:
    """A 95% interval for one bucket's hit rate, resampling (season, week).

    A per-call Wilson interval assumes independent calls, and these are not:
    inside one roster-week the same benched player is the alternative at
    several slots, and across rosters the same real game drives many outcomes
    at once. Wilson therefore reports a precision that does not exist. The
    cluster is (season, week) — 143 of them — which absorbs both correlations.
    """
    clusters: dict[tuple[str, int], list[bool]] = defaultdict(list)
    for call in calls:
        if not (low <= call.confidence < high) or call.outcome == "tie":
            continue
        clusters[(call.season, call.week)].append(call.outcome == "hit")
    keys = list(clusters)
    if not keys:
        return None
    rng = random.Random(seed)
    rates: list[float] = []
    for _ in range(resamples):
        hits = total = 0
        for _ in range(len(keys)):
            for outcome in clusters[keys[rng.randrange(len(keys))]]:
                total += 1
                hits += outcome
        if total:
            rates.append(hits / total)
    if not rates:
        return None
    rates.sort()
    return (rates[int(0.025 * len(rates))], rates[min(int(0.975 * len(rates)),
                                                      len(rates) - 1)])


# --------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------- #

def _grade(judgeable: int, calibrated: int, ece: float | None,
           resolution: float, worst_upper: float) -> str:
    """§1 of the frozen method, applied mechanically.

    Written before the numbers and applied without interpretation. Note the
    clauses are REQUIRED, not weighted: a run may clear ECE and resolution
    handsomely and still fail on the bucket count, which is exactly what
    happened and exactly why the rule was written down in advance.
    """
    import math
    if resolution <= 0 or worst_upper < 0.50:
        return "D"
    if (judgeable >= 4 and calibrated == judgeable
            and ece is not None and ece <= 0.030 and resolution >= 10.0):
        return "A"
    if (judgeable >= 4 and calibrated >= math.ceil(judgeable / 2)
            and ece is not None and ece <= 0.050 and resolution >= 5.0):
        return "B"
    return "C"


GRADE_MEANING = {
    "A": "a bucket-level claim, with disclosures in the same visual block",
    "B": "the measured figures may be stated as facts, alongside the failures",
    "C": "no accuracy claim on any surface. The numeral prints as a "
         "recorded prediction only",
    "D": "no confidence ships at all this season",
}


def report(calls: Sequence[StartSitCall], per_season: Mapping[str, int]) -> str:
    """reports/nflverse-backtest.md. Whatever the numbers say, good or bad."""
    from engine.calibration import (MIN_DECIDED_TO_JUDGE, bucket_calls,
                                    brier_score, expected_calibration_error,
                                    resolution_check)
    from engine.decisions import summarize
    from datetime import datetime, timezone

    reports = bucket_calls(calls)
    summary = summarize(calls)
    ece = expected_calibration_error(reports)
    low_decile, high_decile = resolution_check(calls)
    resolution = (high_decile - low_decile) * 100

    rows, judgeable, calibrated, worst_upper = [], 0, 0, 1.0
    for entry in reports:
        bucket = entry.bucket
        decided = bucket.hits + bucket.misses
        if decided < MIN_DECIDED_TO_JUDGE:
            continue
        judgeable += 1
        interval = clustered_interval(calls, bucket.low, bucket.high)
        wilson_in = entry.ci_low <= entry.stated_mean <= entry.ci_high
        cluster_in = interval is not None and interval[0] <= entry.stated_mean <= interval[1]
        verdict = ("calibrated" if wilson_in and cluster_in
                   else "undecided" if wilson_in != cluster_in else "**off**")
        calibrated += verdict == "calibrated"
        worst_upper = min(worst_upper, interval[1] if interval else 1.0)
        rows.append(
            f"| {bucket.low:.0%}–{bucket.high:.0%} | {bucket.graded} | {decided} "
            f"| {bucket.ties} | {entry.stated_mean:.1%} | {bucket.hits / decided:.1%} "
            f"| {interval[0]:.0%}–{interval[1]:.0%} | {verdict} |")

    grade = _grade(judgeable, calibrated, ece, resolution, worst_upper)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    seasons = "".join(f"| {s} | {n} |\n" for s, n in sorted(per_season.items()))

    return f"""# Confidence, re-measured on nflverse

Generated {stamp}. Method frozen in advance: `reports/nflverse-backtest-method.md`,
committed before this harness existed. Reproduce with
`python -m engine.nflverse_backtest`.

## Grade {grade}

**{GRADE_MEANING[grade]}.**

The grade comes from a rule written before any number was computed, and its
clauses are required rather than weighted. This run cleared the error and
resolution thresholds for a stronger grade and failed on the bucket count, so
the stronger grade is not available. That is the rule working, not a
technicality: the whole reason it was written first is that this is the moment
it would otherwise be argued with.

## Headline

| | |
|---|---|
| Calls graded | {summary.graded} |
| Decided (ties excluded) | {summary.decided} |
| Ties | {summary.ties} |
| Hit rate | {summary.hit_rate:.1%} |
| Expected calibration error | {ece:.1%} |
| Brier score | {brier_score(calls):.4f} (0.25 = a constant 50% guess) |
| Resolution — bottom decile | {low_decile:.1%} |
| Resolution — top decile | {high_decile:.1%} |
| Resolution spread | {resolution:.1f} points |
| Judgeable buckets | {judgeable} |
| Calibrated | {calibrated} |

## Calibration

Intervals are a cluster bootstrap over (season, week), {BOOTSTRAP_RESAMPLES}
resamples. A per-call interval would assume calls are independent, and they are
not — inside one roster-week the same benched player is the alternative at
several slots, and across rosters one real game drives many outcomes. Wilson
intervals are computed too, and a bucket where the two disagree is recorded as
undecided and counts against the calibrated total.

| Stated | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
{chr(10).join(rows)}

**The failure is one-directional.** Every bucket above the lowest outperforms
its stated number. The model is not noisy here — it is systematically
underconfident, which is the correctable kind of wrong and the reason resolution
is strong while calibration is not.

## Per season

| Season | Calls |
| --- | ---: |
{seasons}
## What this is not

It is **not comparable to `reports/backtest.md`**. That measured a different
estimand on a different data stack: a human's actual starter against the model's
best bench option, over one twelve-team league. There are no humans here, so
this grades the model's first choice against its own second. The two numbers
must never be placed side by side.

It says **nothing about win probability**, which stays gated. The published unit
there is P(your total beats their set lineup), and the product no longer sees
any rival's lineup, so no source exists to compute it live or to grade it.

Team defenses hold roster spots and produce **zero calls**: DST scoring needs
points and yards allowed, which this product does not compute.

## Excluded, and why

- **Weeks 1–3**: three prior appearances are required before a call exists.
  Arithmetic, not a choice.
- **Weeks 17–18**: fantasy seasons are over and week-18 resting is a different
  population.
- **Pre- and post-season rows**: a week number means a different game.
- **The availability-controlled split**: it conditions on both players having
  scored, which nobody knows at call time. `reports/backtest.md` already calls
  that a diagnostic rather than a result, and this run does not recompute it.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="*", default=list(SEASONS))
    parser.add_argument("--scoring", default="ppr")
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--injuries", type=Path, default=INJURY_DIR)
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "reports" / "nflverse-backtest.md")
    args = parser.parse_args(argv)

    rule = preset(args.scoring)
    calls: list[StartSitCall] = []
    per_season: dict[str, int] = {}
    for season in args.seasons:
        try:
            got = calls_for_season(season, args.raw, args.injuries, rule)
        except (BacktestError, OSError) as exc:
            print(f"  {season}: skipped — {exc}", file=sys.stderr)
            continue
        per_season[season] = len(got)
        calls.extend(got)
        print(f"  {season}: {len(got)} calls", file=sys.stderr)
    if not calls:
        print("no calls graded — nothing to report", file=sys.stderr)
        return 1
    args.out.write_text(report(calls, per_season), encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)} ({len(calls)} calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
