"""Last season, all season (reports/anchor-method.md) — the code promises.

The clauses that are properties of CODE rather than of a run: the switch is
inert at 0.0, it only ever touches weeks 4-16, it moves the projection and
never the publish gate, and a rookie is projected exactly as before.
"""

from __future__ import annotations

from engine.anchor_backtest import (Pair, decide_headline, decide_setup,
                                    sign_test, tally)
from engine.projection import ProjectionModel
from test_early_season import _players, _season


def test_the_switch_is_inert_at_zero() -> None:
    season, players = _season(weeks=6), _players()
    frozen = ProjectionModel(season, players).project("p1", 7)
    off = ProjectionModel(season, players, prior_self={"p1": [30.0] * 16},
                          late_self_weight=0.0).project("p1", 7)
    assert off == frozen


def test_it_moves_the_projection_in_weeks_4_to_16_only() -> None:
    season, players = _season(weeks=17), _players()
    frozen = ProjectionModel(season, players)
    seeded = ProjectionModel(season, players, prior_self={"p1": [30.0] * 16},
                             late_self_weight=0.25)
    for week in (4, 10, 16):
        assert seeded.project("p1", week).mean > frozen.project("p1", week).mean
    for week in (2, 3, 17, 18):
        assert seeded.project("p1", week) == frozen.project("p1", week)


def test_it_is_never_evidence_for_the_publish_gate() -> None:
    """Method §2.1: the call population is the shipped one, and no row
    carries the 'last season counted in' flag in weeks 4-16."""
    season, players = _season(weeks=5), _players()
    got = ProjectionModel(season, players, prior_self={"p1": [30.0] * 16},
                          late_self_weight=0.25).project("p1", 6)
    assert got.seeded_games == 0.0
    assert got.evidence == got.games == 5


def test_a_rookie_is_projected_exactly_as_shipped() -> None:
    season, players = _season(weeks=6), _players()
    frozen = ProjectionModel(season, players).project("p1", 7)
    seeded = ProjectionModel(season, players, prior_self={},
                             late_self_weight=0.25).project("p1", 7)
    assert seeded == frozen


def test_the_early_seed_keeps_its_own_weight_in_weeks_2_and_3() -> None:
    season, players = _season(weeks=2), _players()
    both = ProjectionModel(season, players, prior_self={"p1": [30.0] * 16},
                           prior_self_weight=0.5, late_self_weight=0.25)
    early = ProjectionModel(season, players, prior_self={"p1": [30.0] * 16},
                            prior_self_weight=0.5)
    assert both.project("p1", 3) == early.project("p1", 3)


def test_the_decision_is_the_frozen_one() -> None:
    assert decide_headline(101, 100, "B") and not decide_headline(100, 100, "B")
    assert not decide_headline(200, 100, "C")
    assert decide_setup(5, 4, "C", True) and not decide_setup(5, 4, "D", True)
    assert not decide_setup(5, 4, "B", False)


def test_the_sign_test_and_tally() -> None:
    assert sign_test(0, 0) == 1.0
    assert abs(sign_test(5, 5) - 1.0) < 1e-12
    assert sign_test(15, 3) < 0.01
    pairs = [Pair("2020", 4, 1, 10, 12, True, (0, 0), (0, 0)),
             Pair("2020", 4, 2, 10, 8, True, (0, 0), (0, 0)),
             Pair("2020", 4, 3, 10, 10, True, (0, 0), (0, 0)),
             Pair("2020", 4, 4, 10, 30, False, (0, 0), (0, 0))]
    assert tally(pairs) == (1, 1, 1)
