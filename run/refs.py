"""The signup reference: a whole subscription, encoded to ride on a payment.

This is the contract between two places that never talk to each other — the
picker in the browser (``site/join/index.html``) writes it into Stripe's
``client_reference_id``, and ``run/sync.py`` reads it back on Tuesday. Nothing
in between stores it, which is the entire point: there is no second list.

Format — deliberately boring, because Stripe accepts only ``[A-Za-z0-9_-]`` and
at most 200 characters, and silently drops anything else while still showing a
working payment page:

    <plan>-<user_id>-<league_id>-<rival>

    plan   s = season pass, m = monthly, p = league pass (commissioner)
    rival  a Sleeper owner_id, or r<roster_id> for an orphaned team

    s-457511950237696-289646328504385536-189140835533586432   (55 chars)
    p-457511950237696-289646328504385536-r6

A league-pass ref is ALSO an individual signup: the commissioner gets their own
report aimed at their own rival, and separately their payment covers the
league. One purchase, two meanings, one string.

Every function here is pure and offline. That is on purpose — this codec is the
one component whose failure is silent (a mangled ref becomes a payment nobody
can attribute), so it must be exhaustively testable without a network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# What Stripe accepts on client_reference_id. Enforced on both sides: the
# browser refuses to navigate with a bad ref, and we refuse to decode one.
STRIPE_REF_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")

SEASON = "season"
MONTHLY = "monthly"
LEAGUE_PASS = "league_pass"

_PREFIX_TO_PLAN = {"s": SEASON, "m": MONTHLY, "p": LEAGUE_PASS}
_PLAN_TO_PREFIX = {plan: prefix for prefix, plan in _PREFIX_TO_PLAN.items()}

_ID_RE = re.compile(r"^\d{6,20}$")


class RefError(ValueError):
    """A reference we cannot turn back into a subscription."""


@dataclass(frozen=True)
class SignupRef:
    plan: str                      # season | monthly | league_pass
    user_id: str
    league_id: str
    rival_owner_id: str | None
    rival_roster_id: int | None

    @property
    def is_league_pass(self) -> bool:
        return self.plan == LEAGUE_PASS

    @property
    def registry_plan(self) -> str:
        """How run/registry.py spells this. Monthly and season are the same
        product to the pipeline — they differ only in how often it bills — and
        the commissioner's own seat is an individual entry, not a covered one:
        they paid for it themselves."""
        return "season"


def encode(plan: str, user_id: str, league_id: str,
           rival_owner_id: str | None = None,
           rival_roster_id: int | None = None) -> str:
    """Build the ref the picker puts on the checkout URL."""
    if plan not in _PLAN_TO_PREFIX:
        raise RefError(f"unknown plan {plan!r}")
    if not _ID_RE.match(str(user_id)):
        raise RefError(f"user_id must be a Sleeper id, got {user_id!r}")
    if not _ID_RE.match(str(league_id)):
        raise RefError(f"league_id must be a Sleeper id, got {league_id!r}")
    if rival_owner_id and _ID_RE.match(str(rival_owner_id)):
        rival = str(rival_owner_id)
    elif rival_roster_id is not None and int(rival_roster_id) >= 1:
        rival = f"r{int(rival_roster_id)}"
    else:
        raise RefError("a ref needs a rival owner_id or roster_id")
    ref = f"{_PLAN_TO_PREFIX[plan]}-{user_id}-{league_id}-{rival}"
    if not STRIPE_REF_RE.match(ref):
        # Unreachable given the checks above; kept because the consequence of
        # being wrong is a payment Stripe accepts and we cannot attribute.
        raise RefError(f"encoded ref is not Stripe-safe: {ref!r}")
    return ref


def decode(ref: str) -> SignupRef:
    """Turn a client_reference_id back into a subscription.

    Raises RefError on anything unrecognised. Callers treat that as "this
    payment needs a human", never as a reason to guess — an invented league id
    would mail someone another manager's team.
    """
    if not isinstance(ref, str) or not STRIPE_REF_RE.match(ref):
        raise RefError(f"not a Stripe-safe reference: {ref!r}")
    parts = ref.split("-")
    if len(parts) != 4:
        raise RefError(f"expected 4 dash-separated fields, got {len(parts)}: {ref!r}")
    prefix, user_id, league_id, rival = parts
    if prefix not in _PREFIX_TO_PLAN:
        raise RefError(f"unknown plan prefix {prefix!r} in {ref!r}")
    if not _ID_RE.match(user_id):
        raise RefError(f"bad user_id in {ref!r}")
    if not _ID_RE.match(league_id):
        raise RefError(f"bad league_id in {ref!r}")
    rival_owner_id: str | None = None
    rival_roster_id: int | None = None
    if rival.startswith("r"):
        if not rival[1:].isdigit() or int(rival[1:]) < 1:
            raise RefError(f"bad rival roster in {ref!r}")
        rival_roster_id = int(rival[1:])
    elif _ID_RE.match(rival):
        rival_owner_id = rival
    else:
        raise RefError(f"bad rival in {ref!r}")
    return SignupRef(
        plan=_PREFIX_TO_PLAN[prefix],
        user_id=user_id,
        league_id=league_id,
        rival_owner_id=rival_owner_id,
        rival_roster_id=rival_roster_id,
    )
