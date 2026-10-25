"""The landing tells the truth about the product it sells (Oct 25 2026).

The hero phone used to be a hand-written one-screen summary that read better
than the email a subscriber receives and quoted it only in part, so the page
sold one design and the inbox delivered another. Now the phone and the page's
real-report cards are GENERATED from the pinned 2024 Week 10 sample
(render/phone.py, run by `make sample`) with the report's own model
(render/anatomy.py) and markup (render.report.card_html): the email sets the
content, the phone is a faithful copy of its first screens. Every test here
states what it guards; the browser half (the phone's first screen at 390 and
320, no sideways scroll, LCP/CLS, axe) was measured in headless Chrome with
device emulation when this landed.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

from test_site import LANDING, SITE, _style, markup_only

ROOT = SITE.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sample-report-w10.json"
CSS = _style(LANDING)
BODY = re.sub(r"<!--(?!/card| ?[\w-]+:(?:start|end) ?).*?-->", "", markup_only(LANDING),
              flags=re.S)


def _sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _squash(fragment: str) -> str:
    """Text as a reader meets it, with whitespace removed entirely: markup
    may break lines anywhere, the words and figures may not differ."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", "", text)


# --------------------------------------------------------------------- #
# the generated blocks are what the generator makes from the fixture
# --------------------------------------------------------------------- #

def test_the_fixture_is_the_pinned_sample() -> None:
    """The fixture `make sample` writes is the report the phone is built
    from: the 2024 Week 10 sample, solo, 12 teams, full PPR — a stale or
    hand-edited fixture would let a page drift from the published sample
    while every generated block still matched it."""
    report = _sample()
    meta = report["meta"]
    assert (meta["season"], meta["week"], meta["num_teams"]) == ("2024", 10, 12)
    assert meta["solo"] and meta["historical_demo"] and meta["scoring"] == "Full PPR"
    flat = html.unescape(re.sub(r"<[^>]+>", " ", (SITE / "sample-report.html")
                                .read_text(encoding="utf-8")))
    for slot in report["lineup"]:
        assert slot["player_name"] in flat, slot["player_name"]


def test_every_generated_block_on_the_landing_is_current() -> None:
    """Staleness, contract B7: the landing's phone and its "What lands in
    your inbox" cards are rebuilt from the committed fixture and must equal
    what the page carries between their markers. A page edited by hand, or a
    sample rebuilt without re-injecting, fails here rather than drifting."""
    from render import phone
    report = _sample()
    for name, want in phone.landing_blocks(report).items():
        assert phone.block(LANDING, name) == want.strip(), (
            f"site/index.html's {name} block is stale — run `make sample`")


def test_every_generated_block_on_how_it_works_is_current() -> None:
    """Staleness, contract B7: How it works annotates cards 01–05 of the same
    sample, generated the same way, between markers the page places."""
    from render import phone
    how = (SITE / "how-it-works.html").read_text(encoding="utf-8")
    for name, want in phone.hiw_cards(_sample()).items():
        assert phone.block(how, name) == want.strip(), (
            f"site/how-it-works.html's {name} block is stale — run `make sample`")


def test_injection_refuses_a_page_without_its_markers(tmp_path: Path) -> None:
    """A page that lost its markers would otherwise keep its stale copy
    forever, so injecting into one RAISES — `make sample` fails loudly."""
    from render import phone
    page = tmp_path / "page.html"
    page.write_text("<p>no markers here</p>", encoding="utf-8")
    with pytest.raises(ValueError):
        phone.inject(page, "phone", "<b>x</b>")
    page.write_text("<!-- phone:start -->old<!-- phone:end -->", encoding="utf-8")
    phone.inject(page, "phone", "<b>new</b>")
    assert phone.block(page.read_text(encoding="utf-8"), "phone") == "<b>new</b>"


def test_a_card_whose_target_left_the_sample_refuses() -> None:
    """The inbox cards show ONE game-plan item and ONE Slot by Slot row,
    chosen by what they say. A rebuilt sample that no longer says them must
    stop the build, never ship a blank or a different card."""
    from render import anatomy, phone
    report = _sample()
    with pytest.raises(phone.SelectionError):
        phone._items(anatomy.plan(report), ("Nobody starts this way",))
    with pytest.raises(phone.SelectionError):
        phone._slot_row(anatomy.slots(report), "Nobody At All")


