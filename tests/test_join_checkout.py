"""The buy page, from a checked roster to Stripe (Nov 4 2026, checkout open).

Walked at 390x844 before this change: a ready buyer pasted, pressed "Check my
team", and the facts panel (~1,484px) sat between the tally and step 3, so the
email field was about two screens down; "Unlock my lineups" then always opened
a read-back box with a second gold "Continue to checkout" while Unlock stayed
live above it; a roster restored from ?ref= came back with the email ~3,100px
down and nothing said where to go; the heading still read as the free check
with checkout open; and the free report's note promised "within the hour" in
two windows when run/trials.py holds every request.

What these tests hold:
- default buy mode, once the roster checks out: one gold "Continue to
  checkout" under the tally, which goes to the email (re-checking an edited
  roster first), and the panel no longer scrolls it off the screen;
- a clean ?ref= restore in buy mode lands on the email, with a line saying the
  roster can still be edited above;
- the address is read back as it is typed, and Unlock goes straight to Stripe
  unless the address looks like a typo; then the box opens and Unlock goes, so
  one gold button shows;
- open, the heading and title say "Get your lineups", and the pitch leads with
  what happens, keeping the price, its stop and the refund;
- the free report's note says the wait run/trials.py really applies, from the
  same hold hours (pinned to it here);
- after a free-report request, one quiet offer of the Monthly plan with this
  roster, carrying no free-report mode, channel parameter or address.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from run import trials
from run.refs import decode_roster
from test_site import JOIN, _js_code, _js_function, _node

ROOT = Path(__file__).resolve().parent.parent
STEPS = ROOT / "tests" / "join_steps.mjs"
GOLD = "rgb(242, 194, 48)"


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'"\s*\+\s*"', "", text))


# --------------------------------------------------------------------- #
# the source
# --------------------------------------------------------------------- #

def test_the_way_on_sits_directly_under_the_tally_and_ships_hidden() -> None:
    markup = re.sub(r"<script\b.*?</script>", "", JOIN, flags=re.S)
    tally = markup.index('<div class="tally" id="tally"')
    go = markup.index('<button type="button" id="go-checkout" hidden>Continue to checkout</button>')
    assert tally < go < markup.index('id="defenses-ok"') < markup.index('<div id="rows">')
    assert not re.search(r"<(?:button|input|a)\b", markup[tally + 1:go].split("</div>", 1)[1])
    # Only the default buy mode, and only while the plan on screen takes money.
    buying = _js_function(JOIN, "buyingNow")
    for flag in ("!SEAT_MODE", "!UPDATE_MODE", "!TRY_MODE", "!WANTS_PASS",
                 "Boolean(planLink())", "!seasonOver()"):
        assert flag in buying, flag
    # An add and a trade check are update modes on this page.
    assert "const UPDATE_MODE = !SEAT_MODE && (TOKEN_UPDATE || QUERY.has(\"update\") || " \
           "ADD_MODE || TRADE_MODE);" in JOIN
    shows = _js_function(JOIN, "goCheckoutShows")
    assert "if (!buyingNow() || !state.matches.length) return false;" in shows
    assert "state.stale ? state.goShown === true : payoffShows()" in shows


def test_the_panel_no_longer_scrolls_the_way_on_off_the_screen() -> None:
    bring = _js_function(JOIN, "bringPayoffIntoView")
    go = bring.split("if (goCheckoutShows()) {")[1].split("\n  }\n")[0]
    assert '$("go-checkout").getBoundingClientRect()' in go and "return;" in go
    assert bring.index("if (goCheckoutShows()) {") < bring.index('$("payoff")')


def test_an_edited_roster_is_checked_again_by_the_same_press() -> None:
    code = _js_code(JOIN)
    press = code.split('$("go-checkout").addEventListener("click", () => {')[1].split("\n});")[0]
    assert press.index('$("resolve").click();') < press.index("bringToEmail();")
    assert "if (!state.ready || state.stale) return;" in press
    bring = _js_function(JOIN, "bringToEmail")
    assert 'behavior: reduced ? "auto" : "smooth"' in bring
    assert "(prefers-reduced-motion: reduce)" in bring
    assert '$("email").focus({ preventScroll: true });' in bring
    # While an edit waits, "Check my team" is the gold again and this one is
    # drawn as the secondary.
    assert '#go-checkout.is-stale{background:var(--card);' in JOIN
    typed = code.split('$("roster-text").addEventListener("input"')[1].split("\n});")[0]
    assert '$("resolve").classList.remove("is-done");' in typed and "drawGoCheckout();" in typed


def test_a_clean_restore_goes_to_the_email_and_says_the_roster_can_change() -> None:
    restore = _js_function(JOIN, "restoreRoster")
    assert "if (state.ready && buyingNow()) {" in restore
    assert restore.index("draw();") < restore.index("jumpToEmailIfWaiting();")
    # It waits for the two files that grow the panel above step 3.
    jump = _js_function(JOIN, "jumpToEmailIfWaiting")
    assert "!SETTLING.byes || !SETTLING.week" in jump and "bringToEmail();" in jump
    assert "!state.checked && buyingNow()" in jump
    assert '.then(() => settled("byes"));' in _js_function(JOIN, "loadByes")
    assert '.then(() => settled("week"));' in JOIN
    line = re.search(r'<p class="note" id="restored-line" hidden>(.*?)</p>', JOIN).group(1)
    assert line == "Changed your roster since? Edit it above before you pay."
    assert JOIN.index('id="restored-line"') < JOIN.index('id="email"')
    # The email never rides in the address.
    keep = "\n".join(line for line in _js_function(JOIN, "keepInAddress").splitlines()
                     if not line.lstrip().startswith("//"))
    assert "email" not in keep.lower()
    bring = _js_function(JOIN, "bringToEmail")
    assert "location" not in bring and "history" not in bring


def test_unlock_goes_straight_to_stripe_unless_the_address_looks_like_a_typo() -> None:
    handler = JOIN.split('$("form-email").addEventListener("submit"')[1].split("\n});")[0]
    ask = handler.index("if (typoSuggestion(email) && state.confirmedEmail !== email) {")
    assert ask < handler.index("leaveForCheckout(link, tagged, email);")
    # One read-back implementation, and the shared typo table is never redeclared.
    assert JOIN.count("function askAboutEmail(") == 1
    assert "const DOMAIN_FIXES" not in JOIN and "function suggestedEmail" not in JOIN
    assert JOIN.count('<script src="/email-check.js') == 1
    # The free paths keep their own rule.
    assert "if ((UPDATE_MODE || TRY_MODE) && !typoSettled(email)) return;" in handler


def test_while_the_read_back_is_open_unlock_steps_aside() -> None:
    assert '$("submit").hidden = true;' in _js_function(JOIN, "askAboutEmail")
    assert '$("submit").hidden = false;' in _js_function(JOIN, "closeEmailCheck")
    assert "#go-checkout[hidden],#submit[hidden]{display:none;}" in JOIN
    # The fix goes back in the field; the button naming the amount is next.
    use = _js_code(JOIN).split('$("check-use").addEventListener("click"')[1].split("\n});")[0]
    paid = use.split("if (go) {")[1].split("}")[0]
    assert "closeEmailCheck();" in paid and '$("submit").focus();' in paid
    assert "askAboutEmail" not in paid


def test_the_address_is_read_back_as_text_as_it_is_typed() -> None:
    echo = _js_function(JOIN, "drawEmailEcho")
    assert "innerHTML" not in echo and "address.textContent = email;" in echo
    assert 'document.createTextNode("Reports go to ")' in echo
    assert 'step3Action === "open"' in echo and '$("check-email").hidden' in echo
    for mode in ("!SEAT_MODE", "!UPDATE_MODE", "!TRY_MODE"):
        assert mode in echo
    typed = _js_code(JOIN).split('$("email").addEventListener("input", () => {')[1].split("});")[0]
    assert "drawEmailEcho();" in typed
    assert re.search(r'<input type="email" id="email"[^>]*>\s*<!--.*?-->\s*'
                     r'<p class="echo" id="email-echo" aria-live="polite" hidden></p>', JOIN, re.S)


def test_open_the_page_says_get_your_lineups_with_the_price_first() -> None:
    head = _flat(_js_function(JOIN, "drawBuyHeading"))
    assert '"Get your lineups"' in head
    assert '"Get your fantasy football lineups — Beat Your League"' in head
    assert "Paste your roster, then check out. The weekly report is " in head
    assert 'price.textContent = "$14.99 a month";' in head
    assert ("it stops on its own after your title game, with a full refund before your "
            "first weekly report's first game.") in head
    # Closed, the free check's own words, as the markup has them.
    assert "const FREE_HEAD = document.querySelector(\"header h1\").textContent;" in JOIN
    assert 'MONTHLY_STATE["header-pitch"]' in head
    assert "<h1>Check your team</h1>" in JOIN
    assert "<title>Check your fantasy football team — Beat Your League</title>" in JOIN
    # Every other visit keeps its own heading.
    assert "if (HEADING || chose2027 || SEAT_MODE || UPDATE_MODE || TRY_MODE || WANTS_PASS) return;" \
        in head
    # The button that checks stays what it is.
    assert '<button id="resolve" type="submit" form="form-roster">Check my team</button>' in JOIN


def test_the_menus_gold_item_follows_checkout() -> None:
    """The join page's Menu says the site's ask in today's words, with the
    same two labels the generated pages use (render.report.ask_label).

    Reproduction (integration, Nov 4 2026): the landing branch made the static
    item the open label to match site_bar, while the join branch fell back to
    the static text when the season closed, so the fallback became the buy
    label, set after footer.js had pointed the same link at the waitlist: a
    Menu item reading "Get my lineups" that opened the email capture. A season
    that is over is now left to footer.js."""
    from render import report as rr
    menu = _js_function(JOIN, "drawMenuGo")
    assert "if (!MENU_GO_LINK || seasonOver()) return;" in menu
    assert "monthlyLink() ? MENU_GO_OPEN : MENU_GO_CLOSED" in menu
    assert f'const MENU_GO_OPEN = "{rr.SAMPLE_CTA}";' in JOIN
    assert f'const MENU_GO_CLOSED = "{rr.CHECK_LABEL}";' in JOIN
    assert f'<a class="go" href="../join/index.html">{rr.ask_label()}</a>' in JOIN
    assert "drawMenuGo();" in _js_function(JOIN, "drawBuyState")


def test_the_pages_hold_hours_are_the_free_reports() -> None:
    """Free reports wait behind paid mail (run/trials.py held_for_tuesday and
    held_for_subscribers). The page says so from the same hours."""
    for name, value in (("TRIAL_HOLD_FROM", trials.REPORT_HOLD_FROM),
                        ("TRIAL_HOLD_UNTIL", trials.TUESDAY_RELEASE_HOUR),
                        ("TRIAL_SATURDAY_UNTIL", trials.SATURDAY_RELEASE_HOUR)):
        assert re.search(rf"^const {name} = {value};", JOIN, re.M), name


def _trial_harness() -> str:
    names = ("etHourWords", "paidMailFirst", "trialWindow", "trialWhenWords")
    consts = "\n".join(re.search(rf"^const {n} = \d+;", JOIN, re.M).group(0)
                       for n in ("TRIAL_HOLD_FROM", "TRIAL_HOLD_UNTIL", "TRIAL_SATURDAY_UNTIL"))
    return consts + "\n" + "\n".join(_js_function(JOIN, n) for n in names)


def test_the_free_report_note_names_the_wait_for_the_hour_it_is_asked() -> None:
    """Nov 4 2026 is a Wednesday. 2026-11-11 is the next report day."""
    w = {"lands_on": "2026-11-11", "first_kickoff": "2026-11-06T01:15:00Z"}
    cases = [
        # (UTC instant, TRIAL.when, expected wait)
        ("2026-11-04T11:59:00Z", None, "hour"),          # Wednesday, before the hold
        ("2026-11-04T12:00:00Z", None, "wednesday"),     # the hold, week.json not rebuilt
        ("2026-11-05T01:30:00Z", None, "wednesday"),     # Wednesday evening ET
        ("2026-11-05T01:30:00Z", "this", "hour"),        # the evening run rebuilt week.json
        ("2026-11-05T02:00:00Z", None, "hour"),          # the Thursday release
        ("2026-11-07T15:00:00Z", "this", "saturday"),    # a week that starts on Saturday
        ("2026-11-07T20:00:00Z", "this", "hour"),
        ("2026-11-07T15:00:00Z", "next", "scored"),      # this week underway
        ("2026-11-10T15:59:00Z", "next", "scored"),      # Monday night's box score
        ("2026-11-10T16:00:00Z", "next", "hour"),        # scored: Tuesday from 16:00 UTC
        ("2026-11-02T15:00:00Z", "this", "hour"),
        # The last 75 minutes before Thursday night's kickoff: trialTiming is
        # null there, and the next hourly run may land on either side of it.
        ("2026-11-05T23:59:00Z", None, "hour"),          # 76 minutes before
        ("2026-11-06T00:00:00Z", None, "kickoff"),
        ("2026-11-06T00:50:00Z", None, "kickoff"),
        ("2026-11-06T01:15:00Z", None, "hour"),          # kicked off, no lands_on reading
    ]
    script = _trial_harness() + "\nconst out = [];\n" + "".join(
        f"out.push(trialWindow({json.dumps({'when': t} if t else None)}, "
        f"{json.dumps(w)}, new Date({json.dumps(at)})));\n" for at, t, _ in cases) + \
        "out.push(trialWhenWords('wednesday', new Date('2026-11-04T13:00:00Z')));\n" \
        "out.push(trialWhenWords('wednesday', new Date('2026-09-16T13:00:00Z')));\n" \
        "out.push(trialWhenWords('saturday', new Date('2026-11-07T15:00:00Z')));\n" \
        "out.push(trialWhenWords('scored', new Date()));\n" \
        "out.push(trialWhenWords('hour', new Date()));\n" \
        "out.push(trialWhenWords('kickoff', new Date()));\n" \
        "console.log(JSON.stringify(out));"
    got = _node(script)
    assert got[:len(cases)] == [want for _, _, want in cases]
    wed, wed_summer, sat, scored, hour, kickoff = got[len(cases):]
    assert kickoff == ("goes out before this week's first game if it can. If not, it waits "
                       "until this week's games are scored, usually by Tuesday morning, so "
                       "it's never about games already underway")
    assert "within the hour" not in kickoff
    assert wed == "arrives this evening: from 7 AM ET on Wednesdays, the weekly reports go out first"
    assert wed_summer.startswith("arrives this evening: from 8 AM ET")      # EDT
    assert sat == "goes out after subscribers' Saturday check, usually by 3 PM ET"
    assert scored == ("goes out once this week's games are done and scored, usually by "
                      "Tuesday morning, so it's never about games already underway")
    assert hour == "usually lands within the hour"
    # The note keeps its static words for a page whose script never runs.
    note = re.search(r'<li id="trial-note"[^>]*>(.*?)</li>', JOIN, re.S).group(1)
    assert '<span id="trial-when">usually lands within the hour</span>' in note
    assert "drawTrialNote(new Date());" in _js_function(JOIN, "drawTrial")
    assert "drawTrialNote(new Date());" in _js_function(JOIN, "submitTrial")
    # Both waits are named in the line itself, so the static sentence after it goes.
    assert '$("trial-wait").hidden = window === "scored" || window === "kickoff";' in \
        _js_function(JOIN, "drawTrialNote")


def test_the_trade_checks_note_names_the_same_paid_mail_wait() -> None:
    """run/trades.py waits on run.trials.held_for_subscribers: the Wednesday
    run and Saturday's final check go first. The note said "usually lands
    within the hour" through both (review, Nov 4 2026). It reads the same
    hold as the free report (paidMailFirst), and never the kickoff rule,
    which the Trade Check doesn't apply."""
    harness = _trial_harness() + "\n" + "\n".join(
        _js_function(JOIN, n) for n in ("etDayEnd", "seasonClosed", "trialTiming",
                                        "drawTradeNote"))
    # Wednesday Nov 4: week.json holds Week 8 until the evening run rebuilds it as Week 9.
    fresh = {"season": "2026", "week": 9, "last_week": 18, "phase": "season",
             "first_kickoff": "2026-11-06T01:15:00Z", "lands_on": "2026-11-11"}
    last = dict(fresh, week=8, first_kickoff="2026-10-30T00:15:00Z", lands_on="2026-11-04")
    cases = [
        # (UTC instant, week.json, expected words after "the answer ")
        ("2026-11-04T11:00:00Z", last, "usually lands within the hour"),
        ("2026-11-04T13:00:00Z", None, "arrives this evening"),      # no week.json: held
        ("2026-11-04T13:00:00Z", last, "arrives this evening"),
        ("2026-11-05T00:30:00Z", fresh, "usually lands within the hour"),   # run finished
        ("2026-11-07T15:00:00Z", fresh, "goes out after subscribers' Saturday check"),
        ("2026-11-07T15:00:00Z", None, "goes out after subscribers' Saturday check"),
        ("2026-11-07T20:00:00Z", fresh, "usually lands within the hour"),
        ("2026-11-06T00:50:00Z", fresh, "usually lands within the hour"),   # no kickoff hold
    ]
    script = harness + "\nconst node = { textContent: '' };\nconst $ = () => node;\n" \
        "const out = [];\n" + "".join(
            f"drawTradeNote({json.dumps(w)}, new Date({json.dumps(at)})); "
            "out.push(node.textContent);\n" for at, w, _ in cases) + \
        "console.log(JSON.stringify(out));"
    got = _node(script)
    lead = "If this is the address your reports go to, the answer "
    for (at, _, want), words in zip(cases, got):
        assert words.startswith(lead + want), (at, words)
        assert words.endswith(". Up to three a day."), words
    # The trade branch draws it, week.json is read in that mode and redraws
    # it, and a press redraws it for the hour it is made.
    code = _js_code(JOIN)
    assert "drawTradeNote(null, new Date());" in code.split("if (TRADE_MODE) {", 1)[1][:400]
    assert "if ((UPDATE_MODE && !TRADE_MODE) || !window.fetch) return;" in code
    assert "if (TRADE_MODE) { drawTradeNote(w, now); return; }" in code
    assert "if (TRADE_MODE) drawTradeNote(state.week, new Date());" in \
        _js_function(JOIN, "submitUpdate")
    assert "usually lands within the hour. Up to three a day." not in _flat(code)


