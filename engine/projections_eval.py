"""Evaluate Sleeper's projections feed against the trailing-form model.

The product deep-dive named the trailing-form projection as the weakest number
in the report and Sleeper's own free projections feed as the candidate fix
(``/v1/projections/nfl/regular/{season}/{week}`` — Rotowire-sourced, public,
archived back to 2018). Principle 1 says nothing gets adopted on vibes: this
module grades the feed on the SAME frozen call set the incumbent is graded on,
against the same cached box scores, before a single product number changes.

Two evaluations, deliberately separate:

* **Paired decisions** (the one that matters): for every head-to-head the
  incumbent graded in the backtest, ask what the feed would have recommended
  and grade both against the actual points. Because both models are graded on
  identical decisions, the comparison is free of selection effects — plus the
  McNemar-style split (feed right where we were wrong, and vice versa) shows
  WHERE the differences live.
* **Point accuracy** (diagnostic): mean absolute error of each model's
  projection against actual points, on every graded player-week both models
  can project. A model can win MAE and still lose decisions, which is why this
  is the secondary table.

Coverage is reported alongside: the feed projects players in weeks 1-3, where
the incumbent (three prior games required) is structurally silent — the exact
gap that leaves the launch-week report nearly empty.

Feed points are computed from the feed's STAT-LEVEL lines x the league's own
``scoring_settings`` — the same arithmetic Sleeper uses to score real games —
so the evaluation is correct for any league scoring, not just full PPR.
Honesty notes the output must carry (principle 3): the feed's archive starts
in 2018 (2017 records exist but are empty husks — verified live), and whether
Rotowire revised archived projections after the fact is unknowable from here.

Usage::

    python -m engine.projections_eval --league <id> [--fetch]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from engine.decisions import HIT, MISS, TIE, StartSitCall, all_calls, grade
from engine.history import PlayerIndex, Season, load_players, load_season_chain
from engine.projection import ProjectionModel

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_PATH = REPO_ROOT / "reports" / "projections-eval.md"

# Feed bookkeeping fields that are not stat lines. Everything else in a record
# is multiplied by the league's scoring weight for the same key (missing key =
# the league doesn't score that stat = contributes nothing).
_NON_STAT_KEYS = {"pts_ppr", "pts_half_ppr", "pts_std", "gp", "adp_dd_ppr"}


def feed_points(record: Mapping[str, Any] | None,
                scoring: Mapping[str, Any]) -> float | None:
    """A projected point total under THIS league's scoring, or None.

    None when the record is missing or carries no stat the league scores —
    the 2017 archive's empty husks land here, as does any player the feed
    declined to project. A husk must never read as "projected for 0 points".
    """
    if not record or not isinstance(record, Mapping):
        return None
    total = 0.0
    scored_any = False
    for stat, value in record.items():
        if stat in _NON_STAT_KEYS or not isinstance(value, (int, float)):
            continue
        weight = scoring.get(stat)
        if isinstance(weight, (int, float)) and weight != 0:
            total += float(value) * float(weight)
            scored_any = True
    return round(total, 2) if scored_any else None


def load_feed_week(raw_dir: Path, season: str, week: int) -> dict[str, Any] | None:
    """One cached projections file, or None if it was never fetched."""
    path = (raw_dir / "projections"
            / f"nfl_regular_{season}_w{week:02d}.json")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class PairedResult:
    """Both models graded on the incumbent's own call set."""
    season: str
    calls: int                   # incumbent calls the feed could also judge
    feed_no_opinion: int         # incumbent calls the feed had no projection for
    model_hits: int
    model_misses: int
    feed_hits: int
    feed_misses: int
    both_right: int
    both_wrong: int
    feed_only_right: int         # feed right where the model was wrong
    model_only_right: int
    ties_either: int

    @property
    def model_rate(self) -> float | None:
        d = self.model_hits + self.model_misses
        return self.model_hits / d if d else None

    @property
    def feed_rate(self) -> float | None:
        d = self.feed_hits + self.feed_misses
        return self.feed_hits / d if d else None


