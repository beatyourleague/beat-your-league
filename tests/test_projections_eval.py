"""Tests for the projections-feed evaluation (engine/projections_eval.py).

All offline: the feed is synthetic dicts, never the network. The properties
under test are the honesty-critical ones — a husk record must never become a
0.0 projection, and the paired grading must match the incumbent's own rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.decisions import HIT, MISS, StartSitCall
from engine.projections_eval import (feed_points, load_feed_week,
                                     paired_decisions)

SCORING = {"rush_yd": 0.1, "rec_yd": 0.1, "rec": 1.0, "rush_td": 6.0,
           "pass_yd": 0.04, "bonus_rec_rb": 0.0}


# --------------------------------------------------------------------- #
# feed_points: the husk rule
# --------------------------------------------------------------------- #

def test_stat_lines_times_league_scoring() -> None:
    record = {"rush_yd": 80.0, "rec": 4.0, "rec_yd": 30.0, "rush_td": 0.5}
    # 8.0 + 4.0 + 3.0 + 3.0 = 18.0
    assert feed_points(record, SCORING) == 18.0


def test_a_husk_is_no_projection_never_zero_points() -> None:
    """The archive's empty records carry only bookkeeping fields. Treating one
    as 'projected for 0.0' would fabricate a projection the feed never made —
    and silently win every head-to-head for the other player."""
    assert feed_points({"adp_dd_ppr": 1000.0}, SCORING) is None
    assert feed_points({}, SCORING) is None
    assert feed_points(None, SCORING) is None


def test_unscored_stats_contribute_nothing() -> None:
    # This league's bonus_rec_rb weight is 0 — the stat exists but scores 0,
    # and a record carrying ONLY such stats has no projection in this league.
    assert feed_points({"bonus_rec_rb": 6.7}, SCORING) is None
    # Alongside a scored stat, the zero-weight line adds nothing.
    assert feed_points({"rush_yd": 50.0, "bonus_rec_rb": 6.7}, SCORING) == 5.0


def test_unknown_and_non_numeric_fields_are_ignored() -> None:
    record = {"rush_yd": 50.0, "team": "NO", "injury": None, "made_up_stat": 3.0}
    assert feed_points(record, SCORING) == 5.0


def test_precomputed_points_fields_are_never_scored() -> None:
    """pts_ppr etc. are outputs, not stat lines. A league whose scoring dict
    somehow carried a 'pts_ppr' key must not double-count them."""
    assert feed_points({"pts_ppr": 24.5}, {**SCORING, "pts_ppr": 1.0}) is None


def test_load_feed_week_absent_or_corrupt_is_none(tmp_path: Path) -> None:
    assert load_feed_week(tmp_path, "2018", 10) is None
    target = tmp_path / "projections" / "nfl_regular_2018_w10.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")
    assert load_feed_week(tmp_path, "2018", 10) is None
    target.write_text('{"123": {"rush_yd": 10}}', encoding="utf-8")
    assert load_feed_week(tmp_path, "2018", 10) == {"123": {"rush_yd": 10.0}}


# --------------------------------------------------------------------- #
# paired grading
# --------------------------------------------------------------------- #

def _call(week=5, started="s1", alt="b1", outcome=HIT,
          actual_started=15.0, actual_alt=10.0) -> StartSitCall:
    return StartSitCall(
        season="2018", week=week, roster_id=1, slot="RB", slot_index=1,
        started_id=started, alternative_id=alt, recommended_id=started,
        confidence=0.6, projected_started=12.0, projected_alternative=9.0,
        actual_started=actual_started, actual_alternative=actual_alt,
        outcome=outcome, is_playoff_week=False)


def test_paired_grading_agrees_and_disagrees_correctly() -> None:
    feed = {5: {
        # call A: feed backs the started player (10 > 5) — started scored more
        # (15 vs 10), so the feed hits alongside the model.
        "s1": {"rush_yd": 100.0}, "b1": {"rush_yd": 50.0},
        # call B: feed backs the BENCH player (90 > 20) and the bench player
        # actually scored more — feed right where the model was wrong.
        "s2": {"rush_yd": 20.0}, "b2": {"rush_yd": 90.0},
    }}
    calls = [
        _call(started="s1", alt="b1", outcome=HIT, actual_started=15, actual_alt=10),
        _call(started="s2", alt="b2", outcome=MISS, actual_started=8, actual_alt=22),
    ]
    result = paired_decisions(calls, "2018", feed, SCORING)
    assert result.calls == 2 and result.feed_no_opinion == 0
    assert result.model_hits == 1 and result.model_misses == 1
    assert result.feed_hits == 2 and result.feed_misses == 0
    assert result.feed_only_right == 1 and result.model_only_right == 0
    assert result.both_right == 1


def test_a_husk_on_either_side_is_no_opinion_not_a_forfeit() -> None:
    """If the feed lacks the bench player, it must not 'win' the head-to-head
    by default — the pair is excluded from its record entirely."""
    feed = {5: {"s1": {"rush_yd": 100.0}, "b1": {"adp_dd_ppr": 1000.0}}}
    result = paired_decisions([_call()], "2018", feed, SCORING)
    assert result.calls == 0
    assert result.feed_no_opinion == 1
    assert result.feed_hits == result.feed_misses == 0


def test_feed_tie_keeps_the_humans_starter() -> None:
    """Same rule as the incumbent: probability >= 0.5 keeps the starter, so a
    projection tie must not flip to the bench player."""
    feed = {5: {"s1": {"rush_yd": 50.0}, "b1": {"rush_yd": 50.0}}}
    # Starter actually outscored the bench: keeping the starter is a HIT.
    result = paired_decisions(
        [_call(actual_started=15, actual_alt=10)], "2018", feed, SCORING)
    assert result.feed_hits == 1 and result.feed_misses == 0


def test_actual_score_ties_are_excluded_like_the_incumbents() -> None:
    from engine.decisions import TIE
    feed = {5: {"s1": {"rush_yd": 60.0}, "b1": {"rush_yd": 50.0}}}
    result = paired_decisions(
        [_call(outcome=TIE, actual_started=10, actual_alt=10)],
        "2018", feed, SCORING)
    assert result.calls == 0 and result.ties_either == 1
