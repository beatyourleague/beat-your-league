"""Tests for Phase 5: ledger record/grade rules, receipt cards, ledger page,
and the content draft generators."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_week_report as twr
from engine.ledger import (GRADED, HIT, MISS, PENDING, VOID, LedgerCall,
                           extract_published_calls, grade_ledger,
                           ledger_summary, load_ledger, public_entries,
                           record_calls)
from render.cards import receipt_card_svg, write_receipt_cards
from render.ledger_site import render_ledger


def _report_with_snapshot(tmp_path: Path, week: int = twr.REPORT_WEEK):
    """Fixture league with an all-active snapshot: calls actually publish.

    Week 6 (the default REPORT_WEEK) has no scores yet in the fixture; week 5
    has real differentiated points — use it for tests that grade outcomes.
    """
    from engine.week_report import build_week_report
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    snap_dir = raw / "availability" / season.season
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / f"regular_week_{week:02d}.json").write_text(json.dumps({
        "as_of": "2025-10-09T12:00:00+00:00", "season": season.season,
        "season_type": "regular", "week": week,
        "statuses": twr.ACTIVE_ALL,
    }), encoding="utf-8")
    report = build_week_report(raw, season.league_id, week, 1)
    return season, raw, report


# --------------------------------------------------------------------- #
# recording
# --------------------------------------------------------------------- #

def test_extract_only_published_calls(tmp_path: Path) -> None:
    season, raw, report = _report_with_snapshot(tmp_path)
    calls = extract_published_calls(report)
    published = [s for s in report["lineup"] if s["confidence"] is not None]
    assert len(calls) == len(published) > 0
    assert all(c.confidence >= 0.5 for c in calls)
    # The regret call is one of the slot calls, flagged — never a duplicate row.
    assert sum(1 for c in calls if c.is_regret) == 1


def test_gated_report_contributes_nothing(tmp_path: Path) -> None:
    from engine.week_report import build_week_report
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)  # no snapshot: everything gated
    report = build_week_report(raw, season.league_id, twr.REPORT_WEEK, 1)
    assert extract_published_calls(report) == []


def test_record_is_idempotent(tmp_path: Path) -> None:
    _, _, report = _report_with_snapshot(tmp_path)
    calls = extract_published_calls(report)
    path = tmp_path / "ledger" / "calls.jsonl"
    assert record_calls(path, calls) == len(calls)
    assert record_calls(path, calls) == 0  # RULE L4: re-runs add nothing
    assert len(load_ledger(path)) == len(calls)


# --------------------------------------------------------------------- #
# grading
# --------------------------------------------------------------------- #

def test_grading_settles_hit_miss_and_respects_box_scores(tmp_path: Path) -> None:
    season, raw, report = _report_with_snapshot(tmp_path, week=twr.REPORT_WEEK - 1)
    path = tmp_path / "ledger" / "calls.jsonl"
    record_calls(path, extract_published_calls(report))
    graded, pending = grade_ledger(path, raw)
    assert graded > 0 and pending == 0  # fixture schedule: every game complete
    settled = load_ledger(path)
    assert any(c.status == GRADED for c in settled)
    for call in settled:
        if call.status != GRADED:
            continue
        expected = HIT if call.pick_points > call.over_points else (
            MISS if call.pick_points < call.over_points else "tie")
        assert call.outcome == expected


def test_unplayed_zero_zero_grades_void_not_tie(tmp_path: Path) -> None:
    """Fixture week 6 has no scores (all 0.0): a non-event must never enter
    the record as a tie (RULE L3 / Phase 2 absence signal)."""
    season, raw, report = _report_with_snapshot(tmp_path)  # week 6
    path = tmp_path / "ledger" / "calls.jsonl"
    record_calls(path, extract_published_calls(report))
    grade_ledger(path, raw)
    calls = load_ledger(path)
    assert calls and all(c.status == VOID for c in calls)
    assert all("0.0" in (c.void_reason or "") for c in calls)


def test_grading_waits_for_unfinished_games(tmp_path: Path) -> None:
    season, raw, report = _report_with_snapshot(tmp_path)
    schedule_file = raw / "schedule" / f"nfl_regular_{season.season}.json"
    games = json.loads(schedule_file.read_text(encoding="utf-8"))
    for game in games:
        if game["week"] == twr.REPORT_WEEK:
            game["status"] = "in_progress"  # Monday night still playing
    schedule_file.write_text(json.dumps(games), encoding="utf-8")

    path = tmp_path / "ledger" / "calls.jsonl"
    record_calls(path, extract_published_calls(report))
    graded, pending = grade_ledger(path, raw)
    assert graded == 0 and pending > 0  # RULE L1: never grade a live game
    assert all(c.status == PENDING for c in load_ledger(path))


def test_grading_never_edits_settled_calls(tmp_path: Path) -> None:
    season, raw, report = _report_with_snapshot(tmp_path)
    path = tmp_path / "ledger" / "calls.jsonl"
    record_calls(path, extract_published_calls(report))
    grade_ledger(path, raw)
    first = {c.call_id: (c.outcome, c.graded_at) for c in load_ledger(path)}
    grade_ledger(path, raw)  # RULE L4: second pass is a no-op
    second = {c.call_id: (c.outcome, c.graded_at) for c in load_ledger(path)}
    assert first == second


def test_missing_player_grades_void_not_silent(tmp_path: Path) -> None:
    """A player in the week's snapshot (game final) who was dropped from the
    fantasy roster mid-week has no scoring record -> VOID, never silent."""
    season, raw, report = _report_with_snapshot(tmp_path)
    path = tmp_path / "ledger" / "calls.jsonl"
    calls = extract_published_calls(report)
    calls[0].pick_id = "qb9"  # in snapshot with a completed game; not on roster 1
    record_calls(path, calls)
    grade_ledger(path, raw)
    ghost = next(c for c in load_ledger(path) if c.pick_id == "qb9")
    assert ghost.status == VOID and "no scoring record" in (ghost.void_reason or "")
    summary = ledger_summary(load_ledger(path))
    assert summary["void"] >= 1  # shown, not hidden (week 6's 0-0s void too)


def test_player_absent_from_snapshot_stays_pending(tmp_path: Path) -> None:
    """RULE L1 conservatism: if finality can't be confirmed, never grade."""
    season, raw, report = _report_with_snapshot(tmp_path)
    path = tmp_path / "ledger" / "calls.jsonl"
    calls = extract_published_calls(report)
    calls[0].pick_id = "ghost99"
    record_calls(path, calls)
    grade_ledger(path, raw)
    ghost = next(c for c in load_ledger(path) if c.pick_id == "ghost99")
    assert ghost.status == PENDING


