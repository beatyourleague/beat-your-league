"""The pages' polish pass (Oct 24 2026): one depth, focus ring and button feel
across the paper pages (PAGES-FOUNDATION), the join page's settings, roster
check and not-open notice (JOIN-*), a success moment on thanks, a miss with
character on 404 and an honest busy state on confirm (PAGES-THANKS-404-
CONFIRM), the League Pass page's feel on its dark design (PAGES-LEAGUEPASS),
how-it-works' bars and compare's sideways table (PAGES-HOW-COMPARE), and a
game plan you can tick in the browser report (REPORT-CHROME).

Every behaviour was also checked in headless Chrome at 320, 390 and 1440 —
keyboard focus by real Tab presses, reduced motion by media emulation, axe-core
on the checked, closed and ticked states. These tests hold the parts a test
reading the files can hold; each docstring says what it guards."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import render.report as rr
from test_site import _js_function, _node, _style

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PAPER = ("join/index.html", "join/confirm.html", "how-it-works.html", "thanks.html",
         "404.html", "compare/index.html")
OWNED = PAPER + ("league-pass.html",)
MOTION = SITE / "motion.js"
BLOCK_START = "  /* ---- paper pages: one depth"
BLOCK_END = "  /* ---- end of the shared paper block ---- */\n"
TEMPLATE = rr.TEMPLATE_PATH.read_text(encoding="utf-8")


def _page(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def _block(page: str) -> str:
    start = page.index(BLOCK_START)
    return page[start:page.index(BLOCK_END, start) + len(BLOCK_END)]


def _media(css: str, query: str) -> list[str]:
    """The bodies of every ``@media <query>{...}`` in ``css`` (braces matched)."""
    out, at = [], 0
    while True:
        at = css.find(f"@media {query}" + "{", at)
        if at < 0:
            return out
        depth, i = 0, css.index("{", at)
        for j in range(i, len(css)):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            if depth == 0:
                out.append(css[i + 1:j])
                break
        at = j


def _keyframes(css: str) -> dict[str, str]:
    found = {}
    for match in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", css):
        depth, i = 0, match.end() - 1
        for j in range(i, len(css)):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            if depth == 0:
                found[match.group(1)] = css[i + 1:j]
                break
    return found


# --------------------------------------------------------------------- #
# PAGES-FOUNDATION — one block, one script
# --------------------------------------------------------------------- #

def test_one_shared_block_gives_every_paper_page_the_same_depth_focus_and_press() -> None:
    """Before: join/, how-it-works, thanks, 404, confirm and compare each kept
    their own shadow (0 2px 18px here, 0 30px 60px -30px there), their own
    hover lift (1px, 2px), no press state and default focus rings — a funnel
    assembled rather than designed. One block, pasted identically, last in each
    sheet so a page's older rule of the same weight cannot win; a drifted copy
    fails here (mutation: change one page's --elev-2). Truth pass (contract
    C7): one paper shadow, a 1px lift on hover, and no sheen — the flat button
    has nothing sweeping across it."""
    blocks = {name: _block(_page(name)) for name in PAPER}
    first = blocks[PAPER[0]]
    for name, block in blocks.items():
        assert block == first, f"{name}: the shared paper block drifted"
        page = _page(name)
        assert page.count(BLOCK_START) == 1, name
        assert page.index(BLOCK_END) + len(BLOCK_END) == page.index("</style>"), \
            f"{name}: the shared block must close the sheet"
    for token in ("--elev-1:", "--elev-2:", "--ease-out:", "--ease-pop:"):
        assert token in first
    assert ("--elev-2:0 1px 2px rgba(16,30,51,.06),0 8px 24px -12px rgba(16,30,51,.18);"
            in first), "not contract C7's paper shadow"
    assert ".btn:active,button:active:not(:disabled){transform:translateY(1px) scale(.985)" in first
    assert ".btn:hover,button:hover:not(:disabled){transform:translateY(-1px);}" in first
    assert "skewX" not in first and ".btn.gold::after" not in first, \
        "the shared block still sweeps a sheen"


def test_a_phone_still_shows_the_paper_edge_to_edge() -> None:
    """D15 holds, at every width now (truth pass, contract C2): the shared
    block draws no sheet and no sheet shadow at all, so no page can be put
    back on a desk by a later rule of the same weight."""
    block = _block(_page("thanks.html"))
    assert ".sheet" not in block and ".page," not in block and "--elev-3" not in block
    assert not re.search(r"(?<![\w-])\.(?:sheet|page|report)\{[^}]*box-shadow", block)


def test_motion_js_is_versioned_and_loaded_only_where_a_block_reveals() -> None:
    """site/motion.js is loaded as its own versioned file, like email-check.js,
    so a changed script is never served stale from a cache — and only on pages
    that mark something to reveal (a page with nothing to reveal pays no
    request). It is same-origin, so it needs no CSP hash (script-src 'self')."""
    digest = hashlib.sha256(MOTION.read_bytes()).hexdigest()[:10]
    tag = f'<script src="/motion.js?v={digest}" defer></script>'
    for name in OWNED:
        page = _page(name)
        reveals = "data-reveal" in re.sub(r"<style>.*?</style>", "", page, flags=re.S)
        assert page.count(tag) == (1 if reveals else 0), \
            f"{name}: motion.js changed or is loaded where nothing reveals (?v={digest})"
        assert page.count("/motion.js?v=") == page.count(tag), f"{name}: a stale digest"


def test_motion_js_stores_nothing_sends_nothing_and_writes_no_markup() -> None:
    """The privacy page says nothing is stored on a visitor's device and no
    page contacts a third party; this script reads the layout and toggles two
    classes, nothing more."""
    code = MOTION.read_text(encoding="utf-8")
    for banned in ("fetch(", "sendBeacon", "XMLHttpRequest", "localStorage", "sessionStorage",
                   "cookie", "indexedDB", "innerHTML", "http:", "https:", "import("):
        assert banned not in code, banned


_MOTION_HARNESS = r"""
const vm = require("node:vm");
const src = __SRC__;
function run(opts) {
  const log = [];
  const timers = [];
  let observer = null;
  const mk = (top, kind, kids = 0) => {
    const el = {
      top, kind, cls: new Set(), observed: false, vars: {}, children: [],
      getAttribute: (n) => (n === "data-reveal" ? kind : null),
      getBoundingClientRect() { log.push("rect:" + html.has("motion")); return { top }; },
      classList: { add(c) { el.cls.add(c); } },
      style: { setProperty() {} },
    };
    for (let i = 0; i < kids; i++) {
      const child = { d: null, style: { setProperty(k, v) { child.d = v; } } };
      el.children.push(child);
    }
    return el;
  };
  const html = new Set();
  const items = [mk(100, ""), mk(2000, ""), mk(3000, "group", 8)];
  const win = {
    innerHeight: 844,
    setTimeout: (fn, ms) => timers.push([ms, fn]),
    addEventListener: () => {},
    matchMedia: () => ({ matches: !!opts.reduced }),
    document: {
      querySelectorAll: () => (opts.none ? [] : items),
      documentElement: { classList: { add(c) { log.push("class:" + c); html.add(c); } } },
    },
  };
  if (!opts.noIO) {
    win.IntersectionObserver = function (cb) {
      observer = this;
      this.cb = cb;
      this.observe = (el) => { el.observed = true; };
      this.unobserve = (el) => { el.observed = false; };
    };
  }
  win.window = win;
  vm.runInNewContext(src, win);
  const state = () => items.map((el) => ({ in: el.cls.has("in"), observed: el.observed }));
  const out = { log, motion: html.has("motion"), at: state(),
                delays: items[2].children.map((c) => c.d) };
  if (observer) {
    observer.cb([{ isIntersecting: true, target: items[1] }]);
    out.afterScroll = state();
    timers.forEach(([, fn]) => fn());
    out.afterTimer = state();
    out.timers = timers.map(([ms]) => ms);
  }
  return out;
}
console.log(JSON.stringify({ normal: run({}), noIO: run({ noIO: true }),
                             reduced: run({ reduced: true }), none: run({ none: true }) }));
