"""The growth pass (Oct 24 2026): the recorded closest call on the season
clock, the weekly share card, the bye drafts, the commissioner kit, the
league-app help pages and the planner offer on the samples.

Every item here repeats a number the product already put on the record, or
states a schedule fact, or sells nothing at all. These tests hold each to
that: the clock's closest call is the ledger's, the share card repeats the
page or is not drawn, a bye draft carries no number to grade, and a help page
says only what the paste reader and the join page already do.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

import render.live_sample as live
from render import og, platforms
from render.report import OG_IMAGE, SOCIAL_IMAGE_TAGS, _pct, regret_verdict
from run import drops
# The live sample's own fixture week and runner (offline, test_solo_run).
from test_live_sample import _ledger, _run, week  # noqa: F401  (week is a fixture)

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
CACHE = REPO / "data" / "raw" / "nflverse"

# The example from the Oct 20 2026 Week 7 build (the lead's spec, C9).
WEEK7 = {"season": "2026", "week": 7, "slot": "FLEX", "start": "Rome Odunze",
         "over": "Rashid Shaheed", "start_id": "00-0039919", "over_id": "00-0037545",
         "start_short": "Odunze", "over_short": "Shaheed", "pct": 61,
         "proj": "10.3 vs 8.0", "start_proj": "10.3", "over_proj": "8.0",
         "label": "Closest call with odds", "tossup": False,
         "kickoff": "2026-10-23T00:15:00Z", "recorded": True}


def _visible(page: str) -> str:
    text = re.sub(r"<head>.*?</head>|<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->",
                  " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


# --------------------------------------------------------------------- #
# G1 — the season clock carries the recorded closest call (C9)
# --------------------------------------------------------------------- #

def test_a_recorded_first_build_puts_the_ledgers_closest_call_on_the_clock(
        tmp_path, monkeypatch, week) -> None:  # noqa: F811
    """(a) A recorded build before kickoff writes ``closest`` with exactly the
    contract's keys, recorded at both levels, its % the ledger's printed
    integer and its names the report's own; (c) the page it published prints
    that same verdict, % and projection on its closest-call card — which is
    exactly what the share card checks before it draws."""
    code, out, processed = _run(tmp_path, monkeypatch, kicked_off=False)
    clock = json.loads(out.with_name("week.json").read_text())
    closest = clock["closest"]
    assert code == 0 and tuple(closest) == live.CLOSEST_KEYS
    assert clock["recorded"] is True and closest["recorded"] is True
    assert (closest["season"], closest["week"]) == (str(clock["season"]), clock["week"])
    regret = week()["regret"]
    assert (closest["start"], closest["over"]) == (regret["start_name"], regret["over_name"])
    [held] = [r for r in _ledger(processed) if r["is_regret"]]
    assert closest["pct"] == _pct(held["confidence"]) and isinstance(closest["pct"], int)
    assert (closest["start_id"], closest["over_id"], closest["slot"]) == (
        held["pick_id"], held["over_id"], held["slot"])
    page = out.read_text(encoding="utf-8")
    # Card 02's % (contract C3: <b class="cpct">, was <div class="num">).
    assert f'<b class="cpct">{closest["pct"]}%</b>' in page
    before, joiner, after = regret_verdict(regret)
    assert f'{live.esc(before)} <span class="over">{joiner}</span> {live.esc(after)}' in page
    assert closest["tossup"] is (joiner == "or")
    if closest["proj"]:
        assert f'proj <b>{closest["proj"]}</b>' in page
        assert closest["proj"] == f'{closest["start_proj"]} vs {closest["over_proj"]}'
    # The share card draws exactly this — or, on a toss-up, where the page
    # says "either is fine", refuses.
    problems = og.week_card_problems(clock, page)
    assert (problems == []) is (not closest["tossup"]), problems
    if closest["tossup"]:
        # The same page with the card's "Start X over Y" verdict passes once
        # the clock says it is not a toss-up: the % and projection match.
        page = page.replace(f'{live.esc(before)} <span class="over">or</span> {live.esc(after)}',
                            f'Start {live.esc(closest["start"])} <span class="over">over</span> '
                            f'{live.esc(closest["over"])}')
    assert og.week_card_problems({**clock, "closest": {**closest, "tossup": False}}, page) == []
    assert live.closest_problems(clock, processed) == []


def test_no_closest_call_reaches_the_clock_unless_it_is_on_the_record(
        tmp_path, monkeypatch, week) -> None:  # noqa: F811
    """(b) Absent when nothing was recorded (--no-record), after kickoff (a
    forced rebuild), when the regret is gated, when the ledger lacks the call
    and when it holds another value. Absent means the landing's strip and the
    share card show nothing."""
    code, out, _ = _run(tmp_path, monkeypatch, kicked_off=False, extra=("--no-record",))
    assert code == 0 and "closest" not in json.loads(out.with_name("week.json").read_text())
    code, out, _ = _run(tmp_path / "k", monkeypatch, kicked_off=True, extra=("--force",))
    assert code == 0 and "closest" not in json.loads(out.with_name("week.json").read_text())

    report = week()
    processed = tmp_path / "ledger-empty"
    assert live.closest_for_clock(live.recorded_only(copy.deepcopy(report), processed),
                                  {}, {}) is None, "a call the ledger lacks"
    live.record(report, processed)
    moved = copy.deepcopy(report)
    moved["regret"]["confidence"] = round(moved["regret"]["confidence"] + 0.02, 3)
    for slot in moved["lineup"]:
        if (slot.get("player_id"), slot.get("alternative_id")) == (
                moved["regret"]["start_id"], moved["regret"]["over_id"]):
            slot["confidence"] = moved["regret"]["confidence"]
    assert live.closest_for_clock(live.recorded_only(moved, processed), {}, {}) is None, \
        "a value the ledger does not hold"
    assert live.closest_for_clock({"meta": report["meta"], "regret": {"gate": "x"}},
                                  {}, {}) is None, "a gated regret"
    # The writer's own guard, whatever it is handed.
    path = tmp_path / "w.json"
    for kwargs in ({"recorded": False}, {"recorded": True, "after_kickoff": True}):
        live.write_week_json(report, path, closest=dict(WEEK7), **kwargs)
        assert "closest" not in json.loads(path.read_text()), kwargs
    live.write_week_json(report, path, recorded=True, closest=dict(WEEK7), byes_left=False)
    assert json.loads(path.read_text())["closest"] == WEEK7
    assert json.loads(path.read_text())["byes_left"] is False


def test_the_clocks_kickoff_is_the_earlier_of_the_two_games_or_nothing() -> None:
    """The earlier of the two players' kickoffs, as the clock's other stamps
    are written; null unless BOTH are known (a missing team cannot be said to
    play later)."""
    report = {"meta": {"season": "2026", "week": 7},
              "regret": {"slot": "FLEX", "start_id": "a", "start_name": "Rome Odunze",
                         "over_id": "b", "over_name": "Rashid Shaheed", "confidence": 0.61,
                         "label": "Closest call with odds",
                         "drivers": [{"label": "proj", "value": "10.3 vs 8.0"}]}}
    starts = {"CHI": datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc),
              "SEA": datetime(2026, 10, 23, 0, 15, tzinfo=timezone.utc)}
    got = live.closest_for_clock(report, {"a": "CHI", "b": "SEA"}, starts)
    assert got["kickoff"] == "2026-10-23T00:15:00Z"
    assert {k: v for k, v in got.items() if k not in ("start_id", "over_id")} == {
        k: v for k, v in WEEK7.items() if k not in ("start_id", "over_id")}
    assert live.closest_for_clock(report, {"a": "CHI"}, starts)["kickoff"] is None


def test_the_clocks_short_names_are_the_drafts_short_names(week) -> None:  # noqa: F811
    """(d) One rule shortens a pair: the clock's start_short/over_short are
    exactly what run/drops.py asks the question with."""
    report = week()
    closest = live.closest_for_clock(report, {}, {})
    assert (closest["start_short"], closest["over_short"]) == drops.short_names(
        closest["start"], closest["over"])
    post = drops._call_post(report)
    if post:
        assert post.startswith(f"Start {closest['start_short']} or {closest['over_short']}")
    assert drops.short_names("Amon-Ra St. Brown", "Equanimeous St. Brown") == (
        "Amon-Ra St. Brown", "Equanimeous St. Brown")


def test_byes_left_reads_the_cached_schedule() -> None:
    """(e) On the 2026 schedule the last byes are in Week 14: some remain
    from Week 7, and from Week 14 itself — its Tuesday build is days before
    ARI and DAL sit out that Sunday (T3: it said none, and hid the planner a
    week early) — none from Week 15. Unreadable means unknown (None), never
    "none left"."""
    if not (CACHE / "games.csv").is_file():
        pytest.skip("nflverse schedule not cached")
    assert live.byes_left_from(CACHE, "2026", 7) is True
    assert {w: live.byes_left_from(CACHE, "2026", w) for w in (12, 13, 14, 15)} == {
        12: True, 13: True, 14: True, 15: False}
    assert live.byes_left_from(Path("/nonexistent"), "2026", 7) is None


def test_the_launch_check_finds_a_closest_call_that_is_not_on_the_record(
        tmp_path, week) -> None:  # noqa: F811
    """render.live_sample.closest_problems — what the launch check's "This
    week's closest call is on the record" gate reports: a clock whose week is
    not marked recorded, a call the typed-ppr-12 store does not hold, or one
    it holds at another printed %."""
    report = week()
    processed = tmp_path / "processed"
    live.record(report, processed)
    closest = live.closest_for_clock(live.recorded_only(copy.deepcopy(report), processed),
                                     {}, {})
    clock = {"season": closest["season"], "week": closest["week"], "recorded": True,
             "closest": closest}
    assert live.closest_problems(clock, processed) == []
    assert live.closest_problems({**clock, "recorded": False}, processed)
    assert live.closest_problems({**clock, "closest": {**closest, "pct": closest["pct"] + 3}},
                                 processed)
    assert live.closest_problems({**clock, "closest": {**closest, "over_id": "00-9"}},
                                 processed)
    # C6-2: the landing quotes the names, so the right ids under the wrong
    # names are not on the record either.
    for wrong in ({"start": "Ja'Marr Chase"}, {"over": "Tee Higgins"}):
        found = live.closest_problems({**clock, "closest": {**closest, **wrong}}, processed)
        assert found and "records that call as" in found[0], (wrong, found)
    assert live.closest_problems({k: v for k, v in clock.items() if k != "closest"},
                                 processed) == []


def test_a_reader_takes_only_a_well_formed_clock_call() -> None:
    """Missing or malformed is absent; so is a call naming another week, or
    one not recorded at both levels — the landing's strip and the card read
    through this same rule."""
    clock = {"season": "2026", "week": 7, "recorded": True, "closest": dict(WEEK7)}
    assert live.closest_from_clock(clock) == WEEK7
    for broken in ({**clock, "recorded": None}, {**clock, "week": 8},
                   {**clock, "closest": {**WEEK7, "recorded": False}},
                   {**clock, "closest": {k: v for k, v in WEEK7.items() if k != "label"}},
                   {**clock, "closest": "Odunze 61%"}, {k: v for k, v in clock.items()
                                                       if k != "closest"}):
        assert live.closest_from_clock(broken) is None, broken


# --------------------------------------------------------------------- #
# G2 — the weekly share card repeats the page or is not drawn
# --------------------------------------------------------------------- #

def _site_copy(tmp_path: Path, closest: dict | None = WEEK7, page_edit=None) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    page = (SITE / "this-week.html").read_text(encoding="utf-8")
    if page_edit:
        page = page_edit(page)
    (site / "this-week.html").write_text(page, encoding="utf-8")
    clock = {"season": "2026", "week": 7, "recorded": True, "phase": "season",
             "built_at": "2026-10-20T17:15:45+00:00"}
    if closest is not None:
        clock["closest"] = dict(closest)
    (site / "week.json").write_text(json.dumps(clock), encoding="utf-8")
    return site


def _published_has_week7_card() -> bool:
    page = (SITE / "this-week.html").read_text(encoding="utf-8")
    return 'Start Rome Odunze <span class="over">over</span> Rashid Shaheed' in page \
        and '<div class="num">61%</div>' in page and "proj <b>10.3 vs 8.0</b>" in page


def test_the_card_escapes_the_names_it_draws() -> None:
    """Names come from the schedule's directory — third-party text — and
    reach the card's markup escaped, never as markup."""
    card = og.week_card_html({**WEEK7, "start": "A<script>x()</script>", "over": "O'Neil & Co"},
                             {"built_at": "2026-10-20T17:15:45+00:00"})
    assert "<script>x()" not in card and "&lt;script&gt;" in card
    assert "O&#x27;Neil &amp; Co" in card
    assert "This week&#x27;s report · Week 7 of 2026" in card and "61%" in card
    assert "proj <b>10.3 vs 8.0</b>" in card and "built Tue, Oct 20" in card
    assert "proj" not in og.week_card_html({**WEEK7, "proj": None}, {}).split("<body>")[1]


