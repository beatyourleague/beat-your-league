"""The landing's polish pass (Oct 24 2026), each piece pinned.

The hero phone rebuilt as hardware, the Tuesday-morning storyline it plays,
the tilt, the motion system (transform and opacity only, paused offscreen,
gone under reduced motion), the email capture's feedback, this week's
recorded closest call in the hero, the free bye-week planner's entry points
(contract C7) and the impulse-buyer section order. Every test states what it
guards; the browser half (overflow at 320/390/1440, LCP/CLS on Slow 4G, axe,
layout counts while scrolling, the reduced-motion end state) was measured in
headless Chrome when this landed and is recorded in the commit.
"""
from __future__ import annotations

import html
import json
import re

from test_site import LANDING, SAMPLE_REPORT, SITE, _js_function, _node, _style, markup_only

CSS = _style(LANDING)
BODY = re.sub(r"<!--.*?-->", "", markup_only(LANDING), flags=re.S)
HERO = BODY.split('<header class="hero">')[1].split("</header>")[0]
SCREEN = HERO.split('<div class="screen">')[1].split('<div class="phone-floor"')[0]
LOCK = '<div class="lock"' + HERO.split('<div class="lock"')[1].split('<div class="lk-dark"')[0]
SCRIPT = "\n".join(re.findall(r"<script>(.*?)</script>", LANDING, re.S))
CLOCK = LANDING.split("// The season clock.")[1]
CLOCK_IIFE = CLOCK[CLOCK.index("(function () {"):CLOCK.index("})();") + 5]


def _flat(page: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))).strip()


def _rule(selector: str) -> str:
    """The declarations of the first rule whose selector is exactly this one,
    at the start of a line (a selector list or a media block is not it)."""
    match = re.search(r"\n  " + re.escape(selector) + r"\{([^}]*)\}", CSS)
    assert match, f"no rule for {selector}"
    return match.group(1)


def _blocks(query: str) -> str:
    """Every block opened by this @media query, joined (the landing keeps a
    one-line reduced-motion rule for buttons beside the main block)."""
    out = []
    for at in [m.start() for m in re.finditer(re.escape(query) + r"\{", CSS)]:
        depth, i = 0, CSS.index("{", at)
        for j in range(i, len(CSS)):
            depth += {"{": 1, "}": -1}.get(CSS[j], 0)
            if depth == 0:
                out.append(CSS[i + 1:j])
                break
    assert out, f"no {query} block"
    return "\n".join(out)


REDUCED = _blocks("@media (prefers-reduced-motion: reduce)")
PRINT = _blocks("@media print")


def _keyframes() -> dict[str, str]:
    found = {}
    for match in re.finditer(r"@keyframes ([\w-]+)\{", CSS):
        depth, i = 0, match.end() - 1
        for j in range(i, len(CSS)):
            depth += {"{": 1, "}": -1}.get(CSS[j], 0)
            if depth == 0:
                found[match.group(1)] = CSS[i + 1:j]
                break
    return found


# --------------------------------------------------------------------- #
# LAND-PHONE-HW: the phone as hardware
# --------------------------------------------------------------------- #

def test_the_phone_is_drawn_as_hardware_from_gradients_alone() -> None:
    """LAND-PHONE-HW: the phone was a flat gunmetal rectangle with two 3px
    bars — beside a product hero it read as a wireframe, and it IS the page's
    proof. It is a glass bezel inside a titanium band (a conic sweep, masked
    to a ring), the five buttons a 16 Pro carries, the island's lens, a glass
    sheen and a contact shadow on the floor. All of it is decoration (hidden
    from assistive tech), and none of it fetches an image."""
    float_at = HERO.index('<div class="phone-float">')
    assert float_at < HERO.index('<div class="phone" id="hero-phone">') < \
        HERO.index('<div class="phone-floor" aria-hidden="true"></div>')
    buttons = re.findall(r'<span\s+class="hw hw-([\w-]+)" aria-hidden="true"></span>', HERO)
    assert buttons == ["action", "up", "down", "side", "cam"], buttons
    assert '<div class="island" aria-hidden="true"><i></i></div>' in HERO
    assert '<div class="glass" aria-hidden="true"><i></i></div>' in HERO
    assert "max-width:320px" in _rule(".phone-float")
    phone = _rule(".phone")
    radius = int(re.search(r"border-radius:(\d+)px", phone).group(1))
    padding = int(re.search(r"padding:(\d+)px", phone).group(1))
    screen = _rule(".screen")
    assert f"border-radius:{radius - padding}px" in screen, "the screen's corner no longer nests"
    assert "container-type:inline-size" in screen
    band = _rule(".phone::before")
    assert "conic-gradient(" in band and "mask:" in band
    lens = _rule(".island i")
    assert "radial-gradient(" in lens and "translateY(-50%)" in lens
    for selector in (".phone", ".phone::before", ".phone::after", ".hw", ".glass", ".glass i",
                     ".phone-floor", ".island i"):
        assert "url(" not in _rule(selector), f"{selector} fetches an image"


