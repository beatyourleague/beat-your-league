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
    # The kicker cases: a NON-LEADING bare K is a position tag and strips;
    # a leading K is an initial and must survive. "Jake Bates K DET" is how
    # every league app pastes a kicker, and it used to fail resolution.
    "Jake Bates K DET", "Harrison Butker K", "K. Walker", "K Walker",
    # Sep 29 2026, a real ESPN paste: the app's own team spellings and its
    # section headers must not stop a signup.
    "Puka Nacua LAR WR", "Terry McLaurin WSH WR", "Bench", "Starters", "LAR D/ST",
    # Sleeper's kicker team line, position first (launch audit PC-07): it
    # stripped to a bare "K" and blocked checkout as an unknown player.
    "K - SF", "K KC", "k - min",
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


def test_a_sleeper_kicker_team_line_is_blank_in_both_languages() -> None:
    """Launch audit PC-07, reproduced: Sleeper lays a roster out two lines per
    player, the second position-first ("QB - BUF"). For a kicker that line is
    "K - PIT", which stripped to a bare "K" — K is deliberately not slot
    decoration, because it is also an initial — and came back as "we don't have
    anybody by that name", blocking checkout for every Sleeper user with a
    kicker. Agreement alone would pass with both parsers still returning "K",
    so the VALUE is asserted, and the initials it must not eat ride along."""
    from engine.roster import _strip_decoration
    teams = ["PIT", "DAL", "DET", "KC"]
    lines = ["K - PIT", "K DAL", "k - det", "K Walker", "K. Walker", "KC"]
    want = ["", "", "", "K Walker", "K. Walker", "KC"]
    assert [_strip_decoration(line, set(teams)) for line in lines] == want
    got = run_js(
        f"const teams = new Set({json.dumps(teams)});\n"
        f"console.log(JSON.stringify({json.dumps(lines)}"
        f".map(l => R.stripDecoration(l, teams))))")
    assert got == want, f"browser: {got}"


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


def test_league_size_survives_the_browser_to_tuesday_trip() -> None:
    """The picker rendered four league-size radios under the note "Scoring and
    league size decide how every player in your roster is valued" — and never
    read them. `radio()` was called for scoring and template, never for size;
    encodeRoster had no size field; the ref could not carry one; and both
    to_rows() and seats_to_rows() hardcoded 12. So every subscriber, whatever
    they picked, got a 12-team report AND had their calls recorded in the
    12-team ledger bucket.

    That second half is the expensive one. CLAUDE.md put league size into the
    ledger store id (typed-{scoring}-{size}-{season}) precisely because it sets
    the positional prior's depth and moves the published probability — so a
    14-team subscriber's calls landed in the wrong bucket, distorting the exact
    calibration table the ledger exists to produce.

    v3 carries the size at a fixed position. Safe to change the format because
    checkout has never opened: no v2 ref was ever issued. This pins the whole
    three-way contract — browser, ref, Python — byte for byte."""
    from run.refs import DEFAULT_LEAGUE_SIZE, decode_roster, encode_roster

    ids = ["00-0034796", "00-0032764", "00-0037840", "00-0036322",
           "00-0038543", "00-0039338", "DEF-CLE"]
    slots = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"]

    for size in (8, 10, 12, 14):
        in_browser = run_js(
            f'console.log(JSON.stringify(R.encodeRoster('
            f'"season", "ppr", {json.dumps(slots)}, {json.dumps(ids)}, {size})));')
        in_python = encode_roster("season", "ppr", tuple(slots), tuple(ids),
                                  league_size=size)
        assert in_browser == in_python, (
            f"browser and Python disagree on a size-{size} ref: "
            f"{in_browser!r} vs {in_python!r}")
        assert decode_roster(in_python).league_size == size, \
            "the size the buyer picked did not survive the round trip"

    # A v2 ref predates the field and still decodes — as 12, which is exactly
    # what the engine used for everyone while the question was discarded.
    v3 = _as_v3(encode_roster("season", "ppr", tuple(slots), tuple(ids),
                              league_size=14))
    assert decode_roster(v3).league_size == 14
    v2 = v3.replace("s3-pd", "s2-p", 1)
    assert decode_roster(v2).league_size == DEFAULT_LEAGUE_SIZE

    # And an unknown size code is refused rather than guessed.
    with pytest.raises(Exception):
        decode_roster(v3.replace("s3-pd", "s3-pz", 1))


def _as_v3(v4: str) -> str:
    """The v3 spelling of a v4 ref: the same fields without the roster count —
    what the page issued before v4, and what must keep decoding."""
    head, settings, packed = v4.split("-", 2)
    assert head.endswith("4") and settings[-2:].isdigit()
    return f"{head[0]}3-{settings[:-2]}-{packed}"


# --------------------------------------------------------------------- #
# what a public form backend can do to a run (found Aug 24 2026)
# --------------------------------------------------------------------- #

def test_a_non_ascii_token_cannot_kill_the_whole_intake() -> None:
    """hmac.compare_digest RAISES TypeError, not False, when either str
    argument is non-ASCII — and the token comes straight off a public form
    backend with no character validation. validate_updates is called with no
    try/except, so one anonymous row took down the entire run: no registry
    written, no welcomes sent, no watermark advanced, repeating every run
    until somebody deleted the row by hand. The attacker can re-post it.

    This module's governing rule is that one person's problem must not become
    everybody's; an anonymous stranger's certainly must not."""
    from run.updates import update_token, validate_updates

    secret = "s" * 32
    good = update_token("fan@example.com", secret)
    from run.refs import encode_roster
    ids = ("00-0034796", "00-0032764", "00-0037840", "00-0036322",
           "00-0038543", "00-0039338", "DEF-CLE")
    slots = ("QB", "RB", "WR", "TE", "FLEX", "K", "DEF")
    ref = encode_roster("season", "ppr", slots, ids)
    registry_rows = [{"email": "fan@example.com", "ref": ref,
                      "origin": "abcdef0123"}]
    rows = [
        {"kind": "update", "email": "fan@example.com", "ref": ref,
         "replaces": "abcdef0123", "token": "caf\u00e9" + "0" * 16},  # non-ASCII
    ]
    # The call must RETURN rather than raise: one anonymous row must not be
    # able to take down every subscriber's Tuesday.
    applied, problems = validate_updates(rows, registry_rows, set(ids), secret)
    assert any("token" in p for p in problems), \
        "the non-ASCII token was not reported"
    assert applied == []
    assert good.isascii()


