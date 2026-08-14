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
    """With no form backend and no inbox, the form must say signups aren't open
    rather than opening an empty mailto: that looks like it worked."""
    assert re.search(r"Signups aren't open just yet", JOIN_PROSE, re.I)
    assert re.search(r"if \(!CONTACT_EMAIL\)", JOIN)
    assert re.search(r"if \(!CONTACT_EMAIL\)", LANDING)


def test_legal_page_covers_the_promises_money_depends_on() -> None:
    legal = prose((SITE / "legal.html").read_text(encoding="utf-8"))
    for required in (r"renews once a year", r"cancel yourself at any time",
                     r"one refund per person", r"18 or older",
                     r"never see or store your card", r"not affiliated"):
        assert re.search(required, legal, re.I), f"legal page is missing: {required}"
    for page, name in ((LANDING, "landing"), (JOIN, "join")):
        assert re.search(r'href="\.\./legal\.html"|href="legal\.html"', page), \
            f"{name} page does not link the terms"


def test_withheld_numbers_read_as_a_decision_not_a_defect() -> None:
    """A gated slot must say we chose not to call it — never a version number."""
    assert "no call" in SAMPLE_REPORT.lower()
    assert re.search(r"not calling it", SAMPLE_REPORT, re.I)


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
