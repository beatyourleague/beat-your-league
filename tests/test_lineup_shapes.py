"""Lineup shapes (contract C8): offered everywhere, odds only where graded.

Sleeper's default lineup has two FLEX spots and Yahoo's three WR; the signup
page offered neither (RQ-10, SS-I3, PE-2, AFTER-9), so those buyers picked a
lineup that was not theirs and were told to bench a starter. Every shape is now
selectable and carried through the ref, intake, registry and run — and a shape
no preregistered arm has graded prints no odds anywhere, while its lineup,
projections, plans and Saturday check all still work.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path

import pytest

from engine.subscriber import (GRADED_SHAPES, LINEUP_SHAPES, SHAPE_BASES,
                               UNGRADED_SHAPE_GATE, RosterSpec, graded_shape,
                               shape_by_code, shape_code, shape_for_slots,
                               withhold_ungraded_odds)

REPO = Path(__file__).resolve().parent.parent
T1 = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")


# --------------------------------------------------------------------- #
# the table
# --------------------------------------------------------------------- #

def test_the_three_graded_shapes_are_the_ones_the_setups_run_measured() -> None:
    """Only shapes an arm graded may print odds. The three are the templates
    reports/setups-method.md graded, letter for letter — the slot ORDER too,
    because the same slots in another order would read as a different shape."""
    import engine.setups_backtest as setups
    from engine.nflverse_backtest import TEMPLATE_T1
    graded = {code: LINEUP_SHAPES[code].slots for code in GRADED_SHAPES}
    assert graded == {"std": tuple(TEMPLATE_T1), "sf": setups.TEMPLATE_SF,
                      "nokd": setups.TEMPLATE_NKD}
    from run.trial import TEMPLATES
    for code in GRADED_SHAPES:
        assert LINEUP_SHAPES[code].slots == TEMPLATES[code], code


def test_every_base_with_and_without_k_and_def_is_one_shape() -> None:
    assert set(SHAPE_BASES) == {"std", "flex2", "wr3", "sf"}
    assert len(LINEUP_SHAPES) == 16
    for shape in LINEUP_SHAPES.values():
        assert shape.slots[: len(SHAPE_BASES[shape.base][0])] == SHAPE_BASES[shape.base][0]
        assert ("K" in shape.slots) is shape.kicker
        assert ("DEF" in shape.slots) is shape.defense
        assert shape_for_slots(shape.slots) is shape
        assert shape_by_code(shape.code) is shape
    # The platform defaults named on the page are what they claim to be.
    assert LINEUP_SHAPES["flex2"].slots == ("QB", "RB", "RB", "WR", "WR", "TE",
                                            "FLEX", "FLEX", "K", "DEF")
    assert LINEUP_SHAPES["wr3"].slots == ("QB", "RB", "RB", "WR", "WR", "WR", "TE",
                                          "FLEX", "K", "DEF")
    assert shape_code("std", False, False) == "nokd"
    assert shape_by_code("std-nokd") is LINEUP_SHAPES["nokd"]
    assert shape_for_slots(("QB", "RB")) is None and not graded_shape(("QB", "RB"))


# --------------------------------------------------------------------- #
# the withholding, on a report in hand
# --------------------------------------------------------------------- #

def _report() -> dict:
    return {
        "meta": {"league_id": "typed-ppr-12-2026", "season": "2026", "week": 6,
                 "my_roster_id": 1},
        "lineup": [
            {"slot": "QB", "player_id": "00-1", "player_name": "A", "confidence": 0.71,
             "confidence_gate": None, "alternative_id": "00-2", "alternative_name": "B",
             "projected": 20.1, "flags": [{"kind": "seeded", "text": "last season counted in"}]},
            {"slot": "RB", "player_id": "00-3", "player_name": "C", "confidence": None,
             "confidence_gate": "not enough games on record yet (2 and 5; we want at least 3)",
             "alternative_id": "00-4", "projected": 9.0, "flags": []},
        ],
        "regret": {"slot": "QB", "start_id": "00-1", "over_id": "00-2", "confidence": 0.71},
        "checklist": [{"action": "No start-sit calls yet. Projections start next week; "
                                 "the number on each call starts in Week 4, once both "
                                 "players in it have three games of record."}],
    }


def test_an_ungraded_shape_prints_no_number_and_says_why() -> None:
    """Reproduction: before C8, a two-FLEX roster's Week 6 report carried
    0.646 / 0.797 / 0.632 on three rows exactly as the standard lineup's did —
    a published probability in a setup no run had graded, recorded on the
    public ledger as if it had been."""
    from engine.ledger import extract_published_calls
    report = _report()
    assert extract_published_calls(copy.deepcopy(report)), "fixture must publish a call"
    out = withhold_ungraded_odds(report, LINEUP_SHAPES["flex2"].slots)
    assert [row["confidence"] for row in out["lineup"]] == [None, None]
    assert out["lineup"][0]["confidence_gate"] == UNGRADED_SHAPE_GATE
    # Other reasons stay true; the projection and the seat never move.
    assert out["lineup"][1]["confidence_gate"].startswith("not enough games")
    assert out["lineup"][0]["projected"] == 20.1 and out["lineup"][0]["player_id"] == "00-1"
    assert out["lineup"][0]["flags"] == []
    assert out["regret"] == {"gate": f"no coin-flip call this week — {UNGRADED_SHAPE_GATE}"}
    assert "Week 4" not in out["checklist"][0]["action"]
    assert "once this lineup shape is graded" in out["checklist"][0]["action"]
    assert out["meta"]["ungraded_shape"] == "Two FLEX"
    # So the public record gets nothing it would have to grade.
    assert extract_published_calls(out) == []


def test_the_game_plan_keeps_its_decision_and_loses_its_number() -> None:
    """Reproduction (Oct 16 2026): the withholding cleared every row and the
    closest call, and left the game plan alone — where a benched starter-
    calibre player paired with the call that sits him is written as words,
    "Start Rome Odunze over Saquon Barkley at FLEX · 64%". A two-FLEX
    subscriber would have read a percentage no arm graded in the first line
    of their report. The line becomes the one engine/solo_report.py writes
    when no call is paired; nothing else in the plan moves. Mutation-checked:
    dropping the rewrite fails the first assertion."""
    report = _report()
    report["checklist"] = [
        {"action": "Start Rome Odunze over Saquon Barkley at FLEX · 64%",
         "detail": "Saquon Barkley: RB3 last season. Projects 9.1, Rome Odunze 10.4."},
        {"action": "Start Josh Allen over Lamar Jackson at SUPER_FLEX · 7%"},
        {"action": "Watch Chase Brown · 58%"},
        {"action": "Bench Amon-Ra St. Brown — he can't play this week"},
    ]
    before = copy.deepcopy(report["checklist"])
    out = withhold_ungraded_odds(report, LINEUP_SHAPES["flex2"].slots)
    actions = [item["action"] for item in out["checklist"]]
    assert actions == ["Bench Saquon Barkley — Rome Odunze starts at FLEX",
                       "Bench Lamar Jackson — Josh Allen starts at SUPER_FLEX",
                       "Watch Chase Brown",
                       "Bench Amon-Ra St. Brown — he can't play this week"]
    assert out["checklist"][0]["detail"] == before[0]["detail"]
    # A graded shape's plan keeps its number.
    graded = _report()
    graded["checklist"] = copy.deepcopy(before)
    assert withhold_ungraded_odds(graded, T1)["checklist"] == before


@pytest.mark.parametrize("code", sorted(GRADED_SHAPES))
def test_a_graded_shape_is_left_exactly_as_built(code) -> None:
    """The withholding may only ever REMOVE from ungraded shapes: a graded
    shape's report is the same object, byte for byte."""
    report = _report()
    before = copy.deepcopy(report)
    assert withhold_ungraded_odds(report, LINEUP_SHAPES[code].slots) is report
    assert report == before


