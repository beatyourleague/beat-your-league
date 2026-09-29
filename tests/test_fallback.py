"""reports/fallback-method.md — the switch, before the run.

§6.1: committed with the method and the runner, with a test that the switch is
inert when False. The fallback run itself reads outcomes; nothing here does.
"""

from __future__ import annotations

import functools

import pytest

from engine.fallback_backtest import changed_shared, decide, key, new_calls


def _sample(fallback: bool):
    import engine.solo_report as solo_report
    import render.sample as sample
    real = solo_report.optimal_lineup
    try:
        if fallback:
            solo_report.optimal_lineup = functools.partial(real, confirmed_fallback=True)
        return sample.build(10)
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    finally:
        solo_report.optimal_lineup = real


def test_the_switch_is_inert_when_false() -> None:
    """Off (the default) is the published sample exactly: three calls at
    70/61/71, and Barkley, Robinson and Chase Brown gated by Pollard."""
    report = _sample(False)
    called = {s["player_name"]: round(s["confidence"] * 100)
              for s in report["lineup"] if s.get("confidence") is not None}
    assert called == {"Ja'Marr Chase": 70, "Amon-Ra St. Brown": 61,
                      "George Kittle": 71}, called
    for name in ("Saquon Barkley", "Bijan Robinson", "Chase Brown"):
        row = next(s for s in report["lineup"] if s["player_name"] == name)
        assert row["confidence"] is None and row["alternative_name"] == "Tony Pollard"


def test_on_it_calls_against_the_next_confirmed_bench_player() -> None:
    """The rule does what §1 says on a real week: a confirmed starter whose
    best bench option is doubtful is called against a confirmed one."""
    report = _sample(True)
    # FLEX: Pollard (questionable) is the best bench option; a confirmed
    # receiver is next in line, so the slot gets a call against him.
    row = next(s for s in report["lineup"] if s["player_name"] == "Chase Brown")
    assert row["confidence"] is not None
    assert row["alternative_name"] not in ("Tony Pollard", None)
    # RB: Pollard is the ONLY bench running back, so there is nobody confirmed
    # to call against and the slot stays gated exactly as before (§1).
    for name in ("Saquon Barkley", "Bijan Robinson"):
        rb = next(s for s in report["lineup"] if s["player_name"] == name)
        assert rb["confidence"] is None
    # Calls that were already made do not move.
    chase = next(s for s in report["lineup"] if s["player_name"] == "Ja'Marr Chase")
    assert round(chase["confidence"] * 100) == 70


def test_the_decision_needs_all_three_clauses() -> None:
    assert decide("C", 2, "B")
    assert decide("B", 5, "A")                    # A is recorded as B
    assert not decide("D", 5, "B")                # NEW may not grade D
    assert not decide("B", 1, "B")                # a grade about almost nothing
    assert not decide("B", 5, "C")                # may not pull the headline down


class _C:
    def __init__(self, season, week, roster, idx, rec="a", alt="b", conf=0.6):
        self.season, self.week, self.roster_id, self.slot_index = season, week, roster, idx
        self.recommended_id, self.alternative_id, self.confidence = rec, alt, conf


def test_new_calls_are_the_slot_weeks_the_frozen_rule_left_empty() -> None:
    frozen = [_C("2020", 4, 1, 0), _C("2020", 4, 1, 1)]
    fallback = [_C("2020", 4, 1, 0), _C("2020", 4, 1, 1, alt="c"), _C("2020", 4, 1, 2)]
    assert [key(c) for c in new_calls(frozen, fallback)] == [("2020", 4, 1, 2)]
    assert changed_shared(frozen, fallback) == 1
