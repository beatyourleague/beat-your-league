"""The owner's private dashboard — `make dashboard`.

Usage:
    python -m run.dashboard [--out PATH] [--registry PATH] [--no-open] [--now ISO]
                            [--every MINUTES]     (make dashboard-live: rebuild on a timer)

One self-contained HTML page, built on the owner's own Mac from the owner's own
sources, opened in the browser. The decisions, each for a reason:

- **No server, no hosted panel, no login.** The safest server is the one we
  don't run (CLAUDE.md security). A dashboard that lived anywhere would need
  an account to guard it and would hold sales and traffic figures somewhere
  that can be breached; this one is a file on the owner's disk that nobody
  else can reach. It is fresh exactly when it is run.
- **It refuses to run in CI**, for the same reason `make stats` does
  (run/stats.py ``in_ci``): the repository is public, so a job log or an
  artifact would publish sales and traffic to anyone.
- **It writes only to a gitignored path** (default ``data/dashboard.html``,
  checked with ``git check-ignore`` like ``make stats --html``) so the counts
  can never be committed to a public repository by accident.
- **Read-only, everywhere.** Every source is read with GETs (Cloudflare's SQL
  API is a POST that only reads). The intake's own sweep is called with
  ``promote=False``, so not even Stripe customer metadata is written. Nothing
  is sent, stamped or changed.
- **Counts and dollars, never a person.** Addresses are turned into a keyed
  digest the moment a row is read (only to count distinct mailboxes and to
  join a free report to a purchase) and never reach the page; every free-text
  string from a provider passes through ``run.redact`` before it is rendered,
  and the finished page is swept once more for anything shaped like an
  address or a credential, plus the literal value of every secret in the
  shell. A secret is never embedded.
- **It reuses `make stats`' collectors** (``run.stats``: the counter query,
  the Stripe list walk, pass typing, form and send-log summaries, the .env
  reader) and the intake's, launch check's and ledger's own functions, so
  the dashboard and the command line can never disagree about a number.
- **Every source degrades on its own.** A source that is not connected shows
  a setup card naming its LAUNCH.md step and what it will show; a source that
  fails shows its (redacted) reason; neither stops the rest of the page.
- **Self-contained.** No CDN, no web fonts, no request of any kind: Barlow is
  inlined from ``site/fonts`` as base64, charts are SVG/HTML drawn here, and
  the few lines of script (period switch, theme, chart hover) are inline. The
  only URLs are plain links to the owner's consoles.
- **Honest numbers.** The page counter counts page views and signup steps,
  never people (privacy section 3), so it is labelled that way; the funnel is
  a ratio of step counts, not a cohort, and says so; insights state the
  numbers they rest on and say "not enough data yet" below a floor instead of
  reading noise; decision-gate targets are read from PLAN.md §6's own table,
  never restated here.
- **Profit and posts come from the owner's own books** (``run/books.py``:
  ``data/costs.csv``, ``hours.csv``, ``posts.csv``, all gitignored). A cost
  counts on the day it is charged; profit is Stripe's net less those; a post
  is a ``?via=`` tag (``make link``), counted on its own row and under its
  channel (the part before the first hyphen), and pinned on the traffic chart
  on the day it went out.
- **Live mode** (``--every``) rebuilds on a timer and the page reloads itself;
  the page turns amber when its numbers are older than two rounds.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import itertools
import html as _html
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

import run.stats as stats
from run.redact import redact

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "data" / "dashboard.html"
# Live mode (`make dashboard-live`) rebuilds on a timer. The floor is set by
# GitHub's unauthenticated API allowance (60 requests an hour, one per workflow
# per build): every 10 minutes is 36 an hour, safely under it.
LIVE_MIN_MINUTES = 10
LIVE_DEFAULT_MINUTES = 15
ET = ZoneInfo("America/New_York")
GITHUB_REPO = "beatyourleague/beat-your-league"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"

# What the dashboard reads from this shell or the gitignored .env. The Stripe
# key may be a dedicated read-only one (STRIPE_STATS_KEY, LAUNCH.md step 3's
# owner-stats key); STRIPE_API_KEY is the fallback make stats already uses.
ENV_NAMES = ("CF_ACCOUNT_ID", "CF_ANALYTICS_TOKEN", "STRIPE_STATS_KEY", "STRIPE_API_KEY",
             "STRIPE_PAYMENT_LINKS", "FORM_ENDPOINT", "FORM_API_KEY", "RESEND_READ_KEY")
SECRET_NAMES = ("CF_ANALYTICS_TOKEN", "STRIPE_STATS_KEY", "STRIPE_API_KEY", "FORM_API_KEY",
                "RESEND_READ_KEY", "STRIPE_PAYMENT_LINKS")

PERIODS = (("7d", "7 days", 7), ("30d", "30 days", 30), ("all", "All", None))
TRAFFIC_ALL_DAYS = 90          # Analytics Engine keeps three months

CONSOLES = (
    ("Stripe", "https://dashboard.stripe.com/payments"),
    ("Cloudflare", "https://dash.cloudflare.com/"),
    ("GitHub Actions", f"https://github.com/{GITHUB_REPO}/actions"),
    ("Resend", "https://resend.com/emails"),
    ("Live site", "https://beatyourleague.com/"),
)

# Floors below which a ratio is noise, not a finding.
MIN_FUNNEL_VIEWS = 100
MIN_CHANNEL_VIEWS = 20
MIN_REFUND_SAMPLE = 5


# --------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------- #

@dataclass
class Source:
    key: str
    label: str
    status: str = "ok"                # ok | off | error
    data: Any = None
    note: str = ""
    setup: str = ""
    shows: str = ""
    read_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class Context:
    env: Mapping[str, str]
    now: datetime
    root: Path = REPO_ROOT
    registry: Path | None = None


# What each source is, how to connect it, and what it shows once it is.
SOURCE_INFO = {
    "traffic": ("Page counter", "LAUNCH.md step 5b — the page counter",
                "Daily views, top pages, sources, channels, devices and countries, "
                "and the signup funnel step by step."),
    "forms": ("Form Worker", "LAUNCH.md step 5 — the form Worker",
              "Waitlist sign-ups, free-report requests, roster updates and seat claims."),
    "stripe": ("Stripe", "LAUNCH.md step 3 — Stripe keys (the read-only owner-stats key)",
               "Passes sold by type, gross, fees, refunds and net, disputes, and paid "
               "signups by channel."),
    "intake": ("Intake check", "LAUNCH.md step 3 — Stripe keys",
               "Payments the hourly intake can't serve (PAID-UNATTRIBUTED, PLAYOFF-EARLY)."),
    "sends": ("Send log", "`git pull` — the crons commit data/processed/sent.jsonl",
              "Emails sent per week, welcomes, free reports and stop requests."),
    "registry": ("Registry", "`make stats-registry` opens a copy; pass --registry PATH",
                 "Subscribers by plan and League Pass seats claimed against each cap."),
    "bounces": ("Resend", "LAUNCH.md step 2 — a Full access key as RESEND_READ_KEY",
                "Emails of the last 48 hours that bounced or were marked spam."),
    "github": ("GitHub Actions", "Needs the network (the repo's public Actions API)",
               "Whether each cron ran on time and passed."),
    "launch": ("Launch check", "`make launch-check` runs the full set",
               "The fast, local launch-check gates: failures and owner steps left."),
    "ledger": ("Public record", "Grows from Week 2's report Tuesday",
               "This season's published calls, graded and pending, by stated band."),
    "site": ("Site data", "Rebuilt by the Tuesday cron",
             "How old this week's sample and the player directory are."),
    "plan": ("PLAN.md §6", "PLAN.md §6 — the decision gates",
             "The pre-committed decision gates and where each stands."),
    "books": ("Your books", 'make cost ITEM="Domain" AMOUNT=12 REPEATS=yearly — costs, hours and '
                            'post links live in data/ (run/books.py)',
              "Profit after your costs, when you break even, what you earn per hour, and which "
              "posts sold."),
}


def _source(key: str, **kw) -> Source:
    label, setup, shows = SOURCE_INFO[key]
    return Source(key=key, label=label, setup=setup, shows=shows, **kw)


def off(key: str, note: str, setup: str = "") -> Source:
    src = _source(key, status="off", note=note)
    if setup:
        src.setup = setup
    return src


_SALT = os.urandom(16)   # per run: a digest joins two lists, never names anyone


def who(email: object) -> str | None:
    """A mailbox as a per-run digest: enough to count distinct people and to
    join a free-report request to a purchase, useless outside this run."""
    if not email:
        return None
    from run.trials import canonical_email
    return hashlib.sha256(_SALT + canonical_email(str(email)).encode()).hexdigest()[:16]


def _iso(value: object) -> str | None:
    stamp = stats._when(value) if value else None
    return stamp.isoformat() if stamp else None


def _season(ctx: Context) -> str:
    try:
        from run.solo import CACHE_DIR, current_season
        return current_season(CACHE_DIR, today=ctx.now.date())
    except Exception:  # noqa: BLE001 — no cache: the calendar year's season
        return str(ctx.now.year if ctx.now.month >= 3 else ctx.now.year - 1)


# --- traffic ---------------------------------------------------------- #

DAILY_SQL = ("SELECT toStartOfInterval(timestamp, INTERVAL '1' DAY) AS t, blob1 AS e, "
             "blob2 AS p, blob6 AS s, blob3 AS v, SUM(_sample_interval) AS n FROM {dataset} "
             "WHERE timestamp > NOW() - INTERVAL '{days}' DAY "
             "GROUP BY t, e, p, s, v ORDER BY t LIMIT 10000 FORMAT JSON")
_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def query_daily(account: str, token: str, days: int) -> list[dict]:
    """The counter by UTC day, event, page and checkout state — the daily
    series and the previous-period deltas. The same read-only SQL endpoint and
    the same field rules as ``run.stats.query_counts``."""
    if not stats.ACCOUNT_RE.fullmatch(account):
        raise ValueError("CF_ACCOUNT_ID is not a 32-character Cloudflare account id")
    sql = DAILY_SQL.format(dataset=stats.COUNT_DATASET, days=int(days))
    request = urllib.request.Request(
        stats.AE_SQL.format(account=account), data=sql.encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
    with urllib.request.urlopen(request, timeout=30) as response:
        doc = json.loads(response.read().decode("utf-8"))
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, list):
        raise ValueError("the counter answered in a shape we don't recognise")
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        day = _DAY.match(str(row.get("t") or ""))
        clean = {k: row.get(k) if isinstance(row.get(k), str) else "" for k in "epsv"}
        if (not day or clean["e"] not in stats.COUNT_EVENTS
                or not all(stats._FIELD.fullmatch(clean[k]) for k in "psv")):
            continue
        try:
            n = int(float(row.get("n") or 0))
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append({"day": day.group(1), **clean, "n": n})
    return out


def collect_traffic(ctx: Context) -> Source:
    endpoint = stats.counter_endpoint(ctx.root / "site" / "count.js")
    if not endpoint:
        return off("traffic", "The counter is switched off: site/count.js has no ENDPOINT yet.")
    account, token = ctx.env.get("CF_ACCOUNT_ID", ""), ctx.env.get("CF_ANALYTICS_TOKEN", "")
    if not (account and token):
        return off("traffic", "CF_ACCOUNT_ID / CF_ANALYTICS_TOKEN are not in this shell or .env.",
                   "LAUNCH.md step 5b, items 6–7 — a read-only Analytics token in .env")
    rows = {"7d": stats.query_counts(account, token, 7),
            "30d": stats.query_counts(account, token, 30),
            "all": stats.query_counts(account, token, TRAFFIC_ALL_DAYS)}
    daily = query_daily(account, token, TRAFFIC_ALL_DAYS)
    return _source("traffic", data={"rows": rows, "daily": daily}, read_at=ctx.now)


# --- forms ------------------------------------------------------------ #

def collect_forms(ctx: Context) -> Source:
    endpoint = ctx.env.get("FORM_ENDPOINT", "")
    if not endpoint:
        return off("forms", "FORM_ENDPOINT is not set — the Worker isn't deployed yet, "
                            "or its address isn't in this shell.")
    from run.intake import fetch_seats
    rows = fetch_seats(endpoint, ctx.env.get("FORM_API_KEY") or None)
    clean = []
    for row in rows:
        via = row.get("via")
        clean.append({
            "kind": str(row.get("kind") or "seat"),
            "at": _iso(row.get("received_at")),
            "via": via if isinstance(via, str) and stats.VIA_RE.fullmatch(via) else None,
            "who": who(row.get("email")),
        })
    channels = {k: dict(c) for k, c in stats.channel_summary(rows).items()}
    return _source("forms", data={"rows": clean, "summary": stats.form_summary(rows, ctx.now),
                                  "channels": channels}, read_at=ctx.now)


# --- Stripe ----------------------------------------------------------- #

def stripe_key(env: Mapping[str, str]) -> str:
    return env.get("STRIPE_STATS_KEY", "") or env.get("STRIPE_API_KEY", "")


def collect_stripe(ctx: Context) -> Source:
    key = stripe_key(ctx.env)
    if not key:
        return off("stripe", "No Stripe key in this shell or .env (STRIPE_STATS_KEY, "
                             "else STRIPE_API_KEY).")
    from run.checkout import parse_link_plans
    from run.intake import split_via
    from run.refs import is_roster_ref
    from run.subscriptions import DisputeLookup, _charge_refunded, dispute_state
    plans = parse_link_plans(ctx.env.get("STRIPE_PAYMENT_LINKS", ""))
    raw = stats._stripe_list("checkout/sessions",
                             [("expand[]", "data.payment_intent.latest_charge")], key)
    lookup = DisputeLookup(key)
    paid_ids = {id(s) for s in stats._paid_pass_sessions(raw, None)}
    sessions = []
    for s in raw:
        ref = s.get("client_reference_id")
        if not (isinstance(ref, str) and is_roster_ref(ref)):
            continue
        _ref, via = split_via(ref)
        entry = {"id": str(s.get("id") or ""), "created": s.get("created"),
                 "status": str(s.get("status") or ""), "paid": id(s) in paid_ids,
                 "via": via if via and stats.VIA_RE.fullmatch(via) else None}
        if entry["paid"]:
            charge = stats._charge(s)
            intent = s.get("payment_intent")
            usd = (str(s.get("currency") or "usd").lower() == "usd"
                   and isinstance(s.get("amount_total"), int))
            entry.update({
                "pass": stats._pass_type(s, plans),
                "amount": s["amount_total"] / 100 if usd else None,
                "refunded": int(charge.get("amount_refunded") or 0) / 100,
                "full_refund": _charge_refunded(charge),
                "dispute": dispute_state(charge, lookup),
                "payment": intent.get("id") if isinstance(intent, Mapping) else
                           (intent if isinstance(intent, str) else None),
                "who": who((s.get("customer_details") or {}).get("email")
                           or s.get("customer_email")),
            })
        sessions.append(entry)
    return _source("stripe", data={"sessions": sessions, "link_map": bool(plans),
                                   "dispute_errors": len(lookup.errors)}, read_at=ctx.now)


def collect_intake(ctx: Context) -> Source:
    """The hourly intake's own sweep, read-only (``promote=False``): the
    payments it would report as PAID-UNATTRIBUTED or PLAYOFF-EARLY this
    season, plus any it remembers in a local roster-sync-state.json."""
    key = stripe_key(ctx.env)
    if not key:
        return off("intake", "Needs the Stripe key to run the intake's sweep read-only.")
    from run.checkout import parse_link_plans, playoff_links
    from run.intake import STATE_NAME, _SESSION_IN, read_state, sweep
    raw_links = ctx.env.get("STRIPE_PAYMENT_LINKS", "")
    signups, _newest, problems = sweep(
        key, stats._season_start(_season(ctx)), parse_link_plans(raw_links), promote=False,
        playoff=playoff_links(raw_links))
    state = read_state(ctx.root / "data" / "registry" / STATE_NAME)
    acknowledged = set(state.get("acknowledged") or [])
    remembered = [p for p in state.get("unresolved") or [] if isinstance(p, str)]
    found = []
    for problem in [*problems, *remembered]:
        session = _SESSION_IN.search(problem)
        if session and session.group(1) in acknowledged:
            continue
        text = redact(problem)
        if text not in found:
            found.append(text)
    return _source("intake", data={"problems": found, "signups": len(signups),
                                   }, read_at=ctx.now)


# --- local files ------------------------------------------------------ #

def collect_sends(ctx: Context) -> Source:
    path = ctx.root / "data" / "processed" / "sent.jsonl"
    from run.suppress import load_suppressed
    try:
        stopped = len(load_suppressed(ctx.root / "data" / "processed" / "suppressed.txt"))
    except Exception:  # noqa: BLE001 — the count is optional
        stopped = None
    if not path.is_file():
        return off("sends", "No send log on this machine yet — nothing has been sent, or "
                            "this checkout hasn't pulled the crons' commits.")
    entries = [{"key": str(e["key"]), "sent_at": _iso(e.get("sent_at")),
                "provider": str(e.get("provider") or "")}
               for e in stats.load_send_log(path)]
    season = _season(ctx)
    return _source("sends", data={"entries": entries, "season": season, "stopped": stopped,
                                  "summary": stats.send_summary(entries, season)},
                   read_at=ctx.now)


def collect_registry(ctx: Context) -> Source:
    from run.rosters import RosterRegistryError, load_rosters
    path = ctx.registry or (ctx.root / "data" / "registry" / "rosters.json")
    if ctx.registry is None and not path.is_file():
        return off("registry", "The registry lives sealed in the CI cache, not on this Mac.")
    try:
        rows = load_rosters(path)
    except RosterRegistryError as exc:
        return _source("registry", status="error", note=redact(exc))
    names = {"season": "Pass holders", "monthly": "Monthly", "pass": "League Pass buyers",
             "league_pass": "League Pass seats"}
    plans = Counter(names.get(s.report_plan, s.report_plan) for s in rows)
    payers = {s.pass_key: s for s in rows if s.is_pass_payer and s.pass_key}
    seats = Counter(s.pass_key for s in rows if s.is_league_seat and s.pass_key)
    filled = sorted(((seats.get(k, 0), max(0, int(p.league_size))) for k, p in payers.items()),
                    key=lambda t: (-t[0], -t[1]))
    return _source("registry", data={"total": len(rows), "plans": dict(plans),
                                     "seats": filled,
                                     "setups": dict(Counter(f"{s.scoring}/{s.league_size}"
                                                            for s in rows))},
                   read_at=ctx.now)


def collect_bounces(ctx: Context) -> Source:
    key = ctx.env.get("RESEND_READ_KEY", "").strip()
    if not key:
        return off("bounces", "RESEND_READ_KEY is not in this shell or .env.")
    from run.delivery import check_bounces
    entries = stats.load_send_log(ctx.root / "data" / "processed" / "sent.jsonl")
    report = check_bounces(entries, ctx.now, api_key=key)
    if report.key_cannot_read:
        return _source("bounces", status="error",
                       note="That Resend key can only send — reading needs a Full access key.")
    return _source("bounces", data={"checked": report.checked, "errors": report.errors,
                                    "paid": [e for _k, e in report.paid],
                                    "unpaid": [e for _k, e in report.unpaid]},
                   read_at=ctx.now)


# --- GitHub Actions (public, unauthenticated) ------------------------- #

WORKFLOWS = (
    ("weekly.yml", "Tuesday reports"),
    ("saturday.yml", "Saturday check"),
    ("daily.yml", "Hourly intake"),
    ("monday.yml", "Monday grading"),
    ("test.yml", "Tests"),
    ("pages.yml", "Site deploy"),
)


def _github_get(path: str) -> Any:
    request = urllib.request.Request(f"{GITHUB_API}/{path}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "beat-your-league-dashboard"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_github(ctx: Context, fetch: Callable[[str], Any] | None = None) -> Source:
    fetch = fetch or _github_get
    out = {}
    for name, label in WORKFLOWS:
        doc = fetch(f"actions/workflows/{name}/runs?per_page=30")
        runs = doc.get("workflow_runs") if isinstance(doc, dict) else None
        if not isinstance(runs, list):
            raise ValueError(f"GitHub answered {name} in a shape we don't recognise")
        out[name] = {"label": label, "runs": [
            {"created_at": str(r.get("created_at") or ""), "status": str(r.get("status") or ""),
             "conclusion": str(r.get("conclusion") or ""), "event": str(r.get("event") or ""),
             "url": str(r.get("html_url") or "")}
            for r in runs if isinstance(r, dict) and r.get("created_at")]}
    return _source("github", data=out, read_at=ctx.now)


# --- launch check (fast, local gates only) ---------------------------- #

FAST_GATES = ("check_links", "check_page_basics", "check_selling_copy", "check_prices",
              "check_funnel_config", "check_week_json", "check_record", "check_compliance",
              "check_secrets", "check_link_map", "check_resend_read_key", "check_economics",
              "check_security_txt", "check_seat_link")


def collect_launch(ctx: Context) -> Source:
    import run.launch_check as lc
    gates = []
    for name in FAST_GATES:
        try:
            gates.extend(g.__dict__.copy() for g in getattr(lc, name)())
        except Exception as exc:  # noqa: BLE001 — one broken check never hides the rest
            gates.append({"area": "Check", "name": f"{name} could not run", "status": "FAIL",
                          "detail": f"{type(exc).__name__}: {exc}"})
    for gate in gates:
        gate["detail"] = redact(gate.get("detail", ""))
    return _source("launch", data={"gates": gates}, read_at=ctx.now)


# --- the public record ------------------------------------------------ #

def collect_ledger(ctx: Context) -> Source:
    from engine.ledger import LedgerError, load_ledger
    season = _season(ctx)
    calls, unreadable = [], []
    for path in sorted((ctx.root / "data" / "processed" / "ledger")
                       .glob(f"typed-*-{season}/calls.jsonl")):
        try:
            held = load_ledger(path)
        except (LedgerError, OSError) as exc:
            unreadable.append(f"{path.parent.name}: {redact(exc)}")
            continue
        for c in held:
            calls.append({"store": path.parent.name, "week": c.week, "confidence": c.confidence,
                          "status": c.status, "outcome": c.outcome,
                          "recorded_at": c.recorded_at})
    return _source("ledger", data={"season": season, "calls": calls, "unreadable": unreadable},
                   read_at=ctx.now)


def _git_time(root: Path, rel: str) -> str | None:
    try:
        done = subprocess.run(["git", "log", "-1", "--format=%cI", "--", rel], cwd=root,
                              capture_output=True, text=True, timeout=20)
        return done.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def collect_site(ctx: Context) -> Source:
    week, players_at = None, None
    try:
        week = json.loads((ctx.root / "site" / "week.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    try:
        players = json.loads((ctx.root / "site" / "join" / "players.json")
                             .read_text(encoding="utf-8"))
        players_at = players.get("generated") if isinstance(players, dict) else None
    except (OSError, json.JSONDecodeError):
        players_at = _git_time(ctx.root, "site/join/players.json")
    keep = ("season", "week", "last_week", "built_at", "phase", "lands_on", "first_kickoff")
    return _source("site", data={"week": {k: week.get(k) for k in keep}
                                 if isinstance(week, dict) else None,
                                 "players_at": players_at}, read_at=ctx.now)


# --- PLAN.md §6 ------------------------------------------------------- #

def parse_plan_gates(text: str) -> dict:
    """The proof-season gate table of PLAN.md §6 and the D date, read
    verbatim — the targets are the plan's, never restated here."""
    d_match = re.search(r"\(write the date here when it happens: D = ([^)]*)\)", text)
    d_raw = (d_match.group(1).strip() if d_match else "")
    d_date = None
    for fmt in ("%Y-%m-%d", "%b %d %Y", "%b %d, %Y", "%B %d %Y", "%B %d, %Y"):
        try:
            d_date = datetime.strptime(d_raw.strip("_ *"), fmt).date().isoformat()
            break
        except ValueError:
            continue
    start = text.find("Proposed proof-season gates")
    gates = []
    if start >= 0:
        table = re.search(r"((?:^\|.*\|\s*$\n?)+)", text[start:], re.M)
        for line in (table.group(1).splitlines() if table else [])[2:]:
            cells = [c.strip().replace("**", "").replace("`", "") for c in line.strip("|").split("|")]
            if len(cells) >= 4:
                gates.append({"read_by": cells[0], "metric": cells[1], "green": cells[2],
                              "red": cells[3]})
    return {"d_date": d_date, "d_written": bool(d_date), "gates": gates}


