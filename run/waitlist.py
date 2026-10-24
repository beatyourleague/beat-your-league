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
4. **Mailing a poisoned list** (pre-launch review APPSEC-1 / INFRA-03). The
   capture is a public form, so a script can fill it with addresses nobody
   asked to mail — and one launch send to them burns the sending domain's
   reputation and the day's provider allowance. So the list is deduped by
   MAILBOX (``+tag`` and Gmail dots fold away, ``run.trials.canonical_email``),
   the preview prints the mailbox count and the five commonest domains, and a
   real send needs ``--max`` (or ``WAITLIST_MAX``): the most the owner, having
   read the preview, means to send. More than that still to announce, and
   nothing is sent.

The list itself lives in the form Worker (``infra/form-worker.js``) — the same
mailbox the seats and roster updates use, read back here with the ``waitlist``
kind filter. A CSV export is still accepted via ``--list``, read tolerantly the
same way ``run/subscriptions.py`` reads a platform export: a launch is not the
moment to discover a column was renamed.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path

from run.delivery import (DRY_PROVIDER, DeliveryError, Message, build_provider,
                          send_all)
from run.digest import DigestError, address as keyed_address
from run.intake import IntakeError, fetch_seats

REPO_ROOT = Path(__file__).resolve().parent.parent

# One campaign, because one is what the capture promised.
CAMPAIGN = "launch-2026"

# Same standard run/registry.py applies, so a bad row cannot reach a provider.
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[a-zA-Z]{2,}$")

# The subject when the season clock (site/week.json) can't say which week a
# buyer's first weekly report is — absent, stale, or out of season.
SUBJECT = "Signups are open — your first report lands the day you join"
# With the clock (final review, copy improvements): the week this buyer's
# lineup is for, the join page's own rule (``launch_frame``).
SUBJECT_TUESDAY = "It's open — your Week {week} lineup lands {day}"
SUBJECT_BEFORE_KICKOFF = "It's open — get your Week {week} lineup before kickoff"

# Mid-season (owner decision, Oct 18 2026): sold as every lineup from here to
# the title game. The three things it does, each one the product does in every
# setup; "you type your roster once" went (a roster can be updated any week,
# so "once" said the opposite of the FAQ). The price paragraph carries the
# one-payment and refund terms beside the price, as every selling surface does.
BODY = """\
{opening}

Paste your roster from any app: no login, no league to connect. Your first
report usually lands within the hour. Then every Tuesday through your title
game, one email sets your lineup for your scoring: every slot decided, every
close call explained, an if/then for late news, and any bye still ahead that
leaves a spot empty, playoff weeks included.

{offer}

  {url}

That is the only email you asked for, so it is the only one you are getting.
To be taken off the list anyway, reply "unsubscribe" (or use your mail app's
Unsubscribe button) and you're off within 10 business days; we do not ask why.

{sender}
"""
OPENING = "You asked to hear when this opened. It's open."
OPENING_WEEK = "You asked to hear when this opened. It's open, in time for Week {week}."
# The join page's own terms line for each pass (site/join/index.html), so the
# email and the checkout state one offer in one set of words.
_REFUND = ("Refunds are no-questions until your second weekly report's week "
           "kicks off — one per person.")
OFFER = ("The Rest-of-Season Pass is {price}, one payment: nothing renews and "
         "nothing more is charged. " + _REFUND)
OFFER_PLAYOFF = ("The Playoff Pass is {price}, one payment: nothing renews and "
                 "nothing more is charged. " + _REFUND)
# The join page's switch (PLAYOFF_FROM_WEEK): the $19 pass replaces the $29
# one once a buyer's first weekly report would be this week or later — and
# only while its payment link is on the page.
PLAYOFF_FROM_WEEK = 13

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
    from run.trials import canonical_email
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
            if canonical_email(value) in seen:
                continue                       # one mailbox, one message
            seen.add(canonical_email(value))
            addresses.append(value)
    return addresses, problems


