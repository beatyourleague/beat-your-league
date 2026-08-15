"""Tests for the Phase 1 ingestion layer: caching, validation, summary logic."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

import ingest.pull as pull_module
from ingest.config import league_id_from_claude_md, resolve_league_id
from ingest.pull import last_week_of_season, pull_history, scoring_label, team_table
from ingest.sleeper import SleeperClient, SleeperError, SleeperNotFound, is_valid_league_id


# --------------------------------------------------------------------- #
# league ID validation
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("league_id", ["289646328504385536", "123456", "9" * 20])
def test_valid_league_ids(league_id: str) -> None:
    assert is_valid_league_id(league_id)


@pytest.mark.parametrize(
    "league_id",
    ["", "PASTE_LEAGUE_ID_HERE", "abc123", "123/../../etc", "12345",
     "9" * 21, "1234;drop", " 123456", "123456 "],
)
def test_invalid_league_ids(league_id: str) -> None:
    assert not is_valid_league_id(league_id)


# --------------------------------------------------------------------- #
# league ID resolution
# --------------------------------------------------------------------- #

def _write_claude_md(tmp_path: Path, league_line: str) -> Path:
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"# Brief\n\n**My Sleeper league ID:** {league_line}\n", encoding="utf-8")
    return path


def test_claude_md_placeholder_is_ignored(tmp_path: Path) -> None:
    path = _write_claude_md(tmp_path, "`PASTE_LEAGUE_ID_HERE`  <!-- comment -->")
    assert league_id_from_claude_md(path) is None


def test_claude_md_real_id_is_found(tmp_path: Path) -> None:
    path = _write_claude_md(tmp_path, "`289646328504385536`")
    assert league_id_from_claude_md(path) == "289646328504385536"


def test_cli_beats_env_and_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_claude_md(tmp_path, "`111111111111111111`")
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "222222222222222222")
    assert resolve_league_id("333333333333333333", tmp_path) == "333333333333333333"
    assert resolve_league_id(None, tmp_path) == "222222222222222222"
    monkeypatch.delenv("SLEEPER_LEAGUE_ID")
    assert resolve_league_id(None, tmp_path) == "111111111111111111"


def test_missing_id_exits_with_instructions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    _write_claude_md(tmp_path, "`PASTE_LEAGUE_ID_HERE`")
    with pytest.raises(SystemExit, match="Paste your Sleeper league ID"):
        resolve_league_id(None, tmp_path)


def test_invalid_id_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    with pytest.raises(SystemExit, match="doesn't look like"):
        resolve_league_id("not-a-league", tmp_path)


# --------------------------------------------------------------------- #
# client caching behavior (no real network: fake session)
# --------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Records requests; serves canned payloads keyed by URL suffix."""

    _MISSING = object()

    def __init__(self, payloads: dict[str, Any], default: Any = _MISSING) -> None:
        self.payloads = payloads
        self.default = default
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls.append(url)
        for suffix, payload in self.payloads.items():
            if url.endswith(suffix):
                if isinstance(payload, int):
                    return FakeResponse(None, status_code=payload)
                return FakeResponse(payload)
        if self.default is not self._MISSING:
            return FakeResponse(self.default)
        raise AssertionError(f"unexpected URL fetched: {url}")


def _client(tmp_path: Path, payloads: dict[str, Any],
            default: Any = FakeSession._MISSING) -> tuple[SleeperClient, FakeSession]:
    session = FakeSession(payloads, default)
    client = SleeperClient(cache_dir=tmp_path / "raw", session=session,  # type: ignore[arg-type]
                           throttle_seconds=0.0)
    return client, session


LEAGUE_ID = "289646328504385536"


def test_second_read_hits_cache_not_network(tmp_path: Path) -> None:
    client, session = _client(tmp_path, {f"/league/{LEAGUE_ID}": {"name": "L", "season": "2025"}})
    first = client.league(LEAGUE_ID)
    second = client.league(LEAGUE_ID)
    assert first == second
    assert len(session.calls) == 1
    assert client.cache_hits == 1
    assert client.files_written == 1


def test_empty_responses_are_not_cached(tmp_path: Path) -> None:
    client, session = _client(tmp_path, {"/matchups/3": []})
    assert client.matchups(LEAGUE_ID, 3) == []
    assert client.matchups(LEAGUE_ID, 3) == []
    assert len(session.calls) == 2  # refetched: emptiness must not freeze
    assert client.files_written == 0


def test_expired_cache_is_refetched(tmp_path: Path) -> None:
    client, session = _client(tmp_path, {f"/league/{LEAGUE_ID}": {"name": "L"}})
    client.league(LEAGUE_ID, max_age_hours=1.0)
    cache_file = tmp_path / "raw" / "league" / LEAGUE_ID / "league.json"
    two_hours_ago = time.time() - 7200
    import os
    os.utime(cache_file, (two_hours_ago, two_hours_ago))
    client.league(LEAGUE_ID, max_age_hours=1.0)
    assert len(session.calls) == 2
    client.league(LEAGUE_ID, max_age_hours=None)  # None = never expires
    assert len(session.calls) == 2


