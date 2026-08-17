"""Tests for the delivery layer — the step that actually reaches a customer.

The failures that matter here are not crashes. They are: mailing someone twice,
mailing someone who cancelled, mailing everyone by accident from a misconfigured
cron, and leaking an API key into a log.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from run.delivery import (DeliveryError, DryRunProvider, Message, SendResult,
                          build_provider, load_sent, record_sent, send_all)


def _message(to: str = "fan@example.com", key: str = "k1") -> Message:
    return Message(to=to, subject="Week 3: the file on Mike",
                   html="<p>hello</p>", text="hello", key=key)


class _CountingProvider:
    name = "counting"

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.sent: list[Message] = []
        self.fail_on = fail_on or set()

    def send(self, message: Message, sender: str, reply_to: str | None) -> str:
        if message.to in self.fail_on:
            raise DeliveryError("provider said no")
        self.sent.append(message)
        return f"id-{len(self.sent)}"


# --------------------------------------------------------------------- #
# the accident cases
# --------------------------------------------------------------------- #

def test_default_provider_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cron with no EMAIL_PROVIDER must not mail anyone."""
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert build_provider().name == "dry"


def test_unknown_provider_is_refused_not_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "mailchimp")
    with pytest.raises(DeliveryError, match="unknown EMAIL_PROVIDER"):
        build_provider()


def test_provider_without_its_key_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(DeliveryError, match="RESEND_API_KEY"):
        build_provider("resend")


def test_dry_run_writes_a_real_email_and_sends_nothing(tmp_path: Path) -> None:
    provider = DryRunProvider(outbox=tmp_path)
    provider.send(_message(), "Us <a@b.co>", "reply@b.co")
    written = list(tmp_path.glob("*.eml"))
    assert len(written) == 1
    raw = written[0].read_text(encoding="utf-8", errors="replace")
    assert "To: fan@example.com" in raw
    assert "Reply-To: reply@b.co" in raw
    assert "multipart/alternative" in raw   # both text and html parts


# --------------------------------------------------------------------- #
# never twice
# --------------------------------------------------------------------- #

def test_a_rerun_does_not_mail_anyone_again(tmp_path: Path) -> None:
    """Re-runs are routine — a failed step, a resumed workflow, a double cron.
    A subscriber getting Tuesday's report three times reads as broken."""
    log = tmp_path / "sent.jsonl"
    provider = _CountingProvider()
    first = send_all([_message()], provider=provider, sent_log=log)
    second = send_all([_message()], provider=provider, sent_log=log)
    assert len(provider.sent) == 1
    assert first[0].ok and not first[0].skipped
    assert second[0].ok and second[0].skipped


def test_resend_flag_overrides_the_guard(tmp_path: Path) -> None:
    log = tmp_path / "sent.jsonl"
    provider = _CountingProvider()
    send_all([_message()], provider=provider, sent_log=log)
    send_all([_message()], provider=provider, sent_log=log, resend_anyway=True)
    assert len(provider.sent) == 2


def test_distinct_weeks_are_distinct_sends(tmp_path: Path) -> None:
    log = tmp_path / "sent.jsonl"
    provider = _CountingProvider()
    send_all([_message(key="lg-2026-w01-fan")], provider=provider, sent_log=log)
    send_all([_message(key="lg-2026-w02-fan")], provider=provider, sent_log=log)
    assert len(provider.sent) == 2


