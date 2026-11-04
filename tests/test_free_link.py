"""The free report, once a purchase can finish (Nov 4 2026).

With checkout open the landing hero showed a gold "Get my lineups", a ghost
"Try it free on your roster", "or read a real report first" and a refund line:
against the owner's Oct 31 2026 rule of one action and one link. Once a
purchase can finish the hero keeps one action, and the free report sits one
scroll down, as a quiet link under the price card (outside it: the card never
changes) and in the closer. The app pages offer it the bye planner's way: paid
first, free as a text link beneath. The Menu's gold first item says the ask in
today's words, and the price line says "lands today" once.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import render.platforms as platforms
import render.report as rr
from test_site import LANDING

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# The landing's flags and the code that acts on them before closeForSeason.
_HEAD = LANDING.split("const CHECKOUT_OPEN = ", 1)[1].split("\nfunction closeForSeason(line) {")[0]
_CLOSE = ("function closeForSeason(line) {"
          + LANDING.split("function closeForSeason(line) {")[1].split("\n}\n")[0] + "\n}")

# A small stand-in DOM: every id or selector is one node, made on first ask,
# and a node placed after another is recorded beside it.
_DOM = r"""
const made = {};
const placed = [];
function node(key) {
  const n = { key, id: "", hidden: false, textContent: "", className: "", href: "", attrs: {}, style: {},
    children: [],
    classList: { set: new Set(), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); },
                 contains(c) { return this.set.has(c); } },
    setAttribute(k, v) { this.attrs[k] = v; if (k === "href") this.href = v; },
    getAttribute(k) { return k === "href" ? this.href : this.attrs[k]; },
    appendChild(kid) { this.children.push(kid); return kid; },
    append(...kids) { this.children.push(...kids); },
    replaceChildren(...kids) { this.children = kids; this.textContent = ""; },
    replaceWith(other) { made[key] = other; },
    after(other) { placed.push([key, other]); },
    remove() { this.removed = true; },
    cloneNode() { return node(key); },
    addEventListener() {},
    querySelectorAll() { return []; },
    get parentNode() { return node(key + ":parent"); },
  };
  return n;
}
function get(key) { return made[key] || (made[key] = node(key)); }
globalThis.window = globalThis;
window.matchMedia = () => ({ matches: false });
globalThis.location = { search: "" };
globalThis.document = {
  getElementById: (id) => (placed.find(([, n]) => n.id === id) || [])[1] || get("#" + id),
  querySelector: (sel) => get(sel),
  querySelectorAll: () => [],
  createElement: () => node("new"),
  createTextNode: (t) => ({ textContent: t }),
};
get("#try-cta").hidden = true;
get(".sitemenu-list a.go").textContent = "Check my team free";
const VIA = undefined;
function carryVia(h) { return h; }
"""


def _run(open_: bool, can: bool, trial: bool, over: bool = False) -> dict:
    head = (_HEAD.replace("const CHECKOUT_CAN_COMPLETE = true;",
                          f"const CHECKOUT_CAN_COMPLETE = {str(can).lower()};")
            .replace("const TRIAL_OPEN = true;", f"const TRIAL_OPEN = {str(trial).lower()};"))
    assert head.startswith("true;") or head.startswith("false;"), "the landing's flag moved"
    script = (_DOM + "const CHECKOUT_OPEN = " + str(open_).lower() + head.split(";", 1)[1]
              + "\n" + _CLOSE + "\n" + ("closeForSeason('over');\n" if over else "") + r"""
const free = placed.filter(([, n]) => /^try-/.test(n.id)).map(([where, n]) => ({
  where, id: n.id, cls: n.className, hidden: n.hidden,
  href: n.children[0] && n.children[0].href, text: n.children[0] && n.children[0].textContent }));
const menu = get(".sitemenu-list a.go");
console.log(JSON.stringify({ tryCta: get("#try-cta").hidden, free,
  hidden: Object.fromEntries(["try-price"].map((k) => [k,
    document.getElementById(k).hidden])),
  menu: menu.textContent, menuHref: menu.href,
  sample: get("#hero-sample").textContent }));