def test_an_unrecognised_seat_payload_refuses_instead_of_reading_it_as_empty() -> None:
    """fetch_seats mined a dict for "data"/"submissions"/"items" and returned
    [] for anything else — indistinguishable from "nobody claimed a seat". A
    backend answering {"records":[...]} (Airtable's own key) therefore wrote a
    Stripe-only registry and exited 0, silently dropping every League Pass
    seat: the exact outcome the "Refusing to write a registry that would drop
    every seat" guard exists to prevent, reached through the one door it did
    not cover. Fail closed on an unknown SHAPE, not just an unreachable host."""
    import json as _json
    import pytest as _pytest
    import run.intake as intake

    class _Resp:
        def __init__(self, body): self._b = body.encode()
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(body):
        return lambda *a, **k: _Resp(body)

    # A recognised key still works, including the newly-added ones.
    for key in ("data", "submissions", "items", "records"):
        intake.urllib.request.urlopen = fake(_json.dumps({key: [{"email": "a@b.co"}]}))
        assert intake.fetch_seats("https://x.test", None) == [{"email": "a@b.co"}]

    # An unrecognised shape REFUSES rather than reporting a quiet week.
    intake.urllib.request.urlopen = fake(_json.dumps({"mystery": [{"email": "a@b.co"}]}))
    with _pytest.raises(intake.IntakeError, match="no recognisable row list"):
        intake.fetch_seats("https://x.test", None)

    intake.urllib.request.urlopen = fake(_json.dumps("a string"))
    with _pytest.raises(intake.IntakeError, match="not a row list"):
        intake.fetch_seats("https://x.test", None)


# --------------------------------------------------------------------- #
# what each league app actually copies out (Sep 29 2026 battery)
# --------------------------------------------------------------------- #
#
# The first battery found that Yahoo's and Sleeper's two-line layout ("Buf - QB",
# "QB - BUF") silently ADDED a team defense the subscriber did not own — the
# most dangerous kind of parse failure, because it looks like success — and
# that stray injury tags, "Last, First" order, initials and NFL.com's matchup
# and kickoff text each stopped a signup. Both parsers now handle them, and
# these pin the outcome on both sides against the shipped directory.

# BE-D1 (Oct 2026): what a real ESPN roster table copies out. Captured by
# loading a public ESPN team page (Week 6 2026) in headless Chrome and
# serialising the roster table the way a copy does (Selection.toString over the
# <table>): ONE CELL PER LINE — slot, name, injury tag, team, position,
# opponent, kickoff, then the stat columns. Through the old parsers every team
# line and every home opponent became a team defense: this copy read as the
# Texans, Falcons, Bears, Ravens, Commanders, Raiders, Bills, Bengals, Jets,
# Seahawks, Eagles and Patriots, the tally said "Looks right", and the report
# would have started a defense the subscriber does not own. The table's own
# headings and totals ("SLOT", "OPRK", "%ROST", "TOTALS", "7th") each stopped
# the signup as an unknown player. The phone-width copy carries opponents and
# kickoffs; the desktop one, read before the schedule loaded, shows "--".
ESPN_TABLE_COPY = (
    "STARTERS\tNFL WEEK 6\t2026 SEASON\nSLOT\nPLAYER\nOPP\nSTATUS\nPROJ\n"
    "SCORE\nOPRK\n%ST\n%ROST\n+/-\nPRK\nFPTS\nAVG\nLAST\nQB\n\nC.J. Stroud\n"
    "HOU\nQB\n@JAX\nSun 9:30 AM\n16.1\n--\n7th\n17.6\n42.9\n+0.5\n16\n"
    "101.18\n20.2\n22.94\nRB\n\nBijan Robinson\nATL\nRB\nCHI\nSun 1:00 PM\n"
    "23.1\n--\n7th\n99.7\n99.9\n0\n2\n121.2\n24.2\n15.8\nRB\n\n"
    "Kyle Monangai\nQ\nCHI\nRB\n@ATL\nSun 1:00 PM\n10.1\n--\n12th\n17.2\n"
    "80.1\n+0.2\n19\n59.3\n14.8\n--\nWR\n\nZay Flowers\nBAL\nWR\n@CLE\n"
    "Sun 1:00 PM\n16.4\n--\n24th\n88.4\n98.9\n+0.1\n8\n81.8\n20.5\n14.6\nWR\n"
    "\nTerry McLaurin\nWSH\nWR\n@SF\nMon 8:15 PM\n12.3\n--\n7th\n52.0\n92.0\n"
    "+0.1\n48\n42.3\n10.6\n12.2\nTE\n\nBrock Bowers\nQ\nLV\nTE\nBUF\n"
    "Sun 4:25 PM\n19.6\n--\n15th\n95.9\n99.9\n0\n5\n71.2\n23.7\n23.0\nFLEX\n"
    "\nTre Tucker\nLV\nWR\nBUF\nSun 4:25 PM\n10.4\n--\n32nd\n16.2\n38.4\n"
    "+2.7\n31\n51.8\n10.4\n7.5\nD/ST\n\nPatriots\nNE\nD/ST\nNYJ\n"
    "Sun 1:00 PM\n6.7\n--\n19th\n67.2\n75.2\n+5.9\n5\n38.0\n7.6\n6.0\nK\n\n"
    "Evan McPherson\nCIN\nK\n*BYE*\n--\n--\n--\n--\n12.4\n27.8\n-4.7\n5\n"
    "55.6\n11.1\n6.6\nTOTALS\n114.7\n0.0\n622.38\n143.14\n108.64\nBench\n\n"
    "A.J. Brown\nIR\nNE\nWR\nNYJ\nSun 1:00 PM\n0.0\n--\n10th\n9.7\n94.5\n0\n"
    "135\n5.6\n5.6\n--\nBench\n\nZach Charbonnet\nO\nSEA\nRB\n@DEN\n"
    "Thu 8:15 PM\n0.0\n--\n26th\n0.2\n57.6\n+0.1\n--\n--\n--\n--\nBench\n\n"
    "Dontayvion Wicks\nQ\nPHI\nWR\nCAR\nSun 1:00 PM\n8.4\n--\n9th\n10.9\n"
    "41.5\n-1.4\n35\n49.0\n9.8\n11.3\nBench\n\nSam Darnold\nSEA\nQB\n@DEN\n"
    "Thu 8:15 PM\n16.3\n--\n14th\n14.2\n40.8\n-1.9\n26\n63.8\n16.0\n10.3\n"
    "Bench\n\nKeon Coleman\nBUF\nWR\n@LV\nSun 4:25 PM\n7.1\n--\n20th\n9.7\n"
    "33.6\n-1.5\n34\n49.4\n9.9\n7.7\nBench\n\nMarvin Harrison Jr.\nHOU\nWR\n"
    "@JAX\nSun 9:30 AM\n3.4\n--\n25th\n7.7\n75.8\n+0.3\n91\n19.5\n4.9\n--\n"
    "TOTALS\n35.2\n0.0\n187.3\n46.11\n29.3\n"
)

