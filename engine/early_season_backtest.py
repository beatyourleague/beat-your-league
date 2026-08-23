"""The early-season arm — weeks 2-3, prior-season seeded. Preregistered.

Method: ``reports/early-season-method.md``, frozen by commit BEFORE this runner
was first executed. Reproduce with ``python -m engine.early_season_backtest``.

Everything statistical is imported from the parent harness
(``engine.nflverse_backtest``) — same universe, same rosters, same gate, same
bucket verdicts, same grade rule — so the arm cannot drift into grading the
same shape of call a second way. The only new ingredient is the seed:
``ProjectionModel(prior_self=..., prior_self_weight=LAMBDA)``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.calibration import brier_score
from engine.decisions import StartSitCall, summarize
from engine.nflverse_backtest import (GRADE_MEANING, INJURY_DIR, LEAGUE_SIZE,
                                      RAW_DIR, REPO_ROOT, SEASONS, TEMPLATE_T1,
                                      BacktestError, calls_for_season, evaluate)
from engine.scoring import preset
from ingest.injuries import fetch as fetch_injuries
from ingest.injuries import load_weeks

# §2 of the method: fixed before any output. The headline is 0.5 no matter
# which sensitivity number looks best.
HEADLINE_LAMBDA = 0.5
SENSITIVITY_LAMBDAS = (0.25, 1.0)
EARLY_WEEKS = (2, 3)
SEEDS = tuple(range(20))
# §4's precision clause: a bucket whose clustered 95% interval spans more than
# this many percentage points is undecided, never calibrated — with only 22
# clusters, agreement inside an enormous interval is not evidence.
MAX_INTERVAL_WIDTH_PP = 15.0
OUT_PATH = REPO_ROOT / "reports" / "early-season-backtest.md"


def _assert_gate_reports(season: str, injury_dir: Path) -> None:
    """§3: the W-1 report must EXIST for every graded week, asserted per
    season rather than trusted from prose — a missing report now fails closed
    in the harness (no snapshot, zero calls), and a season silently
    contributing zero gated weeks would look like a quiet season instead of a
    broken input."""
    weeks = load_weeks(fetch_injuries(season, injury_dir), season)
    for graded in EARLY_WEEKS:
        report = weeks.get(graded - 1)
        if report is None or not report.teams:
            raise BacktestError(
                f"{season}: no week-{graded - 1} injury report — week {graded} "
                f"cannot be graded on the Tuesday information set")


def arm_calls(season: str, raw_dir: Path, injury_dir: Path, rule,
              lam: float, seed: int = 0) -> list[StartSitCall]:
    _assert_gate_reports(season, injury_dir)
    return calls_for_season(season, raw_dir, injury_dir, rule,
                            template=TEMPLATE_T1, league_size=LEAGUE_SIZE,
                            seed=seed, weeks=EARLY_WEEKS,
                            prior_self_weight=lam)


def _sweep(seasons, raw_dir, injury_dir, rule, lam, seed=0):
    calls: list[StartSitCall] = []
    per_season: dict[str, int] = {}
    for season in seasons:
        try:
            got = arm_calls(season, raw_dir, injury_dir, rule, lam, seed)
        except (BacktestError, OSError) as exc:
            print(f"  {season}: skipped — {exc}", file=sys.stderr)
            continue
        per_season[season] = len(got)
        calls.extend(got)
    return calls, per_season


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="*", default=list(SEASONS))
    parser.add_argument("--scoring", default="ppr")
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--injuries", type=Path, default=INJURY_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--skip-seeds", action="store_true",
                        help="skip the 20-seed stability sweep (debug only — "
                             "the published report must include it)")
    args = parser.parse_args(argv)
    rule = preset(args.scoring)

    print(f"headline: λ={HEADLINE_LAMBDA}, weeks {EARLY_WEEKS}", file=sys.stderr)
    calls, per_season = _sweep(args.seasons, args.raw, args.injuries, rule,
                               HEADLINE_LAMBDA)
    if not calls:
        print("no calls graded — nothing to report", file=sys.stderr)
        return 1
    ev = evaluate(calls, max_interval_width=MAX_INTERVAL_WIDTH_PP)
    summary = summarize(calls)

    # §8's effective-sample line, extended with the cross-week repeat share:
    # the seed barely moves between weeks 2 and 3, so the same head-to-heads
    # recur and the clustering has to carry that dependence.
    triples = {(c.started_id, c.alternative_id, c.slot) for c in calls}
    players_involved = {c.started_id for c in calls} | {c.alternative_id for c in calls}
    clusters = {(c.season, c.week) for c in calls}
    from collections import Counter
    per_cluster = Counter((c.season, c.week) for c in calls)
    week2 = {(c.season, c.roster_id, c.slot, c.started_id, c.alternative_id)
             for c in calls if c.week == EARLY_WEEKS[0]}
    week3 = [c for c in calls if c.week == EARLY_WEEKS[1]]
    repeats = sum(1 for c in week3
                  if (c.season, c.roster_id, c.slot, c.started_id,
                      c.alternative_id) in week2)
    repeat_share = repeats / len(week3) if week3 else 0.0
    counts = sorted(per_cluster.values())
    median_cluster = counts[len(counts) // 2] if counts else 0

    sens_lines = []
    for lam in SENSITIVITY_LAMBDAS:
        print(f"sensitivity: λ={lam}", file=sys.stderr)
        arm, _ = _sweep(args.seasons, args.raw, args.injuries, rule, lam)
        arm_ev = evaluate(arm, max_interval_width=MAX_INTERVAL_WIDTH_PP)
        arm_summary = summarize(arm)
        sens_lines.append(
            f"| λ = {lam} | {arm_summary.graded} | {arm_summary.hit_rate:.1%} "
            f"| {arm_ev.ece:.1%} | {arm_ev.resolution:.1f} | {arm_ev.judgeable} "
            f"| {arm_ev.calibrated} | {arm_ev.grade} |")

    spread_line = "(seed sweep skipped — debug run, not publishable)"
    if not args.skip_seeds:
        c_values = []
        for seed in SEEDS:
            print(f"seed {seed}", file=sys.stderr)
            arm, _ = _sweep(args.seasons, args.raw, args.injuries, rule,
                            HEADLINE_LAMBDA, seed)
            c_values.append(evaluate(
                arm, max_interval_width=MAX_INTERVAL_WIDTH_PP).calibrated)
        c_sorted = sorted(c_values)
        spread = max(c_values) - min(c_values)
        spread_line = (
            f"Seeds 0–{len(SEEDS) - 1}: C min {c_sorted[0]}, median "
            f"{c_sorted[len(c_sorted) // 2]}, max {c_sorted[-1]} — spread "
            f"{spread}{' (unstable: Grade A unreachable)' if spread > 1 else ''}.")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    seasons_table = "".join(f"| {s} | {n} |\n"
                            for s, n in sorted(per_season.items()))
    decision = {
        "A": "The seeded model ships for weeks 2–3, under the parent's Grade-A "
             "claim rules for those weeks.",
        "B": "The seeded model ships for weeks 2–3. Its figures may be stated "
             "as facts beside the failures; the banned words stay banned.",
        "C": "The seeded model ships for weeks 2–3. The numeral prints as a "
             "recorded prediction only — the same terms Grade C already "
             "imposes on weeks 4+ — with no accuracy implication anywhere.",
        "D": "No seeded confidence ships. Weeks 2–3 stay as they are, and this "
             "page is the published record of why.",
    }[ev.grade]

    body = f"""# Early-season confidence — weeks 2–3, prior-season seeded

