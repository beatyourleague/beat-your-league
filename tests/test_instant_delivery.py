"""Instant delivery (Nov 3 2026): Stripe tells the form Worker the moment
someone pays, and the Worker starts the hourly intake now instead of at :47.

What is pinned here, each by running the real Worker under node:

- **Verified or nothing.** POST /stripe dispatches only for an event whose
  Stripe-Signature checks out exactly as Stripe documents it (HMAC-SHA256 over
  "<t>.<raw body>", any v1, five minutes either way). The signatures here are
  computed in Python with ``hmac``, so the Worker is checked against an
  independent implementation, not against itself.
- **It decides nothing and keeps nothing.** One dispatch, the same one the
  hourly run gets (daily.yml, {daily: "false"}); nothing from the event is
  stored, logged or forwarded.
- **The quiet window.** A buyer who paid while the Wednesday report run was
  going could be mailed that week's report of record by it AND an early look
  by a purchase-started intake minutes later. That is reproduced below with
  the real intake, and the Worker is pinned to leave a purchase in that
  window to the :47 hourly run, which the schedule already keeps clear.

The Worker tests need node and skip without it; CI installs it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "infra" / "form-worker.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not available")

SECRET = "whsec_test_0123456789abcdef"
EMAIL = "buyer.private@example.com"
SESSION = "cs_live_a1B2c3SECRETSESSION"
# A Tuesday afternoon: no report run near it.
CLEAR = datetime(2026, 11, 3, 18, 5, tzinfo=timezone.utc)


def _event(kind: str = "checkout.session.completed", pad: int = 0) -> bytes:
    """A Checkout Session event shaped like Stripe's, carrying the buyer's
    address — the thing that must never be stored or logged."""
    event = {"id": "evt_1PrivateEvent", "object": "event", "type": kind, "livemode": True,
             "data": {"object": {"id": SESSION, "object": "checkout.session",
                                 "customer_details": {"email": EMAIL, "name": "Pat Private"},
                                 "client_reference_id": "s3-pc-PRIVATEREF",
                                 "payment_status": "paid", "padding": "x" * pad}}}
    # Pretty-printed, as Stripe sends it: a check over re-serialised JSON
    # instead of the raw bytes would then fail here, as it would live.
    return json.dumps(event, indent=2).encode("utf-8")


def _sign(body: bytes, t: int, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), f"{t}.".encode("utf-8") + body,
                    hashlib.sha256).hexdigest()


def _header(body: bytes, t: int, secret: str = SECRET) -> str:
    return f"t={t},v1={_sign(body, t, secret)}"


HARNESS = """
function fakeKV() {
  const store = new Map();
  return {
    store, puts: 0, lists: 0, gets: 0, deletes: 0,
    async put(key, value, opts) { this.puts += 1; store.set(key, { value, opts }); },
    async get(key) { this.gets += 1; return null; },
    async list() { this.lists += 1; return { keys: [], list_complete: true }; },
    async delete(key) { this.deletes += 1; store.delete(key); },
  };
}
const calls = [];
let ghStatus = 204;
let ghThrows = false;
globalThis.fetch = async (url, init) => {
  calls.push({ url: String(url), method: init.method, headers: init.headers,
               body: JSON.parse(init.body) });
  if (ghThrows) throw new Error("network down");
  return new Response(null, { status: ghStatus });
};
let NOW = 0;
Date.now = () => NOW;
const hook = async (env, { body, headers = {}, method = "POST", at }) => {
  NOW = at;
  calls.length = 0;
  const init = { method, headers };
  if (method !== "GET") init.body = body;
  const res = await worker.fetch(new Request("https://forms.test/stripe", init), env);
  return { status: res.status, text: await res.text(), calls: calls.slice() };
};
"""


def _node(tmp_path: Path, body: str, cases: object = None):
    """Run ``body`` as an ES module with the real Worker imported as `worker`
    and ``cases`` (JSON) as `CASES`. console.log is captured into `logs`."""
    (tmp_path / "worker.mjs").write_text(WORKER.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    harness = tmp_path / "harness.mjs"
    harness.write_text(
        'import worker from "./worker.mjs";\nimport { readFileSync } from "node:fs";\n'
        'const CASES = JSON.parse(readFileSync("./cases.json", "utf8"));\n'
        "const logs = [];\nconsole.log = (...a) => logs.push(a.join(' '));\n"
        "console.error = (...a) => logs.push(a.join(' '));\n" + HARNESS +
        "const result = await (async () => {\n" + body + "\n})();\n"
        "process.stdout.write(JSON.stringify({ result, logs }));\n",
        encoding="utf-8")
    done = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=120, cwd=tmp_path)
    if done.returncode:
        raise AssertionError(f"node failed:\n{done.stderr}")
    return json.loads(done.stdout)


def _ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def _case(body: bytes, header: str | None, at: datetime = CLEAR, **extra) -> dict:
    headers = {"Content-Type": "application/json"}
    if header is not None:
        headers["Stripe-Signature"] = header
    headers.update(extra.pop("headers", {}))
    return {"body": body.decode("utf-8"), "headers": headers, "at": _ms(at), **extra}


RUN_CASES = """
const out = {};
for (const [name, c] of Object.entries(CASES)) {
  const env = { ROWS: kv, GH_DISPATCH_TOKEN: "tok", STRIPE_WEBHOOK_SECRET: SECRET,
                ...(c.env || {}) };
  for (const drop of c.drop || []) delete env[drop];
  ghStatus = c.ghStatus || 204;
  ghThrows = Boolean(c.ghThrows);
  out[name] = await hook(env, c);
}
return { out, kv: { size: kv.store.size, puts: kv.puts, lists: kv.lists, gets: kv.gets,
                    deletes: kv.deletes } };
