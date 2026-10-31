"""Finding things on the site (owner review, Oct 30 2026).

The owner's words: "The join page isn't so obvious when it might seem like a
major feature. Same with the 'byes' page." Audited in Chrome: the join page was
three clicks from home on any device, through an app page's "the roster box",
because every main button pointed at an email box while checkout was closed;
the four app pages were two clicks away, behind How it works.

So the roster check is the site's main action, closed or open; every selling
page carries one footer map; and a phone's "Menu" holds what the bar has no room
for. These tests hold that in place. The bar's own pins are in
tests/test_prelaunch_pages.py and tests/test_prelaunch_landing.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import render.report as rr
from test_site import LANDING, _style, markup_only

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BODY = LANDING.split("<body", 1)[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# Every selling page: (page, the prefix back to the site root). terms.html and
# privacy.html are not here: their visible text is pinned to their dates
# (tests/test_promises_legal.py), so the map joins them with their next change.
FOOTED = {
    "index.html": "", "how-it-works.html": "", "league-pass.html": "", "thanks.html": "",
    "sample-report.html": "", "sample-first-week.html": "", "this-week.html": "",
    "404.html": "/", "join/index.html": "../", "byes/index.html": "../",
    "espn/index.html": "../", "yahoo/index.html": "../", "sleeper/index.html": "../",
    "cbs/index.html": "../",
}
# Their next step, closed or open, goes to join/ under the site's label.
NEXT_STEP = ("how-it-works.html", "sample-report.html", "sample-first-week.html",
             "this-week.html", "espn/index.html", "yahoo/index.html", "sleeper/index.html",
             "cbs/index.html", "byes/index.html")


def _page(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name,prefix", FOOTED.items())
def test_every_selling_page_carries_the_one_footer_map(name: str, prefix: str) -> None:
    """One drawing, pasted verbatim (mutation: edit one route on one page). It
    sits inside the page's own footer, above that page's legal line, and every
    route on it is a page that exists."""
    page = _page(name)
    block = rr.site_footer(prefix)
    assert block in page, f"{name}: the footer map drifted from render.report.site_footer"
    assert rr.SITE_FOOTER_CSS in _style(page), f"{name}: its footer CSS drifted"
    footer = page.split("<footer", 1)[1].split("</footer>", 1)[0]
    assert block in footer, f"{name}: the map is outside the footer"
    words = re.sub(r"<[^>]+>", " ", footer.replace(block, ""))
    assert "Beat Your League" in words and "CC-BY-4.0" in words, name
    assert "betting picks" in words, f"{name}: the footer lost its legal line"


def test_the_map_names_the_sites_routes_and_they_exist() -> None:
    block = rr.site_footer()
    heads = re.findall(r"<p>([^<]+)</p>", block)
    assert heads == ["Product", "Free tools", "Your app", "About"]
    labels = [label for _href, label in re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', block)]
    assert labels == ["How it works", "Sample report", "This week&#x27;s report", "League Pass",
                      "Check my team", "Bye planner", "ESPN", "Yahoo", "Sleeper", "CBS",
                      "Terms &amp; refunds", "Privacy", "Contact"]
    for href in re.findall(r'<a href="([^"]+)"', block):
        if href.startswith("mailto:"):
            continue
        target = SITE / href
        assert (target / "index.html" if href.endswith("/") else target).is_file(), href


def test_the_map_links_this_weeks_report_only_under_the_heros_rule() -> None:
    """Launch review PC-01: every link to this-week.html waits for the hero's
    rule. Most footed pages have no script of their own to apply it, so the map
    brings a small one, versioned by digest like the site's other scripts."""
    block = rr.site_footer()
    assert re.search(r'<a href="this-week\.html" data-live-week hidden>', block)
    script = (SITE / "footer.js").read_text(encoding="utf-8")
    assert re.search(r"w\.odds >= 3 && w\.closest_call && w\.cards === true", script)
    assert '(w.phase || "season") !== "season"' in script and "today > w.lands_on" in script
    digest = hashlib.sha256((SITE / "footer.js").read_bytes()).hexdigest()[:10]
    assert f'<script src="/footer.js?v={digest}" defer></script>' in block
    assert "footer .footmap a[hidden]{display:none;}" in rr.SITE_FOOTER_CSS, \
        "a block link ignores [hidden] without this rule"


def test_a_subscribers_own_report_carries_no_site_furniture() -> None:
    """A paying reader's report is not a selling page."""
    assert "footmap" not in rr.footer({"season": "2026", "week": 9})
    assert "footmap" in rr.footer({"season": "2024", "week": 10, "anonymized_demo": True})


def test_the_roster_check_is_the_main_action_with_checkout_closed() -> None:
    """The closed landing's gold buttons, hero to sticky bar, pointed at an
    email box, so visitors never reached the best thing on the site. They go
    to the roster check now: the static page is the closed state, and it must
    be true if no script runs. The price card keeps "Tell me when it opens":
    that is where somebody is deciding to buy, and it is one decision."""
    static = LANDING.split("<script>")[0]
    for cta in ("nav-cta", "hero-open", "closer-cta", "sticky-cta"):
        assert re.search(rf'<a class="btn gold" id="{cta}" href="join/index\.html">'
                         r"Check my team free</a>", static), cta
    card = static.split('id="pass-card"')[1].split('<p class="finance"')[0]
    assert re.search(r'id="season-cta" href="#watch-form"[^>]*>Tell me when it opens</a>', card)
    assert "Check my team" not in card, "two decisions on the price card"
    # The closer says what the button does; "free" on the button says the rest.
    assert '<p id="closer-note">Paste your roster. See the calls on your team in seconds.</p>' \
        in static
    # Open, every one of them turns into the buy label on the same page.
    opened = LANDING.split("if (CHECKOUT_OPEN) {", 1)[1].split("if (CHECKOUT_CAN_COMPLETE)")[0]
    assert 'heroOpen.textContent = "Get my lineups";' in opened
    for cta in ("nav-cta", "sticky-cta", "closer-cta"):
        assert f'"{cta}"' in opened


