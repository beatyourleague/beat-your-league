"""One report, drawn the same way everywhere (contract C1-C5, Oct 2026).

The owner asked that what the landing's phone shows be what the product
actually looks like and does. The phone was a sleek one-screen lineup; the
email opened on a long checklist and buried the lineup in a dense table — two
products. Now one model (render.anatomy) feeds every surface in one order:
the lineup first, then the closest call, the game plan, the if/then, slot by
slot, rising roles, the receipts. These tests hold the things that make that
true and that a later edit to one renderer would quietly break:

- every engine fact the email carried before still reaches the reader;
- one slot prints one % on every surface, and every bar is drawn from it;
- the order is the same on the email, the web report and the plain text;
- a card drawn for a page (the phone, the landing) holds nothing focusable;
- the email stays inside its size budget, and Week 1 reads as an ordering;
- republishing an old page's chrome never pours the new sheet onto it.

Built on the published sample (2024 Week 10, and its Week 1); each test skips
without that cache, like every other test that reads the sample.
"""

from __future__ import annotations

import copy
import html
import re
from pathlib import Path

import pytest

import render.anatomy as anatomy
import render.report as rr
from render.email import render_email, text_summary

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = rr.TEMPLATE_PATH.read_text(encoding="utf-8")


def _sample(week: int = 10) -> dict:
    import render.sample as sample
    try:
        return sample.build(week)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")


def _subscriber(week: int = 10) -> dict:
    """The sample as a subscriber receives it: no sample band, a plan."""
    report = _sample(week)
    for key in ("historical_demo", "anonymized_demo", "first_week_demo"):
        report["meta"].pop(key, None)
    report["meta"]["plan"] = "season"
    return report


@pytest.fixture(scope="module")
def w10() -> dict:
    return _subscriber(10)


