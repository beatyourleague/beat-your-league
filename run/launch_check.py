"""Launch readiness — `make launch-check`.

Usage:
    python -m run.launch_check            # everything (≈4 minutes)
    python -m run.launch_check --fast     # skip the test suite, browser and proving run
    python -m run.launch_check --offline  # skip DNS and the live site

One command that answers "can we take money today, and will the people who pay
like what they get?" — as far as a machine can answer it. Every gate is one of:

    PASS   checked and fine
    FAIL   checked and broken: fix before the first payment (exit code 1)
    WARN   works, but costs sales or trust; fix soon
    OWNER  waiting on a setup step only the owner can do (LAUNCH.md)
    SKIP   could not be checked here (no Chrome, offline, not signed in)

The verdict is READY only with no FAIL and no OWNER. Read-only: it builds a
report in memory, serves site/ on a local port and loads pages; it writes
nothing in the repo, records nothing and sends nothing.

The gates came from the launch-readiness audit (Oct 2026): research into who
pays for fantasy tools, buyer-persona walkthroughs, a product review of real
reports, and website, operations, economics and compliance audits. What a
machine cannot judge — whether the copy persuades the people who pay — is in
that audit's report (reports/launch-readiness.md); this keeps the rest true.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
DOMAIN = "beatyourleague.com"
LIVE = f"https://{DOMAIN}"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Pages a buyer can reach before paying. They sell, so they carry the
# selling rules: no grading figures, no banned words, the product is a report.
SELLING = ("index.html", "join/index.html", "league-pass.html", "how-it-works.html",
           "thanks.html", "sample-report.html", "sample-first-week.html",
           "this-week.html")
# Every page whose browser behaviour matters, at phone and desktop width.
BROWSER_PAGES = (
    ("index.html", (360, 390, 1280)), ("join/index.html", (390, 1280)),
    ("join/index.html?plan=monthly", (390,)), ("join/index.html?plan=pass", (390,)),
    ("join/index.html?pass=1", (390,)), ("join/index.html?try=1", (390,)),
    ("join/index.html?update=1", (390,)), ("join/confirm.html", (390,)),
    ("how-it-works.html", (390, 1280)), ("league-pass.html", (390, 1280)),
    ("sample-report.html", (390, 1280)), ("this-week.html", (390,)),
    ("thanks.html", (390,)), ("terms.html", (390,)), ("privacy.html", (390,)),
    ("compare/index.html", (390,)), ("404.html", (390,)),
)
BANNED = r"\b(calibrated|tested|proven|accurate)\b"
BETTING = r"\b(parlay|sportsbook|against the spread|bet now|odds boost|wager|bookmaker)\b"
PERSONAL_DOMAINS = r"@(gmail|googlemail|outlook|hotmail|live|yahoo|icloud|me|aol|proton|protonmail)\.(com|me)"
REQUIRED_SECRETS = ("STRIPE_API_KEY", "STRIPE_PAYMENT_LINKS", "EMAIL_PROVIDER", "EMAIL_FROM",
                    "EMAIL_REPLY_TO", "RESEND_API_KEY", "SITE_URL", "BILLING_PORTAL_URL",
                    "FORM_ENDPOINT", "FORM_API_KEY", "UPDATE_SECRET")


@dataclass
class Gate:
    area: str
    name: str
    status: str
    detail: str = ""


def _gate(area: str, name: str, ok: bool, detail_fail: str, detail_ok: str = "",
          fail: str = "FAIL") -> Gate:
    return Gate(area, name, "PASS" if ok else fail, detail_ok if ok else detail_fail)


# --------------------------------------------------------------------- #
# reading pages
# --------------------------------------------------------------------- #

def pages() -> list[Path]:
    return sorted(p for p in SITE.rglob("*.html"))


def rel(path: Path) -> str:
    return str(path.relative_to(SITE))


def visible_text(page: str) -> str:
    """What a reader sees: no scripts, styles, comments or tags."""
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", " ", page,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text))


class _Refs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.lang = ""
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang") or ""
        if tag == "title":
            self._in_title = True
        for key in ("id", "name"):
            if a.get(key) and tag != "meta":
                self.ids.add(a[key])
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name:
                self.meta[name] = a.get("content") or ""
        if tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href") or ""
        for key in ("href", "src"):
            if a.get(key) and not (tag == "link" and (a.get("rel") or "") in
                                   ("preconnect", "dns-prefetch")):
                self.refs.append(a[key])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse(path: Path) -> _Refs:
    p = _Refs()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def js_constants(page: str) -> dict[str, str]:
    """`const NAME = value;` at the top level of a page's scripts."""
    out = {}
    for m in re.finditer(r'^const ([A-Z_]+) = ("[^"]*"|true|false|\d+);', page, re.M):
        out[m.group(1)] = m.group(2).strip('"')
    return out


# --------------------------------------------------------------------- #
# gates: the site, read as files
# --------------------------------------------------------------------- #

