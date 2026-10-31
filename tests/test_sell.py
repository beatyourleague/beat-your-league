"""The sell pass (owner brief, Oct 30 2026): a price card that reads like a good
deal in five seconds, and every value line on it literally true.

What these hold:
- no page counts the weeks or lineups left: the card and the buy page say the
  same words all season (owner decision, Oct 31 2026);
- the $49 2027 Season Pass is built switched off: no word of it renders while
  the flag is false, and with the flag on its renewal terms sit under the price;
- the money rule: a price is stated, never broken down, on any page;
- no hype on a selling page (the owner's "don't be cheesy", as a sweep).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from render.report import ONCE_END, ONCE_SEAT_END, season_end_lines

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
THANKS = (SITE / "thanks.html").read_text(encoding="utf-8")
LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _fn(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    return page[start:page.index("\n}\n", start) + 2]


def _node(script: str) -> object:
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60,
                          env={**os.environ, "TZ": "America/New_York"})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _markup(page: str) -> str:
    """What is rendered with no script: no scripts, styles or comments."""
    return re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", "", page, flags=re.S)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


# --------------------------------------------------------------------- #
# the value line
# --------------------------------------------------------------------- #

def _clock(week: dict, now: str, open_: bool) -> dict:
    iife = LANDING.split("// The season clock.")[1]
    iife = iife[iife.index("(function () {"):iife.index("})();") + 5]
    start = {"season-clock": "A new report every Tuesday of the season.",
             "pass-clock": "A new lineup decided every Tuesday.", "hero-open": "", "closer-cta": "",
             "sticky-cta": "", "this-week-label": ""}
    script = """
const FIXED = Date.parse(%(now)s);
const RealDate = Date;
class FakeDate extends RealDate {
  constructor(...a) { if (a.length === 0) super(FIXED); else super(...a); }
  static now() { return FIXED; }
}
FakeDate.parse = RealDate.parse; FakeDate.UTC = RealDate.UTC;
globalThis.Date = FakeDate;
const els = {};
function node(text) { return { textContent: text, hidden: false, className: "",
  replaceChildren(...kids) { this.textContent = kids.map((k) => k.textContent).join(""); },
  appendChild(kid) { this.textContent += kid.textContent; } }; }
for (const [id, text] of Object.entries(%(start)s)) els[id] = node(text);
globalThis.window = globalThis;
globalThis.document = { getElementById: (id) => els[id] || null, querySelectorAll: () => [],
  createElement: () => node(""), createTextNode: (t) => node(t) };
const W = %(week)s;
window.fetch = globalThis.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(W) });
const CHECKOUT_OPEN = %(open)s, PLAYOFF_PASS_READY = false, PLAYOFF_FROM_WEEK = 13;
let closed = null;
function closeForSeason(line) { closed = line; }
function showPlayoffPass() {}
%(iife)s
setTimeout(() => console.log(JSON.stringify({ closed, line: els["pass-clock"].textContent,
  hidden: els["pass-clock"].hidden, hero: els["season-clock"].textContent })), 50);
""" % {"now": json.dumps(now), "start": json.dumps(start), "week": json.dumps(week),
       "open": "true" if open_ else "false", "iife": iife}
    return _node(script)


W8 = {"season": "2026", "week": 8, "last_week": 18, "lands_on": "2026-11-03",
      "first_kickoff": "2026-10-30T00:15:00Z", "phase": "season", "odds": 3, "cards": True,
      "closest_call": True}


@needs_node
@pytest.mark.parametrize("week,lands,kickoff,now,open_,hero", [
    (8, "2026-11-03", "2026-10-30T00:15:00Z", "2026-10-30T20:00:00Z", False, "Week 9's report lands Tuesday."),
    (8, "2026-11-03", "2026-10-30T00:15:00Z", "2026-10-30T20:00:00Z", True, "Week 9's report lands Tuesday."),
    (13, "2026-12-08", "2026-12-04T01:15:00Z", "2026-12-01T20:00:00Z", True, "Week 13's report lands today."),
    (16, "2027-01-05", "2026-12-31T18:00:00Z", "2027-01-01T20:00:00Z", True, "Week 17's report lands Tuesday."),
    # Past Week 17's kickoff: Week 18 still goes out, and the card says the same.
    (17, "2027-01-12", "2027-01-08T01:15:00Z", "2027-01-09T20:00:00Z", True, "Week 18's report lands Tuesday."),
])
def test_the_card_says_the_same_words_every_week(week, lands, kickoff, now, open_, hero) -> None:
    """Owner decision, Oct 31 2026: a falling count makes a buyer do the math and
    wait for the price to fall with it. The hero names the next report and
    counts nothing; the card's line is the one in the markup."""
    got = _clock({**W8, "week": week, "lands_on": lands, "first_kickoff": kickoff}, now, open_)
    assert got["line"] == "A new lineup decided every Tuesday." and not got["hidden"]
    assert got["hero"] == hero


