"""Who is actually paying right now — the gate between the registry and the send.

Cancellation has to cost the operator nothing, and neither does entitlement:
nobody should have to review an inbox or maintain a list to decide who gets
Tuesday's report. Our reports are personalised and therefore sent directly, so
the pipeline has to learn who left, or it would mail a cancelled subscriber
every Tuesday forever.

Two sources, same answer shape (``PaidList``), chosen by config alone:

* **Stripe** (preferred, ``STRIPE_API_KEY`` set) — ask the payment processor
  directly. Zero manual steps, and the entitlement question is answered by the
  system that actually took the money.
* **CSV export** (fallback) — a Substack subscriber export dropped in place.
  Substack has no public subscriber API, so a periodic export is the honest
  mechanism. Column names differ between exports, so the parser is deliberately
  tolerant: it finds the email column by name and looks for any recognisable
  status/plan column. When it cannot find a status column at all it says so
  rather than guessing — treating "I don't know" as "everyone is paid" is how
  cancelled people keep getting billed-for product.

``resolve_paid_list()`` picks between them, so the batch never learns which one
answered and switching platforms is a secret, not a rewrite.
"""

from __future__ import annotations

import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXPORT = REPO_ROOT / "data" / "registry" / "substack-export.csv"

# Header names seen across Substack exports, lowercased.
_EMAIL_COLUMNS = ("email", "email address", "subscriber email")
_STATUS_COLUMNS = ("active_subscription", "active subscription", "subscription status",
                   "status", "plan", "type", "subscription")
# Values that mean "this person is currently paying us".
_PAID_VALUES = {"true", "t", "yes", "y", "1", "paid", "active", "comped",
                "premium", "founding", "monthly", "annual", "gift"}
_UNPAID_VALUES = {"false", "f", "no", "n", "0", "free", "none", "cancelled",
                  "canceled", "expired", "inactive", "unsubscribed"}


class SubscriptionError(ValueError):
    """The paid list cannot be trusted, so the run must not guess."""


@dataclass(frozen=True)
class PaidList:
    emails: frozenset[str]
    source: Path | str
    status_column: str | None
    # Stripe only. Customer ids are the durable join key — see Subscriber
    # .stripe_customer_id for why an email is not one.
    customer_ids: frozenset[str] = frozenset()
    # Leagues covered by an entitled League Pass, read from the payer's own
    # Stripe record rather than from a covered_by email somebody typed.
    covered_leagues: frozenset[str] = frozenset()
    # RULE E1. Subscriptions dropped because the money went back — reported by
    # the run so a revoked entitlement is a visible event rather than a
    # subscriber who quietly stopped appearing.
    refunded: frozenset[str] = frozenset()

    def covers(self, email: str) -> bool:
        return email.strip().lower() in self.emails

    def entitles(self, subscriber) -> bool:
        """Is this subscriber entitled to this week's report?

        Three routes, most durable first:
          1. their Stripe customer is paying (survives an email change);
          2. their league is covered by somebody's League Pass;
          3. the email on file is paying — the fallback for hand-added entries
             and for the CSV path, which has no customer ids at all.
        """
        customer = getattr(subscriber, "stripe_customer_id", None)
        if customer and customer in self.customer_ids:
            return True
        league = getattr(subscriber, "league_id", None)
        if league and league in self.covered_leagues:
            return True
        payer = getattr(subscriber, "covered_by", None) or subscriber.email
        # A seat whose payer cannot be found is NOT entitled — a League Pass
        # seat must die with the pass that bought it, or a lapsed commissioner
        # leaves eleven people receiving a product nobody is paying for.
        return self.covers(payer)


# --------------------------------------------------------------------- #
# Stripe: ask the payment processor directly, so nothing is exported by hand
# --------------------------------------------------------------------- #

# Statuses that mean "this person is entitled to this week's report".
# 'active' is the important one: when a subscriber cancels, Stripe leaves the
# subscription active with cancel_at_period_end until the period they paid for
# actually ends — which is exactly "they paid for a period and we're still in
# it". 'trialing' counts too. 'past_due' deliberately does NOT: the payment
# failed, Stripe is retrying, and it flips back to active on its own if it
# succeeds. Sending during that window is giving away the product on a card
# that bounced.
_ENTITLED_STATUSES = ("active", "trialing")