Generated {stamp}. Method frozen in advance:
`reports/early-season-method.md`, committed before this runner's first
execution. Reproduce with `python -m engine.early_season_backtest`.
Configuration: λ = {HEADLINE_LAMBDA}, weeks {EARLY_WEEKS[0]} and {EARLY_WEEKS[1]},
seasons {args.seasons[0]}–{args.seasons[-1]}, PPR, {LEAGUE_SIZE} teams,
template T1, seed 0 headline. The availability gate is the parent's §6 with
correction C3: week W−1's injury report, carry-forward teams, fail closed.
Inertness check (§6.4): with the seed disabled, the parent's 2024 season
reproduced call-for-call (956 calls, identical hash) before this arm was run.

## Grade {ev.grade}

**{GRADE_MEANING[ev.grade]}.**

**The frozen decision (§5):** {decision}

## Headline

| | |
|---|---|
| Calls graded | {summary.graded} |
| Decided (ties excluded) | {summary.decided} |
| Ties | {summary.ties} |
| Hit rate | {summary.hit_rate:.1%} |
| Expected calibration error | {ev.ece:.1%} |
| Brier score | {brier_score(calls):.4f} (0.25 = a constant 50% guess) |
| Resolution — bottom decile | {ev.low_decile:.1%} |
| Resolution — top decile | {ev.high_decile:.1%} |
| Resolution spread | {ev.resolution:.1f} points |
| Judgeable buckets | {ev.judgeable} |
| Calibrated | {ev.calibrated} |

