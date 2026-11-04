"""Up to three teams on one subscription (run/plans.py TEAMS_INCLUDED).

A buyer's first team comes through checkout. Every other team comes through
``join/?add=1``, costs nothing, and is a row of its own on the registry that
names the SAME Stripe subscription. Entitlement follows the row's subscription
(run/subscriptions D2), so one cancel, one refund, one lost dispute or the
season's stop ends all of a buyer's teams together, and the billing page has
one purchase on it.

The form is public, so the rules are the roster update's:

- A request grants nothing. The intake mails the address on the subscription
  and only a button press from that inbox adds the team. A request naming an
  address with no live subscription is dropped in silence, so the page cannot
  reveal who subscribes.
- The code is recomputed, never trusted, and binds the address, the roster,
  the name and the Worker's stamp, so each request has its own.
- Order comes from the Worker's stamp, and a confirmed team goes in
  ``team-log.jsonl`` the first time it is seen. A Worker row expiring never
  moves a team.
- A team that repeats one the address already holds is not a team: one
  address, one roster, one report (LP2-D1).

A League Pass seat holder has no subscription and gets no extra teams; the
buyer of a pass does. A team's roster changes through the ordinary update
link, which is also how a buyer swaps one team for another.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from run.plans import FOOTBALL, TEAMS_INCLUDED
from run.refs import RefError, decode_roster
from run.updates import (CONFIRM_CODE_LENGTH, CONFIRMS_PER_DAY, EXPIRY_DAYS, _mask,
                         _parse_ts, origin_tag, roster_content)

TEAM_LOG_NAME = "team-log.jsonl"
DEFAULT_LABEL = "Your Team"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # run/rosters.py's rule (D14)
# A team's name lands in an email subject, so it stays short and has no line
# break or markup in it. The Worker and the page hold the same rule.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '&.\-]{0,23}$")


def clean_name(raw: object) -> str:
    """A name a buyer typed, or "" when it isn't one. Never an error: a team
    with a bad name is still a team."""
    name = " ".join(str(raw or "").split())
    return name if _NAME_RE.match(name) else ""


def team_code(email: str, ref: str, ts: str, secret: str, name: str = "") -> str:
    """The code that turns one request into a team. A different prefix from
    the update's and the seat's keeps the three apart over one confirm page."""
    if not secret:
        raise ValueError("a team confirmation code needs a secret")
    message = f"team-confirm|{email.strip().lower()}|{ref}|{ts}|{name}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:CONFIRM_CODE_LENGTH]


def team_confirm_url(site_url: str, code: str) -> str | None:
    site = (site_url or "").rstrip("/")
    return f"{site}/join/confirm.html?c={code}&k=team" if site else None


def team_origin(subscription_id: str, ts: str) -> str:
    """The slug a team is written under. Fixed for life: a roster update moves
    the ref and never this, so send keys and the update link stay put."""
    return hashlib.sha256(f"team|{subscription_id}|{ts}".encode("utf-8")).hexdigest()[:10]


@dataclass(frozen=True)
class TeamEntry:
    """One confirmed team, as logged."""

    email: str
    subscription_id: str
    ref: str
    origin: str
    seen_at: str                     # first seen by the intake, ISO
    code: str = ""
    request_ts: str = ""
    name: str = ""
    sport: str = FOOTBALL

    @property
    def key(self) -> tuple[str, str]:
        return (self.email.lower(), self.code or self.origin)


def load_team_log(path: Path) -> list[TeamEntry]:
    if not Path(path).is_file():
        return []
    out: list[TeamEntry] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(raw, dict) and raw.get("email") and raw.get("ref")
                and raw.get("subscription_id") and raw.get("origin")):
            fields = {f: raw[f] for f in TeamEntry.__dataclass_fields__ if f in raw}
            out.append(TeamEntry(**fields))
    return out


def append_team_log(entries: Iterable[TeamEntry], path: Path) -> int:
    """Append the teams not already logged. A logged team keeps its first-seen
    stamp, which is what makes the sweep idempotent."""
    known = {entry.key for entry in load_team_log(path)}
    fresh = [entry for entry in entries if entry.key not in known]
    if not fresh:
        return 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as handle:
        for entry in fresh:
            handle.write(json.dumps(asdict(entry), separators=(",", ":")) + "\n")
    return len(fresh)


def _origin_of(row: Mapping) -> str:
    from run.updates import slug_of
    return str(row.get("origin") or slug_of(str(row.get("ref", ""))))


def team_counts(rows: Iterable[Mapping]) -> dict[str, int]:
    """Subscription -> the teams it carries, from registry rows or subscribers.
    A seat names no subscription of its own, so it counts on nothing here."""
    counts: dict[str, int] = {}
    for row in rows:
        ids = (row.get("subscription_ids") if isinstance(row, Mapping)
               else getattr(row, "subscription_ids", ()))
        for subscription in ids or ():
            counts[subscription] = counts.get(subscription, 0) + 1
    return counts


def teams_held(subscriber, counts: Mapping[str, int]) -> int:
    """How many teams this row's subscription carries, this one included."""
    ids = tuple(getattr(subscriber, "subscription_ids", ()) or ())
    return max([counts.get(subscription, 0) for subscription in ids] or [1])


