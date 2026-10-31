"""The moment after "Check my roster" (owner brief, Oct 30 2026).

"15 players read, 9 starting spots. Looks right." was the whole payoff of
pasting a team, and the next thing on the page was a button about checkout not
being open. The check now ends in a panel of FACTS about the visitor's roster.

The hard rule these tests hold: facts, computed in the browser from what is
already published (the roster, the chosen lineup, site/join/byes.json, today).
No projection, no percentage, no recommendation, no ordering of anybody's
players, nothing that needs the model, nothing recorded. The bye rule is
byes.js, the planner's copy, never a second one. Run under node where a rule
is at stake, against the real functions lifted out of the page.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.history import FLEX_ELIGIBILITY
from engine.preseason import bye_collisions

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
BYES_JS = SITE / "byes" / "byes.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available (CI has it)")
STD = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
SF = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]
TWO_FLEX = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]


def _player(name: str, position: str, team: str = "BUF") -> dict:
    return {"id": name.lower().replace(" ", "-"), "name": name, "position": position, "team": team}


# The owner's test paste, by position, in the order pasted.
PASTE = [_player(n, p, t) for n, p, t in [
    ("Josh Allen", "QB", "BUF"), ("Saquon Barkley", "RB", "PHI"), ("Bijan Robinson", "RB", "ATL"),
    ("Ja'Marr Chase", "WR", "CIN"), ("Amon-Ra St. Brown", "WR", "DET"), ("George Kittle", "TE", "SF"),
    ("Marvin Harrison Jr.", "WR", "ARI"), ("Jake Bates", "K", "DET"), ("Denver Broncos", "DEF", "DEN"),
    ("Sam LaPorta", "TE", "DET"), ("Kenneth Walker III", "RB", "KC"), ("DJ Moore", "WR", "BUF"),
    ("T.J. Hockenson", "TE", "MIN"), ("De'Von Achane", "RB", "MIA"), ("C.J. Stroud", "QB", "HOU")]]


def _function(name: str) -> str:
    start = JOIN.index(f"function {name}(")
    return JOIN[start:JOIN.index("\n}\n", start) + 2]


def _panel_code() -> str:
    """The panel's own script: from its heading to the loader's first call."""
    start = JOIN.index("// ---- the payoff: what the check found")
    return JOIN[start:JOIN.index("loadByes();\n", start)]


def _harness() -> str:
    """The page's real functions, loose in a script, with byes.js as B."""
    takes = re.search(r"^const SLOT_TAKES = .*?;$", JOIN, re.M).group(0)
    positions = re.search(r"^const PF_POSITIONS = .*?;$", JOIN, re.M).group(0)
    names = ("emptySpots", "lineupWords", "fieldPosition", "contestedCalls", "lockedRows",
             "firstWeekAhead", "byePlan", "byeHitWords")
    return (f"globalThis.B = require({json.dumps(str(BYES_JS))});\n{takes}\n{positions}\n" +
            "\n".join(_function(n) for n in names))


def _node(tmp_path: Path, script: str) -> object:
    digest = hashlib.sha1(script.encode()).hexdigest()[:8]
    path = tmp_path / f"run-{digest}.js"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, f"node failed:\n{done.stderr[-3000:]}"
    return json.loads(done.stdout)


def _calls(tmp_path: Path, players: list, slots: list, out: dict | None = None) -> object:
    return _node(tmp_path, _harness() + "\nconsole.log(JSON.stringify(contestedCalls(" +
                 ", ".join(json.dumps(x) for x in (players, slots, out or {})) + ")));")


# --------------------------------------------------------------------- #
# A. the calls on your team
# --------------------------------------------------------------------- #

@needs_node
def test_the_sample_roster_reads_as_the_calls_it_really_has(tmp_path) -> None:
    calls = _calls(tmp_path, PASTE, STD)
    assert [(c["position"], c["words"]) for c in calls] == [
        ("QB", "2 players, 1 spot"), ("RB", "4 players, 2 spots plus FLEX"),
        ("WR", "4 players, 2 spots plus FLEX"), ("TE", "3 players, 1 spot plus FLEX")]


