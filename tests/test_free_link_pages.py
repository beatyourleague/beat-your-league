"""The free report under the samples' and How it works' paid ask (owner, Nov 6 2026).

The sample report, the first-week sample, this week's report and How it works
ended on the paid button only, while the app pages already offered the free
report as a quieter text link beneath theirs (render.platforms._try). The
owner approved the same link on these four: the same words and markup
(render.report.TRIAL_LINK_LABEL, free_try_html), the same destination
(join/?try=1, the page's ?via= carried by its own pass), the same rule
(render.report.trial_link_open, read when the page is written) and the same
season close (site/footer.js hides [data-free-try]). Small text under the
gold button: never a second button, never gold.

The three samples are generated: `make sample` (render/sample.py), the
Wednesday build (render/live_sample.py main) and the chrome-only restamp
(`python -m render.live_sample --restamp PAGES`) all write it, by one rule.
How it works is written by hand, so its link is pinned here to the same
markup and the same rule.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import render.live_sample as live
import render.platforms as platforms
import render.report as rr
from test_site import _node, _style, markup_only

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SAMPLES = ("sample-report.html", "sample-first-week.html", "this-week.html")
PAGES = SAMPLES + ("how-it-works.html",)
_FREE = re.compile(r"<p class=\"free\" data-free-try[^>]*>.*?</p>", re.S)


def _page(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>", 1)[0]


def _want(name: str) -> str:
    """The link a page carries: the closing card's line on a sample, the bare
    markup (its own CSS spaces it) on How it works."""
    return live.free_try_line_html() if name in SAMPLES else rr.free_try_html()


def _figures(page: str) -> list[str]:
    """Every number a reader sees outside the closing card."""
    body = re.sub(r'<div class="ctacard">.*?</div>', " ", _main(page), flags=re.S)
    return re.findall(r"\d+(?:\.\d+)?%?", body)


# --------------------------------------------------------------------- #
# the published pages
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("name", PAGES)
def test_each_page_ends_on_its_paid_ask_with_one_free_link_under_it(name: str) -> None:
    """While the free report is open (render.report.trial_link_open: the
    landing's TRIAL_OPEN, CHECKOUT_OPEN and CHECKOUT_CAN_COMPLETE), exactly one
    link to join/?try=1, directly under the page's last gold button: inside a
    sample's closing card after its button, and under How it works' closing
    row. Closed, none at all. Mutation: drop the with_free_try call from the
    restamp, or the link from How it works, and this fails."""
    page = _page(name)
    if not rr.trial_link_open():
        assert "try=1" not in page and "data-free-try" not in page, \
            f"{name} offers a free report that is closed"
        return
    link = _want(name)
    main = _main(page)
    assert page.count("data-free-try") == 1 and page.count("try=1") == 1, name
    assert link in main, f"{name}'s free link is not render.report's"
    assert main.rindex('class="btn gold"') < main.index(link), "the free link sits above the ask"
    if name in SAMPLES:
        card = main.split('<div class="ctacard">', 1)[1].split("</div>", 1)[0]
        assert re.search(r'<a class="btn gold" href="join/index\.html">[^<]*</a>'
                         + re.escape(link) + "$", card), \
            f"{name}: the free link is not the line under the closing card's button"
    else:
        row, rest = main.split('<div class="cta">')[-1].split("</div>", 1)
        rest = re.sub(r"<!--.*?-->", "", rest, flags=re.S)    # a comment draws nothing
        assert 'class="btn gold"' in row and rest.lstrip().startswith(link), \
            "How it works: the free link is not under its closing row"


@pytest.mark.parametrize("name", PAGES)
def test_the_free_link_is_a_quiet_text_link_never_a_button(name: str) -> None:
    """One <p class="free"> holding one plain <a>: no button class, no gold,
    no fill, no border. On a sample it takes the closing card's link style
    (off-white on navy, .ctacard a:not(.btn)); on How it works the app pages'
    own .free rules. Mutation: give the link class "btn" or a gold colour."""
    link = _want(name)
    assert link.startswith('<p class="free" data-free-try') and link.count("<a ") == 1
    anchor = re.search(r"<a ([^>]*)>([^<]*)</a>", link)
    assert "class=" not in anchor.group(1), "the free link carries a class"
    assert anchor.group(2) == rr.esc(rr.TRIAL_LINK_LABEL)
    for word in ("btn", "gold", "flag", "#F2C230", "#F0B62A", "background", "border"):
        assert word not in link, f"the free link is styled with {word!r}"
    page = _page(name)
    if name not in SAMPLES:
        rules = re.findall(r"[^{}]*\.free[^{]*\{[^}]*\}", _style(page))
        assert rules, "How it works has no .free rules"
        for rule in rules:
            for word in ("flag", "background", "border", "uppercase"):
                assert word not in rule, f"How it works' .free rule uses {word!r}: {rule}"
        assert "[hidden]{display:none!important;}" in _style(page)
    else:
        assert "display:" not in re.search(r"<p [^>]*>", link).group(0), \
            "a display on the line would beat footer.js's [hidden]"


@pytest.mark.parametrize("name", PAGES)
def test_the_season_close_reaches_every_free_link(name: str) -> None:
    """footer.js hides every [data-free-try] once the season is over or its
    last week has kicked off (tests/test_free_link.py runs it). It only does so
    on a page that loads it, and only for an element it can select."""
    page = _page(name)
    assert rr.site_footer() in page, f"{name} does not load footer.js"
    script = (SITE / "footer.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll("[data-free-try]")' in script
    assert "el.hidden = true" in script
    for free in _FREE.findall(page):
        assert "data-free-try" in free


@pytest.mark.parametrize("name", PAGES)
def test_the_free_link_carries_the_pages_channel_tag(name: str) -> None:
    """The page's own ?via= pass, run in node over every link on the page:
    the free link leaves as join/index.html?try=1&via=<tag>, like the app
    pages' (it is in the carry's funnel list as join/). Mutation: put the link
    after the page's script, or out of the funnel, and this fails."""
    page = _page(name)
    if not rr.trial_link_open():
        pytest.skip("the free report is closed, so no page carries the link")
    script = next(s for s in re.findall(r"<script>(.*?)</script>", page, re.S)
                  if "function carryVia(" in s)
    assert page.index(_want(name)) < page.index("function carryVia("), \
        "the link is written after the pass that tags it"
    hrefs = re.findall(r'<a [^>]*href="([^"]*)"', markup_only(page))
    harness = (r"""
const anchors = HREFS.map((h) => ({ h, getAttribute() { return this.h; },
  setAttribute(k, v) { if (k === "href") this.h = v; } }));
globalThis.location = { search: "?via=reddit-x" };
globalThis.window = {};
globalThis.document = { querySelectorAll: (sel) => sel === "a[href]" ? anchors : [],
  getElementById: () => null };
""".replace("HREFS", json.dumps([h.replace("&amp;", "&") for h in hrefs]))
               + script + "\nconsole.log(JSON.stringify(anchors.map((a) => a.h)));\n")
    tagged = [h for h in _node(harness) if "try=1" in h]
    assert tagged == ["join/index.html?try=1&via=reddit-x"], tagged


