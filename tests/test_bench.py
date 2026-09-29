"""The bench: every rostered player is named, and a benched star is explained.

Found by running the live product against real 2026 week-4 data (Sep 29 2026).
The report named each starter and ONE bench alternative per slot, so every other
bench player vanished — on the sample roster, Saquon Barkley, a first-round
pick, appeared zero times on any surface. The file benched him and never said
so. A subscriber looks for their star, finds nothing, and concludes the product
is broken; and benching a star is the boldest call the file makes.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from enum import Enum

import pytest

from engine import solo_report
from engine.solo_report import (MAX_NOTABLE_ITEMS, _games_phrase, _starter_depth,
                                bench_report)
from render.report import bench_phrase


class _S(str, Enum):
    ACTIVE = "active"
    OUT = "out"


@dataclass
class _Status:
    status: _S
    reason: str | None = None


@dataclass
class _Proj:
    mean: float
    games: int


@dataclass
class _Pick:
    player_id: str | None
    slot: str
    projection: object = None


class _Players:
    def __init__(self, pos, names):
        self._pos, self._names = pos, names

    def position(self, pid):
        return self._pos[pid]

    def name(self, pid):
        return self._names[pid]


class _Model:
    def __init__(self, proj, obs):
        self._proj, self._obs = proj, obs

    def project(self, pid, week):
        return self._proj.get(pid)

    def observations(self, pid, week):
        return list(self._obs.get(pid, []))


class _Avail:
    def __init__(self, out=()):
        self._out = set(out)

    def classify(self, pid):
        return (_Status(_S.OUT, "designated out") if pid in self._out
                else _Status(_S.ACTIVE))


@dataclass
class _Spec:
    player_ids: tuple
    slots: tuple


SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")




def _said(item) -> str:
    """Everything a game-plan item shows: the bold action and the detail line."""
    return f"{item['action']} {item.get('detail', '')}"

def _fixture(out=()):
    roster = ("qb", "rb1", "rb2", "wr1", "wr2", "te", "flex",
              "star", "scrub", "hurt")
    pos = {"qb": "QB", "rb1": "RB", "rb2": "RB", "wr1": "WR", "wr2": "WR",
           "te": "TE", "flex": "RB", "star": "RB", "scrub": "RB", "hurt": "WR"}
    names = {k: k.upper() for k in roster}
    proj = {k: _Proj(10.0, 3) for k in roster}
    proj["star"] = _Proj(7.6, 3)
    proj["scrub"] = _Proj(4.0, 3)
    proj["hurt"] = _Proj(6.4, 2)
    obs = {k: [10.0, 10.0, 10.0] for k in roster}
    obs["star"] = [9.0, 3.0, 9.0]
    obs["scrub"] = [4.0, 4.0, 4.0]
    obs["hurt"] = [5.0, 1.4]
    picks = [_Pick(pid, slot) for pid, slot in
             zip(("qb", "rb1", "rb2", "wr1", "wr2", "te", "flex"), SLOTS)]
    ranks = {"star": ("RB", 15, 99), "scrub": ("RB", 60, 99), "hurt": ("WR", 20, 159)}
    return (_Spec(roster, SLOTS), picks, _Players(pos, names),
            _Model(proj, obs), _Avail(out), ranks)


def test_every_rostered_player_who_is_not_starting_is_named() -> None:
    spec, picks, players, model, avail, ranks = _fixture()
    bench, _ = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    starters = {p.player_id for p in picks}
    assert {b["player_id"] for b in bench} == set(spec.player_ids) - starters, (
        "a rostered player is missing from the file — the Saquon defect")


def test_a_benched_starter_calibre_player_leads_the_game_plan_with_evidence() -> None:
    spec, picks, players, model, avail, ranks = _fixture()
    _, items = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    assert items, "a benched RB15 produced no explanation"
    text = _said(items[0])
    assert "STAR" in text and "RB15 last season" in text
    assert "9.0, 3.0, 9.0" in text, "the explanation must show his games"
    assert "7.6" in text


def test_a_player_outside_the_starters_is_listed_but_not_flagged() -> None:
    """RB60 is not a player a manager expects to start, so explaining why he
    sits is noise. The threshold is the league's own starter count — 2 RB
    slots x 12 teams = 24 — not a hardcoded rank."""
    spec, picks, players, model, avail, ranks = _fixture()
    bench, items = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    scrub = next(b for b in bench if b["player_id"] == "scrub")
    assert not scrub["notable"]
    assert not any("SCRUB" in i["action"] for i in items)


def test_the_threshold_comes_from_the_subscribers_own_slots() -> None:
    assert _starter_depth("RB", SLOTS, 12) == 24
    assert _starter_depth("TE", SLOTS, 12) == 12
    assert _starter_depth("WR", ("QB", "WR", "WR", "WR"), 10) == 30, (
        "a 3-WR league measures a receiver against its own 30 starters")
    assert _starter_depth("RB", SLOTS, 8) == 16


def test_a_player_who_cannot_play_carries_no_projection() -> None:
    """The first render of this block printed "can't play this week" beside
    6.4 for Jayden Reed. The model's number is form, blind to the designation,
    so for a player who cannot play it is not a projection for this week."""
    spec, picks, players, model, avail, ranks = _fixture(out=("hurt",))
    bench, _ = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    hurt = next(b for b in bench if b["player_id"] == "hurt")
    assert hurt["out"] and hurt["projected"] is None
    assert bench_phrase(hurt) == "can't play this week"


def test_a_notable_player_who_cannot_play_is_explained_as_out_not_as_bad() -> None:
    spec, picks, players, model, avail, ranks = _fixture(out=("star",))
    _, items = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    text = next(_said(i) for i in items if "STAR" in _said(i))
    assert "can't play this week" in text
    assert "9.0, 3.0" not in text, (
        "an injured star explained by his form reads as 'we benched him for "
        "playing badly' — the reason is that he cannot play")


def test_a_benched_player_with_no_games_this_season_says_so() -> None:
    spec, picks, players, model, avail, ranks = _fixture()
    model._obs["star"] = []
    _, items = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    assert "no games this season yet" in items[0]["action"]


def test_the_game_plan_stays_thirty_seconds() -> None:
    spec, picks, players, model, avail, ranks = _fixture()
    for extra in ("x1", "x2", "x3", "x4"):
        spec.player_ids = spec.player_ids + (extra,)
        players._pos[extra] = "RB"; players._names[extra] = extra.upper()
        model._proj[extra] = _Proj(5.0, 3); model._obs[extra] = [5.0] * 3
        ranks[extra] = ("RB", 5, 99)
    bench, items = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    assert len(items) == MAX_NOTABLE_ITEMS
    # ...and every one of them is still named in the bench block.
    assert {"x1", "x2", "x3", "x4", "star"} <= {b["player_id"] for b in bench}
    # Best-ranked first, so the cap drops the least surprising.
    assert "RB5" in _said(items[0])


def test_the_bench_is_ordered_and_reproducible() -> None:
    spec, picks, players, model, avail, ranks = _fixture(out=("hurt",))
    first, _ = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    again, _ = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    assert first == again
    projs = [b["projected"] for b in first]
    known = [p for p in projs if p is not None]
    assert known == sorted(known, reverse=True)
    assert projs[-1] is None, "a player with no projection sorts last"


@pytest.mark.parametrize("values, expected", [
    ([9.0], "9.0 in his one game"),
    ([9.0, 3.0], "9.0 and 3.0 in his two games"),
    ([9.0, 3.0, 9.0], "9.0, 3.0 and 9.0 in his three games"),
    ([1.0, 2.0, 9.0, 3.0, 9.0], "9.0, 3.0 and 9.0 in his last three games"),
])
def test_games_read_as_a_person_says_them(values, expected) -> None:
    assert _games_phrase(values) == expected


def test_no_new_probability_is_published_so_nothing_new_needs_grading() -> None:
    """Principle 2: every published probability is recorded and graded. The
    bench explains with box scores, a rank and the EXISTING projection — so it
    must never carry a confidence, or it becomes an ungraded claim."""
    spec, picks, players, model, avail, ranks = _fixture()
    bench, items = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    for entry in bench:
        assert "confidence" not in entry
    for item in items:
        assert "%" not in item["action"], "a percentage in the bench explanation"


def test_every_surface_names_the_benched_star() -> None:
    """The defect was a player absent from ALL surfaces, so the guard checks
    all of them — a fix in the browser file alone leaves the email, which is
    what actually lands, still missing him."""
    from render.email import render_email, text_summary
    from render.report import _bench_table

    spec, picks, players, model, avail, ranks = _fixture()
    bench, _ = bench_report(spec, picks, players, model, avail, 4, 12, ranks)
    report = {"bench": bench, "lineup": [], "meta": {}}
    assert "STAR" in _bench_table(report)
    import render.email as em
    assert "STAR" in em._bench(report)


def test_a_week_one_bench_row_says_why_he_sits() -> None:
    """Before a game is played the only honest basis is last season — the same
    one the week-1 lineup rows print. "no games yet this season" on every
    bench row told a reader nothing about why their player was sitting."""
    assert bench_phrase({"games": [], "last_season_per_game": 14.5}) == \
        "last season: 14.5 a game"
    # A rookie has neither, and gets neither — absent, never zero.
    assert bench_phrase({"games": [], "last_season_per_game": None}) == \
        "no games yet this season"
    # Once this season exists, it is the better evidence and the row uses it.
    assert bench_phrase({"games": [9.0, 3.0], "last_season_per_game": 14.5}) == \
        "last 2: 9.0, 3.0"


def _with_projections(picks):
    """The lineup as optimal_lineup returns it: starters carry projections."""
    means = {"rb1": 14.0, "rb2": 9.8, "flex": 9.0, "qb": 22.0, "wr1": 15.0,
             "wr2": 12.0, "te": 10.0}
    for pick in picks:
        pick.projection = _Proj(means.get(pick.player_id, 10.0), 3)
    return picks


def test_the_explanation_says_who_took_the_slot() -> None:
    """The one fact a reader wants after "sitting your RB15": who plays
    instead. It is read off the lineup — the eligible starter he would replace
    — so it is always true, where a reason would be an inference."""
    spec, picks, players, model, avail, ranks = _fixture()
    _, items = bench_report(spec, _with_projections(picks), players, model,
                            avail, 4, 12, ranks)
    text = next(_said(i) for i in items if "STAR" in _said(i))
    # RB-eligible starters: rb1 14.0, rb2 9.8, flex (RB) 9.0 — the lowest is
    # the one he would displace.
    # Action first since Sep 29 2026: the start is the bold line, the
    # benched player's numbers are the detail under it.
    # No odds pair FLEX with STAR in this fixture, so the line benches STAR
    # and names who plays instead (Sep 29 2026: "Start X over Y" is kept for
    # the pair that actually carries the slot's odds).
    # STAR shares the line with any other bench player FLEX keeps out.
    assert re.search(r"Bench STAR( and \w+)? — FLEX starts at FLEX", text), text
    assert "FLEX 9.0" in text, text


def test_the_form_explanation_asserts_no_judgment() -> None:
    """The first render read "RB23 last season, but 8.5, 14.7 and 18.4" for
    Tony Pollard. Those numbers are GOOD and rising; "but" asserted his form
    was why he sat, when he sat on a near-tie. A connective is a claim the
    numbers do not always support, so the form branch carries none."""
    spec, picks, players, model, avail, ranks = _fixture()
    model._obs["star"] = [8.5, 14.7, 18.4]   # Pollard's real 2024 line
    _, items = bench_report(spec, _with_projections(picks), players, model,
                            avail, 4, 12, ranks)
    text = next(_said(i) for i in items if "STAR" in _said(i))
    assert " but " not in text, f"a judgment the numbers may contradict: {text}"
    assert "8.5, 14.7, 18.4" in text


def test_benched_players_losing_to_one_starter_share_a_line() -> None:
    """Sep 29 2026, live 2026 build: two lines both read "... — Sam LaPorta
    starts at FLEX". One decision, one line; each player's facts stay."""
    from engine.solo_report import _merge_same_starter
    items = [{"action": "Bench A — X starts at FLEX", "detail": "A: facts.",
              "deadline": "d", "urgency": "now"},
             {"action": "Start K over L at TE · 71%", "detail": "L: facts.",
              "deadline": "d", "urgency": "now"},
             {"action": "Bench B — X starts at FLEX", "detail": "B: facts.",
              "deadline": "d", "urgency": "now"}]
    explained = [{"name": "A"}, {"name": "L"}, {"name": "B"}]
    got = _merge_same_starter(items, {0: ("X", "FLEX"), 2: ("X", "FLEX")}, explained)
    assert [i["action"] for i in got] == ["Bench A and B — X starts at FLEX",
                                          "Start K over L at TE · 71%"]
    assert got[0]["detail"] == "A: facts. B: facts."
    # A lone line is untouched.
    assert _merge_same_starter(items[:2], {0: ("X", "FLEX")}, explained) == items[:2]
