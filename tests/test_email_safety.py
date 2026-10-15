"""What an email client will do to our HTML — checked without the clients.

Outlook renders with Word's engine, Gmail strips <style> in forwards and clips
a message over ~102 KB, Apple Mail and Outlook.com invert an email that does
not say it is light-only, and every one of them ignores flex, grid, var() and
loaded fonts. So every HTML email we send is held to what they all render:
tables for layout, inline styles, no external assets, absolute https links, a
declared colour scheme, a padded preview line, and under Gmail's clip.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from engine.final_check import Change
from render.email import render_email
from render.final_check import render_final_check
from render.roster_update import confirm_email
from render.welcome import welcome_message

FORBIDDEN = [r"<style", r"@media", r"display\s*:\s*(flex|grid)", r"var\(--",
             r"position\s*:\s*(absolute|fixed|sticky)", r"background-image",
             r"url\(", r"<link", r"<script", r"<img", r"calc\(", r"<svg",
             r"@import", r"<iframe", r"onclick"]
GMAIL_CLIP = 102 * 1024


def _report() -> dict:
    import render.sample as sample
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    report["meta"].pop("historical_demo", None)
    report["meta"].pop("anonymized_demo", None)
    return report


def _variant(report: dict, **meta) -> str:
    import copy
    out = copy.deepcopy(report)
    out["meta"].update(meta)
    return render_email(out)


def _all_emails() -> dict[str, str]:
    report = _report()
    # The free report and a League Pass seat's report have footers of their
    # own (a sender line on the free one, a stop route on the seat's — launch
    # audit C14, C4), so each is held to the same client rules as the paid one.
    out = {"report": render_email(report),
           "free report": _variant(report, trial=True),
           "seat report": _variant(report, plan="league_pass"),
           "final check": render_final_check(
               {"week": 10, "players": {}},
               [Change("swap", "Start X at RB", "Y is out.")],
               datetime(2024, 11, 9, 16, tzinfo=timezone.utc)),
           "roster confirmation": confirm_email(
               "https://x.test/join/confirm.html?c=" + "a" * 24, ["A", "B"])[1]}
    for plan in ("season", "monthly", "league_pass", "seat"):
        out[f"welcome {plan}"] = welcome_message(
            "a@b.co", plan, "abc123", "2026",
            purchased_at="2026-09-29T12:00:00+00:00").html
    # The renewal notice and the roster report are emails too, and were held
    # to none of this: the notice was a bare <div> a phone laid out at 980px.
    from datetime import date

    from render.preseason import email_html
    from render.renewal import Renewal, renewal_message
    from test_preseason import _report as roster_report
    out["renewal notice"] = renewal_message(
        Renewal("a@b.co", "$39.00 USD", date(2027, 8, 1), "year", plan="season")).html
    out["roster report"] = email_html(roster_report())
    return out


@pytest.fixture(scope="module")
def emails() -> dict[str, str]:
    # Rendered as they ship once configured: with a postal address and a
    # billing page, so the sender block and the cancel link are under test too.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SENDER_POSTAL_ADDRESS", "PO Box 123, Toronto ON M5V 1A1")
        mp.setenv("BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/x")
        return _all_emails()


def test_the_free_report_carries_the_sender_block_like_the_paid_one(emails) -> None:
    """Reproduction (launch audit C14, OPS-4): with SENDER_POSTAL_ADDRESS set,
    the paid report's footer printed the mailbox address and the free report's
    — the one email to a non-customer, ending on how to buy — did not."""
    for name in ("report", "free report", "seat report"):
        assert "PO Box 123, Toronto ON M5V 1A1" in emails[name], name


def test_no_email_uses_what_email_clients_cannot_render(emails) -> None:
    for name, html in emails.items():
        hits = [p for p in FORBIDDEN if re.search(p, html, re.I)]
        assert not hits, f"{name} uses {hits}"
        bare = re.findall(r'<table(?![^>]*role="presentation")', html)
        assert not bare, f"{name} has a layout table without role=presentation"


def test_every_link_is_absolute_https(emails) -> None:
    for name, html in emails.items():
        for href in re.findall(r'href="([^"]*)"', html):
            assert href.startswith("https://"), f"{name} links {href!r}"


def test_every_email_declares_it_is_light_only_and_has_a_padded_preview(emails) -> None:
    """Apple Mail and Outlook.com invert an email that doesn't say otherwise;
    and a preview line with no filler continues into the body text."""
    for name, html in emails.items():
        assert '<meta name="color-scheme" content="light only">' in html, name
        assert '<meta name="supported-color-schemes" content="light only">' in html, name
        assert "<title>" in html and 'lang="en"' in html, name
    for name in ("report", "final check", "roster confirmation", "welcome season",
                 "welcome seat", "renewal notice"):
        assert "&#847;&zwnj;&nbsp;" in emails[name] and "mso-hide:all" in emails[name], name


def test_the_checklist_box_is_a_table_not_a_sized_div(emails) -> None:
    """Outlook's Word engine ignores a div's height and draws it a line tall."""
    for name in ("report", "final check"):
        html = emails[name]
        assert 'width="14" height="14"' in html, name
        assert not re.search(r'<div style="width:14px;height:14px', html), name


def test_a_full_report_stays_far_under_gmails_clip() -> None:
    """A message over ~102 KB is cut off with "View entire message" — losing
    the receipts and the footer with the cancel link. Measured on the largest
    roster the product accepts (30 players) with a full bench."""
    import render.sample as sample
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    report["meta"].pop("historical_demo", None)
    template = report["bench"][0]
    report["bench"] = [dict(template, name=f"Bench Player {i}") for i in range(22)]
    size = len(render_email(report).encode("utf-8"))
    assert size < GMAIL_CLIP * 0.6, f"{size / 1024:.0f} KB is too close to Gmail's clip"


# Every email a subscriber or buyer receives (the roster confirmation is a
# one-line transactional reply to their own request, with no ask in it).
SENDER_BLOCK = [name for name in (
    "report", "free report", "seat report", "final check", "renewal notice",
    "roster report", "welcome season", "welcome monthly", "welcome league_pass",
    "welcome seat")]


def test_every_email_says_who_sent_it(emails) -> None:
    """Reproduction (launch audit L3, GATE-9): rendered with
    SENDER_POSTAL_ADDRESS set, the report and the waitlist carried the sender
    block — and the Saturday final check, all four welcome emails, the renewal
    notice and the roster report did not."""
    for name in SENDER_BLOCK:
        assert "Beat Your League · PO Box 123, Toronto ON M5V 1A1 · " \
               "hello@beatyourleague.com" in emails[name], name


def test_every_email_carries_a_way_out(emails) -> None:
    """GATE-9's other half: each email names how to stop it — a cancel route
    for a paid subscription, a stop route for a seat, and for the free report
    the promise that nothing more comes."""
    import html as _html
    for name in SENDER_BLOCK:
        text = _html.unescape(emails[name])
        assert re.search(r"Cancel|Reply \"stop\"|only email we.ll send you", text), name


def test_every_full_email_is_a_document_a_phone_lays_out(emails) -> None:
    """The renewal notice was a bare <div>: no doctype, no viewport, so a
    phone rendered it at a desktop's 980px and shrank the type to fit
    (measured at 390px, Oct 2026)."""
    for name, page in emails.items():
        assert page.lstrip().lower().startswith("<!doctype html"), name
        assert 'name="viewport"' in page, name
