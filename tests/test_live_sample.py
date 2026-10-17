"""The live sample (render/live_sample.py): this week's public report, on the record.

site/this-week.html prints odds in public every week, the landing links it,
and the Tuesday post drafts quote it. These tests pin the four things that
make it honest rather than merely current: its odds are RECORDED where a
subscriber's would be (principle 2), a week already underway is never rebuilt
into new "predictions", a post may only quote what was recorded, and a thin
week says why in facts the build computed.

Everything runs on the fixture week from test_solo_run, offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import render.live_sample as live
from run.solo import load_week_data, report_for
from test_solo_run import OFFLINE, SEASON, WEEK, _cache, _spec


@pytest.fixture
def week(tmp_path, monkeypatch):
    """The fixture week's report, built exactly as build() builds the live
    sample's (live_demo, anonymised), with build() pointed at it."""
    data = load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE)

    def fake_build(*_a, **_k):
        report = report_for(_spec(), data, league_size=12)
        report["meta"].update(live_demo=True, anonymized_demo=True,
                              thin_week_note=None)
        return report
    monkeypatch.setattr(live, "build", fake_build)
    return fake_build


def _run(tmp_path, monkeypatch, *, kicked_off: bool, extra=()):
    monkeypatch.setattr("run.solo.week_has_kicked_off",
                        lambda *a, **k: kicked_off)
    out = tmp_path / "site" / "this-week.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    processed = tmp_path / "processed"
    code = live.main(["--out", str(out), "--processed-dir", str(processed), *extra])
    return code, out, processed


def _ledger(processed: Path) -> list[dict]:
    return [json.loads(line) for path in sorted(processed.rglob("calls.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_odds_the_page_prints_are_recorded_where_a_subscribers_would_be(
        tmp_path, monkeypatch, week) -> None:
    """G04, reproduced: the module said "Nothing is recorded — it is not a
    subscriber", while the page printed three odds every week (65% Shakir, 79%
    Kelce, 63% Odunze in Week 6), the landing linked it and the X drafts
    quoted it — and data/processed/ledger held no typed store at all, so not
    one of those public numbers could ever be graded. A build before kickoff
    now records every printed probability in the store a subscriber with this
    setup uses, and re-running records nothing twice (RULE L4)."""
    expected = sum(1 for s in week()["lineup"] if s.get("confidence") is not None)
    assert expected, "the fixture week prints no odds — the test would prove nothing"
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 0 and out.is_file()
    rows = _ledger(processed)
    assert len(rows) == expected
    assert {r["league_id"] for r in rows} == {f"typed-ppr-12-{SEASON}"}, \
        "not the store a 12-team PPR subscriber's calls go to"
    page_odds = {round(r["confidence"] * 100) for r in rows}
    assert all(f"{p}%" in out.read_text(encoding="utf-8") for p in page_odds)
    code, _, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 0 and len(_ledger(processed)) == expected, "recorded twice"


def test_a_week_that_has_kicked_off_is_not_rebuilt_and_force_records_nothing(
        tmp_path, monkeypatch, week) -> None:
    """A rebuild after Thursday night's kickoff would print "predictions" about
    a game underway, and could move odds already on the record. Refused, page
    untouched; --force rebuilds (a rendering fix) and records NOTHING."""
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=True)
    assert code == 0 and not out.exists() and not _ledger(processed)
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=True,
                                extra=("--force",))
    assert code == 0 and out.is_file()
    assert not _ledger(processed), "a forced rebuild after kickoff was recorded"
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=False,
                                extra=("--no-record",))
    assert code == 0 and not _ledger(processed), "a preview was recorded"


