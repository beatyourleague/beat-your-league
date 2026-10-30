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
from run.waitlist import (BODY, CAMPAIGN, FORBIDDEN_CLAIMS, SUBJECT, compose,
                          load_list, main, messages)

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
    body = compose("https://x/join/", "Beat Your League · PO Box 1 · hello@beatyourleague.com", {})[1].lower()
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in body, (
            f"the launch email promises {claim!r}, which this product does not "
            f"do — see PLAN §0 for what was removed")


def test_the_brand_line_no_longer_describes_the_sleeper_product() -> None:
    """BRAND_LINE renders in the report footer, the email footer AND this
    announcement, so a stale promise there is false on every surface at once."""
    assert "rival" not in BRAND_LINE.lower()
    # Oct 30 2026: the tagline says what the roster product does for the
    # buyer ("your lineup, decided every Tuesday"), and never reads a league.
    assert "your lineup" in BRAND_LINE.lower() and "league's" not in BRAND_LINE.lower()


def test_the_announcement_states_its_own_volume_and_exit() -> None:
    body = compose("https://x/join/", "Beat Your League · PO Box 1 · hello@beatyourleague.com", {})[1]
    assert "only email you'll get" in body
    assert "unsubscribe" in body.lower()


def test_the_signup_url_is_the_only_link() -> None:
    """A launch email with several destinations converts worse and looks like
    marketing. One address, one thing to do."""
    body = compose("https://x/join/", "Beat Your League · PO Box 1 · hello@beatyourleague.com", {})[1]
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


def test_the_key_is_per_campaign_and_carries_no_address() -> None:
    """This prevents DUPLICATES, not future sends: a second campaign — should
    one ever be promised and collected for — must not be silently swallowed by
    the first one's log entries. And the key is a DIGEST of the address, never
    the address: sent.jsonl is committed by the crons, and a committed log
    must not hold the list itself."""
    [message] = messages(["a@example.com"], "https://x/join/")
    assert message.key.startswith(f"{CAMPAIGN}-")
    assert "@" not in message.key and "a@" not in message.key
    # Deterministic per address, distinct across addresses.
    assert messages(["a@example.com"], "https://x/join/")[0].key == message.key
    assert messages(["b@example.com"], "https://x/join/")[0].key != message.key


def test_the_worker_list_takes_only_waitlist_rows() -> None:
    """The Worker is the same mailbox the seats and roster updates use. A seat
    or update row carries a roster and a token; broadcasting to those
    addresses would email people who never asked for this message."""
    import run.waitlist as wl
    rows = [
        {"kind": "waitlist", "email": "a@example.com"},
        {"kind": "waitlist", "email": "A@Example.com"},   # dupe, case
        {"kind": "seat", "email": "b@example.com", "ref": "x",
         "covered_by": "c@example.com"},
        {"kind": "update", "email": "d@example.com", "ref": "y"},
        {"kind": "waitlist", "email": "not-an-email"},
        {"kind": "waitlist", "email": "e@example.com"},
    ]
    original = wl.fetch_seats
    wl.fetch_seats = lambda *a, **k: rows
    try:
        assert wl.load_worker_list("https://w.test", None) == [
            "a@example.com", "e@example.com"]
    finally:
        wl.fetch_seats = original


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
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 1, Somewhere")
    assert main(["--list", str(export), "--url", "https://x/join/", "--send"]) == 1
    assert "NOTHING WAS SENT" in capsys.readouterr().err


def test_the_launch_email_carries_a_sender_address_and_an_opt_out(
        export: Path, monkeypatch, capsys) -> None:
    """Launch audit L2/L3: the one commercial email had no postal address and
    no opt-out it explained (CAN-SPAM; CASL — the sender is in Ontario), and
    the brand line read "every tuesday". Without SENDER_POSTAL_ADDRESS a real
    send refuses; with it, every message carries the sender line, a reply
    opt-out and a mailto List-Unsubscribe."""
    from run.waitlist import messages
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS", raising=False)
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    assert main(["--list", str(export), "--url", "https://x/join/", "--send"]) == 1
    assert "SENDER_POSTAL_ADDRESS" in capsys.readouterr().err
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 1, Somewhere")
    message = messages(["fan@example.com"], "https://x/join/")[0]
    assert "Beat Your League · PO Box 1, Somewhere · hello@beatyourleague.com" in message.text
    assert 'reply "unsubscribe"' in message.text
    assert message.unsubscribe == "mailto:hello@beatyourleague.com?subject=unsubscribe"
    assert "every Tuesday" in message.text and "every tuesday" not in message.text