@needs_node
def test_a_season_that_is_over_hands_the_card_to_close_for_season() -> None:
    over = _clock({**W8, "phase": "over"}, "2027-02-01T20:00:00Z", True)
    assert over["closed"]
    assert '"pass-clock"' in _fn(LANDING, "closeForSeason")
    assert 'getElementById("pass-2027")' in _fn(LANDING, "closeForSeason")


def test_no_page_counts_the_season_down() -> None:
    """Every page, the text a script builds included. The count came off on Oct
    31 2026; this stops it coming back in another shape."""
    pages = sorted(SITE.rglob("*.html"))
    assert len(pages) > 15
    counted = re.compile(r"\b\d+ (more )?(lineups?|weeks?|reports?) (left|to go|remaining)\b", re.I)
    for path in pages:
        page = path.read_text(encoding="utf-8")
        assert not counted.search(page), path.name
        for built_by_script in ('" lineups"', '"lineups"', "left to a Week", "lineups to a Week",
                                "lineupsLeft", "lineupsAhead", "regular-season weeks"):
            assert built_by_script not in page, (path.name, built_by_script)


@needs_node
@pytest.mark.parametrize("week", [
    {**W8, "phase": "preseason"},                             # not a season week
    {**W8, "lands_on": "2026-10-01"},                         # a stale build
    {"week": 8},                                              # a file that can't say
])
def test_a_clock_that_cannot_say_leaves_the_static_lines(week) -> None:
    got = _clock(week, "2026-10-30T20:00:00Z", True)
    assert got["line"] == "A new lineup decided every Tuesday." and not got["hidden"]


def test_the_cards_generic_line_ships_in_the_markup() -> None:
    card = LANDING.split('id="pass-card"')[1].split("</ul>")[0]
    assert '<p class="passclock" id="pass-clock">A new lineup decided every Tuesday.</p>' in card


@needs_node
def test_step_three_states_the_price_the_button_charges() -> None:
    """Join's value line says the same words whatever the week, and no plan
    counts anything."""
    got = _node('const SEASON_2027_FIRST_RENEWAL = "August 15, 2028";\n' + _fn(JOIN, "valueWords") + """
var WANTS_PASS = false, chose2027 = false;
const out = [valueWords()];
WANTS_PASS = true;
out.push(valueWords());
WANTS_PASS = false; chose2027 = true;
out.push(valueWords());
console.log(JSON.stringify(out));""")
    assert got == ["Every lineup from now to your title game. $14.99 a month, and it stops "
                   "on its own.",
                   "Your whole league, every lineup from now to the title game. $34.99 a "
                   "month, and it stops on its own.",
                   "All of 2027, with the rest of this season included. $49 today, nothing "
                   "more until August 15, 2028."]


def test_step_three_is_redrawn_once_the_clock_has_read() -> None:
    assert ".then(() => { drawStep3(); drawPayoff(); })" in JOIN


# --------------------------------------------------------------------- #
# the money rule (owner decision, Oct 30 2026)
# --------------------------------------------------------------------- #

def test_the_hero_carries_no_price() -> None:
    hero = LANDING.split('<header class="hero">')[1].split("</header>")[0]
    hero = re.sub(r"<!-- phone:start -->.*?<!-- phone:end -->", "", hero, flags=re.S)
    assert "$" not in _flat(_markup(hero))


def test_no_page_breaks_a_price_down_for_the_buyer() -> None:
    """The owner tried "$3.22 a lineup" on the price card and took it out the
    same day: a per-unit figure makes a buyer calculate and think about the money
    instead of what they get. "Saved: $29 against buying both" went for the same
    reason. A price is stated, never worked out. The League Pass's "$5.75 a
    manager" stays: a commissioner collects from the group, and "a manager" is
    outside this sweep on purpose."""
    pages = sorted(SITE.rglob("*.html"))
    assert len(pages) > 15
    per_unit = re.compile(r"\$\d+(\.\d\d)? ?(a|per|/) ?(lineup|week|report|game)\b", re.I)
    for path in pages:
        page = path.read_text(encoding="utf-8")
        assert not per_unit.search(page), path.name
        for built_by_script in ('a lineup"', "perLineup", "against buying both"):
            assert built_by_script not in page, (path.name, built_by_script)


