"""Payments become subscribers: the roster half of the signup pipeline.

Usage:
    python -m run.intake [--dry-run] [--full] [--registry-dir PATH] [--no-mail]

``run/sync.py`` does this for the Sleeper-era refs (a league id, a user id, a
rival) and verifies each one against Sleeper. There is nothing to verify here
and nothing to ask: the roster came from the subscriber, resolved in front of
them (RULE R3 — ambiguity can only be settled by the person who knows the
answer), and the payment carried it. So this is the shorter pipeline:

1. **Sweep** completed Checkout Sessions since a watermark, through
   ``run/checkout.py`` — the same walk ``run/sync.py`` uses, in one copy.
2. **Decode** each ``client_reference_id`` as a v2 roster ref. A v1 ref is left
   alone rather than reported: both intakes run against the same Stripe account
   during the migration, and each ignoring the other's refs is what lets them.
3. **Check the roster is servable** against the published directory. A paid ref
   naming an id we have never seen is a payment we cannot honour, and writing
   it would fail the registry load for EVERYBODY (the loader is whole-file on
   purpose). It is reported instead, loudly, every run until resolved.
4. **Promote** the roster onto the Stripe Customer, so our dependence on old
   sessions being listable is capped at one week rather than a season.
5. **Project** ``rosters.json`` in the exact shape ``run/rosters.py`` validates,
   dropping anything unloadable rather than taking the file down with it.

**The plan comes from the link that took the money, never from the ref.** Every
payment link is visible in the page source and ``client_reference_id`` is a URL
parameter, so a ``p`` prefix is a CLAIM. With no ``STRIPE_PAYMENT_LINKS`` map
configured, no purchase grants a League Pass — fail closed.

The key is (email, ref), so one purchase is one subscription and a customer
who buys twice gets two reports (reported when it happens). A roster CHANGE
is not a purchase: it arrives as a confirmed self-serve update, or as the
operator's update for a change emailed in (``make roster-update``, both in
run/updates.py), and moves the roster under the subscription's first slug.

**League Pass seats** come from the form Worker and pay nothing, so they are
validated harder than anything else here: a seat names its pass by the
per-pass seat link's token or the payer's typed address, and is honoured
only when that pass was really bought and its subscription is active now
(``sweep_seats``, RULE E2). A claim is a request: the claimed address must
confirm it by email before it becomes a seat, and a re-claim — a roster
change — is confirmed the same way (OPS-R1). Confirmed seats live in the
intake's own seat log, so their identity outlives the Worker's rows (OPS-R6).
One seat per (address, pass), at most as many as the payer's league has
teams (OPS-R7), claimed again each season (LP2-D3). A claim that matches no
pass is told so, once (LP-D1). A new seat gets its first email the day it is
confirmed, by the same rules as a purchase (LP-I4).

**One roster, one report** (LP2-D1): an address holding two subscriptions
for the same roster gets one row; the newer purchase's welcome says the other
keeps billing until they cancel it. Nothing here ever cancels or refunds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from run.checkout import (CUSTOMERS_API, customer_id as _customer_id, is_paid,
                          parse_link_plans, post as _stripe_post,
                          session_email as _session_email, sweep_sessions)
from run.refs import (LEAGUE_PASS, RefError, RosterRef, decode_roster,
                      is_roster_ref)
from run.updates import (UPDATE_LOG_NAME, PendingRequest, append_update_log,
                         applied_request_ts, apply_updates, confirm_url,
                         confirmation_key, confirmed_updates, latest_per_target,
                         load_update_log, seat_token, seat_url, slug_of,
                         validate_requests, validate_updates)
from run.rosters import (_EMAIL_RE, MONTHLY, PASS_BILLING, SEASON,
                         RosterRegistryError, drop_unloadable, load_rosters)
from render.welcome import welcome_message
from run.delivery import DRY_PROVIDER, build_provider, send_all
from run.solo import CACHE_DIR, SoloError, load_week_data, spec_from_ref
from run.subscriptions import SubscriptionError

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "data" / "registry"
SIGNUP_LOG_NAME = "roster-signups.jsonl"
STATE_NAME = "roster-sync-state.json"
REGISTRY_NAME = "rosters.json"

# Customer-metadata keys. Namespaced so nothing collides with what an operator
# sets by hand in the Stripe dashboard.
META_REF = "byl_roster_ref"
META_PLAN = "byl_plan"
# Which channel brought the buyer (contract C5): the join page's ?via= tag,
# carried on the payment's own reference so a PURCHASE can be counted by
# channel, which is the number every partner or affiliate decision needs.
META_VIA = "byl_via"

# "<ref>_via-<tag>" — the join page appends the tag only when the whole stays
# within Stripe's 200 characters (contract C5). The tag's shape is the form
# Worker's, so it cannot carry an address or markup.
_VIA_SUFFIX = re.compile(r"^(?P<ref>.+)_via-(?P<via>[a-z0-9-]{1,24})$")


def split_via(ref: str) -> tuple[str, str | None]:
    """A payment's reference -> (the roster ref, the channel tag or None).

    Stripped BEFORE anything else reads the ref, because everything keyed on a
    ref — the slug, the send-log keys, report filenames, the registry's
    agreement rule — must not move with the channel a buyer arrived from. The
    roster's base64url payload uses the same alphabet, so a suffix is taken
    only when what is left is still a whole, decodable roster ref; otherwise
    the ref is returned untouched for the normal checks to judge."""
    match = _VIA_SUFFIX.match(ref or "")
    if not match or not is_roster_ref(match.group("ref")):
        return ref, None
    try:
        decode_roster(match.group("ref"))
    except RefError:
        return ref, None
    return match.group("ref"), match.group("via")

# Exit codes. 1 means something is WRONG and a human should look; 2 means the
# pipeline simply is not switched on yet, which is not a failure to alert about.
NOT_CONFIGURED = 2


class IntakeError(RuntimeError):
    """The sweep could not run at all."""


def _no_email(text: str) -> str:
    """Operator-facing messages land in a CI log."""
    import re
    return re.sub(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})",
                  r"***@\1", text)


@dataclass
class RosterSignup:
    """One payment, decoded. The append-only log's row."""

    email: str
    ref: str
    plan: str
    seen_at: str                       # Stripe's `created`, as a string
    stripe_customer_id: str | None = None
    league_size: int = 12
    label: str = "Your Team"
    source: str = "stripe"
    via: str | None = None
    # A League Pass SEAT, never in this log (seats live in the seat log,
    # SEAT_LOG_NAME): who pays for it, and the slug it was first claimed under,
    # which a re-claim with a new roster does not move (LP-D4).
    covered_by: str | None = None
    origin: str | None = None
    # The Stripe subscription a purchase started. On a League Pass it IS the
    # pass: seats are entitled through it (run/subscriptions RULE E2) and its
    # seat link is bound to it (LP2-D4).
    subscription_id: str | None = None
    # A seat only: the pass that covers it, and that pass's Stripe customer.
    pass_id: str | None = None
    pass_customer: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.email.lower(), self.ref)

    @property
    def pass_of(self) -> str | None:
        """The League Pass this signup bought (a payer) or sits on (a seat)."""
        if self.plan == "seat":
            return self.pass_id
        return self.subscription_id if self.plan == LEAGUE_PASS else None

    @property
    def slug(self) -> str:
        return self.origin or hashlib.sha256(self.ref.encode("utf-8")).hexdigest()[:10]

    def roster(self) -> RosterRef:
        return decode_roster(self.ref)


# --------------------------------------------------------------------- #
# the append-only log
# --------------------------------------------------------------------- #

def load_log(path: Path) -> list[RosterSignup]:
    if not Path(path).is_file():
        return []
    out: list[RosterSignup] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue                    # a torn line is not a reason to lose the rest
        if isinstance(raw, dict) and raw.get("email") and raw.get("ref"):
            fields = {f: raw[f] for f in RosterSignup.__dataclass_fields__ if f in raw}
            out.append(RosterSignup(**fields))
    return out


def append_log(signups: Iterable[RosterSignup], path: Path) -> int:
    """Append the events not already logged. Idempotent by (email, ref, plan)."""
    known = {(s.email.lower(), s.ref, s.plan) for s in load_log(path)}
    fresh = [s for s in signups
             if (s.email.lower(), s.ref, s.plan) not in known]
    if not fresh:
        return 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as handle:
        for signup in fresh:
            handle.write(json.dumps(asdict(signup), separators=(",", ":")) + "\n")
    return len(fresh)


def project(log: Iterable[RosterSignup]) -> list[RosterSignup]:
    """Latest-wins per (email, ref), by Stripe's own timestamp.

    Position alone is not enough: the log is appended in sweep order, and a
    re-sweep with a wider watermark can put an older event after a newer one.
    """
    latest: dict[tuple[str, str], RosterSignup] = {}
    for signup in log:
        held = latest.get(signup.key)
        if held is None or _stamp(signup) >= _stamp(held):
            latest[signup.key] = signup
    return sorted(latest.values(), key=lambda s: (s.email.lower(), s.ref))


def _stamp(signup: RosterSignup) -> int:
    return int(signup.seen_at) if str(signup.seen_at).isdigit() else 0


# --------------------------------------------------------------------- #
# one roster, one report (LP2-D1)
# --------------------------------------------------------------------- #
#
# A commissioner who already had the $39 season pass and then bought the $99
# League Pass with the same roster held two subscriptions, and every Tuesday
# got two identical reports with the same subject under two keys — and a
# self-serve roster change was refused outright, because two equal rosters
# tie in run/updates._target_for. The key is (email, ref) and the plan prefix
# makes the refs differ, so nothing collapsed them. Now one address with one
# roster (players, lineup, scoring and size: the CONTENT, never the ref
# string) gets one report. Nothing is cancelled or refunded here, ever: the
# other subscription bills until its owner cancels it (if they have not
# already — the log keeps cancelled purchases too), the welcome of the newer
# purchase says so plainly, and the operator log flags it.

# Which purchase a merged row is built from: the pass carries seats and the
# billing the season-end line must describe; then the yearly pass; then monthly.
_KEEP_ORDER = {LEAGUE_PASS: 0, SEASON: 1, MONTHLY: 2}


def _content(signup: RosterSignup) -> tuple | None:
    try:
        roster = signup.roster()
    except RefError:
        return None
    return (signup.email.lower(), tuple(roster.player_ids), tuple(roster.slots),
            roster.scoring, roster.league_size)


@dataclass
class Merged:
    """``merge_same_roster``'s answer. ``signups`` are the rows to write;
    ``duplicates`` maps a purchase's key to the plan of the OTHER subscription
    on its roster, for the newest purchase of each group only (its welcome is
    the one still to be sent); ``groups`` are the merged groups, for the log."""

    signups: list[RosterSignup]
    duplicates: dict[tuple[str, str], str] = field(default_factory=dict)
    groups: list[list[RosterSignup]] = field(default_factory=list)


