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
            f"{needs}. Response: {detail}", status=exc.code) from None
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


# STRIPE_PAYMENT_LINKS' own prefixes: the ref prefixes (run/refs.py — s, m,
# p) plus "o", the $19 Playoff Pass (contract C4). A purchase through the o:
# link is a SEASON row, entitled exactly like the $29 Rest-of-Season Pass; the
# prefix exists so the intake can tell WHICH season link took the money. It
# is deliberately NOT a ref prefix: the ref is the buyer's claim, built in the
# browser, and the JS<->Python ref contract stays as it is. "m" stays legal
# for 2027's monthly plan.
PLAYOFF_LINK_PREFIX = "o"
LINK_PREFIX_TO_PLAN = {**_PREFIX_TO_PLAN, PLAYOFF_LINK_PREFIX: _PREFIX_TO_PLAN["s"]}
# The join page's PLAYOFF_FROM_WEEK (and run/economics.py's): the $19 pass is
# sold once a buyer's first weekly report would be this week or later — that
# is, from the first kickoff of the week BEFORE it (tests pin all three).
PLAYOFF_FROM_WEEK = 13


def parse_link_prefixes(raw: str) -> dict[str, str]:
    """``s:plink_A,o:plink_B,p:plink_C`` -> {link_id: prefix} for every item
    whose prefix the map knows (``LINK_PREFIX_TO_PLAN``); a bare ``plink_X``
    maps to "" (a filter, plan unknown). An unknown prefix is left out, so a
    purchase through that link is reported as unattributable, never guessed."""
    out: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        prefix, _, link = item.partition(":")
        if link:
            if prefix.strip() in LINK_PREFIX_TO_PLAN:
                out[link.strip()] = prefix.strip()
        else:
            out[prefix] = ""          # filter only, plan unknown
    return out


def parse_link_plans(raw: str) -> dict[str, str]:
    """``s:plink_A,o:plink_B,p:plink_C`` -> {link_id: plan}.

    This map is what makes the plan an authenticated fact instead of a claim.
    A bare ``plink_X`` with no prefix is accepted as a filter with an unknown
    plan, which is safe: it can never grant a League Pass. The $19 Playoff
    Pass link (``o:``) is the season plan (contract C4); ``playoff_links``
    says which link it was.
    """
    return {link: LINK_PREFIX_TO_PLAN.get(prefix, "")
            for link, prefix in parse_link_prefixes(raw).items()}


def playoff_links(raw: str) -> frozenset[str]:
    """The link id(s) under ``o:`` — the $19 Playoff Pass (contract C4)."""
    return frozenset(link for link, prefix in parse_link_prefixes(raw).items()
                     if prefix == PLAYOFF_LINK_PREFIX)


def link_map_problems(raw: str, *, playoff: bool = True) -> list[str]:
    """What is wrong with a STRIPE_PAYMENT_LINKS value, in words. Empty means
    it is the 2026 shape: ``s:plink_…,o:plink_…,p:plink_…`` — the $29
    Rest-of-Season Pass, the $19 Playoff Pass and the $69 League Pass, each
    under its own prefix, each link once (``m:plink_…`` optional, for a
    monthly plan). ``playoff=False`` when no Playoff Pass is sold.

    The map is the whole of "which plan did this payment buy", and a mistake
    in it fails quietly: an unknown prefix drops its link (every purchase
    through it unattributable), one link under two prefixes keeps only the
    last, and a $19 link filed under ``s:`` sells every report through Week 18
    for $10 less with nothing reported (final review SEC-3 / OPS-1)."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        prefix, _, link = (part.strip() for part in item.partition(":"))
        if not link:
            problems.append(f"{item[:24]!r} has no plan prefix (s:, o:, p:)")
            continue
        if prefix not in LINK_PREFIX_TO_PLAN:
            problems.append(f"unknown prefix {prefix[:4]!r}: in {item[:24]!r} — "
                            f"purchases through it would be unattributable")
            continue
        if not link.startswith("plink_"):
            problems.append(f"{prefix}: {link[:16]!r} is not a payment link id (plink_…)")
        if link in seen and seen[link] != prefix:
            problems.append(f"{link[:16]} is listed as both {seen[link]}: and {prefix}:")
        seen[link] = prefix
    prefixes = list(seen.values())
    wanted = ["s", "p"] + ([PLAYOFF_LINK_PREFIX] if playoff else [])
    for prefix in wanted:
        count = prefixes.count(prefix)
        if count == 0:
            problems.append(f"no {prefix}: link")
        elif count > 1 and prefix != "s":
            problems.append(f"{count} {prefix}: links — one each")
    if prefixes.count("s") > 1:
        problems.append(f"{prefixes.count('s')} s: links — the $19 Playoff Pass "
                        f"goes under o:, so the intake can tell it from the $29 pass")
    return problems


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
