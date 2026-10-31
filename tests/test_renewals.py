"""The pre-renewal reminder — a promise kept, tested like a compliance surface.

Seven places on this site say some form of "we email you before it bills".
California's auto-renewal law requires the same thing for any term of a year
or longer, 15-45 days out, naming the renewal, the amount and how to cancel.
Until this existed the promise was made at the point of sale and kept
nowhere, which is deceptive from the first sale — so these tests treat the
content and the recipient rules as the obligation, not as copy.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

import pytest

import run.renewals as renewals
from render.renewal import (LEAD_MAX_DAYS, LEAD_MIN_DAYS, Renewal, due,
                            renewal_message)

TODAY = date(2027, 7, 1)


def _renewal(**over) -> Renewal:
    fields = {"email": "fan@example.com", "amount": "$39.00 USD",
              "renews_on": date(2027, 8, 1), "interval": "year"}
    fields.update(over)
    return Renewal(**fields)


RENEWS_ON = date(2027, 8, 1)


def _epoch(when: date) -> int:
    """The fixture derives its own timestamp. Hardcoding one had it claiming
    Aug 1 while actually encoding Aug 5 — the tests still passed, because the
    wrong date also fell inside the window, which is a test proving nothing
    about the boundary it names."""
    # Noon UTC: the renewal date is read on the buyer's clock (America/New_York,
    # EMAILS-112), and midnight UTC is the previous evening there.
    return calendar.timegm(when.timetuple()) + 12 * 3600


def _subscription(**over) -> dict:
    """A Stripe subscription in the shape the sweep reads."""
    row = {
        "id": "sub_1",
        "cancel_at_period_end": False,
        "current_period_end": _epoch(RENEWS_ON),
        "items": {"data": [{"price": {"unit_amount": 3900, "currency": "usd",
                                      "recurring": {"interval": "year"}}}]},
        "customer": {"id": "cus_1", "email": "fan@example.com"},
    }
    row.update(over)
    return row


@pytest.fixture
def stripe(monkeypatch):
    state: dict = {"subs": []}

    def _get(url, key):
        # Both status queries return the same page; the sweep dedupes by
        # nothing, so the fixture returns rows only for the first.
        if "status=active" in url:
            return {"data": state["subs"], "has_more": False}
        return {"data": [], "has_more": False}

    monkeypatch.setattr(renewals, "_stripe_get", _get)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    return state


# --------------------------------------------------------------------- #
# who gets one — the whole compliance surface
# --------------------------------------------------------------------- #

def test_the_window_is_the_statutory_one() -> None:
    """15 to 45 days. Earlier is not the notice the law describes; later is
    late."""
    renewal = _renewal(renews_on=date(2027, 8, 1))
    assert not due(renewal, date(2027, 7, 25)), "7 days out is late"
    assert due(renewal, date(2027, 7, 17)), "15 days out is inside"
    assert due(renewal, date(2027, 6, 17)), "45 days out is inside"
    assert not due(renewal, date(2027, 6, 1)), "61 days out is too early"
    assert LEAD_MIN_DAYS == 15 and LEAD_MAX_DAYS == 45


def test_a_subscription_set_to_cancel_is_never_told_it_will_renew(stripe) -> None:
    """It is ending, not renewing. 'We are about to charge you $39' is a false
    statement about somebody's money — the worst kind to send."""
    stripe["subs"] = [_subscription(cancel_at_period_end=True)]
    found, problems = renewals.upcoming("sk_test", TODAY)
    assert found == [] and problems == []


def test_a_monthly_subscription_gets_no_annual_notice(stripe) -> None:
    """Monthly bills monthly and stops on its own at season's end. The statute
    does not reach it, and the notice would describe a charge that is not
    coming in the form it describes."""
    monthly = _subscription()
    monthly["items"]["data"][0]["price"]["recurring"]["interval"] = "month"
    stripe["subs"] = [monthly]
    found, _ = renewals.upcoming("sk_test", TODAY)
    assert found == []


def test_an_unreadable_price_or_address_is_reported_not_guessed(stripe) -> None:
    """The amount is what will actually be charged. A subscriber
    renews at the price they joined at, which our own constants do not know,
    so a reminder we cannot price is one we do not send."""
    no_price = _subscription()
    no_price["items"]["data"][0]["price"]["unit_amount"] = None
    no_email = _subscription(customer={"id": "cus_2", "email": ""})
    stripe["subs"] = [no_price, no_email]
    found, problems = renewals.upcoming("sk_test", TODAY)
    assert found == []
    assert len(problems) == 2
    assert all("no notice sent" in p for p in problems)
    assert not any("@" in p for p in problems), "an address reached a log line"


