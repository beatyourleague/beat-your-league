"""Tests for the subscriber mechanism: registry, roster resolution, batch run,
and the onboarding client methods."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_ingest as ti
import test_week_report as twr
from run.registry import RegistryError, Subscriber, load_registry


def _entry(**overrides) -> dict:
    entry = {
        "email": "fan@example.com",
        "sleeper_username": "FantasyFan",
        "user_id": "457511950237696",
        "league_id": "289646328504385536",
        "rival_owner_id": "189140835533586432",
        "rival_roster_id": 6,
    }
    entry.update(overrides)
    return entry


def _write_registry(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "subscribers.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


# --------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------- #

def test_registry_happy_path(tmp_path: Path) -> None:
    subscribers = load_registry(_write_registry(tmp_path, [_entry()]))
    assert len(subscribers) == 1
    assert subscribers[0].rival_owner_id == "189140835533586432"


@pytest.mark.parametrize("bad", [
    {"email": "not-an-email"},
    {"user_id": "abc"},
    {"league_id": "12"},
    {"rival_owner_id": None, "rival_roster_id": None},
    {"rival_owner_id": "../../etc"},
    {"rival_roster_id": True, "rival_owner_id": None},   # JSON true is not roster 1
    {"rival_roster_id": -2, "rival_owner_id": None},
    {"rival_roster_id": 3.5, "rival_owner_id": None},
])
def test_registry_rejects_bad_entries(tmp_path: Path, bad: dict) -> None:
    with pytest.raises(RegistryError):
        load_registry(_write_registry(tmp_path, [_entry(**bad)]))


def test_registry_accepts_digit_string_roster(tmp_path: Path) -> None:
    subscribers = load_registry(_write_registry(
        tmp_path, [_entry(rival_roster_id="6", rival_owner_id=None)]))
    assert subscribers[0].rival_roster_id == 6


def test_batch_contains_unexpected_exceptions(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """Batch contract: a malformed cache for one subscriber must not raise."""
    import run.batch as batch
    league_dir = tmp_path / "league" / "289646328504385536"
    league_dir.mkdir(parents=True)
    # roster record missing roster_id: KeyError territory inside resolution
    league_dir.joinpath("rosters.json").write_text(
        json.dumps([{"owner_id": "111"}]), encoding="utf-8")
    monkeypatch.setattr(batch, "RAW_DIR", tmp_path)
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    subscriber = Subscriber(email="a@b.co", user_id="111",
                            league_id="289646328504385536",
                            rival_owner_id="999", rival_roster_id=None)
    result = batch.run_subscriber(subscriber, 6, "<style></style>")
    assert not result.ok and "failure" in result.detail.lower() or "owns no" in result.detail


def test_registry_rejects_duplicate_emails(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="duplicate"):
        load_registry(_write_registry(
            tmp_path, [_entry(), _entry(user_id="111111111111")]))


def test_registry_missing_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="subscribers.example.json"):
        load_registry(tmp_path / "nope.json")


def test_league_pass_seat_must_name_its_payer(tmp_path: Path) -> None:
    """A seat with no payer is an unpaid report waiting to be sent."""
    with pytest.raises(RegistryError, match="covered_by"):
        load_registry(_write_registry(tmp_path, [_entry(plan="league_pass")]))
    subs = load_registry(_write_registry(tmp_path, [
        _entry(plan="league_pass", covered_by="commish@example.com")]))
    assert subs[0].is_league_seat and subs[0].covered_by == "commish@example.com"


def test_covered_by_is_rejected_on_an_individual_pass(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="only meaningful"):
        load_registry(_write_registry(tmp_path, [_entry(covered_by="commish@example.com")]))


def test_unknown_plan_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="plan must be"):
        load_registry(_write_registry(tmp_path, [_entry(plan="lifetime_free")]))


def test_two_entries_cannot_claim_the_same_roster(tmp_path: Path) -> None:
    """Same league + same Sleeper user twice means someone would receive another
    manager's team."""
    with pytest.raises(RegistryError, match="two entries for Sleeper user"):
        load_registry(_write_registry(tmp_path, [
            _entry(), _entry(email="other@example.com")]))


def test_league_pass_seats_groups_by_league(tmp_path: Path) -> None:
    from run.registry import league_pass_seats
    subs = load_registry(_write_registry(tmp_path, [
        _entry(email="a@x.co", user_id="111111111", plan="league_pass",
               covered_by="commish@example.com"),
        _entry(email="b@x.co", user_id="222222222", plan="league_pass",
               covered_by="commish@example.com"),
        _entry(email="solo@x.co", user_id="333333333"),
    ]))
    seats = league_pass_seats(subs)
    assert set(seats) == {"289646328504385536"}
    assert len(seats["289646328504385536"]) == 2  # the solo pass isn't a seat


