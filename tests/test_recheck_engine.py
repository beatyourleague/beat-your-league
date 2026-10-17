"""The report's plans, rows and numbers — the recheck of Oct 16-17 2026.

Every item here was confirmed by a second agent reproducing it on real 2026
week-6 rosters: a plan crediting the wrong player with the kickoff that binds
it, a Saturday check calling a healthy, playing cover "out or on bye", the
practice squad reaching Saturday with no caveat, Tuesday and Saturday naming
different covers for the same Friday news, a published probability that moved
with who else sat on the bench, one call printed as two percentages, odds
explained on a row that printed none, a week-1 lineup that started a defense
alphabetically, a superflex line telling a manager with a bench quarterback to
go and find one, a team name that changed every week, and a Monday-night
player told to check his status on Sunday morning. Each test states its
reproduction.

Principle 1 throughout: nothing here may add or move a published percentage,
change a projection the frozen harness grades, the recalibration or the
publish gate. The fixes choose who a plan names, say what is true, round once,
and withhold.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import engine.week_report as wr
import render.report as rr
from engine.availability import Status, WeekAvailability
from engine.final_check import (NO_FILL, SWAP, WATCH, Now, clauses, final_check,
                                first_to_kick_off, rank_covers)
from engine.history import PlayerIndex
from engine.projection import (ProjectionModel, printed_percent,
                               stored_confidence)
from engine.roster import Player, PlayerDirectory
from engine.solo_report import (SHAPE_INPUT_GATE, _form_facts, _named_reason,
                                superflex_items, team_lead)
from engine.subscriber import RosterSpec, build_season, player_index
from engine.week_report import DEFENSE_GATE, SlotPick, optimal_lineup
from test_report_decisions import (MON, SUN, THU, _bench, _game, _pid, _plans,
                                   _report, _row, _schedule, _surfaces)

QB1, QB2, RB1, RB2, RB3, WR1, WR2, WR3, TE1, WR4 = (_pid(i) for i in range(41, 51))
UTC = timezone.utc


def _detail(changes, kind, starter: str) -> str:
    return next(c.detail for c in changes if c.kind == kind and starter in c.action)


# --------------------------------------------------------------------- #
# ENG-1 / RQ2-01 — the player who kicks off first is the one named
# --------------------------------------------------------------------- #

def _slide_roster(**extra) -> dict:
    """A 4:25 PM questionable back, the FLEX back playing in London at 9:30
    AM, and only a 1:00 PM receiver on the bench to take the FLEX."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Ash Late", "RB", "LV"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              RB2: ("Monty London", "RB", "HOU"), WR2: ("Wick Sunday", "WR", "PHI")}
    roster.update(extra)
    return roster


def _slide_schedule(**more) -> dict:
    return _schedule(LV=_game("BUF", SUN, "16:25"), HOU=_game("JAX", SUN, "09:30"),
                     PHI=_game("NYG", SUN, "13:00"), **more)


def test_the_decide_first_line_names_the_mover_whose_game_starts_first() -> None:
    """Reproduction (R08, 2026 week 6): "Dontayvion Wicks kicks off at Sun
    9:30 AM ET, before Ashton Jeanty's inactives … move David Montgomery to RB
    and start Dontayvion Wicks at FLEX". Wicks played at 1:00 PM; the 9:30
    London kickoff was Montgomery's, the one sliding across. The report's own
    row for Wicks said 1:00 PM, so it contradicted itself."""
    report = _report(_slide_roster(), yards={RB1: 90, RB2: 80, WR1: 85, WR2: 60},
                     designations={RB1: "Questionable"},
                     listed={RB1: ("questionable", "ankle")},
                     schedule=_slide_schedule())
    rows = _plans(report, "Ash Late")
    assert rows[0]["action"].startswith("Move Monty London to RB and start Wick "
                                        "Sunday at FLEX")
    assert rows[1]["action"].startswith(
        "Monty London kicks off at Sun 9:30 AM ET, before Ash Late's inactives "
        "(about Sun 2:55 PM ET). Decide before then: move Monty London to RB and "
        "start Wick Sunday at FLEX"), rows[1]["action"]


def test_the_game_day_row_says_who_kicks_off_first_by_name() -> None:
    """The other variant (H1): "Move Terry McLaurin into WR. Rhamondre
    Stevenson kicks off first" — Stevenson played at 1:00 PM, after the
    inactives; the early one was the mover, Nico Collins, in London."""
    roster = _slide_roster(RB3=("Lou Lateback", "RB", "DEN"))
    roster[RB3] = roster.pop("RB3")
    report = _report(roster, yards={RB1: 90, RB2: 80, WR1: 85, WR2: 60, RB3: 30},
                     designations={RB1: "Questionable"},
                     listed={RB1: ("questionable", "ankle")},
                     schedule=_slide_schedule(DEN=_game("NYJ", SUN, "16:25")))
    rows = _plans(report, "Ash Late")
    assert rows[1]["condition"] == "Ash Late (RB) sits as a game-day call"
    assert rows[1]["action"].startswith("Move Lou Lateback into RB")
    assert rows[1]["action"].endswith(". Monty London kicks off first."), rows[1]["action"]


