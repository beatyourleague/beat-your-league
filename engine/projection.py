"""Ex-ante player projections and the probability model behind "confidence".

The one rule that makes a backtest worth anything: a projection for week W may
only use data from weeks strictly before W. Every lookup here takes a
``before_week`` and filters on it, so lookahead bias can't creep in through a
convenience path. ``tests/test_engine.py`` asserts this directly.

Model (v0.2, deliberately simple so it is fully backtestable per principle 1).
A player's week is modelled as two things, because they fail independently:

    availability   p = (appearances + K * position_rate) / (rostered_weeks + K)
    scoring form   mean = (n * player_mean + K * position_mean) / (n + K)

Form is a trailing average shrunk toward the league-wide positional mean, fitted
on weeks the player actually appeared. Availability is the beta-binomial rate at
which they appear at all. Expected points is the product.

Splitting them matters. The v0.1 model projected form alone and was punished for
it: when it overruled a human manager it hit 21%, because a manager benches a
player precisely *when they know he will not play*, so "best projected bench
player" is systematically enriched for players about to score zero. Modelling
availability lets the engine see some of what the manager sees.

Known remaining gap, stated rather than hidden: availability here is inferred
from appearance history, which catches lingering injuries but cannot catch a bye
week — a player on bye played last week and will play next week, so nothing in
cached league data flags it in advance. That needs the NFL schedule, which is
free and public; until it is wired in, the backtest reports the residual as the
gap between its all-calls and both-players-scored rows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from engine.history import PlayerIndex, Season

# Shrinkage weight, in "pseudo-games" of positional prior. K=4 means a player
# with 4 games is weighted 50/50 against their position's average.
DEFAULT_SHRINKAGE_K = 4.0

# Below this many prior appearances the engine has no real opinion, so it
# declines to make a call rather than dressing up a guess as a probability.
MIN_GAMES_FOR_CALL = 3

# Floor on the standard deviation so a freak low-variance sample can't produce
# a 99.9% confidence out of three data points.
MIN_SD = 2.0

# Sleeper reports a player who did not play as exactly 0.0. Real PPR scoring
# almost never lands on exactly 0.0 for a player who took snaps (any reception
# or yard is fractional), so 0.0 is treated as "did not appear" and excluded
# from form. Measured on the sample league: ~20% of RB/WR player-weeks. This is
# an approximation, and the backtest report says so.
DID_NOT_PLAY = 0.0

# Fallback appearance rate for the very first weeks, before the league has
# produced enough player-weeks to measure a positional rate. Roughly the
# observed league-wide rate (~80%) rather than an optimistic 1.0.
DEFAULT_APPEARANCE_RATE = 0.80


def normal_cdf(z: float) -> float:
    """Standard normal CDF via erf — avoids a scipy dependency."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


@dataclass(frozen=True)
class Projection:
    """A projection made with data available before ``as_of_week``.

    ``active_mean``/``active_sd`` describe the player's scoring *when he plays*;
    ``appear_probability`` is how likely he plays at all. ``mean`` is the
    expected points that fall out of the two, and is what the engine ranks on.
    """

    player_id: str
    as_of_week: int
    active_mean: float
    active_sd: float
    appear_probability: float
    games: int
    rostered_weeks: int
    position: str

    @property
    def mean(self) -> float:
        """Expected fantasy points, availability included."""
        return self.appear_probability * self.active_mean

    @property
    def sd(self) -> float:
        """Standard deviation of the availability/form mixture.

        Var = E[Var | state] + Var[E | state] — the second term is the swing
        between playing and not playing, which is why a questionable player is
        volatile even when his form is steady.
        """
        p = self.appear_probability
        within = p * self.active_sd ** 2
        between = p * (1 - p) * self.active_mean ** 2
        return max(math.sqrt(max(within + between, 0.0)), MIN_SD)

    @property
    def confident_enough(self) -> bool:
        return self.games >= MIN_GAMES_FOR_CALL


@dataclass(frozen=True)
class PositionPrior:
    position: str
    mean: float
    variance: float
    samples: int
    appearance_rate: float = DEFAULT_APPEARANCE_RATE


def probability_outscores(a: Projection, b: Projection) -> float:
    """P(a outscores b | they do not tie) — the published confidence number.

    This is the unit the product commits to (CLAUDE.md principle 5): the
    probability this start outscores the *specific* bench alternative at that
    slot, under this model.

    Both players are a mixture of "plays" and "does not play", so the
    probability decomposes into the four states:

        both play        P(N_a > N_b)   for independent normals
        only a plays     P(N_a > 0)
        only b plays     P(0 > N_b)
        neither plays    a 0-0 tie

    The last state is a tie, and ties are excluded from grading (RULE 4), so
    the result is conditioned on a decision actually happening. Without that
    conditioning the engine would quietly report a bye-week stalemate as
    near-certainty for whichever player it happened to prefer.

    Independence is an approximation — teammates and players in the same game
    are correlated — and it is listed as a limitation in the backtest report.
    """
    pa, pb = a.appear_probability, b.appear_probability

    both = _normal_beats(a.active_mean, a.active_sd, b.active_mean, b.active_sd)
    a_only = _normal_beats(a.active_mean, a.active_sd, 0.0, 0.0)
    b_only = 1.0 - _normal_beats(b.active_mean, b.active_sd, 0.0, 0.0)

    a_wins = pa * pb * both + pa * (1 - pb) * a_only + (1 - pa) * pb * b_only
    tie_mass = (1 - pa) * (1 - pb)
    if tie_mass >= 1.0:
        return 0.5
    return min(1.0, max(0.0, a_wins / (1.0 - tie_mass)))