def test_the_email_capture_sits_in_the_closer_for_whoever_is_not_ready() -> None:
    """Every "#watch-form" link on the site still lands in a real form: the
    hero gave it up, and the closer took it, under a real label."""
    closer = BODY.split('<section class="closer">')[1].split("</section>")[0]
    assert re.search(r'<form class="watchform" id="watch-form" novalidate>', closer)
    assert re.search(r'<label for="watch-email" id="watch-label">Not ready\?', closer)
    assert 'id="watch-note"' in closer and 'id="closer-cta"' in closer
    assert closer.index('id="closer-cta"') < closer.index('id="watch-form"')
    assert LANDING.count('id="watch-form"') == 1
    # One gold button at the closer; the form's is the second choice.
    assert '<button class="btn ghost" type="submit">Tell me when it opens</button>' in closer


def test_the_apps_and_the_planner_have_a_visible_home_on_the_landing() -> None:
    hero = BODY.split('<header class="hero">')[1].split("</header>")[0]
    creds = re.search(r'<ul class="creds".*?</ul>', hero, re.S).group(0)
    for slug, name in (("espn", "ESPN"), ("yahoo", "Yahoo"), ("sleeper", "Sleeper"), ("cbs", "CBS")):
        assert f'<a href="{slug}/">{name}</a>' in creds, name
    # A standing line, gated with the callout: no byes left, no planner.
    pricing = BODY.split('<section id="pricing">')[1].split("</section>")[0]
    assert re.search(r'<p class="freetool" data-planner>Free: the <a href="byes/">bye planner</a>',
                     pricing), "the planner line sits under the price, never before it"


@pytest.mark.parametrize("name", NEXT_STEP)
def test_every_proof_and_tool_page_ends_with_the_same_next_step(name: str) -> None:
    """The label on every page that leads to join/ is the same, closed."""
    page = markup_only(_page(name))
    main = page.split("<footer", 1)[0]
    assert re.search(r'<a class="(?:btn gold|golink)"[^>]*href="(?:\.\./)?join/index\.html'
                     r'(?:\?t=[a-z0-9-]+)?"[^>]*>Check my team free</a>', main), name


@pytest.mark.parametrize("name", NEXT_STEP + ("index.html",))
def test_no_page_calls_the_closed_ask_by_an_old_name(name: str) -> None:
    page = markup_only(_page(name))
    assert "Get this for your team" not in page


def test_the_planners_next_step_carries_the_roster_it_checked() -> None:
    """Closed, the planner hands the roster over: join/ restores a ?ref=, and
    typing fifteen names twice is how a visitor is lost."""
    page = _page("byes/index.html")
    closed = page.split("function drawCta() {")[1].split("\n}\n")[0]
    assert 'carryVia("../join/index.html" + (ref ? "?ref=" + ref : ""), VIA)' in closed
    assert '$("cta-check").remove();' in page, "the open state keeps two buttons"


LANDING_CLOSE = r"""
const el = (id) => ({ id, hidden: false, textContent: "", attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, querySelectorAll: () => [] });
const els = {};
for (const id of %(ids)s) els[id] = el(id);
globalThis.document = { getElementById: (id) => els[id] || null,
  querySelector: () => null };
const VIA = undefined;
let closedState = null, watchDoneTail = "";
function carryVia(h) { return h; }
%(fn)s
closeForSeason("The 2026 season's last report has gone out.");
console.log(JSON.stringify(els));
"""


@needs_node
def test_a_season_that_is_over_sends_the_main_buttons_to_the_capture() -> None:
    """With nothing left to check a roster against, "Check my team" would land
    on a page saying the season is over. Run for real, closed: the buttons go
    to the form and say so, and the promise of a free check goes with them."""
    fn = "function closeForSeason(line) {" + \
        LANDING.split("function closeForSeason(line) {")[1].split("\n}\n")[0] + "\n}"
    ids = ["hero-open", "nav-cta", "sticky-cta", "closer-cta", "try-cta", "risk-line",
           "closer-note", "season-clock", "watch-label"]
    script = LANDING_CLOSE % {"ids": json.dumps(ids), "fn": fn}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    for cta, label in (("hero-open", "Tell me when it opens"), ("sticky-cta", "Tell me when it opens"),
                       ("nav-cta", "Notify me")):
        assert got[cta]["attrs"]["href"] == "#watch-form" and got[cta]["textContent"] == label
        assert got[cta]["hidden"] is False
    assert got["closer-cta"]["hidden"]
    assert got["season-clock"]["textContent"].endswith("last report has gone out.")
    assert "checkout opens" in got["closer-note"]["textContent"]
    assert "Not ready" not in got["watch-label"]["textContent"]