def merge_same_roster(signups: Iterable[RosterSignup]) -> Merged:
    """One row per (address, roster content). The kept row is the purchase
    _KEEP_ORDER prefers, carrying the OLDEST purchase's slug and time: its
    send keys, stored plans and receipts are the history this person already
    has, so nothing restarts and the week's report is not mailed twice.

    Two League Passes are never one row, even for one roster: each is its own
    league's seat link and seat count (LP2-D4), and merging them would hand
    one league's seats the other's link. Only a season or monthly purchase
    folds into a pass (the oldest one). Pure."""
    groups: dict[tuple, list[RosterSignup]] = {}
    order: list[tuple] = []
    for signup in signups:
        key = _content(signup) or ("ref", signup.key)
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(signup)
    out = Merged(signups=[])
    for key in order:
        held = sorted(groups[key], key=_stamp)
        passes = [s for s in held if s.plan == LEAGUE_PASS]
        if len(passes) > 1:
            out.signups.extend(passes[1:])
            held = [s for s in held if s.plan != LEAGUE_PASS or s is passes[0]]
        if len(held) == 1:
            out.signups.append(held[0])
            continue
        oldest, newest = held[0], held[-1]
        keep = min(held, key=lambda s: (_KEEP_ORDER.get(s.plan, 3), -_stamp(s)))
        out.signups.append(replace(keep, origin=oldest.slug, seen_at=oldest.seen_at))
        others = [s for s in held if s is not newest]
        out.duplicates[newest.key] = min(
            (s.plan for s in others), key=lambda p: _KEEP_ORDER.get(p, 3))
        out.groups.append(held)
    return out


# --------------------------------------------------------------------- #
# the watermark
# --------------------------------------------------------------------- #

def read_state(path: Path) -> dict[str, Any]:
    if not Path(path).is_file():
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def write_state(state: dict[str, Any], path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(state, indent=1), encoding="utf-8")


# --------------------------------------------------------------------- #
# the sweep
# --------------------------------------------------------------------- #

def sweep(api_key: str, since: int | None = None,
          link_plans: dict[str, str] | None = None,
          promote: bool = True) -> tuple[list[RosterSignup], int | None, list[str]]:
    """Completed sessions -> roster signups, newest watermark, problems.

    Problems are returned rather than raised: one unreadable reference is a
    payment that needs a human, not a reason to deny everybody else their
    report.
    """
    signups: list[RosterSignup] = []
    problems: list[str] = []
    promoted: set[str] = set()
    sessions, newest = sweep_sessions(api_key, since, link_plans or {})

    for session in sessions:
        if not is_paid(session):
            continue
        ref = session.get("client_reference_id")
        if not ref:
            problems.append(
                f"PAID-UNATTRIBUTED session {session.get('id')} completed with NO "
                f"reference — somebody has paid and will receive nothing until "
                f"this is resolved by hand (look the session up in Stripe)")
            continue
        if not is_roster_ref(ref):
            # A v1 Sleeper ref. run/sync.py owns those, and during the migration
            # both intakes run against one Stripe account — each ignoring the
            # other's refs is what lets them coexist without either reporting
            # every one of the other's payments as broken.
            continue
        ref, via = split_via(ref)
        try:
            decode_roster(ref)
        except RefError as exc:
            problems.append(
                f"PAID-UNATTRIBUTED session {session.get('id')}: unreadable roster "
                f"reference ({exc}) — paid, undeliverable, needs a human")
            continue
        email = _session_email(session)
        if not email:
            problems.append(
                f"PAID-UNATTRIBUTED session {session.get('id')}: no email on the "
                f"payment, so there is nowhere to send the report")
            continue

        # AUTHORITATIVE PLAN. Every payment link is visible in the page source
        # and client_reference_id is a URL parameter, so the ref's prefix is a
        # claim: trusting it lets anyone pay the monthly link with a "p" ref and
        # receive the League Pass. The plan comes from the link that took the
        # money, and with no map configured nothing grants a pass at all.
        paid_link = session.get("payment_link")
        plan = (link_plans or {}).get(paid_link) if isinstance(paid_link, str) else None
        claimed = decode_roster(ref).plan
        if claimed == LEAGUE_PASS and plan != LEAGUE_PASS:
            problems.append(
                f"session {session.get('id')} claims a League Pass but "
                + ("no plan map is configured (set STRIPE_PAYMENT_LINKS), so it "
                   "was recorded as an ordinary subscription"
                   if not link_plans else
                   f"it paid the {plan or 'unknown'} link — recorded as an "
                   f"ordinary subscription"))

        customer = _customer_id(session)
        created = session.get("created")
        subscription = _subscription_id(session)
        if plan == LEAGUE_PASS and not subscription:
            # Seats are entitled through the pass SUBSCRIPTION (RULE E2), so a
            # pass that started none can never carry a seat. Said, because
            # nobody would otherwise know why eleven claims go nowhere.
            problems.append(
                f"League Pass session {session.get('id')} started no subscription, "
                f"so no seat can be tied to it — check the pass payment link "
                f"bills yearly")
        signups.append(RosterSignup(
            email=email, ref=ref,
            # A pass PAYER is an ordinary subscriber of ours who also covers
            # other people; what makes their league's seats work is seats naming
            # their pass, not anything else stored on this row.
            plan=plan or "season",
            seen_at=str(created) if isinstance(created, int) else "",
            stripe_customer_id=customer, via=via, subscription_id=subscription))
        if promote and customer and customer not in promoted:
            promoted.add(customer)
            try:
                _promote(api_key, customer, ref, plan or "season",
                         consent=_consent(session), via=via)
            except SubscriptionError as exc:
                # Promotion is a durability optimisation, not the signup — the
                # signup is already in hand.
                problems.append(f"could not stamp customer {customer}: {exc}")
    return signups, newest, problems


def _subscription_id(session: dict) -> str | None:
    """The subscription a Checkout Session started (an id, or the object when
    expanded), or None for a one-off payment."""
    raw = session.get("subscription")
    if isinstance(raw, dict):
        raw = raw.get("id")
    return raw if isinstance(raw, str) and raw.startswith("sub_") else None


def _consent(session: dict) -> dict[str, str]:
    """The renewal-consent record for one purchase (California's auto-renewal
    law asks for affirmative consent and proof of it, kept three years).

    The payment links require the terms box (infra/stripe_paylink_text.py,
    whose checkbox text names the yearly renewal and its amount); Stripe marks
    the session consent.terms_of_service = "accepted". Copied onto the
    Customer with the time and the terms version, because a Checkout Session
    has no documented retention and a Customer lives as long as they do."""
    from render.welcome import TERMS_VERSION
    accepted = ((session.get("consent") or {}).get("terms_of_service") == "accepted")
    created = session.get("created")
    if not accepted:
        return {}
    return {"byl_terms_accepted": "yes",
            "byl_terms_version": TERMS_VERSION,
            "byl_terms_accepted_at": str(created) if isinstance(created, int) else ""}


def _promote(api_key: str, customer: str, ref: str, plan: str,
             consent: dict[str, str] | None = None, via: str | None = None) -> None:
    """Copy the roster onto the Customer, where it lives as long as they do.

    Stripe documents no retention guarantee for old Checkout Sessions, so this
    caps our dependence on session listability at one week instead of a season.
    Metadata writes MERGE, so this is additive and idempotent. The consent
    record rides along (``_consent``), and so does the channel tag the
    purchase carried (``split_via``) — written only when there is one, so a
    later untagged purchase never erases the channel an earlier one recorded.
    """
    form = {f"metadata[{META_REF}]": ref, f"metadata[{META_PLAN}]": plan}
    form.update({f"metadata[{k}]": v for k, v in (consent or {}).items()})
    if via:
        form[f"metadata[{META_VIA}]"] = via
    _stripe_post(f"{CUSTOMERS_API}/{urllib.parse.quote(customer)}", api_key, form)


# --------------------------------------------------------------------- #
# servability: can we actually build this roster a report?
# --------------------------------------------------------------------- #

def unservable(signups: Iterable[RosterSignup],
               known_ids: set[str]) -> dict[tuple[str, str], str]:
    """Which signups name players the directory has never heard of.

    A ref decodes to ids, not to players. Writing one we cannot resolve fails
    the registry load for EVERY subscriber — the loader is whole-file on
    purpose — and even if it loaded, it would render as blank rows in a report
    somebody paid for.
    """
    out: dict[tuple[str, str], str] = {}
    for signup in signups:
        try:
            missing = [pid for pid in signup.roster().player_ids
                       if pid not in known_ids]
        except RefError as exc:
            out[signup.key] = f"the reference stopped decoding: {exc}"
            continue
        if missing:
            out[signup.key] = (
                f"{len(missing)} player id(s) are not in the directory "
                f"({', '.join(missing[:5])})")
    return out


# --------------------------------------------------------------------- #
# League Pass seats — the one path with no payment behind it
# --------------------------------------------------------------------- #

def fetch_seats(endpoint: str, api_key: str | None = None) -> list[dict]:
    """Read seat claims from the form backend.

    Deliberately one small function against a plain JSON endpoint: every hosted
    form vendor can produce one, and swapping vendors is this function rather
    than an architecture.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(endpoint, method="GET")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise IntakeError(f"seat backend returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise IntakeError(f"could not reach the seat backend: {exc}") from None
    except json.JSONDecodeError:
        raise IntakeError("seat backend returned something that is not JSON") from None
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = None
        for key in ("data", "submissions", "items", "records", "results", "rows"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
        if rows is None:
            # FAIL CLOSED. An unrecognised SHAPE used to yield [] — identical to
            # "nobody claimed a seat" — so a backend answering {"records":[...]}
            # (Airtable's own key, among others) wrote a Stripe-only registry
            # and exited 0, silently dropping every League Pass seat. That is
            # the exact outcome the refusal above exists to prevent, reached
            # through the one door it did not cover. Found Aug 24 2026.
            raise IntakeError(
                f"seat backend returned a JSON object with no recognisable row "
                f"list (keys: {sorted(payload)[:6]}) — refusing to read it as "
                f"an empty week")
    else:
        raise IntakeError(
            f"seat backend returned {type(payload).__name__}, not a row list")
    return [row for row in rows if isinstance(row, dict)]


_SEAT_TOKEN = re.compile(r"^[0-9a-f]{20}$")
# The intake's own record of every CONFIRMED seat claim, append-only beside
# the signup log (OPS-R6). A seat's identity — the slug its send keys, plans
# and receipts live under, and the moment it was first claimed, which keys its
# welcome — used to be re-derived every run from the form Worker's rows, which
# expire ~400 days after they arrive: when last season's first claim expired
# mid-season the same seat got a new slug, a second "Your seat is in" and a
# second copy of the week's report. Nothing here expires.
SEAT_LOG_NAME = "seat-log.jsonl"
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
_CUSTOMER = re.compile(r"^cus_[A-Za-z0-9]{4,}$")


def _received(row: Mapping) -> datetime | None:
    """The form Worker's own stamp on a row (a caller cannot set it), or None."""
    raw = str(row.get("received_at") or "").strip()
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class PassInfo:
    """One League Pass a seat can name this run."""

    payer: str                  # the address the pass was bought with
    pass_id: str                # its Stripe subscription (RULE E2)
    league_size: int            # the payer's league, which caps its seats
    customer: str | None = None
    # Active and not refunded in full RIGHT NOW. A seat on a pass that is not
    # is neither confirmed, welcomed nor served (OPS-R4, LP2-D2).
    entitled: bool = True

    @property
    def seat_cap(self) -> int:
        """As many seats as the payer's league has teams (OPS-R7): one for
        every other team, and one to spare for a co-manager (the League Pass
        page says each co-manager claims their own seat). The pass covers
        "every member of one league"; a seat link forwarded outside it used
        to mean unlimited free reports on one $99 purchase."""
        return max(0, int(self.league_size))


