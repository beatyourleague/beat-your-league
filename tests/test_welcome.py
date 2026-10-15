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


def test_a_seat_holder_claimed_a_seat_and_has_a_real_way_out(monkeypatch) -> None:
    """Reproduction (launch audit C4, Oct 15 2026): welcome_message(email,
    'seat', ...) said "You bought a seat on your league's League Pass." and,
    under DONE WITH THIS?, sent the seat to "your billing page" to cancel
    "if you want the charges to end" — in the same email as "Nothing bills you
    for this seat, ever". A seat has no Stripe subscription, so the portal
    finds no customer at its address: the email gave it no working way out at
    all. A seat CLAIMED its place, and stops by asking (run/suppress.py)."""
    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/x1")
    msg = _msg("seat")
    for doc in (msg.html, msg.text):
        assert re.search(r"You claimed a seat", doc), doc
        assert not re.search(r"\bbought\b", doc, re.I), "a seat bought nothing"
        assert "billing.stripe.com" not in doc
        assert not re.search(r"billing page|charges to end|cancel", doc, re.I), \
            "a seat has nothing to cancel and no charges to end"
        assert re.search(r"reply .{0,6}stop", doc, re.I)
        assert re.search(r"mail app.{0,6}s unsubscribe", doc, re.I)
        assert re.search(r"within 10 business days", doc)
        # "Your league's pass": any manager may buy it (panel review LP-D7).
        assert re.search(r"league.{0,6}s pass isn.{0,6}t affected", doc, re.I)
        assert "commissioner" not in doc.lower()
    assert msg.unsubscribe == "mailto:hello@beatyourleague.com?subject=stop", \
        "the mail app's unsubscribe must reach the inbox that honours a stop"
    # A buyer's welcome is unchanged: bought, billing page, no stop header.
    paid = _msg("season")
    assert "You bought" in paid.text and "billing.stripe.com" in paid.text
    assert paid.unsubscribe is None


def test_a_buyer_is_told_reports_run_to_the_end_of_what_they_paid_for() -> None:
    """Terms §4 keeps access to the end of the period already paid for, and
    run/subscriptions.py keeps a cancel_at_period_end subscription entitled
    until then — the acknowledgment states the same fact (launch audit C13)."""
    for plan in ("season", "monthly", "league_pass"):
        msg = _msg(plan)
        for doc in (msg.html, msg.text):
            assert re.search(r"continue to the end of the period you.{0,6}ve "
                             r"already paid for, then stop", doc), plan


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