def test_the_card_refuses_whatever_the_page_does_not_print(tmp_path) -> None:
    """A figure the page's closest-call card does not print, a toss-up (the
    page says "either is fine"), or a call not recorded at both levels: no
    card. The page then keeps the site's own card."""
    if not _published_has_week7_card():
        pytest.skip("site/this-week.html no longer shows the Week 7 call these cases edit")
    page = (SITE / "this-week.html").read_text(encoding="utf-8")
    clock = {"season": "2026", "week": 7, "recorded": True, "closest": dict(WEEK7)}
    assert og.week_card_problems(clock, page) == []
    for bad in ({**WEEK7, "pct": 62}, {**WEEK7, "proj": "10.3 vs 8.1"},
                {**WEEK7, "over": "Zay Flowers"}, {**WEEK7, "tossup": True},
                {**WEEK7, "recorded": False}):
        assert og.week_card_problems({**clock, "closest": bad}, page), bad
    assert og.week_card_problems({**clock, "recorded": False}, page)
    assert og.week_card_problems({k: v for k, v in clock.items() if k != "closest"}, page)
    # Refused: the page is put back on the site's own card, nothing drawn.
    site = _site_copy(tmp_path, {**WEEK7, "tossup": True})
    (site / "og").mkdir()
    (site / "og" / "this-week-2026-w06.png").write_bytes(b"old")
    assert og.build_week_card(site)[0] == "refused"
    assert not list((site / "og").glob("*.png")), "an older week's card was left standing"
    assert f'<meta property="og:image" content="{OG_IMAGE}">' in (site / "this-week.html").read_text()


