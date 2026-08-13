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
from engine.projection import (
    MIN_GAMES_FOR_CALL, Projection, ProjectionModel, probability_outscores,
)

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
WIN_PROBABILITY_GATE = (
    "matchup-level win probability is not yet calibrated — in backtest "
    "(2 seasons, 170 matchups) favorites stated at ~52% won 64.5% of the "
    "time; see the matchup section of reports/backtest.md")
TEAM_RANGE_BASIS = (
    "80% projection band per team; backtested at 77.9% coverage over 340 "
    "team-weeks (2017-2018) — see reports/backtest.md")


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


def optimal_lineup(
    season: Season,
    team_week: TeamWeek,
    model: ProjectionModel,
    players: PlayerIndex,
    availability: WeekAvailability,
) -> list[SlotPick]:
    """Fill the starting slots with the highest-projected available players.

    Assignment is greedy in slot-restrictiveness order (single-position slots
    claim their player before flexes), which is optimal for the common league
    shapes and deterministic everywhere. Players classified OUT are excluded
    unless a slot would otherwise go empty — then the least-bad player is
    seated and flagged, never silently.
    """
    week = team_week.week
    projections = {
        pid: proj
        for pid in team_week.players
        if (proj := model.project(pid, week)) is not None
    }
    statuses = {pid: availability.classify(pid) for pid in team_week.players}

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
            gate = "no available bench alternative at this slot"
        elif (projection.games < MIN_GAMES_FOR_CALL
              or alt_projection.games < MIN_GAMES_FOR_CALL):
            gate = (f"thin evidence ({projection.games} vs "
                    f"{alt_projection.games} prior games; need {MIN_GAMES_FOR_CALL})")
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
) -> list[SlotPick]:
    """The rival's lineup **as currently set**, with fragility flags.

    We render what they have actually done, not what they should do — the
    product's edge is seeing where the set lineup is fragile.
    """
    week = team_week.week
    picks: list[SlotPick] = []
    started = set(team_week.starters)
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

        # The exploitable spot: their own bench has a better-projected option.
        best_alt: Projection | None = None
        best_alt_id: str | None = None
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
            if best_alt is None or alt.mean > best_alt.mean:
                best_alt, best_alt_id = alt, bench_id
        if (projection is not None and best_alt is not None
                and best_alt.mean > projection.mean):
            flags.append({
                "kind": "bench_better",
                "text": (f"their bench {players.name(best_alt_id)} projects higher "
                         f"({best_alt.mean:.1f} vs {projection.mean:.1f})"),
            })
        picks.append(SlotPick(slot, index, pid, projection, status, None, None,
                              best_alt_id, best_alt, flags))
    return picks


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

