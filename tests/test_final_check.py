"""The Saturday final check: Friday's injury report against Tuesday's lineup.

A report that goes out on Tuesday is built on last week's injury report, so by
Sunday it can be telling somebody to start a player who was ruled out on
Friday. The check fixes that without publishing anything new — and every rule
here is a way it could have been confidently wrong: moving a player whose game
already started, calling a Monday-night player "cleared" before his team has
filed, reading a missing report as a healthy league, or mailing everybody every
Saturday until nobody opens it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.saturday as saturday
from engine.final_check import (BACK, CLEARED, NO_FILL, REMINDER, SWAP, WATCH,
                                Now, final_check, worth_sending)
from render.final_check import (render_final_check, subject_for_check,
                                text_for_check)

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]


def _plan(**players) -> dict:
    """players: id -> (position, projected, tuesday status, starting slot|None)."""
    slots = [{"slot": s, "player_id": None} for s in SLOTS]
    table = {}
    for pid, (pos, proj, tuesday, slot_index) in players.items():
        table[pid] = {"name": pid.title(), "position": pos, "projected": proj,
                      "last_season": None, "tuesday": tuesday}
        if slot_index is not None:
            slots[slot_index]["player_id"] = pid
    return {"season": "2024", "week": 10, "slug": "abc", "slots": slots,
            "players": table}


def _roster(**extra) -> dict:
    base = dict(
        qb=("QB", 20.0, "active", 0), rb1=("RB", 15.0, "active", 1),
        rb2=("RB", 12.0, "active", 2), wr1=("WR", 14.0, "active", 3),
        wr2=("WR", 11.0, "active", 4), te=("TE", 9.0, "active", 5),
        flex=("RB", 10.0, "active", 6), benchrb=("RB", 8.0, "active", None),
        benchwr=("WR", 9.5, "active", None), benchte=("TE", 5.0, "active", None))
    base.update(extra)
    return _plan(**base)


def _now(plan, **states) -> dict:
    return {pid: states.get(pid, Now()) for pid in plan["players"]}


OUT = Now("out", "listed out (ankle)")


def test_a_starter_ruled_out_is_replaced_by_the_best_bench_option() -> None:
    plan = _roster()
    changes = final_check(plan, _now(plan, rb1=OUT))
    swaps = [c for c in changes if c.kind == SWAP]
    assert len(swaps) == 1
    # The bench WR projects higher than the bench RB, so the flex RB slides
    # across to RB and the WR takes the flex — the higher-projected fill.
    assert swaps[0].action == "Move Flex to RB and start Benchwr at FLEX"
    assert "Rb1 is listed out (ankle)" in swaps[0].detail
    assert "projects 9.5" in swaps[0].detail
    assert worth_sending(changes)


def test_a_straight_swap_when_nothing_better_comes_from_sliding() -> None:
    plan = _roster(benchrb=("RB", 13.0, "active", None))
    swaps = [c for c in final_check(plan, _now(plan, rb1=OUT)) if c.kind == SWAP]
    assert swaps[0].action == "Start Benchrb at RB"


def test_doubtful_counts_as_out_and_says_so_in_its_own_word() -> None:
    plan = _roster()
    doubtful = Now("doubtful", "listed doubtful (hamstring)")
    swaps = [c for c in final_check(plan, _now(plan, te=doubtful)) if c.kind == SWAP]
    assert swaps and swaps[0].action == "Start Benchte at TE"
    assert "listed doubtful (hamstring)" in swaps[0].detail


def test_rule_f1_a_player_whose_game_has_started_is_never_moved() -> None:
    """Every league app locks a player at kickoff. Telling someone on
    Saturday to bench their Thursday starter is advice they cannot take."""
    plan = _roster()
    locked_out = Now("out", "listed out (ankle)", locked=True)
    assert final_check(plan, _now(plan, rb1=locked_out)) == []
    # ...and a bench player whose game is over is never offered as cover.
    changes = final_check(plan, _now(plan, te=OUT, benchte=Now(locked=True)))
    assert [c.kind for c in changes] == [NO_FILL]


def test_a_bench_player_on_bye_or_ruled_out_is_never_offered() -> None:
    plan = _roster()
    changes = final_check(plan, _now(plan, te=OUT, benchte=Now(playing=False)))
    assert [c.kind for c in changes] == [NO_FILL]
    assert "Nobody on your bench can cover TE" in changes[0].action
    changes = final_check(plan, _now(plan, te=OUT, benchte=OUT))
    assert [c.kind for c in changes] == [NO_FILL]


def test_a_newly_questionable_starter_gets_a_plan_and_an_email() -> None:
    plan = _roster()
    q = Now("questionable", "listed questionable (knee)")
    changes = final_check(plan, _now(plan, wr1=q))
    assert [c.kind for c in changes] == [WATCH]
    assert "If he's ruled out, start Benchwr at WR" in changes[0].detail
    assert worth_sending(changes)


def test_still_questionable_since_tuesday_is_a_reminder_not_a_reason_to_mail() -> None:
    """Tuesday's if/then already covered him. RULE F3: a Saturday email
    that says nothing new trains people to skip the one that does."""
    plan = _roster(wr1=("WR", 14.0, "questionable", 3))
    q = Now("questionable", "listed questionable (knee)")
    changes = final_check(plan, _now(plan, wr1=q))
    assert [c.kind for c in changes] == [REMINDER]
    assert not worth_sending(changes)


def test_nothing_changed_sends_nothing() -> None:
    plan = _roster()
    assert final_check(plan, _now(plan)) == []
    assert not worth_sending([])


def test_rule_f2_cleared_needs_the_final_report() -> None:
    """A Monday-night team files its final report on Saturday; before that,
    "no designation" means "not filed yet", never "healthy"."""
    plan = _roster(wr1=("WR", 14.0, "questionable", 3))
    cleared = final_check(plan, _now(plan, wr1=Now(final=True)))
    assert [c.kind for c in cleared] == [CLEARED]
    assert not worth_sending(cleared)
    assert final_check(plan, _now(plan, wr1=Now(final=False))) == []


def test_a_bench_player_back_from_injury_takes_the_weakest_slot_he_beats() -> None:
    plan = _roster(star=("WR", 16.0, "out", None))
    changes = final_check(plan, _now(plan))
    assert [c.kind for c in changes] == [BACK]
    # He beats both WRs and the flex RB; the weakest of those is the flex.
    assert changes[0].action == "Start Star at FLEX over Flex"
    assert "off the injury report" in changes[0].detail
    # Not before his team's final report is in (RULE F2).
    assert final_check(plan, _now(plan, star=Now(final=False))) == []
    # Not when he is still questionable.
    assert final_check(plan, _now(plan, star=Now("questionable", "q"))) == []


def test_a_player_the_check_knows_nothing_about_is_left_alone() -> None:
    """Missing from the map means unknown, and unknown never acts."""
    plan = _roster(wr1=("WR", 14.0, "questionable", 3))
    now = _now(plan)
    del now["wr1"]
    assert final_check(plan, now) == []


def test_week_one_orders_by_last_season_when_nothing_has_a_projection() -> None:
    plan = _roster()
    for info in plan["players"].values():
        info["last_season"], info["projected"] = info["projected"], None
    swaps = [c for c in final_check(plan, _now(plan, te=OUT)) if c.kind == SWAP]
    assert swaps and "averaged 5.0 a game last season" in swaps[0].detail


def test_the_email_states_no_probability() -> None:
    """Nothing here is graded, so nothing here may look like a call."""
    plan = _roster()
    changes = final_check(plan, _now(plan, rb1=OUT, wr1=Now("questionable", "q")))
    at = datetime(2024, 11, 9, 16, tzinfo=timezone.utc)
    for body in (render_final_check(plan, changes, at),
                 text_for_check(plan, changes, at), subject_for_check(10, changes)):
        assert "%" not in body.replace("width:100%", "").replace('width="100%"', "")
    html = render_final_check(plan, changes, at)
    assert "nflverse" in html and "Cancel" in html            # RULE N1, the way out
    assert "Sat Nov 9, 11:00 AM ET" in html


def test_subject_lines_say_what_to_do() -> None:
    plan = _roster()
    one = final_check(plan, _now(plan, te=OUT))
    assert subject_for_check(10, one) == \
        "Week 10: one change before kickoff — start Benchte at TE"
    two = final_check(plan, _now(plan, te=OUT, wr1=OUT))
    assert subject_for_check(10, two) == "Week 10: 2 changes before kickoff"


# --------------------------------------------------------------------- #
# what "now" means, from the published data
# --------------------------------------------------------------------- #

SAT = datetime(2024, 11, 9, 16, tzinfo=timezone.utc)
SUN_1PM = datetime(2024, 11, 10, 18, tzinfo=timezone.utc)
SUN_NIGHT = datetime(2024, 11, 11, 1, 20, tzinfo=timezone.utc)   # Monday in UTC
MON_NIGHT = datetime(2024, 11, 12, 1, 15, tzinfo=timezone.utc)
THU_NIGHT = datetime(2024, 11, 8, 1, 15, tzinfo=timezone.utc)


def _state(pid="p1", team="DET", kickoff=SUN_1PM, listed=None, filed=None,
           status="ACT"):
    return saturday.state_for(
        pid, starts={team: kickoff} if kickoff else {},
        listed=listed or {}, filed={team} if filed is None else filed,
        roster={pid: (status, team)}, at=SAT)


def test_a_sunday_night_game_is_final_on_saturday_in_nfl_time() -> None:
    """20:20 ET Sunday is Monday in UTC; comparing UTC dates called every
    Sunday-night team's report unfiled (found running 2024 week 10)."""
    assert _state(kickoff=SUN_NIGHT).final
    assert _state(kickoff=SUN_1PM).final
    assert not _state(kickoff=MON_NIGHT).final


