"""Final review (Oct 24 2026), the security branch: SEC-1..4, OPS-1, OPS-5's
optional half, and two appsec hardenings.

Each test names the finding it pins and carries its reproduction:

- SEC-1 — one anonymous POST with a lone UTF-16 surrogate in the address
  ("a\\ud800@x.co") was stored by the Worker, rebuilt by Python's json.loads,
  and the first .encode("utf-8") downstream raised: every intake run stopped
  before the registry was written, and the free report, launch email and
  privacy tool crashed on the same row.
- SEC-2 — the privacy workflow ran show/export/delete for anyone holding the
  dispatch token, on a 12-hex code the public send log carries for every
  waitlist and free-report mailbox.
- SEC-3 / contract C4 — the $19 Playoff Pass link sat under s: beside the $29
  one, so a buyer who copied it from the page source in Week 8 bought every
  report through Week 18 for $10 less and nothing reported it.
- SEC-4 — one forged seat claim with a random token raised "SEAT LINKS MATCH
  NO PASS" and kept every hourly run red for 14 days.
- OPS-1 — the Pay-button script inverted the link map by plan, so the two
  season links collapsed and it then demanded a monthly link 2026 does not
  sell: no 2026 link ever got its one-payment text or 18+ box.
- OPS-5 — a cron key missing Payment Intents/Charges read kept the intake
  green and mailed nobody on Tuesday.
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import run.intake as intake
from run.checkout import (PLAYOFF_FROM_WEEK, link_map_problems, parse_link_plans,
                          playoff_links)
from run.updates import seat_token
from test_intake_sync import (PASS_LINK, PASS_SUB, REF, SEASON_LINK, SEAT_REF,
                              _capture_sends, _pass_session, _registry, _run,
                              _session, directory, stripe)  # noqa: F401 — fixtures
from test_prelaunch_worker import FAKE_KV

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "infra" / "form-worker.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not available")
PLAYOFF_LINK = "plink_O"
LINKS_2026 = f"s:{SEASON_LINK},o:{PLAYOFF_LINK},p:{PASS_LINK}"
BAD = "a\ud800@x.co"


# --------------------------------------------------------------------- #
# harnesses: the Worker under node, and a Worker read served over HTTP
# --------------------------------------------------------------------- #

def _node(tmp_path: Path, body: str, source: str | None = None):
    """Run ``body`` as an ES module with the Worker (or ``source``) as `worker`."""
    (tmp_path / "worker.mjs").write_text(source or WORKER.read_text(encoding="utf-8"),
                                         encoding="utf-8")
    harness = tmp_path / "harness.mjs"
    harness.write_text(
        'import worker from "./worker.mjs";\n' + FAKE_KV +
        "const result = await (async () => {\n" + body + "\n})();\n"
        "process.stdout.write(JSON.stringify({ result }));\n", encoding="utf-8")
    done = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=60, cwd=tmp_path)
    if done.returncode:
        raise AssertionError(f"node failed:\n{done.stderr}")
    return json.loads(done.stdout)["result"]


def _hours_ago(hours: float) -> str:
    at = datetime.now(timezone.utc) - timedelta(hours=hours)
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Every kind that carries an address, each with the surrogate address. A seat
# row is aged 7h (past the unmatched-note grace) the way the verifier aged it.
def _surrogate_rows(email: str = BAD) -> list[dict]:
    token = "0123456789abcdef0123"
    return [
        {"kind": "update", "email": email, "ref": SEAT_REF, "token": token},
        {"kind": "seat", "email": email, "ref": SEAT_REF, "pass_token": token},
        {"kind": "update_request", "email": email, "ref": SEAT_REF},
        {"kind": "trial", "email": email, "ref": SEAT_REF},
        {"kind": "waitlist", "email": email},
    ]


@pytest.fixture
def worker_read():
    """An HTTP endpoint answering GET with a body the test sets — the form
    Worker's read, byte for byte, so fetch_seats runs for real."""
    state = {"body": b"[]", "auth": []}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server's name
            state["auth"].append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *args):  # silence
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/"
    yield state
    server.shutdown()
    server.server_close()


def _unguarded_worker() -> str:
    """The Worker with the SEC-1 guard taken out — what was live before the
    fix, and what any backend without it would store."""
    source = WORKER.read_text(encoding="utf-8")
    guarded = " || LONE_SURROGATE.test(email)"
    assert guarded in source, "the SEC-1 guard moved; update this harness"
    return source.replace(guarded, "")