def pass_infos(signups: Iterable[RosterSignup],
               entitled: Iterable[str]) -> list[PassInfo]:
    """The League Passes in the signup log, each entitled only while its own
    subscription is in ``entitled`` (the PaidList's ``subscription_ids``).

    Built from what the LINK took (a signup's plan is the payment link's,
    never the ref's) and from the subscription's live state — never from the
    log alone, which still names a pass refunded last week (OPS-R4). A pass
    that started no subscription carries no seat (``sweep`` says so)."""
    live = set(entitled)
    out: list[PassInfo] = []
    seen: set[str] = set()
    for signup in signups:
        if signup.plan != LEAGUE_PASS or not signup.subscription_id:
            continue
        if signup.subscription_id in seen:
            continue
        seen.add(signup.subscription_id)
        try:
            size = signup.roster().league_size
        except RefError:
            continue
        out.append(PassInfo(payer=signup.email.lower(), pass_id=signup.subscription_id,
                            league_size=size, customer=signup.stripe_customer_id,
                            entitled=signup.subscription_id in live))
    return out


@dataclass
class SeatEntry:
    """One CONFIRMED seat claim: a line of the seat log."""

    email: str
    pass_id: str
    payer: str
    ref: str
    claimed_at: str             # the Worker's stamp on the claim, verbatim
    confirmed_at: str           # when this intake first saw it confirmed
    customer: str | None = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        """A claim's identity, independent of any signing secret."""
        return (self.email.lower(), self.pass_id, self.ref, self.claimed_at)

    @property
    def at(self) -> datetime | None:
        return _received({"received_at": self.claimed_at})


def _seated_at(entry: SeatEntry) -> datetime:
    """When this confirmed claim was first seen confirmed — the moment its
    seat existed, which is what a full pass's order is by (OPS-R7). The
    claim's own stamp stands in for an entry written without one."""
    try:
        at = datetime.fromisoformat(entry.confirmed_at)
    except ValueError:
        return entry.at or _EPOCH
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def load_seat_log(path: Path) -> list[SeatEntry]:
    if not Path(path).is_file():
        return []
    out: list[SeatEntry] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue                    # a torn line is not a reason to lose the rest
        if isinstance(raw, dict) and all(raw.get(k) for k in
                                         ("email", "pass_id", "payer", "ref", "claimed_at")):
            fields = {f: raw[f] for f in SeatEntry.__dataclass_fields__ if f in raw}
            fields.setdefault("confirmed_at", "")
            out.append(SeatEntry(**fields))
    return out


def append_seat_log(entries: Iterable[SeatEntry], path: Path) -> int:
    """Append the confirmed claims not already logged. Idempotent by claim."""
    known = {e.key for e in load_seat_log(path)}
    fresh = [e for e in entries if e.key not in known]
    if not fresh:
        return 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as handle:
        for entry in fresh:
            handle.write(json.dumps(asdict(entry), separators=(",", ":")) + "\n")
    return len(fresh)


@dataclass(frozen=True)
class PendingSeat:
    """A matched claim waiting for the claimed address to confirm it."""

    email: str
    pass_id: str
    ref: str
    code: str
    ts: str
    # A re-claim by somebody who already holds a seat on this pass: a ROSTER
    # change, which the email says, not a new seat.
    change: bool = False


@dataclass
class SeatSweep:
    """Every seat claim, judged. ``rows`` are registry rows; ``unmatched`` are
    well-formed claims that name no League Pass (LP-D1); ``first_claimed`` and
    ``last_claimed`` are keyed (email, origin slug)."""

    rows: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)
    first_claimed: dict[tuple[str, str], datetime] = field(default_factory=dict)
    last_claimed: dict[tuple[str, str], datetime] = field(default_factory=dict)
    # Seats whose roster a later confirmed claim replaced. Counted in the
    # summary rather than reported per seat: the claims live in the Worker for
    # ~400 days, so a per-seat line would repeat every hourly run as if news.
    reclaimed: int = 0
    # Claims waiting on their address's confirmation (each mailed a code), and
    # the claims confirmed for the first time in this run (to log).
    awaiting: list[PendingSeat] = field(default_factory=list)
    confirmed: list[SeatEntry] = field(default_factory=list)
    # Claims a full pass cannot take, and confirmed seats past the cap — each
    # told once that the league's seats are taken (OPS-R7).
    full: list[dict] = field(default_factory=list)
    overflow: int = 0
    # Claims and logged seats from before this season — a seat is claimed
    # again each season with that season's roster (LP2-D3).
    retired: int = 0
    # Confirmed seats whose pass is not active right now (refunded, lapsed).
    lapsed: int = 0
    # Seat-link claims are arriving and not one matches a pass: a rotated or
    # missing signing secret, not a run of typos (OPS-R10). Exits non-zero.
    links_dead: bool = False


@dataclass(frozen=True)
class _Claim:
    email: str
    pass_: PassInfo
    ref: str
    ts: str
    at: datetime
    row: Mapping


