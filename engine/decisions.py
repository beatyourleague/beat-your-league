"""Reconstruct start/sit calls from history and grade them against real points.

The grading rules are frozen here, in code, before any results are looked at
(CLAUDE.md principle 2). They are not tuned after seeing the numbers.

    RULE 1  A call exists for a (roster, week, slot) when the slot has a real
            starter and at least one eligible bench player, and BOTH have at
            least MIN_GAMES_FOR_CALL prior appearances. Otherwise the engine
            declines — it does not publish a probability it cannot support.
    RULE 2  The alternative is the single highest-projected eligible bench
            player, ranked on expected points.
    RULE 3  Of those two, the engine recommends whichever is more likely to
            outscore the other, and confidence is that probability — so it is
            always >= 0.5. Recommending on *probability* rather than on
            expected points is deliberate: the two can disagree for a volatile
            player, and a recommendation carrying a published 49.9% would be
            advising a start the model expects to lose.
    RULE 4  HIT   = recommended's actual points > alternative's actual points.
            MISS  = recommended's actual points < alternative's.
            TIE   = exactly equal; excluded from hit rate, reported separately.
    RULE 5  Grading uses only ``players_points`` from the same cached matchup
            record, so a graded call is reproducible from data/raw/ forever.

One structural caveat, stated rather than buried: a single strong bench player
can be the best alternative at several slots in the same week (a bench RB is
eligible at RB, RB and both FLEXes). Those calls are correlated, not
independent. Duplicate (starter, alternative) pairs within one roster-week are
deduplicated to the earliest slot, but genuine correlation across *different*
starters facing the *same* alternative remains, and it widens the true
uncertainty beyond the binomial intervals in the calibration table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from engine.history import EMPTY_SLOT_IDS, PlayerIndex, Season, TeamWeek
from engine.projection import MIN_GAMES_FOR_CALL, ProjectionModel, probability_outscores

HIT = "hit"
MISS = "miss"
TIE = "tie"


@dataclass(frozen=True)
class StartSitCall:
    """One graded head-to-head: who the engine would have started, and whether
    that was right. Every field is derived from cached JSON."""

    season: str
    week: int
    roster_id: int
    slot: str
    slot_index: int

    started_id: str
    alternative_id: str
    recommended_id: str

    confidence: float
    projected_started: float
    projected_alternative: float

    actual_started: float
    actual_alternative: float

    outcome: str
    is_playoff_week: bool

    @property
    def agreed_with_manager(self) -> bool:
        """True when the engine would have made the same call the human did."""
        return self.recommended_id == self.started_id

    @property
    def benched_id(self) -> str:
        return self.alternative_id if self.agreed_with_manager else self.started_id

    @property
    def actual_recommended(self) -> float:
        return self.actual_started if self.agreed_with_manager else self.actual_alternative

    @property
    def actual_benched(self) -> float:
        return self.actual_alternative if self.agreed_with_manager else self.actual_started

    @property
    def margin(self) -> float:
        """Points the recommendation gained (positive) or cost (negative)."""
        return self.actual_recommended - self.actual_benched

    @property
    def both_scored(self) -> bool:
        """Both players registered points — neither was on a bye or inactive.

        A diagnostic split, not a filter on the headline: it is computed from
        outcomes, so it cannot be used to select calls up front.
        """
        return self.actual_started != 0.0 and self.actual_alternative != 0.0

    @property
    def manager_points_left_on_bench(self) -> float:
        """Points the manager lost by benching the better player, else 0."""
        started, alternative = self.actual_started, self.actual_alternative
        return max(alternative - started, 0.0)


def grade(actual_recommended: float, actual_alternative: float) -> str:
    """RULE 4, in one place so tests can pin it."""
    if actual_recommended > actual_alternative:
        return HIT
    if actual_recommended < actual_alternative:
        return MISS
    return TIE


def _eligible_bench(
    team_week: TeamWeek, slot: str, players: PlayerIndex
) -> list[str]:
    eligible = []
    for player_id in team_week.bench():
        info = players.get(player_id)
        if info is not None and info.eligible_for(slot):
            eligible.append(player_id)
    return eligible


def calls_for_team_week(
    season: Season,
    team_week: TeamWeek,
    model: ProjectionModel,
    players: PlayerIndex,
    min_games: int = MIN_GAMES_FOR_CALL,
) -> Iterator[StartSitCall]:
    """Generate every gradeable start/sit call for one roster-week."""
    slots = season.starting_slots
    playoff_start = season.playoff_week_start
    is_playoff = playoff_start is not None and team_week.week >= playoff_start
    seen_pairs: set[tuple[str, str]] = set()

    for slot_index, slot in enumerate(slots):
        if slot_index >= len(team_week.starters):
            break
        started_id = team_week.starters[slot_index]
        if started_id in EMPTY_SLOT_IDS:
            continue

        started_actual = team_week.actual_points(started_id)
        if started_actual is None:
            continue  # no scoring record: not gradeable, so not graded
        started_projection = model.project(started_id, team_week.week)
        if started_projection is None or started_projection.games < min_games:
            continue

        best_id = None
        best_projection = None
        for candidate_id in _eligible_bench(team_week, slot, players):
            candidate_actual = team_week.actual_points(candidate_id)
            if candidate_actual is None:
                continue
            projection = model.project(candidate_id, team_week.week)
            if projection is None or projection.games < min_games:
                continue
            if best_projection is None or projection.mean > best_projection.mean:
                best_id, best_projection = candidate_id, projection
        if best_id is None or best_projection is None:
            continue

        pair = tuple(sorted((started_id, best_id)))
        if pair in seen_pairs:
            continue  # same head-to-head already graded at an earlier slot
        seen_pairs.add(pair)

        alternative_actual = team_week.actual_points(best_id)
        assert alternative_actual is not None  # guarded above

        # RULE 3: decide on the probability we publish, not on expected points.
        # The two are complementary by construction, so 1 - p is exact.
        starter_wins = probability_outscores(started_projection, best_projection)
        if starter_wins >= 0.5:
            recommended_id = started_id
            confidence = starter_wins
            actual_recommended, actual_other = started_actual, alternative_actual
        else:
            recommended_id = best_id
            confidence = 1.0 - starter_wins
            actual_recommended, actual_other = alternative_actual, started_actual

        yield StartSitCall(
            season=season.season,
            week=team_week.week,
            roster_id=team_week.roster_id,
            slot=slot,
            slot_index=slot_index,
            started_id=started_id,
            alternative_id=best_id,
            recommended_id=recommended_id,
            confidence=confidence,
            projected_started=started_projection.mean,
            projected_alternative=best_projection.mean,
            actual_started=started_actual,
            actual_alternative=alternative_actual,
            outcome=grade(actual_recommended, actual_other),
            is_playoff_week=is_playoff,
        )


def all_calls(
    season: Season,
    model: ProjectionModel,
    players: PlayerIndex,
    min_games: int = MIN_GAMES_FOR_CALL,
) -> list[StartSitCall]:
    """Every gradeable call across a whole season, week and roster ascending."""
    calls: list[StartSitCall] = []
    for team_week in season.team_weeks():
        calls.extend(
            calls_for_team_week(season, team_week, model, players, min_games=min_games)
        )
    return calls


# --------------------------------------------------------------------- #
# summaries over a set of calls
# --------------------------------------------------------------------- #

@dataclass(frozen=True)
class CallSummary:
    graded: int
    hits: int
    misses: int
    ties: int

    @property
    def decided(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.decided if self.decided else None


def summarize(calls: Iterable[StartSitCall]) -> CallSummary:
    calls = list(calls)
    return CallSummary(
        graded=len(calls),
        hits=sum(1 for c in calls if c.outcome == HIT),
        misses=sum(1 for c in calls if c.outcome == MISS),
        ties=sum(1 for c in calls if c.outcome == TIE),
    )


def coin_flips(calls: Sequence[StartSitCall], ceiling: float = 0.60) -> list[StartSitCall]:
    """The genuinely close calls — the product's "Regret Score" territory."""
    return [c for c in calls if c.confidence < ceiling]


def disagreements(calls: Sequence[StartSitCall]) -> list[StartSitCall]:
    """Calls where the engine would have overruled the human manager."""
    return [c for c in calls if not c.agreed_with_manager]