def test_saturday_names_the_same_player_for_the_same_clock() -> None:
    """Saturday copied it: final_check on the R08 plan with Jeanty still
    questionable printed "Jerry Jeudy kicks off at Sun 9:30 AM ET"."""
    slots = [{"slot": "RB", "player_id": "jeanty"}, {"slot": "FLEX", "player_id": "monty"}]
    players = {pid: {"name": name, "position": pos, "projected": proj,
                     "last_season": None, "tuesday": "active"}
               for pid, name, pos, proj in (("jeanty", "Ashton Jeanty", "RB", 12.0),
                                            ("monty", "David Montgomery", "RB", 10.0),
                                            ("jeudy", "Jerry Jeudy", "WR", 5.2))}
    plan = {"season": "2026", "week": 6, "slug": "x", "slots": slots, "players": players}
    late = datetime(2026, 10, 18, 20, 25, tzinfo=UTC)      # 4:25 PM ET
    london = datetime(2026, 10, 18, 13, 30, tzinfo=UTC)    # 9:30 AM ET
    one = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)        # 1:00 PM ET
    now = {"jeanty": Now("questionable", "listed questionable (ankle)", kickoff=late),
           "monty": Now(kickoff=london), "jeudy": Now(kickoff=one)}
    [change] = final_check(plan, now)
    assert change.detail.startswith(
        "Ashton Jeanty is listed questionable (ankle). David Montgomery kicks off at "
        "Sun 9:30 AM ET, before Ashton Jeanty's inactives"), change.detail
    assert first_to_kick_off(["jeudy", "monty"], lambda pid: now[pid].kickoff) \
        == ("monty", london)


# --------------------------------------------------------------------- #
# ENG-2 / RQ2-05 / BE2-D4 — Saturday's reason is the true one
# --------------------------------------------------------------------- #

def _two_wr_plan() -> dict:
    slots = [{"slot": "WR", "player_id": "jeanty"}, {"slot": "WR", "player_id": "mclaurin"}]
    players = {pid: {"name": name, "position": "WR", "projected": proj,
                     "last_season": None, "tuesday": "active"}
               for pid, name, proj in (("jeanty", "Ashton Jeanty", 12.0),
                                       ("mclaurin", "Terry McLaurin", 11.0),
                                       ("jeudy", "Jerry Jeudy", 5.2),
                                       ("hurt", "Hurt Receiver", 4.0))}
    return {"season": "2026", "week": 6, "slug": "x", "slots": slots, "players": players}


def test_a_cover_named_for_another_starter_is_not_called_out_or_on_bye() -> None:
    """Reproduction (R08, wr3-nokd): Saturday gave Jerry Jeudy to Ashton
    Jeanty's plan, then told Terry McLaurin "Every other WR option on your
    roster is out or on bye, so keep him in." Jeudy was ACTIVE and playing
    Sunday at 1 PM — already named, which is a different fact."""
    sunday = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
    monday = datetime(2026, 10, 20, 0, 15, tzinfo=UTC)
    now = {"jeanty": Now("questionable", "listed questionable (ankle)", kickoff=sunday),
           "mclaurin": Now("questionable", "listed questionable (hamstring)",
                           kickoff=monday),
           "jeudy": Now(kickoff=sunday), "hurt": Now("out", "listed out (knee)",
                                                     kickoff=sunday)}
    changes = final_check(_two_wr_plan(), now)
    detail = _detail(changes, WATCH, "Terry McLaurin")
    assert detail == ("Terry McLaurin is listed questionable (hamstring). Jerry Jeudy "
                      "is already Ashton Jeanty's fallback, and every other WR option "
                      "on your roster is out or on bye, so keep him in."), detail


def test_a_cover_whose_game_has_kicked_off_is_said_to_have_played() -> None:
    """Reproduction (BE2-D4, the buyer's ESPN roster): "Every other QB option
    on your roster is out or on bye, so keep him in" — the only other QB, Bo
    Nix, had played Thursday night. The out branch already said "already
    playing"; the questionable branch now names him."""
    slots = [{"slot": "QB", "player_id": "hurts"}, {"slot": "RB", "player_id": "walker"}]
    players = {pid: {"name": name, "position": pos, "projected": proj,
                     "last_season": None, "tuesday": "active"}
               for pid, name, pos, proj in (("hurts", "Jalen Hurts", "QB", 20.0),
                                            ("nix", "Bo Nix", "QB", 17.0),
                                            ("walker", "Kenneth Walker", "RB", 14.0),
                                            ("back", "Bench Back", "RB", 7.0))}
    plan = {"season": "2026", "week": 6, "slug": "x", "slots": slots, "players": players}
    thursday = datetime(2026, 10, 16, 0, 15, tzinfo=UTC)     # Thu 8:15 PM ET
    sunday = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
    now = {"hurts": Now("questionable", "listed questionable (knee)", kickoff=sunday),
           "nix": Now(locked=True, kickoff=thursday),
           "walker": Now("out", "listed out (ankle)", kickoff=sunday),
           "back": Now(kickoff=sunday)}
    changes = final_check(plan, now)
    assert any(c.kind == SWAP for c in changes)
    detail = _detail(changes, WATCH, "Jalen Hurts")
    assert detail == ("Jalen Hurts is listed questionable (knee). Bo Nix played "
                      "Thursday, so keep him in."), detail
    assert "out or on bye" not in detail


