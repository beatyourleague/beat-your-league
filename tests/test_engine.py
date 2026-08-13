"""Tests for the Phase 2 engine: no-lookahead, grading rules, calibration math.

The grading rules in engine/decisions.py are a published promise (CLAUDE.md
principle 2), so they are pinned here rather than left to drift with the code.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from engine.behavior import LEAGUE_TZ, profile_season, rank_by_aggression
from engine.calibration import (
    Bucket,
    brier_score,
    bucket_calls,
    expected_calibration_error,
    resolution_check,
    wilson_interval,
)
from engine.decisions import (
    HIT,
    MISS,
    TIE,
    StartSitCall,
    all_calls,
    calls_for_team_week,
    coin_flips,
    disagreements,
    grade,
    summarize,
)
from engine.history import (
    FLEX_ELIGIBILITY,
    HistoryError,
    PlayerIndex,
    Season,
    Team,
    TeamWeek,
    _parse_team_week,
    load_season,
    load_season_chain,
)
from engine.projection import (
    MIN_SD,
    Projection,
    ProjectionModel,
    normal_cdf,
    probability_outscores,
)


# --------------------------------------------------------------------- #
# fixtures: a tiny synthetic league we control completely
# --------------------------------------------------------------------- #

SLOTS = ["QB", "RB", "FLEX", "BN", "BN"]

PLAYERS_RAW: dict[str, Any] = {
    "qb1": {"full_name": "Quarter Back", "position": "QB", "fantasy_positions": ["QB"]},
    "qb2": {"full_name": "Backup Passer", "position": "QB", "fantasy_positions": ["QB"]},
    "rb1": {"full_name": "Run Back", "position": "RB", "fantasy_positions": ["RB"]},
    "rb2": {"full_name": "Bench Back", "position": "RB", "fantasy_positions": ["RB"]},
    "wr1": {"full_name": "Wide Out", "position": "WR", "fantasy_positions": ["WR"]},
    "te1": {"full_name": "Tight End", "position": "TE", "fantasy_positions": ["TE"]},
}


@pytest.fixture
def players() -> PlayerIndex:
    return PlayerIndex(PLAYERS_RAW)


def make_season(
    weeks: dict[int, dict[int, dict[str, Any]]],
    *,
    season: str = "2024",
    transactions: dict[int, list[dict[str, Any]]] | None = None,
) -> Season:
    """Build a Season from ``{week: {roster_id: {starters, points}}}``."""
    built = Season(
        league_id="123456789012345678",
        season=season,
        name="Test League",
        status="complete",
        roster_positions=tuple(SLOTS),
        playoff_week_start=14,
        scoring_settings={"rec": 1.0},
        waiver_budget=100,
        transactions=transactions or {},
    )
    roster_ids = {rid for rosters in weeks.values() for rid in rosters}
    roster_ids.update(
        rid
        for entries in (transactions or {}).values()
        for entry in entries
        for rid in (entry.get("roster_ids") or [])
    )
    for roster_id in sorted(roster_ids):
        built.teams[roster_id] = Team(
            roster_id=roster_id,
            team_name=f"Team {roster_id}",
            owner_name=f"owner{roster_id}",
            owner_id=str(roster_id),
        )
    for week, rosters in weeks.items():
        built.weeks[week] = {}
        for roster_id, spec in rosters.items():
            points: dict[str, float] = spec["points"]
            starters = tuple(spec["starters"])
            built.weeks[week][roster_id] = TeamWeek(
                roster_id=roster_id,
                week=week,
                matchup_id=1,
                starters=starters,
                starters_points=tuple(points.get(p, 0.0) for p in starters),
                players=tuple(points),
                players_points=dict(points),
                points=sum(points.get(p, 0.0) for p in starters),
            )
    return built


def steady_history(
    scores: dict[str, list[float]], starters: list[str], weeks: int = 6
) -> dict[int, dict[int, dict[str, Any]]]:
    """One roster, fixed lineup, per-player score series across ``weeks``."""
    return {
        week: {
            1: {
                "starters": starters,
                "points": {pid: series[week - 1] for pid, series in scores.items()},
            }
        }
        for week in range(1, weeks + 1)
    }


# --------------------------------------------------------------------- #
# the no-lookahead guarantee
# --------------------------------------------------------------------- #

def test_projection_ignores_the_target_week_and_everything_after(players: PlayerIndex) -> None:
    """The whole backtest is worthless if a projection can see the future.

    Same league, but weeks >= 4 are replaced with wildly different scores. A
    week-4 projection must be byte-identical across the two worlds.
    """
    base = {"qb1": [20.0] * 6, "rb1": [10.0] * 6, "rb2": [9.0] * 6}
    altered = {"qb1": [20.0, 20.0, 20.0, 99.0, 99.0, 99.0],
               "rb1": [10.0, 10.0, 10.0, 0.5, 0.5, 0.5],
               "rb2": [9.0, 9.0, 9.0, 80.0, 80.0, 80.0]}
    starters = ["qb1", "rb1", "rb2"]

    model_a = ProjectionModel(make_season(steady_history(base, starters)), players)
    model_b = ProjectionModel(make_season(steady_history(altered, starters)), players)

    for player_id in ("qb1", "rb1", "rb2"):
        a = model_a.project(player_id, 4)
        b = model_b.project(player_id, 4)
        assert a is not None and b is not None
        assert a.active_mean == pytest.approx(b.active_mean)
        assert a.appear_probability == pytest.approx(b.appear_probability)
        assert a.games == b.games


def test_observations_are_strictly_before_the_target_week(players: PlayerIndex) -> None:
    scores = {"qb1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "rb1": [5.0] * 6}
    model = ProjectionModel(make_season(steady_history(scores, ["qb1", "rb1", "rb1"])), players)
    assert model.observations("qb1", 1) == []
    assert model.observations("qb1", 4) == [1.0, 2.0, 3.0]
    assert model.observations("qb1", 99) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_position_prior_is_also_time_filtered(players: PlayerIndex) -> None:
    scores = {"qb1": [10.0, 10.0, 10.0, 50.0, 50.0, 50.0], "rb1": [5.0] * 6}
    model = ProjectionModel(make_season(steady_history(scores, ["qb1", "rb1", "rb1"])), players)
    early = model.position_prior("QB", 4)
    late = model.position_prior("QB", 7)
    assert early.mean == pytest.approx(10.0)
    assert late.mean > early.mean


# --------------------------------------------------------------------- #
# projection + availability model
# --------------------------------------------------------------------- #

def test_zero_points_counts_as_absence_not_a_bad_game(players: PlayerIndex) -> None:
    """A 0.0 must lower availability, not drag the scoring average to zero."""
    scores = {"qb1": [20.0, 0.0, 20.0, 0.0, 20.0, 0.0], "rb1": [5.0] * 6}
    model = ProjectionModel(make_season(steady_history(scores, ["qb1", "rb1", "rb1"])), players)
    projection = model.project("qb1", 7)
    assert projection is not None
    assert projection.games == 3
    assert projection.rostered_weeks == 6
    # Form stays near 20 (shrunk toward the QB prior, which is also ~20).
    assert projection.active_mean > 15.0
    # Availability is pulled well below 1.0 by the three missed weeks.
    assert 0.4 < projection.appear_probability < 0.8
    # Expected points is the product, so it lands far below the active mean.
    assert projection.mean < projection.active_mean


def test_free_agency_weeks_are_not_counted_as_missed_games(players: PlayerIndex) -> None:
    """A player rostered from week 4 on has 3 opportunities by week 7, not 6."""
    weeks: dict[int, dict[int, dict[str, Any]]] = {}
    for week in range(1, 7):
        points = {"rb1": 10.0}
        if week >= 4:
            points["qb1"] = 20.0
        weeks[week] = {1: {"starters": ["qb1", "rb1", "rb1"], "points": points}}
    model = ProjectionModel(make_season(weeks), players)
    projection = model.project("qb1", 7)
    assert projection is not None
    assert projection.rostered_weeks == 3
    assert projection.games == 3
    assert projection.appear_probability > 0.85


def test_sd_has_a_floor_so_a_tiny_sample_cannot_fake_certainty(players: PlayerIndex) -> None:
    scores = {"qb1": [12.0] * 6, "qb2": [12.0] * 6, "rb1": [8.0] * 6}
    model = ProjectionModel(make_season(steady_history(scores, ["qb1", "rb1", "rb1"])), players)
    projection = model.project("qb1", 6)
    assert projection is not None
    assert projection.sd >= MIN_SD


def test_project_returns_none_when_there_is_nothing_to_go_on(players: PlayerIndex) -> None:
    model = ProjectionModel(make_season({}), players)
    assert model.project("qb1", 5) is None


# --------------------------------------------------------------------- #
# the probability model
# --------------------------------------------------------------------- #

def build_projection(
    mean: float, sd: float = 6.0, appear: float = 1.0, player_id: str = "x"
) -> Projection:
    return Projection(
        player_id=player_id,
        as_of_week=5,
        active_mean=mean,
        active_sd=sd,
        appear_probability=appear,
        games=5,
        rostered_weeks=5,
        position="RB",
    )


def test_normal_cdf_matches_known_values() -> None:
    assert normal_cdf(0.0) == pytest.approx(0.5)
    assert normal_cdf(1.0) == pytest.approx(0.8413, abs=1e-4)
    assert normal_cdf(-1.96) == pytest.approx(0.0250, abs=1e-4)


def test_equal_players_are_a_coin_flip() -> None:
    a, b = build_projection(12.0), build_projection(12.0)
    assert probability_outscores(a, b) == pytest.approx(0.5)


def test_probability_is_symmetric_and_increases_with_the_gap() -> None:
    baseline = build_projection(10.0)
    close = probability_outscores(build_projection(11.0), baseline)
    far = probability_outscores(build_projection(20.0), baseline)
    assert 0.5 < close < far < 1.0
    assert probability_outscores(baseline, build_projection(11.0)) == pytest.approx(1 - close)


def test_availability_can_outweigh_a_better_scoring_average() -> None:
    """The finding that drove the model: a great player who may not play is
    not a better start than a steady one who will."""
    star_hurt = build_projection(22.0, appear=0.35)
    steady = build_projection(12.0, appear=0.98)
    assert steady.mean > star_hurt.mean
    assert probability_outscores(steady, star_hurt) > 0.5


def test_two_likely_absences_collapse_toward_a_coin_flip() -> None:
    """Both players probably score 0, which is a tie. Conditioning on a decision
    actually happening must stop that becoming false confidence: whoever shows
    up wins, so the edge shrinks toward even."""
    a = build_projection(20.0, appear=0.02)
    b = build_projection(4.0, appear=0.02)
    if_both_played = probability_outscores(
        build_projection(20.0), build_projection(4.0)
    )
    likely_absent = probability_outscores(a, b)
    assert if_both_played > 0.9
    assert 0.5 < likely_absent < 0.7
    assert likely_absent < if_both_played - 0.25


def test_the_two_directions_of_a_head_to_head_sum_to_one() -> None:
    """decisions.py derives the overruled case as 1 - p, so this must be exact
    across the availability mixture, not just for plain normals."""
    for pa, pb, mean_a, mean_b in [
        (1.0, 1.0, 12.0, 9.0), (0.6, 0.9, 18.0, 11.0),
        (0.2, 0.95, 25.0, 8.0), (0.5, 0.5, 10.0, 10.0),
    ]:
        a = build_projection(mean_a, appear=pa)
        b = build_projection(mean_b, appear=pb)
        assert probability_outscores(a, b) + probability_outscores(b, a) == pytest.approx(1.0)


def test_probability_stays_in_bounds_across_extremes() -> None:
    for mean_a, mean_b, pa, pb in [
        (0.0, 0.0, 0.0, 0.0), (50.0, 0.1, 1.0, 0.0), (0.1, 50.0, 0.0, 1.0),
        (10.0, 10.0, 0.5, 0.5), (30.0, 1.0, 0.9, 0.1),
    ]:
        value = probability_outscores(
            build_projection(mean_a, appear=pa), build_projection(mean_b, appear=pb)
        )
        assert 0.0 <= value <= 1.0
        assert not math.isnan(value)


# --------------------------------------------------------------------- #
# grading rules — frozen, per CLAUDE.md principle 2
# --------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "recommended, alternative, expected",
    [(10.0, 5.0, HIT), (5.0, 10.0, MISS), (7.5, 7.5, TIE), (0.0, 0.0, TIE),
     (0.1, 0.0, HIT), (-1.0, 0.0, MISS)],
)
def test_grade_rule(recommended: float, alternative: float, expected: str) -> None:
    assert grade(recommended, alternative) == expected


def make_call(**overrides: Any) -> StartSitCall:
    defaults: dict[str, Any] = dict(
        season="2024", week=5, roster_id=1, slot="RB", slot_index=1,
        started_id="rb1", alternative_id="rb2", recommended_id="rb1",
        confidence=0.6, projected_started=12.0, projected_alternative=9.0,
        actual_started=15.0, actual_alternative=8.0, outcome=HIT,
        is_playoff_week=False,
    )
    defaults.update(overrides)
    return StartSitCall(**defaults)


def test_ties_are_excluded_from_hit_rate_but_still_counted() -> None:
    calls = [
        make_call(outcome=HIT), make_call(outcome=HIT),
        make_call(outcome=MISS), make_call(outcome=TIE), make_call(outcome=TIE),
    ]
    summary = summarize(calls)
    assert summary.graded == 5
    assert summary.decided == 3
    assert summary.ties == 2
    assert summary.hit_rate == pytest.approx(2 / 3)


def test_hit_rate_is_none_rather_than_zero_when_nothing_was_decided() -> None:
    assert summarize([make_call(outcome=TIE)]).hit_rate is None
    assert summarize([]).hit_rate is None


def test_margin_and_bench_points_track_the_recommendation() -> None:
    agreed = make_call(recommended_id="rb1", actual_started=15.0, actual_alternative=8.0)
    assert agreed.agreed_with_manager
    assert agreed.margin == pytest.approx(7.0)
    assert agreed.manager_points_left_on_bench == 0.0

    overruled = make_call(recommended_id="rb2", actual_started=15.0, actual_alternative=8.0)
    assert not overruled.agreed_with_manager
    assert overruled.benched_id == "rb1"
    assert overruled.margin == pytest.approx(-7.0)
    # The manager was right, so they left nothing on the bench.
    assert overruled.manager_points_left_on_bench == 0.0

    regret = make_call(actual_started=3.0, actual_alternative=20.0)
    assert regret.manager_points_left_on_bench == pytest.approx(17.0)


def test_both_scored_flags_a_zero_on_either_side() -> None:
    assert make_call(actual_started=10.0, actual_alternative=5.0).both_scored
    assert not make_call(actual_started=0.0, actual_alternative=5.0).both_scored
    assert not make_call(actual_started=10.0, actual_alternative=0.0).both_scored


def test_coin_flips_and_disagreements_select_the_right_calls() -> None:
    calls = [make_call(confidence=0.52), make_call(confidence=0.75),
             make_call(confidence=0.58, recommended_id="rb2")]
    assert len(coin_flips(calls)) == 2
    assert len(disagreements(calls)) == 1


# --------------------------------------------------------------------- #
# call generation
# --------------------------------------------------------------------- #

def test_call_generation_picks_the_best_eligible_bench_player(players: PlayerIndex) -> None:
    scores = {
        "qb1": [20.0] * 6, "rb1": [6.0] * 6, "wr1": [8.0] * 6,
        "rb2": [14.0] * 6, "te1": [4.0] * 6,
    }
    season = make_season(steady_history(scores, ["qb1", "rb1", "wr1"]))
    model = ProjectionModel(season, players)
    calls = list(calls_for_team_week(season, season.weeks[6][1], model, players))
    by_slot = {c.slot: c for c in calls}

    # RB slot: rb1 started, rb2 is the only eligible bench RB and projects higher.
    assert by_slot["RB"].alternative_id == "rb2"
    assert by_slot["RB"].recommended_id == "rb2"
    assert not by_slot["RB"].agreed_with_manager
    # QB slot has no eligible bench QB at all, so no call exists.
    assert "QB" not in by_slot


def test_flex_eligibility_follows_the_league_slot_definition(players: PlayerIndex) -> None:
    assert players.get("rb2").eligible_for("FLEX")
    assert players.get("te1").eligible_for("FLEX")
    assert not players.get("qb2").eligible_for("FLEX")
    assert players.get("qb2").eligible_for("SUPER_FLEX")
    assert FLEX_ELIGIBILITY["WRRB_FLEX"] == frozenset({"RB", "WR"})


def test_duplicate_head_to_heads_are_graded_once_per_roster_week(players: PlayerIndex) -> None:
    """One bench RB is the best alternative at both RB and FLEX. That is one
    decision, not two, so it must not be double-counted into calibration."""
    scores = {"qb1": [20.0] * 6, "rb1": [6.0] * 6, "wr1": [6.0] * 6, "rb2": [15.0] * 6}
    season = make_season(steady_history(scores, ["qb1", "rb1", "rb1"]))
    calls = list(
        calls_for_team_week(season, season.weeks[6][1], ProjectionModel(season, players), players)
    )
    pairs = [tuple(sorted((c.started_id, c.alternative_id))) for c in calls]
    assert len(pairs) == len(set(pairs))


def test_no_call_when_evidence_is_too_thin(players: PlayerIndex) -> None:
    scores = {"qb1": [20.0, 20.0], "rb1": [6.0, 6.0], "rb2": [9.0, 9.0]}
    season = make_season(steady_history(scores, ["qb1", "rb1", "rb2"], weeks=2))
    calls = list(
        calls_for_team_week(season, season.weeks[2][1], ProjectionModel(season, players), players)
    )
    assert calls == []


def test_empty_starting_slots_are_skipped(players: PlayerIndex) -> None:
    scores = {"qb1": [20.0] * 6, "rb1": [6.0] * 6, "rb2": [9.0] * 6}
    season = make_season(steady_history(scores, ["qb1", "0", "rb1"]))
    calls = list(
        calls_for_team_week(season, season.weeks[6][1], ProjectionModel(season, players), players)
    )
    assert all(c.started_id != "0" for c in calls)


def test_playoff_weeks_are_labelled(players: PlayerIndex) -> None:
    # wr1 sits on the bench, so the FLEX slot actually produces a call.
    scores = {"qb1": [20.0] * 15, "rb1": [6.0] * 15, "rb2": [9.0] * 15,
              "wr1": [11.0] * 15}
    season = make_season(steady_history(scores, ["qb1", "rb1", "rb2"], weeks=15))
    calls = all_calls(season, ProjectionModel(season, players), players)
    assert any(c.is_playoff_week for c in calls if c.week >= 14)
    assert all(not c.is_playoff_week for c in calls if c.week < 14)


# --------------------------------------------------------------------- #
# calibration math
# --------------------------------------------------------------------- #

def test_wilson_interval_brackets_the_observed_rate() -> None:
    low, high = wilson_interval(60, 100)
    assert low < 0.60 < high
    assert 0.0 <= low and high <= 1.0
    # Narrows with more evidence.
    wide_low, wide_high = wilson_interval(6, 10)
    assert (high - low) < (wide_high - wide_low)


def test_wilson_interval_stays_in_bounds_at_the_extremes() -> None:
    assert wilson_interval(0, 0) is None
    low, high = wilson_interval(10, 10)
    assert low >= 0.0 and high <= 1.0
    low, high = wilson_interval(0, 10)
    assert low >= 0.0 and high <= 1.0


def test_brier_score_rewards_being_right_and_confident() -> None:
    confident_right = [make_call(confidence=0.95, outcome=HIT)] * 10
    confident_wrong = [make_call(confidence=0.95, outcome=MISS)] * 10
    hedged = [make_call(confidence=0.5, outcome=HIT)] * 10
    assert brier_score(confident_right) < brier_score(hedged) < brier_score(confident_wrong)
    assert brier_score([make_call(outcome=TIE)]) is None


def test_bucketing_assigns_calls_by_stated_confidence() -> None:
    calls = [make_call(confidence=0.52, outcome=HIT), make_call(confidence=0.54, outcome=MISS),
             make_call(confidence=0.72, outcome=HIT)]
    reports = {r.bucket.label: r for r in bucket_calls(calls)}
    assert reports["50-55%"].bucket.graded == 2
    assert reports["70-80%"].bucket.graded == 1
    assert reports["60-65%"].bucket.graded == 0


def test_a_bucket_is_only_judged_with_enough_evidence() -> None:
    few = bucket_calls([make_call(confidence=0.62, outcome=HIT)] * 5)
    assert all(r.calibrated is None for r in few)
    # 40 calls at a stated 62% that hit 62.5% of the time reads as calibrated.
    many = [make_call(confidence=0.62, outcome=HIT)] * 25 + [
        make_call(confidence=0.62, outcome=MISS)
    ] * 15
    judged = [r for r in bucket_calls(many) if r.bucket.graded]
    assert judged and judged[0].calibrated is True


def test_a_badly_overconfident_bucket_is_reported_as_off() -> None:
    calls = [make_call(confidence=0.9, outcome=HIT)] * 20 + [
        make_call(confidence=0.9, outcome=MISS)
    ] * 20
    judged = [r for r in bucket_calls(calls) if r.bucket.graded]
    assert judged and judged[0].calibrated is False


def test_expected_calibration_error_is_zero_for_a_perfect_model() -> None:
    calls = [make_call(confidence=0.75, outcome=HIT)] * 75 + [
        make_call(confidence=0.75, outcome=MISS)
    ] * 25
    assert expected_calibration_error(bucket_calls(calls)) == pytest.approx(0.0, abs=0.01)


def test_resolution_check_detects_a_model_that_sorts_nothing() -> None:
    flat = [make_call(confidence=0.5 + i * 0.001, outcome=HIT if i % 2 else MISS)
            for i in range(100)]
    bottom, top = resolution_check(flat)
    assert bottom is not None and abs(top - bottom) < 0.35
    assert resolution_check([make_call()] * 5) == (None, None)


def test_bucket_hit_rate_is_none_when_undecided() -> None:
    assert Bucket(0.5, 0.55, graded=2, ties=2, hits=0, misses=0).hit_rate is None


# --------------------------------------------------------------------- #
# behavioral profiles
# --------------------------------------------------------------------- #

def test_faab_and_waiver_counts_include_failed_bids() -> None:
    transactions = {
        3: [
            {"type": "waiver", "status": "complete", "settings": {"waiver_bid": 30},
             "adds": {"p1": 1}, "drops": {"p9": 1}, "roster_ids": [1],
             "status_updated": 1539155042276},
            {"type": "waiver", "status": "failed", "settings": {"waiver_bid": 45},
             "adds": {"p2": 1}, "drops": None, "roster_ids": [1],
             "status_updated": 1539155042276},
            {"type": "free_agent", "status": "complete", "adds": {"p3": 2},
             "drops": None, "roster_ids": [2], "status_updated": 1539155042276},
        ]
    }
    season = make_season({1: {1: {"starters": ["qb1"], "points": {"qb1": 10.0}}}},
                         transactions=transactions)
    profiles = profile_season(season)

    one = profiles[1]
    assert one.waiver_bids_placed == 2
    assert one.waiver_bids_won == 1
    assert one.waiver_bids_lost == 1
    # Only the winning bid costs FAAB, but the losing bid still reveals intent.
    assert one.faab_spent == 30
    assert one.max_bid == 45
    assert one.drops == 1
    assert profiles[2].free_agent_adds == 1


def make_profiles(spends: list[int]) -> list[Any]:
    """One profile per spend value, in a league of len(spends) teams."""
    weeks = {1: {i + 1: {"starters": ["qb1"], "points": {"qb1": 10.0}}
                 for i in range(len(spends))}}
    season = make_season(weeks, transactions={1: []})
    profiles = profile_season(season)
    for index, spend in enumerate(spends):
        profiles[index + 1].faab_spent = spend
    return list(profiles.values())


def test_aggression_is_ranked_within_the_league_not_by_absolute_spend() -> None:
    """A fixed threshold labelled 8 of 12 sample-league managers 'very
    aggressive'. The rank must separate managers regardless of league scale."""
    big_spenders = rank_by_aggression(make_profiles([100, 90, 80, 70, 60, 50]))
    penny_league = rank_by_aggression(make_profiles([10, 9, 8, 7, 6, 5]))
    assert [p.aggression_label() for p in big_spenders] == [
        p.aggression_label() for p in penny_league
    ]
    assert big_spenders[0].aggression_label() == "very aggressive"
    assert big_spenders[-1].aggression_label() == "quiet"