def add_team_url(site_url: str, secret: str, endpoint: str, subscriber=None) -> str | None:
    """The link to add a team, or None until the whole flow works (site,
    backend, secret). It grants nothing, so a forwarded report is safe: the
    change still needs the inbox on file. ``&o=`` names the subscription."""
    site = (site_url or "").rstrip("/")
    if not site or not secret or not endpoint:
        return None
    origin = getattr(subscriber, "slug", None) if subscriber is not None else None
    tag = f"&o={origin_tag(origin, secret)}" if isinstance(origin, str) and origin else ""
    return f"{site}/join/?add=1{tag}"


@dataclass(frozen=True)
class PendingTeam:
    """A validated request. ``subscription_id`` is where it would go now."""

    email: str
    subscription_id: str
    ref: str
    code: str
    ts: str
    name: str = ""


@dataclass
class TeamSweep:
    pending: list[PendingTeam] = field(default_factory=list)  # room left: mail a code
    full: list[PendingTeam] = field(default_factory=list)     # no room: say so once
    confirmed: list[TeamEntry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _pressed_at(confirm_rows: Iterable[Mapping]) -> dict[str, datetime]:
    """Code -> when its button was first pressed, by the Worker's own clock."""
    pressed: dict[str, datetime] = {}
    for row in confirm_rows:
        code = str(row.get("code") or "").strip().lower()
        at = _parse_ts(str(row.get("received_at") or ""))
        if code and at is not None:
            at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
            pressed[code] = min(at, pressed.get(code, at))
    return pressed


def _owners(email: str, rows: list[Mapping], live: set[str]) -> list[Mapping]:
    """This address's rows on a live subscription, oldest purchase first."""
    return [row for row in rows
            if str(row.get("email", "")).lower() == email
            and any(sub in live for sub in row.get("subscription_ids") or ())]


def sweep_teams(rows: Iterable[Mapping], registry_rows: Iterable[Mapping],
                known_ids: set[str] | None, secret: str, live: set[str] | None,
                log: Iterable[TeamEntry] = (), confirm_rows: Iterable[Mapping] = (),
                now: datetime | None = None,
                owners: frozenset[str] | None = None) -> TeamSweep:
    """Form rows -> what to mail and what to add.

    ``registry_rows`` must be the rosters as they now stand, logged teams
    included. ``live`` is the subscriptions active right now, or None when
    Stripe could not say: every request then waits for a run that can tell,
    because a cancelled buyer must not gain a team and a paying one must not
    lose a request."""
    sweep = TeamSweep()
    rows = list(rows)
    if not rows:
        return sweep
    if not secret:
        sweep.problems.append(f"{len(rows)} team request(s) arrived but UPDATE_SECRET "
                              f"is not set — no confirmations sent")
        return sweep
    if live is None:
        sweep.problems.append(f"{len(rows)} team request(s) wait for a run that can "
                              f"read which subscriptions are live")
        return sweep
    now = now or datetime.now(timezone.utc)
    held = list(registry_rows)
    used = {entry.code for entry in log if entry.code}
    pressed = _pressed_at(confirm_rows)
    counts = team_counts(held)
    contents = {}
    for row in held:
        ids = row.get("subscription_ids") or ()
        if ids and not any(sub in live for sub in ids):
            continue                        # a cancelled plan holds nothing now
        try:
            content = roster_content(decode_roster(str(row.get("ref", ""))))
        except RefError:
            continue
        contents.setdefault(str(row.get("email", "")).lower(), set()).add(content)
    per_day: dict[tuple[str, str], int] = {}
    # The owner's own addresses get a higher daily cap to test with, never
    # none (run/owner.py). The team limit itself is the same for everybody.
    from run.owner import daily_cap, owner_addresses
    mine = owner_addresses() if owners is None else owners
    for row in sorted(rows, key=lambda r: str(r.get("received_at") or "")):
        email = str(row.get("email") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        ts = str(row.get("received_at") or "")
        when = _parse_ts(ts)
        if not _EMAIL_RE.match(email) or when is None:
            continue
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        try:
            roster = decode_roster(ref)
        except RefError:
            continue
        owners = _owners(email, held, live)
        if not owners:
            continue                        # silence: the page is public
        name = clean_name(row.get("name"))
        code = team_code(email, ref, ts, secret, name)
        if code in used:
            continue                        # single-use: it is on the log
        limit = timedelta(days=EXPIRY_DAYS)
        if now - when > limit and not (code in pressed and pressed[code] - when <= limit):
            continue
        content = roster_content(roster)
        if content in contents.get(email, set()):
            continue                        # one address, one roster, one report
        if known_ids and any(pid not in known_ids for pid in roster.player_ids):
            sweep.problems.append(f"a team request for {_mask(email)} names a player "
                                  f"the directory does not have — not sent")
            continue
        subscriptions = _in_order(owners, str(row.get("owner") or "").strip().lower(),
                                  secret, live)
        target = next((sub for sub in subscriptions
                       if counts.get(sub, 0) < TEAMS_INCLUDED), None)
        request = PendingTeam(email, target or subscriptions[0], ref, code, ts, name)
        if code in pressed and target is not None:
            seen = now.isoformat(timespec="seconds")
            sweep.confirmed.append(TeamEntry(
                email=email, subscription_id=target, ref=ref,
                origin=team_origin(target, ts), seen_at=seen, code=code,
                request_ts=ts, name=name))
            counts[target] = counts.get(target, 0) + 1
            contents.setdefault(email, set()).add(content)
            continue
        bucket = (email, ts[:10])
        per_day[bucket] = per_day.get(bucket, 0) + 1
        if per_day[bucket] > daily_cap(email, CONFIRMS_PER_DAY, mine):
            continue
        (sweep.pending if target is not None else sweep.full).append(request)
    return sweep


def team_row_open(row: Mapping, now: datetime) -> bool:
    """Can this request still come to anything? Its button lasts EXPIRY_DAYS,
    and a press inside that may be read a run or two later."""
    when = _parse_ts(str(row.get("received_at") or ""))
    if when is None:
        return False
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return now - when <= timedelta(days=EXPIRY_DAYS + 2)


def _in_order(owners: list[Mapping], tag: str, secret: str, live: set[str]) -> list[str]:
    """The address's live subscriptions, the one the link named first."""
    ordered: list[str] = []
    named = [row for row in owners if tag and hmac.compare_digest(
        origin_tag(_origin_of(row), secret), tag.encode("ascii", "replace").decode())]
    for row in [*named, *owners]:
        for sub in row.get("subscription_ids") or ():
            if sub in live and sub not in ordered:
                ordered.append(sub)
    return ordered


def team_mail_key(kind: str, request: PendingTeam) -> str:
    """Send-log key: one email per request, ever, and no address in it."""
    from run.digest import address
    who = address(request.email, 8)
    digest = hashlib.sha256(request.code.encode("utf-8")).hexdigest()[:10]
    return f"team-{kind}-{who}-{digest}"


def add_names(rows: Iterable[Mapping], names: Mapping[tuple[str, str], str]) -> list[dict]:
    """Give each row the name its owner chose (run/updates.latest_names)."""
    out: list[dict] = []
    for row in rows:
        target = (str(row.get("email", "")).lower(), _origin_of(row))
        out.append({**row, "label": names[target]} if target in names else dict(row))
    return out
