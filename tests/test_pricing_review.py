"""The pricing review (owner decision, Oct 31 2026): the prices held, and four
things they rested on were made true.

- no plan renews after Week 16's report, and every report still arrives;
- every sentence about billing says so, in words true of a late buyer too;
- one price for everyone: no founding rate and no 2027 price on any page;
- the compare page says what was checked, and when;
- the free report opens with checkout.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from infra import stripe_paylink_text as paylink
from render import welcome
from run import billing, economics, launch_check
from run.billing import last_charge_send, needs_stop
from run.subscriptions import SEASON_STOP_KEY, stopped_for_season

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
CACHE = ROOT / "data" / "raw" / "nflverse"
needs_schedule = pytest.mark.skipif(not (CACHE / "games.csv").is_file(),
                                    reason="no cached nflverse schedule (data/ is gitignored)")
CHARGE_DUE = datetime(2026, 12, 22, 12, 17, tzinfo=timezone.utc)


def _page(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def _words(page: str) -> str:
    """What a reader gets, script-built text included: only tags and CSS go."""
    text = re.sub(r"<style.*?</style>", " ", page, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _plan(period_end: datetime) -> dict:
    return {"id": "sub_1", "status": "active", "cancel_at": None,
            "cancel_at_period_end": False,
            "customer": {"id": "cus_1", "metadata": {billing.ROSTER_METADATA_KEY: "r3-mc-x"}},
            "items": {"data": [{"price": {"recurring": {"interval": "month"}},
                                "current_period_end": int(period_end.timestamp())}]}}


# --------------------------------------------------------------------- #
# no plan renews after Week 16's report
# --------------------------------------------------------------------- #

@needs_schedule
def test_the_cutoff_is_week_16s_tuesday() -> None:
    assert last_charge_send(CACHE, "2026") == date(2026, 12, 22)


def test_a_renewal_landing_on_christmas_eve_never_happens() -> None:
    """The case that moved it: a Nov 24 buyer's second charge landed Dec 24,
    with two reports left and the refund window long closed."""
    due, notes = needs_stop([_plan(datetime(2026, 12, 24, 15, tzinfo=timezone.utc))], CHARGE_DUE)
    assert [s["id"] for s in due] == ["sub_1"] and not notes


def test_the_last_renewal_lands_before_week_16s_report() -> None:
    due, _ = needs_stop([_plan(datetime(2026, 12, 17, 15, tzinfo=timezone.utc))], CHARGE_DUE)
    assert due == []


def test_a_week_later_never_costs_half_as_much() -> None:
    """Before: $29.98 for seven reports on Nov 24, $14.99 for six on Dec 1."""
    stop = date(2026, 12, 22)
    assert economics.monthly_charges(date(2026, 11, 24), stop)[0] == 1
    assert economics.monthly_charges(date(2026, 12, 1), stop)[0] == 1
    assert economics.monthly_charges(date(2026, 11, 17), stop)[0] == 2


def test_the_model_and_the_billing_run_agree_on_the_week() -> None:
    assert economics.LAST_CHARGE_WEEK == billing.LAST_CHARGE_WEEK
    assert economics.report_tuesday(economics.LAST_CHARGE_WEEK) == date(2026, 12, 22)


@pytest.mark.parametrize("when", [
    datetime(2026, 12, 29, 16, tzinfo=timezone.utc),    # Week 17's Tuesday
    datetime(2027, 1, 5, 16, tzinfo=timezone.utc),      # Week 18's Tuesday
    datetime(2027, 1, 9, 17, tzinfo=timezone.utc),      # Week 18's Saturday check
])
def test_the_earliest_plan_we_stop_keeps_every_report(when) -> None:
    """A stop written at Week 16 would have cost a Nov 23 buyer Week 18 under
    the old two weeks, while the terms promise reports to the season's last."""
    ended = int((CHARGE_DUE + timedelta(minutes=1)).timestamp())
    plan = {"status": "canceled", "ended_at": ended, "metadata": {SEASON_STOP_KEY: "1"}}
    assert stopped_for_season(plan, when)


# --------------------------------------------------------------------- #
# the sentences about billing
# --------------------------------------------------------------------- #

BUYER_TEXTS = {
    **{f"site/{p.relative_to(SITE)}": _words(p.read_text(encoding="utf-8"))
       for p in SITE.rglob("*.html")},
    "Stripe monthly": paylink.MESSAGES["monthly"],
    "Stripe league": paylink.MESSAGES["league_pass"],
    "Stripe box monthly": paylink.TOS_MESSAGES["monthly"],
    "Stripe box league": paylink.TOS_MESSAGES["league_pass"],
    "welcome": welcome.BILLING_STOPS,
}


@pytest.mark.parametrize("name", sorted(BUYER_TEXTS))
def test_no_surface_promises_nothing_is_charged_after_a_report(name) -> None:
    """A buyer after Week 16's report still pays once, at purchase, so "nothing
    is charged after" would be false of them. "Won't renew" is true of everyone."""
    text = BUYER_TEXTS[name]
    assert not re.search(r"nothing is charged after", text, re.I), name
    assert not re.search(r"(charged|renew\w*|bill\w*)[^.]{0,60}Week 17", text, re.I), name


