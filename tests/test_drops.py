"""Tuesday's public posts (run/drops.py): drafts that say what they are."""

from __future__ import annotations

from pathlib import Path

from run import drops

ROOT = Path(__file__).resolve().parent.parent


def _report(**over) -> dict:
    report = {
        "meta": {"week": 5},
        "regret": {"start_name": "Sam LaPorta", "over_name": "Rome Odunze",
                   "confidence": 0.554,
                   "drivers": [{"label": "proj", "value": "10.6 vs 9.7"}]},
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


def test_every_post_fits_says_sample_and_links_the_live_report() -> None:
    posts = drops.drafts(_report())
    assert [p["name"] for p in posts] == ["The closest call", "The if/then", "Rising roles"]
    for post in posts:
        assert len(post["text"]) <= drops.LIMIT, post["name"]
        assert "https://beatyourleague.com/this-week.html" in post["text"]
    assert "sample roster" in posts[0]["text"] and "sample roster" in posts[1]["text"]
    assert "55%" in posts[0]["text"] and "projected 10.6 vs 9.7" in posts[0]["text"]


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
    poisoned = _report(pivots=[{"condition": "X is out", "action": "Take the spread"}])
    assert "The if/then" not in [p["name"] for p in drops.drafts(poisoned)]


def test_nothing_to_say_means_no_posts_not_invented_ones() -> None:
    assert drops.drafts(_report(regret={}, pivots=[], rising=[])) == []
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