def test_a_team_that_filed_nothing_is_not_final() -> None:
    assert not _state(filed=set()).final


def test_thursday_players_are_locked_and_bye_players_are_not_playing() -> None:
    assert _state(kickoff=THU_NIGHT).locked
    assert not _state(kickoff=None).playing


def test_injured_reserve_is_out_even_off_the_injury_report() -> None:
    """A player moved to IR on Thursday stops appearing on the report."""
    state = _state(status="RES")
    assert state.ruled_out and state.reason == "on injured reserve"


def test_the_designation_keeps_its_own_word_and_the_injury() -> None:
    state = _state(listed={"p1": ("doubtful", "hamstring")})
    assert state.designation == "doubtful"
    assert state.reason == "listed doubtful (hamstring)"


def test_a_missing_injury_report_refuses_rather_than_reading_as_healthy() -> None:
    starts = {t: SUN_1PM for t in ("DET", "GB", "CHI", "MIN")}
    with pytest.raises(saturday.SaturdayError, match="isn't in yet"):
        saturday.check_report_is_in(starts, {"DET"}, SAT, 10)
    saturday.check_report_is_in(starts, {"DET", "GB", "CHI", "MIN"}, SAT, 10)
    with pytest.raises(saturday.SaturdayError, match="already kicked off"):
        saturday.check_report_is_in(starts, set(), SUN_1PM + timedelta(days=2), 10)


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def _run(tmp_path, monkeypatch, plan, *, listed=None, extra=()):
    from test_tuesday import _registry, _row
    registry = _registry(tmp_path, _row())
    from run.rosters import load_rosters
    slug = load_rosters(registry)[0].slug
    plans = tmp_path / "plans"
    if plan is not None:
        saturday.write_plan(plans, dict(plan, slug=slug))
    teams = ("DET", "GB", "CHI", "MIN")
    monkeypatch.setattr(saturday, "kickoffs", lambda *a: {t: SUN_1PM for t in teams})
    monkeypatch.setattr(saturday, "designations",
                        lambda *a: (listed or {}, set(teams)))
    monkeypatch.setattr(saturday, "roster_statuses",
                        lambda *a: {pid: ("ACT", "DET")
                                    for pid in (plan or {"players": {}})["players"]})
    monkeypatch.setenv("EMAIL_PROVIDER", "dry")
    monkeypatch.setattr("run.delivery.DRY_OUTBOX", tmp_path / "outbox")
    return saturday.main(["--registry", str(registry), "--season", "2024",
                          "--week", "10", "--plans-dir", str(plans),
                          "--no-paid-check", "--allow-dry",
                          "--now", SAT.isoformat(), *extra])


