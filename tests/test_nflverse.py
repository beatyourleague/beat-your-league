"""Tests for the commercially-licensed data source.

This module exists because Sleeper's terms forbid the product's original data
route (PLAN §0), so these tests guard the properties that make the replacement
*usable*: the licence obligation we must ship, the absence semantics that keep
principle 3 intact, and the outage behaviour that decides whether a Tuesday run
degrades or fails. Nothing here touches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from ingest.nflverse import (ATTRIBUTION, NflverseError, Usage, bye_teams,
                             fetch, usage_week)

STATS_HEADER = ("player_id,player_display_name,position,team,season,week,"
                "season_type,targets,receptions,receiving_yards,"
                "receiving_air_yards,target_share,carries,rushing_yards,"
                "passing_yards,fantasy_points_ppr\n")

STATS_ROWS = (
    # a receiver with a full line
    "00-0000001,Alpha WR,WR,KC,2024,10,REG,9,7,84.0,110.0,0.24,0,0,0,15.4\n"
    # a rusher: no receiving line at all, which is an honest zero, not a hole
    "00-0000002,Bell Cow,RB,BUF,2024,10,REG,,,,,,18,92.0,0,14.2\n"
    # same player, PLAYOFF week 10 — a different game entirely
    "00-0000003,Post Guy,WR,KC,2024,10,POST,12,9,130.0,150.0,0.31,0,0,0,22.0\n"
    # another week, must not leak into week 10
    "00-0000004,Other Week,WR,KC,2024,11,REG,5,4,40.0,50.0,0.12,0,0,0,8.0\n"
)

GAMES = (
    "season,game_type,week,home_team,away_team\n"
    "2024,REG,10,KC,BUF\n"
    "2024,REG,10,SF,DAL\n"
    "2024,REG,11,KC,SEA\n"
    "2024,REG,11,BUF,GB\n"
    "2024,POST,10,SEA,GB\n"     # a playoff row must not create a week-10 game
)


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.content = body
        self.text = body.decode("utf-8")
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise requests.HTTPError(f"status {self._status}")


class _FakeSession:
    """Serves canned bodies and counts calls, so caching is observable."""

    def __init__(self, bodies: dict[str, str], fail: bool = False) -> None:
        self.bodies = bodies
        self.fail = fail
        self.calls: list[str] = []

    def get(self, url: str, timeout: int = 0) -> _FakeResponse:
        self.calls.append(url)
        if self.fail:
            raise requests.ConnectionError("nflverse is down")
        for name, body in self.bodies.items():
            if name in url:
                return _FakeResponse(body.encode("utf-8"))
        return _FakeResponse(b"", 404)


def _session(fail: bool = False) -> _FakeSession:
    return _FakeSession({
        "stats_player_week_2024.csv": STATS_HEADER + STATS_ROWS,
        "games.csv": GAMES,
    }, fail=fail)


# --------------------------------------------------------------------- #
# RULE N1 — the licence obligation
# --------------------------------------------------------------------- #

def test_attribution_is_shipped_not_optional() -> None:
    """CC-BY-4.0 grants commercial use IN EXCHANGE FOR credit. Ship the credit
    or the grant does not apply — which would put the product back in exactly
    the position Sleeper's terms left it in."""
    assert "nflverse" in ATTRIBUTION
    assert "CC-BY-4.0" in ATTRIBUTION
    # "indicate if changes were made" is the other half of the BY term.
    assert "scored to your league's settings" in ATTRIBUTION


# --------------------------------------------------------------------- #
# what a week actually contains
# --------------------------------------------------------------------- #

def test_only_the_regular_season_and_only_the_asked_week(tmp_path: Path) -> None:
    """`season_type` also carries POST and PRE rows, and week 10 means a
    different game in each. Mixing them puts a playoff game in a week-10
    bucket."""
    got = usage_week(tmp_path, "2024", 10, session=_session())
    assert sorted(got) == ["00-0000001", "00-0000002"]
    assert "00-0000003" not in got, "a playoff week leaked into the regular season"
    assert "00-0000004" not in got, "another week leaked in"


