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
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render.welcome import (MONTHLY_PRICE, PASS_PRICE, SEASON_2027_PRICE,  # noqa: E402
                            SEASON_PRICE, TERMS_VERSION, first_renewal_words)
from run.checkout import (SEASON_2027_LINK_PREFIX, link_map_problems,  # noqa: E402
                          parse_link_plans, parse_link_prefixes)

API = "https://api.stripe.com/v1/payment_links"

# Restricted (rk_) or secret (sk_), live or test. Checked BEFORE the first
# request so a mistyped password never reaches Stripe's servers.
KEY_SHAPE = re.compile(r"^[rs]k_(live|test)_[A-Za-z0-9]{20,}$")

CANCEL = ("you can cancel any time from your billing page")

# The renewal sentence must say what terms.html §3 says: once a year, on the
# anniversary of the purchase. It said "each season", which no code enforces
# and the terms contradict (launch audit, Oct 2026).
# 2026 sells ONE-TIME passes (owner decision, Oct 18 2026): the season and
# League Pass links are in payment mode, and the $19 Playoff Pass link (o:)
# carries the season plan's words too — so these carry no price (Stripe shows
# the amount beside them) and promise only what is true of all three: one
# payment, and the refund window terms.html §5 gives every plan (OPS-1: the
# refund term sits beside every price, the Pay button included).
ONE_TIME_COVERS = ("It covers every weekly report from today through the "
                   "season's last")
REFUND = ("Full refund, no questions, until your first weekly report's week "
          "kicks off (or a week after it reaches you, if we send it late)")
ONE_TIME = ("One payment — no subscription, nothing to cancel. Nothing renews and nothing more is "
            f"ever charged. {ONE_TIME_COVERS}. {REFUND} — one per person.")
MESSAGES = {
    "season": ONE_TIME,
    "monthly": (
        f"Bills {MONTHLY_PRICE} USD monthly until you cancel. Billing stops on "
        f"its own after the season's last weekly report: your last charge is "
        f"the month that report falls in, and nothing is charged after it. "
        f"{CANCEL[0].upper()}{CANCEL[1:]}."),
    "league_pass": ("One payment — no subscription, nothing to cancel. Nothing renews and "
                    f"nothing more is ever charged. {ONE_TIME_COVERS}, for every manager "
                    f"in your league who claims a seat. {REFUND} — one per league."),
}
# The 2027 Season Pass (``y:``) is the one link in the map that renews, so its
# words name the renewal, its date and its amount. Beside MESSAGES, not in it:
# that dict is the 2026 plans, and ``plan`` here is a link's wording, not a
# registry plan. The date is the one run/billing.py writes to Stripe.
SEASON_2027_PLAN = "season_2027"
SEASON_2027 = (f"{SEASON_2027_PRICE} USD today covers every weekly report for the rest "
               f"of the 2026 season and all of the 2027 season. It renews at "
               f"{SEASON_2027_PRICE} USD on {first_renewal_words()}, and each August after "
               f"that, until you cancel. We email you 15 to 45 days before each renewal, "
               f"and {CANCEL}. {REFUND} — one per person.")
# Stripe's limit on both custom_text messages (Payment Links API).
STRIPE_TEXT_LIMIT = 1200

# The box the buyer ticks. California's auto-renewal law wants affirmative
# consent to the renewal terms and a record of it; Stripe records the tick on
# the Checkout Session (consent.terms_of_service = "accepted"), and the intake
# copies it onto the Customer with the terms version (run/intake.py). Needs the
# Terms of service URL set in Stripe -> Settings -> Business -> Public details.
TERMS_URL = "https://beatyourleague.com/terms.html"
TOS_MESSAGES = {
    "season": (f"I agree to the [Terms]({TERMS_URL}), including that this pass "
               f"is one payment that does not renew, and I am 18 or older."),
    "monthly": (f"I agree to the [Terms]({TERMS_URL}), including that this plan "
                f"bills {MONTHLY_PRICE} USD every month until I cancel or it stops "
                f"on its own after the season's last weekly report, and I am 18 or "
                f"older."),
    "league_pass": (f"I agree to the [Terms]({TERMS_URL}), including that this "
                    f"League Pass is one payment that does not renew, and I am 18 "
                    f"or older."),
}
# The box the law wants ticked for a renewal: the amount, the date, the cycle.
SEASON_2027_TOS = (f"I agree to the [Terms]({TERMS_URL}), including that this pass "
                   f"renews at {SEASON_2027_PRICE} USD on {first_renewal_words()} and "
                   f"each August after that until I cancel, and I am 18 or older.")
SUBMIT_TEXT = {**MESSAGES, SEASON_2027_PLAN: SEASON_2027}
TOS_TEXT = {**TOS_MESSAGES, SEASON_2027_PLAN: SEASON_2027_TOS}