def test_the_float_lives_on_its_own_wrapper_so_the_tilt_can_own_the_phone() -> None:
    """LAND-PHONE-HW: the float animated .phone's transform, so a tilt there
    would fight it. The float and the breathing floor shadow move to their
    own elements, and nothing ever writes transform:none on `.phone *` — the
    prototype did, and it knocked the island and the home bar off centre
    (both centre with translateX(-50%))."""
    assert ".js .hero .phone-float{animation:float 6s" in CSS
    assert ".js .hero .phone-floor{animation:floor 6s" in CSS
    assert ".js .hero .phone{animation:float" not in CSS
    assert not re.search(r"\.phone \*\s*\{[^}]*transform", CSS), "a rule un-centres the island"
    for selector in (".island", ".homebar"):
        assert "translateX(-50%)" in _rule(selector)
    # At 880px and below the phone is 286px, and so is everything centred
    # with it, or the phone sits left inside a 320px float.
    narrow = _blocks("@media (max-width:880px)")
    assert ".hero .phone-float,.hero .realrow{max-width:286px;}" in narrow


def test_the_status_bar_time_is_after_the_tuesday_send() -> None:
    """LAND-PHONE-HW: the phone read 8:04 beside "now" while the Tuesday
    cron starts at 12:17 UTC — 08:17 ET in daylight time — so the screen
    showed the email before the send runs. The time is read against the
    workflow's own earliest Tuesday cron, in both EDT and EST, and the lock
    screen says the same time as the status bar."""
    workflow = (SITE.parent / ".github" / "workflows" / "weekly.yml").read_text(encoding="utf-8")
    sends = [(int(h), int(m)) for m, h in re.findall(r'cron: "(\d+) (\d+) \* \* 2"', workflow)]
    assert sends, "no Tuesday cron found in weekly.yml"
    hour, minute = min(sends)
    shown = re.search(r'<div class="statusbar" aria-hidden="true"><span>(\d+):(\d\d)</span>',
                      HERO).groups()
    phone = int(shown[0]) * 60 + int(shown[1])
    for offset in (4, 5):                       # EDT, EST
        local = ((hour - offset) % 24) * 60 + minute
        assert phone > local, f"the phone's {shown} is before the {offset}h-offset send"
    assert f'<div class="lk-time">{shown[0]}:{shown[1]}</div>' in LOCK


# --------------------------------------------------------------------- #
# LAND-PHONE-STORY: the Tuesday-morning storyline
# --------------------------------------------------------------------- #

def test_every_word_and_figure_on_the_phone_is_already_on_the_record() -> None:
    """LAND-PHONE-STORY: the storyline says nothing the pinned sample does
    not. The lock screen carries a day, the time, the sender, the inbox
    preview sentence pinned elsewhere and "now" — nothing else — and every
    figure anywhere on the screen is one the published 2024 W10 sample
    prints. The retired banner's element, CSS and keyframes are gone."""
    words = _flat(LOCK)
    assert words == ("Tuesday 9:41 Beat Your League Your lineup, decided. Closest call "
                     "with odds: Kittle over LaPorta, 72%. now"), words
    flat_sample = _flat(SAMPLE_REPORT)
    for figure in set(re.findall(r"\d+\.\d+|\d+%", _flat(SCREEN))):
        assert figure in flat_sample, f"the phone shows {figure}, which the sample lacks"
    for gone in ('id="notif"', ".notif", "@keyframes notif", "function arrive("):
        assert gone not in LANDING, gone
    # The peek's three parts are grouped so the story can bring each in.
    peek = HERO.split('id="hero-peek"')[1].split('<div class="lock"')[0]
    assert re.findall(r'<div class="pk pk-(\w+)">', peek) == ["call", "if", "rise"]


def test_the_storyline_runs_on_one_clock_with_transform_and_opacity_only() -> None:
    """LAND-PHONE-STORY / LAND-MOTION-COMPLY: one 16s linear loop drives
    every layer, and every keyframe anywhere on the landing animates only
    opacity and transform, so the story and every entrance run on the
    compositor and lay nothing out."""
    frames = _keyframes()
    bindings = re.findall(r"\.phone\.story ([^{]+)\{[^}]*animation:(st-[\w-]+) 16s linear infinite", CSS)
    bound = {name for _, name in bindings}
    assert bound == {n for n in frames if n.startswith("st-")}, (bound, sorted(frames))
    for name, body in frames.items():
        props = set(re.findall(r"([a-z-]+)\s*:", body))
        assert props <= {"opacity", "transform", "animation-timing-function"}, (name, props)
    # The pause holds the layers inside the screen, never .phone itself (the
    # touch tilt runs on .phone and must keep following the scroll).
    assert ".phone.paused .screen *{animation-play-state:paused!important;}" in CSS
    assert not re.search(r"\.phone\.paused\s*\{", CSS)
    for target in (".phone-float", ".phone-floor", ".phonewrap::before"):
        for state in ("offscreen", "still"):
            _assert_pause_wins(target, state)


