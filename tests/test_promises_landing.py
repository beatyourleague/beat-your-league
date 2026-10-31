"""Landing promises made exactly true (promise audit, Oct 18 2026).

Each test names the confirmed finding it pins. The page-script ones read the
script text, as test_site.py's season-clock tests do; the behaviour itself was
checked once in headless Chrome against week.json in each phase.
"""
from __future__ import annotations

import re

from test_site import LANDING, markup_only, prose

SCRIPT = LANDING.split("// The season clock.")[1].split("})();")[0]
TEXT = prose(LANDING)


def test_live_week_links_wait_for_a_current_season_week() -> None:
    """LANDING-32/41, D9: an old week.json (a failed build, the offseason) once
    revealed "see this week's" for a January report. The reveal now needs phase
    "season" and an Eastern today no later than lands_on."""
    reveal = SCRIPT.split('querySelectorAll("[data-live-week]")')[0].rsplit("if (", 1)[1]
    assert 'phase === "season" && fresh' in reveal and "w.odds >= 3 && w.closest_call" in reveal
    assert "etToday <= w.lands_on" in SCRIPT and 'timeZone: "America/New_York"' in SCRIPT
    assert 'w.phase || "season"' in SCRIPT, "a week.json without phase reads as season"


def test_the_season_end_puts_the_closed_state_back() -> None:
    """D9/LANDING-102: "Your first report lands today" with no report left to
    send. Over, or from the last week's first kickoff, the landing closes."""
    assert 'phase === "over" ||' in SCRIPT and "closeForSeason(" in SCRIPT
    assert "last && ((landsOk && !fresh) || kicked)" in SCRIPT
    fn = LANDING.split("function closeForSeason(line) {")[1].split("\n}\n")[0]
    for must in ('"watch-form", "watch-note"', '"try-cta", "risk-line", "closer-cta"',
                 "el.hidden = true", "el.hidden = false", "carryVia("):
        assert must in fn, must
    # The roster check has no week left to check: the main buttons go to the
    # capture, which is the one thing a visitor can still do.
    for cta in ("hero-open", "sticky-cta", "nav-cta"):
        assert f'"{cta}"' in fn, cta
    assert 'el.setAttribute("href", "#watch-form");' in fn
    # The flip keeps what it replaces, under the ids the revert looks up.
    assert 'link.id = "season-cta"' in LANDING
    assert "closedState = [" in LANDING.split("if (CHECKOUT_CAN_COMPLETE)")[0]


def test_the_day_one_line_names_what_actually_lands() -> None:
    """LANDING-54/56/65/89/111: the day-one email is that week's report only
    before its first game (from Week 2); otherwise the report of the weeks
    ahead. To a buyer both are "your first report" (sales review: "roster
    report" named an email nobody had heard of), so the open line says only
    that it lands today."""
    for gone in ("Your first report the day you sign up", "the first on the day you join",
                 "Your first one comes the day you sign up"):
        assert gone not in LANDING, gone
    assert TEXT.count("within the hour") >= 3
    assert "Your first report usually lands within the hour" in TEXT
    assert "Set up now and your first report lands today." in LANDING
    # No string the page's scripts can write says it (comments may explain).
    scripts = "\n".join(re.findall(r"<script>(.*?)</script>", LANDING, re.S))
    assert not re.findall(r'"[^"\n]*roster report[^"\n]*"', re.sub(r"//[^\n]*", "", scripts))
    assert "roster report" not in prose(markup_only(LANDING))


def test_monthly_billing_words_match_the_billing_rule() -> None:
    """LANDING-60, D1: no part-month after the season, and no offseason claim a
    pre-season monthly purchase would break."""
    assert "we don't charge through the offseason" not in TEXT
    # 2026 (Oct 31): a monthly plan, with when it stops on its card.
    assert "/ month" in LANDING and "Stops on its own after your title game" in LANDING


def test_lineups_sizes_and_tagline() -> None:
    """D16, D18 (JOIN-36, LANDING-83): Yahoo's default is the standard lineup;
    only even sizes are offered."""
    assert "Beat Your League</b> — analysis, not betting picks." in LANDING
    assert "8 to 14 teams" not in LANDING
    assert LANDING.count("8, 10, 12 or 14 teams") >= 2   # the FAQ twins
    assert LANDING.count("standard (ESPN's and Yahoo's default)") == 2
    assert not re.search(r"three WR[^.;]*?'s default", LANDING)


def test_receipts_odds_and_bar_words_describe_the_report() -> None:
    """LANDING-7/17/33/35/52/79/96/106 and D3/D11/D12."""
    assert "outscores your best bench player at that spot" in TEXT
    assert "the bar starts at 50% (a toss-up)" in TEXT   # D12: drawn from 50%
    for gone in ("lists last week's calls", "Decided calls, with odds",
                 "for your roster, with the odds.", "with the odds and the reason",
                 "scored to your league's settings", "the one player whose news"):
        assert gone not in TEXT, gone
    assert LANDING.count("calls with odds from the one before it") == 2
    # One-time passes have nothing to cancel, so the D3 carve-out is gone.
    assert LANDING.count("Stripe's billing page shows only the newest") == 0
    assert LANDING.count("by Friday night (ET)") == 2


def test_the_league_pass_names_its_size_limit() -> None:
    """D18: a pass carries as many seats as its league has teams, up to 14 —
    "covers every manager" with no limit was false for a 16-team league.
    Since Oct 28 2026 the landing names the pass in one line under the price
    (its FAQ answer went with the FAQ's cut to five), and the limit rides in
    that same strip, in the sentence that says "covers every manager"."""
    line = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", re.search(
        r'<p class="lpline">(.*?)</p>', LANDING, re.S).group(1)))
    assert "covers every manager, each with their own report, up to 14 teams." in line
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", LANDING))
    assert flat.count("covers every manager") == 1, "an unlimited claim elsewhere"
