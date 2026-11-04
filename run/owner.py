"""The owner's own addresses — one source, read by everything that needs it.

The owner tests the live product with their own inbox: a free report asked for
again and again, a roster update, a Trade Check, a purchase refunded the same
day. The system should treat those addresses as the owner's, in two ways and
no others:

- **Room to test.** The free report skips its one-per-season limit, its
  "already a subscriber" refusal and its same-roster refusal for an owner
  address, and each owner request gets its own send key so a repeat goes out
  while a double-fired run still mails one request once. The per-address daily
  caps (roster-update and extra-team confirmations, Trade Check answers, free
  reports) rise to OWNER_DAILY_CAP. They are RAISED, never removed: the forms
  are public, so anybody can type the owner's address, and no cap at all would
  let a stranger fill the owner's inbox.
- **Left out of the numbers.** make stats, the dashboard, the launch check's
  refund and dispute gate and the launch email's recipient list leave owner
  addresses out the way they leave test domains out, and say how many.

Everything else is unchanged on purpose: a weekly report still needs a paid
plan, the stop list still stops, a refund or a cancel still ends a plan, the
team limit still holds, and nothing here can move a published probability or
the ledger.

The addresses live in ``OWNER_EMAILS`` (comma-separated): a GitHub Actions
secret in CI, a line in the gitignored ``.env`` on the owner's machine. Unset
means nobody is the owner (fail closed). Matching is by mailbox
(``run.trials.canonical_email``: case, ``+tags`` and Gmail dots fold away).
Nothing ever prints the configured addresses; at most how many there are.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Mapping

ENV = "OWNER_EMAILS"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
# Per address per UTC day, for an owner address, wherever a per-address daily
# cap exists. High enough to test with, low enough that a stranger typing the
# owner's address into a public form can't flood the owner's inbox.
OWNER_DAILY_CAP = 20
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _raw(env: Mapping[str, str] | None) -> str:
    """OWNER_EMAILS from ``env`` when given; else this process's environment,
    else the gitignored .env (the owner's machine). A variable that is SET,
    even empty, wins over the file: in CI an unset secret maps to ""."""
    if env is not None:
        return str(env.get(ENV) or "")
    if ENV in os.environ:
        return os.environ.get(ENV) or ""
    from run.stats import read_env_file
    return read_env_file(ENV_FILE, (ENV,)).get(ENV, "")


def owner_addresses(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """The owner's mailboxes, canonical. Anything that isn't shaped like an
    address is dropped; unset is the empty set."""
    from run.trials import canonical_email
    out = set()
    for part in re.split(r"[,;\s]+", _raw(env)):
        part = part.strip()
        if part and _EMAIL_RE.match(part):
            out.add(canonical_email(part))
    return frozenset(out)


def is_owner_address(email: object, env: Mapping[str, str] | None = None, *,
                     owners: Iterable[str] | None = None) -> bool:
    """True when ``email`` is one of the owner's mailboxes. Pass ``owners``
    (from :func:`owner_addresses`) when checking many addresses."""
    if not email or "@" not in str(email):
        return False
    from run.trials import canonical_email
    held = owner_addresses(env) if owners is None else owners
    return canonical_email(str(email)) in held


def not_counted(email: object, owners: Iterable[str] | None = None) -> bool:
    """A form row that is never demand: a test domain
    (``run.trials.is_test_address``) or one of the owner's addresses
    (``owners``; None reads them — pass them when checking many)."""
    from run.trials import is_test_address
    return is_test_address(email) or is_owner_address(email, owners=owners)


def count_not_counted(rows: Iterable[Mapping], owners: Iterable[str] | None = None) -> int:
    """How many form rows :func:`not_counted` leaves out."""
    owners = owner_addresses() if owners is None else frozenset(owners)
    return sum(1 for row in rows if not_counted(row.get("email"), owners))


def daily_cap(email: object, base: int, owners: Iterable[str] | None = None) -> int:
    """The per-address daily cap for ``email``: ``base``, or OWNER_DAILY_CAP
    (never lower than ``base``) for an owner address."""
    return max(base, OWNER_DAILY_CAP) if is_owner_address(email, owners=owners) else base


def stripe_email(obj: object) -> str:
    """The buyer's address on a Stripe object, where the object carries one:
    a checkout session, an invoice, a charge, a refund with its charge
    expanded, a subscription with its customer expanded. "" when none."""
    if not isinstance(obj, Mapping):
        return ""
    details = obj.get("customer_details")
    billing = obj.get("billing_details")
    customer = obj.get("customer")
    charge = obj.get("charge")
    for value in ((details or {}).get("email") if isinstance(details, Mapping) else None,
                  obj.get("customer_email"),
                  (billing or {}).get("email") if isinstance(billing, Mapping) else None,
                  obj.get("receipt_email"),
                  customer.get("email") if isinstance(customer, Mapping) else None):
        if isinstance(value, str) and value.strip():
            return value
    return stripe_email(charge) if isinstance(charge, Mapping) else ""


def is_owner_purchase(obj: object, owners: Iterable[str] | None = None) -> bool:
    """A Stripe object bought by one of the owner's addresses."""
    owners = owner_addresses() if owners is None else frozenset(owners)
    return bool(owners) and is_owner_address(stripe_email(obj), owners=owners)


def owners_line(owners: Iterable[str]) -> str:
    """How many owner addresses are set — never which."""
    n = len(frozenset(owners))
    return f"{n} owner address{'es' if n != 1 else ''} set (OWNER_EMAILS)"