"""


def test_motion_js_fails_open_and_never_flashes_a_block_in_view() -> None:
    """Run for real under node: with no IntersectionObserver, with reduced
    motion, or with nothing marked, the hiding class never goes on (the page is
    complete without the script). Otherwise a block already in view is shown in
    the same task, a block below the fold waits for the observer, a group's
    children stagger by 70ms capped at six, and everything shows after six
    seconds whatever happens. Every box is measured BEFORE the class goes on:
    measuring after would compute an in-view block hidden first, and it would
    fade in from nothing (the spec's order did exactly that; mutation: swap
    them)."""
    got = _node(_MOTION_HARNESS.replace("__SRC__", json.dumps(MOTION.read_text(encoding="utf-8"))))
    for case in ("noIO", "reduced", "none"):
        assert got[case]["motion"] is False, case
        assert not any(x["in"] for x in got[case]["at"]), case
    normal = got["normal"]
    assert normal["motion"] is True
    log = normal["log"]
    assert log.index("class:motion") > max(i for i, x in enumerate(log) if x.startswith("rect:"))
    assert all(x == "rect:false" for x in log if x.startswith("rect:"))
    assert normal["at"] == [{"in": True, "observed": False}, {"in": False, "observed": True},
                            {"in": False, "observed": True}]
    assert normal["delays"] == ["0ms", "70ms", "140ms", "210ms", "280ms", "350ms", "420ms", "420ms"]
    assert normal["afterScroll"][1] == {"in": True, "observed": False}
    assert normal["timers"] == [6000] and all(x["in"] for x in normal["afterTimer"])


def test_a_reveal_never_holds_a_headline_the_largest_paint_or_the_words() -> None:
    """data-reveal hides a block until it scrolls into view, so it may never
    sit on a header, an h1, a paragraph of explanation or anything that could be
    the page's largest paint (LCP must stay inside 2.5s). How it works reveals
    its pictures of the report, never the glossary beside them."""
    for name in OWNED:
        page = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", _page(name), flags=re.S)
        header = page.split("<header", 1)[1].split("</header>", 1)[0] if "<header" in page else ""
        assert "data-reveal" not in header, name
        for tag, attrs in re.findall(r"<(\w+)([^>]*\bdata-reveal\b[^>]*)>", page):
            assert tag in ("div", "aside"), f"{name}: data-reveal on <{tag}>"
            assert not re.search(r'class="[^"]*\b(?:terms|lede|note)\b', attrs), (name, attrs)
    # The cell around each generated card (the truth pass: the card itself is
    # render/phone.py's, injected whole between its hiw-* markers).
    how = re.findall(r'<div class="([^"]+)"[^>]*\bdata-reveal\b', _page("how-it-works.html"))
    assert how and set(how) == {"annocard"}, how


# --------------------------------------------------------------------- #
# Motion rules: transform and opacity, reduced motion, LCP never held
# --------------------------------------------------------------------- #

def test_every_new_animation_moves_or_fades_and_nothing_else() -> None:
    """Quality bar: motion is transform and opacity only (compositor-friendly,
    never a layout). Every keyframe on these pages and the report template
    animates those two properties alone — except the thank-you check's
    stroke draw, which predates this pass and is an SVG line being drawn."""
    for name, css in [(n, _style(_page(n))) for n in OWNED] + [("template", _style(TEMPLATE))]:
        for kf, body in _keyframes(css).items():
            if kf == "draw":
                continue
            props = set(re.findall(r"([a-z-]+)\s*:", body))
            assert props <= {"transform", "opacity"}, f"{name} @keyframes {kf}: {props}"


def test_page_load_entrances_move_and_never_fade() -> None:
    """An entrance at load that starts from opacity 0 holds back the largest
    paint; rise-t moves only (the thanks headline and steps, 404's headline)."""
    assert "@keyframes rise-t{from{transform:translateY(10px);}}" in _block(_page("404.html"))
    for name, selector in (("thanks.html", ".done h1{animation:rise-t"),
                           ("thanks.html", ".steps li{animation:rise-t"),
                           ("404.html", "header h1{animation:rise-t")):
        assert selector in _style(_page(name)), (name, selector)


def test_reduced_motion_lands_every_animation_on_its_last_frame() -> None:
    """Fully disabled under prefers-reduced-motion, with the page complete at
    rest: no press or lift, no sheen, and every animation (entrances, the
    burst, the busy dots, the cascade) collapsed to its final frame — checked
    in Chrome by media emulation as well (the checked roster complete at frame
    0, the thank-you page and the League Pass page static). The buttons carry
    no sheen at all since the truth pass (contract C7); the one sheen left,
    the League Pass headline's slab, is hidden under reduced motion."""
    for name in OWNED:
        css = _style(_page(name))
        reduced = "".join(_media(css, "(prefers-reduced-motion:reduce)"))
        assert "animation-duration:.01ms!important" in reduced, name
        assert "animation-iteration-count:1!important" in reduced, name
        assert "transform:none!important" in reduced, name
        for sheen in re.findall(r"([^{}]+::after)\{[^}]*skewX", css):
            assert "display:none" in reduced and sheen.strip().split(",")[0] in reduced, \
                f"{name}: the sheen runs ({sheen.strip()})"
        assert not re.search(r"\.btn[^{}]*::after\{[^}]*skewX", css), f"{name}: a button sheen"


def test_a_slanted_gold_button_shows_its_focus_ring() -> None:
    """Reproduced by Tab in headless Chrome: 404's "Back to the front page"
    took keyboard focus with NO visible ring, because clip-path clips the
    outline along with everything else (before-404-focus-390.png). Contract
    C7 retired the slant on every surface — a flat rounded rectangle, no
    clip-path — so no button can clip its own focus ring: none remains on
    any of these pages, the landing or the report template, and the
    template's keyboard focus draws a navy ring."""
    for name in (*OWNED, "index.html"):
        assert "clip-path:polygon" not in _style(_page(name)), f"{name} clips a button again"
    assert "clip-path:polygon" not in TEMPLATE
    assert ".btn:focus-visible{outline:3px solid var(--navy);outline-offset:2px;}" in TEMPLATE


def test_focus_on_paper_is_navy_never_gold() -> None:
    """Gold on the paper measured 1.5:1, under the 3:1 a focus ring needs; the
    chips' ring and compare's links were gold there. Navy on paper; the navy
    bars keep gold (.sitebar a:focus-visible)."""
    join = _style(_page("join/index.html"))
    assert ".opts label:has(input:focus-visible){outline:3px solid var(--navy);" in join
    compare = _style(_page("compare/index.html"))
    assert "a:focus-visible{outline:3px solid var(--navy);" in compare
    assert ".tablewrap:focus-visible{outline:3px solid var(--navy);" in compare
    for name in OWNED:
        assert ".sitebar a:focus-visible{outline:3px solid #F2C230;" in _style(_page(name)), name
    assert ".price a:focus-visible{outline-color:var(--navy);}" in _style(_page("league-pass.html"))


# --------------------------------------------------------------------- #
# JOIN — settings, the roster check, the not-open notice
# --------------------------------------------------------------------- #

JOIN = _page("join/index.html")
JOIN_CSS = _style(JOIN)


def test_the_progress_bar_fills_instead_of_recolouring() -> None:
    """JOIN-SETTINGS: the 3-step bar recoloured in place. The border is now the
    dim track and each step FILLS it from the left (transform), on the same
    three conditions that light it: step 2 once the roster box holds text,
    step 3 once the email step opens. Gold is the FILL only (contract C6,
    truth pass): a reached step's label turns white, its 3px track gold."""
    assert ".progress .on{color:#FFFFFF;}" in JOIN_CSS
    assert "background:var(--flag);transform:scaleX(0);transform-origin:0 50%;" in JOIN_CSS
    fill = JOIN_CSS.split("  .progress .on::before,", 1)[1].split("{transform:none;}", 1)[0]
    for when in ("body:has(#roster-text:not(:placeholder-shown)) .progress .s2::before",
                 "body:has(#step-email:not(.hidden)) .progress .s2::before",
                 "body:has(#step-email:not(.hidden)) .progress .s3::before"):
        assert when in fill, when


def test_a_chip_pops_only_when_it_is_the_one_just_chosen() -> None:
    """JOIN-SETTINGS: the chips switched with no physical response. The pop is
    scoped to :focus-within, so the chips checked by default do not all pop
    when the page loads."""
    assert ".opts:focus-within label:has(input:checked){animation:chipin" in JOIN_CSS
    assert not re.search(r"(?<!:focus-within )label:has\(input:checked\)\{animation", JOIN_CSS)
    assert ".settings-ok:has(input:checked){border-color:var(--turf);background:var(--turf-tint);}" \
        in JOIN_CSS


def test_the_roster_check_reads_back_in_two_columns_and_marks_itself_done() -> None:
    """JOIN-ROSTER-SUCCESS: fifteen full-width rows were ~915px and pushed
    step 3 a full screen down at 1440. Two columns from 360px (one at 320),
    rows needing work span the width above the pairs, an odd count is filled
    white; the tally says "good" with a check; and once the roster checks out
    the button steps down so the next step owns the gold. Checked in Chrome:
    at 1440 the step-3 heading is in view with the list's end."""
    assert "@media (min-width:360px){" in JOIN_CSS
    two = JOIN_CSS.split("@media (min-width:360px){", 1)[1].split("}\n  }", 1)[0]
    assert "#rows .rows{grid-template-columns:repeat(2,minmax(0,1fr));}" in two
    assert "#rows .row.choose,#rows .row.bad{grid-column:1 / -1;}" in two
    draw = _js_function(JOIN, "draw")
    assert 'row.style.setProperty("--i", position);' in draw
    assert ('wrap.classList.toggle("odd", wrap.querySelectorAll(".row:not(.bad):not(.choose)")'
            '.length % 2 === 1);') in draw
    assert draw.index('classList.toggle("odd"') < draw.index("list.appendChild(wrap);")
    assert 'tally.className = "tally" + (problem ? " bad" : empty.length ? " warn" : " good");' in draw
    assert '$("resolve").classList.toggle("is-done", state.ready);' in draw
    # The done check steps down to the flat secondary (contract C7).
    assert ("#resolve.is-done{background:var(--card);color:var(--navy);"
            "border:1.5px solid var(--navy);}") in JOIN_CSS
    edit = JOIN.split('$("roster-text").addEventListener("input", () => {', 1)[1].split("});", 1)[0]
    assert '$("resolve").classList.remove("is-done");' in edit, \
        "an edited roster must hand the gold back to the check"


def test_only_a_real_check_cascades_the_rows() -> None:
    """The cascade runs on "Check my roster" only: .fresh is set for 900ms in
    the click handler, never in draw(), so removing a player or picking one
    redraws the list without the rows dancing again."""
    click = JOIN.split('$("resolve").addEventListener("click", () => {', 1)[1].split("\n});", 1)[0]
    assert 'rows.classList.add("fresh");' in click
    assert 'setTimeout(() => rows.classList.remove("fresh"), 900);' in click
    assert click.index('classList.add("fresh")') < click.index("draw();")
    assert '"fresh"' not in _js_function(JOIN, "draw")
    assert "#rows.fresh .row{animation:rowin" in JOIN_CSS


def test_checkout_not_open_is_a_notice_and_a_failed_send_is_still_an_error() -> None:
    """JOIN-NOTICE-READBACK: with no list endpoint, "Checkout opens soon" after
    a whole roster showed its message in the brick error box, so a visitor's
    effort ended looking like a failure. The three not-open messages are an
    info notice (role=alert and the focus stay); a send that failed stays an
    error. An empty message clears the tone."""
    show = _js_function(JOIN, "showError")
    assert 'function showError(id, message, tone) {' in show
    assert '$(id).dataset.tone = tone || "";' in show
    handler = JOIN.split('$("form-email").addEventListener("submit"', 1)[1].split(
        "\n// The hand-off to Stripe", 1)[0]
    closed = handler.split("if (!link) {", 1)[1]
    calls = re.findall(r'showError\("err-email", (.*?)\);', closed, re.S)
    info = [c for c in calls if c.rstrip().endswith('"info"')]
    # Four since Oct 30 2026: the mail-app request (askByMail, which sits
    # between the handler and the hand-off) is a not-open notice too.
    assert len(info) == 4, calls
    assert all("isn't open just yet" in re.sub(r'"\s*\+\s*"', "", c) for c in info)
    failed = closed.split(".catch((err) => {", 1)[1].split("});", 1)[0]
    assert "showError(" in failed and '"info"' not in failed
    # A calm card, not a brick alert — and no side bar (contract C7).
    assert '.err[data-tone="info"]{background:var(--card);border-color:var(--line);' in JOIN_CSS
    err = re.search(r"\n  \.err\{([^}]*)\}", JOIN_CSS).group(1)
    assert "border:1px solid" in err and "border-left" not in err


def test_the_read_back_and_the_list_arrive_rather_than_appear() -> None:
    """The address read back before Stripe locks it gets a highlight and a
    settle; the typeahead drops in; a suggestion row shows a navy ring inside
    the list; the field's halo has room under the step's note."""
    for rule in ("#check-address{background:var(--flag-tint);",
                 ".checkmail:not([hidden]){animation:stepin",
                 ".suggest:not(:empty){animation:dropin",
                 ".sugrow:focus-visible{outline:2px solid var(--navy);outline-offset:-2px;}",
                 "#step-roster > .note{margin-bottom:10px;}", "--flag-tint:#FBF3D9;"):
        assert rule in JOIN_CSS, rule
    # "Yes, continue to checkout" is the read-back's one primary: the gold
    # button rule, never the .alt outline beside it.
    assert '<button type="button" id="check-yes">' in JOIN


# --------------------------------------------------------------------- #
# thanks, 404, confirm
# --------------------------------------------------------------------- #

def test_the_thank_you_page_celebrates_once() -> None:
    """PAGES-THANKS-404-CONFIRM: the first screen after money changes hands
    drew its check and stopped. A gold ring bursts off it once, after the
    draw; the next steps stagger in on a phone, where they sit below the fold."""
    css = _style(_page("thanks.html"))
    assert ".done::before{" in css and "animation:burst .7s var(--ease-out) .95s 1 both;" in css
    assert '<div class="nextsteps" id="next-steps" data-reveal="group">' in _page("thanks.html")


_SHARE_HARNESS = r"""
const fn = __FN__;
const name = __NAME__;
async function run(nav) {
  const status = { textContent: "", dataset: {} };
  Object.defineProperty(globalThis, "navigator", { value: nav, configurable: true, writable: true });
  globalThis.window = { getSelection: () => ({ selectAllChildren() {} }) };
  globalThis[name](__TEXT__, {}, status);
  await new Promise((r) => setTimeout(r, 10));
  return { ok: status.dataset.ok, text: status.textContent };
}
(async () => {
  eval(fn + "\nglobalThis[name] = " + name + ";");
  const out = {
    copied: await run({ clipboard: { writeText: () => Promise.resolve() } }),
    refused: await run({ clipboard: { writeText: () => Promise.reject(new Error("no")) } }),
    byHand: await run({}),
    shared: await run({ share: () => Promise.resolve(), clipboard: { writeText: () => Promise.resolve() } }),
  };
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.parametrize("page,name", [("thanks.html", "shareWithFriend"),
                                       ("league-pass.html", "shareLine")])
def test_a_copy_is_marked_done_and_nothing_else_is(page: str, name: str) -> None:
    """The share's status line gets a check (and, on the League Pass page, the
    line flashes gold) only when the clipboard really took the text; a refused
    copy, a copy by hand and a share sheet all leave it unmarked. Run under
    node against the page's own function."""
    fn = _js_function(_page(page), name)
    got = _node(_SHARE_HARNESS.replace("__FN__", json.dumps(fn)).replace(
        "__NAME__", json.dumps(name)).replace("__TEXT__", json.dumps("hello")))
    assert got["copied"]["ok"] == "1" and got["copied"]["text"].startswith("Copied")
    assert got["refused"]["ok"] == "" and "selected" in got["refused"]["text"]
    assert got["byHand"]["ok"] == "" and "selected" in got["byHand"]["text"]
    assert got["shared"]["ok"] == "" and got["shared"]["text"] == ""


