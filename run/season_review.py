"""The season review (`python -m run.season_review`): one email per address once
the season's box scores are in, in the first Wednesday run after the last game.

It reads the plans each report stored and grades them (engine/season_review.py).
Nothing is recorded and nothing bills. A plan we stopped for the season is
still entitled here (run/subscriptions SEASON_STOP_GRACE_DAYS); a plan its buyer
cancelled is not. Each email carries one button, ``hold_code``, asking for the
rookie report: consent we keep (``hold-log.jsonl``), because the off-season has
no plan behind it and nobody gets that mail unasked.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from run.updates import CONFIRM_CODE_LENGTH

HOLD_LOG_NAME = "hold-log.jsonl"
# How long after the last game a review can still go out.
WINDOW_DAYS = 21


@dataclass(frozen=True)
class HoldEntry:
    email: str
    season: str
    seen_at: str


def hold_code(email: str, season: str, secret: str) -> str:
    if not secret:
        raise ValueError("a rookie report request needs a secret")
    message = f"hold|{email.strip().lower()}|{season}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:CONFIRM_CODE_LENGTH]


def hold_url(site_url: str, code: str) -> str | None:
    site = (site_url or "").rstrip("/")
    return f"{site}/join/confirm.html?c={code}&k=hold" if site else None


def load_holds(path: Path) -> list[HoldEntry]:
    if not Path(path).is_file():
        return []
    out: list[HoldEntry] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict) and raw.get("email") and raw.get("season"):
            out.append(HoldEntry(raw["email"], str(raw["season"]), str(raw.get("seen_at", ""))))
    return out


def new_holds(rows: Iterable[Mapping], confirm_rows: Iterable[Mapping], seasons: Iterable[str],
              secret: str, log: Iterable[HoldEntry], now: datetime) -> list[HoldEntry]:
    """Presses of a code this address could only have from its own review. The
    code is recomputed for each address on file and never trusted."""
    pressed = {str(r.get("code") or "").strip().lower() for r in confirm_rows}
    if not secret or not pressed:
        return []
    held = {(entry.email, entry.season) for entry in log}
    fresh: list[HoldEntry] = []
    for email in sorted({str(r.get("email", "")).strip().lower() for r in rows}):
        for season in seasons:
            if email and (email, season) not in held and hold_code(email, season, secret) in pressed:
                held.add((email, season))
                fresh.append(HoldEntry(email, season, now.isoformat(timespec="seconds")))
    return fresh


def append_holds(entries: Iterable[HoldEntry], path: Path) -> int:
    entries = list(entries)
    if entries:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(asdict(entry), separators=(",", ":")) + "\n")
    return len(entries)


def review_key(season: str, email: str) -> str:
    from run.digest import address
    return f"review-{season}-{address(email.lower(), 10)}"


def team_label(subscriber, plans: list[dict]) -> str:
    """A name for the team's section: the one its owner gave it, or the one
    its last report carried."""
    from run.teams import DEFAULT_LABEL
    if subscriber.label != DEFAULT_LABEL:
        return subscriber.label
    named = [p.get("team") for p in sorted(plans, key=lambda p: int(p["week"])) if p.get("team")]
    return named[-1] if named else "Your team"


def is_due(end: str | None, today: date) -> bool:
    if not end:
        return False
    last = date.fromisoformat(end)
    return last < today <= last + timedelta(days=WINDOW_DAYS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season")
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--plans-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)

    from engine.season_review import review_team
    from ingest.nflverse import season_rows
    from render.season_review import review_message
    from render.sender import sender_line
    from run.delivery import DRY_PROVIDER, build_provider, load_sent, send_all
    from run.digest import DigestError, secret as log_secret
    from run.rosters import DEFAULT_ROSTERS, RosterRegistryError, load_rosters
    from run.saturday import PLANS_DIR, first_plans_dir, load_plans
    from run.solo import (CACHE_DIR, SoloError, assert_week_is_complete, current_season, last_week,
                          season_ends)
    from run.subscriptions import DEFAULT_EXPORT
    from run.tuesday import paid_subscribers
    from run.watchdog import not_configured

    if not_configured(args.registry):
        print("Season review: nothing set up yet.")
        return 0
    season = args.season or current_season(CACHE_DIR, today=now.date())
    if not args.season and not is_due(season_ends(CACHE_DIR).get(season), now.date()):
        print(f"Season review: not due for {season}.")
        return 0
    try:
        log_secret()
        weekly = season_rows(CACHE_DIR, season, live=True)
        assert_week_is_complete(CACHE_DIR, season, last_week(CACHE_DIR, season) + 1, weekly)
    except (DigestError, SoloError) as exc:
        print(f"Season review: waiting ({exc}).", file=sys.stderr)
        return 0
    path = args.registry or DEFAULT_ROSTERS
    try:
        subscribers = load_rosters(path)
    except RosterRegistryError as exc:
        print(f"Season review: {exc}", file=sys.stderr)
        return 1
    entitled = paid_subscribers(subscribers, DEFAULT_EXPORT)
    if entitled is None:
        return 1
    sent = load_sent()
    plans_dir = args.plans_dir or PLANS_DIR
    first_plans = first_plans_dir(path)
    secret = os.environ.get("UPDATE_SECRET", "")
    site = os.environ.get("SITE_URL", "")
    by_address: dict[str, list] = {}
    for subscriber in entitled:
        by_address.setdefault(subscriber.email.lower(), []).append(subscriber)
    messages = []
    for email, held in sorted(by_address.items()):
        key = review_key(season, email)
        if key in sent:
            continue
        teams = []
        for subscriber in held:
            plans = load_plans(plans_dir, season, subscriber.slug, also=first_plans)
            team = review_team(plans, weekly, subscriber.spec().rule)
            if team is not None:
                teams.append((team_label(subscriber, plans), team))
        if teams:
            url = hold_url(site, hold_code(email, season, secret)) if secret else None
            messages.append(review_message(held[0].email, season, teams, key, url))
    if not messages:
        print("Season review: nobody left to send to.")
        return 0
    if args.dry_run:
        print(f"Season review: {len(messages)} would be sent (dry run).")
        return 0
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"Season review: {len(messages)} waiting — EMAIL_PROVIDER is not set.")
        return 0
    if not sender_line():
        print("SEASON REVIEW NOT SENT: SENDER_POSTAL_ADDRESS is not set.", file=sys.stderr)
        return 1
    sends = send_all(messages, provider=provider)
    failures = [r for r in sends if not r.ok]
    print(f"Season review via {provider.name}: "
          f"{sum(r.ok and not r.skipped for r in sends)} sent, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