def _match_claims(rows: Iterable[Mapping], passes: list[PassInfo], keys: list[str],
                  known_ids: set[str] | None, season_from: datetime | None,
                  out: SeatSweep) -> tuple[list[_Claim], set[str], list[Mapping], int]:
    """Each well-formed claim of this season -> the pass it names, or an
    unmatched row. -> (claims, addresses that matched, seat-link rows, how
    many seat-link rows matched). Problems are written onto ``out``."""
    by_token = {seat_token(p.payer, key, p.pass_id): p for p in passes for key in keys}
    by_payer: dict[str, list[PassInfo]] = {}
    for p in passes:
        by_payer.setdefault(p.payer, []).append(p)
    claims: list[_Claim] = []
    matched: set[str] = set()
    token_rows: list[Mapping] = []
    token_hits = 0
    for row in sorted(rows, key=lambda r: _received(r) or _EPOCH):
        email = str(row.get("email") or "").strip().lower()
        typed = str(row.get("covered_by") or "").strip().lower()
        token = str(row.get("pass_token") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        # Validated to run/rosters.py's own standard HERE, because this endpoint
        # is public and the registry loader fails the WHOLE file on one bad row.
        # Accepting "not an email" would let any stranger stop every
        # subscriber's Tuesday.
        named = _SEAT_TOKEN.match(token) or _EMAIL_RE.match(typed)
        if not _EMAIL_RE.match(email) or not named:
            out.problems.append("a seat claim arrived with unusable addresses")
            continue
        at = _received(row)
        if season_from is not None and at is not None and at < season_from:
            out.retired += 1
            continue
        try:
            roster = decode_roster(ref)
        except RefError as exc:
            out.problems.append(f"seat claim from {_no_email(email)} carries an "
                                f"unreadable roster ({exc})")
            continue
        if _SEAT_TOKEN.match(token):
            token_rows.append(row)
            found = by_token.get(token)
            token_hits += found is not None
        else:
            options = by_payer.get(typed, [])
            found = options[0] if len(options) == 1 else None
            if len(options) > 1:
                out.problems.append(
                    f"seat claim from {_no_email(email)} names a payer with "
                    f"{len(options)} League Passes — only a league's own seat "
                    f"link can say which")
        if found is None:
            out.problems.append(
                f"seat claim from {_no_email(email)} "
                + ("carries a seat link that matches no League Pass"
                   if _SEAT_TOKEN.match(token) else
                   "names a payer with no League Pass")
                + " — not honoured")
            out.unmatched.append(dict(row))
            continue
        matched.add(email)
        if email == found.payer:
            # The pass buyer already has their own paid row; a seat for
            # themselves would be a second report for one purchase.
            out.problems.append(
                f"seat claim from {_no_email(email)} names ITSELF as the payer "
                f"— the pass buyer already has their own subscription")
            continue
        missing = ([pid for pid in roster.player_ids if pid not in known_ids]
                   if known_ids else [])
        if missing:
            out.problems.append(
                f"seat claim from {_no_email(email)} names {len(missing)} "
                f"player id(s) the directory does not have")
            continue
        if at is None:
            # A code binds the Worker's stamp; a row without one cannot be
            # confirmed (the Worker always stamps — this is not its row).
            out.problems.append(f"seat claim from {_no_email(email)} carries no "
                                f"Worker stamp — not honoured")
            continue
        claims.append(_Claim(email, found, ref, str(row.get("received_at")), at, row))
    return claims, matched, token_rows, token_hits


def _seat_row(email: str, owner: PassInfo, held: list[SeatEntry], roster) -> dict:
    """The registry row of one seat: the newest confirmed roster, under the
    slug the seat was first confirmed with."""
    latest = held[-1]
    return {
        "email": email, "ref": latest.ref,
        "player_ids": list(roster.player_ids), "slots": list(roster.slots),
        "scoring": roster.scoring, "league_size": roster.league_size,
        "label": "Your Team", "plan": LEAGUE_PASS, "covered_by": owner.payer,
        "origin": slug_of(held[0].ref), "pass_id": owner.pass_id,
        **({"pass_customer": owner.customer}
           if owner.customer and _CUSTOMER.match(owner.customer) else {}),
        **({"roster_as_of": latest.at.date().isoformat()} if latest.at else {}),
    }


def _returned_codes(confirm: Iterable[str | Mapping]) -> dict[str, datetime | None]:
    """Confirm-page codes -> when the Worker received each (None for a bare
    code). A code confirms a claim only when it came back within EXPIRY_DAYS
    of the claim — judged by the button press's own stamp, never by the hour
    an intake happens to run."""
    out: dict[str, datetime | None] = {}
    for item in confirm:
        code = str(item.get("code") if isinstance(item, Mapping) else item).strip().lower()
        at = _received(item) if isinstance(item, Mapping) else None
        if code and (code not in out or (at and (out[code] is None or at < out[code]))):
            out[code] = at
    return out


def sweep_seats(rows: Iterable[dict], passes: Iterable[PassInfo],
                known_ids: set[str] | None, secrets: str | Iterable[str] = (), *,
                confirm_codes: Iterable[str | Mapping] = (),
                log: Iterable[SeatEntry] = (), now: datetime | None = None,
                season_from: datetime | None = None) -> SeatSweep:
    """Seat claims and the seat log -> registry rows, confirmations to send,
    and claims newly confirmed. Pure: everything it reads is an argument.

    ``passes`` are the League Passes actually bought (``pass_infos``), built
    from sessions whose own `payment_link` was the pass link — never from what
    a seat claims. The seat form is public by necessity, so without that check
    it is a free-report generator for anyone who finds the URL.

    A claim names its pass one of two ways. The per-pass seat link (contract
    C4) carries ``pass_token``, recomputed here under every signing secret
    (``run.updates.signing_secrets``) and never trusted from the row. The older
    route has the leaguemate type the payer's address as ``covered_by``, which
    names a pass only when that address bought exactly one.

    **A claim is a REQUEST, never a seat (OPS-R1).** The seat link rides on
    every pass report, written to be forwarded, so it proves nothing about who
    is claiming: honoured on sight, it let anyone enrol a stranger's address
    for weekly mail or replace a seat holder's roster with nobody told. Each
    matched claim is mailed a code at the claimed address (``awaiting``); it
    becomes a seat only when that code comes back through the confirm page's
    button (``confirm_codes``), and then it is logged (``confirmed``, for
    SEAT_LOG_NAME) and never needs the Worker row or the secret again. A code
    lives EXPIRY_DAYS and is single-use: a claim at or before the newest
    confirmed one for the same seat is dead.

    ONE SEAT PER (address, pass) — LP-D4. A re-claim is a roster change, under
    the same confirmation: the newest confirmed claim's roster stands, under
    the slug the seat was FIRST confirmed with (``origin``), so its send keys,
    stored plans and update link never move. A claim for the roster already
    held changes nothing and is not mailed.

    A pass carries at most ``PassInfo.seat_cap`` seats, in the order they were
    confirmed (OPS-R7) — a served seat is never displaced by an older claim
    confirmed later; the rest are told the league's seats are taken. Claims
    and logged seats from before ``season_from`` are retired: each season's
    seat is claimed with that season's roster (LP2-D3).

    ``known_ids`` is None when the directory could not be loaded at all. That
    must mean "not checked", never "nothing is known" — an empty set would
    reject every seat with a confident, wrong reason on the one day a data
    release is unavailable.
    """
    from run.updates import CONFIRMS_PER_DAY, EXPIRY_DAYS, same_roster, seat_code
    keys = [secrets] if isinstance(secrets, str) else list(secrets)
    keys = [key for key in keys if key]
    now = now or datetime.now(timezone.utc)
    returned = _returned_codes(confirm_codes)
    expiry = timedelta(days=EXPIRY_DAYS)
    out = SeatSweep()
    passes = list(passes)
    by_id = {p.pass_id: p for p in passes}
    claims, matched, token_rows, token_hits = _match_claims(
        rows, passes, keys, known_ids, season_from, out)

    # The log, this season's part of it, plus whatever came back confirmed now.
    entries: list[SeatEntry] = []
    for entry in log:
        if season_from is not None and (entry.at or _EPOCH) < season_from:
            out.retired += 1
            continue
        entries.append(entry)
    logged = {entry.key for entry in entries}
    newest: dict[tuple[str, str], datetime] = {}
    for entry in entries:
        seat = (entry.email.lower(), entry.pass_id)
        if entry.at is not None and entry.at > newest.get(seat, _EPOCH):
            newest[seat] = entry.at

    def live(claim: _Claim, by: datetime) -> bool:
        """Not logged, not expired by ``by``, and newer than the claim that
        stands."""
        seat = (claim.email, claim.pass_.pass_id)
        return ((claim.email, claim.pass_.pass_id, claim.ref, claim.ts) not in logged
                and by - claim.at <= expiry
                and claim.at > newest.get(seat, _EPOCH))

    for claim in claims:                          # oldest first
        codes = {seat_code(claim.email, claim.pass_.pass_id, claim.ref, claim.ts, key)
                 for key in keys}
        pressed = [returned[code] or now for code in codes if code in returned]
        if not pressed or not claim.pass_.entitled or not live(claim, min(pressed)):
            continue
        entry = SeatEntry(email=claim.email, pass_id=claim.pass_.pass_id,
                          payer=claim.pass_.payer, ref=claim.ref,
                          claimed_at=claim.ts,
                          confirmed_at=now.isoformat(timespec="seconds"),
                          customer=claim.pass_.customer)
        entries.append(entry)
        out.confirmed.append(entry)
        logged.add(entry.key)
        newest[(claim.email, claim.pass_.pass_id)] = claim.at

    # One seat per (address, pass), from the log alone.
    seats: dict[tuple[str, str], list[SeatEntry]] = {}
    for entry in sorted(entries, key=lambda e: e.at or _EPOCH):
        seats.setdefault((entry.email.lower(), entry.pass_id), []).append(entry)
    by_pass: dict[str, list[tuple[datetime, datetime, str, list[SeatEntry]]]] = {}
    for (email, pass_id), held in seats.items():
        owner = by_id.get(pass_id)
        if owner is None or not owner.entitled:
            out.lapsed += 1
            continue
        # Confirmed first, then (for seats confirmed in one run) claimed first.
        by_pass.setdefault(pass_id, []).append(
            (min(_seated_at(entry) for entry in held), held[0].at or _EPOCH, email, held))

    taken: dict[str, int] = {}
    for pass_id, group in by_pass.items():
        owner = by_id[pass_id]
        # The cap counts every confirmed seat in the order it was CONFIRMED,
        # before anything this run might fail to build: a seat already being
        # served is never displaced by an older claim confirmed later, and a
        # seat skipped for one run (a directory hiccup) never lets one past
        # the cap in for that run — with a welcome — only to drop it again.
        group.sort(key=lambda item: item[:3])
        for index, (_seated, _claimed, email, held) in enumerate(group):
            if index >= owner.seat_cap:
                out.overflow += 1
                out.full.append({"email": email, "received_at": held[0].claimed_at,
                                 "ref": held[0].ref, "pass_id": pass_id})
                continue
            try:
                roster = decode_roster(held[-1].ref)
            except RefError as exc:
                out.problems.append(f"a logged seat for {_no_email(email)} stopped "
                                    f"decoding ({exc}) — not served")
                continue
            if known_ids and any(pid not in known_ids for pid in roster.player_ids):
                out.problems.append(f"the seat of {_no_email(email)} names a player "
                                    f"the directory no longer has — not served this run")
                continue
            row = _seat_row(email, owner, held, roster)
            out.rows.append(row)
            if len({entry.ref for entry in held}) > 1:
                out.reclaimed += 1
            for stamp, into in ((held[0].at, out.first_claimed),
                                (held[-1].at, out.last_claimed)):
                if stamp is not None:
                    into[(email, row["origin"])] = stamp
        taken[pass_id] = min(len(group), owner.seat_cap)
        if len(group) > owner.seat_cap:
            out.problems.append(
                f"League Pass {pass_id} is full: {len(group) - owner.seat_cap} "
                f"confirmed seat(s) past its {owner.seat_cap} seats (one per team "
                f"in a {owner.league_size}-team league) are not served — the first "
                f"seats confirmed are kept")

    # Every live claim that would change something is mailed its code.
    pending: list[PendingSeat] = []
    unsigned = 0
    for claim in claims:
        if not live(claim, now):
            continue
        owner = claim.pass_
        if not owner.entitled:
            out.problems.append(f"seat claim from {_no_email(claim.email)} names a "
                                f"League Pass that is not active — nothing sent")
            continue
        held = seats.get((claim.email, owner.pass_id))
        if held and same_roster(held[-1].ref, claim.ref):
            continue                              # the roster they already have
        if not held and taken.get(owner.pass_id, 0) >= owner.seat_cap:
            out.full.append(dict(claim.row))
            continue
        if not keys:
            unsigned += 1
            continue
        pending.append(PendingSeat(
            claim.email, owner.pass_id, claim.ref,
            seat_code(claim.email, owner.pass_id, claim.ref, claim.ts, keys[0]),
            claim.ts, change=bool(held)))
    if unsigned:
        out.problems.append(f"{unsigned} seat claim(s) cannot be confirmed: "
                            f"UPDATE_SECRET is not set")
    # At most CONFIRMS_PER_DAY codes reach one address a day (by the Worker's
    # date): the form is public, so a stranger can annoy an inbox a little and
    # never flood it.
    per_day: dict[tuple[str, str], int] = {}
    for request in sorted(pending, key=lambda r: r.ts):
        bucket = (request.email, request.ts[:10])
        per_day[bucket] = per_day.get(bucket, 0) + 1
        if per_day[bucket] <= CONFIRMS_PER_DAY:
            out.awaiting.append(request)

    # OPS-R9: an address whose claim DID match a pass is never also told its
    # other claim matched nothing — a typo'd first try and a matched second
    # one were sent "Your seat is in" and "isn't set up yet" in the same run.
    out.unmatched = [row for row in out.unmatched
                     if str(row.get("email") or "").strip().lower() not in matched]
    # OPS-R10: seat-link claims arriving and NOT ONE matching is a signing
    # secret that was rotated or unset, not a run of typos. Loud, and nobody
    # is told "no pass" for a link that was good when it was sent.
    recent = [row for row in token_rows
              if (at := _received(row)) is not None and now - at <= UNMATCHED_MAX_AGE]
    if recent and not token_hits and (passes or not keys):
        out.links_dead = True
        out.problems.append(
            f"SEAT LINKS MATCH NO PASS: {len(recent)} claim(s) through a seat link "
            f"in the last {UNMATCHED_MAX_AGE.days} days and not one matches a "
            f"League Pass. If UPDATE_SECRET was rotated, set the old value in "
            f"UPDATE_SECRET_PREVIOUS; if it is unset, set it. Nobody is told "
            f"their claim failed until this is fixed.")
        out.unmatched = [row for row in out.unmatched
                         if not _SEAT_TOKEN.match(str(row.get("pass_token") or "").lower())]
    return out


def seats_to_rows(rows: Iterable[dict], passes: Iterable[PassInfo],
                  known_ids: set[str] | None, secret: str | Iterable[str] = "",
                  **kwargs) -> tuple[list[dict], list[str]]:
    """``sweep_seats`` as (registry rows, problems)."""
    swept = sweep_seats(rows, passes, known_ids, secret, **kwargs)
    return swept.rows, swept.problems


def seat_signups_from(rows: Iterable[Mapping],
                      first_claimed: Mapping[tuple[str, str], datetime],
                      ) -> list[RosterSignup]:
    """The seats a registry is about to hold, as signups for the mail a
    purchase gets (welcome, first report). Their "purchase" moment is the
    FIRST confirmed claim (the Worker's stamp on it), which keys both the
    welcome and the served-since check, so neither repeats when the roster
    moves (LP-D4) — and, read from the seat log, never moves when a Worker
    row expires (OPS-R6)."""
    out: list[RosterSignup] = []
    for row in rows:
        if row.get("plan") != LEAGUE_PASS:
            continue
        email = str(row.get("email", "")).lower()
        origin = str(row.get("origin") or slug_of(str(row.get("ref", ""))))
        claimed = first_claimed.get((email, origin))
        out.append(RosterSignup(
            email=email, ref=str(row["ref"]), plan="seat",
            seen_at=str(int(claimed.timestamp())) if claimed else "",
            league_size=int(row.get("league_size") or 12), source="seat",
            covered_by=str(row.get("covered_by") or "").lower() or None,
            origin=origin, pass_id=row.get("pass_id") or None,
            pass_customer=row.get("pass_customer") or None))
    return out


def seat_counts(rows: Iterable[Mapping]) -> dict[str, int]:
    """pass -> the seats it carries in this registry (contract C2: a count,
    never who), keyed like ``RosterSubscriber.pass_key``: the pass
    subscription, or the payer's address on a row that names none."""
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("plan") == LEAGUE_PASS and row.get("covered_by"):
            key = str(row.get("pass_id") or str(row["covered_by"]).lower())
            counts[key] = counts.get(key, 0) + 1
    return counts


# --------------------------------------------------------------------- #
# a claim that matched no pass is told so — once (LP-D1)
# --------------------------------------------------------------------- #
#
# A claim naming a payer with no League Pass (a typo, swapped fields, the
# wrong buyer) was dropped with a line in a CI log, while the page had told
# the leaguemate "Your seat request is in". Nobody else could ever tell them.
# Now the claimer hears it once per claim, from here, with what to check.
#
# - A grace period first: a leaguemate can claim from the group chat minutes
#   before the buyer's payment is swept, and telling them "no pass" then
#   would be false an hour later.
# - Never a stale claim: Worker rows live ~400 days, and a claim from last
#   season answered now is unrequested mail.
# - Capped per address per day: the seat form is public, so a stranger can
#   type somebody else's address — at most this many notes reach that inbox
#   a day, each saying it is safe to ignore.
# - The buyer's report says nothing about any of it: a stranger's claim is
#   not the buyer's business, and naming it would put addresses in front of
#   somebody who did not ask.

UNMATCHED_GRACE = timedelta(hours=6)
UNMATCHED_MAX_AGE = timedelta(days=14)
UNMATCHED_PER_DAY = 2


def unmatched_key(row: Mapping) -> str:
    """Send-log key: one note per claim, ever, with no address in it."""
    email = str(row.get("email") or "").strip().lower()
    claim = "|".join(str(row.get(k) or "") for k in
                     ("received_at", "ref", "covered_by", "pass_token"))
    return (f"seat-unmatched-{hashlib.sha256(email.encode()).hexdigest()[:8]}-"
            f"{hashlib.sha256(claim.encode()).hexdigest()[:10]}")


def unmatched_due(unmatched: Iterable[Mapping], now: datetime) -> list[Mapping]:
    """The unmatched claims to tell, oldest first: past the grace period,
    within the age limit, at most UNMATCHED_PER_DAY per address per Worker
    date. A claim with no readable Worker stamp cannot be shown to be fresh,
    so it is not mailed. Pure."""
    due: list[tuple[datetime, Mapping]] = []
    for row in unmatched:
        at = _received(row)
        if at is None or not (UNMATCHED_GRACE <= now - at <= UNMATCHED_MAX_AGE):
            continue
        due.append((at, row))
    per_day: dict[tuple[str, str], int] = {}
    out: list[Mapping] = []
    for at, row in sorted(due, key=lambda item: item[0]):
        bucket = (str(row.get("email") or "").strip().lower(), at.date().isoformat())
        per_day[bucket] = per_day.get(bucket, 0) + 1
        if per_day[bucket] <= UNMATCHED_PER_DAY:
            out.append(row)
    return out


def _send_unmatched_notes(unmatched: list[Mapping], now: datetime) -> None:
    """One note per unmatched claim, idempotent through the send log."""
    due = unmatched_due(unmatched, now)
    if not due:
        return
    from render.report import seat_stop_href
    from render.seat_claim import unmatched_email
    from run.delivery import Message
    messages = []
    for row in due:
        subject, html, text = unmatched_email(os.environ.get("SITE_URL", ""))
        messages.append(Message(to=str(row.get("email")).strip().lower(),
                                subject=subject, html=html, text=text,
                                key=unmatched_key(row),
                                unsubscribe=seat_stop_href()))
    _send_notes("Unmatched seat claims", messages)


def _send_notes(what: str, messages: list) -> None:
    """Send a batch of seat notes through the idempotent delivery layer, or
    say they are pending when no provider is configured."""
    if not messages:
        return
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"{what}: {len(messages)} note(s) pending — "
              f"EMAIL_PROVIDER is not set, so none were sent.")
        return
    sends = send_all(messages, provider=provider)
    delivered = [r for r in sends if r.ok and not r.skipped]
    failures = [r for r in sends if not r.ok]
    print(f"{what} via {provider.name}: {len(delivered)} note(s) "
          f"sent, {len(failures)} failed")
    for result in failures:
        print(f"    SEAT NOTE FAILED {result.message.key}: {result.detail}",
              file=sys.stderr)


