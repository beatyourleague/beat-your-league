"""Tests for reconstructing the shipping gate from historical injury reports.

The point of the module is to answer a question honestly, so the properties
worth pinning are the ones that keep the answer honest: no lookahead, no
silent pass, and reconstructed weeks never contaminating the live snapshot
store the product treats as ground truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.gate_backtest import apply_gate
from ingest.injuries import _normalise, load_weeks


class _Call:
    """The two fields apply_gate reads, without building a full StartSitCall."""

    def __init__(self, season, week, started, alt):
        self.season, self.week = season, week
        self.started_id, self.alternative_id = started, alt


def test_a_designation_on_either_player_drops_the_call() -> None:
    """The gate is about the HEAD-TO-HEAD: a number comparing two players is
    only publishable when neither of them is in doubt."""
    designations = {"2018": {5: {"a": "Out", "b": "Questionable"}}}
    calls = [_Call("2018", 5, "a", "x"),    # starter out
             _Call("2018", 5, "x", "b"),    # alternative doubtful
             _Call("2018", 5, "x", "y")]    # neither on the report
    kept, result = apply_gate(calls, designations)
    assert len(kept) == 1 and kept[0].started_id == "x"
    assert result.dropped_out == 1 and result.dropped_doubt == 1


def test_absence_from_the_report_means_active() -> None:
    """An injury report lists who is in question, not who is fine. Treating an
    unlisted player as unknown would throw away almost the whole call set."""
    kept, result = apply_gate([_Call("2018", 5, "nobody", "else")],
                              {"2018": {5: {}}})
    assert result.kept == 1


def test_a_season_with_no_archive_is_dropped_not_assumed_healthy() -> None:
    """Missing data must never be read as 'everyone was fit' — that would
    silently inflate the kept set with unverified calls."""
    kept, result = apply_gate([_Call("1999", 5, "a", "b")], {"2018": {}})
    assert result.kept == 0 and result.unknown_player == 1


def test_practice_notes_are_not_game_designations() -> None:
    """report_status is the game-day designation; a limited practice is not,
    and reading one as doubt would invent uncertainty the league never
    published."""
    assert _normalise("Out") == "Out"
    assert _normalise("Doubtful") == "Out"
    assert _normalise("Questionable") == "Questionable"
    assert _normalise("") is None
    assert _normalise(None) is None
    assert _normalise("Full Participation in Practice") is None


def test_no_snapshot_shaped_export_exists(tmp_path: Path) -> None:
    """engine.availability reads a missing player as UNKNOWN; an injury report
    means a missing player is FINE. A function emitting report data in snapshot
    shape would invert that and gate away nearly every call while appearing to
    work, so it deliberately does not exist."""
    import ingest.injuries as injuries
    assert not hasattr(injuries, "reconstruct_snapshot")
    assert not hasattr(injuries, "write_reconstructed")


def test_designations_parse_from_the_archive(tmp_path: Path) -> None:
    csv_path = tmp_path / "injuries_2018.csv"
    csv_path.write_text(
        "season,week,gsis_id,team,report_status,practice_status\n"
        "2018,3,00-0000001,KC,Out,\n"
        "2018,3,00-0000002,KC,Questionable,\n"
        "2018,3,00-0000003,KC,,Limited Participation in Practice\n",
        encoding="utf-8")
    week = load_weeks(csv_path, "2018")[3]
    assert week.by_gsis == {"00-0000001": "Out", "00-0000002": "Questionable"}
    # on the report but with no game designation: listed, not in doubt
    assert "00-0000003" in week.teams and "00-0000003" not in week.by_gsis
