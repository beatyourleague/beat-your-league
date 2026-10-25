"""`make launch-check` (run/launch_check.py): the gates catch what they claim to.

A readiness check that reports PASS over a broken funnel is worse than none,
because it is the thing the owner reads on launch morning. Each test copies
site/ to a temp folder, breaks one thing on purpose, and requires the gate
that owns it to say so — then requires the real tree to raise no FAIL.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import run.launch_check as lc

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def site(tmp_path, monkeypatch):
    copy = tmp_path / "site"
    shutil.copytree(REPO / "site", copy)
    monkeypatch.setattr(lc, "SITE", copy)
    return copy


def _status(gates, name_part):
    hits = [g for g in gates if name_part.lower() in g.name.lower()]
    assert hits, f"no gate named like {name_part!r}: {[g.name for g in gates]}"
    return hits[0].status


def test_selling_a_closed_checkout_fails(site) -> None:
    page = site / "index.html"
    page.write_text(page.read_text().replace("const CHECKOUT_OPEN = false;",
                                             "const CHECKOUT_OPEN = true;"))
    gates = lc.check_funnel_config()
    assert _status(gates, "never sells a checkout") == "FAIL"
    assert _status(gates, "agree on whether checkout is open") == "FAIL"


def test_a_free_report_button_with_nowhere_to_post_fails(site) -> None:
    page = site / "index.html"
    page.write_text(page.read_text().replace("const TRIAL_OPEN = false;",
                                             "const TRIAL_OPEN = true;"))
    assert _status(lc.check_funnel_config(), "free-report button") == "FAIL"


def test_a_banned_word_or_betting_word_on_a_selling_page_fails(site) -> None:
    page = site / "league-pass.html"
    page.write_text(page.read_text().replace("<h2>Fair play</h2>",
                                             "<h2>Fair play, proven</h2><p>no sportsbook</p>"))
    gates = lc.check_selling_copy()
    assert _status(gates, "banned claim words") == "FAIL"
    assert _status(gates, "betting language") == "FAIL"


def test_a_one_click_cancel_claim_in_the_terms_fails(site) -> None:
    """Reproduction (launch audit C2, Oct 15 2026): terms §3 still said
    "cancelling takes one / click from your billing page" — hand-wrapped
    across two lines — after §4 and every other surface had moved to the real
    flow (an emailed link, about a minute). The gate read only the selling
    pages, so the retired claim survived in the operative contract."""
    page = site / "terms.html"
    text = page.read_text(encoding="utf-8")
    fixed = "you can cancel\n      yourself from your billing page in about a minute (section 4)."
    assert fixed in text
    page.write_text(text.replace(
        fixed, "cancelling takes one\n      click from your billing page."))
    assert _status(lc.check_selling_copy(), "audit retired") == "FAIL"
    # Either order, any phrasing in between, and on the privacy page too.
    page.write_text(text)
    privacy = site / "privacy.html"
    privacy.write_text(privacy.read_text(encoding="utf-8").replace(
        "</main>", "<p>One-click   cancelling, whenever you like.</p></main>"))
    assert _status(lc.check_selling_copy(), "audit retired") == "FAIL"


def test_one_click_that_is_not_about_cancelling_is_not_a_retired_claim(site) -> None:
    """"Our terms are always one click away" is true and says nothing about
    leaving; the gate is about the cancel flow, not the phrase."""
    page = site / "terms.html"
    page.write_text(page.read_text(encoding="utf-8").replace(
        "</main>", "<p>This page is always one click away.</p></main>"))
    assert _status(lc.check_selling_copy(), "audit retired") == "PASS"


def test_a_broken_link_and_a_bad_anchor_fail(site) -> None:
    page = site / "how-it-works.html"
    page.write_text(page.read_text().replace(
        "</main>", '<a href="nowhere.html">x</a><a href="terms.html#no-such-id">y</a></main>', 1))
    gate = lc.check_links()[0]
    assert gate.status == "FAIL"
    assert "nowhere.html" in gate.detail and "no-such-id" in gate.detail


def test_a_price_that_disagrees_with_the_welcome_email_fails(site) -> None:
    page = site / "league-pass.html"
    page.write_text(page.read_text().replace('class="amt">$69', 'class="amt">$89'))
    assert lc.check_prices()[0].status == "FAIL"


def test_a_personal_address_anywhere_fails(site) -> None:
    page = site / "privacy.html"
    page.write_text(page.read_text().replace("</body>", "someone@gmail.com</body>"))
    assert _status(lc.check_selling_copy(), "personal email") == "FAIL"


def test_a_script_that_does_not_parse_fails(site) -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    page = site / "index.html"
    page.write_text(page.read_text().replace("const CHECKOUT_OPEN = false;",
                                             "const CHECKOUT_OPEN = = false;"))
    assert _status(lc.check_scripts(), "script parses") == "FAIL"


def test_the_real_tree_raises_no_failure() -> None:
    """The static gates over the committed site: a FAIL here is a launch bug."""
    gates = (lc.check_links() + lc.check_page_basics() + lc.check_scripts()
             + lc.check_selling_copy() + lc.check_prices() + lc.check_funnel_config()
             + lc.check_compliance())
    failing = [f"{g.name}: {g.detail}" for g in gates if g.status == "FAIL"]
    assert not failing, failing


def test_the_secrets_gate_asks_for_every_secret_the_mail_needs() -> None:
    """Launch review OPS-4: the crons map SENDER_POSTAL_ADDRESS into every
    step that can mail (tests/test_workflows.py), but the launch check's
    secrets gate did not list it — so launch morning could read "all present"
    with every commercial email about to go out with no sender line. Any
    secret a mail-sending step needs, other than a provider's alternative
    token, is on the list."""
    assert "SENDER_POSTAL_ADDRESS" in lc.REQUIRED_SECRETS
    for name in ("EMAIL_PROVIDER", "EMAIL_FROM", "SITE_URL", "BILLING_PORTAL_URL"):
        assert name in lc.REQUIRED_SECRETS, name


def test_the_report_reads_and_the_verdict_follows_the_gates() -> None:
    gates = [lc.Gate("Site", "a", "PASS"), lc.Gate("Owner", "b", "OWNER", "do it")]
    assert "waiting on owner setup" in lc.render(gates)
    gates.append(lc.Gate("Site", "c", "FAIL", "broken"))
    assert "fix the failures" in lc.render(gates)
    assert "READY" in lc.render([lc.Gate("Site", "a", "PASS")]).splitlines()[-1]


# --------------------------------------------------------------------- #
# OPS-04: checkout opens only once roster changes have a route
# --------------------------------------------------------------------- #

def test_opening_checkout_before_the_form_worker_fails(site) -> None:
    """Reproduction (OPS-04, Oct 2026): LAUNCH.md reopened checkout "right
    after" steps 1-3 while the form Worker was step 5, and nothing kept the
    two in order — so a buyer could pay with roster changes possible only by a
    reply the owner applies by hand. CHECKOUT_OPEN on the landing with the join
    page's FORM_ENDPOINT empty is a FAIL; with the Worker wired it passes."""
    page = site / "index.html"
    page.write_text(page.read_text().replace("const CHECKOUT_OPEN = false;",
                                             "const CHECKOUT_OPEN = true;"))
    assert _status(lc.check_funnel_config(), "before roster changes have a route") == "FAIL"
    join = site / "join" / "index.html"
    join.write_text(join.read_text().replace('const FORM_ENDPOINT = "";',
                                             'const FORM_ENDPOINT = "https://forms.example";'))
    assert _status(lc.check_funnel_config(), "before roster changes have a route") == "PASS"


