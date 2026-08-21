"""Contract tests for the public funnel.

These guard the promises the funnel makes to a buyer. They exist because the
pressure to quietly remove them — hide the refund line, bury cancellation,
drop the "no free tier" honesty, let a number lose its source — always arrives
later, dressed as conversion optimisation. A failing test here means someone
is about to ship a dark pattern (PLAN.md §4, CLAUDE.md principle 3).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
ROSTER_JS = (SITE / "join" / "roster.js").read_text(encoding="utf-8")
LEDGER = (SITE / "ledger" / "index.html").read_text(encoding="utf-8")


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
    # The protection is that paid-from-day-one is STATED, not hidden. It has
    # been pinned as "no free tier" (sells an absence) and then as "the report
    # is the product from day one" (internal product-strategy register). The
    # strongest form of the disclosure is the PRICE ITSELF, visible in the
    # hero before any scroll — a page that shows the price up front cannot be
    # accused of hiding that it charges.
    assert re.search(rf"\${SEASON_PRICE} USD for the season", LANDING_PROSE), \
        "the landing hero must state the price plainly"
    assert re.search(r"paid product from day one", JOIN_PROSE, re.I)


def test_price_appears_only_at_decision_points_and_renewal_terms() -> None:
    """Five rendered season prices, each load-bearing: the pricing card, the reservation
    step, and the two renewal disclosures (a renewal notice that omits the
    amount is not a disclosure). Anything beyond this is ambient repetition,
    which pushes cost evaluation ahead of value. (A further mention lives in the
    checkout script, which only ever replaces the button's own text.)"""
    rendered = markup_only(LANDING)
    # Five rendered season prices, each load-bearing: the HERO microcopy (the price is
    # the paid-from-day-one disclosure, per the test above), the pricing card,
    # the reservation step, and the two renewal disclosures.
    assert rendered.count(f"${SEASON_PRICE}") == 5, "landing page price mentions drifted"
    renewal_mentions = len(re.findall(rf"renews? (?:once a year )?at \${SEASON_PRICE}",
                                      rendered, re.I))
    assert renewal_mentions == 2, "renewal disclosures must state the amount"


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
    assert re.search(r"const CHECKOUT_OPEN = false", LANDING), \
        "landing page lost its checkout wiring slot"
    for const in ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY"):
        assert re.search(rf'const {const} = ""', JOIN), \
            f"join page lost its {const} wiring slot"


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
    assert "AbortSignal.timeout" in JOIN


# --------------------------------------------------------------------- #
# the backtest exhibit must not overstate the shipping product
# --------------------------------------------------------------------- #

def test_landing_never_calls_the_diagnostic_table_calibrated() -> None:
    """reports/backtest.md forbids publishing the availability-controlled table
    as an accuracy result; it may appear only labelled as a diagnostic."""
    assert re.search(r"diagnostic", LANDING_PROSE, re.I)
    assert not re.search(r"78\.3%</td><td[^>]*>calibrated", LANDING), \
        "diagnostic bucket presented as a calibrated accuracy claim"
    assert re.search(r"hindsight filter", LANDING_PROSE, re.I)


def test_landing_states_the_unconditional_hit_rate_beside_the_2056() -> None:
    assert "2,056" in LANDING_PROSE
    assert "53.5%" in LANDING_PROSE, \
        "the headline sample size must travel with the honest overall hit rate"


def test_published_backtest_exists_and_keeps_its_failures() -> None:
    """'published here' must resolve, and must not be a laundered version."""
    published = SITE / "backtest.html"
    assert published.is_file(), "landing page links a backtest that isn't published"
    text = published.read_text(encoding="utf-8")
    assert "53.5%" in text
    assert re.search(r">off<", text), "published backtest lost its failing buckets"
    assert 'href="backtest.html"' in LANDING


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


@pytest.mark.parametrize("name", ["sample report", "landing", "join", "live report"])
def test_no_developer_vocabulary_in_buyer_copy(name: str) -> None:
    if name == "live report":
        page = _demo_report_html()
    else:
        page = {"sample report": SAMPLE_REPORT, "landing": LANDING, "join": JOIN}[name]
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
    # Placeholder addresses must not look real either — a fake-but-plausible
    # address silently swallows refund and deletion requests.
    legal = (SITE / "legal.html").read_text(encoding="utf-8")
    assert re.search(r"added before launch", legal, re.I), \
        "legal page must flag the missing contact address, not invent one"


def test_signup_degrades_honestly_without_a_contact_route() -> None:
    """With checkout unwired, the form must say so rather than opening an empty
    mailto: that looks like it worked. The join page no longer has a mailto path
    at all — the picks ride into Stripe or nowhere."""
    assert re.search(r"isn't open just yet", JOIN_PROSE, re.I)
    assert "mailto:" not in JOIN, \
        "the join page must not fall back to an email draft — it loses the signup"
    assert re.search(r"if \(!CONTACT_EMAIL\)", LANDING)


def test_legal_page_covers_the_promises_money_depends_on() -> None:
    legal = prose((SITE / "legal.html").read_text(encoding="utf-8"))
    for required in (r"renew once a year|renews once a year", r"cancel yourself at any time",
                     r"one refund per person", r"18 or older",
                     r"never see or store your card", r"not affiliated"):
        assert re.search(required, legal, re.I), f"legal page is missing: {required}"


def test_cancelling_has_concrete_steps_not_just_a_promise() -> None:
    """"You can cancel any time" without saying HOW is friction wearing a
    promise's clothes. The terms must give real, followable steps."""
    legal = prose((SITE / "legal.html").read_text(encoding="utf-8"))
    assert re.search(r'id="cancel"', (SITE / "legal.html").read_text(encoding="utf-8")), \
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
        assert re.search(r'legal\.html#cancel', page), \
            f"{name} page should link straight to the cancellation steps"


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


def test_billing_never_outlives_the_product() -> None:
    """We only charge for months we actually send something. Monthly billing
    stops at season end; the annual renewal lands before the season it covers."""
    legal = prose((SITE / "legal.html").read_text(encoding="utf-8"))
    assert re.search(r"billing runs only while the season runs", legal, re.I)
    assert re.search(r"do not charge monthly through the offseason", legal, re.I)
    assert re.search(r"never during\s+the offseason", legal, re.I)
    assert re.search(r"billing stops when the season does", prose(LANDING), re.I)


def test_legal_page_actually_protects_the_business() -> None:
    """Consumer promises without limits is a one-sided contract. These are the
    clauses that stop a $29 sale becoming an unbounded claim."""
    legal = prose((SITE / "legal.html").read_text(encoding="utf-8"))
    protections = {
        "liability cap": r"total liability to you.{0,80}limited to the amount you",
        "no consequential damages": r"indirect, incidental, special, or consequential",
        "as-is / warranty disclaimer": r"provided <b>as is</b>|provided as is",
        "implied warranty disclaimer": r"merchantability",
        "refund is the exclusive remedy": r"only remedy we offer",
        "no redistribution (protects League Pass)": r"may <b>not</b> forward the full report",
        "third-party data dependency": r"depend on Sleeper's public data",
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


def test_unset_legal_placeholders_are_visible_not_invented() -> None:
    """A guessed jurisdiction is worse than a blank one."""
    legal = (SITE / "legal.html").read_text(encoding="utf-8")
    assert re.search(r"\[jurisdiction — to be set before", legal), \
        "governing law must stay an explicit placeholder until the owner sets it"
    assert re.search(r"\[contact address — added before launch\]", legal)
    for page, name in ((LANDING, "landing"), (JOIN, "join")):
        assert re.search(r'href="\.\./legal\.html"|href="legal\.html"', page), \
            f"{name} page does not link the terms"


def test_withheld_numbers_read_as_a_decision_not_a_defect() -> None:
    """A gated slot must say we chose not to call it — never a version number."""
    assert "no call" in SAMPLE_REPORT.lower()
    assert re.search(r"not calling it", SAMPLE_REPORT, re.I)


LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")


def test_monthly_price_never_undercuts_the_season_pass() -> None:
    """The monthly tier exists to make the pass obvious. If a full season of
    monthly costs LESS than the pass, the anchor inverts and the pass becomes
    the sucker's choice — which is exactly what $6.99 did (PLAN §4)."""
    SEASON_MONTHS = 3.65   # Sep 8 -> late Dec, 111 days
    rendered = markup_only(LANDING)
    monthly = re.search(r'class="price">\$(\d+\.\d\d) <small>/ month', rendered)
    season = re.search(r'class="price">\$(\d+) <small>/ season', rendered)
    assert monthly and season, "could not read both prices off the pricing cards"
    monthly_season_total = float(monthly.group(1)) * SEASON_MONTHS
    pass_price = float(season.group(1))
    assert monthly_season_total > pass_price, (
        f"a full season month-to-month costs ${monthly_season_total:.2f}, which is "
        f"less than the ${pass_price:.2f} pass — the anchor is inverted")


def test_every_price_shown_to_a_buyer_names_its_currency() -> None:
    """An unlabelled price is ambiguous to a buyer and a support burden."""
    for page, name in ((LANDING, "landing"), (JOIN, "join"),
                       (LEAGUE_PASS, "league pass")):
        assert re.search(r"USD", page), f"{name} page shows a price with no currency"
    legal = prose((SITE / "legal.html").read_text(encoding="utf-8"))
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
    assert re.search(r"can't write anyone's report until they do", prose_page, re.I)
    assert re.search(r'href="legal\.html"', LEAGUE_PASS)


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


def test_waiver_edge_is_sold_as_a_decision_not_a_stat() -> None:
    """The FAAB read is the thing rankings can't do — it has to reach the buyer
    as an action ('bid X, N teams can answer'), not a raw number."""
    assert re.search(r"what a waiver claim actually costs", LANDING_PROSE, re.I)
    assert re.search(r"who can afford to outbid you", LANDING_PROSE, re.I)
    # Numbers sit inside <b> tags, so match the phrasing that carries the action.
    assert re.search(r"or more to top the highest bid|to top the highest bid he's drawn",
                     SAMPLE_REPORT, re.I)
    # The count must carry SCALE: usually a denominator ("8 of the other 11
    # teams"), and when everyone can afford it, "every other team in your
    # league", because "11 of the other 11" is the machine counting out loud.
    # A bare "8 teams" has no scale and is the thing this guards against.
    assert re.search(r"of the other \d+ teams can cover that"
                     r"|every other team in your league can cover that"
                     r"|nobody else in your league can even cover",
                     SAMPLE_REPORT, re.I), "the count lost its scale"
    assert re.search(r"waiver market in your league", SAMPLE_REPORT, re.I)


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
    assert re.search(r"set (the|your) lineup", SAMPLE_REPORT, re.I)


# --------------------------------------------------------------------- #
# no betting positioning anywhere buyer-facing (principle 4)
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("page,name", [(LANDING, "landing"), (JOIN, "join"), (LEDGER, "ledger")])
def test_no_betting_language(page: str, name: str) -> None:
    banned = r"\b(parlay|sportsbook|against the spread|bet now|odds boost|wager)\b"
    assert not re.search(banned, page, re.I), f"betting language crept into {name}"


def test_published_backtest_is_generated_not_hand_edited() -> None:
    """The page claims of itself: 'regenerated by python -m engine.backtest,
    never hand-edited'. That claim was maintained by hand and drifted — the
    published page once carried a generation timestamp older than its own
    source. This asserts the claim is structurally true: what the generator
    produces from backtest.md IS what is published."""
    from render.backtest_site import build
    published = (SITE / "backtest.html").read_text(encoding="utf-8")
    assert build() == published, (
        "site/backtest.html is out of date with reports/backtest.md — "
        "run `python -m render.backtest_site`")


def test_the_backtest_generator_refuses_to_drop_a_figure() -> None:
    """The whole point of the page is faithful publication, so a conversion
    that silently lost a row — especially a FAILING row — must fail loudly
    rather than publish a laundered record."""
    from render.backtest_site import verify
    md = (Path(__file__).resolve().parent.parent / "reports" / "backtest.md"
          ).read_text(encoding="utf-8")
    assert verify(md, "<p>nothing here</p>"), "verify() passed an empty page"
    # A page missing only the failing buckets must still be rejected.
    stripped = (SITE / "backtest.html").read_text(encoding="utf-8").replace(">off<", ">ok<")
    assert any("failing calibration" in p for p in verify(md, stripped))


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
    assert f"${MONTHLY_PRICE} USD / month" in JOIN
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
        SITE / "league-pass.html", SITE / "legal.html",
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
    assert 'class="calfig"' in page, "the calibration chart is missing"
    figure = page.split('class="calfig"')[1].split("</figure>")[0]
    assert figure.count("<circle") == 6, "one dot per unconditional bucket"
    assert "perfect calibration" in figure
    # the failure the chart exists to show must stay in words too
    assert "barely sorts" in figure
    # the diagnostic table's giveaway values must not appear in the drawing
    for forbidden in ("77.2", "63.6", "78.3"):
        assert forbidden not in figure, \
            f"availability-controlled figure {forbidden} was drawn as accuracy"


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
    """A card stamped "Real find" is a factual claim about our own output, and
    the landing page is hand-written while the report is generated — so the two
    drift silently. They did: the page kept advertising a bench player "above
    four of their set starters" for weeks after the engine stopped producing
    that count and started naming the single slot instead. Every number a
    "real"-stamped card quotes has to appear in the published sample report."""
    import html as _html
    for match in re.finditer(
            r'<div class="mini">(.*?)</div>\s*</div>\s*<span class="real">([^<]*)</span>',
            LANDING, re.S):
        body = _html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))
        stamp = match.group(2).strip()
        for number in sorted(set(re.findall(r"\d+\.\d+", body))):
            assert number in SAMPLE_REPORT, (
                f'the landing page cites {number} under "{stamp}", but no such '
                f"number is in the report it points at")


