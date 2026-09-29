"""Saturday, the final check: Friday's injury report, applied to Tuesday's lineup.

Usage:
    python -m run.saturday [--week N] [--allow-dry] [--now 2026-10-03T16:00Z]

The Tuesday report is built on last week's injury report because this week's
does not exist yet on a Tuesday (``run/solo._availability``). By Saturday it
does: every team playing Sunday filed its final report on Friday. This run
reads it, holds it against the lineup each subscriber was actually sent, and
mails the ones whose lineup has to change — and nobody else (RULE F3 in
``engine/final_check.py``: an email every Saturday that says "no changes" is an
email people learn to skip).

What it deliberately does not do:
- **Publish a number.** No probability is computed. The swaps follow the order
  Tuesday's projections already printed, so nothing enters the ledger and there
  is nothing new to grade.
- **Rebuild the report.** It reads the plan ``run/tuesday.py`` stored when the
  report went out. Rebuilding would compare today's model — after a mid-week
  stat correction, say — against a lineup nobody was sent, and could tell a
  subscriber to "start" the player Tuesday already started.
- **Guess.** No plan stored for a subscriber (they joined after Tuesday) means
  no final check for them this week, said in the log. And a week whose injury
  report has not been published refuses outright: an empty report reads as
  "nobody is hurt", which is the one reading principle 1 forbids.

Plans live under ``data/plans/`` — gitignored (they are private rosters), and
cached across CI runs under their own key so the hourly intake cron can never
save a registry snapshot over them.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.final_check import Now, final_check, worth_sending
from render.final_check import render_final_check, subject_for_check, text_for_check
from render.report import cancel_destination
from run.delivery import (DRY_OUTBOX, DRY_PROVIDER, DeliveryError, Message,
                          build_provider, send_all)
from run.rosters import RosterRegistryError, load_rosters
from run.solo import CACHE_DIR, current_season, current_week
from run.subscriptions import DEFAULT_EXPORT

REPO_ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = REPO_ROOT / "data" / "plans"

# players.csv roster statuses that mean he cannot play this week, whatever the
# injury report says: a player moved to injured reserve on Thursday simply
# stops appearing on it.
ROSTER_OUT = {
    "RES": "on injured reserve", "RSR": "on injured reserve",
    "PUP": "on the PUP list", "RSN": "on the non-football injury list",
    "SUS": "suspended", "EXE": "on the exempt list",
    "CUT": "released", "RLS": "released",
}
# Below this share of still-to-play teams with ANY row in the week's report,
# the report is not in yet. Measured on 2024: every team that played filed
# every week but one (week 1, 31 of 32), so a real report clears this easily.
REPORT_COVERAGE_FLOOR = 0.75
NFL_TIME = "America/New_York"


class SaturdayError(RuntimeError):
    """The check cannot be run honestly; the message says why."""


# --------------------------------------------------------------------- #
# the plan — written Tuesday, read Saturday
# --------------------------------------------------------------------- #

def plan_path(plans_dir: Path, season: str, week: int, slug: str) -> Path:
    return Path(plans_dir) / str(season) / f"w{int(week):02d}-{slug}.json"


def build_plan(report: Mapping[str, Any], projections: Mapping[str, float],
               prior_form: Mapping[str, float], statuses: Mapping[str, str],
               slug: str) -> dict[str, Any]:
    """The lineup exactly as sent, and what Tuesday knew about every player.

    Built from the REPORT, not recomputed, so Saturday compares against what
    the subscriber actually read."""
    meta = report["meta"]
    players: dict[str, dict[str, Any]] = {}
    rows = list(report.get("lineup") or []) + list(report.get("bench") or [])
    for row in rows:
        pid = row.get("player_id")
        if not pid:
            continue
        printed = row.get("projected")
        players[pid] = {
            "name": row.get("player_name") or row.get("name") or pid,
            "position": row.get("position"),
            # The number the report printed wins; the model's own figure only
            # stands in for a player the report showed none for.
            "projected": printed if printed is not None else projections.get(pid),
            "last_season": (round(prior_form[pid], 1) if pid in prior_form
                            else None),
            "tuesday": statuses.get(pid),
        }
    return {
        "season": str(meta["season"]),
        "week": int(meta["week"]),
        "slug": slug,
        "slots": [{"slot": row["slot"], "player_id": row.get("player_id")}
                  for row in report.get("lineup") or []],
        "players": players,
    }


def write_plan(plans_dir: Path, plan: Mapping[str, Any]) -> Path:
    path = plan_path(plans_dir, plan["season"], plan["week"], plan["slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def load_plan(plans_dir: Path, season: str, week: int,
              slug: str) -> dict[str, Any] | None:
    path = plan_path(plans_dir, season, week, slug)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fold_roster_change(plan: Mapping[str, Any], roster: Sequence[str],
                       projections: Mapping[str, float],
                       prior_form: Mapping[str, float], players) -> dict[str, Any]:
    """The plan, with a roster the subscriber changed since Tuesday folded in.

    A self-serve update (run/updates.py) lands in the registry mid-week, most
    often right after waivers. Saturday is the first chance to act on it: a
    dropped starter's slot is filled, and a pickup can take a slot the same
    way a player back from injury can. Tuesday's own numbers stay as printed;
    only the new players need the model's figure (``projections``, computed
    for the week on the same data Tuesday used)."""
    folded = {pid: dict(info) for pid, info in plan["players"].items()}
    current = set(roster)
    for pid, info in folded.items():
        if pid not in current:
            info["dropped"] = True
    for pid in roster:
        if pid in folded:
            continue
        folded[pid] = {
            "name": players.name(pid), "position": players.position(pid),
            "projected": projections.get(pid),
            "last_season": (round(prior_form[pid], 1) if pid in prior_form
                            else None),
            "tuesday": None, "added": True,
        }
    return {**plan, "players": folded}


# --------------------------------------------------------------------- #
# what is known now
# --------------------------------------------------------------------- #

def _fetch(asset: str, name: str, cache_dir: Path) -> Path:
    from ingest.nflverse import NflverseError, fetch
    try:
        return fetch(asset, name, cache_dir, live=True)
    except NflverseError as exc:
        raise SaturdayError(f"could not load {name}: {exc}") from exc


def kickoffs(cache_dir: Path, season: str, week: int) -> dict[str, datetime]:
    """team -> kickoff (UTC) for this week's REG games. A team missing is on bye."""
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo(NFL_TIME)
    out: dict[str, datetime] = {}
    path = _fetch("schedules", "games.csv", cache_dir)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season") or "") != str(season):
                continue
            if (row.get("game_type") or "REG").upper() != "REG":
                continue
            try:
                if int(row.get("week") or 0) != int(week):
                    continue
                day = (row.get("gameday") or "").strip()
                clock = (row.get("gametime") or "").strip() or "13:00"
                local = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            start = local.replace(tzinfo=eastern).astimezone(timezone.utc)
            for team in (row.get("home_team"), row.get("away_team")):
                if team:
                    out[team.strip()] = start
    return out


