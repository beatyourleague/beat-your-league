"""Tuesday's public posts (run/drops.py): drafts that say what they are."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from run import drops

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://beatyourleague.com"
URL = "https://beatyourleague.com/this-week.html"


def _report(**over) -> dict:
    report = {
        "meta": {"week": 5, "season": "2026", "league_id": "typed-ppr-12-2026",
                 "my_roster_id": 1},
        "regret": {"slot": "FLEX", "start_id": "00-0038542", "start_name": "Sam LaPorta",
                   "over_id": "00-0039919", "over_name": "Rome Odunze",
                   "confidence": 0.554,
                   "drivers": [{"label": "proj", "value": "10.6 vs 9.7"},
                               {"label": "games this season", "value": "4 vs 4"}]},
        "lineup": [{"slot": "FLEX", "player_id": "00-0038542",
                    "player_name": "Sam LaPorta", "confidence": 0.554,
                    "alternative_id": "00-0039919", "alternative_name": "Rome Odunze",
                    "usage": "last 4 games: 26 targets (6.5 a game)"},
                   {"slot": "RB", "player_id": "00-0040784",
                    "player_name": "Quinshon Judkins", "confidence": None,
                    "usage": "last 4 games: 18 targets (4.5 a game), 61 carries"}],
        "bench": [{"player_id": "00-0039919", "name": "Rome Odunze",
                   "games": [6.1, 7.4, 15.4, 5.0]}],
        "pivots": [{"condition": "Tony Pollard (FLEX) is ruled out",
                    "action": "Move Chase Brown into FLEX (projects 10.3)"}],
        "rising": [{"name": "Emanuel Wilson", "team": "SEA", "position": "RB",
                    "recent": 15.5, "earlier": 2.0},
                   {"name": "Aaron Jones", "team": "MIN", "position": "RB",
                    "recent": 23.0, "earlier": 13.0},
                   {"name": "Kaleb Johnson", "team": "GB", "position": "RB",
                    "recent": 7.5, "earlier": 0.0}],
    }
    report.update(over)
    return report


@pytest.fixture(autouse=True)
def _no_schedule(monkeypatch):
    """No test reads, or downloads, the real schedule through main(): its
    kickoffs are none, so no draft here goes stale against today's date."""
    monkeypatch.setattr(drops, "_week_kickoffs", lambda season, week: {})


def _named(posts: list[dict], name: str) -> str:
    [text] = [p["text"] for p in posts if p["name"] == name]
    return text


def test_every_post_fits_says_sample_and_links_the_live_report() -> None:
    """In a week the site links this week's page (``live_page``), every first
    reply links it; the post itself never carries a link. Told nothing, the
    replies link the home page, which every week can show (site review, Nov
    2026: the drafts linked a page the site itself was hiding)."""
    posts = drops.drafts(_report(), live_page=True)
    assert [p["name"] for p in posts] == ["The closest call", "The if/then", "Rising roles"]
    for post in posts:
        assert len(post["text"]) <= drops.LIMIT, post["name"]
        # The link rides the first reply, never the post (launch review M8).
        assert URL not in post["text"] and URL in post["reply"]
        assert "http" not in post["text"]
    assert "sample roster" in posts[0]["text"] and "sample roster" in posts[1]["text"]
    assert "55%" in posts[0]["text"]
    for post in drops.drafts(_report()):
        assert URL not in post["reply"] and f"{SITE}/?via=" in post["reply"], post


def test_the_call_leads_with_the_question_then_a_fact_then_the_number() -> None:
    """Launch audit: the closest call is by construction near a coin flip, and
    the post opened with the % and a link — nothing a reader could weigh. It
    now asks what a manager asks (both names and the slot), gives one line of
    the report's own facts for the pair, and only then the number."""
    text = _named(drops.drafts(_report()), "The closest call")
    assert text.startswith("Start LaPorta or Odunze at FLEX this week? ")
    fact = "LaPorta projects 10.6 points this week, Odunze 9.7."
    assert fact in text and text.index(fact) < text.index("55%")
    assert "starts LaPorta: 55% to outscore Odunze" in text


def test_the_fact_line_compares_like_with_like() -> None:
    """Reproduction (G23, Oct 2026): the live draft read "Odunze, last 4 games:
    26 targets (6.5 a game). Shaheed's last three games: 3.4, 12.3 and 4.3
    points." — one player's targets beside the other's points, which compares
    nothing. Both sides now get the same measure, or that measure is not used:
    points for both when the report prints games for both, usage for both
    when both lines count the same thing, else the projection on both rows."""
    text = _named(drops.drafts(_report()), "The closest call")
    assert "26 targets" not in text and "7.4, 15.4 and 5.0" not in text, \
        "a measure only one of the two players has"
    # Games for both: points beside points.
    lineup = [{**_report()["lineup"][0], "games": [12.0, 8.5, 9.1]}] + _report()["lineup"][1:]
    text = _named(drops.drafts(_report(lineup=lineup)), "The closest call")
    assert "Last games, in points: LaPorta 12.0, 8.5 and 9.1; Odunze 15.4, 5.0" not in text
    assert "Last games, in points: LaPorta 12.0, 8.5 and 9.1; Odunze 7.4, 15.4 and 5.0." in text
    # Usage for both, only when both lines count the same thing.
    bench = [{"player_id": "00-0039919", "name": "Rome Odunze", "games": [],
              "usage": "last 4 games: 31 targets (7.8 a game)"}]
    text = _named(drops.drafts(_report(bench=bench)), "The closest call")
    assert ("LaPorta, last 4 games: 26 targets (6.5 a game); Odunze, last 4 games: "
            "31 targets (7.8 a game).") in text
    carries = [{**bench[0], "usage": "last 4 games: 61 carries"}]
    text = _named(drops.drafts(_report(bench=carries)), "The closest call")
    assert "61 carries" not in text and "projects 10.6" in text


