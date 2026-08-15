"""Tuesday batch: one report per subscriber, from the registry.

Usage:
    python -m run.batch [--week N] [--registry PATH] [--skip-ingest]

Groups subscribers by league so each league is ingested exactly once (the
cost NFR: N subscribers in one league cost one pull). Per subscriber it
resolves their own roster from their Sleeper user id, builds the report with
their named rival, and writes HTML + text under ``reports/subscribers/``
(gitignored; filenames carry the Sleeper username, never an email).

One subscriber's bad data must never sink the batch: failures are recorded,
reported in the summary, and exit code 1 flags a partial run.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ingest.pull as ingest_pull
import render.report as render_report
from engine.history import HistoryError
from engine.week_report import (RAW_DIR, WeekReportError, build_week_report,
                                current_nfl_season)
from run.registry import (DEFAULT_REGISTRY, RegistryError, Subscriber,
                          league_pass_seats, load_registry)
from run.delivery import (DRY_OUTBOX, DeliveryError, Message, build_provider,
                          send_all)
from run.subscriptions import DEFAULT_EXPORT, SubscriptionError, resolve_paid_list
from run.week import _current_week, text_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBSCRIBER_REPORTS = REPO_ROOT / "reports" / "subscribers"


def _display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise — a cosmetic path in a
    summary line must never be the thing that raises at the end of a good run."""
    try:
        return f"{path.relative_to(REPO_ROOT)}/"
    except ValueError:
        return str(path)


@dataclass
class BatchResult:
    subscriber: Subscriber
    ok: bool
    detail: str
    html_path: Path | None = None
    message: Message | None = None


def _subject(report: dict) -> str:
    """What lands in the inbox. The rival's name is the reason they open it."""
    meta = report["meta"]
    if meta.get("rivalry_week"):
        return f"Week {meta['week']}: RIVALRY WEEK vs {meta['rival_label']}"
    return f"Week {meta['week']}: your report vs {meta['rival_label']}"


def _my_roster_id(raw_dir: Path, subscriber: Subscriber) -> int:
    """The subscriber's roster in their league, by owner or co-owner match."""
    rosters_path = raw_dir / "league" / subscriber.league_id / "rosters.json"
    if not rosters_path.is_file():
        raise WeekReportError(
            f"league {subscriber.league_id} not cached — ingest before batching")
    rosters = json.loads(rosters_path.read_text(encoding="utf-8"))
    for roster in rosters if isinstance(rosters, list) else []:
        if not isinstance(roster, dict):
            continue
        owners = {roster.get("owner_id")} | set(roster.get("co_owners") or [])
        if subscriber.user_id in {str(o) for o in owners if o}:
            return int(roster["roster_id"])
    raise WeekReportError(
        f"user {subscriber.sleeper_username or subscriber.user_id} owns no "
        f"roster in league {subscriber.league_id} — re-check their signup")