def designations(cache_dir: Path, season: str, week: int
                 ) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """(gsis -> (designation, injury), teams that filed anything this week).

    Read straight off the archive rather than through ``ingest.injuries``,
    which folds Doubtful into Out: the backtest wants that, and a subscriber
    reading "listed doubtful" wants the real word."""
    found: dict[str, tuple[str, str]] = {}
    filed: set[str] = set()
    path = _fetch("injuries", f"injuries_{season}.csv", cache_dir)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season") or "") != str(season):
                continue
            if (row.get("game_type") or "REG").upper() != "REG":
                continue
            try:
                if int(row.get("week") or 0) != int(week):
                    continue
            except ValueError:
                continue
            team = (row.get("team") or "").strip()
            if team:
                filed.add(team)
            status = (row.get("report_status") or "").strip().lower()
            gsis = (row.get("gsis_id") or "").strip()
            if gsis and status in {"out", "doubtful", "questionable"}:
                injury = (row.get("report_primary_injury") or "").strip().lower()
                found[gsis] = (status, injury)
    return found, filed


def roster_statuses(cache_dir: Path) -> dict[str, tuple[str, str | None]]:
    """gsis -> (roster status, latest team) from the daily players release."""
    out: dict[str, tuple[str, str | None]] = {}
    path = _fetch("players", "players.csv", cache_dir)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            gsis = (row.get("gsis_id") or "").strip()
            if gsis:
                out[gsis] = ((row.get("status") or "").strip().upper(),
                             (row.get("latest_team") or "").strip() or None)
    return out