def waitlist_addresses(rows) -> list[str]:
    """The launch list in a Worker read (kind "waitlist"), deduped, in order.

    The Worker is the same mailbox the seats and roster updates use, so the
    kind filter is load-bearing: a seat or update row carries a roster and a
    token, and a broadcast to those addresses would email people who never
    asked for this message.

    One MAILBOX, one entry (the first spelling seen): ``a+1@`` and ``a+2@``
    are one inbox, and so are Gmail's dotted spellings.
    """
    from run.trials import canonical_email
    addresses: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if str(row.get("kind") or "") != "waitlist":
            continue
        value = str(row.get("email") or "").strip().lower()
        if EMAIL_RE.match(value) and canonical_email(value) not in seen:
            seen.add(canonical_email(value))
            addresses.append(value)
    return addresses


def top_domains(addresses: list[str], count: int = 5) -> list[tuple[str, int]]:
    """The commonest domains on the list, most first — what a poisoned list
    looks like at a glance (hundreds at one throwaway domain). Domains only,
    never an address. Pure."""
    from collections import Counter
    tally = Counter(a.rsplit("@", 1)[-1] for a in addresses if "@" in a)
    return sorted(tally.items(), key=lambda item: (-item[1], item[0]))[:count]


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


# The form kinds this runner reads (run.intake.fetch_seats `kinds`).
WAITLIST_KINDS = ("waitlist",)


def load_worker_list(endpoint: str, api_key: str | None) -> list[str]:
    """The launch list straight from the form Worker."""
    return waitlist_addresses(fetch_seats(endpoint, api_key, kinds=WAITLIST_KINDS))


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