def _normal_beats(mean_a: float, sd_a: float, mean_b: float, sd_b: float) -> float:
    spread = math.sqrt(sd_a ** 2 + sd_b ** 2)
    if spread <= 0:
        return 0.5 if mean_a == mean_b else (1.0 if mean_a > mean_b else 0.0)
    return normal_cdf((mean_a - mean_b) / spread)


def _mean_and_variance(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n == 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, variance


class ProjectionModel:
    """Trailing-form projections for one league-season.

    Built once per season; every query is filtered to weeks before the target,
    so the same model can serve week 5 and week 14 without contamination.
    """

    def __init__(
        self,
        season: Season,
        players: PlayerIndex,
        shrinkage_k: float = DEFAULT_SHRINKAGE_K,
    ) -> None:
        self.season = season
        self.players = players
        self.shrinkage_k = shrinkage_k
        # player_id -> [(week, points), ...] ascending, appearances only.
        self._appearances: dict[str, list[tuple[int, float]]] = {}
        # player_id -> sorted weeks the player was on someone's roster. A week
        # a player spent in free agency is not a missed game, so it must not
        # count against his availability.
        self._rostered: dict[str, list[int]] = {}
        # player_id -> position, resolved once.
        self._position: dict[str, str] = {}
        self._prior_cache: dict[tuple[str, int], PositionPrior] = {}
        self._ingest(season)

    def _ingest(self, season: Season) -> None:
        rostered: dict[str, set[int]] = {}
        for team_week in season.team_weeks():
            for player_id, points in team_week.players_points.items():
                rostered.setdefault(player_id, set()).add(team_week.week)
                # Appearance is asked of the TeamWeek rather than inferred from
                # the score here, because a player who took the field and
                # scored nothing is not the same fact as one who never played —
                # see TeamWeek.did_appear for the measurement.
                if not team_week.did_appear(player_id):
                    continue
                self._appearances.setdefault(player_id, []).append(
                    (team_week.week, float(points))
                )
        for entries in self._appearances.values():
            entries.sort()
        self._rostered = {pid: sorted(weeks) for pid, weeks in rostered.items()}

    def position_of(self, player_id: str) -> str:
        cached = self._position.get(player_id)
        if cached is None:
            cached = self.players.position(player_id)
            self._position[player_id] = cached
        return cached

    def observations(self, player_id: str, before_week: int) -> list[float]:
        """Appearance points from weeks strictly before ``before_week``."""
        return [
            points
            for week, points in self._appearances.get(player_id, ())
            if week < before_week
        ]

    def rostered_weeks(self, player_id: str, before_week: int) -> int:
        """Weeks before ``before_week`` the player was on a roster — his
        opportunities to appear."""
        return sum(1 for week in self._rostered.get(player_id, ()) if week < before_week)

    def position_prior(self, position: str, before_week: int) -> PositionPrior:
        """League-wide scoring and appearance rate for a position, from weeks
        before ``before_week``."""
        key = (position, before_week)
        cached = self._prior_cache.get(key)
        if cached is not None:
            return cached
        values: list[float] = []
        opportunities = 0
        appearances = 0
        for player_id, weeks in self._rostered.items():
            if self.position_of(player_id) != position:
                continue
            opportunities += sum(1 for week in weeks if week < before_week)
            appearances += sum(
                1 for week, _ in self._appearances.get(player_id, ()) if week < before_week
            )
            values.extend(
                points
                for week, points in self._appearances.get(player_id, ())
                if week < before_week
            )
        mean, variance = _mean_and_variance(values)
        prior = PositionPrior(
            position=position,
            mean=mean,
            variance=variance,
            samples=len(values),
            appearance_rate=(
                appearances / opportunities if opportunities else DEFAULT_APPEARANCE_RATE
            ),
        )
        self._prior_cache[key] = prior
        return prior

    def project(self, player_id: str, week: int) -> Projection | None:
        """Project ``player_id`` for ``week`` using only weeks < ``week``.

        Returns None when there is nothing at all to go on — no appearances and
        no positional prior — so callers skip rather than invent.
        """
        position = self.position_of(player_id)
        values = self.observations(player_id, week)
        prior = self.position_prior(position, week)
        n = len(values)
        if n == 0 and prior.samples == 0:
            return None

        player_mean, player_variance = _mean_and_variance(values)
        k = self.shrinkage_k
        if prior.samples == 0:
            mean, variance = player_mean, player_variance
        else:
            mean = (n * player_mean + k * prior.mean) / (n + k)
            variance = (n * player_variance + k * prior.variance) / (n + k)
        sd = max(math.sqrt(max(variance, 0.0)), MIN_SD)

        # Availability: beta-binomial appearance rate, shrunk toward the
        # position's rate with the same K. Opportunities are weeks the player
        # was rostered, so time spent in free agency is not held against him.
        opportunities = self.rostered_weeks(player_id, week)
        appear = (n + k * prior.appearance_rate) / (opportunities + k) if opportunities + k else prior.appearance_rate
        return Projection(
            player_id=player_id,
            as_of_week=week,
            active_mean=mean,
            active_sd=sd,
            appear_probability=min(1.0, max(0.0, appear)),
            games=n,
            rostered_weeks=opportunities,
            position=position,
        )

    def project_many(
        self, player_ids: Iterable[str], week: int
    ) -> Mapping[str, Projection]:
        projections: dict[str, Projection] = {}
        for player_id in player_ids:
            projection = self.project(player_id, week)
            if projection is not None:
                projections[player_id] = projection
        return projections
