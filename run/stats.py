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
           now: datetime) -> str:
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

    print(render(form_summary(rows, now) if rows is not None else None, form_note,
                 sends, season, registry, registry_note, conv, now), end="")
    return 0 if (rows is not None or not endpoint) else 1


if __name__ == "__main__":
    sys.exit(main())