def test_after_a_free_report_request_the_plan_is_offered_once_quietly() -> None:
    trial = _js_function(JOIN, "submitTrial")
    ok = trial.split("if (!response.ok)")[1].split(".catch(")[0]
    assert "drawTrialOffer();" in ok
    offer = _js_function(JOIN, "drawTrialOffer")
    assert "TRY_MODE && Boolean(monthlyLink()) && !seasonOver()" in offer
    assert 'setAttribute("href", ownPlanHref())' in offer
    block = re.search(r'<p class="plan-offer" id="trial-plan" hidden>(.*?)</p>', JOIN, re.S).group(1)
    words = _flat(re.sub(r"<[^>]+>", " ", block))
    assert "Want it every Wednesday? Start the Monthly plan with this roster." in words
    assert "$14.99 a month. It stops on its own after your title game, with a full refund " \
           "before your first weekly report's first game." in words
    assert 'class="ghost"' in block
    # One encoder: the offer is ownPlanHref's Monthly ref.
    assert JOIN.count('R.encodeRoster("monthly"') == 1
    # The week clock's two rules reach the free report too.
    handler = _js_code(JOIN).split("if (TRY_MODE) {\n          TRIAL = trialTiming(w, now);")[1]
    assert 'if (seasonClosed(w, now)) FIRST = { when: "over" };' in handler.split("return;")[0]
    assert 'if (w && w.phase === "preseason") MONTHLY_PAUSED = true;' in handler.split("return;")[0]