def test_the_card_alt_says_what_the_card_says() -> None:
    assert og.week_card_alt(WEEK7) == ("Week 7's closest call with odds, for a sample "
                                       "roster: Start Rome Odunze over Rashid Shaheed, 61%.")
    assert og.week_card_name(WEEK7) == "this-week-2026-w07.png"
    assert og.week_card_url(WEEK7) == "https://beatyourleague.com/og/this-week-2026-w07.png"


def test_the_page_tags_point_at_the_card_and_come_back_exactly() -> None:
    """with_week_card points og:image, og:image:alt and a twitter:image at the
    week's card; with no card it restores render.report.SOCIAL_IMAGE_TAGS
    word for word, so tests/test_og.py's "every page carries the card" holds
    again the week the card stands down."""
    page = (SITE / "this-week.html").read_text(encoding="utf-8")
    page = og.with_week_card(page, None)          # whatever it holds today
    assert SOCIAL_IMAGE_TAGS in page
    pointed = og.with_week_card(page, WEEK7)
    url = og.week_card_url(WEEK7)
    assert f'<meta property="og:image" content="{url}">' in pointed
    assert f'<meta name="twitter:image" content="{url}">' in pointed
    assert "Week 7&#x27;s closest call with odds" in pointed
    assert pointed.count('property="og:image"') == 1
    assert og.with_week_card(pointed, WEEK7) == pointed, "not idempotent"
    assert og.with_week_card(pointed, None) == page


def test_the_card_renders_at_the_size_every_platform_crops_to(tmp_path) -> None:
    """With Chrome present: a 1200x630 PNG under the 1 MB ceiling, stamped
    with its source, the page pointed at it; a second run draws nothing new;
    a week with no recorded call deletes it and restores og.png."""
    try:
        og.find_chrome()
    except og.OgError:
        pytest.skip("no Chrome to render with")
    if not _published_has_week7_card():
        pytest.skip("site/this-week.html no longer shows the Week 7 call")
    site = _site_copy(tmp_path)
    assert og.build_week_card(site)[0] == "written"
    card = site / "og" / "this-week-2026-w07.png"
    data = card.read_bytes()
    assert struct.unpack(">II", data[16:24]) == (1200, 630) and len(data) < og.MAX_BYTES
    assert og.source_digest(data) == og.week_digest(og.week_card_html(
        WEEK7, json.loads((site / "week.json").read_text())))
    assert og.week_card_url(WEEK7) in (site / "this-week.html").read_text()
    assert og.build_week_card(site)[0] == "current"
    (site / "week.json").write_text(json.dumps({"season": "2026", "week": 8}))
    assert og.build_week_card(site)[0] == "refused" and not card.exists()
    assert SOCIAL_IMAGE_TAGS in (site / "this-week.html").read_text()


