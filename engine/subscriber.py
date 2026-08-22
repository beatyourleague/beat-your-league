"""A subscriber's league, assembled from what they typed plus public data.

THE WHOLE POINT OF THIS MODULE. The engine's shapes — ``Season``, ``TeamWeek``,
``PlayerIndex`` — turned out not to be Sleeper-specific at all. They describe
"a roster, weekly points per player, and starting slots", which is exactly what
we can build from a typed roster plus nflverse. So the post-Sleeper product does
not rewrite the engine (PLAN §0); it FEEDS it, and the projection model, the
gating, the decisions, the ledger and both renderers keep working unchanged.

Three things are worth knowing before changing anything here.

**RULE B1 — A WEEK WITH NO STAT LINE IS 0.0, NOT ABSENT — AND ABSENCE IS
RECORDED SEPARATELY FROM THE SCORE.** Sleeper reported a
player who did not play as exactly 0.0, and the entire calibration story rests
on that: starters score 0.0 about 3% of the time and bench players 35%, which is
what told us the engine's problem was availability rather than scoring. If a
missing nflverse row became a missing key instead of a zero, every player would
look like he appears in every week he played and the availability asymmetry — the
most important finding in the backtest — would vanish silently.

**RULE B2 — THE POSITIONAL PRIOR NEEDS A POPULATION, AND CHOOSING IT WRONG
MOVES EVERY NUMBER.** ``ProjectionModel`` shrinks each player toward his
position's mean and appearance rate. Under Sleeper that population was twelve
rosters — the players managers had actually chosen. Fifteen players is far too
thin to shrink toward, so a FIELD is loaded under ``FIELD_ROSTER_ID``, which
lives in ``season.weeks`` but deliberately NOT in ``season.teams``: one dict
feeds the statistics, the other feeds buyer-visible counts like "the other 11
teams".

Who is in that field is not a detail. MEASURED on 2024 weeks 1-9: a field of
every QB with a stat row (67 of them, third-stringers included) gives a QB prior
of **13.3**, and Josh Allen — who actually averaged 20.1 — projects **13.7**. A
field of the top 24 QBs, which is what a 12-team league rosters, gives a prior
of **17.3**. The wrong population is a six-point error on a starting
quarterback, in the same direction for everyone.

So the field is the ROSTERABLE population, sized from the league, and it is
selected on the PREVIOUS season's production rather than this one's. That
matters: choosing this season's producers would select on the outcome being
predicted, and would inflate the appearance rate — which is the exact quantity
the availability gate depends on.

**RULE B3 — WE DO NOT KNOW WHAT THEY STARTED.** We never saw their league, so
past-week ``starters`` are empty and stay empty. Anything that grades what a
manager actually did — last week's result, points left on the bench, the
manager's own start/sit accuracy — cannot be computed for a solo subscriber and
must be cut rather than guessed. ``optimal_lineup`` is unaffected: it reads the
roster and the projections, never the history of lineups.

The calibration consequence, stated plainly because it is a principle-1 matter:
the published evidence was measured on Sleeper-sourced points over a
twelve-roster population. This module changes both the point source and the
prior population, so **that evidence does not transfer and must be re-measured
on nflverse before any confidence number is published.** The field-sizing rule
below is a defensible default, not a validated one; the backtest re-run is what
turns it into either evidence or a correction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from engine.history import (FLEX_ELIGIBILITY, PlayerIndex, Season, Team,
                            TeamWeek)
from engine.roster import DEFENSE, PlayerDirectory
from engine.scoring import ScoringRule, preset, score, score_defense

# Present in ``weeks`` so the model can build a prior; absent from ``teams`` so
# no buyer-visible count includes it. See RULE B2.
FIELD_ROSTER_ID = 0
SUBSCRIBER_ROSTER_ID = 1

# What Sleeper wrote for a player who did not play, and what RULE B1 preserves.
DID_NOT_PLAY = 0.0


class SubscriberError(ValueError):
    """A roster we cannot turn into a league-season."""


@dataclass(frozen=True)
class RosterSpec:
    """Everything the subscriber told us, validated."""

    player_ids: tuple[str, ...]
    slots: tuple[str, ...]
    scoring: str
    label: str = "Your Team"

    def __post_init__(self) -> None:
        if not self.player_ids:
            raise SubscriberError("a roster needs at least one player")
        if len(set(self.player_ids)) != len(self.player_ids):
            raise SubscriberError("the same player appears twice on this roster")
        if not self.slots:
            raise SubscriberError("a lineup needs at least one starting slot")
        if len(self.player_ids) < len(self.slots):
            raise SubscriberError(
                f"{len(self.slots)} starting slots but only "
                f"{len(self.player_ids)} players")

    @property
    def rule(self) -> ScoringRule:
        return preset(self.scoring)


def player_index(directory: PlayerDirectory) -> PlayerIndex:
    """A PlayerIndex over the nflverse directory.

    PlayerIndex was written to read Sleeper's player table, so it is fed the
    same record shape rather than being changed — the fewer things that move at
    once, the fewer places a bug can hide.
    """
    raw = {
        player.player_id: {
            "full_name": player.name,
            "position": player.position,
            "fantasy_positions": _fantasy_positions(player.position),
        }
        for player in directory.players
    }
    return PlayerIndex(raw)


def _fantasy_positions(position: str) -> list[str]:
    """What slots this position can fill.

    A fullback is slotted at RB by every league that carries one, so listing FB
    alone would make a real rostered player ineligible for the only slot he can
    occupy — and RULE R3's "never guess" applies to eligibility too: better to
    say he is an RB, which leagues agree on, than to leave him unplayable.
    """
    if position == "FB":
        return ["RB", "FB"]
    return [position]


def build_season(
    spec: RosterSpec,
    weekly: Mapping[int, Mapping[str, Mapping[str, object]]],
    directory: PlayerDirectory,
    season: str,
    through_week: int,
    league_size: int = 12,
    field: Iterable[str] | None = None,
) -> Season:
    """Assemble the Season the engine consumes.

    ``weekly`` maps week -> gsis_id -> nflverse stat row, for every week strictly
    before ``through_week``. Weeks are scored under the subscriber's own rule
    (RULE S1), never read from a pre-baked total.

    ``league_size`` is what the subscriber says their league holds. It is only a
    denominator for buyer-visible counts; nothing statistical depends on it, and
    it is NOT invented — the intake asks.

    ``field`` is the rosterable population the positional prior is built from
    (RULE B2) — use ``rosterable_field``. Passing nothing gives a field of only
    the subscriber's own roster, which is statistically far too thin; it is
    allowed so a caller can be explicit about wanting that, never as a default
    somebody gets by accident.
    """
    if through_week < 1:
        raise SubscriberError(f"week {through_week} is not a week")
    rule = spec.rule
    # The field EXCLUDES the subscriber's own players. Without this, every
    # rostered player appears in two TeamWeeks per week and the model counts
    # him twice: a nine-week season reported "18 games of form". That is not
    # cosmetic — MIN_GAMES_FOR_CALL is an evidence gate, so a player with two
    # real appearances would show four and become publishable, and the doubled
    # sample would shrink his standard deviation into false confidence. Found
    # by reading the numbers out of a real run, not by a test.
    on_roster = set(spec.player_ids)
    field_ids = [pid for pid in (field or ()) if pid not in on_roster]

    weeks: dict[int, dict[int, TeamWeek]] = {}
    for week in range(1, through_week):
        rows = weekly.get(week) or {}
        weeks[week] = {
            SUBSCRIBER_ROSTER_ID: _team_week(
                SUBSCRIBER_ROSTER_ID, week, spec.player_ids, rows, rule),
            # RULE B2. Same shape, different purpose: this one is never
            # rendered, and its roster id is absent from `teams` below.
            FIELD_ROSTER_ID: _team_week(
                FIELD_ROSTER_ID, week, field_ids, rows, rule),
        }

    result = Season(
        # The SCORING PRESET is part of the identity, not decoration. Without a
        # league there is one shared ledger, and engine/ledger.py hashes a call
        # id from (league_id, season, week, roster_id, slot, pick, over) — all
        # of which are equal for a PPR subscriber and a standard-scoring one
        # making the "same" call. Measured on real 2024 week-10 data: 5 of 6
        # calls collided while publishing DIFFERENT probabilities (0.647 vs
        # 0.632, 0.616 vs 0.591), so record_calls kept whichever ran first and
        # dropped the other. Grading is worse: "did the pick outscore the
        # alternative" has a different answer under each rule, so a single row
        # cannot be graded correctly for both. Splitting the id splits the
        # store, which is also how grading learns which rule to score with.
        # ...and the LEAGUE SIZE, for the same reason. It sets the positional
        # prior's depth, so it moves the published probability: measured across
        # sizes 4-32 on real 2024 week-10 data, a spread of 0.022 and 1 call in
        # 3 crossing a calibration bucket boundary. The graded pair is identical
        # either way, so this is not a wrong ANSWER like the scoring collision
        # was — it is a probability recorded in the wrong bucket, which distorts
        # the exact table the ledger exists to produce.
        league_id=f"typed-{spec.scoring}-{league_size}-{season}",
        season=str(season),
        name="Your league",
        status="in_season",
        roster_positions=tuple(spec.slots),
        playoff_week_start=None,
        # The engine only ever passes this through; the numbers come from
        # engine.scoring, which the subscriber's own preset selects.
        scoring_settings={"scoring": spec.scoring},
        # RULE W1 already forbids trusting a stated budget as a denominator, and
        # we no longer see a transaction log at all — so there is no waiver
        # market for a solo subscriber and this stays None rather than inviting
        # one to be computed from nothing.
        waiver_budget=None,
    )
    result.weeks = weeks
    # The other teams in the league genuinely EXIST — we simply do not know
    # their rosters. Recording them is what makes `len(season.teams)` honest,
    # and that count is buyer-visible: it is the denominator in "8 of the other
    # 11 teams can cover that". Leaving it at one would silently claim a
    # one-team league. They carry no roster and no name, because we know
    # neither and RULE B3 forbids inventing either.
    size = max(int(league_size), 1)
    result.teams = {SUBSCRIBER_ROSTER_ID: Team(SUBSCRIBER_ROSTER_ID, spec.label,
                                               spec.label, None)}
    for roster_id in range(2, size + 1):
        result.teams[roster_id] = Team(roster_id, "", "", None)
    return result


def rosterable_field(directory: PlayerDirectory,
                     prior_season: Mapping[int, Mapping[str, Mapping[str, object]]],
                     rule: ScoringRule, slots: Iterable[str],
                     league_size: int = 12) -> list[str]:
    """The players a league of this size would actually hold, per position.

    Selected on the PREVIOUS season's total production — out of sample with
    respect to anything we are predicting. Depth is starters plus a bench of the
    same size, which is roughly how real rosters carry each position: a 12-team
    league with one QB slot rosters about 24 quarterbacks.

    A player with no prior-season production is not excluded on purpose; he
    simply does not rank, which is the same thing a draft does to him.
    """
    from collections import defaultdict

    starters_at: dict[str, int] = defaultdict(int)
    for slot in slots:
        for position in FLEX_ELIGIBILITY.get(slot, frozenset({slot})):
            starters_at[position] += 1

    totals: dict[str, float] = defaultdict(float)
    for rows in prior_season.values():
        for player_id, row in rows.items():
            totals[player_id] += score(row, rule)

    by_position: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for player in directory.players:
        by_position[player.position].append(
            (totals.get(player.player_id, 0.0), player.player_id))

    field: list[str] = []
    for position, ranked in by_position.items():
        # Starters plus an equal bench. Two per league at minimum, so a
        # position nobody starts still contributes a usable prior.
        depth = max(starters_at.get(position, 1) * league_size * 2, 2)
        ranked.sort(key=lambda item: (-item[0], item[1]))
        field.extend(player_id for _points, player_id in ranked[:depth])
    return field


def _team_week(roster_id: int, week: int, player_ids: Iterable[str],
               rows: Mapping[str, Mapping[str, object]],
               rule: ScoringRule) -> TeamWeek:
    """One roster's week. RULE B1: no stat line means 0.0, never absent — and
    who APPEARED is carried explicitly rather than inferred from the score.

    Inferring it cost real accuracy: 15.2% of 2024 fantasy stat rows score
    exactly 0.00, so every one of those players was being counted as having
    missed the game. nflverse tells us directly whether a row exists, which
    Sleeper never could, and row-presence is unambiguous — the maximum any 2024
    player has is 17 REG rows in an 18-week season, with no duplicates.
    """
    ids = tuple(player_ids)
    points: dict[str, float] = {}
    appeared: set[str] = set()
    for player_id in ids:
        row = rows.get(player_id)
        if row is None:
            points[player_id] = DID_NOT_PLAY
            continue
        # A team defense is scored from its own team-week, never from a
        # player's stat line (RULE S4). score_defense returns None for a game
        # with no final score, which is an absence rather than a shutout.
        if player_id.startswith(f"{DEFENSE}-"):
            defense_points = score_defense(row, row.get("points_allowed"))
            if defense_points is None:
                points[player_id] = DID_NOT_PLAY
                continue
            points[player_id] = defense_points
        else:
            points[player_id] = score(row, rule)
        appeared.add(player_id)
    return TeamWeek(
        roster_id=roster_id,
        week=week,
        matchup_id=None,
        # RULE B3: we never saw their lineup, so nothing claims to know it.
        starters=(),
        starters_points=(),
        players=ids,
        players_points=points,
        points=0.0,
        appeared=frozenset(appeared),
    )


def merge_defenses(weekly: dict[int, dict[str, Mapping[str, object]]],
                   defenses: Mapping[int, Mapping[str, Mapping[str, object]]],
                   ) -> dict[int, dict[str, Mapping[str, object]]]:
    """Fold team-defense weeks into the player rows, keyed ``DEF-<abbr>``.

    One dict of weekly rows keeps ``_team_week`` simple and keeps the roster a
    flat list of ids — a defense is just another thing you can start, which is
    what it is to the subscriber.
    """
    for week, teams in defenses.items():
        target = weekly.setdefault(week, {})
        for abbr, row in teams.items():
            target[f"{DEFENSE}-{abbr}"] = row
    return weekly
