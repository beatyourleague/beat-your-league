"""2026's one-time passes (owner decision, Oct 18 2026).

The $29 Rest-of-Season Pass, the $19 Playoff Pass and the $69 League Pass are
Payment Links in payment mode: one payment, nothing renews. A purchase is named
by its PaymentIntent (pi_...) wherever a subscription id (sub_...) is, so the
entitlement, seat and refund rules (RULE E1/E2) apply unchanged."""
from datetime import datetime, timezone

import pytest

import run.intake as intake
from run import subscriptions
from run.rosters import RosterRegistryError, RosterSubscriber, _subscription_ids
from render.report import (ONCE, ONCE_END, ONCE_STOP_BODY, cancel_html, cancel_lines,
                           season_end_lines, stop_route, unsubscribe_target)
from render.welcome import welcome_message
from tests.test_promises_billing import REF, _session, _sweep

PAID = int(datetime(2026, 10, 20, 15, tzinfo=timezone.utc).timestamp())
ENDS = {"2026": "2027-01-10", "2027": "2028-01-09"}


def test_a_payment_mode_session_is_named_by_its_payment_intent(monkeypatch) -> None:
    once = _session(subscription=None, mode="payment", payment_intent="pi_aaaa1111")
    signups, _, problems = _sweep(monkeypatch, [once])
    assert problems == [] and [s.subscription_id for s in signups] == ["pi_aaaa1111"]
    # A subscription still wins when there is one.
    assert intake._subscription_id(_session()) == "sub_aaaa1111"


def test_a_one_time_league_pass_can_carry_seats(monkeypatch) -> None:
    """A pass that 'started no subscription' was refused seats; a one-time
    pass names its payment, which is what seats are entitled through."""
    once = _session(link="plink_P", subscription=None, mode="payment",
                    payment_intent={"id": "pi_bbbb2222"})
    signups, _, problems = _sweep(monkeypatch, [once], plans={"plink_P": "league_pass"})
    assert problems == [] and signups[0].pass_of == "pi_bbbb2222"


def test_rows_accept_a_payment_id_and_know_they_never_renew() -> None:
    assert _subscription_ids(["pi_aaaa1111"], "season", "x") == ("pi_aaaa1111",)
    with pytest.raises(RosterRegistryError):
        _subscription_ids(["in_aaaa1111"], "season", "x")
    row = RosterSubscriber(email="a@example.com", ref=REF, player_ids=(), slots=(),
                           scoring="ppr", subscription_ids=("pi_aaaa1111",))
    assert row.one_time
    assert not RosterSubscriber(email="a@example.com", ref=REF, player_ids=(), slots=(),
                                scoring="ppr", subscription_ids=("sub_aaaa1111",)).one_time


def _sessions_page(*rows):
    return {"data": list(rows), "has_more": False}


def _paid(pi, refunded=False, created=PAID, email="fan@example.com", mode="payment"):
    charge = {"amount": 2900, "amount_refunded": 2900 if refunded else 0,
              "refunded": refunded}
    return {"id": "cs_" + pi, "mode": mode, "payment_status": "paid", "created": created,
            "customer_details": {"email": email},
            "payment_intent": {"id": pi, "latest_charge": charge}}


def test_one_time_entitlement_follows_the_payment_and_the_season(monkeypatch) -> None:
    rows = [_paid("pi_live1111"), _paid("pi_refd1111", refunded=True),
            _paid("pi_subs1111", mode="subscription")]
    monkeypatch.setattr(subscriptions, "_stripe_get", lambda url, key: _sessions_page(*rows))
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    ids, emails, refunded = subscriptions._one_time_purchases("sk", now=now, season_ends=ENDS)
    assert ids == {"pi_live1111"} and emails == {"fan@example.com"}
    assert refunded == ["pi_refd1111"]
    # The season it was sold for has ended (plus the retry grace): no longer entitled.
    later = datetime(2027, 1, 25, tzinfo=timezone.utc)
    assert subscriptions._one_time_purchases("sk", now=later, season_ends=ENDS)[0] == set()


def test_a_one_time_pass_is_entitled_through_its_own_season_only() -> None:
    until = subscriptions.one_time_entitled_until(PAID, ENDS)
    assert until.isoformat() == "2027-01-24"            # last game + 14 days
    # Never into next September: the 2027 season is a new purchase.
    assert until < datetime(2027, 9, 1).date()


def test_a_one_time_report_footer_says_there_is_nothing_to_cancel() -> None:
    meta = {"plan": "season", "one_time": True}
    assert stop_route(meta) == ONCE
    from html import escape
    assert escape(ONCE_STOP_BODY) in cancel_html(ONCE) and "billing page" not in cancel_html(ONCE)
    assert ONCE_STOP_BODY in cancel_lines(ONCE)[0]
    assert unsubscribe_target(ONCE).startswith("mailto:")
    assert stop_route({"plan": "season"}) is False         # a subscription: billing page


def test_the_last_report_of_a_one_time_pass_names_no_renewal() -> None:
    meta = {"solo": True, "week": 18, "last_week": 18, "plan": "season", "one_time": True}
    text = " ".join(season_end_lines(meta))
    assert ONCE_END in text and "renews" not in text.replace("nothing renews", "")


def test_the_welcome_for_a_one_time_pass_states_it_and_offers_the_stop_route() -> None:
    msg = welcome_message("a@example.com", "season", "abcdef0123", "2026", one_time=True)
    assert "nothing renews" in msg.text and "renews once a year" not in msg.text
    assert ONCE_STOP_BODY in msg.text
    league = welcome_message("p@example.com", "league_pass", "abcdef0123", "2026", one_time=True)
    assert "rest of this season" in league.text and "renews once a year" not in league.text
