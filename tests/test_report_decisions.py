"""What the report decides, and how each row and plan says it — the
world-class review, Oct 15 2026.

A six-lens panel read real week-6 reports against FantasyPros, the league
apps' optimizers and the paid expert sites, and confirmed defects in the
CONTENT of the rows and the plans: a pivot naming a player already locked when
the news lands, an if/then that denied a questionable starter it had just
flagged, odds published against a practice-squad player, a "closest call" that
was not the closest, toss-ups printed as instructions. Each test below states
its reproduction.

Principle 1 throughout: nothing here may ADD or MOVE a published percentage,
change a projection, the recalibration or the publish gate. These fixes state
facts the report already holds, choose who a plan names, and withhold.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.availability import PlayerStatus, Status, WeekAvailability
from engine.final_check import Now, final_check
from engine.projection import Projection, ProjectionModel
from engine.roster import Player, PlayerDirectory
from engine.solo_report import (INACTIVES_LEAD, after_inactives, build_solo_report,
                                early_kickoff_items, hold_unconfirmed, kickoff,
                                live_availability)
from engine.subscriber import RosterSpec, build_season, player_index
from engine.usage import Usage, usage_line
from engine.week_report import SlotPick
from render.email import render_email, short_usage, text_summary
from render.report import (PROJECTION_NOTE, TEMPLATE_PATH, gate_note, render,
                           row_label)

THU, SAT, SUN, MON = "2026-10-08", "2026-10-10", "2026-10-11", "2026-10-12"


def _pid(i: int) -> str:
    return f"00-00002{i:02d}"


def _game(opponent: str, day: str, time: str = "13:00", home: bool = False) -> dict:
    return {"opponent": opponent, "home": home, "day": day, "time": time}


def _schedule(**overrides: dict) -> dict:
    out = {team: _game("OPP", SUN) for team in ("KC", "SF", "BUF", "LV", "SEA",
                                                "DEN", "NYJ", "WAS", "PHI", "CHI")}
    out.update(overrides)
    return out


def _report(roster: dict[str, tuple[str, str, str]], *,
            slots=("QB", "RB", "WR", "TE", "FLEX"),
            yards: dict[str, int] | None = None,
            missed: dict[str, set[int]] | None = None,
            designations: dict[str, str] | None = None,
            listed: dict[str, tuple[str, str]] | None = None,
            byes: frozenset[str] = frozenset(),
            schedule: dict | None = None,
            reserve: dict[str, str] | None = None,
            live_out: dict[str, str] | None = None,
            unconfirmed: dict[str, str] | None = None,
            ranks: dict | None = None,
            prior_form: dict | None = None,
            shape_graded: bool = True) -> dict:
    """Week 5 of 2026 through the real builders. ``roster``: pid -> (name,
    position, team); every other knob is a fact about the week."""
    yards = yards or {}
    missed = missed or {}
    reserve = reserve or {}
    people = [Player(pid, name, pos, team) for pid, (name, pos, team) in roster.items()]
    directory = PlayerDirectory(people)
    ids = tuple(roster)
    weekly = {w: {pid: {"receiving_yards": yards.get(pid, 50), "team": roster[pid][2]}
                  for pid in ids if w not in missed.get(pid, set())}
              for w in (1, 2, 3, 4)}
    spec = RosterSpec(player_ids=ids, scoring="ppr", label="Your Team", slots=slots)
    season = build_season(spec, weekly, directory, "2026", 5, league_size=12)
    players = player_index(directory)
    model = ProjectionModel(season, players)
    statuses = {pid: {"team": team, "position": pos, "active": pid not in reserve,
                      "out_reason": reserve.get(pid),
                      "injury_status": (designations or {}).get(pid)}
                for pid, (_, pos, team) in roster.items()}
    availability = WeekAvailability("2026", 5, "the week 4 injury report",
                                    statuses, byes)
    return build_solo_report(
        spec, season, players, model, availability, 5, Path("/nonexistent"),
        schedule=_schedule() if schedule is None else schedule,
        teams={pid: team for pid, (_, _, team) in roster.items()},
        injury_report={"week": 4, "listed": listed or {}},
        live_out=live_out, unconfirmed=unconfirmed,
        last_season_ranks=ranks, prior_form=prior_form, shape_graded=shape_graded)


def _surfaces(report: dict) -> dict[str, str]:
    import html as _html
    pages = {"browser": render(report, TEMPLATE_PATH.read_text(encoding="utf-8")),
             "email": render_email(report), "text": text_summary(report)}
    pages = {name: re.sub(r"<style\b.*?</style>|<!--.*?-->", " ", page, flags=re.S | re.I)
             for name, page in pages.items()}
    return {name: _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))
            for name, page in pages.items()}


def _row(report: dict, name: str) -> dict:
    return next(s for s in report["lineup"] if s["player_name"] == name)


def _bench(report: dict, name: str) -> dict:
    return next(b for b in report["bench"] if b["name"] == name)


def _plans(report: dict, name: str) -> list[dict]:
    return [p for p in report["pivots"] if p["condition"].startswith(name)]


def _published(report: dict) -> set[tuple]:
    return {(s["slot"], s["player_id"], s["alternative_id"], s["confidence"])
            for s in report["lineup"] if s.get("confidence") is not None}


QB1, QB2, RB1, RB2, WR1, WR2, WR3, TE1, TE2, RB3 = (_pid(i) for i in range(1, 11))


# --------------------------------------------------------------------- #
# RQ-01 / RQ-09 — the plan waits for the news it names
# --------------------------------------------------------------------- #

def test_a_game_day_ruling_lands_ninety_minutes_before_his_own_kickoff() -> None:
    """The reproduction (2026 week 6, roster r14): "If Ashton Jeanty (RB) is
    ruled out: Move Alvin Kamara into RB" — Jeanty played at 4:25 PM, so a
    game-day ruling came about 2:55 PM, after Kamara's 1:00 PM kickoff had
    locked him. The old clock compared days."""
    late = _game("BUF", SUN, "16:25")
    assert not after_inactives(_game("NYG", SUN, "13:00"), late)
    assert after_inactives(_game("NYG", SUN, "14:55"), late), "exactly at the inactives"
    assert after_inactives(_game("NYG", SUN, "16:25"), late)
    assert not after_inactives(_game("SF", SUN, "20:20"), _game("SF", MON, "20:15"))
    assert after_inactives(None, late), "no game never locks first"
    # A London kickoff (RQ-09) is ruled on at 8:00 AM ET: a 1 PM player is in time.
    assert after_inactives(_game("NYG", SUN, "13:00"), _game("JAX", SUN, "09:30"))
    assert kickoff(late) - INACTIVES_LEAD == datetime(2026, 10, 11, 14, 55)


def _late_q(schedule: dict) -> dict:
    roster = {QB1: ("Quinn Starter", "QB", "PHI"), RB1: ("Ash Late", "RB", "LV"),
              RB2: ("Al Early", "RB", "KC"), WR1: ("Wade Wideout", "WR", "PHI"),
              TE1: ("Tate Tightend", "TE", "PHI"), WR2: ("Wes Slotman", "WR", "PHI")}
    return _report(roster, yards={RB1: 90, RB2: 70, WR1: 80, WR2: 75},
                   designations={RB1: "Questionable"},
                   listed={RB1: ("questionable", "ankle")}, schedule=schedule)


def test_only_an_earlier_cover_gives_the_late_swap_call_not_a_dead_plan() -> None:
    """The same roster: the only RB behind a 4:25 PM questionable starter plays
    at 1:00 PM. A ruling on the final report still lets him in; a game-day
    ruling cannot. So two rows — and the second is the call an expert makes,
    with no number on either side."""
    report = _late_q(_schedule(LV=_game("BUF", SUN, "16:25")))
    rows = _plans(report, "Ash Late")
    assert [p["condition"] for p in rows] == [
        "Ash Late (RB) is ruled out before game day",
        "Ash Late (RB) is still questionable on game day"]
    assert rows[0]["action"].startswith("Move Al Early into RB (projects ")
    assert rows[1]["action"] == (
        "Al Early kicks off at Sun 1:00 PM ET, before Ash Late's inactives (about "
        "Sun 2:55 PM ET). Decide before then: start Al Early, or keep Ash Late and "
        "take a zero if he sits.")
    assert "%" not in rows[1]["action"]
    assert _row(report, "Ash Late")["if_then"] is True


def test_a_cover_who_plays_after_the_inactives_is_the_plan_either_way() -> None:
    report = _late_q(_schedule(LV=_game("BUF", SUN, "16:25"),
                               KC=_game("DEN", SUN, "16:25")))
    [plan] = _plans(report, "Ash Late")
    assert plan["condition"] == "Ash Late (RB) is ruled out"
    assert plan["action"].startswith("Move Al Early into RB")


def test_saturday_never_offers_a_player_locked_before_the_inactives() -> None:
    """The Saturday reproduction: Terry McLaurin still questionable on his
    final report for Monday night, and the check said "If he's ruled out,
    start Ladd McConkey at FLEX" — McConkey kicked off Sunday at 4:25 PM."""
    slots = [{"slot": "WR", "player_id": "mcl"}, {"slot": "FLEX", "player_id": "flx"}]
    players = {pid: {"name": pid.title(), "position": "WR", "projected": proj,
                     "last_season": None, "tuesday": "active"}
               for pid, proj in (("mcl", 12.0), ("flx", 9.0), ("sun", 8.0),
                                 ("mon", 5.0))}
    plan = {"season": "2026", "week": 6, "slug": "x", "slots": slots,
            "players": players}
    sunday = datetime(2026, 10, 18, 20, 25, tzinfo=timezone.utc)      # 4:25 PM ET
    monday = datetime(2026, 10, 20, 0, 15, tzinfo=timezone.utc)       # 8:15 PM ET
    now = {"mcl": Now("questionable", "listed questionable (hamstring)", kickoff=monday),
           "flx": Now(kickoff=sunday), "sun": Now(kickoff=sunday)}
    [change] = final_check(plan, dict(now, mon=Now(kickoff=monday)))
    assert "start Mon at WR" in change.detail and "Sun" not in change.detail.split(".")[1]
    [change] = final_check(plan, now)
    assert change.detail == (
        "Mcl is listed questionable (hamstring). Sun kicks off at Sun 4:25 PM ET, "
        "before Mcl's inactives (about Mon 6:45 PM ET). Decide before then: start "
        "Sun, or keep Mcl and take a zero if he sits.")
    # Without kickoffs (an older plan), nothing changes from before.
    bare = {pid: Now(n.designation, n.reason) for pid, n in now.items()}
    [change] = final_check(plan, bare)
    assert "If he's ruled out, start Sun at WR" in change.detail


