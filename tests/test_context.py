"""reports/context-method.md — the code promises, before the run."""

from __future__ import annotations

from types import SimpleNamespace

from engine.context import (excused_weeks, market_table, matchup_table,
                            multiplier_for, team_in_week)
from engine.context_backtest import choose
from engine.projection import ProjectionModel
from engine.scoring import preset
from test_early_season import _players, _season


def test_the_switches_are_inert_when_absent() -> None:
    season, players = _season(weeks=6), _players()
    frozen = ProjectionModel(season, players).project("p1", 7)
    assert ProjectionModel(season, players, excused=None,
                           multiplier=None).project("p1", 7) == frozen


def test_context_touches_weeks_4_to_16_only() -> None:
    season, players = _season(weeks=17), _players()
    frozen = ProjectionModel(season, players)
    boosted = ProjectionModel(season, players, multiplier=lambda pid, w: 1.5)
    assert boosted.project("p1", 10).active_mean > frozen.project("p1", 10).active_mean
    for week in (3, 17):
        assert boosted.project("p1", week) == frozen.project("p1", week)


def test_an_excused_week_is_neither_an_appearance_nor_a_miss() -> None:
    season, players = _season(weeks=6), _players()
    # p1 missed week 3 (no appearance), which the injury report announced.
    for week in (3,):
        tw = season.weeks[week][1]
        season.weeks[week][1] = type(tw)(**{**tw.__dict__,
                                            "appeared": frozenset(tw.appeared) - {"p1"}})
    plain = ProjectionModel(season, players).project("p1", 7)
    forgiven = ProjectionModel(season, players,
                               excused={"p1": frozenset({3})}).project("p1", 7)
    assert forgiven.appear_probability > plain.appear_probability
    assert forgiven.games == plain.games          # the gate still counts real games


def test_the_market_multiplier_is_a_square_root_ratio() -> None:
    games = [{"home_team": "KC", "away_team": "BAL", "spread_line": "3",
              "total_line": "47"},
             {"home_team": "NYG", "away_team": "DAL", "spread_line": "-7",
              "total_line": "41"}]
    table = market_table(games)
    implied = {"KC": 25.0, "BAL": 22.0, "NYG": 17.0, "DAL": 24.0}
    mean = sum(implied.values()) / 4
    for team, value in implied.items():
        assert abs(table[team] - (value / mean) ** 0.5) < 1e-9
    assert market_table([{"home_team": "A", "away_team": "B"}]) == {}


def test_the_matchup_shrinks_toward_the_league_with_six_games() -> None:
    rule = preset("ppr")
    row = lambda team, opp, yds: {"team": team, "opponent_team": opp,  # noqa: E731
                                  "position": "WR", "receiving_yards": yds}
    weekly = {1: {"a": row("X", "BAD", 200), "b": row("Y", "GOOD", 0)},
              2: {"a": row("X", "BAD", 200), "b": row("Y", "GOOD", 0)},
              3: {"c": row("Z", "X", 100)}}
    games = [{"home_team": "Z", "away_team": "BAD"}]
    allowed, played, league = matchup_table(weekly, rule, 4)
    assert played["BAD"] == 2 and allowed[("BAD", "WR")] == 40.0
    mult = multiplier_for(4, weekly, rule, games, use_matchup=True, use_market=False)
    base = league["WR"]
    assert abs(mult("c", 4) - (40.0 + 6 * base) / ((2 + 6) * base)) < 1e-9
    assert mult("c", 4) > 1.0 and mult("c", 5) == 1.0 and mult("DEF-Z", 4) == 1.0


