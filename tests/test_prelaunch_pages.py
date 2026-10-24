"""Pre-launch review (Oct 23 2026), the pages' half: contract C2's one design
system across the hand-written pages and the samples' chrome (D3, D5, D10,
D14, D15, D18), every published sample's way out and ask (D1, M7, QA-01,
F8/P7), How it works pictured (D8), the thank-you page's next steps (M9),
the posts' link in their first reply (M8), the day-one line (QA-03), the
address read back before checkout (critique #1), the retired projections
study (critique #4) and titles that say what the site is (critique #8).

Each test's docstring is the reproduction it guards against."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

import render.live_sample as live
import render.report as rr
from test_site import (JOIN, SAMPLE_REPORT, THANKS, _js_code, _js_function, _node,
                       _style, markup_only, prose)

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
HOW = (SITE / "how-it-works.html").read_text(encoding="utf-8")
LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")
CONFIRM = (SITE / "join" / "confirm.html").read_text(encoding="utf-8")
PROJECTIONS = (SITE / "projections.html").read_text(encoding="utf-8")

SAMPLES = ("sample-report.html", "sample-first-week.html", "this-week.html")
RESTAMP = ("python -m render.live_sample --restamp site/this-week.html "
           "site/sample-report.html site/sample-first-week.html")

# Every hand-written page this pass put on the one nav: (prefix, lockup href,
# the route the page is).
NAV_PAGES = {
    "how-it-works.html": ("", None, "how-it-works.html"),
    "thanks.html": ("", None, None),
    "404.html": ("/", "/", None),
    "league-pass.html": ("", None, None),
    "join/index.html": ("../", None, None),
    "join/confirm.html": ("../", None, None),
    "projections.html": ("", None, None),
    "compare/index.html": ("../", None, None),
}


def _page(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------- #
# D1 / M7 / QA-01 / F8 — a published sample's way out and ask
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("name", SAMPLES)
def test_every_published_sample_carries_the_way_out_and_the_ask_the_site_sells(
        name: str) -> None:
    """D1 / M7 / QA-01 / F8, reproduced: this-week.html — linked from the
    hero — was built by the Oct 20 cron from code older than the one-time
    passes (6ca7be2 is not an ancestor of 22c1ebf) and merged into HEAD in
    bc59beb. It told a buyer of a one-payment pass to "Cancel it yourself from
    your own billing page … Reports continue to the end of the period you've
    already paid for", and both its asks went into the closed join page. No
    test read a committed sample's chrome, and 69 launch-check gates passed.
    Every committed sample's footer way out and buy buttons must be what
    render.report gives a published sample today; a stale page is fixed
    without moving a number by `python -m render.live_sample --restamp`."""
    page = _page(name)
    footer = page.split("<footer>", 1)[1].split("</footer>", 1)[0]
    way_out = rr.cancel_html(rr.stop_route({"anonymized_demo": True}), sample=True)
    assert way_out in footer, f"{name}'s footer way out is not today's — run {RESTAMP}"
    if rr.SELLING_ONE_TIME:
        for subscription in ("billing page", "does not stop a subscription",
                             "the period you&#x27;ve already paid for"):
            assert subscription not in page, f"{name} describes a subscription: {subscription!r}"
    asks = re.findall(r'<a class="btn[^"]*" href="[^"]*">[^<]*</a>', markup_only(page))
    assert len(asks) == 2, f"{name}: the sample's ask, top and bottom, went missing"
    assert set(asks) == {rr.sample_cta()}, f"{name}'s asks are not today's — run {RESTAMP}"
    if not rr.checkout_open():
        assert 'href="join/' not in markup_only(page), f"{name} sends buyers into a closed checkout"


@pytest.mark.parametrize("name", SAMPLES)
def test_every_published_sample_carries_the_sites_nav_and_day_one_line(name: str) -> None:
    """Contract C2 on the samples: the lockup and the site's routes, no Home
    pill — and the closing card's promise is today's (QA-03), never the
    either/or "lands the day you join: this week's lineup, or your roster
    report if …" sentence, nor "scored your league's way" (INFO-113)."""
    page = _page(name)
    assert rr.site_bar(uid="bylm") in page, f"{name}'s nav is not the site's — run {RESTAMP}"
    assert 'class="home"' not in page
    card = page.split('<div class="ctacard"><p>', 1)[1].split("</p>", 1)[0]
    assert rr.esc(rr.JOIN_PROMISE) in card, f"{name}'s closing promise is stale — run {RESTAMP}"
    assert "league&#x27;s way" not in page and "league's way" not in page


