"""The landing page's pre-launch review fixes (Oct 23 2026), each pinned.

Every test names the finding it holds (M = marketer, D = designer, QA, and the
critique's item 8) and states the reproduction in its docstring. The landing
is hand-written and the report it quotes is generated, so the figure tests
read the published sample rather than trusting the page.
"""
from __future__ import annotations

import html
import json
import re

from test_site import (LANDING, SAMPLE_REPORT, _js_function, _node, _style, markup_only,
                       prose)

CSS = _style(LANDING)
BODY = re.sub(r"<!--.*?-->", "", markup_only(LANDING), flags=re.S)
HERO = BODY.split('<header class="hero">')[1].split("</header>")[0]


def _flat(page: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))


def _block(css: str, query: str) -> str:
    """One @media block's body, matched by its own braces."""
    start = css.index(query + "{")
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        if depth == 0:
            return css[i + 1:j]
    raise AssertionError(f"unclosed {query}")


# --------------------------------------------------------------------- #
# the hero phone (D2, M4)
# --------------------------------------------------------------------- #

def test_the_hero_phone_names_no_week_number() -> None:
    """M4 / D2, reproduced at 390 and 1440 with today's week.json: the season
    clock read "Week 8's report lands Tuesday" directly above a phone whose
    notification and inbox row both said "Week 10: your lineup, decided" — the
    pinned 2024 sample's week, presented as this Tuesday's email. The phone
    says what the email does; the caption under it names the 2024 week."""
    screen = HERO.split('<div class="screen">')[1].split('<p class="realtag">')[0]
    assert not re.search(r"\bWeek \d+", _flat(screen)), "the phone names a week again"
    assert "Your lineup, decided. Closest call with odds: Robinson over Chase Brown, 70%." \
        in _flat(screen)
    tag = HERO.split('<p class="realtag">')[1].split("</p>")[0]
    assert "2024" in tag and "Week 10" in _flat(tag), "the sample's week left its caption"


def test_the_notification_is_solid_and_only_moves_under_the_status_bar() -> None:
    """D2, reproduced in CDP frames at 300 and 1200 ms (1440 wide): the
    notification was rgba(…,.96) and faded in and out over the inbox row, so
    "Beat Your League / Week 10: your lineup, decided" showed through it — two
    lines of text on top of each other — and it crossed the status bar's
    "8:04" on the way in. It is opaque now, the status bar is an opaque layer
    above it, and it is at full opacity on every frame where it can be seen."""
    notif = re.search(r"\.notif\{([^}]*)\}", CSS).group(1)
    background = re.search(r"background:([^;]+);", notif).group(1)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", background), f"translucent again: {background}"
    bar = re.search(r"\.statusbar\{([^}]*)\}", CSS).group(1)
    assert "position:relative" in bar and re.search(r"background:#[0-9A-Fa-f]{6}", bar)
    z_bar = int(re.search(r"z-index:(\d+)", bar).group(1))
    z_notif = int(re.search(r"z-index:(\d+)", notif).group(1))
    assert z_bar > z_notif, "the notification slides over the status bar"
    # The block ends at its first "}}" (the last stop's brace, then its own).
    frames = re.search(r"@keyframes notif\{(.*?\})\}", CSS, re.S).group(1)
    stops = re.findall(r"([\d%,]+)\{([^}]*)\}", frames)
    assert len(stops) >= 3, f"read {len(stops)} keyframe stops — the guard went blind"
    for at, body in stops:
        if at == "100%":
            continue                  # out of sight behind the status bar
        assert "opacity:1" in body, f"the notification fades at {at}: {body}"


def test_the_phone_screen_runs_on_with_the_samples_own_rows() -> None:
    """D2: below the if/then the screen was 110px of empty cream above the
    home bar (measured: the peek's last child ended at y=690, the screen at
    800), and the closest-call bar carried no figure while the notification
    above it quoted 70%. The screen now continues into the report's next
    section, Rising Roles, quoted verbatim from the published sample, and the
    bar carries the sample's own 70% — drawn from 50% as the report draws it."""
    peek = HERO.split('id="hero-peek"')[1].split('<div class="homebar"')[0]
    flat_sample = _flat(SAMPLE_REPORT)
    for item in re.findall(r"<li>(.*?)</li>", peek, re.S):
        assert _flat(item).strip() in flat_sample, f"not the sample's words: {_flat(item)}"
    figures = set(re.findall(r"\d+\.\d+", _flat(peek))) | set(re.findall(r"\d+%", _flat(peek)))
    assert {"70%", "24.0", "11.9", "9.5"} <= figures
    for figure in figures:
        assert figure in flat_sample, f"the hero phone cites {figure!r}, which the sample lacks"
    assert "Rising Roles" in flat_sample and "Rising roles" in _flat(peek)
    assert re.search(r'class="flippct">70%</span>', peek), "the bar lost its number"


