"""Promise audit, info pages (INFO-*): the public pages say only what the
product does, and the live sample's season clock (site/week.json) says which
phase the season is in (D9), so no page links "this week's report" to a week
that is over or months away.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import render.live_sample as live
import render.report as rr
from run.solo import SeasonOver
from test_live_sample import _run, week  # noqa: F401 — the fixture week

SITE = Path(__file__).resolve().parent.parent / "site"
HOW = (SITE / "how-it-works.html").read_text(encoding="utf-8")
NOT_FOUND = (SITE / "404.html").read_text(encoding="utf-8")
FLAG = re.compile(r"^const CHECKOUT_OPEN = (true|false);", re.M)


# --------------------------------------------------------------------- #
# D15 / INFO-4 — the samples' and how-it-works' ask follows the landing
# --------------------------------------------------------------------- #

def test_how_it_works_checkout_flag_is_the_landings() -> None:
    landing = FLAG.search((SITE / "index.html").read_text(encoding="utf-8"))
    mine = FLAG.search(HOW)
    assert landing and mine and landing.group(1) == mine.group(1)
    # The static markup is the closed state (fail closed), like the landing's.
    for anchor in re.findall(r"<a [^>]*data-checkout-cta[^>]*>[^<]*</a>", HOW):
        assert 'href="index.html#watch-form"' in anchor
        assert "Tell me when it opens" in anchor


def test_the_sample_ask_follows_the_landing_flag(tmp_path, monkeypatch) -> None:
    landing = tmp_path / "index.html"
    monkeypatch.setattr(rr, "LANDING_PAGE", landing)
    assert "index.html#watch-form" in rr.sample_cta(), "absent landing reads closed"
    landing.write_text("<script>\nconst CHECKOUT_OPEN = false;\n</script>")
    assert rr.SAMPLE_CTA_CLOSED in rr.sample_cta()
    assert "join/index.html" not in rr.sample_cta()
    landing.write_text("<script>\nconst CHECKOUT_OPEN = true;\n</script>")
    assert rr.sample_cta() == f'<a class="btn" href="join/index.html">{rr.SAMPLE_CTA}</a>'


# --------------------------------------------------------------------- #
# INFO-99 / 100 / 117 — each banner and basis says what its page is
# --------------------------------------------------------------------- #

def _banner(meta: dict) -> str:
    base = {"season": "2024", "week": 10, "solo": True, "scoring": "PPR",
            "league_name": "Sample", "num_teams": 12,
            "generated_at": "2026-10-17T18:13:59+00:00"}
    return rr.header({**base, **meta})


def test_each_sample_banner_says_what_its_week_was_built_from() -> None:
    mid = _banner({"historical_demo": True})
    assert "from the box scores and injury report out before that week" in mid
    assert "that week's box scores" not in mid
    first = _banner({"historical_demo": True, "first_week_demo": True, "week": 1})
    assert "no injury report" in first and "no odds print" in first
    assert "box scores and injury report" not in first


def test_a_rebuild_after_kickoff_says_it_reads_tuesdays_information() -> None:
    tuesday = _banner({"live_demo": True, "week": 6})
    assert "exactly the way yours is built" in tuesday
    assert "Rebuilt every Tuesday of the season" in tuesday
    rebuilt = _banner({"live_demo": True, "week": 6, "rebuilt_after_kickoff": True})
    assert "exactly the way yours is built" not in rebuilt
    assert "the week 5 injury report" in rebuilt and "later" in rebuilt
    basis = "the week 5 injury report, the last complete one before this report goes out"
    assert "last complete one" in rr.availability_basis({"availability_as_of": basis})
    said = rr.availability_basis({"availability_as_of": basis,
                                  "rebuilt_after_kickoff": True})
    assert "last complete one" not in said and "later injury news" in said
    assert live._reworded({"x": ["Week 6 status not announced yet"]},
                          live.NOT_ANNOUNCED, live.NOT_READ) == \
        {"x": ["Week 6 status not read on this rebuild"]}


def test_the_join_promise_names_the_three_scoring_settings() -> None:
    assert "full PPR, half PPR or standard" in rr.JOIN_PROMISE
    assert "league's way" not in rr.JOIN_PROMISE
    assert "every Tuesday of the season" in rr.BRAND_LINE


# --------------------------------------------------------------------- #
# INFO-102 — the reserve list is the reason, before a bye
# --------------------------------------------------------------------- #

def test_an_absence_names_the_reserve_list_before_the_bye() -> None:
    class Players:
        def name(self, pid):
            return {"a": "Achane", "b": "Byeguy"}[pid]

    class Data:
        availability = type("A", (), {"statuses": {"a": {"team": "MIA"},
                                                   "b": {"team": "MIA"}},
                                      "bye_teams": frozenset({"MIA"})})()
        roster_out = {"a": "on injured reserve"}
        players = Players()

    assert live.absences(Data(), ("a", "b")) == [
        ("Achane", "on injured reserve"), ("Byeguy", "on bye")]


# --------------------------------------------------------------------- #
# D9 — the season clock's phases (writer)
# --------------------------------------------------------------------- #

def test_week_one_lands_on_the_first_tuesday_send_it_is_due() -> None:
    # Thursday-night opener, 8:20 PM ET = Fri 00:20 UTC: due Wed Sep 1, 00:20
    # UTC, so the Tuesday before (Aug 31) is too early and Sep 7 sends it.
    assert live.week_one_lands_on(datetime(2027, 9, 10, 0, 20, tzinfo=timezone.utc)) \
        == "2027-09-07"
    # Due that very Tuesday morning, before the last send: that Tuesday.
    assert live.week_one_lands_on(datetime(2027, 9, 16, 10, 0, tzinfo=timezone.utc)) \
        == "2027-09-07"
    # Due that Tuesday after the last send (16:17 UTC): a week later.
    assert live.week_one_lands_on(datetime(2027, 9, 16, 17, 0, tzinfo=timezone.utc)) \
        == "2027-09-14"


def test_the_preseason_clock_is_written_only_before_week_one_is_due(monkeypatch) -> None:
    import run.solo as solo
    kick = datetime(2027, 9, 10, 0, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(solo, "current_week", lambda *a, **k: 1)
    monkeypatch.setattr(solo, "last_week", lambda *a, **k: 18)
    monkeypatch.setattr(solo, "week_first_kickoff", lambda *a, **k: kick)
    monkeypatch.setattr(solo, "week_one_due", lambda *a, **k: False)
    now = datetime(2027, 5, 18, 13, 0, tzinfo=timezone.utc)
    clock = live.preseason_clock(Path("x"), "2027", now)
    assert clock == {**clock, "season": "2027", "week": 1, "last_week": 18,
                     "lands_on": "2027-09-07", "odds": 0, "closest_call": False,
                     "first_kickoff": "2027-09-10T00:20:00Z", "phase": "preseason"}
    monkeypatch.setattr(solo, "week_one_due", lambda *a, **k: True)
    assert live.preseason_clock(Path("x"), "2027", now) is None
    monkeypatch.setattr(solo, "week_one_due", lambda *a, **k: False)
    monkeypatch.setattr(solo, "current_week", lambda *a, **k: 6)
    assert live.preseason_clock(Path("x"), "2027", now) is None


def test_a_season_that_is_over_keeps_its_last_page_marked_as_the_last(
        tmp_path, monkeypatch, week) -> None:  # noqa: F811
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    before = json.loads(out.with_name("week.json").read_text())
    assert code == 0 and before["phase"] == "season"
    assert "THIS WEEK&#x27;S REPORT" in out.read_text() or \
        "THIS WEEK'S REPORT" in out.read_text()

    def over(*_a, **_k):
        raise SeasonOver("the 2024 season is over")
    monkeypatch.setattr(live, "build", over)
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    clock = json.loads(out.with_name("week.json").read_text())
    page = out.read_text(encoding="utf-8")
    assert code == 0 and clock["phase"] == "over"
    assert {k: clock[k] for k in ("season", "week", "last_week", "lands_on")} == \
        {k: before[k] for k in ("season", "week", "last_week", "lands_on")}
    assert clock["odds"] == 0 and clock["closest_call"] is False
    assert "THIS WEEK" not in page and "this week&#x27;s report for a sample" not in page
    assert "SEASON&#x27;S LAST REPORT" in page or "SEASON'S LAST REPORT" in page
    assert re.search(r'<meta property="og:title" content="[^"]*season&#x27;s last report">',
                     page)
    # Checkout is closed once the season is over (D9): no ask to join, and no
    # "first report the day you join" on the kept card.
    assert "join/index.html" not in re.sub(r"<script.*?</script>", "", page, flags=re.S)
    assert "Tell me when it opens" in page and "the day you join" not in page
    assert live.NEXT_SEASON.replace("'", "&#x27;") in page
    # Idempotent: a second offseason Tuesday leaves the page as it is.
    _run(tmp_path, monkeypatch, kicked_off=False)
    assert out.read_text(encoding="utf-8") == page


def test_a_derived_week_one_not_yet_due_is_never_published(
        tmp_path, monkeypatch, week) -> None:  # noqa: F811
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=False)
    rows = sorted(processed.rglob("calls.jsonl"))
    ledger = [p.read_text() for p in rows]

    def week_one(*_a, **_k):
        report = week()
        report["meta"]["week"] = 1
        return report
    clock = {"season": "2027", "week": 1, "last_week": 18, "lands_on": "2027-09-07",
             "built_at": None, "odds": 0, "closest_call": False,
             "first_kickoff": "2027-09-10T00:20:00Z", "phase": "preseason"}
    monkeypatch.setattr(live, "build", week_one)
    monkeypatch.setattr(live, "preseason_clock", lambda *a, **k: dict(clock))
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False)
    assert code == 0
    assert json.loads(out.with_name("week.json").read_text()) == clock
    assert [p.read_text() for p in sorted(processed.rglob("calls.jsonl"))] == ledger
    page = out.read_text(encoding="utf-8")
    assert "LAST REPORT" in page and live.NEXT_SEASON.replace("'", "&#x27;") not in page
    assert rr.sample_cta() in page, "preseason asks follow the landing's flag"


def test_a_withheld_closest_call_says_why_it_is_missing() -> None:
    for sentence in (live.AFTER_KICKOFF_CLOSEST, live.REBUILT_CLOSEST):
        assert sentence.startswith("This week's closest call isn't shown")
        assert "No closest call with odds" not in sentence
    report = {"lineup": [{"confidence": 0.6}, {"confidence": None}],
              "regret": {"confidence": None}}
    assert live.hold_closest(report, live.REBUILT_CLOSEST)["regret"] == \
        {"gate": live.REBUILT_CLOSEST}
    line = live.rebuilt_line(report, datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc))
    assert "1 of its 2 slots" in line and "match that record" in line


# --------------------------------------------------------------------- #
# D9 — the readers (how-it-works, 404), run under node
# --------------------------------------------------------------------- #

def _phase_js(page: str) -> str:
    start = page.index("function easternToday()")
    end = page.index("\n}\n", page.index("function weekPhase(")) + 3
    return page[start:end]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("page", [HOW, NOT_FOUND], ids=["how-it-works", "404"])
def test_the_readers_link_this_week_only_while_the_clock_is_current(page) -> None:
    today = date.today()
    future, past = f"{today.year + 1}-01-05", f"{today.year - 1}-01-05"
    cases = {
        "current": {"week": 6, "last_week": 18, "lands_on": future},
        "stale": {"week": 6, "last_week": 18, "lands_on": past},
        "lastover": {"week": 18, "last_week": 18, "lands_on": past},
        "over": {"week": 18, "last_week": 18, "lands_on": future, "phase": "over"},
        "pre": {"week": 1, "last_week": 18, "lands_on": future, "phase": "preseason"},
    }
    script = (_phase_js(page) + "\nconst cases = " + json.dumps(cases) + ";\n"
              "const out = {}; for (const k in cases) out[k] = weekPhase(cases[k]);\n"
              "console.log(JSON.stringify(out));")
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True,
                                    text=True, check=True).stdout)
    assert got["current"]["phase"] == "season" and got["current"]["current"]
    assert got["stale"]["phase"] == "season" and not got["stale"]["current"]
    assert got["lastover"]["phase"] == "over"
    assert got["over"]["phase"] == "over" and got["pre"]["phase"] == "preseason"
    for name in ("stale", "lastover", "over", "pre"):
        live_link = got[name]["phase"] == "season" and got[name]["current"]
        assert not live_link, name


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_how_it_works_closes_the_ask_from_the_last_weeks_first_kickoff() -> None:
    cases = {
        "last": {"week": 18, "last_week": 18, "lands_on": "2999-01-01",
                 "first_kickoff": "2000-01-01T00:00:00Z"},
        "notyet": {"week": 18, "last_week": 18, "lands_on": "2999-01-01",
                   "first_kickoff": "2999-01-01T00:00:00Z"},
        "mid": {"week": 6, "last_week": 18, "lands_on": "2999-01-01",
                "first_kickoff": "2000-01-01T00:00:00Z"},
        "over": {"week": 18, "last_week": 18, "lands_on": "2999-01-01", "phase": "over"},
        "pre": {"week": 1, "last_week": 18, "lands_on": "2999-01-01",
                "phase": "preseason", "first_kickoff": "2000-01-01T00:00:00Z"},
    }
    script = (_phase_js(HOW) + "\nconst cases = " + json.dumps(cases) + ";\n"
              "const out = {}; for (const k in cases) out[k] = weekPhase(cases[k]).closed;\n"
              "console.log(JSON.stringify(out));")
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True,
                                    text=True, check=True).stdout)
    assert got == {"last": True, "notyet": False, "mid": False, "over": True,
                   "pre": False}
    assert "if (clock.closed && CHECKOUT_OPEN) setCheckoutCta(false);" in HOW


# --------------------------------------------------------------------- #
# INFO-37/46 / D16 / D18 — the words
# --------------------------------------------------------------------- #

def test_the_info_pages_say_what_is_true() -> None:
    lp = (SITE / "league-pass.html").read_text(encoding="utf-8")
    assert "every team in your league" not in lp
    assert "up to 14 teams" in lp and "up to 14 teams" in HOW
    assert "You paste your roster once" not in HOW
    assert "ninety seconds" not in HOW
    for page in (HOW, NOT_FOUND, lp):
        assert "analysis, not betting picks" in page
        assert "analysis, not picks" not in page
