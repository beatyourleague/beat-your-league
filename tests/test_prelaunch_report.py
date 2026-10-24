"""Pre-launch review, Oct 2026 — the report's own fixes (build agent "report").

Each test's docstring carries the reproduction it guards. Grouped by finding:
F1 (the Saturday check read a practice-only file as Friday's final report),
F2 (the Tuesday build trusted posted scores instead of the clock), F3 (odds
printed against a bench player whose role the same report calls rising), F5
(bye cover), F6/D13 (game-plan order and the byes item), F7 (the Saturday
line), M5 (the free report's price and refund terms).
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.saturday as saturday
from engine.final_check import BACK, Now, final_check, worth_sending
from run import solo


def _write(path: Path, rows: list[dict], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


# --------------------------------------------------------------------- #
# F1 — a practice report is not a final report
# --------------------------------------------------------------------- #

SAT_4PM = datetime(2026, 10, 24, 16, tzinfo=timezone.utc)
SUN_1PM = datetime(2026, 10, 25, 17, tzinfo=timezone.utc)
MON_NIGHT = datetime(2026, 10, 27, 0, 15, tzinfo=timezone.utc)
INJURY_FIELDS = ["season", "season_type", "game_type", "team", "week", "gsis_id",
                 "full_name", "report_primary_injury", "report_status",
                 "practice_primary_injury", "practice_status"]
SUNDAY_TEAMS = ["ARI", "ATL", "BAL", "CAR", "CIN", "CLE", "DEN", "DET", "GB",
                "HOU", "IND", "KC", "LA", "LV", "MIA", "MIN", "NO", "NYG", "NYJ",
                "PIT", "SEA", "SF", "TB", "TEN"]


def _practice_only_week(tmp_path: Path, monkeypatch, *, with_status=("PIT",)) -> None:
    """The shape of the real 2026 Week-7 file fetched Fri Oct 23: practice
    rows for every team, a game status for only a few of them."""
    rows = []
    for team in SUNDAY_TEAMS:
        rows.append({"season": "2026", "season_type": "REG", "game_type": "REG",
                     "team": team, "week": "7", "gsis_id": f"00-{team}1",
                     "full_name": f"{team} Starter", "report_primary_injury": "",
                     "report_status": "", "practice_primary_injury": "Hamstring",
                     "practice_status": "Did Not Participate In Practice"})
    for team in with_status:
        rows.append({"season": "2026", "season_type": "REG", "game_type": "REG",
                     "team": team, "week": "7", "gsis_id": f"00-{team}2",
                     "full_name": f"{team} Listed", "report_primary_injury": "Knee",
                     "report_status": "Questionable", "practice_primary_injury": "Knee",
                     "practice_status": "Limited Participation in Practice"})
    path = _write(tmp_path / "injuries_2026.csv", rows, INJURY_FIELDS)
    monkeypatch.setattr(saturday, "_fetch", lambda *a, **k: path)


def test_a_practice_only_file_is_not_the_final_report(tmp_path, monkeypatch) -> None:
    """Reproduction (pre-launch review F1): the cached injuries_2026.csv of Fri
    Oct 23 held 335 Week-7 rows across 28 teams, game statuses for 3 of them.
    run/saturday counted a team as filed on ANY row, so at Sat 16:00 UTC the
    check read 26 of 26 pending teams as filed and passed. A team counts once
    it carries a game status, and the floor refuses."""
    _practice_only_week(tmp_path, monkeypatch)
    listed, filed = saturday.designations(tmp_path, "2026", 7)
    assert filed == {"PIT"}
    starts = {team: SUN_1PM for team in SUNDAY_TEAMS}
    with pytest.raises(saturday.SaturdayError, match="isn't in yet"):
        saturday.check_report_is_in(starts, filed, SAT_4PM, 7)


def test_a_player_who_sat_out_practice_all_week_is_not_mailed_back_in(
        tmp_path, monkeypatch) -> None:
    """Reproduction: a roster holding Rashee Rice (Out in Week 6, DNP all of
    Week 7, no game status yet) was mailed "start Rashee Rice at FLEX over Pat
    Freiermuth … off the injury report" — final_check's BACK rule reads a
    player as cleared once his team's report is final. On a practice-only
    file his team's report is not final, so nothing is sent."""
    _practice_only_week(tmp_path, monkeypatch)
    listed, filed = saturday.designations(tmp_path, "2026", 7)
    roster = {"00-KC1": ("ACT", "KC"), "flex": ("ACT", "PIT")}
    starts = {team: SUN_1PM for team in SUNDAY_TEAMS}
    rice = saturday.state_for("00-KC1", starts=starts, listed=listed, filed=filed,
                              roster=roster, at=SAT_4PM)
    assert rice.designation is None and not rice.final
    plan = {"season": "2026", "week": 7, "slug": "abc",
            "slots": [{"slot": "FLEX", "player_id": "flex"}],
            "players": {
                "flex": {"name": "Pat Freiermuth", "position": "TE", "projected": 7.0,
                         "last_season": None, "tuesday": "active"},
                "00-KC1": {"name": "Rashee Rice", "position": "WR", "projected": 14.0,
                           "last_season": None, "tuesday": "out"}}}
    now = {"flex": Now(final=True, kickoff=SUN_1PM), "00-KC1": rice}
    changes = final_check(plan, now)
    assert not [c for c in changes if c.kind == BACK] and not worth_sending(changes)