# --------------------------------------------------------------------- #
# GATE-1: the product battery, joined to today's facts
# --------------------------------------------------------------------- #

TODAY = {"wr-moved": {"status": "ACT", "team": "MIA", "position": "WR"},
         "wr-ok": {"status": "ACT", "team": "KC", "position": "WR"},
         "rb-cut": {"status": "CUT", "team": "SF", "position": "RB"},
         "rb-ok": {"status": "ACT", "team": "BUF", "position": "RB"}}
BYES = {"MIA", "DET"}


def _slot(**over) -> dict:
    row = {"slot": "WR", "player_id": "wr-ok", "player_name": "Okay Receiver",
           "position": "WR", "confidence": None, "alternative_id": None,
           "alternative_name": None, "flags": []}
    row.update(over)
    return row


def _battery_report(lineup, bench=(), checklist=(), regret=None) -> dict:
    return {"lineup": list(lineup), "bench": list(bench),
            "checklist": [{"action": a} for a in checklist], "regret": regret or {}}


def test_a_player_on_his_current_teams_bye_counts_as_unable_to_play() -> None:
    """Reproduction (GATE-1): the battery read the gate's carried-forward team
    (his last stat row's), so a receiver traded onto a team on bye — or a
    released back the gate never placed — was invisible to it. cannot_play
    reads TODAY's players release: the current team and the status."""
    assert lc.cannot_play("wr-moved", TODAY, BYES) == "MIA on bye"
    assert lc.cannot_play("rb-cut", TODAY, BYES) == "released"
    assert lc.cannot_play("DEF-DET", TODAY, BYES) == "DET on bye"
    assert lc.cannot_play("wr-ok", TODAY, BYES) is None
    assert lc.cannot_play("DEF-KC", TODAY, BYES) is None


def test_a_starter_who_cannot_play_must_be_flagged_named_and_uncoverable() -> None:
    silent = _battery_report([_slot(player_id="wr-moved", player_name="Moved Receiver")])
    assert lc.audit_report("x", silent, TODAY, BYES)["silent"]
    # Flagged on the row but missing from the checklist is still silent: the
    # checklist is the part a reader acts on.
    unnamed = _battery_report([_slot(player_id="wr-moved", player_name="Moved Receiver",
                                     flags=[{"kind": "out"}])], checklist=["Set this lineup"])
    assert lc.audit_report("x", unnamed, TODAY, BYES)["silent"]
    told = _battery_report(
        [_slot(player_id="wr-moved", player_name="Moved Receiver",
               flags=[{"kind": "out"}])],
        checklist=["Bench Moved Receiver — he can't play this week"])
    assert not lc.audit_report("x", told, TODAY, BYES)["silent"]
    # Flagged and named, but a healthy receiver sat on the bench: started over
    # somebody who can play is a defect, not a necessity.
    covered = _battery_report(
        told["lineup"], checklist=["Bench Moved Receiver"],
        bench=[{"player_id": "wr-ok", "name": "Okay Receiver", "position": "WR", "out": False}])
    assert lc.audit_report("x", covered, TODAY, BYES)["over_playable"]
    # The same bench player marked out by the report itself is no cover.
    hurt = _battery_report(
        told["lineup"], checklist=["Bench Moved Receiver"],
        bench=[{"player_id": "wr-ok", "name": "Okay Receiver", "position": "WR", "out": True}])
    assert not lc.audit_report("x", hurt, TODAY, BYES)["over_playable"]


