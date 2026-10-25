"""Contract tests for the public funnel.

These guard the promises the funnel makes to a buyer. They exist because the
pressure to quietly remove them — hide the refund line, bury cancellation,
drop the "no free tier" honesty, let a number lose its source — always arrives
later, dressed as conversion optimisation. A failing test here means someone
is about to ship a dark pattern (PLAN.md §4, CLAUDE.md principle 3).
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest
from conftest import requires_demo_render, requires_sample_league

SITE = Path(__file__).resolve().parent.parent / "site"
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
# The published grading (owner direction, Sep 29 2026): kept live as the record,
# never linked from a page that sells, and kept out of search results.
_EVIDENCE_PAGES = ("backtest.html", "confidence.html", "projections.html",
                   "no-call.html", "compare/index.html", "ledger/index.html")
ROSTER_JS = (SITE / "join" / "roster.js").read_text(encoding="utf-8")
LEDGER = (SITE / "ledger" / "index.html").read_text(encoding="utf-8")
COMPARE = (SITE / "compare" / "index.html").read_text(encoding="utf-8")
PROJECTIONS = (SITE / "projections.html").read_text(encoding="utf-8")
NO_CALL = (SITE / "no-call.html").read_text(encoding="utf-8")
CONFIDENCE = (SITE / "confidence.html").read_text(encoding="utf-8")
HOW = (SITE / "how-it-works.html").read_text(encoding="utf-8")


def prose(page: str) -> str:
    """Copy as a reader meets it: JS string concatenation joined and whitespace
    collapsed, so assertions test the sentence rather than how it wrapped."""
    joined = re.sub(r'"\s*\+\s*"', "", re.sub(r"\s+", " ", page))
    return joined


def markup_only(page: str) -> str:
    """Page with <script> blocks removed — what is actually rendered today."""
    return re.sub(r"<script\b.*?</script>", "", page, flags=re.S | re.I)


LANDING_PROSE, JOIN_PROSE = prose(LANDING), prose(JOIN)

# What the odds gate checks, in the selling pages' plain words (COPY:F7).
# "wherever both players are healthy and playing" promised odds on a pair the
# gate withholds — every team defense (graded D), every pair short of its
# record — and claimed health a Tuesday report cannot know. Then "wherever"
# itself (COPY-3, contract C5): the rising hold and the practice squad
# withhold odds on pairs that pass all three checks, so the clause states the
# checks as NECESSARY ("only where"), never as sufficient.
GATE_CLAUSE = ("only where both players are playing, off the injury report and have "
               "enough games on record (never on team defenses)")


def _price(pattern: str) -> str:
    """Read a price off the landing page's own pricing card.

    The tests below protect PLACEMENT and COUNT — the price is stated in the
    hero, it appears only at decision points, every renewal disclosure names an
    amount. None of that is a claim about the number itself, and hardcoding it
    meant a price change failed five tests that had nothing to say about the
    change. The number is checked in exactly one place:
    test_monthly_price_never_undercuts_the_season_pass, which is the only
    assertion that is genuinely about the figures.
    """
    match = re.search(pattern, markup_only(LANDING))
    assert match, f"could not read a price off the landing page: {pattern}"
    return match.group(1)


# 2026 sells one-time passes (owner decision, Oct 18 2026): the pass card's
# price is "/ rest of season". Monthly is off the landing this season; its
# price is still read, off the join page's (hidden) plan option.
SEASON_PRICE = _price(r'id="pass-price">\$(\d+) <small>/ rest of season')
MONTHLY_PRICE = re.search(r"Monthly · \$(\d+\.\d\d)", (SITE / "join" / "index.html")
                          .read_text(encoding="utf-8")).group(1)


# --------------------------------------------------------------------- #
# consumer protections — the anti-dark-pattern contract
# --------------------------------------------------------------------- #

def test_refund_promise_is_stated_where_money_is_asked_for() -> None:
    for page, name in ((LANDING, "landing"), (JOIN, "join")):
        assert re.search(r"refund", page, re.I), f"{name} page dropped the refund promise"
    assert re.search(r"no-questions", LANDING, re.I)


def test_refund_limit_is_disclosed_before_purchase_not_after() -> None:
    """The one-per-person limit closes the refund-cycling loop only if the buyer
    is told up front — otherwise it's a trap sprung at claim time."""
    for page, name in ((LANDING_PROSE, "landing"), (JOIN_PROSE, "join")):
        assert re.search(r"one per person", page, re.I), \
            f"{name} page states no refund limit, so the stated limit is unenforceable"
        assert re.search(r"final", page, re.I)


def _buyer_surfaces() -> dict[str, str]:
    """Every published page plus the retainable welcome email: anywhere a
    buyer is told what they are entitled to."""
    import render.welcome as welcome
    pages = {str(p.relative_to(SITE)): p.read_text(encoding="utf-8")
             for p in SITE.rglob("*.html")}
    pages["render/welcome.py"] = " ".join(
        (welcome.REFUND_TERMS, welcome.REFUND_TERMS_LEAGUE))
    return pages


def test_every_page_but_the_home_page_has_a_home_button() -> None:
    """The only way back to the front page was the wordmark, and on terms,
    privacy, thanks and join only its WORDS were a link — the logo beside them
    was not. The two published samples had no way back at all: a buyer who
    opened one from the landing page left it with the browser's back button or
    not at all. A wordmark is a convention an experienced visitor knows and a
    less experienced one does not, so every page carried a labelled button,
    above its headline, beside a wordmark that is one link logo and all.

    Contract C2 (launch review D5, Oct 2026) retired the pill: at 390px it
    wrapped onto a row of its own under the routes, repeating a link the
    logo lockup already is, and the nav it now sits in names its routes in
    words (tests/test_prelaunch_pages.py holds the pages that carry it). What
    stays pinned here, on every page, is the way home above the headline.

    legal.html is a redirect stub and is never seen."""
    for path in sorted(SITE.rglob("*.html")):
        rel = path.relative_to(SITE).as_posix()
        if rel in ("index.html", "legal.html"):
            continue
        # 404.html is served for a mistyped URL at ANY depth, so its links are
        # root-absolute; every other page is reached at a known place.
        root = "/" if rel == "404.html" else re.escape("../" * rel.count("/") + "index.html")
        top = (path.read_text(encoding="utf-8")
               .split("<body", 1)[1].split("<h1", 1)[0])
        assert re.search(rf'<a class="brand" href="{root}"', top), \
            f"{rel}'s wordmark is not one link home, logo and all, above its headline"


def test_a_subscribers_own_report_carries_no_home_button() -> None:
    """The button is for visitors to the site. A subscriber's report is opened
    from their inbox, and its masthead must stay what it was."""
    from render.report import header
    meta = {"league_name": "Your Team", "num_teams": 12, "week": 5, "solo": True}
    masthead = header(meta)
    assert 'class="home"' not in masthead
    assert '<div class="brand">' in masthead
    # A published sample is a site page: it carries the site's nav (C2).
    assert 'class="sitenav"' in header({**meta, "historical_demo": True,
                                        "anonymized_demo": True, "season": 2024})


def test_the_join_sidebar_sells_only_to_a_buyer_and_quotes_the_real_count() -> None:
    """The join page's sidebar (Sep 29 2026) carries purchase copy: refund
    terms and "your first file today". A seat holder pays nothing and an
    update comes from an existing subscriber, so the sidebar must hide in both
    modes — the seat flow once shipped refund language about money a seat
    holder never spent. Since Sep 29 2026 (owner direction) it sells the file,
    not the grading: no backtest count and no link to a grading page."""
    assert '<aside class="side">' in JOIN
    guard = re.search(r"if \(SEAT_MODE \|\| UPDATE_MODE \|\| TRY_MODE\) \{(.*?)\n\}", JOIN, re.S)
    assert guard and "side.hidden = true" in guard.group(1), \
        "the sidebar's purchase copy shows to seat holders and updaters"
    side = JOIN.split('<aside class="side">')[1].split("</aside>")[0]
    assert not re.findall(r"\b\d{1,3},\d{3}\b", side), "a backtest count is back in the sidebar"
    for page in _EVIDENCE_PAGES:
        assert page not in side, f"the sidebar links the grading page {page}"


def test_the_refund_window_is_counted_from_the_purchase_not_the_calendar() -> None:
    """"Through Week 2" gave a buyer who joined in Week 3 no window at all,
    while the pricing card beside the button still sold them one — the
    promise a reader relies on, voided by a date they were never shown.

    Reproduction: the site went on selling from Week 4 of 2026 under exactly
    that wording. The window is the buyer's own first two weekly files, so it
    exists whenever in the season they join."""
    calendar = re.compile(
        r"refund[^.<]{0,60}\b(?:through|until|in|during)\s+(?:the\s+)?"
        r"(?:week[\s-]*\d|first\s+two\s+weeks)", re.I)
    for name, page in _buyer_surfaces().items():
        text = re.sub(r"<!--.*?-->", "", prose(page), flags=re.S)
        assert not calendar.search(text), \
            f"{name} ties the refund window to a calendar week"
        assert not re.search(r"week[\s-]*2 refund|refund window closes[^.]{0,40}week",
                             text, re.I), \
            f"{name} names a calendar refund window"
    for name, page in (("landing", LANDING_PROSE), ("join", JOIN_PROSE),
                       ("league pass", prose((SITE / "league-pass.html")
                                             .read_text(encoding="utf-8"))),
                       ("terms", prose((SITE / "terms.html")
                                       .read_text(encoding="utf-8")))):
        assert re.search(r"first two weekly reports|second weekly report", page, re.I), \
            f"{name} page lost the refund window where the money is asked for"


def test_the_refund_window_closes_before_the_second_file_is_played() -> None:
    """A window that ran "a week after your second weekly file" let a buyer
    set that file's lineup, watch the games settle it, and refund on the
    result — the second file used in full, then returned. The window closes
    when the second file's week kicks off: both files are in hand, the first
    one's week has played out, and the second has not been put to use yet.

    Every surface has to say the same close, or the loosest one is the
    promise: "through your first two weekly files" reads as the end of the
    second file's games, which is the week this change takes back."""
    import render.welcome as welcome
    loose = re.compile(r"a\s+week\s+after\s+your\s+second\s+weekly"
                       r"|through\s+your\s+first\s+two\s+weekly", re.I)
    for name, page in _buyer_surfaces().items():
        text = re.sub(r"<!--.*?-->", "", prose(page), flags=re.S)
        assert not loose.search(text), \
            f"{name} still promises a refund after the second file's games"
    kickoff = re.compile(r"second\s+weekly\s+report's\s+week\s+kicks\s+off", re.I)
    # COPY:F8: the selling pages used to say it shorter ("your second report's
    # week kicks off") beside a card that calls the day-one ROSTER report "your
    # first report" — so a mid-week joiner read a window a week shorter than
    # terms §5's, which counts weekly reports only. Every surface says "weekly".
    for name, page in _buyer_surfaces().items():
        text = re.sub(r"<!--.*?-->", "", prose(page), flags=re.S)
        assert not re.search(r"second\s+report's\s+week", text, re.I), \
            f"{name} counts the refund window in reports, not weekly reports"
    for name, page in (("landing", LANDING_PROSE), ("join", JOIN_PROSE)):
        assert kickoff.search(page), f"{name} page does not say when the window closes"
    for name, page in (
                       ("league pass", prose((SITE / "league-pass.html")
                                             .read_text(encoding="utf-8"))),
                       ("thanks", prose((SITE / "thanks.html")
                                        .read_text(encoding="utf-8"))),
                       ("terms", prose((SITE / "terms.html")
                                       .read_text(encoding="utf-8")))):
        assert kickoff.search(page), f"{name} page does not say when the window closes"
    assert kickoff.search(welcome.REFUND_TERMS)
    assert kickoff.search(welcome.REFUND_TERMS_LEAGUE)


def test_a_seat_claimed_in_week_1_is_promised_the_roster_report_it_gets() -> None:
    """COPY:F5's twins, reproduced: league-pass.html (FAQ, JSON-LD, step 3)
    and the join page's seat note promised a seat claimed before a week's
    games "that week's lineup if the week's games haven't started" — but
    run/intake._first_file sends a weekly report only from Week 2, so all
    through Week 1 the first email is the roster report. The welcome email's
    "Today" row (render/welcome.NEXT_TODAY) said the same untrue thing to
    every Week-1 buyer and seat, and is held to the same sentence."""
    from render.welcome import NEXT_TODAY
    lp = prose((SITE / "league-pass.html").read_text(encoding="utf-8"))
    seat = prose(re.search(r'<li id="seat-note"[^>]*>(.*?)</li>', JOIN, re.S).group(1))
    for name, text in (("league pass", lp), ("seat note", seat), ("welcome", NEXT_TODAY)):
        assert not re.search(r"(?:that|this) week's (?:lineup|report) if the week's", text,
                             re.I), name
        if name == "league pass" and not re.search(r"(?:that|this) week's lineup", text, re.I):
            # Oct 21 2026 (fewer words): the page promises "a first report the
            # day they confirm" and names no particular one, which is true of both.
            continue
        assert re.search(r"(?:that|this) week's (?:lineup|report) if it's Week 2 or later "
                         r"and the week's games haven't started, otherwise (?:their|your) "
                         r"roster report", text, re.I), name


def test_the_seat_page_says_a_claim_waits_for_its_inbox() -> None:
    """OPS-R1, the join page's half, reproduced: a seat claim became a seat
    only once the claimed address pressed a mailed button (run/intake.py
    sweep_seats), and the page still answered a claim with "Your seat request
    is in." and promised a first report "the day the seat is matched" — so a
    leaguemate who never opened the email waited for a report that could not
    come. The page says the button is coming, that nothing is set up until
    it is pressed and for how long it works, and times the first report from
    the confirmation. Never "we've emailed": the next hourly run sends it
    (FUNNEL F11's rule)."""
    from run.updates import EXPIRY_DAYS
    seat = prose(re.search(r'<li id="seat-note"[^>]*>(.*?)</li>', JOIN, re.S).group(1))
    for promise in ("We'll email a button to the address you entered, usually within the hour",
                    "Nothing is set up until it's pressed",
                    f"the button works for {EXPIRY_DAYS} days",
                    "Your first report lands the day you confirm",
                    "or your league's seats are all taken, we email you to say so"):
        assert promise in seat, promise
    assert "We've emailed" not in seat and "matched to the pass" not in seat
    submit = _js_function(JOIN, "submitSeat")
    assert '$("done-head").textContent = "Next: confirm your seat from your inbox.";' in submit
    assert "Your seat request is in" not in JOIN
    # The header chips went in the truth pass (the button already says what
    # is open); the sidebar line still times a seat's report from its
    # confirmation, never a match.
    draw = _js_function(JOIN, "drawFirst")
    assert "matched" not in draw
    assert 'SEAT_MODE ? "the day your seat is confirmed" : "the day you join"' in draw


def test_the_week_2_promise_names_exactly_the_setups_that_get_early_odds() -> None:
    """COPY:F12, reproduced: the FAQ and its JSON-LD said "full-PPR 12-team
    standard lineups get them from Week 2", but run/solo.seeded_scope wants
    the exact measured template — a "Standard · ESPN's default" lineup with
    No K or No DEF, offered on join, gets no odds until Week 4. The sentence
    is checked against the scope function over every shape the page offers."""
    from engine.subscriber import LINEUP_SHAPES, RosterSpec
    from render.sample import SAMPLE_ROSTER
    from run.solo import seeded_scope
    early = sorted(code for code, shape in LINEUP_SHAPES.items()
                   if seeded_scope(RosterSpec(player_ids=SAMPLE_ROSTER, slots=shape.slots,
                                              scoring="ppr", label="x"), 12, week=2))
    assert early == ["std"], early     # standard, with a kicker and a defense
    for scoring, size in (("half_ppr", 12), ("ppr", 10)):
        assert not seeded_scope(RosterSpec(player_ids=SAMPLE_ROSTER, slots=LINEUP_SHAPES["std"].slots,
                                           scoring=scoring, label="x"), size, week=2)
    said = ("full-PPR, 12-team standard lineups that start a kicker and a defense get "
            "them from Week 2, and every other setup from Week 4")
    # Mid-season (Oct 21 2026) the FAQ no longer carries the early-season
    # ramp; wherever the landing states it, it states exactly this.
    shown = prose(markup_only(LANDING))
    if "from Week 2" in shown:
        assert said in shown
    assert "full-PPR 12-team standard lineups get them from Week 2" not in LANDING_PROSE


def test_the_terms_define_the_file_the_refund_window_counts() -> None:
    """A window counted in files is only as firm as the definition of a file.
    Without one, "my day-one roster file was the first" and "the season ended
    before my second" are both arguments the terms page must already have
    settled, and a window that never closes is the one without an end date."""
    terms = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    section = terms.split('id="refunds"', 1)[1].split("<h2", 1)[0]
    assert re.search(r"your second weekly\s+report's\s+week\s+kicks\s+off", section, re.I)
    assert re.search(r"first game of the week that report\s+covers", section, re.I), \
        "\"kicks off\" needs the game it means, or Sunday's slate is an argument"
    assert re.search(r"weekly report covers one week", section, re.I)
    assert re.search(r"roster report[^.]*isn't one", section, re.I)
    assert re.search(r"season ends before your second", section, re.I), \
        "a buyer who joins in the last fortnight has a window with no end"
    assert re.search(r"reaches you after its week has kicked off[^.]*"
                     r"a week after it reaches you", section, re.I), \
        "a late send would close the window before the second file arrived"


def test_cancellation_is_promised_and_never_obstructed() -> None:
    """Subscribers must be told they can leave, in plain words. (Read as a
    reader meets it: the monthly terms say "Cancel yourself any time" across a
    JS string join, now that the header chip that also said it is gone.)"""
    assert re.search(r"cancel yourself any time|cancel any time", JOIN_PROSE, re.I), \
        "join page must tell subscribers they can cancel themselves"
    assert re.search(r"nothing to cancel", JOIN_PROSE, re.I), "the one-payment pass says so"
    # 2026's one-time passes have nothing to cancel, and the card says so.
    assert re.search(r"cancel any time|nothing to cancel", LANDING, re.I)
    # No copy anywhere that gates leaving behind contacting us.
    for page in (LANDING, JOIN):
        assert not re.search(r"contact us to cancel|email us to cancel|call to cancel",
                             page, re.I)


def test_the_launch_waitlist_states_exactly_what_it_will_send() -> None:
    """Checkout is closed and the product is being rebuilt, so the only honest
    ask on this page is a waitlist. It must say what arrives, how often, and how
    to leave — a list that promises "updates" and then mails weekly is how a
    launch burns the audience it spent three weeks collecting.

    How to leave must be a route that exists. The hero promised "unsubscribe
    in one click", while the launch email (run/waitlist.py) offers a reply or
    the mail app's button, actioned within 10 business days, and delivery
    deliberately sends no List-Unsubscribe-Post — there is no one-click route
    (launch audit C11)."""
    assert 'id="watch-form"' in LANDING
    assert re.search(r"unsubscribe any time", LANDING, re.I)
    assert not re.search(r"unsubscribe in one click|one-click unsubscribe",
                         prose(LANDING), re.I), \
        "the waitlist promises a one-click unsubscribe nothing provides"
    assert re.search(r"no card", LANDING, re.I)
    # The volume promise is the part that must not go missing.
    assert re.search(r"exactly one message|one email when (?:signups|checkout) open",
                     LANDING_PROSE, re.I), \
        "the waitlist must state how many emails it will send"


def test_the_waitlist_never_claims_to_have_recorded_an_address_it_did_not() -> None:
    """Same rule the picker follows: with no backend wired, say so. A cheerful
    confirmation over a discarded address is the worst outcome available — the
    person believes they will hear from us and never does."""
    handler = LANDING.split("const watchForm")[1]
    # ONLY the no-backend block. The mailto fallback below it legitimately says
    # "you're on the list", because there the address really does reach us —
    # banning the phrase everywhere tests the wrong thing.
    closed = handler.split("if (!CONTACT_EMAIL)")[1].split("return;")[0]
    assert "nothing was recorded" in closed
    assert not re.search(r"you're on the list|we'll email you", closed, re.I), \
        "the page claimed a signup that nothing recorded"


def test_paid_from_day_one_is_stated_not_hidden() -> None:
    # The protection is that paid-from-day-one is STATED, not hidden. The pin
    # has moved twice with owner decisions, and both moves are recorded so the
    # next reader knows which is current: price-in-hero was chosen Aug 13 as
    # the strongest disclosure form; on Aug 24 the owner revised it — value
    # before cost, price at the decision point — so the disclosure now lives
    # in the pricing section (plainly, with currency and renewal terms) and on
    # the join page. What may never come back: a page that hides that it
    # charges until after someone invests effort.
    assert 'id="pass-price">$' + SEASON_PRICE in markup_only(LANDING), \
        "the pricing section must state the season price plainly"
    # The join page states the price in its opening line, before a single
    # roster name is typed (the phrase "a paid product from day one" went Sep
    # 29 2026 as internal-sounding; the price itself is the disclosure).
    pitch = re.search(r'<p id="header-pitch">(.*?)</p>', JOIN, re.S).group(1)
    assert f"{SEASON_PRICE} for the rest of the season" in pitch
    # And no free-tier implication anywhere: the only free thing is the
    # waitlist email, which says exactly what it is.
    assert not re.search(r"\bfree trial\b|\bfor free\b", LANDING_PROSE, re.I)


def test_price_appears_only_at_decision_points_and_renewal_terms() -> None:
    """TWO rendered season prices, each load-bearing: the pricing card and its
    renewal disclosure (a renewal notice that omits the amount is not a
    disclosure). Anything beyond this is ambient repetition, which pushes cost
    evaluation ahead of value — the owner's Aug 24 revision moved the price
    out of the hero entirely for exactly that reason. (A further mention lives
    in the checkout script, which only ever replaces the button's own text.)"""
    # 2026 (owner decision, Oct 18 2026): one-time passes, so the disclosure
    # beside the price is "one payment", not a renewal amount — ONE rendered
    # pass price, on its card, with "One payment" on that card.
    rendered = markup_only(LANDING)
    assert rendered.count(f"${SEASON_PRICE}") == 1, "landing page price mentions drifted"
    card = rendered.split('id="pass-card"')[1].split('<div class="plan">')[0]
    assert "One payment" in card, "the pass card must say it is one payment"


# --------------------------------------------------------------------- #
# honesty of the live scouting demo
# --------------------------------------------------------------------- #



def test_scout_renders_untrusted_names_as_text_only() -> None:
    """League/team names belong to strangers: never assigned as HTML."""
    for page, name in ((JOIN, "join"), (LANDING, "landing")):
        assert not re.search(r"\.innerHTML\s*=", page), f"{name} assigns innerHTML"
        assert not re.search(r"insertAdjacentHTML|document\.write", page), \
            f"{name} injects raw markup"


# --------------------------------------------------------------------- #
# checkout wiring
# --------------------------------------------------------------------- #

def test_checkout_is_a_single_constant_away_on_both_pages() -> None:
    """The wiring slots must exist whatever state they are in — one constant
    per page is the whole payment integration, and losing a slot means losing
    the ability to open or close checkout at all.

    This no longer pins CHECKOUT_OPEN to false. It was flipped on Aug 27 2026
    (owner decision: launch now, create the Stripe links after), which is a
    deliberate interim state, not a mistake — and the guarantee that makes it
    safe is tested below rather than here."""
    assert re.search(r"const CHECKOUT_OPEN = (true|false);", LANDING), \
        "landing page lost its checkout wiring slot"
    for const in ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY", "STRIPE_LINK_PASS"):
        assert re.search(rf"const {const} = ", JOIN), \
            f"join page lost its {const} wiring slot"


def test_an_open_checkout_with_no_links_still_warns_before_the_work() -> None:
    """The interim state between "launched" and "Stripe links exist": the
    landing invites a purchase and the picker cannot finish one.

    That is only tolerable because the picker says so BEFORE the buyer pastes
    fifteen names, never after — the same rule that produced the closed-note in
    the first place. A dead end discovered at the end of the work reads as
    broken software; one stated at the top reads as "not yet".

    This test exists precisely so that the interim cannot quietly become the
    permanent state without somebody noticing the funnel is a cul-de-sac."""
    links_live = not all(re.search(rf'const {c} = ""', JOIN) for c in
                         ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY",
                          "STRIPE_LINK_PASS"))
    if links_live:
        return                      # checkout can actually complete; nothing to warn about
    assert 'id="closed-note"' in JOIN, \
        "checkout is open with no payment links and the picker has no warning"
    assert re.search(r"isn't open just yet", JOIN), \
        "the closed-checkout message is gone while the links are still empty"
    # And it is decided from the LINKS, not hand-toggled — a hand-set banner
    # is one someone forgets to remove the day the links land.
    # The per-plan rewrite derives one link from the three and tests that; the
    # old pattern here matched the all-or-nothing shape it replaced, and nobody
    # noticed because the early return above skipped it for as long as the
    # links were live. Closing checkout again (Sep 29 2026) found it.
    gate = re.search(r"const (\w+) = [^;]*STRIPE_LINK_[A-Z]+[^;]*;\s*"
                     r"if \(!\1\) \{(.*?)\n\}", JOIN, re.S)
    assert gate and "closed-note" in gate.group(2), \
        "the warning must be driven by whether a payment link exists"


def test_every_paid_cta_routes_through_the_picker() -> None:
    """Load-bearing, not cosmetic: the picker is what attaches the buyer's league
    and rival to the payment (as Stripe's client_reference_id). A CTA that jumps
    straight to checkout takes the money and leaves us with no idea whose team
    to report on."""
    for target in re.findall(r'(?:href|\.href)\s*=\s*"([^"]*)"', LANDING):
        assert "stripe.com" not in target and "buy.stripe" not in target, \
            f"landing page publishes a payment URL directly: {target}"
    rewrites = LANDING.split("if (CHECKOUT_OPEN)")[1]
    assert rewrites.count("join/index.html") >= 2, \
        "both pricing CTAs must point at join/, not at a payment link"


def test_the_capture_and_its_own_caption_retire_on_the_same_flag() -> None:
    """One screen must not contradict itself.

    Two flags exist deliberately: CHECKOUT_OPEN says "sell", CHECKOUT_CAN_COMPLETE
    says a payment link is actually pasted in. The email capture retires on the
    second, because a page that can neither take money nor take an address is a
    dead end during the peak draft fortnight.

    But the sentences AROUND the capture were rewritten on the first. So with
    the flags split — which is the live state today — the page showed an email
    box captioned "Checkout is open", above a finance line promising the roster
    rides into a checkout that does not exist. Reproduced in a browser before
    this test was written.

    The .heroline IS the capture's caption ("one email when signups open"), and
    the closer and finance lines both address someone who cannot buy yet, so
    all of them belong behind the same flag as the form.
    """
    block = LANDING.split("if (CHECKOUT_CAN_COMPLETE)")[1]
    # Bounded by the enclosing CHECKOUT_OPEN block's close, which is the last
    # thing in it — everything after is unrelated page script.
    block = block.split("\n}\n")[0]
    for element in ("watch-form", "heroline", "finance-note",
                    "closer-head", "closer-note"):
        assert element in block, (
            f"{element} is retired or rewritten outside the "
            f"CHECKOUT_CAN_COMPLETE guard, so it changes while the capture it "
            f"talks about is still on screen")


def test_the_closer_heading_does_not_outlive_its_own_date() -> None:
    """"The first file goes out Tuesday, Sep 8" is true until Sep 8 2026 and
    false every day after. It is honest in the closed state — nobody can buy,
    so the first file really is that Tuesday — but it must not survive the
    flip, and the flip must replace it rather than leave a stale date under a
    live Buy button."""
    assert 'id="closer-head"' in LANDING, "the heading cannot be rewritten"
    block = LANDING.split("if (CHECKOUT_CAN_COMPLETE)")[1].split("\n}\n")[0]
    assert "closerHead" in block and "Sep 8" not in block, (
        "the flip leaves a hardcoded launch date on the closer")


def test_the_checkout_url_carries_the_signup() -> None:
    """This IS the architecture: no server, no second list — the picks ride into
    the payment, and the paying email is forced to equal the picking email."""
    assert "client_reference_id=" in JOIN, \
        "checkout URL must carry the picks as client_reference_id"
    assert "locked_prefilled_email=" in JOIN, (
        "must use locked_prefilled_email (non-editable), not prefilled_email — an "
        "editable address reintroduces the mismatch this design removes")


def test_the_reference_is_validated_before_we_take_money() -> None:
    """Stripe silently drops an invalid client_reference_id and still shows a
    working payment page, so the browser is the only place this can be loud."""
    # The pattern lives in roster.js and is used by BOTH the encoder and this
    # check, so they cannot drift into disagreeing about what Stripe accepts.
    assert re.search(r"const REF_RE = /\^\[A-Za-z0-9_-\]\{1,200\}\$/", ROSTER_JS), \
        "the ref must be checked against Stripe's documented charset and length"
    assert re.search(r"if \(!R\.REF_RE\.test\(ref\)\)", JOIN), \
        "the ref must be tested before navigating to checkout"


def test_an_individual_signup_is_never_posted_anywhere() -> None:
    """Individual buyers go browser -> Stripe. Only League Pass seats (who have
    no payment to ride) touch a form backend, so a vendor outage costs seats,
    never sales."""
    handler = JOIN.split('$("form-email").addEventListener')[1].split(
        "function submitSeat")[0]
    assert "FORM_ENDPOINT" not in handler, \
        "the individual checkout path must not depend on a form backend"
    assert "window.location.assign" in handler, "the slice missed the redirect"
    # The one place the form backend IS reached is seats, and a seat must never
    # fall through to a payment link: the button says "already paid".
    seat = JOIN.split("function submitSeat")[1].split("function showSeatLink")[0]
    assert "FORM_ENDPOINT" in seat
    assert "STRIPE_LINK" not in seat, "a seat holder was routed to checkout"
    assert "if (SEAT_MODE) {\n    submitSeat(" in handler, \
        "seat mode must leave the payment path before it picks a link"
    assert 'const FORM_ENDPOINT = ""' in JOIN, \
        "PLAN §0: the seat endpoint stays empty until seat provenance is fixed"


def test_no_payment_details_are_collected_by_us() -> None:
    """Card data must live entirely with Substack/Stripe (CLAUDE.md security)."""
    for page in (LANDING, JOIN):
        assert not re.search(r'type="(card|cc-number|creditcard)"', page, re.I)
        assert not re.search(r'autocomplete="cc-', page, re.I)
    assert re.search(r"never touch our systems", JOIN, re.I)


def test_join_collects_only_the_stated_minimum() -> None:
    inputs = re.findall(r'<input[^>]*type="([a-z]+)"', JOIN)
    assert set(inputs) <= {"text", "email", "radio", "checkbox"}, \
        f"unexpected input types: {inputs}"
    # One checkbox, and it collects nothing: the roster update's "these are my
    # league's settings" (FUNNEL F1) gates the submit and is never posted.
    boxes = re.findall(r'<input[^>]*type="checkbox"[^>]*>', re.sub(r"\s+", " ", JOIN))
    assert boxes == ['<input type="checkbox" id="settings-ok">'], boxes
    assert "settings-ok" not in _js_function(JOIN, "submitUpdate").split("fetch(")[1]
    assert re.search(r"never ask for a password", JOIN_PROSE, re.I)
    assert re.search(r"never connect to your league", JOIN_PROSE, re.I)


def test_pass_states_its_renewal_terms() -> None:
    """A recurring charge must say so where it is sold (PLAN §4, ROSCA)."""
    for page, name in ((LANDING_PROSE, "landing"), (JOIN_PROSE, "join")):
        assert re.search(r"renews once a year|no renewal|one payment", page, re.I), \
            f"{name} page sells the season pass without stating renewal terms"
    # One-time passes (2026): the selling page says nothing renews.
    assert re.search(r"nothing renews", LANDING_PROSE, re.I)


def test_free_list_never_routes_to_paid_checkout() -> None:
    """The free ledger form must not hand a "free" clicker to the $29 page."""
    handler = LANDING.split("const watchForm")[1].split("if (CHECKOUT_OPEN)")[0]
    assert "CHECKOUT_OPEN" not in handler, \
        "free ledger signup must not navigate to the paid checkout"
    assert "LEDGER_FREE_URL" in handler


def test_nothing_is_claimed_saved_when_nothing_recorded_it() -> None:
    """The picker holds no state of its own. Until checkout is wired, a signup
    goes nowhere — so the page must say the picks are NOT saved, rather than
    congratulating someone on a reservation that does not exist."""
    assert 'id="done-head"' in JOIN
    assert re.search(r"your roster isn't saved", JOIN_PROSE, re.I), \
        "the not-open path must admit the roster was not stored"
    assert re.search(r"isn't open just yet", JOIN_PROSE, re.I)




def test_network_calls_have_a_timeout() -> None:
    """Both pages: the landing's hero capture is 'the one action a visitor can
    complete' while checkout is closed, and it once awaited a hung Worker
    forever with no feedback (review, Aug 24). Every fetch on either page
    carries the same 15s abort the join page always had."""
    assert "AbortSignal.timeout" in JOIN
    starts = [m.start() for m in re.finditer(r"\bfetch\(", LANDING)]
    assert starts, "the landing lost its capture fetch"
    for start in starts:
        assert "AbortSignal.timeout" in LANDING[start:start + 400], \
            f"a landing fetch has no timeout: {LANDING[start:start + 80]!r}"


# --------------------------------------------------------------------- #
# the backtest exhibit must not overstate the shipping product
# --------------------------------------------------------------------- #