def test_a_london_kickoff_is_early_and_a_defense_is_set_not_checked() -> None:
    """RQ-09: seven starters at Wembley, 9:30 AM ET, got only "Sunday morning:
    check his status (gameday morning)" — 6:30 AM for a reader out west, with
    inactives at 8:00. Any kickoff before the main 1 PM slot is early."""
    directory = PlayerDirectory([Player("a", "Andy London", "QB", "JAX"),
                                 Player("b", "Ben London", "WR", "JAX"),
                                 Player("DEF-JAX", "Jacksonville Jaguars", "DEF", "JAX"),
                                 Player("c", "Cal Sunday", "RB", "KC")])
    games = {"a": _game("LA", SUN, "09:30"), "b": _game("LA", SUN, "09:30"),
             "DEF-JAX": _game("LA", SUN, "09:30"), "c": _game("DEN", SUN, "13:00")}
    items, ids = early_kickoff_items(["a", "b", "DEF-JAX", "c"],
                                     player_index(directory), games.get,
                                     date.fromisoformat(SUN))
    assert [i["action"] for i in items] == [
        "Sunday morning: Andy London, Ben London and Jacksonville Jaguars kick off "
        "at 9:30 AM ET — check their status before then."]
    assert items[0]["deadline"] == "before Sunday's 9:30 AM ET kickoff"
    assert ids == {"a", "b", "DEF-JAX"}


# --------------------------------------------------------------------- #
# BE-D2 / SS-D3 / SS-D4 / G20 — the if/then considers a flex slide, and
# never denies the questionable starter it has just flagged
# --------------------------------------------------------------------- #

def _flowers(**kwargs) -> dict:
    """The live sample's shape: a questionable WR, the only bench WR playing
    Thursday, a FLEX receiver who can slide across and a bench TE for the FLEX."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Zay Questionable", "WR", "BAL"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Rome Flex", "WR", "CHI"), WR3: ("Rashid Thursday", "WR", "SEA"),
              TE2: ("Zach Backup", "TE", "PHI")}
    return _report(roster, yards={WR1: 80, WR2: 70, WR3: 40, TE1: 60, TE2: 30},
                   designations={WR1: "Questionable"},
                   listed={WR1: ("questionable", "foot")},
                   schedule=_schedule(SEA=_game("DEN", THU, "20:15"),
                                      BAL=_game("CLE", SUN)), **kwargs)


def test_a_flex_starter_slides_across_when_nobody_can_step_in_directly() -> None:
    """The reproduction: site/this-week.html (2026 week 6) said "If Zay Flowers
    is out, nobody on your bench can step in at WR in time" while Rome Odunze
    sat at FLEX and a bench player could take the FLEX — the same move
    Saturday's check already made, so the two days disagreed."""
    report = _flowers()
    [plan] = _plans(report, "Zay Questionable")
    assert plan["action"].startswith("Move Rome Flex to WR and start Zach Backup at "
                                     "FLEX (projects ")
    assert "Rashid Thursday" in plan["action"] and "plays Thursday" in plan["action"]
    assert report["pivots_note"] is None
    for name, page in _surfaces(report).items():
        assert "no starter we can check is listed questionable" not in page, name


