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


def test_a_first_build_prints_only_the_odds_the_record_holds(
        tmp_path, monkeypatch, week) -> None:
    """G04-1, reproduced with the committed ledger and no week.json: the store
    already held this week's call ids at other odds (written by another
    writer — a subscriber's report in the same store, or a lost clock), so
    record() added 0 rows (record_calls keeps the first row per id), and the
    page still printed this build's 84% and 75% beside a ledger holding 83%
    and 81%, with week.json saying recorded. The page now prints through the
    record: it withholds what the ledger holds at another value, adds and
    moves nothing, and the clock counts only what is printed."""
    import copy
    report = week()
    other = copy.deepcopy(report)
    for slot in other["lineup"]:
        if slot.get("confidence") is not None:
            slot["confidence"] = round(min(0.97, slot["confidence"] + 0.04), 3)
    if (other.get("regret") or {}).get("confidence") is not None:
        other["regret"]["confidence"] = round(min(0.97, other["regret"]["confidence"] + 0.04), 3)
    processed = tmp_path / "processed"
    assert live.record(other, processed) > 0
    before = _ledger(processed)
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 0 and out.is_file()
    assert _ledger(processed) == before, "the record moved"
    page = out.read_text(encoding="utf-8")
    built = {round(s["confidence"] * 100) for s in report["lineup"]
             if s.get("confidence") is not None}
    held = {round(r["confidence"] * 100) for r in before}
    for pct in built - held:
        assert f">{pct}%<" not in page, f"{pct}% printed with {sorted(held)} on the record"
    clock = json.loads((out.parent / "week.json").read_text(encoding="utf-8"))
    assert clock["recorded"] is True and clock["odds"] == 0 and "closest" not in clock
    # And a build whose odds ARE the record keeps every one of them.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    code, out2, processed2 = _run(fresh, monkeypatch, kicked_off=False)
    printed = json.loads((out2.parent / "week.json").read_text(encoding="utf-8"))["odds"]
    odds = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    assert code == 0 and printed == odds == len(_ledger(processed2))


def test_the_published_report_is_saved_for_the_drafts_only_with_its_page(
        tmp_path, monkeypatch, week) -> None:
    """CRON-1: the drafts are written from the report the page was rendered
    from. A build that publishes saves exactly that report beside the ledger;
    a run that keeps the page (already recorded) or a week underway saves
    none, so run/drops.py keeps the drafts written with the published page."""
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=False)
    saved = live.published_report(processed)
    assert code == 0 and saved is not None
    assert saved["meta"]["week"] == week()["meta"]["week"]
    odds = sum(1 for s in saved["lineup"] if s.get("confidence") is not None)
    assert json.loads((out.parent / "week.json").read_text(encoding="utf-8"))["odds"] == odds
    (processed / live.PUBLISHED_REPORT_NAME).unlink()
    code, _, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 0 and live.published_report(processed) is None, "a kept page saved a report"
    code, _, _ = _run(tmp_path, monkeypatch, kicked_off=True, extra=("--force",))
    assert code == 0 and live.published_report(processed) is None, "a week underway saved one"


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
    """The drafted X posts (run/drops.py) quote the published page's closest
    call (CRON-1: its own report, never a second build). recorded_only() withholds every % that is not in the ledger
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
    and description now name the week and say what the page holds — never
    an odds count, which advertised the slots without one (launch review M7)."""
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False, extra=("--no-record",))
    page = out.read_text(encoding="utf-8")
    assert (f'<meta property="og:title" content="Beat Your League — this week&#x27;s '
            f'report, Week {WEEK} of {SEASON}">') in page
    for name in ('property="og:description"', 'name="description"'):
        tag = page.split(f"<meta {name} content=\"", 1)[1].split('"', 1)[0]
        assert f"Week {WEEK} of the {SEASON}" in tag and "every slot decided" in tag
        assert "odds on" not in tag
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


# --------------------------------------------------------------------- #
# OPS-R3 — a week is recorded once, by its first build before kickoff
# --------------------------------------------------------------------- #

import re  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from render.report import _pct  # noqa: E402

NOW = datetime(2026, 10, 17, 0, 3, tzinfo=timezone.utc)


def _odds(page: str) -> list[int]:
    """The percentages the lineup prints — card 01's odds column (contract C3;
    it was the call column's <b>NN%</b>)."""
    return [int(n) for n in re.findall(r'<span class="fpct">(\d+)%</span>', page)]


