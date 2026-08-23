"""The Tuesday path for a roster the subscriber typed — no league, no Sleeper.

``engine/solo_report.py`` could always build this report; nothing fed it. These
tests cover ``run/solo.py``, the module that does, and they run entirely off
fixture CSVs written into a temp cache — ``ingest.nflverse.fetch`` returns a
cached file untouched, so a fresh fixture means no network at all.

The properties worth having tests for are the ones where being wrong is quiet:
an availability snapshot that reads "everyone is healthy" because the report has
not been published yet, a defense credited with its own offense's targets, a
zero rendered where nothing was measured, and a licence term that has to appear
on every report we send.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest
import re

import run.solo as solo
from engine.availability import Status
from engine.roster import Player, PlayerDirectory
from engine.subscriber import RosterSpec
from ingest.injuries import InjuryWeek


class _Offline:
    """Any fetch the fixture did not provide is a test that went online.

    Without this the suite silently downloaded the real archives — which passes,
    slowly, and stops proving anything about the fixture it claims to test.
    """

    def get(self, url, **_kwargs):        # noqa: D102 - requests.Session shape
        raise AssertionError(f"the fixture is incomplete: something fetched {url}")

SEASON = "2024"
WEEK = 6

# One roster's worth of players plus enough of a field that the positional
# prior has somebody to rank. Ids are GSIS-shaped because RULE R1 requires it.
# Display names deliberately contain NO position tokens (QB, WR, K…): the trial
# path resolves these through the real decoration-stripper, which eats position
# tags — a fixture named "Star QB" would strip to "Star" and resolve nowhere.
# Real players are not named after their positions; the fixture shouldn't be.
ROSTER = [("Aaron Armstrong", "QB", "KC"), ("Bell Cow", "RB", "SF"),
          ("Cade Carter", "RB", "DET"), ("Dre Wideout", "WR", "CIN"),
          ("Eli Slotside", "WR", "DET"), ("Frank Tighten", "TE", "SF"),
          ("Gabe Fielder", "WR", "DEN"), ("Hank Benchman", "RB", "KC")]
SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")


def _pid(index: int) -> str:
    return f"00-00{index:05d}"


def _write(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


OFFLINE = _Offline()


def _cache(tmp_path: Path, *, weeks: int = 5, injuries: bool = True,
           season: str = SEASON) -> Path:
    """A complete nflverse cache: schedule, directory, two seasons, injuries."""
    cache = tmp_path / "nflverse"
    teams = ["KC", "SF", "DET", "CIN", "DEN", "BAL"]

    games = []
    for week in range(1, 9):
        # Week 4 sits DEN and BAL out, which makes it the bye week.
        playing = teams[:4] if week == 4 else teams
        for i in range(0, len(playing) - 1, 2):
            games.append({
                "season": season, "game_type": "REG", "week": week,
                "gameday": f"{season}-09-{week + 6:02d}",
                "away_team": playing[i], "home_team": playing[i + 1],
                "away_score": 17 if week < weeks + 1 else "",
                "home_score": 24 if week < weeks + 1 else "",
            })
    _write(cache / "games.csv", games,
           ["season", "game_type", "week", "gameday", "away_team", "home_team",
            "away_score", "home_score"])

    players = [{"gsis_id": _pid(i), "display_name": name, "position": position,
                "last_season": str(int(season) - 1), "latest_team": team}
               for i, (name, position, team) in enumerate(ROSTER, start=1)]
    # A field of extras so rosterable_field has a population to rank.
    for i in range(len(ROSTER) + 1, 60):
        position = ["QB", "RB", "WR", "TE"][i % 4]
        players.append({"gsis_id": _pid(i), "display_name": f"Extra {i}",
                        "position": position, "last_season": str(int(season) - 1),
                        "latest_team": teams[i % len(teams)]})
    _write(cache / "players.csv", players,
           ["gsis_id", "display_name", "position", "last_season", "latest_team"])
    _write(cache / "teams_colors_logos.csv",
           [{"team_abbr": t, "team_name": f"{t} Team"} for t in teams],
           ["team_abbr", "team_name"])

    for which, offset in ((season, 0), (str(int(season) - 1), 3)):
        rows = []
        for week in range(1, weeks + 1):
            for i, player in enumerate(players, start=1):
                rows.append({
                    "player_id": player["gsis_id"], "season": which,
                    "week": week, "season_type": "REG",
                    "position": player["position"], "team": player["latest_team"],
                    "player_display_name": player["display_name"],
                    "receptions": 4, "receiving_yards": 40 + offset + i,
                    "receiving_tds": 0, "rushing_yards": 10, "rushing_tds": 0,
                    "passing_yards": 0, "passing_tds": 0,
                    # Counted usage. A quarterback's targets are a real zero,
                    # which is the case that used to print "0 targets".
                    "targets": 0 if player["position"] == "QB" else 5,
                    "receiving_air_yards": 0 if player["position"] == "QB" else 60,
                    "carries": 12 if player["position"] in ("QB", "RB") else 0,
                })
        _write(cache / f"stats_player_week_{which}.csv", rows,
               ["player_id", "season", "week", "season_type", "position", "team",
                "player_display_name", "receptions", "receiving_yards",
                "receiving_tds", "rushing_yards", "rushing_tds", "passing_yards",
                "passing_tds", "targets", "receiving_air_yards", "carries"])

    _write(cache / f"stats_team_week_{season}.csv",
           [{"team": team, "season": season, "week": week, "season_type": "REG",
             "def_sacks": 3, "def_interceptions": 1,
             # A team's OFFENSIVE counts ride along in this release, which is
             # what made a defense's usage line describe its own offense.
             "targets": 32, "carries": 28}
            for week in range(1, weeks + 1) for team in teams],
           ["team", "season", "week", "season_type", "def_sacks",
            "def_interceptions", "targets", "carries"])

    rows = []
    if injuries:
        for week in range(1, 9):
            for i, player in enumerate(players, start=1):
                if i % 7 == 0:                       # a few listed each week
                    rows.append({"season": season, "week": week,
                                 "gsis_id": player["gsis_id"],
                                 "team": player["latest_team"],
                                 "report_status": "Out" if i % 14 == 0
                                 else "Questionable"})
                elif i % 5 == 0:
                    rows.append({"season": season, "week": week,
                                 "gsis_id": player["gsis_id"],
                                 "team": player["latest_team"],
                                 "report_status": ""})
    else:
        # The archive EXISTS and simply has nothing for the report week yet —
        # which is what Tuesday looks like before the first practice report.
        rows.append({"season": season, "week": WEEK + 1, "gsis_id": _pid(1),
                     "team": "KC", "report_status": "Questionable"})
    _write(cache / f"injuries_{season}.csv", rows,
           ["season", "week", "gsis_id", "team", "report_status"])
    return cache


def _spec() -> RosterSpec:
    return RosterSpec(player_ids=tuple(_pid(i) for i in range(1, len(ROSTER) + 1)),
                      slots=SLOTS, scoring="ppr", label="Your Team")


# --------------------------------------------------------------------- #
# the calendar, without asking a league platform
# --------------------------------------------------------------------- #

def test_the_week_is_read_from_the_schedule_not_from_state_nfl(tmp_path) -> None:
    """The Sleeper path took the season and week from ``/v1/state/nfl``. Small,
    convenient, and exactly the sort of call that keeps a licence dependency
    alive after the decision to remove it."""
    cache = _cache(tmp_path)
    assert solo.current_season(cache, date(2024, 9, 10)) == SEASON
    # Week n's only gameday is the 6+n'th; a report written on it is about it.
    assert solo.current_week(cache, SEASON, date(2024, 9, 7)) == 1
    assert solo.current_week(cache, SEASON, date(2024, 9, 12)) == 6
    # Past the last game, the season is over and the last week is the answer —
    # never week 19, and never a crash on a Wednesday in February.
    assert solo.current_week(cache, SEASON, date(2025, 3, 1)) == 8


def test_a_finished_season_never_reports_itself_as_current(tmp_path) -> None:
    """A report about games played twelve months ago renders complete and
    confident with no gap and no warning — CLAUDE.md calls it the quietest
    principle-3 violation in the codebase."""
    cache = _cache(tmp_path)
    # After the season ends, with no later schedule published, the answer is
    # the season that just finished rather than a guess at the next one.
    assert solo.current_season(cache, date(2025, 6, 1)) == SEASON


# --------------------------------------------------------------------- #
# availability — the half that must never silently read "everyone is fine"
# --------------------------------------------------------------------- #

def test_a_week_with_no_injury_report_yields_no_snapshot(tmp_path) -> None:
    """The archive holds rows only for players who were LISTED, so an empty
    week is ambiguous: nobody hurt, or nobody has published yet. Building
    statuses from the directory alone resolves that ambiguity the dangerous
    way — a clean bill of health for every player in the league, and a
    confidence on every slot."""
    directory = PlayerDirectory([Player(_pid(1), "Aaron Armstrong", "QB", "KC")])
    assert solo._statuses(directory, None) is None
    empty = InjuryWeek(season=SEASON, week=9, by_gsis={}, teams={})
    assert solo._statuses(directory, empty) is None

    availability = solo._availability(_cache(tmp_path, injuries=False),
                                      SEASON, WEEK, directory, session=OFFLINE)
    assert not availability.has_snapshot
    assert availability.classify(_pid(1)).status is Status.UNKNOWN


def test_the_gate_reads_last_weeks_report_never_this_weeks(tmp_path) -> None:
    """The single most consequential rule in the frozen method (§6): the
    designation used is week W-1's. The product ships Tuesday; week W's
    report is published Wednesday-Friday. Measured on the real 2024 archive,
    by the Tuesday send week W held 0-2 of its 200-385 rows in every week but
    one, and week W-1 was complete in every week. Reading week W meant either
    no snapshot (no confidence anywhere) or a two-row file read as a clean
    bill of health. Both halves pinned: W-1 rows alone yield a snapshot; W
    rows alone yield none."""
    cache = _cache(tmp_path, injuries=False)
    path = cache / f"injuries_{SEASON}.csv"
    columns = ["season", "week", "gsis_id", "team", "report_status"]
    listed = {"season": SEASON, "gsis_id": _pid(7), "team": "DEN",
              "report_status": "Questionable"}
    # Only week W-1 is published — the Tuesday state.
    _write(path, [dict(listed, week=WEEK - 1)], columns)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    assert data.availability.has_snapshot
    assert data.availability.classify(_pid(7)).status is Status.QUESTIONABLE
    assert "week 5" in (data.availability.snapshot_as_of or "")
    # Only week W is published (impossible on a Tuesday, and lookahead if it
    # were) — the gate must not read it.
    _write(path, [dict(listed, week=WEEK)], columns)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    assert not data.availability.has_snapshot, \
        "the live gate read week W's report — lookahead relative to the Tuesday send"


def test_a_player_with_no_season_row_is_unknown_not_active(tmp_path) -> None:
    """Carry-forward team, as the harness does it: a player with no stat row
    strictly before the week cannot be placed on a team and is omitted, which
    classifies UNKNOWN. The directory's team is NOT a fallback — that is
    wherever he is today, and the measured gate never used it."""
    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    ghost = "00-0099999"
    assert ghost not in (data.availability.statuses or {})
    assert data.availability.classify(ghost).status is Status.UNKNOWN


def test_a_healthy_player_is_active_without_being_in_the_archive(tmp_path) -> None:
    """The mirror of the rule above. A player nobody listed is a player nobody
    had a concern about — reading the archive alone would leave every healthy
    starter UNKNOWN and gate the entire product."""
    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    assert data.availability.has_snapshot
    healthy = data.availability.classify(_pid(1))
    assert healthy.status is Status.ACTIVE, healthy.reason
    # And a designation in the archive still lands.
    listed = data.availability.classify(_pid(7))
    assert listed.status is Status.QUESTIONABLE, listed.reason
    assert data.availability.classify(_pid(14)).status is Status.OUT


def test_a_bye_is_out_even_with_a_clean_injury_report(tmp_path) -> None:
    """"ACTIVE requires knowing the player is NOT on bye" — an unavailable
    player with nothing wrong with him is still a zero."""
    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, 4, session=OFFLINE)
    assert data.availability.bye_teams == frozenset({"DEN", "BAL"})
    # Player 7 is on DEN in the fixture and carries a designation; the bye is
    # decided first and names the schedule as its reason.
    assert data.availability.classify(_pid(7)).status is Status.OUT
    assert "bye" in data.availability.classify(_pid(7)).reason


# --------------------------------------------------------------------- #
# counted usage (RULE U1) — reported, never projected
# --------------------------------------------------------------------- #

def test_a_defense_never_carries_its_own_offences_usage(tmp_path) -> None:
    """merge_defenses folds team rows into the same weekly dict, and a team row
    carries the OFFENSE's counts. The Broncos defense rendered "128 targets
    (32.0 a game), 115 carries" in a real run: a true sentence about entirely
    the wrong team."""
    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    assert "DEF-KC" in data.weekly[1], "the fixture never merged a defense"
    assert not [key for key in data.usage if key.startswith("DEF-")]


def test_a_zero_window_total_is_not_reported_as_a_zero(tmp_path) -> None:
    """nflverse writes a real 0 where Sleeper wrote nothing, so a quarterback
    read "0 targets (0.0 a game), 21 carries" — true, and pure noise beside the
    count that is the story."""
    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    quarterback = data.usage[_pid(1)]
    assert quarterback.targets is None and quarterback.air_yards is None
    assert quarterback.carries == 48                 # 4 weeks x 12
    # RULE N2: snaps are PFR-derived and are not read at all.
    assert quarterback.snaps is None


def test_usage_never_reads_the_week_it_is_about(tmp_path) -> None:
    """Same rule as the waiver market (RULE W2): a live report quoting the week
    it is predicting has read the future."""
    cache = _cache(tmp_path)
    receiver = solo.load_week_data(cache, SEASON, 3, session=OFFLINE).usage[_pid(4)]
    assert receiver.weeks == 2, "the report week leaked into the window"
    assert receiver.targets == 10


# --------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------- #

def test_a_typed_roster_becomes_a_report(tmp_path) -> None:
    cache = _cache(tmp_path)
    report = solo.report_for(_spec(), solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE),
                             cache_dir=cache)
    meta = report["meta"]
    assert meta["solo"] is True
    assert meta["rival_label"] is None and meta["week"] == WEEK
    assert len(report["lineup"]) == len(SLOTS)
    assert all(slot["projected"] is not None for slot in report["lineup"])
    # No league means no opponent, and that is stated as a gap rather than
    # rendered as an empty section.
    assert any(gap["field"] == "opponent" for gap in meta["gaps"])
    for absent in ("hype", "fragility", "tape", "last_week"):
        assert absent not in report


def test_week_one_is_a_report_rather_than_an_exception(tmp_path) -> None:
    """The FIRST report of the season is the one every launch subscriber is
    waiting for, and it could not be built: no games played means no roster
    record before week 1, and build_solo_report raised.

    Nothing about that is an error — there is no form yet, and the product has
    copy for exactly this state. What it may never do is invent numbers, so
    every row publishes a player and no projection.
    """
    cache = _cache(tmp_path)
    report = solo.report_for(_spec(), solo.load_week_data(cache, SEASON, 1,
                                                          session=OFFLINE),
                             cache_dir=cache)
    assert report["meta"]["lineup_as_set"] is True
    assert len(report["lineup"]) == len(SLOTS)
    for slot in report["lineup"]:
        assert slot["player_id"], f"{slot['slot']} rendered empty in week 1"
        assert slot["projected"] is None and slot["confidence"] is None


def test_week_one_never_claims_the_roster_is_empty(tmp_path) -> None:
    """A solo TeamWeek has no `starters` (RULE B3: we never saw a lineup), and
    the no-projections branch read them — so every slot rendered empty and the
    checklist told a subscriber with a full roster "You have nobody to start at
    QB, RB, TE, WR". A confident false statement about players the report can
    see is worse than the exception it replaced."""
    cache = _cache(tmp_path)
    report = solo.report_for(_spec(), solo.load_week_data(cache, SEASON, 1,
                                                          session=OFFLINE),
                             cache_dir=cache)
    actions = " ".join(item["action"] for item in report["checklist"])
    assert "nobody to start" not in actions, actions
    assert "no start-sit calls yet" in actions.lower()
    # And it states the BASIS, not just the absence: the slots ARE filled, so a
    # reader told only "this is not a recommendation" is left guessing why these
    # players are in them.
    assert "last season" in actions.lower()
    assert "not a forecast" in actions.lower()


def test_week_one_seats_the_better_player_rather_than_the_lower_id(
        tmp_path) -> None:
    """Week 1's placement used to sort candidates BY PLAYER ID.

    That is reproducible and meaningless, and it is not a harmless default: with
    three running backs and two RB slots, an arbitrary two of them start. The
    ordering is last season's points per APPEARANCE — a record of what happened,
    never a projection for this week — so the same roster now seats the two who
    actually produced.
    """
    cache = _cache(tmp_path, weeks=5)
    data = solo.load_week_data(cache, SEASON, 1, session=OFFLINE)
    # The fixture's prior season pays receiving yards that RISE with player
    # index, so the higher-numbered back is the better one — the opposite of
    # what sorting by id would seat.
    backs = [_pid(2), _pid(3)]                       # both RB in the fixture
    spec = RosterSpec(player_ids=(_pid(1), *backs, _pid(4), _pid(5), _pid(6)),
                      slots=("QB", "RB", "WR", "WR", "TE"), scoring="ppr")
    report = solo.report_for(spec, data, cache_dir=cache)
    rb = [s for s in report["lineup"] if s["slot"] == "RB"][0]
    assert rb["player_id"] == max(backs), (
        f"week 1 seated {rb['player_id']}, the lower id, not the better back")
    # Still no numbers anywhere: an ordering is not a projection.
    assert all(s["projected"] is None and s["confidence"] is None
               for s in report["lineup"])
    # And the basis is on the row, so the order can be checked.
    assert "last season" in (rb.get("usage") or "")


def test_the_week_one_ordering_is_deterministic_without_a_prior_season(
        tmp_path) -> None:
    """A rookie has no prior season at all, and two players can tie. Falling
    back to the id keeps a report byte-identical across runs — which is the
    property the id-sort was there for in the first place."""
    from engine.week_report import _place_without_projections
    from engine.history import TeamWeek

    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, 1, session=OFFLINE)
    spec = _spec()
    season = build_season_for(spec, data)
    carrier = TeamWeek(roster_id=1, week=0, matchup_id=None, starters=(),
                       starters_points=(), players=spec.player_ids,
                       players_points={p: 0.0 for p in spec.player_ids},
                       points=0.0, appeared=frozenset())
    first = _place_without_projections(season, carrier, data.players, {})
    second = _place_without_projections(season, carrier, data.players, {})
    assert first == second and first, "placement is not deterministic"


def build_season_for(spec, data):
    from engine.subscriber import build_season
    return build_season(spec, data.weekly, data.directory, SEASON, 1,
                        league_size=12)


def test_all_three_surfaces_show_the_week_one_ordering_basis(tmp_path) -> None:
    """The checklist says the figure is "shown on each line". That was true of
    the two HTML surfaces and NOT of the plain-text one — which is the half that
    goes in every email, so the sentence was a false statement exactly where it
    was least visible."""
    from render.email import render_email, text_summary
    from render.report import TEMPLATE_PATH, render

    cache = _cache(tmp_path, weeks=5)
    report = solo.report_for(_spec(), solo.load_week_data(cache, SEASON, 1,
                                                          session=OFFLINE),
                             cache_dir=cache)
    seated = [s for s in report["lineup"] if s["player_id"]]
    assert seated, "the fixture produced no filled slots"

    # PER ROW, not anywhere in the document. The first version of this asserted
    # `"last season" in doc`, which passed from the CHECKLIST sentence alone —
    # so deleting the per-row rendering left it green. A test that reads the
    # claim as evidence for the claim proves nothing.
    text = text_summary(report)
    rows = [line for line in text.splitlines()
            if line.startswith("  ") and any(
                f" {s['slot']:<6} " in line + " " for s in seated)]
    assert len(rows) >= len(seated), f"text lineup rows not found in:\n{text}"
    for line in rows:
        assert "last season" in line, f"text row has no basis: {line!r}"

    # The HTML surfaces carry one per seated player, plus the checklist's own.
    for name, doc in (("browser", render(report, TEMPLATE_PATH.read_text(
                                          encoding="utf-8"))),
                      ("email", render_email(report))):
        assert doc.count("last season") >= len(seated), (
            f"{name} shows the basis {doc.count('last season')} times for "
            f"{len(seated)} seated players")
        assert "shown on each line" in doc, name


def test_a_hole_mid_season_is_still_an_error(tmp_path) -> None:
    """Week 1 is early; week 6 with weeks on record and none for this roster is
    an incomplete ingest, and must not quietly render as "no form yet"."""
    from engine.solo_report import build_solo_report
    from engine.projection import ProjectionModel
    from engine.subscriber import build_season, player_index
    from engine.week_report import WeekReportError
    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    season = build_season(_spec(), data.weekly, data.directory, SEASON, WEEK)
    season.weeks.pop(WEEK - 1)
    with pytest.raises(WeekReportError, match="nothing to project from"):
        build_solo_report(_spec(), season, data.players,
                          ProjectionModel(season, data.players),
                          data.availability, WEEK, cache)


def test_the_report_reads_the_most_recent_completed_week(tmp_path) -> None:
    """Every report projected week W from weeks 1..W-2, silently.

    build_season stops at W-1, so the last TeamWeek it holds is week W-1's — and
    optimal_lineup took the week it was projecting from that carrier, which made
    the model's cutoff W-1 and filtered week W-1 straight back out after loading
    it. The most recent completed week is also the most predictive one.

    Measured across 2019-2024 before fixing it: 14.6% of lineup slots seated a
    different player, 10.8% of publishable calls were suppressed by holding
    players one week short of MIN_GAMES_FOR_CALL, and on the matched
    head-to-heads where only the ordering differs the correction wins 133-100
    (two-sided sign test p = 0.036).
    """
    cache = _cache(tmp_path, weeks=5)          # weeks 1-5 played, report week 6
    report = solo.report_for(_spec(), solo.load_week_data(cache, SEASON, 6,
                                                          session=OFFLINE),
                             cache_dir=cache)
    games = {slot["player_name"]: slot["form_games"] for slot in report["lineup"]
             if slot["player_id"]}
    assert games, "no slot was filled"
    assert set(games.values()) == {5}, (
        f"a week-6 report must count all five completed weeks, got {games}")


def test_the_projected_week_is_passed_in_not_read_off_the_roster(tmp_path) -> None:
    """The trap, pinned. A TeamWeek is a roster carrier — both callers used it
    as one, and one of them says so in a comment — so its `.week` must never be
    what decides which weeks the model may read. Passing the week explicitly is
    the whole fix; deriving it again would reintroduce the off-by-one in a form
    no output makes visible."""
    import ast
    import inspect
    import textwrap
    from engine.week_report import optimal_lineup, rival_lineup
    for fn in (optimal_lineup, rival_lineup):
        assert "week" in inspect.signature(fn).parameters, fn.__name__
        # The DOCSTRING names the trap on purpose, so match against code only —
        # otherwise this passes or fails on prose, which is exactly the kind of
        # test that proves nothing about the thing it is named after.
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        body = tree.body[0].body
        if (isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)):
            body = body[1:]
        reads = [n for stmt in body for n in ast.walk(stmt)
                 if isinstance(n, ast.Attribute) and n.attr == "week"
                 and isinstance(n.value, ast.Name) and n.value.id == "team_week"]
        assert not reads, (
            f"{fn.__name__} derives the projected week from its roster carrier")


def test_the_solo_band_makes_no_coverage_claim(tmp_path) -> None:
    """The frozen method (reports/nflverse-backtest-method.md §10.8) gates the
    band's coverage sentence — "landed inside this range about 78% of the
    time" — until the nflverse band table exists: that figure was measured on
    the Sleeper stack over real set lineups, and solo totals have never been
    measured the same way. The published sample carried it anyway. The range
    still renders; the claim does not, and neither does any Grade-C banned
    word."""
    cache = _cache(tmp_path)
    report = solo.report_for(_spec(), solo.load_week_data(cache, SEASON, WEEK,
                                                          session=OFFLINE),
                             cache_dir=cache)
    basis = report["matchup"].get("range_basis")
    if basis is None:
        pytest.skip("no band this week — the gate fired, nothing to caption")
    assert "%" not in basis, f"the band caption quotes a coverage figure: {basis!r}"
    assert not re.search(r"\b(tested|testing|calibrated|proven|accurate)\b", basis, re.I)
    assert report["matchup"]["you"].get("floor") is not None, \
        "the range itself must still print — only the claim is withheld"


def test_a_team_defense_publishes_no_confidence(tmp_path) -> None:
    """Principle 1: every probability we publish must come from a method we can
    backtest. Nothing backtests this one.

    The frozen method (reports/nflverse-backtest-method.md §3) excludes defenses
    from the graded set and justifies it by calling them "unscoreable", citing
    engine/scoring.py:26-32 and engine/subscriber.py:282-290. Both spans now say
    the opposite — the first is RULE S4, the second calls score_defense — so the
    product went on to score defenses and publish a confidence on them (0.627 on
    the Denver defense in a real 2024 week-10 report) against 0 of 10,041 graded
    DEF calls.

    The projection still prints: a projection is not a probability claim, and the
    slot would otherwise read as broken. Only the numeral is withheld, with the
    reason in the buyer's own words.
    """
    cache = _cache(tmp_path)
    spec = RosterSpec(player_ids=_spec().player_ids + ("DEF-KC", "DEF-SF"),
                      slots=SLOTS + ("DEF",), scoring="ppr")
    report = solo.report_for(spec, solo.load_week_data(cache, SEASON, WEEK,
                                                        session=OFFLINE),
                             cache_dir=cache)
    defense = [s for s in report["lineup"] if s["slot"] == "DEF"][0]
    assert defense["player_id"].startswith("DEF-")
    assert defense["projected"] is not None, "the projection is not the claim"
    assert defense["confidence"] is None, \
        f"a DEF slot published {defense['confidence']} with nothing grading it"
    assert "defenses" in (defense["confidence_gate"] or "")
    # And no OTHER slot is collateral damage — the gate is about defenses only.
    others = [s for s in report["lineup"] if s["slot"] != "DEF"]
    assert any(s["confidence"] is not None for s in others), \
        "the defense gate silenced the rest of the lineup"


def test_flipping_the_defense_gate_needs_its_own_evidence(tmp_path) -> None:
    """The flag is the whole gate, so it is pinned like WIN_PROBABILITY_CALIBRATED.

    A note on the guard it controls, learned by mutation testing rather than by
    reading: the condition also covers the case where the ALTERNATIVE is a
    defense, and that half is currently UNREACHABLE — a defense is eligible only
    at DEF, where the seated player is necessarily a defense too. Deleting it
    breaks no test, and this test does not pretend otherwise. It stays because it
    costs nothing and becomes load-bearing the moment eligibility changes (a
    league that lets a DEF fill a FLEX, say), which is exactly the kind of change
    that would otherwise reopen the hole silently.
    """
    from engine.week_report import DEFENSE_GATE, TEAM_DEFENSE_CONFIDENCE_CALIBRATED
    assert TEAM_DEFENSE_CONFIDENCE_CALIBRATED is False, \
        "flipping this needs passing evidence for the DEF population itself"
    assert "defenses" in DEFENSE_GATE
    # Buyer copy, not operator copy: no version numbers, no module names.
    for leak in ("backtest", "calibrat", "v0.", "DEF-", "engine"):
        assert leak not in DEFENSE_GATE, f"{leak!r} leaked into buyer copy"


def test_the_player_directory_is_never_served_frozen(tmp_path) -> None:
    """players.csv and teams_colors_logos.csv must be fetched with live=True.

    Fetched with live=False, ``ingest.nflverse.fetch`` returns any non-empty
    cached copy unconditionally — so a long-lived cache (an Actions cache, a
    developer's laptop) pins the directory to whatever day it was written. A
    player who signed this week never appears, and the subscriber who rosters
    him is BLOCKED at intake with a paid, undeliverable row. Measured on the
    real asset: one refresh moved it by 17 players.

    The first fix for this deleted the cached files in the cron before each run.
    That worked and was wrong — see the next test.
    """
    import inspect
    import run.solo as solo_module
    from render import player_index

    for module, name in ((solo_module, "load_week_data"),
                         (player_index, "main")):
        source = inspect.getsource(getattr(module, name))
        for asset in ('"players.csv"', '"teams_colors_logos.csv"'):
            call = source.split(asset)[1].split(")")[0]
            assert "live=True" in call, (
                f"{module.__name__}.{name} fetches {asset} without live=True — "
                f"the directory would freeze")


def test_an_nflverse_outage_falls_back_to_cache_rather_than_failing(
        tmp_path) -> None:
    """`fetch` deliberately prefers a stale cached copy to an outage: "stale
    counted data is still a real record of games that were actually played".

    Deleting the cached directory assets before each cron run — the first fix
    for the freezing above — threw exactly that away, so one nflverse outage on
    a Tuesday meant a cold cache and NO REPORTS FOR ANYONE. live=True keeps both
    halves: it revalidates on the 6h window AND still falls back.
    """
    import requests

    from ingest.nflverse import fetch

    cache = _cache(tmp_path)
    stale = cache / "players.csv"
    assert stale.is_file(), "the fixture has no directory asset to fall back to"
    before = stale.read_bytes()

    class _Down:
        def get(self, url, **_kwargs):
            raise requests.ConnectionError("simulated nflverse outage")

    import os
    os.utime(stale, (0, 0))          # force live=True past its 6h window
    got = fetch("players", "players.csv", cache, live=True, session=_Down())
    assert got.read_bytes() == before, "an outage lost the cached directory"


def test_an_id_the_directory_does_not_know_fails_loudly(tmp_path) -> None:
    """A ref decodes to ids, not to players. An unknown id would render as a
    blank row in a report somebody paid for."""
    cache = _cache(tmp_path)
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    spec = RosterSpec(player_ids=(_pid(1), "00-9999999") + tuple(
        _pid(i) for i in range(2, len(ROSTER) + 1)), slots=SLOTS, scoring="ppr")
    with pytest.raises(solo.SoloError, match="00-9999999"):
        solo.report_for(spec, data, cache_dir=cache)


def test_the_defense_gap_fires_only_when_a_defense_really_has_no_number(
        tmp_path) -> None:
    """The gap said "team defenses are not scored yet" for every defense in the
    lineup — while the same run printed a projection and a confidence for one.
    A gap list that reports a missing feature the run just used is worse than
    no gap list."""
    cache = _cache(tmp_path)
    spec = RosterSpec(player_ids=_spec().player_ids + ("DEF-KC",),
                      slots=SLOTS + ("DEF",), scoring="ppr")
    report = solo.report_for(spec, solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE),
                             cache_dir=cache)
    defense = [s for s in report["lineup"] if s["slot"] == "DEF"][0]
    assert defense["projected"] is not None
    assert not [g for g in report["meta"]["gaps"] if g["field"] == "team_defense"]


# --------------------------------------------------------------------- #
# what the subscriber actually receives
# --------------------------------------------------------------------- #

def _rendered(tmp_path) -> tuple[dict, str, str, str]:
    from render.email import render_email
    from render.report import TEMPLATE_PATH, render
    from run.week import text_summary
    cache = _cache(tmp_path)
    report = solo.report_for(_spec(), solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE),
                             cache_dir=cache)
    return (report, render(report, TEMPLATE_PATH.read_text(encoding="utf-8")),
            render_email(report), text_summary(report))


def test_the_plain_text_summary_survives_a_solo_report(tmp_path) -> None:
    """It goes in every email as the text half, and it had never been run
    against a solo report: it printed "Your Team vs None" and then raised
    KeyError on matchup['rival'] before anything could be sent."""
    _report, _html, _email, text = _rendered(tmp_path)
    assert "vs None" not in text and " None" not in text
    assert "YOUR WEEK" in text and "MATCHUP" not in text
    assert "projected" in text


def test_every_surface_credits_nflverse_and_not_sleeper(tmp_path) -> None:
    """RULE N1: CC-BY-4.0 grants commercial use IN EXCHANGE FOR attribution, so
    this is a licence term. ingest/nflverse.py says it is "rendered on every
    report and every public page" — and no report rendered it at all. All three
    surfaces printed the Sleeper line instead, crediting a source the run never
    touched while omitting the one the grant depends on."""
    from ingest.nflverse import ATTRIBUTION
    from render.report import esc
    _report, html, email, text = _rendered(tmp_path)
    for name, doc in (("html", esc(ATTRIBUTION) in html and ATTRIBUTION),
                      ("email", esc(ATTRIBUTION) in email and ATTRIBUTION),
                      ("text", text)):
        assert doc, f"{name} ships without the licence term"
        assert "record on Sleeper" not in doc, f"{name} credits the wrong source"


def test_a_league_report_keeps_the_sleeper_disclaimer() -> None:
    """The historical demo and the backtest still run on the league record they
    were always built from — swapping their footer would be its own false
    claim."""
    from render.report import SLEEPER_LINE, source_line
    assert source_line({"solo": True}) != SLEEPER_LINE
    assert source_line({}) == SLEEPER_LINE
    assert source_line({"solo": False}) == SLEEPER_LINE