def check_links() -> list[Gate]:
    broken: list[str] = []
    parsed = {p: parse(p) for p in pages()}
    for page, refs in parsed.items():
        for ref in refs.refs:
            if re.match(r"^(https?:|mailto:|tel:|javascript:|data:|#$)", ref):
                continue
            target, _, anchor = ref.partition("#")
            target = target.split("?")[0]
            if not target:
                dest = page
            elif target.startswith("/"):
                dest = SITE / target.lstrip("/")
            else:
                dest = (page.parent / target).resolve()
            if dest.is_dir() or str(target).endswith("/"):
                dest = dest / "index.html"
            if not dest.exists():
                broken.append(f"{rel(page)} → {ref}")
                continue
            if anchor and dest.suffix == ".html":
                ids = parsed[dest].ids if dest in parsed else parse(dest).ids
                if anchor not in ids:
                    broken.append(f"{rel(page)} → {ref} (no #{anchor})")
    return [_gate("Site", "Every internal link and asset resolves", not broken,
                  f"{len(broken)} broken: " + "; ".join(broken[:6]),
                  f"{sum(len(r.refs) for r in parsed.values())} references across {len(parsed)} pages")]


def check_page_basics() -> list[Gate]:
    problems = []
    for page in pages():
        text = page.read_text(encoding="utf-8")
        if 'http-equiv="refresh"' in text:
            continue                                   # the legal.html redirect stub
        p = parse(page)
        noindex = "noindex" in (p.meta.get("robots") or "")
        missing = [k for k, ok in (("lang", p.lang), ("title", p.title.strip()),
                                   ("viewport", "viewport" in p.meta),
                                   ("description", p.meta.get("description")),
                                   ("canonical", p.canonical or noindex or page.name == "404.html"),
                                   ("og:image", p.meta.get("og:image") or noindex
                                    or page.name == "404.html")) if not ok]
        if missing:
            problems.append(f"{rel(page)}: {', '.join(missing)}")
    return [_gate("Site", "Every page has lang, title, viewport, description, canonical, share image",
                  not problems, "; ".join(problems[:6]), f"{len(pages())} pages")]


def check_scripts() -> list[Gate]:
    node = shutil.which("node")
    if not node:
        return [Gate("Site", "Every page script parses", "SKIP", "node is not installed")]
    bad, ld_bad, count = [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for page in pages():
            text = page.read_text(encoding="utf-8")
            for i, m in enumerate(re.finditer(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>",
                                              text, re.S)):
                attrs, body = m.group(1), m.group(2)
                if "ld+json" in attrs:
                    try:
                        json.loads(body)
                    except json.JSONDecodeError as exc:
                        ld_bad.append(f"{rel(page)}: {exc}")
                    continue
                count += 1
                src = Path(tmp) / f"s{count}.js"
                src.write_text(body, encoding="utf-8")
                r = subprocess.run([node, "--check", str(src)], capture_output=True, text=True)
                if r.returncode:
                    bad.append(f"{rel(page)} script {i + 1}: "
                               f"{(r.stderr.strip().splitlines() or ['?'])[-1]}")
        for js in SITE.rglob("*.js"):
            r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
            if r.returncode:
                bad.append(f"{rel(js)}: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    return [_gate("Site", "Every page script parses", not bad, "; ".join(bad[:5]),
                  f"{count} inline scripts"),
            _gate("Site", "Structured data (JSON-LD) is valid JSON", not ld_bad, "; ".join(ld_bad))]


def check_selling_copy() -> list[Gate]:
    hits_banned, hits_bet, hits_file, hits_personal = [], [], [], []
    for name in SELLING:
        path = SITE / name
        if not path.exists():
            continue
        text = visible_text(path.read_text(encoding="utf-8"))
        for m in re.finditer(BANNED, text, re.I):
            hits_banned.append(f"{name}: …{text[max(0, m.start() - 30):m.end() + 20]}…")
        for m in re.finditer(BETTING, text, re.I):
            hits_bet.append(f"{name}: {m.group(0)}")
        for m in re.finditer(r"\b(?:this|your|the|weekly|first|roster|a) files?\b(?! (?:a|an) )",
                             text, re.I):
            context = text[max(0, m.start() - 15):m.end() + 15]
            if "on file" not in context:
                hits_file.append(f"{name}: …{context}…")
    for page in pages():
        if re.search(PERSONAL_DOMAINS, page.read_text(encoding="utf-8"), re.I):
            hits_personal.append(rel(page))
    retired = []
    for name in SELLING:
        path = SITE / name
        if not path.exists():
            continue
        text = visible_text(path.read_text(encoding="utf-8"))
        for phrase in RETIRED_CLAIMS:
            if phrase.lower() in text.lower():
                retired.append(f"{name}: '{phrase}'")
    landing = (SITE / "index.html").read_text(encoding="utf-8")
    hero = landing.split('<header class="hero">')[1].split("</header>")[0] \
        if '<header class="hero">' in landing else ""
    missing_apps = [a for a in ("ESPN", "Yahoo", "Sleeper", "CBS") if a not in hero]
    return [
        _gate("Copy", "No claim the audit retired (false or unprovable lines)", not retired,
              "; ".join(retired[:5])),
        _gate("Copy", "The hero names the league apps it works with", not missing_apps,
              f"missing: {', '.join(missing_apps)}", fail="WARN"),
        _gate("Copy", "The FAQ says the same thing to people and to search engines",
              _faq_twin_ok(landing), "the JSON-LD FAQ answers differ from the visible ones"),
        _gate("Copy", "No banned claim words on selling pages (calibrated, tested, proven, accurate)",
              not hits_banned, "; ".join(hits_banned[:5])),
        _gate("Copy", "No betting language on selling pages", not hits_bet, "; ".join(hits_bet[:5])),
        _gate("Copy", "The product is a report, never a file", not hits_file,
              "; ".join(hits_file[:5]), fail="WARN"),
        _gate("Copy", "No personal email address on any page", not hits_personal,
              ", ".join(hits_personal)),
    ]


