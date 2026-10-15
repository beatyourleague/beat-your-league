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
4. Build and render per subscriber, with failures contained. One subscriber's
   malformed roster must never sink everybody else's Tuesday. A subscriber
   whose report is already in the send log is not rebuilt at all (unless
   ``--resend``): the 16:00 retry and GitHub's late backup run make a second
   Tuesday run routine, and a rebuild after a line move or a stat correction
   is a DIFFERENT report from the one in the inbox.
5. Send, then record. A call is published when the email carrying it is
   DELIVERED, so only the calls of messages delivered in this run reach the
   ledger (``record_delivered``). Recording at build time put a retry's
   rebuilt, never-sent picks on the public record beside the ones that were
   mailed — reproduced: "Maye over Prescott" mailed, "Prescott over Maye"
   recorded too, one of them bound to hit (launch review OPS-1, Oct 2026).

Dry-run is the default and never the right accident: with no ``EMAIL_PROVIDER``
this writes drafts and exits 1 unless ``--allow-dry`` was passed.

Before launch is not a failure: with no registry file AND no Stripe key nobody
can have paid, so the run says so and exits 0 (``run.watchdog.not_configured``)
instead of filing a "failed" issue every Tuesday until checkout opens. A
registry that exists but cannot be read still fails.

A run that could mail leaves a marker in the send log (``run.watchdog.mark_run``)
once it gets as far as sending — with what it sent and what failed — so the
daily watchdog can tell a Tuesday that ran from a Tuesday GitHub never started.
A run that failed still marks: it has filed its own issue, and the watchdog's
question is only whether it ran.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import render.report as render_report
from render.report import cancel_destination
from render.email import render_email, subject_for, text_summary
from run.delivery import (DRY_OUTBOX, DRY_PROVIDER, DeliveryError, Message,
                          build_provider, send_all)
from run.rosters import (DEFAULT_ROSTERS, RosterRegistryError, RosterSubscriber,
                         league_pass_seats, load_rosters)
from run.solo import (CACHE_DIR, SeasonOver, SoloError, WeekData, _prior_form,
                       current_season, current_week, load_week_data, report_for,
                       season_over, week_has_kicked_off)
from run.saturday import PLANS_DIR, build_plan, first_plans_dir, write_plan
from run.updates import public_update_url
from run.subscriptions import DEFAULT_EXPORT, SubscriptionError, resolve_paid_list
from run.watchdog import NOT_CONFIGURED_NOTE, TUESDAY, mark_run, not_configured

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


def report_key(season: str, week: int, slug: str) -> str:
    """A subscriber's weekly report in the send log: per (season, week,
    subscription), carrying no address. One definition, because the send, the
    don't-rebuild check here and the first email intake sends at purchase
    must all agree on it."""
    return f"{season}-w{int(week):02d}-{slug}"


@dataclass
class RunResult:
    subscriber: RosterSubscriber
    ok: bool
    detail: str
    html_path: Path | None = None
    message: Message | None = None
    # The lineup as sent, for the Saturday final check (run/saturday.py).
    plan: dict | None = None
    # What this report publishes, and the ledger store it belongs in. Nothing
    # here is recorded until the message carrying it is delivered
    # (record_delivered); a report built for a preview carries none at all.
    calls: list = field(default_factory=list)
    store: str | None = None


