"""Grade the lineup offenses the signup page added: two arms per offense.

Implements ``reports/lineup-shapes-method.md``, committed together with this
file before it ever ran, unchanged after the first output is read (CLAUDE.md
principle 2). Until an offense's grade is recorded in code, its reports print
no odds (``engine.subscriber.graded_slots``, contract C8).

The arms are DERIVED from ``engine.subscriber.LINEUP_SHAPES``: for every base
whose offense no arm has graded, the shape with a K and a DEF and the shape
with neither (method §1) — so what is graded is exactly what ships, and a base
added to the table later cannot ship odds without arms of its own. Every other
setting is the headline's: full PPR, 12 teams.

Nothing here computes a call or a grade of its own. Every call comes from the
parent's ``calls_for_season``, configured as the product ships today (context
arm AV, the anchor at 0.25 pseudo-games, the confirmed-alternative fallback —
the configuration ``engine/context_combos.py`` grades), every confidence passes
through the shipped recalibration (``run.solo.CONTEXT_B``), and every grade
comes from the parent's ``evaluate``, on the held-out 2020-2024 seasons, weeks
4-16. No existing run reads this module, so every published run reproduces
byte for byte.

    .venv/bin/python -m engine.shapes_backtest
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from engine.decisions import StartSitCall, summarize
from engine.nflverse_backtest import (GRADE_MEANING, INJURY_DIR, LEAGUE_SIZE,
                                      RAW_DIR, REPO_ROOT, BacktestError,
                                      calls_for_season, evaluate)
from engine.recalibration import GRADE_SEASONS, apply
from engine.scoring import preset
from engine.subscriber import LINEUP_SHAPES, graded_slots

OUT_PATH = REPO_ROOT / "reports" / "lineup-shapes-backtest.md"
METHOD_PATH = "reports/lineup-shapes-method.md"
SCORING = "ppr"
# The configuration the product ships in weeks 4-16 (run/solo.py: CONTEXT_ARM,
# ANCHOR_WEIGHT, CONFIRMED_FALLBACK) — method §2.
SHIPPED = {"confirmed_fallback": True, "late_self_weight": 0.25, "context": "AV"}


@dataclass(frozen=True)
class ShapeArm:
    key: str                    # the shape's code, as the ref and seat link carry it
    label: str
    template: tuple[str, ...]
    base: str                   # the offense this arm grades (method §3 decides per base)


def _arms() -> tuple[ShapeArm, ...]:
    """Method §1: for every base whose offense is ungraded, the shape with a K
    and a DEF, then the shape with neither, in the table's order."""
    arms = []
    for shape in LINEUP_SHAPES.values():
        if graded_slots(shape.slots):
            continue
        if shape.kicker == shape.defense:          # both, or neither
            arms.append(ShapeArm(shape.code, shape.label, shape.slots, shape.base))
    return tuple(arms)


SHAPE_ARMS = _arms()

# Method §3: an offense prints when BOTH its arms grade better than D.
def offense_decision(grades: Sequence[str]) -> str:
    if any(g == "D" for g in grades):
        return ("stays ungraded: no odds print in any variant of this lineup; the "
                "lineup, projections and plans still do")
    return "prints: odds print in every K/DEF variant of this lineup, as recorded predictions"


def arm_calls(arm: ShapeArm, season: str, raw_dir: Path,
              injury_dir: Path) -> list[StartSitCall]:
    return calls_for_season(season, raw_dir, injury_dir, preset(SCORING),
                            template=arm.template, league_size=LEAGUE_SIZE,
                            **SHIPPED)


def _signature(call: StartSitCall) -> tuple:
    return (call.season, call.week, call.roster_id, call.slot, call.started_id,
            call.alternative_id, round(call.confidence, 9), call.outcome)


