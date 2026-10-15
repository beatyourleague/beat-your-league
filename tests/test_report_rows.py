"""What each lineup row says about the week — launch audit, Oct 2026.

Seven findings, all in the body of the report a subscriber reads on a phone:

- F7  no row named the opponent or the kickoff, and nothing warned that a
      starter played Thursday night — the one game Saturday's check is too
      late for;
- F2  a player out on LAST week's report read "can't play this week", number
      hidden, no if/then — though about one in four such players play;
- F4  the plan asked for a Sunday-morning status check on a bench player whose
      clearance changed nothing;
- F5  "designated Questionable" was last week's report in the present tense;
- F6  the email's call column was nowrap and pushed a 390px phone sideways;
- PC-14 a starter on bye printed a projection, and the bye read as nested
      parentheses;
- W7  Rising Roles borrowed a list class scoped to another card.

Facts only: nothing here may move a projection, a confidence or the gate.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from engine.availability import PlayerStatus, Status, WeekAvailability
from engine.projection import Projection, ProjectionModel
from engine.roster import Player, PlayerDirectory
from engine.solo_report import (absence, build_solo_report, cleared_plans,
                                early_kickoff_items, game_label, questionable_note)
from engine.subscriber import RosterSpec, build_season, player_index
from engine.week_report import SlotPick, checklist, late_news, pivots
from render.email import render_email, short_usage, text_summary
from render.report import (SATURDAY_FOLLOWUP, TEMPLATE_PATH, bench_phrase,
                           render)

REPO = Path(__file__).resolve().parent.parent
THURSDAY, SUNDAY = "2026-10-08", "2026-10-11"


# --------------------------------------------------------------------- #
# a small solo week, built through the real builders
# --------------------------------------------------------------------- #

def _pid(i: int) -> str:
    return f"00-00000{i:02d}"


QB1, QB2, RB1, WR1, TE1, WR2, WR3 = (_pid(i) for i in range(1, 8))
NAMES = {QB1: "Quinn Starter", QB2: "Quade Backup", RB1: "Rory Runner",
         WR1: "Wade Wideout", TE1: "Tate Tightend", WR2: "Wes Slotman",
         WR3: "Will Deepman"}
POSITIONS = {QB1: "QB", QB2: "QB", RB1: "RB", WR1: "WR", TE1: "TE",
             WR2: "WR", WR3: "WR"}
SLOTS = ("QB", "RB", "WR", "TE", "FLEX")


def _week(*, yards: dict[str, int] | None = None,
          missed: dict[str, set[int]] | None = None,
          designations: dict[str, str] | None = None,
          listed: dict[str, tuple[str, str]] | None = None,
          teams: dict[str, str] | None = None,
          byes: frozenset[str] = frozenset(),
          schedule: dict | None = None,
          ranks: dict | None = None) -> dict:
    """Week 5 of 2026 for a seven-man roster; every knob is a fact."""
    base = {QB1: 90, QB2: 60, RB1: 80, WR1: 75, TE1: 50, WR2: 70, WR3: 40}
    base.update(yards or {})
    missed = missed or {}
    teams = {pid: "KC" for pid in NAMES} | (teams or {})
    people = [Player(pid, NAMES[pid], POSITIONS[pid], teams[pid]) for pid in NAMES]
    directory = PlayerDirectory(people)
    ids = tuple(NAMES)
    weekly = {w: {pid: {"receiving_yards": base[pid], "team": teams[pid]}
                  for pid in ids if w not in missed.get(pid, set())}
              for w in (1, 2, 3, 4)}
    spec = RosterSpec(player_ids=ids, scoring="ppr", label="Your Team", slots=SLOTS)
    season = build_season(spec, weekly, directory, "2026", 5, league_size=12)
    players = player_index(directory)
    model = ProjectionModel(season, players)
    statuses = {pid: {"team": teams[pid], "position": POSITIONS[pid], "active": True,
                      "injury_status": (designations or {}).get(pid)}
                for pid in ids}
    availability = WeekAvailability(season="2026", week=5,
                                    snapshot_as_of="the week 4 injury report",
                                    statuses=statuses, bye_teams=byes)
    if schedule is None:
        schedule = {"KC": {"opponent": "DEN", "home": False, "day": SUNDAY,
                           "time": "13:00"},
                    "DEN": {"opponent": "KC", "home": True, "day": SUNDAY,
                            "time": "13:00"}}
    return build_solo_report(
        spec, season, players, model, availability, 5, Path("/nonexistent"),
        last_season_ranks=ranks, schedule=schedule,
        teams={pid: teams[pid] for pid in ids},
        injury_report={"week": 4, "listed": listed or {}})


def _row(report: dict, name: str) -> dict:
    return next(s for s in report["lineup"] if s["player_name"] == name)


def _bench(report: dict, name: str) -> dict:
    return next(b for b in report["bench"] if b["name"] == name)


def _surfaces(report: dict) -> dict[str, str]:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return {"browser": render(report, template), "email": render_email(report),
            "text": text_summary(report)}


def _flat(html: str) -> str:
    import html as _html
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))


# --------------------------------------------------------------------- #
# F7 — the opponent and the kickoff, and the Thursday warning
# --------------------------------------------------------------------- #

def test_the_kickoff_reads_as_a_reader_says_it() -> None:
    """The schedule writes "2026-10-08" and "20:15" in NFL time."""
    game = {"opponent": "DEN", "home": False, "day": THURSDAY, "time": "20:15"}
    assert game_label(game) == "@ DEN · Thu 8:15 PM ET"
    assert game_label(dict(game, home=True, time="09:30")) == "vs DEN · Thu 9:30 AM ET"
    assert game_label(dict(game, time="12:00")) == "@ DEN · Thu 12:00 PM ET"
    # A missing time says the day, never a made-up clock; no game says nothing.
    assert game_label(dict(game, time="")) == "@ DEN · Thu"
    assert game_label(None) is None


def test_every_lineup_row_names_its_opponent_and_kickoff_on_every_surface() -> None:
    """The reproduction: the 2024 week-10 sample started Ja'Marr Chase, whose
    Bengals played at Baltimore on THURSDAY night, and no surface said so."""
    report = _week()
    row = _row(report, "Quinn Starter")
    assert row["game"] == "@ DEN · Sun 1:00 PM ET"
    for name, page in _surfaces(report).items():
        assert "@ DEN · Sun 1:00 PM ET" in _flat(page), f"{name} dropped the kickoff"


def test_a_thursday_starter_gets_a_game_plan_line_before_the_weekend() -> None:
    """Saturday's final check runs after a Thursday game has locked, and the
    late-news line said "Sunday morning" — three days late. The plan says so
    on Tuesday, and a questionable starter who plays Thursday is not also
    sent to check on Sunday morning."""
    schedule = {"KC": {"opponent": "DEN", "home": False, "day": THURSDAY,
                       "time": "20:15"},
                "DEN": {"opponent": "KC", "home": True, "day": THURSDAY,
                        "time": "20:15"},
                "SF": {"opponent": "LA", "home": True, "day": SUNDAY, "time": "13:00"}}
    report = _week(schedule=schedule, teams={RB1: "SF", TE1: "SF", WR2: "SF",
                                             WR3: "SF"},
                   designations={QB1: "Questionable"},
                   listed={QB1: ("questionable", "ankle")})
    actions = [i["action"] for i in report["checklist"]]
    thursday = [a for a in actions if a.startswith("Thursday night:")]
    assert len(thursday) == 1, actions
    assert "Quinn Starter" in thursday[0] and "Wade Wideout" in thursday[0]
    assert "kick off at 8:15 PM ET" in thursday[0]
    # Not the audit's "lock": betting slang for a sure thing (run/drops.py
    # bans "lock " from public copy), and this line ships on public samples.
    assert not re.search(r"\blocks?\b", thursday[0], re.I)
    assert not any(a.startswith("Sunday morning") and "Quinn Starter" in a
                   for a in actions), "a Thursday player was sent to check on Sunday"
    item = next(i for i in report["checklist"] if i["action"] == thursday[0])
    assert item["deadline"] == "before Thursday's kickoff"


def test_a_sunday_slate_carries_no_early_warning() -> None:
    assert not any(i["action"].startswith(("Thursday", "Friday", "Saturday"))
                   for i in _week()["checklist"])
    # And a week whose schedule names no Sunday at all calls nothing early,
    # rather than calling everything early.
    items, ids = early_kickoff_items([QB1], _players(), lambda pid: {
        "opponent": "DEN", "home": False, "day": THURSDAY, "time": "20:15"}, None)
    assert items == [] and ids == set()


def _players():
    return player_index(PlayerDirectory(
        [Player(pid, NAMES[pid], POSITIONS[pid], "KC") for pid in NAMES]))


def test_a_replayed_week_with_nobody_placed_shows_no_games(tmp_path) -> None:
    """Today's directory describes today. A replayed week whose gate placed
    nobody (week 1: no injury report yet) must not borrow today's teams — a
    2024 row showing a 2026 team's opponent would be invented — and must not
    show a lone defense's game either."""
    import run.solo as solo
    from engine.availability import WeekAvailability as WA

    directory = PlayerDirectory([Player(QB1, "Quinn Starter", "QB", "KC"),
                                 Player("DEF-KC", "Kansas City Chiefs", "DEF", "KC")])
    spec = RosterSpec(player_ids=(QB1, "DEF-KC"), slots=("QB", "DEF"), scoring="ppr")

    class Data:
        availability = WA("2024", 1, None, None, frozenset())
        is_live_week = False

    Data.directory = directory
    assert solo._row_teams(spec, Data) == {}
    Data.is_live_week = True
    assert solo._row_teams(spec, Data) == {QB1: "KC", "DEF-KC": "KC"}