@pytest.mark.parametrize("words", [
    paylink.MESSAGES["monthly"], paylink.MESSAGES["league_pass"], welcome.BILLING_STOPS,
    _words(_page("join/index.html")),
])
def test_the_rule_comes_with_what_still_arrives(words) -> None:
    assert "won't renew after Week 16's report goes out" in words
    assert "still run through the season's last week" in words


def test_the_contract_says_it_plainly() -> None:
    terms = _words(_page("terms.html"))
    assert "it does not renew after Week 16's report goes out" in terms
    assert "still run through the season's last weekly report, at no further charge" in terms


@pytest.mark.parametrize("name", ["league-pass.html", "thanks.html"])
def test_the_pages_after_the_price_say_it_too(name) -> None:
    assert "won't renew after Week 16's report" in _words(_page(name))


def test_the_box_a_buyer_ticks_names_the_same_report() -> None:
    for plan in ("monthly", "league_pass"):
        assert "stops renewing after Week 16's report" in paylink.TOS_MESSAGES[plan]


def test_how_it_ends_opens_the_clause_it_means() -> None:
    assert '<a href="terms.html#price">how it ends</a>' in _page("index.html")
    assert '<h2 id="price">3. Price, renewal and cancelling</h2>' in _page("terms.html")


def test_the_card_still_links_straight_to_the_cancellation_steps() -> None:
    assert '<a class="stamp50" href="terms.html#cancel">Cancel any time</a>' in _page("index.html")


# --------------------------------------------------------------------- #
# one price for everyone, and no 2027 price promised
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("name", sorted(BUYER_TEXTS))
def test_no_surface_promises_a_founding_rate(name) -> None:
    """Dropped the day after it went up: two prices needed a private link, a
    way to spot a past buyer, and an answer to how long the rate lasted, and it
    forced Monthly up. Nobody had bought, so it cost nothing to remove."""
    assert not re.search(r"founding|new buyers (will )?pay", BUYER_TEXTS[name], re.I), name


def test_the_contract_names_no_2027_price() -> None:
    terms = _words(_page("terms.html"))
    assert "$39" not in terms and "$49" not in terms
    assert "We may change prices for future terms" in terms


def test_the_last_report_promises_no_price() -> None:
    from render.report import ONCE_END, SEASON_END_BILLING
    for words in (ONCE_END, SEASON_END_BILLING["monthly"], SEASON_END_BILLING["pass"]):
        assert "2027" not in words and "$39" not in words


def test_the_working_2027_plan_keeps_the_ladder() -> None:
    """Three charges (the elimination cliff) must pass the season pass, and at
    today's prices they do, so nothing had to move."""
    assert 3 * economics.MONTHLY > economics.SEASON


# --------------------------------------------------------------------- #
# the compare page
# --------------------------------------------------------------------- #

def _row(name: str) -> str:
    page = _page("compare/index.html")
    return re.search(rf"<tr><td>{re.escape(name)}.*?</tr>", page, re.S).group(0)


def test_footclan_is_priced_as_its_own_page_prices_it() -> None:
    """$11.99 is its top tier on annual billing only."""
    row = _row("Fantasy Footballers UDK")
    assert "FootClan membership $4.99–$15.99/mo" in row and "$11.99" not in row


def test_stacked_is_not_criticised_for_hiding_a_price_it_publishes() -> None:
    row = _row("STACKED")
    assert "$19.99 USD/mo" in row and "$4.99/mo billed annually" in row
    assert "Not published" not in row and "create an account" not in row


def test_the_stamp_names_what_was_rechecked_and_keeps_the_old_date_for_the_rest() -> None:
    page = _words(_page("compare/index.html"))
    assert "Prices checked Aug 22, 2026 · FantasyPros, Draft Sharks, FootClan and STACKED " \
           "rechecked Oct 31, 2026" in page


# --------------------------------------------------------------------- #
# the free report opens with checkout
# --------------------------------------------------------------------- #

GATE = "The free report opens with checkout"


def _gate(monkeypatch, can: str, trial: str) -> str:
    real = launch_check.js_constants

    def constants(source: str) -> dict:
        found = dict(real(source))
        found.update(CHECKOUT_CAN_COMPLETE=can, TRIAL_OPEN=trial)
        return found

    monkeypatch.setattr(launch_check, "js_constants", constants)
    return next(g.status for g in launch_check.check_funnel_config() if g.name == GATE)


@pytest.mark.parametrize("can,trial,status", [
    ("true", "false", "FAIL"),
    ("true", "true", "PASS"),
    ("false", "false", "PASS"),
])
def test_checkout_cannot_open_with_the_free_door_shut(monkeypatch, can, trial, status) -> None:
    assert _gate(monkeypatch, can, trial) == status
