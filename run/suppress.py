"""The stop list — addresses that asked us to stop emailing them.

Usage:
    python -m run.suppress <email> [<email> ...]   put them on the list
    python -m run.suppress --check <email>         is this address on it?
    python -m run.suppress --remove <email>        take it off (they asked back in)

Then commit ``data/processed/suppressed.txt`` — the crons read the committed
copy, so an entry that only exists on your machine stops nothing.

Why it exists. A League Pass SEAT pays nothing and has no Stripe subscription,
so it has nothing to cancel: its way out is to reply "stop" (or use the mail
app's unsubscribe, whose header points at the same inbox), and every surface
promises "you're off within 10 business days" — CAN-SPAM's ceiling (launch
audit C4, Oct 15 2026). Until this file existed, nothing could keep that
promise: a stop request reached an inbox and the next Tuesday mailed them
anyway. The waitlist's launch email makes the same promise and leans on the
same list. A PAID subscription still cancels itself from the billing page; the
operator is in this loop only where no money is.

Rules:

- **Digests, never addresses.** The file is committed to a public repo, so it
  holds the same digest the free report's send-log key uses
  (``run.trials.trial_key``): sha256 of the canonical address, 12 hex. One
  mailbox is one entry however it is spelled — ``+tags`` and Gmail dots fold
  away first (``run.trials.canonical_email``), so "F.an+x@gmail.com" asking to
  stop also stops "fan@gmail.com".
- **Checked before every send** (``run.delivery.send_all``), on every runner at
  once, because a per-runner check is one runner short the first time someone
  adds a sender. A suppressed message is reported as SKIPPED, never failed: a
  person who asked to stop is not an error to retry.
- **One notice still goes: the pre-renewal notice** (``LEGALLY_OWED``). It is
  about a charge on the reader's own card, the law requires it, and it carries
  the cancel route — exactly what somebody who wants to stop needs. A stop
  request cannot waive it, and suppressing it would renew a pass with no
  warning.
- **Unreadable fails closed.** If the file exists and cannot be read, nothing
  is sent (every message fails and retries next run): a delayed Tuesday is
  recoverable, mailing somebody who asked us to stop is not.
- **Somebody who signs up again** is still on the list until ``--remove`` —
  a purchase is a new request, but nothing here can see one, so the runners
  report suppressed sends separately for the operator to notice.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

from run.trials import canonical_email

REPO_ROOT = Path(__file__).resolve().parent.parent
SUPPRESS_FILE = REPO_ROOT / "data" / "processed" / "suppressed.txt"

# Send-log key prefixes the stop list never blocks. Only the pre-renewal
# notice (render/renewal.py keys it "renewal-{date}-{slug}"): see the module
# docstring. Everything else — reports, Saturday checks, welcomes, roster
# confirmations, free reports, the launch email — honours a stop.
LEGALLY_OWED = ("renewal-",)

_DIGEST = re.compile(r"^[0-9a-f]{12}$")
HEADER = (
    "# The stop list: addresses that asked us to stop emailing them.\n"
    "# One digest per line (sha256 of the canonical address, 12 hex) - never an\n"
    "# address; this file is public. Add with `python -m run.suppress <email>`,\n"
    "# then commit it. Checked by run/delivery.send_all before every send.\n"
)


class SuppressionError(RuntimeError):
    """The stop list exists and cannot be read. Carries no address."""


def address_digest(email: str) -> str:
    """The digest the free report's send-log key carries (run.trials.trial_key),
    so the two can never disagree about which mailbox an address is."""
    return hashlib.sha256(canonical_email(email).encode("utf-8")).hexdigest()[:12]


def load_suppressed(path: Path | None = None) -> frozenset[str]:
    """Every digest on the list. A missing file is an empty list (a fresh
    checkout, or nobody has asked yet); a file that exists and cannot be read
    raises, because the caller must fail closed rather than guess."""
    path = path or SUPPRESS_FILE
    if not path.exists():
        return frozenset()
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SuppressionError(f"the stop list could not be read "
                               f"({type(exc).__name__})") from None
    found: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _DIGEST.match(line):
            found.add(line)
        elif "@" in line:
            # Never written by this tool, and a test keeps one out of the
            # committed file — but if somebody pastes an address by hand, the
            # stop is honoured rather than ignored.
            found.add(address_digest(line))
    return frozenset(found)


def is_suppressed(email: str, suppressed: frozenset[str] | set[str]) -> bool:
    return address_digest(email) in suppressed


def owed_anyway(key: str) -> bool:
    """A message the stop list never blocks (``LEGALLY_OWED``)."""
    return key.startswith(LEGALLY_OWED)


def _write(path: Path, digests: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted, so the committed file diffs as one added line per request.
    path.write_text(HEADER + "".join(f"{d}\n" for d in sorted(digests)),
                    encoding="utf-8")


def add(emails: list[str], path: Path | None = None) -> int:
    """Put addresses on the list. Returns how many were new."""
    path = path or SUPPRESS_FILE
    held = set(load_suppressed(path))
    new = {address_digest(e) for e in emails} - held
    if new:
        _write(path, held | new)
    return len(new)


def remove(emails: list[str], path: Path | None = None) -> int:
    """Take addresses off the list (they asked back in). Returns how many."""
    path = path or SUPPRESS_FILE
    held = set(load_suppressed(path))
    gone = {address_digest(e) for e in emails} & held
    if gone:
        _write(path, held - gone)
    return len(gone)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m run.suppress",
        description="Stop emailing an address (a League Pass seat, a waitlist "
                    "or free-report address). Paid subscribers cancel from "
                    "their billing page instead.")
    parser.add_argument("emails", nargs="+", metavar="email")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="say whether each address is on the list")
    mode.add_argument("--remove", action="store_true",
                      help="take addresses off the list")
    parser.add_argument("--file", type=Path, default=None,
                        help="the list to use (default: data/processed/suppressed.txt)")
    args = parser.parse_args(argv)

    bad = [e for e in args.emails if not _EMAIL_RE.match(e.strip())]
    if bad:
        # Counted, never echoed: this output can land in a terminal log.
        print(f"{len(bad)} of those doesn't look like an email address; "
              f"nothing was changed.", file=sys.stderr)
        return 2
    path = args.file or SUPPRESS_FILE
    try:
        if args.check:
            held = load_suppressed(path)
            for email in args.emails:
                state = "on the list" if is_suppressed(email, held) else "not on the list"
                print(f"{address_digest(email)}: {state}")
            return 0
        if args.remove:
            gone = remove(args.emails, path)
            print(f"Removed {gone} address(es) from the stop list.")
        else:
            new = add(args.emails, path)
            print(f"Added {new} address(es) to the stop list "
                  f"({len(args.emails) - new} already on it).")
            print("If one of them PAYS for a subscription, its reports stop "
                  "while its billing does not: point them at their billing "
                  "page to cancel instead.")
    except SuppressionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
    print(f"Commit {shown} and push — the crons read the committed copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
