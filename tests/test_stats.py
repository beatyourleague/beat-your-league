"""`make stats` — the owner's view of demand, from data already stored.

The site has no analytics by promise, so this is the only view of whether
anyone is asking. It is the kind of output that gets pasted somewhere, so it
prints counts and never an address.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

import run.stats as stats

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_live_stripe(monkeypatch):
    """A developer shell may export a real key; no test here talks to Stripe
    unless it installs the fake below itself."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)

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


# --------------------------------------------------------------------- #
# channels — the optional "via" tag on a form row
# --------------------------------------------------------------------- #

def test_channels_are_counted_per_kind_and_a_bad_tag_is_never_printed(
        tmp_path, monkeypatch, capsys) -> None:
    """The Worker stores ``via`` as ^[a-z0-9-]{1,24}$, but a row is external
    input whatever the Worker promises. A tag that is not that shape — an
    address pasted into the link, say — is counted as unreadable and never
    printed, because this output gets pasted into chats and notes."""
    import run.delivery as delivery
    import run.intake as intake
    rows = ROWS + [
        {"kind": "waitlist", "email": "b@example.com", "via": "x-reply",
         "received_at": "2026-10-08T08:00:00Z"},
        {"kind": "waitlist", "email": "c@example.com", "via": "x-reply",
         "received_at": "2026-10-08T09:00:00Z"},
        {"kind": "trial", "email": "d@example.com", "via": "reddit",
         "received_at": "2026-10-08T09:00:00Z"},
        {"kind": "trial", "email": "e@example.com", "via": "joe@example.com",
         "received_at": "2026-10-08T09:00:00Z"},
        {"kind": "trial", "email": "f@example.com", "via": "UPPER",
         "received_at": "2026-10-08T09:00:00Z"},
    ]
    channels = stats.channel_summary(rows)
    assert channels["waitlist"] == {"x-reply": 2, stats.NO_VIA: 2}
    assert channels["trial"] == {"reddit": 1, stats.BAD_VIA: 2, stats.NO_VIA: 3}

    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: rows)
    assert stats.main(["--registry", str(tmp_path / "none.json"),
                       "--now", NOW.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "Waitlist sign-ups              x-reply 2, (no tag) 2" in out
    assert "reddit 1, (no tag) 3, (unreadable tag) 2" in out
    assert "@" not in out and "UPPER" not in out


def test_rows_with_no_tag_at_all_say_so() -> None:
    assert stats._channel_lines(stats.channel_summary(ROWS)) == [
        "  No row carries a channel (via) tag yet."]


# --------------------------------------------------------------------- #
# payments — read-only Stripe, fail soft
# --------------------------------------------------------------------- #

def _sub(interval: str, amount: int, **extra) -> dict:
    return {"id": f"sub_{interval}_{amount}_{len(extra)}", "status": "active",
            "items": {"data": [{"price": {"recurring": {"interval": interval},
                                          "unit_amount": amount, "currency": "usd"}}]},
            **extra}


class _FakeStripe:
    """Answers the three list endpoints, records every URL asked for, and
    fails the ones it is told to — the way a restricted key without a
    permission does."""

    def __init__(self, fail: dict | None = None, shapes: dict | None = None) -> None:
        self.urls: list[str] = []
        self.fail = fail or {}
        self.shapes = shapes or {}

    def __call__(self, url: str, api_key: str) -> dict:
        self.urls.append(url)
        path = urlsplit(url).path.removeprefix("/v1/")
        if path in self.fail:
            raise self.fail[path]
        if path in self.shapes:
            return self.shapes[path]
        query = parse_qs(urlsplit(url).query)
        if path == "subscriptions" and "starting_after" not in query:
            return {"data": [_sub("year", 3900),
                             _sub("year", 3900, cancel_at_period_end=True)],
                    "has_more": True}
        if path == "subscriptions":
            return {"data": [_sub("month", 1499, cancel_at=1767225600),
                             _sub("year", 9900)], "has_more": False}
        if path == "checkout/sessions":
            return {"data": [
                {"id": "cs_1", "status": "complete",
                 "customer_details": {"email": "buyer@example.com"}},
                {"id": "cs_2", "status": "expired", "customer_email": "x@example.com"},
                {"id": "cs_3", "status": "expired"}, {"id": "cs_4", "status": "open"}],
                "has_more": False}
        if path == "refunds":
            return {"data": [{"id": "re_1", "status": "succeeded"},
                             {"id": "re_2", "status": "failed"}], "has_more": False}
        raise AssertionError(f"unexpected Stripe call {url}")


def test_payments_are_counted_from_the_price_and_the_windows(monkeypatch) -> None:
    """Plan from each subscription's OWN price (RULE B2), every page read,
    checkouts over the last 7 days and refunds over the last 30 asked of
    Stripe by creation time — counts only, though the rows carry addresses."""
    import run.subscriptions as subscriptions
    fake = _FakeStripe()
    monkeypatch.setattr(subscriptions, "_stripe_get", fake)
    lines = stats.stripe_summary("rk_test_x", NOW)
    assert lines == [
        "  Active subscriptions: 4 — yearly at $39.00 2 (1 set to end), "
        "monthly at $14.99 1 (1 set to end), yearly at $99.00 1",
        "  Checkouts, last 7 days: 4 created — 1 complete, 2 expired, 1 still open",
        "  Refunds, last 30 days: 1",
        "  Paid signups by channel (ever): none yet",
    ]
    windows = [(urlsplit(u).path, parse_qs(urlsplit(u).query).get("created[gte]"))
               for u in fake.urls]
    assert ("/v1/checkout/sessions", [str(int(NOW.timestamp()) - 7 * 86400)]) in windows
    assert ("/v1/refunds", [str(int(NOW.timestamp()) - 30 * 86400)]) in windows
    # The channel count reads every session ever, not the week.
    assert ("/v1/checkout/sessions", None) in windows
    assert "@" not in "\n".join(lines)


def test_a_part_stripe_will_not_show_says_so_and_the_rest_still_prints(
        tmp_path, monkeypatch, capsys) -> None:
    """A restricted key without Refunds access: that line says it could not be
    read — without Stripe's response body, which can quote a masked key — and
    subscriptions print as normal. An unrecognised response is a failure too,
    never a zero. The exit code is the rest of the page's."""
    import run.delivery as delivery
    import run.subscriptions as subscriptions
    denied = subscriptions.SubscriptionError(
        "Stripe returned HTTP 403. Check STRIPE_API_KEY is a valid secret key with "
        "read access. Response: {\"error\": {\"message\": \"The provided key "
        "'rk_live_********abcd' does not have the required permissions\"}}")
    fake = _FakeStripe(fail={"refunds": denied},
                       shapes={"checkout/sessions": {"object": "list"}})
    monkeypatch.setattr(subscriptions, "_stripe_get", fake)
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.setenv("STRIPE_API_KEY", "rk_test_x")
    assert stats.main(["--registry", str(tmp_path / "none.json"),
                       "--now", NOW.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "Active subscriptions: 4" in out
    assert ("Could not read refunds (Stripe returned HTTP 403. Check STRIPE_API_KEY "
            "is a valid secret key with read access — a restricted key needs Read "
            "on it).") in out
    assert "rk_live" not in out and "Response" not in out
    assert "Could not read checkout sessions" in out and "Checkouts, last 7 days" not in out
    assert "Refunds, last 30 days" not in out


def test_without_a_key_the_payment_view_says_why(tmp_path, monkeypatch, capsys) -> None:
    import run.delivery as delivery
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    assert stats.main(["--registry", str(tmp_path / "none.json"),
                       "--now", NOW.isoformat()]) == 0
    assert "STRIPE_API_KEY is not set in this shell" in capsys.readouterr().out


def test_paid_signups_are_counted_by_the_channel_their_payment_carried(
        monkeypatch) -> None:
    """G09 / contract C5, reproduced: `make stats` counted channels only on
    free form rows (who ASKED), while the checkout URL carried no tag at all,
    so the one number a partner deal needs — purchases by channel — could not
    be had. The join page now appends "_via-<tag>" to the payment's own
    reference; this counts PAID roster sessions by it, ever. An unpaid or
    incomplete session, and a Sleeper-era reference, are not this product's
    purchases."""
    import run.subscriptions as subscriptions
    from run.refs import encode_roster
    from test_solo_run import SLOTS, _pid
    ref = encode_roster("season", "ppr", list(SLOTS), [_pid(i) for i in range(1, 9)])

    def session(i, ref, status="complete", paid="paid"):
        return {"id": f"cs_{i}", "status": status, "payment_status": paid,
                "client_reference_id": ref,
                "customer_details": {"email": f"buyer{i}@example.com"}}
    sessions = [session(1, ref + "_via-reddit"), session(2, ref + "_via-reddit"),
                session(3, ref + "_via-x"), session(4, ref),
                session(5, ref + "_via-reddit", status="expired"),
                session(6, ref + "_via-x", paid="unpaid"),
                session(7, "s-123456-789012-345678")]          # Sleeper era
    fake = _FakeStripe(shapes={"checkout/sessions": {"data": sessions,
                                                     "has_more": False}})
    monkeypatch.setattr(subscriptions, "_stripe_get", fake)
    lines = stats.stripe_summary("rk_test_x", NOW)
    assert lines[-1] == "  Paid signups by channel (ever): reddit 2, x 1, (no tag) 1"
    assert "@" not in "\n".join(lines)