def test_with_no_cover_at_all_the_if_then_says_who_and_why() -> None:
    """SS-D3/G20: the empty if/then read "no starter we can check is listed
    questionable" beside a row flagging Zay Flowers questionable and a game
    plan telling the reader to check on him. The empty state now gives the
    true reason, by name, on every surface."""
    report = _flowers(live_out={TE2: "not with his team"})
    assert not _plans(report, "Zay Questionable")
    note = report["pivots_note"]
    assert note == ("No pivots this week. If Zay Questionable is out, nobody on your "
                    "bench can step in at WR in time — Rashid Thursday plays before "
                    "Zay Questionable's status is known.")
    for name, page in _surfaces(report).items():
        if name == "text":
            continue                      # plain text prints no empty if/then
        assert note in page, name
        assert "no starter we can check is listed questionable" not in page, name


def test_no_cover_names_the_bench_player_who_could_be_cleared() -> None:
    """r04 (2026 week 6): "If Terry McLaurin is out, nobody on your bench can
    play WR" while DeVonta Smith — ruled out in Week 5, a bench WR with his own
    "if he's cleared" plan — sat two lines below. F11's rule: the sentence
    names him instead of denying he is there."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Terry Doubt", "WR", "WAS"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Devon Ruledout", "WR", "PHI")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"),
                     yards={WR1: 90, WR2: 40},
                     designations={WR1: "Questionable", WR2: "Out"},
                     listed={WR1: ("questionable", "hamstring"),
                             WR2: ("out", "hamstring")})
    line = ("If Terry Doubt is out, nobody on your bench can play WR unless "
            "Devon Ruledout is cleared.")
    assert report["pivots_note"] == f"No pivots this week. {line}"
    assert any(line in (i.get("detail") or "") for i in report["checklist"]), \
        report["checklist"]
    for name, page in _surfaces(report).items():
        assert "nobody on your bench can play WR." not in page, name
    # Cleared or not, a Thursday player is locked before a Sunday starter's
    # news: he is named as too early, never as the way out.
    early = _report(roster, slots=("QB", "RB", "WR", "TE"),
                    yards={WR1: 90, WR2: 40},
                    designations={WR1: "Questionable", WR2: "Out"},
                    listed={WR1: ("questionable", "hamstring"),
                            WR2: ("out", "hamstring")},
                    schedule=_schedule(PHI=_game("NYG", THU, "20:15")))
    assert early["pivots_note"] == (
        "No pivots this week. If Terry Doubt is out, nobody on your bench can step "
        "in at WR in time — Devon Ruledout plays before Terry Doubt's status is known.")


def test_a_game_day_call_spells_out_the_slide_it_asks_for() -> None:
    """r14: "Decide before then: make that move, or keep Terry McLaurin…" —
    "that move" was the row above's, and a reader acting at 12:55 PM reads one
    line. The slide is named in full."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Terry Monday", "WR", "WAS"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Kal Flex", "WR", "CHI"), RB2: ("Al Sunday", "RB", "NO")}
    report = _report(roster, yards={WR1: 90, WR2: 80, RB1: 70, RB2: 40},
                     designations={WR1: "Questionable"},
                     listed={WR1: ("questionable", "hamstring")},
                     schedule=_schedule(WAS=_game("SF", MON, "20:15"),
                                        CHI=_game("ATL", SUN), NO=_game("NYG", SUN)))
    rows = _plans(report, "Terry Monday")
    assert rows[0]["action"].startswith("Move Kal Flex to WR and start Al Sunday at FLEX")
    assert "that move" not in rows[1]["action"]
    assert ("Decide before then: move Kal Flex to WR and start Al Sunday at FLEX, or "
            "keep Terry Monday and take a zero if he sits.") in rows[1]["action"]


def test_the_game_plan_line_benching_an_even_player_says_why() -> None:
    """r03 (2026 week 6): "Bench George Pickens — Zay Flowers starts at WR …
    Projects 9.6, Zay Flowers 9.6." Flowers was questionable; the row said why
    he starts (Pickens plays after his news), the game plan did not."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Zay Doubt", "WR", "BAL"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("George Even", "WR", "PIT")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"), yards={WR1: 70, WR2: 70},
                     designations={WR1: "Questionable"},
                     listed={WR1: ("questionable", "foot")},
                     ranks={WR2: ("WR", 6, 120)},
                     schedule=_schedule(BAL=_game("CLE", SUN),
                                        PIT=_game("GB", SUN, "20:20")))
    reason = _row(report, "Zay Doubt")["reason"]
    assert reason == ("George Even plays after Zay Doubt's status is known, so you "
                      "can wait for the news and still switch.")
    item = next(i for i in report["checklist"] if "George Even" in i["action"])
    assert item["detail"].endswith(reason)
    assert all("_starter" not in i for i in report["checklist"])


def test_a_quiet_week_says_nobody_was_questionable_in_plain_words() -> None:
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Wes Slotman", "WR", "KC")}
    report = _report(roster)
    assert report["pivots"] == []
    assert report["pivots_note"] == (
        "No pivots this week — none of your starters was questionable last week, "
        "and no bench player's news would change your lineup.")


def test_the_plan_says_why_a_higher_bench_player_is_skipped() -> None:
    """SS-I8: "Move Sam LaPorta into FLEX (projects 9.5)" while Chase Brown
    (10.3) sat on the bench read as a bug — Brown played Thursday, and the
    plan never said so. The bench row carries his kickoff too."""
    report = _flowers()
    [plan] = _plans(report, "Zay Questionable")
    assert re.search(r"\. Rashid Thursday \(\d+\.\d\) plays Thursday, before Zay "
                     r"Questionable's status is known\.$", plan["action"]), plan["action"]
    assert _bench(report, "Rashid Thursday")["game"] == "@ DEN · Thu 8:15 PM ET"


# --------------------------------------------------------------------- #
# SS-D1 — the practice squad is not "confirmed to play"
# --------------------------------------------------------------------- #

def _squad(**kwargs) -> dict:
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Travis Starter", "TE", "KC"),
              WR2: ("Wes Slotman", "WR", "KC"), TE2: ("Zach Squad", "TE", "PHI"),
              WR3: ("Will Deepman", "WR", "KC")}
    return _report(roster, yards={TE1: 80, TE2: 30, WR3: 40}, **kwargs)


def test_odds_against_a_practice_squad_player_are_withheld_not_moved() -> None:
    """The reproduction: site/this-week.html printed "Travis Kelce … over Zach
    Ertz on your bench … 80%" with Ertz on the Eagles' practice squad (DEV,
    "PS; Vet"). Unelevated he scores 0.0 and the ledger grades the call a HIT.
    The live week withholds that one number and adds none (method §15 C9)."""
    before = _squad()
    after = _squad(unconfirmed={TE2: "on the practice squad"})
    te = _row(after, "Travis Starter")
    assert _row(before, "Travis Starter")["confidence"] is not None
    assert te["confidence"] is None and te["player_name"] == "Travis Starter"
    assert te["confidence_gate"] == ("not confirmed to play (Zach Squad: on the "
                                     "practice squad)")
    assert row_label(te) == "Zach Squad on practice squad"
    assert _published(after) < _published(before), "only the practice-squad pair goes"
    assert _bench(after, "Zach Squad")["note"] == ("on the practice squad — not "
                                                  "confirmed to play")
    for name, page in _surfaces(after).items():
        assert "on the practice squad" in page, name


def test_a_placed_player_not_with_his_team_comes_off_without_adding_odds() -> None:
    """NWT (not with his team) was in no table: a placed player the gate read
    ACTIVE kept his seat. In the report layer he comes off like a released
    player, and keep_frozen_odds holds anything the frozen gate never made."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Wade Gone", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Wes Slotman", "WR", "KC"), WR3: ("Will Deepman", "WR", "KC")}
    kwargs = dict(yards={WR1: 90, WR2: 70, WR3: 40})
    before = _report(roster, **kwargs)
    after = _report(roster, live_out={WR1: "not with his team"}, **kwargs)
    assert all(s["player_name"] != "Wade Gone" for s in after["lineup"])
    assert _published(after) <= _published(before)
    assert _bench(after, "Wade Gone")["out_text"] == "not with his team"


