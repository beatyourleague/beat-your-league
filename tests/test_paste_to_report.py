"""A roster pasted from each app becomes a working report.

tests/test_intake.py checks the reader. This walks the whole road a buyer's
paste travels: the browser's own reader (site/join/roster.js), the reference it
builds, the decode the intake runs, the real report, and the email. Each piece
was tested on its own; nothing held the joins together.

The copies are written from the formats the app pages describe, not captured
from a logged-in account, so they prove the road, not each app's exact markup.
Skips on a fresh checkout, which has no cached season to build from.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "site" / "join" / "roster.js"
INDEX = ROOT / "site" / "join" / "players.json"
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
ROSTER = ["Josh Allen", "Saquon Barkley", "Bijan Robinson", "Ja'Marr Chase",
          "Amon-Ra St. Brown", "George Kittle", "Marvin Harrison Jr.", "Jake Bates",
          "Denver Broncos", "Sam LaPorta", "Kenneth Walker III", "D.J. Moore",
          "T.J. Hockenson", "De'Von Achane", "C.J. Stroud"]
NICK = {"Denver Broncos": "Broncos"}


def _players() -> list[tuple[str, str, str, str]]:
    rows = {r[0].lower().replace(".", ""): r for r in json.loads(INDEX.read_text())["players"]}
    out = []
    for index, name in enumerate(ROSTER):
        row = rows[name.lower().replace(".", "")]
        out.append((SLOTS[index] if index < len(SLOTS) else "BN", row[0], row[2], row[3] or ""))
    return out


def _title(code: str) -> str:
    return code.capitalize() if len(code) == 3 else code


def espn_table(rows) -> str:
    out = ["STARTERS\tNFL WEEK 8\t2026 SEASON", "SLOT", "PLAYER", "OPP", "STATUS", "PROJ", "SCORE"]
    for index, (slot, name, pos, team) in enumerate(rows):
        if index == 9:
            out += ["TOTALS", "114.7", "0.0"]
        out += ["Bench" if slot == "BN" else "D/ST" if slot == "DEF" else slot, ""]
        out += ([NICK[name], team, "D/ST"] if pos == "DEF"
                else [name] + (["Q"] if index == 2 else []) + [team, pos])
        out += ["@JAX", "Sun 1:00 PM", f"{10 + index}.1", "--", "7th"]
    return "\n".join(out)


def espn_lines(rows) -> str:
    out: list[str] = []
    for _slot, name, pos, team in rows:
        out += ([f"{NICK[name]} D/ST", "D/ST", "NYJ"] if pos == "DEF"
                else [name, _title(team), pos, "@HOU"])
    return "\n".join(out)


def yahoo(rows) -> str:
    out: list[str] = []
    for index, (slot, name, pos, team) in enumerate(rows):
        out += [{"FLEX": "W/R/T"}.get(slot, slot), name, f"{_title(team)} - {pos}"]
        out += ["Q"] if index == 1 else ["O"] if index == 4 else []
    return "\n".join(out)


def yahoo_table(rows) -> str:
    """The desktop copy, its header row included: "Offense" came back as a player."""
    out = ["Pos\tOffense\tOpp\tStatus\tFan Pts\tProj"]
    for index, (slot, name, pos, team) in enumerate(rows):
        label = {"FLEX": "W/R/T"}.get(slot, slot)
        out.append(f"{label}\t{name} {_title(team)} - {pos}\tvs Mia\t\t0.00\t{12 + index}.31")
    return "\n".join(out)


def sleeper(rows) -> str:
    out: list[str] = []
    for _slot, name, pos, team in rows:
        out += [NICK[name], f"DEF - {team}"] if pos == "DEF" else [name, f"{pos} - {team}"]
    return "\n".join(out)


def cbs(rows) -> str:
    out = []
    for _slot, name, pos, team in rows:
        first, last = name.split(" ", 1)
        out.append(f"{NICK[name]} D/ST" if pos == "DEF" else f"{last}, {first} {pos} {team}")
    return "\n".join(out)


def nfl(rows) -> str:
    return "\n".join(f"{pos} {name} {team} vs. MIA Sun 1:00 PM  {10 + i}.3"
                     for i, (_s, name, pos, team) in enumerate(rows))


def whole_page(rows) -> str:
    """Select-all on a page: the app's chrome around the roster."""
    return ("My Team\nMatchup\nPlayers & Stats\nStandings\nEdit Lineup\nStarters\n" + yahoo(rows)
            + "\nFinal W 24-17\nAdd Player\nDrop\nTrade\nEmpty\nWaiver Wire")


FORMATS = {"espn-table": espn_table, "espn-lines": espn_lines, "yahoo": yahoo,
           "yahoo-table": yahoo_table, "sleeper": sleeper, "cbs": cbs, "nfl": nfl,
           "whole-page": whole_page}


