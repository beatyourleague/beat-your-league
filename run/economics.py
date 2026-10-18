"""Unit economics — what each sale actually leaves, and what a customer is worth.

Usage:
    python -m run.economics

Every number here is an ASSUMPTION with its source beside it, kept in one
place so PLAN.md, LAUNCH.md and the launch check quote the same arithmetic.
The launch-readiness audit (Oct 2026) found PLAN assuming Stripe kept 3.7% of
a sale; on this account (Canadian Stripe, mostly US cards, USD charges paid
out in CAD) it is about 7%, and a refund keeps the fee. Not tax advice:
GST/HST and US sales tax are watched as thresholds, not computed.

Two views (G21, Oct 2026). **Per sale** is what one purchase leaves. **Per
customer** is what a buyer is worth over time — which a per-sale break-even
overstates, because it ignores the owner's hours and that a monthly buyer
pays a different number of charges depending on the week they join. The
customer view prints its assumptions beside its results; none of it is a
forecast, and none of it may be quoted on a selling page.
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Prices (render/welcome.py is the source of truth; tested equal to the site).
SEASON = 39.00
MONTHLY = 14.99
LEAGUE_PASS = 99.00

# Stripe Canada, card in USD from a US cardholder, paid out in CAD (Stripe's
# published Canadian pricing, checked by the audit Oct 2026): 2.9% + C$0.30,
# +0.8% international card, +2% currency conversion, +0.7% Billing for a
# subscription. A USD payout account removes the 2% conversion.
PCT = 0.029 + 0.008 + 0.02 + 0.007
USD_PER_CAD = 0.73                    # stated rate, Oct 2026 — not a live quote
FIXED_USD = round(0.30 * USD_PER_CAD, 2)
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

# Substack's cut, the platform this replaced (PLAN §4) — for the one sentence
# in PLAN that compares the two.
SUBSTACK_CUT = 0.10

# The customer view's assumptions (G21). Stated, not measured: there are no
# customers yet, so every one of these is a scenario to read across, never a
# number to sell with.
RENEWAL_RATES = (0.30, 0.50, 0.70)    # share of 2026 buyers who are still paying in 2027
BASE_CASE = {"season": 30, "league_pass": 2}   # the launch audit's base case for 2026
# Selling is PLAN §5's own time budget, "~30–40 min/day in season (replies +
# one post)" — taken at its middle. It was counted at the 20 minutes of the
# replies alone, which put the base case at about $26 an hour against the
# launch-readiness audit's $17 for the same season (G26): the hourly figure
# the owner reads must be the one PLAN's own budget implies.
SELLING_MIN_PER_DAY = 35
OWNER_HOURS = {                       # what the season costs in the owner's time
    "setup left (LAUNCH steps 1–5)": 3.0,
    "Tuesday QA, refunds, replies (1 h a week)": 1.0 * 12,
    f"selling: replies and one post ({SELLING_MIN_PER_DAY} min a day, PLAN §5)":
        SELLING_MIN_PER_DAY / 60 * 7 * 12,
}
WEEKS_LEFT = 12                       # weeks 7–18, opening Oct 20
HOURLY_NOTE = "owner time is unpaid; this is what it earns, not what it costs"


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


# --------------------------------------------------------------------- #
# the customer view (G21)
# --------------------------------------------------------------------- #

def _add_month(day: date) -> date:
    """The same day next month, clamped to the month's end (how Stripe moves a
    billing anchor past a short month)."""
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    for d in range(day.day, 27, -1):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    return date(year, month, min(day.day, 28))


def monthly_charges(joined: date, stop: date) -> tuple[int, float]:
    """(monthly charges, 0.0) for a monthly buyer who joins on ``joined`` when
    the season's last weekly report is due on ``stop``. The first month is
    charged at signup; Stripe then bills in advance on each anniversary, and
    run/billing.py ends the subscription at the close of the period that
    contains the last report (cancel_at_period_end), so an anniversary renews
    only while it falls on or before ``stop``. No part-month exists any more;
    the second element is kept so callers' shape doesn't move."""
    full, start = 1, _add_month(joined)
    while start <= stop:
        full += 1
        start = _add_month(start)
    return full, 0.0


def season_calendar(cache_dir: Path | None = None, today: date | None = None
                    ) -> tuple[dict[int, date], date] | None:
    """({week: the Tuesday its report goes out}, the last report's date) for
    the season being served, from the schedule the product itself reads.
    None when the cache cannot say (the offseason, a cold cache)."""
    try:
        from run.billing import stop_for
        from run.solo import CACHE_DIR, _schedule, _weeks
        cache = cache_dir or CACHE_DIR
        stop, season = stop_for(cache, today)
        if stop is None or season is None:
            return None
        weeks = _weeks(_schedule(cache, live=False), season)
    except Exception:  # noqa: BLE001 — the per-sale view still prints
        return None
    tuesdays = {}
    for week, days in weeks.items():
        first = date.fromisoformat(min(days))
        tuesdays[week] = first - timedelta(days=(first.weekday() - 1) % 7 or 7)
    return tuesdays, stop.date()


def monthly_by_join_week(calendar: tuple[dict[int, date], date]) -> list[dict]:
    """For each week a monthly buyer could join (on that week's report
    Tuesday): the charges they pay, the total, and the weekly reports they
    get — beside the $39 pass, which is disclosure here, never argument."""
    tuesdays, stop = calendar
    last = max(tuesdays)
    rows = []
    for week in sorted(tuesdays):
        joined = tuesdays[week]
        if joined > stop:
            continue
        full, stub = monthly_charges(joined, stop)
        rows.append({"week": week, "joined": joined, "charges": full + (1 if stub else 0),
                     "stub": stub, "paid": round(full * MONTHLY + stub, 2),
                     "reports": last - week + 1})
    return rows


def ltv(price: float, renewal: float) -> float:
    """Net over two seasons: this one, plus a renewal at ``renewal`` (the
    renewal pays Stripe and runs the same refund and dispute odds)."""
    return round(net_per_sale(price) * (1 + renewal), 2)


def owner_hours() -> float:
    return round(sum(OWNER_HOURS.values()), 1)


def base_case_net() -> float:
    """This season's net on the audit's base case, after fixed costs."""
    gross = (BASE_CASE["season"] * net_per_sale(SEASON)
             + BASE_CASE["league_pass"] * net_per_sale(LEAGUE_PASS))
    return round(gross - sum(FIXED_SEASON_COSTS.values()), 2)


def customer_lines(calendar=None) -> list[str]:
    """The customer view, as printed lines with their assumptions."""
    lines = ["PER CUSTOMER (assumptions, not forecasts — never on a selling page)", ""]
    cal = calendar if calendar is not None else season_calendar()
    if cal is None:
        lines.append("  Monthly by join week: the schedule can't say (offseason or cold cache).")
    else:
        lines.append(f"  Monthly, by the week they join (the last report is {cal[1]:%b %-d}; "
                     f"joins on the report Tuesday):")
        for row in monthly_by_join_week(cal):
            plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"  # noqa: E731
            lines.append(f"    Week {row['week']:>2}: {plural(row['charges'], 'charge')}, "
                         f"${row['paid']:6.2f} · "
                         f"{plural(row['reports'], 'weekly report')}")
        lines.append(f"    (the season pass is ${SEASON:.0f} whichever week they join)")
    lines.append("")
    lines.append("  Two seasons, net of Stripe, refunds and disputes, at a stated renewal rate:")
    for rate in RENEWAL_RATES:
        lines.append(f"    {rate:.0%} renew: season pass ${ltv(SEASON, rate):6.2f} · "
                     f"League Pass ${ltv(LEAGUE_PASS, rate):6.2f}")
    lines.append("    Monthly stops itself at season's end: a 2027 return is a new signup.")
    lines.append("")
    hours, net = owner_hours(), base_case_net()
    lines.append(f"  Owner time this season: about {hours:.0f} h "
                 + "(" + "; ".join(f"{k} {v:.0f} h" for k, v in OWNER_HOURS.items()) + ")")
    lines.append(f"  Base case ({BASE_CASE['season']} season passes + {BASE_CASE['league_pass']} "
                 f"League Passes): ${net:,.2f} after fixed costs — about ${net / hours:.2f} an "
                 f"hour ({HOURLY_NOTE})")
    return lines


# --------------------------------------------------------------------- #
# the documents quote this model (GATE-18)
# --------------------------------------------------------------------- #

def model_figures() -> dict[str, dict[str, float]]:
    """The fee figures a document may quote, by kind: what Stripe keeps on a
    charge (which is what a refund costs), and what that saves against
    Substack's cut."""
    fees = {}
    for name, price in (("season pass", SEASON), ("monthly charge", MONTHLY),
                        ("League Pass", LEAGUE_PASS)):
        fees[f"{name} fee"] = stripe_fee(price)
        fees[f"{name} fee, USD payout"] = stripe_fee(price, usd_payout=True)
        # The part a USD payout account saves — itself a fee a refund keeps.
        fees[f"{name} currency conversion"] = round(stripe_fee(price)
                                                    - stripe_fee(price, usd_payout=True), 2)
    savings = {f"saving vs Substack on a {name}": round(SUBSTACK_CUT * price - stripe_fee(price), 2)
               for name, price in (("season pass", SEASON), ("League Pass", LEAGUE_PASS))}
    return {"fee": fees, "saving": savings}


TOLERANCE = 0.25
# Below this a dollar figure in a fee sentence is a fee; at or above it, it is
# a price or a total (prices are excluded by name too).
FEE_CEILING = 8.0
_PRICES = {SEASON, MONTHLY, LEAGUE_PASS, 29.0, 12.99, 9.99}
_AMOUNT = re.compile(r"(?<![A-Z])\$(\d+(?:\.\d+)?)(?:\s*[–-]\s*\$?(\d+(?:\.\d+)?))?")


def _sentences(text: str) -> list[str]:
    """Hand-wrapped markdown read as sentences: paragraphs and table rows
    joined, then split at sentence ends."""
    out = []
    for block in re.split(r"\n\s*\n|\n(?=\|)|\n(?=\s*[-*] )|\n(?=\s*\d+\. )", text):
        flat = " ".join(block.split())
        out += [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(*])", flat) if s]
    return out


def doc_fee_mismatches(text: str, source: str) -> list[str]:
    """Every dollar figure a sentence about Stripe's fee or a refund's cost
    quotes that no figure of this model is within ±$0.25 of. A refund sentence
    is held to the fee figures (a refund keeps the fee); a saving sentence to
    the savings; anything else about the fee to either."""
    figures = model_figures()
    bad = []
    for sentence in _sentences(text):
        low = sentence.lower()
        if not re.search(r"\bfee|\brefund|stripe (keeps|takes|costs)", low):
            continue
        pool = (figures["fee"] if "refund" in low
                else figures["saving"] if "save" in low
                else {**figures["fee"], **figures["saving"]})
        for match in _AMOUNT.finditer(sentence):
            for raw in (match.group(1), match.group(2)):
                if raw is None:
                    continue
                value = float(raw)
                if value >= FEE_CEILING or value in _PRICES:
                    continue
                if not any(abs(value - v) <= TOLERANCE for v in pool.values()):
                    near = min(pool.items(), key=lambda kv: abs(kv[1] - value))
                    bad.append(f"{source}: ${raw} in “{sentence[:70]}…” "
                               f"(the model's nearest is {near[0]} ${near[1]:.2f})")
    return bad


READINESS = REPO_ROOT / "reports" / "launch-readiness.md"
FEE_DOCS = (REPO_ROOT / "PLAN.md", REPO_ROOT / "LAUNCH.md", READINESS)


def docs_fee_mismatches(paths: tuple[Path, ...] | None = None) -> list[str]:
    out = []
    for path in paths or FEE_DOCS:
        try:
            out += doc_fee_mismatches(path.read_text(encoding="utf-8"), path.name)
        except OSError:
            out.append(f"{path.name}: unreadable")
    return out


def base_case_figures() -> tuple[str, str, str]:
    """The base case as reports/launch-readiness.md states it: the season's
    net after fixed costs, the owner's hours, and what that earns an hour."""
    net, hours = base_case_net(), owner_hours()
    return (f"about ${net:,.0f}", f"about {hours:.0f} hours", f"about ${net / hours:.0f} an hour")


def readiness_base_case_mismatches(path: Path | None = None) -> list[str]:
    """Each base-case figure the model computes that launch-readiness.md does
    not state (G26). The audit put the season at about 64 owner-hours and $17
    an hour while this model counted 20 selling minutes a day and printed $26
    — two documents the owner reads, two different answers to "is this worth
    my time?". Read whitespace-normalised, so a hand-wrapped line still
    counts."""
    path = path or READINESS
    try:
        text = " ".join(path.read_text(encoding="utf-8").split())
    except OSError:
        return [f"{path.name}: unreadable"]
    return [f"{path.name} does not state {figure!r}"
            for figure in base_case_figures() if figure not in text]


def summary_lines() -> list[tuple[str, str, str]]:
    """(gate, status, detail) rows for `make launch-check`."""
    import os
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
                 f"recipients. With the owner's ~{owner_hours():.0f} h, the base case earns "
                 f"about ${base_case_net() / owner_hours():.0f} an hour"))
    saving = round(stripe_fee(SEASON) - stripe_fee(SEASON, usd_payout=True), 2)
    usd = os.environ.get("STRIPE_PAYOUT_CURRENCY", "").lower() == "usd"
    rows.append(("Payouts in USD keep the currency-conversion fee",
                 "PASS" if usd else "WARN",
                 "USD payout account in use" if usd else
                 f"paid out in CAD: ${saving:.2f} more of every $39 pass goes to conversion, "
                 f"kept on every refund — decide in LAUNCH.md section 10, then set "
                 f"STRIPE_PAYOUT_CURRENCY=usd here"))
    try:
        plan = (REPO_ROOT / "PLAN.md").read_text(encoding="utf-8")
        stale = "| Stripe | 2.9% + 30¢ per charge |" in plan or "3.7%" in plan
    except OSError:
        stale = False
    mismatched = docs_fee_mismatches() + readiness_base_case_mismatches()
    rows.append(("PLAN.md's fee figure matches this model",
                 "WARN" if stale else "PASS",
                 "PLAN.md still assumes 3.7% — the real figure is about "
                 f"{fee / SEASON:.1%}" if stale else f"about {fee / SEASON:.1%}"))
    rows.append(("Every fee, refund-cost and base-case figure in PLAN.md, LAUNCH.md and "
                 "launch-readiness.md matches this model",
                 "FAIL" if mismatched else "PASS",
                 "; ".join(mismatched[:3]) if mismatched else
                 f"fees within ±${TOLERANCE:.2f} of run/economics.py; base case "
                 + ", ".join(base_case_figures())))
    return rows


def main(argv: list[str] | None = None) -> int:
    print("UNIT ECONOMICS (assumptions at the top of run/economics.py)\n")
    print("PER SALE")
    for plan, price in (("Season pass", SEASON), ("Monthly charge", MONTHLY),
                        ("League Pass", LEAGUE_PASS)):
        print(f"  {plan:15} ${price:>6.2f}  Stripe ${stripe_fee(price):5.2f}  "
              f"net ${net_per_sale(price):6.2f}")
    print()
    for gate, _status, detail in summary_lines():
        print(f"  {gate}: {detail}")
    print()
    for line in customer_lines():
        print(line)
    print(f"\n  GST/HST registration only past C${GST_HST_THRESHOLD_CAD:,} of "
          f"worldwide sales in four quarters (not tax advice).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
