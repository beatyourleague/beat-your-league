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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from engine.availability import Status, WeekAvailability
from engine.history import PlayerIndex, Season
from engine.projection import ProjectionModel
from engine.roster import DEFENSE
from engine.subscriber import (SUBSCRIBER_ROSTER_ID, RosterSpec,
                               _team_week)
from engine.ledger import GRADED, ledger_path, load_ledger
from engine.week_report import (TEAM_RANGE_GATE,
                                WeekReportError, _join_words, _team_range,
                                checklist, late_news, team_range_gate,
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
NO_OPPONENT_NOTE = "Every call below is your starter against your own bench."

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
    schedule: Mapping[str, Mapping[str, Any]] | None = None,
    teams: Mapping[str, str] | None = None,
    injury_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One subscriber's week, from their roster and public data.

    ``schedule`` (team -> this week's game), ``teams`` (player -> the team
    whose game his row shows) and ``injury_report`` ({"week": W-1, "listed":
    gsis -> (designation, injury)}, the report the gate reads, in its own
    words) are FACTS the rows print, never model inputs: nothing here moves a
    projection, a confidence or the publish gate. Absent, the rows say less.
    """
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
                                  last_season_ranks, prior_form,
                                  injury_report=injury_report, season=season)
    if all(p.projection is None for p in picks):
        notable = []

    schedule = schedule or {}
    teams = teams or {}

    def game_of(player_id: str | None) -> Mapping[str, Any] | None:
        team = teams.get(player_id or "")
        return schedule.get(team) if team else None

    sunday = _week_sunday(schedule)
    watch_items, watch_plans = cleared_plans(bench, picks, players, game_of,
                                             sunday)
    # Who must be decided before Sunday: every starter, and every bench player
    # whose news could still move a seat (late_news names only those, F4).
    deciding = [p.player_id for p in picks if p.player_id]
    deciding += [pid for _, _, starter, pid in
                 late_news(picks, players, availability) if not starter]
    early_items, early_ids = early_kickoff_items(deciding, players, game_of, sunday)

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
                                         early_calls=early_calls,
                                         extra=early_items + watch_items,
                                         late_news_skip=early_ids),
        "matchup": _matchup(spec, my_range, team_range_gate(picks)),
        "lineup": [_slot(p, players, usage_lookup,
                         game=game_label(game_of(p.player_id)),
                         absent=(absence(p.player_id, availability, injury_report)
                                 if p.player_id else None),
                         questionable=(questionable_note(p.player_id, availability,
                                                         injury_report, season)
                                       if p.player_id else None))
                   for p in picks],
        "bench": bench,
        "regret": regret_call(picks, players),
        # An empty rival list is correct rather than a placeholder: pivots reads
        # only MY picks' questionable statuses and their alternatives, and the
        # rival half was never used for anything the subscriber acts on.
        # A player out on last week's report comes after the questionable ones:
        # three in four of them stay out.
        "pivots": (pivots(picks, [], players, availability) + watch_plans)[:3],
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


def _games_line(values: Sequence[float]) -> str:
    """The same games as one short sentence: "Last three games: 3.5, 16.8, 4.8." """
    shown = ", ".join(f"{v:.1f}" for v in values[-3:])
    label = {1: "His one game", 2: "His two games"}.get(len(values), "Last three games")
    return f"{label}: {shown}."


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
                 *, injury_report: Mapping[str, Any] | None = None,
                 season: Season | None = None,
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
        why = absence(player_id, availability, injury_report) if out else None
        # Out on LAST week's report is not "can't play": about one such player
        # in four plays the next week (launch audit F2). His number stays on
        # the row — the model's own, the one the if/then and Saturday's check
        # weigh him by — because a reader deciding whether to watch him needs
        # it. A bye or a reserve list is certain, and stays a dash.
        may_play = bool(why and why["kind"] == "designation")
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
                          and (not out or may_play) else None),
            "games": [round(v, 1) for v in model.observations(player_id, week)],
            # Week 1's basis, the same one the lineup rows print: before a game
            # is played, last season is WHY a player sits, and "no games yet"
            # alone told a week-1 reader nothing. A record, never a projection.
            "last_season_per_game": (round((prior_form or {})[player_id], 1)
                                     if player_id in (prior_form or {}) else None),
            "last_season_rank": rank_label,
            "out": out,
            "out_reason": status.reason if out else None,
            # What the row says, and why (bye / roster / designation / other).
            "out_kind": why["kind"] if why else None,
            "out_text": why["row"] if why else None,
            "out_sentence": why["sentence"] if why else None,
            "notable": notable,
        })

    # Best first, then the ones the model has nothing on, then by name so a
    # report is byte-identical across runs.
    bench.sort(key=lambda b: (b["projected"] is None, -(b["projected"] or 0.0),
                              b["name"]))

    items: list[dict[str, str]] = []
    # A player out on last week's report is not explained as benched: whether
    # he would start if cleared is the watch line's job (cleared_plans), and
    # "he can't play this week" said of him is the F2 defect itself.
    explained = sorted((b for b in bench if b["notable"]
                        and b.get("out_kind") != "designation"),
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
    # Plain words (owner review, Sep 29 2026): short sentences, one fact
    # each. "Start X over Y" only when that exact pair carries the slot's odds;
    # otherwise the line is "Bench Y" and says who plays instead — the old
    # wording printed "Start Chase Brown over Tony Pollard at FLEX" while the
    # same slot's odds were against Courtland Sutton, two different "over"
    # players for one slot.
    merge_key: dict[int, tuple[str, str]] = {}
    for entry in explained[:MAX_NOTABLE_ITEMS]:
        rank = f"{entry['last_season_rank']} last season."
        doubtful = (availability.classify(entry["player_id"]).status.value
                    == "questionable")
        if entry["out"]:
            # One sentence after the rank, never a parenthetical: the engine's
            # reason already carried its own "(NFL schedule)", so the line read
            # "WR4 last season. (DET on bye (NFL schedule))." (PC-14).
            action = f"Bench {entry['name']} — he can't play this week"
            detail = f"{rank} {entry['out_sentence']}" if entry.get("out_sentence") \
                else rank
        elif not entry["games"]:
            action = f"Bench {entry['name']} — no games this season yet"
            detail = rank
        else:
            instead = _displaced_by(entry["position"], picks, players)
            form = _games_line(entry['games'])
            # Dated, with what happened (F5): "Listed questionable." in the
            # present tense was last week's report, printed about a player who
            # may well have played through it.
            note = (questionable_note(entry["player_id"], availability,
                                      injury_report, season)
                    if doubtful else None)
            listed = (f" {note}." if note
                      else " Questionable on last week's report." if doubtful else "")
            if instead is None:
                action = f"Bench {entry['name']}"
                own = (f" Projects {entry['projected']:.1f}."
                       if entry["projected"] is not None else "")
                detail = f"{rank}{listed} {form}{own}"
            else:
                who, slot, proj, pick = instead
                paired = (getattr(pick, "alternative_id", None) == entry["player_id"]
                          and getattr(pick, "confidence", None) is not None)
                if paired:
                    action = (f"Start {who} over {entry['name']} at {slot} · "
                              f"{round(pick.confidence * 100)}%")
                else:
                    action = f"Bench {entry['name']} — {who} starts at {slot}"
                    merge_key[len(items)] = (who, slot)
                versus = (f" Projects {entry['projected']:.1f}, {who} {proj:.1f}."
                          if entry["projected"] is not None else "")
                detail = f"{entry['name']}: {rank}{listed} {form}{versus}"
        items.append({"action": action, "detail": detail,
                      "deadline": "before this week's first kickoff",
                      "urgency": "now"})
    return bench, _merge_same_starter(items, merge_key, explained)


def _merge_same_starter(items: list[dict[str, str]],
                        merge_key: dict[int, tuple[str, str]],
                        explained: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """One line per starter who keeps his slot over several benched players.

    A live 2026 build printed "Bench Saquon Barkley — Sam LaPorta starts at
    FLEX" and, next line, "Bench Courtland Sutton — Sam LaPorta starts at FLEX"
    (Sep 29 2026). Same decision, twice. They share a line now, each player's
    facts kept in the detail. Lines carrying odds are never merged: each names
    its own head-to-head.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for index, key in merge_key.items():
        groups.setdefault(key, []).append(index)
    out: list[dict[str, str]] = []
    for index, item in enumerate(items):
        key = merge_key.get(index)
        members = groups.get(key, []) if key else []
        if len(members) < 2:
            out.append(item)
            continue
        if index != members[0]:
            continue                      # folded into the first one
        who, slot = key
        names = [explained[i]["name"] for i in members]
        listed = ", ".join(names[:-1]) + " and " + names[-1]
        out.append({**item,
                    "action": f"Bench {listed} — {who} starts at {slot}",
                    "detail": " ".join(items[i]["detail"] for i in members)})
    return out


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


def _slot(pick, players: PlayerIndex, usage_lookup, *,
          game: str | None = None,
          absent: Mapping[str, str] | None = None,
          questionable: str | None = None) -> dict[str, Any]:
    """One lineup row.

    Delegates to ``_slot_json`` rather than rebuilding the dict: the renderers
    read a dozen keys off this shape and a second implementation would drift
    from the first silently. Writing one by hand is exactly how this function
    first shipped with a `projection.floor` that does not exist.

    ``game`` is the row's opponent and kickoff; ``absent`` and ``questionable``
    replace the engine's terse availability flag with the sentence the bench
    rows use. Flags are rebuilt as new dicts — the pick's own list is shared
    with the ledger-facing code and is never edited in place.
    """
    row = dict(_slot_json(pick, players))
    if usage_lookup and pick.player_id:
        line = usage_lookup(pick.player_id)
        if line:
            row["usage"] = line
    if game:
        row["game"] = game
    flags = [dict(f) for f in row.get("flags") or []]
    if absent:
        for flag in flags:
            if flag.get("kind") == "out":
                flag["text"] = absent["flag"]
        if absent["kind"] != "designation":
            # PC-14: a starter who certainly is not playing prints a dash, like
            # the bench rows — "OUT — on bye" beside "8.4" was a number about a
            # game he is not in. (Seated only when nobody eligible was left;
            # the team total is already withheld for the same reason.)
            row["projected"] = None
            row["edge"] = None
    if questionable:
        for flag in flags:
            if flag.get("kind") == "questionable":
                flag["text"] = questionable
    row["flags"] = flags
    return row


# --------------------------------------------------------------------- #
# the facts beside each row: this week's game, last week's report
# --------------------------------------------------------------------- #

def _clock(hhmm: str | None) -> str | None:
    """"20:15" -> "8:15 PM". None for anything that is not a clock time."""
    try:
        hour, minute = (int(part) for part in str(hhmm or "").split(":"))
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _game_day(game: Mapping[str, Any] | None) -> date | None:
    try:
        return date.fromisoformat(str((game or {}).get("day") or ""))
    except ValueError:
        return None


def game_label(game: Mapping[str, Any] | None) -> str | None:
    """"@ DEN · Thu 8:15 PM ET" — opponent and kickoff, as the schedule
    release states them (its gametime is NFL time, i.e. Eastern).

    Launch audit F7 (Oct 2026): no row said who a player faces or when he
    kicks off, so nothing warned that a starter played Thursday night — the
    one game Saturday's final check is too late for. Facts only: the spread
    and total in the same file are never read here (principle 4)."""
    if not game or not game.get("opponent"):
        return None
    where = f"{'vs' if game.get('home') else '@'} {game['opponent']}"
    day = _game_day(game)
    if day is None:
        return where
    clock = _clock(game.get("time"))
    return f"{where} · {day.strftime('%a')}" + (f" {clock} ET" if clock else "")


def _week_sunday(schedule: Mapping[str, Mapping[str, Any]]) -> date | None:
    """The week's Sunday — the day "before Sunday" is measured from. None for a
    week with no Sunday game, in which case nothing is called early."""
    sundays = [day for day in (_game_day(g) for g in schedule.values())
               if day is not None and day.weekday() == 6]
    return min(sundays) if sundays else None


def _deadline(game: Mapping[str, Any] | None) -> str:
    day = _game_day(game)
    return f"before {day.strftime('%A')}'s kickoff" if day else "before his kickoff"


def early_kickoff_items(player_ids: Sequence[str], players: PlayerIndex,
                     game_of: Callable[[str], Mapping[str, Any] | None],
                     sunday: date | None) -> tuple[list[dict[str, str]], set[str]]:
    """(checklist items, the players they name) for games before Sunday.

    "Sunday morning: check his status" is three days late for a Thursday-night
    player, and Saturday's final check runs after his game has locked — so the
    report says so on Tuesday, grouped by kickoff (launch audit F7).

    "Kicks off", not the audit's "locks": "lock" is also betting slang for a
    sure thing, and run/drops.py already bans it from public copy."""
    if sunday is None:
        return [], set()
    groups: dict[tuple[str, str], list[str]] = {}
    for pid in player_ids:
        game = game_of(pid)
        day = _game_day(game)
        if day is None or day >= sunday or pid in {p for g in groups.values() for p in g}:
            continue
        groups.setdefault((day.isoformat(), str(game.get("time") or "")), []).append(pid)
    items: list[dict[str, str]] = []
    for (day_iso, clock), pids in sorted(groups.items()):
        day = date.fromisoformat(day_iso)
        hour = int(clock.split(":")[0]) if _clock(clock) else None
        when = day.strftime("%A") + (" night" if hour is not None and hour >= 17 else "")
        one = len(pids) == 1
        at = f" at {_clock(clock)} ET" if _clock(clock) else ""
        items.append({
            "action": (f"{when}: {_join_words([players.name(p) for p in pids])} "
                       f"{'kicks off' if one else 'kick off'}{at} — check "
                       f"{'his' if one else 'their'} status before then."),
            "deadline": f"before {day.strftime('%A')}'s kickoff",
            "urgency": "deadline",
        })
    return items, {pid for pids in groups.values() for pid in pids}


def absence(player_id: str, availability: WeekAvailability,
            injury_report: Mapping[str, Any] | None = None,
            ) -> dict[str, str] | None:
    """Why a player the gate holds OUT is out, worded for each surface.

    Three different facts behind one status. A bye and a reserve list are
    certain. An Out on LAST week's report is not: about one such player in four
    plays the next week (launch audit F2, Oct 2026), so the "can't play this
    week" every one of them used to read was a confident claim about a report
    not yet published, and it hid the projection and the if/then a subscriber
    needs if he is cleared.

    Read off the record ``classify`` decides from, in the same order, so the
    sentence and the gate cannot disagree. None for anyone not OUT.
    Keys: kind, row (bench column), flag (lineup row), sentence (game plan).
    """
    status = availability.classify(player_id)
    if status.status is not Status.OUT:
        return None
    record = (getattr(availability, "statuses", None) or {}).get(player_id) or {}
    team = record.get("team")
    byes = getattr(availability, "bye_teams", None)
    if team and byes is not None and team in byes:
        return {"kind": "bye", "row": f"{team} on bye this week",
                "flag": f"OUT — {team} on bye this week",
                "sentence": f"{team} is on bye this week."}
    if record and record.get("position") != DEFENSE and (
            not record.get("active") or not team):
        reason = record.get("out_reason") or "not on an NFL roster"
        return {"kind": "roster", "row": reason, "flag": f"OUT — {reason}",
                "sentence": "He was released." if reason == "released"
                            else f"He's {reason}."}
    if record.get("injury_status") and injury_report and injury_report.get("week"):
        reported = int(injury_report["week"])
        word, injury = ((injury_report.get("listed") or {}).get(player_id)
                        or ("out", ""))
        what = (f"{'Doubtful' if word == 'doubtful' else 'Ruled out'} for Week "
                f"{reported}" + (f" ({injury})" if injury else ""))
        text = f"{what} — Week {availability.week} status not announced yet"
        return {"kind": "designation", "row": text, "flag": text,
                "sentence": f"{text}."}
    reason = status.reason or "can't play this week"
    return {"kind": "other", "row": "can't play this week",
            "flag": f"OUT — {reason}",
            "sentence": f"{reason[:1].upper()}{reason[1:]}."}


def questionable_note(player_id: str, availability: WeekAvailability,
                      injury_report: Mapping[str, Any] | None,
                      season: Season | None) -> str | None:
    """"Questionable in Week 5 (foot) — played, 14.6": dated, with what happened.

    Launch audit F5: "designated Questionable" / "Listed questionable" were
    last week's report printed in the present tense, about players who had
    often played through it. The stat row is the fact: a row means he played, and
    his points are scored under the subscriber's own rule, like every other
    figure in the report. None when the report's week is not known."""
    if availability.classify(player_id).status is not Status.QUESTIONABLE:
        return None
    if not injury_report or not injury_report.get("week"):
        return None
    reported = int(injury_report["week"])
    _, injury = ((injury_report.get("listed") or {}).get(player_id)
                 or ("questionable", ""))
    head = f"Questionable in Week {reported}" + (f" ({injury})" if injury else "")
    carrier = ((season.weeks.get(reported) or {}).get(SUBSCRIBER_ROSTER_ID)
               if season is not None else None)
    if carrier is None or player_id not in carrier.players_points:
        return head
    if carrier.did_appear(player_id):
        return f"{head} — played, {carrier.players_points[player_id]:.1f}"
    return f"{head} — didn't play"


def cleared_plans(bench: Sequence[Mapping[str, Any]], picks: Sequence[Any],
                  players: PlayerIndex,
                  game_of: Callable[[str], Mapping[str, Any] | None],
                  sunday: date | None,
                  ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """(game-plan lines, if/then plans) for players out on last week's report
    who would START if cleared (launch audit F2).

    No new number: his figure is the model's own projection (the bench row's,
    the one Saturday's check weighs him by), the starter's is the lineup row's,
    and no percentage is ever attached to him. Only when clearing him changes
    a seat — a watch line for a player who sits either way is a chore (F4).
    The Saturday sentence rides only on a Sunday game: that check runs after
    Friday's final report and before Sunday's kickoffs, and is too early for a
    Monday game's final report and too late for a Thursday game."""
    healthy = [p for p in picks
               if not (p.status and p.status.status is Status.OUT)]
    items: list[dict[str, str]] = []
    plans: list[dict[str, Any]] = []
    for entry in bench:
        if entry.get("out_kind") != "designation" or entry.get("projected") is None:
            continue
        seat = _displaced_by(entry["position"], healthy, players)
        if seat is None:
            continue
        who, slot, theirs, _ = seat
        mine = entry["projected"]
        if round(mine, 1) <= round(theirs, 1):
            continue
        game = game_of(entry["player_id"])
        figures = f"{mine:.1f} vs {theirs:.1f}"
        items.append({
            "action": f"Watch {entry['name']}: if he's cleared, start him at "
                      f"{slot} over {who}",
            "detail": f"{entry['out_text']}. He projects {mine:.1f}, "
                      f"{who} {theirs:.1f}.",
            "deadline": _deadline(game),
            "urgency": "deadline",
        })
        day = _game_day(game)
        plans.append({
            "condition": f"{entry['name']} is cleared",
            "action": f"Start him at {slot} over {who} ({figures})",
            "saturday": bool(day and sunday and day == sunday),
        })
    return items, plans