def test_no_former_price_is_ever_struck_or_compared() -> None:
    for name in ("index.html", "join/index.html", "league-pass.html", "thanks.html"):
        page = (SITE / name).read_text(encoding="utf-8")
        assert "<s>" not in page and "<del>" not in page and "line-through" not in page, name
        assert not re.search(r"\bwas \$\d|\bregular(ly)? \$\d|\bnormally \$\d", page, re.I), name


# --------------------------------------------------------------------- #
# the 2027 Season Pass, switched off
# --------------------------------------------------------------------- #

OFFER_WORDS = ("2027 Season Pass", "then each August", "Nothing more until", "more gets you",
               "gets you all of next season", "this season included", "This season included")


def test_the_switch_is_off_on_both_pages() -> None:
    assert re.search(r"^const SEASON_2027_READY = false;$", LANDING, re.M)
    assert re.search(r"^const SEASON_2027_READY = false;$", JOIN, re.M)
    assert re.search(r'^const STRIPE_LINK_2027 = "";', JOIN, re.M)


@pytest.mark.parametrize("name,page", [("landing", LANDING), ("join", JOIN)])
def test_with_the_switch_off_no_offer_text_ships_in_the_page(name: str, page: str) -> None:
    rendered = _markup(page)
    for words in OFFER_WORDS:
        assert words not in rendered, (name, words)
    # Structured data is markup a crawler reads: it stays one offer at $29.
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
                    .group(1)) if name == "landing" else None
    if ld:
        offers = next(n for n in ld["@graph"] if n["@type"] == "Product")["offers"]
        assert [o["price"] for o in offers] == ["14.99"]


def test_the_only_rendered_39_is_the_founding_line() -> None:
    assert _flat(_markup(LANDING)).count("$39") == 1
    assert "Founding rate: your 2027 season pass is $39." in _flat(_markup(LANDING))
    assert "$39" not in _flat(_markup(JOIN))
    assert "$49" not in _flat(_markup(LANDING)) + _flat(_markup(JOIN))


def test_every_offer_word_is_behind_the_switch() -> None:
    """The code that writes the offer runs only with the flag on: the landing's
    card from one guarded call, join's radio inside its guarded block."""
    assert "if (SEASON_2027_READY) season2027Card();" in LANDING
    assert LANDING.count("season2027Card();") == 1, "one call"
    assert "const PLAN_CHOICE = SEASON_2027_READY &&" in JOIN
    assert "let chose2027 = PLAN_CHOICE &&" in JOIN
    block = JOIN[JOIN.index("if (PLAN_CHOICE && !UPDATE_MODE && !TRY_MODE) {"):]
    assert '"2027 Season Pass · $49"' in block


class _Dom:
    """Just enough DOM to run the landing's card builder under node."""
    SCRIPT = r"""
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this.id = "";
    this.textContent = ""; this.href = ""; this.classes = new Set();
    this.classList = { remove: (c) => this.classes.delete(c), add: (c) => this.classes.add(c) }; }
  append(...kids) { this.children.push(...kids); }
  appendChild(kid) { this.children.push(kid); return kid; }
  replaceChildren(...kids) { this.children = kids; }
  text() { return this.textContent + this.children.map((k) => k.text ? k.text() : k.textContent).join(" "); }
}
const plans = new El("div"); plans.classes.add("one");
const first = new El("div"); first.id = "pass-card"; first.classes.add("founder"); first.parentNode = plans;
const ldEl = { textContent: JSON.stringify({ "@graph": [{ "@type": "Product", offers: [{ price: "14.99" }] }] }) };
const found = {};
globalThis.document = {
  createElement: (t) => new El(t),
  createTextNode: (t) => ({ textContent: t }),
  getElementById: (id) => id === "pass-card" ? first : found[id] || null,
  querySelector: () => ldEl,
};
const realAppend = plans.appendChild.bind(plans);
plans.appendChild = (card) => {
  const walk = (n) => { if (n.id) found[n.id] = n; (n.children || []).forEach(walk); };
  walk(card); return realAppend(card);
};
"""