def _shown(page: str) -> str:
    """What a reader sees: tags out, entities decoded, whitespace folded. A
    fact split across two style runs ("<b>head</b> — rest") reads whole."""
    body = page.split("</head>", 1)[-1]
    body = re.sub(r"<style\b.*?</style>|<script\b.*?</script>", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?>|</(div|p|td|li)>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", body)))


def _facts(report: dict) -> list[str]:
    """Every engine fact string the email printed before the redesign."""
    meta = report["meta"]
    lineup = report["lineup"]
    mixed = anatomy.any_odds(report)
    facts: list[str] = []
    for slot in lineup:
        facts += rr.call_bits(slot)
        facts += [rr.form_phrase(slot), anatomy.short_usage(slot.get("usage")) or "",
                  slot.get("reason") or "", slot.get("game") or ""]
        facts += [f["text"] for f in slot.get("flags") or []]
        if slot.get("confidence") is None and slot.get("player_name") \
                and rr.row_marked(slot, mixed):
            facts.append(rr.row_label(slot))
    for entry in report.get("bench") or []:
        facts += [entry["name"], entry.get("game") or ""]
        if rr.bench_shows_form(entry):
            facts.append(rr.bench_form(entry))
        if entry.get("out"):
            facts.append(rr.bench_phrase(entry))
        elif entry.get("note"):
            facts.append(entry["note"])
        if entry.get("notable") and entry.get("last_season_rank"):
            facts.append(f"{entry['last_season_rank']} last season")
    for item in report["checklist"]:
        facts += [item["action"], item["deadline"]]
        if item.get("detail") and not anatomy.is_set_lineup(item):
            facts.append(item["detail"])
    regret = report["regret"]
    if "gate" in regret:
        facts.append(rr.no_call_line(regret))
    else:
        facts += [" ".join(rr.regret_verdict(regret)), f"{rr._pct(regret['confidence'])}%",
                  *[str(regret[k]) for k in ("label", "definition", "reason", "closer")
                    if regret.get(k)]]
        facts += [f"{d['label']} {d['value']}" for d in regret["drivers"]]
    facts += [rr.pivot_action(p, meta) for p in report.get("pivots") or []]
    if not report.get("pivots"):
        facts.append(report.get("pivots_note") or rr.NO_PIVOTS)
    facts += [rr.availability_basis(meta), rr.RANGE_DEFINITION]
    for row in report.get("rising") or []:
        facts += [part for part in rr.rising_parts(row) if part]
    if not mixed and report.get("no_opponent"):
        facts.append(report["no_opponent"])
    return [f for f in facts if f]


def test_every_engine_fact_reaches_the_email(w10) -> None:
    """The redesign moved words and changed no words. The only facts allowed
    to leave the HTML: the "Set this lineup" detail list (card 01's rows ARE
    that lineup; the plain text keeps it) and "Every call below is your
    starter against your own bench" in a week where a % prints (the odds
    definition under card 01 says it)."""
    shown = _shown(render_email(w10))
    missing = [fact for fact in _facts(w10) if re.sub(r"\s+", " ", fact) not in shown]
    assert not missing, missing
    set_item = next(i for i in w10["checklist"] if anatomy.is_set_lineup(i))
    assert set_item["detail"] in text_summary(w10), "the text half lost the lineup list"


def test_every_engine_fact_reaches_the_web_report(w10) -> None:
    """The archive keeps every clause of the usage count (render.report:
    MIN_SHOWN_RATE), so the web report carries the long form."""
    page = _shown(rr.render(w10, TEMPLATE))
    facts = [f for f in _facts(w10)
             if f not in {anatomy.short_usage(s.get("usage")) for s in w10["lineup"]}]
    facts += [s["usage"] for s in w10["lineup"] if s.get("usage")]
    missing = [fact for fact in facts if re.sub(r"\s+", " ", fact) not in page]
    assert not missing, missing


def _email_rows(page: str) -> dict[str, str]:
    """Card 01's rows in the email, by player name (hairline to hairline)."""
    card = page[page.index("<!--sec:lineup-->"):page.index("<!--sec:", page.index(
        "<!--sec:lineup-->") + 1)]
    out = {}
    for chunk in card.split('background:#EEEAE1;">&nbsp;</td></tr>')[1:]:
        name = re.search(r"font-size:15px;font-weight:bold;[^>]*>([^<]+)</td>", chunk)
        if name:
            out[html.unescape(name.group(1))] = chunk
    return out


def test_one_slot_prints_one_percent_and_every_bar_is_drawn_from_it(w10) -> None:
    """Contract C9: Kittle's 0.715 printed 72% and was drawn 43% wide on one
    surface and 44% on another. Every bar is now render.report.bar_from_even
    of the PRINTED %, on the email, the web report and the closest call."""
    email = render_email(w10)
    web = rr.render(w10, TEMPLATE)
    text = text_summary(w10)
    rows = _email_rows(email)
    called = [s for s in w10["lineup"] if s.get("confidence") is not None]
    assert len(called) == 3, "the sample lost its three odds"
    for slot in called:
        pct = rr._pct(slot["confidence"])
        bar = rr.bar_from_even(pct)
        row = rows[slot["player_name"]]
        assert re.search(rf">{pct}%</td>", row), slot["player_name"]
        assert re.search(rf'<td width="{bar}%" style="height:6px;', row), slot["player_name"]
        web_row = re.search(rf'<div class="frow" data-i="\d+">.*?{re.escape(html.escape(slot["player_name"]))}'
                            r".*?</div>", web, re.S).group(0)
        assert f'<i style="width:{bar}%"></i></span><span class="fpct">{pct}%</span>' in web_row
        [line] = [x for x in text.splitlines()
                  if slot["player_name"] in x and x.rstrip().endswith("%")]
        assert line.rstrip().endswith(f"{pct}%"), line
    kittle = rr._pct(w10["regret"]["confidence"])
    assert (kittle, rr.bar_from_even(kittle)) == (72, 44)
    closest = email[email.index("<!--sec:closest-->"):email.index("<!--sec:plan-->")]
    assert '<td width="44%" style="height:8px;' in closest and ">72%</td>" in closest
    assert '<span class="cbar"><i style="width:44%"></i></span><b class="cpct">72%</b>' in web
    assert rr.bar_from_even(50) == 0 and rr.bar_from_even(100) == 100
    assert rr.bar_from_even(40) == 0


def test_every_surface_carries_the_cards_in_one_order(w10) -> None:
    """C1: masthead, any empty spot, then 01 lineup · 02 closest call · 03
    game plan · 04 if/then · 05 slot by slot · 06 rising · 07 receipts — on
    the email, the web report and the plain text."""
    keys = anatomy.sections(w10)
    assert keys == list(anatomy.SECTION_ORDER), keys
    email = render_email(w10)
    marks = [email.index(f"<!--sec:{k}-->") for k in keys]
    assert marks == sorted(marks)
    assert email.index(">Week 10</div>") < marks[0]
    web = rr.render(w10, TEMPLATE)
    sections = re.findall(r'<section class="card" data-sec="([a-z]+)">', web)
    assert sections == keys
    numbers = re.findall(r'<span class="n">(\d\d)</span>', web)
    assert numbers == [f"{i:02d}" for i in range(1, len(keys) + 1)]
    text = text_summary(w10)
    heads = ["YOUR LINEUP, DECIDED", "THE WEEK'S CLOSEST CALL", "YOUR GAME PLAN",
             "IF/THEN FOR GAMEDAY", "SLOT BY SLOT", "RISING ROLES", "RECEIPTS:"]
    at = [text.index(h) for h in heads]
    assert at == sorted(at), dict(zip(heads, at))


def test_a_card_drawn_for_a_page_holds_nothing_focusable(w10) -> None:
    """C3: the phone and the landing draw the same cards as pictures — a link
    or a checkbox inside a picture is a tab stop to nowhere. The web report
    draws them interactive: names link to their Slot by Slot row."""
    for key, model in anatomy.cards(w10):
        drawn = rr.card_html(key, model, "01", interactive=False)
        for focusable in ("<a ", "<input", "<button", "<label", "tabindex", "<select"):
            assert focusable not in drawn, (key, focusable)
        assert ' id="' not in drawn, key
    live = rr.card_html("lineup", anatomy.lineup(w10), "01", interactive=True)
    assert '<a href="#slot-0">Josh Allen</a>' in live
    slots = rr.card_html("slots", anatomy.slots(w10), "05", interactive=True)
    assert '<tr id="slot-0">' in slots
    assert '<label class="task"><input type="checkbox" class="box">' in live


def test_the_email_stays_inside_its_size_budget(w10) -> None:
    """C12: a 15-player Week 10 at most 48,000 bytes, Week 1 at most 33,000,
    a 30-player roster at most 60,000 — far under Gmail's ~102 KB clip,
    which would cut off the receipts and the way out."""
    assert len(render_email(w10).encode("utf-8")) <= 48_000
    assert len(render_email(_subscriber(1)).encode("utf-8")) <= 33_000
    big = copy.deepcopy(w10)
    big["bench"] = [dict(big["bench"][0], name=f"Bench Player {i}") for i in range(22)]
    assert len(render_email(big).encode("utf-8")) <= 60_000


def test_week_one_reads_as_an_opening_lineup() -> None:
    """C4: Week 1 has no projection and no odds anywhere. Its first card says
    what it is ("Your Opening Lineup"), each row carries the last-season basis
    its order rests on, there is no Proj or Odds head, and no row reads
    "status open" — a phrase about an injury report that does not exist yet."""
    report = _subscriber(1)
    email, text = render_email(report), text_summary(report)
    web = rr.render(report, TEMPLATE)
    for page in (email, web):
        assert "Your Opening Lineup" in page and "Your Lineup, Decided" not in page
        assert ">Proj<" not in page and ">Odds<" not in page
        assert "status open" not in page
    assert "YOUR OPENING LINEUP" in text and "status open" not in text
    shown = _shown(email)
    for slot in report["lineup"]:
        if slot.get("usage"):
            assert slot["usage"] in shown, slot["player_name"]
    assert not re.search(r">\d+%<", email)
    from render.email import preheader_for
    assert preheader_for(report) == ("Your opening lineup, every slot filled in last "
                                     "season's scoring order.")


def test_an_empty_spot_leads_the_report_as_an_alert(w10) -> None:
    """An empty spot is the one thing that costs points if left unread: it
    sits above card 01, in the alert tint, still a task to tick — and the
    game plan does not repeat it."""
    report = copy.deepcopy(w10)
    hole = {"action": "Jake Bates (K) isn't playing this week — we had nobody eligible "
                      "to put in, so that's a zero unless you add someone off waivers.",
            "deadline": "before this week's first kickoff", "urgency": "now",
            "zero": {"slots": ["K"], "certain": True}}
    report["checklist"] = [hole] + report["checklist"]
    email = render_email(report)
    alert = email.index("<!--sec:alert-->")
    assert email.index(">Week 10</div>") < alert < email.index("<!--sec:lineup-->")
    assert "background:#F7E3DE;border:1px solid #E7BDB3;" in email[alert:alert + 400]
    plan = email[email.index("<!--sec:plan-->"):email.index("<!--sec:ifthen-->")]
    assert "isn&#x27;t playing this week" not in plan
    web = rr.render(report, TEMPLATE)
    assert web.index('<div class="alert">') < web.index('<section class="card" data-sec="lineup">')


def test_the_email_has_no_side_bars_or_gold_text_on_paper(w10) -> None:
    """C6/C7: 1px borders only (no 3-4px side or top bars), and gold is a
    fill — bars, the button — never a colour of words on paper."""
    email = render_email(w10)
    assert not re.search(r"border-(left|top):[34]px", email)
    for match in re.finditer(r"color:#F2C230;[^>]*>([^<]*)<", email):
        # The only gold words are the card numbers, on the navy head.
        assert re.fullmatch(r"\x00?\d*|\d\d", match.group(1)), match.group(1)
    assert "linear-gradient" not in email


def test_republishing_chrome_never_pours_the_new_sheet_on_an_old_page(w10) -> None:
    """A2: `python -m render.live_sample --restamp` must stay idempotent on
    the page this week's cron built before the card markup existed AND on a
    page built after. The new sheet has none of the old page's rules, so an
    old page keeps the style it was drawn with until Tuesday rebuilds it."""
    import render.live_sample as live
    old = (REPO / "site" / "this-week.html").read_text(encoding="utf-8")
    if 'class="card"' not in old:
        once = live.restamp_style(live.restamp_chrome(old, byes_left=True, phase="season"),
                                  TEMPLATE)
        assert live.restamp_style(live.restamp_chrome(once, byes_left=True, phase="season"),
                                  TEMPLATE) == once
        assert re.search(r"<style>.*?</style>", old, re.S).group(0) == \
            re.search(r"<style>.*?</style>", once, re.S).group(0)
    report = copy.deepcopy(_sample(10))
    new = rr.render(report, TEMPLATE)
    once = live.restamp_style(live.restamp_chrome(new, byes_left=True, phase="season"),
                              TEMPLATE)
    assert live.restamp_style(live.restamp_chrome(once, byes_left=True, phase="season"),
                              TEMPLATE) == once
    assert rr.extract_design(TEMPLATE)[0] in once


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def test_nothing_widens_a_320_or_390_phone_in_a_real_browser(tmp_path, w10) -> None:
    """C12, measured: the email (Week 10 and Week 1), the Saturday check, the
    roster report and the web report, loaded in headless Chrome with phone
    emulation at 320 and 390. A page wider than its phone makes the layout
    viewport grow, so the width the page reports must be the phone's own."""
    import json
    import os
    import shutil
    import subprocess
    from datetime import datetime, timezone

    from engine.final_check import Change
    from render.final_check import render_final_check
    from render.preseason import email_html
    from test_preseason import _report as roster_report
    chrome = os.environ.get("CHROME_PATH") or (CHROME if Path(CHROME).exists()
                                               else shutil.which("google-chrome"))
    node = shutil.which("node")
    if not chrome or not node:
        pytest.skip("needs Chrome and node")
    fonts = tmp_path / "fonts"
    fonts.symlink_to(REPO / "site" / "fonts")
    pages = {
        "w10.html": render_email(w10),
        "w1.html": render_email(_subscriber(1)),
        "saturday.html": render_final_check(
            {"week": 10, "players": {}},
            [Change("swap", "Start Sam LaPorta at FLEX", "Tony Pollard is out (foot).")],
            datetime(2024, 11, 9, 16, tzinfo=timezone.utc)),
        "roster.html": email_html(roster_report()),
        "web.html": rr.render(_sample(10), TEMPLATE),
    }
    for name, page in pages.items():
        (tmp_path / name).write_text(page, encoding="utf-8")
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps([{"path": name, "widths": [320, 390], "settle": 300}
                                for name in pages]))
    run = subprocess.run([node, str(REPO / "run" / "launch_browser.mjs"),
                          tmp_path.as_uri(), chrome, str(jobs)],
                         capture_output=True, text=True, timeout=240)
    results = json.loads(run.stdout or "[]")
    if not results or any("fatal" in r for r in results):
        pytest.skip(f"Chrome could not run here: {run.stderr[-300:]}")
    assert len(results) == 2 * len(pages), run.stderr
    for result in results:
        assert result["innerWidth"] in (320, 390), result
        assert result["scrollWidth"] <= result["innerWidth"], \
            (result["path"], result["innerWidth"], result["scrollWidth"])