# --------------------------------------------------------------------- #
# in a real browser
# --------------------------------------------------------------------- #

def _week_json(now: datetime) -> dict:
    kickoff = now + timedelta(days=2)
    return {"season": str(now.year), "week": 9, "last_week": 18, "phase": "season",
            "first_kickoff": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lands_on": (now + timedelta(days=6)).strftime("%Y-%m-%d"),
            "week_ends": (now + timedelta(days=5)).strftime("%Y-%m-%d")}


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """site/ copied with the payment links and form endpoint on stand-ins,
    served from its own root (the typo table is /email-check.js), with a
    week.json that puts the visit before a week's first kickoff."""
    from run.launch_check import _browser_tools, _serving, flow_roster, join_copy
    tools = _browser_tools()
    if not tools:
        pytest.skip("needs Chrome and node")
    site = tmp_path_factory.mktemp("join-checkout") / "site"
    with _serving(site) as base:
        assert join_copy(site, base, links_open=True) == []
        (site / "week.json").write_text(json.dumps(_week_json(datetime.now(timezone.utc))),
                                        encoding="utf-8")
        roster, ids = flow_roster(site / "join" / "players.json")
        yield {"base": base, "tools": tools, "roster": roster, "ids": ids}


def _run(served, jobs: list[dict]) -> list[dict]:
    chrome, node = served["tools"]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(jobs, fh)
    try:
        done = subprocess.run([node, str(STEPS), served["base"], chrome, fh.name],
                              capture_output=True, text=True, timeout=240)
    finally:
        Path(fh.name).unlink(missing_ok=True)
    results = json.loads(done.stdout or "[]")
    if results and "fatal" in results[0]:
        pytest.skip(results[0]["fatal"])
    for result in results:
        assert not result.get("error"), result
        assert not result.get("errors"), result
    return results