def test_an_ungraded_lineup_shape_prints_projections_and_no_odds() -> None:
    """Contract C8: the picker may offer lineup shapes beyond the three the
    setups method graded, and the ref carries any slot list — a three-receiver
    roster would have printed odds nothing had checked. An ungraded shape
    keeps every seat and projection and prints no odds, with the reason."""
    from run.solo import (GRADED_SHAPES, MEASURED_TEMPLATE, NO_K_OR_DEF_TEMPLATE,
                          SUPERFLEX_TEMPLATE, shape_graded)
    from engine.nflverse_backtest import TEMPLATE_T1
    from engine.setups_backtest import TEMPLATE_NKD, TEMPLATE_SF
    # The graded shapes are the arms' own templates, whatever order a ref lists.
    assert (MEASURED_TEMPLATE, SUPERFLEX_TEMPLATE, NO_K_OR_DEF_TEMPLATE) == (
        TEMPLATE_T1, TEMPLATE_SF, TEMPLATE_NKD)
    assert len(GRADED_SHAPES) == 2, "standard and no K or DEF share an offense"
    assert all(shape_graded(t) for t in (TEMPLATE_T1, TEMPLATE_SF, TEMPLATE_NKD))
    assert shape_graded(tuple(reversed(TEMPLATE_SF)))
    # A kicker or a defense slot stands alone, so one without the other
    # changes no other slot's call; a second of either is a different shape.
    assert shape_graded(TEMPLATE_NKD + ("DEF",)) and shape_graded(TEMPLATE_NKD + ("K",))
    assert not shape_graded(TEMPLATE_T1 + ("K",))
    assert not shape_graded(TEMPLATE_T1 + ("WR",))
    assert not shape_graded(("QB", "RB", "WR", "WR", "WR", "TE", "FLEX", "K", "DEF"))
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Wes Slotman", "WR", "KC"), WR3: ("Will Deepman", "WR", "KC")}
    kwargs = dict(yards={WR1: 90, WR2: 80, WR3: 40})
    graded = _report(roster, **kwargs)
    report = _report(roster, shape_graded=False, **kwargs)
    assert _published(graded) and not _published(report)
    assert [s["projected"] for s in report["lineup"]] == \
        [s["projected"] for s in graded["lineup"]]
    wr = _row(report, "Wade Wideout")
    assert wr["confidence_gate"] == "odds once this lineup shape is graded"
    assert row_label(wr) == "projection only"
    assert report["regret"]["gate"] == "No call with odds this week."
    assert report["regret"]["closest"].endswith(
        "because odds start once this lineup shape is graded.")
    for name, page in _surfaces(report).items():
        assert "projection only" in page, name
        assert "your lineup shape hasn't been graded yet, so it carries no odds" in page, name
        assert not re.search(r"\b\d{2}% vs\b", page), name


def test_hold_unconfirmed_only_ever_removes() -> None:
    def pick(pid, alt, conf):
        return SlotPick("TE", 0, pid, None, None, conf, None, alt, None,
                        [{"kind": "seeded", "text": "x"}])
    players = player_index(PlayerDirectory([Player("b", "Bo Squad", "TE", "PHI")]))
    [held] = hold_unconfirmed([pick("a", "b", 0.8)], {"b": "on the practice squad"},
                              players)
    assert held.confidence is None
    assert held.confidence_gate == "not confirmed to play (Bo Squad: on the practice squad)"
    assert not any(f["kind"] == "seeded" for f in held.flags), \
        "the seeded disclosure travels with a number, and the number is gone"
    [kept] = hold_unconfirmed([pick("a", "c", 0.8)], {"b": "on the practice squad"},
                              players)
    assert kept.confidence == 0.8
    [starter] = hold_unconfirmed([pick("b", "c", None)], {"b": "on the practice squad"},
                                 players)
    assert starter.confidence is None
    assert starter.flags[-1] == {"kind": "unconfirmed",
                                 "text": "on the practice squad — not confirmed to play"}


# --------------------------------------------------------------------- #
# SS-D2 / RQ-06 / SS-I12 — the closest call says what it is
# --------------------------------------------------------------------- #

