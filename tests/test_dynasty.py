"""The dynasty page (owner decision, Oct 31 2026): what the weekly report does
for a dynasty or keeper manager today, and what it does not do."""

from __future__ import annotations

import html
import re
from pathlib import Path

from render import platforms
from run.refs import MAX_ROSTER

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = (SITE / "dynasty" / "index.html").read_text(encoding="utf-8")
WORDS = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", re.sub(
    r"<script.*?</script>|<style.*?</style>|<head>.*?</head>", " ", PAGE, flags=re.S))).split())


def test_the_page_is_generated_and_current() -> None:
    assert platforms.build(SITE)[SITE / "dynasty" / "index.html"] == PAGE


def test_dynasty_is_a_kind_of_league_not_an_app() -> None:
    assert platforms.DYNASTY not in platforms.PLATFORMS
    assert "Copied from" not in WORDS, "dynasty has no copy format of its own"


def test_the_roster_limit_is_the_one_the_page_enforces() -> None:
    assert f"up to {MAX_ROSTER} players" in WORDS
    assert f"More than {MAX_ROSTER} players? Leave out your IR and taxi players." in WORDS


def test_it_says_what_it_is_not() -> None:
    """Each line stops a buyer paying for something that does not exist."""
    for limit in ("It doesn't value trades, rank rookies or help with your startup or rookie draft",
                  "it isn't tuned for dynasty",
                  "Reports run during the NFL season, not the off-season",
                  "TE premium and six-point passing touchdowns aren't scored yet",
                  "Their odds wait until they have enough games on record"):
        assert limit in WORDS, limit


def test_it_carries_no_price_and_promises_no_off_season_product() -> None:
    assert "$" not in WORDS
    assert not re.search(r"year[- ]round|coming soon|all year", WORDS, re.I)


def test_it_opens_join_with_no_lineup_chosen_for_the_manager() -> None:
    assert 'href="../join/index.html?t=' not in PAGE
    assert 'class="shape is"' not in PAGE


def test_every_app_page_and_the_landing_lead_to_it() -> None:
    for slug in ("espn", "yahoo", "sleeper", "cbs"):
        page = (SITE / slug / "index.html").read_text(encoding="utf-8")
        assert '<a href="../dynasty/">Dynasty or keeper league? See what you get</a>' in page
    landing = (SITE / "index.html").read_text(encoding="utf-8")
    assert '<a href="dynasty/">Dynasty and keeper leagues</a> too.' in landing
    assert "https://beatyourleague.com/dynasty/" in (SITE / "sitemap.xml").read_text(encoding="utf-8")


def test_the_page_is_counted_and_keeps_its_channel_tag() -> None:
    assert '"dynasty"' in (SITE / "count.js").read_text(encoding="utf-8")
    assert "(?:espn|yahoo|sleeper|cbs|dynasty)" in PAGE
