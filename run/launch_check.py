"""Launch readiness — `make launch-check`.

Usage:
    python -m run.launch_check            # everything (≈8 minutes)
    python -m run.launch_check --fast     # skip the test suite, browser and proving run
    python -m run.launch_check --offline  # skip DNS, the live site and the account APIs

The account gates read GitHub (`gh`, signed in), Stripe (STRIPE_API_KEY),
Resend (RESEND_API_KEY) and the page counter (CF_ACCOUNT_ID and the read-only
CF_ANALYTICS_TOKEN, in the shell or .env) only when those are present, and
only ever read (one SQL query for the counter); without them each says SKIP
or OWNER rather than guessing. The
accessibility gate needs axe-core: set AXE_CORE_PATH to an axe.min.js, or
`npm install --no-save axe-core@4.11.4` in the repo (LAUNCH.md, "Where things stand").

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
import contextlib
import functools
import html
import http.server
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

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
# SENDER_POSTAL_ADDRESS is here as a SECRET, not just a shell variable: the
# crons are what send, render/sender.py reads only the environment, and every
# mail-sending step maps it (tests/test_workflows.py) — so a value set only in
# the owner's shell reaches no email at all.
# EMAIL_REPLY_TO is optional since D7: an unset one means hello@ (run/delivery).
# LOG_SECRET keys every address-derived code in the public send log and stop
# list (run/digest.py); without it every real send refuses.
# CACHE_KEY seals the registry and the sent lineups between runs
# (run/statebox.py): once STRIPE_API_KEY is set, a run without it goes red and
# saves nothing — so "all present" without it was the OPS-4 failure again.
REQUIRED_SECRETS = ("STRIPE_API_KEY", "STRIPE_PAYMENT_LINKS", "EMAIL_PROVIDER", "EMAIL_FROM",
                    "LOG_SECRET", "RESEND_API_KEY", "SITE_URL", "BILLING_PORTAL_URL",
                    "FORM_ENDPOINT", "FORM_API_KEY", "UPDATE_SECRET",
                    "SENDER_POSTAL_ADDRESS", "CACHE_KEY")
# What each feature stops doing without which secret, so a missing name says
# what a buyer loses rather than only that a box is empty. UPDATE_SECRET keys
# two things since Oct 2026: the roster-update confirmation codes AND each
# League Pass payer's own seat link (run/updates seat token, contract C4), and
# that link is built on SITE_URL — without either, a payer's welcome has no
# seat link to give and no seat can be claimed (contract C3: the generic seat
# page that took the payer's typed address is closed).
FEATURE_SECRETS = {
    "Taking money and knowing who paid": ("STRIPE_API_KEY", "STRIPE_PAYMENT_LINKS"),
    "Sending any email": ("EMAIL_PROVIDER", "EMAIL_FROM", "LOG_SECRET", "RESEND_API_KEY",
                          "SENDER_POSTAL_ADDRESS"),
    "A cancel link that opens the billing page": ("BILLING_PORTAL_URL", "SITE_URL"),
    "Self-serve roster updates": ("FORM_ENDPOINT", "FORM_API_KEY", "UPDATE_SECRET", "SITE_URL"),
    "A League Pass payer's own seat link": ("FORM_ENDPOINT", "FORM_API_KEY", "UPDATE_SECRET",
                                            "SITE_URL"),
    "Free reports and the waitlist": ("FORM_ENDPOINT", "FORM_API_KEY"),
    "Keeping subscribers, seats and roster changes between runs": ("CACHE_KEY",),
}


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


COUNTER_URL = f"https://forms.{DOMAIN}/e"


def counter_endpoint() -> str:
    """site/count.js's ENDPOINT; empty while the page counter is off."""
    from run.stats import counter_endpoint as read
    return read(SITE / "count.js")


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
    for name in SELLING + LEGAL:
        path = SITE / name
        if not path.exists():
            continue
        # visible_text collapses every run of whitespace to one space, so a
        # claim hand-wrapped across two lines of HTML ("takes one\n click")
        # is still one phrase here.
        text = visible_text(path.read_text(encoding="utf-8"))
        for phrase in RETIRED_CLAIMS:
            if phrase.lower() in text.lower():
                retired.append(f"{name}: '{phrase}'")
        for pattern in RETIRED_PATTERNS:
            for m in re.finditer(pattern, text, re.I):
                retired.append(f"{name}: '{m.group(0)}'")
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
# The operative contract and the privacy policy are scanned too. The terms
# kept "cancelling takes one click from your billing page" in §3 after §4 and
# every other surface had moved to the real flow (an emailed link, about a
# minute) — the retired claim survived in the one document that wins every
# disagreement, because the gate only read the selling pages (launch audit
# C2, Oct 15 2026).
LEGAL = ("terms.html", "privacy.html")
# Retired claims with more than one wording. Cancelling through Stripe's
# billing page is never one click — enter an email, open the link it sends,
# press Cancel — so ANY "one click" said of cancelling is the retired claim,
# in either order and however it is phrased between.
RETIRED_PATTERNS = (r"\bcancel\w*\b[^.;:]{0,60}\bone[\s-]+click\b",
                    r"\bone[\s-]+click\b[^.;:]{0,60}\bcancel\w*\b")


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
    # 2026: one-time passes (owner decision, Oct 18 2026) — the pass card is
    # "/ rest of season", the League Pass card "/ your whole league", and
    # monthly is off the landing (its price still lives on the join page).
    season = re.search(r'id="pass-price">\$(\d+) <small>/ rest of season', landing)
    lp_amt = re.search(r'class="amt">\$(\d+)', lp)
    seen = {"landing pass": season and "$" + season.group(1),
            "league pass page": lp_amt and "$" + lp_amt.group(1)}
    want = {"landing pass": SEASON_PRICE, "league pass page": PASS_PRICE}
    wrong = [f"{k} shows {seen[k]} but the welcome email says {want[k]}"
             for k in want if seen[k] != want[k]]
    for label, price in ((f"Rest-of-Season Pass · {SEASON_PRICE}", SEASON_PRICE),
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
    # 2026 (owner decision, Oct 18 2026): monthly isn't sold, so its empty
    # link is not a missing one (MONTHLY_OFFERED on the join page).
    monthly_offered = join.get("MONTHLY_OFFERED") != "false"
    links = {k: join.get(k, "") for k in ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY",
                                          "STRIPE_LINK_PASS")
             if monthly_offered or k != "STRIPE_LINK_MONTHLY"}
    empty = [k for k, v in links.items() if not v]
    open_ = landing.get("CHECKOUT_OPEN") == "true"
    can = landing.get("CHECKOUT_CAN_COMPLETE") == "true"
    trial = landing.get("TRIAL_OPEN") == "true"
    form = join.get("FORM_ENDPOINT", "")
    gates = []
    if empty:
        gates.append(Gate("Funnel", "Checkout can take money", "OWNER",
                          f"{len(empty)} of {len(links)} payment links empty — LAUNCH.md step 5 (the "
                          f"Worker) and steps 1–3, then fresh links go into "
                          f"site/join/index.html"))
    else:
        gates.append(Gate("Funnel", "Checkout can take money", "PASS", "every payment link on sale is set"))
    gates.append(_gate("Funnel", "The landing never sells a checkout that cannot complete",
                       not (open_ and links["STRIPE_LINK_SEASON"] == "")
                       and not (can and empty),
                       "CHECKOUT_OPEN/CHECKOUT_CAN_COMPLETE is on while a payment link is empty"))
    # OPS-04: a buyer's roster churns from the first waiver run, and without the
    # form Worker the only way to change it is a reply somebody applies by hand
    # (`make roster-update`) — a promise of "update any time" that rests on the
    # owner's inbox. Checkout reopens only once step 5's Worker is live.
    gates.append(_gate("Funnel", "Checkout never opens before roster changes have a route",
                       not (open_ and not form),
                       "CHECKOUT_OPEN is on while the join page's FORM_ENDPOINT is empty — "
                       "every roster change would be a reply applied by hand; deploy the "
                       "form Worker (LAUNCH.md step 5) before opening"))
    gates.append(_gate("Funnel", "Landing and League Pass agree on whether checkout is open",
                       landing.get("CHECKOUT_OPEN") == lp.get("CHECKOUT_OPEN"),
                       f"index CHECKOUT_OPEN={landing.get('CHECKOUT_OPEN')}, "
                       f"league-pass CHECKOUT_OPEN={lp.get('CHECKOUT_OPEN')}"))
    # The $19 Playoff Pass swaps in on the landing only when the join page can
    # charge it: the landing's flag must equal "the playoff link is set".
    gates.append(_gate("Funnel", "The landing sells the Playoff Pass only when the join page can charge it",
                       (landing.get("PLAYOFF_PASS_READY") == "true") == bool(join.get("STRIPE_LINK_PLAYOFF")),
                       f"landing PLAYOFF_PASS_READY={landing.get('PLAYOFF_PASS_READY')} but the join "
                       f"page's STRIPE_LINK_PLAYOFF is {'set' if join.get('STRIPE_LINK_PLAYOFF') else 'empty'}"))
    gates.append(_gate("Funnel", "Landing and join page agree on whether free reports are open",
                       landing.get("TRIAL_OPEN") == join.get("TRIAL_OPEN"),
                       f"index TRIAL_OPEN={landing.get('TRIAL_OPEN')}, join "
                       f"TRIAL_OPEN={join.get('TRIAL_OPEN')} — the button and the page it "
                       f"opens would disagree"))
    gates.append(_gate("Funnel", "The free-report button only shows when requests can be received",
                       not (trial and not form),
                       "TRIAL_OPEN is on but FORM_ENDPOINT is empty: the button posts nowhere"))
    # EMAILS-69: every free report ends "Get next Tuesday's report" → join/,
    # which must then be able to sell it.
    gates.append(_gate("Funnel", "The free report's sign-up button lands on an open checkout",
                       not (trial and not open_),
                       "TRIAL_OPEN is on while CHECKOUT_OPEN is off: each free report's "
                       "'Get next Tuesday's report' button would land on a closed page"))
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
    gates.append(_gate("Funnel", "The confirm page posts where the join page does",
                       not form or confirm.get("FORM_ENDPOINT", "") == form,
                       "join/index.html has FORM_ENDPOINT set and join/confirm.html "
                       f"has {confirm.get('FORM_ENDPOINT', '') or 'none'} — every "
                       "emailed confirm button would post nowhere and no roster "
                       "change or seat could ever be confirmed"))
    # The page counter (site/count.js, ANALYTICS-01..06) posts to the same
    # Worker's /e. Blockers drop a beacon to another site (EasyPrivacy's
    # `*$ping,third-party` matches *.workers.dev, not forms.<our domain>), and
    # the privacy page names forms.<our domain> as the counter's address.
    counter = counter_endpoint()
    hosted = {**endpoints, **({"count.js ENDPOINT": counter} if counter else {})}
    gates.append(_gate("Funnel", "The form Worker sits on our own domain",
                       not any("workers.dev" in v for v in hosted.values()),
                       "a *.workers.dev address is easily blocked and looks unofficial — "
                       f"use forms.{DOMAIN}", fail="WARN"))
    gates.append(_gate("Funnel", "The page counter posts to the form Worker on our own domain",
                       not counter or counter == COUNTER_URL,
                       f"site/count.js ENDPOINT is {counter!r}: it must be {COUNTER_URL} — the "
                       "address privacy.html section 3 names, on the Worker's /e route",
                       counter or "off"))
    if form and not counter:
        gates.append(Gate("Funnel", "The page counter is on once the form Worker is", "OWNER",
                          "FORM_ENDPOINT is set but site/count.js has no ENDPOINT, so nothing "
                          "counts visits or signup steps — LAUNCH.md step 5b, then set it to "
                          f"{COUNTER_URL}"))
    else:
        gates.append(Gate("Funnel", "The page counter is on once the form Worker is", "PASS",
                          "on" if counter else "off until the form Worker is (LAUNCH.md step 5)"))
    seats_open = lp.get("SEATS_OPEN") == "true"
    gates.append(_gate("Funnel", "The League Pass is never sold before seats can be claimed",
                       # The page builds its Buy button only when CHECKOUT_OPEN and
                       # SEATS_OPEN are both true, so SEATS_OPEN is the one to guard.
                       not (seats_open and not form),
                       "league-pass.html has SEATS_OPEN on while FORM_ENDPOINT is empty "
                       "(seats would refuse)"))
    gates.append(_gate("Funnel", "The League Pass opens the day seats can be claimed",
                       not (open_ and form and links["STRIPE_LINK_PASS"] and not seats_open),
                       "checkout is open, the Worker is set and the pass link exists, "
                       "but league-pass.html still says SEATS_OPEN=false — the page "
                       "tells commissioners the pass \"opens the day your league can "
                       "claim its seats\", which is today: set SEATS_OPEN = true"))
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
                    if stale else "")),
            recorded_odds_gate(w)]


