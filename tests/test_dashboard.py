"""`make dashboard` — the owner's private page (run/dashboard.py).

Every source is faked here; nothing touches the network. The properties that
matter are the ones a public repository and a pasted screenshot can hurt:
it never runs in CI, it writes only to a gitignored path, it never carries an
address or a secret, it loads nothing from anywhere, and one source failing
or missing never takes the page down.
"""

from __future__ import annotations

import math
import os
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.dashboard as dash
import run.stats as stats
from run.dashboard import Context, Source

NOW = datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
LEAK = "leak.me+tag@fans.mail"
SECRET = "rk_live_SECRETSECRETSECRET123"
CF_TOKEN = "cf-token-VERYSECRET-0123456789"


@pytest.fixture(autouse=True)
def _quiet_env(monkeypatch):
    for name in dash.ENV_NAMES + ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------- #
# a realistic mid-season scenario, every source populated
# --------------------------------------------------------------------- #

PAGES = (("index", 46), ("join", 17), ("sample", 11), ("this-week", 8), ("how-it-works", 5),
         ("planner", 7), ("join-try", 4), ("league-pass", 2))
REFS = (("", 38), ("reddit.com", 22), ("x.com", 14), ("t.co", 8), ("google.com", 9),
        ("discord.com", 6), ("beatyourleague.com", 3))
VIAS = (("", 52), ("reddit", 12), ("reddit-oct20", 6), ("x", 8), ("x-thread1", 4), ("discord", 9),
        ("groupchat", 6), ("newsletter", 3))
COUNTRIES = (("US", 82), ("CA", 10), ("GB", 3), ("AU", 2), ("IE", 1), ("DE", 1), ("XX", 1))


def _pick(rng, table):
    total = sum(w for _v, w in table)
    x = rng.uniform(0, total)
    for value, weight in table:
        x -= weight
        if x <= 0:
            return value
    return table[-1][0]


def traffic_events(now: datetime = NOW, days: int = 60, seed: int = 7) -> list[dict]:
    """Event-level counter lines, growing towards the present."""
    rng = random.Random(seed)
    out = []
    today = now.date()
    for back in range(days):
        day = today - timedelta(days=back)
        base = 40 + (days - back) * 2.1 + (25 if day.weekday() == 1 else 0)
        for _ in range(int(base * rng.uniform(.8, 1.2))):
            page = _pick(rng, PAGES)
            dev = "m" if rng.random() < .62 else "d"
            line = {"day": day.isoformat(), "e": "view", "p": page, "v": _pick(rng, VIAS),
                    "r": _pick(rng, REFS), "d": dev, "s": "", "c": _pick(rng, COUNTRIES)}
            out.append(line)
            if page in ("join", "join-try", "planner") and rng.random() < (.32 if dev == "d" else .17):
                out.append({**line, "e": "roster"})
                if page == "join" and rng.random() < .45:
                    out.append({**line, "e": "checkout", "s": "open" if back < 4 else "closed"})
                if page == "join-try" and rng.random() < .6:
                    out.append({**line, "e": "trial"})
                if page == "planner" and rng.random() < .3:
                    out.append({**line, "e": "waitlist"})
            if page == "index" and rng.random() < .03:
                out.append({**line, "e": "waitlist"})
    return out


def aggregate(events: list[dict], now: datetime, days: int) -> list[dict]:
    since = (now - timedelta(days=days)).date()
    agg: dict[tuple, int] = {}
    for e in events:
        if date.fromisoformat(e["day"]) > since:
            key = tuple(e[k] for k in "epvrdsc")
            agg[key] = agg.get(key, 0) + 1
    return [dict(zip("epvrdsc", k), n=n) for k, n in agg.items()]


def daily(events: list[dict]) -> list[dict]:
    agg: dict[tuple, int] = {}
    for e in events:
        key = (e["day"], e["e"], e["p"], e["s"], e["v"])
        agg[key] = agg.get(key, 0) + 1
    return [{"day": d, "e": e, "p": p, "s": s, "v": v, "n": n} for (d, e, p, s, v), n in agg.items()]


def traffic_source(now: datetime = NOW) -> Source:
    ev = traffic_events(now)
    return dash._source("traffic", data={"rows": {"7d": aggregate(ev, now, 7),
                                                  "30d": aggregate(ev, now, 30),
                                                  "all": aggregate(ev, now, 90)},
                                         "daily": daily(ev)}, read_at=now)


