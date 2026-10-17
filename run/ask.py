"""The product's own answer to "A or B this week?" — for replying in public.

Usage:
    python -m run.ask "Player A" "Player B" [--scoring ppr|half_ppr|standard]
                      [--size 12] [--publish]
    make ask A="Jalen Hurts" B="Bo Nix" [ARGS="--publish --scoring half_ppr"]

Replying to "who do I start?" posts is the cheapest marketing this product
has, and without this the owner answers from gut or, worse, quotes a number
nobody computed (principle 3). This prints what the weekly report would say
about the pair, from the same pipeline: the same directory and name parser as
the join page, the same week load, the same model, the same publish gate and
the same recalibration a subscriber's report applies.

Rules, each because a reply is a public statement with no report around it:
- **RULE R3 for names.** Resolved by `PlayerDirectory.resolve`, the Python
  twin of the join page's parser, against the same directory. An ambiguous or
  unknown name STOPS and names the candidates; a reply about the wrong Josh is
  worse than no reply.
- **Facts always.** Projection, last three games, usage per game, status on
  the report's own information set, opponent. Every one is already printed in
  the weekly report for a player who is on the roster.
- **The % only under the report's gate.** Both players confirmed active,
  enough games on record, never a defense — decided by `optimal_lineup`
  itself, not by a copy of it — at the one slot of the standard lineup that
  holds both. A pair that never shares a slot gets no %.
- **A % posted in public is a PUBLISHED probability (principle 2).** So the
  number only prints with ``--publish``, which records it on the public
  record exactly as a subscriber's report would (`extract_published_calls`
  into the typed-{scoring}-{size}-{season} store), and Monday's grading
  settles it. Without the flag the facts print and the % is withheld. If the
  pair is already on the record this week, in either order and at any slot,
  the RECORDED number is quoted and nothing new is written — one game is one
  call, and the reply must match the record.
- **Only in the window a Tuesday report covers.** Week W-1 fully played and
  week W not yet kicked off. The number is a Tuesday-information prediction
  (week W-1's injury report); once games are underway a "prediction" is the
  thing the ledger exists to make impossible, and before W-1 is over it would
  be built without that week's games.
- **Writes nothing else.** No report, no plan, no send log.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from engine.availability import PlayerStatus, Status
from engine.history import FLEX_ELIGIBILITY
from engine.projection import ProjectionModel
from engine.roster import Player, PlayerDirectory, normalize
from engine.solo_report import _games_line
from engine.subscriber import (SUBSCRIBER_ROSTER_ID, RosterSpec, _team_week,
                               build_season, rosterable_field)
from engine.week_report import SlotPick, _slot_json, optimal_lineup
from run.refs import SIZES
from run.solo import (ANCHOR_WEIGHT, CACHE_DIR, CONTEXT_WEEKS,
                      EARLY_SEASON_LAMBDA, MEASURED_TEMPLATE, SoloError,
                      WeekData, _schedule, _team_before, anchored,
                      calibrator_for, fallback_for, load_week_data,
                      seeded_scope, week_has_kicked_off)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
SCORINGS = ("ppr", "half_ppr", "standard")
SCORING_LABEL = {"ppr": "Full PPR", "half_ppr": "Half PPR",
                 "standard": "Standard"}
# The lineup every graded arm was measured on and the join page's default. It
# decides the positional prior's depth and whether last season is counted in,
# so the pair is judged by the model a standard-lineup subscriber gets.
TEMPLATE = MEASURED_TEMPLATE


class AskError(RuntimeError):
    """The question cannot be answered as asked (a name, the week)."""


# --------------------------------------------------------------------- #
# names — RULE R3
# --------------------------------------------------------------------- #

def _who(player: Player) -> str:
    return f"{player.name} ({player.position}{', ' + player.team if player.team else ''})"


def resolve_pair(directory: PlayerDirectory, typed_a: str,
                 typed_b: str) -> tuple[Player, Player]:
    """Both names -> players, or AskError naming what went wrong. Never picks
    between candidates: the person typing is the one who knows."""
    problems: list[str] = []
    found: list[Player] = []
    for typed in (typed_a, typed_b):
        match = directory.resolve(typed)
        if match.resolved:
            found.append(match.player)
        elif match.candidates:
            problems.append(f'"{typed}" is more than one player: '
                            + "; ".join(_who(c) for c in match.candidates)
                            + ". Type the full name as listed.")
        else:
            problems.append(f'"{typed}": we don\'t have anybody by that name '
                            f"in this season's directory.")
    if problems:
        raise AskError("\n".join(problems))
    if found[0].player_id == found[1].player_id:
        raise AskError(f"both names are {_who(found[0])} — ask about two "
                       f"different players.")
    return found[0], found[1]


def lookalikes(directory: PlayerDirectory, player: Player) -> list[Player]:
    """Same-position names within two letters (Bijan / Brian Robinson). The
    join page shows these inline; here they are a note, because a published
    call about the wrong one stays on the public record for good."""
    from render.player_index import _within
    key = normalize(player.name)
    return [other for other in directory.players
            if other.player_id != player.player_id
            and other.position == player.position
            and _within(key, normalize(other.name))]


# --------------------------------------------------------------------- #
# the week, the model, the call
# --------------------------------------------------------------------- #

def shared_slot(data: WeekData, a: Player, b: Player) -> str | None:
    """The standard-lineup slot that can hold both, single-position slots
    first (the order `optimal_lineup` fills them in). None when no slot can:
    a quarterback and a receiver never compete for one seat outside
    superflex, so the report never makes that call."""
    order = sorted(dict.fromkeys(TEMPLATE),
                   key=lambda s: len(FLEX_ELIGIBILITY.get(s, {s})))
    infos = [data.players.get(a.player_id), data.players.get(b.player_id)]
    if any(info is None for info in infos):
        return None
    for slot in order:
        if all(info.eligible_for(slot) for info in infos):
            return slot
    return None


@dataclass
class Call:
    """What the report would print for the pair at ``slot``."""

    slot: str | None
    pick: SlotPick | None
    league_id: str
    model: Any


def head_to_head(data: WeekData, a: Player, b: Player, scoring: str,
                 size: int) -> Call:
    """The pair, judged the way `run.solo.report_for` judges a subscriber's
    roster: the field, the season and the model are built from the standard
    lineup at this league size, so the anchor, the early-season seed and the
    recalibration switch on exactly when they would for a subscriber. Only
    the LINEUP is narrowed to the one shared slot, which is what makes the
    second player the first one's alternative there.

    The model choice below mirrors `report_for` line for line; run/solo.py
    exposes no single function for it. `test_ask_prints_what_a_subscriber_
    report_prints` pins the two together, so a change on one side that is not
    made on the other fails the suite rather than a public reply.
    """
    slot = shared_slot(data, a, b)
    shape = SimpleNamespace(scoring=scoring, slots=TEMPLATE)
    spec = RosterSpec(player_ids=(a.player_id, b.player_id),
                      slots=(slot or TEMPLATE[0],), scoring=scoring,
                      label="Ask")
    field = rosterable_field(data.directory, data.prior, spec.rule, TEMPLATE,
                             league_size=size)
    season = build_season(spec, data.weekly, data.directory, data.season,
                          data.week, league_size=size, field=field,
                          store_slots=TEMPLATE)
    seeded = seeded_scope(shape, size, data.week)
    contextual = (data.context is not None and not seeded
                  and data.week in CONTEXT_WEEKS)
    anchor = contextual or anchored(shape, size, data.week, seeded)
    if seeded or anchor:
        from engine.nflverse_backtest import prior_self_observations
        model = ProjectionModel(season, data.players,
                                prior_self=prior_self_observations(
                                    data.prior, spec.rule),
                                prior_self_weight=(EARLY_SEASON_LAMBDA
                                                   if seeded else 0.0),
                                late_self_weight=(ANCHOR_WEIGHT or 0.25)
                                if anchor else 0.0,
                                **(data.context if contextual else {}))
    else:
        model = ProjectionModel(season, data.players)
    if slot is None:
        return Call(None, None, season.league_id, model)

    team_week = (season.weeks.get(data.week - 1) or {}).get(SUBSCRIBER_ROSTER_ID)
    if team_week is None:                  # week 1: nothing played yet
        team_week = _team_week(SUBSCRIBER_ROSTER_ID, max(data.week - 1, 0),
                               spec.player_ids, {}, spec.rule)
    [pick] = optimal_lineup(season, team_week, model, data.players,
                            data.availability, data.week,
                            calibrate=calibrator_for(data.week, seeded, anchor,
                                                     contextual),
                            confirmed_fallback=fallback_for(data.week, seeded))
    return Call(slot, pick, season.league_id, model)


def why_no_call(call: Call, statuses: dict[str, PlayerStatus],
                projected: dict[str, float | None], names: dict[str, str]) -> str:
    """The reason in plain words. Display only: whether a % exists is decided
    by `optimal_lineup` (pick.confidence), never here."""
    if call.slot is None:
        return ("they never compete for one slot in a standard lineup, so the "
                "report makes no call between them")
    for pid, status in statuses.items():
        if status.status is Status.OUT:
            return f"{names[pid]} can't play this week: {status.reason}"
    for pid in statuses:
        if projected.get(pid) is None:
            return f"{names[pid]} has no games on record this season yet"
    return (call.pick.confidence_gate if call.pick and call.pick.confidence_gate
            else "nothing the report would publish")


# --------------------------------------------------------------------- #
# the facts — each one already printed by the weekly report
# --------------------------------------------------------------------- #

def _clock(gametime: str) -> str:
    try:
        hour, minute = (int(x) for x in gametime.split(":"))
    except ValueError:
        return ""
    return f"{(hour - 1) % 12 + 1}:{minute:02d} {'AM' if hour < 12 else 'PM'} ET"


def opponent(rows: Sequence[dict], season: str, week: int, team: str | None) -> str | None:
    """"at DAL, Sun 4:25 PM ET" from the schedule, or None when unknown."""
    if not team:
        return None
    for row in rows:
        if str(row.get("season")) != str(season) or str(row.get("week")) != str(week):
            continue
        home, away = row.get("home_team"), row.get("away_team")
        if team not in (home, away):
            continue
        other = away if team == home else home
        where = ("vs" if team == home else "at")
        if (row.get("location") or "").lower() == "neutral":
            where = "vs"
        when = " ".join(x for x in ((row.get("weekday") or "")[:3],
                                    _clock(row.get("gametime") or "")) if x)
        return f"{where} {other}" + (f", {when}" if when else "")
    return None


def _usage(data: WeekData, player_id: str) -> str | None:
    """Per game, over the report's own window. Absent counts stay absent."""
    usage = data.usage.get(player_id)
    if usage is None or usage.weeks <= 0:
        return None
    bits = [f"{usage.per_game(value):.1f} {label}"
            for value, label in ((usage.targets, "targets"),
                                 (usage.carries, "carries"))
            if value is not None]
    if not bits:
        return None
    span = f"last {usage.weeks} game{'s' if usage.weeks != 1 else ''}"
    return f"{' and '.join(bits)} a game ({span})"