def test_both_renderers_state_the_shape_reason_in_its_own_words() -> None:
    """Contract C8's render half. The reason is the plain sentence the engine
    writes; a renderer that does not know it falls through to "a player's
    status isn't confirmed yet" — a false statement about a confirmed starter
    (found rendering a two-FLEX Week 6 report)."""
    from render.report import gate_phrase, row_label
    assert "lineup shape" in gate_phrase(UNGRADED_SHAPE_GATE)
    slot = {"slot": "FLEX", "confidence_gate": UNGRADED_SHAPE_GATE, "status": "active",
            "alternative_name": "Zach Ertz", "player_name": "Rome Odunze"}
    assert "waiting on" not in row_label(slot) and "status" not in row_label(slot)


# --------------------------------------------------------------------- #
# the real pipeline, on the live sample roster (Week 6 2026)
# --------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def week6():
    from run.solo import CACHE_DIR, load_week_data
    if not (CACHE_DIR / "players.csv").is_file():
        pytest.skip("nflverse cache not present")
    try:
        return load_week_data(CACHE_DIR, today=date(2026, 10, 15))
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"week data unavailable: {exc}")


def _roster(data):
    from render.live_sample import LIVE_ROSTER
    known = {p.player_id for p in data.directory.players}
    return tuple(pid for pid in LIVE_ROSTER if pid in known)