def test_the_floor_counts_only_teams_whose_final_report_is_due(tmp_path,
                                                                 monkeypatch) -> None:
    """A Monday-night team files its final report on Saturday, so on Saturday
    it is not due: a complete Sunday report must pass even when several
    Monday-night teams have posted nothing yet."""
    _practice_only_week(tmp_path, monkeypatch, with_status=SUNDAY_TEAMS[:12])
    listed, filed = saturday.designations(tmp_path, "2026", 7)
    starts = {team: SUN_1PM for team in SUNDAY_TEAMS[:12]}
    starts.update({team: MON_NIGHT for team in SUNDAY_TEAMS[12:]})
    saturday.check_report_is_in(starts, filed, SAT_4PM, 7)          # passes
    monday = saturday.state_for("00-SEA1", starts=starts, listed=listed,
                                filed=filed | {"SEA"},
                                roster={"00-SEA1": ("ACT", "SEA")}, at=SAT_4PM)
    assert not monday.final, "a Monday-night team's report is not final on Saturday"
    sunday = saturday.state_for("00-ARI1", starts=starts, listed=listed, filed=filed,
                                roster={"00-ARI1": ("ACT", "ARI")}, at=SAT_4PM)
    assert sunday.final and sunday.designation is None


# --------------------------------------------------------------------- #
# F2 — the week projected from must be complete, by the clock
# --------------------------------------------------------------------- #

GAME_FIELDS = ["season", "game_type", "week", "gameday", "gametime", "away_team",
               "home_team", "away_score", "home_score"]


def _games(tmp_path: Path, games: list[tuple]) -> Path:
    """games: (week, gameday, gametime, away, home, scored)."""
    rows = [{"season": "2026", "game_type": "REG", "week": w, "gameday": day,
             "gametime": clock, "away_team": away, "home_team": home,
             "away_score": 17 if scored else "", "home_score": 24 if scored else ""}
            for w, day, clock, away, home, scored in games]
    cache = tmp_path / "nflverse"
    _write(cache / "games.csv", rows, GAME_FIELDS)
    return cache


def _rows(*teams: str) -> dict:
    return {f"00-{t}": {"team": t} for t in teams}


WEEK7 = [(7, "2026-10-22", "20:15", "NE", "CHI", True),
         (7, "2026-10-25", "13:00", "SF", "ATL", True),
         (7, "2026-10-26", "20:15", "DAL", "PHI", True)]
TUESDAY = datetime(2026, 10, 27, 16, 17, tzinfo=timezone.utc)


def test_a_complete_prior_week_passes(tmp_path) -> None:
    cache = _games(tmp_path, WEEK7)
    weekly = {7: _rows("NE", "CHI", "SF", "ATL", "DAL", "PHI")}
    solo.assert_week_is_complete(cache, "2026", 8, weekly, now=TUESDAY)