OLD_CHROME = """<!DOCTYPE html><html><head><title>Beat Your League — 2026 Week 7 Report</title>
<meta name="description" content="Week 7 of the 2026 NFL season, for a sample roster: the lineup we&#x27;d set, with odds on 3 of its 9 slots. Rebuilt every Tuesday of the season.">
<style>.x{}</style></head><body><div class="report">
<header class="bug"><div class="sitebar"><a class="brand" href="index.html"><span>Beat Your League</span></a><nav class="sitenav" aria-label="Site"><a href="how-it-works.html">How it works</a><a href="index.html#pricing">Pricing</a><a class="home" href="index.html">← Home</a></nav></div><h1>Week 7 · Your Report</h1><p class="headcta"><a class="btn" href="join/index.html">Get this for your team</a></p></header>
<section><div class="v">Brock Purdy 21.5 · Zay Flowers 15.6 · 81% · 76 – 134</div></section>
<div class="ctacard"><p>This is this week's report for a sample roster. Yours is built from your own roster, scored your league's way, and your first report lands the day you join.</p><a class="btn" href="join/index.html">Get this for your team</a></div>
<footer><b>Beat Your League</b> — x.<br>NFL data: nflverse (nflverse-data), CC-BY-4.0. Aggregated and scored to your league&#x27;s settings by us. Not affiliated with the NFL.<br><b>Done with this?</b> Cancel it yourself from your own billing page — press Cancel. Reports continue to the end of the period you&#x27;ve already paid for, then stop. <a href="terms.html#cancel">the exact steps, on our terms page</a>.</footer>
</div></body></html>"""


def test_the_restamp_changes_the_chrome_and_moves_no_number() -> None:
    """The fix for a stale published sample may not be a rebuild: after
    kickoff a --force rebuild drops every odds whose game has started, and a
    pre-kickoff --no-record rebuild printed Zay Flowers at 77% beside the 81%
    the ledger holds (QA-01's verifier). The restamp rewrites the nav, both
    asks, the closing promise, the footer's way out, its data line, the title
    and the odds-count preview — and nothing else: every figure on the page
    survives it, and it is idempotent."""
    out = live.restamp_chrome(OLD_CHROME)
    figures = lambda page: re.findall(r"\d+\.\d|\d+%|\d+ – \d+", page.split("<section>")[1]
                                      .split("</section>")[0])
    assert figures(out) == figures(OLD_CHROME) == ["21.5", "15.6", "81%", "76 – 134"]
    assert rr.site_bar(uid="bylm") in out and 'class="home"' not in out
    assert out.count(rr.sample_cta()) == 2
    assert rr.esc(rr.JOIN_PROMISE) in out and "league's way" not in out
    assert rr.cancel_html(rr.stop_route({"anonymized_demo": True}), sample=True) in out
    assert "billing page" not in out and "to your league&#x27;s settings" not in out
    assert "<title>Beat Your League — sample fantasy football report, 2026 Week 7</title>" in out
    assert "odds on 3" not in out and "every slot decided" in out
    assert live.restamp_chrome(out) == out, "a second restamp changed the page"


def test_the_share_preview_says_what_the_report_holds_never_an_odds_count() -> None:
    """M7, reproduced: this-week.html's description and og:description read
    "the lineup we'd set, with odds on 3 of its 9 slots" — a preview that
    advertises the six slots WITHOUT a number to somebody who has not opened
    the page. It says what the report does, and only what this week's report
    actually carries."""
    base = {"meta": {"week": 7, "season": "2026"}, "lineup": [{"confidence": 0.61}] * 3}
    _title, bare = live.share_text({**base, "regret": {"gate": "x"}, "checklist": []})
    assert "every slot decided." in bare and "odds on" not in bare
    assert "closest call" not in bare and "can't play" not in bare and "byes" not in bare
    full = {**base, "regret": {"confidence": 0.61},
            "checklist": [{"action": "Bench A and B — they can't play this week"},
                          {"action": "Byes ahead: Week 9 leaves your K spot empty"}]}
    assert live.share_text(full)[1] == (
        "Week 7 of the 2026 NFL season, for a sample roster: every slot decided, the "
        "week's closest call, who can't play and byes ahead. Rebuilt every Tuesday of "
        "the season.")


