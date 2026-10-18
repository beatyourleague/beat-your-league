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
- **Only a fresh request, made this season.** A request older than
  TRIAL_MAX_AGE, or received before the current season's first game, is
  never mailed. The Worker keeps rows ~400 days and the key is per season, so
  without this a request served last October came back the next June as a
  "Week 1, decided" email to someone who asked eight months earlier, built
  from last season's roster — and the stale backlog spent the daily allowance
  ahead of real requests (reproduced, launch review OPS-3). A row with no
  readable Worker stamp cannot be shown to be fresh, so it is not mailed.
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
  bounded amount of compute and email — and at most TRIAL_DAILY_CAP a day,
  counted from the send log. The email provider's free tier is 100 messages a
  day, and that allowance belongs to the people paying first.
- **Paying subscribers go first on Tuesday.** Requests held from Thursday's
  kickoff to the next week's build all come due on Tuesday morning, the same
  morning as every subscriber's report. Until the Tuesday run has left its
  marker in the send log (``run.watchdog``) — or until 20:00 UTC,
  whichever is first — free reports wait, so a weekend's backlog can never
  spend the day's sending allowance before the reports people paid for.
- **Before launch is not a failure.** The registry is read only when there
  are requests to check against it, and a MISSING registry while no Stripe key
  is set reads as nobody subscribing (nobody can have paid). Setting
  FORM_ENDPOINT before checkout opened used to turn every hourly run red,
  because the registry was loaded first and did not exist. A registry that
  exists but cannot be read still fails CLOSED: with the subscriber list
  unknown, every subscriber would read as eligible for a "free" report.

Every piece fails closed: no endpoint, no provider or no data means nothing is
sent and the log says why. Requests waiting with NO email provider is the one
quiet state that is a failure (OPS-08): the page promises "usually within the
hour", nothing can ever keep it, so the run exits 1 and the cron files an issue.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_PER_RUN = 50
TRIAL_DAILY_CAP = 40
# A request is acted on within days or not at all: past this it is somebody
# who asked about a different week, and mailing them now is unrequested mail.
# Two weeks covers the longest wait a real request has (held from Thursday's
# kickoff to the next build, or behind a full daily allowance) with room left.
TRIAL_MAX_AGE = timedelta(days=14)
# On a Tuesday (UTC), free reports wait for the subscriber run's marker or
# this hour, whichever comes first. The retry runs at 16:17 and is done well
# before 20:00, so the fallback only fires when Tuesday failed outright — and
# then the watchdog says so separately.
TUESDAY_RELEASE_HOUR = 20
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
    """One free report per mailbox per season. The code is keyed under
    LOG_SECRET (run/digest.py): the send log is public, and a plain hash of
    the address would let anybody who knows it see it asked for one."""
    from run.digest import address
    return f"trial-{season}-{address(email)}"


def week_underway_from(cache_dir: Path, season: str, week: int) -> datetime | None:
    """The week's FIRST kickoff: from then on the week is underway. None when
    it can't be told, which the caller reads as underway."""
    from run.saturday import kickoffs
    try:
        starts = kickoffs(cache_dir, season, week)
    except Exception:  # noqa: BLE001 — unknown means "underway"; hold
        return None
    return min(starts.values()) if starts else None


def held_for_tuesday(now: datetime, sent: set[str], season: str, week: int) -> bool:
    """True while today's subscriber reports may still be going out."""
    from run.watchdog import tuesday_finished
    now = now.astimezone(timezone.utc)
    return (now.weekday() == 1 and now.hour < TUESDAY_RELEASE_HOUR
            and not tuesday_finished(sent, season, week))


def sent_today(entries, now: datetime) -> int:
    """Free reports the send log says went out on ``now``'s UTC date."""
    day = now.astimezone(timezone.utc).date()
    count = 0
    for entry in entries:
        if not str(entry.get("key") or "").startswith("trial-"):
            continue
        try:
            at = datetime.fromisoformat(str(entry.get("sent_at") or ""))
        except ValueError:
            count += 1                 # unreadable: count it, never free a slot
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at.astimezone(timezone.utc).date() == day:
            count += 1
    return count


def received(row) -> datetime | None:
    """When the Worker stamped this row (its own clock — a caller cannot set
    it), or None when there is no readable stamp."""
    raw = str(row.get("received_at") or "").strip()
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def season_start(cache_dir: Path, season: str) -> datetime | None:
    """The current season's first kickoff (week 1's first game), or None when
    it cannot be told — which the caller reads as "no request is fresh"."""
    return week_underway_from(cache_dir, season, 1)


def not_before(now: datetime, start: datetime | None) -> datetime | None:
    """The oldest a request may be and still be mailed: TRIAL_MAX_AGE ago, and
    never before this season's first game. None (the season's start unknown)
    means nothing is fresh enough. Pure."""
    if start is None:
        return None
    return max(now - TRIAL_MAX_AGE, start)


