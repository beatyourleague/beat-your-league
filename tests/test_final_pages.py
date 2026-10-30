"""The final review's site findings (Oct 24 2026), each pinned to its reproduction.

FUN-* are the funnel lens's findings, COPY-* the copy lens's, and the rest the
lenses' improvements routed to the pages. Each docstring says what was seen
before the fix; the behaviour itself was also checked in headless Chrome at
320, 390 and 1440 (join driven through the roster check to the read-back).
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LANDING = (SITE / "index.html").read_text(encoding="utf-8")
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
HOW = (SITE / "how-it-works.html").read_text(encoding="utf-8")
PRIVACY = (SITE / "privacy.html").read_text(encoding="utf-8")
LEAGUE_PASS = (SITE / "league-pass.html").read_text(encoding="utf-8")
NOT_FOUND = (SITE / "404.html").read_text(encoding="utf-8")
EMAIL_CHECK = (SITE / "email-check.js").read_text(encoding="utf-8")

# Contract C5: the odds-gate clause, identical everywhere it appears.
GATE_CLAUSE = ("only where both players are playing, off the injury report and have "
               "enough games on record (never on team defenses)")
REFUND_BESIDE_PRICE = "a full refund until your second weekly report's week kicks off"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _flat(text: str) -> str:
    """Copy as a reader meets it: JS concatenation joined, whitespace collapsed."""
    return re.sub(r'"\s*\+\s*"', "", re.sub(r"\s+", " ", text))


def _visible(page: str) -> str:
    page = re.sub(r"(?is)<(head|script|style)\b.*?</\1>|<!--.*?-->", " ", page)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _js_function(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    return page[start:page.index("\n}\n", start) + 2]


def _node(script: str, tz: str = "America/New_York") -> object:
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          timeout=60, env={**os.environ, "TZ": tz})
    assert done.returncode == 0, f"node failed:\n{done.stderr}"
    return json.loads(done.stdout)


# --------------------------------------------------------------------- #
# FUN-1 / FUN-5 — every address that something is sent to is read back
# --------------------------------------------------------------------- #

def test_a_seat_claim_asks_about_a_mistyped_address_before_it_posts() -> None:
    """FUN-1, reproduced on a stub-wired copy: join/?pass=…&s=ppr&n=12&t=std,
    15 players checked, buyer.test@gmial.com, Claim my seat — no "Did you
    mean" box, and the Worker received {"kind":"seat","email":
    "buyer.test@gmial.com",…}: the seat branch returned before the typo guard,
    so the confirmation code went to a dead mailbox and spent one of the
    pass's daily codes. The check sits inside submitSeat, after the returns
    that send nothing and before the row is built (mutation: delete it)."""
    fn = _js_function(JOIN, "submitSeat")
    ask = fn.index("if (!typoSettled(email)) return;")
    for sends_nothing in ("if (!PASS_TOKEN)", "if (!FORM_ENDPOINT)", "if (seasonOver())"):
        assert fn.index(sends_nothing) < ask, sends_nothing
    assert ask < fn.index('const row = { kind: "seat"') < fn.index("fetch(FORM_ENDPOINT")


def test_one_typo_table_serves_both_pages_and_neither_page_copies_it() -> None:
    """FUN-5, reproduced with WAITLIST_ENDPOINT set: the landing's hero capture
    posted {"kind":"waitlist","email":"buyer.test@gmial.com"} and said "You're
    on the list" — a bounce on the one launch email — while the join page asked
    "Did you mean …?" of the same address. The fix is ONE table both pages
    load (b2b9dc8 recorded a doubled table that broke join's scripts): neither
    page declares it, both load site/email-check.js under its own digest, so a
    changed table is never served stale from a cache."""
    digest = hashlib.sha256((SITE / "email-check.js").read_bytes()).hexdigest()[:10]
    for name, page in (("landing", LANDING), ("join", JOIN)):
        assert f'<script src="/email-check.js?v={digest}"></script>' in page, \
            f"{name}: email-check.js changed; its tag needs ?v={digest}"
        assert "const DOMAIN_FIXES" not in page and "function suggestedEmail" not in page, name
        # Loaded before the page's own script, which reads it at submit.
        assert page.index("/email-check.js?v=") < page.index('<script>\n"use strict";')
    assert EMAIL_CHECK.count("const DOMAIN_FIXES = {") == 1
    assert "innerHTML" not in EMAIL_CHECK and "fetch(" not in EMAIL_CHECK


def test_the_landing_capture_asks_about_a_typo_once_before_anything_is_sent() -> None:
    """FUN-5: the question comes before the Worker post AND before the mailto
    fallback; pressing again with the same spelling goes ahead (the address may
    be real); the one-tap fix is built as text, never markup. Driven in Chrome:
    gmial asked, "Use buyer.test@gmail.com" posted the corrected address, and
    a second press of keep.me@gmial.com posted it as typed."""
    handler = LANDING.split('watchForm.addEventListener("submit"')[1].split("\n  });")[0]
    ask = handler.index("suggestedEmail(email)")
    assert ask < handler.index("if (WAITLIST_ENDPOINT)") < handler.index("window.location.href = \"mailto:")
    assert "watchKept !== email" in handler and "watchKept = email;" in handler
    assert 'typeof suggestedEmail === "function"' in handler, \
        "a failed load of email-check.js must not stop the capture"
    assert "innerHTML" not in handler


@needs_node
def test_the_shared_table_suggests_and_never_rewrites() -> None:
    """The table moved; its behaviour must not have (critique #1's cases)."""
    got = _node(EMAIL_CHECK + "\nconsole.log(JSON.stringify(['pat@gmial.com', "
                "'pat@Gmail.Co', 'x@example.cmo', 'pat@gmail.com', 'nope'].map(suggestedEmail)));")
    assert got == ["pat@gmail.com", "pat@gmail.com", "x@example.com", "", ""]


# --------------------------------------------------------------------- #
# FUN-3 / FUN-8 / FUN-9 / COPY-9 — the join page's money words
# --------------------------------------------------------------------- #

def test_the_sidebar_refund_limit_is_true_in_every_mode() -> None:
    """FUN-3, reproduced at join/?plan=pass, 1440: #terms-line read "— one per
    league." while the sticky sidebar beside it read "— one per person", on
    one screen. The sidebar now says what terms §5 says, in every mode."""
    trust = _flat(JOIN.split('<div class="trust">')[1].split("</div>")[0])
    assert "one per person (one per league for a League Pass)" in trust


def test_every_price_on_the_join_page_has_the_refund_beside_it() -> None:
    """FUN-8, measured at 390: the header said "$29 for the rest of the season
    — one payment, no subscription" at y=181 while the first refund statement
    sat ~2,000px below it (step 3 hidden until a roster is checked). The pitch
    carries the refund in the season, League Pass and Playoff variants."""
    static = _flat(re.search(r'<p id="header-pitch">(.*?)</p>', JOIN, re.S).group(1))
    assert "$29 for the rest of the season" in static and REFUND_BESIDE_PRICE in static
    flat = _flat(JOIN)
    for price in ("$69 for your whole league, rest of season", "$19 for the Playoff Pass"):
        at = flat.index(price)
        assert REFUND_BESIDE_PRICE in flat[at:at + 220], price


def test_the_one_time_offer_carries_no_subscription_leftovers() -> None:
    """FUN-9 / COPY-9 (M14, which had not landed): join said "a re-subscription
    after a refund is final" twice under a one-payment offer, its closed chip
    read "Season pass opens soon" for a product called the Rest-of-Season
    Pass, and How it works promised "on a yearly plan one reminder before it
    renews" when no yearly plan is sold in 2026. Contract C5's wording."""
    for name in ("join/index.html", "how-it-works.html", "index.html", "thanks.html",
                 "league-pass.html"):
        text = _flat((SITE / name).read_text(encoding="utf-8"))
        assert not re.search(r"re-?subscri", text, re.I), name
    assert _flat(JOIN).count("a second purchase after a refund is final") == 2
    assert '"Rest-of-Season Pass opens soon"' in _js_function(JOIN, "closedChipText")
    assert "Season pass opens soon" not in JOIN
    assert "yearly plan" not in HOW


# --------------------------------------------------------------------- #
# FUN-4 — a removed player stays removed
# --------------------------------------------------------------------- #

def _drop_handler() -> str:
    return JOIN.split('drop.addEventListener("click", () => {')[1].split("\n    });")[0]


ROSTER = ["Josh Allen", "Saquon Barkley", "Bijan Robinson", "Ja'Marr Chase",
          "Amon-Ra St. Brown", "George Kittle", "Tony Pollard", "Chase Brown",
          "Sam LaPorta", "Courtland Sutton", "Rome Odunze", "Jake Bates",
          "Denver Broncos", "Baltimore Ravens", "Jayden Reed"]


def _remove(text: str, name: str) -> dict:
    script = f"""
const fs = require("fs");
const R = require({str(SITE / "join" / "roster.js")!r});
const directory = R.buildDirectory(JSON.parse(fs.readFileSync({str(SITE / "join" / "players.json")!r}, "utf8")));
const box = {{ value: {json.dumps(text)} }};
const $ = (id) => (id === "roster-text" ? box : null);
const state = {{ directory, matches: R.resolveAll(directory, box.value) }};
function drop(match, index, position) {{ const draw = () => {{}};
{_drop_handler()}
}}
const before = box.value;
const index = state.matches.findIndex((m) => m.player && m.player.name === {json.dumps(name)});
if (index < 0) throw new Error("not on the list: " + {json.dumps(name)});
drop(state.matches[index], index, 0);
const onScreen = state.matches.map((m) => m.typed);
const reread = R.resolveAll(directory, box.value).map((m) => m.typed);
box.value = box.value.trim() + "\\nJoe Burrow";
const again = R.resolveAll(directory, box.value).filter((m) => m.player).map((m) => m.player.name);
console.log(JSON.stringify({{ changed: before !== box.value.replace(/\\nJoe Burrow$/, ""),
  sameAsScreen: JSON.stringify(reread) === JSON.stringify(onScreen), again }}));
"""
    return _node(script)


@needs_node
def test_a_removed_player_does_not_come_back_on_the_next_check() -> None:
    """FUN-4, reproduced: paste 15, Check, × on Josh Allen (14 rows), append
    "Joe Burrow" in the box, Check — 16 rows, Josh Allen back first, the ref
    starting with his id again, under "Looks right". The × handler spliced the
    list and left the box alone, and a re-check re-reads the whole box. His
    line now leaves the box too (mutation: drop `box.value = edited`), for a
    plain paste and for a tab-separated table copy alike."""
    for text in ("\n".join(ROSTER), "\n".join(f"{n}\tQB\tBUF" if n == "Josh Allen" else n
                                              for n in ROSTER)):
        got = _remove(text, "Josh Allen")
        assert got["changed"] and got["sameAsScreen"], got
        assert "Josh Allen" not in got["again"] and "Joe Burrow" in got["again"], got
        assert len(got["again"]) == 15


@needs_node
def test_the_box_is_never_edited_into_a_roster_nobody_chose() -> None:
    """FUN-4's guard: the box is edited only when it then reads back as exactly
    the rows left on screen. ESPN's one-cell-per-line copy ("Jalen Hurts / Phi
    / QB / CAR") leaves his team and opponent lines behind when his name line
    goes, and those can read as a defense; then the box is left as it was —
    the old behaviour — rather than turned into a list with a phantom DEF."""
    text = "\n".join(["Josh Allen", "Saquon Barkley", "Jalen Hurts", "Phi", "QB", "CAR",
                      "Bijan Robinson", "Ja'Marr Chase"])
    got = _remove(text, "Jalen Hurts")
    assert got["sameAsScreen"] or not got["changed"], got


# --------------------------------------------------------------------- #
# FUN-7 — no "checkout hasn't opened" beside a working buy button
# --------------------------------------------------------------------- #

def test_the_proving_window_captions_say_only_what_the_form_is_for() -> None:
    """FUN-7, reproduced with CHECKOUT_OPEN=true and CHECKOUT_CAN_COMPLETE=false
    (LAUNCH.md step 3 to step 4.4): "Set up my team" and "Get the
    Rest-of-Season Pass — $29" were live beside "Leave your email for one
    message the morning checkout opens." and "One email when signups open".
    That state now rewrites the capture's captions and button; Chrome shows
    "Not ready yet? Leave your email for one message from us, nothing else."
    under the clock and "Email me once" on the form."""
    block = LANDING.split("if (CHECKOUT_CAN_COMPLETE) {")[1].split("\n// Checkout closes with the season")[0]
    # Code only: the comment above it quotes the stale words on purpose.
    other = _flat("\n".join(line for line in block.split("} else {", 1)[1].splitlines()
                            if not line.lstrip().startswith("//")))
    for rewritten in ('querySelector(".heroline")', 'getElementById("closer-note")',
                      '"#watch-form button"', "watchDoneTail ="):
        assert rewritten in other, rewritten
    for stale in ("when signups open", "checkout opens", "Tell me when it opens"):
        assert stale not in other, stale
    assert "Not ready yet?" in other


# --------------------------------------------------------------------- #
# FUN-10 / FUN-11 / 404 — the small pages
# --------------------------------------------------------------------- #

def test_the_league_pass_chat_line_wraps_at_320() -> None:
    """FUN-10 (QA-09 had not landed): at 320px league-pass.html scrolled to
    333px — the bracketed "[your league's link, from your welcome email]" held
    on one line by white-space:nowrap. Chrome now measures 320/320."""
    rule = re.search(r"\.chatline \.blank\{([^}]*)\}", LEAGUE_PASS).group(1)
    assert "nowrap" not in rule


def test_the_league_pass_card_uses_the_landing_check_bullets() -> None:
    """Funnel improvement (D6 on this page): the price card kept the
    browser's disc bullets while the landing's card draws green check circles."""
    ul = re.search(r"\.price ul\{([^}]*)\}", LEAGUE_PASS).group(1)
    assert "list-style:none" in ul
    assert re.search(r"\.price li::before\{[^}]*background:var\(--turf\) url\(", LEAGUE_PASS)


def test_the_404_address_is_a_link() -> None:
    """Funnel improvement: every page's hello@ is a mailto link but the 404's,
    the one page a lost visitor lands on."""
    assert '<a href="mailto:hello@beatyourleague.com">hello@beatyourleague.com</a>' in NOT_FOUND
    assert "<b>hello@beatyourleague.com</b>" not in NOT_FOUND


def test_privacy_names_every_place_a_step_is_counted() -> None:
    """FUN-11, reproduced with the counter and WAITLIST_ENDPOINT set: the
    landing's capture posted /__count {"e":"waitlist","p":"index",…} while §3
    listed the counted steps as happening "on the signup page" only. The
    owner rule is that the policy says exactly what is collected."""
    calls = re.findall(r'window\.bylCount\("(\w+)"', LANDING)
    assert calls == ["waitlist"], calls
    # The free bye-week planner counts two steps of its own: a roster checked
    # and a waitlist row saved — and §3 names it for both.
    planner = (SITE / "byes" / "index.html").read_text(encoding="utf-8")
    assert sorted(set(re.findall(r'window\.bylCount\("(\w+)"', planner))) == ["roster", "waitlist"]
    body = _visible(PRIVACY)
    section3 = body[body.index("3. Cookies, analytics"):body.index("4. Who else")]
    assert ("joins the waitlist (on the front page, the signup page or the bye-week planner)"
            in section3)
    assert "checks a roster on the signup page or the bye-week planner" in section3


def test_privacy_describes_no_storage_the_site_does_not_do() -> None:
    """COPY-5: §3 still described the League Pass thank-you page reading the
    buyer's email out of session storage, a convenience contract C3 removed
    (b147b5e). The sentence is gone, and since the policy now says nothing is
    stored on your device, no page may use session storage at all."""
    body = _visible(PRIVACY)
    assert "session storage" not in body.lower() and "nothing is stored on your device" in body
    for path in SITE.rglob("*"):
        if path.suffix in (".html", ".js") and path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"sessionStorage|localStorage|document\.cookie|indexedDB",
                                 text), path.relative_to(SITE)


def test_privacy_counts_every_public_record_the_repo_commits() -> None:
    """COPY-6: §4 said three records beside the code are public (sends, the
    stop list, graded calls) while .gitignore un-ignores two more that the
    workflows commit — the deleted-customer list (privacy.yml force-adds it)
    and League Pass seat resets (run/seat_resets.py). Every file named must
    actually be committed, so the count cannot drift from the repo."""
    body = _visible(PRIVACY)
    section4 = body[body.index("4. Who else"):body.index("5. Your report")]
    assert "Five records it keeps beside the code are public" in section4
    for record in ("what has been sent", "the stop list", "the list of deleted customers",
                   "League Pass seat resets", "our record of graded calls"):
        assert record in section4, record
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for kept in ("!data/processed/sent.jsonl", "!data/processed/suppressed.txt",
                 "!data/processed/forgotten.txt", "!data/processed/seat-resets.txt",
                 "!data/processed/ledger/"):
        assert kept in ignore, kept


# --------------------------------------------------------------------- #
# COPY-3 (contract C5) — the gate stated as necessary, never sufficient
# --------------------------------------------------------------------- #

def test_the_gate_clause_is_one_string_on_every_surface() -> None:
    """COPY-3, reproduced on the published sample: Barkley and Robinson start
    over Chase Brown, all three playing, undesignated and with games on record,
    and the rows read "start · Chase Brown rising" with no odds — beneath a
    landing promising "a percentage prints wherever both players are playing,
    off the injury report and have enough games on record". The rising hold
    and the practice squad withhold pairs that pass all three checks, so the
    clause is "only where", identically on the meta and JSON-LD entity
    sentence, the landing's "The week's closest call" callout ("Odds against
    your own bench" until the sales review, the "Decided against your bench"
    step until Oct 28 2026) and the join page."""
    meta = re.search(r'<meta name="description" content="([^"]+)"', LANDING).group(1)
    product = next(n for n in json.loads(re.search(
        r'<script type="application/ld\+json">(.*?)</script>', LANDING, re.S).group(1))["@graph"]
        if n["@type"] == "Product")
    step = _flat(LANDING.split("<h3>The week's closest call</h3>")[1].split("</li>")[0])
    assert meta == product["description"]
    assert "the odds " + GATE_CLAUSE in meta
    # Review BUYER-2: the step defines the % in the report's own words
    # (render.report.ODDS_DEFINITION) before it says where it prints — the
    # landing's only readable definition of its one number.
    assert ("The % is the chance your starter outscores your best bench player at that "
            "spot, printed " + GATE_CLAUSE + ".") in step
    assert "the odds " + GATE_CLAUSE in _flat(_js_function(JOIN, "monthlyPlan"))
    for name in ("index.html", "join/index.html", "how-it-works.html", "thanks.html",
                 "league-pass.html"):
        text = _flat((SITE / name).read_text(encoding="utf-8"))
        assert "wherever both players" not in text, name
        assert "(not on team defenses)" not in text, name


def test_the_free_report_pitch_says_what_arrives_not_the_gate() -> None:
    """M15 (routed with COPY-3): join/?try=1 opened with the odds-gate
    definition — the exception, sold first. It says what lands now."""
    fn = _flat(_js_function(JOIN, "drawTrial"))
    pitch = fn[fn.index('"Free: "'):fn.index("One per person, no card.")]
    assert "every slot decided" in pitch and "if/then for late news" in pitch
    assert "odds" not in pitch and "injury report" not in pitch


# --------------------------------------------------------------------- #
# the landing — business and copy improvements
# --------------------------------------------------------------------- #

def test_the_refund_sits_under_the_heros_buy_button_with_no_price() -> None:
    """Business #1: the strongest true objection-killer (a no-questions refund
    until the second weekly report's week kicks off) sat only in the price
    card, ~4,700px down on a phone. Open, it is built under the hero's button
    and hidden with it at the season's end; the price card carries it in
    every state (the trust strip that also did went with contract B3). No
    price in the hero line (the hero rule)."""
    block = LANDING.split("if (CHECKOUT_OPEN) {")[1].split("if (CHECKOUT_CAN_COMPLETE)")[0]
    risk = _flat(block[block.index('const heroRow'):block.index("heroRow.after(risk)")])
    assert "Full refund, no questions, until your second weekly report's week kicks off" in risk
    assert "$" not in risk
    assert '"risk-line"' in _js_function(LANDING, "closeForSeason")
    card = _flat(LANDING.split('id="pass-card"')[1].split("</section>")[0])
    assert "Full refund, no questions, until your second weekly report's week kicks off" in card


def test_the_sunday_scene_sits_directly_under_the_hero() -> None:
    """Copy review: the page's best hook ("He was on your bench. He went for
    30. You lost by four.") sat after four feature tiles. It moved up to the
    first section after the hero, and since the owner's Oct 28 2026 plan it
    is the hero's own last line — the punchline under the headline and the
    phone, before any section (the trust strip that shared its rule went
    with contract B3)."""
    hero = LANDING.split('<header class="hero">', 1)[1].split("</header>", 1)[0]
    punch = re.search(r'<p class="punch">(.*?)</p>\s*$', hero, re.S)
    assert punch, "the Sunday scene is not the hero's last line"
    assert "He was on your bench. He went for 30. You lost by four." in _flat(punch.group(1))
    assert 'class="proof"' not in LANDING and 'class="credsec"' not in LANDING


def test_the_phone_says_not_every_row_gets_odds() -> None:
    """Business #7: the mockup showed a % on 3 of 4 rows while a real week's
    report can print odds on 3 of 9; a buyer expecting nine is a Week-2
    refund. The phone now shows the real card 01 (contract C11): all nine
    slots, odds on three, and every other row its reason in the report's own
    words — the disclosure is the report itself, not a caption about it."""
    card = LANDING.split('data-sec="lineup"')[1].split("</section>")[0]
    rows = re.findall(r'<div class="frow"[^>]*>(.*?)</div>', card, re.S)
    odds = [r for r in rows if 'class="fpct"' in r]
    assert len(rows) == 9 and 0 < len(odds) < len(rows), (len(rows), len(odds))
    for row in rows:
        if row not in odds:
            assert re.search(r'<span class="fnc[^"]*">[^<]+</span>', row), row
    assert "the bar starts at 50% (a toss-up)" in _flat(card)


def test_the_mid_season_answer_is_the_stronger_one_in_both_places() -> None:
    """Copy review: "Yes, it's built for it" was weak; the answer names what a
    playoff-push buyer gets, and the JSON-LD carries the same words."""
    faq = LANDING.split("<summary>Is it worth joining mid-season?</summary>")[1]
    answer = html.unescape(re.search(r'<div class="a">(.*?)</div>', faq, re.S).group(1))
    graph = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',
                                 LANDING, re.S).group(1))["@graph"]
    faqs = next(n for n in graph if n["@type"] == "FAQPage")["mainEntity"]
    ld = next(q for q in faqs if q["name"] == "Is it worth joining mid-season?")
    assert ld["acceptedAnswer"]["text"] == answer
    assert answer.startswith("Yes — it's built for the playoff push.")
    assert "usually lands within the hour" in answer
    assert "Subscribers alone pay for it" not in LANDING


