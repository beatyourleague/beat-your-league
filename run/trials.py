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
- **Never a report about games already underway.** From the week's FIRST
  kickoff (Thursday night) until the next week's data is in, a request waits and
  goes out with the next build — a free report that "predicts" a game already
  played would be worthless and look it. (An earlier cutoff of the main Sunday
  slate left Thursday-to-Sunday requests mailed a report saying "before this
  week's first kickoff" about a game two days old — found by review, Sep 29.)
- **One person is one address.** `+tag` aliases are dropped and Gmail dots
  ignored before the one-per-season key and the subscriber check, or a
  free report could be had again and again, and a subscriber could get one.
- **A bad request never blocks the good ones.** An unbuildable roster is
  skipped and named, never counted toward the per-run cap, and never fails the
  job (the public form makes a bad row remotely triggerable, and the hourly
  cron files an issue for every failed run).
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_PER_RUN = 50
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def canonical_email(email: str) -> str:
    """One mailbox, one spelling: lowercase, no `+tag`, and no dots in a Gmail
    local part (Gmail ignores them)."""
    address = (email or "").strip().lower()
    local, _, domain = address.partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def trial_key(season: str, email: str) -> str:
    digest = hashlib.sha256(canonical_email(email).encode("utf-8")).hexdigest()[:12]
    return f"trial-{season}-{digest}"


def week_underway_from(cache_dir: Path, season: str, week: int) -> datetime | None:
    """The week's FIRST kickoff: from then on the week is underway. None when
    it can't be told, which the caller reads as underway."""
    from run.saturday import kickoffs
    try:
        starts = kickoffs(cache_dir, season, week)
    except Exception:  # noqa: BLE001 — unknown means "underway"; hold
        return None
    return min(starts.values()) if starts else None


def pending(rows, registry_emails: set[str], sent: set[str], season: str
            ) -> list[tuple[str, str]]:
    """(email, ref) worth a free report: valid, not a subscriber, not already
    given one this season — newest request per address wins."""
    from run.refs import RefError, decode_roster
    chosen: dict[str, str] = {}
    held = {canonical_email(e) for e in registry_emails}
    for row in rows:
        if str(row.get("kind") or "") != "trial":
            continue
        email = canonical_email(str(row.get("email") or ""))
        ref = str(row.get("ref") or "").strip()
        if not _EMAIL_RE.match(email) or email in held:
            continue
        if trial_key(season, email) in sent:
            continue
        try:
            decode_roster(ref)
        except RefError:
            continue
        chosen[email] = ref
    return list(chosen.items())


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
    except RosterRegistryError as exc:
        # Fail CLOSED: with the subscriber list unreadable, every subscriber
        # would read as eligible for a "free" report.
        print(f"Free reports: the subscriber registry is unreadable ({exc}); "
              f"nothing was sent.", file=sys.stderr)
        return 1
    season = current_season(CACHE_DIR, today=now.date())
    todo = pending(rows, registry_emails, load_sent(), season)
    if not todo:
        print("Free reports: none pending.")
        return 0
    week = current_week(CACHE_DIR, season, today=now.date())
    cutoff = week_underway_from(CACHE_DIR, season, week)
    if cutoff is None or now >= cutoff:
        print(f"Free reports: {len(todo)} waiting — week {week} is underway, so "
              f"they go out with the next week's build.")
        return 0

    from render.email import render_email, text_summary
    from run.refs import decode_roster
    from run.solo import load_week_data, report_for, spec_from_ref
    try:
        data = load_week_data(CACHE_DIR, season, week)
    except SoloError as exc:
        print(f"Free reports: {len(todo)} waiting — this week's data isn't ready "
              f"({exc}).")
        return 0

    messages, failed, skipped = [], 0, []
    known = {p.player_id for p in data.directory.players}
    for email, ref in todo:
        if len(messages) >= MAX_PER_RUN:
            break                       # the cap counts BUILT reports only
        roster = decode_roster(ref)
        if any(pid not in known for pid in roster.player_ids):
            # A ref that decodes but names a player the directory has never
            # heard of: skipped and named, never a failed run.
            skipped.append(trial_key(season, email)[-12:])
            continue
        try:
            # processed_dir=None: nothing reaches the ledger (module rule).
            report = report_for(spec_from_ref(roster), data,
                                league_size=roster.league_size)
        except Exception as exc:  # noqa: BLE001 — one request, not the run
            skipped.append(trial_key(season, email)[-12:])
            print(f"  trial not built ({type(exc).__name__}: {exc})")
            continue
        report["meta"]["trial"] = True
        messages.append(Message(
            to=email, subject=f"Your free report: Week {data.week}, decided",
            html=render_email(report), text=text_summary(report),
            key=trial_key(season, email),
            # No list to leave and no subscription to cancel: a header pointing
            # at the subscription-cancel page would be wrong for this reader.
            unsubscribe=None))

    if skipped:
        print(f"Free reports: {len(skipped)} request(s) skipped as unbuildable "
              f"({', '.join(skipped[:5])}).")
    if args.dry_run:
        print(f"Free reports (dry run): {len(messages)} built.")
        return 0
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"Free reports: {len(messages)} built — EMAIL_PROVIDER is not set, "
              f"so none were sent or recorded.")
        return 0
    sends = send_all(messages, provider=provider)
    sent_now = sum(1 for s in sends if s.ok and not s.skipped)
    errors = [s for s in sends if not s.ok]
    print(f"Free reports via {provider.name}: {sent_now} sent, {len(errors)} failed.")
    for result in errors:
        print(f"    TRIAL FAILED {result.message.key}: {result.detail}",
              file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