def test_an_absent_stat_is_none_and_never_zero(tmp_path: Path) -> None:
    """A rusher has no receiving line. Parsing that as 0.0 would say "he played
    and was given nothing", which is a different claim from "we have no line" —
    and it is the claim that would understate a returning starter (engine/usage
    RULE U1)."""
    got = usage_week(tmp_path, "2024", 10, session=_session())
    back = got["00-0000002"]
    assert back.targets is None and back.air_yards is None
    assert back.carries == 18 and back.rushing_yards == 92.0
    # and a real zero still parses as a real zero
    assert got["00-0000001"].carries == 0


def test_usage_carries_its_join_key(tmp_path: Path) -> None:
    """RULE N3: the GSIS id is the one id space across every public feed, and
    the same key ingest/injuries.py already uses."""
    got = usage_week(tmp_path, "2024", 10, session=_session())
    assert all(u.gsis_id.startswith("00-") for u in got.values())
    assert isinstance(got["00-0000001"], Usage)


# --------------------------------------------------------------------- #
# byes — the availability half that survives the migration
# --------------------------------------------------------------------- #

def test_byes_are_teams_absent_from_a_week_that_exists(tmp_path: Path) -> None:
    session = _session()
    assert bye_teams(tmp_path, "2024", 10, session=session) == frozenset({"SEA", "GB"})
    assert bye_teams(tmp_path, "2024", 11, session=session) == frozenset({"SF", "DAL"})


def test_an_unknown_week_is_none_never_an_empty_bye_set(tmp_path: Path) -> None:
    """None classifies as UNKNOWN upstream. An empty frozenset would assert
    that everybody is playing, which is the principle-1 gate bypass the
    availability layer was built to prevent — a clean injury report on a bye
    week is still a zero."""
    assert bye_teams(tmp_path, "2024", 99, session=_session()) is None
    assert bye_teams(tmp_path, "1999", 1, session=_session()) is None


def test_a_playoff_row_cannot_conjure_a_regular_season_game(tmp_path: Path) -> None:
    """SEA and GB appear in a POST row for week 10. If game_type were ignored
    they would read as playing, and their bye would vanish."""
    assert "SEA" in (bye_teams(tmp_path, "2024", 10, session=_session()) or set())


# --------------------------------------------------------------------- #
# caching and outages — what a Tuesday run does on a bad day
# --------------------------------------------------------------------- #

def test_a_completed_season_is_fetched_once(tmp_path: Path) -> None:
    session = _session()
    for _ in range(3):
        usage_week(tmp_path, "2024", 10, session=session)
    assert len(session.calls) == 1, "a final season was refetched"


def test_an_outage_falls_back_to_cache_rather_than_failing(tmp_path: Path) -> None:
    """Stale counted data is still a real record of games that were played, and
    the report flags its age. Only a cold cache is fatal."""
    usage_week(tmp_path, "2024", 10, session=_session())
    got = usage_week(tmp_path, "2024", 10, live=True, session=_session(fail=True))
    assert got, "an outage discarded a perfectly good cached season"


def test_a_cold_cache_plus_an_outage_raises(tmp_path: Path) -> None:
    with pytest.raises(NflverseError):
        usage_week(tmp_path, "2024", 10, session=_session(fail=True))


def test_an_empty_body_is_never_cached(tmp_path: Path) -> None:
    """An empty CSV frozen into the cache would mean "nobody played this week"
    forever."""
    empty = _FakeSession({"stats_player_week_2024.csv": ""})
    with pytest.raises(NflverseError):
        fetch("stats_player", "stats_player_week_2024.csv", tmp_path,
              session=empty)
    assert not (tmp_path / "stats_player_week_2024.csv").exists()


def test_a_zero_byte_cache_file_is_refetched(tmp_path: Path) -> None:
    (tmp_path / "games.csv").write_text("", encoding="utf-8")
    session = _session()
    assert bye_teams(tmp_path, "2024", 10, session=session) is not None
    assert session.calls, "a zero-byte cache file was trusted"


# --------------------------------------------------------------------- #
# whole-season loading, for the backtest
# --------------------------------------------------------------------- #