def _instant(stamp: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def recorded_odds_gate(week: dict) -> Gate:
    """G24 / R1 / BE2-D3: site/this-week.html is public proof, and a % on it
    that the ledger does not hold is a published probability with nothing
    grading it — principle 2's failure on the one page the landing links as
    the product. render/live_sample.write_week_json says whether this week's
    odds went on the record (``recorded``) and whether the page was rebuilt
    after the week's first kickoff (``after_kickoff``, which it must then say
    on the page). Reproduced on Oct 17 2026: week.json carried 2 odds, no
    ``recorded`` and a build time a day after Thursday's kickoff, with nothing
    on the record — and no gate looked."""
    name = "This week's sample prints only recorded odds"
    odds = int(week.get("odds") or 0)
    problems = []
    if odds > 0 and not week.get("recorded"):
        problems.append(f"site/this-week.html prints {odds} % the ledger does not hold — "
                        f"rebuild with `make live-sample ARGS=--force`")
    built, first = _instant(week.get("built_at")), _instant(week.get("first_kickoff"))
    if built and first and built > first and not week.get("after_kickoff"):
        problems.append("built after the week's first kickoff but does not say so")
    if problems:
        return Gate("Site", name, "FAIL", "; ".join(problems))
    return Gate("Site", name, "PASS",
                f"{odds} % on the page, all on the record" if odds else "no % on the page")


def ledger_rows(processed_dir: Path, season: str) -> tuple[int, int, list[str]]:
    """(calls on the record for ``season``, typed-* stores holding them, stores
    that could not be read) — the roster product's stores only, deduplicated
    as the grader reads them (engine.ledger.load_ledger)."""
    from engine.ledger import LedgerError, load_ledger
    calls = stores = 0
    broken = []
    for path in sorted((Path(processed_dir) / "ledger").glob(f"typed-*-{season}/calls.jsonl")):
        try:
            held = len(load_ledger(path))
        except (LedgerError, OSError) as exc:
            broken.append(f"{path.parent.name} ({exc})")
            continue
        calls += held
        stores += 1 if held else 0
    return calls, stores, broken


def check_record(processed_dir: Path | None = None, today: date | None = None) -> list[Gate]:
    """G25: the public record holds this season's calls — counted, never
    assumed. Every published % is recorded when it is delivered (run/tuesday)
    and the live sample records its own before kickoff, so once the first
    Tuesday that could carry odds has passed — Week 2's, when the sample's
    measured setup gets them — an empty record means the recording is not
    happening, whatever the code says. Reproduced Oct 17 2026, Week 6: no
    typed-* store existed at all, and nothing in the launch check said so."""
    from render.live_sample import PROCESSED_DIR, next_report_day
    from run.solo import CACHE_DIR, current_season
    today = today or date.today()
    name = "The public record holds this season's calls"
    try:
        season = current_season(CACHE_DIR, today)
        first = next_report_day(CACHE_DIR, season, 1)
    except Exception as exc:  # noqa: BLE001 — the schedule can't say
        return [Gate("Record", name, "SKIP", f"the schedule can't say: {exc}")]
    calls, stores, broken = ledger_rows(processed_dir or PROCESSED_DIR, season)
    held = f"{calls} call(s) on the record for {season} in {stores} typed-* store(s)"
    if broken:
        return [Gate("Record", name, "FAIL", f"{held}; unreadable: {', '.join(broken)}")]
    due = first is not None and today >= date.fromisoformat(first)
    if calls == 0 and due:
        return [Gate("Record", name, "WARN",
                     f"{held}, though odds could be recorded from {first} (Week 2's report "
                     f"Tuesday): the live sample and every delivered report record theirs, "
                     f"so nothing is being recorded")]
    return [Gate("Record", name, "PASS",
                 held + ("" if due or first is None else
                         f" — nothing can be recorded before {first}"))]


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


def players_today(cache_dir: Path) -> dict[str, dict[str, str]]:
    """gsis -> {status, team, position} from TODAY's players release, read here
    rather than through the report's own data. The first version of the
    battery trusted the report's availability records and passed a report that
    started an injured-reserve receiver; the second read the gate's
    carried-forward team, so a player traded onto a team on bye (or released
    before he played a 2026 snap) was invisible to it too (launch audit GATE-1).
    """
    import csv
    out: dict[str, dict[str, str]] = {}
    with (cache_dir / "players.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            gsis = (row.get("gsis_id") or "").strip()
            if gsis:
                out[gsis] = {"status": (row.get("status") or "").strip().upper(),
                             "team": (row.get("latest_team") or "").strip(),
                             "position": (row.get("position") or "").strip()}
    return out


def schedule_byes(cache_dir: Path, season: str, week: int) -> set[str] | None:
    """Teams with no regular-season game in ``week``, read off games.csv
    directly — the schedule, not the report's idea of it. None when the week
    has no games on file (unknown is never "nobody is on bye")."""
    import csv
    teams: set[str] = set()
    playing: set[str] = set()
    with (cache_dir / "games.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("season") != str(season) or row.get("game_type") != "REG":
                continue
            pair = {row.get("home_team") or "", row.get("away_team") or ""} - {""}
            teams |= pair
            if row.get("week") == str(week):
                playing |= pair
    return (teams - playing) if playing else None


def cannot_play(pid: str, today: dict[str, dict[str, str]], byes: set[str]) -> str | None:
    """Why this player cannot play this week, on today's facts alone: a reserve
    list or a release (players.csv status), or his CURRENT team's bye. None
    when nothing today says so. A defense's team is its id."""
    from engine.availability import ROSTER_OUT
    if pid.startswith("DEF-"):
        team = pid.split("-", 1)[1]
        return f"{team} on bye" if team in byes else None
    row = today.get(pid) or {}
    if row.get("status") in ROSTER_OUT:
        return ROSTER_OUT[row["status"]]
    if row.get("team") in byes:
        return f"{row['team']} on bye"
    return None


def _season_points(rows_by_week: dict, before: int | None = None) -> dict[str, float]:
    """player -> PPR points over a season's rows, scored by the product's own
    rule: the only ranking the battery needs is who a real manager would
    actually roster."""
    from engine.scoring import preset, score
    rule = preset("ppr")
    total: dict[str, float] = {}
    for week, rows in rows_by_week.items():
        if before is not None and int(week) >= before:
            continue
        for pid, row in rows.items():
            try:
                total[pid] = total.get(pid, 0.0) + score(row, rule)
            except Exception:  # noqa: BLE001 — a row it cannot score ranks nobody
                continue
    return total


BATTERY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


def battery_rosters(data, today: dict[str, dict[str, str]],
                    byes: set[str]) -> list[tuple[str, tuple[str, ...], str]]:
    """(name, player ids, what it tests) for THIS week, built from the data so
    each keeps testing its hard case whatever the week is:

    - **Sample roster** — the live sample's own (render.live_sample).
    - **Byes and injuries** — the best players this season who cannot play
      this week (current team on bye, injured reserve, released), beside
      enough healthy ones to field a full lineup — so starting any of the
      first is a defect, not a necessity.
    - **Moved onto a bye** — the sample with its best player at one position
      swapped for a player whose CURRENT team is on bye while his last stat
      row's team is not (traded or signed since): the case the gate's
      carried-forward team misses.
    - **Released** — the sample with its best player at one position swapped
      for a released player the gate never placed on a team (no stat row this
      season): the teamless case.
    A case this week cannot supply (no byes in week 1) is left out and said so.
    """
    from render.live_sample import LIVE_ROSTER
    known = {p.player_id: p for p in data.directory.players}
    points = _season_points(data.weekly, before=data.week)
    prior = _season_points(data.prior)
    statuses = data.availability.statuses or {}

    def position(pid: str) -> str:
        player = known.get(pid)
        return "DEF" if pid.startswith("DEF-") else (player.position if player else "")

    def ranked(pos: str, pool=None) -> list[str]:
        ids = [pid for pid in (pool if pool is not None else known)
               if position(pid) == pos and points.get(pid, 0) > 0]
        return sorted(ids, key=lambda pid: (-points.get(pid, 0), pid))

    sample = tuple(pid for pid in LIVE_ROSTER if pid in known)
    out = [("Sample roster", sample, "the live sample")]

    heavy: list[str] = []
    for pos, n_out, n_ok in (("QB", 1, 1), ("RB", 2, 2), ("WR", 2, 3), ("TE", 1, 1),
                             ("K", 1, 1), ("DEF", 1, 1)):
        pool = ranked(pos)
        heavy += [pid for pid in pool if cannot_play(pid, today, byes)][:n_out]
        heavy += [pid for pid in pool if not cannot_play(pid, today, byes)][:n_ok]
    if any(cannot_play(pid, today, byes) for pid in heavy):
        out.append(("Byes and injuries", tuple(heavy), "starters who can't play"))

    def swapped(incoming: str) -> tuple[str, ...]:
        pos = position(incoming)
        best = next(iter(ranked(pos, sample)), None)
        return tuple(incoming if pid == best else pid for pid in sample) \
            if best else sample + (incoming,)

    moved = [pid for pid in known if not pid.startswith("DEF-") and pid not in sample
             and position(pid) in BATTERY_POSITIONS
             and (today.get(pid) or {}).get("team") in byes
             and (today.get(pid) or {}).get("status") not in ("CUT", "RLS")
             and (statuses.get(pid) or {}).get("team") not in (None, *byes)]
    moved.sort(key=lambda pid: (-points.get(pid, 0), pid))
    if moved:
        out.append(("Moved onto a bye", swapped(moved[0]),
                    "a player whose current team is on bye"))
    released = [pid for pid in known if pid not in sample and pid not in statuses
                and position(pid) in ("QB", "RB", "WR", "TE")
                and (today.get(pid) or {}).get("status") in ("CUT", "RLS")]
    released.sort(key=lambda pid: (-prior.get(pid, 0), pid))
    if released:
        out.append(("Released", swapped(released[0]), "a released player with no team"))
    return out


def _battery_setups(name: str) -> tuple[tuple[str, int, str], ...]:
    # The sample under every setup; each hard case under two (its lineup
    # shape is what changes which bench player can cover).
    return BATTERY if name == "Sample roster" else (BATTERY[0], BATTERY[3])


@functools.lru_cache(maxsize=1)
def battery_reports() -> tuple[tuple[str, dict], ...] | str:
    """(label, report) for every battery roster under its setups, built once
    per run: the battery's gates and the email-width gate read the same
    reports. A string is the reason there are none (the offseason)."""
    from engine.subscriber import RosterSpec
    from run.solo import CACHE_DIR, SeasonOver, load_week_data, report_for
    try:
        data = load_week_data(CACHE_DIR)
    except SeasonOver as exc:
        return str(exc)
    today = players_today(CACHE_DIR)
    byes = schedule_byes(CACHE_DIR, data.season, data.week) or set()
    built = []
    for name, roster, _why in battery_rosters(data, today, byes):
        for scoring, size, template in _battery_setups(name):
            report = report_for(RosterSpec(player_ids=roster, slots=TEMPLATE_SLOTS[template],
                                           scoring=scoring, label=name),
                                data, league_size=size)
            built.append((f"{name} {scoring}/{size}/{template}", report))
    return tuple(built)


def audit_report(label: str, report: dict, today: dict[str, dict[str, str]],
                 byes: set[str]) -> dict[str, list[str]]:
    """Every way one report can mishandle a player who cannot play, checked
    against today's facts (``cannot_play``) rather than the report's own:
    - silent: started with no out flag, or not named in the checklist;
    - over_playable: started while a bench player who CAN play, and whom the
      report itself does not mark out, could fill that slot;
    - bad_alt: a printed % whose other side — the bench player the call is
      made against — cannot play (a lineup row's call or the closest call)."""
    from engine.history import FLEX_ELIGIBILITY
    found: dict[str, list[str]] = {"silent": [], "over_playable": [], "bad_alt": [],
                                   "absurd": [], "defense": []}
    told = " ".join(c["action"] for c in report["checklist"])
    bench = report.get("bench") or []

    def fits(pos: str, slot: str) -> bool:
        allowed = FLEX_ELIGIBILITY.get(slot)
        return pos in allowed if allowed else pos == slot

    for slot in report["lineup"]:
        pid = slot.get("player_id") or ""
        why = cannot_play(pid, today, byes) if pid else None
        if why:
            flagged = any(f.get("kind") == "out" for f in slot.get("flags") or [])
            if not (flagged and slot["player_name"].split()[-1] in told):
                found["silent"].append(f"{label}: {slot['player_name']} ({why})")
            cover = [b["name"] for b in bench
                     if not b.get("out") and not cannot_play(b["player_id"], today, byes)
                     and fits(b.get("position") or "", slot["slot"])]
            if cover:
                found["over_playable"].append(
                    f"{label}: {slot['player_name']} ({why}) over {cover[0]}")
        if slot.get("confidence") is not None:
            if not 0.5 <= slot["confidence"] <= 0.99:
                found["absurd"].append(f"{label}: {slot['player_name']}")
            if slot.get("position") == "DEF":
                found["defense"].append(label)
            alt = cannot_play(slot.get("alternative_id") or "", today, byes)
            if alt:
                found["bad_alt"].append(f"{label}: {slot['player_name']} over "
                                        f"{slot.get('alternative_name')} ({alt})")
    regret = report.get("regret") or {}
    if regret.get("confidence") is not None:
        alt = cannot_play(regret.get("over_id") or "", today, byes)
        if alt:
            found["bad_alt"].append(f"{label}: closest call against "
                                    f"{regret.get('over_name')} ({alt})")
    return found


def check_product_battery() -> list[Gate]:
    """The sample roster under five setups and three hard-case rosters built
    for this week, each joined to TODAY's roster status and the SCHEDULE's
    byes outside the report's own availability data (see players_today)."""
    from render.email import render_email
    from run.solo import CACHE_DIR, load_week_data
    built = battery_reports()
    if isinstance(built, str):
        return [Gate("Product", "Every battery roster builds a sound report", "SKIP", built)]
    data = load_week_data(CACHE_DIR)
    today = players_today(CACHE_DIR)
    byes = schedule_byes(CACHE_DIR, data.season, data.week) or set()
    found: dict[str, list[str]] = {}
    wide = []
    for label, report in built:
        for key, items in audit_report(label, report, today, byes).items():
            found.setdefault(key, []).extend(items)
        if len(render_email(report).encode("utf-8")) >= 100_000:
            wide.append(label)
    rosters = list(dict.fromkeys(label.rsplit(" ", 1)[0] for label, _ in built))
    missing = [name for name in ("Byes and injuries", "Moved onto a bye", "Released")
               if name not in rosters]
    scope = (f"{len(built)} reports: {', '.join(rosters)}"
             + (f" (no {', '.join(missing).lower()} case exists this week)" if missing else ""))
    return [
        _gate("Product", "No player who can't play is started without a flag and a checklist line",
              not found["silent"], "; ".join(found["silent"][:4]), scope),
        _gate("Product", "No player who can't play is started over a bench player who can",
              not found["over_playable"], "; ".join(found["over_playable"][:4])),
        _gate("Product", "No % is printed against a player on bye, on a reserve list or released",
              not found["bad_alt"], "; ".join(found["bad_alt"][:4])),
        _gate("Product", "Every % in every setup is between 50 and 99, none on a defense",
              not found["absurd"] and not found["defense"],
              "; ".join((found["absurd"] + found["defense"])[:4])),
        _gate("Product", "Every setup's email stays under Gmail's clip", not wide, ", ".join(wide)),
    ]


# The local simulations below build real send-log keys (run/digest.py), so
# without the owner's LOG_SECRET in this shell they use a throwaway one.
# Nothing they build is ever sent, and the "LOG_SECRET is set" gate reads the
# GitHub secret names, never this environment.
SIMULATION_LOG_SECRET = "launch-check-simulation-only"


def _simulation_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("LOG_SECRET", SIMULATION_LOG_SECRET)
    return env


@contextlib.contextmanager
def _simulation_log_secret():
    had = "LOG_SECRET" in os.environ
    os.environ.setdefault("LOG_SECRET", SIMULATION_LOG_SECRET)
    try:
        yield
    finally:
        if not had:
            os.environ.pop("LOG_SECRET", None)


def check_proving() -> list[Gate]:
    """Two weeks of a real past season through every runner with fake mail."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, "-m", "run.proving", str(Path(tmp) / "p"), "4-5"],
                           cwd=REPO, capture_output=True, text=True, timeout=900,
                           env=_simulation_env())
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


def _browser_tools() -> tuple[str, str] | None:
    chrome = os.environ.get("CHROME_PATH") or (CHROME if Path(CHROME).exists()
                                               else shutil.which("google-chrome")
                                               or shutil.which("chromium"))
    node = shutil.which("node")
    return (chrome, node) if chrome and node else None


class _Handler(http.server.SimpleHTTPRequestHandler):
    """A static server with two stand-ins the join flows need: a Stripe
    payment link (/__stripe/<plan>) that answers with a blank page, and the
    form Worker (/__form) that accepts any row. The browser records what left
    the page; nothing here stores it."""

    def log_message(self, *args, **kwargs) -> None:   # noqa: D102 — quiet
        return

    def _reply(self, body: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                          # noqa: N802
        if self.path.startswith("/__stripe/"):
            return self._reply(b"<!doctype html><title>stub checkout</title>", "text/html")
        return super().do_GET()

    def do_POST(self) -> None:                         # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        return self._reply(b'{"ok":true}', "application/json")

    def do_OPTIONS(self) -> None:                      # noqa: N802
        return self._reply(b"", "text/plain")


@contextlib.contextmanager
def _serving(directory: Path, port: int | None = None) -> Iterator[str]:
    port = port or _free_port()
    handler = functools.partial(_Handler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def run_browser(jobs: list[dict], base: str, timeout: int = 1500) -> list[dict] | str:
    """Run launch_browser.mjs over ``jobs`` against ``base``. A string is why it
    could not run (no Chrome or node, Chrome would not start) — a SKIP, never
    a pass."""
    tools = _browser_tools()
    if not tools:
        return "needs Chrome and node"
    chrome, node = tools
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(jobs, fh)
    try:
        r = subprocess.run([node, str(REPO / "run" / "launch_browser.mjs"), base, chrome,
                            fh.name], capture_output=True, text=True, timeout=timeout)
        results = json.loads(r.stdout or "[]")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return f"{type(exc).__name__}: {exc}"
    finally:
        Path(fh.name).unlink(missing_ok=True)
    fatal = [x["fatal"] for x in results if "fatal" in x]
    return fatal[0] if fatal else results


def audit_privacy_probe(results: list[dict], served: str) -> tuple[list[str], list[str]]:
    """(hosts a page contacted that are not ours, cookies or storage a page
    left) across probe results. ``served`` is the local server's host:port,
    which stands in for the live domain while the copy is checked."""
    ours = {served, DOMAIN, f"forms.{DOMAIN}"}
    hosts, kept = [], []
    for x in results:
        where = f"{x['path']} @{x.get('width')}"
        hosts += [f"{where}: {h}" for h in x.get("hosts") or [] if h not in ours]
        if x.get("cookies"):
            kept.append(f"{where}: cookie {x['cookies'][0]}")
        if any(x.get("storage") or []):
            kept.append(f"{where}: storage {x['storage']}")
    return list(dict.fromkeys(hosts)), list(dict.fromkeys(kept))


def check_browser() -> list[Gate]:
    with _serving(SITE) as base:
        results = run_browser([{"path": p, "widths": list(w)} for p, w in BROWSER_PAGES], base)
    if isinstance(results, str):
        return [Gate("Browser", "Pages load cleanly in a real browser", "SKIP", results)]
    broken = [f"{x['path']}: {x['jobError']}" for x in results if "jobError" in x]
    results = [x for x in results if "jobError" not in x]
    label = lambda x: f"{x['path']} @{x['width']}"  # noqa: E731
    errors = [f"{label(x)}: {x['errors'][0][:120]}" for x in results if x["errors"]] + broken
    # The 404 page is fetched as a 404 on purpose.
    failed = [f"{label(x)}: {x['failed'][0]}" for x in results
              if x["failed"] and x["path"] != "404.html"]
    overflow = [f"{label(x)} ({x['scrollWidth']}px)" for x in results if x.get("overflow")]
    small = [f"{label(x)}: {x['smallText'][0]}" for x in results if x.get("smallTextCount")]
    taps = [f"{label(x)}: {x['smallTaps'][0]}" for x in results if x.get("smallTapCount")]
    slow = [f"{label(x)} {x['loadMs']} ms" for x in results if x.get("loadMs", 0) > 8000]
    hosts, kept = audit_privacy_probe(results, urllib.parse.urlsplit(base).netloc)
    n = len(results)
    return [
        _gate("Browser", "Pages load only from our own domains", not hosts,
              "; ".join(hosts[:4]) + " — privacy.html says loading a page contacts no "
              "third party"),
        _gate("Browser", "No page sets a cookie or stores anything", not kept,
              "; ".join(kept[:4]) + " — privacy.html says nothing is stored on a "
              "visitor's device"),
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


@_simulation_log_secret()
def check_email_widths() -> list[Gate]:
    """GATE-2: the emails this week's run would send, at a true 390px phone.
    A test pins the 2024 sample's email; the live week and the battery are
    what real inboxes get, and a long player name or a new row only shows up
    there. Every other email too (other_email_samples, at its longest): the
    gate measured only reports, so a welcome, a seat note or the launch
    announcement could scroll sideways on launch day with this gate green."""
    from render.email import render_email
    from render.live_sample import build
    from run.solo import SeasonOver
    emails: list[tuple[str, str]] = []
    try:
        sample = build()
        emails.append(("this week's sample", render_email(sample)))
    except SeasonOver as exc:
        return [Gate("Browser", "Every email fits a 390px phone", "SKIP", f"offseason: {exc}")]
    built = battery_reports()
    if not isinstance(built, str):
        emails += [(label, render_email(report)) for label, report in built]
    season = str((sample.get("meta") or {}).get("season") or date.today().year)
    emails += [(name, page) for name, page, _ in other_email_samples(season)]
    with tempfile.TemporaryDirectory() as tmp:
        names = {}
        for i, (label, page) in enumerate(emails):
            names[f"email-{i}.html"] = label
            (Path(tmp) / f"email-{i}.html").write_text(page, encoding="utf-8")
        with _serving(Path(tmp)) as base:
            results = run_browser([{"path": name, "widths": [390], "settle": 300}
                                   for name in names], base)
    if isinstance(results, str):
        return [Gate("Browser", "Every email fits a 390px phone", "SKIP", results)]
    wide = [f"{names.get(x['path'], x['path'])} ({x.get('scrollWidth')}px)" for x in results
            if x.get("overflow") or "jobError" in x]
    return [_gate("Browser", "Every email fits a 390px phone (this week, every battery setup, "
                             "every other email)",
                  not wide, "; ".join(wide[:4]), f"{len(results)} emails at 390px")]


# The join page's constants the flows point at local stand-ins.
JOIN_CONSTANTS = ("STRIPE_LINK_SEASON", "STRIPE_LINK_MONTHLY", "STRIPE_LINK_PASS",
                  "FORM_ENDPOINT", "NOTIFY_LIST_ENDPOINT")
STUB_PLAN = {"season": "season", "monthly": "monthly", "league_pass": "pass"}
FLOW_EMAIL = "buyer.flow@example.com"
FLOW_VIA = "launch-check"
FLOW_TOKEN = "0123456789abcdef0123"
# (mode, which copy, query, what leaves the page, the plan a checkout ref carries)
FLOWS = (
    ("season", "open", f"?via={FLOW_VIA}", "checkout", "season"),
    ("monthly", "open", "?plan=monthly", "checkout", "monthly"),
    ("League Pass", "open", "?plan=pass", "checkout", "league_pass"),
    # The generic seat route claims nothing (contract C3): it only says where
    # the league's own link is, and nothing may leave the page.
    ("seat (no link)", "open", "?pass=1", "none", None),
    ("seat (payer's link)", "open", f"?pass={FLOW_TOKEN}&s=half_ppr&n=10&t=sf", "seat", None),
    ("free report", "open", f"?try=1&via={FLOW_VIA}", "trial", None),
    # Every report links the update page WITH its subscription's settings
    # (run/updates.public_update_url, FUNNEL F1); a bare link — an old report,
    # a typed address — makes the subscriber tick that the settings on screen
    # are their league's (``FLOW_TICKS``). The bare flow alone FAILED once the
    # box arrived, because nothing here ticked it.
    ("roster update (report link)", "open", "?update=1&s=half_ppr&n=10&t=sf",
     "update_request", None),
    ("roster update (bare link)", "open", "?update=1", "update_request", None),
    ("closed checkout", "closed", "", "waitlist", None),
)
# Boxes a buyer must tick in a mode before its button posts anything.
FLOW_TICKS = {"roster update (bare link)": ["settings-ok"]}


def join_copy(dest: Path, base: str, links_open: bool) -> list[str]:
    """site/ copied to ``dest`` with the join page's payment links and form
    endpoint pointed at this run's stand-ins (``links_open``: whether the
    payment links are set at all). -> the constants it could not find."""
    shutil.copytree(SITE, dest)
    page = dest / "join" / "index.html"
    text = page.read_text(encoding="utf-8")
    values = {"STRIPE_LINK_SEASON": f"{base}/__stripe/season" if links_open else "",
              "STRIPE_LINK_MONTHLY": f"{base}/__stripe/monthly" if links_open else "",
              "STRIPE_LINK_PASS": f"{base}/__stripe/pass" if links_open else "",
              "FORM_ENDPOINT": f"{base}/__form", "NOTIFY_LIST_ENDPOINT": f"{base}/__form"}
    missing = []
    for name, value in values.items():
        text, n = re.subn(rf'^const {name} = "[^"]*";', f'const {name} = "{value}";', text,
                          flags=re.M)
        if n != 1:
            missing.append(name)
    # The free report is completed as a buyer would once it is open: the
    # page's own switch (the landing's twin) is on in the copy.
    text, n = re.subn(r"^const TRIAL_OPEN = (true|false);", "const TRIAL_OPEN = true;", text,
                      flags=re.M)
    if n != 1:
        missing.append("TRIAL_OPEN")
    page.write_text(text, encoding="utf-8")
    return missing


def flow_roster(directory_json: Path) -> tuple[str, set[str]]:
    """The live sample's roster as a buyer would paste it — names from the
    page's own player list — and the ids it must resolve to."""
    from render.live_sample import LIVE_ROSTER
    names = {row[1]: row[0] for row in json.loads(
        directory_json.read_text(encoding="utf-8"))["players"]}
    ids = [pid for pid in LIVE_ROSTER if pid in names]
    return "\n".join(names[pid] for pid in ids) + "\n", set(ids)


def audit_flow(mode: str, kind: str, plan: str | None, query: str, result: dict,
               roster_ids: set[str], base: str) -> list[str]:
    """What is wrong with one completed join flow, read off what actually left
    the page. Empty means it is right. The rules: a Stripe hand-off carries
    exactly our two parameters, a ref Stripe will keep (^[A-Za-z0-9_-]{1,200}$
    — Stripe silently DROPS anything else while still taking the money), that
    decodes to the plan of the link it was sent to and the roster that was
    checked, a channel tag only as given, and the locked email exactly as
    typed; a form row carries the typed email and a decodable ref, once."""
    from run.intake import split_via
    from run.refs import STRIPE_REF_RE, RefError, decode_roster
    problems: list[str] = []
    if result.get("error"):
        return [f"{mode}: {result['error']}"]
    if kind == "none":
        if result.get("handoff") or result.get("posted"):
            problems.append(f"{mode}: something left the page")
        want = seat_link_missing_words()
        if not want or want not in str(result.get("note") or ""):
            problems.append(f"{mode}: the page does not say where the league's seat link is")
        if not result.get("mainHidden"):
            problems.append(f"{mode}: the form is still shown")
        return problems
    asked = urllib.parse.parse_qs(query.lstrip("?"))

    def check_ref(ref: str | None, want_plan: str | None) -> Any:
        if not ref:
            problems.append(f"{mode}: no roster reference")
            return None
        if len(ref) > 200 or not STRIPE_REF_RE.match(ref):
            problems.append(f"{mode}: a reference Stripe would drop ({len(ref)} chars)")
            return None
        core, via = split_via(ref)
        if via is not None and via != (asked.get("via") or [None])[0]:
            problems.append(f"{mode}: carries channel tag {via!r} nobody gave it")
        try:
            decoded = decode_roster(core)
        except RefError as exc:
            problems.append(f"{mode}: the reference does not decode ({exc})")
            return None
        if want_plan and decoded.plan != want_plan:
            problems.append(f"{mode}: a {decoded.plan} reference sent to the {want_plan} link")
        if set(decoded.player_ids) != roster_ids:
            problems.append(f"{mode}: the reference holds a different roster than was checked")
        return decoded

    if kind == "checkout":
        url = result.get("handoff")
        if not url:
            return [f"{mode}: never reached checkout"]
        parsed = urllib.parse.urlparse(url)
        if f"{parsed.scheme}://{parsed.netloc}{parsed.path}" != f"{base}/__stripe/{STUB_PLAN[plan]}":
            problems.append(f"{mode}: sent to {parsed.path}, not the {plan} link")
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if set(params) != {"client_reference_id", "locked_prefilled_email"}:
            problems.append(f"{mode}: hand-off parameters {sorted(params)}")
        check_ref((params.get("client_reference_id") or [None])[0], plan)
        if (params.get("locked_prefilled_email") or [None])[0] != FLOW_EMAIL:
            problems.append(f"{mode}: the locked email is not the one typed")
        return problems

    rows = result.get("posted") or []
    if len(rows) != 1:
        return [f"{mode}: posted {len(rows)} rows (one expected)"]
    try:
        row = json.loads(rows[0])
    except (TypeError, ValueError):
        return [f"{mode}: posted something that isn't JSON"]
    if str(row.get("kind") or "seat") != kind:
        problems.append(f"{mode}: posted kind {row.get('kind')!r}, not {kind!r}")
    if row.get("email") != FLOW_EMAIL:
        problems.append(f"{mode}: the posted email is not the one typed")
    if "via" in row and row["via"] != (asked.get("via") or [None])[0]:
        problems.append(f"{mode}: posted channel tag {row['via']!r}")
    if kind == "waitlist":
        if row.get("ref"):
            check_ref(row["ref"], None)
        return problems
    decoded = check_ref(row.get("ref"), None)
    # Settings a link carried (a seat link, a report's update link — the one
    # s/n/t format, run/updates.settings_params) must be the ones posted:
    # an update REPLACES the subscription's settings with the ref's.
    if decoded is not None and asked.get("s"):
        from run.trial import TEMPLATES
        want = ((asked.get("s") or [""])[0], int((asked.get("n") or ["0"])[0]),
                tuple(TEMPLATES.get((asked.get("t") or [""])[0], ())))
        if (decoded.scoring, decoded.league_size, tuple(decoded.slots)) != want:
            problems.append(f"{mode}: the link's settings were not carried")
    if kind == "seat":
        # The payer's own link is the only seat route (contracts C3/C4): the
        # token names the pass, and a typed address never travels.
        if row.get("pass_token") != (asked.get("pass") or [None])[0]:
            problems.append(f"{mode}: posted a different pass token")
        if "covered_by" in row:
            problems.append(f"{mode}: posted a typed payer address")
    return problems


def seat_link_missing_words(text: str | None = None) -> str:
    """What the join page tells a visitor who opened a seat page without
    their league's link (``seatLinkMissingWords`` in site/join/index.html),
    read from the page so the check and the page cannot drift."""
    text = text if text is not None else (SITE / "join/index.html").read_text(encoding="utf-8")
    match = re.search(r"function seatLinkMissingWords\(\)\s*\{\s*return\s+(.*?);", text, re.S)
    if not match:
        return ""
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1)))