def _stored_read(tmp_path: Path, source: str, rows: list[dict]) -> str:
    """POST ``rows`` to a Worker, then return its GET body as raw text."""
    return _node(tmp_path, f"""
      const kv = fakeKV();
      const env = {{ ROWS: kv, SITE_ORIGIN: "https://x.test", FORM_API_KEY: "k",
                     TRIAL_OPEN: "true" }};
      const statuses = [];
      for (const row of {json.dumps(rows)}) {{
        const res = await worker.fetch(new Request("https://w.test/", {{
          method: "POST", headers: {{ Origin: "https://x.test", Authorization: "Bearer k",
                                      "Content-Type": "application/json" }},
          body: JSON.stringify(row) }}), env);
        statuses.push(res.status);
      }}
      const got = await worker.fetch(new Request("https://w.test/",
        {{ headers: {{ Authorization: "Bearer k" }} }}), env);
      return {{ statuses, body: await got.text() }};
    """, source=source)


# --------------------------------------------------------------------- #
# SEC-1 — a lone surrogate
# --------------------------------------------------------------------- #

@needs_node
def test_the_worker_refuses_a_lone_surrogate_in_every_kind(tmp_path) -> None:
    """Reproduced (SEC-1): the Worker answered 200 for update, seat,
    update_request, trial and waitlist rows with "a\\ud800@x.co" and its GET
    returned the address. Now every kind refuses a lone surrogate (high or
    low) with 400 and stores nothing, while an address with an accent, an
    emoji or an apostrophe — whole code points — still lands. EMAIL itself is
    the shared JOIN-129 rule and stays as it is."""
    bad = _surrogate_rows() + _surrogate_rows("a@x\udc00.co")
    good = _surrogate_rows("josé.o'neil@x.co") + _surrogate_rows("fan😀@x.co")
    got = _stored_read(tmp_path, WORKER.read_text(encoding="utf-8"), bad + good)
    assert got["statuses"] == [400] * len(bad) + [200] * len(good)
    stored = json.loads(got["body"])
    assert len(stored) == len(good)
    assert all("\ud800" not in r.get("email", "") and "\udc00" not in r.get("email", "")
               for r in stored)
    source = WORKER.read_text(encoding="utf-8")
    assert "const EMAIL = /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/;" in source, \
        "EMAIL is the rule the page and run/rosters.py share — the guard sits beside it"


@needs_node
def test_a_surrogate_row_no_longer_stops_the_intake(
        tmp_path, stripe, directory, monkeypatch, worker_read, capsys) -> None:
    """Reproduced (SEC-1, the verifier's main_run.py): the real run.intake.main
    against a Worker read holding the surrogate rows raised UnicodeEncodeError
    at update_token (intake → updates.validate_updates → .encode) before the
    registry was written — no buyer registered, welcomed or sent a first
    report for the row's 30 days. Served the read of a Worker WITHOUT the
    guard (a row stored before the fix), the intake now drops those rows at
    fetch_seats, says so, and registers and welcomes the paying buyer."""
    (tmp_path / "w").mkdir()
    body = _stored_read(tmp_path / "w", _unguarded_worker(), _surrogate_rows())
    assert body["statuses"] == [200] * 5, "the unguarded Worker no longer stores the rows"
    assert "\\ud800" in body["body"], "the Worker read no longer carries the surrogate"
    # Aged past the unmatched-note grace, as the verifier's 7h seat row was.
    rows = [dict(r, received_at=_hours_ago(7)) for r in json.loads(body["body"])]
    worker_read["body"] = json.dumps(rows).encode("ascii")
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("FORM_ENDPOINT", worker_read["url"])
    monkeypatch.setenv("FORM_API_KEY", "k")
    monkeypatch.setenv("UPDATE_SECRET", "test-secret-do-not-ship")
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path) == 0
    err = capsys.readouterr().err
    assert "not valid Unicode" in err and "dropped" in err
    assert [r["email"] for r in _registry(tmp_path)] == ["fan@example.com"]
    assert [m.to for m in sends] == ["fan@example.com"], "the buyer was not welcomed"
    assert worker_read["auth"] and worker_read["auth"][0] == "Bearer k"


