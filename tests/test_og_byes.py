"""The bye planner's share card (render/og.py --byes, site/og/byes-SSSS-wNN.png).

Every launch post links the free planner, and its preview was og.png: a 2024
lineup with 80%, 73% and 72% bars over "Know who to start." A free tool with
no odds previewed as an ad for picks, on Discord too, where the post promised
not to push the paid product (site review, Nov 6 2026). The planner now has
its own card, drawn from site/join/byes.json and nothing else: the brand, what
the tool is, the apps, "No login", and the NFL byes from the week being played
through Week 17. Schedule facts only. No %, no projection, no price, nothing
that counts the season down.
"""

from __future__ import annotations

import html
import json
import re
import struct
from datetime import date, timedelta
from pathlib import Path

import pytest

from render import og

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
PLANNER = SITE / "byes" / "index.html"

BYES_2026 = {"CAR": 5, "KC": 5, "CIN": 6, "DET": 6, "MIA": 6, "MIN": 6, "BUF": 7, "JAX": 7,
             "LAC": 7, "WAS": 7, "HOU": 8, "NO": 8, "NYG": 8, "SF": 8, "PIT": 9, "TEN": 9,
             "CHI": 10, "DEN": 10, "PHI": 10, "TB": 10, "ATL": 11, "CLE": 11, "GB": 11,
             "LA": 11, "NE": 11, "SEA": 11, "BAL": 13, "IND": 13, "LV": 13, "NYJ": 13,
             "ARI": 14, "DAL": 14}


def _payload(generated: str = "2026-11-05T06:57:25+00:00", byes=None) -> dict:
    """site/join/byes.json's shape, as render/bye_index.build writes it."""
    byes = BYES_2026 if byes is None else byes
    weeks = []
    for week in range(1, 19):
        ends = (date(2026, 9, 14) + timedelta(days=7 * (week - 1))).isoformat()
        weeks.append({"week": week, "ends": ends if week < 18 else "2027-01-10",
                      "bye": sorted(t for t, w in byes.items() if w == week)})
    return {"season": "2026", "generated": generated, "reserve_as_of": generated,
            "attribution": "NFL data: nflverse", "last_week": 18, "weeks": weeks, "out": {}}