def _reason(designation: str, injury: str) -> str:
    return f"listed {designation}" + (f" ({injury})" if injury else "")


def state_for(player_id: str, *, starts: Mapping[str, datetime],
              listed: Mapping[str, tuple[str, str]], filed: set[str],
              roster: Mapping[str, tuple[str, str | None]],
              at: datetime) -> Now:
    """One player's :class:`Now`. Every unknown resolves toward NOT acting."""
    if player_id.startswith("DEF-"):
        team: str | None = player_id.split("-", 1)[1]
        status = "ACT"
    else:
        status, team = roster.get(player_id, ("", None))
    if not team:
        return Now(playing=False, final=False)
    kickoff = starts.get(team)
    if kickoff is None:
        return Now(playing=False)                 # bye: Tuesday already said so
    locked = at >= kickoff
    # RULE F2: a team's final report comes two days before its game, so on a
    # Saturday a Monday-night team has not filed it — and a team that filed
    # nothing at all this week has told us nothing.
    # Calendar days in NFL time: a Sunday-night kickoff is Monday in UTC.
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo(NFL_TIME)
    days = (kickoff.astimezone(eastern).date() - at.astimezone(eastern).date()).days
    final = team in filed and days <= 1
    if status in ROSTER_OUT:
        return Now("out", ROSTER_OUT[status], locked=locked, final=True)
    if player_id in listed:
        designation, injury = listed[player_id]
        return Now(designation, _reason(designation, injury),
                   locked=locked, final=final)
    return Now(locked=locked, final=final)


