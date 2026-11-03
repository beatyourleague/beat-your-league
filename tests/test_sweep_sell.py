"""The Nov 3 2026 sell sweep: what a buyer reads on the landing, the join
page and the live sample, held where a test can hold it.

Each test names the finding it pins (SELL-n) and the reproduction.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from render import anatomy
from render import live_sample as live
from render import report as rr

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available (CI has it)")


def _markup(page: str) -> str:
    """The page as a buyer reads it: no scripts, styles or comments."""
    page = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
    page = re.sub(r"<style\b.*?</style>", "", page, flags=re.S)
    return re.sub(r"<!--.*?-->", "", page, flags=re.S)


def test_week_json_says_no_total_when_the_live_page_has_none() -> None:
    """SELL-1: site/week.json was written before `total` existed, so the
    hero's rule (`w.total !== false`) passed and linked "See this week's
    report" to a Week 8 page that opened on "Heads up: no projected total",
    its QB out on a bye. When the published page says it has no total, the
    file that gates every link to it must say so too."""
    week = json.loads((SITE / "week.json").read_text(encoding="utf-8"))
    page = (SITE / "this-week.html").read_text(encoding="utf-8")
    shown = re.search(r"Week (\d+) of the (\d{4}) season", page)
    assert shown, "this-week.html no longer says which week it is"
    same_week = (int(shown.group(1)) == int(week.get("week", -1))
                 and shown.group(2) == str(week.get("season")))
    if same_week and "no projected total" in page:
        assert week.get("total") is False, \
            "week.json lets the hero link a live page whose card 01 has no total"


def test_the_live_banner_uses_no_banned_word() -> None:
    """SELL-2: every live rebuild said "for a sample roster, exactly the way
    yours is built", and "exactly" is on the owner's banned list. The
    generator, the published page and the restamp all lose it."""
    meta = {"season": "2026", "week": 9, "solo": True, "live_demo": True,
            "generated_at": "2026-11-04T22:17:00+00:00"}
    text = " ".join(b["text"] for b in anatomy.bands({"meta": meta}))
    assert "the same way yours is built" in text
    assert "exactly" not in text
    assert "exactly" not in _markup((SITE / "this-week.html").read_text(encoding="utf-8"))
    old = "<p>for a sample roster, exactly the way yours is built. Rebuilt every Wednesday</p>"
    assert "exactly" not in live.restamp_chrome(old)


def test_the_landing_holds_the_league_pass_terms_while_it_is_held() -> None:
    """SELL-3: the strip under the price card stated the League Pass's price,
    stop and refund while join's STRIPE_LINK_PASS was empty and the League
    Pass page said "opens soon". LEAGUE_PASS_OPEN must agree with both pages,
    and while it is false the script says the pass opens soon. The static
    markup keeps the full terms (the fail-closed page other tests pin)."""
    flag = re.search(r"^const LEAGUE_PASS_OPEN = (true|false);", LANDING, re.M)
    assert flag, "the landing lost its League Pass flag"
    link = re.search(r'^const STRIPE_LINK_PASS = "([^"]*)";', JOIN, re.M).group(1).strip()
    seats = re.search(r"^const SEATS_OPEN = (true|false);", LEAGUE_PASS, re.M).group(1)
    on_sale = bool(link) and seats == "true"
    assert (flag.group(1) == "true") == on_sale, \
        "the landing's LEAGUE_PASS_OPEN disagrees with join's STRIPE_LINK_PASS / SEATS_OPEN"
    held = LANDING.split("if (!LEAGUE_PASS_OPEN) {")[1].split("\n}\n")[0]
    assert 'querySelector(".lpline .lpterms")' in held
    assert 'textContent = "Opens soon. $34.99 a month for the whole league."' in held
    assert "innerHTML" not in held


def test_the_hero_says_paste_your_roster_once() -> None:
    """SELL-5: "Paste your roster." and then "...CBS: paste your roster, no
    login" were the only two lines read before the phone."""
    hero = _markup(LANDING).split('<header class="hero">')[1].split("</header>")[0]
    assert len(re.findall(r"paste your roster", hero, re.I)) == 1, hero
    creds = re.search(r'<ul class="creds".*?</ul>', hero, re.S).group(0)
    assert "No login." in creds
    for app in ("espn/", "yahoo/", "sleeper/", "cbs/"):
        assert f'href="{app}"' in creds