def _team_range(picks: list[SlotPick]) -> dict[str, float]:
    mean = sum(p.projection.mean for p in picks if p.projection)
    variance = sum(p.projection.sd ** 2 for p in picks if p.projection)
    sd = variance ** 0.5
    return {
        "projected_total": round(mean, 1),
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


def regret_call(picks: list[SlotPick], players: PlayerIndex) -> dict[str, Any]:
    """The week's closest published call — decided, with its drivers."""
    decided = [
        p for p in picks
        if p.confidence is not None and p.alternative_id is not None
    ]
    if not decided:
        gates = [p.confidence_gate for p in picks if p.confidence_gate]
        reason = gates[0] if gates else "no close call this week"
        return {"gate": f"no publishable head-to-head — {reason}"}
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
            {"label": "appear prob", "value": f"{closest.projection.appear_probability:.0%} vs "
                                              f"{closest.alternative_projection.appear_probability:.0%}"},
        ],
        "definition": ("Confidence = probability this start outscores that specific "
                       "bench alternative at this slot, under our model."),
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
            "evidence": f"league transaction log, weeks {min(windows)}-{max(windows)}"
                        if windows else "no transaction data",
            "verdict_gate": ("real-or-mirage verdict needs usage data "
                            "(routes/snaps) — coming in v0.3"),
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
                    "evidence": "availability snapshot"
                                + (f", as of {pick.status.as_of}" if pick.status and pick.status.as_of else ""),
                })

    # One bench player can outproject several starters; that is ONE story,
    # not four repeated lines — group by the benched player.
    beaten_by_alt: dict[str, list[SlotPick]] = {}
    for pick in rival_picks:
        if pick.alternative_id and any(f["kind"] == "bench_better" for f in pick.flags):
            beaten_by_alt.setdefault(pick.alternative_id, []).append(pick)
    for alt_id, beaten in sorted(beaten_by_alt.items(),
                                 key=lambda kv: -len(kv[1])):
        alt_projection = beaten[0].alternative_projection
        if alt_projection is None:
            continue
        starters = ", ".join(
            f"{players.name(p.player_id or '')} at {p.slot} ({p.projection.mean:.1f})"
            for p in beaten if p.projection
        )
        items.append({
            "title": f"{players.name(alt_id)} is sitting on their bench",
            "detail": (f"He projects {alt_projection.mean:.1f} — above "
                       f"{len(beaten)} of their set starters: {starters}."),
            "evidence": f"trailing-form projections before week "
                        f"{alt_projection.as_of_week}, {season.season}",
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


def pivots(
    my_picks: list[SlotPick], rival_picks: list[SlotPick], players: PlayerIndex
) -> list[dict[str, str]]:
    """If/then plan for late news, from questionable statuses + alternatives."""
    plans: list[dict[str, str]] = []
    for pick in my_picks:
        if pick.status and pick.status.status is Status.QUESTIONABLE and pick.alternative_id:
            plans.append({
                "condition": f"{players.name(pick.player_id or '')} "
                             f"({pick.slot}) is ruled out",
                "action": f"Move {players.name(pick.alternative_id)} into {pick.slot}"
                          + (f" (projects {pick.alternative_projection.mean:.1f})"
                             if pick.alternative_projection else ""),
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
        their_picks = rival_lineup(season, their_tw, model, players, availability)
        fragile = [f for p in their_picks for f in p.flags]
        watch["fragile_spots"] = len(fragile)
        watch["top_fragility"] = fragile[0]["text"] if fragile else None
    return watch


def checklist(
    my_picks: list[SlotPick],
    current_starters: tuple[str, ...],
    hype: list[dict[str, Any]],
    players: PlayerIndex,
) -> list[dict[str, str]]:
    changes = [
        p for p in my_picks
        if p.player_id is not None
        and p.slot_index < len(current_starters)
        and current_starters[p.slot_index] != p.player_id
    ]
    items = []
    if changes:
        detail = ", ".join(
            f"{players.name(p.player_id or '')} into {p.slot}" for p in changes
        )
        items.append({
            "action": f"Set the lineup in §3 — {len(changes)} change"
                      f"{'s' if len(changes) != 1 else ''}: {detail}.",
            "deadline": "before this week's first kickoff",
            "urgency": "now",
        })
    else:
        items.append({
            "action": "Your current lineup already matches the engine's optimal — no changes.",
            "deadline": "verified this run",
            "urgency": "done",
        })
    if hype:
        top = hype[0]
        items.append({
            "action": f"Decide on {top['player_name']} ({top['position']}) — "
                      f"{top['managers_chasing']} managers chasing, "
                      f"top bid {top['top_bid'] if top['top_bid'] is not None else '—'}.",
            "deadline": "before waivers clear (league waiver day)",
            "urgency": "deadline",
        })
    watch = [p for p in my_picks
             if p.status and p.status.status is Status.QUESTIONABLE]
    if watch:
        names = ", ".join(players.name(p.player_id or "") for p in watch)
        items.append({
            "action": f"Check late news on: {names} — pivot plan in §6 covers both outcomes.",
            "deadline": "gameday morning",
            "urgency": "deadline",
        })
    return items


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
        "alternative_name": players.name(pick.alternative_id) if pick.alternative_id else None,
        "status": pick.status.status.value if pick.status else None,
        "status_reason": pick.status.reason if pick.status else None,
        "flags": pick.flags,
    }


def build_week_report(
    raw_dir: Path, league_id: str, week: int, my_roster_id: int,
    named_rival_owner_id: str | None = None,
    named_rival_roster_id: int | None = None,
) -> dict[str, Any]:
    seasons = load_season_chain(raw_dir, league_id, max_seasons=2)
    season = seasons[0]
    if not re.fullmatch(r"\d{4}", season.season):
        # The season string flows into report filenames; API data is untrusted.
        raise WeekReportError(
            f"league {league_id} reports season {season.season!r}, "
            "which is not a plausible year")
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
    my_picks = optimal_lineup(season, mine, model, players, availability)
    rival_picks = rival_lineup(season, rival, model, players, availability)

    prob, prob_gate = win_probability(my_picks, rival_picks)
    hype = hype_meter(season, week, players, season.waiver_budget)
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
    gaps.append({"field": "market_context",
                 "reason": "Vegas game totals not ingested — coming in v0.3"})

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
            "gaps": gaps,
            "llm_tokens": 0,
        },
        "checklist": checklist(my_picks, mine.starters, hype, players),
        "matchup": {
            "you": {"label": season.team_label(my_roster_id), **_team_range(my_picks)},
            "rival": {"label": season.team_label(rival.roster_id), **_team_range(rival_picks)},
            "win_probability": round(prob, 3) if prob is not None else None,
            "win_probability_gate": prob_gate,
            "range_basis": TEAM_RANGE_BASIS,
            "market_context_gate": "Vegas game totals not ingested — coming in v0.3",
        },
        "rival_watch": watch,
        "lineup": [_slot_json(p, players) for p in my_picks],
        "rival_lineup": [_slot_json(p, players) for p in rival_picks],
        "fragility": fragility(season, history, rival_picks, rival.roster_id,
                               players, history_model),
        "regret": regret_call(my_picks, players),
        "pivots": pivots(my_picks, rival_picks, players),
        "hype": hype,
        "receipts": receipts(season, week, model, players, my_roster_id, raw_dir),
    }
    return report


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    from ingest.config import resolve_league_id

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", help="Sleeper league ID (overrides CLAUDE.md)")
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--roster", type=int, required=True,
                        help="my roster_id in the league")
    parser.add_argument("--rival-owner", help="named rival's Sleeper user id")
    parser.add_argument("--rival-roster", type=int,
                        help="named rival's roster id (owner id preferred)")
    parser.add_argument("--output", type=Path,
                        default=PROCESSED_DIR / "week_report.json")
    args = parser.parse_args(argv)

    league_id = resolve_league_id(args.league, REPO_ROOT)
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