def test_the_404_fumbles_in_its_own_sheet_only() -> None:
    """The wobble lives in 404's own style, not the shared block, so the
    brand mark never wobbles anywhere else."""
    assert ".sitebar .brand svg.mark{animation:wobble" in _style(_page("404.html"))
    for name in OWNED:
        if name != "404.html":
            assert "wobble" not in _page(name), name


_CONFIRM_HARNESS = r"""
const code = __CODE__;
const els = {};
const el = (id) => els[id] || (els[id] = { id, textContent: "", className: "", disabled: false,
  handlers: {}, attrs: {}, addEventListener(t, f) { this.handlers[t] = f; },
  setAttribute(n, v) { this.attrs[n] = String(v); }, removeAttribute(n) { delete this.attrs[n]; } });
globalThis.document = { title: "", getElementById: el };
globalThis.location = { search: "?c=" + "a".repeat(24) };
globalThis.window = globalThis;
let settle;
const seen = {};
globalThis.fetch = () => { seen.during = { ...el("go").attrs }; seen.disabled = el("go").disabled;
  return new Promise((ok, no) => { settle = { ok, no }; }); };
eval(code);
(async () => {
  el("go").handlers.click();
  settle[__OUTCOME__](__OUTCOME__ === "ok" ? { ok: true } : new Error("offline"));
  await new Promise((r) => setTimeout(r, 10));
  console.log(JSON.stringify({ during: seen.during, disabledDuring: seen.disabled,
    after: el("go").attrs, disabledAfter: el("go").disabled }));
})();
"""