def test_a_week_is_recorded_once_by_its_first_build_before_kickoff(
        tmp_path, monkeypatch, week) -> None:
    """Reproduced (OPS-R3): the Tuesday cron builds the sample twice (12:17
    and the 16:17 retry) and GitHub's backups run late; with one market line
    moved in between, the second build recorded 2 NEW calls for the same 2
    slots (4 calls, Shakir-vs-Shaheed graded twice) and printed odds that
    were not the recorded ones. site/week.json now carries `recorded`, a
    later build before kickoff leaves the published page alone, and a forced
    one prints only what the record holds — and records nothing."""
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=False)
    first = _ledger(processed)
    published = out.read_text(encoding="utf-8")
    assert code == 0 and first
    assert json.loads(out.with_name("week.json").read_text())["recorded"] is True

    def moved(*_a, **_k):
        # The retry's inputs moved: every printed probability shifts a point.
        report = week()
        for slot in report["lineup"]:
            if slot.get("confidence") is not None:
                slot["confidence"] = round(slot["confidence"] + 0.01, 3)
        if report["regret"].get("confidence") is not None:
            report["regret"]["confidence"] = round(report["regret"]["confidence"] + 0.01, 3)
        return report
    monkeypatch.setattr(live, "build", moved)
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 0 and _ledger(processed) == first, "the retry recorded again"
    assert out.read_text(encoding="utf-8") == published, "the published page moved"
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False, extra=("--force",))
    assert code == 0 and _ledger(processed) == first
    assert _odds(out.read_text(encoding="utf-8")) == [], \
        "a forced rebuild printed odds that are not the recorded ones"
    assert json.loads(out.with_name("week.json").read_text())["recorded"] is True


# --------------------------------------------------------------------- #
# OPS-R11 / FUNNEL:F3 / COPY:F1 / G24 / R1 / SS2-D1 / BE2-D3 — after kickoff
# --------------------------------------------------------------------- #

def _rebuild_after_kickoff(tmp_path, monkeypatch, week, teams, starts):
    """--force after the week's first kickoff, at NOW, with the players'
    teams and the week's kickoffs under the test's control."""
    def build(*_a, context=None, **_k):
        report = week()
        if context is not None:
            context.update(teams=dict(teams), missing=[])
        return report
    monkeypatch.setattr(live, "build", build)
    monkeypatch.setattr(live, "_kickoffs", lambda season, wk: dict(starts))
    return _run(tmp_path, monkeypatch, kicked_off=True,
                extra=("--force", "--now", NOW.isoformat()))


def test_a_forced_rebuild_after_kickoff_prints_only_recorded_odds_on_games_still_to_play(
        tmp_path, monkeypatch, week) -> None:
    """Reproduced (COPY:F1, FUNNEL:F3, G24, R1, SS2-D1, BE2-D3, OPS-R11): the
    live sample was rebuilt with --force a day after Week 6 kicked off. It
    printed 64% and 63% that were on no record — one pair's Thursday half
    already final — under "Set this lineup — before this week's first
    kickoff", with "Rashid Shaheed (7.6) plays Thursday" in the future tense
    and nothing on the page saying the week had begun. A forced rebuild after
    kickoff now prints a % only when it is on the record AND both players'
    games are still to come, says when it was rebuilt and that the week had
    begun, gives its steps "for the games still to play", drops an if/then
    about a game underway, and records nothing."""
    report = week()
    _run(tmp_path, monkeypatch, kicked_off=False)              # Tuesday's record
    processed = tmp_path / "processed"
    recorded = _ledger(processed)
    called = [s for s in report["lineup"] if s.get("confidence") is not None]
    started = called[0]["player_id"]                           # his game is underway
    teams = {pid: "LAT" for pid in {str(s.get("player_id")) for s in report["lineup"]}
             | {str(s.get("alternative_id")) for s in report["lineup"]}}
    teams[started] = "THU"
    teams[str(report["pivots"][0]["about"])] = "THU"           # the if/then's game too
    starts = {"THU": NOW - timedelta(days=1), "LAT": NOW + timedelta(days=1)}
    code, out, _ = _rebuild_after_kickoff(tmp_path, monkeypatch, week, teams, starts)
    page = out.read_text(encoding="utf-8")
    assert code == 0 and _ledger(processed) == recorded, "a rebuild after kickoff recorded"
    expected = [_pct(s["confidence"]) for s in called if s["player_id"] != started]
    assert sorted(_odds(page)) == sorted(expected), \
        "a % printed beside a game already underway, or a recorded one was lost"
    assert "before this week&#x27;s first kickoff" not in page
    assert "before this week's first kickoff" not in page
    assert live.STILL_TO_PLAY in page
    # The notice under the banner: when, that the week had begun, what shows.
    notice = page.split("THIS WEEK", 1)[1].split("</div>", 2)[1]
    assert "after this week&#x27;s first kickoff" in notice
    assert "on the record before kickoff" in notice and "slots" in notice
    assert "If/Then" in page and live.AFTER_KICKOFF_PIVOTS.split(":")[0] in page
    clock = json.loads(out.with_name("week.json").read_text())
    assert clock["after_kickoff"] is True and clock["odds"] == len(expected)


