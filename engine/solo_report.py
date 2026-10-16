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
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from engine.availability import Status, WeekAvailability
from engine.final_check import INACTIVES_LEAD
from engine.history import FLEX_ELIGIBILITY, PlayerIndex, Season
from engine.projection import MIN_GAMES_FOR_CALL, ProjectionModel
from engine.roster import DEFENSE
from engine.subscriber import (SUBSCRIBER_ROSTER_ID, RosterSpec,
                               _team_week)
from engine.ledger import GRADED, ledger_path, load_ledger
from engine.week_report import (SWAP_WORTH_POINTS, TEAM_RANGE_GATE, SlotPick,
                                WeekReportError, _join_words, _ruled_out_last_week,
                                _team_range, checklist, late_news, team_range_gate,
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
    live_teams: Mapping[str, str] | None = None,
    live_out: Mapping[str, str] | None = None,
    unconfirmed: Mapping[str, str] | None = None,
    shape_graded: bool = True,
) -> dict[str, Any]:
    """One subscriber's week, from their roster and public data.

    ``schedule`` (team -> this week's game), ``teams`` (player -> the team
    whose game his row shows) and ``injury_report`` ({"week": W-1, "listed":
    gsis -> (designation, injury)}, the report the gate reads, in its own
    words) are FACTS the rows print, never model inputs: nothing here moves a
    projection, a confidence or the publish gate. Absent, the rows say less.

    ``live_teams`` (player -> TODAY's team) and ``live_out`` (player -> why
    today's release says he can't play), the week being played now only, may
    only REMOVE: such a player loses his seat and any odds he was part of (see
    ``live_availability``), and no odds appear that the frozen gate did not
    already publish (``keep_frozen_odds``). ``unconfirmed`` (player -> why: the
    practice squad, the live week only) keeps his seat and loses any odds he
    is part of (``hold_unconfirmed``, method §15 C9). ``shape_graded`` False
    (a lineup shape no preregistered arm has graded — contract C8) keeps every
    seat and projection and prints no odds (``hold_ungraded_shape``).
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
    def lineup(using: WeekAvailability) -> list[SlotPick]:
        return optimal_lineup(season, team_week, model, players, using, week,
                              prior_form=prior_form, calibrate=calibrate,
                              confirmed_fallback=confirmed_fallback)

    picks = lineup(availability)
    # Today's facts (launch audit R1/R5, Oct 2026). The gate places a player on
    # the team of his last stat row, so a player with no row this season — a
    # released kicker, an injured-reserve tight end — or one traded since, whose
    # CURRENT team is on bye, started unflagged, with another team's game on his
    # row, counted in the total. He is out for the lineup now, so the seat goes
    # to whoever can play; but the odds stay the frozen gate's. Applied at the
    # gate instead, it published nine new percentages across 240 live rosters
    # (a released player had been the bench option blocking a slot's call).
    live = live_availability(availability, live_teams, players, live_out)
    if live is not availability:
        picks = keep_frozen_odds(picks, lineup(live))
        availability = live
    # The practice squad keeps its seats and loses its odds (method §15 C9).
    unconfirmed = dict(unconfirmed or {})
    picks = hold_unconfirmed(picks, unconfirmed, players)
    if not shape_graded:
        picks = hold_ungraded_shape(picks)
    my_range = _team_range(picks)

    # Every rostered player accounted for. Week 1 has no projections, so the
    # bench is still listed but nothing is explained — a line built on zero
    # games of this season would be a claim with nothing under it.
    bench, notable = bench_report(spec, picks, players, model, availability,
                                  week, len(season.teams) or 12,
                                  last_season_ranks, prior_form,
                                  injury_report=injury_report, season=season)
    if all(p.projection is None for p in picks):
        notable = []
    standins = stand_ins(picks, bench)

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
        gaps.append({"field": "team_ranges",
                     "reason": team_range_gate(picks, standins)})
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

    schedule = schedule or {}
    teams = teams or {}

    def game_of(player_id: str | None) -> Mapping[str, Any] | None:
        team = teams.get(player_id or "")
        return schedule.get(team) if team else None

    sunday = _week_sunday(schedule)
    _bench_facts(bench, availability, injury_report, season, unconfirmed, game_of)
    # Every plan below waits for news, and names nobody whose game kicks off
    # before that news is in (launch audit R2/R3, Oct 2026): "move Chase Brown
    # in if Tony Pollard is ruled out" named a Thursday-night back on Sunday
    # news, and "start Breece Hall over RJ Harvey if he's cleared" benched a
    # Thursday starter on Friday's report — a plan nobody can carry out.
    news = late_news(picks, players, availability,
                     seat_ok=lambda bench_id, pick: in_time(
                         game_of(pick.player_id), game_of(bench_id), sunday))
    starter_rows: list[dict[str, Any]] = []
    unplanned: dict[str, str] = {}
    covered: dict[str, Cover] = {}
    for name, pick, is_starter, pid in news:
        if not is_starter:
            continue
        final, late, early = stand_in(pick, spec, picks, players, model,
                                      availability, week, game_of, sunday,
                                      unconfirmed)
        rows = starter_plans(name, pick, final, late,
                             covers(pick, spec, picks, players, model,
                                    availability, week, unconfirmed),
                             players, game_of)
        if rows:
            starter_rows += rows
            if late is not None:          # a fallback even for a game-day call
                covered[pid] = late
        else:
            # Bench players who can play the slot but were ruled out last week
            # are named too (F11), as "unless he's cleared" — or, when his game
            # comes first, among the ones who play too early.
            held = [entry for entry in bench
                    if entry.get("out_kind") == "designation"
                    and _fits(entry.get("position"), pick.slot)]
            on_time = [e["name"] for e in held
                       if in_time(game_of(e["player_id"]), game_of(pid), sunday)]
            unplanned[pid] = no_stand_in_line(
                name, pick.slot,
                [players.name(e) for e in early]
                + [e["name"] for e in held if e["name"] not in on_time],
                on_time)
    watch_items, watch_plans = cleared_plans(bench, picks, players, game_of,
                                             sunday)
    # Starters first, as pivots() always ordered them; then the bench players
    # whose clearance moves a seat, then the ones out last week.
    plans = (starter_rows
             + pivots(picks, [], players, availability,
                      news=[n for n in news if not n[2]], limit=None)
             + watch_plans)
    planned = {plan["about"] for plan in plans if plan.get("about")}
    # Who must be decided before Sunday: every starter who might play, and
    # every bench player whose news could still move a seat (late_news names
    # only those, F4). A starter on bye or a reserve list is not one (R6): "kick
    # off at 8:15 PM ET — check their status" two lines after "aren't playing
    # this week" asked the reader to check on somebody already decided.
    deciding = [p.player_id for p in picks if p.player_id and not _certainly_out(p)]
    deciding += [pid for _, _, starter, pid in news if not starter]
    early_items, early_ids = early_kickoff_items(deciding, players, game_of, sunday)
    # A questionable starter seated level with a healthy bench player says why,
    # on his row and on the game-plan line that benches that player — which
    # read "Bench George Pickens — Zay Flowers starts at WR. … Projects 9.6,
    # Zay Flowers 9.6." with nothing to say why (launch review BE-I9/SS-I7).
    reasons = {p.player_id: even_reason(p, players, availability, game_of, sunday,
                                        covered) for p in picks if p.player_id}
    for item in notable:
        why = reasons.get(item.pop("_starter", None) or "")
        if why:
            item["detail"] = f"{item['detail']} {why}"

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
                                         extra=(early_items + watch_items
                                                + superflex_items(
                                                    picks, players, prior_form,
                                                    last_season_ranks,
                                                    len(season.teams) or 12)),
                                         late_news_skip=early_ids,
                                         news=news, planned=planned,
                                         unplanned=unplanned, standins=standins),
        "matchup": _matchup(spec, my_range, team_range_gate(picks, standins)),
        "lineup": [_slot(p, players, usage_lookup,
                         game=game_label(game_of(p.player_id)),
                         absent=(absence(p.player_id, availability, injury_report)
                                 if p.player_id else None),
                         questionable=(questionable_note(p.player_id, availability,
                                                         injury_report, season)
                                       if p.player_id else None),
                         if_then=bool(p.player_id) and p.player_id in planned,
                         held=bench_option_held(p, bench),
                         model=model, week=week, availability=availability,
                         season_label=str(season.season),
                         reason=reasons.get(p.player_id or ""))
                   for p in picks],
        "bench": bench,
        "regret": closest_call(picks, players, model, week, availability,
                               injury_report, bench),
        "pivots_note": pivots_note(plans, unplanned, availability),
        # An empty rival list is correct rather than a placeholder: pivots reads
        # only MY picks' questionable statuses and their alternatives, and the
        # rival half was never used for anything the subscriber acts on.
        # A player out on last week's report comes after the questionable ones:
        # three in four of them stay out. Uncapped (launch audit R7): every
        # player the game plan names has his plan printed; the old cap of three
        # dropped plans the checklist still promised.
        "pivots": plans,
        "receipts": solo_receipts(season.league_id, processed_dir),
        # "Every call below…" only in a week that has a call (launch review
        # D10): the week-1 sample said it above fifteen empty call cells.
        "no_opponent": (NO_OPPONENT_NOTE
                        if any(p.confidence is not None for p in picks) else None),
    }
    return report


# --------------------------------------------------------------------- #
# today's facts, and who a plan may name
# --------------------------------------------------------------------- #

# The reason a slot prints no odds when today's facts moved its pair: the gate
# never made that call, and a fix that may only remove numbers cannot make it
# now. True whether the starter or the bench option changed.
HELD_GATE = "held: the lineup changed around a player who can't play this week"

# The reason a slot's bench option is no option: he is on the bench, eligible,
# and out (last week's report, a bye, a reserve list). "No bench player at
# that position" was false — the live sample's QB row said it with Lamar
# Jackson on the bench (launch audit F11).
BENCH_HELD_GATE = "bench option not cleared"


def live_availability(availability: WeekAvailability,
                      live_teams: Mapping[str, str] | None,
                      players: PlayerIndex,
                      live_out: Mapping[str, str] | None = None,
                      ) -> WeekAvailability:
    """``availability`` with today's facts applied to the players it missed.

    - A player today's release puts on a reserve list or releases, whom the gate
      could not place on a team (no stat row this season), gets the record a
      placed one gets — no team, not active, the plain reason — which
      ``classify`` reads as OUT ("released", "on injured reserve"). A PLACED
      one the gate still holds active (a status only the report reads: not
      with his team, retired — method §15 C9) is marked out the same way.
    - A player whose CURRENT team is on bye gets that team on his record, which
      ``classify`` reads as OUT — the same sentence any other bye gets.
    Only with a snapshot (without one nobody is ACTIVE anyway, and adding
    records would invent one). Returns the SAME object when nothing changes,
    so callers can tell."""
    if (not live_teams and not live_out) or availability.statuses is None:
        return availability
    byes = availability.bye_teams or frozenset()
    statuses = dict(availability.statuses)
    changed = False
    for pid, reason in (live_out or {}).items():
        record = statuses.get(pid)
        if record is not None and record.get("active") is False:
            continue                     # placed and out: the gate already read it
        statuses[pid] = ({**record, "active": False, "out_reason": reason}
                         if record is not None else
                         {"team": None, "position": players.position(pid),
                          "active": False, "out_reason": reason,
                          "injury_status": None})
        changed = True
    for pid, team in (live_teams or {}).items():
        if team not in byes:
            continue
        record = statuses.get(pid)
        if record is not None and (record.get("team") == team
                                   or record.get("active") is False):
            continue
        updated = dict(record or {"position": players.position(pid), "active": True,
                                  "out_reason": None, "injury_status": None})
        updated["team"] = team
        statuses[pid] = updated
        changed = True
    if not changed:
        return availability
    return WeekAvailability(season=availability.season, week=availability.week,
                            snapshot_as_of=availability.snapshot_as_of,
                            statuses=statuses, bye_teams=availability.bye_teams)


def keep_frozen_odds(frozen: Sequence[SlotPick],
                     moved: Sequence[SlotPick]) -> list[SlotPick]:
    """The lineup today's facts produce, carrying only odds the frozen gate
    published.

    A slot keeps its odds when that lineup has the same two players in it
    with the same number; any other number is a call the frozen gate never
    made, and principle 1 says a fix like this one may only remove numbers. So
    it is withheld, with the reason, and the seeded-call flag goes with it."""
    out: list[SlotPick] = []
    for before, after in zip(frozen, moved):
        if after.confidence is not None and (
                (before.player_id, before.alternative_id, before.confidence)
                != (after.player_id, after.alternative_id, after.confidence)):
            after.confidence = None
            after.confidence_gate = HELD_GATE
            after.flags = [f for f in after.flags if f.get("kind") != "seeded"]
        out.append(after)
    return out


# Why a slot prints no odds when a player in its pair is on the practice squad
# (method §15 C9). Starts "not confirmed to play" so render.report can phrase
# it; the name in brackets is who.
UNCONFIRMED_GATE = "not confirmed to play"


def hold_unconfirmed(picks: Sequence[SlotPick], unconfirmed: Mapping[str, str],
                     players: PlayerIndex) -> list[SlotPick]:
    """The lineup with no odds on any pair that includes a player who is not
    confirmed to play — the practice squad (launch review SS-D1, Oct 2026).

    The live sample printed "Travis Kelce … over Zach Ertz on your bench …
    80%" with Ertz on the Eagles' practice squad ("PS; Vet"): elevated three
    weeks running, so he cleared the three-game bar, and never on an injury
    report, so the gate read him ACTIVE. Unelevated he scores 0.0, which the
    ledger grades a HIT — a call that flatters the record. He may still be
    elevated, so his seat (and his place in a plan's order) stays; only the
    number goes, which is the one direction a report-layer rule may move."""
    if not unconfirmed:
        return list(picks)
    for pick in picks:
        who = next((pid for pid in (pick.player_id, pick.alternative_id)
                    if pid and pid in unconfirmed), None)
        if who is None:
            continue
        if pick.player_id in unconfirmed:
            pick.flags = [dict(f) for f in pick.flags] + [{
                "kind": "unconfirmed",
                "text": f"{unconfirmed[pick.player_id]} — not confirmed to play"}]
        if pick.confidence is not None:
            pick.confidence = None
            pick.confidence_gate = (f"{UNCONFIRMED_GATE} ({players.name(who)}: "
                                    f"{unconfirmed[who]})")
            pick.flags = [f for f in pick.flags if f.get("kind") != "seeded"]
    return list(picks)


# Why a slot prints no odds when the subscriber's lineup shape has no graded
# arm (contract C8): the picker may offer shapes beyond the three the setups
# method graded (standard, superflex, no K or DEF), and a number from an
# ungraded shape is one nothing has checked. Projection only until an arm
# grades it — the shape, not the player, is the reason.
SHAPE_GATE = "odds once this lineup shape is graded"


def hold_ungraded_shape(picks: Sequence[SlotPick]) -> list[SlotPick]:
    """Every pick keeps its seat and projection and loses its odds. Removes
    only — like ``hold_unconfirmed`` — so it needs no arm of its own."""
    for pick in picks:
        if pick.confidence is None:
            continue
        pick.confidence = None
        pick.confidence_gate = SHAPE_GATE
        # The seeded disclosure travels with a number, and the number is gone.
        pick.flags = [f for f in pick.flags if f.get("kind") != "seeded"]
    return list(picks)


def _fits(position: str | None, slot: str) -> bool:
    allowed = FLEX_ELIGIBILITY.get(slot)
    return (position in allowed) if allowed else position == slot


def _certainly_out(pick: SlotPick) -> bool:
    """Out for a certain reason — a bye, a reserve list — not merely on last
    week's injury report."""
    return bool(pick.player_id and pick.status
                and pick.status.status is Status.OUT
                and not _ruled_out_last_week(pick))


def stand_ins(picks: Sequence[SlotPick],
              bench: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Seated starter who can't (or may not) play -> the bench players out only
    on last week's report who could start in his slot (launch audit R4).

    optimal_lineup seats an out player only when every eligible bench player
    is out too, so these are the only bench players left who might take the
    slot — and "nobody eligible" is false while one sits there."""
    out: dict[str, list[str]] = {}
    for pick in picks:
        if not (pick.player_id and pick.status and pick.status.status is Status.OUT):
            continue
        names = [entry["name"] for entry in bench
                 if entry.get("out_kind") == "designation"
                 and _fits(entry.get("position"), pick.slot)]
        if names:
            out[pick.player_id] = names
    return out


def bench_option_held(pick: SlotPick,
                      bench: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The bench player a slot's "no bench player" gate actually means.

    optimal_lineup gates a slot "nobody on your bench is eligible here" when no
    bench player is eligible AND playable, so the reason read as an empty
    bench beside a bench row naming one (launch audit F11). The best such
    player, and why he is no option, or None when the bench really is empty."""
    if not pick.player_id or not (pick.confidence_gate or "").startswith(
            "nobody on your bench"):
        return None
    for entry in bench:                       # best first, as the table prints
        if entry.get("out") and _fits(entry.get("position"), pick.slot):
            return {"name": entry["name"], "kind": entry.get("out_kind"),
                    "text": entry.get("out_text") or "out"}
    return None


def _news_day(watched: Mapping[str, Any] | None, sunday: date | None) -> date | None:
    """When the news a plan waits for is in: the reader checks on Sunday
    morning, or before the watched player's own kickoff when that is earlier
    (the game plan says so for a Thursday game)."""
    days = [d for d in (_game_day(watched), sunday) if d is not None]
    return min(days) if days else None


def in_time(other: Mapping[str, Any] | None, watched: Mapping[str, Any] | None,
            sunday: date | None) -> bool:
    """Does ``other``'s game kick off no earlier than the news on the watched
    player is in? A player whose game comes first is locked before the plan
    can be carried out. No game (a bye, a reserve list) never locks first; an
    unknown kickoff is not evidence that it does.

    This is the FINAL-REPORT clock — a ruling made on the team's last injury
    report, two days before its game (an Out, a Doubtful, a player cleared),
    which is in by game-day morning at the latest. A ruling made at the
    inactives is later: see ``after_inactives``."""
    day = _game_day(other)
    news = _news_day(watched, sunday)
    return day is None or news is None or day >= news


# INACTIVES_LEAD (imported from engine.final_check, one definition for
# Tuesday's plan and Saturday's check): the inactive list is posted 90 minutes
# before each kickoff. A player still questionable on his final report is
# ruled in or out THEN, so a plan that waits on him can only name somebody
# whose game has not started.


def _hhmm(clock: str | None) -> tuple[int, int] | None:
    try:
        hour, minute = (int(part) for part in str(clock or "").split(":"))
    except ValueError:
        return None
    return (hour, minute) if 0 <= hour < 24 and 0 <= minute < 60 else None


def kickoff(game: Mapping[str, Any] | None) -> datetime | None:
    """The game's kickoff as the schedule states it (NFL time, Eastern), or
    None without both a day and a clock."""
    day, clock = _game_day(game), _hhmm((game or {}).get("time"))
    if day is None or clock is None:
        return None
    return datetime(day.year, day.month, day.day, *clock)


def after_inactives(other: Mapping[str, Any] | None,
                    watched: Mapping[str, Any] | None) -> bool:
    """Does ``other``'s game kick off no earlier than the watched player's
    inactive list (90 minutes before HIS kickoff)? Launch review RQ-01, Oct
    2026: "If Ashton Jeanty (RB) is ruled out: move Alvin Kamara into RB" —
    Jeanty played at 4:25 PM, so a game-day ruling landed about 2:55 PM, after
    Kamara's 1:00 PM kickoff had locked him; and "If Terry McLaurin is ruled
    out" (Monday night) named a Sunday player. The old clock compared DAYS.

    No game never locks first. Without a clock on either side the day decides,
    as it always did — an unknown time is not evidence of an early one."""
    if not other:
        return True
    mine, theirs = kickoff(other), kickoff(watched)
    if mine is None or theirs is None:
        day_o, day_w = _game_day(other), _game_day(watched)
        return day_o is None or day_w is None or day_o >= day_w
    return mine >= theirs - INACTIVES_LEAD


def _et(moment: datetime) -> str:
    """"Sun 2:55 PM ET" — a clock as the page prints every kickoff."""
    return (f"{moment.strftime('%a')} {moment.hour % 12 or 12}:{moment.minute:02d} "
            f"{'AM' if moment.hour < 12 else 'PM'} ET")


def _finish(text: str) -> str:
    """A plan of more than one sentence ends like one; a single clause stays
    as every surface has always printed it ("Move X into FLEX (projects 9.5)")."""
    return text + "." if ". " in text and not text.endswith(".") else text


@dataclass(frozen=True)
class Cover:
    """Who goes in when a starter can't: one bench player straight into the
    slot, or a flex starter sliding across and the bench player taking the
    flex (``mover``/``flex_slot``) — the same two moves Saturday's check makes
    (engine.final_check.fill)."""
    incoming: str
    value: float | None            # his printed projection; None: no games yet
    mover: str | None = None
    flex_slot: str | None = None
    practice_squad: bool = False   # plays only if elevated (method §15 C9)

    @property
    def moving(self) -> tuple[str, ...]:
        """Everyone the plan moves — each must still be unlocked when it runs."""
        return (self.incoming,) + ((self.mover,) if self.mover else ())


def _printed(model: ProjectionModel, player_id: str, week: int) -> float | None:
    """The number the report prints for a bench player: his projection, but
    only once he has played this season (the bench table's own rule, so a plan
    and the table never disagree — SS-D5)."""
    projection = model.project(player_id, week)
    if projection is None or not projection.games:
        return None
    return round(projection.mean, 1)


def covers(pick: SlotPick, spec: RosterSpec, picks: Sequence[SlotPick],
           players: PlayerIndex, model: ProjectionModel,
           availability: WeekAvailability, week: int,
           unconfirmed: Mapping[str, str] | None = None) -> list[Cover]:
    """Every way to fill ``pick``'s slot if he can't play, best first.

    Straight off the bench, or — launch review BE-D2/SS-D4, Oct 2026 — one
    slide through a flex: the live sample said "nobody on your bench can step
    in at WR in time" about Zay Flowers while Rome Odunze sat at FLEX and could
    move across with a bench player taking the FLEX; Saturday's check already
    made that move, so Tuesday's plan and Saturday's disagreed. Ranked as
    Saturday ranks them: the higher-projected incoming player, a player with no
    games this season last, a straight swap before a slide, a questionable
    player after a healthy one, then the id. A practice-squad player (method
    §15 C9) comes after everyone confirmed — he plays only if elevated, and
    the plan says to check — and is never the one sliding across.

    Nobody OUT, and no questionable starter as the mover: a plan built on a
    second doubt is not a plan."""
    unconfirmed = unconfirmed or {}
    seated = {p.player_id for p in picks if p.player_id}

    def usable(pid: str, slot: str) -> bool:
        info = players.get(pid)
        return (pid not in seated and info is not None and info.eligible_for(slot)
                and availability.classify(pid).status is not Status.OUT)

    bench = [pid for pid in spec.player_ids if pid not in seated]
    found: list[tuple[tuple, Cover]] = []

    def add(incoming: str, mover: str | None = None, flex: str | None = None) -> None:
        value = _printed(model, incoming, week)
        doubt = availability.classify(incoming).status is Status.QUESTIONABLE
        squad = incoming in unconfirmed
        key = (squad, value is None, -(value or 0.0), mover is not None, doubt,
               incoming, mover or "")
        found.append((key, Cover(incoming, value, mover, flex, squad)))

    for pid in bench:
        if usable(pid, pick.slot) and model.project(pid, week) is not None:
            add(pid)
    for other in picks:
        mover = other.player_id
        if (other is pick or not mover or other.slot not in FLEX_ELIGIBILITY
                or mover in unconfirmed or (players.get(mover) is None)
                or not players.get(mover).eligible_for(pick.slot)
                or availability.classify(mover).status in (Status.OUT,
                                                           Status.QUESTIONABLE)):
            continue
        for pid in bench:
            if usable(pid, other.slot) and model.project(pid, week) is not None:
                add(pid, mover, other.slot)
    return [cover for _, cover in sorted(found, key=lambda item: item[0])]


def stand_in(pick: SlotPick, spec: RosterSpec, picks: Sequence[SlotPick],
             players: PlayerIndex, model: ProjectionModel,
             availability: WeekAvailability, week: int,
             game_of: Callable[[str], Mapping[str, Any] | None],
             sunday: date | None,
             unconfirmed: Mapping[str, str] | None = None,
             ) -> tuple[Cover | None, Cover | None, list[str]]:
    """(best cover if he is ruled out on his final report, best cover if he
    is ruled out at the inactives, the straight swaps too early for either).

    Two clocks because there are two rulings (RQ-01). An Out or Doubtful on
    the final report — two days before his game — is in before game day, so
    anyone who plays that day or later can still go in. A player still
    questionable then is ruled in or out at the inactives, 90 minutes before
    his own kickoff, and only someone whose game has not started can.
    Nobody in time for either: no plan, and the game plan says so (launch
    audit R3/C1: the published sample moved Chase Brown, Thursday night, into
    Tony Pollard's slot on Sunday-morning news)."""
    watched = game_of(pick.player_id or "")
    options = covers(pick, spec, picks, players, model, availability, week,
                     unconfirmed)

    def ok(cover: Cover, clock: Callable[[str], bool]) -> bool:
        return all(clock(pid) for pid in cover.moving)

    final = next((c for c in options
                  if ok(c, lambda pid: in_time(game_of(pid), watched, sunday))), None)
    late = next((c for c in options
                 if ok(c, lambda pid: after_inactives(game_of(pid), watched))), None)
    early = [c.incoming for c in options if c.mover is None
             and not in_time(game_of(c.incoming), watched, sunday)]
    return final, late, list(dict.fromkeys(early))


def cover_action(cover: Cover, slot: str, players: PlayerIndex) -> str:
    """"Move Sam LaPorta into FLEX (projects 9.5)" — or, for a slide, "Move
    Rome Odunze to WR and start Devin Neal at FLEX" (Saturday's own words)."""
    number = (f" (projects {cover.value:.1f})" if cover.value is not None
              else " (no games this season yet)")
    squad = (f". {players.name(cover.incoming)} is on the practice squad: check "
             f"he's been elevated" if cover.practice_squad else "")
    if cover.mover is None:
        return f"Move {players.name(cover.incoming)} into {slot}{number}{squad}"
    return (f"Move {players.name(cover.mover)} to {slot} and start "
            f"{players.name(cover.incoming)} at {cover.flex_slot}{number}{squad}")


def _skipped_line(chosen: Cover, options: Sequence[Cover], name: str,
                  players: PlayerIndex,
                  game_of: Callable[[str], Mapping[str, Any] | None]) -> str:
    """Why a higher-projected bench player is not the plan (launch review
    SS-I8): "Move Sam LaPorta into FLEX (projects 9.5)" while Chase Brown
    (10.3) sat on the bench read as a bug — Brown played Thursday."""
    floor = chosen.value if chosen.value is not None else float("-inf")
    for cover in options:                 # best first, so stop at the chosen one
        if cover == chosen:
            return ""
        if cover.mover is not None or cover.value is None or cover.value <= floor:
            continue
        day = _game_day(game_of(cover.incoming))
        when = f"plays {day.strftime('%A')}" if day else "plays first"
        return (f". {players.name(cover.incoming)} ({cover.value:.1f}) {when}, "
                f"before {name}'s status is known")
    return ""


def starter_plans(name: str, pick: SlotPick, final: Cover | None,
                  late: Cover | None, options: Sequence[Cover],
                  players: PlayerIndex,
                  game_of: Callable[[str], Mapping[str, Any] | None]
                  ) -> list[dict[str, Any]]:
    """The if/then rows for one questionable starter (RQ-01).

    - One cover works for both rulings: one row, as always.
    - The better cover plays before his inactives but after his final report:
      two rows — that cover if he is ruled out before game day, the late one
      if he sits as a game-day call.
    - Only an early cover: the row for a ruling before game day, and the
      decision an expert makes on Sunday — the cover kicks off first, so start
      him before then or keep the starter and take a zero if he sits. Facts and
      a choice; no number is attached to either side."""
    slot, about = pick.slot, pick.player_id
    final = final or late
    if final is None:
        return []
    if late is not None and late == final:
        return [{"condition": f"{name} ({slot}) is ruled out",
                 "action": _finish(cover_action(final, slot, players)
                                   + _skipped_line(final, options, name, players,
                                                   game_of)),
                 "about": about}]
    rows = [{"condition": f"{name} ({slot}) is ruled out before game day",
             "action": _finish(cover_action(final, slot, players)), "about": about}]
    first = min((k for k in (kickoff(game_of(pid)) for pid in final.moving) if k),
                default=None)
    theirs = kickoff(game_of(about or ""))
    if late is not None:
        rows.append({"condition": f"{name} ({slot}) sits as a game-day call",
                     "action": _finish(cover_action(late, slot, players)
                                       + (f". {players.name(final.incoming)} kicks "
                                          f"off first" if first else "")),
                     "about": about})
        return rows
    who = players.name(final.incoming)
    clock = (f" at {_et(first)}, before {name}'s inactives (about "
             f"{_et(theirs - INACTIVES_LEAD)})" if first and theirs else
             f" before {name}'s status is known")
    # The move spelled out, never "make that move": the row above may be the
    # other ruling's, and a reader acting at 12:55 PM reads one line.
    move = (f"start {who}" if final.mover is None else
            f"move {players.name(final.mover)} to {slot} and start {who} at "
            f"{final.flex_slot}")
    rows.append({"condition": f"{name} ({slot}) is still questionable on game day",
                 "action": (f"{who} kicks off{clock}. Decide before then: {move}, "
                            f"or keep {name} and take a zero if he sits."),
                 "about": about})
    return rows


def no_stand_in_line(name: str, slot: str, early: Sequence[str],
                     held: Sequence[str] = ()) -> str:
    """The game plan's sentence for a questionable starter with no if/then —
    never "your if/then already has the answer" (launch audit R7).

    ``held``: bench players who can play the slot but were ruled out on last
    week's report — F11's rule here too: "If Terry McLaurin is out, nobody on
    your bench can play WR" sat above DeVonta Smith's bench row and his own
    "if he's cleared" plan (launch review, 2026 week 6)."""
    names = list(held)
    either = (", ".join(names[:-1]) + f" or {names[-1]}") if len(names) > 1 else \
        (names[0] if names else "")
    unless = f" unless {either} is cleared" if held else ""
    if early:
        return (f"If {name} is out, nobody on your bench can step in at {slot} "
                f"in time{unless} — {_join_words(list(early))} "
                f"{'plays' if len(early) == 1 else 'play'} before {name}'s status is known.")
    return f"If {name} is out, nobody on your bench can play {slot}{unless}."


def pivots_note(plans: Sequence[Mapping[str, Any]], unplanned: Mapping[str, str],
                availability: WeekAvailability) -> str | None:
    """What the if/then says when it has no rows — the TRUE reason (launch
    review SS-D3/G20, Oct 2026). It used to print "no starter we can check is
    listed questionable" whenever the list was empty, beside a lineup row
    flagging Zay Flowers questionable and a game plan telling the reader to
    check on him: the list was empty because nobody could cover him in time."""
    if plans:
        return None
    if unplanned:
        return "No pivots this week. " + " ".join(unplanned.values())
    if not availability.has_snapshot:
        return ("No pivots this week — there's no injury report yet to plan "
                "around.")
    return ("No pivots this week — none of your starters was questionable last "
            "week, and no bench player's news would change your lineup.")


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
    # Byes and reserve lists are ONE line (launch review RQ-18): three
    # separate "Bench X — he can't play this week" items opened the live
    # sample's game plan, each restating what "Set this lineup" already
    # excludes. They come after the decisions, which are the news.
    gone = [entry for entry in explained if entry["out"]]
    deciding = [entry for entry in explained if not entry["out"]]
    room = MAX_NOTABLE_ITEMS - (1 if gone else 0)
    merge_key: dict[int, tuple[str, str]] = {}
    sources: list[Mapping[str, Any]] = []
    for entry in deciding:
        if len(items) >= room:
            break
        rank = f"{entry['last_season_rank']} last season."
        doubtful = (availability.classify(entry["player_id"]).status.value
                    == "questionable")
        instead, paired = None, False
        if not entry["games"]:
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
                if _even_pair(pick, entry["player_id"], entry["projected"],
                              availability):
                    # RQ-14: a dead-even pair is not an instruction, so it is
                    # not on the action list. "Start Drake London over George
                    # Pickens at WR · 50%" at 9.6 each read as a call. When the
                    # pair is the row's own (the % and the name are on it),
                    # the row's "toss-up: either is fine" says it all.
                    if paired:
                        continue
                    action = (f"{who} or {entry['name']} at {slot} — a toss-up, "
                              f"keep whichever you have")
                elif paired:
                    action = (f"Start {who} over {entry['name']} at {slot} · "
                              f"{round(pick.confidence * 100)}%")
                else:
                    action = f"Bench {entry['name']} — {who} starts at {slot}"
                    merge_key[len(items)] = (who, slot)
                versus = (f" Projects {entry['projected']:.1f}, {who} {proj:.1f}."
                          if entry["projected"] is not None else "")
                detail = (f"{entry['name']}: {rank}{listed} {form}{versus}"
                          + (fallback_sentence(pick, entry["name"], players,
                                               model, week, availability)
                             if paired else ""))
        item = {"action": action, "detail": detail,
                "deadline": "before this week's first kickoff", "urgency": "now"}
        if (instead is not None and not paired
                and getattr(instead[3], "alternative_id", None) == entry["player_id"]):
            # The starter's row may owe a reason for sitting this player
            # (even_reason), which needs the schedule; build_solo_report
            # appends it and drops this key.
            item["_starter"] = instead[3].player_id
        items.append(item)
        sources.append(entry)
    items = _merge_same_starter(items, merge_key, sources)
    if gone:
        items.append(_gone_item(gone))
    return bench, items


def _bench_facts(bench: list[dict[str, Any]], availability: WeekAvailability,
                 injury_report: Mapping[str, Any] | None, season: Season,
                 unconfirmed: Mapping[str, str],
                 game_of: Callable[[str], Mapping[str, Any] | None]) -> None:
    """What a bench row says beyond his numbers (mutates the entries).

    - ``note``: a bench player's questionable designation, dated, with what
      happened (launch review BE-D3): two starting rows read "waiting on
      Rhamondre Stevenson" and the report never said why — his Week-5
      Questionable (knee) printed nowhere, because bench rows only carried
      Outs. Or the practice squad (method §15 C9).
    - ``game``: his opponent and kickoff, as starter rows carry them (SS-I8:
      the if/then skipped a higher-projected Chase Brown and nothing on the
      page said he played Thursday). None for a certain absence."""
    for entry in bench:
        pid = entry["player_id"]
        note = questionable_note(pid, availability, injury_report, season)
        if note is None and pid in unconfirmed:
            note = f"{unconfirmed[pid]} — not confirmed to play"
        if note:
            entry["note"] = note
        if not entry.get("out") or entry.get("out_kind") == "designation":
            label = game_label(game_of(pid))
            if label:
                entry["game"] = label


def _gone_item(gone: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """One game-plan line for every starter-calibre player on bye or a
    reserve list (RQ-18). One player reads exactly as before."""
    def why(entry: Mapping[str, Any]) -> str:
        # One sentence after the rank, never a parenthetical: the engine's
        # reason once carried its own "(NFL schedule)", so the line read "WR4
        # last season. (DET on bye (NFL schedule))." (PC-14).
        rank = f"{entry['last_season_rank']} last season."
        return f"{rank} {entry['out_sentence']}" if entry.get("out_sentence") else rank
    if len(gone) == 1:
        action = f"Bench {gone[0]['name']} — he can't play this week"
        detail = why(gone[0])
    else:
        action = (f"Bench {_join_words([e['name'] for e in gone])} — they can't "
                  f"play this week")
        detail = " ".join(f"{e['name']}: {why(e)}" for e in gone)
    return {"action": action, "detail": detail,
            "deadline": "before this week's first kickoff", "urgency": "now"}


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
          questionable: str | None = None,
          if_then: bool = False,
          held: Mapping[str, Any] | None = None,
          model: ProjectionModel | None = None,
          week: int = 0,
          availability: WeekAvailability | None = None,
          reason: str | None = None,
          season_label: str | None = None) -> dict[str, Any]:
    """One lineup row.

    Delegates to ``_slot_json`` rather than rebuilding the dict: the renderers
    read a dozen keys off this shape and a second implementation would drift
    from the first silently. Writing one by hand is exactly how this function
    first shipped with a `projection.floor` that does not exist.

    ``game`` is the row's opponent and kickoff; ``absent`` and ``questionable``
    replace the engine's terse availability flag with the sentence the bench
    rows use. Flags are rebuilt as new dicts — the pick's own list is shared
    with the ledger-facing code and is never edited in place.

    ``if_then`` says whether the if/then names this row's player, so a row
    never points at a plan that is not printed (launch audit R7); ``held`` is
    the bench player behind a "no bench player" gate (F11, bench_option_held).

    With ``model`` (launch review, Oct 2026), the row also carries facts it
    used to leave out — never a new number, every figure is one the model or
    the box scores already hold:
    - ``season_per_game`` and ``last_three``: his games this season under the
      subscriber's scoring (F8/SS-I9 — bench rows printed their last three and
      starters never did, and Kenneth Walker's 15.3 projection sat beside no
      sign of his 27.5-a-game start);
    - no point edge over a bench player the bench table shows without a
      projection (SS-D5: "+6.0 over Devin Neal" beside Neal's "—");
    - ``doubtful_alternative_*``: the higher-projected bench player the odds
      skipped because he was questionable (BE-I1, the confirmed fallback);
    - ``tossup``: a dead-even pair of confirmed players (RQ-14/RQ-15) — the
      percentage, if any, still prints, but the row says either is fine;
    - ``reason``: one plain line for a questionable starter seated even with a
      healthy bench player (BE-I9/SS-I7), from ``even_reason``.
    """
    row = dict(_slot_json(pick, players))
    if usage_lookup and pick.player_id:
        line = usage_lookup(pick.player_id)
        if line:
            row["usage"] = line
    if model is not None and pick.player_id:
        _form_facts(row, pick, players, model, week, availability, season_label)
    if reason:
        row["reason"] = reason
    certain = bool(absent) and absent["kind"] != "designation"
    # A starter on bye or a reserve list is in no game this week, so the row
    # names none (R1: a released kicker's row printed his old team's).
    if game and not certain:
        row["game"] = game
    flags = [dict(f) for f in row.get("flags") or []]
    if absent:
        for flag in flags:
            if flag.get("kind") == "out":
                flag["text"] = absent["flag"]
        if certain:
            # PC-14: a starter who certainly is not playing prints a dash, like
            # the bench rows — "OUT — on bye" beside "8.4" was a number about a
            # game he is not in. (Seated only when nobody eligible was left;
            # the team total is already withheld for the same reason.)
            row["projected"] = None
            row["edge"] = None
            row.pop("season_per_game", None)
            row.pop("last_three", None)
            row["tossup"] = False
    if questionable:
        for flag in flags:
            if flag.get("kind") == "questionable":
                flag["text"] = questionable
    row["flags"] = flags
    row["if_then"] = bool(if_then)
    if held:
        row["confidence_gate"] = (f"{BENCH_HELD_GATE} ({held['name']}: "
                                  f"{held['text']})")
        row["bench_held"] = dict(held)
    return row



# --------------------------------------------------------------------- #
# what a row, a close call and the game plan say about them — facts only
# --------------------------------------------------------------------- #

# A pair this close is a toss-up (launch review RQ-14): a printed 52% or
# less, or under half a point, and "Start X over Y" read as an instruction
# when either start is as good as the other. Presentation only — the
# percentage itself, the seat and the ledger are untouched. Read off the
# PRINTED percentage, so a row never says "53%" and "toss-up" together.
TOSSUP_PERCENT = 52
TOSSUP_POINTS = SWAP_WORTH_POINTS


def _confirmed(availability: WeekAvailability | None, player_id: str | None) -> bool:
    return bool(availability is not None and player_id
                and availability.classify(player_id).status is Status.ACTIVE)


def _even_pair(pick: SlotPick, other_id: str | None, other_value: float | None,
               availability: WeekAvailability | None) -> bool:
    """Is ``pick``'s starter a toss-up with ``other_id`` (printed at
    ``other_value``)? Only between two confirmed players: "either is fine"
    is false when one of them may not play."""
    if (pick.projection is None or other_value is None
            or not _confirmed(availability, pick.player_id)
            or not _confirmed(availability, other_id)):
        return False
    gap = round(round(pick.projection.mean, 1) - other_value, 1)
    if abs(gap) < TOSSUP_POINTS:
        return True
    return (pick.alternative_id == other_id and pick.confidence is not None
            and round(pick.confidence * 100) <= TOSSUP_PERCENT)


def _doubt_words(availability: WeekAvailability | None, player_id: str) -> str:
    """Why the fallback skipped him, in the words that are true of him: the
    fallback skips anyone not ACTIVE, and that is not always a designation."""
    status = availability.classify(player_id).status if availability else None
    return ("was questionable last week" if status is Status.QUESTIONABLE
            else "isn't confirmed to play yet")


def fallback_sentence(pick: SlotPick, over: str, players: PlayerIndex,
                      model: ProjectionModel, week: int,
                      availability: WeekAvailability | None = None) -> str:
    """Why a call is against the NEXT healthy option (launch review BE-I1):
    "Start Drake London over Courtland Sutton at FLEX · 71%" while Rhamondre
    Stevenson (11.3) sat higher on the bench read as the model ranking Sutton
    second. The confirmed-alternative fallback skipped Stevenson because he
    was questionable; the number is unchanged, the sentence says so."""
    doubtful = getattr(pick, "doubtful_alternative_id", None)
    if not doubtful:
        return ""
    value = _printed(model, doubtful, week)
    number = f" ({value:.1f})" if value is not None else ""
    return (f" {players.name(doubtful)}{number} {_doubt_words(availability, doubtful)}, "
            f"so these odds are against {over}, your next healthy option.")


def _form_facts(row: dict[str, Any], pick: SlotPick, players: PlayerIndex,
                model: ProjectionModel, week: int,
                availability: WeekAvailability | None,
                season_label: str | None = None) -> None:
    """The row's own record and the corrections that keep it consistent with
    the bench table (see ``_slot``). Mutates ``row``."""
    games = model.observations(pick.player_id or "", week)
    if games:
        row["season_per_game"] = round(sum(games) / len(games), 1)
        row["season_label"] = season_label
        row["last_three"] = [round(v, 1) for v in games[-3:]]
    alternative = pick.alternative_projection
    if pick.alternative_id and alternative is not None and not alternative.games:
        # SS-D5: the bench table prints "—" for a player with no games this
        # season, so no row may quote an edge over him.
        row["edge"] = None
        row["alternative_projected"] = None
    if pick.doubtful_alternative_id:
        row["doubtful_alternative_name"] = players.name(pick.doubtful_alternative_id)
        row["doubtful_alternative_projected"] = _printed(
            model, pick.doubtful_alternative_id, week)
        row["doubtful_alternative_why"] = _doubt_words(
            availability, pick.doubtful_alternative_id).replace(" last week", "")
    row["tossup"] = bool(pick.alternative_id and row.get("alternative_projected") is not None
                         and _even_pair(pick, pick.alternative_id,
                                        row["alternative_projected"], availability))


def even_reason(pick: SlotPick, players: PlayerIndex,
                availability: WeekAvailability,
                game_of: Callable[[str], Mapping[str, Any] | None],
                sunday: date | None, covered: Mapping[str, Cover]) -> str | None:
    """One plain line for a questionable starter seated level with a healthy
    bench player (launch review BE-I9/SS-I7). The published sample started a
    questionable Tony Pollard at FLEX "even with Chase Brown" (10.3 each) and
    said nothing more — an experienced manager reads that as a mistake. The
    facts settle it: Brown played Thursday, before Pollard's news, so starting
    Pollard kept a Sunday-night fallback and starting Brown would not have.
    Stated as facts and their consequence; the seat rule is not changed."""
    alternative = pick.alternative_projection
    if (not pick.player_id or not pick.alternative_id or pick.projection is None
            or alternative is None or not alternative.games
            or pick.status is None or pick.status.status is not Status.QUESTIONABLE
            or not _confirmed(availability, pick.alternative_id)):
        return None
    mine, theirs = round(pick.projection.mean, 1), round(alternative.mean, 1)
    if abs(round(mine - theirs, 1)) >= TOSSUP_POINTS:
        return None
    starter, other = players.name(pick.player_id), players.name(pick.alternative_id)
    # The row's own edge line already gives the gap ("even with Chase Brown on
    # your bench"); this line says only what the gap cannot.
    lead = ""
    their_game = game_of(pick.alternative_id)
    if after_inactives(their_game, game_of(pick.player_id)):
        return (f"{lead}{other} plays after {starter}'s status is known, so you "
                f"can wait for the news and still switch.")
    day = _game_day(their_game)
    when = day.strftime("%A") if day else "first"
    cover = covered.get(pick.player_id)
    keeps = (f"; starting {starter} keeps {players.name(cover.incoming)} as a "
             f"fallback if he sits" if cover is not None and cover.mover is None
             else "")
    return f"{lead}{other} plays {when}, before {starter}'s status is known{keeps}."


def _named_reason(pick: SlotPick, players: PlayerIndex,
                  availability: WeekAvailability,
                  injury_report: Mapping[str, Any] | None,
                  bench: Sequence[Mapping[str, Any]] = ()) -> str:
    """Why a slot has no odds, naming who and dated (launch review RQ-06): the
    closest-call section printed the engine's own "not enough games on record
    yet (2 and 5; we want at least 3)" and an undated "availability in doubt
    (designated Questionable)", naming nobody. ``bench`` lets a "nobody on
    your bench" gate name the bench player it really means (F11): "nobody on
    your bench can play QB" sat above Lamar Jackson's bench row."""
    gate = pick.confidence_gate or ""
    starter = players.name(pick.player_id or "")
    other = players.name(pick.alternative_id) if pick.alternative_id else ""
    reported = (injury_report or {}).get("week")
    when = f"in Week {reported}" if reported else "last week"

    def who(status: Status) -> str:
        if pick.status is not None and pick.status.status is status:
            return starter
        return other if pick.alternative_id and \
            availability.classify(pick.alternative_id).status is status else starter

    if gate.startswith("availability in doubt"):
        return f"{who(Status.QUESTIONABLE)} was questionable {when}"
    if gate.startswith("not enough games"):
        short = [(name, projection) for name, projection in
                 ((starter, pick.projection), (other, pick.alternative_projection))
                 if projection is not None and projection.evidence < MIN_GAMES_FOR_CALL]
        if short:
            name, projection = short[0]
            return (f"{name} has played {projection.games} "
                    f"game{'' if projection.games == 1 else 's'} this season, and "
                    f"odds start at {MIN_GAMES_FOR_CALL}")
        return "one of them hasn't played enough games yet"
    if gate.startswith("not a live head-to-head"):
        return f"{who(Status.OUT)} can't play this week"
    if gate.startswith(UNCONFIRMED_GATE):
        held = gate[len(UNCONFIRMED_GATE):].strip(" ()")
        return f"{held.replace(':', ' is', 1)}" if held else "a player isn't confirmed to play"
    if gate.startswith("held: the lineup changed"):
        return "the lineup changed around a player who can't play this week"
    if gate.startswith("we don't put odds on defenses"):
        return "we don't put odds on defenses"
    if gate.startswith(SHAPE_GATE):
        return "odds start once this lineup shape is graded"
    if gate.startswith("nobody on your bench"):
        held = bench_option_held(pick, bench)
        if held is not None:
            why = {"bye": "is on bye", "roster": "can't play this week"}.get(
                held.get("kind"), "isn't cleared to play yet")
            return f"{held['name']}, your bench {pick.slot}, {why}"
        return f"nobody on your bench can play {pick.slot}"
    if gate.startswith("no eligible player"):
        return f"nobody on your roster can fill {pick.slot}"
    return f"{starter}'s status isn't confirmed yet"


def _three(values: Sequence[float]) -> str:
    return ", ".join(f"{v:.1f}" for v in values[-3:])


def _decisions(picks: Sequence[SlotPick]) -> list[tuple[float, SlotPick]]:
    """Every slot with a real choice in it — a starter who may play, a bench
    alternative with a printed projection, neither a defense — and its gap."""
    out = []
    for pick in picks:
        alternative = pick.alternative_projection
        if (not pick.player_id or not pick.alternative_id or pick.projection is None
                or alternative is None or not alternative.games
                or _certainly_out(pick)
                or pick.player_id.startswith(f"{DEFENSE}-")
                or pick.alternative_id.startswith(f"{DEFENSE}-")):
            continue
        out.append((round(round(pick.projection.mean, 1)
                          - round(alternative.mean, 1), 1), pick))
    return out


def closest_call(picks: Sequence[SlotPick], players: PlayerIndex,
                 model: ProjectionModel, week: int,
                 availability: WeekAvailability,
                 injury_report: Mapping[str, Any] | None,
                 bench: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The closest-call section, honest about what "closest" means (launch
    review SS-D2, Oct 2026).

    The engine's regret call is the narrowest call that CARRIES ODDS — the
    ledger records it and the public drafts quote it, so it stays exactly
    that. But the section called it "the week's closest call" while a
    dead-even decision sat two rows up with no odds (the published sample:
    Bijan Robinson over Chase Brown, 70%, beside Tony Pollard even with Brown
    at FLEX). So the card says what it is — the closest call with odds — and
    names a narrower decision when there is one, with why it has no odds.
    With no odds anywhere it names the closest decision instead of the
    engine's raw reason (RQ-06). Every figure is a projection or a game score
    the report already prints (SS-I12)."""
    regret = dict(regret_call(list(picks), players))
    decisions = _decisions(picks)

    def pair(pick: SlotPick, word: str) -> str:
        return (f"{players.name(pick.player_id or '')} {word} "
                f"{players.name(pick.alternative_id)} at {pick.slot}, "
                f"{pick.projection.mean:.1f} vs {pick.alternative_projection.mean:.1f}")

    if "gate" not in regret:
        call = next(p for p in picks if p.player_id == regret["start_id"]
                    and p.alternative_id == regret["over_id"])
        regret["label"] = "Closest call with odds"
        mine = model.observations(call.player_id or "", week)
        theirs = model.observations(call.alternative_id or "", week)
        start, over = regret["start_name"], regret["over_name"]
        reason = (f"{start} projects {call.projection.mean:.1f} to {over}'s "
                  f"{call.alternative_projection.mean:.1f}.")
        if mine and theirs:
            reason += f" Last three: {start} {_three(mine)}; {over} {_three(theirs)}."
        if _even_pair(call, call.alternative_id,
                      round(call.alternative_projection.mean, 1), availability):
            reason += " A toss-up: either is fine."
        regret["reason"] = reason
        # At the precision the page prints, like ``_decisions``: compared raw,
        # a 9.6-vs-9.6 call "lost" to another 9.6-vs-9.6 one, and the card
        # named a "closer" decision whose printed gap was the same.
        gap = round(round(call.projection.mean, 1)
                    - round(call.alternative_projection.mean, 1), 1)
        narrower = [(g, p) for g, p in decisions
                    if p.confidence is None and abs(g) < abs(gap)]
        if narrower:
            _, closer = min(narrower, key=lambda item: (abs(item[0]), item[1].slot_index))
            regret["closer"] = (f"Closer on points: {pair(closer, 'or')} — no odds, "
                                f"because {_named_reason(closer, players, availability, injury_report, bench)}.")
        return regret
    if not any(p.projection is not None for p in picks):
        return {"gate": "No call with odds yet — nobody has played a game this "
                        "season, so there's nothing to compare."}
    out: dict[str, Any] = {"gate": "No call with odds this week."}
    if decisions:
        _, nearest = min(decisions, key=lambda item: (abs(item[0]), item[1].slot_index))
        out["closest"] = (f"Closest decision: {pair(nearest, 'over')} — no odds, "
                          f"because {_named_reason(nearest, players, availability, injury_report, bench)}.")
        return out
    # No slot has a real choice in it. One reason across the lineup is named;
    # several are not lined up behind the first slot's, which read as the
    # only one ("nobody on your bench can play QB" over a lineup of reserve
    # lists and byes).
    reasons = list(dict.fromkeys(
        _named_reason(p, players, availability, injury_report, bench)
        for p in picks if p.player_id and p.confidence_gate))
    if len(reasons) == 1:
        out["gate"] = f"No call with odds this week — {reasons[0]}."
    elif reasons:
        out["gate"] = ("No call with odds this week — no starter has a bench "
                       "player we can compare him with.")
    return out


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


POSITION_WORDS = {"QB": "quarterback", "RB": "running back", "WR": "wide receiver",
                  "TE": "tight end"}


def _at_depth(ranks: Mapping[str, tuple[str, int, int]], form: Mapping[str, float],
              position: str, depth: int) -> tuple[int, float] | None:
    """(rank, per-game) of the player ranked ``depth`` at ``position`` last
    season — or the last one ranked, in a thinner pool."""
    pool = sorted((rank[1], pid) for pid, rank in ranks.items()
                  if rank[0] == position and pid in form)
    if not pool:
        return None
    rank, pid = pool[min(depth, len(pool)) - 1]
    return rank, form[pid]


def superflex_items(picks: Sequence[SlotPick], players: PlayerIndex,
                    prior_form: Mapping[str, float] | None,
                    ranks: Mapping[str, tuple[str, int, int]] | None,
                    league_size: int) -> list[dict[str, str]]:
    """A superflex holding a non-quarterback, said once (launch review RQ-16):
    the first thing an expert flags, and the report said nothing.

    The figures are last season's record under this subscriber's scoring, at
    the depth a full league starts (two per team: the 24th of each in a
    12-team league) — the quarterback against the position actually in the
    slot, like for like, whichever way it comes out. Never a projection, no
    player is named to go and get, and the waiver line is printed only when
    the record favours the quarterback."""
    items: list[dict[str, str]] = []
    form, ranked = prior_form or {}, ranks or {}
    depth = 2 * league_size
    for pick in picks:
        if pick.slot != "SUPER_FLEX" or not pick.player_id:
            continue
        position = players.position(pick.player_id)
        if position == "QB":
            continue
        detail = ""
        quarterback = _at_depth(ranked, form, "QB", depth)
        other = _at_depth(ranked, form, position, depth)
        if quarterback and other:
            detail = (f"Last season, under your scoring, the "
                      f"{_ordinal(quarterback[0])}-best quarterback averaged "
                      f"{quarterback[1]:.1f} a game and the {_ordinal(other[0])}-best "
                      f"{POSITION_WORDS.get(position, position)} {other[1]:.1f}.")
            if quarterback[1] > other[1]:
                detail += (" A second quarterback off your waiver wire may be "
                           "worth a look.")
        items.append({
            "action": (f"Your {pick.slot} has no quarterback this week — "
                       f"{players.name(pick.player_id)} ({position}) starts there"),
            **({"detail": detail} if detail else {}),
            "deadline": "before this week's first kickoff",
            "urgency": "now",
        })
    return items


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
    sure thing, and run/drops.py already bans it from public copy.

    A Sunday game before the main 1 PM slot is early too (launch review
    RQ-09): a London kickoff is 9:30 AM ET, its inactives 8:00 AM — 5 AM in
    California — and seven starters at Wembley got only "Sunday morning:
    check his status (gameday morning)". A defense has no status to check
    (RQ-18), so a group of defenses alone is told to set the lineup."""
    if sunday is None:
        return [], set()
    groups: dict[tuple[str, str], list[str]] = {}
    for pid in player_ids:
        game = game_of(pid)
        day = _game_day(game)
        if day is None or not _early(game, sunday) \
                or pid in {p for g in groups.values() for p in g}:
            continue
        groups.setdefault((day.isoformat(), str(game.get("time") or "")), []).append(pid)
    items: list[dict[str, str]] = []
    for (day_iso, clock), pids in sorted(groups.items()):
        day = date.fromisoformat(day_iso)
        hour = int(clock.split(":")[0]) if _clock(clock) else None
        part = (" night" if hour is not None and hour >= 17 else
                " morning" if day == sunday and hour is not None and hour < 12 else "")
        when = day.strftime("%A") + part
        one = len(pids) == 1
        at = f" at {_clock(clock)} ET" if _clock(clock) else ""
        people = [p for p in pids if not p.startswith(f"{DEFENSE}-")]
        if not people:
            ask = "set your lineup before then"
        elif len(people) == len(pids) or len(people) > 1:
            ask = f"check {'his' if one else 'their'} status before then"
        else:
            ask = f"check {players.name(people[0])}'s status before then"
        items.append({
            "action": (f"{when}: {_join_words([players.name(p) for p in pids])} "
                       f"{'kicks off' if one else 'kick off'}{at} — {ask}."),
            "deadline": (f"before Sunday's {_clock(clock)} ET kickoff"
                         if day == sunday and _clock(clock) else
                         f"before {day.strftime('%A')}'s kickoff"),
            "urgency": "deadline",
        })
    return items, {pid for pids in groups.values() for pid in pids}


# The main Sunday slot. A kickoff before it — London, 9:30 AM ET — is early.
MAIN_SLOT = (13, 0)


def _early(game: Mapping[str, Any] | None, sunday: date) -> bool:
    """Before Sunday, or on Sunday before the main 1 PM slot."""
    day = _game_day(game)
    if day is None:
        return False
    if day != sunday:
        return day < sunday
    clock = _hhmm((game or {}).get("time"))
    return clock is not None and clock < MAIN_SLOT


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

    Read off the record ``classify`` decides from, so the sentence and the
    gate cannot disagree about WHETHER he is out; a reserve list is named
    before a bye because it is the longer absence (RQ-04). None for anyone
    not OUT.
    Keys: kind, row (bench column), flag (lineup row), sentence (game plan).
    """
    status = availability.classify(player_id)
    if status.status is not Status.OUT:
        return None
    record = (getattr(availability, "statuses", None) or {}).get(player_id) or {}
    team = record.get("team")
    byes = getattr(availability, "bye_teams", None)
    # A reserve list before a bye (launch review RQ-04): De'Von Achane, on
    # injured reserve with Miami on bye, read only "MIA on bye this week" —
    # which says he is back next week. The list is the longer absence, so it
    # is the one stated; the gate's own order (bye first) decides only OUT.
    if record and record.get("position") != DEFENSE and (
            not record.get("active") or not team):
        reason = record.get("out_reason") or "not on an NFL roster"
        return {"kind": "roster", "row": reason, "flag": f"OUT — {reason}",
                "sentence": "He was released." if reason == "released"
                            else f"He's {reason}."}
    if team and byes is not None and team in byes:
        return {"kind": "bye", "row": f"{team} on bye this week",
                "flag": f"OUT — {team} on bye this week",
                "sentence": f"{team} is on bye this week."}
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

    Which seat (launch audit R2/R4, Oct 2026):
    - never a starter whose game kicks off before this player's news is in.
      "If he's cleared, start him over RJ Harvey" named a Thursday-night back
      on news that lands Friday, and promised a Saturday check that never
      moves a locked starter (RULE F1);
    - a starter on bye or a reserve list is a seat worth 0, not skipped: Breece
      Hall sat on the bench at 9.6 under a bye-week Jahmyr Gibbs while the plan
      said nobody could replace him;
    - a starter out only on last week's report is skipped — his own news is
      open too, and a plan on two unknowns is not a plan.
    The deadline is the earlier of the two kickoffs. The Saturday sentence
    rides only on a Sunday game whose seat is still open when that check runs:
    the check reads Friday's final report before Sunday's kickoffs, is too
    early for a Monday game's final report and too late for a Thursday one."""
    items: list[dict[str, str]] = []
    plans: list[dict[str, Any]] = []
    for entry in bench:
        if entry.get("out_kind") != "designation" or entry.get("projected") is None:
            continue
        watched = game_of(entry["player_id"])
        seat = _seat_if_cleared(entry["position"], picks, players, watched,
                                game_of, sunday)
        if seat is None:
            continue
        pick, theirs, gone = seat
        who, slot = players.name(pick.player_id), pick.slot
        mine = entry["projected"]
        # RQ-14: a swap worth under half a point is not worth a Watch line.
        if round(round(mine, 1) - round(theirs, 1), 1) < SWAP_WORTH_POINTS:
            continue
        starter_game = game_of(pick.player_id)
        if gone:
            detail = (f"{entry['out_text']}. He projects {mine:.1f}; {who} "
                      f"can't play this week.")
            then = f"Start him at {slot} over {who}, who can't play this week"
        else:
            detail = f"{entry['out_text']}. He projects {mine:.1f}, {who} {theirs:.1f}."
            then = f"Start him at {slot} over {who} ({mine:.1f} vs {theirs:.1f})"
        items.append({
            "action": f"Watch {entry['name']}: if he's cleared, start him at "
                      f"{slot} over {who}",
            "detail": detail,
            "deadline": _deadline(_earliest(watched, starter_game)),
            "urgency": "deadline",
        })
        day, seat_day = _game_day(watched), _game_day(starter_game)
        plans.append({
            "condition": f"{entry['name']} is cleared",
            "action": then,
            "saturday": bool(day and sunday and day == sunday
                             and (seat_day is None or seat_day >= sunday)),
            "about": entry["player_id"],
        })
    return items, plans


def _seat_if_cleared(position: str, picks: Sequence[Any], players: PlayerIndex,
                     watched: Mapping[str, Any] | None,
                     game_of: Callable[[str], Mapping[str, Any] | None],
                     sunday: date | None) -> tuple[Any, float, bool] | None:
    """(the starter he would replace, that starter's number, whether that
    starter certainly can't play) — the lowest seat he is eligible for whose
    game comes after his news, a certain absence counting as 0. Ties go to the
    name then the slot, as _displaced_by breaks them."""
    candidates = []
    for pick in picks:
        if not getattr(pick, "player_id", None) or not _fits(position, pick.slot):
            continue
        out = bool(pick.status and pick.status.status is Status.OUT)
        if out and _ruled_out_last_week(pick):
            continue
        if not out and pick.projection is None:
            continue
        if not in_time(game_of(pick.player_id), watched, sunday):
            continue
        value = 0.0 if out else round(pick.projection.mean, 1)
        candidates.append((value, players.name(pick.player_id), pick.slot, pick, out))
    if not candidates:
        return None
    value, _, _, pick, out = min(candidates, key=lambda c: c[:3])
    return pick, value, out


def _earliest(*games: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The game, of those given, that kicks off on the earliest day."""
    dated = [(_game_day(game), game) for game in games if _game_day(game) is not None]
    return min(dated, key=lambda pair: pair[0])[1] if dated else None