def test_a_call_with_no_like_for_like_fact_is_not_drafted() -> None:
    """A bare number is what the template exists to replace: with no measure
    both players share, there is no closest-call post at all."""
    regret = {**_report()["regret"], "drivers": []}
    names = [p["name"] for p in drops.drafts(_report(regret=regret, bench=[]))]
    assert "The closest call" not in names


def test_the_fact_line_gives_way_before_the_post_is_dropped() -> None:
    """Long names push the post past 280: a shorter like-for-like fact takes
    the place of a long one; the question and the number never go."""
    # Longer since the link left the post for its first reply (M8): the
    # same names now fit with the long line, so the case needs longer ones.
    long_a, long_b = "Christopher Longname-Hyphenationist", "Bartholomew Extralongsurnamesmiths"
    regret = {**_report()["regret"], "start_name": long_a, "over_name": long_b}
    lineup = [{**_report()["lineup"][0], "player_name": long_a,
               "games": [12.25, 18.5, 9.75]}]
    bench = [{"player_id": "00-0039919", "name": long_b,
              "games": [6.1, 7.4, 15.4, 5.0]}]
    text = _named(drops.drafts(_report(regret=regret, lineup=lineup, bench=bench)),
                  "The closest call")
    assert len(text) <= drops.LIMIT
    assert text.startswith("Start Longname-Hyphenationist or Extralongsurnamesmiths at FLEX this week? ")
    assert "55%" in text
    assert "Last games" not in text and "projects 10.6" in text, "the long line did not give way"


def test_surnames_say_which_player_they_mean() -> None:
    assert drops._short_names("Marvin Harrison Jr.", "Kenneth Walker III") == (
        "Harrison", "Walker")
    assert drops._short_names("Amon-Ra St. Brown", "Rome Odunze") == ("St. Brown", "Odunze")
    # Two St. Browns would read as one question about one player.
    assert drops._short_names("Amon-Ra St. Brown", "Equanimeous St. Brown") == (
        "Amon-Ra St. Brown", "Equanimeous St. Brown")


def test_a_seeded_call_keeps_its_disclosure_in_the_post() -> None:
    """A weeks 2-3 call counts last season in, and the preregistered method
    makes that disclosure travel with the call on every surface."""
    regret = {**_report()["regret"],
              "drivers": [{"label": "proj", "value": "10.6 vs 9.7"},
                          {"label": "seeded", "value": "last season counted in"}]}
    text = _named(drops.drafts(_report(regret=regret)), "The closest call")
    assert "55% to outscore Odunze (last season counted in)." in text


def test_no_post_carries_a_double_full_stop() -> None:
    """The engine's bench-cleared action is its own sentence ("… If he's out,
    nothing changes.") and the template added another full stop: "changes..
    That's". Every template is run against period-terminated input here."""
    pivots = [{"condition": "Tony Pollard (bench) is cleared to play",
               "action": "Start Tony Pollard at FLEX — he projects 11.2 to Chase "
                         "Brown's 10.3. If he's out, nothing changes."}]
    posts = drops.drafts(_report(pivots=pivots))
    assert posts
    for post in posts:
        assert ".." not in post["text"], post
    pivot = _named(posts, "The if/then")
    assert pivot.startswith("If Tony Pollard (bench) is cleared to play: start Tony "
                            "Pollard at FLEX")
    assert "nothing changes. That's the if/then" in pivot


def test_an_if_then_that_changes_no_seat_is_not_drafted() -> None:
    """"If Pollard (bench) is cleared: keep Brown" announces that nothing
    happens. The first plan that actually moves somebody is drafted instead,
    and with none there is no if/then post at all."""
    keep = {"condition": "Tony Pollard (bench) is cleared to play",
            "action": "Keep Chase Brown at FLEX — he projects 10.3 to Tony "
                      "Pollard's 9.1. If he's out, nothing changes."}
    even = {"condition": "Jaylen Warren (bench) is cleared to play",
            "action": "Keep Chase Brown at FLEX — they project dead even at "
                      "10.3, so it's not worth a swap. If he's out, nothing changes."}
    move = {"condition": "Zay Flowers (WR) is ruled out",
            "action": "Move Rashid Shaheed into WR (projects 7.6)"}
    pivot = _named(drops.drafts(_report(pivots=[keep, even, move])), "The if/then")
    assert pivot.startswith("If Zay Flowers (WR) is ruled out: move Rashid Shaheed")
    names = [p["name"] for p in drops.drafts(_report(pivots=[keep, even]))]
    assert "The if/then" not in names