# Lines the launch audit found false, unprovable or contradicted by the code.
RETIRED_CLAIMS = ("cheaper than one buy-in", "Nobody answers", "From Sunday afternoon to Monday",
                  "sign-in code", "fifteen seconds", "in one click, any time",
                  "Cancel any time yourself, in one click", "renews automatically each season")


def _faq_twin_ok(landing: str) -> bool:
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', landing, re.S)
    if not block:
        return False
    try:
        graph = json.loads(block.group(1))["@graph"]
        faq = next(n for n in graph if n["@type"] == "FAQPage")
    except (ValueError, StopIteration, KeyError):
        return False
    visible = {}
    for q, a in re.findall(r"<summary>(.*?)</summary>\s*<div class=\"a\">(.*?)</div>", landing, re.S):
        a = re.sub(r"\s*\(<a href=\"sample-first-week.html\">.*?</a>\)", "", a, flags=re.S)
        visible[html.unescape(q)] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", a))).strip()
    return len(visible) == len(faq["mainEntity"]) and all(
        visible.get(i["name"]) == i["acceptedAnswer"]["text"] for i in faq["mainEntity"])


def check_prices() -> list[Gate]:
    from render.welcome import MONTHLY_PRICE, PASS_PRICE, SEASON_PRICE
    landing = (SITE / "index.html").read_text(encoding="utf-8")
    join = (SITE / "join/index.html").read_text(encoding="utf-8")
    lp = (SITE / "league-pass.html").read_text(encoding="utf-8")
    season = re.search(r'class="price">\$(\d+) <small>/ season', landing)
    monthly = re.search(r'class="price">\$([\d.]+) <small>/ month', landing)
    lp_amt = re.search(r'class="amt">\$(\d+)', lp)
    seen = {"landing season": season and "$" + season.group(1),
            "landing monthly": monthly and "$" + monthly.group(1),
            "league pass page": lp_amt and "$" + lp_amt.group(1)}
    want = {"landing season": SEASON_PRICE, "landing monthly": MONTHLY_PRICE,
            "league pass page": PASS_PRICE}
    wrong = [f"{k} shows {seen[k]} but the welcome email says {want[k]}"
             for k in want if seen[k] != want[k]]
    for label, price in ((f"Season pass · {SEASON_PRICE}", SEASON_PRICE),
                         (f"Monthly · {MONTHLY_PRICE}", MONTHLY_PRICE),
                         (f"Continue to checkout — {SEASON_PRICE}", SEASON_PRICE),
                         (f"— {MONTHLY_PRICE}/mo", MONTHLY_PRICE),
                         (f"Buy the League Pass — {PASS_PRICE}", PASS_PRICE)):
        if label not in join:
            wrong.append(f"join page lacks '{label}'")
    return [_gate("Funnel", "Every surface quotes the same three prices", not wrong,
                  "; ".join(wrong), f"{MONTHLY_PRICE}/mo · {SEASON_PRICE}/season · "
                                    f"{PASS_PRICE} League Pass")]


