"""Tests for Phase 3: availability, lineup assembly, gating, and the renderer.

The synthetic league here is deliberately tiny and fully controlled: two teams,
five weeks of history, week 6 as the report week. Player scoring is chosen so
each assertion has one unambiguous right answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.availability import (
    PlayerStatus, Status, WeekAvailability, bye_teams_for_week,
    load_week_availability, may_publish_confidence,
)
from engine.history import PlayerIndex, Season, TeamWeek
from engine.projection import ProjectionModel
from engine.week_report import (
    build_week_report, hype_meter, optimal_lineup, regret_call, rival_lineup,
    win_probability,
)
from render.report import esc, render

# --------------------------------------------------------------------- #
# fixtures: a tiny controlled league
# --------------------------------------------------------------------- #

SLOTS = ("QB", "RB", "WR", "FLEX")
REPORT_WEEK = 6

# player_id -> (name, position, weekly points weeks 1-5)
PLAYERS: dict[str, tuple[str, str, list[float]]] = {
    "qb1": ("Steady QB", "QB", [20, 21, 19, 20, 20]),
    "qb2": ("Backup QB", "QB", [10, 11, 9, 10, 10]),
    "rb1": ("Bell Cow", "RB", [15, 16, 14, 15, 15]),
    "rb2": ("Handcuff", "RB", [8, 9, 7, 8, 8]),
    "wr1": ("Alpha WR", "WR", [14, 13, 15, 14, 14]),
    "wr2": ("Deep Threat", "WR", [9, 22, 2, 9, 9]),
    "wr3": ("Possession Guy", "WR", [10, 10, 10, 10, 10]),
    "rk1": ("Rookie", "WR", [0, 0, 0, 0, 12]),  # 1 appearance: thin evidence
    # rival's players
    "qb9": ("Rival QB", "QB", [18, 18, 18, 18, 18]),
    "rb9": ("Rival RB", "RB", [12, 12, 12, 12, 12]),
    "rb8": ("Rival Bench RB", "RB", [17, 17, 17, 17, 17]),  # better than rb9!
    "wr9": ("Rival WR", "WR", [11, 11, 11, 11, 11]),
    "fx9": ("Rival Flex", "TE", [7, 7, 7, 7, 7]),
}

MY_ROSTER = ["qb1", "qb2", "rb1", "rb2", "wr1", "wr2", "wr3", "rk1"]
RIVAL_ROSTER = ["qb9", "rb9", "rb8", "wr9", "fx9"]


def _player_index() -> PlayerIndex:
    raw = {
        pid: {"full_name": name, "position": pos, "fantasy_positions": [pos]}
        for pid, (name, pos, _) in PLAYERS.items()
    }
    return PlayerIndex(raw)


def _team_week(roster_id: int, week: int, roster: list[str],
               starters: list[str], matchup_id: int = 1) -> TeamWeek:
    points = {}
    for pid in roster:
        series = PLAYERS[pid][2]
        points[pid] = float(series[week - 1]) if week - 1 < len(series) else 0.0
    return TeamWeek(
        roster_id=roster_id, week=week, matchup_id=matchup_id,
        starters=tuple(starters),
        starters_points=tuple(points.get(s, 0.0) for s in starters),
        players=tuple(roster),
        players_points=points,
        points=sum(points.get(s, 0.0) for s in starters),
    )


def _season(weeks: int = REPORT_WEEK) -> Season:
    season = Season(
        league_id="111111111111111111", season="2025", name="Test League",
        status="in_season", roster_positions=SLOTS + ("BN", "BN", "BN", "BN"),
        playoff_week_start=15, scoring_settings={"rec": 1.0}, waiver_budget=100,
    )
    from engine.history import Team
    season.teams = {
        1: Team(1, "My Team", "kevin", "u1"),
        2: Team(2, "Rival Team", "mike", "u2"),
    }
    my_starters = ["qb1", "rb1", "wr1", "wr2"]
    rival_starters = ["qb9", "rb9", "wr9", "fx9"]
    for week in range(1, weeks + 1):
        season.weeks[week] = {
            1: _team_week(1, week, MY_ROSTER, my_starters),
            2: _team_week(2, week, RIVAL_ROSTER, rival_starters),
        }
    return season


def _availability(statuses: dict[str, dict[str, Any]] | None,
                  byes: frozenset[str] | None = frozenset()) -> WeekAvailability:
    return WeekAvailability(season="2025", week=REPORT_WEEK,
                            snapshot_as_of="2025-10-09T12:00:00+00:00" if statuses is not None else None,
                            statuses=statuses, bye_teams=byes)


def _all_active(*player_ids: str) -> dict[str, dict[str, Any]]:
    return {pid: {"injury_status": None, "active": True, "team": "KC",
                  "position": PLAYERS[pid][1]} for pid in player_ids}


ACTIVE_ALL = _all_active(*PLAYERS)


# --------------------------------------------------------------------- #
# availability classification
# --------------------------------------------------------------------- #

def test_no_snapshot_means_unknown_never_a_guess() -> None:
    avail = _availability(None)
    assert avail.classify("qb1").status is Status.UNKNOWN


def test_bye_week_is_out_even_with_clean_injury_status() -> None:
    statuses = _all_active("qb1")
    avail = _availability(statuses, byes=frozenset({"KC"}))
    status = avail.classify("qb1")
    assert status.status is Status.OUT
    assert "bye" in status.reason


def test_designations_classify() -> None:
    statuses = {
        "out": {"injury_status": "Out", "active": True, "team": "KC", "position": "RB"},
        "q": {"injury_status": "Questionable", "active": True, "team": "KC", "position": "RB"},
        "ir": {"injury_status": "IR", "active": True, "team": "KC", "position": "RB"},
        "fa": {"injury_status": None, "active": False, "team": None, "position": "RB"},
        "clean": {"injury_status": None, "active": True, "team": "KC", "position": "RB"},
        "weird": {"injury_status": "Mystery", "active": True, "team": "KC", "position": "RB"},
        "dst": {"injury_status": None, "active": False, "team": "KC", "position": "DEF"},
    }
    avail = _availability(statuses)
    assert avail.classify("out").status is Status.OUT
    assert avail.classify("q").status is Status.QUESTIONABLE
    assert avail.classify("ir").status is Status.OUT
    assert avail.classify("fa").status is Status.OUT
    assert avail.classify("clean").status is Status.ACTIVE
    assert avail.classify("weird").status is Status.QUESTIONABLE  # doubt, not green light
    assert avail.classify("dst").status is Status.ACTIVE  # team defense
    assert avail.classify("missing").status is Status.UNKNOWN


def test_confidence_gate_requires_both_active() -> None:
    active = PlayerStatus(Status.ACTIVE, "ok", "t")
    unknown = PlayerStatus(Status.UNKNOWN, "no snapshot", None)
    questionable = PlayerStatus(Status.QUESTIONABLE, "designated Questionable", "t")
    assert may_publish_confidence(active, active) == (True, None)
    assert may_publish_confidence(active, unknown)[0] is False
    assert may_publish_confidence(questionable, active)[0] is False


def test_bye_teams_from_schedule() -> None:
    schedule = {1: frozenset({"KC", "BUF", "NYJ", "MIA"}), 2: frozenset({"KC", "BUF"})}
    assert bye_teams_for_week(schedule, 2) == frozenset({"NYJ", "MIA"})
    assert bye_teams_for_week(schedule, 3) is None
    assert bye_teams_for_week(None, 1) is None


def test_load_week_availability_missing_snapshot(tmp_path: Path) -> None:
    avail = load_week_availability(tmp_path, "2025", 6)
    assert not avail.has_snapshot
    assert avail.classify("anyone").status is Status.UNKNOWN


def test_unknown_bye_data_never_concludes_active() -> None:
    """Review finding: without the schedule, 'no designation' must be UNKNOWN,
    not ACTIVE — a clean injury report on a bye week is still a zero."""
    statuses = {
        "clean": {"injury_status": None, "active": True, "team": "KC", "position": "RB"},
        "dst": {"injury_status": None, "active": False, "team": "KC", "position": "DEF"},
        "hurt": {"injury_status": "Out", "active": True, "team": "KC", "position": "RB"},
        "q": {"injury_status": "Questionable", "active": True, "team": "KC", "position": "RB"},
    }
    avail = _availability(statuses, byes=None)  # schedule unavailable
    assert avail.classify("clean").status is Status.UNKNOWN
    assert "bye status unknown" in avail.classify("clean").reason
    assert avail.classify("dst").status is Status.UNKNOWN
    # OUT/QUESTIONABLE stay decidable without the schedule.
    assert avail.classify("hurt").status is Status.OUT
    assert avail.classify("q").status is Status.QUESTIONABLE


# --------------------------------------------------------------------- #
# optimal lineup + gating
# --------------------------------------------------------------------- #

def _build(availability: WeekAvailability):
    season = _season()
    players = _player_index()
    model = ProjectionModel(season, players)
    mine = season.weeks[REPORT_WEEK][1]
    return optimal_lineup(season, mine, model, players, availability), season, players, model


def test_optimal_lineup_no_double_assignment_and_flex_gets_leftover() -> None:
    picks, season, players, model = _build(_availability(ACTIVE_ALL))
    assigned = [p.player_id for p in picks]
    assert len(assigned) == len(set(assigned)) == 4
    by_slot = {p.slot: p.player_id for p in picks}
    assert by_slot["QB"] == "qb1"
    assert by_slot["RB"] == "rb1"
    assert by_slot["WR"] == "wr1"
    # FLEX takes the highest-projected remaining eligible player under the
    # model (shrinkage can rank a steady RB over a similar WR — that's the
    # model's call, so assert consistency with it rather than a hardcoded pick).
    remaining = [pid for pid in ("rb2", "wr2", "wr3", "rk1")]
    expected = max(remaining, key=lambda pid: model.project(pid, REPORT_WEEK).mean)
    assert by_slot["FLEX"] == expected


def test_out_player_is_excluded_from_lineup() -> None:
    statuses = dict(ACTIVE_ALL)
    statuses["qb1"] = {"injury_status": "Out", "active": True, "team": "KC",
                       "position": "QB"}
    picks, *_ = _build(_availability(statuses))
    qb = next(p for p in picks if p.slot == "QB")
    assert qb.player_id == "qb2"  # backup seated, starter is Out


def test_confidence_prints_when_active_and_gates_when_unknown() -> None:
    picks_known, *_ = _build(_availability(ACTIVE_ALL))
    qb_known = next(p for p in picks_known if p.slot == "QB")
    assert qb_known.confidence is not None and qb_known.confidence > 0.9

    picks_unknown, *_ = _build(_availability(None))
    qb_unknown = next(p for p in picks_unknown if p.slot == "QB")
    assert qb_unknown.confidence is None
    assert "couldn't confirm who was active" in (qb_unknown.confidence_gate or "")


def test_thin_evidence_gates_before_availability() -> None:
    """A player with <3 games never gets a published number, even fully active."""
    picks, *_ = _build(_availability(ACTIVE_ALL))
    for pick in picks:
        if pick.alternative_id == "rk1" or pick.player_id == "rk1":
            assert pick.confidence is None
            assert "thin evidence" in (pick.confidence_gate or "")


def test_win_probability_calibration_gate_is_default() -> None:
    """Review finding: the matchup-level method failed its calibration bucket
    (backtest.md), so the number must not ship regardless of availability."""
    season = _season()
    players = _player_index()
    model = ProjectionModel(season, players)
    mine = season.weeks[REPORT_WEEK][1]
    rival = season.weeks[REPORT_WEEK][2]
    known = _availability(ACTIVE_ALL)
    my_picks = optimal_lineup(season, mine, model, players, known)
    rival_picks = rival_lineup(season, rival, model, players, known)
    prob, gate = win_probability(my_picks, rival_picks)
    assert prob is None and "not putting a win percentage" in (gate or "")


def test_win_probability_gates_on_any_non_active_starter(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """With the calibration flag flipped (future state), availability still gates."""
    import engine.week_report as wr
    monkeypatch.setattr(wr, "WIN_PROBABILITY_CALIBRATED", True)
    season = _season()
    players = _player_index()
    model = ProjectionModel(season, players)
    mine = season.weeks[REPORT_WEEK][1]
    rival = season.weeks[REPORT_WEEK][2]

    known = _availability(ACTIVE_ALL)
    my_picks = optimal_lineup(season, mine, model, players, known)
    rival_picks = rival_lineup(season, rival, model, players, known)
    prob, gate = win_probability(my_picks, rival_picks)
    assert gate is None and prob is not None and 0.5 < prob < 1.0

    unknown = _availability(None)
    my_unknown = optimal_lineup(season, mine, model, players, unknown)
    rival_unknown = rival_lineup(season, rival, model, players, unknown)
    prob2, gate2 = win_probability(my_unknown, rival_unknown)
    assert prob2 is None and "availability not confirmed" in (gate2 or "")


def test_truncated_rival_lineup_gates_win_probability() -> None:
    """Review finding: a short/empty rival starters array must not shrink the
    pick list past the gate and fabricate a near-100% win probability."""
    season = _season()
    players = _player_index()
    model = ProjectionModel(season, players)
    mine = season.weeks[REPORT_WEEK][1]
    truncated_rival = _team_week(2, REPORT_WEEK, RIVAL_ROSTER, ["qb9"])  # 1 of 4 set
    known = _availability(ACTIVE_ALL)
    my_picks = optimal_lineup(season, mine, model, players, known)
    rival_picks = rival_lineup(season, truncated_rival, model, players, known)
    assert len(rival_picks) == len(season.starting_slots)
    prob, gate = win_probability(my_picks, rival_picks)
    assert prob is None and gate is not None


def test_rule3_swap_seats_the_probability_winner() -> None:
    """Review finding: a high-mean/low-appearance player can be seated by mean
    while P(he beats the alternative) < 0.5 — the published call must follow
    the probability (decisions.py RULE 3), so the engine swaps."""
    from engine.history import Team
    boom = [50.0, 50.0, 50.0] + [0.0] * 14   # 3 huge games, then never plays
    steady = [6.0] * 17
    season = Season(
        league_id="222222222222222222", season="2025", name="Swap League",
        status="in_season", roster_positions=("WR", "BN", "BN"),
        playoff_week_start=None, scoring_settings={"rec": 1.0}, waiver_budget=100,
    )
    season.teams = {1: Team(1, "Me", "kevin", "u1")}
    for week in range(1, 18):
        points = {"boom": boom[week - 1], "steady": steady[week - 1]}
        season.weeks[week] = {1: TeamWeek(
            roster_id=1, week=week, matchup_id=1, starters=("steady",),
            starters_points=(points["steady"],), players=("boom", "steady"),
            players_points=points, points=points["steady"])}
    players = PlayerIndex({
        "boom": {"full_name": "Boom", "position": "WR", "fantasy_positions": ["WR"]},
        "steady": {"full_name": "Steady", "position": "WR", "fantasy_positions": ["WR"]},
    })
    model = ProjectionModel(season, players)
    week = 18
    boom_proj = model.project("boom", week)
    steady_proj = model.project("steady", week)
    avail = WeekAvailability(
        season="2025", week=week, snapshot_as_of="t",
        statuses={pid: {"injury_status": None, "active": True, "team": "KC",
                        "position": "WR"} for pid in ("boom", "steady")},
        bye_teams=frozenset())
    target = TeamWeek(roster_id=1, week=week, matchup_id=1, starters=("steady",),
                      starters_points=(0.0,), players=("boom", "steady"),
                      players_points={"boom": 0.0, "steady": 0.0}, points=0.0)
    picks = optimal_lineup(season, target, model, players, avail)
    pick = picks[0]
    # Precondition that makes this test meaningful: boom leads on mean.
    assert boom_proj.mean > steady_proj.mean
    # But the seat follows the probability, which favors steady.
    assert pick.player_id == "steady"
    assert pick.alternative_id == "boom"
    assert pick.confidence is not None and pick.confidence >= 0.5


def test_rival_bench_better_flag() -> None:
    season = _season()
    players = _player_index()
    model = ProjectionModel(season, players)
    rival = season.weeks[REPORT_WEEK][2]
    picks = rival_lineup(season, rival, model, players, _availability(ACTIVE_ALL))
    rb = next(p for p in picks if p.slot == "RB")
    assert any(f["kind"] == "bench_better" for f in rb.flags)  # rb8 (17) > rb9 (12)


def test_regret_is_closest_published_call() -> None:
    picks, _, players, _ = _build(_availability(ACTIVE_ALL))
    regret = regret_call(picks, players)
    assert "gate" not in regret
    published = [p.confidence for p in picks if p.confidence is not None]
    assert regret["confidence"] == round(min(published), 3)


def test_regret_gates_when_nothing_publishable() -> None:
    picks, _, players, _ = _build(_availability(None))
    regret = regret_call(picks, players)
    assert "gate" in regret


def test_hype_meter_counts_only_real_chases() -> None:
    season = _season()
    season.transactions[REPORT_WEEK - 1] = [
        {"type": "waiver", "status": "complete", "settings": {"waiver_bid": 21},
         "adds": {"wr2": 2}, "roster_ids": [2]},
        {"type": "waiver", "status": "failed", "settings": {"waiver_bid": 15},
         "adds": {"wr2": 1}, "roster_ids": [1]},
        {"type": "free_agent", "status": "complete", "adds": {"rk1": 1},
         "roster_ids": [1]},
    ]
    players = _player_index()
    hype = hype_meter(season, REPORT_WEEK, players, 100)
    assert hype and hype[0]["player_id"] == "wr2"
    assert hype[0]["managers_chasing"] == 2
    assert hype[0]["top_bid"] == 21
    assert "not calling this one" in hype[0]["verdict_gate"]  # a gap, not a guess
    assert all(e["player_id"] != "rk1" for e in hype)  # one quiet add isn't FOMO


def test_hype_meter_historical_render_excludes_report_week() -> None:
    """Review finding: a historical render must not read the report week's own
    transaction log — those moves happened after the games (lookahead)."""
    season = _season()
    season.status = "complete"
    season.transactions[REPORT_WEEK] = [
        {"type": "waiver", "status": "complete", "settings": {"waiver_bid": 30},
         "adds": {"wr2": 2}, "roster_ids": [2]},
        {"type": "waiver", "status": "failed", "settings": {"waiver_bid": 25},
         "adds": {"wr2": 1}, "roster_ids": [1]},
    ]
    players = _player_index()
    assert hype_meter(season, REPORT_WEEK, players, 100) == []
    season.status = "in_season"  # live: the same window is legitimately visible
    assert hype_meter(season, REPORT_WEEK, players, 100) != []


# --------------------------------------------------------------------- #
# rival watch (named rival vs weekly opponent)
# --------------------------------------------------------------------- #

def _watch(season_list, named_owner, named_roster=None):
    from engine.week_report import rival_watch
    season = season_list[0]
    players = _player_index()
    model = ProjectionModel(season, players)
    return rival_watch(season_list, REPORT_WEEK, 1, 2, named_owner, named_roster,
                       players, model, _availability(ACTIVE_ALL))


def test_rival_watch_rivalry_week_and_head_to_head() -> None:
    watch = _watch([_season()], "u2")
    assert watch is not None and watch["rivalry_week"] is True
    # Roster 1 outscores roster 2 in every played week (5 before week 6);
    # the unplayed 0-0 week must not count.
    assert watch["head_to_head"]["wins"] == 5
    assert watch["head_to_head"]["losses"] == 0


def test_rival_watch_absent_when_unconfigured() -> None:
    assert _watch([_season()], None, None) is None


def test_rival_watch_owner_left_gates() -> None:
    watch = _watch([_season()], "u999")
    assert watch is not None and "gate" in watch


def test_rival_watch_off_week_tracks_their_matchup() -> None:
    from engine.history import Team
    season = _season()
    # Add a second matchup so the named rival is NOT this week's opponent.
    season.teams[3] = Team(3, "Third Team", "carol", "u3")
    season.teams[4] = Team(4, "Fourth Team", "dave", "u4")
    for week in range(1, REPORT_WEEK + 1):
        season.weeks[week][3] = _team_week(3, week, RIVAL_ROSTER,
                                           ["qb9", "rb9", "wr9", "fx9"], matchup_id=2)
        season.weeks[week][4] = _team_week(4, week, MY_ROSTER,
                                           ["qb1", "rb1", "wr1", "wr2"], matchup_id=2)
    watch = _watch([season], "u3")
    assert watch is not None and watch["rivalry_week"] is False
    assert watch["their_opponent"] == "Fourth Team (dave)"
    assert watch["their_record"] == "0-5"  # roster 3 loses to roster 4 weekly
    assert watch["fragile_spots"] >= 1     # rb8 outprojects their started rb9
    # Never played them: head-to-head is 0-0 with an honest evidence string.
    assert watch["head_to_head"]["wins"] == 0
    assert watch["head_to_head"]["losses"] == 0


def test_matchup_backtest_rules() -> None:
    from engine.matchup_backtest import band_coverage, matchup_calls
    season = _season()
    players = _player_index()
    model = ProjectionModel(season, players)
    calls, skipped = matchup_calls(season, model)
    assert calls, "later weeks have projections for every starter"
    for call in calls:
        assert call.confidence >= 0.5  # favorite defined by probability
        # My team outscores the rival every synthetic week, so whenever it is
        # the favorite the call must grade HIT (RULE M3 on actual points).
        if call.favorite.roster_id == 1:
            assert call.outcome == "hit"
    covered, total = band_coverage(calls)
    assert total == 2 * len(calls) and 0 <= covered <= total


# --------------------------------------------------------------------- #
# full report via the real cache layout on disk
# --------------------------------------------------------------------- #

def _write_cache(tmp_path: Path, season: Season) -> Path:
    raw = tmp_path / "raw"
    league_dir = raw / "league" / season.league_id
    (league_dir / "matchups").mkdir(parents=True)
    league_dir.joinpath("league.json").write_text(json.dumps({
        "league_id": season.league_id, "season": season.season,
        "name": season.name, "status": season.status,
        "roster_positions": list(season.roster_positions),
        "settings": {"playoff_week_start": 15, "waiver_budget": 100},
        "scoring_settings": {"rec": 1.0},
    }), encoding="utf-8")
    league_dir.joinpath("users.json").write_text(json.dumps([
        {"user_id": "u1", "display_name": "kevin",
         "metadata": {"team_name": "My Team"}},
        {"user_id": "u2", "display_name": "mike",
         "metadata": {"team_name": "<script>alert(1)</script>"}},
    ]), encoding="utf-8")
    league_dir.joinpath("rosters.json").write_text(json.dumps([
        {"roster_id": 1, "owner_id": "u1"},
        {"roster_id": 2, "owner_id": "u2"},
    ]), encoding="utf-8")
    for week, teams in season.weeks.items():
        records = []
        for tw in teams.values():
            records.append({
                "roster_id": tw.roster_id, "matchup_id": tw.matchup_id,
                "starters": list(tw.starters),
                "starters_points": list(tw.starters_points),
                "players": list(tw.players),
                "players_points": dict(tw.players_points),
                "points": tw.points,
            })
        (league_dir / "matchups" / f"week_{week:02d}.json").write_text(
            json.dumps(records), encoding="utf-8")
    players_raw = {
        pid: {"full_name": name, "position": pos, "fantasy_positions": [pos]}
        for pid, (name, pos, _) in PLAYERS.items()
    }
    (raw / "players").mkdir(parents=True)
    (raw / "players" / "nfl.json").write_text(json.dumps(players_raw), encoding="utf-8")
    # Schedule: KC plays every week, so bye status is knowable and empty.
    (raw / "schedule").mkdir(parents=True)
    (raw / "schedule" / f"nfl_regular_{season.season}.json").write_text(json.dumps([
        {"week": w, "home": "KC", "away": "BUF", "status": "complete",
         "date": f"2025-10-{w:02d}"} for w in range(1, 18)
    ]), encoding="utf-8")
    return raw


def test_build_week_report_end_to_end(tmp_path: Path) -> None:
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, REPORT_WEEK, 1)

    assert report["meta"]["rival_roster_id"] == 2
    assert len(report["lineup"]) == 4
    # No snapshot on disk: everything gated, and the gap is declared.
    assert all(s["confidence"] is None for s in report["lineup"])
    assert any(g["field"] == "availability" for g in report["meta"]["gaps"])
    assert report["matchup"]["win_probability"] is None
    assert report["meta"]["llm_tokens"] == 0
    # No availability snapshots for past weeks -> nothing was publishable,
    # so the ledger is honestly empty rather than graded hypotheticals.
    assert report["receipts"]["record"] is None
    assert "Ledger opens" in report["receipts"]["note"]


def test_build_week_report_unknown_week_is_actionable(tmp_path: Path) -> None:
    season = _season()
    raw = _write_cache(tmp_path, season)
    from engine.week_report import WeekReportError
    with pytest.raises(WeekReportError, match="not in the cache"):
        build_week_report(raw, season.league_id, 12, 1)


# --------------------------------------------------------------------- #
# renderer
# --------------------------------------------------------------------- #

def _template() -> str:
    return (Path(__file__).resolve().parent.parent / "rival-report-template.html"
            ).read_text(encoding="utf-8")


def test_render_escapes_hostile_team_name(tmp_path: Path) -> None:
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, REPORT_WEEK, 1)
    html_out = render(report, _template())
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_render_gates_and_disclaimer(tmp_path: Path) -> None:
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, REPORT_WEEK, 1)
    html_out = render(report, _template())
    assert "Not calling it" in html_out          # gates visible, not hidden
    assert "not guarantees" in html_out          # disclaimer footer present
    assert "Mike's Marauders" not in html_out    # no sample-data leakage
    assert "Not affiliated with Sleeper" in html_out
    assert html_out.count('<div class="lrow head">') == 2  # both lineup grids


def test_render_shows_numbers_when_available(tmp_path: Path) -> None:
    season = _season()
    raw = _write_cache(tmp_path, season)
    # Write a snapshot covering the report week: everything active.
    snap_dir = raw / "availability" / season.season
    snap_dir.mkdir(parents=True)
    (snap_dir / f"regular_week_{REPORT_WEEK:02d}.json").write_text(json.dumps({
        "as_of": "2025-10-09T12:00:00+00:00", "season": season.season,
        "season_type": "regular", "week": REPORT_WEEK,
        "statuses": ACTIVE_ALL,
    }), encoding="utf-8")
    report = build_week_report(raw, season.league_id, REPORT_WEEK, 1)
    # Slot confidences publish (availability known)...
    assert any(s["confidence"] is not None for s in report["lineup"])
    # ...but the matchup win probability stays calibration-gated for now.
    assert report["matchup"]["win_probability"] is None
    assert "not putting a win percentage" in report["matchup"]["win_probability_gate"]
    html_out = render(report, _template())
    # Ranges render on their own evidence, independent of the prob gate.
    assert "realistic range" in html_out
    assert "realistic high and low" in html_out.lower()


def test_render_ball_position_tracks_probability(tmp_path: Path) -> None:
    """Review finding: the ball graphic was inverted. Higher win probability
    must put the ball deeper in RIVAL territory (further right)."""
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, REPORT_WEEK, 1)
    report["matchup"]["win_probability"] = 0.61  # simulate the future un-gated state
    html_out = render(report, _template())
    assert 'class="ball" style="left:61%"' in html_out
    assert "61% win probability" in html_out


def test_untrusted_season_string_is_rejected(tmp_path: Path) -> None:
    """Review finding: the season string flows into report file paths."""
    season = _season()
    raw = _write_cache(tmp_path, season)
    league_file = raw / "league" / season.league_id / "league.json"
    doc = json.loads(league_file.read_text(encoding="utf-8"))
    doc["season"] = "../../evil"
    league_file.write_text(json.dumps(doc), encoding="utf-8")
    from engine.week_report import WeekReportError
    with pytest.raises(WeekReportError, match="not a plausible year"):
        build_week_report(raw, season.league_id, REPORT_WEEK, 1)


# --------------------------------------------------------------------- #
# Week 1: the model has no record and must say so, not fabricate
# --------------------------------------------------------------------- #

def test_week_one_gates_totals_instead_of_printing_zeros(tmp_path: Path) -> None:
    """With no prior weeks there is nothing to project from. The old behavior
    summed an empty generator and published 'proj 0.0 · floor 0 · ceiling 0'
    under a '78% of the time' basis line — a fabricated band in the paying
    subscriber's FIRST report, inside the refund window."""
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, 1, 1)
    matchup = report["matchup"]
    assert matchup["range_gate"], "week 1 must gate the totals"
    assert "projected_total" not in matchup["you"]
    assert "floor" not in matchup["you"] and "ceiling" not in matchup["rival"]
    assert any(g["field"] == "team_ranges" for g in report["meta"]["gaps"])