def test_the_week_and_the_report_are_read_off_the_schedule_release(tmp_path) -> None:
    """run/solo reads the week's games and last week's report in its own words
    — "doubtful" is not "out", whatever the gate folds it into."""
    import csv
    import run.solo as solo

    cache = tmp_path / "nflverse"
    cache.mkdir()
    with (cache / "games.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["season", "game_type", "week", "gameday", "gametime",
                         "away_team", "home_team", "spread_line"])
        writer.writerow(["2026", "REG", "6", THURSDAY, "20:15", "SEA", "DEN", "-3.5"])
        writer.writerow(["2026", "REG", "7", SUNDAY, "13:00", "SEA", "KC", "1"])
    games = solo._week_games(cache, "2026", 6, live=False)
    assert games == {"DEN": {"opponent": "SEA", "home": True, "day": THURSDAY,
                             "time": "20:15"},
                     "SEA": {"opponent": "DEN", "home": False, "day": THURSDAY,
                             "time": "20:15"}}
    assert not any("spread" in str(g) or "-3.5" in str(g) for g in games.values()), \
        "a market line reached the row (principle 4)"

    with (cache / "injuries_2026.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["season", "game_type", "week", "gsis_id", "report_status",
                         "report_primary_injury"])
        writer.writerow(["2026", "REG", "5", QB1, "Doubtful", "Knee"])
        writer.writerow(["2026", "REG", "5", QB2, "Out", "Not injury related - personal"])
        writer.writerow(["2026", "REG", "5", RB1, "", "Ankle"])
        writer.writerow(["2026", "REG", "4", WR1, "Out", "Foot"])
    listed = solo._listed_on_report(cache, "2026", 5, live=False)
    assert listed == {QB1: ("doubtful", "knee"), QB2: ("out", "personal")}