def test_every_reader_of_the_worker_gets_clean_rows(tmp_path, worker_read) -> None:
    """The choke point (SEC-1): fetch_seats is what the intake, free reports,
    the waitlist, privacy, stats and the launch check all call. Reproduced:
    trials.trial_key, digest.address(waitlist email) and privacy.find (for an
    UNRELATED code, so the privacy workflow failed for everyone) each raised
    on the surrogate row. Read through fetch_seats, none of them sees it, and
    the count of dropped rows rides on the list."""
    from run import privacy, trials, waitlist
    from run.digest import address
    good = {"kind": "waitlist", "email": "w@example.com", "received_at": _hours_ago(1)}
    worker_read["body"] = json.dumps(
        [dict(r, received_at=_hours_ago(1)) for r in _surrogate_rows()] + [good]
    ).encode("ascii")
    rows = intake.fetch_seats(worker_read["url"], "k")
    assert rows == [good] and rows.dropped == 5
    assert [address(a) for a in waitlist.waitlist_addresses(rows)]
    trials.pending(rows, set(), set(), "2026",
                   since=datetime(2026, 1, 1, tzinfo=timezone.utc))
    privacy.find("0123456789ab", tmp_path, [], worker_rows=rows)
    # A row that encodes is never dropped, whatever script it is in.
    worker_read["body"] = json.dumps([{"kind": "waitlist", "email": "josé@x.co"}]).encode()
    assert intake.fetch_seats(worker_read["url"], "k").dropped == 0


@needs_node
def test_a_roster_update_post_needs_the_read_key(tmp_path, monkeypatch) -> None:
    """Appsec (with SEC-1): kind:"update" is the operator's route — `make
    roster-update` → run/updates.post_row, which sends the read key — and no
    report link has ever carried a token. From the site's Origin it was
    accepted, which is the public door SEC-1's crash came through. Now 403
    from the Origin alone, 200 with the key; the subscriber's own
    update_request is untouched, and post_row still sends the key."""
    row = {"kind": "update", "email": "fan@example.com", "ref": SEAT_REF,
           "token": "0123456789abcdef0123"}
    got = _node(tmp_path, f"""
      const env = {{ ROWS: fakeKV(), SITE_ORIGIN: "https://x.test", FORM_API_KEY: "k" }};
      const send = (body, headers) => worker.fetch(new Request("https://w.test/", {{
        method: "POST", headers: {{ "Content-Type": "application/json", ...headers }},
        body: JSON.stringify(body) }}), env).then((r) => r.status);
      return {{
        origin: await send({json.dumps(row)}, {{ Origin: "https://x.test" }}),
        home: await send({json.dumps(row)}, {{ Origin: "https://beatyourleague.com" }}),
        wrongKey: await send({json.dumps(row)}, {{ Origin: "https://x.test", Authorization: "Bearer x" }}),
        key: await send({json.dumps(row)}, {{ Authorization: "Bearer k" }}),
        request: await send({{ kind: "update_request", email: "fan@example.com",
                               ref: {json.dumps(SEAT_REF)} }}, {{ Origin: "https://x.test" }}),
      }};
    """)
    assert got == {"origin": 403, "home": 403, "wrongKey": 403, "key": 200, "request": 200}

    import urllib.request

    from run import updates
    seen = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=0):
        seen["auth"] = request.get_header("Authorization")
        return _Response()
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    updates.post_row("https://w.test/", row, api_key="k")
    assert seen["auth"] == "Bearer k"


# --------------------------------------------------------------------- #
# SEC-2 — the privacy workflow needs the owner's code
# --------------------------------------------------------------------- #

def _privacy_steps():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "privacy.yml").read_text())
    return doc, list(doc["jobs"].values())[0]["steps"]


def test_every_privacy_action_needs_the_owners_approval() -> None:
    """Reproduced (SEC-2): with a test LOG_SECRET, a waitlister's launch key
    was 'launch-2026-d950686cd8e6', and dispatching privacy.yml with action
    delete and code d950686cd8e6 erased the paying subscriber that address
    belonged to — registry row, signups, plans and backups. Now the workflow
    takes a required `approval` and verifies it (an HMAC under LOG_SECRET,
    which the dispatch token cannot read) before anything is restored,
    opened or acted on, for every action: `show` prints counts into a public
    log."""
    doc, steps = _privacy_steps()
    inputs = doc[True]["workflow_dispatch"]["inputs"]
    assert inputs["approval"]["required"] is True
    names = [s.get("name") for s in steps]
    check = next(s for s in steps if "run.approval verify" in str(s.get("run", "")))
    assert 'verify privacy "$APPROVAL" "$ACTION" "$CODE"' in check["run"]
    assert "if" not in check, "the approval must gate every action, show included"
    assert check["env"] == {"ACTION": "${{ github.event.inputs.action }}",
                            "CODE": "${{ github.event.inputs.code }}",
                            "APPROVAL": "${{ github.event.inputs.approval }}",
                            "LOG_SECRET": "${{ secrets.LOG_SECRET }}"}
    act = names.index("Act on the request")
    first_restore = next(i for i, s in enumerate(steps) if "restore" in str(s.get("uses", "")))
    assert names.index(check["name"]) < min(act, first_restore)
    assert "if" not in steps[act], "a failed approval must stop the request"


