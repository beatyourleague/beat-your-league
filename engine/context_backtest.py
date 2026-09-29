"""Who he plays, and whether he was really missing — graded as it would ship.

**This module implements a preregistration.** ``reports/context-method.md`` was
committed together with this file and the context switches, before any of
them ran. Arms are CHOSEN on 2014-2019 and CONFIRMED on 2020-2024 (§3).

    .venv/bin/python -m engine.context_backtest
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from engine.anchor_backtest import (Pair, _cap, _grade_line, _sha, _star_counts,
                                    _stars, mean_difference, sign_test, tally)
from engine.decisions import StartSitCall
from engine.nflverse_backtest import (GRADED_WEEKS, HEADLINE_SEED, INJURY_DIR,
                                      LEAGUE_SIZE, RAW_DIR, REPO_ROOT,
                                      TEMPLATE_T1, _points, allocate,
                                      availability_for, build_backtest_season,
                                      build_universe, calls_for_season,
                                      context_inputs, evaluate, player_index_for,
                                      prior_self_observations)
from engine.projection import ProjectionModel
from engine.recalibration import FIT_SEASONS, GRADE_SEASONS, apply, fit_b
from engine.scoring import preset
from engine.setups_backtest import ARMS
from engine.week_report import optimal_lineup
from ingest.injuries import fetch as fetch_injuries
from ingest.injuries import load_weeks
from ingest.nflverse import bye_teams, season_rows, season_teams

OUT_PATH = REPO_ROOT / "reports" / "context-backtest.md"
METHOD_PATH = "reports/context-method.md"

# Frozen (method §3).
ARMS_CONTEXT = ("A", "AM", "AV", "AMV")
ANCHOR = 0.25
SHIPPED_B = {True: 1.4670, False: 1.3714}     # anchored setup -> its published b
ANCHOR_SCORING = {"ppr", "half_ppr", "standard"}
ANCHOR_SIZES = {8, 12}
NKD = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")
SETUP_ARMS = tuple(arm for arm in ARMS if not arm.tail)
GRADE_RANK = {"D": 0, "C": 1, "B": 2, "A": 3}


def anchored(scoring: str, size: int, template) -> bool:
    """Does the shipped product anchor this setup today (run/solo.anchored)?"""
    return (scoring in ANCHOR_SCORING and int(size) in ANCHOR_SIZES
            and tuple(template) in (tuple(TEMPLATE_T1), NKD))


def lineup_pairs(season: str, context: str, *, scoring: str = "ppr",
                 template: Sequence[str] = TEMPLATE_T1,
                 league_size: int = LEAGUE_SIZE) -> list[Pair]:
    """Every team-week seated by the shipped model of this setup and by the
    arm (the anchor plus ``context``), on identical inputs."""
    rule = preset(scoring)
    prior = season_rows(RAW_DIR, str(int(season) - 1))
    weekly = season_rows(RAW_DIR, season)
    universe = build_universe(prior, rule, season_teams(RAW_DIR, season))
    rosters = allocate(universe, template, league_size, HEADLINE_SEED, 2.0)
    players = player_index_for(universe)
    injuries = load_weeks(fetch_injuries(season, INJURY_DIR), season)
    prior_self = prior_self_observations(prior, rule)
    ctx = context_inputs(context, season, RAW_DIR, universe, weekly, rule, injuries)
    shipped_anchor = ANCHOR if anchored(scoring, league_size, template) else 0.0
    stars = _stars(universe)
    out: list[Pair] = []
    for week in GRADED_WEEKS:
        season_obj = build_backtest_season(universe, rosters, weekly, season,
                                           template, rule, through_week=week)
        shipped = ProjectionModel(season_obj, players, prior_self=prior_self,
                                  late_self_weight=shipped_anchor)
        arm = ProjectionModel(season_obj, players, prior_self=prior_self,
                              late_self_weight=ANCHOR, **ctx(week))
        byes = bye_teams(RAW_DIR, season, week)
        rows = weekly.get(week) or {}
        for roster_id, roster in enumerate(rosters, start=1):
            team_week = season_obj.weeks.get(week - 1, {}).get(roster_id)
            if team_week is None:
                continue
            available = availability_for(season, week, roster, universe, weekly,
                                          injuries, byes)
            seated = [optimal_lineup(season_obj, team_week, model, players,
                                     available, week, confirmed_fallback=True)
                      for model in (shipped, arm)]
            totals = [sum(_points(rows, p.player_id, rule)
                          for p in picks if p.player_id) for picks in seated]
            ids = [sorted(filter(None, (p.player_id for p in picks))) for picks in seated]
            counts = [_star_counts(picks, roster, stars, available, players,
                                   rows, rule) for picks in seated]
            out.append(Pair(season, week, roster_id, totals[0], totals[1],
                            ids[0] != ids[1], (counts[0][0], counts[1][0]),
                            (counts[0][1], counts[1][1])))
    return out


def _calls(seasons, context: str, *, scoring="ppr", template=TEMPLATE_T1,
           league_size=LEAGUE_SIZE) -> list[StartSitCall]:
    out: list[StartSitCall] = []
    for season in seasons:
        out.extend(calls_for_season(season, RAW_DIR, INJURY_DIR, preset(scoring),
                                    template=template, league_size=league_size,
                                    confirmed_fallback=True,
                                    late_self_weight=ANCHOR, context=context))
    return out


def choose(fit_tallies: dict[str, tuple[int, int, int]]) -> str | None:
    """Method §3.1: largest wins - losses on 2014-2019; ties go to the simpler
    arm (fewer components, then the order listed); none positive -> None."""
    best, best_margin = None, 0
    for arm in ARMS_CONTEXT:
        wins, losses, _ = fit_tallies[arm]
        if wins - losses > best_margin:
            best, best_margin = arm, wins - losses
    return best


def decide_headline(wins: int, losses: int, grade: str) -> bool:
    return wins > losses and GRADE_RANK[_cap(grade)] >= GRADE_RANK["B"]


def decide_setup(wins: int, losses: int, grade: str, headline: bool) -> bool:
    return headline and wins > losses and GRADE_RANK[_cap(grade)] >= GRADE_RANK["C"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print("choosing on 2014-2019...", file=sys.stderr)
    fit_tallies = {arm: tally([p for s in FIT_SEASONS for p in lineup_pairs(s, arm)])
                   for arm in ARMS_CONTEXT}
    chosen = choose(fit_tallies)
    fit_rows = "\n".join(f"| {arm} | {w}–{l}–{t} | {w - l:+d} |"
                         for arm, (w, l, t) in fit_tallies.items())
    if chosen is None:
        text = (f"# Context — results\n\nGenerated {stamp} at commit {_sha()} under "
                f"`{METHOD_PATH}`.\n\n**No arm won more than it lost on 2014–2019, "
                f"so nothing ships (method §3.1).**\n\n| Arm | W–L–T | Margin |\n"
                f"|---|---|---|\n{fit_rows}\n")
        args.output.write_text(text, encoding="utf-8")
        print(text)
        return 0

    print(f"chosen: {chosen}; fitting b' and confirming on 2020-2024...", file=sys.stderr)
    b_prime = fit_b(_calls(FIT_SEASONS, chosen))
    pairs = [p for s in GRADE_SEASONS for p in lineup_pairs(s, chosen)]
    wins, losses, ties = tally(pairs)
    p_value = sign_test(wins, losses)
    mean, (lo, hi) = mean_difference(pairs)
    arm_calls = apply(_calls(GRADE_SEASONS, chosen), b_prime)
    shipped_calls = apply(_calls(GRADE_SEASONS, ""), SHIPPED_B[True])
    arm_line, arm_grade = _grade_line(f"Arm {chosen}, b′ = {b_prime:.4f}", arm_calls)
    shipped_line, _ = _grade_line(f"Shipped (anchor), b = {SHIPPED_B[True]}",
                                  shipped_calls)
    ships = decide_headline(wins, losses, arm_grade)
    team_weeks = len(pairs)
    benched = [sum(p.stars_benched[i] for p in pairs) for i in (0, 1)]
    beat = [sum(p.stars_outscored[i] for p in pairs) for i in (0, 1)]

    print("other arms held out (reported only) and the setups...", file=sys.stderr)
    others = []
    for arm in ARMS_CONTEXT:
        if arm == chosen:
            continue
        w, l, t = tally([p for s in GRADE_SEASONS for p in lineup_pairs(s, arm)])
        others.append(f"| {arm} | {w}–{l}–{t} | {sign_test(w, l):.4f} |")
    setup_rows = []
    for arm in SETUP_ARMS:
        spairs = [p for s in GRADE_SEASONS for p in lineup_pairs(
            s, chosen, scoring=arm.scoring, template=arm.template,
            league_size=arm.league_size)]
        w, l, t = tally(spairs)
        calls = apply(_calls(GRADE_SEASONS, chosen, scoring=arm.scoring,
                             template=arm.template, league_size=arm.league_size),
                      b_prime)
        ev = evaluate(calls)
        grade = _cap(ev.grade)
        ok = decide_setup(w, l, grade, ships)
        ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
        setup_rows.append(f"| {arm.key} | {arm.setting}: {arm.value} | {w}–{l}–{t} "
                          f"| {sign_test(w, l):.3f} | {len(calls)} | {ece} | **{grade}** "
                          f"| {'ships' if ok else 'does not ship'} |")

    verdict = (f"**Arm {chosen} ships** in weeks 4–16 with b′ = {b_prime:.4f}, in the "
               f"headline setup and every setup marked below." if ships else
               f"**Arm {chosen} does not ship.** Nothing changes in any report.")
    text = f"""# Who he plays, and whether he was really missing — results

