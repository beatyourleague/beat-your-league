"""Tuesday, for the product that never reads a league.

Usage:
    python -m run.tuesday [--week N] [--registry PATH] [--allow-dry]

The counterpart to ``run/batch.py``, which drives the Sleeper-shaped registry
and is the path PLAN §0 is retiring. This one reads ``data/registry/rosters.json``
— rosters the subscribers typed, carried here by their own payments — and never
imports anything that talks to a league platform. ``test_no_sleeper_in_the_paid
_path`` walks the imports reachable from a runner; this runner's set is empty by
construction, and a test pins that.

Shape of a run:

1. Load the roster registry. One bad row fails the whole file on purpose — a
   silently skipped paying subscriber is the one unacceptable failure — which is
   why ``run/sync.py`` validates every row before writing one.
2. Ask who is entitled. Refusing to run without an answer is deliberate:
   silently mailing people who cancelled is the failure that becomes a
   chargeback. A League Pass seat is entitled through its PAYER, never through
   itself.
3. Load the week ONCE. Every download is per-week, not per-subscriber, so a
   hundred subscribers cost what one does.
4. Build, render, record, send — per subscriber, with failures contained. One
   subscriber's malformed roster must never sink everybody else's Tuesday.

Dry-run is the default and never the right accident: with no ``EMAIL_PROVIDER``
this writes drafts and exits 1 unless ``--allow-dry`` was passed.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import render.report as render_report
from render.report import cancel_destination
from render.email import render_email, subject_for, text_summary
from run.delivery import (DRY_OUTBOX, DRY_PROVIDER, DeliveryError, Message,
                          build_provider, send_all)
from run.rosters import (DEFAULT_ROSTERS, RosterRegistryError, RosterSubscriber,
                         league_pass_seats, load_rosters)
from run.solo import CACHE_DIR, SoloError, WeekData, load_week_data, report_for
from run.updates import update_url
from run.subscriptions import DEFAULT_EXPORT, SubscriptionError, resolve_paid_list

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBSCRIBER_REPORTS = REPO_ROOT / "reports" / "subscribers"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


def _display(path: Path) -> str:
    """Repo-relative when it can be. A cosmetic path in a summary line must
    never be the thing that raises at the end of a good run."""
    try:
        return f"{path.relative_to(REPO_ROOT)}/"
    except ValueError:
        return str(path)


def _mask(email: str) -> str:
    """Operator-facing only. Run summaries land in a CI log."""
    if "@" not in email:
        return "unknown"
    name, domain = email.split("@", 1)
    return f"{name[:1]}***@{domain}"


@dataclass
class RunResult:
    subscriber: RosterSubscriber
    ok: bool
    detail: str
    html_path: Path | None = None
    message: Message | None = None


def run_subscriber(subscriber: RosterSubscriber, data: WeekData,
                   template_html: str, out_dir: Path = SUBSCRIBER_REPORTS,
                   processed_dir: Path = PROCESSED_DIR,
                   record: bool = True) -> RunResult:
    """One roster's week: build, write the archive, prepare the email.

    ``record`` is False when nothing is being mailed. A call is PUBLISHED when
    it reaches a subscriber, and the ledger is the record of what was published
    — so a preview that writes rows claims we published calls nobody received,
    permanently, because RULE L4 makes a graded entry immutable. Reproduced:
    `--no-send` on an arbitrary week wrote 4 rows into the real store.
    """
    try:
        report = report_for(subscriber.spec(), data,
                            league_size=subscriber.league_size,
                            processed_dir=processed_dir)
        # NO roster-update credential travels in a report. It used to render
        # directly beneath _forward_line(), which invites the subscriber to
        # forward this very file to their league — so the product asked people
        # to hand a leaguemate a token that rewrites their own lineup for every
        # remaining Tuesday. In a product framed around league rivalry, the
        # recipient is the most motivated adversary there is.
        #
        # Removing it costs nothing today: FORM_ENDPOINT is empty, so self-serve
        # updates were not running, and the FAQ already answers roster changes
        # with "reply to any file". Restoring it safely means CONFIRMING the
        # change — mail the address already on the registry row and apply only
        # when that is clicked — so a forwarded report grants nothing and the
        # real subscriber is told when somebody tries. Found Aug 27 2026.
        report["meta"]["update_url"] = None
    except SoloError as exc:
        return RunResult(subscriber, ok=False, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — batch contract: one subscriber's
        # surprise (a roster the directory lost, a unicode label, anything)
        # must never sink the other subscribers' Tuesday.
        return RunResult(subscriber, ok=False, detail=f"unexpected failure: {exc!r}")

    week = data.week
    out_dir = Path(out_dir) / data.season
    out_dir.mkdir(parents=True, exist_ok=True)
    # The slug is a digest of the ref: stable week to week, and carrying no
    # email, because these filenames outlive the run and land in artifacts.
    stem = f"w{week:02d}-{subscriber.slug}"
    html_path = out_dir / f"{stem}.html"
    text = text_summary(report)
    html_path.write_text(render_report.render(report, template_html),
                         encoding="utf-8")
    (out_dir / f"{stem}.txt").write_text(text, encoding="utf-8")

    message = Message(
        to=subscriber.email,
        subject=subject_for(report),
        # The email-safe rendering, not the browser-grade file written above:
        # per-subscriber reports are private, so the email must BE the report.
        html=render_email(report),
        text=text,
        # Idempotent per (season, week, subscription), so a re-run, a resumed
        # workflow or a double-fired cron cannot mail the same week twice.
        key=f"{data.season}-w{week:02d}-{subscriber.slug}",
        # Every commercial email needs a machine-readable way out, and this
        # product had none: a delivered draft carried only From/To/Subject/MIME.
        # For a PAID subscription there is no free list to leave — unsubscribing
        # and cancelling are the same act — so it points at where the money
        # actually stops.
        unsubscribe=cancel_destination()[0] or None,
    )

    # Every published probability lands on the ledger (principle 2) at the
    # moment it is published — a call not recorded now cannot be recovered
    # later. Guarded separately: the report above is already built, and a
    # corrupt shared ledger must not sink this or anybody else's Tuesday.
    if not record:
        ledger_note = " · nothing recorded (not sending)"
    else:
        try:
            from engine.ledger import (extract_published_calls, ledger_path,
                                       record_calls)
            # One store per SCORING PRESET, not one per subscriber. Two
            # subscribers on the same preset who make the same call made ONE
            # call and their ids agree by construction; two on different presets
            # did NOT — the probabilities differ and so does the answer — which
            # is why the store name carries the preset (engine/ledger.py
            # _call_id, engine/subscriber.py build_season).
            added = record_calls(
                ledger_path(Path(processed_dir), report["meta"]["league_id"]),
                extract_published_calls(report))
            ledger_note = f" · {added} new ledger row(s)" if added else ""
        except Exception as exc:  # noqa: BLE001 — batch contract
            ledger_note = f" · LEDGER RECORD FAILED: {exc!r}"

    published = sum(1 for slot in report["lineup"]
                    if slot.get("confidence") is not None)
    detail = (f"{published}/{len(report['lineup'])} confidences · "
              f"{len(report['meta'].get('gaps') or [])} gaps" + ledger_note)
    return RunResult(subscriber, ok=True, detail=detail, html_path=html_path,
                     message=message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, help="default: the current NFL week")
    parser.add_argument("--season", help="default: the current NFL season")
    parser.add_argument("--registry", type=Path, default=None,
                        help=f"default: {_display(DEFAULT_ROSTERS.parent)}rosters.json")
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--out", type=Path, default=SUBSCRIBER_REPORTS)
    # Threaded rather than baked into a signature: a module constant used as a
    # default argument cannot be redirected by a caller or a test, which is what
    # once let a pipeline run write over the real registry.
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR,
                        help="where the ledger lives")
    parser.add_argument("--paid-list", type=Path, default=DEFAULT_EXPORT,
                        help="CSV export, used only when STRIPE_API_KEY is unset")
    parser.add_argument("--no-paid-check", action="store_true",
                        help="send to everyone in the registry without checking who paid")
    parser.add_argument("--email-provider", default=None,
                        help="dry (default), resend, postmark, ses or smtp")
    parser.add_argument("--no-send", action="store_true",
                        help="build the reports but skip delivery entirely")
    parser.add_argument("--allow-dry", action="store_true",
                        help="preview the emails without sending")
    parser.add_argument("--resend", action="store_true",
                        help="send again even if this week already went out")
    args = parser.parse_args(argv)

    try:
        subscribers = load_rosters(args.registry)
    except RosterRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not subscribers:
        print("roster registry is empty — nothing to do")
        return 0

    if not args.no_paid_check:
        try:
            paid = resolve_paid_list(args.paid_list)
        except SubscriptionError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        entitled = [s for s in subscribers if paid.entitles(s)]
        dropped = [s for s in subscribers if not paid.entitles(s)]
        print(f"Paid check: {len(paid.emails)} entitled subscriber(s) "
              f"(source: {paid.source})")
        if paid.status_column is None:
            print("NOTE: that export has no subscription-status column, so "
                  "everyone listed in it is treated as paying.")
        if paid.refunded:
            # RULE E1. Said out loud, because a refund leaves the subscription
            # ACTIVE in Stripe — so from the Dashboard this person still looks
            # like a customer, and the only place the revocation is visible is
            # here.
            print(f"{len(paid.refunded)} subscription(s) were refunded in full "
                  f"and are no longer served: " + ", ".join(sorted(paid.refunded)))
        had_registry = len(subscribers)
        subscribers = entitled
        if dropped:
            print(f"Skipping {len(dropped)} subscriber(s) who are no longer "
                  f"paying: " + ", ".join(s.slug for s in dropped))
        if not subscribers:
            # Everyone in a non-empty registry failing at once is far more
            # likely to be a broken entitlement source than a business that lost
            # every customer in a week. Exiting 0 made that a green cron with an
            # empty inbox — the failure nobody notices until somebody asks.
            print(f"NOTHING TO SEND: all {had_registry} registry entries failed "
                  f"the paid check against {paid.source}.", file=sys.stderr)
            print("  If that is genuinely everyone cancelling, re-run with "
                  "--no-paid-check to confirm. Otherwise the entitlement source "
                  "is wrong or stale — check it before next Tuesday.",
                  file=sys.stderr)
            return 1

    # One load for the whole run. Everything in it is per-week rather than
    # per-subscriber, which is the cost NFR made structural.
    try:
        data = load_week_data(args.cache, args.season, args.week)
    except SoloError as exc:
        print(f"could not load this week's data: {exc}", file=sys.stderr)
        return 1

    # Is anything actually going to be mailed? Decided BEFORE the reports are
    # built, because it decides whether their calls enter the public record.
    # A preview must leave no trace: RULE L4 makes a recorded call immutable,
    # so a dry run that records claims we published calls nobody received.
    sending = not args.no_send
    if sending:
        try:
            sending = build_provider(args.email_provider).name != DRY_PROVIDER
        except DeliveryError:
            sending = False

    template_html = render_report.TEMPLATE_PATH.read_text(encoding="utf-8")
    results = [run_subscriber(s, data, template_html, out_dir=args.out,
                              processed_dir=args.processed_dir, record=sending)
               for s in subscribers]

    line = "=" * 62
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    print(f"\n{line}\nTUESDAY RUN — {data.season} week {data.week}\n{line}")
    print(f"Subscribers: {len(results)}; {len(ok)} reports written, "
          f"{len(failed)} failed")
    for result in results:
        marker = "ok " if result.ok else "FAIL"
        print(f"  [{marker}] {result.subscriber.slug}: {result.detail}")
    print(f"  {data.attribution}")

    # League Pass coverage. There is no league id to count against any more, so
    # this reports what the pass is actually carrying rather than seats-claimed
    # out of a league size we cannot see.
    for payer, seats in sorted(league_pass_seats(subscribers).items()):
        print(f"League Pass · {_mask(payer)}: {len(seats)} seat(s) claimed")

    if ok and not args.no_send:
        try:
            provider = build_provider(args.email_provider)
        except DeliveryError as exc:
            print(f"Delivery not configured: {exc}", file=sys.stderr)
            return 1
        implicit_dry = (provider.name == DRY_PROVIDER
                        and not args.email_provider
                        and not os.environ.get("EMAIL_PROVIDER"))
        if implicit_dry and not args.allow_dry:
            print(f"NOTHING WAS SENT. {len(ok)} subscriber report(s) were built "
                  f"but EMAIL_PROVIDER is not set, so delivery fell back to a "
                  f"dry run. Set EMAIL_PROVIDER (and its key) to mail them, or "
                  f"pass --allow-dry to preview.", file=sys.stderr)
            return 1
        sends = send_all([r.message for r in ok if r.message], provider=provider,
                         resend_anyway=args.resend)
        delivered = [s for s in sends if s.ok and not s.skipped]
        skipped = [s for s in sends if s.skipped]
        # Deliberately NOT named `failed`: that name holds the subscribers whose
        # report could not be BUILT, and rebinding it made a run where somebody's
        # report failed but every send succeeded exit 0.
        send_failures = [s for s in sends if not s.ok]
        print(f"Delivery via {provider.name}: {len(delivered)} sent, "
              f"{len(skipped)} already sent, {len(send_failures)} failed")
        for send in send_failures:
            # The idempotency key carries the ref digest, never an address.
            print(f"    FAILED {send.message.key}: {send.detail}", file=sys.stderr)
        if provider.name == DRY_PROVIDER:
            print(f"    (dry run — nothing left this machine; drafts in "
                  f"{_display(DRY_OUTBOX)})")
        if send_failures:
            return 1

    if ok:
        print(f"Reports under: {_display(Path(args.out))}")
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