# --------------------------------------------------------------------- #
# F2 — out on LAST week's report is not "can't play this week"
# --------------------------------------------------------------------- #

def test_last_weeks_out_is_dated_and_keeps_his_number() -> None:
    """The reproduction: Lamar Jackson, Out (ankle) on the 2026 week-5 report,
    read "can't play this week" in the week-6 report with his projection hidden
    — about one such player in four plays the next week."""
    report = _week(yards={QB2: 160}, missed={QB2: {4}}, designations={QB2: "Out"},
                   listed={QB2: ("out", "hamstring")})
    entry = _bench(report, "Quade Backup")
    assert entry["out_kind"] == "designation"
    assert bench_phrase(entry) == ("Ruled out for Week 4 (hamstring) — Week 5 "
                                   "status not announced yet")
    assert entry["projected"] is not None, "his projection was hidden again"
    for name, page in _surfaces(report).items():
        flat = _flat(page)
        assert "Ruled out for Week 4 (hamstring)" in flat, name
        assert "Quade Backup — he can't play" not in flat, name


def test_a_doubtful_player_is_never_called_ruled_out() -> None:
    report = _week(missed={QB2: {4}}, designations={QB2: "Out"},
                   listed={QB2: ("doubtful", "knee")})
    assert bench_phrase(_bench(report, "Quade Backup")).startswith(
        "Doubtful for Week 4 (knee)")