def test_week_one_checklist_never_claims_agreement(tmp_path: Path) -> None:
    """'We agree with your lineup' and 'we have nothing to compare it to' are
    different sentences. A model holding zero projections must not endorse."""
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, 1, 1)
    first = report["checklist"][0]["action"]
    assert "the one we'd set" not in first
    assert "No lineup call yet" in first


def test_week_one_render_carries_no_fabricated_numbers(tmp_path: Path) -> None:
    import re
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, 1, 1)
    html = render(report, _template())
    text = re.sub(r"<[^>]+>", " ", html)
    assert not re.search(r"floor 0\b|ceiling 0\b", text)
    assert not re.search(r"0\.0\s+PROJ", text)
    assert "no projected totals yet" in text


def test_data_rich_weeks_still_publish_the_band(tmp_path: Path) -> None:
    """The gate must fire on absence only — the established mid-season path
    keeps its totals, floor and ceiling exactly as before."""
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, REPORT_WEEK, 1)
    matchup = report["matchup"]
    assert matchup["range_gate"] is None
    assert matchup["you"]["projected_total"] > 0
    assert matchup["you"]["floor"] < matchup["you"]["ceiling"]


def test_week_one_shows_the_lineup_as_set_never_empty_rows(tmp_path: Path) -> None:
    """The fresh-eyes review reproduced the first paid report rendering the
    subscriber's own lineup as nine '(empty)' rows — the model held no opinion,
    so no slot could be filled. The honest render is the lineup AS SET (the
    rival grid's treatment), plainly titled, with calls dated."""
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, 1, 1)
    assert report["meta"]["lineup_as_set"] is True
    named = [s for s in report["lineup"] if s.get("player_name")]
    assert len(named) == len(season.starting_slots) - sum(
        1 for s in report["lineup"] if s["slot"] == "BN")
    assert named, "the set starters must appear"
    html = render(report, _template())
    assert "(empty)" not in html
    assert "Your Lineup — As Set" in html
    assert "Your Optimal Lineup" not in html


def test_mid_season_still_claims_optimal(tmp_path: Path) -> None:
    season = _season()
    raw = _write_cache(tmp_path, season)
    report = build_week_report(raw, season.league_id, REPORT_WEEK, 1)
    assert report["meta"]["lineup_as_set"] is False
    html = render(report, _template())
    assert "Your Optimal Lineup" in html


def test_the_checklist_decides_rather_than_asking() -> None:
    """Section 01 is written for someone who reads nothing else, so it must carry
    the verdict the engine already computed — not hand back the question while
    the answer sits four sections lower in the waiver block."""
    import json as _json
    report = _json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "processed" /
         "week_report.json").read_text(encoding="utf-8"))
    waiver = [c["action"] for c in report["checklist"]
              if "waivers clear" in c["deadline"]]
    if not waiver:
        return  # a quiet waiver week has no item to decide
    action = waiver[0]
    assert not action.startswith("Decide on"), \
        "the checklist asked a question the engine had already answered"
    assert action.startswith(("Skip ", "Bid ")), action
