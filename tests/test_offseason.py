"""The season review and the rookie report (owner decision, Nov 1 2026): facts
about what happened, sent only where they're owed or asked for."""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from engine import rookies
from engine.scoring import preset
from engine.season_review import review_team
from render.rookies import ROOKIE_SAMPLE, rookie_email, rookie_page
from render.season_review import REVIEW_SAMPLE, review_message
from run import plans, season_review
from run.season_review import HoldEntry, append_holds, hold_code, is_due, load_holds, new_holds
from run.updates import confirm_code, seat_code

ROOT = Path(__file__).resolve().parent.parent
SECRET = "s" * 40
RULE = preset("ppr")
NOW = datetime(2027, 1, 13, 22, tzinfo=timezone.utc)


def stat(rec: float = 0.0) -> dict:
    return {"receptions": "0", "receiving_yards": str(rec * 10), "receiving_tds": "0"}


def call(pick: str, over: str, confidence: float, slot: str = "WR") -> dict:
    return {"slot": slot, "pick": pick, "over": over, "pick_name": pick.title(),
            "over_name": over.title(), "confidence": confidence}


def plan(week: int, calls: list, starters=("a",)) -> dict:
    return {"week": week, "calls": calls, "team": "Lead's team",
            "slots": [{"slot": "WR", "player_id": p} for p in starters] + [
                {"slot": "DEF", "player_id": "DEN"}],
            "players": {"a": {"name": "A"}, "b": {"name": "B"}, "DEN": {"name": "Broncos"}}}


WEEKLY = {5: {"a": stat(20), "b": stat(5)}, 6: {"a": stat(3), "b": stat(19)},
          7: {"a": stat(10), "b": stat(1)}}


def test_a_season_counts_hits_beside_misses() -> None:
    team = review_team([plan(5, [call("a", "b", 0.72)]), plan(6, [call("a", "b", 0.61)]),
                        plan(7, [call("a", "b", 0.55)])], WEEKLY, RULE)
    assert (team["hits"], team["calls"], team["weeks"]) == (2, 3, 3)
    assert team["worst_miss"]["week"] == 6 and team["best_call"]["week"] == 5
    assert [b["label"] for b in team["bands"]] == ["70% or higher", "60–69%", "Under 60%"]


def test_a_week_with_no_box_scores_is_not_graded() -> None:
    assert review_team([plan(9, [call("a", "b", 0.7)])], WEEKLY, RULE) is None


def test_a_void_is_no_result_and_never_counted() -> None:
    weekly = {5: {"a": stat(0), "b": stat(0)}}
    team = review_team([plan(5, [call("a", "b", 0.7)])], weekly, RULE)
    assert (team["calls"], team["no_result"]) == (0, 1)


def test_a_defense_is_not_scored_as_a_player() -> None:
    team = review_team([plan(5, [])], {5: {"a": stat(20), "DEN": stat(99)}}, RULE)
    assert [r["name"] for r in team["top_scorers"]] == ["A"]


@pytest.mark.parametrize("today,due", [(date(2027, 1, 10), False), (date(2027, 1, 13), True),
                                       (date(2027, 1, 31), True), (date(2027, 2, 1), False)])
def test_the_review_goes_after_the_last_game_and_not_months_later(today, due) -> None:
    assert is_due("2027-01-10", today) is due


def test_the_review_shows_misses_and_predicts_nothing() -> None:
    message = review_message("a@b.co", "2026", [("Work", REVIEW_SAMPLE)], "k", "https://x.test/h")
    for words in (html.unescape(re.sub(r"<[^>]+>", " ", message.html)), message.text):
        assert "Biggest miss" in words and "20 of 31" in words and "reply with the word stop" in words.lower()
        for banned in ("next season you will", "calibrated", "accurate", "proven", "tested"):
            assert banned not in words.lower()
    assert message.unsubscribe and message.key == "k"


def test_no_button_without_a_link() -> None:
    assert "rookie report" not in review_message("a@b.co", "2026", [("W", REVIEW_SAMPLE)], "k").text.lower()


# --------------------------------------------------------------------- #
# consent
# --------------------------------------------------------------------- #

ROWS = [{"email": "a@example.com"}, {"email": "b@example.com"}]


def test_only_a_press_of_the_addresss_own_code_counts() -> None:
    press = [{"code": hold_code("a@example.com", "2026", SECRET)}]
    fresh = new_holds(ROWS, press, ["2026"], SECRET, [], NOW)
    assert [e.email for e in fresh] == ["a@example.com"]
    assert new_holds(ROWS, [{"code": "0" * 24}], ["2026"], SECRET, [], NOW) == []


def test_a_held_address_is_logged_once(tmp_path) -> None:
    path = tmp_path / "hold.jsonl"
    press = [{"code": hold_code("a@example.com", "2026", SECRET)}]
    append_holds(new_holds(ROWS, press, ["2026"], SECRET, [], NOW), path)
    assert new_holds(ROWS, press, ["2026"], SECRET, load_holds(path), NOW) == []


def test_a_hold_code_is_no_other_code() -> None:
    code = hold_code("a@example.com", "2026", SECRET)
    assert code not in (confirm_code("a@example.com", "2026", "", SECRET),
                        seat_code("a@example.com", "2026", "", "", SECRET))


