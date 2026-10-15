"""The free-trial command — the sell window's demo, held to report standards.

A free report is still a report: nothing guessed, nothing recorded where paying
subscribers' receipts live, and nothing mailed twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import run.trial as trial
from test_solo_run import OFFLINE, SEASON, WEEK, _cache


def _directory(tmp_path):
    return trial.load_week_data(_cache(tmp_path), SEASON, WEEK,
                                session=OFFLINE).directory


def test_a_decorated_roster_resolves(tmp_path) -> None:
    """What people actually paste: positions, byes, projections, team tags."""
    directory = _directory(tmp_path)
    ids = trial.resolve_roster(
        "Aaron Armstrong QB KC - BYE 10\nBell Cow (SF) 21.4\nDre Wideout • CIN\n",
        directory)
    assert len(ids) == 3 and len(set(ids)) == 3


def test_an_unknown_name_stops_the_run_and_names_the_line(tmp_path) -> None:
    """RULE R3: the person who typed it is one message away, and a confident
    report about the wrong player costs the sale."""
    directory = _directory(tmp_path)
    with pytest.raises(trial.TrialError, match="Nobody McFakename"):
        trial.resolve_roster("Aaron Armstrong\nNobody McFakename\n", directory)


def test_a_duplicate_is_refused(tmp_path) -> None:
    directory = _directory(tmp_path)
    with pytest.raises(trial.TrialError, match="twice"):
        trial.resolve_roster("Aaron Armstrong\nAaron Armstrong QB KC\n", directory)


def test_the_trial_key_is_stable_and_carries_no_address() -> None:
    """It lands in the committed send log."""
    key = trial.trial_key("Fan@Example.com", ["00-0000002", "00-0000001"],
                          "2026", 3)
    same = trial.trial_key("fan@example.com", ["00-0000001", "00-0000002"],
                           "2026", 3)
    assert key == same, "case and order must not change the key"
    assert "@" not in key and "fan" not in key
    assert key.startswith("trial-2026-w03-")


def test_a_trial_never_touches_the_ledger_or_the_registry(tmp_path,
                                                          monkeypatch) -> None:
    """The public record holds published subscriber calls only; padding it
    with trial rows nobody paid for would misstate the receipts. And a trial
    is not a subscription."""
    roster = tmp_path / "roster.txt"
    roster.write_text("Aaron Armstrong\nBell Cow\nCade Carter\nDre Wideout\n"
                      "Eli Slotside\nFrank Tighten\nGabe Fielder\n",
                      encoding="utf-8")
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    sent: list = []

    class _Provider:
        name = "test"

        def send(self, message, sender, reply_to):
            sent.append(message)
            return "mid"

    monkeypatch.setattr(trial, "build_provider", lambda _n=None: _Provider())
    import run.delivery as delivery
    real = delivery.send_all
    monkeypatch.setattr(
        trial, "send_all",
        lambda msgs, provider, resend_anyway=False: real(
            msgs, provider=provider, sent_log=tmp_path / "sent.jsonl",
            resend_anyway=resend_anyway))

    cache = _cache(tmp_path)
    code = trial.main(["--email", "fan@example.com", "--roster", str(roster),
                       "--template", "nokd", "--season", SEASON,
                       "--week", str(WEEK), "--cache", str(cache)])
    assert code == 0
    assert len(sent) == 1
    assert "Your free report" in sent[0].subject
    assert not list(tmp_path.rglob("calls.jsonl")), "a trial reached the ledger"
    assert not (tmp_path / "processed").exists()

    # And never twice for the same roster+address+week.
    code = trial.main(["--email", "fan@example.com", "--roster", str(roster),
                       "--template", "nokd", "--season", SEASON,
                       "--week", str(WEEK), "--cache", str(cache)])
    assert code == 0 and len(sent) == 1, "the trial re-sent on a re-run"


def test_too_few_players_asks_for_the_rest(tmp_path, capsys,
                                           monkeypatch) -> None:
    roster = tmp_path / "roster.txt"
    roster.write_text("Aaron Armstrong\nBell Cow\n", encoding="utf-8")
    code = trial.main(["--email", "fan@example.com", "--roster", str(roster),
                       "--template", "nokd", "--season", SEASON,
                       "--week", str(WEEK), "--cache", str(_cache(tmp_path))])
    assert code == 1
    assert "ask for the rest" in capsys.readouterr().err


def test_the_operators_free_report_carries_no_subscriber_only_lines(
        tmp_path, monkeypatch) -> None:
    """RQ-02, reproduced: `printf roster | python -m run.trial --email
    prospect@example.com --roster - --print` drafted "Subject: Your free file —
    Week 6…" and a body telling a prospect who had paid nothing "DONE WITH
    THIS? Cancel it yourself from your own billing page", "ROSTER CHANGED?
    Reply to this email … your next report follows it" and "Your results start
    here" — because run/trial.py never set meta["trial"], the flag every
    renderer reads (run/trials.py, the hourly free report, always did). Its
    --print text is pasted straight into the group chat it was asked in."""
    from render.report import CANCEL_TEXT
    monkeypatch.setenv("SITE_URL", "https://x.test")
    roster = tmp_path / "roster.txt"
    roster.write_text("Aaron Armstrong\nBell Cow\nCade Carter\nDre Wideout\n"
                      "Eli Slotside\nFrank Tighten\nGabe Fielder\n", encoding="utf-8")
    data = trial.load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE)
    ids = trial.resolve_roster(roster.read_text(), data.directory)
    spec = trial.RosterSpec(player_ids=tuple(ids), slots=trial.TEMPLATES["nokd"],
                            scoring="ppr", label="Your Team")
    report = trial.report_for(spec, data, league_size=12, cache_dir=_cache(tmp_path))
    report["meta"]["plan"] = "season"           # a stray plan must not survive
    plain, message = trial.trial_message(report, "prospect@example.com", ids,
                                         SEASON, WEEK)
    assert message.subject.startswith("Your free report — ")
    assert "file" not in message.subject.lower()
    for text in (plain, message.html):
        assert CANCEL_TEXT.split(" —")[0] not in text, "a prospect was told to cancel"
        assert "roster changed?" not in text.lower(), \
            "the subscriber's roster route leaked"
        assert "Your results start here" not in text
        assert "This one's on us" in text.replace("&#x27;", "'"), \
            "the free report's own footer is missing"
    assert "plan" not in report["meta"] and report["meta"]["trial"] is True
    assert message.unsubscribe is None