def _specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes + attributes + pseudo-classes, elements + pseudo-elements)
    of one compound selector chain — enough for the plain selectors the
    landing writes (no :is/:not/:where)."""
    sel = selector.strip()
    pseudo_el = len(re.findall(r"::[\w-]+", sel))
    sel = re.sub(r"::[\w-]+", "", sel)
    ids = len(re.findall(r"#[\w-]+", sel))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]*\]|(?<!:):[\w-]+", sel))
    elements = len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel))
    return ids, classes, elements + pseudo_el


def _assert_pause_wins(target: str, state: str) -> None:
    """LOOK-1: the paused rule must win the cascade over the rule that binds
    the animation, or `animation:` (a shorthand, which resets play-state to
    running) silently undoes it — the float and the floor kept bobbing with
    the hero offscreen while a grep for the pause rule passed. Higher
    specificity, or equal and later in the sheet."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    rules = [(m.start(), m.group(1).strip(), m.group(2))
             for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]

    def hits(selectors: str) -> list[str]:
        return [part.strip() for part in selectors.split(",")
                if part.strip().endswith(target) and not part.strip().startswith("@")]

    binds = [(at, sel) for at, sels, body in rules
             if re.search(r"(?:^|;)\s*animation:\s*(?!none)[\w-]+ \d", body)
             for sel in hits(sels)]
    pauses = [(at, sel) for at, sels, body in rules if "animation-play-state:paused" in body
              for sel in hits(sels) if f".{state}" in sel]
    assert binds, f"nothing binds an animation on {target}"
    assert pauses, f"no .{state} rule pauses {target}"
    for b_at, b_sel in binds:
        assert any(_specificity(p_sel) > _specificity(b_sel)
                   or (_specificity(p_sel) == _specificity(b_sel) and p_at > b_at)
                   for p_at, p_sel in pauses), (target, state, b_sel, pauses)


def test_the_pause_toggle_holds_the_float_the_floor_and_the_glow_too() -> None:
    """LOOK-2: the hero's pause stopped only the screen's storyline; the
    phone kept floating, its floor kept breathing and the glow kept
    pulsing, so the control did not do what its label says. Pressed, it
    marks the hero `.still` (and those three hold, by a rule that wins the
    cascade); pressed again, it clears it and plays. The story ending on
    its own after three loops is not the visitor's pause: the button keeps
    offering one for the float that goes on."""
    story = _js_function(LANDING, "storyline")
    clicked = story.split('toggle.addEventListener("click"')[1].split("});")[0]
    assert 'hero.classList.remove("still")' in clicked and "stop(true)" in clicked
    stop = story.split("const stop = (byVisitor) => {")[1].split("\n  };")[0]
    held = stop.split("if (byVisitor) {")[1].split("}")[0]
    assert 'hero.classList.add("still")' in held and "pressed(true)" in held and "held = true" in held
    assert "if (++cycles >= 3) stop();" in story
    for target in (".phone-float", ".phone-floor", ".phonewrap::before"):
        _assert_pause_wins(target, "still")


def test_the_scroll_beat_softens_its_edge_and_skips_a_beat_that_shows_nothing() -> None:
    """LOOK-3: while the story scrolls the email up, it slid under the opaque
    status bar and was cut flat (half a row under 9:41, a half-disc avatar).
    A 16px fade under the bar shows only during that beat (opacity only,
    invisible at rest), and a beat under 60px — every desktop size, where
    the whole of Rising roles already fits — is skipped with the fade."""
    edge = _rule(".statusbar::after")
    assert "top:100%" in edge and "opacity:0" in edge and "pointer-events:none" in edge
    assert ".phone.story .statusbar::after{animation:st-edge 16s linear infinite;}" in CSS
    assert ".phone.story.flat .statusbar::after{animation:none;}" in CSS
    view = _keyframes()["st-view"]
    assert "58.1%,85%{transform:translateY(var(--scroll" in view
    assert _keyframes()["st-edge"] == "0%,52.5%{opacity:0}58.1%,85%{opacity:1}90%,100%{opacity:0}"
    start = _js_function(LANDING, "storyline").split("const start = () => {")[1].split("\n  };")[0]
    assert "const flat = px < 60;" in start
    assert 'setProperty("--scroll", (flat ? 0 : -px) + "px")' in start
    assert 'heroPhone.classList.toggle("flat", flat)' in start


def test_no_motion_on_the_landing_touches_a_layout_property() -> None:
    """LAND-MOTION-COMPLY: the report-card bars animated width (via timed
    width writes), the button shine animated left, the credential icons
    stroke-dashoffset, and the scroll bar was a script-driven rAF. No
    transition or animation on the page names width, left, height, top,
    margin, padding or stroke-dashoffset now."""
    for decl in re.findall(r"(?:transition|animation)[\w-]*\s*:[^;{}]*", CSS):
        assert not re.search(r"\b(width|left|height|top|margin|padding|stroke-dashoffset)\b",
                             decl), decl
    assert "stroke-dash" not in CSS


