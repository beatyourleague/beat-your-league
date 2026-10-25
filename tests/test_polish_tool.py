"""The free bye-week planner: site/byes/ and its data, render/bye_index.py.

The planner is the weekly report's "Byes ahead" check (engine.preseason
.bye_collisions, which run.solo._byes_ahead runs) put in front of anybody who
pastes a roster: facts off the published schedule and today's reserve list,
no projection, no percentage, nothing recorded. Everything that can make it
say something the weekly report would not is pinned here:

- byes.js is the browser's copy of the Python rule, held equal to it on hand
  fixtures and 500 seeded random rosters, with mutation checks showing the
  comparison can fail;
- the page's own logic, run on the live sample's roster, names the weeks
  run.solo._byes_ahead names;
- the data file is built the way the weekly report builds the same facts and
  refuses to publish a partial bye list;
- the page fetches only our own files, writes names only as text, carries the
  funnel's shared functions character for character, and renders no number
  that is a forecast.

Tests that run JavaScript skip without node, like tests/test_intake.py (CI has
it). Tests that need the nflverse cache skip without it, with the reason.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.availability import LIVE_ONLY_OUT, PRACTICE_SQUAD, ROSTER_OUT
from engine.preseason import bye_collisions, unfillable_slots

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
PAGE_PATH = SITE / "byes" / "index.html"
PAGE = PAGE_PATH.read_text(encoding="utf-8")
BYES_JS = SITE / "byes" / "byes.js"
ROSTER_JS = SITE / "join" / "roster.js"
EMAIL_JS = SITE / "email-check.js"
BYES_JSON = SITE / "join" / "byes.json"
PLAYERS_JSON = SITE / "join" / "players.json"
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")
RAW = REPO / "data" / "raw" / "nflverse"
# The live sample's roster (render.live_sample.LIVE_ROSTER) as join/ encodes it.
SAMPLE_REF = ("s4-pcQRRWWTFKD16-AJPKAIfsAJiAAJBtAJ9QAJh4AJ0KAJBjAJiYAJvvAJGNAJKpAHcqAHVt"
              "AHmg_yxg")
TODAY = "2026-10-24"

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available (CI has it)")


def _node(tmp_path: Path, script: str) -> object:
    """Run a script under node from a file and return the JSON it prints."""
    path = tmp_path / f"run-{hashlib.sha1(script.encode()).hexdigest()[:8]}.js"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, f"node failed:\n{done.stderr[-3000:]}"
    return json.loads(done.stdout)


def _js_function(page: str, name: str) -> str:
    """One top-level function's source, declaration to closing brace."""
    start = page.index(f"function {name}(")
    return page[start:page.index("\n}\n", start) + 2]


def _inline_script(page: str) -> str:
    scripts = [body for attrs, body in re.findall(r"<script([^>]*)>(.*?)</script>", page, re.S)
               if "src=" not in attrs and "ld+json" not in attrs]
    assert len(scripts) == 1, f"{len(scripts)} inline scripts"
    return scripts[0]


def _const(page: str, name: str) -> str:
    match = re.search(rf"^const {name} = (.+?);", page, re.M)
    assert match, f"no const {name}"
    return match.group(1)


def _directory() -> dict:
    return json.loads(PLAYERS_JSON.read_text(encoding="utf-8"))


def _byes() -> dict:
    return json.loads(BYES_JSON.read_text(encoding="utf-8"))


def _cache_or_skip() -> None:
    if not all((RAW / name).is_file() for name in ("games.csv", "players.csv",
                                                   "teams_colors_logos.csv")):
        pytest.skip("nflverse cache not present (a fresh checkout) — run `make byes`")


# --------------------------------------------------------------------- #
# the Python reference
# --------------------------------------------------------------------- #

def _thin(roster, slots) -> list[str]:
    """bye_collisions' always_empty, as a list (Counter.elements order)."""
    known = {r["player_id"]: r["position"] for r in roster if r["position"] != "UNK"}
    can = {r["player_id"]: r["position"] for r in roster
           if r["position"] != "UNK" and not r.get("out_today")}
    return list((Counter(unfillable_slots(slots, can))
                 - Counter(unfillable_slots(slots, known))).elements())


def _structural(roster, slots) -> list[str]:
    return unfillable_slots(slots, {r["player_id"]: r["position"] for r in roster
                                    if r["position"] != "UNK"})


def _python(cases: list[dict]) -> list[dict]:
    return [{"collisions": bye_collisions(c["roster"], c["slots"], c["weeks"]),
             "unfillable": unfillable_slots(c["slots"], c["available"]),
             "thin": _thin(c["roster"], c["slots"]),
             "structural": _structural(c["roster"], c["slots"])} for c in cases]


def _javascript(tmp_path: Path, cases: list[dict], source: Path = BYES_JS) -> list[dict]:
    script = (f"const B = require({json.dumps(str(source))});\n"
              f"const cases = JSON.parse(require('fs').readFileSync("
              f"{json.dumps(str(tmp_path / 'cases.json'))}, 'utf8'));\n"
              "console.log(JSON.stringify(cases.map((c) => ({"
              "collisions: B.byeCollisions(c.roster, c.slots, c.weeks),"
              "unfillable: B.unfillableSlots(c.slots, c.available),"
              "thin: B.thinSlots(c.roster, c.slots),"
              "structural: B.structural(c.roster, c.slots)}))));")
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    return _node(tmp_path, script)


def _row(pid, name, pos, bye, out=None):
    return {"player_id": pid, "name": name, "position": pos, "bye": bye, "out_today": out}


STD = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
FLEX2 = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
SF = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]
CORE = [_row("00-0000001", "Qb One", "QB", 9), _row("00-0000017", "Qb Two", "QB", 11),
        _row("00-0000002", "Rb One", "RB", 9),
        _row("00-0000003", "Rb Two", "RB", 10), _row("00-0000004", "Rb Three", "RB", 12),
        _row("00-0000005", "Wr One", "WR", 8), _row("00-0000006", "Wr Two", "WR", 10),
        _row("00-0000007", "Wr Three", "WR", 13), _row("00-0000008", "Te One", "TE", 14),
        _row("00-0000009", "K One", "K", 9), _row("DEF-KC", "Def One", "DEF", 5)]


