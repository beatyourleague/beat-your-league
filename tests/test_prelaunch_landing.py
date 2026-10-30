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
from pathlib import Path

from test_site import (LANDING, SAMPLE_REPORT, _js_function, _node, _style, markup_only,
                       prose)

CSS = _style(LANDING)
BODY = re.sub(r"<!--.*?-->", "", markup_only(LANDING), flags=re.S)
HERO = BODY.split('<header class="hero">')[1].split("</header>")[0]
SCREEN = HERO.split('<div class="screen"')[1].split('<p class="realtag">')[0]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample-report-w10.json"


def _sample() -> dict:
    """The pinned sample report the phone is generated from (make sample)."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _lock_text() -> tuple[str, str]:
    """The notification's subject and preview, as the phone prints them."""
    lock = HERO.split('<div class="lock"')[1].split('<div class="glass"')[0]
    subject = re.search(r'<span class="lsub">(.*?)</span>', lock, re.S).group(1)
    preview = re.search(r'<span class="lpre">(.*?)</span>', lock, re.S).group(1)
    return html.unescape(subject), html.unescape(preview)


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

def test_the_phones_week_is_the_archived_sample() -> None:
    """M4 / D2, reproduced at 390 and 1440 with today's week.json: the season
    clock read "Week 8's report lands Tuesday" directly above a phone whose
    notification and inbox row both said "Week 10: your lineup, decided" — the
    pinned 2024 sample's week, presented as this Tuesday's email. The phone is
    now a faithful copy of that email (contract C11), so its "Week 10" stays —
    and says what it is: the masthead's stamp names the 2024 season archive,
    the caption under the phone names 2024, and on a phone the button row
    sits between the clock and the phone, so the two weeks never read as one
    line. Since Oct 30 2026 a phone meets the report first (owner review), so
    the form stands between them instead, with the clock below it. Since the sales review the caption leads with the year ("2024
    sample report · Week 10, replayed"), and this week's live link sits under
    the hero's "See a real report" (one secondary group) — it names no week,
    so only the clock and the sample do."""
    masthead = SCREEN.split('<div class="mh">')[1].split('<section class="card"')[0]
    assert "Week 10" in _flat(masthead)
    stamp = _flat(re.search(r'<div class="mh-stamp">(.*?)</div>', masthead, re.S).group(1))
    assert "2024 season archive" in stamp, stamp
    tag = HERO.split('<p class="realtag">')[1].split("</p>")[0]
    assert "2024" in tag and "Week 10" in _flat(tag), "the sample's week left its caption"
    phones = CSS.split("@media (max-width:880px){\n")[1]
    assert _flat(tag).strip().startswith("2024"), "the caption no longer leads with the year"
    order = {name: int(re.search(r"\.hero \." + name + r"\{order:(\d+)", phones).group(1))
             for name in ("heroline", "cta-row", "phonewrap", "livepill", "livecall", "watchform")}
    assert order["phonewrap"] < order["watchform"] < order["heroline"] < order["cta-row"], order
    assert order["cta-row"] == order["livepill"] == order["livecall"], order
    assert HERO.index('<div class="cta-row">') < HERO.index('<a class="livepill"') \
        < HERO.index('<p class="livecall"')
    # Open, the buy row moves up to the form's place and the clock goes with
    # it, still above the row (equal orders keep source order: the clock's
    # line comes first in the markup).
    assert ".hero.can-buy .heroline{order:6;}" in phones
    assert ".hero.can-buy .cta-row{order:6;}" in phones
    assert HERO.index('<p class="heroline">') < HERO.index('<div class="cta-row">')


def _keyframes(name: str) -> list[tuple[float, str]]:
    """(stop as a fraction, declarations) for one @keyframes block, every
    stop of a comma list on its own, in time order."""
    body = re.search(r"@keyframes " + re.escape(name) + r"\{(.*?\})\s*\}", CSS, re.S).group(1)
    stops = []
    for at, decl in re.findall(r"([\d.%,\s]+|from|to)\{([^}]*)\}", body):
        for one in at.split(","):
            one = one.strip()
            value = {"from": 0.0, "to": 1.0}.get(one)
            stops.append((float(one.rstrip("%")) / 100 if value is None else value,
                          decl.replace(" ", "")))
    return sorted(stops)


