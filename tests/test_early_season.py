"""The early-season seed (reports/early-season-method.md) — code promises.

The method's §6 lists what invalidates the exercise; the clauses that are
properties of CODE rather than of a run are pinned here: the seed is inert by
default (the parent run must not move), ``games`` keeps meaning real
current-season appearances, the gate moves to evidence, a rookie stays gated,
and a seeded call discloses itself on the row.
"""

from __future__ import annotations

import pytest

from engine.history import PlayerIndex, Season, TeamWeek
from engine.projection import (MIN_GAMES_FOR_CALL, Projection, ProjectionModel)


def _season(weeks: int = 1, players: int = 6) -> Season:
    season = Season(league_id="t", season="2024", name="t", status="in_season",
                    roster_positions=("QB", "RB"), playoff_week_start=None,
                    scoring_settings={}, waiver_budget=None)
    for week in range(1, weeks + 1):
        points = {f"p{i}": 8.0 + i for i in range(players)}
        team_week = TeamWeek(
            roster_id=1, week=week, matchup_id=1,
            starters=tuple(), starters_points=tuple(),
            players=tuple(points), players_points=points,
            points=0.0, appeared=frozenset(points),
        )
        season.weeks[week] = {1: team_week}
    return season


def _players(count: int = 6) -> PlayerIndex:
    return PlayerIndex({f"p{i}": {"full_name": f"P {i}", "position": "RB",
                                  "fantasy_positions": ["RB"]}
                        for i in range(count)})


def test_the_seed_is_inert_unless_both_inputs_are_supplied() -> None:
    """§6.4: the parent run must not move. Weight 0 with observations, and
    observations absent with weight set, must both reproduce the frozen
    model's numbers exactly."""
    season, players = _season(weeks=3), _players()
    frozen = ProjectionModel(season, players).project("p1", 4)
    for model in (
        ProjectionModel(season, players, prior_self={"p1": [20.0] * 17},
                        prior_self_weight=0.0),
        ProjectionModel(season, players, prior_self={}, prior_self_weight=0.5),
    ):
        got = model.project("p1", 4)
        assert got == frozen, "the seed moved the frozen model"
        assert got.seeded_games == 0.0


def test_seeding_moves_the_gate_but_never_the_games_count() -> None:
    """evidence = n + λ·m decides the gate; ``games`` stays the count of real
    current-season appearances, because it renders as 'form games' on buyer
    surfaces and last season must never masquerade as this one."""
    season, players = _season(weeks=2), _players()
    model = ProjectionModel(season, players, prior_self={"p1": [12.0] * 16},
                            prior_self_weight=0.5)
    projection = model.project("p1", 2)          # 1 real game
    assert projection.games == 1
    assert projection.seeded_games == pytest.approx(8.0)
    assert projection.evidence == pytest.approx(9.0)
    assert projection.confident_enough
    # Unseeded, the same week fails the gate — this is the whole point.
    bare = ProjectionModel(season, players).project("p1", 2)
    assert not bare.confident_enough


def test_a_player_with_no_prior_season_stays_gated_early() -> None:
    """A rookie has m = 0: evidence = n <= 2 in weeks 2-3, gate holds. The arm
    admits a player's own record; a player without one is who the original
    gate exists for."""
    season, players = _season(weeks=2), _players()
    model = ProjectionModel(season, players, prior_self={"p1": [12.0] * 16},
                            prior_self_weight=0.5)
    rookie = model.project("p2", 2)
    assert rookie.games == 1 and rookie.seeded_games == 0.0
    assert not rookie.confident_enough


def test_the_seeded_blend_uses_the_prior_seasons_own_mean() -> None:
    """One real 8-point game against sixteen 20-point prior games at half
    weight must land far nearer 20 than 8 — and never shrink toward zero when
    the positional prior is thin (the bug the k_blend guard exists for)."""
    season, players = _season(weeks=2, players=2), _players(2)
    model = ProjectionModel(season, players, prior_self={"p1": [20.0] * 16},
                            prior_self_weight=0.5)
    projection = model.project("p1", 2)
    # n=1 at 9.0 (p1 scores 8+1), w=8 at 20.0, K=4 positional (week-1 field).
    assert projection.active_mean > 14.0, projection.active_mean
    assert projection.evidence == pytest.approx(9.0)


