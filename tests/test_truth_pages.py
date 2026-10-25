"""The truth pass (Oct 25 2026), the pages' half: every site page except the
landing and the legal pages, on the report's one design system — the shared
contract's C2 (full-bleed paper), C6 (colours and their roles), C7 (shape) and
C8 (type) — and How it works reading in the report's own order.

What changed, and what each test below holds:
- the sheet on a desk is gone at every width: a flat navy band, then the paper;
- one button (a flat 8px rectangle, 48px tall), one paper card (12px, a 1px
  border, one shadow), one dark card (16px, a hairline, no shadow), one chip;
- no slanted buttons, no gold gradients, no 3-4px side or top bars, no double
  rules, no sheen, tracking only at 0/.005/.01/.06/.08em, italic only in the
  lockup (and the League Pass headline's slab, the landing hero's own);
- gold fills (buttons, bars, the step track, the slab); it is text only as a
  report card's number on navy and an app page's step numeral on navy;
- every control at 390 is a thumb tall (44px; fields 48; the big ones 52);
- the join page's header chips went (the pitch carries the price beside its
  terms; the button names what is not open yet);
- How it works annotates the report's own cards 01-05 in the report's order.

Each docstring says what it guards against."""
from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

PAGES = ("join/index.html", "join/confirm.html", "how-it-works.html", "thanks.html", "404.html",
         "byes/index.html", "league-pass.html", "espn/index.html", "yahoo/index.html",
         "sleeper/index.html", "cbs/index.html")
PAPER = tuple(p for p in PAGES if p != "league-pass.html")
GOLDS = r"(?:--flag|--flag-deep|#F2C230|#D9A81B|#FFDA5E|#FFD75E|#F0B62A)"


