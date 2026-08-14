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
    for page, name in ((LANDING, "landing"), (JOIN, "join")):
        assert re.search(r'const SUBSTACK_URL = ""', page), \
            f"{name} page lost its checkout wiring slot"


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
    handler = LANDING.split("const watchForm")[1].split("if (SUBSTACK_URL)")[0]
    assert "SUBSTACK_URL" not in handler, \
        "free ledger signup must not navigate to the paid checkout constant"
    assert "LEDGER_FREE_URL" in handler


def test_reservation_claim_is_conditional_on_being_recorded() -> None:
    """Nothing may be declared 'reserved' when nothing recorded it."""
    assert 'id="done-head"' in JOIN
    assert re.search(r"your spot is held once you send this", JOIN_PROSE, re.I)


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
# no betting positioning anywhere buyer-facing (principle 4)
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("page,name", [(LANDING, "landing"), (JOIN, "join"), (LEDGER, "ledger")])
def test_no_betting_language(page: str, name: str) -> None:
    banned = r"\b(parlay|sportsbook|against the spread|bet now|odds boost|wager)\b"
    assert not re.search(banned, page, re.I), f"betting language crept into {name}"
