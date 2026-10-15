"""Every email's way out, and who it says sent it — per reader.

Three findings of the Oct 15 2026 launch audit, all in report footers:

- C4: a League Pass SEAT pays nothing and has no Stripe subscription, yet its
  weekly report (both halves, and the browser archive) told it to "cancel it
  yourself from your own billing page" and its List-Unsubscribe header pointed
  at the same portal, where its address finds no customer. A seat had no
  working way out at all.
- C13: the text half of every paid report ended "The reports stop on their own
  once you do" — while terms §4 keeps access to the end of the period already
  paid for, and run/subscriptions.py keeps that subscription entitled.
- C14: the free report — the one email to a non-customer, ending on how to
  buy — carried no sender identity or postal address on either half, because
  its footer branch returned before the paid footer's sender line.
"""

from __future__ import annotations

import copy
import re

import pytest

import render.report as rr
from render.email import render_email, text_summary

PORTAL = "https://billing.stripe.com/p/login/x"
ADDRESS = "PO Box 123, Toronto ON M5V 1A1"
STOP = "mailto:hello@beatyourleague.com?subject=stop"


@pytest.fixture(scope="module")
def base_report() -> dict:
    import render.sample as sample
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    report["meta"].pop("historical_demo", None)
    report["meta"].pop("anonymized_demo", None)
    return report


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BILLING_PORTAL_URL", PORTAL)
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", ADDRESS)
    monkeypatch.delenv("SITE_URL", raising=False)


def _as(report: dict, **meta) -> dict:
    out = copy.deepcopy(report)
    out["meta"].update(meta)
    return out


def _surfaces(report: dict) -> dict[str, str]:
    template = rr.TEMPLATE_PATH.read_text(encoding="utf-8")
    return {"email html": render_email(report), "email text": text_summary(report),
            "browser archive": rr.render(report, template)}


# --------------------------------------------------------------------- #
# C4 — a seat's way out
# --------------------------------------------------------------------- #

def test_a_seats_report_stops_by_asking_never_at_a_billing_page(base_report, env) -> None:
    """Reproduction: a report built for a seat (meta plan "league_pass", which
    run/tuesday.py copies from the registry row — on a row that word means a
    SEAT) rendered "Cancel it yourself from your own billing page … no further
    charges" plus the portal link on every surface."""
    seat = _as(base_report, plan="league_pass")
    for name, doc in _surfaces(seat).items():
        assert PORTAL not in doc, f"{name} sends a seat to a billing page"
        assert not re.search(r"billing page|further charges|charges to end", doc), name
        assert re.search(r"Reply (&quot;|\")stop(&quot;|\")", doc), name
        assert re.search(r"within 10 business days", doc), name
        # "Your league's pass", never "your commissioner's": any manager may
        # buy it (panel review LP-D7).
        assert re.search(r"league(&#x27;|')s pass isn(&#x27;|')t affected", doc), name
        assert "commissioner" not in doc.lower(), name


def test_a_paying_subscribers_report_still_cancels_itself(base_report, env) -> None:
    """The seat branch must not leak: a paid report keeps the self-serve
    cancel, its link, and the unsubscribe-vs-cancel distinction."""
    for plan in ("season", "monthly", None):
        paid = _as(base_report, plan=plan)
        for name, doc in _surfaces(paid).items():
            assert PORTAL in doc, f"{name} ({plan}) lost its cancel link"
            assert re.search(r"unsubscribing from emails alone does not", doc, re.I), name
            assert "10 business days" not in doc, f"{name} ({plan}) got the seat's route"


def test_the_unsubscribe_header_follows_the_reader(env) -> None:
    """The header the mail app's unsubscribe button reads. A seat's is the
    stop request its footer describes; a subscriber's is where money stops.
    (run/tuesday.py and run/saturday.py pass the subscriber's seat flag.)"""
    assert rr.unsubscribe_target(seat=True) == STOP
    assert rr.unsubscribe_target(seat=False) == PORTAL
    assert rr.unsubscribe_target() == PORTAL


def test_is_seat_reads_the_registry_word_not_the_welcome_word() -> None:
    """On a registry row "league_pass" is a SEAT (a payer is a season row);
    in the welcome email "league_pass" is the PAYER and a seat is "seat".
    The report helper reads the report's own meta, so only the first."""
    assert rr.is_seat({"plan": "league_pass"})
    for plan in ("season", "monthly", "seat", None):
        assert not rr.is_seat({"plan": plan})


def test_the_footer_helpers_say_the_same_thing_on_both_halves(env) -> None:
    """One block, every surface (the Saturday check reuses these too)."""
    seat_html, seat_text = rr.cancel_html(True), "\n".join(rr.cancel_lines(True))
    assert "href" not in seat_html, "every href in an email must be https"
    assert rr.SEAT_STOP_BODY in seat_text
    paid_html, paid_text = rr.cancel_html(False, "color:#101E33;"), "\n".join(rr.cancel_lines(False))
    assert f'href="{PORTAL}" style="color:#101E33;"' in paid_html
    assert f"CANCEL: your billing page — {PORTAL}" in paid_text


# --------------------------------------------------------------------- #
# C13 — when the reports stop
# --------------------------------------------------------------------- #

def test_cancelling_keeps_the_reports_to_the_end_of_the_paid_period(base_report, env) -> None:
    """Reproduction: text_summary's last cancel line said "The reports stop on
    their own once you do." Terms §4: "You keep access for the rest of the
    period you've already paid for"."""
    paid = _as(base_report, plan="season")
    for name, doc in _surfaces(paid).items():
        assert "stop on their own once you do" not in doc, name
        assert re.search(r"continue to the end of the period you(&#x27;|')ve "
                         r"already paid for, then stop", doc), name


# --------------------------------------------------------------------- #
# C14 — who sent the free report
# --------------------------------------------------------------------- #

def test_the_free_report_says_who_sent_it(base_report, env) -> None:
    """Reproduction: a trial (meta.trial=True) rendered with
    SENDER_POSTAL_ADDRESS set carried the address on neither half, while the
    paid report printed it on both."""
    trial = _as(base_report, trial=True)
    html_out, text_out = render_email(trial), text_summary(trial)
    line = f"Beat Your League · {ADDRESS} · hello@beatyourleague.com"
    assert line in text_out
    assert line in html_out
    # And it stays a free report: no cancel route, no billing page.
    for doc in (html_out, text_out):
        assert PORTAL not in doc and "billing page" not in doc


def test_without_an_address_the_free_report_prints_no_empty_sender(base_report,
                                                                   monkeypatch) -> None:
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS", raising=False)
    trial = _as(base_report, trial=True)
    for doc in (render_email(trial), text_summary(trial)):
        assert "None" not in doc.split("This one")[-1]
        assert "· hello@beatyourleague.com" not in doc