# A pass whose league's seats are all taken (OPS-R7) tells the claimer so,
# once per claim and at most UNMATCHED_PER_DAY a day per address — the form is
# public, so the same caps as the unmatched note apply. No grace period:
# fullness is a fact about seats already confirmed, not a payment in flight.
def full_key(row: Mapping) -> str:
    """Send-log key: one note per refused claim, ever, with no address in it."""
    email = str(row.get("email") or "").strip().lower()
    claim = "|".join(str(row.get(k) or "") for k in
                     ("received_at", "ref", "covered_by", "pass_token", "pass_id"))
    return (f"seat-full-{hashlib.sha256(email.encode()).hexdigest()[:8]}-"
            f"{hashlib.sha256(claim.encode()).hexdigest()[:10]}")


def full_due(full: Iterable[Mapping], now: datetime) -> list[Mapping]:
    """The full-pass notes to send: within UNMATCHED_MAX_AGE of the claim, at
    most UNMATCHED_PER_DAY per address per Worker date. Pure."""
    per_day: dict[tuple[str, str], int] = {}
    out: list[Mapping] = []
    for row in sorted(full, key=lambda r: _received(r) or _EPOCH):
        at = _received(row)
        if at is None or now - at > UNMATCHED_MAX_AGE:
            continue
        bucket = (str(row.get("email") or "").strip().lower(), at.date().isoformat())
        per_day[bucket] = per_day.get(bucket, 0) + 1
        if per_day[bucket] <= UNMATCHED_PER_DAY:
            out.append(row)
    return out


def _send_full_notes(full: list[Mapping], now: datetime) -> None:
    from render.report import seat_stop_href
    from render.seat_claim import full_email
    from run.delivery import Message
    messages = []
    for row in full_due(full, now):
        subject, html, text = full_email(os.environ.get("SITE_URL", ""))
        messages.append(Message(to=str(row.get("email")).strip().lower(),
                                subject=subject, html=html, text=text,
                                key=full_key(row), unsubscribe=seat_stop_href()))
    _send_notes("Full League Pass claims", messages)


def seat_confirmation_key(request: PendingSeat) -> str:
    """Send-log key: ONE confirmation per claim, ever, and no address in it."""
    who = hashlib.sha256(request.email.encode("utf-8")).hexdigest()[:8]
    return (f"seat-confirm-{who}-"
            f"{hashlib.sha256(request.code.encode('utf-8')).hexdigest()[:10]}")


def _send_seat_confirmations(awaiting: list[PendingSeat], data) -> None:
    """One confirmation per claim, ever, to the CLAIMED address only — the
    one inbox that can turn the claim into a seat (OPS-R1)."""
    if not awaiting:
        return
    from render.report import seat_stop_href
    from render.seat_claim import confirm_email
    from run.delivery import Message
    from run.updates import seat_confirm_url
    site = os.environ.get("SITE_URL", "")
    if not site:
        print(f"Seat confirmations: {len(awaiting)} pending — SITE_URL is not "
              f"set, so none were sent.")
        return
    names = getattr(data, "players", None) if data is not None else None
    messages = []
    for request in awaiting:
        ids = decode_roster(request.ref).player_ids
        listed = [names.name(pid) for pid in ids] if names is not None else []
        subject, html, text = confirm_email(seat_confirm_url(site, request.code),
                                            listed, change=request.change)
        messages.append(Message(to=request.email, subject=subject, html=html,
                                text=text, key=seat_confirmation_key(request),
                                unsubscribe=seat_stop_href()))
    _send_notes("Seat confirmations", messages)


def registry_plan(purchase: str) -> tuple[str, str | None]:
    """A purchase's plan word -> (the registry row's ``plan``, its ``billing``).

    LEAGUE_PASS on a registry row means a SEAT, not a payer: a pass payer is an
    ordinary subscriber who also covers other people, and recording them as a
    seat would demand a covered_by they do not have and fail the load. So the
    payer is a "season" row whose BILLING is the pass (LP-D3) — before that
    field, the payer and every monthly buyer were flattened to "season" and
    told at the season's end that a season pass renews once a year."""
    if purchase == "seat":
        return LEAGUE_PASS, None
    if purchase == MONTHLY:
        return MONTHLY, MONTHLY
    if purchase == LEAGUE_PASS:
        return SEASON, PASS_BILLING
    return SEASON, SEASON


def _purchase_day(seen_at: str) -> str | None:
    """Stripe's `created` (epoch seconds, as a string) -> YYYY-MM-DD in UTC."""
    if not str(seen_at).isdigit():
        return None
    return datetime.fromtimestamp(int(seen_at), tz=timezone.utc).date().isoformat()


def to_rows(signups: Iterable[RosterSignup]) -> list[dict]:
    """The on-disk shape run/rosters.py validates."""
    rows: list[dict] = []
    for signup in signups:
        roster = signup.roster()
        plan, billing = registry_plan(signup.plan)
        day = _purchase_day(signup.seen_at)
        rows.append({
            "email": signup.email,
            "ref": signup.ref,
            "player_ids": list(roster.player_ids),
            "slots": list(roster.slots),
            "scoring": roster.scoring,
            # From the REF, not the dataclass default: the picker collects the
            # size and the ref now carries it, and reading the default here
            # would silently re-impose 12 on everybody (the bug this fixed).
            "league_size": roster.league_size,
            "label": signup.label,
            "plan": plan,
            "billing": billing,
            # Contract C3: the roster in use was set when it was bought, until
            # a confirmed update moves it (run/updates.apply_updates).
            **({"roster_as_of": day} if day else {}),
            **({"stripe_customer_id": signup.stripe_customer_id}
               if signup.stripe_customer_id else {}),
            # A row merged from several purchases of one roster keeps the
            # oldest one's slug (merge_same_roster), which its ref no longer
            # digests to.
            **({"origin": signup.origin} if signup.origin else {}),
            # A pass payer's row names its pass, so Tuesday counts its seats
            # and signs its seat link per pass (LP2-D4).
            **({"pass_id": signup.pass_of}
               if billing == PASS_BILLING and signup.pass_of else {}),
        })
    return rows


def write_registry(rows: list[dict], path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(rows, indent=1), encoding="utf-8")