def test_if_he_is_cleared_and_would_start_the_plan_says_so() -> None:
    """From Tuesday's OWN projections — the bench row's number against the
    starter's — and never with a percentage: no new number is published."""
    report = _week(yards={QB2: 160}, missed={QB2: {4}}, designations={QB2: "Out"},
                   listed={QB2: ("out", "hamstring")})
    backup, starter = _bench(report, "Quade Backup"), _row(report, "Quinn Starter")
    assert backup["projected"] > starter["projected"]
    watch = [i for i in report["checklist"] if i["action"].startswith("Watch Quade Backup")]
    assert len(watch) == 1, [i["action"] for i in report["checklist"]]
    assert watch[0]["action"] == ("Watch Quade Backup: if he's cleared, start him "
                                  "at QB over Quinn Starter")
    plan = next(p for p in report["pivots"] if p["condition"] == "Quade Backup is cleared")
    assert plan["action"] == (f"Start him at QB over Quinn Starter "
                              f"({backup['projected']:.1f} vs {starter['projected']:.1f})")
    assert plan["saturday"] is True, "a Sunday game is one Saturday's check reads"
    for text in (watch[0]["action"], watch[0]["detail"], plan["action"]):
        assert "%" not in text, f"a probability on a player nobody graded: {text}"
    # Saturday's check is named on every subscriber surface, never on a free
    # report — there is no Saturday check behind one.
    for name, page in _surfaces(report).items():
        assert SATURDAY_FOLLOWUP in _flat(page), name
    report["meta"]["trial"] = True
    for name, page in _surfaces(report).items():
        assert SATURDAY_FOLLOWUP not in _flat(page), name


def test_no_saturday_promise_for_a_game_that_check_cannot_reach() -> None:
    """Thursday locks before Saturday; a Monday game's final report is not in
    when the check runs. The sentence rides only on a Sunday game."""
    entry = {"out_kind": "designation", "projected": 30.0, "position": "QB",
             "player_id": QB2, "name": "Quade Backup", "out_text": "Ruled out"}
    pick = SlotPick("QB", 0, QB1, _proj(QB1, 10.0), None, None, None, None, None, [])
    thursday = {"opponent": "DEN", "home": False, "day": THURSDAY, "time": "20:15"}
    _, plans = cleared_plans([entry], [pick], _players(), lambda pid: thursday,
                             date.fromisoformat(SUNDAY))
    assert plans and plans[0]["saturday"] is False


def test_if_he_would_sit_anyway_nothing_asks_the_reader_to_watch_him() -> None:
    """F4's rule, applied to F2: a line about news that changes nothing is a
    chore. The bench row still says what is true of him."""
    report = _week(yards={QB2: 30}, missed={QB2: {4}}, designations={QB2: "Out"},
                   listed={QB2: ("out", "hamstring")})
    assert not any("Quade Backup" in i["action"] for i in report["checklist"])
    assert not any("Quade Backup" in p["condition"] for p in report["pivots"])
    assert "Ruled out for Week 4" in bench_phrase(_bench(report, "Quade Backup"))


def test_a_bye_and_a_reserve_list_stay_certain() -> None:
    availability = WeekAvailability(
        "2026", 5, "w4", {QB1: {"team": "DEN", "position": "QB", "active": True},
                          QB2: {"team": "KC", "position": "QB", "active": False,
                                "out_reason": "on injured reserve"}},
        frozenset({"DEN"}))
    assert absence(QB1, availability)["kind"] == "bye"
    assert absence(QB1, availability)["sentence"] == "DEN is on bye this week."
    assert absence(QB2, availability)["row"] == "on injured reserve"
    assert absence(RB1, availability) is None      # unknown is not out


# --------------------------------------------------------------------- #
# F4 — a bench player's news is news only when it moves a seat
# --------------------------------------------------------------------- #

def _proj(pid: str, mean: float) -> Projection:
    return Projection(player_id=pid, as_of_week=5, active_mean=mean, active_sd=4.0,
                      appear_probability=1.0, games=5, rostered_weeks=5, position="RB")