@needs_node
def test_only_a_position_with_a_real_choice_is_listed(tmp_path) -> None:
    """Six skill players for six spots: the second tight end has to play FLEX,
    so nobody at any position is a choice. Add a third back and the back and
    the second tight end now compete for FLEX; the receivers still do not."""
    base = [_player("Qb", "QB"), _player("Rb A", "RB"), _player("Rb B", "RB"),
            _player("Wr A", "WR"), _player("Wr B", "WR"), _player("Te A", "TE"),
            _player("Te B", "TE"), _player("Kick", "K"), _player("Def", "DEF")]
    assert _calls(tmp_path, base, STD) == []
    more = base + [_player("Rb C", "RB")]
    assert [c["position"] for c in _calls(tmp_path, more, STD)] == ["RB", "TE"]
    # Short a running back, four receivers still have a choice for FLEX.
    short = [_player("Qb", "QB"), _player("Rb A", "RB")] + \
        [_player(f"Wr {x}", "WR") for x in "ABCD"] + \
        [_player("Te A", "TE"), _player("Kick", "K"), _player("Def", "DEF")]
    assert [c["position"] for c in _calls(tmp_path, short, STD)] == ["WR"]
    # A second kicker is a call; one is not.
    assert [c["position"] for c in _calls(tmp_path, base + [_player("Kick B", "K")], STD)] == ["K"]


@needs_node
def test_flex_eligibility_follows_the_lineup_chosen(tmp_path) -> None:
    """Superflex counts quarterbacks; a quarterback never counts for FLEX."""
    std = {c["position"]: c["words"] for c in _calls(tmp_path, PASTE, STD)}
    sf = {c["position"]: c["words"] for c in _calls(tmp_path, PASTE, SF)}
    two = {c["position"]: c["words"] for c in _calls(tmp_path, PASTE, TWO_FLEX)}
    assert std["QB"] == "2 players, 1 spot"
    assert sf["QB"] == "2 players, 1 spot plus superflex"
    assert sf["RB"] == "4 players, 2 spots plus FLEX and superflex"
    assert two["WR"] == "4 players, 2 spots plus 2 FLEX"


def test_the_pages_flex_table_is_the_engines() -> None:
    takes = re.search(r"^const SLOT_TAKES = (.*?);$", JOIN, re.M).group(1)
    table = json.loads(re.sub(r"(\w+):", r'"\1":', takes).replace("'", '"'))
    assert {slot: frozenset(takes) for slot, takes in table.items()} == \
        {slot: FLEX_ELIGIBILITY[slot] for slot in table}, table
    assert set(table) == {"FLEX", "SUPER_FLEX"}


@needs_node
def test_a_reserve_player_is_marked_and_never_counted(tmp_path) -> None:
    """An absence is never an option: De'Von Achane on injured reserve is shown,
    marked, and the count is of players who can play."""
    achane = next(p for p in PASTE if p["name"].startswith("De'Von"))
    calls = _calls(tmp_path, PASTE, STD, {achane["id"]: "on injured reserve"})
    rb = next(c for c in calls if c["position"] == "RB")
    assert rb["words"] == "3 players, 2 spots plus FLEX"
    assert {"name": "De'Von Achane", "out": "on injured reserve"} in rb["names"]
    # The only other quarterback on IR: no choice left, so no QB line at all.
    stroud = next(p for p in PASTE if p["name"] == "C.J. Stroud")
    calls = _calls(tmp_path, PASTE, STD, {stroud["id"]: "on injured reserve"})
    assert "QB" not in [c["position"] for c in calls]