# --------------------------------------------------------------------- #
# one source
# --------------------------------------------------------------------- #

def test_the_words_and_the_markup_come_from_one_place(monkeypatch) -> None:
    """The label is typed once (render/report.py) and every generated copy is
    render.report.free_try_html: the app pages' link, the samples' line (the
    same markup, spaced for the navy card) and How it works' (held to it by the
    test above). Mutation: retype the label in render/live_sample.py, or build
    the line by hand, and this fails."""
    label = rr.TRIAL_LINK_LABEL
    typed = {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8").count(label)
             for folder in ("render", "run", "engine", "infra")
             for path in (ROOT / folder).rglob("*") if path.suffix in (".py", ".js")}
    assert {k: v for k, v in typed.items() if v} == {"render/report.py": 1}
    plain = re.sub(r' style="[^"]*"', "", live.free_try_line_html())
    assert plain == rr.free_try_html(), "the samples' line is not render.report's link"
    assert rr.free_try_html() == (f'<p class="free" data-free-try><a href="join/index.html?try=1">'
                                  f'{rr.esc(label)}</a></p>')
    monkeypatch.setattr(platforms, "trial_link_open", lambda: True)
    for platform in (*platforms.PLATFORMS, platforms.DYNASTY):
        assert platforms._try(platform) == "\n    " + rr.free_try_html(
            platforms.join_href(platform)), platform.slug