def launch_frame(clock: dict | None, now=None) -> tuple[int, bool, str] | None:
    """(the week a buyer's first weekly report is for, whether it goes out
    before that week's kickoff, the day it lands) from the season clock the
    live build writes (site/week.json), by the join page's own rule: that
    week's report before its first kickoff, the next week's after. None when
    the clock is absent, out of season or stale — then the email names no
    week, which is never false."""
    from datetime import date, datetime, time, timedelta, timezone
    from zoneinfo import ZoneInfo
    clock = clock or {}
    if clock.get("phase") not in (None, "season"):
        return None
    try:
        week = int(clock["week"])
        lands = date.fromisoformat(str(clock["lands_on"]))
    except (KeyError, TypeError, ValueError):
        return None
    eastern = ZoneInfo("America/New_York")
    now = now or datetime.now(timezone.utc)
    if now >= datetime.combine(lands + timedelta(days=1), time(0), eastern):
        return None                                  # a clock nobody rebuilt
    kick = None
    try:
        kick = datetime.fromisoformat(str(clock["first_kickoff"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        pass
    kicked = kick is not None and now >= kick
    first = week + 1 if kicked else week
    last = clock.get("last_week")
    if isinstance(last, int) and first > last:
        return None                                  # the season's last report is out
    today = now.astimezone(eastern).date()
    day = "today" if today == lands else f"{lands:%A}"
    return first, not kicked, day


def _playoff_link_live() -> bool:
    """Is the $19 Playoff Pass link on the join page? The email may offer
    only what the checkout it links to sells."""
    page = REPO_ROOT / "site" / "join" / "index.html"
    try:
        found = re.search(r'const STRIPE_LINK_PLAYOFF = "([^"]*)"',
                          page.read_text(encoding="utf-8"))
    except OSError:
        return False
    return bool(found and found.group(1).strip())


def _clock() -> dict:
    from render.live_sample import read_week_json
    return read_week_json(REPO_ROOT / "site" / "week.json")


def compose(url: str, sender: str, clock: dict | None = None,
            now=None) -> tuple[str, str, str]:
    """(subject, plain-text body, inbox preview) for one launch email."""
    from render.welcome import PLAYOFF_PRICE, SEASON_PRICE
    frame = launch_frame(clock, now)
    playoff = bool(frame and frame[0] >= PLAYOFF_FROM_WEEK and _playoff_link_live())
    offer = (OFFER_PLAYOFF.format(price=PLAYOFF_PRICE) if playoff
             else OFFER.format(price=SEASON_PRICE))
    if frame is None:
        subject, opening = SUBJECT, OPENING
        preview = "Signups are open. Your first report usually lands within the hour."
    else:
        week, before_kickoff, day = frame
        subject = (SUBJECT_BEFORE_KICKOFF.format(week=week) if before_kickoff
                   else SUBJECT_TUESDAY.format(week=week, day=day))
        opening = OPENING_WEEK.format(week=week)
        preview = (f"It's open, in time for Week {week}. Paste your roster; your "
                   f"first report usually lands within the hour.")
    import textwrap
    body = BODY.format(opening=opening, offer=textwrap.fill(offer, 78),
                       url=url, sender=sender)
    return subject, body, preview


def messages(addresses: list[str], signup_url: str,
             refs: dict[str, str] | None = None, clock: dict | None = None,
             now=None) -> list[Message]:
    """One Message per address, keyed so it can only ever be sent once.

    The key carries a DIGEST of the address, not the address: sent.jsonl is
    committed (the crons persist it, merge=union), and a committed log must
    never hold the list itself. Somebody who checked a roster while checkout
    was closed gets their own link back to it (``refs``, contract C6) — the
    same one message, never a second.

    ``clock``: the season clock (site/week.json, read when omitted), which
    names the week in the subject and the opening line.
    """
    from render.sender import CONTACT, sender_line
    clock = _clock() if clock is None else clock
    # Commercial email: sender identity with a postal address (CAN-SPAM,
    # CASL). main() refuses a real send without one; a preview shows the gap.
    sender = sender_line() or "[sender postal address not configured]"
    from run.trials import canonical_email
    by_mailbox = {canonical_email(a): r for a, r in (refs or {}).items()}
    out: list[Message] = []
    for address in addresses:
        ref = (refs or {}).get(address) or by_mailbox.get(canonical_email(address))
        url = restore_url(signup_url, ref)
        subject, body, preview = compose(url, sender, clock, now)
        if ref:
            body = body.replace(f"  {url}\n", f"  {url}\n\n{SAVED_LINE}\n", 1)
        out.append(Message(
            to=address, subject=subject,
            html=_html(body, url, saved=bool(ref), sender=sender,
                       subject=subject, preview=preview), text=body,
            # A keyed code, never the address (run/digest.py): the send log
            # is public, and a plain hash would let anyone holding an
            # address test whether it joined the list.
            key=f"{CAMPAIGN}-{keyed_address(address)}",
            # Gmail and Apple Mail show an Unsubscribe button for this.
            unsubscribe=f"mailto:{CONTACT}?subject=unsubscribe"))
    return out


def _html(body: str, url: str, *, saved: bool, sender: str,
          subject: str = SUBJECT,
          preview: str = "Signups are open. Your first report usually lands "
                         "within the hour.") -> str:
    """The launch email in the welcome email's shell (PANEL:R2): navy
    masthead, a preview line, the message and ONE button.

    It was a bare <div> of Arial paragraphs with the signup URL printed as
    text twice — the second time after the postal address — and a saved
    roster's URL (~100 characters, a 60-character run with no break in it)
    pushed the email to 579-690px on a 390px phone, which zoomed the whole
    message out. The URL is now only the button's href; the plain-text half
    (``body``) keeps it printed, where a text client needs it. The words are
    BODY's own paragraphs, so the two halves cannot say different things."""
    from render.email import BASE, CARD, DISPLAY, FLAG, FONT, NAVY, PAPER, SMALL
    from render.report import EMAIL_META, esc, preheader_html
    label = "Pick up where you left off" if saved else "Set up my team"
    para = f'<p style="{BASE}font-size:15px;margin:0 0 14px 0;">'
    parts = [" ".join(line.strip() for line in part.splitlines())
             for part in body.split("\n\n") if part.strip()]
    before, after = [], []
    for part in parts:
        if part == url:
            before, after = before + after, []     # the button goes here
            continue
        if part == sender:
            continue                               # the footer carries it
        after.append(part)
    # The paragraph after the link is the volume-and-exit promise, set small;
    # SAVED_LINE, when it is there, stays beside the button it describes.
    saved_html = (f"{para}{esc(SAVED_LINE)}</p>"
                  if saved and SAVED_LINE in after else "")
    rest = [part for part in after if part != SAVED_LINE]
    body_html = "".join(f"{para}{esc(part)}</p>" for part in before)
    tail_html = "".join(f'<p style="{SMALL}margin:0 0 6px 0;">{esc(part)}</p>'
                        for part in rest)
    button = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:6px 0 18px 0;"><tr><td style="background:{FLAG};'
        f'border-radius:4px;"><a href="{esc(url)}" style="display:inline-block;'
        f'padding:13px 24px;font-family:{FONT};font-size:16px;font-weight:bold;'
        f'color:{NAVY};text-decoration:none;">{esc(label)}</a></td></tr></table>')
    return (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'{EMAIL_META}<title>{esc(subject)}</title></head>'
        f'<body style="margin:0;padding:0;background:{PAPER};">'
        f'{preheader_html(preview)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:18px 8px;"><table role="presentation" width="560" '
        f'cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:560px;width:100%;background:{CARD};">'
        f'<tr><td style="background:{NAVY};padding:22px 26px;border-left:4px solid {FLAG};">'
        f'<div style="font-family:{DISPLAY};font-size:13px;font-weight:bold;'
        f'letter-spacing:4px;text-transform:uppercase;color:{FLAG};">Beat Your League</div>'
        f'<div style="font-family:{DISPLAY};font-size:28px;font-weight:bold;'
        f'text-transform:uppercase;color:{CARD};padding-top:6px;">Signups are open</div>'
        f'</td></tr><tr><td style="padding:22px 26px 8px 26px;">{body_html}{button}'
        f'{saved_html}{tail_html}</td></tr>'
        f'<tr><td style="background:{PAPER};padding:16px 26px 22px 26px;">'
        f'<p style="{SMALL}margin:0;">{esc(sender)}</p></td></tr>'
        f'</table></td></tr></table></body></html>\n')


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
    parser.add_argument("--max", type=int, default=None,
                        help="the most messages a real send may go out with, "
                             "after reading the preview (or WAITLIST_MAX); "
                             "required with --send")
    args = parser.parse_args(argv)
    if args.max is None and os.environ.get("WAITLIST_MAX", "").strip().isdigit():
        args.max = int(os.environ["WAITLIST_MAX"].strip())

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
        if args.max is None or args.max < 1:
            print("NOTHING WAS SENT. Read `make waitlist-preview` first (the "
                  "mailbox count and the commonest domains), then send with "
                  "--max N (or WAITLIST_MAX=N): the most you mean to send.",
                  file=sys.stderr)
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
            rows = fetch_seats(endpoint, os.environ.get("FORM_API_KEY"),
                               kinds=WAITLIST_KINDS)
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
        built = messages(addresses, args.url, refs)
    except DigestError as exc:
        # Even a preview needs the key: the send-log key it checks is keyed.
        print(str(exc), file=sys.stderr)
        return 1
    from run.delivery import load_sent
    unsent = [m for m in built if m.key not in load_sent()]
    if args.send and len(unsent) > args.max:
        print(f"NOTHING WAS SENT. {len(unsent)} mailbox(es) are still to be "
              f"announced, above --max {args.max}. Check the preview's "
              f"commonest domains for a list somebody filled by script, then "
              f"raise --max or clean the list.", file=sys.stderr)
        return 1
    try:
        results = send_all(built, provider=provider)
    except DeliveryError as exc:
        print(f"Delivery failed: {exc}", file=sys.stderr)
        return 1

    sent = [r for r in results if r.ok and not r.skipped]
    already = [r for r in results if r.skipped]
    failed = [r for r in results if not r.ok]
    print("=" * 62)
    print(f"{CAMPAIGN} via {provider.name}")
    print(f"  on the list      : {len(addresses)} mailbox(es)")
    print("  commonest domains: " + (", ".join(f"{d} {n}" for d, n in
                                                top_domains(addresses)) or "none"))
    print(f"  sent             : {len(sent)}")
    print(f"  already announced: {len(already)}")
    print(f"  failed           : {len(failed)}")
    from run.trials import canonical_email
    saved = {canonical_email(a) for a in refs}
    print(f"  with their roster: "
          f"{sum(1 for a in addresses if canonical_email(a) in saved)}")
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
SEND_ENV = ("EMAIL_PROVIDER", "EMAIL_FROM", "SENDER_POSTAL_ADDRESS", "LOG_SECRET")
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