def test_a_call_against_a_player_who_cannot_play_is_caught() -> None:
    """Every call's ALTERNATIVE is joined to today's facts too: a % that a
    starter outscores a released back, or a receiver on bye, is a number about
    a game one side is not in."""
    released = _battery_report([_slot(slot="RB", player_id="rb-ok", position="RB",
                                      confidence=0.61, alternative_id="rb-cut",
                                      alternative_name="Cut Back")])
    assert lc.audit_report("x", released, TODAY, BYES)["bad_alt"]
    closest = _battery_report([_slot()], regret={"confidence": 0.58, "over_id": "wr-moved",
                                                 "over_name": "Moved Receiver"})
    assert lc.audit_report("x", closest, TODAY, BYES)["bad_alt"]
    fine = _battery_report([_slot(confidence=0.61, alternative_id="wr-ok")])
    assert not any(lc.audit_report("x", fine, TODAY, BYES).values())


def test_byes_come_from_the_schedule_and_an_unknown_week_is_unknown(tmp_path) -> None:
    (tmp_path / "games.csv").write_text(
        "season,game_type,week,home_team,away_team\n"
        "2026,REG,6,KC,BUF\n2026,REG,7,KC,MIA\n2026,REG,7,DET,BUF\n2026,POST,6,MIA,DET\n",
        encoding="utf-8")
    assert lc.schedule_byes(tmp_path, "2026", 6) == {"MIA", "DET"}
    assert lc.schedule_byes(tmp_path, "2026", 9) is None, "no games on file is not 'no byes'"


def test_the_battery_builds_each_hard_case_this_week() -> None:
    """On the live cache: the hard-case rosters exist and each really holds a
    player who cannot play — a battery whose 'bye' roster has nobody on bye
    would pass every gate while testing nothing."""
    from run.solo import CACHE_DIR, load_week_data
    try:
        data = load_week_data(CACHE_DIR)
    except Exception as exc:  # noqa: BLE001 — no cache in CI, or the offseason
        pytest.skip(f"live week not buildable here: {exc}")
    today = lc.players_today(CACHE_DIR)
    byes = lc.schedule_byes(CACHE_DIR, data.season, data.week) or set()
    if not byes:
        pytest.skip("no byes this week")
    rosters = {name: ids for name, ids, _ in lc.battery_rosters(data, today, byes)}
    assert "Byes and injuries" in rosters
    for name, ids in rosters.items():
        if name != "Sample roster":
            assert any(lc.cannot_play(pid, today, byes) for pid in ids), name


# --------------------------------------------------------------------- #
# GATE-5: the join modes, completed
# --------------------------------------------------------------------- #

BASE = "http://127.0.0.1:9"
ROSTER = {"00-0037834", "DEF-KC"}


def _ref(plan: str = "season") -> str:
    from run.refs import encode_roster
    return encode_roster(plan, "ppr", ("QB", "DEF"), tuple(sorted(ROSTER)), 12)


def _handoff(ref: str, email: str = lc.FLOW_EMAIL, plan_path: str = "season",
             extra: str = "") -> dict:
    import urllib.parse
    return {"handoff": f"{BASE}/__stripe/{plan_path}?client_reference_id="
                       f"{urllib.parse.quote(ref)}&locked_prefilled_email="
                       f"{urllib.parse.quote(email)}{extra}"}


def test_a_well_formed_hand_off_passes() -> None:
    assert lc.audit_flow("season", "checkout", "season", "", _handoff(_ref()), ROSTER, BASE) == []
    tagged = _ref() + "_via-launch-check"
    assert lc.audit_flow("season", "checkout", "season", "?via=launch-check",
                         _handoff(tagged), ROSTER, BASE) == []


def test_every_way_a_hand_off_goes_wrong_is_named() -> None:
    """Stripe silently DROPS a client_reference_id outside
    ^[A-Za-z0-9_-]{1,200}$ while still taking the money — the payment arrives
    with no roster — so every property of the hand-off is checked as the
    intake will read it."""
    bad = {
        "long": _handoff(_ref() + "x" * 200),
        "unsafe": _handoff(_ref() + "!"),
        "wrong email": _handoff(_ref(), email="someone.else@example.com"),
        "wrong plan": _handoff(_ref("monthly")),
        "wrong link": _handoff(_ref(), plan_path="monthly"),
        "extra param": _handoff(_ref(), extra="&prefilled_promo_code=X"),
        "foreign tag": _handoff(_ref() + "_via-somebody"),
    }
    for name, result in bad.items():
        assert lc.audit_flow("season", "checkout", "season", "", result, ROSTER, BASE), name
    other = {"00-0037834", "DEF-BUF"}
    assert lc.audit_flow("season", "checkout", "season", "", _handoff(_ref()), other, BASE)
    assert lc.audit_flow("season", "checkout", "season", "", {"handoff": None}, ROSTER, BASE)


def test_a_posted_row_is_checked_as_the_intake_reads_it() -> None:
    import json
    good = {"kind": "trial", "email": lc.FLOW_EMAIL, "ref": _ref()}
    assert lc.audit_flow("free report", "trial", None, "", {"posted": [json.dumps(good)]},
                         ROSTER, BASE) == []
    twice = {"posted": [json.dumps(good)] * 2}
    assert lc.audit_flow("free report", "trial", None, "", twice, ROSTER, BASE)
    for broken in ({**good, "email": "x@example.com"}, {**good, "ref": "nope!"},
                   {**good, "kind": "waitlist"}):
        assert lc.audit_flow("free report", "trial", None, "",
                             {"posted": [json.dumps(broken)]}, ROSTER, BASE), broken
    # Contract C3: a seat row naming its pass by a typed payer address is a
    # failure wherever it comes from — the generic ?pass=1 page claims nothing.
    typed = {"email": lc.FLOW_EMAIL, "covered_by": "commish@example.com", "ref": _ref()}
    assert lc.audit_flow("seat", "seat", None, "?pass=1", {"posted": [json.dumps(typed)]},
                         ROSTER, BASE)
    # The closed checkout keeps an email; a ref it carries must still be sound.
    listed = {"kind": "waitlist", "email": lc.FLOW_EMAIL}
    assert lc.audit_flow("closed", "waitlist", None, "", {"posted": [json.dumps(listed)]},
                         ROSTER, BASE) == []
    assert lc.audit_flow("closed", "waitlist", None, "",
                         {"posted": [json.dumps({**listed, "ref": "x!"})]}, ROSTER, BASE)


