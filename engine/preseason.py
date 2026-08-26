"""The pre-season file — what we can tell a subscriber before any game exists.

Sold and delivered the moment somebody pays, which is the whole point. The
weekly product cannot say anything until box scores exist, so a buyer who paid
in draft season used to wait up to a fortnight holding nothing. "I paid and got
nothing" is the dominant refund driver in a subscription this size, and it was
built into the calendar.

**Every number in here is a FACT, and that is a design constraint rather than a
limitation.** Two sources, both already cached:

- the published NFL schedule, which fixes every team's bye week months ahead;
- last season's completed box scores, scored under this subscriber's own rule.

So nothing here is a projection, a probability or a ranking of what WILL happen.
That means it carries no calibration burden at all: the frozen method's Grade C
governs published *predictions*, and this file makes none. It states what
happened and what the schedule already says. Read the register that follows out
of that: "Kittle scored 12.4 a game last season" is a record; "Kittle will score
12.4" would be a claim we have not earned and do not make.

RULE P1 — no player is ever scored 0.0 from absence. A player with no prior
season (a rookie, or anyone the archive does not cover) has NO RECORD, and that
renders as no record. A zero would read as "he was terrible" when the truth is
"we have nothing on him", which is the fabrication principle 3 forbids.

RULE P2 — a bye collision is only claimed where the roster genuinely cannot fill
a slot. The check places the players who ARE available into the starting
template; a week is only flagged when a slot is left empty. Saying "your RBs are
on bye" when a third RB covers it would be a false alarm, and a file that cries
wolf in August is not read in October.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.history import FLEX_ELIGIBILITY
from engine.roster import DEFENSE, PlayerDirectory
from engine.scoring import score
from ingest.nflverse import bye_teams

# The regular season. Byes never fall in week 1, and the schedule's later weeks
# are the ones a manager can still plan around.
SEASON_WEEKS = range(1, 19)

# What the file says when it has nothing on somebody. Buyer vocabulary: this is
# an absence of evidence, said plainly, never a zero.
NO_RECORD = "no record last season"

# A team defense is a DIFFERENT absence and must not be reported as the same
# one. "No record" on a rookie means the archive has nothing on him; on a
# defense it means we decline to score them, which is the stance the weekly
# product already takes (TEAM_DEFENSE_CONFIDENCE_CALIBRATED is False, so no DEF
# slot carries a number there either). Collapsing the two would tell a
# subscriber their defense was an unknown quantity last season when in fact it
# played seventeen games and we simply do not rank defenses on it.
DEFENSE_NOT_SCORED = "defenses aren't scored here"


def _slot_restrictiveness(slot: str) -> int:
    """Single-position slots claim their player before a flex can take him."""
    allowed = FLEX_ELIGIBILITY.get(slot)
    return len(allowed) if allowed else 1


def _eligible(slot: str, position: str) -> bool:
    allowed = FLEX_ELIGIBILITY.get(slot)
    return position in allowed if allowed else position == slot


def unfillable_slots(slots: Sequence[str],
                     available: Mapping[str, str]) -> list[str]:
    """Which starting slots this roster cannot fill from ``available``.

    ``available`` is {player_id: position} for the players who are NOT on bye.
    Greedy in slot-restrictiveness order — a K slot takes the kicker before a
    FLEX can consider anybody — which is the same order the weekly lineup
    builder uses, so the two cannot disagree about what "covered" means.

    RULE P2: this is what a bye-week claim rests on. A slot is reported only
    when nothing on the roster can occupy it.
    """
    pool = dict(available)
    empty: list[str] = []
    order = sorted(range(len(slots)),
                   key=lambda i: (_slot_restrictiveness(slots[i]), slots[i], i))
    for index in order:
        slot = slots[index]
        taken = next((pid for pid, position in sorted(pool.items())
                      if _eligible(slot, position)), None)
        if taken is None:
            empty.append(slot)
        else:
            pool.pop(taken)
    return empty


def bye_by_team(cache_dir: Path, season: str) -> dict[str, int]:
    """team -> the week it is idle. Straight off the published schedule.

    A team with no bye found is simply absent: the caller then says nothing
    about that player rather than guessing a week, because a wrong bye is worse
    than no bye — it sends somebody looking for a problem that is not there.
    """
    out: dict[str, int] = {}
    for week in SEASON_WEEKS:
        idle = bye_teams(Path(cache_dir), str(season), week)
        if not idle:
            continue
        for team in idle:
            out.setdefault(str(team), week)
    return out


def prior_season_form(prior: Mapping[int, Mapping[str, Mapping[str, str]]],
                      rule) -> dict[str, dict[str, float]]:
    """player -> {points, games, per_game} for last season, under THIS rule.

    Per APPEARANCE, not per week: a player who missed half a season should not
    rank below a worse player who never missed one — the same reason
    engine/usage.py refuses to dilute a rate with games the player sat out.
    ``games`` travels with it because "14.1 a game across 4 games" and "14.1
    across 17" are different facts and the reader is entitled to both.
    """
    totals: dict[str, float] = {}
    games: dict[str, int] = {}
    for rows in prior.values():
        for player_id, row in rows.items():
            totals[player_id] = totals.get(player_id, 0.0) + score(row, rule)
            games[player_id] = games.get(player_id, 0) + 1
    return {pid: {"points": round(totals[pid], 1), "games": games[pid],
                  "per_game": round(totals[pid] / games[pid], 1)}
            for pid in totals if games[pid]}


def build_preseason_report(
    spec,
    directory: PlayerDirectory,
    prior: Mapping[int, Mapping[str, Mapping[str, str]]],
    season: str,
    cache_dir: Path,
    prior_season: str | None = None,
    season_started: bool = False,
    byes: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """One subscriber's pre-season file: byes, thin spots and last year's record.

    ``byes`` is passed in when a batch builds several files: the schedule is
    the same for everybody, and reading it per subscriber would make a hundred
    subscribers cost a hundred times what one does — the opposite of the shared
    per-week load run/solo.py exists to provide.
    """
    by_id = {p.player_id: p for p in directory.players}
    byes = dict(byes) if byes is not None else bye_by_team(cache_dir, season)
    form = prior_season_form(prior, spec.rule)
    slots = list(spec.slots)

    roster: list[dict[str, Any]] = []
    for player_id in spec.player_ids:
        player = by_id.get(player_id)
        if player is None:
            # A roster is validated at intake, so this is defence in depth: a
            # player the directory lost between then and now is named as
            # unknown rather than silently dropped from his own owner's file.
            roster.append({"player_id": player_id, "name": player_id,
                           "position": "UNK", "team": None, "bye": None,
                           "record": None, "no_record_reason": NO_RECORD})
            continue
        record = form.get(player_id)
        roster.append({
            "player_id": player_id,
            "name": player.name,
            "position": player.position,
            "team": player.team,
            "bye": byes.get(player.team) if player.team else None,
            # RULE P1: absent, never zero.
            "record": dict(record) if record else None,
            # Which KIND of absence, so the render can say the true one.
            "no_record_reason": (
                None if record
                else DEFENSE_NOT_SCORED if player.position == DEFENSE
                else NO_RECORD),
        })

    # Bye collisions, week by week. Only weeks where a slot is genuinely left
    # empty (RULE P2), and each one names the slots so it is actionable.
    collisions: list[dict[str, Any]] = []
    for week in SEASON_WEEKS:
        out_this_week = {r["player_id"] for r in roster if r["bye"] == week}
        if not out_this_week:
            continue
        available = {r["player_id"]: r["position"] for r in roster
                     if r["player_id"] not in out_this_week
                     and r["position"] != "UNK"}
        empty = unfillable_slots(slots, available)
        if empty:
            collisions.append({
                "week": week,
                "slots": empty,
                "players": sorted(r["name"] for r in roster
                                  if r["player_id"] in out_this_week),
            })

    # Thin spots: a starting slot whose only eligible bodies are already
    # starting. Reported whether or not a bye exposes it, because it is the
    # thing an injury exposes too.
    thin: list[dict[str, Any]] = []
    for slot in sorted(set(slots)):
        needed = slots.count(slot)
        able = [r for r in roster if _eligible(slot, r["position"])]
        if len(able) <= needed:
            thin.append({"slot": slot, "have": len(able), "start": needed,
                         "players": sorted(r["name"] for r in able)})

    ranked = sorted(
        (r for r in roster if r["record"]),
        key=lambda r: (-r["record"]["per_game"], r["name"]))
    # Only the genuine unknowns. A defense is not an unknown, it is a position
    # we decline to score, and listing it here would misreport that.
    no_record = sorted(r["name"] for r in roster
                       if r["no_record_reason"] == NO_RECORD)

    return {
        "meta": {
            "season": str(season),
            "prior_season": str(prior_season) if prior_season else None,
            "label": getattr(spec, "label", "Your Team"),
            "scoring": spec.scoring,
            "slots": slots,
            "solo": True,
            "preseason": True,
            # The same content serves a mid-season buyer, but the file must not
            # call itself pre-season in October.
            "season_started": bool(season_started),
        },
        "roster": roster,
        "collisions": collisions,
        "thin": thin,
        "ranked": ranked,
        "no_record": no_record,
    }