def test_the_saturday_and_roster_emails_open_like_the_report() -> None:
    """A7/A8: the Saturday check and the roster report wear the weekly
    email's masthead (the lockup, the big line, the meta line) and its cards
    — and the Saturday title no longer wraps to three lines at 390px."""
    from datetime import datetime, timezone

    from engine.final_check import Change
    from render.final_check import render_final_check
    check = render_final_check({"week": 10, "players": {}},
                               [Change("swap", "Start X at RB", "Y is out.")],
                               datetime(2024, 11, 9, 16, tzinfo=timezone.utc))
    lockup = 'Beat Your <span style="color:#F0B62A;">League</span>'
    assert lockup in check and ">Final check</div>" in check and ">Week 10</div>" in check
    assert "Week 10 · Final Check</div>" not in check
    assert ">swap</span>" in check and "border-radius:12px" in check
    from test_preseason import _report as roster_report

    from render.preseason import email_html
    roster = email_html(roster_report())
    assert lockup in roster and "border-radius:12px" in roster
    assert not re.search(r"border-left:[34]px", check + roster)


def test_the_email_week_line_and_stamp_look_like_the_phones(w10: dict) -> None:
    """Integration truth check (Oct 25 2026), side by side at 390px: the
    email printed its week unit as "PROJ" in letterspaced capitals beside a
    lowercase "realistic range", and its stamp in the meta line's #B9C2D0,
    while the web report and the landing's phone print "proj" lowercase like
    its neighbour and the stamp muted (#8FA3BC). One report, one look."""
    email = render_email(w10)
    week = re.search(r'126\.1</b><span style="([^"]*)"> proj</span>', email)
    assert week, "the week line's unit is not the plain lowercase 'proj'"
    assert "uppercase" not in week.group(1) and "font-size:12px" in week.group(1)
    stamp = anatomy.masthead(w10)["stamp"]
    assert f'color:#8FA3BC;padding-top:2px;">{html.escape(stamp)}</div>' in email
    assert ".mstamp{" in TEMPLATE and "color:#8FA3BC" in TEMPLATE.split(".mstamp{", 1)[1][:120]