def test_with_nobody_left_at_all_the_check_says_so_without_inventing_a_reason() -> None:
    plan = _two_wr_plan()
    sunday = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
    del plan["players"]["jeudy"], plan["players"]["hurt"]
    changes = final_check(plan, {"jeanty": Now("out", "listed out (ankle)", kickoff=sunday),
                                 "mclaurin": Now(kickoff=sunday)})
    [hole] = [c for c in changes if c.kind == NO_FILL]
    assert hole.detail == ("Ashton Jeanty is listed out (ankle), and nobody else on "
                           "your roster can play WR. If you can add one before "
                           "kickoff, do.")
    assert clauses(["A", "B", "C"]) == "A, B, and C" and clauses(["A"]) == "A"


# --------------------------------------------------------------------- #
# ENG-3 — the practice squad reaches Saturday
# --------------------------------------------------------------------- #

def test_saturday_ranks_the_practice_squad_last_and_says_to_check_him() -> None:
    """Reproduction (R00, 2026 week 6): with Zay Flowers out, Saturday said
    "Move Chris Godwin Jr. to WR and start Lew Nichols III at FLEX — Lew
    Nichols III projects 3.6", with no caveat. Nichols was on the practice
    squad (DEV); Tuesday ranked him behind every confirmed option and said to
    check he'd been elevated."""
    from run.saturday import state_for
    kick = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
    at = datetime(2026, 10, 17, 16, 0, tzinfo=UTC)
    common = dict(starts={"PIT": kick, "HOU": kick}, listed={}, filed={"PIT", "HOU"}, at=at)
    squad = state_for("nichols", roster={"nichols": ("DEV", "PIT")}, **common)
    assert squad.practice_squad and squad.available
    assert not state_for("chubb", roster={"chubb": ("ACT", "HOU")}, **common).practice_squad

    slots = [{"slot": "WR", "player_id": "flowers"}]
    players = {pid: {"name": name, "position": "WR", "projected": proj,
                     "last_season": None, "tuesday": "active"}
               for pid, name, proj in (("flowers", "Zay Flowers", 12.0),
                                       ("nichols", "Lew Nichols", 3.6),
                                       ("shepard", "Sterling Healthy", 2.0))}
    plan = {"season": "2026", "week": 6, "slug": "x", "slots": slots, "players": players}
    out = Now("out", "listed out (ankle)", kickoff=kick)
    [swap] = final_check(plan, {"flowers": out, "nichols": squad,
                                "shepard": Now(kickoff=kick)})
    assert swap.action == "Start Sterling Healthy at WR", "confirmed before the squad"
    [swap] = final_check(plan, {"flowers": out, "nichols": squad,
                                "shepard": Now("out", "listed out", kickoff=kick)})
    assert swap.action == "Start Lew Nichols at WR"
    assert swap.detail.endswith("Lew Nichols is on the practice squad: check he's "
                                "been elevated."), swap.detail


# --------------------------------------------------------------------- #
# ENG-4 — one ranking for both days
# --------------------------------------------------------------------- #

def test_neither_day_slides_a_questionable_starter_across() -> None:
    """Reproduction (H3 nokd/ppr/12): Tuesday said "If Zay Flowers is ruled
    out: Move Ladd McConkey into WR"; Saturday, with Flowers out and nothing
    else changed, sent "Move Keenan Allen to WR and start Alvin Kamara at
    FLEX" — sliding a questionable Allen, which Tuesday refuses. Both days
    rank by engine.final_check.rank_covers now."""
    slots = [{"slot": "WR", "player_id": "flowers"}, {"slot": "FLEX", "player_id": "allen"}]
    players = {pid: {"name": name, "position": pos, "projected": proj,
                     "last_season": None, "tuesday": status}
               for pid, name, pos, proj, status in (
                   ("flowers", "Zay Flowers", "WR", 12.0, "questionable"),
                   ("allen", "Keenan Allen", "WR", 9.3, "questionable"),
                   ("mcconkey", "Ladd McConkey", "WR", 7.5, "active"),
                   ("kamara", "Alvin Kamara", "RB", 8.0, "active"))}
    plan = {"season": "2026", "week": 6, "slug": "x", "slots": slots, "players": players}
    kick = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
    now = {"flowers": Now("out", "listed out (ankle)", kickoff=kick),
           "allen": Now("questionable", "listed questionable (x)", kickoff=kick),
           "mcconkey": Now(kickoff=kick), "kamara": Now(kickoff=kick)}
    swap = next(c for c in final_check(plan, now) if c.kind == SWAP)
    assert swap.action == "Start Ladd McConkey at WR", swap.action
    # A healthy starter in the FLEX does slide, as Tuesday's plan would.
    now["allen"] = Now(kickoff=kick)
    swap = next(c for c in final_check(plan, now) if c.kind == SWAP)
    assert swap.action == "Move Keenan Allen to WR and start Alvin Kamara at FLEX"


