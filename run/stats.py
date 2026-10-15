"""The owner's one-screen view of demand — `make stats`.

Usage:
    python -m run.stats [--registry PATH] [--now ISO]

The site carries no analytics by design (a promise on the privacy page), so
without this the owner has no view of whether anyone is asking for the product.
Everything it needs is already stored:

- **The form Worker** (``FORM_ENDPOINT`` + ``FORM_API_KEY``): waitlist sign-ups,
  free-report requests, roster-update requests and confirmations, seat claims.
- **The send log** (``data/processed/sent.jsonl``, committed by the crons, so a
  ``git pull`` brings it up to date): what actually went out, week by week.
- **The registry**, when it is on this machine (it normally lives only in the
  CI cache): who subscribes, and so how many free reports turned into one.
- **Channels.** A form row may carry a ``via`` tag (which link brought the
  person: a post, a reply, a profile). Counted per kind, so the owner can see
  which channel a sign-up came from without any analytics on the site.
- **Stripe**, when ``STRIPE_API_KEY`` is set in this shell: active
  subscriptions by plan (read off each subscription's own price), checkout
  sessions of the last 7 days by outcome, refunds of the last 30. Read-only
  GETs. Each part that cannot be read says so and the rest still prints.

Counts only. No address is ever printed — this is the kind of output that gets
pasted into a chat or a note, and the send log keys carry digests for the same
reason. Read-only: nothing here sends, writes or changes anything.
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


def _subscriptions_line(subs: list[dict]) -> str:
    plans = Counter(_plan(s) for s in subs)
    # Still active, but ending: the buyer cancelled, or the monthly stop
    # (run/billing.py) is set. The churn signal, counted where it sits.
    ending = Counter(_plan(s) for s in subs
                     if s.get("cancel_at_period_end") or isinstance(s.get("cancel_at"), int))
    detail = ", ".join(
        f"{plan} {n}" + (f" ({ending[plan]} set to end)" if ending.get(plan) else "")
        for plan, n in sorted(plans.items(), key=lambda item: (-item[1], item[0])))
    return f"  Active subscriptions: {len(subs)}" + (f" — {detail}" if detail else "")


def _checkouts_line(sessions: list[dict]) -> str:
    by = Counter(str(s.get("status") or "unknown") for s in sessions)
    return (f"  Checkouts, last 7 days: {len(sessions)} created — "
            f"{by.get('complete', 0)} complete, {by.get('expired', 0)} expired, "
            f"{by.get('open', 0)} still open")


def _refunds_line(refunds: list[dict]) -> str:
    # A failed or cancelled refund returned nothing to anybody.
    given = [r for r in refunds if r.get("status") not in ("failed", "canceled")]
    return f"  Refunds, last 30 days: {len(given)}"


def stripe_summary(api_key: str, now: datetime) -> list[str]:
    """The payments half. Each read is independent — a key without Refunds
    access still shows subscriptions and checkouts — and a part that cannot
    be read says so instead of printing a zero it never counted."""
    week_ago = int((now - timedelta(days=7)).timestamp())
    month_ago = int((now - timedelta(days=30)).timestamp())
    parts = (
        ("subscriptions", "subscriptions", [("status", "active")], _subscriptions_line),
        ("checkout sessions", "checkout/sessions",
         [("created[gte]", str(week_ago))], _checkouts_line),
        ("refunds", "refunds", [("created[gte]", str(month_ago))], _refunds_line),
    )
    lines: list[str] = []
    for what, path, params, summarise in parts:
        try:
            lines.append(summarise(_stripe_list(path, params, api_key)))
        except Exception as exc:  # noqa: BLE001 — fail soft, say which part
            hint = (" — a restricted key needs Read on it"
                    if re.search(r"HTTP 40[13]", str(exc)) else "")
            lines.append(f"  Could not read {what} ({_safe(exc)}{hint}).")
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


def render(form: dict | None, form_note: str, sends: dict, season: str,
           registry: list | None, registry_note: str, conv: dict | None,
           now: datetime, channels: Mapping[str, Counter[str]] | None = None,
           payments: list[str] | None = None) -> str:
    lines = [f"Beat Your League — demand, {now:%a %b %d %Y %H:%M} UTC", ""]
    lines.append("FORMS (from the site)")
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
        plans = Counter(s.plan for s in registry)
        setups = Counter(f"{s.scoring}/{s.league_size}" for s in registry)
        lines.append(f"  {len(registry)} on the registry: " + ", ".join(
            f"{n} {plan}" for plan, n in sorted(plans.items())))
        lines.append("  Setups: " + ", ".join(f"{k} {n}" for k, n in setups.most_common()))
        for kind, label in (("trial", "free report"), ("waitlist", "waitlist")):
            if conv and kind in conv:
                got, asked = conv[kind]
                lines.append(f"  From the {label}: {got} of {asked} subscribe now")
    lines += ["", "PAYMENTS (Stripe, read-only)"]
    lines += payments if payments is not None else [
        "  STRIPE_API_KEY is not set in this shell — no payment view."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    now = (_when(args.now) if args.now else None) or datetime.now(timezone.utc)

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
        registry_note = (f"No registry on this machine ({exc}). It lives in the "
                         f"CI cache; pass --registry PATH to use a copy.")
    if registry is not None and rows is not None:
        conv = conversions(rows, [s.email for s in registry])

    # Fail soft by design: a payments view that cannot be read is said in its
    # own section and changes neither the rest of the page nor the exit code.
    api_key = os.environ.get("STRIPE_API_KEY", "")
    payments = stripe_summary(api_key, now) if api_key else None

    print(render(form_summary(rows, now) if rows is not None else None, form_note,
                 sends, season, registry, registry_note, conv, now,
                 channels=channel_summary(rows) if rows is not None else None,
                 payments=payments), end="")
    return 0 if (rows is not None or not endpoint) else 1


if __name__ == "__main__":
    sys.exit(main())
