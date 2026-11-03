"""The Trade Check (run/trades.py, render/trade_mail.py): what a deal does to a
lineup and its byes, with no verdict, no % and nothing recorded."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from render.trade_mail import TRADE_SAMPLE, trade_email
from run import trades
from run.refs import decode_roster, encode_roster
from run.trades import TradeAsk, asks_from, compare, team_for
from run.updates import origin_tag
from test_teams import PLAYERS, SECRET, SLOTS

NOW = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parent.parent


class Team:
    def __init__(self, start: int, email: str = "a@example.com", slug: str = "aaaaaaaaaa") -> None:
        self.email, self.slug = email, slug
        self.player_ids = tuple(PLAYERS[start:start + 15])


def ask(start: int = 2, **over) -> TradeAsk:
    ref = encode_roster("monthly", "ppr", SLOTS, PLAYERS[start:start + 15], 12)
    return TradeAsk(**{"email": "a@example.com", "ref": ref, "ts": NOW.isoformat(), **over})


def row(hours: int = 1, **over) -> dict:
    return {"email": "a@example.com", "ref": ask().ref,
            "received_at": (NOW - timedelta(hours=hours)).isoformat(), **over}


def test_an_address_with_no_plan_gets_nothing() -> None:
    assert team_for(ask(email="stranger@example.com"), [Team(0)], SECRET) is None


def test_a_mostly_different_roster_is_not_a_trade() -> None:
    """Otherwise this is a free report on a friend's team."""
    assert team_for(ask(start=2), [Team(0)], SECRET) is not None
    assert team_for(ask(start=12), [Team(0)], SECRET) is None


def test_a_tie_between_two_teams_is_no_answer() -> None:
    assert team_for(ask(start=2), [Team(0), Team(0, slug="bbbbbbbbbb")], SECRET) is None


def test_the_link_names_the_team() -> None:
    two = [Team(0), Team(0, slug="bbbbbbbbbb")]
    named = ask(start=2, owner=origin_tag("bbbbbbbbbb", SECRET))
    assert team_for(named, two, SECRET).slug == "bbbbbbbbbb"


def test_three_answers_a_day_and_nothing_stale() -> None:
    assert len(asks_from([row(h) for h in range(1, 7)], NOW)) == 3
    assert asks_from([row(24 * 4)], NOW) == []


def _report(ids, total, byes=()) -> dict:
    return {"meta": {"week": 10}, "matchup": {"you": {"projected_total": total}},
            "lineup": [{"slot": "RB", "player_id": pid, "player_name": pid.upper(),
                        "projected": 10.0, "season_per_game": 12.0, "last_three": [1, 2, 3]}
                       for pid in ids],
            "bench": [], "byes_ahead": list(byes)}


def test_the_comparison_reports_what_the_two_reports_printed() -> None:
    before = _report(["a", "b"], 100.0, [{"week": 12, "slots": ["QB"]}])
    after = _report(["a", "c"], 104.5)
    after["lineup"][1]["projected"] = 14.5
    out = compare(before, after)
    assert out["change"] == 4.5 and out["byes_before"] == ["Week 12: QB"]
    assert [m["was"] for m in out["moves"]] == ["B"] and not out["byes_after"]
    assert [g["name"] for g in out["gone"]] == ["B"]
    assert [a["name"] for a in out["added"]] == ["C"]


def test_a_missing_total_is_said_not_guessed() -> None:
    gone = _report(["a"], 100.0)
    gone["lineup"][0]["projected"] = None
    out = compare(gone, _report(["b"], 100.0))
    assert out["change"] is None
    assert "not comparing points" in trade_email(out)[2]


def test_a_held_back_total_still_shows_the_gap() -> None:
    """A starter on bye makes a report hold back its total; the gap between
    the two lineups doesn't depend on it."""
    out = compare(_report(["a"], None), _report(["b"], None))
    assert out["change"] == 0.0 and "Now:" not in trade_email(out)[2]


@pytest.mark.parametrize("words", trade_email(TRADE_SAMPLE, "Work", "https://x.test/u")[1:])
def test_the_answer_gives_no_verdict_and_no_percentage(words) -> None:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", words))
    assert "%" not in re.sub(r"width:\d+%|100%", "", plain)
    for word in ("should", "accept", "reject", "fleece", "win the trade", "worth it"):
        assert word not in plain.lower(), word
    assert "the decision is yours" in plain and "hasn't changed" in plain


def test_the_answer_says_how_to_make_it_real() -> None:
    assert "https://x.test/u" in trade_email(TRADE_SAMPLE, "", "https://x.test/u")[2]
    assert "Made the deal" not in trade_email(TRADE_SAMPLE)[2]


def test_a_named_team_is_in_the_subject() -> None:
    assert trade_email(TRADE_SAMPLE, "Work")[0] == "Your trade check: Work"
    assert trade_email(TRADE_SAMPLE, "Your Team")[0] == "Your trade check"


def test_the_workflow_runs_it_and_records_nothing() -> None:
    flow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert "run: .venv/bin/python -m run.trades" in flow
    source = (ROOT / "run" / "trades.py").read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]
    assert "record_delivered" not in code and "record_calls" not in code
    assert "write_plan" not in code and "append_update_log" not in code


def test_the_runner_answers_nothing_with_no_endpoint(monkeypatch, capsys) -> None:
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    assert trades.main([]) == 0


@pytest.mark.parametrize("half", [1, 2])
def test_the_answer_carries_the_disclaimer_and_the_data_credit(half) -> None:
    """Launch review LEG-M2/LEG-3, reproduced: trade_email(TRADE_SAMPLE) printed
    this week's projections ("RB: Saquon Barkley (17.6) → Bijan Robinson
    (15.1)") and how each player has scored with neither principle 4's "not
    betting picks" line nor RULE N1's CC-BY-4.0 credit, a licence term."""
    from render.report import NFLVERSE_LINE, NO_BETTING_LINE
    words = html.unescape(trade_email(TRADE_SAMPLE, "", "https://x.test/u")[half])
    assert NO_BETTING_LINE in words and NFLVERSE_LINE in words


def test_made_the_deal_is_a_button_in_the_products_masthead() -> None:
    """Launch review EM-10: the Trade Check printed "Made the deal?" over a
    raw URL in the client's default blue, under a square header no other
    report-family email used."""
    page = trade_email(TRADE_SAMPLE, "", "https://x.test/u")[1]
    assert re.search(r'<a href="https://x\.test/u" style="[^"]*color:#101E33;[^"]*">'
                     r'Update my roster</a>', page)
    assert ">https://x.test/u<" not in page
    assert 'Beat Your <span style="color:#F0B62A;">League</span>' in page
    assert "border-left:4px" not in page
