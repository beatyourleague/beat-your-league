"""The dead-man's switch: did this week's scheduled runs actually happen?

Usage:
    python -m run.watchdog [--now 2026-10-14T14:00:00+00:00] [--registry PATH]
    python -m run.watchdog --claim-day        (daily.yml's once-a-day gate)

A run that never starts fails nothing, so it files nothing. GitHub's scheduler
started the Tuesday crons 5-7 hours late on Oct 6 and Oct 13 2026 and dropped
most of the hourly runs; a Tuesday it dropped outright would have been found
when a subscriber wrote in to ask where their report was. The Saturday final
check is quieter still: it mails only when a lineup has to change, so a check
that never ran looks exactly like a week with no news.

So the once-a-day run (daily.yml, 14:00 UTC) asks two questions about the
current week and goes red when either answer is no:

- **Tuesday**, from the Wednesday after the week's send Tuesday: did a Tuesday
  run for this week leave its marker? ``run.tuesday`` writes it at the end of
  every run that got as far as sending, with what it sent and what failed.
- **Saturday**, from the Sunday after: the final check's marker, written the
  same way by ``run.saturday``.

**The marker is the only evidence (launch review, Oct 15 2026).** A week's
report key used to count too, and ``run.intake`` mails a NEW buyer that week's
report under exactly that key, hourly, from Tuesday until kickoff — so one
purchase on a Wednesday covered a Tuesday GitHub had dropped for everybody
else, and the watchdog said all clear.

**Only somebody who was owed the run can make it missing.** A Tuesday is owed
to subscribers whose purchase predates its send (12:00 UTC on the send
Tuesday); a Saturday check to subscribers who bought before the week's first
kickoff (they were sent that week's lineup, by Tuesday or at purchase). In
launch week the secrets can go in AFTER a Tuesday that ran unconfigured and
left no marker — and the first purchase, maybe the owner's own proving one,
then read as a missed Tuesday every day until the next one. Purchase times
come from the signup log beside the registry; a subscriber with no readable
purchase (a hand-added row, a seat whose payer is not in the log) counts as
owed, because an alarm is the safe direction to be wrong in.

The markers live in the send log because it is the one record every sending
cron already commits, under ``merge=union`` (``.gitattributes``), so a push race
concatenates lines rather than losing them. They are keyed
``run-<kind>-<season>-wNN`` (and ``run-daily-<date>`` for the once-a-day gate),
a shape no message key has, so nothing that reads the log for sends can mistake
one for a send. A dry run writes none — the same rule as for a send, and for
the same reason: a preview must leave no record claiming something happened.

Quiet, exit 0: nothing set up yet (no registry file and no Stripe key — the
state before checkout opens), an empty registry, the offseason, a week whose
runs are not due yet, or a week nobody was owed. Unknown is never "fine": a
registry or a schedule it cannot read fails.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, NamedTuple

TUESDAY = "tuesday"
SATURDAY = "saturday"
MARKER_PROVIDER = "marker"
# The hour (UTC) the Tuesday run is due on its send Tuesday. A purchase after
# it was never owed that Tuesday's report.
TUESDAY_SEND_HOUR = 12


class WatchdogError(RuntimeError):
    """The question cannot be answered; the message says why."""


# --------------------------------------------------------------------- #
# shared by every scheduled runner
# --------------------------------------------------------------------- #

def not_configured(registry: Path | None = None) -> bool:
    """True while nothing is set up yet: no registry file has ever been written
    and there is no Stripe key to write one from.

    One definition of "before launch", read the same way by the Tuesday run,
    the Saturday check, the free report and this watchdog. Before it existed,
    the Tuesday and Saturday crons failed on every run for want of a file that
    cannot exist until somebody pays, and filed 16 "failed" issues about a
    checkout that was simply not open yet — the alarm fatigue that teaches you
    to ignore the one that matters. Deliberately narrow: a registry file that
    EXISTS but cannot be read is never "not configured", and neither is a
    missing file once a Stripe key is set (the intake writes the registry on
    every run, so its absence then is a lost cache, not a quiet week).
    """
    from run.rosters import DEFAULT_ROSTERS
    path = Path(registry) if registry is not None else DEFAULT_ROSTERS
    if path.exists() or path.is_symlink():
        return False
    return not os.environ.get("STRIPE_API_KEY", "").strip()


NOT_CONFIGURED_NOTE = ("not set up yet: there is no roster registry and "
                       "STRIPE_API_KEY is unset, so nobody can have paid. This "
                       "is the expected state until checkout opens.")


def run_key(kind: str, season: str, week: int) -> str:
    """The marker a run leaves in the send log once it got as far as sending."""
    return f"run-{kind}-{season}-w{int(week):02d}"


def day_key(day: date) -> str:
    """The marker that says today's once-a-day steps have been claimed."""
    return f"run-daily-{day:%Y-%m-%d}"


