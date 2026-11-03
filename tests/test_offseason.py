"""The season review and the rookie report (owner decision, Nov 1 2026): facts
about what happened, sent only where they're owed or asked for."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from engine import rookies
from engine.scoring import preset
from engine.season_review import review_team, rookies_on_team
from render import rookies as render_rookies
from render.rookies import (ROOKIE_SAMPLE, _base_rate, _beside, _bio, _season, _where, class_year,
                            rookie_email, rookie_page)
from render.season_review import REVIEW_SAMPLE, review_message
from run import plans, season_review
from run import rookies as rookie_runner
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


def _people() -> dict:
    return {"r": {"display_name": "Rook", "position": "WR", "rookie_season": "2026"},
            "u": {"display_name": "Undrafted", "position": "RB", "rookie_season": "2026"},
            "v": {"display_name": "Veteran", "position": "WR", "rookie_season": "2019"},
            "n": {"display_name": "Benched", "position": "TE", "rookie_season": "2026"}}


def test_a_team_lists_its_rookies_best_first_and_undrafted_too() -> None:
    weekly = {1: {"r": stat(5), "u": stat(20), "v": stat(30)}, 2: {"r": stat(5)}}
    rows = rookies_on_team(["r", "u", "v", "n", "gone"], _people(), weekly, RULE, "2026")
    assert [r["name"] for r in rows] == ["Undrafted", "Rook", "Benched"]
    assert rows[1]["season"]["games"] == 2 and rows[2]["season"] is None


def test_the_rookies_are_scored_under_the_teams_rule() -> None:
    weekly = {1: {"r": {"receptions": "10"}}}
    ppr = rookies_on_team(["r"], _people(), weekly, RULE, "2026")[0]["season"]["per_game"]
    standard = rookies_on_team(["r"], _people(), weekly, preset("standard"), "2026")[0]["season"]["per_game"]
    assert (ppr, standard) == (10.0, 0.0)


def test_the_review_prints_a_teams_rookies_and_none_when_it_has_none() -> None:
    message = review_message("a@b.co", "2026", [("Work", REVIEW_SAMPLE)], "k")
    assert "Your rookies:" in message.text and "Jeremiyah Love, RB: 14 games, 12.3 a game." in message.text
    assert "Jordyn Tyson, WR: no games." in message.text
    plain = {k: v for k, v in REVIEW_SAMPLE.items() if k != "rookies"}
    assert "Your rookies" not in review_message("a@b.co", "2026", [("Work", plain)], "k").text


def test_only_leagues_that_carry_a_roster_over_get_them() -> None:
    assert season_review.ROOKIE_LEAGUES == ("keeper", "dynasty")


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
    assert rookies.team_rooms(people, weekly)[("NYJ", "WR")] == {
        "left_share": 40, "lead": "Stayed", "arrived": [], "shares": {"9": 60, "8": 40}}


def _rows(*rows: tuple) -> dict:
    return {1: {pid: {"position": pos, "team": team, "targets": str(n), "carries": "0",
                      "attempts": str(n)} for pid, pos, team, n in rows}}


def test_the_room_names_a_veteran_who_arrived() -> None:
    """Review: Mendoza's line read 96% gone, O'Connell still there, with Kirk
    Cousins on the roster. A vacancy with no arrivals in it overstated it."""
    people = [player("9", "Stayed", "QB", team="LV"), player("8", "Gone", "QB", latest_team="NYJ"),
              player("7", "Cousins", "QB", team="LV")]
    weekly = _rows(("9", "QB", "LV", 40), ("8", "QB", "LV", 500), ("7", "QB", "ATL", 300))
    room = rookies.team_rooms(people, weekly)[("LV", "QB")]
    assert room["arrived"] == ["Cousins"] and room["lead"] == "Stayed"


def test_a_player_who_was_already_there_did_not_arrive() -> None:
    people = [player("9", "Same", "WR", team="NYJ")]
    weekly = _rows(("9", "WR", "NYJ", 90))
    assert rookies.team_rooms(people, weekly)[("NYJ", "WR")]["arrived"] == []


def test_depth_and_players_who_are_gone_do_not_arrive() -> None:
    people = [player("1", "Base", "WR", team="NYJ"), player("2", "Depth", "WR", team="NYJ"),
              player("3", "Cut", "WR", team="NYJ", status="CUT")]
    weekly = _rows(("1", "WR", "NYJ", 90), ("2", "WR", "BUF", 5), ("3", "WR", "BUF", 90))
    assert rookies.team_rooms(people, weekly)[("NYJ", "WR")]["arrived"] == []


def test_a_rookie_is_placed_on_his_team_today() -> None:
    """Review: three 2026 rookies had moved, while the page said its teams were
    current and showed the team that drafted them."""
    moved = rookies.draft_class([player("1", "Moved", "TE", latest_team="MIA", team="DEN")], 2026)[0]
    assert (moved["team"], moved["drafted_by"]) == ("MIA", "DEN")
    near = rookies.near_your_players(
        [moved], [{"player_id": "5", "name": "Vet", "position": "TE", "team": "MIA"}])
    assert near[0]["yours"] == ["Vet"]
    assert rookies.near_your_players(
        [moved], [{"player_id": "6", "name": "V", "position": "TE", "team": "DEN"}]) == []
    assert "MIA, drafted by DEN, round 1" in _where(moved)


def test_a_rookie_still_on_his_drafting_team_reads_plainly() -> None:
    rookie = rookies.draft_class([player("1", "A", "WR")], 2026)[0]
    assert _where(rookie) == "NYJ, round 1"


def test_a_rookie_off_the_active_roster_says_so() -> None:
    rookie = rookies.draft_class([player("1", "A", "WR", status="RSR")], 2026)[0]
    assert "On the reserve list" in _bio(rookie)


def test_a_season_so_far_counts_games_played_only() -> None:
    weekly = {1: {"1": {"receiving_yards": "100"}}, 2: {}, 3: {"1": {"receiving_yards": "50"}}}
    assert rookies.this_season("1", weekly, RULE) == {"games": 2, "per_game": 7.5, "recent": [10.0, 5.0]}
    assert rookies.this_season("9", weekly, RULE) is None


def test_the_season_line_reads_plainly() -> None:
    assert _season({"season": None}, 2026) == "2026: no games yet."
    assert _season({"season": {"games": 1, "per_game": 2.2, "recent": [2.2]}}, 2026) == "2026: 1 game, 2.2 points."
    assert "7 games, 11.0 a game. Last 3: 1.0, 2.0, 3.0." in _season(
        {"season": {"games": 7, "per_game": 11.0, "recent": [1, 2, 3]}}, 2026)


def test_no_season_line_before_a_class_has_played() -> None:
    """In May the class has no games: "no games yet" on 80 rows is noise."""
    report = {**ROOKIE_SAMPLE, "through_week": None}
    assert "no games yet" not in rookie_page(report)
    assert "2026: 7 games" not in rookie_email(report, [], "a@b.co", "k").text
    assert "2026: 7 games" in rookie_email(ROOKIE_SAMPLE, [], "a@b.co", "k").text


def test_the_page_says_when_its_data_is_from() -> None:
    page = rookie_page({**ROOKIE_SAMPLE, "history": []})
    assert "Data as of Nov 1, 2026." in page and "as the data stands now" not in page
    assert "Data as of Nov 1, 2026." in rookie_email(ROOKIE_SAMPLE, [], "a@b.co", "k").text


def test_the_newest_class_turns_over_in_may() -> None:
    assert class_year(date(2026, 11, 4)) == 2026
    assert class_year(date(2027, 4, 30)) == 2026
    assert class_year(date(2027, 5, 1)) == 2027


def test_a_failed_read_keeps_the_last_page(monkeypatch, tmp_path) -> None:
    page = tmp_path / "rookie-report.html"
    page.write_text("last week's page", encoding="utf-8")
    monkeypatch.setattr(render_rookies, "SITE", tmp_path)
    monkeypatch.setattr(render_rookies, "load_report", lambda *a, **k: 1 / 0)
    assert render_rookies.main(["--live"]) == 0
    assert page.read_text(encoding="utf-8") == "last week's page"


def test_a_class_not_in_the_data_keeps_the_last_page(monkeypatch, tmp_path) -> None:
    page = tmp_path / "rookie-report.html"
    page.write_text("last year's page", encoding="utf-8")
    monkeypatch.setattr(render_rookies, "SITE", tmp_path)
    monkeypatch.setattr(render_rookies, "load_report", lambda *a, **k: {"rookies": []})
    assert render_rookies.main(["--live"]) == 0
    assert page.read_text(encoding="utf-8") == "last year's page"


def test_the_weekly_run_rebuilds_and_may_commit_the_page() -> None:
    flow = (ROOT / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
    assert "run: .venv/bin/python -m render.rookies --live" in flow
    assert "site/join/byes.json site/byes/index.html site/rookie-report.html" in flow
    assert "/site/join/byes.json /site/byes/index.html /site/rookie-report.html" in flow


def test_a_recent_class_cannot_drag_the_three_season_figure() -> None:
    people = [player("1", "Then", "RB", year="2020"), player("2", "Now", "RB", year="2025")]
    row = {"rushing_yards": "150", "rushing_tds": "0"}
    seasons = {2020: {w: {"1": row} for w in range(1, 8)}}
    out = rookies.history(people, seasons, RULE, 2026)[0]
    assert (out["drafted"], out["mature"], out["rookie_hits"], out["within_three"]) == (2, 1, 1, 1)


def test_short_seasons_do_not_count() -> None:
    assert rookies._per_game("1", {w: {"1": {"rushing_yards": "150"}} for w in range(1, 6)}, RULE) is None


def _rookie_with_room(**room) -> dict:
    rookie = rookies.draft_class([player("1", "New", "RB")], 2026)[0]
    return {**rookie, "room": {"left_share": 30, "shares": {"5": 55}, **room}}


def test_it_finds_rookies_beside_a_subscribers_players() -> None:
    near = rookies.near_your_players(
        [_rookie_with_room()],
        [{"player_id": "5", "name": "Vet", "position": "RB", "team": "NYJ"},
         {"player_id": "6", "name": "Other", "position": "WR", "team": "NYJ"}])
    assert near[0]["yours"] == ["Vet"]
    assert near[0]["usage"] == [{"name": "Vet", "share": 55}] and near[0]["left_share"] == 30


def test_one_player_on_two_teams_is_one_line() -> None:
    row = {"player_id": "5", "name": "Vet", "position": "RB", "team": "NYJ"}
    assert rookies.near_your_players([_rookie_with_room()], [row, row])[0]["yours"] == ["Vet"]


def test_a_rookie_is_not_beside_himself() -> None:
    row = {"player_id": "1", "name": "New", "position": "RB", "team": "NYJ"}
    assert rookies.near_your_players([_rookie_with_room()], [row]) == []


def test_the_biggest_share_comes_first() -> None:
    roster = [{"player_id": "5", "name": "Big", "position": "RB", "team": "NYJ"},
              {"player_id": "6", "name": "Small", "position": "RB", "team": "NYJ"}]
    near = rookies.near_your_players([_rookie_with_room(shares={"5": 55, "6": 10})], roster)
    assert near[0]["yours"] == ["Big", "Small"]


def test_the_email_says_where_a_rookie_leaves_your_player() -> None:
    near = {"rookie": "New", "position": "RB", "team": "NYJ", "round": 2, "pick": 40,
            "left_share": 30, "yours": ["Vet", "Late"],
            "usage": [{"name": "Vet", "share": 55}, {"name": "Late", "share": None}]}
    line = _beside(near, 2026)
    assert "joins your Vet, Late." in line and "Vet had 55% of the team's 2025 RB targets and carries." in line
    assert "Late had none of that usage here in 2025." in line
    assert line.endswith("30% of that room has left.")


def test_a_second_rookie_in_one_room_does_not_repeat_it() -> None:
    near = [{"rookie": name, "position": "WR", "team": "NO", "round": 4, "pick": 100,
             "left_share": 31, "yours": ["Vet"], "usage": [{"name": "Vet", "share": 45}]}
            for name in ("One", "Two")]
    text = rookie_email(ROOKIE_SAMPLE, near, "a@b.co", "k").text
    assert text.count("Vet had 45%") == 1 and "Two (WR, NO, round 4, pick 100) joins the same room." in text


def test_a_quarterback_is_counted_in_passes() -> None:
    near = {"rookie": "New", "position": "QB", "team": "NYJ", "round": 2, "pick": 40,
            "left_share": None, "yours": ["Vet"], "usage": [{"name": "Vet", "share": 90}]}
    assert "2025 QB pass attempts." in _beside(near, 2026) and "room has left" not in _beside(near, 2026)


# --------------------------------------------------------------------- #
# the base rate on each row
# --------------------------------------------------------------------- #

HISTORY = [{"position": "RB", "round": "Round 1", "drafted": 16, "rookie_hits": 13},
           {"position": "RB", "round": "Rounds 4–7", "drafted": 179, "rookie_hits": 9}]


@pytest.mark.parametrize("round_,hits", [(1, 13), (5, 9), (7, 9)])
def test_a_rookie_reads_his_own_row(round_, hits) -> None:
    assert rookies.base_rate(HISTORY, "RB", round_)["rookie_hits"] == hits


def test_no_row_is_no_line() -> None:
    assert rookies.base_rate(HISTORY, "TE", 1) is None
    assert rookies.base_rate(HISTORY, "RB", None) is None
    assert _base_rate({"position": "RB", "base_rate": None}) == ""


def test_the_base_rate_is_worded_as_the_past() -> None:
    rate = rookies.base_rate(HISTORY, "RB", 1)
    assert _base_rate({"position": "RB", "base_rate": rate}) == (
        "Past RBs taken in Round 1: 13 of 16 reached a good pace as rookies.")


def test_every_surface_defines_a_good_pace() -> None:
    page = html.unescape(rookie_page({**ROOKIE_SAMPLE, "history": []}))
    text = rookie_email(ROOKIE_SAMPLE, [], "a@b.co", "k").text
    for words in (page, text):
        assert "reached a good pace" in words and "15+ points a game for a QB" in words
        assert "not a forecast" in words


def test_the_published_page_agrees_with_its_own_table() -> None:
    page = html.unescape((ROOT / "site" / "rookie-report.html").read_text(encoding="utf-8"))
    assert "Past RBs taken in Round 1: 13 of 16 reached a good pace as rookies." in page
    assert re.search(r"RB, Round 1</td><td class=\"n\">16</td><td class=\"n\">13<", page)


def test_the_email_puts_their_players_first_and_says_it_is_not_a_ranking() -> None:
    message = rookie_email(ROOKIE_SAMPLE, ROOKIE_SAMPLE["near"], "a@b.co", "k", "https://x.test/r")
    assert message.text.index("LANDED BESIDE YOUR PLAYERS") < message.text.index("QUARTERBACKS")
    assert "not a ranking of ours" in message.text and "nflverse" in message.text
    assert message.unsubscribe


def test_the_runner_sends_nothing_outside_its_window(capsys, monkeypatch) -> None:
    runner = rookie_runner
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


# --------------------------------------------------------------------- #
# the box on the page
# --------------------------------------------------------------------- #

FORM = "https://forms.example/rows"


def test_no_box_until_the_form_worker_exists() -> None:
    """A box that saves nothing is worse than no box."""
    page = rookie_page({**ROOKIE_SAMPLE, "history": []}, endpoint="")
    assert "rookie-ask" not in page and "rookie-form.js" not in page


def test_the_box_says_exactly_what_it_will_do() -> None:
    page = html.unescape(rookie_page({**ROOKIE_SAMPLE, "history": []}, endpoint=FORM))
    assert f'data-endpoint="{FORM}"' in page and 'src="/rookie-form.js"' in page
    assert "One email after the NFL Draft, and nothing else unless you ask." in page


def test_the_page_reads_the_join_pages_address(tmp_path) -> None:
    join = tmp_path / "index.html"
    join.write_text(f'x\nconst FORM_ENDPOINT = "{FORM}";\ny', encoding="utf-8")
    assert render_rookies.join_endpoint(join) == FORM


def test_the_published_page_matches_the_join_page() -> None:
    page = (ROOT / "site" / "rookie-report.html").read_text(encoding="utf-8")
    assert ("rookie-ask" in page) is bool(render_rookies.join_endpoint())


def _ask(email: str, at: str) -> dict:
    return {"kind": "rookie_ask", "email": email, "received_at": at}


def test_a_request_counts_for_one_class_only() -> None:
    """The page promises one email. A row lives about 13 months, so one from
    April 2027 would otherwise still be there for the 2028 report."""
    rows = [_ask("old@b.co", "2026-08-30T00:00:00Z"), _ask("now@b.co", "2026-11-02T00:00:00Z"),
            _ask("late@b.co", "2027-06-02T00:00:00Z")]
    assert rookie_runner.asked_for(rows, 2027) == ["now@b.co", "late@b.co"]
    assert rookie_runner.asked_for(rows, 2028) == []


def test_a_junk_address_is_not_an_address() -> None:
    assert rookie_runner.asked_for([_ask("nope", "2026-11-02T00:00:00Z")], 2027) == []


def test_members_come_first_and_one_mailbox_gets_one() -> None:
    out = rookie_runner.merged(["m@gmail.com"], ["a@b.co", "m+tag@gmail.com", "m.@gmail.com"])
    assert out[:2] == ["m@gmail.com", "a@b.co"] and len(out) <= 3
    assert "m+tag@gmail.com" not in out


def test_an_alias_cannot_collect_a_second_copy(monkeypatch) -> None:
    monkeypatch.setenv("LOG_SECRET", "x" * 32)
    assert rookie_runner.rookie_key(2027, "m+tag@gmail.com") == rookie_runner.rookie_key(2027, "m@gmail.com")


def test_the_email_points_a_stranger_at_the_product_once() -> None:
    message = rookie_email(ROOKIE_SAMPLE, [], "a@b.co", "k", join_url="https://x.test/join/")
    assert "https://x.test/join/" in message.text and message.text.count("https://x.test/join/") == 1
    assert "https://x.test/join/" not in rookie_email(ROOKIE_SAMPLE, [], "a@b.co", "k").text


def test_the_box_writes_text_never_markup() -> None:
    script = (ROOT / "site" / "rookie-form.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script and "textContent" in script and "response.ok" in script


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_worker_takes_a_request_and_keeps_it_for_months() -> None:
    from test_teams import _worker
    row = _worker('{kind:"rookie_ask",email:"a@b.co",ref:"x",extra:"y",via:"reddit"}')
    assert row == {"kind": "rookie_ask", "email": "a@b.co", "via": "reddit"}
    source = (ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
    assert 'const LONG_ROWS = ["waitlist", "rookie_ask"];' in source
    assert 'const ONE_A_DAY = ["trial", "waitlist", "rookie_ask"];' in source


def test_the_daily_step_can_read_the_requests() -> None:
    flow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    step = flow[flow.index("name: Send the rookie report"):flow.index("run: .venv/bin/python -m run.rookies")]
    assert "FORM_ENDPOINT:" in step and "FORM_API_KEY:" in step and "EMAIL_DAILY_HEADROOM:" in step


def test_the_workflows_carry_both() -> None:
    flows = ROOT / ".github" / "workflows"
    assert "run: .venv/bin/python -m run.season_review" in (flows / "weekly.yml").read_text(encoding="utf-8")
    assert "run: .venv/bin/python -m run.rookies" in (flows / "daily.yml").read_text(encoding="utf-8")


def test_the_calendar_knows_about_the_rookie_report() -> None:
    assert 5 in plans.months_covered() and not plans.bills_all_year()


# --------------------------------------------------------------------- #
# launch review OPS-3: no sender address is red once, never every run
# --------------------------------------------------------------------- #

class _Provider:
    name = "fake"


def _held_env(tmp_path, monkeypatch) -> tuple[Path, list]:
    """A send log in tmp_path, LOG_SECRET set, SENDER_POSTAL_ADDRESS unset, and
    a send_all that records what it was handed."""
    import run.delivery as delivery
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    monkeypatch.setenv("LOG_SECRET", SECRET)
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS", raising=False)
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.setattr(delivery, "build_provider", lambda *a: _Provider())
    handed: list = []

    def send_all(messages, provider=None):
        handed.extend(messages)
        return [delivery.SendResult(m, True, "id") for m in messages]
    monkeypatch.setattr(delivery, "send_all", send_all)
    return log, handed


def test_a_season_review_held_for_its_sender_address_is_red_once(tmp_path, monkeypatch,
                                                                   capsys) -> None:
    """Reproduction (launch review OPS-3): the owner launched without
    SENDER_POSTAL_ADDRESS, and the season review refused with exit 1 on every
    Wednesday of its window, failing the weekly job and commenting on its issue
    each time. Without the address it still sends nothing, but only the first
    run that holds it goes red; the later ones say so with a warning and exit
    0. Once the address is set, the next run sends."""
    import ingest.nflverse as nflverse
    import engine.season_review as engine_review
    import render.season_review as render_review
    import run.delivery as delivery
    import run.rosters as rosters
    import run.saturday as saturday
    import run.solo as solo
    import run.tuesday as tuesday
    from types import SimpleNamespace
    from run.watchdog import held_key
    log, handed = _held_env(tmp_path, monkeypatch)
    registry = tmp_path / "rosters.json"
    registry.write_text("{}", encoding="utf-8")
    team = SimpleNamespace(email="fan@example.com", slug="abcdef0123", label="Work league",
                           league_type="redraft", player_ids=(),
                           spec=lambda: SimpleNamespace(rule=RULE))
    monkeypatch.setattr(nflverse, "season_rows", lambda *a, **k: {})
    monkeypatch.setattr(nflverse, "fetch", lambda *a, **k: (_ for _ in ()).throw(
        nflverse.NflverseError("offline")))
    monkeypatch.setattr(solo, "assert_week_is_complete", lambda *a, **k: None)
    monkeypatch.setattr(solo, "last_week", lambda *a, **k: 18)
    monkeypatch.setattr(solo, "season_ends", lambda *a, **k: {"2026": "2027-01-10"})
    monkeypatch.setattr(rosters, "load_rosters", lambda *a, **k: [team])
    monkeypatch.setattr(tuesday, "paid_subscribers", lambda subscribers, *a, **k: subscribers)
    monkeypatch.setattr(saturday, "load_plans", lambda *a, **k: [plan(5, [])])
    monkeypatch.setattr(engine_review, "review_team", lambda *a, **k: {"calls": []})
    monkeypatch.setattr(render_review, "review_message",
                        lambda email, season, teams, key, url: delivery.Message(
                            key=key, to=email, subject="s", text="t", html="h"))
    args = ["--season", "2026", "--registry", str(registry),
            "--plans-dir", str(tmp_path / "plans")]

    assert season_review.main(args) == 1
    err = capsys.readouterr().err
    assert "SEASON REVIEW NOT SENT" in err and "1 waiting" in err and "until Jan 31" in err
    assert held_key("review", "2026") in delivery.load_sent(log)

    assert season_review.main(args) == 0, "red every Wednesday about the same secret"
    out = capsys.readouterr()
    assert "SEASON REVIEW NOT SENT" in out.err and "::warning::" in out.out
    assert not handed, "a commercial email went out with no postal address"

    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 9, Toronto ON")
    assert season_review.main(args) == 0
    assert [m.to for m in handed] == ["fan@example.com"]


def test_a_rookie_report_held_for_its_sender_address_is_red_once_a_year(
        tmp_path, monkeypatch, capsys) -> None:
    """Reproduction (launch review OPS-3): from May, with anyone having asked,
    the rookie report refused with exit 1 on every hourly run, so the daily
    intake job went red every hour and its issue gathered a comment an hour,
    burying a real blocked signup in the same job. Held for want of the
    address, it is red on the first run of the year and green with a warning
    after; a failed read of the requests still fails."""
    import engine.rookies as engine_rookies
    import ingest.nflverse as nflverse
    import render.rookies as rookies_page
    import run.delivery as delivery
    import run.rosters as rosters
    from run.watchdog import held_key
    log, handed = _held_env(tmp_path, monkeypatch)
    registry = tmp_path / "rosters.json"
    append_holds([HoldEntry("fan@example.com", "2026", "2027-01-14")],
                 tmp_path / season_review.HOLD_LOG_NAME)

    class May(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2027, 5, 3, 14, tzinfo=timezone.utc)
    monkeypatch.setattr(rookie_runner, "datetime", May)
    monkeypatch.setattr(nflverse, "fetch", lambda *a, **k: tmp_path / "players.csv")
    monkeypatch.setattr(engine_rookies, "load_players", lambda *a, **k: [])
    monkeypatch.setattr(engine_rookies, "picks_in", lambda *a, **k: 300)
    monkeypatch.setattr(engine_rookies, "near_your_players", lambda *a, **k: [])
    monkeypatch.setattr(rosters, "load_rosters", lambda *a, **k: [])
    monkeypatch.setattr(rookies_page, "load_report", lambda *a, **k: {"rookies": []})
    monkeypatch.setattr(rookies_page, "rookie_email",
                        lambda report, near, email, key, *a: delivery.Message(
                            key=key, to=email, subject="s", text="t", html="h"))
    args = ["--registry", str(registry)]

    assert rookie_runner.main(args) == 1
    assert "ROOKIE REPORT NOT SENT" in capsys.readouterr().err
    assert held_key("rookies", "2027") in delivery.load_sent(log)
    assert rookie_runner.main(args) == 0, "red every hour about the same secret"
    assert "::warning::" in capsys.readouterr().out
    assert not handed, "a commercial email went out with no postal address"

    import run.intake as intake

    def unreadable(*a, **k):
        raise intake.IntakeError("the form backend is down")
    monkeypatch.setenv("FORM_ENDPOINT", "https://forms.example.com/rows")
    monkeypatch.setattr(intake, "fetch_seats", unreadable)
    assert rookie_runner.main(args) == 1, "a failed read hid behind the held send"
    monkeypatch.delenv("FORM_ENDPOINT")
    capsys.readouterr()

    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 9, Toronto ON")
    assert rookie_runner.main(args) == 0
    assert [m.to for m in handed] == ["fan@example.com"]