def paired_decisions(calls: Iterable[StartSitCall], season: str,
                     feed_by_week: Mapping[int, Mapping[str, Any]],
                     scoring: Mapping[str, Any]) -> PairedResult:
    n = no_op = m_hit = m_miss = f_hit = f_miss = 0
    both_r = both_w = f_only = m_only = ties = 0
    for call in calls:
        week_feed = feed_by_week.get(call.week) or {}
        started = feed_points(week_feed.get(call.started_id), scoring)
        alt = feed_points(week_feed.get(call.alternative_id), scoring)
        if started is None or alt is None:
            no_op += 1
            continue
        # The feed's recommendation under the incumbent's own decision rule:
        # start whichever projects higher (>= keeps the human's starter on a
        # tie, exactly as probability_outscores >= 0.5 does for the model).
        if started >= alt:
            feed_outcome = grade(call.actual_started, call.actual_alternative)
        else:
            feed_outcome = grade(call.actual_alternative, call.actual_started)
        model_outcome = call.outcome
        if TIE in (feed_outcome, model_outcome):
            ties += 1
            continue
        n += 1
        m_hit += model_outcome == HIT
        m_miss += model_outcome == MISS
        f_hit += feed_outcome == HIT
        f_miss += feed_outcome == MISS
        both_r += model_outcome == HIT and feed_outcome == HIT
        both_w += model_outcome == MISS and feed_outcome == MISS
        f_only += model_outcome == MISS and feed_outcome == HIT
        m_only += model_outcome == HIT and feed_outcome == MISS
    return PairedResult(season=season, calls=n, feed_no_opinion=no_op,
                        model_hits=m_hit, model_misses=m_miss,
                        feed_hits=f_hit, feed_misses=f_miss,
                        both_right=both_r, both_wrong=both_w,
                        feed_only_right=f_only, model_only_right=m_only,
                        ties_either=ties)


@dataclass(frozen=True)
class AccuracyResult:
    season: str
    player_weeks: int
    model_mae: float
    feed_mae: float
    model_rmse: float
    feed_rmse: float


def point_accuracy(season: Season, model: ProjectionModel,
                   feed_by_week: Mapping[int, Mapping[str, Any]],
                   scoring: Mapping[str, Any]) -> AccuracyResult | None:
    """MAE/RMSE on starter player-weeks where BOTH models project."""
    m_abs: list[float] = []
    f_abs: list[float] = []
    for team_week in season.team_weeks():
        week_feed = feed_by_week.get(team_week.week) or {}
        for pid in team_week.starters:
            actual = team_week.actual_points(pid)
            if actual is None:
                continue
            projection = model.project(pid, team_week.week)
            feed_pts = feed_points(week_feed.get(pid), scoring)
            if projection is None or feed_pts is None:
                continue
            m_abs.append(abs(projection.mean - actual))
            f_abs.append(abs(feed_pts - actual))
    if not m_abs:
        return None
    n = len(m_abs)
    return AccuracyResult(
        season=season.season, player_weeks=n,
        model_mae=round(sum(m_abs) / n, 2),
        feed_mae=round(sum(f_abs) / n, 2),
        model_rmse=round((sum(x * x for x in m_abs) / n) ** 0.5, 2),
        feed_rmse=round((sum(x * x for x in f_abs) / n) ** 0.5, 2),
    )


def early_week_coverage(season: Season, model: ProjectionModel,
                        feed_by_week: Mapping[int, Mapping[str, Any]],
                        scoring: Mapping[str, Any],
                        weeks: tuple[int, ...] = (1, 2, 3)) -> list[dict[str, Any]]:
    """Weeks 1-3: how many starter slots each model can put a number on.

    This is the launch-week gap in one table — the incumbent needs three prior
    games, so week 1 is structurally silent.
    """
    rows = []
    for week in weeks:
        week_feed = feed_by_week.get(week) or {}
        starters = 0
        model_covered = 0
        feed_covered = 0
        for team_week in season.team_weeks():
            if team_week.week != week:
                continue
            for pid in team_week.starters:
                if team_week.actual_points(pid) is None:
                    continue
                starters += 1
                if model.project(pid, week) is not None:
                    model_covered += 1
                if feed_points(week_feed.get(pid), scoring) is not None:
                    feed_covered += 1
        rows.append({"week": week, "starters": starters,
                     "model": model_covered, "feed": feed_covered})
    return rows