def test_the_storyline_waits_plays_in_view_and_rests() -> None:
    """LAND-PHONE-STORY: the decided report holds the screen first (D3), the
    loop runs only while the phone is in view and the tab is visible, three
    loops then rest, and nothing of it runs under reduced motion or without
    IntersectionObserver. The scroll beat is measured once, capped, never
    per frame."""
    story = _js_function(LANDING, "storyline")
    assert 'if (!heroPhone || reduced || !("IntersectionObserver" in window)) return;' in story
    assert "{ threshold: 0.35 }).observe(heroPhone)" in story
    assert re.search(r"setTimeout\(\(\) => \{ wait = 0; start\(\); \}, 4000\)", story)
    assert 'classList.toggle("paused", !inView || document.hidden)' in story
    assert 'classList.toggle("offscreen", !inView)' in story
    assert 'document.addEventListener("visibilitychange", sync)' in story
    assert 'addEventListener("animationiteration"' in story and "++cycles >= 3" in story
    start = story.split("const start = () => {")[1].split("\n  };")[0]
    assert start.count("getBoundingClientRect()") == 2 and "* 0.3" in start
    assert "Math.max(0, Math.min(over, cap))" in start
    assert "storyline();" in SCRIPT


def test_the_storyline_has_a_stop_and_it_moves_nothing_when_it_appears() -> None:
    """WCAG 2.2.2: motion that starts by itself and runs past five seconds
    needs a way to stop it. The toggle is a real button beside the caption,
    in the layout from the first paint (visibility only), with a spacer the
    same width on the other side so the caption stays centred under the
    phone. Stopping returns the screen to the decided report rather than
    freezing a frame of the lock screen; aria-pressed says it is not
    playing, and the label names the control rather than flipping with it.
    Reduced motion and print never show it."""
    button = re.search(r'<button type="button" class="storytoggle" id="story-toggle"([^>]*)>', HERO)
    assert button and 'aria-pressed="false"' in button.group(1) \
        and 'aria-label="Pause the phone animation"' in button.group(1)
    toggle_html = HERO.split('id="story-toggle"')[1].split("</button>")[0]
    assert toggle_html.count('aria-hidden="true"') == 2
    assert "visibility:hidden" in _rule(".storytoggle")
    assert ".storytoggle.ready{visibility:visible;}" in CSS
    assert "width:32px" in _rule(".storytoggle") and "width:32px" in _rule(".realrow::before")
    story = _js_function(LANDING, "storyline")
    clicked = story.split('toggle.addEventListener("click"')[1].split("});")[0]
    assert "stop(true)" in clicked and "start()" in clicked
    stop = story.split("const stop = (byVisitor) => {")[1].split("\n  };")[0]
    assert 'classList.remove("story")' in stop and "pressed(true)" in stop
    assert 'setAttribute("aria-label"' not in story
    for block in (REDUCED, PRINT):
        assert re.search(r"\.storytoggle,\.realrow::before[^{]*\{display:none!important;\}", block)


def test_the_tilt_follows_a_mouse_only_and_rests_flat() -> None:
    """LAND-PHONE-TILT: toward the pointer on a desktop (fine pointer, not
    under reduced motion, mouse events only), eased each frame from a box
    read once rather than per frame, and back at rest the phone carries no
    transform at all so its screen rasterizes crisply. The floor shadow moves
    with `translate` — its own breathing animation owns `transform`, and an
    inline transform under a running animation does nothing. Touch screens
    tilt with the scroll on the compositor instead; the two never meet."""
    tilt = SCRIPT.split("// The tilt, for a mouse")[1].split("})();")[0]
    assert 'window.matchMedia("(hover: hover) and (pointer: fine)").matches' in tilt
    assert "if (!heroPhone || reduced || !window.matchMedia(" in tilt
    assert 'e.pointerType !== "mouse"' in tilt
    assert tilt.count("getBoundingClientRect()") == 1, "the box is read more than once"
    assert "const measure = () => { box = heroPhone.getBoundingClientRect(); };" in tilt
    assert "rotateY(\" + (x * 9)" in tilt and "rotateX(\" + (-y * 6)" in tilt
    assert 'heroPhone.style.transform = "";' in tilt and 'floor.style.translate = "";' in tilt
    assert "floor.style.translate = " in tilt and "floor.style.transform" not in tilt
    coarse = CSS.split("@media (hover:none),(pointer:coarse){")[1].split("\n  }\n")[0]
    assert "@supports (animation-timeline: view())" in coarse
    assert "animation:tiltscroll linear both;animation-timeline:view();" in coarse
    assert ".phone,.phone-float,.phone-floor{animation:none!important;transform:none!important;}" \
        in REDUCED


def test_rest_states_with_no_script_reduced_motion_and_print() -> None:
    """LAND-PHONE-STORY: with no script the lock and the black sit at opacity
    0 over the decided report; under reduced motion and in print they, and
    the moving glass streak, are not drawn at all and nothing inside the
    screen animates."""
    assert "opacity:0" in re.search(r"\n  \.lock,\.lk-dark\{([^}]*)\}", CSS).group(1)
    assert ".lock,.lk-dark,.glass i{display:none!important;}" in REDUCED
    assert ".phone .screen *{animation:none!important;}" in REDUCED
    assert re.search(r"\.lock,\.lk-dark,[^{]*\{display:none!important;\}", PRINT)
    assert ".phone .screen *{animation:none!important;}" in PRINT
    assert ".phone,.phone-float,.phone-floor{animation:none!important;transform:none!important;}" \
        in PRINT


