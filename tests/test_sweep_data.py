"""The data sweep (Nov 3 2026): what the live site and the repo say must be
the real data, never a stale clock, a made-up card or a partial week.

Each test names its finding and the reproduction it pins.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from run import launch_check as lc
from run import solo

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


# --------------------------------------------------------------------- #
# DATA-01: a page with no projected total says so in its clock
# --------------------------------------------------------------------- #

def test_the_committed_clock_matches_the_live_page() -> None:
    """Reproduced: site/this-week.html opened on "Heads up: no projected
    total" while site/week.json, written before write_week_json learned the
    key, had no ``total`` — so the landing linked it as this week's report."""
    week = json.loads((SITE / "week.json").read_text(encoding="utf-8"))
    gate = lc.total_gate(week)
    assert gate.status == "PASS", gate.detail


def test_the_launch_check_fails_a_clock_that_hides_a_missing_total() -> None:
    page = "<p>Heads up: no projected total — your QB can't play this week.</p>"
    assert lc.total_gate({"odds": 3}, page).status == "FAIL"
    assert lc.total_gate({"odds": 3, "total": False}, page).status == "PASS"
    assert lc.total_gate({"odds": 3}, "<p>Projected 112.4</p>").status == "PASS"
    assert "total_gate(w, site=site)" in __import__("inspect").getsource(lc.check_week_json)


# --------------------------------------------------------------------- #
# DATA-02: "this week's" only until the week's last game
# --------------------------------------------------------------------- #

def _footer(clock: dict) -> bool:
    """Run site/footer.js under node against ``clock``; True when it reveals
    the "This week's report" link."""
    script = """
const link = { hidden: true };
global.document = { querySelectorAll: () => [link] };
global.window = { fetch: true };
global.fetch = () => Promise.resolve({ ok: true, json: () => (CLOCK) });
SCRIPT
setTimeout(() => console.log(JSON.stringify(!link.hidden)), 50);
""".replace("CLOCK", json.dumps(clock)).replace(
        "SCRIPT", (SITE / "footer.js").read_text(encoding="utf-8"))
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_footer_link_waits_for_the_weeks_last_game() -> None:
    """The Tuesday after Monday night: lands_on (Wednesday) still ahead, the
    week's games over. The footer linked the page as "this week's report"
    with "Set this lineup before this week's first kickoff" on it."""
    good = {"season": "2026", "week": 8, "last_week": 18, "lands_on": "2999-01-06",
            "week_ends": "2999-01-04", "odds": 3, "closest_call": True, "cards": True,
            "phase": "season"}
    assert _footer(good) is True
    assert _footer({**good, "week_ends": "2000-01-03"}) is False   # games played
    assert _footer({k: v for k, v in good.items() if k != "week_ends"}) is False
    assert _footer({**good, "total": False}) is False              # DATA-01


def _schedule(tmp_path: Path, games) -> Path:
    cache = tmp_path / "nflverse"
    cache.mkdir(parents=True, exist_ok=True)
    fields = ["season", "game_type", "week", "gameday", "gametime", "away_team",
              "home_team", "away_score", "home_score"]
    with (cache / "games.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for week, day, clock, away, home, scored in games:
            writer.writerow({"season": "2026", "game_type": "REG", "week": week,
                             "gameday": day, "gametime": clock, "away_team": away,
                             "home_team": home, "away_score": 17 if scored else "",
                             "home_score": 24 if scored else ""})
    return cache


GAMES = [(7, "2026-10-22", "20:15", "NE", "CHI", True),
         (7, "2026-10-25", "13:00", "SF", "ATL", True),
         (7, "2026-10-26", "20:15", "DAL", "PHI", True),
         (8, "2026-10-29", "20:15", "NE", "SF", True),
         (8, "2026-11-01", "13:00", "DAL", "ATL", True),
         (8, "2026-11-02", "20:15", "CHI", "SEA", False)]


def test_the_week_ends_on_its_last_regular_game(tmp_path) -> None:
    cache = _schedule(tmp_path, GAMES)
    assert solo.week_end_day(cache, "2026", 8, live=False) == "2026-11-02"
    assert solo.week_end_day(cache, "2026", 7, live=False) == "2026-10-26"
    assert solo.week_end_day(cache, "2026", 9, live=False) is None


# --------------------------------------------------------------------- #
# DATA-05: no made-up graded card in the folder posts come from
# --------------------------------------------------------------------- #

def test_no_committed_card_is_a_design_preview() -> None:
    """content/cards held "START De'Von Achane over Breece Hall · 64% · HIT ·
    Graded against the real box score", a 2026 Week 1 call no ledger holds,
    whose real box score (Achane 10.6, Hall 19.8) was a miss."""
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "content"],
                             capture_output=True, text=True, check=True).stdout.split()
    for name in tracked:
        if name.endswith(".svg"):
            text = (ROOT / name).read_text(encoding="utf-8")
            assert "DESIGN PREVIEW" not in text and "SAMPLE" not in name, name


