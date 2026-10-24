"""The chrome of every report and email — panel review, Oct 15 2026.

A six-lens panel scored the product against the category and found what a
buyer sees around the numbers letting the numbers down: a forwarded League
Pass report sending leaguemates to the $39 checkout, a monthly subscriber told
they renew yearly, two teams' emails indistinguishable, operator time in UTC,
an undefined "realistic range", a free report whose only ask was a bare URL in
the legal footer, sample pages with no way to pricing or setup. Each test
names the item and states its reproduction.

Built offline wherever possible (tests/test_email._solo_report runs on a fresh
checkout); the ones that need the published sample skip without its cache.
"""

from __future__ import annotations

import copy
import html
import re
from pathlib import Path

import pytest

import render.report as rr
from render.email import render_email, subject_for, text_summary
from test_email import _solo_report

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = rr.TEMPLATE_PATH.read_text(encoding="utf-8")
SEAT_LINK = "https://example.com/join/?pass=0123456789abcdef0123&s=ppr&n=12&t=T1"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("SITE_URL", "BILLING_PORTAL_URL", "SENDER_POSTAL_ADDRESS",
                 "UPDATE_SECRET", "FORM_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)


def _as(report: dict, **meta) -> dict:
    out = copy.deepcopy(report)
    out["meta"].update(meta)
    return out


def _subscriber(**meta) -> dict:
    report = _solo_report()
    for key in ("historical_demo", "anonymized_demo", "live_demo", "trial"):
        report["meta"].pop(key, None)
    report["meta"].update(meta)
    return report


def _visible(page: str) -> str:
    """A page's body as a reader sees it: no head, no tags, entities decoded."""
    body = page.split("</head>", 1)[-1]
    body = re.sub(r"<style\b.*?</style>|<script\b.*?</script>", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))


def _surfaces(report: dict) -> dict[str, str]:
    """Every surface a weekly report is read on, as text a reader sees."""
    return {"email html": _visible(render_email(report)),
            "email text": text_summary(report),
            "browser archive": _visible(rr.render(report, TEMPLATE))}


def _published_sample(week: int = 10) -> dict:
    import render.sample as sample
    try:
        return sample.build(week)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")


# --------------------------------------------------------------------- #
# C1 / LP-D3 / LP-D5 — the season's end, per plan
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("plan, says, never", [
    ("monthly", "stops billing on its own", "renews once a year"),
    ("season", "Your season pass renews once a year", "League Pass"),
    ("pass", "Your League Pass renews once a year", "season pass"),
    ("league_pass", "claim your seat again next season with your new roster",
     "renews once a year"),
])
def test_the_last_report_states_each_plans_own_promise(plan, says, never) -> None:
    """Reproduction (LP-D3): run/intake.to_rows wrote plan "season" for every
    paid signup, so a League Pass payer's and a monthly subscriber's Week-18
    report both read "Your season pass renews once a year" — false for monthly
    (billing stops via cancel_at), mislabelled for the $99 payer. With the
    registry carrying the purchase (contract C1), each plan says its own."""
    lines = " ".join(rr.season_end_lines(
        {"solo": True, "week": 18, "last_week": 18, "plan": plan}))
    assert "This is the season's last report." in lines
    assert says in lines, lines
    assert never not in lines, lines


def test_the_seat_and_the_payer_say_the_same_thing_about_next_season() -> None:
    """COPY:F6, reproduced: sweep_seats honours a claim (a 400-day form row)
    with no season check while the payer holds a pass, so "Reports for this
    seat end here" was a promise nothing kept — a renewed pass carried this
    season's roster into next season's reports. The seat's last line is now
    the payer's from the other side: the seat follows the pass, and each
    manager claims it again with a new roster. Never "ends here"."""
    seat = rr.SEASON_END_BILLING[rr.SEAT_PLAN]
    payer = rr.SEASON_END_BILLING[rr.PASS_PLAN]
    assert "end here" not in seat and "ends here" not in seat
    assert "follows your league's pass" in seat
    assert "claim your seat again next season with your new roster" in seat
    assert "claims theirs again next season, with their new roster" in payer


def test_a_seat_is_never_told_its_reports_simply_start_again() -> None:
    """Reproduction (LP-D5): a seat's last report promised "Reports start
    again with Week 1 next September if your league's pass is renewed" — but
    a seat lives as a Worker row with a 400-day TTL and is rebuilt from the
    roster it was claimed with. Seats are CLAIMED each season, with that
    season's roster; the payer's line says the same of the league."""
    for plan in ("league_pass", "pass"):
        lines = " ".join(rr.season_end_lines(
            {"solo": True, "week": 18, "last_week": 18, "plan": plan}))
        assert not re.search(r"start again", lines), plan
        assert re.search(r"claims? (your seat|theirs) again next season", lines), plan
        assert "new roster" in lines, plan