def test_every_closest_call_bar_on_the_landing_is_drawn_from_fifty() -> None:
    """D12, measured: the landing's closest-call card filled its bar to 70%
    (a 0-100 tug-of-war with a midline) while the report and the email draw
    the same 70% as 40% of a bar that starts at 50%. Every bar beside a
    percentage on the page is (p - 50) x 2 wide now, and the midline is gone."""
    pairs = re.findall(r'<div class="flipbar"><span class="a"(?: data-w="(\d+)")? '
                       r'style="width:(\d+)%"></span></div><span class="flippct">(\d+)%</span>',
                       BODY)
    assert len(pairs) == 2, "the hero peek and the card below both carry a closest call"
    for data_w, width, pct in pairs:
        want = (int(pct) - 50) * 2
        assert int(width) == want and (not data_w or int(data_w) == want), (width, pct)
    assert ".flipbar::after" not in CSS, "the 0-100 midline is back"
    assert "The bar starts at 50%, a toss-up." in BODY
    # The motion starts the bar from empty, not from a midline that is gone.
    assert 'bar.closest(".flipbar") ? "50%"' not in LANDING
    for row in re.findall(r'<span class="fbar"><i style="width:(\d+)%"></i></span>'
                          r'<span class="fpct">(\d+)%</span>', BODY):
        assert int(row[0]) == (int(row[1]) - 50) * 2, row


def test_the_live_report_chip_waits_for_the_heros_rule_and_names_its_week() -> None:
    """M4, reproduced: this week's 2026 report was four words of small
    underlined text ("see this week's") at the fold under a phone showing a
    2024 week. It is a chip under the season clock now, still shown only by
    the three-odds rule, and it names the week and the day it was built.
    Run under node: a week.json with 3 odds reveals it labelled from the
    file; one with 2 leaves it hidden and untouched."""
    chip = re.search(r'<a class="livepill"[^>]*>', HERO).group(0)
    assert 'id="this-week-link"' in chip and "data-live-week" in chip and "hidden" in chip
    assert 'href="this-week.html"' in chip
    assert ".livepill[hidden]{display:inline-flex!important;visibility:hidden;}" in CSS, \
        "the chip's room is not reserved, so its arrival shifts the hero (CLS)"
    clock = LANDING.split("// The season clock.")[1]
    iife = clock[clock.index("(function () {"):clock.index("})();") + 5]
    harness = r"""
const make = (id) => ({ id, hidden: true, textContent: "This week's real report",
  replaceChildren() {}, appendChild() {} });
function run(w) {
  const els = { "season-clock": make("season-clock"), "this-week-link": make("this-week-link"),
                "this-week-label": make("this-week-label"), "realfoot": make("realfoot") };
  global.document = {
    getElementById: (id) => els[id] || null,
    querySelectorAll: (sel) => sel === "[data-live-week]"
      ? [els["this-week-link"], els["realfoot"]] : [],
    createElement: () => make("x"), createTextNode: (t) => ({ t }),
  };
  global.window = { fetch: true, AbortSignal: null };
  global.fetch = () => Promise.resolve({ ok: true, json: () => w });
  global.closeForSeason = () => {}; global.showPlayoffPass = () => {};
  global.PLAYOFF_PASS_READY = false; global.PLAYOFF_FROM_WEEK = 13;
  IIFE
  return new Promise((r) => setTimeout(() => r({
    hidden: els["this-week-link"].hidden, label: els["this-week-label"].textContent }), 50));
}
const base = { season: "2026", week: 7, last_week: 18, lands_on: "2999-01-05",
  built_at: "2026-10-20T17:15:45+00:00", closest_call: true,
  first_kickoff: "2999-01-01T00:15:00Z" };
// One at a time: each run swaps the globals the page script reads.
(async () => {
  const out = [];
  for (const w of [{ ...base, odds: 3 }, { ...base, odds: 2 },
                   { ...base, odds: 3, built_at: "garbage" }]) out.push(await run(w));
  console.log(JSON.stringify(out));
})();
""".replace("IIFE", iife)
    shown, held, undated = _node(harness)
    assert shown == {"hidden": False, "label": "Week 7's real report, built Tue, Oct 20"}
    assert held == {"hidden": True, "label": "This week's real report"}
    assert undated == {"hidden": False, "label": "Week 7's real report"}