# --------------------------------------------------------------------- #
# DATA-06: "through Week N" means every game of Week N is in
# --------------------------------------------------------------------- #

MONDAY_NIGHT_OUT = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _rows(*teams: str) -> dict:
    return {f"00-{t}": {"team": t} for t in teams}


def test_a_week_with_monday_night_out_is_not_complete(tmp_path) -> None:
    """Reproduced: the rookie report said "2026 games are through Week 8" with
    CHI@SEA unplayed and no CHI or SEA rows, because it took the highest week
    with any row."""
    cache = _schedule(tmp_path, GAMES)
    weekly = {7: _rows("NE", "CHI", "SF", "ATL", "DAL", "PHI"),
              8: _rows("NE", "SF", "DAL", "ATL")}
    assert solo.last_complete_week(cache, "2026", weekly, now=MONDAY_NIGHT_OUT) == 7
    # Scored but no stat rows yet: still not in.
    scored = _schedule(tmp_path / "scored", [(*g[:5], True) for g in GAMES])
    assert solo.last_complete_week(scored, "2026", weekly, now=LATER) == 7
    weekly[8].update(_rows("CHI", "SEA"))
    assert solo.last_complete_week(scored, "2026", weekly, now=LATER) == 8


def test_a_relocated_franchises_old_schedule_code_still_counts_as_in(tmp_path) -> None:
    """Reproduced on the real archive: the schedule says OAK/SD/STL where the
    stat rows say LV/LAC/LA, so last_complete_week answered None for 2014 and
    2016 and Week 6 for 2019, and the rookie report for those classes printed
    none of their games (DATA-06's rule, re-checked). Schedule codes go
    through engine.context.team_code, as the context model's do."""
    games = [(1, "2016-09-11", "13:00", "SD", "KC", True),
             (1, "2016-09-12", "22:20", "LA", "SF", True),
             (2, "2016-09-18", "13:00", "OAK", "ATL", True)]
    cache = _schedule(tmp_path, games)
    weekly = {1: _rows("LAC", "KC", "LA", "SF"), 2: _rows("LV", "ATL")}
    assert solo.last_complete_week(cache, "2026", weekly, now=LATER) == 2
    weekly[2] = _rows("ATL")                       # the Raiders' rows missing
    assert solo.last_complete_week(cache, "2026", weekly, now=LATER) == 1


def test_the_rookie_report_counts_only_complete_weeks(tmp_path, monkeypatch) -> None:
    import ingest.nflverse as nflverse
    import render.rookies as rookies
    cache = _schedule(tmp_path, GAMES)
    players = tmp_path / "players.csv"
    players.write_text("gsis_id\n", encoding="utf-8")
    current = {7: _rows("NE", "CHI", "SF", "ATL", "DAL", "PHI"),
               8: _rows("NE", "SF", "DAL", "ATL")}
    monkeypatch.setattr(nflverse, "fetch", lambda *a, **k: players)
    monkeypatch.setattr(nflverse, "season_rows",
                        lambda _c, season, **k: current if season == "2026" else {})
    monkeypatch.setattr(rookies, "load_players", lambda _p: [])
    real = solo.last_complete_week
    monkeypatch.setattr(solo, "last_complete_week",
                        lambda c, s, w, now=None: real(c, s, w, now=MONDAY_NIGHT_OUT))
    seen = {}
    monkeypatch.setattr(rookies, "build", lambda *a, **k: seen.update(k) or {})
    rookies.load_report(cache, 2026)
    assert sorted(seen["current"]) == [7]


# --------------------------------------------------------------------- #
# DATA-08: the public stop list describes its own codes truly
# --------------------------------------------------------------------- #

def test_the_committed_stop_list_header_is_the_keyed_one() -> None:
    """The committed file said its entries were sha256 digests (guessable by
    hashing candidate addresses); they are HMACs under LOG_SECRET."""
    from run.suppress import HEADER
    text = (ROOT / "data" / "processed" / "suppressed.txt").read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert "sha256" not in text