def _mark(key: str, summary: str, sent_log: Path | None) -> bool:
    """Write ``key`` to the send log unless it is already there. The path is
    resolved at call time from ``run.delivery.SENT_LOG``, never baked into a
    signature, so a test or a proving run that redirects the send log
    redirects this too."""
    import run.delivery as delivery
    path = Path(sent_log) if sent_log is not None else Path(delivery.SENT_LOG)
    if key in delivery.load_sent(path):
        return False
    # A marker's message_id is what the run did ("sent 12, send failed 0, …"):
    # the line a human reads in the log when the week is questioned.
    delivery.record_sent(key, MARKER_PROVIDER, summary, path)
    return True


def mark_run(kind: str, season: str, week: int,
             sent_log: Path | None = None, summary: str = "") -> bool:
    """Record that this week's ``kind`` run happened — written at the end of
    any run that got as far as sending, failures included, because the
    question this answers is "did it run", and a run that failed has already
    filed its own issue. ``summary`` carries the counts. Idempotent: the
    Tuesday retry finding everything already sent must not grow the log.
    Returns whether a line was written."""
    return _mark(run_key(kind, season, week), summary, sent_log)


def claim_day(day: date, sent_log: Path | None = None) -> bool:
    """Claim ``day``'s once-a-day steps (the end-of-season billing stop, this
    watchdog). True when they are due — nothing claimed the day yet, and now
    this run has — False when an earlier run already did.

    daily.yml fires the 14:00 run twice by design (the Worker's dispatch and
    GitHub's own cron, which can arrive hours apart), and both used to pass
    the once-a-day gate: two "a scheduled run did not happen" comments a day
    and two walks of every Stripe subscription (launch review OPS-7). The two
    runs share a concurrency group and the second checks out the send log the
    first one pushed, so a marker there is what the second one sees."""
    return _mark(day_key(day), "", sent_log)


def tuesday_finished(keys: set[str], season: str, week: int) -> bool:
    return run_key(TUESDAY, season, week) in keys


# --------------------------------------------------------------------- #
# the week's calendar, and what should be in the log by now
# --------------------------------------------------------------------- #

class WeekCalendar(NamedTuple):
    tuesday: date               # the send Tuesday (NFL time)
    saturday: date              # the final check's Saturday
    first_kickoff: datetime     # UTC


def week_calendar(cache_dir: Path, season: str, week: int) -> WeekCalendar:
    """When a week's runs are due, as NFL-time dates, and when it starts.

    The send Tuesday is the Tuesday on or before the week's first kickoff — read
    off the schedule, never assumed, because the first game is not always a
    Thursday (a Wednesday opener, a Christmas Wednesday, a Friday in Brazil)."""
    from zoneinfo import ZoneInfo

    from run.saturday import NFL_TIME, SaturdayError, kickoffs
    try:
        starts = kickoffs(cache_dir, season, week)
    except SaturdayError as exc:
        raise WatchdogError(str(exc)) from exc
    if not starts:
        raise WatchdogError(f"the schedule has no {season} week {week} games")
    kickoff = min(starts.values())
    first = kickoff.astimezone(ZoneInfo(NFL_TIME)).date()
    tuesday = first - timedelta(days=(first.weekday() - 1) % 7)
    return WeekCalendar(tuesday, tuesday + timedelta(days=4), kickoff)