READY = {"until": "typeof state !== 'undefined' && !!state.directory", "ms": 15000}
# Visible gold buttons and links inside the viewport.
GOLDS = f"""(() => [...document.querySelectorAll("button, a")].filter((el) => {{
  const s = getComputedStyle(el), r = el.getBoundingClientRect();
  return !el.closest("details:not([open]) .sitemenu-list") &&
    s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0 &&
    r.bottom > 0 && r.top < innerHeight && s.backgroundColor === "{GOLD}";
}}).map((el) => el.id || el.textContent.trim()))()"""
IN_VIEW = """((id) => { const r = document.getElementById(id).getBoundingClientRect();
  return r.top >= 0 && r.bottom <= innerHeight; })"""
AT_EMAIL = """(() => ({ top: Math.round(document.getElementById("step-email").getBoundingClientRect().top),
  focus: document.activeElement && document.activeElement.id,
  end: Math.ceil(scrollY + innerHeight) >= document.documentElement.scrollHeight - 2,
  half: Math.round(innerHeight / 2) }))()"""


def _landed(at: dict) -> bool:
    """Step 3 at the top of the screen, or as near as the page can scroll it
    (at 1440 the page ends before step 3 can reach the top), with the email
    field focused."""
    return at["focus"] == "email" and (0 <= at["top"] <= 40 or
                                       (at["end"] and 0 <= at["top"] <= at["half"]))