def test_public_entries_leak_nothing_private(tmp_path: Path) -> None:
    season, raw, report = _report_with_snapshot(tmp_path)
    path = tmp_path / "ledger" / "calls.jsonl"
    record_calls(path, extract_published_calls(report))
    grade_ledger(path, raw)
    rows = public_entries(load_ledger(path))
    assert rows
    dumped = json.dumps(rows)
    assert season.league_id not in dumped
    assert "roster" not in dumped and "league_id" not in dumped


def test_concurrent_record_and_grade_lose_nothing(tmp_path: Path) -> None:
    """Review finding (reproduced pre-fix): unlocked read-modify-write let a
    concurrent writer erase recorded calls. With the flock, nothing is lost."""
    import threading
    season, raw, report = _report_with_snapshot(tmp_path, week=twr.REPORT_WEEK - 1)
    path = tmp_path / "ledger" / "calls.jsonl"
    base_calls = extract_published_calls(report)

    def clone(call, i):
        from dataclasses import replace
        return replace(call, call_id=f"{call.call_id[:12]}{i:04d}", slot=f"S{i}")

    workers = []
    for worker_id in range(4):
        batch = [clone(base_calls[0], worker_id * 50 + i) for i in range(50)]
        workers.append(threading.Thread(
            target=lambda b=batch: (record_calls(path, b), grade_ledger(path, raw))))
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    assert len(load_ledger(path)) == 200  # every recorded call survived


