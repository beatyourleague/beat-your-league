"""The change notice: "we email subscribers before it takes effect" (D6).

Usage:
    python -m run.notice --page terms --effective 2026-11-01 \\
        --summary "What changes, in one or two plain sentences." [--send]

``site/terms.html`` and ``site/privacy.html`` both promise that a change which
materially affects a subscriber is emailed to them BEFORE it takes effect.
Nothing could send that email: the only route was exporting addresses from
Stripe by hand. This mails one notice to every subscriber and League Pass seat
entitled to reports today:

- **Before, never after.** ``--effective`` must be a date after today (UTC);
  a notice about a change already in force is not the promise.
- **One per mailbox per change.** The send-log key is
  ``notice-{page}-{effective}-{keyed code}`` — a code that cannot be matched
  back to the address without LOG_SECRET (run/digest.py) — so a re-run never
  mails twice and somebody with two teams gets one notice.
- **The stop list is honoured** (run/delivery.send_all), every email carries
  the sender line and the way out, and the summary is the operator's own words
  — never generated, never more than what changed.
- **Entitled only.** The same paid check the Tuesday run uses
  (run/subscriptions.resolve_paid_list): nobody who has left is mailed, and an
  unreadable entitlement source refuses rather than guessing.

Dry by default, like every sender here. Runs from the ``notice`` workflow
(workflow_dispatch) or locally with the same secrets.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PAGES = {"terms": ("our terms", "terms.html"),
         "privacy": ("our privacy policy", "privacy.html")}
SEND_ENV = ("EMAIL_PROVIDER", "EMAIL_FROM", "SENDER_POSTAL_ADDRESS", "LOG_SECRET")
MAX_SUMMARY = 600


class NoticeError(RuntimeError):
    pass


def notice_key(page: str, effective: date, email: str) -> str:
    from run.digest import address
    return f"notice-{page}-{effective.isoformat()}-{address(email)}"


def recipients(subscribers, paid) -> list:
    """Every entitled row, one per mailbox (canonical address), seats too."""
    from run.trials import canonical_email
    seen: set[str] = set()
    out = []
    for sub in subscribers:
        if not paid.entitles(sub):
            continue
        mailbox = canonical_email(sub.email)
        if mailbox in seen:
            continue
        seen.add(mailbox)
        out.append(sub)
    return out


def notice_message(sub, page: str, effective: date, summary: str, site_url: str):
    """One notice, both halves, in the seat notes' shell (render/seat_claim)."""
    from render.email import BASE, NAVY
    from render.report import ONCE, cancel_html, cancel_lines, esc, unsubscribe_target
    from render.seat_claim import _footer_lines, _para, _shell
    from run.delivery import Message
    name, file = PAGES[page]
    # A seat's stop route, a one-payment pass's stop route (nothing to
    # cancel), or a subscription's billing page — never a billing page for a
    # pass that has none (final review COPY-1).
    seat = True if sub.is_league_seat else (ONCE if getattr(sub, "one_time", False) else False)
    when = f"{effective:%B} {effective.day}, {effective.year}"
    url = f"{site_url.rstrip('/')}/{file}" if site_url.startswith("https://") else ""
    subject = f"We're updating {name} on {when}"
    lede = (f"We're changing {name}. The new version takes effect on {when}; "
            f"this email is the notice we promised before it does.")
    read = (f"The full text, with its new date at the top: {url}" if url
            else f"The full text is on our site's {file} page.")
    leave = ("If you'd rather not continue under the new version, you can stop "
             "before then — the way out is at the bottom of this email.")
    body = (_para(lede) + _para(f"What changes: {summary}")
            + (f'<p style="{BASE}margin:0 0 14px 0;">The full text, with its new '
               f'date at the top: <a href="{esc(url)}" style="color:{NAVY};">'
               f'{esc(url)}</a></p>' if url
               else _para(read))
            + _para(leave) + cancel_html(seat=seat))
    text = "\n\n".join([lede, f"What changes: {summary}", read, leave,
                        *cancel_lines(seat=seat), *_footer_lines()]) + "\n"
    return Message(to=sub.email, subject=subject,
                   html=_shell(subject, f"{name.capitalize()} change on {when}", body),
                   text=text, key=notice_key(page, effective, sub.email),
                   unsubscribe=unsubscribe_target(seat=seat))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--page", choices=sorted(PAGES), required=True)
    parser.add_argument("--effective", type=date.fromisoformat, required=True,
                        help="the date the change takes effect (must be after today)")
    parser.add_argument("--summary", required=True,
                        help="what changes, in the operator's own plain words")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    today = args.today or datetime.now(timezone.utc).date()
    if args.effective <= today:
        print(f"The change must take effect AFTER today ({today}); a notice "
              f"about a change already in force is not the one we promised. "
              f"Nothing was sent.", file=sys.stderr)
        return 2
    summary = " ".join(args.summary.split())
    if not summary or len(summary) > MAX_SUMMARY:
        print(f"--summary must be 1-{MAX_SUMMARY} characters.", file=sys.stderr)
        return 2
    if args.send:
        missing = [n for n in SEND_ENV if not os.environ.get(n, "").strip()]
        if missing:
            print("Not sent — missing: " + ", ".join(missing), file=sys.stderr)
            return 1

    from run.delivery import (DRY_PROVIDER, DeliveryError, build_provider,
                              send_all)
    from run.digest import DigestError
    from run.rosters import RosterRegistryError, load_rosters
    from run.subscriptions import SubscriptionError, resolve_paid_list
    try:
        subscribers = load_rosters(args.registry)
        paid = resolve_paid_list()
    except (RosterRegistryError, SubscriptionError, OSError) as exc:
        # Refuse: guessing who is entitled mails people who left.
        print(f"Could not tell who is subscribed ({exc}); nothing was sent.",
              file=sys.stderr)
        return 1
    people = recipients(subscribers, paid)
    try:
        messages = [notice_message(s, args.page, args.effective, summary,
                                   os.environ.get("SITE_URL", ""))
                    for s in people]
    except DigestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    line = "=" * 62
    print(f"{line}\nCHANGE NOTICE · {args.page} · effective {args.effective}\n{line}")
    print(f"{len(people)} entitled mailbox(es) of {len(subscribers)} registry row(s)")
    try:
        provider = build_provider(None if args.send else DRY_PROVIDER)
    except DeliveryError as exc:
        print(f"Delivery not configured: {exc}", file=sys.stderr)
        return 1
    results = send_all(messages, provider=provider)
    sent = sum(1 for r in results if r.ok and not r.skipped)
    stopped = sum(1 for r in results if r.suppressed)
    again = sum(1 for r in results if r.skipped and not r.suppressed)
    failed = [r for r in results if not r.ok]
    for result in failed:
        print(f"  ! not sent ({result.message.key}): {result.detail}", file=sys.stderr)
    if provider.name == DRY_PROVIDER:
        print(f"(dry run — {len(messages)} drafted, NOTHING WAS SENT. Pass --send.)")
    else:
        print(f"{sent} sent, {again} already notified, {stopped} on the stop list")
    print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
