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
    assert "Check your connection" in got[2] and got[2] == got[3]
    code = _js_code(JOIN)
    # The free report reads the Worker's own reason first (refusedFrom wraps
    # refusedBy): a 403 "free reports are not open" is not a typo.
    assert (code.count("throw refusedBy(response)")
            + code.count("throw await refusedFrom(response)")) == 4
    assert 'throw new Error("rejected")' not in code


def test_an_update_from_a_report_names_its_subscription() -> None:
    """D13: the update link's &o=<tag> is posted as ``replaces`` and the Worker
    keeps it on an update_request (dropping a malformed one, never the row).
    The tag is 12 hex (run/updates.py ORIGIN_TAG_LENGTH): this test once
    pinned 10, the raw slug's length, and with it APPSEC-5 — every real
    link's tag dropped."""
    assert 'QUERY.get("o")' in JOIN
    post = _js_function(JOIN, "submitUpdate")
    assert 'kind: "update_request", email: email, ref: ref, replaces: UPDATE_ORIGIN' in post
    got = _node(SANITIZE + "\nconsole.log(JSON.stringify(['0123456789ab', '0123456789', 'nope']"
                ".map((r) => sanitize({kind: 'update_request', email: 'a@b.co', ref: 'abc',"
                " replaces: r}))));")
    assert got[0] == {"kind": "update_request", "email": "a@b.co", "ref": "abc",
                      "replaces": "0123456789ab"}
    assert got[1] == got[2] == {"kind": "update_request", "email": "a@b.co", "ref": "abc"}


PHASE = "\n".join(_js_function(JOIN, f) for f in
                  ("firstReportTiming", "etDayEnd", "seasonClosed", "trialTiming"))
