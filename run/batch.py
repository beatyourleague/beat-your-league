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
from engine.week_report import RAW_DIR, WeekReportError, build_week_report
from run.registry import DEFAULT_REGISTRY, RegistryError, Subscriber, load_registry
from run.week import _current_week, text_summary

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBSCRIBER_REPORTS = REPO_ROOT / "reports" / "subscribers"


@dataclass
class BatchResult:
    subscriber: Subscriber
    ok: bool
    detail: str
    html_path: Path | None = None


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


def run_subscriber(subscriber: Subscriber, week: int,
                   template_html: str) -> BatchResult:
    try:
        my_roster = _my_roster_id(RAW_DIR, subscriber)
        report = build_week_report(
            RAW_DIR, subscriber.league_id, week, my_roster,
            named_rival_owner_id=subscriber.rival_owner_id,
            named_rival_roster_id=subscriber.rival_roster_id,
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
    html_path.write_text(render_report.render(report, template_html), encoding="utf-8")
    (out_dir / f"{stem}.txt").write_text(text_summary(report), encoding="utf-8")

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
    return BatchResult(subscriber, ok=True, detail=detail, html_path=html_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, help="default: current NFL week")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--skip-ingest", action="store_true",
                        help="use the existing cache without hitting Sleeper")
    args = parser.parse_args(argv)

    try:
        subscribers = load_registry(args.registry)
    except RegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not subscribers:
        print("registry is empty — nothing to do")
        return 0

    leagues = sorted({s.league_id for s in subscribers})
    if not args.skip_ingest:
        for league_id in leagues:
            code = ingest_pull.main(["--league", league_id])
            if code != 0:
                print(f"ingest failed for league {league_id}; its subscribers "
                      "will fail below", file=sys.stderr)

    week = args.week if args.week is not None else _current_week(RAW_DIR)
    template_html = render_report.TEMPLATE_PATH.read_text(encoding="utf-8")

    results = [run_subscriber(s, week, template_html) for s in subscribers]

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
    if ok:
        print(f"Reports under: {SUBSCRIBER_REPORTS.relative_to(REPO_ROOT)}/")
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