ESPN_DESKTOP_COPY = (
    "STARTERS\tNFL WEEK 6\t2026 SEASON\nSLOT\nPLAYER\nOPP\nSTATUS\nPROJ\n"
    "SCORE\nOPRK\n%ST\n%ROST\n+/-\nPRK\nFPTS\nAVG\nLAST\nQB\n\nC.J. Stroud\n"
    "HOU\nQB\n--\n16.1\n--\n7th\n17.6\n42.9\n+0.5\n16\n101.18\n20.2\n22.94\n"
    "RB\n\nBijan Robinson\nATL\nRB\n--\n23.1\n--\n7th\n99.7\n99.9\n0\n2\n"
    "121.2\n24.2\n15.8\nRB\n\nKyle Monangai\nQ\nCHI\nRB\n--\n10.1\n--\n12th\n"
    "17.2\n80.1\n+0.2\n19\n59.3\n14.8\n--\nWR\n\nZay Flowers\nBAL\nWR\n--\n"
    "16.4\n--\n24th\n88.4\n98.9\n+0.1\n8\n81.8\n20.5\n14.6\nWR\n\n"
    "Terry McLaurin\nWSH\nWR\n--\n12.3\n--\n7th\n52.0\n92.0\n+0.1\n48\n42.3\n"
    "10.6\n12.2\nTE\n\nBrock Bowers\nQ\nLV\nTE\n--\n19.6\n--\n15th\n95.9\n"
    "99.9\n0\n5\n71.2\n23.7\n23.0\nFLEX\n\nTre Tucker\nLV\nWR\n--\n10.4\n--\n"
    "32nd\n16.2\n38.4\n+2.7\n31\n51.8\n10.4\n7.5\nD/ST\n\nPatriots\nNE\n"
    "D/ST\n--\n6.7\n--\n19th\n67.2\n75.2\n+5.9\n5\n38.0\n7.6\n6.0\nK\n\n"
    "Evan McPherson\nCIN\nK\n*BYE*\n--\n--\n--\n--\n12.4\n27.8\n-4.7\n5\n"
    "55.6\n11.1\n6.6\nTOTALS\n114.7\n0.0\n622.38\n143.14\n108.64\nBench\n\n"
    "A.J. Brown\nIR\nNE\nWR\n--\n0.0\n--\n10th\n9.7\n94.5\n0\n135\n5.6\n5.6\n"
    "--\nBench\n\nZach Charbonnet\nO\nSEA\nRB\n--\n0.0\n--\n26th\n0.2\n57.6\n"
    "+0.1\n--\n--\n--\n--\nBench\n\nDontayvion Wicks\nQ\nPHI\nWR\n--\n8.4\n"
    "--\n9th\n10.9\n41.5\n-1.4\n35\n49.0\n9.8\n11.3\nBench\n\nSam Darnold\n"
    "SEA\nQB\n--\n16.3\n--\n14th\n14.2\n40.8\n-1.9\n26\n63.8\n16.0\n10.3\n"
    "Bench\n\nKeon Coleman\nBUF\nWR\n--\n7.1\n--\n20th\n9.7\n33.6\n-1.5\n34\n"
    "49.4\n9.9\n7.7\nBench\n\nMarvin Harrison Jr.\nHOU\nWR\n--\n3.4\n--\n"
    "25th\n7.7\n75.8\n+0.3\n91\n19.5\n4.9\n--\nTOTALS\n35.2\n0.0\n187.3\n"
    "46.11\n29.3\n"
)

ESPN_ROSTER = ["C.J. Stroud", "Bijan Robinson", "Kyle Monangai", "Zay Flowers",
                  "Terry McLaurin", "Brock Bowers", "Tre Tucker",
                  "New England Patriots", "Evan McPherson", "A.J. Brown",
                  "Zach Charbonnet", "Dontayvion Wicks", "Sam Darnold",
                  "Keon Coleman", "Marvin Harrison Jr."]