@needs_node
def test_names_stay_in_the_order_pasted_so_nothing_reads_as_a_pick(tmp_path) -> None:
    """Reverse the paste and every list reverses: no ordering of ours exists
    anywhere for a reader to take as a preference."""
    forward = _node(tmp_path, _harness() + f"""
      const players = {json.dumps(PASTE)}, slots = {json.dumps(STD)};
      const run = (ps) => ({{ calls: contestedCalls(ps, slots, {{}}).map((c) => c.names.map((n) => n.name)),
                             lock: lockedRows(ps, slots, {{}}).map((r) => r.names) }});
      console.log(JSON.stringify([run(players), run(players.slice().reverse())]));""")
    ahead, back = forward
    want = lambda row: row[::-1]  # noqa: E731
    assert [want(r) for r in back["calls"]] == ahead["calls"]
    assert [want(r) for r in back["lock"]] == ahead["lock"]
    assert ahead["lock"][1] == ["Saquon Barkley", "Bijan Robinson", "Kenneth Walker III",
                                "De'Von Achane"]
    for name in ("contestedCalls", "lockedRows", "lockedPreview", "callsBlock"):
        assert ".sort(" not in _function(name), name
    assert "relevance" not in _panel_code(), "the typeahead's points rank nothing here"


# --------------------------------------------------------------------- #
# B. byes ahead: byes.js, not a copy
# --------------------------------------------------------------------- #

def test_the_panel_reuses_byes_js_and_never_a_second_copy() -> None:
    digest = hashlib.sha256(BYES_JS.read_bytes()).hexdigest()[:10]
    tag = f'<script src="../byes/byes.js?v={digest}"></script>'
    assert tag in JOIN and JOIN.index(tag) < JOIN.index("<script>\n")
    assert JOIN.index('<script src="roster.js') < JOIN.index(tag)
    code = _panel_code()
    for copy in ("function unfillableSlots", "function byeCollisions", "function eligible",
                 "function describe", "FLEX_ELIGIBILITY ="):
        assert copy not in JOIN, copy
    plan = _function("byePlan")
    assert "B.rosterRows(" in plan and "B.describe(" in plan and "B.byeCollisions(" in plan
    # The weekly report's rule to the letter: a fullback covers nothing here,
    # as tests/test_polish_tool.py holds of the planner.
    assert "fieldPosition" not in plan
    assert 'fetch("byes.json"' in code


@needs_node
def test_a_flagged_bye_is_the_one_the_python_flags(tmp_path) -> None:
    """The real byes.json and the sample paste with a thin roster, through the
    page's byePlan, equal to engine.preseason.bye_collisions on the same rows."""
    byes = json.loads((SITE / "join" / "byes.json").read_text(encoding="utf-8"))
    team_week = {team: w["week"] for w in byes["weeks"] for team in w["bye"]}
    players = [p for p in PASTE if p["name"] in (
        "Josh Allen", "Saquon Barkley", "Bijan Robinson", "Ja'Marr Chase", "Amon-Ra St. Brown",
        "George Kittle", "Marvin Harrison Jr.", "Jake Bates", "Denver Broncos")]
    weeks = sorted(set(team_week.values()))
    first, second, third, fourth, fifth = weeks[:5]
    players = [dict(p, team=next(t for t in sorted(team_week) if team_week[t] == w))
               for p, w in zip(players, [first, second, second, third, fourth, fifth,
                                         third, fourth, fifth])]
    today = byes["weeks"][0]["ends"]
    got = _node(tmp_path, _harness() + f"""
      const out = byePlan({json.dumps(players)}, {json.dumps(STD)}, {json.dumps(byes)},
                          {json.dumps(today)}, null);
      console.log(JSON.stringify({{ hits: out.hits, kinds: out.plan.weeks.map((r) => [r.week, r.kind]),
        words: out.hits.map((h) => byeHitWords(h, out.plan.weeks.find((r) => r.week === h.week))) }}));""")
    rows = [{"player_id": p["id"], "name": p["name"], "position": p["position"],
             "bye": team_week[p["team"]], "out_today": None} for p in players]
    python = bye_collisions(rows, STD, [w for w, _ in got["kinds"]])
    assert python, "the roster must actually be flagged, or this proves nothing"
    assert got["hits"] == python
    assert sorted(w for w, kind in got["kinds"] if kind == "empty") == [h["week"] for h in python]
    assert got["words"][0] == f"Week {first}: nobody left for QB. Josh Allen is on bye."


