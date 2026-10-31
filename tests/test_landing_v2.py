"""The landing, rebuilt simpler (owner plan, Oct 28 2026).

The owner asked for a page a first-timer understands at once: six sections,
more picture than text. The hero (with the Sunday scene as its last line),
how it works as three pictures, ONE picture of the real report with numbered
callouts, rankings against the report as a table, the price with its refund
beside it, and a five-question FAQ before the closer. Each test names what it
protects; the older guards (refund beside price, no price in the hero, the
gate clause, the FAQ twins, the banned words, the closed state failing
closed) moved with the sections they guard and live in their own files.
"""
from __future__ import annotations

import copy
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from test_site import LANDING, SITE, _style, markup_only

CSS = _style(LANDING)
BODY = re.sub(r"<!--(?!/card| ?[\w-]+:(?:start|end) ?).*?-->", "", markup_only(LANDING),
              flags=re.S)
HERO = BODY.split('<header class="hero">')[1].split("</header>")[0]
SCRIPT = "\n".join(re.findall(r"<script>(.*?)</script>", LANDING, re.S))
FIXTURE = SITE.parent / "tests" / "fixtures" / "sample-report-w10.json"


def _flat(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def _section(cls: str) -> str:
    return BODY.split(f'<section class="{cls}"')[1].split("</section>")[0]


def _keyframes(name: str) -> str:
    start = CSS.index(f"@keyframes {name}{{")
    depth, i = 0, CSS.index("{", start)
    for j in range(i, len(CSS)):
        depth += {"{": 1, "}": -1}.get(CSS[j], 0)
        if depth == 0:
            return CSS[i + 1:j]
    raise AssertionError(name)


def _blocks(query: str) -> str:
    out = []
    for at in [m.start() for m in re.finditer(re.escape(query) + r"\{", CSS)]:
        depth, i = 0, CSS.index("{", at)
        for j in range(i, len(CSS)):
            depth += {"{": 1, "}": -1}.get(CSS[j], 0)
            if depth == 0:
                out.append(CSS[i + 1:j])
                break
    assert out, query
    return "\n".join(out)


# --------------------------------------------------------------------- #
# the hero
# --------------------------------------------------------------------- #

def test_the_hero_has_one_action_one_secondary_and_ends_on_the_scene() -> None:
    """One primary action at rest (the roster check, which works with checkout
    closed, Oct 30 2026), one secondary ("See a real report"), the phone beside
    them, and the Sunday scene as the hero's last line. No price anywhere in
    it. The email capture moved to the closer, for whoever isn't ready to paste."""
    assert 'id="watch-form"' not in HERO and "<form" not in HERO
    gold = re.findall(r'<(?:a|button)\b[^>]*class="btn gold"[^>]*>', HERO)
    visible = [g for g in gold if " hidden" not in g]
    assert len(visible) == 1 and 'id="hero-open"' in visible[0], gold
    assert re.search(r'<a class="btn gold" id="hero-open" href="join/index\.html">Check my team</a>',
                     HERO)
    assert re.search(r'<a class="btn ghost" id="hero-sample" href="sample-report.html">'
                     r'See a real report</a>', HERO)
    assert re.search(r'<p class="punch">.*?</p>\s*$', HERO, re.S)
    assert "$" not in _flat(HERO)
    assert "<h1>Know who <em><span>to start.</span></em></h1>" in HERO


# --------------------------------------------------------------------- #
# how it works: three pictures
# --------------------------------------------------------------------- #

def test_how_it_works_is_three_pictures_in_a_few_words_each() -> None:
    """Three steps, each a custom inline picture (decorative, so hidden from
    assistive tech: the words carry the meaning), a title of at most four
    words and a line of at most seven — about eight words a step, ten at most."""
    how = _section("how")
    steps = re.findall(r'<li class="step">(.*?)</li>', how, re.S)
    assert len(steps) == 3
    for step in steps:
        assert re.search(r'<span class="sicon" aria-hidden="true"><svg viewBox="0 0 96 96">', step)
        title = _flat(re.search(r"<h3>(.*?)</h3>", step).group(1))
        line = _flat(re.search(r"<p>(.*?)</p>", step).group(1))
        assert len(title.split()) <= 4 and len(line.split()) <= 7, (title, line)
        assert len(title.split()) + len(line.split()) <= 10, (title, line)
        assert "<img" not in step and "url(" not in step
    # The line to the next picture: on the first two only.
    assert [("wire" in s) for s in steps] == [True, True, False]


def test_how_it_works_moves_on_the_compositor_once_and_holds_offscreen() -> None:
    """Transform and opacity only, every keyframe; played once (nothing
    infinite); animations exist only on an ARMED list and stay paused until
    it is in view (.go) and while it is out of it (.off). The script arms it
    only when it starts below the fold, never under reduced motion, and an
    observer that never reports leaves the finished picture."""
    names = set(re.findall(r"@keyframes (hiw-[\w-]+)\{", CSS))
    assert {"hiw-rise", "hiw-line", "hiw-vline", "hiw-pop", "hiw-kick"} <= names
    for name in names:
        props = set(re.findall(r"([a-z-]+)\s*:", _keyframes(name)))
        assert props <= {"opacity", "transform"}, (name, props)
    for sel, body in re.findall(r"\n  ([^{}@]+)\{([^}]*animation[^}]*)\}", CSS):
        if "hiw-" in body or ".steps" in sel:
            assert ".js .steps.armed" in sel, sel
            assert "infinite" not in body, sel
    assert "animation-play-state:paused;" in re.search(
        r"\.js \.steps\.armed :is\([^)]*\)\{([^}]*)\}", CSS).group(1)
    assert re.search(r"\.js \.steps\.armed\.go:not\(\.off\) :is\([^)]*\)\{\s*"
                     r"animation-play-state:running;\}", CSS)
    arm = SCRIPT.split('const steps = document.querySelector(".steps");')[1].split("\n}\n")[0]
    assert "!reduced" in arm and "getBoundingClientRect().top >= window.innerHeight" in arm
    assert 'steps.classList.toggle("off", !e.isIntersecting)' in arm
    assert 'if (!heard) steps.classList.remove("armed")' in arm


def test_reduced_motion_and_print_show_the_finished_pictures() -> None:
    """The static page IS the end state, so reduced motion and print only
    have to stop what was armed: the steps (step 01's paste card included,
    whose rest state is both columns: the copied lines at 40% and every name
    ticked)."""
    for query in ("@media (prefers-reduced-motion: reduce)", "@media print"):
        block = _blocks(query)
        assert ".js .steps.armed *{animation:none!important;}" in block, query
    raw = re.search(r"\n  \.paste \.raw\{([^}]*)\}", CSS).group(1)
    assert "opacity:.4" in raw
    assert "opacity" not in re.search(r"\n  \.paste \.ok\{([^}]*)\}", CSS).group(1)


def test_how_it_works_plays_in_about_a_second_and_a_half() -> None:
    """Sales review: the three steps took 3.3s to draw. Now the steps start
    .35s apart, each wire draws in .3s and the kick lasts .6s, so the whole
    picture is in by about 1.4s; step 01's paste reads in row by row, 80ms
    apart, 250ms a row."""
    ends = []
    for sel, body in re.findall(r"\n  (\.js \.steps\.armed [^{]+)\{([^}]*)\}", CSS):
        delay = re.search(r"animation-delay:([\d.]+)s", body)
        if delay:
            ends.append(float(delay.group(1)))
    assert max(ends) <= 0.9, ends
    assert ".js .steps.armed .ball{animation-name:hiw-kick;animation-duration:.6s;" in CSS
    assert ".js .steps.armed .wire i{animation-name:hiw-line;animation-duration:.3s;" in CSS
    rows = [float(d) for d in re.findall(
        r"\.prow:nth-child\(\d\) :is\(\.raw,\.ok\)\{animation-delay:([\d.]+)s;\}", CSS)]
    assert len(rows) == 4 and all(round(b - a, 2) == 0.08 for a, b in zip(rows, rows[1:])), rows
    assert ".js .steps.armed .paste .ok{animation-name:hiw-row;animation-duration:.25s;}" in CSS


def test_step_one_shows_a_real_paste_from_the_espn_page() -> None:
    """Step 01 shows the paste: four lines of the ESPN page's own example
    (render/platforms.py, itself backed by a tested paste fixture), each
    beside the name the roster box reads it as — never an invented line."""
    from render.platforms import PLATFORMS
    espn = next(p for p in PLATFORMS if p.slug == "espn")
    step = re.findall(r'<li class="step">(.*?)</li>', _section("how"), re.S)[0]
    rows = re.findall(r'<span class="raw">([^<]+)</span><span class="ok">([^<]+)</span>', step)
    assert len(rows) == 4
    pairs = set(zip(espn.example, espn.reads))
    for raw, read in rows:
        assert (html.unescape(raw), html.unescape(read)) in pairs, (raw, read)
    assert "Copied from ESPN" in step and "Read as" in step


# --------------------------------------------------------------------- #
# what you get: the real report, annotated
# --------------------------------------------------------------------- #

def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_close_up_is_the_generated_report_with_numbered_pins() -> None:
    """Sales review: the close-up repeated the lineup the phone had just
    shown, and its pins 1–3 collided with the report's own badges 01 and 04.
    The picture is now the same email scrolled on past the phone — cards 03
    and 04, generated (render.phone.shot, from the pinned sample) — and the
    pins ARE the report's printed numbers: each callout carries its card's
    own number, the close-up's badges wear the callouts' disc, and the two
    cards on the phone (01, 02) are drawn outlined. No pin is typed onto the
    picture, so none can point at a figure somebody typed."""
    from render import phone
    shot = BODY.split("<!-- shot:start -->")[1].split("<!-- shot:end -->")[0]
    assert shot.strip() == phone.shot(_fixture()).strip()
    badges = re.findall(r'<section class="card" data-sec="(\w+)"><div class="eyebrow">'
                        r'<span class="tag">[^<]+</span><span class="n">(\d+)</span>', shot)
    assert badges == [("plan", "03"), ("ifthen", "04")], badges
    assert ".shot .eyebrow .n{" in CSS and not re.search(r'\.shot [^{]*\{content:"\d"', CSS)
    callouts = re.findall(r'<li( class="[\w-]+")?(?: data-pin="(\d+)")?><h3>([^<]+)</h3>',
                          BODY.split('<ol class="callouts">')[1].split("</ol>")[0])
    assert [(c, n, h) for c, n, h in callouts] == [
        (' class="on-phone"', "01", "Your lineup, decided"),
        (' class="on-phone"', "02", "The week's closest call"),
        ("", "03", "Your game plan"),
        ("", "04", "If/then for gameday"),
        (' class="off-pic"', "", "Byes ahead")], callouts
    # Byes ahead is on no card of a replayed week, so it carries no number.
    assert '.callouts li::before{content:attr(data-pin) / "";' in CSS
    assert '.callouts li.off-pic::before{content:"+" / "";' in CSS
    assert re.search(r'<div class="shot screen" role="img" aria-label="[^"]+">\s*'
                     r'<div aria-hidden="true">', LANDING)
    # The connector from the phone's cards to these two: static, drawn.
    cue = BODY.split('<div class="scrollcue" aria-hidden="true">')[1].split("</div>")[0]
    assert "<svg" in cue and "keep scrolling the same email" in _flat(cue)
    assert "animation" not in re.search(r"\n  \.scrollcue\{([^}]*)\}", CSS).group(1)


def test_the_close_up_shows_what_the_phone_does_not_and_only_the_samples_words() -> None:
    """The close-up shows no card the phone shows (no lineup, no closest
    call, no masthead), card 04 whole, and card 03 cut to three of its items
    exactly as the report prints them, with its standing Saturday line; every
    figure in it is the published sample's. A sample whose plan no longer
    carries a selected item stops the build rather than ship a blank."""
    from render import anatomy, phone
    from test_site import SAMPLE_REPORT
    report = _fixture()
    shot = phone.shot(report)
    assert 'data-sec="lineup"' not in shot and 'data-sec="closest"' not in shot
    assert '<div class="mh">' not in shot
    heads = [html.unescape(h) for h in re.findall(r'<b class="do">([^<]+)</b>', shot)]
    assert [h.split(":")[0].split(" —")[0] for h in heads] == [
        "Bench Sam LaPorta", "Thursday night", "Sunday morning"], heads
    from render.report import SATURDAY_LINE_HEAD
    assert f'<p class="standing"><b>{SATURDAY_LINE_HEAD}:</b>' in shot
    plans = anatomy.ifthen(report)["plans"]
    assert len(re.findall(r'<div class="pivot">', shot)) == len(plans)
    flat_sample = _flat(SAMPLE_REPORT)
    for figure in set(re.findall(r"\d+(?:[.:]\d+)?", _flat(shot))):
        assert figure in flat_sample, figure
    plan = anatomy.plan
    try:
        anatomy.plan = lambda r: {**plan(r), "items": plan(r)["items"][:1]}
        with pytest.raises(phone.SelectionError):
            phone.shot(copy.deepcopy(report))
    finally:
        anatomy.plan = plan


# --------------------------------------------------------------------- #
# rankings vs the report
# --------------------------------------------------------------------- #

def test_the_comparison_is_a_short_table_with_hidden_marks() -> None:
    """Five rows, two columns, real table semantics (column and row headers),
    and the ✓/✕ marks drawn by CSS that assistive tech skips — the column
    head already says which side each cell is on."""
    table = BODY.split('<table class="vstable">')[1].split("</table>")[0]
    assert len(re.findall(r'<th scope="row">', table)) == 5
    assert len(re.findall(r'<th scope="col"', table)) == 2
    assert re.search(r'\.vstable td\.no::before\{content:"\\2715" / "";', CSS)
    assert re.search(r'\.vstable td\.yes::before\{content:"" / "";', CSS)


# --------------------------------------------------------------------- #
# the price
# --------------------------------------------------------------------- #

def test_the_price_card_carries_its_risk_reversal_and_a_way_to_look_first() -> None:
    """Beside the price: when billing stops, the refund in the terms'
    own words, and "See a real report first" — then the League Pass as one
    line, after the card, never a second card or button."""
    card = BODY.split('id="pass-card"')[1].split('<p class="finance"')[0]
    text = _flat(card)
    assert "$14.99" in text and "Stops on its own after your title game" in text
    assert ("Full refund, no questions, until your first weekly report's week kicks off. "
            "One per person") in text
    assert re.search(r'<a class="cardlink" href="sample-report.html">See a real report first</a>',
                     card)
    pricing = BODY.split('<section id="pricing">')[1].split("</section>")[0]
    assert pricing.index('id="pass-card"') < pricing.index('class="lpline"')
    assert pricing.count('class="btn') == 1


# --------------------------------------------------------------------- #
# the script still fits the page
# --------------------------------------------------------------------- #

def test_every_element_the_script_looks_up_by_id_exists() -> None:
    """Removing sections must not leave the script reaching for ids that are
    gone (a null error stops every line after it, the checkout flip
    included). Every getElementById names an id in the markup or one the
    script itself creates."""
    ids = set(re.findall(r'\bid="([^"]+)"', LANDING))
    made = set(re.findall(r'\.id = "([^"]+)"', SCRIPT))
    for wanted in set(re.findall(r'getElementById\("([^"]+)"\)', SCRIPT)):
        assert wanted in ids | made, wanted
    for sel in re.findall(r'querySelector\("(#[\w-]+)"\)', SCRIPT):
        assert sel[1:] in ids | made, sel


def test_every_inline_script_parses() -> None:
    """node --check on each inline script (skipped without node; CI has it)."""
    if shutil.which("node") is None:
        pytest.skip("node not available")
    for body in re.findall(r"<script>(.*?)</script>", LANDING, re.S):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(body)
        done = subprocess.run(["node", "--check", fh.name], capture_output=True, text=True)
        Path(fh.name).unlink(missing_ok=True)
        assert done.returncode == 0, done.stderr


def test_a_ring_in_the_bezels_black_covers_the_seam_of_the_phone_screen() -> None:
    """Every layer inside the screen's rounded clip is antialiased on its own, so
    together they drew a one-pixel light line along the curve behind the dark lock
    screen (owner report, Oct 30 2026). A ring in the bezel's own colour, over the
    screen's edge, covers it in every state.

    It has to sit above the screen's own layers: .screen makes no stacking context
    of its own, so the lock's z-index outranks a ring with none, and the ring then
    does nothing. The screen itself stays paper: making it black to hide the line
    sat the report on black with a hard edge (owner report, same day)."""
    css = LANDING[LANDING.index("<style"):LANDING.index("</style>")]
    screen = re.search(r"\n\s*\.screen\{([^}]*)\}", css).group(1)
    assert "background:#F6F4EE" in screen
    assert not re.search(r"\.screen::before", css)
    bezel = re.search(r"\n\s*\.phone\{([^}]*)\}", css).group(1)
    colour = re.search(r"background:(#[0-9A-Fa-f]{6})", bezel).group(1)
    ring = re.search(r"\n\s*\.edge\{([^}]*)\}", css).group(1)
    assert f"solid {colour}" in ring
    assert "pointer-events:none" in ring
    tops = [int(n) for n in re.findall(r"\.(?:lock|glass|statusbar|island)\{[^}]*?z-index:(\d+)", css)]
    assert tops and int(re.search(r"z-index:(\d+)", ring).group(1)) > max(tops)
    # It reaches past the seam: the screen starts 10px in (the .phone's padding).
    inset = int(re.search(r"inset:(\d+)px", ring).group(1))
    width = float(re.search(r"border:([\d.]+)px", ring).group(1))
    assert inset + width >= 11
    # It is a child of the phone, outside the screen's clip, after the generated block.
    assert re.search(r'<!-- phone:end -->\s*</div>\s*<span class="edge" aria-hidden="true"></span>', LANDING)
