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
import re
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
    """The paid list cannot be trusted, so the run must not guess.

    ``status`` is Stripe's HTTP status when Stripe answered with one (None
    for a network failure or an unreadable body): a 403 is a key missing a
    permission, which a caller can name rather than retry (final review
    OPS-5)."""

    def __init__(self, message: str = "", status: int | None = None,
                 permissions: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.status = status
        # The rak_ permission names a restricted key's 403 cites, read from the
        # whole body: the masked key alone runs past the 200-character excerpt.
        self.permissions = permissions


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
    # RULE E2 (Stripe only): the subscriptions that are entitled right now —
    # active or trialing, and not refunded in full. None on the CSV path,
    # which cannot tell one subscription from another.
    subscription_ids: frozenset[str] | None = None
    # Charges under an OPEN dispute (a chargeback): (subscription or payment
    # id, Stripe's dispute status). Still entitled — a dispute can be won —
    # but each one is an alarm: one that needs a response loses by default
    # when its deadline passes. A LOST dispute ends entitlement like a full
    # refund and is listed in ``refunded`` (pre-launch review, critique #2).
    disputes: tuple[tuple[str, str], ...] = ()
    # Why a disputed charge's status could not be read (usually a cron key
    # without Disputes: Read). Such a charge is listed as "unknown" and stays
    # entitled: a missing permission never stops delivery.
    dispute_errors: tuple[str, ...] = ()

    @property
    def disputes_needing_response(self) -> tuple[str, ...]:
        """The disputed purchases waiting on OUR evidence."""
        return tuple(i for i, state in self.disputes if state in DISPUTE_ACTION)

    def covers(self, email: str) -> bool:
        return email.strip().lower() in self.emails

    def entitles(self, subscriber) -> bool:
        """Is this subscriber entitled to this week's report?

        A paid row that names its own subscription(s) answers to those alone
        (D2, below). Otherwise three routes, most durable first:
          1. their Stripe customer is paying (survives an email change);
          2. their league is covered by somebody's League Pass;
          3. the email on file is paying — the fallback for hand-added entries
             and for the CSV path, which has no customer ids at all.

        A roster product League Pass SEAT answers to RULE E2 instead, below.
        """
        own = tuple(getattr(subscriber, "subscription_ids", ()) or ())
        if self.subscription_ids is not None and own:
            # D2 — A PAID ROW LIVES ON ITS OWN SUBSCRIPTION(S). Route 1 asked
            # "is this CUSTOMER paying", and route 3 "is this ADDRESS paying",
            # so somebody with two teams who cancelled one kept getting the
            # cancelled team's reports for as long as the other plan lasted
            # (reproduced, LEGAL-41) — "then they stop on their own" was false.
            # The row now names the subscription(s) that bought it (run/intake
            # stamps them); it is entitled while one of THOSE is, and the
            # customer/address routes below serve only rows that name none.
            return any(sub in self.subscription_ids for sub in own)
        customer = getattr(subscriber, "stripe_customer_id", None)
        if customer and customer in self.customer_ids:
            return True
        league = getattr(subscriber, "league_id", None)
        if league and league in self.covered_leagues:
            return True
        if (self.subscription_ids is not None and hasattr(subscriber, "pass_id")
                and getattr(subscriber, "covered_by", None)):
            # RULE E2 — A SEAT LIVES ON ITS PASS, NOT ON ITS PAYER'S ADDRESS.
            # Route 3 asked "does the payer's address hold ANY entitled
            # subscription", so a refunded or cancelled $99 pass kept eleven
            # seats served whenever the payer still had a $14.99 monthly
            # (reproduced, OPS-R4 / LP2-D2) — and a payer who changed their
            # billing email in the portal dropped every seat, because the seat
            # named the purchase-time address (OPS-R5). The seat now names the
            # pass subscription itself (run/intake.py stamps it from the
            # session the pass link took), which no email change moves and
            # which ends exactly when that pass does. A seat that names no
            # pass is not entitled: fail closed.
            return getattr(subscriber, "pass_id", None) in self.subscription_ids
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
        body = exc.read().decode("utf-8", "replace")
        detail = body[:200]
        named = tuple(sorted(set(re.findall(r"rak_[a-z_]+", body))))
        raise SubscriptionError(
            f"Stripe returned HTTP {exc.code}. Check STRIPE_API_KEY is a valid "
            f"secret key with read access. Response: {detail}",
            status=exc.code, permissions=named) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SubscriptionError(f"could not reach Stripe: {exc}") from None
    except json.JSONDecodeError:
        raise SubscriptionError("Stripe returned a response we could not read") from None


# Stripe's dispute statuses (Dispute.status), by what they mean for us.
DISPUTE_LOST = "lost"
# Waiting on our response: lost by default if nothing is submitted in time.
DISPUTE_ACTION = ("needs_response", "warning_needs_response")
# Evidence submitted (or an inquiry under review): open, nothing to do yet.
DISPUTE_REVIEW = ("under_review", "warning_under_review")
# Closed in our favour, or never became a chargeback.
DISPUTE_CLOSED = ("won", "warning_closed", "prevented")


DISPUTES_API = "https://api.stripe.com/v1/disputes"
# Worst first: when one charge carries several disputes (an inquiry, then the
# chargeback), the one that asks most of us decides.
_DISPUTE_RANK = (DISPUTE_LOST, *DISPUTE_ACTION, "unknown", *DISPUTE_REVIEW)


class DisputeLookup:
    """Stripe's dispute status for a DISPUTED charge, read with its own list
    call (``GET /v1/disputes?charge=…``) and only for a charge whose
    ``disputed`` flag is set — so an account with no chargebacks makes no
    extra request at all.

    Not an expansion: at the pinned API version (2024-06-20) a Charge has no
    ``dispute`` property (stripe-node v13 removed it; v16, which is
    2024-06-20, types only ``disputed: boolean``), so expanding
    ``latest_charge.dispute`` failed the whole entitlement read — every
    runner, every week (pre-launch review). A failed read here is recorded in
    ``errors`` and answers None ("disputed, status unknown"), never an
    exception: a missing Disputes permission must not stop delivery."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.errors: list[str] = []
        self._seen: dict[str, str | None] = {}

    def __call__(self, charge: Mapping[str, Any]) -> str | None:
        charge_id, intent = charge.get("id"), charge.get("payment_intent")
        if isinstance(charge_id, str) and re.fullmatch(r"(ch|py)_[A-Za-z0-9]+", charge_id):
            param = ("charge", charge_id)
        elif isinstance(intent, str) and re.fullmatch(r"pi_[A-Za-z0-9]+", intent):
            param = ("payment_intent", intent)
        else:
            return None
        if param[1] in self._seen:
            return self._seen[param[1]]
        url = f"{DISPUTES_API}?{urllib.parse.urlencode([param, ('limit', '10')])}"
        try:
            page = _stripe_get(url, self.key)
        except SubscriptionError as exc:
            self.errors.append(str(exc))
            self._seen[param[1]] = None
            return None
        found = [str(d.get("status") or "") for d in (page.get("data") or [])
                 if isinstance(d, dict)] if isinstance(page, dict) else []
        open_ = [s for s in found if s not in DISPUTE_CLOSED]
        status = (min(open_, key=lambda s: _DISPUTE_RANK.index(s)
                      if s in _DISPUTE_RANK else _DISPUTE_RANK.index("unknown"))
                  if open_ else ("won" if found else None))
        self._seen[param[1]] = status
        return status


def dispute_state(charge: Any, lookup: "DisputeLookup | None" = None) -> str | None:
    """What a charge's dispute means: None (no dispute, or one closed in our
    favour), ``"lost"``, a status from DISPUTE_ACTION / DISPUTE_REVIEW, or
    ``"unknown"`` — disputed, but its dispute could not be read or carries a
    status this code does not know, which is an alarm rather than a guess.

    A lost chargeback is NOT a refund in Stripe's data: ``refunded`` stays
    false and ``amount_refunded`` stays 0 (reproduced: ``_charge_refunded``
    returned False for one), so before this a buyer who charged back kept
    every report for the rest of the season. External input: anything
    unexpected is "unknown", never "fine"."""
    if not isinstance(charge, dict) or charge.get("disputed") is not True:
        return None
    status = lookup(charge) if lookup is not None else None
    if status in DISPUTE_CLOSED:
        return None
    if status == DISPUTE_LOST or status in DISPUTE_ACTION or status in DISPUTE_REVIEW:
        return status
    return "unknown"


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


SESSIONS_API = "https://api.stripe.com/v1/checkout/sessions"
# How far back a one-time pass is looked for: longer than any season a pass
# could be bought in (September to January), short enough to stay one query.
ONE_TIME_LOOKBACK_DAYS = 250
# A one-time pass is entitled through its season's last game plus this, so a
# retried final Tuesday (RULE B3's reason) still reaches it.
ONE_TIME_GRACE_DAYS = 14


def _charge_refunded(charge: Any) -> bool:
    """RULE E1 for a one-time payment: refunded in full (flag or arithmetic)."""
    if not isinstance(charge, dict):
        return False
    if charge.get("refunded") is True:
        return True
    amount, returned = charge.get("amount"), charge.get("amount_refunded")
    return isinstance(amount, int) and isinstance(returned, int) and 0 < amount <= returned


def one_time_entitled_until(created: int, season_ends: Mapping[str, str]) -> "date | None":
    """The last day a one-time pass bought at ``created`` (epoch seconds) is
    entitled: its season's last game plus ONE_TIME_GRACE_DAYS. The season is
    the earliest one whose last game is on or after the purchase — the season
    the pass was sold for. None when the schedule can't say."""
    from datetime import date as _date, datetime as _dt, timedelta, timezone as _tz
    bought = _dt.fromtimestamp(int(created), _tz.utc).date().isoformat()
    ends = sorted(end for end in season_ends.values() if end >= bought)
    if not ends:
        return None
    return _date.fromisoformat(ends[0]) + timedelta(days=ONE_TIME_GRACE_DAYS)