# --------------------------------------------------------------------- #
# phone order, nav (M6, D10, D19, M13)
# --------------------------------------------------------------------- #

def test_a_phone_sees_any_app_no_login_before_the_phone_mockup() -> None:
    """M6, measured at 390: the "ESPN, Yahoo, Sleeper, CBS — paste your
    roster, no login" ticks sat at y=1257, after the 620px phone mockup, about
    1.5 screens down on the device most visitors arrive on. The proposed
    fix, order:3.5, is invalid CSS (order takes integers) and was dropped by
    the browser; the orders are integers, ticks straight after the sub."""
    # The hero's own phone block (an earlier one-line 880px query is the
    # credibility strip's).
    phone = next(_block(CSS[at:], "@media (max-width:880px)")
                 for at in (m.start() for m in re.finditer(r"@media \(max-width:880px\)\{", CSS))
                 if ".hero .sub{" in _block(CSS[at:], "@media (max-width:880px)"))
    orders = {sel.strip(): value for sel, value in
              re.findall(r"(\.hero(?:\.can-buy)? \.[\w-]+|\.hero h1)\{[^}]*?order:([^;}]+)", phone)}
    for sel, value in orders.items():
        assert re.fullmatch(r"-?\d+", value.strip()), f"{sel} order:{value} is not an integer"
    num = {k: int(v) for k, v in orders.items()}
    assert num[".hero .sub"] < num[".hero .creds"] < num[".hero .watchform"] \
        < num[".hero .heroline"] < num[".hero .phonewrap"], num
    assert num[".hero.can-buy .cta-row"] < num[".hero .phonewrap"]


def test_the_nav_is_the_logo_lockup_and_a_phone_keeps_one_route() -> None:
    """D10: the nav set the name like the kicker labels (15px, upright,
    tracked gold caps) rather than as the logo in site/brand (heavy italic,
    "Beat Your" in paper, "League" in gold). D19: below 600px the nav was the
    logo alone. M13: the landing nav had no Pricing link while every other
    page's does. A phone keeps exactly one text route — the real report — and
    Pricing is a same-page anchor (index.html#pricing from "/" reloads)."""
    nav = BODY.split("<nav>")[1].split("</nav>")[0]
    assert re.search(r'<a class="brand" href="index\.html"><svg class="mark".*?</svg>'
                     r'<span>Beat Your <span class="lg">League</span></span></a>', nav, re.S)
    brand = re.search(r"\n  \.brand\{([^}]*)\}", CSS).group(1)
    assert "font-weight:900" in brand and "font-style:italic" in brand
    assert "letter-spacing:.24em" not in brand
    links = re.findall(r'<a (?:class="([^"]*)" )?href="([^"]+)"[^>]*>([^<]+)</a>',
                       nav.split('<div class="navlinks">')[1])
    by_label = {label.strip(): (cls, href) for cls, href, label in links}
    assert by_label["Pricing"][1] == "#pricing"
    assert by_label["See a real report"] == ("", "sample-report.html"), \
        "the phone's one route is hidden again"
    small = _block(CSS, "@media (max-width:599px)")
    assert "nav .btn{display:none;}" in small and ".navlinks a{display:none" not in small
    for label in ("How it works", "Pricing"):
        assert "hidemd" in by_label[label][0], f"{label} crowds the phone nav"


# --------------------------------------------------------------------- #
# pricing (D4, D6, QA-03) and the playoff swap
# --------------------------------------------------------------------- #

def test_the_closed_pricing_card_is_a_real_button_not_a_placeholder() -> None:
    """D4, reproduced at 1440 and 390: the $29 card's only control was a
    dashed #EEEBE2 box reading "Checkout opens soon" that looked like a
    wireframe, and the line under the card repeated "Checkout opens soon —
    leave your email". The closed state is the gold "Tell me when it opens"
    every other closed CTA carries, into the form, with one short caption; the
    repeat is gone. Contract C2: never a dashed placeholder box."""
    card = BODY.split('id="pass-card"')[1].split('<p class="finance"')[0]
    assert re.search(r'<a class="btn gold" id="season-cta" href="#watch-form"[^>]*>'
                     r'Tell me when it opens</a>', card)
    assert 'class="soon"' not in BODY and "dashed" not in re.search(
        r"\.plan[^{]*\{[^}]*\}", CSS).group(0)
    assert not re.search(r"\.plan [^{]*\{[^}]*dashed", CSS)
    finance = BODY.split('id="finance-note">')[1].split("</p>")[0]
    assert "Checkout opens soon" not in finance and 'href="league-pass.html"' in finance