""")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_once_a_purchase_can_finish_the_hero_keeps_one_action() -> None:
    """Mutation: put back `if (TRIAL_OPEN) {` on the hero's block and the
    ghost button is shown beside the gold one again."""
    got = _run(open_=True, can=True, trial=True)
    assert got["tryCta"] is True, "the hero shows a second button"
    assert got["sample"] != "or read a real report first"
    # Before a purchase can finish, the free report is still the hero's
    # second button (the interim state), and nothing else offers it.
    interim = _run(open_=True, can=False, trial=True)
    assert interim["tryCta"] is False and interim["free"] == []


@needs_node
def test_the_free_report_sits_under_the_price_card() -> None:
    """One quiet text link outside the price card, to join/?try=1, and only
    while TRIAL_OPEN and a purchase can finish. Not in the closer as well
    (review, Nov 4 2026): its row already holds the ask, and the second copy
    put more words on the open page than the hero button it replaced.
    Mutation: drop the TRIAL_OPEN check and the closed-trial case fails."""
    got = _run(open_=True, can=True, trial=True)
    assert got["free"] == [
        {"where": "#pricing .plans", "id": "try-price", "cls": "freetool", "hidden": False,
         "href": "join/index.html?try=1", "text": "Try it free on your roster"}]
    assert _run(open_=True, can=True, trial=False)["free"] == []
    assert _run(open_=False, can=False, trial=True)["free"] == []


@needs_node
def test_a_season_that_is_over_takes_the_free_links_and_the_menus_ask_with_it() -> None:
    got = _run(open_=True, can=True, trial=True, over=True)
    assert got["hidden"] == {"try-price": True}
    assert got["menuHref"] == "#watch-form" and got["menu"] == "Notify me"


@needs_node
def test_the_menus_first_item_says_the_landings_ask() -> None:
    """The nav, hero, sticky bar and closer said "Get my lineups" while the
    Menu's gold first item still said "Check my team free". Mutation: drop the
    relabel and the open case fails."""
    assert _run(open_=True, can=True, trial=True)["menu"] == "Get my lineups"
    assert _run(open_=False, can=False, trial=False)["menu"] == "Check my team free"


def test_the_static_landing_carries_neither_free_link() -> None:
    """Fail closed: if no script runs, nothing offers a free report, and the
    hero's button keeps its id for the interim state."""
    static = LANDING.split("<script>")[0]
    assert re.search(r'id="try-cta" hidden', static)
    assert 'id="try-price"' not in static and "try-closer" not in LANDING
    assert '"pass-clock", "try-price"]' in _CLOSE


def test_a_live_week_opens_this_weeks_report_from_the_hero_again() -> None:
    """The hero's one link swapped to this week's report only while the free
    report was closed: with it open the swap never ran."""
    swap = LANDING.split('const heroLink = document.getElementById("hero-sample");')[1]
    swap = swap.split("}")[0]
    assert swap.strip().startswith("if (heroLink) {") and "TRIAL_OPEN" not in swap


def test_the_menu_bakes_in_todays_ask(monkeypatch) -> None:
    monkeypatch.setattr(rr, "checkout_open", lambda: True)
    assert f'class="go" href="join/index.html">{rr.SAMPLE_CTA}</a>' in rr.site_menu()
    monkeypatch.setattr(rr, "checkout_open", lambda: False)
    assert f'class="go" href="join/index.html">{rr.CHECK_LABEL}</a>' in rr.site_menu()
    # The footer's Free tools keep the roster check, whatever checkout says.
    assert f'<a href="join/index.html">{rr.CHECK_FOOT_LABEL}</a>' in rr.site_footer()


def test_the_landings_flags_are_read_strictly(tmp_path) -> None:
    page = tmp_path / "index.html"
    for text, want in (("const TRIAL_OPEN = true;\nconst CHECKOUT_OPEN = true;\n"
                        "const CHECKOUT_CAN_COMPLETE = true;\n", True),
                       ("const TRIAL_OPEN = true;\nconst CHECKOUT_OPEN = true;\n"
                        "const CHECKOUT_CAN_COMPLETE = false;\n", False),
                       ("const TRIAL_OPEN = false;\nconst CHECKOUT_OPEN = true;\n"
                        "const CHECKOUT_CAN_COMPLETE = true;\n", False),
                       ("const TRIAL_OPEN = true;\nconst TRIAL_OPEN = true;\n"
                        "const CHECKOUT_OPEN = true;\nconst CHECKOUT_CAN_COMPLETE = true;\n", False),
                       ("// const TRIAL_OPEN = true;\nconst CHECKOUT_OPEN = true;\n"
                        "const CHECKOUT_CAN_COMPLETE = true;\n", False)):
        page.write_text(text)
        assert rr.trial_link_open(page) is want, text
    assert rr.trial_link_open(tmp_path / "missing.html") is False


@pytest.mark.parametrize("platform", [*platforms.PLATFORMS, platforms.DYNASTY],
                         ids=lambda p: p.slug)