## Calibration

Same machinery as the parent report: cluster bootstrap over (season, week),
Wilson agreement required, a disagreement recorded as undecided and counted
against the calibrated total — plus this arm's preregistered precision clause:
a bucket whose clustered interval spans more than {MAX_INTERVAL_WIDTH_PP:.0f}
percentage points is undecided, never calibrated, because agreement inside an
enormous interval is not evidence. The cluster count here is small
({len(clusters)} season-weeks against the parent's 143), so intervals are wide;
that width is the honest price of the question, and the clusters column says
how much each bucket really rests on.

| Stated | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Clusters | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
{chr(10).join(
    f"| {m['low']:.0%}–{m['high']:.0%} | {m['graded']} | {m['decided']} "
    f"| {m['ties']} | {m['stated']:.1%} | {m['observed']:.1%} "
    f"| {m['interval'][0]:.0%}–{m['interval'][1]:.0%} | {m['clusters']} "
    f"| {m['verdict']} |" for m in ev.bucket_meta)}

## Effective sample

The calls are not independent, and this arm doubly so: the seed barely moves
between weeks 2 and 3, so many head-to-heads recur across the two graded
weeks. What the counts really rest on:

| | |
|---|---|
| Raw calls | {summary.graded} |
| Distinct (pick, alternative, slot) triples | {len(triples)} |
| Distinct players involved | {len(players_involved)} |
| Clusters (season, week) | {len(clusters)} |
| Median calls per cluster | {median_cluster} |
| Week-{EARLY_WEEKS[1]} calls repeating their week-{EARLY_WEEKS[0]} pairing | {repeat_share:.1%} |

If the distinct-triple or cluster counts diverge badly from the raw count, the
intervals are decoration — which is why the precision clause above exists.

## Seed stability

{spread_line}

## Sensitivity — reported, never substituted

The headline is λ = {HEADLINE_LAMBDA} regardless of what this table shows
(method §2: reporting a sensitivity arm as the result is the tuning the
preregistration forbids).

| Arm | Calls | Hit rate | ECE | Resolution | Judgeable | Calibrated | Grade |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{chr(10).join(sens_lines)}

## Per season

| Season | Calls |
| --- | ---: |
{seasons_table}
## Scope, stated

Week 1 is out of reach for any model: there is no week-0 injury report, so the
gate classifies everyone UNKNOWN and no number prints. Rookies and anyone
absent from the prior season's stat rows stay gated in weeks 2–3 — this arm
admits a player's own record, and a player without one is who the original
gate exists for. The run covers PPR, 12-team, template T1 only; other presets
and sizes ship no week 2–3 numbers until their own arms run. Every call whose
gate passes through the seed carries "last season counted in" on its row —
a seeded call that hides its seeding violates the preregistration.
"""
    args.out.write_text(body, encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)} ({len(calls)} calls, "
          f"grade {ev.grade})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