@needs_node
@pytest.mark.parametrize("open_", [True, False])
def test_with_the_switch_on_the_renewal_sits_beside_the_price(open_: bool) -> None:
    fns = _fn(LANDING, "season2027Card")
    got = _node(_Dom.SCRIPT + f"""
const CHECKOUT_OPEN = {'true' if open_ else 'false'}, SEASON_2027_PRICE = 49, SEASON_2027_RENEWAL = 39;
const SEASON_2027_FIRST_RENEWAL = "August 15, 2028";
""" + fns + """
season2027Card();
const card = plans.children[0];
const parts = card.children.map((n) => [n.className, n.text()]);
console.log(JSON.stringify({ parts, id: card.id, firstFounder: first.classes.has("founder"),
  gridOne: plans.classes.has("one"), offers: JSON.parse(ldEl.textContent)["@graph"][0].offers,
  buy: card.children[card.children.length - 1].href,
  label: card.children[card.children.length - 1].textContent }));""")
    names = [p[0] for p in got["parts"]]
    assert names.index("price") + 1 == names.index("passterms"), "the terms sit under the price"
    terms = dict(got["parts"])["passterms"]
    assert terms == ("Nothing more until August 15, 2028, when it renews at $39, then each "
                     "August. Cancel any time. We email you before it bills.")
    assert "All of 2027, with the rest of this season included." in dict(got["parts"])["passlead"]
    assert dict(got["parts"])["price"] == "$49 / this season and next"
    assert got["firstFounder"] is False and got["gridOne"] is False, "the $49 card is the preferred one"
    assert [o["price"] for o in got["offers"]] == ["14.99", "49"]
    assert "renews at $39, then each August" in got["offers"][1]["description"]
    if open_:
        assert got["buy"] == "join/index.html?plan=2027" and got["label"] == "Get my lineups — $49"
    else:
        assert got["buy"] == "#watch-form" and got["label"] == "Tell me when it opens"


def test_the_plain_css_keeps_the_renewal_at_full_size() -> None:
    assert re.search(r"\.plan \.passterms\{[^}]*font-size:15px", LANDING), "the card's own size"


def test_the_cheaper_cards_button_never_lands_on_the_dearer_plan() -> None:
    assert 'link.href = "join/index.html?plan=monthly";' in LANDING
    assert '!QUERY.has("update") && QUERY.get("try") !== "1";' in JOIN
    assert 'let chose2027 = PLAN_CHOICE && PLAN_PARAM !== "monthly";' in JOIN
    # The choice is the one thing the address has to carry across a reload.
    assert 'if (PLAN_CHOICE) params.set("plan", chose2027 ? "2027" : "monthly");' in JOIN


def test_the_2027_plan_replaces_every_nothing_renews_line() -> None:
    """A buyer on the renewing plan must never read "stops on its own": the
    button's terms, the sidebar, the confirmation, the hero's risk line and the
    finance note all change with the flag or the choice."""
    fn = _fn(JOIN, "draw2027Plan")
    for target in ('$("terms-line")', '$("renew-note")', '$("first-tail")', '$("side-renew")',
                   '$("header-pitch")', '$("submit")'):
        assert target in fn, target
    assert 'textContent = "Unlock my lineups — $49";' in fn
    assert "We email you before it bills" in re.sub(r'"\s*\+\s*"', "", fn)
    assert LANDING.count('(SEASON_2027_READY ? "" : " Stops on its own after your title game.")') == 2


def test_the_ref_prefix_stays_s() -> None:
    """The plan comes from the link that took the money, never the ref."""
    fn = _fn(JOIN, "checkoutRef")
    assert 'WANTS_PASS ? "league_pass" : (buyingMonthly() ? "monthly" : "season")' in fn
    assert "2027" not in fn


# --------------------------------------------------------------------- #
# the buy page
# --------------------------------------------------------------------- #

def test_the_read_back_names_what_the_next_press_costs() -> None:
    fn = _fn(JOIN, "checkoutWords")
    for price in ("$14.99/mo", "$34.99/mo", "$49"):
        assert f"Continue to checkout — {price}" in fn
    assert '$("check-yes").textContent = go ? checkoutWords()' in JOIN


def test_the_closed_state_keeps_its_honest_lines() -> None:
    label = _fn(JOIN, "closedLabel")
    assert '"Save my team by email"' in label and '"Unlock' not in label


# --------------------------------------------------------------------- #
# long-term profit, words only
# --------------------------------------------------------------------- #

