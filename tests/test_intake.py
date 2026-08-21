"""The JS↔Python contract, checked by running both.

``site/join/roster.js`` resolves names and encodes the signup reference in the
browser; ``engine/roster.py`` and ``run/refs.py`` do the same work on Tuesday.
Nothing type-checks across that gap, and the failure is not a crash: a
subscriber pays, and either the reference cannot be decoded — a payment nobody
can attribute — or worse, it decodes into somebody else's roster.

CLAUDE.md already records this class of bug for the plan prefixes, where a test
pins the literal JavaScript. Pinning source text is weak: it proves the string
has not changed, not that the two implementations AGREE. So these tests execute
the real JavaScript under node on the same inputs and compare outputs.

Skipped rather than failed when node is unavailable, because the suite must
still run on a machine without it — but CI has node, and this is where the
agreement is actually enforced.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.roster import Player, PlayerDirectory, load_directory, normalize
from ingest.nflverse import season_teams
from run.refs import decode_roster, encode_roster

REPO = Path(__file__).resolve().parent.parent
JS = REPO / "site" / "join" / "roster.js"
RAW = REPO / "data" / "raw" / "nflverse"
INDEX = REPO / "site" / "join" / "players.json"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def run_js(body: str) -> object:
    """Execute a snippet with roster.js loaded, and return its JSON result."""
    script = (f'const R = require({str(JS)!r});\n'
              f'// btoa is a browser global; node needs the Buffer equivalent.\n'
              f'globalThis.btoa = (s) => Buffer.from(s, "binary").toString("base64");\n'
              f'{body}')
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          timeout=60)
    if done.returncode != 0:
        raise AssertionError(f"node failed:\n{done.stderr}")
    return json.loads(done.stdout)


# --------------------------------------------------------------------- #
# normalisation must agree character for character
# --------------------------------------------------------------------- #

NAMES = [
    "Ja'Marr Chase", "JAMARR CHASE", "jamarr chase", "A.J. Brown", "AJ Brown",
    "Kenneth Walker III", "Kenneth Walker", "Amon-Ra St. Brown",
    "Amon Ra St Brown", "  Puka Nacua  ", "José Ramírez", "D.K. Metcalf",
    "Marvin Harrison Jr.", "Michael Pittman Jr", "Ka'imi Fairbairn",
    "", "   ", "Nobody McFakename", "O'Dell Beckham",
]


def test_normalise_agrees_between_the_browser_and_tuesday() -> None:
    """The single most load-bearing function in the intake. If the two
    normalisers disagree on one name, that subscriber's roster resolves in the
    browser and fails — or resolves DIFFERENTLY — on Tuesday."""
    got = run_js(f"console.log(JSON.stringify({json.dumps(NAMES)}.map(R.normalize)))")
    expected = [normalize(name) for name in NAMES]
    mismatches = [(n, j, p) for n, j, p in zip(NAMES, got, expected) if j != p]
    assert not mismatches, f"normalisers disagree: {mismatches}"


PASTED = [
    "Patrick Mahomes QB KC - BYE 10", "Patrick Mahomes (KC) 21.4",
    "QB  Patrick Mahomes  KC", "Patrick Mahomes • KC • BYE 6",
    "Justin Jefferson  WR  MIN", "BAL DEF", "Ravens D/ST", "KC",
]


def test_decoration_stripping_agrees() -> None:
    teams = ["KC", "MIN", "BAL", "SF", "LA"]
    got = run_js(
        f"const teams = new Set({json.dumps(teams)});\n"
        f"console.log(JSON.stringify({json.dumps(PASTED)}"
        f".map(l => R.stripDecoration(l, teams))))")
    from engine.roster import _strip_decoration
    expected = [_strip_decoration(line, set(teams)) for line in PASTED]
    mismatches = [(a, b, c) for a, b, c in zip(PASTED, got, expected) if b != c]
    assert not mismatches, f"decoration strippers disagree: {mismatches}"


# --------------------------------------------------------------------- #
# resolution against the REAL published directory
# --------------------------------------------------------------------- #

def _python_directory() -> PlayerDirectory:
    players, teams = RAW / "players.csv", RAW / "teams_colors_logos.csv"
    if not (players.is_file() and teams.is_file() and (RAW / "games.csv").is_file()):
        pytest.skip("nflverse cache not present — run `make index`")
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    return load_directory(players, teams, int(index["season"]) - 1,
                          season_teams(RAW, index["season"]))


def test_the_browser_resolves_the_same_players_python_does() -> None:
    """Run both against the SHIPPED players.json and the same typed names."""
    if not INDEX.is_file():
        pytest.skip("players.json not built — run `make index`")
    directory = _python_directory()
    typed = ["Ja'Marr Chase", "JAMARR CHASE", "AJ Brown", "Bijan Robinson",
             "Brian Robinson", "Ravens", "BAL DEF", "KC", "Rams",
             "Nobody McFakename", "Kenneth Walker"]
    got = run_js(
        f"const fs = require('fs');\n"
        f"const d = R.buildDirectory(JSON.parse(fs.readFileSync({str(INDEX)!r},'utf8')));\n"
        f"console.log(JSON.stringify({json.dumps(typed)}.map(t => {{\n"
        f"  const m = R.resolveLine(d, t);\n"
        f"  return m.player ? m.player.id : (m.reason || null);\n"
        f"}})))")
    expected = []
    for name in typed:
        match = directory.resolve(name)
        expected.append(match.player.player_id if match.resolved
                        else ("ambiguous" if match.candidates else "unknown"))
    mismatches = [(t, j, p) for t, j, p in zip(typed, got, expected) if j != p]
    assert not mismatches, f"resolvers disagree: {mismatches}"


def test_the_browser_refuses_an_ambiguous_name_exactly_as_python_does() -> None:
    """RULE R3 has to hold on BOTH sides. If the browser quietly picks one and
    Python refuses, the subscriber completes a signup Tuesday cannot honour."""
    both = [["Adrian Peterson", "00-0000001", "RB", "MIN"],
            ["Adrian Peterson", "00-0000002", "RB", "CHI"]]
    got = run_js(
        f"const d = R.buildDirectory({{players: {json.dumps(both)}, confusable: []}});\n"
        f"const m = R.resolveLine(d, 'Adrian Peterson');\n"
        f"console.log(JSON.stringify({{player: m.player, n: m.candidates.length,"
        f" reason: m.reason}}))")
    assert got["player"] is None and got["n"] == 2 and got["reason"] == "ambiguous"

    python = PlayerDirectory([Player("00-0000001", "Adrian Peterson", "RB", "MIN"),
                              Player("00-0000002", "Adrian Peterson", "RB", "CHI")])
    match = python.resolve("Adrian Peterson")
    assert not match.resolved and len(match.candidates) == 2


# --------------------------------------------------------------------- #
# the reference must round-trip across the language boundary
# --------------------------------------------------------------------- #

ROSTER = ["00-0036900", "00-0035676", "00-0038134", "00-0036963", "00-0033873",
          "00-0039075", "00-0038542", "00-0034857", "DEF-BAL", "00-0031234",
          "00-0032111", "00-0020030", "00-0034333", "00-0035444", "DEF-KC"]
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


@pytest.mark.parametrize("plan", ["season", "monthly", "league_pass"])
@pytest.mark.parametrize("scoring", ["ppr", "half_ppr", "standard"])
def test_a_ref_built_in_the_browser_decodes_on_tuesday(plan: str,
                                                       scoring: str) -> None:
    """The whole point. The browser writes this string into a Stripe URL and
    nothing stores it in between — if Tuesday cannot read it back, the payment
    is unattributable and the subscriber has bought nothing.

    Note 00-0020030 is in the fixture on purpose: it encodes to "AE4-", so the
    payload really contains the dash that would break a naive split."""
    got = run_js(
        f"console.log(JSON.stringify(R.encodeRoster({plan!r}, {scoring!r},"
        f" {json.dumps(SLOTS)}, {json.dumps(ROSTER)})))")
    assert got == encode_roster(plan, scoring, SLOTS, ROSTER), \
        "the browser and Python built different references"
    back = decode_roster(got)
    assert list(back.player_ids) == ROSTER
    assert list(back.slots) == SLOTS
    assert back.scoring == scoring and back.plan == plan
    assert len(got) <= 200


def test_the_browser_refuses_what_python_would_refuse() -> None:
    """Both ends reject a duplicate and a roster shorter than the lineup. If
    only Python did, the buyer would pay and then be told no."""
    # The duplicate fixture must be LONG ENOUGH to clear the slot-count check,
    # or it throws for the wrong reason and the test passes with the duplicate
    # guard deleted — which is exactly what the first version of it did.
    duplicated = ROSTER[:-1] + [ROSTER[0]]
    assert len(duplicated) >= len(SLOTS) and len(set(duplicated)) < len(duplicated)
    for bad, why, expect in [
        (duplicated, "duplicate", "twice"),
        (ROSTER[:3], "short", "starting slots but only"),
    ]:
        got = run_js(
            f"let err = null;\n"
            f"try {{ R.encodeRoster('season','ppr', {json.dumps(SLOTS)},"
            f" {json.dumps(bad)}); }} catch (e) {{ err = e.message; }}\n"
            f"console.log(JSON.stringify(err))")
        assert got, f"the browser accepted a {why} roster"
        # The REASON matters, not just the refusal. Without this the duplicate
        # case passed with the duplicate guard deleted, because a two-player
        # roster also fails the slot-count check — a test green for the wrong
        # reason proves nothing about the guard it is named after.
        assert expect in got, \
            f"the browser rejected the {why} roster for the wrong reason: {got}"
        with pytest.raises(Exception):
            encode_roster("season", "ppr", SLOTS, bad)