def test_the_season_end_line_reaches_every_surface_for_the_new_plans() -> None:
    report = _subscriber(week=18, last_week=18)
    for plan, words in (("pass", "Your League Pass renews"),
                        ("league_pass", "claim your seat again")):
        for name, doc in _surfaces(_as(report, plan=plan)).items():
            assert words in doc, (plan, name)


# --------------------------------------------------------------------- #
# LP-D2 / C4 / C2 — a League Pass league's footer
# --------------------------------------------------------------------- #

def test_a_pass_leagues_forward_line_points_at_the_seat_never_the_checkout(
        monkeypatch) -> None:
    """Reproduction (LP-D2): with SITE_URL set, a seat's and a payer's report
    both read "Got this from a leaguemate? Every manager gets their own report,
    built from their own roster — https://…/join." — sending a leaguemate
    whose seat is already paid for to the $39 checkout."""
    monkeypatch.setenv("SITE_URL", "https://example.com")
    for plan in ("league_pass", "pass"):
        signed = _subscriber(plan=plan, seat_link=SEAT_LINK)
        generic = _subscriber(plan=plan)
        for name, doc in _surfaces(signed).items():
            assert "already covers your seat" in doc, (plan, name)
            assert SEAT_LINK in doc, (plan, name)
            assert "example.com/join." not in doc and "own roster — https" not in doc
            assert "email address the pass was bought with" not in doc, \
                "the signed link needs no address"
        # D10: with no signed link (UPDATE_SECRET unset — the one state in
        # which no seat claim can be confirmed) no seat is offered; the plain
        # line stands. A full pass offers none either.
        full = _subscriber(plan=plan, seat_link=SEAT_LINK)
        full["meta"]["seats_full"] = True
        for name, doc in [*_surfaces(generic).items(), *_surfaces(full).items()]:
            assert "join/?pass=1" not in doc, (plan, name)
            assert "covers your seat" not in doc, (plan, name)
            assert "email address the pass was bought with" not in doc, (plan, name)
    # Everybody else keeps the standing line.
    for name, doc in _surfaces(_subscriber(plan="season")).items():
        assert "Every manager gets their own report" in doc, name
        assert "covers your seat" not in doc, name
    # The seat link is tappable in the HTML.
    page = render_email(_subscriber(plan="league_pass", seat_link=SEAT_LINK))
    assert f'href="{html.escape(SEAT_LINK)}"' in page


def test_a_seat_link_that_is_not_https_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", "https://example.com")
    report = _subscriber(plan="league_pass", seat_link="javascript:alert(1)")
    for doc in _surfaces(report).values():
        assert "javascript:" not in doc
        assert "join/?pass=1" not in doc and "covers your seat" not in doc


def test_a_payers_report_counts_the_seats_and_never_names_one(monkeypatch) -> None:
    """Contract C2: a League Pass payer could not see whether anyone had
    claimed the seats they paid for (LP-I2). One count line, never a name or
    an address, and only on the payer's own report."""
    monkeypatch.setenv("SITE_URL", "https://example.com")
    report = _subscriber(plan="pass", seat_link=SEAT_LINK,
                         seats_claimed={"claimed": 4, "size": 12})
    for name, doc in _surfaces(report).items():
        assert re.search(r"League Pass:?\s*4 of 12 seats claimed", doc, re.I), name
        assert SEAT_LINK in doc, name
        assert doc.count("@") == doc.count("hello@beatyourleague.com"), \
            f"an address reached the {name}"
    # D10: seats only, against the cap; full reads as full, never an error.
    full = _subscriber(plan="pass", seat_link=SEAT_LINK,
                       seats_claimed={"claimed": 12, "size": 12})
    assert "Every seat is claimed." in text_summary(full)
    assert "claim theirs" not in text_summary(full), "nobody is left to send it to"
    open_one = _subscriber(plan="pass", seat_link=SEAT_LINK,
                           seats_claimed={"claimed": 11, "size": 12})
    assert "11 of 12 seats claimed" in text_summary(open_one)
    assert SEAT_LINK in text_summary(open_one), "the link went with a seat still open"
    # Only the payer; nothing for a seat, a season buyer, or a broken count.
    for meta in ({"plan": "league_pass"}, {"plan": "season"},
                 {"plan": "pass", "seats_claimed": {"claimed": "4", "size": 12}},
                 {"plan": "pass", "seats_claimed": {"claimed": -1, "size": 12}},
                 {"plan": "pass", "seats_claimed": {"claimed": True, "size": 12}},
                 {"plan": "pass", "seats_claimed": [4, 12]}):
        report = _subscriber(**meta)
        if meta.get("plan") != "pass":
            report["meta"]["seats_claimed"] = {"claimed": 4, "size": 12}
        assert rr.seats_text(report["meta"]) == "", meta