def test_the_landing_quotes_no_backtest_figure_in_either_direction() -> None:
    """The landing page used to carry the league study's exhibit — the 53.5%
    headline, the diagnostic table, the 'hindsight filter' qualifier — and two
    tests pinned that the qualifiers travelled with the figures. A cold-buyer
    read scored that block as the sale-killer on the page: to someone who has
    never heard the word calibration, '53.5% and five of six buckets wrong'
    reads as a coin flip that is wrong most of the time, and the dense
    recovery never lands. The qualifiers were only ever required IF the table
    was shown; so the exhibit moved off the landing entirely, and the page now
    LINKS every proof instead of quoting any of it. This guard holds both
    directions: no unflattering figure stripped of its context, and no
    flattering diagnostic column laundered back in as accuracy — the exact
    thing an adversarial review once caught."""
    # Visible copy only: the entity sentence in <head>/JSON-LD legitimately says
    # "the buckets it failed", and that sentence is pinned verbatim elsewhere.
    visible = re.sub(r"<head>.*?</head>|<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->",
                     " ", LANDING, flags=re.S | re.I)
    visible = re.sub(r"\s+", " ", visible)
    for figure in ("53.5%", "2,056", "57.4%", "62.5%", "63.6%", "78.3%", "77.2%",
                   "7.2%", "64.6%"):
        assert figure not in visible, \
            f"backtest figure {figure} is quoted on the landing page; it belongs on " \
            "the evidence page that carries its context"
    # Since Sep 29 2026 (owner direction) the volume of the grading goes too:
    # "10,041 real calls graded… misses included" led a first impression with
    # the audit instead of the benefit. No grading count, no grading
    # vocabulary, and no link to a grading page (see
    # test_no_selling_page_links_the_grading_pages).
    source = (SITE.parent / "reports" / "nflverse-backtest.md").read_text(encoding="utf-8")
    graded = int(re.search(r"\| Calls graded \| (\d+) \|", source).group(1))
    assert f"{graded:,}" not in visible, "the grading count is back on the landing"
    assert not re.search(r"hindsight filter|calibration error|buckets?\b|misses included"
                         r"|grade [A-D]\b", visible, re.I), \
        "grading vocabulary leaked back onto the sales page"


def test_published_backtest_exists_and_keeps_its_failures() -> None:
    """'published here' must resolve, and must not be a laundered version.

    The page publishes the LIVE product's grading now, not the retired
    Sleeper-era study — the frozen method's per-surface mapping requires that
    at every grade, because a buyer sent to 'our backtest' was reading a
    measurement of a stack we no longer run. What must survive the repoint is
    the property, not the old figures: the source's own grade, its refusal to
    claim more, and every failing band it recorded."""
    published = SITE / "backtest.html"
    assert published.is_file(), "landing page links a backtest that isn't published"
    text = published.read_text(encoding="utf-8")
    source = (REPORTS / "nflverse-backtest.md").read_text(encoding="utf-8")
    grade = re.search(r"^## Grade ([A-D])$", source, re.M)
    assert grade, "the source report lost its grade"
    assert f"Grade {grade.group(1)}" in text, "the published page lost its grade"
    failing = len(re.findall(r"\|\s*\*{0,2}off\*{0,2}\s*\|", source))
    assert failing, "the source report has no failing band to keep"
    published_off = len(re.findall(r">\s*(?:<b>)?off(?:</b>)?\s*<", text))
    assert published_off >= failing, (
        f"source records {failing} failing band(s), page shows {published_off}")
    # And the retired study stays in the record rather than being deleted —
    # generated, unedited, and saying what it is in its own first line.
    retired = (REPORTS / "backtest.md").read_text(encoding="utf-8")
    assert "a data stack the product no longer runs" in retired.split("\n")[0]
    assert "53.5%" in retired, "the retired study lost its own headline"


# --------------------------------------------------------------------- #
# the ledger page stays the proof asset
# --------------------------------------------------------------------- #

def test_ledger_page_promises_misses_are_published() -> None:
    assert re.search(r"hit or miss|wins and misses|Voids are shown", LEDGER, re.I)
    assert re.search(r"analysis, not betting picks", LEDGER, re.I)


def test_no_selling_page_links_the_grading_pages() -> None:
    """Owner direction, Sep 29 2026: a new buyer decides on a first impression,
    and the grading pages (grades, failing bands, what free feeds did better)
    create doubt at the moment of decision without helping anyone win. They
    stay live and unedited as the record — nothing is deleted or rewritten —
    but no page that sells links to them, and search engines are told to leave
    them out. A strong record can be promoted back deliberately, later."""
    selling = {
        "landing": LANDING, "join": JOIN, "how it works": HOW,
        "league pass": (SITE / "league-pass.html").read_text(encoding="utf-8"),
        "thanks": (SITE / "thanks.html").read_text(encoding="utf-8"),
        "sample": (SITE / "sample-report.html").read_text(encoding="utf-8"),
        "first-week sample": (SITE / "sample-first-week.html").read_text(encoding="utf-8"),
    }
    for name, page in selling.items():
        for target in _EVIDENCE_PAGES:
            assert not re.search(rf'href="(?:\.\./)?{re.escape(target)}', page), \
                f"{name} links the grading page {target}"
    for target in _EVIDENCE_PAGES:
        page = (SITE / target).read_text(encoding="utf-8")
        assert re.search(r'<meta name="robots" content="noindex', page), \
            f"{target} is not kept out of search results"


# --------------------------------------------------------------------- #
# the buyer never reads our internal vocabulary
# --------------------------------------------------------------------- #

SAMPLE_REPORT = (SITE / "sample-report.html").read_text(encoding="utf-8")
FIRST_WEEK_SAMPLE = (SITE / "sample-first-week.html").read_text(encoding="utf-8")

# Words that mean something to the person BUILDING this and nothing (or something
# alarming) to the person paying for it. "v0.3" in particular reads as "I bought
# unfinished software" when the truth is the opposite — we withhold what we can't
# defend. The backtest page is exempt: it is deliberately the technical document.
_DEV_SPEAK = [
    r"v0\.\d",                # version numbers
    r"week_report\.json",     # our filenames
    r"reports/backtest\.md",
    r"\bLLM\b", r"\btokens?\b(?!\s*of)",   # model/cost telemetry
    r"\bpipeline\b", r"\bschema\b", r"\bJSON\b",
    r"availability snapshot", r"calibration policy",
    r"deterministic", r"ingested",
    # The machinery stays invisible (CLAUDE.md: the AI is invisible to the
    # buyer). "Engine" kept leaking into live-report strings precisely where
    # this sweep didn't look, so it is banned outright in buyer copy.
    r"\bengine\b",
]


def _demo_report_html() -> str:
    """The raw (un-anonymised) demo render — the live-report shape. Local-only
    (gitignored), so skip when absent rather than failing a fresh clone."""
    path = Path(__file__).resolve().parent.parent / "reports" / "rival-report-2018-w10-r1.html"
    if not path.is_file():
        pytest.skip("demo report not rendered locally — run the demo render first")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["sample report", "first-week sample", "landing",
                                  "join", "compare", "projections", "no-call",
                                  "confidence", "how it works", "live report"])
def test_no_developer_vocabulary_in_buyer_copy(name: str) -> None:
    if name == "live report":
        page = _demo_report_html()
    else:
        page = {"sample report": SAMPLE_REPORT,
                "first-week sample": FIRST_WEEK_SAMPLE,
                "landing": LANDING, "join": JOIN,
                "compare": COMPARE, "projections": PROJECTIONS,
                "no-call": NO_CALL, "confidence": CONFIDENCE,
                "how it works": HOW}[name]
    text = prose(markup_only(page))
    for pattern in _DEV_SPEAK:
        assert not re.search(pattern, text, re.I), \
            f"developer vocabulary {pattern!r} reached the {name}"


def test_no_real_league_member_is_named_on_any_public_page() -> None:
    """Public pages profile people's habits. Those people never signed up to
    appear next to a sales page, so every public surface uses neutral labels."""
    import json
    raw = Path(__file__).resolve().parent.parent / "data" / "raw" / "league"
    names: set[str] = set()
    for users_file in raw.glob("*/users.json"):
        for user in json.loads(users_file.read_text(encoding="utf-8")):
            if user.get("display_name"):
                names.add(user["display_name"])
            team = (user.get("metadata") or {}).get("team_name")
            if team:
                names.add(team)
    if not names:
        pytest.skip("no cached league data to build the forbidden-name set")
    # EVERY tracked file, not a hardcoded list of six site/ pages. The narrow
    # version passed green while reports/rival-report-2018-w10-r1.{html,txt}
    # — also tracked, and therefore also published by a push — named four real
    # managers and profiled their waiver habits. "Public surface" is anything
    # that leaves this machine, not just the pages under site/.
    import subprocess
    repo = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                             text=True, check=True).stdout.split()
    skip_dirs = ("tests/", "data/")
    for rel in tracked:
        if rel.startswith(skip_dirs):
            continue
        path = repo / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue                      # binary or unreadable: nothing to name
        for person in names:
            assert person not in text, \
                f"{person!r} is named in tracked file {rel}, which a push publishes"


def test_no_personal_contact_details_are_published() -> None:
    """The owner's personal address must never appear on a public page. Ship a
    product inbox instead — this guards against it creeping back in."""
    personal = re.compile(r"[A-Za-z0-9._%+-]+@(gmail|googlemail|yahoo|hotmail|outlook|"
                          r"icloud|proton(mail)?|me|aol)\.[A-Za-z.]{2,}", re.I)
    for page_path in sorted(SITE.rglob("*.html")):
        text = page_path.read_text(encoding="utf-8")
        found = personal.findall(text)
        assert not personal.search(text), \
            f"personal email address published in {page_path.relative_to(SITE)}"
    # The legal page must carry a REACHABLE contact route — refund and deletion
    # requests have nowhere else to go. Set Aug 26 2026 to the project inbox
    # (Cloudflare Email Routing -> the operator), never a personal address, and
    # never a plausible-looking invention that silently swallows requests.
    legal = (SITE / "terms.html").read_text(encoding="utf-8")
    assert "hello@beatyourleague.com" in legal, \
        "legal page lost its contact route — refunds and deletions need one"
    assert not re.search(r"added before launch", legal, re.I), \
        "the contact placeholder is still there; it was set before launch"


