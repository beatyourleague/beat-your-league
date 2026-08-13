"""Backtest the MATCHUP-level method: team win probability and floor/ceiling.

The Phase 3 report publishes P(my total beats the rival's total) and an 80%
projection band per team. Principle 1 says those numbers may only ship if the
method behind them survives a backtest — this module is that backtest, graded
on the same frozen rules everywhere else uses.

    RULE M1  A matchup is graded when, for BOTH teams, every non-empty starter
             slot has a projection buildable from weeks strictly before the
             graded week. Otherwise the matchup is skipped and counted.
             A matchup where both actual totals are exactly 0.0 is not a game
             that ended 0-0 (impossible in fantasy) — it is a week that has
             not been played, and it is skipped, never graded as a tie.
    RULE M2  Confidence = P(favorite's total > underdog's total), totals
             modelled as independent normals (sum of starter means/variances) —
             exactly the arithmetic ``engine.week_report.win_probability`` uses.
    RULE M3  HIT = the favorite won on actual points; MISS = lost; TIE =
             exactly level, excluded from hit rates, reported separately.
    RULE M4  The 80% band is mean +/- 1.2816 sd per team; coverage counts each
             team-week whose actual total landed inside its own band. A
             calibrated band covers ~80%.

Grading uses the teams' ACTUAL set lineups, so the backtest measures the
published quantity ("beats their set total"), not a hypothetical optimum.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from engine.decisions import HIT, MISS, TIE
from engine.history import EMPTY_SLOT_IDS, Season, TeamWeek
from engine.projection import ProjectionModel, _normal_beats

Z_80_BAND = 1.2816


@dataclass(frozen=True)
class TeamForecast:
    roster_id: int
    mean: float
    sd: float
    actual: float

    @property
    def band_low(self) -> float:
        return self.mean - Z_80_BAND * self.sd

    @property
    def band_high(self) -> float:
        return self.mean + Z_80_BAND * self.sd

    @property
    def in_band(self) -> bool:
        return self.band_low <= self.actual <= self.band_high


@dataclass(frozen=True)
class MatchupCall:
    """One graded matchup prediction. ``confidence``/``outcome`` are duck-type
    compatible with ``engine.calibration``'s bucket machinery."""

    season: str
    week: int
    favorite: TeamForecast
    underdog: TeamForecast
    confidence: float

    @property
    def outcome(self) -> str:
        if self.favorite.actual > self.underdog.actual:
            return HIT
        if self.favorite.actual < self.underdog.actual:
            return MISS
        return TIE

    @property
    def teams(self) -> tuple[TeamForecast, TeamForecast]:
        return self.favorite, self.underdog


def _forecast(team_week: TeamWeek, model: ProjectionModel) -> TeamForecast | None:
    """RULE M1: every non-empty starter needs a projection, or no forecast."""
    mean = 0.0
    variance = 0.0
    for starter in team_week.starters:
        if starter in EMPTY_SLOT_IDS:
            continue
        projection = model.project(starter, team_week.week)
        if projection is None:
            return None
        mean += projection.mean
        variance += projection.sd ** 2
    return TeamForecast(
        roster_id=team_week.roster_id,
        mean=mean,
        sd=math.sqrt(variance),
        actual=team_week.points,
    )


def matchup_calls(season: Season, model: ProjectionModel) -> tuple[list[MatchupCall], int]:
    """All gradeable matchup predictions for a season, plus the skipped count."""
    calls: list[MatchupCall] = []
    skipped = 0
    for week in season.graded_weeks:
        by_matchup: dict[int, list[TeamWeek]] = {}
        for team_week in season.weeks[week].values():
            if team_week.matchup_id is not None:
                by_matchup.setdefault(team_week.matchup_id, []).append(team_week)
        for pair in by_matchup.values():
            if len(pair) != 2:
                continue  # bye or malformed pairing: nothing to predict
            if pair[0].points == 0.0 and pair[1].points == 0.0:
                continue  # RULE M1: an unplayed week, not a 0-0 result
            forecast_a = _forecast(pair[0], model)
            forecast_b = _forecast(pair[1], model)
            if forecast_a is None or forecast_b is None:
                skipped += 1
                continue
            p_a = _normal_beats(forecast_a.mean, forecast_a.sd,
                                forecast_b.mean, forecast_b.sd)
            if p_a >= 0.5:
                favorite, underdog, confidence = forecast_a, forecast_b, p_a
            else:
                favorite, underdog, confidence = forecast_b, forecast_a, 1.0 - p_a
            calls.append(MatchupCall(
                season=season.season, week=week,
                favorite=favorite, underdog=underdog, confidence=confidence,
            ))
    return calls, skipped


def band_coverage(calls: Sequence[MatchupCall]) -> tuple[int, int]:
    """(team-weeks inside their 80% band, total team-weeks). Expect ~80%."""
    covered = 0
    total = 0
    for call in calls:
        for team in call.teams:
            total += 1
            if team.in_band:
                covered += 1
    return covered, total
