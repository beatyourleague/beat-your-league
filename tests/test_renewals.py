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
    return calendar.timegm(when.timetuple())


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
    """The amount is what will actually be charged. A founding subscriber
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
    """A founding subscriber renewing at a locked rate must see THAT rate, on
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


def test_without_a_portal_the_notice_still_names_a_route(monkeypatch) -> None:
    monkeypatch.delenv("BILLING_PORTAL_URL", raising=False)
    monkeypatch.delenv("SITE_URL", raising=False)
    message = renewal_message(_renewal())
    assert "legal page" in message.text
    assert "href" not in message.html.split("fifteen")[1].split(".")[0]


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
