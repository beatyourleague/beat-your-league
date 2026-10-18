"""The pre-season report — what we can tell a subscriber before any game exists.

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
governs published *predictions*, and this report makes none. It states what
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
on bye" when a third RB covers it would be a false alarm, and a report that cries
wolf in August is not read in October.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence

from engine.history import FLEX_ELIGIBILITY
from engine.roster import DEFENSE, PlayerDirectory
from engine.scoring import score
from ingest.nflverse import bye_teams

# The regular season. Byes never fall in week 1, and the schedule's later weeks
# are the ones a manager can still plan around.
SEASON_WEEKS = range(1, 19)

# What the report says when it has nothing on somebody. Buyer vocabulary: this is
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


def _current_week(cache_dir: Path, season: str) -> int | None:
    """The week being played now, from the schedule release — run.solo's own
    calendar, so the roster report and the weekly report cannot disagree about
    which weeks are behind us. None when the schedule cannot say, and then no
    week is dropped: a bye listed late is better than a real one hidden."""
    try:
        from run.solo import current_week
        return int(current_week(Path(cache_dir), str(season)))
    except Exception:  # noqa: BLE001 — an unreadable schedule drops nothing
        return None


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


# Half a season. A rank built on three good games would be a small-sample
# artefact dressed as a fact, and this report's whole claim is that everything in
# it is a fact. Below the bar a player simply has no rank, stated as such.
RANK_MIN_GAMES = 8

# Ranked positions. DEF is excluded for the same reason it carries no record:
# we decline to score defenses, so we cannot honestly rank them either.
RANKED_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K"})


def positional_ranks(form: Mapping[str, Mapping[str, float]],
                     directory: PlayerDirectory,
                     min_games: int = RANK_MIN_GAMES,
                     ) -> dict[str, tuple[str, int, int]]:
    """player -> (position, rank, pool size) by last season's points per game.

    The number the report already prints — "18.7 a game" — does not tell a
    reader whether that is good. "WR3 of 159" does, instantly, in the
    vocabulary they already think in. And because it is scored under THIS
    subscriber's rules, the rank is theirs rather than a generic one: a
    reception-heavy receiver ranks differently in PPR than in standard, which
    is the whole point of computing anything per-league.

    Still a pure fact — a ranking of what happened, not a claim about what
    will. No calibration burden, nothing for the frozen method to govern.
    """
    position_of = {p.player_id: p.position for p in directory.players}
    pools: dict[str, list[tuple[float, str]]] = {}
    for player_id, record in form.items():
        position = position_of.get(player_id)
        if position in RANKED_POSITIONS and record["games"] >= min_games:
            pools.setdefault(position, []).append(
                (record["per_game"], player_id))
    out: dict[str, tuple[str, int, int]] = {}
    for position, pool in pools.items():
        # Ties break on id so a report is byte-identical across runs.
        ordered = sorted(pool, key=lambda row: (-row[0], row[1]))
        for index, (_points, player_id) in enumerate(ordered, start=1):
            out[player_id] = (position, index, len(ordered))
    return out


def _out_names(roster: Sequence[Mapping[str, Any]], slots: Sequence[str],
               exclude: Collection[str] = ()) -> list[str]:
    """'Name (reason)' for each player who could play one of ``slots`` but is
    on a reserve list, suspended or released today."""
    return sorted(f'{r["name"]} ({r["out_today"]})' for r in roster
                  if r.get("out_today") and r["player_id"] not in exclude
                  and any(_eligible(slot, r["position"]) for slot in slots))


def build_preseason_report(
    spec,
    directory: PlayerDirectory,
    prior: Mapping[int, Mapping[str, Mapping[str, str]]],
    season: str,
    cache_dir: Path,
    prior_season: str | None = None,
    season_started: bool = False,
    byes: Mapping[str, int] | None = None,
    from_week: int | None = None,
    roster_out: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One subscriber's pre-season report: byes, thin spots and last year's
    record.

    ``byes`` is passed in when a batch builds several reports: the schedule is
    the same for everybody, and reading it per subscriber would make a hundred
    subscribers cost a hundred times what one does — the opposite of the shared
    per-week load run/solo.py exists to provide.

    ``from_week`` is the first week still worth planning around. Once the
    season has started it defaults to the current week, read off the same
    schedule: a Week-6 buyer was told "Week 5: no one to start at DEF" under
    an opener promising "the weeks ahead", and the subject line counted it
    (launch audit C7, Oct 2026). A week already played is not a problem to
    plan around; it is a week somebody lost.

    ``roster_out`` is TODAY's reserve-list / suspension / release status
    (engine.availability.ROSTER_OUT, as run/solo puts it on
    ``WeekData.roster_out`` for the live week). Once the season has started a
    player on it is not cover: the weekly report already shows him OUT, and
    this report counted him as the backup who fills a bye — so a week the
    roster cannot fill went unlisted (EMAILS-119/126-130). He is named, with
    the reason, wherever he would have counted. Never applied pre-season:
    today's list says nothing about a week months away (principle 3).
    """
    by_id = {p.player_id: p for p in directory.players}
    byes = dict(byes) if byes is not None else bye_by_team(cache_dir, season)
    if from_week is None and season_started:
        from_week = _current_week(cache_dir, season)
    out_today = ({str(k): str(v) for k, v in roster_out.items()}
                 if season_started and roster_out is not None else {})
    form = prior_season_form(prior, spec.rule)
    ranks = positional_ranks(form, directory)
    slots = list(spec.slots)

    roster: list[dict[str, Any]] = []
    for player_id in spec.player_ids:
        player = by_id.get(player_id)
        if player is None:
            # A roster is validated at intake, so this is defence in depth: a
            # player the directory lost between then and now is named as
            # unknown rather than silently dropped from his own owner's report.
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
            # Reserve list / suspended / released today, or None (in-season).
            "out_today": out_today.get(player_id),
            "bye": byes.get(player.team) if player.team else None,
            # RULE P1: absent, never zero.
            "record": dict(record) if record else None,
            # Which KIND of absence, so the render can say the true one.
            # (position, rank, pool) or None — see positional_ranks.
            "rank": list(ranks[player_id]) if player_id in ranks else None,
            "no_record_reason": (
                None if record
                else DEFENSE_NOT_SCORED if player.position == DEFENSE
                else NO_RECORD),
        })

    # Bye collisions, week by week. Only weeks where a slot is genuinely left
    # empty (RULE P2), and each one names the slots so it is actionable.
    collisions: list[dict[str, Any]] = []
    weeks_ahead = [week for week in SEASON_WEEKS
                   if from_week is None or week >= from_week]
    can_play = [r for r in roster
                if r["position"] != "UNK" and not r.get("out_today")]
    # A slot that today's reserve list empties in EVERY week is not a bye
    # problem: it shows under the thin spots, with the reason, so a week is
    # never blamed on the wrong player. With nobody out this is empty and the
    # check is exactly what it always was.
    on_roster = {r["player_id"]: r["position"] for r in roster
                 if r["position"] != "UNK"}
    always_empty = (Counter(unfillable_slots(
        slots, {r["player_id"]: r["position"] for r in can_play}))
        - Counter(unfillable_slots(slots, on_roster)))
    for week in weeks_ahead:
        out_this_week = {r["player_id"] for r in roster if r["bye"] == week}
        if not out_this_week:
            continue
        available = {r["player_id"]: r["position"] for r in can_play
                     if r["player_id"] not in out_this_week}
        empty, skip = [], Counter(always_empty)
        for slot in unfillable_slots(slots, available):
            if skip[slot]:
                skip[slot] -= 1
            else:
                empty.append(slot)
        if empty:
            collisions.append({
                "week": week,
                "slots": empty,
                "players": sorted(r["name"] for r in roster
                                  if r["player_id"] in out_this_week),
                "out": _out_names(roster, empty, exclude=out_this_week),
            })

    # Thin spots: a starting slot whose only eligible bodies are already
    # starting. Reported whether or not a bye exposes it, because it is the
    # thing an injury exposes too.
    thin: list[dict[str, Any]] = []
    for slot in sorted(set(slots)):
        needed = slots.count(slot)
        able = [r for r in roster if _eligible(slot, r["position"])
                and not r.get("out_today")]
        if len(able) <= needed:
            thin.append({"slot": slot, "have": len(able), "start": needed,
                         "players": sorted(r["name"] for r in able),
                         "out": _out_names(roster, [slot])})

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
            # The same content serves a mid-season buyer, but the report must
            # not call itself pre-season in October.
            "season_started": bool(season_started),
            # The first week the bye check covers, and whether any bye on
            # the roster is still ahead of it — so a report sent after the
            # last bye says that, rather than "every bye is covered".
            "from_week": from_week,
            # Whether today's reserve list was applied (in-season, and the
            # caller passed it) — the render says it only when it was.
            "roster_status": bool(season_started and roster_out is not None),
            "byes_ahead": any(r["bye"] is not None
                              and (from_week is None or r["bye"] >= from_week)
                              for r in roster),
        },
        "roster": roster,
        "collisions": collisions,
        "thin": thin,
        "ranked": ranked,
        "no_record": no_record,
    }
