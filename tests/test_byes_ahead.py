"""Byes ahead: the weekly report's rest-of-season check (mid-season product).

A live weekly report lists, as one checklist item, every week still ahead in
which a bye leaves a starting slot nothing else on the roster can fill — the
roster report's own check (engine.preseason.bye_collisions), facts off the
schedule, no projection and no %."""
from types import SimpleNamespace

from engine.preseason import bye_collisions
from engine.solo_report import byes_ahead_items
from run import solo

SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")


def _row(pid, name, pos, bye, out=None):
    return {"player_id": pid, "name": name, "position": pos, "bye": bye, "out_today": out}


ROSTER = [
    _row("q1", "Qb One", "QB", 9), _row("q2", "Qb Two", "QB", 11),
    _row("r1", "Rb One", "RB", 9), _row("r2", "Rb Two", "RB", 10), _row("r3", "Rb Three", "RB", 12),
    _row("w1", "Wr One", "WR", 8), _row("w2", "Wr Two", "WR", 10), _row("w3", "Wr Three", "WR", 13),
    _row("w4", "Wr Four", "WR", 16),
    _row("t1", "Te One", "TE", 15), _row("k1", "K One", "K", 9), _row("d1", "Def One", "DEF", 14),
]


def test_only_weeks_with_an_empty_slot_are_named_and_only_the_players_who_play_it():
    hits = bye_collisions(ROSTER, SLOTS, range(7, 19))
    assert [(h["week"], h["slots"]) for h in hits] == [(9, ["K"]), (14, ["DEF"]), (15, ["TE"])]
    # Week 9 has a QB and an RB idle too, both covered: the item names the kicker only.
    assert hits[0]["short"] == ["K One"]
    assert set(hits[0]["players"]) == {"Qb One", "Rb One", "K One"}


def test_the_item_names_the_slot_the_player_and_a_default_playoff_week():
    hits = bye_collisions(ROSTER, SLOTS, range(7, 19))
    [item] = byes_ahead_items(hits)
    text = item["action"]
    assert text.startswith("Byes ahead: Week 9 leaves your K spot empty (K One is on bye)")
    assert "Week 15 your TE spot empty (Te One is on bye, a playoff week under ESPN's" in text
    assert item["deadline"] == "before Week 9"
    assert "%" not in text                 # a fact, never a number to grade


def test_a_player_out_today_is_named_as_no_cover():
    roster = ROSTER + [_row("t2", "Te Two", "TE", 7, out="injured reserve")]
    hits = bye_collisions(roster, SLOTS, range(15, 16))
    assert hits[0]["out"] == ["Te Two (injured reserve)"]
    assert "Te Two (injured reserve) can't cover" in byes_ahead_items(hits)[0]["action"]


def test_quiet_when_every_bye_ahead_is_covered():
    assert byes_ahead_items([]) == []
    assert bye_collisions(ROSTER, SLOTS, range(16, 19)) == []


def test_a_replayed_week_plans_nothing():
    """The pinned 2024 sample is a replay: there is no rest of season to plan,
    and today's reserve list says nothing about it (principle 3)."""
    data = SimpleNamespace(is_live_week=False, season_byes={"KC": 10}, last_week=18, week=10)
    spec = SimpleNamespace(player_ids=(), slots=SLOTS)
    assert solo._byes_ahead(spec, data) == []
