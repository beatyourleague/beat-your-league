"""Calibration: does a stated 64% actually hit ~64% of the time?

CLAUDE.md principle 1 is the whole reason this file exists. A confidence number
is only worth publishing if it survives being checked against outcomes, so this
module produces the check — buckets, hit rates, honest intervals, Brier score —
and reports/backtest.md prints whatever it says, good or bad.

Ties are excluded from hit rates throughout: a call where both players scored
identically was not decided, so counting it either way would be a thumb on the
scale. Tie counts are reported separately.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from engine.decisions import HIT, MISS, StartSitCall

# Confidence is >= 0.5 by construction (the engine recommends its own favorite),
# so the buckets start at 0.50. The 50-60 bucket is the coin-flip band the
# product's Regret Score lives in.
DEFAULT_EDGES: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 0.90, 1.0001)


@dataclass(frozen=True)
class Bucket:
    low: float
    high: float
    graded: int
    ties: int
    hits: int
    misses: int

    @property
    def decided(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.decided if self.decided else None

    @property
    def label(self) -> str:
        return f"{self.low * 100:.0f}-{self.high * 100:.0f}%"


@dataclass(frozen=True)
class BucketReport:
    """A bucket plus the stated confidence it is being held to."""

    bucket: Bucket
    stated_mean: float | None
    ci_low: float | None
    ci_high: float | None

    @property
    def calibrated(self) -> bool | None:
        """True when the stated confidence falls inside the observed interval.

        None when the bucket is empty or has too few decided calls to say
        anything — reported as "too few to judge", never as a pass.
        """
        if self.stated_mean is None or self.ci_low is None or self.ci_high is None:
            return None
        if self.bucket.decided < MIN_DECIDED_TO_JUDGE:
            return None
        return self.ci_low <= self.stated_mean <= self.ci_high


# Below this many decided calls a bucket's hit rate is noise, and the report
# says so rather than declaring a pass or a failure on a handful of games.
MIN_DECIDED_TO_JUDGE = 30


def wilson_interval(hits: int, decided: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval — behaves at small n and at rates near 0 or 1,
    where the textbook normal interval produces impossible bounds."""
    if decided <= 0:
        return None
    phat = hits / decided
    denominator = 1 + z ** 2 / decided
    center = (phat + z ** 2 / (2 * decided)) / denominator
    spread = (
        z
        * math.sqrt(phat * (1 - phat) / decided + z ** 2 / (4 * decided ** 2))
        / denominator
    )
    return max(0.0, center - spread), min(1.0, center + spread)


def bucket_calls(
    calls: Iterable[StartSitCall], edges: Sequence[float] = DEFAULT_EDGES
) -> list[BucketReport]:
    """Group calls into confidence buckets and measure each one."""
    calls = list(calls)
    reports: list[BucketReport] = []
    for low, high in zip(edges, edges[1:]):
        members = [c for c in calls if low <= c.confidence < high]
        hits = sum(1 for c in members if c.outcome == HIT)
        misses = sum(1 for c in members if c.outcome == MISS)
        ties = sum(1 for c in members if c.outcome not in (HIT, MISS))
        bucket = Bucket(
            low=low,
            high=min(high, 1.0),
            graded=len(members),
            ties=ties,
            hits=hits,
            misses=misses,
        )
        decided_members = [c for c in members if c.outcome in (HIT, MISS)]
        stated_mean = (
            sum(c.confidence for c in decided_members) / len(decided_members)
            if decided_members
            else None
        )
        interval = wilson_interval(hits, bucket.decided)
        reports.append(
            BucketReport(
                bucket=bucket,
                stated_mean=stated_mean,
                ci_low=interval[0] if interval else None,
                ci_high=interval[1] if interval else None,
            )
        )
    return reports


def brier_score(calls: Iterable[StartSitCall]) -> float | None:
    """Mean squared error of the stated probabilities. Lower is better.

    Reference points for a binary forecast: 0.25 is a constant 50% guess;
    below that means the numbers carry information.
    """
    decided = [c for c in calls if c.outcome in (HIT, MISS)]
    if not decided:
        return None
    return sum(
        (c.confidence - (1.0 if c.outcome == HIT else 0.0)) ** 2 for c in decided
    ) / len(decided)


def expected_calibration_error(
    reports: Sequence[BucketReport],
) -> float | None:
    """Weighted average gap between stated confidence and observed hit rate."""
    total = sum(r.bucket.decided for r in reports)
    if total == 0:
        return None
    error = 0.0
    for report in reports:
        rate = report.bucket.hit_rate
        if rate is None or report.stated_mean is None:
            continue
        error += report.bucket.decided * abs(report.stated_mean - rate)
    return error / total


def resolution_check(calls: Iterable[StartSitCall]) -> tuple[float | None, float | None]:
    """Hit rate of the most confident decile vs the least confident decile.

    Calibration alone is not skill: a model that says 50% on everything is
    perfectly calibrated and useless. If the top decile does not out-hit the
    bottom decile, the confidence number is not sorting anything.
    """
    decided = sorted(
        (c for c in calls if c.outcome in (HIT, MISS)), key=lambda c: c.confidence
    )
    if len(decided) < 20:
        return None, None
    size = max(1, len(decided) // 10)
    bottom = decided[:size]
    top = decided[-size:]
    return (
        sum(1 for c in bottom if c.outcome == HIT) / len(bottom),
        sum(1 for c in top if c.outcome == HIT) / len(top),
    )