def collect_plan(ctx: Context) -> Source:
    text = (ctx.root / "PLAN.md").read_text(encoding="utf-8")
    parsed = parse_plan_gates(text)
    if not parsed["gates"]:
        return _source("plan", status="error",
                       note="PLAN.md §6's proof-season gate table could not be read.")
    return _source("plan", data=parsed, read_at=ctx.now)


def collect_books(ctx: Context) -> Source:
    from run.books import load
    books = load(ctx.root)
    if not books.found:
        return off("books", "No costs, hours or posts recorded yet.")
    return _source("books", data=books, read_at=ctx.now)


COLLECTORS: dict[str, Callable[[Context], Source]] = {
    "traffic": collect_traffic, "forms": collect_forms, "stripe": collect_stripe,
    "intake": collect_intake, "sends": collect_sends, "registry": collect_registry,
    "bounces": collect_bounces, "github": collect_github, "launch": collect_launch,
    "ledger": collect_ledger, "site": collect_site, "plan": collect_plan,
    "books": collect_books,
}


def _scrub_error(exc: Exception, env: Mapping[str, str]) -> str:
    text = f"{type(exc).__name__}: {stats._safe(exc)}"
    for name in SECRET_NAMES:
        value = env.get(name) or ""
        if len(value) >= 6:
            text = text.replace(value, "***")
    text = re.sub(r"Bearer\s+\S+", "Bearer ***", text)
    return redact(text)[:220]


def collect_all(ctx: Context, collectors: Mapping[str, Callable[[Context], Source]] | None = None
                ) -> dict[str, Source]:
    """Every source, side by side and independently: one that raises becomes
    an error card with its (redacted) reason, and the rest still render."""
    collectors = dict(COLLECTORS if collectors is None else collectors)

    def run(item: tuple[str, Callable[[Context], Source]]) -> Source:
        key, fn = item
        try:
            src = fn(ctx)
            if not isinstance(src, Source):
                raise TypeError("collector returned no Source")
            return src
        except Exception as exc:  # noqa: BLE001 — one source never kills the page
            src = _source(key, status="error", note=_scrub_error(exc, ctx.env)) \
                if key in SOURCE_INFO else Source(key, key, "error", note=_scrub_error(exc, ctx.env))
            return src
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, collectors.items()))
    out = {src.key: src for src in results}
    for key in SOURCE_INFO:
        out.setdefault(key, off(key, "Not read this time."))
    return out


# --------------------------------------------------------------------- #
# derived numbers
# --------------------------------------------------------------------- #

def period_days(period: str) -> int | None:
    return dict((k, d) for k, _l, d in PERIODS)[period]


def _ts(value: Any) -> datetime | None:
    if isinstance(value, int):
        return datetime.fromtimestamp(value, timezone.utc)
    return stats._when(value) if value else None


def _in(stamp: datetime | None, now: datetime, days: int | None, offset: int = 0) -> bool:
    if stamp is None or stamp > now:
        return False
    if days is None:
        return offset == 0
    end = now - timedelta(days=offset * days)
    return end - timedelta(days=days) < stamp <= end


FUNNEL_TESTS = dict(stats.FUNNEL)


def is_view(r: Mapping) -> bool:
    return r["e"] == "view"


def traffic_count(rows: list[dict], test) -> int:
    return stats._sum(rows, test)


def day_range(now: datetime, days: int) -> list[str]:
    today = now.astimezone(timezone.utc).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def daily_series(daily: list[dict], days: list[str], test) -> list[int]:
    by = Counter()
    for r in daily:
        if test(r):
            by[r["day"]] += r["n"]
    return [by.get(d, 0) for d in days]


def delta(cur: float | None, prev: float | None) -> float | None:
    """Change on the previous period; ``inf`` when there was nothing before
    (shown as "New", never as a percentage)."""
    if cur is None or prev is None:
        return None
    if prev == 0:
        return math.inf if cur > 0 else None
    return (cur - prev) / prev


@dataclass
class Metrics:
    """Everything one period's sections need, computed once."""
    period: str
    days: int | None
    traffic: dict | None = None
    money: dict | None = None
    forms: dict | None = None
    funnel: list = field(default_factory=list)
    channels: list = field(default_factory=list)
    posts: list = field(default_factory=list)
    profit: dict | None = None


TRAFFIC_STEPS = (("Landing views", "Landing views"), ("Buy-page views", "Buy-page views"),
                 ("Rosters checked", "Rosters checked on the buy page"))


def traffic_metrics(src: Source, period: str, now: datetime) -> dict | None:
    if not src.ok:
        return None
    rows = src.data["rows"][period]
    daily = src.data["daily"]
    span = period_days(period) or TRAFFIC_ALL_DAYS
    spark_days = day_range(now, max(span, 14) if period != "all" else TRAFFIC_ALL_DAYS)
    chart_days = day_range(now, span)
    test_buy = lambda r: r["e"] == "checkout"  # noqa: E731
    out = {
        "views": traffic_count(rows, is_view),
        "landing": traffic_count(rows, FUNNEL_TESTS["Landing views"]),
        "buy_views": traffic_count(rows, FUNNEL_TESTS["Buy-page views"]),
        "rosters": traffic_count(rows, FUNNEL_TESTS["Rosters checked on the buy page"]),
        "presses": traffic_count(rows, test_buy),
        "presses_open": traffic_count(rows, FUNNEL_TESTS["Buy pressed, checkout open"]),
        "presses_closed": traffic_count(rows, FUNNEL_TESTS["Buy pressed, checkout closed"]),
        "chart_days": chart_days,
        "chart": daily_series(daily, chart_days, is_view),
        "chart_landing": daily_series(daily, chart_days, FUNNEL_TESTS["Landing views"]),
        "chart_buy": daily_series(daily, chart_days, FUNNEL_TESTS["Buy-page views"]),
        "spark_views": daily_series(daily, spark_days, is_view),
        "spark_rosters": daily_series(daily, spark_days,
                                      FUNNEL_TESTS["Rosters checked on the buy page"]),
        "spark_presses": daily_series(daily, spark_days, test_buy),
        "rows": rows,
    }
    for name, test in (("views", is_view), ("rosters",
                                            FUNNEL_TESTS["Rosters checked on the buy page"]),
                       ("presses", test_buy)):
        if period == "all":
            out[f"{name}_delta"] = None
            continue
        full = day_range(now, 2 * span)
        series = daily_series(daily, full, test)
        out[f"{name}_delta"] = delta(sum(series[span:]), sum(series[:span]))
    for key, test in (("try_views", FUNNEL_TESTS["Free-report page views"]),
                      ("try_rosters", FUNNEL_TESTS["Free-report rosters checked"]),
                      ("try_requests", FUNNEL_TESTS["Free reports requested"]),
                      ("planner_views", FUNNEL_TESTS["Planner views"]),
                      ("planner_rosters", FUNNEL_TESTS["Planner rosters checked"]),
                      ("planner_waitlist", FUNNEL_TESTS["Waitlist joined from the planner"]),
                      ("waitlist_events", FUNNEL_TESTS["Waitlist joined"])):
        out[key] = traffic_count(rows, test)
    return out


def money_metrics(src: Source, period: str, now: datetime) -> dict | None:
    if not src.ok:
        return None
    from run.economics import stripe_fee
    days = period_days(period)
    sessions = src.data["sessions"]
    paid_all = [s for s in sessions if s.get("paid")]

    def window(offset: int) -> list[dict]:
        return [s for s in paid_all if _in(_ts(s.get("created")), now, days, offset)]
    paid, prev = window(0), (window(1) if days else None)

    def money(group: list[dict]) -> dict:
        usd = [s for s in group if isinstance(s.get("amount"), (int, float))]
        gross = sum(s["amount"] for s in usd)
        refunded = sum(s.get("refunded") or 0 for s in usd)
        fees = sum(stripe_fee(s["amount"], one_time=True) for s in usd)
        full = sum(bool(s.get("full_refund")) for s in group)
        return {"count": len(group), "gross": gross, "refunded": refunded, "fees": fees,
                "net": gross - refunded - fees, "full_refunds": full,
                "refund_rate": full / len(group) if group else None,
                "other_currency": len(group) - len(usd)}
    cur = money(paid)
    out = dict(cur)
    out["types"] = Counter(s.get("pass") or "unknown" for s in paid)
    out["by_channel"] = Counter(s.get("via") or stats.NO_VIA for s in paid)
    net_by_via: Counter = Counter()
    for s in paid:
        if isinstance(s.get("amount"), (int, float)):
            net_by_via[s.get("via") or stats.NO_VIA] += (s["amount"] - (s.get("refunded") or 0)
                                                         - stripe_fee(s["amount"], one_time=True))
    out["net_by_via"] = net_by_via
    out["disputes"] = [s for s in paid_all if s.get("dispute")]
    if prev is not None:
        p = money(prev)
        out["count_delta"] = delta(cur["count"], p["count"])
        out["net_delta"] = delta(cur["net"], p["net"])
        out["refund_delta"] = (None if cur["refund_rate"] is None or p["refund_rate"] is None
                               else cur["refund_rate"] - p["refund_rate"])
        out["prev_net"] = p["net"]
    else:
        out["count_delta"] = out["net_delta"] = out["refund_delta"] = None
        out["prev_net"] = None
    span = days or 90
    spark_days = day_range(now, max(span, 14))
    by_day = Counter(_ts(s.get("created")).date().isoformat() for s in paid_all
                     if _ts(s.get("created")))
    out["spark"] = [by_day.get(d, 0) for d in spark_days]
    net_day: Counter = Counter()
    for s in paid_all:
        stamp = _ts(s.get("created"))
        if stamp and isinstance(s.get("amount"), (int, float)):
            net_day[stamp.date().isoformat()] += (s["amount"] - (s.get("refunded") or 0)
                                                  - stripe_fee(s["amount"], one_time=True))
    out["spark_net"] = [round(net_day.get(d, 0), 2) for d in spark_days]
    out["chart_days"] = day_range(now, span)
    out["chart"] = [by_day.get(d, 0) for d in out["chart_days"]]
    started = [s for s in sessions if _in(_ts(s.get("created")), now, days)]
    out["checkouts"] = Counter(s.get("status") or "unknown" for s in started)
    return out


def forms_metrics(src: Source, period: str, now: datetime) -> dict | None:
    if not src.ok:
        return None
    days = period_days(period)
    rows = src.data["rows"]
    out: dict[str, Any] = {}
    for kind in ("waitlist", "trial", "update_request", "confirm", "seat", "update"):
        mine = [r for r in rows if r["kind"] == kind]
        out[kind] = {
            "total": len(mine),
            "people": len({r["who"] for r in mine if r["who"]}),
            "period": sum(_in(_ts(r["at"]), now, days) for r in mine),
            "prev": (sum(_in(_ts(r["at"]), now, days, 1) for r in mine) if days else None),
        }
    waitlist = [r for r in rows if r["kind"] == "waitlist"]
    spark_days = day_range(now, max(days or 90, 14))
    by_day = Counter(_ts(r["at"]).date().isoformat() for r in waitlist if _ts(r["at"]))
    out["waitlist_spark"] = [by_day.get(d, 0) for d in spark_days]
    out["by_channel"] = Counter(r["via"] or stats.NO_VIA for r in rows
                                if _in(_ts(r["at"]), now, days))
    return out


FREE_TO_PAID_DAYS = stats.FREE_TO_PAID_DAYS


def free_to_paid(forms: Source, stripe: Source, now: datetime) -> tuple[int, int, int] | None:
    """(paid within 14 days, requests old enough to judge, requests still
    inside the window) — the join ``make stats`` prints, on digests."""
    if not (forms.ok and stripe.ok):
        return None
    first: dict[str, datetime] = {}
    for row in forms.data["rows"]:
        stamp = _ts(row["at"])
        if row["kind"] == "trial" and row["who"] and stamp:
            first[row["who"]] = min(first.get(row["who"], stamp), stamp)
    bought: dict[str, list[datetime]] = defaultdict(list)
    for s in stripe.data["sessions"]:
        stamp = _ts(s.get("created"))
        if s.get("paid") and s.get("who") and stamp:
            bought[s["who"]].append(stamp)
    window = timedelta(days=FREE_TO_PAID_DAYS)
    closed = {w: at for w, at in first.items() if at <= now - window}
    paid = sum(any(at <= b <= at + window for b in bought.get(w, ())) for w, at in closed.items())
    return paid, len(closed), len(first) - len(closed)


def funnel_steps(traffic: dict | None, money: dict | None) -> list[tuple[str, int | None]]:
    if traffic is None:
        return []
    steps = [("Landing views", traffic["landing"]), ("Buy-page views", traffic["buy_views"]),
             ("Rosters checked", traffic["rosters"]), ("Buy pressed", traffic["presses"])]
    steps.append(("Paid", money["count"] if money is not None else None))
    return steps


def channel_rows(traffic: dict | None, money: dict | None) -> list[dict]:
    """By channel — a post's tag counts under its channel (reddit-oct28 is
    reddit); the posts table has each post on its own."""
    from run.books import channel_of
    if traffic is None:
        return []
    by: dict[str, dict] = defaultdict(lambda: {"views": 0, "rosters": 0, "presses": 0, "paid": 0})
    for r in traffic["rows"]:
        v = channel_of(r["v"]) or stats.NO_VIA
        if r["e"] == "view" and r["p"] in ("index",) + stats.BUY_PAGES:
            by[v]["views"] += r["n"]
        elif r["e"] == "roster" and r["p"] in stats.BUY_PAGES:
            by[v]["rosters"] += r["n"]
        elif r["e"] == "checkout":
            by[v]["presses"] += r["n"]
    if money is not None:
        for v, n in money["by_channel"].items():
            by[v if v == stats.NO_VIA else channel_of(v)]["paid"] += n
    rows = [{"channel": k, **v} for k, v in by.items()]
    rows.sort(key=lambda r: (r["channel"] == stats.NO_VIA, -r["views"], -r["paid"], r["channel"]))
    return rows


def post_rows(traffic: dict | None, money: dict | None, books: Source,
              daily: list[dict] | None) -> list[dict]:
    """One row per post: every tag the posts log names, plus any post-shaped
    tag (channel-detail, e.g. reddit-oct28) seen on the site. A post's day is
    the log's, else the first day the counter saw its tag."""
    from run.books import channel_of
    logged = {p.tag: p for p in books.data.posts} if books.ok else {}
    by: dict[str, dict] = {}

    def row(tag: str) -> dict:
        if tag not in by:
            post = logged.get(tag)
            by[tag] = {"tag": tag, "channel": channel_of(tag), "where": post.where if post else "",
                       "day": post.day.isoformat() if post else None, "logged": post is not None,
                       "views": 0, "rosters": 0, "presses": 0, "paid": 0}
        return by[tag]
    for tag in logged:
        row(tag)
    if traffic is not None:
        for r in traffic["rows"]:
            v = r["v"]
            if not v or (v not in logged and "-" not in v):
                continue
            if r["e"] == "view":
                row(v)["views"] += r["n"]
            elif r["e"] == "roster":
                row(v)["rosters"] += r["n"]
            elif r["e"] == "checkout":
                row(v)["presses"] += r["n"]
    if money is not None:
        for v, n in money["by_channel"].items():
            if v in by or (v != stats.NO_VIA and "-" in v):
                row(v)["paid"] += n
    for r in daily or ():
        v = r.get("v") or ""
        if v in by and not by[v]["logged"] and r["e"] == "view":
            if by[v]["day"] is None or r["day"] < by[v]["day"]:
                by[v]["day"] = r["day"]
    rows = list(by.values())
    rows.sort(key=lambda r: (r["day"] or "", r["tag"]), reverse=True)
    return rows


NET_PER_PASS_PRICE = 29.00      # the pass a break-even is counted in


def net_per_pass() -> float:
    from run.economics import stripe_fee
    return NET_PER_PASS_PRICE - stripe_fee(NET_PER_PASS_PRICE, one_time=True)


def profit_metrics(books: Source, money: dict | None, period: str, now: datetime) -> dict | None:
    """Net revenue less the costs charged in the period, the hours logged in
    it, and a cumulative-profit line. Costs and hours count by Eastern date,
    the date you'd write on them."""
    if not books.ok:
        return None
    from run.books import charges, spent
    b = books.data
    today = now.astimezone(ET).date()
    days = period_days(period)
    start = today - timedelta(days=days) if days else None
    costs = spent(b.costs, start, today)
    hours = round(sum(x.hours for x in b.hours if x.day <= today and (start is None or x.day > start)), 2)
    net = money["net"] if money is not None else None
    profit = round(net - costs, 2) if net is not None else None
    prev = None
    if days and money is not None and money.get("prev_net") is not None:
        prev_costs = spent(b.costs, start - timedelta(days=days), start)
        prev = round(money["prev_net"] - prev_costs, 2)
    span = max(days or 90, 14)
    spark_days = [(today - timedelta(days=i)) for i in range(span - 1, -1, -1)]
    per_day: Counter = Counter()
    for c in b.costs:
        for d in charges(c, today):
            per_day[d] += c.amount
    net_days = money["spark_net"] if money is not None and len(money["spark_net"]) == span else [0] * span
    running, line = 0.0, []
    for i, d in enumerate(spark_days):
        running += net_days[i] - per_day.get(d, 0)
        line.append(round(running, 2))
    return {"costs": costs, "net": net, "profit": profit, "prev": prev, "hours": hours,
            "per_hour": (profit / hours) if profit is not None and hours else None,
            "spark": line}