def test_without_a_portal_the_terms_steps_are_the_destination(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", "https://example.com")
    msg = _msg()
    assert "https://example.com/terms.html#cancel" in msg.html
    assert "https://example.com/terms.html#cancel" in msg.text


def test_with_nothing_configured_the_email_still_names_a_route() -> None:
    """Pre-launch state. The email may not dangle a dead link, and may not go
    silent about cancellation either."""
    msg = _msg()
    assert "href" not in msg.html.split("Cancel any time")[1].split(".")[0]
    assert re.search(r"terms page", msg.text, re.I)


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


# --------------------------------------------------------------------- #
# panel review, Oct 2026: what the first email after paying looks like
# --------------------------------------------------------------------- #

SEAT_LINK = ("https://example.com/join/?pass=0123456789abcdef0123"
             "&s=ppr&n=12&t=T1")


def test_the_welcome_wears_the_weekly_emails_masthead_and_a_preview_line() -> None:
    """Reproduction (panel review I6): welcome_message(..., 'season', ...) at
    600px was plain "You're in." Arial paragraphs — no navy masthead, no mark,
    no preview line, nothing that looked like the report just bought. The
    weekly email's masthead (the gold BEAT YOUR LEAGUE over a navy band) and a
    padded preheader now open every plan's welcome."""
    from render.email import NAVY
    for plan in ("season", "monthly", "league_pass", "seat"):
        html = _msg(plan).html
        assert f"background:{NAVY};" in html.split("You&#x27;re in.")[0], plan
        assert "letter-spacing:4px;text-transform:uppercase" in html, plan
        assert "&#847;&zwnj;&nbsp;" in html and "mso-hide:all" in html, plan
        # What happens next, row by row, as the thanks page lists it.
        assert "Every Tuesday" in html and "Saturday, if needed" in html, plan
    # A matched seat gets its first email the day it is claimed, by the same
    # rules as a purchase (run/intake.py, LP-I4), so it has a "today" too and
    # its subject says the report is on its way, not "Tuesday morning".
    assert ">Today<" in _msg("season").html and ">Today<" in _msg("seat").html
    assert "on its way" in _msg("seat").subject
    assert "Tuesday" not in _msg("seat").subject


def test_the_welcome_names_the_plan_the_purchase_date_and_the_terms(monkeypatch) -> None:
    """Reproduction (launch audit L5): the welcome named no purchase date —
    `purchased_at` fed only the send key — and linked no terms page, though
    the buyer had just ticked a box agreeing to them."""
    monkeypatch.setenv("SITE_URL", "https://example.com")
    # Stripe's `created`, as run/intake passes it: 2026-10-15 16:00 UTC.
    msg = welcome_message("fan@example.com", "season", "abc123def0", "2026",
                          purchased_at="1792080000")
    for doc in (msg.html, msg.text):
        assert "the season pass" in doc
        assert "Purchased October 15, 2026." in doc
        assert "https://example.com/terms.html" in doc
        assert re.search(r"terms you agreed to \(last updated October 15, 2026\)", doc)
    monthly = _msg("monthly")
    assert "the monthly plan" in monthly.text
    pass_ = _msg("league_pass")
    assert "the League Pass" in pass_.text
    # No clock, no invented date.
    assert "Purchased" not in _msg("season").text
    # A seat ticked no box at checkout, and bought nothing on a date.
    seat = welcome_message("m@example.com", "seat", "abc123def0", "2026",
                           purchased_at="1792080000")
    assert "Purchased" not in seat.text and "agreed to" not in seat.text


def test_every_welcome_says_who_sent_it(monkeypatch) -> None:
    """Reproduction (launch audit L3, GATE-9): with SENDER_POSTAL_ADDRESS set,
    the weekly report carried the sender block and every welcome — the
    acknowledgment the law owes the buyer — carried none, on either half."""
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 123, Toronto ON M5V 1A1")
    line = "Beat Your League · PO Box 123, Toronto ON M5V 1A1 · hello@beatyourleague.com"
    for plan in ("season", "monthly", "league_pass", "seat"):
        msg = _msg(plan)
        assert line in msg.text, plan
        assert line in msg.html, plan
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS")
    bare = _msg("season")
    assert "None" not in bare.text and " ·  · " not in bare.text
    assert "hello@beatyourleague.com" in bare.text, "a contact route stays"


def test_a_pass_payer_is_handed_the_leagues_own_seat_link_first() -> None:
    """Reproduction (panel review LP-I6, contract C4): the commissioner's one
    job after paying — sharing with the league — was the third paragraph under
    "The terms, in writing", untappable, and told them to give out "the email
    you paid with" in an email sent to that very address. With the league's
    own seat link it is the first block: a tappable button and a message to
    paste, naming nobody's address."""
    msg = welcome_message("commish@example.com", "league_pass", "abc123def0",
                          "2026", seat_link=SEAT_LINK)
    html_seat = SEAT_LINK.replace("&", "&amp;")
    assert f'href="{html_seat}"' in msg.html, "the seat link is not tappable"
    order = [msg.html.index(f">{title}</div>") for title in
             ("Send your league this", "What happens next", "The terms, in writing")]
    assert order == sorted(order), "the share block is not first"
    for doc in (msg.text, msg.html.replace("&amp;", "&")):
        assert SEAT_LINK in doc
        assert "Nothing to pay. Claim your seat here: " + SEAT_LINK in doc
        assert "email you paid with" not in doc, "the signed link needs no address"
        assert "commish@example.com" not in doc, "an address rode in the share text"
    # "pass" — the registry's word for the payer — reads the same.
    assert welcome_message("c@example.com", "pass", "abc123def0", "2026",
                           seat_link=SEAT_LINK).text == msg.text.replace(
        "commish@example.com", "c@example.com")


def test_a_pass_payer_is_told_seats_end_with_the_pass(monkeypatch) -> None:
    """LP-I6: cancelling or refunding the pass ends every seat's reports, and
    the 'Done with this?' block mentioned only the payer's own."""
    for seat_link in (None, SEAT_LINK):
        msg = welcome_message("c@example.com", "league_pass", "abc123def0",
                              "2026", seat_link=seat_link)
        for doc in (msg.html, msg.text):
            assert re.search(r"seats last as long as your pass does", doc), doc
            assert re.search(r"every seat.{0,6}s reports stop too", doc)
    for plan in ("season", "monthly", "seat"):
        assert "every seat" not in _msg(plan).text, plan


def test_a_seat_link_that_is_not_https_is_never_an_href(monkeypatch) -> None:
    """Every href in an email is https (tests/test_email_safety.py); a seat link
    that is not one is still given, as text, never as a link."""
    monkeypatch.setenv("SITE_URL", "http://localhost:8000")
    msg = _msg("league_pass")
    assert "http://localhost:8000/join/?pass=1" in msg.text
    assert "http://localhost:8000/join/?pass=1" in msg.html
    assert 'href="http://localhost:8000/join' not in msg.html