def tuesday_due_at(tuesday: date) -> datetime:
    """When the send Tuesday's run is due: a purchase after this was never
    owed that week's Tuesday report (it gets the first email intake sends)."""
    return datetime.combine(tuesday, time(TUESDAY_SEND_HOUR), tzinfo=timezone.utc)


def owed(purchases: Iterable[datetime | None], cutoff: datetime) -> bool:
    """Was anybody owed a run due at ``cutoff``? Pure. A purchase time that is
    unknown (None) counts as owed: an alarm is the safe direction."""
    return any(bought is None or bought < cutoff for bought in purchases)


def purchase_times(subscribers, signups) -> list[datetime | None]:
    """When each registry subscriber bought, from the signup log, or None
    where it cannot be told. Pure.

    Matched on the subscription slug — the digest of the ref it was bought
    with, which a roster update keeps as ``origin`` — and the EARLIEST purchase
    of it counts (they have been owed reports since then). A League Pass seat
    never transacts, and cannot be older than the pass that covers it, so it
    takes its payer's earliest purchase."""
    by_slug: dict[str, datetime] = {}
    by_email: dict[str, datetime] = {}
    for signup in signups:
        stamp = str(getattr(signup, "seen_at", "") or "")
        if not stamp.isdigit():
            continue
        bought = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        for table, key in ((by_slug, signup.slug), (by_email, signup.email.lower())):
            if key not in table or bought < table[key]:
                table[key] = bought
    times: list[datetime | None] = []
    for subscriber in subscribers:
        if subscriber.covered_by:
            times.append(by_email.get(subscriber.covered_by.lower()))
        else:
            times.append(by_slug.get(subscriber.slug))
    return times


