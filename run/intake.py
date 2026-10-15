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
only when that address really bought a pass (``sweep_seats``). One seat per
(address, pass) — a re-claim is a roster change. A claim that matches no
pass is told so, once (LP-D1). A new seat gets its first email by the same
rules as a purchase (LP-I4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
from dataclasses import asdict, dataclass, field
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
    # A League Pass SEAT, never logged (seats are rebuilt from the form Worker
    # every run): who pays for it, and the slug it was first claimed under,
    # which a re-claim with a new roster does not move (LP-D4).
    covered_by: str | None = None
    origin: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.email.lower(), self.ref)

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
        signups.append(RosterSignup(
            email=email, ref=ref,
            # A pass PAYER is an ordinary subscriber of ours who also covers
            # other people; what makes their league's seats work is seats naming
            # their address, not anything stored on this row.
            plan=plan or "season",
            seen_at=str(created) if isinstance(created, int) else "",
            stripe_customer_id=customer, via=via))
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


def _received(row: Mapping) -> datetime | None:
    """The form Worker's own stamp on a row (a caller cannot set it), or None."""
    raw = str(row.get("received_at") or "").strip()
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


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
    # Seats whose roster a later claim replaced. Counted in the summary rather
    # than reported per seat: the claims live in the Worker for ~400 days, so
    # a per-seat line would repeat every hourly run as if it were news.
    reclaimed: int = 0


def sweep_seats(rows: Iterable[dict], pass_payers: set[str],
                known_ids: set[str] | None, secret: str = "") -> SeatSweep:
    """Validate seat claims into registry rows.

    ``pass_payers`` is the set of addresses that ACTUALLY BOUGHT a League Pass,
    built from sessions whose own `payment_link` was the pass link — never from
    what a seat claims. The seat form is public by necessity, so without that
    check it is a free-report generator for anyone who finds the URL.

    A claim names its pass one of two ways. The per-pass seat link (contract
    C4) carries ``pass_token``, recomputed here over those payers with
    ``secret`` and never trusted from the row. The older route has the
    leaguemate type the payer's address as ``covered_by``. Entitlement then
    flows through `covered_by`, which is what ``PaidList.entitles`` reads.

    ONE SEAT PER (address, pass) — LP-D4. The group-chat link is reusable, so a
    leaguemate who claims again after a trade used to get a SECOND seat and two
    weekly reports, old roster and new, with nothing said to anyone. A re-claim
    is now a roster change: the newest claim by the Worker's own stamp wins,
    and the seat keeps the slug it was FIRST claimed under (``origin``), so its
    send keys, its stored plans and its update link never move.

    ``known_ids`` is None when the directory could not be loaded at all. That
    must mean "not checked", never "nothing is known" — an empty set would
    reject every seat with a confident, wrong reason on the one day a data
    release is unavailable.
    """
    out = SeatSweep()
    by_token = ({seat_token(payer, secret): payer for payer in pass_payers}
                if secret else {})
    groups: dict[tuple[str, str], list[tuple[dict, Any]]] = {}
    # Oldest first by the Worker's stamp; a stable sort keeps the Worker's own
    # arrival order (its keys are timestamp-prefixed) for rows that tie.
    ordered = sorted(rows, key=lambda r: _received(r) or datetime.min.replace(
        tzinfo=timezone.utc))
    for row in ordered:
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
        try:
            roster = decode_roster(ref)
        except RefError as exc:
            out.problems.append(f"seat claim from {_no_email(email)} carries an "
                                f"unreadable roster ({exc})")
            continue
        payer = (by_token.get(token) if _SEAT_TOKEN.match(token)
                 else typed if typed in pass_payers else None)
        if payer is None:
            out.problems.append(
                f"seat claim from {_no_email(email)} "
                + ("carries a seat link that matches no League Pass"
                   if _SEAT_TOKEN.match(token) else
                   "names a payer with no League Pass")
                + " — not honoured")
            out.unmatched.append(row)
            continue
        if email == payer:
            # The commissioner already has their own paid row; a seat for
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
        groups.setdefault((email, payer), []).append((row, roster))

    for (email, payer), claims in groups.items():
        first, (latest, roster) = claims[0][0], claims[-1]
        origin = slug_of(str(first.get("ref")).strip())
        ref = str(latest.get("ref")).strip()
        if len({str(row.get("ref")).strip() for row, _ in claims}) > 1:
            out.reclaimed += 1
        claimed = _received(latest)
        out.rows.append({
            "email": email, "ref": ref,
            "player_ids": list(roster.player_ids), "slots": list(roster.slots),
            "scoring": roster.scoring, "league_size": roster.league_size,
            "label": "Your Team", "plan": LEAGUE_PASS, "covered_by": payer,
            "origin": origin,
            **({"roster_as_of": claimed.date().isoformat()} if claimed else {}),
        })
        for stamp, into in ((_received(first), out.first_claimed),
                            (claimed, out.last_claimed)):
            if stamp is not None:
                into[(email, origin)] = stamp
    return out


def seats_to_rows(rows: Iterable[dict], pass_payers: set[str],
                  known_ids: set[str] | None,
                  secret: str = "") -> tuple[list[dict], list[str]]:
    """``sweep_seats`` as (registry rows, problems)."""
    swept = sweep_seats(rows, pass_payers, known_ids, secret)
    return swept.rows, swept.problems


