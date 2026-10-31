"""The weekly report moved to Wednesday evening (owner decision, Oct 31 2026).

Each time has one plain reason, and the site says it:
- Wednesday evening: waivers have cleared, so a manager has had the day to
  update the roster, and a day is left before Thursday's game;
- Wednesday morning, in a week with a game on Wednesday;
- Saturday: teams' final injury reports are in.

A buyer before Wednesday's run gets an early look at once, then that report.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "run"))
import report_slot  # noqa: E402

CACHE = ROOT / "data" / "raw" / "nflverse"
needs_schedule = pytest.mark.skipif(not (CACHE / "games.csv").is_file(),
                                    reason="no cached nflverse schedule (data/ is gitignored)")


def _boom():
    raise OSError("down")


# --------------------------------------------------------------------- #
# when it goes
# --------------------------------------------------------------------- #

def test_the_evening_slots_always_run_and_never_read_the_schedule() -> None:
    assert report_slot.due(False, _boom, "2026-11-04") is True


def test_the_morning_slot_runs_only_on_a_day_with_a_game() -> None:
    games = lambda: [{"game_type": "REG", "gameday": "2026-11-25"},
                     {"game_type": "POST", "gameday": "2026-11-18"}]
    assert report_slot.due(True, games, "2026-11-25") is True
    assert report_slot.due(True, games, "2026-11-04") is False
    assert report_slot.due(True, games, "2026-11-18") is False, "a playoff game is not a week"


def test_a_schedule_it_cannot_read_leaves_the_morning_slot_off() -> None:
    assert report_slot.due(True, _boom, "2026-11-25") is False


def test_the_slot_script_imports_nothing_of_ours() -> None:
    """It runs with `python -I -S` in a job with nothing installed."""
    source = (ROOT / "run" / "report_slot.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:from|import) (?:run|ingest|engine|render|requests)\b",
                         source, re.M)


def test_the_workflow_and_the_worker_name_the_morning_slot_alike() -> None:
    workflow = (ROOT / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
    worker = (ROOT / "infra/form-worker.js").read_text(encoding="utf-8")
    assert "github.event.schedule == '17 13 * * 3' || inputs.slot == 'morning'" in workflow
    assert '{ cron: "17 13 * * 3", workflow: "weekly.yml", inputs: { slot: "morning" } }' in worker
    assert "needs.due.outputs.run == 'true'" in workflow


@needs_schedule
def test_every_2026_report_lands_on_a_wednesday() -> None:
    from run.solo import next_report_day
    for week in range(1, 18):
        day = date.fromisoformat(next_report_day(CACHE, "2026", week))
        assert day.weekday() == 2, (week, day)


@needs_schedule
def test_thanksgiving_eve_week_is_due_in_the_morning_slot() -> None:
    """2026's Week 12 opens Wednesday Nov 25 at 8 PM ET."""
    from run.watchdog import tuesday_due_at, week_calendar
    wednesday, saturday, kickoff = week_calendar(CACHE, "2026", 12)
    assert wednesday == date(2026, 11, 25) and saturday == date(2026, 11, 28)
    assert tuesday_due_at(wednesday, morning=True) < kickoff


def test_paid_reports_go_before_free_ones_across_the_evening() -> None:
    from run.trials import held_for_tuesday
    at = lambda iso: datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    assert held_for_tuesday(at("2026-11-04T22:30:00"), set(), "2026", 9)
    assert held_for_tuesday(at("2026-11-05T00:30:00"), set(), "2026", 9)
    assert not held_for_tuesday(at("2026-11-05T03:00:00"), set(), "2026", 9)
    assert not held_for_tuesday(at("2026-11-03T22:30:00"), set(), "2026", 9)
    assert not held_for_tuesday(at("2026-11-04T22:30:00"), {"run-tuesday-2026-w09"}, "2026", 9)


# --------------------------------------------------------------------- #
# saying why, and only what is true
# --------------------------------------------------------------------- #