def facts(data: WeekData, call: Call, player: Player,
          schedule: Sequence[dict]) -> dict[str, Any]:
    status = data.availability.classify(player.player_id)
    projection = call.model.project(player.player_id, data.week)
    out = status.status is Status.OUT
    team = _team_before(player.player_id, data.week, data.weekly) or player.team
    if player.is_defense:
        team = player.team
    games = call.model.observations(player.player_id, data.week)
    return {
        "player": player,
        "team": team,
        "status": status,
        # None for a player who cannot play: the model's number is form, blind
        # to this week's designation, and "can't play" beside "6.4" was the
        # first render of the bench block (engine/solo_report.py).
        "projected": (round(projection.mean, 1)
                      if projection is not None and projection.games and not out
                      else None),
        "games": _games_line(games) if games else "No games this season yet.",
        "usage": None if player.is_defense else _usage(data, player.player_id),
        "opponent": opponent(schedule, data.season, data.week, team),
    }


# --------------------------------------------------------------------- #
# publishing — principle 2
# --------------------------------------------------------------------- #

def publish(call: Call, data: WeekData, processed_dir: Path) -> tuple[Any, bool]:
    """(the call as it stands on the public record, whether this run wrote it).

    Recorded through `extract_published_calls`, the function every subscriber
    report goes through, from the same row `_slot_json` builds — so the store,
    the call id and the fields are a subscriber's, and Monday grades it. A
    pair already on the record this week (either order, any slot) is quoted,
    not re-recorded: two rows for one game would count it twice, and a reply
    quoting a number the record does not hold would be a second answer."""
    from engine.ledger import (extract_published_calls, ledger_path,
                               load_ledger, record_calls)
    path = ledger_path(processed_dir, call.league_id)
    pair = {call.pick.player_id, call.pick.alternative_id}
    for held in load_ledger(path):
        if (held.season == str(data.season) and held.week == data.week
                and {held.pick_id, held.over_id} == pair):
            return held, False
    report = {"meta": {"league_id": call.league_id, "season": data.season,
                       "week": data.week, "my_roster_id": SUBSCRIBER_ROSTER_ID},
              "lineup": [_slot_json(call.pick, data.players)], "regret": {}}
    [new] = extract_published_calls(report)
    record_calls(path, [new])
    return new, True


