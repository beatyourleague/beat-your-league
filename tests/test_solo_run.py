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
ROSTER = [("Star QB", "QB", "KC"), ("Bell Cow", "RB", "SF"),
          ("Committee RB", "RB", "DET"), ("Alpha WR", "WR", "CIN"),
          ("Slot WR", "WR", "DET"), ("Starting TE", "TE", "SF"),
          ("Deep WR", "WR", "DEN"), ("Bench RB", "RB", "KC")]
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
    directory = PlayerDirectory([Player(_pid(1), "Star QB", "QB", "KC")])
    assert solo._statuses(directory, None) is None
    empty = InjuryWeek(season=SEASON, week=9, by_gsis={}, teams={})
    assert solo._statuses(directory, empty) is None

    availability = solo._availability(_cache(tmp_path, injuries=False),
                                      SEASON, WEEK, directory, session=OFFLINE)
    assert not availability.has_snapshot
    assert availability.classify(_pid(1)).status is Status.UNKNOWN


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