# --------------------------------------------------------------------- #
# the welcome email
# --------------------------------------------------------------------- #

def pass_seat_link(signup: RosterSignup) -> str | None:
    """The one link a League Pass payer shares (contract C4), or None when
    the site or the signing secret is missing — then the welcome keeps the
    generic link and the "tell them your email" instruction."""
    if signup.plan != LEAGUE_PASS or not signup.subscription_id:
        # A pass with no subscription can carry no seat (RULE E2): a link
        # printed for it would match nothing, so the welcome keeps the generic
        # route rather than a dead one.
        return None
    return seat_url(os.environ.get("SITE_URL", ""),
                    os.environ.get("UPDATE_SECRET", ""), signup.email,
                    signup.roster(), pass_id=signup.subscription_id)


def _welcome(signup: RosterSignup, season: str, duplicate: str | None = None):
    """One signup's acknowledgment. A pass payer's carries their seat link
    when there is one; a purchase of a roster the address already holds
    another subscription for says so (``duplicate``, LP2-D1). Each keyword is
    passed only when it applies, so every other purchase calls exactly what
    it always called."""
    extra = {}
    link = pass_seat_link(signup)
    if link:
        extra["seat_link"] = link
    if duplicate:
        extra["duplicate"] = duplicate
    return welcome_message(signup.email, signup.plan, signup.slug, season,
                           purchased_at=str(signup.seen_at or ""), **extra)


def _send_welcomes(servable: list[RosterSignup], seats: list[RosterSignup],
                   season: str,
                   duplicates: Mapping[tuple[str, str], str] | None = None) -> None:
    """One acknowledgment per subscription, idempotent forever.

    Built from the SIGNUPS rather than the registry rows, because the registry
    deliberately flattens a League Pass payer to a season row — and the renewal
    terms in the email must describe the purchase that actually happened. A
    $99 payer welcomed with $39 renewal terms is a wrong legal disclosure.

    A seat is keyed on the slug it was FIRST claimed under and the moment of
    that claim, so a re-claim with a new roster (LP-D4) is never a second
    welcome, and a season roll — seat rows are rebuilt from the Worker every
    run — never re-welcomes anybody.

    Every PURCHASE is welcomed, including one merged into another's report
    (merge_same_roster): the acknowledgment is owed per subscription, and the
    newer one is where the person learns they hold two (``duplicates``).
    """
    messages = [_welcome(s, season, (duplicates or {}).get(s.key))
                for s in [*servable, *seats]]
    if not messages:
        return

    provider = build_provider(None)
    implicit_dry = (provider.name == DRY_PROVIDER
                    and not os.environ.get("EMAIL_PROVIDER"))
    if implicit_dry:
        print(f"Welcomes: {len(messages)} pending — EMAIL_PROVIDER is not set, "
              f"so none were sent and none were recorded. They send on the "
              f"first configured run; nobody is welcomed twice.")
        return
    sends = send_all(messages, provider=provider)
    delivered = [r for r in sends if r.ok and not r.skipped]
    failures = [r for r in sends if not r.ok]
    skipped = len(sends) - len(delivered) - len(failures)
    print(f"Welcomes via {provider.name}: {len(delivered)} sent, "
          f"{skipped} already sent, {len(failures)} failed")
    for result in failures:
        # Retries next run: only successes reach the sent log.
        print(f"    WELCOME FAILED {result.message.key}: {result.detail}",
              file=sys.stderr)


def _send_confirmations(awaiting: list[PendingRequest], data) -> None:
    """One confirmation per request, ever, to the address on the subscription
    only. The per-address daily allowance is applied where requests are
    validated (run/updates.py), so what arrives here is already bounded; the
    send-log key carries no date, so a request row that lives on in the Worker
    is never mailed twice. Idempotent through the send log like every message."""
    if not awaiting:
        return
    from render.roster_update import confirm_email
    from run.delivery import Message

    site = os.environ.get("SITE_URL", "")
    secret = os.environ.get("UPDATE_SECRET", "")
    if not site or not secret:
        print(f"Roster confirmations: {len(awaiting)} pending — SITE_URL or "
              f"UPDATE_SECRET is not set, so none were sent.")
        return
    names = getattr(data, "players", None) if data is not None else None
    messages = []
    for request in awaiting:
        from run.refs import decode_roster
        ids = decode_roster(request.ref).player_ids
        listed = [names.name(pid) for pid in ids] if names is not None else []
        subject, html, text = confirm_email(confirm_url(site, request.code), listed)
        messages.append(Message(to=request.email, subject=subject, html=html,
                                text=text, key=confirmation_key(request)))
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"Roster confirmations: {len(messages)} pending — EMAIL_PROVIDER "
              f"is not set, so none were sent.")
        return
    sends = send_all(messages, provider=provider)
    delivered = [r for r in sends if r.ok and not r.skipped]
    failures = [r for r in sends if not r.ok]
    print(f"Roster confirmations via {provider.name}: {len(delivered)} sent, "
          f"{len(failures)} failed")
    for result in failures:
        print(f"    CONFIRMATION FAILED {result.message.key}: {result.detail}",
              file=sys.stderr)


def _served_since_purchase(signup, entries: list[dict]) -> bool:
    """Has this subscription been sent a report since it was bought?

    The purchase log is EVERY signup ever, and the week's-report key is per
    week, so without this each hourly run from Monday night to kickoff mailed
    every subscriber that week's report ahead of the Tuesday run (review, Oct 9
    2026). A first email belongs to a PURCHASE: a weekly report, a final check
    or a roster report sent at or after the purchase means it was served. The
    welcome does not count (it goes out in the same run, just before). A
    re-purchase of the same roster is a new purchase: older sends predate it.
    """
    import re as _re
    slug = signup.slug
    shapes = (_re.compile(rf"^\d{{4}}-w\d\d-{slug}$"),
              _re.compile(rf"^\d{{4}}-w\d\d-final-{slug}$"),
              _re.compile(rf"^preseason-.*-{slug}$"))
    bought = (datetime.fromtimestamp(int(signup.seen_at), tz=timezone.utc)
              if str(signup.seen_at).isdigit() else None)
    for entry in entries:
        key = str(entry.get("key") or "")
        if not any(shape.match(key) for shape in shapes):
            continue
        if bought is None:
            return True                # no purchase time: any send counts
        try:
            at = datetime.fromisoformat(str(entry.get("sent_at") or ""))
        except ValueError:
            return True                # unreadable: err toward not re-sending
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= bought:
            return True
    return False


def _sent_entries() -> list[dict]:
    import run.delivery as delivery
    path = Path(delivery.SENT_LOG)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def subscriber_for(signup: RosterSignup):
    """The registry row a signup becomes, as a RosterSubscriber — the same
    plan/billing mapping ``to_rows`` writes, so a first report and every later
    Tuesday describe the same purchase (contract C1)."""
    from run.rosters import RosterSubscriber
    roster = signup.roster()
    plan, billing = registry_plan(signup.plan)
    return RosterSubscriber(
        email=signup.email, ref=signup.ref,
        player_ids=tuple(roster.player_ids), slots=tuple(roster.slots),
        scoring=roster.scoring, league_size=roster.league_size,
        plan=plan, billing=billing,
        covered_by=signup.covered_by if plan == LEAGUE_PASS else None,
        origin=signup.slug, roster_as_of=_purchase_day(signup.seen_at),
        pass_id=signup.pass_of if (plan == LEAGUE_PASS or billing == PASS_BILLING) else None,
        pass_customer=signup.pass_customer if plan == LEAGUE_PASS else None)


def _first_file(signup, data, season: str, processed_dir, record: bool = True,
                out_dir: Path | None = None, sent: set[str] | None = None,
                seat_counts: Mapping[str, int] | None = None,
                payers: Mapping[str, Any] | None = None):
    """The file a purchase earns, chosen by WHEN the purchase happened.
    -> the week's report as a ``run.tuesday.RunResult``, or None for the
    roster file.

    Pre-season, or mid-week: the roster file — byes, thin spots and last
    season's record under their own scoring. Facts only, no calls.

    Between Tuesday's send and that week's kickoff: the WEEK'S REPORT, the
    thing they actually paid for. A buyer on the Wednesday of week 6 should
    not wait six days to see the product.

    The line is kickoff, and it is an honesty line rather than a convenience
    one. Confidences are predictions about that week's games and the ledger
    records them as such (principle 2), so publishing a report after kickoff
    would put a "prediction" about a finished game on the public record. When
    in doubt week_has_kicked_off answers True, and they get the roster file.

    A week's report already in the send log (``sent``) is never rebuilt — the
    same rule as the Tuesday run: send_all would skip it, so the rebuild could
    only ever be a report nobody receives. The purchase gets the roster file.
    Nothing here touches the ledger: the caller records the calls once the
    message is delivered (``run.tuesday.record_delivered``).
    """
    from run.solo import week_has_kicked_off

    if getattr(data, "week", 1) > 1 and not week_has_kicked_off(
            CACHE_DIR, season, data.week):
        from run.tuesday import league_seat_link, report_key, run_subscriber
        if report_key(data.season, data.week, signup.slug) in (sent or set()):
            return None
        # The same plan/billing mapping the registry row gets, so the first
        # report and every Tuesday after it describe the same purchase.
        subscriber = subscriber_for(signup)
        template = (REPO_ROOT / "rival-report-template.html").read_text(
            encoding="utf-8")
        # record: a call is PUBLISHED when it reaches someone; a report that a
        # dry or unconfigured run will never send carries no calls at all (the
        # rule run/tuesday.py follows).
        from run.tuesday import SUBSCRIBER_REPORTS
        result = run_subscriber(subscriber, data, template,
                                out_dir=out_dir or SUBSCRIBER_REPORTS,
                                processed_dir=processed_dir, record=record,
                                seat_counts=seat_counts,
                                seat_link=league_seat_link(subscriber, payers or {}))
        if result.ok and result.message is not None:
            return result
        # Fall through to the roster file rather than sending nothing.
    return None