def test_odds_that_cannot_be_recorded_are_never_published(tmp_path, monkeypatch,
                                                          week, capsys) -> None:
    """The ledger is written FIRST: a store that cannot be written (here, a
    corrupt line — the public record must be fixed by hand, never skipped)
    leaves the previous page up and fails the run, rather than publishing
    odds that are on no record."""
    processed = tmp_path / "processed"
    store = processed / "ledger" / f"typed-ppr-12-{SEASON}" / "calls.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text("{not json\n", encoding="utf-8")
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 1 and not out.exists()
    assert "NOT published" in capsys.readouterr().err


def test_a_post_may_quote_only_a_recorded_number(tmp_path, week) -> None:
    """The drafted X posts (run/drops.py) build the sample again and quote its
    closest call. recorded_only() withholds every % that is not in the ledger
    at the same value — a rebuild after the record was made, or a week never
    recorded — and never adds or moves one."""
    report = week()
    processed = tmp_path / "processed"
    assert live.recorded_only(week(), processed)["regret"]["confidence"] is None
    assert all(s.get("confidence") is None
               for s in live.recorded_only(week(), processed)["lineup"])
    live.record(report, processed)
    kept = live.recorded_only(week(), processed)
    assert kept["regret"]["confidence"] == report["regret"]["confidence"]
    assert [s.get("confidence") for s in kept["lineup"]] == \
        [s.get("confidence") for s in report["lineup"]]
    moved = week()
    regret = moved["regret"]
    for slot in moved["lineup"]:
        if slot.get("player_id") == regret["start_id"] and slot.get("confidence"):
            slot["confidence"] = regret["confidence"] = slot["confidence"] + 0.01
    assert live.recorded_only(moved, processed)["regret"]["confidence"] is None, \
        "a number that differs from the recorded one was kept"


def test_a_thin_week_says_why_in_facts_the_build_computed() -> None:
    """BE-I8 / I17: the hero links this page, and a bye-heavy week opened on
    "Bench X — he can't play this week" three times with odds on 3 of 9 slots
    and nothing saying why. Below SHOWCASE_MIN_ODDS, with somebody actually
    missing, one line names who can't play and why (bye, injured reserve) and
    counts the slots with odds. A full week, or a thin one with nobody
    missing, says nothing — blaming byes there would be false."""
    lineup = [{"confidence": 0.6}, {"confidence": None}, {"confidence": None}]
    missing = [("Amon-Ra St. Brown", "on bye"), ("De'Von Achane", "on bye"),
               ("Travis Etienne", "on injured reserve")]
    line = live.thin_week_line({"lineup": lineup}, missing)
    assert line == ("Why this week is thin: 3 of this roster's players can't play — "
                    "Amon-Ra St. Brown and De'Von Achane (on bye); Travis Etienne "
                    "(on injured reserve) — and 1 of its 3 slots carry odds.")
    assert live.thin_week_line({"lineup": lineup}, []) is None
    full = [{"confidence": 0.6}] * live.SHOWCASE_MIN_ODDS
    assert live.thin_week_line({"lineup": full}, missing) is None
    page = ('<div class="report"><header><div class="regret-note" style="x">'
            "THIS WEEK'S REPORT — Week 6</div></header></div>")
    shown = live.with_thin_week(page, line)
    assert shown.index("THIS WEEK'S REPORT") < shown.index("Why this week is thin")
    assert "De&#x27;Von" in shown, "the line is escaped like every other value"
    assert live.with_thin_week(page, None) == page
    # The chrome the page renders today (render/report.py): the banner is the
    # first notice inside <main>. The anchor once matched only the old markup,
    # so the line fell to the top of the report, outside every landmark (axe
    # "region", found by the launch check's accessibility gate, Oct 16 2026).
    page = ('<div class="report"><header>…</header><main id="main"><div class="notice">'
            "<b>THIS WEEK'S REPORT</b> — Week 6</div><section>…</section></main></div>")
    shown = live.with_thin_week(page, line)
    main = shown.split('<main id="main">')[1]
    assert main.index("THIS WEEK'S REPORT") < main.index("Why this week is thin")


def test_the_share_card_names_the_week(tmp_path, monkeypatch, week) -> None:
    """GTM-9, reproduced: every link to this-week.html previewed as "a real
    weekly report" with a description of a past season, while the page was
    Week 6 of 2026 — the preview contradicted the page. og:title, og:description
    and description now name the week and count the odds the page shows."""
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False, extra=("--no-record",))
    page = out.read_text(encoding="utf-8")
    report = week()
    odds = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    assert (f'<meta property="og:title" content="Beat Your League — this week&#x27;s '
            f'report, Week {WEEK} of {SEASON}">') in page
    for name in ('property="og:description"', 'name="description"'):
        tag = page.split(f"<meta {name} content=\"", 1)[1].split('"', 1)[0]
        assert f"Week {WEEK} of the {SEASON}" in tag and f"odds on {odds} of" in tag
        assert "file" not in tag.lower()
    assert page.count('property="og:title"') == 1


def test_the_cron_runs_the_build_that_records() -> None:
    """The weekly cron's live-sample step runs the recording build (no
    --no-record, no --force), after the subscriber send and before the drafts,
    and its persist step commits the ledger the build wrote."""
    root = Path(__file__).resolve().parent.parent
    weekly = (root / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
    step = weekly.split("name: Publish this week's sample report", 1)[1].split("- name:", 1)[0]
    assert "-m render.live_sample" in step
    assert "--no-record" not in step and "--force" not in step
    assert weekly.index("-m run.tuesday") < weekly.index("-m render.live_sample") \
        < weekly.index("-m run.drops")
    persist = weekly.split("name: Persist the record", 1)[1].split("- name:", 1)[0]
    assert "data/processed/ledger" in persist