# --------------------------------------------------------------------- #
# the phone is the email
# --------------------------------------------------------------------- #

def _phone_section(key: str) -> str:
    screen = phone_screen_markup()
    if key == "masthead":
        return screen.split('<div class="mh">')[1].split('<section class="card"')[0]
    return screen.split(f'data-sec="{key}"')[1].split(">", 1)[1].split("</section>")[0]


def phone_screen_markup() -> str:
    return LANDING.split("<!-- phone:start -->")[1].split("<!-- phone:end -->")[0]


def _email_sections(report: dict) -> dict[str, str]:
    """The email's body split on its section markers; what comes before the
    first marker (the hidden preview, then the masthead) is "lead"."""
    from render.email import render_email
    page = render_email(report)
    parts = re.split(r"<!--\s*sec:([\w-]+)\s*-->", page[page.find("<body"):])
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    sections["lead"] = parts[0]
    return sections


def test_the_phone_carries_the_emails_own_words_section_by_section() -> None:
    """Parity, contract B7/C11: the phone's masthead, card 01 and card 02 (as
    far as its drivers line, where the phone crops) say exactly what the same
    sections of the real email say, word for word and figure for figure —
    the sample band excluded, because a subscriber's email carries none (it
    follows the masthead, contract C1, so only band words may follow the
    phone's masthead there)."""
    from render import anatomy
    report = _sample()
    email = _email_sections(report)
    band_parts = [re.sub(r"\s+", "", str(part)) for band in anatomy.bands(report)
                  for part in (band.get("head"), band.get("text")) if part]
    masthead = _squash(_phone_section("masthead"))
    assert masthead.startswith("BeatYourLeague") and "Week10" in masthead, masthead
    if "masthead" in email:
        want = _squash(email["masthead"])
        assert want.startswith(masthead), (masthead, want)
        rest = want[len(masthead):]
        for part in band_parts:
            rest = rest.replace(part, "", 1)
        assert not re.sub(r"[—–·:.\-]", "", rest), ("more than a band follows", rest)
    else:
        # Unmarked, the masthead is the last thing before the first section:
        # only the hidden inbox preview comes ahead of it.
        assert _squash(email["lead"]).endswith(masthead), (masthead, _squash(email["lead"]))
    for key in ("lineup", "closest"):
        assert key in email, f"the email marks no {key} section"
        want = _squash(email[key])
        got = _squash(_phone_section(key))
        if key == "lineup":
            assert got == want, (key, got, want)
        else:
            assert want.startswith(got), (key, got, want)


def test_the_notification_and_the_mail_row_are_the_emails() -> None:
    """Contract C9: the lock screen's notification is the email's subject and
    inbox preview, verbatim, and the mail row is its sender, its subject and
    the time — a letter avatar, never a logo (a mail app draws a sender it has
    no photo for that way)."""
    from render.email import preheader_for, subject_for
    report = _sample()
    screen = phone_screen_markup()
    row = screen.split('<div class="mailrow">')[1].split("</div>")[0]
    assert _squash(row) == _squash(f"B Beat Your League {subject_for(report)} 9:41 AM")
    assert '<span class="av">B</span>' in row and "<svg" not in row
    note = screen.split('<div class="lnote">')[1].split('<div class="lk-tools">')[0]
    assert html.unescape(re.search(r'<span class="lsub">(.*?)</span>', note).group(1)) \
        == subject_for(report)
    assert html.unescape(re.search(r'<span class="lpre">(.*?)</span>', note).group(1)) \
        == preheader_for(report)
    assert "mark" not in note, "a brand mark rides on the notification"