def pending(rows, registry_emails: set[str], sent: set[str], season: str, *,
            since: datetime | None) -> list[tuple[str, str]]:
    """(email, ref) worth a free report: received at or after ``since`` (see
    :func:`not_before`; None admits nothing), valid, not a subscriber, not
    already given one this season — newest request per address wins.

    ``since`` is required on purpose: a caller that forgot it would bring
    back every row the Worker still holds, which is the stale-request bug."""
    from run.refs import RefError, decode_roster
    chosen: dict[str, str] = {}
    held = {canonical_email(e) for e in registry_emails}
    for row in rows:
        if str(row.get("kind") or "") != "trial":
            continue
        stamp = received(row)
        if since is None or stamp is None or stamp < since:
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
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    endpoint = os.environ.get("FORM_ENDPOINT", "")
    if not endpoint:
        print("Free reports: FORM_ENDPOINT is not set — nothing to read.")
        return 0
    from run.digest import DigestError, secret as log_secret
    try:
        log_secret()
    except DigestError as exc:
        # Refuse: without the key no request can be matched to the send log,
        # so "one per mailbox per season" could not be kept.
        print(f"Free reports: {exc}", file=sys.stderr)
        return 1
    from run.intake import IntakeError, fetch_seats
    try:
        rows = fetch_seats(endpoint, os.environ.get("FORM_API_KEY"))
    except IntakeError as exc:
        print(f"Free reports: could not read the form backend ({exc}).",
              file=sys.stderr)
        return 1

    from run.delivery import (DRY_PROVIDER, Message, build_provider, load_sent,
                              send_all, sent_entries)
    from run.rosters import RosterRegistryError, load_rosters
    from run.solo import (CACHE_DIR, SoloError, current_season, current_week,
                          season_over)
    from run.watchdog import not_configured
    season = current_season(CACHE_DIR, today=now.date())
    sent = load_sent()
    since = not_before(now, season_start(CACHE_DIR, season))
    if since is None and any(str(r.get("kind") or "") == "trial" for r in rows):
        print(f"Free reports: the {season} schedule's first game can't be read, "
              f"so no request can be shown to be from this season; none sent.")
    # Is there anything to do at all? Asked BEFORE the registry is read: an
    # hourly run with no requests has no business failing on the registry.
    if not pending(rows, set(), sent, season, since=since):
        print("Free reports: none pending.")
        return 0
    prelaunch = not_configured(args.registry)
    if prelaunch:
        registry_emails: set[str] = set()      # nobody can have paid yet
    else:
        try:
            registry_emails = {s.email.lower() for s in load_rosters(args.registry)}
        except RosterRegistryError as exc:
            # Fail CLOSED: with the subscriber list unreadable, every
            # subscriber would read as eligible for a "free" report.
            print(f"Free reports: the subscriber registry is unreadable ({exc}); "
                  f"nothing was sent.", file=sys.stderr)
            return 1
    todo = pending(rows, registry_emails, sent, season, since=since)
    if not todo:
        print("Free reports: none pending.")
        return 0
    if season_over(CACHE_DIR, season, now.date()):
        print(f"Free reports: {len(todo)} waiting — the {season} season is over.")
        return 0
    week = current_week(CACHE_DIR, season, today=now.date())
    cutoff = week_underway_from(CACHE_DIR, season, week)
    if cutoff is None or now >= cutoff:
        print(f"Free reports: {len(todo)} waiting — week {week} is underway, so "
              f"they go out with the next week's build.")
        return 0
    # Before launch there are no subscriber reports to go first.
    if not prelaunch and held_for_tuesday(now, sent, season, week):
        print(f"Free reports: {len(todo)} waiting — subscribers' Tuesday reports "
              f"go out first (until that run finishes, or "
              f"{TUESDAY_RELEASE_HOUR}:00 UTC).")
        return 0
    room = TRIAL_DAILY_CAP - sent_today(sent_entries(), now)
    if room <= 0:
        print(f"Free reports: {len(todo)} waiting — today's {TRIAL_DAILY_CAP} "
              f"have gone out; the rest go tomorrow.")
        return 0
    limit = min(MAX_PER_RUN, room)

    # Somebody asked, the page told them it "usually lands within the hour",
    # and nothing can send it (OPS-08). Every earlier return above is a request
    # waiting for a real reason — the week underway, subscribers first, the
    # day's allowance spent — and stays quiet. This one is a misconfiguration
    # that waits forever, so it goes red and the hourly cron files its issue.
    # Decided before anything is built: a report nobody can send is wasted work.
    provider = None
    if not args.dry_run:
        provider = build_provider(None)
        if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
            print(f"FREE REPORTS NOT SENT: {len(todo)} request(s) are waiting and "
                  f"EMAIL_PROVIDER is not set, so none can be mailed. Set it (and "
                  f"its key), or turn the free report off on the site "
                  f"(TRIAL_OPEN).", file=sys.stderr)
            return 1

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
        if len(messages) >= limit:
            break                       # the caps count BUILT reports only
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
    if args.dry_run or provider is None:
        print(f"Free reports (dry run): {len(messages)} built.")
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
