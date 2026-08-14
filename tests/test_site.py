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


def test_free_watch_list_exists_and_promises_unsubscribe() -> None:
    """The non-buyer off-ramp: waiting on the record must be possible."""
    assert 'id="watch-form"' in LANDING
    assert re.search(r"unsubscribe in one click", LANDING, re.I)
    assert re.search(r"no card", LANDING, re.I)


def test_paid_from_day_one_is_stated_not_hidden() -> None:
    assert re.search(r"no free tier", LANDING_PROSE, re.I)
    assert re.search(r"paid product from day one", JOIN_PROSE, re.I)


def test_price_appears_only_at_decision_points_and_renewal_terms() -> None:
    """Four rendered $29s, each load-bearing: the pricing card, the reservation
    step, and the two renewal disclosures (a renewal notice that omits the
    amount is not a disclosure). Anything beyond this is ambient repetition,
    which pushes cost evaluation ahead of value. (A further mention lives in the
    checkout script, which only ever replaces the button's own text.)"""
    rendered = markup_only(LANDING)
    assert rendered.count("$29") == 4, "landing page price mentions drifted"
    renewal_mentions = len(re.findall(r"renews? (?:once a year )?at \$29", rendered, re.I))
    assert renewal_mentions == 2, "renewal disclosures must state the amount"


# --------------------------------------------------------------------- #
# honesty of the live scouting demo
# --------------------------------------------------------------------- #

def test_scout_screen_labels_its_source_and_season() -> None:
    """A number shown to a buyer must name where and when it came from."""
    assert "scoutRival" in JOIN
    assert re.search(r"leagueRaw && leagueRaw\.season", JOIN), \
        "season label must come from the league actually read, not the page default"
    assert not re.search(r"let season = String\(SEASON\)", JOIN), \
        "season must never default to the page constant when data was read"
    assert re.search(r"straight from your league's record on Sleeper", JOIN_PROSE, re.I)
    assert re.search(r"did not model or estimate", JOIN_PROSE, re.I)


def test_scout_screen_has_an_honest_empty_state() -> None:
    assert re.search(r"nothing to scout", JOIN_PROSE, re.I)
    assert re.search(r"rather show you nothing than invent", JOIN_PROSE, re.I)


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
    assert re.search(r"const REF_RE = /\^\[A-Za-z0-9_-\]\{1,200\}\$/", JOIN), \
        "the ref must be checked against Stripe's documented charset and length"
    assert re.search(r"if \(!REF_RE\.test\(ref\)\)", JOIN), \
        "the ref must be tested before navigating to checkout"


def test_an_individual_signup_is_never_posted_anywhere() -> None:
    """Individual buyers go browser -> Stripe. Only League Pass seats (who have
    no payment to ride) touch a form backend, so a vendor outage costs seats,
    never sales."""
    handler = JOIN.split('$("submit").addEventListener')[1]
    seat_branch, individual_branch = handler.split("--- Individual buyer")
    assert "FORM_ENDPOINT" not in individual_branch, \
        "the individual checkout path must not depend on a form backend"
    assert "FORM_ENDPOINT" in seat_branch


def test_no_payment_details_are_collected_by_us() -> None:
    """Card data must live entirely with Substack/Stripe (CLAUDE.md security)."""
    for page in (LANDING, JOIN):
        assert not re.search(r'type="(card|cc-number|creditcard)"', page, re.I)
        assert not re.search(r'autocomplete="cc-', page, re.I)
    assert re.search(r"never touch our systems", JOIN, re.I)


def test_join_collects_only_the_stated_minimum() -> None:
    inputs = re.findall(r'<input[^>]*type="([a-z]+)"', JOIN)
    assert set(inputs) <= {"text", "email"}, f"unexpected input types: {inputs}"
    assert re.search(r"never a password", JOIN, re.I)


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
    assert re.search(r"your picks aren't saved", JOIN_PROSE, re.I), \
        "the not-open path must admit the picks were not stored"
    assert re.search(r"isn't open just yet", JOIN_PROSE, re.I)


def test_scout_has_an_in_flight_guard() -> None:
    """Rapid re-picks must not render stale data under the new rival's name."""
    assert "scoutGen" in JOIN
    assert re.search(r"if \(gen !== scoutGen\) return;", JOIN)


def test_scout_distinguishes_unread_history_from_no_history() -> None:
    """A failed lookup must never be rendered as an absence of games."""
    assert "unread" in JOIN
    assert re.search(r"couldn't read this league's earlier seasons", JOIN_PROSE, re.I)


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
]


@pytest.mark.parametrize("name", ["sample report", "landing", "join"])
def test_no_developer_vocabulary_in_buyer_copy(name: str) -> None:
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
    public = {
        "landing": LANDING, "join": JOIN, "ledger": LEDGER,
        "sample report": SAMPLE_REPORT,
        "backtest": (SITE / "backtest.html").read_text(encoding="utf-8"),
        "legal": (SITE / "legal.html").read_text(encoding="utf-8"),
    }
    for page_name, page in public.items():
        for person in names:
            assert person not in page, f"{person!r} is named on the public {page_name} page"


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
    """An unlabelled '$29' is ambiguous to a buyer and a support burden."""
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
    assert re.search(r"other teams can cover that|nobody else in your league can even cover",
                     SAMPLE_REPORT, re.I)
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