"""


def _run(tmp_path: Path, cases: dict) -> dict:
    got = _node(tmp_path, f"const SECRET = {json.dumps(SECRET)};\nconst kv = fakeKV();\n"
                + RUN_CASES, cases)
    return {"out": got["result"]["out"], "kv": got["result"]["kv"], "logs": got["logs"]}


# --------------------------------------------------------------------- #
# a signed purchase starts the hourly run, and nothing else does
# --------------------------------------------------------------------- #

@needs_node
def test_a_signed_purchase_starts_the_hourly_intake_now(tmp_path) -> None:
    """Both purchase events, correctly signed: one dispatch each, of
    daily.yml with {daily: "false"} on main, with the token as a Bearer —
    the call the :47 hourly dispatch makes, so every rule the intake keeps
    (plan from the link, refunds, send keys) applies unchanged."""
    t = int(CLEAR.timestamp())
    completed = _event()
    late = _event("checkout.session.async_payment_succeeded")
    got = _run(tmp_path, {
        "completed": _case(completed, _header(completed, t)),
        "async": _case(late, _header(late, t)),
    })
    for name in ("completed", "async"):
        res = got["out"][name]
        assert res["status"] == 200 and res["text"] == "dispatched", (name, res)
        [call] = res["calls"]
        assert call["url"] == ("https://api.github.com/repos/beatyourleague/beat-your-league/"
                               "actions/workflows/daily.yml/dispatches")
        assert call["method"] == "POST"
        assert call["headers"]["Authorization"] == "Bearer tok"
        assert call["headers"]["User-Agent"]
        assert call["body"] == {"ref": "main", "inputs": {"daily": "false"}}


def test_the_purchase_run_is_the_hourly_run_and_skips_the_once_a_day_steps() -> None:
    """The Worker's PURCHASE_RUN must be the SCHEDULE's hourly entry, not a
    copy that drifts: a dispatch with daily "true" would walk every Stripe
    subscription for the billing stop on every purchase. Evaluated against
    daily.yml's own step conditions."""
    from test_scheduling import _evaluate, _once_a_day_steps
    got = WORKER.read_text(encoding="utf-8")
    schedule = re.search(r"const SCHEDULE = \[(.*?)\];", got, re.S).group(1)
    hourly = re.search(r'\{ cron: "47 \* \* \* \*", workflow: "daily\.yml", '
                       r'inputs: \{ daily: "(\w+)" \} \}', schedule)
    purchase = re.search(r'const PURCHASE_RUN = \{ cron: "purchase", workflow: "(\S+)", '
                         r'inputs: \{ daily: "(\w+)" \} \};', got)
    assert hourly and purchase, "the hourly entry or PURCHASE_RUN changed shape"
    assert purchase.group(1) == "daily.yml" and purchase.group(2) == hourly.group(1) == "false"
    for step in _once_a_day_steps():
        assert not _evaluate(step["if"], event="workflow_dispatch", daily=purchase.group(2)), \
            f"{step.get('id')} would run on every purchase"