def _send_first_files(servable: list[RosterSignup], data, season: str,
                      processed_dir=None, first_plans: Path | None = None,
                      out_dir: Path | None = None,
                      seat_counts: Mapping[str, int] | None = None) -> None:
    """The file they get for paying, on the day they pay.

    The weekly product cannot say anything until box scores exist, so a buyer
    who signed up in draft season used to hold nothing for up to a fortnight.
    "I paid and got nothing" is the dominant refund driver at this size.

    One file per purchase, never two — three emails at once (welcome, roster
    file, weekly report) reads as a mailing list rather than a product.

    A League Pass SEAT is served by the same rules (LP-I4): a leaguemate who
    claims from the group chat on a Wednesday gets that week's report the same
    day, not next Tuesday, when the chat has moved on. Its "purchase" is the
    first claim, which is what the served-since check reads; its report and
    roster report carry the seat's stop route, never a billing page.
    """
    from engine.preseason import build_preseason_report, bye_by_team
    from render.preseason import preseason_message

    from run.tuesday import PROCESSED_DIR

    processed_dir = processed_dir or PROCESSED_DIR
    # The pass payers in hand, so a seat's report and a payer's carry their
    # league's own seat link with the payer's setup (contract C4) — keyed by
    # pass, as run/tuesday.py keys them (LP2-D4).
    payers = {}
    for signup in servable:
        if signup.plan == LEAGUE_PASS:
            payer = subscriber_for(signup)
            if payer.pass_key:
                payers[payer.pass_key] = payer
    # Only purchases that have not been served yet. Everyone else is the
    # Tuesday run's, which checks entitlement and reads the current roster.
    entries = _sent_entries()
    servable = [s for s in servable if not _served_since_purchase(s, entries)]
    if not servable:
        return
    if data is None:
        # Two very different states shared one silent return. Nobody to send to
        # is nothing to say; a paid signup we could not build a file for is the
        # promise on the pricing card ("your roster file lands the same day")
        # going unkept, and it deserves a sentence. It self-heals on the next
        # hourly run, so this is a note rather than a failure — but a silence
        # nobody can see is how a run quietly stops delivering.
        print(f"First files: skipped for {len(servable)} paid signup(s) — this "
              f"week's data could not be loaded. They send on the next run.",
              file=sys.stderr)
        return
    try:
        byes = bye_by_team(CACHE_DIR, season)
    except Exception as exc:  # noqa: BLE001
        print(f"First files: skipped, the {season} schedule could not be read "
              f"({exc})", file=sys.stderr)
        return

    # Decided BEFORE anything is built, because it decides whether a week's
    # report built here may ever enter the public record.
    provider = build_provider(None)
    sending = not (provider.name == DRY_PROVIDER)
    sent = {str(entry.get("key") or "") for entry in entries}
    messages, plans, weeklies = [], {}, []
    for signup in servable:
        try:
            weekly = _first_file(signup, data, season, processed_dir, record=sending,
                                 out_dir=out_dir, sent=sent, seat_counts=seat_counts,
                                 payers=payers)
            if weekly is not None:
                messages.append(weekly.message)
                weeklies.append(weekly)
                if weekly.plan is not None:
                    plans[weekly.message.key] = weekly.plan
                continue
            roster = signup.roster()
            spec = spec_from_ref(roster)
            report = build_preseason_report(
                spec, data.directory, data.prior, season, CACHE_DIR,
                season_started=getattr(data, "week", 1) > 1, byes=byes,
                # The week this run already derived, so the roster report's
                # "weeks ahead" and this run agree on what "now" is.
                from_week=getattr(data, "week", None))
            # A seat's roster report must carry the seat's stop route, not the
            # billing page a seat has no account on (render.preseason's
            # `seat`); only a seat passes the keyword.
            extra = {"seat": True} if signup.plan == "seat" else {}
            messages.append(preseason_message(
                signup.email, signup.slug, report,
                purchased_at=str(signup.seen_at or ""), **extra))
        except Exception as exc:  # noqa: BLE001 — batch contract
            print(f"    FIRST FILE FAILED for {signup.slug}: {exc!r}",
                  file=sys.stderr)
    if not messages:
        return

    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"First files: {len(messages)} pending — EMAIL_PROVIDER is not "
              f"set, so none were sent and none were recorded.")
        return
    sends = send_all(messages, provider=provider)
    delivered = [r for r in sends if r.ok and not r.skipped]
    failures = [r for r in sends if not r.ok]
    print(f"First files via {provider.name}: {len(delivered)} sent, "
          f"{len(sends) - len(delivered) - len(failures)} already sent, "
          f"{len(failures)} failed")
    # A week's report mailed today publishes its calls — so they reach the
    # ledger now, for the messages that were DELIVERED and no others (the
    # Tuesday run's rule, in its one copy). Recording at build time put a
    # report that a failed or skipped send never delivered on the record.
    if sending and weeklies:
        from run.tuesday import record_delivered
        added, problems = record_delivered(
            weeklies, [r.message.key for r in delivered], processed_dir)
        if added:
            print(f"    {added} new ledger row(s) from this week's reports")
        for problem in problems:
            print(f"    LEDGER RECORD FAILED {problem}", file=sys.stderr)
    # A week's report mailed today is what Saturday's final check and next
    # week's receipts must read, exactly as sent — so its plan is stored only
    # for a send that really happened, the same rule run/tuesday.py follows.
    if sending and first_plans is not None:
        from run.saturday import write_plan
        for result in delivered:
            plan = plans.get(result.message.key)
            if plan is None:
                continue
            try:
                write_plan(first_plans, plan)
            except OSError as exc:
                print(f"    plan not saved for {result.message.key}: {exc}",
                      file=sys.stderr)
    for result in failures:
        print(f"    FIRST FILE SEND FAILED {result.message.key}: {result.detail}",
              file=sys.stderr)


def _live_passes(signups: Iterable[RosterSignup], api_key: str) -> list[PassInfo]:
    """The League Passes in the log, marked entitled from Stripe's live answer
    (RULE E2). Asked only when there are passes to ask about; raises
    SubscriptionError when Stripe cannot say."""
    passes = [s for s in signups if s.plan == LEAGUE_PASS and s.subscription_id]
    if not passes:
        return []
    from run.subscriptions import load_paid_from_stripe
    paid = load_paid_from_stripe(api_key)
    return pass_infos(passes, paid.subscription_ids or ())