def check_funnel_config() -> list[Gate]:
    landing = js_constants((SITE / "index.html").read_text(encoding="utf-8"))
    join = js_constants((SITE / "join/index.html").read_text(encoding="utf-8"))
    lp = js_constants((SITE / "league-pass.html").read_text(encoding="utf-8"))
    links = {k: join.get(k, "") for k in ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY",
                                          "STRIPE_LINK_PASS")}
    empty = [k for k, v in links.items() if not v]
    open_ = landing.get("CHECKOUT_OPEN") == "true"
    can = landing.get("CHECKOUT_CAN_COMPLETE") == "true"
    trial = landing.get("TRIAL_OPEN") == "true"
    form = join.get("FORM_ENDPOINT", "")
    gates = []
    if empty:
        gates.append(Gate("Funnel", "Checkout can take money", "OWNER",
                          f"{len(empty)} of 3 payment links empty — LAUNCH.md steps 1–3, then "
                          f"they go back into site/join/index.html"))
    else:
        gates.append(Gate("Funnel", "Checkout can take money", "PASS", "all three payment links set"))
    gates.append(_gate("Funnel", "The landing never sells a checkout that cannot complete",
                       not (open_ and links["STRIPE_LINK_SEASON"] == "")
                       and not (can and empty),
                       "CHECKOUT_OPEN/CHECKOUT_CAN_COMPLETE is on while a payment link is empty"))
    gates.append(_gate("Funnel", "Landing and League Pass agree on whether checkout is open",
                       landing.get("CHECKOUT_OPEN") == lp.get("CHECKOUT_OPEN"),
                       f"index CHECKOUT_OPEN={landing.get('CHECKOUT_OPEN')}, "
                       f"league-pass CHECKOUT_OPEN={lp.get('CHECKOUT_OPEN')}"))
    gates.append(_gate("Funnel", "The free-report button only shows when requests can be received",
                       not (trial and not form),
                       "TRIAL_OPEN is on but FORM_ENDPOINT is empty: the button posts nowhere"))
    waitlist = landing.get("WAITLIST_ENDPOINT", "")
    if not waitlist and not can:
        gates.append(Gate("Funnel", "Waitlist sign-ups are collected automatically", "OWNER",
                          "WAITLIST_ENDPOINT is empty, so the hero form opens a pre-filled email "
                          "to hello@ and nothing adds it to the list run/waitlist.py mails — "
                          "deploy the form Worker (LAUNCH.md step 5)"))
    else:
        gates.append(Gate("Funnel", "Waitlist sign-ups are collected automatically", "PASS",
                          "posts to the form Worker" if waitlist else "checkout is open"))
    if not form:
        gates.append(Gate("Funnel", "League Pass seats, roster updates and free reports can be received",
                          "OWNER", "FORM_ENDPOINT is empty (LAUNCH.md step 5): seats refuse, "
                                   "reports carry the reply route, the free report stays hidden"))
    else:
        gates.append(Gate("Funnel", "League Pass seats, roster updates and free reports can be received",
                          "PASS", form))
    confirm = js_constants((SITE / "join/confirm.html").read_text(encoding="utf-8"))
    endpoints = {k: v for k, v in (("index WAITLIST_ENDPOINT", landing.get("WAITLIST_ENDPOINT", "")),
                                   ("join FORM_ENDPOINT", form),
                                   ("join NOTIFY_LIST_ENDPOINT", join.get("NOTIFY_LIST_ENDPOINT", "")),
                                   ("confirm FORM_ENDPOINT", confirm.get("FORM_ENDPOINT", ""))) if v}
    gates.append(_gate("Funnel", "Every page posts to the same form Worker",
                       len(set(endpoints.values())) <= 1,
                       "; ".join(f"{k}={v}" for k, v in endpoints.items()),
                       next(iter(endpoints.values()), "none set yet")))
    gates.append(_gate("Funnel", "The form Worker sits on our own domain",
                       not any("workers.dev" in v for v in endpoints.values()),
                       "a *.workers.dev address is easily blocked and looks unofficial — "
                       f"use forms.{DOMAIN}", fail="WARN"))
    seats_open = lp.get("SEATS_OPEN") == "true"
    gates.append(_gate("Funnel", "The League Pass is never sold before seats can be claimed",
                       # The page builds its Buy button only when CHECKOUT_OPEN and
                       # SEATS_OPEN are both true, so SEATS_OPEN is the one to guard.
                       not (seats_open and not form),
                       "league-pass.html has SEATS_OPEN on while FORM_ENDPOINT is empty "
                       "(seats would refuse)"))
    contact = landing.get("CONTACT_EMAIL", "")
    gates.append(_gate("Funnel", "A project inbox (not a personal one) is the contact route",
                       contact.endswith("@" + DOMAIN), f"CONTACT_EMAIL={contact or 'empty'}",
                       contact))
    return gates


def check_week_json() -> list[Gate]:
    path = SITE / "week.json"
    try:
        w = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Gate("Site", "Season clock data (week.json) is readable", "WARN",
                     f"{exc} — the hero falls back to its static sentence")]
    from datetime import date
    lands = w.get("lands_on")
    stale = not lands or date.fromisoformat(lands) < date.today()
    return [Gate("Site", "Season clock data (week.json) is current",
                 "WARN" if stale else "PASS",
                 f"week {w.get('week')}, next report lands {lands or 'unknown'}"
                 + (" — stale until the next Tuesday build (the hero shows its static sentence)"
                    if stale else ""))]


# --------------------------------------------------------------------- #
# gates: the product itself
# --------------------------------------------------------------------- #