@needs_node
def test_nothing_unverified_or_unrelated_dispatches(tmp_path) -> None:
    """Each of these answers without a dispatch: a wrong secret, a body
    changed after signing, a timestamp more than five minutes either way, a
    missing or malformed header, a header with only v0, an oversized body
    (declared or not), an unrelated event type, a GET, an unset
    STRIPE_WEBHOOK_SECRET (the route is off: 404) and an unset
    GH_DISPATCH_TOKEN (503, so Stripe retries while the hourly run serves
    the buyer)."""
    t = int(CLEAR.timestamp())
    body = _event()
    big = _event(pad=64 * 1024)
    refund = _event("charge.refunded")
    cases = {
        "wrong_secret": _case(body, _header(body, t, "whsec_someone_else")),
        "tampered": _case(body.replace(b"paid", b"PAID"), _header(body, t)),
        "stale": _case(body, _header(body, t - 301)),
        "future": _case(body, _header(body, t + 301)),
        "no_header": _case(body, None),
        "empty_header": _case(body, ""),
        "no_t": _case(body, f"v1={_sign(body, t)}"),
        "junk_t": _case(body, f"t={t}x,v1={_sign(body, t)}"),
        "v0_only": _case(body, f"t={t},v0={_sign(body, t)}"),
        "short_v1": _case(body, f"t={t},v1={_sign(body, t)[:32]}"),
        "oversized": _case(big, _header(big, t)),
        "oversized_declared": _case(body, _header(body, t),
                                    headers={"Content-Length": str(64 * 1024 + 1)}),
        "unrelated": _case(refund, _header(refund, t)),
        "get": {**_case(body, _header(body, t)), "method": "GET"},
        "no_secret": {**_case(body, _header(body, t)), "drop": ["STRIPE_WEBHOOK_SECRET"]},
        "no_token": {**_case(body, _header(body, t)), "drop": ["GH_DISPATCH_TOKEN"]},
        "not_json": _case(b"not json", _header(b"not json", t)),
    }
    got = _run(tmp_path, cases)["out"]
    want = {"wrong_secret": 400, "tampered": 400, "stale": 400, "future": 400,
            "no_header": 400, "empty_header": 400, "no_t": 400, "junk_t": 400,
            "v0_only": 400, "short_v1": 400, "oversized": 413, "oversized_declared": 413,
            "unrelated": 200, "get": 405, "no_secret": 404, "no_token": 503,
            "not_json": 400}
    assert {name: res["status"] for name, res in got.items()} == want
    for name, res in got.items():
        assert res["calls"] == [], f"{name} dispatched"
    assert got["unrelated"]["text"] == "ignored"


