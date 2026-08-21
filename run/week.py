"""Phase 4: the whole weekly pipeline in one command.

Usage:
    python -m run.week [--week N] [--roster R] [--league ID] [--skip-ingest]

ingest -> week_report.json -> HTML report + plain-text summary, all under
``reports/``. Week defaults to the current NFL week from ``/state/nfl``;
roster comes from ``--roster`` or the SLEEPER_ROSTER_ID env var.

Exit codes: 0 on success, 1 with an actionable message on any failure —
this is what the Tuesday GitHub Actions cron runs, so failures must say
what to fix, not print a traceback.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import ingest.pull as ingest_pull
import render.report as render_report
from engine.history import HistoryError
from engine.week_report import PROCESSED_DIR, RAW_DIR, WeekReportError, build_week_report
from ingest.config import resolve_league_id
from render.email import text_summary  # noqa: F401 - re-exported

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"


def _resolve_roster(cli_value: int | None) -> int:
    if cli_value is not None:
        return cli_value
    env = os.environ.get("SLEEPER_ROSTER_ID")
    if env and env.isdigit():
        return int(env)
    raise SystemExit(
        "No roster configured. Pass --roster <id> or set SLEEPER_ROSTER_ID — "
        "`python -m ingest.pull` lists every roster id and owner in the league."
    )


def _current_week(raw_dir: Path) -> int:
    state_path = raw_dir / "state" / "nfl.json"
    if not state_path.is_file():
        raise SystemExit("NFL state not cached — run `python -m ingest.pull` first")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    week = state.get("week")
    if not isinstance(week, int) or week < 1:
        raise SystemExit(f"cannot determine current week from state: {week!r}")
    if state.get("season_type") != "regular":
        raise SystemExit(
            f"NFL is in '{state.get('season_type')}' (week {week}), not the regular "
            "season — pass --week explicitly to build a historical report."
        )
    return week


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", help="Sleeper league ID (overrides CLAUDE.md)")
    parser.add_argument("--week", type=int, help="default: current NFL week")
    parser.add_argument("--roster", type=int, help="my roster_id (or SLEEPER_ROSTER_ID)")
    parser.add_argument("--skip-ingest", action="store_true",
                        help="use the existing cache without hitting Sleeper")
    args = parser.parse_args(argv)

    league_id = resolve_league_id(args.league, REPO_ROOT)
    roster_id = _resolve_roster(args.roster)

    if not args.skip_ingest:
        ingest_args = ["--league", league_id]
        code = ingest_pull.main(ingest_args)
        if code != 0:
            return code

    week = args.week if args.week is not None else _current_week(RAW_DIR)

    try:
        report = build_week_report(RAW_DIR, league_id, week, roster_id)
    except (WeekReportError, HistoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    report_json = PROCESSED_DIR / "week_report.json"
    report_json.write_text(json.dumps(report, indent=1), encoding="utf-8")

    meta = report["meta"]
    stem = f"rival-report-{meta['season']}-w{week:02d}-r{roster_id}"
    html_path = REPORTS_DIR / f"{stem}.html"
    template_html = render_report.TEMPLATE_PATH.read_text(encoding="utf-8")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_report.render(report, template_html), encoding="utf-8")
    text_path = REPORTS_DIR / f"{stem}.txt"
    text_path.write_text(text_summary(report), encoding="utf-8")

    # Ledger bookkeeping runs AFTER the deliverables are on disk: a corrupt
    # ledger must never cost a subscriber their report. It does flag the run
    # (exit 1) so the cron surfaces it instead of quietly skipping grading.
    from engine.ledger import (extract_published_calls, grade_ledger,
                               ledger_path, record_calls)
    ledger_file = ledger_path(PROCESSED_DIR, league_id)
    ledger_ok = True
    try:
        recorded = record_calls(ledger_file, extract_published_calls(report))
        graded, pending = grade_ledger(ledger_file, RAW_DIR)
    except Exception as exc:  # noqa: BLE001 — report first, bookkeeping second
        ledger_ok = False
        recorded = graded = pending = 0
        print(f"WARNING: ledger update failed ({exc!r}). The report rendered "
              f"fine; inspect {ledger_file} and re-run to record/grade this "
              "week's calls.", file=sys.stderr)

    line = "=" * 62
    print(f"\n{line}\nWEEKLY RUN COMPLETE\n{line}")
    print(f"{meta['my_label']} vs {meta['rival_label']} — "
          f"{meta['league_name']} {meta['season']} week {week}")
    print(f"  report: {html_path.relative_to(REPO_ROOT)}")
    print(f"  summary: {text_path.relative_to(REPO_ROOT)}")
    print(f"  json: {report_json.relative_to(REPO_ROOT)}")
    published = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    print(f"  published confidences: {published}/{len(report['lineup'])} slots; "
          f"declared gaps: {len(meta.get('gaps') or [])}")
    print(f"  ledger: {recorded} new call(s) recorded, {graded} graded this run, "
          f"{pending} awaiting final games"
          + ("" if ledger_ok else " · LEDGER UPDATE FAILED (see warning above)"))
    print("  LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0 if ledger_ok else 1


if __name__ == "__main__":
    sys.exit(main())