# --------------------------------------------------------------------- #
# C3 — the roster's date, beside the route that changes it
# --------------------------------------------------------------------- #

def test_the_report_says_which_roster_it_used(monkeypatch) -> None:
    """Contract C3: a subscriber whose trade has not reached us could not tell
    this report predates it. The date the roster in use was set prints beside
    "Roster changed?", on every surface, for a subscriber's report only."""
    # The reply route renders only where an emailed roster can be applied.
    monkeypatch.setenv("UPDATE_SECRET", "s3cret")
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    report = _subscriber(plan="season", roster_as_of="2026-10-03")
    for name, doc in _surfaces(report).items():
        assert re.search(r"Roster changed\?\s*This report used your roster as "
                         r"of Oct 3\.", doc, re.I), name
    for bad in ("", "Oct 3", "2026-13-40", None):
        assert rr.roster_as_of({"solo": True, "roster_as_of": bad}) == ""
    for demo in ({"historical_demo": True}, {"live_demo": True}, {"trial": True}):
        assert rr.roster_as_of({"solo": True, "roster_as_of": "2026-10-03",
                                **demo}) == "", demo
    # The last report has no update route, and still says which roster it used.
    last = _subscriber(plan="season", roster_as_of="2026-10-03", week=18,
                       last_week=18)
    assert "as of Oct 3" in text_summary(last)


def test_a_roster_from_another_season_says_its_year() -> None:
    """LP2-D3, the report half, reproduced: a season pass renewed into 2026
    keeps the roster from its 2025 purchase day, and its report said "This
    report used your roster as of Aug 20." — read as five weeks ago, when it
    was last season's roster. The year prints whenever it is not the
    report's season, on every surface; a date in the season keeps none."""
    renewed = _subscriber(plan="season", roster_as_of="2025-08-20")
    assert renewed["meta"]["season"] == "2026"
    for name, doc in _surfaces(renewed).items():
        assert re.search(r"This report used your roster as of Aug 20, 2025\.", doc), name
    assert rr.roster_as_of({"solo": True, "season": "2026",
                            "roster_as_of": "2026-08-20"}).endswith("as of Aug 20.")


# --------------------------------------------------------------------- #
# BE-I5 / BE-I10 — telling two teams apart, on the buyer's clock
# --------------------------------------------------------------------- #

def test_two_teams_emails_can_be_told_apart() -> None:
    """Reproduction (BE-I5): the same manager with two teams got two emails
    with the subject "Week 6: your lineup, decided" over a header reading
    "Your league · 12 teams · Full PPR". The subject and header now name the
    team by its lead player (engine.solo_report.team_lead) — and, since panel
    review RQ2-06, by the roster on file rather than this week's projections,
    so the name holds from week to week: it moved from "Bijan Robinson's team"
    to "Garrett Wilson's" to "Jayden Daniels's" for one subscription."""
    report = _subscriber(plan="season")
    lead = report["meta"]["team_lead"]
    assert lead, "the report names its team"
    team = f"{lead}'s team"
    assert subject_for(report) == f"Week {report['meta']['week']} — {team}: your lineup, decided"
    for name, doc in _surfaces(report).items():
        assert team in doc.split("GAME PLAN")[0].split("Game Plan")[0], name
    # A week whose projections reorder the starters keeps the name...
    moved = copy.deepcopy(report)
    for slot in moved["lineup"]:
        if slot.get("player_name") != lead and slot.get("projected") is not None:
            slot["projected"] = 99.0
    assert subject_for(moved) == subject_for(report)
    # ...while another roster, with another lead, reads differently.
    other = _as(report, team_lead="Someone Else")
    assert subject_for(other) != subject_for(report)


