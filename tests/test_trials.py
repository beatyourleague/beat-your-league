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


def test_a_flood_is_bounded() -> None:
    rows = [_row(f"u{i}@example.com") for i in range(trials.MAX_PER_RUN + 20)]
    assert len(trials.pending(rows, set(), set(), "2026")) == trials.MAX_PER_RUN


def test_the_week_is_underway_from_the_main_sunday_slate() -> None:
    from run.solo import CACHE_DIR
    start = trials.main_slate_start(CACHE_DIR, "2024", 10)
    if start is None:                                   # pragma: no cover
        import pytest
        pytest.skip("schedule not cached")
    # 2024 week 10: Thursday night was Nov 7; the main slate Sunday Nov 10, 1 PM ET.
    assert start == datetime(2024, 11, 10, 18, tzinfo=timezone.utc)


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
