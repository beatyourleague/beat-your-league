"""Who is sending — the sender block every commercial email must carry.

CAN-SPAM requires a valid physical postal address in commercial email, and
Canada's anti-spam law (the owner is in Ontario) requires sender
identification, including a mailing address, in commercial electronic
messages. The owner is anonymous, so the address is a rented mailbox (a
virtual mailbox or PO box), never a home — and it is configuration, not code:
``SENDER_POSTAL_ADDRESS`` (a GitHub Actions secret or variable; LAUNCH.md).

Without it, the one purely commercial email (run/waitlist.py, the launch
announcement) refuses to send, and `make launch-check` shows an OWNER gate.
Not legal advice; the launch-readiness audit recommends one professional
review of the Ontario rules.
"""

from __future__ import annotations

import os

SENDER_NAME = "Beat Your League"
CONTACT = "hello@beatyourleague.com"


def postal_address() -> str:
    return " ".join(os.environ.get("SENDER_POSTAL_ADDRESS", "").split())


def sender_line() -> str | None:
    """'Beat Your League · <mailbox address> · hello@…', or None when no
    address is configured (the caller decides whether that blocks a send)."""
    address = postal_address()
    return f"{SENDER_NAME} · {address} · {CONTACT}" if address else None
