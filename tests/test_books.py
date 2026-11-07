"""run/books.py — the owner's costs, hours and post links (data/, gitignored)."""

from __future__ import annotations

from datetime import date

import pytest

import run.books as books
from run.books import Cost, charges, monthly_run_rate, next_charges, spent


def _write(root, name, text):
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / name).write_text(text, encoding="utf-8")


def test_a_monthly_cost_lands_on_the_last_day_of_a_short_month() -> None:
    c = Cost(date(2026, 1, 31), "Mailbox", 10.0, "monthly")
    assert charges(c, date(2026, 4, 30)) == [date(2026, 1, 31), date(2026, 2, 28),
                                              date(2026, 3, 31), date(2026, 4, 30)]


def test_costs_count_on_the_day_they_are_charged() -> None:
    costs = [Cost(date(2026, 8, 1), "Domain", 12.0, "yearly"),
             Cost(date(2026, 9, 5), "Mailbox", 9.99, "monthly"),
             Cost(date(2026, 10, 20), "Ad", 40.0, "once"),
             Cost(date(2026, 12, 1), "Not yet", 99.0, "once")]
    today = date(2026, 10, 28)
    assert spent(costs, None, today) == round(12 + 9.99 * 2 + 40, 2)
    assert spent(costs, date(2026, 9, 28), today) == round(9.99 + 40, 2)   # Oct 5 and Oct 20
    assert monthly_run_rate(costs) == round(9.99 + 1, 2)
    assert [(d.isoformat(), c.item) for d, c in next_charges(costs, today)] == [("2026-11-05", "Mailbox")]


def test_a_bad_line_is_skipped_and_reported_never_guessed(tmp_path) -> None:
    _write(tmp_path, "costs.csv", "date,item,amount,repeats\n"
                                  "# a comment line\n"
                                  "2026-10-01,Domain,12,yearly\n"
                                  "2026-10-02,Typo,twelve,once\n"
                                  "2026-10-03,Weekly thing,5,weekly\n"
                                  "\n"
                                  "2026-10-04,Ad,$1,200.50,once\n")
    b = books.load(tmp_path)
    assert [c.item for c in b.costs] == ["Domain"]
    assert len(b.problems) == 3
    assert "line 4" in b.problems[0] and "line 5" in b.problems[1]


def test_quoted_amounts_with_commas_read(tmp_path) -> None:
    _write(tmp_path, "costs.csv", 'date,item,amount,repeats\n2026-10-04,"Ads, round 1","$1,200.50",once\n')
    b = books.load(tmp_path)
    assert b.costs == [Cost(date(2026, 10, 4), "Ads, round 1", 1200.5, "once")] and not b.problems


def test_no_files_means_nothing_found(tmp_path) -> None:
    b = books.load(tmp_path)
    assert b.found == () and not b.costs and not b.posts


def test_the_tag_rule_is_the_one_the_site_and_intake_use() -> None:
    from run.refs import VIA_RE
    import run.stats as stats
    assert books.TAG_RE.pattern == VIA_RE.pattern == stats.VIA_RE.pattern


def test_cost_command_appends_with_a_header(tmp_path, capsys) -> None:
    assert books.cli(["cost", "Domain", "12", "--repeats", "yearly", "--date", "2026-08-01"], root=tmp_path) == 0
    assert books.cli(["cost", "Ad", "$40.00"], root=tmp_path) == 0
    text = (tmp_path / "data" / "costs.csv").read_text()
    assert text.splitlines()[0] == "date,item,amount,repeats"
    assert "2026-08-01,Domain,12.00,yearly" in text
    assert books.cli(["cost", "Ad", "forty"], root=tmp_path) == 2
    assert len(books.load(tmp_path).costs) == 2


def test_link_prints_a_tagged_link_and_refuses_a_reused_tag(tmp_path, capsys) -> None:
    assert books.cli(["link", "reddit-oct28", "--where", "r/fantasyfootball", "--page", "byes/"],
                     root=tmp_path) == 0
    out = capsys.readouterr().out
    assert "https://beatyourleague.com/byes/?via=reddit-oct28" in out
    assert books.load(tmp_path).posts[0].channel == "reddit"
    # Reusing a tag would merge two posts' numbers.
    assert books.cli(["link", "reddit-oct28"], root=tmp_path) == 2