def test_the_share_card_job_holds_no_secret_and_commits_only_the_card() -> None:
    """The card job runs a browser on a page built from third-party data, so
    it is its own job: after the week job, never cancelled with it, no
    secrets and no sealed registry anywhere in it, contents:write only, and
    its commit adds the card folder and the page — nothing else."""
    yaml = pytest.importorskip("yaml")
    text = (REPO / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
    job = yaml.safe_load(text)["jobs"]["share-card"]
    raw = text.split("\n  share-card:", 1)[1]
    assert "secrets." not in raw and "statebox" not in raw and "data/sealed" not in raw
    assert job["needs"] == "week" and job["if"] == "always() && needs.week.result != 'cancelled'"
    assert job["permissions"] == {"contents": "write"}
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert ".venv/bin/python -m render.og --week" in runs
    adds = [line.strip() for line in re.findall(r"^\s*git add .*$", runs, re.M)]
    assert adds == ["git add -A site/og site/this-week.html"]
    checkout = job["steps"][0]
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["ref"] == "${{ github.ref_name }}"


# --------------------------------------------------------------------- #
# G3 — the bye drafts: schedule facts, no number to grade
# --------------------------------------------------------------------- #

BYES_2026 = {"CAR": 5, "KC": 5, "CIN": 6, "DET": 6, "MIA": 6, "MIN": 6, "BUF": 7, "JAX": 7,
             "LAC": 7, "WAS": 7, "HOU": 8, "NO": 8, "NYG": 8, "SF": 8, "PIT": 9, "TEN": 9,
             "CHI": 10, "DEN": 10, "PHI": 10, "TB": 10, "ATL": 11, "CLE": 11, "GB": 11,
             "LA": 11, "NE": 11, "SEA": 11, "BAL": 13, "IND": 13, "LV": 13, "NYJ": 13,
             "ARI": 14, "DAL": 14}
NO_NUMBERS = ("%", "odds", "project")


def _bye_report(**over) -> dict:
    report = {"meta": {"week": 7, "season": "2026", "box_scores_as_of": "Box scores through Week 6."},
              "byes_ahead": [{"week": 9, "slots": ["K"], "players": ["Chris Boswell", "Tyjae Spears"],
                              "short": ["Chris Boswell"], "out": []}]}
    report.update(over)
    return report


def test_the_byes_left_draft_lists_every_team_still_to_have_one() -> None:
    """Each team with a bye this week or later, once, by week, the Rams as
    the apps spell them (LAR, never a bare LA); the playoff sentence only
    when no team is off in Weeks 15-17, and the first thing to go when the
    post would not fit. The week's own teams are listed (C7-1: drafted for
    the week's Wednesday, Week 8's post left HOU, NO, NYG and SF off, as if
    their bye of Nov 1 were already behind them)."""
    text = drops._byes_left_post(BYES_2026, 8)
    assert text == ("NFL byes left this season. Week 8: HOU, NO, NYG, SF · Week 9: PIT, TEN · "
                    "Week 10: CHI, DEN, PHI, TB · Week 11: ATL, CLE, GB, LAR, NE, SEA · "
                    "Week 13: BAL, IND, LV, NYJ · Week 14: ARI, DAL. No byes in Weeks 15–17, "
                    "the fantasy playoffs under ESPN's, Yahoo's and Sleeper's defaults.")
    assert len(text) <= drops.LIMIT
    listed = re.findall(r"\b[A-Z]{2,3}\b", text.split(". No byes")[0])
    teams = [t for t in listed if t not in ("NFL",)]
    assert sorted(teams) == sorted(drops._app_code(t) for t, w in BYES_2026.items() if w >= 8)
    assert len(teams) == len(set(teams)) and not re.search(r"\bLA\b", text)
    seven = drops._byes_left_post(BYES_2026, 7)
    assert seven.startswith("NFL byes left this season. Week 7: BUF, JAX, LAC, WAS · Week 8: ")
    assert seven.endswith("Week 14: ARI, DAL.") and len(seven) <= drops.LIMIT
    playoff = {**BYES_2026, "DAL": 16}
    assert "No byes in Weeks 15" not in drops._byes_left_post(playoff, 8)
    assert drops._byes_left_post(BYES_2026, 14) == "NFL byes left this season. Week 14: ARI, DAL." \
        " No byes in Weeks 15–17, the fantasy playoffs under ESPN's, Yahoo's and Sleeper's defaults."
    assert drops._byes_left_post(BYES_2026, 15) is None
    assert drops._byes_left_post(None, 7) is None
    # Over the limit: the sentence goes first, then the post.
    crowded = {f"T{i:02d}": 8 + i % 6 for i in range(40)}
    text = drops._byes_left_post(crowded, 7)
    assert text is None or ("No byes in" not in text and len(text) <= drops.LIMIT)


def test_the_bye_check_names_only_the_players_who_leave_the_spot_empty() -> None:
    """The report's own byes_ahead: the first week through 17, naming only the
    hit's short players (the kicker, not every idle back); "every bye
    covered" only when the report's check demonstrably ran."""
    assert drops._bye_check_post(_bye_report()) == (
        "Bye check for the playoff push: our sample roster's report flags Week 9, when "
        "Chris Boswell is on bye and nobody else on the roster can kick.")
    two = _bye_report(byes_ahead=[{"week": 12, "slots": ["QB", "TE"],
                                   "players": ["Brock Purdy", "George Kittle", "Christian McCaffrey"],
                                   "short": ["Brock Purdy", "George Kittle"]}])
    text = drops._bye_check_post(two)
    assert text.endswith("when Brock Purdy and George Kittle are on bye and nobody else on "
                         "the roster can start at QB and TE.")
    assert "McCaffrey" not in text
    late = _bye_report(byes_ahead=[{"week": 18, "slots": ["K"], "short": ["X"], "players": ["X"]}])
    covered = ("Bye check for the playoff push: our sample roster's report finds every bye "
               "from Week 8 through 17 covered.")
    assert drops._bye_check_post(late, BYES_2026) == covered
    assert drops._bye_check_post(_bye_report(byes_ahead=[]), BYES_2026) == covered
    assert drops._bye_check_post(_bye_report(byes_ahead=[])) is None, "no schedule, no claim"
    stale = _bye_report(byes_ahead=[], meta={"week": 7, "season": "2026"})
    assert drops._bye_check_post(stale, BYES_2026) is None, "not a live week"


def test_neither_bye_draft_carries_a_number_to_grade() -> None:
    posts = drops.bye_drafts(_bye_report(), BYES_2026)
    assert [p["name"] for p in posts] == ["NFL byes left", "Bye check"]
    for post in posts:
        low = post["text"].lower()
        assert len(post["text"]) <= drops.LIMIT
        assert not any(w in low for w in NO_NUMBERS + drops.BANNED), post
        assert "http" not in post["text"], "the link goes in the first reply"
        assert post["reply"].startswith("Check your own roster's byes through Week 17, free, no login: ")
    assert posts[0]["when"] == "Wednesday" and posts[0]["card"] == "Every 2026 NFL bye week"
    assert posts[1]["card"] == "Your Game Plan" and "when" not in posts[1]


def test_the_bye_check_reply_opens_the_planner_on_the_sample_roster() -> None:
    """Contract C7: the planner is /byes/. Draft B's link carries the sample
    roster as the same v4 roster code a signup carries."""
    from run.refs import decode_roster
    [table, check] = drops.bye_drafts(_bye_report(), BYES_2026)
    assert table["reply"].endswith(" https://beatyourleague.com/byes/")
    url = check["reply"].rsplit(" ", 1)[1]
    assert url.startswith("https://beatyourleague.com/byes/?ref=")
    roster = decode_roster(url.split("?ref=", 1)[1])
    assert tuple(roster.player_ids) == live.LIVE_ROSTER
    assert roster.league_size == 12 and roster.scoring == "ppr"


def test_the_bye_drafts_sit_after_the_reports_own_posts() -> None:
    """After the call, the if/then and the rising roles; before the facts-only
    fallback and the Thursday post. Every this-week link names its week, so
    X fetches that week's card."""
    posts = [{"name": n, "text": n} for n in ("The closest call", "Rising roles", "Thursday night")]
    names = [p["name"] for p in drops.with_bye_drafts(posts, _bye_report(), BYES_2026)]
    assert names == ["The closest call", "Rising roles", "NFL byes left", "Bye check",
                     "Thursday night"]
    names = [p["name"] for p in drops.with_bye_drafts([{"name": "Workloads", "text": "w"}],
                                                      _bye_report(), BYES_2026)]
    assert names == ["NFL byes left", "Bye check", "Workloads"]
    report = {"meta": {"week": 7, "season": "2026"}, "regret": {}, "pivots": [],
              "rising": [{"name": "A B", "team": "SEA", "position": "RB", "recent": 9.0,
                          "earlier": 2.0}]}
    [rising] = drops.drafts(report)
    assert rising["reply"].endswith("https://beatyourleague.com/this-week.html?w=7")


def test_the_drafts_file_says_where_the_planner_card_is(tmp_path) -> None:
    text = drops.render(_bye_report(), drops.bye_drafts(_bye_report(), BYES_2026))
    assert ('Attach: a screenshot of the "Every 2026 NFL bye week" card, from the bye-week '
            'planner (https://beatyourleague.com/byes/).') in text
    assert "Post it: Wednesday." in text


# --------------------------------------------------------------------- #
# G4 — the commissioner kit (markup for site/league-pass.html, pasted by the
# pages builder) and the League Pass line in the one launch email
# --------------------------------------------------------------------- #

# The canonical kit: integrator_notes carries these verbatim. It goes after
# the "Ask the league first" block, before "What you do after paying".
KIT_MARKUP = """  <!-- The commissioner kit (G4): two things a commissioner can send the group
       chat today, whether or not checkout is open. Neither needs an email or a login, neither names a price
       (and the lead names no count: from Week 14 the bye line hides and one is left), and
       ?via=league-chat lets `make stats` count what the kit brought. The bye
       line hides once week.json says no bye is left or the season is over. -->
  <div class="steps ask kit" id="kit" data-reveal>
    <h3>Something free for the league</h3>
    <p class="kit-lead">Free to send the group chat today. Nothing here needs an email or a login.</p>
    <div class="kit-item" id="kit-byes-block">
      <div class="chatline">
        <p id="kit-byes">Bye check for the playoff push, free, no login: paste your roster and it shows every week through 17 where a bye leaves a starting spot empty. https://beatyourleague.com/byes/?via=league-chat</p>
      </div>
      <button type="button" class="sharebtn" data-share-from="kit-byes" data-share-status="kit-byes-msg" aria-describedby="kit-byes">Send this to the group chat</button>
      <p class="chatline-msg" id="kit-byes-msg" role="status"></p>
    </div>
    <div class="kit-item" id="kit-sample-block">
      <div class="chatline">
        <p id="kit-sample">This is the report each of us would get every Tuesday, built from our own roster: https://beatyourleague.com/sample-report.html?via=league-chat</p>
      </div>
      <button type="button" class="sharebtn" data-share-from="kit-sample" data-share-status="kit-sample-msg" aria-describedby="kit-sample">Send this to the group chat</button>
      <p class="chatline-msg" id="kit-sample-msg" role="status"></p>
    </div>
  </div>
"""
KIT_CSS = """  /* The commissioner kit (G4): the ask's own chatline and share button. */
  .kit-lead{margin-top:8px;font-size:15px;line-height:1.55;color:var(--dusk2);}
  .kit-item + .kit-item{margin-top:20px;}
"""
# Inside the page's script, after the ask's handler.
KIT_SHARE_JS = """// The commissioner kit (G4): each line goes to the group chat through the
// page's one shareLine.
document.querySelectorAll("[data-share-from]").forEach((button) => {
  button.addEventListener("click", () => {
    const line = document.getElementById(button.getAttribute("data-share-from"));
    const status = document.getElementById(button.getAttribute("data-share-status"));
    if (line && status) shareLine(line.textContent.replace(/\\s+/g, " ").trim(), line, status);
  });
});
"""
# First thing inside the week.json fetch's `.then((w) => {`, before its early return.
KIT_HIDE_JS = """      // No bye left to plan, or the season is over: the kit's bye line goes (G4).
      const kitByes = document.getElementById("kit-byes-block");
      if (kitByes && w && (w.byes_left === false || w.phase === "over")) kitByes.hidden = true;
"""
VIA_RE = r"^[a-z0-9-]{1,24}$"


def _kit_lines() -> list[str]:
    return re.findall(r'<p id="kit-[a-z]+">(.*?)</p>', KIT_MARKUP, re.S)


def test_the_kit_lines_sell_nothing_and_say_where_they_came_from() -> None:
    """No price (so no disclosure is owed), no checkout link, and each ends
    with an https URL tagged ?via=league-chat — a tag the funnel's own
    sanitiser keeps — on the planner (contract C7) or the sample."""
    lines = _kit_lines()
    assert len(lines) == 2
    for line in lines:
        assert "$" not in line and "join/" not in line
        url = line.rsplit(" ", 1)[1]
        assert url.startswith("https://beatyourleague.com/") and url.endswith("?via=league-chat")
        assert re.fullmatch(VIA_RE, url.rsplit("=", 1)[1])
        low = line.lower()
        assert not re.search(r"\b(calibrated|tested|proven|accurate|file|bet|odds)\b", low)
    assert lines[0].split(" https://")[1].startswith("beatyourleague.com/byes/")
    assert lines[1].split(" https://")[1].startswith("beatyourleague.com/sample-report.html")
    # T2: the bye line hides from Week 14 on (KIT_HIDE_JS), so a lead that
    # counted its items ("Two things…") promised two above one.
    lead = re.search(r'<p class="kit-lead">(.*?)</p>', KIT_MARKUP).group(1)
    assert not re.search(r"\b(two|both|neither|one)\b", lead.lower()), lead
    buttons = re.findall(r"<button[^>]*>", KIT_MARKUP)
    assert len(buttons) == 2 and all("data-share-from" in b and "data-share-status" in b
                                     for b in buttons)
    assert "shareLine(" in KIT_SHARE_JS and "data-share-from" in KIT_SHARE_JS


def _node(script: str):
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node not available")
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_kit_shares_each_line_and_hides_the_bye_line_with_no_byes_left() -> None:
    """Run under node with a stub DOM: each button hands ITS line to
    shareLine; the bye block hides on byes_left false or phase over, and
    stays for an ordinary week, an unknown one and the preseason."""
    got = _node("""
const els = {"kit-byes": {textContent: " Bye check\\n  for the push https://x/byes/?via=league-chat "},
             "kit-byes-msg": {}, "kit-sample": {textContent: "This is the report https://x/s"},
             "kit-sample-msg": {}};
const buttons = [["kit-byes", "kit-byes-msg"], ["kit-sample", "kit-sample-msg"]].map(([f, s]) => ({
  attrs: {"data-share-from": f, "data-share-status": s},
  getAttribute(n) { return this.attrs[n]; },
  addEventListener(_e, fn) { this.click = fn; }}));
const document = {querySelectorAll: () => buttons, getElementById: (id) => els[id]};
const shared = [];
function shareLine(text, line, status) { shared.push([text, line === els[buttons[shared.length].attrs["data-share-from"]], !!status]); }
""" + KIT_SHARE_JS + """
buttons.forEach((b) => b.click());
const hidden = [{byes_left: false}, {phase: "over"}, {byes_left: true, phase: "season"},
                {}, {phase: "preseason"}, null].map((w) => {
  const block = {hidden: false};
  els["kit-byes-block"] = block;
  (function () {
""" + KIT_HIDE_JS + """
  })();
  return block.hidden;
});
console.log(JSON.stringify({shared, hidden}));
""")
    assert got["shared"] == [["Bye check for the push https://x/byes/?via=league-chat", True, True],
                             ["This is the report https://x/s", True, True]]
    assert got["hidden"] == [True, True, False, False, False, False]


def test_once_pasted_the_kit_follows_the_ask_and_precedes_the_steps() -> None:
    """When the pages builder has pasted the kit into league-pass.html: it is
    the markup above, after "Ask the league first" (whose #ask-text and
    #ask-share stay) and before "What you do after paying", and its two
    scripts are in the page."""
    page = (SITE / "league-pass.html").read_text(encoding="utf-8")
    if 'id="kit"' not in page:
        pytest.skip("the commissioner kit is not pasted into league-pass.html yet (integrator note G4)")
    assert KIT_MARKUP.strip() in page
    assert page.index('id="ask-share"') < page.index('id="kit"') < page.index("What you do after paying")
    assert KIT_SHARE_JS.strip() in page and KIT_HIDE_JS.strip() in page
    assert KIT_CSS.strip() in page


def test_the_launch_email_names_the_league_pass_only_when_it_can_be_bought(monkeypatch) -> None:
    """The one promised email gains ONE line for a commissioner — only when
    the join page can sell the pass (FORM_ENDPOINT and STRIPE_LINK_PASS both
    set), and never as a second email."""
    from run import waitlist
    if not hasattr(waitlist, "LEAGUE_PASS_LINE"):
        pytest.skip("run/waitlist.py LEAGUE_PASS_LINE not applied yet (integrator note G4)")
    sender = "Beat Your League · PO Box 1 · hello@beatyourleague.com"
    lead = waitlist.LEAGUE_PASS_LINE.split(":")[0]
    def body() -> str:
        return " ".join(waitlist.compose("https://beatyourleague.com/join/", sender, {})[1].split())
    monkeypatch.setattr(waitlist, "_league_pass_live", lambda: False)
    assert lead not in body()
    monkeypatch.setattr(waitlist, "_league_pass_live", lambda: True)
    assert lead in body() and "https://beatyourleague.com/league-pass.html" in body()
    assert body().index("one per person") < body().index(lead) < body().index("/join/"), \
        "the line belongs after the offer paragraph"
    assert body().count("league-pass.html") == 1
    page = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    both = (re.search(r'^const FORM_ENDPOINT = "([^"]*)";', page, re.M).group(1).strip()
            and re.search(r'^const STRIPE_LINK_PASS = "([^"]*)";', page, re.M).group(1).strip())
    lp = (SITE / "league-pass.html").read_text(encoding="utf-8")
    sells = all(re.search(rf"^const {n} = true;", lp, re.M) for n in ("CHECKOUT_OPEN", "SEATS_OPEN"))
    monkeypatch.undo()
    assert waitlist._league_pass_live() == bool(both and sells)
    for claim in waitlist.FORBIDDEN_CLAIMS:
        assert claim not in waitlist.LEAGUE_PASS_LINE.lower()


def test_the_league_pass_line_waits_for_the_page_it_links(tmp_path, monkeypatch) -> None:
    """WL-1, reproduced: with the join page's FORM_ENDPOINT and
    STRIPE_LINK_PASS set and league-pass.html still at CHECKOUT_OPEN=false /
    SEATS_OPEN=false (the launch check flags the mismatch, nothing stopped a
    send), the one launch email said "One payment covers every manager's own
    report…" and linked a page with no Buy button. The line needs the page
    it links to build one too."""
    from run import waitlist
    join = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    join = re.sub(r'^const FORM_ENDPOINT = "[^"]*";',
                  'const FORM_ENDPOINT = "https://forms.beatyourleague.com/rows";', join,
                  count=1, flags=re.M)
    join = re.sub(r'^const STRIPE_LINK_PASS = "[^"]*";',
                  'const STRIPE_LINK_PASS = "https://buy.stripe.com/test_x";', join,
                  count=1, flags=re.M)
    lp = (SITE / "league-pass.html").read_text(encoding="utf-8")
    (tmp_path / "site" / "join").mkdir(parents=True)
    (tmp_path / "site" / "join" / "index.html").write_text(join, encoding="utf-8")
    monkeypatch.setattr(waitlist, "REPO_ROOT", tmp_path)
    for checkout, seats, live in (("false", "false", False), ("true", "false", False),
                                  ("false", "true", False), ("true", "true", True)):
        page = re.sub(r"^const CHECKOUT_OPEN = (?:true|false);", f"const CHECKOUT_OPEN = {checkout};",
                      lp, count=1, flags=re.M)
        page = re.sub(r"^const SEATS_OPEN = (?:true|false);", f"const SEATS_OPEN = {seats};",
                      page, count=1, flags=re.M)
        (tmp_path / "site" / "league-pass.html").write_text(page, encoding="utf-8")
        assert waitlist._league_pass_live() is live, (checkout, seats)


# --------------------------------------------------------------------- #
# G5 — the league-app help pages carry that app's own substance
# --------------------------------------------------------------------- #

PAGES = {p.slug: (p, (SITE / p.slug / "index.html").read_text(encoding="utf-8"))
         for p in platforms.PLATFORMS}


def test_the_pages_are_what_the_generator_writes() -> None:
    """Hand edits are forbidden: --check fails when a page is stale (the ask
    follows the landing's CHECKOUT_OPEN when written)."""
    assert platforms.main(["--check"]) == 0
    for slug, (_p, page) in PAGES.items():
        assert page.startswith("<!DOCTYPE html>\n<!-- GENERATED by `python -m render.platforms`")


def test_every_paste_line_is_backed_by_a_paste_the_reader_passes() -> None:
    """Each page's claim about its app's copy maps to tests/test_intake.py
    PASTES fixtures of that app, and those fixtures resolve to exactly their
    rosters in Python and in the browser. The slice shown on the page is a
    contiguous run of the first fixture's lines and resolves to what the page
    says it reads."""
    import test_intake
    for platform in platforms.PLATFORMS:
        assert platform.pastes, platform.slug
        for key in platform.pastes:
            assert key in test_intake.PASTES, (platform.slug, key)
            test_intake.test_a_paste_from_each_league_app_resolves_to_exactly_the_roster(key)
        lines = [line for line in test_intake.PASTES[platform.pastes[0]][0].splitlines()]
        n = len(platform.example)
        assert any(lines[i:i + n] == list(platform.example) for i in range(len(lines))), \
            f"{platform.slug}: the example is not a slice of its fixture"
        directory = test_intake._python_directory()
        read = [m.player.name for m in directory.resolve_all(list(platform.example))
                if m.resolved]
        unresolved = [m.typed for m in directory.resolve_all(list(platform.example))
                      if not m.resolved]
        assert read == list(platform.reads) and not unresolved, (platform.slug, read, unresolved)


@pytest.mark.parametrize("slug", sorted(PAGES))
def test_each_page_says_only_what_the_product_does(slug: str) -> None:
    """The banned-word, betting, developer-vocabulary and "file" sweeps; no
    price (so nothing owes a disclosure), no grade or comparison; the exact
    title, description, heading and canonical; indexed; the site's own share
    card; the planner at ../byes/ (C7); the one ask; the site's carry script,
    character for character; the counter last; and "Not affiliated with".
    """
    from test_site import _DEV_SPEAK, _js_function
    platform, page = PAGES[slug]
    name = platform.name
    visible = _visible(page)
    assert not re.search(r"\b(calibrated|tested|proven|accurate)\b|we hit \d", visible, re.I)
    assert not re.search(r"\b(parlay|sportsbook|against the spread|bet now|odds boost|wager|"
                         r"spread|lock)\b", visible, re.I)
    assert not re.search(r"\bfiles?\b", visible, re.I)
    for pattern in _DEV_SPEAK:
        assert not re.search(pattern, visible, re.I), pattern
    assert "$" not in visible and not re.search(r"better than|more accurate|grade", visible, re.I)
    assert f"<title>{name} fantasy football start/sit report for your roster — Beat Your League</title>" in page
    assert (f'<meta name="description" content="Copy your {name} fantasy roster and paste it, no '
            f"login: every Tuesday a report sets your lineup — every slot decided, close calls "
            f'explained, byes checked through Week 17.">') in page
    assert f"<h1>Your {name} roster, decided every Tuesday</h1>" in page
    assert f'<link rel="canonical" href="https://beatyourleague.com/{slug}/">' in page
    assert "noindex" not in page and SOCIAL_IMAGE_TAGS in page
    assert page.count('href="../byes/"') == 2 and "bye-week-planner" not in page
    assert f"Not affiliated with {name}." in visible
    assert live.esc(platform.lineup) in page and live.esc(platform.paste) in page
    assert re.search(r'<a class="btn gold" href="\.\./(?:index\.html#watch-form|'
                     r'join/index\.html(?:\?t=[a-z0-9-]+)?)">', page)
    # T4: step 2's "roster box" is a link to it (join/ checks a roster with
    # checkout closed too), on the app's default lineup (T5).
    assert f'<a href="{platforms.join_href(platform)}">the roster box</a>' in page
    # T8: "a ESPN copy", and a planner link about a roster the page holds.
    assert f"Part of a copy from {name}, shown the way the roster box reads it." in page
    assert "check your roster&#x27;s byes" in page and "this roster" not in visible
    assert _js_function(page, "carryVia") == _js_function(live.VIA_SCRIPT, "carryVia")
    assert page.rstrip().endswith('<script src="/count.js" defer></script>\n</body>\n</html>'.strip())


def test_an_apps_links_into_join_open_on_its_default_lineup(monkeypatch) -> None:
    """T5: Sleeper's page says its default lineup is Two FLEX, and its links
    into join/ were bare, while join's buy mode never read ?t= — so a
    Sleeper manager who kept join's defaults got Standard-lineup reports.
    Each app with a default carries the join page's own code for it (open
    state and the roster-box link alike), the codes are join's own, and
    join/ preselects them outside a seat, an update or a restored roster."""
    from render import report as rr
    monkeypatch.setattr(rr, "checkout_open", lambda landing=None: True)
    by = {p.slug: p for p in platforms.PLATFORMS}
    want = {"espn": "?t=std", "yahoo": "?t=std", "sleeper": "?t=flex2", "cbs": ""}
    for slug, query in want.items():
        page = platforms.page(by[slug])
        assert page.count(f'<a class="btn gold" href="../join/index.html{query}">') == 2, slug
        assert f'<a href="../join/index.html{query}">the roster box</a>' in page, slug
    roster_js = (SITE / "join" / "roster.js").read_text(encoding="utf-8")
    bases = re.search(r"const SHAPE_BASES = \{(.*?)\};", roster_js, re.S).group(1)
    assert set(platforms.SHAPE_CODES.values()) == set(re.findall(r"^\s*(\w+):", bases, re.M))
    assert set(platforms.SHAPE_CODES) == {name for name, _ in platforms.SHAPES}
    join = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    flow = join.split("if (RESTORED) {\n  setRadio(\"scoring\"", 1)[1].split(
        "if (UPDATE_MODE) prefillUpdateSettings();", 1)[0]
    assert re.search(r"\} else if \(SEAT_MODE\) \{.*\} else if \(!UPDATE_MODE\) \{[^}]*"
                     r"settingsFromLink\(\);\s*\}\s*$", flow, re.S), flow


def test_no_two_pages_differ_only_by_the_name() -> None:
    """A cheap doorway guard: with each app's name blanked out, every pair of
    pages still differs, and so do their paste and lineup lines."""
    blanked = {}
    for slug, (platform, page) in PAGES.items():
        text = _visible(page)
        for p in platforms.PLATFORMS:
            text = text.replace(p.name, "APP")
        blanked[slug] = text
    slugs = sorted(blanked)
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            assert blanked[a] != blanked[b], (a, b)
            pa, pb = PAGES[a][0], PAGES[b][0]
            assert pa.paste.replace(pa.name, "APP") != pb.paste.replace(pb.name, "APP")
            assert pa.example != pb.example


def test_the_lineup_lines_reuse_only_what_the_join_page_claims() -> None:
    """ESPN and Yahoo default to the lineup we call Standard and Sleeper to
    Two FLEX — the join page's own labels — and the shapes a page lists are
    the join page's four."""
    join = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    assert "Standard <span class=\"optsub\">· ESPN's and Yahoo's default</span>" in join
    assert "Two FLEX <span class=\"optsub\">· Sleeper's default</span>" in join
    by = {p.slug: p for p in platforms.PLATFORMS}
    assert by["espn"].shape == by["yahoo"].shape == "Standard" and by["sleeper"].shape == "Two FLEX"
    for shape, _slots in platforms.SHAPES:
        assert re.search(rf'value="[a-z0-9]+"(?: checked)?>{re.escape(shape)}\b', join), shape


# --------------------------------------------------------------------- #
# G6 — the planner, offered on the samples while checkout is closed
# --------------------------------------------------------------------- #

PUBLISHED = ("this-week.html", "sample-report.html", "sample-first-week.html")


def _figures(page: str) -> list[str]:
    """Every number a reader sees outside the closing card."""
    body = re.sub(r'<div class="ctacard">.*?</div>', " ", _visible_main(page), flags=re.S)
    return re.findall(r"\d+(?:\.\d+)?%?", body)


def _visible_main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0] if "<main" in page else page