def _build(data, code):
    from run.solo import report_for
    projections: dict[str, float] = {}
    spec = RosterSpec(_roster(data), LINEUP_SHAPES[code].slots, "ppr")
    return report_for(spec, data, 12, projections_out=projections), projections


def test_report_for_withholds_every_number_in_an_ungraded_shape(week6) -> None:
    """End to end through run/solo.report_for. The standard lineup publishes
    on this roster (the control: delete the withholding's graded check and
    this half fails); the two-FLEX lineup carries every row, projection and
    plan, and no number anywhere — not on a row, not as the closest call,
    not on the ledger."""
    from engine.ledger import extract_published_calls
    std, _ = _build(week6, "std")
    assert any(row["confidence"] is not None for row in std["lineup"]), \
        "the control lost its odds: this test no longer proves anything"
    for code in ("flex2", "wr3", "sf-nok", "flex2-nokd"):
        report, projections = _build(week6, code)
        assert len(report["lineup"]) == len(LINEUP_SHAPES[code].slots), code
        assert all(row["confidence"] is None for row in report["lineup"]), code
        assert UNGRADED_SHAPE_GATE in {row["confidence_gate"] for row in report["lineup"]}, code
        assert "confidence" not in report["regret"], code
        assert extract_published_calls(report) == [], code
        assert any(row["projected"] is not None for row in report["lineup"]), code
        assert projections, code
        assert report["checklist"], code
        assert [row["slot"] for row in report["lineup"]] == list(LINEUP_SHAPES[code].slots)
        # Nowhere in what the renderers read — row, plan, closest call.
        assert not re.search(r"\d%", json.dumps(report)), code


def test_the_saturday_check_works_on_an_ungraded_shape(week6) -> None:
    """A two-FLEX subscriber's Saturday check: a FLEX starter ruled out on
    Friday is replaced from the bench, from Tuesday's printed projections —
    no number involved, so nothing about grading touches it."""
    from engine.final_check import SWAP, Now, final_check
    from run.saturday import build_plan
    report, projections = _build(week6, "flex2")
    plan = build_plan(report, projections, {}, {}, "abcdef0123")
    flex = [s["player_id"] for s in plan["slots"] if s["slot"] == "FLEX"]
    assert len(flex) == 2 and all(flex)
    now = {pid: Now() for pid in plan["players"]}
    now[flex[0]] = Now(designation="out", reason="listed out (ankle)")
    changes = final_check(plan, now)
    assert any(change.kind == SWAP for change in changes), changes