def test_a_week_with_no_call_still_drafts_a_facts_only_post() -> None:
    """A bye-heavy week can leave the sample with no call. That is no number,
    never an empty page: the rising roles carry it, and failing those the
    workloads the lineup rows already print — counts, no %."""
    gated = {"gate": "no coin-flip call this week — nobody on your bench is eligible here"}
    names = [p["name"] for p in drops.drafts(_report(regret=gated, pivots=[]))]
    assert names == ["Rising roles"]
    posts = drops.drafts(_report(regret=gated, pivots=[], rising=[]))
    text = _named(posts, "Workloads")
    assert "sample roster" in text and URL not in text and len(text) <= drops.LIMIT
    assert "Judkins, last 4 games: 18 targets (4.5 a game), 61 carries" in text
    assert "%" not in text
    # A week WITH a call does not add it: one facts-only post is the floor.
    assert "Workloads" not in [p["name"] for p in drops.drafts(_report(rising=[]))]


def test_a_post_that_cannot_fit_drops_a_line_rather_than_truncating() -> None:
    long_name = "A Very Long Rising Player Name"
    report = _report(rising=[{"name": long_name, "team": "SEA", "position": "RB",
                              "recent": 15.5, "earlier": 2.0}] * 6)
    [post] = [p for p in drops.drafts(report) if p["name"] == "Rising roles"]
    assert len(post["text"]) <= drops.LIMIT
    assert post["text"].count(long_name) < 6 and post["text"].rstrip().endswith("your league.")


def test_no_post_promises_a_result_or_uses_a_banned_word() -> None:
    for post in drops.drafts(_report()):
        low = post["text"].lower()
        for word in drops.BANNED:
            assert word not in low, f"{post['name']} uses {word!r}"
        assert "%" not in post["text"] or post["name"] == "The closest call"
    # A draft that would use one is dropped, never posted.
    poisoned = _report(pivots=[{"condition": "X is out", "action": "Move the spread"}])
    assert "The if/then" not in [p["name"] for p in drops.drafts(poisoned)]


def test_nothing_to_say_means_no_posts_not_invented_ones() -> None:
    assert drops.drafts(_report(regret={}, pivots=[], rising=[], lineup=[])) == []
    text = drops.render(_report(regret={}, pivots=[], rising=[]), [])
    assert "Nothing to draft" in text


def test_the_tuesday_cron_drafts_them_and_commits_the_file() -> None:
    weekly = (ROOT / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
    assert "python -m run.drops" in weekly
    assert "content/this-week.md" in weekly.split("Persist the record")[1]


def test_the_drafter_reads_no_subscriber_data() -> None:
    src = (ROOT / "run" / "drops.py").read_text(encoding="utf-8")
    for private in ("run.rosters", "run.tuesday", "reports/subscribers", "registry"):
        assert private not in src.split('"""', 2)[2], private


def test_a_post_quotes_only_odds_on_the_record(tmp_path, monkeypatch) -> None:
    """Reproduction (G04, Oct 2026): `python -m run.drops` posted "Our sample
    roster's report starts Odunze: 63% to outscore Shaheed" while nothing was
    in the ledger, so a public probability went out that Monday's grading
    could never settle. The drafts are built from `recorded_only(build())`:
    with an empty ledger no draft carries a %; once that exact call is
    recorded at that value, it may be quoted."""
    import render.live_sample as live
    from engine.ledger import extract_published_calls, ledger_path, record_calls

    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: False)
    out = tmp_path / "this-week.md"
    empty = tmp_path / "empty"
    live.write_published_report(_report(), empty)
    assert drops.main(["--out", str(out), "--processed-dir", str(empty)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "%" not in text, "a draft quoted odds the ledger does not hold"
    assert "Rising roles" in text, "withholding the odds must not empty the page"

    ledger = tmp_path / "ledger-dir"
    record_calls(ledger_path(ledger, "typed-ppr-12-2026"), extract_published_calls(_report()))
    live.write_published_report(_report(), ledger)
    drops.main(["--out", str(out), "--processed-dir", str(ledger)])
    assert "55% to outscore Odunze" in out.read_text(encoding="utf-8")


def test_the_drafts_come_from_the_published_page_or_not_at_all(tmp_path, monkeypatch) -> None:
    """CRON-1, reproduced on Sun Oct 25 (Week 7 underway): `python -m
    run.drops` built the report a second time — the page kept its recorded
    first build, but the rebuild had moved (FLEX 0.608 against the ledger's
    0.61), so the flagship closest-call post was withheld, and it still
    drafted "Thursday night … Post it: Thursday" three days after that game.
    The drafts now read only the report this run's page was rendered from:
    none published in this run (a retry that kept the page) or a week that
    has kicked off leaves the previous file exactly as it was, and no second
    build is ever made."""
    import render.live_sample as live

    def no_second_build(*_a, **_k):
        raise AssertionError("run.drops built the report a second time")
    monkeypatch.setattr(live, "build", no_second_build)
    out = tmp_path / "this-week.md"
    out.write_text("last run's drafts\n", encoding="utf-8")
    processed = tmp_path / "processed"
    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: False)
    assert drops.main(["--out", str(out), "--processed-dir", str(processed)]) == 0
    assert out.read_text(encoding="utf-8") == "last run's drafts\n"
    (processed).mkdir()
    (processed / live.PUBLISHED_REPORT_NAME).write_text("{not json", encoding="utf-8")
    assert drops.main(["--out", str(out), "--processed-dir", str(processed)]) == 0
    assert out.read_text(encoding="utf-8") == "last run's drafts\n"
    live.write_published_report(_report(), processed)
    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: True)
    assert drops.main(["--out", str(out), "--processed-dir", str(processed)]) == 0
    assert out.read_text(encoding="utf-8") == "last run's drafts\n"
    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: False)
    assert drops.main(["--out", str(out), "--processed-dir", str(processed)]) == 0
    assert "Rising roles" in out.read_text(encoding="utf-8")