def test_the_closest_call_names_a_closer_decision_that_has_no_odds() -> None:
    """The reproduction: the published sample's section 04 read "Start Bijan
    Robinson over Chase Brown 70%" as "the week's closest call", while two
    rows up Tony Pollard was dead even with the same Chase Brown (10.3 each),
    with no odds because Pollard was questionable. The card now says it is the
    closest call WITH ODDS and names the closer one, and why it has none."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              RB2: ("Remy Even", "RB", "KC"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC"), RB3: ("Bo Bench", "RB", "KC"),
              WR2: ("Wes Slotman", "WR", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE", "FLEX"),
                     yards={RB1: 120, RB2: 60, RB3: 60, WR1: 90, WR2: 40, TE1: 50},
                     designations={RB2: "Questionable"},
                     listed={RB2: ("questionable", "foot")})
    regret = report["regret"]
    assert regret["label"] == "Closest call with odds"
    assert regret["closer"].startswith("Closer on points: Remy Even or Bo Bench at FLEX")
    assert regret["closer"].endswith("— no odds, because Remy Even was questionable "
                                     "in Week 4.")
    assert re.fullmatch(r"\S.* projects \d+\.\d to .*'s \d+\.\d\. Last three: .*\.",
                        regret["reason"]), regret["reason"]
    pages = _surfaces(report)
    for name, page in pages.items():
        assert "Closer on points: Remy Even or Bo Bench" in page, name
        assert "closest call with odds" in page.lower(), name


def test_a_closer_decision_is_closer_at_the_precision_the_page_prints() -> None:
    """r03 (2026 week 6): the card read "Drake London over George Pickens …
    9.6 vs 9.6" and then "Closer on points: Zay Flowers or George Pickens at
    WR, 9.6 vs 9.6" — the call's gap was compared unrounded (0.06 → 0.1)
    against the other's printed 0.0, so an equal gap was called closer."""
    from engine.solo_report import closest_call

    def proj(pid, mean):
        return Projection(player_id=pid, as_of_week=6, active_mean=mean, active_sd=4.0,
                          appear_probability=1.0, games=5, rostered_weeks=5,
                          position="WR")

    class Model:
        def observations(self, pid, week):
            return []

    players = player_index(PlayerDirectory([Player("a", "Drake Even", "WR", "KC"),
                                            Player("q", "Zay Doubt", "WR", "BAL"),
                                            Player("p", "George Bench", "WR", "SF")]))
    ok = PlayerStatus(Status.ACTIVE, "no injury designation", "w5")
    call = SlotPick("WR", 3, "a", proj("a", 9.64), ok, 0.5, None, "p",
                    proj("p", 9.58), [])
    doubt = SlotPick("WR", 4, "q", proj("q", 9.61),
                     PlayerStatus(Status.QUESTIONABLE, "designated Questionable", "w5"),
                     None, "availability in doubt (designated Questionable)", "p",
                     proj("p", 9.58), [])
    availability = WeekAvailability("2026", 6, "w5", {}, frozenset())
    regret = closest_call([call, doubt], players, Model(), 6, availability,
                          {"week": 5, "listed": {}})
    assert regret["start_name"] == "Drake Even"
    assert "closer" not in regret, regret.get("closer")
    doubt.projection = proj("q", 9.75)      # prints 9.8 vs 9.6: wider, still not closer
    assert "closer" not in closest_call([call, doubt], players, Model(), 6,
                                        availability, {"week": 5, "listed": {}})
    call.projection = proj("a", 10.4)       # prints 10.4 vs 9.6: now the other is closer
    assert closest_call([call, doubt], players, Model(), 6, availability,
                        {"week": 5, "listed": {}})["closer"].startswith(
        "Closer on points: Zay Doubt or George Bench at WR")


def test_with_no_odds_the_section_names_the_closest_decision_and_who() -> None:
    """RQ-06: "no coin-flip call this week — not enough games on record yet (2
    and 5; we want at least 3)" named nobody, and "availability in doubt
    (designated Questionable)" was last week's report in the present tense."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              RB2: ("Rookie Twogames", "RB", "KC"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"),
                     yards={RB1: 90, RB2: 85}, missed={RB2: {1, 2}})
    regret = report["regret"]
    assert regret["gate"] == "No call with odds this week."
    assert regret["closest"].startswith("Closest decision: Rory Runner over Rookie "
                                        "Twogames at RB, ")
    assert regret["closest"].endswith("— no odds, because Rookie Twogames has played "
                                      "2 games this season, and odds start at 3.")
    assert "we want at least" not in str(regret)


def test_with_no_odds_the_section_is_one_plain_line() -> None:
    """RQ-19: with no call anywhere the closest-call section still took a
    whole section with a "Heads up" box, then the closest decision under it.
    It is one plain line now, the same line on all three surfaces."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              RB2: ("Rookie Twogames", "RB", "KC"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"),
                     yards={RB1: 90, RB2: 85}, missed={RB2: {1, 2}})
    line = f"{report['regret']['gate']} {report['regret']['closest']}"
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    browser = render(report, template)
    section = browser[browser.index("The Week&#x27;s Closest Call"):]
    section = section[:section.index("</section>")]
    assert 'class="withheld"' not in section and "Heads up" not in section
    assert section.count("<p") == 1
    email = render_email(report)
    section = email[email.index("The Week&#x27;s Closest Call"):]
    section = section[:section.index("If/Then for Gameday")]
    assert "Heads up" not in section and section.count("<p ") == 1
    for name, page in _surfaces(report).items():
        assert line in page, name
    assert f"THE WEEK'S CLOSEST CALL: {line}" in text_summary(report)


def test_a_no_bench_gate_names_the_bench_player_it_means() -> None:
    """F11's rule, in the closest-call line too: a week with no odds read "No
    call with odds this week — nobody on your bench can play QB" above Lamar
    Jackson's bench row ("Ruled out for Week 5"). It names him; and when the
    slots have different reasons, none is passed off as the only one."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), QB2: ("Lamar Backup", "QB", "KC"),
              RB1: ("Rory Runner", "RB", "KC")}
    out = dict(designations={QB2: "Out"}, listed={QB2: ("out", "ankle")})
    one = _report(roster, slots=("QB",), **out)["regret"]
    assert one["gate"] == ("No call with odds this week — Lamar Backup, your bench "
                           "QB, isn't cleared to play yet.")
    two = _report(roster, slots=("QB", "RB"), **out)["regret"]
    assert two["gate"] == ("No call with odds this week — no starter has a bench "
                           "player we can compare him with.")
    assert "nobody on your bench can play QB" not in str(two)


def test_a_callout_under_its_label_starts_like_a_sentence() -> None:
    """D10: the week-1 sample printed "Heads up" over "no projected totals yet…",
    "no coin-flip call this week…", "no pivots this week…"."""
    assert '</span>No projected totals yet' in gate_note("no projected totals yet")


# --------------------------------------------------------------------- #
# the rows: BE-D3, SS-D5, BE-I1, BE-I9/SS-I7, RQ-14, RQ-15, I16, F8
# --------------------------------------------------------------------- #

def test_the_bench_player_a_row_waits_on_has_his_designation_printed() -> None:
    """BE-D3: Jonathan Taylor's row read "start · waiting on Rhamondre
    Stevenson", and Stevenson's Week-5 Questionable (knee) printed nowhere —
    bench rows only carried Outs. RQ-18: "waiting on" a backup who projects
    far below the starter implied the start depended on him."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Jon Starter", "RB", "KC"),
              RB2: ("Rhett Bench", "RB", "KC"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"), yards={RB1: 120, RB2: 60},
                     designations={RB2: "Questionable"},
                     listed={RB2: ("questionable", "knee")})
    row = _row(report, "Jon Starter")
    assert row_label(row) == "start · Rhett Bench was questionable"
    note = _bench(report, "Rhett Bench")["note"]
    assert note == "Questionable in Week 4 (knee) — played, 6.0"
    for name, page in _surfaces(report).items():
        assert "waiting on" not in page, name
        assert "Questionable in Week 4 (knee) — played, 6.0" in page, name