@needs_node
def test_the_strip_starts_with_the_first_lineup_left(tmp_path) -> None:
    """The plan moves up to the first lineup a buyer still gets, and never back
    behind the week being played."""
    byes = json.loads((SITE / "join" / "byes.json").read_text(encoding="utf-8"))
    current_ends = byes["weeks"][7]["ends"]
    got = _node(tmp_path, _harness() + f"""
      const byes = {json.dumps(byes)}, players = {json.dumps(PASTE)}, slots = {json.dumps(STD)};
      const first = (start) => byePlan(players, slots, byes, {json.dumps(current_ends)}, start).plan.weeks;
      console.log(JSON.stringify([first(9)[0].week, first(9).length, first(null)[0].week,
                                  first(3)[0].week, first(9).slice(-3).map((r) => r.playoff)]));""")
    assert got == [9, 9, 8, 8, [True, True, True]]


def test_no_byes_file_means_no_byes_said() -> None:
    """A failed read leaves the section out: never "no byes"."""
    code = _panel_code()
    body = _function("drawPayoff")
    assert "if (window.B && state.byes) {" in body
    assert 'const out = window.B ? reserveList() : {};' in body
    # A purchase still gets the facts it can; a seat or an update has nothing left.
    assert "return SALES_PANEL || Boolean(window.B && state.byes);" in _function("payoffShows")
    assert ".catch(() => {})" in code.split("function loadByes()")[1]


# --------------------------------------------------------------------- #
# D. the locked preview
# --------------------------------------------------------------------- #

FAKE_DOM = r"""
const made = [];
function el(tag) {
  const node = { tag, className: "", attrs: {}, kids: [], _text: "", style: { setProperty() {} },
    setAttribute(k, v) { this.attrs[k] = v; },
    appendChild(c) { this.kids.push(c); return c; },
    append(...cs) { cs.forEach((c) => this.kids.push(typeof c === "string" ? { text: c } : c)); },
    set textContent(v) { this._text = v; }, get textContent() { return this._text; } };
  made.push(node);
  return node;
}
globalThis.document = { createElement: el, createElementNS: (ns, tag) => el(tag) };
const walk = (n, f) => { f(n); (n.kids || []).forEach((k) => walk(k, f)); };
"""


def _lock(tmp_path: Path, players: list, slots: list, wants_pass: bool = False) -> dict:
    fns = "\n".join(_function(n) for n in ("panelNode", "lockIcon", "lockedPreview"))
    return _node(tmp_path, _harness() + FAKE_DOM + f"""
      const WANTS_PASS = {json.dumps(wants_pass)};
      const PF_SVG = "svg";
      {fns}
      const block = lockedPreview(4, {json.dumps(players)}, {json.dumps(slots)}, {{}});
      const text = [], attrs = [], bars = [];
      walk(block, (n) => {{
        if (n.text) text.push(n.text);
        if (n._text) text.push(n._text);
        if (n.attrs) attrs.push(n.attrs);
        if (n.className === "pf-bar") bars.push({{ hidden: n.attrs["aria-hidden"], kids: n.kids.map((k) => k.tag),
          text: n.kids.map((k) => k._text) }});
      }});
      console.log(JSON.stringify({{ text, attrs, bars }}));""")


@needs_node
def test_the_locked_preview_has_no_digit_and_no_percentage_at_all(tmp_path) -> None:
    """Not on screen, not blurred, not in the DOM: a bar is an empty element."""
    got = _lock(tmp_path, PASTE, STD)
    text = " ".join(got["text"])
    assert not re.search(r"[0-9%]", text), text
    for name in ("Josh Allen", "C.J. Stroud", "Denver Broncos"):
        assert name in text
    assert got["text"][0] == "Your Lineup, Decided"
    assert got["bars"] and all(b["hidden"] == "true" and b["kids"] == ["i", "i"]
                               and b["text"] == ["", ""] for b in got["bars"])
    numeric = [v for attrs in got["attrs"] for k, v in attrs.items()
               if k not in ("viewBox", "d", "x", "y", "width", "height", "rx", "aria-hidden")]
    assert not numeric, numeric