def _doubt(alt_mean: float):
    availability = WeekAvailability(
        "2026", 5, "w4", {RB1: {"team": "KC", "position": "RB", "active": True},
                          QB2: {"team": "KC", "position": "RB", "active": True,
                                "injury_status": "Questionable"}},
        frozenset())
    ok = PlayerStatus(Status.ACTIVE, "no injury designation", "w4")
    pick = SlotPick("RB", 0, RB1, _proj(RB1, 10.0), ok, None,
                    "availability in doubt (designated Questionable)",
                    QB2, _proj(QB2, alt_mean), [])
    return [pick], availability


def test_a_bench_check_that_changes_nothing_is_not_asked_for() -> None:
    """The reproduction: the plan said "Sunday morning: check Tony Pollard's
    status" while its own if/then read "Keep Chase Brown at FLEX — they
    project dead even … If he's out, nothing changes"."""
    players = _players()
    for alt_mean in (8.0, 10.0, 10.04):           # lower, dead even, even at print
        picks, availability = _doubt(alt_mean)
        assert late_news(picks, players, availability) == [], alt_mean
        assert pivots(picks, [], players, availability) == []
        assert not any("Sunday morning" in i["action"] for i in
                       checklist(picks, None, [], players, availability=availability))


def test_a_bench_check_that_moves_a_seat_is_still_asked_for() -> None:
    players = _players()
    picks, availability = _doubt(12.0)
    assert [pid for *_, pid in late_news(picks, players, availability)] == [QB2]
    [plan] = pivots(picks, [], players, availability)
    assert plan["action"].startswith("Start Quade Backup at RB — he projects 12.0")
    assert any(i["action"] == "Sunday morning: check Quade Backup's status"
               for i in checklist(picks, None, [], players, availability=availability))


# --------------------------------------------------------------------- #
# F5 — last week's questionable, dated, with what happened
# --------------------------------------------------------------------- #

def test_a_questionable_designation_is_dated_and_says_what_happened() -> None:
    """The reproduction: Zay Flowers read "designated Questionable" in the
    2026 week-6 report; he was Questionable (foot) in week 5 and played."""
    report = _week(designations={WR1: "Questionable"},
                   listed={WR1: ("questionable", "foot")})
    row = _row(report, "Wade Wideout")
    texts = [f["text"] for f in row["flags"]]
    assert texts == ["Questionable in Week 4 (foot) — played, 7.5"], texts
    for name, page in _surfaces(report).items():
        assert "designated Questionable" not in page, name
        assert "Questionable in Week 4 (foot) — played, 7.5" in _flat(page), name


def test_a_questionable_player_who_sat_says_so() -> None:
    report = _week(missed={WR1: {4}}, designations={WR1: "Questionable"},
                   listed={WR1: ("questionable", "foot")})
    assert [f["text"] for f in _row(report, "Wade Wideout")["flags"]] == \
        ["Questionable in Week 4 (foot) — didn't play"]


# --------------------------------------------------------------------- #
# PC-14 — a starter who certainly cannot play
# --------------------------------------------------------------------- #

def test_a_starter_on_bye_prints_a_dash_and_one_plain_sentence() -> None:
    """The reproduction: "OUT — CIN on bye (NFL schedule)" beside a
    projection, and a game-plan line reading "WR3 last season. (CIN on bye
    (NFL schedule))." Now: a dash, and "CIN is on bye this week." """
    report = _week(teams={TE1: "CIN", WR3: "CIN"}, byes=frozenset({"CIN"}),
                   ranks={WR3: ("WR", 3, 99)}, yards={WR3: 60})
    tight = _row(report, "Tate Tightend")
    assert tight["projected"] is None and tight["edge"] is None
    assert [f["text"] for f in tight["flags"]] == ["OUT — CIN on bye this week"]
    assert [f["kind"] for f in tight["flags"]] == ["out"], \
        "launch_check finds a starter who can't play by the out flag"
    item = next(i for i in report["checklist"] if "Will Deepman" in i["action"])
    assert item["detail"] == "WR3 last season. CIN is on bye this week."
    assert "(" not in item["detail"]


