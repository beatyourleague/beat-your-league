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
    assert "git pull" in hit[0].fix[0] and "only before the week's first kickoff" in hit[0].fix[1]
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


def test_connect_steps_are_named_in_order_and_carry_no_values() -> None:
    S = empty_sources()
    steps = dash.connect_steps(S, set())
    assert [s[0] for s in steps] == ["owner_emails", "stripe", "traffic_from", "costs", "log_secret",
                                     "resend", "registry"]
    assert all(len(s) == 5 and isinstance(s[1], bool) and isinstance(s[3], int) for s in steps)
    assert not any(done for _i, done, *_ in steps)
    S["stripe"] = dash._source("stripe", data={"sessions": []}, read_at=NOW)
    names = {"TRAFFIC_FROM", "LOG_SECRET"}
    done = {i: d for i, d, *_ in dash.connect_steps(S, names)}
    # Stripe read without OWNER_EMAILS would count the owner's test sale.
    assert done["traffic_from"] and done["log_secret"] and not done["stripe"]
    stripe_how = next(s[4] for s in dash.connect_steps(S, names) if s[0] == "stripe")
    assert "OWNER_EMAILS first" in stripe_how
    done = {i: d for i, d, *_ in dash.connect_steps(S, names | {"OWNER_EMAILS"})}
    assert done["owner_emails"] and done["stripe"]
    S["books"] = dash._source("books", data=books_fixture(), read_at=NOW)
    S["registry"] = rich_sources()["registry"]
    done = {i: d for i, d, *_ in dash.connect_steps(S, set())}
    assert done["costs"] and done["registry"]


def test_the_optional_step_never_reaches_today() -> None:
    names = {"OWNER_EMAILS", "TRAFFIC_FROM", "LOG_SECRET"}
    S = _today_sources(stripe=dash._source("stripe", data={"sessions": []}, read_at=WED),
                       books=dash._source("books", data=books_fixture(), read_at=WED))
    tasks = dash.today_tasks(S, WED, names, [], [], None, None)
    assert [t.id for t in _kinds(tasks, "connect")] == ["registry"]


def test_today_runs_in_its_fixed_order_and_folds_the_rest_into_later() -> None:
    issues = [_issue("critical", "Somebody paid and can't be served."),
              _issue("high", "The last hourly intake run failed."),
              _issue("high", "Two emails bounced."),
              _issue("medium", "A medium thing.")]
    tasks = dash.today_tasks(_today_sources(), WED, set(), issues, [], None, None)
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
    tasks = dash.today_tasks(_today_sources(), WED, set(), [], [], None, None)
    rhythm = _kinds(tasks, "rhythm")[0]
    assert rhythm.state == "unknown" and "Can't tell until GitHub" in rhythm.how
    assert rhythm.title == "Read your own Week 9 report once it lands"
    assert "Can't tell yet" in dash.today_html(tasks)
    assert "Overdue" not in dash.today_html(tasks)


def test_the_wednesday_report_row_follows_github_run_state() -> None:
    S = _today_sources(github=GITHUB_ON)
    week_ago = _wf("weekly.yml", (WED - timedelta(days=7), "success"))
    row = _kinds(dash.today_tasks(S, WED, set(), [], [week_ago], None, None), "rhythm")[0]
    assert row.state == "open" and "once it lands" in row.title and "5:17 PM ET" in row.how
    evening = _utc(2026, 11, 4, 23, 0)
    sent = _wf("weekly.yml", (_utc(2026, 11, 4, 22, 18), "success"))
    row = _kinds(dash.today_tasks(S, evening, set(), [], [sent], None, None), "rhythm")[0]
    assert row.title == "Read your own Week 9 report" and "green" in row.how
    red = _wf("weekly.yml", (_utc(2026, 11, 4, 22, 18), "failure"))
    assert not _kinds(dash.today_tasks(S, evening, set(), [], [red], None, None), "rhythm")
    # Once the evening run rebuilt week.json, the week it names is the one sent.
    S2 = _today_sources(github=GITHUB_ON, week={"season": "2026", "week": 9, "phase": "season",
                                                "lands_on": "2026-11-11",
                                                "built_at": "2026-11-04T22:40:00+00:00"})
    row = _kinds(dash.today_tasks(S2, evening, set(), [], [sent], None, None), "rhythm")[0]
    assert row.title == "Read your own Week 9 report"


def test_saturday_and_monday_rows_and_no_row_on_other_days() -> None:
    sat = _utc(2026, 11, 7, 14, 0)                     # 9 AM ET, before 11:17
    S = _today_sources(sat, github=GITHUB_ON)
    row = _kinds(dash.today_tasks(S, sat, set(), [], [_wf("saturday.yml")], None, None), "rhythm")[0]
    assert "Saturday" in row.title and "11:17 AM ET" in row.how and "unless it goes red" in row.how
    later = _utc(2026, 11, 7, 18, 0)
    green = _wf("saturday.yml", (_utc(2026, 11, 7, 16, 18), "success"))
    assert not _kinds(dash.today_tasks(S, later, set(), [], [green], None, None), "rhythm")
    going = _wf("saturday.yml", (_utc(2026, 11, 7, 16, 18), ""))
    row = _kinds(dash.today_tasks(S, later, set(), [], [going], None, None), "rhythm")[0]
    assert row.how == "It's running now."
    row = _kinds(dash.today_tasks(S, later, set(), [], [_wf("saturday.yml")], None, None), "rhythm")[0]
    assert "hasn't started" in row.how and "missed" not in row.how.lower()
    mon = _utc(2026, 11, 9, 15, 0)
    row = _kinds(dash.today_tasks(_today_sources(mon), mon, set(), [], [], None, None), "rhythm")[0]
    assert "Monday" in row.title and row.state == "unknown"
    tue = _utc(2026, 11, 10, 15, 0)
    assert not _kinds(dash.today_tasks(_today_sources(tue, github=GITHUB_ON), tue, set(), [], [],
                                       None, None), "rhythm")