def test_a_seeded_call_discloses_itself_on_the_row() -> None:
    """Method §5: any call whose gate passes through the seed says so where
    drivers render. The 'thin' flag is the per-row surface: with seeding it
    names last season instead of implying three real games exist."""
    from engine.week_report import optimal_lineup
    from engine.availability import WeekAvailability

    season, players = _season(weeks=2), _players()
    model = ProjectionModel(season, players,
                            prior_self={f"p{i}": [12.0 + i] * 16 for i in range(6)},
                            prior_self_weight=0.5)
    season.roster_positions = ("RB", "RB")
    team_week = season.weeks[1][1]
    availability = WeekAvailability(
        season="2024", week=2, snapshot_as_of="the week 1 injury report",
        statuses={f"p{i}": {"team": "KC", "position": "RB", "active": True,
                            "injury_status": None} for i in range(6)},
        bye_teams=frozenset())
    picks = optimal_lineup(season, team_week, model, players, availability,
                           week=2)
    called = [p for p in picks if p.confidence is not None]
    assert called, "seeding produced no call at all on a clean fixture"
    for pick in called:
        texts = [f["text"] for f in pick.flags]
        assert any("last season counted in" in t for t in texts), \
            f"seeded call at {pick.slot} carries no disclosure: {texts}"


def test_the_gate_message_still_reports_real_games() -> None:
    """When the gate FAILS even with seeding (a rookie), the reason names real
    games — a seeded count in that sentence would overstate the evidence."""
    from engine.week_report import optimal_lineup
    from engine.availability import WeekAvailability

    season, players = _season(weeks=2), _players()
    season.roster_positions = ("RB",)
    model = ProjectionModel(season, players, prior_self={},
                            prior_self_weight=0.5)
    availability = WeekAvailability(
        season="2024", week=2, snapshot_as_of="the week 1 injury report",
        statuses={f"p{i}": {"team": "KC", "position": "RB", "active": True,
                            "injury_status": None} for i in range(6)},
        bye_teams=frozenset())
    picks = optimal_lineup(season, season.weeks[1][1], model, players,
                           availability, week=2)
    gated = [p for p in picks if p.confidence is None and p.confidence_gate]
    assert gated
    assert "not enough games on record yet (1 and 1" in gated[0].confidence_gate


def test_the_seed_cannot_touch_week_one_or_week_four() -> None:
    """Method §2: the seed is week-restricted IN THE MODEL, not by caller
    discipline — a model built with a seed must answer week 1 and week 4+
    exactly as the frozen model would. Week 1's frozen placement branch
    depends on project() returning None when there is nothing current to go
    on; a seeded week-1 opinion would silently kill it."""
    season, players = _season(weeks=3), _players()
    seeded = ProjectionModel(season, players,
                             prior_self={"p1": [20.0] * 17},
                             prior_self_weight=0.5)
    frozen = ProjectionModel(season, players)
    for week in (1, 4):
        assert seeded.project("p1", week) == frozen.project("p1", week), \
            f"the seed moved week {week}"
    # Week 1 with no current games and no positional prior: still None.
    empty = Season(league_id="t", season="2024", name="t", status="in_season",
                   roster_positions=("RB",), playoff_week_start=None,
                   scoring_settings={}, waiver_budget=None)
    bare = ProjectionModel(empty, players, prior_self={"p1": [20.0] * 17},
                           prior_self_weight=0.5)
    assert bare.project("p1", 1) is None, \
        "a seeded model invented a week-1 opinion from last season alone"
    # Week 2 in the same empty season: the seed IS allowed to speak.
    assert bare.project("p1", 2) is not None


def test_the_harness_gate_fails_closed_without_last_weeks_report() -> None:
    """C3's branch, now mirrored in the harness: a missing W-1 injury report
    yields no snapshot — everyone UNKNOWN, every call gated — never an empty
    designations map read as a league-wide clean bill of health."""
    from engine.availability import Status
    from engine.nflverse_backtest import Universe, availability_for

    universe = Universe(names={"00-1": "A"}, positions={"00-1": "RB"},
                        prior_points={"00-1": 100.0})
    weekly = {1: {"00-1": {"team": "KC"}}}
    availability = availability_for("2024", 2, ["00-1"], universe, weekly,
                                    injuries={}, byes=frozenset())
    assert not availability.has_snapshot
    assert availability.classify("00-1").status is Status.UNKNOWN