# --------------------------------------------------------------------- #
# LAND-MOTION-COMPLY and LAND-MOTION-SECTIONS
# --------------------------------------------------------------------- #

def test_report_card_bars_fill_by_scale_never_by_width() -> None:
    """LAND-MOTION-COMPLY: play() zeroed every bar's width and wrote it back
    on timers — a layout per bar per frame of the transition. The markup's
    width IS the figure and is never written; the bar scales out from the
    left after its own delay (--bd). Only the print handler sets a width,
    and print and reduced motion draw every bar full."""
    play = _js_function(LANDING, "play")
    assert ".style.width" not in play and 'setProperty("--bd"' in play
    assert "(0.12 + i * 0.16).toFixed(2)" in play
    assert 'bar.style.width = "0%"' not in LANDING
    writes = re.findall(r"\.style\.width = ", SCRIPT)
    printing = LANDING.split('window.addEventListener("beforeprint"')[1].split("\n});")[0]
    assert len(writes) == 1 and "bar.style.width = bar.dataset.w" in printing
    assert ".js .anim [data-w]{transform:scaleX(0);transform-origin:0 50%;" in CSS
    assert ".js .anim.in [data-w]{transform:none;}" in CSS
    for block in (REDUCED, PRINT):
        assert ".js .anim [data-w]{transform:none!important;transition:none!important;}" in block
    for data_w, width in re.findall(r'data-w="(\d+)" style="width:(\d+)%"', BODY):
        assert data_w == width


def test_the_shine_the_icons_and_the_progress_bar_run_on_the_compositor() -> None:
    """LAND-MOTION-COMPLY: the button's sheen moves by transform from a
    parked position off its left edge (it was `left` from -60% to 130%), the
    credential icons pop in by scale and opacity (they were drawn by dash
    offset), and the scroll progress bar is a scroll-driven animation where
    the browser has one — the per-frame script, which read the page height
    every frame, runs only where it does not."""
    assert "transform:translateX(-130%) skewX(-12deg)" in _rule(".btn.gold::after")
    assert "@keyframes shine{to{transform:translateX(330%) skewX(-12deg)}}" in CSS
    assert ".js .cred.stagger svg{opacity:0;transform:scale(.6) rotate(-8deg);" in CSS
    timeline = CSS.split("@supports (animation-timeline: scroll()){")[1].split("\n  }")[0]
    # The shorthand resets animation-timeline, so the timeline comes after it.
    assert ".scrollbar{animation:progress linear both;animation-timeline:scroll(root);}" in timeline
    guard = ('if (progress && !reduced && !(window.CSS && CSS.supports && '
             'CSS.supports("animation-timeline: scroll()")))')
    assert guard in SCRIPT


def test_sections_each_get_one_entrance_and_only_clickables_answer_hover() -> None:
    """LAND-MOTION-SECTIONS: one beat per section, played once on entrance
    from the observers already there — the 12:55 yard line draws, the method
    steps' gold rules draw in order, one glint runs the week, the One
    payment stamp lands (the price never moves: money is disclosure), the
    group-chat bubble is sent, an FAQ answer eases open, the closer's button
    catches the light. The stagger step is 80ms and stops growing at the
    sixth item. D9 stands: nothing that is not a link lifts on hover."""
    assert "(Math.min(i, 6) * 0.08)" in SCRIPT
    parts = SCRIPT.split("const parts = document.querySelectorAll(")[1].split(");")[0]
    for part in (".proofline", ".plannerband", ".leaguepass", ".plans", ".closer > *"):
        assert part in parts, part
    rise = SCRIPT.split("const rise = new IntersectionObserver")[1].split("\n}\n")[0]
    assert 'e.target.matches(".closer > .cta-row")' in rise
    assert 'setTimeout(() => button.classList.add("shine"), 500)' in rise
    assert ".js .proofline.reveal.shown::before{transform:none;" in CSS
    assert ".js .method.stagger article::before{transform:scaleX(0);" in CSS
    assert "border-top:3px solid var(--flag)" in _rule(".method article")
    assert re.search(r"\.js \.timeline\.stagger\.shown::after\{animation:weekpass", CSS)
    assert ".js .plans.reveal.shown .stamp50{animation:stamp" in CSS
    assert not re.search(r"\.price[^{]*\{[^}]*animation", CSS), "the price moves"
    assert ".js .leaguepass.reveal.shown .bubble{opacity:1;transform:none;}" in CSS
    assert ".faq details[open] .a{animation:faqin" in CSS
    for card in (r"\.leaf", r"\.method article", r"\.timeline li", r"\.plan(?:\.founder)?",
                 r"\.plcard", r"\.lpcard", r"\.cred div"):
        assert not re.search(card + r":hover", CSS), f"{card} reacts to hover"
    assert ".btn.gold:hover{transform:translateY(-2px);}" in CSS
    assert ".btn:active{transform:translateY(1px) scale(.985);" in CSS


