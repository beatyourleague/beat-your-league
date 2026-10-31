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
# A League Pass is identified by its Stripe SUBSCRIPTION (run/intake.py takes
# it from the session the pass link charged): it outlives a billing-email
# change, it ends exactly when the pass does, and two passes bought with one
# address are two of them (OPS-R4/R5, LP2-D2/D4).
# The purchase that pays for a row: a subscription (sub_) or, for a one-time
# pass (the 2026 rest-of-season passes, Oct 18 2026), its payment (pi_).
_SUBSCRIPTION_RE = re.compile(r"^(?:sub|pi)_[A-Za-z0-9]{4,}$")

PLANS = (SEASON, MONTHLY, LEAGUE_PASS)

# What a PAID row is billed as, kept apart from `plan` (LP-D3, Oct 15 2026).
# `plan` already carries a meaning other code reads — LEAGUE_PASS on a row is a
# SEAT — so a League Pass PAYER was written as an ordinary "season" row, and a
# monthly buyer was too. Every report a payer or a monthly buyer received then
# said "Your season pass renews once a year" at the season's end: false for a
# monthly plan that stops itself, and the wrong product for a $99 pass. A seat
# pays nothing and carries no billing at all.
PASS_BILLING = "pass"
BILLINGS = (SEASON, MONTHLY, PASS_BILLING)
# What a report calls a row bought through the 2027 Season Pass link (``y:``):
# never a `plan` or `billing` value, only ``report_plan``'s word. The row is an
# ordinary season row everywhere else; but "season" prints "your season pass
# renews once a year, on the day you bought it" at the season's end, which is
# false of a pass that renews on a stated August date. A word the report has
# no sentence for prints no sentence, which is the safe way round.
SEASON_2027 = "season_2027"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
    # season | monthly | pass on a paid row; None on a seat. Rows written
    # before the field existed read as their plan (season or monthly).
    billing: str | None = None
    # The day the roster in use was set — the purchase, the seat claim or the
    # last confirmed update — as YYYY-MM-DD. A report says it beside the
    # roster-change route, so a subscriber can see which roster it read.
    roster_as_of: str | None = None
    # The League Pass this row belongs to, as its Stripe subscription id: on
    # a payer's row the pass they bought, on a seat the pass that covers it.
    # A seat is entitled only while THAT subscription is (run/subscriptions
    # RULE E2), and its seat link and seat count are per pass, not per payer
    # address, so one address with two passes has two leagues (LP2-D4).
    pass_id: str | None = None
    # A seat's payer as Stripe knows them, resolved when the seat was
    # confirmed — kept so a later run never has to re-derive it (OPS-R10).
    pass_customer: str | None = None
    # The Stripe subscription(s) behind a PAID row (D2): one normally, several
    # when purchases of one roster were folded into one row. Reports follow
    # THESE — a cancelled one stops its own reports at the end of its period
    # even while the same address pays for another team (run/subscriptions).
    # Empty on a seat (it lives on its pass, RULE E2) and on rows written
    # before the field, which fall back to the customer or the address.
    subscription_ids: tuple[str, ...] = ()
    # Bought through the 2027 Season Pass link (``y:``; run/checkout.py).
    season_2027: bool = False

    @property
    def is_league_seat(self) -> bool:
        return self.plan == LEAGUE_PASS

    @property
    def one_time(self) -> bool:
        """Bought with one payment that never renews (a ``pi_`` purchase) —
        for a seat, its league's pass was. Such a reader has no subscription
        to cancel: the way out is a stop request, and the season's last report
        says nothing renews."""
        ids = tuple(self.subscription_ids) or ((self.pass_id,) if self.pass_id else ())
        return bool(ids) and all(str(i).startswith("pi_") for i in ids)

    @property
    def is_pass_payer(self) -> bool:
        return self.billing == PASS_BILLING

    @property
    def pass_key(self) -> str | None:
        """Which pass a payer or seat row belongs to, for counting seats and
        finding the league's seat link: the pass subscription when the row
        names one, else the payer's address (rows written before passes had
        an identity, and the CSV path). None outside a pass league."""
        if not (self.is_pass_payer or self.is_league_seat):
            return None
        if self.pass_id:
            return self.pass_id
        return (self.covered_by if self.is_league_seat else self.email or "").lower() or None

    @property
    def report_plan(self) -> str:
        """What a report's meta["plan"] says (one vocabulary for every
        renderer): season | monthly | pass (the League Pass PAYER) |
        league_pass (a SEAT, render.report.SEAT_PLAN) | season_2027."""
        if self.is_league_seat:
            return LEAGUE_PASS
        if self.season_2027 and (self.billing or self.plan) == SEASON:
            return SEASON_2027
        return self.billing or self.plan

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
    billing = _billing(raw.get("billing"), plan, where)
    as_of_raw = raw.get("roster_as_of")
    roster_as_of = str(as_of_raw).strip() if as_of_raw else None
    if roster_as_of is not None and not _DATE_RE.match(roster_as_of):
        raise RosterRegistryError(
            f"{where}: roster_as_of must be YYYY-MM-DD, got {as_of_raw!r}")
    pass_id, pass_customer = _pass_fields(raw, plan, billing, where)
    subscription_ids = _subscription_ids(raw.get("subscription_ids"), plan, where)
    subscriber = RosterSubscriber(
        email=email, ref=ref, player_ids=players, slots=slots, scoring=scoring,
        league_size=size, label=label, plan=plan, covered_by=covered_by,
        stripe_customer_id=stripe_customer_id, origin=origin, billing=billing,
        roster_as_of=roster_as_of, pass_id=pass_id, pass_customer=pass_customer,
        subscription_ids=subscription_ids, season_2027=raw.get("season_2027") is True)
    try:
        # RosterSpec carries the roster's own invariants (no duplicate player,
        # enough players to fill the lineup). Running it here means a row that
        # cannot build a report fails the load rather than the Tuesday run.
        subscriber.spec()
    except SubscriberError as exc:
        raise RosterRegistryError(f"{where}: {exc}") from exc
    return subscriber


