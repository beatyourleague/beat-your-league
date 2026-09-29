"""Last season, all season: graded as it would ship on 2020-2024.

**This module implements a preregistration.** ``reports/anchor-method.md`` was
committed together with this file and the ``late_self_weight`` switch, before
any of them ran.

Every call comes from the parent's ``calls_for_season``, every grade from its
``evaluate``, every lineup from the product's own ``optimal_lineup``, and the
recalibration is fitted by ``engine.recalibration.fit_b`` — so the arm cannot
be graded differently from the product it is compared with.

    .venv/bin/python -m engine.anchor_backtest
"""

from __future__ import annotations

import argparse
import math
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from engine.availability import Status
from engine.decisions import StartSitCall, summarize
from engine.nflverse_backtest import (BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED,
                                      GRADED_WEEKS, HEADLINE_SEED, INJURY_DIR,
                                      LEAGUE_SIZE, RAW_DIR, REPO_ROOT,
                                      TEMPLATE_T1, _points, allocate,
                                      availability_for, build_backtest_season,
                                      build_universe, calls_for_season,
                                      evaluate, player_index_for,
                                      prior_self_observations)
from engine.projection import ProjectionModel
from engine.recalibration import FIT_SEASONS, GRADE_SEASONS, apply, fit_b
from engine.scoring import preset
from engine.setups_backtest import ARMS
from engine.week_report import optimal_lineup
from ingest.injuries import fetch as fetch_injuries
from ingest.injuries import load_weeks
from ingest.nflverse import bye_teams, season_rows, season_teams

OUT_PATH = REPO_ROOT / "reports" / "anchor-backtest.md"
METHOD_PATH = "reports/anchor-method.md"

# Method §2 and §5. Frozen.
PRIMARY = 0.25
SENSITIVITY = (0.125, 0.5)
SHIPPED_B = 1.3714          # the published recalibration the arm is compared with
STAR_DEPTH = {"QB": 12, "TE": 12, "RB": 24, "WR": 24}
SETUP_ARMS = tuple(arm for arm in ARMS if not arm.tail)
GRADE_RANK = {"D": 0, "C": 1, "B": 2, "A": 3}


@dataclass(frozen=True)
class Pair:
    """One team-week, seated both ways (method §4a) with §4c's star counts."""

    season: str
    week: int
    roster_id: int
    shipped: float
    arm: float
    differs: bool
    stars_benched: tuple[int, int]        # (shipped, arm)
    stars_outscored: tuple[int, int]      # benched stars who beat their displacer


def _cap(grade: str) -> str:
    return "B" if grade == "A" else grade


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _stars(universe) -> set[str]:
    """Method §4c: starter-calibre last season, inside the universe."""
    by_position: dict[str, list[tuple[float, str]]] = {}
    for pid, points in universe.prior_points.items():
        position = universe.positions.get(pid)
        if position in STAR_DEPTH:
            by_position.setdefault(position, []).append((points, pid))
    out: set[str] = set()
    for position, entries in by_position.items():
        entries.sort(key=lambda e: (-e[0], e[1]))
        out.update(pid for _, pid in entries[:STAR_DEPTH[position]])
    return out


def _star_counts(picks, roster, stars, available, players, rows, rule):
    seated = {p.player_id for p in picks if p.player_id}
    benched = outscored = 0
    for star in roster:
        if star not in stars or star in seated:
            continue
        if available.classify(star).status is Status.OUT:
            continue
        info = players.get(star)
        slots = [p for p in picks if p.player_id and p.projection is not None
                 and info is not None and info.eligible_for(p.slot)]
        if not slots:
            continue
        benched += 1
        displacer = min(slots, key=lambda p: (p.projection.mean, p.player_id))
        outscored += (_points(rows, star, rule)
                      > _points(rows, displacer.player_id, rule))
    return benched, outscored


def lineup_pairs(season: str, lam: float, *, scoring: str = "ppr",
                 template: Sequence[str] = TEMPLATE_T1,
                 league_size: int = LEAGUE_SIZE, raw_dir: Path = RAW_DIR,
                 injury_dir: Path = INJURY_DIR) -> list[Pair]:
    """Method §4a: every team-week seated by the shipped model and the arm on
    identical inputs. Built the way ``calls_for_season`` builds its season."""
    rule = preset(scoring)
    prior = season_rows(raw_dir, str(int(season) - 1))
    weekly = season_rows(raw_dir, season)
    universe = build_universe(prior, rule, season_teams(raw_dir, season))
    rosters = allocate(universe, template, league_size, HEADLINE_SEED, 2.0)
    players = player_index_for(universe)
    injuries = load_weeks(fetch_injuries(season, injury_dir), season)
    prior_self = prior_self_observations(prior, rule)
    stars = _stars(universe)
    out: list[Pair] = []
    for week in GRADED_WEEKS:
        season_obj = build_backtest_season(universe, rosters, weekly, season,
                                           template, rule, through_week=week)
        shipped = ProjectionModel(season_obj, players)
        arm = ProjectionModel(season_obj, players, prior_self=prior_self,
                              late_self_weight=lam)
        byes = bye_teams(raw_dir, season, week)
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
            ids = [tuple(p.player_id for p in picks) for picks in seated]
            counts = [_star_counts(picks, roster, stars, available, players,
                                   rows, rule) for picks in seated]
            out.append(Pair(season, week, roster_id, totals[0], totals[1],
                            sorted(filter(None, ids[0])) != sorted(filter(None, ids[1])),
                            (counts[0][0], counts[1][0]),
                            (counts[0][1], counts[1][1])))
    return out


