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
    # One short bold line, the names in the detail (pre-launch review F6/D13).
    assert item["action"] == ("Byes ahead: Week 9 leaves your K spot empty; Week 14 "
                              "your DEF spot; Week 15 your TE spot, a playoff week "
                              "under ESPN's, Yahoo's and Sleeper's defaults")
    assert item["detail"].startswith("Week 9: K One is on bye. Week 14: Def One is on "
                                     "bye. Week 15: Te One is on bye.")
    assert item["deadline"] == "before Week 9"
    assert "%" not in item["action"] + item["detail"]    # a fact, never a number


def test_a_player_out_today_is_named_as_no_cover():
    roster = ROSTER + [_row("t2", "Te Two", "TE", 7, out="injured reserve")]
    hits = bye_collisions(roster, SLOTS, range(15, 16))
    assert hits[0]["out"] == ["Te Two (injured reserve)"]
    assert "Te Two (injured reserve) can't cover" in byes_ahead_items(hits)[0]["detail"]


def test_quiet_when_every_bye_ahead_is_covered():
    assert byes_ahead_items([]) == []
    assert bye_collisions(ROSTER, SLOTS, range(16, 19)) == []


def test_a_replayed_week_plans_nothing():
    """The pinned 2024 sample is a replay: there is no rest of season to plan,
    and today's reserve list says nothing about it (principle 3)."""
    data = SimpleNamespace(is_live_week=False, season_byes={"KC": 10}, last_week=18, week=10)
    spec = SimpleNamespace(player_ids=(), slots=SLOTS)
    assert solo._byes_ahead(spec, data) == []


def test_bye_cover_names_players_who_can_fill_it_by_this_seasons_record(monkeypatch):
    """The cover list: eligible for the emptied slot, not rostered, not on bye
    that week, not on a reserve list today, three games or more this season,
    and outside the top (league size x starting slots) at the position by this
    season's points a game — best points a game first."""
    import engine.preseason as preseason
    P = lambda pid, pos, team: SimpleNamespace(player_id=pid, name=pid, position=pos, team=team)
    players = [P("00-k1", "K", "AAA"), P("00-k2", "K", "BBB"), P("00-k3", "K", "CCC"),
               P("00-k4", "K", "DDD"), P("00-k5", "K", "EEE"), P("00-mine", "K", "FFF"),
               P("00-wr", "WR", "GGG"), P("00-k6", "K", "HHH")]
    form = {"00-k1": {"per_game": 9.0, "games": 6}, "00-k2": {"per_game": 12.0, "games": 6},
            "00-k3": {"per_game": 15.0, "games": 6},     # his team is on bye in week 9
            "00-k4": {"per_game": 14.0, "games": 2},     # too few games
            "00-k5": {"per_game": 13.0, "games": 6},     # on injured reserve today
            "00-k6": {"per_game": 25.0, "games": 6},     # top 2: almost surely rostered
            "00-mine": {"per_game": 20.0, "games": 6}, "00-wr": {"per_game": 30.0, "games": 6}}
    monkeypatch.setattr(preseason, "prior_season_form", lambda weekly, rule: form)
    data = SimpleNamespace(weekly={1: {}}, directory=SimpleNamespace(players=players),
                           season_byes={"CCC": 9}, roster_out={"00-k5": "injured reserve"})
    spec = SimpleNamespace(rule="ppr", player_ids=("00-mine",), slots=SLOTS)
    [cover] = solo._bye_cover({"week": 9, "slots": ["K"]}, spec, data, {"00-mine"},
                              league_size=2)
    # The top two kickers this season (k6 25.0, mine 20.0) are left out: a
    # two-team league with one K slot almost surely rosters them.
    assert cover == {"slot": "K", "cut": "outside the top 2",
                     "names": [{"name": "00-k2", "per_game": 12.0},
                               {"name": "00-k1", "per_game": 9.0}]}
    [none] = solo._bye_cover({"week": 9, "slots": ["DEF"]}, spec, data, {"00-mine"})
    assert none["names"] == []


def test_the_item_prints_cover_as_a_record_not_a_forecast():
    [item] = byes_ahead_items([{"week": 9, "slots": ["K"], "players": ["Bo"], "short": ["Bo"],
                                "out": [], "cover": [{"slot": "K", "cut": "outside the top 12",
                                                      "names": [{"name": "Al", "per_game": 14.0}]}]}])
    assert ("by points a game this season, leaving out the top scorers a 12-team "
            "league almost surely has rostered: Week 9 — K, outside the top 12: Al 14.0."
            in item["detail"])
    assert "Check who's free in your league." in item["detail"] and "%" not in item["detail"]