def test_the_notification_is_solid_and_only_shows_on_the_lock_screen() -> None:
    """D2, carried into the Oct 24 2026 storyline. The old banner was
    rgba(…,.96) and faded in over the inbox row, so two lines of text sat on
    top of each other for half a second. The notification now lives on the
    lock screen, which covers the whole report while it shows: the card is a
    solid colour, it sits inside .lock, the layers stack status bar < lock <
    black < island, the card is opaque only while the lock is, and the lock's
    own text has faded out by the time the lock itself starts to go — so
    text never crosses text on the way back to the report."""
    from render.email import preheader_for, subject_for
    note = re.search(r"\.lnote\{([^}]*)\}", CSS).group(1)
    background = re.search(r"background:([^;]+);", note).group(1)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", background), f"translucent again: {background}"
    lock = HERO.split('<div class="lock"')[1].split('<div class="glass"')[0]
    assert 'class="lnote"' in lock, "the notification left the lock screen"
    # Contract C11: the notification IS the email's own subject and preview.
    assert _lock_text() == (subject_for(_sample()), preheader_for(_sample()))

    def z(rule: str) -> int:
        block = re.search(rule + r"\{([^}]*)\}", CSS).group(1)
        return int(re.search(r"z-index:(\d+)", block).group(1))
    # Each layer's own rule, at the start of a line. No black layer since
    # the sales review: the report cross-fades to the lock and back.
    assert z(r"\n  \.statusbar") < z(r"\n  \.lock") < z(r"\n  \.island")
    assert "lk-dark" not in HERO and "lk-dark" not in CSS
    # The lock is fully up from its first opaque stop to its last; the card's
    # opaque stops all fall inside that stretch.
    lock_up = [t for t, d in _keyframes("st-lock") if "opacity:1" in d]
    note_up = [t for t, d in _keyframes("st-note") if "opacity:1" in d]
    lock_fade = max(lock_up)
    # The card's 100% stop keeps opacity:1 under a lock that has gone by then
    # (the rest state); its visible stretch is every opaque stop before that.
    shown = [t for t in note_up if t < 1]
    assert shown and min(lock_up) <= min(shown) and max(shown) <= lock_fade, (lock_up, note_up)
    # The lock's text has gone before the lock starts to fade.
    fg_gone = min(t for t, d in _keyframes("st-fg") if "opacity:0" in d)
    assert fg_gone <= lock_fade, "the lock's text is still up when the lock fades"


def test_the_phone_screen_runs_on_with_the_samples_own_rows() -> None:
    """D2: below the if/then the screen was 110px of empty cream above the
    home bar, and the closest-call bar carried no figure while the
    notification above it quoted 70%. The screen is now the email itself, cut
    by the bottom edge as a real inbox cuts it (the paper runs on under the
    crop): its masthead, card 01 whole and card 02 through its drivers line,
    every figure the sample's own, the bar carrying its number."""
    flat_sample = _flat(SAMPLE_REPORT)
    lineup = SCREEN.split('data-sec="lineup"')[1].split("</section>")[0]
    closest = SCREEN.split('data-sec="closest"')[1].split("</section>")[0]
    assert len(re.findall(r'<div class="frow"', lineup)) == 9, "card 01 lost a slot"
    assert '<p class="drivers">' in closest, "card 02 is cut above its drivers line"
    figures = set(re.findall(r"\d+\.\d+", _flat(SCREEN))) | set(re.findall(r"\d+%", _flat(SCREEN)))
    assert {"72%", "126.1", "14.1", "9.5"} <= figures
    for figure in figures:
        assert figure in flat_sample, f"the hero phone cites {figure!r}, which the sample lacks"
    assert re.search(r'<b class="cpct">72%</b>', closest), "the bar lost its number"
    assert re.search(r"\n  \.mailview\{[^}]*padding-bottom:\d", CSS), \
        "the paper stops at the crop again"