def test_the_price_cards_first_line_is_the_outcome() -> None:
    """Copy review: the card led with the delivery mechanics ("Every weekly
    report from now…"); it leads with what the buyer gets, and the Playoff
    swap says the same."""
    span = _flat(LANDING.split('id="pass-span">')[1].split("</li>")[0])
    assert span.startswith("Your lineup decided every Tuesday from now through your title game")
    assert "Your lineup decided every Tuesday from Week " in _flat(
        _js_function(LANDING, "showPlayoffPass"))


def test_the_pricing_band_is_not_half_empty_at_1440() -> None:
    """Funnel improvement, seen at 1440: the single 520px card left about half
    the band as empty dark space. On a wide screen the card spans the band
    and sets its own list in a second column; nothing new is said, and below
    881px it is the same one-column card."""
    wide = re.search(r"@media \(min-width:881px\)\{\n    \.plans\.one\{grid-template-columns:"
                     r"minmax\(0,1fr\);\}(.*?)\n  \}", LANDING, re.S)
    assert wide, "the wide pricing layout is gone"
    assert ".plans.one .plan.founder > ul{grid-column:2;" in wide.group(1)


# --------------------------------------------------------------------- #
# the season clock and the open-state buttons, run under node
# --------------------------------------------------------------------- #

def _clock(week: dict, now: str, open_: bool, can: bool = True) -> dict:
    iife = LANDING.split("// The season clock.")[1]
    iife = iife[iife.index("(function () {"):iife.index("})();") + 5]
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
function node(text) { return { textContent: text, hidden: false,
  replaceChildren(...kids) { this.textContent = kids.map((k) => k.textContent).join(""); },
  appendChild(kid) { this.textContent += kid.textContent; } }; }