@pytest.mark.parametrize("outcome", ["ok", "no"])
def test_confirming_looks_busy_and_cannot_looks_different(outcome: str) -> None:
    """The confirm button went to opacity .55 while it posted — the same look
    as a link that cannot work, so "working" read as "broken". While the POST
    is in flight it is aria-busy (full strength, three pulsing dots); both
    endings clear it; the no-code state keeps the dimmed disabled look. Run
    under node with the page's own script and a fetch held open."""
    page = _page("join/confirm.html")
    code = re.search(r"<script>(.*?)</script>", page, re.S).group(1).replace(
        'const FORM_ENDPOINT = "";', 'const FORM_ENDPOINT = "https://w.test";')
    got = _node(_CONFIRM_HARNESS.replace("__CODE__", json.dumps(code)).replace(
        "__OUTCOME__", json.dumps(outcome)))
    assert got["during"] == {"aria-busy": "true"} and got["disabledDuring"] is True
    assert got["after"] == {}
    assert got["disabledAfter"] is (outcome == "ok")
    css = _style(page)
    assert 'button[aria-busy="true"]:disabled{opacity:1;}' in css
    assert "button:disabled{opacity:.55;cursor:default;}" in css


# --------------------------------------------------------------------- #
# League Pass, how it works, compare
# --------------------------------------------------------------------- #