def test_ranking_orders_by_spend_and_records_evidence() -> None:
    ranked = rank_by_aggression(make_profiles([10, 50, 30]))
    assert [p.faab_spent for p in ranked] == [50, 30, 10]
    assert [p.aggression_rank for p in ranked] == [1, 2, 3]
    assert all(p.league_size == 3 for p in ranked)
    assert "#1 of 3 on waiver spend" in ranked[0].aggression_evidence()


def test_a_single_manager_is_not_declared_the_most_aggressive() -> None:
    ranked = rank_by_aggression(make_profiles([40]))
    assert ranked[0].aggression_percentile is None
    assert ranked[0].aggression_label() == "unranked"


def test_spending_over_the_recorded_budget_is_flagged_not_hidden() -> None:
    """Seen in real data: 140 FAAB spent against a stated budget of 100,
    because budgets can be raised mid-season."""
    profile = make_profiles([140])[0]
    profile.faab_budget = 100
    assert profile.budget_exceeded
    assert profile.faab_spent_share == pytest.approx(1.4)

    normal = make_profiles([40])[0]
    normal.faab_budget = 100
    assert not normal.budget_exceeded


def test_unavailable_metrics_are_declared_not_faked() -> None:
    season = make_season({1: {1: {"starters": ["qb1"], "points": {"qb1": 10.0}}}},
                         transactions={1: []})
    profile = profile_season(season)[1]
    metrics = {u.metric for u in profile.unavailable}
    assert "questionable-start rate" in metrics
    assert "lineup-setting lateness" in metrics
    assert all(u.reason for u in profile.unavailable)


