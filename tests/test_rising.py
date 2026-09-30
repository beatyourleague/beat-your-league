"""Rising roles (engine/rising.py) — counted usage, reported, never a call."""

from __future__ import annotations

from types import SimpleNamespace

from engine import rising


def _row(pos="RB", team="SEA", targets=0, carries=0):
    return {"position": pos, "team": team, "targets": targets, "carries": carries}


def _weeks(**series):
    """series: pid -> {week: (targets, carries)}, all RBs."""
    out: dict[int, dict] = {}
    for pid, by_week in series.items():
        for week, (t, c) in by_week.items():
            out.setdefault(week, {})[pid] = _row(targets=t, carries=c)
    return out


def test_a_jump_in_touches_over_the_last_two_weeks_is_a_riser() -> None:
    weekly = _weeks(**{"00-0000001": {1: (1, 2), 2: (0, 3), 3: (4, 11), 4: (3, 12)}})
    [c] = rising.candidates(weekly, 5)
    assert c["recent"] == 15.0 and c["earlier"] == 3.0 and c["jump"] == 12.0


def test_no_riser_without_two_recent_games_an_earlier_one_or_a_real_jump() -> None:
    weekly = _weeks(**{
        "00-0000001": {1: (1, 2), 4: (5, 9)},                        # missed a recent week
        "00-0000002": {3: (5, 9), 4: (5, 9)},                        # nothing earlier
        "00-0000003": {1: (5, 6), 2: (5, 6), 3: (5, 7), 4: (5, 7)},  # steady
        "00-0000004": {1: (0, 0), 3: (2, 2), 4: (2, 3)},             # jump, but tiny
    })
    assert rising.candidates(weekly, 5) == []
    assert rising.candidates(weekly, 3) == []                        # too early in the season


def test_quarterbacks_defenses_and_the_current_week_are_never_read() -> None:
    weekly = _weeks(**{"00-0000001": {1: (0, 0), 2: (0, 0), 3: (9, 9), 4: (9, 9)}})
    weekly[4]["00-0000001"]["position"] = "QB"
    weekly[4]["DEF-SEA"] = _row(targets=99, carries=99)
    weekly[5] = {"00-0000001": _row(targets=50, carries=50)}         # the week itself
    assert rising.candidates(weekly, 5) == []
    weekly[4]["00-0000001"]["position"] = "RB"
    [c] = rising.candidates(weekly, 5)
    assert c["recent"] == 18.0, "week 5's own rows leaked into a week-5 report"


def test_roster_players_and_last_seasons_starters_are_left_out() -> None:
    pool = [{"player_id": pid, "position": "RB", "team": "SEA", "recent": 12.0,
             "earlier": 2.0, "jump": 10.0 - i} for i, pid in
            enumerate(["a", "b", "c", "d", "e"])]
    names = SimpleNamespace(name=lambda pid: pid.upper())
    ranks = {"b": ("RB", 10, 200), "c": ("RB", 60, 200)}   # b was an RB10, c an RB60
    rows = rising.for_roster(pool, ["a"], ranks, names)
    assert [r["name"] for r in rows] == ["C", "D", "E"]
    assert rows[0]["line"] == "C (SEA, RB): 12.0 touches a game over his last two, up from 2.0 before."


def test_no_number_here_is_a_probability() -> None:
    line = rising.line("X", {"team": "SEA", "position": "RB", "recent": 9.5, "earlier": 3.0})
    assert "%" not in line and "odds" not in line.lower()