def test_the_league_pass_price_never_moves_on_its_own() -> None:
    """PAGES-LEAGUEPASS: the price card's checks pop in once it is in view;
    the $69 itself carries no animation and the h1 never moves (only the gold
    slab's sheen sweeps across it)."""
    css = _style(_page("league-pass.html"))
    assert ".motion .price.in li::before{animation:okpop" in css
    assert not re.search(r"\.amt[^{]*\{[^}]*animation", css)
    assert not re.search(r"(?<![\w.-])h1\{[^}]*animation", css)
    assert "h1 em::after{" in css and "animation:slabsheen 1.1s var(--ease-out) .4s 1 both;" in css


def test_the_bars_fill_on_screen_only_and_the_width_stays_the_figure() -> None:
    """PAGES-HOW-COMPARE / REPORT-CHROME: the odds bars fill as they come into
    view — on screen only, only with motion allowed, only where view timelines
    exist, scaleX on top of the inline width (the published figure). The
    timeline is NAMED on the bar's track: the report's fill sits inside
    .cbar's overflow:hidden, a scroll container of its own, where an anonymous
    view() never advances, and on the 4-6px bar itself entry 20%-100% is a
    few pixels of scroll. Measured in Chrome: empty at the bottom edge, full
    about 100px up, and none under reduced motion."""
    for name, css in (("how", _style(_page("how-it-works.html"))), ("template", _style(TEMPLATE))):
        motion = "".join(_media(css, "screen and (prefers-reduced-motion:no-preference)"))
        assert "@supports (animation-timeline: view()){" in motion, name
        assert "view-timeline:--fillbar block;" in motion and "animation-timeline:--fillbar;" in motion
        assert "animation-timeline:view()" not in css, name
        assert _keyframes(css)["cfill"] == "from{transform:scaleX(0);}to{transform:none;}", name
        outside = css.replace(motion, "")
        assert "animation:cfill" not in outside, f"{name}: the fill escapes its media gate"