def sign_test(wins: int, losses: int) -> float:
    """Exact two-sided binomial test at p = 0.5, ties dropped."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def mean_difference(pairs: Sequence[Pair]) -> tuple[float, tuple[float, float]]:
    """Mean (arm - shipped) points per differing team-week, with a 95% interval
    resampling (season, week) clusters — the parent's bootstrap settings."""
    differing = [p for p in pairs if p.differs]
    if not differing:
        return 0.0, (0.0, 0.0)
    clusters: dict[tuple[str, int], list[float]] = {}
    for p in differing:
        clusters.setdefault((p.season, p.week), []).append(p.arm - p.shipped)
    keys = sorted(clusters)
    mean = sum(p.arm - p.shipped for p in differing) / len(differing)
    rng = random.Random(BOOTSTRAP_SEED)
    samples = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        chosen = [clusters[keys[rng.randrange(len(keys))]] for _ in keys]
        values = [v for group in chosen for v in group]
        samples.append(sum(values) / len(values))
    samples.sort()
    return mean, (samples[int(0.025 * len(samples))],
                  samples[int(0.975 * len(samples)) - 1])


def tally(pairs: Sequence[Pair]) -> tuple[int, int, int]:
    differing = [p for p in pairs if p.differs]
    wins = sum(p.arm > p.shipped for p in differing)
    losses = sum(p.arm < p.shipped for p in differing)
    return wins, losses, len(differing) - wins - losses


def _calls(seasons, lam: float, *, scoring="ppr", template=TEMPLATE_T1,
           league_size=LEAGUE_SIZE) -> list[StartSitCall]:
    out: list[StartSitCall] = []
    for season in seasons:
        out.extend(calls_for_season(season, RAW_DIR, INJURY_DIR, preset(scoring),
                                    template=template, league_size=league_size,
                                    confirmed_fallback=True,
                                    late_self_weight=lam))
    return out


def decide_headline(wins: int, losses: int, grade: str) -> bool:
    """Method §5: C1 and C2."""
    return wins > losses and GRADE_RANK[_cap(grade)] >= GRADE_RANK["B"]


def decide_setup(wins: int, losses: int, grade: str, headline: bool) -> bool:
    return headline and wins > losses and GRADE_RANK[_cap(grade)] >= GRADE_RANK["C"]