def test_a_stale_schedule_with_one_game_scored_refuses(tmp_path) -> None:
    """Reproduction (pre-launch review F2): week 8 built with today=Oct 27 on
    files where week 7 carried a score and stat rows for NE@CHI only. The old
    guard read "final" from posted scores, found {CHI, NE} and passed, and
    every player on the other 26 teams was counted as having missed week 7
    (Goff appear 0.98 -> 0.84, projection 21.4 -> 16.9) while odds printed."""
    stale = [(7, "2026-10-22", "20:15", "NE", "CHI", True),
             (7, "2026-10-25", "13:00", "SF", "ATL", False),
             (7, "2026-10-26", "20:15", "DAL", "PHI", False)]
    cache = _games(tmp_path, stale)
    with pytest.raises(solo.SoloError, match="SF@ATL, DAL@PHI kicked off more than 8 hours"):
        solo.assert_week_is_complete(cache, "2026", 8, {7: _rows("NE", "CHI")},
                                     now=TUESDAY)


def test_scores_without_stat_rows_refuse(tmp_path) -> None:
    cache = _games(tmp_path, WEEK7)
    with pytest.raises(solo.SoloError, match="no rows for it"):
        solo.assert_week_is_complete(
            cache, "2026", 8, {7: _rows("NE", "CHI", "SF", "ATL")}, now=TUESDAY)


def test_a_game_still_being_played_refuses(tmp_path) -> None:
    """At 00:47 UTC on a Tuesday the UTC date already says the week ahead
    while Monday night is being played: the hourly runs built week 8 with the
    MNF teams counted as having missed week 7."""
    in_progress = WEEK7[:2] + [(7, "2026-10-26", "20:15", "DAL", "PHI", False)]
    cache = _games(tmp_path, in_progress)
    during = datetime(2026, 10, 27, 0, 47, tzinfo=timezone.utc)
    with pytest.raises(solo.SoloError, match="DAL@PHI is not over and in yet"):
        solo.assert_week_is_complete(
            cache, "2026", 8, {7: _rows("NE", "CHI", "SF", "ATL")}, now=during)


def test_week_one_and_an_unreadable_schedule_are_not_checked(tmp_path) -> None:
    solo.assert_week_is_complete(tmp_path / "empty", "2026", 1, {})
    solo.assert_week_is_complete(_games(tmp_path, []), "2026", 8, {}, now=TUESDAY)


def test_a_live_report_dates_its_box_scores_beside_the_injury_data() -> None:
    """Principle 3: the injury line dated its data and the box scores the
    projections stand on were dated nowhere."""
    from render.report import availability_basis
    meta = {"availability_as_of": "the week 6 injury report, the last complete "
                                  "one before this report goes out",
            "box_scores_as_of": solo.box_scores_line(7)}
    assert availability_basis(meta).endswith("Box scores through Week 6, every game.")
    assert "Box scores" not in availability_basis({"availability_as_of": "x"})
    assert solo.box_scores_line(1) is None


# --------------------------------------------------------------------- #
# F3 — no odds against a bench player whose role is growing
# --------------------------------------------------------------------- #

def _solo(rising=None) -> dict:
    """A small solo report through the real builders (tests/test_email's
    shape), optionally with rising candidates."""
    from engine.availability import WeekAvailability
    from engine.projection import ProjectionModel
    from engine.roster import Player, PlayerDirectory
    from engine.solo_report import build_solo_report
    from engine.subscriber import RosterSpec, build_season, player_index

    people = [Player(f"00-000000{i}", n, p, "KC") for i, (n, p) in enumerate(
        [("Star Passer", "QB"), ("Bell Cow", "RB"), ("Committee Back", "RB"),
         ("Alpha Wideout", "WR"), ("Slot Wideout", "WR"), ("Starting Tight", "TE"),
         ("Deep Wideout", "WR")], start=1)]
    directory = PlayerDirectory(people)
    ids = tuple(p.player_id for p in people)
    weekly = {w: {pid: {"receiving_yards": 80 + 10 * i}
                  for i, pid in enumerate(ids)} for w in (1, 2, 3, 4)}
    spec = RosterSpec(player_ids=ids, scoring="ppr", label="Your Team",
                      slots=("QB", "RB", "WR", "TE", "FLEX"))
    season = build_season(spec, weekly, directory, "2026", 5, league_size=12)
    players = player_index(directory)
    model = ProjectionModel(season, players)
    statuses = {pid: {"team": "KC", "position": players.position(pid),
                      "active": True, "injury_status": None} for pid in ids}
    availability = WeekAvailability(season="2026", week=5, snapshot_as_of="2026-w4",
                                    statuses=statuses, bye_teams=frozenset())
    return build_solo_report(spec, season, players, model, availability, 5,
                             Path("/nonexistent"), rising=rising)


