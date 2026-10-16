"""Who a plan may name, and when — launch-readiness review, Oct 15 2026.

The report tells a subscriber what to do when news lands. Every finding here is
a sentence that could not be carried out, or a fact that was not true:

- R1  a player on a reserve list with no stat row this season, or whose CURRENT
      team is on bye, started unflagged and counted in the total;
- R2  "if he's cleared, start him over X" named a starter whose game kicked off
      before the news, and promised a Saturday check that cannot move him;
- R3  "if X is ruled out, move Y in" named a Thursday-night Y on Sunday news;
- R4  "nobody eligible" while a bench player out only on last week's report sat
      there — no watch line, no if/then;
- R5  a row printed the game of a team the player had left;
- R6  the Thursday line asked the reader to check on players already decided;
- R7  "your if/then already has the answer" about players with no if/then;
- R8  a team defense was "his";
- F11 "odds after 3 games" blamed the wrong player, and "no bench player" sat
      beside a bench row naming one.

Principle 1 throughout: nothing here may ADD or MOVE a published percentage.
These fixes only remove seats, numbers and promises.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from engine.availability import PlayerStatus, Status, WeekAvailability
from engine.projection import Projection, ProjectionModel
from engine.roster import Player, PlayerDirectory
from engine.solo_report import (HELD_GATE, build_solo_report, cleared_plans,
                                early_kickoff_items, in_time, keep_frozen_odds)
from engine.subscriber import RosterSpec, build_season, player_index
from engine.week_report import (ANSWER_EITHER_WAY, TEAM_RANGE_STANDIN_STARTER,
                                SlotPick)
from render.email import render_email, text_summary
from render.report import (TEMPLATE_PATH, gate_list, render, row_label)

THU, SUN, MON = "2026-10-08", "2026-10-11", "2026-10-12"
SLOTS = ("QB", "RB", "WR", "TE", "FLEX")


def _pid(i: int) -> str:
    return f"00-00001{i:02d}"


def _game(opponent: str, day: str, time: str = "13:00", home: bool = False) -> dict:
    return {"opponent": opponent, "home": home, "day": day, "time": time}


# Every team the fixtures use, all on Sunday unless a test says otherwise.
def _schedule(**overrides: dict) -> dict:
    out = {team: _game("OPP", SUN) for team in ("KC", "SF", "BUF", "LV", "SEA",
                                                "DEN", "NYJ", "WAS", "PHI")}
    out.update(overrides)
    return out


def _report(roster: dict[str, tuple[str, str, str]], *, slots=SLOTS,
            yards: dict[str, int] | None = None,
            missed: dict[str, set[int]] | None = None,
            designations: dict[str, str] | None = None,
            listed: dict[str, tuple[str, str]] | None = None,
            reserve: dict[str, str] | None = None,
            unplaced: set[str] = frozenset(),
            byes: frozenset[str] = frozenset(),
            schedule: dict | None = None,
            live_teams: dict[str, str] | None = None,
            reserve_games: bool = False) -> dict:
    """Week 5 of 2026 through the real builders. ``roster`` is pid -> (name,
    position, team); every other knob is a fact about the week.

    ``unplaced`` players get no gate record (no stat row to place them on a
    team: UNKNOWN). ``reserve`` players are on a reserve list or released —
    in the gate's own record when placed, as run/solo does since C7, and
    through ``live_out`` (today's release) when not."""
    yards = yards or {}
    missed = missed or {}
    reserve = reserve or {}
    people = [Player(pid, name, pos, team) for pid, (name, pos, team) in roster.items()]
    directory = PlayerDirectory(people)
    ids = tuple(roster)
    weekly = {w: {pid: {"receiving_yards": yards.get(pid, 50),
                        "team": roster[pid][2]}
                  for pid in ids if w not in missed.get(pid, set())}
              for w in (1, 2, 3, 4)}
    spec = RosterSpec(player_ids=ids, scoring="ppr", label="Your Team", slots=slots)
    season = build_season(spec, weekly, directory, "2026", 5, league_size=12)
    players = player_index(directory)
    model = ProjectionModel(season, players)
    statuses = {pid: {"team": team, "position": pos, "active": pid not in reserve,
                      "out_reason": reserve.get(pid),
                      "injury_status": (designations or {}).get(pid)}
                for pid, (_, pos, team) in roster.items() if pid not in unplaced}
    availability = WeekAvailability("2026", 5, "the week 4 injury report",
                                    statuses, byes)
    # run/solo shows no game for a reserve-list player; ``reserve_games``
    # hands one over anyway, to prove the report does not lean on that.
    teams = {pid: team for pid, (_, _, team) in roster.items()
             if pid not in reserve or reserve_games}
    teams.update({pid: t for pid, t in (live_teams or {}).items()})
    return build_solo_report(
        spec, season, players, model, availability, 5, Path("/nonexistent"),
        schedule=_schedule() if schedule is None else schedule, teams=teams,
        injury_report={"week": 4, "listed": listed or {}},
        live_teams=live_teams,
        live_out={pid: why for pid, why in reserve.items() if pid in unplaced})


def _surfaces(report: dict) -> dict[str, str]:
    import html as _html
    pages = {"browser": render(report, TEMPLATE_PATH.read_text(encoding="utf-8")),
             "email": render_email(report), "text": text_summary(report)}
    # Visible text only: the template's CSS comments are not prose.
    pages = {name: re.sub(r"<style\b.*?</style>|<!--.*?-->", " ", page, flags=re.S | re.I)
             for name, page in pages.items()}
    return {name: _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))
            for name, page in pages.items()}