def test_a_seated_starter_out_last_week_is_in_doubt_not_gone() -> None:
    """Seated only because nobody else on the roster can play TE. "Isn't
    playing this week" was a confident claim about a report not yet out; the
    total is still withheld, for a reason that is now true, and the row keeps
    the number the if-cleared decision turns on. launch_check still finds him
    by his out flag and his name in the plan."""
    from engine.week_report import TEAM_RANGE_DOUBTFUL_STARTER
    report = _week(missed={TE1: {4}}, designations={TE1: "Out"},
                   listed={TE1: ("out", "calf")})
    tight = _row(report, "Tate Tightend")
    assert tight["projected"] is not None
    assert [f["kind"] for f in tight["flags"]] == ["out"]
    assert tight["flags"][0]["text"].startswith("Ruled out for Week 4 (calf)")
    actions = " ".join(i["action"] for i in report["checklist"])
    assert "Tate Tightend (TE) was out on last week's injury report" in actions
    assert "isn't playing this week" not in actions
    assert report["matchup"]["range_gate"] == \
        TEAM_RANGE_DOUBTFUL_STARTER.format(slots="TE", them="him")


# --------------------------------------------------------------------- #
# F6 — the email at a phone's width
# --------------------------------------------------------------------- #

def test_usage_is_shortened_without_dropping_a_fact() -> None:
    """Reproduction (panel review I11): the email row read "last 4: 2.5
    tgt/g, 21.0 car/g" — our shorthand, not the reader's. Spelled out now,
    and a clause under one every other game goes from the short line only
    when another clause stays ("1 carry" over four games was "0.2 car/g" on a
    receiver's row)."""
    from engine.usage import Usage, usage_line
    line = usage_line(Usage(weeks=4, targets=34, air_yards=None, rz_targets=None,
                            snaps=None, carries=21))
    assert line == "last 4 games: 34 targets (8.5 a game), 21 carries"
    assert short_usage(line) == "last 4: 8.5 targets · 5.2 carries a game"
    one = usage_line(Usage(1, 1, None, None, None, 1))
    assert short_usage(one) == "last 1: 1.0 targets · 1.0 carries a game"
    receiver = usage_line(Usage(4, 34, None, None, None, 1))
    assert short_usage(receiver) == "last 4: 8.5 targets a game"
    # A line never empties: the larger of two tiny clauses stays.
    trickle = usage_line(Usage(4, 1, None, None, None, 1))
    assert short_usage(trickle).startswith("last 4: 0.2") and "a game" in short_usage(trickle)
    for row in (line, one, receiver):
        assert "tgt/g" not in short_usage(row) and "car/g" not in short_usage(row)
    # Anything it does not recognise passes through whole, never trimmed.
    assert short_usage("last 3 games: 4 inside the 20") == "last 3 games: 4 inside the 20"
    assert short_usage("last season: 14.5 a game over 17 games") == \
        "last season: 14.5 a game over 17 games"


def _lineup_table(email: str) -> str:
    """The lineup's player rows, header excluded."""
    start = email.index(">Call</td></tr>")
    return email[start:email.index("</table>", start)]


def test_no_sentence_sits_in_a_column_that_cannot_wrap() -> None:
    """The reproduction: "start · waiting on Rashid Shaheed" in a nowrap call
    cell pushed the 2026 week-6 email to 413px on a 390px phone and squeezed
    the player column so rows ran four to eight lines."""
    report = _week(designations={WR1: "Questionable"},
                   listed={WR1: ("questionable", "foot")})
    table = _lineup_table(render_email(report))
    for cell in re.findall(r'<td[^>]*white-space:nowrap[^>]*>(.*?)</td>', table, re.S):
        visible = _flat(cell).strip()
        assert len(visible) <= 6, f"a nowrap cell carries text: {visible!r}"
    for cell in re.findall(r'<td width="60"[^>]*>(.*?)</td>', table, re.S):
        assert re.fullmatch(r"(\d+%)?", _flat(cell).strip()), \
            f"the call column carries a sentence: {_flat(cell).strip()!r}"


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def test_the_email_fits_a_390px_phone_in_a_real_browser(tmp_path) -> None:
    """Measured, not inferred: the published sample week (Tony Pollard is a
    questionable starter in it) rendered as the email and loaded in headless
    Chrome at a true 390px width. Before the fix: scrollWidth 413."""
    import os
    import render.sample as sample
    chrome = os.environ.get("CHROME_PATH") or (CHROME if Path(CHROME).exists()
                                               else shutil.which("google-chrome"))
    node = shutil.which("node")
    if not chrome or not node:
        pytest.skip("needs Chrome and node")
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    assert any(f["kind"] == "questionable" for s in report["lineup"]
               for f in s["flags"]), "the sample lost its questionable starter"
    report["meta"].pop("historical_demo", None)
    (tmp_path / "mail.html").write_text(render_email(report), encoding="utf-8")
    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps([{"path": "mail.html", "widths": [390], "settle": 300}]))
    run = subprocess.run([node, str(REPO / "run" / "launch_browser.mjs"),
                          tmp_path.as_uri(), chrome, str(pages)],
                         capture_output=True, text=True, timeout=180)
    [result] = json.loads(run.stdout or "[]")
    if "fatal" in result:
        pytest.skip(f"Chrome could not run here: {result['fatal']}")
    assert result["innerWidth"] == 390
    assert result["scrollWidth"] <= 390, \
        f"the email is {result['scrollWidth']}px wide on a 390px phone"