for (const [id, text] of Object.entries(%(start)s)) els[id] = node(text);
globalThis.window = globalThis;
globalThis.document = {
  getElementById: (id) => els[id] || null,
  querySelectorAll: () => [],
  createElement: () => node(""),
  createTextNode: (t) => node(t),
};
const W = %(week)s;
window.fetch = globalThis.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(W) });
const CHECKOUT_OPEN = %(open)s, PLAYOFF_PASS_READY = false, PLAYOFF_FROM_WEEK = 13;
let closed = null;
function closeForSeason(line) { closed = line; }
function showPlayoffPass() {}
%(iife)s
setTimeout(() => console.log(JSON.stringify({ closed,
  clock: els["season-clock"].textContent, open: els["open-line"] ? els["open-line"].textContent : null,
  hero: els["hero-open"].textContent, closer: els["closer-cta"].textContent })), 50);
"""
    start = {"season-clock": "Checkout is open." if open_ else "A new report every Tuesday of the season.",
             "hero-open": "Get my lineups",
             "closer-cta": "Get my lineups" if open_ else "Tell me when it opens",
             "sticky-cta": "Get my lineups" if open_ else "Tell me when it opens",
             "this-week-label": ""}
    if open_ and can:
        start["open-line"] = " Set up now and your first report lands today."
    return _node(script % {"now": json.dumps(now), "start": json.dumps(start),
                           "week": json.dumps(week), "open": "true" if open_ else "false",
                           "iife": iife})


WEEK7 = {"season": "2026", "week": 7, "last_week": 18, "lands_on": "2026-10-27",
         "built_at": "2026-10-20T17:15:45+00:00", "odds": 3, "closest_call": True, "cards": True,
         "first_kickoff": "2026-10-23T00:15:00Z", "recorded": True}


@needs_node
def test_mid_week_the_clock_and_the_button_name_the_week_a_buyer_gets() -> None:
    """Business #5, reproduced in the clock's own code: on the Wednesday after
    Week 8's build a buyer gets Week 8's report the hour they pay
    (run/intake.py), while the hero read "Week 9's report lands Tuesday. 9
    lineups…" beside "Set up your team and Week 8's report lands today" — the
    week and the count one short of what that buyer gets. Open, the clock now
    counts from the week a buyer gets first. Closed, it keeps the product's
    own calendar. Since the sales review every buy button says one verb,
    "Get my lineups" (the price card adds its price), so the week lives in
    the clock alone. Mutation: count from w.week + 1 always and the first
    case fails."""
    mid = {**WEEK7, "week": 8, "lands_on": "2026-11-03", "first_kickoff": "2026-10-30T00:15:00Z"}
    got = _clock(mid, "2026-10-28T16:00:00Z", open_=True)
    assert got["clock"] == "Week 8's report lands today. 10 lineups to a Week 17 title game, every one decided."
    assert got["open"] == " Set up now and your first report lands today."
    assert got["hero"] == got["closer"] == "Get my lineups"
    closed = _clock(mid, "2026-10-28T16:00:00Z", open_=False)
    assert closed["clock"].startswith("Week 9's report lands Tuesday. 9 lineups")
    assert closed["hero"] == "Get my lineups" and closed["closer"] == "Tell me when it opens"


@needs_node
def test_after_kickoff_the_open_line_names_only_what_the_clock_cannot() -> None:
    """Funnel review, seen in the open state: "Week 8's report lands Tuesday. …
    Set up your team: your roster report lands today, and Week 8's report on
    Tuesday." The second clause repeated the clock. Since the sales review
    the open line never names a week or "roster report" (an email a buyer
    has never heard of): it says the one thing true at every hour — "Set up
    now and your first report lands today." — and the clock names the week."""
    got = _clock(WEEK7, "2026-10-24T16:00:00Z", open_=True)
    assert got["clock"].startswith("Week 8's report lands Tuesday. 10 lineups")
    assert got["open"] == " Set up now and your first report lands today."
    assert got["hero"] == "Get my lineups"
    tuesday = _clock(WEEK7, "2026-10-27T11:00:00Z", open_=True)
    assert tuesday["clock"].startswith("Week 8's report lands today.")
    assert tuesday["open"] == " Set up now and your first report lands today."