def run_subscriber(subscriber: RosterSubscriber, data: WeekData,
                   template_html: str, out_dir: Path = SUBSCRIBER_REPORTS,
                   processed_dir: Path = PROCESSED_DIR,
                   record: bool = True,
                   plans_dir: Path | None = None,
                   first_plans: Path | None = None) -> RunResult:
    """One roster's week: build, write the archive, prepare the email.

    Writes nothing to the public ledger. ``record`` says whether this report's
    calls may EVER be recorded: False when nothing is being mailed, and then
    the result carries no calls for anything downstream to record. A call is
    PUBLISHED when it reaches a subscriber, and the ledger is the record of
    what was published — so a preview that writes rows claims we published
    calls nobody received, permanently, because RULE L4 makes a graded entry
    immutable. Reproduced: `--no-send` on an arbitrary week wrote 4 rows into
    the real store. With ``record`` True the calls ride on the result and the
    caller records them once the send has landed (``record_delivered``).
    """
    projections: dict[str, float] = {}
    try:
        report = report_for(subscriber.spec(), data,
                            league_size=subscriber.league_size,
                            processed_dir=processed_dir,
                            projections_out=projections)
        # The PUBLIC update link (run/updates.py, confirm-by-email): it grants
        # nothing, so a report forwarded to the league stays safe. The
        # tokenised link it replaced put a roster-write credential in a file
        # built to be forwarded (removed Aug 27 2026). None until the site,
        # the form backend and the signing secret all exist.
        # The plan decides the season-end billing sentence the last report
        # carries (render/report.season_end_lines).
        report["meta"]["plan"] = subscriber.plan
        report["meta"]["update_url"] = public_update_url(
            os.environ.get("SITE_URL", ""), os.environ.get("UPDATE_SECRET", ""),
            os.environ.get("FORM_ENDPOINT", ""))
        # The Receipts are THIS subscriber's calls (engine/own_record.py),
        # never the shared preset ledger counted as if it were theirs. With no
        # plans stored yet it is the honest empty state.
        from engine.own_record import own_record
        from run.saturday import load_plans
        report["receipts"] = own_record(
            load_plans(plans_dir, data.season, subscriber.slug, also=first_plans)
            if plans_dir is not None else [],
            data.weekly, subscriber.spec().rule, data.week)
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
        key=report_key(data.season, week, subscriber.slug),
        # Every commercial email needs a machine-readable way out, and this
        # product had none: a delivered draft carried only From/To/Subject/MIME.
        # For a PAID subscription there is no free list to leave — unsubscribing
        # and cancelling are the same act — so it points at where the money
        # actually stops.
        unsubscribe=cancel_destination()[0] or None,
    )

    # Every published probability lands on the ledger (principle 2) at the
    # moment it is published — which is DELIVERY, so they are carried out of
    # here and recorded after the send. Read here because the report is in
    # hand; guarded separately, because the report above is already built and
    # an unreadable call must not sink this or anybody else's Tuesday.
    calls: list = []
    store: str | None = None
    if not record:
        ledger_note = " · nothing recorded (not sending)"
    else:
        try:
            from engine.ledger import extract_published_calls
            # One store per SCORING PRESET (and size), not one per subscriber.
            # Two subscribers on the same preset who make the same call made
            # ONE call and their ids agree by construction; two on different
            # presets did NOT — the probabilities differ and so does the answer
            # — which is why the store name carries the preset
            # (engine/ledger.py _call_id, engine/subscriber.py build_season).
            calls = extract_published_calls(report)
            store = str(report["meta"]["league_id"])
            ledger_note = ""
        except Exception as exc:  # noqa: BLE001 — batch contract
            ledger_note = f" · LEDGER CALLS UNREADABLE: {exc!r}"

    try:
        spec = subscriber.spec()
        plan = build_plan(
            report, projections, _prior_form(data.prior, spec.rule),
            {pid: data.availability.classify(pid).status.value
             for pid in spec.player_ids},
            subscriber.slug)
    except Exception as exc:  # noqa: BLE001 — the report is built; Saturday can do without
        plan = None
        # Said out loud: a subscriber with no plan never hears about Friday's
        # news, and nothing else would tell anyone.
        plan_note = f" · PLAN NOT SAVED ({type(exc).__name__}: {exc})"
    else:
        plan_note = ""

    published = sum(1 for slot in report["lineup"]
                    if slot.get("confidence") is not None)
    detail = (f"{published}/{len(report['lineup'])} confidences · "
              f"{len(report['meta'].get('gaps') or [])} gaps" + ledger_note + plan_note)
    return RunResult(subscriber, ok=True, detail=detail, html_path=html_path,
                     message=message, plan=plan, calls=calls, store=store)


def record_delivered(results: Iterable[RunResult], delivered: Iterable[str],
                     processed_dir: Path) -> tuple[int, list[str]]:
    """Put on the public ledger the calls of every report whose email was
    DELIVERED in this run, and nothing else. -> (rows added, problems).

    ``delivered`` is the keys of messages that left in THIS run — never the
    ones skipped as already sent, because a skipped message's report was
    rebuilt now and may not be the one in the inbox. A store that cannot be
    written is reported per report and never stops the others; record_calls
    is idempotent by call id, so two subscribers making the same call record
    one row. Shared with run/intake.py's first email, the other place a
    week's report is mailed."""
    from engine.ledger import ledger_path, record_calls
    keys = set(delivered)
    added, problems = 0, []
    for result in results:
        if (result.message is None or result.message.key not in keys
                or not result.calls or not result.store):
            continue
        try:
            added += record_calls(ledger_path(Path(processed_dir), result.store),
                                  result.calls)
        except Exception as exc:  # noqa: BLE001 — batch contract
            problems.append(f"{result.message.key}: {exc!r}")
    return added, problems