def test_no_tracked_file_carries_a_home_folder_path() -> None:
    """The repo is public and the owner stays anonymous, and a machine path
    names its user. The mid-season LAUNCH.md rewrite put `cd /Users/<name>/…`
    into a copy-paste command — the owner's first name, in a public file, in
    the one doc they follow literally. Every tracked text file is swept."""
    import subprocess
    root = SITE.parent
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                             capture_output=True).stdout.decode().split("\0")
    home = re.compile(r"/(?:Users|home)/[A-Za-z][\w.-]*/")
    for name in filter(None, tracked):
        path = root / name
        if path.suffix in {".png", ".jpg", ".ico", ".csv"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not home.search(text), f"{name} carries a home-folder path"


def test_signup_degrades_honestly_without_a_contact_route() -> None:
    """With checkout unwired, the form must say so rather than opening an empty
    mailto: that looks like it worked. The join page no longer has a mailto path
    at all — the picks ride into Stripe or nowhere."""
    assert re.search(r"isn't open just yet", JOIN_PROSE, re.I)
    assert "mailto:" not in JOIN, \
        "the join page must not fall back to an email draft — it loses the signup"
    assert re.search(r"if \(!CONTACT_EMAIL\)", LANDING)


def test_legal_page_covers_the_promises_money_depends_on() -> None:
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    for required in (r"renew once a year|renews once a year", r"cancel yourself at any time",
                     r"one refund per person", r"18 or older",
                     r"never see or store your card", r"not affiliated"):
        assert re.search(required, legal, re.I), f"legal page is missing: {required}"


def test_the_post_purchase_page_sets_an_honest_delivery_expectation() -> None:
    """The page a buyer lands on the instant after paying.

    "I paid and got nothing" is the dominant refund driver at this size, and
    the gap is real: run/intake.py sends the welcome and the first file, and
    daily.yml runs it HOURLY — so a buyer can wait up to an hour. Stripe's own
    confirmation page says a payment was received and nothing about when
    anything arrives, which leaves the buyer to guess during the exact window
    where guessing turns into a chargeback.

    The page must therefore state a wait we can actually keep. If the intake
    cron ever slows down, this assertion is where that becomes visible.
    """
    page = SITE / "thanks.html"
    assert page.is_file(), "the post-purchase page is missing"
    text = page.read_text(encoding="utf-8")
    visible = html.unescape(prose(text[text.find("<body>"):]))

    workflow = (SITE.parent / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert re.search(r'cron: "\d{1,2} \* \* \* \*"', workflow), (
        "the intake no longer runs hourly, so \"usually within the hour\" on the "
        "post-purchase page may now be a promise we cannot keep")
    assert re.search(r"usually lands\s+within the hour", visible, re.I), \
        "the page does not say how long the first file takes"

    for required, why in (
            (r"spam", "a new sending domain's first email often lands there"),
            (r"refund", "the two-file refund window, at the moment they are most anxious"),
            (r"cancel", "stated before they have to go looking for it"),
            (r"hello@beatyourleague\.com", "a human, reachable")):
        assert re.search(required, visible, re.I), \
            f"post-purchase page is missing {required!r} — {why}"

    assert 'name="robots" content="noindex"' in text, (
        "this page reads as a claim about the reader out of context; it must "
        "not turn up in a search result")


def test_the_post_purchase_page_promises_only_what_gets_sent() -> None:
    """It describes the first file, so it must describe the one that ships.

    run/intake.py's _first_file sends the WEEK'S REPORT to anyone who buys
    before that week's kickoff and the roster file otherwise — so a page
    promising only one of the two is wrong for half of all buyers.
    """
    text = (SITE / "thanks.html").read_text(encoding="utf-8")
    visible = html.unescape(prose(text[text.find("<body>"):]))
    assert re.search(r"roster report", visible, re.I), "the pre-season case"
    assert re.search(r"current week's report|week's report", visible, re.I), \
        "the mid-season case — a Wednesday buyer gets that week's report"
    assert re.search(r"every tuesday", visible, re.I), "the recurring product"


def test_the_privacy_policy_stands_on_its_own() -> None:
    """It is linked from Stripe's checkout as the privacy policy, so it has to
    BE one rather than a section that used to live inside the terms.

    Each requirement is a thing a reader came to the page to find, and each is
    also a thing that quietly disappears when a page is rewritten for length.
    """
    # BODY ONLY. prose() collapses whitespace but does not strip tags, so a
    # claim surviving in <meta name="description"> would satisfy an assertion
    # while the page a reader actually sees had lost it — the guard reading the
    # wrong copy of the sentence.
    page = (SITE / "privacy.html").read_text(encoding="utf-8")
    privacy = prose(page[page.find("<body>"):])
    for required, why in (
            (r"what we collect", "the heading a reader scans for"),
            (r"never ask for", "passwords and card details, stated as absences"),
            (r"no cookies|sets no cookies", "the strongest true claim on the page"),
            (r"analytics", "named explicitly, not merely absent"),
            (r"do not sell your data|don't sell your data", "the promise buyers check"),
            (r"delete", "the right that makes the rest meaningful"),
            (r"how long", "retention"),
            (r"stripe", "the processor that holds the payment"),
            (r"18 or older", "the age gate"),
            (r"hello@beatyourleague\.com", "a route to exercise any of it")):
        assert re.search(required, privacy, re.I), \
            f"privacy policy is missing {required!r} — {why}"


def test_the_privacy_policy_does_not_claim_more_privacy_than_we_deliver() -> None:
    """The no-cookies claim is only honest while it is true. The pages used to
    reach one third party — Google Fonts saw every visitor's IP — and the
    policy had to say so. Contract C7 self-hosts the type (site/fonts), and the
    policy now makes the stronger claim: loading a page makes no request to
    any third party. That claim is only true while NO page under site/ links
    a font CDN, so every page is swept, the generated ones included (a stale
    sample still carrying the old <link> would falsify it)."""
    pages = [p for p in SITE.rglob("*.html")]
    cdn = re.compile(r"fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit|fonts\.bunny")
    still = sorted(str(p.relative_to(SITE)) for p in pages
                   if cdn.search(p.read_text(encoding="utf-8")))
    whole = (SITE / "privacy.html").read_text(encoding="utf-8")
    privacy = prose(whole[whole.find("<body>"):])    # body only, same reason
    assert re.search(r"makes no request to any third party", privacy), \
        "the policy must state the no-third-party claim the self-hosted type makes true"
    assert not re.search(r"google fonts", privacy, re.I), \
        "the policy still names a processor the site no longer uses"
    assert not still, (
        f"{len(still)} page(s) still load type from a font CDN while the privacy "
        f"policy says no page makes a third-party request: {', '.join(still)}")


# The hosts a page may load anything from (ANALYTICS-05). Everything else —
# a font CDN, an analytics beacon, a widget — is a third party, which the
# privacy page says no page ever contacts. forms.* is the form Worker, which
# also runs the page counter (site/count.js, privacy section 3).
OUR_HOSTS = {"beatyourleague.com", "forms.beatyourleague.com"}
_LOAD_RELS = {"stylesheet", "preload", "modulepreload", "prefetch", "preconnect",
              "dns-prefetch", "icon", "shortcut", "apple-touch-icon", "mask-icon",
              "manifest"}
_LOAD_ATTRS = {"script": ("src",), "img": ("src", "srcset"), "iframe": ("src",),
               "frame": ("src",), "source": ("src", "srcset"), "video": ("src", "poster"),
               "audio": ("src",), "track": ("src",), "embed": ("src",), "object": ("data",),
               "input": ("src",), "form": ("action",)}
_CSS_URL = re.compile(r"""url\(\s*(["']?)([^"')]+)\1\s*\)|@import\s+(["'])([^"']+)\3""")
_JS_LOADS = (
    re.compile(r"""\b(?:fetch|sendBeacon|importScripts|import|EventSource|WebSocket|Worker)"""
               r"""\s*\(\s*(["'`])([^"'`]*)\1"""),
    re.compile(r"""\b[A-Z_]*ENDPOINT\s*=\s*(["'])([^"']*)\1"""),
    re.compile(r"""\.src\s*=\s*(["'])([^"']*)\1"""),
)


def _loaded_urls(text: str, kind: str) -> list[str]:
    """Every URL a page (``kind`` html), stylesheet (css) or script (js) makes
    the browser FETCH. Navigation is exempt — an <a href>, a canonical link,
    an og:image a crawler reads, a JSON-LD context, an xmlns — because none of
    them is a request made by loading the page."""
    from html.parser import HTMLParser
    found: list[str] = []

    def css(chunk: str) -> None:
        for m in _CSS_URL.finditer(chunk):
            found.append(m.group(2) or m.group(4))

    def js(chunk: str) -> None:
        for pattern in _JS_LOADS:
            found.extend(m.group(2) for m in pattern.finditer(chunk))

    if kind == "css":
        css(text)
        return found
    if kind == "js":
        js(text)
        return found

    class _Loads(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.inside = ""
            self.ld = False

        def handle_starttag(self, tag, attrs):
            a = {k: v or "" for k, v in attrs}
            for name in _LOAD_ATTRS.get(tag, ()):
                value = a.get(name)
                if value and name == "srcset":
                    found.extend(part.strip().split(" ")[0] for part in value.split(","))
                elif value:
                    found.append(value)
            if tag == "link" and set(a.get("rel", "").lower().split()) & _LOAD_RELS:
                found.append(a.get("href", ""))
            if a.get("style"):
                css(a["style"])
            self.inside = tag if tag in ("script", "style") else ""
            self.ld = tag == "script" and "ld+json" in a.get("type", "")

        def handle_endtag(self, tag):
            self.inside = ""

        def handle_data(self, data):
            if self.inside == "style":
                css(data)
            elif self.inside == "script" and not self.ld:
                js(data)

    _Loads().feed(text)
    return [u for u in found if u]


def _third_party(url: str) -> bool:
    """True when fetching ``url`` from one of our pages contacts another host."""
    from urllib.parse import urlsplit
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url                        # protocol-relative
    scheme = re.match(r"(?i)^([a-z][a-z0-9+.-]*):", url)
    if not scheme:
        return False                                # relative: our own host
    if scheme.group(1).lower() in ("data", "blob", "about", "javascript"):
        return False                                # nothing leaves the page
    return (urlsplit(url).hostname or "") not in OUR_HOSTS


def _site_files() -> list[tuple[Path, str]]:
    kinds = {".html": "html", ".css": "css", ".js": "js"}
    return [(p, kinds[p.suffix]) for p in sorted(SITE.rglob("*"))
            if p.is_file() and p.suffix in kinds]


def test_no_page_loads_anything_but_our_own_hosts() -> None:
    """An ALLOWLIST of origins, not a list of tracker names (ANALYTICS-05).

    Reproduction (Oct 23 2026): the old guard checked six names
    (googletagmanager, google-analytics, gtag(, plausible.io, fathom,
    posthog). Cloudflare Web Analytics' beacon
    (static.cloudflareinsights.com/beacon.min.js) and Umami's script.js
    injected before </body> on every page passed it — 24 privacy tests green —
    while privacy.html said loading a page "makes no request to any third
    party". Now every URL any page, stylesheet or script makes the browser
    fetch must be relative or on our own two hosts; navigation links are exempt."""
    offenders = []
    for path, kind in _site_files():
        for url in _loaded_urls(path.read_text(encoding="utf-8"), kind):
            if _third_party(url):
                offenders.append(f"{path.relative_to(SITE)} loads {url}")
    assert not offenders, (
        "privacy.html says no page makes a request to any third party, but: "
        + "; ".join(offenders[:6]))


def test_no_page_stores_anything_but_the_one_documented_key() -> None:
    """No cookie, no localStorage, no IndexedDB anywhere on the site — the
    privacy page's "nothing is stored on your device" (section 3) — and
    sessionStorage only for the one convenience it describes: the League Pass
    buyer's own address, kept in that tab for thanks.html's share line under
    PAID_EMAIL_KEY ("byl_paid_email") and deleted there once read."""
    allowed = {"join/index.html", "thanks.html"}
    for path, _kind in _site_files():
        text = path.read_text(encoding="utf-8")
        name = str(path.relative_to(SITE))
        assert not re.search(r"document\.cookie|localStorage|indexedDB|openDatabase", text), \
            f"{name} stores something in the browser"
        kept = re.sub(r'sessionStorage\.(?:setItem|getItem|removeItem)\(\s*'
                      r'(?:PAID_EMAIL_KEY|["\']byl_paid_email["\'])', "", text)
        if name in allowed:
            assert "sessionStorage" not in kept, f"{name} uses session storage for something new"
        else:
            assert "sessionStorage" not in text, f"{name} uses session storage"


def _privacy_body() -> str:
    page = (SITE / "privacy.html").read_text(encoding="utf-8")
    return html.unescape(prose(re.sub(r"<[^>]+>", " ", page[page.find("<body>"):])))


def _terms_body() -> str:
    page = (SITE / "terms.html").read_text(encoding="utf-8")
    return html.unescape(prose(re.sub(r"<[^>]+>", " ", page[page.find("<body>"):])))


def test_the_privacy_policy_states_only_retention_something_performs() -> None:
    """Reproduction (launch audit C3, Oct 15 2026): §4 said Cloudflare keeps
    form rows "until we read it" — rows are never deleted on read and live
    400 days; §7 said "the waitlist is cleared after the one message it was
    for" — run/waitlist.py sends and returns, nothing clears anything; and it
    said email, roster and settings are deleted "12 months afterwards" — no
    code anywhere prunes the registry, the signup log or Stripe metadata. A
    deletion promise nothing performs is a false statement about people's
    data. What IS performed: the Worker's TTL."""
    privacy = _privacy_body()
    for retired in (r"until we read it", r"cleared after the one message",
                    r"12 months after", r"up to 12 months"):
        assert not re.search(retired, privacy, re.I), \
            f"privacy promises a deletion nothing performs: {retired!r}"
    worker = (SITE.parent / "infra" / "form-worker.js").read_text(encoding="utf-8")
    ttl = re.search(r"ROW_TTL_SECONDS\s*=\s*(\d+)\s*\*\s*24\s*\*\s*60\s*\*\s*60", worker)
    assert ttl and "expirationTtl: ROW_TTL_SECONDS" in worker
    days = int(ttl.group(1))
    assert re.search(r"within about 13 months", privacy), \
        "the one retention the code performs must be stated"
    assert 365 < days <= 13 * 31, \
        f"the Worker keeps rows {days} days; privacy says about 13 months"
    assert re.search(r"no fixed date", privacy, re.I), \
        "say plainly that nothing deletes the rest on a timer"
    assert re.search(r"within 30 days", privacy), "a deletion request needs a response time"


def test_the_privacy_policy_names_every_place_our_data_actually_goes() -> None:
    """Reproduction (launch audit C5): mail to hello@ is forwarded to a Gmail
    inbox (LAUNCH.md) — so Google holds every refund, deletion and roster
    reply — and Google was not named; and Stripe was said to hold only the
    payment and subscription while run/intake.py writes the encoded roster
    (byl_roster_ref), the plan and the terms-acceptance record onto the
    Customer, and the ref rides client_reference_id."""
    privacy = _privacy_body()
    assert re.search(r"Google \(Gmail\)", privacy), "the inbox hello@ forwards to"
    assert re.search(r"Five service providers", privacy)
    stripe = privacy[privacy.find("Stripe handles payment"):][:500]
    for held in (r"roster", r"settings", r"accepting these terms"):
        assert re.search(held, stripe), f"Stripe's record also holds {held!r}"
    assert not re.search(r"we hold only a reference to it", privacy)


def test_the_privacy_policy_names_the_channel_tag_and_the_stop_list() -> None:
    """Reproduction (launch audit C8): the landing and join pages post `via`
    with every form row and the Worker stores it beside the email, while the
    policy said "That is everything we hold about you" without it. Same for
    the stop list's digest (run/suppress.py), which the C4 fix added."""
    worker = (SITE.parent / "infra" / "form-worker.js").read_text(encoding="utf-8")
    privacy = _privacy_body()
    # Section 1 is the itemised list; the summary box above it is not enough.
    section1 = privacy[privacy.find("1. What we collect"):privacy.find("2. What we never")]
    if re.search(r"\bvia\b", worker):
        assert re.search(r"name of (that|the) channel", section1), \
            "the Worker stores a channel tag the policy does not itemise"
    if (SITE.parent / "run" / "suppress.py").exists():
        assert re.search(r"stop emailing you", section1) and \
            re.search(r"keyed one-way code", section1), "the stop list is held data"


def test_the_terms_describe_one_cancel_flow() -> None:
    """Reproduction (launch audit C2): §3 said "cancelling takes one click from
    your billing page" while §4 — and every other surface — said enter your
    email, open the link Stripe sends, press Cancel, about a minute. Two
    descriptions of leaving in the document that wins every disagreement."""
    terms = _terms_body()
    assert not re.search(r"cancel\w*[^.;:]{0,60}\bone[\s-]+click|"
                         r"\bone[\s-]+click[^.;:]{0,60}cancel", terms, re.I)
    section3 = terms[terms.find("3. Price"):terms.find("4. How to cancel")]
    assert re.search(r"in about a minute", section3)


def test_the_terms_keep_reports_to_the_end_of_the_paid_period() -> None:
    """Reproduction (launch audit C13): §4 said the reports "stop on their own
    after that" (after cancelling) and, two sentences on, "you keep access for
    the rest of the period you've already paid for" — and every report's
    text half said "The reports stop on their own once you do"."""
    terms = _terms_body()
    assert re.search(r"continue to the end of the period you've already paid "
                     r"for, then stop", terms)
    assert not re.search(r"stop on their own after that", terms)


def test_the_terms_give_a_seat_its_way_out() -> None:
    """A League Pass seat has no billing, so §4's billing page is no route for
    it (launch audit C4). The operative contract says what its emails say."""
    from render.report import SEAT_STOP_BODY
    terms = _terms_body()
    assert re.search(r"A League Pass seat has no billing of its own", terms)
    assert re.search(r'reply "stop"', terms) and "10 business days" in terms
    assert "10 business days" in SEAT_STOP_BODY, "terms and emails must agree"


def test_both_documents_are_reachable_and_the_old_url_still_resolves() -> None:
    """legal.html was live before the split. Nothing external points at it that
    we know of, but a 404 on a terms link is the worst possible broken link on
    a paid site, so it redirects rather than disappearing."""
    stub = (SITE / "legal.html").read_text(encoding="utf-8")
    assert 'http-equiv="refresh"' in stub and "terms.html" in stub
    assert 'href="privacy.html"' in stub, "the stub strands anyone after privacy"
    assert 'rel="canonical"' in stub, "search engines need the destination"
    for page in (SITE / "index.html", SITE / "join" / "index.html"):
        text = page.read_text(encoding="utf-8")
        assert re.search(r'href="(\.\./)?terms\.html', text), f"{page.name}: no terms link"
        assert re.search(r'href="(\.\./)?privacy\.html"', text), f"{page.name}: no privacy link"


def test_cancelling_has_concrete_steps_not_just_a_promise() -> None:
    """"You can cancel any time" without saying HOW is friction wearing a
    promise's clothes. The terms must give real, followable steps."""
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    assert re.search(r'id="cancel"', (SITE / "terms.html").read_text(encoding="utf-8")), \
        "the cancellation steps need a linkable anchor"
    # A concrete destination, not "contact your provider". Which vendor it names
    # is a platform decision; that it names ONE is not negotiable.
    assert re.search(r"(substack|stripe|billing)\S*\.com\S*/\S+", legal, re.I), \
        "the self-serve cancel path must name a concrete place to go"
    assert re.search(r"no further charges", legal, re.I)
    # Self-serve must be the advertised route: any promise that WE cancel on
    # request creates an inbox someone has to watch every day of the season.
    assert not re.search(r"reply to (any report|this email) with the word", legal, re.I), \
        "cancellation must not depend on the operator reading email"
    # And the trap must be called out, not left for the customer to discover.
    assert re.search(r"does not always stop a", legal, re.I), \
        "terms must warn that unsubscribing is not the same as cancelling"
    for page, name in ((LANDING, "landing"), (JOIN, "join")):
        assert re.search(r'(\.\./)?terms\.html#cancel', page), \
            f"{name} page should link straight to the cancellation steps"


@requires_demo_render
def test_every_report_carries_a_way_out() -> None:
    """A weekly commercial email with no exit is friction and a compliance
    problem; one that stops emails while billing continues is worse."""
    for page, name in ((SAMPLE_REPORT, "html report"),
                       ((Path(__file__).resolve().parent.parent / "reports"
                         / "rival-report-2018-w10-r1.txt").read_text(encoding="utf-8"),
                        "emailed text report")):
        text = prose(page)
        if name == "html report" and "Nothing renews and nothing more is charged" in text:
            # 2026's samples show the one-time pass's way out (SELLING_ONE_TIME):
            # nothing bills, so stopping the emails is the whole exit.
            assert re.search(r'reply (?:"|&quot;)stop', text, re.I), f"{name} offers no way out"
            continue
        assert re.search(r"cancel", text, re.I), f"{name} offers no way to cancel"
        assert re.search(r"unsubscrib\w+ from emails alone does ?not|"
                         r"unsubscribing from emails alone does NOT", text, re.I), \
            f"{name} must distinguish stopping emails from stopping billing"
        assert not re.search(r"reply to this email with the word", text, re.I), \
            f"{name} must not route cancellation through a human inbox"


def test_monthly_billing_never_outlives_the_product() -> None:
    """Monthly stops at season end, and run/billing.py is what makes it true."""
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    assert re.search(r"Month to month billing ends with the season", legal, re.I)
    assert re.search(r"stops on its own after the season's last weekly report", legal, re.I)
    assert re.search(r"nothing is charged after it", legal, re.I)
    # Monthly isn't sold in 2026 (owner decision, Oct 18 2026): the landing
    # carries no monthly price at all rather than terms for a plan it can't sell.
    assert "/ month" not in markup_only(LANDING)


def test_the_contract_does_not_promise_a_renewal_date_stripe_will_not_honour() -> None:
    """This test used to REQUIRE the false promise, which is how it survived.

    terms.html said the annual renewal is "charged shortly before the season it
    covers — never during the offseason". Stripe anchors a renewal on the
    subscription's own creation date, nothing in this repo moves that anchor,
    and RULE B2 in run/billing.py deliberately never touches a yearly plan. So
    a season pass bought in November renews the following November — mid-season
    — and one bought in January renews in January, deep in the offseason. The
    sentence was false for every buyer who did not happen to join in Aug/Sep,
    in the document that wins over every other surface.

    What replaced it is the promise we DO keep: the anniversary is stated
    plainly, and render/renewal.py sends the 15-45 day notice that California's
    ARL requires and that run/renewals.py actually runs.
    """
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    assert not re.search(r"never during\s+the offseason", legal, re.I), (
        "the unkeepable annual-renewal promise is back — nothing in this repo "
        "moves a Stripe billing anchor, and RULE B2 forbids touching a yearly "
        "subscription at all")
    assert not re.search(r"shortly before the season it covers", legal, re.I)
    assert re.search(r"anniversary of the day you subscribed", legal, re.I), (
        "the contract no longer says when an annual renewal actually falls")
    assert re.search(r"15 and 45 days", legal), (
        "the notice window we do keep — and legally owe — is unstated")


def test_the_contract_agrees_with_itself_on_when_monthly_billing_starts() -> None:
    """Section 3 said BOTH "you're charged when you subscribe" AND "you are
    charged monthly from the week your reports start". Those are mutually
    exclusive, and with a plain Payment Link and no billing anchor the first is
    what happens — so the second was false for every draft-season buyer, which
    the landing page actively recruits ("Sign up before Week 1 and your roster
    file lands the same day").

    Reproduction is arithmetic: a week-1 joiner is billed five times for
    $62.46, and an Aug 27 buyer five times for $68.45, because billing starts
    at purchase and not at kickoff.
    """
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    assert re.search(r"charged\s+when you (?:subscribe|buy)", legal, re.I)
    assert not re.search(r"from the week your reports start", legal, re.I), (
        "the contract claims monthly billing begins at kickoff; it begins at "
        "purchase, and checkout is deliberately open in draft season")
    assert re.search(r"is not refunded|not refunded", legal, re.I), (
        "the contract does not disclose that a part-month already billed is "
        "not refunded when the season-end stop fires inside it")


def test_legal_page_actually_protects_the_business() -> None:
    """Consumer promises without limits is a one-sided contract. These are the
    clauses that stop a $29 sale becoming an unbounded claim."""
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    protections = {
        "liability cap": r"total liability to you.{0,80}limited to the amount you",
        "no consequential damages": r"indirect, incidental, special, or consequential",
        "as-is / warranty disclaimer": r"provided <b>as is</b>|provided as is",
        "implied warranty disclaimer": r"merchantability",
        "refund is the exclusive remedy": r"only remedy we offer",
        "no redistribution (protects League Pass)": r"may <b>not</b> forward the full report",
        "third-party data dependency": r"depend on public NFL data",
        "force majeure": r"beyond our reasonable control",
        "right to discontinue": r"change, pause, or discontinue",
        "changes to terms": r"we may update these terms",
        "governing law": r"governed by the laws of",
        "severability": r"unenforceable, the rest stays in force",
    }
    for name, pattern in protections.items():
        assert re.search(pattern, legal, re.I), f"terms are missing: {name}"
    # Protective clauses must not be used to strip consumer rights.
    assert re.search(r"doesn't remove protections you have|"
                     r"nothing here takes away consumer rights", legal, re.I)


def test_the_contract_describes_the_product_actually_sold() -> None:
    """terms.html carries a 'this page wins' clause — so when §1, §7, §9 and
    §10 still described the discontinued Sleeper product (a Rival Report built
    from the league's record, a privacy list of 'your Sleeper user ID and which
    manager you named as your rival'), the operative contract did not cover
    the service being sold, and the privacy policy was inaccurate under
    CalOPPA. Found by a compliance read three weeks before launch."""
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    for stale in (r"Rival Report", r"Sleeper user ID", r"named as your rival",
                  r"league's own publicly readable record", r"Sleeper's public API",
                  r"depend on Sleeper"):
        assert not re.search(stale, legal, re.I), \
            f"terms.html still describes the Sleeper product: {stale!r}"
    # ...and it describes what is actually collected and depended on.
    assert re.search(r"the roster and scoring settings you give us", legal, re.I)
    assert re.search(r"complete list of what we hold", legal, re.I)
    assert re.search(r"never connect to your league", legal, re.I)
    assert re.search(r"public NFL data", legal, re.I)
    # The pitch says the founding rate is locked for every renewal; the
    # contract has to say it too, or the 'legal wins' clause makes the pitch
    # a deceptive-pricing pattern.
    assert re.search(r"Founding subscribers renew at their founding price", legal)
    # 2026 sells one-time passes; the founding promise is the 2027 price.
    assert re.search(r"Founding rate", LANDING) and re.search(r"\$39 USD, never more", legal)


def test_renewal_terms_are_in_sight_of_the_checkout_button() -> None:
    """ROSCA and California's ARL attach the renewal disclosure to the point of
    consent, in visual proximity to it. The join page's renewal sentence lived
    only in the post-submit block — which the paid flow never shows, because
    submit navigates to Stripe. A buyer could reach the payment page having
    seen '$39 · Cancel any time' and nothing else. The terms line now renders
    inside the email step, above the button, and the mode script rewrites it
    per plan: the monthly buyer sees monthly terms, the pass buyer sees $99
    (not the season pass's $39), and a seat holder — who pays nothing — sees
    no billing terms at all."""
    form = re.search(r'<form id="form-email".*?</form>', JOIN, re.S).group(0)
    terms = re.search(r'<p class="terms-line" id="terms-line">(.*?)</p>', form, re.S)
    assert terms, "the renewal terms are not inside the email step's form"
    assert form.index('id="terms-line"') < form.index('id="submit"'), \
        "the terms must come before the button, not after it"
    text = prose(terms.group(1))
    assert re.search(rf"\${SEASON_PRICE}, one payment", text, re.I)
    assert re.search(r"nothing renews", text, re.I)
    assert re.search(r"one per person", text, re.I)
    script = prose(JOIN)
    # Plan-aware rewrites, each naming its own amount.
    assert re.search(r'\$\("terms-line"\)\.textContent = monthlyTerms', script)
    assert re.search(r'\$\("terms-line"\)\.textContent = passTerms', script)
    assert re.search(r"League Pass is \$69, one payment", script)
    assert re.search(r'\$\("terms-line"\)\.style\.display = "none"', script), \
        "a seat holder must not be shown billing terms"


def test_the_legal_page_names_a_real_jurisdiction_and_contact() -> None:
    """A guessed jurisdiction is worse than a blank one — which is why this
    stayed an explicit placeholder until the owner supplied it. Set Aug 26 2026
    to Ontario, Canada (the operator's own province). What this now guards is
    the other direction: the placeholders must not come BACK, because a
    contract with no governing law and a refund route with no address are the
    two gaps that make everything else on the page unenforceable."""
    legal = (SITE / "terms.html").read_text(encoding="utf-8")
    assert re.search(r"Province of Ontario", legal), \
        "governing law lost its jurisdiction"
    assert "hello@beatyourleague.com" in legal, "legal page lost its contact route"
    for ghost in (r"\[jurisdiction", r"\[contact address", "to be set before"):
        assert not re.search(ghost, legal), f"a placeholder came back: {ghost}"
    # The consumer savings clause travels with it: naming Ontario must not read
    # as stripping rights a buyer has where they actually live.
    assert re.search(r"doesn't remove protections you have", legal, re.I)
    for page, name in ((LANDING, "landing"), (JOIN, "join")):
        assert re.search(r'href="(\.\./)?terms\.html"', page), \
            f"{name} page does not link the terms"


def test_withheld_numbers_read_as_a_decision_not_a_defect() -> None:
    """A slot without odds explains itself in plain words — never a version
    number, never a bare blank."""
    assert "rows without odds this week" in SAMPLE_REPORT.lower()
    assert not re.search(r"\bv0\.\d", SAMPLE_REPORT)


LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")


def test_monthly_price_never_undercuts_the_season_pass() -> None:
    """The monthly tier exists to make the pass obvious. If a full season of
    monthly costs LESS than the pass, the anchor inverts and the pass becomes
    the sucker's choice — which is exactly what $6.99 did (PLAN §4).

    Measured in CHARGES, not months. Stripe bills monthly in advance on the
    anniversary, so a subscriber is charged an integer number of times and a
    fractional multiplier prices a customer who does not exist. The old
    `× 3.65` was satisfied by anything above $10.69, which is why it passed at
    a price the modal customer beat: PLAN §4 names the Week 10–12 elimination
    cliff as the point most monthly subscribers leave, and a Week-1 joiner who
    leaves there has been charged exactly three times. At $12.99 that is
    $38.97 — three cents under the pass gross, 63 cents under it net of Stripe
    fees — after three months of collection risk and no upfront cash. A tier
    whose typical customer is worth less than the tier it feeds is a leak, not
    a ladder.
    """
    BILLED_MONTHS = 3      # the modal churn point, and an integer because
    #                        charges are. Sep 8 -> the week 10-12 cliff.
    # Monthly is paused for 2026 but keeps its price on the join page; the
    # invariant holds against the pass on sale now (the $29 one-time pass).
    modal_total = float(MONTHLY_PRICE) * BILLED_MONTHS
    pass_price = float(SEASON_PRICE)
    assert modal_total > pass_price, (
        f"a subscriber who leaves at the elimination cliff has paid "
        f"${modal_total:.2f} against a ${pass_price:.2f} pass — the tier meant "
        f"to feed the pass is worth less than it")


def test_the_contract_and_the_comparison_state_the_price_the_buyer_is_charged() -> None:
    """The landing pricing card is the single source of truth for price, and
    two surfaces were never enrolled in that propagation.

    terms.html is the operative contract under a "this page wins" clause, so a
    stale price there is not a typo — it is the document that governs. And
    compare/index.html is where a diligent buyer checks us against nine
    competitors, which is the worst place to be caught quoting an old number.
    Both were updated by hand during the $12.99 -> $14.99 move and nothing
    would have caught it if either had been missed.
    """
    monthly = re.match(r"(.*)", MONTHLY_PRICE)
    season = re.match(r"(.*)", SEASON_PRICE)
    legal = (SITE / "terms.html").read_text(encoding="utf-8")
    compare = (SITE / "compare" / "index.html").read_text(encoding="utf-8")
    # The compare table quotes NINE competitors' real prices, so only our own
    # row may be swept for a stale figure — scoping it to any narrower thing
    # than <tr class="us"> would be a guard that reads somebody else's number.
    ours = re.search(r'<tr class="us">.*?</tr>', compare, re.S)
    assert ours, "the comparison table no longer marks our own row"

    for page, name in ((legal, "terms.html"), (ours.group(0), "compare, our row")):
        # Monthly isn't sold in 2026: the comparison row quotes only what is.
        assert name == "compare, our row" or f"${monthly.group(1)}" in page, (
            f"{name} does not state the monthly price the landing charges "
            f"(${monthly.group(1)})")
        assert f"${season.group(1)}" in page, (
            f"{name} does not state the season price the landing charges")
        others = {p for p in re.findall(r"\$\d+\.\d\d", page)
                  if p != f"${monthly.group(1)}"}
        assert not others, (
            f"{name} carries another decimal price {sorted(others)} — one of "
            f"them is stale, and terms.html is the operative contract")


def test_every_price_shown_to_a_buyer_names_its_currency() -> None:
    """An unlabelled price is ambiguous to a buyer and a support burden — and
    the ambiguity is not hypothetical here: the seller is in Ontario, so a
    Canadian reading a bare "$39" would reasonably assume CAD and be charged
    roughly a third more at checkout. That gap, discovered at the payment step,
    is exactly what produces a chargeback.

    Owner decision (Aug 26 2026): the figure stays bare at every decision point
    — "$39 USD" six times is clutter for the US majority — and the currency is
    stated ONCE per page, plainly, near the price. So this checks the statement
    exists, not that the token sits beside every numeral."""
    for page, name in ((LANDING, "landing"), (JOIN, "join"),
                       (LEAGUE_PASS, "league pass")):
        assert re.search(r"All prices in US dollars|USD", page), \
            f"{name} page shows a price with no currency stated anywhere"
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    assert re.search(r"All prices are in US dollars", legal, re.I)


def test_league_pass_never_competes_with_the_single_checkout_decision() -> None:
    """PLAN §4: exactly one decision at checkout. The commissioner offer is
    reachable by one link, never a third pricing card."""
    assert re.search(r'href="league-pass\.html"', LANDING), \
        "League Pass must be reachable from the pricing section"
    rendered = markup_only(LANDING)
    assert "$99" not in rendered, \
        "the League Pass price must not appear beside the individual decision"


def test_league_pass_states_its_own_terms() -> None:
    prose_page = prose(LEAGUE_PASS)
    for required in (r"\$69", r"one payment", r"nothing renews",
                     r"no-questions refund", r"18\+", r"not affiliated"):
        assert re.search(required, prose_page, re.I), f"league pass missing: {required}"
    # It must not promise a report to managers who never signed up.
    assert re.search(r"Managers who never sign up simply don't get a report", prose_page, re.I)
    assert re.search(r'href="terms\.html"', LEAGUE_PASS)


def test_league_pass_makes_no_win_promise() -> None:
    prose_page = prose(LEAGUE_PASS)
    assert re.search(r"not a guarantee", prose_page, re.I)
    assert re.search(r"somebody finishes last|exactly one champion", prose_page, re.I)


def test_landing_states_the_weekly_ritual_not_just_the_contents() -> None:
    """People buy a habit, not a document. The page must say what the week
    actually looks like: when it arrives, how long it takes, what you do."""
    # "About a minute" to set the lineup, as How it works and every welcome
    # email say (review F8: the landing said "Ninety seconds" for the same
    # Tuesday act, a figure EMAILS-90 had retired as the game plan's).
    assert re.search(r"set it in about a minute", LANDING_PROSE, re.I)
    assert not re.search(r"ninety seconds|90 seconds", LANDING_PROSE, re.I)
    assert re.search(r"tuesday morning", LANDING_PROSE, re.I)
    assert re.search(r"tick off the game plan", LANDING_PROSE, re.I)


def test_the_funnel_never_promises_what_the_product_cannot_see() -> None:
    """The successor to the waiver-edge test, whose subject died with the
    league read (PLAN §0). The product now sees one roster and public NFL
    data — no rival, no opponent lineup, no league transaction log — so the
    landing page and the published sample may not promise any of it. This is
    the page-level twin of the waitlist email's FORBIDDEN_CLAIMS: the landing
    page sold "Pick your rival" for four days while the signup page had no
    rival on it, which is a broken promise at the moment of highest intent.

    Prose only: the sample's CSS still carries .rival class names from the
    shared template, and a class name is not a promise."""
    def visible(page: str) -> str:
        stripped = re.sub(r"<style\b.*?</style>", "", markup_only(page),
                          flags=re.S | re.I)
        return re.sub(r"<[^>]+>", " ", prose(stripped))

    for page, name in ((visible(LANDING), "landing"),
                       (visible(SAMPLE_REPORT), "sample report")):
        text = page
        for dead in (r"\brivals?\b", r"\bwaivers?\b", r"\bopponents?\b",
                     r"league's own record", r"\bFAAB\b"):
            assert not re.search(dead, text, re.I), (
                f"the {name} still promises {dead!r}, which the product "
                f"cannot see any more")


@requires_sample_league
def test_bid_advice_never_exceeds_what_the_reader_can_pay() -> None:
    """Telling someone with 10 FAAB to bid 38 would waste their season. The
    unaffordable case must say so instead of recommending it."""
    import json as _json
    from engine.week_report import build_week_report, RAW_DIR
    report = build_week_report(RAW_DIR, "289646328504385536", 10, 1)
    left = report["waiver_market"]["my_remaining"]
    if left is None:
        pytest.skip("budget setting unreliable in this league")
    for entry in report["hype"]:
        if entry.get("bid_to_beat") and entry["bid_to_beat"] > left:
            assert entry["affordable"] is False, \
                f"{entry['player_name']}: recommends {entry['bid_to_beat']} with {left} left"


def test_sample_report_explains_what_to_do_with_it() -> None:
    """The buyer's decisive question is 'what do I actually do on Tuesday?'
    The sample answers it with its game plan card and the lineup's own box
    to tick. (This once matched "30-second game plan" — a CSS comment in the
    page's style, not anything a reader sees.)"""
    shown = re.sub(r"<style\b.*?</style>|<[^>]+>", " ", SAMPLE_REPORT, flags=re.S)
    assert re.search(r"Your Game Plan", shown, re.I)
    assert re.search(r"set (the|your|this) lineup", shown, re.I)


# --------------------------------------------------------------------- #
# the comparison page stays honest, or it stops being useful
# --------------------------------------------------------------------- #

def test_the_published_sample_is_the_solo_product() -> None:
    """`make demo` used to write the league demo over site/sample-report.html —
    a page full of features the paid product does not have. The published
    sample must always be the solo render: its title says Report (not Rival
    Report), and it carries the solo banner."""
    assert "Week 10 · Your Report" in SAMPLE_REPORT
    assert "Rival Report" not in SAMPLE_REPORT
    assert "a real week from the 2024 NFL season" in SAMPLE_REPORT
    makefile = (SITE.parent / "Makefile").read_text(encoding="utf-8")
    demo_block = makefile.split("\ndemo:")[1].split("\n\n")[0]
    assert "site/" not in demo_block, \
        "the legacy demo target writes into site/ again"


def test_compare_discloses_its_author_before_anything_else() -> None:
    """The whole trick of a founder-written comparison is the disclosure: a
    reader who finds out later that a "neutral" roundup was written by one of
    the products reads everything else on the domain as marketing. It has to be
    the first thing after the headline, not a footer credit."""
    body = prose(COMPARE.split("<h1")[1])
    first_block = body.split("</p>")[0]
    assert re.search(r"the person who makes Beat Your League", first_block), \
        "authorship must be disclosed in the first paragraph"
    assert re.search(r"one of the products below", first_block)


def test_compare_carries_a_dated_price_stamp() -> None:
    """An undated price table rots into misinformation. The date is the claim's
    boundary, and it must be a real date — not "recently"."""
    assert re.search(r"Prices checked [A-Z][a-z]{2} \d{1,2}, 20\d{2}", COMPARE), \
        "the price-checked stamp lost its date"
    assert re.search(r"prices move|they change", COMPARE, re.I), \
        "the page must say prices drift, so a stale read fails soft"


def test_compare_lists_our_own_weaknesses_like_everyone_elses() -> None:
    """The complete honest comparison is the marketing strategy (PLAN §5) — a
    version that goes soft on its own row is just a longer ad. The row must
    name real product gaps, including the one that matters most to a buyer
    right now: no live track record yet. (It said "until October" until Sep 29
    2026; the record starts with the first subscriber's file, not a date.)"""
    our_row = COMPARE.split('class="us"')[1].split("</tr>")[0]
    for admission in ("No draft kit", "no app", "we're new",
                      "record fills in", "backtest and a sample"):
        assert admission in our_row, \
            f"our own weaknesses column lost {admission!r}"


def test_compare_includes_the_free_answer() -> None:
    """Recommending "pay nobody" where it's true is what separates this page
    from every self-ranking listicle in the niche — it is the honesty principle
    applied to marketing, and the first thing to vanish under conversion
    pressure."""
    assert 'class="free"' in COMPARE
    free_row = COMPARE.split('class="free"')[1].split("</tr>")[0]
    assert re.search(r"\$0", free_row)
    assert re.search(r"pay nobody|start here", free_row, re.I)
    # And at least three competitors are recommended BY NAME for needs we
    # don't serve — a "which one" section that always answers "us" is an ad.
    picks = COMPARE.split("Which one, honestly")[1]
    named = sum(1 for p in ("FantasyPros", "Draft Sharks", "4for4",
                            "Establish The Run") if p in picks)
    assert named >= 3, "the guidance section stopped recommending competitors"


def test_compare_never_denies_a_rival_feature_we_verified_they_have() -> None:
    """Aug 24 2026: the 4for4 row read "Projections for everyone, not decisions
    for your roster." Their own plans page sells a "Start/Sit Tool" and
    "Unlimited LeagueSync Access" at the $59 Pro tier, so the page's single
    most load-bearing property — that a founder-written comparison tells the
    truth about rivals — was false about a named company.

    Per-roster start/sit is a COMMODITY (FantasyPros ships it in every tier
    from $3.99/mo, 4for4 at $59/season, Yahoo's Assistant GM in-app). A page
    that implies otherwise is not merely flattering, it is checkable in one
    click, and the reader who checks stops believing the rest of the domain.

    The paired rule is symmetry: if a rival's strength column advertises "no
    typing", our own weakness column has to admit the typing. Removing a false
    claim about them and leaving the matching omission about us would be the
    same asymmetry wearing a different hat."""
    row = COMPARE.split(">4for4<")[1].split("</tr>")[0]
    assert "not decisions for your roster" not in row, \
        "the 4for4 row denies a start/sit tool their own plans page sells"
    assert re.search(r"start/sit", row, re.I), \
        "their per-roster tool must be acknowledged, not quietly dropped"
    # Our own row carries the mirror admission.
    our_row = COMPARE.split('class="us"')[1].split("</tr>")[0]
    assert re.search(r"you enter it yourself|type or past", our_row, re.I), \
        "we advertise a rival's one-tap sync without admitting our own typing"
    # And the guidance section still sends the sync-wanters to them by name.
    picks = COMPARE.split("Which one, honestly")[1]
    assert re.search(r"rather not enter your roster by hand", picks), \
        "the guidance stopped naming who to use if you won't type a roster"


def test_the_picker_uses_every_setting_it_asks_for() -> None:
    """The page rendered four league-size radios under "Scoring and league
    size decide how every player in your roster is valued" and never read
    them: radio() was called for scoring and template, never for size. Every
    subscriber got a 12-team report and a 12-team ledger bucket whatever they
    picked (found Aug 24 2026, by running the intake path for real).

    The JS/Python contract test cannot catch this — it exercises roster.js
    directly, so the page can stop PASSING a value while the encoder still
    accepts one. This pins the other half of the seam: every radio group the
    page renders has to reach the ref.

    A question we ask and discard is worse than one we never ask: it tells the
    buyer their answer matters, and it is checkable in one click."""
    groups = set(re.findall(r'<input type="radio" name="(\w+)"', JOIN))
    assert groups == {"scoring", "size", "template", "kicker", "defense", "plan"}, \
        f"the picker's question set changed: {groups}"
    call = re.search(r"R\.encodeRoster\((.*?)\);", JOIN, re.S)
    assert call, "the picker no longer builds a ref"
    args = call.group(1)
    for reader, group in (("radio(\"scoring\")", "scoring"),
                          ("template()", "template"),
                          ("leagueSize()", "size")):
        assert reader in args, (
            f"the {group} answer is collected but never reaches the ref — "
            f"the page says it matters, so it has to")
    # The lineup is the base plus the kicker and defense answers (contract
    # C8): template() reaches all three through shapeChoice().
    choice = _js_function(JOIN, "shapeChoice")
    for group in ("template", "kicker", "defense"):
        assert f'radio("{group}")' in choice, f"the {group} answer never reaches the ref"
    assert "R.shapeSlots(s.base, s.kicker, s.defense)" in _js_function(JOIN, "template")
    # The plan switch (Oct 9 2026) reaches the ref through monthlyChosen,
    # which the switch's change listener sets from radio("plan").
    assert "monthlyChosen" in args
    assert re.search(r'monthlyChosen = radio\("plan"\) === "monthly"', JOIN)
    assert re.search(r'function leagueSize\(\)[^}]*radio\("size"\)', JOIN), \
        "leagueSize() stopped reading the size radio"


def test_compare_tables_scroll_on_a_phone() -> None:
    assert COMPARE.count("<table>") <= COMPARE.count("overflow-x:auto"), \
        "the comparison table would scroll the whole page sideways on mobile"


# --------------------------------------------------------------------- #
# the entity sentence is one string, everywhere, forever
# --------------------------------------------------------------------- #

def test_the_entity_sentence_is_identical_everywhere() -> None:
    """PLAN §1's whole mechanism: identical phrasing across independent surfaces
    is the co-occurrence signal that forms an entity, and varying it destroys
    the only channel available. So the sentence is one string — PLAN.md is the
    source of truth, and every surface that carries it must match verbatim.
    The first version of the sentence described the retired product, which is
    why this is a test and not a convention."""
    plan = (SITE.parent / "PLAN.md").read_text(encoding="utf-8")
    match = re.search(r"^> (Beat Your League is a weekly .+?late news\.)$", plan,
                      re.S | re.M)
    assert match, "PLAN §1 lost the blockquoted entity sentence"
    sentence = re.sub(r"\s+", " ", match.group(1).replace("> ", ""))

    # PLAN §1 names its surfaces: meta description, JSON-LD, pitches, README,
    # directories. og:description is NOT one — it is what a group chat shows
    # under a shared link, and the 70-word gate-qualified sentence there read
    # as fine print (pre-launch review M12), so it carries a short benefit line
    # instead (tests/test_prelaunch_landing.py pins it).
    surfaces = {
        "landing meta description":
            re.search(r'<meta name="description" content="([^"]+)"', LANDING).group(1),
        "landing JSON-LD":
            re.search(r'"description": "([^"]+)"', LANDING).group(1),
    }
    pitches = SITE.parent / "content" / "pitches.md"
    if pitches.is_file():
        text = re.sub(r"\s+", " ", pitches.read_text(encoding="utf-8"))
        assert sentence in text, "the pitch template's sentence drifted from PLAN §1"
    for name, found in surfaces.items():
        assert re.sub(r"\s+", " ", found) == sentence, (
            f"{name} differs from PLAN §1's entity sentence — the co-occurrence "
            f"signal only works verbatim")
    # And the sentence may only promise what the product ships.
    for dead in ("rival", "opponent", "waiver", "Sleeper league"):
        assert dead not in sentence, f"the entity sentence promises {dead!r}"


# --------------------------------------------------------------------- #
# structured data stays true to the page it annotates
# --------------------------------------------------------------------- #

def test_structured_data_parses_and_matches_the_page() -> None:
    """Search hygiene is one hour of work and zero ongoing claims — unless the
    JSON-LD drifts from the page, at which point it is a machine-readable lie
    served to every crawler. The prices must be the page's own, and every FAQ
    question in the markup must exist on the page."""
    import json as _json
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                        LANDING, re.S)
    assert blocks, "landing page lost its structured data"
    data = _json.loads(blocks[0])
    graph = data["@graph"]
    product = next(node for node in graph if node["@type"] == "Product")
    prices = {offer["price"] for offer in product["offers"]}
    assert prices == {SEASON_PRICE}, (
        f"structured-data prices {prices} drifted from the page's {{{SEASON_PRICE}}}")
    faq = next(node for node in graph if node["@type"] == "FAQPage")
    page_text = prose(LANDING)
    for question in faq["mainEntity"]:
        assert question["name"] in page_text, (
            f"structured data asks {question['name']!r}, which is not on the page")


# --------------------------------------------------------------------- #
# the evidence pages may only say what their source reports measured
# --------------------------------------------------------------------- #

REPORTS = SITE.parent / "reports"


@pytest.mark.parametrize("page,source", [
    (PROJECTIONS, "projections-eval.md"),
    (NO_CALL, "gate-backtest.md"),
    # Two sources: the parent grading and the early-season arm — the page
    # translates both, and a figure must exist in at least one of them.
    (CONFIDENCE, ("nflverse-backtest.md", "early-season-backtest.md",
                  "setups-backtest.md", "recalibration-backtest.md",
                  "round-two-backtest.md")),
])
def test_every_figure_on_an_evidence_page_exists_in_its_source(page, source) -> None:
    """These pages are hand-written translations of operator reports into buyer
    language, which is exactly the seam where numbers drift: the landing page
    once kept citing a count the product had stopped producing. Every decimal
    and percentage on the page must appear in the report it translates."""
    sources = (source,) if isinstance(source, str) else source
    report = "\n".join((REPORTS / one).read_text(encoding="utf-8")
                       for one in sources)
    source = " + ".join(sources)
    body = re.sub(r"<style\b.*?</style>|<script\b.*?</script>", "", page,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", body)
    # The licence version in the nflverse attribution (RULE N1, a licence term
    # that must appear on every public page) is not a measured figure.
    text = text.replace("CC-BY-4.0", "")
    for figure in sorted(set(re.findall(r"\d+\.\d+", text))):
        assert figure in report, (
            f"{source} page cites {figure}, which is not in the report it "
            f"translates — regenerate or fix the page")


def test_every_setup_on_the_confidence_page_matches_its_graded_run() -> None:
    """The per-setup table (Sep 29 2026) translates reports/setups-backtest.md.
    Every row must match its arm exactly (calls, rate, error, grade), every
    arm must appear, and the one arm whose failing band went the wrong way
    must say so beside its better grade."""
    source = (REPORTS / "setups-backtest.md").read_text(encoding="utf-8")
    arms = re.findall(r"^\| (\w+) \| ([^|]+) \| (\d+) \| \d+ \| ([\d.]+%) \| ([\d.]+%) "
                      r"\| \d+ \| \d+ \| [\d.]+ \| \*\*(\w)\*\* \|$", source, re.M)
    assert len(arms) == 8, "the setups report's summary table changed shape"
    table = CONFIDENCE.split('class="setups">')[1].split("</table>")[0]
    rows = re.findall(r"<tr><td>[^<]+</td><td>([\d,]+)</td><td>([\d.]+%)</td>"
                      r"<td>([\d.]+%)</td><td>(\w)</td></tr>", table)
    assert len(rows) == len(arms)
    assert sorted(rows) == sorted((f"{int(c):,}", r, e, g) for _, _, c, r, e, g in arms)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", CONFIDENCE))
    assert re.search(r"its margins are wide", text) and re.search(r"went the other way", text), \
        "weeks 17-18's better grade lost its disclosures"


def test_the_corrected_number_is_published_exactly_as_it_was_graded() -> None:
    """The recalibration shipped (reports/recalibration-method.md §4). The page
    leads with it, so its figures carry the most weight on the site: every band
    of the held-out table and every corrected setup row must match the report,
    the opening must say which seasons fitted it and which graded it, and its
    stated shortfalls must stay beside it."""
    report = (REPORTS / "recalibration-backtest.md").read_text(encoding="utf-8")
    recal = report.split("#### Recalibrated, 2020–2024")[1].split("##")[0]
    bands = re.findall(r"^\| (\d+)%–(\d+)% \| (\d+) \| (\d+) \| \d+ \| ([\d.]+%) "
                       r"\| ([\d.]+%) \| (\d+)%–(\d+)% \| (\w+) \|$", recal, re.M)
    assert len(bands) == 6
    page_rows = re.findall(r"<tr><td>(\d+)–(\d+)%</td><td>([\d,]+)</td><td>([\d,]+)</td>"
                           r"<td>([\d.]+%)</td><td>([\d.]+%)</td><td>(\d+)–(\d+)%</td>"
                           r'<td class="pass">passes</td></tr>', CONFIDENCE)
    assert sorted(page_rows) == sorted(
        (lo, hi, f"{int(g):,}", f"{int(d):,}", st, ob, cl, ch)
        for lo, hi, g, d, st, ob, cl, ch, verdict in bands if verdict == "calibrated")
    arms = dict(re.findall(r"^\| \w+ \| [^|]+ \| \w \| ([\d.]+%) \| \w \| ([\d.]+%) \|$",
                           report, re.M))
    table = CONFIDENCE.split('class="setups recal"')[1].split("</table>")[0]
    rows = re.findall(r"<tr><td>[^<]+</td><td>([\d.]+%)</td><td>([\d.]+%)</td><td>(\w)</td></tr>",
                      table)
    assert sorted(rows) == sorted((before, after, "B") for before, after in
                                  re.findall(r"^\| \w+ \| [^|]+ \| \w \| ([\d.]+%) \| B \| ([\d.]+%) \|$",
                                             report, re.M))
    assert len(rows) == 7 and arms
    first_screen = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                          CONFIDENCE.split("</h1>")[1].split("<h2")[0]))
    assert "2014–2019" in first_screen and "2020–2024, seasons it never saw" in first_screen
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", CONFIDENCE))
    assert re.search(r"five seasons, not eleven", text), "the held-out window's width went missing"
    assert re.search(r"weeks 2–3 and 17–18 are left uncorrected", text)


def test_the_projections_page_never_quotes_the_gap_without_its_uncertainty() -> None:
    """The source report's own rule: 'do not quote the gap without the p-value'.
    47-31 on one season is suggestive, not conclusive, and quoting 68.8% vs
    64.4% bare would claim more than was measured."""
    text = re.sub(r"<[^>]+>", " ", prose(PROJECTIONS))
    assert "68.8%" in text and "64.4%" in text
    assert re.search(r"0\.089", text), "the p-value no longer travels with the gap"
    assert re.search(r"suggestive, not conclusive", text, re.I)
    assert re.search(r"one league|one season", text, re.I), \
        "the single-league scope disclosure went missing"
    # And the page leads with the unflattering half, which is the whole point.
    first_screen = prose(PROJECTIONS.split("</h1>")[1].split("<h2")[0])
    assert re.search(r"beat our own numbers|beat us", first_screen, re.I)


def test_the_no_call_page_claims_improvement_never_rescue() -> None:
    """The measurement's conclusion is deliberately uncomfortable: the filter
    helps and does not earn an accuracy claim. The page exists to publish that,
    and the first thing conversion pressure will do is soften it."""
    text = re.sub(r"<[^>]+>", " ", prose(NO_CALL))
    assert re.search(r"an improvement, not a\s*rescue", text, re.I)
    assert re.search(r"1 of 6 to 2 of 5", text)
    assert re.search(r"does not,? by itself,? earn a published accuracy claim"
                     r"|not enough to brag about", text, re.I)
    assert re.search(r"declines\s+more calls than it makes", text, re.I)
    # The failing buckets stay on the page.
    assert NO_CALL.count('class="off"') >= 3, "the off buckets were laundered"


def test_the_confidence_page_leads_with_what_it_may_not_claim() -> None:
    """The buyer translation of reports/nflverse-backtest.md — the live
    product's own grading. Its preregistered rule landed on Grade C, whose
    terms are: the numeral prints as a recorded prediction only, and no claim
    that it is right appears on any surface. The page exists to close the
    chain of evidence a diligent buyer found open ('the number I'd pay for has
    no published test behind it') WITHOUT becoming that claim. So the refusal
    leads, the four failing bands stay, the flattering direction of the
    failure is stated beside the verdict that it still fails, the scope the
    run actually covered is named, and the older league study's headline is
    never quoted beside this one (the report's own rule)."""
    text = re.sub(r"<[^>]+>", " ", prose(CONFIDENCE))
    first_screen = prose(CONFIDENCE.split("</h1>")[1].split("<h2")[0])
    assert re.search(r"does not let us tell you the number is right", first_screen), \
        "the refusal must lead, before any figure"
    assert CONFIDENCE.count('class="off"') == 4, "the failing bands were laundered"
    assert CONFIDENCE.count('class="ok"') == 2
    assert re.search(r"Two of six pass", text)
    assert re.search(r"wrong in a flattering direction is still wrong", text, re.I)
    assert re.search(r"no claim that the number\s+is right", text, re.I)
    assert re.search(r"full PPR, 12 teams, the standard lineup", text), \
        "the scope the run covered must travel with the number"
    assert re.search(r"team defense never carries a\s+percentage", text, re.I)
    for other_study in ("53.5%", "2,056", "62.5% to", "77.2%"):
        assert other_study not in text, \
            "the two studies measure different questions and may not sit side by side"
    assert 'href="ledger/index.html"' in CONFIDENCE
    assert "join/index.html" in CONFIDENCE, "proof page is a dead end"
    # The early-season arm's section keeps its own load-bearing caveats: the
    # failing band beside the passing count, the measured scope, the row-level
    # disclosure promise, and week 1 staying numberless for everyone.
    assert re.search(r"four of five judgeable bands passed", text)
    assert re.search(r"failed high again", text), \
        "the arm's failure direction was laundered off the page"
    assert re.search(r"full PPR, 12 teams, the standard lineup", text)
    assert re.search(r"last season\s+counted in", text)
    assert re.search(r"week 1 stays numberless", text, re.I)


def test_selling_surfaces_carry_no_grade_c_banned_words() -> None:
    """reports/nflverse-backtest-method.md §1, frozen before the run: at Grade
    C the words 'calibrated', 'tested', 'proven', 'accurate' and 'we hit X%'
    are banned on every surface, and the 5-row availability-controlled table
    leaves the landing regardless of grade. The landing carried that table and
    a 'Tested on two full seasons' chip for a day after the grade was
    computed, and the rewrite that removed them nearly shipped 'Tested' three
    more times. The evidence pages are exempt in one narrow way: a table's own
    verdict column and a sentence describing that a grading happened, beside
    its failures, are the report's vocabulary, not a claim."""
    banned = r"\b(calibrated|tested|proven|accurate)\b|we hit \d"
    # The samples are here because the review sweep (Aug 24) found "tested" in
    # the published sample's own DEF-gate prose — product copy renders onto
    # these pages, so a leak in engine wording ships here first. terms.html is
    # here because its warranty disclaimer said "accurate" (a negation, but
    # the frozen ban is on the word, and reword-not-allowlist is the precedent).
    surfaces = {"landing": LANDING, "join": JOIN,
                "league-pass": (SITE / "league-pass.html").read_text(encoding="utf-8"),
                "compare": COMPARE, "how it works": HOW,
                "sample": SAMPLE_REPORT,
                "sample-first-week": (SITE / "sample-first-week.html").read_text(encoding="utf-8"),
                "legal": (SITE / "terms.html").read_text(encoding="utf-8")}
    for name, page in surfaces.items():
        visible = re.sub(r"<head>.*?</head>|<script\b.*?</script>|<style\b.*?</style>|"
                         r"<!--.*?-->", " ", page, flags=re.S | re.I)
        visible = re.sub(r"<[^>]+>", " ", visible)
        hit = re.search(banned, visible, re.I)
        assert not hit, f"{name} carries a Grade-C banned word: {hit.group(0)!r}"
    assert 'class="caltable"' not in LANDING, \
        "the availability-controlled table is deleted from the landing at every grade"

    # site/backtest.html is NOT swept, and the reason is recorded here rather
    # than left implicit: it is the grading report itself, published verbatim,
    # so its "calibrated" verdicts and its hit rate are the RUN's vocabulary
    # beside the run's failures — not a claim this site makes. That exemption
    # is only honest while it is true, so it is checked: every banned word on
    # that page must exist in the source it publishes.
    from render.backtest_site import SOURCE
    source_text = SOURCE.read_text(encoding="utf-8").lower()
    page = re.sub(r"<[^>]+>", " ", (SITE / "backtest.html").read_text(encoding="utf-8"))
    for word in set(re.findall(banned, page, re.I)):
        assert word.lower() in source_text, (
            f"{word!r} is on the backtest page but not in the report it "
            f"publishes — that is this site's claim, not the run's")


# --------------------------------------------------------------------- #
# no betting positioning anywhere buyer-facing (principle 4)
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("page,name", [(LANDING, "landing"), (JOIN, "join"),
                                       (LEDGER, "ledger"), (COMPARE, "compare"),
                                       (PROJECTIONS, "projections"),
                                       (NO_CALL, "no-call"), (CONFIDENCE, "confidence"),
                                       (FIRST_WEEK_SAMPLE, "first-week sample"),
                                       (HOW, "how it works"),
                                       (LEAGUE_PASS, "league pass")])
def test_no_betting_language(page: str, name: str) -> None:
    banned = r"\b(parlay|sportsbook|against the spread|bet now|odds boost|wager)\b"
    assert not re.search(banned, page, re.I), f"betting language crept into {name}"


def test_published_backtest_is_generated_not_hand_edited() -> None:
    """The page claims of itself that it is regenerated from the grading run's
    own output and never hand-edited. That claim was maintained by hand and
    drifted — the published page once carried a generation timestamp older
    than its own source. This asserts the claim is structurally true: what the
    generator produces from the source IS what is published. The source is
    named from the module so the message cannot go stale again."""
    from render.backtest_site import SOURCE, build
    published = (SITE / "backtest.html").read_text(encoding="utf-8")
    assert build() == published, (
        f"site/backtest.html is out of date with {SOURCE.name} — "
        "run `python -m render.backtest_site`")


def test_the_backtest_generator_refuses_to_drop_a_figure() -> None:
    """The whole point of the page is faithful publication, so a conversion
    that silently lost a row — especially a FAILING row — must fail loudly
    rather than publish a laundered record."""
    from render.backtest_site import SOURCE, verify
    md = SOURCE.read_text(encoding="utf-8")
    assert verify(md, "<p>nothing here</p>"), "verify() passed an empty page"
    page = (SITE / "backtest.html").read_text(encoding="utf-8")
    assert not verify(md, page), "the published page is not faithful to its source"
    # A page missing only the failing bands must still be rejected — and
    # dropping SOME of them counts: the check used to match the substring
    # ">off<", which also matches inside "<b>off</b>", so it double-counted
    # and a page that lost half its failures would have cleared it.
    stripped = page.replace("<b>off</b>", "<b>ok</b>", 1)
    assert any("did not survive" in p for p in verify(md, stripped)), \
        "dropping one failing band was accepted"
    # The source's own grade is required content, read from the source rather
    # than hardcoded, so this holds whichever report the page publishes.
    graded_out = re.sub(r"Grade [A-D]", "Grade &nbsp;", page)
    assert any("grade" in p for p in verify(md, graded_out))


# --------------------------------------------------------------------- #
# the funnel asks and the artifacts recruit
# --------------------------------------------------------------------- #


def test_every_proof_page_ends_with_an_ask() -> None:
    """The sample report, backtest and ledger are the highest-intent surfaces
    in the funnel; each used to end at a footer with no way to buy."""
    backtest = (SITE / "backtest.html").read_text(encoding="utf-8")
    sample = SAMPLE_REPORT
    # D15 (promise audit): the sample's ask follows the landing's checkout
    # state — the join page while it can sell, the waitlist while it can't.
    from render.report import checkout_open
    ask = "join/index.html" if checkout_open() else 'href="index.html#watch-form"'
    assert ask in sample, "sample report is a dead end"
    assert "join/index.html" in backtest, "backtest page is a dead end"
    assert "../join/index.html" in LEDGER, "ledger page is a dead end"


def test_the_demo_band_never_reaches_a_live_report() -> None:
    """Selling a subscriber the thing they already own reads as spam. The
    closing ask renders on the anonymized demo only."""
    from render.report import demo_band
    assert demo_band({"anonymized_demo": True})
    assert demo_band({"historical_demo": True}) == ""     # live-shaped render
    assert demo_band({}) == ""


def test_forward_line_is_gated_on_a_real_destination(monkeypatch) -> None:
    """An acquisition line with nowhere to go is worse than none. With SITE_URL
    set it appears ABOVE the cancellation block; without it, silence."""
    from render.report import _forward_line
    monkeypatch.delenv("SITE_URL", raising=False)
    assert _forward_line() == ""
    monkeypatch.setenv("SITE_URL", "https://example.com/")
    line = _forward_line()
    assert "example.com/join" in line
    # The ledger link left the forward line Sep 29 2026: a forwarded report is
    # a selling surface, and the grading pages are kept off every one.
    assert "ledger" not in line


def test_launch_notify_uses_the_list_endpoint_never_the_seat_form() -> None:
    """The closed-checkout capture keeps the email and the checked roster's ref
    (contract C6, I1 — the launch email links back to it), on the list
    backend. The seat form endpoint must stay reserved for League Pass seats —
    an individual signup posted there would bypass the payment architecture."""
    handler = JOIN.split('$("form-email").addEventListener')[1]
    closed = handler.split("if (!link) {")[1].split("showSeatLink();")[0]
    assert "NOTIFY_LIST_ENDPOINT" in closed
    assert "FORM_ENDPOINT" not in closed
    assert "league_id" not in closed, "launch-notify carries an email and a roster ref only"
    # C6: the row carries the ref checkout WOULD have used — the tagged one.
    assert 'kind: "waitlist", email: email, ref: tagged' in closed
    # Every not-open outcome — kept, failed, or nothing to keep it with — says
    # checkout is not open, and says exactly what was kept: the roster WITH
    # the email when the row went in, and otherwise that it isn't saved with
    # us (it stays in the page's own address). Read per message, so a new
    # outcome cannot slip in without both.
    messages = re.findall(r'show(?:Error\("err-email", |Ok\()(.*?)\);', prose(closed), re.S)
    assert len(messages) >= 3, messages
    kept = [m for m in messages if "we kept" in m]
    assert len(kept) == 1 and "we kept your email and this roster" in kept[0], messages
    for message in messages:
        assert "isn't open just yet" in message, f"a not-open outcome hides it: {message}"
        if message not in kept:
            assert "isn't saved" in message, f"a not-open outcome implies a save: {message}"
    # The kept one is a done message, said only after the backend accepted it.
    ok_block = closed.split('closedAction(otherLink) === "list"')[1].split(".catch(")[0]
    assert "if (!response.ok) throw" in ok_block.split("showOk(")[0]


def test_backtest_page_carries_no_internal_register() -> None:
    """The backtest page is deliberately the technical document — commands and
    file paths are its verifiability story and stay. But the internal spec,
    the AI layer, version numbers and phase names are operator vocabulary, and
    this page is read by exactly the persona a group chat sends to vet the
    purchase. 'CLAUDE.md' on a public page is the screenshot the
    invisible-machinery rule exists to prevent. Every earlier sweep exempted
    this page wholesale; that exemption was the leak."""
    page = (SITE / "backtest.html").read_text(encoding="utf-8")
    for banned in (r"CLAUDE", r"\bLLM\b", r"v0\.\d", r"Phase \d",
                   r"week_report\.json", r"\bdeterministic\b"):
        assert not re.search(banned, page), f"{banned!r} leaked onto the public backtest page"


def test_every_page_carries_social_meta_and_a_favicon() -> None:
    """A shared link is the product's main growth channel — the group chat.
    A page without og: meta unfurls as a bare URL; a page without a favicon
    looks unfinished in the tab bar. Both generators emit theirs too, so this
    covers generated pages by construction."""
    for page_path in sorted(SITE.rglob("*.html")):
        text = page_path.read_text(encoding="utf-8")
        rel = page_path.relative_to(SITE)
        for needle in ('property="og:title"', 'property="og:description"',
                       'name="twitter:card"', 'rel="icon"'):
            assert needle in text, f"{rel} is missing {needle}"


def test_wide_tables_scroll_inside_their_own_container() -> None:
    """Generated tables (backtest, ledger) are wider than a phone. Each must
    live in an overflow-x container so the table scrolls, never the page."""
    for name in ("backtest.html", "ledger/index.html"):
        text = (SITE / name).read_text(encoding="utf-8")
        opens = text.count("<table>")
        wrapped = text.count('overflow-x:auto')
        assert wrapped >= opens, \
            f"{name}: {opens} tables but only {wrapped} scroll containers"
    # The backtest page always carries tables; if that ever hits zero the
    # generator broke, not the guard.
    assert (SITE / "backtest.html").read_text(encoding="utf-8").count("<table>") > 0


def test_picker_inputs_live_in_real_forms() -> None:
    """Enter (and the mobile keyboard's Go) must submit the username and email
    steps — dead Enter keys read as a broken page. The forms never POST
    anywhere themselves; submit is prevented and routed to the buttons."""
    for form_id, button_id in (("form-roster", "resolve"),):
        assert f'<form id="{form_id}"' in JOIN, f"missing {form_id}"
        assert f'wireEnter("{form_id}", "{button_id}")' in JOIN
    # The router must prevent the default submission (no reload) and never
    # re-click a button whose own click produced the submission (no double run).
    assert "e.preventDefault();" in JOIN and "e.submitter !== btn" in JOIN
    # The email form is its own handler — submitting IS the action there —
    # but it must still prevent the reload.
    assert '$("form-email").addEventListener("submit"' in JOIN


def test_seat_and_pass_modes_rewrite_the_ask() -> None:
    """A seat holder must never read a price for something their commissioner
    already paid; a pass or monthly buyer must never read the season price.
    The static header stays the season default — the rewrites are JS, so we
    pin their presence and their key phrases. (The header chips that repeated
    the pitch were removed in the truth pass: the pitch carries the price with
    its terms, and the button says what is open.)"""
    assert 'id="header-pitch"' in JOIN and 'id="header-chips"' not in JOIN
    seat = prose(_js_code(JOIN).split("} else if (SEAT_MODE)")[1].split("} else if (WANTS_MONTHLY)")[0])
    assert "Nothing to pay." in seat and not re.search(r"\$\d", seat), "a seat reads a price"
    assert "already paid" not in prose(_js_code(JOIN).split("} else if (SEAT_MODE)")[1]
                                       .split("} else if (WANTS_MONTHLY)")[0])
    assert "every manager in your league" in prose(JOIN) and "claims their seat" in prose(JOIN)
    assert f"${MONTHLY_PRICE} a month" in prose(_js_function(JOIN, "monthlyPlan"))
    # The pass buyer is told, on the way to Stripe, where the seat link will
    # come from: the welcome email, which carries a link naming THIS pass
    # (contract C4). The page itself no longer hands out the generic ?pass=1
    # link, whose typed buyer's address is how a seat claim got lost (LP-D1).
    share = _js_function(JOIN, "showSeatLink")
    assert 'id="seat-share"' in JOIN and "welcome email has the link" in share
    assert '"?pass=1"' not in share


def test_the_logo_mark_is_one_shape_on_every_surface() -> None:
    """The mark shipped on the landing hero and nowhere else — not on the report
    a subscriber pays for, not on the ledger or backtest a skeptic is sent to.
    It is now single-sourced in render/report.py; this pins that every surface
    carries it AND that they all carry the SAME geometry, so a hand-edit to one
    page cannot quietly fork the logo."""
    from render.report import MARK_PATH

    surfaces = [
        SITE / "index.html", SITE / "join" / "index.html",
        SITE / "league-pass.html", SITE / "terms.html", SITE / "privacy.html",
        SITE / "backtest.html", SITE / "ledger" / "index.html",
        SITE / "sample-report.html",
        SITE.parent / "rival-report-template.html",
    ]
    for path in surfaces:
        text = path.read_text(encoding="utf-8")
        assert MARK_PATH in text, f"{path.name} is missing the logo mark"
    # The silhouette stays a lens of two arcs (the Sep 29 2026 redraw), never an
    # ellipse — an ellipse is what made the first mark read as a sticker.
    assert MARK_PATH.count("A33.5 33.5") == 2
    assert "<ellipse" not in (SITE / "index.html").read_text(
        encoding="utf-8").split('class="brand"')[1].split("</svg>")[0]


def test_the_backtest_draws_its_own_calibration_claim() -> None:
    """The page's whole argument is "when we say 64%, roughly 64% hit", and it
    was only ever tabulated. The chart must exist, must carry one dot per
    published bucket, and must plot the UNCONDITIONAL table — the
    availability-controlled one conditions on an outcome unknowable at call
    time and may never be drawn as if it were accuracy."""
    page = (SITE / "backtest.html").read_text(encoding="utf-8")
    figures = [block.split("</figure>")[0]
               for block in page.split('class="calfig"')[1:]]
    assert figures, "the calibration chart is missing"
    # EXACTLY one. This assertion is the bug: the page carried a second chart
    # drawn from the availability-controlled table — the most flattering
    # possible picture of the one table that may never be shown as accuracy —
    # and the old test read `split(...)[1]` only, so it inspected the innocent
    # figure and passed while the forbidden one shipped beside it.
    assert len(figures) == 1, (
        f"{len(figures)} calibration charts on the page; a second chart can "
        f"only be a diagnostic table drawn as accuracy")
    figure = figures[0]
    source = (REPORTS / "nflverse-backtest.md").read_text(encoding="utf-8")
    bands = len(re.findall(r"^\| \d+%–\d+%", source, re.M))
    assert bands, "the source report lost its calibration table"
    assert figure.count("<circle") == bands, "one dot per published band"
    assert "perfect calibration" in figure
    # The caption must describe the picture actually drawn. It used to be
    # hardcoded prose about a flat line — true of the study it was written
    # for, false of any other — so this recomputes the verdict from the
    # source's own table and requires the words to match it.
    rows = re.findall(r"^\| \d+%–\d+% \|[^|]*\|[^|]*\|[^|]*\| ([\d.]+)% \| ([\d.]+)% \|",
                      source, re.M)
    assert rows, "could not read the source's stated/observed columns"
    stated = [float(a) for a, _ in rows]
    observed = [float(b) for _, b in rows]
    residuals = [o - s for s, o in zip(stated, observed)]
    spread = max(observed) - min(observed)
    above = [r for r in residuals if r > 0.5]
    below = [r for r in residuals if r < -0.5]
    if spread < 8.0:
        assert "barely sorts" in figure
    elif above and below:
        # The honest wording for a chart that is above at some bands and below
        # at others is a COUNT, never "every".
        assert f"{len(above)} of {len(residuals)} bands" in figure
        assert "at all" not in figure
    elif not below:
        assert f"ABOVE the diagonal at all {len(residuals)} bands" in figure
    elif not above:
        assert f"BELOW the diagonal at all {len(residuals)} bands" in figure
    assert "flat" not in figure or spread < 8.0, \
        "the caption calls a sorting chart flat"
    # the diagnostic table's giveaway values may not appear in ANY drawing
    for forbidden in ("77.2", "63.6", "78.3", "62.1", "69.1", "73.9"):
        for n, drawn in enumerate(figures, 1):
            assert forbidden not in drawn, \
                f"availability-controlled figure {forbidden} was drawn as " \
                f"accuracy in chart {n}"


def test_the_generator_refuses_a_list_item_it_split_in_half() -> None:
    """The source is hand-wrapped; the converter consumed only lines that
    themselves began with a bullet, so every wrapped item published as a
    one-line <li> plus an orphaned <p> — "week-18 resting is a different" and
    "population." as separate blocks. verify() could not see it: every FIGURE
    was present, the <li> COUNT still matched (the halves land in <p>), and
    flattening the page rejoins the halves into text that reads correct. So
    the check compares the source's items against the <li> contents."""
    from render.backtest_site import to_html, verify
    # A valid miniature source: the grade heading is required of any source
    # this module publishes, so a fragment without one is correctly refused.
    md = ("## Grade C\n\nno accuracy claim.\n\n## Excluded\n\n"
          "- **Weeks 17-18**: fantasy seasons are over and week-18 resting is a\n"
          "  different population.\n"
          "- **Pre-season rows**: a week number means a different game.\n")
    page = to_html(md)
    assert not verify(md, page), "a correctly converted list was rejected"
    assert page.count("<li>") == 2
    assert "different population." in page.split("</li>")[0], \
        "the wrapped continuation did not land inside its own item"
    # The old behaviour: the continuation escapes into a paragraph.
    broken = page.replace(" different population.</li>",
                          "</li></ul><p>different population.</p><ul>")
    assert any("did not survive whole" in p for p in verify(md, broken))


def test_the_chart_never_says_every_band_unless_every_band() -> None:
    """The caption branched on the MEAN residual, which cancels. Reproduced
    against the generator: errors of +12,+11,+8,-7,-12,-13 average to nearly
    zero and it called a wildly miscalibrated chart 'tracking the diagonal';
    a positive mean with one band below published 'above at every bucket'
    about a picture whose LARGEST band sat below. Both are false statements on
    a page whose whole value is being faithful, so the branch is on the
    per-band residuals now."""
    from render.backtest_site import _calibration_chart

    def chart(pairs):
        head = ["Stated confidence", "Graded", "Decided", "Ties", "Stated avg",
                "Observed", "95% interval", "Verdict"]
        body = [[f"{int(st)}-{int(st) + 5}%", "400", "400", "0", f"{st}%",
                 f"{ob}%", f"{ob - 4:.0f}% - {ob + 4:.0f}%", "calibrated"]
                for st, ob in pairs]
        return _calibration_chart(head, body)

    # Mixed, mean cancels: must NOT claim it tracks the diagonal.
    mixed = chart([(52, 64), (57, 68), (62, 70), (67, 60), (72, 60), (82, 69)])
    assert "track the diagonal" not in mixed
    assert re.search(r"above the diagonal at \d of \d bands and below it at \d", mixed)
    # One band below: must not say "all".
    almost = chart([(52, 51), (57, 62), (62, 68), (67, 74), (72, 80), (82, 90)])
    assert "at all 6 bands" not in almost, "one band sits below and the caption said all"
    assert "5 of 6" in almost
    # Genuinely all above: may say all.
    everyone = chart([(52, 58), (57, 64), (62, 70), (67, 76), (72, 82), (82, 90)])
    assert "ABOVE the diagonal at all 6 bands" in everyone


def test_the_chart_draws_every_band_inside_its_own_frame() -> None:
    """The axis window was hardcoded 45-90%, sized for one study. Repointing
    the page at another put the top band's dot and its entire error bar
    OUTSIDE the SVG — a chart silently omitting its most extreme result, on
    the page that exists to publish results whole."""
    page = (SITE / "backtest.html").read_text(encoding="utf-8")
    figure = page.split('class="calfig"')[1].split("</figure>")[0]
    box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', figure)
    assert box, "the chart lost its viewBox"
    width, height = float(box.group(1)), float(box.group(2))
    ys = [float(y) for y in re.findall(r'<circle cx="[\d.]+" cy="([-\d.]+)"', figure)]
    ys += [float(y) for y in re.findall(r'<line x1="[\d.]+" y1="([-\d.]+)"', figure)]
    ys += [float(y) for y in re.findall(r'y2="([-\d.]+)"', figure)]
    xs = [float(x) for x in re.findall(r'<circle cx="([-\d.]+)"', figure)]
    assert ys and xs
    assert all(0 <= y <= height for y in ys), \
        f"chart draws outside its frame vertically: {[y for y in ys if not 0 <= y <= height]}"
    assert all(0 <= x <= width for x in xs)


def test_the_diagnostic_table_is_never_charted_whatever_its_position() -> None:
    """The rule is the SECTION, not the position. A naive "chart the first
    calibration table" fix would pass today (the publishable table happens to
    come first) and silently invert the moment a report put the diagnostic
    above it — charting the forbidden table and suppressing the real one."""
    from render.backtest_site import to_html

    def table(rows: str) -> str:
        return ("| Stated confidence | Graded | Decided | Ties | Stated avg "
                "| Observed | 95% interval | Verdict |\n"
                "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |\n" + rows)

    diagnostic = table(
        "| 50-55% | 375 | 373 | 2 | 52.4% | 57.4% | 52% - 62% | calibrated |\n"
        "| 55-60% | 310 | 302 | 8 | 57.4% | 58.6% | 53% - 64% | calibrated |\n"
        "| 60-65% | 215 | 209 | 6 | 62.1% | 63.6% | 57% - 70% | calibrated |\n")
    publishable = table(
        "| 50-55% | 617 | 608 | 9 | 52.4% | 53.3% | 49% - 57% | calibrated |\n"
        "| 55-60% | 539 | 525 | 14 | 57.4% | 53.0% | 49% - 57% | off |\n"
        "| 60-65% | 399 | 390 | 9 | 62.2% | 52.6% | 48% - 57% | off |\n")
    for order in (
        f"## Calibration\n\n{publishable}\n"
        f"## Calibration, availability controlled (diagnostic)\n\n{diagnostic}",
        f"## Calibration, availability controlled (diagnostic)\n\n{diagnostic}\n"
        f"## Calibration\n\n{publishable}",
        # And a diagnostic whose heading says NONE of the words a denylist
        # would look for, placed first. Guessing "not a diagnostic" from prose
        # fails open: this one used to take the chart AND suppress the real
        # table via the once-per-page latch. The rule is an allowlist now.
        f"## Calibration among head-to-heads where both played\n\n{diagnostic}\n"
        f"## Calibration\n\n{publishable}",
    ):
        figures = to_html(order).split('class="calfig"')[1:]
        assert len(figures) == 1, "one chart, whatever the order of the tables"
        drawn = figures[0].split("</figure>")[0]
        assert "63.6" not in drawn, "the diagnostic table was charted"
        assert "53.3" in drawn, "the publishable table was not charted"


def test_the_retired_study_stays_in_the_repo_not_on_the_site() -> None:
    """Owner decision, Aug 24 2026: archival deep pages confuse buyers and
    invite scrutiny of a product that no longer exists, so the retired
    Sleeper-era study is NOT published as a page. What the honesty
    architecture still requires — and this pins — is that the record itself
    survives: reports/backtest.md stays generated and unedited with its own
    first-line header, its unflattering figures intact, and the live page's
    "What this is not" section still names it and the non-comparability rule.
    Acknowledged in the record, not sold on the site."""
    assert not (SITE / "retired-backtest.html").exists(), \
        "the retired study is back on the site against the owner decision"
    retired = (REPORTS / "backtest.md").read_text(encoding="utf-8")
    assert "a data stack the product no longer runs" in retired.split("\n")[0]
    assert "53.5%" in retired and "-5670.6" in retired, \
        "the retired study lost its own unflattering figures"
    live = re.sub(r"<[^>]+>", " ", (SITE / "backtest.html").read_text(encoding="utf-8"))
    assert "not comparable to" in live and "backtest.md" in live, \
        "the live page no longer acknowledges the earlier study"
    assert "53.5" not in live, "the two figures may not share a surface"
    # And the generator REFUSES the retired source outright (review, Aug 24:
    # when this was a mere grade exemption, the Makefile's old invocation
    # `--source reports/backtest.md` still built the retired figures under the
    # live masthead and wrote them over site/backtest.html — one shell-history
    # recall from publishing 53.5% as the record behind today's numbers).
    import pytest as _pytest
    from render.backtest_site import build
    with _pytest.raises(SystemExit, match="retired study"):
        build(REPORTS / "backtest.md")

def test_verify_cannot_be_disabled_by_rewording_the_source() -> None:
    """Two of verify()'s checks keyed on literal strings — the word "off" and
    an exact "## Grade X" heading — and BOTH silently switched themselves off
    when the source worded things differently, which is the opposite of what a
    guard should do when it stops understanding its input."""
    from render.backtest_site import SOURCE, verify
    md = SOURCE.read_text(encoding="utf-8")
    page = (SITE / "backtest.html").read_text(encoding="utf-8")
    assert not verify(md, page)
    # Reworded verdicts: the guard follows the source's vocabulary.
    assert any("did not survive" in p for p in
               verify(md.replace("**off**", "**miscalibrated**"),
                      page.replace("<b>off</b>", "<b>calibrated</b>")))
    # A renamed grade heading must FAIL, not skip.
    assert any("grade" in p for p in
               verify(md.replace("## Grade C", "## Grade C — no claim"),
                      page.replace("Grade C", "Grade A")))
    assert any("states no grade" in p for p in verify("## Headline\n\ntext", page))


def test_the_who_can_cover_sentence_reads_like_a_person() -> None:
    """This line is generated from two counts, and both edge cases used to
    expose the machine: a full count read "11 of the other 11 teams can cover
    that", and the singular case lost its plural — "one of the other 11 team"."""
    from render.report import who_can_cover

    assert who_can_cover(11, 11) == "every other team in your league can cover that"
    assert who_can_cover(12, 11) == "every other team in your league can cover that"
    assert who_can_cover(1, 11) == "one of the other 11 teams can cover that"
    assert who_can_cover(8, 11) == "8 of the other 11 teams can cover that"
    assert who_can_cover(0, 11).startswith("nobody else")
    assert who_can_cover(None, 11).startswith("we can't tell")
    # no denominator available: the noun agrees with the count
    assert who_can_cover(1, None) == "one team can cover that"


def test_last_weeks_opponent_is_anonymised_on_the_public_demo() -> None:
    """Last week's opponent is a DIFFERENT manager from this week's rival, and
    their name is baked into a prose headline rather than sitting in a label
    field. The first version of that section published a real Sleeper handle on
    the marketing page; the naming guard caught it."""
    from render.report import anonymize_for_public

    report = {
        "meta": {"my_label": "Me", "rival_label": "Them",
                 "named_rival_label": None, "league_name": "L"},
        "last_week": {"opponent_label": "realperson99",
                      "headline": "realperson99 beat you 120.0-100.0."},
    }
    out = anonymize_for_public(report)
    assert "realperson99" not in str(out), \
        "last week's opponent survived the scrub"
    assert "Last Week's Opponent" in out["last_week"]["headline"]


def test_every_real_stamped_figure_still_exists_in_the_report() -> None:
    """A card stamped "Real output" is a factual claim about our own output,
    and the landing page is hand-written while the report is generated — so
    the two drift silently. They did, twice: the page once advertised "above
    four of their set starters" after the engine stopped producing that count,
    and after the Aug 24 redesign THIS TEST matched zero cards (its regex was
    anchored on the old markup) and passed while checking nothing. So: the
    guard sweeps every `.filecard`, requires that it found the cards it
    expects to exist, and pins every figure — integers and decimals — to the
    published sample. Since the phone and the inbox cards became GENERATED
    (contract C11, render/phone.py) the guard sweeps the generated markup:
    the phone's card and the three that follow it, and a kickoff time counts
    as a figure (the Thursday item quotes one and nothing else)."""
    import html as _html
    # Re-anchored Sep 29 2026: the redesign states "Real file" once, not on
    # every card, so the cards carry a data marker and a closing comment.
    # Oct 25 2026: the phone's card carries an id before its marker.
    cards = re.findall(r'<div class="filecard[^"]*"[^>]*\bdata-real="[^"]+"[^>]*>(.*?)<!--/card-->',
                       LANDING, re.S)
    assert len(cards) >= 4, (
        "the landing lost its Real-output cards, or the markup moved and this "
        "guard went blind again — re-anchor it, never delete it")
    flat_sample = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                                                            SAMPLE_REPORT)))
    for card in cards:
        body = _html.unescape(re.sub(r"<!--.*?-->", " ", card, flags=re.S))
        body = re.sub(r"<[^>]+>", " ", body)
        figures = set(re.findall(r"\d+\.\d+", body))
        figures |= {m for m in re.findall(r"\d+%", body)}
        figures |= {m for m in re.findall(r"\d+ targets \([\d.]+ a game\)", body)}
        figures |= {m for m in re.findall(r"last \d games", body)}
        figures |= {m for m in re.findall(r"\d{1,2}:\d\d [AP]M ET", body)}
        assert figures, "a Real-output card with no figures is not this guard's card"
        for figure in sorted(figures):
            assert figure in flat_sample or figure in SAMPLE_REPORT, (
                f"the landing page cites {figure!r} on a Real-output card, but "
                f"no such figure is in the sample report it points at — "
                f"regenerate with `make sample` and re-check")