def test_every_closest_call_bar_on_the_landing_is_drawn_from_fifty() -> None:
    """D12, measured: the landing's closest-call card filled its bar to 70%
    (a 0-100 tug-of-war with a midline) while the report and the email draw
    the same 70% as 40% of a bar that starts at 50%. Every bar beside a
    percentage on the page is render.report.bar_from_even(pct) wide — (p − 50)
    × 2, from the PRINTED % (contract C9) — and the midline is gone. One
    closest call on the page: the phone's card 02 (the page never shows 72%
    Kittle-over-LaPorta in two cards)."""
    pairs = re.findall(r'<span class="cbar"><i style="width:(\d+)%"></i></span>'
                       r'<b class="cpct">(\d+)%</b>', BODY)
    assert len(pairs) == 1, "the closest call is on the page once, in the phone"
    for width, pct in pairs:
        assert int(width) == (int(pct) - 50) * 2, (width, pct)
    assert ".cbar::after" not in CSS and ".flipbar" not in CSS, "the 0-100 midline is back"
    assert "the bar starts at 50% (a toss-up)" in _flat(BODY)
    rows = re.findall(r'<span class="fbar"><i style="width:(\d+)%"></i></span>'
                      r'<span class="fpct">(\d+)%</span>', BODY)
    assert len(rows) >= 3, "the phone's lineup lost its odds rows"
    for row in rows:
        assert int(row[0]) == (int(row[1]) - 50) * 2, row


def test_the_live_report_chip_waits_for_the_heros_rule_and_names_its_week() -> None:
    """M4, reproduced: this week's 2026 report was four words of small
    underlined text ("see this week's") at the fold under a phone showing a
    2024 week. It is a link of its own under the season clock now, still shown only by
    the three-odds rule, and it names the day it was built — "this week's",
    never a week number (sales review: with the clock's week and the
    sample's, a third number read as three weeks at once).
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
const make = (id) => ({ id, hidden: true, textContent: "or this week's live report",
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
  built_at: "2026-10-20T17:15:45+00:00", closest_call: true, cards: true,
  first_kickoff: "2999-01-01T00:15:00Z" };
// One at a time: each run swaps the globals the page script reads.
(async () => {
  const out = [];
  for (const w of [{ ...base, odds: 3 }, { ...base, odds: 2 },
                   { ...base, odds: 3, built_at: "garbage" },
                   { ...base, odds: 3, cards: undefined },
                   { ...base, odds: 3, cards: "true" }]) out.push(await run(w));
  console.log(JSON.stringify(out));
})();
""".replace("IIFE", iife)
    shown, held, undated, old_layout, loose = _node(harness)
    assert shown == {"hidden": False, "label": "or this week's live report (built Tue, Oct 20)"}
    assert held == {"hidden": True, "label": "or this week's live report"}
    assert undated == {"hidden": False, "label": "or this week's live report"}
    # Review BUYER-1: a page built before the card stack (no `cards` on its
    # clock, as the Oct 20 build wrote it) is not offered beside the phone.
    assert old_layout == loose == {"hidden": True, "label": "or this week's live report"}


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
    assert num[".hero .sub"] < num[".hero .creds"] < num[".hero .phonewrap"] \
        < num[".hero .watchform"] < num[".hero .heroline"], num
    # The report, then the action: closed or open, the phone never sits under it.
    assert num[".hero .phonewrap"] < num[".hero.can-buy .cta-row"]


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
    finance = BODY.split('id="finance-note"')[1].split("</p>")[0]
    assert "Checkout opens soon" not in finance
    # The League Pass is pitched once, by its own strip under the card
    # (review BUYER-4/SLEEK-6: "Running the league? One payment can cover
    # every team" sat directly above "Run the league? One payment covers
    # every manager"), and the open state does not bring it back.
    assert 'href="league-pass.html"' not in finance and "Running the league" not in LANDING
    lpline = re.search(r'<p class="lpline">(.*?)</p>', BODY, re.S).group(1)
    assert 'href="league-pass.html"' in lpline and "Run the league?" in lpline


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
        assert "Your first report usually lands within the hour" in text, name


