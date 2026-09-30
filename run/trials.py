"""The free first report — one per person, this week's, for their own roster.

Usage:
    python -m run.trials [--dry-run] [--now ISO]

The strongest thing the site can show a buyer is THEIR team, decided. The
join page's try mode (`join/?try=1`) posts `{kind:"trial", email, ref}` to the
form Worker; this runner (hourly, from daily.yml) builds that roster's report
for the current week through the real pipeline and mails it.

Rules, each a way a free report could cost more than it earns:

- **One per address per season.** Keyed in the send log on a digest of the
  address, never the address itself (the log is committed).
- **Never a subscriber.** An address already on the registry has reports.
- **Nothing is recorded.** A trial is not a published call to a subscriber, so
  none of its probabilities enter the public ledger (the same rule run/trial.py
  follows for the operator's hand-made trials).
- **Never a report about games already underway.** From the main Sunday slate
  until the next week's data is in, a request waits and goes out with the next
  build — a free report that "predicts" a game in progress would be worthless
  and look it.
- **Bounded.** At most MAX_PER_RUN a run, so a flood of requests costs a
  bounded amount of compute and email.

Every piece fails closed: no endpoint, no provider or no data means nothing is
sent and the log says why.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_PER_RUN = 50
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def trial_key(season: str, email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:12]
    return f"trial-{season}-{digest}"


def main_slate_start(cache_dir: Path, season: str, week: int) -> datetime | None:
    """The week's busiest gameday at 1 PM ET: after it, the week is underway."""
    from run.saturday import kickoffs
    try:
        starts = kickoffs(cache_dir, season, week)
    except Exception:  # noqa: BLE001 — unknown means "underway"; hold
        return None
    if not starts:
        return None
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    days = Counter(t.astimezone(eastern).date() for t in starts.values())
    busiest = max(days, key=lambda d: (days[d], d))
    return datetime(busiest.year, busiest.month, busiest.day, 13,
                    tzinfo=eastern).astimezone(timezone.utc)


def pending(rows, registry_emails: set[str], sent: set[str], season: str
            ) -> list[tuple[str, str]]:
    """(email, ref) worth a free report: valid, not a subscriber, not already
    given one this season — newest request per address wins."""
    from run.refs import RefError, decode_roster
    chosen: dict[str, str] = {}
    for row in rows:
        if str(row.get("kind") or "") != "trial":
            continue
        email = str(row.get("email") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        if not _EMAIL_RE.match(email) or email in registry_emails:
            continue
        if trial_key(season, email) in sent:
            continue
        try:
            decode_roster(ref)
        except RefError:
            continue
        chosen[email] = ref
    return list(chosen.items())[:MAX_PER_RUN]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now")
    parser.add_argument("--registry", type=Path, default=None)
    args = parser.parse_args(argv)
    now = (datetime.fromisoformat(args.now) if args.now
           else datetime.now(timezone.utc))

    endpoint = os.environ.get("FORM_ENDPOINT", "")
    if not endpoint:
        print("Free reports: FORM_ENDPOINT is not set — nothing to read.")
        return 0
    from run.intake import IntakeError, fetch_seats
    try:
        rows = fetch_seats(endpoint, os.environ.get("FORM_API_KEY"))
    except IntakeError as exc:
        print(f"Free reports: could not read the form backend ({exc}).",
              file=sys.stderr)
        return 1

    from run.delivery import (DRY_PROVIDER, Message, build_provider, load_sent,
                              send_all)
    from run.rosters import RosterRegistryError, load_rosters
    from run.solo import CACHE_DIR, SoloError, current_season, current_week
    try:
        registry_emails = {s.email.lower() for s in load_rosters(args.registry)}
    except RosterRegistryError:
        registry_emails = set()
    season = current_season(CACHE_DIR, today=now.date())
    todo = pending(rows, registry_emails, load_sent(), season)
    if not todo:
        print("Free reports: none pending.")
        return 0
    week = current_week(CACHE_DIR, season, today=now.date())
    cutoff = main_slate_start(CACHE_DIR, season, week)
    if cutoff is None or now >= cutoff:
        print(f"Free reports: {len(todo)} waiting — week {week} is underway, so "
              f"they go out with the next week's build.")
        return 0

    from render.email import render_email, text_summary
    from render.report import cancel_destination
    from run.refs import decode_roster
    from run.solo import load_week_data, report_for, spec_from_ref
    try:
        data = load_week_data(CACHE_DIR, season, week)
    except SoloError as exc:
        print(f"Free reports: {len(todo)} waiting — this week's data isn't ready "
              f"({exc}).")
        return 0

    messages, failed = [], 0
    for email, ref in todo:
        roster = decode_roster(ref)
        try:
            # processed_dir=None: nothing reaches the ledger (module rule).
            report = report_for(spec_from_ref(roster), data,
                                league_size=roster.league_size)
        except Exception as exc:  # noqa: BLE001 — one request, not the run
            failed += 1
            print(f"  trial not built ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        report["meta"]["trial"] = True
        messages.append(Message(
            to=email, subject=f"Your free report: Week {data.week}, decided",
            html=render_email(report), text=text_summary(report),
            key=trial_key(season, email),
            unsubscribe=cancel_destination()[0] or None))

    if args.dry_run:
        print(f"Free reports (dry run): {len(messages)} built, {failed} failed.")
        return 1 if failed else 0
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"Free reports: {len(messages)} built — EMAIL_PROVIDER is not set, "
              f"so none were sent or recorded.")
        return 0
    sends = send_all(messages, provider=provider)
    sent_now = sum(1 for s in sends if s.ok and not s.skipped)
    errors = [s for s in sends if not s.ok]
    print(f"Free reports via {provider.name}: {sent_now} sent, {len(errors)} "
          f"failed, {failed} not built.")
    for result in errors:
        print(f"    TRIAL FAILED {result.message.key}: {result.detail}",
              file=sys.stderr)
    return 1 if (errors or failed) else 0


if __name__ == "__main__":
    sys.exit(main())