# --------------------------------------------------------------------- #
# the preregistered harness (draft): arms derived, published runs untouched
# --------------------------------------------------------------------- #

def test_the_shape_arms_are_exactly_the_ungraded_shapes() -> None:
    import engine.shapes_backtest as shapes
    assert {arm.key for arm in shapes.SHAPE_ARMS} == \
        {code for code, shape in LINEUP_SHAPES.items() if not shape.graded}
    for arm in shapes.SHAPE_ARMS:
        assert arm.template == LINEUP_SHAPES[arm.key].slots
        if arm.same_calls_as:
            twin = LINEUP_SHAPES[arm.same_calls_as]
            assert twin.slots == arm.template + ("DEF",)


def test_the_shape_harness_grades_with_the_parents_code_as_shipped() -> None:
    import engine.nflverse_backtest as parent
    import engine.shapes_backtest as shapes
    from engine.recalibration import GRADE_SEASONS
    assert shapes.calls_for_season is parent.calls_for_season
    assert shapes.evaluate is parent.evaluate
    assert shapes.SHIPPED == {"confirmed_fallback": True, "late_self_weight": 0.25,
                              "context": "AV"}
    import run.solo as solo
    assert solo.CONTEXT_ARM == "AV" and solo.ANCHOR_WEIGHT == 0.25 and solo.CONFIRMED_FALLBACK
    assert GRADE_SEASONS == tuple(str(y) for y in range(2020, 2025))


def test_adding_the_shape_harness_moved_no_published_arm() -> None:
    """Every published run reproduces: the setups and round-two arms are the
    frozen ones, and no frozen runner imports the new module."""
    import engine.round_two_backtest as round_two
    import engine.setups_backtest as setups
    assert [a.key for a in setups.ARMS] == ["S1", "S2", "L10", "L14", "L8", "TSF",
                                            "TNKD", "W17"]
    assert [c.key for c in round_two.COMBOS] == [f"X{i}" for i in range(1, 10)]
    for name in ("setups_backtest", "round_two_backtest", "context_combos",
                 "nflverse_backtest", "recalibration", "context_backtest",
                 "anchor_backtest", "fallback_backtest", "early_season_backtest"):
        source = (REPO / "engine" / f"{name}.py").read_text(encoding="utf-8")
        assert "shapes_backtest" not in source, name


def test_the_shape_runner_refuses_a_partial_window_and_writes_one_report(tmp_path) -> None:
    """Wired, without grading anything real (the run is the lead's, once the
    method is frozen): a failed season writes nothing and exits non-zero; a
    full window writes every arm through the shipped recalibration."""
    import engine.shapes_backtest as shapes
    from engine.decisions import StartSitCall
    from engine.nflverse_backtest import BacktestError

    def fake(arm, season, raw, injuries):
        return [StartSitCall(season, week, roster, "FLEX", 6, "00-1", "00-2", "00-1",
                             0.55 + 0.01 * roster, 10.0, 8.0, 12.0,
                             7.0 if roster % 3 else 13.0,
                             "hit" if roster % 3 else "miss", False)
                for week in range(4, 17) for roster in range(1, 13)]

    def broken(arm, season, raw, injuries):
        if season == "2023":
            raise BacktestError("no stats")
        return fake(arm, season, raw, injuries)

    arms = shapes.SHAPE_ARMS[:2]
    assert shapes.run(arms, tmp_path, tmp_path, broken) is None
    results = shapes.run(arms, tmp_path, tmp_path, fake)
    assert [arm.key for arm, _, _ in results] == [a.key for a in arms]
    text = shapes.report(results, 1.2064)
    assert "b = 1.2064" in text and all(f"### {a.key}" in text for a in arms)