def check_product() -> list[Gate]:
    """This week's live sample, built through the real pipeline, held to what a
    paying buyer would notice."""
    try:
        from render.email import render_email, subject_for, text_summary
        from render.live_sample import build
        report = build()
    except Exception as exc:  # noqa: BLE001
        from run.solo import SeasonOver
        if isinstance(exc, SeasonOver):
            return [Gate("Product", "This week's report builds", "SKIP", f"offseason: {exc}")]
        return [Gate("Product", "This week's report builds", "FAIL", f"{type(exc).__name__}: {exc}")]
    gates = [Gate("Product", "This week's report builds", "PASS",
                  f"{report['meta']['season']} week {report['meta']['week']}, sample roster")]
    lineup = report["lineup"]
    empty = [s["slot"] for s in lineup if not s.get("player_id")]
    gates.append(_gate("Product", "Every starting slot is filled", not empty,
                       f"empty: {', '.join(empty)}"))
    out = [s for s in lineup if any(f.get("kind") == "out" for f in s.get("flags") or [])]
    told = " ".join(c["action"] for c in report["checklist"])
    unflagged = [s["player_name"] for s in out if s["player_name"].split()[-1] not in told]
    gates.append(_gate("Product", "A starter who can't play is always named in the checklist",
                       not unflagged, f"silent: {', '.join(unflagged)}",
                       f"{len(out)} such starter(s), all named" if out else "none this week"))
    odds = [s["confidence"] for s in lineup if s.get("confidence") is not None]
    absurd = [p for p in odds if not 0.5 <= p <= 0.99]
    gates.append(_gate("Product", "Every printed % is between 50 and 99", not absurd,
                       f"out of range: {absurd}"))
    defense_odds = [s["slot"] for s in lineup if s.get("position") == "DEF"
                    and s.get("confidence") is not None]
    gates.append(_gate("Product", "No % on a team defense (graded D: no skill)", not defense_odds,
                       f"printed on {defense_odds}"))
    gates.append(Gate("Product", "The live sample shows the product's odds",
                      "PASS" if len(odds) >= 3 else "WARN",
                      f"{len(odds)} of {len(lineup)} slots carry a % this week"
                      + ("" if len(odds) >= 3 else
                         " — the landing links this page as proof; a week of byes on the "
                         "sample roster leaves it with nothing to show")))
    mail = render_email(report)
    size = len(mail.encode("utf-8"))
    gates.append(_gate("Product", "The email stays under Gmail's 102 KB clip", size < 100_000,
                       f"{size / 1024:.0f} KB", f"{size / 1024:.0f} KB"))
    text = text_summary(report)
    gates.append(_gate("Product", "The plain-text half carries the lineup and the way out",
                       "GAME PLAN" in text and "unsubscrib" in text.lower(),
                       "missing GAME PLAN or the cancel/unsubscribe line"))
    gates.append(_gate("Product", "The subject line names the week",
                       f"Week {report['meta']['week']}" in subject_for(report), subject_for(report)))
    return gates


BATTERY = (("ppr", 12, "std"), ("half_ppr", 10, "std"), ("standard", 14, "std"),
           ("ppr", 12, "sf"), ("half_ppr", 12, "nokd"))
TEMPLATE_SLOTS = {
    "std": ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"),
    "sf": ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"),
    "nokd": ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX"),
}


