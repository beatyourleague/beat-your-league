"""The join page's sales narrative (review, Oct 30 2026).

Each test pins one finding from the flow review so it cannot drift back:
a heading per visit, the settings as one line before the roster, a free
report that says it isn't open instead of pitching then refusing, the
player list failing loudly rather than killing the page, and the day-one
email called "your first report".
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
BYES = (SITE / "byes" / "index.html").read_text(encoding="utf-8")


def _code(page: str) -> str:
    """Inline script code without whole-line comments."""
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    return "\n".join(line for line in "\n".join(scripts).splitlines()
                     if not line.lstrip().startswith("//"))


def _flat(text: str) -> str:
    return re.sub(r'"\s*\+\s*"', "", re.sub(r"\s+", " ", text))


def _markup(page: str) -> str:
    return re.sub(r"<script\b.*?</script>", "", page, flags=re.S | re.I)


def _function(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    return page[start:page.index("\n}\n", start) + 2]


def test_every_visit_gets_its_own_heading() -> None:
    """flow-join / m-update / m-try / m-pass: the page read "Set Up Your Team"
    over a roster update, a free report, a League Pass and a seat claim. The
    markup keeps the default; the script names the visit where modes are
    resolved, from the same flags the submit handler reads."""
    assert "<h1>Set Up Your Team</h1>" in JOIN
    decl = re.search(r"const HEADING = (.*?);\n", JOIN, re.S).group(1)
    for mode, words in (("SEAT_MODE", "Claim your seat"), ("UPDATE_MODE", "Update your roster"),
                        ("TRY_MODE", "Get a free report"), ("WANTS_PASS", "Cover your whole league")):
        assert mode in decl and f'"{words}"' in decl, mode
    assert '"Free reports open soon"' in decl and "FORM_ENDPOINT && TRIAL_OPEN" in decl
    assert 'document.querySelector("header h1").textContent = HEADING' in JOIN
    # Set once the modes exist, before any branch draws its pitch.
    code = _code(JOIN)
    assert code.index("const TRY_MODE =") < code.index("const HEADING =") \
        < code.index("if (TRY_MODE) {\n  drawTrial();")


def test_the_settings_are_one_line_before_the_roster() -> None:
    """The settings wall: five radio groups and a paragraph stood between a
    buyer and the roster box, though most leagues keep the defaults. Now one
    line drawn from the radios, with "Change" opening them — a real button
    (keyboard, aria-expanded) — and every radio's name and value unchanged,
    so the ref the page encodes is exactly what it was."""
    step = JOIN.split('<section id="step-league">')[1].split("</section>")[0]
    intro = _flat(re.search(r'<div class="note" id="settings-intro">(.*?)</div>', step, re.S)
                  .group(1))
    assert intro == "Pick what your league uses. Six-point passing TDs or TE premium? " \
                    "Pick the closest."
    line = re.sub(r"<[^>]+>", "", re.search(r'<b id="settings-line">(.*?)</b>', step).group(1))
    assert line == "Full PPR · 12 teams · Standard lineup · K and DEF"
    assert re.search(r'<button type="button" class="retry" id="settings-change" '
                     r'aria-expanded="false"\s+aria-controls="settings-body">Change</button>', step)
    body = step.split('<div id="settings-body" hidden>')[1]
    radios = re.findall(r'<input type="radio" name="(\w+)" value="([\w]+)"( checked)?>', body)
    assert radios == [("scoring", "ppr", " checked"), ("scoring", "half_ppr", ""),
                      ("scoring", "standard", ""), ("size", "8", ""), ("size", "10", ""),
                      ("size", "12", " checked"), ("size", "14", ""),
                      ("template", "std", " checked"), ("template", "flex2", ""),
                      ("template", "wr3", ""), ("template", "sf", ""),
                      ("kicker", "yes", " checked"), ("kicker", "no", ""),
                      ("defense", "yes", " checked"), ("defense", "no", "")]
    # The line only ever reads the radios, on every change and at first paint.
    draw = _function(JOIN, "drawSettingsLine")
    for read in ('radio("scoring")', "leagueSize()", "shapeChoice()", "textContent = words"):
        assert read in draw, read
    assert "innerHTML" not in draw
    change = JOIN.split('$("step-league").addEventListener("change", () => {')[1].split("});")[0]
    assert "drawSettingsLine();" in change
    assert "\ndrawSettingsLine();\ndrawShapeNote();\n" in JOIN
    show = _function(JOIN, "showSettings")
    assert 'setAttribute("aria-expanded", open ? "true" : "false")' in show
    # An update whose link carried no settings opens them: the box vouches for them.
    assert "if (!UPDATE_SETTINGS_FROM_LINK) showSettings(true);" in _function(
        JOIN, "prefillUpdateSettings")
    # An ungraded shape's caveat is said even with the radios folded away.
    assert '$("shape-note").hidden = !settingsOpen() && R.GRADED_SHAPES.includes(code);' \
        in _function(JOIN, "drawShapeNote")


def test_a_free_report_that_is_not_open_asks_for_nothing() -> None:
    """m-try: with free reports switched off the page pitched a free report,
    took a roster and an email, and then refused. It now says so in the
    heading and the pitch, takes the form away, and links what works today."""
    branch = _code(JOIN).split("if (TRY_MODE) {\n  drawTrial();")[1].split("} else if (UPDATE_MODE)")[0]
    closed = branch.split("if (FORM_ENDPOINT && TRIAL_OPEN) {")[1].split("} else {", 1)[1]
    said = _flat(closed)
    assert "It isn't open yet, so there's nothing to fill in today." in said
    assert "Free reports aren't open yet." in said
    assert 'link("../sample-report.html", "read a real report")' in closed
    assert 'link("../byes/", "free bye-week planner")' in closed
    assert 'for (const child of $("main").children) child.style.display = "none";' in closed
    assert "closedUpFront(" not in branch
    # A week.json arriving later never redraws a pitch for a closed form.
    assert _function(JOIN, "drawTrial").split("\n")[2].strip() == \
        "if (!(FORM_ENDPOINT && TRIAL_OPEN)) return;"


def test_a_missing_player_list_says_so_and_stops_cleanly() -> None:
    """Reproduced: with roster.js unreachable, "ReferenceError: R is not
    defined" killed the whole page script and left buttons wired to nothing.
    Both pages that load it check for it before the first line that names it,
    say so on the page, and end the script with a throw they swallow."""
    for name, page, check in (("join", JOIN, "if (!window.R) {"),
                              ("byes", BYES, "if (!window.R || !window.B) {")):
        code = _code(page)
        at = code.index(check)
        first = min(m.start() for m in re.finditer(r"\bR\.\w", code))
        assert at < first, f"{name}: R is used before the guard"
        guard = code[at:code.index("\n}\n", at)]
        assert "The player list didn't load — reload the page." in guard, name
        assert "event.error === stop) event.preventDefault()" in guard, name
        assert guard.rstrip().endswith("throw stop;"), name
        assert "innerHTML" not in guard, name


def test_the_join_page_speaks_to_a_one_payment_buyer() -> None:
    """The day-one email is "your first report" to a buyer, never "roster
    report"; the one-payment product has pass holders, not subscribers."""
    buyer = _flat(_markup(JOIN)) + _flat(_code(JOIN))
    assert "roster report" not in buyer.lower()
    assert "Your first report today" in buyer and "your Tuesday report" in buyer
    visible = re.sub(r"<!--.*?-->", "", _flat(_markup(JOIN)), flags=re.S)
    assert not re.search(r"\bsubscriber", visible, re.I)
    assert "doesn't belong to a pass holder" in visible