def test_a_privacy_approval_binds_the_action_and_the_person(monkeypatch, capsys) -> None:
    """The code is over the exact action and 12-hex code: another person, or
    delete in place of show, is a different code. Case and stray whitespace
    normalise (run/privacy.py lowercases the code). A notice code is
    byte-for-byte what it was before privacy existed, so no code the owner
    already made stops matching."""
    import hmac as _hmac

    import run.approval as approval
    from run.digest import keyed
    monkeypatch.setenv("LOG_SECRET", "owner-secret")
    signed = approval.code("privacy", "delete", "d950686cd8e6")
    assert re.fullmatch(r"[0-9a-f]{20}", signed)
    assert approval.verify("privacy", signed, " DELETE ", "D950686CD8E6\n")
    assert not approval.verify("privacy", signed, "delete", "d950686cd8e7")
    assert not approval.verify("privacy", signed, "show", "d950686cd8e6")
    assert approval.main(["verify", "privacy", signed, "delete", "d950686cd8e6"]) == 0
    assert approval.main(["verify", "privacy", "0" * 20, "delete", "d950686cd8e6"]) == 1
    assert approval.main(["privacy", "erase", "d950686cd8e6"]) == 1
    capsys.readouterr()
    assert approval.main(["privacy", "show", "d950686cd8e6"]) == 0
    assert capsys.readouterr().out.strip() == approval.code("privacy", "show", "d950686cd8e6")
    old = keyed("\x00".join(["byl-approval-v1", "notice", "terms", "2026-11-15",
                             "Refunds now close at kickoff."]), approval.LENGTH)
    assert _hmac.compare_digest(
        approval.code("notice", "terms", "2026-11-15", "Refunds  now close\nat kickoff."), old)
    monkeypatch.setenv("LOG_SECRET", "a-stolen-guess")
    assert not approval.verify("privacy", signed, "delete", "d950686cd8e6")


# --------------------------------------------------------------------- #
# SEC-3 / contract C4 — the $19 Playoff Pass under its own prefix
# --------------------------------------------------------------------- #

def test_the_link_map_carries_the_playoff_pass_under_o() -> None:
    """Contract C4: o: is the $19 Playoff Pass — the season plan, told apart.
    Reproduced (SEC-3): LAUNCH.md's 's:plink_ROS29,s:plink_PO19,p:plink_LP69'
    parsed to two season links nobody could tell apart. link_map_problems is
    the one check the Pay-button script and the launch check share."""
    assert parse_link_plans(LINKS_2026) == {SEASON_LINK: "season", PLAYOFF_LINK: "season",
                                            PASS_LINK: "league_pass"}
    assert playoff_links(LINKS_2026) == {PLAYOFF_LINK}
    assert playoff_links(f"s:{SEASON_LINK},p:{PASS_LINK}") == frozenset()
    assert parse_link_plans("s:plink_A,m:plink_B,p:plink_C")["plink_B"] == "monthly"
    good = "s:plink_A,o:plink_B,p:plink_C"
    assert link_map_problems(good) == []
    assert link_map_problems(good + ",m:plink_D") == []
    assert any("o:" in p for p in link_map_problems("s:plink_A,s:plink_B,p:plink_C"))
    assert any("no o: link" in p for p in link_map_problems("s:plink_A,p:plink_C"))
    assert link_map_problems("s:plink_A,p:plink_C", playoff=False) == []
    assert any("unknown prefix" in p for p in link_map_problems(good + ",x:plink_E"))
    assert any("both" in p for p in link_map_problems("s:plink_A,o:plink_A,p:plink_C"))
    assert any("no p: link" in p for p in link_map_problems("s:plink_A,o:plink_B"))


def test_the_playoff_week_is_one_number_everywhere() -> None:
    """The intake's switch is the join page's rule (firstWeek >= 13) and the
    economics model's; three copies, held equal."""
    from run.economics import PLAYOFF_FROM_WEEK as modelled
    page = (ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    found = re.search(r"const PLAYOFF_FROM_WEEK = (\d+);", page)
    assert found and int(found.group(1)) == PLAYOFF_FROM_WEEK == modelled


def test_the_playoff_switch_is_read_from_the_schedule() -> None:
    """Never hardcoded: the first kickoff of the week before PLAYOFF_FROM_WEEK
    in the season the purchase belongs to — 2026's Week 12 opens Wed Nov 25,
    8:00 PM ET."""
    from run.solo import CACHE_DIR, week_first_kickoff
    expected = week_first_kickoff(CACHE_DIR, "2026", PLAYOFF_FROM_WEEK - 1)
    if expected is None:
        pytest.skip("the 2026 schedule is not cached here")
    week8 = int(datetime(2026, 10, 27, 15, tzinfo=timezone.utc).timestamp())
    assert intake.playoff_opens(week8) == expected
    assert expected == datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc)


