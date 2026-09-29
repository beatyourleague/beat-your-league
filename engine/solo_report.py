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
from engine.subscriber import (SUBSCRIBER_ROSTER_ID, RosterSpec,
                               _team_week)
from engine.ledger import GRADED, ledger_path, load_ledger
from engine.week_report import (TEAM_RANGE_GATE,
                                WeekReportError, _team_range, checklist,
                                team_range_gate,
                                _slot_json, optimal_lineup, pivots,
                                regret_call)


# The record section 06 reports on.
#
# It used to call engine.week_report.receipts(), which reconstructs calls from
# the SEASON'S OWN history for one roster id and decides which were publishable
# by reading availability snapshots out of ``raw_dir``. Both halves are wrong
# here: the solo product has no season history for a roster somebody typed in
# last week, and the snapshot subtree lives under data/raw/availability, which
# only the retired ingest.pull ever wrote — so raw_dir (the nflverse cache) can
# never contain it. has_snapshot was therefore False for every week of every
# season, no call ever qualified, and section 06 read "Ledger opens this week"
# in week 1 and in week 17 alike, forever. Found by running the Tuesday path
# for real (Aug 24 2026); no test caught it because nothing ran it.
#
# The real published record is the LEDGER — written at send time by
# run/tuesday.py, settled by run/monday.py, and published by
# render/ledger_site.py. That is what principle 2 means by "grade everything
# publicly", so that is what this section reports. It reads the store this
# report belongs to (typed-{scoring}-{size}-{season}), which is the cohort
# whose calls were decided under the subscriber's own scoring rule.
#
# GRADED only: a pending call is a claim about a game that has not finished.
def solo_receipts(league_id: str, processed_dir: Path | None) -> dict[str, Any]:
    """Section 06 — what the public record says so far."""
    empty = {"record": None,
             "note": "Your results start here: once this week's games are "
                     "final, every call shows up with how it played out."}
    if processed_dir is None:
        return empty
    try:
        calls = load_ledger(ledger_path(Path(processed_dir), league_id))
    except Exception:
        # A record we cannot read is not a record we may describe. The report
        # still ships; principle 3 forbids inventing the alternative.
        return empty
    graded = [c for c in calls if c.status == GRADED and c.outcome in ("hit", "miss")]
    if not graded:
        return empty
    hits = sum(1 for c in graded if c.outcome == "hit")
    weeks = sorted({c.week for c in graded})
    note = (f"{hits} of {len(graded)} calls have come in right so far, "
            f"weeks {weeks[0]}-{weeks[-1]}, each one written down before kickoff.")
    if len(weeks) == 1:
        note = (f"{hits} of {len(graded)} calls have come in right so far, "
                f"from week {weeks[0]}, each one written down before kickoff.")
    return {"record": {"graded": len(graded), "hits": hits,
                       "first_week": weeks[0], "last_week": weeks[-1]},
            "note": note}

# What the report says where an opponent used to be. Stated once, plainly, in
# the buyer's register — not a gate note, because nothing is being withheld.
NO_OPPONENT_NOTE = (
    "Every call in this file is your player against your own bench — so every "
    "point it finds comes from starting the right guys.")

# The band renders with NO coverage claim. The frozen method (§10.8) gates
# the "about 78%" sentence until the nflverse band table exists: that figure
# was measured on the Sleeper stack over real set lineups, and the solo
# product's totals have never been measured the same way.
SOLO_RANGE_BASIS = ""   # "79 – 144 realistic range" already says it