def test_slug_never_contains_email() -> None:
    subscriber = Subscriber(
        email="secret.person@example.com", user_id="123456789",
        league_id="289646328504385536", rival_owner_id="1", rival_roster_id=None,
        sleeper_username="Cool Name!<script>",
    )
    assert "secret" not in subscriber.slug
    assert "@" not in subscriber.slug
    assert "<" not in subscriber.slug  # sanitized for filenames


# --------------------------------------------------------------------- #
# roster resolution + batch
# --------------------------------------------------------------------- #

def test_my_roster_id_matches_owner_and_co_owner(tmp_path: Path) -> None:
    from run.batch import _my_roster_id
    league_dir = tmp_path / "league" / "289646328504385536"
    league_dir.mkdir(parents=True)
    league_dir.joinpath("rosters.json").write_text(json.dumps([
        {"roster_id": 1, "owner_id": "111", "co_owners": None},
        {"roster_id": 2, "owner_id": "222", "co_owners": ["333"]},
    ]), encoding="utf-8")

    def sub(user_id: str) -> Subscriber:
        return Subscriber(email="a@b.co", user_id=user_id,
                          league_id="289646328504385536",
                          rival_owner_id="999", rival_roster_id=None)

    assert _my_roster_id(tmp_path, sub("111")) == 1
    assert _my_roster_id(tmp_path, sub("333")) == 2  # co-owner counts
    from engine.week_report import WeekReportError
    with pytest.raises(WeekReportError, match="owns no"):
        _my_roster_id(tmp_path, sub("444"))


def test_batch_run_subscriber_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import run.batch as batch
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    monkeypatch.setattr(batch, "RAW_DIR", raw)
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")

    subscriber = Subscriber(
        email="fan@example.com", user_id="u1".replace("u", "") or "1",
        league_id=season.league_id, rival_owner_id=None, rival_roster_id=2,
        sleeper_username="kevin_fan",
    )
    # user u1 owns roster 1 in the fixture; registry stores numeric ids in
    # production, the fixture uses "u1" — patch the roster file to match.
    rosters_file = raw / "league" / season.league_id / "rosters.json"
    rosters_file.write_text(json.dumps([
        {"roster_id": 1, "owner_id": "1"},
        {"roster_id": 2, "owner_id": "2"},
    ]), encoding="utf-8")

    template_html = twr._template()
    result = batch.run_subscriber(subscriber, twr.REPORT_WEEK, template_html)
    assert result.ok, result.detail
    assert result.html_path is not None and result.html_path.is_file()
    assert "fan@example.com" not in result.html_path.name
    assert "kevin_fan" in result.html_path.name
    html_out = result.html_path.read_text(encoding="utf-8")
    assert "RIVALRY WEEK" in html_out  # rival IS this week's opponent here
    text_out = result.html_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "GAME PLAN" in text_out


def test_batch_failure_is_contained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import run.batch as batch
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    monkeypatch.setattr(batch, "RAW_DIR", raw)
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    ghost = Subscriber(email="g@example.com", user_id="404404404",
                       league_id=season.league_id, rival_owner_id=None,
                       rival_roster_id=2)
    result = batch.run_subscriber(ghost, twr.REPORT_WEEK, twr._template())
    assert not result.ok
    assert "owns no" in result.detail


# --------------------------------------------------------------------- #
# onboarding client methods
# --------------------------------------------------------------------- #

def test_user_lookup_and_leagues(tmp_path: Path) -> None:
    client, session = ti._client(tmp_path, {
        "/user/FantasyFan": {"user_id": "457511950237696", "display_name": "FantasyFan"},
        "/user/457511950237696/leagues/nfl/2026": [{"league_id": "1", "name": "L"}],
    })
    user = client.user("FantasyFan")
    assert user["user_id"] == "457511950237696"
    leagues = client.user_leagues("457511950237696", "2026")
    assert leagues and leagues[0]["name"] == "L"


@pytest.mark.parametrize("bad", ["has space", "semi;colon", "a" * 33, "", "näme"])
def test_user_lookup_rejects_bad_usernames(tmp_path: Path, bad: str) -> None:
    client, session = ti._client(tmp_path, {})
    with pytest.raises(ValueError):
        client.user(bad)
    assert session.calls == []


def test_user_leagues_rejects_bad_inputs(tmp_path: Path) -> None:
    client, _ = ti._client(tmp_path, {})
    with pytest.raises(ValueError):
        client.user_leagues("abc", "2026")
    with pytest.raises(ValueError):
        client.user_leagues("457511950237696", "20x6")
