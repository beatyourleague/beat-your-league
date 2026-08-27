"""Reading Stripe Checkout Sessions — the paging, once.

``run/sync.py`` (the Sleeper-era signups) and ``run/intake.py`` (the roster
signups PLAN §0's product uses) both have to walk completed sessions since a
watermark. That walk is subtle in ways that were each a real bug:

* The per-link queries are an OPTIMISATION, never the filter. With only the
  League Pass link configured, every season and monthly buyer paid, was never
  swept, never reached the registry, never got a report — and kept being
  charged. Every sweep therefore ends with an unfiltered query.
* Which means a session can come back twice, so it is deduped by id.
* Stripe lists newest-first while every projection resolves latest-wins by
  POSITION, so somebody who changed their picks twice before Tuesday was
  scouted against the pick they abandoned. Sessions come back oldest-first.
* The watermark advances past sessions we could not use, because they are still
  sessions we have seen; an unusable one is reported separately and remembered
  by the caller, not re-swept forever.

Two copies of that would drift, and the drift is invisible until somebody who
paid gets nothing. This module holds no Sleeper import, which is also what lets
the roster path use it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from run.refs import _PREFIX_TO_PLAN
from run.subscriptions import SubscriptionError, _stripe_get

SESSIONS_API = "https://api.stripe.com/v1/checkout/sessions"
CUSTOMERS_API = "https://api.stripe.com/v1/customers"

# How far behind the stored watermark to start. Stripe's `created` is the moment
# the session opened, not the moment it completed, so a session that started
# before the last sweep and completed after it would otherwise never be seen.
WATERMARK_SLACK_SECONDS = 3 * 24 * 3600


def post(url: str, api_key: str, form: dict[str, str],
         what: str = "writing customer metadata",
         needs: str = "WRITE access to Customers") -> dict:
    """One form-encoded write. ``what``/``needs`` name the call in the error.

    They are arguments rather than a fixed sentence because a second caller now
    exists: a message telling an operator to grant Customers write access when
    the call that actually 403'd was a subscription update sends them to fix the
    wrong permission, and the promise stays broken while they do.
    """
    body = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Stripe-Version": "2024-06-20",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never echo the request — it carries the secret key.
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise SubscriptionError(
            f"Stripe returned HTTP {exc.code} {what}. The restricted key needs "
            f"{needs}. Response: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SubscriptionError(f"could not reach Stripe: {exc}") from None
    except json.JSONDecodeError:
        raise SubscriptionError("Stripe returned a response we could not read") from None


def session_email(session: dict) -> str:
    """The address to mail.

    ``locked_prefilled_email`` means this equals the address typed into the
    picker, but we read Stripe's copy because Stripe is the one that actually
    took the money.
    """
    customer = session.get("customer")
    if isinstance(customer, dict) and not customer.get("deleted"):
        email = (customer.get("email") or "").strip().lower()
        if email:
            return email
    details = session.get("customer_details")
    if isinstance(details, dict):
        return (details.get("email") or "").strip().lower()
    return ""


def customer_id(session: dict) -> str | None:
    customer = session.get("customer")
    if isinstance(customer, dict):
        cid = customer.get("id")
        return cid if isinstance(cid, str) and cid else None
    return customer if isinstance(customer, str) and customer else None


def parse_link_plans(raw: str) -> dict[str, str]:
    """``s:plink_A,m:plink_B,p:plink_C`` -> {link_id: plan}.

    This map is what makes the plan an authenticated fact instead of a claim.
    A bare ``plink_X`` with no prefix is accepted as a filter with an unknown
    plan, which is safe: it can never grant a League Pass.
    """
    out: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        prefix, _, link = item.partition(":")
        if link:
            plan = _PREFIX_TO_PLAN.get(prefix.strip())
            if plan:
                out[link.strip()] = plan
        else:
            out[prefix] = ""          # filter only, plan unknown
    return out


def is_paid(session: dict) -> bool:
    """A session can be ``status:"complete"`` and still unpaid when the buyer
    used a delayed-notification method. Entitlement follows the money."""
    return session.get("payment_status") in (None, "paid", "no_payment_required")


def sweep_sessions(api_key: str, since: int | None = None,
                   link_plans: Iterable[str] | None = None,
                   ) -> tuple[list[dict], int | None]:
    """Every completed session since the watermark, oldest first, deduped.

    Returns the sessions and the newest ``created`` seen — including sessions
    the caller could not use, because they are still sessions we have seen.
    """
    seen: set[str] = set()
    sessions: list[dict] = []
    newest = since

    base = {"status": "complete", "limit": "100", "expand[]": "data.customer"}
    if since is not None:
        base["created[gte]"] = str(max(0, since - WATERMARK_SLACK_SECONDS))
    queries: list[dict[str, str]] = []
    for link in [*(link_plans or ()), None]:
        query = dict(base)
        if link:
            query["payment_link"] = link
        queries.append(query)

    for query in queries:
        url = f"{SESSIONS_API}?{urllib.parse.urlencode(query)}"
        while True:
            page = _stripe_get(url, api_key)
            data = page.get("data")
            data = data if isinstance(data, list) else []
            for session in data:
                if not isinstance(session, dict):
                    continue
                session_id = session.get("id")
                if isinstance(session_id, str):
                    if session_id in seen:
                        continue
                    seen.add(session_id)
                created = session.get("created")
                if isinstance(created, int):
                    newest = created if newest is None else max(newest, created)
                sessions.append(session)
            last_id = data[-1].get("id") if data and isinstance(data[-1], dict) else None
            if not page.get("has_more") or not last_id:
                break
            url = (f"{SESSIONS_API}?{urllib.parse.urlencode(query)}"
                   f"&starting_after={urllib.parse.quote(str(last_id))}")

    sessions.sort(key=lambda s: s.get("created") if isinstance(s.get("created"), int) else 0)
    return sessions, newest
