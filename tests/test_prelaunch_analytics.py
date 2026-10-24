"""The site's own page counter, and the views the owner reads it through.

Pre-launch review, Oct 23 2026 (ANALYTICS-01..09, M2, BIZ-08, QA-04's
analytics half): nothing recorded a page view, a referrer or a funnel step,
`make stats` read "Active subscriptions: 0" for every 2026 buyer (2026 sells
one-time passes), and the privacy page promised "runs no analytics" — so the
counter, the privacy rewrite and the readers ship together. Pinned here:

- **site/count.js** (contract C1): six short fields, never a URL, a query, a
  cookie or storage; nothing under GPC, Do Not Track, an automated browser or
  any host but the live one; fire-and-forget, never throwing. Run under node
  against the real file.
- **Every page loads it** with one identical tag, and the join page calls it
  at exactly the four funnel steps.
- **The Worker contract**, once the Worker has its /e route: every line
  count.js can send is accepted and written as the same blobs.
- **`make stats`**: the TRAFFIC block (sampling, a hostile row dropped, the
  token masked), passes sold by type with the money and the refund rate,
  free report → paid within 14 days, seats against their cap, the
  subscription line labelled as 2027's, and never in CI.
- **The launch check**: the counter's address, its switch-on, the live site's
  cookies and edge injection, and the browser probe's hosts and storage.
- **The privacy page** describes exactly what count.js sends.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import run.launch_check as lc
import run.stats as stats

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
COUNT_JS = SITE / "count.js"
WORKER = ROOT / "infra" / "form-worker.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not available")
LIVE_URL = "https://forms.beatyourleague.com/e"
TAG = '<script src="/count.js" defer></script>'
FIELD = re.compile(r"^[a-z0-9.-]{0,40}$")
PAGE_KEYS = {"index", "join", "join-pass", "join-try", "league-pass", "how-it-works",
             "thanks", "sample", "this-week", "first-week", "404", "other"}
EVENTS = ("view", "roster", "checkout", "waitlist", "trial")
# The three generated pages this branch may not rebuild: the lead runs `make
# sample` after merging, and this-week.html is rebuilt by the Tuesday cron.
# Their generator carries COUNT_TAG (pinned below); DELETE THIS SET once they
# are rebuilt, so every page must carry the tag exactly once.
PENDING_REGENERATION = {"sample-report.html", "sample-first-week.html", "this-week.html"}
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


# --------------------------------------------------------------------- #
# count.js, run for real under node
# --------------------------------------------------------------------- #

HARNESS = r"""
import vm from "node:vm";
import fs from "node:fs";
const [file, scenariosFile] = process.argv.slice(2);
const original = fs.readFileSync(file, "utf8");
const scenarios = JSON.parse(fs.readFileSync(scenariosFile, "utf8"));
const out = [];
for (const sc of scenarios) {
  const src = sc.endpoint === null ? original
    : original.replace(/const ENDPOINT = "[^"]*";/, `const ENDPOINT = ${JSON.stringify(sc.endpoint)};`);
  const calls = [];
  const listeners = {};
  const u = new URL(sc.href);
  const nav = Object.assign({}, sc.nav || {});
  if (sc.beacon) nav.sendBeacon = (url, body) => { calls.push({ via: "beacon", url, body: String(body) }); return true; };
  const win = Object.assign({
    location: { hostname: u.hostname, pathname: u.pathname, search: u.search, protocol: u.protocol },
    navigator: nav, innerWidth: sc.width || 390, URL, URLSearchParams, JSON,
    addEventListener: (name, fn) => { listeners[name] = fn; },
  }, sc.win || {});
  if (sc.fetch !== "none") {
    win.fetch = (url, init) => {
      if (sc.fetch === "throw") throw new Error("boom");
      const { body, ...rest } = init || {};
      calls.push({ via: "fetch", url, init: rest, body });
      return sc.fetch === "reject" ? Promise.reject(new Error("offline")) : Promise.resolve({ ok: true });
    };
  }
  win.window = win;
  win.document = { referrer: sc.referrer || "", prerendering: !!sc.prerendering,
                   addEventListener: (name, fn) => { listeners["doc:" + name] = fn; } };
  let error = null;
  try {
    vm.runInNewContext(src, win);
    if (sc.pageshow !== false && listeners.pageshow) listeners.pageshow({ persisted: !!sc.persisted });
    if (sc.showPrerender && listeners["doc:prerenderingchange"]) listeners["doc:prerenderingchange"]();
    for (const [event, state] of sc.events || []) win.bylCount(event, state);
  } catch (err) { error = String(err); }
  await new Promise((r) => setTimeout(r, 0));
  out.push({ calls, error, api: typeof win.bylCount });
}
process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path: Path, scenarios: list[dict]) -> list[dict]:
    harness = tmp_path / "count_harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    spec = tmp_path / "scenarios.json"
    full = [{"endpoint": LIVE_URL, "fetch": "ok", **sc} for sc in scenarios]
    spec.write_text(json.dumps(full), encoding="utf-8")
    done = subprocess.run([NODE, str(harness), str(COUNT_JS), str(spec)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _bodies(result: dict) -> list[dict]:
    return [json.loads(call["body"]) for call in result["calls"]]


SEAT_URL = ("https://beatyourleague.com/join/?pass=0123456789abcdef0123&ref=s4-xyz"
            "&c=0123456789abcdef01234567&email=a@b.co&via=x")


@needs_node
def test_a_line_carries_six_short_fields_and_nothing_from_the_address(tmp_path) -> None:
    """Reproduction (ANALYTICS-02): the seat link carries the pass code, a roster
    ref, a confirm code and here an email; the referrer carries a query. The
    line must hold none of them — only {e,p,v,r,d,s}, each in the Worker's
    alphabet — and leave with no credentials and an origin-only Referer."""
    [result] = _run(tmp_path, [{"href": SEAT_URL, "referrer": "https://t.co/abc?email=a@b.co",
                                "events": [["checkout", "closed"]]}])
    assert result["error"] is None and result["api"] == "function"
    bodies = _bodies(result)
    assert [b["e"] for b in bodies] == ["view", "checkout"]
    for call, body in zip(result["calls"], bodies):
        assert set(body) == {"e", "p", "v", "r", "d", "s"}
        assert all(FIELD.fullmatch(v) for v in body.values()), body
        assert len(call["body"].encode()) <= 512
        assert call["url"] == LIVE_URL
        for secret in ("0123456789abcdef0123", "s4-xyz", "0123456789abcdef01234567",
                       "a@b.co", "abc", "email", "?"):
            assert secret not in call["body"], secret
        init = call["init"]
        assert init["method"] == "POST" and init["keepalive"] is True
        assert init["credentials"] == "omit" and init["referrerPolicy"] == "strict-origin"
        assert init["headers"] == {"Content-Type": "text/plain"}
    assert bodies[0] == {"e": "view", "p": "other", "v": "x", "r": "t.co", "d": "m", "s": ""}
    assert bodies[1]["s"] == "closed"


def _page_paths() -> list[tuple[str, str]]:
    """(published file, the URL path a visitor lands on) for every page."""
    out = []
    for page in sorted(SITE.rglob("*.html")):
        rel = str(page.relative_to(SITE))
        url = "/" + rel.replace("index.html", "")
        out.append((rel, url))
        if rel.endswith(".html") and not rel.endswith("index.html"):
            out.append((rel, "/" + rel[:-5]))            # GitHub Pages' extensionless form
    return out


@needs_node
def test_every_page_has_a_key_and_only_the_404_page_counts_as_404(tmp_path) -> None:
    """A page missing from count.js's lists would be counted as the 404 page
    (any unknown path IS GitHub Pages serving 404.html), so every published
    page, with and without .html, must land on a real key."""
    paths = _page_paths() + [("404.html", "/no/such/page"), ("404.html", "/Join/")]
    results = _run(tmp_path, [{"href": "https://beatyourleague.com" + url} for _f, url in paths])
    expected = {"index.html": "index", "join/index.html": "join",
                "league-pass.html": "league-pass", "how-it-works.html": "how-it-works",
                "thanks.html": "thanks", "sample-report.html": "sample",
                "this-week.html": "this-week", "sample-first-week.html": "first-week",
                "404.html": "404"}
    for (published, url), result in zip(paths, results):
        [body] = _bodies(result)
        assert body["p"] in PAGE_KEYS
        assert body["p"] == expected.get(published, "other"), (published, url, body["p"])


@needs_node
def test_the_join_page_modes_follow_the_join_pages_own_rules(tmp_path) -> None:
    base = "https://beatyourleague.com/join/"
    cases = {"": "join", "?try=1": "join-try", "?plan=pass": "join-pass",
             "?plan=pass&pass=1": "join-pass", "?pass=1": "other",
             "?pass=0123456789abcdef0123&s=ppr&n=12&t=std": "other",
             "?update=1&s=ppr&n=12&t=std&o=0123456789": "other",
             "?pass=1&try=1": "other", "?update=1&try=1": "other",
             "index.html?try=1&via=x": "join-try"}
    results = _run(tmp_path, [{"href": base + q} for q in cases])
    for (query, key), result in zip(cases.items(), results):
        assert _bodies(result)[0]["p"] == key, query


@needs_node
def test_nothing_is_sent_off_the_live_site_or_when_the_browser_asks_not(tmp_path) -> None:
    """Contract C1: live host only (a local preview, www, http and the launch
    check's copy count nothing), nothing under Global Privacy Control or Do
    Not Track in any of their spellings, nothing from an automated browser —
    and nothing at all while the committed ENDPOINT is still empty."""
    live = "https://beatyourleague.com/"
    quiet = [
        {"href": "http://127.0.0.1:9100/"}, {"href": "http://localhost/join/"},
        {"href": "https://www.beatyourleague.com/"}, {"href": "http://beatyourleague.com/"},
        {"href": "https://beatyourleague.com.evil.test/"},
        {"href": live, "nav": {"webdriver": True}},
        {"href": live, "nav": {"globalPrivacyControl": True}},
        {"href": live, "nav": {"doNotTrack": "1"}}, {"href": live, "nav": {"doNotTrack": "yes"}},
        {"href": live, "win": {"doNotTrack": "1"}}, {"href": live, "nav": {"msDoNotTrack": "1"}},
        {"href": live, "endpoint": ""},
        {"href": live, "events": [["purchase", "open"], ["view?x", ""]], "pageshow": False},
    ]
    for scenario, result in zip(quiet, _run(tmp_path, quiet)):
        assert result["error"] is None, scenario
        assert result["calls"] == [], scenario
    committed = re.findall(r'const ENDPOINT = "([^"]*)";', COUNT_JS.read_text(encoding="utf-8"))
    assert committed in ([""], [LIVE_URL]), \
        "count.js ENDPOINT is empty until LAUNCH.md step 5b, then exactly the forms. /e route"


@needs_node
def test_counting_never_throws_never_repeats_and_never_counts_a_restored_page(tmp_path) -> None:
    """Fire-and-forget: a fetch that throws or rejects, or a browser with no
    fetch, costs the page nothing. A back-forward-cache restore is the same
    view; a prerendered page counts once shown; a second press of a button in
    one visit is the same step."""
    live = "https://beatyourleague.com/join/"
    scenarios = [
        {"href": live, "fetch": "throw", "events": [["roster", "closed"]]},
        {"href": live, "fetch": "reject", "events": [["roster", "closed"]]},
        {"href": live, "fetch": "none"},
        {"href": live, "fetch": "none", "beacon": True},
        {"href": live, "persisted": True},
        {"href": live, "prerendering": True},
        {"href": live, "prerendering": True, "showPrerender": True},
        {"href": live, "events": [["roster", "open"], ["roster", "open"], ["checkout", "open"],
                                  ["checkout", "closed"], ["checkout", "open"]]},
    ]
    r = _run(tmp_path, scenarios)
    assert all(x["error"] is None for x in r)
    assert len(r[0]["calls"]) == 0 and len(r[1]["calls"]) == 2 and r[2]["calls"] == []
    assert [c["via"] for c in r[3]["calls"]] == ["beacon"]
    assert r[4]["calls"] == [] and r[5]["calls"] == []
    assert [b["e"] for b in _bodies(r[6])] == ["view"]
    assert [(b["e"], b["s"]) for b in _bodies(r[7])] == [
        ("view", ""), ("roster", "open"), ("checkout", "open"), ("checkout", "closed")]


@needs_node
def test_the_tag_and_the_referrer_are_cleaned_the_way_the_pages_clean_them(tmp_path) -> None:
    """The channel tag goes through the funnel pages' own sanitiser, so a
    channel counts under one name in the counter and in the form rows; our
    own site as referrer is a step inside the site and says so with our own
    bare host (the stats drop it, so "(direct or hidden)" counts arrivals); a
    host too long for the Worker's alphabet is blank rather than a dropped
    line."""
    long_host = "a" * 41 + ".example.com"
    scenarios = [
        {"href": "https://beatyourleague.com/?via=X_Post", "referrer": "https://www.reddit.com/r/ff"},
        {"href": "https://beatyourleague.com/join/", "referrer": "https://beatyourleague.com/"},
        {"href": "https://beatyourleague.com/join/", "referrer": "https://forms.beatyourleague.com/"},
        {"href": "https://beatyourleague.com/", "referrer": f"https://{long_host}/x", "width": 1280},
        {"href": "https://beatyourleague.com/?via=" + "a" * 60, "referrer": "not a url"},
    ]
    r = [_bodies(x)[0] for x in _run(tmp_path, scenarios)]
    assert (r[0]["v"], r[0]["r"]) == ("xpost", "www.reddit.com")
    assert r[1]["r"] == "beatyourleague.com" and r[2]["r"] == "beatyourleague.com"
    assert (r[3]["r"], r[3]["d"]) == ("", "d")
    assert r[4]["v"] == "a" * 24 and r[4]["r"] == ""
    funnel = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    page_rule = '.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 24)'
    assert page_rule in funnel and page_rule in COUNT_JS.read_text(encoding="utf-8")


def test_count_js_stores_nothing_and_fetches_only_its_endpoint() -> None:
    source = COUNT_JS.read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", source)
    assert not re.search(r"document\.cookie|localStorage|sessionStorage|indexedDB", code)
    # The query is read once, to pick the ?via= tag and the join mode out of it.
    rest = code.replace("new URLSearchParams(window.location.search)", "")
    assert not re.search(r"location\.(href|search|hash)|document\.URL|location\.toString", rest), \
        "the address itself must never be read into a line"
    assert code.count("fetch(ENDPOINT") == 1 and code.count("sendBeacon(ENDPOINT") == 1
    assert "workers.dev" not in code


# --------------------------------------------------------------------- #
# every page loads it; the join page calls it
# --------------------------------------------------------------------- #

def test_every_page_loads_the_counter_once_before_the_body_closes() -> None:
    """One identical tag, root-relative (the 404 page is served at any depth),
    deferred (it never blocks the first paint), right before </body>. No
    version digest on purpose: switching the counter on is then a one-line
    change to count.js, and GitHub Pages' 10-minute cache carries it."""
    for page in sorted(SITE.rglob("*.html")):
        rel = str(page.relative_to(SITE))
        text = page.read_text(encoding="utf-8")
        count = text.count("count.js")
        if rel in PENDING_REGENERATION and count == 0:
            continue
        assert count == 1 and text.count(TAG) == 1, f"{rel} loads count.js {count} times"
        assert text.index(TAG) < text.index("</body>")
        assert not text[text.index(TAG) + len(TAG):text.index("</body>")].strip(), \
            f"{rel}: the counter tag is not the last thing before </body>"


def test_the_join_page_counts_exactly_the_four_funnel_steps_where_they_happen() -> None:
    """Roster checked (after resolveAll on the button press), buy pressed with
    checkout closed (the branch the missing link takes), the redirect to Stripe
    when it is open, the waitlist row accepted, the free-report request
    accepted. Each guarded, so a blocked count.js changes nothing on the page.

    Reproduction (review routing): counted at the top of the submit handler,
    "open" fired on every press, including one the join page then stops to
    read the address back — so a buyer who left at the read-back, never
    reaching Stripe, still counted as a checkout."""
    join = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    calls = re.findall(r'if \(window\.bylCount\) window\.bylCount\("(\w+)"', join)
    assert sorted(calls) == ["checkout", "checkout", "roster", "trial", "waitlist"]
    assert "bylCount(" not in join.replace("if (window.bylCount) window.bylCount(", "")
    roster = join.index('window.bylCount("roster"')
    assert join.rindex('state.matches = R.resolveAll(state.directory, $("roster-text").value);',
                       0, roster) > roster - 200
    closed = join.index('window.bylCount("checkout", "closed")')
    assert 0 < closed - join.index("  if (!link) {") < 220
    assert join.index("const link = seasonOver()") < closed
    # Open is counted on the way out to Stripe, once per real redirect — not
    # once per press of a button that may stop at a read-back first.
    opened = join.index('window.bylCount("checkout", "open")')
    assert 0 < join.index("window.location.assign(", opened) - opened < 80
    assert join.count('window.bylCount("checkout"') == 2
    waitlist = join.index('window.bylCount("waitlist", "closed")')
    assert join.rindex("state.listed = true;", 0, waitlist) > waitlist - 120
    trial = join.index('window.bylCount("trial")')
    assert join.rindex('kind: "trial"', 0, trial) > join.index("function submitTrial(")
    assert join.rindex("if (!response.ok) throw await refusedFrom(response);", 0, trial) > trial - 80


def test_the_generated_public_pages_carry_the_counter_and_a_subscribers_report_never() -> None:
    """Reproduction (review, ANALYTICS-02 item 2): `grep -c count.js` gave 0
    for sample-report, sample-first-week, this-week, backtest and the ledger,
    so the landing's main proof link — "See a real report", the one phone-nav
    link — landed on pages never counted, and `make stats` read the proof as
    unvisited. The generators now carry COUNT_TAG, gated like the share meta:
    on the public renders, never on a subscriber's own report."""
    import render.report as rr
    from render.backtest_site import build as backtest_page
    from render.ledger_site import render_ledger
    from render.live_sample import VIA_SCRIPT, with_via_carry
    from test_email import _solo_report

    assert rr.COUNT_TAG == TAG
    template = rr.TEMPLATE_PATH.read_text(encoding="utf-8")

    def closes_with_counter(page: str) -> None:
        assert page.count("count.js") == 1 and page.count(TAG) == 1
        assert not page[page.index(TAG) + len(TAG):page.index("</body>")].strip()

    private = _solo_report()
    for key in ("anonymized_demo", "historical_demo", "live_demo", "first_week_demo"):
        private["meta"].pop(key, None)
    assert "count.js" not in rr.render(private, template), \
        "a subscriber's private report is nobody's page view"
    public = _solo_report()
    public["meta"]["anonymized_demo"] = True
    page = rr.render(public, template)
    closes_with_counter(page)
    # Both samples and the live sample go through with_via_carry: the ?via=
    # carry stays inside the body and the counter stays last.
    carried = with_via_carry(page)
    closes_with_counter(carried)
    assert carried.index(VIA_SCRIPT) < carried.index(TAG)
    assert rr.with_counter(carried) == carried, "never twice"
    closes_with_counter(backtest_page())
    closes_with_counter(render_ledger([], {}, generated_at="2026-10-23 00:00 UTC"))


@needs_node
def test_a_restored_league_pass_roster_counts_as_the_pass_page(tmp_path) -> None:
    """Reproduction (review): the launch email's ?ref= of a League Pass roster,
    with no ?plan=pass, makes the join page WANTS_PASS through RESTORED_PLAN,
    while count.js read only ?plan= and counted the visit as "join". The join
    page now names its own mode in window.bylPage, from the flags it runs on;
    count.js takes it only on the join page and only if it is a join key."""
    restored = "https://beatyourleague.com/join/?ref=p4-abc&via=x"
    scenarios = [
        {"href": restored, "win": {"bylPage": "join-pass"}},
        {"href": restored},                                   # an older join page
        {"href": restored, "win": {"bylPage": "index"}},      # not a join key
        {"href": restored, "win": {"bylPage": "a@b.co"}},
        {"href": "https://beatyourleague.com/how-it-works", "win": {"bylPage": "join-pass"}},
        {"href": "https://beatyourleague.com/join/?pass=1", "win": {"bylPage": "other"}},
    ]
    keys = [_bodies(r)[0]["p"] for r in _run(tmp_path, scenarios)]
    assert keys == ["join-pass", "join", "join", "join", "how-it-works", "other"]
    join = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    assignment = re.search(r"window\.bylPage = SEAT_MODE \|\| UPDATE_MODE \? \"other\" : "
                           r"TRY_MODE \? \"join-try\"\s+: WANTS_PASS \? \"join-pass\" : \"join\";",
                           join)
    assert assignment, "the join page names its counter key from its own mode flags"
    assert join.index("const TRY_MODE =") < assignment.start()
    assert join.index("const WANTS_PASS =") < assignment.start()


# --------------------------------------------------------------------- #
# the Worker contract (live once infra/form-worker.js has its /e route)
# --------------------------------------------------------------------- #

def _worker_counts() -> bool:
    return WORKER.is_file() and "COUNTS" in WORKER.read_text(encoding="utf-8")


@needs_node
@pytest.mark.skipif(not _worker_counts(), reason="the form Worker has no /e route yet "
                    "(the WORKER build adds it; this test then pins the contract)")
def test_every_line_count_js_sends_is_one_the_worker_writes_as_is(tmp_path) -> None:
    """Contract C1 end to end: the bodies count.js really produces, POSTed as
    a browser on our site posts them, each come back 204 with no cookie and
    become exactly one data point whose first six blobs are the line."""
    scenarios = [{"href": f"https://beatyourleague.com{url}", "referrer": "https://t.co/x",
                  "events": [[e, "closed"] for e in EVENTS[1:]]}
                 for url in ("/", "/join/", "/join/?try=1", "/join/?plan=pass", "/thanks.html",
                             "/sample-report.html", "/nope")]
    lines = [call["body"] for r in _run(tmp_path, scenarios) for call in r["calls"]]
    (tmp_path / "worker.mjs").write_text(WORKER.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "lines.json").write_text(json.dumps(lines), encoding="utf-8")
    (tmp_path / "w.mjs").write_text(r"""
import worker from "./worker.mjs";
import fs from "node:fs";
console.log = () => {};
const lines = JSON.parse(fs.readFileSync("lines.json", "utf8"));
const points = []; const puts = [];
const env = { SITE_ORIGIN: "https://beatyourleague.com",
  COUNTS: { writeDataPoint: (p) => points.push(p) },
  ROWS: { put: async (...a) => puts.push(a), get: async () => null,
          list: async () => ({ keys: [], list_complete: true }) } };
const out = [];
for (const body of lines) {
  const before = points.length;
  const res = await worker.fetch(new Request("https://forms.beatyourleague.com/e", {
    method: "POST", body, headers: { "Content-Type": "text/plain",
                                     "Origin": "https://beatyourleague.com" } }),
    env, { waitUntil: () => {} });
  out.push({ status: res.status, cookie: res.headers.get("set-cookie"),
             point: points.slice(before) });
}
process.stdout.write(JSON.stringify({ out, puts: puts.length }));
""", encoding="utf-8")
    done = subprocess.run([NODE, "w.mjs"], cwd=tmp_path, capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["puts"] == 0, "the counter must never write KV"
    for body, got in zip(lines, result["out"]):
        line = json.loads(body)
        assert got["status"] == 204 and got["cookie"] is None
        assert len(got["point"]) == 1, (line, got)
        blobs = got["point"][0]["blobs"]
        assert blobs[:6] == [line[k] for k in "epvrds"], (line, blobs)


# --------------------------------------------------------------------- #
# make stats — traffic
# --------------------------------------------------------------------- #

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


ACCOUNT = "0123456789abcdef0123456789abcdef"
ROWS_7 = [
    {"e": "view", "p": "index", "v": "x", "r": "t.co", "d": "m", "s": "", "c": "US", "n": "120"},
    {"e": "view", "p": "index", "v": "", "r": "", "d": "d", "s": "", "c": "CA", "n": 30.0},
    {"e": "view", "p": "join", "v": "x", "r": "", "d": "m", "s": "", "c": "US", "n": 40},
    {"e": "roster", "p": "join", "v": "x", "r": "", "d": "m", "s": "closed", "c": "US", "n": 18},
    {"e": "checkout", "p": "join", "v": "x", "r": "", "d": "m", "s": "closed", "c": "US", "n": 7},
    {"e": "view", "p": "join-try", "v": "", "r": "", "d": "m", "s": "", "c": "US", "n": 5},
    {"e": "trial", "p": "join-try", "v": "", "r": "", "d": "m", "s": "", "c": "US", "n": 2},
    # hostile: an address, markup, an unknown event, a lower-case country
    {"e": "view", "p": "index", "v": "a@b.co", "r": "", "d": "m", "s": "", "c": "US", "n": 999},
    {"e": "view", "p": "index", "v": "", "r": "<script>", "d": "m", "s": "", "c": "US", "n": 999},
    {"e": "purchase", "p": "index", "v": "", "r": "", "d": "m", "s": "", "c": "US", "n": 999},
    {"e": "view", "p": "index", "v": "", "r": "", "d": "m", "s": "", "c": "us", "n": 999},
]


def _fake_cf(monkeypatch, week=ROWS_7, month=None, fail: Exception | None = None):
    seen = []

    def urlopen(request, timeout=0):
        seen.append(request)
        if fail is not None:
            raise fail
        days = re.search(r"INTERVAL '(\d+)' DAY", request.data.decode()).group(1)
        data = week if days == "7" else (month if month is not None else week)
        return _Resp(json.dumps({"meta": [], "data": data}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return seen


def test_the_traffic_block_reads_the_sampled_counts_and_drops_a_hostile_row(monkeypatch) -> None:
    """ANALYTICS-03, reproduced with the reviewer's planted rows: an address
    in the via field and markup in the referrer (n=999 each) never print and
    never count; counts are SUM(_sample_interval); the one token is a header."""
    seen = _fake_cf(monkeypatch)
    lines = stats.traffic_summary(ACCOUNT, "tok-SECRET", LIVE_URL)
    text = "\n".join(lines)
    assert "a@b.co" not in text and "<script>" not in text and "999" not in text
    assert "1,0" not in text
    row = {label.strip(): line for line in lines for label, _t in stats.FUNNEL
           if line.strip().startswith(label)}
    assert row["Landing views"].split()[-2:] == ["150", "150"]
    assert row["Buy-page views"].split()[-2:] == ["40", "40"]
    assert row["Rosters checked on the buy page"].split()[-2:] == ["18", "18"]
    assert row["Buy pressed, checkout closed"].split()[-2:] == ["7", "7"]
    assert row["Free reports requested"].split()[-2:] == ["2", "2"]
    assert "x 160 → 18 → 7, (no tag) 30 → 0 → 0" in text
    assert "phone 165, desktop 30" in text and "US 165, CA 30" in text
    assert "never of people" in text
    assert len(seen) == 2
    for request in seen:
        sql = request.data.decode()
        assert "SUM(_sample_interval)" in sql and "FROM byl_counts" in sql
        assert request.full_url == stats.AE_SQL.format(account=ACCOUNT)
        assert request.get_header("Authorization") == "Bearer tok-SECRET"
        assert "tok-SECRET" not in request.full_url


def test_the_traffic_block_fails_soft_and_never_prints_the_token(monkeypatch) -> None:
    _fake_cf(monkeypatch, fail=OSError("HTTP 403 Bearer tok-SECRET denied for tok-SECRET"))
    [line] = stats.traffic_summary(ACCOUNT, "tok-SECRET", LIVE_URL)
    assert "Could not read the counter" in line and "tok-SECRET" not in line
    seen = _fake_cf(monkeypatch)
    [line] = stats.traffic_summary("not-an-account/../x", "tok", LIVE_URL)
    assert "32-character" in line and not seen, "a malformed account id never reaches a URL"
    assert stats.traffic_summary("", "", LIVE_URL)[0].startswith("  CF_ACCOUNT_ID")
    assert "counter is off" in stats.traffic_summary(ACCOUNT, "tok", "")[0] and not seen


def test_a_counter_that_is_on_and_returns_nothing_says_to_check_the_binding(monkeypatch) -> None:
    """The Worker answers 204 whether or not COUNTS is bound (C1), so an
    unbound Worker reads exactly like a quiet week unless this says so."""
    _fake_cf(monkeypatch, week=[], month=[])
    lines = stats.traffic_summary(ACCOUNT, "tok", LIVE_URL)
    assert "COUNTS binding" in lines[0]


def test_the_funnel_reads_every_event_count_js_can_send() -> None:
    source = COUNT_JS.read_text(encoding="utf-8")
    events = re.search(r"const EVENTS = \[([^\]]*)\]", source).group(1)
    assert tuple(re.findall(r'"(\w+)"', events)) == stats.COUNT_EVENTS == EVENTS
    funnel_events = {e for _l, test in stats.FUNNEL for e in EVENTS
                     if any(test({"e": e, "p": p, "s": s, "v": "", "r": "", "d": "", "c": ""})
                            for p in PAGE_KEYS for s in ("", "open", "closed"))}
    assert funnel_events == set(EVENTS)


def test_the_referrer_line_counts_arrivals_not_steps_inside_the_site() -> None:
    """Reproduction (review): count.js blanked our own host, so every step
    inside the site had r="" — index r=t.co n=100, join n=60 and how-it-works
    n=30, every visitor having come from t.co, printed "t.co 100, (direct or
    hidden) 90". Steps inside the site now carry our own host and the line
    leaves them out; a real direct arrival still counts as direct."""
    rows = [
        {"e": "view", "p": "index", "v": "", "r": "t.co", "d": "m", "s": "", "c": "US", "n": 100},
        {"e": "view", "p": "join", "v": "", "r": "beatyourleague.com", "d": "m", "s": "",
         "c": "US", "n": 60},
        {"e": "view", "p": "how-it-works", "v": "", "r": "beatyourleague.com", "d": "m",
         "s": "", "c": "US", "n": 30},
    ]
    [line] = [x for x in stats.traffic_lines(rows, rows) if "Referrers" in x]
    assert "t.co 100" in line and "direct or hidden" not in line.split("(steps")[0]
    assert "beatyourleague.com" not in line.replace("steps inside the site", "")
    direct = rows + [{"e": "view", "p": "index", "v": "", "r": "", "d": "d", "s": "",
                      "c": "CA", "n": 12}]
    [line] = [x for x in stats.traffic_lines(direct, direct) if "Referrers" in x]
    assert "t.co 100, (direct or hidden) 12" in line
    # Every page view still counts on the pages line.
    [pages] = [x for x in stats.traffic_lines(rows, rows) if "Pages, 7 days" in x]
    assert "join 60" in pages and "how-it-works 30" in pages


def test_the_waitlist_row_says_it_is_the_buy_pages_save_only() -> None:
    """Reproduction (review): only the join page's closed-checkout save calls
    bylCount("waitlist"); the landing hero's capture — the main waitlist path
    — is never counted, so a row labelled "Waitlist joined" undercounted
    badly beside the FORMS block's real total. The row names what it counts."""
    labels = [label for label, _t in stats.FUNNEL]
    assert "Waitlist joined" not in labels
    assert "Waitlist joined on the buy page" in labels
    landing = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'bylCount("waitlist"' not in landing, \
        "the landing counts its capture now: relabel the row back to the whole waitlist"


# --------------------------------------------------------------------- #
# make stats — passes, money, free → paid, seats
# --------------------------------------------------------------------- #

def _ref(via: str = "") -> str:
    from run.refs import encode_roster
    from test_solo_run import SLOTS, _pid
    ref = encode_roster("season", "ppr", list(SLOTS), [_pid(i) for i in range(1, 9)])
    return ref + (f"_via-{via}" if via else "")


SEASON_START = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())


def _session(i, amount, *, link="plink_season", refunded=0, mode="payment", paid="paid",
             ref=None, created=None, email=None, subtotal=None):
    return {"id": f"cs_{i}", "mode": mode, "status": "complete", "payment_status": paid,
            "client_reference_id": _ref() if ref is None else ref, "payment_link": link,
            "amount_total": amount, "amount_subtotal": subtotal if subtotal else amount,
            "currency": "usd",
            "created": created or int(NOW.timestamp()) - i * 3600,
            "customer_details": {"email": email or f"buyer{i}@example.com"},
            "payment_intent": {"id": f"pi_{i}", "latest_charge": {
                "amount": amount, "amount_refunded": refunded, "refunded": refunded >= amount}}}


SESSIONS = [
    _session(1, 2900), _session(2, 2900, refunded=2900),
    _session(3, 1900),                                       # the Playoff Pass, same plan
    _session(4, 6900, link="plink_pass"),
    _session(5, 2320, subtotal=2900),                        # a discount: still Rest-of-Season
    _session(6, 2900, refunded=1000),                        # partly refunded
    _session(7, 3900, mode="subscription"),                  # 2027's plans, not a pass
    _session(8, 2900, paid="unpaid"),
    _session(9, 2900, ref="s-123456-789012-345678"),         # Sleeper era
    _session(10, 2900, created=SEASON_START - 86400),        # last season
]
LINKS = {"plink_season": "season", "plink_pass": "league_pass"}


def test_passes_are_counted_by_type_with_the_money_and_the_refund_rate() -> None:
    """BIZ-08, reproduced: `make stats` printed "Active subscriptions: 0" for
    every 2026 buyer — the passes are payment-mode sessions — and had no
    revenue, pass-type split or refund rate. The $29 and $19 links share the
    season plan, so price before discount tells them apart; the League Pass is
    the link map's. A subscription, an unpaid or Sleeper-era session, and last
    season's sale are not this season's passes."""
    from run.economics import stripe_fee
    lines = stats.passes_lines(SESSIONS, LINKS, "2026 season", SEASON_START)
    assert lines[0] == "  Passes sold, 2026 season: 6 — Rest-of-Season 4, Playoff 1, League Pass 1"
    gross = (2900 * 3 + 2320 + 1900 + 6900) / 100
    refunded = (2900 + 1000) / 100
    fees = sum(stripe_fee(a / 100, one_time=True) for a in (2900, 2900, 1900, 6900, 2320, 2900))
    assert lines[1] == (f"  Money: ${gross:,.2f} gross, ${refunded:,.2f} refunded, "
                        f"${gross - refunded - fees:,.2f} net of Stripe's fee (modelled)")
    assert lines[2] == "  Refund rate: 17% (1 of 6 refunded in full)"
    assert stats.passes_lines([], LINKS, "2026 season", None) == [
        "  Passes sold, 2026 season: none yet"]
    assert "@" not in "\n".join(lines)


def test_free_report_to_paid_is_counted_inside_fourteen_days_only() -> None:
    """Joined on the mailbox the way the free report counts people; a buyer
    after day 14 is not a conversion; a request younger than 14 days is
    counted apart rather than as a miss."""
    asked = NOW - timedelta(days=20)
    rows = [{"kind": "trial", "email": "Fan.One+ff@gmail.com", "received_at": asked.isoformat()},
            {"kind": "trial", "email": "two@example.com", "received_at": asked.isoformat()},
            {"kind": "trial", "email": "three@example.com",
             "received_at": (NOW - timedelta(days=3)).isoformat()},
            {"kind": "waitlist", "email": "four@example.com", "received_at": asked.isoformat()}]
    sessions = [
        _session(1, 2900, email="fanone@gmail.com",
                 created=int((asked + timedelta(days=4)).timestamp())),
        _session(2, 2900, email="two@example.com",
                 created=int((asked + timedelta(days=16)).timestamp())),
        _session(3, 2900, email="four@example.com",
                 created=int((asked + timedelta(days=1)).timestamp()))]
    line = stats.free_to_paid_line(rows, sessions, NOW)
    assert line == ("  Free report → paid within 14 days: 1 of 2 "
                    "(1 asked under 14 days ago, not counted yet)")
    assert "@" not in line


def test_seats_are_counted_against_each_pass_cap() -> None:
    from run.rosters import RosterSubscriber
    from run.refs import LEAGUE_PASS

    def row(email, **kw):
        return RosterSubscriber(email=email, ref=_ref(), player_ids=(), slots=(),
                                scoring="ppr", **kw)
    registry = [row("payer1@example.com", league_size=12, billing="pass", pass_id="pi_a"),
                row("payer2@example.com", league_size=10, billing="pass", pass_id="pi_b"),
                *[row(f"s{i}@example.com", plan=LEAGUE_PASS, covered_by="payer1@example.com",
                      pass_id="pi_a") for i in range(3)],
                row("lost@example.com", plan=LEAGUE_PASS, covered_by="x@example.com",
                    pass_id="pi_z"),
                row("solo@example.com", league_size=12, billing="season")]
    assert stats.seat_lines(registry) == [
        "  League Pass seats: 2 pass(es) — 3 of 12, 0 of 10 claimed; "
        "1 seat(s) on a pass whose payer row isn't here"]
    assert stats.seat_lines([row("solo@example.com", billing="season")]) == []


def test_the_subscription_line_is_labelled_as_2027s_while_passes_are_sold(monkeypatch) -> None:
    import run.subscriptions as subscriptions
    from test_stats import _FakeStripe
    monkeypatch.setattr(subscriptions, "_stripe_get", _FakeStripe())
    on = stats.stripe_summary("rk_test_x", NOW, one_time=True)
    off = stats.stripe_summary("rk_test_x", NOW, one_time=False)
    assert any(l.startswith(f"  {stats.SUBSCRIPTIONS_LABEL_ONE_TIME}: 4") for l in on)
    assert not any(l.startswith("  Active subscriptions") for l in on)
    assert any(l.startswith("  Active subscriptions: 4") for l in off)
    from render.report import SELLING_ONE_TIME
    assert stats.stripe_summary("rk_test_x", NOW) == (on if SELLING_ONE_TIME else off)


def test_the_passes_read_asks_stripe_for_the_charge_and_feeds_free_to_paid(monkeypatch) -> None:
    import run.subscriptions as subscriptions
    from urllib.parse import parse_qs, urlsplit
    from test_stats import _FakeStripe
    fake = _FakeStripe(shapes={"checkout/sessions": {"data": SESSIONS, "has_more": False}})
    monkeypatch.setattr(subscriptions, "_stripe_get", fake)
    rows = [{"kind": "trial", "email": "buyer3@example.com",
             "received_at": (NOW - timedelta(days=14, hours=2)).isoformat()}]
    lines = stats.stripe_summary("rk_test_x", NOW, rows=rows, link_plans=LINKS,
                                 season_label="2026 season", since=SEASON_START)
    assert lines[0].startswith("  Passes sold, 2026 season: 6")
    assert "  Free report → paid within 14 days: 1 of 1" in lines
    expands = [parse_qs(urlsplit(u).query).get("expand[]") for u in fake.urls]
    assert ["data.payment_intent.latest_charge"] in expands
    assert "@" not in "\n".join(lines)


# --------------------------------------------------------------------- #
# make stats — never in CI, credentials, the page copy
# --------------------------------------------------------------------- #

def test_stats_refuses_to_run_in_ci_and_no_workflow_runs_it(capsys) -> None:
    """The repository is public, so a job log or summary of `make stats`
    would publish sales and traffic (BIZ-08). The command refuses under
    GitHub Actions, and no workflow asks it to."""
    for environ in ({"GITHUB_ACTIONS": "true"}, {"CI": "1"}):
        assert stats.cli([], environ=environ, env_file=Path("/nonexistent")) == 2
    out = capsys.readouterr()
    assert out.out == "" and "does not run in CI" in out.err
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert not re.search(r"run\.stats|make\s+stats", text), workflow.name


def test_the_counter_credentials_come_from_the_shell_or_dot_env_and_only_via_the_cli(
        tmp_path, monkeypatch) -> None:
    """main() never reads CF credentials itself, so a test (or any caller)
    cannot reach Cloudflare by accident; the command line reads the shell,
    then the gitignored .env — only the two counter names, nothing executed."""
    env = tmp_path / ".env"
    env.write_text("# local\nexport CF_ACCOUNT_ID=\"%s\"\nCF_ANALYTICS_TOKEN='from-file'\n"
                   "STRIPE_API_KEY=sk_live_should_not_be_read\nCF_OTHER=$(rm -rf /)\n" % ACCOUNT,
                   encoding="utf-8")
    assert stats.read_env_file(env) == {"CF_ACCOUNT_ID": ACCOUNT,
                                        "CF_ANALYTICS_TOKEN": "from-file"}
    handed = {}
    monkeypatch.setattr(stats, "main", lambda argv=None, cf=None: handed.update(cf) or 0)
    assert stats.cli([], environ={"CF_ANALYTICS_TOKEN": "from-shell"}, env_file=env) == 0
    assert handed == {"CF_ACCOUNT_ID": ACCOUNT, "CF_ANALYTICS_TOKEN": "from-shell"}


def test_main_never_reaches_cloudflare_without_being_handed_credentials(
        tmp_path, monkeypatch, capsys) -> None:
    import run.delivery as delivery
    seen = _fake_cf(monkeypatch)
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.setenv("CF_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CF_ANALYTICS_TOKEN", "tok")
    counter = tmp_path / "count.js"
    counter.write_text(f'  const ENDPOINT = "{LIVE_URL}";\n', encoding="utf-8")
    monkeypatch.setattr(stats, "COUNT_JS", counter)
    assert stats.main(["--registry", str(tmp_path / "none.json"), "--now", NOW.isoformat()]) == 0
    out = capsys.readouterr().out
    assert not seen and out.index("TRAFFIC") < out.index("FORMS")
    assert "CF_ACCOUNT_ID / CF_ANALYTICS_TOKEN are not set" in out


def test_the_html_copy_goes_only_to_a_gitignored_path(tmp_path, monkeypatch, capsys) -> None:
    import run.delivery as delivery
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    args = ["--registry", str(tmp_path / "none.json"), "--now", NOW.isoformat()]
    if shutil.which("git"):
        assert stats._gitignored(ROOT / "data" / "stats.html")
        assert not stats._gitignored(SITE / "stats.html")
        assert stats.main(args + ["--html", str(SITE / "stats.html")]) == 2
        assert not (SITE / "stats.html").exists()
    monkeypatch.setattr(stats, "_gitignored", lambda path: True)
    page = tmp_path / "stats.html"
    assert stats.main(args + ["--html", str(page)]) == 0
    html = page.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>") and 'name="robots" content="noindex"' in html
    assert "TRAFFIC" in html and "<script" not in html
    assert "&lt;" in stats.html_page("<b>") and "<b>" not in stats.html_page("<b>")


# --------------------------------------------------------------------- #
# the launch check
# --------------------------------------------------------------------- #

@pytest.fixture
def site(tmp_path, monkeypatch):
    copy = tmp_path / "site"
    shutil.copytree(SITE, copy)
    monkeypatch.setattr(lc, "SITE", copy)
    return copy


def _gate(gates, part):
    hits = [g for g in gates if part.lower() in g.name.lower()]
    assert hits, [g.name for g in gates]
    return hits[0]


def _set(path: Path, name: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(rf'const {name} = "[^"]*";', f'const {name} = "{value}";', text)
    assert n == 1, name
    path.write_text(new, encoding="utf-8")


def test_the_counter_must_post_to_the_forms_e_route_and_switch_on_with_the_worker(site) -> None:
    """ANALYTICS-06: the counter on a *.workers.dev address is blocked as a
    third-party beacon and is not the address privacy section 3 names, so it
    FAILs; the Worker live with the counter still off is owner setup."""
    gates = lc.check_funnel_config()
    assert _gate(gates, "page counter posts").status == "PASS"
    assert _gate(gates, "page counter is on once").status == "PASS"
    _set(site / "count.js", "ENDPOINT", "https://byl-forms.someone.workers.dev/e")
    gates = lc.check_funnel_config()
    assert _gate(gates, "page counter posts").status == "FAIL"
    assert _gate(gates, "form Worker sits on our own domain").status == "WARN"
    _set(site / "count.js", "ENDPOINT", "")
    _set(site / "join" / "index.html", "FORM_ENDPOINT", "https://forms.beatyourleague.com")
    assert _gate(lc.check_funnel_config(), "page counter is on once").status == "OWNER"
    _set(site / "count.js", "ENDPOINT", LIVE_URL)
    gates = lc.check_funnel_config()
    assert _gate(gates, "page counter posts").status == "PASS"
    assert _gate(gates, "page counter is on once").status == "PASS"


def _response(status=200, headers=None, text="<html><body>ok</body></html>"):
    base = {"content-type": "text/html; charset=utf-8"}
    return SimpleNamespace(status_code=status, text=text,
                           headers={**base, **(headers or {})})


def test_the_live_gate_catches_a_cookie_or_an_edge_injection() -> None:
    """Edge features change the served HTML after the repo (ANALYTICS-06/09):
    Web Analytics' automatic setup, Rocket Loader, Email Obfuscation, a bot
    product's cookie. Each falsifies privacy section 3 without a commit."""
    clean = [("", _response()), ("og.png", _response(headers={"content-type": "image/png"},
                                                   text="cloudflareinsights"))]
    assert lc.audit_live_responses(clean) == []
    for bad in (_response(headers={"set-cookie": "__cf_bm=abc; path=/"}),
                _response(text='<script src="https://static.cloudflareinsights.com/beacon.min.js">'),
                _response(text='<script src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/'
                               'email-decode.min.js"></script>'),
                _response(text="<script>zaraz.track()</script>")):
        assert lc.audit_live_responses([("x.html", bad)]), bad
    ok = _response(204, {"access-control-allow-origin": "https://beatyourleague.com"}, "")
    assert lc.audit_counter_response(ok) == []
    assert lc.audit_counter_response(_response(204, {
        "access-control-allow-origin": "https://beatyourleague.com",
        "set-cookie": "__cf_bm=x"}, ""))
    assert lc.audit_counter_response(_response(500, {}, ""))


def test_a_counter_that_records_nothing_for_two_days_is_a_warning() -> None:
    """A Worker missing its COUNTS binding still answers 204 (C1)."""
    on = NOW - timedelta(hours=72)
    assert lc.counter_gate(0, on, NOW).status == "WARN"
    assert lc.counter_gate(0, None, NOW).status == "WARN"
    assert lc.counter_gate(0, NOW - timedelta(hours=3), NOW).status == "PASS"
    assert lc.counter_gate(12, on, NOW).status == "PASS"
    assert lc.counter_gate(None, None, NOW, "no token").status == "SKIP"


def test_the_account_gate_is_owner_setup_while_the_counter_is_off(site, monkeypatch) -> None:
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("no query while off"))
    assert lc.check_counter_account()[0].status == "OWNER"


def test_the_probe_audit_names_foreign_hosts_cookies_and_storage() -> None:
    results = [{"path": "index.html", "width": 390, "hosts": ["127.0.0.1:9", "forms.beatyourleague.com"],
                "cookies": [], "storage": [0, 0]},
               {"path": "join/index.html", "width": 390,
                "hosts": ["127.0.0.1:9", "static.cloudflareinsights.com"],
                "cookies": ["_ga (.beatyourleague.com)"], "storage": [0, 1]}]
    hosts, kept = lc.audit_privacy_probe(results, "127.0.0.1:9")
    assert hosts == ["join/index.html @390: static.cloudflareinsights.com"]
    assert len(kept) == 2 and "_ga" in kept[0] and "[0, 1]" in kept[1]


@pytest.mark.skipif(lc._browser_tools() is None, reason="needs Chrome and node")
def test_the_browser_probe_really_sees_hosts_cookies_and_storage(tmp_path) -> None:
    """Mutation check of the probe itself: a page that loads from another
    host, sets a cookie and writes localStorage is caught; a clean page is not."""
    (tmp_path / "bad.html").write_text(
        '<!doctype html><html lang="en"><body><p>x</p><img alt="" '
        'src="https://example.invalid/p.gif"><script>document.cookie="a=1";'
        'localStorage.setItem("k","v")</script></body></html>', encoding="utf-8")
    (tmp_path / "good.html").write_text('<!doctype html><html lang="en"><body><p>x</p>'
                                        '</body></html>', encoding="utf-8")
    with lc._serving(tmp_path) as base:
        results = lc.run_browser([{"path": "good.html", "widths": [390], "settle": 300},
                                  {"path": "bad.html", "widths": [390], "settle": 300}], base)
    assert not isinstance(results, str), results
    hosts, kept = lc.audit_privacy_probe(results, base.split("//")[1])
    assert hosts == ["bad.html @390: example.invalid"]
    assert any("cookie a" in k for k in kept) and any("storage [1, 0]" in k for k in kept)
    assert all("good.html" not in k for k in hosts + kept)


def test_the_origin_allowlist_catches_what_the_old_denylist_let_through() -> None:
    """ANALYTICS-05, as a standing mutation check of tests/test_site.py's
    allowlist: the two scripts the six-name denylist passed — Cloudflare Web
    Analytics' beacon and Umami — plus a fetch, a stylesheet, a srcset and a
    CSS url() to another host are each named; our own two hosts and relative
    paths are not."""
    from test_site import _loaded_urls, _third_party
    page = (SITE / "index.html").read_text(encoding="utf-8")
    assert not [u for u in _loaded_urls(page, "html") if _third_party(u)]
    injected = page.replace("</body>", (
        "<script defer src='https://static.cloudflareinsights.com/beacon.min.js' "
        "data-cf-beacon='{}'></script><script src=\"https://cloud.umami.is/script.js\">"
        "</script><link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2\">"
        "<img alt=\"\" srcset=\"//cdn.example.com/a.png 1x, b.png 2x\">"
        "<div style=\"background:url(https://t.co/p.gif)\"></div>"
        "<script>fetch('https://api.example.com/x')</script></body>"))
    caught = {u for u in _loaded_urls(injected, "html") if _third_party(u)}
    assert caught == {"https://static.cloudflareinsights.com/beacon.min.js",
                      "https://cloud.umami.is/script.js", "https://fonts.googleapis.com/css2",
                      "//cdn.example.com/a.png", "https://t.co/p.gif",
                      "https://api.example.com/x"}
    own = 'const WAITLIST_ENDPOINT = "https://forms.beatyourleague.com"; fetch("/week.json")'
    assert not [u for u in _loaded_urls(own, "js") if _third_party(u)]
    assert [u for u in _loaded_urls('const FORM_ENDPOINT = "https://x.workers.dev";', "js")
            if _third_party(u)] == ["https://x.workers.dev"]


# --------------------------------------------------------------------- #
# the privacy page says exactly what count.js does
# --------------------------------------------------------------------- #

def _privacy() -> str:
    from test_promises_legal import _visible
    return _visible("privacy.html")


def test_the_privacy_page_describes_the_counter_and_drops_no_analytics() -> None:
    """ANALYTICS-04: "runs no analytics" and "Do Not Track changes nothing"
    were true until the counter; now the page names what a line holds, field
    by field as count.js sends them, who runs it, how long it lasts, and that
    GPC and Do Not Track switch it off — and still that no third party is
    contacted, which the origin allowlist (tests/test_site.py) keeps true."""
    text = _privacy()
    for gone in ("runs no analytics", "no analytics,", "changes nothing",
                 "no tracking of where you go or what you read"):
        assert gone not in text, gone
    section3 = text[text.index("3. Cookies, analytics and tracking"):text.index("4. Who else")]
    for field in ("which page or step", "channel tag", "the name of the site that linked here",
                  "phone- or desktop-sized", "whether checkout was open", "country",
                  "forms.beatyourleague.com", "three months", "Global Privacy Control",
                  "Do Not Track", "no IP address", "makes no request to any third party"):
        assert field in section3, field
    box = text[text.index("The whole list."):text.index("1. What we collect")]
    assert "page counts" in box
    section1 = text[text.index("1. What we collect"):text.index("2. What we never")]
    assert "Page counts" in section1
    section4 = text[text.index("4. Who else"):text.index("5. Your report")]
    assert "runs our page counter" in section4
    assert "page counts (section 3) after three months" in text
    # True before the Worker's /e is deployed as well as after (review): the
    # counting is stated as switched on with the forms, never as running now.
    assert "We do count visits" not in text
    assert "until then nothing is counted" in section3
    assert "once it is switched on, runs our page counter" in section4
    assert re.search(r"Page counts\s*,\s*once our counter is switched on", section1)
    assert "once our counter is switched on, anonymous page counts" in box
    # Steps inside the site carry our own name as the referrer (count.js).
    assert "or ours for a step from one of our pages" in section3
    source = COUNT_JS.read_text(encoding="utf-8")
    assert "globalPrivacyControl" in source and "doNotTrack" in source
    assert re.search(r"const LIVE = \"beatyourleague\.com\"", source)


def test_the_privacy_page_names_the_postal_code_not_a_full_address() -> None:
    """Critique #7, both halves. Reproduction (review): LAUNCH.md still set
    "Collect customer addresses" On while this page named only the card's
    country and postal code. LAUNCH now sets it Off, so Checkout takes the
    card's country and, where the card needs one, its postal code; the page
    says that, and a full address only if checkout is set to ask — true
    whichever way the owner leaves the toggle. The join page's footer says
    the same instead of "asks for your billing address"."""
    text = _privacy()
    assert "your billing address, plus" not in text
    assert "your card's country and, where the card needs one, its postal code" in text
    assert text.count("billing address only if") >= 2
    launch = (ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    [toggle] = re.findall(r"\| Collect customer addresses \| (\w+) \|", launch)
    assert toggle == "Off"
    join = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    assert "asks for your billing address" not in join
    assert "asks for your card's country and, where needed, its postal code" in join
    assert "We ask for a billing address at checkout and nothing more" not in text


def test_the_privacy_page_matches_seats_codes_and_backups_as_they_now_work() -> None:
    """Routed by the WORKER and INFRA builds, and the lead: a seat claim now
    holds only the pass code from the league's own link (contract C3), so
    "or the email the pass was bought with" described a match nothing makes;
    a free report also keeps a keyed code for each player on that roster; and
    the automation's storage is encrypted, with an encrypted backup kept up
    to 90 days. The page must describe exactly what is collected."""
    text = _privacy()
    section1 = text[text.index("1. What we collect"):text.index("2. What we never")]
    seat = section1[section1.index("If you claim a League Pass seat"):]
    seat = seat[:seat.index("If you change your roster")]
    assert "the email the pass was bought with" not in text
    assert "the pass code in your league's own link" in seat
    free = section1[section1.index("If you ask for a free report"):]
    free = free[:free.index("If you join the waitlist")]
    assert "a keyed one-way code for each player on that roster" in free
    assert "no names, no address" in free and "for the season" in free
    box = text[text.index("The whole list."):text.index("1. What we collect")]
    assert "one for each player on that roster" in box
    section4 = text[text.index("4. Who else"):text.index("5. Your report")]
    assert "kept, encrypted, in the storage that automation carries" in section4
    assert "an encrypted backup copy it keeps for up to 90 days" in section4
    assert "A deletion removes the older copies too." in section4
    # Form rows: waitlist rows about 400 days, every other kind 30 — "within
    # about 13 months" covers both and stays the stated limit.
    assert "deletes itself within about 13 months" in section4


def test_the_privacy_page_carries_the_sites_one_nav() -> None:
    """Routed by the PAGES build: privacy kept the old nav (a Home pill, "Real
    report") only because its visible text is pinned to its Last-updated
    date; this rewrite moved the date, so the nav moved with it (contract C2:
    the lockup, "See a real report", no Home pill)."""
    page = (SITE / "privacy.html").read_text(encoding="utf-8")
    top = page.split("<body", 1)[1].split("<h1", 1)[0]
    assert 'class="home"' not in top and "← Home" not in top
    assert '<span>Beat Your <span class="lg">League</span></span>' in top
    assert '<a href="sample-report.html">See a real report</a>' in top
    assert '<a class="hidesm" href="index.html#pricing">Pricing</a>' in top


def test_the_counters_store_and_token_are_a_plan_risk_decision() -> None:
    """ANALYTICS-01 better fix (b): CLAUDE.md's security section makes any new
    data store or credential a PLAN.md risk-item decision first. The counter
    added both (the byl_counts dataset, CF_ANALYTICS_TOKEN), so PLAN §7 now
    records the decision and §2's budget table carries the free line."""
    plan = (ROOT / "PLAN.md").read_text(encoding="utf-8")
    budget = plan[plan.index("## 2. Budget"):plan.index("## 3.")]
    assert "Cloudflare Analytics Engine (the page counter" in budget
    risks = plan[plan.index("## 7. Risks"):plan.index("## 8.")]
    item = risks[risks.index("The page counter's data store and read token"):]
    item = item[:item.index("\n- ")]
    for fact in ("`byl_counts`", "`CF_ANALYTICS_TOKEN`", "Account Analytics: Read",
                 "never a GitHub secret", "three months", "Off switch"):
        assert fact in item, fact


def test_launch_does_not_promise_the_phone_is_left_out() -> None:
    """Reproduction (review): step 8 said to turn on DNT or GPC "phone
    included", but iPhone Safari and Chrome on iOS send neither, so the owner's
    own iPhone visits are counted however the step is followed. The step says
    so and names a browser that does send it."""
    launch = (ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    step = launch[launch.index("8. Turn on Do Not Track"):launch.index("9. **Tell me")]
    assert "phone included" not in step
    assert "On an iPhone, Safari and Chrome send" in step
    assert "DuckDuckGo" in step
    start = launch.index("## 5b.")
    intro = launch[start:launch.index("1. Cloudflare", start)]
    assert "(on every page)" not in intro and "the generated ones too" in intro