@needs_node
def test_the_tolerance_is_five_minutes_and_any_v1_may_match(tmp_path) -> None:
    """Stripe sends one v1 per active signing secret (two while a secret is
    being rolled), plus a v0 in test mode: any v1 matching is enough,
    wherever it sits. 300 seconds either way is inside the tolerance."""
    t = int(CLEAR.timestamp())
    body = _event()
    good, bad = _sign(body, t), _sign(body, t, "whsec_old")
    cases = {
        "right_second": _case(body, f"t={t},v1={bad},v1={good}"),
        "right_first": _case(body, f"t={t},v1={good},v1={bad}"),
        "with_v0": _case(body, f"t={t},v1={good},v0={bad}"),
        "spaces": _case(body, f"t={t}, v1={good}"),
        "upper": _case(body, f"t={t},v1={good.upper()}"),
        "old_edge": _case(body, _header(body, t), at=CLEAR + timedelta(seconds=300)),
        "new_edge": _case(body, _header(body, t), at=CLEAR - timedelta(seconds=300)),
        "only_wrong": _case(body, f"t={t},v1={bad},v1={bad}"),
    }
    got = _run(tmp_path, cases)["out"]
    for name in ("right_second", "right_first", "with_v0", "spaces", "upper",
                 "old_edge", "new_edge"):
        assert got[name]["status"] == 200 and len(got[name]["calls"]) == 1, (name, got[name])
    assert got["only_wrong"]["status"] == 400 and got["only_wrong"]["calls"] == []


@needs_node
def test_nothing_from_the_event_is_stored_logged_or_forwarded(tmp_path) -> None:
    """The event carries the buyer's address, name, session id and roster
    reference. None of it may reach KV, a log line, the response or the
    GitHub call — whether the request was verified, refused or failed."""
    t = int(CLEAR.timestamp())
    body = _event()
    cases = {
        "ok": _case(body, _header(body, t)),
        "refused": _case(body, _header(body, t, "whsec_wrong")),
        "gh_down": {**_case(body, _header(body, t)), "ghStatus": 500},
        "gh_unreachable": {**_case(body, _header(body, t)), "ghThrows": True},
        "no_token": {**_case(body, _header(body, t)), "drop": ["GH_DISPATCH_TOKEN"]},
    }
    got = _run(tmp_path, cases)
    assert got["kv"] == {"size": 0, "puts": 0, "lists": 0, "gets": 0, "deletes": 0}
    private = (EMAIL, "buyer.private", SESSION, "PRIVATEREF", "Pat Private", "evt_1Private",
               SECRET, _sign(body, t))
    shown = json.dumps(got["logs"]) + json.dumps(
        {n: {"text": r["text"], "calls": r["calls"]} for n, r in got["out"].items()})
    for value in private:
        assert value not in shown, value
    # And the log says what happened in fixed words a reader can act on.
    assert any("dispatched daily.yml" in line for line in got["logs"])
    assert any("dispatch failed" in line and "HTTP 500" in line for line in got["logs"])


@needs_node
def test_a_failed_dispatch_answers_502_so_stripe_retries(tmp_path) -> None:
    """The dispatch is awaited, not left to waitUntil: a GitHub refusal or an
    unreachable API answers 502, which Stripe retries (for up to three days
    in live mode) and shows on its webhook page. A 200 before the dispatch
    would have lost a failed one in silence; the hourly run would still
    serve the buyer, an hour later."""
    t = int(CLEAR.timestamp())
    body = _event()
    got = _run(tmp_path, {
        "refused": {**_case(body, _header(body, t)), "ghStatus": 401},
        "unreachable": {**_case(body, _header(body, t)), "ghThrows": True},
    })["out"]
    for name, res in got.items():
        assert res["status"] == 502 and len(res["calls"]) == 1, (name, res)


# --------------------------------------------------------------------- #
# the quiet window
# --------------------------------------------------------------------- #

def _yaml(name: str) -> dict:
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _crons(name: str) -> list[str]:
    doc = _yaml(name)
    triggers = doc.get("on") or doc.get(True)
    return [entry["cron"] for entry in triggers.get("schedule") or []]