def _riser(pid: str, **extra) -> dict:
    return {"player_id": pid, "position": "WR", "team": "KC", "recent": 17.5,
            "earlier": 6.5, "jump": 11.0, "earlier_weeks": [1, 2], "missed": [],
            **extra}


def test_odds_against_a_rising_bench_player_are_withheld_and_the_seat_kept() -> None:
    """Reproduction (pre-launch review F3): roster r2's Week-7 email printed
    "George Pickens 11.2 57% vs Malik Nabers" while the same email listed
    Nabers under Rising Roles. Over 10,098 graded calls from the shipped
    harness, calls whose BENCH option was rising stated 63.5% and landed
    55.7% (n=508). Withheld, never recomputed: same seats, same projections,
    every other number unchanged."""
    from engine.solo_report import RISING_GATE
    from render.report import gate_phrase, row_label
    base = _solo()
    called = [r for r in base["lineup"] if r.get("confidence") is not None]
    assert called, "the fixture needs a call to withhold"
    target = called[0]
    held = _solo(rising={target["alternative_id"]: _riser(target["alternative_id"])})
    for before, after in zip(base["lineup"], held["lineup"]):
        assert (before["player_id"], before["projected"]) == (after["player_id"],
                                                               after["projected"])
        if before["alternative_id"] == target["alternative_id"]:
            assert after["confidence"] is None
            assert after["confidence_gate"].startswith(RISING_GATE)
            assert row_label(after) == f"start · {target['alternative_name']} rising"
        else:
            assert after["confidence"] == before["confidence"]
    assert "more of the ball" in gate_phrase(RISING_GATE)
    [line] = [i for i in held["checklist"] if "no odds against" in i["action"]]
    assert target["alternative_name"] in line["action"]
    assert ("17.5 targets + carries a game over his last two, up from 6.5 in Weeks "
            "1–2" in line["detail"])
    assert "%" not in line["action"] + line["detail"]
    assert "your call" not in line["detail"].lower()


def test_a_rising_starter_keeps_his_odds() -> None:
    """Only the BENCH side ran high; a rising starter's odds ran low (stated
    67.8, hit 72.5) — the safe direction — so his number stands."""
    base = _solo()
    target = next(r for r in base["lineup"] if r.get("confidence") is not None)
    held = _solo(rising={target["player_id"]: _riser(target["player_id"])})
    row = next(r for r in held["lineup"] if r["player_id"] == target["player_id"])
    assert row["confidence"] == target["confidence"]


def test_the_report_holds_only_on_the_measured_definition(tmp_path, monkeypatch) -> None:
    """report_for passes the league-wide pool with RETURNS left out (weeks
    missed before the jump): the definition the 508-call subset was measured
    on. A player coming back from injury is not a growing role."""
    import dataclasses
    from test_solo_run import OFFLINE, SEASON, WEEK, _cache, _spec
    seen = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("captured")
    data = solo.load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE)
    data = dataclasses.replace(data, rising=[_riser("00-a"),
                                             _riser("00-b", missed=[2])])
    monkeypatch.setattr(solo, "build_solo_report", capture)
    with pytest.raises(RuntimeError, match="captured"):
        solo.report_for(_spec(), data)
    assert set(seen["rising"]) == {"00-a"}
    monkeypatch.setattr(solo, "RISING_ALTERNATIVE_HOLD", False)
    with pytest.raises(RuntimeError, match="captured"):
        solo.report_for(_spec(), data)
    assert seen["rising"] is None