def build_solo_report(
    spec: RosterSpec,
    season: Season,
    players: PlayerIndex,
    model: ProjectionModel,
    availability: WeekAvailability,
    week: int,
    raw_dir: Path,
    usage_lookup=None,
    prior_form: Mapping[str, float] | None = None,
    early_calls: bool = False,
    processed_dir: Path | None = None,
    last_season_ranks: Mapping[str, tuple[str, int, int]] | None = None,
    calibrate=None,
    confirmed_fallback: bool = False,
) -> dict[str, Any]:
    """One subscriber's week, from their roster and public data."""
    if not re.fullmatch(r"\d{4}", str(season.season)):
        raise WeekReportError(
            f"season {season.season!r} is not a plausible year")
    team_week = (season.weeks.get(week - 1) or {}).get(SUBSCRIBER_ROSTER_ID)
    if team_week is None:
        if season.weeks:
            # A hole mid-season is a real error: weeks exist, and this one does
            # not, which means the ingest is incomplete rather than early.
            raise WeekReportError(
                f"no roster record before week {week} — nothing to project from")
        # WEEK 1. Nothing has been played, so there is no form and no record to
        # be missing — and raising here meant the FIRST report of the season,
        # the one every launch subscriber is waiting for, could not be built at
        # all. optimal_lineup already knows this state: with no projections it
        # renders the lineup exactly as set, and AS_SET_HEAD/AS_SET_BODY are
        # the copy written for it. The roster is real; only the numbers are not
        # there yet, and saying so is the product's own rule.
        team_week = _team_week(SUBSCRIBER_ROSTER_ID, max(week - 1, 0),
                               spec.player_ids, {}, spec.rule)

    # `week`, not team_week.week. team_week is the roster carrier — build_season
    # stops at W-1, so the last TeamWeek it holds is week W-1's — and passing it
    # in as the projection week meant every report projected from weeks 1..W-2,
    # discarding the most recent completed week. Measured across 2019-2024:
    # 14.6% of slots seated a different player, 10.8% of publishable calls were
    # suppressed by keeping players a week short of MIN_GAMES_FOR_CALL, and the
    # matched head-to-heads the correction reorders go 133-100 in its favour
    # (two-sided sign test p = 0.036).
    picks = optimal_lineup(season, team_week, model, players, availability, week,
                           prior_form=prior_form, calibrate=calibrate,
                           confirmed_fallback=confirmed_fallback)
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

    # Defenses ARE scored now (RULE S4: from the team week plus the schedule's
    # own final score). The gap fires on the ones that actually came back with
    # nothing — an expansion-week team, a season not yet ingested — rather than
    # on every defense categorically, which claimed a missing feature the run
    # had in fact just used.
    unscoreable = [p.player_id for p in picks
                   if p.player_id and p.player_id.startswith(f"{DEFENSE}-")
                   and p.projection is None]
    if unscoreable:
        gaps.append({"field": "team_defense",
                     "reason": f"no scored weeks for {', '.join(unscoreable)} "
                               f"before week {week}, so that slot carries no "
                               f"projection"})

    # Every rostered player accounted for. Week 1 has no projections, so the
    # bench is still listed but nothing is explained — a line built on zero
    # games of this season would be a claim with nothing under it.
    bench, notable = bench_report(spec, picks, players, model, availability,
                                  week, len(season.teams) or 12,
                                  last_season_ranks, prior_form)
    if all(p.projection is None for p in picks):
        notable = []

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
        # The counter-intuitive calls lead: a benched starter-calibre player
        # is the one line in the plan a subscriber could not have predicted,
        # and the nine-name lineup below it is the part they could.
        "checklist": notable + checklist(picks, None, [], players, stakes=None,
                                         availability=availability,
                                         early_calls=early_calls),
        "matchup": _matchup(spec, my_range, team_range_gate(picks)),
        "lineup": [_slot(p, players, usage_lookup) for p in picks],
        "bench": bench,
        "regret": regret_call(picks, players),
        # An empty rival list is correct rather than a placeholder: pivots reads
        # only MY picks' questionable statuses and their alternatives, and the
        # rival half was never used for anything the subscriber acts on.
        "pivots": pivots(picks, [], players, availability),
        "receipts": solo_receipts(season.league_id, processed_dir),
        "no_opponent": NO_OPPONENT_NOTE,
    }
    return report


# --------------------------------------------------------------------- #
# the bench — every rostered player is accounted for
# --------------------------------------------------------------------- #

