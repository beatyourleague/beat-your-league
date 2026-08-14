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


def _export(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "substack-export.csv"
    path.write_text(rows, encoding="utf-8")
    return path


def test_cancelled_subscribers_drop_out_without_operator_action(tmp_path: Path) -> None:
    """Substack stops the billing on its own; this is how the pipeline learns to
    stop the reports. No inbox, no manual list."""
    from run.subscriptions import load_paid_list
    path = _export(tmp_path, "email,active_subscription\n"
                             "stays@example.com,true\n"
                             "quit@example.com,false\n")
    paid = load_paid_list(path)
    assert paid.covers("stays@example.com")
    assert not paid.covers("quit@example.com")
    assert paid.covers("STAYS@Example.com ")   # case/whitespace tolerant


def test_missing_export_refuses_rather_than_mailing_everyone(tmp_path: Path) -> None:
    """Silently sending to people who cancelled is the failure that becomes a
    chargeback, so an absent list is an error the operator must resolve."""
    from run.subscriptions import SubscriptionError, load_paid_list
    with pytest.raises(SubscriptionError, match="no subscriber export"):
        load_paid_list(tmp_path / "nope.csv")


def test_unrecognised_status_is_not_treated_as_paid(tmp_path: Path) -> None:
    from run.subscriptions import load_paid_list
    paid = load_paid_list(_export(tmp_path, "email,status\n"
                                            "weird@example.com,something_new\n"
                                            "ok@example.com,active\n"))
    assert paid.covers("ok@example.com")
    assert not paid.covers("weird@example.com")


def test_export_without_status_column_is_flagged(tmp_path: Path) -> None:
    """A plain list has no cancellation signal — callers must be told, not
    silently handed 'everyone is paying'."""
    from run.subscriptions import load_paid_list
    paid = load_paid_list(_export(tmp_path, "email\na@example.com\n"))
    assert paid.status_column is None and paid.covers("a@example.com")


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


# --------------------------------------------------------------------- #
# Stripe as the source of truth for "is this person entitled to a report"
# --------------------------------------------------------------------- #

def _stripe_page(subs, has_more=False):
    return {"data": subs, "has_more": has_more}


def _sub(sub_id, email, deleted=False):
    return {"id": sub_id, "customer": {"email": email, "deleted": deleted}}


def test_stripe_lists_entitled_subscribers(monkeypatch: pytest.MonkeyPatch) -> None:
    import run.subscriptions as subs
    calls = []

    def fake_get(url, api_key):
        calls.append(url)
        if "status=active" in url:
            return _stripe_page([_sub("sub_1", "Paying@Example.com")])
        return _stripe_page([_sub("sub_2", "trial@example.com")])

    monkeypatch.setattr(subs, "_stripe_get", fake_get)
    paid = subs.load_paid_from_stripe(api_key="sk_test_x")
    assert paid.covers("paying@example.com")     # normalised
    assert paid.covers("trial@example.com")      # trialing counts
    assert paid.source == "stripe"
    assert not any("sk_test_x" in c for c in calls)   # key never in a URL


def test_cancelled_but_still_inside_paid_period_still_gets_reports(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The requirement: someone who cancelled in October but paid through
    December keeps receiving. Stripe keeps them 'active' until the period ends,
    so querying active is exactly right — no date arithmetic on our side."""
    import run.subscriptions as subs
    monkeypatch.setattr(subs, "_stripe_get", lambda url, key: _stripe_page(
        [{"id": "sub_1", "cancel_at_period_end": True,
          "customer": {"email": "leaving@example.com"}}]
        if "status=active" in url else []))
    assert subs.load_paid_from_stripe(api_key="sk").covers("leaving@example.com")


def test_stripe_pagination_collects_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    import run.subscriptions as subs
    pages = {
        0: _stripe_page([_sub("sub_1", "a@example.com")], has_more=True),
        1: _stripe_page([_sub("sub_2", "b@example.com")], has_more=False),
    }
    seen = {"n": 0}

    def fake_get(url, key):
        if "status=trialing" in url:
            return _stripe_page([])
        page = pages[seen["n"]]
        seen["n"] += 1
        return page

    monkeypatch.setattr(subs, "_stripe_get", fake_get)
    paid = subs.load_paid_from_stripe(api_key="sk")
    assert paid.covers("a@example.com") and paid.covers("b@example.com")


def test_deleted_stripe_customer_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    import run.subscriptions as subs
    monkeypatch.setattr(subs, "_stripe_get", lambda url, key: _stripe_page(
        [_sub("sub_1", "gone@example.com", deleted=True)]))
    assert subs.load_paid_from_stripe(api_key="sk").emails == frozenset()


def test_malformed_stripe_page_does_not_crash_the_batch(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Stripe's response is external input like any other feed: a shape we did
    not expect must not raise out of the Tuesday run."""
    import run.subscriptions as subs
    monkeypatch.setattr(subs, "_stripe_get", lambda url, key: _stripe_page(
        ["not-a-dict", {"customer": "cus_123"}, {"customer": {"email": None}},
         _sub("sub_ok", "real@example.com")]))
    assert subs.load_paid_from_stripe(api_key="sk").emails == frozenset(
        {"real@example.com"})


def test_stripe_without_a_key_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    import run.subscriptions as subs
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    with pytest.raises(subs.SubscriptionError, match="STRIPE_API_KEY"):
        subs.load_paid_from_stripe()


def test_stripe_wins_over_csv_when_configured(monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    """Platform choice is a config change, not a rewrite: the batch never
    learns which source answered."""
    import run.subscriptions as subs
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setattr(subs, "_stripe_get", lambda url, key: _stripe_page(
        [_sub("sub_1", "fromstripe@example.com")] if "status=active" in url else []))
    paid = subs.resolve_paid_list(tmp_path / "unused.csv")
    assert paid.source == "stripe" and paid.covers("fromstripe@example.com")
    monkeypatch.delenv("STRIPE_API_KEY")
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("email,active_subscription\nfromcsv@example.com,true\n",
                        encoding="utf-8")
    assert subs.resolve_paid_list(csv_path).covers("fromcsv@example.com")


# --------------------------------------------------------------------- #
# Entitlement: who the paid check lets through
# --------------------------------------------------------------------- #

def _paid(*emails):
    from run.subscriptions import PaidList
    return PaidList(emails=frozenset(emails), source="stripe", status_column="active")


def test_a_league_pass_seat_survives_the_paid_check(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """The seat holder never paid us a cent — their commissioner did. Checking
    the seat's own email drops every seat and reports it in the words meant for
    a cancellation, making the $99 tier undeliverable except by disabling the
    cancellation gate for everyone. Runs the real batch filter, not PaidList."""
    import run.batch as batch
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    registry = _write_registry(tmp_path, [
        _entry(email="member@example.com", plan="league_pass",
               covered_by="commish@example.com")])
    export = _export(tmp_path, "email,active_subscription\n"
                               "commish@example.com,true\n")
    batch.main(["--week", "10", "--skip-ingest", "--registry", str(registry),
                "--paid-list", str(export), "--no-send"])
    out = capsys.readouterr().out
    assert "no longer paying" not in out, \
        "a covered seat was dropped as if it had cancelled"
    assert "1 reports written" in out


def test_a_seat_is_entitled_through_its_payer_not_itself() -> None:
    seat = Subscriber(email="member@example.com", user_id="1",
                      league_id="289646328504385536", rival_owner_id="2",
                      rival_roster_id=None, plan="league_pass",
                      covered_by="commish@example.com")
    paid = _paid("commish@example.com")
    assert not paid.covers(seat.email)                      # they never paid
    assert paid.covers(seat.covered_by or seat.email)       # but they are covered


def test_a_seat_dies_with_its_payer() -> None:
    """When the commissioner stops paying, the whole league stops — a seat must
    not outlive the pass that bought it."""
    seat = Subscriber(email="member@example.com", user_id="1",
                      league_id="289646328504385536", rival_owner_id="2",
                      rival_roster_id=None, plan="league_pass",
                      covered_by="lapsed@example.com")
    assert not _paid("someone-else@example.com").covers(seat.covered_by or seat.email)


def test_everyone_failing_the_paid_check_at_once_is_an_error_not_a_quiet_success(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A whole registry failing at once is far more likely to be a broken
    entitlement source than every customer cancelling in the same week. Exiting
    0 made that a green cron with an empty inbox."""
    import run.batch as batch
    registry = _write_registry(tmp_path, [_entry()])
    export = _export(tmp_path, "email,active_subscription\nnobody@example.com,true\n")
    code = batch.main(["--week", "10", "--skip-ingest", "--registry", str(registry),
                       "--paid-list", str(export), "--no-send"])
    assert code == 1, "a fully-empty entitled set must fail the run, not pass it"
    assert "NOTHING TO SEND" in capsys.readouterr().err


# --------------------------------------------------------------------- #
# Stale league id: the quietest way to break principle 3
# --------------------------------------------------------------------- #

def test_a_league_from_a_finished_season_refuses_to_render(tmp_path: Path) -> None:
    """Sleeper mints a NEW league id every season and the old one keeps
    resolving forever, out of a cache that never expires for a completed
    season. A renewed subscriber still carrying last year's id would otherwise
    get a complete, confident report about games played twelve months ago —
    no gap, no warning, exit code 0."""
    from engine.week_report import WeekReportError, build_week_report
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    stale = str(int(season.season) + 1)
    with pytest.raises(WeekReportError, match="new league id each season"):
        build_week_report(raw, season.league_id, twr.REPORT_WEEK, 1,
                          require_season=stale)


def test_the_guard_gates_on_staleness_only(tmp_path: Path) -> None:
    """It must not become a blanket refusal: the league's own season passes, and
    historical/demo renders (require_season unset) are unaffected."""
    from engine.week_report import build_week_report
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    assert build_week_report(raw, season.league_id, twr.REPORT_WEEK, 1,
                             require_season=season.season)["meta"]["season"]
    assert build_week_report(raw, season.league_id, twr.REPORT_WEEK, 1
                             )["meta"]["season"] == season.season


def test_current_nfl_season_reads_state(tmp_path: Path) -> None:
    from engine.week_report import current_nfl_season
    assert current_nfl_season(tmp_path) is None          # no state cached
    state = tmp_path / "state"
    state.mkdir()
    state.joinpath("nfl.json").write_text('{"league_season":"2026"}', encoding="utf-8")
    assert current_nfl_season(tmp_path) == "2026"
    state.joinpath("nfl.json").write_text('{"season":"not-a-year"}', encoding="utf-8")
    assert current_nfl_season(tmp_path) is None          # untrusted input


def test_a_subscriber_whose_report_failed_fails_the_run(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """One subscriber's report failing to build must fail the run even when
    every send that DID happen succeeded. The delivery block used to rebind the
    same name for send failures, so a run that quietly skipped somebody exited
    0 — a green cron with a paying subscriber missing."""
    import run.batch as batch
    import run.delivery as delivery
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    # Isolate the send log and outbox, or this test would mark the demo
    # subscriber as mailed and make its own second run a no-op.
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setattr(delivery, "DRY_OUTBOX", tmp_path / "outbox")
    registry = _write_registry(tmp_path, [
        _entry(),                                              # builds fine
        _entry(email="broken@example.com", user_id="111111111111",
               league_id="999999999999999999"),                # not cached
    ])
    code = batch.main(["--week", "10", "--skip-ingest", "--registry", str(registry),
                       "--no-paid-check", "--email-provider", "dry"])
    out = capsys.readouterr().out
    assert "1 reports written, 1 failed" in out
    assert "1 sent" in out, "the healthy subscriber should still be delivered"
    assert code == 1, "a failed report must not exit 0 just because sends worked"