def test_the_playoff_swap_never_relabels_the_closed_button() -> None:
    """The closed card's control is a link now (D4), and showPlayoffPass used
    to relabel #season-cta whenever it was an <a> — which would have put "Get
    the Playoff Pass — $19" on a button that only opens the email capture.
    Only the BUY link the open state builds (marked data-buy) takes the price.
    Run under node against both elements."""
    fn = _js_function(LANDING, "showPlayoffPass")
    assert 'link.setAttribute("data-buy", "")' in LANDING.split("if (CHECKOUT_OPEN)")[1]
    harness = r"""
let PASS_LABEL = "Get my lineups — $29";
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
    assert open_ == "Get my lineups — $19"


# --------------------------------------------------------------------- #
# the FAQ (M3)
# --------------------------------------------------------------------- #

def test_the_rankings_objection_is_answered_with_facts_only() -> None:
    """M3, moved from the FAQ to its own table by the owner's Oct 28 2026
    plan: the first objection to a paid start/sit report is "my app and free
    rankings already do this". The table says only what each one does — no
    competitor named, no claim of better projections (our own evaluation
    found a free feed's beat the model's), no number, no link to a grading
    page, no results promise — and the FAQ no longer repeats it."""
    table = BODY.split('<table class="vstable">')[1].split("</table>")[0]
    text = _flat(table)
    assert "<a " not in table and not re.search(r"\d", text)
    for claim in (r"\bbetter\b", r"\bmore accurate\b", r"\bbeats?\b", r"\bsmarter\b",
                  r"\bwin\b", r"\bproven\b", r"\btested\b", r"\bbest\b", r"\bonly\b"):
        assert not re.search(claim, text, re.I), claim
    for fact in ("roster", "Every slot decided", "bench", "if/then", "Saturday", "title game"):
        assert fact in text, fact
    for brand in ("ESPN", "Yahoo", "Sleeper", "CBS", "FantasyPros", "Rotowire", "4for4"):
        assert brand not in text, brand
    faq = BODY.split('<section id="faq">')[1].split("</section>")[0]
    assert "How is this different from free rankings?" not in faq
    assert "Tuesday" in _flat(BODY) and "Saturday" in _flat(BODY)


# --------------------------------------------------------------------- #
# cards, headings and icons (D9, D11, D16, D17, critique #8)
# --------------------------------------------------------------------- #

def test_nothing_that_cannot_be_clicked_moves_on_hover() -> None:
    """D9 / contract C2: the method cards lifted 5px with a gold glow, the
    pricing card glowed and the week strip tinted on hover — none of them is
    a link, so each promised a click that did nothing. Nothing that is not a
    link answers the cursor: the steps, their pictures, the callouts, the
    comparison, the pricing card and the report close-up hold still; the
    planner link in the callouts, which IS a link, does answer it. No 3-4px
    side or top bars."""
    for sel in (r"\.step", r"\.sicon", r"\.callouts li", r"\.vstable[^{,]*",
                r"\.plan(?:\.founder)?", r"\.shot[^{,]*", r"\.anat"):
        assert not re.search(sel + r":hover", CSS), f"{sel} still reacts to hover"
    assert not re.search(r"border-(?:top|left):[34]px", CSS), "a 3-4px side bar is back"
    assert re.search(r"\n  \.callouts a\.go:hover\{", CSS), "the planner link lost its hover"


def test_section_heads_follow_one_rule() -> None:
    """D16: two headings ended in a period and five did not, and two were
    slanted with no pattern. Section heads are upright with no period; only
    the slogans (pricing, closer) end with one — and since contract C7 they
    are upright too (italic survives only in the hero slab and the lockup).
    The kicker fits one line at a phone's width (13px, .08em: measured at 320
    and 390), so no dot strands at a line's end."""
    slogans = {"Take it through your title game.", "Your lineup, decided every Tuesday."}
    for attrs, text in re.findall(r"<h2([^>]*)>(.*?)</h2>", BODY, re.S):
        words = _flat(text).strip()
        assert "slant" not in attrs, f"a slanted head is back: {words}"
        if words in slogans:
            assert words.endswith("."), words
        else:
            assert not words.endswith("."), f"a section head ends in a period: {words}"
    h2 = re.search(r"\n  h2\{([^}]*)\}", CSS).group(1)
    assert "italic" not in h2 and "h2.slant" not in CSS
    kicker = re.search(r"\n  \.kicker\{([^}]*)\}", CSS).group(1)
    assert "font-size:13px" in kicker and "letter-spacing:.08em" in kicker
    assert ('<div class="kicker"><span>Fantasy football</span><span class="ksep">&nbsp;· </span>'
            '<span>the playoff push</span></div>') in BODY


