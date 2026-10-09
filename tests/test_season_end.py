"""The season's end: the last two reports, and the offseason after them.

Found by running the pipeline over 2025 weeks 14-18 (`python -m run.proving
<dir> 14-18`, Oct 2026). Every runner exited 0 and every report read fine,
which is what hid the two gaps:

- ``current_week`` answers the LAST week forever once the season is over, so
  every offseason Tuesday rebuilt Week 18 and mailed it to anyone who joined
  after it went out: "decided, before this week's first kickoff" about games
  played months ago. A derived week past the season's last game is now
  ``SeasonOver`` — a quiet exit for every runner, never a cron failure.
- Nothing told a subscriber the reports were ending, what Week 18's rested
  starters mean, or what happens to their billing; and the last report still
  promised "your next report follows" a roster change.
"""

from __future__ import annotations

import dataclasses
import html
from datetime import date
from pathlib import Path

import pytest

import run.saturday as saturday
import run.solo as solo
import run.tuesday as tuesday
from render.email import render_email, text_summary
from render.report import season_end_lines
from test_solo_run import OFFLINE, SEASON, WEEK, _cache
from test_tuesday import _registry, _row, _subscriber

TEMPLATE = Path("rival-report-template.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------- #
# the offseason
# --------------------------------------------------------------------- #

def test_a_derived_week_after_the_last_game_is_season_over(tmp_path) -> None:
    cache = _cache(tmp_path)          # 2024 fixture: last game Sep 14 2024
    assert not solo.season_over(cache, SEASON, date(2024, 9, 14))
    assert solo.season_over(cache, SEASON, date(2024, 9, 15))
    with pytest.raises(solo.SeasonOver):
        solo.load_week_data(cache, SEASON, None, session=OFFLINE,
                            today=date(2024, 12, 1))
    # An explicit week is a deliberate rebuild (a backfill, the proving run)
    # and still builds.
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    assert data.week == WEEK and data.last_week == 8


def test_the_tuesday_run_is_quiet_in_the_offseason(tmp_path, capsys) -> None:
    """Exit 0: the cron fires every Tuesday of the offseason and a failure
    files an issue each time."""
    code = tuesday.main(["--registry", str(_registry(tmp_path, _row())),
                         "--season", SEASON, "--cache", str(_cache(tmp_path)),
                         "--no-paid-check", "--no-send",
                         "--out", str(tmp_path / "out"),
                         "--processed-dir", str(tmp_path / "processed")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "No reports this week" in out and "season is over" in out
    assert not (tmp_path / "out").exists()


def test_the_saturday_check_is_quiet_in_the_offseason(tmp_path, capsys) -> None:
    code = saturday.main(["--registry", str(_registry(tmp_path, _row())),
                          "--season", SEASON, "--cache", str(_cache(tmp_path)),
                          "--no-paid-check", "--plans-dir", str(tmp_path / "plans"),
                          "--now", "2024-12-07T16:00:00+00:00"])
    assert code == 0
    assert "season is over" in capsys.readouterr().out


# --------------------------------------------------------------------- #
# the last two reports
# --------------------------------------------------------------------- #

def _report(tmp_path, last_week: int, plan: str = "season"):
    data = dataclasses.replace(
        solo.load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE),
        last_week=last_week)
    result = tuesday.run_subscriber(
        _subscriber(**({"plan": plan, "covered_by": "payer@example.com"}
                       if plan == "league_pass" else {"plan": plan})),
        data, TEMPLATE, out_dir=tmp_path / "out",
        processed_dir=tmp_path / "processed")
    assert result.ok, result.detail
    return result


def test_championship_week_says_whether_another_report_comes(tmp_path) -> None:
    result = _report(tmp_path, last_week=WEEK + 1)
    note = f"If your league plays Week {WEEK + 1}, next Tuesday's report covers it"
    assert note in result.message.text
    assert note in html.unescape(result.message.html)
    assert "season's last report" not in result.message.text
    # A normal week carries no season note at all.
    assert "SEASON'S END" not in _report(tmp_path, last_week=WEEK + 5).message.text


@pytest.mark.parametrize("plan, says", [
    ("monthly", "stops billing on its own"),
    ("season", "we email you before it does"),
    ("league_pass", "if your league's pass is renewed"),
])
def test_the_last_report_says_so_and_what_happens_to_the_billing(
        tmp_path, plan, says) -> None:
    result = _report(tmp_path, last_week=WEEK, plan=plan)
    text, body = result.message.text, html.unescape(result.message.html)
    assert "This is the season's last report." in text
    assert says in text and says in body
    assert "inactives, posted 90 minutes before kickoff" in text
    # No next report exists to follow a roster change.
    assert "your next report follows it" not in text
    assert "your next report follows it" not in body
    # The browser archive carries it too.
    assert "This is the season" in result.html_path.read_text(encoding="utf-8")


def test_the_last_reports_billing_line_never_reaches_a_sample_or_free_report() -> None:
    meta = {"solo": True, "week": 18, "last_week": 18}
    assert season_end_lines(meta) and not any(
        "billing" in line or "renews" in line for line in season_end_lines(meta))
    assert season_end_lines({**meta, "historical_demo": True}) == []
    assert season_end_lines({**meta, "trial": True, "plan": None})[0].startswith("Week 18")


def test_the_season_note_carries_no_banned_words() -> None:
    banned = ("calibrated", "tested", "proven", "accurate", "bet", "odds")
    for plan in ("monthly", "season", "league_pass", None):
        for week in (17, 18):
            for line in season_end_lines({"solo": True, "week": week,
                                          "last_week": 18, "plan": plan}):
                assert not any(word in line.lower().split() for word in banned), line
