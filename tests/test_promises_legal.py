"""The legal pages say exactly what the product does (promise audit, Oct 2026).

Each test pins one confirmed mismatch between terms.html / privacy.html and the
product, so the words cannot drift back to the version that was false.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

# A change to a legal page's words must move its "Last updated" date, because
# consent and notices are tied to that date. APPEND a (date, digest) pair when
# the words change; never edit an old one. The last pair must match the page.
PRIVACY_VERSIONS = [
    ("2026-10-18", "25bc5d53a2db85c1"),
    # The page counter (ANALYTICS-04) and the card's postal code (critique #7).
    ("2026-10-23", "83390cb12c707aec"),
]
TERMS_VERSIONS = [
    ("2026-10-18", "0d5cce06d12dd87c"),
]

_DATE = re.compile(r"Last updated (\d{1,2} [A-Z][a-z]+ \d{4})\.")


def _visible(name: str) -> str:
    page = (SITE / name).read_text(encoding="utf-8")
    page = re.sub(r"(?is)<(head|script|style)\b.*?</\1>|<!--.*?-->", " ", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return " ".join(text.split())


def _stamp(name: str) -> tuple[str, str]:
    text = _visible(name)
    found = _DATE.search(text)
    assert found, f"{name} has no 'Last updated' date"
    day = dt.datetime.strptime(found.group(1), "%d %B %Y").date().isoformat()
    body = _DATE.sub("Last updated.", text)
    return day, hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _check(name: str, versions: list[tuple[str, str]]) -> None:
    dates = [d for d, _ in versions]
    assert dates == sorted(set(dates)), "versions must be appended with later dates"
    assert len({h for _, h in versions}) == len(versions)
    assert _stamp(name) == versions[-1], (
        f"{name}'s words changed without a new Last-updated date, or the pin is "
        f"stale: bump the date on the page and APPEND {_stamp(name)}")


def test_privacy_words_are_pinned_to_their_last_updated_date() -> None:
    _check("privacy.html", PRIVACY_VERSIONS)


def test_terms_words_are_pinned_to_their_last_updated_date_and_version() -> None:
    from render.welcome import TERMS_VERSION
    _check("terms.html", TERMS_VERSIONS)
    assert TERMS_VERSIONS[-1][0] == TERMS_VERSION, (
        "consent is recorded against TERMS_VERSION: it must name the current words")


def test_the_short_version_restates_the_body() -> None:
    """LEGAL-7/10/11: 'It is not advice' disclaimed the very thing sold, and
    'what you paid us' dropped section 8's twelve-month limit."""
    terms = _visible("terms.html")
    short = terms[terms.index("The short version."):terms.index("1. What you're buying")]
    assert "not advice," not in short
    assert "analysis, not betting picks" in short
    assert "twelve months" in short and "twelve months before the claim" in terms
    assert "one refund per person" in short.lower()
    assert "says the same things" not in short


def test_monthly_billing_words_match_the_season_end_stop() -> None:
    """LEGAL-28..31/139 under D1: the last charge is the month the season's
    last weekly report falls in; no 'offseason' or part-month stub claim."""
    from infra.stripe_paylink_text import MESSAGES, TOS_MESSAGES
    terms = _visible("terms.html")
    for text in (terms, MESSAGES["monthly"], TOS_MESSAGES["monthly"]):
        assert "after the season's last weekly report" in text
    assert "through the offseason" not in terms + MESSAGES["monthly"]
    assert "when the season ends" not in MESSAGES["monthly"]


def test_contact_us_carve_out_names_the_two_purchase_case() -> None:
    """D3: Stripe's billing page shows only the newest purchase for an email."""
    terms = _visible("terms.html")
    assert "never require you to contact us" in terms
    assert "most recent purchase under that address" in terms
    assert "reply to any report" in terms


def test_league_pass_size_is_the_size_chosen_at_checkout() -> None:
    """LEGAL-14/61: seat_cap is the league size chosen at checkout (8-14)."""
    terms = _visible("terms.html")
    assert "as many seats as the league has teams" not in terms
    assert "league size chosen at checkout (8, 10, 12 or 14)" in terms
    assert terms.count("up to 14") >= 2


def test_the_privacy_box_is_the_whole_list() -> None:
    """LEGAL-73/90/93: the box claimed completeness and omitted the stored
    lineups and odds, the Stripe ids, the plan, the send log and form rows;
    the terms restated an even shorter list."""
    privacy = _visible("privacy.html")
    box = privacy[privacy.index("The whole list."):privacy.index("1. What we collect")]
    for item in ("billing address", "each change you make", "when you bought",
                 "which plan", "Stripe reference numbers", "accepting our terms",
                 "the lineup it set", "odds it printed", "League Pass seat",
                 "through our forms", "channel", "which emails we've sent",
                 "keyed one-way codes", "stop list"):
        assert item in box, f"the whole-list box omits {item!r}"
    assert "That is everything we hold" not in privacy
    terms = _visible("terms.html")
    section = terms[terms.index("10. Privacy"):terms.index("11. Age")]
    assert "your email, the roster you entered, and your league's" not in section
    assert "complete list" in section


def test_no_unkeyed_digest_is_promised() -> None:
    """D4: address-derived codes are HMACs under a private key."""
    privacy = _visible("privacy.html")
    assert "one-way digest" not in privacy
    assert privacy.count("without our private key") >= 3


def test_privacy_says_what_is_public_and_what_waits_for_the_forms() -> None:
    """LEGAL-122/123 (the ledger is public, by setup) and LEGAL-115/126 (the
    waitlist is an email to hello@ until the form Worker is on)."""
    privacy = _visible("privacy.html")
    assert "We never publish your name, your email or your roster" not in privacy
    assert "could recognise your calls" in privacy
    assert "nothing that could identify you" not in privacy
    assert privacy.count("once the launch email has gone out") >= 2
    assert "copy you can take elsewhere" in privacy


def test_legal_pages_carry_the_tagline() -> None:
    for name in ("terms.html", "privacy.html"):
        assert "Beat Your League — analysis, not betting picks." in _visible(name)