def check_report_is_in(starts: Mapping[str, datetime], filed: set[str],
                       at: datetime, week: int) -> None:
    """Refuse when the week's injury report has not been published yet."""
    pending = {team for team, kickoff in starts.items() if kickoff > at}
    if not pending:
        raise SaturdayError(f"every week-{week} game has already kicked off — "
                            "there is nothing left to change")
    share = len(pending & filed) / len(pending)
    if share < REPORT_COVERAGE_FLOOR:
        raise SaturdayError(
            f"the week-{week} injury report isn't in yet: {len(pending & filed)} "
            f"of {len(pending)} teams still to play have filed anything. With "
            f"it missing, every player would read as healthy. Nothing was sent.")


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, help="default: the current NFL week")
    parser.add_argument("--season", help="default: the current NFL season")
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--plans-dir", type=Path, default=PLANS_DIR)
    parser.add_argument("--paid-list", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--no-paid-check", action="store_true")
    parser.add_argument("--email-provider", default=None)
    parser.add_argument("--allow-dry", action="store_true",
                        help="preview the emails without sending")
    parser.add_argument("--resend", action="store_true")
    parser.add_argument("--now", help="pretend it is this UTC time (ISO), for previews")
    args = parser.parse_args(argv)

    at = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
          if args.now else datetime.now(timezone.utc))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)

    try:
        subscribers = load_rosters(args.registry)
    except RosterRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not subscribers:
        print("roster registry is empty — nothing to do")
        return 0

    from run.tuesday import paid_subscribers
    subscribers = paid_subscribers(subscribers, args.paid_list, args.no_paid_check)
    if subscribers is None:
        return 1

    season = str(args.season or current_season(args.cache, today=at.date()))
    week = int(args.week or current_week(args.cache, season, today=at.date()))
    try:
        starts = kickoffs(args.cache, season, week)
        listed, filed = designations(args.cache, season, week)
        check_report_is_in(starts, filed, at, week)
        roster = roster_statuses(args.cache)
    except SaturdayError as exc:
        print(f"FINAL CHECK NOT RUN — {season} week {week}: {exc}", file=sys.stderr)
        return 1

    messages: list[Message] = []
    missing, quiet, unreadable = [], [], []
    week_data: list = []                      # loaded once, only if needed

    def data_for_changes():
        if not week_data:
            from run.solo import load_week_data
            week_data.append(load_week_data(args.cache, season, week))
        return week_data[0]

    for subscriber in subscribers:
        plan = load_plan(args.plans_dir, season, week, subscriber.slug)
        if plan is None:
            missing.append(subscriber.slug)
            continue
        if set(subscriber.player_ids) != set(plan["players"]):
            # The roster changed since Tuesday. Checking the old plan would
            # tell somebody to start a player they dropped, so either the
            # change is folded in or this subscriber is skipped, loudly.
            try:
                from run.solo import _prior_form, report_for
                data = data_for_changes()
                projections: dict[str, float] = {}
                report_for(subscriber.spec(), data,
                           league_size=subscriber.league_size,
                           projections_out=projections)
                plan = fold_roster_change(
                    plan, subscriber.player_ids, projections,
                    _prior_form(data.prior, subscriber.spec().rule), data.players)
            except Exception as exc:  # noqa: BLE001 — one roster, not the run
                unreadable.append(f"{subscriber.slug} ({exc})")
                continue
        now = {pid: state_for(pid, starts=starts, listed=listed, filed=filed,
                              roster=roster, at=at)
               for pid in plan["players"]}
        changes = final_check(plan, now)
        if not worth_sending(changes):
            quiet.append(subscriber.slug)
            continue
        messages.append(Message(
            to=subscriber.email,
            subject=subject_for_check(week, changes),
            html=render_final_check(plan, changes, at),
            text=text_for_check(plan, changes, at),
            # Its own key, distinct from Tuesday's, and once per week.
            key=f"{season}-w{week:02d}-final-{subscriber.slug}",
            unsubscribe=cancel_destination()[0] or None))

    line = "=" * 62
    print(f"\n{line}\nFINAL CHECK — {season} week {week} · as of "
          f"{at:%a %Y-%m-%d %H:%M} UTC\n{line}")
    print(f"Subscribers: {len(subscribers)}; {len(messages)} need a change, "
          f"{len(quiet)} unchanged, {len(missing)} with no Tuesday plan")
    if missing:
        print("  no plan (joined after Tuesday, or Tuesday did not send): "
              + ", ".join(missing))
    for note in unreadable:
        print(f"  ROSTER CHANGED, NOT CHECKED: {note}", file=sys.stderr)
    if subscribers and len(missing) == len(subscribers):
        # Nobody at all having a plan is not a week in which everybody joined
        # on Wednesday: it is a lost cache or a Tuesday that never sent.
        print("NO PLANS FOUND for anybody — the plans cache is missing or "
              "Tuesday's run did not send. Nothing was checked.", file=sys.stderr)
        return 1

    if messages:
        try:
            provider = build_provider(args.email_provider)
        except DeliveryError as exc:
            print(f"Delivery not configured: {exc}", file=sys.stderr)
            return 1
        implicit_dry = (provider.name == DRY_PROVIDER and not args.email_provider
                        and not os.environ.get("EMAIL_PROVIDER"))
        if implicit_dry and not args.allow_dry:
            print(f"NOTHING WAS SENT. {len(messages)} final check(s) were built "
                  f"but EMAIL_PROVIDER is not set. Pass --allow-dry to preview.",
                  file=sys.stderr)
            return 1
        sends = send_all(messages, provider=provider, resend_anyway=args.resend)
        delivered = [s for s in sends if s.ok and not s.skipped]
        failures = [s for s in sends if not s.ok]
        print(f"Delivery via {provider.name}: {len(delivered)} sent, "
              f"{sum(1 for s in sends if s.skipped)} already sent, "
              f"{len(failures)} failed")
        for send in failures:
            print(f"    FAILED {send.message.key}: {send.detail}", file=sys.stderr)
        if provider.name == DRY_PROVIDER:
            print(f"    (dry run — drafts in {DRY_OUTBOX})")
        if failures:
            return 1
    if unreadable:
        return 1
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