def test_reduced_motion_and_print_draw_every_new_motion_at_rest() -> None:
    """LAND-MOTION-SECTIONS item 12: every animated selector this pass added
    is neutralised under prefers-reduced-motion (the page is complete at
    rest, measured in Chrome: nothing runs, the scroll-linked progress bar
    included) and in print."""
    for selector in (".heroline .clock", ".livepill .dot::after", ".timeline::after", ".stamp50",
                     ".faq details[open] .a", ".watchnote.ok::before", ".watchform::after",
                     ".js .proofline.reveal::before", ".js .method.stagger article::before",
                     ".js .leaguepass.reveal .bubble", ".js .plans.reveal .plan.founder::after",
                     ".btn.gold::after", "h1 em::after"):
        assert selector in REDUCED, f"{selector} still moves under reduced motion"
    for selector in (".js .proofline.reveal::before", ".js .method.stagger article::before",
                     ".js .leaguepass.reveal .bubble", ".js .plans.reveal .plan.founder::after",
                     ".btn.gold::after", "h1 em::after", ".timeline::after"):
        assert selector in PRINT, f"{selector} can print mid-motion"
    assert "!reduced && !form.classList.contains(\"called\")" in SCRIPT
    # LOOK-7: the progress bar was the one thing left moving under reduced
    # motion (scroll-linked, but motion all the same): not drawn there, and
    # the per-frame fallback never starts.
    assert ".scrollbar{display:none!important;}" in REDUCED
    assert 'if (progress && !reduced && !(window.CSS' in SCRIPT


def test_the_headline_sheen_never_moves_the_headline() -> None:
    """LAND-MOTION-SECTIONS item 2: one pass of light across the gold slab at
    0.4s, on a pseudo-element: the h1's own box and text never animate, so
    the largest paint is untouched, and it plays once."""
    sheen = _rule("h1 em::after")
    assert "animation:shine 1.1s var(--ease-out) .4s 1 forwards" in sheen
    assert not re.search(r"\n  h1(?: em)?(?: span)?\{[^}]*animation", CSS)


# --------------------------------------------------------------------- #
# LAND-CAPTURE-MICRO
# --------------------------------------------------------------------- #

def test_the_capture_answers_the_eye_with_no_new_words() -> None:
    """LAND-CAPTURE-MICRO: while checkout is closed the email field is the
    page's one completable action, and it had no focus state beyond the
    outline and no success moment. The field warms to gold on focus, an
    accepted address (and only that) earns a tick, the "Did you mean" fix
    fades in, a link that lands in the form rings it once with a
    transform/opacity ring, and every message the capture prints is
    unchanged."""
    assert ".watchform input:focus{border-color:rgba(242,194,48,.75);" in CSS
    handler = LANDING.split('watchForm.addEventListener("submit"')[1].split("\n  });")[0]
    assert handler.index('note.className = "watchnote";') < handler.index("const email")
    ok = handler.index('note.className = "watchnote ok";')
    assert handler.index("if (!res.ok)") < ok < handler.index("You're on the list.")
    assert handler.count("watchnote ok") == 1
    for kept in ("That email doesn't look right.", "You're on the list. ",
                 "We couldn't accept that address — check it for typos. Nothing was recorded.",
                 "That didn't send — check your connection and try again. Nothing was recorded."):
        assert kept in handler, kept
    assert "@keyframes callring{from{opacity:.6;transform:none}" in CSS
    click = LANDING.split('document.addEventListener("click", (event) => {')[1].split("\n});")[0]
    assert 'form.classList.add("called")' in click
    assert 'setTimeout(() => form.classList.remove("called"), 900)' in click
    assert ".watchnote .fixmail{animation:faqin" in CSS


# --------------------------------------------------------------------- #
# L1: this week's recorded call, the planner, the order
# --------------------------------------------------------------------- #

_HARNESS = r"""
const real = setTimeout;
function run(w) {
  const timers = [];
  global.setTimeout = (fn, ms) => { if (ms > 1000) { timers.push(ms); return 0; } return real(fn, ms); };
  const make = (id, hidden) => ({ id, hidden, textContent: "", kids: [],
    replaceChildren(...k) { this.kids = k; }, appendChild(k) { this.kids.push(k); } });
  const els = {};
  for (const id of ["season-clock", "this-week-link", "this-week-label", "live-call",
                    "realfoot"]) els[id] = make(id, true);
  for (const id of ["planner-link", "planner-band"]) els[id] = make(id, false);
  global.document = {
    getElementById: (id) => els[id] || null,
    querySelectorAll: (sel) => sel === "[data-live-week]" ? [els["this-week-link"], els["realfoot"]]
      : sel === "[data-planner]" ? [els["planner-link"], els["planner-band"]] : [],
    createElement: (tag) => ({ tag, textContent: "" }), createTextNode: (t) => ({ t }),
  };
  global.window = { fetch: true, AbortSignal: null };
  global.fetch = () => Promise.resolve({ ok: true, json: () => w });
  global.closeForSeason = () => {}; global.showPlayoffPass = () => {};
  global.PLAYOFF_PASS_READY = false; global.PLAYOFF_FROM_WEEK = 13; global.CHECKOUT_OPEN = false;
  IIFE
  return new Promise((r) => real(() => {
    global.setTimeout = real;
    const live = els["live-call"];
    r({ hidden: live.hidden,
        text: live.kids.map((k) => k.t !== undefined ? k.t : k.textContent).join(""),
        bold: live.kids.filter((k) => k.tag === "b").map((k) => k.textContent),
        planner: [els["planner-link"].hidden, els["planner-band"].hidden], timers });
  }, 50));
}
const soon = new Date(Date.now() + 2 * 864e5).toISOString().replace(/\.\d+Z$/, "Z");
const past = new Date(Date.now() - 3600e3).toISOString().replace(/\.\d+Z$/, "Z");
const call = { start: "Odunze", over: "Shaheed", slot: "WR", pct: 61, start_proj: "11.4",
               over_proj: "9.8", label: "Closest call with odds", tossup: false };
const base = { season: "2026", week: 7, last_week: 18, lands_on: "2999-01-05",
  built_at: "2026-10-20T17:15:45+00:00", closest_call: true, odds: 3, phase: "season",
  first_kickoff: soon, recorded: true, closest: call };
const cases = CASES;
(async () => {
  const out = [];
  for (const c of cases) out.push(await run(c));
  console.log(JSON.stringify(out));
})();
"""


