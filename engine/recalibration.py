"""Recalibrate the confidence number: fit on 2014-2019, grade on 2020-2024.

**This module implements a preregistration.** ``reports/recalibration-method.md``
was committed together with this file, before either was run.

The map (method §1) is ``p' = sigmoid(b * logit(p))``: one parameter, monotone,
symmetric, 0.5 fixed — so it never changes a pick, only the number printed
beside it. That is also why applying it to finished calls is exact. Calls come
from the parent's ``calls_for_season`` and grades from its ``evaluate``; the
setup arms are the setups runner's own ``ARMS``.

    .venv/bin/python -m engine.recalibration
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from engine.decisions import HIT, MISS, StartSitCall, summarize
from engine.nflverse_backtest import (GRADE_MEANING, INJURY_DIR, RAW_DIR,
                                      REPO_ROOT, BacktestError,
                                      calls_for_season, evaluate)
from engine.scoring import preset
from engine.setups_backtest import ARMS, arm_calls

OUT_PATH = REPO_ROOT / "reports" / "recalibration-backtest.md"
METHOD_PATH = "reports/recalibration-method.md"

# Method §2. Frozen.
FIT_SEASONS = tuple(str(y) for y in range(2014, 2020))
GRADE_SEASONS = tuple(str(y) for y in range(2020, 2025))
SEARCH = (0.25, 4.0)
TOLERANCE = 1e-4
CLIP = (0.001, 0.999)
# Method §3: arms re-graded under the headline's b. W17 is excluded (its one
# failing band went the opposite way).
RECAL_ARMS = tuple(arm for arm in ARMS if not arm.tail)
GRADE_RANK = {"D": 0, "C": 1, "B": 2, "A": 3}


def recalibrate(p: float, b: float) -> float:
    """Method §1's map."""
    p = min(max(p, CLIP[0]), CLIP[1])
    z = b * math.log(p / (1.0 - p))
    return 1.0 / (1.0 + math.exp(-z))


def log_likelihood(calls: Sequence[StartSitCall], b: float) -> float:
    total = 0.0
    for call in calls:
        if call.outcome not in (HIT, MISS):
            continue
        q = recalibrate(call.confidence, b)
        total += math.log(q if call.outcome == HIT else 1.0 - q)
    return total


def fit_b(calls: Sequence[StartSitCall]) -> float:
    """Maximum likelihood by golden-section search (method §2). The
    log-likelihood of a one-parameter logistic scaling is concave in b, so
    the search finds the maximum, deterministically."""
    lo, hi = SEARCH
    ratio = (math.sqrt(5) - 1) / 2
    c, d = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
    fc, fd = log_likelihood(calls, c), log_likelihood(calls, d)
    while hi - lo > TOLERANCE:
        if fc > fd:
            hi, d, fd = d, c, fc
            c = hi - ratio * (hi - lo)
            fc = log_likelihood(calls, c)
        else:
            lo, c, fc = c, d, fd
            d = lo + ratio * (hi - lo)
            fd = log_likelihood(calls, d)
    return (lo + hi) / 2


def apply(calls: Sequence[StartSitCall], b: float) -> list[StartSitCall]:
    return [replace(c, confidence=recalibrate(c.confidence, b)) for c in calls]


def decide(raw_grade: str, recal_grade: str, raw_ece: float | None,
           recal_ece: float | None) -> bool:
    """Method §4, all three clauses required."""
    return (recal_grade != "D"
            and GRADE_RANK[recal_grade] >= GRADE_RANK[raw_grade]
            and raw_ece is not None and recal_ece is not None
            and recal_ece < raw_ece)


def _cap(grade: str) -> str:
    return "B" if grade == "A" else grade      # seed 0 only; A unreachable


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _table(label: str, calls: Sequence[StartSitCall]) -> tuple[str, str, float | None]:
    ev = evaluate(calls)
    s = summarize(calls)
    grade = _cap(ev.grade)
    ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
    rate = f"{s.hits / s.decided:.1%}" if s.decided else "—"
    rows = "\n".join(ev.rows) or "| (no bucket reached 30 decided calls) |"
    text = f"""#### {label} — Grade {grade}

{s.graded} calls, {s.decided} decided, hit rate {rate}, ECE {ece}, {ev.judgeable} judgeable
bands, {ev.calibrated} calibrated, resolution {ev.resolution:.1f} points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
{rows}
"""
    return text, grade, ev.ece


