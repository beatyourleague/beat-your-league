"""The confirmed-alternative fallback, graded as it would ship on 2020-2024.

**This module implements a preregistration.** ``reports/fallback-method.md``
was committed together with this file and the ``confirmed_fallback`` switch,
before any of them ran.

Every call comes from the parent's ``calls_for_season``; every grade from its
``evaluate``; every confidence passes through the published recalibration,
because that is the number a report prints in weeks 4-16.

    .venv/bin/python -m engine.fallback_backtest
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from engine.decisions import StartSitCall, summarize
from engine.nflverse_backtest import (GRADED_WEEKS, INJURY_DIR, LEAGUE_SIZE,
                                      RAW_DIR, REPO_ROOT, SEASONS, TEMPLATE_T1,
                                      BacktestError, calls_for_season, evaluate)
from engine.recalibration import GRADE_SEASONS, apply
from engine.scoring import preset

OUT_PATH = REPO_ROOT / "reports" / "fallback-backtest.md"
METHOD_PATH = "reports/fallback-method.md"
MIN_JUDGEABLE = 2                      # method §3.2


def _b() -> float:
    from run.solo import RECALIBRATION_B
    if RECALIBRATION_B is None:
        raise SystemExit("no published recalibration — method §2 grades as it ships")
    return RECALIBRATION_B


def _cap(grade: str) -> str:
    return "B" if grade == "A" else grade


def _ece(ev) -> str:
    return f"{ev.ece:.1%}" if ev.ece is not None else "—"


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def key(call: StartSitCall) -> tuple[str, int, int, int]:
    return (call.season, call.week, call.roster_id, call.slot_index)


def new_calls(frozen: Sequence[StartSitCall],
              fallback: Sequence[StartSitCall]) -> list[StartSitCall]:
    """Method §2: calls whose slot-week had no call in the frozen set."""
    seen = {key(c) for c in frozen}
    return [c for c in fallback if key(c) not in seen]


def changed_shared(frozen: Sequence[StartSitCall],
                   fallback: Sequence[StartSitCall]) -> int:
    """Shared slot-weeks whose call moved (a RULE 3 re-seat can do that)."""
    before = {key(c): (c.recommended_id, c.alternative_id, round(c.confidence, 6))
              for c in frozen}
    return sum(1 for c in fallback if key(c) in before
               and before[key(c)] != (c.recommended_id, c.alternative_id,
                                      round(c.confidence, 6)))


def decide(new_grade: str, new_judgeable: int, all_grade: str) -> bool:
    """Method §3, all three clauses."""
    return (new_grade != "D" and new_judgeable >= MIN_JUDGEABLE
            and _cap(all_grade) == "B")


def _collect(seasons, fallback: bool, raw: Path, injuries: Path):
    rule = preset("ppr")
    out: list[StartSitCall] = []
    for season in seasons:
        try:
            out.extend(calls_for_season(season, raw, injuries, rule,
                                        confirmed_fallback=fallback))
        except (BacktestError, OSError) as exc:
            print(f"  {season}: FAILED — {exc}", file=sys.stderr)
            return None
        print(f"  {season} fallback={fallback}: {len(out)} so far", file=sys.stderr)
    return out


def _block(label: str, calls: Sequence[StartSitCall]):
    ev = evaluate(calls)
    s = summarize(calls)
    rate = f"{s.hits / s.decided:.1%}" if s.decided else "—"
    rows = "\n".join(ev.rows) or "| (no bucket reached 30 decided calls) |"
    return f"""#### {label} — Grade {_cap(ev.grade)}

{s.graded} calls, {s.decided} decided, hit rate {rate}, ECE {_ece(ev)}, {ev.judgeable}
judgeable bands, {ev.calibrated} calibrated, resolution {ev.resolution:.1f} points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
{rows}
""", ev


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--injuries", type=Path, default=INJURY_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)
    b = _b()

    frozen = _collect(SEASONS, False, args.raw, args.injuries)
    fallback = _collect(SEASONS, True, args.raw, args.injuries)
    if frozen is None or fallback is None:
        return 1
    added_all = new_calls(frozen, fallback)
    held = lambda calls: [c for c in calls if c.season in GRADE_SEASONS]  # noqa: E731
    new_ho, all_ho, frozen_ho = held(added_all), held(fallback), held(frozen)

    new_text, ev_new = _block("NEW recalibrated, 2020–2024", apply(new_ho, b))
    all_text, ev_all = _block("ALL recalibrated, 2020–2024", apply(all_ho, b))
    new_raw_text, ev_new_raw = _block("NEW raw, 2020–2024 (diagnostic)", new_ho)
    all_raw_text, ev_all_raw = _block("ALL raw, 2020–2024 (diagnostic)", all_ho)
    new_full_text, _ = _block("NEW raw, 2014–2024 (diagnostic)", added_all)
    ships = decide(_cap(ev_new.grade), ev_new.judgeable, ev_all.grade)

    slots = LEAGUE_SIZE * len(GRADED_WEEKS) * len(TEMPLATE_T1) * len(GRADE_SEASONS)
    moved = changed_shared(frozen_ho, all_ho)

    def row(name, calls, ev, ev_raw):
        s = summarize(calls)
        return (f"| {name} | {s.graded} | {s.decided} | **{_cap(ev.grade)}** | {_ece(ev)} "
                f"| {_cap(ev_raw.grade)} | {_ece(ev_raw)} | {ev.judgeable} |")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = f"""# The confirmed-alternative fallback, graded as it would ship

Generated {stamp} from commit `{_sha()}`. Method frozen in advance: `{METHOD_PATH}`,
committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.fallback_backtest`.

Headline configuration (full PPR, 12 teams, the standard lineup), weeks 4–16, graded on
2020–2024 through the published recalibration (b = {b:.4f}). Raw grades are diagnostics.

## Decision

The fallback **{"SHIPS" if ships else "DOES NOT SHIP"}**. Method §3 requires NEW graded C or
better (got **{_cap(ev_new.grade)}**) on at least {MIN_JUDGEABLE} judgeable bands (got
{ev_new.judgeable}), and ALL graded B (got **{_cap(ev_all.grade)}**).

## Summary

| Population | Calls | Decided | Grade (as shipped) | ECE | Raw grade | Raw ECE | Judgeable |
|---|---|---|---|---|---|---|---|
{row("NEW", new_ho, ev_new, ev_new_raw)}
{row("ALL", all_ho, ev_all, ev_all_raw)}

Diagnostics (decide nothing): frozen calls 2020–2024 **{len(frozen_ho)}**, with the
fallback **{len(all_ho)}** ({len(new_ho)} new); share of slot-weeks carrying odds
{len(frozen_ho) / slots:.1%} → {len(all_ho) / slots:.1%}; shared slot-weeks whose call
moved: {moved}.

## Bucket tables

{new_text}
{all_text}
{new_raw_text}
{all_raw_text}
{new_full_text}"""
    args.out.write_text(report, encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)} — ships={ships}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