def test_game_day_share_is_none_without_timestamps() -> None:
    season = make_season({1: {1: {"starters": ["qb1"], "points": {"qb1": 10.0}}}},
                         transactions={1: []})
    assert profile_season(season)[1].game_day_add_share is None


# --------------------------------------------------------------------- #
# history loading
# --------------------------------------------------------------------- #

def test_starting_slots_exclude_bench_and_reserve() -> None:
    season = make_season({})
    assert season.starting_slots == ("QB", "RB", "FLEX")


def test_bench_is_roster_minus_starters() -> None:
    season = make_season(
        {1: {1: {"starters": ["qb1", "rb1", "wr1"],
                 "points": {"qb1": 1.0, "rb1": 2.0, "wr1": 3.0, "rb2": 4.0}}}}
    )
    assert set(season.weeks[1][1].bench()) == {"rb2"}


def test_missing_league_reports_instead_of_crashing(tmp_path: Path) -> None:
    with pytest.raises(HistoryError, match="not cached"):
        load_season(tmp_path, "289646328504385536")
    with pytest.raises(HistoryError):
        load_season_chain(tmp_path, "289646328504385536")


def test_player_index_falls_back_to_name_parts_and_handles_junk() -> None:
    index = PlayerIndex({
        "a": {"first_name": "Only", "last_name": "Parts", "position": "WR"},
        "b": {"position": "DEF", "team": "NYJ"},
        "c": "not a dict",
    })
    assert index.name("a") == "Only Parts"
    assert index.name("b") == "b"
    assert "c" not in index
    assert index.position("zzz") == "UNK"


