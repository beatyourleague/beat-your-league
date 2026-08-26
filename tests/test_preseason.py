"""The pre-season file — the one report that may contain no prediction at all.

Built Aug 24 2026 to close the gap between paying and receiving: the weekly
product cannot say anything until box scores exist, so a buyer who signed up in
draft season held nothing for up to a fortnight. "I paid and got nothing" is the
dominant refund driver in a subscription this size.

What makes it safe to ship in a week is that it contains only FACTS — the
published schedule and last season's completed box scores — so the frozen
method's Grade C, which governs published predictions, has nothing to govern
here. These tests pin that property, because the moment a projection creeps in
this file acquires a calibration burden it was designed not to have.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from engine.preseason import (DEFENSE_NOT_SCORED, NO_RECORD,
                              build_preseason_report, prior_season_form,
                              unfillable_slots)
from engine.roster import Player, PlayerDirectory
from engine.subscriber import RosterSpec

REPO = Path(__file__).resolve().parent.parent
SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")

# A synthetic league, so these run on a fresh checkout with no cache.
ROSTER = [
    Player("p-qb", "Ace Passer", "QB", "BAL"),
    Player("p-rb1", "Bruiser One", "RB", "BAL"),
    Player("p-rb2", "Bruiser Two", "RB", "LA"),
    Player("p-rb3", "Bruiser Three", "RB", "NYG"),
    Player("p-wr1", "Speedy One", "WR", "MIN"),
    Player("p-wr2", "Speedy Two", "WR", "SEA"),
    Player("p-te", "Sure Hands", "TE", "LV"),
    Player("p-k", "Toe Punter", "K", "NO"),
    Player("DEF-CLE", "Cleveland Browns", "DEF", "CLE"),
    Player("p-rookie", "Fresh Legs", "WR", "NYG"),
]
BYES = {"BAL": 13, "LA": 11, "NYG": 8, "MIN": 6, "SEA": 11, "LV": 13,
        "NO": 8, "CLE": 11}


def _directory() -> PlayerDirectory:
    return PlayerDirectory(list(ROSTER))


def _prior(exclude: set[str] | None = None) -> dict:
    """Last season: everybody but ``exclude`` played 17 games."""
    exclude = exclude or set()
    out: dict[int, dict[str, dict[str, str]]] = {}
    for week in range(1, 18):
        rows = {}
        for player in ROSTER:
            if player.player_id in exclude or player.position == "DEF":
                continue
            rows[player.player_id] = {"receptions": "5", "receiving_yards": "50",
                                      "receiving_tds": "0"}
        out[week] = rows
    return out


def _spec(ids=None, scoring="ppr") -> RosterSpec:
    return RosterSpec(
        player_ids=tuple(ids or [p.player_id for p in ROSTER]),
        slots=SLOTS, scoring=scoring, label="Your Team")


def _prose(page: str) -> str:
    """Visible text only. CSS carries widths in %, which is not a claim."""
    stripped = re.sub(r"<style\b.*?</style>|<script\b.*?</script>|<!--.*?-->",
                      " ", page, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", stripped)


def _report(**over):
    kwargs = dict(spec=_spec(), directory=_directory(),
                  prior=_prior({"p-rookie"}), season="2026",
                  cache_dir=REPO / "data" / "raw" / "nflverse", byes=BYES)
    kwargs.update(over)
    return build_preseason_report(**kwargs)


# --------------------------------------------------------------------- #
# the defining property: no prediction, anywhere
# --------------------------------------------------------------------- #

def test_the_file_states_no_probability_and_makes_no_call() -> None:
    """This is why the file could be built and shipped in a week. The frozen
    method governs published PREDICTIONS; a file of facts has none to govern,
    so it needs no preregistration, no backtest and no arm. The moment a
    projection creeps in, it acquires the calibration burden it was designed
    without — so the absence is pinned rather than trusted."""
    from render.preseason import email_html, render, text_summary
    from render.report import TEMPLATE_PATH

    report = _report()
    surfaces = {
        "browser": render(report, TEMPLATE_PATH.read_text(encoding="utf-8")),
        "email": email_html(report),
        "text": text_summary(report),
    }
    for name, page in surfaces.items():
        prose = _prose(page)
        # No odds of any kind: a percentage here would be a claim about a game
        # that has not been scheduled to happen yet.
        assert "%" not in prose, f"{name} carries a percentage"
        for word in ("odds this", "we project", "projected to", "confidence",
                     "chance he", "expected points"):
            assert word not in prose.lower(), f"{name} makes a prediction: {word!r}"
    # And the report itself carries no projection field to render.
    assert "confidence" not in str(report)
    assert "projected" not in str(report)


def test_no_grade_c_banned_word_reaches_the_buyer() -> None:
    """The frozen method bans calibrated/tested/proven/accurate on EVERY
    surface at Grade C, and this is a surface a paying subscriber reads."""
    from render.preseason import email_html, text_summary

    report = _report()
    for name, page in (("email", email_html(report)),
                       ("text", text_summary(report))):
        prose = _prose(page)
        hit = re.search(r"\b(calibrated|tested|proven|accurate)\b|we hit \d",
                        prose, re.I)
        assert not hit, f"{name} carries a Grade-C banned word: {hit.group(0)!r}"


# --------------------------------------------------------------------- #
# RULE P1 — an absence is never a zero
# --------------------------------------------------------------------- #

def test_a_player_with_no_prior_season_has_no_record_not_a_zero() -> None:
    """A rookie scored 0.0 would read as "he was dreadful" when the truth is
    "we have nothing on him" — the fabrication principle 3 forbids, in the
    direction that would have a subscriber bench a first-rounder."""
    report = _report()
    rookie = next(r for r in report["roster"] if r["player_id"] == "p-rookie")
    assert rookie["record"] is None
    assert rookie["no_record_reason"] == NO_RECORD
    assert "Fresh Legs" in report["no_record"]
    # He is absent from the ranking rather than sorted to the bottom of it.
    assert all(r["player_id"] != "p-rookie" for r in report["ranked"])


def test_a_defense_is_a_different_absence_from_an_unknown_player() -> None:
    """"No record" on a rookie means the archive has nothing on him. On a
    defense it means we decline to score them — the same stance the weekly
    product takes, where no DEF slot carries a number either. Reporting both
    as the same fact would tell a subscriber their defense was an unknown
    quantity when it played all seventeen games."""
    report = _report()
    defense = next(r for r in report["roster"] if r["position"] == "DEF")
    assert defense["no_record_reason"] == DEFENSE_NOT_SCORED
    assert "Cleveland Browns" not in report["no_record"], \
        "a defense was reported as a player we know nothing about"


# --------------------------------------------------------------------- #
# RULE P2 — a bye is only a problem when it actually leaves a slot empty
# --------------------------------------------------------------------- #

def test_a_bye_somebody_else_covers_is_not_reported() -> None:
    """A file that cries wolf in August is not read in October. The check
    places the players who ARE available into the starting template and only
    reports a slot nothing can fill."""
    # Three RBs, two RB slots plus a FLEX: one RB on bye is covered.
    assert unfillable_slots(SLOTS, {
        "p-qb": "QB", "p-rb1": "RB", "p-rb2": "RB", "p-wr1": "WR",
        "p-wr2": "WR", "p-te": "TE", "p-k": "K", "DEF-CLE": "DEF",
        "p-rookie": "WR"}) == []
    # Lose the kicker and there is nothing else on the roster that plays K.
    assert unfillable_slots(SLOTS, {
        "p-qb": "QB", "p-rb1": "RB", "p-rb2": "RB", "p-wr1": "WR",
        "p-wr2": "WR", "p-te": "TE", "DEF-CLE": "DEF",
        "p-rookie": "WR"}) == ["K"]


def test_the_weeks_reported_are_the_weeks_that_actually_leave_a_slot_empty() -> None:
    report = _report()
    weeks = {hit["week"]: hit["slots"] for hit in report["collisions"]}
    # W13: BAL (QB + an RB) and LV (the only TE) — QB and TE cannot be filled.
    assert sorted(weeks[13]) == ["QB", "TE"]
    # W8: NO (the only K) and NYG — K cannot be filled.
    assert "K" in weeks[8]
    # W6 is MIN alone: one of four receivers, comfortably covered.
    assert 6 not in weeks, "a covered bye was reported as a problem"


def test_a_roster_with_no_collisions_says_so_rather_than_showing_nothing() -> None:
    """An empty section reads as a feature that failed to load. It has to say
    the good news out loud."""
    from render.preseason import BYE_NONE, text_summary
    # Everyone on one team, so no bye ever leaves a hole they could fill.
    flat = {p.player_id: "NE" for p in ROSTER}
    report = _report(byes={"NE": 9})
    if not report["collisions"]:
        assert BYE_NONE in text_summary(report)
    # And with the real spread, the section is populated instead.
    assert _report()["collisions"], "the fixture stopped exercising collisions"


# --------------------------------------------------------------------- #
# last season's record
# --------------------------------------------------------------------- #

def test_form_is_per_appearance_and_carries_its_denominator() -> None:
    """Per APPEARANCE, not per week: a player who missed half a season should
    not rank below a worse player who never missed one. And "14.1 a game over
    4 games" is a different fact from "over 17" — the reader gets both."""
    prior = {1: {"a": {"receptions": "10"}}, 2: {"a": {"receptions": "10"}},
             3: {"b": {"receptions": "10"}}}
    form = prior_season_form(prior, _spec().rule)
    assert form["a"]["games"] == 2 and form["b"]["games"] == 1
    assert form["a"]["per_game"] == form["b"]["per_game"], \
        "a player was penalised for games he did not play"
    assert form["a"]["points"] == 20.0


