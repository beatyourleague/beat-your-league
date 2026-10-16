"""Unit economics (run/economics.py): per sale, per customer, and the documents.

Every figure here is an assumption with its source beside it. These tests pin
the arithmetic the owner documents quote, the customer view's charge model
against run/billing.py's real stop rule, and the gate that keeps PLAN.md and
LAUNCH.md quoting this model rather than a figure somebody typed in August.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import run.economics as econ

REPO = Path(__file__).resolve().parent.parent


def test_the_fee_figures_the_documents_quote() -> None:
    """LAUNCH.md and PLAN.md say $2.72 kept on a refunded $39 pass, about
    $1.94 with a USD payout account. Pinned so a change to the model shows up
    here and in the documents' gate together."""
    assert econ.stripe_fee(econ.SEASON) == 2.72
    assert econ.stripe_fee(econ.SEASON, usd_payout=True) == 1.94
    assert econ.stripe_fee(econ.LEAGUE_PASS) == 6.56
    assert 3 * econ.MONTHLY > econ.SEASON


def test_a_monthly_buyer_pays_the_first_month_in_full_then_a_prorated_last() -> None:
    """The charge model follows run/billing.py: the first month is charged in
    full at signup whatever the stop; after that Stripe bills on the
    anniversary and prorates the period containing the stop by time.
    Reproduction (G06): an Oct 20 buyer pays 14.99 + 14.99 + a Dec 20 period
    cut at Jan 13 (24 of 31 days, $11.61) — $41.59, more than the $39 pass."""
    stop = date(2027, 1, 13)
    full, stub = econ.monthly_charges(date(2026, 10, 20), stop)
    assert (full, stub) == (2, 11.61)
    assert round(full * econ.MONTHLY + stub, 2) == 41.59
    assert econ.monthly_charges(date(2026, 10, 13), stop) == (3, 0.0)
    # Joined inside the last period: one full month, never a credit back.
    assert econ.monthly_charges(date(2026, 12, 29), stop) == (1, 0.0)


def test_the_join_week_table_counts_charges_and_reports() -> None:
    tuesdays = {7: date(2026, 10, 20), 17: date(2026, 12, 29), 18: date(2027, 1, 5)}
    rows = econ.monthly_by_join_week((tuesdays, date(2027, 1, 13)))
    assert [(r["week"], r["charges"], r["paid"], r["reports"]) for r in rows] == [
        (7, 3, 41.59, 12), (17, 1, 14.99, 2), (18, 1, 14.99, 1)]


def test_lifetime_value_is_net_of_fees_refunds_and_disputes() -> None:
    for rate in econ.RENEWAL_RATES:
        assert econ.ltv(econ.SEASON, rate) == round(econ.net_per_sale(econ.SEASON) * (1 + rate), 2)
    assert econ.ltv(econ.SEASON, 0.7) > econ.ltv(econ.SEASON, 0.3)


def test_the_customer_view_says_it_is_assumptions(monkeypatch) -> None:
    lines = "\n".join(econ.customer_lines(calendar=({7: date(2026, 10, 20)},
                                                    date(2027, 1, 13))))
    assert "assumptions, not forecasts" in lines
    assert "never on a selling page" in lines

    assert "Week  7: 3 charges, $ 41.59 incl. a $11.61 part-month" in lines
    assert "an hour" in lines and "unpaid" in lines
    monkeypatch.setattr(econ, "season_calendar", lambda *a, **k: None)
    assert "can't say" in "\n".join(econ.customer_lines())


def test_the_customer_view_never_reaches_a_selling_page() -> None:
    """The scenarios are the owner's arithmetic. A renewal rate or a
    lifetime value on a page a buyer reads would be an invented result."""
    for page in (REPO / "site").rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for phrase in ("lifetime value", "LTV", "renewal rate", "an hour (owner"):
            assert phrase not in text, f"{page.name}: {phrase}"


def test_a_stale_refund_cost_in_a_document_is_caught() -> None:
    """Reproduction (ECON-04, GATE-18): PLAN §4 kept "the operator eats the
    payment-processing fee on every refund — roughly $1–1.50 a cycle" after
    §2 was corrected to $2.72, and the gate only looked for the old "3.7%"
    string, so any other wrong number passed."""
    stale = ("Note the operator eats the payment-processing fee on every refund — "
             "roughly $1–1.50 a cycle — so even without abuse, refunds are never free.")
    assert econ.doc_fee_mismatches(stale, "PLAN.md")
    right = ("A refund doesn't return Stripe's fee (about $2.72 on a $39 pass from a "
             "Canadian account, or about $1.94 with a USD payout account).")
    assert econ.doc_fee_mismatches(right, "LAUNCH.md") == []
    # Hand-wrapped across lines is still one sentence.
    wrapped = "A refund doesn't return Stripe's fee\n(about $3.40 on a $39 pass)."
    assert econ.doc_fee_mismatches(wrapped, "LAUNCH.md")
    # Prices, totals and the C$ rate components are not fee figures.
    assert econ.doc_fee_mismatches("Stripe's fee is 2.9% + C$0.30 on a $14.99 charge, "
                                   "and refunds return the $39.", "x") == []


def test_the_real_documents_quote_the_model() -> None:
    assert econ.docs_fee_mismatches() == []


def test_the_usd_payout_saving_is_a_warning_until_decided(monkeypatch) -> None:
    monkeypatch.delenv("STRIPE_PAYOUT_CURRENCY", raising=False)
    rows = {name: (status, detail) for name, status, detail in econ.summary_lines()}
    status, detail = rows["Payouts in USD keep the currency-conversion fee"]
    assert status == "WARN" and "$0.78" in detail
    monkeypatch.setenv("STRIPE_PAYOUT_CURRENCY", "usd")
    rows = {name: status for name, status, _ in econ.summary_lines()}
    assert rows["Payouts in USD keep the currency-conversion fee"] == "PASS"


def test_the_printout_runs(capsys) -> None:
    assert econ.main([]) == 0
    out = capsys.readouterr().out
    assert "PER SALE" in out and "PER CUSTOMER" in out


@pytest.mark.parametrize("day,expected", [(date(2026, 1, 31), date(2026, 2, 28)),
                                          (date(2026, 12, 15), date(2027, 1, 15))])
def test_a_billing_anchor_clamps_to_a_short_month(day, expected) -> None:
    assert econ._add_month(day) == expected