def test_the_drafter_withholds_before_it_drafts() -> None:
    """The order is the rule: recorded_only runs on the report BEFORE drafts()
    sees it, so no template can reach an unrecorded number — and that report
    is the published page's own (CRON-1), never a build of its own."""
    src = (ROOT / "run" / "drops.py").read_text(encoding="utf-8")
    body = src.split("def main", 1)[1]
    assert "report = recorded_only(published, processed)" in body
    assert "build(" not in body
    assert body.index("recorded_only(") < body.index("drafts(report")


def test_a_thursday_starter_gets_a_thursday_post_with_his_if_then() -> None:
    """Launch review M8 (the verifier's draft): posts were Tuesday-only, and
    the one game the Saturday check is too late for — a Thursday-night
    starter — had no post. The draft gives his kickoff as his row prints it
    and the if/then the report printed ABOUT him that moves somebody; with
    none, the report's own "check his status" line. Marked for Thursday, no
    number of any kind, the link in the first reply like every post."""
    lineup = [{"slot": "QB", "player_id": "00-1", "player_name": "Brock Purdy",
               "game": "@ ATL · Sun 1:00 PM ET"},
              {"slot": "FLEX", "player_id": "00-0039919", "player_name": "Rome Odunze",
               "game": "vs NE · Thu 8:15 PM ET"}]
    tuesday = {"condition": "Tony Pollard (RB) is ruled out",
               "action": "Move Chase Brown into RB (projects 10.3)", "about": "00-9"}
    his = {"condition": "Rome Odunze (FLEX) is ruled out before game day",
           "action": "Start Rashid Shaheed at FLEX (projects 8.1).", "about": "00-0039919"}
    keep = {"condition": "Rome Odunze (FLEX) is cleared", "action": "Keep him.",
            "about": "00-0039919"}
    posts = drops.drafts(_report(lineup=lineup, pivots=[tuesday, keep, his]), live_page=True)
    [post] = [p for p in posts if p["name"] == "Thursday night"]
    assert post["text"] == ("Thursday night: Rome Odunze (FLEX, vs NE) kicks off at 8:15 PM "
                            "ET. The if/then we set on Wednesday for our sample roster: if "
                            "Rome Odunze (FLEX) is ruled out before game day, start Rashid "
                            "Shaheed at FLEX (projects 8.1).")
    assert post["when"].startswith("Post it: Thursday") and post["card"] == "If/Then for Gameday"
    assert "%" not in post["text"] and URL not in post["text"] and URL in post["reply"]
    plain = drops.drafts(_report(lineup=lineup, pivots=[tuesday]))
    [post] = [p for p in plain if p["name"] == "Thursday night"]
    assert post["text"].endswith("Our sample roster's Wednesday report flags it: set your "
                                 "lineup before then.") and post["card"] == "Your Game Plan"
    assert "Post it: Thursday, before his kickoff." in drops.render(_report(), plain)
    sunday = [dict(row, game="vs NE · Sun 1:00 PM ET") for row in lineup]
    assert "Thursday night" not in [p["name"] for p in drops.drafts(_report(lineup=sunday))]