def test_scoring_follows_the_subscribers_own_rule() -> None:
    """The whole pitch is "under your scoring". A PPR reception is worth a
    point and a standard one is not, so the same roster must not produce the
    same table for both."""
    ppr = _report(spec=_spec(scoring="ppr"))["ranked"][0]["record"]["per_game"]
    std = _report(spec=_spec(scoring="standard"))["ranked"][0]["record"]["per_game"]
    assert ppr > std, "the scoring preset did not reach the record"


# --------------------------------------------------------------------- #
# delivery
# --------------------------------------------------------------------- #

def test_the_email_half_is_client_safe() -> None:
    """Outlook lays email out with Word's engine and Gmail strips <style> on
    forward — mailing the browser-grade render ships soup, which run/batch.py
    learned the hard way and a test already pins for the weekly report."""
    from render.preseason import email_html

    page = email_html(_report())
    for construct in ("display:grid", "display:flex", "var(--", "@media",
                      "<style", "<link", "fonts.googleapis", "position:absolute"):
        assert construct not in page, f"email-unsafe construct: {construct}"
    assert 'role="presentation"' in page


def test_the_file_is_sent_once_per_purchase_not_once_per_season() -> None:
    """Same rule as the welcome, for the same reason: a season-keyed idempotency
    key moves every August over an append-only signup log that is never pruned,
    so a season roll would mail this to everybody the product ever had —
    cancelled subscribers included. A genuine re-purchase is a new key and does
    get a new file, which is right: new byes, new prior season."""
    from render.preseason import preseason_message

    report = _report()
    first = preseason_message("fan@example.com", "abcdef0123", report,
                              purchased_at="1756000000")
    later = preseason_message("fan@example.com", "abcdef0123", report,
                              purchased_at="1756000000")
    assert first.key == later.key
    assert "@" not in first.key, "an address reached a committed send log"
    repurchase = preseason_message("fan@example.com", "abcdef0123", report,
                                   purchased_at="1788000000")
    assert repurchase.key != first.key


