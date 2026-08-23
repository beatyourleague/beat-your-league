"""The subscriber registry for the product that never reads a league.

``run/registry.py`` describes a Sleeper subscriber: a league id, a user id, a
rival. None of those exist any more (PLAN §0) — what a subscriber has now is the
roster they typed, which the payment carried in its own reference. This is a
separate module rather than more branches inside that one, for two reasons:

* The shapes share no required field. A Sleeper entry without a league id is
  invalid and a roster entry with one is meaningless, so one parser would be two
  parsers wearing a trench coat, and every rule in it would need a "which kind"
  qualifier.
* ``run/registry.py`` imports ``ingest.sleeper``. That import is what keeps
  Sleeper inside the paid path's import graph, and the point of this path is
  that it has no such graph.

Storage is ``data/registry/rosters.json`` — gitignored, like everything holding
an email.

**The whole-file rules are deliberate and inherited.** A malformed row fails the
LOAD, not just itself: silently skipping a paying subscriber is the one
unacceptable failure. That makes anything able to write a bad row a total
outage, which is why the writer validates every row before it lands (see
``drop_unloadable``) rather than trusting what produced it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from engine.subscriber import RosterSpec, SubscriberError
from run.refs import LEAGUE_PASS, MONTHLY, SEASON, RefError, decode_roster

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROSTERS = REPO_ROOT / "data" / "registry" / "rosters.json"

# Deliberately loose: enough to catch a registry typo, not an RFC gate. Same
# standard run/registry.py applies, on purpose — a seat address that passes one
# and fails the other is a row that syncs and then cannot be loaded.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CUSTOMER_RE = re.compile(r"^cus_[A-Za-z0-9]{4,}$")

PLANS = (SEASON, MONTHLY, LEAGUE_PASS)

# A league smaller than four cannot fill a bench and one larger than 32 cannot
# be filled by the NFL. Both ends only ever act as a denominator in buyer-facing
# counts ("8 of the other 11 teams can cover that"), so a wrong one is a visible
# lie rather than a statistical error — but it is still typed by a human.
MIN_LEAGUE_SIZE, MAX_LEAGUE_SIZE = 4, 32


class RosterRegistryError(ValueError):
    """A registry entry that cannot drive a report run."""


@dataclass(frozen=True)
class RosterSubscriber:
    """One paid roster. Everything here came from the subscriber or Stripe."""

    email: str
    # The client_reference_id verbatim. It is the identity of the SUBSCRIPTION
    # (a second team in a second league is a second purchase and a second ref),
    # and keeping it lets any row be re-derived from the payment that made it.
    ref: str
    player_ids: tuple[str, ...]
    slots: tuple[str, ...]
    scoring: str
    league_size: int = 12
    label: str = "Your Team"
    plan: str = SEASON
    covered_by: str | None = None       # payer's email, for League Pass seats
    stripe_customer_id: str | None = None
    # The slug this subscription was FIRST written under. A self-serve roster
    # update replaces ``ref`` (run/updates.py), and everything keyed on the
    # slug — send-log keys, report filenames, the update link itself — must
    # not move when the roster does, or a changed roster is a second send.
    origin: str | None = None

    @property
    def is_league_seat(self) -> bool:
        return self.plan == LEAGUE_PASS

    @property
    def slug(self) -> str:
        """Filename-safe identity carrying no email.

        There is no Sleeper username to fall back on any more, and an email must
        not appear in a filename or a CI log, so this is a digest of the ref:
        stable week to week, unique per subscription, and meaningless to anyone
        who finds it.
        """
        return self.origin or hashlib.sha256(self.ref.encode("utf-8")).hexdigest()[:10]

    @property
    def key(self) -> tuple[str, str]:
        return (self.email.lower(), self.ref)

    def spec(self) -> RosterSpec:
        return RosterSpec(player_ids=self.player_ids, slots=self.slots,
                          scoring=self.scoring, label=self.label)


def _parse_entry(raw: dict, index: int) -> RosterSubscriber:
    where = f"roster registry entry {index}"
    if not isinstance(raw, dict):
        raise RosterRegistryError(f"{where}: not an object")
    email = str(raw.get("email", "")).strip()
    if not _EMAIL_RE.match(email):
        raise RosterRegistryError(f"{where}: invalid email {email!r}")

    ref = str(raw.get("ref", "")).strip()
    try:
        decoded = decode_roster(ref)
    except RefError as exc:
        raise RosterRegistryError(f"{where}: ref does not decode ({exc})") from exc

    # The roster is stored expanded AND encoded, and they have to agree. They
    # are written by the same sync from the same object, so a disagreement is
    # corruption or a hand edit — and the two halves disagreeing silently means
    # somebody gets a report about a roster they do not own.
    players = tuple(str(p) for p in (raw.get("player_ids") or decoded.player_ids))
    slots = tuple(str(s) for s in (raw.get("slots") or decoded.slots))
    scoring = str(raw.get("scoring") or decoded.scoring)
    if players != tuple(decoded.player_ids):
        raise RosterRegistryError(
            f"{where}: player_ids disagree with the ref they came from")
    if slots != tuple(decoded.slots):
        raise RosterRegistryError(
            f"{where}: slots disagree with the ref they came from")
    if scoring != decoded.scoring:
        raise RosterRegistryError(
            f"{where}: scoring {scoring!r} disagrees with the ref ({decoded.scoring})")

    size = raw.get("league_size", 12)
    if isinstance(size, bool) or not isinstance(size, int):
        # JSON true satisfies isinstance(..., int); a `true` here must not
        # silently become a one-team league.
        try:
            size = int(str(size).strip())
        except (TypeError, ValueError):
            raise RosterRegistryError(
                f"{where}: league_size must be a number, got {raw.get('league_size')!r}"
            ) from None
    if not MIN_LEAGUE_SIZE <= size <= MAX_LEAGUE_SIZE:
        raise RosterRegistryError(
            f"{where}: league_size {size} is outside "
            f"{MIN_LEAGUE_SIZE}-{MAX_LEAGUE_SIZE}")

    plan = str(raw.get("plan") or SEASON).strip()
    if plan not in PLANS:
        raise RosterRegistryError(f"{where}: plan must be one of {PLANS}, got {plan!r}")
    covered = raw.get("covered_by")
    covered_by = str(covered).strip() if covered else None
    if plan == LEAGUE_PASS:
        # A seat naming no payer is an unpaid report waiting to be sent.
        if not covered_by or not _EMAIL_RE.match(covered_by):
            raise RosterRegistryError(
                f"{where}: a {LEAGUE_PASS} seat needs covered_by set to the "
                f"payer's email, got {covered!r}")
    elif covered_by:
        raise RosterRegistryError(
            f"{where}: covered_by is only meaningful on a {LEAGUE_PASS} seat")

    customer = raw.get("stripe_customer_id")
    stripe_customer_id = str(customer).strip() if customer else None
    if stripe_customer_id is not None and not _CUSTOMER_RE.match(stripe_customer_id):
        raise RosterRegistryError(
            f"{where}: stripe_customer_id must look like 'cus_...', got {customer!r}")

    label = str(raw.get("label") or "Your Team").strip() or "Your Team"
    origin_raw = raw.get("origin")
    origin = str(origin_raw).strip() if origin_raw else None
    if origin is not None and not re.fullmatch(r"[0-9a-f]{10}", origin):
        raise RosterRegistryError(f"{where}: origin must be a 10-hex slug, got {origin_raw!r}")
    subscriber = RosterSubscriber(
        email=email, ref=ref, player_ids=players, slots=slots, scoring=scoring,
        league_size=size, label=label, plan=plan, covered_by=covered_by,
        stripe_customer_id=stripe_customer_id, origin=origin)
    try:
        # RosterSpec carries the roster's own invariants (no duplicate player,
        # enough players to fill the lineup). Running it here means a row that
        # cannot build a report fails the load rather than the Tuesday run.
        subscriber.spec()
    except SubscriberError as exc:
        raise RosterRegistryError(f"{where}: {exc}") from exc
    return subscriber


def load_rosters(path: Path | None = None) -> list[RosterSubscriber]:
    """Load and validate every entry, failing the whole file on any bad row."""
    path = Path(path) if path is not None else DEFAULT_ROSTERS
    if not path.is_file():
        raise RosterRegistryError(f"no roster registry at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RosterRegistryError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise RosterRegistryError(f"{path} must be a JSON array")
    subscribers = [_parse_entry(entry, i) for i, entry in enumerate(raw)]

    keys = [s.key for s in subscribers]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise RosterRegistryError(
            "the same roster is registered twice for one address: "
            + ", ".join(sorted(ref for _email, ref in duplicates)))
    return subscribers


def to_json(subscribers: list[RosterSubscriber]) -> list[dict]:
    """The on-disk shape. Written by the sync, read by ``load_rosters``."""
    rows = []
    for sub in subscribers:
        row: dict = {
            "email": sub.email, "ref": sub.ref,
            "player_ids": list(sub.player_ids), "slots": list(sub.slots),
            "scoring": sub.scoring, "league_size": sub.league_size,
            "label": sub.label, "plan": sub.plan,
        }
        if sub.covered_by:
            row["covered_by"] = sub.covered_by
        if sub.stripe_customer_id:
            row["stripe_customer_id"] = sub.stripe_customer_id
        rows.append(row)
    return rows


def drop_unloadable(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate projected rows against BOTH of the loader's rules before they
    are written.

    Defence in depth, and it exists because it happened on the Sleeper side: the
    loader fails the whole file, so one bad row is a total outage rather than
    one subscriber's problem. A row we cannot parse is dropped and reported.
    """
    kept: list[dict] = []
    problems: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        try:
            parsed = _parse_entry(row, index)
        except RosterRegistryError as exc:
            problems.append(str(exc))
            continue
        if parsed.key in seen:
            held = kept[seen[parsed.key]]
            held_is_seat = str(held.get("plan") or SEASON) == LEAGUE_PASS
            if held_is_seat != parsed.is_league_seat:
                # The SAME address holds both a payment and a seat for the same
                # roster: one person who bought their own and then claimed a
                # seat under their commissioner's pass, in either order. The
                # payment wins. This is not the hijack case — that arrives under
                # a DIFFERENT address, which is a different key and never
                # collides here — so it must not read like an alarm.
                problems.append(
                    f"{parsed.slug} has both a paid subscription and a League "
                    f"Pass seat; keeping the paid one")
                if parsed.is_league_seat:
                    continue                       # the held payment stays
                kept[seen[parsed.key]] = row       # the payment replaces the seat
                continue
            problems.append(f"two entries for the same roster ({parsed.slug}); "
                            f"keeping the later one")
            kept[seen[parsed.key]] = row
            continue
        seen[parsed.key] = len(kept)
        kept.append(row)
    return kept, problems


def league_pass_seats(subscribers: list[RosterSubscriber]) -> dict[str, list[RosterSubscriber]]:
    """payer email -> the seats their pass is carrying.

    There is no league id to group on any more — a seat names the payer, and the
    payer is what the coverage check reads.
    """
    out: dict[str, list[RosterSubscriber]] = {}
    for sub in subscribers:
        if sub.is_league_seat and sub.covered_by:
            out.setdefault(sub.covered_by.lower(), []).append(sub)
    return out
