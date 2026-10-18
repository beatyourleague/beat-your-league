"""The join funnel's promises, held to what the product does (promise audit,
Oct 18 2026 — the JOIN items). Each test names the item it pins."""
from __future__ import annotations

import json
import re
from pathlib import Path

from test_site import CONFIRM, JOIN, _js_code, _js_function, _node, prose

ROOT = Path(__file__).resolve().parent.parent
WORKER = (ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
THANKS = (ROOT / "site" / "thanks.html").read_text(encoding="utf-8")
SANITIZE = WORKER[WORKER.index("const EMAIL"):WORKER.index("// ── the scheduler")]

ODD_BUT_REAL = ["o'brien@gmail.com", "josé@example.com", "sub@example.c"]


def test_one_address_rule_on_the_page_the_worker_and_the_intake() -> None:
    """D14 / JOIN-129, JOIN-138: the Worker answered 400 to addresses the page
    passed and a subscription could hold, and the page called it a connection
    problem, so retrying could never work. One rule everywhere now."""
    from run import rosters, trials, updates
    rule = rosters._EMAIL_RE.pattern
    assert updates._EMAIL_RE.pattern == trials._EMAIL_RE.pattern == rule
    assert f"const EMAIL = /{rule}/;" in WORKER
    assert f"const EMAIL_RE = /{rule}/;" in JOIN
    for address in ODD_BUT_REAL:
        assert rosters._EMAIL_RE.match(address) and updates._EMAIL_RE.match(address)
    got = _node(SANITIZE + "\nconsole.log(JSON.stringify(" + json.dumps(ODD_BUT_REAL) +
                ".map((email) => Boolean(sanitize({kind: 'trial', email, ref: 'abc'})))));")
    assert got == [True, True, True]


def test_a_refused_row_is_not_blamed_on_the_connection() -> None:
    """D14: a 4xx says the address couldn't be accepted; only a failure to reach
    the Worker (or its 5xx) says check your connection."""
    src = _js_function(JOIN, "refusedBy") + _js_function(JOIN, "notSentWords")
    got = _node(src + "\nconsole.log(JSON.stringify([400, 413, 500].map((status) =>"
                " notSentWords(refusedBy({status}))).concat([notSentWords(new Error('x'))])));")
    assert got[0] == got[1] and "couldn't accept that address" in got[0]
    assert "check your connection" in got[2] and got[2] == got[3]
    code = _js_code(JOIN)
    assert code.count("throw refusedBy(response)") == 4
    assert 'throw new Error("rejected")' not in code


def test_an_update_from_a_report_names_its_subscription() -> None:
    """D13: the update link's &o=<slug> is posted as ``replaces`` and the Worker
    keeps it on an update_request (dropping a malformed one, never the row)."""
    assert 'QUERY.get("o")' in JOIN
    post = _js_function(JOIN, "submitUpdate")
    assert 'kind: "update_request", email: email, ref: ref, replaces: UPDATE_ORIGIN' in post
    got = _node(SANITIZE + "\nconsole.log(JSON.stringify(['0123456789', 'nope'].map((r) =>"
                " sanitize({kind: 'update_request', email: 'a@b.co', ref: 'abc', replaces: r}))));")
    assert got[0] == {"kind": "update_request", "email": "a@b.co", "ref": "abc",
                      "replaces": "0123456789"}
    assert got[1] == {"kind": "update_request", "email": "a@b.co", "ref": "abc"}


PHASE = "\n".join(_js_function(JOIN, f) for f in
                  ("firstReportTiming", "etDayEnd", "seasonClosed", "trialTiming"))
WEEK = {"week": 6, "last_week": 18, "lands_on": "2026-10-20",
        "first_kickoff": "2026-10-16T00:15:00Z"}


def _phase(cases: list) -> list:
    return _node(PHASE + "\nconsole.log(JSON.stringify(" + json.dumps(cases) +
                 ".map(([w, now]) => { const d = new Date(now); const t = trialTiming(w, d);"
                 " const f = firstReportTiming(w, d);"
                 " return [seasonClosed(w, d), t ? t.when : null, f ? f.when : null]; })));")


def test_today_switches_off_an_hourly_run_before_kickoff() -> None:
    """JOIN-16/21: the intake runs hourly, so "this week's report today" stops
    75 minutes before the first kickoff; inside that window the page names
    neither report."""
    got = _phase([[WEEK, "2026-10-15T22:59:00Z"], [WEEK, "2026-10-15T23:30:00Z"],
                  [WEEK, "2026-10-16T00:20:00Z"]])
    assert got == [[False, "this", "before"], [False, None, None], [False, "next", "after"]]


def test_the_season_closes_when_no_weekly_report_is_left() -> None:
    """D9: "over", the last week from its first kickoff, and past the last
    week's lands_on (ET) all close; preseason is open for checkout and closed
    for the free report, which is never mailed for a request before the
    season's first game (run/trials.py)."""
    last = {**WEEK, "week": 18, "lands_on": "2027-01-12", "first_kickoff": "2027-01-09T21:30:00Z"}
    no_kick = {k: v for k, v in last.items() if k != "first_kickoff"}
    pre = {"phase": "preseason", "season": "2027", "week": 1, "last_week": 18,
           "lands_on": "2027-09-07", "first_kickoff": "2027-09-10T00:20:00Z"}
    wk1 = {**WEEK, "week": 1, "lands_on": "2026-09-15", "first_kickoff": "2026-09-11T00:20:00Z"}
    got = _phase([
        [{**WEEK, "phase": "over"}, "2026-10-15T12:00:00Z"],
        [last, "2027-01-09T20:00:00Z"],
        [last, "2027-01-09T21:31:00Z"],
        [no_kick, "2027-01-13T04:59:00Z"],          # 11:59 PM ET on lands_on
        [no_kick, "2027-01-13T05:01:00Z"],          # the next ET day
        [pre, "2027-08-20T12:00:00Z"],
        [wk1, "2026-09-10T12:00:00Z"],
        [wk1, "2026-09-11T01:00:00Z"],
        [None, "2026-10-15T12:00:00Z"],
    ])
    assert got == [
        [True, "over", "before"],
        [False, "this", "before"],
        [True, "over", None],
        [False, None, None],
        [True, "over", None],
        [False, "pre", "after"],
        [False, "pre", "after"],
        [False, "next", "after"],
        [False, None, None],
    ]
    # A closed season closes every way in: the button, the chip, the plan
    # switch, a seat claim and the free report.
    assert 'if (FIRST && FIRST.when === "over") return false;' in _js_function(JOIN, "canStartToday")
    assert "if (seasonOver()) return false;" in _js_function(JOIN, "switchesPlan")
    assert "if (seasonOver()) {" in _js_function(JOIN, "submitSeat")
    assert 'TRIAL.when === "over" || TRIAL.when === "pre"' in _js_function(JOIN, "submitTrial")
    handler = _js_code(JOIN).split('$("form-email").addEventListener("submit"')[1]
    assert 'const link = seasonOver() ? "" :' in handler
    assert "if (UPDATE_MODE || !window.fetch) return;" in _js_code(JOIN)


def test_the_free_report_names_the_report_it_will_send() -> None:
    """JOIN-112/113/115: before kickoff "this week's", after it "next week's",
    with no clock "your next weekly report" — and a request is "in", not on
    its way, because the intake decides."""
    draw = _js_function(JOIN, "drawTrial")
    for words in ("this week's report", "next week's report, on ", "your next weekly report"):
        assert words in draw
    assert "Your free report is on its way" not in JOIN
    assert '"Your request is in."' in _js_function(JOIN, "submitTrial")


def test_a_count_is_not_a_lineup() -> None:
    """JOIN-45: fifteen running backs, or no kicker under "Starts a K", read
    "Looks right". The list is seated by position and an empty spot is named
    (a warning; step 3 stays open)."""
    src = "const SLOT_TAKES = { FLEX: ['RB', 'WR', 'TE'], SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'] };\n" + \
        _js_function(JOIN, "emptySpots") + _js_function(JOIN, "emptySpotWords")
    std = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    full = ["QB", "RB", "RB", "FB", "WR", "WR", "WR", "TE", "K", "DEF"]
    cases = [[std, full], [std, ["RB"] * 15], [std, [p for p in full if p != "K"]],
             [std + ["SUPER_FLEX"], full + ["QB"]], [std + ["SUPER_FLEX"], full]]
    got = _node(src + "\nconsole.log(JSON.stringify(" + json.dumps(cases) +
                ".map(([s, p]) => emptySpotWords(emptySpots(s, p)))));")
    assert got == ["", "QB, 2 WR spots, TE, K or DEF", "K", "", ""]
    draw = _js_function(JOIN, "draw")
    assert "nobody here can start at" in draw and "state.ready = !problem;" in draw
    assert draw.index("state.ready = !problem;") < draw.index("emptySpots(")


def test_a_roster_changed_after_listing_can_be_listed_again() -> None:
    """JOIN-136/137: the launch email brings back the roster the list kept, so a
    changed roster re-opens the button instead of keeping the old one."""
    relist = _js_function(JOIN, "relistIfChanged")
    assert "now === state.listedRef" in relist and "state.listed = false;" in relist
    assert "state.listedRef = tagged;" in JOIN
    assert "relistIfChanged();" in _js_function(JOIN, "draw")
    apply = _js_function(JOIN, "applyPlan")
    assert apply.index("relistIfChanged();") < apply.index("monthlyPlan()")


def test_the_join_words_describe_the_product_after_the_decisions() -> None:
    """D1, D10, D13, D16, D18, D19 and the JOIN word items."""
    code = re.sub(r'"\s*\+\s*"', "", _js_code(JOIN))   # concatenated strings, joined
    assert "billing stops on its own after the season's last weekly report" in prose(code)
    assert "your last charge is the month that report falls in" in prose(code)
    assert "billing stops on its own when the season ends" not in prose(code)
    assert code.count("(or a week after your last report, if the season ends first)") >= 2
    assert "each manager claims their seat from it once" in prose(code)
    assert "up to 14 teams" in prose(code) and "Covers every manager" not in code
    assert "Seat already paid" not in code and "Claim my seat — already paid" not in code
    assert "8, 10, 12 or 14 teams" in prose(JOIN)
    assert 'value="wr3">Three WR</label>' in JOIN
    for page in (JOIN, CONFIRM, THANKS):
        assert "analysis, not betting picks" in prose(page)
        assert "analysis, not picks" not in prose(page)
    assert "by Friday night (ET)" in prose(CONFIRM) and "by Friday night (ET)" in prose(THANKS)
    thanks = prose(THANKS)
    assert "usually lands within the hour" in thanks and "allow up to an hour" not in thanks
    assert "We do not ask why" not in thanks and "shows only the newest" in thanks
    assert "Bought a pass for more than one league?" in thanks
    assert "everyone who claims a seat gets their own lineup report" in thanks
    assert 'fetch("week.json"' in THANKS
    assert re.search(r"usually (?:set up|applied) within the hour", prose(CONFIRM))