PASTES = {
    "yahoo": ("QB\nJosh Allen\nBuf - QB\nQ\nRB\nSaquon Barkley\nPhi - RB\nO\nWR\n"
              "Ja'Marr Chase\nCin - WR\nAmon-Ra St. Brown\nDet - WR\nTE\nGeorge Kittle\n"
              "SF - TE\nW/R/T\nTony Pollard\nTen - RB\nK\nJake Bates\nDet - K\nDEF\n"
              "Denver Broncos\nDen - DEF\nBN\nCourtland Sutton\nDen - WR\nIR\n"
              "Jayden Reed\nGB - WR   IR",
              ["Josh Allen", "Saquon Barkley", "Ja'Marr Chase", "Amon-Ra St. Brown",
               "George Kittle", "Tony Pollard", "Jake Bates", "Denver Broncos",
               "Courtland Sutton", "Jayden Reed"]),
    "cbs": ("Josh Allen, QB BUF\nBarkley, Saquon RB PHI\nSt. Brown, Amon-Ra WR DET\n"
            "Kittle, George TE SF\nBroncos D/ST\nJake Bates, K DET\nRavens D/ST",
            ["Josh Allen", "Saquon Barkley", "Amon-Ra St. Brown", "George Kittle",
             "Denver Broncos", "Jake Bates", "Baltimore Ravens"]),
    "nfl": ("QB Josh Allen BUF vs. MIA Sun 1:00 PM  21.3\n"
            "RB Saquon Barkley PHI @ NYG  Mon 8:15 PM 18.1\nWR Ja'Marr Chase CIN Bye 12\n"
            "TE George Kittle SF Q\nDEF Denver Broncos DEN\nK Jake Bates DET --",
            ["Josh Allen", "Saquon Barkley", "Ja'Marr Chase", "George Kittle",
             "Denver Broncos", "Jake Bates"]),
    # The kicker's line is "K - DET": position first, then team. It used to
    # strip to a bare "K" and block checkout as an unknown player (PC-07).
    "sleeper": ("Josh Allen\nQB - BUF\nSaquon Barkley\nRB - PHI\nBroncos\nDEF - DEN\n"
                "Chase Brown\nRB - CIN\nJ. Mixon\nRB - HOU\nD. Adams\nWR\n"
                "Jake Bates\nK - DET",
                ["Josh Allen", "Saquon Barkley", "Denver Broncos", "Chase Brown",
                 "Joe Mixon", "Davante Adams", "Jake Bates"]),
    "espn": ("Josh Allen  QB BUF  OUT\nSaquon Barkley  RB PHI  DTD\n"
             "Ja'Marr Chase  WR CIN  P: 15.2 22.1\nSam LaPorta  TE DET  Q\n"
             "Ravens D/ST  D/ST\nJake Bates  K DET  IR\nJayden Reed  WR GB  SSPD",
             ["Josh Allen", "Saquon Barkley", "Ja'Marr Chase", "Sam LaPorta",
              "Baltimore Ravens", "Jake Bates", "Jayden Reed"]),
    "copy-paste": ("Josh Allen 🏈\n1. Saquon Barkley\n2) Ja'Marr Chase\n• Amon-Ra St. Brown\n"
                   "Sam LaPorta (TE - DET) *\nBijan Robinson — ATL RB\n"
                   "Chase Brown, Cincinnati Bengals\nD.J. Moore\nKenneth Walker III\n"
                   "Michael Pittman Jr.\nMarvin Harrison Jr. WR ARI\nBrian Thomas Jr., WR JAC",
                   ["Josh Allen", "Saquon Barkley", "Ja'Marr Chase", "Amon-Ra St. Brown",
                    "Sam LaPorta", "Bijan Robinson", "Chase Brown", "DJ Moore",
                    "Kenneth Walker III", "Michael Pittman", "Marvin Harrison Jr.",
                    "Brian Thomas Jr."]),
    "espn-table": (ESPN_TABLE_COPY, ESPN_ROSTER),
    "espn-desktop": (ESPN_DESKTOP_COPY, ESPN_ROSTER),
    # The verifier's own reproduction (BE-D1): name, team and position each on
    # their own line, a home opponent after the position, a defense written
    # "Eagles D/ST" with its tag on the next line, and a back whose team line
    # disagrees with our list (ESPN said "Sea", the list says KC) — that one is
    # a team line because a position line follows it.
    "espn-lines": ("Jalen Hurts\nPhi\nQB\nCAR\nJonathan Taylor\nInd\nRB\n@HOU\n"
                   "Kenneth Walker III\nSea\nRB\nPuka Nacua\nLAR\nWR\nDrake London\n"
                   "Atl\nWR\nTravis Kelce\nKC\nTE\nLAC\nHarrison Butker\nKC\nK\n"
                   "Eagles D/ST\nD/ST\nNYJ\nRhamondre Stevenson\nNE\nRB\n"
                   "Courtland Sutton\nDen\nWR",
                   ["Jalen Hurts", "Jonathan Taylor", "Kenneth Walker III", "Puka Nacua",
                    "Drake London", "Travis Kelce", "Harrison Butker",
                    "Philadelphia Eagles", "Rhamondre Stevenson", "Courtland Sutton"]),
}


@pytest.mark.parametrize("app", sorted(PASTES))
def test_a_paste_from_each_league_app_resolves_to_exactly_the_roster(app) -> None:
    """Every line resolves, to exactly the players on the roster — no phantom
    defense from a team code, no unresolved tag — in Python AND in the browser."""
    if not INDEX.is_file():
        pytest.skip("players.json not built — run `make index`")
    text, expected = PASTES[app]
    directory = _python_directory()
    py = directory.resolve_all([line for line in text.splitlines() if line.strip()])
    assert [m.player.name if m.resolved else f"UNRESOLVED {m.typed!r}"
            for m in py] == expected, f"python, {app}"
    got = run_js(
        f"const fs = require('fs');\n"
        f"const d = R.buildDirectory(JSON.parse(fs.readFileSync({str(INDEX)!r},'utf8')));\n"
        f"console.log(JSON.stringify(R.resolveAll(d, {json.dumps(text)})"
        f".map(m => m.player ? m.player.name : 'UNRESOLVED ' + m.typed)))")
    assert got == expected, f"browser, {app}"


def test_an_initial_that_fits_two_players_is_a_choice_not_a_guess() -> None:
    """RULE R3 for "J. Smith": a unique initial-plus-surname is a lookup; two
    of them come back as a choice in BOTH languages."""
    both = [["John Smith", "00-0000001", "WR", "MIN"],
            ["Jane Smith", "00-0000002", "WR", "CHI"],
            ["Josh Allen", "00-0000003", "QB", "BUF"]]
    directory = PlayerDirectory([Player(i, n, pos, team) for n, i, pos, team in both])
    for typed, kind in (("J. Smith", "ambiguous"), ("J. Allen", "resolved"),
                        ("D. Smith", "unknown")):
        m = directory.resolve(typed)
        assert ("resolved" if m.resolved else "ambiguous" if m.candidates
                else "unknown") == kind, typed
        got = run_js(
            f"const d = R.buildDirectory({{players: {json.dumps(both)}, confusable: []}});\n"
            f"const m = R.resolveLine(d, {json.dumps(typed)});\n"
            f"console.log(JSON.stringify(m.player ? 'resolved' : "
            f"m.candidates.length ? 'ambiguous' : 'unknown'))")
        assert got == kind, f"browser {typed}"


# --------------------------------------------------------------------- #
# reviewer-found inputs (adversarial review, Sep 29 2026)
# --------------------------------------------------------------------- #