def seat_signups_from(rows: Iterable[Mapping],
                      first_claimed: Mapping[tuple[str, str], datetime],
                      ) -> list[RosterSignup]:
    """The seats a registry is about to hold, as signups for the mail a
    purchase gets (welcome, first report). Their "purchase" moment is the
    FIRST claim (the Worker's stamp), which keys both the welcome and the
    served-since check, so neither repeats when the roster moves (LP-D4)."""
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
            origin=origin))
    return out


def seat_counts(rows: Iterable[Mapping]) -> dict[str, int]:
    """payer address -> the seats their pass carries in this registry
    (contract C2: a count, never who)."""
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("plan") == LEAGUE_PASS and row.get("covered_by"):
            payer = str(row["covered_by"]).lower()
            counts[payer] = counts.get(payer, 0) + 1
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
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER and not os.environ.get("EMAIL_PROVIDER"):
        print(f"Unmatched seat claims: {len(messages)} note(s) pending — "
              f"EMAIL_PROVIDER is not set, so none were sent.")
        return
    sends = send_all(messages, provider=provider)
    delivered = [r for r in sends if r.ok and not r.skipped]
    failures = [r for r in sends if not r.ok]
    print(f"Unmatched seat claims via {provider.name}: {len(delivered)} note(s) "
          f"sent, {len(failures)} failed")
    for result in failures:
        print(f"    SEAT NOTE FAILED {result.message.key}: {result.detail}",
              file=sys.stderr)


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
    if signup.plan != LEAGUE_PASS:
        return None
    return seat_url(os.environ.get("SITE_URL", ""),
                    os.environ.get("UPDATE_SECRET", ""), signup.email,
                    signup.roster())


def _welcome(signup: RosterSignup, season: str):
    """One signup's acknowledgment. A pass payer's carries their seat link
    when there is one; the keyword is passed only then, so every other plan
    calls exactly what it always called."""
    extra = {}
    link = pass_seat_link(signup)
    if link:
        extra["seat_link"] = link
    return welcome_message(signup.email, signup.plan, signup.slug, season,
                           purchased_at=str(signup.seen_at or ""), **extra)


def _send_welcomes(servable: list[RosterSignup], seats: list[RosterSignup],
                   season: str) -> None:
    """One acknowledgment per subscription, idempotent forever.

    Built from the SIGNUPS rather than the registry rows, because the registry
    deliberately flattens a League Pass payer to a season row — and the renewal
    terms in the email must describe the purchase that actually happened. A
    $99 payer welcomed with $39 renewal terms is a wrong legal disclosure.

    A seat is keyed on the slug it was FIRST claimed under and the moment of
    that claim, so a re-claim with a new roster (LP-D4) is never a second
    welcome, and a season roll — seat rows are rebuilt from the Worker every
    run — never re-welcomes anybody.
    """
    messages = [_welcome(s, season) for s in [*servable, *seats]]
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
        origin=signup.slug, roster_as_of=_purchase_day(signup.seen_at))


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
    # league's own seat link with the payer's setup (contract C4).
    payers = {s.email.lower(): subscriber_for(s) for s in servable
              if s.plan == LEAGUE_PASS}
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
    seat_endpoint = os.environ.get("FORM_ENDPOINT", "")
    if seat_endpoint:
        # Built from what the LINK took, never from what a seat claims.
        pass_payers = {s.email.lower() for s in servable if s.plan == LEAGUE_PASS}
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
        # One backend, two kinds of row: a seat claim (the default, for rows
        # written before updates existed) and a roster update.
        claims = [r for r in form_rows if str(r.get("kind") or "seat") == "seat"]
        update_rows = [r for r in form_rows if str(r.get("kind") or "") == "update"]
        request_rows = [r for r in form_rows
                        if str(r.get("kind") or "") == "update_request"]
        confirm_rows = [r for r in form_rows if str(r.get("kind") or "") == "confirm"]
        seats = sweep_seats(claims, pass_payers, known or None, secret)
        seat_rows = seats.rows
        problems.extend(seats.problems)
        # Counted, so a run where claims are going nowhere is visible in the
        # log; each claimer is told by email (_send_unmatched_notes).
        print(f"Seats: {len(seat_rows)} honoured of {len(claims)} claim(s); "
              f"{seats.reclaimed} re-claimed with a new roster (one seat each, "
              f"the newest roster stands); {len(seats.unmatched)} matched no "
              f"League Pass")

    candidate = to_rows(servable) + seat_rows

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
    for signup in servable:
        if signup.stripe_customer_id:
            by_customer.setdefault(signup.stripe_customer_id, []).append(signup)
    for customer, held in sorted(by_customer.items()):
        if len(held) > 1:
            print(f"  NOTE: customer {customer} has {len(held)} rosters and will "
                  f"get {len(held)} reports. If that is a roster CHANGE rather "
                  f"than a second team, remove the old row by hand.")

    if wiped:
        print(f"REFUSING TO WRITE: all {len(servable)} servable signup(s) were "
              f"dropped as unloadable, which is a bug in what we write rather "
              f"than a week in which everybody cancelled. The existing registry "
              f"is untouched.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("(dry run — nothing written, no customer metadata stamped)")
        print(line)
        return 1 if (blocked or unattributed) else 0

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
        _send_welcomes(servable, seat_signups, known_season)
        _send_confirmations(awaiting, data)
        _send_unmatched_notes(seats.unmatched, datetime.now(timezone.utc))
        from run.saturday import FIRST_PLANS_NAME
        _send_first_files([*servable, *seat_signups], data, known_season,
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
    print(line)
    return 1 if (blocked or unattributed) else 0


if __name__ == "__main__":
    sys.exit(main())