def _actions(report: dict) -> list[str]:
    return [i["action"] for i in report["checklist"]]


def _item(report: dict, start: str) -> dict:
    return next(i for i in report["checklist"] if i["action"].startswith(start))


def _row(report: dict, name: str) -> dict:
    return next(s for s in report["lineup"] if s["player_name"] == name)


def _published(report: dict) -> set[tuple]:
    return {(s["slot"], s["player_id"], s["alternative_id"], s["confidence"])
            for s in report["lineup"] if s.get("confidence") is not None}


QB1, QB2, RB1, RB2, WR1, WR2, WR3, WR4, TE1, TE2 = (_pid(i) for i in range(1, 11))
BASE = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
        WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
        WR2: ("Wes Slotman", "WR", "KC")}


# --------------------------------------------------------------------- #
# the timing rule itself
# --------------------------------------------------------------------- #

def test_a_player_whose_game_comes_first_is_never_in_time() -> None:
    """The news a plan waits for is in on Sunday morning, or before the
    watched player's own earlier kickoff. A game before that is locked."""
    sunday = date.fromisoformat(SUN)
    thu, sun, mon = _game("A", THU), _game("A", SUN), _game("A", MON)
    assert not in_time(thu, sun, sunday), "a Thursday game locks before Sunday news"
    assert in_time(sun, sun, sunday)
    assert in_time(sun, mon, sunday), "a Monday player's news is in by Sunday morning"
    assert not in_time(thu, mon, sunday)
    assert in_time(thu, thu, sunday), "a Thursday player is checked before Thursday"
    assert in_time(None, sun, sunday), "no game (a bye, a reserve list) never locks"


# --------------------------------------------------------------------- #
# R3 / C1 — "if he's ruled out, move X in" names nobody already locked
# --------------------------------------------------------------------- #

def test_a_thursday_alternative_is_never_the_plan_for_a_sunday_starter() -> None:
    """The reproduction: the published sample said "If Tony Pollard (FLEX) is
    ruled out: Move Chase Brown into FLEX" — Brown's Bengals played Thursday,
    and Pollard's news could not exist before Friday. With nobody else who can
    play there in time, there is no plan, and the game plan says why instead
    of "your if/then below already has the answer"."""
    roster = dict(BASE, **{WR3: ("Will Deepman", "WR", "SEA")})
    report = _report(roster, yards={WR1: 75, WR2: 70, WR3: 40},
                     designations={WR1: "Questionable"},
                     listed={WR1: ("questionable", "foot")},
                     schedule=_schedule(SEA=_game("DEN", THU, "20:15")))
    assert not any("Wade Wideout" in p["condition"] for p in report["pivots"]), \
        report["pivots"]
    sunday = _item(report, "Sunday morning")
    assert "Wade Wideout" in sunday["action"]
    assert ANSWER_EITHER_WAY not in sunday["detail"]
    assert sunday["detail"] == ("If Wade Wideout is out, nobody on your bench can "
                                "step in at WR in time — Will Deepman plays "
                                "before Wade Wideout's status is known.")
    row = _row(report, "Wade Wideout")
    assert row["if_then"] is False and row_label(row) == "questionable"
    for name, page in _surfaces(report).items():
        assert "Move Will Deepman" not in page, name
        assert "questionable · see if/then" not in page, name