def test_the_phone_is_one_image_with_nothing_to_focus() -> None:
    """Accessibility: the phone is one labelled image and its screen is
    hidden from assistive tech, so nothing inside it may take focus — a link
    or control in an aria-hidden subtree is a keyboard stop a screen reader
    cannot announce (axe: aria-hidden-focus)."""
    assert re.search(r'<div class="phone" id="hero-phone" role="img" '
                     r'aria-label="The 2024 Week 10 sample report as it arrives on a phone">',
                     LANDING)
    assert '<div class="screen" aria-hidden="true">' in LANDING
    screen = phone_screen_markup()
    for focusable in (r"<a\b", r"<input\b", r"<button\b", r"<select\b", r"<textarea\b",
                      r"tabindex=", r"<label\b"):
        assert not re.search(focusable, screen), focusable


def test_the_page_never_shows_one_call_in_two_cards() -> None:
    """Contract B3: the phone carries the closest call (card 02), so the
    inbox section shows the cards that come next — 03, 04, 05, in report
    order — and nothing on the page repeats the phone."""
    rows = BODY.split('<div class="rows">')[1].split('<p class="realfoot">')[0]
    keys = re.findall(r'<section class="card" data-sec="(\w+)">', rows)
    numbers = re.findall(r'<span class="n">(\d+)</span>', rows)
    assert keys == ["plan", "ifthen", "slots"] and numbers == ["03", "04", "05"], (keys, numbers)
    page = markup_only(LANDING)
    assert page.count('data-sec="closest"') == 1 and page.count('data-sec="lineup"') == 1
    assert "Who's getting the ball" not in LANDING


# --------------------------------------------------------------------- #
# the story the page tells (contract B3)
# --------------------------------------------------------------------- #

def test_the_faq_answers_in_the_order_a_buyer_asks_and_its_twin_follows() -> None:
    """Contract B3: the FAQ leads with "How is this different from free
    rankings?" and ends with "Who's behind this?"; the FAQPage structured
    data lists the same questions in the same order, with the same answers,
    so a search snippet and the page never disagree."""
    order = ["How is this different from free rankings?", "Does it work with my league?",
             "Is it worth joining mid-season?", "What if my roster changes mid-season?",
             "Can I check how it decides?", "I'm in more than one league. What do I need?",
             "Who's behind this?"]
    faq = BODY.split('<section id="faq">')[1].split("</section>")[0]
    asked = [html.unescape(q) for q in re.findall(r"<summary>(.*?)</summary>", faq)]
    assert asked == order, asked
    graph = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                 LANDING, re.S).group(1))["@graph"]
    twin = next(n for n in graph if n["@type"] == "FAQPage")["mainEntity"]
    assert [q["name"] for q in twin] == order
    answers = re.findall(r'<div class="a">(.*?)</div>', faq, re.S)
    for q, a in zip(twin, answers):
        page = " ".join(html.unescape(re.sub(r"<[^>]+>", "", a)).split())
        assert q["acceptedAnswer"]["text"] == page, q["name"]


def test_the_league_pass_teaser_has_no_price_and_no_chat_bubble() -> None:
    """Contract B3: one decision at checkout — the League Pass is sold on its
    own page, so the landing's teaser carries no price, one ghost button, and
    the group-chat bubble went (league-pass.html keeps that copy)."""
    lp = BODY.split('<section class="leaguepass">')[1].split("</section>")[0]
    assert "$" not in lp and "bubble" not in lp and "chatmock" not in lp
    assert re.findall(r'class="btn (\w+)"', lp) == ["ghost"]
    assert 'href="league-pass.html"' in lp


def test_the_landing_stays_inside_its_word_budget() -> None:
    """Quality gate, contract B3: replace, don't add. The generated phone
    brought the real email's words onto the page, so the hand-written copy
    gave room (the trust strip, the chat bubble, the Monday beat, the hero's
    bye link, the inbox lede). Measured the way test_site counts it."""
    rendered = re.sub(r"<script.*?</script>|<style.*?</style>|<head>.*?</head>", "",
                      LANDING, flags=re.S)
    words = len(re.sub(r"<[^>]+>", " ", rendered).split())
    assert words <= 1289, f"the landing is {words} words"


# --------------------------------------------------------------------- #
# the visual system (contracts C6-C8)
# --------------------------------------------------------------------- #