def _page(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def _style(page: str) -> str:
    return "\n".join(re.findall(r"<style>(.*?)</style>", page, re.S))


def _rules(css: str) -> list[tuple[str, str]]:
    """(selector, body) for every plain rule, media blocks flattened."""
    flat = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(sel.strip().split("{")[-1].strip(), body)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", flat)]


@pytest.mark.parametrize("name", PAGES)
def test_no_slant_no_gold_gradient_no_side_bars_no_double_rules(name: str) -> None:
    """Before: slanted gold buttons (clip-path:polygon) with a gradient and a
    sheen, cards with 3-5px gold or navy top and side bars, sections split by
    3px double rules, a gold-gradient headline slab. One flat system now."""
    css = _style(_page(name))
    assert "clip-path:polygon" not in css, name
    assert not re.search(r"gradient\([^;{}]*" + GOLDS, css, re.I), f"{name}: a gold gradient"
    assert not re.search(r"border-(?:left|top|right|bottom):\s*[3-5]px", css), f"{name}: a bar"
    assert not re.search(r"inset\s+[3-5]px\s+0\s+0", css), f"{name}: a bar drawn as a shadow"
    assert not re.search(r"border[\w-]*:[^;}]*\bdouble\b", css), f"{name}: a double rule"
    assert not re.search(r"\.btn[^{}]*::after\{[^}]*skewX", css), f"{name}: a button sheen"


@pytest.mark.parametrize("name", PAGES)
def test_tracking_is_one_of_the_five(name: str) -> None:
    """Contract C7: letter-spacing only at 0, .005em, .01em, .06em and .08em —
    the .1em-.24em tracked caps read as labels from another product."""
    values = set(v.strip() for v in re.findall(r"letter-spacing:([^;}!]+)", _style(_page(name))))
    assert values <= {"0", ".005em", ".01em", ".06em", ".08em"}, (name, values)


@pytest.mark.parametrize("name", PAGES)
def test_every_button_is_the_flat_rounded_rectangle(name: str) -> None:
    """Contract C7: every .btn is a flat rounded rectangle — 8px corners, 48px
    tall, no drop shadow — the primary a flat #F2C230, the secondary a 1.5px
    outline; the markup holds only .btn.gold and .btn.ghost."""
    page = _page(name)
    css = _style(page)
    for sel, body in _rules(css):
        if re.fullmatch(r"\.btn", sel) and "font-family" in body:
            assert "border-radius:8px" in body and "min-height:48px" in body, (name, body)
            assert "box-shadow" not in body, name
        if re.fullmatch(r"\.btn\.gold", sel):
            assert "background:var(--flag)" in body and "gradient" not in body, (name, body)
        if re.fullmatch(r"\.btn\.ghost", sel):
            assert "border:1.5px solid" in body, (name, body)
    classes = set(re.findall(r'class="(btn(?: [^"]*)?)"', re.sub(r"<script.*?</script>", "",
                                                                page, flags=re.S)))
    assert classes <= {"btn gold", "btn ghost"}, (name, classes)


@pytest.mark.parametrize("name", PAGES)
def test_italic_only_in_the_lockup_and_the_league_pass_slab(name: str) -> None:
    """Contract C7: numerals upright everywhere; italic survives only in the
    lockup and the hero slab (here, the League Pass headline, drawn as the
    landing hero draws it). The $69, the closer and the app pages' headlines
    were italic."""
    allowed = {".sitebar .brand"} | ({"h1", "h1 em"} if name == "league-pass.html" else set())
    italic = {sel for sel, body in _rules(_style(_page(name))) if "font-style:italic" in body}
    assert italic <= allowed, (name, italic - allowed)


@pytest.mark.parametrize("name", PAPER)
def test_gold_is_never_text_on_the_paper(name: str) -> None:
    """Contract C6: gold is a FILL (buttons, bars, the step track). As text it
    is a report card's number on its navy head and an app page's step numeral
    in its navy circle — never words on the paper, where it measured under 2:1."""
    allowed = {".card .eyebrow .n", "ol.how li::before", ".sitebar .brand .lg"}
    for sel, body in _rules(_style(_page(name))):
        if re.search(r"(?<![-\w])color:\s*(?:var\(--flag\)|#F2C230|#F0B62A)", body):
            assert sel in allowed, (name, sel)


@pytest.mark.parametrize("name", PAPER)
def test_paper_cards_are_one_card(name: str) -> None:
    """Contract C7: a paper card is 12px corners and a 1px #E2DDD0 border with
    the one paper shadow; nothing on these pages draws a square card or a 4px
    one-off any more."""
    css = _style(_page(name))
    assert "--line:#E2DDD0" in css.replace(" ", ""), name
    for sel, body in _rules(css):
        if "border-radius:4px" in body:
            # 4px is the chip, the tag, the checkbox and a bar's track only.
            assert re.search(r"chip|tag|shape|box|check-address|kicker|bar\b", sel), (name, sel)
        if "border-radius:0" in body.replace("border-radius:0 0", ""):
            assert re.search(r"sugrow|fixmail", sel), (name, sel)


def test_the_dark_page_draws_hairlines_not_shadows() -> None:
    """Contract C7: no shadow on a dark ground (it reads as a smudge), a
    hairline instead; the four reasons are .dcard (16px, a hairline) and the
    $69 card is the landing's pricing card — paper, 16px, an upright numeral,
    the flat gold button full width, the terms beside the price."""
    page = _page("league-pass.html")
    css = _style(page)
    assert "box-shadow" not in css and "text-shadow" not in css
    assert page.count('<div class="dcard"><h3>') == 4 and 'class="box"' not in page
    dcard = re.search(r"\n  \.dcard\{([^}]*)\}", css).group(1)
    assert "border-radius:16px" in dcard and "border:1px solid var(--hair)" in dcard
    price = re.search(r"\n  \.price\{([^}]*)\}", css).group(1)
    assert "border-radius:16px" in price and "background:var(--card)" in price
    assert "border:2px solid var(--flag)" not in css, "a gold frame"
    amt = re.search(r"\n  \.price \.amt\{([^}]*)\}", css).group(1)
    assert "italic" not in amt
    assert ".price .btn{display:flex;width:100%;min-height:52px;}" in css
    card = page.split('<div class="price" data-reveal>')[1].split('<p class="see">')[0]
    words = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", card))
    for term in ("$69", "One payment. Nothing renews", "refund until your second weekly report"):
        assert term in words, term
    # The group-chat line lives here, shareable: the one copy of it (the
    # landing's bubble is the landing builder's to retire).
    assert '<p id="ask-text">Should we take the League Pass' in page and 'id="ask-share"' in page


@pytest.mark.parametrize("name", ["join/index.html", "byes/index.html"])
def test_every_control_is_a_thumb_tall(name: str) -> None:
    """Acceptance (truth pass): every control at 390 is 44px or taller — the
    options, the typeahead rows, the × beside a player, the retry and choice
    buttons — fields 48px with 16px type (no zoom on focus), the full-width
    primaries 52px, the roster box 160px."""
    css = _style(_page(name))

    def rule(selector: str) -> str:
        return re.search(r"\n  " + re.escape(selector) + r"\{([^}]*)\}", css).group(1)

    assert "min-height:44px" in rule(".opts label") and "border-radius:8px" in rule(".opts label")
    fields = rule("input[type=text], input[type=email]")
    assert "min-height:48px" in fields and "font-size:16px" in fields and "border-radius:8px" in fields
    assert "min-height:160px" in rule("textarea") and "font-size:16px" in rule("textarea")
    assert "min-height:44px" in rule(".sugrow")
    assert "height:44px" in rule(".row .fix button.drop")
    assert "min-height:44px" in rule(".row .fix button") and "min-height:44px" in rule(".retry")
    primary = "#resolve,#submit" if name == "join/index.html" else "#check"
    assert "min-height:52px" in rule(primary)


def test_the_join_header_carries_the_price_with_its_terms_and_no_chips() -> None:
    """The header chips ('$29 · REST OF SEASON', 'ONE PAYMENT, NOTHING
    RENEWS', 'REST-OF-SEASON PASS OPENS SOON') repeated the pitch in tracked
    gold caps under it. They are gone: the pitch keeps the price beside its
    one-payment and refund terms, verbatim, and the closed button names the
    plan that is not open yet (closedChipText feeds closedLabel). The closed
    note is a dark notice in the band — above step 1 at 390 — with no side bar."""
    page = _page("join/index.html")
    assert 'id="header-chips"' not in page and "beta-chips" not in page
    pitch = re.sub(r"\s+", " ", re.search(r'<p id="header-pitch">(.*?)</p>', page, re.S).group(1))
    assert pitch == ("Every lineup from here to your title game, decided for your roster and in "
                     "your inbox every Tuesday. <b>$29 for the rest of the season</b> — one "
                     "payment, no subscription, and a full refund until your second weekly "
                     "report's week kicks off.")
    label = re.search(r"function closedLabel\(action\) \{.*?\n\}\n", page, re.S).group(0)
    assert label.rstrip().endswith('return closedChipText();\n}')
    note = re.search(r"\n  header #closed-note\{([^}]*)\}", _style(page)).group(1)
    for part in ("background:rgba(246,244,238,.06)", "border:1px solid rgba(242,194,48,.35)",
                 "border-radius:12px", "padding:14px 16px", "font-size:15px", "color:#F6F4EE"):
        assert part in note, part
    header = page.split("<header>", 1)[1].split("</header>", 1)[0]
    assert 'id="closed-note"' in header and page.index("</header>") < page.index('id="step-league"')
    side = page.split('<aside class="side">')[1].split("</aside>")[0]
    assert '<h2>What lands in your inbox</h2>' in side


HOW_INTRO = ("Every Tuesday: every slot decided, the week's closest call explained, what to do "
             "and by when, and a plan for late news. Here's what each part means, where the "
             "numbers come from and how to check any call. You paste your roster when you sign "
             "up, and again whenever it changes. No login, no league connection.")


def test_how_it_works_reads_in_the_reports_order_and_words() -> None:
    """How it works has to look and read like the product: the intro says
    what the report holds; "Reading your report" annotates the report's own
    five cards in its order, each beside its glossary — the lineup (Proj, the
    percentage, rows without one, the realistic range), the closest call, the
    game plan (no longer "the checklist at the top… everything below is the
    why", which the new order made false) with byes ahead, the if/then, and
    one slot in full — then Rising roles and the Receipts in words. The
    separate "Your week" card is gone: the week line is the top of card 01."""
    page = _page("how-it-works.html")
    intro = re.sub(r"\s+", " ", page.split("<h1>How your report works</h1>")[1]
                   .split("<p>", 1)[1].split("</p>", 1)[0]).strip()
    assert intro == HOW_INTRO
    read = page.split('<h2 id="read">')[1].split("<h2>")[0]
    annos = read.split('<div class="anno">')[1:]
    assert len(annos) == 5
    terms = [re.findall(r"<dt>([^<]+)</dt>",
                        block.split('<dl class="terms">', 1)[1].split("</dl>", 1)[0])
             for block in annos]
    assert terms == [["Proj", "The percentage on a row", "Rows with no percentage",
                      "Realistic range"],
                     ["The week's closest call with odds"],
                     ["Game plan", "Byes ahead"],
                     ["If/then for gameday"],
                     ["Slot by slot"]], terms
    flat = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", read)))
    assert ("Game plan What to do this week and by when, each with its deadline. Tick the "
            "boxes and you're done.") in flat
    assert ("Slot by slot Every starter and bench player in full: his game and kickoff, the "
            "bench option he's measured against and by how many points, his season and last "
            "three games, and his recent usage.") in flat
    assert "everything below is the why" not in flat and "The checklist at the top" not in flat
    assert '"Touches" means' not in flat and "Touches" not in flat
    assert ">Your week<" not in page and "Rising roles" in flat and "The Receipts" in flat
    assert "The cards are rows from the" in flat
    top = page.split("<h2>")[0]
    assert "The game plan at the top" not in top


def test_thanks_holds_six_paper_cards_and_one_button() -> None:
    """The six 'what happens' cards had gold and navy 4px top bars; they are
    paper cards now (12px, a 1px border), a 13px slate kicker over a 15px
    title, and only "Send it to them" is a button. Its sections number
    themselves 01-04, like every page and the report."""
    page = _page("thanks.html")
    css = _style(page)
    for sel in (".steps li", ".nextcard"):
        body = re.search(r"\n  " + re.escape(sel) + r"\{([^}]*)\}", css).group(1)
        assert "border-radius:12px" in body and "border:1px solid var(--line)" in body, sel
    kicker = re.search(r"\n  \.steps li b\{([^}]*)\}", css).group(1)
    assert "font-size:13px" in kicker and "color:var(--slate)" in kicker
    assert page.count("<li ") + page.count("<li>") >= 3
    block = page.split('<div class="nextsteps" id="next-steps"')[1].split("\n    </div>")[0]
    assert block.count("nextcard") == 3 and block.count('class="btn') == 1
    assert '<button type="button" class="btn gold" id="friend-share">Send it to them</button>' in block
    numbers = re.findall(r'<h2><span class="n">(\d\d)</span>', page)
    assert numbers == ["01", "02", "03", "04"]


def test_the_app_pages_steps_are_one_card_with_numbered_circles() -> None:
    """Contract C8 of the pages spec: the steps were four separately bordered
    boxes with square numerals; they are one paper card's rows, each numbered
    by a 28px navy circle with a gold 14px numeral. The lineup tags are 4px,
    12px, .06em; the copied text is 13px/1.6 monospace inside a paper card;
    the headline is upright."""
    from render import platforms
    css = platforms.STYLE
    how = re.search(r"\n  ol\.how\{([^}]*)\}", css).group(1)
    assert "border-radius:12px" in how and "border:1px solid var(--line)" in how
    li = re.search(r"\n  ol\.how li\{([^}]*)\}", css).group(1)
    assert "border-top:1px solid var(--rule)" in li and "background" not in li
    num = re.search(r"\n  ol\.how li::before\{([^}]*)\}", css).group(1)
    for part in ("width:28px", "height:28px", "border-radius:50%", "background:var(--navy)",
                 "color:var(--flag)", "font-size:14px", "font-weight:800"):
        assert part in num, part
    shape = re.search(r"\n  \.shape\{([^}]*)\}", css).group(1)
    assert "border-radius:4px" in shape
    tag = re.search(r"\n  \.shape b\{([^}]*)\}", css).group(1)
    assert "font-size:12px" in tag and "letter-spacing:.06em" in tag
    raw = re.search(r"\n  \.praw\{([^}]*)\}", css).group(1)
    assert "ui-monospace" in raw and "font-size:13px;line-height:1.6" in raw
    assert "border-radius:12px" in re.search(r"\n  \.pcol\{([^}]*)\}", css).group(1)
    h1 = re.search(r"\n  header h1\{([^}]*)\}", css).group(1)
    assert "italic" not in h1 and "font-weight:800" in h1