@needs_node
def test_the_locked_preview_decides_nothing(tmp_path) -> None:
    """Rows are positions with every eligible name, never a slot with one
    player in it, and the bars are one fixed width so none reads as a ranking."""
    got = _lock(tmp_path, PASTE, STD)
    rows = [t for t in got["text"] if t in ("QB", "RB", "WR", "TE", "K", "DEF", "FLEX")]
    assert rows == ["QB", "RB", "WR", "TE", "K", "DEF"]
    assert "Josh Allen · C.J. Stroud" in got["text"]
    css = JOIN.split(".pf-bar{")[1].split(".pf-lockline")[0]
    assert css.count("width:") == 2 and "var(--" not in css.split("first-child{")[1].split("}")[0]
    assert "style" not in _function("lockedPreview").split("lockedRows(")[1]
    # No K, no DEF: those rows go, even for a kicker left on the roster.
    no_kd = [s for s in STD if s not in ("K", "DEF")]
    rows = [t for t in _lock(tmp_path, PASTE, no_kd)["text"] if t in ("K", "DEF")]
    assert rows == []
    # A League Pass reads for a league.
    assert any("Each manager's report" in t for t in _lock(tmp_path, PASTE, STD, True)["text"])


# --------------------------------------------------------------------- #
# E. the week the plan starts
# --------------------------------------------------------------------- #

@needs_node
def test_the_first_week_ahead_is_the_landings_clock(tmp_path) -> None:
    now = "2026-10-30T15:00:00Z"
    season = {"week": 8, "last_week": 18, "phase": "season", "lands_on": "2026-11-03",
              "first_kickoff": "2026-10-30T00:15:00Z"}
    before = dict(season, first_kickoff="2026-11-01T17:00:00Z")
    cases = [
        [season, True], [season, False], [before, True], [before, False],
        [dict(season, lands_on="2026-10-20"), False],             # a missed build
        [dict(season, lands_on="2026-11-20"), False],             # too far off to trust
        [dict(season, week=17, lands_on="2026-11-03"), False],    # past Week 17
        [dict(season, phase="over"), False], [None, False],
        [dict(season, phase="preseason", week=1), False],
    ]
    got = _node(tmp_path, _harness() + f"""
      console.log(JSON.stringify({json.dumps(cases)}.map(([w, open]) =>
        firstWeekAhead(w, new Date({json.dumps(now)}), open))));""")
    assert got == [9, 9, 8, 9, None, None, None, None, None, 1]
    # The same rule as the landing's season clock, on the same file.
    flat = re.sub(r"\s+", " ", LANDING)
    assert 'phase === "preseason" ? w.week : CHECKOUT_OPEN && sameDay ? w.week : w.week + 1' in flat
    assert 'phase === "preseason" ? w.week : open && sameDay ? w.week : w.week + 1' in \
        _function("firstWeekAhead")


def test_the_panel_head_counts_nothing_ahead() -> None:
    top = _function("payoffTop")
    assert "Every lineup through your title game." in top
    assert " left to a Week 17" not in top and "lineups" not in top


# --------------------------------------------------------------------- #
# The hard rule, on the words themselves
# --------------------------------------------------------------------- #

def test_the_panel_says_facts_and_nothing_more() -> None:
    """Every string the panel can render. No odds, no projection, no advice,
    no betting word, no banned word, and "report", never "file"."""
    code = re.sub(r"^\s*//.*$", "", _panel_code(), flags=re.M)
    code = re.sub(r"\s*\+\s*\n\s*", " + ", code)
    strings = " ".join(re.findall(r'"([^"\n]*)"', code))
    for banned in (r"%", r"\bodds\b", r"\bproject", r"\bshould\b", r"\brecommend", r"\bbest\b",
                   r"\bbetter\b", r"\bwin\b", r"\bfile\b", r"\bcalibrated\b", r"\btested\b",
                   r"\bproven\b", r"\baccurate\b", r"\bsportsbook\b", r"\bbet\b", r"\bwager",
                   r"\brival\b", r"\bopponent\b", r"\bwaiver"):
        assert not re.search(banned, strings, re.I), banned
    assert "Your Tuesday report decides these for your team, every week." in strings
    assert "Everyone who can play starts" in strings