def test_an_empty_list_refuses_rather_than_reporting_success(
        tmp_path: Path, capsys) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("email,when\n", encoding="utf-8")
    assert main(["--list", str(path), "--url", "https://x/join/"]) == 1
    assert "empty" in capsys.readouterr().err


def test_the_url_defaults_from_site_url_so_the_runbook_command_works(
        export: Path, monkeypatch, capsys) -> None:
    """The runbook command is `run.waitlist` with no --url. That works
    only because the link defaults from the SITE_URL secret that already
    exists — and with neither set, the run refuses rather than announcing a
    signup page at no address."""
    monkeypatch.delenv("SITE_URL", raising=False)
    assert main(["--list", str(export)]) == 1
    assert "SITE_URL" in capsys.readouterr().err
    monkeypatch.setenv("SITE_URL", "https://example.com/")
    sent: list = []
    import run.waitlist as wl
    original = wl.send_all
    wl.send_all = lambda msgs, provider: sent.extend(msgs) or []
    try:
        assert main(["--list", str(export)]) == 0
    finally:
        wl.send_all = original
    assert sent and all("https://example.com/join/" in m.text for m in sent)


# --------------------------------------------------------------------- #
# the roster a closed checkout saved (contract C6) and opening morning (OPS-13)
# --------------------------------------------------------------------- #

def _roster_ref() -> str:
    from run.refs import encode_roster
    from test_solo_run import SLOTS, _pid
    return encode_roster("season", "ppr", list(SLOTS), [_pid(i) for i in range(1, 9)])


def test_a_saved_roster_comes_back_in_that_persons_launch_email(monkeypatch,
                                                                 capsys) -> None:
    """Contract C6. A visitor who checked a roster while checkout was closed
    left only an address on the list, so the one launch email sent them back
    to an empty page and fifteen names to type again — the step most of them
    will not repeat. The join page now saves the ref checkout would have used
    on the waitlist row, and that person's email links SITE_URL/join/?ref=<ref>,
    which the page decodes back into the roster and its settings. Everybody
    else's email is unchanged, one link each, and a ref that does not decode
    is never put in a link."""
    import run.waitlist as wl
    ref = _roster_ref()
    rows = [
        {"kind": "waitlist", "email": "saved@example.com", "ref": "s3-old"},
        {"kind": "waitlist", "email": "saved@example.com", "ref": ref},
        {"kind": "waitlist", "email": "plain@example.com"},
        {"kind": "waitlist", "email": "junk@example.com", "ref": "s3-not-a-roster"},
        {"kind": "trial", "email": "trial@example.com", "ref": ref},
    ]
    assert wl.saved_refs(rows) == {"saved@example.com": ref}
    monkeypatch.setenv("SITE_URL", "https://example.com")
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setattr(wl, "fetch_seats", lambda *a, **k: rows)
    sent: list = []
    monkeypatch.setattr(wl, "send_all", lambda msgs, provider: sent.extend(msgs) or [])
    assert main([]) == 0
    by_to = {m.to: m for m in sent}
    assert set(by_to) == {"saved@example.com", "plain@example.com", "junk@example.com"}
    restore = f"https://example.com/join/?ref={ref}"
    saved = by_to["saved@example.com"]
    assert restore in saved.text and restore in saved.html
    assert wl.SAVED_LINE in saved.text and saved.text.count("http") == 1
    for other in ("plain@example.com", "junk@example.com"):
        assert "?ref=" not in by_to[other].text and wl.SAVED_LINE not in by_to[other].text
        assert "https://example.com/join/" in by_to[other].text
    assert "with their roster: 1" in capsys.readouterr().out
    # The query is joined, never doubled, when --url already carries one.
    assert wl.restore_url("https://x/join/?via=x", ref) == f"https://x/join/?via=x&ref={ref}"