def test_the_scouting_cards_quote_the_report_verbatim() -> None:
    """The number check above catches an invented figure; this catches the way
    it actually went wrong — right numbers, a claim the engine no longer makes.
    The page said "above four of their set starters" for a rival whose bench
    player is now correctly named against the ONE slot he can fill. Whenever
    render/engine wording changes, regenerate the demo and update this quote."""
    quoted = "Start George Kittle over Sam LaPorta"
    def flat(page: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
    assert quoted in flat(SAMPLE_REPORT).replace("  ", " "), \
        "the sample no longer says this — regenerate with `make sample` and re-check"
    assert quoted in flat(LANDING).replace("  ", " "), \
        "the landing page's coin-flip card drifted from the report it cites"
    # And the figures the card attaches to that claim.
    assert "14.1 vs 9.5" in flat(SAMPLE_REPORT) and "14.1 vs 9.5" in flat(LANDING)
    # The lineup card's rows, too — a row quoting a confidence the sample no
    # longer publishes is a number the product did not compute.
    import html as _html
    sample_rows = _html.unescape(flat(SAMPLE_REPORT))
    for name, pct in (("Amon-Ra St. Brown", "80%"), ("Ja'Marr Chase", "73%"),
                      ("George Kittle", "72%")):
        # A row now carries the player's game, season average and last three
        # before the call column (panel review F7, F8, SS-I9), so the window
        # spans a whole row — never into the next player's.
        assert re.search(rf"{re.escape(name)}.{{0,420}}?{pct}", sample_rows), \
            f"the sample no longer publishes {pct} on {name}"
        assert re.search(rf"{re.escape(name)}.{{0,160}}{pct}", _html.unescape(flat(LANDING)))


def test_the_seat_link_is_not_handed_out_before_checkout() -> None:
    """The League Pass seat URL used to render at step 2 of 4. A commissioner
    could paste it in the group chat and then abandon the payment, leaving
    eleven managers each told their seat was claimed — while every claim is
    dropped on Tuesday for want of a pass covering that league, visible only in
    a CI log. It is revealed on the way to Stripe, and the seat holder is told
    what actually happened rather than that they are entitled."""
    # The roster step is where a commissioner would be tempted to reveal it,
    # so that is what must stay clean.
    pick = JOIN.split("function draw(")[1].split("\n$(")[0]
    assert "showSeatLink" not in pick, \
        "the seat link is shown before the commissioner reaches checkout"
    # Comment lines stripped: this function's comment explains where the link
    # IS revealed, and matching that would pass a broken page as fixed.
    code = "\n".join(line for line in pick.splitlines()
                     if not line.lstrip().startswith("//"))
    assert "showSeatLink" not in code, \
        "the seat link is shown before the commissioner reaches checkout"
    # It is revealed immediately before the redirect to the payment link, and
    # nowhere else: exactly one call site, and the next statement navigates.
    calls = [line for line in JOIN.splitlines()
             if "showSeatLink()" in line and "function" not in line]
    assert len(calls) == 1, f"showSeatLink is called {len(calls)} times"
    tail = JOIN.split(calls[0])[1][:300]
    assert "window.location.assign" in tail, \
        "the seat link is no longer tied to the checkout redirect"
    # And no page copy claims an unpaid seat is already entitled.
    assert "Your seat is claimed" not in JOIN


def test_the_league_pass_arithmetic_matches_the_actual_season_price() -> None:
    """`site/league-pass.html` is the ONE page where price is argued rather than
    just disclosed (PLAN §4: a commissioner justifying spend to eleven
    leaguemates is a genuinely deliberative buyer). That licence comes with an
    obligation — the multiple has to be true. It said "twelve individual passes
    would cost $348" for as long as the season pass was $29, and a stale
    comparison on our own page is a false claim about our own prices."""
    match = re.search(r"Twelve Rest-of-Season Passes would cost \$(\d+)", LEAGUE_PASS)
    assert match, "the League Pass page lost its comparison"
    assert int(match.group(1)) == 12 * int(SEASON_PRICE), (
        f"the page compares against ${match.group(1)} but twelve season passes "
        f"at ${SEASON_PRICE} is ${12 * int(SEASON_PRICE)}")
    # The ten-team figure (Oct 9 2026: most leagues are not twelve) carries
    # the same obligation.
    ten = re.search(r"ten would cost \$(\d+)", LEAGUE_PASS)
    assert ten and int(ten.group(1)) == 10 * int(SEASON_PRICE), \
        "the ten-team comparison is missing or no longer matches the season price"


def test_the_league_pass_is_not_commissioner_only() -> None:
    """Requiring the commissioner makes every league sale depend on one specific
    person agreeing (PLAN §4, revised Aug 17 2026). Nothing in the code ever
    checked who was buying — this was copy alone."""
    assert re.search(r"any manager in the league can buy it", LEAGUE_PASS, re.I)
    assert not re.search(r"Why a commissioner buys this", LEAGUE_PASS)


def test_checkout_cannot_open_while_the_sleeper_question_is_unresolved() -> None:
    """The one guard that is about the BUSINESS surviving, not the buyer's
    experience — though it protects them too.

    Sleeper's Terms of Use (§11.1, §11.3, verbatim in PLAN §0) prohibit a
    third-party retrieving league data without express written consent, and
    §11.2's first remedy is terminating the SUBSCRIBER's account. Until that is
    resolved, taking money means selling a product that can get the buyer's
    Sleeper account closed without telling them — which is the exact failure
    this repo's honesty rules exist to prevent.

    So flipping CHECKOUT_OPEN or pasting a payment link is not a config change
    while PLAN §0 still reads `unresolved`; it is a decision, and it has to be
    recorded as one. Set the status line to granted / refused /
    proceeding-with-disclosure — whichever is true — and this test lets you
    ship."""
    plan = (SITE.parent / "PLAN.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*SLEEPER_LICENCE_STATUS: (\w[\w-]*)\*\*", plan)
    assert match, "PLAN §0 lost its Sleeper licence status line"
    status = match.group(1)
    assert status in {"unresolved", "granted", "refused",
                      "proceeding-with-disclosure", "not-required"}, \
        f"unknown status {status!r}"
    if status != "unresolved":
        # A decision was made and written down. `not-required` carries its own
        # obligation instead: see test_no_sleeper_in_the_paid_path.
        return

    assert re.search(r"const CHECKOUT_OPEN = false", LANDING), (
        "checkout was opened while PLAN §0 still records the Sleeper licence "
        "question as unresolved — see PLAN §0 before shipping this")
    for const in ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY", "STRIPE_LINK_PASS"):
        assert re.search(rf'const {const} = ""', JOIN), (
            f"{const} was set while PLAN §0 records the Sleeper licence question "
            f"as unresolved — a live payment link takes money for a product whose "
            f"terms position is undecided")


# The paid path: every module run/batch.py can reach when it builds and mails a
# subscriber's report. Walked statically so a new import cannot quietly widen it.
def _paid_path_modules(root: str = "run.batch") -> set[Path]:
    import ast
    repo = SITE.parent
    seen: set[str] = set()
    queue = [root]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = repo / (name.replace(".", "/") + ".py")
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                queue += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                queue.append(node.module)
    return {repo / (n.replace(".", "/") + ".py") for n in seen
            if (repo / (n.replace(".", "/") + ".py")).is_file()}


def _runners_the_crons_execute() -> set[str]:
    """Every `python -m run.X` a workflow actually RUNS, comments excluded.

    Comments are stripped because a `#` line inside a `run:` block explaining
    why a runner was REMOVED would otherwise be read as evidence that it is
    still there — a test measuring its own documentation.
    """
    import yaml

    roots: set[str] = set()
    workflows = SITE.parent / ".github" / "workflows"
    for path in sorted(workflows.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                for line in str(step.get("run", "")).splitlines():
                    body = line.split("#", 1)[0]
                    roots.update(re.findall(r"-m\s+(run\.[a-z_]+)", body))
    return roots


def test_the_roster_runner_cannot_reach_sleeper_at_all() -> None:
    """``run/tuesday.py`` is the runner PLAN §0's product actually uses, and its
    whole claim is that no league platform is involved. Unlike the staged check
    below — quiet until money can move, so a multi-day migration does not teach
    people to ignore a red suite — this one is unconditional: there is nothing
    to stage, the module was written after the decision.

    Import reachability rather than a grep of this one file, because the way a
    dependency comes back is through something it imports.
    """
    offenders = sorted(
        p.name for p in _paid_path_modules("run.tuesday")
        if re.search(r"api\.sleeper\.app|sleeper\.app/|docs\.sleeper",
                     p.read_text(encoding="utf-8")))
    assert not offenders, (
        f"run/tuesday.py reaches Sleeper through {offenders} — §11.3's remedy "
        f"lands on the SUBSCRIBER's account, not ours")
    # And nothing in its graph imports the Sleeper client under any name.
    modules = {p.stem for p in _paid_path_modules("run.tuesday")}
    assert "sleeper" not in modules and "pull" not in modules, sorted(modules)


def test_no_sleeper_in_the_paid_path() -> None:
    """PLAN §0: the owner chose to remove the Sleeper dependency rather than ask
    Sleeper's permission for it. That choice is only real when the code stops
    reading Sleeper — until then `SLEEPER_LICENCE_STATUS: not-required` is a
    claim about intent, not about the software.

    So this fails the moment money can move while the paid path still reaches
    Sleeper. It is deliberately quiet before then: the migration is staged
    (PLAN §0 actions 2-3) and a red suite through a multi-day migration teaches
    people to ignore red suites.

    The historical backtest may keep its Sleeper code — that is research on a
    public sample league, not a commercial service — so this walks only the
    modules the PAID PATH reaches.

    WHAT "the paid path" MEANS, and why it is derived rather than named
    (Aug 27 2026, found by flipping CHECKOUT_OPEN): this used to walk
    `run/batch.py`, which WAS the paid runner when it was written. batch is now
    the retired league runner — nothing executes it — while the live product
    runs run.tuesday, run.intake, run.solo and run.monday, every one of which
    is clean. So the first real launch turned the suite red over a module no
    customer can reach, which is exactly the cry-wolf failure the staging above
    exists to avoid.

    A hardcoded root goes stale the moment the architecture moves. The paid
    path is therefore READ OUT OF THE CRONS — whatever they actually run is
    what can touch a paying customer — so re-adding a Sleeper-reaching runner
    to a workflow fails this immediately, and retiring one stops being a
    reason to edit a test. Commands only, never comments: a workflow comment
    naming run.batch must not be read as evidence that it runs.
    """
    plan = (SITE.parent / "PLAN.md").read_text(encoding="utf-8")
    checkout_open = not re.search(r"const CHECKOUT_OPEN = false", LANDING)
    links_live = not all(re.search(rf'const {c} = ""', JOIN) for c in
                         ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY",
                          "STRIPE_LINK_PASS"))

    roots = _runners_the_crons_execute()
    assert roots, "no runner found in any workflow — this guard has gone blind"
    reached: set[Path] = set()
    for root in roots:
        reached |= _paid_path_modules(root)
    offenders = sorted(
        p.name for p in reached
        if re.search(r"api\.sleeper\.app|sleeper\.app/|docs\.sleeper",
                     p.read_text(encoding="utf-8")))

    if checkout_open or links_live:
        assert not offenders, (
            f"checkout is live and the paid path still reads Sleeper via "
            f"{offenders} — PLAN §0 records the dependency as removed, and "
            f"§11.2's remedy lands on the SUBSCRIBER's account")
    elif "SLEEPER_LICENCE_STATUS: not-required" in plan:
        # Not a failure — a standing reminder of what is left to do, visible in
        # -v output without turning the suite red mid-migration.
        assert True, offenders


# --------------------------------------------------------------------- #
# self-serve roster updates — the picker's third mode
# --------------------------------------------------------------------- #

def test_update_mode_never_reaches_a_payment_and_posts_the_contract() -> None:
    """The link inside every report opens the picker in update mode. Two
    things must hold in the browser: the payment path is never reached (an
    update is not a purchase), and the row posted carries exactly what
    run/updates.py verifies — kind, the subscription's slug, the token. The
    Python side is pinned in tests/test_intake_sync.py; this pins the JS half
    of the contract."""
    handler = JOIN.split('$("form-email").addEventListener')[1]
    before_link = handler.split("const link = ")[0]
    assert "if (UPDATE_MODE)" in before_link and "submitUpdate(email, ref)" in before_link, \
        "update mode must leave the handler before a payment link is chosen"
    post = JOIN.split("function submitUpdate")[1].split("function showSeatLink")[0]
    assert 'kind: "update"' in post
    assert "replaces: UPDATE_SLUG" in post and "token: UPDATE_TOKEN" in post
    assert "STRIPE_LINK" not in post
    # A malformed pair is an ordinary visit, never an update.
    assert re.search(r'TOKEN_UPDATE = /\^\[0-9a-f\]\{10\}\$/\.test\(UPDATE_SLUG\)', JOIN)
    assert re.search(r'/\^\[0-9a-f\]\{20\}\$/\.test\(UPDATE_TOKEN\)', JOIN)
    # With no backend it says nothing was saved — and promises no reply route,
    # which needs the same backend (JOIN-122).
    closed = post.split("if (!FORM_ENDPOINT) {")[1].split("}")[0]
    assert "Nothing was sent or saved" in closed and "reply to any report" not in closed
    # A subscriber changing their roster is shown no billing terms.
    mode = JOIN.rsplit("if (UPDATE_MODE) {", 1)[1].split("} else if (SEAT_MODE)")[0]
    for hidden in ("terms-line", "renew-note", "pay-note", "first-note"):
        assert f'$("{hidden}").style.display = "none"' in mode, \
            f"update mode leaves {hidden} visible"
    assert "Nothing to pay" in mode


# --------------------------------------------------------------------- #
# the first-week sample — what actually arrives, published beside what sold it
# --------------------------------------------------------------------- #

def test_the_first_week_sample_is_the_real_pipelines_week_one() -> None:
    """A buyer decides on a mid-season file and then receives a WEEK ONE file,
    which by design carries no number anywhere: no week-0 injury report
    exists, so nothing is confirmable and nothing prints. Publishing only the
    mid-season one sells a file nobody's first Tuesday looks like — a Week-2
    refund with a stamp on it. This page is that first file, built through the
    same pipeline, and it may not quietly acquire numbers the product cannot
    produce in week 1."""
    page = FIRST_WEEK_SAMPLE
    assert "Week 1" in page, "the first-week sample is not a week-1 report"
    # No confidence anywhere: every call cell is a withheld one.
    assert not re.search(r"<b>\d\d%</b>", page), \
        "a week-1 sample published a confidence, which no model can earn"
    # It states the basis for the ordering, and the ramp, in the buyer's words.
    # Unescaped: apostrophes render as entities, and "last season&#x27;s" is
    # not a match anybody would write by hand.
    import html as _html
    text = _html.unescape(re.sub(r"<[^>]+>", " ", prose(page)))
    assert "last season's scoring order" in text
    assert "not a forecast for this week" in text
    assert re.search(r"start next week", text), \
        "the first-week file must say when numbers start"
    # Every row that HAS a prior season shows the figure it was ordered on, so
    # the order can be checked rather than taken on trust. Two rows here do
    # not — a kicker and a defense with no prior-season record — and showing
    # nothing is the honest render of nothing, exactly as a live week 1 would
    # do for a rookie.
    assert text.count("last season:") >= 7, "rows do not carry their own basis"


def test_the_two_samples_point_at_each_other() -> None:
    """Each page shows what the other one does not: rebuilding one without the
    other is how the pair drifts into contradicting itself."""
    assert 'href="sample-report.html"' in FIRST_WEEK_SAMPLE
    from render.report import checkout_open
    ask = "join/index.html" if checkout_open() else 'href="index.html#watch-form"'
    assert ask in FIRST_WEEK_SAMPLE, "first-week sample is a dead end"
    assert ask in SAMPLE_REPORT, "the sample is a dead end"
    # The mid-season sample no longer points at the week-1 file (Sep 29 2026):
    # a buyer joining now gets a full file, and the landing FAQ links the
    # week-1 sample for anyone who asks. Before the NEXT pre-season, restore
    # the "first file of a season is thinner" line here (CLAUDE.md, selling
    # strategy).


def test_closed_checkout_shows_no_live_paid_cta_anywhere() -> None:
    """Adversarial review, Aug 24: the hero's paid CTA was correctly gated
    behind CHECKOUT_OPEN while three identical gold "Set up my team" buttons
    (nav, season card, closer) shipped live — the biggest buttons on the page
    led to a closed checkout, beside a monthly card honestly saying "Checkout
    opens at launch". The resting state in static markup must be the CLOSED
    state, because that is what renders if the script never runs; the open
    state is what JS builds the day the constant flips."""
    static = LANDING.split("<script>")[0]
    for anchor in re.findall(r"<a\b[^>]*>", static):
        if "join/index.html" not in anchor or "btn gold" not in anchor:
            continue
        assert "hidden" in anchor, (
            "a live gold CTA points at join/ while checkout is closed — gate "
            f"it behind CHECKOUT_OPEN like hero-open: {anchor}")
    # The open state still routes every paid CTA through the picker.
    rewrites = LANDING.split("if (CHECKOUT_OPEN)")[1]
    for cta in ("nav-cta", "season-cta", "closer-cta"):   # one card in 2026
        assert cta in rewrites, f"the open state forgot to enable {cta}"
    # And the CLOSED-state copy must not survive the flip (review, Aug 24):
    # "setting up today saves nothing yet" under a live $39 button, and a
    # capture promising "one email when signups open" after that email has
    # gone out, are false statements on launch morning.
    for stale in ("watch-form", "finance-note", "heroline"):
        assert stale in rewrites, (
            f"the open state leaves closed-state copy live: {stale} — the "
            f"flip must retire the capture and rewrite the finance line")


def test_join_errors_are_visible_and_backend_rejections_are_not_success() -> None:
    """Two review reproductions, Aug 24. (1) `.err` was display:none and
    showError only set textContent, so EVERY error on the page — including
    "checkout isn't open" after full setup — was invisible; visibility now
    follows content (`:empty`). (2) fetch resolves on HTTP 400 too, so a row
    the Worker rejected was answered with "Your seat request is in" — every
    POST must check response.ok before claiming success."""
    assert ".err:empty{display:none;}" in JOIN
    err_rule = JOIN.split(".err{")[1].split("}")[0]
    assert "display:none" not in err_rule, \
        "a fixed display:none on .err makes every error invisible again"
    assert JOIN.count("if (!response.ok) throw") >= 3, \
        "all three POSTs (waitlist, seat, update) must treat a rejected row " \
        "as failure, not success"
    # And a successful seat claim actually shows its confirmation block.
    seat = JOIN.split("function submitSeat")[1].split("function submitUpdate")[0]
    assert '$("done").style.display = "block"' in seat


def test_a_roster_edited_after_the_check_forces_a_recheck() -> None:
    """Review reproduction, Aug 24: with no input listener on the paste box, a
    player typed AFTER "Check my roster" was silently dropped at checkout —
    the ref encoded the stale checked list, which is RULE R3's failure
    (nothing is dropped) wearing a different hat."""
    assert '$("roster-text").addEventListener("input"' in JOIN
    listener = JOIN.split('$("roster-text").addEventListener("input"')[1] \
                   .split("});")[0]
    assert "state.ready = false" in listener
    assert "hit" in listener and "again" in listener, \
        "the stale state must tell the buyer to re-check, not just block"


def test_each_purchase_mode_prices_its_own_header() -> None:
    """Review, Aug 24 (verified live): the League Pass page showed a "$39 USD
    for the season" pitch and a "$39 / season" chip above a "Buy the League
    Pass — $99" button. Every price a mode shows must be the price that mode
    charges."""
    pass_branch = JOIN.split("else if (WANTS_PASS)")[1]
    assert "header-pitch" in pass_branch and "$69" in pass_branch
    # The header chips are gone (truth pass): the price lives in the pitch,
    # beside its terms, so no stale chip can name another mode's price.
    assert "setChips" not in JOIN and 'id="header-chips"' not in JOIN
    assert "$69 for your whole league, rest of season — one payment" in prose(pass_branch)
    # Monthly is a function since Oct 9 2026, because the buyer can now switch
    # to it on the page as well as arrive with ?plan=monthly.
    monthly_branch = JOIN.split("else if (WANTS_MONTHLY)")[1] \
                         .split("else if (WANTS_PASS)")[0]
    assert "monthlyPlan()" in monthly_branch
    monthly = JOIN.split("function monthlyPlan()")[1].split("\nfunction ")[0]
    assert "header-pitch" in monthly and "14.99" in monthly
    assert '$("terms-line").textContent = monthlyTerms' in monthly
    season = JOIN.split("function seasonPlan()")[1].split("\n}")[0]
    assert "SEASON_STATE" in season and "SEASON_SUBMIT" in season, \
        "switching back to the season pass must restore its own terms and price"


def test_the_buyer_can_switch_plans_without_losing_their_roster() -> None:
    """Personas, Oct 9 2026: a mid-season buyer from the hero CTA saw only the
    $39 season pass, and would buy monthly or not at all. The switch rewrites
    the page in place (a reload would drop the pasted roster), is never shown
    to a seat holder, an update, a free report or a League Pass buyer, and the
    submit handler charges the plan on screen, never the one in the URL."""
    switch = JOIN.split("// Season ⇄ monthly, on the page.")[1].split("</script>")[0]
    assert "!SEAT_MODE && !UPDATE_MODE && !TRY_MODE && !WANTS_PASS" in switch
    assert "location" not in switch, "switching plans must not reload the page"
    handler = JOIN.split('$("form-email").addEventListener')[1].split("\n});")[0]
    assert "monthlyChosen ? monthlyLink() : seasonLink()" in handler
    assert "WANTS_MONTHLY" not in handler, "the handler reads the URL, not the choice"
    # Both prices on the switch are the prices the plans charge.
    assert f"Rest-of-Season Pass · ${SEASON_PRICE}" in JOIN
    assert f"Monthly · ${MONTHLY_PRICE}" in JOIN


def test_seat_mode_carries_no_billing_promises_and_warns_up_front() -> None:
    """A seat holder paid nothing: the refund/cancel-from-your-account sentence
    is about money they never spent, and learning "seats aren't open" only
    after pasting fifteen names is the disappointment the closed-note exists
    to prevent."""
    seat_branch = JOIN.split("else if (SEAT_MODE)")[1] \
                      .split("else if (WANTS_MONTHLY)")[0]
    assert '$("first-note").style.display = "none"' in seat_branch
    assert "Seats aren't open" in seat_branch and "closed-note" in seat_branch


def test_the_picker_offers_type_to_add_beside_the_paste_box() -> None:
    """People fix a roster one player at a time, and a typeahead beats
    retyping into a paste box (owner direction, Aug 24: reduce the pain of
    the typing flow). The suggestions come from the same published directory
    the resolver uses — so anything added this way resolves by construction —
    and every rendered string is a TEXT node, because a player name from a
    downloaded file is still not markup."""
    assert 'id="player-search"' in JOIN
    typeahead = JOIN.split("function suggestions")[1].split('$("resolve")')[0]
    assert "state.directory" in typeahead, \
        "suggestions must come from the resolver's own directory"
    assert "textContent" in typeahead and ".innerHTML" not in typeahead
    # Adding re-checks the roster so the tally follows without extra taps.
    assert "R.resolveAll(state.directory, box.value)" in typeahead
    # Enter picks the first suggestion rather than submitting the form.
    assert "event.preventDefault()" in typeahead
    # The input lives inside the roster form like every other picker input.
    form = JOIN.split('<form id="form-roster"')[1].split("</form>")[0]
    assert 'id="player-search"' in form


def test_the_site_always_offers_one_action_a_visitor_can_finish() -> None:
    """Flipping CHECKOUT_OPEN sold the product AND retired the email capture,
    while the payment links were still empty. Net effect on the live site:
    a visitor could not pay (the picker says checkout isn't open) and could not
    leave an address either — a sealed cul-de-sac, during the peak draft
    fortnight, found by three independent reviews the same morning.

    The rule this encodes: the capture retires when a purchase can actually
    COMPLETE, never merely when the flag says "sell". A dead end that also
    throws away the lead is strictly worse than the honest waiting list it
    replaced."""
    can_complete = re.search(r"const CHECKOUT_CAN_COMPLETE = (true|false);", LANDING)
    assert can_complete, "the landing lost its can-complete flag"
    links_live = not all(re.search(rf'const {c} = ""', JOIN) for c in
                         ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY",
                          "STRIPE_LINK_PASS"))
    # The flag must not claim more than the picker can deliver.
    if can_complete.group(1) == "true":
        assert links_live, \
            "CHECKOUT_CAN_COMPLETE is true but the picker has no payment links"
    # And while it is false, hiding the capture must be gated on it.
    rewrites = LANDING.split("if (CHECKOUT_OPEN)")[1]
    hide = rewrites.split('"watch-form"')[0]
    assert "CHECKOUT_CAN_COMPLETE" in hide, \
        "the email capture is retired without checking a purchase can finish"