def _fixtures() -> list[dict]:
    """The hand cases the spec names, each one a rule a careless port breaks."""
    def case(roster, slots, weeks=range(7, 18)):
        return {"roster": roster, "slots": list(slots), "weeks": list(weeks),
                "available": {r["player_id"]: r["position"] for r in roster
                              if r["position"] != "UNK" and not r.get("out_today")}}
    return [
        # A K-only hole whose short names only the kicker (the QB and an RB
        # are idle that week too, both covered).
        case(CORE, STD),
        # FLEX filled by a TE, and the WR hole it cannot hide.
        case(CORE + [_row("00-0000010", "Te Two", "TE", 8)], STD),
        # SUPER_FLEX filled by a QB; then a third QB's bye.
        case(CORE + [_row("00-0000011", "Qb Three", "QB", 13)], SF),
        # Two FLEX.
        case(CORE + [_row("00-0000012", "Wr Four", "WR", 11)], FLEX2),
        # An FB never covers an RB or a FLEX.
        case(CORE + [_row("00-0000013", "Fb One", "FB", 7)], STD),
        # A reserve player excluded, and named in "out".
        case(CORE + [_row("00-0000014", "Te Hurt", "TE", 7, "on injured reserve")], STD),
        # always_empty: the only kicker is on injured reserve, so K is thin
        # every week and no week is blamed on a bye for it.
        case([r for r in CORE if r["position"] != "K"]
             + [_row("00-0000015", "K Hurt", "K", 9, "on injured reserve")], STD),
        # A structural hole: no TE at all.
        case([r for r in CORE if r["position"] != "TE"], STD),
        # Weeks with no idle player are skipped.
        case(CORE, STD, weeks=[6, 9, 12, 14, 15]),
        # An unknown player never counts.
        case(CORE + [_row("00-0000016", "Nobody", "UNK", 9)], STD),
        # The id order decides which flex a receiver fills: the lowest id goes
        # first, so a port that walks the pool in insertion order disagrees.
        case([_row("00-0000099", "Te Late", "TE", None), _row("00-0000098", "Wr Early", "WR", None),
              _row("00-0000097", "Qb Q", "QB", 9)], ["QB", "REC_FLEX", "WRRB_FLEX"]),
    ]