WEEK = {"week": 6, "last_week": 18, "lands_on": "2026-10-21",
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


def test_a_monday_night_buyer_is_not_promised_a_report_today() -> None:
    """PUR-2, reproduced: a purchase at 01:55Z Nov 3 (Mon 8:55 PM ET), week.json
    on week 8 with lands_on Nov 4. The page said "Your first report lands
    today", but current_week had moved to 9 at 00:00Z, so the first report was
    week 9's early look, held by the intake until Monday night's box score
    landed ("CHI@SEA is not over"): only the welcome went out that night. From
    00:00 UTC the day before lands_on until 16:00 UTC that day the page names
    the wait instead; outside it, and in the season's last week, nothing
    changes. DES-10 rides along: the date drops its weekday, so the line no
    longer reads "your Wednesday report from Wed, Nov 4"."""
    wk8 = {**WEEK, "week": 8, "lands_on": "2026-11-04", "first_kickoff": "2026-10-30T00:15:00Z"}
    last = {**wk8, "week": 18}
    got = _node(PHASE + "\nconsole.log(JSON.stringify(" + json.dumps([
        [wk8, "2026-11-02T23:59:00Z"],     # Monday 6:59 PM ET: the roster report today
        [wk8, "2026-11-03T01:55:00Z"],     # Monday 8:55 PM ET
        [wk8, "2026-11-03T09:00:00Z"],     # Tuesday 4 AM ET, box score maybe not in
        [wk8, "2026-11-03T16:00:00Z"],     # Tuesday 11 AM ET: today again
        [last, "2026-11-03T01:55:00Z"],    # the last week: no next week to wait for
    ]) + ".map(([w, now]) => firstReportTiming(w, new Date(now)))));")
    assert [g and g["when"] for g in got] == ["after", "overnight", "overnight", "after", None]
    assert got[0]["tuesday"] == "Nov 4"
    draw = _js_function(JOIN, "drawFirst")
    night = prose(draw.split('FIRST.when === "overnight"')[1].split("} else if")[0])
    assert "once Monday night's game is scored" in night and "usually by Tuesday morning" in night
    assert "today" not in night
    after = prose(draw.split('FIRST.when === "after"')[1].split("} else {")[0])
    assert "then a new one every Wednesday from" in after
    assert "your Wednesday report from" not in after


PRESEASON = {"season": "2026", "week": 1, "last_week": 18, "lands_on": "2026-09-09",
             "first_kickoff": "2026-09-10T00:20:00Z", "phase": "preseason"}


def test_no_monday_night_wait_before_the_season_has_a_game() -> None:
    """PUR-2's window, reproduced on the preseason clock (render/live_sample
    preseason_clock: week 1, lands_on Week 1's own report day): at 01:00Z Sep
    8 (Labor Day, 9 PM ET) the window opened and the page said "This week's
    report lands once Monday night's game is scored" with no game anywhere.
    A seat claim shows that line in the preseason (canStartToday is the form
    endpoint). The wait is named only once the week has kicked off; before
    that the first report is the roster report, today."""
    got = _node(PHASE + "\nconsole.log(JSON.stringify(" + json.dumps([
        [PRESEASON, "2026-09-08T01:00:00Z"],
        [{**PRESEASON, "phase": "season"}, "2026-09-08T01:00:00Z"],
    ]) + ".map(([w, now]) => firstReportTiming(w, new Date(now)))));")
    assert [g and g["when"] for g in got] == ["after", "after"]


def test_the_thank_you_page_waits_for_monday_night_with_the_join_page() -> None:
    """PUR-2's other half, reproduced on the page a Monday-night buyer lands on
    after Stripe: join had come to say "lands once Monday night's game is
    scored, usually by Tuesday morning", and then thanks.html said "Your first
    report is on its way. It usually lands within the hour" and, after that
    hour, to check the spam folder, for a report the intake would not build
    until the box score was in. Inside the same window as join's "overnight"
    (checked against firstReportTiming on the same times) it says the wait;
    outside it the static words stand."""
    fn = _js_function(THANKS, "mondayNight")
    wk8 = {**WEEK, "week": 8, "lands_on": "2026-11-04", "first_kickoff": "2026-10-30T00:15:00Z"}
    last = {**wk8, "week": 18}
    cases = [[wk8, "2026-11-02T23:59:00Z"], [wk8, "2026-11-03T01:55:00Z"],
             [wk8, "2026-11-03T09:00:00Z"], [wk8, "2026-11-03T16:00:00Z"],
             [last, "2026-11-03T01:55:00Z"], [{**wk8, "first_kickoff": "2026-11-05T01:15:00Z"},
                                              "2026-11-03T01:55:00Z"],
             [PRESEASON, "2026-09-08T01:00:00Z"]]
    got = _node(fn + "\n" + PHASE + "\nconsole.log(JSON.stringify(" + json.dumps(cases) +
                ".map(([w, now]) => { const t = firstReportTiming(w, new Date(now));"
                " return [mondayNight(w, Date.parse(now), Date.parse(w.first_kickoff)),"
                " Boolean(t && t.when === 'overnight')]; })));")
    assert [g[0] for g in got] == [False, True, True, False, False, False, False]
    assert [g[0] for g in got] == [g[1] for g in got], "thanks.html and join disagree"
    handler = _js_code(THANKS).split("mondayNight(w, Date.now(), kick)) {")[1].split("} else if")[0]
    words = " ".join(s for s in re.findall(r'"((?:[^"\\]|\\.)*)"',
                                           re.sub(r'"\s*\+\s*"', "", handler))
                     if " " in s and not s.startswith("#"))   # sentences, not selectors
    assert "Your first report lands once Monday night's game is scored" in words
    assert "usually by Tuesday morning" in words
    assert "within the hour" not in words and "today" not in words.lower()
    assert 'getElementById("first-note").replaceChildren' in handler
    # The static first screen keeps its pinned words for every other hour.
    assert "usually lands within the hour" in prose(THANKS)


def test_the_landing_waits_for_monday_night_with_join_and_thanks() -> None:
    """SITE-3, reproduced at 09:20 UTC Tue Nov 3 2026: thanks.html and join/
    said the first report waits for Monday night's box score, and at the same
    moment the landing's price card and FAQ said "Your first report usually
    lands within the hour." The landing carries thanks.html's mondayNight()
    to the letter and, inside its window, rewrites both sentences in
    thanks.html's words. The static text (and the structured data) stays the
    general case."""
    landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    # Inside the clock's IIFE (the tests that run it extract only that), so
    # compared line by line without its indent.
    start = landing.index("function mondayNight(")
    nested = landing[start:landing.index("\n    }\n", start) + 6]
    flat = lambda src: [line.strip() for line in src.strip().splitlines()]  # noqa: E731
    assert flat(nested) == flat(_js_function(THANKS, "mondayNight"))
    wait = ("Your first report lands once Monday night's game is scored, "
            "usually by Tuesday morning.")
    code = re.sub(r'"\s*\+\s*"', "", _js_code(landing))
    handler = code.split('mondayNight(w, Date.now(), Date.parse(w.first_kickoff || ""))) {')[1]
    handler = handler.split("\n        }\n")[0]
    assert '["first-lands", "faq-first-lands"]' in handler and f'"{wait}"' in handler
    # Site review #7: the open line and the closer said "today" in the same
    # window. Both are rewritten there too (test_final_pages runs it).
    assert 'getElementById("open-line")' in handler and '" Set up now."' in handler
    assert 'getElementById("closer-head")' in handler and handler.count(f'"{wait}"') == 2
    assert wait in re.sub(r'"\s*\+\s*"', "", _js_code(THANKS))
    for anchor in ('<li id="first-lands">Your first report usually lands within the hour.</li>',
                   '<span id="faq-first-lands">Your first report usually lands within the '
                   'hour.</span>'):
        assert anchor in landing, anchor
    # The window is join's "overnight", as the thanks test checks: Monday 23:59
    # UTC no, Tuesday 01:55 and 09:00 yes, Tuesday 16:00 no.
    wk8 = {**WEEK, "week": 8, "lands_on": "2026-11-04", "first_kickoff": "2026-10-30T00:15:00Z"}
    got = _node(nested + "\nconsole.log(JSON.stringify(" +
                json.dumps(["2026-11-02T23:59:00Z", "2026-11-03T01:55:00Z",
                            "2026-11-03T09:00:00Z", "2026-11-03T16:00:00Z"]) +
                ".map((now) => mondayNight(" + json.dumps(wk8) +
                ", Date.parse(now), Date.parse('2026-10-30T00:15:00Z')))));")
    assert got == [False, True, True, False]


def test_the_season_closes_when_no_weekly_report_is_left() -> None:
    """D9: "over", the last week from its first kickoff, and past the last
    week's lands_on (ET) all close; preseason is open for checkout and closed
    for the free report, which is never mailed for a request before the
    season's first game (run/trials.py)."""
    last = {**WEEK, "week": 18, "lands_on": "2027-01-13", "first_kickoff": "2027-01-09T21:30:00Z"}
    no_kick = {k: v for k, v in last.items() if k != "first_kickoff"}
    pre = {"phase": "preseason", "season": "2027", "week": 1, "last_week": 18,
           "lands_on": "2027-09-08", "first_kickoff": "2027-09-10T00:20:00Z"}
    wk1 = {**WEEK, "week": 1, "lands_on": "2026-09-16", "first_kickoff": "2026-09-11T00:20:00Z"}
    got = _phase([
        [{**WEEK, "phase": "over"}, "2026-10-15T12:00:00Z"],
        [last, "2027-01-09T20:00:00Z"],
        [last, "2027-01-09T21:31:00Z"],
        [no_kick, "2027-01-14T04:59:00Z"],          # 11:59 PM ET on lands_on
        [no_kick, "2027-01-14T05:01:00Z"],          # the next ET day
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
    # Updates and adds never read the season's clock; the Trade Check reads it
    # only for its note's wait, and returns before the season can close anything.
    code = _js_code(JOIN)
    assert "if ((UPDATE_MODE && !TRADE_MODE) || !window.fetch) return;" in code
    week = code.split("if ((UPDATE_MODE && !TRADE_MODE) || !window.fetch) return;")[1]
    assert week.index("if (TRADE_MODE) { drawTradeNote(w, now); return; }") < \
        week.index("if (TRY_MODE) {") < week.index("FIRST = seasonClosed(w, now)")


def test_the_free_report_names_the_report_it_will_send() -> None:
    """JOIN-112/113/115: before kickoff "this week's", after it "next week's",
    with no clock "your next weekly report" — and a request is "in", not on
    its way, because the intake decides."""
    draw = _js_function(JOIN, "drawTrial")
    for words in ("this week's report", "next week's report, by ", "your next weekly report"):
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
    assert "billing stops on its own" in prose(code)
    assert "it won't renew after Week 16's report goes out" in prose(code)
    assert "billing stops on its own when the season ends" not in prose(code)
    # The short form sells; the late-send clause lives where the refund is defined.
    assert "a week after" in prose((ROOT / "site" / "terms.html").read_text(encoding="utf-8"))
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
    assert "We do not ask why" not in thanks and "stop on its own" in thanks
    assert "Bought a pass for more than one league?" in thanks
    assert "everyone who claims a seat gets their own lineup report" in thanks
    assert 'fetch("week.json"' in THANKS
    assert re.search(r"usually (?:set up|applied) within the hour", prose(CONFIRM))