def test_the_proof_cards_survive_a_narrow_screen() -> None:
    """Measured in a real browser across a width sweep (Aug 27 2026), because
    CSS bugs of this shape are invisible to every other kind of test:

    - At 375px the hero card's five fixed columns (258px of them) left 39px for
      a name needing 130 — every player truncated to about three characters, on
      the one card whose whole job is to be believed.
    - At 881px, ONE PIXEL above the old 880 breakpoint, all four truncated
      again: the hero returns to two columns there, so the card's own column is
      narrower than it was on a phone. The bug lived at the boundary, which is
      why the fix keys on 1000px — where the card actually has room — rather
      than on the layout breakpoint.
    - The usage row's .ucount carried `white-space:nowrap` in a 120px column.
      A grid item defaults to min-width:auto, so that column blew out to the
      ~230px the text needs and scrolled the WHOLE PAGE sideways on a phone.

    The last one matters most for a link opened from X on a mobile: a page that
    scrolls sideways reads as broken before a word of it is read.
    """
    # Since the Sep 29 2026 redesign the hero card sits inside a phone frame
    # capped at 320px, so it is narrow at EVERY viewport and the squeeze comes
    # only at phone widths, where the frame itself shrinks. There the columns
    # tighten and a name wraps rather than truncating. Measured at 360-430px.
    assert re.search(r"\.phone\{[^}]*max-width:320px", LANDING), \
        "the phone frame lost its cap — re-measure the hero card's columns"
    # Oct 25 2026 (contract C8): every size inside the phone's email is in
    # cqw, so the columns tighten with the phone at EVERY width (measured at
    # 266 and 300px screens: all nine names on one line) instead of at one
    # breakpoint, and the name column is the one that may shrink.
    grid = re.search(r"\.screen \.ghead,\.screen \.frow\{[^}]*grid-template-columns:([^;]+);",
                     LANDING)
    assert grid and "cqw" in grid.group(1) and "minmax(0,1fr)" in grid.group(1), \
        "the hero card's columns no longer scale with the phone"
    # Launch review D5, measured in Chrome: the wrap rule lived only in that
    # 430px block, so from 431px to 880px — where the phone is 286px wide —
    # "Amon-Ra St. Brown" truncated to "Amon-Ra St. …" (scrollWidth 117 >
    # clientWidth 94). The phone's name column is narrow at EVERY viewport, so
    # the rule is a base rule now, outside every media query.
    style = LANDING.split("<style>")[1].split("</style>")[0]
    base = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", style)
    assert re.search(r"\.screen \.fname\{white-space:normal;overflow:visible", base), \
        "names truncate again inside the phone at some width — the one card " \
        "whose job is to be believed"
    assert "text-overflow:ellipsis" not in re.search(r"\.screen \.fname\{([^}]*)\}", base).group(1)

    # The usage widget (.urow/.ucount, whose nowrap pushed the page sideways)
    # went with "Who's getting the ball"; its counts now live in the
    # generated Slot by Slot card, whose lines wrap.
    assert ".ucount" not in LANDING and ".urow" not in LANDING


def test_the_policy_discloses_the_address_stripe_now_collects() -> None:
    """Owner decision, Aug 27 2026: switch on Stripe's "collect customer
    addresses". The reason is tax — nexus thresholds are counted per country
    AND per state, so knowing where sales come from is what makes it possible
    to register in the right places.

    Collecting it made THREE statements on this page false at once, which is
    why the policy had to be rewritten before the toggle was flipped and not
    after: the exhaustive "whole list" note, the header lede's "and nothing
    else", and section 2's "no postal address". A privacy policy that lags the
    collection by even a day is the kind of small untruth that discredits every
    other claim on the page — and this one is linked from Stripe's own
    checkout, so a buyer may read it in the same minute they hand the address
    over.
    """
    whole = (SITE / "privacy.html").read_text(encoding="utf-8")
    page = html.unescape(prose(whole[whole.find("<body>"):]))
    lede = html.unescape(prose(whole))

    assert re.search(r"billing address", page, re.I), \
        "the address is collected and the policy does not say so"
    # Oct 23 2026 (critique #7): LAUNCH sets the address toggle Off, so what
    # checkout always takes is the card's country and, where the card needs
    # one, its postal code, and a full address only when the toggle is on —
    # the note says both, true either way.
    assert re.search(r"your card's country and, where the card needs one, its postal code, "
                     r"which Stripe takes with the card at checkout",
                     page, re.I), "the exhaustive 'whole list' note omits the postal code"
    assert re.search(r"full\s+billing address only if", page, re.I), (
        "the exhaustive 'whole list' note omits the address checkout may ask for")
    assert not re.search(r"no postal address", page, re.I), (
        "section 2 still claims we never ask for a postal address")
    assert not re.search(r"scoring settings, and nothing else", lede, re.I), (
        "the lede still says the old three-item list is everything")
    # Why we take it, in the buyer's terms — a purpose, not just a disclosure.
    assert re.search(r"tax", page, re.I), "no stated purpose for the address"
    assert re.search(r"not.{0,40}(target|advertis)", page, re.I), (
        "the policy does not rule out the use a reader will assume")
    # And the limit that keeps it out of everything we publish.
    assert re.search(r"not.{0,60}copied into", page, re.I), (
        "the policy no longer says the address stays out of the report system")


def test_the_address_never_enters_the_system_that_builds_reports() -> None:
    """Collecting it in Stripe and pulling it into our pipeline are different
    decisions, and only the first was made.

    The address is for reading in Stripe's dashboard to see where sales come
    from. Nothing about a report needs it — the file is computed from a roster
    and public NFL data — so keeping it out of run/ means it cannot leak
    through a rendered report, the public record of graded calls, a CI log or
    an Actions artifact. The policy promises exactly this ("not copied into the
    system that builds and sends your reports"), so the promise and the code
    are pinned together.
    """
    source = (SITE.parent / "run" / "subscriptions.py").read_text(encoding="utf-8")
    reads = set(re.findall(r'customer\.get\("([a-z_]+)"', source))
    assert reads <= {"deleted", "email", "id", "metadata"}, (
        f"run/subscriptions.py now reads {sorted(reads)} off a Stripe customer "
        f"— the policy says the address stays out of the report system")
    for module in ("subscriptions.py", "intake.py", "rosters.py", "tuesday.py"):
        text = (SITE.parent / "run" / module).read_text(encoding="utf-8")
        for field in ("address", "shipping", "phone", "tax_ids"):
            assert f'customer.get("{field}")' not in text, (
                f"run/{module} reads customer.{field} into our own records")


def test_the_closed_note_is_decided_per_plan_not_all_or_nothing() -> None:
    """Payment links arrive ONE AT A TIME as each is created in Stripe, so the
    half-configured state is not an edge case — it is every state between the
    first link and the last.

    The guard used to be `!SEASON && !MONTHLY && !PASS`, correct only while all
    three were empty together. Reproduced in a browser the moment the League
    Pass link landed: /join/ showed a season buyer "Continue to checkout — $39"
    with no warning, and they would have pasted fifteen player names before
    learning at submit that nothing was saved — precisely the disappointment
    this note exists to move earlier.
    """
    # The pass resolves through PASS_LINK, which is empty until seats can be
    # claimed (test_the_league_pass_is_never_sold_before_its_seats_can_be_claimed).
    assert "const PLAN_LINK = WANTS_PASS ? PASS_LINK" in JOIN, (
        "the closed note no longer resolves the link for the visitor's own plan")
    assert "if (!PLAN_LINK) {" in JOIN
    assert not re.search(r"!STRIPE_LINK_SEASON\s*&&\s*!STRIPE_LINK_MONTHLY", JOIN), (
        "the all-or-nothing guard is back: one configured tier switches the "
        "warning off for the tiers that still cannot take money")
    # The plan must be known before the note is decided, or PLAN_LINK reads
    # undefined constants and the note never shows for anyone.
    assert JOIN.index("const WANTS_PASS") < JOIN.index("const PLAN_LINK")


def test_a_configured_tier_can_take_money_while_the_others_cannot() -> None:
    """The other half of the same property: a live link must actually work.
    Only the tiers still missing a link say checkout is closed."""
    live = re.findall(r'const (STRIPE_LINK_\w+) = "(https://buy\.stripe\.com/[^"]+)"', JOIN)
    empty = re.findall(r'const (STRIPE_LINK_\w+) = ""', JOIN)
    # Season, monthly, League Pass and (Oct 18 2026) the $19 Playoff Pass.
    assert len(live) + len(empty) == 4, "a payment-link constant went missing"
    for _name, url in live:
        assert "?" not in url, (
            f"{url} carries a query string; the picker appends "
            f"client_reference_id and would produce a malformed URL")


def test_the_cancel_section_links_the_portal_rather_than_describing_it() -> None:
    """"Cancelling has concrete steps" is only half the promise; the steps have
    to be followable from the page making them. §4 used to describe the URL
    shape ("it looks like billing.stripe.com/p/login/…") because the portal did
    not exist yet — a nervous buyer reading the contract before paying had
    nothing to click.

    The report footer and welcome email carry the same destination from the
    BILLING_PORTAL_URL secret; this pins the one copy a human pasted, since a
    hand-pasted link is the copy that goes stale.
    """
    terms = (SITE / "terms.html").read_text(encoding="utf-8")
    cancel = terms[terms.find('id="cancel"'):terms.find("<h2>5.")]
    assert re.search(r'href="https://billing\.stripe\.com/p/login/[A-Za-z0-9]+"', cancel), (
        "the cancellation section does not link the billing portal")
    assert "LAUNCH:" not in cancel, "the launch placeholder comment is still there"
    assert not re.search(r"looks\s+like billing\.stripe\.com", cancel), (
        "still describing the URL shape instead of linking it")


def test_the_pay_button_disclosure_quotes_the_price_the_page_charges() -> None:
    """The text above Stripe's Pay button is the last renewal disclosure a
    buyer meets, and it is on the one page we do not control — API-only, with
    no Dashboard field. It was three curl commands in a doc with the prices
    typed into them, which is a fourth copy of every price and the copy nobody
    would think to update.

    infra/stripe_paylink_text.py builds them from render/welcome.py's
    constants, which another test already ties to the pricing page. So the
    sentence above Stripe's Pay button cannot disagree with the one beside the
    Buy button.
    """
    import sys
    sys.path.insert(0, str(SITE.parent))
    from infra.stripe_paylink_text import MESSAGES
    from render.welcome import MONTHLY_PRICE, PASS_PRICE, SEASON_PRICE

    assert set(MESSAGES) == {"season", "monthly", "league_pass"}
    # 2026's one-time passes (Oct 18 2026): the season and League Pass words
    # carry no price (the $19 Playoff Pass link shares the season text, and
    # Stripe prints the amount beside it) and say what is true of all of them.
    assert MONTHLY_PRICE in MESSAGES["monthly"]
    assert "Nothing renews" in MESSAGES["season"] and "monthly" not in MESSAGES["season"]
    assert "Nothing renews" in MESSAGES["league_pass"]
    assert not any("each season" in m for m in MESSAGES.values())
    from infra.stripe_paylink_text import TOS_MESSAGES, fields
    for plan in MESSAGES:
        assert "18 or older" in TOS_MESSAGES[plan] and "[Terms](" in TOS_MESSAGES[plan]
        assert fields(plan)["consent_collection[terms_of_service]"] == "required"
    assert "does not renew" in TOS_MESSAGES["season"]
    assert "does not renew" in TOS_MESSAGES["league_pass"]
    from render.welcome import TERMS_VERSION
    import datetime as _dt
    terms = (SITE / "terms.html").read_text(encoding="utf-8")
    stamp = _dt.date.fromisoformat(TERMS_VERSION)
    assert f"Last updated {stamp.day} {stamp:%B %Y}" in terms, \
        "terms.html's Last updated date must equal TERMS_VERSION, the version consent is recorded against"
    assert "after the season's last weekly report" in MESSAGES["monthly"], (
        "the monthly disclosure omits the season-end stop, which is the one "
        "promise a monthly buyer most needs at the moment of paying")
    for plan, text in MESSAGES.items():
        assert "cancel" in text.lower(), f"{plan} disclosure never mentions cancelling"


def test_the_paylink_script_never_takes_the_key_as_an_argument() -> None:
    """An argument is visible in the shell history and in `ps` while it runs.
    getpass is the only intake."""
    source = (SITE.parent / "infra" / "stripe_paylink_text.py").read_text(encoding="utf-8")
    assert "getpass.getpass(" in source
    assert "argparse" not in source, "a key passed as a flag lands in shell history"
    assert "Never echo the request" in source, "the error path may leak the key"