def _check(roster: str) -> list:
    return [READY, f"""(() => {{ const box = document.getElementById("roster-text");
      box.value = {json.dumps(roster)}; box.dispatchEvent(new Event("input", {{ bubbles: true }}));
      document.getElementById("resolve").click(); return state.ready; }})()""",
            {"sleep": 1300}]


def _type_email(address: str) -> str:
    return f"""(() => {{ const f = document.getElementById("email"); f.value = {json.dumps(address)};
      f.dispatchEvent(new Event("input", {{ bubbles: true }}));
      return document.getElementById("email-echo").textContent; }})()"""


def _buy_steps(roster: str) -> list:
    return _check(roster) + [
        "document.querySelector('header h1').textContent",
        "document.title",
        "document.querySelector('.sitemenu-list a.go').textContent",
        f"{IN_VIEW}('go-checkout')",
        GOLDS,
        "document.getElementById('resolve').classList.contains('is-done')",
        "document.getElementById('header-pitch').textContent.replace(/\\s+/g, ' ')",
        "document.getElementById('go-checkout').click()",
        {"sleep": 1500},
        AT_EMAIL,
        _type_email("pat@example.com"),
        GOLDS,
        "R.withVia(checkoutRef(), SOURCE)",
        "document.getElementById('submit').click()",
        {"sleep": 1500},
    ]