def _quiet_minutes(start: datetime, days: int, lead: int, resume: int) -> set[datetime]:
    """Every minute from ``lead`` minutes before a weekly.yml or saturday.yml
    cron until the hourly run's minute after it, read from the workflows."""
    from test_scheduling import _matches
    crons = _crons("weekly.yml") + _crons("saturday.yml")
    quiet = set()
    for m in range(-60, days * 24 * 60 + 60):
        fire = start + timedelta(minutes=m)
        if not any(_matches(cron, fire) for cron in crons):
            continue
        wait = resume - fire.minute
        wait += 60 if wait <= 0 else 0
        for k in range(-lead, wait):
            quiet.add(fire + timedelta(minutes=k))
    return quiet


def test_the_quiet_window_is_derived_from_the_workflows() -> None:
    """The lead is daily.yml's intake timeout (the longest a run started just
    before a report run can still be sending), and the window ends at the
    hourly cron's minute, from which a dispatch is no worse than that run."""
    src = WORKER.read_text(encoding="utf-8")
    lead = int(re.search(r"const QUIET_LEAD_MINUTES = (\d+);", src).group(1))
    assert lead == _yaml("daily.yml")["jobs"]["intake"]["timeout-minutes"]
    assert re.search(r'const QUIET_FOR = \["weekly\.yml", "saturday\.yml"\];', src)
    hourly = [c for c in _crons("daily.yml") if c.split()[1:] == ["*"] * 4]
    assert hourly == ["47 * * * *"]


@needs_node
def test_a_purchase_during_a_report_run_is_left_for_the_hourly_run(tmp_path) -> None:
    """Every minute of one UTC week through the real route: a signed purchase
    dispatches unless the minute is inside a quiet window computed here from
    the YAML crons. Spot checks read as a schedule."""
    src = WORKER.read_text(encoding="utf-8")
    lead = int(re.search(r"const QUIET_LEAD_MINUTES = (\d+);", src).group(1))
    resume = int(_crons("daily.yml")[1].split()[0])
    start = datetime(2026, 10, 12, tzinfo=timezone.utc)          # a Monday
    body = _event()
    got = _node(tmp_path, f"""
      const SECRET = {json.dumps(SECRET)};
      const env = {{ ROWS: fakeKV(), GH_DISPATCH_TOKEN: "tok", STRIPE_WEBHOOK_SECRET: SECRET }};
      const out = {{}};
      for (const c of CASES) {{
        const res = await hook(env, c);
        out[c.at] = [res.status, res.calls.length, res.text];
      }}
      return out;
    """, [_case(body, _header(body, int((start + timedelta(minutes=m)).timestamp())),
                at=start + timedelta(minutes=m))
          for m in range(7 * 24 * 60)])["result"]
    expected = _quiet_minutes(start, 7, lead, resume)
    quiet = set()
    for m in range(7 * 24 * 60):
        at = start + timedelta(minutes=m)
        status, dispatched, text = got[str(_ms(at))]
        assert status == 200, (at, text)
        if at in expected:
            quiet.add(at)
            assert dispatched == 0 and text == "left for the hourly run", at
        else:
            assert dispatched == 1 and text == "dispatched", at

    def q(iso: str) -> bool:
        return datetime.fromisoformat(iso + "+00:00") in quiet
    # Wednesday's evening run (22:17) and its retry (00:17 Thursday).
    assert not q("2026-10-14T22:01") and q("2026-10-14T22:02") and q("2026-10-14T22:17")
    assert q("2026-10-14T22:46") and not q("2026-10-14T22:47")
    assert q("2026-10-15T00:02") and q("2026-10-15T00:46") and not q("2026-10-15T00:47")
    assert not q("2026-10-14T23:30")
    # The morning slot (13:17 every Wednesday) and the Saturday check.
    assert q("2026-10-14T13:02") and not q("2026-10-14T13:47")
    assert q("2026-10-17T16:02") and q("2026-10-17T16:46") and not q("2026-10-17T16:47")
    # Monday's grading mails nobody, so a Monday purchase goes at once.
    assert not q("2026-10-12T13:20")
    # Four runs a week, each window 45 minutes: the rest of the week is instant.
    assert len(quiet) == 4 * 45