def test_no_edge_is_quoted_over_a_bench_player_shown_without_a_projection() -> None:
    """SS-D5: "Quinshon Judkins … +6.0 over Devin Neal" while Neal's bench row
    read "—" (no games this season): an edge over a number the report hides."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              RB2: ("Devin Nogames", "RB", "KC"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"),
                     missed={RB2: {1, 2, 3, 4}})
    row = _row(report, "Rory Runner")
    assert row["alternative_name"] == "Devin Nogames"
    assert row["edge"] is None and row["alternative_projected"] is None
    assert _bench(report, "Devin Nogames")["projected"] is None
    for name, page in _surfaces(report).items():
        assert "over Devin Nogames" not in page, name


def test_a_questionable_starter_level_with_a_healthy_one_says_why_he_starts() -> None:
    """BE-I9/SS-I7: the published sample started a questionable Tony Pollard at
    FLEX "even with Chase Brown" (10.3 each) and gave no reason. The facts do:
    Brown played Thursday, before Pollard's news, so starting Pollard kept a
    later fallback. A fact and its consequence — the seat rule is unchanged."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              RB2: ("Tony Even", "RB", "LV"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC"), RB3: ("Chase Thursday", "RB", "SEA"),
              TE2: ("Sam Sunday", "TE", "NYJ")}
    report = _report(roster, yards={RB1: 120, RB2: 60, RB3: 60, TE1: 70, TE2: 55},
                     designations={RB2: "Questionable"},
                     listed={RB2: ("questionable", "foot")},
                     schedule=_schedule(SEA=_game("DEN", THU, "20:15"),
                                        LV=_game("KC", SUN, "16:05"),
                                        NYJ=_game("HOU", SUN, "20:20")))
    flex = _row(report, "Tony Even")
    assert flex["alternative_name"] == "Chase Thursday" and flex["edge"] == 0.0
    assert flex["reason"] == ("Chase Thursday plays Thursday, before Tony Even's "
                              "status is known; starting Tony Even keeps Sam Sunday "
                              "as a fallback if he sits.")
    for name, page in _surfaces(report).items():
        assert flex["reason"] in page, name


def test_a_dead_even_pair_is_a_toss_up_not_an_instruction() -> None:
    """RQ-14: r03's game plan opened "Start Drake London over George Pickens at
    WR · 50% … Projects 9.6, Drake London 9.6" — a coin flip on the action
    list. The percentage still prints on the row (it is the published number)
    and the row says either is fine; the game plan, a list of things to do,
    no longer carries it."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Drew Level", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Gus Level", "WR", "SF")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"), yards={WR1: 70, WR2: 70},
                     ranks={WR2: ("WR", 6, 120)})
    row = _row(report, "Drew Level") if any(
        s["player_name"] == "Drew Level" for s in report["lineup"]) else _row(report, "Gus Level")
    assert row["confidence"] is not None and row["tossup"] is True
    benched = ({"Drew Level", "Gus Level"} - {row["player_name"]}).pop()
    assert not any(benched in i["action"] for i in report["checklist"]), \
        report["checklist"]
    for name, page in _surfaces(report).items():
        assert "toss-up: either is fine" in page, name
    # The points arm on its own: a pair with no odds (RQ-15's defenses, 6.3 vs
    # 6.2) is a toss-up under half a point, and is not one at 0.8 — nor ever
    # when one of the two may not play.
    from engine.solo_report import _even_pair
    availability = WeekAvailability("2026", 5, "w4", {
        "DEF-DEN": {"team": "DEN", "position": "DEF", "active": True},
        "DEF-JAX": {"team": "JAX", "position": "DEF", "active": True},
        "q": {"team": "JAX", "position": "RB", "active": True,
              "injury_status": "Questionable"}}, frozenset())

    def defense(mean):
        return Projection(player_id="DEF-DEN", as_of_week=5, active_mean=mean,
                          active_sd=4.0, appear_probability=1.0, games=5,
                          rostered_weeks=5, position="DEF")
    ok = PlayerStatus(Status.ACTIVE, "team defense", "w4")
    pick = SlotPick("DEF", 8, "DEF-DEN", defense(6.3), ok, None, "x", "DEF-JAX",
                    None, [])
    assert _even_pair(pick, "DEF-JAX", 6.2, availability)
    pick.projection = defense(7.0)
    assert not _even_pair(pick, "DEF-JAX", 6.2, availability)
    pick.projection = defense(6.3)
    assert not _even_pair(pick, "q", 6.2, availability)


def test_a_swap_worth_under_half_a_point_is_not_a_watch_line() -> None:
    """RQ-14: "Watch Zach Charbonnet: if he's cleared, start him at RB over
    Rachaad White … 6.5 vs 6.4" — a Sunday chore worth a tenth of a point."""
    from engine.solo_report import cleared_plans

    def proj(pid, mean):
        return Projection(player_id=pid, as_of_week=6, active_mean=mean, active_sd=4.0,
                          appear_probability=1.0, games=5, rostered_weeks=5,
                          position="RB")
    players = player_index(PlayerDirectory([Player("s", "Rach Starter", "RB", "KC"),
                                            Player("b", "Zach Bench", "RB", "SEA")]))
    pick = SlotPick("RB", 0, "s", proj("s", 6.4),
                    PlayerStatus(Status.ACTIVE, "no injury designation", "w5"),
                    None, None, None, None, [])
    entry = {"out_kind": "designation", "projected": 6.5, "position": "RB",
             "player_id": "b", "name": "Zach Bench", "out_text": "Ruled out"}
    games = {"s": _game("X", SUN), "b": _game("Y", SUN)}
    assert cleared_plans([entry], [pick], players, games.get,
                         date.fromisoformat(SUN)) == ([], [])
    entry["projected"] = 6.9
    items, plans = cleared_plans([entry], [pick], players, games.get,
                                 date.fromisoformat(SUN))
    assert len(items) == 1 and len(plans) == 1


def test_a_defense_row_always_says_projection_only() -> None:
    """RQ-15: defense projections graded with no skill, yet "Denver Broncos 6.3"
    over Jacksonville 6.2 read as decided. The row says it is a projection
    alone in every week, and a close pair is a toss-up."""
    from engine.week_report import DEFENSE_GATE
    from render.report import row_marked
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC")}
    report = _report(roster, slots=("QB", "RB"))
    assert not any(s.get("confidence") is not None for s in report["lineup"])
    row = report["lineup"][1]
    row.update(confidence_gate=DEFENSE_GATE, slot="DEF")
    assert row_label(row) == "projection only"
    assert row_marked(row, mixed=False), "a week with no odds anywhere still says it"
    for name, page in _surfaces(report).items():
        assert "projection only" in page, name
    # And the close pair reads as the toss-up it is.
    from render.report import call_bits
    assert "toss-up: either is fine" in call_bits(
        {"edge": 0.1, "alternative_name": "Jacksonville Jaguars", "tossup": True})