def test_tuesday_and_saturday_name_the_same_cover_for_the_same_news() -> None:
    """The property itself: build Tuesday's report, store its plan the way
    run/tuesday.py does, give Saturday exactly the news Tuesday's row is
    about, and both name one cover."""
    from run.saturday import build_plan
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Zay Doubt", "WR", "BAL"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Keen Doubt", "WR", "IND"), WR3: ("Lad Healthy", "WR", "LAC"),
              RB2: ("Al Benchback", "RB", "NO")}
    report = _report(roster, yards={WR1: 90, WR2: 70, WR3: 55, RB2: 60, RB1: 80},
                     designations={WR1: "Questionable", WR2: "Questionable"},
                     listed={WR1: ("questionable", "ankle"), WR2: ("questionable", "x")})
    [tuesday] = _plans(report, "Zay Doubt")
    assert tuesday["action"].startswith("Move Lad Healthy into WR"), tuesday["action"]
    projections = {row["player_id"]: row.get("projected")
                   for row in report["lineup"] + report["bench"] if row.get("player_id")}
    statuses = {pid: ("questionable" if pid in (WR1, WR2) else "active") for pid in roster}
    plan = build_plan(report, projections, {}, statuses, "x")
    kick = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
    now = {pid: Now(kickoff=kick) for pid in plan["players"]}
    now[WR1] = Now("out", "listed out (ankle)", kickoff=kick)
    now[WR2] = Now("questionable", "listed questionable (x)", kickoff=kick)
    swap = next(c for c in final_check(plan, now) if c.kind == SWAP)
    assert swap.action == "Start Lad Healthy at WR", swap.action


