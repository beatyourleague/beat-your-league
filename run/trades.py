"""The Trade Check: what a deal does to a subscriber's lineup and byes.

A subscriber pastes their roster as it would stand after a trade
(``join/?trade=1``) and gets an email comparing the two: this week's lineup and
projected total, each slot that changes, the byes ahead, and how the players
moving have scored. It runs the same report twice through the same model and
adds no number of its own.

It stops short of the two things we can't back up. It never says whether to
make the trade, and it prints no %: a rest-of-season value has never been
graded (principle 1), and we can't see the other team's roster or the league.
Nothing is recorded, and no roster changes. Making the trade is still a roster
update.

The form is public, so:

- The answer goes ONLY to the address on an entitled plan, and a request from
  anywhere else gets silence, so the page can't reveal who subscribes.
- The comparison uses the team's own scoring, size and lineup from the
  registry, never settings typed on the page.
- A trade changes part of a roster. A paste sharing under half of the team on
  file isn't a trade, and is not answered: this must not become a free report
  on a friend's team.
- Three answers per address per day (OWNER_DAILY_CAP for the owner's own
  addresses, run/owner.py: raised to test with, never removed), and optional
  mail gives way to paid mail (run/intake.py DAY_HEADROOM), so a stranger
  can't spend the day's sends.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from run.refs import RefError, decode_roster
from run.updates import CONFIRMS_PER_DAY, _parse_ts, origin_tag, slug_of

TRADE_KINDS = ("trade_check",)
MAX_PER_RUN = 20
# Hourly, so an older row is one nobody can still be waiting on.
MAX_AGE = timedelta(days=3)
MIN_SHARED = 0.5


@dataclass(frozen=True)
class TradeAsk:
    email: str
    ref: str
    ts: str
    owner: str = ""


def asks_from(rows: Iterable[Mapping], now: datetime,
              owners: frozenset[str] | None = None) -> list[TradeAsk]:
    """The rows worth answering, oldest first, within the daily allowance
    (higher, never unlimited, for the owner's own addresses: run/owner.py)."""
    from run.owner import daily_cap, owner_addresses
    owners = owner_addresses() if owners is None else owners
    out: list[TradeAsk] = []
    per_day: dict[tuple[str, str], int] = {}
    for row in sorted(rows, key=lambda r: str(r.get("received_at") or "")):
        email = str(row.get("email") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        ts = str(row.get("received_at") or "")
        when = _parse_ts(ts)
        if not email or not ref or when is None:
            continue
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        if now - when > MAX_AGE:
            continue
        day = (email, ts[:10])
        per_day[day] = per_day.get(day, 0) + 1
        if per_day[day] <= daily_cap(email, CONFIRMS_PER_DAY, owners):
            out.append(TradeAsk(email, ref, ts, str(row.get("owner") or "").strip().lower()))
    return out


def team_for(ask: TradeAsk, entitled: Sequence, secret: str):
    """Which of this address's teams the trade is for, or None. The report
    link names it; otherwise the team sharing the most players, and a tie is
    no answer, because comparing the wrong team is worse than none."""
    try:
        wanted = set(decode_roster(ask.ref).player_ids)
    except RefError:
        return None
    held = [s for s in entitled if s.email.lower() == ask.email]
    if ask.owner and secret:
        named = [s for s in held if origin_tag(s.slug, secret) == ask.owner]
        if named:
            held = named
    ranked = sorted(held, key=lambda s: -len(wanted & set(s.player_ids)))
    if not ranked:
        return None
    best = len(wanted & set(ranked[0].player_ids))
    if len(ranked) > 1 and best == len(wanted & set(ranked[1].player_ids)):
        return None
    return ranked[0] if best >= MIN_SHARED * max(len(ranked[0].player_ids), 1) else None


def trade_key(ask: TradeAsk) -> str:
    """Send-log key: one answer per request, ever, and no address in it."""
    from run.digest import address
    digest = hashlib.sha256(f"{ask.ref}|{ask.ts}".encode("utf-8")).hexdigest()[:10]
    return f"trade-{address(ask.email, 8)}-{digest}"


def _facts(report: Mapping[str, Any]) -> dict[str, dict]:
    """player id -> name, projection and recent scoring, from both halves of a
    report."""
    out: dict[str, dict] = {}
    for row in report.get("lineup") or []:
        if row.get("player_id"):
            out[row["player_id"]] = {
                "name": row.get("player_name"), "projected": row.get("projected"),
                "per_game": row.get("season_per_game"), "recent": row.get("last_three") or []}
    for row in report.get("bench") or []:
        if row.get("player_id"):
            games = list(row.get("games") or [])
            out.setdefault(row["player_id"], {
                "name": row.get("name"), "projected": row.get("projected"),
                "per_game": round(sum(games) / len(games), 1) if games else None,
                "recent": games[-3:]})
    return out


def _total(report: Mapping[str, Any]) -> float | None:
    return ((report.get("matchup") or {}).get("you") or {}).get("projected_total")


def _byes(report: Mapping[str, Any]) -> list[str]:
    return [f"Week {hit['week']}: {', '.join(hit['slots'])}"
            for hit in report.get("byes_ahead") or []]


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Two reports of one team -> what changes between them. Nothing here
    computes a projection; every figure was printed by one of the reports."""
    old, new = _facts(before), _facts(after)
    moves = []
    for was, now in zip(before.get("lineup") or [], after.get("lineup") or []):
        if was.get("player_id") != now.get("player_id"):
            moves.append({"slot": was.get("slot"),
                          "was": was.get("player_name"), "was_points": was.get("projected"),
                          "now": now.get("player_name"), "now_points": now.get("projected")})
    # The gap between the lineups, from the rows that differ: a report may hold
    # back its total (a starter on bye), and the gap doesn't depend on it.
    gaps = [(m["was_points"], m["now_points"]) for m in moves]
    known = all(None not in gap for gap in gaps)
    return {"week": (before.get("meta") or {}).get("week"),
            "total_before": _total(before), "total_after": _total(after),
            "change": round(sum(now - was for was, now in gaps), 1) if known else None,
            "moves": moves,
            "gone": [old[p] for p in old if p not in new],
            "added": [new[p] for p in new if p not in old],
            "byes_before": _byes(before), "byes_after": _byes(after)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--registry", type=Path, default=None)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)

    endpoint = os.environ.get("FORM_ENDPOINT", "")
    if not endpoint:
        print("Trade checks: FORM_ENDPOINT is not set — nothing to read.")
        return 0
    from run.digest import DigestError, secret as log_secret
    try:
        log_secret()
    except DigestError as exc:
        print(f"Trade checks: {exc}", file=sys.stderr)
        return 1
    from run.intake import IntakeError, day_headroom, fetch_seats, sent_on
    try:
        rows = fetch_seats(endpoint, os.environ.get("FORM_API_KEY"), kinds=TRADE_KINDS)
    except IntakeError as exc:
        print(f"Trade checks: could not read the form backend ({exc}).", file=sys.stderr)
        return 1
    from run.delivery import (DRY_PROVIDER, build_provider, load_sent, send_all,
                              sent_entries)
    sent = load_sent()
    asks = [ask for ask in asks_from(rows, now) if trade_key(ask) not in sent]
    if not asks:
        print("Trade checks: none pending.")
        return 0

    from run.rosters import DEFAULT_ROSTERS, RosterRegistryError, load_rosters
    from run.solo import (CACHE_DIR, SoloError, current_season, current_week,
                          load_week_data, report_for, spec_from_ref)
    from run.subscriptions import SubscriptionError, resolve_paid_list
    from run.trials import held_for_subscribers
    season = current_season(CACHE_DIR, today=now.date())
    try:
        week = current_week(CACHE_DIR, season, today=now.date())
        data = load_week_data(CACHE_DIR, season, week)
    except SoloError as exc:
        print(f"Trade checks: {len(asks)} waiting — no week to build ({exc}).")
        return 0
    if held_for_subscribers(now, sent, season, week):
        print(f"Trade checks: {len(asks)} waiting — subscribers' reports go out first.")
        return 0
    room = min(MAX_PER_RUN, day_headroom() - sent_on(sent_entries(), now))
    if room <= 0:
        print(f"Trade checks: {len(asks)} waiting — today's optional mail is spent.")
        return 0
    try:
        subscribers = load_rosters(args.registry or DEFAULT_ROSTERS)
        paid = resolve_paid_list(None)
    except (RosterRegistryError, SubscriptionError) as exc:
        print(f"Trade checks: could not tell who is entitled ({exc}).", file=sys.stderr)
        return 1
    entitled = [s for s in subscribers if paid.entitles(s) and not s.is_league_seat]

    from render.trade_mail import trade_email
    from run.delivery import Message
    from run.updates import public_update_url
    secret = os.environ.get("UPDATE_SECRET", "")
    known = {p.player_id for p in data.directory.players}
    messages = []
    for ask in asks:
        if len(messages) >= room:
            break
        team = team_for(ask, entitled, secret)
        if team is None:
            continue                         # silence: the page is public
        wanted = decode_roster(ask.ref)
        if any(pid not in known for pid in wanted.player_ids):
            continue
        try:
            current = spec_from_ref(decode_roster(team.ref))
            traded = spec_from_ref(wanted)
            # The team's own league, never what was left on the page.
            traded = replace(traded, slots=current.slots, scoring=current.scoring,
                             label=current.label)
            before = report_for(current, data, team.league_size)
            after = report_for(traded, data, team.league_size)
        except Exception as exc:  # noqa: BLE001 — one bad roster stops nobody else
            print(f"Trade checks: could not build {trade_key(ask)[-10:]}: {exc!r}",
                  file=sys.stderr)
            continue
        update_url = public_update_url(os.environ.get("SITE_URL", ""), secret, endpoint,
                                       roster=team)
        subject, html, text = trade_email(compare(before, after), team.label, update_url)
        messages.append(Message(to=ask.email, subject=subject, html=html, text=text,
                                key=trade_key(ask)))
    if not messages:
        print(f"Trade checks: {len(asks)} request(s), none to answer.")
        return 0
    if args.dry_run:
        print(f"Trade checks: {len(messages)} would be sent (dry run).")
        return 0
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"TRADE CHECKS NOT SENT: {len(messages)} waiting and EMAIL_PROVIDER is "
              f"not set.", file=sys.stderr)
        return 1
    sends = send_all(messages, provider=provider)
    failures = [r for r in sends if not r.ok]
    print(f"Trade checks via {provider.name}: "
          f"{sum(r.ok and not r.skipped for r in sends)} sent, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