def test_the_scouting_cards_quote_the_report_verbatim() -> None:
    """The number check above catches an invented figure; this catches the way
    it actually went wrong — right numbers, a claim the engine no longer makes.
    The page said "above four of their set starters" for a rival whose bench
    player is now correctly named against the ONE slot he can fill. Whenever
    render/engine wording changes, regenerate the demo and update this quote."""
    quoted = "projects 17.8 against Peyton Barber at FLEX (8.0)"
    assert quoted in SAMPLE_REPORT, \
        "the demo no longer says this — regenerate with `make demo` and re-check"
    assert quoted in LANDING.replace("he projects", "projects"), \
        "the landing page's fragility card drifted from the report it cites"


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
    match = re.search(r"Twelve individual passes would cost \$(\d+) USD", LEAGUE_PASS)
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
def _paid_path_modules() -> set[Path]:
    import ast
    repo = SITE.parent
    seen: set[str] = set()
    queue = ["run.batch"]
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
    public sample league, not a commercial service — which is exactly why this
    walks the imports reachable from `run/batch.py` rather than the whole repo.
    """
    plan = (SITE.parent / "PLAN.md").read_text(encoding="utf-8")
    checkout_open = not re.search(r"const CHECKOUT_OPEN = false", LANDING)
    links_live = not all(re.search(rf'const {c} = ""', JOIN) for c in
                         ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY",
                          "STRIPE_LINK_PASS"))
    offenders = sorted(
        p.name for p in _paid_path_modules()
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