def test_two_game_day_plans_never_lean_on_one_bench_player() -> None:
    """Tuesday named Keenan Allen as the game-day cover for four starters (H3
    flex2), where Saturday's check names a player once — each game-day plan is
    carried out alone, at the inactives, and both may be needed. The second
    starter's row says whose fallback the player already is."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Sunny Doubt", "WR", "BAL"), WR2: ("Monday Doubt", "WR", "WAS"),
              TE1: ("Tate Tightend", "TE", "KC"), WR3: ("Mo Backup", "WR", "SF")}
    report = _report(roster, slots=("QB", "RB", "WR", "WR", "TE"),
                     yards={WR1: 90, WR2: 85, WR3: 40},
                     designations={WR1: "Questionable", WR2: "Questionable"},
                     listed={WR1: ("questionable", "ankle"), WR2: ("questionable", "knee")},
                     schedule=_schedule(BAL=_game("CLE", SUN), WAS=_game("SF", MON, "20:15"),
                                        SF=_game("WAS", MON, "20:15", home=True)))
    [first] = _plans(report, "Sunny Doubt")
    assert first["action"].startswith("Move Mo Backup into WR")
    rows = _plans(report, "Monday Doubt")
    assert rows[0]["action"].startswith("Move Mo Backup into WR"), \
        "a ruling before game day is Saturday's to re-plan, like its swap"
    assert rows[1]["condition"] == "Monday Doubt (WR) is still questionable on game day"
    assert rows[1]["action"] == (
        "Mo Backup is Sunny Doubt's game-day fallback, and nobody else can step in "
        "after Monday Doubt's inactives — keep Monday Doubt and take a zero if he sits.")


def test_rank_covers_is_one_order() -> None:
    slots = [("WR", "a"), ("FLEX", "m")]
    order = rank_covers(0, slots, ["x", "y", "z", "q", "s"],
                        eligible_for=lambda pid, slot: True,
                        value=lambda pid: {"x": 5.0, "y": 5.0, "z": None, "q": 5.0,
                                           "s": 9.0}[pid],
                        questionable=lambda pid: pid == "q",
                        practice_squad=lambda pid: pid == "s",
                        incoming_ok=lambda pid: True, mover_ok=lambda pid: True)
    direct = [c for c in order if c[1] is None]
    assert [c[0] for c in direct] == ["x", "y", "q", "z", "s"]
    assert order.index(("x", None)) < order.index(("x", 1)), "a straight swap first"


# --------------------------------------------------------------------- #
# ENG-5 — a published probability is the same for everyone in its store
# --------------------------------------------------------------------- #

def _qb_season(roster: tuple[str, ...]):
    people = [Player(pid, pid, "QB", "KC") for pid in ("qa", "qb", "qc", "qd", "qe")]
    directory = PlayerDirectory(people)
    points = {"qa": 300, "qb": 250, "qc": 30, "qd": 280, "qe": 220}
    weekly = {w: {pid: {"passing_yards": yards} for pid, yards in points.items()}
              for w in (1, 2, 3, 4)}
    spec = RosterSpec(player_ids=roster, slots=("QB",), scoring="ppr")
    season = build_season(spec, weekly, directory, "2026", 5,
                          field=["qa", "qb", "qd", "qe"])
    return season, ProjectionModel(season, player_index(directory))


def test_a_deep_bench_player_outside_the_field_moves_nobody_elses_number() -> None:
    """Reproduction (BASE5, std/ppr/12): call be5e815bc03ed096, Josh Allen
    over Jalen Hurts, recorded 0.85 with Allen projected 25.9; add Shedeur
    Sanders to the bench and the same call id read 0.84 with Allen at 25.4,
    in the same store (typed-ppr-12-2026). The subscriber's own players sat on
    top of the field, so an out-of-field quarterback joined the positional
    prior; record_calls kept whichever subscriber ran first."""
    _, alone = _qb_season(("qa", "qb"))
    season, deep = _qb_season(("qa", "qb", "qc"))
    assert season.prior_pool == frozenset({"qa", "qb", "qd", "qe"})
    for pid in ("qa", "qb"):
        assert deep.project(pid, 5).mean == alone.project(pid, 5).mean, pid
        assert deep.project(pid, 5).sd == alone.project(pid, 5).sd, pid
    # He keeps his own form, shrunk toward the field's prior like anyone else.
    assert deep.project("qc", 5) is not None


def test_a_roster_inside_the_field_draws_the_prior_it_always_did() -> None:
    """The frozen harnesses never set a pool, and a roster wholly inside the
    field gets exactly the pool it always had — so no graded number moves
    (verified on 120 in-field rosters and the proving run, Oct 17 2026)."""
    season, pooled = _qb_season(("qa", "qb"))
    season.prior_pool = None
    unpooled = ProjectionModel(season, pooled.players)
    assert pooled.project("qa", 5).mean == unpooled.project("qa", 5).mean


# --------------------------------------------------------------------- #
# ENG-6 / RQ2-03 — one call, one number
# --------------------------------------------------------------------- #

def _qb_pair_report(monkeypatch, raw: float) -> dict:
    monkeypatch.setattr(wr, "probability_outscores", lambda a, b: raw)
    roster = {QB1: ("Quinn Starter", "QB", "KC"), QB2: ("Bo Backup", "QB", "SF"),
              RB1: ("Rory Runner", "RB", "KC"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC"), WR2: ("Wes Slotman", "WR", "KC")}
    return _report(roster, yards={QB1: 120, QB2: 60},
                   ranks={QB2: ("QB", 5, 40)}, prior_form={QB2: 20.0})


def test_the_game_plan_prints_the_number_the_row_and_the_ledger_carry(monkeypatch) -> None:
    """Reproduction (R22, roster A): the game plan printed "Start Matthew
    Stafford over Bo Nix at QB · 77%" from the raw 0.76536 while the row and
    the ledger read 0.765 as 76%; roster A printed 59% in the plan and 60% on
    the row, the closest call and the preheader. Rounded once, read once."""
    report = _qb_pair_report(monkeypatch, 0.5945)
    row = _row(report, "Quinn Starter")
    assert row["confidence"] == 0.595
    line = next(i for i in report["checklist"] if i["action"].startswith("Start Quinn"))
    assert line["action"].endswith(f"· {rr._pct(row['confidence'])}%"), line["action"]
    assert line["action"].endswith("· 60%")
    for value in (0.5945, 0.765, 0.52501, 0.5, 0.999, 0.0004):
        stored = stored_confidence(value)
        assert printed_percent(stored) == rr._pct(stored), value


def test_a_printed_52_is_a_toss_up_wherever_it_prints(monkeypatch) -> None:
    """Reproduction (R074): Croskey-Merritt over Dobbins stored 0.525 and
    printed 52% with no toss-up label — the test read the raw 0.52501 as 53."""
    report = _qb_pair_report(monkeypatch, 0.52501)
    row = _row(report, "Quinn Starter")
    assert rr._pct(row["confidence"]) == 52
    assert row["tossup"] is True
    assert "toss-up: either is fine" in rr.call_bits(row)


# --------------------------------------------------------------------- #
# ENG-7 / ENG-8 / ENG-9 — every row explains only what it shows
# --------------------------------------------------------------------- #

def test_a_row_without_odds_never_explains_whom_the_odds_were_against() -> None:
    """Reproduction (H1 FLEX): "Rhamondre Stevenson (11.3) was questionable,
    so the odds are against Zach Ertz" on a row whose odds the practice-squad
    hold had withheld — no percentage anywhere on it."""
    row = {"edge": 8.7, "alternative_name": "Zach Ertz", "confidence": None,
           "doubtful_alternative_name": "Rhamondre Stevenson",
           "doubtful_alternative_projected": 11.3}
    assert not any("odds are against" in bit for bit in rr.call_bits(row))
    row["confidence"] = 0.71
    assert any("so the odds are against Zach Ertz" in bit for bit in rr.call_bits(row))

    class Model:
        def project(self, pid, week):
            return None

        def observations(self, pid, week):
            return []

    players = player_index(PlayerDirectory([Player("st", "Rhett Doubt", "RB", "NE")]))
    pick = SlotPick("FLEX", 0, "a", None, None, None, "not confirmed to play (x)", "su",
                    None, [], "st", None)
    out: dict = {}
    _form_facts(out, pick, players, Model(), 6, None)
    assert "doubtful_alternative_name" not in out


def test_a_held_input_is_named_as_the_reason_not_a_healthy_player() -> None:
    """Reproduction (BASE5 + Jake Ferguson, flex2, context unreadable): the
    closest call said "no odds, because James Cook's status isn't confirmed
    yet" — Cook had no designation; the missing input held the odds."""
    players = player_index(PlayerDirectory([Player("c", "James Cook", "RB", "BUF"),
                                            Player("l", "Drake London", "WR", "ATL")]))
    pick = SlotPick("FLEX", 6, "c", None, None, None, SHAPE_INPUT_GATE, "l", None, [])
    availability = WeekAvailability("2026", 6, "w5", {}, frozenset())
    assert _named_reason(pick, players, availability, None) == \
        "an input these odds need is missing this week"