def test_a_bye_and_an_out_designation_are_excused() -> None:
    weekly = {1: {"p": {"team": "KC"}}, 3: {"p": {"team": "KC"}}}
    schedule = {1: [{"home_team": "KC", "away_team": "BAL"}],
                2: [{"home_team": "NYG", "away_team": "DAL"}],
                3: [{"home_team": "KC", "away_team": "BAL"}],
                4: [{"home_team": "KC", "away_team": "BAL"}]}
    injuries = {3: SimpleNamespace(by_gsis={"p": "Out"})}
    assert excused_weeks(["p"], weekly, schedule, injuries, 5) == {"p": frozenset({2, 3})}
    assert team_in_week("p", 2, weekly) == "KC"


def test_the_arm_is_chosen_on_the_fit_seasons_by_margin() -> None:
    assert choose({"A": (10, 5, 0), "AM": (12, 5, 0), "AV": (12, 6, 0),
                   "AMV": (11, 5, 0)}) == "AM"
    assert choose({"A": (5, 5, 0), "AM": (4, 5, 0), "AV": (1, 9, 0),
                   "AMV": (0, 0, 0)}) is None


def test_relocated_franchises_are_not_on_bye_all_season() -> None:
    """The schedule archive says OAK/SD/STL while stat rows say LV/LAC/LA. Raw
    comparison read every player on those teams as on bye every week of
    2014-2019 (found by adversarial review) — and skipped the market lookup."""
    from engine.context import market_table, multiplier_for, team_code
    assert (team_code("OAK"), team_code("SD"), team_code("STL"), team_code("KC")) == \
        ("LV", "LAC", "LA", "KC")
    weekly = {w: {"p": {"team": "LV", "position": "WR"}} for w in range(1, 8)}
    schedule = {w: [{"home_team": "OAK", "away_team": "KC"}] for w in range(1, 8)}
    assert excused_weeks(["p"], weekly, schedule, {}, 8) == {}, \
        "a player who played every week was excused as on bye"
    week8 = [{"home_team": "OAK", "away_team": "KC", "spread_line": "3", "total_line": "47"},
             {"home_team": "NYG", "away_team": "DAL", "spread_line": "-7", "total_line": "41"}]
    assert "LV" in market_table(week8) and "OAK" not in market_table(week8)
    assert multiplier_for(8, weekly, None, week8, False, True)("p", 8) != 1.0


def test_excused_weeks_read_only_what_the_product_could_have_had() -> None:
    """The backtest passes the whole season; the product holds only weeks before
    the report week. A player with no rows before W must not borrow a team from
    a later week to get his bye excused."""
    weekly = {9: {"p": {"team": "KC"}}}                       # first row is AFTER week 8
    schedule = {w: [{"home_team": "NYG", "away_team": "DAL"}] for w in range(1, 9)}
    assert excused_weeks(["p"], weekly, schedule, {}, 8) == {}


def test_the_live_path_falls_back_rather_than_run_a_model_nobody_graded(tmp_path) -> None:
    """With no market lines for the week, arm A alone would publish under AV's
    recalibration. It falls back to the previous model (context None)."""
    import csv
    import run.solo as solo
    games = tmp_path / "games.csv"
    fields = ["season", "game_type", "week", "home_team", "away_team",
              "spread_line", "total_line", "gameday"]
    with games.open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=fields)
        w.writeheader()
        for lines in (("", ""), ("3", "47")):
            w.writerow(dict(season="2026", game_type="REG", week="6" if not lines[0] else "5",
                            home_team="KC", away_team="BAL", spread_line=lines[0],
                            total_line=lines[1], gameday="2026-10-11"))
    (tmp_path / "injuries_2026.csv").write_text(
        "season,game_type,team,week,gsis_id,report_status\n")
    import ingest.nflverse as nv
    real = nv.fetch
    nv.fetch = lambda asset, name, cache, **k: games if asset == "schedules" else tmp_path / name
    try:
        assert solo._context_inputs(tmp_path, "2026", 6, SimpleNamespace(players=[]), {}) is None
        assert solo._context_inputs(tmp_path, "2026", 5, SimpleNamespace(players=[]), {}) is not None
    finally:
        nv.fetch = real
