"""Tests for the directory the intake page downloads.

Two properties matter here and neither is about formatting: the asset must
carry its own licence term (CC-BY is a trade, not a courtesy), and it must be
built from a window where exact name matching is actually unambiguous. The
second is a fact about live data, so it is checked against live data when the
cache is present.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from engine.roster import Player, PlayerDirectory, load_directory, normalize
from ingest.nflverse import ATTRIBUTION, season_teams
from render.player_index import (MAX_EDITS, build, confusable_pairs, main,
                                 _within)

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "nflverse"
SITE_ASSET = Path(__file__).resolve().parent.parent / "site" / "join" / "players.json"


def _cache_or_skip() -> tuple[Path, Path]:
    players, teams = RAW / "players.csv", RAW / "teams_colors_logos.csv"
    if not (players.is_file() and teams.is_file() and (RAW / "games.csv").is_file()):
        pytest.skip("nflverse cache not present — run `make index`")
    return players, teams


# --------------------------------------------------------------------- #
# bounded edit distance
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("a,b,near", [
    ("bijanrobinson", "brianrobinson", True),    # transposition + swap
    ("camjohnson", "cadejohnson", True),
    ("joshallen", "jalen", False),               # length gap
    ("mahomes", "mahomes", True),
    ("allen", "allan", True),                    # one substitution
    ("smith", "jones", False),
    ("ab", "ba", True),                          # pure transposition
])
def test_bounded_distance(a: str, b: str, near: bool) -> None:
    assert _within(a, b) is near
    assert _within(b, a) is near, "distance must be symmetric"


def test_the_bound_is_actually_enforced() -> None:
    """The early-out must not change the answer, only the work."""
    assert _within("abcdefgh", "abcdefgh", 0)
    assert not _within("abcdefgh", "xbcdefgh", 0)
    assert _within("abcdefgh", "xbcdefgh", 1)


# --------------------------------------------------------------------- #
# confusable pairs
# --------------------------------------------------------------------- #

def test_confusables_are_same_position_only() -> None:
    """A quarterback and a kicker one edit apart is not a mistake anyone makes
    reading their own roster, and including such pairs buries the real ones."""
    directory = PlayerDirectory([
        Player("00-0000001", "Mac Jones", "QB", "JAX"),
        Player("00-0000002", "Zay Jones", "WR", "ARI"),
        Player("00-0000003", "May Jones", "QB", "NYJ"),
    ])
    pairs = confusable_pairs(directory)
    assert pairs == [["00-0000001", "00-0000003"]]


def test_confusable_output_is_stable_across_builds() -> None:
    """The asset is committed, so a rebuild that reorders it makes every diff
    unreadable and `--check` meaningless."""
    directory = PlayerDirectory([
        Player("00-0000003", "Cam Miller", "RB", "KC"),
        Player("00-0000001", "Jam Miller", "RB", "SF"),
        Player("00-0000002", "Ham Miller", "RB", "LA"),
    ])
    once = confusable_pairs(directory)
    assert once == sorted(once)
    assert all(pair == sorted(pair) for pair in once)
    assert once == confusable_pairs(PlayerDirectory(
        list(reversed(directory.players))))


# --------------------------------------------------------------------- #
# RULE N1 — the licence rides with the data
# --------------------------------------------------------------------- #

def test_the_asset_carries_its_attribution() -> None:
    """CC-BY-4.0 grants commercial use IN EXCHANGE FOR credit. Keeping the
    credit only on the page that renders this would let a redesign drop a
    licence term."""
    payload = build(PlayerDirectory([Player("00-0000001", "A B", "QB", "KC")]),
                    "2026", generated_at="2026-08-18T00:00:00+00:00")
    assert payload["attribution"] == ATTRIBUTION
    assert "CC-BY-4.0" in payload["attribution"]


def test_the_published_asset_still_carries_it() -> None:
    if not SITE_ASSET.is_file():
        pytest.skip("players.json not built — run `make index`")
    published = json.loads(SITE_ASSET.read_text(encoding="utf-8"))
    assert published.get("attribution") == ATTRIBUTION
    assert published.get("players") and published.get("season")


def test_build_is_deterministic_apart_from_its_timestamp() -> None:
    directory = PlayerDirectory([
        Player("00-0000002", "B C", "RB", "SF"),
        Player("00-0000001", "A B", "QB", "KC"),
    ])
    first = build(directory, "2026", generated_at="x")
    second = build(PlayerDirectory(list(reversed(directory.players))),
                   "2026", generated_at="y")
    first.pop("generated"), second.pop("generated")
    assert first == second


# --------------------------------------------------------------------- #
# RULE R2's window, against the live data
# --------------------------------------------------------------------- #

def test_the_shipped_window_is_collision_free_and_the_next_one_is_not() -> None:
    """The generator uses season-1, and that is a MEASURED boundary rather than
    a taste: against live data season-1 admits zero normalised-name collisions
    and season-2 admits four. Both halves are asserted — a test that only
    checked the good side would not notice the window silently widening."""
    players, teams = _cache_or_skip()
    eligible = season_teams(RAW, "2024")

    def collisions(window: int) -> int:
        directory = load_directory(players, teams, window, eligible)
        seen: dict[str, set[str]] = collections.defaultdict(set)
        for player in directory.players:
            seen[normalize(player.name)].add(player.player_id)
        return sum(1 for ids in seen.values() if len(ids) > 1)

    assert collisions(2023) == 0, "the shipped window is no longer unambiguous"
    assert collisions(2022) > 0, (
        "season-2 no longer collides, so the window could widen — re-measure "
        "before changing the generator, and update this test with the numbers")


def test_a_short_schedule_refuses_rather_than_shipping_a_hole(
        tmp_path: Path, capsys) -> None:
    """A directory missing one defense is a subscriber who rosters that team
    and cannot finish signup. Refusing is louder than shipping 31 teams."""
    _cache_or_skip()
    out = tmp_path / "players.json"
    assert main(["--season", "1999", "--raw", str(RAW), "--output", str(out)]) == 1
    assert "not 32" in capsys.readouterr().err
    assert not out.exists()


def test_check_mode_detects_drift(tmp_path: Path, capsys) -> None:
    """`--check` is what stops the committed asset drifting from the data it
    claims to describe."""
    _cache_or_skip()
    out = tmp_path / "players.json"
    assert main(["--season", "2024", "--raw", str(RAW), "--output", str(out)]) == 0
    assert main(["--season", "2024", "--raw", str(RAW), "--output", str(out),
                 "--check"]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["players"] = payload["players"][:-1]
    out.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["--season", "2024", "--raw", str(RAW), "--output", str(out),
                 "--check"]) == 1
    assert "stale" in capsys.readouterr().err


def test_the_asset_the_generator_ACTUALLY_produces_is_collision_free(
        tmp_path: Path) -> None:
    """The test above measures the window; this one measures the OUTPUT.

    That distinction is not academic — it is a mutation that got through.
    Widening the generator to season-2 left the window test passing, because
    that test computes collisions itself and never asks what the generator
    chose. A directory with two players under one name means the intake hands
    a subscriber a choice the page was not built to offer, so the property
    belongs to the artifact, not to a constant."""
    _cache_or_skip()
    out = tmp_path / "players.json"
    assert main(["--season", "2024", "--raw", str(RAW), "--output", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))

    seen: dict[str, list[str]] = collections.defaultdict(list)
    for name, player_id, _position, _team in payload["players"]:
        seen[normalize(name)].append(player_id)
    clashes = {key: ids for key, ids in seen.items() if len(ids) > 1}
    assert not clashes, (
        f"the published directory holds {len(clashes)} colliding name(s): "
        f"{list(clashes.items())[:3]} — exact matching is no longer safe, so "
        f"either narrow the window or teach the intake to offer a choice")


def test_the_published_asset_is_collision_free_too() -> None:
    """The committed file, not a rebuild of it — this is what a subscriber's
    browser actually downloads."""
    if not SITE_ASSET.is_file():
        pytest.skip("players.json not built — run `make index`")
    payload = json.loads(SITE_ASSET.read_text(encoding="utf-8"))
    seen: dict[str, list[str]] = collections.defaultdict(list)
    for name, player_id, _position, _team in payload["players"]:
        seen[normalize(name)].append(player_id)
    assert not {k: v for k, v in seen.items() if len(v) > 1}