def test_the_thursday_post_quotes_the_reports_own_ask() -> None:
    """Sweep OPS-4, reproduced on Week 9 of 2026: the draft said "Our sample
    roster's Wednesday report flags it: check his status before then" about
    Zay Flowers, who was on no injury report, while the report's own item said
    "Thursday night: Zay Flowers kicks off at 8:15 PM ET — set your lineup
    before then." The post takes the report's ask for HIM: "check his status"
    only when the report asks for his status, never because somebody else in
    the same game is listed."""
    lineup = [{"slot": "WR", "player_id": "00-7", "player_name": "Zay Flowers",
               "game": "vs JAX · Thu 8:15 PM ET"}]

    def thursday(item: str | None) -> str:
        checklist = [{"action": item}] if item else []
        posts = drops.drafts(_report(lineup=lineup, pivots=[], checklist=checklist))
        return _named(posts, "Thursday night")

    healthy = thursday("Thursday night: Zay Flowers kicks off at 8:15 PM ET — set your "
                       "lineup before then.")
    assert healthy.endswith("flags it: set your lineup before then.")
    assert "check his status" not in healthy
    listed = thursday("Thursday night: Zay Flowers kicks off at 8:15 PM ET — check his "
                      "status before then.")
    assert listed.endswith("flags it: check his status before then.")
    other = thursday("Thursday night: Zay Flowers and Mark Andrews kick off at 8:15 PM ET — "
                     "check Mark Andrews's status before then.")
    assert other.endswith("flags it: set your lineup before then.")
    named = thursday("Thursday night: Zay Flowers and Mark Andrews kick off at 8:15 PM ET — "
                     "check the status of Zay Flowers and Mark Andrews before then.")
    assert named.endswith("flags it: check his status before then.")
    assert thursday(None).endswith("flags it: set your lineup before then.")


def test_a_toss_up_is_never_drafted_as_a_pick() -> None:
    """Sweep OPS-2, reproduced on Week 9 of 2026: the closest call printed 52%
    and the page this post links said "Rome Odunze or Khalil Shakir — either
    is fine", while the draft read "Our sample roster's report starts Odunze:
    52% to outscore Shakir." A toss-up (render.report.regret_tossup: 52% or
    under, or the toss-up sentence in its reason) drafts no call post, the
    rule the landing's strip and the share card already follow."""
    from engine.solo_report import TOSSUP_SENTENCE
    base = _report()
    assert "The closest call" in [d["name"] for d in drops.drafts(base)]
    for regret in ({**base["regret"], "confidence": 0.524},
                   {**base["regret"], "reason": f"Closer than it looks. {TOSSUP_SENTENCE}"}):
        posts = drops.drafts(_report(regret=regret))
        assert "The closest call" not in [d["name"] for d in posts], regret
        assert not any("to outscore" in d["text"] for d in posts)


# --------------------------------------------------------------------- #
# Site review, Nov 6 2026: the drafts follow the site's own rules
# --------------------------------------------------------------------- #

UTC = timezone.utc
# A made-up Week 5 of 2026, in UTC (Eastern daylight time is UTC-4).
THU = datetime(2026, 10, 9, 0, 15, tzinfo=UTC)     # Thu 8:15 PM ET
SUN1 = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)   # Sun 1:00 PM ET
SUN4 = datetime(2026, 10, 11, 20, 25, tzinfo=UTC)  # Sun 4:25 PM ET
SNF = datetime(2026, 10, 12, 0, 20, tzinfo=UTC)    # Sun 8:20 PM ET
MNF = datetime(2026, 10, 13, 0, 15, tzinfo=UTC)    # Mon 8:15 PM ET
STARTS = {"NE": THU, "BAL": THU, "SEA": SUN1, "ARI": SUN1, "GB": SUN4, "DET": SUN4,
          "MIN": SUN4, "CLE": SUN4, "TB": SNF, "ATL": SNF, "DAL": MNF, "CIN": MNF}
# The clock render.live_sample writes for that week, in a week the landing
# links this week's page; the build runs Wednesday evening.
CLOCK = {"season": "2026", "week": 5, "last_week": 18, "lands_on": "2026-10-14",
         "week_ends": "2026-10-12", "first_kickoff": "2026-10-09T00:15:00Z", "odds": 4,
         "closest_call": True, "phase": "season", "cards": True}
BUILD = datetime(2026, 10, 7, 22, 30, tzinfo=UTC)
BYES = {"PIT": 9, "TEN": 9, "CHI": 10, "DEN": 10}


def _timed(**over) -> dict:
    """The fixture report with every row's game, as render prints it."""
    report = _report()
    report["meta"]["box_scores_as_of"] = "Box scores through Week 4."
    report["lineup"] = [
        {**report["lineup"][0], "game": "@ GB · Sun 4:25 PM ET"},
        {"slot": "RB", "player_id": "00-0035261", "player_name": "Tony Pollard",
         "confidence": None, "game": "vs SEA · Sun 1:00 PM ET",
         "usage": "last 4 games: 9 targets (2.3 a game), 70 carries"},
        {"slot": "WR", "player_id": "00-7", "player_name": "Zay Flowers",
         "confidence": None, "game": "vs NE · Thu 8:15 PM ET"}]
    report["bench"] = [{**report["bench"][0], "game": "vs TB · Sun 8:20 PM ET"},
                       {"player_id": "00-0038597", "name": "Chase Brown",
                        "game": "@ DAL · Mon 8:15 PM ET"}]
    report["pivots"] = [{"condition": "Tony Pollard (RB) is ruled out",
                         "action": "Move Chase Brown into RB (projects 10.3)",
                         "about": "00-0035261"}]
    report["rising"] = [{"name": "Aaron Jones", "team": "MIN", "position": "RB",
                         "recent": 23.0, "earlier": 13.0},
                        {"name": "Bijan Robinson", "team": "ATL", "position": "RB",
                         "recent": 25.0, "earlier": 18.0}]
    report["byes_ahead"] = []
    report.update(over)
    return report


