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
  hidden: Object.fromEntries(["try-price", "try-closer"].map((k) => [k,
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
def test_the_free_report_sits_under_the_price_card_and_in_the_closer() -> None:
    """One quiet text link outside the price card, one in the closer, both to
    join/?try=1, and only while TRIAL_OPEN and a purchase can finish.
    Mutation: drop the TRIAL_OPEN check and the closed-trial case fails."""
    got = _run(open_=True, can=True, trial=True)
    assert got["free"] == [
        {"where": "#pricing .plans", "id": "try-price", "cls": "freetool", "hidden": False,
         "href": "join/index.html?try=1", "text": "Try it free on your roster"},
        {"where": ".closer .cta-row", "id": "try-closer", "cls": "freetool", "hidden": False,
         "href": "join/index.html?try=1", "text": "Try it free on your roster"}]
    assert _run(open_=True, can=True, trial=False)["free"] == []
    assert _run(open_=False, can=False, trial=True)["free"] == []


@needs_node
def test_a_season_that_is_over_takes_the_free_links_and_the_menus_ask_with_it() -> None:
    got = _run(open_=True, can=True, trial=True, over=True)
    assert got["hidden"] == {"try-price": True, "try-closer": True}
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
    assert 'id="try-price"' not in static and 'id="try-closer"' not in static
    assert '"try-price", "try-closer"' in _CLOSE


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
    link = f'<p class="free"><a href="{want}">{rr.TRIAL_LINK_LABEL}</a></p>'
    assert page.count("try=1") == 1 and link in header
    assert header.index('class="btn gold"') < header.index(link)
    monkeypatch.setattr(platforms, "trial_link_open", lambda: False)
    assert "try=1" not in build()


def test_the_published_app_pages_follow_todays_flags() -> None:
    for path, text in platforms.build().items():
        assert path.read_text(encoding="utf-8") == text, f"{path} is stale"
        assert ("try=1" in text) is rr.trial_link_open(), path