def _clock(cases: str) -> list[dict]:
    return _node(_HARNESS.replace("IIFE", CLOCK_IIFE).replace("CASES", cases))


def test_the_live_call_shows_only_a_recorded_call_before_kickoff() -> None:
    """L1 / contract C6: one line under the live link names this week's
    closest call with odds — only from the record the Tuesday build wrote
    (week.json "closest"), only in a season week that build recorded, only
    until the week's first kickoff (when the call is about a game underway),
    never for a toss-up (52% or less, or under half a point: the report says
    "either is fine" there — C6-1: the writer prints the projections as
    strings, "10.4", so a numbers-only check never fired; the writer's own
    `tossup` now decides first and a missing one fails closed, as
    render/og.py's does), and always as text. Run under node against the
    page's own season-clock script: one good week shows exactly the
    recorded words and figure and schedules its own removal at kickoff;
    every other case leaves the line hidden. A player's name never breaks
    across the line's wrap (its spaces are no-break spaces)."""
    shown, *held = _clock("""[
      base,
      { ...base, first_kickoff: past },
      { ...base, after_kickoff: true },
      { ...base, recorded: undefined },
      { ...base, recorded: false },
      { ...base, closest: undefined },
      { ...base, closest: { ...call, pct: 52 } },
      { ...base, closest: { ...call, start_proj: "11.2", over_proj: "10.8" } },
      { ...base, closest: { ...call, start_proj: 11.2, over_proj: 10.8 } },
      { ...base, closest: { ...call, pct: 55, start_proj: "10.4", over_proj: "10.0", tossup: true } },
      { ...base, closest: { ...call, tossup: true } },
      { ...base, closest: { ...call, tossup: undefined } },
      { ...base, closest: { ...call, tossup: "false" } },
      { ...base, closest: { ...call, pct: 61.5 } },
      { ...base, closest: { ...call, start: 7 } },
      { ...base, odds: 2 },
      { ...base, phase: "preseason" },
      { ...base, first_kickoff: "garbage" },
      { ...base, closest: { ...call, start: " Rome  Odunze ", over: "Marvin Harrison Jr." } },
    ]""")
    *held, named = held
    assert named["hidden"] is False and named["text"] == (
        "Closest call with odds: Rome\u00a0Odunze over Marvin\u00a0Harrison\u00a0Jr., 61%"), named
    assert shown["hidden"] is False
    assert shown["text"] == "Closest call with odds: Odunze over Shaheed, 61%"
    assert shown["bold"] == ["61%"]
    assert len(shown["timers"]) == 1 and 1.9 * 864e5 < shown["timers"][0] < 2.1 * 864e5
    for i, case in enumerate(held):
        assert case["hidden"] is True and case["text"] == "", f"case {i + 1} showed {case}"


def test_the_live_call_is_written_as_text_into_reserved_room() -> None:
    """L1: the names come from a file a build writes, so they reach the page
    as text nodes only (no innerHTML anywhere in the season clock), and the
    line's room is reserved — two lines where two full names wrap — so its
    arrival moves nothing (CLS)."""
    assert "innerHTML" not in CLOCK_IIFE and "insertAdjacentHTML" not in CLOCK_IIFE
    assert re.search(r'<a class="livepill"[^>]*>.*?</a>\s*<p class="livecall" id="live-call" hidden></p>',
                     HERO, re.S)
    assert ".livecall[hidden]{display:block!important;visibility:hidden;" in CSS
    assert "min-height:1.45em" in _rule(".livecall")
    assert "@media (max-width:600px){.livecall{min-height:2.9em;}}" in CSS
    assert ".hero .livecall{order:7;}" in _blocks("@media (max-width:880px)")


