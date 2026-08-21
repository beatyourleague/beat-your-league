"""Fantasy points from a stat line, under the subscriber's own scoring.

WHY THIS EXISTS. The product used to read points straight from the league —
Sleeper had already scored every player under that league's settings. We no
longer read the league (PLAN §0), so we compute points ourselves from nflverse
stat lines. That makes this module the base of everything numeric downstream: a
systematic error here does not surface as a crash, it surfaces as a projection
model that is confidently wrong about every player, every week.

**RULE S1 — COMPUTE FROM STAT LINES, NEVER FROM A PRE-BAKED TOTAL.** nflverse
ships ``fantasy_points`` and ``fantasy_points_ppr``. Both are ONE league's
settings, and the subscriber's league is not that league — half-PPR, six-point
passing touchdowns and per-first-down scoring are all common. CLAUDE.md froze
this rule for the Sleeper projections feed and it survives the move unchanged.

**RULE S2 — THE PRE-BAKED TOTAL IS A TEST ORACLE, NOT AN INPUT.** What
``fantasy_points_ppr`` IS good for is checking our arithmetic: our PPR preset
should reproduce it. ``test_scoring`` diffs the two across a full real season,
which is how a dropped term or a wrong coefficient gets caught immediately
rather than after the first subscriber report.

**RULE S3 — AN ABSENT STAT IS ZERO, BUT AN ABSENT PLAYER IS NOT A ZERO SCORE.**
Inside a stat line a missing field means the player did not do that thing, so it
contributes nothing. A player with no stat line at all is a different fact — he
did not play, or nflverse has no row — and that is the caller's business
(``engine.availability``), not a 0.0 we invent here.

**RULE S4 — A TEAM DEFENSE IS SCORED FROM THE TEAM'S OWN WEEK, NEVER FROM A
DEFENDER'S LINE.** DST needs points allowed (the opponent's final score) and
counts that only exist team-wide: sacks, takeaways, safeties, defensive and
return touchdowns. Summing a linebacker's tackles would be a fabricated number
wearing a real column's name. Points allowed come from the schedule's own
score, so a defense cannot be scored for a game that has not finished.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# The three presets the signup ref can encode (run/refs.py SCORING). They differ
# only in the reception term, which is the axis leagues actually vary.
PPR = "ppr"
HALF_PPR = "half_ppr"
STANDARD = "standard"


@dataclass(frozen=True)
class ScoringRule:
    """Points per unit. Named fields rather than a loose dict so a typo is an
    error at construction instead of a silently ignored scoring term."""

    reception: float = 0.0
    passing_yards: float = 0.04          # a point per 25
    passing_td: float = 4.0
    passing_interception: float = -2.0
    passing_2pt: float = 2.0
    rushing_yards: float = 0.1           # a point per 10
    rushing_td: float = 6.0
    rushing_2pt: float = 2.0
    receiving_yards: float = 0.1
    receiving_td: float = 6.0
    receiving_2pt: float = 2.0
    fumble_lost: float = -2.0
    special_teams_td: float = 6.0
    # Kickers. Distance buckets because that is how leagues actually score them;
    # a flat per-make value is expressible by setting them all equal.
    fg_0_19: float = 3.0
    fg_20_29: float = 3.0
    fg_30_39: float = 3.0
    fg_40_49: float = 4.0
    fg_50_plus: float = 5.0
    fg_missed: float = 0.0
    extra_point: float = 1.0

    def with_reception(self, value: float) -> "ScoringRule":
        return ScoringRule(**{**self.__dict__, "reception": value})


# The points-allowed ladder every mainstream ruleset uses, as (max_points,
# value) in ascending order. Expressed as data rather than branches because
# leagues vary the bands and a league that does is then expressible without
# touching this module.
DEFAULT_POINTS_ALLOWED = ((0, 10.0), (6, 7.0), (13, 4.0), (20, 1.0),
                          (27, 0.0), (34, -1.0), (99, -4.0))


@dataclass(frozen=True)
class DefenseRule:
    """Points per unit for a team defense."""

    sack: float = 1.0
    interception: float = 2.0
    fumble_recovery: float = 2.0
    safety: float = 2.0
    defensive_td: float = 6.0
    return_td: float = 6.0
    points_allowed: tuple[tuple[int, float], ...] = DEFAULT_POINTS_ALLOWED


DEFENSE_RULE = DefenseRule()


PRESETS: Mapping[str, ScoringRule] = {
    PPR: ScoringRule(reception=1.0),
    HALF_PPR: ScoringRule(reception=0.5),
    STANDARD: ScoringRule(reception=0.0),
}


class ScoringError(ValueError):
    """A scoring name we do not recognise."""


def preset(name: str) -> ScoringRule:
    """Look up one of the three presets the signup flow can express."""
    try:
        return PRESETS[name]
    except KeyError:
        raise ScoringError(
            f"unknown scoring {name!r} — expected one of {sorted(PRESETS)}") from None


def _num(row: Mapping[str, object], key: str) -> float:
    """One stat, as a number. RULE S3: absent means the player did not do it."""
    value = row.get(key)
    if value is None or value == "" or value == "NA":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def score(row: Mapping[str, object], rule: ScoringRule) -> float:
    """Fantasy points for one player-week under one league's scoring.

    ``row`` is an nflverse ``stats_player_week`` record (or any mapping with the
    same keys). Rounded to two places, which is finer than any league displays
    and coarse enough that float noise never shows up as a 0.01 difference
    between two runs.
    """
    total = (
        _num(row, "receptions") * rule.reception
        + _num(row, "passing_yards") * rule.passing_yards
        + _num(row, "passing_tds") * rule.passing_td
        + _num(row, "passing_interceptions") * rule.passing_interception
        + _num(row, "passing_2pt_conversions") * rule.passing_2pt
        + _num(row, "rushing_yards") * rule.rushing_yards
        + _num(row, "rushing_tds") * rule.rushing_td
        + _num(row, "rushing_2pt_conversions") * rule.rushing_2pt
        + _num(row, "receiving_yards") * rule.receiving_yards
        + _num(row, "receiving_tds") * rule.receiving_td
        + _num(row, "receiving_2pt_conversions") * rule.receiving_2pt
        + _num(row, "special_teams_tds") * rule.special_teams_td
    )
    # Fumbles LOST, not fumbles. A fumble the offense recovers costs a league
    # nothing, and summing `fumbles_total` would penalise players for plays
    # their own team kept.
    total += (_num(row, "sack_fumbles_lost")
              + _num(row, "rushing_fumbles_lost")
              + _num(row, "receiving_fumbles_lost")) * rule.fumble_lost
    total += _kicking(row, rule)
    return round(total, 2)


def _kicking(row: Mapping[str, object], rule: ScoringRule) -> float:
    """Kicker scoring, by distance bucket.

    nflverse splits made field goals into explicit ranges, so distance scoring
    needs no play-by-play. The 60+ bucket rides with 50+ because no common
    ruleset separates them and inventing a tier would be a number we made up.
    """
    return (
        _num(row, "fg_made_0_19") * rule.fg_0_19
        + _num(row, "fg_made_20_29") * rule.fg_20_29
        + _num(row, "fg_made_30_39") * rule.fg_30_39
        + _num(row, "fg_made_40_49") * rule.fg_40_49
        + (_num(row, "fg_made_50_59") + _num(row, "fg_made_60_")) * rule.fg_50_plus
        + _num(row, "fg_missed") * rule.fg_missed
        + _num(row, "pat_made") * rule.extra_point
    )


def score_defense(team_week: Mapping[str, object], points_allowed: int | None,
                  rule: DefenseRule = DEFENSE_RULE) -> float | None:
    """Fantasy points for one team defense in one week (RULE S4).

    Returns None when ``points_allowed`` is unknown — an unplayed or unfinished
    game. That is not a zero: a defense that has not played yet has no score,
    and rendering 0.0 would read as a shutout's opposite, which is the single
    most misleading number this function could produce.
    """
    if points_allowed is None:
        return None
    total = (
        _num(team_week, "def_sacks") * rule.sack
        + _num(team_week, "def_interceptions") * rule.interception
        + _num(team_week, "def_fumbles") * rule.fumble_recovery
        + _num(team_week, "def_safeties") * rule.safety
        + _num(team_week, "def_tds") * rule.defensive_td
        + _num(team_week, "special_teams_tds") * rule.return_td
    )
    for ceiling, value in rule.points_allowed:
        if points_allowed <= ceiling:
            total += value
            break
    return round(total, 2)
