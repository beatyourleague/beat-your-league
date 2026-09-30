"""Self-serve roster updates — the change a season forces every week.

A subscriber types a roster in late August; week-1 waivers run the
following Wednesday; by the SECOND report the file describes a team they no
longer own — recommending a dropped player, blind to the pickup — and it
compounds every week for the rest of the season. A stale-but-confident
report is worse than an honest thin one, and it lands inside the refund
window.

The mechanism reuses what the League Pass seats already proved: the picker
posts a small row to the form backend, and the intake validates it before a
single byte reaches the registry. Three rules, each bought with a failure
elsewhere in this repo:

- **The form is public, so an update must be AUTHENTICATED, not merely
  addressed.** A seat claim is honoured only when its payer bought a pass;
  an update is honoured only when it carries the subscriber's TOKEN — an
  HMAC of their address under a repo secret — which reaches them inside
  their own reports and nowhere else. Without it, anyone who knows a
  leaguemate's email could set their lineup for them.
- **An update names the row it replaces.** One customer can legitimately
  hold two rosters (two teams). ``replaces`` is the slug of the row being
  changed, so an update is never applied to the wrong team and never merges
  two subscriptions into one.
- **Order is stamped on receipt, never read from the row.** Public-form
  timestamps are attacker-supplied (the seat sweep learned this: a row dated
  9999 outranks every later one forever). An update is logged the first time
  the intake sees it, and the newest FIRST-SEEN row per target wins.

The registry row keeps its plan, its payer and its Stripe customer; only the
roster — both the encoded ref and the expanded copy, from one object — moves.
Nothing here touches the signup log, so the welcome email (keyed on the
ORIGINAL ref) is never sent twice.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from run.refs import RefError, decode_roster

UPDATE_LOG_NAME = "roster-updates.jsonl"
TOKEN_LENGTH = 20
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def update_token(email: str, secret: str) -> str:
    """The per-subscriber credential. Deterministic, so no state is kept and
    every report carries the same link; rotating the secret invalidates all."""
    if not secret:
        raise ValueError("an update token needs a secret")
    digest = hmac.new(secret.encode("utf-8"), email.strip().lower().encode("utf-8"),
                      hashlib.sha256).hexdigest()
    return digest[:TOKEN_LENGTH]


def slug_of(ref: str) -> str:
    """The same digest the registry and the send log use for a ref."""
    return hashlib.sha256(ref.encode("utf-8")).hexdigest()[:10]


def update_url(site_url: str, email: str, slug: str, secret: str) -> str | None:
    """Where a subscriber changes their roster — or None, so a report never
    carries a dead link. Gated on both the site and the secret existing.
    ``slug`` is the subscription's ORIGIN slug, which does not move when the
    roster does, so every report a subscriber ever receives carries the same
    link."""
    site = (site_url or "").rstrip("/")
    if not site or not secret:
        return None
    return f"{site}/join/?update={slug}&token={update_token(email, secret)}"


@dataclass
class RosterUpdate:
    """One validated change, as logged."""

    email: str
    replaces: str            # slug of the registry row being changed
    ref: str                 # the new roster
    seen_at: str             # first seen by the intake, ISO
    # Confirm-by-email updates only: the request's own code and the Worker's
    # timestamp for it. Two different requests for the SAME roster (A -> B -> A)
    # are two different updates; without the nonce the second collided with the
    # first in the log, was deduped away, and the roster silently stayed B.
    nonce: str = ""
    request_ts: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.email.lower(), self.replaces, self.ref, self.nonce)


def load_update_log(path: Path) -> list[RosterUpdate]:
    if not Path(path).is_file():
        return []
    out: list[RosterUpdate] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict) and raw.get("email") and raw.get("ref"):
            fields = {f: raw[f] for f in RosterUpdate.__dataclass_fields__ if f in raw}
            out.append(RosterUpdate(**fields))
    return out


def append_update_log(updates: Iterable[RosterUpdate], path: Path) -> int:
    """Append the updates not already logged; a logged update keeps its
    first-seen stamp forever, which is what makes the sweep idempotent."""
    known = {u.key for u in load_update_log(path)}
    fresh = [u for u in updates if u.key not in known]
    if not fresh:
        return 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as handle:
        for update in fresh:
            handle.write(json.dumps(asdict(update), separators=(",", ":")) + "\n")
    return len(fresh)


def validate_updates(rows: Iterable[Mapping], registry_rows: Iterable[Mapping],
                     known_ids: set[str] | None, secret: str,
                     now: str | None = None) -> tuple[list[RosterUpdate], list[str]]:
    """Turn form rows into validated updates against the rows about to be written.

    ``registry_rows`` are the rows the intake is about to write (payers and
    honoured seats): the only rosters an update may change. ``known_ids`` is
    None when the directory could not be loaded — "not checked", never
    "nothing is known".
    """
    problems: list[str] = []
    out: list[RosterUpdate] = []
    if not secret:
        rows = list(rows)
        if rows:
            problems.append(f"{len(rows)} roster update(s) arrived but UPDATE_SECRET "
                            f"is not set — none applied, because an update that "
                            f"cannot be authenticated is anyone's to forge")
        return out, problems
    targets: dict[tuple[str, str], Mapping] = {
        (str(row.get("email", "")).lower(),
         str(row.get("origin") or slug_of(str(row.get("ref", ""))))): row
        for row in registry_rows
    }
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        token = str(row.get("token") or "").strip()
        replaces = str(row.get("replaces") or "").strip()
        ref = str(row.get("ref") or "").strip()
        if not _EMAIL_RE.match(email):
            problems.append("a roster update arrived with an unusable address")
            continue
        # ASCII-only BEFORE compare_digest: it raises TypeError rather than
        # returning False when either str argument is non-ASCII, and this value
        # came straight off a public form backend with no character validation.
        # One anonymous row killed the whole intake — no registry written, no
        # welcomes sent, no watermark advanced — and repeated every run until
        # somebody deleted it by hand. The governing rule here is that one
        # person's problem must not become everybody's; an attacker's problem
        # certainly must not. Found Aug 24 2026.
        if not token.isascii() or not hmac.compare_digest(
                token, update_token(email, secret)):
            # Said without the address: the summary lands in a CI log.
            problems.append("a roster update carried a token that does not match "
                            "its address — not applied")
            continue
        if (email, replaces) not in targets:
            problems.append(f"a roster update for {_mask(email)} names a subscription "
                            f"it does not hold — not applied")
            continue
        try:
            roster = decode_roster(ref)
        except RefError as exc:
            problems.append(f"a roster update for {_mask(email)} carries an "
                            f"unreadable roster ({exc}) — not applied")
            continue
        missing = ([pid for pid in roster.player_ids if pid not in known_ids]
                   if known_ids else [])
        if missing:
            problems.append(f"a roster update for {_mask(email)} names "
                            f"{len(missing)} player id(s) the directory does not "
                            f"have — not applied")
            continue
        key = (email, replaces, ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(RosterUpdate(email=email, replaces=replaces, ref=ref, seen_at=stamp))
    return out, problems


def latest_per_target(log: Iterable[RosterUpdate]) -> dict[tuple[str, str], RosterUpdate]:
    """Newest first-seen update per (email, replaces)."""
    latest: dict[tuple[str, str], RosterUpdate] = {}
    for update in log:
        target = (update.email.lower(), update.replaces)
        held = latest.get(target)
        if held is None or update.seen_at >= held.seen_at:
            latest[target] = update
    return latest


def apply_updates(rows: list[dict], latest: Mapping[tuple[str, str], RosterUpdate],
                  ) -> tuple[list[dict], int]:
    """Replace the roster on the targeted rows. Both copies move from one
    decoded object, so the registry's agreement rule holds by construction.

    Every row is written with its ``origin`` — the slug it was first written
    under — and an update targets that slug, because that is the slug every
    report the subscriber has ever received carries. So a chain of changes
    (A -> B -> C) resolves to the newest one against a target that never
    moved."""
    out: list[dict] = []
    applied = 0
    for row in rows:
        email = str(row.get("email", "")).lower()
        origin = str(row.get("origin") or slug_of(str(row.get("ref", ""))))
        update = latest.get((email, origin))
        if update is None or update.ref == row.get("ref"):
            out.append({**row, "origin": origin})
            continue
        roster = decode_roster(update.ref)
        out.append({
            **row,
            "origin": origin,
            "ref": update.ref,
            "player_ids": list(roster.player_ids),
            "slots": list(roster.slots),
            "scoring": roster.scoring,
        })
        applied += 1
    return out, applied


def _mask(email: str) -> str:
    return re.sub(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", r"***@\1", email)


# --------------------------------------------------------------------- #
# confirm-by-email requests (Sep 29 2026)
# --------------------------------------------------------------------- #
#
# The token link above was pulled out of every report (run/tuesday.py): a
# report is written to be forwarded to the league, and a forwarded credential
# hands the most motivated adversary in the product a way to set somebody's
# lineup. This replaces it with the pattern that survives forwarding:
#
#   1. Every report links a PUBLIC page (`join/?update=1`) that grants nothing.
#   2. The page posts {kind:"update_request", email, ref}. Anyone can do that;
#      the Worker stamps it (`received_at`, its own clock — the row cannot).
#   3. The intake mails a confirmation to the ADDRESS ON THE REGISTRY ROW —
#      never to anyone else — carrying a code only that inbox receives.
#   4. The subscriber opens `join/confirm.html?c=<code>` and PRESSES A BUTTON,
#      which posts {kind:"confirm", code}. A button, not a link that confirms
#      on load: mail security scanners open every link in an inbox.
#   5. The next intake sees the confirm, and the update is logged and applied.
#
# A forwarded report therefore grants nothing, a forged request reaches only
# the real subscriber's inbox, and ignoring it changes nothing.
#
# Rules bought by the adversarial review of Sep 29 2026 (each reproduced):
# - **Every request keeps its own code.** The newest request used to overwrite
#   the pending one, so a stranger's junk request killed the code already in the
#   subscriber's inbox. The code binds (address, subscription, roster) AND the
#   request's timestamp; all live requests stay valid until one is applied.
# - **A code is single-use and expires.** Once any request for a subscription is
#   applied, that request and every OLDER one is dead; a request is dead after
#   EXPIRY_DAYS. A stale or forwarded email can never re-apply an old roster.
# - **Requests are judged against the roster AS IT NOW STANDS**, compared by
#   content (players, slots, scoring, size — not the ref string, whose plan
#   prefix differs for a monthly subscriber). A request equal to the current
#   roster changes nothing and cancels every earlier pending request: it is how
#   a subscriber says "never mind, keep what I have".
# - **One confirmation email per request, ever** (not per day: a request row
#   never expires in the Worker, so a per-day key mailed the victim of one
#   forged request every day forever). The daily cap counts requests by the
#   Worker's own date.

CONFIRM_CODE_LENGTH = 24
# Confirmation emails per address per UTC day — a stranger posting requests
# in a loop can annoy an inbox a little, never flood it. Residual, stated: a
# stranger can spend the day's allowance, delaying the real subscriber's request
# to tomorrow (their earlier codes stay valid, and nothing else is harmed).
CONFIRMS_PER_DAY = 3
EXPIRY_DAYS = 7


@dataclass(frozen=True)
class PendingRequest:
    """A validated request waiting for its confirmation."""

    email: str
    replaces: str
    ref: str
    code: str
    ts: str = ""


def confirm_code(email: str, replaces: str, ref: str, secret: str, ts: str = "") -> str:
    if not secret:
        raise ValueError("a confirmation code needs a secret")
    message = f"confirm|{email.strip().lower()}|{replaces}|{ref}|{ts}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:CONFIRM_CODE_LENGTH]


def same_roster(ref_a: str, ref_b: str) -> bool:
    """Do two refs describe the same roster? By CONTENT: a monthly subscriber
    re-submitting an identical roster builds a ref with a different plan prefix,
    which is not a change."""
    try:
        a, b = decode_roster(ref_a), decode_roster(ref_b)
    except RefError:
        return False
    return ((a.player_ids, a.slots, a.scoring, a.league_size)
            == (b.player_ids, b.slots, b.scoring, b.league_size))


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _target_for(email: str, roster, registry_rows: Iterable[Mapping]) -> str | None:
    """Which of this address's subscriptions a request changes, or None when
    that cannot be told. One subscription: that one. Several: the one in the
    same league setup whose roster overlaps the new one most — and a tie is
    refused, because changing the wrong team is worse than changing none."""
    held = [row for row in registry_rows
            if str(row.get("email", "")).lower() == email]
    if not held:
        return None
    if len(held) > 1:
        same = [row for row in held
                if list(row.get("slots") or []) == list(roster.slots)
                and row.get("scoring") == roster.scoring]
        new = set(roster.player_ids)
        ranked = sorted(same, key=lambda r: -len(new & set(r.get("player_ids") or [])))
        if not ranked or (len(ranked) > 1 and
                          len(new & set(ranked[0].get("player_ids") or []))
                          == len(new & set(ranked[1].get("player_ids") or []))):
            return None
        held = ranked[:1]
    row = held[0]
    return str(row.get("origin") or slug_of(str(row.get("ref", ""))))


def applied_request_ts(log: Iterable[RosterUpdate]) -> dict[tuple[str, str], str]:
    """Newest confirmed request already applied, per (address, subscription)."""
    out: dict[tuple[str, str], str] = {}
    for update in log:
        if update.request_ts:
            key = (update.email.lower(), update.replaces)
            out[key] = max(out.get(key, ""), update.request_ts)
    return out


def validate_requests(rows: Iterable[Mapping], registry_rows: Iterable[Mapping],
                      known_ids: set[str] | None, secret: str,
                      now: datetime | None = None,
                      applied: Mapping[tuple[str, str], str] | None = None,
                      ) -> tuple[list[PendingRequest], list[str]]:
    """Public-form requests -> requests worth a confirmation email.

    ``registry_rows`` must be the roster AS IT NOW STANDS (updates already
    applied): "nothing would change" is judged against that. Nothing here
    changes a roster. A request naming an address that holds no subscription is
    dropped in silence: the page is public, and answering it would let anybody
    learn who subscribes."""
    problems: list[str] = []
    rows = list(rows)
    if not secret:
        if rows:
            problems.append(f"{len(rows)} roster update request(s) arrived but "
                            f"UPDATE_SECRET is not set — no confirmations sent")
        return [], problems
    registry_rows = list(registry_rows)
    applied = dict(applied or {})
    now = now or datetime.now(timezone.utc)
    live: list[PendingRequest] = []
    cancelled: dict[tuple[str, str], str] = {}
    for row in sorted(rows, key=lambda r: str(r.get("received_at") or "")):
        email = str(row.get("email") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        ts = str(row.get("received_at") or "")
        when = _parse_ts(ts)
        if not _EMAIL_RE.match(email) or when is None:
            continue                       # no Worker stamp: not a request we can identify
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if now - when > timedelta(days=EXPIRY_DAYS):
            continue
        try:
            roster = decode_roster(ref)
        except RefError:
            continue
        replaces = _target_for(email, roster, registry_rows)
        if replaces is None:
            if any(str(r.get("email", "")).lower() == email for r in registry_rows):
                problems.append(f"a roster update request for {_mask(email)} matches "
                                f"more than one of their teams equally — not sent")
            continue
        if known_ids and any(pid not in known_ids for pid in roster.player_ids):
            problems.append(f"a roster update request for {_mask(email)} names a "
                            f"player the directory does not have — not sent")
            continue
        current = next((r for r in registry_rows
                        if str(r.get("email", "")).lower() == email
                        and str(r.get("origin") or slug_of(str(r.get("ref", "")))) == replaces),
                       None)
        target = (email, replaces)
        if current is not None and same_roster(str(current.get("ref", "")), ref):
            # "Keep what I have": nothing to change, and every earlier pending
            # request for this subscription is withdrawn.
            cancelled[target] = max(cancelled.get(target, ""), ts)
            continue
        live.append(PendingRequest(email, replaces, ref,
                                   confirm_code(email, replaces, ref, secret, ts), ts))
    pending = [r for r in live
               if r.ts > applied.get((r.email, r.replaces), "")
               and r.ts > cancelled.get((r.email, r.replaces), "")]
    # The daily cap, by the Worker's own date, oldest first — deterministic.
    per_day: dict[tuple[str, str], int] = {}
    capped: list[PendingRequest] = []
    for request in sorted(pending, key=lambda r: r.ts):
        bucket = (request.email, request.ts[:10])
        per_day[bucket] = per_day.get(bucket, 0) + 1
        if per_day[bucket] <= CONFIRMS_PER_DAY:
            capped.append(request)
    return capped, problems


def confirmed_updates(pending: Iterable[PendingRequest],
                      confirm_rows: Iterable[Mapping], secret: str,
                      now: str | None = None) -> list[RosterUpdate]:
    """The pending requests whose code came back through the confirm page,
    oldest first (so that, if a subscriber pressed two buttons, the NEWEST
    request is the one that stands).

    The code is recomputed, never trusted: a confirm row is only a string, and
    it counts only when it equals the code of a request that is still live."""
    if not secret:
        return []
    codes = {str(r.get("code") or "").strip().lower() for r in confirm_rows}
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [RosterUpdate(email=p.email, replaces=p.replaces, ref=p.ref, seen_at=stamp,
                         nonce=p.code, request_ts=p.ts)
            for p in sorted(pending, key=lambda r: r.ts) if p.code in codes]


def confirmation_key(request: PendingRequest) -> str:
    """Send-log key: ONE confirmation per request, ever, and no address in it."""
    who = hashlib.sha256(request.email.encode("utf-8")).hexdigest()[:8]
    return f"confirm-{who}-{hashlib.sha256(request.code.encode('utf-8')).hexdigest()[:10]}"


def confirm_url(site_url: str, code: str) -> str | None:
    site = (site_url or "").rstrip("/")
    return f"{site}/join/confirm.html?c={code}" if site else None


def public_update_url(site_url: str, secret: str, endpoint: str) -> str | None:
    """The link every report carries. It grants nothing — which is why it may
    be forwarded — and it renders only when the whole flow can work: a site to
    land on, a backend to post to, a secret to sign confirmations with."""
    site = (site_url or "").rstrip("/")
    if not site or not secret or not endpoint:
        return None
    return f"{site}/join/?update=1"