def test_the_amount_and_date_come_from_stripe_not_from_our_constants(stripe) -> None:
    """A subscriber renewing at an older rate must see THAT rate, on
    the date Stripe will actually charge it."""
    stripe["subs"] = [_subscription()]
    stripe["subs"][0]["items"]["data"][0]["price"]["unit_amount"] = 2900
    found, _ = renewals.upcoming("sk_test", TODAY)
    assert found[0].amount == "$29.00 USD"
    assert found[0].renews_on == RENEWS_ON, \
        "the swept renewal date is not the one the fixture encodes"


# --------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------- #

def test_the_notice_carries_everything_the_statute_names(monkeypatch) -> None:
    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/x")
    message = renewal_message(_renewal())
    for doc in (message.html, message.text):
        assert "renews on August 1, 2027" in doc, "the date must be stated"
        assert "$39.00 USD" in doc, "the amount must be stated"
        assert re.search(r"cancel it yourself", doc, re.I)
        assert "billing.stripe.com/p/login/x" in doc
        assert re.search(r"cancel before that date and you are not charged",
                         doc, re.I)
        assert re.search(r"unsubscribing from emails alone", doc, re.I)
    assert "renews" in message.subject.lower()
    # What the statute names besides date and amount (launch audit L5): the
    # product, how often it renews, and a way to reach the business.
    assert "Beat Your League" in message.subject
    for doc in (message.html, message.text):
        assert "Beat Your League subscription" in doc and "once a year" in doc
        assert "hello@beatyourleague.com" in doc


def test_without_a_portal_the_notice_still_names_a_route(monkeypatch) -> None:
    monkeypatch.delenv("BILLING_PORTAL_URL", raising=False)
    monkeypatch.delenv("SITE_URL", raising=False)
    message = renewal_message(_renewal())
    assert "terms.html#cancel" in message.text
    assert "href" not in message.html.split("about a minute")[1].split(".")[0]


def test_the_notice_is_email_safe() -> None:
    html = renewal_message(_renewal()).html
    for construct in ("<style", "var(--", "display:grid", "display:flex",
                      "@media", "fonts.googleapis", "<link"):
        assert construct not in html


def test_one_notice_per_renewal_and_the_key_carries_no_address() -> None:
    """Keyed on the renewal DATE: a re-run inside the window sends nothing
    twice, and next year's renewal still gets its own notice rather than
    being suppressed as a duplicate. The send log is committed, so no address
    may ride in the key."""
    first = _renewal(renews_on=date(2027, 8, 1))
    again = _renewal(renews_on=date(2028, 8, 1))
    assert first.key == _renewal(renews_on=date(2027, 8, 1)).key
    assert first.key != again.key
    assert "@" not in first.key and "fan" not in first.key


# --------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------- #