def _grade_line(label: str, calls: Sequence[StartSitCall]) -> tuple[str, str]:
    s = summarize(calls)
    ev = evaluate(calls)
    rate = f"{s.hits / s.decided:.1%}" if s.decided else "—"
    ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
    grade = _cap(ev.grade)
    return (f"| {label} | {s.graded} | {rate} | {ece} | {ev.judgeable} "
            f"| {ev.calibrated} | {ev.resolution:.1f} | **{grade}** |", grade)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print("fitting b' on 2014-2019 (primary arm)...", file=sys.stderr)
    fit = _calls(FIT_SEASONS, PRIMARY)
    b_prime = fit_b(fit)

    print("lineups and calls on 2020-2024...", file=sys.stderr)
    headline: dict[float, dict] = {}
    for lam in (PRIMARY, *SENSITIVITY):
        pairs = [p for s in GRADE_SEASONS for p in lineup_pairs(s, lam)]
        b = b_prime if lam == PRIMARY else fit_b(_calls(FIT_SEASONS, lam))
        calls = apply(_calls(GRADE_SEASONS, lam), b)
        headline[lam] = {"pairs": pairs, "b": b, "calls": calls}
    shipped_calls = apply(_calls(GRADE_SEASONS, 0.0), SHIPPED_B)

    primary = headline[PRIMARY]
    wins, losses, ties = tally(primary["pairs"])
    p_value = sign_test(wins, losses)
    mean, (lo, hi) = mean_difference(primary["pairs"])
    arm_line, arm_grade = _grade_line(f"Arm λ_L = {PRIMARY}, b′ = {b_prime:.4f}",
                                      primary["calls"])
    shipped_line, _ = _grade_line(f"Shipped, b = {SHIPPED_B}", shipped_calls)
    ships = decide_headline(wins, losses, arm_grade)

    sens_rows = []
    for lam in SENSITIVITY:
        w, l, t = tally(headline[lam]["pairs"])
        line, _ = _grade_line(f"λ_L = {lam}, b′ = {headline[lam]['b']:.4f}",
                              headline[lam]["calls"])
        sens_rows.append((lam, w, l, t, line))

    pairs = primary["pairs"]
    team_weeks = len(pairs)
    benched = [sum(p.stars_benched[i] for p in pairs) for i in (0, 1)]
    beat = [sum(p.stars_outscored[i] for p in pairs) for i in (0, 1)]

    print("the other setups...", file=sys.stderr)
    setup_rows = []
    for arm in SETUP_ARMS:
        spairs = [p for s in GRADE_SEASONS for p in lineup_pairs(
            s, PRIMARY, scoring=arm.scoring, template=arm.template,
            league_size=arm.league_size)]
        w, l, t = tally(spairs)
        calls = apply(_calls(GRADE_SEASONS, PRIMARY, scoring=arm.scoring,
                             template=arm.template, league_size=arm.league_size),
                      b_prime)
        ev = evaluate(calls)
        grade = _cap(ev.grade)
        ok = decide_setup(w, l, grade, ships)
        ece = f"{ev.ece:.1%}" if ev.ece is not None else "—"
        setup_rows.append(f"| {arm.key} | {arm.setting}: {arm.value} | {w}–{l}–{t} "
                          f"| {sign_test(w, l):.3f} | {len(calls)} | {ece} "
                          f"| **{grade}** | {'ships' if ok else 'does not ship'} |")

    verdict = ("**It ships** in weeks 4–16 at λ_L = 0.25 with b′ = "
               f"{b_prime:.4f}, in the headline setup and every setup marked "
               "below." if ships else
               "**It does not ship.** The product keeps the shipped model; "
               "nothing below changes a report.")
    text = f"""# Last season, all season — results (weeks 4–16, 2020–2024)

Generated {stamp} by `engine/anchor_backtest.py` at commit {_sha()}, under the
preregistration in `{METHOD_PATH}` (frozen before this ran). Every lineup is
the product's own `optimal_lineup`; every grade is the parent's `evaluate`.

## Decision

{verdict}

- **C1 (lineups):** the arm's lineups won **{wins}**, lost **{losses}** and tied
  {ties} of the {wins + losses + ties} team-weeks where the two lineups differed
  (of {team_weeks} in all). Exact two-sided sign test p = {p_value:.4f}.
  Mean points per differing team-week: {mean:+.2f} (95% interval
  {lo:+.2f} to {hi:+.2f}, clustered by season-week). **{'Held' if wins > losses else 'Failed'}.**
- **C2 (the number):** corrected held-out grade **{arm_grade}**.
  **{'Held' if GRADE_RANK[arm_grade] >= GRADE_RANK['B'] else 'Failed'}.**

## The number, beside the shipped product's (2020–2024, corrected)

| Model | Calls | Hit rate | ECE | Judgeable bands | Calibrated | Resolution | Grade |
|---|---|---|---|---|---|---|---|
{shipped_line}
{arm_line}

## Star benchings (method §4c — reported, not a clause)

A star ranked top 12 (QB, TE) or top 24 (RB, WR) at his position last season.
Counted only when he was available (not OUT on the Tuesday report, not on bye).

| Model | Stars benched | Per 1,000 team-weeks | Benched star outscored the weakest starter he could have replaced |
|---|---|---|---|
| Shipped | {benched[0]} | {1000 * benched[0] / team_weeks:.0f} | {beat[0]} of {benched[0]}{f" ({beat[0] / benched[0]:.0%})" if benched[0] else ""} |
| Arm λ_L = {PRIMARY} | {benched[1]} | {1000 * benched[1] / team_weeks:.0f} | {beat[1]} of {benched[1]}{f" ({beat[1] / benched[1]:.0%})" if benched[1] else ""} |

## Sensitivity arms (reported, never substituted — method §2)

| Arm | Lineups W–L–T |
|---|---|
""" + "\n".join(f"| λ_L = {lam} | {w}–{l}–{t} (p = {sign_test(w, l):.4f}) |"
               for lam, w, l, t, _ in sens_rows) + """

| Model | Calls | Hit rate | ECE | Judgeable bands | Calibrated | Resolution | Grade |
|---|---|---|---|---|---|---|---|
""" + "\n".join(line for *_, line in sens_rows) + f"""

## The other setups (method §4d), with b′ = {b_prime:.4f}

| Arm | Setting | Lineups W–L–T | Sign test p | Calls | ECE | Grade | Decision |
|---|---|---|---|---|---|---|---|
""" + "\n".join(setup_rows) + """

## What this is not

It is a fixed-roster league: no trades, drops or pickups, so it cannot isolate
the player who lost his job over the summer or mid-season — the case where last
season is the worst guide (method §6). A lineup that scored more in one week is
not a better decision every time; over five seasons of differing team-weeks it
is the right aggregate.
"""
    args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