def _season_from(cache: Path, season: str) -> datetime | None:
    """The first moment a seat claim belongs to ``season``: the day after the
    previous season's last regular-season game (UTC). A claim made in August
    is this season's; one made last October is last season's, which ended
    with its Week 18 report ("claim your seat again next season", LP2-D3).
    None when the schedule cannot say — then no claim is retired, and the
    run says so rather than guessing."""
    if not str(season).isdigit():
        return None
    try:
        from run.solo import season_ends
        end = season_ends(cache, live=False).get(str(int(season) - 1))
    except Exception:  # noqa: BLE001 — a missing schedule retires nothing
        end = None
    if not end:
        print(f"Seats: the {int(season) - 1} season's end could not be read, so "
              f"no claim was retired as last season's this run.", file=sys.stderr)
        return None
    day = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    return day + timedelta(days=1)


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-dir", type=Path, default=REGISTRY_DIR,
                        help="where the log, watermark and registry live")
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change; write nothing, stamp nothing")
    parser.add_argument("--full", action="store_true",
                        help="ignore the watermark and sweep every session")
    parser.add_argument("--clear-unresolved", action="store_true",
                        help="forget the payments reported every run as unattributable")
    parser.add_argument("--no-mail", action="store_true",
                        help="write the registry and send nothing (the Tuesday "
                             "run's intake; the daily run does the mailing)")
    args = parser.parse_args(argv)

    api_key = os.environ.get("STRIPE_API_KEY", "")
    if not api_key:
        # EXIT 2, not 1. Before checkout opens this is the EXPECTED state — the
        # picker says so too — and a cron that files a bug issue every week for
        # it teaches you to ignore bug issues, which is how the real one gets
        # missed. Exit 1 stays reserved for "something is wrong": a paid signup
        # we cannot serve, or a Stripe read that failed.
        print("STRIPE_API_KEY is not set — nothing to sweep. That is expected "
              "until checkout opens; set the secret to start attributing "
              "payments.", file=sys.stderr)
        return NOT_CONFIGURED

    registry_dir = Path(args.registry_dir)
    log_path = registry_dir / SIGNUP_LOG_NAME
    state_path = registry_dir / STATE_NAME
    registry_path = registry_dir / REGISTRY_NAME

    state = read_state(state_path)
    since = None if args.full else state.get("watermark")
    link_plans = parse_link_plans(os.environ.get("STRIPE_PAYMENT_LINKS", ""))

    try:
        swept, newest, problems = sweep(api_key, since if isinstance(since, int) else None,
                                        link_plans, promote=not args.dry_run)
    except SubscriptionError as exc:
        print(f"could not read Stripe: {exc}", file=sys.stderr)
        return 1

    # Unattributable payments PERSIST. The watermark moves past the session
    # within days, so a once-only message meant the third run forgot a customer
    # who is still being charged.
    remembered = [] if args.clear_unresolved else list(state.get("unresolved") or [])
    for problem in problems:
        if problem.startswith("PAID-UNATTRIBUTED") and problem not in remembered:
            remembered.append(problem)

    added = 0 if args.dry_run else append_log(swept, log_path)
    log = load_log(log_path) if not args.dry_run else [*load_log(log_path), *swept]
    projected = project(log)

    # Can we serve them? The directory is the same one the picker published, so
    # a ref that resolved in the browser resolves here — unless it was hand-made.
    blocked: dict[tuple[str, str], str] = {}
    known: set[str] = set()
    known_season = str(datetime.now(timezone.utc).year)
    # Bound before the try: the except below is not fatal, so `data` has to
    # exist either way for the senders that read it.
    data = None
    try:
        data = load_week_data(args.cache)
        known = {player.player_id for player in data.directory.players}
        known_season = str(getattr(data, "season", known_season))
        blocked = unservable(projected, known)
    except SoloError as exc:
        # Not fatal: refusing to write a registry because a data release is
        # briefly unavailable would strand every paid signup for a week.
        problems.append(f"could not check rosters against the directory ({exc}) "
                        f"— rows were written unchecked")

    servable = [s for s in projected if s.key not in blocked]
    # One address, one roster, one report (LP2-D1): an upgrade to the League
    # Pass, or a second purchase of the same roster, is written as ONE row.
    # Every purchase is still welcomed (`servable`); the registry and the
    # first report read the merged list.
    merged = merge_same_roster(servable)

    # League Pass SEATS. The only signups with no payment behind them, and the
    # only external dependency in this pipeline — so a vendor outage costs
    # seats, never sales. FORM_ENDPOINT is empty by PLAN §0 decision until a
    # validated backend exists, and empty means the tier simply does not
    # deliver seats rather than delivering unpaid ones.
    seat_rows: list[dict] = []
    seats = SeatSweep()
    update_rows: list[dict] = []
    request_rows: list[dict] = []
    confirm_rows: list[dict] = []
    secret = os.environ.get("UPDATE_SECRET", "")
    seat_log_path = registry_dir / SEAT_LOG_NAME
    seat_endpoint = os.environ.get("FORM_ENDPOINT", "")
    if seat_endpoint:
        try:
            form_rows = fetch_seats(seat_endpoint, os.environ.get("FORM_API_KEY"))
        except IntakeError as exc:
            # Refuse rather than writing a Stripe-only registry: that would
            # silently drop every seat and read as a quiet week.
            print(f"could not read the seat backend: {exc}", file=sys.stderr)
            print("  Refusing to write a registry that would drop every League "
                  "Pass seat. Fix the backend, or unset FORM_ENDPOINT to run "
                  "without seats deliberately.", file=sys.stderr)
            return 1
        # One backend, several kinds of row: a seat claim (the default, for
        # rows written before updates existed), roster updates and requests,
        # and the confirm page's codes — which confirm seat claims and roster
        # requests alike, each code meaning something to exactly one of them.
        claims = [r for r in form_rows if str(r.get("kind") or "seat") == "seat"]
        update_rows = [r for r in form_rows if str(r.get("kind") or "") == "update"]
        request_rows = [r for r in form_rows
                        if str(r.get("kind") or "") == "update_request"]
        confirm_rows = [r for r in form_rows if str(r.get("kind") or "") == "confirm"]
        seat_log = load_seat_log(seat_log_path)
        try:
            passes = _live_passes(servable, api_key) if (claims or seat_log) else []
        except SubscriptionError as exc:
            # Which passes are active is the whole seat question (RULE E2).
            # Unanswerable, the run refuses rather than serving seats on a
            # refunded pass — or dropping every seat on a paid one.
            print(f"could not read which League Passes are active: {exc}",
                  file=sys.stderr)
            print("  Refusing to write a registry that would serve or drop "
                  "League Pass seats on a guess.", file=sys.stderr)
            return 1
        from run.updates import signing_secrets
        seats = sweep_seats(
            claims, passes, known or None,
            signing_secrets(secret, os.environ.get("UPDATE_SECRET_PREVIOUS", "")),
            confirm_codes=confirm_rows,
            log=seat_log, now=datetime.now(timezone.utc),
            season_from=_season_from(args.cache, known_season))
        seat_rows = seats.rows
        problems.extend(seats.problems)
        if not args.dry_run:
            append_seat_log(seats.confirmed, seat_log_path)
        # Counted, so a run where claims are going nowhere is visible in the
        # log; each claimer is told by email.
        print(f"Seats: {len(seat_rows)} served; {len(seats.confirmed)} newly "
              f"confirmed; {len(seats.awaiting)} claim(s) mailed a confirmation; "
              f"{seats.reclaimed} with a confirmed new roster (one seat each, "
              f"the newest stands); {len(seats.unmatched)} matched no League "
              f"Pass; {seats.overflow} past a full pass; {seats.lapsed} on a pass "
              f"not active now; {seats.retired} from an earlier season")

    candidate = to_rows(merged.signups) + seat_rows

    # Self-serve roster UPDATES (run/updates.py). Validated against the rows
    # about to be written — a subscriber can only change a roster they hold —
    # and authenticated by the token that reaches them inside their own
    # reports. Logged on first sight so the order is ours, not the form's.
    update_log_path = registry_dir / UPDATE_LOG_NAME
    validated, update_problems = validate_updates(
        update_rows, candidate, known or None, secret)
    problems.extend(update_problems)
    # Confirm-by-email requests (run/updates.py): a request only ever becomes
    # an update once its code has come back from the subscriber's own inbox.
    # Requests are judged against the roster AS IT NOW STANDS — updates already
    # logged (and this run's token updates) applied first — so "nothing would
    # change" and "revert to what I had" mean what they say, and a request that
    # was already applied is dead (single-use).
    base_log = [*load_update_log(update_log_path), *validated]
    # A seat re-claimed through its link after an update was logged: the
    # claim is the newer roster, and the older update must not undo it.
    current, _ = apply_updates(candidate, latest_per_target(base_log),
                               since=seats.last_claimed)
    pending, request_problems = validate_requests(
        request_rows, current, known or None, secret,
        applied=applied_request_ts(base_log))
    problems.extend(request_problems)
    confirmed = confirmed_updates(pending, confirm_rows, secret)
    validated = [*validated, *confirmed]
    confirmed_codes = {u.nonce for u in confirmed}
    awaiting = [p for p in pending if p.code not in confirmed_codes]
    if not args.dry_run:
        append_update_log(validated, update_log_path)
        update_log = load_update_log(update_log_path)
    else:
        update_log = [*load_update_log(update_log_path), *validated]
    candidate, applied = apply_updates(candidate, latest_per_target(update_log),
                                       since=seats.last_claimed)
    if update_rows or request_rows or applied:
        print(f"Updates: {applied} roster(s) changed; {len(pending)} request(s) "
              f"valid, {len(confirmed)} confirmed, {len(awaiting)} awaiting "
              f"confirmation")

    # A PAYMENT ALWAYS BEATS AN UNPAID CLAIM. Someone who bought their own
    # subscription must not have it replaced by a seat row naming them.
    # drop_unloadable resolves that collision in the payer's favour in EITHER
    # order — verified by mutation, because the first version of this comment
    # claimed the ordering was load-bearing and it is not.
    rows, dropped = drop_unloadable(candidate)
    # Every servable signup being dropped is a bug in what we write, not a
    # business that lost all its customers — and writing an empty registry over
    # a good one, then exiting 0, is the failure nobody notices until Tuesday.
    wiped = bool(servable) and not rows
    # The module contract says exit 1 means "a paid signup we cannot serve, or
    # a Stripe read that failed". `blocked` covered only unservable ROSTERS, so
    # every PAID-UNATTRIBUTED payment — a completed, paid session with no
    # reference, an unreadable ref, or no address to send to — printed its own
    # sentence saying "somebody has paid and will receive nothing" and then
    # exited 0. Both crons gate their failure step on code == 1, and daily.yml
    # files the issue only on failure, so the customer was charged, undeliverable
    # and invisible: green cron, no alarm. Found Aug 24 2026.
    # `remembered` counts too — an unresolved payment stays unresolved until a
    # human clears it, and a re-run that goes green is how it gets forgotten.
    unattributed = [p for p in list(problems) + list(remembered)
                    if str(p).startswith("PAID-UNATTRIBUTED")]

    line = "=" * 62
    print(f"\n{line}\nROSTER INTAKE{' (dry run)' if args.dry_run else ''}\n{line}")
    print(f"Swept {len(swept)} roster payment(s); {added} new log event(s)")
    print(f"Registry: {len(rows)} subscriber(s)")
    for signup in servable:
        print(f"  [ok ] {signup.slug}: {signup.plan}")
    for (_email, ref), reason in sorted(blocked.items()):
        print(f"  [BLOCKED] {ref[:12]}…: {reason} — this person has PAID and "
              f"will receive nothing until it is fixed", file=sys.stderr)
    for problem in problems:
        print(f"  ! {_no_email(problem)}", file=sys.stderr)
    for note in dropped:
        print(f"  ! {_no_email(note)}", file=sys.stderr)
    for problem in remembered:
        if problem not in problems:
            print(f"  ! (still open) {_no_email(problem)}", file=sys.stderr)

    # One customer holding several subscriptions is legitimate (two teams) and
    # is also what a roster CHANGE looks like, because re-running the picker
    # builds a new ref and only a new payment carries it here. Say so rather
    # than silently picking one.
    by_customer: dict[str, list[RosterSignup]] = {}
    for signup in merged.signups:
        if signup.stripe_customer_id:
            by_customer.setdefault(signup.stripe_customer_id, []).append(signup)
    for customer, held in sorted(by_customer.items()):
        if len(held) > 1:
            print(f"  NOTE: customer {customer} has {len(held)} rosters and will "
                  f"get {len(held)} reports. If one is a roster CHANGE rather "
                  f"than a second team, the older subscription keeps its report "
                  f"until it is cancelled in Stripe.")
    # LP2-D1: the same roster bought twice by one address is ONE report; the
    # other subscription still bills. Flagged here, and the newer purchase's
    # welcome tells the subscriber they can cancel it — nothing is cancelled
    # or refunded on anybody's behalf.
    for group in merged.groups:
        # group[0] is the oldest purchase, whose slug the one row keeps.
        print(f"  NOTE: one address holds {len(group)} subscriptions for one roster "
              f"({', '.join(s.plan for s in group)}) — one report a week, under "
              f"{group[0].slug}. The others keep billing until the subscriber "
              f"cancels them; their welcome says how. Nothing was cancelled or "
              f"refunded.")

    if wiped:
        print(f"REFUSING TO WRITE: all {len(servable)} servable signup(s) were "
              f"dropped as unloadable, which is a bug in what we write rather "
              f"than a week in which everybody cancelled. The existing registry "
              f"is untouched.", file=sys.stderr)
        return 1

    # A seat link that matches no pass at all is a signing secret gone wrong
    # (OPS-R10): every seat claim is going nowhere, and that must not be a
    # green cron.
    failing = bool(blocked or unattributed or seats.links_dead)
    if args.dry_run:
        print("(dry run — nothing written, no customer metadata stamped)")
        print(line)
        return 1 if failing else 0

    write_registry(rows, registry_path)

    # The welcome / acknowledgment email (render/welcome.py). Legally owed:
    # renewal terms and the cancel method, in a form the buyer keeps. Sent
    # through the same idempotent delivery layer as the reports, so a re-run
    # can never welcome anyone twice, and a failed send retries next run
    # because only successes are logged. With no provider configured this
    # reports what is pending rather than failing — the registry is this run's
    # contract.
    #
    # ONE intake mails: daily.yml's. The Tuesday job runs this too, with
    # --no-mail, because the two workflows sit in different concurrency groups
    # and each reads the send log from its own checkout — so a late GitHub
    # backup of the weekly run landing beside an hourly daily run mailed the
    # same buyer two welcomes and two first reports (reproduced, launch review
    # OPS-6). Everything here is keyed and retried, so the daily run's next
    # half-hour sends whatever this run leaves.
    if args.no_mail:
        print("Mail: none from this run (--no-mail). Welcomes, roster-update "
              "confirmations and first reports go out from the daily run.")
    else:
        # Seats as the registry now holds them — after the payment-beats-seat
        # collision and any update — so nobody is welcomed or sent a first
        # report for a seat that was not written.
        seat_signups = seat_signups_from(rows, seats.first_claimed)
        _send_welcomes(servable, seat_signups, known_season, merged.duplicates)
        _send_confirmations(awaiting, data)
        now = datetime.now(timezone.utc)
        _send_seat_confirmations(seats.awaiting, data)
        _send_unmatched_notes(seats.unmatched, now)
        _send_full_notes(seats.full, now)
        from run.saturday import FIRST_PLANS_NAME
        # The merged list: one first report per roster, never one per purchase
        # of it (LP2-D1).
        _send_first_files([*merged.signups, *seat_signups], data, known_season,
                          first_plans=registry_dir / FIRST_PLANS_NAME,
                          seat_counts=seat_counts(rows))
    if isinstance(newest, int):
        state["watermark"] = newest
    state["unresolved"] = remembered
    state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_state(state, state_path)
    try:
        load_rosters(registry_path)
    except RosterRegistryError as exc:
        # Written and unloadable is the worst outcome: every subscriber's
        # Tuesday is down and nothing said so until the run that mails them.
        print(f"WROTE AN UNLOADABLE REGISTRY: {exc}", file=sys.stderr)
        return 1
    print(f"Registry written: {registry_path}")
    if unattributed:
        print(f"{len(unattributed)} PAID payment(s) could not be attributed — "
              f"exiting non-zero so this is not a green cron.", file=sys.stderr)
    if seats.links_dead:
        print("League Pass seat links match no pass — exiting non-zero so this "
              "is not a green cron.", file=sys.stderr)
    print(line)
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
