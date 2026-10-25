"""Tuesday's public posts (run/drops.py): drafts that say what they are."""

from __future__ import annotations

from pathlib import Path

from run import drops

ROOT = Path(__file__).resolve().parent.parent
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


def _named(posts: list[dict], name: str) -> str:
    [text] = [p["text"] for p in posts if p["name"] == name]
    return text


def test_every_post_fits_says_sample_and_links_the_live_report() -> None:
    posts = drops.drafts(_report())
    assert [p["name"] for p in posts] == ["The closest call", "The if/then", "Rising roles"]
    for post in posts:
        assert len(post["text"]) <= drops.LIMIT, post["name"]
        # The link rides the first reply, never the post (launch review M8).
        assert URL not in post["text"] and URL in post["reply"]
    assert "sample roster" in posts[0]["text"] and "sample roster" in posts[1]["text"]
    assert "55%" in posts[0]["text"]


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
    assert body.index("recorded_only(") < body.index("drafts(report)")


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
    posts = drops.drafts(_report(lineup=lineup, pivots=[tuesday, keep, his]))
    [post] = [p for p in posts if p["name"] == "Thursday night"]
    assert post["text"] == ("Thursday night: Rome Odunze (FLEX, vs NE) kicks off at 8:15 PM "
                            "ET. The if/then we set on Tuesday for our sample roster: if "
                            "Rome Odunze (FLEX) is ruled out before game day, start Rashid "
                            "Shaheed at FLEX (projects 8.1).")
    assert post["when"].startswith("Thursday") and post["card"] == "If/Then for Gameday"
    assert "%" not in post["text"] and URL not in post["text"] and URL in post["reply"]
    plain = drops.drafts(_report(lineup=lineup, pivots=[tuesday]))
    [post] = [p for p in plain if p["name"] == "Thursday night"]
    assert post["text"].endswith("Our sample roster's Tuesday report flags it: check his "
                                 "status before then.") and post["card"] == "Your Game Plan"
    assert "Post it: Thursday, before his kickoff." in drops.render(_report(), plain)
    sunday = [dict(row, game="vs NE · Sun 1:00 PM ET") for row in lineup]
    assert "Thursday night" not in [p["name"] for p in drops.drafts(_report(lineup=sunday))]