OPENS = datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc)


def _playoff_session(when: datetime, sid: str = "cs_po") -> dict:
    session = _session(REF, sid=sid, link=PLAYOFF_LINK, created=int(when.timestamp()))
    session.update(mode="payment", payment_intent="pi_playoff1")
    return session


def test_an_early_playoff_purchase_is_served_and_reported(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Reproduced (SEC-3, playoff_tier.py): a paid session through the $19
    link created Oct 27 2026 (Week 8), under LAUNCH.md's s:,s:,p: map, went
    through the sweep as 'problems: []', 'plan: season', entitled until
    2027-01-24 — identical to a $29 purchase. Now, under o:, it is still a
    season row (they paid; a refusal would strand them) and the run reports
    PLAYOFF-EARLY and exits 1 on every run that sweeps the session (three
    days past the newest one). It is not persisted like PAID-UNATTRIBUTED: the
    buyer is served, and no workflow can pass --clear-unresolved, so a
    remembered one would keep the hourly cron red for good. A purchase after
    the switch is quiet."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS_2026)
    monkeypatch.setattr(intake, "playoff_opens", lambda created, cache=None: OPENS)
    stripe["sessions"] = [_playoff_session(datetime(2026, 10, 27, 15, tzinfo=timezone.utc))]
    assert _run(tmp_path, "--no-mail") == 1
    err = capsys.readouterr().err
    assert "PLAYOFF-EARLY session cs_po" in err and "needs a human" in err
    [row] = _registry(tmp_path)
    assert row["plan"] == "season" and row["subscription_ids"] == ["pi_playoff1"]
    [logged] = intake.load_log(tmp_path / intake.SIGNUP_LOG_NAME)
    assert logged.playoff is True and logged.plan == "season"
    assert _run(tmp_path, "--no-mail") == 1, "the next sweep of it was green"
    assert "PLAYOFF-EARLY session cs_po" in capsys.readouterr().err
    state = json.loads((tmp_path / intake.STATE_NAME).read_text())
    assert not any(p.startswith("PLAYOFF-EARLY") for p in state["unresolved"])
    stripe["sessions"] = []                     # the sweep window moved past it
    assert _run(tmp_path, "--no-mail") == 0
    assert len(_registry(tmp_path)) == 1, "the early buyer stopped being served"
    capsys.readouterr()

    late = tmp_path / "late"
    stripe["sessions"] = [_playoff_session(datetime(2026, 11, 26, 2, tzinfo=timezone.utc))]
    assert _run(late, "--no-mail") == 0
    assert "PLAYOFF-EARLY" not in capsys.readouterr().err
    # An unreadable schedule is never read as "on time".
    signups, _newest, problems = intake.sweep(
        "sk", None, parse_link_plans(LINKS_2026), promote=False,
        playoff=playoff_links(LINKS_2026), opens=lambda created: None)
    assert signups[0].playoff and any(p.startswith("PLAYOFF-EARLY") for p in problems)


def test_the_intake_says_so_when_the_19_link_sits_under_s(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The reproduction's map itself (SEC-3): with LAUNCH.md's
    's:plink_ROS29,s:plink_PO19,p:plink_LP69' the early purchase is invisible
    by construction, so the intake names the map's mistake on every run."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},s:{PLAYOFF_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_session(REF)]
    _run(tmp_path, "--no-mail")
    assert "lists 2 s: links" in capsys.readouterr().err
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS_2026)
    _run(tmp_path, "--no-mail")
    assert "s: links" not in capsys.readouterr().err


def test_an_ordinary_season_log_line_is_unchanged(tmp_path, stripe, directory) -> None:
    """The playoff flag is logged only when true: the $29 buyer's log line is
    the one it always was, so nothing reading the append-only log moves."""
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path, "--no-mail") == 0
    line = (tmp_path / intake.SIGNUP_LOG_NAME).read_text().strip()
    assert "playoff" not in json.loads(line)


