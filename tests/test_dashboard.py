"""`make dashboard` — the owner's private page (run/dashboard.py).

Every source is faked here; nothing touches the network. The properties that
matter are the ones a public repository and a pasted screenshot can hurt:
it never runs in CI, it writes only to a gitignored path, it never carries an
address or a secret, it loads nothing from anywhere, and one source failing
or missing never takes the page down.
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.dashboard as dash
import run.stats as stats
from run.dashboard import Context, Source

NOW = datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
LEAK = "leak.me+tag@example.com"
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
VIAS = (("", 52), ("reddit", 18), ("x", 12), ("discord", 9), ("groupchat", 6), ("newsletter", 3))
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
        key = (e["day"], e["e"], e["p"], e["s"])
        agg[key] = agg.get(key, 0) + 1
    return [{"day": d, "e": e, "p": p, "s": s, "n": n} for (d, e, p, s), n in agg.items()]


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
                    "via": _pick(rng, (("reddit", 5), ("x", 3), ("discord", 2), ("groupchat", 2),
                                       (None, 6))),
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
                           "via": None, "who": f"w{i:03d}" if i < 5 else f"t{i}"})
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
    tue = now - timedelta(days=(now.weekday() - 1) % 7)
    tue_run = tue.replace(hour=12, minute=31)
    github = {
        "weekly.yml": {"label": "Tuesday reports", "runs": [
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
    plan_text = (root / "PLAN.md").read_text(encoding="utf-8").replace(
        "D = ____", "D = 2026-10-26")
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
        "plan": dash._source("plan", data=dash.parse_plan_gates(plan_text), read_at=now),
    }
    return S


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
    assert page.count('class="kpi off"') == 7 * len(dash.PERIODS)


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
    monkeypatch.setattr(stats, "query_counts", lambda a, t, days: aggregate(ev, NOW, days))
    monkeypatch.setattr(dash, "query_daily", lambda a, t, days: daily(ev))
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
    assert "@example.com" not in page and "@gmail.com" not in page
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
    got = dash.free_to_paid(S["forms"], S["stripe"], NOW)
    assert got is not None and got[1] + got[2] == 38


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
    assert any("Tuesday reports didn't run" in t for t in titles)
    assert any("The last tests run failed" in t for t in titles)


def test_an_on_time_tuesday_is_not_a_missed_slot() -> None:
    S = rich_sources()
    weekly = next(w for w in dash.workflow_health(S["github"], NOW) if w["file"] == "weekly.yml")
    assert not weekly["missing"]


def test_refund_rate_over_plans_red_line_is_an_issue() -> None:
    S = rich_sources()
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
