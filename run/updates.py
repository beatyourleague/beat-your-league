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
from datetime import datetime, timezone
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

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.email.lower(), self.replaces, self.ref)


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
