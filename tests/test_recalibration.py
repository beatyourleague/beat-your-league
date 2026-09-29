"""The recalibration may only implement its preregistration (synthetic data only)."""

from __future__ import annotations

import random

import engine.nflverse_backtest as parent
import engine.recalibration as recal
from engine.decisions import HIT, MISS, StartSitCall


def _call(p: float, outcome: str) -> StartSitCall:
    return StartSitCall(season="2015", week=5, roster_id=1, slot="WR", slot_index=3,
                        started_id="a", alternative_id="b", recommended_id="a",
                        confidence=p, projected_started=10.0,
                        projected_alternative=9.0, actual_started=10.0,
                        actual_alternative=9.0, outcome=outcome,
                        is_playoff_week=False)


def test_the_map_changes_no_pick() -> None:
    """Method §1: monotone, symmetric, 0.5 fixed, b = 1 the identity — so a
    call above 50% stays above it and no seat or recommendation moves."""
    grid = [i / 100 for i in range(1, 100)]
    for b in (0.5, 1.0, 1.3, 2.0):
        out = [recal.recalibrate(p, b) for p in grid]
        assert out == sorted(out)
        assert abs(recal.recalibrate(0.5, b) - 0.5) < 1e-12
        for p in grid:
            assert abs(recal.recalibrate(1 - p, b) - (1 - recal.recalibrate(p, b))) < 1e-9
            assert (recal.recalibrate(p, b) > 0.5) == (p > 0.5)
    assert all(abs(recal.recalibrate(p, 1.0) - p) < 1e-9 for p in grid)


def test_the_fit_recovers_a_known_correction() -> None:
    """Outcomes drawn from true odds g(p, 1.5) must fit b near 1.5."""
    rng = random.Random(7)
    calls = []
    for _ in range(20000):
        p = rng.uniform(0.5, 0.9)
        truth = recal.recalibrate(p, 1.5)
        calls.append(_call(p, HIT if rng.random() < truth else MISS))
    assert abs(recal.fit_b(calls) - 1.5) < 0.1


def test_the_decision_is_the_three_clauses() -> None:
    assert recal.decide("C", "B", 0.036, 0.020)
    assert recal.decide("C", "C", 0.036, 0.020)
    assert not recal.decide("C", "C", 0.036, 0.036)       # ECE must fall
    assert not recal.decide("B", "C", 0.036, 0.010)       # grade may not fall
    assert not recal.decide("C", "D", 0.036, 0.010)       # never ship a D


def test_the_split_never_lets_a_graded_season_into_the_fit() -> None:
    assert not set(recal.FIT_SEASONS) & set(recal.GRADE_SEASONS)
    assert set(recal.FIT_SEASONS) | set(recal.GRADE_SEASONS) == set(parent.SEASONS)
    assert recal.calls_for_season is parent.calls_for_season
    assert recal.evaluate is parent.evaluate
    assert not any(arm.tail for arm in recal.RECAL_ARMS)
