"""The owner's own tools, as the Nov 3 2026 sweep found them (area "tools").

`make stats`, the dashboard, `make launch-check`, `make roster-update`,
`make seat-reset`, `make cost` and the LAUNCH.md runbook around them. Each
test names the finding it pins and was mutation-checked: undo the fix it
names and it fails.
"""

from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.dashboard as dash
import run.launch_check as lc
import run.stats as stats
from run.dashboard import Context, Source

ROOT = Path(__file__).resolve().parent.parent
ACCOUNT = "0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_live_keys(monkeypatch):
    """A developer shell may export real keys; nothing here talks to a
    provider unless it installs its own fake."""
    for name in ("STRIPE_API_KEY", "STRIPE_STATS_KEY", "TRAFFIC_FROM", *lc.GATE_ENV):
        monkeypatch.delenv(name, raising=False)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_cf(monkeypatch, data: list[dict] | None = None) -> list[str]:
    """Cloudflare's SQL API, offline: records every query it is sent."""
    import urllib.request
    seen: list[str] = []

    def urlopen(request, timeout=None):
        seen.append(request.data.decode())
        return _Resp(json.dumps({"meta": [], "data": data or []}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return seen


# --------------------------------------------------------------------- #
# TOOLS-1 — the owner's own checks stay out of the traffic
# --------------------------------------------------------------------- #

def test_traffic_from_is_a_strict_utc_time() -> None:
    """It goes into the SQL as text, so nothing but a plain UTC time may."""
    assert stats.parse_traffic_from("") is None and stats.parse_traffic_from(None) is None
    assert stats.parse_traffic_from("2026-11-03T19:00Z") == datetime(2026, 11, 3, 19,
                                                                     tzinfo=timezone.utc)
    assert stats.parse_traffic_from("2026-11-03") == datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert stats.parse_traffic_from("2026-11-03 19:00:30+00:00").second == 30
    for bad in ("yesterday", "2026-11-03T19:00-05:00", "2026-13-01",
                "2026-11-03') OR 1=1 --", "2026-11-03T19:00Z extra"):
        with pytest.raises(ValueError):
            stats.parse_traffic_from(bad)
    assert stats.since_clause(None) == ""
    assert stats.since_clause(stats.parse_traffic_from("2026-11-03T19:00Z")) == \
        " AND timestamp >= toDateTime('2026-11-03 19:00:00')"


def test_make_stats_counts_traffic_only_from_traffic_from(monkeypatch) -> None:
    """TOOLS-1, reproduced on Nov 3: 51 views in 7 days before any launch
    post, every one of them the sweep's own, and Analytics Engine rows can't
    be deleted. Both queries carry the bound, the block says where it counts
    from, and a value that isn't a time counts nothing rather than everything."""
    seen = _fake_cf(monkeypatch)
    lines = stats.traffic_summary(ACCOUNT, "tok", "https://forms.example/e", "2026-11-03T19:00Z")
    assert len(seen) == 2
    assert all("AND timestamp >= toDateTime('2026-11-03 19:00:00')" in sql for sql in seen)
    assert "Counting from Nov 3 19:00 UTC (TRAFFIC_FROM)" in lines[0]
    seen.clear()
    stats.traffic_summary(ACCOUNT, "tok", "https://forms.example/e")
    assert seen and not any("toDateTime" in sql for sql in seen)
    seen.clear()
    [line] = stats.traffic_summary(ACCOUNT, "tok", "https://forms.example/e", "Nov 3")
    assert "TRAFFIC_FROM is not an ISO UTC time" in line and not seen


def test_the_command_line_reads_traffic_from_from_dotenv(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("TRAFFIC_FROM=2026-11-03T19:00Z\n", encoding="utf-8")
    handed = {}
    monkeypatch.setattr(stats, "main", lambda argv=None, cf=None, **kw: handed.update(cf) or 0)
    assert stats.cli([], environ={}, env_file=env) == 0
    assert handed["TRAFFIC_FROM"] == "2026-11-03T19:00Z"


def test_the_dashboard_counts_no_view_from_before_traffic_from(monkeypatch) -> None:
    """The dashboard reads the same bound: its three totals and its daily
    series are queried from it, and a day before it never reaches a chart
    (a row older than TRAFFIC_FROM is not counted)."""
    asked = []
    monkeypatch.setattr(stats, "counter_endpoint", lambda path=None: "https://forms.example/e")
    monkeypatch.setattr(stats, "query_counts",
                        lambda a, t, days, since=None: asked.append(since) or [])
    old = {"day": "2026-11-02", "e": "view", "p": "index", "s": "", "v": "", "n": 40}
    new = {"day": "2026-11-03", "e": "view", "p": "index", "s": "", "v": "", "n": 3}
    monkeypatch.setattr(dash, "query_daily",
                        lambda a, t, days, since=None: asked.append(since) or [old, new])
    env = {"CF_ACCOUNT_ID": ACCOUNT, "CF_ANALYTICS_TOKEN": "tok",
           "TRAFFIC_FROM": "2026-11-03T19:00Z"}
    src = dash.collect_traffic(Context(env=env, now=NOW))
    bound = datetime(2026, 11, 3, 19, tzinfo=timezone.utc)
    assert asked == [bound] * 4
    assert src.data["daily"] == [new]
    metrics = dash.traffic_metrics(src, "7d", NOW)
    assert sum(metrics["chart"]) == 3
    assert "TRAFFIC_FROM" in dash.ENV_NAMES
    import test_dashboard as td
    sources = td.rich_sources(NOW)
    sources["traffic"] = src
    page = dash.render_page(sources, NOW, fonts=False)
    assert "Counting from Nov 3 19:00 UTC (TRAFFIC_FROM)" in page


def test_the_dashboards_daily_query_carries_the_bound(monkeypatch) -> None:
    seen = _fake_cf(monkeypatch)
    dash.query_daily(ACCOUNT, "tok", 90, since=datetime(2026, 11, 3, 19, tzinfo=timezone.utc))
    assert "AND timestamp >= toDateTime('2026-11-03 19:00:00')" in seen[0]
    dash.query_daily(ACCOUNT, "tok", 90)
    assert "toDateTime" not in seen[1]


# --------------------------------------------------------------------- #
# TOOLS-2 — a test row is not a person on the list
# --------------------------------------------------------------------- #

ROWS = [
    {"kind": "waitlist", "email": "owner@beatyourleague.com", "received_at": "2026-11-02T05:02:58Z"},
    {"kind": "waitlist", "email": "a@example.com", "received_at": "2026-11-02T06:00:00Z",
     "via": "reddit"},
    {"kind": "waitlist", "email": "b@shop.test", "received_at": "2026-11-02T06:00:00Z"},
    {"kind": "waitlist", "email": "fan@fans.mail", "received_at": "2026-11-02T07:00:00Z",
     "via": "x"},
    {"kind": "trial", "email": "c@mail.example.org", "ref": "r",
     "received_at": "2026-11-02T07:00:00Z"},
]


def test_our_own_domain_and_the_reserved_ones_are_test_addresses() -> None:
    from run.trials import count_test_rows, is_test_address
    for address in ("owner@beatyourleague.com", "x@forms.beatyourleague.com", "a@example.com",
                    "A@EXAMPLE.NET", "b@example.org", "c@x.test", "d@y.example", "e@z.invalid",
                    "f@host.localhost"):
        assert is_test_address(address), address
    for address in ("fan@gmail.com", "x@notexample.com", "y@example.co", "z@beatyourleague.co",
                    "", None, "not an address", "test@fans.mail"):
        assert not is_test_address(address), address
    assert count_test_rows(ROWS) == 4


def test_make_stats_leaves_test_rows_out_of_every_count_and_says_so(
        tmp_path, monkeypatch, capsys) -> None:
    """TOOLS-2, reproduced: the Worker's one row was the business's own
    address, and stats printed "Waitlist sign-ups 1 … people 1": the demand
    count was wrong by 100%."""
    form = stats.form_summary(ROWS, NOW)
    assert form["waitlist"]["total"] == 1 and form["waitlist"]["people"] == 1
    assert "trial" not in form
    assert stats.channel_summary(ROWS) == {"waitlist": {"x": 1}}
    assert stats.conversions(ROWS, ["fan@fans.mail", "a@example.com"]) == {"waitlist": (1, 1)}
    import run.delivery as delivery
    import run.intake as intake
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: ROWS)
    assert stats.main(["--registry", str(tmp_path / "none.json"), "--now", NOW.isoformat()],
                      form={"FORM_ENDPOINT": "https://w.test"}) == 0
    out = capsys.readouterr().out
    assert "4 test rows from our own domain or a reserved test domain, not counted." in out
    assert "@" not in out


def test_the_dashboard_leaves_test_rows_out_and_says_so(monkeypatch) -> None:
    import run.intake as intake
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: ROWS)
    src = dash.collect_forms(Context(env={"FORM_ENDPOINT": "https://w.test"}, now=NOW))
    assert [r["kind"] for r in src.data["rows"]] == ["waitlist"]
    assert src.data["left_out"] == 4
    assert dash.forms_metrics(src, "7d", NOW)["waitlist"]["people"] == 1
    import test_dashboard as td
    sources = td.rich_sources(NOW)
    sources["forms"] = src
    page = dash.render_page(sources, NOW, fonts=False)
    assert "4 test rows from our own domain or a reserved test domain, not counted." in page


def test_the_launch_email_never_goes_to_a_test_row(tmp_path, capsys) -> None:
    import run.waitlist as wl
    assert wl.waitlist_addresses(ROWS) == ["fan@fans.mail"]
    export = tmp_path / "list.csv"
    export.write_text("email\nowner@beatyourleague.com\nfan@fans.mail\n", encoding="utf-8")
    addresses, problems = wl.load_list(export)
    assert addresses == ["fan@fans.mail"]
    assert problems == ["row 2: a test row from our own domain or a reserved test domain"]


# --------------------------------------------------------------------- #
# TOOLS-4 — make launch-check reads .env for its config gates, and only them
# --------------------------------------------------------------------- #

def test_the_launch_check_reads_dotenv_for_config_gates_but_never_for_a_simulation(
        tmp_path, monkeypatch) -> None:
    """TOOLS-4, reproduced: from a plain Terminal the site/Worker TRIAL_OPEN
    gate said SKIP ("needs FORM_ENDPOINT and FORM_API_KEY in the shell")
    while the dashboard, reading .env, ran it. The config gates now see .env;
    the proving run's environment never does, because _simulation_env copies
    os.environ into its subprocesses and the real Worker must not reach one."""
    env = tmp_path / ".env"
    env.write_text("FORM_ENDPOINT=https://w.file/rows\nFORM_API_KEY=file-key\n",
                   encoding="utf-8")
    monkeypatch.setattr(stats, "ENV_FILE", env)
    asked = []
    monkeypatch.setattr(lc, "worker_status",
                        lambda endpoint, key: asked.append((endpoint, key)) or {"trial_open": False})
    for name in [n for n in dir(lc) if n.startswith("check_")]:
        if name != "check_worker_switches":
            monkeypatch.setattr(lc, name, lambda: [])
    simulated = {}

    def check_proving():
        simulated.update(lc._simulation_env())
        return []
    monkeypatch.setattr(lc, "check_proving", check_proving)
    gates = lc.run_all(fast=False, offline=False, progress=lambda label: None)
    assert asked == [("https://w.file/rows", "file-key")]
    [gate] = [g for g in gates if g.name.startswith("The form Worker takes")]
    assert gate.status == "PASS"
    assert "FORM_ENDPOINT" not in simulated and "FORM_API_KEY" not in simulated
    assert "FORM_ENDPOINT" not in os.environ, "nothing outlives the gates' run"


def test_the_shell_still_wins_over_dotenv(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("FORM_ENDPOINT=https://w.file/rows\n", encoding="utf-8")
    monkeypatch.setattr(stats, "ENV_FILE", env)
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.shell/rows")
    with lc.filled_env():
        assert os.environ["FORM_ENDPOINT"] == "https://w.shell/rows"
    assert dash.GATE_ENV is lc.GATE_ENV


# --------------------------------------------------------------------- #
# TOOLS-6 — make stats finds the Stripe key where the dashboard does
# --------------------------------------------------------------------- #

def test_make_stats_reads_the_stripe_key_from_dotenv_in_the_dashboards_order(
        tmp_path, monkeypatch) -> None:
    """TOOLS-6, reproduced: `make stats` printed "STRIPE_API_KEY is not set in
    this shell — no payment view" while the dashboard, the same minute, read
    STRIPE_STATS_KEY from .env."""
    keys = []
    monkeypatch.setattr(stats, "main", lambda argv=None, cf=None, form=None, stripe_key=None:
                        keys.append(stripe_key) or 0)
    env = tmp_path / ".env"
    env.write_text("STRIPE_API_KEY=rk_test_api\n", encoding="utf-8")
    stats.cli([], environ={}, env_file=env)
    env.write_text("STRIPE_API_KEY=rk_test_api\nSTRIPE_STATS_KEY=rk_test_stats\n",
                   encoding="utf-8")
    stats.cli([], environ={}, env_file=env)
    stats.cli([], environ={"STRIPE_API_KEY": "rk_test_shell"}, env_file=env)
    stats.cli([], environ={"STRIPE_STATS_KEY": "rk_test_shell_stats"}, env_file=env)
    assert keys == ["rk_test_api", "rk_test_stats", "rk_test_stats", "rk_test_shell_stats"]
    assert [dash.stripe_key(e) for e in ({"STRIPE_API_KEY": "a"},
                                         {"STRIPE_API_KEY": "a", "STRIPE_STATS_KEY": "s"})] == \
        ["a", "s"]


def test_main_uses_the_key_it_is_handed(tmp_path, monkeypatch, capsys) -> None:
    import run.delivery as delivery
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    used = []
    monkeypatch.setattr(stats, "stripe_summary", lambda key, *a, **k: used.append(key) or [])
    argv = ["--registry", str(tmp_path / "none.json"), "--now", NOW.isoformat()]
    assert stats.main(argv, stripe_key="rk_test_handed") == 0
    assert used == ["rk_test_handed"]
    assert stats.main(argv, stripe_key="") == 0
    assert "not set in this shell or .env" in capsys.readouterr().out


# --------------------------------------------------------------------- #
# TOOLS-11 — a monthly League Pass is reset by its subscription
# --------------------------------------------------------------------- #

def test_a_seat_reset_refuses_a_payment_id_unless_the_pass_was_one_time(
        tmp_path, capsys) -> None:
    """TOOLS-11: LAUNCH said "its id starts pi_", but the monthly League Pass
    is named by its subscription (sub_…), so a pi_ recorded a reset matching
    no pass and the old seat link kept working."""
    from run import seat_resets
    path = tmp_path / "seat-resets.txt"
    with pytest.raises(ValueError, match=r"subscription \(sub_…\)"):
        seat_resets.add_reset("pi_3Pabc123", path=path)
    assert not path.exists()
    assert seat_resets.main(["pi_3Pabc123", "--file", str(path)]) == 2
    assert "sub_" in capsys.readouterr().err and not path.exists()
    assert seat_resets.main(["pi_3Pabc123", "--one-time", "--file", str(path)]) == 0
    assert seat_resets.main(["sub_1Pabc123", "--file", str(path)]) == 0
    assert len(seat_resets.load_resets(path)) == 2
    launch = (ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "PASS=sub_" in launch and "PASS=pi_" not in launch
    assert "PASS=sub_" in makefile and "PASS=pi_" not in makefile


# --------------------------------------------------------------------- #
# TOOLS-12 — a late run from before the Worker's trigger is history
# --------------------------------------------------------------------- #

def _runs(*rows: tuple[str, str]) -> list[dict]:
    return [{"created_at": at, "status": "completed", "conclusion": "success", "event": event,
             "url": f"https://github.com/{dash.GITHUB_REPO}/actions/runs/{k}"}
            for k, (at, event) in enumerate(rows)]


def _late_titles(daily: list[dict]) -> list[tuple[str, object]]:
    import test_dashboard as td
    now = datetime(2026, 11, 3, 16, 30, tzinfo=timezone.utc)
    src = dash._source("github", data={
        "saturday.yml": {"label": "Saturday final check",
                         "runs": _runs(("2026-10-31T20:03:00Z", "schedule"))},
        "daily.yml": {"label": "Daily intake", "runs": daily}}, read_at=now)
    health = dash.workflow_health(src, now)
    S = td.rich_sources(now)
    issues = dash.build_issues(S, now, health, None, dash.metrics_for(S, "7d", now))
    return [(i.title, i.fix) for i in issues if "minutes after its slot" in i.title]


def test_a_late_run_before_the_workers_trigger_does_not_ask_for_the_trigger() -> None:
    """TOOLS-12, reproduced: Saturday's Oct 31 run started 226 minutes late,
    on GitHub's own schedule, while from Nov 2 the Worker dispatched daily
    and monday on time; the issue still said "Set the Worker's Cron Trigger"."""
    on_time = _runs(("2026-11-03T15:47:09Z", "workflow_dispatch"),
                    ("2026-11-03T14:17:08Z", "workflow_dispatch"))
    [(title, fix)] = _late_titles(on_time)
    assert "226 minutes" in title and "before the Worker's trigger was on" in title
    assert "clears after the next on-time run" in fix
    # No on-time dispatch after it (a hand-pressed one at :30 isn't the
    # Worker): the trigger really may be off.
    for daily in ([], _runs(("2026-11-03T15:30:00Z", "workflow_dispatch")),
                  _runs(("2026-10-30T14:17:08Z", "workflow_dispatch"))):
        [(title, fix)] = _late_titles(daily)
        assert "before the Worker" not in title and fix == "Set the Worker's Cron Trigger so it starts on time."


# --------------------------------------------------------------------- #
# TOOLS-13, 14, 15 — what the dashboard's words say
# --------------------------------------------------------------------- #

def test_channel_views_say_which_views_they_count() -> None:
    """TOOLS-13: the column counts landing and buy-page views only, while
    Traffic → Channels counts every view; both said "Views"."""
    rows = [{"e": "view", "p": "index", "v": "", "r": "", "d": "m", "s": "", "c": "US", "n": 7}]
    assert any("landing + buy-page views → rosters → buy presses" in line
               for line in stats.traffic_lines(rows, rows))
    source = (ROOT / "run" / "dashboard.py").read_text(encoding="utf-8")
    assert '<th class="r">Landing + buy-page views</th>' in source


def test_a_long_detail_is_never_cut_mid_name(monkeypatch) -> None:
    """TOOLS-14: with gh signed out the secrets gate lists all 13 names, and
    `[:240]` cut the list in the middle of one of the names to check by hand."""
    monkeypatch.setattr(lc.shutil, "which", lambda name: None)
    [gate] = [g for g in lc.check_secrets() if g.name == "GitHub Actions secrets are set"]
    assert len(gate.detail) > 240
    import test_dashboard as td
    S = td.rich_sources(NOW)
    S["launch"] = dash._source("launch", data={"gates": [gate.__dict__.copy()]}, read_at=NOW)
    [issue] = [i for i in dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
               if "waiting on you" in i.title]
    step = issue.fix[1]
    assert len(step) <= 240 and step.endswith("… (full list: make launch-check)")
    listed = step.split(": ", 1)[1].split("…", 1)[0].split(", ")
    assert listed and all(name in lc.REQUIRED_SECRETS for name in listed), listed
    assert dash.clip("short") == "short"
    assert dash.clip("word " * 100).endswith("word… (full list: make launch-check)")


def test_the_quick_checks_never_read_as_the_whole_list_and_link_a_real_section() -> None:
    """TOOLS-15: the page runs 15 quick gates and said "N launch steps are
    waiting on you", and it pointed at LAUNCH's dead "This weekend" list."""
    gates = [{"area": "Owner", "name": f"Step {k}", "status": "OWNER", "detail": "set it"}
             for k in range(3)]
    import test_dashboard as td
    S = td.rich_sources(NOW)
    S["launch"] = dash._source("launch", data={"gates": gates}, read_at=NOW)
    [issue] = [i for i in dash.build_issues(S, NOW, [], None, dash.metrics_for(S, "7d", NOW))
               if "waiting on you" in i.title]
    assert issue.title == "3 of the quick launch checks are waiting on you."
    assert "The full check (make launch-check) covers DNS, Stripe and the accounts too." \
        in issue.fix[-1]
    launch = (ROOT / "LAUNCH.md").read_text(encoding="utf-8")

    def slug(heading: str) -> str:
        text = heading.strip().lower()
        return "".join(ch for ch in text if ch.isalnum() or ch in " -_").replace(" ", "-")
    anchors = {slug(h) for h in re.findall(r"(?m)^#{1,4} (.+)$", launch)}
    for label, url in dash.LAUNCH_REFS.values():
        assert url.split("#", 1)[1] in anchors, (label, url)
    assert dash.LAUNCH_REFS[issue.ref][1].endswith("#now-in-order-nov-3")


# --------------------------------------------------------------------- #
# TOOLS-20 — the books are in US dollars and never hold Stripe's fees
# --------------------------------------------------------------------- #

def test_make_cost_says_its_currency_and_to_leave_stripes_fees_out(tmp_path, capsys) -> None:
    import run.books as books
    assert books.cli(["cost", "Domain", "12"], root=tmp_path) == 0
    out = capsys.readouterr().out
    assert "Amounts in US dollars. Stripe's fees are already taken out of net revenue, " \
           "so don't log them here." in out
    with pytest.raises(SystemExit):
        books.cli(["cost", "--help"], root=tmp_path)
    assert "US dollars" in capsys.readouterr().out
    assert books.cli(["link", "x-nov3", "--page", "byes"], root=tmp_path) == 0
    assert "https://beatyourleague.com/byes/?via=x-nov3" in capsys.readouterr().out
    assert "Stripe's fees are already taken out of net revenue" in \
        (ROOT / "LAUNCH.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------- #
# TOOLS-7, 9, 18 — LAUNCH.md says what the code does
# --------------------------------------------------------------------- #

def _launch_section(prefix: str) -> str:
    text = (ROOT / "LAUNCH.md").read_text(encoding="utf-8")
    start = text.index(f"\n## {prefix}")
    end = text.find("\n## ", start + 1)
    return re.sub(r"\s+", " ", text[start:end])


def test_the_weekly_table_matches_the_crons() -> None:
    """TOOLS-7, reproduced on Nov 3: the table said "ET until Nov 1", mixed
    EST and EDT rows, gave the retired Tuesday crons as the UTC times, and
    named the retired 12:17pm retry."""
    section = _launch_section("8. Every week")
    assert "ET until Nov 1" not in section and "12:17pm" not in section
    assert "Tue 12:17" not in section and "an hour earlier" not in section
    utc = section.split("UTC: ", 1)[1].split("The Worker", 1)[0]
    for workflow in ("weekly.yml", "daily.yml", "saturday.yml", "monday.yml"):
        for cron in lc.workflow_crons(workflow):
            minute, hour = cron.split()[:2]
            stamp = f"{minute}" if hour == "*" else f"{int(hour):02d}:{int(minute):02d}"
            assert stamp in utc, (workflow, cron)
            if hour != "*":
                et = (int(hour) - 5) % 24       # EST, from Nov 1 to March
                clock = f"{(et - 1) % 12 + 1}:{int(minute):02d}{'am' if et < 12 else 'pm'}"
                assert clock in section, (workflow, cron, clock)


def test_free_weeks_are_built_once_mondays_game_is_in() -> None:
    """TOOLS-9: run.trial builds through load_week_data, which refuses while
    Monday night's game has no box score; LAUNCH said to build them from
    Monday night and that before the game it built anyway."""
    item = _launch_section("7. Selling").split(" 2. ", 1)[1].split(" 3. ", 1)[0]
    assert "from Tuesday morning" in item and "try again in an hour" in item
    assert "Monday night to" not in item and "builds from a week that isn't finished" not in item
    assert "Oct 27" not in item


def test_opening_writes_d_in_the_same_push() -> None:
    """TOOLS-18: step 6 never mentioned D, so the owner's own test purchase
    and its refund counted in PLAN §6's gates."""
    item = _launch_section("6. Opening morning").split(" 1. ", 1)[1].split(" 2. ", 1)[0]
    assert "CHECKOUT_CAN_COMPLETE" in item and "same push" in item
    assert "D in PLAN §6" in item and "step-4 purchase" in item
    assert "step 6.1" in _launch_section("10. Decisions")