def test_no_headline_is_used_twice_and_the_note_does_not_repeat_its_card() -> None:
    """D17: "Odds only when earned" was both the credibility strip's third
    item and method card 03, and a note repeated its card's figures verbatim
    beside it. No head on the page repeats another — the three steps, the
    four callouts and the comparison's row labels — and no callout repeats a
    figure from the report close-up it annotates."""
    heads = (re.findall(r"<h3>([^<]+)</h3>", BODY)
             + re.findall(r'<th scope="row">([^<]+)</th>', BODY))
    assert len(heads) == len(set(heads)) >= 12, heads
    shot = BODY.split('id="shot-card"')[1].split("<!--/card-->")[0] if "<!--/card-->" in BODY \
        else BODY.split('id="shot-card"')[1].split('<figcaption')[0]
    figures = set(re.findall(r"\d+(?:[.:]\d+)?%?", _flat(shot)))
    callouts = BODY.split('<ol class="callouts">')[1].split("</ol>")[0]
    for item in re.findall(r"<li[^>]*>(.*?)</li>", callouts, re.S):
        assert not set(re.findall(r"\d+(?:[.:]\d+)?%?", _flat(item))) & figures, _flat(item)


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


# --------------------------------------------------------------------- #
# the review of this branch (Oct 24 2026)
# --------------------------------------------------------------------- #

def test_the_live_report_link_never_promotes_a_page_with_subscription_terms() -> None:
    """Review (medium), reproduced: the hero's live-report link made
    site/this-week.html far more visible (a 288x38 chip at y=647 at 390,
    where it had been a 100x17 inline link under the phone) while that page,
    built by the Oct 20 cron from code older than the one-time passes, still
    said "Cancel it yourself from your own billing page … Reports continue to
    the end of the period you've already paid for" (grep -c 'billing page'
    = 1) and sent both its asks into the closed join page — beside a landing
    that says "One payment. Nothing renews". The link waits on week.json's
    three-odds rule, which says nothing about the page's terms, so this test
    is the gate: while the site sells one-time passes, the page the link
    opens may not describe a subscription, and while checkout is closed it
    may not send anybody into join/. It fails until this-week.html is
    restamped (`python -m render.live_sample --restamp`, the pages branch)
    or rebuilt by the Tuesday cron with today's code."""
    from render import report as rr
    from test_site import SITE

    link = re.search(r'<a class="livepill"[^>]*href="([^"]+)"', HERO).group(1)
    target = (SITE / link).read_text(encoding="utf-8")
    if rr.SELLING_ONE_TIME:
        for subscription in ("billing page", "does not stop a subscription",
                             "the period you&#x27;ve already paid for",
                             "the period you've already paid for"):
            assert subscription not in target, (
                f"{link} describes a subscription ({subscription!r}) under a one-payment "
                f"landing — restamp it before the hero links it")
    if "const CHECKOUT_OPEN = false;" in LANDING:
        assert 'href="join/' not in markup_only(target), \
            f"{link} sends buyers into a closed checkout"


def test_the_live_report_link_is_a_text_link_not_a_third_button() -> None:
    """Review (low), contract C2: the live-report "chip" was bordered,
    padded, bold and gold-tinted with an arrow — a third button-like control
    stacked between the gold form button and the ghost "See a real report"
    (measured at 1440: y=700, between the two). It is a text link with the
    live dot: no border, no fill, no horizontal padding, its room still
    reserved so its arrival moves nothing."""
    rule = re.search(r"\n  \.livepill\{([^}]*)\}", CSS).group(1)
    for prop in ("border:", "background:", "border-radius"):
        assert prop not in rule, f"the live link is drawn as a box again ({prop})"
    pad = re.search(r"padding:([^;]+);", rule).group(1).split()
    assert len(pad) == 2 and pad[1] == "0", f"the live link has a padded box: {pad}"
    assert not re.search(r"\.livepill:hover\{[^}]*(?:border|background)", CSS)
    assert ".livepill[hidden]{display:inline-flex!important;visibility:hidden;}" in CSS
    chip = re.search(r'<a class="livepill"[^>]*>', HERO).group(0)
    assert "btn" not in chip


