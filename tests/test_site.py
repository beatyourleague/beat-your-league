"""Contract tests for the public funnel.

These guard the promises the funnel makes to a buyer. They exist because the
pressure to quietly remove them — hide the refund line, bury cancellation,
drop the "no free tier" honesty, let a number lose its source — always arrives
later, dressed as conversion optimisation. A failing test here means someone
is about to ship a dark pattern (PLAN.md §4, CLAUDE.md principle 3).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from conftest import requires_demo_render, requires_sample_league

SITE = Path(__file__).resolve().parent.parent / "site"
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
ROSTER_JS = (SITE / "join" / "roster.js").read_text(encoding="utf-8")
LEDGER = (SITE / "ledger" / "index.html").read_text(encoding="utf-8")
COMPARE = (SITE / "compare" / "index.html").read_text(encoding="utf-8")
PROJECTIONS = (SITE / "projections.html").read_text(encoding="utf-8")
NO_CALL = (SITE / "no-call.html").read_text(encoding="utf-8")
CONFIDENCE = (SITE / "confidence.html").read_text(encoding="utf-8")


def prose(page: str) -> str:
    """Copy as a reader meets it: JS string concatenation joined and whitespace
    collapsed, so assertions test the sentence rather than how it wrapped."""
    joined = re.sub(r'"\s*\+\s*"', "", re.sub(r"\s+", " ", page))
    return joined


def markup_only(page: str) -> str:
    """Page with <script> blocks removed — what is actually rendered today."""
    return re.sub(r"<script\b.*?</script>", "", page, flags=re.S | re.I)


LANDING_PROSE, JOIN_PROSE = prose(LANDING), prose(JOIN)


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


SEASON_PRICE = _price(r'class="price">\$(\d+) <small>/ season')
MONTHLY_PRICE = _price(r'class="price">\$(\d+\.\d\d) <small>/ month')


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


def test_cancellation_is_promised_and_never_obstructed() -> None:
    """Subscribers must be told they can leave, in plain words."""
    assert re.search(r"cancel yourself any time|cancel any time", JOIN, re.I), \
        "join page must tell subscribers they can cancel themselves"
    assert re.search(r"cancel any time", LANDING, re.I)
    # No copy anywhere that gates leaving behind contacting us.
    for page in (LANDING, JOIN):
        assert not re.search(r"contact us to cancel|email us to cancel|call to cancel",
                             page, re.I)


def test_the_launch_waitlist_states_exactly_what_it_will_send() -> None:
    """Checkout is closed and the product is being rebuilt, so the only honest
    ask on this page is a waitlist. It must say what arrives, how often, and how
    to leave — a list that promises "updates" and then mails weekly is how a
    launch burns the audience it spent three weeks collecting."""
    assert 'id="watch-form"' in LANDING
    assert re.search(r"unsubscribe in one click", LANDING, re.I)
    assert re.search(r"no card", LANDING, re.I)
    # The volume promise is the part that must not go missing.
    assert re.search(r"exactly one message|one email when signups open",
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
    assert 'class="price">$' + SEASON_PRICE in markup_only(LANDING), \
        "the pricing section must state the season price plainly"
    assert re.search(r"paid product from day one", JOIN_PROSE, re.I)
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
    rendered = markup_only(LANDING)
    assert rendered.count(f"${SEASON_PRICE}") == 2, "landing page price mentions drifted"
    renewal_mentions = len(re.findall(rf"renews? (?:once a year )?at \${SEASON_PRICE}",
                                      rendered, re.I))
    assert renewal_mentions == 1, "the renewal disclosure must state the amount"


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
    assert re.search(r"STRIPE_LINK[_A-Z]*\s*(\|\||\?|===|!==|&&)|!.*STRIPE_LINK", JOIN), \
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
    assert set(inputs) <= {"text", "email", "radio"}, \
        f"unexpected input types: {inputs}"
    assert re.search(r"never ask for a password", JOIN_PROSE, re.I)
    assert re.search(r"never connect to your league", JOIN_PROSE, re.I)


def test_pass_states_its_renewal_terms() -> None:
    """A recurring charge must say so where it is sold (PLAN §4, ROSCA)."""
    for page, name in ((LANDING_PROSE, "landing"), (JOIN_PROSE, "join")):
        assert re.search(r"renews once a year|no renewal|one payment", page, re.I), \
            f"{name} page sells the season pass without stating renewal terms"
    assert re.search(r"email you before it bills|we email you first|email before it bills",
                     LANDING_PROSE, re.I)


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
                   "7.2%", "64.6%", "10,041"):
        assert figure not in visible, \
            f"backtest figure {figure} is quoted on the landing page; it belongs on " \
            "the evidence page that carries its context"
    assert not re.search(r"hindsight filter|calibration error|buckets?\b", visible,
                         re.I), "calibration vocabulary leaked back onto the sales page"
    # Every proof is one click away, never zero clicks.
    for href in ("confidence.html", "projections.html", "no-call.html", "backtest.html"):
        assert f'href="{href}"' in LANDING, f"the landing no longer links {href}"


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
    assert 'href="backtest.html"' in LANDING
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
    assert re.search(r"analysis, not picks", LEDGER, re.I)


def test_landing_links_to_the_public_ledger() -> None:
    assert 'href="ledger/index.html"' in LANDING


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
                                  "confidence", "live report"])
def test_no_developer_vocabulary_in_buyer_copy(name: str) -> None:
    if name == "live report":
        page = _demo_report_html()
    else:
        page = {"sample report": SAMPLE_REPORT,
                "first-week sample": FIRST_WEEK_SAMPLE,
                "landing": LANDING, "join": JOIN,
                "compare": COMPARE, "projections": PROJECTIONS,
                "no-call": NO_CALL, "confidence": CONFIDENCE}[name]
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
    assert 'cron: "0 * * * *"' in workflow, (
        "the intake no longer runs hourly, so \"up to an hour\" on the "
        "post-purchase page may now be a promise we cannot keep")
    assert re.search(r"up to an hour", visible, re.I), \
        "the page does not say how long the first file takes"

    for required, why in (
            (r"spam", "a new sending domain's first email often lands there"),
            (r"refund", "the Week-2 window, at the moment they are most anxious"),
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
    assert re.search(r"roster file", visible, re.I), "the pre-season case"
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
    """The no-cookies claim is only honest while it is true, and the pages DO
    reach one third party: Google Fonts sees a visitor's IP. Saying "no
    trackers" while silently loading a Google stylesheet is the kind of small
    untruth that discredits the whole page, so the policy names it."""
    pages = [p for p in SITE.rglob("*.html")]
    fonts = [p for p in pages
             if "fonts.googleapis.com" in p.read_text(encoding="utf-8")]
    whole = (SITE / "privacy.html").read_text(encoding="utf-8")
    privacy = whole[whole.find("<body>"):]           # body only, same reason
    if fonts:
        assert re.search(r"google fonts", privacy, re.I), (
            f"{len(fonts)} pages load Google Fonts and the privacy policy does "
            f"not mention it, while claiming no trackers")
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for tracker in ("googletagmanager", "google-analytics", "gtag(",
                        "plausible.io", "fathom", "posthog"):
            assert tracker not in text, (
                f"{page.name} loads {tracker} while privacy.html says the site "
                f"runs no analytics")


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
    assert re.search(r"billing stops immediately", legal, re.I)
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
        assert re.search(r"cancel", text, re.I), f"{name} offers no way to cancel"
        assert re.search(r"unsubscrib\w+ from emails alone does ?not|"
                         r"unsubscribing from emails alone does NOT", text, re.I), \
            f"{name} must distinguish stopping emails from stopping billing"
        assert not re.search(r"reply to this email with the word", text, re.I), \
            f"{name} must not route cancellation through a human inbox"


def test_monthly_billing_never_outlives_the_product() -> None:
    """Monthly stops at season end, and run/billing.py is what makes it true."""
    legal = prose((SITE / "terms.html").read_text(encoding="utf-8"))
    assert re.search(r"billing runs only while the season runs", legal, re.I)
    assert re.search(r"do not charge monthly through the offseason", legal, re.I)
    assert re.search(r"billing stops when the season does", prose(LANDING), re.I)


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
    assert re.search(r"charged\s+when you subscribe", legal, re.I)
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
    assert re.search(r"the roster you entered", legal, re.I)
    assert re.search(r"scoring settings", legal, re.I)
    assert re.search(r"never connect to your league", legal, re.I)
    assert re.search(r"public NFL data", legal, re.I)
    # The pitch says the founding rate is locked for every renewal; the
    # contract has to say it too, or the 'legal wins' clause makes the pitch
    # a deceptive-pricing pattern.
    assert re.search(r"Founding subscribers renew at their founding price", legal)
    assert re.search(r"locked in for every renewal", prose(JOIN), re.I)


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
    assert re.search(r"renews once a year at \$39", text, re.I)
    assert re.search(r"email you before it bills", text, re.I)
    assert re.search(r"cancel yourself", text, re.I)
    assert re.search(r"one per person", text, re.I)
    script = prose(JOIN)
    # Plan-aware rewrites, each naming its own amount.
    assert re.search(r'\$\("terms-line"\)\.textContent = monthlyTerms', script)
    assert re.search(r'\$\("terms-line"\)\.textContent = passTerms', script)
    assert re.search(r"renews once a year at \$99", script)
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
    """A gated slot must say we chose not to call it — never a version number."""
    assert "no call" in SAMPLE_REPORT.lower()
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
    rendered = markup_only(LANDING)
    monthly = re.search(r'class="price">\$(\d+\.\d\d) <small>/ month', rendered)
    season = re.search(r'class="price">\$(\d+) <small>/ season', rendered)
    assert monthly and season, "could not read both prices off the pricing cards"
    modal_total = float(monthly.group(1)) * BILLED_MONTHS
    pass_price = float(season.group(1))
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
    rendered = markup_only(LANDING)
    monthly = re.search(r'class="price">\$(\d+\.\d\d) <small>/ month', rendered)
    season = re.search(r'class="price">\$(\d+) <small>/ season', rendered)
    assert monthly and season, "could not read both prices off the pricing cards"
    legal = (SITE / "terms.html").read_text(encoding="utf-8")
    compare = (SITE / "compare" / "index.html").read_text(encoding="utf-8")
    # The compare table quotes NINE competitors' real prices, so only our own
    # row may be swept for a stale figure — scoping it to any narrower thing
    # than <tr class="us"> would be a guard that reads somebody else's number.
    ours = re.search(r'<tr class="us">.*?</tr>', compare, re.S)
    assert ours, "the comparison table no longer marks our own row"

    for page, name in ((legal, "terms.html"), (ours.group(0), "compare, our row")):
        assert f"${monthly.group(1)}" in page, (
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
    for required in (r"\$99", r"renews once a year", r"cancel yourself any time",
                     r"no-questions refund", r"18\+", r"not affiliated"):
        assert re.search(required, prose_page, re.I), f"league pass missing: {required}"
    # It must not promise a report to managers who never signed up.
    assert re.search(r"Managers who never sign up simply don't get a report", prose_page, re.I)
    assert re.search(r'href="terms\.html"', LEAGUE_PASS)


def test_league_pass_makes_no_win_promise() -> None:
    prose_page = prose(LEAGUE_PASS)
    assert re.search(r"not a guarantee", prose_page, re.I)
    assert re.search(r"somebody finishes last", prose_page, re.I)


def test_landing_states_the_weekly_ritual_not_just_the_contents() -> None:
    """People buy a habit, not a document. The page must say what the week
    actually looks like: when it arrives, how long it takes, what you do."""
    assert re.search(r"ninety seconds|90 seconds", LANDING_PROSE, re.I)
    assert re.search(r"tuesday morning", LANDING_PROSE, re.I)
    assert re.search(r"tick the boxes|three-box checklist", LANDING_PROSE, re.I)


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
    """The buyer's decisive question is 'what do I actually do on Tuesday?'"""
    assert re.search(r"30-second game plan", SAMPLE_REPORT, re.I)
    assert re.search(r"set (the|your|this) lineup", SAMPLE_REPORT, re.I)


