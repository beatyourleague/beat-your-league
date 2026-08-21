"""The week report for a subscriber whose league we never read.

``build_week_report`` needs a whole league: an opponent sharing a matchup id, a
transaction log to price waivers, league-wide adds to rank hype, last week's
scoreboard. None of that exists any more (PLAN §0), so this is a SIBLING
builder rather than a pile of conditionals inside that one — the historical
backtest and the published demo still run through the original path, and
threading "maybe there is no league" through it would put the two products'
failure modes in the same function.

It emits the SAME JSON contract, so both renderers and the ledger keep working.
Sections that cannot be computed are absent, not empty: an empty section renders
as a feature we forgot, while an absent one lets the renderer say nothing.

WHAT SURVIVES, and why each is honest without a league:
- The lineup, with per-slot confidence. Computed from the subscriber's own
  roster and public scoring history.
- The one coin-flip call (the Regret Score's input), same source.
- The if/then pivot plan, which is about players we can see.
- Counted usage — targets, carries, air yards. RULE U1: a count of something
  that already happened carries no calibration burden.
- The receipts ledger. It gets BETTER without a league: calls become
  league-agnostic player calls, so one public record grades every call we make
  and a stranger can check it.

WHAT DIES, and why it is cut rather than gated:
- The opponent, and with it the Tape's right half and every fragility flag.
  RULE B3: we never saw their lineup. A permanently gated section is worse than
  an absent one — CLAUDE.md's own rule is that a stated omission reads as focus
  while a silent one reads as unfinished, so the site says what is missing and
  the report simply does not carry it.
- The waiver market. It was priced from the league's own transaction log, which
  is exactly the data Sleeper's terms cover.
- The hype meter's league-wide chase counts, for the same reason.
- Last week's result and points left on the bench: RULE B3 again.
- Win probability, permanently. The unit is P(your total beats THEIR SET
  lineup); no rival lineup exists to compute it from or to grade it against.

**GRADE C (reports/nflverse-backtest.md).** The confidence numeral prints as a
recorded prediction only. Nothing in this module, and nothing rendered from it,
may imply an accuracy the measurement does not support.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.availability import WeekAvailability
from engine.history import PlayerIndex, Season
from engine.projection import ProjectionModel
from engine.roster import DEFENSE
from engine.subscriber import SUBSCRIBER_ROSTER_ID, RosterSpec
from engine.week_report import (TEAM_RANGE_BASIS, TEAM_RANGE_GATE,
                                WeekReportError, _team_range, checklist,
                                team_range_gate,
                                _slot_json, optimal_lineup, pivots, receipts,
                                regret_call)

# What the report says where an opponent used to be. Stated once, plainly, in
# the buyer's register — not a gate note, because nothing is being withheld.
NO_OPPONENT_NOTE = (
    "This report is about your roster. We don't read your league, so we can't "
    "see who you're playing or what they've started — that's the trade for not "
    "needing your league's permission to exist.")


def build_solo_report(
    spec: RosterSpec,
    season: Season,
    players: PlayerIndex,
    model: ProjectionModel,
    availability: WeekAvailability,
    week: int,
    raw_dir: Path,
    usage_lookup=None,
) -> dict[str, Any]:
    """One subscriber's week, from their roster and public data."""
    if not re.fullmatch(r"\d{4}", str(season.season)):
        raise WeekReportError(
            f"season {season.season!r} is not a plausible year")
    team_week = (season.weeks.get(week - 1) or {}).get(SUBSCRIBER_ROSTER_ID)
    if team_week is None:
        raise WeekReportError(
            f"no roster record before week {week} — nothing to project from")

    picks = optimal_lineup(season, team_week, model, players, availability)
    my_range = _team_range(picks)

    gaps: list[dict[str, str]] = []
    if not availability.has_snapshot:
        gaps.append({"field": "availability",
                     "reason": f"no injury report for {season.season} week "
                               f"{week}; statuses UNKNOWN, so no confidence "
                               "numbers print"})
    if availability.bye_teams is None:
        gaps.append({"field": "bye_weeks",
                     "reason": f"NFL schedule unavailable for {season.season} "
                               f"week {week} — bye status unknowable, so ACTIVE "
                               "cannot be concluded for anyone"})
    if my_range is None:
        gaps.append({"field": "team_ranges", "reason": team_range_gate(picks)})
    # Operator-facing. Recorded so a future session does not mistake the
    # absence for an oversight and try to "restore" a section that cannot exist.
    gaps.append({"field": "opponent",
                 "reason": "the subscriber's league is not read (PLAN §0), so "
                           "no opponent lineup, fragility, waiver market, "
                           "league hype or last-week result is computable"})

    unscoreable = [p.player_id for p in picks
                   if p.player_id and p.player_id.startswith(f"{DEFENSE}-")]
    if unscoreable:
        gaps.append({"field": "team_defense",
                     "reason": "team defenses are not scored yet (points and "
                               "yards allowed are not ingested), so their slot "
                               "carries no projection"})

    report: dict[str, Any] = {
        "meta": {
            "league_id": season.league_id,
            "league_name": season.name,
            "season": season.season,
            "week": week,
            "scoring": _scoring_label(spec.scoring),
            "num_teams": len(season.teams),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "my_roster_id": SUBSCRIBER_ROSTER_ID,
            "my_label": spec.label,
            # No opponent exists. These keys stay present and null so the
            # renderers can branch on them rather than KeyError, and so the
            # shape of a solo report is visibly the same contract.
            "rival_roster_id": None,
            "rival_label": None,
            "named_rival_label": None,
            "rivalry_week": False,
            "availability_as_of": availability.snapshot_as_of,
            "historical_demo": False,
            "solo": True,
            "lineup_as_set": (any(p.player_id for p in picks)
                              and all(p.projection is None for p in picks)),
            "gaps": gaps,
            "llm_tokens": 0,
        },
        # None, not (): we have never seen their lineup, and an empty tuple would
        # read as "they started nobody" and produce a full list of changes — or
        # worse, "nothing to change", which claims agreement with a lineup we
        # cannot see.
        "checklist": checklist(picks, None, [], players, stakes=None),
        "matchup": _matchup(spec, my_range, team_range_gate(picks)),
        "lineup": [_slot(p, players, usage_lookup) for p in picks],
        "regret": regret_call(picks, players),
        # An empty rival list is correct rather than a placeholder: pivots reads
        # only MY picks' questionable statuses and their alternatives, and the
        # rival half was never used for anything the subscriber acts on.
        "pivots": pivots(picks, [], players),
        "receipts": receipts(season, week, model, players,
                             SUBSCRIBER_ROSTER_ID, raw_dir),
        "no_opponent": NO_OPPONENT_NOTE,
    }
    return report