def test_the_subject_says_what_the_file_found() -> None:
    """An inbox line that says nothing gets opened by nobody, and this is the
    first thing a paying subscriber ever receives."""
    from render.preseason import preseason_message

    report = _report()
    assert "weeks leave a slot empty" in preseason_message("a@b.co", "s", report).subject
    report["collisions"] = report["collisions"][:1]
    assert "one week leaves" in preseason_message("a@b.co", "s", report).subject
    report["collisions"] = []
    assert "every bye is covered" in preseason_message("a@b.co", "s", report).subject


def test_the_pre_season_path_cannot_reach_a_league_platform() -> None:
    """PLAN §0: nothing in the paid path may import a league client. Import
    reachability, not a grep — a dependency comes back through what it
    imports."""
    seen: set[str] = set()
    queue = ["engine.preseason", "render.preseason"]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = REPO / (name.replace(".", "/") + ".py")
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                queue += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                queue.append(node.module)
    assert "ingest.sleeper" not in seen and "ingest.pull" not in seen, \
        "the pre-season file reaches a league platform"


def test_both_halves_report_the_same_collisions() -> None:
    """Availability facts travel on every surface or none — the rule the weekly
    report's plain-text half broke by never reading slot flags."""
    from render.preseason import email_html, text_summary

    report = _report()
    html_prose = _prose(email_html(report))
    text = text_summary(report)
    for hit in report["collisions"]:
        for name in hit["players"]:
            assert name in html_prose, f"{name} missing from the email half"
            assert name in text, f"{name} missing from the text half"
