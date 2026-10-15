"""The schedule itself: who starts the crons, and who notices when one never ran.

GitHub's scheduler is best-effort. It started the Tuesday runs 5-7 hours late
on Oct 6 and Oct 13 2026 and dropped most of the hourly ones, so "Tuesday
morning" and "within the hour" were promises nothing kept. Three things answer
that, and each is pinned here:

- **The form Worker fires the workflows itself** (infra/form-worker.js,
  `scheduled()`), through workflow_dispatch, at the times the workflows' own
  `schedule:` blocks name. Tested by RUNNING the Worker under node for a whole
  week of half-hour ticks and comparing what it dispatched with what the YAML
  crons say — not by reading its source — and by evaluating daily.yml's
  once-a-day gate against the inputs the Worker actually sends.
- **A double trigger stays safe**: queued runs check out the branch tip.
- **A run that never happened turns red** (run/watchdog.py), because a run
  that never starts fails nothing and so files nothing.

The Worker tests need node and skip without it; CI installs it.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.watchdog as watchdog

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "infra" / "form-worker.js"
WORKFLOWS = ROOT / ".github" / "workflows"
SCHEDULED = ("weekly.yml", "daily.yml", "saturday.yml", "monday.yml")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not available")
WEEK_START = datetime(2026, 10, 12, tzinfo=timezone.utc)      # a Monday


def _yaml(name: str) -> dict:
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _crons(name: str) -> list[str]:
    doc = _yaml(name)
    triggers = doc.get("on") or doc.get(True)      # `on` parses as True in YAML 1.1
    return [entry["cron"] for entry in triggers.get("schedule") or []]


def _matches(cron: str, at: datetime) -> bool:
    """The same five-field subset the Worker implements: numbers, lists, *."""
    values = (at.minute, at.hour, at.day, at.month, (at.weekday() + 1) % 7)
    return all(field == "*" or value in {int(p) for p in field.split(",")}
               for field, value in zip(cron.split(), values))


def _node(tmp_path: Path, body: str):
    """Run ``body`` as an ES module with the real Worker imported as `worker`.
    console.log is captured, so the Worker's own logging cannot corrupt the
    JSON the harness prints."""
    (tmp_path / "worker.mjs").write_text(WORKER.read_text(encoding="utf-8"),
                                         encoding="utf-8")
    harness = tmp_path / "harness.mjs"
    harness.write_text(
        'import worker from "./worker.mjs";\n'
        "const logs = [];\n"
        "console.log = (...a) => logs.push(a.join(' '));\n"
        "const result = await (async () => {\n" + body + "\n})();\n"
        "process.stdout.write(JSON.stringify({ result, logs }));\n",
        encoding="utf-8")
    done = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=60, cwd=tmp_path)
    if done.returncode:
        raise AssertionError(f"node failed:\n{done.stderr}")
    return json.loads(done.stdout)


def _simulate_week(tmp_path: Path, env: str = '{ GH_DISPATCH_TOKEN: "tok" }',
                   status: int = 204):
    """Every half-hour tick of one UTC week through `scheduled()`, with fetch
    stubbed: tick ISO -> the dispatches it made."""
    # The trigger fires at :17 and :47 (OPS-01), so the ticks do too.
    start = int((WEEK_START + timedelta(minutes=17)).timestamp() * 1000)
    return _node(tmp_path, f"""
      const calls = [];
      globalThis.fetch = async (url, init) => {{
        calls.push({{ url, method: init.method, headers: init.headers,
                      body: JSON.parse(init.body) }});
        return new Response(null, {{ status: {status} }});
      }};
      const out = {{}};
      const errors = {{}};
      for (let t = {start}; t < {start} + 7 * 24 * 3600 * 1000; t += 30 * 60 * 1000) {{
        calls.length = 0;
        try {{
          await worker.scheduled({{ scheduledTime: t, cron: "17,47 * * * *" }},
                                 {env}, {{ waitUntil() {{}} }});
        }} catch (e) {{ errors[new Date(t).toISOString()] = String(e); }}
        if (calls.length) out[new Date(t).toISOString()] = calls.slice();
      }}
      return {{ out, errors }};
    """)


# --------------------------------------------------------------------- #
# the Worker fires the crons (OPS-01)
# --------------------------------------------------------------------- #

def test_every_workflow_cron_is_one_the_worker_can_fire() -> None:
    """The Worker runs on ONE Cron Trigger, "17,47 * * * *", and matches only
    numbers, lists and `*`. A workflow cron at :15, or written with a step
    (`*/2`), would simply never be dispatched — no error anywhere — so the
    syntax the two sides share is pinned here, before any simulation."""
    header = WORKER.read_text(encoding="utf-8").split("*/", 1)[0]
    assert "17,47 * * * *" in header, "the trigger to configure is not documented"
    for name in SCHEDULED:
        crons = _crons(name)
        assert crons, f"{name} lost its own schedule — the GitHub backup is gone"
        for cron in crons:
            fields = cron.split()
            assert len(fields) == 5 and all(re.fullmatch(r"\*|\d+(,\d+)*", f)
                                            for f in fields), (name, cron)
            assert fields[0] in ("17", "47"), \
                f"{name} runs at minute {fields[0]}, which the Worker's trigger never reaches"


def test_no_backup_cron_fires_at_the_top_of_the_hour_and_the_watchdog_agrees() -> None:
    """OPS-01, reproduced from the launch audit: every GitHub backup cron sat
    at minute :00 (weekly 0 12 / 0 16, daily 0 14, saturday 0 16, monday
    0 13) — the minute GitHub's own documentation names as its busiest, when
    scheduled runs start latest or are dropped. They now sit off-peak, and the
    two places that encode WHEN the Tuesday run is due must say the same
    minute as the cron: the watchdog's "owed" cutoff (a purchase before it was
    owed that Tuesday's report) and the Worker's table (pinned below by
    simulation)."""
    for name in SCHEDULED:
        for cron in _crons(name):
            assert cron.split()[0] != "0", f"{name} still fires at :00: {cron}"
    tuesday = _crons("weekly.yml")[0].split()
    due = watchdog.tuesday_due_at(datetime(2026, 10, 13).date())
    assert (due.hour, due.minute) == (int(tuesday[1]), int(tuesday[0])), \
        f"the watchdog says the Tuesday run is due at {due:%H:%M}, the cron {tuesday}"


@needs_node
def test_the_worker_dispatches_exactly_what_the_workflows_schedule(tmp_path) -> None:
    """A week of half-hour ticks through the real `scheduled()`: at every tick
    the Worker dispatches exactly the workflows whose own crons fire then — no
    more (a duplicate Tuesday is cheap, but a Saturday check on a Wednesday is
    a wrong email), no fewer (the point of the Worker)."""
    sim = _simulate_week(tmp_path)
    assert not sim["result"]["errors"], sim["result"]["errors"]
    got = {iso: sorted(c["url"].rsplit("/workflows/", 1)[1].split("/")[0]
                       for c in calls)
           for iso, calls in sim["result"]["out"].items()}
    expected: dict[str, list[str]] = {}
    at = WEEK_START + timedelta(minutes=17)
    while at < WEEK_START + timedelta(days=7):
        fired = sorted(name for name in SCHEDULED
                       for cron in _crons(name) if _matches(cron, at))
        if fired:
            expected[at.strftime("%Y-%m-%dT%H:%M:%S.000Z")] = fired
        at += timedelta(minutes=30)
    assert got == expected
    # Spot checks in plain words, so a failure reads as a schedule.
    assert got["2026-10-13T12:17:00.000Z"] == ["weekly.yml"]     # Tuesday's reports
    assert got["2026-10-13T16:17:00.000Z"] == ["weekly.yml"]     # ...and the retry
    assert got["2026-10-17T16:17:00.000Z"] == ["saturday.yml"]
    assert got["2026-10-12T13:17:00.000Z"] == ["monday.yml"]
    assert sum(1 for names in got.values() if "daily.yml" in names) == 7 * 25


@needs_node
def test_a_dispatch_is_the_documented_github_call(tmp_path) -> None:
    """POST /repos/{repo}/actions/workflows/{file}/dispatches with a ref, the
    token as a Bearer, and a User-Agent (GitHub's API refuses a request with
    none). Inputs travel as STRINGS — the API rejects a JSON boolean for a
    boolean input — and only to daily.yml, the one workflow that declares
    any: an input a workflow does not declare is a 422, i.e. no run at all."""
    calls = [c for batch in _simulate_week(tmp_path)["result"]["out"].values()
             for c in batch]
    for call in calls:
        workflow = call["url"].rsplit("/workflows/", 1)[1].split("/")[0]
        assert call["url"] == ("https://api.github.com/repos/beatyourleague/"
                               f"beat-your-league/actions/workflows/{workflow}/dispatches")
        assert call["method"] == "POST"
        assert call["headers"]["Authorization"] == "Bearer tok"
        assert call["headers"]["User-Agent"]
        assert call["headers"]["Accept"] == "application/vnd.github+json"
        assert call["body"]["ref"] == "main"
        inputs = call["body"].get("inputs")
        if workflow == "daily.yml":
            assert set(inputs) == {"daily"} and inputs["daily"] in ("true", "false")
        else:
            assert inputs is None, f"{workflow} would refuse an undeclared input"


@needs_node
def test_without_its_token_the_worker_dispatches_nothing_and_a_refusal_is_loud(
        tmp_path) -> None:
    """Unset, the scheduler is off and the GitHub schedules carry on alone. A
    dispatch GitHub refuses (an expired token is the likely one) must show as a
    failed Cron Event, not a quiet log line nobody reads."""
    off = _simulate_week(tmp_path, env="{}")["result"]
    assert off["out"] == {} and off["errors"] == {}
    refused = _simulate_week(tmp_path, status=401)["result"]
    assert refused["errors"], "a refused dispatch was swallowed"
    assert all("HTTP 401" in e for e in refused["errors"].values())


def _evaluate(condition: str, *, event: str, schedule: str | None = None,
              daily: str | None = None, due: str | None = "true") -> bool:
    """A step's `if:` under one trigger. Only the names daily.yml's gate uses
    are substituted; anything left over fails the test rather than guessing.
    ``due`` is what the once-a-day claim step printed ("" when it did not run
    or printed nothing)."""
    expr = (condition.replace("always()", "True")
            .replace("steps.today.outputs.due", repr(due or ""))
            .replace("github.event.inputs.daily", repr(daily or ""))
            .replace("github.event.schedule", repr(schedule or ""))
            .replace("github.event_name", repr(event))
            .replace("&&", " and ").replace("||", " or "))
    leftover = re.sub(r"'[^']*'|True|and|or|==|!=|[()\s]", "", expr)
    assert not leftover, f"unrecognised condition terms: {leftover!r}"
    return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 — test-only, vetted above


def _once_a_day_steps() -> list[dict]:
    steps = list(_yaml("daily.yml")["jobs"].values())[0]["steps"]
    gated = [s for s in steps if "github.event.schedule" in str(s.get("if", ""))]
    assert {s.get("id") for s in gated} >= {"today", "billing", "watchdog"}, \
        "the day's claim, the billing stop or the watchdog is no longer once-a-day"
    return gated


@needs_node
def test_the_once_a_day_steps_run_on_the_14_00_dispatch_and_never_hourly(tmp_path) -> None:
    """A dispatch has no `github.event.schedule`, so the old gate
    (`!= '30 * * * *'`) read EVERY Worker dispatch as the daily run: the
    end-of-season billing stop would have walked every Stripe subscription 24
    times a day, and the watchdog would have filed its alarm hourly.

    Pinned by behaviour: for every tick at which the Worker dispatches
    daily.yml, each once-a-day step must run under the Worker's real inputs
    exactly when it would have run under GitHub's own schedule event at that
    tick. A forgotten input (or a hand-run with the box unticked) runs them
    NOT at all — the safe direction."""
    out = _simulate_week(tmp_path)["result"]["out"]
    daily_crons = _crons("daily.yml")
    seen_daily = seen_hourly = 0
    for iso, calls in out.items():
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        for call in calls:
            if not call["url"].endswith("/daily.yml/dispatches"):
                continue
            [cron] = [c for c in daily_crons if _matches(c, at)]
            for step in _once_a_day_steps():
                by_github = _evaluate(step["if"], event="schedule", schedule=cron)
                by_worker = _evaluate(step["if"], event="workflow_dispatch",
                                      daily=call["body"]["inputs"]["daily"])
                assert by_worker == by_github, (iso, step.get("name"))
            seen_daily += cron == "17 14 * * *"
            seen_hourly += cron == "47 * * * *"
    assert seen_daily == 7 and seen_hourly == 7 * 24
    for step in _once_a_day_steps():
        assert _evaluate(step["if"], event="schedule", schedule="17 14 * * *")
        assert not _evaluate(step["if"], event="schedule", schedule="47 * * * *")
        assert not _evaluate(step["if"], event="workflow_dispatch", daily="false")
        assert _evaluate(step["if"], event="workflow_dispatch", daily="true")
    triggers = _yaml("daily.yml").get(True) or _yaml("daily.yml").get("on")
    assert triggers["workflow_dispatch"]["inputs"]["daily"]["default"] is False


def test_the_once_a_day_steps_run_once_however_many_times_14_00_fires(
        tmp_path, monkeypatch, capsys) -> None:
    """Launch review OPS-7, evaluated: the gate above passes BOTH GitHub's
    `0 14 * * *` run and the Worker's 14:00 dispatch (daily=true), and the
    Worker fires every day beside the unchanged GitHub cron — so the watchdog
    commented on a missed run twice a day (the second possibly hours later)
    and the billing stop walked Stripe twice. The first 14:00 run now claims
    the UTC day (`run-daily-<date>` in the send log, which the second run reads
    from the branch tip) and the second skips.

    The claim carries the SAME schedule gate as the steps it guards, so an
    hourly run can never claim the day before 14:00. And it fails OPEN: a
    claim that printed nothing leaves the steps running, because running twice
    is a nuisance and not running is the failure the watchdog exists for."""
    import run.delivery as delivery
    steps = _once_a_day_steps()
    claim = next(s for s in steps if s.get("id") == "today")
    names = [s.get("id") for s in list(_yaml("daily.yml")["jobs"].values())[0]["steps"]]
    assert names.index("today") < names.index("billing") < names.index("watchdog")
    assert "steps.today" not in claim["if"], "the claim gates on itself"
    assert "-m run.watchdog --claim-day" in claim["run"]
    assert '>> "$GITHUB_OUTPUT"' in claim["run"]
    for step in steps:
        if step.get("id") == "today":
            continue
        for event, kw in (("schedule", {"schedule": "17 14 * * *"}),
                          ("workflow_dispatch", {"daily": "true"})):
            assert _evaluate(step["if"], event=event, due="true", **kw)
            assert not _evaluate(step["if"], event=event, due="false", **kw), \
                f"{step.get('id')} runs again on a day already claimed"
            assert _evaluate(step["if"], event=event, due="", **kw), \
                f"{step.get('id')} is skipped when the claim printed nothing"

    # The claim itself, run for real against a send log.
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    from test_tuesday import _registry, _row
    registry = str(_registry(tmp_path, _row()))
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)

    def claim_at(now: str) -> str:
        capsys.readouterr()
        assert watchdog.main(["--claim-day", "--now", now, "--registry", registry]) == 0
        return capsys.readouterr().out
    assert claim_at("2026-10-15T14:00:00+00:00") == "due=true\n"
    assert claim_at("2026-10-15T19:12:00+00:00") == "due=false\n"   # GitHub, late
    assert claim_at("2026-10-16T14:00:00+00:00") == "due=true\n"
    keys = [json.loads(line)["key"] for line in log.read_text().splitlines()]
    assert keys == ["run-daily-2026-10-15", "run-daily-2026-10-16"]
    # Before launch both steps are no-ops: nothing is claimed, so the
    # committed send log does not become a calendar of empty days.
    log.unlink()
    absent = str(tmp_path / "nowhere" / "rosters.json")
    capsys.readouterr()
    assert watchdog.main(["--claim-day", "--registry", absent]) == 0
    assert capsys.readouterr().out == "due=true\n" and not log.exists()


def test_a_queued_second_run_reads_what_the_first_one_pushed() -> None:
    """Every scheduled workflow now runs twice by design (the Worker's dispatch
    and GitHub's backup), and the second is QUEUED behind the first in its
    concurrency group. Without an explicit `ref`, actions/checkout checks out
    `github.sha` — the commit at the moment the run was triggered, i.e. BEFORE
    the first run pushed its send log — so the second run would read a log
    with none of the first run's sends in it and mail every subscriber again.
    The send log's idempotency only holds if the run reads the latest log;
    checking out the branch tip is what makes the double trigger safe."""
    for name in SCHEDULED:
        doc = _yaml(name)
        steps = list(doc["jobs"].values())[0]["steps"]
        assert any("git push" in str(s.get("run", "")) for s in steps), name
        checkout = next(s for s in steps if "actions/checkout" in str(s.get("uses")))
        assert checkout.get("with", {}).get("ref") == "${{ github.ref_name }}", \
            f"{name} checks out the trigger commit, not the branch tip"
        group = doc.get("concurrency") or {}
        assert group.get("group") and group.get("cancel-in-progress") is False, \
            f"{name} can run twice at once, or cancels a run half-way"


# --------------------------------------------------------------------- #
# the Worker's rows: they expire, and they may say where they came from
# --------------------------------------------------------------------- #

ROWS = {
    "seat": {"kind": "seat", "email": "m@example.com", "covered_by": "c@example.com",
             "ref": "s3-abc"},
    "update": {"kind": "update", "email": "m@example.com", "ref": "s3-abc",
               "replaces": "0123456789", "token": "0123456789abcdef0123"},
    "update_request": {"kind": "update_request", "email": "m@example.com", "ref": "s3-abc"},
    "confirm": {"kind": "confirm", "code": "0123456789abcdef01234567"},
    "trial": {"kind": "trial", "email": "m@example.com", "ref": "s3-abc"},
    "waitlist": {"kind": "waitlist", "email": "m@example.com"},
}


def _post_all(tmp_path, bodies: list[dict]):
    return _node(tmp_path, f"""
      const puts = [];
      const env = {{ SITE_ORIGIN: "https://x.test",
                     ROWS: {{ put: async (key, value, opts) => puts.push({{ key, value, opts }}) }} }};
      const statuses = [];
      for (const body of {json.dumps(bodies)}) {{
        const res = await worker.fetch(new Request("https://w.test/", {{
          method: "POST", body: JSON.stringify(body) }}), env);
        statuses.push(res.status);
      }}
      return {{ statuses, puts }};
    """)["result"]


@needs_node
def test_every_stored_row_expires(tmp_path) -> None:
    """The privacy page says we delete what we hold a short period after it
    stops being used, and nothing deleted anything: every row lived in KV
    forever (reproduced: the put carried metadata and no expiry). About 400
    days is the longest any row is needed (a seat claim serves the season it
    names; a waitlist address waits one offseason at most)."""
    got = _post_all(tmp_path, list(ROWS.values()))
    assert got["statuses"] == [200] * len(ROWS)
    for put in got["puts"]:
        ttl = put["opts"]["expirationTtl"]
        assert 395 * 86400 <= ttl <= 405 * 86400, ttl
        assert put["opts"]["metadata"]["kind"], "the row moved out of metadata"


@needs_node
def test_any_kind_may_say_where_it_came_from_and_a_bad_tag_costs_nothing(tmp_path) -> None:
    """Cookie-free attribution: an optional `via` on every kind, kept only in
    the shape ^[a-z0-9-]{1,24}$. A tag that is not that shape is DROPPED, never
    a refused row — a malformed link must not cost a signup — and it never
    changes any other field (the Worker <-> picker <-> intake contract)."""
    plain = _post_all(tmp_path, list(ROWS.values()))["puts"]
    for tag, kept in (("x", "x"), ("Reply-Kit", "reply-kit"), ("  x2  ", "x2"),
                      ("a" * 24, "a" * 24), ("a" * 25, None), ("<b>", None),
                      ("a b", None), ("me@example.com", None), ({"a": 1}, None)):
        tagged = _post_all(tmp_path, [dict(body, via=tag) for body in ROWS.values()])
        assert tagged["statuses"] == [200] * len(ROWS), tag
        for before, after in zip(plain, tagged["puts"]):
            meta = dict(after["opts"]["metadata"])
            assert meta.pop("via", None) == kept, (tag, meta["kind"])
            expected = dict(before["opts"]["metadata"])
            meta.pop("received_at"), expected.pop("received_at")
            assert meta == expected, f"`via` changed another field of {meta['kind']}"
    # Still refused for the reasons a row was refused before.
    refused = _post_all(tmp_path, [{"kind": "trial", "email": "nope", "via": "x"}])
    assert refused["statuses"] == [400] and not refused["puts"]


@needs_node
def test_the_worker_stores_the_new_shapes_and_nothing_looser(tmp_path) -> None:
    """Three Worker-side halves of shared contracts, run under node:

    - C4: a seat claim from the per-pass seat link carries `pass_token` (20
      hex) and NO payer address; one of the two is required, and a token of
      any other shape is dropped like a bad `via`, never stored.
    - C6: a waitlist row may carry the `ref` checkout would have used; a ref
      that is not Stripe-safe is dropped and the address still lands (a bad
      ref must not cost a sign-up).
    - G12: the operator's update (`make roster-update`) names no `replaces`;
      a token is still required, and a `replaces` that is present must be a
      slug."""
    token = "0123456789abcdef0123"
    rows = [
        {"kind": "seat", "email": "m@example.com", "ref": "s3-abc", "pass_token": token},
        {"kind": "seat", "email": "m@example.com", "ref": "s3-abc",
         "pass_token": "ABC", "covered_by": "c@example.com"},
        {"kind": "seat", "email": "m@example.com", "ref": "s3-abc", "pass_token": "nope"},
        {"kind": "waitlist", "email": "w@example.com", "ref": "s3-abc_via-x"},
        {"kind": "waitlist", "email": "w@example.com", "ref": "<b>"},
        {"kind": "update", "email": "u@example.com", "ref": "s3-abc", "token": token},
        {"kind": "update", "email": "u@example.com", "ref": "s3-abc", "token": token,
         "replaces": "not-a-slug"},
        {"kind": "update", "email": "u@example.com", "ref": "s3-abc"},
    ]
    got = _post_all(tmp_path, rows)
    assert got["statuses"] == [200, 200, 400, 200, 200, 200, 400, 400]
    stored = [{k: v for k, v in p["opts"]["metadata"].items() if k != "received_at"}
              for p in got["puts"]]
    assert stored == [
        {"kind": "seat", "email": "m@example.com", "ref": "s3-abc", "pass_token": token},
        {"kind": "seat", "email": "m@example.com", "ref": "s3-abc",
         "covered_by": "c@example.com"},
        {"kind": "waitlist", "email": "w@example.com", "ref": "s3-abc_via-x"},
        {"kind": "waitlist", "email": "w@example.com"},
        {"kind": "update", "email": "u@example.com", "ref": "s3-abc", "token": token},
    ]


# --------------------------------------------------------------------- #
# the dead-man's switch (OPS-06)
# --------------------------------------------------------------------- #

SEASON = "2026"


def _calendar(tmp_path: Path) -> Path:
    """Weeks 5-8 of a season laid out like a real one: Thursday night, the
    Sunday slate, Monday night — except week 8, which opens on a WEDNESDAY
    (the Christmas-Wednesday shape). Week 6's send Tuesday is Oct 13."""
    cache = tmp_path / "nflverse"
    cache.mkdir(parents=True, exist_ok=True)
    games = []
    for week, opener in ((5, "2026-10-08"), (6, "2026-10-15"), (7, "2026-10-22"),
                         (8, "2026-10-28")):
        first = datetime.fromisoformat(opener)
        sunday = first + timedelta(days=(6 - first.weekday()) % 7)
        for day, clock, home, away in ((first, "20:15", "KC", "DEN"),
                                       (sunday, "13:00", "DET", "GB"),
                                       (sunday + timedelta(days=1), "20:15", "SF", "SEA")):
            games.append({"season": SEASON, "game_type": "REG", "week": week,
                          "gameday": f"{day:%Y-%m-%d}",
                          "gametime": clock, "home_team": home, "away_team": away})
    with (cache / "games.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(games[0]))
        writer.writeheader()
        writer.writerows(games)
    return cache


def _watch(tmp_path, monkeypatch, now: str, keys=(), *, registry="one",
           bought: str | None = None) -> int:
    """The watchdog at ``now`` over a send log holding ``keys``. ``bought``
    (ISO, UTC) writes the subscriber's purchase into the signup log beside the
    registry; without it there is no log, so the purchase is unknown — owed."""
    import run.delivery as delivery
    from run.intake import SIGNUP_LOG_NAME
    from test_tuesday import REF, _registry, _row
    log = tmp_path / "sent.jsonl"
    log.write_text("".join(json.dumps({"key": k, "sent_at": now}) + "\n" for k in keys))
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    signups = tmp_path / SIGNUP_LOG_NAME
    signups.unlink(missing_ok=True)
    if bought is not None:
        stamp = int(datetime.fromisoformat(bought).timestamp())
        signups.write_text(json.dumps({"email": "fan@example.com", "ref": REF,
                                       "plan": "season", "seen_at": str(stamp)}) + "\n")
    path = {"one": lambda: _registry(tmp_path, _row()),
            "empty": lambda: _registry(tmp_path),
            "absent": lambda: tmp_path / "no-such" / "rosters.json"}[registry]()
    return watchdog.main(["--now", now, "--registry", str(path),
                          "--cache", str(_calendar(tmp_path))])


def _slug(tmp_path) -> str:
    """The test registry row's slug: the same digest the send log keys use."""
    from run.rosters import load_rosters
    from test_tuesday import _registry, _row
    return load_rosters(_registry(tmp_path, _row()))[0].slug


def test_a_tuesday_that_never_ran_turns_the_next_day_red(tmp_path, monkeypatch, capsys) -> None:
    """GitHub dropping the Tuesday cron files no issue — nothing failed. The
    Tuesday run's marker is the evidence: from Wednesday, no marker means no
    Tuesday run got as far as sending, and the run says so instead of a
    subscriber."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert _watch(tmp_path, monkeypatch, "2026-10-14T14:00:00+00:00") == 1
    err = capsys.readouterr().err
    assert "Tuesday's reports for 2026 week 6" in err and "@" not in err
    assert _watch(tmp_path, monkeypatch, "2026-10-14T14:00:00+00:00",
                  ["run-tuesday-2026-w06"]) == 0
    # Before the first kickoff the fix is a by-hand run; after it, re-running
    # would publish calls on a game already played, so the alarm says not to.
    assert "Run the weekly-report workflow by hand" in err
    assert _watch(tmp_path, monkeypatch, "2026-10-16T14:00:00+00:00") == 1
    late = capsys.readouterr().err
    assert "do NOT re-run" in late and "by hand" not in late
    # Not due on the Tuesday itself: the 16:00 retry is still to come.
    assert _watch(tmp_path, monkeypatch, "2026-10-13T14:00:00+00:00") == 0
    # Another week's marker, or any send at all, is not this Tuesday's run.
    slug = _slug(tmp_path)
    for wrong in (f"2026-w05-{slug}", f"2026-w06-final-{slug}", "run-tuesday-2026-w05",
                  "run-saturday-2026-w06"):
        assert _watch(tmp_path, monkeypatch, "2026-10-14T14:00:00+00:00", [wrong]) == 1, wrong


def test_a_new_buyers_first_email_is_not_proof_that_tuesday_ran(
        tmp_path, monkeypatch, capsys) -> None:
    """Launch review OPS-2, reproduced: the send log held only `2026-w07-<slug>`
    sent Tue 2026-10-20 09:30 UTC — an hourly intake's first email to a NEW
    buyer, keyed exactly like a Tuesday report — and no `run-tuesday-2026-w07`.
    `run.watchdog --now 2026-10-21T14:00Z` printed "everything due has run:
    Tuesday's reports" and exited 0, while every other subscriber had missed
    the week. This test used to ACCEPT a report key as evidence; only the
    marker counts now, and run.tuesday writes it on every run that got as far
    as sending."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    slug = _slug(tmp_path)
    for evidence in (f"2026-w06-{slug}", f"2026-w06-final-{slug}"):
        assert _watch(tmp_path, monkeypatch, "2026-10-14T14:00:00+00:00",
                      [evidence]) == 1, f"{evidence} was taken as Tuesday's run"
    assert "Tuesday's reports for 2026 week 6" in capsys.readouterr().err


def test_nobody_is_owed_a_run_that_was_due_before_they_bought(
        tmp_path, monkeypatch, capsys) -> None:
    """Launch review OPS-5, reproduced: secrets set AFTER a launch-week Tuesday
    that ran unconfigured (no marker), the first purchase — perhaps the
    owner's own proving one — on the Friday, the Saturday check run for real.
    The watchdog then reported "Subscribers missed this week; find out why"
    every day until the next Tuesday, about a report nobody was owed. A run is
    only missing if somebody bought before it was due: 12:00 UTC on the send
    Tuesday for the reports, the week's first kickoff for the final check (a
    buyer before kickoff was sent that week's lineup at purchase)."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    sunday = "2026-10-18T14:00:00+00:00"
    friday = "2026-10-16T15:00:00+00:00"          # after Thursday's kickoff
    assert _watch(tmp_path, monkeypatch, sunday, bought=friday) == 0
    out = capsys.readouterr().out
    assert out.count("nobody was owed it") == 2 and "everything due has run" not in out
    # Bought on the Tuesday, AFTER the 12:00 send: not owed Tuesday, but owed
    # the final check (Tuesday's buyers get the week's report at purchase).
    afternoon = "2026-10-13T15:00:00+00:00"
    assert _watch(tmp_path, monkeypatch, sunday, ["run-saturday-2026-w06"],
                  bought=afternoon) == 0
    assert _watch(tmp_path, monkeypatch, sunday, ["run-tuesday-2026-w06"],
                  bought=afternoon) == 1
    assert "final check for 2026 week 6" in capsys.readouterr().err
    # Bought before the send: owed both, exactly as before.
    monday = "2026-10-12T15:00:00+00:00"
    assert _watch(tmp_path, monkeypatch, sunday, ["run-saturday-2026-w06"],
                  bought=monday) == 1
    assert _watch(tmp_path, monkeypatch, sunday,
                  ["run-tuesday-2026-w06", "run-saturday-2026-w06"],
                  bought=monday) == 0


def test_purchase_times_err_toward_owed() -> None:
    """Pure. Unknown is never "not owed": a row with no purchase in the log
    (hand-added, or a lost log) alarms; a League Pass seat — which never
    transacts — takes its payer's purchase, since it cannot predate the pass;
    a roster update keeps the slug it was bought under (`origin`)."""
    from run.intake import RosterSignup
    from run.rosters import RosterSubscriber
    from test_tuesday import REF
    cutoff = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    late = str(int(datetime(2026, 10, 16, tzinfo=timezone.utc).timestamp()))
    early = str(int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()))
    payer = RosterSignup(email="Pay@Example.com", ref=REF, plan="league_pass",
                         seen_at=late)
    sub = RosterSubscriber(email="pay@example.com", ref=REF, player_ids=("a",),
                           slots=("QB",), scoring="ppr")
    seat = RosterSubscriber(email="m@example.com", ref="s3-other", player_ids=("a",),
                            slots=("QB",), scoring="ppr", plan="league_pass",
                            covered_by="pay@example.com")
    updated = RosterSubscriber(email="pay@example.com", ref="s3-new", player_ids=("a",),
                               slots=("QB",), scoring="ppr", origin=payer.slug)
    times = watchdog.purchase_times([sub, seat, updated], [payer])
    assert times[0] == times[1] == times[2] == datetime.fromtimestamp(int(late), tz=timezone.utc)
    assert not watchdog.owed(times, cutoff)
    assert watchdog.owed([None], cutoff), "an unknown purchase read as not owed"
    # The earliest purchase of a subscription counts.
    again = RosterSignup(email="pay@example.com", ref=REF, plan="season", seen_at=early)
    assert watchdog.owed(watchdog.purchase_times([sub], [payer, again]), cutoff)


def test_a_saturday_check_that_never_ran_is_not_mistaken_for_a_quiet_one(
        tmp_path, monkeypatch, capsys) -> None:
    """The final check mails only on change, so its sends prove nothing about
    a quiet week; its marker does — and only its marker (a final-check key
    proves no more than a report key does). From Sunday, no marker = red."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    slug = _slug(tmp_path)
    tuesday = ["run-tuesday-2026-w06"]
    assert _watch(tmp_path, monkeypatch, "2026-10-17T14:00:00+00:00", tuesday) == 0
    assert _watch(tmp_path, monkeypatch, "2026-10-18T14:00:00+00:00", tuesday) == 1
    assert "final check for 2026 week 6" in capsys.readouterr().err
    assert _watch(tmp_path, monkeypatch, "2026-10-18T14:00:00+00:00",
                  tuesday + ["run-saturday-2026-w06"]) == 0
    assert _watch(tmp_path, monkeypatch, "2026-10-18T14:00:00+00:00",
                  tuesday + [f"2026-w06-final-{slug}"]) == 1
    # Monday of the same week still reads week 6, and still knows.
    assert _watch(tmp_path, monkeypatch, "2026-10-19T14:00:00+00:00", tuesday) == 1


def test_a_saturday_check_that_ran_and_failed_still_says_it_ran(
        tmp_path, monkeypatch, capsys) -> None:
    """The marker answers "did it run", so the Saturday check leaves it at the
    end of any run that got as far as sending — a failed send included, with
    the counts saying so. That run exits 1 and files "Saturday final check
    failed"; a second, contradictory alarm the next day ("never finished")
    would send the owner looking for a run that did happen."""
    import run.delivery as delivery
    import run.saturday as saturday
    from run.delivery import DeliveryError
    from test_final_check import _registry_plan, _run
    from test_tuesday import ROSTER_IDS
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)

    class Down:
        name = "down"

        def send(self, message, sender, reply_to):
            raise DeliveryError("provider down")
    monkeypatch.setattr(saturday, "build_provider", lambda *a: Down())
    assert _run(tmp_path, monkeypatch, _registry_plan(),
                listed={ROSTER_IDS[1]: ("out", "ankle")}) == 1
    [entry] = [json.loads(line) for line in log.read_text().splitlines()]
    assert entry["key"] == watchdog.run_key("saturday", "2024", 10)
    assert "send failed 1" in entry["message_id"]


def test_the_watchdog_is_quiet_when_nobody_is_owed_anything(tmp_path, monkeypatch, capsys) -> None:
    """Before launch, with an empty registry, or after the season: no alarm. An
    alarm that fires when nothing is wrong is how the real one gets ignored —
    but an unreadable registry is not "nobody", it is unknown, and fails."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    wednesday = "2026-10-14T14:00:00+00:00"
    assert _watch(tmp_path, monkeypatch, wednesday, registry="absent") == 0
    assert "not set up yet" in capsys.readouterr().out
    assert _watch(tmp_path, monkeypatch, wednesday, registry="empty") == 0
    assert _watch(tmp_path, monkeypatch, "2026-11-04T14:00:00+00:00") == 0   # season over
    # Once a Stripe key exists the intake writes the registry every run, so a
    # missing one is a lost cache, not a quiet week.
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    assert _watch(tmp_path, monkeypatch, wednesday, registry="absent") == 1
    monkeypatch.delenv("STRIPE_API_KEY")
    (tmp_path / "rosters.json").write_text("{not json")
    import run.delivery as delivery
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    assert watchdog.main(["--now", wednesday, "--registry", str(tmp_path / "rosters.json"),
                          "--cache", str(_calendar(tmp_path))]) == 1


def test_the_send_tuesday_follows_the_schedule_not_an_assumed_thursday(tmp_path) -> None:
    """A Wednesday opener (a Christmas Wednesday, a 2026-style kickoff) still
    has its reports on the Tuesday before. "Two days before the first game"
    would put that week's send on a Monday, and the watchdog would then ask
    for Tuesday's reports a day before Tuesday ran (found by mutation: the
    Thursday-only fixture could not tell the two rules apart)."""
    cache = _calendar(tmp_path)
    assert watchdog.week_calendar(cache, SEASON, 6)[:2] == (
        datetime(2026, 10, 13).date(), datetime(2026, 10, 17).date())
    assert watchdog.week_calendar(cache, SEASON, 8)[:2] == (
        datetime(2026, 10, 27).date(), datetime(2026, 10, 31).date())
    # Thursday 20:15 in New York is Friday 00:15 UTC.
    assert watchdog.week_calendar(cache, SEASON, 6).first_kickoff == datetime(
        2026, 10, 16, 0, 15, tzinfo=timezone.utc)


def test_a_marker_is_a_key_no_message_has_and_is_written_once(tmp_path, monkeypatch) -> None:
    """Markers share the send log because it is the record every sending cron
    already commits (merge=union). So they must never read as a send to
    anything that counts sends — a report key is `{season}-wNN-<hex>` — and
    the Tuesday retry must not grow the log."""
    import run.delivery as delivery
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    assert watchdog.mark_run("tuesday", "2026", 6) is True
    assert watchdog.mark_run("tuesday", "2026", 6) is False
    lines = log.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["provider"] == "marker"
    key = json.loads(lines[0])["key"]
    assert not re.match(r"^\d{4}-w\d\d-", key) and not key.startswith(
        ("trial-", "welcome-", "preseason-", "confirm-", "renewal-", "launch-"))
    from run.stats import send_summary
    assert send_summary([json.loads(lines[0])], "2026") == {
        "weekly": {}, "finals": {}, "other": {}}