def _random_cases(n: int = 500, seed: int = 7) -> list[dict]:
    """equiv.py's harness, ported: rosters drawn from the published directory,
    the committed season's real byes, every lineup the page offers plus the
    two odd flexes, and a random sprinkle of reserve-list players."""
    rng = random.Random(seed)
    directory = _directory()["players"]
    byes = {team: w["week"] for w in _byes()["weeks"] for team in w["bye"]}
    bases = [["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
             ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX"],
             ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"],
             ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"],
             ["QB", "RB", "WR", "TE", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"]]
    reasons = sorted(set(ROSTER_OUT.values()))
    by_pos: dict[str, list] = {}
    for name, pid, pos, team, *_ in directory:
        by_pos.setdefault(pos, []).append((name, pid, pos, team))
    cases = []
    for _ in range(n):
        slots = (list(rng.choice(bases)) + (["K"] if rng.random() < .8 else [])
                 + (["DEF"] if rng.random() < .8 else []))
        want = {"QB": rng.randint(1, 3), "RB": rng.randint(1, 6), "WR": rng.randint(1, 7),
                "TE": rng.randint(0, 3), "K": rng.randint(0, 2), "DEF": rng.randint(0, 2),
                "FB": rng.randint(0, 1)}
        picks = {}
        for pos, k in want.items():
            for row in rng.sample(by_pos.get(pos, []), min(k, len(by_pos.get(pos, [])))):
                picks[row[1]] = row
        rows = list(picks.values())
        rng.shuffle(rows)
        roster = [_row(pid, name, pos, byes.get(team) if team else None,
                       rng.choice(reasons) if rng.random() < .08 else None)
                  for name, pid, pos, team in rows[:rng.randint(len(slots), 20)]]
        available = {r["player_id"]: r["position"] for r in roster
                     if not r["out_today"] and r["bye"] != 9}
        cases.append({"roster": roster, "slots": slots,
                      "weeks": list(range(rng.randint(1, 17), 18)), "available": available})
    return cases


# --------------------------------------------------------------------- #
# 1. byes.js IS engine.preseason
# --------------------------------------------------------------------- #

@needs_node
def test_the_planner_rule_equals_the_weekly_reports_rule_on_the_hand_cases(tmp_path) -> None:
    """Every spec'd fixture, exact JSON both ways: a K-only hole that names
    only the kicker, FLEX filled by a TE, SUPER_FLEX by a QB, two FLEX, an FB
    that never covers, a reserve player excluded and named, the always-empty
    (thin) case, a structural hole, weeks with nobody idle skipped."""
    cases = _fixtures()
    expected = _python(cases)
    assert _javascript(tmp_path, cases) == expected
    # The fixtures say what they claim to (so a passing comparison is not two
    # wrong answers agreeing on a case that tests nothing).
    assert expected[0]["collisions"][0] == {"week": 9, "slots": ["K"],
                                            "players": ["K One", "Qb One", "Rb One"],
                                            "short": ["K One"], "out": []}
    assert [h["out"] for h in expected[5]["collisions"] if h["week"] == 14] == \
        [["Te Hurt (on injured reserve)"]]
    assert expected[6]["thin"] == ["K"] and all("K" not in h["slots"]
                                                for h in expected[6]["collisions"])
    assert expected[7]["structural"] == ["TE"]
    # 6 and 15: nobody idle, skipped; 12: idle but covered.
    assert [h["week"] for h in expected[8]["collisions"]] == [9, 14]
    # The fullback changes nothing: Week 10's FLEX hole stays a hole.
    holes = lambda e: [(h["week"], h["slots"]) for h in e["collisions"]]  # noqa: E731
    assert holes(expected[4]) == holes(expected[0]) and (10, ["FLEX"]) in holes(expected[0])
    assert expected[10]["unfillable"] == ["WRRB_FLEX"]


@needs_node
def test_the_planner_rule_equals_the_weekly_reports_rule_on_500_random_rosters(tmp_path) -> None:
    """The prototype matched on 3,000 random rosters; 500 seeded ones run on
    every push. A disagreement means the free planner and the weekly report's
    "Byes ahead" tell one manager two different things about the same week."""
    cases = _random_cases()
    expected = _python(cases)
    got = _javascript(tmp_path, cases)
    bad = [i for i, (a, b) in enumerate(zip(expected, got)) if a != b]
    assert not bad, (f"{len(bad)} disagreements, first: {json.dumps(cases[bad[0]])[:600]} "
                     f"python={expected[bad[0]]} js={got[bad[0]]}")
    # The sample exercises what matters: holes, out names and thin spots.
    assert sum(1 for e in expected if e["collisions"]) > 50
    assert any(h["out"] for e in expected for h in e["collisions"])
    assert any(e["thin"] for e in expected)


@needs_node
@pytest.mark.parametrize("old,new", [
    # The restrictiveness sort: a FLEX would take a back before RB could.
    ("(restrictiveness(slots[i]) - restrictiveness(slots[j]))\n      || ", ""),
    # The id sort: the pool walked in insertion order.
    ("const ids = [...pool.keys()].sort(byCodePoint);", "const ids = [...pool.keys()];"),
])
def test_the_comparison_catches_a_port_that_drops_a_sort(tmp_path, old, new) -> None:
    """Mutation check: without either ordering rule the browser's answer
    differs from Python's somewhere in the same cases, so the two tests above
    can fail — they are not two copies agreeing by construction."""
    source = BYES_JS.read_text(encoding="utf-8")
    assert source.count(old) == 1
    mutant = tmp_path / "byes-mutant.js"
    mutant.write_text(source.replace(old, new), encoding="utf-8")
    cases = _fixtures() + _random_cases(200)
    assert _javascript(tmp_path, cases, mutant) != _python(cases)


# --------------------------------------------------------------------- #
# 2. the page and the weekly report name the same weeks
# --------------------------------------------------------------------- #

def _week_data(players_rows, season_byes, roster_out, week, last_week):
    directory = SimpleNamespace(players=[
        SimpleNamespace(player_id=r[1], name=r[0], position=r[2], team=r[3] or None)
        for r in players_rows])
    return SimpleNamespace(is_live_week=True, season_byes=season_byes, last_week=last_week,
                           week=week, directory=directory, roster_out=dict(roster_out))


def _page_weeks(tmp_path, players_payload, byes_payload, ids, slots, today) -> dict:
    """The page's own path: roster.js reads the directory, byes.js builds the
    rows and describes the weeks — exactly what the inline script calls."""
    (tmp_path / "p.json").write_text(json.dumps(players_payload), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(byes_payload), encoding="utf-8")
    script = (f"const R = require({json.dumps(str(ROSTER_JS))});\n"
              f"const B = require({json.dumps(str(BYES_JS))});\n"
              "const fs = require('fs');\n"
              f"const players = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'p.json'))}));\n"
              f"const byes = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'b.json'))}));\n"
              "const dir = R.buildDirectory(players);\n"
              f"const ids = {json.dumps(list(ids))};\n"
              f"const slots = {json.dumps(list(slots))};\n"
              "const rows = B.rosterRows(ids.map((id) => dir.byId.get(id)), byes);\n"
              f"const plan = B.describe(rows, slots, byes, {json.dumps(today)});\n"
              "const weeks = []; for (let w = plan.from; w <= plan.through; w++) weeks.push(w);\n"
              "console.log(JSON.stringify({plan, from: plan.from,"
              " collisions: B.byeCollisions(rows, slots, weeks)}));")
    return _node(tmp_path, script)


def _same_weeks(page: dict, ahead: list[dict]) -> None:
    keys = ("week", "slots", "players", "short", "out")
    want = [{k: h[k] for k in keys} for h in ahead if h["week"] <= 17]
    # The weekly report plans the weeks AFTER this one; the planner includes it.
    got = [{k: h[k] for k in keys} for h in page["collisions"] if h["week"] > page["from"]]
    assert got == want
    empty = [w["week"] for w in page["plan"]["weeks"] if w["kind"] == "empty"]
    assert [w for w in empty if w > page["from"]] == [h["week"] for h in want]


@needs_node
def test_the_planner_names_the_weeks_the_weekly_report_names(tmp_path, monkeypatch) -> None:
    """The live sample's roster, the sample's lineup, the committed data, Oct
    24 2026 (Week 7): the page's weeks equal run.solo._byes_ahead's up to
    Week 17. On the data committed with the planner that is one week, Week 9,
    the K spot, Chris Boswell — the acceptance case. Deterministic: both sides
    read the same committed files, so CI runs it without the cache."""
    from render.live_sample import LIVE_ROSTER
    from render.sample import SLOTS
    from run import solo
    players, byes = _directory(), _byes()
    week = next(w["week"] for w in byes["weeks"] if w["ends"] >= TODAY)
    data = _week_data(players["players"],
                      {team: w["week"] for w in byes["weeks"] for team in w["bye"]},
                      byes["out"], week, byes["last_week"])
    monkeypatch.setattr(solo, "_bye_cover", lambda *a, **k: [])
    spec = SimpleNamespace(player_ids=tuple(LIVE_ROSTER), slots=tuple(SLOTS))
    ahead = solo._byes_ahead(spec, data)
    page = _page_weeks(tmp_path, players, byes, LIVE_ROSTER, SLOTS, TODAY)
    assert page["from"] == week == 7
    _same_weeks(page, ahead)


@needs_node
def test_the_planner_and_the_weekly_report_agree_on_the_caches_own_facts(tmp_path, monkeypatch) -> None:
    """The same comparison with each side built from the cache the way it
    builds it in production: the weekly report from load_directory,
    bye_by_team and roster_out (WeekData), the planner from bye_index.build
    and the directory render.player_index publishes."""
    _cache_or_skip()
    from engine.availability import roster_out
    from engine.preseason import bye_by_team
    from engine.roster import load_directory
    from ingest.nflverse import season_teams
    from render import bye_index, player_index
    from render.live_sample import LIVE_ROSTER
    from render.sample import SLOTS
    from run import solo
    season = "2026"
    directory = load_directory(RAW / "players.csv", RAW / "teams_colors_logos.csv",
                               min_last_season=int(season) - 1,
                               eligible_teams=season_teams(RAW, season))
    players = player_index.build(directory, season)
    byes = bye_index.build(season, RAW, players)
    week = solo.current_week(RAW, season, date.fromisoformat(TODAY), live=False)
    data = SimpleNamespace(is_live_week=True, season_byes=bye_by_team(RAW, season),
                           last_week=solo.last_week(RAW, season, live=False), week=week,
                           directory=directory, roster_out=roster_out(RAW / "players.csv"))
    monkeypatch.setattr(solo, "_bye_cover", lambda *a, **k: [])
    spec = SimpleNamespace(player_ids=tuple(LIVE_ROSTER), slots=tuple(SLOTS))
    missing = [pid for pid in LIVE_ROSTER if pid not in {p.player_id for p in directory.players}]
    if missing:
        pytest.skip(f"the cached directory no longer carries {missing}")
    _same_weeks(_page_weeks(tmp_path, players, byes, LIVE_ROSTER, SLOTS, TODAY),
                solo._byes_ahead(spec, data))


# --------------------------------------------------------------------- #
# 3. the page's contract
# --------------------------------------------------------------------- #

def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def test_the_page_loads_the_scripts_it_was_tested_with_in_order() -> None:
    """roster.js at join/'s own digest (the parser the intake tests run),
    byes.js at its own, email-check.js at the landing's, ONE inline script
    (make headers hashes it), then the counter — and nothing else."""
    srcs = re.findall(r'<script src="([^"]+)"', PAGE)
    assert srcs == [f"../join/roster.js?v={_digest(ROSTER_JS)}", f"byes.js?v={_digest(BYES_JS)}",
                    f"/email-check.js?v={_digest(EMAIL_JS)}", "/count.js"]
    assert f'<script src="roster.js?v={_digest(ROSTER_JS)}"></script>' in JOIN
    assert f'<script src="/email-check.js?v={_digest(EMAIL_JS)}"></script>' in LANDING
    _inline_script(PAGE)
    from render.report import COUNT_TAG
    body = PAGE[:PAGE.index("</body>")]
    assert body.rstrip().endswith(COUNT_TAG) and PAGE.count("count.js") == 1
    assert PAGE.index(f"byes.js?v=") < PAGE.index("<script>\n")


def test_the_page_fetches_only_our_own_files() -> None:
    """Two same-origin reads — the player list and this season's byes, beside
    each other in join/ — and the launch list's endpoint on submit. No other
    request, and no library from anywhere."""
    code = _inline_script(PAGE)
    assert sorted(re.findall(r'getJson\("([^"]+)"\)', code)) == ["../join/byes.json",
                                                                 "../join/players.json"]
    calls = re.findall(r"\bfetch\(([^,)]+)", code)
    assert sorted(calls) == ["NOTIFY_LIST_ENDPOINT", "url"], calls
    assert "fetch(" not in BYES_JS.read_text(encoding="utf-8")
    absolute = re.findall(r'(?:src|href)="((?:https?:)?//[^"]*)"', PAGE)
    assert absolute == ["https://beatyourleague.com/byes/"], absolute   # the canonical only


def test_no_name_ever_reaches_the_page_as_markup() -> None:
    """Every name is a text node: a roster box is arbitrary typed input."""
    for text in (PAGE, BYES_JS.read_text(encoding="utf-8")):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in text, sink


def test_the_funnels_shared_functions_are_copied_character_for_character() -> None:
    """carryVia and the VIA sanitiser as on the landing (tests/test_site.py
    holds every other copy), whyUnread and lineupWords as on join/, shareLine
    as on league-pass.html — so the planner can never explain a name, a
    lineup or a share differently from the page it hands the visitor to."""
    code = _inline_script(PAGE)
    assert _js_function(code, "carryVia") == _js_function(LANDING, "carryVia")
    via = r"const VIA = .*?\|\| undefined;"
    assert re.search(via, code, re.S).group(0) == re.search(via, LANDING, re.S).group(0)
    for name in ("whyUnread", "lineupWords"):
        assert _js_function(code, name) == _js_function(JOIN, name), name
    assert _js_function(code, "shareLine") == _js_function(LEAGUE_PASS, "shareLine")
    assert 'a.setAttribute("href", carryVia(a.getAttribute("href"), VIA))' in code
    assert not re.search(r"localStorage|sessionStorage|document\.cookie", code)


def test_the_planners_switches_are_join_and_the_landings_own() -> None:
    """Launch morning sets the endpoint on join/ and flips the landing's
    flags; a planner left behind would post its waitlist rows nowhere, or
    show a checkout link that cannot finish (T3 adds the launch-check gate)."""
    code = _inline_script(PAGE)
    assert _const(code, "NOTIFY_LIST_ENDPOINT") == _const(JOIN, "NOTIFY_LIST_ENDPOINT")
    assert _const(code, "CHECKOUT_CAN_COMPLETE") == _const(LANDING, "CHECKOUT_CAN_COMPLETE")
    assert _const(code, "TRIAL_OPEN") == _const(LANDING, "TRIAL_OPEN")


def test_the_page_is_an_indexed_site_page_with_its_own_head() -> None:
    """Indexed (in the sitemap, canonical to itself), the site's one nav and
    its stylesheet verbatim, the shared social tags and favicon, no JSON-LD,
    and a static closed state: the email capture, with the open state's links
    hidden until the script decides."""
    import render.report as rr
    from render import sitemap
    assert "<title>Fantasy football bye week planner (2026): check your roster through " \
           "Week 17 — Beat Your League</title>" in PAGE
    assert '<link rel="canonical" href="https://beatyourleague.com/byes/">' in PAGE
    assert sitemap.url_for(PAGE_PATH) == "https://beatyourleague.com/byes/"
    assert "https://beatyourleague.com/byes/" in (SITE / "sitemap.xml").read_text()
    assert "noindex" not in PAGE and "ld+json" not in PAGE
    assert rr.site_bar("../") in PAGE and rr.SITE_BAR_CSS in PAGE
    assert rr.SOCIAL_IMAGE_TAGS in PAGE and rr.FAVICON_LINK in PAGE
    for needle in ('property="og:title" content="Free bye week planner — your roster, '
                   'through Week 17"', 'name="twitter:description"', 'property="og:description"'):
        assert needle in PAGE
    assert 'id="cta-form"' in PAGE
    assert re.search(r'<a class="golink" id="cta-go"[^>]*hidden>', PAGE)
    assert re.search(r'<a class="ghostlink" id="cta-try"[^>]*hidden>', PAGE)
    assert '<a class="textlink" href="../sample-report.html">See a real report</a>' in PAGE
    # The paper pages' rules (tests/test_prelaunch_pages.py, for when the page
    # joins NAV_PAGES): no home pill, and only what you can press lifts.
    assert 'class="home"' not in PAGE
    style = "\n".join(re.findall(r"<style>(.*?)</style>", PAGE, re.S))
    for selector, body in re.findall(r"([^{}]+):hover[^{]*\{([^}]*)\}", style):
        if "transform:translate" in body:
            assert re.search(r"\bbutton\b|(?<![\w.#-])a(?![\w-])|\.btn\b|\.cardbtn\b",
                             selector), selector
    # A selling surface: it links no grading page (the owner's selling rule).
    for grading in ("backtest", "confidence", "projections", "no-call", "compare", "ledger"):
        assert not re.search(rf'href="[^"]*{grading}', PAGE), grading
    # Without JavaScript: the note, the controls not drawn, the table below.
    assert "<noscript><p class=\"nojs\">The planner needs JavaScript. Every 2026 bye week " \
           "is listed below.</p></noscript>" in PAGE
    assert ".needs-js{display:none!important;}" in PAGE


# --------------------------------------------------------------------- #
# 4. the page, run: facts only, and every state's words
# --------------------------------------------------------------------- #

# A DOM just big enough for the planner's script, so the page's own code runs
# under node exactly as written. Every string the script puts on the page is
# kept (textContent and text nodes), with each element's final text.
DOM_STUB = r"""
const vm = require("vm"), fs = require("fs");
const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const html = fs.readFileSync(cfg.page, "utf8");
const said = [];
class Text { constructor(t) { this.t = String(t); said.push(this.t); }
  get textContent() { return this.t; } }
class El {
  constructor(tag, id) {
    this.tagName = String(tag || "div").toUpperCase(); this.id = id || "";
    this.children = []; this._text = ""; this.className = ""; this.hidden = false;
    this.disabled = false; this.value = ""; this.open = false; this.attrs = {};
    this.listeners = {}; this.parent = null; this.title = "";
    const props = {};
    this.style = { setProperty: (k, v) => { props[k] = v; } };
    const self = this;
    this.classList = {
      add(c) { if (!self.has(c)) self.className = (self.className + " " + c).trim(); },
      remove(c) { self.className = self.className.split(/\s+/).filter((x) => x !== c).join(" "); },
      toggle(c, on) { (on === undefined ? !self.has(c) : on) ? this.add(c) : this.remove(c); },
      contains(c) { return self.has(c); },
    };
  }
  has(c) { return this.className.split(/\s+/).includes(c); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this._text = String(v); this.children = []; said.push(this._text); }
  get childElementCount() { return this.children.filter((c) => c instanceof El).length; }
  appendChild(n) { this.children.push(n); n.parent = this; return n; }
  replaceChildren(...ns) { this.children = []; this._text = ""; ns.forEach((n) => this.appendChild(n)); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, extra) { for (const f of this.listeners[t] || []) f(Object.assign({ preventDefault() {}, target: this }, extra || {})); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  focus() {} closest() { return new El("div"); } contains() { return false; }
  all() { return this.children.filter((c) => c instanceof El).flatMap((c) => [c, ...c.all()]); }
  querySelectorAll(sel) {
    if (sel[0] === ".") return this.all().filter((e) => e.has(sel.slice(1)));
    return this.all().filter((e) => e.tagName === sel.toUpperCase());
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const byId = new Map();
// The static markup's own state, read off each id'd tag: disabled, hidden
// and an inline display:none are what the script starts from.
for (const m of html.matchAll(/<(\w+)\b([^>]*?)\bid="([^"]+)"([^>]*)>/g)) {
  const attrs = " " + m[2] + " " + m[4] + " ";
  const e = new El(m[1], m[3]);
  e.disabled = /\sdisabled\s/.test(attrs);
  e.hidden = /\shidden\s/.test(attrs);
  if (/style="display:none"/.test(attrs)) e.style.display = "none";
  byId.set(m[3], e);
}
const radios = [];
for (const m of html.matchAll(/<input type="radio" name="(\w+)" value="([^"]+)"( checked)?/g)) {
  const r = new El("input"); r.name = m[1]; r.value = m[2]; r.checked = Boolean(m[3]); radios.push(r);
}
const document = {
  getElementById(id) { if (!byId.has(id)) byId.set(id, new El("div", id)); return byId.get(id); },
  createElement(tag) { return new El(tag); },
  createTextNode(t) { return new Text(t); },
  addEventListener() {},
  querySelectorAll(sel) { return sel === "a[href]" ? [] : []; },
  querySelector(sel) {
    let m = /^input\[name="(\w+)"\]:checked$/.exec(sel);
    if (m) return radios.find((r) => r.name === m[1] && r.checked) || null;
    m = /^input\[name="(\w+)"\]\[value="([^"]+)"\]$/.exec(sel);
    if (m) {
      const r = radios.find((x) => x.name === m[1] && x.value === m[2]);
      if (r) return { set checked(v) { radios.filter((x) => x.name === r.name).forEach((x) => { x.checked = false; }); r.checked = v; } };
      return null;
    }
    return null;
  },
};
let lastUrl = null;
const files = { "../join/players.json": cfg.players, "../join/byes.json": cfg.byes };
const fetch = (url) => {
  if (cfg.fail) return Promise.reject(new Error("offline"));
  if (!(url in files)) return Promise.reject(new Error("unexpected fetch " + url));
  const data = JSON.parse(fs.readFileSync(files[url], "utf8"));
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
};
const ctx = vm.createContext({ document, fetch, URLSearchParams, btoa, atob, console, setTimeout,
  location: { search: cfg.search, pathname: "/byes/", hash: "" },
  history: { replaceState(s, t, url) { lastUrl = url; } }, navigator: {}, Intl, Date });
ctx.window = vm.runInContext("this", ctx);
const RealDate = Date;
if (cfg.today) {
  const fixed = new RealDate(cfg.today + "T16:00:00Z").getTime();
  ctx.Date = class extends RealDate { constructor(...a) { super(...(a.length ? a : [fixed])); }
    static now() { return fixed; } };
}
for (const src of [cfg.roster, cfg.byesJs, cfg.email]) vm.runInContext(fs.readFileSync(src, "utf8"), ctx);
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
vm.runInContext(inline[0], ctx);
const tick = () => new Promise((r) => setTimeout(r, 20));
(async () => {
  for (let i = 0; i < 5; i++) await tick();
  if (cfg.paste !== null && cfg.paste !== undefined) {
    document.getElementById("roster-text").value = cfg.paste;
    document.getElementById("form-roster").fire("submit");
    for (let i = 0; i < 3; i++) await tick();
  }
  // What the CTA said after the check, then an edit to the box (stale).
  const ctaChecked = { button: document.getElementById("cta-button").textContent,
    settingsHidden: document.getElementById("cta-settings").hidden,
    go: document.getElementById("cta-go").getAttribute("href") };
  if (cfg.edit !== null && cfg.edit !== undefined) {
    document.getElementById("roster-text").value = cfg.edit;
    document.getElementById("roster-text").fire("input");
    for (let i = 0; i < 3; i++) await tick();
  }
  const text = (id) => document.getElementById(id).textContent;
  const weeks = document.getElementById("weeks").children.map((li) => li.textContent);
  const rows = document.getElementById("rows").querySelectorAll(".row").map((r) => r.textContent);
  console.log(JSON.stringify({ said, weeks, rows, lastUrl,
    summary: text("summary"), tally: text("tally"), err: text("err-roster"), thin: text("thin"),
    head: text("byes-head"), asOf: text("as-of"), footnote: text("footnote"),
    playoffNone: text("playoff-none"), check: document.getElementById("check").disabled,
    share: !document.getElementById("share").hidden,
    summaryClass: document.getElementById("summary").className, ctaChecked,
    ctaButton: document.getElementById("cta-button").textContent,
    ctaSettingsHidden: document.getElementById("cta-settings").hidden,
    ctaGo: document.getElementById("cta-go").getAttribute("href"),
    retry: document.getElementById("retry-load").style.display }));
})();
"""


def _run_page(tmp_path: Path, search: str = "", paste: str | None = None, fail: bool = False,
              byes: dict | None = None, today: str = TODAY, consts: dict | None = None,
              edit: str | None = None) -> dict:
    """``consts``: the page with those top-level constants set (the launch
    flip: an endpoint, an open checkout). ``edit``: text typed over the box
    after the check, so the list on screen goes stale."""
    byes_path = BYES_JSON
    if byes is not None:
        byes_path = tmp_path / "byes-variant.json"
        byes_path.write_text(json.dumps(byes), encoding="utf-8")
    page_path = PAGE_PATH
    if consts:
        page = PAGE
        for name, value in consts.items():
            page, n = re.subn(rf"^const {name} = .+?;$", f"const {name} = {value};", page,
                              count=1, flags=re.M)
            assert n == 1, name
        page_path = tmp_path / "page-variant.html"
        page_path.write_text(page, encoding="utf-8")
    cfg = {"page": str(page_path), "players": str(PLAYERS_JSON), "byes": str(byes_path),
           "roster": str(ROSTER_JS), "byesJs": str(BYES_JS), "email": str(EMAIL_JS),
           "search": search, "paste": paste, "fail": fail, "today": today, "edit": edit}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
    stub = tmp_path / "dom-stub.js"
    stub.write_text(DOM_STUB, encoding="utf-8")
    done = subprocess.run(["node", str(stub), str(tmp_path / "cfg.json")], capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout)


FORECAST_WORDS = re.compile(r"%|project|odds|chance", re.I)


@needs_node
def test_the_sample_roster_renders_the_acceptance_case_and_nothing_but_facts(tmp_path) -> None:
    """The live sample's ref on Oct 24: Week 7 through 17, exactly one empty
    week — "Week 9 · K spot empty · On bye: Chris Boswell. Nobody else on
    your roster can start there." — and De'Von Achane and Travis Etienne read
    "on injured reserve". No string the page renders may contain '%',
    'project', 'odds' or 'chance': the planner makes no forecast, so it
    carries no calibration or ledger burden."""
    out = _run_page(tmp_path, search="?ref=" + SAMPLE_REF)
    assert out["head"] == "3 · Your byes, Week 7 to Week 17"
    assert out["summary"] == "1 week leaves a starting spot empty: Week 9."
    assert [int(re.match(r"Week (\d+)", w).group(1)) for w in out["weeks"]] == list(range(7, 18))
    assert out["weeks"][0].startswith("Week 7 · this week")
    empty = [w for w in out["weeks"] if "empty" in w]
    assert empty == ["Week 9K spot emptyOn bye: Chris Boswell. Nobody else on your roster "
                     "can start there."]
    assert out["weeks"][8] == "Week 15Fantasy playoffs*Nobody on your roster is on bye."
    assert out["weeks"][10] == "Week 17Title game*Nobody on your roster is on bye."
    ir = [r for r in out["rows"] if "injured reserve" in r]
    assert [r.split("RB")[0] for r in ir] == ["De'Von Achane", "Travis Etienne"]
    assert all(r.endswith("on injured reserve×") for r in ir)
    assert out["playoffNone"] == "No NFL team has a bye in Weeks 15–17."
    assert out["footnote"].startswith("*Under ESPN's, Yahoo's and Sleeper's default settings")
    assert out["asOf"].startswith("Reserve-list status as of ")
    assert out["share"] and not out["check"]
    # The address keeps the roster (the same ref, no email).
    assert out["lastUrl"] == "/byes/?ref=" + SAMPLE_REF
    for line in out["said"] + out["weeks"] + out["rows"]:
        assert not FORECAST_WORDS.search(line), line


@needs_node
def test_every_state_says_what_the_spec_says(tmp_path) -> None:
    """Load failure (with the roster kept), an empty press, names that need a
    look (nothing checked: RULE R3), a structural hole (no week list), and a
    season whose byes are behind it."""
    failed = _run_page(tmp_path, fail=True)
    assert failed["err"] == "We couldn't load the player list and bye weeks just now."
    assert failed["retry"] == "block" and failed["check"] is True

    empty = _run_page(tmp_path, paste="")
    assert empty["tally"] == "Paste or add at least one player." and not empty["weeks"]

    one = _run_page(tmp_path, paste="Josh Allen\n")
    assert one["tally"] == ("Your lineup has 9 starting spots and you've listed 1 player. "
                            "Add the rest.") and not one["weeks"]

    unread = _run_page(tmp_path, paste="Josh Allen\nNot A Player Anywhere\nHurts\n")
    assert unread["tally"] == "2 names need a look before we can check your byes."
    assert not unread["weeks"] and unread["summary"] == ""

    roster = "\n".join(["Brock Purdy", "Lamar Jackson", "Quinshon Judkins", "Tyjae Spears",
                        "Amon-Ra St. Brown", "Zay Flowers", "Rome Odunze", "Khalil Shakir",
                        "Chris Boswell", "Kansas City Chiefs"])
    hole = _run_page(tmp_path, paste=roster)
    assert hole["summary"] == ("Your roster has nobody left to start at TE, so that spot is "
                               "empty every week, byes or not. Add one.")
    assert not hole["weeks"] and not hole["share"]

    no_k = _run_page(tmp_path, paste=roster.replace("Chris Boswell\n", "")
                     .replace("Kansas City Chiefs", "Travis Kelce"))
    assert no_k["summary"].endswith("byes or not. Add players for them, or set Kicker to No K "
                                    "and Team defense to No DEF above.")

    over = _run_page(tmp_path, search="?ref=" + SAMPLE_REF, today="2027-02-01")
    assert over["summary"] == ("The 2026 season's bye weeks are behind us. The planner opens "
                               "again when next season's schedule is out.")
    assert over["check"] is True and not over["weeks"]
    for out in (failed, empty, unread, hole, no_k, over):
        for line in out["said"]:
            assert not FORECAST_WORDS.search(line), line


@needs_node
def test_no_byes_left_still_lists_the_weeks(tmp_path) -> None:
    """A schedule with no bye between this week and 17 says there is nothing
    to plan around, and still shows the weeks."""
    byes = _byes()
    for week in byes["weeks"]:
        if week["week"] >= 7:
            week["bye"] = []
    out = _run_page(tmp_path, search="?ref=" + SAMPLE_REF, byes=byes)
    assert out["summary"] == ("No NFL team has a bye from Week 7 through Week 17 — nothing "
                              "to plan around.")
    assert len(out["weeks"]) == 11


def _player_id(name: str) -> str:
    [pid] = [row[1] for row in _directory()["players"] if row[0] == name]
    return pid


THIN_ROSTER = ["Brock Purdy", "Lamar Jackson", "Quinshon Judkins", "Tyjae Spears", "Devin Neal",
               "Amon-Ra St. Brown", "Zay Flowers", "Rome Odunze", "Khalil Shakir",
               "Rashid Shaheed", "Chris Boswell", "Brandon Aubrey", "Kansas City Chiefs",
               "Bryson Nesbit"]


@needs_node
def test_a_spot_the_reserve_list_empties_every_week_is_never_good_news(tmp_path) -> None:
    """Planner review, reproduced: with the roster's only TE on injured
    reserve and no bye leaving a hole, the summary read "No week from 7
    through 17 leaves a starting spot empty. Every bye on your roster is
    covered." in green — directly above a red line saying the TE spot is empty
    every week — and "Copy my result" broadcast it. The summary is scoped to
    byes now, names the spot, and is never styled good; and a covered week
    with ONE player on bye no longer says "Each of them"."""
    byes = _byes()
    byes["out"] = dict(byes.get("out") or {}, **{_player_id("Bryson Nesbit"): "on injured reserve"})
    out = _run_page(tmp_path, paste="\n".join(THIN_ROSTER) + "\n", byes=byes)
    assert out["thin"].startswith("Every week, byes or not: nobody can start at TE")
    if out["summary"].startswith("No bye"):
        assert out["summary"] == ("No bye from Week 7 through Week 17 empties another spot — "
                                  "but your TE spot is empty every week, byes or not.")
    assert "TE spot is empty every week" in out["summary"]
    assert "good" not in out["summaryClass"].split() and "bad" in out["summaryClass"].split()
    covered = [w for w in out["weeks"] if "Covered" in w]
    assert covered
    for week in covered:
        names = week.split("On bye: ")[1].split(".")[0]
        single = " and " not in names and ", " not in names
        assert week.endswith("That bye opens no new empty spot." if single
                             else "Those byes open no new empty spot."), week


@needs_node
def test_a_list_that_starts_in_the_playoffs_says_no_byes_once(tmp_path) -> None:
    """Planner review: from Week 15 on, the summary "No NFL team has a bye
    from Week 15 through Week 17 — nothing to plan around." was repeated by
    the fine print "No NFL team has a bye in Weeks 15–17." It is said once."""
    out = _run_page(tmp_path, search="?ref=" + SAMPLE_REF, today="2026-12-15")
    assert out["summary"] == ("No NFL team has a bye from Week 15 through Week 17 — nothing "
                              "to plan around.")
    assert out["playoffNone"] == ""
    assert out["footnote"].startswith("*Under ESPN's")


@needs_node
def test_the_closed_button_promises_a_kept_roster_only_when_one_is_kept(tmp_path) -> None:
    """Planner review, reproduced: the closed button always read "Keep my
    roster — email me when it opens", while with no list endpoint (today's
    configuration, join/'s too) the fallback email carries only the address
    and the note after it says "Your roster isn't saved with us" — and with no
    roster checked nothing is kept at all. It is the site's "Tell me when it
    opens" unless an endpoint is set AND a clean roster is on screen; the
    scoring and size questions, which shape only the kept roster, wait for it."""
    closed = _run_page(tmp_path, search="?ref=" + SAMPLE_REF)
    assert closed["ctaChecked"]["button"] == "Tell me when it opens"
    assert closed["ctaChecked"]["settingsHidden"] is False
    fresh = _run_page(tmp_path, paste="")
    assert fresh["ctaButton"] == "Tell me when it opens" and fresh["ctaSettingsHidden"] is True
    listed = _run_page(tmp_path, search="?ref=" + SAMPLE_REF, edit="Josh Allen\n",
                       consts={"NOTIFY_LIST_ENDPOINT": '"https://forms.beatyourleague.com/rows"'})
    assert listed["ctaChecked"]["button"] == "Keep my roster for launch"
    assert listed["ctaButton"] == "Tell me when it opens", "an edited roster is not the kept one"
    assert listed["ctaSettingsHidden"] is True


@needs_node
def test_the_open_states_link_never_carries_a_roster_the_visitor_changed(tmp_path) -> None:
    """Planner review, reproduced (latent until checkout opens): state.ref was
    never cleared, so after the box was edited the gold "Get the weekly report
    for this roster" link still carried the last clean roster, and join/
    restored a roster the visitor had just changed. A stale or unready list
    sends the link back to the bare join page."""
    out = _run_page(tmp_path, search="?ref=" + SAMPLE_REF, edit="Josh Allen\nBijan Robinson\n",
                    consts={"CHECKOUT_CAN_COMPLETE": "true"})
    assert out["ctaChecked"]["go"] == "../join/index.html?ref=" + SAMPLE_REF
    assert out["ctaGo"] == "../join/index.html"


@needs_node
def test_the_reserve_list_is_dated_from_its_own_download(tmp_path) -> None:
    """Planner review: the page dated the reserve list from "generated" (the
    moment the file was written), so a cron that fell back to a days-old
    cached players release during an nflverse outage labelled it as today's.
    It reads reserve_as_of, the players file's own write time."""
    byes = dict(_byes(), generated="2026-10-24T14:00:00+00:00",
                reserve_as_of="2026-10-20T14:00:00+00:00")
    out = _run_page(tmp_path, search="?ref=" + SAMPLE_REF, byes=byes)
    assert out["asOf"].startswith("Reserve-list status as of Tue, Oct 20 ")


def test_the_season_in_the_title_and_noscript_line_follows_the_data() -> None:
    """Planner review: the generator rewrote only the table, so after the
    September rollover the cron would have published 2027 byes under a page
    titled 2026. The title, description and no-script line follow the
    season, and a page missing one of them refuses rather than guessing."""
    from render import bye_index
    page = bye_index.with_season(PAGE, "2027")
    assert "<title>Fantasy football bye week planner (2027):" in page
    assert "Every 2027 bye, by week." in page and "Every 2027 bye week is listed below." in page
    assert "2026" not in page.split("<!-- byes:start -->")[0].replace("2026-", "")
    assert bye_index.with_season(PAGE, "2026") == PAGE
    with pytest.raises(bye_index.ByeIndexError):
        bye_index.with_season(PAGE.replace("bye week is listed below", "byes are below"), "2027")


def test_the_data_carries_the_reserve_lists_own_date() -> None:
    """reserve_as_of is in the committed file and never later than it was
    written."""
    data = _byes()
    assert data["reserve_as_of"] <= data["generated"]


# --------------------------------------------------------------------- #
# 5. the site's sweeps, on this page
# --------------------------------------------------------------------- #

def _visible(page: str) -> str:
    text = re.sub(r"<head>.*?</head>|<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->",
                  " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def _script_strings() -> str:
    """Every string literal the page's script and byes.js can render."""
    code = _inline_script(PAGE) + BYES_JS.read_text(encoding="utf-8")
    code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("//"))
    return " ".join(re.findall(r'"((?:[^"\\]|\\.)*)"', code))


def test_the_planner_passes_the_sites_copy_sweeps() -> None:
    """The owner's rules, on every word this page can show: no Grade-C word,
    no betting word but "not betting picks", no developer vocabulary
    (test_site._DEV_SPEAK), "report" never "file", and no personal address.
    The page is not in test_site's hand-kept lists, so it is swept here."""
    from test_site import _DEV_SPEAK
    words = _visible(PAGE) + " " + _script_strings()
    assert not re.search(r"\b(calibrated|tested|proven|accurate)\b|we hit \d", words, re.I)
    betting = r"\b(bet|bets|betting|wager|parlay|sportsbook|odds boost|bookmaker|gambl\w*)\b"
    hits = [m.group(0) for m in re.finditer(betting, words, re.I)]
    assert hits == ["betting"] and "analysis, not betting picks" in words
    for pattern in _DEV_SPEAK:
        assert not re.search(pattern, _visible(PAGE), re.I), pattern
    assert not re.search(r"\bfiles?\b", words, re.I)
    assert not re.search(r"@(gmail|outlook|hotmail|yahoo|icloud|proton|aol)\.", PAGE, re.I)
    # Facts only, in the static words too.
    assert not FORECAST_WORDS.search(_visible(PAGE))


# --------------------------------------------------------------------- #
# T2. the data: render/bye_index.py
# --------------------------------------------------------------------- #

def test_the_committed_data_is_this_seasons_and_small() -> None:
    """One season with players.json (a roster read against another season's
    byes plans weeks for teams that are not theirs), every regular-season
    week with its end date, 32 teams' byes, the reserve list cut to ids the
    planner can resolve with ROSTER_OUT reasons only — never LIVE_ONLY_OUT or
    the practice squad, which run.solo._byes_ahead does not count either —
    and under 20 KB."""
    byes, players = _byes(), _directory()
    assert byes["season"] == players["season"]
    assert [w["week"] for w in byes["weeks"]] == list(range(1, byes["last_week"] + 1))
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d", w["ends"]) for w in byes["weeks"])
    assert [w["ends"] for w in byes["weeks"]] == sorted(w["ends"] for w in byes["weeks"])
    teams = [t for w in byes["weeks"] for t in w["bye"]]
    assert len(teams) == len(set(teams)) == 32
    ids = {row[1] for row in players["players"]}
    assert set(byes["out"]) <= ids
    allowed = set(ROSTER_OUT.values())
    assert set(byes["out"].values()) <= allowed
    assert not set(byes["out"].values()) & (set(LIVE_ONLY_OUT.values())
                                            | set(PRACTICE_SQUAD.values())) - allowed
    from ingest.nflverse import ATTRIBUTION
    assert byes["attribution"] == ATTRIBUTION
    assert BYES_JSON.stat().st_size < 20_000


def test_the_committed_page_table_is_the_committed_data() -> None:
    """The static table (no-JavaScript visitors and crawlers read it) is
    table_html of the committed byes.json, so it can never show a bye the
    planner does not use."""
    from render import bye_index
    assert bye_index.table_in(PAGE) == bye_index.table_html(_byes(), _directory())
    block = bye_index.table_in(PAGE)
    assert block.startswith('<h2 id="every-bye">Every 2026 NFL bye week</h2>')
    assert "<li><b>Week 9</b> — Pittsburgh Steelers, Tennessee Titans</li>" in block
    assert "<p>No byes in Weeks 1–4, 12 and 15–18.</p>" in block
    assert block.endswith('<p class="src">Schedule: nflverse (nflverse-data), CC-BY-4.0.</p>')


def test_the_table_escapes_and_words_its_gaps() -> None:
    from render.bye_index import _ranges, table_html
    assert _ranges([1, 2, 3, 4, 12, 15, 16, 17, 18]) == "1–4, 12 and 15–18"
    assert _ranges([12]) == "12" and _ranges([3, 5]) == "3 and 5"
    payload = {"season": "2026", "weeks": [{"week": 1, "ends": "x", "bye": ["ZZ"]},
                                           {"week": 2, "ends": "x", "bye": []}]}
    html = table_html(payload, {"players": [["<b>Evil</b> & Co", "DEF-ZZ", "DEF", "ZZ"]]})
    assert "&lt;b&gt;Evil&lt;/b&gt; &amp; Co" in html and "<b>Evil" not in html
    assert "<p>No byes in Week 2.</p>" in html


def test_the_data_is_built_the_way_the_weekly_report_reads_the_same_facts() -> None:
    """weeks[].bye regrouped is bye_by_team; every "ends" is
    regular_week_end; the first week ending today or later is
    run.solo.current_week; "out" is roster_out restricted to the directory."""
    _cache_or_skip()
    from engine.availability import roster_out
    from engine.preseason import bye_by_team
    from render import bye_index
    from run.solo import _schedule, _weeks, current_week, regular_week_end
    players = _directory()
    payload = bye_index.build(players["season"], RAW, players)
    regrouped = {t: w["week"] for w in payload["weeks"] for t in w["bye"]}
    assert regrouped == bye_by_team(RAW, players["season"])
    weeks = _weeks(_schedule(RAW, live=False), players["season"])
    assert {w["week"]: w["ends"] for w in payload["weeks"]} == \
        {week: regular_week_end(days) for week, days in weeks.items()}
    for today in ("2026-09-01", TODAY, "2026-11-10", "2026-12-29"):
        first = next(w["week"] for w in payload["weeks"] if w["ends"] >= today)
        assert first == current_week(RAW, players["season"], date.fromisoformat(today), live=False)
    ids = {row[1] for row in players["players"]}
    assert payload["out"] == {k: v for k, v in roster_out(RAW / "players.csv").items() if k in ids}


def _tmp_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    out, players, page = tmp_path / "byes.json", tmp_path / "players.json", tmp_path / "page.html"
    shutil.copy(PLAYERS_JSON, players)
    shutil.copy(PAGE_PATH, page)
    return out, players, page


def _args(out, players, page, *extra) -> list[str]:
    return ["--season", "2026", "--raw", str(RAW), "--output", str(out), "--players", str(players),
            "--page", str(page), "--offline", *extra]


def test_the_generator_is_deterministic_and_check_catches_drift(tmp_path, capsys) -> None:
    """Two builds differ only in "generated"; --check passes on a fresh build
    and fails on a changed bye or a hand-edited table."""
    _cache_or_skip()
    from render import bye_index
    out, players, page = _tmp_inputs(tmp_path)
    assert bye_index.main(_args(out, players, page)) == 0
    first = json.loads(out.read_text(encoding="utf-8"))
    assert bye_index.main(_args(out, players, page)) == 0
    second = json.loads(out.read_text(encoding="utf-8"))
    first.pop("generated"), second.pop("generated")
    assert first == second
    assert bye_index.main(_args(out, players, page, "--check")) == 0
    changed = json.loads(out.read_text(encoding="utf-8"))
    changed["weeks"][8]["bye"] = ["PIT"]
    out.write_text(json.dumps(changed), encoding="utf-8")
    assert bye_index.main(_args(out, players, page, "--check")) == 1
    assert bye_index.main(_args(out, players, page)) == 0
    page.write_text(page.read_text(encoding="utf-8").replace("Week 9</b>", "Week 10</b>"),
                    encoding="utf-8")
    assert bye_index.main(_args(out, players, page, "--check")) == 1
    assert "stale" in capsys.readouterr().err


def test_the_generator_refuses_rather_than_publish_a_wrong_bye(tmp_path, capsys) -> None:
    """Fewer than 32 teams with a bye, no weeks, or a players.json from
    another season: exit 1 and last week's file stays exactly as it was."""
    from render import bye_index
    players = _directory()
    good = {"season": "2026", "weeks": _byes()["weeks"]}
    bye_index.validate(good, players)
    partial = {"season": "2026", "weeks": [dict(w, bye=w["bye"][:1]) for w in good["weeks"]]}
    with pytest.raises(bye_index.ByeIndexError, match="not 32"):
        bye_index.validate(partial, players)
    with pytest.raises(bye_index.ByeIndexError, match="no 2026 weeks"):
        bye_index.validate({"season": "2026", "weeks": []}, players)
    with pytest.raises(bye_index.ByeIndexError, match="2025 directory"):
        bye_index.validate(good, dict(players, season="2025"))
    _cache_or_skip()
    out, players_path, page = _tmp_inputs(tmp_path)
    out.write_text("last week's file\n", encoding="utf-8")
    stale = json.loads(players_path.read_text(encoding="utf-8"))
    stale["season"] = "2025"
    players_path.write_text(json.dumps(stale), encoding="utf-8")
    assert bye_index.main(_args(out, players_path, page)) == 1
    assert out.read_text(encoding="utf-8") == "last week's file\n"
    assert "refusing" in capsys.readouterr().err
    # A season the schedule has never heard of: no weeks at all.
    shutil.copy(PLAYERS_JSON, players_path)
    args = _args(out, players_path, page)
    args[1] = "1990"
    assert bye_index.main(args) == 1
    assert out.read_text(encoding="utf-8") == "last week's file\n"


def test_a_page_without_its_markers_is_refused() -> None:
    from render.bye_index import ByeIndexError, with_table
    with pytest.raises(ByeIndexError):
        with_table("<html>no markers</html>", "<p>x</p>")
    assert with_table("a<!-- byes:start -->old<!-- byes:end -->b", "new") == \
        "a<!-- byes:start -->\nnew\n<!-- byes:end -->b"


# --------------------------------------------------------------------- #
# the cron and the Makefile
# --------------------------------------------------------------------- #

def test_the_tuesday_cron_refreshes_and_commits_the_planners_data() -> None:
    """Beside players.json, in the same step and after it (the reserve list
    is cut to that directory); a refusal warns rather than failing the run,
    because last week's dated file is still right about every bye; and the
    persist step commits both files the generator writes."""
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    doc = yaml.safe_load((REPO / ".github" / "workflows" / "weekly.yml").read_text())
    steps = list(doc["jobs"].values())[0]["steps"]
    step = next(s for s in steps if s.get("name") == "Refresh the published player directory")
    run = step["run"]
    assert run.index("render.player_index") < run.index("render.bye_index")
    line = next(l for l in run.splitlines() if "render.bye_index" in l)
    assert '--season "$SEASON"' in line and "|| echo \"::warning::" in line
    persist = next(s for s in steps if s.get("name") == "Persist the record")["run"]
    add = next(l for l in persist.splitlines() if l.strip().startswith("git add -A"))
    assert "site/join/byes.json" in add and "site/byes/index.html" in add


def test_make_index_and_make_byes_build_the_planners_data() -> None:
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    index = make.split("\nindex:\n", 1)[1].split("\n\n", 1)[0]
    assert "render.player_index" in index and "render.bye_index" in index
    assert "\nbyes:\n\t$(PY) -m render.bye_index --season $(SEASON)" in make
