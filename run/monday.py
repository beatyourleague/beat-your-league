"""Monday: settle last week's published calls, and republish the record.

Usage:
    python -m run.monday [--dry-run] [--processed-dir PATH] [--cache PATH]

The grading half of principle 2, for the product that never reads a league.
``run/tuesday.py`` RECORDS every probability at the moment it is published —
the half that cannot be done retroactively — and this settles them against real
box scores once the games are final.

``run/content.py receipts`` is the Sleeper-era equivalent and cannot be reused
by renaming a module: it resolves a league id, reads a roster id, and grades via
``grade_ledger``, which decides finality from a cached Sleeper schedule plus the
weekly availability snapshots that only ``ingest.pull`` writes. The roster path
writes neither, so every ``typed-*`` call would have stayed PENDING forever —
green cron, empty public record, principle 2 quietly voided.

What this does NOT do is change any grading rule. RULES L1-L4 live in
``engine/ledger.py`` and are applied by one function for both data stacks; this
runner only points it at the nflverse sources and reports what settled.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.ledger import (GRADED, PENDING, VOID, grade_ledger_nflverse,
                           ledger_path, ledger_summary, load_all_ledgers,
                           load_ledger, public_entries, scoring_of)
from render.ledger_site import DEFAULT_OUT_DIR, write_ledger_site
from run.solo import CACHE_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"


class MondayError(RuntimeError):
    """The grading run refused to proceed."""


def typed_stores(processed_dir: Path) -> list[str]:
    """Every roster-product ledger store, by league id.

    A store is named `typed-{scoring}-{season}` because the scoring preset is
    part of a call's identity — the same pick over the same alternative is a
    different call, with a different probability and a different answer, under
    PPR and under standard.
    """
    root = Path(processed_dir) / "ledger"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and scoring_of(d.name) is not None)


def guard_shrink(new_entries: list[dict], out_dir: Path) -> None:
    """Fail closed if the regenerated page would LOSE settled entries.

    The ledger is append-only and graded entries are immutable (RULE L4), so the
    only way the public list shrinks is data loss — a cache-restore miss, a
    wiped store. Publishing a shrunken page would silently rewrite the public
    record, which is the one failure this whole mechanism exists to prevent.

    Deliberately duplicated in spirit from run/content.py rather than imported:
    that module pulls a Sleeper client through its imports, and this runner's
    guarantee is that it cannot.
    """
    committed = Path(out_dir) / "data.json"
    if not committed.is_file():
        return
    try:
        old_entries = json.loads(committed.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return                      # no trustworthy baseline to guard against
    if not isinstance(old_entries, list):
        return

    def key(entry: dict) -> tuple:
        # `scoring` is part of the key. Without it, the same head-to-head
        # published under two presets collapses to ONE key — measured: three
        # rows, one key — so two whole stores could vanish and this guard would
        # see nothing missing. The split that made the ledger correct is exactly
        # what made this key insufficient.
        return (entry.get("season"), entry.get("week"), entry.get("slot"),
                entry.get("pick"), entry.get("over"), entry.get("scoring"))

    missing = {key(e) for e in old_entries} - {key(e) for e in new_entries}
    if missing:
        raise MondayError(
            f"REFUSING to regenerate the public ledger: {len(missing)} "
            f"previously published entr(ies) would disappear (e.g. "
            f"{sorted(str(m) for m in missing)[0]}). The ledger store has lost "
            f"data — restore data/processed/ledger/ from the artifact backup, "
            f"then re-run.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                        help="where the public ledger page is written")
    parser.add_argument("--dry-run", action="store_true",
                        help="grade nothing and publish nothing; report only")
    args = parser.parse_args(argv)

    stores = typed_stores(args.processed_dir)
    line = "=" * 62
    print(f"\n{line}\nMONDAY GRADING{' (dry run)' if args.dry_run else ''}\n{line}")
    if not stores:
        print("no roster-product ledger yet — nothing published to settle")
        print(line)
        return 0

    total_graded = 0
    total_pending = 0
    for league_id in stores:
        path = ledger_path(args.processed_dir, league_id)
        before = load_ledger(path)
        if args.dry_run:
            pending = sum(1 for c in before if c.status == PENDING)
            print(f"  {league_id}: {len(before)} call(s), {pending} pending")
            total_pending += pending
            continue
        graded, pending = grade_ledger_nflverse(path, args.cache)
        total_graded += graded
        total_pending += pending
        print(f"  {league_id}: {graded} settled this run, {pending} still pending "
              f"({len(before)} recorded)")

    calls = load_all_ledgers(args.processed_dir)
    settled = [c for c in calls if c.status != PENDING]
    voided = [c for c in calls if c.status == VOID]
    summary = ledger_summary(calls)
    print(f"\nRecord: {len(calls)} published, {len(settled)} settled, "
          f"{len(voided)} void")
    decided = summary["hits"] + summary["misses"]
    if decided and summary.get("hit_rate") is not None:
        stated = [c.confidence for c in calls
                  if c.status == GRADED and c.outcome in ("hit", "miss")]
        print(f"  {summary['hits']} of {decided} decided calls hit "
              f"({summary['hit_rate']:.1%}); stated average "
              f"{sum(stated) / len(stated):.1%}")

    if args.dry_run:
        print("(dry run — nothing graded, nothing published)")
        print(line)
        return 0

    entries = public_entries(calls)
    try:
        guard_shrink(entries, args.out)
    except MondayError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if entries:
        page = write_ledger_site(entries, summary, out_dir=args.out)
        print(f"Public ledger: {page}")
    else:
        # Nothing settled yet is a real state early in a season, and publishing
        # an empty page over a good one is exactly what guard_shrink prevents.
        print("Nothing settled yet — the public page is left as it stands.")
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
