"""Send the pre-renewal reminders that five surfaces promise.

Usage:
    python -m run.renewals              # dry by default, like every sender here
    python -m run.renewals --send

Runs daily. The window it serves is 15-45 days wide (render/renewal.py), so a
missed day costs nothing and a duplicate is impossible — the send log is keyed
on the renewal DATE, so one subscriber gets one notice per renewal and next
year's gets its own.

What this refuses to do, deliberately:

- **It never invents the amount or the date.** Both come from the Stripe
  subscription that will actually be charged. A founding subscriber renews at
  the price they joined at (legal §3), which our own price constants do not
  know, and a reminder quoting the wrong figure is worse than none.
- **It skips subscriptions already set to cancel.** They are ending, not
  renewing; telling that person we are about to charge them is a false
  statement about their money.
- **It skips anything that is not a yearly term.** The monthly plan stops on
  its own at season's end and the statute does not reach it.
- With no ``STRIPE_API_KEY`` it exits 2 — the expected state before checkout
  opens, and the same not-configured contract the intake uses, so a daily
  cron does not file a bug every morning for a shop that has not opened.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

from render.renewal import LEAD_MAX_DAYS, Renewal, due, renewal_message
from run.checkout import _stripe_get
from run.delivery import DRY_PROVIDER, DeliveryError, build_provider, send_all
from run.subscriptions import SubscriptionError

STRIPE_SUBSCRIPTIONS = "https://api.stripe.com/v1/subscriptions"
NOT_CONFIGURED = 2
# A yearly term is what the statute reaches. Stripe reports the interval on
# the price; anything else is out of scope for this notice.
YEARLY = "year"


def _money(amount: object, currency: object) -> str:
    """Stripe's minor units, formatted for a human. Untrusted input like every
    other field: anything unexpected yields an empty string, and the caller
    skips a renewal it cannot state a price for rather than guessing one."""
    if not isinstance(amount, int):
        return ""
    code = str(currency or "").upper() or "USD"
    symbol = {"USD": "$", "CAD": "CA$", "GBP": "£", "EUR": "€"}.get(code, "")
    return f"{symbol}{amount / 100:,.2f} {code}"


def upcoming(api_key: str, today: date) -> tuple[list[Renewal], list[str]]:
    """Every yearly subscription due to renew inside the notice window.

    Returns (renewals, problems). A subscription we cannot read cleanly is a
    problem to report, never a reminder to guess at.
    """
    renewals: list[Renewal] = []
    problems: list[str] = []
    for status in ("active", "trialing"):
        params = {"status": status, "limit": "100", "expand[]": "data.customer"}
        url = f"{STRIPE_SUBSCRIPTIONS}?{urllib.parse.urlencode(params)}"
        while True:
            page = _stripe_get(url, api_key)
            data = page.get("data")
            data = data if isinstance(data, list) else []
            for subscription in data:
                if not isinstance(subscription, dict):
                    continue
                if (subscription.get("cancel_at_period_end")
                        or isinstance(subscription.get("cancel_at"), int)):
                    # Ending, not renewing. No notice is owed and a notice
                    # would be false.
                    #
                    # `cancel_at` belongs beside `cancel_at_period_end` and was
                    # missing: the two are different ways to say the same thing,
                    # and reading only one was harmless only for as long as
                    # nothing in the repo set the other. run/billing.py now
                    # sets `cancel_at`, so this became live the day it shipped —
                    # a subscription scheduled to end would have been told "we
                    # are about to charge you $39", which is the false statement
                    # about somebody's money this module's first rule exists to
                    # prevent.
                    continue
                item = _first_item(subscription)
                price = (item or {}).get("price")
                recurring = (price or {}).get("recurring")
                interval = (recurring or {}).get("interval")
                if interval != YEARLY:
                    continue
                period_end = subscription.get("current_period_end")
                if not isinstance(period_end, int):
                    problems.append("a yearly subscription has no readable "
                                    "renewal date — no notice sent")
                    continue
                renews_on = datetime.fromtimestamp(
                    period_end, timezone.utc).date()
                customer = subscription.get("customer")
                email = ""
                customer_id = None
                if isinstance(customer, dict) and not customer.get("deleted"):
                    email = (customer.get("email") or "").strip().lower()
                    cid = customer.get("id")
                    customer_id = cid if isinstance(cid, str) else None
                amount = _money((price or {}).get("unit_amount"),
                                (price or {}).get("currency"))
                if not email or not amount:
                    problems.append(
                        "a yearly subscription renewing "
                        f"{renews_on.isoformat()} has no readable address or "
                        f"price — no notice sent")
                    continue
                renewal = Renewal(email=email, amount=amount,
                                  renews_on=renews_on, interval=interval,
                                  customer_id=customer_id)
                if due(renewal, today):
                    renewals.append(renewal)
            last = data[-1].get("id") if data and isinstance(data[-1], dict) else None
            if not page.get("has_more") or not last:
                break
            url = (f"{STRIPE_SUBSCRIPTIONS}?{urllib.parse.urlencode(params)}"
                   f"&starting_after={urllib.parse.quote(str(last))}")
    renewals.sort(key=lambda r: (r.renews_on, r.slug))
    return renewals, problems


def _first_item(subscription: dict) -> dict | None:
    items = (subscription.get("items") or {}).get("data")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true",
                        help="actually send; without it nothing leaves")
    parser.add_argument("--today", help="ISO date, for rehearsing a window")
    args = parser.parse_args(argv)

    api_key = os.environ.get("STRIPE_API_KEY", "")
    if not api_key:
        print("STRIPE_API_KEY is not set — no subscriptions to read. That is "
              "expected until checkout opens.", file=sys.stderr)
        return NOT_CONFIGURED

    today = (date.fromisoformat(args.today) if args.today
             else datetime.now(timezone.utc).date())
    try:
        renewals, problems = upcoming(api_key, today)
    except (SubscriptionError, OSError) as exc:
        print(f"could not read Stripe: {exc}", file=sys.stderr)
        return 1

    line = "=" * 62
    print(f"{line}\nPRE-RENEWAL NOTICES · {today.isoformat()}\n{line}")
    print(f"{len(renewals)} subscription(s) renewing in "
          f"{LEAD_MAX_DAYS} days or fewer")
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)

    if not renewals:
        print(line)
        return 1 if problems else 0

    messages = [renewal_message(renewal) for renewal in renewals]
    if not args.send:
        for renewal in renewals:
            print(f"  [dry] renews {renewal.renews_on.isoformat()} · "
                  f"{renewal.amount} · {renewal.slug}")
        print("(dry run — nothing sent, nothing logged. Pass --send.)")
        print(line)
        return 0

    try:
        provider = build_provider(None)
    except DeliveryError as exc:
        print(f"delivery not configured: {exc}", file=sys.stderr)
        return 1
    results = send_all(messages, provider=provider)
    sent = sum(1 for r in results if r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = [r for r in results if not r.ok]
    for result in failed:
        print(f"  ! send failed: {result.detail}", file=sys.stderr)
    if provider.name == DRY_PROVIDER:
        print(f"{len(messages)} notice(s) drafted; NOTHING WAS SENT (no "
              f"EMAIL_PROVIDER set) and nothing was recorded.")
    else:
        print(f"{sent} sent, {skipped} already notified for this renewal")
    print(line)
    return 1 if failed or problems else 0


if __name__ == "__main__":
    sys.exit(main())