def test_a_defense_row_says_defenses_carry_no_odds_whoever_is_on_the_bench() -> None:
    """Reproduction (H1, std/ppr/12): with the only bench defense on bye the
    DEF row read "Seattle Seahawks 5.8 · Detroit Lions on bye" and the note
    dropped "defenses get a projection only" — as if odds would print with a
    playable bench defense. A playable one (R08) printed "projection only"."""
    people = [Player("DEF-SEA", "Seattle Seahawks", "DEF", "SEA"),
              Player("DEF-DET", "Detroit Lions", "DEF", "DET")]
    directory = PlayerDirectory(people)
    weekly = {w: {"DEF-SEA": {"def_sacks": 3, "points_allowed": 17},
                  "DEF-DET": {"def_sacks": 2, "points_allowed": 20}} for w in (1, 2, 3, 4)}
    spec = RosterSpec(player_ids=("DEF-SEA", "DEF-DET"), slots=("DEF",), scoring="ppr")
    season = build_season(spec, weekly, directory, "2026", 5)
    players = player_index(directory)
    model = ProjectionModel(season, players)
    statuses = {pid: {"team": pid[4:], "position": "DEF", "active": True,
                      "injury_status": None} for pid in spec.player_ids}
    team_week = season.weeks[4][1]
    for byes in (frozenset({"DET"}), frozenset()):
        availability = WeekAvailability("2026", 5, "w4", statuses, byes)
        [pick] = optimal_lineup(season, team_week, model, players, availability, 5)
        assert pick.player_id == "DEF-SEA" and pick.confidence is None
        assert pick.confidence_gate == DEFENSE_GATE, (byes, pick.confidence_gate)
    assert rr.row_label({"confidence_gate": DEFENSE_GATE}) == "projection only"


# --------------------------------------------------------------------- #
# ENG-10 — the sample's stamp is on the buyer's clock
# --------------------------------------------------------------------- #

def test_the_samples_rebuilt_date_is_eastern() -> None:
    """Reproduction: at Fri Oct 16 2026 11:35 PM EDT `python -m render.sample`
    wrote "Rebuilt Oct 17, 2026" — the UTC date. Every other stamp is ET."""
    stamp = rr._generated_stamp({"historical_demo": True, "season": "2024",
                                 "generated_at": "2026-10-17T03:35:00+00:00"})
    assert stamp == "Rebuilt Oct 16, 2026 from the 2024 season archive"


# --------------------------------------------------------------------- #
# RQ2-02 — Week 1: defenses by their record, and the lineup to set
# --------------------------------------------------------------------- #

