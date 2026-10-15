"""The dead-man's switch: did this week's scheduled runs actually happen?

Usage:
    python -m run.watchdog [--now 2026-10-14T14:00:00+00:00] [--registry PATH]

A run that never starts fails nothing, so it files nothing. GitHub's scheduler
started the Tuesday crons 5-7 hours late on Oct 6 and Oct 13 2026 and dropped
most of the hourly runs; a Tuesday it dropped outright would have been found
when a subscriber wrote in to ask where their report was. The Saturday final
check is quieter still: it mails only when a lineup has to change, so a check
that never ran looks exactly like a week with no news.

So the once-a-day run (daily.yml, 14:00 UTC) asks two questions about the
current week and goes red when either answer is no:

- **Tuesday**, from the Wednesday after the week's send Tuesday: is a Tuesday
  report for this week in the send log, or the marker the Tuesday run leaves
  when it finishes clean? (The marker is what covers a week whose Tuesday had
  nobody to mail yet, when the first subscriber joined after kickoff.)
- **Saturday**, from the Sunday after: the final check's marker, or a final
  check it sent.

The markers live in the send log because it is the one record every sending
cron already commits, under ``merge=union`` (``.gitattributes``), so a push race
concatenates lines rather than losing them. They are keyed
``run-<kind>-<season>-wNN``, a shape no message key has, so nothing that reads
the log for sends can mistake one for a send. A dry run writes none — the same
rule as for a send, and for the same reason: a preview must leave no record
claiming something happened.

Quiet, exit 0: nothing set up yet (no registry file and no Stripe key — the
state before checkout opens), an empty registry, the offseason, or a week whose
runs are not due yet. Unknown is never "fine": a registry or a schedule it
cannot read fails.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

TUESDAY = "tuesday"
SATURDAY = "saturday"
MARKER_PROVIDER = "marker"


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
    """The marker a run leaves in the send log when it finished the week clean."""
    return f"run-{kind}-{season}-w{int(week):02d}"


def mark_run(kind: str, season: str, week: int,
             sent_log: Path | None = None) -> bool:
    """Record that this week's ``kind`` run finished. Idempotent: the Tuesday
    retry finding everything already sent must not grow the log. Returns
    whether a line was written.

    The path is resolved at call time from ``run.delivery.SENT_LOG``, never
    baked into a signature, so a test or a proving run that redirects the send
    log redirects this too."""
    import run.delivery as delivery
    path = Path(sent_log) if sent_log is not None else Path(delivery.SENT_LOG)
    key = run_key(kind, season, week)
    if key in delivery.load_sent(path):
        return False
    delivery.record_sent(key, MARKER_PROVIDER, "", path)
    return True


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


def missing_runs(keys: set[str], season: str, week: int, today: date,
                 tuesday: date, saturday: date, kicked_off: bool = False) -> list[str]:
    """Which of this week's runs are due and left no trace. Pure.

    "Due" is the day AFTER: the Tuesday run has a same-day retry at 16:00 UTC,
    and the Saturday check may legitimately run into the afternoon, so the
    question is only asked once the whole day is over.

    The advice depends on ``kicked_off``. Before the week's first game a
    by-hand run is the fix. After it, the Tuesday run does not check the clock,
    so re-running it would publish calls on a game already played — onto the
    public record, which exists to make that impossible — and the alarm says
    so instead of recommending it."""
    missing: list[str] = []
    tag = f"{re.escape(str(season))}-w{int(week):02d}"
    if today > tuesday:
        report = re.compile(rf"^{tag}-[0-9a-f]+$")
        if not (tuesday_finished(keys, season, week)
                or any(report.match(k) for k in keys)):
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
                f"{tuesday:%a %b %d}) are not in the send log, and no Tuesday "
                f"run for that week finished. {fix}")
    if today > saturday:
        final = re.compile(rf"^{tag}-final-[0-9a-f]+$")
        if not (run_key(SATURDAY, season, week) in keys
                or any(final.match(k) for k in keys)):
            missing.append(
                f"The Saturday final check for {season} week {week} (due "
                f"{saturday:%a %b %d}) never finished. Its silence is not "
                f"'no changes': run the saturday-final-check workflow by hand "
                f"if games are still to play.")
    return missing


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="pretend it is this UTC time (ISO)")
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=None)
    args = parser.parse_args(argv)

    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(timezone.utc).date()

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

    missing = missing_runs(load_sent(), season, week, today, tuesday, saturday,
                           kicked_off=now >= first_kickoff)
    print(f"Watchdog — {season} week {week} · as of {now:%a %Y-%m-%d %H:%M} UTC "
          f"(send Tuesday {tuesday:%b %d}, final check {saturday:%b %d})")
    if not missing:
        due = [name for name, day in (("Tuesday's reports", tuesday),
                                      ("the Saturday check", saturday))
               if today > day]
        print("  everything due has run" + (f": {', '.join(due)}." if due
                                            else " (nothing due yet this week)."))
        return 0
    for line in missing:
        print(f"  MISSING: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