# --------------------------------------------------------------------- #
# F5 / QA-02 / P2 — cover per emptied slot, outside the likely-rostered top
# --------------------------------------------------------------------- #

def _cover_data(players, form, *, byes=None, games=None, listed=None, week=8,
                defenses=None):
    from types import SimpleNamespace
    weekly = {1: {}}
    for pid, points_allowed in (defenses or {}).items():
        for w in (1, 2, 3):
            weekly.setdefault(w, {})[pid] = {"def_sacks": 3,
                                              "points_allowed": points_allowed}
    return SimpleNamespace(
        weekly=weekly, week=week, directory=SimpleNamespace(players=players),
        season_byes=byes or {}, roster_out={}, not_active={}, practice_squad={},
        games=games or {}, listed=listed or {}, is_live_week=True,
        availability=SimpleNamespace(statuses={}), _form=form)


def _player(pid, position, team):
    from types import SimpleNamespace
    return SimpleNamespace(player_id=pid, name=f"P {pid}", position=position, team=team)


def test_every_emptied_slot_gets_its_own_list_outside_the_likely_rostered(
        monkeypatch) -> None:
    """Reproduction (pre-launch review F5/QA-02): r5's Week-8 hole read "DEF,
    K, QB and TE spots empty … options: Josh Allen 26.9, Jared Goff 23.0,
    Bryce Young 22.1" — one ranking across every slot, so only quarterbacks
    were ever named, and the league's top three at that, rostered in every
    12-team league. Each slot now gets its own list, the top (league size ×
    starting slots) at the position are left out and the line says so, and
    team defenses are named on their own record."""
    import engine.preseason as preseason
    from types import SimpleNamespace
    qbs = [_player(f"00-q{i}", "QB", f"T{i}") for i in range(6)]
    tes = [_player(f"00-t{i}", "TE", f"T{i}") for i in range(4)]
    defs = [_player(f"DEF-D{i}", "DEF", f"D{i}") for i in range(4)]
    form = {p.player_id: {"per_game": 30.0 - i, "games": 5} for i, p in enumerate(qbs)}
    form.update({p.player_id: {"per_game": 12.0 - i, "games": 5} for i, p in enumerate(tes)})
    monkeypatch.setattr(preseason, "prior_season_form",
                        lambda weekly, rule: dict(form))
    data = _cover_data(qbs + tes + defs, form,
                       defenses={"DEF-D0": 0, "DEF-D1": 10, "DEF-D2": 20, "DEF-D3": 30})
    spec = SimpleNamespace(rule="ppr", player_ids=(), slots=("QB", "TE", "K", "DEF"))
    cover = solo.cover_for(["DEF", "QB", "TE"], spec, data, set(), week=8, league_size=2)
    by_slot = {entry["slot"]: entry for entry in cover}
    # Two teams, one QB slot: the top two QBs are left out.
    assert [c["name"] for c in by_slot["QB"]["names"]] == ["P 00-q2", "P 00-q3", "P 00-q4"]
    assert by_slot["QB"]["cut"] == "outside the top 2"
    assert [c["name"] for c in by_slot["TE"]["names"]] == ["P 00-t2", "P 00-t3"]
    # Defenses on their own scored record (fewest points allowed scores most).
    assert [c["name"] for c in by_slot["DEF"]["names"]] == ["P DEF-D2", "P DEF-D3"]
    from engine.solo_report import cover_parts
    said = cover_parts(cover)
    assert said.startswith("QB, outside the top 2: P 00-q2 28.0")   # lineup order
    assert "%" not in said
    # A TE hole and a FLEX hole the same week: nobody is named twice.
    te, flex = solo.cover_for(["TE", "FLEX"], spec, data, set(), week=8, league_size=0)
    assert [c["name"] for c in te["names"]] == ["P 00-t0", "P 00-t1", "P 00-t2"]
    assert [c["name"] for c in flex["names"]] == ["P 00-t3"]