def _all(report: dict, starts=STARTS, live_page: bool = False) -> dict[str, dict]:
    posts = drops.with_bye_drafts(drops.drafts(report, live_page=live_page, starts=starts),
                                  report, BYES, starts=starts)
    return {p["name"]: p for p in posts}


def _until(post: dict) -> datetime | None:
    return datetime.fromisoformat(post["until"]) if post.get("until") else None


def test_a_reply_links_this_weeks_page_only_when_the_landing_does() -> None:
    """Site review, reproduced on Week 9 of 2026: site/week.json said
    "total": false (the sample's kicker was on bye), so the landing, the
    footer and How it works all kept this-week.html unlinked, and the drafts
    still sent every X reader there, to a page opening on "no projected
    total". The rule is the landing's own, read from the clock this run
    wrote; when it fails, each reply links the home page and says what it is."""
    meta = _report()["meta"]
    assert drops.this_week_hidden(CLOCK, meta, BUILD) is None
    week9 = {"season": "2026", "week": 9, "last_week": 18, "lands_on": "2026-11-11",
             "week_ends": "2026-11-09", "built_at": "2026-11-04T22:17:50+00:00",
             "odds": 4, "closest_call": True, "first_kickoff": "2026-11-06T01:15:00Z",
             "recorded": True, "phase": "season", "byes_left": True, "cards": True,
             "total": False}
    reason = drops.this_week_hidden(week9, {"season": "2026", "week": 9},
                                    datetime(2026, 11, 4, 22, 30, tzinfo=UTC))
    assert reason == "its lineup has no projected total"
    for change, words in (({"total": False}, "no projected total"),
                          ({"odds": 2}, "fewer than 3 odds"),
                          ({"odds": True}, "fewer than 3 odds"),
                          ({"odds": "4"}, "fewer than 3 odds"),
                          ({"closest_call": False}, "no closest call"),
                          ({"cards": None}, "card layout"),
                          ({"cards": "true"}, "card layout"),
                          ({"phase": "over"}, "over"),
                          ({"phase": "preseason"}, "preseason"),
                          ({"week": 6}, "another week"),
                          ({"season": "2025"}, "another week"),
                          ({"week_ends": None}, "no dates"),
                          ({"lands_on": "soon"}, "no dates"),
                          ({"week_ends": "2026-10-06"}, "games are over"),
                          ({"lands_on": "2026-10-06"}, "games are over"),
                          ({"last_week": 5, "first_kickoff": "2026-10-07T00:00:00Z"},
                           "last week")):
        got = drops.this_week_hidden({**CLOCK, **change}, meta, BUILD)
        assert got and words in got, (change, got)
    assert "can't be read" in drops.this_week_hidden({}, meta, BUILD)
    # The last week before its kickoff is still linked.
    assert drops.this_week_hidden({**CLOCK, "last_week": 5}, meta, BUILD) is None
    # No phase is the season (every reader's rule).
    clock = {k: v for k, v in CLOCK.items() if k != "phase"}
    assert drops.this_week_hidden(clock, meta, BUILD) is None
    # "Today" is Eastern: 11:30 PM ET on the week's Monday is still the week.
    late = datetime(2026, 10, 13, 3, 30, tzinfo=UTC)
    assert drops.this_week_hidden(CLOCK, meta, late) is None
    assert "games are over" in drops.this_week_hidden(
        CLOCK, meta, datetime(2026, 10, 13, 4, 30, tzinfo=UTC))

    hidden = drops.drafts(_report())
    shown = drops.drafts(_report(), live_page=True)
    for post in hidden:
        assert post["reply"] == ("What it is, with a full sample report: "
                                 f"{SITE}/?via={post['via']}"), post
    for post in shown:
        assert post["reply"] == ("The whole report, rebuilt every Wednesday for our "
                                 f"sample roster: {URL}?w=5&via={post['via']}"), post
    text = drops.render(_report(), hidden, hidden="its lineup has no projected total")
    assert ("This week's page isn't linked. The site doesn't show it this week (its "
            "lineup has no projected total), so the replies that would link it link the home page "
            "instead. The bye drafts link the planner.") in text
    assert "isn't linked" not in drops.render(_report(), shown)