def _week_one(prior_form: dict) -> dict:
    from engine.solo_report import build_solo_report
    people = [Player("00-0000801", "Quinn Starter", "QB", "SF"),
              Player("00-0000802", "Rory Runner", "RB", "SF"),
              Player("DEF-NE", "New England Patriots", "DEF", "NE"),
              Player("DEF-SEA", "Seattle Seahawks", "DEF", "SEA"),
              Player("DEF-SF", "San Francisco 49ers", "DEF", "SF")]
    directory = PlayerDirectory(people)
    spec = RosterSpec(player_ids=tuple(p.player_id for p in people),
                      slots=("QB", "RB", "DEF"), scoring="ppr")
    season = build_season(spec, {}, directory, "2026", 1)
    players = player_index(directory)
    availability = WeekAvailability("2026", 1, None, None, frozenset())
    return build_solo_report(spec, season, players, ProjectionModel(season, players),
                             availability, 1, Path("/nonexistent"),
                             prior_form=prior_form)


def test_week_one_starts_the_defense_with_the_better_record_not_the_first_name() -> None:
    """Reproduction (2026 week 1, live): two defenses on the roster and New
    England started over Seattle on the ids alone (DEF-NE < DEF-SEA) — the
    placement's own docstring calls that "reproducible and meaningless" — while
    the game plan said the slots were filled "in last season's scoring order,
    shown on each line". Defenses are ordered by their own record now."""
    report = _week_one({"00-0000801": 20.6, "00-0000802": 15.0, "DEF-NE": 6.2,
                        "DEF-SEA": 8.7, "DEF-SF": 3.2})
    defense = next(s for s in report["lineup"] if s["slot"] == "DEF")
    assert defense["player_name"] == "Seattle Seahawks"
    assert all(s.get("confidence") is None and s.get("projected") is None
               for s in report["lineup"]), "placement only"


def test_week_one_sets_the_lineup_and_gives_the_true_reason_for_no_odds() -> None:
    """The week-1 game plan had no "Set this lineup" — the line every other
    week leads with — and the note under the lineup said "a player's status
    isn't confirmed yet" above a week with no injury report at all."""
    report = _week_one({})
    first = report["checklist"][0]
    assert first["action"] == "Set this lineup"
    assert first["detail"].startswith("QB Quinn Starter · RB Rory Runner · DEF ")
    assert "%" not in first["detail"]
    assert report["checklist"][1]["action"].startswith("No start-sit calls yet")
    assert rr.gate_phrase("no game record yet to compare against") == \
        "nobody has played a game this season yet"


def test_week_one_defense_record_comes_from_last_seasons_box_scores() -> None:
    """run.solo reads last season's team-defense weeks as a RECORD beside the
    field: the positional prior, the field and the anchor never see them."""
    import run.solo as solo
    data = type("Data", (), {"prior_defense": {"DEF-SEA": [10.0, 7.0], "DEF-NE": []},
                             "week": 1})()
    assert solo._defense_form(data) == {"DEF-SEA": 8.5}
    assert solo._defense_form_line("DEF-SEA", data) == "last season: 8.5 a game over 2 games"
    assert solo._defense_form_line("DEF-NE", data) is None
    cache = solo.CACHE_DIR / "stats_team_week_2025.csv"
    if not cache.is_file():
        pytest.skip("needs the cached 2025 team-defense release")
    record = solo._prior_defense(solo.CACHE_DIR, "2025")
    assert len(record) == 32 and all(len(games) == 17 for games in record.values())


# --------------------------------------------------------------------- #
# RQ2-04 / F10 — the superflex line, only when no quarterback can fill it
# --------------------------------------------------------------------- #

def _sf_pick() -> tuple[SlotPick, PlayerIndex, dict, dict]:
    players = player_index(PlayerDirectory([Player("w", "Rashid Shaheed", "WR", "SEA"),
                                            Player("q", "Lamar Jackson", "QB", "BAL")]))
    pick = SlotPick("SUPER_FLEX", 7, "w", None, None, None, None, None, None, [])
    ranks = {f"q{i}": ("QB", i, 30) for i in range(1, 31)}
    ranks |= {f"r{i}": ("WR", i, 90) for i in range(1, 91)}
    form = {f"q{i}": 25.0 - i * 0.5 for i in range(1, 31)}
    form |= {f"r{i}": 20.0 - i * 0.4 for i in range(1, 91)}
    return pick, players, form, ranks


def test_a_healthy_bench_quarterback_gets_no_superflex_line_and_no_waiver_nudge() -> None:
    """Reproduction (roster T, half-PPR sf): "Your SFLEX has no quarterback
    this week — CeeDee Lamb (WR) starts there … A second quarterback off your
    waiver wire may be worth a look" while Daniel Jones sat healthy on the
    bench and the QB row read "79% vs Daniel Jones"."""
    pick, players, form, ranks = _sf_pick()
    healthy = [{"player_id": "q", "name": "Daniel Jones", "position": "QB", "out": False}]
    assert superflex_items([pick], players, form, ranks, 12, bench=healthy) == []
    bye = [{"player_id": "q", "name": "Daniel Jones", "position": "QB", "out": True,
            "out_kind": "bye"}]
    [item] = superflex_items([pick], players, form, ranks, 12, bench=bye)
    assert "waiver" not in item["detail"], "never with a quarterback on the bench"