def test_the_comparison_table_keeps_its_names_and_says_it_scrolls() -> None:
    """PAGES-HOW-COMPARE: on a phone the 780px table sat in a 346px frame, cut
    mid-word at the edge with nothing saying it scrolls. At 820px and under the
    product names stick (narrow, wrapping), and a shadow on the right edge —
    a cover riding the content, a shadow staying put — shows until the end."""
    css = _style(_page("compare/index.html"))
    sticky = "".join(_media(css, "(max-width:820px)"))
    assert "td:first-child,th:first-child{position:sticky;left:0;z-index:1;}" in sticky
    assert "th:first-child{background:var(--navy);}" in sticky
    assert re.search(r"\.tablewrap\{[^}]*no-repeat local,[^}]*no-repeat scroll,", css)
    assert '<div class="pick" data-reveal="group">' in _page("compare/index.html")
    # Review SLEEK-9, measured at 390: even with the names stuck, 780px of
    # table in a 346px window left two of four columns off-screen and every
    # row ~170px tall. At 600px and under each product is a card, its
    # column names written in.
    phone = "".join(_media(css, "(max-width:600px)"))
    assert "table,tbody,tr,td{display:block;}" in phone and "table{min-width:0;}" in phone
    assert "tr:first-child{display:none;}" in phone
    for n, label in ((2, "Price"), (3, "Best at"), (4, "Falls short")):
        assert f'td:nth-child({n})::before{{content:"{label}";}}' in phone
    header = re.search(r"<tr>(<th>.*?)</tr>", _page("compare/index.html")).group(1)
    assert re.findall(r"<th>([^<]+)</th>", header)[1:] == ["Price", "Best at", "Falls short"]