def _scoring_label(scoring: str) -> str:
    return {"ppr": "Full PPR", "half_ppr": "Half PPR",
            "standard": "Standard"}.get(scoring, scoring)


def _matchup(spec: RosterSpec, my_range: Mapping[str, Any] | None,
             gate: str) -> dict[str, Any]:
    """Your week, not a head-to-head.

    Every field that described an opponent is simply absent. The renderer must
    not print a gap note for them: nothing is being withheld pending better
    evidence, the data does not exist and never will under this architecture.
    """
    you: dict[str, Any] = {"label": spec.label}
    if my_range is not None:
        you.update(my_range)
    out: dict[str, Any] = {"you": you}
    if my_range is None:
        out["range_gate"] = gate
    else:
        out["range_basis"] = TEAM_RANGE_BASIS
    return out


def _slot(pick, players: PlayerIndex, usage_lookup) -> dict[str, Any]:
    """One lineup row.

    Delegates to ``_slot_json`` rather than rebuilding the dict: the renderers
    read a dozen keys off this shape and a second implementation would drift
    from the first silently. Writing one by hand is exactly how this function
    first shipped with a `projection.floor` that does not exist.
    """
    row = dict(_slot_json(pick, players))
    if usage_lookup and pick.player_id:
        line = usage_lookup(pick.player_id)
        if line:
            row["usage"] = line
    return row