def test_the_day_one_line_is_true_every_day_of_the_week() -> None:
    """QA-03: the price card promised "the first [weekly report] usually
    within the hour of joining" while from Thursday's kickoff to Tuesday the
    first WEEKLY report is Tuesday's. The first report of any kind does come
    within the hour (the roster report or the week's, run/intake._first_file),
    so that is what the samples' closing card says — usually, because the
    intake runs hourly — and it no longer spells out the either/or."""
    assert "Your first report usually lands within the hour of joining" in rr.JOIN_PROMISE
    assert "the day you join:" not in rr.JOIN_PROMISE
    assert "full PPR, half PPR or standard" in rr.JOIN_PROMISE


# --------------------------------------------------------------------- #
# C2 / D5 / D10 — one nav, the logo lockup
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("name", sorted(NAV_PAGES))
def test_every_page_carries_the_one_nav_with_its_one_stylesheet(name: str) -> None:
    """D5 / D10, reproduced at 390px: how-it-works, thanks and 404 drew the
    brand, then "How it works · Real report · Pricing", then "← Home" alone on
    a third row; join, confirm, projections and compare had the brand and a
    pill only; and every page's wordmark was 15px tracked caps — the eyebrow
    labels' style — not the logo (italic 900, "BEAT YOUR" paper, "LEAGUE"
    gold). Each page carried its own copy of the nav CSS, so they drifted.
    Now every page's nav is render.report.site_bar() verbatim and its style
    carries SITE_BAR_CSS verbatim (mutation: edit one rule on one page)."""
    prefix, home, current = NAV_PAGES[name]
    page = _page(name)
    assert rr.site_bar(prefix, home=home, current=current) in page, f"{name}: not the site's nav"
    assert rr.SITE_BAR_CSS in _style(page), f"{name}: its nav CSS drifted from SITE_BAR_CSS"
    assert 'class="home"' not in page and "← Home" not in markup_only(page)
    top = page.split("<body", 1)[1].split("<h1", 1)[0]
    assert 'class="sitebar"' in top, f"{name}: the nav is not above the headline"


def test_the_samples_template_carries_the_same_nav_stylesheet() -> None:
    template = rr.TEMPLATE_PATH.read_text(encoding="utf-8")
    assert rr.SITE_BAR_CSS in template
    assert ".sitenav a.home" not in template


def test_the_nav_is_the_lockup_and_on_a_phone_one_link() -> None:
    """C2: the nav is the official lockup (mark, "Beat Your" + "League" in the
    logo's gold, Barlow Condensed 900 italic — render/brand.py logo_html) and,
    on a phone, the lockup plus ONE link, "See a real report". Pricing goes to
    the landing's #pricing."""
    bar = rr.site_bar()
    assert '<span>Beat Your <span class="lg">League</span></span>' in bar
    links = re.findall(r"<a([^>]*)>([^<]*)</a>", bar.split('<nav class="sitenav"')[1])
    assert [label for _a, label in links] == ["How it works", "See a real report", "Pricing"]
    shown = [label for attrs, label in links if "hidesm" not in attrs]
    assert shown == ["See a real report"], "a phone shows more than the lockup and one link"
    assert 'href="index.html#pricing">Pricing' in bar
    css = rr.SITE_BAR_CSS
    assert "font-weight:900;font-style:italic" in css and ".sitebar .brand .lg{color:#F0B62A;}" in css
    assert "@media (max-width:599px){.sitenav .hidesm{display:none;}" in css
    assert "flex-wrap:nowrap" in css.split(".sitenav{", 1)[1].split("}", 1)[0]


# --------------------------------------------------------------------- #
# C2 / D3 / D4 / D9 / D14 / D15 — buttons, cards, the closed state
# --------------------------------------------------------------------- #

def test_no_green_call_to_action_and_no_dashed_placeholder() -> None:
    """D3 / D4 / C2, reproduced: join's "Check my roster" was the one green
    CTA on the site (button{background:var(--turf)}), a dead .checkout rule
    sat beside it, and the closed checkout — on join and League Pass alike —
    was a dashed "opens soon" box that read as a wireframe. Primary buttons
    are the site's gold; the closed state is a real button."""
    css = _style(JOIN)
    rule = re.search(r"\n  button\{([^}]*)\}", css).group(1)
    assert "--turf" not in rule and "--flag" in rule
    assert ".checkout{" not in css
    closed = css.split("#submit.is-closed{", 1)[1].split("}", 1)[0]
    assert "dashed" not in closed and "border:2px solid var(--navy)" in closed
    lp_css = _style(LEAGUE_PASS)
    assert ".soon" not in LEAGUE_PASS and "dashed #C9C3B4" not in lp_css


