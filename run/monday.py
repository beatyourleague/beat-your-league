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
from collections import Counter
from pathlib import Path

from engine.ledger import (GRADED, PENDING, VOID, grade_ledger_nflverse,
                           ledger_path, ledger_summary, load_all_ledgers,
                           load_ledger, public_entries, scoring_of)
from render.ledger_site import DEFAULT_OUT_DIR, write_ledger_site
from run.solo import CACHE_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# How far past its own week a call may stay pending before the run says so. Two
# weeks clears the ordinary Monday-night wait with room to spare.
STALE_AFTER_WEEKS = 2


def _weeks_old(call, calls, now_week: int | None = None,
               now_season: str | None = None) -> int:
    """How many weeks have passed since this call's own week.

    Measured against the CALENDAR, with the ledger's newest week only as a
    fallback. Keying it off the ledger alone made the alarm silence itself in
    exactly the situations that strand calls: staleness was
    max(week of any call this season) - call.week, which only grows while the
    TUESDAY run keeps recording. A broken send cron, every subscriber churning,
    or simply the end of the season all stop `latest` advancing, so calls that
    nothing can ever settle stayed at 0 weeks old and were never reported —
    the precise silence this alarm was added to break. Week 17-18 calls were
    structurally unreportable. Found Aug 24 2026.
    """
    if now_season is not None and now_week is not None and str(call.season) == str(now_season):
        return now_week - call.week
    latest = max((c.week for c in calls if c.season == call.season), default=call.week)
    return latest - call.week


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
                entry.get("pick"), entry.get("over"), entry.get("scoring"),
                entry.get("league_size"))

    # MULTISETS, not sets. Adding scoring and league_size to the key made the
    # collision I found distinguishable, but counting is what makes the guard
    # robust to the NEXT collision: two rows that legitimately share a key, one
    # of which disappears, is still a loss — and a set comparison cannot see it.
    missing = (Counter(key(e) for e in old_entries)
               - Counter(key(e) for e in new_entries))
    if missing:
        raise MondayError(
            f"REFUSING to regenerate the public ledger: {sum(missing.values())} "
            f"previously published entr(ies) would disappear (e.g. "
            f"{sorted(str(m) for m in missing.elements())[0]}). The ledger store has lost "
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
    unreadable: list[str] = []
    for league_id in stores:
        path = ledger_path(args.processed_dir, league_id)
        # One unreadable store used to abort the WHOLE run: load_ledger ->
        # _collapse raises when a call_id carries two different graded
        # outcomes, nothing caught it, and stores sorted after the poisoned one
        # were never graded while the public page was never regenerated. That
        # duplicate is an ANTICIPATED state — .gitattributes deliberately sets
        # merge=union on the ledger so a Monday/Tuesday push race concatenates
        # instead of conflicting, which is exactly what _collapse exists to
        # resolve — so its unresolvable case recurring every Monday until a
        # human hand-edits a JSONL is a total outage from a routine event.
        # One store's problem must not become every store's. Found Aug 24 2026.
        try:
            before = load_ledger(path)
        except Exception as exc:  # noqa: BLE001
            unreadable.append(f"{league_id}: {exc}")
            print(f"  {league_id}: UNREADABLE — {exc}", file=sys.stderr)
            continue
        if args.dry_run:
            pending = sum(1 for c in before if c.status == PENDING)
            print(f"  {league_id}: {len(before)} call(s), {pending} pending")
            total_pending += pending
            continue
        try:
            graded, pending = grade_ledger_nflverse(path, args.cache)
        except Exception as exc:  # noqa: BLE001 — same containment rule
            unreadable.append(f"{league_id}: {exc}")
            print(f"  {league_id}: GRADING FAILED — {exc}", file=sys.stderr)
            continue
        total_graded += graded
        total_pending += pending
        print(f"  {league_id}: {graded} settled this run, {pending} still pending "
              f"({len(before)} recorded)")

    calls = load_all_ledgers(args.processed_dir, unreadable)
    # A call that stays PENDING long after its games is not "waiting for Monday
    # Night Football" — it is a call nothing can settle (a player whose team we
    # cannot resolve, a week whose box scores never landed), and the failure
    # mode is silence: it simply never appears on the record. Say so.
    # The real clock. current_season/current_week come from the schedule
    # release, so they keep advancing when the ledger does not.
    try:
        from run.solo import current_season, current_week
        _season = str(current_season(args.cache))
        _week = int(current_week(args.cache, _season))
    except Exception:                       # noqa: BLE001 — a cold cache
        _season, _week = None, None
    stale = [c for c in calls if c.status == PENDING
             and _weeks_old(c, calls, _week, _season) >= STALE_AFTER_WEEKS]
    if stale:
        by_week = sorted({(c.season, c.week) for c in stale})
        print(f"  {len(stale)} call(s) still pending {STALE_AFTER_WEEKS}+ weeks "
              f"on: " + ", ".join(f"{s} w{w}" for s, w in by_week[:6]),
              file=sys.stderr)
        print("    Nothing will settle these on its own — check whether that "
              "week's stat rows ever published.", file=sys.stderr)
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
        return 1 if unreadable else 0

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
    unreadable = sorted(set(unreadable))
    if unreadable:
        # Contained, never swallowed. Every other store still graded and the
        # record still published, but a store nobody can read is calls that
        # will never settle, so the run goes red and the cron files its issue.
        print(f"{len(unreadable)} ledger store(s) could not be read or graded; "
              f"their calls cannot settle until a human looks:", file=sys.stderr)
        for note in unreadable:
            print(f"  ! {note}", file=sys.stderr)
        print(line)
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