def test_the_sticky_bar_hides_while_the_pricing_cards_button_is_on_screen() -> None:
    """Review (low), reproduced at 390x844: with #season-cta scrolled to
    centre, the card's gold "Tell me when it opens" (top=339..382) and the
    sticky bar's identical button (top=780, class "stickybar show") were both
    on screen — the bar watched only the hero and the closer, and the card
    had become a real button in D4. The card's button is watched too
    (measured after: the bar hides while it is in view and returns once it
    leaves). Since Oct 30 2026 it watches the hero's action, not the hero: on a
    phone the report comes first, so the hero could fill the screen with no way
    to act in sight."""
    script = LANDING.split('const stickybar = document.getElementById("stickybar");')[1] \
        .split("\n}\n")[0]
    watched = re.search(r"const watched = \[(.*?)\]", script, re.S).group(1)
    assert 'document.querySelector(".hero")' not in watched
    for source in ('document.getElementById("watch-form")', 'document.getElementById("hero-open")',
                   'document.getElementById("season-cta")',
                   'document.querySelector(".closer")'):
        assert source in watched, f"the sticky bar no longer watches {source}"
    assert 'id="season-cta"' in BODY.split('id="pass-card"')[1].split('<p class="finance"')[0]


def test_every_storyline_layer_starts_and_ends_on_the_decided_report() -> None:
    """Replaces the parked-banner shadow test (Oct 24 2026): the banner is
    gone, and the storyline's promise is stronger — every layer's 0% and 100%
    stops ARE the resting page, so a pause, the loop's wrap, the end of the
    third loop (the class comes off at an iteration boundary) and a page whose
    script never runs all show the same decided report. The lock and the black
    are invisible at rest; everything drawn on the report is at full opacity
    and untransformed; the lock's text layer is gone by the end. Since the
    phone became the generated email (contract C11) the report layers are the
    scroll, card 01's bars and card 02's bar; the old peek layers are gone."""
    hidden_at_rest = ("st-lock",)
    on_report = ("st-view", "st-bar", "st-call")
    names = re.findall(r"@keyframes (st-[\w-]+)\{", CSS)
    assert {"st-lock", "st-fg", "st-note", "st-tap", "st-pad", *on_report} <= set(names)
    assert "st-dark" not in names, "the dip to black is back (sales review)"
    assert not {"st-flip", "st-if", "st-rise"} & set(names), "a retired peek layer is back"
    for name in names:
        stops = _keyframes(name)
        assert stops[0][0] == 0 and stops[-1][0] == 1, f"{name} has no 0% or 100% stop"
        for t, decl in (stops[0], stops[-1]):
            if name in hidden_at_rest:
                assert "opacity:0" in decl, f"{name} is visible at {t:.0%}"
            elif name in on_report:
                assert "transform:none" in decl and "opacity:0" not in decl, (name, t, decl)
    assert "opacity:0" in _keyframes("st-fg")[-1][1]
    # Without .story the layers themselves are invisible.
    assert re.search(r"\n  \.lock\{[^}]*opacity:0", CSS)
    assert re.search(r"\.lk-tap\{[^}]*opacity:0", CSS)


def test_the_phone_nav_has_room_at_320() -> None:
    """Review (low), measured at 320x800: the lockup (19px below 430) ended at
    x=187 and "See a real report" began at 190 — 3px. Below 360px the lockup
    is 17px (after: brand 22..170, link 190..298, no sideways scroll)."""
    narrow = _block(CSS, "@media (max-width:360px)")
    assert re.search(r"\.brand\{font-size:(\d+)px;\}", narrow).group(1) == "17"


def test_the_share_preview_is_a_short_benefit_line_not_the_entity_sentence() -> None:
    """M12: og:description was the 70-word, gate-qualified entity sentence,
    so a link pasted in a group chat unfurled with fine print under the title
    (and twitter:description, absent, fell back to it). PLAN §1's entity
    sentence lives on in the meta description and the JSON-LD, its named
    surfaces; the share preview is ~25 words of what the report does — no
    odds (which would owe the gate), no price, nothing it cannot keep."""
    og = re.search(r'<meta property="og:description" content="([^"]+)">', LANDING).group(1)
    tw = re.search(r'<meta name="twitter:description" content="([^"]+)">', LANDING).group(1)
    meta = re.search(r'<meta name="description" content="([^"]+)">', LANDING).group(1)
    assert og == tw
    assert og != meta and meta.startswith("Beat Your League is a weekly start/sit report")
    words = len(og.split())
    assert 15 <= words <= 30, f"the share preview is {words} words"
    for banned in (r"\bodds\b", r"\$", r"\bfile\b", r"calibrat|proven|accurate|tested",
                   r"\bbet", r"\bwin more\b"):
        assert not re.search(banned, og, re.I), banned
    for promise in ("Tuesday", "exact roster", "no login"):
        assert promise in og, promise