def test_the_card_uses_the_sites_check_bullets() -> None:
    """D6: the card's list used the browser's disc bullets at line-height 1.7
    while the hero uses green check circles, and the 520px card sat centred
    between a left-set heading and left-set notes — three alignment axes in
    one section."""
    ul = re.search(r"\.plan ul\{([^}]*)\}", CSS).group(1)
    assert "list-style:none" in ul
    assert re.search(r"\.plan li::before\{[^}]*background:var\(--turf\) url\(", CSS)
    assert re.search(r"\.plans\.one\{[^}]*justify-content:start", CSS)


def test_the_pass_card_promises_a_first_report_not_a_first_weekly_one() -> None:
    """QA-03, reproduced in code: the card, the Playoff swap and the JSON-LD
    said "every weekly report … the first usually within the hour of joining",
    but run/intake._first_file sends that week's report only before its first
    kickoff — from Thursday night to Tuesday (about 4.5 days in 7) the first
    WEEKLY report is the next Tuesday's, and what lands within the hour is the
    roster report. Every copy now says "your first report"."""
    product = next(n for n in json.loads(re.search(
        r'<script type="application/ld\+json">(.*?)</script>', LANDING, re.S).group(1))["@graph"]
        if n["@type"] == "Product")
    surfaces = {
        "card": _flat(BODY.split('id="pass-span">')[1].split("</li>")[0]),
        "playoff swap": prose(_js_function(LANDING, "showPlayoffPass")),
        "JSON-LD": product["offers"][0]["description"],
    }
    for name, text in surfaces.items():
        assert "the first usually within the hour" not in text, name
        assert "your first report usually lands within the hour of joining" in text, name


def test_the_playoff_swap_never_relabels_the_closed_button() -> None:
    """The closed card's control is a link now (D4), and showPlayoffPass used
    to relabel #season-cta whenever it was an <a> — which would have put "Get
    the Playoff Pass — $19" on a button that only opens the email capture.
    Only the BUY link the open state builds (marked data-buy) takes the price.
    Run under node against both elements."""
    fn = _js_function(LANDING, "showPlayoffPass")
    assert 'link.setAttribute("data-buy", "")' in LANDING.split("if (CHECKOUT_OPEN)")[1]
    harness = r"""
let PASS_LABEL = "Get the Rest-of-Season Pass — $29";
function check(buy) {
  const cta = { tagName: "A", textContent: "Tell me when it opens",
                hasAttribute: (n) => buy && n === "data-buy" };
  global.document = { getElementById: (id) => id === "season-cta" ? cta : null,
                      createTextNode: () => ({}), createElement: () => ({}) };
  FN
  showPlayoffPass(13);
  return cta.textContent;
}
console.log(JSON.stringify([check(false), check(true)]));
""".replace("FN", fn)
    closed, open_ = _node(harness)
    assert closed == "Tell me when it opens"
    assert open_ == "Get the Playoff Pass — $19"


# --------------------------------------------------------------------- #
# the FAQ (M3)
# --------------------------------------------------------------------- #

def test_the_faq_answers_the_free_rankings_objection_with_facts_only() -> None:
    """M3: none of the seven questions answered the first objection to a paid
    start/sit report — "my app and free rankings already do this". "When does
    it arrive?" gave its place (the week strip already says Tuesday and
    Saturday). The answer says only what the report does: no claim of better
    projections (our own evaluation found a free feed's beat the model's), no
    number, no link to a grading page, and the JSON-LD says the same words."""
    faq = BODY.split('<section id="faq">')[1].split("</section>")[0]
    qa = dict(re.findall(r"<summary>(.*?)</summary>\s*<div class=\"a\">(.*?)</div>", faq, re.S))
    assert len(qa) == 7 and "When does it arrive?" not in qa
    answer = qa["How is this different from free rankings?"]
    text = _flat(answer)
    assert "<a " not in answer and not re.search(r"\d", text)
    for claim in (r"\bbetter\b", r"\bmore accurate\b", r"\bbeats? (?:them|rankings)\b",
                  r"\bsmarter\b", r"\bwin\b", r"\bproven\b", r"\btested\b"):
        assert not re.search(claim, text, re.I), claim
    for fact in ("your roster", "bench player", "if/then", "byes", "Saturday",
                 "Friday's injury report"):
        assert fact.lower() in text.lower() or fact in text, fact
    block = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                 LANDING, re.S).group(1))
    faq_ld = next(n for n in block["@graph"] if n["@type"] == "FAQPage")
    twin = {q["name"]: q["acceptedAnswer"]["text"] for q in faq_ld["mainEntity"]}
    assert twin["How is this different from free rankings?"] == re.sub(r"\s+", " ", text).strip()
    week = _flat(BODY.split('<ol class="timeline">')[1].split("</ol>")[0])
    assert "Tuesday" in week and "Saturday" in week, "the removed answer's facts left the page"


