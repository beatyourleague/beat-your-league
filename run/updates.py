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
#   2. The page posts {kind:"update_request", email, ref}. Anyone can do that.
#   3. The intake mails a confirmation to the ADDRESS ON THE REGISTRY ROW —
#      never to anyone else — carrying a code only that inbox receives.
#   4. The subscriber opens `join/confirm.html?c=<code>` and PRESSES A BUTTON,
#      which posts {kind:"confirm", code}. A button, not a link that confirms
#      on load: mail security scanners open every link in an inbox, and a
#      scanner that "clicks" would confirm a leaguemate's forged request for
#      the victim without them ever seeing it.
#   5. The next intake sees the confirm, and the update is logged and applied
#      exactly as a token update always was.
#
# A forwarded report therefore grants nothing, a forged request reaches only
# the real subscriber's inbox, and ignoring it changes nothing.

CONFIRM_CODE_LENGTH = 24
# Confirmation emails per address per UTC day — a stranger posting requests
# in a loop can annoy an inbox a little, never flood it.
CONFIRMS_PER_DAY = 3


@dataclass(frozen=True)
class PendingRequest:
    """A validated request waiting for its confirmation."""

    email: str
    replaces: str
    ref: str
    code: str


def confirm_code(email: str, replaces: str, ref: str, secret: str) -> str:
    if not secret:
        raise ValueError("a confirmation code needs a secret")
    message = f"confirm|{email.strip().lower()}|{replaces}|{ref}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:CONFIRM_CODE_LENGTH]


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


def validate_requests(rows: Iterable[Mapping], registry_rows: Iterable[Mapping],
                      known_ids: set[str] | None, secret: str,
                      ) -> tuple[list[PendingRequest], list[str]]:
    """Public-form requests -> requests worth a confirmation email.

    Nothing here changes a roster. A request naming an address that holds no
    subscription is dropped in silence: the page is public, and answering it
    would let anybody learn who subscribes."""
    problems: list[str] = []
    rows = list(rows)
    if not secret:
        if rows:
            problems.append(f"{len(rows)} roster update request(s) arrived but "
                            f"UPDATE_SECRET is not set — no confirmations sent")
        return [], problems
    registry_rows = list(registry_rows)
    out: dict[tuple[str, str], PendingRequest] = {}
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        if not _EMAIL_RE.match(email):
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
                        and str(r.get("origin") or slug_of(str(r.get("ref", ""))))
                        == replaces), None)
        if current is not None and current.get("ref") == ref:
            continue                                   # nothing would change
        # The NEWEST request per subscription wins; the form lists rows in
        # arrival order, so later rows overwrite earlier ones here.
        out[(email, replaces)] = PendingRequest(
            email, replaces, ref, confirm_code(email, replaces, ref, secret))
    return list(out.values()), problems


def confirmed_updates(pending: Iterable[PendingRequest],
                      confirm_rows: Iterable[Mapping], secret: str,
                      now: str | None = None) -> list[RosterUpdate]:
    """The pending requests whose code came back through the confirm page.

    The code is recomputed, never trusted: a confirm row is only a string, and
    it counts only when it equals the code for a request that is still valid
    against the registry as it stands."""
    if not secret:
        return []
    codes = {str(r.get("code") or "").strip().lower() for r in confirm_rows}
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [RosterUpdate(email=p.email, replaces=p.replaces, ref=p.ref, seen_at=stamp)
            for p in pending if p.code in codes]


def confirmation_key(request: PendingRequest, day: str) -> str:
    """Send-log key: one confirmation per request, and no address in it."""
    who = hashlib.sha256(request.email.encode("utf-8")).hexdigest()[:8]
    what = hashlib.sha256(f"{request.replaces}|{request.ref}".encode("utf-8")).hexdigest()[:8]
    return f"confirm-{who}-{day}-{what}"


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