def test_the_planner_is_linked_where_contract_c7_says_and_hides_with_the_season() -> None:
    """L1 / contract C7: the free bye-week planner lives at /byes/ and every
    link to it from the site root is href="byes/". The hero carries a text
    link (never a third button) and a band sits after "Your week, handled"
    with a ghost button, so the gold price CTA keeps priority. Both go once
    no bye is left to plan for (byes_left false) or the season is over (run
    under node), and the open checkout keeps the hero on buying."""
    hrefs = re.findall(r'href="([^"]*bye[^"]*)"', BODY)
    assert hrefs and set(hrefs) == {"byes/"}, hrefs
    assert '<a class="textlink" id="planner-link" data-planner href="byes/">Free: your byes ' \
           'through Week 17</a>' in HERO
    band = BODY.split('<section class="plannerband" data-planner')[1].split("</section>")[0]
    assert '<a class="btn ghost" href="byes/">Check my byes</a>' in band and "btn gold" not in band
    nobyes, over, kept = _clock("""[
      { ...base, byes_left: false }, { ...base, phase: "over" }, base ]""")
    assert nobyes["planner"] == [True, True] and over["planner"] == [True, True]
    assert kept["planner"] == [False, False], "a week with byes left hid the planner"
    complete = LANDING.split("if (CHECKOUT_CAN_COMPLETE) {")[1].split("} else {")[0]
    assert 'getElementById("planner-link")' in complete and "plannerLink.hidden = true" in complete


def test_the_landing_reads_in_impulse_buyer_order() -> None:
    """L1: the ninety-seconds-on-Tuesday promise ("Your week, handled") now
    comes before the method, so it lands before the deliberation, with the
    free planner between them; the rest of the order is unchanged."""
    heads = [_flat(h) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", BODY, re.S)]
    assert heads[:4] == ["What lands in your inbox", "Your week, handled", "Bye-week planner",
                         "How every call gets made"], heads
    assert heads.index("How every call gets made") < heads.index("Take it through your title game.")


def test_the_word_neutral_copy_says_the_same_thing_in_fewer_words() -> None:
    """L1: the hero sub says what the email does (it said "decided by the
    numbers", which says nothing); the method cards leave the supported list
    to the FAQ; the FAQ twins stay word for word equal to their structured
    data; the footer no longer dates every visual to 2024 (the hero's 2026
    line is labelled as this week's)."""
    sub = _flat(re.search(r'<p class="sub">(.*?)</p>', HERO, re.S).group(1))
    assert sub == ("Every Tuesday, one email sets your lineup for your exact roster — all "
                   "the way to your title game.")
    assert "decided by the numbers" not in LANDING and "$" not in _flat(HERO)
    method = _flat(BODY.split('<div class="method">')[1].split("</section>")[0])
    assert "Your scoring, your league's size, the lineup your league starts." in method
    assert "byes, announced injuries and each game's expected scoring." in method
    faq = BODY.split('<section id="faq">')[1].split("</section>")[0]
    qa = {q: _flat(a) for q, a in re.findall(r"<summary>(.*?)</summary>\s*<div class=\"a\">(.*?)</div>",
                                             faq, re.S)}
    block = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                 LANDING, re.S).group(1))
    twin = {q["name"]: q["acceptedAnswer"]["text"]
            for q in next(n for n in block["@graph"] if n["@type"] == "FAQPage")["mainEntity"]}
    for question in ("Does it work with my league?", "How is this different from free rankings?"):
        assert qa[question] == twin[question], question
    assert "Sample visuals above are real output, labeled where shown." in _flat(BODY)


# --------------------------------------------------------------------- #
# speed: the fonts
# --------------------------------------------------------------------- #

def test_the_landing_inlines_fonts_css_rule_for_rule() -> None:
    """The landing's largest paint waited on fonts/fonts.css: a render-
    blocking stylesheet on a round trip of its own, sharing a Slow 4G pipe
    with the page — measured in headless Chrome (390, Slow 4G, 4x CPU,
    median of 4): 1.58s linked, 1.15s with its rules inline, and with the
    rules inline the page's own size stopped mattering (30KB of padding at
    the tail moved nothing, against +40ms linked). So the landing carries
    the file's rules inline, and this holds that copy to the file: the same
    declarations, in the same order, each url() pointing into fonts/ —
    edit fonts.css and this fails until the landing's copy is pasted again.
    No other page changes (each still links the file)."""
    def rules(css: str) -> list[str]:
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        return [re.sub(r"\s+", "", r) for r in re.findall(r"@font-face\{[^}]*\}", css)]
    source = (SITE / "fonts" / "fonts.css").read_text(encoding="utf-8")
    want = [re.sub(r"url\(([^)'\"]+)\)", r"url(fonts/\1)", r) for r in rules(source)]
    got = rules(CSS)
    assert want and got == want, "the landing's inline faces drifted from fonts/fonts.css"
    assert 'href="fonts/fonts.css"' not in LANDING
    head = LANDING.split("</head>")[0]
    assert head.count('rel="preload"') == 2 and "barlow-condensed-900i.woff2" in head
    for url in re.findall(r"url\(fonts/([^)]+)\)", "".join(got)):
        assert (SITE / "fonts" / url).is_file(), url