# (typed, expected). "UNRESOLVED" is ONE row reported back to the person; []
# is a line that is not a roster entry. Every case runs through both languages.
REVIEW_CASES = [
    # A desktop copy is tab-separated: the player beats the team and opponent
    # cells. The longest cell used to win, so the OPPONENT became a phantom
    # defense and Josh Allen vanished.
    ("Josh Allen\tQB\tBUF\tvs. Miami Dolphins Sun 1:00 PM", ["Josh Allen"]),
    ("Justin Jefferson\tMinnesota Vikings\tWR", ["Justin Jefferson"]),
    ("Denver Broncos\tDEF\tvs. KC", ["Denver Broncos"]),
    # A lone team code beside an opponent, bye, status or projection is NOT a
    # roster entry; a bare code or a code with DEF still is a defense.
    ("vs. MIA", []), ("@ NYG", []), ("vs MIA Sun 1:00 PM", []),
    ("Buf - Bye 9", []), ("BUF (Bye 7)", []), ("Buf - Q", []), ("BUF OUT", []),
    ("KC", ["Kansas City Chiefs"]), ("KC D/ST", ["Kansas City Chiefs"]),
    ("Den - DEF", ["Denver Broncos"]),
    # A kicker's team line, position first (Sleeper): not a player, not a
    # defense. Either reading blocks or corrupts the signup (PC-07).
    ("K - PIT", []), ("K DAL", []), ("K - LAR", []),
    # After a comma only a FULL team name or a code is an annotation. A bare
    # nickname is a second roster entry and must not be swallowed.
    ("Josh Allen, Buffalo Bills", ["Josh Allen"]), ("Josh Allen, BUF", ["Josh Allen"]),
    ("Josh Allen, Ravens", ["UNRESOLVED"]),
    # A team code that leads a NAME.
    ("KC Concepcion WR CLE", ["KC Concepcion"]),
    # Blank means no LETTER survives; letters of any script are reported back.
    ("🏈", []), ("•", []), ("Патрик", ["UNRESOLVED"]),
    # Whitespace the two languages disagree about.
    ("Josh Allen\x85Q", ["Josh Allen"]), ("Josh Allen\x1cQ", ["Josh Allen"]),
    ("Josh Allen QB BUF", ["Josh Allen"]),
    # BE-D1. A bare team code is read in CONTEXT: right after a player it is
    # his team line (his team, or a position line follows it), and after his
    # own position line it is his opponent. Elsewhere it is still a defense.
    ("Jalen Hurts\nPhi\nQB", ["Jalen Hurts"]),
    ("Jalen Hurts\nPhi\nQB\nCAR", ["Jalen Hurts"]),
    ("Kenneth Walker III\nSea\nRB", ["Kenneth Walker III"]),
    ("Patriots\nNE\nD/ST\nNYJ", ["New England Patriots"]),
    ("Josh Allen\nKC", ["Josh Allen", "Kansas City Chiefs"]),
    ("KC\nQB\nJosh Allen", ["Kansas City Chiefs", "Josh Allen"]),
    ("Josh Allen\nBuf - QB\nDEF\nKC", ["Josh Allen", "Kansas City Chiefs"]),
    # A tab row with a player's team and his opponent but no player cell is
    # not an entry; before, the opponent's code became that team's defense.
    ("QB\tJalen Hurts\nPhiQB\tCAR\tSun 1:00 PM", ["Jalen Hurts"]),
    ("BUF\tQB", []),
    # Cells glued together by a copy with no space between them.
    ("Eagles D/STD/ST", ["Philadelphia Eagles"]), ("Jalen HurtsQ", ["Jalen Hurts"]),
    ("SeaWR", []), ("PHIQB", []),
]
# Decoration words glued to accented letters: the two languages must AGREE.
AGREE_ONLY = ["Josh Allen éNA", "Allenéout", "ÉPM", "Josh Allen Ñ", "Zoë Kravitz"]


def _both(text):
    directory = _python_directory()
    py = [m.player.name if m.resolved else "UNRESOLVED"
          for m in directory.resolve_all(text.split("\n"))]
    js = run_js(
        f"const fs = require('fs');\n"
        f"const d = R.buildDirectory(JSON.parse(fs.readFileSync({str(INDEX)!r},'utf8')));\n"
        f"console.log(JSON.stringify(R.resolveAll(d, {json.dumps(text)})"
        f".map(m => m.player ? m.player.name : 'UNRESOLVED')))")
    return py, js


@pytest.mark.parametrize("typed,expected", REVIEW_CASES)
def test_every_reviewer_found_input_resolves_the_same_in_both_languages(typed, expected) -> None:
    if not INDEX.is_file():
        pytest.skip("players.json not built — run `make index`")
    py, js = _both(typed)
    assert py == expected, f"python: {typed!r} -> {py}"
    assert js == expected, f"browser: {typed!r} -> {js}"


@pytest.mark.parametrize("typed", AGREE_ONLY)
def test_the_two_parsers_agree_on_accented_and_glued_decoration(typed) -> None:
    if not INDEX.is_file():
        pytest.skip("players.json not built — run `make index`")
    py, js = _both(typed)
    assert py == js, f"{typed!r}: python {py} vs browser {js}"


def test_no_directory_player_is_mangled_by_the_decoration_stripping() -> None:
    """Every plain full name in the shipped directory must still resolve to
    that player in BOTH languages (a new stripped word — OUT, NA, PM, SUN — must
    never eat part of a real name). Names that resolve to a DIFFERENT player or
    to a choice are reported, since two players may legitimately share one."""
    if not INDEX.is_file():
        pytest.skip("players.json not built — run `make index`")
    directory = _python_directory()
    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    in_python = {p.name for p in directory.players}
    # The shipped players.json and the freshly built Python directory are two
    # snapshots (a signing between them is not a parser difference).
    names = [row[0] for row in payload["players"] if row[0] in in_python]
    got = run_js(
        f"const fs = require('fs');\n"
        f"const d = R.buildDirectory(JSON.parse(fs.readFileSync({str(INDEX)!r},'utf8')));\n"
        f"console.log(JSON.stringify({json.dumps(names)}.map(n => {{\n"
        f"  const m = R.resolveLine(d, n); return m.player ? m.player.name : null; }})))")
    py = [(m.player.name if (m := directory.resolve(n)).resolved else None) for n in names]
    both_wrong = [n for n, a, b in zip(names, py, got) if a != n and b != n]
    disagree = [(n, a, b) for n, a, b in zip(names, py, got) if a != b]
    assert not disagree, f"python and browser disagree on real names: {disagree[:5]}"
    # Only a name shared with another player (or a defense alias) may fail to
    # resolve to itself, and then both languages say so.
    assert len(both_wrong) <= 12, f"stripping mangles real names: {both_wrong}"