def _flat(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def test_the_reasons_are_on_the_page() -> None:
    landing = _flat((SITE / "index.html").read_text(encoding="utf-8"))
    how = _flat((SITE / "how-it-works.html").read_text(encoding="utf-8"))
    for page in (landing, how):
        assert re.search(r"aivers have cleared, so you can update your roster first, and you "
                         r"still have a day before Thursday's game", page)
    assert "A week with a Wednesday game gets its report that morning" in how
    assert "teams file their final injury reports on Friday" in how


@pytest.mark.parametrize("name", ["index.html", "how-it-works.html", "thanks.html",
                                  "join/index.html", "league-pass.html"])
def test_no_page_says_we_see_the_roster_after_waivers(name) -> None:
    """We read no league. Waivers clearing only helps if the manager updates
    the roster, so no page may say the report knows the new one by itself."""
    page = _flat((SITE / name).read_text(encoding="utf-8"))
    assert "roster you'll really play" not in page and "post-waiver roster" not in page


def test_the_report_says_when_a_roster_change_counts() -> None:
    from render.report import UPDATE_BODY
    assert "by Wednesday afternoon (ET)" in UPDATE_BODY
    assert "that evening's report uses it" in UPDATE_BODY
    assert "by Friday night (ET)" in UPDATE_BODY


# --------------------------------------------------------------------- #
# the early look
# --------------------------------------------------------------------- #

class _Sink:
    name = "sink"

    def __init__(self) -> None:
        self.sent = []

    def send(self, message, sender, reply_to):
        self.sent.append(message)
        return "id"


def _env(tmp_path, monkeypatch):
    import run.delivery as delivery
    import run.intake as intake
    from test_solo_run import OFFLINE, SEASON, WEEK, _cache
    data = intake.load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE)
    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: False)
    monkeypatch.setattr(intake, "CACHE_DIR", _cache(tmp_path))
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    sink = _Sink()
    monkeypatch.setattr(intake, "build_provider", lambda *a, **k: sink)
    return intake, data, SEASON, WEEK, sink


def _signup():
    from run.intake import RosterSignup
    from test_tuesday import REF
    return RosterSignup(email="fan@example.com", ref=REF, plan="season", seen_at="1791500000")


def test_a_buyer_before_wednesdays_run_gets_an_early_look_at_once(tmp_path, monkeypatch) -> None:
    intake, data, season, week, sink = _env(tmp_path, monkeypatch)
    signup = _signup()
    processed, first = tmp_path / "processed", tmp_path / "first"
    intake._send_first_files([signup], data, season, processed_dir=processed,
                             first_plans=first, out_dir=tmp_path / "out")
    [message] = sink.sent
    assert message.key == f"{season}-w{week:02d}-early-{signup.slug}"
    assert message.subject.endswith("your early look, before waivers")
    for words in (message.text, message.html):
        assert "Your full report comes Wednesday evening" in words.replace("&#x27;", "'")
    assert not list(processed.rglob("calls.jsonl")), "an early look is not the report of record"
    from run import saturday
    assert saturday.load_plan(first, season, week, signup.slug) is None


def test_an_early_look_goes_once_and_wednesdays_report_still_goes(tmp_path, monkeypatch) -> None:
    intake, data, season, week, sink = _env(tmp_path, monkeypatch)
    from run.tuesday import report_key
    signup = _signup()
    for _ in range(2):
        intake._send_first_files([signup], data, season, processed_dir=tmp_path / "p",
                                 first_plans=tmp_path / "first", out_dir=tmp_path / "out")
    assert len(sink.sent) == 1, "the hourly run mailed the early look twice"
    entries = [json.loads(line) for line in (tmp_path / "sent.jsonl").read_text().splitlines()]
    assert report_key(season, week, signup.slug) not in {e["key"] for e in entries}, \
        "the early look would stop Wednesday's report"


def test_after_wednesdays_run_a_buyer_gets_the_report_of_record(tmp_path, monkeypatch) -> None:
    intake, data, season, week, sink = _env(tmp_path, monkeypatch)
    (tmp_path / "sent.jsonl").write_text(
        json.dumps({"key": f"run-tuesday-{season}-w{week:02d}"}) + "\n", encoding="utf-8")
    signup = _signup()
    intake._send_first_files([signup], data, season, processed_dir=tmp_path / "p",
                             first_plans=tmp_path / "first", out_dir=tmp_path / "out")
    [message] = sink.sent
    assert message.key == f"{season}-w{week:02d}-{signup.slug}"
    assert "early look" not in message.subject
    assert list((tmp_path / "p").rglob("calls.jsonl"))


def test_a_buyer_after_kickoff_still_gets_the_roster_report(tmp_path, monkeypatch) -> None:
    """No lineup for a week underway: it could be played, then refunded on the
    result, and its odds would be about games already started."""
    intake, data, season, week, sink = _env(tmp_path, monkeypatch)
    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: True)
    signup = _signup()
    intake._send_first_files([signup], data, season, processed_dir=tmp_path / "p",
                             first_plans=tmp_path / "first", out_dir=tmp_path / "out")
    [message] = sink.sent
    assert message.key.startswith("preseason-")