def test_the_rostered_cut_counts_the_flex_and_superflex_slots() -> None:
    standard = solo.rostered_cut(("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"), 12)
    assert standard == {"QB": 12, "RB": 36, "WR": 36, "TE": 12, "K": 12, "DEF": 12}
    superflex = solo.rostered_cut(("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"), 10)
    assert superflex["QB"] == 20


def test_this_weeks_zero_names_cover_who_play_late_enough(monkeypatch) -> None:
    """Reproduction (pre-launch review P2): "Lamar Jackson (QB) was out on last
    week's injury report … that's a zero unless you add someone off waivers"
    named nobody, nor did a kicker on bye. The line now names who could fill
    it this week — playing this week, not on last week's injury report, and,
    for a starter who may still play, kicking off no earlier than him so the
    pickup can wait for his news."""
    import engine.preseason as preseason
    from types import SimpleNamespace
    starter = _player("00-mine", "QB", "BAL")
    early = _player("00-thu", "QB", "THU")           # plays Thursday: too early
    listed = _player("00-hurt", "QB", "SUN")         # on last week's report
    late = _player("00-late", "QB", "SNF")
    bye = _player("00-bye", "QB", "BYE")
    form = {p.player_id: {"per_game": 20.0 - i, "games": 5}
            for i, p in enumerate([early, listed, late, bye])}
    monkeypatch.setattr(preseason, "prior_season_form", lambda weekly, rule: dict(form))
    games = {"BAL": {"day": "2026-10-25", "time": "13:00"},
             "THU": {"day": "2026-10-22", "time": "20:15"},
             "SUN": {"day": "2026-10-25", "time": "13:00"},
             "SNF": {"day": "2026-10-25", "time": "20:20"}}
    data = _cover_data([starter, early, listed, late, bye], form, games=games,
                       listed={"00-hurt": ("questionable", "knee")}, week=7)
    spec = SimpleNamespace(rule="ppr", player_ids=("00-mine",), slots=("QB",))
    monkeypatch.setattr(solo, "_row_teams", lambda spec, data: {"00-mine": "BAL"})
    report = {"checklist": [{"action": "Lamar (QB) was out …", "deadline": "x",
                             "urgency": "now",
                             "zero": {"slots": ["QB"], "wait_on": ["00-mine"]}}]}
    solo._this_week_cover(report, spec, data, league_size=0)
    detail = report["checklist"][0]["detail"]
    assert "kicking off no earlier than him" in detail
    assert "P 00-late 18.0" in detail
    for absent in ("00-thu", "00-hurt", "00-bye", "00-mine"):
        assert absent not in detail
    assert detail.endswith("Check who's free in your league.")
    data.is_live_week = False                       # a replayed week names nobody
    replay = {"checklist": [dict(report["checklist"][0], detail=None)]}
    solo._this_week_cover(replay, spec, data, league_size=0)
    assert not replay["checklist"][0]["detail"]


# --------------------------------------------------------------------- #
# F6 / D13 — stakes first, a short byes line, the subject leads with a hole
# --------------------------------------------------------------------- #

def test_zero_lines_lead_the_game_plan() -> None:
    """Reproduction (pre-launch review F6): "Tyler Bass isn't playing — that's
    a zero" was item 5 of 7 in r3's plan, after three benchings and the
    lineup that started him."""
    from engine.solo_report import by_stakes
    notable = [{"action": "Bench RJ Harvey"}]
    plan = [{"action": "Set this lineup"},
            {"action": "Lamar out last week", "zero": {"slots": ["QB"], "wait_on": ["x"]}},
            {"action": "Tyler Bass isn't playing", "zero": {"slots": ["K"], "certain": True}},
            {"action": "Sunday morning"}]
    assert [i["action"] for i in by_stakes(notable, plan)] == [
        "Tyler Bass isn't playing", "Lamar out last week", "Bench RJ Harvey",
        "Set this lineup", "Sunday morning"]