def test_corrupt_cache_is_refetched(tmp_path: Path) -> None:
    client, session = _client(tmp_path, {f"/league/{LEAGUE_ID}": {"name": "L"}})
    client.league(LEAGUE_ID)
    cache_file = tmp_path / "raw" / "league" / LEAGUE_ID / "league.json"
    cache_file.write_text("{not json", encoding="utf-8")
    assert client.league(LEAGUE_ID) == {"name": "L"}
    assert len(session.calls) == 2


def test_404_raises_not_found(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, {f"/league/{LEAGUE_ID}": 404})
    with pytest.raises(SleeperNotFound):
        client.league(LEAGUE_ID)


def test_manifest_records_fetch_time(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, {f"/league/{LEAGUE_ID}": {"name": "L"}})
    client.league(LEAGUE_ID)
    manifest = json.loads((tmp_path / "raw" / "_manifest.json").read_text(encoding="utf-8"))
    entry = manifest[str(Path("league") / LEAGUE_ID / "league.json")]
    assert entry["url"].endswith(f"/league/{LEAGUE_ID}")
    assert "fetched_at" in entry and entry["bytes"] > 0


def test_invalid_league_id_never_reaches_url(tmp_path: Path) -> None:
    client, session = _client(tmp_path, {})
    with pytest.raises(ValueError):
        client.users("123/../../etc")
    assert session.calls == []


# --------------------------------------------------------------------- #
# review-confirmed regressions: cache poisoning, empties, manifest, rollover
# --------------------------------------------------------------------- #

def test_wrong_shape_response_raises_and_is_not_cached(tmp_path: Path) -> None:
    client, session = _client(tmp_path, {"/users": {"oops": "dict not list"}})
    with pytest.raises(SleeperError, match="expected list"):
        client.users(LEAGUE_ID)
    assert not (tmp_path / "raw" / "league" / LEAGUE_ID / "users.json").exists()
    session.payloads["/users"] = [{"user_id": "u1"}]  # API healthy again
    assert client.users(LEAGUE_ID) == [{"user_id": "u1"}]  # self-heals


def test_wrong_shape_cache_entry_is_refetched(tmp_path: Path) -> None:
    cache_file = tmp_path / "raw" / "league" / LEAGUE_ID / "users.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text('{"poisoned": true}', encoding="utf-8")  # dict where list expected
    client, session = _client(tmp_path, {"/users": [{"user_id": "u1"}]})
    assert client.users(LEAGUE_ID, max_age_hours=None) == [{"user_id": "u1"}]
    assert len(session.calls) == 1  # poisoned entry discarded, refetched, overwritten
    assert json.loads(cache_file.read_text(encoding="utf-8")) == [{"user_id": "u1"}]


def test_empty_immutable_response_is_cached(tmp_path: Path) -> None:
    client, session = _client(tmp_path, {"/transactions/17": []})
    assert client.transactions(LEAGUE_ID, 17, max_age_hours=None) == []
    assert client.transactions(LEAGUE_ID, 17, max_age_hours=None) == []
    assert len(session.calls) == 1  # a completed season's empty week is final
    assert client.cache_hits == 1


def test_manifest_backfilled_on_cache_hit(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, {f"/league/{LEAGUE_ID}": {"name": "L"}})
    client.league(LEAGUE_ID)
    manifest_path = tmp_path / "raw" / "_manifest.json"
    manifest_path.unlink()  # simulate Ctrl-C between cache write and manifest write
    client.league(LEAGUE_ID)  # cache hit must heal the manifest
    entry = json.loads(manifest_path.read_text(encoding="utf-8"))[
        str(Path("league") / LEAGUE_ID / "league.json")]
    assert entry["fetched_at"] and entry["bytes"] > 0


def test_stale_previous_league_is_revalidated(tmp_path: Path) -> None:
    prev_id = "198946952535085056"
    stale_file = tmp_path / "raw" / "league" / prev_id / "league.json"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text(
        json.dumps({"league_id": prev_id, "status": "in_season", "season": "2018"}),
        encoding="utf-8")
    eight_hours_ago = time.time() - 8 * 3600
    import os
    os.utime(stale_file, (eight_hours_ago, eight_hours_ago))

    fresh = {"league_id": prev_id, "status": "complete", "season": "2018",
             "name": "L", "settings": {}, "scoring_settings": {}}
    client, session = _client(tmp_path, {f"/league/{prev_id}": fresh}, default=[])
    result = pull_history(client, {"previous_league_id": prev_id})

    assert result is not None and result.league["status"] == "complete"
    league_fetches = [c for c in session.calls if c.endswith(prev_id)]
    assert len(league_fetches) == 1  # stale snapshot revalidated exactly once
    assert json.loads(stale_file.read_text(encoding="utf-8"))["status"] == "complete"


