"""Build ``week_report.json`` — the single input to the Phase 3 renderer.

Usage:
    python -m engine.week_report --week N --roster R [--league ID] [--output PATH]

Everything in the output is either (a) computed from cached Sleeper data with
its evidence attached, or (b) an explicit gap ``{"gate": reason}`` that the
renderer shows as *coming in v0.3*. Nothing is invented (CLAUDE.md principle 3),
and no probability is published unless availability is known for both players
involved (principle 1, enforced by ``engine.availability.may_publish_confidence``).

This JSON is also the future language-layer input: the prose model will be
prompted to reference only numbers present here, so every number carries its
own basis.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.availability import (
    PlayerStatus, Status, WeekAvailability, load_week_availability,
    may_publish_confidence,
)
from engine.behavior import profile_season, rank_by_aggression
from engine.decisions import HIT, MISS, StartSitCall, calls_for_team_week, summarize
from engine.history import (
    EMPTY_SLOT_IDS, FLEX_ELIGIBILITY, HistoryError, PlayerIndex, Season,
    TeamWeek, load_players, load_season_chain,
)
from engine.last_week import headline as last_week_headline
from engine.roster import DEFENSE
from engine.last_week import summarise as last_week_summary
from engine.usage import recent_usage, usage_line
from engine.projection import (
    MIN_GAMES_FOR_CALL, Projection, ProjectionModel, probability_outscores,
)
from engine.waivers import build_waiver_market, market_json

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# 10th/90th percentile of a normal — the template's floor/ceiling band.
Z_80_BAND = 1.2816

# Matchup-level calibration evidence (reports/backtest.md, matchup section,
# 2017+2018 sample seasons — regenerate and revisit when real league history
# lands):
# - The 80% floor/ceiling band covered 77.9% of 340 team-weeks -> it ships.
# - The win probability's only well-populated bucket (stated 50-55%) observed
#   64.5% — systematically underconfident, so per principle 1 the number does
#   NOT ship. Flip this flag only with fresh backtest.md evidence that passes.
WIN_PROBABILITY_CALIBRATED = False

# Team defenses: SCOREABLE, but not MEASURED. The two are different questions and
# conflating them is how an unsupported number ships.
#
# The frozen backtest method (reports/nflverse-backtest-method.md §3) excludes
# defenses from the graded set, and justifies it by calling them "unscoreable",
# citing engine/scoring.py:26-32 and engine/subscriber.py:282-290. Both spans now
# say the opposite: the first is RULE S4 (a defense IS scored, from the team's own
# week plus the schedule's final score) and the second is the code that calls
# score_defense. So the product went on to score defenses, project them and
# publish a confidence on them — 0.627 on the Denver defense in a real 2024
# week-10 report — while reports/nflverse-backtest.md graded 0 of 10,041 calls on
# a DEF slot. A published probability with no graded call behind it is precisely
# what principle 1 forbids.
#
# Gated rather than quietly folded into the existing run, because the method says
# in terms that nothing in it may change after an output is read: adding defenses
# to the graded set requires a NEW preregistration and a new commit. Until that
# measurement exists this behaves exactly like WIN_PROBABILITY_CALIBRATED — the
# machinery stays, the number does not print, and the reason is stated in the
# buyer's own words. Flip it only with passing evidence for the DEF population
# specifically.
TEAM_DEFENSE_CONFIDENCE_CALIBRATED = False
DEFENSE_GATE = ("we don't put a number on defenses yet — we haven't tested our "
                "defense calls against enough real weeks to stand behind one")
# Buyer-facing wording: plain English, no file paths, no lab vocabulary.
WIN_PROBABILITY_GATE = (
    "No win percentage. We tested one against two seasons and our favorites "
    "won more often than it said, so the number would mislead you")
# "Your" was wrong once both bands shared one axis: this captions the rival's
# range as much as yours, and it sat directly above a pair of numerals that
# were the UNION of the two, not either team's.
TEAM_RANGE_BASIS = (
    "Each team's realistic high and low. Testing on two past seasons, real "
    "weekly totals landed inside this range about 78% of the time.")


class WeekReportError(RuntimeError):
    """Raised with an actionable message when the report cannot be built."""


# --------------------------------------------------------------------- #
# lineup construction
# --------------------------------------------------------------------- #

@dataclass
class SlotPick:
    """One starting slot in a lineup, with everything the renderer shows."""

    slot: str
    slot_index: int
    player_id: str | None
    projection: Projection | None
    status: PlayerStatus | None
    confidence: float | None          # vs best alternative; None when gated
    confidence_gate: str | None       # why it is None
    alternative_id: str | None        # the specific alternative confidence is against
    alternative_projection: Projection | None
    flags: list[dict[str, str]]       # renderer chips: {"kind", "text"}


def _slot_restrictiveness(slot: str) -> int:
    allowed = FLEX_ELIGIBILITY.get(slot)
    return len(allowed) if allowed else 1


def _place_without_projections(season: Season, team_week: TeamWeek,
                               players: PlayerIndex,
                               ranking: Mapping[str, float] | None = None,
                               ) -> dict[int, str]:
    """Put each eligible player in a slot when this season has no form yet.

    Greedy in slot-restrictiveness order, the same order the projected path
    uses, so a single-position slot claims its player before a flex can take
    him.

    ``ranking`` decides WHICH eligible player takes a slot when more than one
    could. Without it the order came off the player id, which is reproducible
    and meaningless — and in week 1 that is not a harmless default: with three
    running backs and two RB slots, an arbitrary two of them start. Ranked on
    last season's points per game, the same three-back roster seats the two who
    actually produced.

    That is an ORDERING, never a projection. Last season is a record of what
    happened, not a claim about this week, so nothing built from it carries a
    number: every row still has no projection, no confidence, and a reason.
    Ties, and players with no prior season at all, fall back to the id so a
    report stays byte-identical across runs.
    """
    order = sorted(range(len(season.starting_slots)),
                   key=lambda i: (_slot_restrictiveness(season.starting_slots[i]), i))
    rank = ranking or {}
    placed: dict[int, str] = {}
    used: set[str] = set()
    for index in order:
        slot = season.starting_slots[index]
        candidates = sorted(
            (pid for pid in team_week.players
             if pid not in used and pid not in EMPTY_SLOT_IDS
             and (info := players.get(pid)) is not None and info.eligible_for(slot)),
            key=lambda pid: (-rank.get(pid, 0.0), pid))
        if candidates:
            placed[index] = candidates[0]
            used.add(candidates[0])
    return placed


def optimal_lineup(
    season: Season,
    team_week: TeamWeek,
    model: ProjectionModel,
    players: PlayerIndex,
    availability: WeekAvailability,
    week: int,
    prior_form: Mapping[str, float] | None = None,
) -> list[SlotPick]:
    """Fill the starting slots with the highest-projected available players.

    Assignment is greedy in slot-restrictiveness order (single-position slots
    claim their player before flexes), which is optimal for the common league
    shapes and deterministic everywhere. Players classified OUT are excluded
    unless a slot would otherwise go empty — then the least-bad player is
    seated and flagged, never silently.

    ``week`` is the week being PROJECTED, and it is an explicit argument rather
    than ``team_week.week`` because deriving it was a trap that cost a week of
    form on every solo report and every backtest call. ``team_week`` is only a
    roster carrier here — which is exactly how both callers used it, one of them
    saying so in a comment — but its ``.week`` silently became the model's
    ``before_week``, and ``build_season`` stops at W-1, so the report for week W
    projected from weeks 1..W-2. Week W-1 was loaded into the model and then
    filtered back out. Passing the week is what makes the two independent.
    """
    projections = {
        pid: proj
        for pid in team_week.players
        if (proj := model.project(pid, week)) is not None
    }
    statuses = {pid: availability.classify(pid) for pid in team_week.players}

    if not projections:
        # Week 1: the model holds no opinion about anyone on the roster. An
        # "optimal" lineup of nine empty slots reads as broken software, not
        # honesty — the subscriber HAS a lineup. Render it exactly as set,
        # the same treatment the rival's grid gets, with calls starting once
        # a record exists to compare against.
        picks: list[SlotPick] = []
        # A solo roster has no `starters` at all (RULE B3: we never saw a
        # lineup), so reading them rendered EVERY slot empty and the checklist
        # then told a subscriber with a full roster that they had "nobody to
        # start at QB, RB, TE, WR" — a confident false statement about players
        # the report can see, which is worse than the exception it replaced.
        # Placement by eligibility instead, deterministic on id so a report is
        # byte-identical across runs. It is PLACEMENT, not a call: the reason
        # on every row says so, and no confidence is attached to any of it.
        placed = _place_without_projections(season, team_week, players,
                                            prior_form) \
            if not team_week.starters else {}
        for index, slot in enumerate(season.starting_slots):
            pid = (team_week.starters[index]
                   if index < len(team_week.starters) else placed.get(index))
            if pid in EMPTY_SLOT_IDS:
                pid = None
            picks.append(SlotPick(
                slot, index, pid, None,
                statuses.get(pid) if pid else None, None,
                "no game record yet to compare against", None, None, []))
        return picks

    order = sorted(
        range(len(season.starting_slots)),
        key=lambda i: (_slot_restrictiveness(season.starting_slots[i]), i),
    )
    assigned: dict[int, str] = {}
    used: set[str] = set()

    def eligible(slot: str, exclude_out: bool) -> list[str]:
        out = []
        for pid in team_week.players:
            if pid in used or pid in EMPTY_SLOT_IDS:
                continue
            info = players.get(pid)
            if info is None or not info.eligible_for(slot):
                continue
            if exclude_out and statuses[pid].status is Status.OUT:
                continue
            if pid not in projections:
                continue
            out.append(pid)
        return sorted(out, key=lambda p: projections[p].mean, reverse=True)

    for index in order:
        slot = season.starting_slots[index]
        candidates = eligible(slot, exclude_out=True) or eligible(slot, exclude_out=False)
        if candidates:
            assigned[index] = candidates[0]
            used.add(candidates[0])

    picks_by_index: dict[int, SlotPick] = {}
    # Second pass in the same restrictive order, so a RULE 3 swap frees the
    # displaced player for later, less restrictive slots.
    for index in order:
        slot = season.starting_slots[index]
        pid = assigned.get(index)
        if pid is None:
            picks_by_index[index] = SlotPick(
                slot, index, None, None, None, None,
                "no eligible player with any scoring history", None, None, [])
            continue
        projection = projections[pid]
        status = statuses[pid]
        alternatives = eligible(slot, exclude_out=True)
        alt_id = alternatives[0] if alternatives else None

        confidence = None
        gate: str | None = None
        alt_projection = projections.get(alt_id) if alt_id else None
        if alt_id is None or alt_projection is None:
            gate = "nobody on your bench is eligible here"
        elif (projection.evidence < MIN_GAMES_FOR_CALL
              or alt_projection.evidence < MIN_GAMES_FOR_CALL):
            # ``evidence`` = real games plus any preregistered prior-season
            # seed (reports/early-season-method.md §2). With no seed active it
            # IS the game count, so weeks 4+ behave exactly as before.
            gate = (f"not enough games on record yet ({projection.games} and "
                    f"{alt_projection.games}; we want at least {MIN_GAMES_FOR_CALL})")
        elif not TEAM_DEFENSE_CONFIDENCE_CALIBRATED and (
                pid.startswith(f"{DEFENSE}-")
                or alt_id.startswith(f"{DEFENSE}-")):
            # Either side being a defense is enough: the published unit is
            # "this player beats that one at this slot", and no such pair has
            # ever been graded when either half is a team defense.
            gate = DEFENSE_GATE
        else:
            ok, reason = may_publish_confidence(status, statuses[alt_id])
            if ok:
                confidence = probability_outscores(projection, alt_projection)
                if confidence < 0.5:
                    # RULE 3 (decisions.py): recommend on probability, not on
                    # expected points — the two disagree for volatile players.
                    # Publishing "start A, 43%" would advise a start the model
                    # expects to lose, and next week's grader would grade the
                    # opposite call. Seat the alternative instead.
                    used.discard(pid)
                    used.add(alt_id)
                    pid, alt_id = alt_id, pid
                    projection, alt_projection = alt_projection, projection
                    status = statuses[pid]
                    confidence = 1.0 - confidence
            else:
                gate = reason

        flags: list[dict[str, str]] = []
        if status.status is Status.OUT:
            flags.append({"kind": "out", "text": f"OUT — {status.reason}"})
        elif status.status is Status.QUESTIONABLE:
            flags.append({"kind": "questionable", "text": status.reason})
        if confidence is not None and (
                projection.seeded_games
                or (alt_projection is not None and alt_projection.seeded_games)):
            # The preregistered disclosure (reports/early-season-method.md §5):
            # a call whose evidence includes the prior-season seed says so on
            # the row it prints on, every surface.
            flags.append({"kind": "seeded", "text": "last season counted in"})
        picks_by_index[index] = SlotPick(slot, index, pid, projection, status,
                                         confidence, gate, alt_id, alt_projection,
                                         flags)
    return [picks_by_index[i] for i in sorted(picks_by_index)]


def rival_lineup(
    season: Season,
    team_week: TeamWeek,
    model: ProjectionModel,
    players: PlayerIndex,
    availability: WeekAvailability,
    week: int,
) -> list[SlotPick]:
    """The rival's lineup **as currently set**, with fragility flags.

    We render what they have actually done, not what they should do — the
    product's edge is seeing where the set lineup is fragile.

    ``week`` is explicit for the same reason it is on ``optimal_lineup``: a
    TeamWeek is a roster carrier and its ``.week`` must never quietly decide
    which weeks the model may read.
    """
    picks: list[SlotPick] = []
    started = set(team_week.starters)
    projections: dict[int, Projection] = {}
    # (slot_index, bench_id) -> that bench player's projection, for every pair
    # the league would actually allow.
    candidates: dict[tuple[int, str], Projection] = {}
    for index, slot in enumerate(season.starting_slots):
        # A short or null starters array means unset slots, not fewer slots —
        # emit an unfilled pick so win_probability's gate still sees it.
        pid = team_week.starters[index] if index < len(team_week.starters) else None
        if pid is None or pid in EMPTY_SLOT_IDS:
            picks.append(SlotPick(slot, index, None, None, None, None,
                                  "slot left empty", None, None,
                                  [{"kind": "out", "text": "EMPTY SLOT"}]))
            continue
        projection = model.project(pid, week)
        status = availability.classify(pid)
        flags: list[dict[str, str]] = []
        if status.status is Status.OUT:
            flags.append({"kind": "out", "text": f"OUT — {status.reason}"})
        elif status.status is Status.QUESTIONABLE:
            flags.append({"kind": "questionable", "text": status.reason})
        if projection is not None and projection.games < MIN_GAMES_FOR_CALL:
            flags.append({"kind": "thin",
                          "text": f"only {projection.games} scoring games on record"})
        if projection is not None:
            projections[index] = projection
        for bench_id in team_week.players:
            if bench_id in started or bench_id in EMPTY_SLOT_IDS:
                continue
            info = players.get(bench_id)
            if info is None or not info.eligible_for(slot):
                continue
            alt = model.project(bench_id, week)
            if alt is None or alt.games < MIN_GAMES_FOR_CALL:
                continue
            if availability.classify(bench_id).status is Status.OUT:
                continue
            candidates[(index, bench_id)] = alt
        picks.append(SlotPick(slot, index, pid, projection, status, None, None,
                              None, None, flags))

    for index, bench_id, alt in _assign_alternatives(candidates, projections):
        pick = picks[index]
        pick.alternative_id = bench_id
        pick.alternative_projection = alt
        gain = alt.mean - projections[index].mean
        if gain > 0:
            pick.flags.append({
                "kind": "bench_better",
                "text": (f"their bench {players.name(bench_id)} projects higher "
                         f"({alt.mean:.1f} vs {projections[index].mean:.1f})"),
            })
    return picks


def _assign_alternatives(
    candidates: Mapping[tuple[int, str], Projection],
    projections: Mapping[int, Projection],
) -> list[tuple[int, str, Projection]]:
    """Give each bench player to at most ONE slot: the one he improves most.

    Computing the best alternative per slot independently let a single bench
    receiver be named as the fix for four different slots at once — four
    exploitable spots reported where the roster only ever contained one. The
    rival cannot start him twice, so neither may we say so. Greedy by gain,
    which is the order a manager would actually make the swaps in.
    """
    ranked = sorted(
        ((alt.mean - projections[index].mean, index, bench_id, alt)
         for (index, bench_id), alt in candidates.items()
         if index in projections),
        # Ties broken on the ids so a report is byte-identical across runs.
        key=lambda item: (-item[0], item[1], item[2]),
    )
    taken_slots: set[int] = set()
    taken_bench: set[str] = set()
    assigned: list[tuple[int, str, Projection]] = []
    for _, index, bench_id, alt in ranked:
        if index in taken_slots or bench_id in taken_bench:
            continue
        taken_slots.add(index)
        taken_bench.add(bench_id)
        assigned.append((index, bench_id, alt))
    return assigned


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

# Buyer-facing reason when the totals/band cannot be published. Week 1 is the
# common case: no games have been played, so there is no record to project from.
# "Your league hasn't played" was written for the retired product, which read
# a league; this one never does, and a sentence implying we can see their
# league is the same wrong-reason failure the constant below exists to avoid.
TEAM_RANGE_GATE = (
    "no projected totals yet — the season hasn't played its first games, and "
    "we don't publish a number without a record behind it. Totals and ranges "
    "start once box scores exist.")


# A DIFFERENT reason for the same withheld number. The week-1 message ("the
# season hasn't played its first games") is false when the real problem is a
# lineup slot nobody can fill, and a wrong reason for a withheld number is its
# own principle-3 failure — the subscriber goes looking for the wrong fix.
TEAM_RANGE_INCOMPLETE = (
    "no projected total — your lineup has a slot we can't fill from your "
    "roster, so any total we showed would be the sum of the slots you CAN "
    "fill, quietly presented as your team's.")


def team_range_gate(picks: list[SlotPick]) -> str:
    """Which reason applies. Unfillable slots first: it is the more specific
    fact and the only one the subscriber can act on."""
    if any(p.player_id is None for p in picks):
        return TEAM_RANGE_INCOMPLETE
    return TEAM_RANGE_GATE


def _team_range(picks: list[SlotPick]) -> dict[str, float] | None:
    """The team total and its 80% band — or None when it cannot be honest.

    The 77.9% coverage evidence behind TEAM_RANGE_BASIS was measured only on
    team-weeks where every starter had a buildable pre-week projection (matchup
    backtest RULE M1 skips the rest). Summing whatever projections happen to
    exist would publish an UNDERCOUNT dressed as a total — in week 1, with no
    projections at all, it rendered "proj 0.0 · floor 0 · ceiling 0" under a
    "78% of the time" basis line. A fabricated zero is still a fabrication
    (principle 3), so the band gates instead.

    An UNFILLED slot gates for the same reason, and used to not: it was dropped
    from the sum silently, so a nine-slot lineup missing a kicker and a defense
    published the sum of SEVEN slots as the team total — an undercount wearing a
    total's name, under a band whose 77.9% coverage was measured only on
    team-weeks where every starter had a projection. A subscriber who cannot
    fill a slot needs telling, not a quietly smaller number.
    """
    if any(p.player_id is None for p in picks):
        return None
    filled = [p for p in picks if p.player_id is not None]
    if any(p.projection is None for p in filled) or not filled:
        return None
    mean = sum(p.projection.mean for p in filled)
    variance = sum(p.projection.sd ** 2 for p in filled)
    sd = variance ** 0.5
    return {
        "projected_total": round(mean, 1),
        "sd": round(sd, 3),
        "floor": round(mean - Z_80_BAND * sd, 1),
        "ceiling": round(mean + Z_80_BAND * sd, 1),
    }


def win_probability(
    mine: list[SlotPick], theirs: list[SlotPick]
) -> tuple[float | None, str | None]:
    """P(my optimal total > rival's set total).

    Two gates, both must open: the method must be calibrated (module flag,
    backtest evidence) and availability must be known for every starter.
    """
    if not WIN_PROBABILITY_CALIBRATED:
        return None, WIN_PROBABILITY_GATE
    blockers: list[str] = []
    for side, picks in (("your", mine), ("rival", theirs)):
        for pick in picks:
            if pick.player_id is None or pick.projection is None:
                blockers.append(f"{side} {pick.slot} unfilled/unprojected")
            elif pick.status is None or pick.status.status is not Status.ACTIVE:
                reason = pick.status.reason if pick.status else "unknown"
                blockers.append(f"{side} {pick.slot}: {reason}")
    if blockers:
        sample = "; ".join(blockers[:3])
        more = f" (+{len(blockers) - 3} more)" if len(blockers) > 3 else ""
        return None, f"availability not confirmed for every starter — {sample}{more}"

    from engine.projection import _normal_beats  # same math, one implementation
    my_mean = sum(p.projection.mean for p in mine if p.projection)
    my_var = sum(p.projection.sd ** 2 for p in mine if p.projection)
    their_mean = sum(p.projection.mean for p in theirs if p.projection)
    their_var = sum(p.projection.sd ** 2 for p in theirs if p.projection)
    return _normal_beats(my_mean, my_var ** 0.5, their_mean, their_var ** 0.5), None


def _usage_driver(raw_dir: Path | None, season: str | None, week: int | None,
                  pick_id: str | None, alt_id: str | None) -> list[dict[str, str]]:
    """Opportunity for both sides of the week's closest call.

    Every other driver is the model talking about itself. This one is the
    league's own record, and it is the axis the gate backtest showed actually
    separates players — the availability blind spot turned out to be healthy
    players who were not going to get the ball, not injured ones.

    Only shown when BOTH sides have a figure: a count for one player and a
    blank for the other invites a comparison the data does not support.
    """
    if not (raw_dir and season and week and pick_id and alt_id):
        return []
    a = recent_usage(raw_dir, pick_id, season, week)
    b = recent_usage(raw_dir, alt_id, season, week)
    drivers: list[dict[str, str]] = []
    if a.targets is not None and b.targets is not None:
        drivers.append({"label": "targets",
                        "value": f"{a.targets} vs {b.targets}"})
    if a.snaps is not None and b.snaps is not None:
        drivers.append({"label": "snaps", "value": f"{a.snaps} vs {b.snaps}"})
    return drivers


def regret_call(picks: list[SlotPick], players: PlayerIndex,
                raw_dir: Path | None = None, season: str | None = None,
                week: int | None = None) -> dict[str, Any]:
    """The week's closest published call — decided, with its drivers."""
    decided = [
        p for p in picks
        if p.confidence is not None and p.alternative_id is not None
    ]
    if not decided:
        gates = [p.confidence_gate for p in picks if p.confidence_gate]
        reason = gates[0] if gates else "nothing close enough to be worth calling"
        return {"gate": f"no coin-flip call this week — {reason}"}
    closest = min(decided, key=lambda p: p.confidence or 1.0)
    assert closest.projection and closest.alternative_projection
    return {
        "slot": closest.slot,
        "start_id": closest.player_id,
        "start_name": players.name(closest.player_id or ""),
        "over_id": closest.alternative_id,
        "over_name": players.name(closest.alternative_id),
        "confidence": round(closest.confidence or 0.0, 3),
        "drivers": [
            {"label": "proj", "value": f"{closest.projection.mean:.1f} vs "
                                       f"{closest.alternative_projection.mean:.1f}"},
            {"label": "form games", "value": f"{closest.projection.games} vs "
                                             f"{closest.alternative_projection.games}"},
        ] + ([{"label": "seeded", "value": "last season counted in"}]
             if (closest.projection.seeded_games
                 or closest.alternative_projection.seeded_games) else []) + [
            {"label": "suits up", "value": f"{closest.projection.appear_probability:.0%} vs "
                                              f"{closest.alternative_projection.appear_probability:.0%}"},
        ] + _usage_driver(raw_dir, season, week, closest.player_id,
                          closest.alternative_id),
        "definition": ("What the number means: the odds this guy outscores that "
                       "specific bench option at this slot."),
    }


def hype_meter(
    season: Season, week: int, players: PlayerIndex, budget: int | None
) -> list[dict[str, Any]]:
    """League-wide waiver FOMO from the transaction log, most-chased first.

    Measures the *chase* (bids, including failed ones, and adds). The real-or-
    mirage verdict needs usage data (routes/snaps) that is not ingested yet, so
    it is a gap, not a guess.

    Window honesty: a live pre-week report may read the report week's own
    transactions (they are all, by definition, in the past at generation time).
    A historical render must not — the report-week log contains moves made
    after the week's games, which a real pre-week report could never have seen.
    """
    if season.status == "complete":
        windows = [w for w in (week - 1,) if w in season.transactions]
    else:
        windows = [w for w in (week - 1, week) if w in season.transactions]
    chases: dict[str, dict[str, Any]] = {}
    for w in windows:
        for txn in season.transactions[w]:
            if txn.get("type") not in ("waiver", "free_agent"):
                continue
            adds = txn.get("adds")
            if not isinstance(adds, dict):
                continue
            bid = (txn.get("settings") or {}).get("waiver_bid")
            for pid, roster_id in adds.items():
                entry = chases.setdefault(str(pid), {
                    "player_id": str(pid), "bids": 0, "adds": 0,
                    "managers": set(), "top_bid": None,
                })
                if txn.get("type") == "waiver":
                    entry["bids"] += 1
                    if isinstance(bid, int):
                        entry["top_bid"] = max(entry["top_bid"] or 0, bid)
                if txn.get("status") == "complete":
                    entry["adds"] += 1
                if isinstance(roster_id, int):
                    entry["managers"].add(roster_id)
    ranked = sorted(
        chases.values(),
        key=lambda e: (len(e["managers"]), e["bids"], e["top_bid"] or 0),
        reverse=True,
    )
    out = []
    for entry in ranked[:2]:
        if len(entry["managers"]) < 2 and entry["bids"] < 2:
            continue  # one quiet add is not FOMO
        out.append({
            "player_id": entry["player_id"],
            "player_name": players.name(entry["player_id"]),
            "position": players.position(entry["player_id"]),
            "managers_chasing": len(entry["managers"]),
            "bids": entry["bids"],
            "completed_adds": entry["adds"],
            "top_bid": entry["top_bid"],
            "faab_budget": budget,
            "evidence": ((f"league transaction log, week {windows[0]}"
                          if len(windows) == 1 else
                          f"league transaction log, weeks {min(windows)}-{max(windows)}")
                         if windows else "no transaction data"),
            "verdict_gate": ("We can see the whole league chasing him, and the "
                             "usage below is what he has actually been given. "
                             "Whether that holds up behind a different offense "
                             "is not something we put a number on, so we're not "
                             "calling this one real or a mirage."),
        })
    return out


def receipts(
    season: Season, before_week: int, model: ProjectionModel,
    players: PlayerIndex, my_roster_id: int, raw_dir: Path,
) -> dict[str, Any]:
    """The graded ledger of calls the product would actually have PUBLISHED.

    Principle 2 grades our published calls, not hypotheticals: only this
    subscriber's roster, and only head-to-heads that passed the availability
    gate in their own week (the same ``may_publish_confidence`` the live report
    enforces). Weeks with no snapshot contribute nothing — so the ledger starts
    exactly when publishing started, never retroactively.
    """
    calls: list[StartSitCall] = []
    for week in season.graded_weeks:
        if week >= before_week:
            continue
        team_week = season.weeks[week].get(my_roster_id)
        if team_week is None:
            continue
        week_availability = load_week_availability(raw_dir, season.season, week)
        for call in calls_for_team_week(season, team_week, model, players):
            ok, _ = may_publish_confidence(
                week_availability.classify(call.recommended_id),
                week_availability.classify(call.benched_id),
            )
            if ok:
                calls.append(call)
    if not calls:
        return {"record": None,
                "note": "Ledger opens this week — every published call gets "
                        "graded against the real box score, hit or miss."}
    summary = summarize(calls)
    decided = [c for c in calls if c.outcome in (HIT, MISS)]
    best = max(decided, key=lambda c: c.margin, default=None)
    worst = min(decided, key=lambda c: c.margin, default=None)

    def cite(call: StartSitCall) -> dict[str, Any]:
        return {
            "week": call.week,
            "slot": call.slot,
            "recommended": players.name(call.recommended_id),
            "over": players.name(call.benched_id),
            "confidence": round(call.confidence, 3),
            "margin": round(call.margin, 1),
            "outcome": call.outcome,
        }

    return {
        "record": {
            "graded": summary.graded, "hits": summary.hits,
            "misses": summary.misses, "ties": summary.ties,
            "hit_rate": round(summary.hit_rate, 3) if summary.hit_rate is not None else None,
        },
        "best_call": cite(best) if best else None,
        "worst_call": cite(worst) if worst else None,
        "note": (f"Your published calls through week {before_week - 1}: "
                 f"{summary.hits}-{summary.misses}"
                 + (f"-{summary.ties}" if summary.ties else "")
                 + ". Wins and misses alike, graded on real box scores."),
    }


def fragility(
    season: Season,
    history: Season | None,
    rival_picks: list[SlotPick],
    rival_roster_id: int,
    players: PlayerIndex,
    history_model: ProjectionModel | None,
    raw_dir: Path | None = None,
    week: int | None = None,
) -> list[dict[str, str]]:
    """Where the rival is fragile — every line cites its evidence."""
    items: list[dict[str, str]] = []
    for pick in rival_picks:
        for flag in pick.flags:
            if flag["kind"] in ("out", "questionable"):
                name = players.name(pick.player_id or "")
                items.append({
                    "title": f"Their {pick.slot} may not play",
                    "detail": f"{name}: {flag['text']}.",
                    "evidence": "injury and inactive report"
                                + (f", as of {pick.status.as_of}" if pick.status and pick.status.as_of else ""),
                })

    # Each bench player is assigned to at most ONE slot upstream, so every
    # line here is a distinct exploitable spot rather than the same benched
    # receiver counted once per slot he happens to be eligible for. Biggest
    # gain first — that is the one worth reading.
    beating = [p for p in rival_picks
               if p.alternative_id and p.projection and p.alternative_projection
               and any(f["kind"] == "bench_better" for f in p.flags)]
    for pick in sorted(beating, key=lambda p: -(p.alternative_projection.mean
                                                - p.projection.mean)):
        alt_id = pick.alternative_id or ""
        alt_projection = pick.alternative_projection
        assert alt_projection is not None and pick.projection is not None
        # What he has actually been given, when we can say it. A projection is
        # our opinion; a target count is the league's own record, and it is the
        # difference between "we think he is better" and "look what he gets".
        usage_note = ""
        if raw_dir is not None and week is not None:
            line = usage_line(recent_usage(raw_dir, alt_id, season.season, week))
            if line:
                usage_note = f" And he is being used: {line}."
        items.append({
            "title": f"{players.name(alt_id)} is sitting on their bench",
            "detail": (f"He projects {alt_projection.mean:.1f} against "
                       f"{players.name(pick.player_id or '')} at {pick.slot} "
                       f"({pick.projection.mean:.1f}).{usage_note}"),
            "evidence": f"based on scoring through week "
                        f"{alt_projection.as_of_week - 1}, {season.season}",
        })

    # Behavioral lines join across seasons by OWNER, not roster id — owners
    # change roster slots between seasons, and a wrong join would pin last
    # year's habits on the wrong person.
    rival_team = season.teams.get(rival_roster_id)
    rival_owner = rival_team.owner_id if rival_team else None
    hist_roster_id = None
    if history is not None and rival_owner:
        hist_roster_id = next(
            (rid for rid, team in history.teams.items()
             if team.owner_id == rival_owner), None)
    if history is not None and history_model is not None and hist_roster_id is not None:
        profiles = rank_by_aggression(profile_season(history).values())
        profile = next((p for p in profiles if p.roster_id == hist_roster_id), None)
        if profile is not None and profile.active_weeks:
            items.append({
                "title": f"Waiver style last season: {profile.aggression_label()}",
                "detail": (f"{profile.waiver_bids_won} of {profile.waiver_bids_placed} claims won, "
                           f"{profile.faab_spent} FAAB spent"
                           + (f", top bid {profile.max_bid}" if profile.max_bid is not None else "")
                           + "."),
                "evidence": f"{profile.aggression_evidence()}, same owner",
            })
        hist_calls: list[StartSitCall] = []
        for team_week in history.team_weeks():
            if team_week.roster_id == hist_roster_id:
                hist_calls.extend(
                    calls_for_team_week(history, team_week, history_model, players))
        if hist_calls:
            left = sum(c.manager_points_left_on_bench for c in hist_calls)
            items.append({
                "title": "Points they leave on the bench",
                "detail": f"{left:.0f} points left on the bench across "
                          f"{len(hist_calls)} graded start/sit chances last season.",
                "evidence": f"{history.season} league log, "
                            f"weeks {min(history.graded_weeks)}-{max(history.graded_weeks)}"
                            ", same owner",
            })
    return items[:4]


def late_news(my_picks: list[SlotPick], players: PlayerIndex,
              availability: WeekAvailability | None = None,
              ) -> list[tuple[str, SlotPick, bool]]:
    """The players whose Sunday news decides a slot: (name, pick, is_starter).

    Two kinds. A QUESTIONABLE starter, whose alternative steps in if he is
    ruled out. And — new, and the one the product used to miss — a
    QUESTIONABLE bench player whose doubt is the reason a slot carries no
    number: on the Tuesday information set he is the single most consequential
    piece of late news on the roster, and the report named him nowhere. Found
    on the real 2024 week-10 sample, where Tony Pollard's week-9 designation
    gated three slots and the pivot plan read "no starter is listed
    questionable". One bench player can gate several slots; he is named once,
    at the slot he comes closest to taking.
    """
    out: list[tuple[str, SlotPick, bool]] = []
    for pick in my_picks:
        if pick.status and pick.status.status is Status.QUESTIONABLE and pick.player_id:
            out.append((players.name(pick.player_id), pick, True))
    if availability is None:
        return out
    closest: dict[str, SlotPick] = {}
    for pick in my_picks:
        alt = pick.alternative_id
        if not alt or pick.confidence is not None or pick.projection is None:
            continue
        if availability.classify(alt).status is not Status.QUESTIONABLE:
            continue
        if any(name == players.name(alt) for name, _, _ in out):
            continue
        held = closest.get(alt)
        gap = pick.projection.mean - (pick.alternative_projection.mean
                                      if pick.alternative_projection else 0.0)
        held_gap = (held.projection.mean - (held.alternative_projection.mean
                                            if held.alternative_projection else 0.0)
                    if held and held.projection else None)
        if held is None or held_gap is None or gap < held_gap:
            closest[alt] = pick
    for alt, pick in closest.items():
        out.append((players.name(alt), pick, False))
    return out


def pivots(
    my_picks: list[SlotPick], rival_picks: list[SlotPick], players: PlayerIndex,
    availability: WeekAvailability | None = None,
) -> list[dict[str, str]]:
    """If/then plan for late news, from questionable statuses + alternatives."""
    plans: list[dict[str, str]] = []
    for name, pick, is_starter in late_news(my_picks, players, availability):
        if is_starter and pick.alternative_id:
            plans.append({
                "condition": f"{name} ({pick.slot}) is ruled out",
                "action": f"Move {players.name(pick.alternative_id)} into {pick.slot}"
                          + (f" (projects {pick.alternative_projection.mean:.1f})"
                             if pick.alternative_projection else ""),
            })
        elif not is_starter and pick.player_id and pick.projection:
            starter = players.name(pick.player_id)
            alt_proj = (f"{pick.alternative_projection.mean:.1f}"
                        if pick.alternative_projection else "—")
            plans.append({
                "condition": f"{name} (bench) is cleared to play",
                "action": f"Look again at {pick.slot}: he projects {alt_proj} against "
                          f"{starter}'s {pick.projection.mean:.1f}, and that slot has "
                          f"no number until his status is known",
            })
    for pick in rival_picks:
        if pick.status and pick.status.status is Status.QUESTIONABLE:
            plans.append({
                "condition": f"Rival's {players.name(pick.player_id or '')} "
                             f"({pick.slot}) is ruled out",
                "action": "Their projected total drops — say nothing in the group "
                          "chat until their lineup locks.",
            })
    return plans[:3]


def _season_record(season: Season, roster_id: int, before_week: int) -> tuple[int, int, int]:
    """(wins, losses, ties) from decided matchups before ``before_week``.
    A 0.0-0.0 pairing is an unplayed week, not a tie (matchup RULE M1)."""
    wins = losses = ties = 0
    for week in season.graded_weeks:
        if week >= before_week:
            continue
        team_week = season.weeks[week].get(roster_id)
        if team_week is None or team_week.matchup_id is None:
            continue
        opponent = next(
            (tw for rid, tw in season.weeks[week].items()
             if rid != roster_id and tw.matchup_id == team_week.matchup_id), None)
        if opponent is None or (team_week.points == 0.0 and opponent.points == 0.0):
            continue
        if team_week.points > opponent.points:
            wins += 1
        elif team_week.points < opponent.points:
            losses += 1
        else:
            ties += 1
    return wins, losses, ties


def _roster_for_owner(season: Season, owner_id: str | None,
                      roster_fallback: int | None) -> int | None:
    """Owner-first lookup (owners keep identity across seasons; rosters don't)."""
    if owner_id:
        for rid, team in season.teams.items():
            if team.owner_id == owner_id:
                return rid
    if roster_fallback is not None and roster_fallback in season.teams:
        return roster_fallback
    return None


def rival_watch(
    seasons: list[Season],
    week: int,
    my_roster_id: int,
    scheduled_roster_id: int,
    named_owner_id: str | None,
    named_roster_fallback: int | None,
    players: PlayerIndex,
    model: ProjectionModel,
    availability: WeekAvailability,
) -> dict[str, Any] | None:
    """The named rival's weekly strip — rendered even in weeks you don't play
    them. Returns None when no named rival is configured."""
    if named_owner_id is None and named_roster_fallback is None:
        return None
    season = seasons[0]
    named_roster = _roster_for_owner(season, named_owner_id, named_roster_fallback)
    if named_roster is None:
        return {"gate": "your named rival has no roster in this season's league "
                        "(owner left or changed?) — re-pick a rival"}
    label = season.team_label(named_roster)
    rivalry_week = named_roster == scheduled_roster_id

    wins, losses, ties = _season_record(season, named_roster, week)
    record = f"{wins}-{losses}" + (f"-{ties}" if ties else "")

    # All-time head-to-head, owner-keyed across every cached season.
    my_owner = season.teams.get(my_roster_id).owner_id if season.teams.get(my_roster_id) else None
    h2h_wins = h2h_losses = 0
    seasons_counted: list[str] = []
    for past in seasons:
        mine_rid = _roster_for_owner(past, my_owner, my_roster_id if past is season else None)
        theirs_rid = _roster_for_owner(past, named_owner_id,
                                       named_roster if past is season else None)
        if mine_rid is None or theirs_rid is None:
            continue
        counted = False
        for past_week in past.graded_weeks:
            if past is season and past_week >= week:
                continue
            mine_tw = past.weeks[past_week].get(mine_rid)
            theirs_tw = past.weeks[past_week].get(theirs_rid)
            if (mine_tw is None or theirs_tw is None
                    or mine_tw.matchup_id is None
                    or mine_tw.matchup_id != theirs_tw.matchup_id):
                continue
            if mine_tw.points == 0.0 and theirs_tw.points == 0.0:
                continue
            counted = True
            if mine_tw.points > theirs_tw.points:
                h2h_wins += 1
            elif mine_tw.points < theirs_tw.points:
                h2h_losses += 1
        if counted:
            seasons_counted.append(past.season)

    watch: dict[str, Any] = {
        "label": label,
        "roster_id": named_roster,
        "rivalry_week": rivalry_week,
        "their_record": record,
        "record_evidence": f"{season.season} weeks 1-{week - 1}" if week > 1 else "season start",
        "head_to_head": {
            "wins": h2h_wins, "losses": h2h_losses,
            "evidence": (f"cached matchups, seasons {', '.join(seasons_counted)}"
                         if seasons_counted else "no head-to-head matchups in cache"),
        },
    }
    if rivalry_week:
        return watch

    # Their week, briefly: opponent + fragile spots (same detector the main
    # rival grid uses, run against the named rival's set lineup).
    their_tw = season.weeks.get(week, {}).get(named_roster)
    if their_tw is not None and their_tw.matchup_id is not None:
        their_opponent = next(
            (season.team_label(rid) for rid, tw in season.weeks[week].items()
             if rid != named_roster and tw.matchup_id == their_tw.matchup_id), None)
        watch["their_opponent"] = their_opponent
        their_picks = rival_lineup(season, their_tw, model, players, availability,
                                   week)
        fragile = [f for p in their_picks for f in p.flags]
        watch["fragile_spots"] = len(fragile)
        watch["top_fragility"] = fragile[0]["text"] if fragile else None
    return watch


def _stakes_clause(stakes: Mapping[str, Any] | None) -> str:
    """What the swaps are worth, and — when it is true — that the lineup as it
    stands is losing. The report used to say the optimal lineup wins by 5.3 and
    never that doing nothing loses by 3.1, which is the fact that makes the
    section urgent rather than informational. Both totals must be honest or
    neither is quoted (a partial sum is a fabricated total)."""
    if not stakes:
        return ""
    swap = stakes.get("swap_value")
    if swap is None or swap <= 0:
        return ""
    return f" worth +{swap:.1f}"


def _behind_sentence(stakes: Mapping[str, Any] | None) -> str:
    """Stated only when the set lineup is actually losing — the whole force of
    it is that it is true this week, so it must never become boilerplate."""
    if not stakes:
        return ""
    as_set, theirs = stakes.get("as_set_total"), stakes.get("rival_total")
    if as_set is None or theirs is None or as_set >= theirs:
        return ""
    return (f" As it stands you project {as_set:.1f} against their "
            f"{theirs:.1f}.")


def checklist(
    my_picks: list[SlotPick],
    current_starters: tuple[str, ...] | None,
    hype: list[dict[str, Any]],
    players: PlayerIndex,
    stakes: Mapping[str, Any] | None = None,
    availability: WeekAvailability | None = None,
    early_calls: bool = False,
) -> list[dict[str, str]]:
    seated = [p for p in my_picks if p.player_id is not None]
    items: list[dict[str, str]] = []
    if current_starters is None:
        # We do not read the subscriber's league (PLAN §0), so we have never
        # seen the lineup they set. "Nothing to change" would be a claim about
        # a lineup we cannot see — the same fabricated endorsement the week-1
        # branch below exists to avoid. State the lineup instead of comparing
        # to one.
        if not seated or not any(p.projection for p in seated):
            # State the BASIS, not just the absence. The slots are filled, so a
            # reader who is told only "this is not a recommendation" is left to
            # guess why these players are in them — and the honest answer is
            # concrete: they are ordered on last season's per-game scoring,
            # which is a record of what happened rather than a claim about this
            # week. Each row carries its own figure so the order can be checked.
            items.append({
                "action": "No start-sit calls yet — nobody has played a game "
                          "this season, so there is nothing to project from. "
                          "Your slots are filled in last season's scoring order, "
                          "shown on each line. That's a record of what happened, "
                          "not a forecast for this week. "
                          + ("Projections and the number on each call start "
                             "next week — leaning on last season at first, and "
                             "saying so on each row."
                             if early_calls else
                             "Projections start next week; the number on each "
                             "call starts in Week 4, once both players in it "
                             "have three games of record."),
                "deadline": "calls start once there is a record",
                "urgency": "done",
            })
        else:
            listed = ", ".join(f"{players.name(p.player_id or '')} at {p.slot}"
                               for p in seated)
            items.append({
                "action": f"Set this lineup{_stakes_clause(stakes)}: {listed}."
                          f"{_behind_sentence(stakes)}",
                "deadline": "before this week's first kickoff",
                "urgency": "now",
            })
        # A slot nobody can fill is the most actionable thing in the report and
        # used to be silent: the lineup simply rendered "(empty)" and the
        # checklist said nothing, so a subscriber with no kicker rostered would
        # start the week a slot short without being told.
        unfillable = [p.slot for p in my_picks if p.player_id is None]
        if unfillable:
            spots = ", ".join(sorted(set(unfillable)))
            items.append({
                "action": f"You have nobody to start at {spots}. Add someone "
                          f"off waivers, or that slot scores zero.",
                "deadline": "before this week's first kickoff",
                "urgency": "now",
            })
        # The late-news item used to live only below this return, so the solo
        # product — the one that ships — never printed it, while the landing
        # page promised "the one player whose news you need to check".
        items.extend(_late_news_item(my_picks, players, availability))
        return items

    changes = [
        p for p in my_picks
        if p.player_id is not None
        and p.slot_index < len(current_starters)
        and current_starters[p.slot_index] != p.player_id
    ]
    if changes:
        detail = ", ".join(
            f"{players.name(p.player_id or '')} into {p.slot}" for p in changes
        )
        items.append({
            # No §-references in action items: they read as legalese, and they
            # dangle entirely in the plain-text email that has no sections.
            "action": f"Set your lineup — {len(changes)} change"
                      f"{'s' if len(changes) != 1 else ''}"
                      f"{_stakes_clause(stakes)}: {detail}."
                      f"{_behind_sentence(stakes)}",
            "deadline": "before this week's first kickoff",
            "urgency": "now",
        })
    elif not any(p.projection for p in my_picks):
        # "We agree with your lineup" and "we have nothing to compare it to"
        # are different sentences. In week 1 the optimal lineup is empty
        # because no games exist to project from, so `changes` is empty too —
        # and claiming agreement there is a fabricated endorsement from a
        # model holding no opinion (principle 3).
        items.append({
            "action": "No lineup call yet — your league's first box scores land "
                      "this weekend, and we don't compare lineups without a "
                      "record to compare against. Your lineup is untouched.",
            "deadline": "calls start next week",
            "urgency": "done",
        })
    else:
        items.append({
            "action": "Nothing to change — the lineup you've set is the one we'd set.",
            "deadline": "checked today",
            "urgency": "done",
        })
    if hype:
        top = hype[0]
        # The checklist is for someone who reads nothing else, so it carries the
        # verdict rather than handing back the question. Every number here is
        # already computed and already shown in the waiver section below.
        who = f"{top['player_name']} ({top['position']})"
        bid, left = top.get("bid_to_beat"), top.get("my_remaining")
        if bid and top.get("affordable") is False and left is not None:
            action = (f"Skip {who} — it takes {bid} to top the highest bid he's drawn "
                      f"and you have {left} left. Save it for one you can land.")
        elif bid:
            # No "who else can cover" here: that sentence lives in the waiver
            # section, and keeping a second copy is what let the two drift.
            action = f"Bid {bid} or more on {who}."
        else:
            action = (f"Decide on {who} — {top['managers_chasing']} managers chasing, "
                      f"top bid {top['top_bid'] if top['top_bid'] is not None else '—'}.")
        items.append({
            "action": action,
            "deadline": "before waivers clear (league waiver day)",
            "urgency": "deadline",
        })
    items.extend(_late_news_item(my_picks, players, availability))
    return items


def _late_news_item(my_picks: list[SlotPick], players: PlayerIndex,
                    availability: WeekAvailability | None) -> list[dict[str, str]]:
    watch = late_news(my_picks, players, availability)
    if not watch:
        return []
    names = ", ".join(name for name, _, _ in watch)
    return [{
        "action": f"Check late news on: {names} — your pivot plan below covers "
                  f"both outcomes.",
        "deadline": "gameday morning",
        "urgency": "deadline",
    }]


# --------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------- #

def _slot_json(pick: SlotPick, players: PlayerIndex) -> dict[str, Any]:
    projection = pick.projection
    return {
        "slot": pick.slot,
        "player_id": pick.player_id,
        "player_name": players.name(pick.player_id) if pick.player_id else None,
        "position": players.position(pick.player_id) if pick.player_id else None,
        "projected": round(projection.mean, 1) if projection else None,
        "form_games": projection.games if projection else None,
        "appear_probability": round(projection.appear_probability, 2) if projection else None,
        "confidence": round(pick.confidence, 3) if pick.confidence is not None else None,
        "confidence_gate": pick.confidence_gate,
        "alternative_id": pick.alternative_id,
        "alternative_name": players.name(pick.alternative_id) if pick.alternative_id else None,
        "alternative_projected": (round(pick.alternative_projection.mean, 1)
                                  if pick.alternative_projection else None),
        "edge": (round(projection.mean - pick.alternative_projection.mean, 1)
                 if projection and pick.alternative_projection else None),
        "status": pick.status.status.value if pick.status else None,
        "status_reason": pick.status.reason if pick.status else None,
        "flags": pick.flags,
    }


def current_nfl_season(raw_dir: Path) -> str | None:
    """The season Sleeper says we are in, or None if state isn't cached."""
    state_path = raw_dir / "state" / "nfl.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    season = state.get("league_season") or state.get("season")
    return season if isinstance(season, str) and re.fullmatch(r"\d{4}", season) else None


def build_week_report(
    raw_dir: Path, league_id: str, week: int, my_roster_id: int,
    named_rival_owner_id: str | None = None,
    named_rival_roster_id: int | None = None,
    require_season: str | None = None,
) -> dict[str, Any]:
    seasons = load_season_chain(raw_dir, league_id, max_seasons=2)
    season = seasons[0]
    if not re.fullmatch(r"\d{4}", season.season):
        # The season string flows into report filenames; API data is untrusted.
        raise WeekReportError(
            f"league {league_id} reports season {season.season!r}, "
            "which is not a plausible year")
    # Principle 3, the quietest way to break it: Sleeper mints a NEW league id
    # every season and the old one keeps resolving forever, with a completed
    # season that our cache never expires. A subscriber whose registry entry
    # still carries last year's league id would therefore get a complete,
    # confident report about games played twelve months ago — no gap, no
    # warning, exit code 0. Callers that MAIL people pass require_season so
    # that failure is loud; historical and demo renders leave it unset.
    if require_season is not None and season.season != require_season:
        raise WeekReportError(
            f"league {league_id} is season {season.season}, but the current NFL "
            f"season is {require_season}. Sleeper issues a new league id each "
            "season, so this entry is pointing at last season's league and would "
            "produce a confident report about games that are already over. "
            "Re-resolve the league id from the owner's Sleeper user before "
            "sending anything.")
    history = seasons[1] if len(seasons) > 1 else None
    players = load_players(raw_dir)
    model = ProjectionModel(season, players)
    history_model = ProjectionModel(history, players) if history else None

    week_data = season.weeks.get(week)
    if not week_data:
        cached = ", ".join(map(str, season.graded_weeks)) or "none"
        raise WeekReportError(
            f"week {week} of season {season.season} is not in the cache "
            f"(cached weeks: {cached}) — run `python -m ingest.pull` first")
    mine = week_data.get(my_roster_id)
    if mine is None:
        raise WeekReportError(
            f"roster {my_roster_id} has no week-{week} matchup record; "
            f"rosters this week: {sorted(week_data)}")
    if mine.matchup_id is None:
        raise WeekReportError(
            f"roster {my_roster_id} has no opponent in week {week} (bye or "
            "unscheduled) — no rival report to build")
    rival = next(
        (tw for rid, tw in week_data.items()
         if rid != my_roster_id and tw.matchup_id == mine.matchup_id),
        None,
    )
    if rival is None:
        raise WeekReportError(
            f"no opponent shares matchup_id {mine.matchup_id} in week {week}")

    availability = load_week_availability(raw_dir, season.season, week)
    my_picks = optimal_lineup(season, mine, model, players, availability, week)
    rival_picks = rival_lineup(season, rival, model, players, availability, week)

    prob, prob_gate = win_probability(my_picks, rival_picks)
    hype = hype_meter(season, week, players, season.waiver_budget)
    market = build_waiver_market(season, week)
    waiver_market = market_json(market, my_roster_id, rival.roster_id,
                                season.team_label(rival.roster_id))
    # Turn each chase into a decision. The threshold must come from what THIS
    # player has actually drawn — using the league-wide max appetite would tell
    # someone to spend 38 on a player nobody has valued above 17. The league's
    # top appetite is reported separately, as the worst case if a rival really
    # wants him, and everything is checked against what the reader can afford.
    my_left = waiver_market.get("my_remaining")
    for entry in hype:
        observed = entry.get("top_bid") or market.going_rate
        if not observed:
            continue
        entry["bid_to_beat"] = observed + 1
        entry["rivals_who_can_pay"] = market.rivals_who_can_pay(
            entry["bid_to_beat"], exclude=my_roster_id)
        entry["league_top_appetite"] = market.bid_to_beat(my_roster_id)
        entry["affordable"] = my_left is None or entry["bid_to_beat"] <= my_left
        entry["my_remaining"] = my_left
        # A bare count has no scale. "8 teams" means nothing; "8 of the other
        # 11" is a reason to act. League size is already known here.
        entry["league_others"] = max(len(season.teams) - 1, 0)
        # What the league is chasing him FOR. Counted, never projected
        # (engine/usage.py RULE U1), and strictly from weeks before this one.
        usage = recent_usage(raw_dir, entry["player_id"], season.season, week)
        line = usage_line(usage)
        if line:
            entry["usage"] = line
    # Close out the week just gone. Retrospective and factual, so it carries no
    # calibration burden — and it is the part of the fantasy week a manager
    # actually feels, which the report skipped entirely.
    last = None
    if week > 1:
        prior = [t for t in season.team_weeks() if t.week == week - 1]
        mine_prior = next((t for t in prior if t.roster_id == my_roster_id), None)
        opp_prior = next((t for t in prior
                          if mine_prior is not None
                          and t.roster_id != my_roster_id
                          and t.matchup_id == mine_prior.matchup_id), None)
        if mine_prior is not None and opp_prior is not None:
            summary = last_week_summary(
                season, mine_prior, opp_prior,
                season.team_label(opp_prior.roster_id), players)
            if summary is not None:
                last = {
                    "week": summary.week,
                    "headline": last_week_headline(summary),
                    "points": summary.points,
                    "opponent_points": summary.opponent_points,
                    "opponent_label": summary.opponent_label,
                    "best_possible": summary.best_possible,
                    "left_on_bench": summary.left_on_bench,
                    "won": summary.won,
                    "winnable": summary.winnable,
                }
    watch = rival_watch(seasons, week, my_roster_id, rival.roster_id,
                        named_rival_owner_id, named_rival_roster_id,
                        players, model, availability)

    gaps: list[dict[str, str]] = []
    if not availability.has_snapshot:
        gaps.append({
            "field": "availability",
            "reason": f"no snapshot exists for {season.season} week {week}; "
                      "statuses UNKNOWN, so no confidence numbers print "
                      "(snapshots accumulate from Aug 2026 onward)",
        })
    if availability.bye_teams is None:
        gaps.append({"field": "bye_weeks",
                     "reason": f"NFL schedule unavailable for {season.season} "
                               f"week {week} (not cached, unreadable, or week "
                               "absent from the feed) — bye status unknowable, "
                               "so ACTIVE cannot be concluded for anyone"})
    if prob_gate:
        gaps.append({"field": "win_probability", "reason": prob_gate})
    my_range = _team_range(my_picks)
    rival_range = _team_range(rival_picks)
    # What the lineup they have SET projects, under the identical gate.
    as_set_range = _team_range(
        rival_lineup(season, mine, model, players, availability, week))
    if my_range is None or rival_range is None:
        gaps.append({"field": "team_ranges", "reason": TEAM_RANGE_GATE})
    # Operator-facing note only. Deliberately NOT rendered to buyers: an empty
    # betting-market section on a product that promises "no picks" advertises a
    # missing feature and drags the brand toward the sportsbook framing we sell
    # against (principle 4).
    gaps.append({"field": "market_context",
                 "reason": "betting-market context not ingested; not shown to buyers"})

    report = {
        "meta": {
            "league_id": season.league_id,
            "league_name": season.name,
            "season": season.season,
            "week": week,
            "scoring": "Full PPR" if season.scoring_settings.get("rec") == 1 else None,
            "num_teams": len(season.teams),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "my_roster_id": my_roster_id,
            "my_label": season.team_label(my_roster_id),
            "rival_roster_id": rival.roster_id,
            "rival_label": season.team_label(rival.roster_id),
            "named_rival_label": (watch or {}).get("label"),
            "rivalry_week": bool((watch or {}).get("rivalry_week")),
            "availability_as_of": availability.snapshot_as_of,
            "historical_demo": season.status == "complete",
            # True when the model held no opinion and the grid shows the
            # lineup exactly as the subscriber set it (week 1). The renderer
            # switches the section title so "optimal" is never claimed for a
            # lineup nobody optimized.
            "lineup_as_set": (any(p.player_id for p in my_picks)
                              and all(p.projection is None for p in my_picks)),
            "gaps": gaps,
            "llm_tokens": 0,
        },
        "checklist": checklist(
            my_picks, mine.starters, hype, players,
            stakes=({"swap_value": round(my_range["projected_total"]
                                         - as_set_range["projected_total"], 1),
                     "as_set_total": as_set_range["projected_total"],
                     "rival_total": rival_range["projected_total"]}
                    if my_range and as_set_range and rival_range else None)),
        "matchup": {
            # A side without an honest total carries label only — the renderer
            # and the text summary print the gate reason instead of a number.
            "you": {"label": season.team_label(my_roster_id), **(my_range or {})},
            "rival": {"label": season.team_label(rival.roster_id),
                      **(rival_range or {})},
            # The gap between the two totals, and — inseparably — how wide the
            # week actually swings. Publishing the gap alone would republish the
            # numerator of a quantity we deliberately gate (win probability)
            # with its uncertainty stripped off. Independent teams, so the
            # variances add: swing = z * sqrt(sd_you^2 + sd_rival^2). On the
            # sample week the gap is 5.3 and the swing is 53 — a tenth of it.
            # What doing nothing costs. Published only when BOTH totals are
            # honest — a sum over eight of nine starters in scoreboard font is
            # a fabricated number, and it would understate the swap value.
            **({"as_set_total": as_set_range["projected_total"],
                "swap_value": round(my_range["projected_total"]
                                    - as_set_range["projected_total"], 1)}
               if my_range and as_set_range else {}),
            **({"margin": round(my_range["projected_total"]
                                - rival_range["projected_total"], 1),
                "margin_swing": round(
                    Z_80_BAND * ((my_range["sd"] ** 2
                                  + rival_range["sd"] ** 2) ** 0.5))}
               if my_range and rival_range else {}),
            "win_probability": round(prob, 3) if prob is not None else None,
            "win_probability_gate": prob_gate,
            "range_basis": TEAM_RANGE_BASIS,
            "range_gate": (None if my_range and rival_range else TEAM_RANGE_GATE),
        },
        "last_week": last,
        "rival_watch": watch,
        "lineup": [_slot_json(p, players) for p in my_picks],
        "rival_lineup": [_slot_json(p, players) for p in rival_picks],
        "fragility": fragility(season, history, rival_picks, rival.roster_id,
                               players, history_model, raw_dir, week),
        "regret": regret_call(my_picks, players, raw_dir, season.season, week),
        "pivots": pivots(my_picks, rival_picks, players),
        "hype": hype,
        "waiver_market": waiver_market,
        "receipts": receipts(season, week, model, players, my_roster_id, raw_dir),
    }
    return report


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    # --league is REQUIRED rather than resolved from CLAUDE.md. That fallback
    # was the only line in this module that reached ingest.config, and through
    # it ingest.sleeper — which put a Sleeper client in the import graph of
    # every module that reads a cached report, including the roster runner whose
    # whole claim is that no league platform is involved. Nothing here fetches;
    # build_week_report reads a cache. The one caller (`make demo`) already
    # passes the league explicitly.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True,
                        help="the cached league id to build from")
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--roster", type=int, required=True,
                        help="my roster_id in the league")
    parser.add_argument("--rival-owner", help="named rival's Sleeper user id")
    parser.add_argument("--rival-roster", type=int,
                        help="named rival's roster id (owner id preferred)")
    parser.add_argument("--output", type=Path,
                        default=PROCESSED_DIR / "week_report.json")
    args = parser.parse_args(argv)

    league_id = args.league
    try:
        report = build_week_report(RAW_DIR, league_id, args.week, args.roster,
                                   named_rival_owner_id=args.rival_owner,
                                   named_rival_roster_id=args.rival_roster)
    except (WeekReportError, HistoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=1), encoding="utf-8")
    meta = report["meta"]
    print(f"week_report.json written to {args.output}")
    print(f"  {meta['my_label']} vs {meta['rival_label']} — "
          f"{meta['league_name']} {meta['season']} week {meta['week']}")
    print(f"  publishable confidences: "
          f"{sum(1 for s in report['lineup'] if s['confidence'] is not None)}"
          f"/{len(report['lineup'])} slots; gaps: {len(meta['gaps'])}")
    print("  LLM tokens: 0 (deterministic layer)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