def test_the_only_quarterback_says_so_in_a_week_with_odds() -> None:
    """I16: in a mixed week the QB and K rows showed an EMPTY call cell beside
    rows reading 70% — a value we forgot, to a reader. "no bench QB" is what
    it is."""
    roster = {QB1: ("Quinn Only", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Wes Slotman", "WR", "KC"), WR3: ("Will Deepman", "WR", "KC")}
    report = _report(roster, yards={WR1: 90, WR2: 80, WR3: 40})
    assert any(s.get("confidence") is not None for s in report["lineup"])
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    page = render(report, template)
    qb = re.search(r'<td class="tslot">QB</td>.*?<td class="tcall">(.*?)</td>', page, re.S)
    assert "no bench QB" in qb.group(1)
    assert "QB     Quinn Only" in text_summary(report) and "no bench QB" in text_summary(report)


def test_a_starter_row_carries_his_season_and_last_three() -> None:
    """F8 + SS-I9: Kenneth Walker III projected 15.3 beside no sign of a 27.5
    start, and starter rows never printed the last three games the bench rows
    did. Facts under the subscriber's scoring; the projection is unchanged."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Hot Start", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              RB2: ("Ray Backup", "RB", "KC"), RB3: ("Ron Backup", "RB", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"),
                     yards={RB1: 300, RB2: 20, RB3: 20})
    row = _row(report, "Hot Start")
    assert row["season_per_game"] == 30.0 and row["last_three"] == [30.0, 30.0, 30.0]
    assert row["projected"] < row["season_per_game"] - 3
    for name, page in _surfaces(report).items():
        assert "2026: 30.0 a game · last 3: 30.0, 30.0, 30.0" in page, name
        assert PROJECTION_NOTE in page, name


def test_the_emailed_record_and_usage_are_separate_lines() -> None:
    """The live sample's email at 390px: "2026: 20.4 a game · last 3: 15.4,
    25.8, 14.6 · last 3: 8.3 targets · 0.7 carries a game" — two "last 3"s on
    one line, the first his points and the second a usage window."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Hot Start", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"), yards={RB1: 300})
    row = _row(report, "Hot Start")
    row["usage"] = "last 3 games: 25 targets (8.3 a game), 2 carries"
    email = render_email(report)
    assert "30.0, 30.0, 30.0 · last 3: 8.3 targets" not in email
    assert "30.0, 30.0, 30.0<br>last 3: 8.3 targets" in email


def test_the_fallback_says_whom_it_skipped() -> None:
    """BE-I1: "Start Drake London over Courtland Sutton at FLEX · 71%" while
    Rhamondre Stevenson (11.3), questionable, sat higher on the bench — read
    as the model ranking Sutton second."""
    from engine.solo_report import fallback_sentence

    def proj(pid, mean):
        return Projection(player_id=pid, as_of_week=6, active_mean=mean, active_sd=4.0,
                          appear_probability=1.0, games=5, rostered_weeks=5,
                          position="WR")

    class Model:
        def project(self, pid, week):
            return proj(pid, 11.3)

    players = player_index(PlayerDirectory([Player("st", "Rhett Doubt", "RB", "NE")]))
    pick = SlotPick("FLEX", 0, "a", proj("a", 14.0), None, 0.71, None, "su",
                    proj("su", 8.2), [], "st", proj("st", 11.3))
    availability = WeekAvailability("2026", 6, "w5", {"st": {
        "team": "NE", "position": "RB", "active": True,
        "injury_status": "Questionable"}}, frozenset())
    assert fallback_sentence(pick, "Cort Sutton", players, Model(), 6, availability) == (
        " Rhett Doubt (11.3) was questionable last week, so these odds are against "
        "Cort Sutton, your next healthy option.")
    # The fallback skips anyone not confirmed — not always a designation.
    unknown = WeekAvailability("2026", 6, "w5", {}, frozenset())
    assert "isn't confirmed to play yet" in fallback_sentence(
        pick, "Cort Sutton", players, Model(), 6, unknown)
    from render.report import call_bits
    assert "Rhett Doubt (11.3) was questionable, so the odds are against Cort " \
           "Sutton" in call_bits({"edge": 5.8, "alternative_name": "Cort Sutton",
                                  "doubtful_alternative_name": "Rhett Doubt",
                                  "doubtful_alternative_projected": 11.3})


# --------------------------------------------------------------------- #
# the game plan: RQ-04, RQ-16, RQ-18
# --------------------------------------------------------------------- #

def test_injured_reserve_is_named_before_a_bye() -> None:
    """RQ-04: De'Von Achane, on injured reserve with Miami on bye, read only
    "MIA on bye this week" — which says he is back next week."""
    from engine.solo_report import absence
    availability = WeekAvailability(
        "2026", 6, "w5", {RB1: {"team": "MIA", "position": "RB", "active": False,
                                "out_reason": "on injured reserve"}},
        frozenset({"MIA"}))
    assert absence(RB1, availability)["row"] == "on injured reserve"
    assert availability.classify(RB1).status is Status.OUT


def test_byes_and_reserve_lists_are_one_game_plan_line() -> None:
    """RQ-18: three separate "Bench X — he can't play this week" items opened
    the live sample's game plan, each restating what "Set this lineup" excludes."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Byron Bye", "WR", "DET"), RB2: ("Ira Reserve", "RB", "MIA")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"), byes=frozenset({"DET"}),
                     reserve={RB2: "on injured reserve"},
                     ranks={WR2: ("WR", 4, 120), RB2: ("RB", 5, 90)},
                     yards={WR2: 90, RB2: 90})
    gone = [i for i in report["checklist"] if "can't play" in i["action"]]
    assert [i["action"] for i in gone] == [
        "Bench Byron Bye and Ira Reserve — they can't play this week"]
    assert gone[0]["detail"] == ("Byron Bye: WR4 last season. DET is on bye this week. "
                                 "Ira Reserve: RB5 last season. He's on injured reserve.")


def test_a_superflex_without_a_quarterback_says_so_with_last_seasons_record() -> None:
    """RQ-16: one quarterback on a superflex roster, a receiver in the SFLEX,
    and the report said nothing — the first thing an expert flags."""
    from engine.solo_report import superflex_items
    players = player_index(PlayerDirectory([Player("w", "Emmy Receiver", "WR", "TB")]))
    pick = SlotPick("SUPER_FLEX", 7, "w", None, None, None, None, None, None, [])
    ranks = {f"q{i}": ("QB", i, 30) for i in range(1, 31)}
    ranks |= {f"r{i}": ("WR", i, 90) for i in range(1, 91)}
    form = {f"q{i}": 25.0 - i * 0.5 for i in range(1, 31)}
    form |= {f"r{i}": 20.0 - i * 0.4 for i in range(1, 91)}
    [item] = superflex_items([pick], players, form, ranks, 12)
    assert item["action"] == ("Your SUPER_FLEX has no quarterback this week — Emmy "
                              "Receiver (WR) starts there")
    assert item["detail"] == ("Last season, under your scoring, the 24th-best "
                              "quarterback averaged 13.0 a game and the 24th-best wide "
                              "receiver 10.4. A second quarterback off your waiver "
                              "wire may be worth a look.")
    # The waiver line only when the record favours the quarterback.
    form |= {f"r{i}": 30.0 for i in range(1, 91)}
    [item] = superflex_items([pick], players, form, ranks, 12)
    assert "waiver" not in item["detail"]
    pick.player_id = None
    assert superflex_items([pick], players, form, ranks, 12) == []


# --------------------------------------------------------------------- #
# the text and the email: RQ-07, RQ-08, D7, D10
# --------------------------------------------------------------------- #

def test_a_quarterbacks_usage_is_his_passing_volume() -> None:
    """RQ-07: "Josh Allen … last 4 games: 1 target (0.2 a game), 37 carries" —
    a trick-play catch reported as his role, the throws missing."""
    usage = Usage(weeks=4, targets=1, air_yards=None, rz_targets=None, snaps=None,
                  carries=37, pass_attempts=142)
    assert usage_line(usage, "QB") == ("last 4 games: 142 pass attempts (35.5 a game), "
                                       "37 carries")
    assert usage_line(usage, "WR") == "last 4 games: 1 target (0.2 a game), 37 carries"
    assert short_usage(usage_line(usage, "QB")) == ("last 4: 35.5 pass attempts · "
                                                   "9.2 carries a game")


def test_mid_season_an_out_starters_usage_is_not_printed_as_his_call() -> None:
    """r10 (2026 week 6), plain text: "RB  De'Von Achane  —  last 2 games: 7
    targets (3.5 a game), 23 carries" — the week-1 rule (a row with no
    projection shows its basis in the call column) fired on a starter on
    injured reserve, so his usage sat where a call goes, above "OUT"."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Ira Reserve", "RB", "MIA"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE"),
                     reserve={RB1: "on injured reserve"})
    row = _row(report, "Ira Reserve")
    assert row["projected"] is None and not report["meta"]["lineup_as_set"]
    row["usage"] = "last 2 games: 7 targets (3.5 a game), 23 carries"
    def line() -> str:
        [row_line] = [x for x in text_summary(report).splitlines()
                      if x.startswith("  RB ") and "Ira Reserve" in x]
        return row_line
    assert "targets" not in line(), line()
    report["meta"]["lineup_as_set"] = True          # week 1: the basis prints
    assert line().endswith("23 carries")