def test_an_app_page_offers_the_free_report_beneath_its_paid_ask(platform, monkeypatch) -> None:
    """The bye planner's pattern: paid first, the free report as a quieter
    text link under it, on the app's own lineup. Never while the landing's
    free report or checkout is closed. Mutation: make _try ignore
    trial_link_open and the closed case fails."""
    build = platforms.dynasty_page if platform is platforms.DYNASTY else \
        (lambda: platforms.page(platform))
    monkeypatch.setattr(platforms, "trial_link_open", lambda: True)
    page = build()
    header = page.split("<header>", 1)[1].split("</header>", 1)[0]
    href = platforms.join_href(platform)
    want = href + ("&amp;" if "?" in href else "?") + "try=1"
    link = f'<p class="free" data-free-try><a href="{want}">{rr.TRIAL_LINK_LABEL}</a></p>'
    assert page.count("try=1") == 1 and link in header
    assert header.index('class="btn gold"') < header.index(link)
    monkeypatch.setattr(platforms, "trial_link_open", lambda: False)
    assert "try=1" not in build()


def test_the_published_app_pages_follow_todays_flags() -> None:
    for path, text in platforms.build().items():
        assert path.read_text(encoding="utf-8") == text, f"{path} is stale"
        assert ("try=1" in text) is rr.trial_link_open(), path


# --------------------------------------------------------------------- #
# Review fixes (Nov 4 2026)
# --------------------------------------------------------------------- #

_CARRY = ("function carryVia(href, via) {"
          + LANDING.split("function carryVia(href, via) {", 1)[1].split("\n}\n")[0] + "\n}\n")
_VIA_PASS = ("if (VIA) {" + LANDING.split("// AFTER every href this script writes", 1)[1]
             .split("if (VIA) {", 1)[1].split("\n}\n")[0] + "\n}\n")


@needs_node
def test_the_free_link_carries_the_channel_tag() -> None:
    """The link carries ?via= only because it is built above the page's one
    VIA pass. Run with a tag and the real carryVia; and the construction must
    stay above that pass. Mutation: move the tryLink block below the pass and
    the position check fails; skip the pass and the href check fails."""
    assert LANDING.index('tryLink("try-price")') < LANDING.index(
        "// AFTER every href this script writes")
    assert LANDING.count('tryLink("') == 1, "one free link on the open page"
    dom = _DOM.replace('const VIA = undefined;\nfunction carryVia(h) { return h; }\n',
                       'const VIA = "reddit-x";\n' + _CARRY)
    assert dom != _DOM, "the stand-in's VIA lines moved"
    script = (dom + r"""
document.querySelectorAll = (sel) => sel === "a[href]"
  ? placed.flatMap(([, n]) => n.children) : [];
""" + "const CHECKOUT_OPEN = " + _HEAD + "\n" + _VIA_PASS + r"""
const link = placed.find(([, n]) => n.id === "try-price")[1].children[0];
console.log(JSON.stringify(link.href));
""")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == "join/index.html?try=1&via=reddit-x"


@needs_node
def test_beside_the_free_button_this_weeks_link_stays_the_lesser_one() -> None:
    """Interim state (TRIAL_OPEN, a purchase not completing): the hero shows
    the ghost try button and "or read a real report first", stacked. The
    live-week swap renamed it "See this week's report" and dropped the "or".
    Mutation: drop the stacked check and the interim case fails."""
    clock = LANDING.split("// The season clock.")[1]
    iife = clock[clock.index("(function () {"):clock.index("})();") + 5]
    harness = r"""
const make = (id, stacked) => ({ id, hidden: true, textContent: "", attrs: {},
  classList: { contains: (c) => c === "stacked" && stacked },
  setAttribute(k, v) { this.attrs[k] = v; }, replaceChildren() {}, appendChild() {} });
function run(stacked) {
  const els = { "season-clock": make("season-clock"), "hero-sample": make("hero-sample", stacked) };
  global.document = { getElementById: (id) => els[id] || null, querySelectorAll: () => [],
    createElement: () => make("x"), createTextNode: (t) => ({ t }) };
  global.window = { fetch: true, AbortSignal: null };
  global.fetch = () => Promise.resolve({ ok: true, json: () => ({ season: "2026", week: 7,
    last_week: 18, lands_on: "2999-01-05", week_ends: "2999-01-04", odds: 3,
    built_at: "2026-10-20T17:15:45+00:00", closest_call: true, cards: true,
    first_kickoff: "2999-01-01T00:15:00Z" }) });
  global.closeForSeason = () => {}; global.showPlayoffPass = () => {};
  global.PLAYOFF_PASS_READY = false; global.PLAYOFF_FROM_WEEK = 13;
  global.TRIAL_OPEN = true; global.VIA = undefined; global.carryVia = (href) => href;
  IIFE
  return new Promise((r) => setTimeout(() => r(els["hero-sample"].textContent), 50));
}
(async () => console.log(JSON.stringify([await run(false), await run(true)])))();
""".replace("IIFE", iife)
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    alone, stacked = json.loads(out.stdout)
    assert alone == "See this week's report"
    assert stacked == "or read this week's report first"