def test_no_doc_tells_the_owner_to_run_this_repo_on_system_python() -> None:
    """`python3` on this machine is 3.9 and has no `requests`, and every module
    here reaches it through ingest/nflverse.py. Every Makefile target uses
    `$(PY)` = .venv/bin/python for exactly that reason; a doc that says
    `python3` instead hands the owner a ModuleNotFoundError at the one moment
    they are following instructions literally. Reproduced, then pinned.
    """
    import re
    for name in ("LAUNCH.md", "README.md"):
        doc = SITE.parent / name
        if not doc.is_file():
            continue
        for line in doc.read_text(encoding="utf-8").splitlines():
            # The lookbehind must exclude "/" as well as ".", or
            # `.venv/bin/python` matches its own fix — which it did, on the
            # first run of this guard.
            assert not re.search(r"(?<![/.\w])python3?\s+-m\s+(run|render|engine|ingest)\b",
                                 line), (
                f"{name} tells the owner to run a repo module on system python: "
                f"{line.strip()!r} — use .venv/bin/python")
            assert not re.search(r"(?<![/.\w])python3?\s+\S*\.py\b", line), (
                f"{name} runs a repo script on system python: {line.strip()!r}")


def test_a_mistyped_password_never_reaches_stripe() -> None:
    """A hidden terminal prompt reads as a system password prompt.

    The owner typed his Mac password into it, and the script sent that straight
    to Stripe as an auth attempt — where it landed in a failed-auth log and
    came back partially echoed in the error. The prompt wording was the cause;
    the transmission was the harm, and only the second one is fixable in code.

    So the key's SHAPE is checked before any network call: anything that is not
    a Stripe key is refused locally, and a secret typed by mistake never leaves
    the machine.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_paylink", SITE.parent / "infra" / "stripe_paylink_text.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for good in ("rk_live_" + "A1b2C3d4E5" * 3, "sk_test_" + "z9Y8x7W6v5" * 3):
        assert module.KEY_SHAPE.match(good), f"a real key was refused: {good[:12]}…"
    for bad in ("hunter2", "Password123", "my mac password",
                "rk_live_short", "", "rk_" + "x" * 40,
                "correct horse battery staple"):
        assert not module.KEY_SHAPE.match(bad), (
            f"{bad!r} would be sent to Stripe as an auth attempt")

    source = (SITE.parent / "infra" / "stripe_paylink_text.py").read_text(encoding="utf-8")
    # The refusal must come BEFORE the first request, or the guard is decoration.
    assert source.index("KEY_SHAPE.match(key)") < source.index("for link, plan in links:"), (
        "the shape check runs after the first Stripe call")
    assert "NOT your Mac password" in source, (
        "the prompt no longer says what it is not, which is what caused this")


FUNNEL_PAGES = ("index.html", "join/index.html", "league-pass.html", "thanks.html")


@pytest.mark.parametrize("name", FUNNEL_PAGES)
def test_no_funnel_page_carries_a_launch_date_that_outlives_itself(name: str) -> None:
    """On Sep 29 2026 the live landing told every visitor "First files land
    Tuesday, Sep 8" — three times — beside "Checkout opens at launch", and the
    join page put "First report Tue Sep 8" beside every Buy button. To a cold
    reader arriving from X that does not read as pre-launch; it reads as
    abandoned.

    The fix is not a newer date, which goes stale the same way. It is copy that
    is true in August, in October and next August: "the day you sign up", "every
    Tuesday". A launch date belongs in an announcement, never in a page that
    outlives it — and "before Week 1" is the same mistake as a phrase.
    """
    # What a buyer can SEE: markup and JS string literals, not comments. The
    # first run of this guard failed on a JS comment explaining why the old
    # date was removed — prose SAYING not to hardcode a date, read as a date.
    # `(^|\s)//` rather than `//`, so https:// URLs survive the strip.
    text = (SITE / name).read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->|/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"(^|\s)//[^\n]*", r"\1", text, flags=re.M)
    for stale in (r"\bSept?\.? ?\d{1,2}\b(?!,? 20\d\d)", r"before Week 1",
                  r"\bWeek 1 through\b", r"opens before Week"):
        hit = re.search(stale, text)
        assert not hit, (
            f"{name} carries {hit.group(0)!r} — a date or season phase that will "
            f"be false for most of the year")


def test_every_page_points_at_icon_files_that_exist() -> None:
    """The logo redraw (Sep 29 2026) moved the favicon from a data URI to real
    files, because the .ico, the Apple icon and the manifest are what browsers,
    phones and Google's crawler actually fetch. A page linking a file that is
    not there shows a blank tab icon and a grey square in search results."""
    from render.report import FAVICON_LINK
    for href in re.findall(r'href="/([^"]+)"', FAVICON_LINK):
        assert (SITE / href).is_file(), f"/{href} is linked but not published"
    pages = [p for p in SITE.rglob("*.html") if p.name != "legal.html"]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert 'href="/favicon.svg"' in text, f"{page.relative_to(SITE)} has no favicon"
        assert 'href="data:image/svg+xml' not in text, \
            f"{page.relative_to(SITE)} still embeds the old favicon"
    # Google reads the brand logo from the landing page's structured data.
    logo = re.search(r'"logo": "https://beatyourleague\.com/([^"]+)"', LANDING)
    assert logo and (SITE / logo.group(1)).is_file()


def test_the_join_page_loads_the_roster_parser_it_was_tested_with() -> None:
    """GitHub Pages lets browsers cache a script for up to ten minutes, so a
    returning visitor ran the OLD roster.js after the LAR / "Bench" parser fix
    shipped (found Sep 29 2026) — the very failures the fix removed. The src
    carries the file's own digest, so any change to the parser changes the
    URL. If this fails, set the ?v= in site/join/index.html to the value below."""
    import hashlib
    digest = hashlib.sha256((SITE / "join" / "roster.js").read_bytes()).hexdigest()[:10]
    assert f'<script src="roster.js?v={digest}"></script>' in JOIN, \
        f"roster.js changed; its script tag needs ?v={digest}"


def test_the_live_sample_says_what_it_is_and_the_cron_keeps_it_fresh() -> None:
    """site/this-week.html is this week's report for the sample roster, so the
    site shows the product running now rather than only a 2024 replay. It must
    say what it is, carry no internal slot code, and be rebuilt and committed
    by the weekly cron. Its odds are published, so they are recorded on the
    public record before kickoff like any other published probability (G04,
    principle 2) — it is a sample, never a subscriber."""
    page = (SITE / "this-week.html").read_text(encoding="utf-8")
    assert "THIS WEEK'S REPORT" in page and "sample roster" in page
    assert "SUPER_FLEX" not in page and "Reply to this email" not in page
    weekly = (SITE.parent / ".github" / "workflows" / "weekly.yml").read_text()
    assert "python -m render.live_sample" in weekly
    assert "site/this-week.html" in weekly.split("Persist the record")[1]
    assert 'href="this-week.html"' in LANDING


def test_the_how_it_works_page_answers_who_what_and_how_to_check() -> None:
    """A skeptical buyer's first questions — who is this, what does the number
    mean, where does it come from, can I check it, what won't it do — each get a
    plain answer, with no personal detail and no claim about results. It is
    reachable from the landing nav and footer, carries the home button and the
    contact address only, and is indexed (unlike the grading pages)."""
    page = prose(markup_only(HOW))
    for needed in ("Who's behind it", "Where the numbers come from", "How to check us",
                   "What it doesn't do", "chance your starter outscores",
                   "not a certainty", "nflverse", "independent and small"):
        assert needed in page, f"the how-it-works page lost {needed!r}"
    assert 'name="robots"' not in HOW, "the page that builds trust must be indexable"
    assert 'href="how-it-works.html"' in LANDING
    assert LANDING.count('href="how-it-works.html"') >= 2, "nav and footer both link it"
    for claim in (r"\bwin \d", r"more (?:often|games) than", r"beat(s)? (?:the )?(?:market|vegas|experts)"):
        assert not re.search(claim, page, re.I), f"how-it-works makes a results claim: {claim}"


def test_the_season_clock_is_derived_committed_and_quiet_when_stale(tmp_path) -> None:
    """The hero's "Week N's report lands Tuesday" line (Oct 9 2026) is honest
    urgency only while it is true. It is read from site/week.json, which the
    Tuesday build writes beside this-week.html from the report it just built
    and the NFL schedule (never typed), the weekly cron commits it, and the
    page shows it only in the eight days before the next report actually
    lands. The verification pass found the first version (a 9-day file-age
    check) claimed "Week 2's report lands Tuesday" from May to September once
    the cron built a preseason Week 1, and ran two days past a missed build."""
    import json as _json
    from render.live_sample import next_report_day, write_week_json
    from run.solo import CACHE_DIR
    out = tmp_path / "week.json"
    write_week_json({"meta": {"season": "2026", "week": 6, "last_week": 18,
                              "generated_at": "2026-10-13T12:05:00+00:00"}}, out,
                    "2026-10-20")
    assert _json.loads(out.read_text()) == {
        "season": "2026", "week": 6, "last_week": 18, "lands_on": "2026-10-20",
        "built_at": "2026-10-13T12:05:00+00:00", "odds": 0, "closest_call": False,
        "first_kickoff": None, "phase": "season"}
    # The join page's "today" needs the week's first kickoff (panel review
    # PC-02): the build writes it when the schedule has it.
    write_week_json({"meta": {"season": "2026", "week": 6, "last_week": 18}}, out,
                    "2026-10-20", "2026-10-16T00:15:00Z")
    assert _json.loads(out.read_text())["first_kickoff"] == "2026-10-16T00:15:00Z"
    try:
        day = next_report_day(CACHE_DIR, "2026", 5)
    except Exception:                                   # pragma: no cover
        day = None
    if day is not None:
        # Week 5 of 2026 ends with Monday night (Oct 12): Week 6 lands Tue Oct 13.
        assert day == "2026-10-13"
    workflow = (SITE.parent / ".github" / "workflows" / "weekly.yml").read_text()
    assert "site/week.json" in workflow, "the cron builds the clock but never commits it"
    assert (SITE / "week.json").is_file(), \
        "week.json must be committed: the persist step's git add names it explicitly"
    script = LANDING.split("// The season clock.")[1].split("})();")[0]
    assert 'fetch("week.json"' in script
    assert "8 * 864e5" in script and "lands_on" in script, \
        "the line must be tied to the day the report lands"
    assert "if (left < 1" in script
    assert "AbortSignal.timeout ?" in script or "AbortSignal && AbortSignal.timeout" in script, \
        "an unguarded AbortSignal.timeout throws on iOS 15 and kills the rest of the script"
    assert "try {" in script
    assert "textContent" in script and "innerHTML" not in script
    # The static sentence is what shows when the file can't be used, and the
    # open state keeps a target for the clock.
    assert 'id="season-clock">A new report every Tuesday of the season.' in LANDING
    assert 'lead.id = "season-clock"' in LANDING


def test_no_page_calls_abort_signal_timeout_unguarded() -> None:
    """AbortSignal.timeout arrived in Safari 16. Called bare where it is
    missing (iOS 15 iPhones) it throws a TypeError, and at page load that
    aborts the rest of the inline script: the join page's player-list load did
    exactly that before any roster could be checked, and the landing's season
    clock would have taken the phone sticky bar down with it (verification
    pass, Oct 9 2026). Every call is feature-detected."""
    for path in SITE.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"AbortSignal\.timeout\(", text):
            before = text[max(0, match.start() - 60):match.start()]
            assert "AbortSignal.timeout ?" in before, (
                f"{path.relative_to(SITE)} calls AbortSignal.timeout without "
                f"checking it exists: {text[match.start() - 60:match.end() + 10]!r}")


def test_the_plan_on_screen_is_the_plan_charged_after_back() -> None:
    """Verification pass, Oct 9 2026 (reproduced with bfcache off): a browser
    restoring form state on Back re-checked Monthly AFTER the script drew the
    season price, so a Monthly pill sat beside a $39 button and tapping it
    changed nothing. The radios opt out of restoration and the page re-draws
    from whatever is checked on every pageshow; a stale "isn't open" error is
    cleared on every switch."""
    plan_inputs = re.findall(r'<input type="radio" name="plan"[^>]*>', JOIN)
    assert len(plan_inputs) == 2
    assert all('autocomplete="off"' in tag for tag in plan_inputs)
    switch = JOIN.split("// Season ⇄ monthly, on the page.")[1].split("</script>")[0]
    assert 'window.addEventListener("pageshow", applyPlan)' in switch
    assert 'monthlyChosen = radio("plan") === "monthly"' in switch
    assert 'showError("err-email", "")' in switch



def test_the_faq_says_the_same_thing_to_people_and_to_search_engines() -> None:
    """The FAQ is answered twice: in the page and in its JSON-LD. Only the
    questions were checked, so an answer could be fixed on the page and stay
    false in the markup crawlers quote (launch audit, Oct 2026). Every answer
    in the markup must be the page's answer, word for word (links dropped)."""
    import html as _html
    import json as _json
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', LANDING, re.S)
    faq = next(n for n in _json.loads(block.group(1))["@graph"] if n["@type"] == "FAQPage")
    visible = {}
    for q, a in re.findall(r"<summary>(.*?)</summary>\s*<div class=\"a\">(.*?)</div>",
                           LANDING, re.S):
        a = re.sub(r"\s*\(<a href=\"sample-first-week.html\">.*?</a>\)", "", a, flags=re.S)
        visible[_html.unescape(q)] = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", a))).strip()
    assert len(faq["mainEntity"]) == len(visible)
    for item in faq["mainEntity"]:
        assert visible.get(item["name"]) == item["acceptedAnswer"]["text"], item["name"]


def test_the_landing_names_the_league_apps_in_the_hero() -> None:
    """Launch audit: "does it work with my app?" is a target buyer's first
    question, and the platforms were named only in a collapsed FAQ, eight phone
    screens down. They are in the hero's first line of credentials now."""
    hero = LANDING.split('<header class="hero">')[1].split("</header>")[0]
    creds = re.search(r'<ul class="creds".*?</ul>', hero, re.S).group(0)
    for app in ("ESPN", "Yahoo", "Sleeper", "CBS"):
        assert app in creds, f"the hero no longer names {app}"


# --------------------------------------------------------------------- #
# launch audit, Oct 15 2026 — the funnel's own findings (F1–F9, C6, C10–C12)
# --------------------------------------------------------------------- #

THANKS = (SITE / "thanks.html").read_text(encoding="utf-8")


def _node(script: str) -> object:
    """Run a snippet under node and return the JSON it prints. Skipped without
    node, like tests/test_intake.py; CI has it."""
    import json as _json
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node not available")
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, f"node failed:\n{done.stderr}"
    return _json.loads(done.stdout)


def _js_function(page: str, name: str) -> str:
    """One top-level function's source, declaration to closing brace."""
    start = page.index(f"function {name}(")
    return page[start:page.index("\n}\n", start) + 2]


def _js_code(page: str) -> str:
    """Inline script code with whole-line comments removed — a comment that
    names the trap it explains must not pass for the code that avoids it."""
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    return "\n".join(line for line in "\n".join(scripts).splitlines()
                     if not line.lstrip().startswith("//"))


def test_the_league_pass_is_never_sold_before_its_seats_can_be_claimed() -> None:
    """Launch audit F1, reproduced in headless Chrome at 390px: with all three
    payment links set and FORM_ENDPOINT empty — LAUNCH.md restores the links in
    step 3 and the seat Worker in step 5 — league-pass.html showed "Checkout
    opens soon", but join/index.html?plan=pass showed no closed note and a live
    "Buy the League Pass — $99" button, and submitting navigated to
    buy.stripe.com with a p3- ref. Every manager the commissioner then sent to
    join/?pass=1 read "Seats aren't open just yet". The pass is gated on the
    endpoint its seats need, on the join page too, through ONE constant."""
    code = _js_code(JOIN)
    uses = [line.strip() for line in code.splitlines() if "STRIPE_LINK_PASS" in line]
    assert len(uses) == 2 and uses[0].startswith("const STRIPE_LINK_PASS = ") and \
        uses[1] == 'const PASS_LINK = FORM_ENDPOINT ? STRIPE_LINK_PASS : "";', (
            "the pass link is read somewhere other than PASS_LINK, the only place "
            f"the seat gate lives: {uses}")
    # Every place a plan's link is resolved — the up-front note, the submit,
    # the first paint, and whether a delivery date may be named (canStartToday)
    # — resolves the pass through the gate.
    assert code.count("WANTS_PASS ? PASS_LINK") == 4
    # The gate itself, run: an empty endpoint sells no pass, whatever the link.
    line = re.search(r"const PASS_LINK = [^;]*;", JOIN).group(0)
    got = _node(
        "const out = [];\n"
        "for (const [FORM_ENDPOINT, STRIPE_LINK_PASS] of [['', 'https://buy.stripe.com/x'],"
        " ['https://forms.example', 'https://buy.stripe.com/x'],"
        " ['https://forms.example', '']]) {\n"
        f"  {line}\n  out.push(PASS_LINK);\n}}\nconsole.log(JSON.stringify(out));")
    assert got == ["", "https://buy.stripe.com/x", ""]
    # A closed pass says so up front and in its own name, never as a $99 button.
    assert "League Pass opens soon" in JOIN
    assert "The League Pass isn't open just yet" in JOIN


def _funnel_pages() -> dict[str, str]:
    from render.live_sample import VIA_SCRIPT
    return {"landing": LANDING, "join": JOIN, "how-it-works": HOW,
            "league-pass": (SITE / "league-pass.html").read_text(encoding="utf-8"),
            "this-week (live sample)": VIA_SCRIPT,
            # FUNNEL F5 / BE2-D1: the published samples carry it too
            # (render/sample.page), from the live sample's one script.
            "sample-report": SAMPLE_REPORT, "sample-first-week": FIRST_WEEK_SAMPLE,
            # The free bye-week planner (contract C7) and the four league-app
            # pages (render/platforms.py, built with VIA_SCRIPT).
            "byes": (SITE / "byes" / "index.html").read_text(encoding="utf-8"),
            **{app: (SITE / app / "index.html").read_text(encoding="utf-8")
               for app in ("espn", "yahoo", "sleeper", "cbs")}}


def test_a_tag_survives_the_detour_through_the_sample_report(monkeypatch) -> None:
    """FUNNEL F5 / BE2-D1, reproduced: index.html?via=promo left all seven
    sample-report.html links bare (the funnel list left the samples out), and
    the sample's own "Get this for your team" links had no carry at all, so
    landing -> "See a real report" -> join -> checkout produced a ref with no
    _via- suffix and `make stats` counted the sale nowhere. The samples are
    now built with the live sample's carry script, before </body>."""
    import render.sample as sample
    monkeypatch.setattr(sample, "render",
                        lambda report, template: '<html><body><a href="join/index.html">'
                                                 'Get this</a></body></html>')
    page = sample.page({})
    assert page.index("function carryVia(") < page.index("</body>")
    assert 'a.setAttribute("href", carryVia(a.getAttribute("href"), VIA))' in page
    main = inspect_source(sample.main)
    assert "page(report)" in main and "render(report" not in main, \
        "the sample is written without the tag carry"


def inspect_source(fn) -> str:
    import inspect
    return inspect.getsource(fn)


def test_the_channel_tag_rides_every_link_into_the_funnel() -> None:
    """Launch audit F2, reproduced: LAUNCH.md tells the owner to post
    beatyourleague.com/?via=reddit, the landing read the tag only for its own
    waitlist POST, and every link to join/ dropped it — "Try it free" opened
    join/index.html?try=1 and the trial row posted with no via, so once the
    landing's capture retires `make stats` could count no channel at all.
    this-week.html, the page the Tuesday posts link, did the same. Each page
    now carries the sanitised tag onto its links into the funnel — URL only,
    nothing stored — with ONE function, identical on every page."""
    import inspect
    import json as _json
    from render import live_sample
    pages = _funnel_pages()
    sources = {name: _js_function(page, "carryVia") for name, page in pages.items()}
    assert len(set(sources.values())) == 1, \
        "carryVia drifted between pages: " + ", ".join(sources)
    via = {name: re.search(r"const VIA = .*?\|\| undefined;", page, re.S).group(0)
           for name, page in pages.items()}
    assert len(set(via.values())) == 1, "the VIA sanitiser drifted between pages"
    for name, page in pages.items():
        assert 'a.setAttribute("href", carryVia(a.getAttribute("href"), VIA))' in page, \
            f"{name} defines carryVia but never applies it"
        # One exception, and it is not the tag: the join page may keep a League
        # Pass buyer's own address in that tab's session storage under ONE key,
        # for thanks.html to prefill the group-chat line (LP-I9). It never
        # leaves the browser and thanks.html deletes it once read.
        kept = re.sub(r'sessionStorage\.(?:setItem|getItem|removeItem)\(\s*'
                      r'(?:PAID_EMAIL_KEY|["\']byl_paid_email["\'])', "", page) \
            if name == "join" else page
        assert not re.search(r"localStorage|sessionStorage|document\.cookie", kept), \
            f"{name} stores something in the browser"
    # The landing and league-pass write hrefs in script (the open state's
    # CTAs, the Buy button): the tag is applied AFTER the last of them.
    for name in ("landing", "league-pass"):
        code = pages[name]
        apply_at = code.rindex('a.setAttribute("href", carryVia(')
        writes = [m.start() for m in re.finditer(r"\.href = ", code)]
        assert writes and max(writes) < apply_at, \
            f"{name} writes an href after the tag was carried, so that link drops it"
    # The live sample's page carries it, before the closing body tag.
    page = live_sample.with_via_carry('<html><body><a href="join/index.html">x</a></body></html>')
    assert page.index("function carryVia(") < page.index("</body>")
    assert "with_via_carry(" in inspect.getsource(live_sample.main), \
        "this-week.html is written without the tag carry"
    # The function itself, run.
    cases = [
        ("join/index.html", "reddit", "join/index.html?via=reddit"),
        ("join/index.html?try=1", "reddit", "join/index.html?try=1&via=reddit"),
        ("join/index.html?plan=monthly", "x-post", "join/index.html?plan=monthly&via=x-post"),
        ("join/", "x", "join/?via=x"),
        ("index.html#pricing", "x", "index.html?via=x#pricing"),
        ("../index.html", "x", "../index.html?via=x"),
        ("../how-it-works.html", "x", "../how-it-works.html?via=x"),
        ("this-week.html", "x", "this-week.html?via=x"),
        ("league-pass.html", "x", "league-pass.html?via=x"),
        # The proof pages carry it on to join (FUNNEL F5, BE2-D1).
        ("sample-report.html", "x", "sample-report.html?via=x"),
        ("../sample-report.html", "x", "../sample-report.html?via=x"),
        ("sample-first-week.html", "x", "sample-first-week.html?via=x"),
        # The bye-week planner is a funnel page too (contract C7).
        ("byes/", "x", "byes/?via=x"),
        ("../byes/", "x", "../byes/?via=x"),
        ("byes/index.html?ref=s4-abc", "x", "byes/index.html?ref=s4-abc&via=x"),
        # The league-app pages read it and carry it on (T6: how-it-works and
        # the apps' own "Other league apps" links dropped it).
        ("espn/", "x", "espn/?via=x"),
        ("../yahoo/", "x", "../yahoo/?via=x"),
        ("../sleeper/index.html", "x", "../sleeper/index.html?via=x"),
        ("cbs/", "x", "cbs/?via=x"),
        ("espnx/", "x", "espnx/"),
        # Not a page that reads it, not ours, or already tagged: untouched.
        ("terms.html#cancel", "x", "terms.html#cancel"),
        ("compare/index.html", "x", "compare/index.html"),
        ("#watch-form", "x", "#watch-form"),
        ("mailto:hello@beatyourleague.com", "x", "mailto:hello@beatyourleague.com"),
        ("https://elsewhere.example/join/index.html", "x",
         "https://elsewhere.example/join/index.html"),
        ("join/index.html?via=first", "second", "join/index.html?via=first"),
        # Only a sanitised tag is ever written into a URL.
        ("join/index.html", "Reddit", "join/index.html"),
        ("join/index.html", "a b", "join/index.html"),
        ("join/index.html", "x" * 25, "join/index.html"),
        ("join/index.html", "", "join/index.html"),
    ]
    got = _node(sources["landing"] + "\nconsole.log(JSON.stringify("
                + _json.dumps([[h, v] for h, v, _ in cases])
                + ".map(([h, v]) => carryVia(h, v))));")
    assert got == [want for _, _, want in cases]
    # And what reaches it is the page's own sanitiser output.
    sanitise = via["landing"].replace("const VIA = ", "const f = (search) => ") \
                             .replace("location.search", "search")
    got = _node(sanitise + "\nconsole.log(JSON.stringify(['?via=Reddit!', '?via=a%20b', "
                "'?x=1', '?via=' + 'y'.repeat(30)].map((q) => f(q) || null)));")
    assert got == ["reddit", "ab", None, "y" * 24]


def test_the_league_pass_capture_never_points_at_a_hidden_form() -> None:
    """Launch audit F3, reproduced at 390 and 1280: with the landing able to
    complete checkout (its capture hidden) and seats still closed, League
    Pass's "Leave your email" loaded index.html#watch-form onto a form that was
    hidden=true — the visitor landed at the top of the page and could neither
    buy nor leave an address. The static link is right only while the landing
    shows its capture, which is exactly while CHECKOUT_OPEN is false (the
    landing hides it only inside `if (CHECKOUT_OPEN)`), and the two pages'
    CHECKOUT_OPEN must agree; once it is true, the closed pass points at the
    own-team checkout, which then exists."""
    lp = (SITE / "league-pass.html").read_text(encoding="utf-8")
    flag = r"const CHECKOUT_OPEN = (true|false);"
    assert re.search(flag, LANDING).group(1) == re.search(flag, lp).group(1), \
        "the landing and League Pass disagree on whether checkout is open"
    hide = LANDING.index('for (const id of ["watch-form", "watch-note"])')
    assert LANDING.rindex("if (CHECKOUT_OPEN) {", 0, hide) > LANDING.index("const CHECKOUT_OPEN"), \
        "the landing hides its capture outside the CHECKOUT_OPEN block"
    code = _js_code(lp)
    branch = code.split("} else if (CHECKOUT_OPEN) {")[1].split("\n}\n")[0]
    assert "ctaSlots" in branch and "join/index.html" in branch
    assert "watch-form" not in branch, "the open-checkout state still links the hidden capture"
    # The static closed state — the price card's ask and, since D18, the
    # closer's — is the only place the landing's capture is linked.
    slots = re.findall(r'<div class="ctaslot"[^>]*data-lp-cta>(.*?)</div>', lp, re.S)
    assert len(slots) == 2 and all("index.html#watch-form" in s for s in slots)
    assert lp.count("index.html#watch-form") == len(slots)


def test_the_group_chat_line_is_an_example_and_never_the_generic_seat_page() -> None:
    """Launch audit F4, then contract C3. The pre-purchase page once offered a
    live Copy of "I got us the League Pass … join/?pass=1" — false before
    anybody paid — and the fix made it copyable only once checkout and seats
    opened, carrying the payer's email for the generic seat page to match.
    That generic page is closed now (pre-launch review APPSEC-2: anyone who
    knew a buyer's address could take the pass's seats, and the replies said
    whether an address had bought one). A seat is claimed only through the
    link made for each pass after payment, which neither page can know: so
    league-pass shows an example with a blank in every state, thanks.html
    says where the link is, and neither offers a line to copy or asks for the
    buyer's address."""
    lp = (SITE / "league-pass.html").read_text(encoding="utf-8")
    example = re.search(r'<div id="chat-example">(.*?)\n    </div>', lp, re.S).group(1)
    assert "<button" not in example and "join/" not in example, \
        "the example can be copied, or hands out a seat link before payment"
    assert 'id="chat-live"' not in lp and 'id="chat-copy"' not in lp
    assert "chat-live" not in _js_code(lp)
    for name, page in (("league-pass", lp), ("thanks", THANKS)):
        markup = re.sub(r"<!--.*?-->", "", page, flags=re.S)
        assert "join/?pass=1" not in markup, f"{name} still hands out the generic seat page"
        assert not re.search(r'<input[^>]+type="email"', markup.split("<main")[-1]
                             if name == "thanks" else markup), \
            f"{name} asks for the buyer's address"
        assert ".innerHTML" not in _js_code(page)
    note = re.search(r'<div class="note passnote" id="pass-note" hidden>(.*?)</div>',
                     THANKS, re.S).group(1)
    assert "welcome email" in prose(note) and "<button" not in note


def test_a_closed_plans_button_says_what_pressing_it_does() -> None:
    """Launch audit F5 and F6, both reproduced. F5: only the monthly link set,
    list connected, season chosen — the button read "Email me when checkout
    opens", and pressing it posted nothing and said "switch to monthly". F6:
    no links, list connected — the note said "leave your email on the front
    page" while the page's own button captured it, the confirmation rendered
    in the red alert box, and each further press posted another row (two
    recorded). Now the label and the action come from one decision
    (closedAction): "switch" switches, "list" keeps the email once and then
    stops, "none" looks switched off — and names the plan that is not open
    yet (closedChipText, the words the header chip carried until the truth
    pass removed the chips)."""
    fns = (_js_function(JOIN, "closedAction") + _js_function(JOIN, "closedLabel")
           + _js_function(JOIN, "closedChipText"))
    states = [  # notify, pass, own plan open, monthly chosen, other plan's link
        ("https://f", False, "", False, "https://buy.stripe.com/m"),
        ("", False, "", True, "https://buy.stripe.com/s"),
        ("https://f", False, "", False, ""),
        ("", False, "", False, ""),
        ("https://f", True, "index.html", False, ""),
        ("https://f", True, "", False, ""),
        ("", True, "", False, ""),
    ]
    import json as _json
    got = _node(
        "let NOTIFY_LIST_ENDPOINT, WANTS_PASS, OWN_PLAN_HREF, monthlyChosen;\n"
        "const FIRST = null, SEAT_MODE = false;\n" + fns +
        "\nconsole.log(JSON.stringify(" + _json.dumps(states) + ".map(([n, p, o, m, other]) => {"
        " NOTIFY_LIST_ENDPOINT = n; WANTS_PASS = p; OWN_PLAN_HREF = o; monthlyChosen = m;"
        " const a = closedAction(other); return [a, closedLabel(a)]; })));")
    assert got == [
        ["switch", "Switch to monthly — open now"],
        ["switch", "Switch to the season pass — open now"],
        ["list", "Email me when checkout opens"],
        ["none", "Rest-of-Season Pass opens soon"],
        ["none", "League Pass opens soon"],     # own team's plan is open: no launch list
        ["list", "Email me when checkout opens"],
        ["none", "League Pass opens soon"],
    ]
    code = _js_code(JOIN)
    handler = code.split('$("form-email").addEventListener')[1].split("\n});")[0]
    # The press does what the label says: the same decision drives both.
    assert "if (switchesPlan()) {\n    switchPlan();" in handler
    assert 'closedAction(other) === "switch"' in _js_function(JOIN, "switchesPlan")
    assert 'closedAction(otherLink) === "list"' in handler
    assert "closedLabel(action)" in _js_function(JOIN, "noteClosedFor")
    # The first paint knows the other plan too (it used to pass none).
    first = code.split("if (!SEAT_MODE && !UPDATE_MODE && !TRY_MODE) {\n  noteClosedFor(")[1] \
                .split(");")[0]
    assert "seasonLink() : monthlyLink()" in first
    # F6: a kept email is a done message, once, and the note says "below".
    listed = handler.split('closedAction(otherLink) === "list"')[1].split(".catch(")[0]
    assert "if (state.listed) return;" in listed
    assert "state.listed = true" in listed and "showOk(" in listed
    assert 'showError("err-email"' not in listed, "a kept email is shown as an error"
    assert "$(\"submit\").disabled = listed" in _js_function(JOIN, "noteClosedFor")
    ok_rule = JOIN.split(".ok{")[1].split("}")[0]
    assert "brick" not in ok_rule and "turf" in ok_rule
    notes = _js_function(JOIN, "closedNoteNodes")
    below = notes.split('if (action === "list") {')[1].split("}")[0]
    assert "leave your email below" in below and "front page" not in below


def test_adding_a_player_keeps_every_choice_already_made() -> None:
    """Launch audit F7, reproduced at 390: paste a roster with "J. Taylor" and
    a junk line, tap "Jonathan Taylor" and "remove" ("…Looks right", step 3
    shown), then add Tyler Warren from the typeahead — the tally went back to
    "2 lines we couldn't read" and step 3 vanished, because adding re-read the
    whole paste box and neither choice ever edits it. A checked, unedited list
    now gains one row (R.addPick, run under node in tests/test_intake.py); only
    an unchecked or typed-over list is read from the box afresh."""
    add = _js_function(JOIN, "addPlayer")
    assert "R.addPick(state.directory, state.matches, player)" in add
    assert "state.matches.length > 0 && !state.stale" in add
    code = _js_code(JOIN)
    typed = code.split('$("roster-text").addEventListener("input"')[1].split("});")[0]
    assert "state.stale = true" in typed, "typing in the box must make the list stale"
    check = code.split('$("resolve").addEventListener("click"')[1].split("\n});")[0]
    assert "state.stale = false" in check


def test_a_row_that_needs_a_pick_says_so_and_never_says_nobody_has_that_name() -> None:
    """FUNNEL F9 / BE2-D2, the page's half (the resolver is twin-tested in
    tests/test_intake.py): "Allen" and "Kelce" read "we don't have anybody by
    that name" beside a typeahead that listed them, and the tally called them
    "lines we couldn't read". A part-name row offers its players as buttons
    (the existing choice row) with a sentence that asks for the pick; the
    tally counts picks apart from unreadable lines. Run under node."""
    assert "we don't have anybody by that name" not in _js_code(JOIN) + markup_only(JOIN)
    fn = _js_function(JOIN, "whyUnread")
    got = _node(fn + "\nconsole.log(JSON.stringify(["
                "{reason: 'partial', candidates: [{}]}, {reason: 'partial', candidates: [{}, {}]},"
                "{reason: 'ambiguous', candidates: [{}, {}]}, {reason: 'unknown', candidates: []},"
                "{reason: 'gone', candidates: []}].map(whyUnread)));")
    assert got[0] == "did you mean him? Tap his name to add him"
    assert got[1].startswith("that's part of more than one player's name — pick one")
    assert got[2] == "more than one player goes by that name — pick one"
    assert got[3].startswith("we couldn't find that name") and "Add a player" in got[3]
    assert got[4].startswith("not in this season's player list")
    draw = _js_function(JOIN, "draw")
    assert 'textCell("why", whyUnread(match))' in draw
    assert '" line needs" : " lines need") + " a pick"' in draw
    # The part-name candidates are the choice row's buttons, like "J Taylor".
    assert "const options = match.player ? (match.twins || []) : match.candidates;" in draw


