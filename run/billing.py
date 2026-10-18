"""Stopping monthly billing when the season ends — the promise, enforced.

Five surfaces promise this, one of them the operative contract:

    render/welcome.py  "billing stops on its own when the season ends — we
                        don't charge through the offseason, because we aren't
                        sending you anything."
    site/terms.html    "We do not charge monthly through the offseason"
    site/index.html, site/join/index.html, and the payment link's own custom
    text above Stripe's Pay button (LAUNCH.md).

Nothing enforced any of it. A Stripe monthly subscription bills forever, and no
code in this repo had ever written to `/v1/subscriptions` at all — every Stripe
call was a read plus one customer-metadata write. So in February a monthly
subscriber would have been charged for a product that sends nothing,
which is precisely the forgot-to-cancel pattern PLAN §4 bans outright.

**What the subscriber is charged (D1, Oct 18 2026).** Monthly bills on the
anniversary of the purchase, and billing stops on its own AFTER THE SEASON'S
LAST WEEKLY REPORT: the last charge is the month that report falls in. No
charge ever starts a period with no weekly report in it, there is no part-month
stub, and nothing is charged after the season. Mechanically: a monthly
subscription is stamped ``cancel_at_period_end`` only once its CURRENT period
ends after the season's last weekly send — that is its final paid period — and
until then it carries nothing, so the billing page keeps its normal Cancel
button.

That replaced a ``cancel_at`` written months ahead (the last send plus a retry
week), which was wrong twice over, both reproduced in the promises audit:

- Stripe's billing page treats a subscription carrying a ``cancel_at`` as
  already cancelled — "Cancels on <date>", a Reactivate button and NO Cancel
  button — so from the day after purchase a monthly subscriber could not stop
  the November and December charges themselves (LEGAL-33/34/38).
- The date sat three days after the last game, so a billing day of Jan 11-12
  renewed into a prorated stub for days after the season (LEGAL-31, EMAILS-94).

Rules, each bought with a reproduced failure in review:

RULE B1 — NEVER DELETE, NEVER GUESS A SEASON. `run/solo.py:current_season`
answers the season that just ENDED once the next schedule is unpublished (its
own docstring concedes the fallback), which is right for "which season is this
report about" and catastrophic here. `final_send` answers only a season whose
last game has not been played, and when there is none — or the schedule cannot
be read — the run REPORTS any monthly subscription still billing and acts on
none of them. A missing date is a problem to raise, never a licence to end
somebody's subscription.

RULE B2 — THE PLAN COMES FROM THE PRICE. The interval on the subscription's own
price decides, never our `plan` field and never a ref: `$39/year` and `$99/year`
must renew, and a bug that reads a claim rather than the price would cancel
them. Same reasoning as STRIPE_PAYMENT_LINKS being authoritative over a ref
prefix. `run/renewals.py` already reads intervals this way.

RULE B3 — THE FINAL PERIOD, AND NOT ONE DAY BEFORE IT. The stop is written only
when the subscription's current period ends after the last weekly send is DUE
(the Tuesday run's scheduled minute, `run.watchdog.tuesday_due_at`, of the
first Tuesday `current_week` answers the last week — derived from the send
calendar, not from "the finale is a Sunday", which is true of 24 of 28 cached
seasons and is not a rule). A period that ends before that instant renews into
the period the last report falls in, which is the month the subscriber is
owed; one that ends after it would renew into a month with no report. Written
any earlier, the stop takes the Cancel button away (above).

RULE B4 — OUR SUBSCRIPTIONS ONLY. Scoped to customers carrying `byl_roster_ref`.
A sweep over every non-yearly subscription in the account would attach a
season-end stop to anything else ever sold from it.

RULE B5 — A CANCEL ALREADY ON THE SUBSCRIPTION IS DONE. One the customer set in
the portal (Stripe stores it as `cancel_at`), one a human set in the Dashboard,
or one we set: each already ends the billing, and none is overwritten.

Dry by default like every other sender here (`run/renewals.py --send`): this is
the first money-mutating call in the repo, and a misconfigured cron must not
cancel real subscriptions by accident.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ingest.nflverse import NflverseError
from run.checkout import post as _stripe_post
from run.solo import SoloError, current_week, season_ends
from run.subscriptions import SubscriptionError, _stripe_get

SUBSCRIPTIONS_API = "https://api.stripe.com/v1/subscriptions"

REPO_ROOT = Path(__file__).resolve().parent.parent
# The SAME directory every other nflverse reader uses (run/solo.py,
# render/player_index.py, engine/ledger.py). `fetch` resolves `cache_dir /
# asset` with no subdirectory of its own, so `data/raw` here quietly created a
# SECOND games.csv at `data/raw/games.csv` — a copy no cron restores and none
# saves, so in CI it downloads on every run and an nflverse outage becomes
# (None, None) and a filed bug issue, instead of falling back to the cached
# schedule the way `fetch` intends.
CACHE_DIR = REPO_ROOT / "data" / "raw" / "nflverse"

# The customer metadata run/intake.py stamps on every roster purchase. RULE B4.
ROSTER_METADATA_KEY = "byl_roster_ref"

# Stamped alongside the stop so a later reader can tell OUR end-of-season stop
# from a cancellation the customer made: the period end it stops at.
STOP_METADATA_KEY = "byl_offseason_stop"

# Yearly plans renew. Everything else is the monthly-shaped tier this stops.
YEARLY = "year"

# Statuses we may write to. A canceled subscription cannot be updated at all
# (Stripe accepts only metadata and cancellation_details after the fact), and
# incomplete_expired never became anything.
WRITABLE = ("active", "trialing", "past_due")

# Statuses that are still live but that we deliberately do not touch: a paused
# subscription resumes billing on its own, so it needs saying out loud rather
# than passing silently through a filter.
REPORTABLE = ("paused", "unpaid")

NOT_CONFIGURED = 2


class BillingError(RuntimeError):
    pass


# --------------------------------------------------------------------- #
# when does billing stop?
# --------------------------------------------------------------------- #

def last_send(cache_dir: Path, season: str, *,
              live: bool = False) -> date | None:
    """The Tuesday the season's final report actually goes out.

    Derived by walking the real `current_week`, not by assuming the last game
    is a Sunday: measured across 28 cached seasons the finale falls on a Sunday
    24 times and a Monday 4 times, and 2010's final send lands two days AFTER
    its last game because a week-16 makeup held `current_week` back. A fixed
    offset would have been right most years and silently wrong in the others.

    The send is the FIRST Tuesday on which `current_week` answers the last week
    — later Tuesdays answer it too, but the delivery key is per (season, week),
    so they mail nothing new.
    """
    ends = season_ends(cache_dir, live=live)
    end = ends.get(str(season))
    if not end:
        return None
    final = date.fromisoformat(end)
    try:
        last_week = current_week(cache_dir, str(season), final, session=None)
    except SoloError:
        return None
    # Start a fortnight before the finale and walk forward: enough to cover the
    # makeup case above without assuming where in the week anything falls.
    day = final - timedelta(days=21)
    day += timedelta(days=(1 - day.weekday()) % 7)          # next Tuesday
    while day <= final + timedelta(days=14):
        try:
            if current_week(cache_dir, str(season), day, session=None) >= last_week:
                return day
        except SoloError:
            return None
        day += timedelta(days=7)
    return None


def final_send(cache_dir: Path, today: date | None = None, *,
               live: bool = False) -> tuple[datetime | None, str | None]:
    """(the instant the season's LAST weekly report is due, that season).

    The season is the earliest one whose last game has NOT been played — a
    season still to be served. RULE B1: when there is no such season the answer
    is (None, None), which the caller reports and acts on in no way whatsoever.
    Reaching for `current_season` here would answer the season that just ended.

    The instant may already be past (the days between the last report and the
    last game): every monthly subscription's current period then ends after
    it, which is exactly right — none of them may renew again.

    Fails closed on every data problem. `_schedule` reaches `ingest.nflverse`,
    whose `NflverseError` is NOT a subclass of `SoloError` — verified — so an
    outage or a cold cache raises a class the caller's `except SoloError` would
    not have caught.
    """
    from run.watchdog import tuesday_due_at
    when = today or datetime.now(timezone.utc).date()
    try:
        ends = season_ends(cache_dir, live=live)
    except (NflverseError, SoloError, OSError, ValueError):
        return None, None
    upcoming = [s for s in sorted(ends) if ends[s] >= when.isoformat()]
    if not upcoming:
        return None, None
    season = upcoming[0]
    try:
        send = last_send(cache_dir, season, live=live)
    except (NflverseError, SoloError, OSError, ValueError):
        return None, None
    if send is None:
        return None, None
    return tuesday_due_at(send), season


# run/economics.py models what a monthly buyer pays from this date.
stop_for = final_send


# --------------------------------------------------------------------- #
# reading Stripe
# --------------------------------------------------------------------- #

def _interval(subscription: Mapping[str, Any]) -> str | None:
    items = ((subscription.get("items") or {}).get("data") or [])
    first = items[0] if items and isinstance(items[0], dict) else {}
    return (((first.get("price") or {}).get("recurring") or {}).get("interval"))


def _period_end(subscription: Mapping[str, Any]) -> int | None:
    items = ((subscription.get("items") or {}).get("data") or [])
    first = items[0] if items and isinstance(items[0], dict) else {}
    for value in (first.get("current_period_end"),
                  subscription.get("current_period_end")):
        if isinstance(value, int):
            return value
    return None


def _already_stopping(subscription: Mapping[str, Any]) -> bool:
    """Both of Stripe's ways of saying "this one is scheduled to end".

    One predicate because two readings of it drifted: `needs_stop` skipped
    these and `main`'s census did not, so a subscription carrying a perfectly
    good stop date was counted among those "billing with nothing to stop
    them" — and the alarm went off about a date we had set ourselves.
    """
    return (bool(subscription.get("cancel_at_period_end"))
            or isinstance(subscription.get("cancel_at"), int))


def _is_ours(subscription: Mapping[str, Any]) -> bool:
    """RULE B4. The customer must carry the roster stamp intake writes."""
    customer = subscription.get("customer")
    if not isinstance(customer, dict):
        return False
    metadata = customer.get("metadata")
    return bool(isinstance(metadata, dict) and metadata.get(ROSTER_METADATA_KEY))


def load_subscriptions(api_key: str) -> list[dict]:
    """Every subscription on the account, customers expanded.

    Expanded because RULE B4 needs the customer's metadata to tell our
    subscribers from anything else the account ever sells, and an id string
    cannot answer that.
    """
    out: list[dict] = []
    query = {"limit": "100", "status": "all", "expand[]": "data.customer"}
    url = f"{SUBSCRIPTIONS_API}?{urllib.parse.urlencode(query)}"
    while True:
        page = _stripe_get(url, api_key)
        data = page.get("data")
        data = data if isinstance(data, list) else []
        out.extend(row for row in data if isinstance(row, dict))
        last = data[-1].get("id") if data and isinstance(data[-1], dict) else None
        if not page.get("has_more") or not last:
            return out
        url = (f"{SUBSCRIPTIONS_API}?{urllib.parse.urlencode(query)}"
               f"&starting_after={urllib.parse.quote(str(last))}")


# --------------------------------------------------------------------- #
# deciding
# --------------------------------------------------------------------- #

def needs_stop(subscriptions: Iterable[Mapping[str, Any]], final: datetime,
               ) -> tuple[list[dict], list[str]]:
    """(the subscriptions in their final paid period, things worth saying out
    loud), against ``final`` — the instant the season's last report is due.

    Everything the filter drops is dropped for a stated reason, and the two
    live-but-untouched statuses are REPORTED rather than skipped in silence: a
    paused subscription starts billing again by itself, so a stop it never
    received is a charge nobody is expecting.
    """
    cutoff = int(final.timestamp())
    due: list[dict] = []
    notes: list[str] = []
    for subscription in subscriptions:
        if not _is_ours(subscription):
            continue
        interval = _interval(subscription)
        # RULE B2 FIRST, before status is ever considered. A yearly price may
        # never receive a stop, so no state it is ever in is this module's
        # business — and checking status first meant a $39 pass sitting in
        # Stripe's `unpaid` dunning end-state produced a note, which fails the
        # run, which files a bug issue, EVERY DAY, about a subscription there is
        # by definition nothing to do about.
        if interval == YEARLY:
            continue
        status = subscription.get("status")
        if status in REPORTABLE:
            notes.append(
                f"subscription {subscription.get('id')} is {status} and was not "
                f"given a stop — Stripe resumes billing a {status} subscription "
                f"without asking us, so this one needs a human")
            continue
        if status not in WRITABLE:
            continue
        if interval is None:
            notes.append(f"subscription {subscription.get('id')} has no readable "
                         f"billing interval — left alone rather than guessed at")
            continue
        if _already_stopping(subscription):
            continue                             # RULE B5: already ending
        period_end = _period_end(subscription)
        if period_end is None:
            notes.append(f"subscription {subscription.get('id')} has no readable "
                         f"period end — left alone rather than guessed at")
            continue
        # RULE B3. Ends before the last report is due: the next renewal starts
        # the period that report falls in, which is owed. Ends after it: this
        # is the final paid period, and the next renewal would have no report.
        if period_end > cutoff:
            due.append(dict(subscription))
    return due, notes


def apply_stop(api_key: str, subscription: Mapping[str, Any]) -> None:
    """One write: end the subscription when the period already paid for ends.

    `cancel_at_period_end` never refunds, never prorates and never charges:
    the subscriber keeps every report in the period they paid for, and there
    is no further charge. Written only in the final period (RULE B3), it is
    the state Stripe's billing page shows as "Cancels on <date>" — true then,
    because nothing more will be billed.
    """
    form = {"cancel_at_period_end": "true"}
    period_end = _period_end(subscription)
    if isinstance(period_end, int):
        form[f"metadata[{STOP_METADATA_KEY}]"] = str(period_end)
    _stripe_post(
        f"{SUBSCRIPTIONS_API}/{urllib.parse.quote(str(subscription.get('id')))}",
        api_key, form,
        what="ending a monthly subscription after its final paid period",
        needs="WRITE access to Subscriptions")


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--send", action="store_true",
                        help="actually end final-period subscriptions in Stripe")
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="pretend it is this date (testing)")
    args = parser.parse_args(argv)

    api_key = os.environ.get("STRIPE_API_KEY", "")
    if not api_key:
        # EXIT 2 like every other pre-launch state: expected until checkout
        # opens, and a cron filing an issue for it weekly teaches you to ignore
        # the issues, which is how the real one gets missed.
        print("STRIPE_API_KEY is not set — no subscriptions to stop. That is "
              "expected until checkout opens.", file=sys.stderr)
        return NOT_CONFIGURED

    at, season = final_send(Path(args.cache), args.today, live=args.today is None)

    line = "=" * 62
    print(f"\n{line}\nOFFSEASON BILLING STOP"
          f"{'' if args.send else ' (dry run)'}\n{line}")

    try:
        subscriptions = load_subscriptions(api_key)
    except SubscriptionError as exc:
        print(f"could not read Stripe: {exc}", file=sys.stderr)
        return 1

    ours = [s for s in subscriptions if _is_ours(s)]
    # WRITABLE **and** REPORTABLE. A paused or unpaid subscription resumes
    # billing on its own, so in the offseason gap — where this branch returns
    # before needs_stop is ever called — filtering to WRITABLE alone let one
    # pass through in complete silence at exit 0, which is the only state where
    # nothing else would ever mention it.
    monthly = [s for s in ours
               if _interval(s) not in (None, YEARLY)
               and s.get("status") in WRITABLE + REPORTABLE]
    # The alarm population, and it must agree with `needs_stop` — a subscription
    # already ending is not "billing with nothing to stop it". In-season every
    # monthly subscription is stamped in its final period, so once the season
    # is over this population is empty unless something went wrong.
    unstopped = [s for s in monthly if not _already_stopping(s)]

    if at is None:
        # RULE B1. Never a licence to end anybody's subscription.
        print(f"Subscriptions: {len(ours)} ours, {len(monthly)} monthly, "
              f"{len(monthly) - len(unstopped)} already stopping")
        if unstopped:
            print(f"NO SEASON TO SERVE: {len(unstopped)} monthly subscription(s) are "
                  f"billing with nothing set to stop them, and no season "
                  f"still to be played could be read from the schedule"
                  + (f" (the most recent is {season})." if season else ".")
                  + " Nothing was cancelled; this needs a human.",
                  file=sys.stderr)
            print(line)
            return 1
        print("Nothing billing without a stop, and no season still to be "
              "played — nothing to do.")
        print(line)
        return 0

    due, notes = needs_stop(subscriptions, at)
    print(f"Season {season}: the last weekly report is due {at:%Y-%m-%d %H:%M} "
          f"UTC; a monthly period ending after it is the final one")
    print(f"Subscriptions: {len(ours)} ours, {len(monthly)} monthly, "
          f"{len(due)} in their final paid period")

    failures: list[str] = []
    for subscription in due:
        label = str(subscription.get("id"))
        if not args.send:
            print(f"  [would set] {label}")
            continue
        try:
            apply_stop(api_key, subscription)
            print(f"  [set] {label}")
        except SubscriptionError as exc:
            failures.append(f"{label}: {exc}")

    for note in notes:
        print(f"  ! {note}", file=sys.stderr)
    for failure in failures:
        print(f"  FAILED {failure}", file=sys.stderr)

    if not args.send and due:
        print(f"(dry run — nothing written. Pass --send to end {len(due)} "
              f"subscription(s) at the end of their final paid period.)")
    if failures:
        print(f"{len(failures)} subscription(s) in their final period could "
              f"not be stopped. Each renews into a month with no report unless "
              f"a later run succeeds before its period ends.", file=sys.stderr)
    print(line)
    return 1 if (failures or notes) else 0


if __name__ == "__main__":
    sys.exit(main())