def metrics_for(sources: Mapping[str, Source], period: str, now: datetime) -> Metrics:
    m = Metrics(period, period_days(period))
    m.traffic = traffic_metrics(sources["traffic"], period, now)
    m.money = money_metrics(sources["stripe"], period, now)
    m.forms = forms_metrics(sources["forms"], period, now)
    m.funnel = funnel_steps(m.traffic, m.money)
    m.channels = channel_rows(m.traffic, m.money)
    daily = sources["traffic"].data["daily"] if sources["traffic"].ok else None
    books = sources.get("books") or off("books", "Not read this time.")
    m.posts = post_rows(m.traffic, m.money, books, daily)
    m.profit = profit_metrics(books, m.money, period, now)
    return m


def ledger_view(src: Source, now: datetime) -> dict | None:
    if not src.ok:
        return None
    calls = src.data["calls"]
    graded = [c for c in calls if c["status"] == "graded"]
    decided = [c for c in graded if c["outcome"] in ("hit", "miss")]
    bands = []
    for low, high in ((0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 1.01)):
        rows = [c for c in decided if low <= c["confidence"] < high]
        if rows:
            bands.append({"label": f"{low:.0%}–{min(high, 1.0):.0%}", "n": len(rows),
                          "stated": sum(c["confidence"] for c in rows) / len(rows),
                          "observed": sum(c["outcome"] == "hit" for c in rows) / len(rows)})
    weeks = defaultdict(lambda: {"calls": 0, "hits": 0, "misses": 0, "pending": 0, "void": 0})
    for c in calls:
        w = weeks[c["week"]]
        w["calls"] += 1
        if c["status"] == "pending":
            w["pending"] += 1
        elif c["status"] == "void" or c["outcome"] not in ("hit", "miss"):
            w["void"] += 1
        else:
            w["hits" if c["outcome"] == "hit" else "misses"] += 1
    stale = [c for c in calls if c["status"] == "pending"
             and (_ts(c.get("recorded_at")) or now) < now - timedelta(days=16)]
    hits = sum(c["outcome"] == "hit" for c in decided)
    return {"season": src.data["season"], "recorded": len(calls), "graded": len(graded),
            "pending": sum(c["status"] == "pending" for c in calls),
            "hits": hits, "misses": len(decided) - hits,
            "hit_rate": hits / len(decided) if decided else None,
            "stated": (sum(c["confidence"] for c in decided) / len(decided)) if decided else None,
            "bands": bands, "weeks": dict(sorted(weeks.items())),
            "stores": sorted({c["store"] for c in calls}), "stale": len(stale),
            "unreadable": src.data["unreadable"]}


# --------------------------------------------------------------------- #
# issues and insights
# --------------------------------------------------------------------- #

SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Issue:
    severity: str
    title: str                  # one plain sentence: what is wrong
    fix: str | tuple[str, ...]  # the "do this": one line, or short numbered steps
    link: str = ""
    area: str = ""
    ref: str = ""               # the LAUNCH.md section that explains it (a key of LAUNCH_REFS)


LAUNCH_URL = f"https://github.com/{GITHUB_REPO}/blob/main/LAUNCH.md"
LAUNCH_REFS = {
    "§8": ("LAUNCH.md §8", f"{LAUNCH_URL}#8-every-week-from-here"),
    "5.8": ("LAUNCH.md step 5", f"{LAUNCH_URL}#5-the-form-worker-25-min--do-this-first"),
    "5b": ("LAUNCH.md step 5b", f"{LAUNCH_URL}#5b-the-page-counter-10-min-right-after-step-5"),
    "weekend": ("LAUNCH.md “This weekend”", f"{LAUNCH_URL}#this-weekend-in-order"),
}