def test_a_bench_quarterback_with_his_status_open_is_named() -> None:
    """Reproduction (COPY F10, the live sample in superflex): the SFLEX line
    said "no quarterback this week" with Lamar Jackson (14.3) on the bench,
    ruled out in Week 5 and his Week 6 status not yet announced — and Rashid
    Shaheed in the SFLEX playing Thursday, before that news."""
    pick, players, form, ranks = _sf_pick()
    bench = [{"player_id": "q", "name": "Lamar Jackson", "position": "QB", "out": True,
              "out_kind": "designation",
              "out_text": "Ruled out for Week 5 (ankle) — Week 6 status not announced yet"}]
    games = {"w": _game("DEN", THU, "20:15"), "q": _game("CLE", SUN)}
    [item] = superflex_items([pick], players, form, ranks, 12, bench=bench,
                             game_of=games.get, sunday=date.fromisoformat(SUN))
    assert item["action"] == ("Your SUPER_FLEX has no quarterback yet — Rashid Shaheed "
                              "(WR) starts there")
    assert item["detail"] == (
        "Lamar Jackson: Ruled out for Week 5 (ankle) — Week 6 status not announced "
        "yet. Rashid Shaheed plays Thursday, before that news is in, so decide "
        "before then.")
    assert "waiver" not in item["detail"]
    # In time for his news, his own "if he's cleared" line is the plan.
    games["w"] = _game("DEN", SUN, "16:25")
    assert superflex_items([pick], players, form, ranks, 12, bench=bench,
                           game_of=games.get, sunday=date.fromisoformat(SUN)) == []


# --------------------------------------------------------------------- #
# RQ2-06 — one subscription, one team name
# --------------------------------------------------------------------- #

def test_the_team_name_comes_from_the_roster_not_this_weeks_projections() -> None:
    """Reproduction (proving run, 2025 weeks 4-8): 8 of 12 subscriptions
    changed name — "Bijan Robinson's team" → "Garrett Wilson's" → "Jayden
    Daniels's" → "Bijan Robinson's" — and one became a bye-week receiver's."""
    report = _report({QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
                      WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
                      WR2: ("Wes Slotman", "WR", "KC")},
                     yards={WR2: 200}, prior_form={RB1: 18.0, QB1: 17.0},
                     ranks={RB1: ("RB", 8, 80), QB1: ("QB", 14, 40)})
    assert report["meta"]["team_lead"] == "Rory Runner"
    later = _report({QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
                     WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
                     WR2: ("Wes Slotman", "WR", "KC")},
                    yards={QB1: 300}, prior_form={RB1: 18.0, QB1: 17.0},
                    ranks={RB1: ("RB", 8, 80), QB1: ("QB", 14, 40)})
    assert later["meta"]["team_lead"] == "Rory Runner"
    for doc in (report, later):
        doc["meta"].update(plan="season")
    assert rr.team_name(report) == rr.team_name(later) == "Rory Runner's team"


# --------------------------------------------------------------------- #
# RQ2-07 — a Monday-night questionable is checked on Monday
# --------------------------------------------------------------------- #

def test_a_monday_night_questionable_is_checked_at_his_own_inactives() -> None:
    """Reproduction (roster O, wr3-nod/ppr/8): Terry McLaurin questionable for
    Monday night, his cover in the same game, and the game plan said "Sunday
    morning: check Terry McLaurin's status (gameday morning)". The call is
    made at Monday's inactives, about 6:45 PM ET."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Terry Monday", "WR", "WAS"), TE1: ("Tate Tightend", "TE", "KC"),
              RB2: ("Jake Sameplay", "RB", "SF"), WR2: ("Sunny Doubt", "WR", "BAL")}
    report = _report(roster, slots=("QB", "RB", "WR", "WR", "TE"),
                     yards={WR1: 90, RB2: 30, WR2: 80},
                     designations={WR1: "Questionable", WR2: "Questionable"},
                     listed={WR1: ("questionable", "hamstring"),
                             WR2: ("questionable", "ankle")},
                     schedule=_schedule(WAS=_game("SF", MON, "20:15"),
                                        SF=_game("WAS", MON, "20:15", home=True),
                                        BAL=_game("CLE", SUN)))
    actions = {i["action"]: i for i in report["checklist"]}
    monday = actions.get("Monday: check Terry Monday's status")
    assert monday and monday["deadline"] == "by Monday 6:45 PM ET", report["checklist"]
    sunday = actions.get("Sunday morning: check Sunny Doubt's status")
    assert sunday and sunday["deadline"] == "gameday morning"
    for name, page in _surfaces(report).items():
        assert "Sunday morning: check Terry Monday" not in page, name
        assert "check on Sunny Doubt and Terry Monday" not in page, name