def test_the_planner_line_shows_only_while_checkout_is_closed(monkeypatch) -> None:
    """On a sample's closing card, under its one button, exactly once — and
    gone once the pass can be bought, the season is over, or the schedule
    says no bye is left."""
    from render import report as rr
    page = (SITE / "sample-report.html").read_text(encoding="utf-8")
    monkeypatch.setattr(rr, "checkout_open", lambda landing=None: False)
    shown = live.with_planner_line(page, live.show_planner_line())
    card = shown.split('<div class="ctacard">', 1)[1].split("</div>", 1)[0]
    assert card.count('class="plannerline"') == 1 and 'href="byes/"' in card
    assert card.index('class="btn gold"') < card.index("plannerline")
    assert live.PLANNER_LINE_TEXT.replace("'", "&#x27;") in card
    assert not live.show_planner_line(byes_left=False)
    assert not live.show_planner_line(phase="over")
    assert live.show_planner_line(byes_left=None, phase="preseason")
    monkeypatch.setattr(rr, "checkout_open", lambda landing=None: True)
    assert not live.show_planner_line()
    assert "plannerline" not in live.with_planner_line(shown, live.show_planner_line())


@pytest.mark.parametrize("name", PUBLISHED)
def test_the_restamp_adds_the_line_and_moves_no_number(name: str, monkeypatch) -> None:
    """`python -m render.live_sample --restamp` on each published page: the
    line appears once under the closing card's button, no figure, banner or
    row moves, and a second restamp changes nothing."""
    from render import report as rr
    monkeypatch.setattr(rr, "checkout_open", lambda landing=None: False)
    before = (SITE / name).read_text(encoding="utf-8")
    once = live.restamp_chrome(before, byes_left=True, phase="season")
    assert live.restamp_chrome(once, byes_left=True, phase="season") == once
    assert once.count('class="plannerline"') == 1
    assert _figures(once) == _figures(live.restamp_chrome(before, byes_left=False))
    assert _figures(once) == _figures(live.with_planner_line(before, False)), \
        "the restamp moved a number"
    assert "plannerline" not in live.restamp_chrome(once, byes_left=False)
    assert "plannerline" not in live.restamp_chrome(once, phase="over")