# --------------------------------------------------------------------- #
# cards, headings and icons (D9, D11, D16, D17, critique #8)
# --------------------------------------------------------------------- #

def test_nothing_that_cannot_be_clicked_moves_on_hover() -> None:
    """D9 / contract C2: the method cards (the only rounded cards on the
    site, 14px) lifted 5px with a gold glow, the pricing card glowed and the
    week strip tinted on hover — none of them is a link, so each promised a
    click that did nothing. Square cards, no hover state."""
    for sel in (r"\.method article", r"\.plan(?:\.founder)?", r"\.timeline li"):
        assert not re.search(sel + r":hover", CSS), f"{sel} still reacts to hover"
    method = re.search(r"\n  \.method article\{([^}]*)\}", CSS).group(1)
    assert "border-radius" not in method and "border-top:3px solid var(--flag)" in method


def test_the_roster_icon_is_not_the_menu_glyph() -> None:
    """D11: "Your exact roster" was drawn with M4 6h16M4 12h16M4 18h10 —
    three horizontal lines, the universal hamburger-menu icon. It is a
    clipboard with a check, every path inside the 64-unit draw-in dash."""
    cred = BODY.split('<div class="cred">')[1].split("</div>\n</section>")[0]
    roster = cred.split("<b>Your exact roster</b>")[0].rsplit("<svg", 1)[1]
    assert "M4 6h16M4 12h16" not in roster and "<rect" in roster and "M9 14l2 2 4-4" in roster


def test_section_heads_follow_one_rule() -> None:
    """D16: two headings ended in a period and five did not, and two were
    slanted with no pattern. Section heads are upright with no period; only
    the slogans (pricing, closer) are slanted, with one. The kicker and the
    closer's line balance rather than orphaning a word at 390."""
    for attrs, text in re.findall(r"<h2([^>]*)>(.*?)</h2>", BODY, re.S):
        words = _flat(text).strip()
        if "slant" in attrs:
            assert words.endswith("."), words
        else:
            assert not words.endswith("."), f"a section head ends in a period: {words}"
    assert re.search(r"\.kicker\{[^}]*text-wrap:balance", CSS)
    assert "Fantasy football&nbsp;· the playoff push" in BODY


def test_no_headline_is_used_twice_and_the_note_does_not_repeat_its_card() -> None:
    """D17: "Odds only when earned" was both the credibility strip's third
    item and method card 03, and "The close one, called" repeated its card's
    "Start Bijan Robinson over Chase Brown — 70%, proj 15.1 vs 10.3" verbatim
    beside it (directly above it on a phone)."""
    strip = re.findall(r"<b>([^<]+)</b>", BODY.split('<div class="cred">')[1].split("</section>")[0])
    cards = re.findall(r"<h3>([^<]+)</h3>", BODY.split('<div class="method">')[1].split("</section>")[0])
    assert not set(strip) & set(cards), set(strip) & set(cards)
    note = _flat(BODY.split("<b>The close one, called</b>")[1].split("</div>")[0])
    assert "70%" not in note and "15.1" not in note


def test_the_title_names_the_category_a_searcher_types() -> None:
    """Critique #8: none of the site's titles said "fantasy football" or
    "start/sit" — the landing's was "every lineup decided, through your title
    game", and og:title the same. Both now name the category and keep the
    mid-season promise; the entity sentence (meta description, JSON-LD) is
    untouched and pinned elsewhere."""
    title = re.search(r"<title>(.*?)</title>", LANDING).group(1)
    og = re.search(r'<meta property="og:title" content="([^"]+)">', LANDING).group(1)
    assert title == og
    for words in ("fantasy football", "start/sit", "title game"):
        assert words in title, words
    assert title.startswith("Beat Your League — ")