def test_the_subject_and_preview_lead_with_an_empty_spot() -> None:
    """Reproduction: the Week-8 bye week for r5 — four starters with nobody to
    replace them — went out as "your lineup, decided", previewing "Closest
    call: start Michael Wilson over Rachaad White, 55%"."""
    from render.email import preheader_for, subject_for
    report = _solo()
    assert subject_for(report).endswith("your lineup, decided")
    hole = {"action": "Tyler Bass (K) and the Giants (DEF) aren't playing this week",
            "deadline": "before this week's first kickoff", "urgency": "now",
            "zero": {"slots": ["K", "DEF"], "certain": True}}
    report["checklist"] = [hole] + report["checklist"]
    assert subject_for(report).endswith(": 2 empty spots to fill before kickoff")
    assert preheader_for(report).startswith("Tyler Bass (K) and the Giants (DEF) "
                                            "aren't playing this week.")
    hole["zero"] = {"slots": ["K"], "wait_on": ["x"]}        # may still play
    assert subject_for(report).endswith("your lineup, decided")


def test_the_byes_item_is_one_short_bold_line() -> None:
    """Reproduction (D13): the whole byes sentence — who is on bye, the cover
    options — was the bold action, 7-9 lines tall at 390px."""
    from engine.solo_report import byes_ahead_items
    [item] = byes_ahead_items([{"week": 8, "slots": ["DEF", "QB"], "players": ["A", "B"],
                                "short": ["A", "B"], "out": [], "cover": []}])
    assert item["action"] == "Byes ahead: Week 8 leaves your QB and DEF spots empty"
    assert item["detail"].startswith("Week 8: A and B are on bye.")


def test_the_email_masthead_uses_a_condensed_stack_and_never_wraps_its_title() -> None:
    """Reproduction (D13): "WEEK 7 · YOUR / REPORT" wrapped at 390px in plain
    Arial — phones have no Arial Narrow. Arial Narrow stays FIRST (Outlook
    drops to Times when the first face is missing), then the condensed faces
    Apple and Android ship. No remote font: an email fetches nothing."""
    from render.email import DISPLAY, render_email
    assert DISPLAY.startswith("'Arial Narrow',")
    for face in ("HelveticaNeue-CondensedBold", "Roboto Condensed"):
        assert face in DISPLAY
    page = render_email(_solo())
    assert "Week 5 · Your Report" not in page
    assert ">Week 5</div>" in page and "Your Report</div>" in page


# --------------------------------------------------------------------- #
# F7 — the Saturday line, and a cleared zero is good news worth sending
# --------------------------------------------------------------------- #

def test_every_subscriber_report_says_a_saturday_check_follows() -> None:
    """Reproduction (pre-launch review F7): none of five Week-7 reports, nor
    either sample, said a Saturday check existed. Never "no email means it
    stands": a Saturday run that refuses sends nothing."""
    import render.report as rr
    from render.email import render_email, text_summary
    report = _solo()
    line = "after Friday's final injury report, we email you if it changes your lineup."
    template = rr.TEMPLATE_PATH.read_text(encoding="utf-8")
    for surface in (render_email(report), text_summary(report), rr.render(report, template)):
        assert line in surface.replace("&#x27;", "'")
        assert "no email means" not in surface.lower()
    report["meta"]["trial"] = True
    for surface in (render_email(report), text_summary(report)):
        assert line not in surface.replace("&#x27;", "'")


def test_a_starter_tuesday_called_a_possible_zero_is_mailed_when_cleared() -> None:
    """Reproduction: r2 was told "Lamar Jackson … If he is out again, that's a
    zero unless you add someone off waivers". A Friday clearance sent nothing
    (CLEARED is not a trigger), so the manager burned a claim or worried for
    nothing."""
    from engine.final_check import UNBLOCKED
    from render.final_check import subject_for_check
    plan = {"season": "2026", "week": 7, "slug": "abc",
            "slots": [{"slot": "QB", "player_id": "lamar"}],
            "players": {"lamar": {"name": "Lamar Jackson", "position": "QB",
                                  "projected": 17.8, "last_season": None,
                                  "tuesday": "out"}}}
    changes = final_check(plan, {"lamar": Now(final=True, kickoff=SUN_1PM)})
    assert [c.kind for c in changes] == [UNBLOCKED] and worth_sending(changes)
    assert changes[0].detail.endswith("He's off Friday's final report: no pickup needed.")
    assert subject_for_check(7, changes) == "Week 7: Lamar Jackson is cleared — no pickup needed"
    # Not before his team's final report, and not while still listed.
    assert final_check(plan, {"lamar": Now(final=False)}) == []
    assert not worth_sending(final_check(plan, {"lamar": Now("questionable", "q")}))


