"""Keyed one-way codes for addresses — the only form an address takes in a
committed file.

Two files are committed to a public repo and carry something derived from an
email address: the send log (``data/processed/sent.jsonl`` — free-report,
waitlist, roster-confirmation, seat-note and renewal-notice keys) and the stop
list (``data/processed/suppressed.txt``). They used to carry a plain sha256 of
the address, which is one-way but not secret: anybody who already knows an
address can hash it and see whether it is on the list or was ever mailed
(privacy audit LEGAL-89/103/117). Every one of those codes is now an HMAC under
``LOG_SECRET`` — a secret that lives only in the GitHub Actions secrets and the
owner's shell — so a code cannot be matched back to an address without it.

Rules:

- **One secret, never rotated.** Rotating it would make every committed code
  stop matching: the stop list would silently stop stopping, and every free
  report and launch email would be eligible to go out again. So there is no
  rotation path, on purpose. (``UPDATE_SECRET`` signs links that travel in
  email and can rotate; this one never leaves the runner.)
- **No secret, no code.** ``DigestError`` is raised rather than falling back
  to an unkeyed hash: a fallback would write codes that can never match the
  keyed ones, which is a duplicate send or an ignored stop request waiting to
  happen. Every sender that needs one refuses without it.
- **One mailbox, one code.** Addresses are canonicalised first
  (``run.trials.canonical_email``: case, ``+tags`` and Gmail dots fold away),
  so the stop list, the free-report key and the privacy tool always agree
  about which mailbox an address is.
"""

from __future__ import annotations

import hashlib
import hmac
import os

ENV = "LOG_SECRET"
# 12 hex = 48 bits. Enough that two of our few thousand addresses never share
# a code, short enough to read in a send log.
LENGTH = 12


class DigestError(RuntimeError):
    """LOG_SECRET is not set, so no keyed code can be made. No address in it."""


def secret() -> str:
    value = os.environ.get(ENV, "").strip()
    if not value:
        raise DigestError(
            f"{ENV} is not set, so no address can be turned into the keyed code "
            f"the send log and the stop list use — nothing that needs one is sent "
            f"(set the {ENV} secret: LAUNCH.md step 3)")
    return value


def available() -> bool:
    return bool(os.environ.get(ENV, "").strip())


def keyed(value: str, length: int = LENGTH) -> str:
    """HMAC-SHA256(LOG_SECRET, value), hex, truncated."""
    return hmac.new(secret().encode("utf-8"), value.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:length]


def address(email: str, length: int = LENGTH) -> str:
    """The keyed code for one MAILBOX (canonicalised first)."""
    from run.trials import canonical_email
    return keyed(canonical_email(email), length)