def test_the_next_bench_player_who_plays_in_time_takes_the_plan() -> None:
    """Skipping the locked one, the plan names the next player who can play
    there, ranked as the lineup ranks them — and then the line may say the
    if/then has the answer, because it does."""
    roster = dict(BASE, **{WR3: ("Will Deepman", "WR", "SEA"),
                           WR4: ("Walt Later", "WR", "KC")})
    report = _report(roster, yards={WR1: 75, WR2: 70, WR3: 65, WR4: 45},
                     designations={WR1: "Questionable"},
                     listed={WR1: ("questionable", "foot")},
                     schedule=_schedule(SEA=_game("DEN", THU, "20:15")))
    [plan] = [p for p in report["pivots"] if "Wade Wideout" in p["condition"]]
    assert plan["action"].startswith("Move Walt Later into WR (projects ")
    assert _item(report, "Sunday morning")["detail"] == ANSWER_EITHER_WAY
    assert row_label(_row(report, "Wade Wideout")) == "questionable · see if/then"


def test_a_lone_quarterback_gets_an_honest_line_not_a_promise() -> None:
    """Launch audit R7: "check Caleb Williams's status — your if/then below
    already has the answer either way", with no quarterback behind him and no
    if/then for him anywhere."""
    report = _report(BASE, designations={QB1: "Questionable"},
                     listed={QB1: ("questionable", "ankle")})
    sunday = _item(report, "Sunday morning")
    assert sunday["detail"] == "If Quinn Starter is out, nobody on your bench can play QB."
    assert not report["pivots"]


def test_a_bench_player_whose_only_seat_locks_first_is_not_late_news() -> None:
    """The bench half of the same rule: a questionable bench player's news is
    news only if a seat he would win is still open when it lands. If that
    starter plays first, "Sunday morning: check X" is a chore with no move at
    the end of it (launch audit F4's rule, applied to the clock)."""
    from engine.week_report import late_news, pivots

    def proj(pid, mean):
        return Projection(player_id=pid, as_of_week=5, active_mean=mean,
                          active_sd=4.0, appear_probability=1.0, games=5,
                          rostered_weeks=5, position="RB")

    availability = WeekAvailability(
        "2026", 5, "w4", {RB1: {"team": "SEA", "position": "RB", "active": True},
                          RB2: {"team": "KC", "position": "RB", "active": True,
                                "injury_status": "Questionable"}}, frozenset())
    ok = PlayerStatus(Status.ACTIVE, "no injury designation", "w4")
    picks = [SlotPick("RB", 0, RB1, proj(RB1, 10.0), ok, None,
                      "availability in doubt (designated Questionable)",
                      RB2, proj(RB2, 12.0), [])]
    players = player_index(PlayerDirectory([Player(RB1, "Rory Runner", "RB", "SEA"),
                                            Player(RB2, "Remy Reserve", "RB", "KC")]))
    assert [pid for *_, pid in late_news(picks, players, availability)] == [RB2]
    locked = late_news(picks, players, availability,
                       seat_ok=lambda bench_id, pick: False)
    assert locked == []
    assert pivots(picks, [], players, availability, news=locked) == []


# --------------------------------------------------------------------- #
# R7 — every player the game plan names has his if/then printed
# --------------------------------------------------------------------- #