def _collect(fn, seasons) -> list[StartSitCall] | None:
    out: list[StartSitCall] = []
    for season in seasons:
        try:
            out.extend(fn(season))
        except (BacktestError, OSError) as exc:
            print(f"  {season}: FAILED — {exc}", file=sys.stderr)
            return None
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--injuries", type=Path, default=INJURY_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)
    rule = preset("ppr")

    def headline(season: str) -> list[StartSitCall]:
        return calls_for_season(season, args.raw, args.injuries, rule)

    fit_calls = _collect(headline, FIT_SEASONS)
    grade_calls = _collect(headline, GRADE_SEASONS)
    if fit_calls is None or grade_calls is None:
        return 1          # method §6: a partial window is a different measurement
    b = fit_b(fit_calls)
    print(f"  b = {b:.4f}", file=sys.stderr)

    raw_text, raw_grade, raw_ece = _table("Raw, 2020–2024", grade_calls)
    rec_text, rec_grade, rec_ece = _table("Recalibrated, 2020–2024", apply(grade_calls, b))
    ships = decide(raw_grade, rec_grade, raw_ece, rec_ece)

    arm_sections, arm_rows = [], []
    for arm in RECAL_ARMS:
        calls = _collect(lambda s: arm_calls(arm, s, args.raw, args.injuries),
                         GRADE_SEASONS)
        if calls is None:
            return 1
        a_raw, g_raw, e_raw = _table(f"{arm.key} raw", calls)
        a_rec, g_rec, e_rec = _table(f"{arm.key} recalibrated", apply(calls, b))
        arm_rows.append(f"| {arm.key} | {arm.setting}: {arm.value} | {g_raw} "
                        f"| {e_raw:.1%} | {g_rec} | {e_rec:.1%} |"
                        if e_raw is not None and e_rec is not None else
                        f"| {arm.key} | {arm.setting}: {arm.value} | {g_raw} | — | {g_rec} | — |")
        arm_sections.append(f"### {arm.key} — {arm.setting}: {arm.value}\n\n{a_raw}\n{a_rec}")
        print(f"  {arm.key}: raw {g_raw}, recalibrated {g_rec}", file=sys.stderr)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verdict = ("**SHIPS.** All three clauses of method §4 hold: reports apply the map in "
               "weeks 4–16, in every setting whose recalibrated grade is not D."
               if ships else
               "**DOES NOT SHIP.** At least one clause of method §4 fails; the product "
               "keeps the raw number.")
    report = f"""# Recalibration, fitted on 2014–2019 and graded on 2020–2024

Generated {stamp} from commit `{_sha()}`. Method frozen in advance:
`{METHOD_PATH}`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.recalibration`.

The map is `p' = σ(b · logit(p))`: it keeps every pick and changes only the
number printed beside it. `b` was fitted on {len(fit_calls)} calls from
2014–2019 and never saw 2020–2024.

## Decision

- **b = {b:.4f}** (log-likelihood on the fit seasons: {log_likelihood(fit_calls, b):.1f}
  at b, {log_likelihood(fit_calls, 1.0):.1f} at b = 1).
- Headline on 2020–2024: raw **Grade {raw_grade}** (ECE {raw_ece:.1%}),
  recalibrated **Grade {rec_grade}** (ECE {rec_ece:.1%}).
- {verdict}

{GRADE_MEANING[rec_grade].capitalize()} — at the recalibrated grade.

## Headline, 2020–2024

{raw_text}
{rec_text}
## Setup arms, 2020–2024, same b

| Arm | Setting | Raw grade | Raw ECE | Recalibrated grade | Recalibrated ECE |
|---|---|---|---|---|---|
{chr(10).join(arm_rows)}

Weeks 17–18 and weeks 2–3 are not recalibrated (method §3).

{chr(10).join(arm_sections)}"""
    args.out.write_text(report, encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