def test_the_last_report_and_the_thanks_page_make_the_founding_rate_plain() -> None:
    assert "Your 2027 season pass is $39." in ONCE_END
    assert "$39" not in ONCE_SEAT_END, "a seat bought nothing"
    meta = {"solo": True, "week": 18, "last_week": 18, "plan": "season", "one_time": True}
    assert "Your 2027 season pass is $39." in " ".join(season_end_lines(meta))
    assert not any("$39" in line for line in season_end_lines({"solo": True, "week": 18,
                                                               "last_week": 18}))
    assert "Your 2027 season pass is $39." in _flat(_markup(THANKS))


def test_the_group_chat_lines_are_short() -> None:
    ask = _flat(re.search(r'<p id="ask-text">(.*?)</p>', LEAGUE_PASS, re.S).group(1))
    friend = _flat(re.search(r'<p id="friend-line">(.*?)</p>', THANKS, re.S).group(1))
    assert len(ask) <= 210 and len(friend) <= 110, (len(ask), len(friend))


def test_the_closed_league_pass_leads_to_the_roster_check() -> None:
    slots = re.findall(r'<div class="ctaslot"[^>]*data-lp-cta>(.*?)</div>', LEAGUE_PASS, re.S)
    assert len(slots) == 2
    for slot in slots:
        assert 'class="btn gold" href="join/index.html?plan=pass"' in slot
        assert '<a href="index.html#watch-form">' in slot


# --------------------------------------------------------------------- #
# the sweep: not cheesy
# --------------------------------------------------------------------- #

SELLING = ("index.html", "join/index.html", "league-pass.html", "thanks.html", "how-it-works.html",
           "byes/index.html", "espn/index.html", "yahoo/index.html", "sleeper/index.html",
           "cbs/index.html")
CHEESE = (r"limited time", r"act now", r"\bhurry\b", r"don'?t miss", r"last chance", r"only \d+ (spots|left)",
          r"spots left", r"while supplies", r"\bexclusive\b", r"game[- ]chang", r"\bunbeatable\b",
          r"\brevolution", r"\bultimate\b", r"\binsane\b", r"\bguarantee[sd]? (you|a win)\b",
          r"win more", r"make the playoffs", r"\bsportsbook\b")


def _strings(page: str) -> str:
    """Every string literal in a page's inline scripts: buyer copy lives there too."""
    scripts = "\n".join(re.findall(r"<script>(.*?)</script>", page, re.S))
    code = "\n".join(line for line in scripts.splitlines() if not line.lstrip().startswith("//"))
    return " ".join(re.findall(r'"((?:[^"\\\n]|\\.)*)"', code))


@pytest.mark.parametrize("name", SELLING)
def test_no_selling_page_shouts(name: str) -> None:
    page = (SITE / name).read_text(encoding="utf-8")
    rendered = _flat(_markup(page))
    words = rendered + " " + _strings(page)
    for pattern in CHEESE:
        assert not re.search(pattern, words, re.I), (name, pattern)
    assert "!" not in rendered, f"an exclamation mark on {name}"
    assert not re.search(r"[A-Za-z]!(\s|$)", _strings(page)), f"an exclamation mark in {name}'s script"


@pytest.mark.parametrize("name", SELLING)
def test_no_selling_page_uses_a_banned_word(name: str) -> None:
    rendered = _flat(_markup((SITE / name).read_text(encoding="utf-8")))
    for word in ("calibrated", "tested", "proven", "accurate"):
        assert not re.search(rf"\b{word}\b", rendered, re.I), (name, word)


def test_the_refund_line_is_a_promise_and_keeps_the_pinned_words() -> None:
    card = _flat(LANDING.split('id="pass-card"')[1].split("</ul>")[0])
    assert ("Read your first weekly report before its games. Not for you? Full refund, no "
            "questions, until your first weekly report's week kicks off. One per person") in card
    # "weekly", not "first report": a buyer after a week's first game gets the
    # roster report first, and it has no games to read it before (terms §5).
    assert "Read your first report before" not in card


def test_the_first_renewal_date_is_the_one_the_code_bills_on() -> None:
    """The welcome, the terms and Stripe all say the code's date. Every page that
    sells or confirms the pass says the same one, or "each August" reads as
    next August and a buyer is surprised by nothing happening, then by a charge."""
    from render.welcome import first_renewal_words
    date = first_renewal_words()
    assert date == "August 15, 2028"
    for name in ("index.html", "join/index.html"):
        page = (SITE / name).read_text(encoding="utf-8")
        assert f'const SEASON_2027_FIRST_RENEWAL = "{date}";' in page, name
    assert f"Nothing more until {date}" in (SITE / "thanks.html").read_text(encoding="utf-8")
