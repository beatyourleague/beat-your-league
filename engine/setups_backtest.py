"""Grade the setups the headline run never measured, one setting at a time.

**This module implements a preregistration.** ``reports/setups-method.md`` was
written and committed together with this file, before either was run. Four of
its arms (half-PPR, standard, 10 and 14 teams) were already preregistered in
the parent method's §9 on Aug 21 2026 and never run; the rest are new there.

Nothing here computes a call or a grade of its own. Every call comes from the
parent's ``calls_for_season`` and every grade from its ``evaluate``, so an arm
cannot be graded differently from the headline it is compared with (method
§6). Each arm changes exactly one setting; everything else is the headline's.

    .venv/bin/python -m engine.setups_backtest
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from engine.decisions import StartSitCall, summarize
from engine.nflverse_backtest import (GRADE_MEANING, GRADED_WEEKS, INJURY_DIR,
                                      LEAGUE_SIZE, RAW_DIR, REPO_ROOT, SEASONS,
                                      TEMPLATE_T1, BacktestError,
                                      calls_for_season, evaluate)
from engine.scoring import preset
from ingest.nflverse import bye_teams

OUT_PATH = REPO_ROOT / "reports" / "setups-backtest.md"
METHOD_PATH = "reports/setups-method.md"

TEMPLATE_SF = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF")
TEMPLATE_NKD = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")
TAIL = (17, 18)


@dataclass(frozen=True)
class Arm:
    """One row of method §1. Only the field named in ``setting`` differs from
    the headline configuration."""

    key: str
    setting: str
    value: str
    scoring: str = "ppr"
    league_size: int = LEAGUE_SIZE
    template: tuple[str, ...] = TEMPLATE_T1
    tail: bool = False


# Method §1, in its order. Frozen: an arm may not be added, dropped or
# reparameterised once any output has been read.
ARMS = (
    Arm("S1", "scoring", "half_ppr", scoring="half_ppr"),
    Arm("S2", "scoring", "standard", scoring="standard"),
    Arm("L10", "league size", "10", league_size=10),
    Arm("L14", "league size", "14", league_size=14),
    Arm("L8", "league size", "8", league_size=8),
    Arm("TSF", "lineup shape", "superflex", template=TEMPLATE_SF),
    Arm("TNKD", "lineup shape", "no K or DEF", template=TEMPLATE_NKD),
    Arm("W17", "weeks", "17-18", tail=True),
)

# Method §3: what each grade does to a report in that setting.
DECISION = {
    "A": "not reachable here (seed 0 only); recorded as B",
    "B": "numeral prints as a recorded prediction; the confidence page may state "
         "this setting's figures as facts beside its failures",
    "C": "numeral prints as a recorded prediction only",
    "D": "no confidence numeral prints in any setup with this setting",
}


def weeks_for(arm: Arm, season: str, raw_dir: Path) -> Sequence[int]:
    """The weeks an arm grades in a season. Weeks 4-16 for every arm but W17;
    W17 takes 17 and 18 where the schedule has them (week 18 exists only from
    2021 — method §1), and never invents a week the schedule lacks."""
    if not arm.tail:
        return GRADED_WEEKS
    return tuple(w for w in TAIL if bye_teams(raw_dir, season, w) is not None)


def arm_calls(arm: Arm, season: str, raw_dir: Path,
              injury_dir: Path) -> list[StartSitCall]:
    return calls_for_season(season, raw_dir, injury_dir, preset(arm.scoring),
                            template=arm.template, league_size=arm.league_size,
                            weeks=weeks_for(arm, season, raw_dir))


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def report(results: list[tuple[Arm, list[StartSitCall], dict[str, int]]]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary_rows, sections = [], []
    for arm, calls, per_season in results:
        s = summarize(calls)
        ev = evaluate(calls)
        grade = "B" if ev.grade == "A" else ev.grade
        ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
        rate = f"{s.hits / s.decided:.1%}" if s.decided else "—"
        summary_rows.append(
            f"| {arm.key} | {arm.setting}: {arm.value} | {s.graded} | {s.decided} "
            f"| {rate} | {ece} | {ev.judgeable} | {ev.calibrated} "
            f"| {ev.resolution:.1f} | **{grade}** |")
        buckets = "\n".join(ev.rows) or "| (no bucket reached 30 decided calls) |"
        seasons = ", ".join(f"{k} {v}" for k, v in sorted(per_season.items()))
        tail = ""
        if arm.tail:
            by_week = {}
            for w in TAIL:
                wc = [c for c in calls if c.week == w]
                ws = summarize(wc)
                by_week[w] = (ws.graded, (ws.hits / ws.decided) if ws.decided else None)
            tail = "\n\nDiagnostic, not graded separately (method §1): " + "; ".join(
                f"week {w}: {n} calls" + (f", hit rate {r:.1%}" if r is not None else "")
                for w, (n, r) in by_week.items()) + "."
        sections.append(f"""### {arm.key} — {arm.setting}: {arm.value}

**Grade {grade}: {GRADE_MEANING[grade]}.** Decision under method §3: {DECISION[grade]}.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
{buckets}

Calls per season: {seasons}.{tail}
""")
    return f"""# Other setups, graded one setting at a time

Generated {stamp} from commit `{_sha()}`. Method frozen in advance:
`{METHOD_PATH}`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.setups_backtest`.

Each arm changes one setting from the published run (full PPR, 12 teams, the
standard lineup, weeks 4–16, which keeps its own Grade C) and is graded alone,
by the same rule and the same code. Combined settings are not graded as
combinations: a report prints a numeral only if every setting of its setup
graded C or better (method §3).

## Summary

| Arm | Setting | Calls | Decided | Hit rate | ECE | Judgeable | Calibrated | Resolution (pts) | Grade |
|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(summary_rows)}

Grade A is unreachable in these runs by construction (seed 0 only; method §2).
Hit rate and ECE are measured facts about past seasons, not a claim that any
number in a report is right. The banned words stay banned at every grade here.

## By arm

{chr(10).join(sections)}"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--injuries", type=Path, default=INJURY_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    results = []
    for arm in ARMS:
        calls: list[StartSitCall] = []
        per_season: dict[str, int] = {}
        for season in SEASONS:
            try:
                got = arm_calls(arm, season, args.raw, args.injuries)
            except (BacktestError, OSError) as exc:
                # Method §5: an arm that grades fewer seasons than §1 fixes is a
                # different measurement under the same name. Write nothing.
                print(f"  {arm.key} {season}: FAILED — {exc}", file=sys.stderr)
                return 1
            per_season[season] = len(got)
            calls.extend(got)
        print(f"  {arm.key}: {len(calls)} calls", file=sys.stderr)
        results.append((arm, calls, per_season))
    args.out.write_text(report(results), encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