def test_invalid_previous_league_id_skips_history(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    client, session = _client(tmp_path, {})
    assert pull_history(client, {"previous_league_id": "0"}) is None
    assert pull_history(client, {"previous_league_id": None}) is None
    assert pull_history(client, {}) is None
    assert session.calls == []
    assert "not a valid Sleeper ID" in capsys.readouterr().out


def test_numeric_previous_league_id_is_coerced(tmp_path: Path) -> None:
    prev_id = 198946952535085056  # int, as an API quirk might deliver it
    fresh = {"league_id": str(prev_id), "status": "complete", "season": "2018"}
    client, _ = _client(tmp_path, {f"/league/{prev_id}": fresh}, default=[])
    result = pull_history(client, {"previous_league_id": prev_id})
    assert result is not None and result.season == "2018"


def _patched_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                  payloads: dict[str, Any], **client_kwargs: Any) -> FakeSession:
    session = FakeSession(payloads, default=[])
    def fake_client(cache_dir: Path) -> SleeperClient:
        return SleeperClient(cache_dir=tmp_path / "raw", session=session,  # type: ignore[arg-type]
                             throttle_seconds=0.0, **client_kwargs)
    monkeypatch.setattr(pull_module, "SleeperClient", fake_client)
    return session


def test_main_reports_unknown_league(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture) -> None:
    _patched_main(monkeypatch, tmp_path,
                  {"/state/nfl": {"season": "2026"}, f"/league/{LEAGUE_ID}": 404})
    rc = pull_module.main(["--league", LEAGUE_ID, "--skip-players"])
    assert rc == 1
    assert "not found on Sleeper" in capsys.readouterr().err


def test_main_reports_api_failure_without_traceback(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture) -> None:
    _patched_main(monkeypatch, tmp_path, {"/state/nfl": 500}, max_retries=0)
    rc = pull_module.main(["--league", LEAGUE_ID, "--skip-players"])
    assert rc == 1
    assert "Sleeper API failure" in capsys.readouterr().err


# --------------------------------------------------------------------- #
# availability snapshots
# --------------------------------------------------------------------- #

def test_snapshot_rejects_traversal_in_state_fields(tmp_path: Path) -> None:
    """Review finding: /state/nfl season and season_type flow into a file path."""
    from ingest.availability import write_snapshot
    players = {"1": {"position": "RB", "fantasy_positions": ["RB"],
                     "active": True, "team": "KC", "injury_status": None}}
    for bad_state in (
        {"season": "../../etc", "season_type": "regular", "week": 1},
        {"season": "2026", "season_type": "../evil", "week": 1},
        {"season": "20261", "season_type": "regular", "week": 1},
    ):
        with pytest.raises(ValueError):
            write_snapshot(tmp_path, players, bad_state)
    path, count = write_snapshot(
        tmp_path, players, {"season": "2026", "season_type": "pre", "week": 1})
    assert path.is_file() and count == 1

def test_scoring_labels() -> None:
    assert scoring_label({"rec": 1.0}).startswith("Full PPR")
    assert scoring_label({"rec": 0.5}).startswith("Half PPR")
    assert scoring_label({"rec": 0.0}).startswith("Standard")
    assert scoring_label({}).startswith("Standard")
    assert scoring_label({"rec": 0.25}).startswith("Custom")


def test_last_week_of_season() -> None:
    assert last_week_of_season("2018") == 17
    assert last_week_of_season("2025") == 18
    assert last_week_of_season("garbage") == 18


def test_team_table_joins_and_falls_back() -> None:
    users = [
        {"user_id": "u1", "display_name": "kevin", "metadata": {"team_name": "The Regret Index"}},
        {"user_id": "u2", "display_name": "mike", "metadata": {}},
        {"user_id": "u3", "display_name": "dana", "metadata": None},
    ]
    rosters = [
        {"roster_id": 2, "owner_id": "u2"},
        {"roster_id": 1, "owner_id": "u1"},
        {"roster_id": 3, "owner_id": "u3"},
        {"roster_id": 4, "owner_id": None},
    ]
    assert team_table(users, rosters) == [
        (1, "The Regret Index", "kevin"),
        (2, "mike", "mike"),
        (3, "dana", "dana"),
        (4, "(no owner)", "(no owner)"),
    ]


def test_projections_endpoint_validates_input(tmp_path: Path) -> None:
    """The projections fetcher must refuse garbage before it builds a URL."""
    from ingest.sleeper import SleeperClient
    client = SleeperClient(tmp_path)
    with pytest.raises(ValueError):
        client.projections("18", 10)
    with pytest.raises(ValueError):
        client.projections("2018", 0)
    with pytest.raises(ValueError):
        client.projections("2018", 10, season_type="playoffs")
