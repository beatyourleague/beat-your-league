"""The launch announcement: one message, once, to everyone who waited.

Usage:
    python -m run.waitlist                                   # dry run, Worker list
    EMAIL_PROVIDER=resend python -m run.waitlist --send      # the real thing
    python -m run.waitlist --list export.csv                 # a CSV instead
    make waitlist-preview | make waitlist-send [LIST=file.csv]

On opening morning (OPS-13): ``make waitlist-preview``, then ``make
waitlist-send`` with EMAIL_PROVIDER and its key, EMAIL_FROM, SITE_URL,
SENDER_POSTAL_ADDRESS, FORM_ENDPOINT and FORM_API_KEY in the shell (the same
values as the GitHub secrets). Sign-ups that arrived by email before the
Worker existed go in a CSV with an ``email`` column, sent with ``LIST=`` —
the send log keys on the address, so anyone on both lists gets one message.
Then commit and push ``data/processed/sent.jsonl``.

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

The list itself lives in the form Worker (``infra/form-worker.js``) — the same
mailbox the seats and roster updates use, read back here with the ``waitlist``
kind filter. A CSV export is still accepted via ``--list``, read tolerantly the
same way ``run/subscriptions.py`` reads a platform export: a launch is not the
moment to discover a column was renamed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from pathlib import Path

from render.report import BRAND_LINE
from run.delivery import (DRY_PROVIDER, DeliveryError, Message, build_provider,
                          send_all)
from run.intake import IntakeError, fetch_seats

REPO_ROOT = Path(__file__).resolve().parent.parent

# One campaign, because one is what the capture promised.
CAMPAIGN = "launch-2026"

# Same standard run/registry.py applies, so a bad row cannot reach a provider.
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[a-zA-Z]{2,}$")

SUBJECT = "Signups are open — your first report lands the day you join"

BODY = """\
You asked to hear when this opened. It's open.

{brand}

You type your roster once and your first report lands the day you join. Then
every Tuesday morning: the lineup we would set with the odds on the close calls,
the one decision worth arguing about, and who is actually earning the ball —
real target and carry counts, not adjectives.

  {url}

That is the only email you asked for, so it is the only one you are getting.
To be taken off the list anyway, reply "unsubscribe" (or use your mail app's
Unsubscribe button) and you're off within 10 business days; we do not ask why.

{sender}
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


def waitlist_addresses(rows) -> list[str]:
    """The launch list in a Worker read (kind "waitlist"), deduped, in order.

    The Worker is the same mailbox the seats and roster updates use, so the
    kind filter is load-bearing: a seat or update row carries a roster and a
    token, and a broadcast to those addresses would email people who never
    asked for this message.
    """
    addresses: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if str(row.get("kind") or "") != "waitlist":
            continue
        value = str(row.get("email") or "").strip().lower()
        if EMAIL_RE.match(value) and value not in seen:
            seen.add(value)
            addresses.append(value)
    return addresses