Generated {stamp} by `engine/context_backtest.py` at commit {_sha()}, under the
preregistration in `{METHOD_PATH}` (frozen before this ran).

## Decision

{verdict}

## 1. The choice, made on 2014–2019 only (method §3.1)

Each arm's lineups against the shipped lineups, where they differed.

| Arm | W–L–T | Margin |
|---|---|---|
{fit_rows}

Chosen: **{chosen}**.

## 2. The confirmation, on held-out 2020–2024

- **C1 (lineups):** won **{wins}**, lost **{losses}**, tied {ties} of the
  {wins + losses + ties} differing team-weeks (of {team_weeks}). Exact two-sided
  sign test p = {p_value:.4f}. Mean points per differing team-week {mean:+.2f}
  (95% interval {lo:+.2f} to {hi:+.2f}, clustered by season-week).
  **{'Held' if wins > losses else 'Failed'}.**
- **C2 (the number):** corrected grade **{arm_grade}**.
  **{'Held' if GRADE_RANK[arm_grade] >= GRADE_RANK['B'] else 'Failed'}.**

| Model | Calls | Hit rate | ECE | Judgeable bands | Calibrated | Resolution | Grade |
|---|---|---|---|---|---|---|---|
{shipped_line}
{arm_line}

Star benchings (reported): shipped benched {benched[0]} available stars, who
outscored the weakest starter they could have replaced {beat[0]} times; the arm
benched {benched[1]} ({beat[1]} outscored).

## 3. The other arms on 2020–2024 (printed after the decision; never substituted)

| Arm | W–L–T | Sign test p |
|---|---|---|
""" + "\n".join(others) + f"""

## 4. The setups (method §4d), with b′ = {b_prime:.4f}

| Arm | Setting | Lineups W–L–T | Sign test p | Calls | ECE | Grade | Decision |
|---|---|---|---|---|---|---|---|
""" + "\n".join(setup_rows) + """

## What this is not

The backtest reads CLOSING lines; the product reads Tuesday's (method §6). The
harness never trades or drops.
"""
    args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