def check_product_battery() -> list[Gate]:
    """The sample roster under five setups, joined to TODAY's roster status and
    the schedule's byes OUTSIDE the report's own availability data — the first
    version of this check trusted that data and passed a report that started an
    injured-reserve receiver (launch audit)."""
    import csv
    from engine.availability import ROSTER_OUT
    from engine.subscriber import RosterSpec
    from render.email import render_email
    from render.live_sample import LIVE_ROSTER
    from run.solo import CACHE_DIR, SeasonOver, load_week_data, report_for
    try:
        data = load_week_data(CACHE_DIR)
    except SeasonOver as exc:
        return [Gate("Product", "Five league setups build sound reports", "SKIP", str(exc))]
    status: dict[str, str] = {}
    with (CACHE_DIR / "players.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("status") or "").upper() in ROSTER_OUT:
                status[row["gsis_id"]] = ROSTER_OUT[row["status"].upper()]
    byes = data.availability.bye_teams or set()
    known = {p.player_id for p in data.directory.players}
    roster = tuple(p for p in LIVE_ROSTER if p in known)
    silent, bad_alt, absurd, defense, wide = [], [], [], [], []
    for scoring, size, template in BATTERY:
        label = f"{scoring}/{size}/{template}"
        report = report_for(RosterSpec(player_ids=roster, slots=TEMPLATE_SLOTS[template],
                                       scoring=scoring, label="Sample roster"),
                            data, league_size=size)
        told = " ".join(c["action"] for c in report["checklist"])
        for slot in report["lineup"]:
            pid = slot.get("player_id") or ""
            team = (data.availability.statuses or {}).get(pid, {}).get("team")
            cannot = pid in status or (team in byes and not pid.startswith("DEF-")) \
                or (pid.startswith("DEF-") and pid.split("-", 1)[1] in byes)
            flagged = any(f.get("kind") == "out" for f in slot.get("flags") or [])
            if cannot and not (flagged and slot["player_name"].split()[-1] in told):
                silent.append(f"{label}: {slot['player_name']}")
            if slot.get("confidence") is not None:
                if not 0.5 <= slot["confidence"] <= 0.99:
                    absurd.append(f"{label}: {slot['player_name']}")
                if slot.get("position") == "DEF":
                    defense.append(label)
                if slot.get("alternative_id") in status:
                    bad_alt.append(f"{label}: {slot.get('alternative_name')}")
        if len(render_email(report).encode("utf-8")) >= 100_000:
            wide.append(label)
    n = len(BATTERY)
    return [
        _gate("Product", "No player who can't play is started without a flag and a checklist line",
              not silent, "; ".join(silent[:4]), f"{n} setups, this week"),
        _gate("Product", "No call is made against a player on injured reserve or suspended",
              not bad_alt, "; ".join(bad_alt[:4])),
        _gate("Product", "Every % in every setup is between 50 and 99, none on a defense",
              not absurd and not defense, "; ".join((absurd + defense)[:4])),
        _gate("Product", "Every setup's email stays under Gmail's clip", not wide, ", ".join(wide)),
    ]


def check_proving() -> list[Gate]:
    """Two weeks of a real past season through every runner with fake mail."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, "-m", "run.proving", str(Path(tmp) / "p"), "4-5"],
                           cwd=REPO, capture_output=True, text=True, timeout=900)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    return [_gate("Product", "Tuesday → Saturday → Monday run end to end (2025 weeks 4–5)",
                  r.returncode == 0, f"exit {r.returncode}: {tail or r.stderr[-300:]}", tail)]


# --------------------------------------------------------------------- #
# gates: the browser
# --------------------------------------------------------------------- #

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def check_browser() -> list[Gate]:
    chrome = os.environ.get("CHROME_PATH") or (CHROME if Path(CHROME).exists()
                                               else shutil.which("google-chrome")
                                               or shutil.which("chromium"))
    node = shutil.which("node")
    if not chrome or not node:
        return [Gate("Browser", "Pages load cleanly in a real browser", "SKIP",
                     "needs Chrome and node")]
    import http.server
    import functools
    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([{"path": p, "widths": list(w)} for p, w in BROWSER_PAGES], fh)
        r = subprocess.run([node, str(REPO / "run" / "launch_browser.mjs"),
                            f"http://127.0.0.1:{port}", chrome, fh.name],
                           capture_output=True, text=True, timeout=900)
        results = json.loads(r.stdout or "[]")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return [Gate("Browser", "Pages load cleanly in a real browser", "SKIP", str(exc))]
    finally:
        server.shutdown()
    fatal = [x["fatal"] for x in results if "fatal" in x]
    if fatal:
        return [Gate("Browser", "Pages load cleanly in a real browser", "SKIP", fatal[0])]
    label = lambda x: f"{x['path']} @{x['width']}"  # noqa: E731
    errors = [f"{label(x)}: {x['errors'][0][:120]}" for x in results if x["errors"]]
    # The 404 page is fetched as a 404 on purpose.
    failed = [f"{label(x)}: {x['failed'][0]}" for x in results
              if x["failed"] and x["path"] != "404.html"]
    overflow = [f"{label(x)} ({x['scrollWidth']}px)" for x in results if x.get("overflow")]
    small = [f"{label(x)}: {x['smallText'][0]}" for x in results if x.get("smallTextCount")]
    taps = [f"{label(x)}: {x['smallTaps'][0]}" for x in results if x.get("smallTapCount")]
    slow = [f"{label(x)} {x['loadMs']} ms" for x in results if x.get("loadMs", 0) > 8000]
    n = len(results)
    return [
        _gate("Browser", "No script errors on any page or mode", not errors,
              "; ".join(errors[:4]), f"{n} page loads"),
        _gate("Browser", "No failed requests", not failed, "; ".join(failed[:4])),
        _gate("Browser", "Nothing scrolls sideways on a phone", not overflow, "; ".join(overflow[:4])),
        _gate("Browser", "No text under 11px a reader has to read", not small,
              "; ".join(small[:4]), fail="WARN"),
        _gate("Browser", "Buttons and controls are at least 24px to tap", not taps,
              "; ".join(taps[:4]), fail="WARN"),
        _gate("Browser", "Pages load in under 8 seconds locally", not slow, "; ".join(slow[:4]),
              fail="WARN"),
    ]


# --------------------------------------------------------------------- #
# gates: outside the repo
# --------------------------------------------------------------------- #

def _dig(kind: str, name: str) -> list[str]:
    if not shutil.which("dig"):
        raise RuntimeError("dig is not installed")
    r = subprocess.run(["dig", "+short", kind, name], capture_output=True, text=True, timeout=20)
    return [line.strip().strip('"') for line in r.stdout.splitlines() if line.strip()]


def check_dns() -> list[Gate]:
    try:
        mx = _dig("MX", DOMAIN)
        txt = _dig("TXT", DOMAIN)
        dmarc = _dig("TXT", f"_dmarc.{DOMAIN}")
        dkim = _dig("TXT", f"resend._domainkey.{DOMAIN}")
        send_mx = _dig("MX", f"send.{DOMAIN}")
        send_spf = _dig("TXT", f"send.{DOMAIN}")
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        return [Gate("Email", "Sending domain is authenticated", "SKIP", str(exc))]
    return [
        _gate("Email", "Mail to hello@ is routed (MX)", bool(mx), "no MX record", ", ".join(mx[:2])),
        _gate("Email", "DMARC policy published", any("v=DMARC1" in t for t in dmarc),
              f"no _dmarc.{DOMAIN} record — inbox providers distrust an unauthenticated sender",
              dmarc[0][:60] if dmarc else "", fail="OWNER"),
        _gate("Email", "Resend DKIM key published", bool(dkim),
              f"no resend._domainkey.{DOMAIN} — LAUNCH.md step 2 (verify the domain in Resend)",
              "present", fail="OWNER"),
        _gate("Email", "Resend return path (send.) has MX and SPF",
              bool(send_mx) and any("v=spf1" in t for t in send_spf),
              f"send.{DOMAIN} MX/SPF missing — LAUNCH.md step 2", "present", fail="OWNER"),
        _gate("Email", "Root SPF does not block the sender", not any(
            "v=spf1" in t and "-all" in t and "amazonses" not in t and "resend" not in t
            for t in txt), "a strict root SPF without the sender would fail its mail",
            "ok", fail="WARN"),
    ]


def check_live() -> list[Gate]:
    import requests
    gates = []
    bad = []
    for path in ("", "join/", "how-it-works.html", "league-pass.html", "sample-report.html",
                 "this-week.html", "terms.html", "privacy.html", "sitemap.xml", "og.png"):
        try:
            r = requests.get(f"{LIVE}/{path}", timeout=20)
            if r.status_code != 200:
                bad.append(f"/{path} {r.status_code}")
        except requests.RequestException as exc:
            bad.append(f"/{path} {type(exc).__name__}")
    gates.append(_gate("Live", "Every key page on the live site answers 200", not bad,
                       "; ".join(bad[:5]), LIVE))
    try:
        ahead = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=REPO,
                               capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "site"], cwd=REPO,
                               capture_output=True, text=True).stdout.strip()
    except OSError:
        ahead, dirty = "", ""
    gates.append(Gate("Live", "The live site is what is in the repo",
                      "WARN" if (ahead not in ("", "0") or dirty) else "PASS",
                      (f"{ahead} commit(s) not pushed" if ahead not in ("", "0") else "")
                      + ("; uncommitted site changes" if dirty else "") or "pushed"))
    return gates


def check_secrets() -> list[Gate]:
    if not shutil.which("gh"):
        names = None
    else:
        r = subprocess.run(["gh", "secret", "list", "--json", "name"], cwd=REPO,
                           capture_output=True, text=True)
        names = ({s["name"] for s in json.loads(r.stdout)} if r.returncode == 0 and r.stdout
                 else None)
    if names is None:
        return [Gate("Owner", "GitHub Actions secrets are set", "OWNER",
                     "can't read them from this machine (gh not signed in) — confirm these "
                     "names exist in Settings → Secrets → Actions: " + ", ".join(REQUIRED_SECRETS))]
    missing = [n for n in REQUIRED_SECRETS if n not in names]
    return [_gate("Owner", "GitHub Actions secrets are set", not missing,
                  "missing: " + ", ".join(missing), f"all {len(REQUIRED_SECRETS)} present",
                  fail="OWNER")]


def check_compliance() -> list[Gate]:
    from render.welcome import welcome_message
    gates = []
    join = visible_text((SITE / "join/index.html").read_text(encoding="utf-8"))
    gates.append(_gate("Compliance", "Renewal amount, refund and cancel terms sit above the pay button",
                       bool(re.search(r"renews once a year at \$39", join))
                       and "cancel yourself" in join and "Refunds are no-questions" in join,
                       "the join page's terms line lost a disclosure"))
    msg = welcome_message("x@example.com", "season", "abcdef0123", "2026")
    body = visible_text(msg.html)
    gates.append(_gate("Compliance", "The welcome email states renewal, amount and how to cancel",
                       "renews once a year" in body and "$39" in body and "Cancel" in body,
                       "the acknowledgment email lost a disclosure"))
    from render.sender import postal_address
    address = postal_address()
    gates.append(Gate("Compliance", "Commercial email carries a postal address (CAN-SPAM, CASL)",
                      "PASS" if address else "OWNER",
                      address or "SENDER_POSTAL_ADDRESS is not set here — the launch "
                                 "announcement refuses to send without it. Rent a mailbox "
                                 "(never a home address) and set it as a GitHub secret and "
                                 "in your shell"))
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from infra.stripe_paylink_text import MESSAGES, TOS_MESSAGES
    from render.welcome import TERMS_VERSION
    from datetime import date
    stamp = date.fromisoformat(TERMS_VERSION)
    terms = (SITE / "terms.html").read_text(encoding="utf-8")
    gates.append(_gate("Compliance", "Stripe's Pay-button text matches the terms (once a year)",
                       not any("each season" in m for m in MESSAGES.values())
                       and all("once a year" in MESSAGES[p] for p in ("season", "league_pass")),
                       "infra/stripe_paylink_text.py says something the terms don't"))
    gates.append(_gate("Compliance", "The checkout's terms box names the renewal, its amount and 18+",
                       all("18 or older" in t and "[Terms](" in t for t in TOS_MESSAGES.values()),
                       "a TOS_MESSAGES entry lost a required element"))
    gates.append(_gate("Compliance", "The terms carry the version consent is recorded against",
                       f"Last updated {stamp.day} {stamp:%B %Y}" in terms,
                       f"terms.html's Last updated date ≠ TERMS_VERSION {TERMS_VERSION}"))
    privacy = visible_text((SITE / "privacy.html").read_text(encoding="utf-8"))
    missing = [p for p in ("Stripe", "Resend", "Cloudflare", "GitHub", "United States")
               if p not in privacy]
    gates.append(_gate("Compliance", "The privacy policy names every processor and where data lives",
                       not missing, f"missing: {', '.join(missing)}"))
    worker = (REPO / "infra" / "form-worker.js").read_text(encoding="utf-8")
    gates.append(_gate("Compliance", "Form rows expire as the privacy policy says",
                       "expirationTtl" in worker,
                       "infra/form-worker.js stores rows forever; privacy.html promises ~13 months"))
    return gates


def check_tests() -> list[Gate]:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"],
                       cwd=REPO, capture_output=True, text=True, timeout=1800)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    return [_gate("Code", "The full test suite passes", r.returncode == 0,
                  tail or r.stderr[-300:], tail)]


def check_economics() -> list[Gate]:
    try:
        from run.economics import summary_lines
    except ImportError:
        return []
    return [Gate("Economics", line[0], line[1], line[2]) for line in summary_lines()]


# --------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------- #

MARK = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "OWNER": "○", "SKIP": "–"}


def run_all(fast: bool, offline: bool, progress: Callable[[str], None]) -> list[Gate]:
    steps: list[tuple[str, Callable[[], Iterable[Gate]]]] = [
        ("site links", check_links), ("page basics", check_page_basics),
        ("scripts", check_scripts), ("selling copy", check_selling_copy),
        ("prices", check_prices), ("funnel configuration", check_funnel_config),
        ("season clock", check_week_json), ("this week's report", check_product),
        ("five league setups", check_product_battery),
        ("compliance text", check_compliance), ("owner secrets", check_secrets),
        ("economics", check_economics),
    ]
    if not offline:
        steps += [("email DNS", check_dns), ("live site", check_live)]
    if not fast:
        steps += [("browser", check_browser), ("proving run", check_proving),
                  ("test suite", check_tests)]
    gates: list[Gate] = []
    for label, fn in steps:
        progress(label)
        try:
            gates.extend(fn())
        except Exception as exc:  # noqa: BLE001 — one broken check never hides the rest
            gates.append(Gate("Check", f"{label} could not run", "FAIL",
                              f"{type(exc).__name__}: {exc}"))
    return gates


def render(gates: list[Gate]) -> str:
    lines = ["BEAT YOUR LEAGUE — LAUNCH CHECK", ""]
    for area in dict.fromkeys(g.area for g in gates):
        lines.append(area.upper())
        for g in (g for g in gates if g.area == area):
            lines.append(f"  {MARK[g.status]} {g.status:<5} {g.name}")
            if g.detail:
                lines.append(f"          {g.detail}")
        lines.append("")
    counts = {s: sum(g.status == s for g in gates) for s in MARK}
    verdict = ("READY" if not counts["FAIL"] and not counts["OWNER"]
               else "NOT READY — fix the failures" if counts["FAIL"]
               else "NOT READY — waiting on owner setup")
    lines.append(f"{counts['PASS']} pass · {counts['FAIL']} fail · {counts['WARN']} warn · "
                 f"{counts['OWNER']} owner · {counts['SKIP']} skipped")
    lines.append(f"VERDICT: {verdict}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fast", action="store_true",
                        help="skip the test suite, the browser and the proving run")
    parser.add_argument("--offline", action="store_true", help="skip DNS and the live site")
    parser.add_argument("--json", action="store_true", help="print the gates as JSON")
    args = parser.parse_args(argv)
    started = time.time()
    gates = run_all(args.fast, args.offline,
                    lambda label: print(f"  checking {label}…", file=sys.stderr))
    if args.json:
        print(json.dumps([g.__dict__ for g in gates], indent=1))
    else:
        print(render(gates), end="")
        print(f"({time.time() - started:.0f}s)", file=sys.stderr)
    return 1 if any(g.status == "FAIL" for g in gates) else 0


if __name__ == "__main__":
    sys.exit(main())