def test_the_rule_is_the_landings_own() -> None:
    """``this_week_hidden`` is a Python twin of the rule every page applies
    before it reveals a link to this-week.html. Held to the landing's and
    footer.js's own condition, so a change there fails here first."""
    def flat(path: Path) -> str:
        return " ".join(path.read_text(encoding="utf-8").split())
    landing = flat(ROOT / "site" / "index.html")
    [cond] = re.findall(r'if \(phase === "season" && current && (.*?)\) \{', landing)
    assert cond == ("Number.isInteger(w.odds) && w.odds >= 3 && w.closest_call && "
                    "w.cards === true && w.total !== false")
    assert ("const fresh = landsOk && etToday <= w.lands_on;" in landing
            and "etToday <= w.week_ends;" in landing
            and 'const phase = w.phase || "season";' in landing
            and "const last = w.week >= w.last_week;" in landing)
    footer = flat(ROOT / "site" / "footer.js")
    assert ("if (Number.isInteger(w.odds) && w.odds >= 3 && w.closest_call && "
            "w.cards === true && w.total !== false) {") in footer
    # The clock it reads is the one the same run wrote beside the page.
    assert drops.WEEK_JSON == ROOT / "site" / "week.json"
    weekly = (ROOT / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
    assert weekly.index("-m render.live_sample") < weekly.index("-m run.drops")


def test_every_draft_says_when_it_goes_stale() -> None:
    """Site review: on the Friday of Week 9 the file still offered "Thursday
    night: Zay Flowers … kicks off at 8:15 PM ET", a game already played, and
    the closest call carried no time at all. Each draft is now good until the
    first kickoff it is about: both players' for the call, the player and his
    cover for an if/then, the named players' for rising roles and workloads,
    his for Thursday's. The bye drafts hold until the week's last game."""
    posts = _all(_timed())
    assert _until(posts["The closest call"]) == SUN4         # LaPorta @ GB, before Odunze
    assert _until(posts["The if/then"]) == SUN1              # Pollard, before Brown on Monday
    assert _until(posts["Rising roles"]) == SUN4             # Jones (MIN), before Robinson
    assert _until(posts["Thursday night"]) == THU
    assert _until(posts["NFL byes left"]) == MNF
    assert _until(posts["Bye check"]) == MNF
    text = drops.render(_timed(), list(posts.values()))
    assert "Good until Sun Oct 11 · 4:25 PM ET." in text
    assert "Post it: Thursday, before his kickoff. Good until Thu Oct 8 · 8:15 PM ET." in text
    assert "Best posted on Wednesday. Good until Mon Oct 12 · 8:15 PM ET." in text
    assert text.count("\nGood until ") + text.count(". Good until ") == len(posts)
    # An if/then is about its cover too: one who plays first sets the time.
    lineup = [{**row, "game": "@ GB · Sun 4:25 PM ET"} if row["player_id"] == "00-0035261"
              else row for row in _timed()["lineup"]]
    bench = [{**row, "game": "vs SEA · Sun 1:00 PM ET"} if row["name"] == "Chase Brown"
             else row for row in _timed()["bench"]]
    assert _until(_all(_timed(lineup=lineup, bench=bench))["The if/then"]) == SUN1
    # Rising roles: only the players the post names, not the ones cut to fit.
    long = [{"name": f"A Very Long Rising Player Name {i}", "team": "TB", "position": "RB",
             "recent": 15.5, "earlier": 2.0} for i in range(5)]
    cut = {"name": "Cut Last", "team": "NE", "position": "WR", "recent": 9.0, "earlier": 1.0}
    rising = _all(_timed(rising=[*long, cut]))["Rising roles"]
    assert "Cut Last" not in rising["text"] and _until(rising) == SNF
    # Thursday's post is his game, even in a week that opens earlier.
    wednesday = {**STARTS, "KC": datetime(2026, 10, 8, 0, 15, tzinfo=UTC)}
    early = _all(_timed(), starts=wednesday)
    assert _until(early["Thursday night"]) == THU
    # A kickoff it can't place makes it the week's first, never later.
    assert _until(_all(_timed(bench=[]), starts=wednesday)["The closest call"]) == \
        wednesday["KC"]
    bench = [{k: v for k, v in row.items() if k != "game"} for row in _timed()["bench"]]
    unplaced = _all(_timed(bench=bench))
    assert _until(unplaced["The closest call"]) == THU
    assert _until(unplaced["The if/then"]) == THU
    nowhere = {"name": "Kaleb Johnson", "team": "XYZ", "position": "RB", "recent": 9.0,
               "earlier": 1.0}
    assert _until(_all(_timed(rising=[nowhere]))["Rising roles"]) == THU
    # Workloads: the players the post names.
    gated = {"gate": "no coin-flip call this week"}
    work = _all(_timed(regret=gated, rising=[], pivots=[]))["Workloads"]
    assert "Pollard" in work["text"] and "Flowers" not in work["text"]
    assert _until(work) == SUN1
    # No schedule at all: no time to give, and the file says what to go by.
    blind = _all(_timed(), starts={})
    assert all(p["until"] is None for p in blind.values())
    assert "Good until this week's first kickoff." in drops.render(_timed(), list(blind.values()))


def test_a_draft_past_its_time_is_left_out() -> None:
    """The Thursday draft read on Friday is about a game already played; a
    file written after a draft's time leaves it out and says so."""
    posts = list(_all(_timed()).values())
    kept, gone = drops.still_good(posts, datetime(2026, 10, 10, 12, 0, tzinfo=UTC))
    assert [p["name"] for p in gone] == ["Thursday night"]
    assert "Thursday night" not in [p["name"] for p in kept] and len(kept) == len(posts) - 1
    text = drops.render(_timed(), kept, gone=gone)
    assert "Left out, past their time: Thursday night." in text
    assert f"## {len(kept) + 1}." not in text
    kept, gone = drops.still_good(posts, BUILD)
    assert not gone and kept == posts
    # Exactly at the kickoff it is gone; with no time it stays.
    kept, gone = drops.still_good(posts, THU)
    assert [p["name"] for p in gone] == ["Thursday night"]
    blind = list(_all(_timed(), starts={}).values())
    assert drops.still_good(blind, MNF) == (blind, [])


def test_every_link_carries_its_own_via_tag() -> None:
    """Site review: the weekly replies were bare links, so a sale from an X
    post counted as untagged while posts were the channel being tried. Each
    reply's link carries ``x-wNN-<draft>``, by the site's own tag rule, one
    tag per draft, and the week's own ?w= stays first."""
    from run.refs import VIA_RE
    gated = {"gate": "no coin-flip call this week"}
    reports = (_timed(), _timed(regret=gated, rising=[], pivots=[]))
    seen: dict[str, str] = {}
    for live_page in (False, True):
        for report in reports:
            for name, post in _all(report, live_page=live_page).items():
                link = post["reply"].rsplit(" ", 1)[1]
                query = parse_qs(urlsplit(link).query)
                assert query["via"] == [post["via"]] and VIA_RE.fullmatch(post["via"]), post
                assert post["via"] == f"x-w05-{drops.SLUGS[name]}"
                assert link.count("?") == 1, link
                if "this-week.html" in link:
                    assert link == f"{URL}?w=5&via={post['via']}"
                seen.setdefault(post["via"], name)
                assert seen[post["via"]] == name, "two drafts share a tag"
    assert set(seen.values()) == set(drops.SLUGS)
    text = drops.render(_timed(), list(_all(_timed()).values()))
    assert "x-w05-" in text and "discord-w05-byes" in text


def test_the_bye_check_links_the_plain_planner() -> None:
    """Site review: "Check your own roster's byes" opened the planner on OUR
    sample roster, whose links then carried that roster into a free report and
    checkout. Both bye drafts link the bare planner (contract C7: /byes/)."""
    posts = _all(_timed())
    for name in ("NFL byes left", "Bye check"):
        link = posts[name]["reply"].rsplit(" ", 1)[1]
        assert link == f"{SITE}/byes/?via={posts[name]['via']}", link
        assert "ref=" not in posts[name]["reply"]
        assert posts[name]["reply"].startswith("Check your own roster's byes through Week 17")


def test_main_links_by_the_clock_this_run_wrote(tmp_path, monkeypatch) -> None:
    """The drafter reads site/week.json as render.live_sample left it: a clock
    the landing would not link sends each reply to the home page, and a
    missing or unreadable clock does the same (fail closed)."""
    import render.live_sample as live
    from engine.ledger import extract_published_calls, ledger_path, record_calls

    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: False)
    monkeypatch.setattr(drops, "_week_kickoffs", lambda season, week: {})
    processed = tmp_path / "processed"
    record_calls(ledger_path(processed, "typed-ppr-12-2026"), extract_published_calls(_report()))
    out, clock = tmp_path / "this-week.md", tmp_path / "week.json"
    future = {**CLOCK, "lands_on": "2099-12-30", "week_ends": "2099-12-29",
              "first_kickoff": "2099-12-28T00:00:00Z"}

    def drafted(clock_text: str | None) -> str:
        if clock_text is None:
            clock.unlink(missing_ok=True)
        else:
            clock.write_text(clock_text, encoding="utf-8")
        live.write_published_report(_report(), processed)
        assert drops.main(["--out", str(out), "--processed-dir", str(processed),
                           "--week-json", str(clock)]) == 0
        return out.read_text(encoding="utf-8")

    linked = drafted(json.dumps(future))
    assert f"{URL}?w=5&via=x-w05-closest" in linked and "isn't linked" not in linked
    assert "55% to outscore Odunze" in linked
    for text in (drafted(json.dumps({**future, "total": False})), drafted(None),
                 drafted("{not json")):
        assert URL + "?" not in text and f"{SITE}/?via=x-w05-closest" in text
        assert "This week's page isn't linked." in text
    # A week already played (here, Oct 2026 read in a later month): every
    # draft is past its time, and the file says so rather than "nothing to say".
    monkeypatch.setattr(drops, "_week_kickoffs", lambda season, week: dict(STARTS))
    stale = drafted(json.dumps(future))
    assert "## 1." not in stale and "Left out, past their time: The closest call" in stale
    assert "Nothing left to post this week" in stale and "had no closest call" not in stale
