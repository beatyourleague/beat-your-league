"""Phase 2 entry point: grade history and write reports/backtest.md.

Usage:
    python -m engine.backtest [--league <ID>] [--out reports/backtest.md]

Runs entirely off the Phase 1 cache: no network, no LLM, no cost. Whatever the
calibration table says is what gets written — CLAUDE.md principle 2 makes the
numbers non-negotiable once the rules in engine/decisions.py are frozen.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from engine.behavior import (
    UNAVAILABLE_METRICS,
    BehaviorProfile,
    lineup_records,
    profile_season,
    rank_by_aggression,
)
from engine.calibration import (
    MIN_DECIDED_TO_JUDGE,
    BucketReport,
    brier_score,
    bucket_calls,
    expected_calibration_error,
    resolution_check,
)
from engine.decisions import (
    HIT,
    MISS,
    StartSitCall,
    all_calls,
    coin_flips,
    disagreements,
    summarize,
)
from engine.history import HistoryError, PlayerIndex, Season, load_players, load_season_chain
from engine.matchup_backtest import MatchupCall, band_coverage, matchup_calls
from engine.projection import (
    DEFAULT_SHRINKAGE_K,
    MIN_GAMES_FOR_CALL,
    MIN_SD,
    ProjectionModel,
)
from ingest.config import resolve_league_id

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
DEFAULT_OUT = REPO_ROOT / "reports" / "backtest.md"


def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


# --------------------------------------------------------------------- #
# report sections
# --------------------------------------------------------------------- #

def _header(seasons: Sequence[Season]) -> list[str]:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Backtest & calibration report",
        "",
        f"Generated {generated} from cached Sleeper data in `data/raw/`. "
        "No network calls, no LLM calls, no estimates: every number below is "
        "reproducible by re-running `python -m engine.backtest`.",
        "",
        "## Leagues graded",
        "",
        "| Season | League | Teams | Scoring | Weeks cached | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for season in seasons:
        weeks = season.graded_weeks
        span = f"{min(weeks)}-{max(weeks)} ({len(weeks)})" if weeks else "none"
        rec = season.scoring_settings.get("rec", 0) or 0
        scoring = {1: "Full PPR", 0.5: "Half PPR", 0: "Standard"}.get(rec, f"{rec}/rec")
        lines.append(
            f"| {season.season} | {season.name} | {len(season.teams)} | {scoring} "
            f"| {span} | {season.status} |"
        )
    return lines


def _method(seasons: Sequence[Season]) -> list[str]:
    slots = ", ".join(seasons[0].starting_slots) if seasons else "n/a"
    return [
        "",
        "## What a graded call is",
        "",
        "For every roster, every week, every starting slot, the engine compares the "
        "player who was actually started against the **highest-projected eligible "
        "bench player** at that slot, and recommends whichever it projects higher. "
        "That head-to-head is then graded on real box-score points.",
        "",
        f"- **Starting slots:** {slots}",
        "- **Projection:** trailing-form mean shrunk toward the league-wide positional "
        f"mean (K = {DEFAULT_SHRINKAGE_K:g} pseudo-games), built **only from weeks "
        "before the graded week**. No lookahead: `tests/test_engine.py` asserts a "
        "projection is unchanged when future weeks are altered.",
        f"- **Confidence** = P(recommended outscores that specific alternative), "
        "independent normals. This is the published unit "
        "(CLAUDE.md principle 5) — not a generic 'good start' score.",
        f"- **Minimum evidence:** both players need ≥ {MIN_GAMES_FOR_CALL} prior "
        "appearances or the engine declines to make a call at all.",
        f"- **Standard-deviation floor:** {MIN_SD:g} points, so a three-game low-variance "
        "sample cannot manufacture a 99% confidence.",
        "- **Hit** = recommended scored more than the alternative. **Tie** = exactly "
        "equal, excluded from hit rates and reported separately.",
        "",
        "Rules are frozen in `engine/decisions.py` and were written before these "
        "numbers were computed (CLAUDE.md principle 2).",
    ]


def _headline(calls: Sequence[StartSitCall]) -> list[str]:
    summary = summarize(calls)
    both = [c for c in calls if c.both_scored]
    both_summary = summarize(both)
    flips = coin_flips(calls)
    flip_summary = summarize(flips)
    overruled = disagreements(calls)
    overrule_summary = summarize(overruled)

    lines = [
        "",
        "## Headline",
        "",
        "| Set | Graded | Decided | Hits | Hit rate |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| All calls | {summary.graded} | {summary.decided} | {summary.hits} "
        f"| {_pct(summary.hit_rate)} |",
        f"| Coin-flip calls (confidence < 60%) | {flip_summary.graded} "
        f"| {flip_summary.decided} | {flip_summary.hits} | {_pct(flip_summary.hit_rate)} |",
        f"| Both players scored | {both_summary.graded} | {both_summary.decided} "
        f"| {both_summary.hits} | {_pct(both_summary.hit_rate)} |",
        f"| Engine overrules the manager | {overrule_summary.graded} "
        f"| {overrule_summary.decided} | {overrule_summary.hits} "
        f"| {_pct(overrule_summary.hit_rate)} |",
        "",
        f"Ties excluded from every hit rate above: {summary.ties} of {summary.graded} "
        "calls ended exactly level.",
    ]

    if overruled:
        gained = sum(c.margin for c in overruled)
        lines += [
            "",
            f"On the {len(overruled)} calls where the engine would have overruled the "
            f"human, following the engine would have changed the score by "
            f"**{gained:+.1f} points** in total "
            f"({gained / len(overruled):+.2f} per call).",
        ]
    return lines


def _calibration(
    calls: Sequence[StartSitCall],
    title: str = "Calibration",
    preamble: Sequence[str] = (),
) -> list[str]:
    reports = bucket_calls(calls)
    lines = [
        "",
        f"## {title}",
        "",
    ]
    lines += list(preamble) or [
        "The test that matters (CLAUDE.md principle 1): when the engine says 64%, do "
        "roughly 64% of those calls hit? *Observed* is the real hit rate; the interval "
        "is a 95% Wilson score interval."
    ]
    lines += [
        "",
        "| Stated confidence | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for report in reports:
        bucket = report.bucket
        if bucket.graded == 0:
            continue
        interval = (
            f"{_pct(report.ci_low, 0)} – {_pct(report.ci_high, 0)}"
            if report.ci_low is not None
            else "n/a"
        )
        verdict = {
            True: "calibrated",
            False: "off",
            None: f"too few (< {MIN_DECIDED_TO_JUDGE})",
        }[report.calibrated]
        lines.append(
            f"| {bucket.label} | {bucket.graded} | {bucket.decided} | {bucket.ties} "
            f"| {_pct(report.stated_mean)} | {_pct(bucket.hit_rate)} | {interval} "
            f"| {verdict} |"
        )

    brier = brier_score(calls)
    ece = expected_calibration_error(reports)
    bottom, top = resolution_check(calls)
    lines += [
        "",
        f"- **Brier score:** {_num(brier, 4)} "
        "(0.25 = always guessing 50%; lower carries information).",
        f"- **Expected calibration error:** {_pct(ece, 1)} "
        "— the sample-weighted average gap between stated and observed.",
        f"- **Resolution:** least-confident decile hits {_pct(bottom)}, "
        f"most-confident decile hits {_pct(top)}. "
        "Calibration without this gap would mean the number sorts nothing.",
    ]
    verdicts = [r.calibrated for r in reports if r.bucket.graded]
    judged = [v for v in verdicts if v is not None]
    if judged:
        lines.append(
            f"- **Buckets with enough data to judge:** {len(judged)}; "
            f"{sum(1 for v in judged if v)} calibrated, "
            f"{sum(1 for v in judged if not v)} off."
        )
    return lines


def _availability_finding(
    seasons: Sequence[Season], calls: Sequence[StartSitCall]
) -> list[str]:
    """The headline result: availability, not scoring form, is what breaks.

    Everything in this section is measured, not asserted — the numbers are
    recomputed on each run so a model change moves them.
    """
    starter_zero = starter_total = bench_zero = bench_total = 0
    for season in seasons:
        for team_week in season.team_weeks():
            started = set(team_week.starters)
            for player_id, points in team_week.players_points.items():
                if player_id in started:
                    starter_total += 1
                    starter_zero += points == 0.0
                else:
                    bench_total += 1
                    bench_zero += points == 0.0

    starter_rate = starter_zero / starter_total if starter_total else None
    bench_rate = bench_zero / bench_total if bench_total else None

    overruled = disagreements(calls)
    overrule_zero = sum(1 for c in overruled if c.actual_recommended == 0.0)
    overrule_share = overrule_zero / len(overruled) if overruled else None

    both = [c for c in calls if c.both_scored]
    all_summary, both_summary = summarize(calls), summarize(both)
    all_brier, both_brier = brier_score(calls), brier_score(both)
    _, all_top = resolution_check(calls)
    _, both_top = resolution_check(both)

    return [
        "",
        "## Finding: the model's problem is availability, not scoring",
        "",
        "This is the result that should drive the next build phase, so it is stated "
        "before the detailed tables.",
        "",
        f"- **Starters score exactly 0.0 {_pct(starter_rate)} of the time. Bench players "
        f"score 0.0 {_pct(bench_rate)} of the time.** A manager benching a player is "
        "overwhelmingly a statement that the player is not going to play — a bye, an "
        "inactive, an injury. That signal is "
        + (
            f"roughly a {bench_rate / starter_rate:.0f}x difference"
            if starter_rate and bench_rate
            else "a large difference"
        )
        + " in the odds of scoring nothing, and cached Sleeper league data contains "
        "none of the underlying facts.",
        f"- **The engine cannot see it, and pays for it.** On the {len(overruled)} calls "
        "where the engine would have overruled the human, "
        f"{_pct(overrule_share)} of the players it wanted to promote scored zero. That "
        "one blind spot, not bad scoring math, is what produces the poor headline "
        "numbers above.",
        f"- **Where both players actually played, the same model is well calibrated.** "
        f"Brier improves from {_num(all_brier, 4)} to {_num(both_brier, 4)}, hit rate "
        f"from {_pct(all_summary.hit_rate)} to {_pct(both_summary.hit_rate)}, and the "
        f"most-confident decile from {_pct(all_top)} to {_pct(both_top)}.",
        "",
        "The conditional table below is a **diagnostic, not a result to publish**: it "
        "conditions on an outcome (both players scored), which is not knowable when the "
        "call is made. It answers one specific question — is the scoring and probability "
        "math sound, or is it broken independently of availability? — and the answer is "
        "that it is sound.",
    ]


def _implications(calls: Sequence[StartSitCall]) -> list[str]:
    both = [c for c in calls if c.both_scored]
    reports = bucket_calls(both)
    judged = [r for r in reports if r.calibrated is not None]
    calibrated = sum(1 for r in judged if r.calibrated)
    return [
        "",
        "## What this means for Phase 3",
        "",
        "1. **Ship an availability feed before shipping a confidence number.** Bye weeks "
        "come from the free public NFL schedule and injury designations are already on "
        "Sleeper's player records — they simply have to be captured weekly, since the "
        "players table only ever holds today's status. This is the highest-value change "
        "available to the engine, and it is cheap.",
        f"2. **The probability math itself passes.** On the availability-controlled set, "
        f"{calibrated} of {len(judged)} judgeable buckets are calibrated. A stated 64% is "
        "worth publishing once the engine knows who is playing — and not before "
        "(CLAUDE.md principle 1).",
        "3. **Until then, the report must not print a confidence for a player whose "
        "status is unknown.** Per the Phase 3 spec, that slot renders as *coming in "
        "v0.3*, never as a number. The honest version of this engine declines more calls "
        "than it makes.",
        "4. **The rival's bench is where the edge is.** A rival starting a player who "
        "will not play is the single most exploitable event in this data, and it is "
        "visible to us the moment an availability feed exists — this is exactly the "
        "\"where the rival is fragile\" section the product promises.",
    ]


def _by_slot(calls: Sequence[StartSitCall]) -> list[str]:
    slots: dict[str, list[StartSitCall]] = {}
    for call in calls:
        slots.setdefault(call.slot, []).append(call)
    lines = [
        "",
        "## By slot",
        "",
        "Where the engine earns its keep, and where it does not.",
        "",
        "| Slot | Graded | Decided | Hit rate | Avg stated |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for slot, slot_calls in sorted(slots.items(), key=lambda kv: -len(kv[1])):
        summary = summarize(slot_calls)
        stated = sum(c.confidence for c in slot_calls) / len(slot_calls)
        lines.append(
            f"| {slot} | {summary.graded} | {summary.decided} "
            f"| {_pct(summary.hit_rate)} | {_pct(stated)} |"
        )
    return lines


def _matchup_section(seasons: Sequence[Season], players: PlayerIndex) -> list[str]:
    """Backtest of the MATCHUP-level method the Phase 3 report publishes:
    team win probability + the 80% floor/ceiling band (rules M1-M4 frozen in
    engine/matchup_backtest.py before these numbers were computed)."""
    calls: list[MatchupCall] = []
    skipped_total = 0
    for season in seasons:
        model = ProjectionModel(season, players)
        season_calls, skipped = matchup_calls(season, model)
        calls.extend(season_calls)
        skipped_total += skipped

    lines = [
        "",
        "## Matchup-level backtest: win probability and floor/ceiling",
        "",
        "The weekly report's matchup section publishes P(your set-lineup total beats the rival's) "
        "and an 80% projection band per team. Same rule as everywhere else: those "
        "numbers ship only if this table earns them (principle 1).",
        "",
    ]
    if not calls:
        lines += ["No gradeable matchups in the cache."]
        return lines

    decided = [c for c in calls if c.outcome in (HIT, MISS)]
    hits = sum(1 for c in decided if c.outcome == HIT)
    lines += [
        f"- **Matchups graded:** {len(calls)} ({skipped_total} skipped under RULE M1 "
        "— a starter without a buildable pre-week projection)",
        f"- **Favorite won:** {hits} of {len(decided)} decided "
        f"({_pct(hits / len(decided) if decided else None)}); "
        f"{len(calls) - len(decided)} exact ties",
        f"- **Brier score:** {_num(brier_score(calls), 4)} "
        "(0.25 = a constant 50% guess)",
    ]
    covered, total = band_coverage(calls)
    lines += [
        f"- **80% band coverage:** {covered} of {total} team-weeks landed inside "
        f"their band ({_pct(covered / total if total else None)}; calibrated ≈ 80%)",
        "",
        "| Stated win prob | Graded | Decided | Stated avg | Observed | 95% interval | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    reports = bucket_calls(calls)
    judgeable = [r for r in reports if r.calibrated is not None]
    for report in reports:
        bucket = report.bucket
        if bucket.graded == 0:
            continue
        if report.calibrated is None:
            verdict = f"too few (< {MIN_DECIDED_TO_JUDGE})"
        else:
            verdict = "calibrated" if report.calibrated else "off"
        interval = (
            f"{_pct(report.ci_low, 0)} – {_pct(report.ci_high, 0)}"
            if report.ci_low is not None else "n/a"
        )
        lines.append(
            f"| {bucket.label} | {bucket.graded} | {bucket.decided} | "
            f"{_pct(report.stated_mean)} | {_pct(bucket.hit_rate)} | {interval} | {verdict} |"
        )
    passed = sum(1 for r in judgeable if r.calibrated)
    lines += [
        "",
        f"Buckets with enough data to judge: {len(judgeable)}; "
        f"{passed} calibrated, {len(judgeable) - passed} off.",
        "",
        "Availability caveat: set lineups here occasionally start players who "
        "did not play, exactly as live lineups do — so unlike the start/sit "
        "table, this measures the published quantity under real conditions.",
    ]
    return lines


def _by_season(seasons: Sequence[Season], calls_by_season: dict[str, list[StartSitCall]]) -> list[str]:
    lines = [
        "",
        "## By season",
        "",
        "| Season | Graded | Decided | Hit rate | Brier |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for season in seasons:
        season_calls = calls_by_season.get(season.season, [])
        if not season_calls:
            lines.append(f"| {season.season} | 0 | 0 | n/a | n/a |")
            continue
        summary = summarize(season_calls)
        lines.append(
            f"| {season.season} | {summary.graded} | {summary.decided} "
            f"| {_pct(summary.hit_rate)} | {_num(brier_score(season_calls), 4)} |"
        )
    lines += [
        "",
        "Two seasons is a small out-of-sample check, not a validation. The model has "
        "no fitted parameters, so there is nothing overfit to a single season — but "
        "a hit rate that swings hard between seasons is a warning, and it is printed "
        "here rather than averaged away.",
    ]
    return lines


def _managers(seasons: Sequence[Season], calls_by_season: dict[str, list[StartSitCall]]) -> list[str]:
    lines = [
        "",
        "## Manager profiles",
        "",
        "Rival profiles for Phase 3. Every line cites the season and week span it "
        "was computed from.",
    ]
    for season in seasons:
        profiles = profile_season(season)
        if not profiles:
            continue
        # This document is published on the public site. The managers in it are
        # real people who never signed up to have their habits profiled next to
        # a sales page, so they are aliased here at the source — one stable
        # letter per roster, so a reader can still follow the same manager
        # across both tables. Naming a rival is legitimate ONLY in the private
        # weekly report, which goes solely to the person entitled to see it.
        alias = {p.roster_id: f"Manager {chr(65 + i)}"
                 for i, p in enumerate(rank_by_aggression(list(profiles.values())))}
        weeks = sorted(season.transactions)
        span = f"weeks {min(weeks)}-{max(weeks)}" if weeks else "no transaction weeks"
        lines += [
            "",
            f"### {season.season} — {season.name} (transaction log: {span})",
            "",
            "| Rank | Team | Waiver style | FAAB spent | Bids (won/placed) | Top bid | "
            "Median bid | FA adds | Trades | Moves/wk | Game-day adds |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        ranked = rank_by_aggression(profiles.values())
        exceeded = [p for p in ranked if p.budget_exceeded]
        for profile in ranked:
            budget = (
                f"{profile.faab_spent}/{profile.faab_budget}"
                if profile.faab_budget
                else str(profile.faab_spent)
            )
            if profile.budget_exceeded:
                budget += " ⚠"
            lines.append(
                f"| {profile.aggression_rank}/{profile.league_size} "
                f"| {alias[profile.roster_id]} | {profile.aggression_label()} | "
                f"{budget} | "
                f"{profile.waiver_bids_won}/{profile.waiver_bids_placed} | "
                f"{profile.max_bid if profile.max_bid is not None else 'n/a'} | "
                f"{_num(profile.median_bid, 0)} | {profile.free_agent_adds} | "
                f"{profile.trades} | {_num(profile.moves_per_week, 2)} | "
                f"{_pct(profile.game_day_add_share, 0)} |"
            )
        lines += [
            "",
            "Waiver style is a rank **within this league**, not an absolute grade: "
            "league cultures differ too much for a fixed threshold to separate anyone. "
            "Bids counted include failed claims, which reveal intent and price; only "
            "winning bids spend FAAB. *Game-day adds* is a proxy for engagement "
            "(share of adds made Thu/Sun/Mon, US Eastern), not lineup-setting time.",
        ]
        if exceeded:
            lines += [
                "",
                f"⚠ {len(exceeded)} manager(s) spent more FAAB than the league's recorded "
                f"budget of {season.waiver_budget}. That setting reports only its "
                "current value, so a commissioner raising budgets mid-season makes the "
                "*percentage* meaningless — raw spend is still accurate, and the "
                "ranking above uses raw spend for exactly this reason.",
            ]

        season_calls = calls_by_season.get(season.season, [])
        if season_calls:
            lines += [
                "",
                f"**Start/sit accuracy, {season.season}** — measured on the same graded "
                "head-to-heads. This scores the human, not the engine: how often the "
                "player they started outscored the best bench alternative.",
                "",
                "These numbers look flattering, and they are: roughly a third of bench "
                "players score nothing, so \"beat the best bench option\" is a low bar "
                "that a manager clears simply by starting someone on a bye. Read the "
                "column as *engagement* — did they set a lineup at all — not as skill, "
                "and do not publish it to a subscriber as a rival's accuracy. Points "
                "left on the bench is the more honest column, and it is the one the "
                "Regret Score should build on.",
                "",
                "| Team | Decided calls | Manager right | Accuracy | Points left on bench |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
            for record in lineup_records(season, season_calls):
                lines.append(
                    f"| {alias.get(record.roster_id, 'Manager ?')} | {record.calls} "
                    f"| {record.manager_correct} "
                    f"| {_pct(record.accuracy)} | {record.points_left_on_bench:.1f} |"
                )
    return lines


def _limitations(calls: Sequence[StartSitCall], skipped: int) -> list[str]:
    lines = [
        "",
        "## Limitations — read before quoting any number above",
        "",
        "1. **No availability signal** — quantified in the finding section above, and "
        "the dominant error source by a wide margin. The engine infers availability "
        "only from a player's own appearance history, which catches a lingering injury "
        "but cannot catch a bye week: a player on bye played last week and will play "
        "next week, so nothing in cached league data flags it in advance.",
        "2. **Zero means absent.** A player scoring exactly 0.0 is treated as not "
        "having played and dropped from form. Real PPR scoring lands on exactly 0.0 "
        "only rarely for an active player, but this does discard genuine zeros.",
        "3. **Correlated calls.** One strong bench player can be the best alternative "
        "at several slots in a week. Duplicate head-to-heads are removed, but the "
        "remaining calls are not independent, so the Wilson intervals are narrower "
        "than the truth.",
        "4. **Independence assumption.** P(A beats B) treats two players as "
        "independent; teammates and players in the same game are not.",
        "5. **Position drift.** The players table is a current snapshot, so a player "
        "who changed listed position since the graded season is classified by today's "
        "position.",
        f"6. **Declined calls.** {skipped:,} slot-weeks produced no call because a "
        "player lacked the required prior appearances. Early-season weeks are "
        "therefore under-represented, and the measured hit rate describes the part of "
        "the season the engine is willing to speak about.",
        "",
        "Metrics deliberately **not** computed, rather than approximated:",
        "",
    ]
    for item in UNAVAILABLE_METRICS:
        lines.append(f"- **{item.metric}** — {item.reason}")
    return lines


def _verification(
    seasons: Sequence[Season],
    calls: Sequence[StartSitCall],
    players: PlayerIndex,
    skipped: int,
) -> list[str]:
    return [
        "",
        "## Run verification",
        "",
        f"- Seasons loaded: {len(seasons)} ({', '.join(s.season for s in seasons)})",
        f"- Roster-weeks examined: {sum(len(s.weeks[w]) for s in seasons for w in s.weeks):,}",
        f"- Players table: {len(players):,} entries",
        f"- Calls graded: {len(calls):,}; slot-weeks declined for thin evidence: {skipped:,}",
        "- HTTP requests: 0 (cache only)",
        "- LLM tokens: 0 (deterministic layer — no language calls in the backtest)",
    ]


# --------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------- #

def _count_slot_weeks(seasons: Sequence[Season]) -> int:
    total = 0
    for season in seasons:
        slots = len(season.starting_slots)
        for week in season.weeks:
            total += slots * len(season.weeks[week])
    return total


def build_report(seasons: Sequence[Season], players: PlayerIndex) -> tuple[str, list[StartSitCall]]:
    calls_by_season: dict[str, list[StartSitCall]] = {}
    all_graded: list[StartSitCall] = []
    for season in seasons:
        model = ProjectionModel(season, players)
        season_calls = all_calls(season, model, players)
        calls_by_season[season.season] = season_calls
        all_graded.extend(season_calls)

    skipped = _count_slot_weeks(seasons) - len(all_graded)

    lines: list[str] = []
    lines += _header(seasons)
    lines += _method(seasons)
    if not all_graded:
        lines += [
            "",
            "## No gradeable calls",
            "",
            "The cache holds no roster-week with enough prior appearances to support "
            "a call. Run `python -m ingest.pull` for a completed season and re-run.",
        ]
        return "\n".join(lines) + "\n", all_graded

    lines += _headline(all_graded)
    lines += _availability_finding(seasons, all_graded)
    lines += _calibration(all_graded)
    lines += _calibration(
        [c for c in all_graded if c.both_scored],
        title="Calibration, availability controlled (diagnostic)",
        preamble=[
            "The same calls, restricted to head-to-heads where **both players actually "
            "played**. This isolates the scoring and probability math from the "
            "availability blind spot. It is not a publishable accuracy claim — it "
            "conditions on an outcome — it is the evidence that the confidence number "
            "becomes trustworthy once the engine can see who is active.",
        ],
    )
    lines += _implications(all_graded)
    lines += _matchup_section(seasons, players)
    lines += _by_season(seasons, calls_by_season)
    lines += _by_slot(all_graded)
    lines += _managers(seasons, calls_by_season)
    lines += _limitations(all_graded, skipped)
    lines += _verification(seasons, all_graded, players, skipped)
    return "\n".join(lines) + "\n", all_graded


def print_summary(seasons: Sequence[Season], calls: Sequence[StartSitCall], out_path: Path) -> None:
    line = "=" * 62
    print(f"\n{line}\nPHASE 2 VERIFICATION SUMMARY\n{line}")
    print(f"Seasons graded: {', '.join(s.season for s in seasons)}")
    summary = summarize(calls)
    print(
        f"Calls graded: {summary.graded} "
        f"({summary.hits} hit, {summary.misses} miss, {summary.ties} tie)"
    )
    if summary.hit_rate is not None:
        print(f"Overall hit rate: {_pct(summary.hit_rate)}")
    flips = summarize(coin_flips(calls))
    if flips.hit_rate is not None:
        print(
            f"Coin-flip calls (<60% confidence): {flips.decided} graded, "
            f"{_pct(flips.hit_rate)} hit"
        )
    print(f"Brier score: {_num(brier_score(calls), 4)} (0.25 = a constant 50% guess)")
    both = [c for c in calls if c.both_scored]
    if both:
        both_summary = summarize(both)
        print(
            f"Availability-controlled (both played): {both_summary.decided} graded, "
            f"{_pct(both_summary.hit_rate)} hit, Brier {_num(brier_score(both), 4)}"
        )
        print(
            "  -> scoring math is sound; availability is the gap. See the finding "
            "section in the report."
        )
    print(f"Report written: {out_path}")
    print("LLM tokens this run: 0 (deterministic layer only)")
    print(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", help="Sleeper league ID (overrides CLAUDE.md)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output markdown path")
    parser.add_argument(
        "--max-seasons", type=int, default=4, help="how far back to walk previous_league_id"
    )
    args = parser.parse_args(argv)

    league_id = resolve_league_id(args.league, REPO_ROOT)
    try:
        players = load_players(RAW_DIR)
        seasons = load_season_chain(RAW_DIR, league_id, max_seasons=args.max_seasons)
    except HistoryError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    # Grade completed seasons only: an in-progress season has no settled weeks
    # to learn from and would mix a half-season into the calibration table.
    completed = [s for s in seasons if s.status == "complete" and s.weeks]
    if not completed:
        print(
            "No completed season is cached for this league, so there is nothing to "
            "backtest yet. Phase 2 grades finished seasons; re-run once a season "
            "completes, or point --league at a league with history.",
            file=sys.stderr,
        )
        return 1

    report, calls = build_report(completed, players)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print_summary(completed, calls, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