def test_the_free_address_keeps_a_pages_own_query() -> None:
    assert rr.free_try_href() == "join/index.html?try=1"
    assert rr.free_try_href("../join/index.html?t=std") == "../join/index.html?t=std&try=1"
    assert 'href="../join/index.html?t=std&amp;try=1"' in rr.free_try_html(
        "../join/index.html?t=std")


# --------------------------------------------------------------------- #
# the writers: restamp, make sample, the Wednesday build
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("name", SAMPLES)
def test_the_restamp_writes_the_free_link_by_the_app_pages_rule(name: str, monkeypatch) -> None:
    """`python -m render.live_sample --restamp` on each published sample: the
    line appears once, under the closing card's button, while the free report
    is open; it goes when it closes, when the clock says the season is over,
    and when restamp_last marks the page as an over season's last report. No
    figure moves and a second restamp changes nothing. Mutation: make
    show_free_try ignore trial_link_open or the phase."""
    before = _page(name)
    monkeypatch.setattr(rr, "trial_link_open", lambda landing=None: True)
    once = live.restamp_chrome(before, byes_left=True, phase="season")
    assert live.restamp_chrome(once, byes_left=True, phase="season") == once
    assert once.count("data-free-try") == 1 and once.count("try=1") == 1
    card = once.split('<div class="ctacard">', 1)[1].split("</div>", 1)[0]
    assert card.index('class="btn gold"') < card.index("data-free-try")
    assert _figures(once) == _figures(before), "the restamp moved a number"
    assert "data-free-try" not in live.restamp_chrome(once, byes_left=True, phase="over")
    # The kept live page, restamped as its season's last report: preseason
    # follows the rule, an over season takes the link with the asks.
    assert live.restamp_last(once, season_over=False).count("data-free-try") == 1
    if name == "this-week.html":
        assert live._LIVE_BANNER.search(once) or live._LAST_BANNER.search(once)
        assert "data-free-try" not in live.restamp_last(once, season_over=True)
    monkeypatch.setattr(rr, "trial_link_open", lambda landing=None: False)
    closed = live.restamp_chrome(once, byes_left=True, phase="season")
    assert "data-free-try" not in closed and "try=1" not in closed
    assert _figures(closed) == _figures(before)


def test_make_sample_writes_it_by_the_same_rule(monkeypatch) -> None:
    """render/sample.page, which `make sample` writes both pinned samples
    through: the line under the closing card's button while the free report is
    open, none once it closes. Mutation: drop with_free_try from page()."""
    import render.sample as sample
    card = ('<html><body><main><div class="ctacard"><p>This report is from the 2024 '
            'season.</p><a class="btn gold" href="join/index.html">Get my lineups</a>'
            '</div></main><footer></footer></body></html>')
    monkeypatch.setattr(sample, "render", lambda report, template: card)
    monkeypatch.setattr(live, "clock_hints", lambda path=None: (True, "season"))
    monkeypatch.setattr(rr, "trial_link_open", lambda landing=None: True)
    page = sample.page({})
    assert page.count(live.free_try_line_html()) == 1
    assert page.index('class="btn gold"') < page.index("data-free-try") < page.index("</div>")
    monkeypatch.setattr(rr, "trial_link_open", lambda landing=None: False)
    assert "data-free-try" not in sample.page({})


def test_the_wednesday_build_writes_it_by_the_same_rule(tmp_path, monkeypatch) -> None:
    """render/live_sample main, the weekly build of this-week.html, offline on
    test_solo_run's fixture week. Mutation: drop with_free_try from main()."""
    from test_live_sample import _run
    from run.solo import load_week_data, report_for
    from test_solo_run import OFFLINE, SEASON, WEEK, _cache, _spec

    data = load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE)

    def fake_build(*_a, **_k):
        report = report_for(_spec(), data, league_size=12)
        report["meta"].update(live_demo=True, anonymized_demo=True, thin_week_note=None)
        return report
    monkeypatch.setattr(live, "build", fake_build)
    for state, want in ((True, 1), (False, 0)):
        monkeypatch.setattr(rr, "trial_link_open", lambda landing=None, s=state: s)
        root = tmp_path / str(state)
        root.mkdir()
        code, out, _ = _run(root, monkeypatch, kicked_off=False, extra=("--no-record",))
        assert code == 0 and out.is_file()
        page = out.read_text(encoding="utf-8")
        assert page.count("data-free-try") == want, state
        if want:
            card = page.split('<div class="ctacard">', 1)[1].split("</div>", 1)[0]
            assert card.endswith(live.free_try_line_html())