def _outside_phone(css: str) -> str:
    """The landing's own CSS, without the phone block (its hardware and the
    email inside it are sized in cqw and drawn to the phone's own rules)."""
    start, end = css.index("/* phone:css:start"), css.index("/* phone:css:end */")
    return css[:start] + css[end:]


def test_no_gold_gradient_anywhere() -> None:
    """Contract C6: gold is a flat fill (bars, the primary button, the hero
    slab) — never a gradient. The slab, the button, the bars, the stamp and
    the progress bar all wore one."""
    for grad in re.findall(r"(?:linear|radial|conic)-gradient\([^;]*", CSS):
        assert not re.search(r"#F2C230|#D9A81B|var\(--flag", grad, re.I), grad


def test_buttons_are_flat_rounded_rectangles() -> None:
    """Contract C7: one button shape on every surface — 48px (the nav's 40,
    a phone's full-width 52), radius 8, Barlow Condensed 800 16px in
    capitals at .06em, no slant, no shadow, no sheen."""
    rule = re.search(r"\n  \.btn\{([^}]*)\}", CSS).group(1)
    for want in ("min-height:48px", "border-radius:8px", "font-weight:800", "font-size:16px",
                 "letter-spacing:.06em", "text-transform:uppercase"):
        assert want in rule, want
    assert "clip-path" not in CSS
    for sel in (r"\.btn(?:\.gold|\.ghost)?(?::hover)?", r"\.plan \.btn", r"\.stickybar \.btn"):
        for body in re.findall(r"\n  " + sel + r"\{([^}]*)\}", CSS):
            assert "box-shadow" not in body, sel
    assert re.search(r"\n  nav \.btn\{min-height:40px;", CSS)
    assert "min-height:52px" in re.search(r"\n  \.plan \.btn\{([^}]*)\}", CSS).group(1)


def test_tracking_and_type_sizes_stay_in_the_system() -> None:
    """Contract C7/C8: tracking only 0, .005em, .01em, .06em and .08em (the
    .1–.3em capitals read as a stock template), at most fourteen distinct
    pixel sizes outside the phone, and numerals upright everywhere except
    the hero slab and the lockup."""
    own = _outside_phone(CSS)
    spacing = set(re.findall(r"letter-spacing:\s*([^;}]+)", own))
    assert spacing <= {"0", ".005em", ".01em", ".06em", ".08em"}, spacing
    sizes = set(re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", own))
    assert len(sizes) <= 14, sorted(sizes, key=float)
    italic = re.findall(r"\n  ([^{}\n]+)\{[^}]*font-style:italic", own)
    assert set(italic) <= {".brand", "h1", "h1 em"}, italic


def test_cards_are_one_shape_with_hairlines_only() -> None:
    """Contract C7: radii 4, 8, 12, 16 and 999 only (the phone hardware keeps
    its own), 1px borders, no 3-4px side or top bars, no double rules."""
    own = _outside_phone(CSS)
    radii = set(re.findall(r"border-radius:\s*([^;}]+)", own))
    assert radii <= {"4px", "8px", "12px", "16px", "999px", "50%"}, radii
    assert not re.search(r"border(?:-(?:left|top|right|bottom))?:\s*[2-9]px", own)
    assert "double" not in own


def test_the_storyline_still_starts_and_ends_on_the_opened_email() -> None:
    """Contract B4: every storyline layer's keyframes start and end on the
    rest state, so pause, wrap, reduced motion, no script and print all show
    the opened email at its top; the old peek's layers are gone, and the new
    beats are card 01's bars and card 02's bar."""
    frames = dict(re.findall(r"@keyframes (st-[\w-]+)\{(.*?\})\s*\}", CSS, re.S))
    assert {"st-bar", "st-call", "st-view"} <= set(frames)
    assert not {"st-flip", "st-if", "st-rise"} & set(frames)
    assert "[data-sec=lineup] .fbar i" in CSS and "[data-sec=closest] .cbar i" in CSS
    for name in ("st-bar", "st-call", "st-view"):
        body = frames[name]
        first = re.match(r"\s*0%[^{]*\{([^}]*)\}", body).group(1)
        last = re.search(r"100%\{([^}]*)\}\s*$", body).group(1)
        assert "transform:none" in first and "transform:none" in last, name