def test_every_closed_league_pass_ask_is_a_real_button_and_the_page_ends_on_one() -> None:
    """D18, reproduced at 1440: the page ended on "Fair play" and the footer
    with no closing action, its one ask was the dashed box, and the group-chat
    placeholder "[your league's link, from your welcome email]" rendered as
    gold bracketed text — a link that had failed to load. Both asks are gold
    buttons to the landing's capture while checkout is closed, the closer sits
    last in <main> with the price beside its one-payment and refund terms, and
    the placeholder is drawn as a blank to fill in."""
    slots = re.findall(r'<div class="ctaslot"[^>]*data-lp-cta>(.*?)</div>', LEAGUE_PASS, re.S)
    assert len(slots) == 2
    for slot in slots:
        assert re.match(r'<a class="btn gold" href="index\.html#watch-form">Tell\s+me when it opens</a>',
                        slot)
    main = LEAGUE_PASS.split('<main id="main">')[1].split("</main>")[0]
    closer = main.rsplit('<div class="closer">', 1)[1]
    assert main.rstrip().endswith("</div>") and "data-lp-cta" in closer
    words = prose(re.sub(r"<[^>]+>", " ", closer))
    assert "$69" in words and "one payment, nothing renews" in words and "refund" in words
    blank = _style(LEAGUE_PASS).split(".chatline .blank{", 1)[1].split("}", 1)[0]
    assert "border:1px dashed" in blank and "background:" in blank
    code = _js_code(LEAGUE_PASS)
    assert 'querySelectorAll("[data-lp-cta]")' in code
    assert code.count('className = "btn gold"') == 2, "an opened ask is not the gold button"


@pytest.mark.parametrize("name", ["404.html", "how-it-works.html", "projections.html",
                                  "compare/index.html"])
def test_page_buttons_are_the_two_c2_styles(name: str) -> None:
    """D3: the 404's primary was a flat gold rectangle and its other routes
    plain outlines, How it works styled bare anchors, and the evidence pages
    drew their secondary button with an inline style. Every button is
    .btn.gold or .btn.ghost, and Pricing/cost goes to index.html#pricing."""
    page = markup_only(_page(name))
    buttons = re.findall(r'<a class="(btn[^"]*)"', page)
    assert buttons and set(buttons) <= {"btn gold", "btn ghost"}, buttons
    assert 'style="background:none' not in page
    assert not re.search(r'href="(?:\.\./)?index\.html">What it costs', page)


def test_the_confirm_button_is_the_sites_primary() -> None:
    """D3, reproduced (shots/confirm390.png): join/confirm.html's button was a
    6px-rounded pale pill in sentence-case body type, the only button on the
    site in its own style."""
    rule = _style(CONFIRM).split("\n  button{", 1)[1].split("}", 1)[0]
    assert "var(--display)" in rule or "Barlow Condensed" in rule
    assert "text-transform:uppercase" in rule and "border-radius:0" in rule
    assert "border-radius:6px" not in rule


def test_cards_are_square_and_only_what_you_can_press_moves() -> None:
    """C2 / D9: the join page and its sidebar were the only rounded cards on
    the paper pages, and a hover that lifts something you cannot press
    promises a click that does nothing."""
    css = _style(JOIN)
    for card in (".page{", ".side{"):
        rules = [r.split("}", 1)[0] for r in css.split(card)[1:]]
        assert all("border-radius:4px" not in r for r in rules), card
    for name in NAV_PAGES:
        for selector, body in re.findall(r"([^{}]+):hover[^{]*\{([^}]*)\}", _style(_page(name))):
            if "transform:translate" in body:
                assert re.search(r"\bbutton\b|(?<![\w.#-])a(?![\w-])|\.btn\b|\.cardbtn\b",
                                 selector), (name, selector)