# --------------------------------------------------------------------- #
# REPORT-CHROME — the game plan ticks for real
# --------------------------------------------------------------------- #

def test_the_game_plan_is_a_checklist_you_can_tick() -> None:
    """Every surface promises "tick the boxes on a short checklist", and in the
    browser report .task .box was an empty div. Each task is now a label around
    a real checkbox, so the whole card is the target and the task's own words
    are its accessible name; spans, because a label holds phrasing content
    only. Nothing is stored: no id, no name, no script — a tick lasts until the
    page reloads. The words are unchanged (mutation: a div inside the label)."""
    html = rr.section_checklist([
        {"action": "Bench A — B starts at FLEX", "detail": "A projects 9.5, B 10.3.",
         "deadline": "before this week's first kickoff", "urgency": "now"},
        {"action": "Sunday morning: check B's status", "deadline": "gameday morning"}])
    tasks = re.findall(r'<label class="task">(.*?)</label>', html, re.S)
    assert len(tasks) == 2
    for task in tasks:
        assert task.startswith('<input type="checkbox" class="box"><span class="tbody">')
        assert "<div" not in task and "id=" not in task and "name=" not in task
    assert '<span class="dl ok">before this week&#x27;s first kickoff</span>' in tasks[0]
    assert '<span class="why">' not in tasks[1]
    visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    assert "Bench A — B starts at FLEX A projects 9.5, B 10.3." in visible