def test_the_typeahead_closes_when_the_tap_is_meant_for_something_else() -> None:
    """FUNNEL F2, reproduced at 360-1280: after typing "wil", the list sat over
    the paste box and "Check my roster" (elementFromPoint at the box's centre
    was "Javonte Williams"); a tap meant for the box added him, and neither
    Escape nor a click outside closed it. It now closes on Escape, on a press
    outside it, and when focus leaves for anything but the list — never on a
    press inside the LIST, which would remove the name being tapped. A tap on
    the field itself is not a press in the list: the first fix counted it as
    one, so tapping the field, typing and pressing the keyboard's "Done" left
    all eight rows up (driven in headless Chrome at 390 and 1280). The
    handlers are run here under node against stand-in elements."""
    code = _js_code(JOIN)
    block = code[code.index("const addWrap = searchBox ?"):code.index("\nif (searchBox) {")]
    got = _node(r"""
const handlers = {doc: {}, wrap: {}, field: {}};
const on = (bag) => (type, fn) => { (bag[type] = bag[type] || []).push(fn); };
const fire = (bag, type, event) => (bag[type] || []).forEach((fn) => fn(event));
let rows = 8, focused = 0;
const field = {id: "field", addEventListener: on(handlers.field), focus() { focused++; }};
const row = {id: "row"}, outside = {id: "outside"};
const suggestBox = {contains: (n) => n === row, get childElementCount() { return rows; },
                    replaceChildren() { rows = 0; }};
const wrap = {contains: (n) => n === row || n === field, addEventListener: on(handlers.wrap)};
field.closest = () => wrap;
const document = {addEventListener: on(handlers.doc)};
const searchBox = field;
function renderSuggestions() { rows = 8; }
""" + block + r"""
const out = [];
const press = (target) => fire(handlers.doc, "pointerdown", {target});
const leave = (relatedTarget) => fire(handlers.wrap, "focusout", {relatedTarget});
press(field); leave(null); out.push(["field tapped, then Done", rows]);
rows = 8; press(row); leave(null); out.push(["a name tapped", rows]);
press(outside); out.push(["a press outside", rows]);
rows = 8; fire(handlers.doc, "keydown", {}); leave(row); out.push(["Tab onto a row", rows]);
leave(outside); out.push(["Tab past the list", rows]);
rows = 8; focused = 0;
fire(handlers.wrap, "keydown", {key: "Escape", preventDefault() {}});
out.push(["Escape", rows, focused]);
fire(handlers.field, "focus", {}); out.push(["focus again", rows]);
console.log(JSON.stringify(out));""")
    assert got == [["field tapped, then Done", 0], ["a name tapped", 8],
                   ["a press outside", 0], ["Tab onto a row", 8],
                   ["Tab past the list", 0], ["Escape", 0, 1], ["focus again", 8]], got
    esc = code.split('addWrap.addEventListener("keydown", (event) => {')[1].split("});")[0]
    assert esc.index("searchBox.focus();") < esc.index("closeSuggestions();"), \
        "focus first, or the field's focus handler redraws the list Escape closed"


def test_a_duplicate_row_names_the_player_not_a_line_number() -> None:
    """Launch audit F9, reproduced: a Sleeper paste plus "Josh Allen" again
    from the search box showed "you already listed this player on line 1" on
    the FIRST row drawn — the number counted players, not lines of the box
    (Josh Allen sat on line 2 under a "QB" header), and problem rows are drawn
    first, so the row it pointed at was below it."""
    draw = _js_function(JOIN, "draw")
    assert 'match.player.name + " is already on your roster — remove one"' in draw
    assert not re.search(r"on line \"|line \" \+", draw), "a duplicate still points at a line number"


def test_the_landing_invents_no_behaviour_of_people_it_has_never_observed() -> None:
    """Launch audit C6: the multi-league FAQ answer said "most managers start
    with the league that has the most riding on it" — on the page and in the
    JSON-LD — about customers that do not exist yet (no invented behaviour
    claims). Both copies are checked: the FAQ equality test keeps them equal."""
    import json as _json
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', LANDING, re.S)
    texts = {"landing": prose(markup_only(LANDING)),
             "landing JSON-LD": _json.dumps(_json.loads(block.group(1)))}
    # COPY:F9: terms §8 said "For most people that is $39" — an unbacked claim
    # about what customers pay, wrong for monthly and the League Pass — and
    # the 404 "Here's where most people meant to go."
    for page in ("join/index.html", "league-pass.html", "how-it-works.html", "thanks.html",
                 "terms.html", "404.html", "privacy.html"):
        texts[page] = prose(markup_only((SITE / page).read_text(encoding="utf-8")))
    claim = re.compile(r"\bmost (?:managers|people|players|subscribers|buyers|commissioners|"
                       r"fantasy players|of (?:you|our))\b|\b(?:managers|people|subscribers) "
                       r"(?:usually|typically|tend to)\b", re.I)
    for name, text in texts.items():
        assert not claim.search(text), f"{name} claims a behaviour nobody observed"


def test_the_free_report_waits_from_the_weeks_first_kickoff_whatever_day() -> None:
    """Launch audit C10: the note said "From Thursday night's first kickoff",
    but run/trials.py holds from the week's actual first kickoff — Week 1 and
    Week 12 of 2026 start on a Wednesday, Week 18 on a Sunday."""
    note = prose(re.search(r'<li id="trial-note"[^>]*>(.*?)</li>', JOIN, re.S).group(1))
    assert "From the week's first kickoff until Tuesday" in note
    assert "Thursday" not in note


def test_the_pass_buyers_thank_you_states_the_pass_refund_limit() -> None:
    """Launch audit C12, reproduced in headless Chrome: thanks.html?plan=pass
    showed the pass note and then "Full refund … — one per person", while the
    pass's own terms (terms §5, the welcome email, the join page's pass mode)
    say one per LEAGUE."""
    assert '<span id="refund-limit">one per person</span>' in THANKS
    branch = _js_code(THANKS).split('get("plan") === "pass") {')[1]
    assert 'getElementById("refund-limit").textContent = "one per league"' in branch


# --------------------------------------------------------------------- #
# the join page, Oct 15 2026 (world-class pass): shapes, seats, keeping the work
# --------------------------------------------------------------------- #

CONFIRM = (SITE / "join" / "confirm.html").read_text(encoding="utf-8")


def test_the_lineup_choices_name_the_platform_defaults_and_say_what_an_ungraded_one_gets() -> None:
    """RQ-10 / SS-I3 / PE-2: Sleeper's default (two FLEX) and Yahoo's (three
    WR) could not be set up, and a K-less league that keeps its DEF had no
    fitting option. The choices are a base named by the app whose default it
    is, plus a kicker and a defense answer — and a shape no arm has graded says,
    before anyone pays, that its report carries everything but the odds."""
    step = JOIN.split('<section id="step-league">')[1].split("</section>")[0]
    # Yahoo's default is the standard shape (help.yahoo.com SLN6489, JOIN-36).
    for value, words in (("std", "ESPN's and Yahoo's default"), ("flex2", "Sleeper's default"),
                         ("wr3", "Three WR"), ("sf", "Superflex")):
        assert re.search(rf'value="{value}"[^<]*>[^<]*(?:<span[^>]*>[^<]*)?{re.escape(words)}',
                         step), value
    assert 'name="kicker" value="no"' in step and 'name="defense" value="no"' in step
    note = _js_function(JOIN, "drawShapeNote")
    assert "R.GRADED_SHAPES.includes(code)" in note
    assert "everything except the odds" in prose(note)


def test_the_scoring_note_names_what_is_scored_and_what_is_not() -> None:
    """PC-10: "so every number matches your league" overclaimed — six-point
    passing touchdowns and TE premium are not scored. The note names the
    scoring that is, and says plainly that those two are not."""
    step = prose(JOIN.split('<section id="step-league">')[1].split("</section>")[0])
    assert "4-point passing touchdowns" in step
    assert "Six-point passing touchdowns and TE premium aren't scored yet" in step
    assert "every number matches your league" not in JOIN_PROSE


def test_no_join_copy_promises_odds_on_every_close_call() -> None:
    """PE-11: bye-heavy weeks, gated players and ungraded lineups carry none,
    so the promise is the true one — odds wherever both players are confirmed."""
    assert not re.search(r"odds on (?:every|each) close call", JOIN_PROSE, re.I)
    # Oct 21 2026 (fewer words): the default pitch and sidebar no longer
    # promise odds at all; where the page still does, the gate is stated.
    assert JOIN_PROSE.count(GATE_CLAUSE) >= 1


def test_a_table_copys_eleven_defenses_never_read_as_looks_right() -> None:
    """BE-D1, the page's half: more than two defenses on a checked list is a
    question, not "Looks right" — with a one-tap way to say they really are
    all yours. Run in the browser by the verification flow; pinned here."""
    draw = _js_function(JOIN, "draw")
    guard = draw.split("defenses > 2")[1].split("} else if")[0]
    assert "state.defensesOk !== defenses" in draw
    assert "did some come from a" in prose(guard) and 'confirm.style.display = "block"' in guard
    assert draw.index("defenses > 2") < draw.index("Looks right")


def test_seat_links_name_their_pass_and_bring_their_settings() -> None:
    """Contract C4 / LP-I1 / LP-I3. A 20-hex pass code in the seat link names
    the pass, so the page asks for NO buyer's address and posts the code; the
    link's s/n/t prefill the league's settings, said out loud and editable.
    ?pass=1 no longer has a typed-address path (contract C3, pre-launch review
    APPSEC-2): without a code the page says where the league's link is and
    posts nothing."""
    code = _js_code(JOIN)
    assert "/^[0-9a-f]{20}$/.test(QUERY.get(\"pass\") || \"\")" in code
    seat = _js_function(JOIN, "submitSeat")
    assert 'kind: "seat", email: email, ref: ref, via: SOURCE, pass_token: PASS_TOKEN' in seat
    assert "covered_by" not in code, "the page still posts a typed payer"
    assert seat.index("if (!PASS_TOKEN)") < seat.index("fetch(")
    assert 'id="pass-field"' not in JOIN and 'id="pass-email"' not in JOIN
    read = _js_function(JOIN, "settingsFromLink")
    for param in ('QUERY.get("s")', 'QUERY.get("n")', 'QUERY.get("t")'):
        assert param in read
    seat_branch = code.split("} else if (SEAT_MODE) {\n  const told")[1].split("\n}\n")[0]
    assert "settingsFromLink()" in seat_branch
    assert "Not right? Change them below." in prose(seat_branch)


def test_a_roster_update_never_quietly_replaces_the_settings_on_file() -> None:
    """FUNNEL F1, reproduced: join/index.html?update=1 sat on the page's
    defaults (Full PPR, 12 teams, standard + K + DEF) and posted them in the
    ref — run/updates.apply_updates takes scoring, size and slots from it — so
    a half-PPR 10-team subscriber's update re-scored every later report under
    the wrong rules. The update page now reads the report link's s/n/t (the
    seat link's format) and says they stand; without them it refuses to post
    until the subscriber ticks that the settings on screen are their league's.
    Run under node: the gate, every way round."""
    code = _js_code(JOIN)
    assert "if (UPDATE_MODE) prefillUpdateSettings();" in code
    # The box comes after the settings it vouches for, inside step 1: placed
    # above them it was ticked before a single setting was in view.
    assert (JOIN.index('id="shape-note"') < JOIN.index('id="settings-ok-wrap"')
            < JOIN.index('<section id="step-roster">'))
    prefill = _js_function(JOIN, "prefillUpdateSettings")
    assert "settingsFromLink()" in prefill and "told.length === 3" in prefill
    # A reload restores the roster (?ref=) with the settings chosen on this
    # page; the link's older ones never overwrite them, and the box confirms
    # what is on screen. So the prefill runs after the restore, and skips the
    # link when there is one.
    assert "const told = RESTORED ? [] : settingsFromLink();" in prefill
    assert code.index("if (RESTORED) {\n  setRadio(") < code.index(
        "if (UPDATE_MODE) prefillUpdateSettings();")
    assert "They stay as they are unless you change them here." in prose(prefill)
    assert "replaces the settings on file" in prose(prefill)
    submit = _js_function(JOIN, "submitUpdate")
    gate = 'if (!UPDATE_SETTINGS_FROM_LINK && !$("settings-ok").checked) {'
    assert gate in submit and submit.index(gate) < submit.index("fetch(FORM_ENDPOINT"), \
        "the settings check must come before anything is posted"
    # The gate, run: link settings or a ticked box let it through, nothing else.
    body = submit.split(gate)[1].split("return;")[0]
    got = _node(
        "const out = [];\n"
        "for (const [fromLink, ticked] of [[false, false], [false, true], [true, false]]) {\n"
        "  const UPDATE_SETTINGS_FROM_LINK = fromLink; let posted = true;\n"
        "  const $ = () => ({ checked: ticked });\n"
        "  const showError = () => { posted = false; };\n"
        f"  if (!UPDATE_SETTINGS_FROM_LINK && !$(\"settings-ok\").checked) {{{body} posted = false; }}\n"
        "  out.push(posted);\n}\nconsole.log(JSON.stringify(out));")
    assert got == [False, True, True]


def test_the_seat_page_asks_for_whoever_bought_the_pass_with_visible_labels() -> None:
    """LP-D6 / LP-D7. Both addresses on the seat form carry a <label> that
    stays on screen once typed in (the placeholders vanished, inviting the swap
    LP-D1 then dropped), and the copy names whoever bought the pass — any
    manager can — never "your commissioner's email"."""
    assert '<label class="optlabel" id="lbl-email" for="email">' in JOIN
    # The second address is gone with the typed-address route (contract C3):
    # a seat page asks only for the claimer's own address.
    assert 'id="lbl-pass-email"' not in JOIN
    assert "The email the League Pass was bought with" not in prose(JOIN)
    assert "commissioner's email" not in JOIN_PROSE
    assert "paid by your commissioner" not in JOIN_PROSE
    assert '$("footer-checkout").style.display = "none"' in _js_function(JOIN, "nothingToPay")


def test_the_renewal_date_is_stated_and_computed_from_today() -> None:
    """LP-I11: the terms line names the date the pass renews — the
    anniversary, or the month's last day when there is none — so a buyer can
    budget it. Run under node."""
    got = _node(_js_function(JOIN, "renewsOn") +
                "\nconsole.log(JSON.stringify([new Date(2026, 9, 15), new Date(2028, 1, 29),"
                " new Date(2026, 11, 31)].map(renewsOn)));")
    assert got == ["Oct 15, 2027", "Feb 28, 2029", "Dec 31, 2027"]
    # "bought today, on Oct 15, 2027" read as a purchase date a year away.
    assert '" — bought today, it renews on " + renewsOn(new Date())' in JOIN
    # 2026's passes don't renew, so no sentence on the page carries the date
    # today (renewsOn stays for the subscriptions 2027 brings back).
    assert JOIN.count('<span class="renews-on"></span>') == 0


def test_a_closed_checkout_names_no_delivery_date() -> None:
    """FUNNEL F4 / panel R3, reproduced on the closed page at 390 and 1280:
    under "Checkout isn't open just yet" the header chip read "Weekly reports
    from Tue, Oct 20", the sidebar "Your roster report today, your first
    weekly report Tue, Oct 20", and step 3 "bought today, it renews on Oct 17,
    2027" — for a purchase nobody could make that day (the same in
    ?plan=monthly, ?plan=pass and seat mode with no backend). The chip, the
    sidebar, the first-note and the renewal date all ask canStartToday()
    first; run under node for every mode. (The chip itself went in the truth
    pass; a closed plan's name now labels its button, closedChipText.)"""
    for fn in ("renewalDate",):
        assert "canStartToday()" in _js_function(JOIN, fn), fn
    assert "header-chips" not in JOIN and "firstChipText" not in JOIN
    draw = _js_function(JOIN, "drawFirst")
    assert draw.index("if (!canStartToday()) {") < draw.index('FIRST.when === "before"')
    assert "once checkout opens" in prose(draw)
    # A seat has no checkout: closed, it waits for seats to open.
    assert 'SEAT_MODE ? ", once seats open" : ", once checkout opens"' in draw
    # drawFirst runs at first paint and on every plan switch, so the static
    # "A report the day you join" never outlives a closed checkout.
    assert "drawFirst();" in _js_function(JOIN, "monthlyPlan")
    assert re.search(r"\ndrawShapeNote\(\);\nfillRenewalDates\(\);\ndrawFirst\(\);\n", JOIN)
    src = "\n".join(_js_function(JOIN, f) for f in
                    ("canStartToday", "closedChipText", "renewalDate",
                     "renewsOn", "monthlyLink", "seasonLink")) + (
        "\nvar MONTHLY_PAUSED = false; var MONTHLY_OFFERED = true;"
        " var PLAYOFF_ACTIVE = false; var STRIPE_LINK_PLAYOFF = \"\";")
    cases = [  # seat, pass, monthly, season link, monthly link, pass link, form
        [False, False, False, "", "", "", ""],
        [False, False, True, "x", "", "", ""],
        [False, True, False, "x", "x", "", ""],
        [True, False, False, "", "", "", ""],
        [False, False, False, "x", "", "", ""],
        [True, False, False, "", "", "", "https://forms.example"],
    ]
    got = _node(
        src + "\nconst FIRST = {when: 'after', tuesday: 'Tue, Oct 20'};\n"
        "const out = [];\n"
        f"for (const c of {json.dumps(cases)}) {{\n"
        "  globalThis.SEAT_MODE = c[0]; globalThis.WANTS_PASS = c[1];\n"
        "  globalThis.monthlyChosen = c[2]; globalThis.STRIPE_LINK_SEASON = c[3];\n"
        "  globalThis.STRIPE_LINK_MONTHLY = c[4]; globalThis.PASS_LINK = c[5];\n"
        "  globalThis.FORM_ENDPOINT = c[6];\n"
        "  out.push([canStartToday() ? 'open' : closedChipText(),"
        " renewalDate() ? 'dated' : '']);\n}\n"
        "console.log(JSON.stringify(out));")
    assert got == [["Rest-of-Season Pass opens soon", ""], ["Monthly opens soon", ""],
                   ["League Pass opens soon", ""], ["Seats open soon", ""],
                   ["open", "dated"], ["open", "dated"]]


def test_today_is_said_only_before_the_weeks_first_kickoff() -> None:
    """PC-02: the chips and sidebar promised "your first report today" to a
    buyer after kickoff, who gets the roster report today and the weekly report
    on Tuesday (run/intake.py _first_file; week 1 always starts with the roster
    report). Decided from site/week.json's first_kickoff; anything it cannot
    tell gives the sentence that is true either way."""
    fn = _js_function(JOIN, "firstReportTiming")
    week = {"week": 6, "last_week": 18, "lands_on": "2026-10-20",
            "first_kickoff": "2026-10-16T00:15:00Z"}
    import json as _json
    cases = [
        (week, "2026-10-15T12:00:00Z"),              # before Thursday night
        (week, "2026-10-16T01:00:00Z"),              # after it
        ({**week, "week": 1}, "2026-09-08T12:00:00Z"),
        ({k: v for k, v in week.items() if k != "first_kickoff"}, "2026-10-15T12:00:00Z"),
        (week, "2026-10-21T12:00:00Z"),              # the clock ran out
        ({**week, "week": 18}, "2026-10-16T01:00:00Z"),
    ]
    got = _node(fn + "\nconsole.log(JSON.stringify(" + _json.dumps(cases) +
                ".map(([w, now]) => { const r = firstReportTiming(w, new Date(now));"
                " return r ? r.when : null; })));")
    assert got == ["before", "after", "after", None, None, None]
    assert 'fetch("../week.json"' in _js_code(JOIN)
    static = markup_only(JOIN)
    assert "Your first report today" not in static and "First report the day you join" not in static
    assert "A report the day you join" in static


def test_a_closed_checkout_keeps_the_roster() -> None:
    """BE-I3 / I1 / contract C6. A checked roster is kept in the page's own
    address (?ref=), the waitlist row carries it, and ?ref= brings it back —
    decoded by roster.js, by id, never re-read from names."""
    keep = _js_function(JOIN, "keepInAddress")
    assert "R.withVia(checkoutRef(), SOURCE)" in keep and 'params.set("ref", ref)' in keep
    assert "history.replaceState" in keep and "email" not in keep.split("{", 1)[1]
    assert "keepInAddress();" in _js_function(JOIN, "draw")
    restore = _js_function(JOIN, "restoreRoster")
    assert "state.directory.byId.get(id)" in restore and "resolveAll" not in restore
    assert 'R.decodeRoster(QUERY.get("ref"))' in _js_code(JOIN)
    assert "SOURCE = VIA || (RESTORED && RESTORED.via)" in _js_code(JOIN)


def test_a_restored_roster_comes_back_under_the_plan_it_was_saved_under() -> None:
    """FUNNEL F8, reproduced on both copies: join/index.html?plan=monthly ->
    check a roster -> choose the season pass; the address became
    ?plan=monthly&ref=s4-…, and reopening it checked Monthly, read "Continue
    to checkout — $14.99/mo" and re-encoded the ref as m4-…, because ?plan=
    outranked the ref. The ref is the choice made last: it wins, and the
    address drops the stale ?plan= beside it. Run under node."""
    keep = _js_function(JOIN, "keepInAddress")
    assert 'if (!SEAT_MODE && !UPDATE_MODE && !TRY_MODE) params.delete("plan");' in keep
    decl = re.search(r"const RESTORED_PLAN = .*?;\nconst PLAN_PARAM = [^;]*;", JOIN, re.S).group(0)
    cases = [  # query, restored plan
        ["?plan=monthly&ref=s4", "season"], ["?plan=monthly&ref=p4", "league_pass"],
        ["?ref=m4", "monthly"], ["?plan=monthly", None], ["?plan=pass", None],
        ["?pass=1&ref=s4", "season"], ["?update=1&plan=monthly&ref=s4", "season"],
    ]
    got = _node(
        "const out = [];\n"
        f"for (const [q, plan] of {json.dumps(cases)}) {{\n"
        "  const QUERY = new URLSearchParams(q);\n"
        "  const RESTORED = plan ? { plan } : null;\n"
        f"  {decl}\n  out.push(PLAN_PARAM);\n}}\nconsole.log(JSON.stringify(out));")
    assert got == ["", "pass", "monthly", "monthly", "pass", "", "monthly"]


def test_every_confirmation_with_one_line_reads_as_a_sentence() -> None:
    """Panel R5, reproduced at 390 (?try=1, submitted): "Your free report is on
    its way." then a lone "1." before the only visible line — #done is an <ol>
    whose other items are hidden in that mode, and the same in seat and update
    mode. Every mode that pays nothing marks the list single."""
    assert ".done ol.single{list-style:none;margin-left:0;}" in JOIN
    assert 'document.querySelector("#done ol").classList.add("single");' in \
        _js_function(JOIN, "nothingToPay")
    for mode in ("TRY_MODE", "UPDATE_MODE", "SEAT_MODE"):
        branch = _js_code(JOIN).split(f"\nif ({mode}) {{" if mode == "TRY_MODE"
                                      else f"}} else if ({mode}) {{")[1][:1600]
        assert "nothingToPay(" in branch, mode


def test_the_update_and_confirm_pages_promise_only_what_happens() -> None:
    """FUNNEL F11 / COPY:F2, reproduced: right after the update form posted,
    the page said "Check your inbox. We've emailed a button to confirm the
    change" — nothing is mailed at submit, and nothing at all for an unchanged
    roster, an address with no subscription, or a fourth request that day
    (run/updates.validate_requests). The confirm page said "Confirmed. It's
    applied within the hour" for any 24-hex code, while the intake ignores a
    request older than EXPIRY_DAYS or one a newer confirmation retired."""
    from run.updates import CONFIRMS_PER_DAY, EXPIRY_DAYS
    note = prose(re.search(r'<li id="update-note"[^>]*>(.*?)</li>', JOIN, re.S).group(1))
    assert "We've emailed" not in note and "Check your inbox" not in JOIN_PROSE
    for promise in ("If this is the address your reports go to",
                    "differ from the ones on file", "usually within the hour",
                    f"within {EXPIRY_DAYS} days", "Nothing changes until it's pressed",
                    "up to three requests a day"):
        assert promise in note, promise
    assert CONFIRMS_PER_DAY == 3
    confirm = prose(CONFIRM)
    assert "Confirmed. It's applied" not in confirm
    assert f"Press the button within {EXPIRY_DAYS} days of asking" in confirm
    assert (f"If you asked for this change in the last {EXPIRY_DAYS} days and haven't "
            "confirmed a newer one since, it's usually applied within the hour") in confirm
    assert "An older button changes nothing" in confirm


def _run_confirm_page(search: str, endpoint: str) -> dict:
    """join/confirm.html's script under node, with a stub DOM: the page as it
    stands after load and after the button is pressed (fetch answers 200)."""
    import json as _json
    code = re.search(r"<script>(.*?)</script>", CONFIRM, re.S).group(1)
    code = code.replace('const FORM_ENDPOINT = "";',
                        f"const FORM_ENDPOINT = {_json.dumps(endpoint)};")
    return _node(
        "const els = {}; const el = (id) => els[id] || (els[id] = {id, textContent: '',"
        " className: '', disabled: false, handlers: {}, attrs: {}, addEventListener(t, f) {"
        " this.handlers[t] = f; }, setAttribute(n, v) { this.attrs[n] = String(v); },"
        " removeAttribute(n) { delete this.attrs[n]; }});\n"
        "el('head').textContent = 'Confirm your roster'; el('go').textContent ="
        " 'Yes, use my new roster';\n"
        "globalThis.document = { title: 'Beat Your League — Confirm your roster',"
        " getElementById: el };\n"
        f"globalThis.location = {{ search: {_json.dumps(search)} }};\n"
        "globalThis.window = globalThis;\n"
        "const posted = [];\n"
        "globalThis.fetch = (url, opts) => { posted.push(JSON.parse(opts.body));"
        " return Promise.resolve({ ok: true }); };\n"
        + code +
        "\nconst before = { title: document.title, head: el('head').textContent,"
        " intro: el('intro').textContent, button: el('go').textContent,"
        " msg: el('msg').textContent, disabled: el('go').disabled };\n"
        "if (el('go').handlers.click) el('go').handlers.click();\n"
        "setTimeout(() => console.log(JSON.stringify({ before, after:"
        " el('msg').textContent, posted })), 20);\n")


def test_a_seat_confirmation_says_seat_on_the_confirm_page() -> None:
    """OPS-R1's page half, reproduced: a seat claim is now confirmed from the
    claimed inbox, and its email links join/confirm.html?c=<code>&k=seat
    (run/updates.seat_confirm_url) — a page that said "Confirm your roster",
    "Yes, use my new roster" and "your next report uses the new one" to a
    leaguemate who has no reports yet, and with no backend told them to
    "reply to any report". In seat mode it names the seat; the POST is the
    same {kind:"confirm", code}; and, like the roster page (COPY:F2), it
    never says "Confirmed" for a code only the intake can judge — a seat's
    code lives 7 days and a full pass takes no more seats. Run under node."""
    from run.updates import seat_confirm_url
    good = "a" * 24
    assert seat_confirm_url("https://x.test", good).endswith(f"?c={good}&k=seat")
    seat = _run_confirm_page(f"?c={good}&k=seat", "https://w.test")
    assert seat["before"]["head"] == "Confirm your League Pass seat"
    assert seat["before"]["title"] == "Beat Your League — Confirm your League Pass seat"
    assert seat["before"]["button"] == "Yes, set up my seat"
    assert seat["before"]["intro"] == (
        "You asked for a seat on your league's League Pass, or to change the roster on "
        "the seat you hold. Press the button within 7 days of asking and it's usually "
        "set up within the hour.")
    assert seat["posted"] == [{"kind": "confirm", "code": good}]
    assert seat["after"].startswith("Received. If you asked in the last 7 days, your seat "
                                    "is usually set up within the hour and your first report "
                                    "follows the same day"), seat["after"]
    assert "seats are all taken" in seat["after"] and "Confirmed" not in seat["after"]
    closed = _run_confirm_page(f"?c={good}&k=seat", "")
    assert closed["after"] == "Seats aren't open just yet — nothing was set up."
    assert closed["posted"] == []
    broken = _run_confirm_page("?c=zz&k=seat", "https://w.test")
    assert broken["before"]["disabled"] and "reply to any report" not in broken["before"]["msg"]
    # The roster page is unchanged by it.
    roster = _run_confirm_page(f"?c={good}", "https://w.test")
    assert roster["before"]["head"] == "Confirm your roster"
    assert roster["before"]["button"] == "Yes, use my new roster"
    assert roster["after"].startswith("Received. If you asked for this change")
    assert "Didn't ask for this? Close this page — nothing changes unless you press the " \
           "button." in prose(CONFIRM)


def test_the_chips_are_a_thumb_tall_on_touch() -> None:
    """I10: the first controls in the funnel measured 35px on touch. Since the
    truth pass every option is 44px tall at every pointer (contract C7's one
    option shape), not only on touch."""
    rule = re.search(r"\n  \.opts label\{([^}]*)\}", _style(JOIN)).group(1)
    assert "min-height:44px" in rule and "border-radius:8px" in rule


@pytest.mark.parametrize("page,name", [(JOIN, "join"), (CONFIRM, "confirm")])
def test_join_pages_load_no_third_party_fonts_and_declare_their_colours(page, name) -> None:
    """Contract C7 and I12: fonts are self-hosted (no request to a font
    service — privacy.html can say so — and metric fallbacks stop the swap
    moving the page), the two above-the-fold faces are preloaded, and the paper
    page says it is light, with a navy browser bar."""
    assert "fonts.googleapis.com" not in page and "fonts.gstatic.com" not in page, name
    assert '<link rel="stylesheet" href="../fonts/fonts.css">' in page, name
    preloads = re.findall(r'<link rel="preload" href="\.\./fonts/[\w-]+\.woff2" as="font"'
                          r' type="font/woff2" crossorigin>', page)
    assert 1 <= len(preloads) <= 2, name
    assert '<meta name="theme-color" content="#101E33">' in page, name
    assert '<meta name="color-scheme" content="light">' in page, name
    assert not re.search(r"font-family:'Barlow(?: Condensed)?';", page), \
        f"{name}: a face with no fallback stack renders in Times until the font lands"


# --------------------------------------------------------------------- #
# world-class round 2 (Oct 15 2026) — the site: self-hosted type (C7), the
# hero (D3-D6), positioning (GTM-5, SS-I6, I8), the live-week links (PC-01),
# the copy (PC-03, PC-10, PE-11, BE-D4), legal (L6, L7), League Pass (LP-D7,
# LP-I5, LP-I6, LP-I8, LP-I9) and the site furniture (I4, I5, I12, I14)
# --------------------------------------------------------------------- #

FONTS = SITE / "fonts"
FONTS_CSS = (FONTS / "fonts.css").read_text(encoding="utf-8")
LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")
TERMS = (SITE / "terms.html").read_text(encoding="utf-8")
PRIVACY = (SITE / "privacy.html").read_text(encoding="utf-8")
# The hand-written pages; the generated ones are checked through their
# generators below.
_STATIC = ("index.html", "how-it-works.html", "league-pass.html", "thanks.html",
           "terms.html", "privacy.html", "404.html", "legal.html", "compare/index.html",
           "confidence.html", "projections.html", "no-call.html", "byes/index.html")
_PAPER = ("how-it-works.html", "terms.html", "privacy.html", "thanks.html", "404.html")


def _font_faces(css: str) -> list[dict[str, str]]:
    faces = []
    for block in re.findall(r"@font-face\s*\{([^}]*)\}", css):
        def get(key: str, block: str = block) -> str:
            found = re.search(rf"{key}\s*:\s*([^;]+)", block)
            return found.group(1).strip() if found else ""
        faces.append({"family": get("font-family").strip("'\""), "weight": get("font-weight"),
                      "style": get("font-style") or "normal", "src": get("src"),
                      "block": block})
    return faces


def _style(page: str) -> str:
    return "\n".join(re.findall(r"<style>(.*?)</style>", page, re.S))