def test_the_run_mails_only_a_lineup_that_has_to_change(tmp_path, monkeypatch,
                                                         capsys) -> None:
    plan = _roster()
    assert _run(tmp_path, monkeypatch, plan) == 0
    out = capsys.readouterr().out
    assert "0 need a change, 1 unchanged" in out
    assert not list((tmp_path / "outbox").glob("*"))

    assert _run(tmp_path, monkeypatch, plan,
                listed={"rb1": ("out", "ankle")}) == 0
    assert "1 need a change" in capsys.readouterr().out
    drafts = list((tmp_path / "outbox").glob("*"))
    assert drafts and "final" in drafts[0].name


def test_nobody_having_a_plan_is_a_lost_cache_not_a_quiet_week(
        tmp_path, monkeypatch, capsys) -> None:
    assert _run(tmp_path, monkeypatch, None) == 1
    assert "NO PLANS FOUND" in capsys.readouterr().err


def test_tuesday_saves_the_lineup_it_sent_and_a_preview_saves_none(
        tmp_path, monkeypatch, capsys) -> None:
    """The plan is what Saturday compares against, so it must be the lineup in
    the inbox — written for a real send, never for a dry preview."""
    import run.delivery as delivery
    import run.tuesday as tuesday
    from test_solo_run import SEASON, WEEK, _cache
    from test_tuesday import _registry, _row

    class Fake:
        name = "fake"

        def send(self, message, sender, reply_to):
            return "id-1"

    registry = _registry(tmp_path, _row())
    base = ["--registry", str(registry), "--season", SEASON, "--week", str(WEEK),
            "--cache", str(_cache(tmp_path)), "--no-paid-check",
            "--out", str(tmp_path / "out"),
            "--processed-dir", str(tmp_path / "processed")]
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setenv("EMAIL_PROVIDER", "dry")
    assert tuesday.main(base + ["--allow-dry"]) == 0
    assert not (tmp_path / "plans").exists()

    monkeypatch.setattr(tuesday, "build_provider", lambda *a: Fake())
    assert tuesday.main(base + ["--plans-dir", str(tmp_path / "plans")]) == 0
    written = list((tmp_path / "plans").rglob("*.json"))
    assert len(written) == 1
    plan = json.loads(written[0].read_text())
    assert plan["week"] == WEEK and plan["slots"]
    assert {s["player_id"] for s in plan["slots"] if s["player_id"]} <= set(plan["players"])
    assert all("tuesday" in p for p in plan["players"].values())