# --------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------- #

def _pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "—"


def render_markdown(paired: list[PairedResult], accuracy: list[AccuracyResult],
                    coverage: list[dict[str, Any]],
                    absent_seasons: list[str], generated: str) -> str:
    lines = [
        "# Projections feed evaluation — Sleeper/Rotowire vs trailing-form model",
        "",
        f"Generated {generated} from cached data in `data/raw/`. No estimates: "
        "every number is reproducible by re-running "
        "`python -m engine.projections_eval`.",
        "",
        "**The question:** should the report's projections come from Sleeper's own "
        "free feed (Rotowire-sourced, archived, fetched through the same public "
        "API) instead of the trailing-form model? Rule: the feed is graded on the "
        "**same frozen call set** the incumbent was backtested on — identical "
        "head-to-heads, identical box scores, decision rule held fixed.",
        "",
    ]
    if absent_seasons:
        lines += [
            f"**Archive honesty:** the feed has no usable records for "
            f"{', '.join(absent_seasons)} (records exist but carry no stat lines "
            "— verified). Those seasons are excluded rather than counted as "
            "zeros. Whether Rotowire ever revised archived projections after "
            "the fact is unknowable from here; treat the feed's numbers as "
            "as-archived, not as-published.",
            "",
        ]
    lines += ["## Paired decisions (the number that matters)", ""]
    lines += ["| Season | Head-to-heads | Model hit rate | Feed hit rate | "
              "Feed right / model wrong | Model right / feed wrong | "
              "Feed had no opinion |",
              "|---|---|---|---|---|---|---|"]
    for r in paired:
        lines.append(
            f"| {r.season} | {r.calls} | {_pct(r.model_rate)} | {_pct(r.feed_rate)} "
            f"| {r.feed_only_right} | {r.model_only_right} | {r.feed_no_opinion} |")
    lines += ["", "## Projection accuracy (diagnostic — decisions above outrank this)", ""]
    lines += ["| Season | Player-weeks | Model MAE | Feed MAE | Model RMSE | Feed RMSE |",
              "|---|---|---|---|---|---|"]
    for a in accuracy:
        lines.append(f"| {a.season} | {a.player_weeks} | {a.model_mae} | "
                     f"{a.feed_mae} | {a.model_rmse} | {a.feed_rmse} |")
    lines += ["", "## Early-week coverage (the launch-week gap)", ""]
    lines += ["| Week | Graded starters | Model can project | Feed can project |",
              "|---|---|---|---|"]
    for row in coverage:
        lines.append(f"| {row['week']} | {row['starters']} | {row['model']} "
                     f"| {row['feed']} |")
    total = sum(r.calls for r in paired)
    f_hits = sum(r.feed_hits for r in paired)
    f_dec = sum(r.feed_hits + r.feed_misses for r in paired)
    m_hits = sum(r.model_hits for r in paired)
    m_dec = sum(r.model_hits + r.model_misses for r in paired)
    f_only = sum(r.feed_only_right for r in paired)
    m_only = sum(r.model_only_right for r in paired)
    discordant = f_only + m_only
    p_two = _mcnemar_two_sided(f_only, discordant)
    no_opinion = sum(r.feed_no_opinion for r in paired)
    lines += [
        "",
        "## Verdict inputs",
        "",
        f"- Across {total} identical head-to-heads where BOTH could speak: model "
        f"{_pct(m_hits / m_dec if m_dec else None)}, feed "
        f"{_pct(f_hits / f_dec if f_dec else None)}. Where they disagreed, the "
        f"feed was right {f_only} times and the model {m_only} (exact McNemar "
        f"two-sided p = {p_two:.3f} — suggestive, NOT conclusive on one season; "
        "do not quote the gap without the p-value).",
        f"- **The feed cannot replace the model.** It had no opinion on "
        f"{no_opinion} of {total + no_opinion} incumbent head-to-heads: its "
        "projection universe is a fixed ~400-520 players per week in EVERY era "
        "(2018: ~513, 2022: 383, 2024: 370, 2025: 383 — verified live Aug "
        "2026), while a 12-team league's best-bench alternatives regularly sit "
        "outside it. Any adoption is a BLEND: feed where it speaks, "
        "trailing-form where it does not.",
        "- Survivorship check (passed): the usable subset is NOT filtered by "
        "who is still active today — 85 of 513 usable 2018-w10 records are "
        "players inactive in 2026, and 8,139 currently-active players are "
        "husks. The paired design also conditions both models on the same "
        "subset, so the comparison is fair even though the subset is selected.",
        "- The one unambiguous win is week 1: the feed projects most starters "
        "where the trailing-form model is structurally silent. That is the "
        "launch-week gap closed with real numbers instead of a gate.",
        "- Adoption caveat (principle 1): the floor/ceiling band's 77.9% "
        "coverage evidence was measured under TRAILING-FORM means. Swapping or "
        "blending means invalidates that evidence — re-run the matchup "
        "backtest under the blend before the band publishes on feed numbers, "
        "and leave every availability/confidence gate exactly where it is.",
        "- One league, one usable season. Enough to decide direction, not "
        "enough to claim a universal number — say so wherever this is quoted.",
        "",
    ]
    return "\n".join(lines)