def test_every_questionable_starter_named_has_his_plan_printed() -> None:
    """The reproduction: six players named in the checklist, three plans in
    the if/then — pivots() capped at three and the cleared plans were capped
    again behind them. No cap now; and a row says "see if/then" only when one
    is printed for it."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), QB2: ("Quade Backup", "QB", "KC"),
              RB1: ("Rory Runner", "RB", "KC"), RB2: ("Remy Reserve", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), WR2: ("Wes Slotman", "WR", "KC"),
              WR3: ("Will Deepman", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              TE2: ("Tom Twotight", "TE", "KC")}
    doubt = {pid: "Questionable" for pid in (QB1, RB1, WR1, TE1)}
    report = _report(roster, yards={QB1: 90, QB2: 60, RB1: 80, RB2: 30, WR1: 75,
                                    WR2: 70, WR3: 20, TE1: 60, TE2: 10},
                     designations=doubt,
                     listed={pid: ("questionable", "knee") for pid in doubt})
    names = ("Quinn Starter", "Rory Runner", "Wade Wideout", "Tate Tightend")
    sunday = _item(report, "Sunday morning")
    for name in names:
        assert name in sunday["action"]
        assert any(p["condition"].startswith(name) for p in report["pivots"]), \
            f"{name} is named in the game plan with no if/then"
    assert sunday["detail"] == ANSWER_EITHER_WAY
    for slot in report["lineup"]:
        if "see if/then" in row_label(slot):
            assert any(p["condition"].startswith(slot["player_name"])
                       for p in report["pivots"]), slot["player_name"]


# --------------------------------------------------------------------- #
# R2 — "if he's cleared, start him over X": X must still be benchable
# --------------------------------------------------------------------- #

def _cleared(seats: dict[str, tuple[float, str, str]], bench_day: str = SUN):
    """seats: name -> (projection, slot, game day). One bench RB, out on last
    week's report, projecting 9.6."""
    picks, games = [], {"bench": _game("X", bench_day)}
    players = {"bench": Player("bench", "Breece Bench", "RB", "NYJ")}
    for i, (name, (mean, slot, day)) in enumerate(seats.items()):
        pid = f"s{i}"
        players[pid] = Player(pid, name, "RB", "KC")
        games[pid] = _game("Y", day)
        projection = Projection(player_id=pid, as_of_week=6, active_mean=mean,
                                active_sd=4.0, appear_probability=1.0, games=5,
                                rostered_weeks=5, position="RB")
        picks.append(SlotPick(slot, i, pid, projection,
                              PlayerStatus(Status.ACTIVE, "no injury designation", "w5"),
                              None, None, None, None, []))
    entry = {"out_kind": "designation", "projected": 9.6, "position": "RB",
             "player_id": "bench", "name": "Breece Bench",
             "out_text": "Ruled out for Week 5 (quadricep) — Week 6 status not announced yet"}
    index = player_index(PlayerDirectory(list(players.values())))
    return cleared_plans([entry], picks, index, games.get, date.fromisoformat(SUN))


def test_a_starter_who_plays_before_the_news_is_never_the_one_benched() -> None:
    """The reproduction (2026 week 6): "Watch Breece Hall: if he's cleared,
    start him at RB over RJ Harvey" — Harvey played Thursday night, Hall's news
    came Friday, and the Saturday check it promised returned nothing. It now
    takes the next seat he would win, with the deadline of the earlier game
    and the Saturday sentence only where that check can act."""
    items, plans = _cleared({"RJ Early": (7.8, "RB", THU),
                             "Terry Late": (8.8, "FLEX", MON)})
    assert [i["action"] for i in items] == [
        "Watch Breece Bench: if he's cleared, start him at FLEX over Terry Late"]
    assert items[0]["deadline"] == "before Sunday's kickoff"
    assert plans[0]["action"] == "Start him at FLEX over Terry Late (9.6 vs 8.8)"
    assert plans[0]["saturday"] is True


def test_with_only_a_locked_seat_to_take_there_is_no_watch_line() -> None:
    items, plans = _cleared({"RJ Early": (7.8, "RB", THU)})
    assert items == [] and plans == []


# --------------------------------------------------------------------- #
# R4 — a bench player out only last week can still take a dead seat
# --------------------------------------------------------------------- #