# --------------------------------------------------------------------- #
# why the window exists, reproduced with the real intake
# --------------------------------------------------------------------- #

class _Sink:
    name = "sink"

    def __init__(self) -> None:
        self.sent = []

    def send(self, message, sender, reply_to):
        self.sent.append(message)
        return "id"


def _intake(tmp_path, monkeypatch, log: Path):
    import run.delivery as delivery
    import run.intake as intake
    from test_solo_run import OFFLINE, SEASON, WEEK, _cache
    cache = _cache(tmp_path)
    data = intake.load_week_data(cache, SEASON, WEEK, session=OFFLINE)
    monkeypatch.setattr("run.solo.week_has_kicked_off", lambda *a, **k: False)
    monkeypatch.setattr(intake, "CACHE_DIR", cache)
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    sink = _Sink()
    monkeypatch.setattr(intake, "build_provider", lambda *a, **k: sink)
    return intake, data, SEASON, WEEK, sink


def _log(path: Path, *entries: tuple[str, datetime]) -> None:
    path.write_text("".join(json.dumps({"key": key, "sent_at": at.isoformat()}) + "\n"
                            for key, at in entries), encoding="utf-8")


def test_an_intake_inside_the_wednesday_run_mails_a_second_report(tmp_path, monkeypatch) -> None:
    """The hazard, run for real. A buyer pays at 22:20 UTC on a Wednesday,
    after weekly.yml's own intake (--no-mail) registered them, so its
    run.tuesday mails them the week's report of record. weekly-report and
    daily-intake sit in different concurrency groups, and weekly.yml pushes
    its send log (the report's key AND its run marker) only when the whole
    run ends. An intake started by the purchase checks out the log as it was
    before that push: no marker, so `tuesday_finished` is False, and no
    report key. So it mails an EARLY LOOK, minutes after the report of
    record. Two reports for one week, the second labelled as coming first.

    The :47 hourly run starts after weekly.yml has pushed, and is right in
    both cases: nothing more when the report of record went out, and the
    report of record (not an early look) when the weekly run registered the
    buyer too late to mail them."""
    from run.intake import RosterSignup
    from run.tuesday import early_look_key, report_key
    from run.watchdog import TUESDAY, run_key
    from test_tuesday import REF
    paid = datetime(2026, 10, 14, 22, 20, tzinfo=timezone.utc)
    signup = RosterSignup(email="fan@example.com", ref=REF, plan="season",
                          seen_at=str(int(paid.timestamp())))
    log = tmp_path / "sent.jsonl"
    intake, data, season, week, sink = _intake(tmp_path, monkeypatch, log)
    record_key = report_key(data.season, data.week, signup.slug)
    marker = run_key(TUESDAY, data.season, data.week)

    def first(log_at_checkout: list[tuple[str, datetime]]) -> list[str]:
        _log(log, *log_at_checkout)
        sink.sent.clear()
        intake._send_first_files([signup], data, season, processed_dir=tmp_path / "p",
                                 first_plans=tmp_path / "first", out_dir=tmp_path / "out")
        return [m.key for m in sink.sent]

    # A purchase-started intake at 22:23, while weekly.yml (22:17) is still
    # running: the committed log has neither its report nor its marker.
    during = first([])
    assert during == [early_look_key(data.season, data.week, signup.slug)]
    # Meanwhile weekly.yml mailed `record_key` to the same buyer at 22:25:
    # once both push (merge=union), the log holds two reports for one week.
    both = {record_key, *during}
    assert len(both) == 2, "the same buyer, two reports, one week"

    # The :47 hourly run, after weekly.yml pushed.
    after = paid + timedelta(minutes=5)
    assert first([(record_key, after), (marker, after)]) == [], \
        "the hourly run mailed a buyer the weekly run had already served"
    assert first([(marker, paid - timedelta(minutes=1))]) == [record_key], \
        "the hourly run sent an early look after the week's report had gone out"


