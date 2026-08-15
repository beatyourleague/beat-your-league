"""Subscriber registry: who gets a report, for which league, against which rival.

The registry is a JSON array at ``data/registry/subscribers.json`` (gitignored —
it contains emails; CLAUDE.md security says collect the minimum and keep it out
of the repo). Each entry:

    {
      "email": "fan@example.com",           # delivery address (Substack list)
      "sleeper_username": "TheirName",      # informational, for humans
      "user_id": "457511950237696",         # their Sleeper user id
      "league_id": "289646328504385536",
      "rival_owner_id": "189140835533586432",  # preferred: stable across seasons
      "rival_roster_id": 6,                 # fallback for orphaned rival teams
      "added_at": "2026-08-13"
    }

``rival_owner_id`` or ``rival_roster_id`` must be present (both is best).
Entries come from the signup picker (site/join/) — already validated there,
but everything is re-validated here because files are editable by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ingest.sleeper import is_valid_league_id

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_ROOT / "data" / "registry" / "subscribers.json"

# Deliberately loose: enough to catch registry typos, not an RFC gate.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SEASON_PLAN = "season"
LEAGUE_PASS_PLAN = "league_pass"
_PLANS = (SEASON_PLAN, LEAGUE_PASS_PLAN)
_CUSTOMER_RE = re.compile(r"^cus_[A-Za-z0-9]{4,}$")


class RegistryError(ValueError):
    """A registry entry that cannot drive a report run."""


@dataclass(frozen=True)
class Subscriber:
    email: str
    user_id: str
    league_id: str
    rival_owner_id: str | None
    rival_roster_id: int | None
    sleeper_username: str | None = None
    # "season"     — this person bought their own pass.
    # "league_pass"— a seat covered by whoever bought the league's pass. Every
    #                seat still gets its OWN report (own roster, own rival);
    #                the pass only changes who paid, never what is delivered.
    plan: str = SEASON_PLAN
    covered_by: str | None = None   # payer's email, for league_pass seats
    # The Stripe customer this signup was paid by, when it came through
    # checkout. This is the JOIN KEY for entitlement: an email is something the
    # buyer types (twice, in two forms, minutes apart) and can change later in
    # the billing portal, so joining on it means reconciling typos, work-vs-
    # personal addresses and plus-tags forever. A customer id is issued by the
    # system that took the money and never changes. Entries added by hand have
    # none, and fall back to the email join.
    stripe_customer_id: str | None = None

    @property
    def is_league_seat(self) -> bool:
        return self.plan == LEAGUE_PASS_PLAN

    @property
    def slug(self) -> str:
        """Filename-safe identity that carries no email (PII stays out of
        report filenames and out of git)."""
        base = self.sleeper_username or self.user_id
        return re.sub(r"[^A-Za-z0-9_-]", "_", base)[:40] or self.user_id


def _parse_entry(raw: dict, index: int) -> Subscriber:
    where = f"registry entry {index}"
    email = str(raw.get("email", "")).strip()
    if not _EMAIL_RE.match(email):
        raise RegistryError(f"{where}: invalid email {email!r}")
    user_id = str(raw.get("user_id", "")).strip()
    if not user_id.isdigit():
        raise RegistryError(f"{where}: user_id must be a numeric Sleeper id, "
                            f"got {raw.get('user_id')!r}")
    league_id = str(raw.get("league_id", "")).strip()
    if not is_valid_league_id(league_id):
        raise RegistryError(f"{where}: invalid league_id {raw.get('league_id')!r}")
    rival_owner = raw.get("rival_owner_id")
    rival_owner_id = str(rival_owner).strip() if rival_owner else None
    if rival_owner_id is not None and not rival_owner_id.isdigit():
        raise RegistryError(f"{where}: rival_owner_id must be numeric, got {rival_owner!r}")
    rival_roster = raw.get("rival_roster_id")
    # JSON true/false satisfies isinstance(..., int) in Python — a `true` here
    # must not silently become roster 1. Accept real ints and digit strings.
    if isinstance(rival_roster, bool):
        raise RegistryError(f"{where}: rival_roster_id must be a number, got {rival_roster!r}")
    if isinstance(rival_roster, int):
        rival_roster_id: int | None = rival_roster
    elif isinstance(rival_roster, str) and rival_roster.strip().isdigit():
        rival_roster_id = int(rival_roster.strip())
    elif rival_roster in (None, ""):
        rival_roster_id = None
    else:
        raise RegistryError(f"{where}: rival_roster_id must be a number, got {rival_roster!r}")
    if rival_roster_id is not None and rival_roster_id < 1:
        raise RegistryError(f"{where}: rival_roster_id must be positive, got {rival_roster_id}")
    if rival_owner_id is None and rival_roster_id is None:
        raise RegistryError(f"{where}: needs rival_owner_id or rival_roster_id")
    username = raw.get("sleeper_username")
    plan = str(raw.get("plan") or SEASON_PLAN).strip()
    if plan not in _PLANS:
        raise RegistryError(f"{where}: plan must be one of {_PLANS}, got {plan!r}")
    covered = raw.get("covered_by")
    covered_by = str(covered).strip() if covered else None
    if plan == LEAGUE_PASS_PLAN:
        # A seat that names no payer is an unpaid report waiting to happen.
        if not covered_by or not _EMAIL_RE.match(covered_by):
            raise RegistryError(
                f"{where}: a {LEAGUE_PASS_PLAN} seat needs covered_by set to the "
                f"payer's email, got {covered!r}")
    elif covered_by:
        raise RegistryError(
            f"{where}: covered_by is only meaningful on a {LEAGUE_PASS_PLAN} seat")
    customer = raw.get("stripe_customer_id")
    stripe_customer_id = str(customer).strip() if customer else None
    if stripe_customer_id is not None and not _CUSTOMER_RE.match(stripe_customer_id):
        raise RegistryError(
            f"{where}: stripe_customer_id must look like 'cus_...', got {customer!r}")
    return Subscriber(
        email=email,
        user_id=user_id,
        league_id=league_id,
        rival_owner_id=rival_owner_id,
        rival_roster_id=rival_roster_id,
        sleeper_username=str(username).strip() if username else None,
        plan=plan,
        covered_by=covered_by,
        stripe_customer_id=stripe_customer_id,
    )


def load_registry(path: Path = DEFAULT_REGISTRY) -> list[Subscriber]:
    """Load and validate every entry. A malformed entry fails the load loudly —
    silently skipping a paying subscriber is the one unacceptable failure."""
    if not path.is_file():
        raise RegistryError(
            f"no registry at {path} — create it from run/subscribers.example.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise RegistryError(f"registry {path} must be a JSON array")
    subscribers = [_parse_entry(entry, i) for i, entry in enumerate(raw)]
    # Uniqueness is per (email, league) — NOT per email. One person can genuinely
    # play in two leagues and buy a subscription for each, and they get one
    # report per league. Rejecting a repeated email outright made that legitimate
    # customer unloadable, and because the loader fails the WHOLE file, it took
    # every other subscriber's Tuesday down with it. The same rule fires at every
    # season rollover, when a rolled entry briefly coexists with the old one.
    pairs = [(s.email.lower(), s.league_id) for s in subscribers]
    duplicates = {p for p in pairs if pairs.count(p) > 1}
    if duplicates:
        raise RegistryError(
            "the same email is registered twice for one league: "
            + ", ".join(f"{email} in {league}" for email, league in sorted(duplicates)))
    # Two people in one league cannot both hold the same roster — that means a
    # bad signup, and it would send one person another person's team.
    seen: dict[tuple[str, str], str] = {}
    for sub in subscribers:
        key = (sub.league_id, sub.user_id)
        if key in seen:
            raise RegistryError(
                f"league {sub.league_id} has two entries for Sleeper user "
                f"{sub.user_id}: {seen[key]} and {sub.email}")
        seen[key] = sub.email
    return subscribers


def league_pass_seats(subscribers: list[Subscriber]) -> dict[str, list[Subscriber]]:
    """league_id -> seats covered by a league pass, for coverage reporting."""
    out: dict[str, list[Subscriber]] = {}
    for sub in subscribers:
        if sub.is_league_seat:
            out.setdefault(sub.league_id, []).append(sub)
    return out