def _visible(card_html: str) -> str:
    text = re.sub(r"<style>.*?</style>", " ", card_html, flags=re.S)
    text = re.sub(r"<svg.*?</svg>", " ", text, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


# --------------------------------------------------------------------- #
# what the card says
# --------------------------------------------------------------------- #

def test_the_card_lists_the_byes_from_the_week_being_played_through_week_17() -> None:
    """The week being played is render.bye_index.played_before's, on the
    file's own stamp, the rule the page's table uses to mark weeks played: a
    Nov 5 build is Week 9, whose games end Monday Nov 9. Week 9's teams are in
    the list, since they sit out that Sunday. nflverse's "LA" is printed as
    the apps print it, "LAR" (run.drops._app_code)."""
    facts = og.byes_card_facts(_payload())
    assert (facts["season"], facts["from"], facts["through"]) == ("2026", 9, 17)
    assert facts["rows"] == [{"week": 9, "teams": ["PIT", "TEN"]},
                             {"week": 10, "teams": ["CHI", "DEN", "PHI", "TB"]},
                             {"week": 11, "teams": ["ATL", "CLE", "GB", "LAR", "NE", "SEA"]},
                             {"week": 13, "teams": ["BAL", "IND", "LV", "NYJ"]},
                             {"week": 14, "teams": ["ARI", "DAL"]}]
    assert facts["empty"] == [12, 15, 16, 17]
    seen = _visible(og.byes_card_html(facts))
    for words in ("Beat Your League", "Free bye week planner", "Your roster, through Week 17.",
                  "ESPN · Yahoo · Sleeper · CBS", "No login.", "2026 NFL byes", "Week 9 to 17",
                  "Week 11 ATL CLE GB LAR NE SEA", "No byes in Weeks 12 and 15–17.",
                  "beatyourleague.com"):
        assert words in seen, (words, seen)
    assert " LA " not in f" {seen} "
    # Played weeks are never on it.
    for played in ("Week 5 ", "Week 8 ", "CAR", "SF"):
        assert played not in seen, played


def test_the_card_carries_no_odds_no_price_and_no_countdown() -> None:
    """The point of the card. Swept on the card's own text and its alt text,
    in every shape the list can take (mid-season, before Week 1, after the
    last bye): no %, no figure with a % after it, no $ or price word, no
    projection or odds vocabulary, no betting word, none of the banned words,
    no em dash, and nothing counting weeks down."""
    from tests.test_site import _DEV_SPEAK
    for generated in ("2026-11-05T06:57:25+00:00", "2026-08-20T12:00:00+00:00",
                      "2026-12-16T12:00:00+00:00"):
        facts = og.byes_card_facts(_payload(generated))
        for surface in (_visible(og.byes_card_html(facts)), og.byes_card_alt(facts)):
            assert "%" not in surface and not re.search(r"\d\s*(%|percent)", surface, re.I)
            assert "$" not in surface and not re.search(
                r"\b(price|month|paid|subscribe|odds|project\w*|chance|win|start|sit)\b",
                surface, re.I), surface
            assert not re.search(r"\b(calibrated|tested|proven|accurate|just|exactly)\b",
                                 surface, re.I), surface
            assert not re.search(r"\b(bet|wager|spread|parlay|lock|sportsbook)\b", surface, re.I)
            assert "—" not in surface, surface
            assert not re.search(r"\b\d+ (more )?(lineups?|weeks?|reports?) "
                                 r"(left|to go|remaining)\b", surface, re.I), surface
            assert not re.search(r"\b(left|ahead)\b", surface, re.I), surface
            for pattern in _DEV_SPEAK:
                assert not re.search(pattern, surface, re.I), (pattern, surface)


def test_the_card_starts_where_the_planner_starts_in_every_part_of_the_season() -> None:
    """Before Week 1 the list is the whole season; after the last bye it says
    no team has one (byes.js's own words); a span of one week is named once."""
    early = og.byes_card_facts(_payload("2026-08-20T12:00:00+00:00"))
    assert early["from"] == 1 and [r["week"] for r in early["rows"]] == [5, 6, 7, 8, 9, 10,
                                                                         11, 13, 14]
    assert "No byes in Weeks 1–4, 12 and 15–17." in _visible(og.byes_card_html(early))
    late = og.byes_card_facts(_payload("2026-12-16T12:00:00+00:00"))
    assert late["from"] == 15 and late["rows"] == []
    assert "No NFL team has a bye from Week 15 through Week 17." in _visible(
        og.byes_card_html(late))
    last = og.byes_card_facts(_payload("2026-12-30T12:00:00+00:00"))
    assert last["from"] == 17
    seen = _visible(og.byes_card_html(last))
    assert "No NFL team has a bye in Week 17." in seen and "Week 17 to" not in seen
    assert og.byes_card_name(facts=late) == "byes-2026-w15.png"
    assert og.byes_card_url(late) == "https://beatyourleague.com/og/byes-2026-w15.png"


def test_the_alt_text_says_what_the_card_says() -> None:
    facts = og.byes_card_facts(_payload())
    assert og.byes_card_alt(facts) == (
        "Free bye week planner: your fantasy roster, through Week 17. 2026 NFL byes, "
        "Week 9 to Week 17. Week 9: PIT and TEN. Week 10: CHI, DEN, PHI and TB. "
        "Week 11: ATL, CLE, GB, LAR, NE and SEA. Week 13: BAL, IND, LV and NYJ. "
        "Week 14: ARI and DAL. No byes in Weeks 12 and 15–17.")


@pytest.mark.parametrize("case", ["partial", "over", "week-18", "bad-code", "code-newline",
                                  "bad-season", "season-newline", "no-stamp", "not-a-row"])
def test_a_card_that_would_be_wrong_is_never_drawn(case) -> None:
    """Fails closed, as the planner's data does (render/bye_index.validate):
    a bye list missing a team, a season whose planned weeks are all played, a
    team code or season that is not one, or a file with no build stamp (no
    week being played can be read from it) refuses. A wrong bye is worse than
    none."""
    payload = _payload()
    if case == "partial":
        payload = _payload(byes={t: w for t, w in BYES_2026.items() if t != "DAL"})
    elif case == "over":
        payload = _payload("2027-02-01T12:00:00+00:00")
    elif case == "week-18":
        payload = _payload("2027-01-06T12:00:00+00:00")
    elif case == "bad-code":
        payload["weeks"][9]["bye"] = ["CHI", "<b>x</b>", "DEN", "PHI", "TB"]
    elif case == "code-newline":           # "$" alone accepts a trailing newline
        payload["weeks"][9]["bye"] = ["CHI", "DEN", "PHI", "TB\n"]
    elif case == "bad-season":
        payload["season"] = "next year"
    elif case == "season-newline":
        payload["season"] = "2026\n"
    elif case == "no-stamp":
        payload["generated"] = None
    elif case == "not-a-row":
        payload["weeks"][0] = "week 1"
    with pytest.raises(og.OgError):
        og.byes_card_facts(payload)


# --------------------------------------------------------------------- #
# the planner page's preview tags
# --------------------------------------------------------------------- #

def test_the_page_tags_point_at_the_card_and_point_again_the_same_way() -> None:
    """og:image, og:image:alt and a twitter:image beside them, once each, and
    the size and card-type tags left as they are. Idempotent, and a later
    week's card replaces the earlier one in place."""
    page = PLANNER.read_text(encoding="utf-8")
    facts = og.byes_card_facts(_payload())
    pointed = og.with_byes_card(page, facts)
    url = og.byes_card_url(facts)
    assert f'<meta property="og:image" content="{url}">' in pointed
    assert f'<meta name="twitter:image" content="{url}">' in pointed
    alt = html.escape(og.byes_card_alt(facts), quote=True)
    assert f'<meta property="og:image:alt" content="{alt}">' in pointed
    for tag in ('property="og:image"', 'name="twitter:image"', 'property="og:image:alt"',
                'property="og:image:width" content="1200"',
                'property="og:image:height" content="630"',
                'name="twitter:card" content="summary_large_image"'):
        assert pointed.count(tag) == 1, tag
    assert og.with_byes_card(pointed, facts) == pointed, "not idempotent"
    later = og.byes_card_facts(_payload("2026-11-12T06:57:25+00:00"))
    moved = og.with_byes_card(pointed, later)
    assert "byes-2026-w10.png" in moved and "byes-2026-w09.png" not in moved
    assert moved.count('name="twitter:image"') == 1
    # Only the head's preview tags move.
    strip = lambda p: re.sub(r'<meta (?:property|name)="(?:og|twitter):image(?::alt)?"[^>]*>\n?',  # noqa: E731
                             "", p)
    assert strip(moved) == strip(page)


def test_the_planner_page_previews_as_the_planner_not_the_lineup_card() -> None:
    """The committed page points at its own card, which exists, is 1200x630,
    fits the ceiling every image here has, and carries the fingerprint of
    what it was drawn from. And the lineup card's alt ("three with a
    percentage") is gone from the page."""
    from render.report import OG_IMAGE
    page = PLANNER.read_text(encoding="utf-8")
    found = re.search(r'<meta property="og:image" content="https://beatyourleague\.com/og/'
                      r'(byes-(\d{4})-w(\d{2})\.png)">', page)
    assert found, "the planner page does not point at its own card"
    card = SITE / "og" / found.group(1)
    assert card.is_file(), f"{found.group(1)} is missing — run `make og-byes`"
    data = card.read_bytes()
    assert struct.unpack(">II", data[16:24]) == (og.WIDTH, og.HEIGHT) == (1200, 630)
    assert len(data) <= og.MAX_BYTES and og.source_digest(data)
    assert f'<meta name="twitter:image" content="https://beatyourleague.com/og/{found.group(1)}">' \
        in page
    assert OG_IMAGE not in page and "with a percentage" not in page
    alt = re.search(r'<meta property="og:image:alt" content="([^"]*)"', page).group(1)
    assert alt.startswith("Free bye week planner: your fantasy roster, through Week ")
    assert f"{found.group(2)} NFL byes, Week {int(found.group(3))}" in html.unescape(alt)
    # Only one planner card stands.
    assert [p.name for p in (SITE / "og").glob("byes-*.png")] == [found.group(1)]


def test_the_committed_card_is_the_one_the_committed_byes_file_draws() -> None:
    """When the card's week is the week site/join/byes.json reads, the card
    must be the one this code draws from it, fingerprint for fingerprint: a
    change to the card's words or layout without a redraw fails here, as
    og.png's does. (A byes file a week newer than its card means the weekly
    share-card job could not draw that week; the card it left is still true,
    since it names its own weeks, and the next run redraws it.)"""
    payload = json.loads((SITE / "join" / "byes.json").read_text(encoding="utf-8"))
    try:
        facts = og.byes_card_facts(payload)
    except og.OgError as exc:
        pytest.skip(f"byes.json draws no card today ({exc})")
    page = PLANNER.read_text(encoding="utf-8")
    if og.byes_card_url(facts) not in page:
        pytest.skip("byes.json is newer than the planner's card; the weekly run redraws it")
    card = SITE / "og" / og.byes_card_name(facts)
    assert og.source_digest(card.read_bytes()) == og.card_digest(og.byes_card_html(facts)), (
        "the planner's card was drawn from older words or data. Run `make og-byes`.")


# --------------------------------------------------------------------- #
# drawing it
# --------------------------------------------------------------------- #

def _site(tmp_path: Path, generated: str = "2026-11-05T06:57:25+00:00") -> Path:
    site = tmp_path / "site"
    (site / "join").mkdir(parents=True)
    (site / "byes").mkdir()
    (site / "og").mkdir()
    (site / "join" / "byes.json").write_text(json.dumps(_payload(generated)), encoding="utf-8")
    (site / "byes" / "index.html").write_text(PLANNER.read_text(encoding="utf-8"),
                                              encoding="utf-8")
    (site / "og" / "this-week-2026-w09.png").write_bytes(b"week card")
    return site


def test_a_card_that_cannot_be_drawn_leaves_the_last_one_standing(tmp_path) -> None:
    """Never back to og.png, the lineup card with odds this exists to replace:
    a refusal (nothing left to plan) or a failed render (no browser) keeps the
    page and its card exactly as they were. That card is still true, since it
    names its own weeks. This week's lineup card is never touched."""
    site = _site(tmp_path, "2027-02-01T12:00:00+00:00")
    (site / "og" / "byes-2026-w17.png").write_bytes(b"last card")
    page = og.with_byes_card((site / "byes" / "index.html").read_text(encoding="utf-8"),
                             og.byes_card_facts(_payload("2026-12-30T12:00:00+00:00")))
    (site / "byes" / "index.html").write_text(page, encoding="utf-8")
    assert og.build_byes_card(site)[0] == "refused"
    assert (site / "byes" / "index.html").read_text(encoding="utf-8") == page
    assert (site / "og" / "byes-2026-w17.png").read_bytes() == b"last card"
    # A render that fails: the browser is not there.
    (site / "join" / "byes.json").write_text(json.dumps(_payload()), encoding="utf-8")
    outcome, _detail = og.build_byes_card(site, chrome=str(tmp_path / "no-chrome"))
    assert outcome == "skipped"
    assert (site / "byes" / "index.html").read_text(encoding="utf-8") == page
    assert sorted(p.name for p in (site / "og").iterdir()) == ["byes-2026-w17.png",
                                                              "this-week-2026-w09.png"]
    (site / "join" / "byes.json").write_text("{not json", encoding="utf-8")
    assert og.build_byes_card(site)[0] == "refused"


def test_the_card_renders_at_the_size_every_platform_crops_to(tmp_path) -> None:
    """With Chrome present: a 1200x630 PNG under the ceiling, stamped with its
    source, the page pointed at it and last week's planner card deleted; a
    second run draws nothing new; this week's lineup card is left alone."""
    try:
        og.find_chrome()
    except og.OgError:
        pytest.skip("no Chrome to render with")
    site = _site(tmp_path)
    (site / "og" / "byes-2026-w08.png").write_bytes(b"last week")
    assert og.build_byes_card(site)[0] == "written"
    card = site / "og" / "byes-2026-w09.png"
    data = card.read_bytes()
    assert struct.unpack(">II", data[16:24]) == (1200, 630) and len(data) <= og.MAX_BYTES
    facts = og.byes_card_facts(_payload())
    assert og.source_digest(data) == og.card_digest(og.byes_card_html(facts))
    assert og.byes_card_url(facts) in (site / "byes" / "index.html").read_text(encoding="utf-8")
    assert sorted(p.name for p in (site / "og").iterdir()) == ["byes-2026-w09.png",
                                                              "this-week-2026-w09.png"]
    assert og.build_byes_card(site)[0] == "current"


def test_the_main_entry_never_fails_the_run(tmp_path, capsys) -> None:
    """Like --week: a card that is not drawn is a notice, exit 0."""
    site = _site(tmp_path, "2027-02-01T12:00:00+00:00")
    assert og.main(["--byes", "--site", str(site)]) == 0
    assert "::notice::" in capsys.readouterr().out


# --------------------------------------------------------------------- #
# where it is built
# --------------------------------------------------------------------- #

def test_the_weekly_share_card_job_draws_and_hands_over_the_planner_card() -> None:
    """Beside this week's card, in the same secretless job, after the week's
    record (byes.json included) is pushed; handed to commit-card with the
    planner page, whose preview tags it moves; and commit-card accepts the
    planner card's name and nothing looser."""
    yaml = pytest.importorskip("yaml")
    jobs = yaml.safe_load((REPO / ".github" / "workflows" / "weekly.yml")
                          .read_text(encoding="utf-8"))["jobs"]
    job, commit = jobs["share-card"], jobs["commit-card"]
    runs = [str(s.get("run", "")) for s in job["steps"]]
    week = runs.index(".venv/bin/python -m render.og --week")
    assert runs.index(".venv/bin/python -m render.og --byes") == week + 1
    hand_off = next(s for s in job["steps"] if s.get("id") == "handoff")
    assert "site/byes/index.html" in hand_off["env"]["RECORD_PATHS"].split()
    check = next(s for s in commit["steps"] if str(s.get("name", "")).startswith("Check the record"))
    allowed = check["env"]["RECORD_ALLOWED"].split()
    assert "/site/og/byes-[0-9][0-9][0-9][0-9]-w[0-9][0-9].png" in allowed
    assert "/site/byes/index.html" in allowed
    assert not any(p.endswith("/*") or p == "/site/og/*.png" for p in allowed)


def test_make_has_a_target_for_it() -> None:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "\nog-byes:\n\t$(PY) -m render.og --byes\n" in makefile
