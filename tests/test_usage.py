"""Tests for counted usage — the market's vocabulary, from Sleeper's own feed.

The rules under test are the honesty rules in engine/usage.py: usage is counted
rather than projected, an absent field is absent rather than silently zero, and
a live report never reads the week it is about.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.usage import Usage, recent_usage, usage_line


def _write(raw: Path, season: str, week: int, payload: dict) -> None:
    d = raw / "stats"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"nfl_regular_{season}_w{week:02d}.json").write_text(
        json.dumps(payload), encoding="utf-8")


def test_usage_never_reads_the_week_it_reports_on(tmp_path: Path) -> None:
    """A live report reading its own week would quote a game already played —
    the same lookahead the waiver market forbids (RULE W2)."""
    _write(tmp_path, "2026", 5, {"p1": {"gp": 1, "rec_tgt": 99}})
    _write(tmp_path, "2026", 4, {"p1": {"gp": 1, "rec_tgt": 7}})
    usage = recent_usage(tmp_path, "p1", "2026", before_week=5)
    assert usage.targets == 7, "week 5 must not contribute to a week-5 report"


def test_a_missing_field_is_absent_not_zero(tmp_path: Path) -> None:
    """off_snp is 0% populated for 2018 and 100% for 2024. Reporting the gap as
    '0 snaps' would be a fabricated number (principle 3)."""
    _write(tmp_path, "2018", 4, {"p1": {"gp": 1, "rec_tgt": 5}})
    usage = recent_usage(tmp_path, "p1", "2018", before_week=5)
    assert usage.targets == 5
    assert usage.snaps is None
    assert "snaps" not in (usage_line(usage) or "")


def test_weeks_not_played_do_not_dilute_the_average(tmp_path: Path) -> None:
    """A returning starter's per-game rate must not be divided by weeks he was
    injured — that would understate exactly the player worth flagging."""
    _write(tmp_path, "2026", 2, {"p1": {"gp": 1, "rec_tgt": 10}})
    _write(tmp_path, "2026", 3, {"p1": {"rec_tgt": 0}})       # did not play
    _write(tmp_path, "2026", 4, {"p1": {"gp": 1, "rec_tgt": 10}})
    usage = recent_usage(tmp_path, "p1", "2026", before_week=5)
    assert usage.weeks == 2
    assert "10.0 a game" in usage_line(usage)


def test_nothing_on_record_says_nothing(tmp_path: Path) -> None:
    assert usage_line(recent_usage(tmp_path, "ghost", "2026", 5)) is None
    assert usage_line(Usage(0, None, None, None, None, None)) is None


def test_counts_read_as_english() -> None:
    line = usage_line(Usage(weeks=1, targets=1, air_yards=None,
                            rz_targets=None, snaps=None, carries=1))
    assert "1 target " in line and "1 carry" in line
    assert "last 1 game:" in line


def test_the_bench_case_cites_what_he_is_given_not_just_our_opinion() -> None:
    """The strongest line in the report is 'their bench beats their starter'.
    A projection is our opinion; a target count is the league's own record, and
    it is what makes the line hard to argue with."""
    import json as _json
    report = _json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "processed" /
         "week_report.json").read_text(encoding="utf-8"))
    bench = [f for f in report["fragility"] if "sitting on their bench" in f["title"]]
    if not bench:
        return  # a week with no benched-better player has no line to carry
    detail = bench[0]["detail"]
    assert "projects" in detail, "the projection is still the lead"
    assert "being used:" in detail and "targets" in detail, \
        "the bench case dropped its usage evidence"