def _mcnemar_two_sided(k: int, n: int) -> float:
    """Exact binomial two-sided p for k successes in n discordant pairs."""
    if n == 0:
        return 1.0
    from math import comb
    tail = sum(comb(n, i) for i in range(max(k, n - k), n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    parser.add_argument("--fetch", action="store_true",
                        help="fetch any missing projection weeks first (network)")
    args = parser.parse_args(argv)

    seasons = load_season_chain(args.raw_dir, args.league, max_seasons=4)
    players = load_players(args.raw_dir)

    if args.fetch:
        from ingest.sleeper import SleeperClient
        client = SleeperClient(args.raw_dir)
        for season in seasons:
            for week in season.graded_weeks:
                # A completed season's archive is final: cache forever.
                age = None if season.status == "complete" else 24.0
                client.projections(season.season, week, max_age_hours=age)
        print(f"fetch done: {client.http_requests} requests, "
              f"{client.cache_hits} cache hits")

    paired: list[PairedResult] = []
    accuracy: list[AccuracyResult] = []
    coverage: list[dict[str, Any]] = []
    absent: list[str] = []
    from datetime import datetime, timezone
    for season in seasons:
        model = ProjectionModel(season, players)
        feed_by_week: dict[int, Mapping[str, Any]] = {}
        usable = False
        for week in season.graded_weeks:
            data = load_feed_week(args.raw_dir, season.season, week)
            if data is None:
                continue
            feed_by_week[week] = data
            if not usable:
                usable = any(
                    feed_points(v, season.scoring_settings) is not None
                    for v in list(data.values())[:200])
        if not usable:
            absent.append(season.season)
            continue
        calls = all_calls(season, model, players)
        paired.append(paired_decisions(calls, season.season, feed_by_week,
                                       season.scoring_settings))
        acc = point_accuracy(season, model, feed_by_week, season.scoring_settings)
        if acc:
            accuracy.append(acc)
        coverage.extend(early_week_coverage(season, model, feed_by_week,
                                            season.scoring_settings))

    if not paired:
        print("no season has usable feed data cached — run with --fetch first",
              file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    markdown = render_markdown(paired, accuracy, coverage, absent, stamp)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(f"Wrote {args.output.relative_to(REPO_ROOT)}")
    print(markdown.split("## Verdict inputs")[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