def _one_time_purchases(key: str, now: "datetime | None" = None,
                        season_ends: Mapping[str, str] | None = None,
                        disputes: list | None = None,
                        dispute_lookup: "DisputeLookup | None" = None,
                        ) -> tuple[set[str], set[str], list[str]]:
    """(entitled PaymentIntent ids, their emails, refunded ids) for one-time
    passes (Payment Links in payment mode — the 2026 rest-of-season passes).

    A charge whose dispute was LOST counts as refunded (its id joins the
    refunded list and it is not entitled); one still open stays entitled and
    is appended to ``disputes`` as (id, status) when a list is given. A
    disputed charge's status is read by ``dispute_lookup`` (one built from
    ``key`` when none is given).

    A subscription answers "am I paid up" itself; a one-time payment never
    does, so entitlement is read off the paid Checkout Session: paid, not
    refunded in full (RULE E1), and its season not yet over. The season comes
    from the schedule the product reads (run.solo.season_ends); if it can't
    be read, a purchase inside the lookback counts — the Tuesday run builds
    nothing outside a season anyway (SeasonOver, week_one_due)."""
    from datetime import datetime as _dt, timezone as _tz
    now = now or _dt.now(_tz.utc)
    if season_ends is None:
        try:
            from run.solo import CACHE_DIR, season_ends as _season_ends
            season_ends = _season_ends(CACHE_DIR, live=False)
        except Exception:  # noqa: BLE001 — unknown season: the lookback decides
            season_ends = {}
    since = int(now.timestamp()) - ONE_TIME_LOOKBACK_DAYS * 86400
    lookup = dispute_lookup if dispute_lookup is not None else DisputeLookup(key)
    params = [("status", "complete"), ("limit", "100"), ("created[gte]", str(since)),
              ("expand[]", "data.payment_intent.latest_charge")]
    ids: set[str] = set()
    emails: set[str] = set()
    refunded: list[str] = []
    url = f"{SESSIONS_API}?{urllib.parse.urlencode(params)}"
    while True:
        page = _stripe_get(url, key)
        data = page.get("data")
        data = data if isinstance(data, list) else []
        for session in data:
            if not isinstance(session, dict) or session.get("mode") != "payment":
                continue
            if session.get("payment_status") != "paid":
                continue
            intent = session.get("payment_intent")
            if not isinstance(intent, dict):
                continue
            pi = intent.get("id")
            if not (isinstance(pi, str) and pi.startswith("pi_")):
                continue
            charge = intent.get("latest_charge")
            state = dispute_state(charge, lookup)
            if _charge_refunded(charge) or state == DISPUTE_LOST:
                refunded.append(pi)
                continue
            if state is not None and disputes is not None:
                disputes.append((pi, state))
            created = session.get("created")
            if not isinstance(created, int):
                continue
            until = one_time_entitled_until(created, season_ends) if season_ends else None
            if until is not None and now.date() > until:
                continue
            ids.add(pi)
            email = ((session.get("customer_details") or {}).get("email") or "").strip().lower()
            if email:
                emails.add(email)
        last_id = data[-1].get("id") if data and isinstance(data[-1], dict) else None
        if not page.get("has_more") or not last_id:
            break
        url = (f"{SESSIONS_API}?{urllib.parse.urlencode(params)}"
               f"&starting_after={urllib.parse.quote(str(last_id))}")
    return ids, emails, refunded


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
    subscription_ids: set[str] = set()
    refunded: list[str] = []
    disputes: list[tuple[str, str]] = []
    lookup = DisputeLookup(key)
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
                invoice = subscription.get("latest_invoice")
                # A LOST chargeback ends entitlement like a full refund; its
                # status is read only for a charge Stripe marks disputed.
                state = dispute_state(invoice.get("charge")
                                      if isinstance(invoice, dict) else None, lookup)
                if fully_refunded(subscription) or state == DISPUTE_LOST:
                    refunded.append(str(subscription.get("id")))
                    continue
                if state is not None:
                    disputes.append((str(subscription.get("id")), state))
                sub_id = subscription.get("id")
                if isinstance(sub_id, str) and sub_id.startswith("sub_"):
                    subscription_ids.add(sub_id)
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
    # One-time passes: their PaymentIntent ids join the entitled set, so a row
    # or seat naming one is served exactly like a subscription (RULE E2).
    once_ids, once_emails, once_refunded = _one_time_purchases(
        key, disputes=disputes, dispute_lookup=lookup)
    subscription_ids |= once_ids
    emails |= once_emails
    refunded.extend(once_refunded)
    return PaidList(emails=frozenset(emails), source="stripe",
                    status_column=",".join(statuses),
                    customer_ids=frozenset(customer_ids),
                    covered_leagues=frozenset(covered_leagues),
                    refunded=frozenset(refunded),
                    subscription_ids=frozenset(subscription_ids),
                    disputes=tuple(sorted(set(disputes))),
                    dispute_errors=tuple(dict.fromkeys(lookup.errors)))


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