def test_the_restamp_brings_an_older_carry_script_up_to_date() -> None:
    """The ?via= carry is one function on every funnel page; a published
    page holding an older copy (the planner joins the funnel list, T3) is
    brought up to VIA_SCRIPT by a restamp rather than a rebuild."""
    old = live.VIA_SCRIPT.replace("sample-first-week\\.html)", "sample-first-week\\.html|old)")
    page = live.with_via_carry("<html><body><main id=\"main\"></main></body></html>")
    stale = page.replace(live.VIA_SCRIPT, old)
    assert stale != page and live.with_current_via(stale) == page
    assert live.with_current_via(page) == page


def test_no_subscriber_or_free_report_carries_the_planner_line(week) -> None:  # noqa: F811
    """Samples only: the email a subscriber receives, its text half and a
    rendered report (a free report included) never carry it — the line is
    added by the sample builders, never by the report renderer."""
    from render.email import render_email, text_summary
    from render.report import TEMPLATE_PATH, render
    report = week()
    for meta in ({}, {"live_demo": False, "anonymized_demo": False},
                 {"trial": True, "live_demo": False, "anonymized_demo": False}):
        r = copy.deepcopy(report)
        r["meta"].update(meta)
        assert "plannerline" not in render_email(r)
        assert live.PLANNER_LINE_TEXT not in text_summary(r)
        assert "plannerline" not in render(r, TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_the_planner_rides_the_funnels_tag_once_t3_lands() -> None:
    """T3 (another builder's): once the funnel regex names the planner, a
    ?via= tag rides the samples' planner line like every funnel link."""
    if "byes" not in live.VIA_SCRIPT:
        pytest.skip("the carryVia funnel list does not name the planner yet (T3)")
    from test_site import _js_function
    got = _node(_js_function(live.VIA_SCRIPT, "carryVia")
                + '\nconsole.log(JSON.stringify([carryVia("byes/", "x"), carryVia("../byes/", "x")]));')
    assert got == ["byes/?via=x", "../byes/?via=x"]