def paid_subscribers(subscribers: list[RosterSubscriber], paid_list: Path,
                     no_paid_check: bool = False) -> list[RosterSubscriber] | None:
    """The subscribers entitled to mail this run, or None when that cannot be
    answered (reported on stderr). Shared with the Saturday final check: the
    rule for who gets mailed must not have two copies to drift apart.
    """
    if no_paid_check:
        return subscribers
    try:
        paid = resolve_paid_list(paid_list)
    except SubscriptionError as exc:
        print(str(exc), file=sys.stderr)
        return None
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
        return None
    return subscribers


def _mails_for_real(args) -> bool:
    """Would this run put messages in inboxes? Not for --no-send, a dry
    provider, or a provider that cannot be built. Decides both whether calls
    enter the public record and whether the run may leave its marker."""
    if args.no_send:
        return False
    try:
        return build_provider(args.email_provider).name != DRY_PROVIDER
    except DeliveryError:
        return False


def _mark_finished(season: str, week: int, summary: str = "") -> None:
    """Best effort: a marker that fails to write costs a false alarm from the
    watchdog tomorrow, never a send, so it is said and the run carries on."""
    try:
        if mark_run(TUESDAY, season, week, summary=summary):
            print(f"Marked {season} week {week}'s Tuesday run as having run"
                  + (f" ({summary})." if summary else "."))
    except OSError as exc:
        print(f"could not mark the Tuesday run as finished ({exc}); the "
              f"watchdog may report this week as missed", file=sys.stderr)