# --------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------- #

def _block(fact: dict[str, Any], notes: list[Player]) -> list[str]:
    player: Player = fact["player"]
    head = f"{player.name} ({player.position}{', ' + fact['team'] if fact['team'] else ''})"
    if fact["opponent"]:
        head += f" — {fact['opponent']}"
    status: PlayerStatus = fact["status"]
    lines = [head,
             f"  Projection   {fact['projected']:.1f}" if fact["projected"] is not None
             else "  Projection   none" + (" — he can't play this week"
                                           if status.status is Status.OUT else ""),
             f"  Form         {fact['games']}"]
    if fact["usage"]:
        lines.append(f"  Usage        {fact['usage']}")
    lines.append(f"  Status       {status.status.value} — {status.reason}")
    for other in notes:
        lines.append(f"  Check        also in the directory: {_who(other)}")
    return lines


def previous_week_played(schedule: Sequence[dict], season: str, week: int) -> bool:
    """Is every game of week ``week - 1`` final? With the kickoff check, this
    pins a published % to the window a Tuesday report covers. Without it,
    ``--week 7`` on the Friday of week 6 would record a week-7 prediction
    built on a half-played week 6 and its half-published injury report — a
    number no subscriber was ever sent. An unreadable schedule is a no."""
    if week <= 1:
        return True
    games = [row for row in schedule
             if str(row.get("season")) == str(season)
             and str(row.get("week")) == str(week - 1)]
    return bool(games) and all(
        str(row.get("home_score") or "").strip() and str(row.get("away_score") or "").strip()
        for row in games)


