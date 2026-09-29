"""The round-two runner and the parent's defenses switch may only implement
their preregistration."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import engine.nflverse_backtest as parent
import engine.round_two_backtest as r2
from engine.scoring import preset

REPO = Path(__file__).resolve().parent.parent
METHOD = (REPO / "reports" / "round-two-method.md").read_text(encoding="utf-8")
HAS_DATA = (REPO / "data" / "raw" / "nflverse").is_dir()


def test_the_combinations_are_exactly_the_preregistered_ones() -> None:
    table = re.findall(r"^\| (X\d) \| (\w+) \| (\d+) \| ([^|]+?) \|$", METHOD, re.M)
    assert [(k, sc, int(n), shape) for k, sc, n, shape in table] == [
        (c.key, c.scoring, c.league_size, c.shape) for c in r2.COMBOS]


def test_the_defense_decision_is_both_clauses() -> None:
    assert r2.defense_ships("C", 2) and r2.defense_ships("B", 5)
    assert not r2.defense_ships("C", 1), "a number about almost nothing"
    assert not r2.defense_ships("D", 6)


def test_grades_and_calls_come_from_the_parent() -> None:
    assert r2.calls_for_season is parent.calls_for_season
    assert r2.evaluate is parent.evaluate


@pytest.mark.skipif(not HAS_DATA, reason="needs the cached nflverse data")
def test_the_defenses_switch_is_inert_when_off() -> None:
    """Method §3: with the switch False the parent must reproduce its frozen,
    published per-season count exactly (2014: 953 calls)."""
    published = (REPO / "reports" / "nflverse-backtest.md").read_text(encoding="utf-8")
    expected = int(re.search(r"^\| 2014 \| (\d+) \|$", published, re.M).group(1))
    calls = parent.calls_for_season("2014", parent.RAW_DIR, parent.INJURY_DIR, preset("ppr"))
    assert len(calls) == expected
    assert not any(c.slot == "DEF" for c in calls)


@pytest.mark.skipif(not HAS_DATA, reason="needs the cached nflverse data")
def test_the_product_gate_is_restored_even_when_a_run_fails(monkeypatch) -> None:
    import engine.week_report as week_report
    before = week_report.TEAM_DEFENSE_CONFIDENCE_CALIBRATED

    def boom(*args, **kwargs):
        assert week_report.TEAM_DEFENSE_CONFIDENCE_CALIBRATED is True
        raise RuntimeError("stop before any outcome is computed")

    monkeypatch.setattr(parent, "_season_calls", boom)
    with pytest.raises(RuntimeError):
        parent.calls_for_season("2014", parent.RAW_DIR, parent.INJURY_DIR,
                                preset("ppr"), defenses=True)
    assert week_report.TEAM_DEFENSE_CONFIDENCE_CALIBRATED is before


def test_the_product_carries_the_published_decisions() -> None:
    """Method §2, applied: every combination's grade in run/solo.COMBO_GRADES
    matches the report, no D is carried without a withholding path, and the
    defense gate is open if and only if the report says it ships."""
    from engine.week_report import TEAM_DEFENSE_CONFIDENCE_CALIBRATED
    from run.solo import COMBO_GRADES
    report = (REPO / "reports" / "round-two-backtest.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (X\d) \| (\w+), (\d+) teams, ([^|]+?) \| \d+ \| \d+ "
                      r"\| \*\*(\w)\*\* \|", report, re.M)
    assert len(rows) == len(r2.COMBOS)
    for _, scoring, size, shape, grade in rows:
        assert COMBO_GRADES[(scoring, int(size), shape)] == grade
    assert "D" not in COMBO_GRADES.values(), "build the withholding path first"
    assert TEAM_DEFENSE_CONFIDENCE_CALIBRATED is ("**SHIPS**" in report)