def test_a_seat_link_row_carries_its_token_and_the_links_settings() -> None:
    """Contract C4: from the payer's own link a seat posts the pass token, not
    a payer address, and the league's settings arrive from the link."""
    import json
    from run.refs import encode_roster
    query = f"?pass={lc.FLOW_TOKEN}&s=half_ppr&n=10&t=sf"
    slots = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF")
    ids = tuple(f"00-00000{i:02d}" for i in range(10))
    ref = encode_roster("season", "half_ppr", slots, ids, 10)
    row = {"kind": "seat", "email": lc.FLOW_EMAIL, "ref": ref, "pass_token": lc.FLOW_TOKEN}
    assert lc.audit_flow("seat link", "seat", None, query, {"posted": [json.dumps(row)]},
                         set(ids), BASE) == []
    wrong = encode_roster("season", "ppr", slots, ids, 12)
    assert lc.audit_flow("seat link", "seat", None, query,
                         {"posted": [json.dumps({**row, "ref": wrong})]}, set(ids), BASE)
    assert lc.audit_flow("seat link", "seat", None, query,
                         {"posted": [json.dumps({**row, "pass_token": "f" * 20})]},
                         set(ids), BASE)


def test_the_generic_seat_page_must_say_where_the_link_is_and_send_nothing() -> None:
    """Reproduced (pre-launch review): GATE-5 still completed `?pass=1` as a
    seat claim with the payer's address typed in and required the row's
    `covered_by` — the route contract C3 closed — so `make launch-check`
    FAILed ("nothing left the page") on a deliberate change. The flow is now
    "seat (no link)": nothing may leave the page, the form is hidden, and the
    note says where the league's own link is, in the page's own words."""
    words = lc.seat_link_missing_words()
    assert words.startswith("Seats are claimed with your league's own seat link.")
    right = {"note": words, "mainHidden": True, "posted": [], "handoff": None}
    assert lc.audit_flow("seat (no link)", "none", None, "?pass=1", right, ROSTER, BASE) == []
    for broken in ({**right, "posted": ['{"kind": "seat"}']}, {**right, "note": ""},
                   {**right, "mainHidden": False}, {**right, "handoff": BASE + "/__stripe/x"}):
        assert lc.audit_flow("seat (no link)", "none", None, "?pass=1", broken, ROSTER, BASE)
    modes = {mode: kind for mode, _c, _q, kind, _p in lc.FLOWS}
    assert modes.get("seat (no link)") == "none" and modes.get("seat (payer's link)") == "seat"
    assert "seat (payer's address)" not in modes
    browser = (lc.REPO / "run" / "launch_browser.mjs").read_text(encoding="utf-8")
    assert "pass-email" not in browser and "pass-field" not in browser


def test_a_report_update_link_must_post_the_settings_it_carried() -> None:
    """FUNNEL F1 in the browser gate: every report now links the update page
    with its subscription's s/n/t, and an update REPLACES the settings on file
    with the posted ref's. The gate's only update flow opened a bare
    ``?update=1``, which since the settings box arrived posted nothing (the
    gate FAILED on the real tree, Oct 17 2026). Now both flows run — the
    report link, whose posted ref must carry the link's settings exactly, and
    the bare link with its box ticked."""
    import json
    from run.refs import encode_roster
    modes = {mode: query for mode, _copy, query, _k, _p in lc.FLOWS}
    query = modes["roster update (report link)"]
    assert "s=" in query and "n=" in query and "t=" in query
    assert modes["roster update (bare link)"] == "?update=1"
    assert lc.FLOW_TICKS["roster update (bare link)"] == ["settings-ok"]
    slots = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF")
    ids = tuple(f"00-00000{i:02d}" for i in range(10))
    good = {"kind": "update_request", "email": lc.FLOW_EMAIL,
            "ref": encode_roster("season", "half_ppr", slots, ids, 10)}
    assert lc.audit_flow("update", "update_request", None, query,
                         {"posted": [json.dumps(good)]}, set(ids), BASE) == []
    for scoring, size, shape in (("ppr", 10, slots), ("half_ppr", 12, slots),
                                 ("half_ppr", 10, slots[:7] + ("FLEX", "K", "DEF"))):
        wrong = {**good, "ref": encode_roster("season", scoring, shape, ids, size)}
        assert lc.audit_flow("update", "update_request", None, query,
                             {"posted": [json.dumps(wrong)]}, set(ids), BASE), (scoring, size)


def test_the_plan_switch_must_rewrite_the_button_and_the_terms() -> None:
    season = {"button": "Continue to checkout — $29", "terms": "$29, one payment"}
    monthly = {"button": "Continue to checkout — $14.99/mo", "terms": "Monthly is $14.99"}
    assert lc.audit_plan_switch({"before": season, "after": monthly, "back": season}) == []
    stale = {"button": "Continue to checkout — $14.99/mo", "terms": "$29, one payment"}
    assert lc.audit_plan_switch({"before": season, "after": stale, "back": season})
    assert lc.audit_plan_switch({"before": season, "after": monthly, "back": monthly})
    assert lc.audit_plan_switch(None)


def _needs_browser() -> None:
    if not lc._browser_tools():
        pytest.skip("needs Chrome and node")


