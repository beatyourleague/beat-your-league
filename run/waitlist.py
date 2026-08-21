"""The launch announcement: one message, once, to everyone who waited.

Usage:
    python -m run.waitlist --list data/registry/waitlist.csv --dry-run
    EMAIL_PROVIDER=resend python -m run.waitlist --list <csv> --send

The waitlist is the one asset that can start working before the product does,
which is exactly why it is easy to ruin. Three failures are available and all
three are permanent, because a list can only be burned once:

1. **Mailing twice.** Every send is keyed and recorded through the same
   ``data/processed/sent.jsonl`` the weekly batch uses, so a re-run, a resumed
   workflow or a double-fired command cannot send the announcement again. The
   key is the campaign plus the address, so a SECOND campaign later still goes
   out — this prevents duplicates, not future sends.
2. **Mailing more than promised.** The capture says "exactly one message when
   signups open, nothing between now and then." That is a promise made at the
   moment of collection, so ``CAMPAIGN`` is a constant with one legal value at
   launch and adding another is a deliberate edit, not a flag.
3. **Sending by accident.** Dry-run is the default, as everywhere else in this
   repo: with no ``EMAIL_PROVIDER`` set and no ``--send``, this writes drafts
   and mails nobody. `run/batch.py` learned that the hard way.

The list itself lives with whatever backend the capture posts to (Resend
Audiences is the natural fit — Resend is already the sender). This reads a CSV
export, tolerantly, the same way ``run/subscriptions.py`` reads a platform
export: a launch is not the moment to discover a column was renamed.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

from render.report import BRAND_LINE
from run.delivery import (DRY_PROVIDER, DeliveryError, Message, build_provider,
                          send_all)

REPO_ROOT = Path(__file__).resolve().parent.parent

# One campaign, because one is what the capture promised.
CAMPAIGN = "launch-2026"

# Same standard run/registry.py applies, so a bad row cannot reach a provider.
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[a-zA-Z]{2,}$")

SUBJECT = "Signups are open — first report lands Tuesday"

BODY = """\
You asked to hear when this opened. It's open.

{brand}

You type your roster once. Every Tuesday morning you get one file: the lineup
we would set and what each call is worth, the one decision worth arguing about,
and who is actually earning the ball — real target and carry counts, not
adjectives.

  {url}

That is the only email you asked for, so it is the only one you are getting.
Unsubscribe any time; we do not ask why.
"""

# What the body must NOT promise, and why — this list is a test, not a comment:
# the waiver market needs a league transaction log we no longer read, the rival
# needs league history we no longer read, and the self-updating report is not
# built yet. A launch announcement is the single most-forwarded thing this
# business will ever send.
FORBIDDEN_CLAIMS = ("waiver market", "your rival", "your league's", "opponent",
                    "updates itself", "live")


def load_list(path: Path) -> tuple[list[str], list[str]]:
    """Read a list export. Returns (addresses, problems).

    Tolerant about columns and strict about addresses: an export renamed
    ``Email Address`` must not silently yield an empty list, and a malformed row
    must not reach a provider — one rejected recipient can cost the sending
    domain's reputation, which is not recoverable in a launch week.
    """
    if not path.is_file():
        raise FileNotFoundError(f"no waitlist export at {path}")
    addresses: list[str] = []
    problems: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = {(name or "").strip().lower(): name for name in
                   (reader.fieldnames or [])}
        column = next((columns[key] for key in columns
                       if "email" in key or key in ("address", "subscriber")), None)
        if column is None:
            raise ValueError(
                f"{path.name} has no email column (saw {reader.fieldnames})")
        for index, row in enumerate(reader, start=2):
            value = (row.get(column) or "").strip().lower()
            if not value:
                continue
            if not EMAIL_RE.match(value):
                problems.append(f"row {index}: not an address")
                continue
            if value in seen:
                continue
            seen.add(value)
            addresses.append(value)
    return addresses, problems


def messages(addresses: list[str], signup_url: str) -> list[Message]:
    """One Message per address, keyed so it can only ever be sent once."""
    body = BODY.format(brand=BRAND_LINE.capitalize(), url=signup_url)
    return [Message(to=address, subject=SUBJECT, html=_html(body, signup_url),
                    text=body, key=f"{CAMPAIGN}-{address}")
            for address in addresses]


def _html(body: str, signup_url: str) -> str:
    """Deliberately plain. A launch announcement that renders as soup in Outlook
    is worse than one that renders as text everywhere, and this is the first
    thing most of these addresses will ever receive from us."""
    from render.report import esc
    paragraphs = "".join(
        f'<p style="font-family:Arial,Helvetica,sans-serif;font-size:15px;'
        f'line-height:1.55;color:#101E33;margin:0 0 14px 0;">{esc(part)}</p>'
        for part in body.split("\n\n") if part.strip())
    return (f'<div style="max-width:560px;margin:0 auto;padding:24px;">'
            f'{paragraphs}<p><a href="{esc(signup_url)}" '
            f'style="font-family:Arial,Helvetica,sans-serif;font-weight:bold;'
            f'color:#1E7A46;">{esc(signup_url)}</a></p></div>')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", type=Path, required=True,
                        help="CSV export from the waitlist backend")
    parser.add_argument("--url", required=True,
                        help="where signups actually open (the join page)")
    parser.add_argument("--send", action="store_true",
                        help="actually send; without it this is a dry run")
    args = parser.parse_args(argv)

    try:
        addresses, problems = load_list(args.list)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not read the waitlist: {exc}", file=sys.stderr)
        return 1

    for problem in problems:
        print(f"  skipped {problem}", file=sys.stderr)
    if not addresses:
        print("The waitlist is empty — nothing to announce.", file=sys.stderr)
        return 1

    provider = build_provider(None if args.send else DRY_PROVIDER)
    implicit_dry = args.send and provider.name == DRY_PROVIDER
    if implicit_dry:
        # Same rule as run/batch.py: asked to send with nothing configured, say
        # NOTHING WAS SENT rather than printing a success and exiting 0.
        print(f"NOTHING WAS SENT. {len(addresses)} address(es) are on the list "
              f"but EMAIL_PROVIDER is not set.", file=sys.stderr)
        return 1

    try:
        results = send_all(messages(addresses, args.url), provider=provider)
    except DeliveryError as exc:
        print(f"Delivery failed: {exc}", file=sys.stderr)
        return 1

    sent = [r for r in results if r.ok and not r.skipped]
    already = [r for r in results if r.skipped]
    failed = [r for r in results if not r.ok]
    print("=" * 62)
    print(f"{CAMPAIGN} via {provider.name}")
    print(f"  on the list      : {len(addresses)}")
    print(f"  sent             : {len(sent)}")
    print(f"  already announced: {len(already)}")
    print(f"  failed           : {len(failed)}")
    if provider.name == DRY_PROVIDER:
        print("  (dry run — nothing left this machine, and nothing was recorded)")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