def test_the_type_is_self_hosted_with_every_face_a_page_sets() -> None:
    """Contract C7 (launch review W1, W2, D2). Every page linked
    fonts.googleapis.com as a render-blocking cross-origin stylesheet, and on a
    slow phone the swap to Barlow moved the page by a quarter of a screen (CLS
    join 0.43-0.54, sample 0.27, how-it-works 0.23-0.25, terms 0.24): Barlow
    Condensed had no fallback at all and rendered in Times first.

    Now: one same-origin fonts.css naming the eleven faces the site actually
    sets (measured page by page in Chrome: Barlow 400-800, Barlow Condensed
    600/700/800/900 and 800/900 italic), each a latin woff2 that exists, with
    font-display:swap, under the OFL that ships beside them."""
    real = [f for f in _font_faces(FONTS_CSS) if "url(" in f["src"]]
    wanted = {("Barlow", w, "normal") for w in ("400", "500", "600", "700", "800")} | \
        {("Barlow Condensed", w, "normal") for w in ("600", "700", "800", "900")} | \
        {("Barlow Condensed", w, "italic") for w in ("800", "900")}
    assert {(f["family"], f["weight"], f["style"]) for f in real} == wanted
    for face in real:
        name = re.search(r"url\(([^)]+\.woff2)\)", face["src"]).group(1)
        data = (FONTS / name).read_bytes()
        assert data[:4] == b"wOF2", f"{name} is not a woff2 file"
        assert len(data) < 40_000, f"{name} is not a latin subset ({len(data)} bytes)"
        assert "font-display:swap" in face["block"].replace(" ", "")
        assert "unicode-range" in face["block"], f"{name} claims glyphs it lacks"
    licence = (FONTS / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence and "Barlow Project Authors" in licence


def test_every_stack_falls_back_to_a_metric_matched_face_first() -> None:
    """D2's cause was the fallback, not the font: Arial at a different width,
    or Times for the condensed face, re-wrapped every line when Barlow landed.
    Each fallback face is local Arial (or Arimo / Liberation Sans, which share
    its metrics) scaled to Barlow's measured width per weight, with Barlow's
    own ascent and descent, so nothing moves on swap. Measured in Chrome over
    the site's own copy: every fallback lands within 0.02% of its face's width,
    as written AND uppercased. That takes two faces per weight — Barlow's
    capitals are narrower against Arial's than its lower case (0.86 against
    0.96 at 400) — so each weight has a general face and a capitals face
    (unicode-range A-Z, defined after it so it wins for its range). Tuned to
    sentences alone, a sample's masthead chips (uppercase, 700) wrapped in the
    fallback and unwrapped on swap: CLS 0.20 at 768px on Slow 4G. The faces
    are named exactly as the report template's stacks name them (addendum a),
    and every hand-written page uses those stacks."""
    fallbacks = [f for f in _font_faces(FONTS_CSS) if "url(" not in f["src"]]
    assert {f["family"] for f in fallbacks} == {"Barlow Fallback", "Barlow Condensed Fallback"}
    slots: dict[tuple[str, str, str], list[str]] = {}
    for face in fallbacks:
        caps = "unicode-range:U+0041-005A" in face["block"].replace(" ", "")
        slots.setdefault((face["family"], face["weight"], face["style"]), []).append(
            "caps" if caps else "all")
    assert all(kinds == ["all", "caps"] for kinds in slots.values()), \
        f"every fallback weight needs a general face, then a capitals face: {slots}"
    for face in fallbacks:
        for descriptor in ("size-adjust", "ascent-override", "descent-override",
                           "line-gap-override"):
            assert descriptor in face["block"], f"{face['family']} {face['weight']}: no {descriptor}"
        assert "local('Arial" in face["src"] and "local('Arimo" in face["src"]
        size = float(re.search(r"size-adjust:([\d.]+)%", face["block"]).group(1))
        ascent = float(re.search(r"ascent-override:([\d.]+)%", face["block"]).group(1))
        descent = float(re.search(r"descent-override:([\d.]+)%", face["block"]).group(1))
        # Barlow's own vertical metrics are 1.0 em up and 0.2 em down; an
        # override is a share of the size-adjusted em.
        assert abs(ascent * size / 100 - 100) < 0.1 and abs(descent * size / 100 - 20) < 0.1
    template = (SITE.parent / "rival-report-template.html").read_text(encoding="utf-8")
    for stack in ("--display:'Barlow Condensed','Barlow Condensed Fallback'",
                  "--sans:'Barlow','Barlow Fallback'"):
        assert stack in template, f"the report template no longer names {stack}"
        for name in _STATIC:
            assert stack in _style((SITE / name).read_text(encoding="utf-8")), name


@pytest.mark.parametrize("name", _STATIC)
def test_every_page_links_its_own_type_and_preloads_what_exists(name: str) -> None:
    """C7: a relative fonts.css (root-absolute on 404.html, which is served at
    any depth), a preload only for files that exist, and no font-family that
    names Barlow without its fallback face (a bare 'Barlow Condensed' was the
    Times flash)."""
    page = (SITE / name).read_text(encoding="utf-8")
    prefix = "/" if name == "404.html" else "../" * name.count("/")
    # The landing carries fonts.css's own rules inline instead (Oct 24 2026:
    # the linked sheet was a render-blocking round trip that held the first
    # paint); tests/test_polish_landing.py holds that copy to the file.
    if name != "index.html":
        assert f'<link rel="stylesheet" href="{prefix}fonts/fonts.css">' in page
    preloads = re.findall(r'<link rel="preload" href="([^"]+)" as="font" '
                          r'type="font/woff2" crossorigin>', page)
    assert 1 <= len(preloads) <= 2, f"{name} preloads {len(preloads)} faces"
    for href in preloads:
        assert (FONTS / href.rsplit("/", 1)[1]).is_file() and href.startswith(prefix + "fonts/")
    rules = re.sub(r"@font-face\{[^}]*\}", "", _style(page))
    assert not re.search(r"font-family:\s*'Barlow", rules.split("--sans:", 1)[1]), \
        f"{name} sets Barlow without its fallback stack"


def test_the_generators_and_images_use_the_self_hosted_type() -> None:
    """Addendum (b): the ledger and backtest generators, the og card and the
    brand renderer still fetched Google Fonts. The two pages link the site's
    own fonts.css (the ledger one level down); the two image renderers embed
    the woff2 files, because Chrome refuses a file:// font in a file:// page
    (and a missing file refuses rather than rendering in Arial); the report
    template's preload helper reads the real fonts.css."""
    from render import brand, og
    from render.backtest_site import HEAD
    from render.report import font_preloads
    assert '<link rel="stylesheet" href="fonts/fonts.css">' in HEAD
    assert '<link rel="stylesheet" href="../fonts/fonts.css">' in LEDGER
    for source in ("render/backtest_site.py", "render/ledger_site.py", "render/og.py",
                   "render/brand.py"):
        assert "googleapis" not in (SITE.parent / source).read_text(encoding="utf-8"), source
    card = og.build_html(LANDING)
    assert card.count("src:url(data:font/woff2;base64,") == len(og.CARD_FACES)
    assert "src:url(data:font/woff2;base64," in brand.logo_html()
    with pytest.raises(og.OgError):
        og.embedded_fonts(font_dir=SITE / "no-such-folder")
    tags = font_preloads()
    assert tags.count('rel="preload"') == 2 and "barlow-condensed-800.woff2" in tags \
        and "barlow-400.woff2" in tags


def test_the_hero_report_is_on_screen_from_the_first_frame() -> None:
    """Launch review D3, reproduced at 1280x800 in Chrome: the script removed
    .screen.opened before first paint, so the first frame showed the card's
    header with an EMPTY body (rows held at opacity 0), then an inbox for two
    seconds; the rows reached full opacity at ~2.6s — the page's proof arrived
    last. The hero card is no longer an animated card, nothing in the CSS can
    hide the open email, and the motion is additive. Since Oct 24 2026 that
    motion is the Tuesday storyline (lock screen, the email, the open report),
    and it may not start until the decided report has held the screen for at
    least three seconds: .story is added only inside start(), and start() is
    reached only through a setTimeout of 3000ms or more, or the visitor's own
    press of the play toggle. Its first frame is the decided report too."""
    hero = LANDING.split('<header class="hero">')[1].split("</header>")[0]
    card = re.search(r'<div class="([^"]*)" id="hero-card"', hero).group(1)
    assert "anim" not in card.split(), "the hero card is held back until it animates"
    css = _style(LANDING)
    assert not re.search(r"\.screen[^{]*#hero-card[^{]*\{[^}]*opacity:\s*0", css)
    assert ".opened" not in css and 'classList.remove("opened")' not in LANDING
    story = _js_function(LANDING, "storyline")
    assert story.count('classList.add("story")') == 1
    start = story.split("const start = () => {")[1].split("\n  };")[0]
    assert 'classList.add("story")' in start, ".story is added outside start()"
    calls = re.findall(r"\bstart\(\)", story)
    timed = re.findall(r"setTimeout\(\(\) => \{ wait = 0; start\(\); \}, (\d+)\)", story)
    assert timed and all(int(ms) >= 3000 for ms in timed), timed
    clicked = story.split('toggle.addEventListener("click"')[1].split("});")[0]
    assert len(calls) == len(timed) + clicked.count("start()"), \
        "start() is reached some other way than the dwell timer or the toggle"
    for gone in ("heroCard", "mailrow", "play("):
        assert gone not in story, f"the storyline still drives {gone}"


def test_the_status_bar_clears_the_island_at_every_phone_size() -> None:
    """Launch review D4, measured in Chrome: a fixed 92px island on the 286px
    phone (every viewport up to 880px) sat over the first signal bar — at 390px
    the island spanned x 149-241 and the bar x 235.1-237.8. The island is a
    share of the screen now, and the status bar is three columns with the
    island's own width in the middle, so the icons sit in the right "ear"."""
    css = _style(LANDING)
    island = re.search(r"\.island\{([^}]*)\}", css).group(1)
    width = re.search(r"width:(\d+)%", island)
    assert width, "the island is sized in pixels again"
    # The lock screen's status bar (Oct 24 2026 storyline) keeps the same
    # three columns, so its icons clear the island too.
    for name in ("statusbar", "lk-status"):
        bar = re.search(r"\." + name + r"\{([^}]*)\}", css).group(1)
        assert f"grid-template-columns:1fr {width.group(1)}% 1fr" in bar, name
        assert re.search(r"\." + name + r" \.icons\{[^}]*grid-column:3", css), name


def test_reduced_motion_never_glides_the_page() -> None:
    """Launch review D6: html{scroll-behavior:smooth} survived reduced motion,
    and the sticky "Tell me when it opens" scrolled ~4,500px over most of a
    second for a visitor who asked for none (measured at 390px). The
    reduced-motion block turns it off, and the capture links scroll with
    behavior "auto" under it."""
    block = LANDING.split("@media (prefers-reduced-motion: reduce){\n")[1].split("\n  }")[0]
    assert "html{scroll-behavior:auto;}" in block
    assert 'behavior: reduced ? "auto" : "smooth"' in LANDING


def test_the_closest_call_card_keeps_one_numeral_and_says_what_the_bar_starts_at() -> None:
    """Panel review BE-I11: on a phone the tick label "TOSS-UP" sat right above
    "70%" and read as one phrase. The tick's meaning is a legend line, and the
    card says what the call IS (PC-03): the closest call that carries odds on
    that roster, not a coin flip. Since contract C11 the page's one closest
    call is the phone's card 02 — the report's own, with its own label — and
    the legend is card 01's, which says the bar starts at 50%."""
    assert "fliptoss" not in LANDING and "toss-up</span>" not in LANDING
    closest = LANDING.split('data-sec="closest"')[1].split("</section>")[0]
    assert len(re.findall(r'class="cpct"', closest)) == 1, "the card prints one numeral"
    assert '<p class="clabel">Closest call with odds</p>' in closest
    # Pre-launch review D12: the bar is drawn from 50%, as the report draws it.
    assert "and the bar starts at 50% (a toss-up)." in prose(LANDING)
    assert "go back and forth" not in prose(LANDING)


def test_the_closest_call_is_named_with_the_reports_own_label() -> None:
    """COPY:F4 / SS2-D2, reproduced: the landing said "The week's closest call
    on this roster, decided: Start Bijan Robinson over Chase Brown — 70%" and
    How it works defined it as "The one decision that could go either way",
    while the sample they link labels that call "Closest call with odds" and
    names a closer one: "Closer on points: Tony Pollard or Chase Brown at
    FLEX, 10.3 vs 10.3 — no odds". Every prose naming says "with odds"."""
    from engine import solo_report
    import inspect
    assert '"Closest call with odds"' in inspect.getsource(solo_report)
    import html as _html
    import json as _json
    from render.email import preheader_for
    landing = _html.unescape(prose(markup_only(LANDING)))
    assert '<p class="clabel">Closest call with odds</p>' in landing
    # The phone's notification is the email's own preview (contract C11),
    # which names the call in the report's words.
    fixture = _json.loads((SITE.parent / "tests" / "fixtures" / "sample-report-w10.json")
                          .read_text(encoding="utf-8"))
    preview = preheader_for(fixture)
    assert preview.startswith("Closest call with odds: start George Kittle over Sam LaPorta, 72%.")
    assert f'<span class="lpre">{preview}</span>' in landing
    assert "The week's closest call on this roster" not in landing
    how = prose(HOW)
    assert "<dt>The week's closest call with odds</dt>" in how
    assert "The one decision that could go either way" not in how
    assert "the report names it too" in how


def test_the_landing_sells_without_a_comparison_essay() -> None:
    """Owner direction, Oct 21 2026: too many words, focus on selling. The
    optimizer-vs-chatbot grid (GTM-5) and the "Why this exists" essay were cut;
    the page says what the buyer gets, shows the real report, prices it and
    answers six questions. Kept from the old guard: no results claim and no
    rankings straw man anywhere on the page."""
    assert 'class="cmpsec"' not in LANDING and 'class="why"' not in LANDING
    page = prose(markup_only(LANDING))
    assert "Why not just use rankings" not in page
    for claim in (r"\bmore (?:often|wins|accurate)\b", r"\bwin more\b", r"make the playoffs"):
        assert not re.search(claim, page, re.I), f"a results claim: {claim}"
    rendered = re.sub(r"<script.*?</script>|<style.*?</style>|<head>.*?</head>", "", LANDING, flags=re.S)
    words = len(re.sub(r"<[^>]+>", " ", rendered).split())
    assert words < 1300, f"the landing grew back to {words} words"


def test_the_faq_is_short_and_its_heading_stays_in_view() -> None:
    """I8: twelve questions read as a stock section; the three that compared
    tools now live in the comparison, and the heading column is sticky beside
    the answers on a wide screen."""
    questions = re.findall(r"<summary>(.*?)</summary>", LANDING.split('<section id="faq">')[1])
    assert 6 <= len(questions) <= 7, questions
    assert re.search(r"@media \(min-width:881px\)\{\.faqgrid > div:first-child\{position:sticky",
                     LANDING)


def _live_week_gate(page: str) -> bool:
    # And the page is in the card layout the phone shows (review BUYER-1).
    return re.search(r"w\.odds >= 3 && w\.closest_call &&\s*w\.cards === true", page) \
        is not None and 'querySelectorAll("[data-live-week]")' in page


@pytest.mark.parametrize("name", ("index.html", "how-it-works.html", "404.html"))
def test_every_link_to_the_live_report_waits_for_the_heros_rule(name: str) -> None:
    """Launch review PC-01, PE-3, F3(3): the hero linked this-week.html only
    in a week it showed at least three odds and a closest call, while the proof
    cards' footer, How it works (its PRIMARY button and its body) and the 404
    page linked it every week — including the bye-heavy one that once left it
    with nothing to show. Every such link now sits in a `data-live-week`
    element hidden until the same rule passes, and the pinned sample stands in
    until then."""
    page = (SITE / name).read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->", "", markup_only(page), flags=re.S)
    links = [m.start() for m in re.finditer(r'href="/?this-week\.html"', body)]
    assert links, f"{name} no longer links this week's report"
    for at in links:
        tag = body[body.rfind("<", 0, at):body.find(">", at) + 1]
        span = body.rfind("<span", 0, at)
        enclosing = body[span:at] if span >= 0 else ""
        assert ("data-live-week" in tag and "hidden" in tag) or (
            "data-live-week" in enclosing.split(">")[0] and "hidden" in enclosing.split(">")[0]
            and "</span>" not in enclosing), f"{name}: an ungated link to this-week.html"
    assert _live_week_gate(page), f"{name} never applies the three-odds rule"
    assert re.search(r'href="/?sample-report\.html"', body), f"{name} lost its pinned fallback"


def test_how_it_works_asks_for_the_one_action_it_leads_to() -> None:
    """PE-3: How it works' primary button was "See this week's report" — the
    hollow live sample on a bye-heavy week — on the page a skeptic reads last
    before deciding. Its first CTA is setting up a team."""
    cta = HOW.split('<div class="cta">')[1].split("</div>")[0]
    first = re.search(r'<a([^>]*)href="([^"]+)"', cta)
    # Closed checkout is the static state (D15): the ask is the landing's
    # email capture until CHECKOUT_OPEN turns it into setting up a team.
    assert first.group(2) in ("join/index.html", "index.html#watch-form") \
        and "ghost" not in first.group(1)
    assert re.search(r'<p class="headcta"><a class="btn gold" href="(?:join/index\.html|'
                     r'index\.html#watch-form)"', HOW)


def test_the_supported_scoring_and_the_odds_gate_are_stated_not_overclaimed() -> None:
    """PC-10, PE-11: "scored your league's way, every number" and "the odds on
    each one" overclaim a product that scores full PPR, half-PPR and standard
    and prints odds only where both players are confirmed to play — a bye-heavy
    week can carry few. Checked on every surface the review named: the hero,
    the meta, og and JSON-LD descriptions, and the thank-you page."""
    import json as _json
    block = _json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                  LANDING, re.S).group(1))
    product = next(n for n in block["@graph"] if n["@type"] == "Product")
    surfaces = {
        "meta": re.search(r'<meta name="description" content="([^"]+)"', LANDING).group(1),
        "og": re.search(r'property="og:description" content="([^"]+)"', LANDING).group(1),
        "JSON-LD": product["description"],
        "hero": prose(re.search(r'<p class="sub">(.*?)</p>', LANDING, re.S).group(1)),
        "thanks": prose(markup_only(THANKS)),
    }
    for name, text in surfaces.items():
        for overclaim in (r"your league's way", r"odds on (?:each one|every close call)",
                          r"every close call decided and the odds"):
            assert not re.search(overclaim, text, re.I), f"{name}: {overclaim}"
        # The hero (Oct 21 2026: fewer words) and the share preview (M12: the
        # benefit line, not the entity sentence) promise no odds at all, so
        # they owe no qualifier; any surface that mentions odds states the gate.
        if name in ("hero", "thanks") and "the odds" not in text:
            continue
        if name == "og" and not re.search(r"\bodds\b", text, re.I):
            continue
        assert GATE_CLAUSE in text, name
    for name in ("meta", "JSON-LD"):
        assert "half-PPR or standard" in surfaces[name]


def test_every_selling_page_states_the_odds_gate_in_the_same_plain_words() -> None:
    """COPY:F7, reproduced on the published sample: the Denver Broncos DEF row
    (@ KC, Sun; both teams playing, no designation) read "projection only"
    beneath a landing that promised "the odds wherever both players are
    healthy and playing" — defenses never get odds (graded D), a pair short
    of its record gets none either, and "healthy" claimed what a Tuesday report
    cannot know. Decided: it overclaimed. Every selling page now says what the
    gate checks, in one clause, and How it works spells out each check."""
    pages = {"landing": LANDING, "join": JOIN, "thanks": THANKS,
             "league pass": (SITE / "league-pass.html").read_text(encoding="utf-8"),
             "how it works": HOW}
    for name, page in pages.items():
        # Inline emphasis dropped, so "<b>The odds</b> wherever" is read too.
        text = prose(re.sub(r"</?(?:b|i|em|strong|span)\b[^>]*>", "", page))
        assert "healthy and playing" not in text, f"{name} still claims health"
        # COPY-3: "wherever" promised odds on every pair that passes the
        # checks; the old guard looked only for "odds wherever" and so passed
        # vacuously once the wording moved. Now no form of the sufficient
        # clause may appear, and every "only where both players" — the odds'
        # or a percentage's — is the whole clause, defenses included.
        assert not re.search(r"wherever both players", text), f"{name}: 'wherever' is back"
        for at in [m.start() for m in re.finditer(r"only where both players", text)]:
            assert text[at:].startswith(GATE_CLAUSE), \
                f"{name}: {text[at:at + 160]!r}"
    explained = prose(HOW.split("<dt>Rows with no percentage</dt>")[1].split("</dd>")[0])
    for check in ("teams play this week", "questionable, doubtful or out",
                  "reserve list or the practice squad", "three this season",
                  "Never on defenses", "never in Week 1"):
        assert check in explained, check


def test_who_built_it_agrees_with_the_terms() -> None:
    """Panel review BE-D4: the FAQ and its JSON-LD said "built by fantasy
    players" while terms §15 and privacy §11 say "an independent solo
    project". Anonymous, and singular."""
    for page in (LANDING, HOW):
        text = prose(page)
        assert "built by fantasy players" not in text and "We built it because we" not in text
        assert "one fantasy player built it" in text
    assert "an independent solo project" in prose(TERMS)


def test_the_terms_say_what_unsubscribing_does_on_each_kind_of_email() -> None:
    """Launch audit L6: terms §4 said clicking "unsubscribe" at the bottom of an
    email stops the emails. A paid report has no such link — its unsubscribe
    (the footer link and List-Unsubscribe) opens the billing page, and after
    cancelling the reports continue to the end of the paid period. Seats and
    the free emails have a reply-stop route. The contract says exactly that."""
    from render.report import unsubscribe_target
    terms = _terms_body()
    assert 'clicking "unsubscribe" at the bottom of an email stops the' not in terms
    assert "Unsubscribing, on a paid report, is cancelling." in terms
    assert re.search(r"continue to the end of the period you've already paid for, then "
                     r"stop", terms)
    assert re.search(r"Emails nobody pays for.{0,240}reply \"stop\"", terms)
    assert "Your league's pass isn't affected" in terms
    assert unsubscribe_target(seat=True).startswith("mailto:")


def test_the_privacy_policy_names_an_accountable_role_and_true_storage() -> None:
    """Launch audit L7: no accountable title, and GitHub's Actions cache called
    "private storage" — true only once fork-PR approval or encryption is in
    place, neither of which the policy can promise. Plus the records the ops
    work added (addendum f): a waitlist row's roster code, the channel tag on
    the Stripe customer, a seat claim's pass code, and the sample's recorded
    odds. Anonymous: a role, never a name."""
    privacy = _privacy_body()
    assert "Privacy contact, Beat Your League:" in privacy
    assert "private storage" not in privacy
    assert "the storage that automation carries between runs" in privacy
    section1 = privacy[privacy.find("1. What we collect"):privacy.find("2. What we never")]
    assert re.search(r"waitlist.{0,260}short code standing for that roster", section1, re.S)
    assert re.search(r"pass code in your league's own link", section1)
    # Contract C3: a seat comes only through the pass's own link, so its claim
    # holds the pass code and never the buyer's address.
    assert "the email the pass was bought with" not in section1
    stripe = privacy[privacy.find("Stripe handles payment"):][:600]
    assert "channel tag" in stripe
    assert "sample roster's report" in privacy
    assert "commissioner" not in privacy


def test_league_pass_copy_names_the_address_the_seat_page_asks_for() -> None:
    """Panel review LP-D7: any manager may buy the pass, yet the copy told a
    leaguemate to enter "your commissioner's email" — so a pass bought by a
    regular manager sent their league to type the wrong address, and the
    claim dropped. One phrase on every surface the site owns."""
    for name, page in (("league-pass", LEAGUE_PASS), ("thanks", THANKS),
                       ("terms", TERMS), ("privacy", PRIVACY)):
        # Comments may quote the old wording to explain the fix; a reader
        # never sees them.
        text = prose(re.sub(r"<!--.*?-->", "", markup_only(page), flags=re.S))
        assert "commissioner's email" not in text and "commissioner's pass" not in text, name
    # Contract C3 (pre-launch review APPSEC-2): no surface asks a leaguemate
    # for the buyer's address at all any more — a seat is claimed only
    # through its pass's own link — so the phrase that once named it is gone.
    for page in (LEAGUE_PASS, THANKS, PRIVACY):
        text = prose(re.sub(r"<!--.*?-->", "", markup_only(page), flags=re.S))
        assert "the email the pass was bought with" not in text
        assert "join/?pass=1" not in text


def test_league_pass_offers_a_true_ask_before_the_purchase() -> None:
    """Panel review LP-I5: a commissioner spending shared dues usually asks the
    league first, and the only line on offer was "I got us the League Pass" —
    false until paid. The ask is a question, true at any time, shareable at
    once, and carries no seat link (that goes out only after payment)."""
    ask = LEAGUE_PASS.split('<div class="steps ask" data-reveal>')[1].split("\n  </div>")[0]
    line = prose(re.search(r'<p id="ask-text">(.*?)</p>', ask, re.S).group(1))
    # Late October: out of the pot, not "this year's dues" (launch review M11).
    assert line.startswith("Should we take the League Pass")
    assert "join/" not in ask and "I got us" not in ask
    assert "league-pass.html" in line
    assert 'id="ask-share"' in ask
    assert LEAGUE_PASS.index('class="steps ask"') < LEAGUE_PASS.index("What you do after paying")


def test_the_pass_share_is_one_tap_and_prefilled() -> None:
    """Panel review LP-I6, LP-I9: the share is one big button using the
    phone's share sheet where there is one (a copy otherwise). It lives on the
    League Pass page's ask before buying. thanks.html had a second one for the
    generic seat line, prefilled from the join page's session storage; that
    line is gone with the generic route (contract C3), and with it the only
    thing either page kept in the browser — nothing is stored now."""
    share = _js_function(LEAGUE_PASS, "shareLine")
    assert "navigator.share" in share and "navigator.clipboard.writeText" in share
    assert 'err.name !== "AbortError"' in share, "a cancelled share sheet is not a failure"
    assert "shareLine(" in _js_code(LEAGUE_PASS).split('ask.addEventListener("click"')[1]
    for page in (THANKS, JOIN):
        assert "byl_paid_email" not in page and "PAID_EMAIL_KEY" not in _js_code(page)
    assert 'id="pass-copy"' not in THANKS


def test_league_pass_answers_the_commissioners_questions_twice_alike() -> None:
    """Panel review LP-I8: no page answered late joiners, replaced managers,
    co-managers, one person in two leagues, or what leaguemates' emails are
    used for — and How it works never mentioned the pass. The FAQ answers with
    what the code does (run/intake.py: one seat per address and pass, a
    claimed seat's first email the same day; render.welcome.SEATS_END), and
    its JSON-LD says the same words."""
    import json as _json
    from render.welcome import SEATS_END
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', LEAGUE_PASS, re.S)
    faq = _json.loads(block.group(1))
    assert faq["@type"] == "FAQPage"
    visible = {html.unescape(q): re.sub(r"\s+", " ", html.unescape(a)).strip()
               for q, a in re.findall(r"<summary>(.*?)</summary>\s*<div class=\"a\">(.*?)</div>",
                                      LEAGUE_PASS, re.S)}
    assert {i["name"]: i["acceptedAnswer"]["text"] for i in faq["mainEntity"]} == visible
    asked = " ".join(visible)
    for topic in ("join late", "leaves or is replaced", "co-manage", "two leagues",
                  "emails used for", "take a refund", "How many seats",
                  "switch to the League Pass"):
        assert topic in asked, topic
    # 2026's one-time pass: nothing to cancel, a refund ends the seats.
    assert "if you take a refund, every seat's reports stop too" in \
        visible["What happens to the seats if I take a refund?"]
    assert 'href="league-pass.html"' in HOW


def test_the_seat_cap_is_stated_where_a_buyer_and_a_leaguemate_read_it() -> None:
    """OPS-R7 / LP2-D1, the copy half. A pass now carries as many seats as its
    league has teams, in confirmation order (run/intake.PassInfo.seat_cap), a
    seat counts only once its inbox confirms it (OPS-R1), and a second
    purchase of the same roster folds into one report (merge_same_roster) —
    and no page said any of it: the operative terms promised "every member of
    one league" with no limit, the co-manager answer promised a seat with no
    "while they last", and a season-pass holder buying the pass had no answer
    about the subscription that keeps billing. The terms, the FAQ and the code
    say the same thing now; the terms change moved TERMS_VERSION with it."""
    from run.intake import PassInfo
    from render.welcome import TERMS_VERSION
    assert PassInfo(payer="p@x.test", pass_id="sub_1", league_size=12).seat_cap == 12
    terms = prose(TERMS)
    assert ("A League Pass is for one league of up to 14 teams. Besides the buyer's own "
            "report, it carries as many seats as the league size chosen at checkout "
            "(8, 10, 12 or 14), filled in the order members confirm them by email") in terms
    assert TERMS_VERSION >= "2026-10-17", "a change to the terms must move their version"
    lp = prose(LEAGUE_PASS)
    assert ("As many as your league has teams — one for every other manager, plus one to "
            "spare for a co-manager. Seats go to the managers who confirm theirs first") in lp
    assert "and each gets the report, while your league's seats last." in lp
    assert ("Your League Pass covers your own team, so you still get one report a week, not "
            "two. Both are one payment, so nothing keeps billing") in lp
    for page in (lp, prose(THANKS)):
        assert "the day they confirm their seat (we email them a button)" in page
        assert "the day they claim their seat" not in page


def test_the_closed_pricing_cards_take_you_into_the_form() -> None:
    """Launch review I4: both cards said "Leave your email above" while, at
    390px, the form sat ~3,000px above them. The prompt is a link to the form
    now, and every #watch-form link puts the cursor in the field."""
    # Pre-launch review D4: the closed card's control is a real gold button
    # into the form, not a dashed box holding a link.
    for cta in ("season-cta",):
        assert re.search(rf'<a class="btn gold" id="{cta}" href="#watch-form" data-to-capture>'
                         r'Tell me when it opens</a>', LANDING)
    handler = LANDING.split('document.addEventListener("click"')[1].split("\n});")[0]
    assert "closest('a[href=\"#watch-form\"]')" in handler
    assert "field.focus({ preventScroll: true })" in handler
    assert "form.hidden" in handler, "a hidden form must not swallow the click"
    # Review BUYER-4: the finance line no longer pitches the League Pass (its
    # own section follows), so the open state writes it whole and shows it.
    finance = LANDING.split('const finance = document.getElementById("finance-note");')[1]
    finance = finance.split("\n    }")[0]
    assert "finance.hidden = false;" in finance and "league-pass" not in finance


# thanks.html is reached by paying, so its nav offers no Pricing (launch
# review D5): tests/test_prelaunch_pages.py pins its routes (NAV_PAGES).
@pytest.mark.parametrize("name", tuple(p for p in _PAPER if p != "thanks.html")
                         + ("league-pass.html",))
def test_every_secondary_page_carries_the_sites_routes(name: str) -> None:
    """Launch review I5: only the landing had a nav; How it works, League
    Pass, terms, privacy, thanks and 404 offered a Home pill alone, so a
    visitor from a shared link had no route to pricing, a real report or
    setup. The routes the samples' masthead carries (render.report._site_bar)."""
    page = (SITE / name).read_text(encoding="utf-8")
    root = "/" if name == "404.html" else ""
    nav = re.search(r'<nav class="sitenav" aria-label="Site">(.*?)</nav>', page, re.S)
    assert nav, f"{name} has no site nav"
    # "See a real report" is contract C2's label (site_bar); terms and privacy
    # keep "Real report" until their words next change, because their visible
    # text is pinned to their Last-updated date (tests/test_promises_legal.py).
    for href, label in ((f"{root}how-it-works.html", "How it works"),
                        (f"{root}sample-report.html", "(?:See a real|Real) report"),
                        (f"{root}index.html#pricing", "Pricing")):
        assert re.search(rf'<a [^>]*href="{re.escape(href)}"[^>]*>{label}</a>', nav.group(1)), \
            f"{name}: no {label}"
    assert page.index("sitenav") < page.index("<h1"), "the routes sit above the headline"


@pytest.mark.parametrize("name,scheme,colour", [
    ("index.html", "dark", "#05090F"), ("league-pass.html", "dark", "#05090F"),
    *[(p, "light", "#101E33") for p in _PAPER]])
def test_every_page_declares_its_colour_scheme_and_bar_colour(name: str, scheme: str,
                                                               colour: str) -> None:
    """Launch review I12: no page declared color-scheme or theme-color, so the
    dark landing drew light native controls and scrollbars, and Safari's bar
    stayed untinted. Dark pages say dark; paper pages say light with the
    masthead's navy, as the generated report pages do (render.report.PAGE_META)."""
    head = (SITE / name).read_text(encoding="utf-8").split("</head>")[0]
    assert f'<meta name="color-scheme" content="{scheme}">' in head
    assert f'<meta name="theme-color" content="{colour}">' in head


def test_a_tablet_keeps_its_nav_and_two_pricing_cards() -> None:
    """Launch review I14, at 768px: the nav showed the logo alone (links and
    CTA hidden below 880px) and the pricing cards stacked into 724px-wide
    cards of mostly empty line. The CTA (short label) and How it works stay
    down to 600px; the cards go one column only at 640px."""
    css = _style(LANDING)
    tablet = css.split("@media (max-width:880px){\n")[1].split("\n  }")[0]
    assert "nav .btn{display:none" not in tablet and ".navlinks .hidesm{display:none" not in tablet
    assert "nav .btn .short{display:inline;}" in tablet
    assert ".plans{grid-template-columns:1fr;}" not in tablet
    assert "@media (max-width:640px){.plans{grid-template-columns:1fr;}}" in css
    phone = css.split("@media (max-width:599px){")[1].split("\n  }")[0]
    assert "nav .btn{display:none;}" in phone
    # The base rule hiding the short label must come BEFORE the media query
    # that shows it, or the cascade leaves the tablet's button empty (found in
    # Chrome at 768px while building this).
    assert css.index("nav .btn .short{display:none;}") < css.index("@media (max-width:880px){\n")


def test_the_social_card_uses_the_heros_headline_treatment() -> None:
    """Launch review I13: the card set "Know who to start." in sentence case,
    unlike the landing's italic capitals with the payoff on a gold slab, which
    weakened recall between X and the page. The card rebuilds the landing's
    own <em> slab from TEXT, so no markup of the page's reaches the card."""
    from render import og
    card = og.build_html(LANDING)
    h1 = re.search(r"\n  h1\{([^}]*)\}", card).group(1)
    assert "font-style:italic" in h1 and "text-transform:uppercase" in h1
    assert "<h1>Know who <em><span>to start.</span></em></h1>" in card
    hostile = LANDING.replace("<em><span>to start.</span></em>",
                              "<em><span>to <b>start</b>&lt;x&gt;</span></em>", 1)
    assert "<em><span>to start &lt;x&gt;</span></em>" in og.build_html(hostile)
    assert og.headline(LANDING) == "Know who to start."


def test_the_glossary_defines_the_realistic_range_in_the_reports_words() -> None:
    """Panel review SS-I1 (addendum d): every report prints a "realistic range"
    and no page said what it was. How it works carries the report's own
    definition, verbatim, and no figure."""
    from render.report import RANGE_DEFINITION
    glossary = HOW.split('<h2 id="read">')[1].split("<h2>")[0]
    entry = prose(glossary.split("<dt>Realistic range</dt>")[1].split("</dd>")[0])
    entry = re.sub(r"<[^>]+>", "", entry).strip()
    assert entry == RANGE_DEFINITION[0].upper() + RANGE_DEFINITION[1:]
    assert not re.search(r"\d", entry)