# --------------------------------------------------------------------- #
# the comparison page stays honest, or it stops being useful
# --------------------------------------------------------------------- #

def test_the_published_sample_is_the_solo_product() -> None:
    """`make demo` used to write the league demo over site/sample-report.html —
    a page full of features the paid product does not have. The published
    sample must always be the solo render: its title says Report (not Rival
    Report), and it carries the solo banner."""
    assert "Week 10 Report" in SAMPLE_REPORT
    assert "Rival Report" not in SAMPLE_REPORT
    assert "built from the real 2024 NFL season" in SAMPLE_REPORT
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
    right now: no track record until October."""
    our_row = COMPARE.split('class="us"')[1].split("</tr>")[0]
    for admission in ("No draft kit", "no app", "we're new",
                      "October", "backtest and a sample"):
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
    assert groups == {"scoring", "size", "template"}, \
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
    match = re.search(r"^> (Beat Your League is a weekly .+?failed\.)$", plan,
                      re.S | re.M)
    assert match, "PLAN §1 lost the blockquoted entity sentence"
    sentence = re.sub(r"\s+", " ", match.group(1).replace("> ", ""))

    surfaces = {
        "landing meta description":
            re.search(r'<meta name="description" content="([^"]+)"', LANDING).group(1),
        "landing og:description":
            re.search(r'property="og:description" content="([^"]+)"', LANDING).group(1),
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
    assert prices == {SEASON_PRICE, MONTHLY_PRICE}, (
        f"structured-data prices {prices} drifted from the page's "
        f"{{{SEASON_PRICE}, {MONTHLY_PRICE}}}")
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
    (CONFIDENCE, ("nflverse-backtest.md", "early-season-backtest.md")),
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
    assert re.search(r"PPR scoring, 12-team\s+leagues and the standard lineup", text), \
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
                "compare": COMPARE,
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
                                       (FIRST_WEEK_SAMPLE, "first-week sample")])
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
    assert "join/index.html" in sample, "sample report is a dead end"
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
    assert "example.com/join" in line and "example.com/ledger" in line


def test_launch_notify_uses_the_list_endpoint_never_the_seat_form() -> None:
    """The closed-checkout capture keeps the email ONLY, on the ledger-list
    backend. The seat form endpoint must stay reserved for League Pass seats —
    an individual signup posted there would bypass the payment architecture."""
    handler = JOIN.split('$("form-email").addEventListener')[1]
    closed = handler.split("if (!link) {")[1].split("if (WANTS_PASS)")[0]
    assert "NOTIFY_LIST_ENDPOINT" in closed
    assert "FORM_ENDPOINT" not in closed
    assert "league_id" not in closed, "launch-notify must carry the email only"
    # The honest-refusal phrases survive in both outcomes.
    assert closed.count("isn't open just yet") == 3, \
        "every not-open outcome must say so"
    assert closed.count("isn't saved") == 3


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
    pin their presence and their key phrases."""
    assert 'id="header-pitch"' in JOIN and 'id="header-chips"' in JOIN
    assert "Seat already paid by your commissioner" in JOIN
    assert "covers " in JOIN and "every manager in your league" in prose(JOIN)
    assert f"${MONTHLY_PRICE} / month" in JOIN
    # The commissioner's shareable seat link exists only pre-checkout (Stripe
    # confirmation messages are static per link and cannot carry a league id).
    assert 'id="seat-share"' in JOIN
    assert '"?pass=1"' in JOIN


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
    # The silhouette must stay a vesica (two arcs), never revert to an ellipse.
    assert MARK_PATH.count("A13.145 13.145") == 2
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
    published sample."""
    import html as _html
    cards = re.findall(r'<div class="filecard[^"]*">(.*?)<span class="real">',
                       LANDING, re.S)
    assert len(cards) >= 3, (
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
    quoted = "Start Amon-Ra St. Brown over Courtland Sutton"
    def flat(page: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
    assert quoted in flat(SAMPLE_REPORT).replace("  ", " "), \
        "the sample no longer says this — regenerate with `make sample` and re-check"
    assert quoted in flat(LANDING).replace("  ", " "), \
        "the landing page's coin-flip card drifted from the report it cites"
    # And the figures the card attaches to that claim.
    assert "12.7 vs 10.3" in flat(SAMPLE_REPORT) and "12.7 vs 10.3" in flat(LANDING)
    # The lineup card's rows, too — a row quoting a confidence the sample no
    # longer publishes is a number the product did not compute.
    import html as _html
    sample_rows = _html.unescape(flat(SAMPLE_REPORT))
    for name, pct in (("Ja'Marr Chase", "65%"), ("Amon-Ra St. Brown", "58%"),
                      ("George Kittle", "66%")):
        assert re.search(rf"{re.escape(name)}.{{0,160}}{pct}", sample_rows), \
            f"the sample no longer publishes {pct} on {name}"
        assert re.search(rf"{re.escape(name)}.{{0,160}}{pct}", flat(LANDING))


def test_the_seat_link_is_not_handed_out_before_checkout() -> None:
    """The League Pass seat URL used to render at step 2 of 4. A commissioner
    could paste it in the group chat and then abandon the payment, leaving
    eleven managers each told their seat was claimed — while every claim is
    dropped on Tuesday for want of a pass covering that league, visible only in
    a CI log. It is revealed on the way to Stripe, and the seat holder is told
    what actually happened rather than that they are entitled."""
    # The roster step is where a commissioner would be tempted to reveal it,
    # so that is what must stay clean.
    pick = JOIN.split("function draw()")[1].split("\n$(")[0]
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
    match = re.search(r"Twelve individual passes would cost \$(\d+)", LEAGUE_PASS)
    assert match, "the League Pass page lost its comparison"
    assert int(match.group(1)) == 12 * int(SEASON_PRICE), (
        f"the page compares against ${match.group(1)} but twelve season passes "
        f"at ${SEASON_PRICE} is ${12 * int(SEASON_PRICE)}")


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
    assert re.search(r'UPDATE_MODE = /\^\[0-9a-f\]\{10\}\$/\.test\(UPDATE_SLUG\)', JOIN)
    assert re.search(r'/\^\[0-9a-f\]\{20\}\$/\.test\(UPDATE_TOKEN\)', JOIN)
    # With no backend it says the roster is NOT saved and names the fallback.
    assert "isn't saved" in post and "reply to any report" in post
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
    assert 'href="sample-first-week.html"' in SAMPLE_REPORT
    assert "join/index.html" in FIRST_WEEK_SAMPLE, "first-week sample is a dead end"
    # And the mid-season page says plainly that the first file is thinner,
    # rather than leaving a buyer to discover it on Sep 8.
    assert re.search(r"first file of a season is thinner",
                     re.sub(r"<[^>]+>", " ", prose(SAMPLE_REPORT)))


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
    for cta in ("nav-cta", "season-cta", "closer-cta", "monthly-cta"):
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
    assert "header-pitch" in pass_branch and "$99" in pass_branch
    assert "header-chips" in pass_branch
    monthly_branch = JOIN.split("else if (WANTS_MONTHLY)")[1] \
                         .split("else if (WANTS_PASS)")[0]
    assert "header-pitch" in monthly_branch and "14.99" in monthly_branch


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
    # The hero card's compact treatment keys on the CARD's width, not the
    # layout breakpoint that happens to sit at 880.
    assert re.search(r"@media \(max-width:1000px\)\{[^}]*\.frow\{", LANDING, re.S), \
        "the hero card's narrow treatment is gone or re-keyed to a breakpoint"
    compact = LANDING.split("@media (max-width:1000px)")[1][:400]
    assert ".fbar{display:none;}" in compact, \
        "the bar column is back on narrow screens — it is the 92px the name needs"
    assert ".fnc{grid-column:2 / 5;}" in compact, \
        "the no-call row still spans the five-column grid"

    # Grid children must be allowed to shrink, or nowrap text forces the row
    # wider than the viewport again.
    assert re.search(r"\.urow > \*\{min-width:0;\}", LANDING), \
        "grid items can grow past their column again (min-width:auto)"
    ucount = re.search(r"\.ucount\{([^}]*)\}", LANDING).group(1)
    assert "nowrap" not in ucount, \
        ".ucount is nowrap again — that is what pushed the page sideways"


def test_location_data_stays_in_stripe_and_never_reaches_our_records() -> None:
    """The privacy policy makes an EXHAUSTIVE claim — email, roster, scoring,
    "that is everything we hold about you". Card country and billing postal
    code are visible in Stripe's dashboard (Stripe collects them to verify the
    card, whatever our checkout settings say), and reading them there is fine.
    Copying one into our own store would make that sentence false.

    So this pins both halves: the policy says where they live, and no code
    reads them off a Stripe customer.
    """
    whole = (SITE / "privacy.html").read_text(encoding="utf-8")
    privacy = html.unescape(prose(whole[whole.find("<body>"):]))
    assert re.search(r"country your card was\s+issued in", privacy, re.I), (
        "the policy no longer says what Stripe shows us about location")
    assert re.search(r"They stay in Stripe|never copied into our records", privacy, re.I)

    # And the code half. run/subscriptions.py is the only place a Stripe
    # customer object is read for anything other than metadata.
    source = (SITE.parent / "run" / "subscriptions.py").read_text(encoding="utf-8")
    reads = set(re.findall(r'customer\.get\("([a-z_]+)"', source))
    assert reads <= {"deleted", "email", "id", "metadata"}, (
        f"run/subscriptions.py now reads {sorted(reads)} off a Stripe customer "
        f"— anything beyond email/id/metadata contradicts the privacy policy's "
        f"'that is everything we hold about you'")
    for field in ("address", "shipping", "phone", "tax_ids"):
        assert f'customer.get("{field}")' not in source, (
            f"customer.{field} is being read into our own records")