def fields(plan: str) -> dict[str, str]:
    """Everything this script writes onto one payment link."""
    one_time = plan in ("season", "league_pass")
    return {**({"customer_creation": "always"} if one_time else {}),
            # A one-time payment makes no Customer unless told to, and the
            # intake keeps the consent record and roster on the Customer.
            "custom_text[submit][message]": SUBMIT_TEXT[plan],
            "consent_collection[terms_of_service]": "required",
            "custom_text[terms_of_service_acceptance][message]": TOS_TEXT[plan]}


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


SHAPE = "s:plink_…,o:plink_…,p:plink_…"


def targets(raw: str) -> list[tuple[str, str]]:
    """(link, plan) for every link this script writes, in the map's order —
    one entry per LINK, never per plan: the $29 and $19 passes are both the
    season plan, and inverting the map to {plan: link} kept only one of them,
    so the other never got its one-payment text, refund term or 18+ box
    (final review OPS-1). Refuses (SystemExit, before any key is asked for)
    unless the map is the 2026 shape (``SHAPE``; ``m:`` optional, for a
    monthly plan). The check is run/checkout.link_map_problems, the same one
    the launch check reads.

    A ``y:`` link is the season PLAN but never the season WORDS: read off the
    plan alone, this script would write "One payment. Nothing renews" onto
    the one link that renews, and over the renewal text a buyer must see."""
    problems = link_map_problems(raw)
    if problems:
        raise SystemExit(
            "STRIPE_PAYMENT_LINKS is not the shape this script writes:\n  - "
            + "\n  - ".join(problems)
            + f"\nExpected {SHAPE} (the $29, $19 and $69 links; add m:plink_… only "
              f"for a monthly plan). Nothing was changed.")
    prefixes = parse_link_prefixes(raw)
    return [(link, SEASON_2027_PLAN if prefixes.get(link) == SEASON_2027_LINK_PREFIX else plan)
            for link, plan in parse_link_plans(raw).items() if plan in MESSAGES]


def main() -> int:
    raw = os.environ.get("STRIPE_PAYMENT_LINKS", "").strip()
    if not raw:
        print("Paste your STRIPE_PAYMENT_LINKS value — the same string you put")
        print(f"in the GitHub secret, e.g.  {SHAPE}")
        raw = input("> ").strip()

    links = targets(raw)

    print(f"\nThis writes the one-payment and refund text onto {len(links)} Stripe "
          f"payment links.")
    print("Use the throwaway `setup-payment-link-text` key, not the cron key.")
    print()
    print("  >>> This is NOT your Mac password and NOT your Stripe login. <<<")
    print("  Paste the STRIPE RESTRICTED KEY. It starts with 'rk_' and is about")
    print("  100 characters long. Find it at: dashboard.stripe.com ->")
    print("  Developers -> API keys.  Nothing will appear as you paste.")
    print()
    key = getpass.getpass("Stripe restricted key (starts rk_): ").strip()
    if not key:
        raise SystemExit("No key given — nothing was changed.")
    # CHECK THE SHAPE BEFORE ANY NETWORK CALL. A hidden prompt in a terminal
    # reads as a system password prompt, and the owner typed his password into
    # it — which this script then sent to Stripe, where it landed in a
    # failed-auth log. A password must never leave the machine because of a
    # misread prompt, so anything not shaped like a Stripe key is refused here.
    if not KEY_SHAPE.match(key):
        raise SystemExit(
            "\nThat does not look like a Stripe key, so it was NOT sent anywhere.\n"
            "  A Stripe key looks like:  rk_live_51AbCdEf...  (or rk_test_...)\n"
            "  It is about 100 characters and contains no spaces.\n"
            "  You may have pasted a password — if so, nothing was transmitted,\n"
            "  but change it anyway if you typed it somewhere else too.\n"
            "  Find the key: dashboard.stripe.com -> Developers -> API keys\n")

    print()
    for link, plan in links:
        _call(f"{API}/{urllib.parse.quote(link)}", key, fields(plan))
        # Read it back rather than trusting the write: a 200 says Stripe
        # accepted the request, not that the field says what we meant.
        back = _call(f"{API}/{urllib.parse.quote(link)}", key)
        custom = back.get("custom_text") or {}
        got = (custom.get("submit") or {}).get("message")
        tos = (custom.get("terms_of_service_acceptance") or {}).get("message")
        consent = (back.get("consent_collection") or {}).get("terms_of_service")
        ok = got == SUBMIT_TEXT[plan] and tos == TOS_TEXT[plan] and consent == "required"
        print(f"  [{'ok ' if ok else 'FAIL'}] {plan:12} {link}")
        print(f"         {(got or 'MISSING')[:96]}")
        if not ok:
            raise SystemExit("\nStripe stored something other than what we sent.")

    print(f"\nAll {len(links)} set and verified.")
    print("NOW DELETE the setup-payment-link-text key in Stripe:")
    print("  Developers -> API keys -> setup-payment-link-text -> delete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