def _typo_steps(roster: str) -> list:
    return _check(roster) + [
        "document.getElementById('go-checkout').click()",
        {"sleep": 1200},
        _type_email("pat@gmial.com"),
        "document.getElementById('submit').click()",
        {"sleep": 400},
        """(() => ({ box: document.getElementById("check-email").hidden,
            submit: getComputedStyle(document.getElementById("submit")).display,
            use: document.getElementById("check-use").textContent,
            yes: document.getElementById("check-yes").textContent }))()""",
        GOLDS,
        "document.getElementById('check-use').click()",
        """(() => ({ value: document.getElementById("email").value,
            box: document.getElementById("check-email").hidden,
            focus: document.activeElement.id,
            echo: document.getElementById("email-echo").textContent }))()""",
        "document.getElementById('submit').click()",
        {"sleep": 1500},
    ]


def _stale_steps(roster: str) -> list:
    trimmed = "\n".join(roster.strip().splitlines()[:-1]) + "\n"
    return _check(roster) + [
        f"""(() => {{ const box = document.getElementById("roster-text");
          box.value = {json.dumps(trimmed)}; box.dispatchEvent(new Event("input", {{ bubbles: true }}));
          const go = document.getElementById("go-checkout");
          return {{ hidden: go.hidden, stale: go.classList.contains("is-stale"),
                    gold: getComputedStyle(go).backgroundColor === "{GOLD}",
                    resolveDone: document.getElementById("resolve").classList.contains("is-done") }}; }})()""",
        "document.getElementById('go-checkout').click()",
        {"sleep": 1500},
        "({ ready: state.ready, stale: state.stale, n: state.matches.length })",
        AT_EMAIL,
    ]