def test_a_phone_shows_the_page_not_a_sheet_on_a_desk() -> None:
    """D15, reproduced (shots/hiw390-t0.png, thanks390, 404390, confirm390):
    at 390px the paper pages kept an 8px beige margin and a drop shadow around
    the card, and join ended in a grey shadow smear under its sidebar."""
    rule = "@media (max-width:480px){body{padding:0;background:var(--paper);}.sheet{border:0;box-shadow:none;}}"
    for name in ("how-it-works.html", "thanks.html", "404.html", "join/confirm.html"):
        assert rule in _style(_page(name)), name
    assert ".side{position:static;box-shadow:none;}" in _style(JOIN)


def test_the_checked_roster_has_quiet_remove_controls_and_step_three_says_it_once() -> None:
    """D14, reproduced (shots/joinstep3-1440.png): fifteen bordered uppercase
    REMOVE buttons dominated a checked roster; step 3 read "3 · WHERE DO
    REPORTS GO?" and then the label "WHERE REPORTS GO"; and the sidebar's
    "Your team." was the one sentence-case display heading on the site. Each
    row's control is a quiet × named for its player, the step heading names
    the step (as the progress bar does) and the label names the field."""
    draw = _js_function(JOIN, "draw")
    assert 'drop.textContent = "×";' in draw and 'drop.textContent = "remove"' not in draw
    assert 'drop.setAttribute("aria-label", "Remove " +' in draw
    drop = _style(JOIN).split(".row .fix button.drop{", 1)[1].split("}", 1)[0]
    assert "border:0" in drop and "width:32px" in drop
    head = re.search(r'<div class="eyebrow" id="step3-head">([^<]*)</div>', JOIN).group(1)
    label = re.search(r'<label class="optlabel" id="lbl-email" for="email">([^<]*)</label>',
                      JOIN).group(1)
    assert head == "3 · Checkout" and "report" not in head.lower()
    assert '$("step3-head").textContent = stepLabel;' in _js_function(JOIN, "nothingToPay")
    assert label == "Where reports go"
    proof = _style(JOIN).split(".side .proof b{", 1)[1].split("}", 1)[0]
    assert "text-transform:uppercase" in proof


# --------------------------------------------------------------------- #
# critique #1 — the address, read back before Stripe locks it
# --------------------------------------------------------------------- #

def test_a_common_domain_typo_is_suggested_never_silently_changed() -> None:
    """Critique #1, reproduced: the address went straight into Stripe as
    locked_prefilled_email, nothing read it back and nothing caught
    "gmial.com" — a paid pass and an empty inbox, found by nobody (no code
    reads bounces). The page suggests the fix; it never rewrites an address
    on its own. Run under node."""
    fn = _js_function(JOIN, "suggestedEmail")
    table = JOIN[JOIN.index("const DOMAIN_FIXES = {"):]
    table = table[:table.index("};") + 2]
    got = _node(table + "\n" + fn + "\nconsole.log(JSON.stringify(["
                "'pat@gmial.com','pat@Gmail.Co','pat@hotmial.com','pat@yahoo.con',"
                "'pat@gmail.com','pat@example.com','pat@gmail.co.uk','nope'].map(suggestedEmail)));")
    assert got == ["pat@gmail.com", "pat@gmail.com", "pat@hotmail.com", "pat@yahoo.com",
                   "", "", "", ""]


def test_checkout_waits_for_the_address_to_be_read_back() -> None:
    """Critique #1: before the page leaves for Stripe it shows "Reports go to
    <address> — right?" with Edit beside the yes, and the yes is the only way
    on. The hand-off is one function, reached from the handler only once the
    address on screen is the one read back, and from the yes; the read-back
    is filled as text. A seat claim never meets it (the WORKER's path)."""
    handler = JOIN.split('$("form-email").addEventListener("submit"')[1].split("\n});")[0]
    assert "if (state.confirmedEmail !== email) {\n    askAboutEmail(email," in handler
    assert handler.index("askAboutEmail(email, {") < handler.index("leaveForCheckout(link, tagged, email)")
    assert handler.index("if (SEAT_MODE) {") < handler.index("typoSettled(email)")
    assert JOIN.count("window.location.assign(") == 1
    leave = _js_function(JOIN, "leaveForCheckout")
    assert "window.location.assign(" in leave and "locked_prefilled_email" in leave
    yes = JOIN.split('$("check-yes").addEventListener("click"')[1].split("\n});")[0]
    assert "go.email === email" in yes and "leaveForCheckout(go.link, go.tagged, go.email)" in yes
    box = re.search(r'<div class="checkmail" id="check-email"[^>]*hidden>(.*?)\n      </div>',
                    JOIN, re.S).group(1)
    assert "Reports go to" in box and "— right?" in box and 'id="check-edit">Edit<' in box
    ask = _js_function(JOIN, "askAboutEmail")
    assert ".innerHTML" not in ask and '$("check-address").textContent = email;' in ask
    probe = (ROOT / "run" / "launch_browser.mjs").read_text(encoding="utf-8")
    assert 'getElementById("check-yes")' in probe, "the launch check no longer answers the read-back"