def test_corrupt_ledger_raises_typed_error_with_line(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    path.write_text('{"call_id": "ok"\nnot json\n', encoding="utf-8")
    from engine.ledger import LedgerError
    with pytest.raises(LedgerError, match="line 1"):
        load_ledger(path)


def test_unknown_fields_from_newer_schema_are_tolerated(tmp_path: Path) -> None:
    call = _settled_call()
    from dataclasses import asdict
    raw = asdict(call)
    raw["future_field"] = "added in v2"
    path = tmp_path / "calls.jsonl"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    assert load_ledger(path)[0].call_id == call.call_id


# --------------------------------------------------------------------- #
# receipt cards + ledger page
# --------------------------------------------------------------------- #

def _settled_call(**overrides) -> LedgerCall:
    base = dict(
        call_id="abc123", source="slot", league_id="1", season="2025", week=6,
        roster_id=1, slot="WR", pick_id="p1",
        pick_name='Hostile <script>"Name"</script>', over_id="p2",
        over_name="Steady & Sons", confidence=0.61, recorded_at="t",
        status=GRADED, outcome=HIT, pick_points=17.4, over_points=9.9,
        graded_at="t",
    )
    base.update(overrides)
    return LedgerCall(**base)


def test_receipt_card_escapes_names_and_refuses_pending() -> None:
    svg = receipt_card_svg(_settled_call())
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg and "Steady &amp; Sons" in svg
    assert ">HIT<" in svg
    with pytest.raises(ValueError, match="pending"):
        receipt_card_svg(_settled_call(status=PENDING, outcome=None))


def test_receipt_cards_written_only_for_settled(tmp_path: Path) -> None:
    calls = [_settled_call(),
             _settled_call(call_id="d4", status=PENDING, outcome=None)]
    written = write_receipt_cards(calls, tmp_path)
    assert len(written) == 1 and "abc123" in written[0].name


def test_ledger_page_escapes_and_handles_both_states() -> None:
    empty = render_ledger([], ledger_summary([]))
    # The empty state is what every launch visitor sees — it must show the rule
    # it can actually stand behind today, and must never announce its own
    # emptiness to someone who arrived looking for proof.
    assert "rules are up before the first game" in empty.lower()
    assert "hit or miss" in empty.lower()
    assert "nothing to show" not in empty.lower()
    call = _settled_call()
    page = render_ledger(public_entries([call]), ledger_summary([call]))
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "HIT" in page and "61%" in page


# --------------------------------------------------------------------- #
# content drafts (via the real generators on the fixture cache)
# --------------------------------------------------------------------- #

def _patched_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: Path):
    import engine.week_report as wr
    import run.content as content
    monkeypatch.setattr(content, "RAW_DIR", raw)
    monkeypatch.setattr(content, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(content, "CONTENT_DIR", tmp_path / "content")
    monkeypatch.setattr(content, "REPO_ROOT", tmp_path)
    import render.ledger_site as ls
    monkeypatch.setattr(ls, "DEFAULT_OUT_DIR", tmp_path / "site" / "ledger")
    return content


def test_receipts_draft_full_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    season, raw, report = _report_with_snapshot(tmp_path, week=twr.REPORT_WEEK - 1)
    content = _patched_content(monkeypatch, tmp_path, raw)
    from engine.ledger import ledger_path as lp
    record_calls(lp(tmp_path / "processed", season.league_id),
                 extract_published_calls(report))
    path, note = content.receipts_monday(season.league_id, twr.REPORT_WEEK - 1)
    text = path.read_text(encoding="utf-8")
    assert "Receipts Monday" in text and "HIT" in text.upper()
    assert "LLM tokens used to draft this: 0" in text
    assert (tmp_path / "site" / "ledger" / "index.html").is_file()
    assert list((tmp_path / "content" / "cards").glob("receipt-*.svg"))


def test_receipts_draft_honest_when_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    content = _patched_content(monkeypatch, tmp_path, raw)
    path, _ = content.receipts_monday(season.league_id, None)
    assert "No graded calls" in path.read_text(encoding="utf-8")


def test_coinflip_gated_when_availability_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No snapshot -> the regret call is gated -> the draft passes honestly.
    (The recorded-vs-fresh distinction is covered by
    test_coinflip_drafts_only_from_the_ledger.)"""
    gated_raw = twr._write_cache(tmp_path / "gated", twr._season())
    content = _patched_content(monkeypatch, tmp_path / "gated", gated_raw)
    path, note = content.coinflip_friday(twr._season().league_id, twr.REPORT_WEEK, 1)
    assert "No publishable coin flip" in path.read_text(encoding="utf-8")
    assert note == "gated"


def test_reply_kit_counts_and_honesty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    season, raw, _ = _report_with_snapshot(tmp_path)
    content = _patched_content(monkeypatch, tmp_path, raw)
    path, note = content.reply_kit(season.league_id, twr.REPORT_WEEK, 1, "2026-09-10")
    text = path.read_text(encoding="utf-8")
    assert path.name == "reply-kit-2026-09-10.md"
    headings = [l for l in text.splitlines() if l.startswith("## ")]
    assert 1 <= len(headings) <= 8
    assert "Reply template" in text


def test_shrink_guard_refuses_to_wipe_the_public_record(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: a cache-restore miss must never regenerate (and then
    publish) an emptier ledger page — fail closed instead."""
    season, raw, report = _report_with_snapshot(tmp_path, week=twr.REPORT_WEEK - 1)
    content = _patched_content(monkeypatch, tmp_path, raw)
    from engine.ledger import ledger_path as lp
    record_calls(lp(tmp_path / "processed", season.league_id),
                 extract_published_calls(report))
    path, _ = content.receipts_monday(season.league_id, twr.REPORT_WEEK - 1)
    data_json = tmp_path / "site" / "ledger" / "data.json"
    assert json.loads(data_json.read_text(encoding="utf-8"))  # entries published

    # Simulate the ledger store losing data (restore miss on a fresh runner).
    import shutil
    shutil.rmtree(tmp_path / "processed" / "ledger")
    from engine.week_report import WeekReportError
    with pytest.raises(WeekReportError, match="REFUSING"):
        content.receipts_monday(season.league_id, twr.REPORT_WEEK - 1)
    # The committed page survived untouched.
    assert json.loads(data_json.read_text(encoding="utf-8"))


def test_coinflip_drafts_only_from_the_ledger(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: Friday's post must quote the recorded call, never a
    fresh unrecorded number."""
    season, raw, report = _report_with_snapshot(tmp_path, week=twr.REPORT_WEEK - 1)
    content = _patched_content(monkeypatch, tmp_path, raw)

    # Nothing recorded yet: the draft must decline, even though a publishable
    # regret call is computable from the cache.
    path, note = content.coinflip_friday(season.league_id, twr.REPORT_WEEK - 1, 1)
    assert note == "gated"
    assert "run.week" in path.read_text(encoding="utf-8")

    # Record (as run.week would), then the draft quotes the ledger entry.
    from engine.ledger import ledger_path as lp
    calls = extract_published_calls(report)
    record_calls(lp(tmp_path / "processed", season.league_id), calls)
    path2, note2 = content.coinflip_friday(season.league_id, twr.REPORT_WEEK - 1, 1)
    text = path2.read_text(encoding="utf-8")
    regret_entry = next(c for c in calls if c.is_regret)
    assert "from ledger" in note2
    assert regret_entry.pick_name in text and f"{regret_entry.confidence:.0%}" in text


def test_batch_survives_corrupt_ledger(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: a corrupt shared ledger must not sink the batch."""
    import run.batch as batch
    season, raw, _ = _report_with_snapshot(tmp_path, week=twr.REPORT_WEEK - 1)
    monkeypatch.setattr(batch, "RAW_DIR", raw)
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    import engine.week_report as wr
    monkeypatch.setattr(wr, "PROCESSED_DIR", tmp_path / "processed")
    ledger_file = tmp_path / "processed" / "ledger" / season.league_id / "calls.jsonl"
    ledger_file.parent.mkdir(parents=True)
    ledger_file.write_text("not json at all\n", encoding="utf-8")

    rosters_file = raw / "league" / season.league_id / "rosters.json"
    rosters_file.write_text(json.dumps([
        {"roster_id": 1, "owner_id": "1"}, {"roster_id": 2, "owner_id": "2"},
    ]), encoding="utf-8")
    from run.registry import Subscriber
    subscriber = Subscriber(email="a@b.co", user_id="1",
                            league_id=season.league_id, rival_owner_id=None,
                            rival_roster_id=2, sleeper_username="fan_one")
    result = batch.run_subscriber(subscriber, twr.REPORT_WEEK - 1, twr._template())
    assert result.ok  # the report shipped
    assert "LEDGER RECORD FAILED" in result.detail  # and the failure is loud


def test_no_league_member_names_in_public_drafts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: manager handles must never reach public-bound drafts."""
    season, raw, _ = _report_with_snapshot(tmp_path, week=twr.REPORT_WEEK - 1)
    content = _patched_content(monkeypatch, tmp_path, raw)
    users = json.loads((raw / "league" / season.league_id / "users.json")
                       .read_text(encoding="utf-8"))
    forbidden = {u["display_name"] for u in users}
    forbidden |= {(u.get("metadata") or {}).get("team_name") or "" for u in users}
    forbidden.discard("")

    kit_path, _ = content.reply_kit(season.league_id, twr.REPORT_WEEK - 1, 1,
                                    "2026-09-10")
    hype_path, _ = content.hype_wednesday(season.league_id, twr.REPORT_WEEK - 1)
    for path in (kit_path, hype_path):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in text, f"{name!r} leaked into {path.name}"


def test_hype_draft_states_the_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    season, raw, _ = _report_with_snapshot(tmp_path)
    # Give the fixture league a real chase in the transaction log.
    league_dir = raw / "league" / season.league_id / "transactions"
    league_dir.mkdir(parents=True, exist_ok=True)
    (league_dir / f"week_{twr.REPORT_WEEK - 1:02d}.json").write_text(json.dumps([
        {"type": "waiver", "status": "complete", "settings": {"waiver_bid": 21},
         "adds": {"wr2": 2}, "roster_ids": [2], "leg": twr.REPORT_WEEK - 1},
        {"type": "waiver", "status": "failed", "settings": {"waiver_bid": 15},
         "adds": {"wr2": 1}, "roster_ids": [1], "leg": twr.REPORT_WEEK - 1},
    ]), encoding="utf-8")
    content = _patched_content(monkeypatch, tmp_path, raw)
    path, _ = content.hype_wednesday(season.league_id, twr.REPORT_WEEK)
    text = path.read_text(encoding="utf-8")
    assert "Deep Threat" in text            # wr2's name from the fixture
    assert "can't see yet" in text          # the usage gap is stated, not papered over
