"""Tuesday's public posts (run/drops.py): drafts that say what they are."""

from __future__ import annotations

from pathlib import Path

from run import drops

ROOT = Path(__file__).resolve().parent.parent
URL = "https://beatyourleague.com/this-week.html"


def _report(**over) -> dict:
    report = {
        "meta": {"week": 5},
        "regret": {"start_id": "00-0038542", "start_name": "Sam LaPorta",
                   "over_id": "00-0039919", "over_name": "Rome Odunze",
                   "confidence": 0.554,
                   "drivers": [{"label": "proj", "value": "10.6 vs 9.7"},
                               {"label": "games this season", "value": "4 vs 4"}]},
        "lineup": [{"slot": "FLEX", "player_id": "00-0038542",
                    "player_name": "Sam LaPorta", "confidence": 0.554,
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
        assert URL in post["text"]
    assert "sample roster" in posts[0]["text"] and "sample roster" in posts[1]["text"]
    assert "55%" in posts[0]["text"]


def test_the_call_leads_with_the_question_then_a_fact_then_the_number() -> None:
    """Launch audit: the closest call is by construction near a coin flip, and
    the post opened with the % and a link — nothing a reader could weigh. It
    now asks what a manager asks, gives the report's own facts for the pair,
    and only then the number."""
    text = _named(drops.drafts(_report()), "The closest call")
    assert text.startswith("LaPorta or Odunze this week? ")
    usage = "LaPorta, last 4 games: 26 targets (6.5 a game)."      # verbatim
    games = "Odunze's last three games: 7.4, 15.4 and 5.0 points."
    assert usage in text and games in text
    assert text.index(usage) < text.index("55%") and text.index(games) < text.index("55%")
    assert "starts LaPorta: 55% to outscore Odunze" in text


def test_the_fact_line_gives_way_before_the_post_is_dropped() -> None:
    """Long names push the post past 280: one player's fact goes first, the
    question and the number never do."""
    long_a, long_b = "Christopher Longname-Hyphenated", "Bartholomew Extralongsurname"
    regret = {**_report()["regret"], "start_name": long_a, "over_name": long_b}
    lineup = [{**_report()["lineup"][0], "player_name": long_a,
               "usage": "last 4 games: 26 targets (6.5 a game), 31 carries, "
                        "4 inside the 20"}]
    text = _named(drops.drafts(_report(regret=regret, lineup=lineup)), "The closest call")
    assert len(text) <= drops.LIMIT
    assert text.startswith("Longname-Hyphenated or Extralongsurname this week? ")
    assert "55%" in text and text.count("last") == 1


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
              "drivers": [{"label": "seeded", "value": "last season counted in"}]}
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
    assert "sample roster" in text and URL in text and len(text) <= drops.LIMIT
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
    assert post["text"].count(long_name) < 6 and post["text"].rstrip().endswith("this-week.html")


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