def test_a_join_page_that_unlocks_the_email_fails_in_the_browser(site) -> None:
    """The gate end to end: a join page whose hand-off stops carrying the
    typed email is caught by completing the flow in Chrome — the source-text
    test (tests/test_site.py) still finds the parameter by name."""
    import re
    _needs_browser()
    page = site / "join" / "index.html"
    text = page.read_text(encoding="utf-8")
    locked = re.compile(r'(locked_prefilled_email="\s*\+\s*encodeURIComponent\()(\w+)\)')
    assert locked.search(text), "the join page no longer builds locked_prefilled_email"
    page.write_text(locked.sub(r"\1\2.toUpperCase())", text, count=1))
    gate = [g for g in lc.check_join_flows() if "hands off" in g.name][0]
    assert gate.status == "FAIL" and "locked email" in gate.detail, gate


# --------------------------------------------------------------------- #
# GATE-2, GATE-19, GATE-20: the other browser gates
# --------------------------------------------------------------------- #

def test_an_email_wider_than_a_phone_fails(monkeypatch) -> None:
    """GATE-2: the live week and the battery at a true 390px. A 640px table
    is the shape of the failure: the reader scrolls sideways through a
    lineup."""
    _needs_browser()
    import render.email as email
    import render.live_sample as live
    wide = ('<!doctype html><html><head><meta name="viewport" content="width=device-width">'
            '</head><body><table width="640"><tr><td>wide</td></tr></table></body></html>')
    monkeypatch.setattr(live, "build", lambda *a, **k: {})
    monkeypatch.setattr(email, "render_email", lambda report: wide)
    monkeypatch.setattr(lc, "battery_reports", lambda: ())
    [gate] = lc.check_email_widths()
    assert gate.status == "FAIL" and "this week's sample" in gate.detail, gate


def test_a_control_with_no_name_fails_the_accessibility_gate(site, monkeypatch) -> None:
    """GATE-19: a button a screen reader announces as nothing is a serious
    axe violation, and serious is a FAIL."""
    if not lc.axe_core_path():
        pytest.skip("axe-core not found (set AXE_CORE_PATH)")
    _needs_browser()
    page = site / "league-pass.html"
    page.write_text(page.read_text().replace("</main>", "<button></button></main>", 1))
    monkeypatch.setattr(lc, "A11Y_PAGES", ("league-pass.html",))
    gates = lc.check_accessibility()
    assert gates[0].status == "FAIL" and "button-name" in gates[0].detail, gates[0]


def test_the_speed_gate_reads_the_median_against_the_budget(monkeypatch) -> None:
    """GATE-20: median of three, so one slow run is not a failure and one fast
    run does not hide a slow page; an unmeasured page is not a fast one."""
    def results(lcp, cls):
        return lambda jobs, base, timeout=0: [
            {"kind": "perf", "path": "index.html", "lcp": lcp, "cls": cls}]
    monkeypatch.setattr(lc, "run_browser", results([1200, 9000, 1300], [0.01, 0.4, 0.02]))
    assert [g.status for g in lc.check_speed()] == ["PASS", "PASS"]
    monkeypatch.setattr(lc, "run_browser", results([2600, 2700, 1200], [0.2, 0.3, 0.0]))
    assert [g.status for g in lc.check_speed()] == ["FAIL", "WARN"]
    monkeypatch.setattr(lc, "run_browser", results([None, None, None], [None] * 3))
    assert lc.check_speed()[0].status == "FAIL"


# --------------------------------------------------------------------- #
# GATE-9: every email says who sent it, and how to stop it
# --------------------------------------------------------------------- #

def test_an_email_without_the_sender_block_fails_once_the_address_is_set(monkeypatch) -> None:
    """Reproduction (L3, GATE-9): the gate only checked the variable was set,
    while the final check, the welcomes, the renewal notice and the roster
    report printed no sender at all. Set, a single email without the block
    FAILS; unset, the code is checked under a stand-in and the gate is OWNER."""
    from render.sender import sender_line

    def samples():
        line = sender_line() or ""
        return [("weekly report", f"<p>Cancel any time.</p><p>{line}</p>", None),
                ("renewal notice", "<p>Cancel any time.</p>", "https://billing.example")]
    monkeypatch.setattr(lc, "email_samples", samples)
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 9, Toronto ON")
    gates = lc.check_email_senders()
    assert gates[0].status == "FAIL" and "renewal notice" in gates[0].detail
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS")
    assert lc.check_email_senders()[0].status == "FAIL", "the code is broken either way"
    monkeypatch.setattr(lc, "email_samples", lambda: [
        ("weekly report", f"<p>Cancel.</p><p>{sender_line()}</p>", None)])
    assert lc.check_email_senders()[0].status == "OWNER"


def test_an_email_with_no_way_out_fails() -> None:
    found = lc.audit_senders([("a", "<p>Nothing to see.</p><p>S</p>", None),
                              ("b", "<p>S</p>", "mailto:hello@x?subject=stop"),
                              ("c", "<p>Reply \"stop\" to any email. S</p>", None)], "S")
    assert found == {"missing": [], "no_way_out": ["a"]}


def test_the_real_emails_carry_the_sender_and_a_way_out(monkeypatch) -> None:
    """Every email type, as the runners build them around this week's report."""
    from run.solo import CACHE_DIR
    if not (CACHE_DIR / "players.csv").is_file():
        pytest.skip("live data not cached")
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 9, Toronto ON")
    gates = lc.check_email_senders()
    if gates[0].status == "SKIP":
        pytest.skip(gates[0].detail)
    assert [g.status for g in gates] == ["PASS", "PASS"], gates


# --------------------------------------------------------------------- #
# GATE-12 to GATE-17: the accounts, read-only
# --------------------------------------------------------------------- #

