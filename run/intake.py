"""Payments become subscribers: the roster half of the signup pipeline.

Usage:
    python -m run.intake [--dry-run] [--full] [--registry-dir PATH]

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

**Known limitation, deliberate:** the key is (email, ref), so one purchase is one
subscription and a customer who buys twice gets two reports. There is no path
for a subscriber to CHANGE their roster mid-season — re-running the picker
builds a new ref, which only reaches here attached to a new payment. Reported
when it happens; a real fix needs a self-serve edit and belongs with the
customer portal, not here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from run.checkout import (CUSTOMERS_API, customer_id as _customer_id, is_paid,
                          parse_link_plans, post as _stripe_post,
                          session_email as _session_email, sweep_sessions)
from run.refs import (LEAGUE_PASS, RefError, RosterRef, decode_roster,
                      is_roster_ref)
from run.updates import (UPDATE_LOG_NAME, append_update_log, apply_updates,
                         latest_per_target, load_update_log, validate_updates)
from run.rosters import (_EMAIL_RE, RosterRegistryError, drop_unloadable,
                         load_rosters)
from render.welcome import welcome_message
from run.delivery import DRY_PROVIDER, build_provider, send_all
from run.solo import CACHE_DIR, SoloError, load_week_data
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

    @property
    def key(self) -> tuple[str, str]:
        return (self.email.lower(), self.ref)

    @property
    def slug(self) -> str:
        import hashlib
        return hashlib.sha256(self.ref.encode("utf-8")).hexdigest()[:10]

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
            stripe_customer_id=customer))
        if promote and customer and customer not in promoted:
            promoted.add(customer)
            try:
                _promote(api_key, customer, ref, plan or "season")
            except SubscriptionError as exc:
                # Promotion is a durability optimisation, not the signup — the
                # signup is already in hand.
                problems.append(f"could not stamp customer {customer}: {exc}")
    return signups, newest, problems


def _promote(api_key: str, customer: str, ref: str, plan: str) -> None:
    """Copy the roster onto the Customer, where it lives as long as they do.

    Stripe documents no retention guarantee for old Checkout Sessions, so this
    caps our dependence on session listability at one week instead of a season.
    Metadata writes MERGE, so this is additive and idempotent.
    """
    _stripe_post(f"{CUSTOMERS_API}/{urllib.parse.quote(customer)}", api_key,
                 {f"metadata[{META_REF}]": ref, f"metadata[{META_PLAN}]": plan})


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


def seats_to_rows(rows: Iterable[dict], pass_payers: set[str],
                  known_ids: set[str] | None) -> tuple[list[dict], list[str]]:
    """Validate seat claims into registry rows.

    ``pass_payers`` is the set of addresses that ACTUALLY BOUGHT a League Pass,
    built from sessions whose own `payment_link` was the pass link — never from
    what a seat claims. The seat form is public by necessity, so without that
    check it is a free-report generator for anyone who finds the URL.

    Under the roster architecture there is no league id to match a seat against.
    The seat holder types their commissioner's address, and entitlement flows
    through `covered_by` — which is what ``PaidList.entitles`` already reads.

    ``known_ids`` is None when the directory could not be loaded at all. That
    must mean "not checked", never "nothing is known" — an empty set would
    reject every seat with a confident, wrong reason on the one day a data
    release is unavailable.
    """
    out: list[dict] = []
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        payer = str(row.get("covered_by") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        # Validated to run/rosters.py's own standard HERE, because this endpoint
        # is public and the registry loader fails the WHOLE file on one bad row.
        # Accepting "not an email" would let any stranger stop every
        # subscriber's Tuesday.
        if not _EMAIL_RE.match(email) or not _EMAIL_RE.match(payer):
            problems.append("a seat claim arrived with unusable addresses")
            continue
        if payer not in pass_payers:
            problems.append(
                f"seat claim from {_no_email(email)} names a payer with no "
                f"League Pass — not honoured")
            continue
        if email == payer:
            # The commissioner already has their own paid row; a seat for
            # themselves would be a second report for one purchase.
            problems.append(
                f"seat claim from {_no_email(email)} names ITSELF as the payer "
                f"— the pass buyer already has their own subscription")
            continue
        try:
            roster = decode_roster(ref)
        except RefError as exc:
            problems.append(f"seat claim from {_no_email(email)} carries an "
                            f"unreadable roster ({exc})")
            continue
        missing = ([pid for pid in roster.player_ids if pid not in known_ids]
                   if known_ids else [])
        if missing:
            problems.append(
                f"seat claim from {_no_email(email)} names {len(missing)} "
                f"player id(s) the directory does not have")
            continue
        if (email, ref) in seen:
            continue
        seen.add((email, ref))
        out.append({
            "email": email, "ref": ref,
            "player_ids": list(roster.player_ids), "slots": list(roster.slots),
            "scoring": roster.scoring, "league_size": roster.league_size,
            "label": "Your Team", "plan": LEAGUE_PASS, "covered_by": payer,
        })
    return out, problems


def to_rows(signups: Iterable[RosterSignup]) -> list[dict]:
    """The on-disk shape run/rosters.py validates."""
    rows: list[dict] = []
    for signup in signups:
        roster = signup.roster()
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
            # LEAGUE_PASS on a registry row means a SEAT, not a payer: a pass
            # payer is an ordinary subscriber who also covers other people, and
            # recording them as a seat would demand a covered_by they do not
            # have and fail the load.
            "plan": "season",
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

def _send_welcomes(servable: list[RosterSignup], seat_rows: list[dict],
                   season: str) -> None:
    """One acknowledgment per subscription, idempotent forever.

    Built from the SIGNUPS rather than the registry rows, because the registry
    deliberately flattens a League Pass payer to a season row — and the renewal
    terms in the email must describe the purchase that actually happened. A
    $99 payer welcomed with $39 renewal terms is a wrong legal disclosure.
    """
    import hashlib

    messages = [welcome_message(s.email, s.plan, s.slug, season)
                for s in servable]
    for row in seat_rows:
        slug = hashlib.sha256(row["ref"].encode("utf-8")).hexdigest()[:10]
        messages.append(welcome_message(row["email"], "seat", slug, season))
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
    update_rows: list[dict] = []
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
        seat_rows, seat_problems = seats_to_rows(claims, pass_payers,
                                                 known or None)
        problems.extend(seat_problems)
        print(f"Seats: {len(seat_rows)} honoured of {len(claims)} claim(s)")

    candidate = to_rows(servable) + seat_rows

    # Self-serve roster UPDATES (run/updates.py). Validated against the rows
    # about to be written — a subscriber can only change a roster they hold —
    # and authenticated by the token that reaches them inside their own
    # reports. Logged on first sight so the order is ours, not the form's.
    update_log_path = registry_dir / UPDATE_LOG_NAME
    validated, update_problems = validate_updates(
        update_rows, candidate, known or None, os.environ.get("UPDATE_SECRET", ""))
    problems.extend(update_problems)
    if not args.dry_run:
        append_update_log(validated, update_log_path)
        update_log = load_update_log(update_log_path)
    else:
        update_log = [*load_update_log(update_log_path), *validated]
    candidate, applied = apply_updates(candidate, latest_per_target(update_log))
    if update_rows or applied:
        print(f"Updates: {applied} roster(s) changed from {len(update_rows)} "
              f"update row(s)")

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
    # contract; the weekly and daily crons set EMAIL_PROVIDER.
    _send_welcomes(servable, seat_rows, known_season)
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