def _mark_nobody_to_mail(args) -> None:
    """A Tuesday with an empty registry still RAN. Without its marker, the
    first subscriber who joins after that week's kickoff (and so gets the
    roster report, not this week's) makes the watchdog report a run that was
    never missed."""
    if not _mails_for_real(args):
        return
    try:
        season = str(args.season or current_season(args.cache))
        if not args.week and season_over(args.cache, season):
            return
        week = int(args.week or current_week(args.cache, season))
    except Exception as exc:  # noqa: BLE001 — a marker never fails the run
        print(f"could not tell which week this was, so no marker was left "
              f"({exc})", file=sys.stderr)
        return
    _mark_finished(season, week, "nobody to mail")


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
    parser.add_argument("--plans-dir", type=Path, default=None,
                        help="where the Saturday final check reads the lineups "
                             "sent (default: data/plans/, real sends only)")
    args = parser.parse_args(argv)

    if not_configured(args.registry):
        print(f"No reports this week: {NOT_CONFIGURED_NOTE}")
        return 0
    try:
        subscribers = load_rosters(args.registry)
    except RosterRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not subscribers:
        print("roster registry is empty — nothing to do")
        _mark_nobody_to_mail(args)
        return 0

    subscribers = paid_subscribers(subscribers, args.paid_list,
                                   args.no_paid_check)
    if subscribers is None:
        return 1

    # One load for the whole run. Everything in it is per-week rather than
    # per-subscriber, which is the cost NFR made structural.
    try:
        data = load_week_data(args.cache, args.season, args.week)
    except SeasonOver as exc:
        # Not a failure: the cron keeps firing every Tuesday of the offseason.
        print(f"No reports this week: {exc}.")
        return 0
    except SoloError as exc:
        print(f"could not load this week's data: {exc}", file=sys.stderr)
        return 1

    # Never a report about games already underway. The Worker starts this run
    # on time and GitHub's own schedule is the backup — which can fire hours
    # late — and a hand re-run after Thursday night's kickoff would publish
    # (and record, permanently) "predictions" about a game being played. A
    # derived week that has kicked off is a quiet exit; the watchdog is what
    # alarms if the on-time run never happened. An explicit --week is a
    # deliberate rebuild and is allowed (launch audit, Oct 2026).
    if args.week is None and week_has_kicked_off(args.cache, data.season, data.week):
        print(f"No reports sent: week {data.week} has already kicked off, so a "
              f"report now would be about games underway. If this week's reports "
              f"never went out, the watchdog says so.")
        return 0

    # Is anything actually going to be mailed? Decided BEFORE the reports are
    # built, because it decides whether their calls enter the public record.
    # A preview must leave no trace: RULE L4 makes a recorded call immutable,
    # so a dry run that records claims we published calls nobody received.
    sending = _mails_for_real(args)

    # Never rebuild a report that is already in an inbox. The 16:00 retry and
    # GitHub's late backup make a second run every Tuesday routine, and by
    # then the market lines (games.csv) or a stat correction may have moved:
    # the rebuilt report is a different report, with different picks, and
    # nothing about it was published. Skipped before the build, so it costs
    # nothing and cannot leak into the ledger, the archive or a plan. A
    # deliberate --resend rebuilds; --no-send is a build for inspection.
    already: list[RosterSubscriber] = []
    if not (args.no_send or args.resend):
        from run.delivery import load_sent
        in_log = load_sent()
        already = [s for s in subscribers
                   if report_key(data.season, data.week, s.slug) in in_log]
    done = {s.key for s in already}

    template_html = render_report.TEMPLATE_PATH.read_text(encoding="utf-8")
    results = [run_subscriber(s, data, template_html, out_dir=args.out,
                              processed_dir=args.processed_dir, record=sending,
                              plans_dir=args.plans_dir or PLANS_DIR,
                              first_plans=first_plans_dir(args.registry))
               for s in subscribers if s.key not in done]

    line = "=" * 62
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    print(f"\n{line}\nTUESDAY RUN — {data.season} week {data.week}\n{line}")
    print(f"Subscribers: {len(results) + len(already)}; {len(ok)} reports "
          f"written, {len(failed)} failed"
          + (f", {len(already)} already sent this week (not rebuilt)"
             if already else ""))
    for result in results:
        marker = "ok " if result.ok else "FAIL"
        print(f"  [{marker}] {result.subscriber.slug}: {result.detail}")
    print(f"  {data.attribution}")

    # League Pass coverage. There is no league id to count against any more, so
    # this reports what the pass is actually carrying rather than seats-claimed
    # out of a league size we cannot see.
    for payer, seats in sorted(league_pass_seats(subscribers).items()):
        print(f"League Pass · {_mask(payer)}: {len(seats)} seat(s) claimed")

    delivered, skipped, send_failures = [], [], []
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
        # The public record: the calls of what was DELIVERED just now, and
        # nothing else — not a draft, not a failed send, and not a message
        # skipped as already sent, whose report was rebuilt now and may differ
        # from the one in the inbox. `sending` is the second gate: a dry
        # provider's "delivered" drafts carry no calls in the first place.
        if sending:
            added, problems = record_delivered(
                ok, [s.message.key for s in delivered], args.processed_dir)
            print(f"    {added} new ledger row(s) from {len(delivered)} "
                  f"delivered report(s)")
            for problem in problems:
                print(f"    LEDGER RECORD FAILED {problem}", file=sys.stderr)
        # The lineup each subscriber was actually SENT, for Saturday's final
        # check. Only for a send that happened now: a retry that skipped an
        # earlier send may have rebuilt a slightly different report (a stat
        # correction overnight), and the plan must match what is in the inbox.
        # A preview writes none unless it is pointed somewhere on purpose.
        plans_dir = args.plans_dir or (
            PLANS_DIR if provider.name != DRY_PROVIDER else None)
        if plans_dir is not None:
            plans = {r.message.key: r.plan for r in ok if r.message and r.plan}
            written = 0
            for send in delivered:
                plan = plans.get(send.message.key)
                if plan is None:
                    continue
                try:
                    write_plan(plans_dir, plan)
                    written += 1
                except OSError as exc:
                    print(f"    plan not saved for {send.message.key}: {exc}",
                          file=sys.stderr)
            print(f"    {written} lineup(s) saved for Saturday's final check")

    if ok:
        print(f"Reports under: {_display(Path(args.out))}")
    # This run got as far as sending, for real: it leaves the watchdog's
    # marker, failures included — the counts say what happened, and a run that
    # failed exits 1 below and files its own issue. Only the marker tells the
    # watchdog a Tuesday ran; a report key in the log does not (a new buyer's
    # first email shares it). A preview leaves none.
    if sending:
        _mark_finished(data.season, data.week,
                       f"sent {len(delivered)}, already sent "
                       f"{len(skipped) + len(already)}, send failed "
                       f"{len(send_failures)}, not built {len(failed)}")
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0 if not (failed or send_failures) else 1


if __name__ == "__main__":
    sys.exit(main())
