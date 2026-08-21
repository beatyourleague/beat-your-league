"""Tests for the adapter that feeds the engine a typed roster.

The engine is unchanged; this module supplies its inputs. So the properties
here are about what the engine is entitled to ASSUME — that a zero means "did
not play", that a player is counted once, and that nothing claims to know a
lineup we never saw.
"""

from __future__ import annotations

import pytest

from engine.history import Season
from engine.projection import ProjectionModel
from engine.roster import Player, PlayerDirectory
from engine.scoring import preset
from engine.subscriber import (DID_NOT_PLAY, FIELD_ROSTER_ID,
                               SUBSCRIBER_ROSTER_ID, RosterSpec,
                               SubscriberError, build_season, is_scoreable,
                               player_index, rosterable_field)

SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")


def _directory() -> PlayerDirectory:
    people = [
        Player("00-0000001", "Star QB", "QB", "BUF"),
        Player("00-0000002", "Backup QB", "QB", "NYJ"),
        Player("00-0000003", "Bell Cow", "RB", "ATL"),
        Player("00-0000004", "Committee RB", "RB", "LA"),
        Player("00-0000005", "Alpha WR", "WR", "CIN"),
        Player("00-0000006", "Slot WR", "WR", "DET"),
        Player("00-0000007", "Starting TE", "TE", "ARI"),
        Player("00-0000008", "Blocking TE", "TE", "SF"),
        Player("00-0000009", "Fullback", "FB", "SF"),
        Player("DEF-BAL", "Baltimore Ravens", "DEF", "BAL"),
    ]
    return PlayerDirectory(people)


def _rows(**points: float) -> dict:
    """A week of stat lines, expressed as receiving yards for simplicity."""
    return {pid: {"receiving_yards": yards * 10} for pid, yards in points.items()}


def _spec(**over) -> RosterSpec:
    base = dict(player_ids=("00-0000001", "00-0000003", "00-0000004",
                            "00-0000005", "00-0000006", "00-0000007",
                            "00-0000008"),
                slots=SLOTS, scoring="ppr")
    base.update(over)
    return RosterSpec(**base)


# --------------------------------------------------------------------- #
# RULE B1 — a week with no stat line is 0.0
# --------------------------------------------------------------------- #

def test_a_missing_stat_line_is_a_zero_not_an_absence() -> None:
    """The whole calibration story rests on this. Sleeper reported a player who
    did not play as exactly 0.0, which is what told us starters score zero 3% of
    the time and bench players 35% — the availability asymmetry. A missing KEY
    instead of a zero makes every player look like he appears whenever he plays,
    and that finding disappears silently."""
    weekly = {1: _rows(**{"00-0000001": 2.0})}   # only one player has a line
    season = build_season(_spec(), weekly, _directory(), "2026", 2)
    week = season.weeks[1][SUBSCRIBER_ROSTER_ID]
    assert week.players_points["00-0000003"] == DID_NOT_PLAY
    assert "00-0000003" in week.players_points, "an absent week became an absent key"
    assert week.actual_points("00-0000003") == 0.0


def test_the_model_treats_those_zeros_as_missed_opportunities() -> None:
    """The engine's own semantics, end to end: a zero is rostered-but-absent, so
    it counts against appearance rate without polluting the scoring mean."""
    weekly = {1: _rows(**{"00-0000001": 2.0}), 2: {}, 3: _rows(**{"00-0000001": 3.0})}
    directory = _directory()
    season = build_season(_spec(), weekly, directory, "2026", 4)
    model = ProjectionModel(season, player_index(directory))
    assert model.rostered_weeks("00-0000001", 4) == 3
    # _rows takes points and writes them as yards, so 2.0 -> 20 yards -> 2.0 PPR
    assert model.observations("00-0000001", 4) == [2.0, 3.0]   # week 2 excluded


# --------------------------------------------------------------------- #
# RULE B2 — the field, and who is counted
# --------------------------------------------------------------------- #

def test_a_rostered_player_is_counted_exactly_once() -> None:
    """FOUND BY READING A REAL RUN: with the field including the subscriber's
    own players, every one of them appeared in two TeamWeeks per week and the
    model reported "18 games of form" over a nine-week season. Not cosmetic —
    MIN_GAMES_FOR_CALL is an evidence gate, so two real appearances would show
    as four and become publishable, and the doubled sample would shrink the
    standard deviation into false confidence."""
    directory = _directory()
    weekly = {w: _rows(**{"00-0000001": 2.0}) for w in (1, 2, 3)}
    field = [p.player_id for p in directory.players]
    season = build_season(_spec(), weekly, directory, "2026", 4, field=field)
    model = ProjectionModel(season, player_index(directory))
    projection = model.project("00-0000001", 4)
    assert projection is not None and projection.games == 3, \
        f"{projection.games} appearances over 3 weeks — the player was double-counted"


