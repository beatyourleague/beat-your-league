"""The free first report (run/trials.py) — one per person, never a purchase,
never recorded, never about games already underway."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import run.trials as trials
from run.refs import encode_roster

ROOT = Path(__file__).resolve().parent.parent
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
from render.sample import SAMPLE_ROSTER  # noqa: E402

REF = encode_roster("season", "ppr", SLOTS, list(SAMPLE_ROSTER))
# The Worker's own stamp on a request, a day before the tests' THURSDAY: fresh
# for every `now` below. SINCE is what not_before() answers around then.
FRESH = "2025-12-31T12:00:00.000Z"
SINCE = datetime(2025, 12, 20, tzinfo=timezone.utc)


def _row(email="fan@example.com", ref=REF, kind="trial", received_at=FRESH):
    row = {"kind": kind, "email": email, "ref": ref}
    if received_at is not None:
        row["received_at"] = received_at
    return row


def test_one_per_person_never_a_subscriber_newest_request_wins() -> None:
    other = encode_roster("season", "half_ppr", SLOTS, list(SAMPLE_ROSTER))
    rows = [_row(), _row(ref=other), _row("sub@example.com"),
            _row("bad-address"), _row("x@example.com", ref="garbage"),
            _row("w@example.com", kind="waitlist")]
    got = trials.pending(rows, {"sub@example.com"}, set(), "2026", since=SINCE)
    assert got == [("fan@example.com", other)]
    sent = {trials.trial_key("2026", "Fan@Example.com ")}
    assert trials.pending(rows, {"sub@example.com"}, sent, "2026", since=SINCE) == []
    # A new season is a new free report; the key carries no address.
    assert trials.pending(rows, set(), sent, "2027", since=SINCE)
    assert "@" not in trials.trial_key("2026", "fan@example.com")


def test_one_person_is_one_address_however_it_is_spelled() -> None:
    """`+tag` aliases and Gmail dots are the same mailbox: without this a free
    report could be had again and again, and a subscriber could get one."""
    c = trials.canonical_email
    assert c(" Fan+promo@Example.com ") == "fan@example.com"
    assert c("f.a.n@gmail.com") == c("fan+x@googlemail.com") == "fan@gmail.com"
    assert c("f.a.n@example.com") == "f.a.n@example.com"      # dots only matter to Gmail
    sent = {trials.trial_key("2026", "real@fan.com")}
    rows = [_row("real+2@fan.com"), _row("sub+x@fan.com"), _row("new@fan.com")]
    assert trials.pending(rows, {"sub@fan.com"}, sent, "2026", since=SINCE) == \
        [("new@fan.com", REF)]
    assert trials.trial_key("2026", "R.E.A.L+1@gmail.com") == trials.trial_key("2026", "real@gmail.com")


def test_only_a_fresh_request_made_this_season_is_ever_mailed() -> None:
    """Launch review OPS-3, reproduced: a request stamped 2025-10-20 whose
    `trial-2025-…` key was already in the send log was mailed AGAIN by a run
    on 2026-06-03 — "Your free report: Week 1, decided", eight months after
    anyone asked, from last season's roster — because the key is per season
    and the Worker keeps rows ~400 days. A request is mailed within
    TRIAL_MAX_AGE of arriving, never before the current season's first game,
    and never without the Worker's stamp (it cannot be shown to be fresh)."""
    assert trials.TRIAL_MAX_AGE.days == 14
    now = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)
    opener = datetime(2026, 9, 11, 0, 20, tzinfo=timezone.utc)
    since = trials.not_before(now, opener)
    assert since == now - trials.TRIAL_MAX_AGE
    for days, kept in ((13, True), (14, True), (15, False), (240, False)):
        stamp = (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        got = trials.pending([_row(received_at=stamp)], set(), set(), "2026",
                             since=since)
        assert bool(got) is kept, (days, got)
    # The repro, exactly: served last season, keyed for last season.
    stale = _row(received_at="2025-10-20T18:00:00.000Z")
    served = {trials.trial_key("2025", "fan@example.com")}
    june = datetime(2026, 6, 3, 15, 30, tzinfo=timezone.utc)
    assert trials.pending([stale], set(), served, "2026",
                          since=trials.not_before(june, opener)) == []
    # Early in a season the opener is the floor, not the fortnight.
    week2 = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
    assert trials.not_before(week2, opener) == opener
    before_opener = _row(received_at="2026-09-08T12:00:00.000Z")
    assert trials.pending([before_opener], set(), set(), "2026",
                          since=trials.not_before(week2, opener)) == []
    # No readable stamp, or no readable opener: nothing is fresh.
    for bad in (None, "", "yesterday"):
        assert trials.pending([_row(received_at=bad)], set(), set(), "2026",
                              since=since) == [], bad
    assert trials.not_before(now, None) is None
    assert trials.pending([_row(received_at=now.isoformat())], set(), set(),
                          "2026", since=None) == []


def test_the_cap_counts_built_reports_so_junk_cannot_starve_real_requests() -> None:
    rows = [_row(f"u{i}@example.com") for i in range(trials.MAX_PER_RUN + 20)]
    assert len(trials.pending(rows, set(), set(), "2026", since=SINCE)) == \
        trials.MAX_PER_RUN + 20, \
        "pending() must not slice: the cap belongs after the build, on built reports"
    import inspect
    body = inspect.getsource(trials.main)
    # The per-run and the per-day caps both bound BUILT reports (`limit` is
    # the smaller of the two); the daily-cap test below pins the behaviour.
    assert "len(messages) >= limit" in body and "not in known" in body
    assert "min(MAX_PER_RUN, room)" in body


def test_the_week_is_underway_from_its_first_kickoff() -> None:
    """A Thursday-night game means a Friday request is about a week already
    underway; the cutoff used to be Sunday 1 PM and mailed it anyway."""
    from run.solo import CACHE_DIR
    start = trials.week_underway_from(CACHE_DIR, "2024", 10)
    if start is None:                                   # pragma: no cover
        import pytest
        pytest.skip("schedule not cached")
    # 2024 week 10: Thursday Nov 7, 8:15 PM ET.
    assert start == datetime(2024, 11, 8, 1, 15, tzinfo=timezone.utc)


def test_a_bad_request_never_fails_the_run_and_the_free_report_carries_no_subscription_headers(
        tmp_path, monkeypatch, capsys) -> None:
    """The public form makes a bad row remotely triggerable, and the hourly cron
    files an issue for every failed run: an unbuildable roster is skipped and
    named, exit 0. And a free report has no list to leave, so no
    List-Unsubscribe header pointing at the subscription-cancel page."""
    import run.delivery as delivery
    import run.intake as intake
    from test_solo_run import SEASON, WEEK, _cache
    from test_tuesday import REF as FIXTURE_REF, ROSTER_IDS
    from test_tuesday import SLOTS as FIXTURE_SLOTS
    ghost = encode_roster("season", "ppr", list(FIXTURE_SLOTS),
                          list(ROSTER_IDS[:-1]) + ["00-0099999"])
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: [
        _row("bad@example.com", ref=ghost),
        _row("good@example.com", ref=FIXTURE_REF)])
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    sent = []

    class Fake:
        name = "fake"

        def send(self, message, sender, reply_to):
            sent.append(message)
            return "id"
    monkeypatch.setattr(delivery, "build_provider", lambda *a, **k: Fake())
    monkeypatch.setattr(trials, "current_season", lambda *a, **k: SEASON, raising=False)
    monkeypatch.setattr("run.solo.current_season", lambda *a, **k: SEASON)
    monkeypatch.setattr("run.solo.current_week", lambda *a, **k: WEEK)
    monkeypatch.setattr("run.solo.season_over", lambda *a, **k: False)
    monkeypatch.setattr(trials, "week_underway_from",
                        lambda *a: datetime(2099, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(trials, "season_start", lambda *a: SINCE)
    monkeypatch.setattr("run.solo.CACHE_DIR", _cache(tmp_path))
    reg = tmp_path / "rosters.json"
    reg.write_text("[]")
    code = trials.main(["--registry", str(reg), "--now", "2026-01-01T00:00:00+00:00"])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "skipped as unbuildable" in out.out
    assert [m.to for m in sent] == ["good@example.com"], (out.out, out.err)
    assert all(m.unsubscribe is None for m in sent)
    # An unreadable registry fails CLOSED: nobody may be treated as a non-subscriber.
    reg.write_text("{not json")
    assert trials.main(["--registry", str(reg), "--now", "2026-01-01T00:00:00+00:00"]) == 1


def test_the_free_report_says_what_it_is_and_asks_nothing_of_a_non_subscriber() -> None:
    import render.sample as sample
    from render.email import render_email, text_summary
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        import pytest
        pytest.skip(f"sample data not cached: {exc}")
    report["meta"].pop("historical_demo", None)
    report["meta"].pop("anonymized_demo", None)
    report["meta"]["trial"] = True
    import html
    for body in (html.unescape(render_email(report)), text_summary(report)):
        assert "on us" in body and "only email we'll send you unless you sign up" in body
        # No subscription exists, so nothing about cancelling one, updating a
        # roster on file, or results they have none of.
        assert "Cancel it yourself" not in body and "billing page" not in body
        assert "Roster changed?" not in body and "ROSTER CHANGED?" not in body
        assert "Your results start here" not in body and "RECEIPTS" not in body


def test_the_try_mode_never_reaches_a_payment_and_the_contract_matches() -> None:
    join = (ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    handler = join.split('$("form-email").addEventListener')[1].split("const link = ")[0]
    assert "if (TRY_MODE)" in handler and "submitTrial(email, ref)" in handler
    post = join.split("function submitTrial")[1].split("function showSeatLink")[0]
    assert 'kind: "trial"' in post and "STRIPE_LINK" not in post
    worker = (ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
    assert '"trial"' in worker and 'kind === "trial"' in worker
    daily = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert "python -m run.trials" in daily
    landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    # The button exists but stays hidden until the backend and email are live.
    assert re.search(r'id="try-cta" hidden', landing)
    assert "const TRIAL_OPEN = false;" in landing
    privacy = (ROOT / "site" / "privacy.html").read_text(encoding="utf-8")
    assert "free report" in privacy


# --------------------------------------------------------------------- #
# before launch, Tuesday, and the daily allowance (Oct 2026)
# --------------------------------------------------------------------- #

THURSDAY = "2026-01-01T15:00:00+00:00"
TUESDAY_1PM = "2026-01-06T13:00:00+00:00"


def _drive(tmp_path, monkeypatch, capsys, *, rows, now, registry="[]", sent=()):
    """run.trials.main end to end on the fixture week, with a fake provider.
    `registry` is the file's text, or None for no file at all; `sent` is
    (key, sent_at) pairs already in the send log. -> (code, out, err, mailed)."""
    import run.delivery as delivery
    import run.intake as intake
    from test_solo_run import SEASON, WEEK, _cache
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: list(rows))
    log = tmp_path / "sent.jsonl"
    log.write_text("".join(json.dumps({"key": k, "provider": "resend",
                                       "message_id": "x", "sent_at": at}) + "\n"
                           for k, at in sent))
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    mailed = []

    class Fake:
        name = "fake"

        def send(self, message, sender, reply_to):
            mailed.append(message)
            return "id"
    monkeypatch.setattr(delivery, "build_provider", lambda *a, **k: Fake())
    monkeypatch.setattr("run.solo.current_season", lambda *a, **k: SEASON)
    monkeypatch.setattr("run.solo.current_week", lambda *a, **k: WEEK)
    monkeypatch.setattr("run.solo.season_over", lambda *a, **k: False)
    monkeypatch.setattr(trials, "week_underway_from",
                        lambda *a: datetime(2099, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(trials, "season_start", lambda *a: SINCE)
    monkeypatch.setattr("run.solo.CACHE_DIR", _cache(tmp_path))
    reg = tmp_path / "reg" / "rosters.json"
    reg.unlink(missing_ok=True)
    if registry is not None:
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text(registry)
    capsys.readouterr()
    code = trials.main(["--registry", str(reg), "--now", now])
    captured = capsys.readouterr()
    return code, captured.out, captured.err, mailed


def _fixture_ref() -> str:
    from test_tuesday import REF as FIXTURE_REF
    return FIXTURE_REF


def test_with_the_form_live_before_checkout_opens_the_hourly_run_stays_green(
        tmp_path, monkeypatch, capsys) -> None:
    """FORM_ENDPOINT set while checkout is still closed: the registry file does
    not exist yet, and run.trials loaded it FIRST — so every hourly daily-intake
    run went red over a file nobody could have written. Now the registry is
    read only when there is a request to check, and a missing one while no
    Stripe key exists reads as nobody subscribing (nobody can have paid)."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    waitlist_only = [{"kind": "waitlist", "email": "w@example.com"}]
    for registry in (None, "{not json"):        # not even read: nothing pending
        code, out, err, _ = _drive(tmp_path, monkeypatch, capsys, rows=waitlist_only,
                                   now=THURSDAY, registry=registry)
        assert code == 0 and "none pending" in out, err
    code, _, err, mailed = _drive(
        tmp_path, monkeypatch, capsys, rows=[_row("fan@example.com", ref=_fixture_ref())],
        now=THURSDAY, registry=None)
    assert code == 0, err
    assert [m.to for m in mailed] == ["fan@example.com"]


def test_a_missing_registry_after_launch_still_fails_closed(
        tmp_path, monkeypatch, capsys) -> None:
    """Once a Stripe key exists the intake writes the registry every run, so a
    missing one is a lost cache — and reading it as empty would offer every
    paying subscriber a "free" report. Corrupt fails closed regardless."""
    rows = [_row("fan@example.com", ref=_fixture_ref())]
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    code, _, err, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows,
                                  now=THURSDAY, registry=None)
    assert code == 1 and not mailed and "unreadable" in err
    monkeypatch.delenv("STRIPE_API_KEY")
    code, _, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows,
                                now=THURSDAY, registry="{not json")
    assert code == 1 and not mailed


def test_on_tuesday_paying_subscribers_go_first(tmp_path, monkeypatch, capsys) -> None:
    """Requests held from Thursday's kickoff all come due on Tuesday morning —
    the same morning as every paid report, on a sending allowance of 100 a day.
    Until the Tuesday run's "finished" marker is in the send log, or 20:00 UTC,
    free reports wait. Before launch there is nothing to wait for."""
    from run.watchdog import run_key
    from test_solo_run import SEASON, WEEK
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    rows = [_row("fan@example.com", ref=_fixture_ref())]
    code, out, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows,
                                  now=TUESDAY_1PM)
    assert code == 0 and not mailed and "go out first" in out
    finished = [(run_key("tuesday", SEASON, WEEK), TUESDAY_1PM)]
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=TUESDAY_1PM,
                        sent=finished)
    assert len(mailed) == 1
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows,
                        now="2026-01-06T20:00:00+00:00")
    assert len(mailed) == 1, "a Tuesday that never finished holds them all day"
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=TUESDAY_1PM,
                        registry=None)                          # before launch
    assert len(mailed) == 1


def test_a_stale_request_is_never_mailed_and_never_spends_the_allowance(
        tmp_path, monkeypatch, capsys) -> None:
    """OPS-3 end to end. The Worker hands back every row it still holds,
    oldest first: a request from months ago was mailed again as if new, and a
    backlog of them took the day's allowance ahead of the person who asked an
    hour ago. With one slot left today, the fresh request gets it."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    stale = _row("old@example.com", ref=_fixture_ref(),
                 received_at="2025-10-20T18:00:00.000Z")
    fresh = _row("new@example.com", ref=_fixture_ref())
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=[stale], now=THURSDAY)
    assert mailed == [], "a request from October was mailed in January"
    today = [(f"trial-2024-{i:012x}", "2026-01-01T09:00:00+00:00")
             for i in range(trials.TRIAL_DAILY_CAP - 1)]
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=[stale, fresh],
                        now=THURSDAY, sent=today)
    assert [m.to for m in mailed] == ["new@example.com"]


def test_free_reports_stop_at_the_daily_allowance(tmp_path, monkeypatch, capsys) -> None:
    """At most TRIAL_DAILY_CAP a UTC day, counted from the send log — so the
    hourly runs together cannot spend the provider's free tier (100 a day) that
    welcomes, roster reports and Tuesday's paid reports also need. Yesterday's
    sends do not count against today."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    cap = trials.TRIAL_DAILY_CAP
    assert 0 < cap <= 40
    rows = [_row(f"new{i}@example.com", ref=_fixture_ref()) for i in range(3)]
    today = [(f"trial-2024-{i:012x}", "2026-01-01T09:00:00+00:00")
             for i in range(cap - 1)]
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=THURSDAY,
                        sent=today)
    assert len(mailed) == 1
    full = today + [("trial-2024-ffffffffffff", "2026-01-01T10:00:00+00:00")]
    code, out, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows,
                                  now=THURSDAY, sent=full)
    assert code == 0 and not mailed and "have gone out" in out
    yesterday = [(k, "2025-12-31T23:59:59+00:00") for k, _ in full]
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=THURSDAY,
                        sent=yesterday)
    assert len(mailed) == 3