def test_a_bye_week_starter_is_a_seat_his_bench_back_can_take_if_cleared() -> None:
    """The reproduction: Jahmyr Gibbs (DET bye) seated at RB, "we had nobody
    eligible to put in", while Breece Hall — ruled out last week, status not
    out yet — sat on the bench at 9.6 with no watch line and no if/then. The
    seated starter is worth 0; the bench back gets the watch line and the plan,
    and still no percentage."""
    roster = dict(BASE, **{RB1: ("Rory Runner", "RB", "DET"),
                           RB2: ("Remy Reserve", "RB", "NYJ")})
    report = _report(roster, yards={RB1: 90, RB2: 80}, missed={RB2: {4}},
                     designations={RB2: "Out"}, listed={RB2: ("out", "quadricep")},
                     byes=frozenset({"DET"}))
    assert _row(report, "Rory Runner")["projected"] is None
    actions = _actions(report)
    assert not any("nobody eligible" in a for a in actions), actions
    covered = _item(report, "Rory Runner (RB) isn't playing this week")
    assert covered["action"] == (
        "Rory Runner (RB) isn't playing this week, and the only bench player who "
        "could start there, Remy Reserve, was out on last week's injury report. "
        "If he isn't cleared, that's a zero unless you add someone off waivers.")
    watch = _item(report, "Watch Remy Reserve")
    assert watch["action"] == ("Watch Remy Reserve: if he's cleared, start him at "
                               "RB over Rory Runner")
    [plan] = [p for p in report["pivots"] if p["condition"] == "Remy Reserve is cleared"]
    assert plan["action"] == "Start him at RB over Rory Runner, who can't play this week"
    assert report["matchup"]["range_gate"] == TEAM_RANGE_STANDIN_STARTER.format(
        slots="RB", them="him", verb="can't play")
    for text in (covered["action"], watch["action"], watch["detail"], plan["action"]):
        assert "%" not in text


def test_two_out_last_week_say_start_whoever_is_cleared() -> None:
    roster = dict(BASE, **{RB2: ("Remy Reserve", "RB", "KC")})
    report = _report(roster, yards={RB1: 90, RB2: 80}, missed={RB1: {4}, RB2: {4}},
                     designations={RB1: "Out", RB2: "Out"},
                     listed={RB1: ("out", "ankle"), RB2: ("out", "thumb")})
    actions = " ".join(_actions(report))
    assert "nobody else on your roster can start there" not in actions
    assert ("Rory Runner (RB) was out on last week's injury report, and so was the "
            "only bench player who could start there, Remy Reserve. Start whoever "
            "is cleared; if neither is, that's a zero") in actions


# --------------------------------------------------------------------- #
# R1 / R5 — today's team, and nothing it adds
# --------------------------------------------------------------------- #

def test_a_starter_whose_current_team_is_on_bye_loses_his_seat_and_adds_no_odds() -> None:
    """The reproduction: Kaytron Allen (last stat row WAS, now MIA, on bye)
    started with WAS's Monday game on his row and counted in the total. Today's
    team decides; he is benched where someone can play, flagged where nobody
    can — and no percentage appears that the frozen gate did not publish."""
    roster = dict(BASE, **{WR3: ("Will Deepman", "WR", "KC")})
    kwargs = dict(yards={WR1: 75, WR2: 70, WR3: 40})
    before = _report(roster, **kwargs)
    after = _report(roster, live_teams={WR1: "CIN"}, byes=frozenset({"CIN"}), **kwargs)
    assert _published(after) <= _published(before), "a fix that may only remove added odds"
    assert all(s["player_name"] != "Wade Wideout" for s in after["lineup"])
    bench = next(b for b in after["bench"] if b["name"] == "Wade Wideout")
    assert bench["out_text"] == "CIN on bye this week" and bench["projected"] is None


