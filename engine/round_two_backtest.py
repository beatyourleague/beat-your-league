"""Combined settings and team defenses, graded as they ship on 2020-2024.

**This module implements a preregistration.** ``reports/round-two-method.md``
was committed together with this file and the parent's ``defenses`` switch,
before any of them ran.

Every call comes from the parent's ``calls_for_season``; every grade from its
``evaluate``; every confidence passes through the published recalibration
(``engine.recalibration.recalibrate`` with ``run.solo.RECALIBRATION_B``), because
that is the number a report prints in weeks 4-16.

    .venv/bin/python -m engine.round_two_backtest
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
from engine.nflverse_backtest import (INJURY_DIR, RAW_DIR, REPO_ROOT, SEASONS,
                                      TEMPLATE_T1, BacktestError,
                                      calls_for_season, evaluate)
from engine.recalibration import GRADE_SEASONS, apply
from engine.roster import DEFENSE
from engine.scoring import preset
from engine.setups_backtest import TEMPLATE_NKD, TEMPLATE_SF

OUT_PATH = REPO_ROOT / "reports" / "round-two-backtest.md"
METHOD_PATH = "reports/round-two-method.md"
MIN_JUDGEABLE_FOR_DEFENSE = 2          # method §2


@dataclass(frozen=True)
class Combo:
    key: str
    scoring: str
    league_size: int
    template: tuple[str, ...]
    shape: str


# Method §1a, in its order. Frozen.
COMBOS = (
    Combo("X1", "half_ppr", 10, TEMPLATE_T1, "standard"),
    Combo("X2", "half_ppr", 14, TEMPLATE_T1, "standard"),
    Combo("X3", "standard", 10, TEMPLATE_T1, "standard"),
    Combo("X4", "standard", 14, TEMPLATE_T1, "standard"),
    Combo("X5", "half_ppr", 12, TEMPLATE_SF, "superflex"),
    Combo("X6", "ppr", 10, TEMPLATE_SF, "superflex"),
    Combo("X7", "ppr", 14, TEMPLATE_SF, "superflex"),
    Combo("X8", "half_ppr", 12, TEMPLATE_NKD, "no K or DEF"),
    Combo("X9", "half_ppr", 8, TEMPLATE_T1, "standard"),
)


def _b() -> float:
    from run.solo import RECALIBRATION_B
    if RECALIBRATION_B is None:
        raise SystemExit("no published recalibration — method §1 grades as it ships")
    return RECALIBRATION_B


def _ece(ev) -> str:
    return f"{ev.ece:.1%}" if ev.ece is not None else "—"


def _cap(grade: str) -> str:
    return "B" if grade == "A" else grade


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _collect(fn, seasons) -> list[StartSitCall] | None:
    out: list[StartSitCall] = []
    for season in seasons:
        try:
            out.extend(fn(season))
        except (BacktestError, OSError) as exc:
            print(f"  {season}: FAILED — {exc}", file=sys.stderr)
            return None
    return out


def defense_only(calls: Sequence[StartSitCall]) -> list[StartSitCall]:
    return [c for c in calls if c.slot == DEFENSE]


def defense_ships(grade: str, judgeable: int) -> bool:
    """Method §2, both clauses."""
    return grade != "D" and judgeable >= MIN_JUDGEABLE_FOR_DEFENSE


def _block(label: str, calls: Sequence[StartSitCall]) -> tuple[str, object]:
    ev = evaluate(calls)
    s = summarize(calls)
    ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
    rate = f"{s.hits / s.decided:.1%}" if s.decided else "—"
    rows = "\n".join(ev.rows) or "| (no bucket reached 30 decided calls) |"
    return f"""#### {label} — Grade {_cap(ev.grade)}

{s.graded} calls, {s.decided} decided, hit rate {rate}, ECE {ece}, {ev.judgeable} judgeable
bands, {ev.calibrated} calibrated, resolution {ev.resolution:.1f} points.

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

    summary, sections = [], []
    for combo in COMBOS:
        rule = preset(combo.scoring)
        calls = _collect(lambda s: calls_for_season(
            s, args.raw, args.injuries, rule, template=combo.template,
            league_size=combo.league_size), GRADE_SEASONS)
        if calls is None:
            return 1
        recal_text, ev_r = _block(f"{combo.key} recalibrated", apply(calls, b))
        raw_text, ev_w = _block(f"{combo.key} raw (diagnostic)", calls)
        s = summarize(calls)
        summary.append(
            f"| {combo.key} | {combo.scoring}, {combo.league_size} teams, {combo.shape} "
            f"| {s.graded} | {s.decided} | **{_cap(ev_r.grade)}** "
            f"| {_ece(ev_r)} | {_cap(ev_w.grade)} | {_ece(ev_w)} | {ev_r.judgeable} |")
        sections.append(f"### {combo.key} — {combo.scoring}, {combo.league_size} teams, "
                        f"{combo.shape}\n\n{recal_text}\n{raw_text}")
        print(f"  {combo.key}: {_cap(ev_r.grade)}", file=sys.stderr)

    rule = preset("ppr")
    all_def = _collect(lambda s: defense_only(calls_for_season(
        s, args.raw, args.injuries, rule, defenses=True)), SEASONS)
    if all_def is None:
        return 1
    held_out = [c for c in all_def if c.season in GRADE_SEASONS]
    def_recal, ev_d = _block("DEF recalibrated, 2020–2024", apply(held_out, b))
    def_raw, ev_dw = _block("DEF raw, 2020–2024 (diagnostic)", held_out)
    def_full, _ = _block("DEF raw, 2014–2024 (diagnostic)", all_def)
    ships = defense_ships(ev_d.grade, ev_d.judgeable)
    s = summarize(held_out)
    summary.append(
        f"| DEF | team defenses, full PPR, 12 teams, standard | {s.graded} | {s.decided} "
        f"| **{_cap(ev_d.grade)}** | {_ece(ev_d)} | {_cap(ev_dw.grade)} | {_ece(ev_dw)} "
        f"| {ev_d.judgeable} |")
    print(f"  DEF: {_cap(ev_d.grade)}, {ev_d.judgeable} judgeable, ships={ships}",
          file=sys.stderr)

    withheld = [line.split(" | ")[0].lstrip("| ") for line in summary[:-1]
                if "| **D** |" in line]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = f"""# Combined settings and team defenses, graded as they ship

Generated {stamp} from commit `{_sha()}`. Method frozen in advance:
`{METHOD_PATH}`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.round_two_backtest`.

Graded on 2020–2024 only, every confidence through the published recalibration
(b = {b:.4f}), weeks 4–16. The raw grade beside each is a diagnostic and
decides nothing.

## Decisions

- Combined settings withheld (grade D): {", ".join(withheld) if withheld else "none"}.
- Team defenses: recalibrated grade **{_cap(ev_d.grade)}** on {ev_d.judgeable} judgeable
  bands — {"**SHIPS**: the defense numeral prints from now on" if ships else
  "**DOES NOT SHIP**: the defense gate stays closed"} (method §2 requires C or
  better and at least {MIN_JUDGEABLE_FOR_DEFENSE} judgeable bands).

## Summary

| Arm | Setup | Calls | Decided | Grade (as shipped) | ECE | Raw grade | Raw ECE | Judgeable |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(summary)}

## Team defenses

{def_recal}
{def_raw}
{def_full}
## Combined settings

{chr(10).join(sections)}"""
    args.out.write_text(report, encoding="utf-8")
    print(f"\nwrote {args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