# --------------------------------------------------------------------- #
# M5 — the free report names its price and terms near the top
# --------------------------------------------------------------------- #

def test_the_free_report_states_the_price_and_refund_terms_up_top(monkeypatch) -> None:
    """Reproduction (pre-launch review M5): the one ask sat after the whole
    report, with no price. The offer now sits under the free-report header,
    with one payment, nothing renews and the refund window beside the price."""
    from render.email import render_email, text_summary, trial_price_line
    monkeypatch.setenv("SITE_URL", "https://example.com")
    report = _solo()
    report["meta"]["trial"] = True
    line = trial_price_line(report["meta"])
    assert line == ("Every Tuesday through your title game: the $29 Rest-of-Season "
                    "Pass, one payment, nothing renews. Full refund, no questions, "
                    "until your second weekly report's week kicks off. One per person.")
    page = render_email(report).replace("&#x27;", "'")
    assert page.index("one payment, nothing renews") < page.index("Your Game Plan")
    text = text_summary(report)
    assert text.index("$29") < text.index("GAME PLAN")
    assert "https://example.com/join/?via=trial" in text.split("GAME PLAN")[0]
    # The week before the Playoff Pass may be sold: no price the join page may
    # not charge. The season's last week: no offer at all.
    assert "$" not in trial_price_line({"week": 12, "last_week": 18})
    assert trial_price_line({"week": 18, "last_week": 18}) is None


# --------------------------------------------------------------------- #
# P10 — a toss-up's card says either is fine
# --------------------------------------------------------------------- #

def test_a_tossup_closest_call_is_not_titled_start_x_over_y() -> None:
    from render.report import regret_verdict
    tossup = {"start_name": "Ashton Jeanty", "over_name": "Chuba Hubbard",
              "confidence": 0.52, "reason": ""}
    assert regret_verdict(tossup) == ("Ashton Jeanty", "or",
                                      "Chuba Hubbard — either is fine")
    clear = dict(tossup, confidence=0.72)
    assert regret_verdict(clear) == ("Start Ashton Jeanty", "over", "Chuba Hubbard")


# --------------------------------------------------------------------- #
# F8 — the samples' way out is the one-time pass's
# --------------------------------------------------------------------- #

SITE = Path(__file__).resolve().parent.parent / "site"


@pytest.mark.parametrize("page", ["sample-report.html", "sample-first-week.html",
                                  "this-week.html"])
def test_every_sample_carries_the_one_time_way_out(page) -> None:
    """Reproduction (pre-launch review F8): site/this-week.html, written by the
    Oct 20 cron from a checkout that predated one-time passes, told visitors
    "Cancel it yourself from your own billing page" and "Unsubscribing from
    emails alone does not stop a subscription" while 2026 sells one payment
    that renews nothing. Rebuilding is the cron's job (Tue Oct 27), never a
    forced rebuild, so the live page is checked from the week after."""
    from datetime import date
    import render.report as rr
    if not rr.SELLING_ONE_TIME:
        pytest.skip("subscriptions are on sale; the subscription footer is right")
    text = (SITE / page).read_text(encoding="utf-8").replace("&#x27;", "'")
    stale = "billing page" in text or "does not stop a subscription" in text
    if page == "this-week.html" and stale and date.today() < date(2026, 10, 28):
        pytest.skip("this-week.html predates one-time passes; the Oct 27 weekly "
                    "run rebuilds it with the one-time footer")
    assert not stale, f"{page} still describes a subscription"
    assert rr.ONCE_STOP_BODY.split(":")[0] in text