def test_starter_missing_from_players_list_is_still_rostered() -> None:
    """Sleeper can omit a starter from `players`. Bench detection must not then
    promote that starter into the bench and grade him against himself."""
    team_week = _parse_team_week(
        {
            "roster_id": 1,
            "matchup_id": 2,
            "starters": ["qb1", "rb1", "0"],
            "starters_points": [10.0, 2.0, 0.0],
            "players": ["rb1", "rb2"],
            "players_points": {"qb1": 10.0, "rb1": 2.0, "rb2": 4.0},
            "points": 12.0,
        },
        week=1,
    )
    assert team_week is not None
    assert "qb1" in team_week.players
    assert set(team_week.bench()) == {"rb2"}
    # The unfilled "0" slot is not invented into a rostered player.
    assert "0" not in team_week.players


def test_parse_team_week_rejects_a_record_without_a_roster() -> None:
    assert _parse_team_week({"starters": []}, week=1) is None
    assert _parse_team_week({"roster_id": None}, week=1) is None


# --------------------------------------------------------------------- #
# end-to-end against the real cache, when it is present
# --------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_LEAGUE = "289646328504385536"
RAW_DIR = REPO_ROOT / "data" / "raw"


requires_cache = pytest.mark.skipif(
    not (RAW_DIR / "league" / SAMPLE_LEAGUE / "league.json").is_file()
    or not (RAW_DIR / "players" / "nfl.json").is_file(),
    reason="sample-league cache not present; run `python -m ingest.pull`",
)


@requires_cache
def test_real_cache_grades_and_stays_self_consistent() -> None:
    from engine.history import load_players

    players_index = load_players(RAW_DIR)
    seasons = [s for s in load_season_chain(RAW_DIR, SAMPLE_LEAGUE) if s.status == "complete"]
    assert seasons, "expected at least one completed cached season"

    calls: list[StartSitCall] = []
    for season in seasons:
        calls.extend(all_calls(season, ProjectionModel(season, players_index), players_index))
    assert len(calls) > 500

    for call in calls:
        assert 0.5 <= call.confidence <= 1.0, "engine backs its own recommendation"
        assert call.recommended_id in (call.started_id, call.alternative_id)
        assert call.started_id != call.alternative_id
        expected = grade(call.actual_recommended, call.actual_benched)
        assert call.outcome == expected

    summary = summarize(calls)
    assert summary.graded == summary.hits + summary.misses + summary.ties