# Positions where benching a known player is a decision a manager agonises
# over. A benched kicker or defense is routine and would only add noise.
NOTABLE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})

# The game plan is thirty seconds. Past three, the counter-intuitive calls
# stop reading as the week's news and start reading as a list — and every one
# of them is still named in the bench block below the lineup.
MAX_NOTABLE_ITEMS = 3


def _starter_depth(position: str, slots: Sequence[str], league_size: int) -> int:
    """How far down a position a player can rank and still be a starter.

    The number of that position a full league starts, from the subscriber's OWN
    slots rather than a constant — so a 3-WR league measures a receiver against
    36 starters and a 1-WR league against 12. Flex slots are left out on purpose:
    counting them would call a WR45 "a starter", and the point of the flag is a
    player the manager would EXPECT to start.
    """
    return sum(1 for slot in slots if slot == position) * league_size


def _games_phrase(values: Sequence[float]) -> str:
    """This season's appearances, as a reader says them."""
    shown = [f"{v:.1f}" for v in values[-3:]]
    body = (shown[0] if len(shown) == 1
            else f"{', '.join(shown[:-1])} and {shown[-1]}")
    if len(values) <= 3:
        count = {1: "one game", 2: "two games", 3: "three games"}[len(values)]
        return f"{body} in his {count}"
    return f"{body} in his last three games"


def _displaced_by(position: str, picks: Sequence[Any],
                  players: PlayerIndex) -> tuple[str, str, float, Any] | None:
    """(name, slot, projection) of the starter who took this player's place.

    The starter at a slot he is eligible for whose projection is LOWEST — the
    one he would replace if he started. Always a fact read off the lineup, so
    the explanation can say who instead of asserting why.
    """
    from engine.history import FLEX_ELIGIBILITY
    candidates = []
    for pick in picks:
        if not getattr(pick, "player_id", None) or pick.projection is None:
            continue
        allowed = FLEX_ELIGIBILITY.get(pick.slot)
        if (position in allowed) if allowed else (pick.slot == position):
            candidates.append((pick.projection.mean, players.name(pick.player_id),
                               pick.slot, pick))
    if not candidates:
        return None
    mean, name, slot, pick = min(candidates, key=lambda c: c[:3])
    return name, slot, round(mean, 1), pick