def test_a_playoff_purchase_is_welcomed_as_the_playoff_pass() -> None:
    """Contract C4: an o: purchase calls welcome_message(..., playoff=True),
    which names the Playoff Pass and its $19 price in place of the
    Rest-of-Season Pass. The keyword belongs to render/welcome.py (the report
    branch); this fails LOUDLY until it exists — never a $19 buyer told they
    bought the $29 pass."""
    from render.welcome import PLAYOFF_PRICE, welcome_message
    assert "playoff" in inspect.signature(welcome_message).parameters, \
        "render.welcome.welcome_message has no `playoff` keyword (contract C4, report branch)"
    signup = intake.RosterSignup(email="fan@example.com", ref=REF, plan="season",
                                 seen_at="1793026800", subscription_id="pi_playoff1",
                                 playoff=True)
    message = intake._welcome(signup, "2026")
    assert "Playoff Pass" in message.text and PLAYOFF_PRICE in message.text
    plain = intake._welcome(intake.RosterSignup(
        email="fan@example.com", ref=REF, plan="season", seen_at="1793026800",
        subscription_id="pi_season1"), "2026")
    assert "Playoff Pass" not in plain.text


# --------------------------------------------------------------------- #
# OPS-1 — the words above Stripe's Pay button
# --------------------------------------------------------------------- #

def _paylink():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_paylink_final", ROOT / "infra" / "stripe_paylink_text.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_pay_button_script_writes_every_2026_link(monkeypatch) -> None:
    """Reproduced (OPS-1): STRIPE_PAYMENT_LINKS='s:plink_NEW_29,s:plink_NEW_19,
    p:plink_NEW_69' printed 'No payment link given for: monthly' and exited 1
    before asking for the key — the inversion to {plan: link} kept only the
    $19 link, then monthly was required. Now one write and read-back per LINK:
    s:,o:,p: writes all three (the $19 link with the season text), m: is
    optional, and the old shape is refused with the right hint before any
    key is asked for."""
    module = _paylink()
    writes = []
    stored = {}

    def fake_call(url, key, form=None):
        link = url.rsplit("/", 1)[1]
        if form:
            writes.append(link)
            stored[link] = form
            return {}
        form = stored[link]
        return {"custom_text": {
                    "submit": {"message": form["custom_text[submit][message]"]},
                    "terms_of_service_acceptance": {
                        "message": form["custom_text[terms_of_service_acceptance][message]"]}},
                "consent_collection": {"terms_of_service": "required"}}
    monkeypatch.setattr(module, "_call", fake_call)
    monkeypatch.setattr(module.getpass, "getpass", lambda prompt: "rk_test_" + "A1b2C3d4E5" * 3)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", "s:plink_NEW_29,o:plink_NEW_19,p:plink_NEW_69")
    assert module.main() == 0
    assert writes == ["plink_NEW_29", "plink_NEW_19", "plink_NEW_69"]
    assert stored["plink_NEW_19"]["custom_text[submit][message]"] == module.ONE_TIME
    assert stored["plink_NEW_69"]["custom_text[submit][message]"] == module.MESSAGES["league_pass"]
    assert all(stored[link]["customer_creation"] == "always" for link in writes)

    asked = []
    monkeypatch.setattr(module.getpass, "getpass", lambda prompt: asked.append(prompt) or "")
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", "s:plink_NEW_29,s:plink_NEW_19,p:plink_NEW_69")
    with pytest.raises(SystemExit) as refused:
        module.main()
    assert "o:" in str(refused.value) and "monthly" not in str(refused.value).split("Expected")[0]
    assert not asked, "the key was asked for before the map was checked"
    with_monthly = module.targets("s:plink_A,o:plink_B,p:plink_C,m:plink_D")
    assert [plan for _link, plan in with_monthly] == ["season", "season", "league_pass", "monthly"]


def test_the_one_payment_text_carries_the_refund_term_and_fits() -> None:
    """OPS-1 / owner rule: the refund term sits beside every price, and the
    Pay button is a price. The sentence is terms.html §5's window, and every
    message fits Stripe's 1,200 characters."""
    module = _paylink()
    refund = "Full refund, no questions, until your second weekly report's week kicks off."
    assert module.REFUND == refund
    assert module.ONE_TIME.endswith(refund) and module.MESSAGES["league_pass"].endswith(refund)
    assert "for every manager in your league who claims a seat" in module.MESSAGES["league_pass"]
    for plan in module.MESSAGES:
        assert len(module.MESSAGES[plan]) <= module.STRIPE_TEXT_LIMIT == 1200
        assert len(module.TOS_MESSAGES[plan]) <= module.STRIPE_TEXT_LIMIT
    from test_promises_legal import _visible
    assert "until your second weekly report's week kicks off" in _visible("terms.html")