def test_a_forced_rebuild_of_a_week_never_recorded_prints_no_odds(
        tmp_path, monkeypatch, week, capsys) -> None:
    """The Week 6 case exactly: nothing was ever recorded, so a rebuild after
    kickoff may print nothing — and the refusal without --force says what the
    record holds instead of asserting "its recorded odds stand"."""
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=True)
    assert code == 0 and "The record holds 0 of this week's odds" in capsys.readouterr().out
    report = week()
    teams = {str(s.get(k)): "LAT" for s in report["lineup"]
             for k in ("player_id", "alternative_id") if s.get(k)}
    code, out, processed = _rebuild_after_kickoff(
        tmp_path, monkeypatch, week, teams, {"LAT": NOW + timedelta(days=1)})
    page = out.read_text(encoding="utf-8")
    assert code == 0 and _odds(page) == [] and not _ledger(processed)
    assert live.AFTER_KICKOFF_CLOSEST in page.replace("&#x27;", "'")


def test_the_after_kickoff_page_withholds_but_never_adds_or_moves() -> None:
    """after_kickoff() is pure withholding: a % on a pair whose players are
    not BOTH still to come goes (an unknown team counts as not still to come
    — fail closed), a played game reads in the past tense, and nothing it
    keeps changes value."""
    report = {
        "meta": {"thin_week_note": "x"},
        "lineup": [
            {"slot": "WR", "player_id": "a", "alternative_id": "b", "confidence": 0.64},
            {"slot": "FLEX", "player_id": "c", "alternative_id": "d", "confidence": 0.63},
            {"slot": "TE", "player_id": "e", "alternative_id": "f", "confidence": 0.79}],
        "regret": {"slot": "FLEX", "start_id": "c", "over_id": "d", "confidence": 0.63},
        "checklist": [{"action": "Set this lineup", "detail": "",
                       "deadline": "before this week's first kickoff"}],
        "pivots": [{"about": "d", "condition": "D is out",
                    "action": "Start X. Rashid Shaheed (7.6) plays Thursday, before "
                              "D's status is known."},
                   {"about": "a", "condition": "A is out",
                    "action": "Rashid Shaheed (7.6) plays Thursday."}]}
    upcoming, played = live.kickoff_split(
        {"a": "LAT", "b": "LAT", "c": "LAT", "d": "THU", "e": "LAT", "f": "UNK",
         "s": "THU"},
        {"LAT": NOW + timedelta(hours=5), "THU": NOW - timedelta(hours=30)}, NOW)
    assert upcoming == {"a", "b", "c", "e"} and played == {"d", "s"}, \
        "a player whose game cannot be told was counted as still to come"
    out = live.after_kickoff(report, upcoming, played, {"s": "Rashid Shaheed"})
    assert [s["confidence"] for s in out["lineup"]] == [0.64, None, None]
    assert out["regret"] == {"gate": live.AFTER_KICKOFF_CLOSEST}
    assert out["checklist"][0]["deadline"] == live.STILL_TO_PLAY
    [plan] = out["pivots"]
    assert plan["about"] == "a" and plan["action"] == "Rashid Shaheed (7.6) played Thursday."
    assert live._past_tense("Rashid Shaheed (7.6) plays Thursday, before C's status is known.",
                            ["Rashid Shaheed"]) == \
        "Rashid Shaheed (7.6) played Thursday, before C's status was known."
    assert out["meta"]["rebuilt_after_kickoff"] and out["meta"]["thin_week_note"] is None
    assert live.share_text({"meta": {"week": 6, "season": "2026",
                                     "rebuilt_after_kickoff": True},
                            "lineup": out["lineup"]})[1].endswith(
        "Rebuilt after this week's first kickoff.")


def test_the_clock_says_the_page_is_in_the_card_layout_only_when_it_is(
        tmp_path, monkeypatch, week) -> None:
    """Review BUYER-1/SLEEK-1/F7: three links promote "this week's real
    report", and the page they opened (built Oct 20) was in the layout from
    before the card stack — game plan first, the tape table, a slanted gold
    button — right under a phone showing the cards. restamp_style leaves such
    a page alone on purpose (restyling it would need a rebuild, and a rebuild
    after kickoff drops odds), so the links wait for a page in the card
    layout: the build writes `cards` beside it, only when the page it wrote
    carries the cards, and an older clock has no such field."""
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 0 and 'class="card"' in out.read_text(encoding="utf-8")
    clock = json.loads((out.parent / "week.json").read_text(encoding="utf-8"))
    assert clock["cards"] is True
    plain = tmp_path / "plain.json"
    live.write_week_json(week(), plain)
    assert "cards" not in json.loads(plain.read_text(encoding="utf-8"))