def test_the_field_never_reaches_a_buyer_visible_count() -> None:
    """`len(season.teams)` is the denominator in "8 of the other 11 teams can
    cover that". The field lives in `weeks` so the model sees it, and stays out
    of `teams` so the copy does not."""
    directory = _directory()
    field = [p.player_id for p in directory.players]
    season = build_season(_spec(), {}, directory, "2026", 3, league_size=12,
                          field=field)
    assert len(season.teams) == 12
    assert FIELD_ROSTER_ID not in season.teams
    assert FIELD_ROSTER_ID in season.weeks[1], "the model cannot see the field"


def test_the_league_size_the_subscriber_gave_us_is_the_one_used() -> None:
    for size in (8, 10, 12, 14):
        season = build_season(_spec(), {}, _directory(), "2026", 2,
                              league_size=size)
        assert len(season.teams) == size


def test_the_field_is_sized_from_the_lineup_and_selected_out_of_sample() -> None:
    """Selecting on THIS season's production would select on the outcome being
    predicted and inflate the appearance rate — the exact quantity the
    availability gate depends on. So the ranking comes from last season."""
    directory = _directory()
    prior = {1: _rows(**{"00-0000002": 9.0, "00-0000001": 1.0})}   # backup outscored
    field = rosterable_field(directory, prior, preset("ppr"), ("QB",), league_size=1)
    # Every position gets SOME depth so its prior is usable, but the QB depth
    # is what the lineup sizes: one slot, one team, starters + equal bench = 2.
    quarterbacks = [pid for pid in field if pid in ("00-0000001", "00-0000002")]
    assert quarterbacks == ["00-0000002", "00-0000001"], \
        "the field is not ranked by prior-season production"


def test_flex_slots_widen_the_field_for_every_eligible_position() -> None:
    """A FLEX is a starting spot for RB, WR and TE, so all three need the depth
    that implies — otherwise the prior for a position is built from too few
    players in exactly the leagues that start the most of them."""
    directory = _directory()
    narrow = rosterable_field(directory, {}, preset("ppr"), ("RB",), league_size=1)
    wide = rosterable_field(directory, {}, preset("ppr"), ("RB", "FLEX"),
                            league_size=1)
    assert len(wide) >= len(narrow)


# --------------------------------------------------------------------- #
# RULE B3 — we do not know what they started
# --------------------------------------------------------------------- #

def test_nothing_claims_to_know_a_lineup_we_never_saw() -> None:
    """We never read their league, so past starters are unknown. Inventing them
    — even as "probably the best players" — would let the report grade decisions
    the subscriber never made."""
    weekly = {1: _rows(**{"00-0000001": 2.0})}
    season = build_season(_spec(), weekly, _directory(), "2026", 2)
    week = season.weeks[1][SUBSCRIBER_ROSTER_ID]
    assert week.starters == () and week.starters_points == ()
    assert week.bench() == week.players, "an empty lineup implied a bench"


# --------------------------------------------------------------------- #
# the spec itself
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("bad,reason", [
    (dict(player_ids=()), "empty roster"),
    (dict(player_ids=("00-0000001", "00-0000001")), "duplicate"),
    (dict(slots=()), "no slots"),
    (dict(player_ids=("00-0000001",)), "fewer players than slots"),
])
def test_an_unusable_roster_is_refused_at_construction(bad: dict, reason: str) -> None:
    with pytest.raises(SubscriberError):
        _spec(**bad)


def test_an_unknown_scoring_is_refused_before_any_number_is_computed() -> None:
    from engine.scoring import ScoringError
    with pytest.raises(ScoringError):
        _spec(scoring="dynasty-superflex").rule


def test_week_zero_is_not_a_week() -> None:
    with pytest.raises(SubscriberError):
        build_season(_spec(), {}, _directory(), "2026", 0)


# --------------------------------------------------------------------- #
# the player index
# --------------------------------------------------------------------- #

def test_a_fullback_can_fill_the_slot_leagues_actually_give_him() -> None:
    """Listing FB alone makes a real rostered player ineligible for the only
    slot he can occupy."""
    index = player_index(_directory())
    fullback = index.get("00-0000009")
    assert fullback is not None and fullback.eligible_for("RB")
    assert fullback.eligible_for("FLEX")


def test_defenses_are_marked_unscoreable_rather_than_scored_as_zero() -> None:
    """DST needs points and yards allowed from the team release. A 0.0 would
    look like a real week of no production."""
    assert not is_scoreable("DEF-BAL")
    assert is_scoreable("00-0000001")


def test_positions_survive_into_slot_eligibility() -> None:
    index = player_index(_directory())
    assert index.get("00-0000005").eligible_for("WR")
    assert index.get("00-0000005").eligible_for("FLEX")
    assert not index.get("00-0000005").eligible_for("QB")
