"""Set the custom text above Stripe's Pay button — the one page we don't control.

Every renewal disclosure lives on our own surfaces, except the last one: the
Stripe checkout page. `custom_text[submit][message]` is API-only — the Dashboard
has no field for it — so it has to be set by a call like this one, and a buyer
who never reads the terms still meets the renewal terms at the moment of paying.

Run it, paste the key when asked, done:

    python3 infra/stripe_paylink_text.py

The key is read with getpass, so it never reaches your shell history and never
appears in the process list the way an argument would. Use the throwaway
`setup-payment-link-text` key (Payment Links write, nothing else) and delete it
afterwards — a key that can rewrite a payment link can change what a buyer is
charged, and the cron key must never hold that.

**The prices come from render/welcome.py, not from this file.** A test ties
those constants to the pricing page, so the sentence above Stripe's Pay button
cannot quietly disagree with the one beside the Buy button. That is the whole
reason this is a script and not three commands pasted into a doc.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render.welcome import MONTHLY_PRICE, PASS_PRICE, SEASON_PRICE  # noqa: E402
from run.checkout import parse_link_plans  # noqa: E402

API = "https://api.stripe.com/v1/payment_links"

CANCEL = ("you can cancel any time from your billing page")

MESSAGES = {
    "season": (
        f"Renews automatically each season at {SEASON_PRICE} USD unless you "
        f"cancel. We email you before any renewal, and {CANCEL} — the link is "
        f"in every report we send."),
    "monthly": (
        f"Bills {MONTHLY_PRICE} USD monthly until you cancel. Billing stops "
        f"automatically when the season ends — we never charge through the "
        f"offseason."),
    "league_pass": (
        f"Renews automatically each season at {PASS_PRICE} USD unless you "
        f"cancel. We email you before any renewal, and {CANCEL}."),
}


def _call(url: str, key: str, form: dict | None = None) -> dict:
    data = urllib.parse.urlencode(form).encode() if form else None
    request = urllib.request.Request(
        url, data=data, method="POST" if form else "GET",
        headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        # Never echo the request — it carries the key.
        raise SystemExit(
            f"\nStripe returned HTTP {exc.code}.\n"
            f"  401 means the key is wrong or mistyped.\n"
            f"  403 means it lacks Payment Links WRITE.\n"
            f"  Response: {detail}\n")


def main() -> int:
    raw = os.environ.get("STRIPE_PAYMENT_LINKS", "").strip()
    if not raw:
        print("Paste your STRIPE_PAYMENT_LINKS value — the same string you put")
        print("in the GitHub secret, e.g.  s:plink_A,m:plink_B,p:plink_C")
        raw = input("> ").strip()

    plans = parse_link_plans(raw)
    by_plan = {plan: link for link, plan in plans.items() if plan}
    missing = sorted(set(MESSAGES) - set(by_plan))
    if missing:
        raise SystemExit(
            f"No payment link given for: {', '.join(missing)}.\n"
            f"Expected all three, as s:plink_…,m:plink_…,p:plink_…")

    print("\nThis writes the renewal disclosure onto three Stripe payment links.")
    print("Use the throwaway `setup-payment-link-text` key, not the cron key.")
    key = getpass.getpass("Restricted key (hidden, not echoed): ").strip()
    if not key:
        raise SystemExit("No key given — nothing was changed.")

    print()
    for plan in ("season", "monthly", "league_pass"):
        link = by_plan[plan]
        _call(f"{API}/{urllib.parse.quote(link)}", key,
              {"custom_text[submit][message]": MESSAGES[plan]})
        # Read it back rather than trusting the write: a 200 says Stripe
        # accepted the request, not that the field says what we meant.
        back = _call(f"{API}/{urllib.parse.quote(link)}", key)
        got = ((back.get("custom_text") or {}).get("submit") or {}).get("message")
        ok = got == MESSAGES[plan]
        print(f"  [{'ok ' if ok else 'FAIL'}] {plan:12} {link}")
        print(f"         {(got or 'MISSING')[:96]}")
        if not ok:
            raise SystemExit("\nStripe stored something other than what we sent.")

    print("\nAll three set and verified.")
    print("NOW DELETE the setup-payment-link-text key in Stripe:")
    print("  Developers -> API keys -> setup-payment-link-text -> delete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