def test_a_missed_monday_grading_leads_only_while_calls_wait() -> None:
    wf = {**_wf("monday.yml"), "missing": True, "slot": _utc(2026, 11, 3, 13, 17)}
    tasks = dash.today_tasks(_today_sources(), WED, set(), [], [wf], {"pending": 3, "graded": 0}, None)
    assert tasks[0].kind == "risk" and "3 calls wait to be graded" in tasks[0].title
    assert "Tue 8:17 AM ET" in tasks[0].title and "monday-receipts" in tasks[0].how
    tasks = dash.today_tasks(_today_sources(), WED, set(), [], [wf], {"pending": 0, "graded": 4}, None)
    assert not _kinds(tasks, "risk")


def _secrets_gate(status: str, detail: str) -> Source:
    return dash._source("launch", data={"gates": [{"area": "Owner", "status": status, "detail": detail,
                                                   "name": "GitHub Actions secrets are set"}]},
                        read_at=WED)


def test_deadlines_show_inside_14_days_and_never_overdue_when_unknown() -> None:
    assert not _kinds(dash.today_tasks(_today_sources(), WED, set(), [], [], None, None), "deadline")
    dec30 = _utc(2026, 12, 30, 15, 0)
    missing = _secrets_gate("OWNER", "missing: SENDER_POSTAL_ADDRESS — the sender line is off")
    rows = _kinds(dash.today_tasks(_today_sources(dec30, launch=missing), dec30, set(), [], [],
                                   None, None), "deadline")
    assert [t.id for t in rows] == ["owned_list", "sender_address"]
    assert rows[1].title == "Set SENDER_POSTAL_ADDRESS by Jan 11" and rows[1].state == "open"
    present = _secrets_gate("PASS", "all 9 present")
    assert [t.id for t in _kinds(dash.today_tasks(_today_sources(dec30, launch=present), dec30, set(),
                                                  [], [], None, None), "deadline")] == ["owned_list"]
    other = _secrets_gate("OWNER", "missing: CACHE_KEY — the cache is off")
    assert [t.id for t in _kinds(dash.today_tasks(_today_sources(dec30, launch=other), dec30, set(),
                                                  [], [], None, None), "deadline")] == ["owned_list"]
    cant = _secrets_gate("OWNER", "can't read them from this machine (gh not signed in)")
    row = next(t for t in dash.today_tasks(_today_sources(dec30, launch=cant), dec30, set(), [], [],
                                           None, None) if t.id == "sender_address")
    assert row.state == "unknown" and "gh auth login" in row.how
    jan12 = _utc(2027, 1, 12, 15, 0)
    over = _kinds(dash.today_tasks(_today_sources(jan12, launch=missing), jan12, set(), [], [],
                                   None, None), "deadline")
    assert [t.state for t in over] == ["overdue"] and "it was due Jan 11" in over[0].title
    # Unknown, or a decision only the owner knows: never overdue.
    assert not _kinds(dash.today_tasks(_today_sources(jan12), jan12, set(), [], [], None, None),
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
    row = _kinds(dash.today_tasks(S, thu, set(), [], [], None, drafts), "selling")[0]
    assert row.minutes == SELLING_MIN_PER_DAY and "“The closest call”" in row.how
    row = _kinds(dash.today_tasks(S, thu, set(), [], [], None, drafts.replace("Week 9", "Week 8")),
                 "selling")[0]
    assert "Week 8's" in row.how and "replies" in row.how
    # On the next report's day the drafts are last week's, whatever they say.
    wed = _utc(2026, 11, 11, 15, 0)
    row = _kinds(dash.today_tasks(S, wed, set(), [], [], None, drafts), "selling")[0]
    assert "Week 9's" in row.how
    row = _kinds(dash.today_tasks(S, thu, set(), [], [], None, None), "selling")[0]
    assert "No drafts" in row.how
    over = _today_sources(thu, week={**week, "phase": "over"})
    assert not [t for t in dash.today_tasks(over, thu, set(), [], [], None, drafts)
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
    tasks = dash.today_tasks(S, nov11, set(), [], [], None, None)
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
    assert not _kinds(dash.today_tasks(S, nov11, set(), [], [], None, None), "target")


def test_past_its_date_and_red_shows_plans_own_words() -> None:
    nov20 = _utc(2026, 11, 20, 15, 0)
    S = _today_sources(nov20, sends=_trial_sends(5))
    red = _gate(S["plan"].data["gates"], "free reports")["red"]
    assert "the selling hours aren't happening" in red      # PLAN.md's own words
    t = _gate(dash.plan_targets(S, nov20, S["sends"].data, None, S["registry"]), "free reports")
    assert t["state"] == "missed" and t["red_now"]
    gates = dash.gates_html(S, nov20, S["sends"].data, None, S["registry"])
    assert "PLAN §6 says:" in gates and dash.h(red) in gates and "Missed" in gates
    row = _kinds(dash.today_tasks(S, nov20, set(), [], [], None, None), "target")[0]
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
    assert "Needs STRIPE_STATS_KEY in .env" in gates and "Needs the send log (git pull)" in gates
    assert "Needs the registry (make dashboard-registry)" in gates
    assert "Needs the public record (git pull)" in gates
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