def saved_refs(rows) -> dict[str, str]:
    """address -> the roster they checked while checkout was closed (contract
    C6), the newest one per address. A waitlist row's ref is what checkout
    WOULD have used; one that does not decode as a roster is ignored — the
    email then carries the plain signup link, never a link that fails."""
    from run.intake import split_via
    from run.refs import RefError, decode_roster, is_roster_ref
    out: dict[str, str] = {}
    for row in rows:
        if str(row.get("kind") or "") != "waitlist":
            continue
        address = str(row.get("email") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        if not EMAIL_RE.match(address) or not is_roster_ref(ref):
            continue
        try:
            decode_roster(split_via(ref)[0])
        except RefError:
            continue
        out[address] = ref
    return out


def load_worker_list(endpoint: str, api_key: str | None) -> list[str]:
    """The launch list straight from the form Worker."""
    return waitlist_addresses(fetch_seats(endpoint, api_key))


def restore_url(signup_url: str, ref: str | None) -> str:
    """The signup link, carrying the roster this person already checked
    (contract C6: the join page reads ?ref= and fills the roster and the
    settings back in). A ref is [A-Za-z0-9_-] only, so it needs no quoting."""
    if not ref:
        return signup_url
    base, hash_ = (signup_url.split("#", 1) + [""])[:2]
    joined = f"{base}{'&' if '?' in base else '?'}ref={ref}"
    return joined + (f"#{hash_}" if hash_ else "")


# Said only to somebody whose link carries their roster, beside that link.
SAVED_LINE = ("That link brings back the roster you checked while signups were "
              "closed, so it's already filled in when you open it.")


def messages(addresses: list[str], signup_url: str,
             refs: dict[str, str] | None = None) -> list[Message]:
    """One Message per address, keyed so it can only ever be sent once.

    The key carries a DIGEST of the address, not the address: sent.jsonl is
    committed (the crons persist it, merge=union), and a committed log must
    never hold the list itself. Somebody who checked a roster while checkout
    was closed gets their own link back to it (``refs``, contract C6) — the
    same one message, never a second.
    """
    from render.sender import CONTACT, sender_line
    # The brand line, sentence-cased properly: .capitalize() lowered every
    # other letter, so it read "every tuesday" (launch audit L2).
    brand = BRAND_LINE[:1].upper() + BRAND_LINE[1:]
    # Commercial email: sender identity with a postal address (CAN-SPAM,
    # CASL). main() refuses a real send without one; a preview shows the gap.
    sender = sender_line() or "[sender postal address not configured]"
    out: list[Message] = []
    for address in addresses:
        ref = (refs or {}).get(address)
        url = restore_url(signup_url, ref)
        body = BODY.format(brand=brand, url=url, sender=sender)
        if ref:
            body = body.replace(f"  {url}\n", f"  {url}\n\n{SAVED_LINE}\n", 1)
        out.append(Message(
            to=address, subject=SUBJECT, html=_html(body, url), text=body,
            key=f"{CAMPAIGN}-{hashlib.sha256(address.encode()).hexdigest()[:10]}",
            # Gmail and Apple Mail show an Unsubscribe button for this.
            unsubscribe=f"mailto:{CONTACT}?subject=unsubscribe"))
    return out


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
    parser.add_argument("--list", type=Path,
                        help="CSV export; omit to read the form Worker "
                             "(FORM_ENDPOINT + FORM_API_KEY)")
    parser.add_argument("--url",
                        help="where signups actually open; defaults to "
                             "SITE_URL + /join/")
    parser.add_argument("--send", action="store_true",
                        help="actually send; without it this is a dry run")
    args = parser.parse_args(argv)

    if not args.url:
        site = os.environ.get("SITE_URL", "").rstrip("/")
        if not site:
            print("No --url and SITE_URL is not set — the announcement's one "
                  "job is that link, so there is nothing to send.",
                  file=sys.stderr)
            return 1
        args.url = f"{site}/join/"

    if args.send:
        # Everything a real send needs, said in one place before anything is
        # read (OPS-13): the launch email is sent once, by hand, on opening
        # morning, and finding the missing secret one refusal at a time is
        # how it goes out late — or from the placeholder sender.
        missing = send_env_missing()
        if missing:
            print("NOTHING WAS SENT. Set these first (the same values as the "
                  "GitHub secrets): " + ", ".join(missing), file=sys.stderr)
            return 1

    problems: list[str] = []
    refs: dict[str, str] = {}
    if args.list is not None:
        try:
            addresses, problems = load_list(args.list)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Could not read the waitlist: {exc}", file=sys.stderr)
            return 1
    else:
        endpoint = os.environ.get("FORM_ENDPOINT", "")
        if not endpoint:
            print("No --list export and FORM_ENDPOINT is not set — there is "
                  "no waitlist to read.", file=sys.stderr)
            return 1
        try:
            rows = fetch_seats(endpoint, os.environ.get("FORM_API_KEY"))
        except IntakeError as exc:
            print(f"Could not read the waitlist: {exc}", file=sys.stderr)
            return 1
        addresses, refs = waitlist_addresses(rows), saved_refs(rows)

    for problem in problems:
        print(f"  skipped {problem}", file=sys.stderr)
    if not addresses:
        print("The waitlist is empty — nothing to announce.", file=sys.stderr)
        return 1

    from render.sender import sender_line
    if args.send and not sender_line():
        # A commercial email without the sender's postal address breaks
        # CAN-SPAM and CASL, and a list can only be burned once.
        print("REFUSING TO SEND: SENDER_POSTAL_ADDRESS is not set. The launch "
              "email must carry a postal address (a rented mailbox, never a "
              "home) — see LAUNCH.md.", file=sys.stderr)
        return 1
    try:
        provider = build_provider(None if args.send else DRY_PROVIDER)
    except DeliveryError as exc:
        # A provider named without its key raised straight through as a
        # traceback; it is a refusal like any other missing setting.
        print(f"NOTHING WAS SENT. {exc}", file=sys.stderr)
        return 1
    implicit_dry = args.send and provider.name == DRY_PROVIDER
    if implicit_dry:
        # Same rule as run/batch.py: asked to send with nothing configured, say
        # NOTHING WAS SENT rather than printing a success and exiting 0.
        print(f"NOTHING WAS SENT. {len(addresses)} address(es) are on the list "
              f"but EMAIL_PROVIDER is not set.", file=sys.stderr)
        return 1

    try:
        results = send_all(messages(addresses, args.url, refs), provider=provider)
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
    print(f"  with their roster: {sum(1 for a in addresses if a in refs)}")
    if provider.name == DRY_PROVIDER:
        print("  (dry run — nothing left this machine, and nothing was recorded)")
    elif sent:
        # The send log is the only thing that stops a second announcement,
        # and on this machine it is not where the crons read it until it is
        # committed and pushed.
        print("  NOW COMMIT data/processed/sent.jsonl and push it — the crons "
              "read the committed copy, and it is what stops a second send.")
    print("=" * 62)
    return 1 if failed else 0


# What `--send` needs in the environment (OPS-13). EMAIL_FROM is on the list
# because run/delivery.py falls back to a placeholder sender at
# example.invalid, which no provider will deliver and no reader would trust.
SEND_ENV = ("EMAIL_PROVIDER", "EMAIL_FROM", "SENDER_POSTAL_ADDRESS")
PROVIDER_KEYS = {"resend": "RESEND_API_KEY", "postmark": "POSTMARK_TOKEN"}


def send_env_missing() -> list[str]:
    """The settings a real launch send still lacks, by name. Pure over the
    environment; never prints a value."""
    missing = [name for name in SEND_ENV if not os.environ.get(name, "").strip()]
    key = PROVIDER_KEYS.get(os.environ.get("EMAIL_PROVIDER", "").strip().lower())
    if key and not os.environ.get(key, "").strip():
        missing.append(key)
    return missing


if __name__ == "__main__":
    sys.exit(main())
