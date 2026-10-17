"""The operator's route for a roster change that arrived by email (G12, OPS-04).

Every welcome, the thanks page and the landing FAQ promise "reply with your
updated roster and your report follows it", and until now nothing could apply
the reply: the registry lives in the Actions cache, not on the owner's
machine, and no module had a command. `make roster-update EMAIL=… ROSTER=…`
posts the same authenticated kind:"update" row a self-serve update is, and the
next intake validates it on the same path. These tests pin that path: the
token authenticates, the subscriber's own team is chosen and keeps its
settings, nothing ambiguous is applied, and no address is ever printed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import run.intake as intake
import run.updates as updates
from run.refs import decode_roster, encode_roster
from run.rosters import load_rosters
from test_intake_sync import (PLAYERS, REF, SLOTS, _registry, _run, _seats,
                              _session, directory, stripe)  # noqa: F401 — fixtures

SECRET = "test-secret-do-not-ship"
HALF_REF = encode_roster("season", "half_ppr", list(SLOTS), PLAYERS, league_size=10)
NEW_IDS = PLAYERS[1:] + PLAYERS[:1]


def _row(email: str, ref: str) -> dict:
    roster = decode_roster(ref)
    return {"email": email, "ref": ref, "player_ids": list(roster.player_ids),
            "slots": list(roster.slots), "scoring": roster.scoring,
            "league_size": roster.league_size}


def test_an_emailed_roster_keeps_the_teams_own_scoring_lineup_and_size() -> None:
    """The operator types NAMES, which say nothing about scoring or lineup.
    The intake picks the subscriber's team and re-encodes the new players
    under that team's own settings — a half-PPR 10-team subscriber stays
    half-PPR 10-team, whatever placeholder the posted row carried."""
    row = updates.operator_row("Fan@Example.com", NEW_IDS, SECRET)
    assert "replaces" not in row and row["email"] == "fan@example.com"
    assert row["token"] == updates.update_token("fan@example.com", SECRET)
    [update], problems = updates.validate_updates(
        [row], [_row("fan@example.com", HALF_REF)], set(PLAYERS), SECRET)
    assert not problems
    applied = decode_roster(update.ref)
    assert update.replaces == updates.slug_of(HALF_REF)
    assert applied.player_ids == tuple(NEW_IDS)
    assert (applied.scoring, applied.slots, applied.league_size, applied.plan) == \
        ("half_ppr", tuple(SLOTS), 10, "season")


def test_two_teams_are_told_apart_by_overlap_and_a_tie_is_refused() -> None:
    """A subscriber with two teams: the change goes to the team it overlaps
    most. Equal overlap is refused, never guessed — changing the wrong team
    is worse than changing none, and the operator can ask which they meant.
    A forged token, as ever, changes nothing."""
    other = encode_roster("season", "ppr", list(SLOTS),
                          [f"00-00{i:05d}" for i in range(40, 48)])
    rows = [_row("fan@example.com", REF), _row("fan@example.com", other)]
    [update], _ = updates.validate_updates(
        [updates.operator_row("fan@example.com", NEW_IDS, SECRET)], rows, None, SECRET)
    assert update.replaces == updates.slug_of(REF)
    half = PLAYERS[:4] + [f"00-00{i:05d}" for i in range(40, 44)]
    none, problems = updates.validate_updates(
        [updates.operator_row("fan@example.com", half, SECRET)], rows, None, SECRET)
    assert none == [] and "more than one" in problems[0]
    forged = dict(updates.operator_row("fan@example.com", NEW_IDS, SECRET), token="0" * 20)
    none, problems = updates.validate_updates([forged], rows, None, SECRET)
    assert none == [] and "does not match" in problems[0]


def test_the_intake_applies_the_operators_row_like_any_confirmed_update(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """End to end through run.intake: the row the command posts changes the
    registry's roster (both copies, one object), keeps everything else, and
    stamps the day it was applied (contract C3)."""
    from datetime import datetime, timezone
    stripe["sessions"] = [_session(REF)]
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    _seats(monkeypatch, updates.operator_row("fan@example.com", NEW_IDS, SECRET))
    assert _run(tmp_path) == 0, capsys.readouterr().err
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.player_ids == tuple(NEW_IDS) and row.scoring == "ppr"
    assert row.slug == updates.slug_of(REF), "the subscription's identity moved"
    assert row.roster_as_of == datetime.now(timezone.utc).date().isoformat()


def test_the_command_posts_through_the_worker_and_prints_no_address(
        tmp_path, monkeypatch, capsys) -> None:
    """`make roster-update` refuses without UPDATE_SECRET and FORM_ENDPOINT
    (no authenticated path, so nothing is written by hand), resolves the
    pasted names with the trial's no-guessing resolver, posts one row, and
    never prints the address — operator output gets pasted places."""
    from test_solo_run import OFFLINE, SEASON, WEEK, _cache
    roster = tmp_path / "names.txt"
    roster.write_text("Aaron Armstrong\nBell Cow\nCade Carter\n", encoding="utf-8")
    monkeypatch.delenv("UPDATE_SECRET", raising=False)
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    argv = ["--email", "fan@example.com", "--roster", str(roster)]
    assert updates.main(argv) == 1
    assert "Nothing was posted" in capsys.readouterr().err
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    data = updates.decode_roster  # keep a name bound; replaced below
    data = __import__("run.solo", fromlist=["load_week_data"]).load_week_data(
        _cache(tmp_path), SEASON, WEEK, session=OFFLINE)
    monkeypatch.setattr("run.solo.load_week_data", lambda *a, **k: data)
    posted: list = []
    monkeypatch.setattr(updates, "post_row", lambda endpoint, row: posted.append((endpoint, row)))
    assert updates.main(argv) == 0
    out = capsys.readouterr().out
    [(endpoint, row)] = posted
    assert endpoint == "https://w.test" and row["kind"] == "update"
    assert row["token"] == updates.update_token("fan@example.com", SECRET)
    assert "fan@" not in out and "***@example.com" in out
    assert updates.main([*argv, "--dry-run"]) == 0 and len(posted) == 1
    makefile = (Path(__file__).resolve().parent.parent / "Makefile").read_text()
    target = makefile.split("\nroster-update:", 1)[1].split("\n\n", 1)[0]
    assert '-m run.updates --email "$(EMAIL)" --roster "$(ROSTER)"' in target


# --------------------------------------------------------------------- #
# OPS-R8 — a change back to an earlier roster is a change
# --------------------------------------------------------------------- #

KICKER_X = PLAYERS[:7] + ["00-0000071"]
KICKER_Y = PLAYERS[:7] + ["00-0000072"]


def _stamped(row: dict, received_at: str) -> dict:
    """The row as the Worker stores it: its own `received_at` stamp."""
    return dict(row, received_at=received_at)


def test_a_change_back_to_an_earlier_roster_is_applied_not_deduped(
        tmp_path, stripe, monkeypatch, capsys) -> None:
    """Reproduced (OPS-R8): operator rows X, then Y, then X again (a kicker
    streamed back and forth). RosterUpdate.key was (email, replaces, ref, "")
    for every kind:"update" row, so the third collided with the first, was
    dropped as a duplicate, and the roster silently stayed Y — while the
    intake printed "1 roster(s) changed" and the command had told the
    operator "their next report uses it". Every kind:"update" row now carries
    the Worker's stamp as its nonce: three rows, three log lines, X stands."""
    from engine.roster import Player, PlayerDirectory

    people = [Player(pid, f"Player {pid}", "WR", "KC")
              for pid in [*PLAYERS, "00-0000071", "00-0000072"]]

    class _Data:
        directory = PlayerDirectory(people)

    monkeypatch.setattr(intake, "load_week_data", lambda *a, **k: _Data())
    stripe["sessions"] = [_session(REF)]
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    rows: list[dict] = []
    for stamp, ids in (("2026-10-10T10:00:00.000Z", KICKER_X),
                       ("2026-10-11T10:00:00.000Z", KICKER_Y),
                       ("2026-10-12T10:00:00.000Z", KICKER_X)):
        rows.append(_stamped(updates.operator_row("fan@example.com", ids, SECRET), stamp))
        _seats(monkeypatch, *rows)
        assert _run(tmp_path) == 0, capsys.readouterr().err
        [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
        assert row.player_ids == tuple(ids), f"the change sent at {stamp} was lost"
    log = updates.load_update_log(tmp_path / updates.UPDATE_LOG_NAME)
    assert len(log) == 3 and len({u.key for u in log}) == 3
    # Re-reading the same Worker rows (every hour, for ~400 days) adds nothing.
    assert _run(tmp_path) == 0
    assert len(updates.load_update_log(tmp_path / updates.UPDATE_LOG_NAME)) == 3


def test_a_row_logged_before_rows_carried_a_nonce_is_not_logged_again(tmp_path) -> None:
    """The migration hazard of the fix above: an update logged bare (no
    nonce) before it existed would, on its next re-read, be logged AGAIN
    under its new nonce — with a NEW first-seen stamp, so a months-old change
    became the newest and undid every later one. It is recognised as the same
    row (logged at or after the Worker received it); a later row with the
    same roster (A -> B -> A) is still a new update."""
    path = tmp_path / updates.UPDATE_LOG_NAME
    bare = updates.RosterUpdate("fan@example.com", "abcdef0123", REF,
                                seen_at="2026-10-10T11:00:00+00:00")
    updates.append_update_log([bare], path)
    same = updates.RosterUpdate("fan@example.com", "abcdef0123", REF,
                                seen_at="2026-10-17T09:00:00+00:00",
                                nonce="rx:2026-10-10T10:00:00.000Z")
    later = updates.RosterUpdate("fan@example.com", "abcdef0123", REF,
                                 seen_at="2026-10-17T09:00:00+00:00",
                                 nonce="rx:2026-10-16T10:00:00.000Z")
    assert updates.append_update_log([same], path) == 0
    assert updates.append_update_log([later], path) == 1
