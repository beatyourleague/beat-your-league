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


@pytest.mark.parametrize("page", ["https://evil.example/", "../x", "join/?a=1"])
def test_link_refuses_a_page_outside_the_site(page, tmp_path) -> None:
    assert books.cli(["link", "x-1", "--page", page], root=tmp_path) == 2


def test_the_books_live_under_the_gitignored_data_folder() -> None:
    import run.stats as stats
    for path in (books.COSTS, books.HOURS, books.POSTS):
        assert path.parent == books.REPO_ROOT / "data" and stats._gitignored(path)