def missing_runs(keys: set[str], season: str, week: int, today: date,
                 tuesday: date, saturday: date, kicked_off: bool = False, *,
                 owed_tuesday: bool = True, owed_saturday: bool = True) -> list[str]:
    """Which of this week's runs are due, were owed to somebody, and left no
    marker. Pure.

    "Due" is the day AFTER: the Tuesday run has a same-day retry at 16:00 UTC,
    and the Saturday check may legitimately run into the afternoon, so the
    question is only asked once the whole day is over.

    Only the marker answers it — never a report key in the log, which a new
    buyer's first email shares with the Tuesday send (see the module doc).

    The advice depends on ``kicked_off``. Before the week's first game a
    by-hand run is the fix. After it, the Tuesday run does not check the clock,
    so re-running it would publish calls on a game already played — onto the
    public record, which exists to make that impossible — and the alarm says
    so instead of recommending it."""
    missing: list[str] = []
    if today > tuesday and owed_tuesday:
        if not tuesday_finished(keys, season, week):
            fix = ("This week's first game has kicked off, so do NOT re-run it "
                   "now: a report built after kickoff publishes calls on a game "
                   "already played. Subscribers missed this week; find out why "
                   "before next Tuesday."
                   if kicked_off else
                   "Run the weekly-report workflow by hand before the first "
                   "kickoff: every send is keyed, so nobody already mailed is "
                   "mailed twice.")
            missing.append(
                f"Tuesday's reports for {season} week {week} (due "
                f"{tuesday:%a %b %d}): no Tuesday run for that week got as far "
                f"as sending. {fix}")
    if today > saturday and owed_saturday:
        if run_key(SATURDAY, season, week) not in keys:
            missing.append(
                f"The Saturday final check for {season} week {week} (due "
                f"{saturday:%a %b %d}) never finished. Its silence is not "
                f"'no changes': run the saturday-final-check workflow by hand "
                f"if games are still to play.")
    return missing


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def _claim_today(args, today: date) -> int:
    """``--claim-day``: print ``due=true`` or ``due=false`` for daily.yml's
    $GITHUB_OUTPUT, and nothing else on stdout. The workflow runs the
    once-a-day steps unless this says ``false`` — so a claim that crashes
    leaves them running (the duty) rather than skipped (the nicety)."""
    if not_configured(args.registry):
        # Before launch both steps are no-ops, and a marker a day would turn
        # the committed send log into a calendar of days nothing happened.
        print("due=true")
        print("Once-a-day steps: not set up yet, so nothing is claimed.",
              file=sys.stderr)
        return 0
    try:
        due = claim_day(today)
    except OSError as exc:
        print("due=true")
        print(f"Once-a-day steps: could not claim {today} ({exc}); running "
              f"them anyway.", file=sys.stderr)
        return 0
    print(f"due={'true' if due else 'false'}")
    print(f"Once-a-day steps: {'claimed for' if due else 'already ran on'} "
          f"{today:%Y-%m-%d}.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="pretend it is this UTC time (ISO)")
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--claim-day", action="store_true",
                        help="claim today's once-a-day steps; prints due=true|false")
    args = parser.parse_args(argv)

    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(timezone.utc).date()

    if args.claim_day:
        return _claim_today(args, today)

    if not_configured(args.registry):
        print(f"Watchdog: {NOT_CONFIGURED_NOTE}")
        return 0
    from run.rosters import RosterRegistryError, load_rosters
    try:
        subscribers = load_rosters(args.registry)
    except (RosterRegistryError, OSError) as exc:
        print(f"Watchdog: cannot tell whether anyone was owed a report — the "
              f"registry is unreadable ({exc}).", file=sys.stderr)
        return 1
    if not subscribers:
        print("Watchdog: the registry is empty, so no run owed anybody anything.")
        return 0

    from ingest.nflverse import NflverseError
    from run.delivery import load_sent
    from run.solo import (CACHE_DIR, SoloError, current_season, current_week,
                          season_over)
    cache = args.cache or CACHE_DIR
    try:
        season = current_season(cache, today=today)
        if season_over(cache, season, today):
            print(f"Watchdog: the {season} season is over; no runs are due.")
            return 0
        week = current_week(cache, season, today=today)
        tuesday, saturday, first_kickoff = week_calendar(cache, season, week)
    except (SoloError, NflverseError, WatchdogError, OSError) as exc:
        print(f"Watchdog: cannot read the schedule, so cannot tell whether "
              f"this week's runs happened ({exc}).", file=sys.stderr)
        return 1

    # Who was owed what. The signup log sits beside the registry; a missing
    # or unreadable one leaves every purchase time unknown, i.e. owed.
    from run.intake import SIGNUP_LOG_NAME, load_log
    from run.rosters import DEFAULT_ROSTERS
    log = Path(args.registry or DEFAULT_ROSTERS).parent / SIGNUP_LOG_NAME
    try:
        bought = purchase_times(subscribers, load_log(log))
    except (OSError, ValueError, TypeError):
        bought = [None] * len(subscribers)
    owed_tuesday = owed(bought, tuesday_due_at(tuesday))
    owed_saturday = owed(bought, first_kickoff)

    missing = missing_runs(load_sent(), season, week, today, tuesday, saturday,
                           kicked_off=now >= first_kickoff,
                           owed_tuesday=owed_tuesday, owed_saturday=owed_saturday)
    print(f"Watchdog — {season} week {week} · as of {now:%a %Y-%m-%d %H:%M} UTC "
          f"(send Tuesday {tuesday:%b %d}, final check {saturday:%b %d})")
    if not missing:
        due = [(name, was_owed) for name, day, was_owed in (
                   ("Tuesday's reports", tuesday, owed_tuesday),
                   ("the Saturday check", saturday, owed_saturday))
               if today > day]
        ran = [name for name, was_owed in due if was_owed]
        unowed = [name for name, was_owed in due if not was_owed]
        if ran:
            print(f"  everything due has run: {', '.join(ran)}.")
        elif not unowed:
            print("  everything due has run (nothing due yet this week).")
        for name in unowed:
            print(f"  {name}: nobody was owed it — every subscriber bought "
                  f"after it was due.")
        return 0
    for line in missing:
        print(f"  MISSING: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