def test_the_typeahead_ranks_by_who_people_mean_and_enter_never_guesses() -> None:
    """Launch audit PC-09, in the browser's own code: a surname search lists the
    player who has actually scored first, and Enter adds only an exact name or
    the single remaining suggestion."""
    got = run_js(
        "const d = R.buildDirectory({players: ["
        "['Josh Allen','00-1','QB','BUF',900],['Allen Lazard','00-2','WR','NYJ',80],"
        "['Keenan Allen','00-3','WR','LAC',400],['Brandon Allen','00-4','QB','SF',null]]});\n"
        "const s = R.suggestPlayers(d, 'allen', 8).map(p => p.name);\n"
        "const one = R.suggestPlayers(d, 'keenan', 8);\n"
        "console.log(JSON.stringify({s, enterMany: R.enterPick(R.suggestPlayers(d,'allen',8),'allen'),"
        " enterOne: (R.enterPick(one,'keenan')||{}).name,"
        " enterExact: (R.enterPick(R.suggestPlayers(d,'josh allen',8),'Josh Allen')||{}).name}))")
    assert got["s"][0] == "Allen Lazard" or got["s"][0] == "Josh Allen"
    # Word-start matches outrank, then points: Josh Allen (900) before Keenan (400).
    assert got["s"].index("Josh Allen") < got["s"].index("Keenan Allen") < got["s"].index("Brandon Allen")
    assert got["enterMany"] is None
    assert got["enterOne"] == "Keenan Allen"
    assert got["enterExact"] == "Josh Allen"


def test_a_typeahead_add_keeps_every_choice_already_made_on_the_list() -> None:
    """Launch audit F7, in the browser's own code. A pasted "J. Smith" is a
    choice and a junk line is removable; the person picks Jane and removes the
    junk — on the LIST, which the paste box never learns. Adding a player used
    to re-read the box and bring both problems back, blocking checkout.
    R.addPick appends the tapped player and leaves every earlier row exactly
    as decided, without touching the array it was given. A tapped row carries
    no near-name swap: the person read the full name and chose it, which is
    the exact-name case (I15, Oct 2026 — the swap offered on an exact name
    read as doubt about a household name)."""
    got = run_js(
        "const d = R.buildDirectory({players: ["
        "['John Smith','00-0000001','WR','MIN'],['Jane Smith','00-0000002','WR','CHI'],"
        "['Bijan Robinson','00-0000003','RB','ATL'],['Brian Robinson','00-0000004','RB','ATL'],"
        "['Josh Allen','00-0000005','QB','BUF']],"
        " confusable: [['00-0000003','00-0000004']]});\n"
        "const matches = R.resolveAll(d, 'Josh Allen\\nJ. Smith\\nWaiver note 98.2');\n"
        "const before = matches.map(m => m.player ? m.player.name : 'OPEN ' + m.reason);\n"
        "matches[1] = {typed: 'J. Smith', player: d.byId.get('00-0000002'), candidates: [], twins: []};\n"
        "matches.splice(2, 1);\n"
        "const kept = matches.slice();\n"
        "const after = R.addPick(d, matches, d.byId.get('00-0000003'));\n"
        "console.log(JSON.stringify({before, untouched: matches.length === kept.length,"
        " after: after.map(m => m.player ? m.player.name : 'OPEN ' + m.reason),"
        " twins: after[after.length - 1].twins.map(t => t.name),"
        " reread: R.resolveAll(d, 'Josh Allen\\nJ. Smith\\nWaiver note 98.2\\nBijan Robinson')"
        ".map(m => m.player ? m.player.name : 'OPEN ' + m.reason)}))")
    assert got["before"] == ["Josh Allen", "OPEN ambiguous", "OPEN unknown"]
    assert got["after"] == ["Josh Allen", "Jane Smith", "Bijan Robinson"]
    assert got["untouched"] is True
    assert got["twins"] == []
    # The trap it replaces: re-reading the box undoes both decisions.
    assert got["reread"] == ["Josh Allen", "OPEN ambiguous", "OPEN unknown", "Bijan Robinson"]


# --------------------------------------------------------------------- #
# exact names never offer a swap (I15, Oct 2026)
# --------------------------------------------------------------------- #

def test_an_exact_full_name_offers_no_near_name_swap_in_either_language() -> None:
    """Reproduction (I15): a Yahoo paste of "Bijan Robinson" — the exact name —
    still showed "not Brian Robinson? tap to swap", which reads as doubt about
    a household name. The swap is offered only when what was typed is NOT the
    full name letter for letter (case and spacing aside)."""
    from engine.roster import exact_name
    cases = [("Bijan Robinson", True), ("bijan  robinson", True),
             ("Bijan Robinson RB ATL", True), ("BijanRobinson", False),
             ("B. Robinson", False), ("Kenneth Walker", False)]
    names = {"Kenneth Walker": "Kenneth Walker III"}
    teams = {"ATL"}
    for typed, want in cases:
        name = names.get(typed, "Bijan Robinson")
        assert exact_name(typed, name, teams) is want, typed
    got = run_js(
        f"const teams = new Set(['ATL']);\n"
        f"console.log(JSON.stringify({json.dumps(cases)}.map(([t]) => "
        f"R.exactName(t, {json.dumps(names)}[t] || 'Bijan Robinson', teams))))")
    assert got == [want for _, want in cases]
    # And the resolver acts on it: the exact name carries no twin, a run-together
    # spelling of the same name still does.
    pair = [["Bijan Robinson", "00-0000003", "RB", "ATL"],
            ["Brian Robinson", "00-0000004", "RB", "ATL"]]
    twins = run_js(
        f"const d = R.buildDirectory({{players: {json.dumps(pair)},"
        f" confusable: [['00-0000003','00-0000004']]}});\n"
        f"console.log(JSON.stringify(['Bijan Robinson', 'BIJAN ROBINSON', 'BijanRobinson']"
        f".map((t) => R.resolveLine(d, t).twins.map((p) => p.name))))")
    assert twins == [[], [], ["Brian Robinson"]]


