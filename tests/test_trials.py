"""The free first report (run/trials.py) — one per person, never a purchase,
never recorded, never about games already underway."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import run.trials as trials
from run.refs import encode_roster

ROOT = Path(__file__).resolve().parent.parent
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
from render.sample import SAMPLE_ROSTER  # noqa: E402

REF = encode_roster("season", "ppr", SLOTS, list(SAMPLE_ROSTER))


def _row(email="fan@example.com", ref=REF, kind="trial"):
    return {"kind": kind, "email": email, "ref": ref}


def test_one_per_person_never_a_subscriber_newest_request_wins() -> None:
    other = encode_roster("season", "half_ppr", SLOTS, list(SAMPLE_ROSTER))
    rows = [_row(), _row(ref=other), _row("sub@example.com"),
            _row("bad-address"), _row("x@example.com", ref="garbage"),
            _row("w@example.com", kind="waitlist")]
    got = trials.pending(rows, {"sub@example.com"}, set(), "2026")
    assert got == [("fan@example.com", other)]
    sent = {trials.trial_key("2026", "Fan@Example.com ")}
    assert trials.pending(rows, {"sub@example.com"}, sent, "2026") == []
    # A new season is a new free report; the key carries no address.
    assert trials.pending(rows, set(), sent, "2027")
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
    assert trials.pending(rows, {"sub@fan.com"}, sent, "2026") == [("new@fan.com", REF)]
    assert trials.trial_key("2026", "R.E.A.L+1@gmail.com") == trials.trial_key("2026", "real@gmail.com")


def test_the_cap_counts_built_reports_so_junk_cannot_starve_real_requests() -> None:
    rows = [_row(f"u{i}@example.com") for i in range(trials.MAX_PER_RUN + 20)]
    assert len(trials.pending(rows, set(), set(), "2026")) == trials.MAX_PER_RUN + 20, \
        "pending() must not slice: the cap belongs after the build, on built reports"
    import inspect
    body = inspect.getsource(trials.main)
    assert "len(messages) >= MAX_PER_RUN" in body and "not in known" in body


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
    monkeypatch.setattr(trials, "week_underway_from",
                        lambda *a: datetime(2099, 1, 1, tzinfo=timezone.utc))
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
    assert trials.main(["--registry", str(reg)]) == 1


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