def audit_plan_switch(switched: dict | None, monthly_offered: bool = True) -> list[str]:
    """Season ⇄ monthly on the page rewrites the button and the terms line
    above it, and switching back restores the season pass exactly — a buyer
    must never read the season pass's renewal terms above a monthly button.
    With monthly not offered (2026's one-time passes, join MONTHLY_OFFERED)
    there is no switch: the season pass's own price must still be shown."""
    from render.welcome import MONTHLY_PRICE, SEASON_PRICE
    if not monthly_offered:
        before = (switched or {}).get("before") or {}
        if SEASON_PRICE not in before.get("button", "") + before.get("terms", ""):
            return [f"season: {SEASON_PRICE} is not on the button or terms line"]
        return []
    if not switched or not switched.get("after"):
        return ["season: the page offers no switch to monthly"]
    before, after, back = switched["before"], switched["after"], switched["back"]
    problems = []
    if SEASON_PRICE not in before["button"] + before["terms"]:
        problems.append(f"season: {SEASON_PRICE} is not on the button or terms line")
    if MONTHLY_PRICE not in after["button"] or MONTHLY_PRICE not in after["terms"]:
        problems.append(f"monthly: the button or terms line still reads {after}")
    if SEASON_PRICE in after["terms"]:
        problems.append("monthly: the season pass's terms are still above the button")
    if back != before:
        problems.append("season: switching back did not restore the season pass")
    return problems


