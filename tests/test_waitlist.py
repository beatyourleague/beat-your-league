"""Tests for the launch announcement.

A waitlist can only be burned once, so the properties here are about restraint:
send it exactly once, send only what was promised, and never send by accident.
Nothing touches the network.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from render.report import BRAND_LINE
from run.delivery import Message, load_sent, send_all
from run.waitlist import (BODY, CAMPAIGN, FORBIDDEN_CLAIMS, SUBJECT, load_list,
                          main, messages)

EXPORT = """Email Address,Signed up
Fan@Example.com,2026-08-18
second@example.com,2026-08-18
not an email,2026-08-18
FAN@example.com,2026-08-19
,2026-08-19
third@example.com,2026-08-20
"""


@pytest.fixture()
def export(tmp_path: Path) -> Path:
    path = tmp_path / "waitlist.csv"
    path.write_text(EXPORT, encoding="utf-8")
    return path


# --------------------------------------------------------------------- #
# reading the list
# --------------------------------------------------------------------- #

def test_addresses_are_deduped_case_insensitively(export: Path) -> None:
    """Someone signs up twice, once shouting. Mailing them twice on the first
    contact is the worst possible first impression."""
    addresses, problems = load_list(export)
    assert addresses == ["fan@example.com", "second@example.com",
                         "third@example.com"]
    assert len(problems) == 1 and "row 4" in problems[0]


def test_a_renamed_column_is_found_not_silently_empty(tmp_path: Path) -> None:
    """Vendors spell it "Email Address", "email", "Subscriber". Returning an
    empty list because a header changed would look like nobody signed up."""
    for header in ("email", "Email Address", "EMAIL", "subscriber"):
        path = tmp_path / f"{header.replace(' ', '_')}.csv"
        path.write_text(f"{header},when\nsomeone@example.com,x\n", encoding="utf-8")
        assert load_list(path)[0] == ["someone@example.com"]


def test_a_file_with_no_email_column_raises_rather_than_returning_nothing(
        tmp_path: Path) -> None:
    path = tmp_path / "wrong.csv"
    path.write_text("name,when\nSomebody,x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_list(path)


def test_a_malformed_address_never_reaches_a_provider(export: Path) -> None:
    """One rejected recipient costs sending-domain reputation, and reputation
    is not recoverable inside a launch week."""
    addresses, _ = load_list(export)
    assert all("@" in a and " " not in a for a in addresses)


# --------------------------------------------------------------------- #
# what the announcement says
# --------------------------------------------------------------------- #

def test_the_announcement_promises_only_what_exists() -> None:
    """The product changed under this copy (PLAN §0). The waiver market needs a
    league transaction log we no longer read, the rival needs league history we
    no longer read, and the self-updating report is not built. This test exists
    because the first draft of this email promised two of those — inherited
    from BRAND_LINE, which still described the Sleeper product."""
    body = BODY.format(brand=BRAND_LINE.capitalize(), url="https://x/join/").lower()
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in body, (
            f"the launch email promises {claim!r}, which this product does not "
            f"do — see PLAN §0 for what was removed")


def test_the_brand_line_no_longer_describes_the_sleeper_product() -> None:
    """BRAND_LINE renders in the report footer, the email footer AND this
    announcement, so a stale promise there is false on every surface at once."""
    assert "rival" not in BRAND_LINE.lower()
    assert "roster" in BRAND_LINE.lower()


def test_the_announcement_states_its_own_volume_and_exit() -> None:
    body = BODY.format(brand=BRAND_LINE.capitalize(), url="https://x/join/")
    assert "only one you are getting" in body
    assert "unsubscribe" in body.lower()


def test_the_signup_url_is_the_only_link() -> None:
    """A launch email with several destinations converts worse and looks like
    marketing. One address, one thing to do."""
    body = BODY.format(brand=BRAND_LINE.capitalize(), url="https://x/join/")
    assert body.count("http") == 1


# --------------------------------------------------------------------- #
# sending exactly once
# --------------------------------------------------------------------- #

def test_the_announcement_cannot_be_sent_twice(tmp_path: Path) -> None:
    """Keyed through the same send log the weekly batch uses. A re-run, a
    resumed workflow or a nervous second invocation must all be no-ops."""
    log = tmp_path / "sent.jsonl"

    class _Fake:
        name = "fake"
        def __init__(self) -> None:
            self.sent: list[str] = []
        def send(self, message: Message, sender: str, reply_to: str) -> str:
            self.sent.append(message.to)
            return f"fake:{message.key}"

    provider = _Fake()
    batch = messages(["a@example.com", "b@example.com"], "https://x/join/")
    first = send_all(batch, provider=provider, sent_log=log)
    assert [r.ok for r in first] == [True, True]
    assert len(provider.sent) == 2

    second = send_all(batch, provider=provider, sent_log=log)
    assert all(r.skipped for r in second), "the announcement went out twice"
    assert len(provider.sent) == 2, "a provider was called on a re-run"
    assert len(load_sent(log)) == 2


def test_the_key_is_per_campaign_so_a_later_send_is_still_possible() -> None:
    """This prevents DUPLICATES, not future sends. A second campaign — should
    one ever be promised and collected for — must not be silently swallowed by
    the first one's log entries."""
    keys = {m.key for m in messages(["a@example.com"], "https://x/join/")}
    assert keys == {f"{CAMPAIGN}-a@example.com"}
    assert CAMPAIGN in next(iter(keys))


# --------------------------------------------------------------------- #
# never by accident
# --------------------------------------------------------------------- #

def test_the_default_is_a_dry_run(export: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "should-not-be-used")
    assert main(["--list", str(export), "--url", "https://x/join/"]) == 0
    out = capsys.readouterr().out
    assert "via dry" in out and "nothing left this machine" in out


def test_asking_to_send_with_nothing_configured_fails_loudly(
        export: Path, monkeypatch, capsys) -> None:
    """The lesson run/batch.py learned: a misconfigured send that prints a
    success and exits 0 is a launch that silently did not happen."""
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert main(["--list", str(export), "--url", "https://x/join/", "--send"]) == 1
    assert "NOTHING WAS SENT" in capsys.readouterr().err


def test_an_empty_list_refuses_rather_than_reporting_success(
        tmp_path: Path, capsys) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("email,when\n", encoding="utf-8")
    assert main(["--list", str(path), "--url", "https://x/join/"]) == 1
    assert "empty" in capsys.readouterr().err