# --------------------------------------------------------------------- #
# W7 — Rising Roles has its own styling
# --------------------------------------------------------------------- #

def test_rising_roles_is_styled_where_it_renders() -> None:
    """It borrowed ``ul.receipts``, whose rules are scoped to the navy ledger
    card, so on the published samples the bullets hung outside the section and
    the intro rendered as bare text."""
    report = _week()
    report["rising"] = [{"name": "Braelon Allen", "line": "Braelon Allen (NYJ, RB): "
                         "22.0 touches a game over his last two, up from 8.0 before."}]
    pages = _surfaces(report)
    assert '<ul class="rising">' in pages["browser"]
    assert '<p class="risingintro">' in pages["browser"]
    assert 'class="receipts"' not in pages["browser"].split("Rising Roles")[1].split("</section>")[0]
    assert "<b>Braelon Allen (NYJ, RB)</b>" in pages["browser"]
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    for rule in (".risingintro{", ".rising{", ".rising li{"):
        assert rule in template, f"no CSS for {rule}"
    assert "<b>Braelon Allen (NYJ, RB)</b>" in pages["email"]


# --------------------------------------------------------------------- #
# the published sample, through the real pipeline
# --------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def sample10():
    import render.sample as sample
    try:
        return sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")


def test_the_sample_warns_about_its_thursday_starter(sample10) -> None:
    """2024 week 10: Cincinnati at Baltimore, Thursday 8:15 PM ET."""
    chase = _row(sample10, "Ja'Marr Chase")
    assert chase["game"] == "@ BAL · Thu 8:15 PM ET"
    assert any(i["action"] == "Thursday night: Ja'Marr Chase kicks off at 8:15 PM ET "
                              "— check his status before then."
               for i in sample10["checklist"])


def test_the_email_says_usage_at_a_phones_width_and_the_page_keeps_the_count(
        sample10) -> None:
    """The email row takes the short form (F6); the browser report keeps the
    full count, which the landing's Real-output card quotes verbatim
    ("34 targets (8.5 a game)") and test_site pins to the published sample."""
    chase = _row(sample10, "Ja'Marr Chase")
    assert chase["usage"].startswith("last 4 games: 34 targets (8.5 a game)")
    email = _flat(render_email(sample10))
    assert short_usage(chase["usage"]) in email
    assert chase["usage"] not in email
    browser = _flat(render(sample10, TEMPLATE_PATH.read_text(encoding="utf-8")))
    assert "34 targets (8.5 a game)" in browser


def test_the_samples_if_then_names_nobody_who_played_thursday(sample10) -> None:
    """Launch audit R3/C1: the published sample said "If Tony Pollard (FLEX)
    is ruled out: Move Chase Brown into FLEX" — Brown's Bengals were at
    Baltimore on THURSDAY, before Pollard's Sunday news existed, and the same
    page said "Thursday night: Ja'Marr Chase kicks off". The plan now moves
    the next FLEX option who plays after the news: Sam LaPorta (DET, Sunday)."""
    [plan] = [p for p in sample10["pivots"] if "Tony Pollard" in p["condition"]]
    assert plan["action"] == "Move Sam LaPorta into FLEX (projects 9.5)"
    assert not any("Chase Brown" in p["action"] for p in sample10["pivots"])
    sunday = next(i for i in sample10["checklist"]
                  if i["action"].startswith("Sunday morning"))
    assert sunday["detail"] == "Your if/then below already has the answer either way."


def test_the_sample_dates_pollards_questionable(sample10) -> None:
    pollard = _row(sample10, "Tony Pollard")
    assert [f["text"] for f in pollard["flags"]] == \
        ["Questionable in Week 9 (foot) — played, 18.4"]