def test_everything_from_the_paste_goes_in_as_text() -> None:
    code = _panel_code()
    assert "innerHTML" not in code and "insertAdjacentHTML" not in code
    assert "innerHTML" not in re.sub(r"^\s*//.*$", "", JOIN, flags=re.M).split("<script>")[1]
    assert "node.textContent = text;" in _function("panelNode")


def test_the_panel_records_nothing_and_asks_for_nothing() -> None:
    code = _panel_code()
    fetches = re.findall(r"\bfetch\(([^,)]+)", code)
    assert fetches == ['"byes.json"'], fetches
    assert "bylCount" not in code and "localStorage" not in code and "sessionStorage" not in code


def test_the_tally_keeps_its_facts_and_leads_into_the_panel() -> None:
    draw = _function("draw")
    assert "Looks right" not in re.sub(r"^\s*//.*$", "", draw, flags=re.M)
    flat = re.sub(r'"\s*\+\s*"', "", re.sub(r"\s+", " ", draw))
    assert 'ids.length + " players read, " + slots.length + " starting spots."' in flat
    assert "Here's what that means for your team." in flat
    assert 'id="tally" role="status"' in JOIN


# --------------------------------------------------------------------- #
# Motion
# --------------------------------------------------------------------- #

def test_the_entrance_lives_only_under_play_and_stays_on_transform_and_opacity() -> None:
    css = re.search(r"<style>(.*?)</style>", JOIN, re.S).group(1)
    for name in ("pfrise", "pffill"):
        frames = re.search(r"@keyframes " + name + r"\{(.*?)\}\}", css, re.S).group(1)
        props = set(re.findall(r"([a-z-]+):", frames))
        assert props <= {"opacity", "transform"}, (name, props)
    # A complete panel by default: nothing is hidden unless .play is on.
    panel = css.split("the payoff: what")[1].split("paper pages: one depth")[0]
    for line in panel.splitlines():
        if "animation:" in line:
            assert "#payoff.play" in line or "animation:none" in line, line
    assert "infinite" not in panel
    assert re.search(r"\.pf-rise\{animation:pfrise \.3s", panel)
    assert "var(--i,0) * 80ms" in panel


def test_reduced_motion_is_complete_and_still() -> None:
    css = re.search(r"<style>(.*?)</style>", JOIN, re.S).group(1)
    still = "#payoff.play .pf-rise,#payoff.play .pf-weekbox,#payoff.play .pf-po{animation:none!important;}"
    assert still in css
    assert css.index("@media (prefers-reduced-motion:reduce){\n    #payoff.play") < \
        css.index(still)
    draw = _function("drawPayoff")
    assert '(prefers-reduced-motion: reduce)' in draw
    play = draw.split("if (!reduced) {")[1].split("}")[0]
    assert 'panel.classList.add("play");' in play and "countUp(" in play
    assert 'behavior: reduced ? "auto" : "smooth"' in _function("bringPayoffIntoView")


def test_the_entrance_runs_once_and_finishes_inside_a_second_and_a_half() -> None:
    draw = _function("drawPayoff")
    assert "if (state.checked && !state.payoffPlayed) {" in draw
    assert "state.payoffPlayed = true;" in draw
    assert 'setTimeout(() => panel.classList.remove("play"), 1500)' in draw
    # Every draw starts at rest, so a redraw never replays anything.
    assert draw.index('panel.classList.remove("play");') < draw.index("const shows")
    # Only the press itself scrolls, and focus is left alone.
    assert "if (state.freshCheck) setTimeout(() => bringPayoffIntoView(reduced), 400);" in draw
    assert ".focus(" not in _panel_code()
    press = JOIN.split('$("resolve").addEventListener("click"')[1].split("\n});")[0]
    assert press.index("state.freshCheck = true;") < press.index("draw();") < \
        press.index("state.freshCheck = false;")
    # A number that never lands is a wrong number.
    assert "node.textContent = String(to);" in _function("countUp")