# --------------------------------------------------------------------- #
# D8 — How it works, pictured with the report itself
# --------------------------------------------------------------------- #

def test_how_it_works_pictures_the_report_with_the_samples_own_rows() -> None:
    """D8, reproduced (shots/hiw1440-t0..t2): seven numbered text sections, a
    ten-term glossary and no picture of the report it explains, numbered "1."
    while the report and landing say "01". Each glossary group now sits beside
    the real component, every figure on those cards is one the published
    sample prints (the landing's own guard, on this page — mutation: change
    16.9 to 17.9), and each odds bar starts at 50% as the report draws it."""
    cards = re.findall(r'<div class="filecard[^"]*" data-real="[^"]+">(.*?)<!--/card-->', HOW, re.S)
    assert len(cards) >= 4, "How it works lost its pictures of the report"
    flat_sample = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", SAMPLE_REPORT)))
    for card in cards:
        body = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<!--.*?-->", " ", card, flags=re.S)))
        figures = set(re.findall(r"\d+\.\d+|\d+%|\d+ – \d+", body))
        assert figures, "a sample card with no figures"
        for figure in sorted(figures):
            assert figure in flat_sample, f"How it works quotes {figure!r}, which the sample never printed"
        for name in re.findall(r"<b>([A-Z][^<]+)</b>", card):
            assert name in flat_sample, f"{name!r} is not a row of the sample"
        for pct, width in re.findall(r'<span class="pct">(\d+)%</span><span class="cbar">'
                                     r'<i style="width:(\d+)%">', card):
            assert int(width) == (int(pct) - 50) * 2, "the bar is not drawn from 50%"
        # Row by row, not figure by figure: a figure that happens to appear
        # elsewhere in the sample ("17.9 a game") must not pass for the row's.
        for row in re.findall(r'<div class="frow">(.*?)</div>', card):
            name = re.search(r"<b>([^<]+)</b>", row).group(1)
            proj = re.search(r'<span class="proj">([^<]+)</span>', row).group(1)
            call = html.unescape(re.sub(r"<[^>]+>", " ", row.split('class="call">', 1)[1]))
            call = re.sub(r"\s+", " ", call).strip()
            assert re.search(re.escape(html.unescape(name)) + r".{0,420}?" + re.escape(proj)
                             + r" " + re.escape(call), flat_sample), \
                f"{name}'s row ({proj}, {call}) is not the sample's"
    assert '<span class="n">01</span>What you get, and when</h2>' in HOW
    assert not re.search(r"<h2[^>]*>\d\. ", HOW), "a section still numbers itself 1."
    links = _style(HOW).split("main a,p a,li a{", 1)[1].split("}", 1)[0]
    assert "color:var(--navy)" in links


# --------------------------------------------------------------------- #
# M9 — after paying, the next steps
# --------------------------------------------------------------------- #