def test_a_season_counts_its_own_consent() -> None:
    assert hold_code("a@b.co", "2026", SECRET) != hold_code("a@b.co", "2027", SECRET)


def test_privacy_tools_are_told_about_the_consent_log() -> None:
    source = (ROOT / "run" / "privacy.py").read_text(encoding="utf-8")
    assert "HOLD_LOG_NAME" in source


# --------------------------------------------------------------------- #
# the rookie report
# --------------------------------------------------------------------- #

def player(pid, name, position, year="2026", rnd="1", pick="5", team="NYJ", **over) -> dict:
    return {"gsis_id": pid, "display_name": name, "position": position, "draft_year": year,
            "draft_round": rnd, "draft_pick": pick, "draft_team": team, "latest_team": team,
            "college_name": "Oregon; Tulsa", "birth_date": "2004-06-01", "height": "73",
            "weight": "210", "status": "ACT", **over}


def test_the_class_is_in_draft_order_and_skill_positions_only() -> None:
    people = [player("1", "Late", "WR", pick="50"), player("2", "Early", "RB", pick="3"),
              player("3", "Lineman", "T", pick="1"), player("4", "Old", "WR", year="2025")]
    names = [r["name"] for r in rookies.draft_class(people, 2026)]
    assert names == ["Early", "Late"]


def test_a_rookie_is_described_as_the_file_has_him() -> None:
    rookie = rookies.draft_class([player("1", "A", "WR")], 2026)[0]
    assert (rookie["college"], rookie["age"], rookie["height"]) == ("Oregon", 21, "6'1\"")


def test_the_room_counts_who_left() -> None:
    people = [player("9", "Stayed", "WR"), player("8", "Gone", "WR", latest_team="BUF")]
    weekly = {1: {"9": {"position": "WR", "team": "NYJ", "targets": "6", "carries": "0"},
                  "8": {"position": "WR", "team": "NYJ", "targets": "4", "carries": "0"}}}
    assert rookies.team_rooms(people, weekly)[("NYJ", "WR")] == {"left_share": 40, "lead": "Stayed"}


def test_a_recent_class_cannot_drag_the_three_season_figure() -> None:
    people = [player("1", "Then", "RB", year="2020"), player("2", "Now", "RB", year="2025")]
    row = {"rushing_yards": "150", "rushing_tds": "0"}
    seasons = {2020: {w: {"1": row} for w in range(1, 8)}}
    out = rookies.history(people, seasons, RULE, 2026)[0]
    assert (out["drafted"], out["mature"], out["rookie_hits"], out["within_three"]) == (2, 1, 1, 1)


def test_short_seasons_do_not_count() -> None:
    assert rookies._per_game("1", {w: {"1": {"rushing_yards": "150"}} for w in range(1, 6)}, RULE) is None


def test_it_finds_rookies_beside_a_subscribers_players() -> None:
    near = rookies.near_your_players(
        rookies.draft_class([player("1", "New", "RB")], 2026),
        [{"name": "Vet", "position": "RB", "team": "NYJ"},
         {"name": "Other", "position": "WR", "team": "NYJ"}])
    assert near[0]["yours"] == ["Vet"]


def test_the_email_puts_their_players_first_and_says_it_is_not_a_ranking() -> None:
    message = rookie_email(ROOKIE_SAMPLE, ROOKIE_SAMPLE["near"], "a@b.co", "k", "https://x.test/r")
    assert message.text.index("LANDED BESIDE YOUR PLAYERS") < message.text.index("QUARTERBACKS")
    assert "not a ranking of ours" in message.text and "nflverse" in message.text
    assert message.unsubscribe


def test_the_runner_sends_nothing_outside_its_window(capsys, monkeypatch) -> None:
    from run import rookies as runner
    assert runner.is_due(date(2027, 5, 1)) and not runner.is_due(date(2027, 4, 30))
    assert not runner.is_due(date(2027, 9, 1))


def test_no_pfr_derived_release_is_read() -> None:
    """RULE N2: nflverse's draft_picks is Pro-Football-Reference data."""
    for name in ("engine/rookies.py", "render/rookies.py", "run/rookies.py"):
        code = (ROOT / name).read_text(encoding="utf-8").split('"""', 2)[2]
        assert "draft_picks" not in code, name


def test_the_published_page_is_facts_and_names_its_source() -> None:
    page = (ROOT / "site" / "rookie-report.html").read_text(encoding="utf-8")
    words = html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", page, flags=re.S))
    assert "not a ranking of ours" in words and "nflverse" in words
    assert "not a forecast" in words
    for banned in ("sleeper pick", "must draft", "will be", "guaranteed"):
        assert banned not in words.lower(), banned


def test_the_page_builds_from_a_report() -> None:
    assert "Fernando Mendoza" in rookie_page({**ROOKIE_SAMPLE, "history": []})


def test_the_workflows_carry_both() -> None:
    flows = ROOT / ".github" / "workflows"
    assert "run: .venv/bin/python -m run.season_review" in (flows / "weekly.yml").read_text(encoding="utf-8")
    assert "run: .venv/bin/python -m run.rookies" in (flows / "daily.yml").read_text(encoding="utf-8")


def test_the_calendar_knows_about_the_rookie_report() -> None:
    assert 5 in plans.months_covered() and not plans.bills_all_year()