def _run(created: str) -> dict:
    return {"event": "schedule", "created_at": created}


def test_a_late_tuesday_run_warns_and_a_dispatch_on_time_passes() -> None:
    """Reproduction (OPS-01): GitHub started the Tuesday runs 5-7 hours late
    on Oct 6 and Oct 13. The slot is read off the workflow's own cron; the
    first start for a slot is what a subscriber waits on, so the Worker's
    on-time dispatch beside GitHub's late backup reads as on time."""
    from datetime import datetime, timezone
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    hourly = [_run(f"2026-10-{d:02d}T{h:02d}:48:00Z") for d in range(9, 16) for h in range(24)]
    late = {"weekly.yml": [_run("2026-10-13T17:40:00Z"), _run("2026-10-06T18:02:00Z")],
            "saturday.yml": [_run("2026-10-10T16:20:00Z")], "daily.yml": hourly}
    found = lc.audit_cron_runs(late, now)
    assert any("weekly.yml" in line for line in found["late"]), found
    on_time = {**late, "weekly.yml": late["weekly.yml"] + [_run("2026-10-13T12:18:00Z"),
                                                           _run("2026-10-06T12:19:00Z")]}
    found = lc.audit_cron_runs(on_time, now)
    assert not found["late"], found
    sparse = {**on_time, "daily.yml": hourly[:40]}
    assert lc.audit_cron_runs(sparse, now)["late"], "most hourly runs dropped"


def test_a_tuesday_is_measured_from_its_first_slot_not_the_retry() -> None:
    """A run at 17:40 on a Tuesday is 5 h 23 min late for the 12:17 report,
    not 83 minutes late for the 16:17 retry; a manual run on a Thursday
    belongs to no slot at all."""
    from datetime import datetime, timedelta, timezone
    crons = ["17 12 * * 2", "17 16 * * 2"]
    late = datetime(2026, 10, 13, 17, 40, tzinfo=timezone.utc)
    [(slot, delay)] = lc.first_start_delays([late], crons)
    assert slot == datetime(2026, 10, 13, 12, 17, tzinfo=timezone.utc)
    assert delay == timedelta(hours=5, minutes=23)
    thursday = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
    assert lc.first_start_delays([thursday], crons) == []