def test_the_launch_check_reads_the_link_map(monkeypatch) -> None:
    """The launch check holds the map to the same shape (SEC-3 / OPS-1): the
    old s:,s:,p: is an OWNER line naming o:, the 2026 shape passes, and with
    no map in the shell it says what to check by hand."""
    import run.launch_check as lc
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", "s:plink_A,s:plink_B,p:plink_C")
    gates = {g.name: g for g in lc.check_link_map()}
    words = gates["The payment-link map names each pass under its own prefix"]
    assert words.status == "OWNER" and "o:" in words.detail
    assert gates["The words above Stripe's Pay button fit and carry the refund term"].status == "PASS"
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", "s:plink_A,o:plink_B,p:plink_C")
    assert all(g.status == "PASS" for g in lc.check_link_map())
    monkeypatch.delenv("STRIPE_PAYMENT_LINKS")
    [_, unset] = lc.check_link_map()
    assert unset.status == "OWNER" and "isn't in this shell" in unset.detail


# --------------------------------------------------------------------- #
# OPS-5 — a cron key missing a read permission goes red before Tuesday
# --------------------------------------------------------------------- #

def test_a_key_missing_payment_intents_read_turns_the_intake_red(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Reproduced (OPS-5, the verifier's oldkey.py): with _stripe_get 403ing
    on the payment_intent expansion, dispute_alarm printed 'could not be
    checked this run' and the intake stayed GREEN — the buyer registered and
    welcomed — while Tuesday's entitlement read (the same call) found nobody
    paid and mailed nobody. A 403 there now fails the intake and names the
    permissions to add; a network failure stays a note."""
    import run.subscriptions as subscriptions
    from run.subscriptions import SubscriptionError
    sends = _capture_sends(monkeypatch, tmp_path)
    real = subscriptions._stripe_get

    def get(url, key):
        if "payment_intent" in url:
            raise SubscriptionError(
                "Stripe returned HTTP 403. Response: Having the 'rak_payment_intent_read' "
                "permission would allow this request to continue.", status=403)
        return real(url, key)
    monkeypatch.setattr(subscriptions, "_stripe_get", get)
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path) == 1
    err = capsys.readouterr().err
    assert "MISSING A PERMISSION" in err and "rak_payment_intent_read" in err
    assert "Payment Intents: Read" in err and "Charges: Read" in err
    assert [m.to for m in sends] == ["fan@example.com"], "the buyer must still be welcomed"
    assert [r["email"] for r in _registry(tmp_path)] == ["fan@example.com"]

    def offline(url, key):
        raise SubscriptionError("could not reach Stripe: timed out")
    monkeypatch.setattr(subscriptions, "load_paid_from_stripe",
                        lambda key: offline("", key))
    assert intake.dispute_alarm("sk") is False


def test_stripes_http_status_rides_on_the_error(monkeypatch) -> None:
    """The 403 is read off Stripe's own answer, never guessed from text."""
    import io
    import urllib.error
    import urllib.request

    import run.subscriptions as subscriptions

    def denied(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b'{"error":{"type":"permission_error"}}'))
    monkeypatch.setattr(urllib.request, "urlopen", denied)
    with pytest.raises(subscriptions.SubscriptionError) as raised:
        subscriptions._stripe_get("https://api.stripe.com/v1/x", "rk_test_x")
    assert raised.value.status == 403 and "rk_test_x" not in str(raised.value)
    assert subscriptions.SubscriptionError("plain").status is None


# --------------------------------------------------------------------- #
# SEC-4 — the dead-secret alarm needs evidence a stranger cannot supply
# --------------------------------------------------------------------- #

PASS = intake.PassInfo(payer="commish@example.com", pass_id=PASS_SUB, league_size=12,
                       customer="cus_commish01", entitled=True)


def test_a_forged_seat_claim_no_longer_raises_the_rotation_alarm() -> None:
    """Reproduced (SEC-4, forged_seat_alarm.py): sweep_seats with one entitled
    pass and ONE claim carrying '0123456789abcdef0123' gave links_dead True and
    'SEAT LINKS MATCH NO PASS', so every hourly run went red for 14 days and
    told the operator to look for a secret rotation that never happened. Now
    the claim is an ordinary unmatched one (the capped note), and the alarm
    needs the intake's own record that the secret moved."""
    forged = {"email": "x@example.net", "ref": SEAT_REF,
              "pass_token": "0123456789abcdef0123", "received_at": _hours_ago(1)}
    swept = intake.sweep_seats([forged], [PASS], None, "the-secret")
    assert not swept.links_dead
    assert not any("SEAT LINKS MATCH NO PASS" in p for p in swept.problems)
    assert [r["email"] for r in swept.unmatched] == ["x@example.net"]
    real = dict(forged, pass_token=seat_token("commish@example.com", "old", PASS_SUB))
    dead = intake.sweep_seats([real], [PASS], None, "new", rotated=True)
    assert dead.links_dead and dead.unmatched == []


def test_a_rotation_is_read_from_the_intakes_own_fingerprint() -> None:
    """seat_key_rotated: no fingerprint is a first sighting; the same secret
    is quiet; a new secret with the old one kept in UPDATE_SECRET_PREVIOUS is
    a rotation done right (and the new one is stored); a new secret with the
    old one nowhere is the OPS-R10 accident, and the old fingerprint stays
    until it is put back. The fingerprint never is the secret."""
    old, new = intake.seat_key_check("old"), intake.seat_key_check("new")
    assert re.fullmatch(r"[0-9a-f]{16}", old) and old != new and "old" not in old
    assert intake.seat_key_check("") is None
    assert intake.seat_key_rotated(None, "old") == (False, old)
    assert intake.seat_key_rotated(old, "old") == (False, old)
    assert intake.seat_key_rotated(old, "new", "x, old") == (False, new)
    assert intake.seat_key_rotated(old, "new") == (True, old)
    assert intake.seat_key_rotated(old, "") == (True, old)


def test_the_intake_alarms_on_a_real_rotation_only(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """End to end: a forged claim on a fresh state stays green and stores the
    fingerprint; the links' secret replaced with the old one nowhere goes red;
    the old value put in UPDATE_SECRET_PREVIOUS goes green and the new
    fingerprint is stored."""
    import run.intake as _intake
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    monkeypatch.setenv("FORM_ENDPOINT", "https://forms.example/")
    monkeypatch.setenv("UPDATE_SECRET", "old")
    stripe["sessions"] = [_pass_session()]
    forged = {"email": "x@example.net", "ref": SEAT_REF, "kind": "seat",
              "pass_token": "0123456789abcdef0123", "received_at": _hours_ago(1)}
    monkeypatch.setattr(_intake, "fetch_seats", lambda *a, **k: [forged])
    assert _run(tmp_path, "--no-mail") == 0
    state = json.loads((tmp_path / intake.STATE_NAME).read_text())
    assert state[intake.SEAT_KEY_CHECK] == intake.seat_key_check("old")

    real = dict(forged, pass_token=seat_token("commish@example.com", "old", PASS_SUB))
    monkeypatch.setattr(_intake, "fetch_seats", lambda *a, **k: [real])
    monkeypatch.setenv("UPDATE_SECRET", "new")
    assert _run(tmp_path, "--no-mail") == 1
    assert "SEAT LINKS MATCH NO PASS" in capsys.readouterr().err
    monkeypatch.setenv("UPDATE_SECRET_PREVIOUS", "old")
    assert _run(tmp_path, "--no-mail") == 0
    state = json.loads((tmp_path / intake.STATE_NAME).read_text())
    assert state[intake.SEAT_KEY_CHECK] == intake.seat_key_check("new")


# --------------------------------------------------------------------- #
# appsec — the sealed state's iteration count
# --------------------------------------------------------------------- #

def test_a_sealed_blob_cannot_name_a_huge_iteration_count(monkeypatch) -> None:
    """The header's PBKDF2 count is read before the tag can be checked, so a
    damaged or planted blob naming 4,294,967,295 iterations made the job spin
    for hours before the MAC rejected it. Now anything above MAX_ITERATIONS is
    refused before a single round runs; a real blob still opens."""
    import run.statebox as sb
    if not shutil.which("openssl"):
        pytest.skip("openssl not available")
    secret = "k" * 40
    blob = sb.encrypt(b"registry", secret, sb.MIN_ITERATIONS)
    assert sb.decrypt(blob, secret) == b"registry"
    at = len(sb.MAGIC)
    planted = blob[:at] + (2 ** 32 - 1).to_bytes(4, "big") + blob[at + 4:]
    monkeypatch.setattr(sb, "_keys", lambda *a: pytest.fail("PBKDF2 ran on a planted count"))
    with pytest.raises(sb.SealError):
        sb.decrypt(planted, secret)
    over = blob[:at] + (sb.MAX_ITERATIONS + 1).to_bytes(4, "big") + blob[at + 4:]
    with pytest.raises(sb.SealError):
        sb.decrypt(over, secret)
    assert sb.ITERATIONS <= sb.MAX_ITERATIONS