def _read(text: str, scoring: str, size: int) -> dict:
    script = (f"const R=require({str(JS)!r});"
              "globalThis.btoa=(s)=>Buffer.from(s,'binary').toString('base64');"
              f"const d=R.buildDirectory(JSON.parse(require('fs').readFileSync({str(INDEX)!r},'utf8')));"
              f"const ms=R.resolveAll(d,{json.dumps(text)});"
              "const held=ms.filter(m=>!m.player).map(m=>m.typed);"
              "const ref=held.length?null:R.encodeRoster('season',"
              f"{json.dumps(scoring)},{json.dumps(SLOTS)},ms.map(m=>m.player.id),{size});"
              "console.log(JSON.stringify({names:ms.filter(m=>m.player).map(m=>m.player.name),held,ref}))")
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def week():
    from run.solo import CACHE_DIR, SoloError, load_week_data
    if shutil.which("node") is None or not INDEX.is_file():
        pytest.skip("needs node and site/join/players.json")
    if not any(Path(CACHE_DIR).glob("stats_player_week_*.csv")):
        pytest.skip("no cached nflverse data on a fresh checkout")
    try:
        return load_week_data(CACHE_DIR)
    except (SoloError, OSError) as exc:
        pytest.skip(f"no week to build: {exc}")


@pytest.mark.parametrize("app", sorted(FORMATS))
def test_a_paste_from_each_app_becomes_a_report_for_that_roster(app, week) -> None:
    from render.email import render_email, subject_for, text_summary
    from run.refs import decode_roster
    from run.solo import report_for, spec_from_ref
    rows = _players()
    read = _read(FORMATS[app](rows), "half_ppr", 10)
    assert read["held"] == [], f"{app}: the buyer would be asked to fix these"
    assert sorted(read["names"]) == sorted(name for _s, name, _p, _t in rows), app
    ref = decode_roster(read["ref"])
    assert (ref.scoring, int(ref.league_size), list(ref.slots)) == ("half_ppr", 10, SLOTS)
    report = report_for(spec_from_ref(ref), week, league_size=10)
    names = {name for _s, name, _p, _t in rows}
    assert len(report["lineup"]) == len(SLOTS)
    assert all(slot["player_name"] in names for slot in report["lineup"]), app
    text = text_summary(report)
    assert "Your Lineup, Decided".upper() in text
    assert not re.search(r"\b(?:None|nan|undefined)\b", text), app
    assert "Your Lineup, Decided" in render_email(report)
    assert re.search(r"Week \d+", subject_for(report))


@pytest.mark.parametrize("app", sorted(FORMATS))
def test_the_operator_tool_reads_what_the_join_page_reads(app) -> None:
    """run.trial promises "positions, bye weeks, app junk and all" and read one
    line at a time, so it refused every app whose copy spreads a player over
    several lines: "'Buf - QB' — no current player by that name"."""
    from run.solo import CACHE_DIR, load_week_data
    from run.trial import resolve_roster
    if not any(Path(CACHE_DIR).glob("stats_player_week_*.csv")):
        pytest.skip("no cached nflverse data on a fresh checkout")
    directory = load_week_data(CACHE_DIR).directory
    assert len(resolve_roster(FORMATS[app](_players()), directory)) == len(ROSTER), app


def test_both_readers_ignore_the_same_page_words() -> None:
    """A list kept in two languages drifts; a word in only one means the page
    says "looks right" about a roster the intake reads differently."""
    from engine.roster import _PAGE_WORDS
    source = JS.read_text(encoding="utf-8")
    words = re.search(r"const PAGE_WORDS = new Set\(`(.*?)`", source, re.S).group(1).split()
    assert set(words) == set(_PAGE_WORDS) and len(words) == len(_PAGE_WORDS)
    assert all(re.fullmatch(r"[a-z]+", word) for word in words), "normalize() keeps letters only"


def test_no_page_word_is_a_real_players_name() -> None:
    """A page word is dropped without asking, so it may never be somebody: the
    guard against a rookie named Close arriving in next week's directory."""
    from engine.roster import _PAGE_WORDS, normalize
    if not INDEX.is_file():
        pytest.skip("players.json not built")
    keys = set()
    for row in json.loads(INDEX.read_text())["players"]:
        keys.add(normalize(row[0]))
        keys.update(normalize(part) for part in row[0].split())
    assert not _PAGE_WORDS & keys


def test_a_line_with_a_name_in_it_is_never_a_page_word() -> None:
    """Whole lines only: page furniture beside a player must still reach the
    reader, and a line we don't recognise must still come back to the buyer."""
    from engine.roster import _is_blank
    assert _is_blank("Empty") and _is_blank("Set Lineup")
    assert not _is_blank("Empty Josh Allen")
    assert not _is_blank("Josh Allenn")
    assert not _is_blank("Кириллица")
