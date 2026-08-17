"""Tests for closing out the week — the resolution the report used to skip.

The rules under test are the two that keep it honest AND keep it kind: every
figure is a count of something that already happened, and regret is only
reported when a different choice would genuinely have changed the result.
"""

from __future__ import annotations

from pathlib import Path

import test_week_report as twr
from engine.history import load_players, load_season_chain
from engine.last_week import headline, summarise


def _week(tmp_path, week: int, roster_id: int = 1):
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    seasons = load_season_chain(raw, season.league_id, max_seasons=1)
    s = seasons[0]
    players = load_players(raw)
    tws = [t for t in s.team_weeks() if t.week == week]
    mine = next((t for t in tws if t.roster_id == roster_id), None)
    if mine is None:
        return None, None
    opp = next((t for t in tws if t.roster_id != roster_id
                and t.matchup_id == mine.matchup_id), None)
    if opp is None:
        return None, None
    return summarise(s, mine, opp, s.team_label(opp.roster_id), players), s


def test_an_unplayed_week_is_not_a_tie(tmp_path) -> None:
    """0.0 vs 0.0 means the games have not happened, never a 0-0 draw — the
    same rule the matchup backtest froze as RULE M1."""
    from engine.history import TeamWeek
    from engine.last_week import summarise as s2
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    chain = load_season_chain(raw, season.league_id, max_seasons=1)[0]
    players = load_players(raw)
    blank = TeamWeek(roster_id=1, week=99, matchup_id=1, starters=(),
                     starters_points=(), players=(), players_points={}, points=0.0)
    assert s2(chain, blank, blank, "them", players) is None


def test_a_won_week_never_gets_a_regret_line(tmp_path) -> None:
    """RULE R2. Telling a winner what they left on the bench is guilt with no
    decision attached — the week was already won."""
    last, _ = _week(tmp_path, twr.REPORT_WEEK)
    if last is None or not last.won:
        return
    assert "would have won it" not in headline(last)
    assert headline(last).startswith("You beat")


def test_an_unwinnable_week_says_so_instead_of_blaming(tmp_path) -> None:
    """The differentiator. When the best available lineup still loses, the
    honest and useful reading is that selection was not the problem."""
    from dataclasses import replace
    last, _ = _week(tmp_path, twr.REPORT_WEEK)
    if last is None:
        return
    # force the unwinnable shape rather than hunting the fixture for one
    unwinnable = replace(last, points=100.0, opponent_points=200.0,
                         best_possible=110.0, winnable=False, flipped_by=None)
    text = headline(unwinnable)
    assert "Nothing on your bench saves that one" in text
    assert "beaten on scoring, not on selection" in text


def test_regret_is_only_reported_when_a_swap_would_have_won(tmp_path) -> None:
    """A loss no single swap could have changed gets the result and nothing
    else — inventing a culprit would be hindsight dressed as advice."""
    from dataclasses import replace
    last, _ = _week(tmp_path, twr.REPORT_WEEK)
    if last is None:
        return
    lost = replace(last, points=114.8, opponent_points=126.6,
                   best_possible=130.0, winnable=True, flipped_by=None)
    text = headline(lost)
    assert "would have won it" not in text
    assert "114.8" in text and "126.6" in text


def test_every_figure_is_a_real_score(tmp_path) -> None:
    """RULE R1: counts, never projections — so the section carries no
    calibration burden."""
    last, _ = _week(tmp_path, twr.REPORT_WEEK)
    if last is None:
        return
    assert last.best_possible >= last.points, \
        "the best possible lineup cannot score less than the one that played"
    assert last.left_on_bench >= 0