_FOOTER_MENU = r"""
const fs = require("fs");
const [src, clockJson, now, href, landing] = process.argv.slice(1);
const ask = { attrs: { href }, textContent: "Get my lineups",
  getAttribute(k) { return this.attrs[k]; }, setAttribute(k, v) { this.attrs[k] = v; } };
const free = { hidden: false };
global.document = {
  querySelectorAll: (sel) => sel === ".sitemenu-list a.go" ? [ask]
    : sel === "[data-free-try]" ? [free] : [],
  getElementById: (id) => (id === "watch-form" && landing === "1" ? {} : null),
};
global.window = { fetch: true };
const RealDate = Date;
const at = RealDate.parse(now);
global.Date = class extends RealDate {
  constructor(...a) { super(...(a.length ? a : [at])); }
  static now() { return at; }
};
global.fetch = () => Promise.resolve({ ok: true, json: () => JSON.parse(clockJson) });
eval(fs.readFileSync(src, "utf8"));
setTimeout(() => process.stdout.write(JSON.stringify(
  { text: ask.textContent, href: ask.attrs.href, free: !free.hidden })), 20);
"""


def _footer_menu(clock: dict, now: str, href: str = "../join/index.html",
                 landing: bool = False) -> dict:
    done = subprocess.run(["node", "-e", _FOOTER_MENU, str(SITE / "footer.js"),
                           json.dumps(clock), now, href, "1" if landing else "0"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_a_closed_season_takes_the_menus_ask_and_the_free_link_on_every_page() -> None:
    """Review, Nov 4 2026, reproduced with phase "over": how-it-works'
    buttons said "Tell me when it opens" while its Menu still said "Get my
    lineups", and the app pages kept "Try it free on your roster" with no
    season left. site/footer.js, on every footed page, now closes both by
    how-it-works' own rule (over, or the last week from its first kickoff),
    keeps a ?via= tag, and leaves the landing (which has #watch-form) to its
    own closeForSeason. Mutations: make seasonClosed return false, or drop
    the #watch-form skip, and this fails."""
    mid = {"season": "2026", "week": 9, "last_week": 18, "lands_on": "2026-11-04",
           "week_ends": "2026-11-09", "phase": "season",
           "first_kickoff": "2026-11-06T01:15:00Z"}
    now = "2026-11-04T15:00:00Z"
    still = {"text": "Get my lineups", "href": "../join/index.html", "free": True}
    closed = {"text": "Tell me when it opens", "href": "../index.html#watch-form", "free": False}
    assert _footer_menu(mid, now) == still
    assert _footer_menu({**mid, "phase": "over"}, now) == closed
    last = {**mid, "week": 18, "lands_on": "2027-01-06", "first_kickoff": "2027-01-09T18:00:00Z"}
    assert _footer_menu(last, "2027-01-06T15:00:00Z") == still, "closed before last kickoff"
    assert _footer_menu(last, "2027-01-09T18:30:00Z") == closed, "open after last kickoff"
    assert _footer_menu({**last, "first_kickoff": ""}, "2027-01-07T15:00:00Z") == closed, \
        "a last week past its report day is over"
    assert _footer_menu({**mid, "phase": "preseason"}, now) == still
    tagged = _footer_menu({**mid, "phase": "over"}, now,
                          href="../join/index.html?t=std&via=reddit-x")
    assert tagged["href"] == "../index.html?via=reddit-x#watch-form"
    root = _footer_menu({**mid, "phase": "over"}, now, href="join/index.html")
    assert root["href"] == "index.html#watch-form"
    landing = _footer_menu({**mid, "phase": "over"}, now, href="join/index.html", landing=True)
    assert landing == {"text": "Get my lineups", "href": "join/index.html", "free": False}


def test_every_footed_page_carries_the_current_footer_script() -> None:
    """footer.js is versioned by digest, so a change to it reaches a page only
    when that page carries the new digest (regenerated or re-pasted)."""
    import hashlib
    digest = hashlib.sha256((SITE / "footer.js").read_bytes()).hexdigest()[:10]
    for page in SITE.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for got in re.findall(r"/footer\.js\?v=([0-9a-f]+)", text):
            assert got == digest, f"{page.relative_to(SITE)} carries a stale footer.js"