@pytest.mark.parametrize("tag", ["Reddit Oct28", "reddit_oct28", "a" * 25, ""])
def test_link_refuses_a_tag_the_site_would_drop(tag, tmp_path) -> None:
    assert books.cli(["link", tag], root=tmp_path) == 2
    assert not (tmp_path / "data" / "posts.csv").exists()


@pytest.mark.parametrize("page", ["https://evil.example/", "../x", "join/?a=1",
                                  # Only the free report's own query is a page.
                                  "join/?try=2", "join/?try=1&via=x", "join/?try=1#x",
                                  "byes/?try=1", "join/?ref=s4-abc", "join/?try=1&ref=s4-abc",
                                  "?try=1", "join?try=1x"])
def test_link_refuses_a_page_outside_the_site(page, tmp_path) -> None:
    assert books.cli(["link", "x-1", "--page", page], root=tmp_path) == 2
    assert not (tmp_path / "data" / "posts.csv").exists()


def test_link_tags_the_free_report_link_with_an_ampersand(tmp_path, capsys) -> None:
    """Site review, Nov 6 2026: `make link PAGE=join/?try=1` was refused, so a
    post offering the free report could carry no ?via= tag, and the one way to
    see which post brought a free request (and the sale after it) was lost.
    It is the one query a page may carry; the tag joins it with "&", because
    a second "?" ("join/?try=1?via=…") would make try read "1?via=…" and the
    page would open as the buy page with no tag at all."""
    assert books.cli(["link", "league-nov10", "--where", "my league chat",
                      "--page", "join/?try=1"], root=tmp_path) == 0
    out = capsys.readouterr().out
    link = "https://beatyourleague.com/join/?try=1&via=league-nov10"
    assert f"  {link}\n" in out and out.count("?") == 1
    # The link opens join's free report and carries the tag the site reads.
    from urllib.parse import parse_qs, urlsplit
    query = parse_qs(urlsplit(link).query)
    assert query == {"try": ["1"], "via": ["league-nov10"]}
    join = (books.REPO_ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    assert 'QUERY.get("try") === "1"' in join
    assert books.load(tmp_path).posts[0].tag == "league-nov10"
    # The same rules as any link: a reused tag is refused.
    assert books.cli(["link", "league-nov10", "--page", "join/?try=1"], root=tmp_path) == 2
    assert books.tagged_link("x-1", "byes/") == "https://beatyourleague.com/byes/?via=x-1"
    assert books.tagged_link("x-1") == "https://beatyourleague.com/?via=x-1"


def test_the_books_live_under_the_gitignored_data_folder() -> None:
    import run.stats as stats
    for path in (books.COSTS, books.HOURS, books.POSTS):
        assert path.parent == books.REPO_ROOT / "data" and stats._gitignored(path)


# --------------------------------------------------------------------- #
# HQ's feed (HQ SPEC section 9): costs and hours come from the Mac app
# --------------------------------------------------------------------- #

import json
import os

FEED = {
    "schema": "hq-feed/1", "generated_at": "2026-11-07T12:00:00Z", "rates_as_of": "2026-11-06",
    "business": {"id": "b1", "name": "Beat Your League", "slug": "beat-your-league", "currency": "CAD"},
    "costs": [
        {"id": "c1", "date": "2026-11-07", "item": "Domain", "category": "software", "amount": "10.46",
         "currency": "USD", "amount_business": "14.45", "amount_usd": "10.46", "refund": False},
        {"id": "c2", "date": "2026-11-10", "item": "Ad credit back", "category": "advertising",
         "amount": "5.00", "currency": "USD", "amount_business": "6.90", "amount_usd": "5.00", "refund": True},
        {"id": "c3", "date": "2026-11-09", "item": "Lawyer", "category": "professional", "amount": "100.00",
         "currency": "CAD", "amount_business": "100.00", "amount_usd": None, "refund": False},
    ],
    "repeating": [{"id": "r1", "item": "Mailbox", "amount": "10.00", "currency": "USD", "amount_usd": "10.00",
                   "every": "monthly", "first": "2026-11-01", "until": None}],
    "hours": [{"id": "h1", "date": "2026-11-07", "hours": 2.0, "note": "Launch setup"}],
    "problems": [],
}


def _feed(tmp_path, feed=FEED, slug="beat-your-league"):
    feeds = tmp_path / "hq" / "feeds"
    feeds.mkdir(parents=True)
    (feeds / "index.json").write_text(json.dumps({slug: "b1"}), encoding="utf-8")
    (feeds / "b1.json").write_text(json.dumps(feed), encoding="utf-8")
    return feeds


def test_the_tests_never_read_the_owners_real_feed() -> None:
    assert os.environ["HQ_HOME"] and "Application Support" not in os.environ["HQ_HOME"]


def test_with_hq_costs_and_hours_come_from_the_feed_not_the_csvs(tmp_path) -> None:
    _write(tmp_path, "costs.csv", "date,item,amount,repeats\n2026-11-07,Old,99,once\n")
    _write(tmp_path, "posts.csv", "date,tag,where,note\n2026-11-07,reddit-nov7,r/x,\n")
    b = books.load(tmp_path, feeds=_feed(tmp_path))
    assert b.hq and "hq" in b.found and "costs.csv" not in b.found
    assert [c.item for c in b.costs if not c.template] == ["Domain", "Ad credit back"]
    assert [p.tag for p in b.posts] == ["reddit-nov7"]          # posts still live here
    assert [h.hours for h in b.hours] == [2.0]


def test_a_feed_line_with_no_dollar_amount_is_reported_not_guessed(tmp_path) -> None:
    b = books.load(tmp_path, feeds=_feed(tmp_path))
    assert any("HQ cost 3 was skipped" in p and "exchange rate" in p for p in b.problems)


def test_a_refund_reduces_costs_and_a_template_never_counts_twice(tmp_path) -> None:
    b = books.load(tmp_path, feeds=_feed(tmp_path))
    # 10.46 - 5.00; the Mailbox template schedules but HQ's own charge lines count.
    assert spent(b.costs, None, date(2026, 11, 30)) == 5.46
    assert monthly_run_rate(b.costs, date(2026, 11, 30)) == 10.0
    assert [(d, c.item) for d, c in next_charges(b.costs, date(2026, 11, 7))] == [(date(2026, 12, 1), "Mailbox")]


def test_a_stale_or_broken_feed_says_so(tmp_path) -> None:
    old = dict(FEED, generated_at="2026-10-01T00:00:00Z")
    b = books.Books([], [], [], [], ())
    path = _feed(tmp_path, old) / "b1.json"
    books.load_hq_feed(path, b, today=date(2026, 11, 7))
    assert any("from 2026-10-01" in p for p in b.problems)
    path.write_text("{not json", encoding="utf-8")
    b2 = books.Books([], [], [], [], ())
    books.load_hq_feed(path, b2)
    assert not b2.hq and any("couldn't be read" in p for p in b2.problems)


def test_stripe_lines_from_hq_are_left_out_because_revenue_is_already_net(tmp_path) -> None:
    fee = {"id": "s1", "date": "2026-11-08", "item": "Stripe fee", "category": "payment-fees",
           "amount": "1.20", "currency": "CAD", "amount_business": "1.20", "amount_usd": "0.87",
           "refund": False, "source": "stripe"}
    b = books.load(tmp_path, feeds=_feed(tmp_path, dict(FEED, costs=FEED["costs"] + [fee])))
    assert "Stripe fee" not in [c.item for c in b.costs]


def test_another_business_feed_is_never_read(tmp_path) -> None:
    b = books.load(tmp_path, feeds=_feed(tmp_path, slug="other-site"))
    assert not b.hq and b.costs == []


def test_a_stopped_repeating_cost_stops_charging_and_leaves_the_run_rate() -> None:
    c = Cost(date(2026, 1, 15), "Tool", 20.0, "monthly", until=date(2026, 3, 1))
    assert charges(c, date(2026, 6, 30)) == [date(2026, 1, 15), date(2026, 2, 15)]
    assert monthly_run_rate([c], date(2026, 6, 30)) == 0
    q = Cost(date(2026, 1, 31), "Insurance", 30.0, "quarterly")
    assert charges(q, date(2026, 8, 1)) == [date(2026, 1, 31), date(2026, 4, 30), date(2026, 7, 31)]
    assert monthly_run_rate([q], date(2026, 8, 1)) == 10.0


def test_make_cost_refuses_once_hq_owns_the_costs(tmp_path, monkeypatch, capsys) -> None:
    home = tmp_path / "hq"
    _feed(tmp_path)
    monkeypatch.setenv("HQ_HOME", str(home))
    assert books.cli(["cost", "Domain", "12"], root=tmp_path) == 2
    assert "Add it in HQ" in capsys.readouterr().err
    assert not (tmp_path / "data" / "costs.csv").exists()