def test_opening_morning_says_every_missing_setting_at_once(monkeypatch, capsys,
                                                             export: Path) -> None:
    """OPS-13, reproduced: nothing said which settings `run.waitlist --send`
    needs, so they surfaced one refusal at a time — and EMAIL_FROM, which
    run/delivery.py silently defaults to a placeholder at example.invalid,
    surfaced as nothing at all. A provider named without its key raised a
    traceback. Now a real send names everything missing before reading a
    list, and `make waitlist-send` is the one command the runbook points at."""
    import run.waitlist as wl
    for name in ("EMAIL_PROVIDER", "EMAIL_FROM", "SENDER_POSTAL_ADDRESS",
                 "RESEND_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    assert main(["--list", str(export), "--url", "https://x/join/", "--send"]) == 1
    err = capsys.readouterr().err
    assert "NOTHING WAS SENT" in err
    for name in ("EMAIL_FROM", "SENDER_POSTAL_ADDRESS", "RESEND_API_KEY"):
        assert name in err, f"{name} was not named"
    monkeypatch.setenv("EMAIL_FROM", "Beat Your League <hi@example.com>")
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 1")
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    assert wl.send_env_missing() == []
    makefile = (Path(__file__).resolve().parent.parent / "Makefile").read_text()
    send = makefile.split("\nwaitlist-send:", 1)[1].split("\n\n", 1)[0]
    assert "-m run.waitlist --send" in send
    preview = makefile.split("\nwaitlist-preview:", 1)[1].split("\n\n", 1)[0]
    assert "-m run.waitlist" in preview and "--send" not in preview
    assert "sent.jsonl" in makefile.split("\nwaitlist-preview:", 1)[0].rsplit("\n\n", 1)[1], \
        "the target's comment must say to commit the send log afterwards"


def test_the_launch_email_is_the_brands_shell_with_one_button_that_fits_a_phone(
        monkeypatch) -> None:
    """Reproduced (PANEL:R2): the one email every waitlister gets was a bare
    <div> of Arial paragraphs whose call to action was the join URL printed
    as text twice (the second time after the postal address). With a saved
    roster that URL runs ~100 characters with a 60-character stretch that
    cannot wrap, and a 390px phone laid the email out at 579-690px. It now
    wears the welcome email's shell — masthead, preview line, light-only
    colour scheme — with ONE button-styled link ("Pick up where you left off"
    when it carries their roster), the URL only as that button's href, and
    the sender block once. Every client rule the other emails are held to."""
    import html as _html
    import re

    import run.waitlist as wl
    from test_email_safety import FORBIDDEN
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 123, Toronto ON M5V 1A1")
    ref = _roster_ref() + "_via-reply-kit"
    saved, plain = wl.messages(["a@example.com", "b@example.com"],
                               "https://example.com/join/", {"a@example.com": ref})
    for message, label in ((saved, "Pick up where you left off"),
                           (plain, "Set up my team")):
        page = message.html
        assert page.lstrip().lower().startswith("<!doctype html")
        assert 'name="viewport"' in page and 'lang="en"' in page and "<title>" in page
        assert '<meta name="color-scheme" content="light only">' in page
        assert "&#847;&zwnj;&nbsp;" in page, "no padded preview line"
        assert "Signups are open" in page
        assert not [p for p in FORBIDDEN if re.search(p, page, re.I)]
        assert not re.findall(r'<table(?![^>]*role="presentation")', page)
        hrefs = re.findall(r'href="([^"]*)"', page)
        assert len(hrefs) == 1 and _html.unescape(hrefs[0]) == wl.restore_url(
            "https://example.com/join/", ref if message is saved else None)
        assert f">{label}</a>" in page
        text_nodes = _html.unescape(re.sub(r"<[^>]+>", " ", re.sub(
            r"<(title|style)[^>]*>.*?</\1>", "", page, flags=re.S)))
        assert "https://" not in text_nodes, "a URL is printed as text again"
        assert max((len(w) for w in text_nodes.split()), default=0) <= 40, \
            "an unbreakable run wider than a phone"
        assert page.count("PO Box 123") == 1, "the sender block is not printed once"
    assert wl.SAVED_LINE in _html.unescape(saved.html)
    assert wl.SAVED_LINE not in _html.unescape(plain.html)
    # The plain-text half keeps the link printed, where a text client needs it.
    assert wl.restore_url("https://example.com/join/", ref) in saved.text
