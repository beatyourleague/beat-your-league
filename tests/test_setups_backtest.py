"""The setups runner may only implement its preregistration."""

from __future__ import annotations

import re
from pathlib import Path

import engine.nflverse_backtest as parent
import engine.setups_backtest as setups

METHOD = (Path(__file__).resolve().parent.parent / "reports" / "setups-method.md"
          ).read_text(encoding="utf-8")


def test_the_arms_are_exactly_the_preregistered_ones() -> None:
    """Method §1 lists the arms; the runner may not add, drop or rename one
    after an output exists — that would be choosing arms by their result."""
    table = re.findall(r"^\| (S1|S2|L10|L14|L8|TSF|TNKD|W17) \|", METHOD, re.M)
    assert tuple(table) == tuple(a.key for a in setups.ARMS)


def test_each_arm_changes_exactly_one_setting() -> None:
    headline = ("ppr", parent.LEAGUE_SIZE, parent.TEMPLATE_T1, False)
    for arm in setups.ARMS:
        values = (arm.scoring, arm.league_size, arm.template, arm.tail)
        assert sum(a != b for a, b in zip(values, headline)) == 1, arm.key


def test_calls_and_grades_come_from_the_parent_harness() -> None:
    """Method §6: an arm computed by anything other than the parent's call
    builder and grader is invalid, so the two can never grade differently."""
    assert setups.calls_for_season is parent.calls_for_season
    assert setups.evaluate is parent.evaluate
    assert setups.SEASONS == parent.SEASONS


def test_the_lineup_shapes_are_the_ones_the_product_sells() -> None:
    from run.trial import TEMPLATES
    assert setups.TEMPLATE_SF == TEMPLATES["sf"]
    assert setups.TEMPLATE_NKD == TEMPLATES["nokd"]