def test_setup_is_a_noun_on_the_closer() -> None:
    """SELL-6: the closer read "Set up takes about two minutes." in all
    three of its script states."""
    assert "Set up takes" not in LANDING
    assert LANDING.count("Setup takes about two minutes.") == 3


def test_the_price_card_reads_any_mix_of_three_teams() -> None:
    """SELL-7: "Up to 3 teams: redraft, keeper, dynasty." reads as one of each,
    while run/teams.py takes any mix (and join/ says "or")."""
    card = _markup(LANDING).split('id="pass-card"')[1].split("</ul>")[0]
    assert "Up to 3 teams: redraft, keeper or dynasty." in card
    assert "redraft, keeper, dynasty" not in LANDING


def test_the_comparison_table_does_not_promise_odds_on_every_close_call() -> None:
    """SELL-8: the Close calls row promised "The odds, against your own bench"
    above a sample that prints odds on 3 of its 9 rows."""
    row = re.search(r'<th scope="row">Close calls</th>.*?</tr>', LANDING, re.S).group(0)
    assert "with odds where we can" in row
    assert "The odds, against your own bench" not in LANDING


@pytest.mark.parametrize("page", ("sample-report.html", "sample-first-week.html"))
def test_the_sample_stamp_drops_the_leading_zero(page: str) -> None:
    """SELL-9: the sample masthead read "Rebuilt Nov 03, 2026" while every
    other stamp says "Oct 27"."""
    meta = {"historical_demo": True, "season": "2024", "solo": True,
            "generated_at": "2026-11-03T18:00:00+00:00"}
    stamp = rr._generated_stamp(meta)
    assert stamp == "Rebuilt Nov 3, 2026 from the 2024 season archive", stamp
    text = (SITE / page).read_text(encoding="utf-8")
    assert not re.search(r"Rebuilt [A-Z][a-z]{2} 0\d,", text)
    fixture = (ROOT / "tests" / "fixtures" / "pass-stack.json").read_text(encoding="utf-8")
    assert not re.search(r"Rebuilt [A-Z][a-z]{2} 0\d,", fixture)


def test_the_roster_box_says_paste_here() -> None:
    """SELL-10: the textarea's placeholder was names only and never said where
    the paste goes."""
    box = re.search(r'<textarea id="roster-text"[^>]*placeholder="([^"]*)"', JOIN, re.S)
    assert box and box.group(1).startswith("Paste your roster here\n"), box


def _paste_listener() -> str:
    start = JOIN.index('searchBox.addEventListener("paste"')
    return JOIN[start:JOIN.index("\n  });\n", start) + 6]


def _run_paste(tmp_path: Path, clip: str, box: str) -> dict:
    script = """
const events = [];
const handlers = {};
const roster = { value: %s, focused: false,
  dispatchEvent(e) { events.push(e.type); }, focus() { this.focused = true; } };
const searchBox = { value: "Jo",
  addEventListener(type, fn) { handlers[type] = fn; } };
function $(id) { if (id !== "roster-text") throw new Error(id); return roster; }
let closed = 0;
function closeSuggestions() { closed += 1; }
class Event { constructor(type) { this.type = type; } }
%s
let prevented = false;
handlers.paste({ clipboardData: { getData: () => %s },
                 preventDefault() { prevented = true; } });
console.log(JSON.stringify({ box: roster.value, search: searchBox.value, events,
  focused: roster.focused, prevented, closed }));
""" % (json.dumps(box), _paste_listener(), json.dumps(clip))
    path = tmp_path / "paste.js"
    path.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@needs_node
def test_a_roster_pasted_into_the_name_field_lands_in_the_roster_box(tmp_path) -> None:
    """SELL-10: the one-name field sits above the paste box, and a text input
    drops line breaks, so fifteen pasted names became one search string. A
    multi-line paste now goes to the roster box, fires its input event (so a
    checked list goes stale like any edit) and moves focus there."""
    got = _run_paste(tmp_path, "Josh Allen\nBijan Robinson\n", "Ja'Marr Chase\n")
    assert got["prevented"] and got["focused"] and got["events"] == ["input"]
    assert got["box"] == "Ja'Marr Chase\nJosh Allen\nBijan Robinson\n"
    assert got["search"] == "" and got["closed"] == 1
    empty = _run_paste(tmp_path, "Josh Allen\r\nBijan Robinson", "  ")
    assert empty["box"] == "Josh Allen\r\nBijan Robinson"
    # One name is a search, as before: the field keeps it.
    one = _run_paste(tmp_path, "Josh Allen", "")
    assert not one["prevented"] and one["box"] == "" and one["events"] == []