def test_ungluing_never_splits_a_team_code() -> None:
    """The glued-tag split (BE-D1: "PhiQB", "Jalen HurtsQ") must never cut a
    real team code in two — "DET" is not "DE" + "T", "LAC" is not "LA" + "C".
    Every code and alias, both languages, comes through whole."""
    from engine.roster import TEAM_ALIASES, _unglue
    directory = _python_directory()
    codes = sorted({p.team for p in directory.players if p.team} | set(TEAM_ALIASES))
    teams = set(codes)
    assert [_unglue(c, teams) for c in codes] == codes
    got = run_js(f"const teams = new Set({json.dumps(codes)});\n"
                 f"console.log(JSON.stringify({json.dumps(codes)}.map((c) => R.unglue(c, teams))))")
    assert got == codes
    glued = ["PhiQB", "PHIQB", "Jalen HurtsQ", "Eagles D/STD/ST", "SeaWR", "DK Metcalf",
             "AJ Brown", "CeeDee Lamb", "JuJu Smith-Schuster", "LaPorta"]
    want = ["Phi QB", "PHI QB", "Jalen Hurts Q", "Eagles D/ST D/ST", "Sea WR",
            "DK Metcalf", "AJ Brown", "CeeDee Lamb", "JuJu Smith-Schuster", "LaPorta"]
    assert [_unglue(g, teams) for g in glued] == want
    got = run_js(f"const teams = new Set({json.dumps(codes)});\n"
                 f"console.log(JSON.stringify({json.dumps(glued)}.map((c) => R.unglue(c, teams))))")
    assert got == want


# --------------------------------------------------------------------- #
# the v4 reference: the roster count, and the source tag it makes safe
# --------------------------------------------------------------------- #

def _shapes():
    from engine.subscriber import LINEUP_SHAPES
    return LINEUP_SHAPES


def test_every_lineup_shape_is_the_same_in_the_browser_and_python() -> None:
    """Contract C8: the page builds the slots from a base and two answers; the
    engine reads them back as a shape. The two tables are one contract."""
    shapes = _shapes()
    got = run_js(
        "const out = {};\n"
        "for (const base of Object.keys(R.SHAPE_BASES)) for (const k of [true, false])"
        " for (const d of [true, false]) { const code = R.shapeCode(base, k, d);"
        " out[code] = {slots: R.shapeSlots(base, k, d), graded: R.GRADED_SHAPES.includes(code),"
        " back: R.shapeOfSlots(R.shapeSlots(base, k, d)).code,"
        " fromCode: R.shapeFromCode(code).base}; }\n"
        "out['std-nokd-alias'] = R.shapeFromCode('std-nokd').code;\n"
        "console.log(JSON.stringify(out))")
    alias = got.pop("std-nokd-alias")
    assert alias == "nokd"
    assert set(got) == set(shapes)
    for code, shape in shapes.items():
        assert tuple(got[code]["slots"]) == shape.slots, code
        assert got[code]["graded"] is shape.graded, code
        assert got[code]["back"] == code and got[code]["fromCode"] == shape.base, code


@pytest.mark.parametrize("via", [None, "reddit", "x-post", "a" * 24])
def test_every_shape_round_trips_with_its_tag_in_both_languages(via) -> None:
    """The page writes a v4 ref (roster count + optional "_via-<tag>", contract
    C5); Tuesday reads it. Built in the browser, decoded by Python AND by the
    browser's own decoder (the ?ref= restore, contract C6), for every shape."""
    from run.refs import decode_roster, encode_roster, split_via
    for code, shape in _shapes().items():
        ids = ROSTER[: max(len(shape.slots), 10)]
        js = run_js(
            f"const ref = R.withVia(R.encodeRoster('monthly', 'half_ppr', "
            f"{json.dumps(list(shape.slots))}, {json.dumps(ids)}, 10), {json.dumps(via)});\n"
            f"console.log(JSON.stringify({{ref, back: R.decodeRoster(ref)}}))")
        py = encode_roster("monthly", "half_ppr", shape.slots, ids, 10, via=via)
        assert js["ref"] == py, code
        assert len(py) <= 200 and py.split("-", 1)[0] == "m4"
        back = decode_roster(py)
        assert back.slots == shape.slots and back.player_ids == tuple(ids)
        assert back.via == via and back.league_size == 10 and back.plan == "monthly"
        assert split_via(py) == ((py[: -len(f"_via-{via}")], via) if via else (py, None))
        b = js["back"]
        assert (tuple(b["slots"]), tuple(b["playerIds"]), b["via"], b["leagueSize"],
                b["plan"], b["scoring"]) == (shape.slots, tuple(ids), via, 10,
                                             "monthly", "half_ppr")


def test_the_tag_can_never_be_read_off_the_roster_itself() -> None:
    """Why v4 carries the count. base64url's alphabet includes "_" and "-", so
    a packed roster can itself END in "_via-..." — and reading the tag off the
    end, wherever it appears, would silently drop the subscriber's last
    players. Built here: the last two players pack to "_via" and "-abc". With
    the count the payload's end is known, so both languages read no tag and
    the whole roster. A v3 ref has no count, so the same payload under v3 is
    cut by the intake's rule — every decoder agrees with it, which is exactly
    why the page issues v4 and never tags a v3."""
    import base64
    from run.intake import split_via as intake_split
    from run.refs import _pack_one, decode_roster, split_via
    tail = base64.urlsafe_b64decode("_via-abc")
    blob = b"".join(_pack_one(pid).to_bytes(3, "big") for pid in ROSTER[:9]) + tail
    packed = base64.urlsafe_b64encode(blob).decode().rstrip("=")
    assert packed.endswith("_via-abc")
    ref = "s4-pcQRRWWTFKD11-" + packed
    assert split_via(ref) == (ref, None) == intake_split(ref)
    back = decode_roster(ref)
    assert back.via is None and len(back.player_ids) == 11
    js = run_js(f"console.log(JSON.stringify(R.decodeRoster({json.dumps(ref)})))")
    assert js["via"] is None and len(js["playerIds"]) == 11
    v3 = "s3-pcQRRWWTFKD-" + packed
    assert split_via(v3) == intake_split(v3) == (v3[:-len("_via-abc")], "abc")