def test_a_kicker_or_defense_never_names_a_team_and_week_one_still_does() -> None:
    """A defense or a kicker must not make "the Denver Broncos's team"; and
    Week 1, with no projections, names the same team as every other week,
    under the opening-lineup promise."""
    from engine.roster import Player, PlayerDirectory
    from engine.solo_report import team_lead
    from engine.subscriber import RosterSpec, player_index
    people = [Player("DEF-DEN", "Denver Broncos", "DEF", "DEN"),
              Player("00-0000901", "Big Leg", "K", "BAL"),
              Player("00-0000902", "Steady Back", "RB", "KC"),
              Player("00-0000903", "Hot Receiver", "WR", "KC")]
    players = player_index(PlayerDirectory(people))
    spec = RosterSpec(player_ids=tuple(p.player_id for p in people),
                      slots=("RB", "WR"), scoring="ppr")
    assert team_lead(spec, players, None, None) == "Steady Back"
    form = {"DEF-DEN": 30.0, "00-0000901": 25.0, "00-0000902": 12.0,
            "00-0000903": 14.0}
    ranks = {"00-0000901": ("K", 1, 32), "00-0000902": ("RB", 20, 80),
             "00-0000903": ("WR", 12, 120)}
    assert team_lead(spec, players, form, ranks) == "Hot Receiver"
    report = _subscriber(plan="season")
    named = rr.team_name(report)
    for slot in report["lineup"]:
        slot["projected"] = None
    assert rr.team_name(report) == named
    assert subject_for(report) == (f"Week {report['meta']['week']} — "
                                   f"{named}: your opening lineup")
    for demo in ({"historical_demo": True}, {"live_demo": True}, {"trial": True}):
        assert rr.team_name(_as(report, **demo)) is None, demo


def test_a_subscribers_report_is_stamped_on_the_buyers_clock() -> None:
    """Reproduction (BE-I10, I11, RQ-19): the header read "Generated Thu Oct
    15 · 18:51 UTC" — the operator's word on the operator's clock — above
    kickoffs printed in ET."""
    report = _subscriber(plan="season", generated_at="2026-10-15T18:51:00+00:00")
    stamp = rr._generated_stamp(report["meta"])
    assert stamp == "Built Thu Oct 15 · 2:51 PM ET", stamp
    for name, doc in _surfaces(report).items():
        assert "UTC" not in doc and "Generated" not in doc, name
    assert rr.availability_basis({"availability_as_of": "2026-10-13T22:05:00+00:00"}) \
        == "Injury and inactive data as of Tue Oct 13 · 6:05 PM ET."


# --------------------------------------------------------------------- #
# SS-I1 — every number shown has a definition
# --------------------------------------------------------------------- #

def test_the_realistic_range_is_defined_wherever_it_is_shown() -> None:
    """Reproduction (SS-I1): "94 – 158 realistic range" printed on every report
    with no definition anywhere (principle 5). It is defined beside the band
    now, from what engine.week_report._team_range computes — and with NO
    coverage figure, which the frozen method withholds (§10.8)."""
    report = _subscriber(plan="season")
    assert report["matchup"].get("range_gate") is None, "fixture has no band"
    for name, doc in _surfaces(report).items():
        assert re.search(r"Realistic range:\s*your projected total, give or take "
                         r"the week-to-week swing", doc), name
    definition = rr.RANGE_DEFINITION
    assert not re.search(r"\d", definition), "a coverage figure crept in"
    assert not re.search(r"\b(percent|likely|chance|usually|most weeks)\b",
                         definition, re.I)


# --------------------------------------------------------------------- #
# D8 — one title per section
# --------------------------------------------------------------------- #

def test_the_closest_call_is_titled_once_in_the_email() -> None:
    """Reproduction (D8): the email printed "04 · The Week's Closest Call" and
    then a navy card header "The week's closest call" directly beneath it."""
    report = _subscriber(plan="season")
    assert "gate" not in report["regret"], "fixture has no published call"
    doc = html.unescape(render_email(report)).lower()
    assert doc.count("the week's closest call") == 1


# --------------------------------------------------------------------- #
# D9 / I9 / I12 / C7 — the generated pages
# --------------------------------------------------------------------- #

def test_a_generated_page_has_one_main_landmark_between_banner_and_footer() -> None:
    """Reproduction (D9): sample-report, sample-first-week and this-week had no
    <main>; axe flagged every section as content outside a landmark."""
    page = rr.render(_published_sample(10), TEMPLATE)
    assert page.count("<main") == 1 and page.count("</main>") == 1
    assert page.index("</header>") < page.index("<main") < page.index("<section")
    assert page.index("</main>") < page.index("<footer>")
    assert page.index("SAMPLE REPORT") > page.index("<main"), \
        "the sample notice is content outside any landmark"
    assert rr.landmarks("<p>x</p>") == '<main id="main"><p>x</p></main>'


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*{([^}]*)}", css)
    assert match, selector
    return match.group(1)