def verdict(call: Call, data: WeekData, sides: list[dict[str, Any]],
            args: argparse.Namespace, now: datetime,
            schedule: Sequence[dict] = ()) -> tuple[list[str], int]:
    """(the head-to-head lines, exit code). A % appears in exactly one place:
    after the call is on the public record, and then as RECORDED. Asking to
    publish and not publishing is exit 1, so it is never mistaken for done."""
    pick = call.pick
    names = {f["player"].player_id: f["player"].name for f in sides}
    if pick is None or pick.confidence is None:
        reason = why_no_call(call, {f["player"].player_id: f["status"] for f in sides},
                             {f["player"].player_id: f["projected"] for f in sides},
                             names)
        return [f"No % — {reason}."], 0
    start, over = names[pick.player_id], names[pick.alternative_id]
    if not args.publish:
        return [f"At {call.slot} the report starts {start} over {over}.",
                "The % is withheld: a % posted in public is a published call. "
                "Re-run with --publish to put it on the public record "
                f"({call.league_id}, graded on Monday) and print it."], 0
    if week_has_kicked_off(args.cache, data.season, data.week, now=now):
        return [f"At {call.slot} the report starts {start} over {over}.",
                f"Not published: week {data.week} has kicked off, and a % now "
                f"would be a prediction about games already underway."], 1
    if not previous_week_played(schedule, data.season, data.week):
        return [f"At {call.slot} the report starts {start} over {over}.",
                f"Not published: week {data.week - 1} isn't over, so this is not "
                f"the week a report would cover yet — the number would be built "
                f"without that week's games."], 1
    try:
        held, wrote = publish(call, data, args.processed_dir)
    except Exception as exc:  # noqa: BLE001 — no record, no number
        return [f"At {call.slot} the report starts {start} over {over}.",
                f"Not published: the public record could not be written ({exc})."], 1
    return [f"At {held.slot}: start {held.pick_name} over {held.over_name} — "
            f"{round(held.confidence * 100)}%, the chance {held.pick_name} "
            f"outscores {held.over_name} this week.",
            f"Recorded on the public record ({call.league_id}); Monday's grading "
            f"settles it." if wrote else
            "Already on the public record this week; quoted as recorded, "
            "nothing new written."], 0


def main(argv: list[str] | None = None, *, session=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a", help="first player, as you'd type him on the join page")
    parser.add_argument("b", help="second player")
    parser.add_argument("--scoring", choices=SCORINGS, default="ppr")
    parser.add_argument("--size", type=int, choices=sorted(SIZES.values()),
                        default=12)
    parser.add_argument("--publish", action="store_true",
                        help="record the call on the public record and print the %%")
    parser.add_argument("--season", help="default: the current NFL season")
    parser.add_argument("--week", type=int, help="default: the current NFL week")
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--now", help=argparse.SUPPRESS)       # tests
    args = parser.parse_args(argv)
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.now(timezone.utc))

    try:
        data = load_week_data(args.cache, args.season, args.week,
                              session=session, today=now.date())
        a, b = resolve_pair(data.directory, args.a, args.b)
    except (SoloError, AskError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    call = head_to_head(data, a, b, args.scoring, args.size)
    try:
        schedule = _schedule(args.cache, session=session)
    except Exception:  # noqa: BLE001 — the opponent is a nicety, not a fact we need
        schedule = []
    sides = [facts(data, call, p, schedule) for p in (a, b)]

    lines = [f"{data.season} Week {data.week} · {SCORING_LABEL[args.scoring]} · "
             f"{args.size} teams · standard lineup",
             f"Status as of {data.availability.snapshot_as_of or 'no injury report yet'}.",
             ""]
    for fact in sides:
        lines += _block(fact, lookalikes(data.directory, fact["player"])) + [""]

    said, code = verdict(call, data, sides, args, now, schedule)
    lines += said + ["", data.attribution]
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