def _cap(grade: str) -> str:
    return "B" if grade == "A" else grade


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def report(results: Sequence[tuple[ShapeArm, list[StartSitCall], dict[str, int]]],
           b: float) -> str:
    """The generated document (method §5). ``results`` carries each arm's RAW
    calls; the recalibration is applied here, once, the way the product does."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary, sections = [], []
    grades_by_base: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for arm, calls, per_season in results:
        shipped = apply(calls, b)
        ev = evaluate(shipped)
        grade = _cap(ev.grade)
        grades_by_base.setdefault(arm.base, []).append(grade)
        labels.setdefault(arm.base, arm.label)
        s = summarize(shipped)
        ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
        rate = f"{s.hits / s.decided:.1%}" if s.decided else "—"
        summary.append(
            f"| {arm.key} | {arm.label} | {s.graded} | {s.decided} | {rate} | {ece} "
            f"| {ev.judgeable} | {ev.calibrated} | {ev.resolution:.1f} | **{grade}** |")
        buckets = "\n".join(ev.rows) or "| (no bucket reached 30 decided calls) |"
        seasons = ", ".join(f"{k} {v}" for k, v in sorted(per_season.items()))
        sections.append(f"""### {arm.key} — {arm.label}

`{" ".join(arm.template)}`

**Grade {grade}: {GRADE_MEANING[grade]}.**

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
{buckets}

Calls per season: {seasons}.
""")
    decisions = "\n".join(
        f"- {labels[base]} ({base}): arms graded {' and '.join(grades)} — "
        f"{offense_decision(grades)}."
        for base, grades in grades_by_base.items())
    return f"""# Lineup shapes, graded one shape at a time

Generated {stamp} from commit `{_sha()}`. Method frozen in advance:
`{METHOD_PATH}`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.shapes_backtest`.

Each arm is one lineup shape for an offense the signup page offers that had no
grade (with a K and a DEF, and with neither), graded alone on 2020–2024,
weeks 4–16, full PPR, 12 teams, as the product ships
(context arm AV, anchor 0.25, confirmed fallback), every confidence through the
shipped recalibration (b = {b:.4f}).

## Decisions

{decisions}

An offense that prints does so once its grade is recorded in code (method §3).

## Summary

| Arm | Lineup | Calls | Decided | Hit rate | ECE | Judgeable | Calibrated | Resolution (pts) | Grade |
|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(summary)}

Grade A is unreachable in these runs by construction (seed 0 only). Hit rate
and ECE are measured facts about past seasons, not a claim that any number in
a report is right. The banned words stay banned at every grade here.

## By arm

{chr(10).join(sections)}"""


def run(arms: Sequence[ShapeArm], raw_dir: Path, injury_dir: Path,
        calls_fn: Callable[[ShapeArm, str, Path, Path], list[StartSitCall]] = arm_calls,
        ) -> list[tuple[ShapeArm, list[StartSitCall], dict[str, int]]] | None:
    """Every arm over every graded season, or None when any season fails —
    method §5: an arm graded on fewer seasons is a different measurement under
    the same name, so nothing is written."""
    results = []
    for arm in arms:
        calls: list[StartSitCall] = []
        per_season: dict[str, int] = {}
        for season in GRADE_SEASONS:
            try:
                got = calls_fn(arm, season, raw_dir, injury_dir)
            except (BacktestError, OSError) as exc:
                print(f"  {arm.key} {season}: FAILED — {exc}", file=sys.stderr)
                return None
            per_season[season] = len(got)
            calls.extend(got)
        print(f"  {arm.key}: {len(calls)} calls", file=sys.stderr)
        results.append((arm, calls, per_season))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--injuries", type=Path, default=INJURY_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)
    from run.solo import CONTEXT_B
    # Every arm, every time (method §6): nothing here grades a subset, because
    # a subset re-run is how a preferred result gets kept.
    results = run(SHAPE_ARMS, args.raw, args.injuries)
    if results is None:
        return 1
    args.out.write_text(report(results, CONTEXT_B), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