def test_the_checkbox_draws_in_the_templates_own_style_at_a_thumbs_size() -> None:
    """The box keeps the template's navy square and turns turf when ticked,
    with the task struck through; it is 24px (the probe flagged the 20px box
    under WCAG 2.5.8) with the report's navy focus ring; the email draws its
    own boxes and is untouched."""
    css = _style(TEMPLATE)
    assert ".task .box{-webkit-appearance:none;appearance:none;width:24px;height:24px;" in css
    assert ".task .box:checked{background:var(--turf);border-color:var(--turf);}" in css
    assert ".task:has(.box:checked) .do{text-decoration:line-through;" in css
    assert ".task .box:focus-visible{outline:3px solid var(--navy);outline-offset:2px;}" in css
    assert ".task .do,.task .why,.task .dl{display:block;}" in css
    email = (ROOT / "render" / "email.py").read_text(encoding="utf-8")
    assert "<input" not in email


def test_the_report_has_one_depth_and_the_ctas_feel_like_the_sites() -> None:
    """REPORT-CHROME: one depth. Moved with the card stack (contract C7, Oct
    2026): the page is paper edge to edge at every width (no framed sheet on
    a grey desk), each CARD takes the paper pages' elevation, nothing inside
    a card casts a shadow of its own, and the samples' gold CTA is the site's
    flat button — it lifts on hover, with no sheen and no clip."""
    css = _style(TEMPLATE)
    assert re.search(r"body\{background:var\(--paper\);", css)
    assert not re.search(r"\.report\{[^}]*(box-shadow|border:)", css)
    card = re.search(r"\n  \.card\{([^}]*)\}", css).group(1)
    assert ("box-shadow:0 1px 2px rgba(16,30,51,.06),0 8px 24px -12px rgba(16,30,51,.18)"
            in card) and "border-radius:12px" in card and "border:1px solid" in card
    for inner in (".task{", ".pivot{", ".frow,.ghead{"):
        rule = css.split("\n  " + inner, 1)[1].split("}", 1)[0]
        assert "box-shadow" not in rule, inner
    assert re.search(r"\.btn:hover\{background:#FFD24A;transform:translateY\(-1px\);\}", css)
    assert "::after{content" not in css.split(".btn{", 1)[1].split("@media print", 1)[0]
    assert "clip-path:polygon" not in css