def _contrast(fg: str, bg: str) -> float:
    def lum(hex_: str) -> float:
        r, g, b = (int(hex_.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_bench_header_passes_contrast() -> None:
    """Reproduction (D9): .benchtape .thead td was slate #5A6B80 on #E9E6DC,
    4.37:1 — under the 4.5:1 a 12px bold label needs."""
    css = rr.extract_design(TEMPLATE)[0]
    root = _rule(css, ":root")
    colours = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", root))
    rule = _rule(css, ".benchtape .thead td")
    fg = re.search(r"color:\s*var\(--([\w-]+)\)", rule).group(1)
    bg = re.search(r"background:\s*(#[0-9A-Fa-f]{6})", rule).group(1)
    assert _contrast(colours[fg], bg) >= 4.5, (colours[fg], bg)


def test_report_meta_type_is_at_least_12px_on_a_phone() -> None:
    """Reproduction (I9): the lines that carry the opponent, kickoff, injury
    status and the band (.tgame, .tsub, .tflag, .yards) were 11px — 32 of them
    on the sample at 390px."""
    css = rr.extract_design(TEMPLATE)[0]
    sizes = {sel: float(re.search(r"font-size:([\d.]+)px", _rule(css, sel)).group(1))
             for sel in (".tsub", ".tgame", ".tflag", ".yards", ".trank", ".chip")}
    assert min(sizes.values()) >= 12, sizes
    phone = css.split("@media (max-width:520px){", 1)[1].split("\n  }", 1)[0]
    for size in re.findall(r"\.tsub,\.tflag,\.tgame{font-size:([\d.]+)px;}", phone):
        assert float(size) >= 12, phone


def test_the_call_column_holds_its_longest_word_on_a_phone() -> None:
    """Panel R4, reproduced by a geometry probe on both published samples:
    td.tcall holding "questionable · see if/then" measured scrollWidth 74
    against clientWidth 65/68/71 at 360/375/390, and the report's border was
    drawn through "questionab|le". The same probe found the "Proj" head 4px
    past its 12% column and "FLEX" 1px past its 9% one at 360. At 420px and
    under the four-column lineup now takes its widths from this rule —
    measured after on the regenerated sample: no cell of either table
    overflows at 360, 375, 390, 414 or 1280 (call cell 86/91/95/102px), and
    desktop widths are unchanged. The <col> widths ride inline, which is why
    the phone rule must be !important; the five-column Tape is untouched."""
    css = rr.extract_design(TEMPLATE)[0]
    phone = css.split("@media (max-width:420px){", 1)[1].split("\n  }", 1)[0]
    widths = dict(re.findall(r"\.tape col:nth-child\((\d)\):(?:nth-last-child\(\d\)|last-child)"
                             r"\{width:(\d+)% !important;\}", phone))
    assert widths == {"1": "10", "2": "48", "3": "14", "4": "28"}, widths
    assert sum(int(w) for w in widths.values()) == 100
    # Each selector names its column by position from BOTH ends, so it can
    # only ever match a four-column group.
    for n, last in (("1", "nth-last-child(4)"), ("2", "nth-last-child(3)"),
                    ("3", "nth-last-child(2)"), ("4", "last-child")):
        assert f".tape col:nth-child({n}):{last}{{" in phone, n
    assert ".tcall{overflow-wrap:anywhere;}" in phone
    four = re.findall(r'width:(\d+)%', rr.LINEUP_COLS)
    assert len(four) == 4 and rr.TAPE_COLS.count("<col>") == 5
    # The call column on a 360px phone (a 314px table): room for its 74px word.
    assert 314 * int(widths["4"]) / 100 - 10 >= 74


def test_a_generated_page_declares_its_colour_scheme_and_bar_colour() -> None:
    """Reproduction (I12): no page declared color-scheme or theme-color, so a
    dark-mode phone drew dark native controls on a cream page."""
    page = rr.render(_subscriber(plan="season"), TEMPLATE)
    head = page.split("</head>")[0]
    assert '<meta name="color-scheme" content="light">' in head
    assert '<meta name="theme-color" content="#101E33">' in head
    # Emails keep their own, stricter declaration.
    assert 'name="theme-color"' not in render_email(_subscriber(plan="season"))


def test_the_report_pages_load_no_font_from_google(tmp_path) -> None:
    """Contract C7: the template linked fonts.googleapis.com, so every sample
    page made a third-party request and shifted its layout when Barlow landed
    (D2: CLS 0.27 on the sample on a slow phone). The fonts are self-hosted,
    linked RELATIVE (the generated pages sit at the site root), every stack
    names its metric-matched fallback face, and the faces above the fold are
    preloaded from whatever fonts.css names them."""
    style, links = rr.extract_design(TEMPLATE)
    assert "googleapis" not in TEMPLATE and "gstatic" not in TEMPLATE
    assert '<link rel="stylesheet" href="fonts/fonts.css">' in links
    assert "'Barlow Condensed Fallback'" in style and "'Barlow Fallback'" in style
    assert not re.search(r"font-family:\s*'Barlow", style.split(":root", 1)[1]
                         .split("}", 1)[1]), "a stack skipped the fallback variables"

    css = tmp_path / "fonts.css"
    css.write_text(
        # The italic first: a preload must take the upright face, not the
        # first one listed.
        "@font-face{font-family:'Barlow';font-style:italic;font-weight:400;"
        "src:url(barlow-400i.woff2) format('woff2');}\n"
        "@font-face{font-family:'Barlow';font-style:normal;font-weight:400;"
        "font-display:swap;src:url(barlow-400.woff2) format('woff2');}\n"
        "@font-face{font-family:\"Barlow Condensed\";font-weight:800;"
        "src:url('./barlow-condensed-800.woff2') format('woff2');}\n"
        "@font-face{font-family:'Barlow Fallback';src:local('Arial');"
        "size-adjust:93%;}\n", encoding="utf-8")
    tags = rr.font_preloads(css)
    assert tags.count('rel="preload"') == 2
    assert 'href="fonts/barlow-condensed-800.woff2"' in tags
    assert 'href="fonts/barlow-400.woff2"' in tags and "400i" not in tags
    assert 'as="font" type="font/woff2" crossorigin' in tags
    assert rr.font_preloads(tmp_path / "missing.css") == ""


# --------------------------------------------------------------------- #
# I3 / I5 — the samples are site pages
# --------------------------------------------------------------------- #

def test_the_samples_carry_the_sites_routes_and_one_ask_top_and_bottom(monkeypatch) -> None:
    """Reproduction (I3, I5): the most-linked proof page carried only "← Home"
    in its header and ended on one underlined "set it up" inside a box tinted
    like an error. Visitors from a shared link had no route to pricing, How it
    works or setup."""
    for week in (10, 1):
        page = rr.render(_published_sample(week), TEMPLATE)
        top = page.split("<h1")[0]
        assert 'href="how-it-works.html"' in top and 'href="index.html#pricing"' in top
        assert rr.site_bar(uid="bylm") in top, "the sample's nav is not the site's (C2)"
        masthead = page.split("</header>")[0]
        assert rr.sample_cta() in masthead
        end = page.split("</main>")[0].rsplit("<section", 1)[1]
        assert 'class="ctacard"' in end and rr.sample_cta() in end
        assert "regret-note" not in page.split("</head>")[1], \
            "the sample still wears the alert tint"
        assert re.search(r"\$\d", top) is None, "no price in the header (hero rule)"
    # Nobody forwards a published sample: its ask is the closing card, not
    # the subscriber footer's "Got this from a leaguemate?".
    monkeypatch.setenv("SITE_URL", "https://example.com")
    assert "from a leaguemate" not in rr.render(_published_sample(10), TEMPLATE)


def test_a_subscribers_report_carries_none_of_the_sites_furniture() -> None:
    page = rr.render(_subscriber(plan="season"), TEMPLATE).split("</head>")[1]
    for furniture in ("sitenav", "ctacard", "headcta", rr.SAMPLE_CTA, 'class="home"'):
        assert furniture not in page, furniture


# --------------------------------------------------------------------- #
# I2 — the free report's ask
# --------------------------------------------------------------------- #

def test_the_free_report_asks_with_a_button_above_the_footer(monkeypatch) -> None:
    """Reproduction (I2): the free report — the main conversion email — had
    zero <a> tags pointing at join; its only ask was "Get one every Tuesday…
    https://beatyourleague.com/join." inside the grey footer, after the data
    source and no-betting lines, with a trailing period and no ?via tag."""
    monkeypatch.setenv("SITE_URL", "https://example.com")
    trial = _subscriber(trial=True)
    page = render_email(trial)
    url = "https://example.com/join/?via=trial"
    assert page.count(f'href="{url}"') == 1
    assert page.index(url) < page.index("Projections are analysis"), \
        "the ask sits below the fine print"
    assert "Get next Tuesday&#x27;s report" in page
    text = text_summary(trial)
    assert f"Get next Tuesday's report: {url}" in text
    assert text.index(url) < text.index("Projections are analysis")
    for doc in (html.unescape(page), text):
        assert "only email we'll send you unless you sign up" in doc
        assert not re.search(r"\$\d", doc), "money is disclosed on the join page"
    # No site, no button.
    monkeypatch.delenv("SITE_URL")
    assert "via=trial" not in render_email(trial) + text_summary(trial)
    # A subscriber's report never carries it.
    monkeypatch.setenv("SITE_URL", "https://example.com")
    assert "via=trial" not in render_email(_subscriber(plan="season"))


# --------------------------------------------------------------------- #
# RQ-05 — the inbox preview line
# --------------------------------------------------------------------- #

def _preheader(page: str) -> str:
    return html.unescape(re.search(r"mso-hide:all;[^>]*>(.*?)&#847;", page).group(1))


def test_the_preview_line_describes_this_report() -> None:
    """Reproduction (RQ-05): every solo email's hidden preview read "Your lineup
    for the week, the one call worth arguing about, …" — including above weeks
    1-3 and every report whose closest-call section reads "No coin-flip call
    published"."""
    report = _subscriber(plan="season")
    regret = report["regret"]
    line = _preheader(render_email(report))
    assert line.startswith(f"Closest call: start {regret['start_name']} over "
                           f"{regret['over_name']}, "), line
    gated = _as(report)
    gated["regret"] = {"gate": "not enough games played yet"}
    line = _preheader(render_email(gated))
    assert "call worth arguing" not in line and "Closest call" not in line
    assert line.startswith(report["checklist"][0]["action"].rstrip(".")), line


def test_the_preview_line_says_what_the_closest_call_card_says() -> None:
    """COPY:F4, reproduced on the published sample's shape: the card is
    labelled "Closest call with odds" whenever it names a narrower decision
    without odds (regret["closer"]), and the preview still said "Closest
    call:"; and a toss-up — printed 52% or less, or the card's "either is
    fine" — previewed as "start X over Y, 51%", the instruction the card and
    the row decline to give. The preview takes the card's label and its
    toss-up wording."""
    report = _subscriber(plan="season")
    base = dict(report["regret"])
    assert "gate" not in base

    def preview(**regret) -> str:
        out = _as(report)
        out["regret"] = {**base, **regret}
        out["regret"] = {k: v for k, v in out["regret"].items() if v is not None}
        return _preheader(render_email(out))

    start, over = base["start_name"], base["over_name"]
    plain = preview(confidence=0.64, closer=None, reason="")
    assert plain.startswith(f"Closest call: start {start} over {over}, 64%."), plain
    closer = preview(confidence=0.64, closer="Closer on points: A or B at RB, 9.9 vs 9.8 — "
                                             "no odds, because B isn't confirmed.")
    assert closer.startswith(f"Closest call with odds: start {start} over {over}, 64%."), closer
    for tossup in (preview(confidence=0.52, closer=None, reason=""),
                   preview(confidence=0.58, closer=None,
                           reason="A projects 9.9 to B's 9.8. A toss-up: either is fine.")):
        assert "either is fine" in tossup and "%" not in tossup, tossup
        assert f"start {start} over" not in tossup, tossup
        assert tossup.startswith(f"Closest call: {start} or {over}"), tossup
    assert preview(confidence=0.53, closer=None, reason="").startswith(
        f"Closest call: start {start} over {over}, 53%.")


# --------------------------------------------------------------------- #
# L3 / GATE-9 / BE-D5 — the other emails
# --------------------------------------------------------------------- #

ADDRESS = "PO Box 123, Toronto ON M5V 1A1"
SENDER = f"Beat Your League · {ADDRESS} · hello@beatyourleague.com"


def test_the_saturday_check_says_who_sent_it(monkeypatch) -> None:
    """Reproduction (L3, GATE-9): with SENDER_POSTAL_ADDRESS set, the Saturday
    final check — a commercial email to a subscriber — carried no sender
    block on either half."""
    from datetime import datetime, timezone

    from engine.final_check import Change
    from render.final_check import render_final_check, text_for_check
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", ADDRESS)
    args = ({"week": 6, "players": {}}, [Change("swap", "Start X at RB", "Y is out.")],
            datetime(2026, 10, 17, 16, tzinfo=timezone.utc))
    assert SENDER in render_final_check(*args)
    assert SENDER in text_for_check(*args)
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS")
    assert "PO Box" not in text_for_check(*args) + render_final_check(*args)


def test_the_roster_report_says_who_sent_it_and_names_the_scoring(monkeypatch) -> None:
    """Reproductions: L3/GATE-9 — the roster report carried no sender block on
    either half; BE-D5 — its plain-text half printed the raw code "Your Team ·
    ppr" while the HTML said "Full PPR"."""
    from test_preseason import _report
    from render.preseason import email_html, render, text_summary as roster_text
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", ADDRESS)
    report = _report()
    assert report["meta"]["scoring"] == "ppr"
    text = roster_text(report)
    assert text.splitlines()[1] == "Your Team · Full PPR", text.splitlines()[1]
    assert not re.search(r"·\s*ppr\b", text)
    for doc in (text, email_html(report), render(report, TEMPLATE)):
        assert SENDER in doc
    half = _report(spec=__import__("test_preseason")._spec(scoring="half_ppr"))
    assert "Half PPR" in roster_text(half).splitlines()[1]


# --------------------------------------------------------------------- #
# GATE-2 — every email this module family sends, at a true 390px phone
# --------------------------------------------------------------------- #

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _real_roster_report() -> dict | None:
    """The published sample roster's roster report off the real 2025 record —
    real names and real ranks ("WR4 of 159") are what overflowed; the
    synthetic fixture's are too short to. None without the cache."""
    try:
        from engine.nflverse_backtest import TEMPLATE_T1
        from engine.preseason import build_preseason_report
        from engine.subscriber import RosterSpec
        from render.sample import SAMPLE_ROSTER
        from run.solo import CACHE_DIR, load_week_data
        data = load_week_data(CACHE_DIR, "2025", 10, live=False)
        spec = RosterSpec(player_ids=SAMPLE_ROSTER, slots=TEMPLATE_T1,
                          scoring="ppr", label="Your Team")
        return build_preseason_report(spec, data.directory, data.prior, "2026",
                                      CACHE_DIR, prior_season="2025")
    except Exception:                                   # noqa: BLE001
        return None


def test_every_email_fits_a_390px_phone_in_a_real_browser(tmp_path, monkeypatch) -> None:
    """Measured in headless Chrome, with the sender block and the long signed
    seat link both present (the widest each email gets). Reproductions: the
    pass welcome's seat link ran 17px past the screen; the roster report's
    nowrap rank cell 9px; the renewal notice, a bare <div>, laid out at 980px.
    Only the weekly report was ever measured (tests/test_report_rows.py)."""
    import json
    import shutil
    import subprocess
    from datetime import date, datetime, timezone

    from engine.final_check import Change
    from render.final_check import render_final_check
    from render.preseason import email_html
    from render.renewal import Renewal, renewal_message
    from render.welcome import welcome_message
    from test_preseason import _report as roster_report

    chrome = CHROME if Path(CHROME).exists() else shutil.which("google-chrome")
    node = shutil.which("node")
    if not chrome or not node:
        pytest.skip("needs Chrome and node")
    monkeypatch.setenv("SITE_URL", "https://example.com")
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", ADDRESS)
    payer = _subscriber(plan="pass", seat_link=SEAT_LINK, roster_as_of="2026-10-03",
                        seats_claimed={"claimed": 4, "size": 12})
    mails = {
        "payer.html": render_email(payer),
        "seat.html": render_email(_subscriber(plan="league_pass")),
        "trial.html": render_email(_subscriber(trial=True)),
        "welcome-pass.html": welcome_message("c@example.com", "league_pass", "a1",
                                             "2026", purchased_at="1792080000",
                                             seat_link=SEAT_LINK).html,
        "welcome-seat.html": welcome_message("m@example.com", "seat", "a2", "2026").html,
        "renewal.html": renewal_message(Renewal("c@example.com", "$99.00 USD",
                                                date(2027, 8, 1), "year",
                                                plan="pass")).html,
        "check.html": render_final_check(
            {"week": 6, "players": {}}, [Change("swap", "Start X at RB", "Y is out.")],
            datetime(2026, 10, 17, 16, tzinfo=timezone.utc)),
        "roster.html": email_html(_real_roster_report() or roster_report()),
    }
    for name, page in mails.items():
        (tmp_path / name).write_text(page, encoding="utf-8")
    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps([{"path": name, "widths": [390], "settle": 200}
                                 for name in mails]))
    run = subprocess.run([node, str(REPO / "run" / "launch_browser.mjs"),
                          tmp_path.as_uri(), chrome, str(pages)],
                         capture_output=True, text=True, timeout=300)
    results = json.loads(run.stdout or "[]")
    if results and "fatal" in results[0]:
        pytest.skip(f"Chrome could not run here: {results[0]['fatal']}")
    assert len(results) == len(mails), run.stderr
    for result in results:
        assert result["innerWidth"] == 390, result
        assert result["scrollWidth"] <= 390, \
            f"{result['path']} is {result['scrollWidth']}px wide on a 390px phone"
        assert result["smallTextCount"] == 0, (result["path"], result["smallText"])