def test_the_account_gates_skip_or_ask_rather_than_guess(monkeypatch) -> None:
    monkeypatch.setattr(lc, "_gh_json", lambda path: None)
    assert lc.check_cron_timing()[0].status == "SKIP"
    assert lc.check_fork_approval()[0].status == "OWNER"
    monkeypatch.setattr(lc, "_gh_json", lambda path: {"approval_policy": lc.FORK_POLICY})
    assert lc.check_fork_approval()[0].status == "PASS"
    monkeypatch.setattr(lc, "_gh_json",
                        lambda path: {"approval_policy": "first_time_contributors"})
    assert lc.check_fork_approval()[0].status == "OWNER"
    for name in ("RESEND_API_KEY", "STRIPE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert lc.check_resend_domain()[0].status == "OWNER"
    assert lc.check_stripe_account()[0].status == "OWNER"
    assert lc.check_refund_rates()[0].status == "SKIP"


def test_resend_must_say_verified(monkeypatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(lc, "_get_json", lambda url, key: (200, {"data": [
        {"name": lc.DOMAIN, "status": "pending"}]}))
    assert lc.check_resend_domain()[0].status == "OWNER"
    monkeypatch.setattr(lc, "_get_json", lambda url, key: (200, {"data": [
        {"name": lc.DOMAIN, "status": "verified"}]}))
    assert lc.check_resend_domain()[0].status == "PASS"


def test_stripes_public_details_must_keep_the_owner_anonymous(monkeypatch) -> None:
    good = {"business_profile": {"support_email": f"hello@{lc.DOMAIN}"}}
    assert lc.audit_stripe_account(good) == []
    assert lc.audit_stripe_account({"business_profile": {
        "support_email": f"hello@{lc.DOMAIN}", "support_phone": "+14165550000"}})
    assert lc.audit_stripe_account({"business_profile": {
        "support_email": f"hello@{lc.DOMAIN}", "support_address": {"line1": "1 Home St"}}})
    assert lc.audit_stripe_account({"business_profile": {"support_email": "me@gmail.com"}})
    monkeypatch.setenv("STRIPE_API_KEY", "rk_test")
    monkeypatch.setattr(lc, "_get_json", lambda url, key: (200, {"business_profile": {
        "support_email": "me@gmail.com"}}))
    assert lc.check_stripe_account()[0].status == "OWNER"


def test_refund_and_dispute_rates_warn_past_their_lines(monkeypatch) -> None:
    def charges(n, refunded=0, disputed=0):
        return [{"paid": True, "status": "succeeded", "refunded": i < refunded,
                 "amount_refunded": 3900 if i < refunded else 0, "disputed": i < disputed,
                 "amount": 3900} for i in range(n)]
    assert lc.audit_charge_rates(charges(10, refunded=2))[1] == 0.2
    monkeypatch.setenv("STRIPE_API_KEY", "rk_test")
    monkeypatch.setattr(lc, "_stripe_charges", lambda key, days: charges(10, refunded=2))
    assert lc.check_refund_rates()[0].status == "WARN"
    monkeypatch.setattr(lc, "_stripe_charges", lambda key, days: charges(200, disputed=2))
    assert lc.check_refund_rates()[0].status == "WARN", "1% disputes"
    monkeypatch.setattr(lc, "_stripe_charges", lambda key, days: charges(20, refunded=1))
    assert lc.check_refund_rates()[0].status == "PASS"
    monkeypatch.setattr(lc, "_stripe_charges", lambda key, days: [])
    assert lc.check_refund_rates()[0].status == "SKIP", "no charge yet is not a 0% rate"


def test_volume_warns_past_the_free_email_tier_and_the_tax_line(monkeypatch) -> None:
    monkeypatch.delenv("RESEND_PLAN", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.setattr(lc, "count_recipients", lambda registry=None: (80, 10))
    assert lc.check_volume()[0].status == "WARN"
    monkeypatch.setenv("RESEND_PLAN", "pro")
    assert lc.check_volume()[0].status == "PASS"
    monkeypatch.setattr(lc, "count_recipients", lambda registry=None: (40, 5))
    monkeypatch.delenv("RESEND_PLAN")
    assert lc.check_volume()[0].status == "PASS"
    monkeypatch.setenv("STRIPE_API_KEY", "rk_test")
    big = [{"paid": True, "status": "succeeded", "amount": 9900 * 250, "amount_refunded": 0}]
    monkeypatch.setattr(lc, "_stripe_charges", lambda key, days: big)
    assert lc.check_volume()[1].status == "OWNER", "over the GST/HST threshold"


def test_every_missing_secret_says_what_a_buyer_loses() -> None:
    """Addendum (Oct 2026): UPDATE_SECRET keys the seat links as well as the
    roster updates, and SITE_URL builds the payer's seat link — the secrets
    gate says which features each missing name switches off."""
    assert {name for needs in lc.FEATURE_SECRETS.values() for name in needs} \
        <= set(lc.REQUIRED_SECRETS)
    off = lc.features_off(["UPDATE_SECRET"])
    assert "seat link" in off and "roster updates" in off
    assert "seat link" in lc.features_off(["SITE_URL"])
    assert lc.features_off([]) == "nothing a buyer sees"


def test_the_pass_welcome_carries_the_seat_link() -> None:
    assert lc.check_seat_link()[0].status == "PASS"


# --------------------------------------------------------------------- #
# Recheck (Oct 17 2026): the live sample's odds, the record, every email
# --------------------------------------------------------------------- #

_WEEK = {"season": "2026", "week": 6, "lands_on": "2026-10-20",
         "built_at": "2026-10-14T12:00:00+00:00", "first_kickoff": "2026-10-16T00:15:00Z"}


def test_a_live_sample_printing_unrecorded_odds_fails() -> None:
    """G24 / R1 / BE2-D3, reproduced from the committed site/week.json of Oct
    17 2026: 2 odds, no ``recorded``, built a day after Thursday's kickoff and
    not saying so, with nothing on the record — and no launch-check gate read
    either flag. Each half fails on its own; a page whose odds are on the
    record, or that shows none, passes; a page rebuilt after kickoff passes
    only when it says so."""
    gate = lc.recorded_odds_gate
    assert gate({**_WEEK, "odds": 2}).status == "FAIL"
    assert "prints 2 %" in gate({**_WEEK, "odds": 2}).detail
    assert gate({**_WEEK, "odds": 2, "recorded": True}).status == "PASS"
    assert gate({**_WEEK, "odds": 0}).status == "PASS"
    late = {**_WEEK, "odds": 0, "built_at": "2026-10-17T00:03:38+00:00"}
    assert gate(late).status == "FAIL" and "does not say so" in gate(late).detail
    assert gate({**late, "after_kickoff": True}).status == "PASS"
    both = gate({**late, "odds": 3})
    assert both.status == "FAIL" and "prints 3 %" in both.detail and "does not say" in both.detail


def test_the_season_clock_check_carries_the_recorded_odds_gate(site) -> None:
    import json
    (site / "week.json").write_text(json.dumps({**_WEEK, "odds": 4}), encoding="utf-8")
    assert _status(lc.check_week_json(), "only recorded odds") == "FAIL"
    (site / "week.json").write_text(json.dumps({**_WEEK, "odds": 4, "recorded": True}),
                                    encoding="utf-8")
    assert _status(lc.check_week_json(), "only recorded odds") == "PASS"


def test_an_empty_record_warns_once_odds_could_have_been_recorded(tmp_path, monkeypatch) -> None:
    """G25, reproduced on Oct 17 2026 (Week 6): no typed-* store existed, so
    not one published % was on the record — and nothing said so, because no
    gate counted. The gate counts this season's calls as the grader reads
    them; zero is a WARN from Week 2's report Tuesday on and a PASS before
    it; an unreadable store is a FAIL; another season's store, or the retired
    product's, never counts."""
    import json
    from dataclasses import asdict
    from datetime import date
    import render.live_sample as live
    import run.solo as solo
    from engine.ledger import LedgerCall, ledger_path
    monkeypatch.setattr(solo, "current_season", lambda cache, today=None: "2026")
    monkeypatch.setattr(live, "next_report_day", lambda cache, season, week: "2026-09-15")
    week6, preseason = date(2026, 10, 17), date(2026, 9, 1)
    [gate] = lc.check_record(tmp_path, week6)
    assert gate.status == "WARN" and "0 call(s)" in gate.detail and "2026-09-15" in gate.detail
    assert lc.check_record(tmp_path, preseason)[0].status == "PASS"
    call = LedgerCall(call_id="c1", source="slot", league_id="typed-ppr-12-2026",
                      season="2026", week=6, roster_id=1, slot="RB", pick_id="a",
                      pick_name="A", over_id="b", over_name="B", confidence=0.61)
    # Another season's store and a Sleeper-era store are not this record.
    for store in ("typed-ppr-12-2025", "289646328504385536"):
        path = ledger_path(tmp_path, store)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(asdict(call)) + "\n", encoding="utf-8")
    assert lc.check_record(tmp_path, week6)[0].status == "WARN"
    path = ledger_path(tmp_path, "typed-ppr-12-sf-2026")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(asdict(call)) + "\n", encoding="utf-8")
    [gate] = lc.check_record(tmp_path, week6)
    assert gate.status == "PASS" and "1 call(s)" in gate.detail, gate
    path.write_text("not json\n", encoding="utf-8")
    assert lc.check_record(tmp_path, week6)[0].status == "FAIL"


def test_every_email_the_product_sends_is_in_the_samples(monkeypatch) -> None:
    """S6/S7: the three notes a seat claim gets, the League Pass bought over a
    season pass, and the launch announcement that restores a saved roster
    were never built by the launch check — so neither the sender gate nor the
    390px gate ever saw them. Each is built here as its runner builds it, and
    each that is not a transactional reply carries the sender block and a way
    out (a seat note's List-Unsubscribe is the seat stop route)."""
    from render.report import seat_stop_href
    from render.sender import sender_line
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", lc.PROBE_ADDRESS)
    samples = lc.other_email_samples("2026")
    names = {name: (page, unsub) for name, page, unsub in samples}
    for name in ("failed seat claim", "seat pass full", "seat confirmation",
                 "welcome (League Pass over a season pass)", "launch announcement",
                 "launch announcement (saved roster)", "roster confirmation"):
        assert name in names, name
    for name in ("failed seat claim", "seat pass full", "seat confirmation"):
        assert names[name][1] == seat_stop_href(), name
    assert "k=seat" in names["seat confirmation"][0]
    assert "not two" in names["welcome (League Pass over a season pass)"][0]
    assert "ref=" in names["launch announcement (saved roster)"][0]
    assert "→" in names["roster confirmation"][0], "the confirmation sample shows no change"
    assert lc.audit_senders(samples, sender_line() or "") == {"missing": [], "no_way_out": []}


def test_a_non_report_email_wider_than_a_phone_fails(monkeypatch) -> None:
    """S7, reproduced by breaking one: the width gate measured only reports,
    so a seat note laid out at 640px passed it. Every other email is measured
    now, and the one that overflows is named."""
    _needs_browser()
    import render.email as email
    import render.live_sample as live
    import render.seat_claim as seat_claim
    narrow = ('<!doctype html><html><head><meta name="viewport" '
              'content="width=device-width"></head><body><p>ok</p></body></html>')
    wide = narrow.replace("<p>ok</p>", '<table width="640"><tr><td>wide</td></tr></table>')
    monkeypatch.setattr(live, "build", lambda *a, **k: {"meta": {"season": "2026"}})
    monkeypatch.setattr(email, "render_email", lambda report: narrow)
    monkeypatch.setattr(lc, "battery_reports", lambda: ())
    monkeypatch.setattr(seat_claim, "full_email", lambda site="": ("s", wide, "t"))
    [gate] = lc.check_email_widths()
    assert gate.status == "FAIL" and "seat pass full" in gate.detail, gate
    assert "this week's sample" not in gate.detail


# --------------------------------------------------------------------- #
# the free bye-week planner (contract C7) and the clock's closest call (C6)
# --------------------------------------------------------------------- #

def test_a_planner_left_behind_on_launch_morning_fails(site) -> None:
    """The planner shows the gold "Get the weekly report" link on its own
    CHECKOUT_CAN_COMPLETE and a free-report link on its own TRIAL_OPEN; flags
    flipped on the landing and not on the planner (or the reverse) would send
    a visitor to a closed checkout, or hide the open one. A planner endpoint
    that is not the Worker the other pages post to fails too."""
    gates = lc.check_funnel_config()
    assert _status(gates, "planner's checkout and free-report flags") == "PASS"
    planner = site / "byes" / "index.html"
    text = planner.read_text()
    planner.write_text(text.replace("const CHECKOUT_CAN_COMPLETE = false;",
                                    "const CHECKOUT_CAN_COMPLETE = true;"))
    assert _status(lc.check_funnel_config(), "planner's checkout and free-report flags") == "FAIL"
    planner.write_text(text.replace('const NOTIFY_LIST_ENDPOINT = "";',
                                    'const NOTIFY_LIST_ENDPOINT = "https://elsewhere.example/rows";'))
    join = site / "join" / "index.html"
    join.write_text(join.read_text().replace('const FORM_ENDPOINT = "";',
                                             'const FORM_ENDPOINT = "https://forms.example/rows";'))
    assert _status(lc.check_funnel_config(), "same form Worker") == "FAIL"


def test_the_planner_and_league_app_pages_are_held_to_the_selling_rules() -> None:
    """Both sell (the planner hands a roster to join/, the app pages link
    it), so the copy, accessibility and speed gates read them; the planner
    with a restored roster is an accessibility page of its own."""
    for page in ("byes/index.html", "espn/index.html", "yahoo/index.html",
                 "sleeper/index.html", "cbs/index.html"):
        assert page in lc.SELLING and page in lc.A11Y_PAGES
    assert any(p.startswith("byes/index.html?ref=") for p in lc.A11Y_PAGES)
    assert ("byes/index.html", (320, 390, 1280)) in lc.BROWSER_PAGES


def test_a_closest_call_the_ledger_does_not_hold_fails() -> None:
    """C6: the landing quotes week.json's closest call as recorded output, so
    the gate reads the ledger itself — absent is fine, unrecorded fails."""
    assert lc.closest_gate({"week": 8}).status == "PASS"
    bad = {"season": "2026", "week": 8, "recorded": False,
           "closest": {"season": "2026", "week": 8, "slot": "WR", "start": "A", "over": "B",
                       "pct": 61, "recorded": True}}
    assert lc.closest_gate(bad).status == "FAIL"
    assert "closest_gate(w)" in __import__("inspect").getsource(lc.check_week_json)