def test_an_unplaced_starter_on_a_bye_team_is_flagged_like_any_other() -> None:
    """Joe Flacco: no stat row this season, so the gate could not place him on
    a team and held him UNKNOWN (here: no record at all); his team CIN on bye —
    seated with no flag and counted in a stated 95.1. Now: the dash, the flag,
    the checklist line, no total and no game."""
    roster = {QB1: ("Joe Backup", "QB", "CIN"), RB1: ("Rory Runner", "RB", "KC")}
    report = _report(roster, slots=("QB", "RB"), unplaced={QB1},
                     live_teams={QB1: "CIN"},
                     byes=frozenset({"CIN"}),
                     schedule=_schedule(CIN=_game("BAL", SUN)))
    row = _row(report, "Joe Backup")
    assert [f["text"] for f in row["flags"]] == ["OUT — CIN on bye this week"]
    assert row["projected"] is None and "game" not in row
    assert "Joe Backup (QB) isn't playing this week" in " ".join(_actions(report))
    assert "projected_total" not in report["matchup"]["you"]


def test_a_released_starter_shows_no_game() -> None:
    """Jake Moody, released: "@ CLE · Sun 1:00 PM ET" on his row named a game
    he is not in."""
    roster = dict(BASE)
    report = _report(roster, reserve={TE1: "released"}, unplaced={TE1})
    row = _row(report, "Tate Tightend")
    assert "game" not in row and row["projected"] is None
    assert [f["text"] for f in row["flags"]] == ["OUT — released"]


def test_a_released_bench_option_comes_off_without_adding_odds() -> None:
    """Measured on 240 live week-6 rosters: making every teamless reserve-list
    player OUT at the gate published NINE new percentages — Kenny McIntosh (on
    injured reserve, no games this season) had been the RB slot's bench option,
    blocking its call as "not enough games", and with him gone the next back
    was called. Owner rule: a fix of this kind may only remove numbers. Here
    the released player was SEATED (at FLEX, unflagged): he comes off, the
    next back takes the slot, and the call that pairing would make is held,
    saying why, rather than published as a call the gate never made."""
    roster = dict(BASE, **{RB2: ("Remy Released", "RB", "KC"),
                           WR3: ("Rob Thirdback", "RB", "KC")})
    kwargs = dict(yards={RB1: 120, RB2: 200, WR3: 10, WR2: 30},
                  missed={RB2: {1, 2, 3}})
    before = _report(roster, unplaced={RB2}, **kwargs)
    assert _row(before, "Remy Released")["slot"] == "FLEX"
    after = _report(roster, unplaced={RB2}, reserve={RB2: "released"}, **kwargs)
    assert _published(after) <= _published(before), "a new percentage was published"
    flex = _row(after, "Rob Thirdback")
    assert flex["slot"] == "FLEX" and flex["confidence"] is None
    assert flex["confidence_gate"] == HELD_GATE and row_label(flex) == "held this week"
    bench = next(b for b in after["bench"] if b["name"] == "Remy Released")
    assert bench["out_text"] == "released" and bench["projected"] is None


def test_a_re_set_slot_keeps_only_the_frozen_gates_odds() -> None:
    def pick(pid, alt, conf, flags=()):
        return SlotPick("WR", 0, pid, None, None, conf, None, alt, None, list(flags))

    kept = keep_frozen_odds([pick("a", "b", 0.7)], [pick("a", "b", 0.7)])
    assert kept[0].confidence == 0.7
    moved = keep_frozen_odds([pick("a", "b", 0.7)],
                             [pick("b", "c", 0.6, [{"kind": "seeded", "text": "x"}])])
    assert moved[0].confidence is None and moved[0].confidence_gate == HELD_GATE
    assert moved[0].flags == []
    assert gate_list({HELD_GATE}) == ("the lineup changed around a player who "
                                      "can't play this week")


# --------------------------------------------------------------------- #
# R6 / R8 — the Thursday line
# --------------------------------------------------------------------- #

def test_the_thursday_line_names_nobody_already_decided() -> None:
    """The reproduction: "Pat Bryant (WR), Zach Charbonnet (FLEX) aren't
    playing this week" and then "Thursday night: Jaxon Smith-Njigba, Pat
    Bryant and Zach Charbonnet kick off — check their status"."""
    roster = dict(BASE, **{WR1: ("Wade Wideout", "WR", "SEA"),
                           WR2: ("Wes Slotman", "WR", "SEA")})
    report = _report(roster, reserve={WR2: "on injured reserve"}, reserve_games=True,
                     schedule=_schedule(SEA=_game("DEN", THU, "20:15")))
    assert "game" not in _row(report, "Wes Slotman")
    thursday = _item(report, "Thursday night")
    assert thursday["action"] == ("Thursday night: Wade Wideout kicks off at "
                                  "8:15 PM ET — check his status before then.")


