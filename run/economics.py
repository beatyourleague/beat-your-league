"""Unit economics — what each sale actually leaves, and the break-even.

Usage:
    python -m run.economics

Every number here is an ASSUMPTION with its source beside it, kept in one
place so PLAN.md, LAUNCH.md and the launch check quote the same arithmetic.
The launch-readiness audit (Oct 2026) found PLAN assuming Stripe kept 3.7% of
a sale; on this account (Canadian Stripe, mostly US cards, USD charges paid
out in CAD) it is about 7%, and a refund keeps the fee. Not tax advice:
GST/HST and US sales tax are watched as thresholds, not computed.
"""

from __future__ import annotations

import sys

# Prices (render/welcome.py is the source of truth; tested equal to the site).
SEASON = 39.00
MONTHLY = 14.99
LEAGUE_PASS = 99.00

# Stripe Canada, card in USD from a US cardholder, paid out in CAD (Stripe's
# published Canadian pricing, checked by the audit Oct 2026): 2.9% + C$0.30,
# +0.8% international card, +2% currency conversion, +0.7% Billing for a
# subscription. A USD payout account removes the 2% conversion.
PCT = 0.029 + 0.008 + 0.02 + 0.007
FIXED_USD = 0.22                      # C$0.30 at about 0.73
REFUND_RATE = 0.08                    # audit base case; the biggest profit lever
DISPUTE_RATE = 0.006

# Fixed cash costs for the rest of a season (audit estimates): a non-home
# mailbox for the sender address, the domain, Resend Pro once a send day passes
# the free tier's 100 emails (about 85 report recipients).
FIXED_SEASON_COSTS = {"mailbox (≈US$10/mo × 3)": 30.0, "domain (share)": 12.0}
RESEND_PRO_MONTHLY = 20.0
RESEND_FREE_RECIPIENTS = 85

# Tax thresholds (not tax advice): GST/HST small-supplier limit, worldwide.
GST_HST_THRESHOLD_CAD = 30_000


def stripe_fee(amount: float, usd_payout: bool = False) -> float:
    pct = PCT - (0.02 if usd_payout else 0.0)
    return round(amount * pct + FIXED_USD, 2)


def net_per_sale(amount: float) -> float:
    """What one purchase leaves after Stripe, expected refunds (which return
    the price but keep Stripe's fee) and disputes."""
    fee = stripe_fee(amount)
    kept = (1 - REFUND_RATE - DISPUTE_RATE) * (amount - fee)
    lost_fees = (REFUND_RATE + DISPUTE_RATE) * fee
    return round(kept - lost_fees, 2)


def break_even_purchases() -> int:
    fixed = sum(FIXED_SEASON_COSTS.values())
    per = net_per_sale(SEASON)
    return int(-(-fixed // per))          # ceiling


def summary_lines() -> list[tuple[str, str, str]]:
    """(gate, status, detail) rows for `make launch-check`."""
    rows = []
    rows.append(("Three monthly charges cost more than the season pass",
                 "PASS" if 3 * MONTHLY > SEASON else "FAIL",
                 f"3 × ${MONTHLY} = ${3 * MONTHLY:.2f} vs ${SEASON:.0f}"))
    fee = stripe_fee(SEASON)
    rows.append(("Net per season pass after Stripe, refunds and disputes", "PASS",
                 f"${net_per_sale(SEASON):.2f} of ${SEASON:.0f} (Stripe ${fee:.2f}, "
                 f"{fee / SEASON:.1%}; ${stripe_fee(SEASON, usd_payout=True):.2f} "
                 f"with a USD payout account)"))
    rows.append(("Break-even on this season's fixed costs", "PASS",
                 f"{break_even_purchases()} season-pass purchases cover "
                 f"${sum(FIXED_SEASON_COSTS.values()):.0f}; Resend Pro "
                 f"(${RESEND_PRO_MONTHLY:.0f}/mo) only past ~{RESEND_FREE_RECIPIENTS} "
                 f"recipients"))
    try:
        from pathlib import Path
        plan = (Path(__file__).resolve().parent.parent / "PLAN.md").read_text(encoding="utf-8")
        stale = "| Stripe | 2.9% + 30¢ per charge |" in plan or "3.7%" in plan
    except OSError:
        stale = False
    rows.append(("PLAN.md's fee figure matches this model",
                 "WARN" if stale else "PASS",
                 "PLAN.md still assumes 3.7% — the real figure is about "
                 f"{fee / SEASON:.1%}" if stale else f"about {fee / SEASON:.1%}"))
    return rows


def main(argv: list[str] | None = None) -> int:
    print("UNIT ECONOMICS (assumptions at the top of run/economics.py)\n")
    for plan, price in (("Season pass", SEASON), ("Monthly charge", MONTHLY),
                        ("League Pass", LEAGUE_PASS)):
        print(f"  {plan:15} ${price:>6.2f}  Stripe ${stripe_fee(price):5.2f}  "
              f"net ${net_per_sale(price):6.2f}")
    print()
    for gate, _status, detail in summary_lines():
        print(f"  {gate}: {detail}")
    print(f"\n  GST/HST registration only past C${GST_HST_THRESHOLD_CAD:,} of "
          f"worldwide sales in four quarters (not tax advice).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