def check_join_flows() -> list[Gate]:
    """GATE-5: every join mode completed in a real browser, on a copy of the
    site whose payment links and form endpoint are local stand-ins, and the
    hand-off or row that left the page checked as the intake will read it.
    The only earlier check read the page's source text."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as tmp:
        missing = (join_copy(Path(tmp) / "open", base, True)
                   + join_copy(Path(tmp) / "closed", base, False))
        if missing:
            return [Gate("Browser", "Every join mode hands off a well-formed purchase or row",
                         "FAIL", f"join page constants not found: {sorted(set(missing))}")]
        roster_text, roster_ids = flow_roster(Path(tmp) / "open" / "join" / "players.json")
        # Monthly isn't sold in 2026 (join MONTHLY_OFFERED): ?plan=monthly is
        # the season pass then, and the monthly flow is not one a buyer can take.
        offered = js_constants((SITE / "join/index.html").read_text(encoding="utf-8")) \
            .get("MONTHLY_OFFERED") != "false"
        flows = [f for f in FLOWS if offered or f[0] != "monthly"]
        jobs = [{"kind": "flow", "mode": mode, "path": f"{copy}/join/index.html{query}",
                 "width": 390, "roster": roster_text, "email": FLOW_EMAIL,
                 "planSwitch": mode == "season", "tick": FLOW_TICKS.get(mode, []),
                 **({"expect": "nothing"} if kind == "none" else {})}
                for mode, copy, query, kind, _p in flows]
        with _serving(Path(tmp), port):
            results = run_browser(jobs, base)
    name = "Every join mode hands off a well-formed purchase or row"
    if isinstance(results, str):
        return [Gate("Browser", name, "SKIP", results)]
    by_mode = {r.get("mode"): r for r in results}
    problems: list[str] = []
    for mode, _copy, query, kind, plan in flows:
        result = by_mode.get(mode) or {"error": "no result"}
        problems += audit_flow(mode, kind, plan, query, result, roster_ids, base)
        if mode == "season" and not result.get("error"):
            problems += audit_plan_switch(
                result.get("switched"),
                js_constants((SITE / "join/index.html").read_text(encoding="utf-8"))
                .get("MONTHLY_OFFERED") != "false")
    errors = [f"{r['mode']}: {r['errors'][0][:100]}" for r in results if r.get("errors")]
    return [_gate("Browser", name, not problems, "; ".join(problems[:5]),
                  f"{len(flows)} modes: {', '.join(m for m, *_ in flows)}"),
            _gate("Browser", "No script errors while completing the join modes", not errors,
                  "; ".join(errors[:3]))]


def axe_core_path() -> Path | None:
    """axe-core's browser bundle: AXE_CORE_PATH, or `npm install --no-save
    axe-core@4.11.4` in the repo. Not vendored — the gate SKIPs without it."""
    for candidate in (os.environ.get("AXE_CORE_PATH"),
                      REPO / "node_modules" / "axe-core" / "axe.min.js"):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


# Every page a buyer sells themselves on, and every join mode.
A11Y_PAGES = SELLING + ("join/index.html?plan=monthly", "join/index.html?plan=pass",
                        "join/index.html?pass=1", "join/index.html?try=1",
                        "join/index.html?update=1", "join/confirm.html")


def check_accessibility() -> list[Gate]:
    """GATE-19: axe-core over every selling page and every join mode at 390 and
    1280. Serious and critical violations FAIL (a screen-reader user cannot
    complete the purchase, or cannot read the price); moderate and minor are
    listed as a WARN."""
    name = "No serious accessibility problem on a selling page or join mode"
    axe = axe_core_path()
    if axe is None:
        return [Gate("Browser", name, "SKIP", "axe-core not found — set AXE_CORE_PATH or "
                     "`npm install --no-save axe-core@4.11.4` in the repo")]
    with _serving(SITE) as base:
        results = run_browser([{"kind": "axe", "path": p, "widths": [390, 1280],
                                "axe": str(axe)} for p in A11Y_PAGES], base)
    if isinstance(results, str):
        return [Gate("Browser", name, "SKIP", results)]
    serious, minor = [], []
    for x in results:
        if "jobError" in x:
            serious.append(f"{x['path']}: could not run ({x['jobError'][:80]})")
            continue
        for v in x.get("violations") or []:
            line = f"{x['path']} @{x['width']}: {v['id']} ×{v['nodes']} ({v['help']})"
            (serious if v.get("impact") in ("serious", "critical") else minor).append(line)
    found = list(dict.fromkeys(serious))
    return [_gate("Browser", name, not found, "; ".join(found[:4])
                  + (f" … {len(found)} in all" if len(found) > 4 else ""),
                  f"{len(results)} page loads, axe-core"),
            _gate("Browser", "No moderate or minor accessibility problems", not minor,
                  "; ".join(list(dict.fromkeys(minor))[:4]), fail="WARN")]


# Lighthouse's mobile budget for "good": the largest paint by 2.5s and a
# layout that moves under 0.1, on the network and CPU a mid-range phone has.
LCP_BUDGET_MS = 2500
CLS_BUDGET = 0.1
SPEED_RUNS = 3


def check_speed() -> list[Gate]:
    """GATE-20: each selling page on Slow 4G with a 4x slower CPU, median of
    three fresh loads. The only earlier speed gate was an unthrottled
    localhost load event, which practically cannot fail. Served from this
    machine there is no DNS or TLS handshake to pay for, so the figure is a
    little kinder than a real phone's: a page near the budget is over it."""
    with _serving(SITE) as base:
        results = run_browser([{"kind": "perf", "path": p, "width": 390, "runs": SPEED_RUNS}
                               for p in SELLING], base, timeout=2400)
    if isinstance(results, str):
        return [Gate("Browser", "The largest paint lands within 2.5s on a phone", "SKIP", results)]
    slow, shifty, unmeasured, seen = [], [], [], []
    for x in results:
        lcps = [v for v in x.get("lcp") or [] if v is not None]
        clss = [v for v in x.get("cls") or [] if v is not None]
        if "jobError" in x or not lcps:
            unmeasured.append(x["path"])
            continue
        lcp, cls = statistics.median(lcps), statistics.median(clss) if clss else 0.0
        seen.append(f"{x['path']} {lcp / 1000:.1f}s/{cls:.2f}")
        if lcp > LCP_BUDGET_MS:
            slow.append(f"{x['path']} {lcp / 1000:.1f}s")
        if cls > CLS_BUDGET:
            shifty.append(f"{x['path']} {cls:.2f}")
    return [_gate("Browser", "The largest paint lands within 2.5s on a phone (Slow 4G, 4x CPU)",
                  not slow and not unmeasured,
                  "; ".join(slow[:5] + [f"{p}: not measured" for p in unmeasured[:2]]),
                  f"median of {SPEED_RUNS}: " + ", ".join(seen[:4])
                  + (" …" if len(seen) > 4 else "")),
            _gate("Browser", "The layout does not jump while it loads (CLS ≤ 0.1)", not shifty,
                  "; ".join(shifty[:5]), fail="WARN")]


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


# The GitHub account that owns the repo and its Pages site: the verified
# domain's TXT record is named after it.
GITHUB_ACCOUNT = "beatyourleague"
SECURITY_TXT = SITE / ".well-known" / "security.txt"


def check_security_txt(today: date | None = None) -> list[Gate]:
    """INFRA-15: site/.well-known/security.txt (RFC 9116) names where a
    security report goes, and its Expires is ahead — a lapsed one tells a
    reporter the address is dead. Read from the repo, so it runs offline."""
    name = "security.txt names a contact and has not expired"
    if not SECURITY_TXT.is_file():
        return [Gate("Site", name, "FAIL", "site/.well-known/security.txt is missing")]
    fields: dict[str, str] = {}
    for line in SECURITY_TXT.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            fields.setdefault(key.strip().lower(), value.strip())
    try:
        expires = datetime.fromisoformat(fields.get("expires", "").replace("Z", "+00:00"))
    except ValueError:
        return [Gate("Site", name, "FAIL", "no readable Expires line")]
    if not fields.get("contact", "").startswith(("mailto:", "https://")):
        return [Gate("Site", name, "FAIL", "no Contact line")]
    left = (expires.date() - (today or date.today())).days
    if left < 0:
        return [Gate("Site", name, "FAIL", f"expired {expires.date()} — set a new Expires")]
    return [_gate("Site", name, left >= 30,
                  f"expires {expires.date()} — set a new Expires (at most a year ahead)",
                  f"{fields['contact']}, expires {expires.date()}", fail="WARN")]


def check_hardening() -> list[Gate]:
    """INFRA-15: the owner's account and DNS hardening (LAUNCH.md step 0 and
    section 11), read back from outside — each an OWNER line until done, like
    the DMARC gate. Read-only: dig, `gh api` GETs and two HTTPS GETs."""
    import requests
    gates: list[Gate] = []
    try:
        challenge = _dig("TXT", f"_github-pages-challenge-{GITHUB_ACCOUNT}.{DOMAIN}")
        ds = _dig("DS", DOMAIN)
        caa = _dig("CAA", DOMAIN)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        gates.append(Gate("Owner", "The domain's hardening can be read", "SKIP", str(exc)))
    else:
        gates += [
            _gate("Owner", "The domain is verified for GitHub Pages", bool(challenge),
                  f"no _github-pages-challenge-{GITHUB_ACCOUNT} TXT record — LAUNCH.md "
                  "step 0.7, before ANY hosting or visibility change", "verified",
                  fail="OWNER"),
            _gate("Owner", "DNSSEC is on", bool(ds),
                  "no DS record — Cloudflare → DNS → Settings → DNSSEC (LAUNCH.md step 0.3)",
                  "DS published", fail="OWNER"),
            _gate("Owner", "CAA records limit who may issue the certificate", bool(caa),
                  "no CAA record — optional; add it once the site's host is settled "
                  "(LAUNCH.md section 11), so it names the authority that host uses",
                  ", ".join(caa[:3]), fail="WARN"),
        ]
    rules = _gh_json("repos/{owner}/{repo}/rules/branches/main")
    if not isinstance(rules, list):
        gates.append(Gate("Owner", "main can't be force-pushed or deleted", "OWNER",
                          "can't read main's rules from here (gh signed out, or a private "
                          "repo on the Free plan, which has none) — LAUNCH.md step 0.5"))
    else:
        types = {r.get("type") for r in rules if isinstance(r, dict)}
        gates.append(_gate("Owner", "main can't be force-pushed or deleted",
                           {"deletion", "non_fast_forward"} <= types,
                           "no ruleset with Restrict deletions and Block force pushes on "
                           "main — LAUNCH.md step 0.5", "ruleset active", fail="OWNER"))
    try:
        page = requests.get(f"{LIVE}/join/", timeout=20)
        missing = [h for h in ("strict-transport-security", "content-security-policy")
                   if h not in {k.lower() for k in page.headers}]
        gates.append(_gate("Live", "The live site sends HSTS and a Content-Security-Policy",
                           not missing, "no " + " or ".join(missing) + " — GitHub Pages "
                           "can't send headers; site/_headers takes effect on Cloudflare "
                           "Pages (LAUNCH.md section 11)", "both present", fail="OWNER"))
        found = requests.get(f"{LIVE}/.well-known/security.txt", timeout=20)
        gates.append(_gate("Live", "The live site serves security.txt",
                           found.status_code == 200 and "Contact:" in found.text,
                           f"/.well-known/security.txt answered {found.status_code} — "
                           "pushed yet?", "served", fail="WARN"))
    except requests.RequestException as exc:
        gates.append(Gate("Live", "The live site's security headers", "SKIP",
                          type(exc).__name__))
    return gates
def worker_status(endpoint: str, api_key: str) -> dict:
    """The form Worker's own switches (GET ?status=1 with the read key,
    infra/form-worker.js). Read-only: no row is listed or written."""
    import urllib.request
    joiner = "&" if "?" in endpoint else "?"
    request = urllib.request.Request(f"{endpoint}{joiner}status=1", method="GET",
                                     headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict) or "trial_open" not in data:
        raise ValueError("the Worker does not answer ?status=1 — re-paste infra/form-worker.js")
    return data


def check_worker_switches() -> list[Gate]:
    """The site's TRIAL_OPEN and the Worker's must agree: the Worker refuses
    every free-report row while its own variable is off, so a site that
    offers free reports over a Worker that refuses them loses every request
    (pre-launch review, SEC-06's second half)."""
    name = "The form Worker takes free-report requests exactly when the site offers them"
    site = js_constants((SITE / "index.html").read_text(encoding="utf-8")).get("TRIAL_OPEN") == "true"
    endpoint = os.environ.get("FORM_ENDPOINT", "").strip()
    key = os.environ.get("FORM_API_KEY", "").strip()
    if not endpoint or not key:
        if site:
            return [Gate("Owner", name, "OWNER",
                         "TRIAL_OPEN is on in the site — set the Worker's TRIAL_OPEN variable "
                         "to true as well (LAUNCH.md step 5), then run this with FORM_ENDPOINT "
                         "and FORM_API_KEY in the shell to confirm")]
        return [Gate("Owner", name, "SKIP", "needs FORM_ENDPOINT and FORM_API_KEY in the shell")]
    try:
        worker = bool(worker_status(endpoint, key).get("trial_open"))
    except Exception as exc:  # noqa: BLE001 — reported, never guessed
        return [Gate("Owner", name, "WARN", f"could not read the Worker's switches: {exc}")]
    if site and not worker:
        return [Gate("Owner", name, "FAIL", "the site offers free reports and the Worker's "
                     "TRIAL_OPEN is not \"true\": every request is refused (LAUNCH.md step 5)")]
    if worker and not site:
        return [Gate("Owner", name, "WARN", "the Worker takes free-report rows while the site's "
                     "TRIAL_OPEN is off; nothing is served (run/trials.py) — unset it")]
    return [Gate("Owner", name, "PASS", f"both {'on' if site else 'off'}")]


def check_resend_read_key() -> list[Gate]:
    """The bounce check (run/delivery.check_bounces) reads each sent email
    back from Resend, which the sending key cannot do: without a Full access
    RESEND_READ_KEY it says so once per run and checks nothing."""
    name = "The bounce check has a Resend key that can read sent email"
    if os.environ.get("RESEND_READ_KEY", "").strip():
        return [Gate("Email", name, "PASS", "RESEND_READ_KEY is set in this shell")]
    return [Gate("Email", name, "OWNER",
                 "RESEND_READ_KEY is not in this shell — Resend's Sending access key can only "
                 "send, so a bounced buyer address goes unseen. Create a Full access key and "
                 "save it as the GitHub secret RESEND_READ_KEY (LAUNCH.md step 2)")]


# What a proxy in front of the site would add to a page or a response, any one
# of which makes privacy.html's "no cookies … no request to any third party"
# false without a byte of the repo changing (ANALYTICS-06/09): Web Analytics'
# automatic setup, Rocket Loader and Email Obfuscation (/cdn-cgi/scripts),
# Zaraz, the bot products' cookies and challenge scripts.
EDGE_INJECTION = re.compile(r"cloudflareinsights|/cdn-cgi/(?:rum|scripts|zaraz|challenge-platform)"
                            r"|zaraz|__cf_bm|cf_clearance", re.I)


def audit_live_responses(responses: Iterable[tuple[str, Any]]) -> list[str]:
    """What is wrong with the live pages as served: a Set-Cookie header, or
    something injected into an HTML page that the repo never wrote."""
    problems = []
    for path, r in responses:
        if r.headers.get("set-cookie"):
            problems.append(f"/{path} sets a cookie ({r.headers['set-cookie'].split('=')[0]})")
        if "html" in (r.headers.get("content-type") or "") and EDGE_INJECTION.search(r.text or ""):
            problems.append(f"/{path} carries {EDGE_INJECTION.search(r.text).group(0)}")
    return problems


def audit_counter_response(r: Any) -> list[str]:
    """The counter's preflight as a browser on our site would send it: 204,
    our origin allowed, and no cookie (Bot Fight Mode would add __cf_bm)."""
    problems = []
    if r.status_code != 204:
        problems.append(f"answered {r.status_code}, not 204")
    if r.headers.get("set-cookie"):
        problems.append(f"sets a cookie ({r.headers['set-cookie'].split('=')[0]})")
    if r.headers.get("access-control-allow-origin") not in (LIVE, "*"):
        problems.append("does not allow our origin (access-control-allow-origin "
                        f"{r.headers.get('access-control-allow-origin')!r})")
    return problems


def check_live() -> list[Gate]:
    import requests
    gates = []
    bad = []
    served: list[tuple[str, Any]] = []
    for path in ("", "join/", "how-it-works.html", "league-pass.html", "sample-report.html",
                 "this-week.html", "terms.html", "privacy.html", "sitemap.xml", "og.png"):
        try:
            r = requests.get(f"{LIVE}/{path}", timeout=20)
            if r.status_code != 200:
                bad.append(f"/{path} {r.status_code}")
            served.append((path, r))
        except requests.RequestException as exc:
            bad.append(f"/{path} {type(exc).__name__}")
    gates.append(_gate("Live", "Every key page on the live site answers 200", not bad,
                       "; ".join(bad[:5]), LIVE))
    edge = audit_live_responses(served)
    gates.append(_gate("Live", "The live site sets no cookie and nothing is injected at the edge",
                       not edge, "; ".join(edge[:4]) + " — privacy.html says no cookies and no "
                       "third-party request: switch it off in Cloudflare (LAUNCH.md step 5b)",
                       f"{len(served)} responses"))
    counter = counter_endpoint()
    if counter:
        try:
            r = requests.options(counter, timeout=20, headers={
                "Origin": LIVE, "Access-Control-Request-Method": "POST"})
            trouble = audit_counter_response(r)
        except requests.RequestException as exc:
            trouble = [type(exc).__name__]
        gates.append(_gate("Live", "The page counter answers 204 with no cookie", not trouble,
                           f"{counter}: " + "; ".join(trouble), counter))
    try:
        counted = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=REPO,
                                 capture_output=True, text=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "site"], cwd=REPO,
                               capture_output=True, text=True).stdout.strip()
    except OSError:
        counted, dirty = None, ""
    # A branch with no upstream answers nothing (rev-list fails): that is "can't
    # tell", never "pushed".
    if counted is None or counted.returncode:
        gates.append(Gate("Live", "The live site is what is in the repo", "SKIP",
                          "this branch has no upstream to compare with"))
        return gates
    ahead = counted.stdout.strip()
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
    gates = [_gate("Owner", "GitHub Actions secrets are set", not missing,
                   "missing: " + ", ".join(missing) + " — " + features_off(missing),
                   f"all {len(REQUIRED_SECRETS)} present", fail="OWNER")]
    return gates + log_secret_gate(names)


def log_secret_gate(names: set[str] | None) -> list[Gate]:
    """D4: once checkout is open, no LOG_SECRET is a FAIL, not owner setup —
    every real send refuses without it (welcomes, reports, renewal notices),
    so a buyer would pay and receive nothing."""
    landing = js_constants((SITE / "index.html").read_text(encoding="utf-8"))
    if landing.get("CHECKOUT_OPEN") != "true" or names is None:
        return []
    return [_gate("Owner", "LOG_SECRET is set while checkout is open",
                  "LOG_SECRET" in names,
                  "checkout is open and LOG_SECRET is missing: every send refuses "
                  "(run/digest.py) — set it before taking money (LAUNCH.md step 3)")]


def features_off(missing: Iterable[str]) -> str:
    """Which features stop working without these secrets, in the owner's
    words — so "UPDATE_SECRET missing" reads as what a buyer loses."""
    gone = set(missing)
    off = [feature for feature, needs in FEATURE_SECRETS.items() if gone & set(needs)]
    return ("off until then: " + "; ".join(off)) if off else "nothing a buyer sees"


def check_compliance() -> list[Gate]:
    from render.welcome import welcome_message
    gates = []
    join = visible_text((SITE / "join/index.html").read_text(encoding="utf-8"))
    # 2026 sells one-time passes (owner decision, Oct 18 2026): the disclosure
    # above the button is the price, that nothing renews, and the refund.
    from render.welcome import SEASON_PRICE
    gates.append(_gate("Compliance", "Price, no-renewal and refund terms sit above the pay button",
                       f"{SEASON_PRICE}, one payment" in join
                       and "nothing renews" in join and "Refunds are no-questions" in join,
                       "the join page's terms line lost a disclosure"))
    msg = welcome_message("x@example.com", "season", "abcdef0123", "2026", one_time=True)
    body = visible_text(msg.html)
    gates.append(_gate("Compliance", "The welcome email states that nothing renews, the refund, and how to stop",
                       "nothing renews" in body and "Refunds are no-questions" in body
                       and "stop" in body,
                       "the acknowledgment email lost a disclosure"))
    # The postal address (CAN-SPAM, CASL) is check_email_senders' question now:
    # it renders every email type and looks for the block in each, where this
    # gate only asked whether the variable was set (GATE-9).
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from infra.stripe_paylink_text import MESSAGES, TOS_MESSAGES
    from render.welcome import TERMS_VERSION
    from datetime import date
    stamp = date.fromisoformat(TERMS_VERSION)
    terms = (SITE / "terms.html").read_text(encoding="utf-8")
    gates.append(_gate("Compliance", "Stripe's Pay-button text matches the terms (one payment)",
                       not any("each season" in m for m in MESSAGES.values())
                       and all("Nothing renews" in MESSAGES[p] for p in ("season", "league_pass")),
                       "infra/stripe_paylink_text.py says something the terms don't"))
    gates.append(_gate("Compliance", "The checkout's terms box names what's bought and 18+",
                       all("18 or older" in t and "[Terms](" in t for t in TOS_MESSAGES.values()),
                       "a TOS_MESSAGES entry lost a required element"))
    gates.append(_gate("Compliance", "The terms carry the version consent is recorded against",
                       f"Last updated {stamp.day} {stamp:%B %Y}" in terms,
                       f"terms.html's Last updated date ≠ TERMS_VERSION {TERMS_VERSION}"))
    privacy = visible_text((SITE / "privacy.html").read_text(encoding="utf-8"))
    missing = [p for p in ("Stripe", "Resend", "Cloudflare", "GitHub", "Google", "United States")
               if p not in privacy]
    gates.append(_gate("Compliance", "The privacy policy names every processor and where data lives",
                       not missing, f"missing: {', '.join(missing)}"))
    worker = (REPO / "infra" / "form-worker.js").read_text(encoding="utf-8")
    gates.append(_gate("Compliance", "Form rows expire as the privacy policy says",
                       "expirationTtl" in worker,
                       "infra/form-worker.js stores rows forever; privacy.html promises ~13 months"))
    gates += check_seat_link()
    return gates


def check_seat_link() -> list[Gate]:
    """A League Pass payer's welcome names the ONE link their league shares
    (contract C4): built from UPDATE_SECRET (the seat-token key) and SITE_URL.
    The code is checked here with stand-ins. Whether the two secrets exist on
    the crons is the secrets gate's question (FEATURE_SECRETS): without them
    the welcome falls back to the generic seat page plus "tell them your
    email", which is the owner's step, not a defect."""
    from render.welcome import welcome_message
    from run.refs import RosterRef
    from run.updates import seat_url
    roster = RosterRef(plan="league_pass", scoring="ppr", slots=TEMPLATE_SLOTS["std"],
                       player_ids=tuple(f"00-00000{i:02d}" for i in range(9)), league_size=12)
    link = seat_url("https://example.com", "launch-check-secret", "payer@example.com", roster)
    page = welcome_message("payer@example.com", "league_pass", "abcdef0123", "2026",
                           seat_link=link).html if link else ""
    shown = bool(link) and (link in page or html.escape(link) in page)
    return [_gate("Compliance", "A League Pass payer's welcome carries their league's seat link",
                  shown, "built from UPDATE_SECRET and SITE_URL, the link is missing from the "
                         "pass welcome")]


@contextlib.contextmanager
def _env(name: str, value: str | None) -> Iterator[None]:
    """``name`` set to ``value`` (None: unset) for the block, then restored."""
    before = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = before


# A transactional reply to the reader's own request, with no ask in it and no
# list behind it: the roster-change confirmation. Exempt from both checks, as
# tests/test_email_safety.py exempts it.
TRANSACTIONAL = ("roster confirmation",)
WAY_OUT = re.compile(r"cancel|reply \"stop\"|only email we.ll send you|unsubscrib", re.I)


def email_samples(report: dict | None = None) -> list[tuple[str, str, str | None]]:
    """(name, html, List-Unsubscribe or None) for every email the product
    sends, built by the same functions the runners call, around THIS week's
    live report where a report is involved (``report``, built when not
    given)."""
    import copy

    from engine.final_check import Change
    from render.email import render_email
    from render.final_check import render_final_check
    from render.live_sample import build
    from render.report import unsubscribe_target
    report = report if report is not None else build()

    def variant(**meta) -> str:
        out = copy.deepcopy(report)
        out["meta"].update(meta)
        return render_email(out)

    week = int(report["meta"]["week"])
    out = [("weekly report", render_email(report), unsubscribe_target(False)),
           ("free report", variant(trial=True), None),
           ("seat report", variant(plan="league_pass"), unsubscribe_target(True)),
           ("Saturday final check",
            render_final_check({"week": week, "players": {}},
                               [Change("swap", "Start X at RB", "Y is out.")],
                               datetime.now(timezone.utc)), unsubscribe_target(False))]
    out += other_email_samples(str(report["meta"]["season"]))
    roster = roster_report()
    if roster is not None:
        from render.preseason import preseason_message
        msg = preseason_message("a@example.com", "abcdef0123", roster)
        out.append(("roster report", msg.html, msg.unsubscribe))
    return out


# A pass payer's seat link at its longest: one unbroken string, which once
# pushed the welcome 17px past a 390px phone (render/welcome.py).
SAMPLE_SEAT_LINK = "https://example.com/join/?pass=" + "0" * 20 + "&s=half_ppr&n=14&t=flex2-nokd"


def other_email_samples(season: str) -> list[tuple[str, str, str | None]]:
    """Every email that is not built around a weekly report, as the runners
    build them, each in its longest form: the roster-change confirmation with
    every setting moving, every welcome (and the League Pass bought over a
    season pass, with its seat link), the renewal notice, the three notes a
    League Pass seat claim can get, and the launch announcement with and
    without a saved roster. (name, html, List-Unsubscribe or None)."""
    from render.renewal import Renewal, renewal_message
    from render.report import seat_stop_href
    from render.roster_update import confirm_email
    from render.seat_claim import confirm_email as seat_confirm_email
    from render.seat_claim import full_email, unmatched_email
    from render.welcome import welcome_message
    from run.refs import encode_roster
    from run.waitlist import messages
    import render.live_sample as live_sample
    import render.sample as sample
    on_file = {"scoring": "ppr", "league_size": 12, "slots": TEMPLATE_SLOTS["std"]}
    wanted = {"scoring": "half_ppr", "league_size": 10, "slots": TEMPLATE_SLOTS["sf"]}
    out = [("roster confirmation",
            confirm_email("https://example.com/join/confirm.html?c=" + "a" * 24,
                          ["A", "B"], settings=wanted, on_file=on_file)[1], None)]
    bought = datetime.now(timezone.utc).isoformat()
    for plan in ("season", "monthly", "league_pass", "seat"):
        msg = welcome_message("a@example.com", plan, "abcdef0123", season, purchased_at=bought)
        out.append((f"welcome ({plan})", msg.html, msg.unsubscribe))
    msg = welcome_message("a@example.com", "league_pass", "abcdef0123", season,
                          purchased_at=bought, seat_link=SAMPLE_SEAT_LINK, duplicate="season")
    out.append(("welcome (League Pass over a season pass)", msg.html, msg.unsubscribe))
    msg = renewal_message(Renewal("a@example.com", "$39.00 USD", date.today() + timedelta(days=30),
                                  "year", plan="season"))
    out.append(("renewal notice", msg.html, msg.unsubscribe))
    out += [("failed seat claim", unmatched_email("https://example.com")[1], seat_stop_href()),
            ("seat pass full", full_email("https://example.com")[1], seat_stop_href()),
            ("seat confirmation",
             seat_confirm_email("https://example.com/join/confirm.html?c=" + "a" * 24
                                + "&k=seat", ["A", "B"])[1], seat_stop_href())]
    msg = messages(["a@example.com"], "https://example.com/join/")[0]
    out.append(("launch announcement", msg.html, msg.unsubscribe))
    ref = encode_roster("season", "ppr", sample.SLOTS, list(live_sample.LIVE_ROSTER),
                        league_size=12) + "_via-reply-kit"
    msg = messages(["a@example.com"], "https://example.com/join/", {"a@example.com": ref})[0]
    out.append(("launch announcement (saved roster)", msg.html, msg.unsubscribe))
    return out


def roster_report() -> dict | None:
    """The purchase-day roster report for the live sample's roster, built the
    way render/preseason.py's own entry point builds it. None if it cannot."""
    try:
        from engine.nflverse_backtest import TEMPLATE_T1
        from engine.preseason import build_preseason_report
        from engine.subscriber import RosterSpec
        from render.live_sample import LIVE_ROSTER
        from run.solo import CACHE_DIR, current_season, load_week_data
        season = current_season(CACHE_DIR)
        data = load_week_data(CACHE_DIR, str(int(season) - 1), 10, live=False)
        known = {p.player_id for p in data.directory.players}
        spec = RosterSpec(player_ids=tuple(p for p in LIVE_ROSTER if p in known),
                          slots=TEMPLATE_T1, scoring="ppr", label="Your Team")
        return build_preseason_report(spec, data.directory, data.prior, str(season),
                                      CACHE_DIR, prior_season=str(int(season) - 1))
    except Exception:  # noqa: BLE001 — the gate names it as not built
        return None


def audit_senders(samples: list[tuple[str, str, str | None]], line: str) -> dict[str, list[str]]:
    """Which emails lack the sender block (``line``) and which give the reader
    no way out — neither a List-Unsubscribe header nor a cancel or stop route
    in the body."""
    missing, no_way_out = [], []
    for name, page, unsubscribe in samples:
        text = html.unescape(page)
        if name in TRANSACTIONAL:
            continue
        if line not in text:
            missing.append(name)
        if not unsubscribe and not WAY_OUT.search(visible_text(page)):
            no_way_out.append(name)
    return {"missing": missing, "no_way_out": no_way_out}


PROBE_ADDRESS = "PO Box 0, Launch Check ON A1A 1A1"


@_simulation_log_secret()
def check_email_senders() -> list[Gate]:
    """GATE-9: every email type, rendered, carries who sent it (CAN-SPAM,
    CASL) and a way out. Unset SENDER_POSTAL_ADDRESS is the owner's step, so
    the code is checked under a stand-in address and the gate says OWNER; set,
    a single email without the block FAILS. The first version checked only
    that the variable was set — and the final check, all four welcomes, the
    renewal notice and the roster report never printed it (launch audit L3)."""
    from render.sender import postal_address, sender_line
    from run.solo import SeasonOver
    real = postal_address()
    try:
        with _env("SENDER_POSTAL_ADDRESS", real or PROBE_ADDRESS):
            samples = email_samples()
            line = sender_line() or ""
    except SeasonOver as exc:
        return [Gate("Email", "Every email names its sender and a way out", "SKIP",
                     f"offseason: {exc}")]
    found = audit_senders(samples, line)
    names = [n for n, *_ in samples]
    gates = []
    if found["missing"]:
        gates.append(Gate("Email", "Every email carries the sender block (name, postal address, "
                                   "contact)", "FAIL",
                          f"missing from: {', '.join(found['missing'])}"
                          + ("" if real else " (checked under a stand-in address)")))
    elif not real:
        gates.append(Gate("Email", "Every email carries the sender block (name, postal address, "
                                   "contact)", "OWNER",
                          f"all {len(names)} email types print it once SENDER_POSTAL_ADDRESS is "
                          f"set — a rented mailbox, never a home (LAUNCH.md step 2.6)"))
    else:
        gates.append(Gate("Email", "Every email carries the sender block (name, postal address, "
                                   "contact)", "PASS", f"{len(names)} email types"))
    gates.append(_gate("Email", "Every email gives a way out (List-Unsubscribe or a cancel/stop "
                                "route)", not found["no_way_out"],
                       f"none in: {', '.join(found['no_way_out'])}", ", ".join(names)))
    return gates


# --------------------------------------------------------------------- #
# gates: the accounts (read-only; each needs its own credential in the shell)
# --------------------------------------------------------------------- #

def _gh_json(path: str) -> Any:
    """`gh api <path>` as JSON, or None when gh is missing, signed out or the
    call fails. GET only."""
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(["gh", "api", path], cwd=REPO, capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def workflow_crons(name: str) -> list[str]:
    """The literal cron strings in .github/workflows/<name>."""
    text = (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")
    return re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', text, re.M)


def _cron_fires(cron: str, day: datetime) -> list[datetime]:
    """Every UTC time ``cron`` fires on ``day``'s date. Numbers, comma lists
    and * only — the only syntax the workflows use (infra/form-worker.js
    refuses anything else for the same reason)."""
    minute, hour, dom, month, dow = cron.split()

    def matches(field: str, value: int) -> bool:
        return field == "*" or value in {int(v) for v in field.split(",")}
    if not (matches(dom, day.day) and matches(month, day.month)
            and matches(dow, (day.weekday() + 1) % 7)):
        return []
    hours = range(24) if hour == "*" else [int(h) for h in hour.split(",")]
    minutes = range(60) if minute == "*" else [int(m) for m in minute.split(",")]
    base = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return [base + timedelta(hours=h, minutes=m) for h in hours for m in minutes]


def first_start_delays(starts: list[datetime], crons: list[str]
                       ) -> list[tuple[datetime, timedelta]]:
    """(the day's first slot, how long after it the day's first run started),
    newest day first, for a workflow whose ``crons`` fire on given days. A
    subscriber waits on the FIRST run of the day, measured against the FIRST
    slot: the Tuesday retry slot is a backup, never the time a report is due.
    A day with no slot (a manual run on a Thursday) is nobody's day."""
    by_day: dict = {}
    for at in starts:
        by_day.setdefault(at.date(), []).append(at)
    out = []
    for day in sorted(by_day, reverse=True):
        midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        fires = sorted(t for cron in crons for t in _cron_fires(cron, midnight))
        after = [at for at in by_day[day] if fires and at >= fires[0]]
        if after:
            out.append((fires[0], min(after) - fires[0]))
    return out


def _runs(workflow: str, per_page: int = 100) -> list[dict] | None:
    data = _gh_json(f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow}/runs?per_page={per_page}")
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        return None
    return [r for r in data["workflow_runs"]
            if r.get("event") in ("schedule", "workflow_dispatch") and r.get("created_at")]


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


LATE = timedelta(minutes=60)


def audit_cron_runs(runs: dict[str, list[dict]], now: datetime) -> dict[str, list[str]]:
    """How late the last two Tuesday and Saturday runs started against their
    slot, and how many runs the hourly-plus-daily intake actually got over
    the past week (GitHub's own scheduler dropped most hourly runs in Oct
    2026; the Worker now dispatches them)."""
    found: dict[str, list[str]] = {"late": [], "ok": [], "daily": []}
    for workflow in ("weekly.yml", "saturday.yml"):
        starts = [_when(r["created_at"]) for r in runs.get(workflow) or []]
        # The Worker's dispatch and GitHub's backup are two runs for one slot;
        # the earlier one is the one that mailed people.
        for slot, delay in first_start_delays(starts, workflow_crons(workflow))[:2]:
            line = f"{workflow} {slot:%a %b %d %H:%M}Z +{int(delay.total_seconds() // 60)} min"
            (found["late"] if delay > LATE else found["ok"]).append(line)
    daily = [r for r in runs.get("daily.yml") or []
             if now - _when(r["created_at"]) <= timedelta(days=7)]
    expected = 7 * 24 + 7
    found["daily"].append(f"{len(daily)} of about {expected} intake runs in 7 days")
    if len(daily) < 0.8 * expected:
        found["late"].append(found["daily"][0])
    return found


def check_cron_timing() -> list[Gate]:
    """GATE-12: did the last two Tuesday and Saturday runs start on time, and
    did the intake run every hour this past week. GitHub started the Tuesday
    runs 5-7 hours late on Oct 6 and 13 (OPS-01); the watchdog only alarms
    when a run never happened."""
    name = "The crons start on time (last two Tuesday and Saturday runs, a week of intake)"
    runs = {w: _runs(w) for w in ("weekly.yml", "saturday.yml", "daily.yml")}
    if any(v is None for v in runs.values()):
        return [Gate("Owner", name, "SKIP", "needs `gh` signed in to this repo (gh auth login)")]
    found = audit_cron_runs(runs, datetime.now(timezone.utc))
    if not found["ok"] and not found["late"]:
        return [Gate("Owner", name, "SKIP", "no scheduled run on record yet")]
    # A WARN while nothing is sold; a FAIL once checkout is open, because the
    # thanks page and the welcome promise the first report "usually within the
    # hour" and the Tuesday report on Tuesday morning (JOIN-161/169).
    landing = js_constants((SITE / "index.html").read_text(encoding="utf-8"))
    selling = landing.get("CHECKOUT_OPEN") == "true"
    return [_gate("Owner", name, not found["late"], "late: " + "; ".join(found["late"][:4])
                  + " — set the Worker's Cron Trigger (LAUNCH.md step 5.8)",
                  "; ".join(found["ok"][:4] + found["daily"]),
                  fail="FAIL" if selling else "WARN")]


# What GitHub calls the setting that makes an outside pull request wait for
# approval before its workflows run (Settings → Actions → General).
FORK_POLICY = "all_external_contributors"


def check_fork_approval() -> list[Gate]:
    """GATE-14: pull requests from outside collaborators need approval before
    their workflows run — the automation's cache holds subscribers' emails and
    rosters, and the repository is public."""
    name = "Outside pull requests need approval before their workflows run"
    data = _gh_json("repos/{owner}/{repo}/actions/permissions/fork-pr-contributor-approval")
    policy = data.get("approval_policy") if isinstance(data, dict) else None
    if policy == FORK_POLICY:
        return [Gate("Owner", name, "PASS", policy)]
    return [Gate("Owner", name, "OWNER",
                 (f"set to {policy!r}" if policy else "can't read it from here (gh signed out?)")
                 + " — Settings → Actions → General → Fork pull request workflows → "
                   "Require approval for all outside collaborators (LAUNCH.md step 3)")]


def _get_json(url: str, key: str) -> tuple[int, Any]:
    """GET ``url`` with a bearer key -> (HTTP status, JSON or None). Never
    raises, never echoes the key: a status of 0 means it could not connect."""
    import requests
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=20)
    except requests.RequestException:
        return 0, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


COUNTER_QUIET = timedelta(hours=48)


def counter_on_since() -> datetime | None:
    """When site/count.js's ENDPOINT line last changed in git — the counter's
    switch-on, once it is on. None when git can't say."""
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cI", "-G", r"const ENDPOINT = ",
                            "--", "site/count.js"], cwd=REPO, capture_output=True,
                           text=True, timeout=20)
        return datetime.fromisoformat(r.stdout.strip()) if r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def counter_gate(total: int | None, on_since: datetime | None, now: datetime,
                 why: str = "") -> Gate:
    """A Worker missing its COUNTS binding still answers 204 (C1: a silent
    no-op), so a counter that records nothing looks exactly like a quiet
    week. Two days on with nothing at all is the alarm."""
    name = "The page counter is recording"
    if total is None:
        return Gate("Owner", name, "SKIP", why)
    if total > 0:
        return Gate("Owner", name, "PASS", f"{total} lines in the last 2 days")
    if on_since is not None and now - on_since < COUNTER_QUIET:
        return Gate("Owner", name, "PASS", "switched on under 48 hours ago — nothing yet")
    return Gate("Owner", name, "WARN", "nothing recorded in 2 days with site/count.js on — "
                "check the form Worker's COUNTS binding (LAUNCH.md step 5b)")


def check_counter_account() -> list[Gate]:
    """Read-only: one SQL query with the Account Analytics Read token."""
    import requests
    from run.stats import CF_NAMES, COUNT_DATASET, ENV_FILE, read_env_file
    name = "The page counter is recording"
    if not counter_endpoint():
        return [Gate("Owner", name, "OWNER", "the counter is off (site/count.js has no "
                     "ENDPOINT) — LAUNCH.md step 5b")]
    found = read_env_file(ENV_FILE)
    account, token = (os.environ.get(n) or found.get(n, "") for n in CF_NAMES)
    if not (account and token):
        return [counter_gate(None, None, datetime.now(timezone.utc),
                             "needs CF_ACCOUNT_ID and CF_ANALYTICS_TOKEN (shell or .env)")]
    if not re.fullmatch(r"[0-9a-f]{32}", account):
        return [counter_gate(None, None, datetime.now(timezone.utc),
                             "CF_ACCOUNT_ID is not a 32-character account id")]
    sql = (f"SELECT SUM(_sample_interval) AS n FROM {COUNT_DATASET} "
           "WHERE timestamp > NOW() - INTERVAL '2' DAY FORMAT JSON")
    try:
        r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{account}/"
                          "analytics_engine/sql", data=sql.encode("utf-8"), timeout=20,
                          headers={"Authorization": f"Bearer {token}"})
        rows = r.json().get("data") if r.status_code == 200 else None
        total = int(float((rows[0] if rows else {}).get("n") or 0)) if isinstance(rows, list) \
            else None
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        total, r = None, None
    if total is None:
        status = getattr(r, "status_code", 0)
        return [counter_gate(None, None, datetime.now(timezone.utc),
                             f"couldn't read the counter (HTTP {status})")]
    return [counter_gate(total, counter_on_since(), datetime.now(timezone.utc))]


def check_resend_domain() -> list[Gate]:
    """GATE-13: Resend says the sending domain is verified. DNS records being
    present (check_dns) is not the same as Resend having checked them."""
    name = f"Resend has verified {DOMAIN}"
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        return [Gate("Email", name, "OWNER", "RESEND_API_KEY is not in this shell — verify the "
                                             "domain in Resend (LAUNCH.md step 2)")]
    status, body = _get_json("https://api.resend.com/domains", key)
    if status != 200 or not isinstance(body, dict):
        return [Gate("Email", name, "SKIP",
                     f"Resend answered HTTP {status} (a sending-only key can't list domains)")]
    rows = [d for d in body.get("data") or [] if isinstance(d, dict) and d.get("name") == DOMAIN]
    state = rows[0].get("status") if rows else None
    return [_gate("Email", name, state == "verified",
                  f"{DOMAIN} is {state or 'not added'} in Resend (LAUNCH.md step 2)", "verified",
                  fail="OWNER")]


STRIPE = "https://api.stripe.com/v1"


def audit_stripe_account(account: dict) -> list[str]:
    """What the buyer-facing business details would give away or leave out:
    receipts and the checkout page show them."""
    profile = account.get("business_profile") or {}
    problems = []
    if not str(profile.get("support_email") or "").endswith("@" + DOMAIN):
        problems.append(f"support email is {profile.get('support_email') or 'unset'}, not hello@{DOMAIN}")
    if profile.get("support_phone"):
        problems.append("a support phone number is public")
    address = profile.get("support_address") or {}
    if any(address.get(k) for k in ("line1", "line2", "postal_code")):
        problems.append("a support address is public (a rented mailbox only, never a home)")
    if re.search(PERSONAL_DOMAINS, str(profile.get("support_email") or ""), re.I):
        problems.append("the support email is a personal address")
    return problems


def check_stripe_account() -> list[Gate]:
    """GATE-15: Stripe's public details — what every receipt prints."""
    name = "Stripe's public details keep the owner anonymous"
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        return [Gate("Owner", name, "OWNER", "STRIPE_API_KEY is not in this shell — check "
                     "Settings → Business → Public details by hand (LAUNCH.md step 1.4)")]
    status, body = _get_json(f"{STRIPE}/account", key)
    if status != 200 or not isinstance(body, dict):
        return [Gate("Owner", name, "SKIP", f"Stripe answered HTTP {status} — this key can't "
                     "read the account; check Public details by hand (LAUNCH.md step 1.4)")]
    problems = audit_stripe_account(body)
    return [_gate("Owner", name, not problems, "; ".join(problems), "support email on the "
                  "domain, no phone, no address", fail="OWNER")]


def audit_portal(config: dict) -> list[str]:
    """What the buyer-facing promises need from Stripe's customer portal:
    cancel allowed, at the END of the period ("reports continue to the end of
    the period you've already paid for"), and no "why are you leaving?"
    question ("we do not ask why", JOIN-177)."""
    features = config.get("features") or {}
    cancel = features.get("subscription_cancel") or {}
    problems = []
    if not cancel.get("enabled"):
        problems.append("customers cannot cancel from the billing page")
    if cancel.get("mode") != "at_period_end":
        problems.append(f"cancellation mode is {cancel.get('mode') or 'unset'}, "
                        f"not 'at the end of the billing period'")
    if (cancel.get("cancellation_reason") or {}).get("enabled"):
        problems.append("the cancel page asks why (Cancellation reason is on) — "
                        "the thanks page promises we do not ask")
    if (cancel.get("proration_behavior") or "none") != "none":
        problems.append("cancelling prorates — a cancel must never raise a credit "
                        "or a charge")
    return problems


def check_billing_portal() -> list[Gate]:
    """The billing page's own settings, read from Stripe (needs a key that can
    read Billing → Customer portal)."""
    name = "Stripe's billing page cancels at period end and asks no reason"
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        return [Gate("Owner", name, "OWNER", "STRIPE_API_KEY is not in this shell — check "
                     "Settings → Billing → Customer portal by hand (LAUNCH.md step 1.4)")]
    status, body = _get_json(f"{STRIPE}/billing_portal/configurations?is_default=true&limit=1",
                             key)
    data = (body or {}).get("data") if isinstance(body, dict) else None
    if status != 200 or not data:
        return [Gate("Owner", name, "SKIP", f"Stripe answered HTTP {status} — this key "
                     "can't read the portal settings; check them by hand (LAUNCH.md step 1.4)")]
    problems = audit_portal(data[0])
    landing = js_constants((SITE / "index.html").read_text(encoding="utf-8"))
    selling = landing.get("CHECKOUT_OPEN") == "true"
    return [_gate("Owner", name, not problems, "; ".join(problems),
                  "cancel at period end, no reason asked",
                  fail="FAIL" if selling else "OWNER")]


REFUND_WARN = 0.10
DISPUTE_WARN = 0.0075


def audit_charge_rates(charges: list[dict]) -> tuple[int, float, float]:
    """(paid charges, refunded share, disputed share) over ``charges``."""
    paid = [c for c in charges if c.get("paid") and c.get("status") == "succeeded"]
    if not paid:
        return 0, 0.0, 0.0
    refunded = sum(1 for c in paid if c.get("refunded") or (c.get("amount_refunded") or 0) > 0)
    disputed = sum(1 for c in paid if c.get("disputed"))
    return len(paid), refunded / len(paid), disputed / len(paid)


def _stripe_charges(key: str, days: int) -> list[dict]:
    from run.stats import _stripe_list
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    return _stripe_list("charges", [("created[gte]", str(since))], key)


def check_refund_rates() -> list[Gate]:
    """GATE-16: refunds and disputes as a share of the last 30 days' charges.
    Card networks start watching an account near 0.75% disputes; a refund
    rate past 10% means the first reports are not landing."""
    name = "Refunds and disputes stay low (last 30 days)"
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        return [Gate("Economics", name, "SKIP", "needs STRIPE_API_KEY with Charges read")]
    try:
        n, refunds, disputes = audit_charge_rates(_stripe_charges(key, 30))
    except Exception as exc:  # noqa: BLE001 — a read failure is a SKIP, never a zero
        from run.stats import _safe
        return [Gate("Economics", name, "SKIP", f"couldn't read charges ({_safe(exc)})")]
    if not n:
        return [Gate("Economics", name, "SKIP", "no charge yet")]
    bad = ([f"refunds {refunds:.0%} (over {REFUND_WARN:.0%})"] if refunds > REFUND_WARN else []) \
        + ([f"disputes {disputes:.2%} (at or over {DISPUTE_WARN:.2%})"]
           if disputes >= DISPUTE_WARN else [])
    return [_gate("Economics", name, not bad, "; ".join(bad) + f" of {n} charges",
                  f"{n} charges: refunds {refunds:.0%}, disputes {disputes:.2%}", fail="WARN")]


def count_recipients(registry: Path | None = None) -> tuple[int, int] | str:
    """(paid subscribers on the registry, free reports waiting) — the people
    one Tuesday mails. A string is why it can't be counted here."""
    from run.rosters import RosterRegistryError, load_rosters
    from run.rosters import DEFAULT_ROSTERS
    path = registry or DEFAULT_ROSTERS
    if not path.is_file():
        return "no registry on this machine (it lives in the Actions cache)"
    try:
        subscribers = load_rosters(path)
    except RosterRegistryError as exc:
        return f"registry unreadable ({exc})"
    pending = 0
    endpoint = os.environ.get("FORM_ENDPOINT", "")
    if endpoint:
        try:
            from run.delivery import load_sent
            from run.intake import fetch_seats
            from run.solo import CACHE_DIR, current_season
            from run.trials import not_before, pending as pending_trials, season_start
            rows = fetch_seats(endpoint, os.environ.get("FORM_API_KEY"))
            season = current_season(CACHE_DIR)
            since = not_before(datetime.now(timezone.utc), season_start(CACHE_DIR, season))
            pending = len(pending_trials(rows, {s.email for s in subscribers}, load_sent(),
                                         season, since=since))
        except Exception:  # noqa: BLE001 — subscribers alone still answer the question
            pending = 0
    return len({s.email for s in subscribers}), pending


def check_volume() -> list[Gate]:
    """GATE-17: one Tuesday's recipients against the free email tier (100 a
    day, so about 85 subscribers once welcomes and first reports share the
    day), and four quarters of sales against the GST/HST small-supplier
    threshold. Not tax advice: the threshold is watched, not computed."""
    from run.economics import (GST_HST_THRESHOLD_CAD, RESEND_FREE_RECIPIENTS, USD_PER_CAD)
    gates = []
    counted = count_recipients()
    pro = os.environ.get("RESEND_PLAN", "").lower() == "pro"
    if isinstance(counted, str):
        gates.append(Gate("Economics", "One Tuesday fits the email plan", "SKIP", counted))
    else:
        subs, waiting = counted
        total = subs + waiting
        gates.append(_gate("Economics", "One Tuesday fits the email plan",
                           total <= RESEND_FREE_RECIPIENTS or pro,
                           f"{subs} subscribers + {waiting} free reports waiting = {total}, over "
                           f"the free tier's ~{RESEND_FREE_RECIPIENTS} — move to Resend Pro "
                           "($20/mo, PLAN §2) and set RESEND_PLAN=pro here",
                           f"{total} of ~{RESEND_FREE_RECIPIENTS}" + (" (Resend Pro)" if pro else ""),
                           fail="WARN"))
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        gates.append(Gate("Economics", "Sales stay under the GST/HST registration threshold",
                          "SKIP", "needs STRIPE_API_KEY with Charges read"))
        return gates
    try:
        charges = _stripe_charges(key, 365)
    except Exception as exc:  # noqa: BLE001
        from run.stats import _safe
        gates.append(Gate("Economics", "Sales stay under the GST/HST registration threshold",
                          "SKIP", f"couldn't read charges ({_safe(exc)})"))
        return gates
    gross_usd = sum(((c.get("amount") or 0) - (c.get("amount_refunded") or 0)) / 100
                    for c in charges if c.get("paid") and c.get("status") == "succeeded")
    gross_cad = gross_usd / USD_PER_CAD
    share = gross_cad / GST_HST_THRESHOLD_CAD
    status = "PASS" if share < 0.8 else "WARN" if share < 1 else "OWNER"
    gates.append(Gate("Economics", "Sales stay under the GST/HST registration threshold", status,
                      f"about C${gross_cad:,.0f} over the last 365 days of C$"
                      f"{GST_HST_THRESHOLD_CAD:,} ({share:.0%})"
                      + ("" if status == "PASS" else " — book the accountant question now")))
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
        ("season clock", check_week_json), ("the public record", check_record),
        ("this week's report", check_product),
        ("five league setups", check_product_battery),
        ("compliance text", check_compliance), ("every email's sender and way out",
                                                check_email_senders),
        ("owner secrets", check_secrets), ("bounce check key", check_resend_read_key),
        ("economics", check_economics),
        ("security.txt", check_security_txt),
    ]
    if not offline:
        steps += [("email DNS", check_dns), ("live site", check_live),
                  ("form Worker switches", check_worker_switches),
                  ("Resend domain", check_resend_domain), ("Stripe public details",
                                                           check_stripe_account),
                  ("Stripe billing page", check_billing_portal),
                  ("refunds and disputes", check_refund_rates), ("email volume and tax",
                                                                 check_volume),
                  ("cron timing", check_cron_timing), ("fork pull requests", check_fork_approval),
                  ("account and domain hardening", check_hardening),
                  ("page counter", check_counter_account)]
    if not fast:
        steps += [("browser", check_browser), ("email width", check_email_widths),
                  ("join flows", check_join_flows), ("accessibility", check_accessibility),
                  ("phone speed", check_speed), ("proving run", check_proving),
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