def bench_report(spec: RosterSpec, picks: Sequence[Any], players: PlayerIndex,
                 model: ProjectionModel, availability: WeekAvailability,
                 week: int, league_size: int,
                 last_season_ranks: Mapping[str, tuple[str, int, int]] | None,
                 prior_form: Mapping[str, float] | None = None,
                 ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """(every bench player, game-plan items for the ones worth explaining).

    **Found by running the live product against real 2026 week-4 data (Sep 29
    2026).** The report names each starter and ONE bench alternative per slot,
    so any other bench player simply vanished. On the sample roster that was
    Saquon Barkley — a first-round pick — mentioned zero times on any surface:
    the file benched him and never said so. A subscriber opens their report,
    looks for their star, finds nothing, and concludes the product is broken.
    And benching a star is the boldest, most shareable call the file makes; it
    was the one call it hid.

    Two rules, and the second is why this adds no ledger obligation:
    - **Every rostered player is named.** Fifteen in, fifteen out.
    - **Only facts explain a surprise.** A benched player who ranked as a
      starter last season gets a game-plan line built from his box scores this
      season, his rank last season (the same `positional_ranks` the roster file
      prints, so the two can never disagree about who was RB14) and the model's
      existing projection. No new probability is published, so nothing here
      needs grading — the confidences on the lineup rows remain the product's
      only graded claims.
    """
    starters = {p.player_id for p in picks if getattr(p, "player_id", None)}
    ranks = last_season_ranks or {}
    bench: list[dict[str, Any]] = []
    for player_id in spec.player_ids:
        if player_id in starters:
            continue
        position = players.position(player_id)
        projection = model.project(player_id, week)
        status = availability.classify(player_id)
        out = status.status.value == "out"
        ranked = ranks.get(player_id)
        rank_label = f"{ranked[0]}{ranked[1]}" if ranked else None
        notable = bool(
            ranked and position in NOTABLE_POSITIONS
            and ranked[1] <= _starter_depth(position, spec.slots, league_size))
        bench.append({
            "player_id": player_id,
            "name": players.name(player_id),
            "position": position,
            # Rounded like every other projection in the report, and None rather
            # than 0.0 when the model has nothing — RULE P1: absent, never zero.
            # None too for a player who CANNOT PLAY: the model's number is form,
            # blind to this week's designation, and "can't play this week" next
            # to "6.4" was the first render of this block (Jayden Reed, 2026 w4).
            "projected": (round(projection.mean, 1)
                          if projection is not None and projection.games
                          and not out else None),
            "games": [round(v, 1) for v in model.observations(player_id, week)],
            # Week 1's basis, the same one the lineup rows print: before a game
            # is played, last season is WHY a player sits, and "no games yet"
            # alone told a week-1 reader nothing. A record, never a projection.
            "last_season_per_game": (round((prior_form or {})[player_id], 1)
                                     if player_id in (prior_form or {}) else None),
            "last_season_rank": rank_label,
            "out": out,
            "out_reason": status.reason if out else None,
            "notable": notable,
        })

    # Best first, then the ones the model has nothing on, then by name so a
    # report is byte-identical across runs.
    bench.sort(key=lambda b: (b["projected"] is None, -(b["projected"] or 0.0),
                              b["name"]))

    items: list[dict[str, str]] = []
    explained = sorted((b for b in bench if b["notable"]),
                       key=lambda b: int(b["last_season_rank"][len(b["position"]):]))
    # ACTION FIRST (owner review, Sep 29 2026). The line used to open with the
    # benched player's stat line and name the start last — "Sitting Sam
    # LaPorta — TE3 last season. This year: 3.5, 16.8 and 4.8 …, projecting
    # 6.5. George Kittle starts at TE instead, at 10.7." — so the one thing to
    # DO was the last clause of a paragraph. Now the bold line is the decision
    # (with the slot's odds when that exact head-to-head carries them) and the
    # facts sit underneath as the reason. Same facts, no new claim: no
    # connective asserts WHY he sits (a "but" once implied form did, when he
    # actually sat on a near-tie).
    for entry in explained[:MAX_NOTABLE_ITEMS]:
        rank = f"{entry['last_season_rank']} last season"
        if entry["out"]:
            reason = f" ({entry['out_reason']})" if entry["out_reason"] else ""
            action = f"Bench {entry['name']} — he can't play this week"
            detail = f"{rank}{reason}."
        elif not entry["games"]:
            action = f"Bench {entry['name']} — no games this season yet"
            detail = f"{rank}."
        else:
            instead = _displaced_by(entry["position"], picks, players)
            form = f"this year {_games_phrase(entry['games'])}"
            if instead is None:
                action = f"Bench {entry['name']}"
                own = (f", projecting {entry['projected']:.1f}"
                       if entry["projected"] is not None else "")
                detail = f"{rank}; {form}{own}."
            else:
                who, slot, proj, pick = instead
                odds = ""
                if (getattr(pick, "alternative_id", None) == entry["player_id"]
                        and getattr(pick, "confidence", None) is not None):
                    odds = f" · {round(pick.confidence * 100)}%"
                action = f"Start {who} over {entry['name']} at {slot}{odds}"
                versus = (f", projecting {entry['projected']:.1f} to {who}'s {proj:.1f}"
                          if entry["projected"] is not None else "")
                detail = f"{entry['name']}: {rank}; {form}{versus}."
        items.append({"action": action, "detail": detail,
                      "deadline": "before this week's first kickoff",
                      "urgency": "now"})
    return bench, items


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
        out["range_basis"] = SOLO_RANGE_BASIS
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