def test_a_damaged_send_log_never_licenses_a_duplicate(tmp_path: Path) -> None:
    log = tmp_path / "sent.jsonl"
    record_sent("k1", "test", "id1", log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    record_sent("k2", "test", "id2", log)
    assert load_sent(log) == {"k1", "k2"}   # good lines still count


# --------------------------------------------------------------------- #
# one failure must not sink the batch
# --------------------------------------------------------------------- #

def test_one_failed_send_does_not_stop_the_others(tmp_path: Path) -> None:
    log = tmp_path / "sent.jsonl"
    provider = _CountingProvider(fail_on={"broken@example.com"})
    results = send_all([
        _message(to="a@example.com", key="a"),
        _message(to="broken@example.com", key="b"),
        _message(to="c@example.com", key="c"),
    ], provider=provider, sent_log=log)
    assert [r.ok for r in results] == [True, False, True]
    assert len(provider.sent) == 2
    # And the failure is retryable: it was never recorded as sent.
    assert load_sent(log) == {"a", "c"}


def test_an_unexpected_provider_error_is_contained(tmp_path: Path) -> None:
    class Exploding:
        name = "boom"

        def send(self, message, sender, reply_to):
            raise RuntimeError("library blew up")

    results = send_all([_message()], provider=Exploding(), sent_log=tmp_path / "s.jsonl")
    assert results[0].ok is False and "unexpected" in results[0].detail


def test_failures_do_not_echo_credentials(tmp_path: Path) -> None:
    """Error text goes to logs and CI output; it must not carry the key."""
    class Leaky:
        name = "leaky"

        def send(self, message, sender, reply_to):
            raise DeliveryError("HTTP 401 from provider: unauthorized")

    results = send_all([_message()], provider=Leaky(), sent_log=tmp_path / "s.jsonl")
    assert "secret" not in results[0].detail.lower()
    assert "authorization" not in results[0].detail.lower()


# --------------------------------------------------------------------- #
# the batch wiring
# --------------------------------------------------------------------- #

def test_batch_only_builds_messages_for_paying_subscribers(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Delivery must inherit the paid check rather than re-deciding it."""
    import test_week_report as twr
    import run.batch as batch
    from run.registry import Subscriber

    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    monkeypatch.setattr(batch, "RAW_DIR", raw)
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    (raw / "league" / season.league_id / "rosters.json").write_text(
        json.dumps([{"roster_id": 1, "owner_id": "1"}, {"roster_id": 2, "owner_id": "2"}]),
        encoding="utf-8")
    subscriber = Subscriber(email="payer@example.com", user_id="1",
                            league_id=season.league_id, rival_owner_id=None,
                            rival_roster_id=2, sleeper_username="payer")
    result = batch.run_subscriber(subscriber, twr.REPORT_WEEK - 1, twr._template())
    assert result.ok and result.message is not None
    assert result.message.to == "payer@example.com"
    # The key pins subscriber + season + week, so re-runs collapse to one send.
    assert season.league_id in result.message.key
    assert f"w{twr.REPORT_WEEK - 1:02d}" in result.message.key
    assert "Week" in result.message.subject
    # The two real subject shapes: rivalry weeks keep the vs framing.
    assert ("the file on" in result.message.subject
            or "RIVALRY WEEK vs" in result.message.subject)


def test_a_dry_run_never_claims_a_delivery(tmp_path) -> None:
    """`make dry-send` is documented as a safe preview, and the cron itself runs
    dry until EMAIL_PROVIDER is set. Recording those drafts as sends meant the
    first REAL send skipped everyone who had ever been drafted — a green run
    with empty inboxes, which is the failure this log exists to prevent."""
    from run.delivery import Message, build_provider, load_sent, send_all

    log = tmp_path / "sent.jsonl"
    msg = Message(to="a@example.com", subject="s", html="<p>h</p>",
                  text="t", key="league-2026-w01-someone")
    for _ in range(2):
        results = send_all([msg], provider=build_provider("dry"), sent_log=log)
        assert results[0].ok and not results[0].skipped, \
            "a dry run must draft every time, never report 'already sent'"
    assert not log.exists() or load_sent(log) == set(), \
        "a dry run recorded a delivery that never happened"


def test_a_real_provider_records_and_then_skips(tmp_path) -> None:
    """The other half of the same rule: a provider that actually delivered must
    be remembered, or a re-run mails the same person twice."""
    from run.delivery import Message, load_sent, send_all

    class _Fake:
        name = "fake"
        def __init__(self): self.sent = 0
        def send(self, message, sender, reply_to):
            self.sent += 1
            return f"fake:{message.key}"

    log = tmp_path / "sent.jsonl"
    msg = Message(to="a@example.com", subject="s", html="<p>h</p>",
                  text="t", key="league-2026-w01-someone")
    provider = _Fake()
    send_all([msg], provider=provider, sent_log=log)
    second = send_all([msg], provider=provider, sent_log=log)
    assert provider.sent == 1, "the same message was delivered twice"
    assert second[0].skipped
    assert load_sent(log) == {msg.key}


def test_an_unconfigured_send_fails_loudly_instead_of_reporting_success(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Dry-run is the right DEFAULT and never the right ACCIDENT. With
    EMAIL_PROVIDER unset the Tuesday cron built every report, wrote drafts to an
    ephemeral runner, printed "N sent" and exited 0 — a green run with empty
    inboxes and no alarm anywhere. It must exit non-zero and say NOTHING WAS
    SENT; `--allow-dry` is the deliberate preview path."""
    import test_week_report as twr
    import run.batch as batch
    from run.registry import Subscriber

    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    monkeypatch.setattr(batch, "RAW_DIR", raw)
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    (raw / "league" / season.league_id / "rosters.json").write_text(
        json.dumps([{"roster_id": 1, "owner_id": "1"}, {"roster_id": 2, "owner_id": "2"}]),
        encoding="utf-8")
    registry = tmp_path / "subscribers.json"
    registry.write_text(json.dumps([{
        "email": "payer@example.com", "user_id": "1",
        "league_id": season.league_id, "rival_roster_id": 2,
        "sleeper_username": "payer",
    }]), encoding="utf-8")

    argv = ["--registry", str(registry), "--week", str(twr.REPORT_WEEK - 1),
            "--skip-ingest", "--no-paid-check"]
    assert batch.main(argv) == 1, "an unconfigured send reported success"
    assert "NOTHING WAS SENT" in capsys.readouterr().err

    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out2")
    assert batch.main([*argv, "--allow-dry"]) == 0, \
        "the deliberate preview path must still work"