@needs_node
def test_a_stale_week_file_leaves_the_static_words_and_the_plain_button() -> None:
    """The fallback: a week.json past its lands_on (a missed build) names no
    week anywhere — "Get my lineups" and the static clock stay."""
    got = _clock(WEEK7, "2026-11-05T16:00:00Z", open_=True)
    assert got["hero"] == "Get my lineups" and got["clock"] == "Checkout is open."


# --------------------------------------------------------------------- #
# How it works — the report's colours and reasons
# --------------------------------------------------------------------- #

def test_how_it_works_draws_the_report_in_the_reports_colours() -> None:
    """Funnel improvement: How it works drew the lineup's odds bars green and
    both deadline labels red, while every report (and the landing) draws the
    bar gold with a navy numeral, "before this week's first kickoff" green and
    "gameday morning" red — exactly as the published sample does.

    Truth pass (contract C6): the bars are FLAT gold (no gold gradient
    anywhere), the numeral navy, and a deadline is a chip — "ok" turf on its
    tint where it is met, "due" brick on its tint where it is not — the same
    chip class beside the same deadline as the sample report prints it."""
    css = "\n".join(re.findall(r"<style>(.*?)</style>", HOW, re.S))
    assert re.search(r"\n  \.fbar i\{[^}]*background:var\(--flag\);", css)
    assert re.search(r"\n  \.cmeter \.cbar i\{[^}]*background:var\(--flag\);", css)
    assert not re.search(r"gradient\([^)]*(?:--flag|F2C230|D9A81B)", css, re.I)
    assert re.search(r"\n  \.fpct\{[^}]*color:var\(--navy\)", css)
    assert ".chip.ok{color:#1E7A46;background:#E3F2E8;}" in css
    assert ".chip.due{color:#B3402F;background:#F9E6E1;}" in css
    chip = r'class="chip {}">before this week(?:&#x27;|\')s first kickoff</span>'
    # Review SLEEK-8: the sample's week has a Thursday-night starter, so its
    # first kickoff is a deadline still to meet and prints due, in the same
    # colour as "before Thursday's kickoff" (one moment, one colour);
    # render.anatomy.early_week decides, and a calm week keeps "ok".
    assert re.search(chip.format("due"), HOW)
    assert '<span class="chip due">gameday morning</span>' in HOW
    sample = (SITE / "sample-report.html").read_text(encoding="utf-8")
    # The tag is not the point (the checklist moved from divs to spans inside a
    # label, REPORT-CHROME, Oct 24 2026); the class beside each deadline is.
    # Since the card stack (contract C6) the deadline is a chip: .chip.ok turf,
    # .chip.due brick, in the sample and in the template that draws it.
    assert re.search(chip.format("due"), sample) and not re.search(chip.format("ok"), sample)
    assert 'class="chip due">before Thursday' in sample
    assert 'class="chip due">gameday morning</' in sample
    from render.report import TEMPLATE_PATH, extract_design
    tcss = extract_design(TEMPLATE_PATH.read_text(encoding="utf-8"))[0]
    assert ".chip.ok{color:var(--turf);" in tcss and ".chip.due{color:var(--brick);" in tcss


def test_how_it_works_lists_each_reason_a_row_has_no_odds() -> None:
    """Funnel improvement: "Rows with no percentage" was a ten-line paragraph.
    It is a list, one reason a bullet, in the report's own terms, with the
    checks test_site.py pins still inside it."""
    dd = HOW.split("<dt>Rows with no percentage</dt>")[1].split("</dd>")[0]
    reasons = re.findall(r"<li><b>([^<]+)</b>", dd)
    assert reasons == ["Not playing, or on the injury report.", "Reserve list or practice squad.",
                       "Too few games.", "A defense.", "No bench player there.",
                       "A rising bench player."], reasons


def test_how_it_works_carries_no_betting_slang_or_market_words() -> None:
    """Owner rule (no betting words but "not betting picks"), the site half of
    the copy lens's COPY-8: "a strong lean, not a lock" is tout slang and
    "when the week's game lines are in" named the market input no surface may
    cite. Plain words now, the same facts."""
    text = _visible(HOW)
    for gone in ("lean", "a lock", "game lines"):
        assert not re.search(r"\b" + gone + r"\b", text, re.I), gone
    assert "A 70% call is a clear favorite, not a certainty: it can still lose." in text
    assert "It's paid for only by the people who buy it" in text
