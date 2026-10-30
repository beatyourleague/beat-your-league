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
    """One primary action at rest (closed checkout: the email capture), one
    secondary ("See a real report"), the phone beside them, and the Sunday
    scene as the hero's last line. No price anywhere in it."""
    assert re.search(r'<form class="watchform" id="watch-form"', HERO)
    gold = re.findall(r'<(?:a|button)\b[^>]*class="btn gold"[^>]*>', HERO)
    visible = [g for g in gold if " hidden" not in g]
    assert len(visible) == 1 and "<button" in visible[0], gold
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
    have to stop what was armed: the steps, and the close-up's bars."""
    for query in ("@media (prefers-reduced-motion: reduce)", "@media print"):
        block = _blocks(query)
        assert ".js .steps.armed *{animation:none!important;}" in block, query
        assert ".js .shotwrap.reveal .fbar i{transform:none!important;" in block, query


# --------------------------------------------------------------------- #
# what you get: the real report, annotated
# --------------------------------------------------------------------- #

def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_close_up_is_the_generated_report_with_numbered_pins() -> None:
    """The picture is generated (render.phone.shot, from the pinned sample);
    the numbered pins are the page's CSS on the report's own elements — card
    01's title, its Odds column head, card 04's title — so a pin can never
    point at a figure somebody typed. Each pin's target must exist in the
    generated markup, or the pin silently vanishes."""
    from render import phone
    shot = BODY.split("<!-- shot:start -->")[1].split("<!-- shot:end -->")[0]
    assert shot.strip() == phone.shot(_fixture()).strip()
    lineup = shot.split('data-sec="lineup"')[1].split("</section>")[0]
    ifthen = shot.split('data-sec="ifthen"')[1].split("</section>")[0]
    assert '<span class="tag">' in lineup and '<span class="tag">' in ifthen
    assert re.search(r'<div class="ghead"><span>Proj</span><span>Odds</span></div>', lineup)
    pins = dict(re.findall(r'\n  (\.shot [^{]+?)\{content:"(\d)" / "";', CSS))
    assert pins == {".shot [data-sec=lineup] .eyebrow .tag::before": "1",
                    ".shot .ghead span + span::after": "2",
                    ".shot [data-sec=ifthen] .eyebrow .tag::before": "3"}, pins
    callouts = re.findall(r"<li( class=\"off-pic\")?><h3>([^<]+)</h3>",
                          BODY.split('<ol class="callouts">')[1].split("</ol>")[0])
    assert [h for _, h in callouts] == ["Every slot decided", "Odds against your own bench",
                                        "A plan for late news", "Byes checked to your title game"]
    # The fourth is not on the picture (a replayed week checks no byes
    # ahead), so its number is drawn outlined, never as a pin.
    assert [bool(c) for c, _ in callouts] == [False, False, False, True]
    assert re.search(r'<div class="shot screen" role="img" aria-label="[^"]+">\s*'
                     r'<div aria-hidden="true">', LANDING)


def test_the_close_up_crops_only_lines_the_phone_shows_whole() -> None:
    """The close-up keeps every lineup row, the task and the "Checked for
    you" line exactly as printed; it drops only the projected-total line and
    two legend lines, which the phone above shows whole — and a sample that
    no longer carries "Checked for you" stops the build rather than ship a
    blank."""
    from render import anatomy, phone
    report = _fixture()
    shot = phone.shot(report)
    rows = re.findall(r'<div class="frow" data-i="(\d)">', shot)
    assert rows == [str(r["i"]) for r in anatomy.lineup(report)["rows"]]
    assert "Checked for you:" in shot and '<p class="wk">' not in shot
    assert len(re.findall(r'<p class="legend">', shot)) == 1
    broken = copy.deepcopy(report)
    lineup = anatomy.lineup
    try:
        anatomy.lineup = lambda r: {**lineup(r), "legend": []}
        with pytest.raises(phone.SelectionError):
            phone.shot(broken)
    finally:
        anatomy.lineup = lineup


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
    """Beside the $29: one payment, nothing renews, the refund in the terms'
    own words, and "See a real report first" — then the League Pass as one
    line, after the card, never a second card or button."""
    card = BODY.split('id="pass-card"')[1].split('<p class="finance"')[0]
    text = _flat(card)
    assert "$29" in text and "One payment. Nothing renews" in text
    assert ("Full refund, no questions, until your second weekly report's week kicks off. "
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