def stripe_sessions(now: datetime = NOW, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    out = []
    kinds = [("Rest-of-Season", 29.0)] * 16 + [("League Pass", 69.0)] * 2
    for i, (kind, price) in enumerate(kinds):
        created = int((now - timedelta(days=rng.uniform(0, 6) if i < 9 else rng.uniform(6, 26))
                       ).timestamp())
        out.append({"id": f"cs_test_{i:04d}", "created": created, "status": "complete", "paid": True,
                    "via": _pick(rng, (("reddit", 3), ("reddit-oct20", 2), ("x", 3), ("discord", 2),
                                       ("groupchat", 2), (None, 6))),
                    "pass": kind, "amount": price, "refunded": 0.0, "full_refund": False,
                    "dispute": None, "payment": f"pi_test_{i:04d}", "who": f"w{i:03d}"})
    out[3].update(refunded=29.0, full_refund=True)
    out[12].update(dispute="under_review")
    for i in range(7):
        out.append({"id": f"cs_test_x{i}", "created": int((now - timedelta(days=i)).timestamp()),
                    "status": "expired", "paid": False, "via": None})
    return out


def _hours_since(now: datetime, weekday: int, hour: int, minute: int) -> float:
    """Hours since the most recent ``weekday`` at hour:minute UTC."""
    back = (now.weekday() - weekday) % 7
    at = (now - timedelta(days=back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if at > now:
        at -= timedelta(days=7)
    return (now - at).total_seconds() / 3600


def rich_sources(now: datetime = NOW, root: Path = dash.REPO_ROOT) -> dict[str, Source]:
    rng = random.Random(11)
    forms_rows = []
    for i in range(190):
        forms_rows.append({"kind": "waitlist", "at": (now - timedelta(days=rng.uniform(0, 40))).isoformat(),
                           "via": _pick(rng, (("reddit", 3), ("x", 2), (None, 5))), "who": f"p{i % 170}"})
    for i in range(38):
        forms_rows.append({"kind": "trial", "at": (now - timedelta(days=rng.uniform(0, 30))).isoformat(),
                           "via": None, "who": f"w{i:03d}" if i < 5 else f"t{i}",
                           # 23 of the 38 were mailed (the send log's trial keys below).
                           "sent_code": f"{i:012x}"})
    for i, kind in enumerate(["update_request"] * 6 + ["confirm"] * 4 + ["seat"] * 7):
        forms_rows.append({"kind": kind, "at": (now - timedelta(days=rng.uniform(0, 12))).isoformat(),
                           "via": None, "who": f"s{i}"})
    summary = {k: {"total": sum(r["kind"] == k for r in forms_rows),
                   "week": sum(r["kind"] == k and dash._ts(r["at"]) > now - timedelta(days=7)
                               for r in forms_rows),
                   "day": sum(r["kind"] == k and dash._ts(r["at"]) > now - timedelta(days=1)
                              for r in forms_rows),
                   "people": len({r["who"] for r in forms_rows if r["kind"] == k})}
               for k in ("waitlist", "trial", "update_request", "confirm", "seat")}
    entries = []
    for week, n in ((7, 4), (8, 13)):
        for j in range(n):
            entries.append({"key": f"2026-w{week:02d}-{j:010x}", "sent_at": f"2026-10-{13 + week * 2}T13:00:00+00:00",
                            "provider": "resend"})
    entries += [{"key": f"trial-2026-{j:012x}", "sent_at": f"2026-10-2{6 + j % 2}T15:00:00+00:00", "provider": "resend"}
                for j in range(23)]
    entries += [{"key": f"welcome-2026-10-2{j % 8}-{j:010x}", "sent_at": f"2026-10-2{j % 8}T15:00:00+00:00",
                 "provider": "resend"} for j in range(18)]
    entries.append({"key": "2026-w08-final-0000000001", "sent_at": "2026-10-24T16:30:00+00:00",
                    "provider": "resend"})
    calls = []
    for week in (7, 8):
        for j in range(18 if week == 7 else 22):
            conf = round(rng.uniform(.52, .88), 3)
            status = "graded" if week == 7 else "pending"
            outcome = ("hit" if rng.random() < conf else "miss") if status == "graded" else None
            calls.append({"store": "typed-ppr-12-2026", "week": week, "confidence": conf, "status": status,
                          "outcome": outcome, "recorded_at": f"2026-10-{20 if week == 7 else 27}T17:00:00+00:00"})

    def runs(every_h: float, n: int, start_offset_h: float = 0, fail_at: tuple = ()) -> list[dict]:
        return [{"created_at": (now - timedelta(hours=start_offset_h + i * every_h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "status": "completed", "conclusion": "failure" if i in fail_at else "success",
                 "event": "schedule", "url": f"https://github.com/{dash.GITHUB_REPO}/actions/runs/{1000 + i}"}
                for i in range(n)]
    tue = now - timedelta(days=(now.weekday() - 2) % 7)
    tue_run = tue.replace(hour=13, minute=31)     # the Wednesday morning slot
    github = {
        "weekly.yml": {"label": "Wednesday reports", "runs": [
            {"created_at": (tue_run - timedelta(days=7 * k)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "status": "completed", "conclusion": "success", "event": "workflow_dispatch",
             "url": f"https://github.com/{dash.GITHUB_REPO}/actions/runs/2{k}"} for k in range(6)]},
        "saturday.yml": {"label": "Saturday check", "runs": runs(24 * 7, 6, _hours_since(now, 5, 16, 24))},
        "daily.yml": {"label": "Hourly intake", "runs": runs(1, 30, .3, fail_at=(9,))},
        "monday.yml": {"label": "Monday grading", "runs": runs(24 * 7, 6, _hours_since(now, 0, 13, 22))},
        "test.yml": {"label": "Tests", "runs": runs(5, 12, 1, fail_at=(0,))},
        "pages.yml": {"label": "Site deploy", "runs": runs(9, 12, 2)},
    }
    gates = [{"area": "Funnel", "name": "Checkout can take money", "status": "OWNER",
              "detail": "STRIPE_LINK_SEASON is empty"},
             {"area": "Email", "name": "Payouts in USD keep the currency-conversion fee", "status": "WARN",
              "detail": "a USD bank account saves about 2%"},
             {"area": "Site", "name": "Every internal link and asset resolves", "status": "PASS", "detail": ""}]
    S = {
        "traffic": traffic_source(now),
        "forms": dash._source("forms", data={"rows": forms_rows, "summary": summary,
                                             "channels": {}}, read_at=now),
        "stripe": dash._source("stripe", data={"sessions": stripe_sessions(now), "link_map": True,
                                               "dispute_errors": 0}, read_at=now),
        "intake": dash._source("intake", data={"problems": [
            "PAID-UNATTRIBUTED session cs_test_a1B2c3 paid through a payment link that is not in "
            "STRIPE_PAYMENT_LINKS — its plan is unknown"], "signups": 18}, read_at=now),
        "sends": dash._source("sends", data={"entries": entries, "season": "2026", "stopped": 2,
                                             "summary": stats.send_summary(entries, "2026")}, read_at=now),
        "registry": dash._source("registry", data={"total": 21, "plans": {"Pass holders": 16,
                                                                         "League Pass buyers": 2,
                                                                         "League Pass seats": 3},
                                                   "seats": [(2, 11), (1, 9)], "setups": {}}, read_at=now),
        "bounces": dash._source("bounces", data={"checked": 24, "errors": 0, "paid": ["bounced"],
                                                 "unpaid": []}, read_at=now),
        "github": dash._source("github", data=github, read_at=now),
        "launch": dash._source("launch", data={"gates": gates}, read_at=now),
        "ledger": dash._source("ledger", data={"season": "2026", "calls": calls, "unreadable": []},
                               read_at=now),
        "site": dash._source("site", data={"week": {"season": "2026", "week": 8, "phase": "season",
                                                    "built_at": (now - timedelta(hours=22)).isoformat()},
                                           "players_at": (now - timedelta(hours=22)).isoformat()},
                             read_at=now),
        "plan": dash._source("plan", data=dash.parse_plan_gates(plan_text(root, "2026-10-26")),
                             read_at=now),
        "books": dash._source("books", data=books_fixture(now), read_at=now),
    }
    return S


def plan_text(root: Path = dash.REPO_ROOT, d: str | None = None) -> str:
    """PLAN.md with its D line set to ``d`` (unwritten when None), whatever
    PLAN.md itself says today: D gets written there the day the owner adopts
    the gates (LAUNCH.md section 10), and a test that leaned on "D = ____"
    would break that day."""
    text = (root / "PLAN.md").read_text(encoding="utf-8")
    line = "(write the date here when it happens: D = "
    assert line in text, "PLAN §6's D line moved; parse_plan_gates reads it"
    return re.sub(rf"{re.escape(line)}[^)]*\)", f"{line}{d or '____'})", text, count=1)


def books_fixture(now: datetime = NOW):
    from run.books import Books, Cost, Hours, Post
    today = now.date()
    return Books(
        costs=[Cost(date(2026, 8, 1), "Domain", 12.0, "yearly"),
               Cost(date(2026, 9, 5), "Mailbox for the sender address", 9.99, "monthly"),
               Cost(date(2026, 10, 20), "Reddit ad test", 40.0, "once")],
        hours=[Hours(today - timedelta(days=k), 1.5, "") for k in range(20)],
        posts=[Post(date(2026, 10, 20), "reddit-oct20", "r/fantasyfootball", ""),
               Post(date(2026, 10, 25), "x-thread1", "X thread", "")],
        problems=[], found=("costs.csv", "hours.csv", "posts.csv"))


def empty_sources(now: datetime = NOW) -> dict[str, Source]:
    """Nothing connected: every source off."""
    return {k: dash.off(k, "Not connected in this test.") for k in dash.SOURCE_INFO}


# --------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------- #

def test_every_section_renders_from_the_rich_scenario() -> None:
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    for sid in ("overview", "traffic", "funnel", "money", "customers", "issues", "record", "insights"):
        assert f'id="{sid}"' in page and f'href="#{sid}"' in page
    # Overview KPIs carry numbers and deltas, the traffic chart its series.
    assert 'class="kpi"' in page and 'class="delta' in page
    assert page.count('<figure class="area"') == 3          # one per period
    assert "Top pages" in page and "Sources" in page and "Countries" in page
    # The funnel names every step down to the payment.
    for step in ("Landing views", "Buy-page views", "Rosters checked", "Buy pressed", "Paid"):
        assert step in page
    assert "continue" in page and "drop off" in page
    # Money: passes by type, the PLAN §6 gates read from PLAN.md itself.
    assert "Rest-of-Season" in page and "PLAN §6 decision gates" in page
    assert "D = 2026-10-26" in page and "Free reports sent" in page
    # Customers & ops: seats against cap, sends per week, bounces, stop list.
    assert "2 of 11" in page and "Weekly reports sent" in page and "Stop requests" in page
    # Issues: the intake's alarm leads, with its fix.
    assert "Somebody paid and the intake can" in page and "Do this:" in page
    # The record: graded calls by band.
    assert "Stated vs landed" in page and "Week 7" in page
    # Insights state their basis.
    assert "Based on:" in page


def test_the_attention_strip_leads_with_the_most_urgent_issue() -> None:
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    strip = page.split('class="attn"', 1)[1].split("</ol>", 1)[0]
    assert "Needs you now" in strip and "Critical" in strip
    assert strip.index("Somebody paid") < strip.index("bounced") if "bounced" in strip else True


def test_all_clear_when_nothing_is_wrong() -> None:
    S = empty_sources()
    page = dash.render_page(S, NOW, fonts=False)
    assert "attn clear" in page


@pytest.mark.parametrize("key", sorted(dash.SOURCE_INFO))
def test_every_unconnected_source_shows_its_setup_card(key: str) -> None:
    S = rich_sources()
    S[key] = dash.off(key, "Not connected in this test.")
    page = dash.render_page(S, NOW, fonts=False)
    label, setup, _shows = dash.SOURCE_INFO[key]
    if key in ("intake", "site", "launch", "plan"):
        # Sources with no panel of their own: their absence must not break the page.
        assert 'id="insights"' in page
        if key == "plan":
            assert "not connected yet" in page and dash.h(setup) in page
        return
    if key in dash.CONNECT_SOURCE_STEP:
        # A source with a step on the Connect card shrinks to one line naming it.
        step = dash.CONNECT_STEPS[dash.CONNECT_SOURCE_STEP[key] - 1]
        assert f"{dash.h(label)} isn't connected." in page
        assert (f"Needs step {step.n}: {dash.h(step.short)}" in page if not step.optional
                else dash.h(step.how) in page)
        return
    assert f"{dash.h(label)} — not connected yet" in page or "Not connected" in page
    assert dash.h(setup) in page or re.search(r"step [0-9a-z.]+", setup).group(0) in page


def test_nothing_connected_renders_setup_cards_everywhere() -> None:
    page = dash.render_page(empty_sources(), NOW, fonts=False)
    for step in ("LAUNCH.md step 5b", "LAUNCH.md step 3", "LAUNCH.md step 5 ", "LAUNCH.md step 2"):
        assert step.strip() in page
    assert page.count('class="kpi off"') == 8 * len(dash.PERIODS)


def test_one_source_raising_does_not_break_the_page() -> None:
    def boom(ctx):
        raise RuntimeError(f"Stripe exploded for {LEAK} with key {SECRET}")
    rich = rich_sources()
    collectors = {k: (lambda ctx, s=s: s) for k, s in rich.items()}
    collectors["stripe"] = boom
    ctx = Context(env={"STRIPE_API_KEY": SECRET}, now=NOW)
    sources = dash.collect_all(ctx, collectors)
    assert sources["stripe"].status == "error"
    assert SECRET not in sources["stripe"].note and LEAK not in sources["stripe"].note
    page = dash.render_page(sources, NOW, fonts=False)
    assert "couldn't be read" in page and 'id="traffic"' in page and "Top pages" in page
    assert SECRET not in page and LEAK not in page


def test_a_collector_returning_garbage_is_an_error_card_not_a_crash() -> None:
    sources = dash.collect_all(Context(env={}, now=NOW), {"forms": lambda ctx: "nonsense"})
    assert sources["forms"].status == "error"
    assert all(k in sources for k in dash.SOURCE_INFO)
    dash.render_page(sources, NOW, fonts=False)


# --------------------------------------------------------------------- #
# privacy: no address, no secret, no external request
# --------------------------------------------------------------------- #

def _raw_session(i: int, email: str) -> dict:
    return {"id": f"cs_live_{i}", "object": "checkout.session", "mode": "payment", "status": "complete",
            "payment_status": "paid", "client_reference_id": None, "created": int(NOW.timestamp()) - 3600 * i,
            "amount_total": 2900, "amount_subtotal": 2900, "currency": "usd",
            "customer_details": {"email": email}, "customer_email": email,
            "payment_intent": {"id": f"pi_{i}", "latest_charge": {"id": f"ch_{i}", "amount_refunded": 0,
                                                                 "refunded": False, "disputed": False}}}


def test_collectors_turn_addresses_into_digests_and_the_page_holds_none(monkeypatch, tmp_path) -> None:
    """Real collectors over fake transports, with an address and secrets in
    every field a provider could put one."""
    import run.intake as intake
    rows = [{"kind": "waitlist", "email": LEAK, "received_at": "2026-10-27T10:00:00Z", "via": LEAK},
            {"kind": "trial", "email": "Second.Person@gmail.com", "received_at": "2026-10-20T10:00:00Z",
             "via": "reddit"}]
    monkeypatch.setattr(intake, "fetch_seats", lambda endpoint, key=None: rows)
    ev = traffic_events(NOW, days=20)
    monkeypatch.setattr(stats, "counter_endpoint", lambda path=None: "https://forms.example/e")
    monkeypatch.setattr(stats, "query_counts", lambda a, t, days, **k: aggregate(ev, NOW, days))
    monkeypatch.setattr(dash, "query_daily", lambda a, t, days, **k: daily(ev))
    ref = _a_roster_ref()
    raw = [_raw_session(i, LEAK) | {"client_reference_id": ref} for i in range(3)]
    monkeypatch.setattr(stats, "_stripe_list", lambda path, params, key: raw)
    env = {"FORM_ENDPOINT": "https://forms.example", "FORM_API_KEY": SECRET,
           "CF_ACCOUNT_ID": "0" * 32, "CF_ANALYTICS_TOKEN": CF_TOKEN, "STRIPE_API_KEY": SECRET}
    ctx = Context(env=env, now=NOW)
    collectors = {k: dash.COLLECTORS[k] for k in ("traffic", "forms", "stripe")}
    sources = dash.collect_all(ctx, collectors)
    assert all(sources[k].ok for k in ("traffic", "forms", "stripe")), \
        {k: sources[k].note for k in ("traffic", "forms", "stripe")}
    assert LEAK not in repr(sources["forms"].data) and LEAK not in repr(sources["stripe"].data)
    assert sources["stripe"].data["sessions"][0]["paid"] is True
    out = dash.write_dashboard(sources, tmp_path / "d.html", NOW, env=env)
    page = out.read_text(encoding="utf-8")
    assert LEAK not in page and "Second.Person" not in page.lower().replace("second.person", "Second.Person") \
        or "second.person@gmail.com" not in page.lower()
    assert "@fans.mail" not in page and "@gmail.com" not in page
    for secret in (SECRET, CF_TOKEN):
        assert secret not in page


def _a_roster_ref() -> str:
    """A real, decodable roster reference, built by the join page's own encoder."""
    from run.refs import encode_roster
    from test_solo_run import SLOTS, _pid
    return encode_roster("season", "ppr", list(SLOTS), [_pid(i) for i in range(1, 9)])


def test_a_leaked_address_or_key_in_any_string_is_scrubbed() -> None:
    S = rich_sources()
    S["intake"].data["problems"].append(f"PAID-UNATTRIBUTED session cs_x: no email for {LEAK}")
    S["launch"].data["gates"].append({"area": "x", "name": f"gate for {LEAK}", "status": "FAIL",
                                      "detail": f"key {SECRET}"})
    page = dash.render_page(S, NOW, fonts=False)
    assert LEAK not in page and SECRET not in page
    assert "example.com" not in page


def test_secret_values_from_the_shell_never_reach_the_page(tmp_path) -> None:
    S = rich_sources()
    S["launch"].data["gates"].append({"area": "x", "name": "odd", "status": "FAIL",
                                      "detail": f"token is {CF_TOKEN}"})
    out = dash.write_dashboard(S, tmp_path / "x.html", NOW, env={"CF_ANALYTICS_TOKEN": CF_TOKEN})
    assert CF_TOKEN not in out.read_text(encoding="utf-8")


def test_the_page_loads_nothing_from_anywhere() -> None:
    """No src, no stylesheet link, no url() to the network: the only URLs are
    plain <a href> links to the owner's consoles and run pages."""
    page = dash.render_page(rich_sources(), NOW, fonts=True)
    assert not re.search(r"""\bsrc\s*=\s*["']?https?:""", page, re.I)
    assert not re.search(r"<link\b", page, re.I)
    assert not re.search(r"url\(\s*['\"]?(?:https?:)?//", page, re.I)
    assert not re.search(r"@import", page, re.I)
    assert "fetch(" not in page and "XMLHttpRequest" not in page
    for url in re.findall(r"https?://[^\s\"'<>)]+", page):
        # Every absolute URL sits in an anchor's href.
        assert f'href="{url}' in page or f"href=\"{dash.h(url)}" in page, url
    assert "font/woff2;base64," in page          # Barlow is inlined


# --------------------------------------------------------------------- #
# the command line
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("environ", [{"CI": "true"}, {"GITHUB_ACTIONS": "true"}])
def test_it_refuses_to_run_in_ci(environ, tmp_path, capsys) -> None:
    called = []
    code = dash.cli(["--no-open", "--out", "data/dashboard.html"], environ=environ,
                    env_file=tmp_path / ".env", collectors={"plan": lambda ctx: called.append(1)})
    assert code == 2 and not called
    assert "does not run in CI" in capsys.readouterr().err


def test_it_refuses_a_path_that_is_not_gitignored(tmp_path, capsys) -> None:
    code = dash.cli(["--no-open", "--out", "site/dashboard.html"], environ={},
                    env_file=tmp_path / ".env", collectors={})
    assert code == 2 and "not gitignored" in capsys.readouterr().err
    assert not (dash.REPO_ROOT / "site" / "dashboard.html").exists()


def test_the_default_output_is_gitignored() -> None:
    assert dash.DEFAULT_OUT == dash.REPO_ROOT / "data" / "dashboard.html"
    assert stats._gitignored(dash.DEFAULT_OUT)


def test_cli_writes_the_page_and_opens_it_only_when_asked(tmp_path, monkeypatch) -> None:
    out = dash.REPO_ROOT / "data" / f"dashboard-test-{id(tmp_path)}.html"
    rich = rich_sources()
    collectors = {k: (lambda ctx, s=s: s) for k, s in rich.items()}
    opened = []
    try:
        env_file = tmp_path / ".env"
        env_file.write_text(f"CF_ANALYTICS_TOKEN={CF_TOKEN}\nexport STRIPE_API_KEY='{SECRET}'\n")
        code = dash.cli(["--out", str(out), "--now", NOW.isoformat()], environ={}, env_file=env_file,
                        collectors=collectors, opener=opened.append)
        assert code == 0 and opened == [out]
        page = out.read_text(encoding="utf-8")
        assert 'id="overview"' in page and CF_TOKEN not in page and SECRET not in page
        opened.clear()
        dash.cli(["--out", str(out), "--no-open"], environ={}, env_file=env_file,
                 collectors=collectors, opener=opened.append)
        assert opened == []
    finally:
        out.unlink(missing_ok=True)


def test_env_reads_the_shell_first_then_dotenv(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CF_ACCOUNT_ID=fromfile\nRESEND_READ_KEY=re_fromfile_key\nOTHER=x\n")
    env = dash.env_from({"CF_ACCOUNT_ID": "fromshell"}, env_file)
    assert env["CF_ACCOUNT_ID"] == "fromshell" and env["RESEND_READ_KEY"] == "re_fromfile_key"
    assert "OTHER" not in env


def test_the_module_writes_nothing_to_any_service() -> None:
    """Read-only by construction: the only HTTP methods it names are GET and
    the counter's read-only SQL POST, and the intake sweep never promotes."""
    text = (dash.REPO_ROOT / "run" / "dashboard.py").read_text(encoding="utf-8")
    methods = set(re.findall(r'method="([A-Z]+)"', text))
    assert methods <= {"POST"}                       # the Analytics Engine SQL read
    assert "promote=False" in text and "promote=True" not in text
    assert "send_all" not in text and "_promote" not in text


# --------------------------------------------------------------------- #
# the numbers
# --------------------------------------------------------------------- #

def test_money_nets_refunds_and_the_modelled_fee() -> None:
    from run.economics import stripe_fee
    S = rich_sources()
    m = dash.money_metrics(S["stripe"], "all", NOW)
    assert m["count"] == 18 and m["full_refunds"] == 1
    gross = 16 * 29 + 2 * 69
    fees = 16 * stripe_fee(29, one_time=True) + 2 * stripe_fee(69, one_time=True)
    assert m["gross"] == pytest.approx(gross)
    assert m["net"] == pytest.approx(gross - 29 - fees)
    assert m["types"]["League Pass"] == 2


def test_period_windows_and_deltas() -> None:
    S = rich_sources()
    m7 = dash.money_metrics(S["stripe"], "7d", NOW)
    assert m7["count"] == 9 and m7["count_delta"] is not None
    t7 = dash.traffic_metrics(S["traffic"], "7d", NOW)
    t30 = dash.traffic_metrics(S["traffic"], "30d", NOW)
    assert 0 < t7["views"] < t30["views"] and t7["views_delta"] > 0     # the scenario grows
    assert len(t30["chart"]) == 30 and len(t7["chart"]) == 7


def test_free_report_to_paid_joins_on_digests_within_14_days() -> None:
    S = rich_sources()
    # Without the send log there is no denominator to count from.
    assert dash.free_to_paid(S["forms"], S["stripe"], NOW) is None
    got = dash.free_to_paid(S["forms"], S["stripe"], NOW, S["sends"])
    # The denominator is free reports MAILED (23 send keys), never every
    # request the Worker holds (38 rows: refused, stale and unbuilt ones too).
    assert got is not None and got[1] + got[2] == 23


def test_free_report_to_paid_counts_only_mailed_reports_from_the_day_they_went() -> None:
    from run.trials import OWNER_KEY_PART
    forms = dash._source("forms", data={"rows": [
        {"kind": "trial", "at": (NOW - timedelta(days=40)).isoformat(), "via": None,
         "who": "a", "sent_code": "aaaa"},
        {"kind": "trial", "at": (NOW - timedelta(days=40)).isoformat(), "via": None,
         "who": "b", "sent_code": "bbbb"},           # never mailed: not counted
        {"kind": "trial", "at": (NOW - timedelta(days=40)).isoformat(), "via": None,
         "who": "c", "sent_code": "cccc"}]}, read_at=NOW)
    went = (NOW - timedelta(days=20)).isoformat()
    sends = dash._source("sends", data={"entries": [
        {"key": "trial-2026-aaaa", "sent_at": went},
        # The owner's own test report never counts as a mailing.
        {"key": f"trial-2026-{OWNER_KEY_PART}-cccc-1234567890", "sent_at": went}]},
        read_at=NOW)
    bought = (NOW - timedelta(days=15)).isoformat()   # 25 days after asking, 5 after the mail
    stripe = dash._source("stripe", data={"sessions": [
        {"paid": True, "who": "a", "created": bought}]}, read_at=NOW)
    assert dash.free_to_paid(forms, stripe, NOW, sends) == (1, 1, 0)
    # Without LOG_SECRET no row carries a code, so no rate: the reason instead.
    for row in forms.data["rows"]:
        row["sent_code"] = None
    assert dash.free_to_paid(forms, stripe, NOW, sends) == dash.FREE_TO_PAID_UNMATCHED


def test_log_secret_is_read_from_dot_env_and_a_missing_one_is_said(tmp_path, monkeypatch) -> None:
    """Review, reproduced: the owner keeps LOG_SECRET in the gitignored .env
    (make signups reads it there), but the dashboard read only the shell, so
    free_to_paid() matched nothing and the insight vanished with no reason.
    It reads .env like the other names, keys the free-report codes with it,
    never prints its value, and says why when it's missing."""
    import html as _html
    import run.intake as intake
    from run.digest import address
    monkeypatch.delenv("LOG_SECRET", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_SECRET=from-the-dot-env\nFORM_ENDPOINT=https://w.test\n",
                        encoding="utf-8")
    env = dash.env_from({}, env_file)
    assert env["LOG_SECRET"] == "from-the-dot-env"
    assert "LOG_SECRET" in dash.SECRET_NAMES
    assert dash.scrub("x from-the-dot-env y", env) == "x *** y"
    monkeypatch.setattr(intake, "fetch_seats", lambda endpoint, key=None: [
        {"kind": "trial", "email": "fan@fans.mail", "received_at": NOW.isoformat()}])
    forms = dash.collect_forms(dash.Context(env=env, now=NOW))
    code = forms.data["rows"][0]["sent_code"]
    assert code == address("fan@fans.mail", key="from-the-dot-env")
    # Mutation: keyed from the shell only, there would be no code at all.
    assert dash.collect_forms(dash.Context(env={**env, "LOG_SECRET": ""}, now=NOW)
                              ).data["rows"][0]["sent_code"] is None
    # No key anywhere: the page names the reason where the rate would be.
    S = rich_sources()
    for row in S["forms"].data["rows"]:
        row["sent_code"] = None
    page = _html.unescape(dash.render_page(S, NOW, fonts=False))
    assert dash.FREE_TO_PAID_UNMATCHED in page
    assert "needs LOG_SECRET" in page


def test_plan_gates_are_read_from_plan_md_not_restated() -> None:
    parsed = dash.parse_plan_gates((dash.REPO_ROOT / "PLAN.md").read_text(encoding="utf-8"))
    metrics = [g["metric"] for g in parsed["gates"]]
    assert any("Refund rate" in m for m in metrics) and any("Paid purchases" in m for m in metrics)
    assert dash.plan_threshold(parsed, "Refund rate", "green") == 15
    assert dash.plan_threshold(parsed, "Refund rate", "red") == 25


def test_insights_say_when_there_is_not_enough_data() -> None:
    S = rich_sources()
    thin = [e for e in traffic_events(NOW, days=3)][:40]
    S["traffic"] = dash._source("traffic", data={"rows": {p: aggregate(thin, NOW, 90) for p in ("7d", "30d", "all")},
                                                 "daily": daily(thin)})
    m = dash.metrics_for(S, "30d", NOW)
    texts = [i.text for i in dash.build_insights(S, m, NOW, None, None)]
    assert any(t.startswith("Not enough traffic") for t in texts)


def test_insights_name_the_biggest_drop_with_its_numbers() -> None:
    S = rich_sources()
    m = dash.metrics_for(S, "30d", NOW)
    ins = dash.build_insights(S, m, NOW, None, None)
    drop = [i for i in ins if i.text.startswith("The biggest drop")]
    assert drop and re.search(r"\d+ of \d", drop[0].text) and drop[0].action


def test_a_failed_cron_and_a_missed_slot_become_issues() -> None:
    S = rich_sources()
    S["github"].data["weekly.yml"]["runs"] = [
        r for r in S["github"].data["weekly.yml"]["runs"]
        if dash._gh_when(r["created_at"]) < NOW - timedelta(days=3)]
    health = dash.workflow_health(S["github"], NOW)
    weekly = next(w for w in health if w["file"] == "weekly.yml")
    assert weekly["missing"]
    m = dash.metrics_for(S, "7d", NOW)
    titles = [i.title for i in dash.build_issues(S, NOW, health, dash.ledger_view(S["ledger"], NOW), m)]
    assert any("Wednesday reports didn't run" in t for t in titles)
    assert any("The last tests run failed" in t for t in titles)


def test_an_on_time_tuesday_is_not_a_missed_slot() -> None:
    S = rich_sources()
    weekly = next(w for w in dash.workflow_health(S["github"], NOW) if w["file"] == "weekly.yml")
    assert not weekly["missing"]


def test_refund_rate_over_plans_red_line_is_an_issue() -> None:
    """With D unwritten every purchase this season counts: 6 of 18 refunded
    is over the 25% line. (With D written the rate counts from D; see
    test_a_refund_before_d_never_moves_the_refund_rate.)"""
    S = rich_sources()
    S["plan"] = dash._source("plan", data=dash.parse_plan_gates(plan_text()), read_at=NOW)
    assert not S["plan"].data["d_written"]
    for s in S["stripe"].data["sessions"][:6]:
        s.update(full_refund=True, refunded=s.get("amount") or 0)
    m = dash.metrics_for(S, "7d", NOW)
    titles = [i.title for i in dash.build_issues(S, NOW, [], None, m)]
    assert any("red line" in t for t in titles)


def test_a_dispute_needing_response_is_critical() -> None:
    S = rich_sources()
    S["stripe"].data["sessions"][0]["dispute"] = "needs_response"
    issues = dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
    assert any(i.severity == "critical" and "chargeback" in i.title for i in issues)


def test_counts_never_read_a_traffic_view_as_people() -> None:
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    assert "never people" in page


# --------------------------------------------------------------------- #
# live mode (`make dashboard-live`)
# --------------------------------------------------------------------- #

def test_live_mode_refuses_an_interval_under_the_github_allowance(tmp_path, capsys) -> None:
    """Each build makes one unsigned GitHub request per workflow; GitHub allows
    60 an hour, so a 5-minute loop would start failing its own cron health."""
    code = dash.cli(["--no-open", "--every", "5", "--out", "data/dashboard.html"], environ={},
                    env_file=tmp_path / ".env", collectors={})
    assert code == 2 and "at least 10" in capsys.readouterr().err


def test_live_mode_rebuilds_opens_once_and_survives_a_bad_round(tmp_path) -> None:
    out = dash.REPO_ROOT / "data" / f"dashboard-live-{id(tmp_path)}.html"
    rich = rich_sources()
    calls = {"n": 0}

    def flaky(ctx):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError(f"network blip for {LEAK} with {SECRET}")
        return rich["plan"]

    collectors = {**{k: (lambda ctx, s=s: s) for k, s in rich.items()}, "plan": flaky}
    opened, slept = [], []
    try:
        code = dash.cli(["--out", str(out), "--every", "15", "--rounds", "3", "--now", NOW.isoformat()],
                        environ={"STRIPE_API_KEY": SECRET}, env_file=tmp_path / ".env",
                        collectors=collectors, opener=opened.append, sleep=slept.append)
        assert code == 0
        assert opened == [out]                       # the tab opens once, then reloads itself
        assert slept == [900, 900]                   # no sleep after the last round
        page = out.read_text(encoding="utf-8")
        assert 'data-refresh="900"' in page and f'data-generated="{int(NOW.timestamp() * 1000)}"' in page
        assert "Live · every 15 min" in page and 'class="stale" hidden' in page
        assert not out.with_name(f".{out.name}.tmp").exists()
    finally:
        out.unlink(missing_ok=True)


def test_a_failed_round_never_prints_a_secret(tmp_path, capsys, monkeypatch) -> None:
    """collect_all contains a single collector's failure, so the round-level
    catch is for the rest (rendering, the disk): force the whole build to fail."""
    out = dash.REPO_ROOT / "data" / f"dashboard-live-{id(tmp_path)}.html"

    def failing_build(*a, **k):
        raise RuntimeError(f"Stripe said no to {SECRET} for {LEAK}")

    monkeypatch.setattr(dash, "_build", failing_build)
    code = dash.cli(["--out", str(out), "--every", "10", "--rounds", "1", "--no-open"],
                    environ={"STRIPE_API_KEY": SECRET}, env_file=tmp_path / ".env",
                    collectors={}, sleep=lambda s: None)
    assert not out.exists()
    err = capsys.readouterr().err
    assert code == 0 and "this update failed" in err
    assert SECRET not in err and LEAK not in err


def test_a_one_off_build_carries_no_reload() -> None:
    """`make dashboard` is a snapshot: it must not reload itself into an
    unchanged file every few minutes, or claim to be live."""
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    body_tag = re.search(r"<body[^>]*>", page).group(0)
    assert "data-refresh" not in body_tag and "Live · every" not in page and 'class="stale"' not in page
    live = dash.render_page(rich_sources(), NOW, fonts=False, live_minutes=15)
    assert 'data-refresh="900"' in live


def test_the_reload_never_spins_on_a_stopped_loop() -> None:
    """If the loop has stopped, the file never changes; the page must wait at
    least a minute between reloads rather than reloading in a tight loop."""
    assert "Math.max(gen+(refresh+45)*1000-Date.now(),60000)" in dash.JS
    assert "document.hidden" in dash.JS                      # no reloads in a background tab
    assert 'sessionStorage.setItem("byl-dash-y"' in dash.JS   # the reader keeps their place


# --------------------------------------------------------------------- #
# profit and posts (run/books.py)
# --------------------------------------------------------------------- #

def test_profit_is_net_revenue_less_the_costs_charged_in_the_period() -> None:
    S = rich_sources()
    m = dash.metrics_for(S, "30d", NOW)
    # Oct 5 mailbox + Oct 20 ad fall in the last 30 days; the Aug 1 domain doesn't.
    assert m.profit["costs"] == round(9.99 + 40, 2)
    assert m.profit["profit"] == round(m.money["net"] - 49.99, 2)
    assert m.profit["hours"] == 30.0 and m.profit["per_hour"] == pytest.approx(m.profit["profit"] / 30)
    allm = dash.metrics_for(S, "all", NOW)
    assert allm.profit["costs"] == round(12 + 9.99 * 2 + 40, 2)


def test_break_even_counts_passes_at_their_net_after_stripe() -> None:
    S = rich_sources()
    S["stripe"] = dash._source("stripe", data={"sessions": stripe_sessions()[:1], "link_map": True,
                                               "dispute_errors": 0}, read_at=NOW)
    page = dash.render_page(S, NOW, fonts=False)
    per = dash.net_per_charge()
    assert 13 < per < 14.99
    m = dash.metrics_for(S, "all", NOW)
    gap = 71.98 - m.money["net"]
    need = math.ceil(gap / per)
    assert f"{need} more monthly charge" in page


def test_without_costs_the_profit_card_says_how_to_add_them() -> None:
    S = rich_sources()
    S["books"] = dash.off("books", "No costs, hours or posts recorded yet.")
    page = dash.render_page(S, NOW, fonts=False)
    assert "Record costs: make cost" in page and 'make cost ITEM=&quot;Domain&quot;' in page
    # Post-shaped tags seen on the site still get their rows without a log.
    assert "reddit-oct20" in page and "No posts tracked yet" not in page


def test_with_no_post_tags_at_all_the_posts_card_says_how_to_start() -> None:
    m = dash.Metrics("30d", 30, traffic={"rows": []}, money=None)
    html = dash.posts_card(m, {})
    assert "No posts tracked yet" in html and "make link TAG=" in html


def test_a_post_tag_counts_under_its_channel_and_on_its_own_row() -> None:
    S = rich_sources()
    m = dash.metrics_for(S, "30d", NOW)
    channels = {r["channel"] for r in m.channels}
    assert "reddit" in channels and "reddit-oct20" not in channels
    posts = {r["tag"]: r for r in m.posts}
    assert set(posts) == {"reddit-oct20", "x-thread1"}
    assert posts["reddit-oct20"]["where"] == "r/fantasyfootball" and posts["reddit-oct20"]["day"] == "2026-10-20"
    assert posts["reddit-oct20"]["views"] > 0 and posts["reddit-oct20"]["paid"] >= 0
    page = dash.render_page(S, NOW, fonts=False)
    assert 'class="pmark"' in page and "Posted Oct 20: reddit-oct20" in page


def test_an_unlogged_post_tag_gets_the_first_day_it_was_seen() -> None:
    S = rich_sources()
    S["books"] = dash.off("books", "none")
    m = dash.metrics_for(S, "all", NOW)
    row = {r["tag"]: r for r in m.posts}["x-thread1"]
    first = min(r["day"] for r in S["traffic"].data["daily"] if r["v"] == "x-thread1" and r["e"] == "view")
    assert row["day"] == first and not row["logged"]


def test_a_bad_line_in_the_books_is_a_low_issue() -> None:
    S = rich_sources()
    S["books"].data.problems.append("data/costs.csv line 4 was skipped: could not convert string to float.")
    m = dash.metrics_for(S, "7d", NOW)
    issues = dash.build_issues(S, NOW, [], None, m)
    hit = [i for i in issues if "line 4" in i.title]
    assert hit and hit[0].severity == "low"


def test_the_books_reader_is_listed_with_the_sources() -> None:
    assert "books" in dash.COLLECTORS and "books" in dash.FRESHNESS_KEYS


# --------------------------------------------------------------------- #
# the launch-readiness review (Nov 2026)
# --------------------------------------------------------------------- #

# 346171e, the commit that moved the weekly report from Tuesday to Wednesday.
SCHEDULE_MOVED = datetime(2026, 10, 31, 19, 13, 39, tzinfo=timezone.utc)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _weekly_runs(*starts: datetime) -> Source:
    runs = [{"created_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "completed",
             "conclusion": "success", "event": "schedule",
             "url": f"https://github.com/{dash.GITHUB_REPO}/actions/runs/{k}"}
            for k, at in enumerate(starts)]
    return dash._source("github", data={"weekly.yml": {"label": "Wednesday reports", "runs": runs}},
                        read_at=NOW)


def test_a_slot_from_before_the_schedule_existed_is_not_missed(monkeypatch) -> None:
    """DASH-02. On Nov 3 the top "Needs you now" item read "Wednesday reports
    didn't run after its Wed 8:17 PM ET slot": Oct 28 22:17 UTC, a slot of
    the Wednesday schedule committed Oct 31. Under the schedule in force
    then, the week's runs were Tuesday Oct 27 at 18:03 and 20:44, green."""
    now = _utc(2026, 11, 3, 16, 0)
    src = _weekly_runs(_utc(2026, 10, 27, 20, 44), _utc(2026, 10, 27, 18, 3))
    monkeypatch.setattr(dash, "schedule_changed", lambda root, name: SCHEDULE_MOVED)
    weekly = dash.workflow_health(src, now)[0]
    # The slot is the main 22:17 one; the 00:17 retry only backs it up.
    assert weekly["slot"] == _utc(2026, 10, 28, 22, 17)
    assert not weekly["missing"]
    titles = [i.title for i in dash.build_issues(rich_sources(), now, [weekly], None,
                                                 dash.metrics_for(rich_sources(), "7d", now))]
    assert not any("didn't run" in t for t in titles)
    # When git can't say when the schedule changed, a missed slot still shows.
    monkeypatch.setattr(dash, "schedule_changed", lambda root, name: None)
    assert dash.workflow_health(src, now)[0]["missing"]


def test_the_thursday_retry_is_never_a_slot_of_its_own(monkeypatch) -> None:
    """DASH-02, going forward. The 00:17 UTC retry falls on Thursday, so it
    was read as Thursday's own slot: with Wednesday's 13:17 and 22:17 runs
    green and no retry run (none is needed), the cron read as missed from
    Thursday 02:17 UTC until the next week."""
    monkeypatch.setattr(dash, "schedule_changed", lambda root, name: SCHEDULE_MOVED)
    now = _utc(2026, 11, 5, 3, 0)
    both = _weekly_runs(_utc(2026, 11, 4, 22, 19), _utc(2026, 11, 4, 13, 18))
    weekly = dash.workflow_health(both, now)[0]
    assert weekly["slot"] == _utc(2026, 11, 4, 22, 17) and not weekly["missing"]
    # The morning run never answers for the evening one.
    morning = _weekly_runs(_utc(2026, 11, 4, 13, 18))
    assert dash.workflow_health(morning, now)[0]["missing"]


def test_schedule_changed_reads_the_commit_that_moved_a_cron_line(tmp_path) -> None:
    """A comment that mentions a cron is not a schedule change."""
    import subprocess
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)

    def commit(text: str, when: str) -> None:
        (wf / "weekly.yml").write_text(text, encoding="utf-8")
        env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "HOME": str(tmp_path),
               "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
        for cmd in (["git", "add", "-A"],
                    ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit",
                     "-q", "-m", "x"]):
            subprocess.run(cmd, cwd=tmp_path, check=True, env=env, capture_output=True)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    commit('on:\n  schedule:\n    - cron: "17 22 * * 3"\n', "2026-10-31T19:13:39+00:00")
    commit('# the cron: moved to Wednesday\non:\n  schedule:\n    - cron: "17 22 * * 3"\n',
           "2026-11-02T10:00:00+00:00")
    assert dash.schedule_changed(tmp_path, "weekly.yml") == SCHEDULE_MOVED
    assert dash.schedule_changed(tmp_path, "nothing.yml") is None


def _site(built_at: str, **switches: bool) -> Source:
    base = {"checkout_open": True, "can_complete": False, "trial_open": False,
            "monthly_link": True, "pass_link": False, "seats_open": False}
    return dash._source("site", data={"week": {"season": "2026", "week": 9, "phase": "season",
                                               "built_at": built_at},
                                      "players_at": built_at, "switches": {**base, **switches}},
                        read_at=NOW)


def test_the_sample_is_not_stale_before_wednesday_evenings_run(monkeypatch) -> None:
    """M-01. The sample and the player directory were built Tue Oct 27 18:04.
    The move to Wednesday made that week's gap 8 days 4 hours, so a fixed
    eight days said "stale" from 2 PM ET on Nov 4, and its advice (run
    weekly-report) would have sent Week 9's reports hours before 5:17 PM."""
    monkeypatch.setattr(dash, "schedule_changed", lambda root, name: SCHEDULE_MOVED)
    built = "2026-10-27T18:04:03+00:00"
    for now in (_utc(2026, 11, 4, 19, 0), _utc(2026, 11, 4, 23, 30)):
        assert not dash.site_is_stale(built, now)
        S = rich_sources(now)
        S["site"] = _site(built)
        titles = [i.title for i in dash.build_issues(S, now, [], None, dash.metrics_for(S, "7d", now))]
        assert not any("sample page" in t or "player directory" in t for t in titles), now
    # Two hours after the evening slot with no rebuild, it is stale, and the
    # advice never starts with running the workflow.
    late = _utc(2026, 11, 5, 0, 30)
    assert dash.site_is_stale(built, late)
    S = rich_sources(late)
    S["site"] = _site(built)
    hit = [i for i in dash.build_issues(S, late, [], None, dash.metrics_for(S, "7d", late))
           if "sample page" in i.title]
    assert hit and "Wednesday evening's run should have rebuilt it" in hit[0].title
    assert "build this page again" in hit[0].fix[0] and "only before the week's first kickoff" in hit[0].fix[1]
    # The evening run's own build is fresh, and in a week with a Wednesday
    # game the morning run's build answers for that day.
    assert not dash.site_is_stale("2026-11-04T22:21:00+00:00", late)
    assert not dash.site_is_stale("2026-11-25T13:30:00+00:00", _utc(2026, 11, 26, 1, 0))


def test_without_the_link_map_a_served_sale_is_never_a_critical_alarm(monkeypatch, tmp_path) -> None:
    """DASH-01. With the owner's Stripe key and no STRIPE_PAYMENT_LINKS on the
    Mac, the read-only sweep called a $14.99 Monthly sale PAID-UNATTRIBUTED,
    and the page raised a critical whose last step was "refund in full", for
    a buyer the hourly run (which has the map) served. The sweep's other
    findings still show."""
    import run.intake as intake
    ref = _a_roster_ref()
    sold = _raw_session(1, "buyer@example.net") | {"client_reference_id": ref,
                                                   "payment_link": "plink_M"}
    no_email = _raw_session(2, "") | {"client_reference_id": ref, "payment_link": "plink_M",
                                      "customer_details": {}, "customer_email": None}
    monkeypatch.setattr(intake, "sweep_sessions", lambda key, since, plans: ([sold, no_email], None))
    ctx = Context(env={"STRIPE_STATS_KEY": SECRET}, now=NOW, root=tmp_path)
    src = dash.collect_intake(ctx)
    assert src.ok and src.data["link_map"] is False and "STRIPE_PAYMENT_LINKS" in src.note
    assert not any("STRIPE_PAYMENT_LINKS is not set" in p for p in src.data["problems"])
    assert any("no email" in p for p in src.data["problems"])
    S = rich_sources()
    S["intake"] = src
    issues = dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
    critical = [i.title for i in issues if i.severity == "critical"]
    assert not any("cs_live_1" in t for t in critical)        # the served sale
    assert any("cs_live_2" in t for t in critical)            # nobody to send to: real
    # With the map, the same sale is served and nothing about it is reported.
    with_map = dash.collect_intake(Context(env={"STRIPE_STATS_KEY": SECRET,
                                                "STRIPE_PAYMENT_LINKS": "m:plink_M,p:plink_P"},
                                           now=NOW, root=tmp_path))
    assert with_map.data["link_map"] and with_map.note == ""
    assert with_map.data["signups"] == 1


def test_a_key_without_the_sweeps_permission_is_a_note_not_an_error(monkeypatch, tmp_path) -> None:
    """The owner-stats key may lack a permission the sweep needs: that is a
    check this key can't make, said once, never a red source every build."""
    import run.intake as intake
    from run.subscriptions import SubscriptionError

    def refuse(key, since, plans):
        raise SubscriptionError("403", status=403, permissions=("rak_customer_read",))
    monkeypatch.setattr(intake, "sweep_sessions", refuse)
    src = dash.collect_intake(Context(env={"STRIPE_STATS_KEY": SECRET}, now=NOW, root=tmp_path))
    assert src.status == "off" and "rak_customer_read" in src.note


def test_a_sale_without_the_link_map_is_named_by_its_price() -> None:
    """DASH-01's other half: "other price ($14.99)" for a Monthly sale."""
    assert stats._pass_type({"amount_subtotal": 1499}, {}) == "Monthly"
    assert stats._pass_type({"amount_subtotal": 3499}, {}) == "League Pass"


def test_the_two_views_read_the_same_names_from_dotenv(tmp_path) -> None:
    """DASH-03 and M-02: make stats and the dashboard read the form Worker,
    the link map and the payout currency from one list each, from the shell
    first and then .env."""
    for name in (*stats.CF_NAMES, *stats.FORM_NAMES, "STRIPE_PAYOUT_CURRENCY"):
        assert name in dash.ENV_NAMES
    assert "STRIPE_PAYOUT_CURRENCY" not in dash.SECRET_NAMES
    env_file = tmp_path / ".env"
    env_file.write_text("FORM_ENDPOINT=https://forms.example/rows\nSTRIPE_PAYMENT_LINKS=m:plink_M\n"
                        "STRIPE_PAYOUT_CURRENCY=usd\n")
    env = dash.env_from({"FORM_ENDPOINT": "https://shell.example/rows"}, env_file)
    assert env["FORM_ENDPOINT"] == "https://shell.example/rows"
    assert env["STRIPE_PAYMENT_LINKS"] == "m:plink_M" and env["STRIPE_PAYOUT_CURRENCY"] == "usd"


def test_the_launch_gates_see_what_the_dashboard_read_from_dotenv(monkeypatch) -> None:
    """DASH-04 and M-02. The gates read os.environ, so with the link map and
    the payout currency in .env the page still said "isn't in this shell"
    and "paid out in CAD". For the gates' run they see .env too; a value in
    the shell wins, and nothing outlives the run."""
    import run.launch_check as lc
    assert "check_worker_switches" in dash.FAST_GATES
    monkeypatch.delenv("STRIPE_PAYOUT_CURRENCY", raising=False)
    monkeypatch.setenv("FORM_ENDPOINT", "https://shell.example/rows")
    seen = {}

    def probe():
        seen.update({n: os.environ.get(n) for n in dash.GATE_ENV})
        return [lc.Gate("Owner", "probe", "PASS", "")]
    monkeypatch.setattr(lc, "check_probe", probe, raising=False)
    monkeypatch.setattr(dash, "FAST_GATES", ("check_probe", "check_economics"))
    env = {"STRIPE_PAYMENT_LINKS": "m:plink_M", "STRIPE_PAYOUT_CURRENCY": "usd",
           "FORM_ENDPOINT": "https://dotenv.example/rows"}
    src = dash.collect_launch(Context(env=env, now=NOW))
    assert seen["STRIPE_PAYMENT_LINKS"] == "m:plink_M"
    assert seen["FORM_ENDPOINT"] == "https://shell.example/rows"
    payout = next(g for g in src.data["gates"] if g["name"].startswith("Payouts in USD"))
    assert payout["status"] == "PASS"
    assert "STRIPE_PAYMENT_LINKS" not in os.environ and "STRIPE_PAYOUT_CURRENCY" not in os.environ
    assert os.environ["FORM_ENDPOINT"] == "https://shell.example/rows"


def test_launch_switches_are_read_off_the_pages(tmp_path) -> None:
    (tmp_path / "site" / "join").mkdir(parents=True)
    (tmp_path / "site" / "index.html").write_text(
        "const CHECKOUT_OPEN = true;\nconst CHECKOUT_CAN_COMPLETE = false;\nconst TRIAL_OPEN = false;\n")
    (tmp_path / "site" / "join" / "index.html").write_text(
        'const STRIPE_LINK_MONTHLY = "https://buy.stripe.com/x";\nconst STRIPE_LINK_PASS = "";\n')
    (tmp_path / "site" / "league-pass.html").write_text("const SEATS_OPEN = false;\n")
    assert dash.launch_switches(tmp_path) == {
        "checkout_open": True, "can_complete": False, "trial_open": False,
        "monthly_link": True, "pass_link": False, "seats_open": False}


def test_the_page_says_where_launch_stands_and_the_step_next() -> None:
    """DASH-04. Nothing on the page said "Monthly link live, checkout can't
    complete yet, League Pass held, next: your own purchase"."""
    S = rich_sources()
    S["stripe"] = dash._source("stripe", data={"sessions": [], "link_map": True,
                                               "dispute_errors": 0}, read_at=NOW)
    S["site"] = _site((NOW - timedelta(hours=2)).isoformat())
    card = dash.launch_status(S, NOW)
    assert "Where launch stands" in card and "Monthly link live" in card
    assert "Held" in card and "None yet" in card
    assert "Your own purchase of the Monthly plan" in card and "step 4" in card
    # After the owner's purchase: the emails, then the two switches together.
    S["stripe"] = dash._source("stripe", data={"sessions": stripe_sessions()[:1], "link_map": True,
                                               "dispute_errors": 0}, read_at=NOW)
    card = dash.launch_status(S, NOW)
    assert "1 paid purchase so far" in card and "step 6" in card and "TRIAL_OPEN" in card
    # Once checkout completes and the free report is on, the card goes.
    S["site"] = _site((NOW - timedelta(hours=2)).isoformat(), can_complete=True, trial_open=True)
    assert dash.launch_status(S, NOW) == ""
    assert "Where launch stands" not in dash.render_page(S, NOW, fonts=False)


def _with_d(S: dict, d: str | None) -> None:
    S["plan"] = dash._source("plan", data=dash.parse_plan_gates(plan_text(d=d)), read_at=NOW)


def test_a_refund_before_d_never_moves_the_refund_rate() -> None:
    """DASH-05. The owner buys first and may refund. With D written, the
    refund-rate gate still counted every purchase ever: an owner refund on
    Nov 3 plus one buyer after D read "Refund rate 50% Behind" forever."""
    sessions = stripe_sessions()[:6]
    owner, buyers = sessions[0], sessions[1:]
    owner.update(created=int(_utc(2026, 10, 20, 15, 0).timestamp()), full_refund=True,
                 refunded=owner["amount"])
    for k, s in enumerate(buyers):
        s.update(created=int(_utc(2026, 10, 26, 12 + k, 0).timestamp()), full_refund=False,
                 refunded=0.0, dispute=None)
    S = rich_sources()
    S["stripe"] = dash._source("stripe", data={"sessions": sessions, "link_map": True,
                                               "dispute_errors": 0}, read_at=NOW)
    _with_d(S, "2026-10-26")
    gates = dash.gates_html(S, NOW, None, None, S["registry"])
    row = next(r for r in gates.split("<tr>") if "Refund rate" in r)
    assert ">0%<" in row
    assert "1 purchase before D is left out" in gates
    # Every purchase counts until D is written, the owner's too.
    _with_d(S, None)
    row = next(r for r in dash.gates_html(S, NOW, None, None, S["registry"]).split("<tr>")
               if "Refund rate" in r)
    assert ">17%<" in row


def test_checkout_completing_with_d_unwritten_is_a_low_reminder() -> None:
    S = rich_sources()
    _with_d(S, None)
    S["site"] = _site((NOW - timedelta(hours=2)).isoformat(), can_complete=True)
    issues = dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
    hit = [i for i in issues if "D isn't written" in i.title]
    assert hit and hit[0].severity == "low" and "section 10" in hit[0].fix[0]
    S["site"] = _site((NOW - timedelta(hours=2)).isoformat(), can_complete=False)
    issues = dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
    assert not any("D isn't written" in i.title for i in issues)


def test_the_waitlist_insight_never_points_at_a_send_that_will_refuse(monkeypatch) -> None:
    """DASH-06. "make waitlist-send MAX=<n> sends the one launch email" while
    SENDER_POSTAL_ADDRESS is unset, so the command refuses. Also "1 people"."""
    S = rich_sources()
    S["forms"].data["rows"] = [{"kind": "waitlist", "at": (NOW - timedelta(days=1)).isoformat(),
                                "via": None, "who": "p1"}]
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS", raising=False)
    ins = [i for i in dash.build_insights(S, dash.metrics_for(S, "7d", NOW), NOW, None, None)
           if "on the list" in i.text]
    assert ins and "1 waitlist sign-up in" in ins[0].text and "1 person on the list" in ins[0].text
    assert "waits for a postal address" in ins[0].action and "step 2.6" in ins[0].action
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 1, Somewhere")
    ins = [i for i in dash.build_insights(S, dash.metrics_for(S, "7d", NOW), NOW, None, None)
           if "on the list" in i.text]
    assert "make waitlist-send MAX=<n>" in ins[0].action


def test_trade_check_requests_are_counted() -> None:
    """DASH-07. The Worker takes trade_check rows; neither view showed them."""
    S = rich_sources()
    S["forms"].data["rows"] += [{"kind": "trade_check", "at": (NOW - timedelta(hours=k)).isoformat(),
                                 "via": None, "who": "s1"} for k in (1, 30)]
    S["forms"].data["summary"]["trade_check"] = {"total": 2, "week": 2, "day": 1, "people": 1}
    assert dash.forms_metrics(S["forms"], "7d", NOW)["trade_check"]["total"] == 2
    assert "Trade Check requests" in dash.render_page(S, NOW, fonts=False)


def test_an_optional_or_unverifiable_launch_step_never_reads_as_undone(monkeypatch) -> None:
    """DASH-08. "3 launch steps are waiting on you. Next: GitHub Actions
    secrets are set." counted the bounce key the owner declined (LAUNCH
    calls it optional) and stated as fact a check this Mac can't make."""
    import run.launch_check as lc
    monkeypatch.setattr(lc.shutil, "which", lambda name: None)
    monkeypatch.delenv("RESEND_READ_KEY", raising=False)
    gates = [g.__dict__.copy() for g in lc.check_secrets() + lc.check_resend_read_key()]
    assert gates[-1]["name"].rstrip(".") in dash.OPTIONAL_OWNER_GATES
    S = rich_sources()
    S["launch"] = dash._source("launch", data={"gates": gates}, read_at=NOW)
    issues = dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
    steps = [i for i in issues if "waiting on you" in i.title]
    assert steps and steps[0].title == "1 of the quick launch checks is waiting on you."
    assert steps[0].fix[0] == "Check by hand: GitHub Actions secrets are set."
    optional = [i for i in issues if i.title.startswith("Optional:")]
    assert optional and optional[0].severity == "low"


def test_a_secret_missing_from_this_shell_is_a_check_not_an_undone_step(monkeypatch) -> None:
    """DASH-08's other half. With gh signed in and the link map neither in
    the shell nor in .env, the first step read "Not done yet: The
    payment-link map names each pass under its own prefix." The map is a
    GitHub secret the owner set in step 3; this Mac can't see it, which says
    nothing about whether it is right. A gate that found a real gap still
    reads "Not done yet"."""
    import run.launch_check as lc
    monkeypatch.delenv("STRIPE_PAYMENT_LINKS", raising=False)
    gates = [g.__dict__.copy() for g in lc.check_link_map() if g.status == "OWNER"]
    assert gates and "in this shell" in gates[0]["detail"]
    S = rich_sources()
    S["launch"] = dash._source("launch", data={"gates": gates}, read_at=NOW)
    steps = [i for i in dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
             if "waiting on you" in i.title]
    assert steps[0].fix[0] == ("Check by hand: The payment-link map names each pass under "
                               "its own prefix.")
    missing = {"area": "Owner", "name": "GitHub Actions secrets are set", "status": "OWNER",
               "detail": "missing: LOG_SECRET — the send log can't be keyed"}
    S["launch"] = dash._source("launch", data={"gates": [missing]}, read_at=NOW)
    steps = [i for i in dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
             if "waiting on you" in i.title]
    assert steps[0].fix[0] == "Not done yet: GitHub Actions secrets are set."


def test_a_worker_it_cant_reach_is_never_called_a_mismatch(monkeypatch) -> None:
    """The launch card said "The Worker's own switch doesn't match" whenever
    the Worker gate warned, and the gate also warns when it can't reach the
    Worker at all: a timeout on Nov 3 would have told the owner the Worker's
    TRIAL_OPEN was wrong. The card names the gate by its own name, so the
    two must not drift apart either."""
    import run.launch_check as lc
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    assert lc.check_worker_switches()[0].name == dash.WORKER_GATE
    S = rich_sources()
    S["stripe"] = dash._source("stripe", data={"sessions": [], "link_map": True,
                                               "dispute_errors": 0}, read_at=NOW)
    S["site"] = _site((NOW - timedelta(hours=2)).isoformat())

    def card(status: str, detail: str) -> str:
        S["launch"] = dash._source("launch", data={"gates": [
            {"area": "Owner", "name": dash.WORKER_GATE, "status": status, "detail": detail}]},
            read_at=NOW)
        return dash.launch_status(S, NOW)
    unread = card("WARN", "could not read the Worker's switches: timed out")
    assert "couldn&#x27;t be read" in unread and "match" not in unread
    stray = card("WARN", "the Worker takes free-report rows while the site's TRIAL_OPEN is off")
    assert "doesn&#x27;t match" in stray
    assert "match" not in card("PASS", "both off") and "be read" not in card("PASS", "both off")


def test_the_page_names_plans_not_passes() -> None:
    """DASH-09: the site sells monthly plans, and the $19 Playoff Pass was
    retired Oct 31."""
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    assert "Plans sold" in page and "Plans by type" in page
    for old in ("Passes sold", "Passes per day", "Passes by type", "No passes sold",
                "Every pass from here"):
        assert old not in page, old
    assert all("PLAYOFF" not in shows for _l, _s, shows in dash.SOURCE_INFO.values())


def test_an_empty_sparkline_is_a_flat_line_not_a_setup_box() -> None:
    """DASH-10. `<svg class="spark empty">` took the setup card's dashed
    `.empty` box under every KPI at zero."""
    svg = dash.spark([0, 0, 0])
    assert 'class="spark flat"' in svg and "empty" not in svg
    assert ".spark.flat line{" in dash.CSS and ".spark.empty" not in dash.CSS


def test_small_samples_read_as_flat_or_too_few_not_as_alarms() -> None:
    """DASH-11. 0 then 0 read "no prior period", and one landing view drew
    "100% drop off" in red beside an insight saying it was too few."""
    assert dash.delta(0, 0) == 0.0 and "flat" in dash.delta_chip(dash.delta(0, 0))
    assert dash.delta(3, 0) == math.inf and dash.delta(None, 0) is None
    thin = dash.funnel_html([("Landing views", 1), ("Buy-page views", 0), ("Paid", 0)],
                            min_views=dash.MIN_FUNNEL_VIEWS)
    assert "drop off" not in thin and "too few views to read yet" in thin
    full = dash.funnel_html([("Landing views", 150), ("Buy-page views", 30)],
                            min_views=dash.MIN_FUNNEL_VIEWS)
    assert "80% drop off" in full


def test_on_a_phone_the_issues_tab_comes_second() -> None:
    """DASH-12. At 390px the Issues tab and its red count sat past the right
    edge of the scrolling tab bar. Desktop keeps the page's order."""
    phone = dash.CSS.split("@media (max-width:700px){", 1)[1].split("@media", 1)[0]
    assert '.tabs a[data-nav="overview"]{order:-2}' in phone
    assert '.tabs a[data-nav="issues"]{order:-1}' in phone
    assert [k for k, _v in dash.NAV][:2] == ["overview", "traffic"]


def test_the_forms_card_points_at_make_signups_and_shows_no_address() -> None:
    """The owner asked where the waitlist's addresses are. The page stays
    counts-only and says where to look instead: make signups, in the terminal."""
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    card = page.split("<h3>Form Worker rows</h3>", 1)[1].split('<div class="card">', 1)[0]
    assert "make signups" in card and "never shows them" in card
    assert "@" not in card


# ===================================================================== #
# dash-fresh: the page's age (A1), the background updater (A2) and the
# crons' files read from GitHub's copy (A3)
# ===================================================================== #

import json as _json
import plistlib
import shutil
import subprocess

import run.dashboard_auto as auto

# The real ones, before the fixture below swaps them out for every test.
_REAL_GIT_RUN = dash._git_run
_REAL_ROTATE = auto.rotate_log


def _no_git(args, cwd):
    """No test reaches GitHub: every git command 'fails', so a build reads
    this checkout's files (the fallback)."""
    return 1, b""


@pytest.fixture(autouse=True)
def _fresh_isolation(monkeypatch, tmp_path):
    monkeypatch.setattr(dash, "_git_run", _no_git)
    monkeypatch.setattr(auto, "LAUNCH_AGENTS", tmp_path / "no-launch-agents")
    monkeypatch.setattr(auto, "rotate_log", lambda *a, **k: None)
    # No test asks this Mac's launchd anything: a test that needs an answer
    # passes its own stand-in.
    monkeypatch.setattr(auto, "_launchctl", lambda args: (1, "launchctl is not run in tests"))


# --- A1: every page says how old it is -------------------------------- #

def test_a_one_off_page_carries_its_build_time_and_age_but_never_reloads() -> None:
    """The Nov 3 4:23 AM page looked current a day later: a one-off build had
    no age and no warning. Now every page counts its own age and says when it
    is old; only a live page reloads itself."""
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    body_tag = re.search(r"<body[^>]*>", page).group(0)
    assert f'data-generated="{int(NOW.timestamp() * 1000)}"' in body_tag
    assert "data-refresh" not in body_tag and "data-updater" not in body_tag
    assert '<span class="age" data-age>built just now</span>' in page
    assert dash.AGED_STRIP in page and 'class="aged" data-aged hidden' in page
    assert ("Built <span data-age-words>an hour</span> ago, so these numbers are old. Run "
            "<code>make dashboard</code>, or <code>make dashboard-auto</code> to keep it fresh."
            ) in page
    assert "by make dashboard, once. It doesn&#x27;t update itself." in page
    assert "<script>" + dash.FRESH_JS + "</script>" in page
    assert dash.OLD_AFTER_MINUTES == 60 and "OLD=60*60000" in dash.FRESH_JS


@pytest.mark.parametrize("updater,name,stale_cmd", [
    ("terminal", "Terminal loop", "make dashboard-live"),
    ("agent", "Background updater", "make dashboard-auto-status")])
def test_a_live_page_names_what_rebuilds_it(updater, name, stale_cmd) -> None:
    page = dash.render_page(rich_sources(), NOW, fonts=False, live_minutes=15, updater=updater)
    body_tag = re.search(r"<body[^>]*>", page).group(0)
    assert 'data-refresh="900"' in body_tag and f'data-updater="{updater}"' in body_tag
    assert f"Live · every 15 min<em> · {name}</em>" in page
    stale = page.split('<div class="stale" hidden>', 1)[1].split("</div>", 1)[0]
    assert stale_cmd in stale and "stopped updating" in stale
    # Both strips exist; the script shows the amber one only while the
    # stopped-updating one is hidden, so a live page never shows both.
    assert dash.AGED_STRIP in page and "!(stale&&!stale.hidden)" in dash.FRESH_JS


def test_an_unknown_updater_is_named_as_the_terminal_loop() -> None:
    page = dash.render_page(rich_sources(), NOW, fonts=False, live_minutes=15, updater="<x>")
    assert 'data-updater="terminal"' in page and "<x>" not in page


def _run_fresh_js(age_ms: int, stale_visible: bool = False, refresh: int = 0) -> dict:
    """FRESH_JS in node against a tiny stand-in for the page (``refresh``:
    a live page's data-refresh, in seconds)."""
    script = """
var els={age:{textContent:""},aged:{hidden:true},words:{textContent:""},stale:STALE};
var GEN=1700000000000;Date.now=function(){return GEN+AGE};
global.setInterval=function(){};
global.document={body:{getAttribute:function(n){return n==="data-generated"?String(GEN):
 n==="data-refresh"&&REFRESH?String(REFRESH):null}},
 querySelector:function(s){return {"[data-age]":els.age,"[data-aged]":els.aged,
  "[data-age-words]":els.words,".stale":els.stale}[s]||null}};
""".replace("REFRESH", str(refresh)).replace("AGE", str(age_ms)).replace(
        "STALE", "{hidden:false}" if stale_visible else "{hidden:true}") + dash.FRESH_JS + """
console.log(JSON.stringify({age:els.age.textContent,aged:els.aged.hidden,words:els.words.textContent}));
"""
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return _json.loads(done.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_counts_its_own_age_and_turns_amber_after_an_hour() -> None:
    fresh = _run_fresh_js(20 * 1000)
    assert fresh == {"age": "built just now", "aged": True, "words": ""}
    assert _run_fresh_js(45 * 60_000)["age"] == "built 45 min ago"
    assert _run_fresh_js(45 * 60_000)["aged"] is True
    old = _run_fresh_js(31 * 3_600_000)
    assert old == {"age": "built 31 h ago", "aged": False, "words": "31 hours"}
    assert _run_fresh_js(61 * 60_000)["words"] == "1 hour"
    assert _run_fresh_js(3 * 86_400_000)["age"] == "built 3 days ago"
    # A live page whose loop stopped shows its own strip, not both.
    assert _run_fresh_js(31 * 3_600_000, stale_visible=True)["aged"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_header_and_the_amber_line_state_one_age() -> None:
    """Review #2. The header rounded and the amber line floored: at 95
    minutes the page read "built 2 h ago" above "Built 1 hour ago". One rule
    now, whole units rounded down, and Python's ago() follows it too."""
    for minutes, hours in ((95, 1), (119, 1), (150, 2), (2856, 47)):
        js = _run_fresh_js(minutes * 60_000)
        assert js["age"] == f"built {hours} h ago", minutes
        assert js["words"] == ("1 hour" if hours == 1 else f"{hours} hours"), minutes
    for minutes, days in ((2880, 2), (4300, 2)):
        js = _run_fresh_js(minutes * 60_000)
        assert js["age"] == f"built {days} days ago" and js["words"] == f"{days} days", minutes
    for minutes in (1, 2, 45, 59, 61, 95, 150, 2856, 2880, 4300):
        python = dash.ago(NOW - timedelta(minutes=minutes, seconds=30), NOW)
        assert "built " + python == _run_fresh_js((minutes * 60 + 30) * 1000)["age"], minutes


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_working_live_loop_of_an_hour_or_more_never_says_its_numbers_are_old() -> None:
    """Review #3. The amber line came at a fixed hour, but the stopped strip
    only after two rounds: make dashboard-live EVERY=120 said "these numbers
    are old" for an hour of every cycle of a loop that was working."""
    assert _run_fresh_js(int(60.5 * 60_000), refresh=3600)["aged"] is True
    assert _run_fresh_js(61 * 60_000, refresh=7200)["aged"] is True
    assert _run_fresh_js(119 * 60_000, refresh=7200)["aged"] is True
    # Past two rounds and two minutes the loop has stopped: amber may show
    # until the stopped strip does, and never beside it.
    assert _run_fresh_js(243 * 60_000, refresh=7200)["aged"] is False
    assert _run_fresh_js(243 * 60_000, refresh=7200, stale_visible=True)["aged"] is True
    # The 15-minute updater: amber waits for the stopped strip's 32 minutes,
    # then the hour, as before; a one-off page still turns amber at an hour.
    assert _run_fresh_js(61 * 60_000, refresh=900)["aged"] is False
    assert _run_fresh_js(61 * 60_000)["aged"] is False
    assert _run_fresh_js(59 * 60_000)["aged"] is True


def test_the_page_is_written_under_a_per_process_temp_name(tmp_path, monkeypatch) -> None:
    """The background updater and a build by hand can overlap: a shared temp
    name let one swap the other's half-written page in."""
    out = dash.REPO_ROOT / "data" / f"dashboard-tmpname-{id(tmp_path)}.html"
    swapped = []
    real = os.replace
    monkeypatch.setattr(dash.os, "replace", lambda a, b: (swapped.append(Path(a).name), real(a, b)))
    try:
        dash.write_dashboard(rich_sources(), out, NOW, env={})
        assert swapped == [f".{out.name}.{os.getpid()}.tmp"]
        assert out.is_file() and not list(out.parent.glob(f".{out.name}.*.tmp"))
    finally:
        out.unlink(missing_ok=True)


# --- A2: the background updater --------------------------------------- #

def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "Code" / "beat-your-league"
    (repo / "data").mkdir(parents=True)
    (repo / ".env").write_text(f"STRIPE_STATS_KEY={SECRET}\nCF_ANALYTICS_TOKEN={CF_TOKEN}\n"
                               f"OWNER_EMAILS={LEAK}\n")
    return repo


def test_the_plist_round_trips_and_holds_no_secret(tmp_path) -> None:
    repo = _fake_repo(tmp_path)
    python = repo / ".venv" / "bin" / "python"
    raw = auto.plist_bytes(repo, python)
    doc = plistlib.loads(raw)
    log = str(repo / "data" / "dashboard-updater.log")
    assert doc == {
        "Label": "com.beatyourleague.dashboard",
        "ProgramArguments": [str(python), "-m", "run.dashboard", "--auto", "--every", "15"],
        "WorkingDirectory": str(repo), "StartInterval": 900, "RunAtLoad": True,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        "StandardOutPath": log, "StandardErrorPath": log}
    text = raw.decode("utf-8")
    for name in (*dash.ENV_NAMES, *dash.SECRET_NAMES, "CACHE_KEY", "UPDATE_SECRET"):
        assert name not in text
    for value in (SECRET, CF_TOKEN, LEAK, "STRIPE_STATS_KEY"):
        assert value not in text
    assert ".env" not in text


def test_the_updaters_log_and_page_are_gitignored() -> None:
    assert stats._gitignored(dash.REPO_ROOT / auto.LOG_REL)
    assert stats._gitignored(dash.REPO_ROOT / (auto.LOG_REL + ".1"))
    assert stats._gitignored(dash.REPO_ROOT / auto.PAGE_REL)


def test_no_committed_file_carries_a_path_from_this_mac() -> None:
    for rel in ("run/dashboard_auto.py", "run/dashboard.py", "Makefile"):
        text = (dash.REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "/Users/" not in text and "/home/" not in text, rel


class _Launchctl:
    def __init__(self, codes=None, print_out=""):
        self.calls, self.codes, self.print_out = [], list(codes or []), print_out

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "print":
            return (0 if self.print_out else 113), self.print_out
        if args[0] == "bootstrap" and self.codes:
            return self.codes.pop(0), "Bootstrap failed: 5: Input/output error"
        return (0 if args[0] != "bootout" else 3), ""


def test_install_writes_the_agent_into_the_folder_it_is_given(tmp_path, capsys) -> None:
    repo, agents = _fake_repo(tmp_path), tmp_path / "LaunchAgents"
    run = _Launchctl()
    assert auto.install(repo, agents, run, uid=501, python=Path("/venv/python")) == 0
    target = agents / "com.beatyourleague.dashboard.plist"
    assert plistlib.loads(target.read_bytes())["WorkingDirectory"] == str(repo)
    assert run.calls == [["bootout", "gui/501/com.beatyourleague.dashboard"],
                         ["bootstrap", "gui/501", str(target)]]
    assert not list(agents.glob(".*.tmp"))
    assert auto.installed(agents)
    err = capsys.readouterr().err
    assert "every 15 minutes" in err and "make dashboard-auto-off" in err


def test_install_retries_a_slow_bootout_then_says_how_to_recover(tmp_path, capsys) -> None:
    repo, agents = _fake_repo(tmp_path), tmp_path / "LaunchAgents"
    waits = []
    assert auto.install(repo, agents, _Launchctl(codes=[5, 0]), uid=501,
                        python=Path("/p"), wait=waits.append) == 0
    assert waits == [1]
    assert auto.install(repo, agents, _Launchctl(codes=[5, 5, 5]), uid=501,
                        python=Path("/p"), wait=lambda s: None) == 1
    assert "make dashboard-auto-off" in capsys.readouterr().err


def test_uninstall_removes_the_agent_and_is_quiet_when_there_is_none(tmp_path, capsys) -> None:
    repo, agents = _fake_repo(tmp_path), tmp_path / "LaunchAgents"
    auto.install(repo, agents, _Launchctl(), uid=501, python=Path("/p"))
    run = _Launchctl()
    assert auto.uninstall(agents, run, uid=501) == 0
    assert ["bootout", "gui/501/com.beatyourleague.dashboard"] in run.calls
    assert not auto.installed(agents)
    capsys.readouterr()
    assert auto.uninstall(agents, _Launchctl(), uid=501) == 0
    assert "isn't installed" in capsys.readouterr().err


def test_status_reads_launchd_and_the_logs_last_lines(tmp_path, capsys) -> None:
    repo, agents = _fake_repo(tmp_path), tmp_path / "LaunchAgents"
    assert auto.status(repo, agents, _Launchctl(), uid=501) == 0
    assert "is off" in capsys.readouterr().err
    auto.install(repo, agents, _Launchctl(), uid=501, python=Path("/p"))
    (repo / auto.LOG_REL).write_text("Wed 4:15 PM ET  updated dashboard.html\n"
                                     "Wed 4:30 PM ET  this update failed (OSError: disk); "
                                     "the last page stays up\n")
    (repo / auto.PAGE_REL).write_text("<html></html>")
    now = (repo / auto.PAGE_REL).stat().st_mtime + 4 * 60
    capsys.readouterr()
    good = "state = not running\n\truns = 7\n\tlast exit code = 0\n"
    assert auto.status(repo, agents, _Launchctl(print_out=good), uid=501, now=now) == 0
    err = capsys.readouterr().err
    assert "waiting for its next build" in err and "Builds since it was loaded: 7." in err
    assert "The last build worked." in err and "The page was written 4 min ago." in err
    assert "this update failed (OSError: disk)" in err
    bad = "state = not running\n\tlast exit code = 1\n"
    assert auto.status(repo, agents, _Launchctl(print_out=bad), uid=501, now=now) == 1
    assert "The last build failed (exit 1)" in capsys.readouterr().err
    assert auto.status(repo, agents, _Launchctl(), uid=501, now=now) == 1   # installed, not loaded


def test_status_shows_the_failed_line_the_rotating_build_wrote_into_the_old_log(tmp_path,
                                                                                capsys) -> None:
    """Review #5. The build that rotates the log keeps writing to the file
    launchd opened, which is now .1, and no new log exists until the next
    build: status said "The log below says why" and showed nothing."""
    repo, agents = _fake_repo(tmp_path), tmp_path / "LaunchAgents"
    auto.install(repo, agents, _Launchctl(), uid=501, python=Path("/p"))
    log = repo / auto.LOG_REL
    log.write_text("x" * 600 + "\n")
    _REAL_ROTATE(log, max_bytes=500)
    with (repo / (auto.LOG_REL + ".1")).open("a") as held_open:
        held_open.write("Wed 4:30 PM ET  this update failed (OSError: disk); the last page stays up\n")
    assert not log.exists()
    capsys.readouterr()
    bad = "state = not running\n\tlast exit code = 1\n"
    assert auto.status(repo, agents, _Launchctl(print_out=bad), uid=501) == 1
    err = capsys.readouterr().err
    assert "The last build failed (exit 1). The log below says why." in err
    assert "this update failed (OSError: disk)" in err
    # Once the next build starts a new log, its lines come last.
    log.write_text("Wed 4:45 PM ET  updated dashboard.html\n")
    auto.status(repo, agents, _Launchctl(print_out=bad), uid=501)
    assert capsys.readouterr().err.rstrip().endswith("updated dashboard.html")


@pytest.mark.parametrize("environ", [{"CI": "true"}, {"GITHUB_ACTIONS": "true"}])
def test_the_updater_refuses_in_ci(environ, tmp_path, capsys) -> None:
    run = _Launchctl()
    assert auto.main(["install"], environ=environ, agent_dir=tmp_path, run=run) == 2
    assert run.calls == [] and not list(tmp_path.iterdir())
    assert "does not run in CI" in capsys.readouterr().err


def test_the_log_rotates_by_rename_never_truncate(tmp_path) -> None:
    log = tmp_path / "dashboard-updater.log"
    log.write_text("x" * 100)
    _REAL_ROTATE(log, max_bytes=200)
    assert log.read_text() == "x" * 100
    log.write_text("y" * 300)
    _REAL_ROTATE(log, max_bytes=200)
    assert not log.exists() and (tmp_path / "dashboard-updater.log.1").read_text() == "y" * 300


def test_an_auto_build_writes_a_reloading_page_opens_nothing_and_logs_one_line(tmp_path, capsys) -> None:
    out = dash.REPO_ROOT / "data" / f"dashboard-auto-{id(tmp_path)}.html"
    rich = rich_sources()
    collectors = {k: (lambda ctx, s=s: s) for k, s in rich.items()}
    opened = []
    try:
        code = dash.cli(["--auto", "--out", str(out), "--now", NOW.isoformat()],
                        environ={"STRIPE_API_KEY": SECRET}, env_file=tmp_path / ".env",
                        collectors=collectors, opener=opened.append)
        assert code == 0 and opened == []
        page = out.read_text(encoding="utf-8")
        body_tag = re.search(r"<body[^>]*>", page).group(0)
        assert 'data-refresh="900"' in body_tag and 'data-updater="agent"' in body_tag
        lines = capsys.readouterr().err.strip().splitlines()
        assert len(lines) == 1 and lines[0].endswith(f"updated {out.name}")
        assert not re.search(r"\d+ (of|sources|views|plans)", lines[0])
    finally:
        out.unlink(missing_ok=True)


def test_a_failed_auto_build_exits_1_without_a_secret(tmp_path, capsys, monkeypatch) -> None:
    def failing_build(*a, **k):
        raise RuntimeError(f"Stripe said no to {SECRET} for {LEAK}")
    monkeypatch.setattr(dash, "_build", failing_build)
    code = dash.cli(["--auto", "--out", "data/dashboard.html"], environ={"STRIPE_API_KEY": SECRET},
                    env_file=tmp_path / ".env", collectors={})
    err = capsys.readouterr().err
    assert code == 1 and "this update failed" in err and SECRET not in err and LEAK not in err


def test_with_the_updater_on_a_build_by_hand_keeps_the_tab_reloading(tmp_path, monkeypatch) -> None:
    """A snapshot written over the updater's page would stop the open tab
    reloading for good. With the agent installed, make dashboard writes the
    updater's kind of page; another --out stays a snapshot."""
    out = dash.REPO_ROOT / "data" / f"dashboard-byhand-{id(tmp_path)}.html"
    other = dash.REPO_ROOT / "data" / f"dashboard-other-{id(tmp_path)}.html"
    monkeypatch.setattr(dash, "DEFAULT_OUT", out)
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "com.beatyourleague.dashboard.plist").write_bytes(auto.plist_bytes(tmp_path, Path("/p")))
    rich = rich_sources()
    collectors = {k: (lambda ctx, s=s: s) for k, s in rich.items()}
    opened = []
    loaded = _Launchctl(print_out="state = not running\n")
    try:
        assert dash.cli(["--now", NOW.isoformat()], environ={}, env_file=tmp_path / ".env",
                        collectors=collectors, opener=opened.append, agent_dir=agents,
                        launchd=loaded) == 0
        assert opened == [out]
        assert 'data-updater="agent"' in out.read_text(encoding="utf-8")
        dash.cli(["--out", str(other), "--no-open"], environ={}, env_file=tmp_path / ".env",
                 collectors=collectors, agent_dir=agents, launchd=loaded)
        assert "data-refresh" not in re.search(r"<body[^>]*>", other.read_text()).group(0)
        # Without the agent, make dashboard is a snapshot again.
        dash.cli(["--no-open"], environ={}, env_file=tmp_path / ".env", collectors=collectors,
                 agent_dir=tmp_path / "none", launchd=loaded)
        assert "data-refresh" not in re.search(r"<body[^>]*>", out.read_text()).group(0)
    finally:
        out.unlink(missing_ok=True)
        other.unlink(missing_ok=True)


class _Disabled(_Launchctl):
    """launchd has the job loaded, but print-disabled marks it off."""

    def __init__(self, mark: str):
        super().__init__(print_out="state = not running\n")
        self.mark = mark

    def __call__(self, args):
        if args[0] == "print-disabled":
            self.calls.append(args)
            return 0, ('disabled services = {\n\t"com.apple.x" => enabled\n'
                       f'\t"com.beatyourleague.dashboard" => {self.mark}\n}}\n')
        return super().__call__(args)


@pytest.mark.parametrize("launchd", [_Launchctl(), _Disabled("disabled"), _Disabled("true")],
                         ids=["not-loaded", "disabled", "disabled-old-macos"])
def test_a_plist_launchd_isnt_running_never_makes_a_live_page(tmp_path, monkeypatch, capsys,
                                                             launchd) -> None:
    """Review #1. The plist alone was read as "the updater is on": after a
    failed install (the plist stayed) or with the item turned off in Login
    Items, make dashboard wrote "Live · every 15 min · Background updater"
    and said the page keeps itself fresh, while nothing rebuilt it."""
    out = dash.REPO_ROOT / "data" / f"dashboard-notloaded-{id(tmp_path)}.html"
    monkeypatch.setattr(dash, "DEFAULT_OUT", out)
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "com.beatyourleague.dashboard.plist").write_bytes(auto.plist_bytes(tmp_path, Path("/p")))
    collectors = {k: (lambda ctx, s=s: s) for k, s in rich_sources().items()}
    try:
        assert dash.cli(["--no-open", "--now", NOW.isoformat()], environ={},
                        env_file=tmp_path / ".env", collectors=collectors, agent_dir=agents,
                        launchd=launchd) == 0
        page = out.read_text(encoding="utf-8")
        assert "data-refresh" not in re.search(r"<body[^>]*>", page).group(0)
        assert "Background updater" not in page
        assert "keeps itself fresh" not in capsys.readouterr().err
    finally:
        out.unlink(missing_ok=True)
    assert auto.running(agents, _Launchctl(print_out="state = running\n"), uid=501)
    assert not auto.running(agents, launchd, uid=501)
    assert not auto.running(tmp_path / "none", _Launchctl(print_out="state = running\n"), uid=501)


def test_a_failed_install_leaves_no_plist_behind(tmp_path, capsys) -> None:
    """Review #1 (a): three failed bootstraps returned 1 and left the plist,
    which every later make dashboard read as a running updater."""
    repo, agents = _fake_repo(tmp_path), tmp_path / "LaunchAgents"
    assert auto.install(repo, agents, _Launchctl(codes=[5, 5, 5]), uid=501,
                        python=Path("/p"), wait=lambda s: None) == 1
    assert not auto.installed(agents) and not list(agents.iterdir())
    assert "make dashboard-auto again" in capsys.readouterr().err


# --- A3: the crons' files come from GitHub's copy --------------------- #

class _Git:
    """A stand-in git: origin/main holds ``files``; records every command."""

    def __init__(self, files: dict, fetch: int = 0, behind: str = "2",
                 cat_fails: bool = False, log: str = "2026-11-03T04:10:00-05:00"):
        self.files, self.fetch, self.behind = files, fetch, behind
        self.cat_fails, self.log = cat_fails, log
        self.calls: list = []

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        cmd = args[0]
        if cmd == "fetch":
            return self.fetch, b""
        if cmd == "ls-tree":
            return 0, b"\0".join(n.encode() for n in self.files) + b"\0"
        if cmd == "cat-file":
            name = args[2].split(":", 1)[1]
            return (1, b"") if self.cat_fails else (0, self.files[name])
        if cmd == "rev-list":
            return 0, (self.behind + "\n").encode()
        if cmd == "log":
            return 0, (self.log + "\n").encode()
        return 128, b""


def _sent_line(key: str, at: str) -> bytes:
    return (_json.dumps({"key": key, "sent_at": at, "provider": "resend"}) + "\n").encode()


def test_the_crons_files_are_read_from_githubs_copy_and_never_written_here(tmp_path) -> None:
    local = tmp_path / "checkout"
    (local / "data" / "processed").mkdir(parents=True)
    old = _sent_line("2026-w08-aaaaaaaaaa", "2026-10-28T23:00:00+00:00")
    (local / "data" / "processed" / "sent.jsonl").write_bytes(old)
    before = sorted(p.relative_to(local).as_posix() for p in local.rglob("*"))
    git = _Git({"data/processed/sent.jsonl": old + _sent_line("2026-w09-bbbbbbbbbb",
                                                              "2026-11-04T23:00:00+00:00"),
                "data/processed/ledger/typed-ppr-12-2026/calls.jsonl": b"",
                "site/week.json": b'{"season": "2026", "week": 9}',
                "../escape.txt": b"no", "README.md": b"not a cron file"})
    with dash.cron_copy(local, NOW, git) as cron:
        assert cron.source == "github" and cron.behind == 2 and cron.files == 3
        copy_root = cron.root
        assert copy_root != local and not str(copy_root).startswith(str(dash.REPO_ROOT))
        ctx = Context(env={}, now=NOW, root=local, cron=cron)
        sends = dash.collect_sends(ctx)
        assert [e["key"][:8] for e in sends.data["entries"]] == ["2026-w08", "2026-w09"]
        assert dash.collect_site(ctx).data["week"]["week"] == 9
        assert not (copy_root / "README.md").exists() and not (tmp_path / "escape.txt").exists()
    assert not copy_root.exists()                        # the temporary copy is gone
    assert sorted(p.relative_to(local).as_posix() for p in local.rglob("*")) == before
    assert {c[0] for c in git.calls} <= {"fetch", "ls-tree", "cat-file", "rev-list", "log"}
    assert git.calls[0] == ["fetch", "--quiet", "origin", "main"]


def test_without_github_the_build_reads_this_macs_copy_and_says_so(tmp_path) -> None:
    git = _Git({}, fetch=128)
    with dash.cron_copy(tmp_path, NOW, git) as cron:
        assert cron.source == "local" and cron.reason == "unreachable" and cron.root == tmp_path
    assert [c[0] for c in git.calls] == ["fetch", "log"]
    row = dash.cron_row(cron.view(), NOW)
    assert "GitHub couldn&#x27;t be reached, so this Mac&#x27;s copy was read" in row
    assert "Its newest commit is from Tue Nov 3, 4:10 AM ET" in row and 'class="warn"' in row
    broken = _Git({"site/week.json": b"{}"}, cat_fails=True)
    with dash.cron_copy(tmp_path, NOW, broken) as cron:
        assert cron.source == "local" and cron.reason == "unreadable"
    assert "GitHub&#x27;s copy couldn&#x27;t be read" in dash.cron_row(cron.view(), NOW)


def test_the_freshness_list_says_which_copy_and_how_far_behind(tmp_path) -> None:
    view = dash.CronCopy(root=tmp_path, source="github", behind=1, fetched_at=NOW).view()
    page = dash.render_page(rich_sources(), NOW, fonts=False, cron=view)
    srclist = page.split('<ul class="srclist">', 1)[1].split("</ul>", 1)[0]
    assert ("<b>Crons&#x27; files</b> <span>GitHub&#x27;s copy, fetched just now. This checkout is "
            "1 commit behind GitHub, which this page doesn&#x27;t need.</span>") in srclist
    level = dash.CronCopy(root=tmp_path, source="github", behind=0, fetched_at=NOW).view()
    assert "This checkout is up to date." in dash.cron_row(level, NOW)
    assert dash.cron_row(None, NOW) == ""


def test_every_collector_of_a_cron_file_goes_through_one_helper() -> None:
    text = (dash.REPO_ROOT / "run" / "dashboard.py").read_text(encoding="utf-8")
    assert not re.search(r'root\s*/\s*"data"\s*/\s*"processed"', text)
    assert not re.search(r'root\s*/\s*"site"\s*/\s*"(week\.json|join)"', text)
    assert not re.search(r'root\s*/\s*"content"', text)
    for rel in ("data/processed/sent.jsonl", "data/processed/suppressed.txt",
                "data/processed/ledger", "site/week.json", "site/join/players.json"):
        assert f'cron_file(ctx, "{rel}")' in text
    for rel in ("data/processed/sent.jsonl", "data/processed/ledger", "site/week.json",
                "site/join/players.json", "content/this-week.md"):
        assert rel in dash.CRON_PATHS


def test_the_bounce_check_reads_githubs_send_log(tmp_path, monkeypatch) -> None:
    copy = tmp_path / "copy"
    (copy / "data" / "processed").mkdir(parents=True)
    (copy / "data" / "processed" / "sent.jsonl").write_bytes(
        _sent_line("2026-w09-cccccccccc", "2026-10-28T12:00:00+00:00"))
    seen = []

    class Report:
        key_cannot_read, checked, errors, paid, unpaid = False, 1, 0, [], []

    import run.delivery as delivery

    def fake_check(entries, now, api_key):
        seen.append(entries)
        return Report()
    monkeypatch.setattr(delivery, "check_bounces", fake_check)
    cron = dash.CronCopy(root=copy, source="github")
    dash.collect_bounces(Context(env={"RESEND_READ_KEY": "re_x"}, now=NOW, root=tmp_path, cron=cron))
    assert [e["key"] for e in seen[0]] == ["2026-w09-cccccccccc"]


def test_git_is_never_interactive_and_never_waits_long(monkeypatch, tmp_path) -> None:
    real_git_run = _REAL_GIT_RUN
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0, b"ok", b"")
    monkeypatch.setattr(dash.subprocess, "run", fake_run)
    assert real_git_run(["fetch", "--quiet", "origin", "main"], tmp_path) == (0, b"ok")
    assert seen["cmd"][:2] == ["git", "fetch"] and seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in seen["env"]["GIT_SSH_COMMAND"]
    assert seen["timeout"] <= 30 and seen["stdin"] is subprocess.DEVNULL

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 20)
    monkeypatch.setattr(dash.subprocess, "run", boom)
    assert real_git_run(["fetch"], tmp_path) == (1, b"")


def test_a_build_reads_githubs_copy_end_to_end(tmp_path) -> None:
    out = dash.REPO_ROOT / "data" / f"dashboard-cron-{id(tmp_path)}.html"
    git = _Git({"site/week.json": b'{"season": "2026", "week": 9}'}, behind="3")
    rich = rich_sources()
    seen = {}

    def site(ctx):
        seen["root"] = ctx.cron.root
        seen["week"] = dash.collect_site(ctx).data["week"]["week"]
        return rich["site"]
    collectors = {**{k: (lambda ctx, s=s: s) for k, s in rich.items()}, "site": site}
    try:
        assert dash.cli(["--out", str(out), "--no-open", "--now", NOW.isoformat()], environ={},
                        env_file=tmp_path / ".env", collectors=collectors, git=git) == 0
        assert seen["week"] == 9 and not seen["root"].exists()
        page = out.read_text(encoding="utf-8")
        assert "This checkout is 3 commits behind GitHub" in page
    finally:
        out.unlink(missing_ok=True)


# --------------------------------------------------------------------- #
# Connect your dashboard (A4), "includes you" labels (A5), and the
# dashboard's own registry command (B1)
# --------------------------------------------------------------------- #

OWNER_VALUE = "owner.one@fans.mail,owner.two@fans.mail"
LOG_VALUE = "logsecret-0123456789abcdef0123456789"
ALL_SET = {"OWNER_EMAILS": OWNER_VALUE, "LOG_SECRET": LOG_VALUE,
           "TRAFFIC_FROM": "2026-10-01T00:00Z", "STRIPE_STATS_KEY": SECRET}


def _connected(**over: Source) -> dict[str, Source]:
    """Every step's source read: the rich scenario already has Stripe,
    costs, bounces and a registry."""
    S = rich_sources()
    S.update(over)
    return S


def _card(page: str) -> str:
    assert 'id="connect"' in page, "the Connect card is missing"
    return page.split('id="connect"', 1)[1].split("</ol></div>", 1)[0]


def _state(S: dict, env: dict, n: int) -> str:
    return next(s["state"] for s in dash.connect_steps(S, env) if s["step"].n == n)


def test_the_connect_card_lists_seven_numbered_steps_in_order() -> None:
    """A4: one ordered list of what to connect, each saying what it unlocks
    and where to put it, under the attention strip."""
    page = dash.render_page(empty_sources(), NOW, fonts=False, env={})
    card = _card(page)
    assert "Connect your dashboard" in page and "0 of 7 done" in card
    names = ["OWNER_EMAILS", "STRIPE_STATS_KEY", "TRAFFIC_FROM", "make cost", "LOG_SECRET",
             "RESEND_READ_KEY", "make dashboard-registry"]
    assert [s.name for s in dash.CONNECT_STEPS] == names
    at = [card.index(f"<code>{dash.h(n)}</code>") for n in names]
    assert at == sorted(at)
    for n in range(1, 8):
        assert f"<b>{n}</b>" in card
    # Under the attention strip, above the period switch.
    assert page.index('class="attn') < page.index('id="connect"') < page.index('class="filters"')
    # It unlocks what the plan says it does.
    stripe = dash.CONNECT_STEPS[1].unlocks
    for word in ("Money", "Profit", "Intake check", "PLAN §6 targets"):
        assert word in stripe
    assert "Optional" in card and "make dashboard-registry" in card and "CACHE_KEY" in card


@pytest.mark.parametrize("step", dash.CONNECT_STEPS, ids=lambda s: s.name)
def test_every_step_points_at_a_launch_step_that_says_it(step) -> None:
    """The LAUNCH.md step each line names must exist and talk about the same
    thing; a renumbered LAUNCH.md must fail here, not mislead the owner."""
    text = (dash.REPO_ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    ref = re.search(r"LAUNCH\.md (?:step|section) ([0-9]+b?)(?:, item ([0-9]+))?", step.how)
    assert ref, f"step {step.n} names no LAUNCH.md step"
    num_, item = ref.groups()
    head = re.search(rf"^## {re.escape(num_)}\. .*$", text, re.M)
    assert head, f"LAUNCH.md has no section {num_}"
    nxt = re.search(r"^## ", text[head.end():], re.M)
    body = text[head.end(): head.end() + nxt.start()] if nxt else text[head.end():]
    token = {"STRIPE_STATS_KEY": "owner-stats", "make dashboard-registry": "CACHE_KEY"}.get(
        step.name, step.name)
    assert token in body, f"LAUNCH.md section {num_} doesn't mention {token}"
    if item:
        assert re.search(rf"^\s*{item}\. ", body, re.M), f"section {num_} has no item {item}"


def test_each_step_ticks_itself_and_the_card_hides_when_done() -> None:
    page = dash.render_page(_connected(), NOW, fonts=False, env=ALL_SET)
    assert 'id="connect"' not in page and "Connect your dashboard" not in page
    # One name missing brings it back, with that step open and the rest ticked.
    env = {k: v for k, v in ALL_SET.items() if k != "LOG_SECRET"}
    card = _card(dash.render_page(_connected(), NOW, fonts=False, env=env))
    assert "6 of 7 done" in card
    assert card.count('class="cs done"') == 6 and card.count('class="cs open"') == 1
    assert "Add LOG_SECRET= to .env" in card


def test_step_2_is_never_done_while_step_1_is_open() -> None:
    """Connecting Stripe without OWNER_EMAILS counts the owner's own test
    purchase as the first sale, so a read Stripe still waits on step 1."""
    env = {k: v for k, v in ALL_SET.items() if k != "OWNER_EMAILS"}
    S = _connected()
    assert _state(S, env, 1) == "open" and _state(S, env, 2) == "waiting"
    card = _card(dash.render_page(S, NOW, fonts=False, env=env))
    assert "do step 1 first" in card and 'class="cs waiting"' in card
    assert _state(S, ALL_SET, 2) == "done"
    # Without Stripe, step 2 is open whatever step 1 says.
    off = _connected(stripe=dash.off("stripe", "No key."))
    assert _state(off, ALL_SET, 2) == "open"
    # An OWNER_EMAILS holding nothing usable is not done.
    junk = {**ALL_SET, "OWNER_EMAILS": "not-an-address"}
    assert _state(S, junk, 1) == "open" and _state(S, junk, 2) == "waiting"


def test_an_optional_step_never_keeps_the_card_up() -> None:
    S = _connected(bounces=dash.off("bounces", "RESEND_READ_KEY is not in this shell or .env."))
    page = dash.render_page(S, NOW, fonts=False, env=ALL_SET)
    assert 'id="connect"' not in page
    # The bounce line then carries its own how-to, never a link to a hidden card.
    line = page.split("Resend isn't connected.", 1)[1].split("</p>", 1)[0]
    assert "RESEND_READ_KEY" in line and "#connect" not in line and "Optional" in line


def test_a_typo_in_traffic_from_is_not_a_done_step() -> None:
    env = {**ALL_SET, "TRAFFIC_FROM": "yesterday"}
    S = _connected()
    assert _state(S, env, 3) == "open"
    card = _card(dash.render_page(S, NOW, fonts=False, env=env))
    assert "isn&#x27;t a UTC time" in card
    assert dash.own_flags(env)["visits"] is True


def test_costs_tick_step_4_and_hours_alone_do_not() -> None:
    from run.books import Books, Hours
    hours_only = Books(costs=[], hours=[Hours(NOW.date(), 1.0, "")], posts=[], problems=[],
                       found=("hours.csv",))
    S = _connected(books=dash._source("books", data=hours_only, read_at=NOW))
    assert _state(S, ALL_SET, 4) == "open"
    assert "no cost is recorded yet" in _card(dash.render_page(S, NOW, fonts=False, env=ALL_SET))
    assert _state(_connected(), ALL_SET, 4) == "done"


def test_the_card_shows_names_never_values() -> None:
    env = {**ALL_SET, "RESEND_READ_KEY": "re_live_ABCDEFGHIJKL0123"}
    S = _connected(books=dash.off("books", "Nothing yet."))
    page = dash.render_page(S, NOW, fonts=False, env=env)
    card = _card(page)
    assert "OWNER_EMAILS" in card and "LOG_SECRET" in card
    for value in (OWNER_VALUE, *OWNER_VALUE.split(","), LOG_VALUE, SECRET,
                  "re_live_ABCDEFGHIJKL0123", "2026-10-01T00:00Z"):
        assert value not in page
    assert "@" not in card
    assert dash.set_names(env) >= {"OWNER_EMAILS", "LOG_SECRET", "TRAFFIC_FROM",
                                   "STRIPE_STATS_KEY", "RESEND_READ_KEY"}
    assert "STRIPE_API_KEY" not in dash.set_names({**env, "STRIPE_API_KEY": "  "})


def test_unconnected_sections_shrink_to_one_line_naming_their_step() -> None:
    S = rich_sources()
    S["stripe"] = dash.off("stripe", "No Stripe key in this shell or .env.")
    S["registry"] = dash.off("registry", "The registry lives sealed in the CI cache.")
    page = dash.render_page(S, NOW, fonts=False, env={})
    money = page.split('id="money"', 1)[1].split('id="customers"', 1)[0]
    assert '<a href="#connect">Needs step 2: Stripe key</a>' in money
    assert "Stripe — not connected yet" not in page and "Once connected: Plans sold" not in page
    cust = page.split('id="customers"', 1)[1].split('id="issues"', 1)[0]
    # The registry step is on demand: its line carries its own how-to,
    # never a link to a card that can be hidden.
    line = cust.split("Registry isn't connected.", 1)[1].split("</p>", 1)[0]
    assert "Optional: When you want the list" in line and "#connect" not in line
    assert "data/dashboard-registry.html" in line
    # The KPI tiles say the same in their few words.
    tiles = re.findall(r'<div class="kpi off"><p class="kl">(Plans sold|Net revenue)</p>'
                       r'<p class="kval">—</p><p class="ks">.*?</p>', page)
    assert tiles and all("Needs step 2: Stripe key" in t for t in re.findall(
        r'<div class="kpi off"><p class="kl">(?:Plans sold|Net revenue)</p><p class="kval">—</p>'
        r'<p class="ks">(.*?)</p>', page))
    # A source with no step (the page counter) keeps its full setup card,
    # and an error is never shrunk to "not connected".
    S["traffic"] = dash.off("traffic", "CF keys missing.", "LAUNCH.md step 5b, items 6–7")
    S["bounces"] = dash._source("bounces", status="error", note="That key can only send.")
    page = dash.render_page(S, NOW, fonts=False, env={})
    assert "Page counter — not connected yet" in page and "Resend couldn" in page


def test_the_issues_all_clear_counts_what_it_could_not_read() -> None:
    """It used to say every source was healthy while five were never read."""
    S = rich_sources()
    for key in ("traffic", "stripe", "bounces", "registry", "books"):
        S[key] = dash.off(key, "Not connected in this test.")
    assert dash.sources_read_line(S) == (
        "Nothing to fix in the 7 sources read; 5 aren’t connected yet.")
    html = dash.issues_section([], [], S, NOW)
    assert "Nothing to fix in the 7 sources read; 5 aren’t connected yet." in html
    assert "healthy" not in html
    S["stripe"] = dash._source("stripe", status="error", note="boom")
    assert dash.sources_read_line(S) == (
        "Nothing to fix in the 7 sources read; 4 aren’t connected yet and 1 couldn’t be read.")
    one = rich_sources()
    one["books"] = dash.off("books", "Nothing yet.")
    assert dash.sources_read_line(one).endswith("; 1 isn’t connected yet.")
    assert dash.sources_read_line(rich_sources()) == "Nothing to fix in the 12 sources read."


def _kl(page: str, label: str) -> list[str]:
    """The label line of each Overview tile called ``label``."""
    return re.findall(rf'<div class="kpi"[^>]*><p class="kl">{re.escape(label)}(.*?)</p>', page)


def test_counts_holding_the_owners_own_activity_say_so() -> None:
    """A5: without OWNER_EMAILS and TRAFFIC_FROM the owner's own visits and
    test purchase read as demand; the counts carry an amber chip until then."""
    page = dash.render_page(rich_sources(), NOW, fonts=False, env={})
    assert all(dash.OWN_VISITS in k for k in _kl(page, "Page views")) and _kl(page, "Page views")
    for label in ("Plans sold", "Net revenue"):
        assert _kl(page, label) and all(dash.OWN_TESTS in k for k in _kl(page, label))
    assert dash.OWN_TESTS not in "".join(_kl(page, "Rosters checked"))
    cust = page.split('id="customers"', 1)[1].split('id="issues"', 1)[0]
    assert cust.count(dash.OWN_TESTS) == 2      # weekly reports and the other mail
    assert dash.OWN_VISITS in page.split("<h3>Page views per day", 1)[1].split("</h3>", 1)[0]
    # Each name clears its own chips.
    owner_only = dash.render_page(rich_sources(), NOW, fonts=False,
                                  env={"OWNER_EMAILS": OWNER_VALUE})
    assert dash.OWN_TESTS not in owner_only and dash.OWN_VISITS in owner_only
    both = dash.render_page(rich_sources(), NOW, fonts=False,
                            env={"OWNER_EMAILS": OWNER_VALUE, "TRAFFIC_FROM": "2026-10-01"})
    assert dash.OWN_TESTS not in both and dash.OWN_VISITS not in both


def test_one_day_holding_most_views_is_named() -> None:
    days = [f"2026-11-0{d}" for d in range(1, 6)]
    assert dash.one_day_hint(days, [1, 1, 49, 1, 1]) == "49 of 53 views are from Nov 3"
    assert dash.one_day_hint(days, [10, 10, 40, 0, 0]) == ""         # 67%: not most
    assert dash.one_day_hint(days, [0, 0, 8, 0, 0]) == ""            # too few to say
    assert dash.one_day_hint(days, [0, 0, 41, 0, 9]) == "41 of 50 views are from Nov 3"
    assert dash.one_day_hint(days, [0, 0, 40, 0, 10]) == ""          # exactly 80% is not over


def test_the_traffic_card_and_tile_carry_the_one_day_hint() -> None:
    now = datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc)
    lines = [{"day": "2026-11-03", "e": "view", "p": "index", "s": "", "v": "", "n": 49}]
    lines += [{"day": f"2026-11-0{d}", "e": "view", "p": "join", "s": "", "v": "", "n": 1}
              for d in (1, 2, 4)]
    lines.append({"day": "2026-10-30", "e": "view", "p": "join", "s": "", "v": "", "n": 1})
    rows = [{"e": "view", "p": l["p"], "v": "", "r": "", "d": "d", "s": "", "c": "CA", "n": l["n"]}
            for l in lines]
    S = rich_sources(now)
    S["traffic"] = dash._source("traffic", data={"rows": {"7d": rows, "30d": rows, "all": rows},
                                                 "daily": lines, "since": ""}, read_at=now)
    page = dash.render_page(S, now, fonts=False, env={})
    assert "49 of 53 views are from Nov 3. If that was you testing, step 3 in Connect your " \
           "dashboard leaves it out." in page
    assert 'title="Counts page views, never people (privacy §3). 49 of 53 views are from Nov 3"' \
        in page
    quiet = dash.render_page(S, now, fonts=False, env={"TRAFFIC_FROM": "2026-10-01"})
    assert "49 of 53 views are from Nov 3." in quiet and "If that was you" not in quiet


def test_the_funnel_says_what_the_counter_skips_and_count_js_agrees() -> None:
    page = dash.render_page(rich_sources(), NOW, fonts=False, env={})
    funnel = page.split('id="funnel"', 1)[1].split('id="money"', 1)[0]
    assert funnel.count(dash.h(dash.COUNTER_SKIPS)) == len(dash.PERIODS)
    # Every exemption the note names is one count.js really makes.
    js = (dash.REPO_ROOT / "site" / "count.js").read_text(encoding="utf-8")
    quiet = js.split("function quiet()", 1)[1].split("function ", 1)[0]
    for claim, code in (("Global Privacy Control", "globalPrivacyControl"),
                        ("Do Not Track", "doNotTrack"), ("?nocount=1", '"nocount") === "1"'),
                        ("automated browsers", "webdriver")):
        assert claim in dash.COUNTER_SKIPS and code in quiet
    # "Rosters checked" is one press of Check my roster on the join page.
    join = (dash.REPO_ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    press = join.split('$("resolve").addEventListener("click"', 1)[1].split("});", 1)[0]
    assert 'bylCount("roster"' in press and "Check my roster" in dash.COUNTER_SKIPS


def test_the_page_names_the_dashboards_own_registry_command() -> None:
    """B1: make stats-registry builds the terminal summary, never this page."""
    S = rich_sources()
    entries = S["sends"].data["entries"]
    S["sends"] = dash._source("sends", data={"entries": entries, "season": "2026", "stopped": 0,
                                             "summary": stats.send_summary(entries, "2026", None)},
                              read_at=NOW)
    assert S["sends"].data["summary"]["note"] == stats.OWNER_MAIL_UNKNOWN
    S["registry"] = dash._source("registry", status="error", note="unreadable copy")
    page = dash.render_page(S, NOW, fonts=False, env={})
    assert "make stats-registry" not in page
    assert "`make dashboard-registry`" in page          # the send log's note
    assert "make dashboard-registry" in dash.SOURCE_INFO["registry"][1]
    assert "CACHE_KEY" in dash.SOURCE_INFO["registry"][1]
    # make stats keeps its own command, which is right for it.
    assert "`make stats-registry`" in stats.OWNER_MAIL_UNKNOWN
    makefile = (dash.REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\ndashboard-registry:", 1)[1].split("\n\n", 1)[0]
    assert "-m run.dashboard --registry" in recipe and "CACHE_KEY" in recipe


# --------------------------------------------------------------------- #
# A6 Today and A7 PLAN §6 pace (branch dash-today)
# --------------------------------------------------------------------- #

WED = _utc(2026, 11, 4, 15, 0)        # Wed Nov 4 2026, 10 AM ET: D, Week 9's report day
D_TEXT = "2026-11-04"


def _today_sources(now: datetime = WED, *, week: dict | None = None, **extra: Source) -> dict:
    S = empty_sources(now)
    S["site"] = dash._source("site", data={"week": week if week is not None else {
        "season": "2026", "week": 8, "phase": "season", "lands_on": "2026-11-04",
        "built_at": "2026-10-27T18:04:03+00:00"}, "players_at": None, "switches": {}}, read_at=now)
    S["plan"] = dash._source("plan", data=dash.parse_plan_gates(plan_text(d=D_TEXT)), read_at=now)
    S.update(extra)
    return S


def _issue(sev: str, title: str) -> dash.Issue:
    return dash.Issue(sev, title, ("First step.", "Second step."))


def _trial_sends(n: int, at: str = "2026-11-05T15:00:00+00:00") -> Source:
    entries = [{"key": f"trial-2026-{j:012x}", "sent_at": at, "provider": "resend"} for j in range(n)]
    return dash._source("sends", data={"entries": entries, "season": "2026", "stopped": 0,
                                       "summary": stats.send_summary(entries, "2026")}, read_at=WED)


def _wf(file: str, *runs: tuple[datetime, str]) -> dict:
    """One workflow_health entry; ``runs`` are (start, conclusion), "" for one still going."""
    rows = sorted(({"created_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": "completed" if c else "in_progress", "conclusion": c,
                    "event": "schedule", "url": ""} for at, c in runs),
                  key=lambda r: r["created_at"], reverse=True)
    done = [r for r in rows if r["status"] == "completed"]
    return {"file": file, "label": dict(dash.WORKFLOWS)[file], "last": rows[0] if rows else None,
            "last_done": done[0] if done else None, "slot": None, "missing": False, "late": None}


GITHUB_ON = dash._source("github", data={}, read_at=WED)


def _kinds(tasks, kind: str) -> list:
    return [t for t in tasks if t.kind == kind]


def _env(*names: str) -> dict[str, str]:
    """A shell holding these names, with values the page can parse. The
    values are never shown; OWNER_EMAILS needs an address to count as set."""
    vals = {"OWNER_EMAILS": "owner@example.test", "TRAFFIC_FROM": "2026-11-03T23:00Z"}
    return {n: vals.get(n, "set") for n in names}


def test_connect_steps_are_named_in_order_and_carry_no_values() -> None:
    S = empty_sources()
    steps = dash.today_connect(S, {})
    assert [s[0] for s in steps] == ["owner_emails", "stripe", "traffic_from", "costs", "log_secret",
                                     "resend", "registry"]
    assert all(len(s) == 5 and isinstance(s[1], bool) and isinstance(s[3], int) for s in steps)
    assert not any(done for _i, done, *_ in steps)
    S["stripe"] = dash._source("stripe", data={"sessions": []}, read_at=NOW)
    names = ("TRAFFIC_FROM", "LOG_SECRET")
    done = {i: d for i, d, *_ in dash.today_connect(S, _env(*names))}
    # Stripe read without OWNER_EMAILS would count the owner's test sale.
    assert done["traffic_from"] and done["log_secret"] and not done["stripe"]
    stripe_how = next(s[4] for s in dash.today_connect(S, _env(*names)) if s[0] == "stripe")
    assert "do step 1 first" in stripe_how
    done = {i: d for i, d, *_ in dash.today_connect(S, _env(*names, "OWNER_EMAILS"))}
    assert done["owner_emails"] and done["stripe"]
    S["books"] = dash._source("books", data=books_fixture(), read_at=NOW)
    S["registry"] = rich_sources()["registry"]
    done = {i: d for i, d, *_ in dash.today_connect(S, {})}
    assert done["costs"] and done["registry"]


def test_today_and_the_card_read_one_list_of_steps() -> None:
    """Today's connect row is the card's first open step, done-ness included:
    two lists of steps once disagreed about when Stripe counted."""
    S = empty_sources()
    for env in ({}, _env("OWNER_EMAILS"), _env("OWNER_EMAILS", "TRAFFIC_FROM", "LOG_SECRET")):
        card = [s["state"] == "done" for s in dash.connect_steps(S, env)]
        assert card == [d for _i, d, *_ in dash.today_connect(S, env)]


def test_the_optional_step_never_reaches_today() -> None:
    """Review #7/#16: the registry step is done only on make
    dashboard-registry's own page, so on every other build it stayed open:
    Today listed it forever and the card never hid. It is on demand now,
    like the bounce key: on the card, never in Today, never keeping it up."""
    names = _env("OWNER_EMAILS", "TRAFFIC_FROM", "LOG_SECRET")
    S = _today_sources(stripe=dash._source("stripe", data={"sessions": []}, read_at=WED),
                       books=dash._source("books", data=books_fixture(), read_at=WED))
    assert S["registry"].status == "off" and S["bounces"].status == "off"
    tasks = dash.today_tasks(S, WED, names, [], [], None, None)
    assert _kinds(tasks, "connect") == []
    assert dash.connect_card(S, names) == ""
    states = {s["step"].n: s["state"] for s in dash.connect_steps(S, names)}
    assert states[6] == states[7] == "open"
    assert set(dash.OPTIONAL_CONNECT_STEPS) == {"resend", "registry"}
    assert [s.n for s in dash.CONNECT_STEPS if s.optional] == [6, 7]


def test_today_runs_in_its_fixed_order_and_folds_the_rest_into_later() -> None:
    issues = [_issue("critical", "Somebody paid and can't be served."),
              _issue("high", "The last hourly intake run failed."),
              _issue("high", "Two emails bounced."),
              _issue("medium", "A medium thing.")]
    tasks = dash.today_tasks(_today_sources(), WED, {}, issues, [], None, None)
    assert [t.kind for t in tasks] == ["risk", "risk", "risk", "connect", "rhythm", "selling"]
    assert tasks[0].title.startswith("Somebody paid") and tasks[0].tone == "bad"
    assert tasks[0].how == "First step. Then the rest of its steps in Issues."
    assert not any("medium" in t.title.lower() for t in tasks)
    assert tasks[3].id == "owner_emails"
    shown, later = dash.today_split(tasks)
    assert len(shown) == dash.TODAY_MAX == 5 and [t.kind for t in later] == ["selling"]
    card = dash.today_html(tasks)
    assert "Later (1)" in card and card.count('class="task') == 6
    # 20 + 15 + 15 + 5 + 5 = 60 minutes shown.
    assert "about 60 min today" in card


def test_today_without_github_never_claims_the_report_went_or_was_missed() -> None:
    tasks = dash.today_tasks(_today_sources(), WED, {}, [], [], None, None)
    rhythm = _kinds(tasks, "rhythm")[0]
    assert rhythm.state == "unknown" and "Can't tell until GitHub" in rhythm.how
    assert rhythm.title == "Read your own Week 9 report once it lands"
    assert "Can't tell yet" in dash.today_html(tasks)
    assert "Overdue" not in dash.today_html(tasks)


def test_the_wednesday_report_row_follows_github_run_state() -> None:
    S = _today_sources(github=GITHUB_ON)
    week_ago = _wf("weekly.yml", (WED - timedelta(days=7), "success"))
    row = _kinds(dash.today_tasks(S, WED, {}, [], [week_ago], None, None), "rhythm")[0]
    assert row.state == "open" and "once it lands" in row.title and "5:17 PM ET" in row.how
    evening = _utc(2026, 11, 4, 23, 0)
    sent = _wf("weekly.yml", (_utc(2026, 11, 4, 22, 18), "success"))
    row = _kinds(dash.today_tasks(S, evening, {}, [], [sent], None, None), "rhythm")[0]
    assert row.title == "Read your own Week 9 report" and "green" in row.how
    red = _wf("weekly.yml", (_utc(2026, 11, 4, 22, 18), "failure"))
    assert not _kinds(dash.today_tasks(S, evening, {}, [], [red], None, None), "rhythm")
    # Once the evening run rebuilt week.json, the week it names is the one sent.
    S2 = _today_sources(github=GITHUB_ON, week={"season": "2026", "week": 9, "phase": "season",
                                                "lands_on": "2026-11-11",
                                                "built_at": "2026-11-04T22:40:00+00:00"})
    row = _kinds(dash.today_tasks(S2, evening, {}, [], [sent], None, None), "rhythm")[0]
    assert row.title == "Read your own Week 9 report"


def test_saturday_and_monday_rows_and_no_row_on_other_days() -> None:
    sat = _utc(2026, 11, 7, 14, 0)                     # 9 AM ET, before 11:17
    S = _today_sources(sat, github=GITHUB_ON)
    row = _kinds(dash.today_tasks(S, sat, {}, [], [_wf("saturday.yml")], None, None), "rhythm")[0]
    assert "Saturday" in row.title and "11:17 AM ET" in row.how and "unless it goes red" in row.how
    later = _utc(2026, 11, 7, 18, 0)
    green = _wf("saturday.yml", (_utc(2026, 11, 7, 16, 18), "success"))
    assert not _kinds(dash.today_tasks(S, later, {}, [], [green], None, None), "rhythm")
    going = _wf("saturday.yml", (_utc(2026, 11, 7, 16, 18), ""))
    row = _kinds(dash.today_tasks(S, later, {}, [], [going], None, None), "rhythm")[0]
    assert row.how == "It's running now."
    row = _kinds(dash.today_tasks(S, later, {}, [], [_wf("saturday.yml")], None, None), "rhythm")[0]
    assert "hasn't started" in row.how and "missed" not in row.how.lower()
    mon = _utc(2026, 11, 9, 15, 0)
    row = _kinds(dash.today_tasks(_today_sources(mon), mon, {}, [], [], None, None), "rhythm")[0]
    assert "Monday" in row.title and row.state == "unknown"
    tue = _utc(2026, 11, 10, 15, 0)
    assert not _kinds(dash.today_tasks(_today_sources(tue, github=GITHUB_ON), tue, {}, [], [],
                                       None, None), "rhythm")


def _ledger_calls(*calls: tuple[int, str, str]) -> Source:
    """A ledger source of (week, status, recorded_at) calls."""
    return dash._source("ledger", data={"season": "2026", "unreadable": [], "calls": [
        {"store": "typed-ppr-12-2026", "week": w, "confidence": 0.6, "status": st,
         "outcome": "hit" if st == "graded" else None, "recorded_at": at,
         "graded_at": "2026-11-03T14:00:00+00:00" if st == "graded" else None}
        for w, st, at in calls]}, read_at=WED)


def test_a_missed_monday_grading_leads_only_while_calls_wait() -> None:
    wf = {**_wf("monday.yml"), "missing": True, "slot": _utc(2026, 11, 3, 13, 17)}
    week8 = [(8, "pending", "2026-10-28T22:30:00+00:00")] * 3
    S = _today_sources(ledger=_ledger_calls(*week8))
    tasks = dash.today_tasks(S, WED, {}, [], [wf], dash.ledger_view(S["ledger"], WED), None)
    assert tasks[0].kind == "risk" and "3 calls from before it wait to be graded" in tasks[0].title
    assert "Tue 8:17 AM ET" in tasks[0].title and "monday-receipts" in tasks[0].how
    S = _today_sources(ledger=_ledger_calls((8, "graded", "2026-10-28T22:30:00+00:00")))
    tasks = dash.today_tasks(S, WED, {}, [], [wf], dash.ledger_view(S["ledger"], WED), None)
    assert not _kinds(tasks, "risk")


def test_a_missed_grading_counts_only_calls_it_could_have_settled() -> None:
    """Review #12/#18: calls the next week's report recorded after the
    missed slot are about games not played yet. Running monday-receipts
    settles none of them, so they never raise the red row or its count."""
    wf = {**_wf("monday.yml"), "missing": True, "slot": _utc(2026, 11, 3, 13, 17)}
    thu = _utc(2026, 11, 5, 15, 0)
    week9 = {"season": "2026", "week": 9, "phase": "season", "lands_on": "2026-11-11",
             "built_at": "2026-11-04T22:40:00+00:00"}
    # Week 8 graded, six Week 9 calls recorded Wednesday night: nothing to settle.
    S = _today_sources(thu, week=week9, ledger=_ledger_calls(
        (8, "graded", "2026-10-28T22:30:00+00:00"),
        *[(9, "pending", "2026-11-04T22:30:00+00:00")] * 6))
    led = dash.ledger_view(S["ledger"], thu)
    assert led["pending"] == 6
    assert not _kinds(dash.today_tasks(S, thu, {}, [], [wf], led, None), "risk")
    # Two Week 8 calls still pending beside them: those two, never eight.
    S = _today_sources(thu, week=week9, ledger=_ledger_calls(
        *[(8, "pending", "2026-10-28T22:30:00+00:00")] * 2,
        *[(9, "pending", "2026-11-04T22:30:00+00:00")] * 6))
    row = _kinds(dash.today_tasks(S, thu, {}, [], [wf], dash.ledger_view(S["ledger"], thu), None),
                 "risk")[0]
    assert "2 calls from before it wait to be graded" in row.title
    # A call with no recorded time counts only when its week is over.
    S = _today_sources(thu, week=week9, ledger=_ledger_calls((8, "pending", ""), (9, "pending", "")))
    assert dash._gradeable_pending(S, wf["slot"]) == 1
    # A bare count with no calls behind it can't say which could be graded.
    assert not _kinds(dash.today_tasks(_today_sources(thu), thu, {}, [], [wf],
                                       {"pending": 3, "graded": 0}, None), "risk")


def test_a_missed_cron_names_its_own_workflow_and_only_wednesdays_has_the_kickoff_limit() -> None:
    """Review #20: Today said "Actions → monday-receipts", Issues said "the
    workflow" with Wednesday's kickoff caveat, and the attention card under
    Today's red row said "No urgent issues"."""
    import re as _re
    for path in (dash.REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        if path.name in dash.ACTIONS_NAMES:
            name = _re.search(r"^name:\s*(\S+)", path.read_text(encoding="utf-8"), _re.M).group(1)
            assert dash.ACTIONS_NAMES[path.name] == name
    assert set(dash.ACTIONS_NAMES) >= {f for f, _l in dash.WORKFLOWS}
    health = [{**_wf(f), "missing": True, "slot": _utc(2026, 11, 3, 13, 17)}
              for f in ("monday.yml", "weekly.yml", "saturday.yml")]
    S = _today_sources(ledger=_ledger_calls((8, "pending", "2026-10-28T22:30:00+00:00")))
    issues = dash.build_issues(S, WED, health, dash.ledger_view(S["ledger"], WED),
                               dash.metrics_for(S, "7d", WED))
    fixes = {i.title.split(" didn't")[0]: i.fix for i in issues if "didn't run" in i.title}
    assert fixes["Monday grading"][0] == "Actions → monday-receipts → Run workflow."
    assert fixes["Saturday check"][0] == "Actions → saturday-final-check → Run workflow."
    assert fixes["Wednesday reports"][0] == ("Actions → weekly-report → Run workflow, only before "
                                             "the week's first kickoff.")
    assert sum("kickoff" in " ".join(f) for f in fixes.values()) == 1
    # Today's grading row and the Issue give the same first step.
    tasks = dash.today_tasks(S, WED, {}, [], [health[0]], dash.ledger_view(S["ledger"], WED), None)
    assert _kinds(tasks, "risk")[0].how == fixes["Monday grading"][0]
    # With only the medium grading issue, the card under Today says "other".
    medium = [i for i in issues if i.severity == "medium"]
    card = dash.attention(medium, today_risk=True)
    assert "No other urgent issues." in card and "No urgent issues." not in card
    assert "The urgent one is first in Today." in card
    assert "No urgent issues." in dash.attention(medium)
    assert "No other urgent issues." in dash.attention([], today_risk=True)
    assert "All clear" in dash.attention([])


def _secrets_gate(status: str, detail: str) -> Source:
    return dash._source("launch", data={"gates": [{"area": "Owner", "status": status, "detail": detail,
                                                   "name": "GitHub Actions secrets are set"}]},
                        read_at=WED)


def test_deadlines_show_inside_14_days_and_never_overdue_when_unknown() -> None:
    assert not _kinds(dash.today_tasks(_today_sources(), WED, {}, [], [], None, None), "deadline")
    dec30 = _utc(2026, 12, 30, 15, 0)
    missing = _secrets_gate("OWNER", "missing: SENDER_POSTAL_ADDRESS — the sender line is off")
    rows = _kinds(dash.today_tasks(_today_sources(dec30, launch=missing), dec30, {}, [], [],
                                   None, None), "deadline")
    assert [t.id for t in rows] == ["owned_list", "sender_address"]
    assert rows[1].title == "Set SENDER_POSTAL_ADDRESS by Jan 11" and rows[1].state == "open"
    present = _secrets_gate("PASS", "all 9 present")
    assert [t.id for t in _kinds(dash.today_tasks(_today_sources(dec30, launch=present), dec30, {},
                                                  [], [], None, None), "deadline")] == ["owned_list"]
    other = _secrets_gate("OWNER", "missing: CACHE_KEY — the cache is off")
    assert [t.id for t in _kinds(dash.today_tasks(_today_sources(dec30, launch=other), dec30, {},
                                                  [], [], None, None), "deadline")] == ["owned_list"]
    cant = _secrets_gate("OWNER", "can't read them from this machine (gh not signed in)")
    row = next(t for t in dash.today_tasks(_today_sources(dec30, launch=cant), dec30, {}, [], [],
                                           None, None) if t.id == "sender_address")
    assert row.state == "unknown" and "gh auth login" in row.how
    jan12 = _utc(2027, 1, 12, 15, 0)
    over = _kinds(dash.today_tasks(_today_sources(jan12, launch=missing), jan12, {}, [], [],
                                   None, None), "deadline")
    assert [t.state for t in over] == ["overdue"] and "it was due Jan 11" in over[0].title
    # Unknown, or a decision only the owner knows: never overdue.
    assert not _kinds(dash.today_tasks(_today_sources(jan12), jan12, {}, [], [], None, None),
                      "deadline")


def test_every_deadline_is_still_written_in_launch_md() -> None:
    launch = (dash.REPO_ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    for dl in dash.DEADLINES:
        assert dl["launch_text"] in launch, dl["id"]
        assert f"{dl['due']:%b} {dl['due'].day}" in dl["launch_text"], dl["id"]
        year = re.search(r"\b(20\d\d)\b", dl["launch_text"])
        assert not year or int(year.group(1)) == dl["due"].year


def test_the_selling_row_names_the_next_draft_only_when_it_is_this_weeks() -> None:
    from run.economics import SELLING_MIN_PER_DAY
    drafts = "# Week 9 posts — drafts, not posted\n\n## 1. The closest call (158/280)\n\ntext\n"
    week = {"season": "2026", "week": 9, "phase": "season", "lands_on": "2026-11-11",
            "built_at": "2026-11-04T22:40:00+00:00"}
    thu = _utc(2026, 11, 5, 15, 0)
    S = _today_sources(thu, week=week)
    row = _kinds(dash.today_tasks(S, thu, {}, [], [], None, drafts), "selling")[0]
    assert row.minutes == SELLING_MIN_PER_DAY and "“The closest call”" in row.how
    row = _kinds(dash.today_tasks(S, thu, {}, [], [], None, drafts.replace("Week 9", "Week 8")),
                 "selling")[0]
    assert "Week 8's" in row.how and "replies" in row.how
    # On the next report's day the drafts are last week's, whatever they say.
    wed = _utc(2026, 11, 11, 15, 0)
    row = _kinds(dash.today_tasks(S, wed, {}, [], [], None, drafts), "selling")[0]
    assert "Week 9's" in row.how
    row = _kinds(dash.today_tasks(S, thu, {}, [], [], None, None), "selling")[0]
    assert "No drafts" in row.how
    over = _today_sources(thu, week={**week, "phase": "over"})
    assert not [t for t in dash.today_tasks(over, thu, {}, [], [], None, drafts)
                if t.kind in ("selling", "rhythm")]


def test_the_today_card_sits_above_everything_else_on_the_page() -> None:
    page = dash.render_page(rich_sources(), NOW, fonts=False)
    assert page.index('id="today"') < page.index('class="attn') < page.index('id="overview"')
    assert re.search(r"about \d+ min today", page)
    card = page.split('id="today"', 1)[1].split('class="attn', 1)[0]
    for word in ("calibrated", "tested", "proven", "accurate", " just ", "exactly", "—"):
        assert word not in card.lower(), word


def test_today_never_shows_a_secret_or_an_address() -> None:
    env = {"STRIPE_STATS_KEY": SECRET, "OWNER_EMAILS": LEAK, "LOG_SECRET": "x" * 40}
    page = dash.render_page(rich_sources(), NOW, fonts=False, env=env)
    card = page.split('id="today"', 1)[1].split('class="attn', 1)[0]
    assert SECRET not in page and LEAK not in page and "x" * 40 not in page
    assert "Add OWNER_EMAILS" not in card       # set, so the step is done


def test_gate_read_by_dates() -> None:
    d, today = date(2026, 11, 4), date(2026, 11, 4)
    assert dash.gate_read_by("D+14", d, today) == date(2026, 11, 18)
    assert dash.gate_read_by("D+28", d, today) == date(2026, 12, 2)
    assert dash.gate_read_by("Dec 22 (Week 16)", d, today) == date(2026, 12, 22)
    assert dash.gate_read_by("D+14 after each League Pass", d, today) is None
    assert dash.gate_read_by("D+14", None, today) is None
    assert dash.gate_read_by("Jan 5", d, today) == date(2027, 1, 5)


def _gate(targets: list[dict], word: str) -> dict:
    return next(t for t in targets if word in t["metric"].lower())


def test_a_target_behind_a_straight_line_from_d_is_todays_action() -> None:
    nov11 = _utc(2026, 11, 11, 15, 0)             # 7 of 14 days gone: 10 of 20 by now
    S = _today_sources(nov11, sends=_trial_sends(4))
    t = _gate(dash.plan_targets(S, nov11, S["sends"].data, None, S["registry"]), "free reports")
    assert t["state"] == "behind_pace" and t["expected"] == 10 and t["days_left"] == 7
    assert t["pace"] == ("4 of 20 · 7 days left · about 2.3 a day needed · a straight line from D "
                         "says 10 by now")
    tasks = dash.today_tasks(S, nov11, {}, [], [], None, None)
    row = _kinds(tasks, "target")[0]
    assert row.title.endswith("4 of 20 by Nov 18, behind pace") and row.minutes == 0
    assert row.how.startswith("About 2.3 a day from here")
    assert "in selling time" in dash.today_html(tasks)
    gates = dash.gates_html(S, nov11, S["sends"].data, None, S["registry"])
    assert "Behind pace" in gates and "a straight line from D says 10 by now" in gates
    # Under the red line (<10) but before its read-by date: no red action yet.
    assert not t["red_now"] and "PLAN §6 says:" not in gates
    # On the line is on pace, and no row.
    S = _today_sources(nov11, sends=_trial_sends(10))
    t = _gate(dash.plan_targets(S, nov11, S["sends"].data, None, S["registry"]), "free reports")
    assert t["state"] == "on_pace"
    assert not _kinds(dash.today_tasks(S, nov11, {}, [], [], None, None), "target")


def test_past_its_date_and_red_shows_plans_own_words() -> None:
    nov20 = _utc(2026, 11, 20, 15, 0)
    S = _today_sources(nov20, sends=_trial_sends(5))
    red = _gate(S["plan"].data["gates"], "free reports")["red"]
    assert "the selling hours aren't happening" in red      # PLAN.md's own words
    t = _gate(dash.plan_targets(S, nov20, S["sends"].data, None, S["registry"]), "free reports")
    assert t["state"] == "missed" and t["red_now"]
    gates = dash.gates_html(S, nov20, S["sends"].data, None, S["registry"])
    assert "PLAN §6 says:" in gates and dash.h(red) in gates and "Missed" in gates
    row = _kinds(dash.today_tasks(S, nov20, {}, [], [], None, None), "target")[0]
    assert row.how == f"PLAN §6 says: {red}" and "when it was read on Nov 18" in row.title
    # Short of green but not over the red line: missed, and no red action.
    S = _today_sources(nov20, sends=_trial_sends(15))
    t = _gate(dash.plan_targets(S, nov20, S["sends"].data, None, S["registry"]), "free reports")
    assert t["state"] == "missed" and not t["red_now"]
    assert "PLAN §6 says:" not in dash.gates_html(S, nov20, S["sends"].data, None, S["registry"])


def test_an_unmeasurable_target_names_what_is_missing() -> None:
    S = _today_sources()
    gates = dash.gates_html(S, WED, None, None, S["registry"])
    assert "Not measurable here" not in gates
    assert "Needs STRIPE_STATS_KEY in .env" in gates and "Needs the send log, which this build couldn&#x27;t read" in gates
    assert "Needs the registry (make dashboard-registry)" in gates
    assert "Needs the public record, which this build couldn&#x27;t read" in gates
    S["stripe"] = dash._source("stripe", status="error", note="boom")
    assert dash.h("Stripe couldn't be read this time") in dash.gates_html(S, WED, None, None,
                                                                          S["registry"])


def test_a_refund_rate_under_the_floor_is_a_raw_count_never_a_percent() -> None:
    now = _utc(2026, 11, 6, 15)
    sessions = stripe_sessions()[:3]
    for k, s in enumerate(sessions):
        s.update(created=int(_utc(2026, 11, 5, 12 + k).timestamp()), full_refund=k == 0,
                 refunded=s["amount"] if k == 0 else 0.0, dispute=None)
    S = _today_sources(now, stripe=dash._source(
        "stripe", data={"sessions": sessions, "link_map": True, "dispute_errors": 0}, read_at=now))
    t = _gate(dash.plan_targets(S, now, None, None, S["registry"]), "refund rate")
    assert t["state"] == "few" and t["cur_text"] == "1 of 3 refunded"
    row = next(r for r in dash.gates_html(S, now, None, None, S["registry"]).split("<tr>")
               if "Refund rate" in r)
    assert '<td class="num">1 of 3 refunded</td>' in row and "Too few to judge" in row


# --------------------------------------------------------------------- #
# Review fixes (dash-fix-fresh): a cron GitHub didn't have yet, the launch
# gates on GitHub's copy, a broken ledger named by its own path, cleanup
# on SIGTERM, and the temp page under the same ignore rule as the page
# --------------------------------------------------------------------- #

# monday.yml's Tuesday line (f0407d5): committed Tue Nov 3 4:44 AM ET,
# merged onto main's line at 2:46 PM ET, pushed to GitHub at 7:18 PM ET.
TUESDAY_LINE_COMMITTED = "2026-11-03T04:44:55-05:00"
MONDAY_CRONS = ["17 13 * * 1", "17 13 * * 2"]


def _monday_runs(*starts: str) -> Source:
    runs = [{"created_at": at, "status": "completed", "conclusion": "success",
             "event": "workflow_dispatch", "url": ""} for at in starts]
    return dash._source("github", data={"monday.yml": {"label": "Monday grading", "runs": runs}},
                        read_at=WED)


def _github_view(crons: list[str], changed: str | None) -> dict:
    return {"source": "github", "reason": "", "behind": 0, "fetched_at": WED.isoformat(),
            "local_at": None, "files": 0,
            "schedules": {"monday.yml": {"crons": crons, "changed": changed}}}


def test_a_cron_that_reached_github_after_its_slot_is_not_missed(monkeypatch) -> None:
    """Review #6, Nov 4 2026. Today led with a red "Monday grading didn't run
    after its Tue 8:17 AM ET slot, and 3 calls wait to be graded." That line
    was committed at 4:44 AM but reached GitHub at 7:18 PM, after the slot,
    so neither GitHub nor the Worker knew of it at 8:17 AM. A schedule is
    owed only a day after its change joined main."""
    src = _monday_runs("2026-11-02T22:21:36Z")
    cron = _github_view(MONDAY_CRONS, TUESDAY_LINE_COMMITTED)
    monday = dash.workflow_health(src, WED, cron=cron)[0]
    assert monday["slot"] == _utc(2026, 11, 3, 13, 17) and not monday["missing"]
    S = _today_sources(github=src)
    ledger = {"pending": 3, "graded": 0, "unreadable": [], "stale": 0}
    tasks = dash.today_tasks(S, WED, {}, None, None, ledger, None, cron=cron)
    assert not [t for t in tasks if t.id == "grading"]
    issues = dash.build_issues(S, WED, [monday], None, dash.metrics_for(S, "7d", WED))
    assert not any("didn't run" in i.title for i in issues)
    # The page reads one health list for Issues and Today: neither says it.
    page = dash.render_page(S, WED, fonts=False, env={}, cron=cron)
    assert "Monday grading didn&#x27;t run" not in page
    # The same on this checkout's copy, when GitHub's wasn't read.
    monkeypatch.setattr(dash, "schedule_changed",
                        lambda root, name: datetime.fromisoformat(TUESDAY_LINE_COMMITTED))
    assert not dash.workflow_health(src, WED)[0]["missing"]
    # A week on, the Tuesday slot is owed, and a missed one leads Today.
    later = _utc(2026, 11, 10, 15, 0)
    owed = dash.workflow_health(src, later, cron=cron)[0]
    assert owed["missing"]
    # Three Week 8 calls recorded before that slot, still pending.
    S = _today_sources(later, github=src, ledger=_ledger_calls(
        *[(8, "pending", "2026-10-28T22:30:00+00:00")] * 3))
    tasks = dash.today_tasks(S, later, {}, None, None, dash.ledger_view(S["ledger"], later),
                             None, cron=cron)
    assert [t for t in tasks if t.id == "grading"]


def test_the_schedule_is_the_one_github_runs_not_this_checkouts() -> None:
    """Review #6: a cron line on this branch that main doesn't have names a
    slot GitHub never runs. GitHub's copy holds only Monday's line here; this
    checkout's monday.yml carries Tuesday's too."""
    assert "17 13 * * 2" in dash.workflow_crons(dash.REPO_ROOT, "monday.yml")
    src = _monday_runs("2026-11-02T13:18:00Z")
    cron = _github_view(["17 13 * * 1"], "2026-10-15T19:22:04-04:00")
    monday = dash.workflow_health(src, WED, cron=cron)[0]
    assert monday["slot"] == _utc(2026, 11, 2, 13, 17) and not monday["missing"]
    assert dash.crons_for(dash.REPO_ROOT, "monday.yml", cron) == ["17 13 * * 1"]
    # Without GitHub's copy, this checkout's schedule is what's read.
    assert dash.crons_for(dash.REPO_ROOT, "monday.yml", None) == MONDAY_CRONS


def test_githubs_copy_carries_mains_schedules_and_when_they_changed(tmp_path) -> None:
    monday = b'on:\n  schedule:\n    - cron: "17 13 * * 1"\n    # - cron: "0 0 * * 0"\n'
    git = _Git({"site/week.json": b"{}", ".github/workflows/monday.yml": monday},
               log="2026-11-03T14:46:36-05:00")
    with dash.cron_copy(tmp_path, NOW, git) as cron:
        assert cron.files == 1 and not (cron.root / ".github").exists()
        assert cron.schedules == {"monday.yml": {"crons": ["17 13 * * 1"],
                                                 "changed": "2026-11-03T14:46:36-05:00"}}
        assert cron.view()["schedules"] == cron.schedules
    logs = [c for c in git.calls if c[0] == "log" and ".github/workflows/monday.yml" in c]
    assert logs and {"--first-parent", "-m", "origin/main"} <= set(logs[0])
    assert all(c[0] in ("fetch", "ls-tree", "cat-file", "rev-list", "log") for c in git.calls)


def test_a_cron_merged_from_a_branch_counts_from_the_merge(tmp_path) -> None:
    """Review #6: the cron commit's own date was used, hours before the
    merge that brought it onto main."""
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}

    def git(*args: str, when: str = "2026-10-01T00:00:00+00:00") -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args],
                       cwd=tmp_path, check=True, capture_output=True,
                       env={**env, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    git("init", "-q", "-b", "main")
    (wf / "monday.yml").write_text('on:\n  schedule:\n    - cron: "17 13 * * 1"\n')
    git("add", "-A")
    git("commit", "-q", "-m", "monday")
    git("checkout", "-q", "-b", "side")
    (wf / "monday.yml").write_text('on:\n  schedule:\n    - cron: "17 13 * * 1"\n'
                                   '    - cron: "17 13 * * 2"\n')
    git("add", "-A")
    git("commit", "-q", "-m", "tuesday", when="2026-11-03T09:44:55+00:00")
    git("checkout", "-q", "main")
    (tmp_path / "other.txt").write_text("x")
    git("add", "-A")
    git("commit", "-q", "-m", "other", when="2026-11-03T12:00:00+00:00")
    git("merge", "-q", "--no-ff", "-m", "merge", "side", when="2026-11-03T19:46:36+00:00")
    assert dash.schedule_changed(tmp_path, "monday.yml") == _utc(2026, 11, 3, 19, 46, 36)


def test_the_launch_gates_read_githubs_copy_of_the_crons_files(tmp_path, monkeypatch) -> None:
    """Review #0. The site and record cards read GitHub's week.json while the
    launch gates read this checkout's: a branch behind main's Wednesday
    commit said "Launch check warns: week.json is ... stale" beside a site
    card showing the fresh week."""
    import run.launch_check as lc
    stale, fresh = tmp_path / "checkout", tmp_path / "github"
    for root, week, lands in ((stale, 8, "2020-01-07"), (fresh, 9, "2099-01-07")):
        (root / "site").mkdir(parents=True)
        (root / "site" / "week.json").write_text(_json.dumps({"week": week, "lands_on": lands}))
    (fresh / "site" / "this-week.html").write_text("<p>Heads up: no projected total</p>")
    monkeypatch.setattr(lc, "SITE", stale / "site")
    seen = {}
    monkeypatch.setattr(lc, "closest_gate", lambda w, processed_dir=None: (
        seen.update(closest=processed_dir), lc.Gate("Site", "closest", "PASS", ""))[1])
    monkeypatch.setattr(lc, "check_record", lambda processed_dir=None, today=None: (
        seen.update(record=processed_dir), [])[1])
    monkeypatch.setattr(dash, "FAST_GATES", ("check_week_json", "check_record"))

    def gates(cron) -> dict:
        got = dash.collect_launch(Context(env={}, now=WED, root=stale, cron=cron)).data["gates"]
        return {g["name"]: g for g in got}
    # make launch-check's reading is unchanged: this checkout's copy.
    old = gates(None)
    assert old["Season clock data (week.json) is current"]["status"] == "WARN"
    assert seen == {"closest": None, "record": None}
    new = gates(dash.CronCopy(root=fresh, source="github"))
    clock = new["Season clock data (week.json) is current"]
    assert clock["status"] == "PASS" and "week 9" in clock["detail"]
    assert new["This week's sample is linked only when card 01 has a total"]["status"] == "FAIL"
    assert seen == {"closest": fresh / "data" / "processed", "record": fresh / "data" / "processed"}
    assert "site/this-week.html" in dash.CRON_PATHS


def test_a_broken_ledger_store_is_named_by_its_repo_path_and_its_copy(tmp_path) -> None:
    """Review #14. The message carried the deleted temp folder's path (or
    this Mac's checkout path), and the fix sent the owner to a local file
    that could be clean while GitHub's was broken."""
    season = dash._season(Context(env={}, now=WED))
    for source in ("github", "local"):
        root = tmp_path / source / "byl-dashboard-x"
        store = root / "data" / "processed" / "ledger" / f"typed-ppr-12-{season}"
        store.mkdir(parents=True)
        (store / "calls.jsonl").write_text("<<<<<<< HEAD\n")
        ctx = Context(env={}, now=WED, root=root if source == "local" else tmp_path,
                      cron=dash.CronCopy(root=root, source=source))
        src = dash.collect_ledger(ctx)
        [broken] = src.data["unreadable"]
        assert f"data/processed/ledger/typed-ppr-12-{season}/calls.jsonl" in broken
        assert str(tmp_path) not in broken and "byl-dashboard" not in broken
        S = rich_sources(WED)
        S["ledger"] = src
        hit = [i for i in dash.build_issues(S, WED, [], dash.ledger_view(src, WED),
                                            dash.metrics_for(S, "7d", WED))
               if "ledger store" in i.title]
        assert len(hit) == 1
        if source == "github":
            assert "in GitHub's copy" in hit[0].title and "on main" in hit[0].fix
        else:
            assert "in this Mac's copy" in hit[0].title and "data/processed/ledger" in hit[0].fix


def test_a_failed_write_leaves_no_temp_page(tmp_path, monkeypatch) -> None:
    """Review #4. A build stopped between the write and the swap left
    .dashboard.html.<pid>.tmp, a full page of counts, one per process."""
    out = dash.REPO_ROOT / "data" / f"dashboard-failswap-{id(tmp_path)}.html"

    def stopped(a, b):
        raise KeyboardInterrupt
    monkeypatch.setattr(dash.os, "replace", stopped)
    with pytest.raises(KeyboardInterrupt):
        dash.write_dashboard(rich_sources(), out, NOW, env={})
    assert not out.exists() and not dash.temp_page(out).exists()


SIGTERM_CHILD = """
import sys, time
sys.path.insert(0, sys.argv[1])
import run.dashboard as dash
from datetime import datetime, timezone

def git(args, cwd):
    if args[0] == "ls-tree":
        return 0, b"site/week.json\\0"
    if args[0] == "cat-file":
        return 0, b"{}"
    return 0, b"0"

with dash.term_unwinds():
    with dash.cron_copy(dash.REPO_ROOT, datetime.now(timezone.utc), git) as cron:
        open(sys.argv[2], "w").write(str(cron.root))
        time.sleep(60)
"""


def test_sigterm_unwinds_so_the_temp_copy_is_removed(tmp_path) -> None:
    """Review #4. launchd stops the updater with SIGTERM, whose default
    ends Python without running a finally: the temporary copy of GitHub's
    files stayed in TMPDIR. Run in a child process, signalled for real."""
    import signal
    import sys
    import time as _time
    marker = tmp_path / "copy-root.txt"
    child = subprocess.Popen([sys.executable, "-c", SIGTERM_CHILD, str(dash.REPO_ROOT), str(marker)],
                             env={**os.environ, "TMPDIR": str(tmp_path)})
    try:
        for _ in range(400):
            if marker.exists() and marker.read_text():
                break
            _time.sleep(0.05)
        copy = Path(marker.read_text())
        assert copy.exists()
        child.send_signal(signal.SIGTERM)
        assert child.wait(timeout=20) == 143
        assert not copy.exists()
    finally:
        child.kill()
    # The handler is put back afterwards, in this process too.
    before = signal.getsignal(signal.SIGTERM)
    with dash.term_unwinds():
        assert signal.getsignal(signal.SIGTERM) is not before
    assert signal.getsignal(signal.SIGTERM) is before


def test_the_temp_page_must_be_gitignored_too(tmp_path, capsys) -> None:
    """Review #15. reports/rival-report-owner.html is ignored by a name
    pattern; its temp sibling .rival-report-owner.html.<pid>.tmp was not, so
    an interrupted build could leave a page of counts for git add -A."""
    out = dash.REPO_ROOT / "reports" / f"rival-report-dashprobe-{id(tmp_path)}.html"
    assert not out.exists()
    assert stats._gitignored(out) and not stats._gitignored(dash.temp_page(out))
    assert dash.cli(["--out", str(out), "--no-open"], environ={}, env_file=tmp_path / ".env",
                    collectors={}) == 2
    assert "is not gitignored" in capsys.readouterr().err and not out.exists()
    assert stats._gitignored(dash.temp_page(dash.DEFAULT_OUT))


# Review fixes (branch dash-fix-today)
# --------------------------------------------------------------------- #

def test_the_registry_page_is_its_own_snapshot_the_updater_never_writes(tmp_path,
                                                                        monkeypatch) -> None:
    """Review #16: with the background updater on, make dashboard-registry
    wrote data/dashboard.html in agent mode, and within 15 minutes the agent
    rebuilt it without the registry while the tab reloaded itself."""
    assert dash.REGISTRY_OUT == dash.REPO_ROOT / "data" / "dashboard-registry.html"
    out = dash.REPO_ROOT / "data" / f"dashboard-main-{id(tmp_path)}.html"
    reg_out = dash.REPO_ROOT / "data" / f"dashboard-registry-{id(tmp_path)}.html"
    monkeypatch.setattr(dash, "DEFAULT_OUT", out)
    monkeypatch.setattr(dash, "REGISTRY_OUT", reg_out)
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "com.beatyourleague.dashboard.plist").write_bytes(auto.plist_bytes(tmp_path, Path("/p")))
    collectors = {k: (lambda ctx, s=s: s) for k, s in rich_sources().items()}
    opened = []
    try:
        assert dash.cli(["--registry", str(tmp_path / "rosters.json"), "--now", NOW.isoformat()],
                        environ={}, env_file=tmp_path / ".env", collectors=collectors,
                        opener=opened.append, agent_dir=agents) == 0
        assert opened == [reg_out] and not out.exists()
        body = re.search(r"<body[^>]*>", reg_out.read_text(encoding="utf-8")).group(0)
        assert "data-refresh" not in body and 'data-updater="agent"' not in body
    finally:
        out.unlink(missing_ok=True)
        reg_out.unlink(missing_ok=True)
    # The real name is gitignored, and the step says where the page goes.
    assert stats._gitignored(Path("data/dashboard-registry.html"))
    step = dash.CONNECT_STEPS[6]
    assert step.optional and "data/dashboard-registry.html" in step.how
    assert "background updater never overwrites it" in step.how
    makefile = (dash.REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\ndashboard-registry:", 1)[1].split("\n\n", 1)[0]
    assert "data/dashboard.html" not in recipe


def test_the_key_steps_say_only_what_launch_md_allows() -> None:
    """Review #17/#21: step 6 put the Full access Resend key in .env, which
    LAUNCH.md step 2 item 3 says goes nowhere but the GitHub secret, and
    claimed the hourly run checks bounces without it. Step 2 cited a LAUNCH
    item that keeps the owner-stats key out of .env; section 8 allows it."""
    text = (dash.REPO_ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    item3 = text.split("## 2. Resend", 1)[1].split("\n4. ", 1)[0]
    assert "goes nowhere but that secret" in item3
    resend = dash.CONNECT_STEPS[5]
    assert "only as the GitHub secret RESEND_READ_KEY, never in .env" in resend.how
    assert "Add RESEND_READ_KEY" not in resend.how and "without it" not in resend.how.split(
        "With that secret set")[0]
    assert "With that secret set, the hourly run checks bounces" in resend.how
    assert "Optional" not in resend.how            # the card's pill and the line say it once
    line = dash.needs_line(dash.off("bounces", "x"))
    assert line.count("Optional") == 1 and "to .env" not in line
    assert "to .env" not in dash.TODAY_CONNECT[6][1]
    stripe = dash.CONNECT_STEPS[1]
    assert "(LAUNCH.md section 8, The dashboard)" in stripe.how
    dash_para = text.split("**The dashboard.**", 1)[1].split("\n\n", 1)[0]
    assert "STRIPE_STATS_KEY" in dash_para and ".env" in dash_para
    # The card's own header no longer says every name goes in .env.
    S = empty_sources()
    card = dash.connect_card(S, {})
    assert "unless a step says otherwise" in card


def _wed_rhythm(now: datetime, week: dict, runs: tuple = (), games: Path | None = None):
    S = _today_sources(now, week=week, github=GITHUB_ON)
    return dash._rhythm(S, now, [_wf("weekly.yml", *runs)], dash.REPO_ROOT,
                        games=games or Path("/nonexistent/games.csv"))


def test_a_wednesday_game_week_reads_the_morning_report(tmp_path) -> None:
    """Review #13/#19: in a week with a game that Wednesday the report goes
    out from the 8:17 AM ET slot (run/report_slot.py), and Today said it
    "goes out about 5:17 PM ET" about a report already in the inbox."""
    games = tmp_path / "games.csv"
    games.write_text("game_type,gameday,away_team,home_team\nREG,2026-11-25,GB,LA\n"
                     "POST,2026-11-18,X,Y\n", encoding="utf-8")
    assert dash.wednesday_game(date(2026, 11, 25), {}, games)
    assert not dash.wednesday_game(date(2026, 11, 18), {}, games)     # not a regular-season game
    assert not dash.wednesday_game(date(2026, 11, 4), {}, tmp_path / "none.csv")
    # After the morning run, week.json's first kickoff says it too.
    assert dash.wednesday_game(date(2026, 11, 25), {"first_kickoff": "2026-11-26T01:00:00Z"},
                               tmp_path / "none.csv")
    before = {"season": "2026", "week": 11, "phase": "season", "lands_on": "2026-11-25",
              "built_at": "2026-11-18T22:40:00+00:00", "first_kickoff": "2026-11-20T01:15:00Z"}
    row = _wed_rhythm(_utc(2026, 11, 25, 12, 0), before, games=games)
    assert row.title == "Read your own Week 12 report once it lands"
    assert "8:17 AM ET" in row.how and "5:17 PM" not in row.how
    after = {"season": "2026", "week": 12, "phase": "season", "lands_on": "2026-12-02",
             "built_at": "2026-11-25T13:30:00+00:00", "first_kickoff": "2026-11-26T01:00:00Z"}
    green = (_utc(2026, 11, 25, 13, 17), "success")
    row = _wed_rhythm(_utc(2026, 11, 25, 16, 0), after, (green,))
    assert row.title == "Read your own Week 12 report" and "green" in row.how
    # Through today_tasks too, with no schedule file at all.
    S = _today_sources(_utc(2026, 11, 25, 16, 0), week=after, github=GITHUB_ON)
    row = _kinds(dash.today_tasks(S, _utc(2026, 11, 25, 16, 0), {}, [], [_wf("weekly.yml", green)],
                                  None, None), "rhythm")[0]
    assert row.title == "Read your own Week 12 report"
    # An ordinary Wednesday keeps the evening slot.
    row = _wed_rhythm(_utc(2026, 11, 4, 15, 0), {"season": "2026", "week": 8, "phase": "season",
                                                 "lands_on": "2026-11-04"},
                      ((_utc(2026, 11, 4, 13, 17), "success"),), games=games)
    assert "5:17 PM ET" in row.how and "once it lands" in row.title


def test_every_tile_holding_the_owners_activity_says_so() -> None:
    """Review #9: Rosters checked and Buy presses come from the same counter
    TRAFFIC_FROM trims; Refund rate and Waitlist hold the owner's own test
    purchase and form rows until OWNER_EMAILS is set."""
    page = dash.render_page(rich_sources(), NOW, fonts=False, env={})
    for label in ("Rosters checked", "Buy presses"):
        assert _kl(page, label) and all(dash.OWN_VISITS in k for k in _kl(page, label))
    for label in ("Refund rate", "Waitlist"):
        assert _kl(page, label) and all(dash.OWN_TESTS in k for k in _kl(page, label))
    both = dash.render_page(rich_sources(), NOW, fonts=False,
                            env={"OWNER_EMAILS": OWNER_VALUE, "TRAFFIC_FROM": "2026-10-01"})
    for label in ("Rosters checked", "Buy presses", "Refund rate", "Waitlist"):
        assert _kl(both, label) and not any("ownchip" in k for k in _kl(both, label))


def _paid(*days: tuple[int, int], league: int = 0) -> list[dict]:
    """Paid sessions on (month, day) 2026; the last ``league`` are League Passes."""
    out = []
    for k, (mo, dy) in enumerate(days):
        out.append({"id": f"cs_{k}", "created": int(_utc(2026, mo, dy, 15).timestamp()),
                    "paid": True, "status": "complete", "via": None, "amount": 14.99,
                    "pass": "League Pass" if k >= len(days) - league else "Monthly",
                    "refunded": 0.0, "full_refund": False, "dispute": None})
    return out


def _stripe(sessions: list[dict], now: datetime) -> Source:
    return dash._source("stripe", data={"sessions": sessions, "link_map": True,
                                        "dispute_errors": 0}, read_at=now)


def test_a_past_reading_is_frozen_at_its_date() -> None:
    """Review #8: past its read-by date the row counted up to today, so a
    later sale rewrote "when it was read on Nov 18" and could hide the red
    line the gate had crossed on the day."""
    nov25 = _utc(2026, 11, 25, 15, 0)
    sends = {"entries": [{"key": f"trial-2026-{j:012x}", "provider": "resend",
                          "sent_at": ("2026-11-10T15:00:00+00:00" if j < 8 else
                                      "2026-11-21T15:00:00+00:00")} for j in range(12)],
             "season": "2026"}
    S = _today_sources(nov25, stripe=_stripe(_paid((11, 10), (11, 12), (11, 18), (11, 22)), nov25))
    targets = dash.plan_targets(S, nov25, sends, None, S["registry"])
    t = _gate(targets, "free reports")
    assert t["current"] == 8 and t["state"] == "missed" and t["red_now"]
    assert "12 by today" in t["extra"]
    # The 18th counts: the reading is the end of that day, Eastern.
    p = _gate(targets, "paid purchases")
    assert p["current"] == 3 and p["red_now"] and "4 by today" in p["extra"]
    tasks = _kinds(dash.today_tasks({**S, "sends": dash._source(
        "sends", data={**sends, "stopped": 0, "summary": stats.send_summary(sends["entries"], "2026")},
        read_at=nov25)}, nov25, {}, [], [], None, None), "target")
    titles = [t.title for t in tasks]
    assert "Free reports sent (hand-run or self-serve): 8 of 20 when it was read on Nov 18" in titles
    assert "Paid purchases: 3 of 5 when it was read on Nov 18" in titles
    # On its read day nothing is frozen yet: every row it is given counts.
    nov18 = _utc(2026, 11, 18, 15, 0)
    t = _gate(dash.plan_targets(S, nov18, sends, None, S["registry"]), "free reports")
    assert t["current"] == 12 and "by today" not in (t["extra"] or "")
    # Graded rows freeze on when each call was graded.
    dec30 = _utc(2026, 12, 30, 15, 0)
    calls = [{"store": "typed-ppr-12-2026", "week": 10, "confidence": 0.6, "status": "graded",
              "outcome": "hit", "recorded_at": "2026-11-11T22:00:00+00:00",
              "graded_at": ("2026-12-01T13:30:00+00:00" if k < 25 else "2026-12-29T13:30:00+00:00")}
             for k in range(33)]
    S = _today_sources(dec30, ledger=dash._source("ledger", data={"season": "2026", "calls": calls,
                                                                  "unreadable": []}, read_at=dec30))
    g = _gate(dash.plan_targets(S, dec30, None, dash.ledger_view(S["ledger"], dec30), S["registry"]),
              "graded rows")
    assert g["current"] == 25 and g["state"] == "missed" and "33 by today" in g["extra"]


def test_a_green_cell_the_page_cannot_fully_measure_is_never_met() -> None:
    """Review #10: "≥5, ≥2 from outside the owner's own leagues" read as 5,
    and "~30 + 2" as 30 with League Passes counted in."""
    nov11 = _utc(2026, 11, 11, 15, 0)
    S = _today_sources(nov11, stripe=_stripe(_paid(*[(11, 10)] * 5), nov11))
    t = _gate(dash.plan_targets(S, nov11, None, None, S["registry"]), "paid purchases")
    assert t["current"] == 5 and t["state"] == "tracking"
    assert "Not measured here: ≥2 from outside the owner's own leagues" in t["extra"]
    row = next(r for r in dash.gates_html(S, nov11, None, None, S["registry"]).split("<tr>")
               if "Paid purchases" in r)
    assert ">Met<" not in row and ">Tracking<" in row and "Not measured here" in row
    # Without Stripe the row needs the key, and "+ 2" is never an unmeasured part.
    off = _gate(dash.plan_targets(_today_sources(nov11), nov11, None, None,
                                  _today_sources(nov11)["registry"]), "league passes")
    assert off["state"] == "unmeasured" and "Not measured here" not in (off["extra"] or "")
    # Purchases + League Passes: each half against its own number.
    dec23 = _utc(2026, 12, 23, 15, 0)
    for monthly, passes, state, red in ((30, 0, "missed", True), (28, 2, "missed", True),
                                        (30, 2, "met", False)):
        S = _today_sources(dec23, stripe=_stripe(_paid(*[(12, 1)] * (monthly + passes),
                                                       league=passes), dec23))
        c = _gate(dash.plan_targets(S, dec23, None, None, S["registry"]), "league passes")
        assert (c["state"], c["red_now"]) == (state, red), (monthly, passes)
        assert c["cur_text"] == f"{monthly} + {passes}" and c["target_text"] == "30 + 2"
    S = _today_sources(dec23, stripe=_stripe(_paid(*[(12, 1)] * 30), dec23))
    titles = [t.title for t in _kinds(dash.today_tasks(S, dec23, {}, [], [], None, None), "target")]
    assert "Purchases + League Passes: 30 + 0 of 30 + 2 when it was read on Dec 22" in titles
    # The same sales came after Nov 18, so that reading stays what it was.
    assert "Paid purchases: 0 of 5 when it was read on Nov 18" in titles
    # Before the date, short only on passes: behind pace, and the need names passes alone.
    dec1 = _utc(2026, 12, 1, 15, 0)
    S = _today_sources(dec1, stripe=_stripe(_paid(*[(11, 20)] * 30), dec1))
    c = _gate(dash.plan_targets(S, dec1, None, None, S["registry"]), "league passes")
    assert c["state"] == "behind_pace" and c["needed"].endswith("for League Passes")
    assert "for purchases" not in c["needed"] and "straight line" not in c["pace"]
    row = next(t for t in _kinds(dash.today_tasks(S, dec1, {}, [], [], None, None), "target")
               if "League Passes" in t.title)
    assert row.title == "Purchases + League Passes: 30 + 0 of 30 + 2 by Dec 22, behind pace"
    assert row.how.startswith("About 1 every ") and "for League Passes from here" in row.how


def test_each_league_pass_is_judged_on_its_own_fourteen_days(tmp_path) -> None:
    """Review #11: a pass bought today with no seats yet read "Behind"."""
    from run.refs import LEAGUE_PASS, decode_roster
    from run.rosters import RosterSubscriber, to_json
    from test_trials import _fixture_ref
    ref = _fixture_ref()
    spec = decode_roster(ref)

    def sub(email, **kw):
        return RosterSubscriber(email=email, ref=ref, player_ids=tuple(spec.player_ids),
                                slots=tuple(spec.slots), scoring=spec.scoring, **kw)
    rows = [sub("buyer@fans.mail", billing="pass", pass_id="sub_PPPP1", league_size=12,
                subscription_ids=("sub_PPPP1",), origin="aaaaaaaaaa", roster_as_of="2026-11-10"),
            sub("pal@fans.mail", plan=LEAGUE_PASS, covered_by="buyer@fans.mail", pass_id="sub_PPPP1",
                origin="bbbbbbbbbb")]
    path = tmp_path / "rosters.json"
    path.write_text(_json.dumps(to_json(rows)), encoding="utf-8")
    reg = dash.collect_registry(Context(env={}, now=_utc(2026, 11, 10, 15), registry=path))
    assert reg.data["seats"] == [(1, 12)] and reg.data["seats_bought"] == ["2026-11-10"]

    def seats(now: datetime, registry: Source) -> dict:
        S = _today_sources(now, registry=registry)
        return _gate(dash.plan_targets(S, now, None, None, registry), "seats")
    t = seats(_utc(2026, 11, 10, 15), reg)
    assert t["state"] == "tracking" and not t["red_now"] and "read Nov 24" in t["extra"]
    gates = dash.gates_html(_today_sources(_utc(2026, 11, 10, 15), registry=reg),
                            _utc(2026, 11, 10, 15), None, None, reg)
    row = next(r for r in gates.split("<tr>") if "Seats claimed" in r)
    assert ">Behind<" not in row and ">Tracking<" in row
    assert seats(_utc(2026, 11, 24, 15), reg)["state"] == "tracking"     # its own read day
    late = _utc(2026, 11, 25, 15)
    t = seats(late, reg)
    assert t["state"] == "missed" and t["red_now"] and t["when"] == date(2026, 11, 24)
    row = _kinds(dash.today_tasks(_today_sources(late, registry=reg), late, {}, [], [], None, None),
                 "target")[0]
    assert row.title == "Seats claimed: 1 of 12 seats when it was read on Nov 24"
    assert row.how.startswith("PLAN §6 says: Fewer")
    # Half the seats on time is met; a pass with no purchase day stays tracking.
    full = dash._source("registry", data={**reg.data, "seats": [(6, 12)]}, read_at=late)
    assert seats(late, full)["state"] == "met"
    undated = dash._source("registry", data={**reg.data, "seats_bought": [None]}, read_at=late)
    assert seats(late, undated)["state"] == "tracking"


def test_the_bounce_step_ticks_from_the_github_secrets_name() -> None:
    """LAUNCH.md step 2 keeps the Full access Resend key in its GitHub secret
    only, so following it must tick the step: the launch check reads that
    secret's name (never its value). The gate's name is held to the check's."""
    import run.launch_check as lc
    from unittest import mock
    with mock.patch.object(lc, "gh_secret_names", lambda: {"RESEND_READ_KEY"}), \
            mock.patch.dict("os.environ", {"RESEND_READ_KEY": ""}):
        gate = lc.check_resend_read_key()[0]
    assert gate.name == dash.BOUNCE_GATE and gate.status == "PASS"
    S = empty_sources()
    def step6(S):
        return next(s["state"] for s in dash.connect_steps(S, {}) if s["step"].n == 6)
    assert step6(S) == "open"
    S["launch"] = dash._source("launch", data={"gates": [gate.__dict__.copy()]}, read_at=NOW)
    assert step6(S) == "done"
    S["launch"] = dash._source("launch", data={"gates": [{**gate.__dict__, "status": "OWNER"}]},
                               read_at=NOW)
    assert step6(S) == "open"
