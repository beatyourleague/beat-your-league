"""The owner's one-screen view of demand — `make stats`.

Usage:
    python -m run.stats [--registry PATH] [--now ISO] [--html PATH]

Everything it needs is already stored somewhere the owner can read:

- **The page counter** (``site/count.js`` → the form Worker's ``/e`` →
  Cloudflare Analytics Engine, dataset ``byl_counts``), when ``CF_ACCOUNT_ID``
  and ``CF_ANALYTICS_TOKEN`` are in this shell or the gitignored ``.env``:
  page views and signup steps by channel, referring site, device and country.
  Counts of anonymous lines, never of people (privacy section 3).
- **The form Worker** (``FORM_ENDPOINT`` + ``FORM_API_KEY``): waitlist sign-ups,
  free-report requests, roster-update requests and confirmations, seat claims.
- **The send log** (``data/processed/sent.jsonl``, committed by the crons, so a
  ``git pull`` brings it up to date): what actually went out, week by week.
- **The registry**, when it is on this machine (it normally lives only in the
  CI cache): who subscribes, how many free reports turned into one, and how
  many seats each League Pass has filled against its cap.
- **Channels.** A form row may carry a ``via`` tag (which link brought the
  person: a post, a reply, a profile). Counted per kind, so the owner can see
  which channel a sign-up came from.
- **Stripe**, when ``STRIPE_API_KEY`` is set in this shell: the season's passes
  sold by type (paid payment-mode sessions), gross, refunded and net of
  Stripe's modelled fee, the refund rate, free report → paid within 14 days,
  checkout sessions of the last 7 days by outcome, refunds of the last 30,
  paid signups ever by channel, and — labelled as 2027's plans while 2026
  sells one-time passes — active subscriptions. Read-only GETs. Each part that
  cannot be read says so and the rest still prints. The Stripe Dashboard's
  phone app is the live view of money; this is the funnel around it.

Counts and dollars only. No address is ever printed — this is the kind of
output that gets pasted into a chat or a note, and the send log keys carry
digests for the same reason. It never runs in CI: the repository is public,
so a job log or summary would publish sales and traffic to anyone (the
secrets would stay hidden; the output would not). Read-only: nothing here
sends or changes anything; the ``--html`` copy is written only to a
gitignored path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

FORM_KINDS = (("waitlist", "Waitlist sign-ups"),
              ("trial", "Free-report requests"),
              ("update_request", "Roster-update requests"),
              ("confirm", "Roster-update confirmations"),
              ("seat", "League Pass seat claims"),
              ("update", "Roster updates (old link)"))


def _when(value: object) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def form_summary(rows: Iterable[Mapping], now: datetime) -> dict[str, dict[str, int]]:
    """Per kind: rows ever, in the last 7 days, in the last day, and people
    (distinct mailboxes, one spelling per mailbox as the free report counts them)."""
    from run.trials import canonical_email
    out: dict[str, dict[str, int]] = {}
    people: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        kind = str(row.get("kind") or "seat")
        counts = out.setdefault(kind, {"total": 0, "week": 0, "day": 0, "people": 0})
        counts["total"] += 1
        stamp = _when(row.get("received_at"))
        if stamp is not None and stamp <= now:
            counts["week"] += stamp > now - timedelta(days=7)
            counts["day"] += stamp > now - timedelta(days=1)
        if row.get("email"):
            people[kind].add(canonical_email(str(row["email"])))
    for kind, seen in people.items():
        out[kind]["people"] = len(seen)
    return out


# The shape the form Worker stores for ``via``. Re-checked here because a row
# is external input whatever the Worker promises: a tag that does not match is
# counted as unreadable and never printed, so a pasted address can't ride
# through this field into the output.
VIA_RE = re.compile(r"^[a-z0-9-]{1,24}$")
NO_VIA = "(no tag)"
BAD_VIA = "(unreadable tag)"


def channel_summary(rows: Iterable[Mapping]) -> dict[str, Counter[str]]:
    """Per kind: rows by ``via`` tag. Rows, not people — a channel is credited
    with every request it brought, the same count the "ever" column shows."""
    out: dict[str, Counter[str]] = {}
    for row in rows:
        kind = str(row.get("kind") or "seat")
        via = row.get("via")
        if via is None or via == "":
            tag = NO_VIA
        elif isinstance(via, str) and VIA_RE.fullmatch(via):
            tag = via
        else:
            tag = BAD_VIA
        out.setdefault(kind, Counter())[tag] += 1
    return out


def _channel_lines(channels: Mapping[str, Counter[str]]) -> list[str]:
    if not any(set(c) - {NO_VIA} for c in channels.values()):
        return ["  No row carries a channel (via) tag yet."]
    lines = []
    labels = dict(FORM_KINDS)
    for kind in [k for k, _ in FORM_KINDS] + sorted(set(channels) - set(labels)):
        counts = channels.get(kind)
        if not counts:
            continue
        # Tagged channels by size, then the untagged and unreadable remainder.
        ranked = sorted(((t, n) for t, n in counts.items() if t not in (NO_VIA, BAD_VIA)),
                        key=lambda item: (-item[1], item[0]))
        ranked += [(t, counts[t]) for t in (NO_VIA, BAD_VIA) if counts.get(t)]
        label = labels.get(kind, "Other rows")
        lines.append(f"  {label:30} " + ", ".join(f"{t} {n}" for t, n in ranked))
    return lines


# --------------------------------------------------------------------- #
# Stripe — read-only, fail soft
# --------------------------------------------------------------------- #

STRIPE = "https://api.stripe.com/v1"


def _stripe_list(path: str, params: list[tuple[str, str]], api_key: str) -> list[dict]:
    """Every object a Stripe list endpoint returns, all pages. GET only, via
    the one helper that never echoes the key (run/subscriptions.py)."""
    import urllib.parse

    import run.subscriptions as subscriptions
    query = urllib.parse.urlencode([*params, ("limit", "100")])
    url = f"{STRIPE}/{path}?{query}"
    out: list[dict] = []
    while True:
        page = subscriptions._stripe_get(url, api_key)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            # A shape we don't recognise is not an empty list: saying "0
            # refunds" about a response we could not read is the quiet zero.
            raise ValueError("Stripe returned a list in a shape we don't recognise")
        data = page["data"]
        out.extend(row for row in data if isinstance(row, dict))
        last = data[-1].get("id") if data and isinstance(data[-1], dict) else None
        if not page.get("has_more") or not last:
            return out
        url = (f"{STRIPE}/{path}?{query}"
               f"&starting_after={urllib.parse.quote(str(last))}")


def _plan(subscription: Mapping) -> str:
    """"yearly at $39.00", read off the subscription's OWN price — never our
    plan field or a ref prefix (RULE B2 in run/billing.py: the price is what
    the buyer is actually charged)."""
    def obj(value: object) -> Mapping:
        return value if isinstance(value, Mapping) else {}
    items = obj(subscription.get("items")).get("data")
    first = items[0] if isinstance(items, list) and items else None
    price = obj(obj(first).get("price"))
    interval = obj(price.get("recurring")).get("interval")
    amount = price.get("unit_amount")
    name = {"month": "monthly", "year": "yearly", "week": "weekly",
            "day": "daily"}.get(str(interval), "unknown interval")
    money = (f" at ${amount / 100:.2f}" if isinstance(amount, int)
             and str(price.get("currency") or "usd").lower() == "usd" else "")
    return name + money


def _safe(exc: Exception) -> str:
    """The reason a read failed, without Stripe's response body: that body can
    quote a masked key, and this output gets pasted places."""
    return str(exc).split(" Response:")[0].rstrip(".")


SUBSCRIPTIONS_LABEL = "Active subscriptions"
# While the site sells one-time passes (render.report.SELLING_ONE_TIME) no
# 2026 buyer has a subscription, so a bare "Active subscriptions: 0" read as
# "nobody bought" all season (BIZ-08). The line stays — a stray subscription
# is still worth seeing — under a label that says whose plans these are.
SUBSCRIPTIONS_LABEL_ONE_TIME = "Subscriptions (the 2027 plans; 2026 sells one-time passes)"


def _subscriptions_line(subs: list[dict], label: str = SUBSCRIPTIONS_LABEL) -> str:
    plans = Counter(_plan(s) for s in subs)
    # Still active, but ending: the buyer cancelled, or the monthly stop
    # (run/billing.py) is set. The churn signal, counted where it sits.
    ending = Counter(_plan(s) for s in subs
                     if s.get("cancel_at_period_end") or isinstance(s.get("cancel_at"), int))
    detail = ", ".join(
        f"{plan} {n}" + (f" ({ending[plan]} set to end)" if ending.get(plan) else "")
        for plan, n in sorted(plans.items(), key=lambda item: (-item[1], item[0])))
    return f"  {label}: {len(subs)}" + (f" — {detail}" if detail else "")


def _checkouts_line(sessions: list[dict]) -> str:
    by = Counter(str(s.get("status") or "unknown") for s in sessions)
    return (f"  Checkouts, last 7 days: {len(sessions)} created — "
            f"{by.get('complete', 0)} complete, {by.get('expired', 0)} expired, "
            f"{by.get('open', 0)} still open")


def _refunds_line(refunds: list[dict]) -> str:
    # A failed or cancelled refund returned nothing to anybody.
    given = [r for r in refunds if r.get("status") not in ("failed", "canceled")]
    return f"  Refunds, last 30 days: {len(given)}"


def _paid_by_channel_line(sessions: list[dict]) -> str:
    """Paid roster signups, ever, by the channel tag the purchase carried
    (contract C5: the join page appends "_via-<tag>" to the payment's own
    reference). Form rows only ever counted who ASKED; this is who PAID, the
    number a partner or affiliate decision needs (G09). Only this product's
    payments count — a Sleeper-era reference is not one — and the tag is
    re-checked to its shape before it is printed."""
    from run.checkout import is_paid
    from run.intake import split_via
    from run.refs import is_roster_ref
    counts: Counter[str] = Counter()
    for session in sessions:
        ref = session.get("client_reference_id")
        if (session.get("status") != "complete" or not is_paid(session)
                or not isinstance(ref, str) or not is_roster_ref(ref)):
            continue
        _ref, via = split_via(ref)
        counts[via if via and VIA_RE.fullmatch(via) else NO_VIA] += 1
    if not counts:
        return "  Paid signups by channel (ever): none yet"
    ranked = sorted(((t, n) for t, n in counts.items() if t != NO_VIA),
                    key=lambda item: (-item[1], item[0]))
    ranked += [(NO_VIA, counts[NO_VIA])] if counts.get(NO_VIA) else []
    return ("  Paid signups by channel (ever): "
            + ", ".join(f"{tag} {n}" for tag, n in ranked))


def stripe_summary(api_key: str, now: datetime, rows: list[Mapping] | None = None,
                   link_plans: Mapping[str, str] | None = None,
                   season_label: str = "ever", since: int | None = None,
                   one_time: bool | None = None) -> list[str]:
    """The payments half. Each read is independent — a key without Refunds
    access still shows subscriptions and checkouts — and a part that cannot
    be read says so instead of printing a zero it never counted.

    ``rows`` (the form Worker's, when read) adds free report → paid; ``since``
    (epoch seconds, the day after last season's final game) scopes passes to
    this season, named ``season_label``; ``one_time`` (default: what the site
    sells, render.report.SELLING_ONE_TIME) labels subscriptions as 2027's."""
    if one_time is None:
        from render.report import SELLING_ONE_TIME as one_time
    week_ago = int((now - timedelta(days=7)).timestamp())
    month_ago = int((now - timedelta(days=30)).timestamp())
    plans = dict(link_plans or {})

    def passes(sessions: list[dict]) -> list[str]:
        out = passes_lines(sessions, plans, season_label, since)
        if rows is not None:
            out.append(free_to_paid_line(rows, sessions, now, since))
        return out

    label = SUBSCRIPTIONS_LABEL_ONE_TIME if one_time else SUBSCRIPTIONS_LABEL
    parts = (
        # The charge rides along so a refund is read off the purchase itself.
        ("passes sold", "checkout/sessions",
         [("expand[]", "data.payment_intent.latest_charge")], passes),
        ("subscriptions", "subscriptions", [("status", "active")],
         lambda subs: _subscriptions_line(subs, label)),
        ("checkout sessions", "checkout/sessions",
         [("created[gte]", str(week_ago))], _checkouts_line),
        ("refunds", "refunds", [("created[gte]", str(month_ago))], _refunds_line),
        # Every session ever, not the week: a channel's worth is its total.
        ("paid signups by channel", "checkout/sessions", [], _paid_by_channel_line),
    )
    lines: list[str] = []
    for what, path, params, summarise in parts:
        try:
            got = summarise(_stripe_list(path, params, api_key))
            lines.extend(got if isinstance(got, list) else [got])
        except Exception as exc:  # noqa: BLE001 — fail soft, say which part
            hint = (" — a restricted key needs Read on it"
                    if re.search(r"HTTP 40[13]", str(exc)) else "")
            lines.append(f"  Could not read {what} ({_safe(exc)}{hint}).")
    return lines


# --------------------------------------------------------------------- #
# Passes — 2026 sells one-time passes (payment-mode Payment Links)
# --------------------------------------------------------------------- #

# What a pass is called here. The League Pass link is authenticated by
# STRIPE_PAYMENT_LINKS (plan "p"); the $29 and $19 links share the season plan
# ("s", LAUNCH.md step 3), so those two are told apart by their price before
# any discount. Prices are run/economics.ONE_TIME's, which tests tie to the
# welcome email and the live pages.
PASS_NAMES = (("Rest-of-Season Pass", "Rest-of-Season"), ("Playoff Pass", "Playoff"),
              ("League Pass (rest of season)", "League Pass"))
FREE_TO_PAID_DAYS = 14


def _pass_type(session: Mapping, link_plans: Mapping[str, str]) -> str:
    from run.economics import ONE_TIME
    from run.refs import LEAGUE_PASS
    short = dict(PASS_NAMES)
    if link_plans.get(str(session.get("payment_link") or "")) == LEAGUE_PASS:
        return short["League Pass (rest of season)"]
    price = session.get("amount_subtotal")
    price = price if isinstance(price, int) else session.get("amount_total")
    for name, dollars in ONE_TIME.items():
        if isinstance(price, int) and price == round(dollars * 100):
            return short.get(name, name)
    return f"other price (${price / 100:.2f})" if isinstance(price, int) else "unknown price"


def _paid_pass_sessions(sessions: Iterable[Mapping], since: int | None) -> list[Mapping]:
    """This product's paid one-time purchases: payment mode, complete, paid,
    a roster reference (a Sleeper-era or foreign session is not one), and —
    when the season's start is known — bought after the last season ended."""
    from run.refs import is_roster_ref
    out = []
    for session in sessions:
        ref = session.get("client_reference_id")
        created = session.get("created")
        if (session.get("mode") != "payment" or session.get("status") != "complete"
                or session.get("payment_status") != "paid"
                or not isinstance(ref, str) or not is_roster_ref(ref)):
            continue
        if since is not None and not (isinstance(created, int) and created > since):
            continue
        out.append(session)
    return out


def _charge(session: Mapping) -> Mapping:
    intent = session.get("payment_intent")
    charge = intent.get("latest_charge") if isinstance(intent, Mapping) else None
    return charge if isinstance(charge, Mapping) else {}


def passes_lines(sessions: Iterable[Mapping], link_plans: Mapping[str, str],
                 label: str, since: int | None) -> list[str]:
    """Passes sold by type, the money, and the refund rate. Gross is what the
    buyers paid; refunded is what Stripe returned (a partial refund counts its
    amount, and only a FULL refund counts toward the rate — RULE E1's line);
    net also takes off Stripe's fee as run/economics models it for a one-time
    payment, which Stripe keeps when it refunds."""
    from run.economics import stripe_fee
    from run.subscriptions import _charge_refunded
    paid = _paid_pass_sessions(sessions, since)
    if not paid:
        return [f"  Passes sold, {label}: none yet"]
    kinds = Counter(_pass_type(s, link_plans) for s in paid)
    order = [short for _name, short in PASS_NAMES]
    detail = ", ".join(f"{k} {kinds[k]}" for k in order + sorted(set(kinds) - set(order))
                       if kinds.get(k))
    usd = [s for s in paid if str(s.get("currency") or "usd").lower() == "usd"
           and isinstance(s.get("amount_total"), int)]
    gross = sum(s["amount_total"] for s in usd) / 100
    refunded = sum(int(_charge(s).get("amount_refunded") or 0) for s in usd) / 100
    fees = sum(stripe_fee(s["amount_total"] / 100, one_time=True) for s in usd)
    full = sum(_charge_refunded(_charge(s)) for s in paid)
    lines = [f"  Passes sold, {label}: {len(paid)} — {detail}",
             f"  Money: ${gross:,.2f} gross, ${refunded:,.2f} refunded, "
             f"${gross - refunded - fees:,.2f} net of Stripe's fee (modelled)",
             f"  Refund rate: {full / len(paid):.0%} ({full} of {len(paid)} refunded in full)"]
    if len(usd) < len(paid):
        lines.append(f"  ({len(paid) - len(usd)} paid in another currency, "
                     f"left out of the money line)")
    return lines


def free_to_paid_line(rows: Iterable[Mapping], sessions: Iterable[Mapping],
                      now: datetime, since: int | None = None) -> str:
    """Of the people who asked for a free report, how many bought a pass
    within FREE_TO_PAID_DAYS of first asking — joined on the mailbox the way
    the free report counts people (run.trials.canonical_email). Requests
    younger than the window are counted apart: they can still convert."""
    from run.trials import canonical_email
    first: dict[str, datetime] = {}
    for row in rows:
        stamp = _when(row.get("received_at"))
        if row.get("kind") == "trial" and row.get("email") and stamp is not None:
            who = canonical_email(str(row["email"]))
            first[who] = min(first.get(who, stamp), stamp)
    bought: dict[str, list[datetime]] = defaultdict(list)
    for session in _paid_pass_sessions(sessions, since):
        email = ((session.get("customer_details") or {}).get("email")
                 or session.get("customer_email") or "")
        if email and isinstance(session.get("created"), int):
            bought[canonical_email(str(email))].append(
                datetime.fromtimestamp(session["created"], timezone.utc))
    window = timedelta(days=FREE_TO_PAID_DAYS)
    closed = {who: at for who, at in first.items() if at <= now - window}
    young = len(first) - len(closed)
    paid = sum(any(at <= b <= at + window for b in bought.get(who, ()))
               for who, at in closed.items())
    tail = (f" ({young} asked under {FREE_TO_PAID_DAYS} days ago, not counted yet)"
            if young else "")
    return (f"  Free report → paid within {FREE_TO_PAID_DAYS} days: {paid} of "
            f"{len(closed)}" + tail)


# --------------------------------------------------------------------- #
# Traffic — the page counter (site/count.js), read-only, fail soft
# --------------------------------------------------------------------- #

COUNT_DATASET = "byl_counts"
COUNT_JS = Path(__file__).resolve().parent.parent / "site" / "count.js"
# count.js names our own site as the referrer of a step from one of our pages
# to another, so the referrer line can leave those out: "(direct or hidden)"
# then counts arrivals, not every click from the landing to the join page.
OWN_HOST = "beatyourleague.com"
AE_SQL = "https://api.cloudflare.com/client/v4/accounts/{account}/analytics_engine/sql"
ACCOUNT_RE = re.compile(r"^[0-9a-f]{32}$")
# blob1 event, blob2 page, blob3 via, blob4 referring host, blob5 device,
# blob6 checkout state, blob7 country — the order the Worker writes (C1).
# Counts are SUM(_sample_interval), never COUNT(): Analytics Engine samples.
TRAFFIC_SQL = ("SELECT blob1 AS e, blob2 AS p, blob3 AS v, blob4 AS r, blob5 AS d, "
               "blob6 AS s, blob7 AS c, SUM(_sample_interval) AS n FROM {dataset} "
               "WHERE timestamp > NOW() - INTERVAL '{days}' DAY "
               "GROUP BY e, p, v, r, d, s, c ORDER BY n DESC LIMIT 10000 FORMAT JSON")
COUNT_EVENTS = ("view", "roster", "checkout", "waitlist", "trial")
BUY_PAGES = ("join", "join-pass")
FUNNEL = (
    ("Landing views", lambda r: r["e"] == "view" and r["p"] == "index"),
    ("Buy-page views", lambda r: r["e"] == "view" and r["p"] in BUY_PAGES),
    ("Rosters checked on the buy page", lambda r: r["e"] == "roster" and r["p"] in BUY_PAGES),
    ("Buy pressed, checkout open", lambda r: r["e"] == "checkout" and r["s"] == "open"),
    ("Buy pressed, checkout closed", lambda r: r["e"] == "checkout" and r["s"] == "closed"),
    # Both captures count it: the landing's hero form and the join page's
    # closed-checkout save (the FORMS block still has the stored total).
    ("Waitlist joined", lambda r: r["e"] == "waitlist"),
    ("Free-report page views", lambda r: r["e"] == "view" and r["p"] == "join-try"),
    ("Free-report rosters checked", lambda r: r["e"] == "roster" and r["p"] == "join-try"),
    ("Free reports requested", lambda r: r["e"] == "trial"),
    ("Planner views", lambda r: r["e"] == "view" and r["p"] == "planner"),
    ("Planner rosters checked", lambda r: r["e"] == "roster" and r["p"] == "planner"),
    ("Waitlist joined from the planner", lambda r: r["e"] == "waitlist" and r["p"] == "planner"),
)
# External input: a field that is not the shape the Worker writes drops the
# whole row, never prints — no field can smuggle an address through (C1's own
# rule, plus the two-letter country Cloudflare adds, or its T1/XX).
_FIELD = re.compile(r"^[a-z0-9.-]{0,40}$")
_COUNTRY = re.compile(r"^(?:[A-Z]{2}|T1)?$")
TRAFFIC_CAVEAT = ("  Counts of page views and signup steps, never of people: a reload "
                  "counts again, and\n  visitors with Global Privacy Control, Do Not "
                  "Track or some blockers are not counted.")


def counter_endpoint(path: Path | None = None) -> str:
    """The ENDPOINT site/count.js posts to; empty while the counter is off."""
    try:
        text = (path or COUNT_JS).read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.findall(r'\bconst ENDPOINT = "([^"]*)";', text)
    return found[0] if len(found) == 1 else ""


def query_counts(account: str, token: str, days: int) -> list[dict]:
    """The counter's rows for the last ``days`` days, grouped. One read-only
    POST to Cloudflare's SQL API, whose token needs Account Analytics: Read
    and nothing else — it can see these counts and change nothing."""
    import urllib.request
    if not ACCOUNT_RE.fullmatch(account):
        raise ValueError("CF_ACCOUNT_ID is not a 32-character Cloudflare account id")
    sql = TRAFFIC_SQL.format(dataset=COUNT_DATASET, days=int(days))
    request = urllib.request.Request(
        AE_SQL.format(account=account), data=sql.encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
    with urllib.request.urlopen(request, timeout=30) as response:
        doc = json.loads(response.read().decode("utf-8"))
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, list):
        raise ValueError("the counter answered in a shape we don't recognise")
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        clean = {k: row.get(k) if isinstance(row.get(k), str) else "" for k in "epvrdsc"}
        if (clean["e"] not in COUNT_EVENTS or not _COUNTRY.fullmatch(clean["c"])
                or not all(_FIELD.fullmatch(clean[k]) for k in "pvrds")):
            continue
        try:
            n = int(float(row.get("n") or 0))
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append({**clean, "n": n})
    return out


def _sum(rows: Iterable[Mapping], test) -> int:
    return sum(r["n"] for r in rows if test(r))


def _top(rows: list[dict], field: str, empty: str, limit: int = 6,
         names: Mapping[str, str] | None = None) -> str:
    counts: Counter[str] = Counter()
    for row in rows:
        if row["e"] == "view":
            value = row[field] or empty
            counts[(names or {}).get(value, value)] += row["n"]
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return ", ".join(f"{k} {n}" for k, n in ranked) or "none yet"


def traffic_lines(week: list[dict], month: list[dict]) -> list[str]:
    """The funnel over 7 and 30 days, then the week by channel (landing and
    buy-page views → rosters checked → buy presses), referrer, page, device
    and country."""
    lines = [f"  {'':34} {'7 days':>7} {'30 days':>8}"]
    for label, test in FUNNEL:
        lines.append(f"  {label:34} {_sum(week, test):>7} {_sum(month, test):>8}")
    steps: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in week:
        if row["e"] == "view" and row["p"] in ("index",) + BUY_PAGES:
            steps[row["v"] or NO_VIA][0] += row["n"]
        elif row["e"] == "roster" and row["p"] in BUY_PAGES:
            steps[row["v"] or NO_VIA][1] += row["n"]
        elif row["e"] == "checkout":
            steps[row["v"] or NO_VIA][2] += row["n"]
    channels = sorted(steps.items(), key=lambda item: (-item[1][0], item[0]))[:6]
    lines += [TRAFFIC_CAVEAT,
              "  Channels, 7 days (views → rosters → buy presses): "
              + (", ".join(f"{v} {a} → {b} → {c}" for v, (a, b, c) in channels)
                 or "none yet"),
              "  Referrers, 7 days: " + _top(
                  [r for r in week if r["r"] != OWN_HOST and not r["r"].endswith("." + OWN_HOST)],
                  "r", "(direct or hidden)") + " (steps inside the site left out)",
              "  Pages, 7 days:     " + _top(week, "p", "unknown", 8),
              "  Devices, 7 days:   " + _top(week, "d", "unknown",
                                             names={"m": "phone", "d": "desktop"}),
              "  Countries, 7 days: " + _top(week, "c", "unknown")]
    return lines


def traffic_summary(account: str, token: str, endpoint: str) -> list[str]:
    """The traffic half, failing soft like the Stripe half: an error says why
    in one line, with the token masked wherever it appears."""
    if not endpoint:
        return ["  The counter is off: site/count.js has no ENDPOINT yet "
                "(LAUNCH.md step 5b)."]
    if not (account and token):
        return ["  CF_ACCOUNT_ID / CF_ANALYTICS_TOKEN are not set in this shell or .env "
                "— no traffic view (LAUNCH.md step 5b)."]
    try:
        week, month = query_counts(account, token, 7), query_counts(account, token, 30)
    except Exception as exc:  # noqa: BLE001 — fail soft, say why
        reason = re.sub(r"Bearer\s+\S+", "Bearer ***", str(exc)).replace(token, "***")
        return [f"  Could not read the counter ({type(exc).__name__}: {reason[:160]})."]
    lines = traffic_lines(week, month)
    if not week:
        lines.insert(0, "  The counter returned nothing for 7 days although site/count.js "
                        "is on — check the Worker's COUNTS binding (LAUNCH.md step 5b).")
    return lines


def load_send_log(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("key"):
            entries.append(entry)
    return entries


def send_summary(entries: Iterable[Mapping], season: str) -> dict:
    """What went out this season, from the send log's key shapes."""
    weekly: Counter[int] = Counter()
    finals: Counter[int] = Counter()
    other: Counter[str] = Counter()
    weekly_re = re.compile(rf"^{re.escape(season)}-w(\d\d)-([0-9a-f]+)$")
    final_re = re.compile(rf"^{re.escape(season)}-w(\d\d)-final-[0-9a-f]+$")
    for entry in entries:
        key = str(entry["key"])
        if m := weekly_re.match(key):
            weekly[int(m.group(1))] += 1
        elif m := final_re.match(key):
            finals[int(m.group(1))] += 1
        elif key.startswith(f"trial-{season}-"):
            other["free reports"] += 1
        elif key.startswith("welcome-") and str(entry.get("sent_at", "")).startswith(season):
            other["welcome emails (new subscribers)"] += 1
        elif key.startswith("preseason-") and str(entry.get("sent_at", "")).startswith(season):
            other["roster reports at purchase"] += 1
        elif key.startswith("confirm-") and str(entry.get("sent_at", "")).startswith(season):
            other["roster-update confirmations"] += 1
        elif key.startswith("renewal-"):
            other["renewal notices"] += 1
        elif key.startswith("launch-"):
            other["launch announcement"] += 1
    return {"weekly": dict(sorted(weekly.items())),
            "finals": dict(sorted(finals.items())), "other": dict(other)}


def conversions(rows: Iterable[Mapping], subscriber_emails: Iterable[str]) -> dict[str, tuple[int, int]]:
    """Of the people who asked for a free report / joined the waitlist, how many
    subscribe now: kind -> (subscribed, asked)."""
    from run.trials import canonical_email
    held = {canonical_email(e) for e in subscriber_emails}
    asked: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        kind = str(row.get("kind") or "")
        if kind in ("trial", "waitlist") and row.get("email"):
            asked[kind].add(canonical_email(str(row["email"])))
    return {kind: (len(seen & held), len(seen)) for kind, seen in asked.items()}


def seat_lines(registry: Iterable) -> list[str]:
    """Seats each League Pass has filled against its cap — as many seats as
    the payer's league has teams (run.intake.PassInfo.seat_cap; the payer's
    own team is not a seat). Counts only, never who."""
    registry = list(registry)
    payers = {s.pass_key: s for s in registry if s.is_pass_payer and s.pass_key}
    seats = Counter(s.pass_key for s in registry if s.is_league_seat and s.pass_key)
    if not payers and not seats:
        return []
    filled = sorted(((seats.get(key, 0), max(0, int(payer.league_size)))
                     for key, payer in payers.items()), key=lambda t: (-t[0], -t[1]))
    line = (f"  League Pass seats: {len(payers)} pass(es) — "
            + (", ".join(f"{n} of {cap}" for n, cap in filled) + " claimed"
               if filled else "no payer row here"))
    stray = sum(n for key, n in seats.items() if key not in payers)
    if stray:
        line += f"; {stray} seat(s) on a pass whose payer row isn't here"
    return [line]


def render(form: dict | None, form_note: str, sends: dict, season: str,
           registry: list | None, registry_note: str, conv: dict | None,
           now: datetime, channels: Mapping[str, Counter[str]] | None = None,
           payments: list[str] | None = None, traffic: list[str] | None = None) -> str:
    lines = [f"Beat Your League — demand, {now:%a %b %d %Y %H:%M} UTC", ""]
    lines.append("TRAFFIC (the site's own page counter, privacy section 3)")
    lines += traffic if traffic is not None else [
        "  The counter's view was not read this time."]
    lines += ["", "FORMS (from the site)"]
    if form is None:
        lines.append(f"  {form_note}")
    else:
        lines.append(f"  {'':30} {'ever':>6} {'7 days':>7} {'24 h':>5} {'people':>7}")
        for kind, label in FORM_KINDS:
            c = form.get(kind)
            if c is None and kind == "update":
                continue
            c = c or {"total": 0, "week": 0, "day": 0, "people": 0}
            people = c["people"] if kind != "confirm" else "-"
            lines.append(f"  {label:30} {c['total']:>6} {c['week']:>7} {c['day']:>5} {people!s:>7}")
    if channels is not None:
        lines += ["", "CHANNELS (form rows by via tag, ever)"] + _channel_lines(channels)
    lines += ["", f"SENT THIS SEASON ({season})"]
    if sends["weekly"]:
        lines.append("  Weekly reports by week: " + ", ".join(
            f"W{w} {n}" for w, n in sends["weekly"].items()))
    else:
        lines.append("  Weekly reports: none yet")
    if sends["finals"]:
        lines.append("  Saturday final checks: " + ", ".join(
            f"W{w} {n}" for w, n in sends["finals"].items()))
    for label, n in sorted(sends["other"].items()):
        lines.append(f"  {label[0].upper() + label[1:]}: {n}")
    lines += ["", "SUBSCRIBERS"]
    if registry is None:
        lines.append(f"  {registry_note}")
        if sends["weekly"]:
            last = max(sends["weekly"])
            lines.append(f"  (Week {last}'s send reached {sends['weekly'][last]} "
                         f"subscriber(s) — the closest count without it.)")
    else:
        # By what each row is billed as (LP-D3): a League Pass buyer used to
        # count as "season", which hid how many passes there are.
        names = {"season": "season", "monthly": "monthly",
                 "pass": "League Pass buyer", "league_pass": "League Pass seat"}
        plans = Counter(names.get(s.report_plan, s.report_plan) for s in registry)
        setups = Counter(f"{s.scoring}/{s.league_size}" for s in registry)
        lines.append(f"  {len(registry)} on the registry: " + ", ".join(
            f"{n} {plan}" for plan, n in sorted(plans.items())))
        lines.append("  Setups: " + ", ".join(f"{k} {n}" for k, n in setups.most_common()))
        for kind, label in (("trial", "free report"), ("waitlist", "waitlist")):
            if conv and kind in conv:
                got, asked = conv[kind]
                lines.append(f"  From the {label}: {got} of {asked} subscribe now")
        lines += seat_lines(registry)
    lines += ["", "PAYMENTS (Stripe, read-only)"]
    lines += payments if payments is not None else [
        "  STRIPE_API_KEY is not set in this shell — no payment view."]
    return "\n".join(lines) + "\n"


def _season_start(season: str) -> int | None:
    """Epoch seconds just after the previous season's last game — where this
    season's pass sales start — or None when the schedule can't say."""
    try:
        from run.solo import CACHE_DIR, season_ends
        last = season_ends(CACHE_DIR, live=False).get(str(int(season) - 1))
        day = datetime.fromisoformat(last).replace(tzinfo=timezone.utc) if last else None
    except Exception:  # noqa: BLE001 — unknown: count every pass ever, and say so
        return None
    return int((day + timedelta(days=1)).timestamp()) if day else None


# The page counter's read-only credentials, from this shell or the gitignored
# .env (LAUNCH.md step 5b) — read by the command line only (`cli`), so a test
# calling main() can never reach Cloudflare.
CF_NAMES = ("CF_ACCOUNT_ID", "CF_ANALYTICS_TOKEN")
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def read_env_file(path: Path, names: Iterable[str] = CF_NAMES) -> dict[str, str]:
    """``NAME=value`` lines of a .env file, for ``names`` only. Comments,
    ``export `` and matching quotes are understood; nothing is executed."""
    wanted, out = set(names), {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep or line.startswith("#") or key.strip() not in wanted:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def html_page(text: str) -> str:
    """The same view as a page in the report's palette, for a phone or a
    browser tab. Local only: --html writes it to a gitignored path."""
    import html as _html
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            '<meta name="robots" content="noindex"><title>Beat Your League — stats</title>'
            '<style>:root{--navy:#101E33;--gold:#F0B62A;--paper:#F7F4EC;--ink:#101E33;}'
            'body{margin:0;background:var(--paper);color:var(--ink);'
            'font:15px/1.5 Barlow,"Helvetica Neue",Arial,sans-serif;}'
            'header{background:var(--navy);color:#fff;padding:16px;'
            'border-bottom:4px solid var(--gold);font:800 20px/1.2 "Barlow Condensed",'
            'Barlow,"Helvetica Neue",Arial,sans-serif;letter-spacing:.04em;'
            'text-transform:uppercase;}'
            'pre{margin:0;padding:16px;overflow-x:auto;white-space:pre;'
            'font:13px/1.55 ui-monospace,Menlo,Consolas,monospace;}</style></head>'
            '<body><header>Beat Your League — stats</header><pre>'
            + _html.escape(text) + '</pre></body></html>\n')


def _gitignored(path: Path) -> bool:
    import subprocess
    root = Path(__file__).resolve().parent.parent
    try:
        done = subprocess.run(["git", "check-ignore", "-q", str(path.resolve())],
                              cwd=root, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def in_ci(environ: Mapping[str, str]) -> bool:
    return environ.get("GITHUB_ACTIONS") == "true" or bool(environ.get("CI"))


def cli(argv: list[str] | None = None, environ: Mapping[str, str] | None = None,
        env_file: Path | None = None) -> int:
    """The command line (`make stats`). Refuses in CI — the repository is
    public, so its job logs are too — and reads the counter's credentials
    from this shell, else the gitignored .env."""
    environ = os.environ if environ is None else environ
    if in_ci(environ):
        print("make stats does not run in CI: the repository is public, so the job "
              "log would publish sales and traffic. Run it on your own machine.",
              file=sys.stderr)
        return 2
    found = read_env_file(env_file or ENV_FILE)
    cf = {name: environ.get(name) or found.get(name, "") for name in CF_NAMES}
    return main(argv, cf=cf)


def main(argv: list[str] | None = None, cf: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--now")
    parser.add_argument("--html", type=Path, default=None,
                        help="also write the view as a page, to a gitignored path "
                             "such as data/stats.html")
    args = parser.parse_args(argv)
    now = (_when(args.now) if args.now else None) or datetime.now(timezone.utc)
    if args.html is not None and not _gitignored(args.html):
        print(f"{args.html} is not gitignored, so the counts could be committed to a "
              f"public repository — use a path such as data/stats.html.", file=sys.stderr)
        return 2

    rows: list[dict] | None = None
    endpoint = os.environ.get("FORM_ENDPOINT", "")
    if not endpoint:
        form_note = ("FORM_ENDPOINT is not set — the form Worker isn't deployed "
                     "yet, or its address isn't in this shell.")
    else:
        from run.intake import IntakeError, fetch_seats
        try:
            rows = fetch_seats(endpoint, os.environ.get("FORM_API_KEY"))
            form_note = ""
        except IntakeError as exc:
            form_note = f"Could not read the form Worker ({exc})."

    from run.delivery import SENT_LOG
    from run.solo import CACHE_DIR, current_season
    try:
        season = current_season(CACHE_DIR, today=now.date())
    except Exception:  # noqa: BLE001 — a summary still prints without the cache
        season = str(now.year if now.month >= 3 else now.year - 1)
    sends = send_summary(load_send_log(SENT_LOG), season)

    from run.rosters import RosterRegistryError, load_rosters
    registry, registry_note, conv = None, "", None
    try:
        registry = load_rosters(args.registry)
    except RosterRegistryError as exc:
        registry_note = (f"No registry on this machine ({exc}). It lives sealed in "
                         f"the CI cache; `make stats-registry` fetches and opens a "
                         f"copy, then pass --registry PATH.")
    if registry is not None and rows is not None:
        conv = conversions(rows, [s.email for s in registry])

    # Fail soft by design: a payments view that cannot be read is said in its
    # own section and changes neither the rest of the page nor the exit code.
    api_key = os.environ.get("STRIPE_API_KEY", "")
    payments = None
    if api_key:
        from run.checkout import parse_link_plans
        since = _season_start(season)
        payments = stripe_summary(
            api_key, now, rows=rows,
            link_plans=parse_link_plans(os.environ.get("STRIPE_PAYMENT_LINKS", "")),
            season_label=f"{season} season" if since is not None else "ever", since=since)
    # The same rule for traffic: one line says why it is missing, the exit
    # code is the rest of the page's.
    # Credentials arrive only through ``cf`` (the command line's), never read
    # here, so main() itself cannot reach Cloudflare unless handed them.
    cf = cf or {}
    traffic = traffic_summary(cf.get("CF_ACCOUNT_ID", ""), cf.get("CF_ANALYTICS_TOKEN", ""),
                              counter_endpoint())

    page = render(form_summary(rows, now) if rows is not None else None, form_note,
                  sends, season, registry, registry_note, conv, now,
                  channels=channel_summary(rows) if rows is not None else None,
                  payments=payments, traffic=traffic)
    print(page, end="")
    if args.html is not None:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(html_page(page), encoding="utf-8")
        print(f"(also written to {args.html})", file=sys.stderr)
    return 0 if (rows is not None or not endpoint) else 1


if __name__ == "__main__":
    sys.exit(cli())