# --------------------------------------------------------------------- #
# the switch, as the owner's checks see it
# --------------------------------------------------------------------- #

@needs_node
def test_the_worker_says_whether_instant_delivery_is_set_up_and_nothing_more(tmp_path) -> None:
    """GET ?status=1 (read key only) answers a boolean: true only with BOTH
    the Stripe signing secret and the dispatch token. Neither value appears."""
    got = _node(tmp_path, """
      const ask = async (env) => {
        const res = await worker.fetch(new Request("https://w.test/?status=1",
          { headers: { Authorization: "Bearer k" } }), { ROWS: fakeKV(), FORM_API_KEY: "k", ...env });
        return await res.text();
      };
      return { none: await ask({}),
               secret: await ask({ STRIPE_WEBHOOK_SECRET: "whsec_x1" }),
               token: await ask({ GH_DISPATCH_TOKEN: "ghp_x2" }),
               both: await ask({ STRIPE_WEBHOOK_SECRET: "whsec_x1", GH_DISPATCH_TOKEN: "ghp_x2" }) };
    """)["result"]
    for name, want in (("none", False), ("secret", False), ("token", False), ("both", True)):
        assert json.loads(got[name])["instant_delivery"] is want, name
        assert "whsec_x1" not in got[name] and "ghp_x2" not in got[name]


def test_the_launch_check_reports_instant_delivery_from_the_worker(monkeypatch) -> None:
    """OWNER when the Worker says false (or runs code too old to say), PASS
    when true, SKIP when it can't be asked or read: a buyer is still served
    by the hourly run, so this is never a failure."""
    import run.launch_check as lc
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.delenv("FORM_API_KEY", raising=False)
    [gate] = lc.check_instant_delivery()
    assert gate.status == "SKIP"
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test/rows")
    monkeypatch.setenv("FORM_API_KEY", "k")
    for answer, want in (({"trial_open": False, "instant_delivery": True}, "PASS"),
                         ({"trial_open": False, "instant_delivery": False}, "OWNER"),
                         ({"trial_open": False}, "OWNER")):
        monkeypatch.setattr(lc, "worker_status", lambda e, k, a=answer: a)
        [gate] = lc.check_instant_delivery()
        assert gate.status == want, answer
        if want == "OWNER":
            assert gate.detail.startswith("Instant delivery isn't set up")
            assert "LAUNCH.md step 4" in gate.detail

    def down(endpoint, key):
        raise OSError("timed out")
    monkeypatch.setattr(lc, "worker_status", down)
    [gate] = lc.check_instant_delivery()
    assert gate.status == "SKIP" and "could not read" in gate.detail
    steps = [line for line in Path(lc.__file__).read_text(encoding="utf-8").splitlines()
             if "check_instant_delivery)" in line]
    assert steps, "make launch-check never runs the gate"


def test_the_dashboard_runs_the_gate_and_shows_it_on_the_launch_card() -> None:
    """The dashboard runs the fast gates; this one is among them, named as
    the launch check names it, and the launch card says on or not set up."""
    import run.dashboard as dash
    import run.launch_check as lc
    from test_dashboard import NOW, _site, rich_sources
    assert "check_instant_delivery" in dash.FAST_GATES
    assert dash.INSTANT_GATE == lc.INSTANT_GATE
    S = rich_sources()
    S["stripe"] = dash._source("stripe", data={"sessions": [], "link_map": True,
                                               "dispute_errors": 0}, read_at=NOW)
    S["site"] = _site((NOW - timedelta(hours=2)).isoformat())

    def card(status: str) -> str:
        S["launch"] = dash._source("launch", data={"gates": [
            {"area": "Owner", "name": lc.INSTANT_GATE, "status": status, "detail": ""}]},
            read_at=NOW)
        return dash.launch_status(S, NOW)
    assert "Instant delivery" in card("PASS") and "On: Stripe starts" in card("PASS")
    assert "Not set up" in card("OWNER")
    assert "Instant delivery" not in card("SKIP")