def _gh_when(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def last_slot(crons: list[str], now: datetime, grace: timedelta) -> datetime | None:
    """The slot a run must have started after, ``grace`` ago: on a day with
    one or two slots (Tuesday's 12:17 plus its retry) the day's FIRST one —
    the retry is a backup, and one run that day is the day's run; for an
    hourly workflow the newest slot."""
    from run.launch_check import _cron_fires
    cutoff = now - grace
    for back in range(0, 9):
        day = (cutoff - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        every = sorted(t for cron in crons for t in _cron_fires(cron, day))
        fires = [t for t in every if t <= cutoff]
        if fires:
            return max(fires) if len(every) > 2 else fires[0]
    return None


def workflow_health(src: Source, now: datetime, root: Path = REPO_ROOT) -> list[dict]:
    """Per workflow: the last run, its outcome, and whether a scheduled slot
    passed with no run after it."""
    if not src.ok:
        return []
    from run.launch_check import first_start_delays
    out = []
    for name, info in src.data.items():
        runs = sorted(info["runs"], key=lambda r: r["created_at"], reverse=True)
        last = runs[0] if runs else None
        crons = []
        path = root / ".github" / "workflows" / name
        if path.is_file():
            crons = re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M)
        grace = timedelta(hours=3) if name == "daily.yml" else timedelta(hours=2)
        slot = last_slot(crons, now, grace) if crons else None
        missing = bool(slot and not any((_gh_when(r["created_at"]) or now) >= slot - timedelta(minutes=10)
                                        for r in runs))
        completed = [r for r in runs if r["status"] == "completed"]
        late = None
        if name in ("weekly.yml", "saturday.yml") and crons:
            starts = [t for t in (_gh_when(r["created_at"]) for r in runs
                                  if r["event"] in ("schedule", "workflow_dispatch")) if t]
            delays = first_start_delays(starts, crons)
            late = delays[0] if delays else None
        out.append({"file": name, "label": info["label"], "last": last,
                    "last_done": completed[0] if completed else None,
                    "slot": slot, "missing": missing, "late": late,
                    "fails": sum(r["conclusion"] == "failure" for r in completed[:10]),
                    "recent": [r["conclusion"] or r["status"] for r in completed[:12]]})
    return out


def _age(stamp: Any, now: datetime) -> timedelta | None:
    when = _ts(stamp)
    return now - when if when else None


def build_issues(sources: Mapping[str, Source], now: datetime, health: list[dict],
                 ledger: dict | None, metrics: Metrics) -> list[Issue]:
    issues: list[Issue] = []
    actions = f"https://github.com/{GITHUB_REPO}/actions"

    if sources["intake"].ok:
        for problem in sources["intake"].data["problems"]:
            session = re.search(r"\b(cs_[A-Za-z0-9_]+)", problem)
            sid = f" (session {session.group(1)})" if session else ""
            if problem.startswith("PAID-UNATTRIBUTED"):
                issues.append(Issue(
                    "critical", f"Somebody paid and the intake can't tie it to a roster or plan{sid}.",
                    ("Find the session in Stripe → Payments.",
                     "A link missing from STRIPE_PAYMENT_LINKS: add it to the secret. "
                     "Anything else: refund in full.",
                     "Actions → daily-intake → Run workflow, ticking “Forget the payments "
                     "already dealt with”."),
                    "https://dashboard.stripe.com/payments", "Payments", "§8"))
            elif problem.startswith("PLAYOFF-EARLY"):
                issues.append(Issue(
                    "high", f"A $19 Playoff Pass was bought before it went on sale{sid}.",
                    ("Stripe → Payment links: deactivate the $19 link if it's on.",
                     "Keep serving the buyer (recommended) or refund in full.",
                     "Actions → daily-intake → Run workflow, ticking “Forget the payments "
                     "already dealt with”."),
                    "https://dashboard.stripe.com/payment-links", "Payments", "§8"))
            else:
                issues.append(Issue("medium", problem.rstrip(".") + ".",
                                    "Read it in the hourly run's log and resolve by hand.",
                                    actions, "Payments"))

    if sources["stripe"].ok:
        for s in sources["stripe"].data["sessions"]:
            state = s.get("dispute")
            ref = s.get("payment") or s.get("id")
            if state in ("needs_response", "warning_needs_response"):
                issues.append(Issue(
                    "critical", f"A chargeback on {ref} needs your response before Stripe's deadline.",
                    ("Check the send log for what they received; if a send of ours failed, accept it.",
                     "Otherwise Stripe → Disputes → Submit evidence: the consent record, the terms, "
                     "the send-log lines.",
                     "Never refund it as well."),
                    "https://dashboard.stripe.com/disputes", "Payments", "§8"))
            elif state == "unknown":
                issues.append(Issue(
                    "high", f"Payment {ref} is disputed and its status could not be read.",
                    "Open it in Stripe → Disputes and check the deadline.",
                    "https://dashboard.stripe.com/disputes", "Payments"))
            elif state in ("under_review", "warning_under_review"):
                issues.append(Issue("low", f"The dispute on {ref} is under review.",
                                    "Nothing to do until Stripe decides.",
                                    "https://dashboard.stripe.com/disputes", "Payments"))

    if sources["bounces"].ok and sources["bounces"].data["paid"]:
        n = len(sources["bounces"].data["paid"])
        issues.append(Issue(
            "high", f"{n} email{'s' if n != 1 else ''} somebody paid for bounced or was marked spam "
                    f"in the last 48 hours.",
            "Resend → Emails → filter Bounced; ask the buyer for a working address by another route.",
            "https://resend.com/emails", "Email"))

    for wf in health:
        last = wf["last_done"]
        link = (wf["last"] or {}).get("url") or actions
        if wf["missing"] and wf["slot"]:
            slot = wf["slot"].astimezone(ET)
            issues.append(Issue(
                "high" if wf["file"] in ("weekly.yml", "daily.yml", "saturday.yml") else "medium",
                f"{wf['label']} didn't run after its {slot:%a %-I:%M %p} ET slot.",
                ("Actions → the workflow → Run workflow (Tuesday's: only before the week's "
                 "first kickoff).",
                 "Check the Worker's Cron Trigger."),
                actions, "Crons", "5.8"))
        if last and last["conclusion"] == "failure":
            sev = ("high" if wf["file"] in ("weekly.yml", "daily.yml", "saturday.yml", "pages.yml")
                   else "medium")
            issues.append(Issue(sev, f"The last {wf['label'].lower()} run failed.",
                                "Open the run's log and match the red message to its fix.",
                                link, "Crons", "§8"))
        if wf["late"] and wf["late"][1] > timedelta(minutes=60):
            minutes = int(wf["late"][1].total_seconds() // 60)
            issues.append(Issue("low", f"{wf['label']} started {minutes} minutes after its slot last time.",
                                "Set the Worker's Cron Trigger so it starts on time.",
                                actions, "Crons", "5.8"))
    if sources["github"].status == "error":
        issues.append(Issue("low", "GitHub's Actions record could not be read this time.",
                            "Check the network and run make dashboard again.", actions, "Crons"))

    if sources["launch"].ok:
        gates = sources["launch"].data["gates"]
        for g in gates:
            if g["status"] == "FAIL":
                issues.append(Issue("high", f"Launch check fails: {g['name'].rstrip('.')}.",
                                    (g["detail"] or "Run make launch-check for detail.")[:240],
                                    "", "Launch check"))
        owner = [g for g in gates if g["status"] == "OWNER"]
        if owner:
            first = owner[0]["name"].rstrip(".")
            rest = len(owner) - 1
            issues.append(Issue("medium", f"{len(owner)} launch step{'s are' if len(owner) != 1 else ' is'} "
                                          f"waiting on you.",
                                (f"Next: {first}.",
                                 (f"Then the other {rest} in the weekend list, and run make launch-check."
                                  if rest else "Then run make launch-check.")),
                                "", "Launch check", "weekend"))
        for g in gates:
            if g["status"] == "WARN":
                issues.append(Issue("low", f"Launch check warns: {g['name'].rstrip('.')}.",
                                    (g["detail"] or "")[:240], "", "Launch check"))

    site = sources["site"].data if sources["site"].ok else None
    if site and site.get("week"):
        age = _age(site["week"].get("built_at"), now)
        if age and age > timedelta(days=8) and site["week"].get("phase", "season") == "season":
            issues.append(Issue("medium", f"This week's sample page is {age.days} days old.",
                                "Actions → weekly-report → Run workflow (before the week's first kickoff).",
                                actions, "Site"))
    if site and site.get("players_at"):
        age = _age(site["players_at"], now)
        if age and age > timedelta(days=8):
            issues.append(Issue("medium", f"The player directory the join page uses is {age.days} days old.",
                                "It's rebuilt by the Tuesday run — check weekly-report is green, then git pull.",
                                actions, "Site"))

    if ledger:
        for broken in ledger["unreadable"]:
            issues.append(Issue("high", f"A ledger store can't be read ({broken}).",
                                "Look for a merge leftover in data/processed/ledger; the Monday run "
                                "goes red until it's fixed.", "", "Record"))
        if ledger["stale"]:
            issues.append(Issue("medium", f"{ledger['stale']} recorded call(s) are still pending more "
                                          f"than two weeks on.",
                                "Check the monday-receipts log for the week whose box scores never landed.",
                                actions, "Record"))

    t = metrics.traffic
    if sources["traffic"].ok and t is not None and t["views"] == 0 and metrics.period == "7d":
        issues.append(Issue("medium", "The page counter is on but recorded nothing in 7 days.",
                            "Check the Worker's COUNTS binding (item 2).",
                            "https://dash.cloudflare.com/", "Traffic", "5b"))

    plan = sources["plan"].data if sources["plan"].ok else None
    money_all = money_metrics(sources["stripe"], "all", now) if sources["stripe"].ok else None
    if plan and money_all and money_all["count"] >= MIN_REFUND_SAMPLE:
        red = plan_threshold(plan, "Refund rate", "red")
        if red is not None and money_all["refund_rate"] is not None \
                and money_all["refund_rate"] * 100 >= red:
            issues.append(Issue("high", f"The refund rate is {money_all['refund_rate']:.0%}, at or above "
                                        f"PLAN §6's red line of {red:g}%.",
                                "PLAN §6 says: talk to every refunder before another selling hour.",
                                "", "Money"))
    if sources["books"].ok:
        for problem in sources["books"].data.problems[:5]:
            issues.append(Issue("low", problem, "Open the file in a text editor and fix or delete that "
                                                "line; the rest of the file still counts.", "", "Books"))
    issues.sort(key=lambda i: SEVERITY[i.severity])
    return issues


def plan_threshold(plan: dict, metric_word: str, column: str) -> float | None:
    """A number from PLAN §6's own table cell (≥15%, <10, ≤15%), or None."""
    for g in plan["gates"]:
        if metric_word.lower() in g["metric"].lower():
            found = re.search(r"([≥≤<>])\s*(\d+(?:\.\d+)?)", g[column])
            return float(found.group(2)) if found else None
    return None


@dataclass
class Insight:
    tone: str           # good | warn | info
    text: str           # one plain sentence, with its numbers
    action: str         # the do-this step
    basis: str          # what it rests on


def build_insights(sources: Mapping[str, Source], m: Metrics, now: datetime,
                   ftp: tuple[int, int, int] | None, ledger: dict | None) -> list[Insight]:
    out: list[Insight] = []
    t, money, forms = m.traffic, m.money, m.forms
    span = "this period" if m.days is None else f"the last {m.days} days"
    if t is not None:
        if t["landing"] < MIN_FUNNEL_VIEWS:
            need = MIN_FUNNEL_VIEWS - t["landing"]
            out.append(Insight("info", f"Not enough traffic for a reliable funnel read yet: "
                                       f"{t['landing']} landing views in {span}.",
                               f"About {need} more landing views and the biggest drop-off shows here.",
                               f"{t['landing']} landing views; floor {MIN_FUNNEL_VIEWS}"))
        else:
            steps = [(a, b) for a, b in zip(m.funnel, m.funnel[1:]) if a[1] and b[1] is not None]
            if steps:
                worst = min(steps, key=lambda ab: ab[1][1] / ab[0][1])
                (la, na), (lb, nb) = worst
                out.append(Insight(
                    "warn", f"The biggest drop is {la.lower()} → {lb.lower()}: only "
                            f"{nb / na:.0%} continue ({nb:,} of {na:,}).",
                    STEP_ADVICE.get(lb, "Look at what that page asks of a visitor."),
                    f"step counts, {span}"))
        ranked = [c for c in m.channels if c["channel"] != stats.NO_VIA
                  and c["views"] >= MIN_CHANNEL_VIEWS]
        if ranked:
            # One yardstick for every channel: purchases when any channel has
            # one, otherwise buy presses — never a mix of the two.
            by_paid = money is not None and any(c["paid"] for c in ranked)
            field_ = "paid" if by_paid else "presses"

            def rate(c):
                return c[field_] / c["views"]
            best = max(ranked, key=lambda c: (rate(c), c["views"]))
            unit = "purchases" if by_paid else "buy presses"
            n = best[field_]
            out.append(Insight("good", f"“{best['channel']}” converts best: {n} {unit} from "
                                       f"{best['views']:,} views ({rate(best):.1%}).",
                               "Put this week's selling hours into that channel first.",
                               f"channels with ≥{MIN_CHANNEL_VIEWS} views, {span}"))
        elif t["views"]:
            out.append(Insight("info", "No ?via= channel has enough views to compare yet.",
                               "Tag every link you post (…/?via=reddit) so each channel gets credit.",
                               f"channels need ≥{MIN_CHANNEL_VIEWS} views each"))
        rows = t["rows"]
        content = Counter()
        for r in rows:
            if r["e"] == "view" and r["p"] in ("sample", "this-week", "how-it-works", "first-week"):
                content[r["p"]] += r["n"]
        if content and t["buy_views"] < sum(content.values()) * 0.25 and sum(content.values()) >= 50:
            page, n = content.most_common(1)[0]
            out.append(Insight("warn", f"Visitors read the {PAGE_NAMES.get(page, page)} page "
                                       f"({n:,} views) far more than they open the buy page "
                                       f"({t['buy_views']:,}).",
                               "Make that page's call to action the next obvious step.",
                               f"page views, {span} (cookieless: counts, not paths)"))
        if t["planner_views"] >= 30:
            r = t["planner_rosters"] / t["planner_views"]
            out.append(Insight("info", f"The bye planner: {t['planner_views']:,} views, "
                                       f"{t['planner_rosters']:,} rosters checked ({r:.0%}), "
                                       f"{t['planner_waitlist']:,} waitlist joins.",
                               "If check rate is low, shorten the planner's first screen.",
                               f"planner events, {span}"))
        phone = sum(r["n"] for r in rows if r["e"] == "view" and r["d"] == "m")
        desk = sum(r["n"] for r in rows if r["e"] == "view" and r["d"] == "d")
        rp = sum(r["n"] for r in rows if r["e"] == "roster" and r["d"] == "m")
        rd = sum(r["n"] for r in rows if r["e"] == "roster" and r["d"] == "d")
        if phone >= 50 and desk >= 50:
            a, b = rp / phone, rd / desk
            if a < b * 0.6:
                out.append(Insight("warn", f"Phones check rosters at {a:.1%} of views against "
                                           f"{b:.1%} on desktop, on {phone / (phone + desk):.0%} "
                                           f"of the traffic.",
                                   "Try pasting a roster on your own phone and fix what's awkward.",
                                   f"{phone:,} phone and {desk:,} desktop views, {span}"))
        if t.get("views_delta") is not None and not math.isinf(t["views_delta"]) and t["views"] >= 50:
            d = t["views_delta"]
            out.append(Insight("good" if d >= 0 else "warn",
                               f"Page views are {'up' if d >= 0 else 'down'} {abs(d):.0%} on the "
                               f"previous {m.days} days ({t['views']:,} now).",
                               "Match the change to what you posted, so you know what moved it."
                               if d >= 0 else "Check whether a channel you relied on went quiet.",
                               "daily page views"))
    if money is not None and t is not None and t["landing"] >= MIN_FUNNEL_VIEWS and money["count"]:
        per = money["count"] / t["landing"] * 100
        out.append(Insight("info", f"{per:.1f} purchases per 100 landing views "
                                   f"({money['count']} from {t['landing']:,}).",
                           "Use this as the baseline to judge a page change against.",
                           f"Stripe and the counter, {span}"))
    if money is not None and money["count"] >= MIN_REFUND_SAMPLE:
        rate = money["refund_rate"] or 0
        plan = sources["plan"].data if sources["plan"].ok else None
        green = plan_threshold(plan, "Refund rate", "green") if plan else None
        if green is not None:
            out.append(Insight("good" if rate * 100 <= green else "warn",
                               f"Refund rate {rate:.0%} ({money['full_refunds']} of {money['count']}) "
                               f"against PLAN §6's green line of ≤{green:g}%.",
                               "Read every refund reason; the first weekly report is the moment to win."
                               if rate * 100 > green else "Keep the first weekly report strong.",
                               f"full refunds, {span}"))
    elif money is not None and money["count"]:
        out.append(Insight("info", f"Only {money['count']} purchase(s) in {span} — too few to "
                                   f"read a refund rate.",
                           f"Wait for {MIN_REFUND_SAMPLE} before judging it.",
                           f"floor {MIN_REFUND_SAMPLE} purchases"))
    if ftp is not None and m.period == "all":
        paid, judged, young = ftp
        if judged >= 10:
            out.append(Insight("info", f"{paid} of {judged} free-report requesters bought within "
                                       f"{FREE_TO_PAID_DAYS} days ({paid / judged:.0%}).",
                               "Follow up with a one-line nudge at day 3 if this is low.",
                               f"{young} newer requests not judged yet"))
    if forms is not None and forms["waitlist"]["total"] and m.days:
        w = forms["waitlist"]
        out.append(Insight("info", f"{w['period']} waitlist sign-ups in {span}, "
                                   f"{w['people']:,} people on the list.",
                           "When checkout opens, make waitlist-send MAX=<n> sends the one launch email.",
                           "form Worker rows"))
    if ledger and ledger["hit_rate"] is not None and m.period == "all":
        n = ledger["hits"] + ledger["misses"]
        out.append(Insight("info", f"This season's published calls: {ledger['hits']} of {n} hit "
                                   f"({ledger['hit_rate']:.0%}) at an average stated "
                                   f"{ledger['stated']:.0%}"
                                   + (" — too few to judge calibration." if n < 50 else "."),
                           "Owner view only: selling pages never quote the record.",
                           "data/processed/ledger"))
    posts = [r for r in m.posts if r["views"] >= MIN_CHANNEL_VIEWS]
    if posts and t is not None:
        by_paid = money is not None and any(r["paid"] for r in posts)
        key = "paid" if by_paid else "presses"
        best = max(posts, key=lambda r: (r[key] / r["views"], r["views"]))
        if best[key]:
            unit = "purchases" if by_paid else "buy presses"
            out.append(Insight("good", f"Your best post is {best['tag']}"
                                       + (f" ({best['where']})" if best["where"] else "")
                                       + f": {best[key]} {unit} from {best['views']:,} views.",
                               "Post the same way again in that place, with a new tag so you can compare.",
                               f"posts with ≥{MIN_CHANNEL_VIEWS} views, {span}"))
    pr = m.profit
    if pr is not None and pr["profit"] is not None and m.period == "all" and pr["costs"]:
        if pr["profit"] < 0:
            need = math.ceil(-pr["profit"] / net_per_pass())
            out.append(Insight("warn" if money and money["count"] >= MIN_REFUND_SAMPLE else "info",
                               f"Still {money_fmt(-pr['profit'], True)} short of covering costs: "
                               f"{need} more $29 pass{'es' if need != 1 else ''} breaks even.",
                               "Hold off new costs until sales cover the ones you have.",
                               "Stripe net revenue and data/costs.csv"))
        else:
            out.append(Insight("good", f"Costs are covered: {money_fmt(pr['profit'], True)} profit so far.",
                               "Every pass from here is profit after Stripe's fee.",
                               "Stripe net revenue and data/costs.csv"))
    order = {"warn": 0, "good": 1, "info": 2}
    out.sort(key=lambda i: order[i.tone])
    return out


STEP_ADVICE = {
    "Buy-page views": "The landing isn't sending people on: make the hero button the one obvious step.",
    "Rosters checked": "People reach the buy page but don't paste a roster: shorten or explain that step.",
    "Buy pressed": "Rosters check out but few press buy: look at price clarity and the terms line.",
    "Paid": "Buy presses don't become payments: test the Stripe page on a phone.",
}
PAGE_NAMES = {"index": "landing", "join": "buy", "join-pass": "League Pass buy",
              "join-try": "free report", "sample": "sample report", "this-week": "this week's sample",
              "how-it-works": "how-it-works", "first-week": "first-week sample",
              "planner": "bye planner", "league-pass": "League Pass", "thanks": "thanks",
              "other": "other", "404": "not-found"}


# --------------------------------------------------------------------- #
# rendering helpers
# --------------------------------------------------------------------- #

def h(value: object) -> str:
    return _html.escape(str(value), quote=True)


def num(n: float | int | None) -> str:
    if n is None:
        return "—"
    n = float(n)
    if abs(n) >= 10_000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return f"{n:,.0f}"


def money_fmt(n: float | None, cents: bool = False) -> str:
    if n is None:
        return "—"
    sign = "−" if n < 0 else ""
    return f"{sign}${abs(n):,.2f}" if cents or abs(n) < 100 else f"{sign}${abs(n):,.0f}"


def pct(n: float | None, digits: int = 0) -> str:
    return "—" if n is None else f"{n * 100:.{digits}f}%"


def nice_max(v: float) -> float:
    if v <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(v))
    for step in (1, 2, 2.5, 5, 10):
        if v <= step * exp:
            return step * exp
    return 10 * exp


def nice_ticks(v: float) -> tuple[float, float]:
    """(top, step): a 1/2/5 step giving three to six round gridlines."""
    if v <= 6:
        return float(max(3, math.ceil(v))), 1.0
    for exp in range(int(math.floor(math.log10(v))) - 1, int(math.log10(v)) + 2):
        for base in (1, 2, 5):
            step = base * 10 ** exp
            if step < 1:
                continue
            count = math.ceil(v / step)
            if 3 <= count <= 6:
                return count * step, step
    top = nice_max(v)
    return top, top / 4


def delta_chip(d: float | None, good_up: bool = True, points: bool = False, label: str = "") -> str:
    if d is None:
        return f'<span class="delta flat">{h(label) if label else "no prior period"}</span>'
    if math.isinf(d):
        return '<span class="delta new" title="nothing in the previous period">New</span>'
    if abs(d) < 0.005:
        return '<span class="delta flat">— flat</span>'
    up = d > 0
    good = up == good_up
    text = f"{abs(d) * 100:.1f} pts" if points else f"{abs(d):.0%}"
    arrow = "↑" if up else "↓"
    return (f'<span class="delta {"good" if good else "bad"}" title="vs the previous period">'
            f'<span aria-hidden="true">{arrow}</span> {text}</span>')


def money_chip(cur: float | None, prev: float | None) -> str:
    """Change in dollars: a percentage of a profit that crossed zero means
    nothing, a dollar figure always does."""
    if cur is None or prev is None:
        return '<span class="delta flat">no prior period</span>'
    d = cur - prev
    if abs(d) < 0.5:
        return '<span class="delta flat">— flat</span>'
    arrow = "↑" if d > 0 else "↓"
    return (f'<span class="delta {"good" if d > 0 else "bad"}" title="vs the previous period">'
            f'<span aria-hidden="true">{arrow}</span> {money_fmt(abs(d))}</span>')


def weekly_buckets(values: list[float]) -> list[float]:
    """Seven-day sums counted back from the newest day, oldest first."""
    out = []
    for end in range(len(values), 0, -7):
        out.append(sum(values[max(0, end - 7):end]))
    return out[::-1]


def spark(values: list[float], klass: str = "spark") -> str:
    # A sparse daily series (a sale every few days) reads as spiky noise; in
    # weekly buckets it reads as the trend it is.
    if len(values) >= 14 and sum(1 for v in values if not v) > len(values) * .4:
        values = weekly_buckets(values)
    elif len(values) >= 14:
        values = [sum(values[max(0, i - 1):i + 2]) / len(values[max(0, i - 1):i + 2])
                  for i in range(len(values))]
    if not values or max(values) <= 0:
        return f'<svg class="{klass} empty" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="28" x2="100" y2="28"/></svg>'
    top = max(values)
    n = len(values)
    pts = [(i / (n - 1) * 100 if n > 1 else 50, 28 - v / top * 24) for i, v in enumerate(values)]
    line = smooth_path(pts)
    area = f"{line} L100,30 L0,30 Z"
    gid = f"sg{next(_GRADIENT_IDS)}"
    return (f'<svg class="{klass}" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">'
            f'{gradient(gid)}<path class="a" fill="url(#{gid})" d="{area}"/><path class="l" d="{line}"/></svg>')


_GRADIENT_IDS = itertools.count(1)


def gradient(gid: str) -> str:
    """A vertical wash of the series colour, strong at the line and gone at
    the baseline. Colours come from CSS, so it follows the theme."""
    return (f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" class="g0"/><stop offset="1" class="g1"/></linearGradient></defs>')


def smooth_path(pts: list[tuple[float, float]]) -> str:
    """A monotone cubic through the points (Fritsch–Carlson): smooth, and
    never overshooting below zero or above a peak the data didn't reach."""
    if len(pts) < 3:
        return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    n = len(pts)
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    sl = [(ys[i + 1] - ys[i]) / dx[i] if dx[i] else 0 for i in range(n - 1)]
    m = [sl[0]] + [0.0] * (n - 2) + [sl[-1]]
    for i in range(1, n - 1):
        m[i] = 0.0 if sl[i - 1] * sl[i] <= 0 else (sl[i - 1] + sl[i]) / 2
    for i in range(n - 1):
        if sl[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / sl[i], m[i + 1] / sl[i]
        s = a * a + b * b
        if s > 9:
            t = 3 / math.sqrt(s)
            m[i], m[i + 1] = t * a * sl[i], t * b * sl[i]
    d = [f"M{xs[0]:.2f},{ys[0]:.2f}"]
    for i in range(n - 1):
        c1 = (xs[i] + dx[i] / 3, ys[i] + m[i] * dx[i] / 3)
        c2 = (xs[i + 1] - dx[i] / 3, ys[i + 1] - m[i + 1] * dx[i] / 3)
        d.append(f"C{c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} {xs[i + 1]:.2f},{ys[i + 1]:.2f}")
    return " ".join(d)


def short_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


def area_chart(cid: str, days: list[str], values: list[int], extras: list[tuple[str, list[int]]],
               label: str, marks: list[tuple[str, str]] | None = None) -> str:
    top, step = nice_ticks(max(values) if values else 0)
    n = len(values)
    pts = [(i / (n - 1) * 100 if n > 1 else 50, 100 - v / top * 100) for i, v in enumerate(values)]
    line = smooth_path(pts)
    levels = [k * step for k in range(int(round(top / step)) + 1)]
    grid = "".join(f'<line x1="0" x2="100" y1="{100 - lv / top * 100:.2f}" y2="{100 - lv / top * 100:.2f}"/>'
                   for lv in levels if lv)
    ylabels = "".join(f'<span style="top:{100 - lv / top * 100:.2f}%">{num(lv)}</span>' for lv in levels)
    ticks = sorted({0, n - 1, *range(0, n, max(1, n // 6))})
    if len(ticks) > 2 and ticks[-1] - ticks[-2] < max(1, n // 7):
        ticks.pop(-2)
    xlabels = "".join(f'<span style="left:{(i / (n - 1) * 100) if n > 1 else 50:.2f}%">'
                      f'{h(short_day(days[i]))}</span>' for i in ticks)
    tips = [{"d": f"{date.fromisoformat(d):%a %b} {date.fromisoformat(d).day}", "v": values[i],
             "x": [[name, series[i]] for name, series in extras]} for i, d in enumerate(days)]
    payload = h(json.dumps({"label": label, "tips": tips, "top": top}, separators=(",", ":")))
    total = sum(values)
    peak = max(range(n), key=lambda i: values[i]) if n and total else None
    peak_note = (f"Peak {num(values[peak])} on {short_day(days[peak])}" if peak is not None else
                 "No views recorded")
    return (f'<figure class="area" id="{cid}" data-chart="{payload}">'
            f'<figcaption class="sr">{h(label)}: {num(total)} in total. {h(peak_note)}.</figcaption>'
            f'<div class="yaxis" aria-hidden="true">{ylabels}</div>'
            f'<div class="plot" tabindex="0" role="img" aria-label="{h(label)}">'
            f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
            f'{gradient("ag-" + cid)}<g class="grid">{grid}</g><path class="fill" fill="url(#ag-{cid})" d="{line} L100,100 L0,100 Z"/>'
            f'<path class="line" d="{line}"/><line class="base" x1="0" x2="100" y1="100" y2="100"/></svg>'
            f'{post_marks(days, marks or [])}'
            f'<div class="xhair" hidden></div><div class="hdot" hidden></div>'
            f'<div class="tip" role="status" hidden></div></div>'
            f'<div class="xaxis" aria-hidden="true">{xlabels}</div></figure>')


def post_marks(days: list[str], marks: list[tuple[str, str]]) -> str:
    """A thin gold rule and a pin at each day a post went out, so a spike
    sits next to the post that caused it."""
    n = len(days)
    index = {d: i for i, d in enumerate(days)}
    by_day: dict[str, list[str]] = defaultdict(list)
    for day, label in marks:
        if day in index:
            by_day[day].append(label)
    out = []
    for day, labels in sorted(by_day.items()):
        x = index[day] / (n - 1) * 100 if n > 1 else 50
        text = f"Posted {short_day(day)}: " + ", ".join(labels)
        out.append(f'<span class="pmark" style="left:{x:.2f}%" title="{h(text)}">'
                   f'<span class="sr">{h(text)}</span></span>')
    return "".join(out)


def column_chart(days: list[str], values: list[float], unit: str, money_vals: bool = False,
                 labels: list[str] | None = None) -> str:
    top, _step = nice_ticks(max(values) if values else 0)
    n = len(values)
    bars = []
    for i, v in enumerate(values):
        lab = labels[i] if labels else short_day(days[i])
        val = money_fmt(v, True) if money_vals else f"{num(v)} {unit}"
        bars.append(f'<div class="col" tabindex="0" data-tip="{h(lab)} · {h(val)}">'
                    f'<i style="height:{max(v / top * 100, 0 if v == 0 else 3):.1f}%"></i></div>')
    every = max(1, n // 6)
    xl = "".join(f'<span style="left:{(i + .5) / n * 100:.2f}%">'
                 f'{h(labels[i] if labels else short_day(days[i]))}</span>'
                 for i in range(0, n, every))
    return (f'<div class="cols"><div class="yax"><span>{num(top)}</span><span>0</span></div>'
            f'<div class="colplot">{"".join(bars)}</div><div class="colx">{xl}</div></div>')


def bar_list(title: str, unit: str, items: list[tuple[str, int]], empty: str, limit: int = 8,
             note: str = "") -> str:
    if not items:
        body = f'<p class="muted small pad">{h(empty)}</p>'
    else:
        top = max(n for _l, n in items) or 1
        total = sum(n for _l, n in items) or 1
        rows = "".join(
            f'<li><span class="bar" style="width:{n / top * 100:.1f}%"></span>'
            f'<span class="lab" title="{h(lab)}">{h(lab)}</span>'
            f'<span class="val">{num(n)}<em>{n / total:.0%}</em></span></li>'
            for lab, n in items[:limit])
        more = (f'<p class="more">+ {len(items) - limit} more</p>' if len(items) > limit else "")
        body = f'<ul class="bars">{rows}</ul>{more}'
    foot = f'<p class="note">{h(note)}</p>' if note else ""
    return (f'<div class="card barcard"><div class="cardhead"><h3>{h(title)}</h3>'
            f'<span class="unit">{h(unit)}</span></div>{body}{foot}</div>')


ICONS = {
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/>',
    "alert": '<path d="M12 3 2 21h20zM12 10v5M12 18v.01"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "up": '<path d="M4 16l6-6 4 4 6-7M14 7h6v6"/>',
    "down": '<path d="M4 8l6 6 4-4 6 7M14 17h6v-6"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "ext": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
}


def icon(name: str, klass: str = "ic") -> str:
    return (f'<svg class="{klass}" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICONS[name]}</svg>')


def setup_card(src: Source, compact: bool = False) -> str:
    """The friendly empty state: what's missing, how to connect it, what the
    panel will show once data arrives."""
    if src.status == "error":
        return (f'<div class="empty err{" compact" if compact else ""}">{icon("alert", "eic")}'
                f'<div><p class="et">{h(src.label)} couldn\'t be read</p>'
                f'<p class="ed">{h(src.note)}</p>'
                f'<p class="es">Shows: {h(src.shows)}</p></div></div>')
    return (f'<div class="empty{" compact" if compact else ""}">{icon("plug", "eic")}'
            f'<div><p class="et">{h(src.label)} — '
            f'{"nothing recorded yet" if src.key == "books" else "not connected yet"}</p>'
            f'<p class="ed">{h(src.note)}</p>'
            f'<p class="es"><b>Set up:</b> {h(src.setup)}</p>'
            f'<p class="es">Once connected: {h(src.shows)}</p></div></div>')


def kpi(label: str, value: str, chip: str, sparkline: str, sub: str, hint: str = "",
        missing: Source | None = None, why: str = "") -> str:
    if missing is not None:
        step = re.search(r"step [0-9a-z.]+", missing.setup)
        if not why:
            why = "Not connected" if missing.status == "off" else "Couldn't read"
            why += f" · {step.group(0)}" if step else ""
        return (f'<div class="kpi off"><p class="kl">{h(label)}</p><p class="kval">—</p>'
                f'<p class="ks">{icon("plug", "ic tiny")} {h(why)}</p></div>')
    title = f' title="{h(hint)}"' if hint else ""
    return (f'<div class="kpi"{title}><p class="kl">{h(label)}</p>'
            f'<p class="kval">{value}</p><div class="krow">{chip}<span class="ks">{h(sub)}</span></div>'
            f'{sparkline}</div>')


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

def section(sid: str, title: str, lead: str, body: str, extra: str = "") -> str:
    return (f'<section id="{sid}" class="sec"><header class="sech"><div><h2>{h(title)}</h2>'
            f'<p class="lead">{h(lead)}</p></div>{extra}</header><div class="vs">{body}</div></section>')


def by_period(render_one: Callable[[str], str]) -> str:
    return "".join(f'<div class="pv vs" data-p="{k}">{render_one(k)}</div>' for k, _l, _d in PERIODS)


def prev_label(m: Metrics) -> str:
    return f"vs previous {m.days} days" if m.days else "all time"


def overview(S: Mapping[str, Source], M: Mapping[str, Metrics], sends: dict | None) -> str:
    def one(p: str) -> str:
        m = M[p]
        t, mo, fo = m.traffic, m.money, m.forms
        cards = []
        tr, st, fm = S["traffic"], S["stripe"], S["forms"]
        span_word = "90 days" if p == "all" else f"{m.days} days"
        cards.append(kpi("Page views", num(t["views"]) if t else "",
                         delta_chip(t["views_delta"]) if t else "", spark(t["spark_views"]) if t else "",
                         prev_label(m) if p != "all" else span_word,
                         "Counts page views, never people (privacy §3)",
                         missing=None if t else tr))
        cards.append(kpi("Rosters checked", num(t["rosters"]) if t else "",
                         delta_chip(t["rosters_delta"]) if t else "",
                         spark(t["spark_rosters"]) if t else "",
                         prev_label(m) if p != "all" else span_word, "On the buy page",
                         missing=None if t else tr))
        cards.append(kpi("Buy presses", num(t["presses"]) if t else "",
                         delta_chip(t["presses_delta"]) if t else "",
                         spark(t["spark_presses"]) if t else "",
                         (f"{num(t['presses_open'])} open · {num(t['presses_closed'])} closed"
                          if t else ""), "Checkout open or closed when pressed",
                         missing=None if t else tr))
        cards.append(kpi("Passes sold", num(mo["count"]) if mo else "",
                         delta_chip(mo["count_delta"]) if mo else "", spark(mo["spark"]) if mo else "",
                         prev_label(m), missing=None if mo else st))
        cards.append(kpi("Net revenue", money_fmt(mo["net"]) if mo else "",
                         delta_chip(mo["net_delta"]) if mo else "", spark(mo["spark_net"]) if mo else "",
                         f"{money_fmt(mo['gross'])} gross" if mo else "",
                         "After refunds and Stripe's modelled fee (run/economics.py)",
                         missing=None if mo else st))
        pr = m.profit
        if pr is not None and pr["profit"] is not None:
            cards.append(kpi("Profit", money_fmt(pr["profit"]), money_chip(pr["profit"], pr["prev"])
                             if p != "all" else delta_chip(None, label="all time"),
                             spark(pr["spark"], "spark cumulative"),
                             f"{money_fmt(pr['costs'])} costs",
                             "Net revenue less the costs in data/costs.csv; the line is the running total"))
        elif pr is not None:
            cards.append(kpi("Profit", "", "", "", "", missing=st, why="Needs Stripe for revenue"))
        else:
            cards.append(kpi("Profit", "", "", "", "", missing=S["books"], why="Record costs: make cost"))
        cards.append(kpi("Refund rate", pct(mo["refund_rate"]) if mo else "",
                         delta_chip(mo["refund_delta"], good_up=False, points=True,
                                    label="no earlier sales" if p != "all" else "all time") if mo else "",
                         "", f"{mo['full_refunds']} of {mo['count']} in full" if mo else "",
                         missing=None if mo else st))
        if fo:
            w = fo["waitlist"]
            cards.append(kpi("Waitlist", num(w["people"]),
                             delta_chip(delta(w["period"], w["prev"])) if p != "all" else
                             delta_chip(None, label="people"),
                             spark(fo["waitlist_spark"]),
                             f"+{w['period']} {('in ' + span_word) if p != 'all' else 'ever'}"))
        else:
            cards.append(kpi("Waitlist", "", "", "", "", missing=fm))
        return f'<div class="kpis">{"".join(cards)}</div>'
    return section("overview", "Overview", "The business at a glance for the period you pick.",
                   by_period(one))


def traffic_section(S: Mapping[str, Source], M: Mapping[str, Metrics]) -> str:
    src = S["traffic"]
    if not src.ok:
        return section("traffic", "Traffic", "Where visits come from and what they look at.",
                       setup_card(src))

    from run.books import channel_of

    def one(p: str) -> str:
        t = M[p].traffic
        rows = t["rows"]
        pages = Counter()
        refs = Counter()
        chans = Counter()
        countries = Counter()
        devices = Counter()
        for r in rows:
            if r["e"] != "view":
                continue
            pages[PAGE_NAMES.get(r["p"], r["p"] or "unknown").capitalize()] += r["n"]
            host = r["r"]
            if host != stats.OWN_HOST and not host.endswith("." + stats.OWN_HOST):
                refs[host or "Direct / hidden"] += r["n"]
            chans[channel_of(r["v"]) or "(no tag)"] += r["n"]
            countries[COUNTRY.get(r["c"], r["c"] or "Unknown")] += r["n"]
            devices[{"m": "Phone", "d": "Desktop"}.get(r["d"], "Unknown")] += r["n"]
        span = "last 90 days" if p == "all" else f"last {M[p].days} days"
        marks = [(r["day"], r["tag"]) for r in M["all"].posts if r["day"]]
        chart = area_chart(f"visits-{p}", t["chart_days"], t["chart"],
                           [("Landing", t["chart_landing"]), ("Buy page", t["chart_buy"])],
                           "Page views per day", marks)
        total = sum(devices.values()) or 1
        dev = "".join(f'<span class="dseg s{i}" style="width:{n / total * 100:.1f}%" '
                      f'title="{h(k)} {n / total:.0%}"></span>'
                      for i, (k, n) in enumerate(devices.most_common()))
        legend = "".join(f'<span class="lg"><i class="sw s{i}"></i>{h(k)} <b>{n / total:.0%}</b></span>'
                         for i, (k, n) in enumerate(devices.most_common()))
        return (f'<div class="card chartcard"><div class="cardhead"><div><h3>Page views per day</h3>'
                f'<p class="muted small">{num(t["views"])} views · {span} · UTC days'
                f'{" · gold pins mark your posts" if marks else ""}</p></div>'
                f'<div class="devices"><div class="segbar">{dev}</div>'
                f'<div class="legend">{legend}</div></div></div>{chart}</div>'
                f'<div class="grid2">'
                + bar_list("Top pages", "Views", pages.most_common(), "No page views yet.")
                + bar_list("Sources", "Views", refs.most_common(), "No arrivals yet.",
                           note="Referring sites; steps between our own pages are left out.")
                + bar_list("Channels (?via=)", "Views", chans.most_common(), "No tagged links yet.",
                           note="A post's tag counts under its channel: reddit-oct28 is reddit.")
                + bar_list("Countries", "Views", countries.most_common(), "No views yet.")
                + '</div>')
    return section("traffic", "Traffic",
                   "From the site's own cookieless counter: counts of page views, never people.",
                   by_period(one))


COUNTRY = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "AU": "Australia",
           "DE": "Germany", "MX": "Mexico", "IE": "Ireland", "NZ": "New Zealand",
           "IN": "India", "PH": "Philippines", "FR": "France", "BR": "Brazil",
           "NL": "Netherlands", "SE": "Sweden", "T1": "Tor", "XX": "Unknown"}


def funnel_html(steps: list[tuple[str, int | None]], pending_label: str = "") -> str:
    if not steps:
        return ""
    first = steps[0][1] or 0
    out = []
    prev = None
    for i, (label, n) in enumerate(steps):
        if i and prev is not None:
            if n is None:
                out.append('<div class="drop muted">↓</div>')
            elif prev:
                keep = n / prev
                out.append(f'<div class="drop"><span class="keep">↓ {keep:.0%} continue</span>'
                           f'<span class="lost">{1 - keep:.0%} drop off</span></div>')
            else:
                out.append('<div class="drop muted">↓</div>')
        if n is None:
            out.append(f'<div class="fstep na"><span class="fl">{h(label)}</span>'
                       f'<span class="fbar"><i style="width:0"></i></span>'
                       f'<span class="fn">—</span><span class="fp">{h(pending_label)}</span></div>')
        else:
            w = (n / first * 100) if first else 0
            out.append(f'<div class="fstep"><span class="fl">{h(label)}</span>'
                       f'<span class="fbar"><i style="width:{max(w, 0.6 if n else 0):.1f}%"></i></span>'
                       f'<span class="fn">{num(n)}</span>'
                       f'<span class="fp">{(n / first):.1%} of first</span></div>'
                       if first else
                       f'<div class="fstep"><span class="fl">{h(label)}</span>'
                       f'<span class="fbar"><i style="width:0"></i></span><span class="fn">{num(n)}</span>'
                       f'<span class="fp">—</span></div>')
        prev = n
    return f'<div class="funnel">{"".join(out)}</div>'


def funnel_section(S: Mapping[str, Source], M: Mapping[str, Metrics]) -> str:
    if not S["traffic"].ok:
        return section("funnel", "Funnel", "From landing to paid, step by step.",
                       f'<p class="needs">{icon("plug", "ic")} Needs the page counter — see '
                       f'<a href="#traffic">Traffic</a> for how to connect it.</p>')

    def one(p: str) -> str:
        m = M[p]
        t = m.traffic
        main = funnel_html(m.funnel, "Stripe not connected")
        tryf = funnel_html([("Free-report page views", t["try_views"]),
                            ("Rosters checked", t["try_rosters"]),
                            ("Free reports requested", t["try_requests"])])
        plan = funnel_html([("Planner views", t["planner_views"]),
                            ("Rosters checked", t["planner_rosters"]),
                            ("Waitlist joins", t["planner_waitlist"])])
        rows = m.channels[:10]
        if rows:
            trs = "".join(
                f'<tr><td>{h(r["channel"])}</td><td class="r">{num(r["views"])}</td><td class="r hm">{num(r["rosters"])}</td>'
                f'<td class="r">{num(r["presses"])}</td><td class="r">{num(r["paid"]) if m.money else "—"}</td>'
                f'<td class="r hm">{pct(r["presses"] / r["views"], 1) if r["views"] else "—"}</td>'
                f'<td class="r">{pct(r["paid"] / r["views"], 2) if r["views"] and m.money else "—"}</td></tr>'
                for r in rows)
            table = (f'<div class="card"><div class="cardhead"><h3>By channel</h3>'
                     f'<span class="unit">?via= tag</span></div><div class="tablewrap"><table class="tbl">'
                     f'<thead><tr><th>Channel</th><th class="r">Views</th><th class="r hm">Rosters</th><th class="r">Buy presses</th>'
                     f'<th class="r">Paid</th><th class="r hm">Press rate</th><th class="r">Paid rate</th></tr></thead><tbody>{trs}</tbody></table></div></div>')
        else:
            table = ""
        table += posts_card(m, S)
        return (f'<div class="card"><div class="cardhead"><div>'
                f'<h3>Landing → paid</h3><p class="muted small">Step counts in the period. Cookieless, so '
                f'these are counts of each step, not one cohort of people.</p></div></div>{main}</div>'
                f'<div class="grid2"><div class="card"><div class="cardhead"><h3>Free report</h3></div>{tryf}</div>'
                f'<div class="card"><div class="cardhead"><h3>Bye planner</h3></div>{plan}</div></div>'
                f'{table}')
    return section("funnel", "Funnel", "Where the signup path loses people.", by_period(one))


LINK_HOWTO = 'make link TAG=reddit-oct28 WHERE="r/fantasyfootball"'


def posts_card(m: Metrics, S: Mapping[str, Source]) -> str:
    """Which posts sold: each tagged link on its own row."""
    rows = m.posts
    head = (f'<div class="cardhead"><div><h3>Posts</h3><p class="muted small">Each post\'s own link '
            f'tag. Make one with <code>{h(LINK_HOWTO)}</code> — it prints the link and logs the post.'
            f'</p></div><span class="unit">?via= tag</span></div>')
    if not rows:
        return (f'<div class="card">{head}<p class="muted small pad">No posts tracked yet. Give every '
                f'post its own tag (channel first, then anything: reddit-oct28, x-thread2) and this '
                f'table shows what each one brought in, down to the sale.</p></div>')
    def where(r: dict) -> str:
        return f'<br><span class="muted small">{h(r["where"])}</span>' if r["where"] else ""
    trs = "".join(
        f'<tr><td><b>{h(r["tag"])}</b>{where(r)}</td>'
        f'<td class="hm">{h(short_day(r["day"])) if r["day"] else "—"}</td>'
        f'<td class="r">{num(r["views"]) if m.traffic else "—"}</td>'
        f'<td class="r hm">{num(r["rosters"]) if m.traffic else "—"}</td>'
        f'<td class="r">{num(r["presses"]) if m.traffic else "—"}</td>'
        f'<td class="r"><b>{num(r["paid"]) if m.money else "—"}</b></td>'
        f'<td class="r">{money_fmt(m.money["net_by_via"].get(r["tag"], 0), True) if m.money and r["paid"] else "—"}</td></tr>'
        for r in rows[:15])
    more = f'<p class="more">+ {len(rows) - 15} older posts</p>' if len(rows) > 15 else ""
    return (f'<div class="card">{head}<div class="tablewrap"><table class="tbl posts">'
            f'<thead><tr><th>Post</th><th class="hm">Posted</th><th class="r" title="Page views on any page">Views</th>'
            f'<th class="r hm">Rosters</th><th class="r">Buy presses</th><th class="r">Paid</th>'
            f'<th class="r" title="What those purchases left after refunds and Stripe\'s fee">Net</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div>{more}</div>')


def gates_html(S: Mapping[str, Source], now: datetime, sends: dict | None, ledger: dict | None,
               registry: Source) -> str:
    plan = S["plan"]
    if not plan.ok:
        return setup_card(plan, compact=True)
    data = plan.data
    money_all = money_metrics(S["stripe"], "all", now) if S["stripe"].ok else None
    d_date = data["d_date"]
    since = datetime.fromisoformat(d_date).replace(tzinfo=timezone.utc) if d_date else None

    def paid_since() -> list[dict]:
        if not S["stripe"].ok:
            return []
        return [s for s in S["stripe"].data["sessions"] if s.get("paid")
                and (since is None or (_ts(s.get("created")) or now) >= since)]
    rows = []
    for g in data["gates"]:
        metric = g["metric"]
        low = metric.lower()
        current, frac, state = None, None, "unmeasured"
        target = re.search(r"([≥≤])\s*(\d+(?:\.\d+)?)(%?)", g["green"])
        tnum = float(target.group(2)) if target else None
        if "free reports sent" in low and sends is not None:
            current = sum(1 for e in sends["entries"]
                          if e["key"].startswith(f"trial-{sends['season']}-")
                          and (since is None or (_ts(e["sent_at"]) or now) >= since))
        elif "paid purchases" in low and S["stripe"].ok:
            current = len(paid_since())
        elif "refund rate" in low and money_all:
            current = (money_all["refund_rate"] * 100) if money_all["refund_rate"] is not None else None
        elif "purchases + league passes" in low and S["stripe"].ok:
            paid = paid_since()
            current = len(paid)
            lp = sum(1 for s in paid if (s.get("pass") or "").startswith("League"))
            g = {**g, "extra": f"{lp} League Pass{'es' if lp != 1 else ''}"}
        elif "graded rows" in low and ledger is not None:
            current = ledger["graded"]
        elif "seats claimed" in low and registry.ok:
            seats = registry.data["seats"]
            current = sum(n for n, _c in seats)
            g = {**g, "extra": ", ".join(f"{n} of {c}" for n, c in seats) or "no pass yet"}
            if seats and "half" in g["green"].lower():
                # "≥ half its seat_cap", per pass: on track only when every pass is.
                frac = min(min((n / c) / 0.5 if c else 1 for n, c in seats), 1)
                state = "met" if frac >= 1 else "behind"
        if current is not None and tnum is None and state == "unmeasured":
            state = "tracking"
        if current is not None and tnum is not None:
            if target.group(1) == "≥":
                frac = min(current / tnum, 1) if tnum else 1
                state = "met" if current >= tnum else "behind"
            else:
                frac = 1 if current <= tnum else max(0.0, tnum / current)
                state = "met" if current <= tnum else "behind"
        read_by = g["read_by"]
        if d_date and read_by.startswith("D+"):
            n = re.match(r"D\+(\d+)", read_by)
            if n:
                when = date.fromisoformat(d_date) + timedelta(days=int(n.group(1)))
                read_by = f"{read_by} · {when:%b} {when.day}"
        cur = ("—" if current is None else
               f"{current:.0f}%" if "refund rate" in low else num(current))
        pill = {"met": '<span class="pill good">On track</span>',
                "behind": '<span class="pill warn">Behind</span>',
                "tracking": '<span class="pill">Tracking</span>',
                "unmeasured": '<span class="pill">Not measurable here</span>'}[state]
        bar = (f'<span class="meter"><i class="{state}" style="width:{frac * 100:.0f}%"></i></span>'
               if frac is not None else '<span class="meter"></span>')
        rows.append(f'<tr><td class="nowrap">{h(read_by)}</td><td>{h(metric)}'
                    f'{"<br><span class=muted>" + h(g["extra"]) + "</span>" if g.get("extra") else ""}</td>'
                    f'<td class="nowrap">{h(g["green"])}</td><td class="num">{h(cur)}</td>'
                    f'<td>{bar}</td><td>{pill}</td></tr>')
    d_note = (f"D = {d_date} (written in PLAN §6)." if d_date else
              "D, the day checkout opens, isn't written in PLAN §6 yet — counts below run from the "
              "season's start until it is.")
    return (f'<div class="card"><div class="cardhead"><div><h3>PLAN §6 decision gates</h3>'
            f'<p class="muted small">{h(d_note)} Targets are read from PLAN.md, never restated.</p>'
            f'</div></div><div class="tablewrap"><table class="tbl gates"><thead><tr><th>Read by</th>'
            f'<th>Metric</th><th>Green</th><th>Now</th><th></th><th></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></div>')


def profit_block(S: Mapping[str, Source], M: Mapping[str, Metrics], now: datetime) -> str:
    """Profit after your own costs, break-even, per hour, and what's due next."""
    books = S["books"]
    if not books.ok:
        return (f'<div class="card"><div class="cardhead"><div><h3>Profit</h3><p class="muted small">'
                f'Revenue minus what the business costs you.</p></div></div>{setup_card(books, compact=True)}'
                f'<p class="muted small">Record a cost: <code>make cost ITEM="Domain" AMOUNT=12 '
                f'REPEATS=yearly</code> · time spent: <code>make hours H=1.5</code></p></div>')
    from run.books import monthly_run_rate, next_charges, spent
    b = books.data
    today = now.astimezone(ET).date()
    all_m = M["all"]
    costs_all = spent(b.costs, None, today)
    net_all = all_m.money["net"] if all_m.money is not None else None
    per_pass = net_per_pass()
    if net_all is None:
        be = (f'<p class="be-line">Costs so far: <b>{money_fmt(costs_all, True)}</b>. Connect Stripe to '
              f'see how far revenue has come against them.</p>')
    else:
        gap = costs_all - net_all
        fill = 100 if costs_all <= 0 else min(100, max(0, net_all / costs_all * 100))
        if gap > 0:
            need = math.ceil(gap / per_pass)
            line = (f'<b>{need} more $29 pass{"es" if need != 1 else ""}</b> to break even '
                    f'({money_fmt(gap, True)} to go at {money_fmt(per_pass, True)} each after Stripe).')
        else:
            line = f'<b>Broken even</b>, {money_fmt(-gap, True)} ahead of every cost so far.'
        be = (f'<div class="be"><div class="bebar"><i style="width:{fill:.1f}%"></i></div>'
              f'<p class="be-line">{line}</p><p class="muted small">Net revenue to date '
              f'{money_fmt(net_all, True)} · costs to date {money_fmt(costs_all, True)}</p></div>')

    def one(p: str) -> str:
        pr = M[p].profit
        span = "all time" if p == "all" else f"last {M[p].days} days"
        tiles = [("Net revenue", money_fmt(pr["net"], True) if pr["net"] is not None else "—", ""),
                 ("Costs", money_fmt(-pr["costs"], True) if pr["costs"] else "$0.00", ""),
                 ("Profit", money_fmt(pr["profit"], True) if pr["profit"] is not None else "—", " net"),
                 ("Per hour", (money_fmt(pr["per_hour"], True) if pr["per_hour"] is not None else "—"),
                  "")]
        th = "".join(f'<div class="mini{c}"><p class="kl">{h(a)}</p><p class="mv">{v}</p></div>'
                     for a, v, c in tiles)
        hrs = (f'{pr["hours"]:g} h logged, {span}' if pr["hours"] else
               'Log time with <code>make hours H=1.5</code> to see this')
        return f'<div class="minis">{th}</div><p class="muted small">{hrs}</p>'
    due = next_charges(b.costs, today)
    due_html = ("".join(f'<li><span>{h(short_day(d.isoformat()))}</span><b>{h(c.item)}</b>'
                        f'<em>{money_fmt(c.amount, True)}</em></li>' for d, c in due[:6])
                or '<li class="muted">Nothing recurring due in the next 30 days.</li>')
    items: Counter = Counter()
    for c in b.costs:
        items[c.item] += spent([c], None, today)
    cost_list = bar_list("Costs by item", "$ so far", [(k, round(v)) for k, v in items.most_common() if v],
                         "No costs recorded yet.",
                         note=f"Recurring: {money_fmt(monthly_run_rate(b.costs), True)} a month.")
    return (f'<div class="card profit"><div class="cardhead"><div><h3>Profit</h3>'
            f'<p class="muted small">Net revenue after Stripe, less the costs you record in '
            f'data/costs.csv.</p></div></div>{by_period(one)}{be}</div>'
            f'<div class="grid2">{cost_list}<div class="card"><div class="cardhead"><h3>Due in the next '
            f'30 days</h3><span class="unit">Recurring</span></div><ul class="due">{due_html}</ul></div></div>')


def money_section(S: Mapping[str, Source], M: Mapping[str, Metrics], now: datetime,
                  sends: dict | None, ledger: dict | None, ftp) -> str:
    gates = gates_html(S, now, sends, ledger, S["registry"])
    profit = profit_block(S, M, now)
    if not S["stripe"].ok:
        return section("money", "Money", "Passes sold, what they left after Stripe, profit and the "
                       "plan's gates.", setup_card(S["stripe"]) + profit + gates)

    def one(p: str) -> str:
        m = M[p]
        mo, t = m.money, m.traffic
        tiles = "".join(
            f'<div class="mini{" net" if lab == "Net" else ""}"><p class="kl">{h(lab)}</p><p class="mv">{val}</p></div>'
            for lab, val in (("Gross", money_fmt(mo["gross"], True)),
                             ("Stripe fees (modelled)", money_fmt(-mo["fees"], True)),
                             ("Refunded", money_fmt(-mo["refunded"], True)),
                             ("Net", money_fmt(mo["net"], True))))
        conv = []
        if t is not None and t["landing"]:
            conv.append(("Landing view → paid", pct(mo["count"] / t["landing"], 2),
                         f"{mo['count']} of {num(t['landing'])} views"))
        if t is not None and t["rosters"]:
            conv.append(("Roster checked → buy press", pct(t["presses"] / t["rosters"]),
                         f"{num(t['presses'])} of {num(t['rosters'])}"))
        if ftp is not None:
            paid, judged, young = ftp
            conv.append((f"Free report → paid in {FREE_TO_PAID_DAYS} d",
                         pct(paid / judged) if judged else "—",
                         f"{paid} of {judged}" + (f" · {young} too new" if young else "")))
        ck = mo["checkouts"]
        if sum(ck.values()):
            conv.append(("Checkouts completed", pct(ck.get("complete", 0) / sum(ck.values())),
                         f"{ck.get('complete', 0)} of {sum(ck.values())} started"))
        convh = "".join(f'<div class="mini"><p class="kl">{h(a)}</p><p class="mv">{h(b)}</p>'
                        f'<p class="muted small">{h(c)}</p></div>' for a, b, c in conv)
        convh = (f'<div class="minis conv">{convh}</div>' if convh else
                 '<p class="muted small">Conversion needs the page counter as well as Stripe.</p>')
        types = sorted(mo["types"].items(), key=lambda kv: -kv[1])
        from run.books import channel_of
        grouped: Counter = Counter()
        for via, n in mo["by_channel"].items():
            grouped[via if via == stats.NO_VIA else channel_of(via)] += n
        chans = sorted(grouped.items(), key=lambda kv: (kv[0] == stats.NO_VIA, -kv[1]))
        span_days = mo["chart_days"]
        chart = column_chart(span_days, mo["chart"], "passes") if span_days else ""
        disputes = [s for s in mo["disputes"]]
        dline = (f'{len(disputes)} disputed payment(s) this season.' if disputes else
                 "No disputes this season.")
        other = (f' {mo["other_currency"]} paid in another currency, left out of the dollar figures.'
                 if mo["other_currency"] else "")
        return (f'<div class="minis">{tiles}</div>{convh}'
                f'<div class="card"><div class="cardhead"><div><h3>Passes per day</h3>'
                f'<p class="muted small">{num(mo["count"])} sold · {mo["full_refunds"]} refunded in full · '
                f'{h(dline)}{h(other)}</p></div></div>{chart}</div>'
                f'<div class="grid2">'
                + bar_list("Passes by type", "Sold", types, "No passes sold in this period.")
                + bar_list("Paid by channel", "Sold", chans, "No paid signups in this period.",
                           note="From the ?via= tag on the payment; a post counts under its "
                                "channel (the Posts table has each post).")
                + '</div>')
    return section("money", "Money", "Passes sold, what they left after Stripe, profit and the "
                   "plan's gates.", by_period(one) + profit + gates)


def customers_section(S: Mapping[str, Source], sends: dict | None, now: datetime) -> str:
    parts = []
    reg = S["registry"]
    if reg.ok:
        d = reg.data
        plans = "".join(f'<li><span>{h(k)}</span><b>{num(v)}</b></li>' for k, v in sorted(d["plans"].items()))
        seats = "".join(
            f'<li><span>Pass {i + 1}</span><span class="meter"><i class="met" '
            f'style="width:{(n / c * 100) if c else 0:.0f}%"></i></span><b>{n} of {c}</b></li>'
            for i, (n, c) in enumerate(d["seats"])) or '<li class="muted">No League Pass yet.</li>'
        parts.append(f'<div class="card"><div class="cardhead"><h3>Subscribers</h3>'
                     f'<span class="big">{num(d["total"])}</span></div><ul class="kv">{plans}</ul>'
                     f'<h4>League Pass seats claimed</h4><ul class="kv seats">{seats}</ul></div>')
    else:
        parts.append(f'<div class="card"><div class="cardhead"><h3>Subscribers & seats</h3></div>'
                     f'{setup_card(reg, compact=True)}</div>')
    fo = S["forms"]
    if fo.ok:
        s = fo.data["summary"]
        labels = dict(stats.FORM_KINDS)
        trs = "".join(
            f'<tr><td>{h(labels.get(k, k))}</td><td class="r">{num(s.get(k, {}).get("total", 0))}</td>'
            f'<td class="r">{num(s.get(k, {}).get("week", 0))}</td><td class="r">{num(s.get(k, {}).get("day", 0))}</td>'
            f'<td class="r">{"—" if k == "confirm" else num(s.get(k, {}).get("people", 0))}</td></tr>'
            for k, _l in stats.FORM_KINDS if k != "update" or k in s)
        parts.append(f'<div class="card"><div class="cardhead"><h3>Form Worker rows</h3>'
                     f'<span class="unit">rows kept ~13 months</span></div><div class="tablewrap">'
                     f'<table class="tbl"><thead><tr><th>Kind</th><th class="r">Ever</th><th class="r">7 days</th>'
                     f'<th class="r">24 h</th><th class="r">People</th></tr></thead><tbody>{trs}</tbody></table></div></div>')
    else:
        parts.append(f'<div class="card"><div class="cardhead"><h3>Form Worker rows</h3></div>'
                     f'{setup_card(fo, compact=True)}</div>')
    if sends is not None:
        weekly = sends["summary"]["weekly"]
        finals = sends["summary"]["finals"]
        if weekly:
            weeks = list(range(min(weekly), max(weekly) + 1))
            chart = column_chart([], [weekly.get(w, 0) for w in weeks], "reports",
                                 labels=[f"Week {w}" for w in weeks])
        else:
            chart = '<p class="muted small pad">No weekly report has gone to a subscriber yet.</p>'
        other = sends["summary"]["other"]
        extras = "".join(f'<li><span>{h(k[0].upper() + k[1:])}</span><b>{num(v)}</b></li>'
                         for k, v in sorted(other.items()))
        if finals:
            extras += (f'<li><span>Saturday final checks</span><b>{num(sum(finals.values()))}</b></li>')
        stopped = sends.get("stopped")
        extras += (f'<li><span>Stop requests on the list</span><b>{num(stopped)}</b></li>'
                   if stopped is not None else "")
        left = (f'<div><div class="cardhead"><div><h3>Weekly reports sent</h3>'
                f'<p class="muted small">{h(sends["season"])} season · data/processed/sent.jsonl</p>'
                f'</div><span class="big">{num(sum(weekly.values()))}</span></div>{chart}</div>')
        mid = f'<div><h4 class="first">Other mail this season</h4><ul class="kv">{extras}</ul></div>'
    else:
        left = (f'<div><div class="cardhead"><h3>Emails sent</h3></div>'
                f'{setup_card(S["sends"], compact=True)}</div>')
        mid = ""
    b = S["bounces"]
    if b.ok:
        paid, unpaid = len(b.data["paid"]), len(b.data["unpaid"])
        tone = "bad" if paid else "good"
        right = (f'<div><h4 class="first">Bounces, last 48 hours <span class="big {tone} inline">'
                 f'{paid + unpaid}</span></h4><ul class="kv">'
                 f'<li><span>Checked with Resend</span><b>{b.data["checked"]}</b></li>'
                 f'<li><span>Paid mail undelivered</span><b>{paid}</b></li>'
                 f'<li><span>Unpaid mail undelivered</span><b>{unpaid}</b></li></ul></div>')
    else:
        right = f'<div><h4 class="first">Bounces</h4>{setup_card(b, compact=True)}</div>'
    parts.append(f'<div class="card wide delivery">{left}<div class="dside">{mid}{right}</div></div>')
    return section("customers", "Customers & operations",
                   "Who's on the list, what went out, and whether it arrived.",
                   f'<div class="grid-cust">{"".join(parts)}</div>')


def issues_section(issues: list[Issue], health: list[dict], S: Mapping[str, Source],
                   now: datetime) -> str:
    if issues:
        items = "".join(issue_html(i) for i in issues)
        body = f'<ol class="issues">{items}</ol>'
    else:
        body = (f'<div class="allclear">{icon("check", "eic")}<div><p class="et">Nothing to resolve</p>'
                f'<p class="ed">Every source that could be read is healthy.</p></div></div>')
    if health:
        rows = []
        for wf in health:
            last = wf["last"]
            when = _gh_when(last["created_at"]) if last else None
            state = (last["conclusion"] or last["status"]) if last else "never run"
            cls = {"success": "good", "failure": "bad", "in_progress": "warn", "queued": "warn",
                   "cancelled": "warn"}.get(state, "")
            if wf["missing"]:
                state, cls = "missed slot", "bad"
            dots = "".join(f'<i class="d {"good" if c == "success" else "bad" if c == "failure" else "warn"}" '
                           f'title="{h(c)}"></i>' for c in reversed(wf["recent"]))
            rows.append(
                f'<tr><td><a href="{h(last["url"]) if last and last["url"] else "#"}" class="wf">'
                f'{h(wf["label"])}</a><span class="muted small block">{h(wf["file"])}</span></td>'
                f'<td><span class="state {cls}">{h(state.replace("_", " "))}</span></td>'
                f'<td class="nowrap">{h(ago(when, now)) if when else "—"}</td>'
                f'<td><span class="dots">{dots}</span></td></tr>')
        crons = (f'<div class="card"><div class="cardhead"><div><h3>Cron health</h3><p class="muted small">'
                 f'From the repository\'s public Actions record. Dots: the last 12 completed runs, '
                 f'oldest first.</p></div></div><div class="tablewrap"><table class="tbl">'
                 f'<thead><tr><th>Workflow</th><th>Last run</th><th>When</th><th>Recent</th></tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table></div></div>')
    else:
        crons = (f'<div class="card"><div class="cardhead"><h3>Cron health</h3></div>'
                 f'{setup_card(S["github"], compact=True)}</div>')
    counts = Counter(i.severity for i in issues)
    extra = "".join(f'<span class="pill sev-{k}">{counts[k]} {k}</span>'
                    for k in ("critical", "high", "medium", "low") if counts.get(k))
    return section("issues", "Issues to resolve", "Most urgent first, each with the step that fixes it.",
                   f'<div class="grid-issues"><div>{body}</div>{crons}</div>',
                   f'<div class="pills">{extra}</div>')


def issue_html(i: Issue, compact: bool = False) -> str:
    links = []
    if i.link:
        links.append(f'<a class="go" href="{h(i.link)}">Open {icon("ext", "ic tiny")}</a>')
    if i.ref in LAUNCH_REFS:
        label, url = LAUNCH_REFS[i.ref]
        links.append(f'<a class="go quiet" href="{h(url)}">{h(label)} {icon("ext", "ic tiny")}</a>')
    links_html = f'<span class="golinks">{"".join(links)}</span>' if links else ""
    icon_name = "alert" if i.severity in ("critical", "high") else "info"
    if isinstance(i.fix, tuple) and len(i.fix) > 1:
        steps = "".join(f"<li>{h(step)}</li>" for step in i.fix)
        fix = f'<div class="fix"><b>Do this:</b><ol class="steps">{steps}</ol>{links_html}</div>'
    else:
        text = i.fix[0] if isinstance(i.fix, tuple) else i.fix
        fix = f'<p class="fix"><b>Do this:</b> {h(text)} {links_html}</p>'
    return (f'<li class="issue sev-{i.severity}">{icon(icon_name, "iic")}<div>'
            f'<p class="it"><span class="pill sev-{i.severity}">{i.severity.capitalize()}</span>'
            f'{" <span class=iarea>" + h(i.area) + "</span>" if i.area and not compact else ""} {h(i.title)}</p>'
            f'{fix}</div></li>')


def ago(when: datetime, now: datetime) -> str:
    secs = (now - when).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs / 60:.0f} min ago"
    if secs < 48 * 3600:
        return f"{secs / 3600:.0f} h ago"
    return f"{secs / 86400:.0f} days ago"


def record_section(ledger: dict | None, src: Source) -> str:
    if ledger is None:
        return section("record", "Product record", "This season's published calls, graded.",
                       setup_card(src))
    if not ledger["recorded"]:
        return section("record", "Product record", "This season's published calls, graded.",
                       f'<div class="empty">{icon("clock", "eic")}<div><p class="et">No calls on the '
                       f'record for {h(ledger["season"])} yet</p><p class="ed">Every delivered report '
                       f'and the live sample record their odds; they appear here once recorded.</p></div></div>')
    tiles = "".join(f'<div class="mini"><p class="kl">{h(a)}</p><p class="mv">{b}</p></div>' for a, b in (
        ("Recorded", num(ledger["recorded"])), ("Graded", num(ledger["graded"])),
        ("Pending", num(ledger["pending"])),
        ("Hit rate", pct(ledger["hit_rate"])), ("Average stated", pct(ledger["stated"]))))
    size = 280
    pad = 34

    def xy(stated: float, observed: float) -> tuple[float, float]:
        lo, hi = 0.5, 1.0
        x = pad + (stated - lo) / (hi - lo) * (size - pad - 10)
        y = (size - pad) - (max(min(observed, 1), 0) - 0) / 1.0 * (size - pad - 10)
        return x, y
    grid = "".join(
        f'<line x1="{pad}" x2="{size - 10}" y1="{xy(.5, v)[1]:.1f}" y2="{xy(.5, v)[1]:.1f}"/>'
        f'<text x="{pad - 6}" y="{xy(.5, v)[1] + 4:.1f}" text-anchor="end">{v:.0%}</text>'
        for v in (0, .25, .5, .75, 1))
    xt = "".join(f'<text x="{xy(v, 0)[0]:.1f}" y="{size - pad + 16}" text-anchor="middle">{v:.0%}</text>'
                 for v in (.5, .6, .7, .8, .9, 1))
    diag = f'<line class="diag" x1="{xy(.5, .5)[0]}" y1="{xy(.5, .5)[1]}" x2="{xy(1, 1)[0]}" y2="{xy(1, 1)[1]}"/>'
    dots = "".join(
        f'<g class="pt" tabindex="0"><title>{h(b["label"])}: stated {b["stated"]:.0%}, landed '
        f'{b["observed"]:.0%} on {b["n"]} call(s)</title><circle cx="{xy(b["stated"], b["observed"])[0]:.1f}" '
        f'cy="{xy(b["stated"], b["observed"])[1]:.1f}" r="{4 + min(b["n"], 40) ** .5:.1f}"/></g>'
        for b in ledger["bands"])
    chart = (f'<svg class="calib" viewBox="0 0 {size} {size}" role="img" aria-label="Stated against '
             f'landed, by band"><g class="grid">{grid}</g>{xt}{diag}{dots}'
             f'<text class="axl" x="{(size + pad) / 2}" y="{size - 2}" text-anchor="middle">Stated</text></svg>')
    trs = "".join(f'<tr><td>{h(b["label"])}</td><td class="r">{b["n"]}</td><td class="r">{b["stated"]:.0%}</td>'
                  f'<td class="r">{b["observed"]:.0%}</td></tr>' for b in ledger["bands"])
    weeks = "".join(f'<tr><td>Week {w}</td><td class="r">{d["calls"]}</td><td class="r">{d["hits"]}</td>'
                    f'<td class="r">{d["misses"]}</td><td class="r">{d["pending"]}</td><td class="r">{d["void"]}</td></tr>'
                    for w, d in ledger["weeks"].items())
    note = ("Too few graded calls to judge calibration — read the bands as a log, not a verdict."
            if (ledger["hits"] + ledger["misses"]) < 50 else
            "Dots on the diagonal mean the stated odds landed as often as stated.")
    return section(
        "record", "Product record",
        f"{ledger['season']} published calls from the public ledger — owner view; selling pages never quote it.",
        f'<div class="minis">{tiles}</div><div class="grid-record">'
        f'<div class="card"><div class="cardhead"><div><h3>Stated vs landed</h3><p class="muted small">'
        f'{h(note)}</p></div></div><div class="calwrap">{chart}</div></div>'
        f'<div class="card"><div class="cardhead"><h3>By band</h3></div><div class="tablewrap"><table class="tbl">'
        f'<thead><tr><th>Band</th><th class="r">Graded</th><th class="r">Stated</th><th class="r">Landed</th></tr></thead><tbody>{trs or "<tr><td colspan=4 class=muted>Nothing graded yet.</td></tr>"}</tbody></table></div>'
        f'<h4>By week</h4><div class="tablewrap"><table class="tbl"><thead><tr><th>Week</th><th class="r">Calls</th><th class="r">Hits</th>'
        f'<th class="r">Misses</th><th class="r">Pending</th><th class="r">Void</th></tr></thead><tbody>{weeks}</tbody></table></div></div></div>')


def insights_section(I: Mapping[str, list[Insight]]) -> str:
    def one(p: str) -> str:
        items = I[p]
        if not items:
            return (f'<div class="empty">{icon("spark", "eic")}<div><p class="et">No insights yet</p>'
                    f'<p class="ed">They appear as traffic and sales arrive: the biggest funnel drop, '
                    f'the channel that converts, refund rate against the plan.</p></div></div>')
        cards = "".join(
            f'<li class="ins {i.tone}">{icon({"good": "up", "warn": "down", "info": "info"}[i.tone], "iic")}'
            f'<div><p class="it">{h(i.text)}</p><p class="fix"><b>Do this:</b> {h(i.action)}</p>'
            f'<p class="basis">Based on: {h(i.basis)}</p></div></li>' for i in items)
        return f'<ul class="insights">{cards}</ul>'
    return section("insights", "Insights", "Plain-language reads of the numbers, each with its basis.",
                   by_period(one))


def attention(issues: list[Issue]) -> str:
    urgent = [i for i in issues if i.severity in ("critical", "high")][:3]
    if not urgent:
        rest = len(issues)
        return (f'<div class="attn clear">{icon("check", "aic")}<div><p class="at">Nothing needs you right now.</p>'
                f'<p class="ad">{rest} lower-priority item{"s" if rest != 1 else ""} below in Issues.'
                f'</p></div></div>' if rest else
                f'<div class="attn clear">{icon("check", "aic")}<div><p class="at">All clear — nothing '
                f'needs you right now.</p></div></div>')
    items = "".join(issue_html(i, compact=True) for i in urgent)
    more = len([i for i in issues if i.severity in ("critical", "high")]) - len(urgent)
    tail = f'<a class="more" href="#issues">+ {more} more urgent</a>' if more > 0 else \
        '<a class="more" href="#issues">All issues →</a>'
    return (f'<div class="attn"><div class="attnhead">{icon("alert", "aic")}<p class="at">Needs you now</p>'
            f'{tail}</div><ol class="issues">{items}</ol></div>')


FRESHNESS_KEYS = ("traffic", "stripe", "forms", "intake", "sends", "bounces", "github", "ledger",
                  "launch", "registry", "plan", "books")


def freshness(S: Mapping[str, Source], now: datetime) -> str:
    """One quiet chip when every source is live; each source that isn't gets
    its own amber (not connected) or red (error) chip beside it. The full
    list, with data ages, opens from the summary chip."""
    live = [k for k in FRESHNESS_KEYS if S[k].ok]
    rows = []
    for key in FRESHNESS_KEYS:
        src = S[key]
        word = {"ok": "live", "off": "not connected", "error": "couldn't be read"}[src.status]
        if key == "books" and src.status == "off":
            word = "nothing recorded yet"
        extra = ""
        if key == "sends" and src.ok and src.data["entries"]:
            last = max((e["sent_at"] or "" for e in src.data["entries"]), default="")
            if last and _ts(last):
                extra = f" · last send {ago(_ts(last), now)}"
        rows.append(f'<li class="{ {"ok": "good", "off": "warn", "error": "bad"}[src.status] }"><i></i>'
                    f'<b>{h(src.label)}</b> <span>{h(word + extra)}</span></li>')
    site = S["site"]
    if site.ok:
        week = site.data.get("week") or {}
        if week.get("built_at") and _ts(week["built_at"]):
            rows.append(f'<li><i></i><b>This week\'s sample</b> <span>built '
                        f'{h(ago(_ts(week["built_at"]), now))}</span></li>')
        if site.data.get("players_at") and _ts(site.data["players_at"]):
            rows.append(f'<li><i></i><b>Player directory</b> <span>rebuilt '
                        f'{h(ago(_ts(site.data["players_at"]), now))}</span></li>')
    total = len(FRESHNESS_KEYS)
    summary = (f"All {total} sources live" if len(live) == total
               else f"{len(live)} of {total} sources live")
    cls = "good" if len(live) == total else ""
    chips = [f'<details class="srcs"><summary class="chip {cls}"><i></i>{h(summary)}'
             f'<span class="caret" aria-hidden="true">▾</span></summary>'
             f'<ul class="srclist">{"".join(rows)}</ul></details>']
    for key in FRESHNESS_KEYS:
        src = S[key]
        if not src.ok:
            word = "not connected" if src.status == "off" else "error"
            if key == "books" and src.status == "off":
                word = "nothing recorded yet"
            chips.append(f'<span class="chip {"warn" if src.status == "off" else "bad"}" '
                         f'title="{h(src.note)}"><i></i>{h(src.label)} <em>{word}</em></span>')
    return f'<div class="chips">{"".join(chips)}</div>'


# --------------------------------------------------------------------- #
# the page
# --------------------------------------------------------------------- #

FONT_FILES = (("Barlow", 400, "normal", "barlow-400.woff2"), ("Barlow", 500, "normal", "barlow-500.woff2"),
              ("Barlow", 600, "normal", "barlow-600.woff2"), ("Barlow", 700, "normal", "barlow-700.woff2"),
              ("Barlow Condensed", 700, "normal", "barlow-condensed-700.woff2"),
              ("Barlow Condensed", 800, "normal", "barlow-condensed-800.woff2"))
FONT_BUDGET = 160_000   # bytes of woff2; above this the page uses system fonts


def font_css(root: Path = REPO_ROOT) -> str:
    out, used = [], 0
    for family, weight, style, name in FONT_FILES:
        path = root / "site" / "fonts" / name
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        used += len(raw)
        if used > FONT_BUDGET:
            break
        out.append(f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};"
                   f"font-display:swap;src:url(data:font/woff2;base64,"
                   f"{base64.b64encode(raw).decode()}) format('woff2');}}")
    return "".join(out)


NAV = (("overview", "Overview"), ("traffic", "Traffic"), ("funnel", "Funnel"), ("money", "Money"),
       ("customers", "Customers"), ("issues", "Issues"), ("record", "Record"), ("insights", "Insights"))


def render_page(sources: Mapping[str, Source], now: datetime, root: Path = REPO_ROOT,
                fonts: bool = True, env: Mapping[str, str] | None = None,
                live_minutes: int | None = None) -> str:
    # A source nobody read is an unconnected one, never a crash.
    sources = {**{k: off(k, "Not read this time.") for k in SOURCE_INFO}, **sources}
    M = {p: metrics_for(sources, p, now) for p, _l, _d in PERIODS}
    sends = sources["sends"].data if sources["sends"].ok else None
    ledger = ledger_view(sources["ledger"], now)
    health = workflow_health(sources["github"], now, root)
    issues = build_issues(sources, now, health, ledger, M["7d"])
    ftp = free_to_paid(sources["forms"], sources["stripe"], now)
    insights = {p: build_insights(sources, M[p], now, ftp, ledger) for p, _l, _d in PERIODS}
    from render.report import mark_svg
    urgent = sum(i.severity in ("critical", "high") for i in issues)
    badge = (f'<span class="badge{" hot" if urgent else ""}">{len(issues)}</span>' if issues else "")
    nav = "".join(f'<a href="#{k}" data-nav="{k}">{h(v)}{badge if k == "issues" else ""}</a>'
                  for k, v in NAV)
    periods = "".join(f'<button type="button" data-period="{k}" aria-pressed="{str(k == "30d").lower()}">'
                      f'{h(lab)}</button>' for k, lab, _d in PERIODS)
    consoles = "".join(f'<a href="{h(u)}" target="_blank" rel="noopener noreferrer">{h(n)} '
                       f'{icon("ext", "ic tiny")}</a>' for n, u in CONSOLES)
    stamp = now.astimezone(ET)
    # Live mode: the page reloads itself after the next rebuild and says so,
    # and says so again when the rebuilds have stopped (the stale strip).
    live = (f'<span class="live" title="Rebuilt every {live_minutes} minutes while make dashboard-live '
            f'runs">Live · every {live_minutes} min</span>' if live_minutes else "")
    stale = ('<div class="stale" hidden>These numbers stopped updating. Live updates stopped at '
             f'{stamp:%-I:%M %p} ET; run <code>make dashboard-live</code> again.</div>'
             if live_minutes else "")
    body_attrs = (f' data-refresh="{live_minutes * 60}" data-generated="{int(now.timestamp() * 1000)}"'
                  if live_minutes else "")
    body = (
        f'<header class="top"><div class="topin"><a class="brand" href="#overview">'
        f'{mark_svg("dash", "logo")}<span><b>Beat Your League</b><em>Owner dashboard</em></span></a>'
        f'<span class="gen" title="Generated {h(now.isoformat())}">{icon("clock", "ic tiny")} '
        f'{stamp:%a %b} {stamp.day}, {stamp:%-I:%M %p} ET</span>{live}'
        f'<button class="theme" type="button" aria-label="Switch light or dark">{icon("moon", "ic moon")}'
        f'{icon("sun", "ic sun")}</button></div>'
        f'<nav class="tabs" aria-label="Sections"><div class="tabsin">{nav}</div></nav></header>'
        f'<main class="wrap">{stale}'
        f'{attention(issues)}'
        f'<div class="filters"><div class="seg" role="group" aria-label="Period">{periods}</div>'
        f'<p class="muted small fnote">Traffic keeps 90 days; money and forms count all time under “All”.</p>'
        f'{freshness(sources, now)}</div>'
        + overview(sources, M, sends)
        + traffic_section(sources, M)
        + funnel_section(sources, M)
        + money_section(sources, M, now, sends, ledger, ftp)
        + customers_section(sources, sends, now)
        + issues_section(issues, health, sources, now)
        + record_section(ledger, sources["ledger"])
        + insights_section(insights)
        + f'<footer class="foot"><div class="consoles"><span class="muted">Consoles</span>{consoles}</div>'
          f'<p class="muted small">Private: built on this machine by <code>make dashboard</code> from your own '
          f'sources, read-only, counts and dollars only. Never commit or share this file.</p></footer></main>')
    # Everything dynamic lives in the body; the CSS, the script and the
    # inlined fonts are constants of this module.
    body = scrub(body, os.environ if env is None else {**os.environ, **env})
    css = (font_css(root) if fonts else "") + CSS
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="robots" content="noindex, nofollow">'
            '<meta name="referrer" content="no-referrer">'
            '<title>BYL — Owner dashboard</title>'
            f'<style>{css}</style></head><body data-period="30d"{body_attrs}>{body}'
            f'<script>{JS}</script></body></html>\n')


def scrub(text: str, env: Mapping[str, str]) -> str:
    """The last line of defence: no address and no secret value can leave in
    the page, whatever a provider put in a string upstream."""
    for name in SECRET_NAMES:
        value = env.get(name) or ""
        if len(value) >= 6:
            text = text.replace(value, "***")
    return redact(text)


CSS = r"""
:root{--bg:#F6F4EE;--surface:#fff;--surface2:#FBFAF6;--line:#E7E2D7;--line2:#EFEBE2;
--ink:#101E33;--ink2:#47546B;--muted:#7C8698;--navy:#101E33;--gold:#F2C230;--goldink:#8A6A00;
--series:#24456F;--series2:#E9B21C;--wash:rgba(36,69,111,.10);--barbg:rgba(242,194,48,.26);--good:#23744A;--goodbg:#E3F1E8;
--bad:#B23B2A;--badbg:#F8E4E0;--warn:#9A6408;--warnbg:#FBEFD6;--focus:#2F6FD6;
--shadow:0 1px 2px rgba(16,30,51,.05),0 4px 16px rgba(16,30,51,.04);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0A1220;--surface:#111C2E;--surface2:#15223A;
--line:#22324C;--line2:#1B2A42;--ink:#EDF1F7;--ink2:#B4BFD1;--muted:#8592A8;--series:#F2C230;--series2:#7EA6E0;
--wash:rgba(242,194,48,.12);--barbg:rgba(126,166,224,.15);--good:#5FC48C;--goodbg:rgba(95,196,140,.12);
--bad:#F0806C;--badbg:rgba(240,128,108,.13);--warn:#E9B24E;--warnbg:rgba(233,178,78,.13);--goldink:#F2C230;
--focus:#7EB0FF;--shadow:0 1px 2px rgba(0,0,0,.3);color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0A1220;--surface:#111C2E;--surface2:#15223A;--line:#22324C;--line2:#1B2A42;
--ink:#EDF1F7;--ink2:#B4BFD1;--muted:#8592A8;--series:#F2C230;--series2:#7EA6E0;--wash:rgba(242,194,48,.12);
--barbg:rgba(126,166,224,.15);--good:#5FC48C;--goodbg:rgba(95,196,140,.12);--bad:#F0806C;
--badbg:rgba(240,128,108,.13);--warn:#E9B24E;--warnbg:rgba(233,178,78,.13);--goldink:#F2C230;--focus:#7EB0FF;
--shadow:0 1px 2px rgba(0,0,0,.3);color-scheme:dark}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:118px;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Barlow,-apple-system,"Segoe UI",
"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{color:inherit}h2,h3,h4,p{margin:0}code{font:13px ui-monospace,Menlo,monospace;background:var(--line2);padding:1px 5px;border-radius:5px}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:6px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.muted{color:var(--muted)}.small{font-size:13px}.block{display:block}.nowrap{white-space:nowrap}.pad{padding:8px 0}
.ic{width:16px;height:16px;flex:none;vertical-align:-3px}.ic.tiny{width:13px;height:13px;vertical-align:-2px}
/* top bar */
.top{position:sticky;top:0;z-index:20;background:#101E33;color:#fff;box-shadow:0 1px 0 rgba(242,194,48,.55)}
.topin{max-width:1240px;margin:0 auto;padding:12px 24px 8px;display:flex;align-items:center;gap:16px}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;min-width:0}
.brand .logo{width:30px;height:30px;flex:none}
.brand b{display:block;font:800 18px/1 "Barlow Condensed",Barlow,sans-serif;letter-spacing:.04em;text-transform:uppercase}
.brand em{display:block;font:500 12px/1.3 Barlow,sans-serif;font-style:normal;color:#AEB9CC;letter-spacing:.02em}
.gen{margin-left:auto;font-size:13px;color:#C9D2E1;white-space:nowrap;font-variant-numeric:tabular-nums}
.live{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:#BFE8CF;
background:rgba(95,196,140,.14);border:1px solid rgba(95,196,140,.3);border-radius:999px;padding:3px 10px;white-space:nowrap}
.live::before{content:"";width:7px;height:7px;border-radius:50%;background:#5FC48C;box-shadow:0 0 0 3px rgba(95,196,140,.22)}
.stale{margin:0 0 16px;padding:12px 16px;border-radius:12px;border:1px solid var(--warn);background:var(--warnbg);
color:var(--ink);font-size:14px;font-weight:600}
.theme{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);color:#fff;border-radius:8px;
width:34px;height:34px;display:grid;place-items:center;cursor:pointer}
.theme:hover{background:rgba(255,255,255,.14)}.theme .sun{display:none}
:root[data-theme="dark"] .theme .sun{display:block}:root[data-theme="dark"] .theme .moon{display:none}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .theme .sun{display:block}
:root:not([data-theme="light"]) .theme .moon{display:none}}
.tabs{overflow-x:auto;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
.tabsin{max-width:1240px;margin:0 auto;padding:0 16px;display:flex;gap:2px}
.tabs a{position:relative;display:flex;align-items:center;gap:6px;padding:9px 10px 11px;color:#AEB9CC;
text-decoration:none;font-weight:600;font-size:14px;white-space:nowrap;border-bottom:2px solid transparent}
.tabs a:hover{color:#fff}.tabs a.on{color:#fff;border-bottom-color:var(--gold)}
.badge{min-width:20px;height:20px;padding:0 6px;border-radius:10px;background:rgba(255,255,255,.16);color:#fff;
font-size:12px;font-weight:700;display:inline-grid;place-items:center;font-variant-numeric:tabular-nums}
.badge.hot{background:#D2533F}
/* layout */
.wrap{max-width:1240px;margin:0 auto;padding:24px 24px 64px}
.sec{margin-top:44px}.sech{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:16px}
.sech h2{font:800 26px/1.1 "Barlow Condensed",Barlow,sans-serif;letter-spacing:.03em;text-transform:uppercase}
.lead{color:var(--ink2);margin-top:4px;font-size:14.5px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px;box-shadow:var(--shadow);min-width:0}
.cardhead{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}
.card h3{font-size:15px;font-weight:700;letter-spacing:.005em}.card h4{font-size:13px;font-weight:700;margin:18px 0 8px;color:var(--ink2)}
.unit{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:600;white-space:nowrap}
.big{font-size:28px;font-weight:600;line-height:1}.big.bad{color:var(--bad)}.big.good{color:var(--good)}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.vs>*+*{margin-top:16px}
.grid-funnel{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:16px}
.stack{display:grid;gap:16px;align-content:start}
.grid-money{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:16px}
.grid-cust{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:start}.grid-cust .wide{grid-column:1/-1}.delivery{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:28px}.dside{display:grid;gap:18px;align-content:start}.card h4.first{margin-top:0;display:flex;align-items:center;justify-content:space-between}.big.inline{font-size:20px}
.grid-issues{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:16px;align-items:start}
.grid-record{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}
/* attention */
.attn{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--bad);border-radius:14px;
padding:16px 20px;box-shadow:var(--shadow)}
.attn.clear{display:flex;gap:12px;align-items:center;border-left-color:var(--good)}
.attnhead{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.aic{width:22px;height:22px;color:var(--bad);flex:none}.attn.clear .aic{color:var(--good)}
.at{font-weight:700;font-size:16px}.ad{color:var(--ink2);font-size:14px}
.attnhead .more{margin-left:auto;font-size:13px;font-weight:600;color:var(--ink2);text-decoration:none}
.attnhead .more:hover{color:var(--ink)}
/* filters + chips */
.filters{display:flex;align-items:center;gap:10px 14px;flex-wrap:wrap;margin:22px 0 4px}
.seg{display:inline-flex;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:3px;box-shadow:var(--shadow)}
.seg button{font:600 14px Barlow,sans-serif;border:0;background:none;color:var(--ink2);padding:6px 14px;border-radius:7px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--navy);color:#fff}
:root[data-theme="dark"] .seg button[aria-pressed="true"]{background:var(--gold);color:#101E33}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .seg button[aria-pressed="true"]{background:var(--gold);color:#101E33}}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-left:auto}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;padding:4px 10px;border-radius:999px;
background:var(--surface);border:1px solid var(--line);color:var(--ink2);white-space:nowrap}
.chip i{width:7px;height:7px;border-radius:50%;background:var(--line);flex:none}
.chip.good i{background:var(--good)}.chip.bad i{background:var(--bad)}.chip.warn i{background:var(--warn)}.chip.warn{background:var(--warnbg);border-color:transparent;color:var(--warn)}.chip.warn em{color:var(--warn)}.chip.bad{background:var(--badbg);border-color:transparent;color:var(--bad)}.chip.bad em{color:var(--bad)}.srcs{position:relative}.srcs summary{cursor:pointer;list-style:none}.srcs summary::-webkit-details-marker{display:none}.caret{font-size:10px;color:var(--muted);margin-left:2px}.srclist{position:absolute;z-index:10;top:calc(100% + 6px);right:0;min-width:300px;list-style:none;margin:0;padding:8px 0;background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 32px rgba(16,30,51,.14)}.srclist li{display:flex;align-items:center;gap:8px;padding:6px 14px;font-size:13px}.srclist li i{width:7px;height:7px;border-radius:50%;background:var(--muted);flex:none}.srclist li.good i{background:var(--good)}.srclist li.warn i{background:var(--warn)}.srclist li.bad i{background:var(--bad)}.srclist li span{margin-left:auto;color:var(--muted);white-space:nowrap}.srclist b{font-weight:600}
.chip em{font-style:normal;color:var(--muted)}
/* period switching */
body[data-period="7d"] .pv:not([data-p="7d"]),body[data-period="30d"] .pv:not([data-p="30d"]),
body[data-period="all"] .pv:not([data-p="all"]){display:none}
/* KPIs */
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.kpi{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 16px 0;
box-shadow:var(--shadow);overflow:hidden;display:flex;flex-direction:column;min-height:146px}
.kl{font-size:13px;color:var(--muted);font-weight:600}
.kval{font-size:34px;font-weight:600;line-height:1.1;margin:6px 0 6px;letter-spacing:-.01em}
.krow{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ks{font-size:12px;color:var(--muted)}
.kpi .spark{margin:auto -16px 0;width:calc(100% + 32px);height:38px;display:block}
.kpi.off{background:var(--surface2);box-shadow:none;border-style:dashed}.kpi.off .kval{color:var(--muted)}
.kpi.off .ks{display:flex;align-items:center;gap:5px;margin-top:2px}
.spark .l{fill:none;stroke:var(--series);stroke-width:1.75;vector-effect:non-scaling-stroke;stroke-linejoin:round}
.spark .a{stroke:none}.g0{stop-color:var(--series);stop-opacity:.22}.g1{stop-color:var(--series);stop-opacity:0}.spark.empty line{stroke:var(--line);stroke-width:1;vector-effect:non-scaling-stroke}
.delta{display:inline-flex;align-items:center;gap:3px;font-size:12.5px;font-weight:700;padding:2px 7px;border-radius:6px;
font-variant-numeric:tabular-nums}.delta.good{color:var(--good);background:var(--goodbg)}
.delta.bad{color:var(--bad);background:var(--badbg)}.delta.new{color:var(--series);background:var(--wash)}.delta.flat{color:var(--muted);background:var(--line2);font-weight:600}
/* area chart */
.chartcard .cardhead{flex-wrap:wrap}
.area{position:relative;margin:4px 0 0;padding:0 0 22px 40px}
.area .plot{position:relative;height:240px;outline:none}
.area svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.area .grid line{stroke:var(--line2);stroke-width:1;vector-effect:non-scaling-stroke}
.area .base{stroke:var(--line);stroke-width:1;vector-effect:non-scaling-stroke}
.area .line{fill:none;stroke:var(--series);stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}
.area .fill{stroke:none}
.yaxis{position:absolute;left:0;top:0;height:240px;width:34px}
.yaxis span,.xaxis span{position:absolute;font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.yaxis span{right:0;transform:translateY(-50%)}.xaxis{position:absolute;left:40px;right:0;bottom:0;height:18px}
.xaxis span{transform:translateX(-50%);top:3px}.xaxis span:first-child{transform:none}.xaxis span:last-child{transform:translateX(-100%)}
.xhair{position:absolute;top:0;bottom:0;width:1px;background:var(--ink2);opacity:.35;pointer-events:none}
.hdot{position:absolute;width:10px;height:10px;border-radius:50%;background:var(--series);
box-shadow:0 0 0 2px var(--surface);transform:translate(-50%,-50%);pointer-events:none}
.tip{position:absolute;top:8px;min-width:150px;background:var(--navy);color:#fff;border-radius:10px;padding:9px 12px;
font-size:12.5px;pointer-events:none;box-shadow:0 8px 24px rgba(0,0,0,.18);z-index:3}
:root[data-theme="dark"] .tip{background:#22314B}
.tip b{display:block;font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}.tip .td{color:#AEB9CC}
.tip .tr{display:flex;justify-content:space-between;gap:14px;color:#D6DDE8;font-variant-numeric:tabular-nums}
.devices{min-width:220px}.segbar{display:flex;gap:2px;height:8px;border-radius:4px;overflow:hidden;background:var(--line2)}
.dseg{height:100%}.dseg.s0{background:var(--series)}.dseg.s1{background:var(--series2)}.dseg.s2{background:var(--muted)}
.legend{display:flex;gap:12px;margin-top:6px;font-size:12.5px;color:var(--ink2);flex-wrap:wrap}
.lg{display:inline-flex;align-items:center;gap:5px}.lg b{color:var(--ink);font-weight:600}
.sw{width:9px;height:9px;border-radius:3px;display:inline-block}.sw.s0{background:var(--series)}.sw.s1{background:var(--series2)}.sw.s2{background:var(--muted)}
/* bar lists */
.bars{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.bars li{position:relative;display:flex;align-items:center;justify-content:space-between;gap:12px;height:32px;padding:0 10px;font-size:14px}
.bars .bar{position:absolute;left:0;top:0;bottom:0;background:var(--barbg);border-radius:6px;min-width:4px}
.bars .lab{position:relative;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.bars .val{position:relative;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.bars .val em{font-style:normal;color:var(--muted);font-weight:500;font-size:12px;margin-left:8px;display:inline-block;width:34px;text-align:right}
.more{font-size:12.5px;color:var(--muted);margin-top:8px}.note{font-size:12px;color:var(--muted);margin-top:10px}
/* funnel */
.funnel{display:grid;gap:0}
.fstep{display:grid;grid-template-columns:170px minmax(0,1fr) 70px 100px;align-items:center;gap:12px;padding:6px 0}
.fl{font-weight:600;font-size:14px}.fbar{height:28px;background:var(--line2);border-radius:6px;overflow:hidden}
.fbar i{display:block;height:100%;background:var(--series);border-radius:6px}
.fn{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}.fp{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.fstep.na .fbar{background:repeating-linear-gradient(135deg,var(--line2),var(--line2) 6px,transparent 6px,transparent 12px)}
.drop{display:flex;gap:12px;align-items:center;padding:0 0 0 182px;font-size:12px;font-variant-numeric:tabular-nums}
.drop .keep{color:var(--good);font-weight:700}.drop .lost{color:var(--bad)}
/* money */
.minis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.mini{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}
.mv{font-size:24px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}.mini.net{background:var(--navy);border-color:var(--navy);color:#fff}.mini.net .kl{color:#C9D2E1}:root[data-theme="dark"] .mini.net{background:rgba(242,194,48,.10);border-color:rgba(242,194,48,.45)}@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .mini.net{background:rgba(242,194,48,.10);border-color:rgba(242,194,48,.45)}}.minis.conv .mini{box-shadow:none;background:var(--surface2)}.minis.conv .mv{font-size:22px}
.convs{display:grid;gap:14px}.conv .mv{font-size:22px}
.cols{position:relative;padding:0 0 22px 34px}
.yax{position:absolute;left:0;top:0;bottom:22px;display:flex;flex-direction:column;justify-content:space-between;font-size:11.5px;color:var(--muted)}
.colplot{display:flex;align-items:flex-end;gap:2px;height:170px;border-bottom:1px solid var(--line)}
.col{flex:1;height:100%;display:flex;align-items:flex-end;position:relative;outline:none;min-width:0}
.col i{display:block;width:100%;max-width:24px;margin:0 auto;background:var(--series);border-radius:4px 4px 0 0}
.col:hover i,.col:focus i{opacity:.75}
.col:hover::after,.col:focus::after{content:attr(data-tip);position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);
background:var(--navy);color:#fff;padding:5px 9px;border-radius:7px;font-size:12px;white-space:nowrap;z-index:4}
.colx{position:absolute;left:34px;right:0;bottom:0;height:18px}
.colx span{position:absolute;transform:translateX(-50%);font-size:11.5px;color:var(--muted);top:3px;white-space:nowrap}
/* tables, lists */
.tablewrap{overflow-x:auto;max-width:100%}
.tbl{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}
.tbl th{text-align:left;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em;padding:0 10px 8px;border-bottom:1px solid var(--line)}
.tbl td{padding:9px 10px;border-bottom:1px solid var(--line2);vertical-align:middle}
.tbl tr:last-child td{border-bottom:0}.tbl th:first-child,.tbl td:first-child{padding-left:0}
.tbl td.num{font-weight:700}.tbl .r{text-align:right}
.kv{list-style:none;margin:0;padding:0}.kv li{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--line2);font-size:14px}
.kv li:last-child{border-bottom:0}.kv b{font-variant-numeric:tabular-nums;font-weight:600}
.seats li span:first-child{width:56px;flex:none}.seats li b{white-space:nowrap;min-width:60px;text-align:right}
.meter{display:inline-block;width:100%;min-width:70px;height:8px;background:var(--line2);border-radius:4px;overflow:hidden;vertical-align:middle}
.meter i{display:block;height:100%;border-radius:4px;background:var(--series)}.meter i.met{background:var(--good)}.meter i.behind{background:var(--warn)}
.pill{display:inline-flex;align-items:center;font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px;
background:var(--line2);color:var(--ink2);white-space:nowrap;letter-spacing:.02em}
.pill.good{background:var(--goodbg);color:var(--good)}.pill.warn{background:var(--warnbg);color:var(--warn)}
.pill.sev-critical{background:#C2412D;color:#fff}.pill.sev-high{background:var(--badbg);color:var(--bad)}
.pill.sev-medium{background:var(--warnbg);color:var(--warn)}.pill.sev-low{background:var(--line2);color:var(--ink2)}
.pills{display:flex;gap:6px;flex-wrap:wrap}
/* issues + insights */
.issues,.insights{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.issue,.ins{display:flex;gap:12px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}
.attn .issue{box-shadow:none;border:0;border-top:1px solid var(--line2);border-radius:0;padding:12px 0 4px}
.iic{width:20px;height:20px;flex:none;margin-top:1px;color:var(--muted)}
.sev-critical .iic,.sev-high .iic{color:var(--bad)}.sev-medium .iic{color:var(--warn)}
.it{font-weight:600;line-height:1.45}.it .pill{margin-right:8px;vertical-align:1px}
.iarea{font-size:12px;color:var(--muted);font-weight:600;margin-right:6px;text-transform:uppercase;letter-spacing:.05em}
.fix{color:var(--ink2);font-size:14px;margin-top:4px}.fix b{color:var(--ink)}
.go{font-weight:600;color:var(--ink);white-space:nowrap;text-decoration:none;border-bottom:1px solid var(--line)}.go.quiet{color:var(--ink2);font-weight:500}.golinks{display:inline-flex;gap:14px;flex-wrap:wrap}.steps{margin:4px 0 6px;padding-left:20px}.steps li{padding:1px 0}.steps li::marker{color:var(--muted);font-weight:600}div.fix .golinks{display:flex}
.basis{font-size:12px;color:var(--muted);margin-top:6px}
.ins.good .iic{color:var(--good)}.ins.warn .iic{color:var(--warn)}.ins.info .iic{color:var(--series)}
.insights{grid-template-columns:repeat(2,minmax(0,1fr))}
.state{font-weight:600;font-size:13px;text-transform:capitalize}.state.good{color:var(--good)}.state.bad{color:var(--bad)}.state.warn{color:var(--warn)}
.wf{font-weight:600;text-decoration:none}.wf:hover{text-decoration:underline}
.dots{display:inline-flex;gap:3px}.d{width:8px;height:14px;border-radius:2px;background:var(--line)}
.d.good{background:var(--good);opacity:.75}.d.bad{background:var(--bad)}.d.warn{background:var(--warn);opacity:.7}
/* empty states */
.empty,.allclear{display:flex;gap:16px;align-items:flex-start;background:var(--surface2);border:1px dashed var(--line);border-radius:14px;padding:22px}
.empty.compact{padding:16px;border-radius:12px}.empty.err{border-color:var(--bad);border-style:solid;background:var(--badbg)}
.eic{width:40px;height:40px;flex:none;padding:9px;border-radius:12px;background:var(--surface);border:1px solid var(--line);color:var(--goldink)}
.empty.err .eic{color:var(--bad)}.allclear .eic{color:var(--good)}
.needs{display:flex;align-items:center;gap:8px;color:var(--ink2);font-size:14px;padding:14px 16px;border:1px dashed var(--line);border-radius:12px;background:var(--surface2)}.needs .ic{color:var(--goldink)}.et{font-weight:700}.ed{color:var(--ink2);font-size:14px;margin-top:2px}.es{color:var(--muted);font-size:13px;margin-top:6px}.es b{color:var(--ink2)}
/* record */
.calwrap{display:flex;justify-content:center}.calib{width:100%;max-width:340px;height:auto}
.calib .grid line{stroke:var(--line2)}.calib text{fill:var(--muted);font:11px Barlow,sans-serif}
.calib .diag{stroke:var(--ink2);stroke-width:1;opacity:.4}.calib circle{fill:var(--series);stroke:var(--surface);stroke-width:2;opacity:.9}
.calib .axl{font-weight:600}
/* footer */
.foot{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);display:grid;gap:10px}
.consoles{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.consoles a{display:inline-flex;align-items:center;gap:5px;text-decoration:none;font-weight:600;font-size:14px;
padding:6px 12px;border:1px solid var(--line);border-radius:9px;background:var(--surface)}
.consoles a:hover{border-color:var(--ink2)}.consoles .muted{margin-right:4px;font-size:13px}
.pmark{position:absolute;top:0;bottom:0;width:0;border-left:1.5px dashed var(--gold);opacity:.75;pointer-events:auto}
.pmark::after{content:"";position:absolute;top:-4px;left:-5px;width:9px;height:9px;border-radius:50%;background:var(--gold);
box-shadow:0 0 0 2px var(--surface)}
.be{margin-top:16px;padding-top:14px;border-top:1px solid var(--line2)}
.bebar{height:10px;border-radius:999px;background:var(--line2);overflow:hidden}
.bebar i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--good),#3FA36B)}
.be-line{margin:10px 0 2px;font-size:15px}
.due{list-style:none;margin:0;padding:0}.due li{display:flex;gap:12px;align-items:baseline;padding:9px 0;
border-bottom:1px solid var(--line2);font-size:14px}.due li:last-child{border-bottom:0}
.due li span{color:var(--muted);width:56px;flex:none;font-variant-numeric:tabular-nums}
.due li em{margin-left:auto;font-style:normal;font-weight:600;font-variant-numeric:tabular-nums}
.card.profit .minis{margin-top:4px}.tbl.posts td b{font-weight:600}
@media (max-width:1180px){.kpis{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media (max-width:960px){.delivery,.grid-funnel,.grid-money,.grid-issues,.grid-record{grid-template-columns:minmax(0,1fr)}
.insights{grid-template-columns:minmax(0,1fr)}}
@media (max-width:700px){.hm{display:none}.gates thead{display:none}.gates tr{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 12px;padding:12px 0;border-bottom:1px solid var(--line2)}.gates tr:last-child{border-bottom:0}.gates td{padding:0!important;border:0!important}.gates td:nth-child(1){grid-column:1;grid-row:2;color:var(--muted);font-size:12.5px}.gates td:nth-child(2){grid-column:1/-1;grid-row:1;font-weight:600}.gates td:nth-child(3){grid-column:1;grid-row:3;color:var(--ink2)}.gates td:nth-child(3)::before{content:"Green: ";color:var(--muted)}.gates td:nth-child(4){grid-column:2;grid-row:3;text-align:right}.gates td:nth-child(5){grid-column:1/-1;grid-row:4}.gates td:nth-child(6){grid-column:2;grid-row:2;text-align:right}.xaxis span:nth-child(even):not(:last-child),.colx span:nth-child(even){display:none}.kpis>:last-child:nth-child(odd){grid-column:1/-1}.brand b{font-size:16px;white-space:nowrap}.brand .logo{width:26px;height:26px}.srclist{position:static;min-width:0;margin-top:8px}.srcs[open]{flex-basis:100%}.chips{margin-left:0}.fnote{display:none}.wrap{padding:16px 16px 48px}.topin{padding:10px 16px 6px;gap:10px}.tabsin{padding:0 8px}
.brand em{display:none}.gen{font-size:12px}.live{font-size:0;padding:4px}.live::before{margin:0}.grid2,.grid-cust{grid-template-columns:minmax(0,1fr)}
.kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.kpi{min-height:132px;padding:14px 14px 0}.kval{font-size:28px}
.kpi .spark{margin:auto -14px 0;width:calc(100% + 28px)}
.sech{flex-direction:column;align-items:flex-start}.sech h2{font-size:23px}.card{padding:16px;border-radius:12px}
.fstep{grid-template-columns:minmax(0,1fr) auto;gap:4px 10px}.fstep .fbar{grid-column:1/-1;grid-row:2}
.fstep .fp{grid-column:1/-1;grid-row:3}.drop{padding-left:0}.area .plot,.yaxis{height:190px}
.devices{min-width:0;width:100%}.cardhead{flex-wrap:wrap}.filters{margin-top:16px}
.tbl{font-size:13px}.tbl th,.tbl td{padding-left:6px;padding-right:6px}.empty{padding:16px}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""

JS = r"""
(function(){
"use strict";
var root=document.documentElement,body=document.body;
function get(k){try{return localStorage.getItem(k)}catch(e){return null}}
function put(k,v){try{localStorage.setItem(k,v)}catch(e){}}
var t=get("byl-dash-theme");if(t==="dark"||t==="light")root.setAttribute("data-theme",t);
document.querySelector(".theme").addEventListener("click",function(){
 var dark=root.getAttribute("data-theme")==="dark"||(!root.getAttribute("data-theme")&&matchMedia("(prefers-color-scheme: dark)").matches);
 var next=dark?"light":"dark";root.setAttribute("data-theme",next);put("byl-dash-theme",next);});
var btns=document.querySelectorAll("[data-period]");
function setP(p){body.setAttribute("data-period",p);for(var i=0;i<btns.length;i++){var b=btns[i];if(b.tagName==="BUTTON")b.setAttribute("aria-pressed",String(b.getAttribute("data-period")===p));}put("byl-dash-period",p);}
for(var i=0;i<btns.length;i++){if(btns[i].tagName==="BUTTON")btns[i].addEventListener("click",function(){setP(this.getAttribute("data-period"))});}
var sp=get("byl-dash-period");if(sp==="7d"||sp==="30d"||sp==="all")setP(sp);
var links=document.querySelectorAll(".tabs a"),secs=[];
for(var j=0;j<links.length;j++){var s=document.getElementById(links[j].getAttribute("data-nav"));if(s)secs.push([s,links[j]]);}
function onScroll(){var y=window.scrollY+window.innerHeight*.35,cur=secs[0];for(var k=0;k<secs.length;k++){if(secs[k][0].offsetTop<=y)cur=secs[k];}
 for(var k2=0;k2<secs.length;k2++)secs[k2][1].classList.toggle("on",secs[k2]===cur);
 if(cur&&cur[1].scrollIntoView&&cur[1].dataset.shown!=="1"){}}
window.addEventListener("scroll",onScroll,{passive:true});onScroll();
var charts=document.querySelectorAll("figure.area");
for(var c=0;c<charts.length;c++)(function(fig){
 var data;try{data=JSON.parse(fig.getAttribute("data-chart"))}catch(e){return}
 var plot=fig.querySelector(".plot"),x=fig.querySelector(".xhair"),d=fig.querySelector(".hdot"),tip=fig.querySelector(".tip");
 var n=data.tips.length;
 function show(i){var tp=data.tips[i];var w=plot.clientWidth,hgt=plot.clientHeight;var px=n>1?i/(n-1)*w:w/2;
  var py=hgt-tp.v/data.top*hgt;x.hidden=false;d.hidden=false;tip.hidden=false;x.style.left=px+"px";d.style.left=px+"px";d.style.top=py+"px";
  tip.textContent="";var dd=document.createElement("div");dd.className="td";dd.textContent=tp.d;tip.appendChild(dd);
  var b=document.createElement("b");b.textContent=tp.v.toLocaleString()+" views";tip.appendChild(b);
  for(var q=0;q<tp.x.length;q++){var r=document.createElement("div");r.className="tr";var a=document.createElement("span");a.textContent=tp.x[q][0];
   var v=document.createElement("span");v.textContent=String(tp.x[q][1]);r.appendChild(a);r.appendChild(v);tip.appendChild(r);}
  var tw=tip.offsetWidth;var left=px+14;if(left+tw>w)left=px-tw-14;if(left<0)left=0;tip.style.left=left+"px";}
 function hide(){x.hidden=true;d.hidden=true;tip.hidden=true;}
 function at(e){var r=plot.getBoundingClientRect();var f=(e.clientX-r.left)/r.width;show(Math.max(0,Math.min(n-1,Math.round(f*(n-1)))));}
 plot.addEventListener("pointermove",at);plot.addEventListener("pointerleave",hide);
 var cur=n-1;plot.addEventListener("focus",function(){show(cur)});plot.addEventListener("blur",hide);
 plot.addEventListener("keydown",function(e){if(e.key==="ArrowLeft"){cur=Math.max(0,cur-1);show(cur);e.preventDefault()}
  else if(e.key==="ArrowRight"){cur=Math.min(n-1,cur+1);show(cur);e.preventDefault()}});
})(charts[c]);
var refresh=+body.getAttribute("data-refresh")||0,gen=+body.getAttribute("data-generated")||0;
if(refresh&&gen){
 try{var y=sessionStorage.getItem("byl-dash-y");if(y!==null){sessionStorage.removeItem("byl-dash-y");window.scrollTo({top:+y,behavior:"instant"});}}catch(e){}
 var stale=document.querySelector(".stale");
 function reload(){try{sessionStorage.setItem("byl-dash-y",String(window.scrollY))}catch(e){}location.reload();}
 function tick(){var age=Date.now()-gen;
  if(stale)stale.hidden=age<(2*refresh+120)*1000;
  // The rebuild lands within a minute or so of its slot; never reload faster
  // than once a minute, so a stopped loop can't make the page spin.
  var wait=Math.max(gen+(refresh+45)*1000-Date.now(),60000);
  setTimeout(function(){if(document.hidden){document.addEventListener("visibilitychange",function v(){
   if(!document.hidden){document.removeEventListener("visibilitychange",v);reload();}});}else reload();},wait);}
 tick();}
})();
"""


# --------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------- #

def env_from(environ: Mapping[str, str], env_file: Path) -> dict[str, str]:
    """This shell first, then the gitignored .env — run.stats' reader."""
    found = stats.read_env_file(env_file, ENV_NAMES)
    return {name: environ.get(name) or found.get(name, "") for name in ENV_NAMES}


def write_dashboard(sources: Mapping[str, Source], out: Path, now: datetime,
                    root: Path = REPO_ROOT, env: Mapping[str, str] | None = None,
                    live_minutes: int | None = None) -> Path:
    page = render_page(sources, now, root, env=env or {}, live_minutes=live_minutes)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and swapped in, so a reload mid-write never
    # reads half a page.
    tmp = out.with_name(f".{out.name}.tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, out)
    return out


def cli(argv: list[str] | None = None, environ: Mapping[str, str] | None = None,
        env_file: Path | None = None,
        collectors: Mapping[str, Callable[[Context], Source]] | None = None,
        opener: Callable[[Path], None] | None = None,
        sleep: Callable[[float], None] | None = None) -> int:
    environ = os.environ if environ is None else environ
    if stats.in_ci(environ):
        print("make dashboard does not run in CI: the repository is public, so the job "
              "log would publish sales and traffic. Run it on your own machine.", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="where to write the page (must be gitignored; default data/dashboard.html)")
    parser.add_argument("--registry", type=Path, default=None,
                        help="a registry copy to count subscribers and seats from")
    parser.add_argument("--no-open", action="store_true", help="write the page, don't open it")
    parser.add_argument("--now", help="pretend it is this ISO time (for checks)")
    parser.add_argument("--every", type=int, default=None, metavar="MINUTES",
                        help=f"live mode: rebuild every MINUTES (at least {LIVE_MIN_MINUTES}) until "
                             "Ctrl-C; the open page reloads itself")
    parser.add_argument("--rounds", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.every is not None and args.every < LIVE_MIN_MINUTES:
        print(f"--every must be at least {LIVE_MIN_MINUTES} minutes: GitHub allows 60 unsigned "
              f"requests an hour and each build makes one per workflow.", file=sys.stderr)
        return 2
    now = (stats._when(args.now) if args.now else None) or datetime.now(timezone.utc)
    if not stats._gitignored(args.out):
        print(f"{args.out} is not gitignored, so the counts could be committed to a public "
              f"repository — use a path such as data/dashboard.html.", file=sys.stderr)
        return 2
    env = env_from(environ, env_file or stats.ENV_FILE)
    if args.every is None:
        out = _build(env, now, args, collectors)
        if not args.no_open:
            (opener or _open)(out)
        return 0
    # Live mode. One round failing (a network blip, a provider error) keeps
    # the last good page up and tries again next round; the page itself turns
    # amber when its numbers are older than two rounds.
    rounds = 0
    try:
        while True:
            now = (stats._when(args.now) if args.now else None) or datetime.now(timezone.utc)
            try:
                out = _build(env, now, args, collectors, live_minutes=args.every, quiet=rounds > 0)
                print(f"{now.astimezone(ET):%-I:%M %p} ET  updated; next in {args.every} min "
                      f"(Ctrl-C stops)", file=sys.stderr)
                if rounds == 0 and not args.no_open:
                    (opener or _open)(out)
            except Exception as exc:  # noqa: BLE001 — a bad round must not end the loop
                print(f"{now.astimezone(ET):%-I:%M %p} ET  this update failed "
                      f"({scrub(type(exc).__name__ + ': ' + str(exc), env)}); the last page stays up",
                      file=sys.stderr)
            rounds += 1
            if args.rounds and rounds >= args.rounds:
                return 0
            (sleep or time.sleep)(args.every * 60)
    except KeyboardInterrupt:
        print("\nStopped. The page keeps its last numbers and will say they've stopped updating.",
              file=sys.stderr)
        return 0


def _build(env: Mapping[str, str], now: datetime, args: argparse.Namespace,
           collectors: Mapping[str, Callable[[Context], Source]] | None,
           live_minutes: int | None = None, quiet: bool = False) -> Path:
    ctx = Context(env=env, now=now, registry=args.registry)
    if not quiet:
        print("Reading your sources (read-only)…", file=sys.stderr)
    sources = collect_all(ctx, collectors)
    if not quiet:
        for src in sources.values():
            mark = {"ok": "✓", "off": "–", "error": "✗"}[src.status]
            print(f"  {mark} {src.label}" + (f": {scrub(src.note, env)}" if src.note else ""),
                  file=sys.stderr)
    out = write_dashboard(sources, args.out, now, env=env, live_minutes=live_minutes)
    if not quiet:
        print(f"Written to {out}", file=sys.stderr)
    return out


def _open(path: Path) -> None:
    try:
        subprocess.run(["open", str(path)], check=False, timeout=20)
    except (OSError, subprocess.SubprocessError):
        print(f"Open {path} in your browser.", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(cli())