def _trial_steps(roster: str) -> list:
    return _check(roster) + [
        "document.getElementById('go-checkout').hidden",
        "document.querySelector('header h1').textContent",
        _type_email("pat@example.com"),
        "document.getElementById('submit').click()",
        {"until": "getComputedStyle(document.getElementById('done')).display === 'block'",
         "ms": 8000},
        """(() => ({ hidden: document.getElementById("trial-plan").hidden,
            href: document.getElementById("trial-plan-link").getAttribute("href"),
            when: document.getElementById("trial-when").textContent }))()""",
        GOLDS,
    ]


def _mode_steps(roster: str) -> list:
    return _check(roster) + ["document.querySelector('header h1').textContent",
                             "document.getElementById('go-checkout').hidden"]


OTHER_MODES = [("?plan=pass", "Cover your whole league"), ("?update=1", "Update your roster"),
               ("?add=1", "Add a team"), ("?trade=1", "Check a trade")]
RESTORED_WAIT = [{"until": "typeof state !== 'undefined' && state.ready === true", "ms": 15000},
                 {"sleep": 1500}]
RESTORED = RESTORED_WAIT + [
            AT_EMAIL,
            "!document.getElementById('restored-line').hidden",
            "document.getElementById('restored-line').textContent",
            "Math.round(scrollY)"]


def _restored_edit_steps() -> list:
    """A restored roster is never checked, so the re-check a press of the
    edited way on makes is the panel's FIRST entrance, whose scroll used to
    pull the page back up to the button (review, Nov 4 2026)."""
    return RESTORED_WAIT + [
        """(() => { const box = document.getElementById("roster-text");
          box.scrollIntoView({ block: "center" });
          box.value = box.value.trim().split("\\n").slice(0, -1).join("\\n") + "\\n";
          box.dispatchEvent(new Event("input", { bubbles: true }));
          const go = document.getElementById("go-checkout");
          go.scrollIntoView({ block: "center" });
          return { hidden: go.hidden, stale: go.classList.contains("is-stale") }; })()""",
        "document.getElementById('go-checkout').click()",
        {"sleep": 2500},
        "({ ready: state.ready, stale: state.stale, played: state.payoffPlayed })",
        AT_EMAIL,
    ]


@pytest.fixture(scope="module")
def ran(served) -> dict:
    """Every walk, in one Chrome: the buy flow at 390 and 1440, a typo, an
    edit after the check, reduced motion, a free report and the other modes;
    then the buy flow's own roster brought back by ?ref=, as the bye planner
    sends it."""
    roster = served["roster"]
    jobs = {
        "buy-390": ("join/index.html?via=byes", 390, False, _buy_steps(roster)),
        "buy-1440": ("join/index.html", 1440, False, _buy_steps(roster)),
        "typo": ("join/index.html", 390, False, _typo_steps(roster)),
        "stale": ("join/index.html", 390, False, _stale_steps(roster)),
        "reduced": ("join/index.html", 390, True, _check(roster) + [
            "document.getElementById('go-checkout').click()", AT_EMAIL]),
        "trial": ("join/index.html?try=1&via=reddit", 390, False, _trial_steps(roster)),
    }
    jobs.update({query: ("join/index.html" + query, 390, False, _mode_steps(roster))
                 for query, _ in OTHER_MODES})
    results = _run(served, [{"path": path, "width": width, "reduced": reduced, "steps": steps}
                            for path, width, reduced, steps in jobs.values()])
    got = dict(zip(jobs, results))
    ref = got["buy-390"]["values"][15]
    back = _run(served, [
        {"path": f"join/index.html?ref={ref}", "width": 390, "steps": RESTORED},
        {"path": f"join/index.html?ref={ref}&try=1", "width": 390, "steps": RESTORED},
        {"path": f"join/index.html?ref={ref}", "width": 1440, "steps": RESTORED},
        {"path": f"join/index.html?ref={ref}", "width": 390, "steps": _restored_edit_steps()},
    ])
    got.update({"ref": ref, "back-buy": back[0], "back-try": back[1], "back-1440": back[2],
                "back-edit": back[3]})
    return got


