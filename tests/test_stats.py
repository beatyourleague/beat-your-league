"""`make stats` — the owner's view of demand, from data already stored.

The site has no analytics by promise, so this is the only view of whether
anyone is asking. It is the kind of output that gets pasted somewhere, so it
prints counts and never an address.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import run.stats as stats

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)

ROWS = [
    {"kind": "waitlist", "email": "a@example.com", "received_at": "2026-10-09T08:00:00Z"},
    {"kind": "waitlist", "email": "A@example.com", "received_at": "2026-09-01T08:00:00Z"},
    {"kind": "trial", "email": "j.o.e+x@gmail.com", "ref": "r", "received_at": "2026-10-05T08:00:00Z"},
    {"kind": "trial", "email": "joe@gmail.com", "ref": "r", "received_at": "2026-10-08T20:00:00Z"},
    {"kind": "trial", "email": "kim@example.com", "ref": "r", "received_at": "2026-10-01T08:00:00Z"},
    {"kind": "confirm", "code": "0" * 24, "received_at": "2026-10-09T09:00:00Z"},
    {"kind": "update_request", "email": "sub@example.com", "ref": "r",
     "received_at": "not a date"},
]


def test_counts_people_once_per_mailbox_and_by_recency() -> None:
    form = stats.form_summary(ROWS, NOW)
    assert form["waitlist"] == {"total": 2, "week": 1, "day": 1, "people": 1}
    # Gmail dots and +tags are one mailbox, as the free report counts them.
    assert form["trial"] == {"total": 3, "week": 2, "day": 1, "people": 2}
    assert form["confirm"]["total"] == 1 and form["confirm"]["people"] == 0
    # An unreadable stamp still counts toward "ever", never toward a window.
    assert form["update_request"] == {"total": 1, "week": 0, "day": 0, "people": 1}


def test_the_send_log_is_read_by_key_shape() -> None:
    entries = [{"key": k, "sent_at": "2026-10-06T12:00:00+00:00"} for k in (
        "2026-w05-0123456789", "2026-w05-abcdefabcd", "2026-w06-0123456789",
        "2026-w05-final-0123456789", "2025-w18-0123456789",
        "trial-2026-0123456789ab", "trial-2025-0123456789ab",
        "welcome-2026-10-02-0123456789", "confirm-01234567-0123456789")]
    sends = stats.send_summary(entries, "2026")
    assert sends["weekly"] == {5: 2, 6: 1}            # last season's week 18 is not this one
    assert sends["finals"] == {5: 1}
    assert sends["other"]["free reports"] == 1
    assert sends["other"]["welcome emails (new subscribers)"] == 1
    assert sends["other"]["roster-update confirmations"] == 1


def test_conversion_joins_on_the_mailbox() -> None:
    conv = stats.conversions(ROWS, ["Joe@gmail.com", "nobody@example.com"])
    assert conv == {"trial": (1, 2), "waitlist": (0, 1)}


def test_no_address_is_ever_printed(tmp_path, monkeypatch, capsys) -> None:
    import run.delivery as delivery
    import run.intake as intake
    log = tmp_path / "sent.jsonl"
    log.write_text(json.dumps({"key": "2026-w05-0123456789",
                               "sent_at": "2026-10-06T12:00:00+00:00"}) + "\n")
    registry = tmp_path / "rosters.json"
    registry.write_text("[]")
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: ROWS)
    assert stats.main(["--registry", str(registry), "--now", NOW.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "@" not in out
    assert "Free-report requests" in out and "W5 1" in out
    # Without the Worker it still prints what it has, and says why the rest is missing.
    monkeypatch.delenv("FORM_ENDPOINT")
    assert stats.main(["--registry", str(registry), "--now", NOW.isoformat()]) == 0
    assert "FORM_ENDPOINT is not set" in capsys.readouterr().out


def test_an_unreadable_worker_is_a_failure_not_a_quiet_zero(monkeypatch, capsys) -> None:
    import run.intake as intake

    def down(*a, **k):
        raise intake.IntakeError("HTTP 500")
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setattr(intake, "fetch_seats", down)
    assert stats.main(["--now", NOW.isoformat()]) == 1
    assert "Could not read the form Worker" in capsys.readouterr().out