def run_subscriber(subscriber: Subscriber, week: int, template_html: str,
                   require_season: str | None = None) -> BatchResult:
    try:
        my_roster = _my_roster_id(RAW_DIR, subscriber)
        report = build_week_report(
            RAW_DIR, subscriber.league_id, week, my_roster,
            named_rival_owner_id=subscriber.rival_owner_id,
            named_rival_roster_id=subscriber.rival_roster_id,
            require_season=require_season,
        )
    except (WeekReportError, HistoryError) as exc:
        return BatchResult(subscriber, ok=False, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — batch contract: one subscriber's
        # surprise (malformed cache, unicode filename, anything) must never
        # sink the other subscribers' Tuesday reports.
        return BatchResult(subscriber, ok=False, detail=f"unexpected failure: {exc!r}")

    out_dir = SUBSCRIBER_REPORTS / subscriber.league_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"w{week:02d}-{subscriber.slug}"
    html_path = out_dir / f"{stem}.html"
    html = render_report.render(report, template_html)
    text = text_summary(report)
    html_path.write_text(html, encoding="utf-8")
    (out_dir / f"{stem}.txt").write_text(text, encoding="utf-8")

    # The idempotency key is per subscriber, season and week — so a re-run,
    # a resumed workflow, or a second cron firing all resolve to the same send.
    meta_season = report["meta"]["season"]
    message = Message(
        to=subscriber.email,
        subject=_subject(report),
        html=html,
        text=text,
        key=f"{subscriber.league_id}-{meta_season}-w{week:02d}-{subscriber.slug}",
    )

    # Every published probability lands on the league's ledger (principle 2).
    # Guarded separately: the report above is already delivered, and a corrupt
    # shared ledger file must not sink this or any other subscriber's Tuesday.
    ledger_note = ""
    try:
        from engine.ledger import extract_published_calls, ledger_path, record_calls
        from engine.week_report import PROCESSED_DIR
        record_calls(ledger_path(PROCESSED_DIR, subscriber.league_id),
                     extract_published_calls(report))
    except Exception as exc:  # noqa: BLE001 — batch contract
        ledger_note = f" · LEDGER RECORD FAILED: {exc!r}"

    meta = report["meta"]
    published = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    detail = (f"{meta['my_label']} vs {meta['rival_label']}"
              + (" · RIVALRY WEEK" if meta.get("rivalry_week") else "")
              + f" · {published}/{len(report['lineup'])} confidences · "
              f"{len(meta.get('gaps') or [])} gaps" + ledger_note)
    return BatchResult(subscriber, ok=True, detail=detail, html_path=html_path,
                       message=message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, help="default: current NFL week")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--skip-ingest", action="store_true",
                        help="use the existing cache without hitting Sleeper")
    parser.add_argument("--paid-list", type=Path, default=DEFAULT_EXPORT,
                        help="CSV subscriber export, used only when STRIPE_API_KEY "
                             "is unset; cancelled people are skipped either way")
    parser.add_argument("--no-paid-check", action="store_true",
                        help="send to everyone in the registry without checking who paid")
    parser.add_argument("--email-provider", default=None,
                        help="dry (default), resend, postmark, ses or smtp; "
                             "overrides EMAIL_PROVIDER")
    parser.add_argument("--no-send", action="store_true",
                        help="build the reports but skip delivery entirely")
    parser.add_argument("--resend", action="store_true",
                        help="send again even if this week already went out")
    args = parser.parse_args(argv)

    try:
        subscribers = load_registry(args.registry)
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not subscribers:
        print("registry is empty — nothing to do")
        return 0

    # Cancellation must cost the operator nothing: the payment platform stops the
    # billing on its own, and this is how the pipeline learns to stop the reports.
    # Someone who cancelled mid-period still counts — Stripe keeps them active
    # until the period they paid for ends, which is exactly what they bought.
    # Refusing to run without an answer is deliberate: silently mailing people who
    # cancelled is the one failure that turns into chargebacks and screenshots.
    dropped: list[Subscriber] = []
    if not args.no_paid_check:
        try:
            paid = resolve_paid_list(args.paid_list)
        except SubscriptionError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        # PaidList.entitles() knows the three routes: the subscriber's own
        # Stripe customer, a League Pass covering their league, or the email on
        # file. A seat holder never paid us a cent — their commissioner did —
        # so checking the seat's OWN email drops every seat and reports it in
        # the words meant for a cancellation, leaving the pass undeliverable
        # unless the operator disables the gate for everybody.
        entitled = [s for s in subscribers if paid.entitles(s)]
        dropped = [s for s in subscribers if not paid.entitles(s)]
        print(f"Paid check: {len(paid.emails)} entitled subscriber(s) "
              f"(source: {paid.source})")
        if paid.status_column is None:
            print("NOTE: that export has no subscription-status column, so everyone "
                  "listed in it is treated as paying.")
        had_registry = len(subscribers)
        subscribers = entitled
        if dropped:
            print(f"Skipping {len(dropped)} subscriber(s) who are no longer paying: "
                  + ", ".join(s.slug for s in dropped))
        if not subscribers:
            # Everyone in a non-empty registry failing the check at once is far
            # more likely to be a broken entitlement source than a business that
            # lost every customer in one week. Exiting 0 here made that a green
            # cron with an empty inbox — the failure nobody notices until a
            # subscriber asks where their report went.
            print(f"NOTHING TO SEND: all {had_registry} registry entries failed the "
                  f"paid check against {paid.source}.", file=sys.stderr)
            print("  If that is genuinely everyone cancelling, re-run with "
                  "--no-paid-check to confirm. Otherwise the entitlement source is "
                  "wrong or stale — check it before next Tuesday.", file=sys.stderr)
            return 1

    leagues = sorted({s.league_id for s in subscribers})
    if not args.skip_ingest:
        for league_id in leagues:
            code = ingest_pull.main(["--league", league_id])
            if code != 0:
                print(f"ingest failed for league {league_id}; its subscribers "
                      "will fail below", file=sys.stderr)

    week = args.week if args.week is not None else _current_week(RAW_DIR)
    template_html = render_report.TEMPLATE_PATH.read_text(encoding="utf-8")

    # This is the one path that mails strangers, so a league id pointing at a
    # season that is already over must fail loudly rather than render.
    require_season = None if args.week is not None else current_nfl_season(RAW_DIR)
    results = [run_subscriber(s, week, template_html, require_season)
               for s in subscribers]

    line = "=" * 62
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    print(f"\n{line}\nBATCH RUN — week {week}\n{line}")
    print(f"Subscribers: {len(results)} across {len(leagues)} league(s); "
          f"{len(ok)} reports written, {len(failed)} failed")
    for result in results:
        marker = "ok " if result.ok else "FAIL"
        who = result.subscriber.slug
        print(f"  [{marker}] {who}: {result.detail}")
    # League Pass coverage: the commissioner paid for the whole league, so an
    # unclaimed seat is someone who was promised a report and isn't getting one.
    seats = league_pass_seats(subscribers)
    for league_id, members in sorted(seats.items()):
        rosters_file = RAW_DIR / "league" / league_id / "rosters.json"
        total = None
        if rosters_file.is_file():
            try:
                total = len(json.loads(rosters_file.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                total = None
        payer = members[0].covered_by
        claimed = f"{len(members)} of {total}" if total else str(len(members))
        print(f"League Pass · league {league_id}: {claimed} seats claimed "
              f"(paid by {payer})")
        if total and len(members) < total:
            print(f"    {total - len(members)} team(s) haven't signed up yet — "
                  "they get nothing until they pick a rival.")

    # Delivery. Dry-run by default: a misconfigured cron must never mail people
    # by accident, so sending is opt-in via EMAIL_PROVIDER.
    if ok and not args.no_send:
        try:
            provider = build_provider(args.email_provider)
        except DeliveryError as exc:
            print(f"Delivery not configured: {exc}", file=sys.stderr)
            return 1
        sends = send_all([r.message for r in ok if r.message], provider=provider,
                         resend_anyway=args.resend)
        delivered = [s for s in sends if s.ok and not s.skipped]
        skipped = [s for s in sends if s.skipped]
        # Deliberately NOT named `failed`: that name already holds the
        # subscribers whose report could not be BUILT, and rebinding it here
        # made a run where somebody's report failed but every send succeeded
        # exit 0 — a green cron with a subscriber silently missing.
        send_failures = [s for s in sends if not s.ok]
        print(f"Delivery via {provider.name}: {len(delivered)} sent, "
              f"{len(skipped)} already sent, {len(send_failures)} failed")
        for send in send_failures:
            # The idempotency key carries the Sleeper username, never the email
            # — this line lands in a CI log, and the registry is gitignored so
            # subscriber addresses never leave the machine.
            print(f"    FAILED {send.message.key}: {send.detail}", file=sys.stderr)
        if provider.name == "dry":
            print(f"    (dry run — nothing left this machine; drafts in "
                  f"{_display(DRY_OUTBOX)})")
        if send_failures:
            return 1

    if ok:
        print(f"Reports under: {_display(SUBSCRIBER_REPORTS)}")
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