def test_the_superflex_row_lines_up_in_plain_text() -> None:
    """RQ-08: "  SFLEX Dak Prescott" against "  FLEX   Javonte Williams" — the
    slot overran its column as SUPER_FLEX and was shortened afterwards."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), QB2: ("Dak Second", "QB", "KC"),
              RB1: ("Rory Runner", "RB", "KC"), WR1: ("Wade Wideout", "WR", "KC"),
              TE1: ("Tate Tightend", "TE", "KC"), WR2: ("Wes Slotman", "WR", "KC")}
    report = _report(roster, slots=("QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"))
    lines = [line for line in text_summary(report).splitlines()
             if line.startswith(("  FLEX ", "  SFLEX"))]
    assert len(lines) == 2, lines
    assert lines[0].index(lines[0].split()[1]) == lines[1].index(lines[1].split()[1])


def test_the_emailed_odds_span_the_name_and_its_details() -> None:
    """D7: in the email the call cell (the % and its bar) sat in the name row
    only, so that row grew and opened a gap between a player's name and his
    kickoff on exactly the rows that carry odds."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC"),
              WR1: ("Wade Wideout", "WR", "KC"), TE1: ("Tate Tightend", "TE", "KC"),
              WR2: ("Wes Slotman", "WR", "KC"), WR3: ("Will Deepman", "WR", "KC")}
    report = _report(roster, yards={WR1: 90, WR2: 80, WR3: 40})
    email = render_email(report)
    calls = re.findall(r'<td width="60"([^>]*)>(.*?)</td>', email, re.S)
    with_odds = [attrs for attrs, body in calls if re.search(r"\d+%", body)]
    assert with_odds and all('rowspan="2"' in attrs for attrs in with_odds)


def test_every_call_below_is_said_only_in_a_week_with_calls() -> None:
    """D10: the week-1 sample said "Every call below is your starter against
    your own bench." above fifteen empty call cells."""
    roster = {QB1: ("Quinn Starter", "QB", "KC"), RB1: ("Rory Runner", "RB", "KC")}
    quiet = _report(roster, slots=("QB", "RB"))
    assert quiet["no_opponent"] is None
    roster |= {WR1: ("Wade Wideout", "WR", "KC"), WR2: ("Wes Slotman", "WR", "KC")}
    busy = _report(roster, slots=("QB", "RB", "WR"), yards={WR1: 90, WR2: 40})
    assert busy["no_opponent"] == "Every call below is your starter against your own bench."


# --------------------------------------------------------------------- #
# the live week and the pinned sample, through the real pipeline
# --------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def sample10():
    import render.sample as sample
    try:
        return sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")


def test_the_sample_names_its_closer_call_and_why_pollard_starts(sample10) -> None:
    """The published 2024 week-10 sample: Robinson over Brown at 70% stays the
    closest call WITH ODDS (the ledger records it, the landing quotes it), and
    the FLEX row's dead heat is named with its reason."""
    regret = sample10["regret"]
    assert (regret["start_name"], regret["over_name"]) == ("Bijan Robinson", "Chase Brown")
    assert regret["closer"] == ("Closer on points: Tony Pollard or Chase Brown at FLEX, "
                                "10.3 vs 10.3 — no odds, because Tony Pollard was "
                                "questionable in Week 9.")
    pollard = next(s for s in sample10["lineup"] if s["player_name"] == "Tony Pollard")
    assert pollard["reason"] == ("Chase Brown plays Thursday, before Tony Pollard's "
                                 "status is known; starting Tony Pollard keeps Sam "
                                 "LaPorta as a fallback if he sits.")
    allen = next(s for s in sample10["lineup"] if s["player_name"] == "Josh Allen")
    assert allen["usage"].startswith("last 4 games: ") and "pass attempts" in allen["usage"]