SEASON_ROWS = (
    "player_id,player_display_name,position,team,season,week,season_type,"
    "receptions,receiving_yards,receiving_air_yards,targets\n"
    "00-0000001,Alpha WR,WR,KC,2024,1,REG,5,60.0,80.0,7\n"
    "00-0000002,Bell Cow,RB,BUF,2024,1,REG,2,10.0,12.0,3\n"
    "00-0000001,Alpha WR,WR,KC,2024,2,REG,7,90.0,110.0,9\n"
    "00-0000003,Post Guy,WR,KC,2024,1,POST,9,120.0,140.0,12\n"
    ",Nameless,WR,KC,2024,2,REG,1,5.0,6.0,1\n"
)


def test_a_whole_season_loads_keyed_by_week_and_player(tmp_path: Path) -> None:
    from ingest.nflverse import season_rows
    session = _FakeSession({"stats_player_week_2024.csv": SEASON_ROWS})
    weeks = season_rows(tmp_path, "2024", session=session)
    assert sorted(weeks) == [1, 2]
    assert set(weeks[1]) == {"00-0000001", "00-0000002"}
    assert set(weeks[2]) == {"00-0000001"}, "a row with no id was kept"


def test_the_postseason_never_enters_a_regular_season_week(tmp_path: Path) -> None:
    """A POST row at week 1 is a different game. Mixing them would put a playoff
    performance in a week-1 bucket and quietly corrupt every projection built
    from that week."""
    from ingest.nflverse import season_rows
    session = _FakeSession({"stats_player_week_2024.csv": SEASON_ROWS})
    weeks = season_rows(tmp_path, "2024", session=session)
    assert "00-0000003" not in weeks[1]


def test_rows_are_trimmed_to_what_scoring_reads(tmp_path: Path) -> None:
    """A backtest holds whole seasons in memory. Keeping 150 columns per row
    when scoring reads 30 is the difference between comfortable and not."""
    from engine.scoring import preset, score
    from ingest.nflverse import SCORING_COLUMNS, season_rows
    session = _FakeSession({"stats_player_week_2024.csv": SEASON_ROWS})
    weeks = season_rows(tmp_path, "2024", session=session)
    row = weeks[1]["00-0000001"]
    assert set(row) <= SCORING_COLUMNS
    assert "targets" not in row, "a column scoring never reads was kept"
    # and what survives is still enough to score
    assert score(row, preset("ppr")) == pytest.approx(11.0)


def test_keeping_every_column_is_available_for_exploration(tmp_path: Path) -> None:
    from ingest.nflverse import season_rows
    session = _FakeSession({"stats_player_week_2024.csv": SEASON_ROWS})
    weeks = season_rows(tmp_path, "2024", columns=None, session=session)
    assert "targets" in weeks[1]["00-0000001"]


def test_an_error_page_served_with_200_is_never_cached_as_data(tmp_path) -> None:
    """A non-empty body is not the same as the CSV we asked for.

    An HTML 404 or a proxy error page sails through the emptiness check and gets
    CACHED, and every reader then parses it as a season with no rows — which
    downstream is indistinguishable from "nobody played". That matters because
    only a cached copy is trusted when the network is down: a poisoned one must
    never become that copy.

    Surfaced by an adversarial review of the grading path, where a stats file
    that parses to nothing used to void real calls permanently.
    """
    from ingest.nflverse import NflverseError, fetch

    class _Serves:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def get(self, _url, **_kwargs):
            body = self.body

            class _Response:
                content = body

                def raise_for_status(self) -> None:
                    return None

            return _Response()

    for bad in (b"<!DOCTYPE html>\n<html><body>404</body></html>",
                b'{"message":"Not Found"}',
                b"[]"):
        cache = tmp_path / f"c{len(bad)}"
        with pytest.raises(NflverseError, match="not a CSV"):
            fetch("stats_player", "stats_player_week_2024.csv", cache,
                  session=_Serves(bad))
        assert not (cache / "stats_player_week_2024.csv").exists(), \
            "the bad body was cached anyway"

    good = tmp_path / "good"
    path = fetch("stats_player", "stats_player_week_2024.csv", good,
                 session=_Serves(b"player_id,season,week\n00-0036900,2024,10\n"))
    assert path.is_file()