# RULE E1 — A REFUND ENDS ENTITLEMENT, EVEN WHILE THE SUBSCRIPTION IS ACTIVE.
#
# Refunding a charge does not change the subscription's status: Stripe leaves
# it `active`, so the statuses above kept answering yes and the subscriber kept
# receiving a report every Tuesday for money they had been given back. On a
# season pass that runs for a YEAR. It needs no bad intent to happen — refunding
# and forgetting to cancel is one missed click in the Dashboard — which is
# exactly why it cannot be left to the operator's memory.
#
# Only a FULL refund revokes. A partial one is how a pro-rata goodwill
# adjustment is issued (the terms offer one for a mid-term change), and treating
# that as "no longer a customer" would cut off somebody we had just apologised
# to. Read from the latest invoice's own charge, expanded in the same list call,
# so this costs no extra request per subscriber.
REFUND_REVOKES = True

STRIPE_API = "https://api.stripe.com/v1/subscriptions"

# Customer-metadata keys written by run/sync.py. Namespaced so we never collide
# with anything the operator sets by hand in the Stripe dashboard.
PASS_LEAGUE_KEY = "byl_pass_league"


def _stripe_get(url: str, api_key: str) -> dict:
    request = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": f"Bearer {api_key}",
                 "Stripe-Version": "2024-06-20"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never echo the request — it carries the secret key.
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise SubscriptionError(
            f"Stripe returned HTTP {exc.code}. Check STRIPE_API_KEY is a valid "
            f"secret key with read access. Response: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SubscriptionError(f"could not reach Stripe: {exc}") from None
    except json.JSONDecodeError:
        raise SubscriptionError("Stripe returned a response we could not read") from None


def fully_refunded(subscription: Mapping[str, Any]) -> bool:
    """Has the money for the period we are in been given back in full?

    RULE E1. Read off the latest invoice's own charge, which the list call
    expands. Everything is checked before it is trusted, because this is
    external input and a wrong answer goes one of two bad ways: too eager and a
    paying subscriber is silently dropped, too shy and a refunded one keeps
    being served for a year.

    A PARTIAL refund deliberately does not revoke — that is how a pro-rata
    goodwill adjustment is issued, and cutting somebody off mid-apology would
    be worse than the problem this solves.
    """
    invoice = subscription.get("latest_invoice")
    if not isinstance(invoice, dict):
        return False                      # unexpanded or absent: claim nothing
    charge = invoice.get("charge")
    if not isinstance(charge, dict):
        return False
    if charge.get("refunded") is True:
        return True                       # Stripe's own "fully refunded" flag
    # Belt and braces: the flag is what Stripe sets, the arithmetic is what is
    # true. A charge refunded to the penny by several partial refunds is fully
    # refunded whatever the flag says.
    amount = charge.get("amount")
    returned = charge.get("amount_refunded")
    if isinstance(amount, int) and isinstance(returned, int) and amount > 0:
        return returned >= amount
    return False


def load_paid_from_stripe(api_key: str | None = None,
                          statuses: Iterable[str] = _ENTITLED_STATUSES) -> PaidList:
    """Every email currently entitled to a report, straight from Stripe.

    No export, no file, no manual step: the Tuesday run asks Stripe who is
    paying and mails exactly those people.
    """
    key = api_key or os.environ.get("STRIPE_API_KEY", "")
    if not key:
        raise SubscriptionError(
            "STRIPE_API_KEY is not set. Add it as a secret (a restricted key with "
            "read access to subscriptions and customers is enough), or point "
            "--paid-list at a CSV export instead.")
    emails: set[str] = set()
    customer_ids: set[str] = set()
    covered_leagues: set[str] = set()
    refunded: list[str] = []
    for status in statuses:
        # A LIST of pairs, not a dict: `expand[]` has to repeat, and a dict can
        # only carry it once. RULE E1's expansion is the second one, answered in
        # the same request rather than one extra call per subscriber every week.
        params = [("status", status), ("limit", "100"),
                  ("expand[]", "data.customer"),
                  ("expand[]", "data.latest_invoice.charge")]
        url = f"{STRIPE_API}?{urllib.parse.urlencode(params)}"
        while True:
            page = _stripe_get(url, key)
            data = page.get("data")
            data = data if isinstance(data, list) else []
            for subscription in data:
                # Stripe's response is external input like every other feed:
                # anything unexpected is skipped, never assumed.
                if not isinstance(subscription, dict):
                    continue
                customer = subscription.get("customer")
                if not isinstance(customer, dict) or customer.get("deleted"):
                    # An unexpanded id, or a deleted customer, has no usable
                    # email — and we will not mail an address we cannot read.
                    continue
                # RULE E1, applied before a single identifier is collected: a
                # fully refunded subscriber must not reach `emails`,
                # `customer_ids` OR `covered_leagues` — a League Pass payer who
                # was refunded would otherwise keep eleven other people served.
                if fully_refunded(subscription):
                    refunded.append(str(subscription.get("id")))
                    continue
                email = (customer.get("email") or "").strip().lower()
                if email:
                    emails.add(email)
                customer_id = customer.get("id")
                if isinstance(customer_id, str) and customer_id:
                    customer_ids.add(customer_id)
                # A League Pass covers a whole league. run/sync.py stamps the
                # league onto the payer's customer record at first sight, so
                # coverage is answered here without listing sessions — and it
                # lapses the moment the payer's subscription does.
                metadata = customer.get("metadata")
                league = (metadata or {}).get(PASS_LEAGUE_KEY) if isinstance(metadata, dict) else None
                if isinstance(league, str) and league.strip().isdigit():
                    covered_leagues.add(league.strip())
            last_id = data[-1].get("id") if data and isinstance(data[-1], dict) else None
            if not page.get("has_more") or not last_id:
                break
            url = (f"{STRIPE_API}?{urllib.parse.urlencode(params)}"
                   f"&starting_after={urllib.parse.quote(str(last_id))}")
    return PaidList(emails=frozenset(emails), source="stripe",
                    status_column=",".join(statuses),
                    customer_ids=frozenset(customer_ids),
                    covered_leagues=frozenset(covered_leagues),
                    refunded=frozenset(refunded))


def resolve_paid_list(csv_path: Path | None = None) -> PaidList:
    """Prefer Stripe when it's configured; fall back to a CSV export.

    This is what makes the platform choice a config change rather than a
    rewrite: the batch run never learns which one answered.
    """
    if os.environ.get("STRIPE_API_KEY"):
        return load_paid_from_stripe()
    path = csv_path or DEFAULT_EXPORT
    if not path.is_file():
        # Name the recommended fix first: the whole point is that nobody has to
        # produce this file by hand every week.
        raise SubscriptionError(
            "no way to tell who is currently paying, so this run will not mail "
            "anyone.\n"
            "  Recommended: set STRIPE_API_KEY (a restricted key with read access "
            "to subscriptions and customers) and the run asks Stripe directly — "
            "no export, no manual step.\n"
            f"  Or: save a subscriber CSV export at {path}.\n"
            "  Or: pass --no-paid-check to send to everyone in the registry anyway.")
    return load_paid_list(path)


def _pick(header: Iterable[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {h.strip().lower(): h for h in header if h}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def load_paid_list(path: Path = DEFAULT_EXPORT) -> PaidList:
    """Parse a Substack export into the set of currently-paying emails."""
    if not path.is_file():
        raise SubscriptionError(
            f"no subscriber export at {path}. Export subscribers from Substack "
            "(Dashboard -> Subscribers -> Export) and save the CSV there, or pass "
            "--no-paid-check to send to everyone in the registry anyway.")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SubscriptionError(f"{path} has no header row")
        email_col = _pick(reader.fieldnames, _EMAIL_COLUMNS)
        if not email_col:
            raise SubscriptionError(
                f"{path} has no email column (looked for {_EMAIL_COLUMNS}); "
                f"found {reader.fieldnames}")
        status_col = _pick(reader.fieldnames, _STATUS_COLUMNS)
        paid: set[str] = set()
        for row in reader:
            email = (row.get(email_col) or "").strip().lower()
            if not email:
                continue
            if status_col is None:
                # No status column: the export is a plain list, so presence is
                # the only signal we have. Callers are told, and decide.
                paid.add(email)
                continue
            value = (row.get(status_col) or "").strip().lower()
            if value in _PAID_VALUES:
                paid.add(email)
            elif value in _UNPAID_VALUES:
                continue
            else:
                # An unrecognised status is not a licence to bill someone's
                # inbox — skip it and let the summary show the shortfall.
                continue
    return PaidList(emails=frozenset(paid), source=path, status_column=status_col)
