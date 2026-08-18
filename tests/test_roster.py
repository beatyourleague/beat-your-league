"""Tests for name resolution — the correctness heart of the post-Sleeper product.

A wrong match here does not fail loudly. It produces a complete, confident
report about a player the subscriber does not own. So these tests are mostly
about the cases where the matcher must REFUSE, and about the measurement that
makes exact matching safe in the first place (RULE R2).

The fixtures below are real players and real name shapes, written out rather
than sampled from the live CSV, so the suite stays offline and deterministic.
One test does read the live directory when it is cached, because the zero-
collision claim in the module docstring is about real data and is worth
re-checking whenever that data moves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.roster import (DEFENSE, Match, Player, PlayerDirectory,
                           index_payload, load_directory, normalize)

PLAYERS_CSV = """gsis_id,display_name,position,latest_team,last_season
00-0036900,Ja'Marr Chase,WR,CIN,2026
00-0035676,A.J. Brown,WR,PHI,2026
00-0038134,Kenneth Walker III,RB,SEA,2026
00-0036963,Amon-Ra St. Brown,WR,DET,2026
00-0033873,Patrick Mahomes,QB,KC,2026
00-0039075,Puka Nacua,WR,LA,2026
PRY456541,Layne Pryor,TE,HOU,2026
00-0040792,Layne Pryor,TE,HOU,2026
00-0000001,Adrian Peterson,RB,MIN,2011
00-0000002,Adrian Peterson,RB,CHI,2026
00-0000003,Retired Guy,WR,NYJ,2019
00-0000004,Deep Snapper,LS,KC,2026
"""

TEAMS_CSV = """team_abbr,team_name,team_id,team_nick
BAL,Baltimore Ravens,0325,Ravens
KC,Kansas City Chiefs,2310,Chiefs
SF,San Francisco 49ers,4500,49ers
"""


@pytest.fixture()
def directory(tmp_path: Path) -> PlayerDirectory:
    players = tmp_path / "players.csv"
    teams = tmp_path / "teams.csv"
    players.write_text(PLAYERS_CSV, encoding="utf-8")
    teams.write_text(TEAMS_CSV, encoding="utf-8")
    return load_directory(players, teams, min_last_season=2024)


# --------------------------------------------------------------------- #
# RULE R1 — one human, one entry
# --------------------------------------------------------------------- #

def test_players_without_a_gsis_id_are_skipped(directory: PlayerDirectory) -> None:
    """6,079 of nflverse's 25,040 rows carry a non-GSIS id, and they duplicate
    real humans — Layne Pryor is in the file twice. Without the filter the
    directory holds two of him and his name becomes ambiguous, so a real
    subscriber with a real tight end cannot complete signup."""
    ids = {p.player_id for p in directory.players}
    assert "PRY456541" not in ids
    assert "00-0040792" in ids
    assert directory.resolve("Layne Pryor").resolved, \
        "a duplicate row made a real player unresolvable"


def test_only_rosterable_positions_are_eligible(directory: PlayerDirectory) -> None:
    assert not directory.resolve("Deep Snapper").resolved


# --------------------------------------------------------------------- #
# RULE R2 — recency is what makes exact matching safe
# --------------------------------------------------------------------- #

def test_the_recency_window_is_what_prevents_collisions(directory: PlayerDirectory) -> None:
    """Across all time there are 156 colliding fantasy names, including two
    Adrian Petersons. Inside the window there are none. The window is therefore
    load-bearing, not a tidy-up — and the 2011 Peterson must be out."""
    assert not directory.resolve("Retired Guy").resolved
    ids = {p.player_id for p in directory.players}
    assert "00-0000001" not in ids and "00-0000002" in ids
    assert directory.resolve("Adrian Peterson").resolved


def test_a_genuine_collision_is_refused_not_guessed() -> None:
    """RULE R3. When the window ever fails to separate two people, the matcher
    must hand the choice back rather than pick — a guess is indistinguishable
    from working until the report goes out."""
    both = [Player("00-0000001", "Adrian Peterson", "RB", "MIN"),
            Player("00-0000002", "Adrian Peterson", "RB", "CHI")]
    match = PlayerDirectory(both).resolve("Adrian Peterson")
    assert not match.resolved
    assert len(match.candidates) == 2
    assert "more than one" in (match.reason or "")


# --------------------------------------------------------------------- #
# what people actually type
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("typed,expected", [
    ("Ja'Marr Chase", "Ja'Marr Chase"),        # as printed
    ("JAMARR CHASE", "Ja'Marr Chase"),         # no apostrophe, shouting
    ("jamarr chase", "Ja'Marr Chase"),
    ("A.J. Brown", "A.J. Brown"),
    ("AJ Brown", "A.J. Brown"),                # periods dropped
    ("Kenneth Walker", "Kenneth Walker III"),  # suffix omitted
    ("Kenneth Walker III", "Kenneth Walker III"),
    ("Amon-Ra St. Brown", "Amon-Ra St. Brown"),
    ("Amon Ra St Brown", "Amon-Ra St. Brown"), # hyphen typed as a space
    ("  Puka Nacua  ", "Puka Nacua"),
])
def test_real_name_shapes_resolve(directory: PlayerDirectory, typed: str,
                                  expected: str) -> None:
    match = directory.resolve(typed)
    assert match.resolved, f"{typed!r} did not resolve: {match.reason}"
    assert match.player is not None and match.player.name == expected


@pytest.mark.parametrize("typed", [
    "Patrick Mahomes QB KC - BYE 10",
    "Patrick Mahomes (KC) 21.4",
    "QB  Patrick Mahomes  KC",
    "Patrick Mahomes • KC • BYE 6",
])
def test_pasted_decoration_is_stripped(directory: PlayerDirectory,
                                       typed: str) -> None:
    """A manager copies their roster out of an app; the name is the only part
    every platform writes the same way."""
    match = directory.resolve(typed)
    assert match.resolved, f"{typed!r} did not resolve: {match.reason}"
    assert match.player is not None and match.player.name == "Patrick Mahomes"


def test_an_unknown_name_is_refused_with_a_plain_reason(
        directory: PlayerDirectory) -> None:
    match = directory.resolve("Nobody McFakename")
    assert not match.resolved and not match.candidates
    assert match.reason == "we don't have a player by that name"
    # Buyer vocabulary: no ids, no jargon, no version numbers.
    assert "gsis" not in (match.reason or "").lower()


# --------------------------------------------------------------------- #
# team defenses — written a dozen ways, none of them a person's name
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("typed", [
    "Baltimore Ravens", "Ravens", "Ravens D/ST", "BAL DEF", "BAL",
    "baltimore", "Baltimore Ravens DEF",
])
def test_defenses_resolve_however_they_are_written(directory: PlayerDirectory,
                                                   typed: str) -> None:
    match = directory.resolve(typed)
    assert match.resolved, f"{typed!r} did not resolve"
    assert match.player is not None
    assert match.player.position == DEFENSE and match.player.team == "BAL"


def test_a_bare_team_abbreviation_survives_decoration_stripping(
        directory: PlayerDirectory) -> None:
    """"KC" alone is a defense; the same token inside "Mahomes QB KC" is noise.
    Stripping team abbreviations unconditionally would delete the defense."""
    assert directory.resolve("KC").player.position == DEFENSE
    assert directory.resolve("Patrick Mahomes KC").player.name == "Patrick Mahomes"


def test_defense_ids_are_distinguishable_from_players(
        directory: PlayerDirectory) -> None:
    assert directory.resolve("SF").player.player_id == "DEF-SF"
    assert directory.resolve("Puka Nacua").player.player_id.startswith("00-")


# --------------------------------------------------------------------- #
# resolving a whole paste
# --------------------------------------------------------------------- #

def test_blank_lines_do_not_become_failed_matches(
        directory: PlayerDirectory) -> None:
    """A paste is full of blank lines and separators. Reporting them as
    unresolved players would bury the one name that actually needs fixing."""
    lines = ["Puka Nacua", "", "   ", "---", "A.J. Brown"]
    got = directory.resolve_all(lines)
    assert len(got) == 2 and all(m.resolved for m in got)


def test_one_bad_line_does_not_stop_the_others(
        directory: PlayerDirectory) -> None:
    got = directory.resolve_all(["Puka Nacua", "Nobody McFakename", "A.J. Brown"])
    assert [m.resolved for m in got] == [True, False, True]


def test_the_browser_index_carries_what_the_page_needs(
        directory: PlayerDirectory) -> None:
    payload = index_payload(directory)
    assert payload and all(len(row) == 4 for row in payload)
    names = [row[0] for row in payload]
    assert names == sorted(names), "the index must be stable across builds"
    assert any(row[1].startswith("DEF-") for row in payload)


# --------------------------------------------------------------------- #
# the measurement the whole design rests on
# --------------------------------------------------------------------- #

def test_the_real_directory_has_no_colliding_names() -> None:
    """The module docstring claims exact matching is safe because the eligible
    pool contains zero normalised-name collisions. That is a fact about live
    data, not about this code, so it is re-checked whenever the cache exists —
    the day a rookie shares a name with a starter, resolution starts handing
    people a choice they did not expect, and this is where we find out.

    Skipped rather than fetched: the suite stays offline.
    """
    raw = Path(__file__).resolve().parent.parent / "data" / "raw" / "nflverse"
    players, teams = raw / "players.csv", raw / "teams_colors_logos.csv"
    if not (players.is_file() and teams.is_file()):
        pytest.skip("nflverse cache not present — run `python -m ingest.nflverse`")
    directory = load_directory(players, teams, min_last_season=2024)
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for player in directory.players:
        key = normalize(player.name)
        if key in seen and seen[key] != player.name:
            clashes.append(f"{seen[key]} / {player.name}")
        seen[key] = player.name
    assert not clashes, (
        f"real name collisions appeared in the eligible pool: {clashes}. "
        f"Exact matching is no longer safe on its own — resolution must offer "
        f"these as a choice (RULE R3), and the intake copy must expect it.")