def _pass_fields(raw: dict, plan: str, billing: str | None,
                 where: str) -> tuple[str | None, str | None]:
    """A row's (pass_id, pass_customer), each checked for shape and for
    belonging on this kind of row: a pass id only on a pass payer or a seat,
    a payer's customer only on a seat (a payer's own is stripe_customer_id)."""
    pass_id = str(raw.get("pass_id") or "").strip() or None
    customer = str(raw.get("pass_customer") or "").strip() or None
    if pass_id is not None:
        if not _SUBSCRIPTION_RE.match(pass_id):
            raise RosterRegistryError(
                f"{where}: pass_id must look like 'sub_...', got {pass_id!r}")
        if plan != LEAGUE_PASS and billing != PASS_BILLING:
            raise RosterRegistryError(
                f"{where}: pass_id belongs on a League Pass payer or seat only")
    if customer is not None:
        if not _CUSTOMER_RE.match(customer):
            raise RosterRegistryError(
                f"{where}: pass_customer must look like 'cus_...', got {customer!r}")
        if plan != LEAGUE_PASS:
            raise RosterRegistryError(
                f"{where}: pass_customer belongs on a League Pass seat only")
    return pass_id, customer


def _subscription_ids(raw: object, plan: str, where: str) -> tuple[str, ...]:
    """A paid row's own subscriptions, each shaped like a Stripe id."""
    if raw in (None, "", []):
        return ()
    if not isinstance(raw, list) or not raw:
        raise RosterRegistryError(f"{where}: subscription_ids must be a list of 'sub_...'")
    if plan == LEAGUE_PASS:
        raise RosterRegistryError(
            f"{where}: a {LEAGUE_PASS} seat lives on its pass, not on subscription_ids")
    ids = tuple(str(s).strip() for s in raw)
    bad = [s for s in ids if not _SUBSCRIPTION_RE.match(s)]
    if bad:
        raise RosterRegistryError(
            f"{where}: subscription_ids must look like 'sub_...' or 'pi_...', got {bad[0]!r}")
    return ids


def _billing(raw: object, plan: str, where: str) -> str | None:
    """A paid row's billing, defaulting to its plan; a seat's is None.

    The two fields must agree where they overlap: a monthly plan is billed
    monthly and nothing else is, and a seat bills nobody. A disagreement is a
    hand edit or a bug in what wrote the row, and either way the season-end
    sentence would describe somebody else's money."""
    value = str(raw).strip() if raw else None
    if plan == LEAGUE_PASS:
        if value:
            raise RosterRegistryError(
                f"{where}: a {LEAGUE_PASS} seat bills nobody, got billing {value!r}")
        return None
    value = value or plan
    if value not in BILLINGS:
        raise RosterRegistryError(
            f"{where}: billing must be one of {BILLINGS}, got {value!r}")
    if (value == MONTHLY) != (plan == MONTHLY):
        raise RosterRegistryError(
            f"{where}: billing {value!r} disagrees with plan {plan!r}")
    return value


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
        for name in ("origin", "billing", "roster_as_of", "pass_id", "pass_customer"):
            if getattr(sub, name):
                row[name] = getattr(sub, name)
        if sub.subscription_ids:
            row["subscription_ids"] = list(sub.subscription_ids)
        if sub.season_2027:
            row["season_2027"] = True
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
    """pass -> the seats it is carrying, keyed by ``RosterSubscriber.pass_key``.

    There is no league id to group on any more. Grouping on the payer's
    ADDRESS counted both of one buyer's leagues against each pass ("4 of 12"
    and "4 of 10" for a 10-team league holding one seat, LP2-D4); the pass
    itself is the league now.
    """
    out: dict[str, list[RosterSubscriber]] = {}
    for sub in subscribers:
        if sub.is_league_seat and sub.pass_key:
            out.setdefault(sub.pass_key, []).append(sub)
    return out
