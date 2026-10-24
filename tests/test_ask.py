"""`make ask` (run/ask.py): the product's own answer to "A or B this week?".

Replies on X are public statements with no report around them, so the
properties worth testing are the ones where being wrong would put something
on the record: a reply about the wrong player, a % the report would not have
printed, a % printed without being recorded, a number that disagrees with the
one a subscriber was sent for the same pair.

Offline, on the fixture cache tests/test_solo_run.py builds (no network: a
fetch the fixture did not provide fails the test).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

import run.ask as ask
import run.solo as solo
from engine.ledger import extract_published_calls, load_ledger
from engine.roster import Player, PlayerDirectory
from test_solo_run import OFFLINE, SEASON, WEEK, _cache, _pid, _spec, _t1_spec

BEFORE_KICKOFF = "2024-09-10T12:00:00Z"     # the fixture's week 6 is 2024-09-12
AFTER_KICKOFF = "2024-09-13T12:00:00Z"
PERCENT = re.compile(r"\d+%")


def _run(cache: Path, processed: Path, *names: str, publish: bool = False,
         now: str = BEFORE_KICKOFF, week: int = WEEK, extra=()) -> tuple[int, str, str]:
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    argv = [*names, "--season", SEASON, "--week", str(week), "--cache", str(cache),
            "--processed-dir", str(processed), "--now", now, *extra]
    if publish:
        argv.append("--publish")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ask.main(argv, session=OFFLINE)
    return code, out.getvalue(), err.getvalue()


def _rows(processed: Path) -> list[dict]:
    return [json.loads(line) for path in sorted(processed.rglob("calls.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines() if line]


# --------------------------------------------------------------------- #
# RULE R3 — the name, before anything else
# --------------------------------------------------------------------- #

def test_an_ambiguous_name_stops_and_names_every_candidate(tmp_path) -> None:
    """A second "Bell Cow" joins the directory. Resolving to either one would
    print — and with --publish, record — a call about a player the owner may
    not have meant, so the run stops, names both with position and team, and
    writes nothing."""
    cache = _cache(tmp_path)
    players = cache / "players.csv"
    with players.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow([_pid(99), "Bell Cow", "WR",
                                     str(int(SEASON) - 1), "BAL"])
    processed = tmp_path / "processed"
    code, out, err = _run(cache, processed, "Bell Cow", "Hank Benchman", publish=True)
    assert code == 2
    assert "Bell Cow (RB, SF)" in err and "Bell Cow (WR, BAL)" in err
    assert not PERCENT.search(out + err)
    assert not processed.exists(), "an ambiguous name wrote to the public record"


def test_an_unknown_name_stops_and_says_which(tmp_path) -> None:
    code, out, err = _run(_cache(tmp_path), tmp_path / "p", "Nobody Atall",
                          "Bell Cow")
    assert code == 2 and '"Nobody Atall"' in err and "Bell Cow" not in err
    assert out == ""


def test_the_same_player_twice_is_not_a_question(tmp_path) -> None:
    code, _out, err = _run(_cache(tmp_path), tmp_path / "p", "Bell Cow", "bell cow")
    assert code == 2 and "two different players" in err


def test_a_one_letter_twin_is_pointed_out() -> None:
    """Bijan and Brian Robinson: same position, two letters apart. The join
    page shows the twin inline; the reply tool says so under the facts."""
    bijan = Player("00-0000001", "Bijan Robinson", "RB", "ATL")
    brian = Player("00-0000002", "Brian Robinson", "RB", "SF")
    other = Player("00-0000003", "Brian Robinsen", "WR", "SF")      # not an RB
    directory = PlayerDirectory([bijan, brian, other])
    assert ask.lookalikes(directory, bijan) == [brian]


# --------------------------------------------------------------------- #
# the facts, and the % only under the report's own gate
# --------------------------------------------------------------------- #

def test_the_facts_print_without_publishing_and_the_percent_does_not(tmp_path) -> None:
    """Without --publish the answer is the facts and the side the report
    takes; the number is withheld, because a % posted in public is a
    published call and an unrecorded one is principle 2 broken in public."""
    processed = tmp_path / "processed"
    code, out, _err = _run(_cache(tmp_path), processed, "Hank Benchman", "Bell Cow")
    assert code == 0
    for fact in ("Projection", "Last three games:", "a game (last 4 games)",
                 "Status       active", "at SF"):
        assert fact in out, fact
    assert "starts Hank Benchman over Bell Cow" in out
    assert not PERCENT.search(out), "a % printed without being recorded"
    assert "--publish" in out
    assert not processed.exists()


def test_a_gated_pair_prints_no_percent_even_when_publishing(tmp_path) -> None:
    """Gabe Fielder is designated Questionable on week 5's report — the one a
    week-6 report reads. The report prints no number on that head-to-head, so
    neither does a reply, and nothing reaches the record."""
    processed = tmp_path / "processed"
    code, out, _err = _run(_cache(tmp_path), processed, "Dre Wideout",
                           "Gabe Fielder", publish=True)
    assert code == 0
    assert not PERCENT.search(out)
    assert "No % — availability in doubt (designated Questionable)" in out
    assert not _rows(processed)


@pytest.mark.parametrize("names, reason", [
    (("Dre Wideout", "Frank Tighten"), "Frank Tighten can't play this week: designated Out"),
    (("Aaron Armstrong", "Dre Wideout"), "never compete for one slot"),
])
def test_no_call_says_why_in_plain_words(tmp_path, names, reason) -> None:
    """A receiver and a tight end share FLEX, so the reason is the designation;
    a quarterback and a receiver share nothing outside superflex."""
    cache = _cache(tmp_path)
    with (cache / f"injuries_{SEASON}.csv").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow([SEASON, WEEK - 1, _pid(6), "SF", "Out"])
    code, out, _err = _run(cache, tmp_path / "p", *names, publish=True)
    assert code == 0 and reason in out and not PERCENT.search(out)


def _deepen_the_field(cache: Path, extra: int = 40) -> None:
    """Add ``extra`` low-scoring running backs, so the rosterable field is
    deeper than one slot's worth. The base fixture holds ~16 per position,
    fewer than any league's depth, which made the field's lineup shape
    invisible to every test; real directories hold hundreds."""
    def append(path: Path, rows: list[dict]) -> None:
        with path.open(encoding="utf-8", newline="") as handle:
            columns = next(csv.reader(handle))
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, restval="0")
            writer.writerows(rows)
    ids = [_pid(100 + i) for i in range(extra)]
    append(cache / "players.csv",
           [{"gsis_id": pid, "display_name": f"Depth {i}", "position": "RB",
             "last_season": str(int(SEASON) - 1), "latest_team": "BAL"}
            for i, pid in enumerate(ids)])
    for which in (SEASON, str(int(SEASON) - 1)):
        append(cache / f"stats_player_week_{which}.csv",
               [{"player_id": pid, "season": which, "week": week,
                 "season_type": "REG", "position": "RB", "team": "BAL",
                 "player_display_name": f"Depth {i}", "rushing_yards": i % 7,
                 "carries": 2}
                for i, pid in enumerate(ids) for week in range(1, 6)])


@pytest.mark.parametrize("week, spec, size, deep", [
    (WEEK, _spec, 12, False), (WEEK, _t1_spec, 12, False), (2, _t1_spec, 12, False),
    (WEEK, _spec, 8, True)])
def test_ask_prints_what_a_subscriber_report_prints(tmp_path, week, spec, size,
                                                    deep) -> None:
    """The reply quotes the PRODUCT, so for every call a subscriber's report
    publishes, the same pair asked here gets the same side and the same
    number: the anchor (week 6), the early-season seed (week 2, standard
    lineup), the recalibration, the gate, and a field as deep as a full
    lineup's (the last case, where depth is finally smaller than the
    population). run/ask.py mirrors run.solo's model choice line for line
    because run/solo.py exposes no single function for it; this is what
    catches the two drifting apart."""
    cache = _cache(tmp_path)
    if deep:
        _deepen_the_field(cache)
    data = solo.load_week_data(cache, SEASON, week, session=OFFLINE)
    report = solo.report_for(spec(), data, league_size=size, cache_dir=cache)
    published = [s for s in report["lineup"] if s["confidence"] is not None]
    assert published, "the fixture produced no call to compare against"
    players = {p.player_id: p for p in data.directory.players}
    for slot in published:
        call = ask.head_to_head(data, players[slot["alternative_id"]],
                                players[slot["player_id"]], "ppr", size)
        assert call.pick is not None and call.pick.confidence is not None
        assert call.pick.player_id == slot["player_id"]
        assert round(call.pick.confidence, 3) == slot["confidence"], slot["slot"]
        assert call.league_id == report["meta"]["league_id"]


# --------------------------------------------------------------------- #
# publishing — principle 2
# --------------------------------------------------------------------- #

def test_publish_records_exactly_one_row_a_subscriber_report_would(tmp_path) -> None:
    """--publish writes ONE row, into the store, under the id and in the shape
    a subscriber's report records the same call — so Monday grades it, and a
    subscriber who was sent the same head-to-head adds no second row."""
    cache = _cache(tmp_path)
    processed = tmp_path / "processed"
    code, out, _err = _run(cache, processed, "Hank Benchman", "Bell Cow",
                           publish=True)
    assert code == 0
    [row] = _rows(processed)
    assert (row["league_id"], row["week"], row["slot"], row["pick_name"],
            row["over_name"], row["source"], row["status"]) == (
        f"typed-ppr-12-{SEASON}", WEEK, "RB", "Hank Benchman", "Bell Cow",
        "slot", "pending")
    assert f"{round(row['confidence'] * 100)}%" in out
    data = solo.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    subscriber = extract_published_calls(solo.report_for(_spec(), data, cache_dir=cache))
    assert row["call_id"] in {c.call_id for c in subscriber}

    # Asked again, in the other order: the record already holds it.
    code, again, _err = _run(cache, processed, "Bell Cow", "Hank Benchman",
                             publish=True)
    assert code == 0 and "Already on the public record" in again
    assert len(_rows(processed)) == 1


def test_a_pair_already_on_the_record_is_quoted_as_recorded(tmp_path) -> None:
    """A subscriber's report put the same two players on the record this week
    at a DIFFERENT slot. A second row would count one game twice, and a reply
    quoting a fresh number would be a second answer to one question — so the
    recorded number is quoted and nothing is written."""
    from engine.ledger import LedgerCall, ledger_path, record_calls
    processed = tmp_path / "processed"
    record_calls(ledger_path(processed, f"typed-ppr-12-{SEASON}"), [LedgerCall(
        call_id="0123456789abcdef", source="slot", league_id=f"typed-ppr-12-{SEASON}",
        season=SEASON, week=WEEK, roster_id=1, slot="FLEX", pick_id=_pid(8),
        pick_name="Hank Benchman", over_id=_pid(2), over_name="Bell Cow",
        confidence=0.6, recorded_at="2024-09-10T08:00:00+00:00")])
    code, out, _err = _run(_cache(tmp_path), processed, "Hank Benchman",
                           "Bell Cow", publish=True)
    assert code == 0
    assert "At FLEX: start Hank Benchman over Bell Cow — 60%" in out
    assert len(load_ledger(ledger_path(processed, f"typed-ppr-12-{SEASON}"))) == 1


def test_nothing_is_published_once_the_week_has_kicked_off(tmp_path) -> None:
    """The number is a prediction on the Tuesday information set. Recorded
    after kickoff it would be a "prediction" about games underway — the one
    thing the ledger exists to make impossible — so the run refuses, prints no
    %, and exits non-zero so the refusal is never mistaken for done."""
    processed = tmp_path / "processed"
    code, out, _err = _run(_cache(tmp_path), processed, "Hank Benchman",
                           "Bell Cow", publish=True, now=AFTER_KICKOFF)
    assert code == 1 and "has kicked off" in out
    assert not PERCENT.search(out) and not _rows(processed)


def test_nothing_is_published_for_a_week_whose_previous_week_is_unplayed(tmp_path) -> None:
    """``--week 7`` before week 6 is over: week 7 has not kicked off, so the
    kickoff check alone let it through, and the record would hold a week-7
    "prediction" built without week 6's games, on a half-published injury
    report — a number no subscriber is ever sent. Only the window a Tuesday
    report covers may publish."""
    processed = tmp_path / "processed"
    code, out, err = _run(_cache(tmp_path), processed, "Hank Benchman",
                          "Bell Cow", publish=True, week=WEEK + 1)
    # Since pre-launch review F2 the week's data refuses to load at all: every
    # game of the week projected from must be in (run.solo
    # .assert_week_is_complete), so nothing is built, printed or recorded.
    assert code != 0 and f"week {WEEK}'s box scores are not all in" in err
    assert not PERCENT.search(out) and not _rows(processed)


def test_a_week_is_over_only_when_every_game_is_final() -> None:
    """Thursday's game final and Sunday's not is the exact state in which a
    next-week number would be built on half a week."""
    played = {"season": "2026", "week": "6", "home_score": "24", "away_score": "17"}
    pending = {"season": "2026", "week": "6", "home_score": "", "away_score": ""}
    assert ask.previous_week_played([played, played], "2026", 7)
    assert not ask.previous_week_played([played, pending], "2026", 7)
    assert not ask.previous_week_played([], "2026", 7)          # unreadable: no
    assert ask.previous_week_played([], "2026", 1)               # week 1 has none


def test_the_store_follows_the_scoring_and_league_size(tmp_path) -> None:
    """The preset and the size are part of a call's identity (engine/
    subscriber.py build_season): a half-PPR 10-team reply lands in that store,
    never in the PPR/12 one."""
    processed = tmp_path / "processed"
    code, _out, _err = _run(_cache(tmp_path), processed, "Hank Benchman",
                            "Bell Cow", publish=True,
                            extra=("--scoring", "half_ppr", "--size", "10"))
    assert code == 0
    assert {r["league_id"] for r in _rows(processed)} == {f"typed-half_ppr-10-{SEASON}"}


# --------------------------------------------------------------------- #
# what it may read and say
# --------------------------------------------------------------------- #

def test_the_opponent_line_never_cites_the_market() -> None:
    """The schedule row carries spreads, totals and moneylines. The market is
    a model input only — no surface cites a line — so the opponent line reads
    the teams, the day and the kickoff and nothing else."""
    row = {"season": "2026", "week": "6", "home_team": "ATL", "away_team": "CHI",
           "weekday": "Sunday", "gametime": "13:00", "location": "Home",
           "spread_line": "-1.5", "total_line": "50.5", "home_moneyline": "-105"}
    assert ask.opponent([row], "2026", 6, "CHI") == "at ATL, Sun 1:00 PM ET"
    assert ask.opponent([row], "2026", 6, "ATL") == "vs CHI, Sun 1:00 PM ET"
    assert ask.opponent([row], "2026", 6, "DET") is None          # a bye
    neutral = {**row, "location": "Neutral", "gametime": "09:30"}
    assert ask.opponent([neutral], "2026", 6, "CHI") == "vs ATL, Sun 9:30 AM ET"


def test_the_reply_tool_cannot_reach_a_subscriber_or_sleeper() -> None:
    """It answers about two players from public data. A subscriber's roster,
    registry or report is none of its business, and neither is a league
    platform. Import reachability, not a grep: a dependency comes back through
    something it imports."""
    from test_posts import _reachable
    modules = _reachable("run.ask")
    for forbidden in ("run.rosters", "run.registry", "run.tuesday", "run.intake",
                      "run.batch", "run.delivery", "ingest.sleeper", "ingest.pull"):
        assert forbidden not in modules, forbidden


def test_make_ask_runs_it() -> None:
    makefile = (Path(__file__).resolve().parent.parent / "Makefile").read_text(
        encoding="utf-8")
    assert re.search(r"^ask:\n\t\$\(PY\) -m run\.ask \"\$\(A\)\" \"\$\(B\)\"", makefile,
                     re.M), "make ask is missing or does not pass A and B"
    assert re.search(r"\.PHONY:[^\n]*(\\\n[^\n]*)*\bask\b", makefile)