def test_a_stale_or_unfinished_roster_shows_no_panel() -> None:
    shows = _function("payoffShows")
    assert "!state.ready || state.stale || !state.matches.length || TRY_MODE" in shows
    typed = JOIN.split('$("roster-text").addEventListener("input"')[1].split("\n});")[0]
    assert typed.index("state.ready = false;") < typed.index("drawPayoff();")
    # A season that is over has no lineups to look ahead to.
    assert "seasonOver()" in shows


# --------------------------------------------------------------------- #
# Modes and step 3
# --------------------------------------------------------------------- #

def test_each_mode_gets_its_own_panel() -> None:
    assert "const SALES_PANEL = !SEAT_MODE && !UPDATE_MODE;" in JOIN
    draw = _function("drawPayoff")
    assert "blocks.push(callsBlock(1, players, slots, out));" in draw.split("if (SALES_PANEL) {")[1]
    assert "if (SALES_PANEL) blocks.push(lockedPreview(4, players, slots, out));" in draw
    assert "const first = SALES_PANEL ?" in draw
    calls = re.sub(r'"\s*\+\s*"', "", _function("callsBlock"))
    assert "WANTS_PASS ? \"Every manager's report decides these" in calls


def test_the_panel_sits_straight_above_the_purchase() -> None:
    markup = re.sub(r"<script\b.*?</script>", "", JOIN, flags=re.S)
    panel = markup.index('<section id="payoff"')
    assert markup.index('id="step-roster"') < panel < markup.index('<section id="step-email"')
    between = markup[panel:markup.index('<section id="step-email"')]
    assert "<button" not in between and "<input" not in between


def test_closed_step_three_is_a_next_step_with_the_mechanics_true() -> None:
    step = _function("drawStep3")
    flat = re.sub(r'"\s*\+\s*"', "", step)
    assert '"3 · Save your team"' in step and '"3 · Checkout"' in step
    # Only where pressing can save anything: a closed League Pass whose own
    # team's plan is open has nothing to keep, so it stays what it was.
    assert 'step3Action === "list" || step3Action === "mail"' in step
    # The line itself is valueWords: the same sentence every week.
    assert "value.textContent = valueWords();" in step
    words = re.sub(r'"\s*\+\s*"', "", _function("valueWords"))
    assert "Every lineup from now to your title game. $" in words
    assert "(PLAYOFF_ACTIVE ? 19 : 29)" in words and '", one payment' in words
    assert "$69, one payment." in words
    label = _function("closedLabel")
    assert '"Save my team and tell me when it opens"' in label
    assert '"Save my team by email"' in label, "the mail route saves nothing until it's sent"
    # The press stays honest: the page says nothing was saved until it was.
    mail = re.sub(r'"\s*\+\s*"', "", _function("askByMail"))
    assert "your request isn't saved with us until you send that email" in mail
    words = re.sub(r'"\s*\+\s*"', "", _function("mailLineWords"))
    assert "Press below to open your mail app with a request to us filled in" in words
    # The list's own line is about the press, and goes once it has happened.
    note = _function("noteClosedFor")
    assert 'action === "list" && !listed && !seasonOver()' in note
    # A real report is one click from the closed step, and only there.
    assert 'id="see-real" href="../sample-report.html" hidden' in JOIN
    assert '$("see-real").hidden = step3Action === "open";' in step
    # Terms and refund stay beside any price the step shows.
    markup = JOIN.split('id="value-line"')[1].split("</form>")[0]
    assert 'id="terms-line"' in markup and "no-questions" in markup and "one\n      payment" in markup


def test_an_open_checkout_keeps_the_button_the_purchase() -> None:
    # "Unlock" once they have built something (owner brief, Oct 30 2026); the
    # read-back's button is the one that says it leaves for checkout.
    assert '<button id="submit" type="submit">Unlock my lineups — $29</button>' in JOIN
    assert '<button type="button" id="check-yes">Continue to checkout — $29</button>' in JOIN
    assert "const SEASON_SUBMIT = $(\"submit\").textContent;" in JOIN
    # The open path through the handler is untouched by the panel.
    handler = JOIN.split('$("form-email").addEventListener')[1].split("\n});")[0]
    assert "leaveForCheckout(link, tagged, email);" in handler
    assert "payoff" not in handler
