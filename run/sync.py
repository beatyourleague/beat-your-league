"""Turn payments into a subscriber registry, with nobody in the loop.

Runs before ``run.batch`` every Tuesday:

    python -m run.sync            # then: python -m run.batch

What it does, in order:

1. **Sweep Stripe.** Lists completed Checkout Sessions since the last watermark
   and decodes each ``client_reference_id`` back into a signup (see run/refs.py).
   That reference was written by the picker in the buyer's browser, so the
   payment carries its own configuration and there is no second list.
2. **Promote to the customer.** Writes the picks onto the Stripe Customer as
   metadata. This matters: Stripe documents no retention guarantee for old
   Checkout Sessions, so depending on them for a whole season would be building
   on sand. After promotion we depend on session listability for one week.
3. **Read the seats.** League Pass seat-holders never pay, so no Stripe object
   can hold them — they come from one form backend. This is the only external
   dependency in the signup path, and it is deliberately the one that only
   affects seats.
4. **Verify against Sleeper.** Every new row is checked against live league
   data: does this user actually own a roster in this league, and is the rival
   a real, different team? A row that fails is quarantined, not shipped.
5. **Roll the season.** Sleeper mints a new league id every year while the old
   one keeps resolving forever, so a renewed subscriber would otherwise get a
   confident report about last season. Each entry is re-resolved from the
   subscriber's stable user id through the previous_league_id chain.
6. **Project the registry.** Writes ``data/registry/subscribers.json`` in the
   exact shape run/registry.py already validates. Nothing downstream — batch,
   render, delivery, ledger — learns where a signup came from.

Storage, all under the gitignored ``data/registry/``:
  signups.jsonl     append-only log of every signup event ever seen
  sync-state.json   the Stripe sweep watermark
  subscribers.json  the projection batch reads

The log is append-only and latest-wins per (league, user), which makes running
the picker again a rival CHANGE rather than a duplicate — the same property
that makes re-runs safe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ingest.sleeper import (SleeperClient, SleeperError, SleeperNotFound,
                            is_valid_league_id)
from run.refs import (LEAGUE_PASS, MONTHLY, SEASON, RefError, SignupRef, decode)
from run.subscriptions import PASS_LEAGUE_KEY, SubscriptionError, _stripe_get

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "data" / "registry"
SIGNUP_LOG = REGISTRY_DIR / "signups.jsonl"
SYNC_STATE = REGISTRY_DIR / "sync-state.json"
REGISTRY = REGISTRY_DIR / "subscribers.json"
RAW_DIR = REPO_ROOT / "data" / "raw"

SESSIONS_API = "https://api.stripe.com/v1/checkout/sessions"
CUSTOMERS_API = "https://api.stripe.com/v1/customers"

# Customer-metadata keys. Namespaced to never collide with the operator's own.
META_USER = "byl_user"
META_LEAGUE = "byl_league"
META_RIVAL = "byl_rival"
META_PLAN = "byl_plan"

# Which plan each payment-link prefix in STRIPE_PAYMENT_LINKS means. This map is
# the ONLY thing allowed to grant a League Pass — see the AUTHORITATIVE PLAN
# comment in sweep_stripe for why the ref's own prefix cannot be trusted.
_PREFIX_PLANS = {"s": SEASON, "m": MONTHLY, "p": LEAGUE_PASS}

# How far back to re-read on every sweep, on top of the watermark. Stripe orders
# by creation and we advance the watermark to the newest session we saw, so a
# little overlap costs one extra page and protects against clock skew and
# sessions that complete out of order. Re-reading is free: the log is
# latest-wins keyed on (league, user), so seeing a signup twice is a no-op.
WATERMARK_SLACK_SECONDS = 3 * 24 * 3600


class SyncError(RuntimeError):
    """The sync cannot produce a trustworthy registry, so it must not write one."""


@dataclass
class Signup:
    """One signup event, as stored in the append-only log."""
    email: str
    user_id: str
    league_id: str
    rival_owner_id: str | None
    rival_roster_id: int | None
    plan: str                        # registry plan: season | league_pass
    source: str                      # stripe | form
    seen_at: str                     # Stripe/form timestamp, never our clock
    sleeper_username: str | None = None
    covered_by: str | None = None
    stripe_customer_id: str | None = None
    pass_league_id: str | None = None  # set when this purchase covers a league

    @property
    def key(self) -> tuple[str, str]:
        return (self.league_id, self.user_id)


# --------------------------------------------------------------------- #
# the append-only log
# --------------------------------------------------------------------- #

def load_log(path: Path = SIGNUP_LOG) -> list[Signup]:
    """Every signup ever seen, oldest first. A corrupt line is skipped loudly
    rather than failing the run — one bad line must not cost everyone their
    Tuesday, but it must never pass silently either."""
    if not path.is_file():
        return []
    out: list[Signup] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            out.append(Signup(**record))
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"  WARNING: {path.name} line {number} is unreadable and was "
                  f"skipped ({exc}). That subscriber will be missing until it "
                  f"is fixed or they sign up again.", file=sys.stderr)
    return out


def append_log(signups: Iterable[Signup], path: Path = SIGNUP_LOG) -> int:
    """Append new events. Never rewrites history — a signup log that can be
    edited in place is one where a lost row looks like a row that never was."""
    signups = list(signups)
    if not signups:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for signup in signups:
            fh.write(json.dumps(asdict(signup), sort_keys=True) + "\n")
    return len(signups)


def project(log: Iterable[Signup]) -> list[Signup]:
    """Latest-wins per (league, user).

    This is what makes re-running the picker a rival CHANGE instead of a
    duplicate registry entry — and what makes the whole sweep idempotent."""
    latest: dict[tuple[str, str], Signup] = {}
    for signup in log:
        latest[signup.key] = signup
    return list(latest.values())


def _read_state(path: Path = SYNC_STATE) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        # A lost watermark costs one full re-sweep, which is correct but slower.
        # Never fatal: the alternative is refusing to run over a cache file.
        return {}


def _write_state(state: dict[str, Any], path: Path = SYNC_STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------- #
# Stripe: completed checkouts -> signups
# --------------------------------------------------------------------- #

def _stripe_post(url: str, api_key: str, form: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Stripe-Version": "2024-06-20",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never echo the request — it carries the secret key.
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise SubscriptionError(
            f"Stripe returned HTTP {exc.code} writing customer metadata. The "
            f"restricted key needs WRITE access to Customers. Response: {detail}"
        ) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SubscriptionError(f"could not reach Stripe: {exc}") from None
    except json.JSONDecodeError:
        raise SubscriptionError("Stripe returned a response we could not read") from None


def _session_email(session: dict) -> str:
    """The address to mail. locked_prefilled_email means this equals the address
    typed into the picker, but we read Stripe's copy because Stripe is the one
    that actually took the money."""
    customer = session.get("customer")
    if isinstance(customer, dict) and not customer.get("deleted"):
        email = (customer.get("email") or "").strip().lower()
        if email:
            return email
    details = session.get("customer_details")
    if isinstance(details, dict):
        return (details.get("email") or "").strip().lower()
    return ""


def _customer_id(session: dict) -> str | None:
    customer = session.get("customer")
    if isinstance(customer, dict):
        cid = customer.get("id")
        return cid if isinstance(cid, str) and cid else None
    return customer if isinstance(customer, str) and customer else None


def parse_link_plans(raw: str) -> dict[str, str]:
    """``s:plink_A,m:plink_B,p:plink_C`` -> {link_id: plan}.

    This map is what makes the plan an authenticated fact instead of a claim.
    A bare ``plink_X`` with no prefix is accepted as a filter with an unknown
    plan, which is safe: it can never grant a League Pass.
    """
    out: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        prefix, _, link = item.partition(":")
        if link:
            plan = _PREFIX_PLANS.get(prefix.strip())
            if plan:
                out[link.strip()] = plan
        else:
            out[prefix] = ""          # filter only, plan unknown
    return out


def sweep_stripe(api_key: str, since: int | None = None,
                 link_plans: dict[str, str] | None = None,
                 promote: bool = True) -> tuple[list[Signup], int | None, list[str]]:
    """Completed Checkout Sessions -> signups, newest watermark, problems.

    Returns problems rather than raising them: one unreadable reference is a
    payment that needs a human, not a reason to deny everyone else their report.
    """
    signups: list[Signup] = []
    problems: list[str] = []
    newest = since
    promoted: set[str] = set()
    # One query per payment link, so a session could in principle be returned
    # twice; a duplicate signup is harmless (project() dedupes) but a duplicate
    # problem line is noise, and cheap insurance is cheaper than reasoning
    # about Stripe's filter semantics every time this is read.
    seen_sessions: set[str] = set()

    queries: list[dict[str, str]] = []
    base = {"status": "complete", "limit": "100", "expand[]": "data.customer"}
    if since is not None:
        base["created[gte]"] = str(max(0, since - WATERMARK_SLACK_SECONDS))
    for link in (list(link_plans or {}) or [None]):
        query = dict(base)
        if link:
            query["payment_link"] = link
        queries.append(query)

    for query in queries:
        url = f"{SESSIONS_API}?{urllib.parse.urlencode(query)}"
        while True:
            page = _stripe_get(url, api_key)
            data = page.get("data")
            data = data if isinstance(data, list) else []
            for session in data:
                if not isinstance(session, dict):
                    continue
                session_id = session.get("id")
                if isinstance(session_id, str):
                    if session_id in seen_sessions:
                        continue
                    seen_sessions.add(session_id)
                created = session.get("created")
                if isinstance(created, int):
                    newest = created if newest is None else max(newest, created)
                # A session can be status=complete and still unpaid when the
                # buyer used a delayed-notification method. Entitlement follows
                # the money, so an unpaid session is not a signup yet.
                status = session.get("payment_status")
                if status not in (None, "paid", "no_payment_required"):
                    continue
                ref = session.get("client_reference_id")
                if not ref:
                    # A payment with no reference: either it did not come
                    # through the picker, or Stripe dropped a malformed ref.
                    # Either way somebody paid and we cannot say for what.
                    problems.append(
                        f"session {session.get('id')} completed with NO reference "
                        f"({_session_email(session) or 'unknown email'}) — that "
                        f"person has paid and will receive nothing until this is "
                        f"resolved by hand")
                    continue
                try:
                    parsed = decode(ref)
                except RefError as exc:
                    problems.append(
                        f"session {session.get('id')}: unreadable reference "
                        f"{ref!r} ({exc}) — paid, undeliverable, needs a human")
                    continue
                email = _session_email(session)
                if not email:
                    problems.append(
                        f"session {session.get('id')}: no email on the payment, "
                        f"so there is nowhere to send the report")
                    continue
                customer_id = _customer_id(session)

                # AUTHORITATIVE PLAN. The ref's prefix is a string the buyer's
                # browser put in a URL, and every payment link is visible in
                # the page source — so trusting it means anyone can pay $9.99
                # on the monthly link with a "p-" ref and receive the $99
                # League Pass, for any league id they care to type. The plan
                # therefore comes from the link that actually took the money.
                paid_link = session.get("payment_link")
                paid_plan = (link_plans or {}).get(paid_link) if isinstance(paid_link, str) else None
                grants_pass = paid_plan == LEAGUE_PASS
                if parsed.is_league_pass and not grants_pass:
                    # Fail closed, and say which case it was: an unconfigured
                    # map is an operator problem, a mismatch is an attempt.
                    problems.append(
                        f"session {session.get('id')} ({email}) claims a League "
                        f"Pass but "
                        + ("no plan map is configured (set STRIPE_PAYMENT_LINKS), "
                           "so coverage was NOT granted"
                           if not link_plans else
                           f"it paid the {paid_plan or 'unknown'} link — coverage "
                           f"was NOT granted"))
                signups.append(Signup(
                    email=email,
                    user_id=parsed.user_id,
                    league_id=parsed.league_id,
                    rival_owner_id=parsed.rival_owner_id,
                    rival_roster_id=parsed.rival_roster_id,
                    plan=parsed.registry_plan,
                    source="stripe",
                    seen_at=str(created) if isinstance(created, int) else "",
                    stripe_customer_id=customer_id,
                    pass_league_id=parsed.league_id if grants_pass else None,
                ))
                if promote and customer_id and customer_id not in promoted:
                    promoted.add(customer_id)
                    try:
                        _promote(api_key, customer_id, parsed)
                    except SubscriptionError as exc:
                        # Promotion is a durability optimisation, not the
                        # signup itself — the signup is already in hand.
                        problems.append(
                            f"could not stamp customer {customer_id}: {exc}")
            last_id = data[-1].get("id") if data and isinstance(data[-1], dict) else None
            if not page.get("has_more") or not last_id:
                break
            url = (f"{SESSIONS_API}?{urllib.parse.urlencode(query)}"
                   f"&starting_after={urllib.parse.quote(str(last_id))}")
    return signups, newest, problems


def _promote(api_key: str, customer_id: str, ref: SignupRef) -> None:
    """Copy the picks onto the Customer, where they live for as long as the
    customer does. Metadata writes MERGE, so this is additive and idempotent."""
    form = {
        f"metadata[{META_USER}]": ref.user_id,
        f"metadata[{META_LEAGUE}]": ref.league_id,
        f"metadata[{META_RIVAL}]": ref.rival_owner_id or f"r{ref.rival_roster_id}",
        f"metadata[{META_PLAN}]": ref.plan,
    }
    _stripe_post(f"{CUSTOMERS_API}/{urllib.parse.quote(customer_id)}", api_key, form)


def stamp_pass_coverage(api_key: str, customer_id: str, league_id: str) -> None:
    """Record on the payer's customer that they cover a league.

    Deliberately NOT done during the sweep. This is the key run/subscriptions.py
    reads to answer "is this league covered", so writing it straight from a
    decoded reference would let an unverified claim grant twelve people a free
    product. It is written only after Sleeper confirms the payer really owns a
    roster in the league they are covering — and it lives on the customer, so
    coverage lapses exactly when their billing does.
    """
    _stripe_post(f"{CUSTOMERS_API}/{urllib.parse.quote(customer_id)}", api_key,
                 {f"metadata[{PASS_LEAGUE_KEY}]": league_id})


# --------------------------------------------------------------------- #
# form backend: League Pass seats (the only signups with no payment)
# --------------------------------------------------------------------- #

def fetch_seats(endpoint: str, api_key: str | None = None) -> list[dict]:
    """Read seat claims from the form backend.

    Deliberately one small function against a plain JSON endpoint: every hosted
    form vendor can produce one, and swapping vendors is this function, not an
    architecture. Returns raw rows; validation happens with everything else.
    """
    request = urllib.request.Request(endpoint, method="GET")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SyncError(f"form backend returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SyncError(f"could not reach the form backend: {exc}") from None
    except json.JSONDecodeError:
        raise SyncError("form backend returned something that is not JSON") from None
    # Accept the two shapes vendors actually return.
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("data") or payload.get("submissions") or payload.get("items") or []
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def seats_to_signups(rows: Iterable[dict], covered_leagues: dict[str, str]) -> \
        tuple[list[Signup], list[str]]:
    """Validate seat claims. ``covered_leagues`` maps league_id -> payer email.

    A seat is only real if some League Pass actually covers that league. Without
    that check the form endpoint is a free-report generator for anyone who finds
    the URL — it is public by necessity, so it must be validated, not trusted.
    """
    signups: list[Signup] = []
    problems: list[str] = []
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        user_id = str(row.get("user_id") or "").strip()
        league_id = str(row.get("league_id") or "").strip()
        if not email or not user_id.isdigit() or not is_valid_league_id(league_id):
            problems.append(f"seat claim with unusable fields: {row.get('email')!r}")
            continue
        payer = covered_leagues.get(league_id)
        if not payer:
            problems.append(
                f"seat claim for league {league_id} ({email}) — no League Pass "
                f"covers that league, so it was ignored")
            continue
        rival_owner = row.get("rival_owner_id")
        rival_roster = row.get("rival_roster_id")
        rival_owner_id = str(rival_owner).strip() if rival_owner else None
        rival_roster_id = int(rival_roster) if str(rival_roster or "").isdigit() else None
        if not rival_owner_id and rival_roster_id is None:
            problems.append(f"seat claim from {email} names no rival")
            continue
        username = row.get("sleeper_username")
        signups.append(Signup(
            email=email,
            user_id=user_id,
            league_id=league_id,
            rival_owner_id=rival_owner_id,
            rival_roster_id=rival_roster_id,
            plan="league_pass",
            source="form",
            seen_at=str(row.get("added_at") or row.get("created_at") or ""),
            sleeper_username=str(username).strip() if username else None,
            covered_by=payer,
        ))
    return signups, problems


# --------------------------------------------------------------------- #
# verification + season roll: the two things that make a row trustworthy
# --------------------------------------------------------------------- #

def verify(signup: Signup, client: SleeperClient) -> str | None:
    """None if this signup can produce a real report; else why not.

    Checked against live Sleeper because a reference is just a string a browser
    put in a URL. A row that says someone owns a roster they do not own would
    mail them another manager's team.
    """
    try:
        rosters = client.rosters(signup.league_id)
    except SleeperNotFound:
        return f"league {signup.league_id} does not exist on Sleeper"
    except (SleeperError, ValueError) as exc:
        # An outage must never look like a rejection: the caller keeps the row
        # and retries next run rather than dropping a paying subscriber.
        raise
    mine = None
    for roster in rosters:
        if not isinstance(roster, dict):
            continue
        owners = {roster.get("owner_id")} | set(roster.get("co_owners") or [])
        if signup.user_id in {str(o) for o in owners if o}:
            mine = roster
            break
    if mine is None:
        return (f"Sleeper user {signup.user_id} owns no roster in league "
                f"{signup.league_id}")
    rival = None
    for roster in rosters:
        if not isinstance(roster, dict):
            continue
        if signup.rival_owner_id and str(roster.get("owner_id")) == signup.rival_owner_id:
            rival = roster
            break
        if signup.rival_roster_id is not None and \
                roster.get("roster_id") == signup.rival_roster_id:
            rival = roster
            break
    if rival is None:
        return "the rival they picked is not a team in that league any more"
    if rival.get("roster_id") == mine.get("roster_id"):
        return "they picked themselves as their own rival"
    return None


def roll_season(signup: Signup, client: SleeperClient, season: str) -> tuple[Signup, str | None]:
    """Move a signup onto this season's league, following Sleeper's chain.

    Sleeper mints a NEW league id every year and the old one resolves forever,
    so without this a renewed subscriber gets a confident report about games
    played twelve months ago. The subscriber's user id is the stable thing, so
    we re-resolve from that: of their leagues this season, take the one whose
    previous_league_id chain leads back to the league they signed up for.

    Returns (signup, note). An ambiguous roll changes nothing and says so — a
    wrong league is worse than a missing one, because it looks like it worked.
    """
    try:
        current = client.league(signup.league_id)
    except (SleeperError, ValueError):
        return signup, None
    if str(current.get("season") or "") == season:
        return signup, None                      # already this season

    try:
        leagues = client.user_leagues(signup.user_id, season)
    except (SleeperError, ValueError) as exc:
        return signup, (f"{signup.email}: still on season "
                        f"{current.get('season')} and this season's leagues "
                        f"could not be read ({exc})")

    matches = []
    for league in leagues:
        if not isinstance(league, dict):
            continue
        # Walk this candidate back through its own history looking for the
        # league they actually signed up for.
        cursor: Any = league.get("previous_league_id")
        hops = 0
        while cursor and hops < 8:
            if str(cursor) == signup.league_id:
                matches.append(league)
                break
            try:
                previous = client.league(str(cursor))
            except (SleeperError, ValueError):
                break
            cursor = previous.get("previous_league_id")
            hops += 1
    if len(matches) != 1:
        detail = "no" if not matches else f"{len(matches)} ambiguous"
        return signup, (
            f"{signup.email}: their league is from season "
            f"{current.get('season')} and {detail} {season} league follows from "
            f"it — they need to re-pick before they can be sent anything")

    rolled_id = str(matches[0].get("league_id") or "")
    if not is_valid_league_id(rolled_id):
        return signup, f"{signup.email}: rolled league id looks wrong ({rolled_id!r})"

    # owner_id is stable across seasons; roster_id is NOT (verified: sample
    # league roster 6 changed hands between 2017 and 2018). So the rival is
    # carried by owner and its roster id is dropped, to be re-resolved live.
    rival_owner_id = signup.rival_owner_id
    if not rival_owner_id:
        return signup, (
            f"{signup.email}: rolled to {rolled_id} is not possible — their "
            f"rival was recorded only as a roster number, which does not "
            f"survive a season change. They need to re-pick.")
    # A League Pass covers a LEAGUE, and the league just got a new id. Leaving
    # pass_league_id on last season's id means the commissioner keeps paying
    # while every seat claim against the current league finds no coverage.
    rolled = Signup(**{**asdict(signup), "league_id": rolled_id,
                       "rival_roster_id": None,
                       "pass_league_id": rolled_id if signup.pass_league_id else None})
    return rolled, (f"{signup.email}: rolled from {signup.league_id} "
                    f"({current.get('season')}) to {rolled_id} ({season})")


# --------------------------------------------------------------------- #
# projection to the registry
# --------------------------------------------------------------------- #

def to_registry_entries(signups: Iterable[Signup]) -> list[dict]:
    entries = []
    for signup in signups:
        entry = {
            "email": signup.email,
            "user_id": signup.user_id,
            "league_id": signup.league_id,
            "rival_owner_id": signup.rival_owner_id,
            "rival_roster_id": signup.rival_roster_id,
            "plan": signup.plan,
        }
        if signup.sleeper_username:
            entry["sleeper_username"] = signup.sleeper_username
        if signup.plan == "league_pass" and signup.covered_by:
            entry["covered_by"] = signup.covered_by
        if signup.stripe_customer_id:
            entry["stripe_customer_id"] = signup.stripe_customer_id
        entries.append(entry)
    return entries


def write_registry(entries: list[dict], path: Path = REGISTRY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", help="default: the current NFL season")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the live Sleeper checks (offline testing)")
    parser.add_argument("--no-roll", action="store_true",
                        help="skip the season roll")
    parser.add_argument("--no-promote", action="store_true",
                        help="do not write picks onto Stripe customers")
    parser.add_argument("--full", action="store_true",
                        help="ignore the watermark and re-read every session")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing anything")
    parser.add_argument("--registry-dir", type=Path, default=REGISTRY_DIR,
                        help="where the log, watermark and registry live "
                             "(default: data/registry)")
    args = parser.parse_args(argv)

    # Resolved here, not bound as default arguments: a module constant baked
    # into a signature cannot be redirected by a caller, which makes the whole
    # pipeline impossible to exercise end-to-end without writing over the real
    # subscriber list.
    signup_log = args.registry_dir / SIGNUP_LOG.name
    sync_state = args.registry_dir / SYNC_STATE.name
    registry = args.registry_dir / REGISTRY.name

    api_key = os.environ.get("STRIPE_API_KEY", "")
    if not api_key:
        print("STRIPE_API_KEY is not set — nothing to sync. Set it (a restricted "
              "key with read access to checkout sessions, subscriptions and "
              "customers, plus write on customers) and re-run.", file=sys.stderr)
        return 1

    client = SleeperClient(RAW_DIR)
    season = args.season
    if not season:
        try:
            season = str(client.state("nfl").get("league_season") or "")
        except (SleeperError, ValueError) as exc:
            print(f"could not read the current NFL season from Sleeper: {exc}",
                  file=sys.stderr)
            return 1
    if not season.isdigit():
        print(f"unusable season {season!r}", file=sys.stderr)
        return 1

    state = {} if args.full else _read_state(sync_state)
    since = state.get("stripe_watermark")
    # "s:plink_A,m:plink_B,p:plink_C" — the map that makes the plan a fact
    # about the payment rather than a claim in the buyer's URL.
    link_plans = parse_link_plans(os.environ.get("STRIPE_PAYMENT_LINKS", ""))
    if not any(plan == LEAGUE_PASS for plan in link_plans.values()):
        print("NOTE: no League Pass payment link is mapped in "
              "STRIPE_PAYMENT_LINKS, so no purchase can grant league coverage.",
              file=sys.stderr)

    problems: list[str] = []
    try:
        fresh, newest, sweep_problems = sweep_stripe(
            api_key, since=since if isinstance(since, int) else None,
            link_plans=link_plans or None, promote=not args.no_promote)
    except SubscriptionError as exc:
        print(f"Stripe sweep failed: {exc}", file=sys.stderr)
        return 1
    problems.extend(sweep_problems)
    print(f"Stripe: {len(fresh)} completed checkout(s) since "
          f"{'the beginning' if since is None else since}")

    # ORDER MATTERS. Coverage may only be granted by a payer we have verified,
    # so the Stripe side is rolled and verified BEFORE the seat list is read —
    # otherwise a claim to cover a league the payer has never played in would
    # hand twelve strangers a free product.
    def verify_all(signups):
        kept, notes, rejected = [], [], []
        if args.no_verify:
            return list(signups), notes, rejected
        for signup in signups:
            try:
                reason = verify(signup, client)
            except (SleeperError, ValueError) as exc:
                # Outage, not rejection: keep them and try again next week.
                notes.append(f"{signup.email}: could not verify ({exc}) — kept")
                kept.append(signup)
                continue
            if reason:
                rejected.append(f"{signup.email}: {reason}")
            else:
                kept.append(signup)
        return kept, notes, rejected

    def roll_all(signups):
        moved, notes = [], []
        if args.no_roll:
            return list(signups), notes
        for signup in signups:
            rolled, note = roll_season(signup, client, season)
            if note:
                notes.append(note)
            moved.append(rolled)
        return moved, notes

    notes: list[str] = []
    known = {(s.key, s.rival_owner_id, s.rival_roster_id, s.email)
             for s in load_log(signup_log)}
    new_events = [s for s in fresh
                  if (s.key, s.rival_owner_id, s.rival_roster_id, s.email) not in known]
    payers = project(load_log(signup_log) + new_events)

    payers, roll_notes = roll_all(payers)
    notes.extend(roll_notes)
    # A roll is a real change to the subscription, so it is logged as an event
    # rather than applied invisibly at projection time.
    new_events += [p for p in payers
                   if (p.key, p.rival_owner_id, p.rival_roster_id, p.email) not in known
                   and p not in new_events]

    payers, verify_notes, payer_problems = verify_all(payers)
    notes.extend(verify_notes)
    problems.extend(payer_problems)

    # Only a VERIFIED League Pass payer covers a league.
    covered = {p.pass_league_id: p.email for p in payers if p.pass_league_id}
    if not args.no_promote:
        for payer in payers:
            if payer.pass_league_id and payer.stripe_customer_id:
                try:
                    stamp_pass_coverage(api_key, payer.stripe_customer_id,
                                        payer.pass_league_id)
                except SubscriptionError as exc:
                    problems.append(
                        f"could not record League Pass coverage for "
                        f"{payer.email}: {exc} — their league's seats will not "
                        f"be entitled until this succeeds")

    seat_endpoint = os.environ.get("FORM_ENDPOINT", "")
    seats: list[Signup] = []
    if seat_endpoint:
        try:
            rows = fetch_seats(seat_endpoint, os.environ.get("FORM_API_KEY"))
            seats, seat_problems = seats_to_signups(rows, covered)
            problems.extend(seat_problems)
            print(f"Seats: {len(seats)} claim(s) across {len(covered)} covered league(s)")
        except SyncError as exc:
            # Do NOT proceed with a Stripe-only registry: that would silently
            # drop every League Pass seat and look like a clean run.
            print(f"Seat backend unreadable: {exc}", file=sys.stderr)
            print("  Refusing to write a registry that would be missing every "
                  "League Pass seat.", file=sys.stderr)
            return 1
    elif covered:
        print(f"NOTE: {len(covered)} league(s) have a pass but FORM_ENDPOINT is "
              f"unset, so no seats can be claimed.", file=sys.stderr)

    new_seat_events = [s for s in seats
                       if (s.key, s.rival_owner_id, s.rival_roster_id, s.email) not in known]
    seats, seat_notes, seat_problems = verify_all(
        project(new_seat_events + [s for s in load_log(signup_log)
                                   if s.source == "form"]))
    notes.extend(seat_notes)
    problems.extend(seat_problems)
    new_events += new_seat_events

    # Seats whose league lost its coverage between runs stop being entitled;
    # they stay in the log (the claim happened) but not in the registry.
    seats = [s for s in seats if s.league_id in covered]
    verified = payers + seats

    entries = to_registry_entries(verified)
    line = "=" * 62
    print(f"\n{line}\nSYNC — season {season}\n{line}")
    print(f"New events: {len(new_events)}   Registry: {len(entries)} subscriber(s)")
    for note in notes:
        print(f"  · {note}")
    if problems:
        print(f"\n{len(problems)} thing(s) need a human:", file=sys.stderr)
        for problem in problems:
            print(f"  ! {problem}", file=sys.stderr)

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    appended = append_log(new_events, signup_log)
    write_registry(entries, registry)
    if newest is not None:
        state["stripe_watermark"] = newest
        _write_state(state, sync_state)
    print(f"\nWrote {appended} event(s) to {signup_log.name} and "
          f"{len(entries)} entr(y/ies) to {registry}")
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    # Problems are reported but do not fail the run: the whole point is that
    # the other subscribers still get their Tuesday. An empty registry when
    # events exist IS a failure, though.
    return 1 if (new_events and not entries) else 0


if __name__ == "__main__":
    sys.exit(main())