def test_a_bad_tag_is_dropped_never_refused_and_a_bad_tail_is_refused() -> None:
    """Attribution must not cost a sale: an unusable tag leaves the ref as it
    was (the page still checks out). But a tail after the counted roster that
    is not a well-formed tag is a ref nobody can read with certainty — refused
    in both languages, never decoded as a shorter roster."""
    from run.refs import RefError, decode_roster, encode_roster, with_via
    ref = encode_roster("season", "ppr", SLOTS, ROSTER)
    for bad in ("Reddit", "has space", "x" * 25, "", None, "a_b"):
        assert with_via(ref, bad) == ref
        assert run_js(f"console.log(JSON.stringify(R.withVia({json.dumps(ref)}, "
                      f"{json.dumps(bad)})))") == ref
    assert with_via(with_via(ref, "one"), "two") == with_via(ref, "one")
    for broken in (ref + "_via-", ref + "_via-UP", ref + "AAAA", ref[:-4]):
        with pytest.raises(RefError):
            decode_roster(broken)
        thrown = run_js(f"let e = null; try {{ R.decodeRoster({json.dumps(broken)}); }}"
                        f" catch (x) {{ e = x.message; }} console.log(JSON.stringify(e))")
        assert thrown, broken
    # A full 30-player roster with the longest tag still fits Stripe.
    big = [f"00-{n:07d}" for n in range(1, 31)]
    longest = encode_roster("league_pass", "standard",
                            _shapes()["sf"].slots, big, 14, via="z" * 24)
    assert len(longest) <= 200 and longest.endswith("_via-" + "z" * 24)


def test_older_refs_still_decode_in_both_languages() -> None:
    """No v3 ref may break: the browser restores and Tuesday reads one exactly
    as before (no count, no tag)."""
    from run.refs import decode_roster, encode_roster
    v4 = encode_roster("season", "standard", SLOTS, ROSTER, 8)
    v3 = _as_v3(v4)
    v2 = v3.replace("s3-sa", "s2-s", 1)
    for ref, size in ((v3, 8), (v2, 12)):
        back = decode_roster(ref)
        assert (back.player_ids, back.league_size, back.via) == (tuple(ROSTER), size, None)
        js = run_js(f"console.log(JSON.stringify(R.decodeRoster({json.dumps(ref)})))")
        assert (tuple(js["playerIds"]), js["leagueSize"], js["via"]) == (tuple(ROSTER), size, None)


def test_every_decoder_strips_a_tag_exactly_as_the_intake_does() -> None:
    """Contract C5 addendum: run/intake.split_via strips "_via-<tag>" before a
    payment's ref is stored or decoded, taking the suffix only when what is
    left still decodes. run/refs.split_via (which decode_roster calls, so the
    registry, the waitlist and every Tuesday read agree) and the browser's
    R.splitVia (the ?ref= restore) apply that one rule, pinned here over refs
    the page issues and refs it never would. Mutation-checked: dropping the
    remainder-decodes test from either Python copy, or the count check from
    a v4 decode, fails this."""
    from run.intake import split_via as intake_split
    from run.refs import encode_roster, split_via
    refs = []
    for code, shape in _shapes().items():
        ids = ROSTER[: max(len(shape.slots), 10)]
        plain = encode_roster("season", "ppr", shape.slots, ids)
        refs += [plain, plain + "_via-reddit", plain + "_via-x-post"]
    plain = refs[0]
    v3 = _as_v3(plain)
    refs += [v3, v3 + "_via-reddit", plain + "_via-", plain + "_via-UP",
             plain + "_via-" + "a" * 25, plain[:-4] + "_via-reddit",
             plain + "AAAA_via-reddit", "s3-zz_via-x", "nonsense_via-x", "",
             # Tagged twice by hand: every copy splits at the LAST tag.
             plain + "_via-reddit_via-x", v3 + "_via-a_via-b"]
    want = [intake_split(ref) for ref in refs]
    assert [split_via(ref) for ref in refs] == want
    got = run_js(f"console.log(JSON.stringify({json.dumps(refs)}.map((r) => R.splitVia(r))))")
    assert [tuple(pair) for pair in got] == [tuple(pair) for pair in want]
    # And they say something: tags come off v4 refs, junk is left for the
    # decoder to refuse.
    assert split_via(plain + "_via-reddit") == (plain, "reddit")
    assert split_via(plain + "_via-UP") == (plain + "_via-UP", None)
    assert split_via(plain[:-4] + "_via-reddit")[1] is None
    assert split_via(plain + "_via-reddit_via-x") == (plain + "_via-reddit", "x")


def test_every_seat_link_the_intake_builds_prefills_the_join_page() -> None:
    """Contract C4 + C8 across the language boundary: run/updates.seat_url
    writes s/n/t from a pass payer's own setup, and the join page applies
    them only when they are values it offers (a radio value, or a code
    R.shapeFromCode knows) — anything else is silently left for the leaguemate
    to pick. So a shape the intake can name but the page cannot read would
    send eleven leaguemates a link that quietly drops their lineup. Every
    shape, every scoring rule, every size: the link's values round-trip to the
    same slots in the browser."""
    import re
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit
    from run.trial import TEMPLATES
    from run.updates import seat_url
    join = JS.with_name("index.html").read_text(encoding="utf-8")

    def offered(name: str) -> set[str]:
        return set(re.findall(rf'name="{name}" value="([^"]+)"', join))

    assert set(TEMPLATES) == set(_shapes()), "a shape the seat link cannot name"
    links = []
    for code, slots in TEMPLATES.items():
        for scoring in ("ppr", "half_ppr", "standard"):
            for size in (8, 10, 12, 14):
                roster = SimpleNamespace(scoring=scoring, league_size=size, slots=slots)
                url = seat_url("https://beatyourleague.test", "s3cret", "payer@example.com",
                               roster)
                query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
                assert query["s"] in offered("scoring") and query["n"] in offered("size")
                assert re.fullmatch(r"[0-9a-f]{20}", query["pass"])
                links.append((query["t"], list(slots)))
    got = run_js(
        f"console.log(JSON.stringify({json.dumps(links)}.map(([t]) => {{"
        f" const s = R.shapeFromCode(t); return s && [s.base, s.kicker, s.defense,"
        f" R.shapeSlots(s.base, s.kicker, s.defense)]; }})))")
    for (code, slots), shape in zip(links, got):
        assert shape is not None, code
        base, kicker, defense, back = shape
        assert back == slots, code
        assert base in offered("template"), code
        assert {"yes", "no"} <= offered("kicker") and {"yes", "no"} <= offered("defense")
