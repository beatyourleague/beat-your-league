"""The welcome email — the legally-owed acknowledgment, tested like one.

California's auto-renewal law requires a retainable post-purchase notice with
the renewal terms and the cancellation method; Stripe's receipt covers the
charge but not our cancel route. So these tests treat the email's content as a
compliance surface, not copy: the amount must match what was actually bought,
the cancel destination must resolve, and the whole thing must survive real
email clients.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from render.welcome import (MONTHLY_PRICE, PASS_PRICE, SEASON_PRICE,
                            welcome_message)

SITE = Path(__file__).resolve().parent.parent / "site"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("BILLING_PORTAL_URL", raising=False)
    monkeypatch.delenv("SITE_URL", raising=False)


def _msg(plan: str = "season"):
    return welcome_message("fan@example.com", plan, "abc123def0", "2026")


# --------------------------------------------------------------------- #
# the disclosures match the purchase
# --------------------------------------------------------------------- #

def test_the_season_welcome_carries_its_renewal_terms() -> None:
    msg = _msg("season")
    for doc in (msg.html, msg.text):
        assert f"{SEASON_PRICE} USD" in doc
        assert re.search(r"renews once a year", doc, re.I)
        assert re.search(r"email you before it bills", doc, re.I)
        assert re.search(r"one per person", doc, re.I)
        assert re.search(r"cancel", doc, re.I)
        assert re.search(r"unsubscribing from emails alone", doc, re.I), \
            "stopping emails and stopping billing must be distinguished"


def test_the_monthly_welcome_never_claims_an_annual_renewal() -> None:
    """Monthly bills monthly and stops at season's end. Telling a monthly
    buyer their plan 'renews once a year' would be a false disclosure."""
    msg = _msg("monthly")
    for doc in (msg.html, msg.text):
        assert f"{MONTHLY_PRICE} USD" in doc
        assert SEASON_PRICE + " USD" not in doc
        assert not re.search(r"renews once a year", doc, re.I)
        assert re.search(r"billing stops on its own when the season ends", doc, re.I)


def test_the_pass_payer_is_welcomed_at_the_price_they_paid() -> None:
    """The registry flattens a pass payer to a season row, so a welcome built
    from the registry would state $39 renewal terms for a $99 purchase — a
    wrong legal disclosure. The builder takes the true plan."""
    msg = _msg("league_pass")
    for doc in (msg.html, msg.text):
        assert f"{PASS_PRICE} USD" in doc
        assert SEASON_PRICE + " USD" not in doc
        assert re.search(r"one per league", doc, re.I)
        assert re.search(r"claims a seat", doc, re.I)


def test_the_pass_welcome_hands_over_the_seat_link(monkeypatch) -> None:
    """The join page cannot deliver the seat link — it renders it in the
    instant before navigating to Stripe (deliberately: any earlier and an
    abandoned checkout leaves a shareable claim link) — so the welcome email
    is the commissioner's only reliable copy. With no SITE_URL there is no
    link to give, and the email must say something true instead of printing a
    dead href."""
    monkeypatch.setenv("SITE_URL", "https://example.com/")
    msg = _msg("league_pass")
    for doc in (msg.html, msg.text):
        assert "https://example.com/join/?pass=1" in doc
        assert re.search(r"email you paid with", doc, re.I), \
            "members must be told the payer address that matches their seat"
    monkeypatch.delenv("SITE_URL", raising=False)
    bare = _msg("league_pass")
    assert "/join/?pass=1" not in bare.text
    assert "None" not in bare.text


def test_a_seat_holder_is_never_shown_billing_terms() -> None:
    """A seat holder paid nothing. Renewal terms for money they never spent
    would read as a charge waiting to happen."""
    msg = _msg("seat")
    for doc in (msg.html, msg.text):
        assert re.search(r"nothing bills you", doc, re.I)
        assert re.search(r"never\s+quietly convert into a charge", doc, re.I)
        for price in (SEASON_PRICE, MONTHLY_PRICE, PASS_PRICE):
            assert price + " USD" not in doc
        assert not re.search(r"renews", doc, re.I)
        assert not re.search(r"refund", doc, re.I), \
            "a refund promise implies a payment that never happened"
    assert "seat" in msg.subject.lower()


def test_welcome_prices_match_the_pages_that_sold_them() -> None:
    """Two surfaces stating two prices is the drift this repo keeps finding.
    The email's constants must equal the landing page's own numbers and the
    league-pass page's own number."""
    landing = (SITE / "index.html").read_text(encoding="utf-8")
    assert f'class="price">{SEASON_PRICE} <small>/ season' in landing
    assert f'class="price">{MONTHLY_PRICE} <small>/ month' in landing
    league = (SITE / "league-pass.html").read_text(encoding="utf-8")
    assert f'class="amt">{PASS_PRICE} <small>' in league


# --------------------------------------------------------------------- #
# the cancel destination resolves
# --------------------------------------------------------------------- #

def test_the_cancel_link_prefers_the_billing_portal(monkeypatch) -> None:
    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/x1")
    monkeypatch.setenv("SITE_URL", "https://example.com")
    msg = _msg()
    assert "billing.stripe.com/p/login/x1" in msg.html
    assert "billing.stripe.com/p/login/x1" in msg.text


def test_without_a_portal_the_legal_steps_are_the_destination(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", "https://example.com")
    msg = _msg()
    assert "https://example.com/legal.html#cancel" in msg.html
    assert "https://example.com/legal.html#cancel" in msg.text


def test_with_nothing_configured_the_email_still_names_a_route() -> None:
    """Pre-launch state. The email may not dangle a dead link, and may not go
    silent about cancellation either."""
    msg = _msg()
    assert "href" not in msg.html.split("Cancel any time")[1].split(".")[0]
    assert re.search(r"legal page", msg.text, re.I)


# --------------------------------------------------------------------- #
# it survives real clients, and the operator's registers stay out
# --------------------------------------------------------------------- #

def test_the_welcome_is_email_safe() -> None:
    html = _msg().html
    for construct in ("<style", "var(--", "display:grid", "display:flex",
                      "@media", "fonts.googleapis", "<link"):
        assert construct not in html, f"email-unsafe construct: {construct}"


def test_the_welcome_key_is_idempotent_and_carries_no_address() -> None:
    """One welcome per subscription, forever — and the key lands in
    data/processed/sent.jsonl, which is committed, so no address may ride in
    it."""
    msg = _msg()
    assert msg.key == "welcome-2026-abc123def0"
    assert "@" not in msg.key and "fan" not in msg.key
    assert _msg().key == msg.key, "the key is not stable across builds"


def test_no_developer_vocabulary_reaches_the_welcome() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_site import _DEV_SPEAK
    for plan in ("season", "monthly", "league_pass", "seat"):
        msg = _msg(plan)
        for doc in (msg.html, msg.text, msg.subject):
            for pattern in _DEV_SPEAK:
                assert not re.search(pattern, doc, re.I), \
                    f"developer vocabulary {pattern!r} in the {plan} welcome"