def test_a_printout_shows_every_section_and_every_bar() -> None:
    """QA-06, reproduced with headless Chrome --print-to-pdf: the pages
    holding the section heads, the real-report rows, pricing, the FAQ and the
    closer printed as blank navy (.reveal is opacity:0 until a scroll that a
    printout never makes, with no failsafe), and the report cards' bars
    printed empty (the motion zeroed them). The page's report cards are now
    generated and drawn at rest — no script zeroes a bar outside the phone's
    storyline, which print stops — so the print rule shows everything the
    script holds back, stops the phone's animation and drops the fixed bars,
    and the rise observer keeps its failsafe (one that only distrusts an
    observer that never reported, so sections still rise as they are
    scrolled to)."""
    printed = _block(CSS, "@media print")
    for held in (".js .reveal", ".js .stagger > *", ".phone .screen *"):
        assert held in printed, f"{held} can still print invisible"
    assert "opacity:1!important" in printed and ".stickybar" in printed
    assert "animation:none!important" in printed
    assert ".anim" not in CSS and "data-w=" not in BODY, "a script-zeroed bar is back"
    rise = LANDING.split("const rise = new IntersectionObserver")[1].split("\n}\n")[0]
    assert "heard = true" in rise
    assert re.search(r"setTimeout\(\(\) => \{ if \(!heard\) parts\.forEach\(\(el\) => "
                     r"el\.classList\.add\(\"shown\"\)\); \}, 6000\)", rise)


def test_a_phone_has_a_route_to_the_price() -> None:
    """M13 (phone half): below 600px the nav carries the lockup and one link
    (contract C2), so a phone had no route to the price, about 4,700px down.
    The hero's button row and the closer each carry a small "See pricing"
    text link to #pricing, shown only below 600px (measured at 390: beside
    "See a real report" and "or read a real report first"; at 1440 hidden,
    where the nav's Pricing shows). A text link, never a third button, and no
    price figure in the hero."""
    closer = BODY.split('<section class="closer">')[1].split("</section>")[0]
    for where, block in (("hero", HERO), ("closer", closer)):
        assert re.search(r'<a class="textlink onlysm" href="#pricing">See pricing</a>', block), where
    assert ".cta-row .onlysm{display:none;}" in CSS
    assert ".cta-row .onlysm{display:inline-block;}" in _block(CSS, "@media (max-width:599px)")
    assert "$" not in _flat(HERO)


def test_a_waitlist_signup_is_counted_once_it_is_accepted() -> None:
    """Routed from the analytics branch (contract C1): the landing's capture
    counts a waitlist signup only after the form accepted it — after the
    success note, never on a refusal — through the guarded call the page
    counter defines (window.bylCount, absent until count.js loads)."""
    handler = LANDING.split('watchForm.addEventListener("submit"')[1].split("\n  });")[0]
    ok = handler.index("You're on the list.")
    call = handler.index('if (window.bylCount) window.bylCount("waitlist", "closed");')
    assert ok < call < handler.index("} catch (err)")
    assert LANDING.count('window.bylCount("waitlist"') == 1


def test_the_share_card_sets_the_name_as_the_logo() -> None:
    """D10, og half: the share card set the name like the old nav — tracked
    gold caps, upright (letter-spacing:.2em, #F2C230) — rather than as the
    logo lockup the landing now carries: heavy italic, "Beat Your" in paper
    and "League" in the logo's gold. site/og.png is rebuilt from this by
    `make og` (test_og's digest test holds the image to it)."""
    from render import og

    built = og.build_html(LANDING)
    assert '<span>Beat Your <span class="lg">League</span></span>' in built
    rule = re.search(r"\.mark span\{([^}]*)\}", built).group(1)
    assert "font-style:italic" in rule and "letter-spacing:.01em" in rule \
        and "color:#F6F4EE" in rule and ".2em" not in rule
    assert ".mark span .lg{color:#F0B62A;}" in built