def test_an_unconfigured_stripe_is_not_a_failure(monkeypatch, capsys) -> None:
    """Before checkout opens this is the expected state, and a daily cron that
    files a bug every morning teaches you to ignore bug issues."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert renewals.main([]) == renewals.NOT_CONFIGURED


def test_the_runner_sends_nothing_without_an_explicit_flag(stripe, capsys,
                                                           monkeypatch) -> None:
    """Every sender in this repo is dry by default; a misconfigured cron must
    not mail real people about money by accident."""
    sent: list = []
    monkeypatch.setattr(renewals, "send_all",
                        lambda msgs, **kw: sent.extend(msgs) or [])
    stripe["subs"] = [_subscription()]
    assert renewals.main(["--today", "2027-07-01"]) == 0
    assert sent == []
    assert "dry run" in capsys.readouterr().out


def test_a_new_season_does_not_re_welcome_everyone_who_ever_subscribed() -> None:
    """The key was welcome-{season}-{slug}, and `season` moves every August.
    The message set is `servable` — the projection of an append-only signup log
    that is never pruned and never entitlement-checked — so in Aug 2027 every
    2026 subscriber, INCLUDING people who cancelled, refunded, or were seats
    whose pass lapsed, would receive a fresh "here's what you bought and how to
    cancel" carrying $39/yr renewal terms.

    That email is the legally-owed ARL acknowledgment. Sending it to somebody
    with no subscription is a false statement about their money — the exact
    failure it exists to prevent. Keyed on the purchase now, so the same
    purchase is acknowledged once, ever. Found Aug 24 2026."""
    from render.welcome import welcome_message

    slug = "abcdef0123"
    first = welcome_message("fan@example.com", "season", slug, "2026",
                            purchased_at="1756000000")
    # The SAME purchase, a season later: same key, so the idempotent delivery
    # layer skips it rather than re-welcoming.
    next_year = welcome_message("fan@example.com", "season", slug, "2027",
                                purchased_at="1756000000")
    assert first.key == next_year.key, \
        "a new season re-welcomes every subscriber the product ever had"

    # A genuine RE-purchase is a different purchase and is acknowledged.
    resubscribed = welcome_message("fan@example.com", "season", slug, "2027",
                                   purchased_at="1788000000")
    assert resubscribed.key != first.key, \
        "a real second purchase must still get its acknowledgment"

    # With no purchase clock it falls back to the old behaviour rather than
    # collapsing every seat onto one key.
    seat_a = welcome_message("a@example.com", "seat", "1111111111", "2026")
    seat_b = welcome_message("b@example.com", "seat", "2222222222", "2026")
    assert seat_a.key != seat_b.key


# --------------------------------------------------------------------- #
# panel review, Oct 2026: which product, and who sent it
# --------------------------------------------------------------------- #

def test_the_notice_names_what_is_renewing(monkeypatch) -> None:
    """Reproduction (launch audit L5): Renewal carried no plan, so a $99
    League Pass payer's notice read "Your Beat Your League subscription" with
    nothing about the seats that ride on the charge — and nothing told them
    seats are claimed again with the new season's roster (LP-D5)."""
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS", raising=False)
    season = renewal_message(_renewal(plan="season"))
    payer = renewal_message(_renewal(plan="pass", amount="$99.00 USD"))
    for doc in (season.html, season.text):
        assert "Beat Your League season pass renews on August 1, 2027" in doc
        assert "every manager in your league" not in doc
    assert "season pass" in season.subject
    for doc in (payer.html, payer.text):
        assert "Beat Your League League Pass renews on August 1, 2027" in doc
        assert "$99.00 USD" in doc
        assert re.search(r"each claims their\s+seat again with their new roster", doc)
        assert re.search(r"every seat.{0,6}s\s+reports stop", doc)
    assert "League Pass" in payer.subject
    # The welcome's word for the payer reads the same.
    assert renewal_message(_renewal(plan="league_pass", amount="$99.00 USD")).text \
        == payer.text
    # A sweep that cannot tell names neither, rather than guessing.
    assert "subscription renews" in renewal_message(_renewal()).subject


def test_the_notice_says_who_sent_it(monkeypatch) -> None:
    """Reproduction (launch audit L3, GATE-9): rendered with
    SENDER_POSTAL_ADDRESS set, the weekly report printed the sender block and
    the renewal notice — the email about somebody's money — did not."""
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 123, Toronto ON M5V 1A1")
    message = renewal_message(_renewal(plan="season"))
    line = "Beat Your League · PO Box 123, Toronto ON M5V 1A1 · hello@beatyourleague.com"
    assert line in message.text and line in message.html
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS")
    bare = renewal_message(_renewal(plan="season"))
    assert "PO Box" not in bare.text and "None" not in bare.text


def test_the_sweep_names_the_plan_from_the_link_that_took_the_money(stripe) -> None:
    """The notice says "League Pass" or "season pass" only when the plan the
    intake stamped on the Customer (from the payment link, never a ref) says
    so (launch audit L5). Before, the sweep never passed a plan, so every
    notice said "your subscription" — including a $99 pass whose notice has
    to explain what happens to the league's seats. An unknown or missing
    stamp names neither, rather than guess."""
    stripe["subs"] = [
        _subscription(id="sub_pass", customer={
            "id": "cus_p", "email": "commish@example.com",
            "metadata": {"byl_plan": "league_pass"}}),
        _subscription(id="sub_season", customer={
            "id": "cus_s", "email": "fan@example.com",
            "metadata": {"byl_plan": "season"}}),
        _subscription(id="sub_odd", customer={
            "id": "cus_o", "email": "odd@example.com",
            "metadata": {"byl_plan": "monthly"}}),
        _subscription(id="sub_none", customer={
            "id": "cus_n", "email": "none@example.com"}),
    ]
    found, _ = renewals.upcoming("sk_test", TODAY)
    plans = {r.email: r.plan for r in found}
    assert plans == {"commish@example.com": "pass", "fan@example.com": "season",
                     "odd@example.com": None, "none@example.com": None}