def test_a_defense_has_no_status_to_check() -> None:
    """R8 made a defense "its", not "his"; launch review RQ-18 went further —
    "Denver Broncos kicks off at 8:15 PM ET — check its status" asked about a
    status a defense does not have. What matters is that the lineup must be
    set before that kickoff."""
    directory = PlayerDirectory([Player("DEF-SEA", "Seattle Seahawks", "DEF", "SEA")])
    items, _ = early_kickoff_items(["DEF-SEA"], player_index(directory),
                                   lambda pid: _game("DEN", THU, "20:15"),
                                   date.fromisoformat(SUN))
    assert items[0]["action"] == ("Thursday night: Seattle Seahawks kicks off at "
                                  "8:15 PM ET — set your lineup before then.")
    assert "status" not in items[0]["action"]


# --------------------------------------------------------------------- #
# F11 — the call column says who
# --------------------------------------------------------------------- #

def test_odds_wait_on_the_player_who_is_short_of_games() -> None:
    """The reproduction: "odds after 3 games" beside Quinshon Judkins, five
    games on record; the short record was Devin Neal's, on the bench."""
    roster = dict(BASE, **{WR3: ("Will Deepman", "WR", "KC")})
    report = _report(roster, yards={WR1: 75, WR2: 70, WR3: 72},
                     missed={WR3: {1, 2, 3}})
    rows = [s for s in report["lineup"] if s["alternative_name"] == "Will Deepman"
            and (s["confidence_gate"] or "").startswith("not enough games")]
    assert rows, [(s["player_name"], s["confidence_gate"]) for s in report["lineup"]]
    assert rows[0]["short_games"] == ["Will Deepman"]
    assert row_label(rows[0]) == "odds once Will Deepman has 3 games"


def test_a_bench_player_who_is_out_is_named_not_denied() -> None:
    """The reproduction: the live sample's QB row blamed "no bench player at
    that position" with Lamar Jackson on the bench, ruled out last week."""
    roster = dict(BASE, **{QB2: ("Quade Backup", "QB", "KC")})
    report = _report(roster, yards={QB2: 120}, missed={QB2: {4}},
                     designations={QB2: "Out"}, listed={QB2: ("out", "ankle")})
    row = _row(report, "Quinn Starter")
    assert row["confidence_gate"].startswith("bench option not cleared")
    assert row_label(row) == "Quade Backup not cleared yet"
    assert "Quade Backup" not in gate_list({row["confidence_gate"]}), \
        "the note names nobody; the row does"
    assert gate_list({row["confidence_gate"]}) == \
        "your bench player at that position isn't cleared to play"
    for name, page in _surfaces(report).items():
        assert "isn't cleared to play" in page, name


def test_the_weekly_report_never_calls_itself_a_file() -> None:
    """The report-not-file gate (run/launch_check.py) reads site pages only;
    the emails are where a subscriber reads the word (launch audit C7). Every
    surface of a weekly report with plans, watch lines and the Thursday line."""
    roster = dict(BASE, **{RB1: ("Rory Runner", "RB", "DET"),
                           RB2: ("Remy Reserve", "RB", "NYJ"),
                           WR1: ("Wade Wideout", "WR", "SEA")})
    report = _report(roster, yards={RB1: 90, RB2: 80}, missed={RB2: {4}},
                     designations={RB2: "Out", WR2: "Questionable"},
                     listed={RB2: ("out", "quadricep"), WR2: ("questionable", "toe")},
                     byes=frozenset({"DET"}),
                     schedule=_schedule(SEA=_game("DEN", THU, "20:15")))
    pattern = re.compile(
        r"\b(?:this|your|the|weekly|first|roster|a) files?\b(?! (?:a|an) )", re.I)
    for name, page in _surfaces(report).items():
        hits = [m.group(0) for m in pattern.finditer(page)
                if "on file" not in page[max(0, m.start() - 5):m.end() + 8]]
        assert not hits, f"{name} calls the product a file: {hits}"
