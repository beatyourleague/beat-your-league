"""Post-ship check: the nine combined setups, graded as they now ship.

reports/round-two-method.md graded the combinations on the model of that day.
Since then every setup ships with the context arm, the anchor and
``run.solo.CONTEXT_B`` (reports/context-method.md), and only SINGLE-setting arms
were graded on that model. This grades the nine combinations on it, with the
parent's own ``calls_for_season`` and ``evaluate``, on the held-out 2020-2024
seasons. It decides nothing by itself: a D would mean the numeral must be
withheld for that combination (round-two method §2), and the report says so.

    .venv/bin/python -m engine.context_combos
"""

from __future__ import annotations

from pathlib import Path

from engine.nflverse_backtest import (INJURY_DIR, RAW_DIR, REPO_ROOT,
                                      calls_for_season, evaluate)
from engine.recalibration import GRADE_SEASONS, apply
from engine.round_two_backtest import COMBOS
from engine.scoring import preset
from engine.decisions import summarize
from run.solo import CONTEXT_B

OUT = REPO_ROOT / "reports" / "context-combos-check.md"


def main() -> int:
    rows = []
    for combo in COMBOS:
        calls = []
        for season in GRADE_SEASONS:
            calls.extend(calls_for_season(
                season, RAW_DIR, INJURY_DIR, preset(combo.scoring),
                template=combo.template, league_size=combo.league_size,
                confirmed_fallback=True, late_self_weight=0.25, context="AV"))
        calls = apply(calls, CONTEXT_B)
        ev = evaluate(calls)
        grade = "B" if ev.grade == "A" else ev.grade
        stats = summarize(calls)
        ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
        rate = f"{stats.hits / stats.decided:.1%}" if stats.decided else "—"
        rows.append(f"| {combo.key} | {combo.scoring}, {combo.league_size} teams, "
                    f"{combo.shape} | {len(calls)} | {rate} | {ece} | "
                    f"{ev.calibrated}/{ev.judgeable} | **{grade}** |")
        print(rows[-1])
    text = f"""# The nine combinations, graded as they now ship

Held-out 2020–2024, context arm AV + anchor 0.25 + b = {CONTEXT_B}. Produced by
`engine/context_combos.py`. Round-two method §2: a D withholds the numeral for
that combination; nothing here is a preregistered decision, it is a check on
what ships.

| Key | Setup | Calls | Hit rate | ECE | Bands calibrated | Grade |
|---|---|---|---|---|---|---|
""" + "\n".join(rows) + "\n"
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
