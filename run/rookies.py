"""The rookie report's send (`python -m run.rookies`): once a year, after the
draft class is in the data, to the addresses that pressed the button in their
season review (``hold-log.jsonl``), and nobody else: the off-season has no plan
behind it. Sends nothing outside its window, so the hourly cron can carry it.
Nothing bills, and nothing is recorded.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping



EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # run/rosters.py's rule (D14)
# Requests read from the Worker per run, once members have theirs. The day's
# allowance for optional mail (run/intake.py DAY_HEADROOM) binds as well.
MAX_ASKS_PER_RUN = 50
ASK_KINDS = ("rookie_ask",)


def is_due(today: date) -> bool:
    """May to August: past the draft, before the season's first report."""
    return 5 <= today.month <= 8


def rookie_key(year: int, email: str) -> str:
    from run.digest import address
    from run.trials import canonical_email
    return f"rookies-{year}-{address(canonical_email(email), 10)}"


def asked_for(rows: Iterable[Mapping], year: int) -> list[str]:
    """The addresses that asked on the page for THIS year's report, oldest first.
    The page promises one email, so a request counts for one class: from the
    day last year's sending closed to the day this year's does. A row lives
    about 13 months, and without this window it could reach a second one."""
    opened, closed = f"{year - 1}-09-01", f"{year}-09-01"
    out: list[str] = []
    for row in sorted(rows, key=lambda r: str(r.get("received_at") or "")):
        email = str(row.get("email") or "").strip().lower()
        if EMAIL_RE.match(email) and opened <= str(row.get("received_at") or "") < closed:
            out.append(email)
    return out


def merged(held: Iterable[str], asked: Iterable[str]) -> list[str]:
    """Members first, one entry per mailbox (Gmail dots and +tags fold)."""
    from run.trials import canonical_email
    seen: set[str] = set()
    out: list[str] = []
    for email in [*held, *asked]:
        box = canonical_email(email)
        if box not in seen:
            seen.add(box)
            out.append(email)
    return out




def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    today = datetime.now(timezone.utc).date()
    year = today.year
    if not is_due(today):
        print("Rookie report: not the time of year.")
        return 0
    from engine.rookies import MIN_PICKS, load_players, near_your_players, picks_in
    from ingest.nflverse import fetch
    from render.rookies import PAGE, load_report, rookie_email
    from render.sender import sender_line
    from run.delivery import DRY_PROVIDER, build_provider, load_sent, send_all
    from run.digest import DigestError, secret as log_secret
    from run.rosters import DEFAULT_ROSTERS, RosterRegistryError, load_rosters
    from run.season_review import HOLD_LOG_NAME, load_holds
    from run.solo import CACHE_DIR
    path = Path(args.registry or DEFAULT_ROSTERS)
    held = sorted({e.email for e in load_holds(path.parent / HOLD_LOG_NAME)
                   if e.season == str(year - 1)})
    asked: list[str] = []
    endpoint = os.environ.get("FORM_ENDPOINT", "")
    read_failed = False
    if endpoint:
        from run.intake import IntakeError, fetch_seats
        try:
            asked = asked_for(fetch_seats(endpoint, os.environ.get("FORM_API_KEY"),
                                          kinds=ASK_KINDS), year)
        except IntakeError as exc:
            # Members still get theirs; the run goes red so this is seen.
            print(f"Rookie report: could not read the form backend ({exc}).", file=sys.stderr)
            read_failed = True
    if not held and not asked:
        print("Rookie report: nobody asked for it.")
        return 1 if read_failed else 0
    try:
        log_secret()
    except DigestError as exc:
        print(f"Rookie report: {exc}", file=sys.stderr)
        return 1
    sent = load_sent()
    todo = [email for email in merged(held, asked) if rookie_key(year, email) not in sent]
    if not todo:
        print("Rookie report: everyone who asked has it.")
        return 1 if read_failed else 0
    players = load_players(fetch("players", "players.csv", CACHE_DIR, live=True))
    if picks_in(players, year) < MIN_PICKS:
        print(f"Rookie report: the {year} class isn't in the data yet "
              f"({picks_in(players, year)} picks).")
        return 0
    try:
        subscribers = load_rosters(path)
    except RosterRegistryError as exc:
        print(f"Rookie report: {exc}", file=sys.stderr)
        return 1
    report = load_report(CACHE_DIR, year, live=True)
    now_on = {p.get("gsis_id"): p for p in players}

    def roster_of(email: str) -> list[dict]:
        rows = []
        for team in (s for s in subscribers if s.email.lower() == email):
            for pid in team.player_ids:
                player = now_on.get(pid)
                if player:
                    rows.append({"player_id": pid, "name": player.get("display_name"),
                                 "position": player.get("position"),
                                 "team": player.get("latest_team")})
        return rows

    site = os.environ.get("SITE_URL", "").rstrip("/")
    page_url = f"{site}/{PAGE}" if site.startswith("https://") else None
    join_url = f"{site}/join/" if site.startswith("https://") else None
    # Members first, always. Strangers' addresses wait for the allowance.
    from run.delivery import sent_entries
    from run.intake import day_headroom, sent_on
    members = [email for email in todo if email in held]
    others = [email for email in todo if email not in held]
    room = max(0, min(MAX_ASKS_PER_RUN,
                      day_headroom() - sent_on(sent_entries(), datetime.now(timezone.utc))
                      - len(members)))
    if len(others) > room:
        print(f"Rookie report: {len(others) - room} request(s) wait for a later run.")
    messages = [rookie_email(report, near_your_players(report["rookies"], roster_of(email)),
                             email, rookie_key(year, email), page_url, join_url)
                for email in [*members, *others[:room]]]
    if args.dry_run:
        print(f"Rookie report: {len(messages)} would be sent (dry run).")
        return 0
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"Rookie report: {len(messages)} waiting — EMAIL_PROVIDER is not set.")
        return 0
    if not sender_line():
        print("ROOKIE REPORT NOT SENT: SENDER_POSTAL_ADDRESS is not set.", file=sys.stderr)
        return 1
    sends = send_all(messages, provider=provider)
    failures = [r for r in sends if not r.ok]
    print(f"Rookie report via {provider.name}: "
          f"{sum(r.ok and not r.skipped for r in sends)} sent, {len(failures)} failed")
    return 1 if failures or read_failed else 0


if __name__ == "__main__":
    sys.exit(main())