def test_the_thank_you_page_gives_a_buyer_their_next_steps() -> None:
    """M9, reproduced: an individual buyer's thank-you page named no sender
    to add to contacts, never mentioned the League Pass for the league they
    may run, and offered no way to tell anyone (the share existed only on the
    pass view). Three steps now: the sender (LAUNCH.md's EMAIL_FROM, so the
    two cannot drift), the League Pass with its price beside its terms and the
    refund-on-request switch the pass FAQ describes, and a share aimed at a
    manager in ANOTHER league, tagged ?via=friend. Hidden on the pass view and
    once the season is over."""
    block = THANKS.split('<div class="nextsteps" id="next-steps">')[1].split("\n    </div>")[0]
    launch = (ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    sender = re.search(r"`EMAIL_FROM` \| `Beat Your League <([^>]+)>`", launch).group(1)
    assert f"<b>{sender}</b>" in block
    assert 'href="league-pass.html"' in block
    words = prose(re.sub(r"<[^>]+>", " ", block))
    assert "$69 for the whole league, one payment, nothing renews" in words and "refund" in words
    assert "reply to any report while your own pass's refund window is open" in words
    friend = block.split("Know a manager in another league?")[1]
    assert "https://beatyourleague.com/?via=friend" in friend and "your league" not in friend
    code = _js_code(THANKS)
    passed = code.split('get("plan") === "pass") {')[1].split("\n}")[0]
    assert 'getElementById("next-steps").hidden = true' in passed
    assert code.count('getElementById("next-steps").hidden = true') == 2, "not hidden once over"
    assert "[hidden]{display:none!important;}" in _style(THANKS), \
        "a display:grid block ignores the hidden attribute without it"


# --------------------------------------------------------------------- #
# M8 — the posts: the link in the first reply, a card to attach
# --------------------------------------------------------------------- #

def test_the_drafted_posts_carry_no_link_and_name_the_card_to_attach() -> None:
    """M8, reproduced: content/this-week.md's posts each ended with the
    this-week.html link and carried no image. The post goes up with no link;
    the link is its first reply; each names the report card to screenshot —
    by the heading the report itself prints over it."""
    from run import drops
    from test_drops import _report
    posts = drops.drafts(_report())
    assert posts
    for post in posts:
        assert "http" not in post["text"] and "this-week.html" in post["reply"]
        assert post["card"] in drops.CARDS.values()
    source = (ROOT / "render" / "report.py").read_text(encoding="utf-8")
    for heading in drops.CARDS.values():
        assert f'_section("{heading}"' in source or f'RISING_HEAD = "{heading}"' in source, heading
    page = drops.render(_report(), posts)
    assert page.count("First reply: ") == len(posts) == page.count("Attach: a screenshot of")
    assert "that is where the link goes" in page


# --------------------------------------------------------------------- #
# critique #4, #8 — the retired study, and titles that say what this is
# --------------------------------------------------------------------- #

def test_the_retired_projections_study_says_so_before_anything_else() -> None:
    """Critique #4: site/projections.html — "Sleeper's free projections beat
    our own numbers, 68.8% to 64.4%" — measures the retired 2018 Sleeper-era
    model, and robots.txt lets every crawler read it, noindex or not. The tests
    pin its content (the unflattering half leads), so it stays published and
    unedited, under a masthead saying it describes nothing in today's reports."""
    top = PROJECTIONS.split("<h1", 1)[0]
    assert '<div class="retired" role="note"><b>Retired study.</b>' in top
    assert "no longer runs" in top and "Nothing below describes them" in prose(top)
    title = re.search(r"<title>([^<]+)</title>", PROJECTIONS).group(1)
    assert title.startswith("Retired 2018 study")
    for tag in ("description", "og:title", "og:description"):
        value = re.search(rf'(?:name|property)="{tag}" content="([^"]+)"', PROJECTIONS).group(1)
        assert "etired" in value, tag
    assert '<meta name="robots" content="noindex">' in PROJECTIONS
    assert 'href="join/' not in markup_only(PROJECTIONS), "a retired study sells into checkout"


@pytest.mark.parametrize("name", ["how-it-works.html", "league-pass.html", "join/index.html",
                                  "compare/index.html", "projections.html"])
def test_every_title_says_fantasy_football(name: str) -> None:
    """Critique #8: no page's <title> said "fantasy football" — not the
    explainer, the League Pass, the join page or the samples — so a search
    result or a shared tab did not say what the site is about."""
    page = _page(name)
    title = re.search(r"<title>([^<]+)</title>", page).group(1)
    assert "fantasy football" in title.lower(), title
    og = re.search(r'property="og:title" content="([^"]+)"', page)
    if og and name not in ("compare/index.html", "projections.html"):
        assert og.group(1) == title or "fantasy football" in og.group(1).lower()


def test_a_published_sample_is_titled_as_a_fantasy_football_report() -> None:
    import render.sample as sample
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    page = sample.page(report)
    assert "<title>Beat Your League — sample fantasy football report, 2024 Week 10</title>" in page
    subscriber = {**report, "meta": {k: v for k, v in report["meta"].items()
                                     if k not in ("anonymized_demo", "historical_demo")}}
    assert "<title>Beat Your League — 2024 Week 10 Report</title>" in rr.render(
        subscriber, rr.TEMPLATE_PATH.read_text(encoding="utf-8"))