@pytest.mark.parametrize("width", [390, 1440])
def test_a_ready_buyer_presses_once_to_reach_the_email_and_once_to_reach_stripe(
        ran, width) -> None:
    result = ran[f"buy-{width}"]
    v = result["values"]
    assert v[1] is True                                       # the roster checks out
    assert v[3] == "Get your lineups"
    assert v[4] == "Get your fantasy football lineups — Beat Your League"
    assert v[5] == "Get my lineups"
    assert v[6] is True, "the way on is off the screen after the check"
    assert v[7] == ["go-checkout"], v[7]                      # one gold on screen
    assert v[8] is True
    assert v[9].strip().startswith("Paste your roster, then check out.") and "$14.99 a month" in v[9]
    assert _landed(v[12]), v[12]
    assert v[13] == "Reports go to pat@example.com"
    assert v[14] == ["submit"], v[14]
    # One press: straight to Stripe, with the ref and the address as typed.
    (handoff,) = result["handoffs"]
    assert "locked_prefilled_email=pat%40example.com" in handoff
    sent = handoff.split("client_reference_id=", 1)[1].split("&", 1)[0]
    assert sent == v[15]
    assert decode_roster(sent).plan == "monthly"


def test_a_likely_typo_opens_the_read_back_with_one_gold_button(ran) -> None:
    result = ran["typo"]
    v = result["values"]
    asked = v[8]
    assert asked["box"] is False and asked["submit"] == "none", asked
    assert asked["use"] == "Use pat@gmail.com"
    assert asked["yes"] == "Continue to checkout — $14.99/mo"     # names the amount
    assert v[9] == ["check-use"], v[9]
    fixed = v[11]
    assert fixed == {"value": "pat@gmail.com", "box": True, "focus": "submit",
                     "echo": "Reports go to pat@gmail.com"}, fixed
    (handoff,) = result["handoffs"]
    assert "locked_prefilled_email=pat%40gmail.com" in handoff


def test_one_press_rechecks_an_edited_roster_and_goes_on(ran, served) -> None:
    v = ran["stale"]["values"]
    assert v[3] == {"hidden": False, "stale": True, "gold": False, "resolveDone": False}, v[3]
    assert v[6] == {"ready": True, "stale": False, "n": len(served["ids"]) - 1}, v[6]
    assert _landed(v[7]), v[7]


def test_reduced_motion_jumps_to_the_email(ran) -> None:
    at = ran["reduced"]["values"][-1]
    assert _landed(at), at


def test_a_restored_roster_lands_on_the_email_in_buy_mode_only(ran) -> None:
    assert decode_roster(ran["ref"]).via == "byes"
    buy, free, wide = (ran[k]["values"] for k in ("back-buy", "back-try", "back-1440"))
    assert _landed(buy[2]), buy[2]
    assert buy[3] is True and buy[4] == "Changed your roster since? Edit it above before you pay."
    assert _landed(wide[2]) and wide[3] is True, wide
    # The free report keeps its own path: nothing scrolls, no line.
    assert free[2]["focus"] != "email" and free[3] is False and free[5] == 0, free


def test_a_restored_then_edited_roster_still_lands_on_the_email(ran) -> None:
    v = ran["back-edit"]["values"]
    assert v[2] == {"hidden": False, "stale": True}, v[2]
    assert v[5] == {"ready": True, "stale": False, "played": True}, v[5]
    assert _landed(v[6]), v[6]


def test_a_free_report_request_ends_on_one_quiet_offer(ran) -> None:
    result = ran["trial"]
    v = result["values"]
    assert v[3] is True and v[4] == "Get a free report"
    assert v[5] == ""                                         # no "Reports go to" here
    assert v[7] is True and len(result["posted"]) == 1
    offer = v[8]
    assert offer["hidden"] is False
    href = offer["href"]
    assert href.startswith("index.html?ref=") and "&" not in href and "@" not in href
    assert "try" not in href and "via=" not in href
    roster = decode_roster(href.split("?ref=", 1)[1])
    assert roster.plan == "monthly" and roster.via == "reddit"
    assert offer["when"] in ("usually lands within the hour",
                             "goes out after subscribers' Saturday check, usually by 3 PM ET",
                             "goes out after subscribers' Saturday check, usually by 4 PM ET")
    assert v[9] == [], v[9]                                    # the offer is not a gold button


@pytest.mark.parametrize("query, heading", OTHER_MODES)
def test_every_other_mode_keeps_its_own_way(ran, query, heading) -> None:
    assert ran[query]["values"][-2:] == [heading, True], ran[query]["values"]
