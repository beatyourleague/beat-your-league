"""Pre-launch review, the form Worker and everything that reads it (Oct 2026).

Each test names the finding it pins and carries its reproduction:

- APPSEC-1 — forged seat claims were unlimited outbound mail. 150 POSTs to one
  inbox's +aliases became 99 "no pass" notes, the provider's 100-a-day free
  tier ran out, and the buyer's first report was refused — exit 0.
- APPSEC-2 / contract C3 — anyone who knew a League Pass buyer's address took
  every seat on the pass by typing it, and the replies said whether an
  address had bought one. Seats now come only through each pass's own link.
- APPSEC-3 / INFRA-03 — the Worker took a POST from any origin, stored any
  kind, kept every row 400 days, walked every row on every read, threw with
  no CORS on a non-ASCII row, and a failed read stopped the intake from
  registering anybody who paid.
- SEC-06 — a free-report request posted straight to the Worker was built and
  mailed while the site's free-report button was switched off.
- Contract C1 — the visit counter: POST /e, always 204, Analytics Engine only.
- Critique #1 — a mistyped buyer address bounced, was logged as sent, and
  nothing ever read the bounce.
- Critique #2 — a lost chargeback is not a refund in Stripe's data, so the
  buyer kept every report.
- Critique #3 — the free report was limited per address only, so the same
  roster could be had every week from another inbox.

The Worker tests need node and skip without it; CI installs it.
"""

from __future__ import annotations

import json
import urllib.parse
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.intake as intake
from run.updates import seat_token

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "infra" / "form-worker.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not available")
SITE = "https://x.test"


# --------------------------------------------------------------------- #
# a node harness around the real Worker
# --------------------------------------------------------------------- #

# A KV namespace that honours `prefix` and paging like Cloudflare's, and can
# be told to fail.
FAKE_KV = """
function fakeKV({ failPut = false, failList = false, page = 1000 } = {}) {
  const store = new Map();
  return {
    store,
    puts: 0,
    lists: 0,
    async put(key, value, opts) {
      if (failPut) throw new Error("KV put failed: quota");
      this.puts += 1;
      store.set(key, { value, opts });
    },
    async list({ prefix = "", cursor } = {}) {
      if (failList) throw new Error("KV list failed");
      this.lists += 1;
      const names = [...store.keys()].filter((k) => k.startsWith(prefix)).sort();
      const start = cursor ? Number(cursor) : 0;
      const slice = names.slice(start, start + page);
      const done = start + page >= names.length;
      return { keys: slice.map((name) => ({ name, metadata: store.get(name).opts.metadata })),
               list_complete: done, cursor: done ? undefined : String(start + page) };
    },
    async delete(key) { store.delete(key); },
  };
}
const post = (env, body, headers = { Origin: "https://x.test" }, path = "/") =>
  worker.fetch(new Request("https://w.test" + path, {
    method: "POST", headers: { "Content-Type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body) }), env);
const read = async (env, query = "") => {
  const res = await worker.fetch(new Request("https://w.test/" + query,
    { headers: { Authorization: "Bearer k" } }), env);
  return { status: res.status, rows: res.status === 200 ? await res.json() : null };
};
"""


def _node(tmp_path: Path, body: str):
    """Run ``body`` as an ES module with the real Worker imported as `worker`."""
    (tmp_path / "worker.mjs").write_text(WORKER.read_text(encoding="utf-8"),
                                         encoding="utf-8")
    harness = tmp_path / "harness.mjs"
    harness.write_text(
        'import worker from "./worker.mjs";\n' + FAKE_KV +
        "const logs = [];\nconsole.log = (...a) => logs.push(a.join(' '));\n"
        "const result = await (async () => {\n" + body + "\n})();\n"
        "process.stdout.write(JSON.stringify({ result, logs }));\n",
        encoding="utf-8")
    done = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=60, cwd=tmp_path)
    if done.returncode:
        raise AssertionError(f"node failed:\n{done.stderr}")
    return json.loads(done.stdout)["result"]


def _rows_fn(name: str) -> str:
    """One top-level function of the Worker's source, for running alone."""
    src = WORKER.read_text(encoding="utf-8")
    start = src.index(f"function {name}(")
    end = src.index("\n}\n", start) + 3
    return src[start:end]


# --------------------------------------------------------------------- #
# APPSEC-3 / INFRA-03 — the Worker's own abuse control
# --------------------------------------------------------------------- #

@needs_node
def test_a_post_must_come_from_the_site_or_carry_the_read_key(tmp_path) -> None:
    """Reproduced (csrf.mjs, flood.mjs): text/plain from Origin evil.example
    got 200 and a row written, and so did curl with no Origin at all — and
    with SITE_ORIGIN unset every answer carried `Access-Control-Allow-Origin:
    *`. Now a POST needs the site's Origin (SITE_ORIGIN or the home domain) or
    the read key (the operator's `make roster-update`); every refusal still
    carries CORS for the site, never `*`."""
    got = _node(tmp_path, """
      const kv = fakeKV();
      const env = { ROWS: kv, SITE_ORIGIN: "https://x.test", FORM_API_KEY: "k" };
      const row = { kind: "waitlist", email: "a@example.com" };
      const out = {};
      for (const [name, headers] of Object.entries({
        site: { Origin: "https://x.test" },
        home: { Origin: "https://beatyourleague.com" },
        evil: { Origin: "https://evil.example" },
        none: {},
        evilWithKey: { Origin: "https://evil.example", Authorization: "Bearer k" },
        noneWithKey: { Authorization: "Bearer k" },
        noneWrongKey: { Authorization: "Bearer kk" },
      })) {
        const res = await post(env, row, headers);
        out[name] = [res.status, res.headers.get("Access-Control-Allow-Origin")];
      }
      const unset = await post({ ROWS: fakeKV() }, row, { Origin: "https://evil.example" });
      out.unsetOrigin = [unset.status, unset.headers.get("Access-Control-Allow-Origin")];
      out.puts = kv.puts;
      return out;
    """)
    assert got["site"] == [200, SITE]
    assert got["home"] == [200, "https://beatyourleague.com"]
    assert got["evil"] == [403, SITE] and got["none"] == [403, SITE]
    assert got["noneWrongKey"][0] == 403
    assert got["evilWithKey"][0] == 200 and got["noneWithKey"][0] == 200
    assert got["unsetOrigin"] == [403, "https://beatyourleague.com"], \
        "with SITE_ORIGIN unset the Worker must fail closed, never answer *"
    assert got["puts"] == 4


@needs_node
def test_unknown_kinds_and_typed_payer_seats_are_refused(tmp_path) -> None:
    """An unknown kind used to be stored as a seat. And a seat naming its pass
    by a typed buyer address (`covered_by`) is no longer a way in (contract
    C3), so the Worker refuses it rather than storing the address."""
    got = _node(tmp_path, """
      const kv = fakeKV();
      const env = { ROWS: kv, SITE_ORIGIN: "https://x.test" };
      const statuses = [];
      for (const body of [
        { kind: "nonsense", email: "a@example.com", ref: "s3-abc", pass_token: "0123456789abcdef0123" },
        { email: "a@example.com", ref: "s3-abc", pass_token: "0123456789abcdef0123" },
        { kind: "seat", email: "a@example.com", ref: "s3-abc", covered_by: "buyer@example.com" },
        { kind: "seat", email: "a@example.com", ref: "s3-abc",
          pass_token: "0123456789abcdef0123", covered_by: "buyer@example.com" },
      ]) statuses.push((await post(env, body)).status);
      return { statuses, stored: [...kv.store.values()].map((v) => v.opts.metadata) };
    """)
    assert got["statuses"] == [400, 400, 400, 200]
    [seat] = got["stored"]
    assert "covered_by" not in seat and seat["pass_token"] == "0123456789abcdef0123"


@needs_node
def test_rows_sit_under_their_kind_and_a_reader_lists_only_what_it_asks(tmp_path) -> None:
    """Reproduced (getcpu.mjs): every GET walked every row of every kind —
    30,000 rows meant 30 list() calls and ~15 ms CPU per read, on a free tier
    of 1,000 list operations and 10 ms a request, and two hourly readers. A
    waitlist flood now never touches the intake's read: rows sit under a kind
    prefix and GET ?kinds= lists only those prefixes. Unknown kinds in the
    filter are refused; the answer is oldest first whatever the key shape."""
    got = _node(tmp_path, """
      const kv = fakeKV({ page: 2 });
      const env = { ROWS: kv, SITE_ORIGIN: "https://x.test", FORM_API_KEY: "k",
                    TRIAL_OPEN: "true" };
      for (let i = 0; i < 9; i += 1) await post(env, { kind: "waitlist", email: `w${i}@example.com` });
      await post(env, { kind: "seat", email: "m@example.com", ref: "s3-abc",
                        pass_token: "0123456789abcdef0123" });
      await new Promise((r) => setTimeout(r, 5));
      await post(env, { kind: "confirm", code: "0123456789abcdef01234567" });
      await post(env, { kind: "trial", email: "t@example.com", ref: "s3-abc" });
      const keys = [...kv.store.keys()];
      kv.lists = 0;
      const intakeRead = await read(env, "?kinds=seat,update,update_request,confirm");
      const intakeLists = kv.lists;
      const all = await read(env);
      const bad = await read(env, "?kinds=seat,bogus");
      return { keys, intake: intakeRead.rows.map((r) => r.kind), intakeLists,
               all: all.rows.length, bad: bad.status,
               stamps: intakeRead.rows.map((r) => r.received_at) };
    """)
    assert all(k.split(":", 1)[0] in ("waitlist", "seat", "confirm", "trial")
               for k in got["keys"])
    assert got["intake"] == ["seat", "confirm"], "the intake read walked other kinds"
    assert got["intakeLists"] == 4, "one list per asked kind (each fits one page)"
    assert got["all"] == 12 and got["bad"] == 400
    assert got["stamps"] == sorted(got["stamps"])


@needs_node
def test_waitlist_and_trial_rows_are_one_per_mailbox_a_day_and_nothing_else_is(tmp_path) -> None:
    """Reproduced: the same waitlist address posted twice was stored twice,
    and 5,000/5,000 flood rows were accepted from one client. A waitlist or
    free-report row is now ONE per (kind, canonical mailbox, UTC day) — a
    repeat, a +alias or a dotted Gmail spelling overwrites. Never a seat
    claim, roster request or confirmation: overwriting by address would let a
    stranger's request replace the real one and move the stamp its emailed
    code is bound to (the Sep 29 defect)."""
    got = _node(tmp_path, """
      const kv = fakeKV();
      const env = { ROWS: kv, SITE_ORIGIN: "https://x.test", TRIAL_OPEN: "true" };
      for (const email of ["john.doe@gmail.com", "johndoe+x@googlemail.com", "JohnDoe@gmail.com"]) {
        await post(env, { kind: "waitlist", email });
        await post(env, { kind: "trial", email, ref: "s3-abc" });
      }
      await post(env, { kind: "waitlist", email: "other@example.com" });
      for (let i = 0; i < 2; i += 1) {
        await post(env, { kind: "seat", email: "m@example.com", ref: "s3-abc",
                          pass_token: "0123456789abcdef0123" });
        await post(env, { kind: "update_request", email: "m@example.com", ref: "s3-abc" });
        await post(env, { kind: "confirm", code: "0123456789abcdef01234567" });
      }
      const count = (kind) => [...kv.store.keys()].filter((k) => k.startsWith(kind + ":")).length;
      const day = new Date().toISOString().slice(0, 10);
      return { waitlist: count("waitlist"), trial: count("trial"), seat: count("seat"),
               update_request: count("update_request"), confirm: count("confirm"),
               dated: [...kv.store.keys()].filter((k) => k.startsWith("waitlist:"))
                        .every((k) => k.startsWith(`waitlist:${day}:`)),
               noAddress: [...kv.store.keys()].every((k) => !k.includes("@")) };
    """)
    assert got["waitlist"] == 2 and got["trial"] == 1
    assert got["seat"] == 2 and got["update_request"] == 2 and got["confirm"] == 2
    assert got["dated"] and got["noAddress"]


@needs_node
def test_the_worker_and_the_intake_canonicalise_a_mailbox_the_same_way(tmp_path) -> None:
    """The Worker's day-key and the Python caps must agree about which
    addresses are one inbox, or a flood folds in one place and not the
    other."""
    from run.trials import canonical_email
    cases = ["John.Doe+tag@Gmail.com", "johndoe@googlemail.com", "a.b+c+d@example.com",
             " Spaced@Example.COM ", "o'brien@gmail.com", "josé@example.com", "no-at-sign",
             "x+@gmail.com"]
    got = _node(tmp_path, _rows_fn("canonicalEmail") +
                f"\nreturn {json.dumps(cases)}.map(canonicalEmail);")
    assert got == [canonical_email(c) for c in cases]


@needs_node
def test_sizes_are_bytes_and_storage_failures_answer_503_with_cors(tmp_path) -> None:
    """Reproduced (meta.mjs): size checks counted UTF-16 characters, so a
    639-character row of non-ASCII text (1,119 bytes) passed them and then
    threw inside put() against KV's 1,024-byte metadata limit — a 1101 with no
    CORS header, which the page reads as "check your connection". Same for a
    quota-exceeded put. Now bytes are measured, a declared oversize body is
    refused unread, and a KV failure is a JSON 503 with the site's CORS."""
    got = _node(tmp_path, """
      const env = { ROWS: fakeKV(), SITE_ORIGIN: "https://x.test", FORM_API_KEY: "k" };
      const wide = { kind: "seat", email: "中".repeat(240) + "@x.co", ref: "a".repeat(200),
                     pass_token: "0123456789abcdef0123", via: "reply-kit" };
      const big = await post(env, wide);
      const declared = await post(env, { kind: "waitlist", email: "a@example.com" },
                                  { Origin: "https://x.test", "Content-Length": "999999" });
      const putFails = await post({ ROWS: fakeKV({ failPut: true }), SITE_ORIGIN: "https://x.test" },
                                  { kind: "waitlist", email: "a@example.com" });
      const listFails = await worker.fetch(new Request("https://w.test/",
        { headers: { Authorization: "Bearer k" } }),
        { ROWS: fakeKV({ failList: true }), FORM_API_KEY: "k" });
      return { big: [big.status, big.headers.get("Access-Control-Allow-Origin")],
               declared: declared.status,
               putFails: [putFails.status, putFails.headers.get("Access-Control-Allow-Origin"),
                          await putFails.json()],
               listFails: listFails.status, wideChars: JSON.stringify(wide).length };
    """)
    assert got["wideChars"] < 1000, "the row must pass a CHARACTER count to prove the point"
    assert got["big"] == [413, SITE]
    assert got["declared"] == 413
    assert got["putFails"][:2] == [503, SITE] and got["putFails"][2]["error"]
    assert got["listFails"] == 503


@needs_node
def test_a_free_report_request_is_refused_unless_the_worker_says_free_reports_are_open(
        tmp_path) -> None:
    """SEC-06, reproduced: `{kind:"trial"}` posted straight to the Worker was
    stored — and then built and mailed — while the site's button was off. The
    Worker now stores one only while its own TRIAL_OPEN is "true"."""
    got = _node(tmp_path, """
      const body = { kind: "trial", email: "victim@example.com", ref: "s3-abc" };
      const closed = fakeKV();
      const shut = await post({ ROWS: closed, SITE_ORIGIN: "https://x.test" }, body);
      const shutFalse = await post({ ROWS: closed, SITE_ORIGIN: "https://x.test",
                                     TRIAL_OPEN: "false" }, body);
      const open = fakeKV();
      const ok = await post({ ROWS: open, SITE_ORIGIN: "https://x.test", TRIAL_OPEN: "true" }, body);
      return { shut: shut.status, shutFalse: shutFalse.status, closedPuts: closed.puts,
               ok: ok.status, openPuts: open.puts };
    """)
    assert got == {"shut": 403, "shutFalse": 403, "closedPuts": 0, "ok": 200, "openPuts": 1}


@needs_node
def test_the_join_page_says_free_reports_are_closed_instead_of_blaming_the_address(
        tmp_path) -> None:
    """Reproduced (pre-launch review): the Worker answers every trial row 403
    {"error":"free reports are not open"} while its TRIAL_OPEN is unset, try
    mode was gated only on FORM_ENDPOINT, and the page mapped any 4xx to "We
    couldn't accept that address — check it for typos." Once FORM_ENDPOINT
    was wired, every free-report request got that false sentence. The page
    now has its own TRIAL_OPEN (the landing's twin; the launch check holds
    them together) and reads the Worker's reason instead of guessing from the
    status. Run here with the page's own functions against a real Response."""
    page = (ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    assert "const TRIAL_OPEN = false;" in page
    assert "if (!FORM_ENDPOINT || !TRIAL_OPEN) {" in page
    assert '"free reports are not open"' in WORKER.read_text(encoding="utf-8")
    start = page.index("function refusedBy(response)")
    end = page.index("\n}\n", page.index("async function refusedFrom(")) + 3
    (tmp_path / "page.mjs").write_text(page[start:end] + """
const said = async (status, body) => notSentWords(await refusedFrom(
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));
const out = [await said(403, { error: "free reports are not open" }),
             await said(400, { error: "bad row" }),
             notSentWords(refusedBy(new Response("x", { status: 400 }))),
             notSentWords(new Error("network"))];
process.stdout.write(JSON.stringify(out));
""", encoding="utf-8")
    done = subprocess.run([NODE, str(tmp_path / "page.mjs")], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    closed, bad, plain, network = json.loads(done.stdout)
    assert closed.startswith("Free reports aren't open just yet") and "typos" not in closed
    assert "typos" in bad and "typos" in plain and "connection" in network


@needs_node
def test_the_update_links_origin_tag_survives_the_page_and_the_worker(tmp_path) -> None:
    """Reproduced (APPSEC-5): `public_update_url` emits `&o=` as 12 hex
    (run/updates.py ORIGIN_TAG_LENGTH = 12), but the join page's UPDATE_ORIGIN
    and the Worker's SLUG accepted only 10, so `replaces` was dropped from
    every update_request and an address holding two teams had the wrong one
    picked. End to end now: the link's tag passes the page's own regex, the
    Worker stores it, and the intake's validate_requests names the team the
    report came from. The operator's kind:"update" keeps the raw 10-hex slug."""
    import re
    from types import SimpleNamespace

    from run import updates
    from run.refs import encode_roster
    from test_promises_engine import PLAYERS, SLOTS, _row as reg_row
    link = updates.public_update_url("https://x.test", "s", "https://w.test",
                                     roster=SimpleNamespace(scoring="ppr", league_size=12,
                                                            slots=SLOTS, slug="bbbbbbbbbb"))
    tag = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)["o"][0]
    assert len(tag) == updates.ORIGIN_TAG_LENGTH == 12
    page = (ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    found = re.search(r"const UPDATE_ORIGIN = UPDATE_MODE && (/\^[^/]+\$/)\.test", page)
    assert found, "the join page's UPDATE_ORIGIN test moved"
    half = encode_roster("season", "half_ppr", list(SLOTS), list(PLAYERS))
    got = _node(tmp_path, f"""
      const kv = fakeKV();
      const env = {{ ROWS: kv, SITE_ORIGIN: "https://x.test", FORM_API_KEY: "k" }};
      const pageAccepts = {found.group(1)}.test({json.dumps(tag)});
      await post(env, {{ kind: "update_request", email: "fan@example.com",
                         ref: {json.dumps(half)}, replaces: {json.dumps(tag)} }});
      const operator = await post(env, {{ kind: "update", email: "fan@example.com",
                                          ref: {json.dumps(half)}, token: "0".repeat(20),
                                          replaces: {json.dumps(tag)} }});
      return {{ pageAccepts, rows: (await read(env)).rows, operator: operator.status }};
    """)
    assert got["pageAccepts"] is True
    [stored] = got["rows"]
    assert stored["replaces"] == tag
    assert got["operator"] == 400, "the operator's update names the raw 10-hex origin"
    a = encode_roster("season", "ppr", list(SLOTS), list(PLAYERS))
    two = [reg_row("fan@example.com", a, "aaaaaaaaaa"),
           reg_row("fan@example.com", a, "bbbbbbbbbb", players=PLAYERS[:-1])]
    now = datetime.fromisoformat(stored["received_at"].replace("Z", "+00:00")) \
        + timedelta(minutes=5)
    [request] = updates.validate_requests([stored], two, None, "s", now=now)[0]
    assert request.replaces == "bbbbbbbbbb"


@needs_node
def test_a_waitlist_row_without_a_roster_never_erases_one_with(tmp_path) -> None:
    """Reproduced (pre-launch review): waitlist rows were keyed one per
    (kind, mailbox, UTC day), so the landing's email-only capture posted
    after join's closed-checkout row (contract C6, which carries the roster)
    overwrote it: KV held only {"email":"ab@gmail.com"} and the launch email
    could no longer bring the roster back. A row carrying a roster has a key
    of its own; run/waitlist.saved_refs still finds it, and the mailbox is
    still mailed once."""
    from run.waitlist import saved_refs, waitlist_addresses
    from test_intake_sync import SEAT_REF
    got = _node(tmp_path, f"""
      const kv = fakeKV();
      const env = {{ ROWS: kv, SITE_ORIGIN: "https://x.test", FORM_API_KEY: "k" }};
      await post(env, {{ kind: "waitlist", email: "A.B+1@gmail.com", ref: {json.dumps(SEAT_REF)} }});
      await post(env, {{ kind: "waitlist", email: "ab@gmail.com" }});
      await post(env, {{ kind: "waitlist", email: "ab@gmail.com" }});
      return {{ keys: [...kv.store.keys()].sort(), rows: (await read(env, "?kinds=waitlist")).rows }};
    """)
    assert len(got["keys"]) == 2 and sum(k.endswith(":r") for k in got["keys"]) == 1
    assert list(saved_refs(got["rows"]).values()) == [SEAT_REF]
    assert len(waitlist_addresses(got["rows"])) == 1


@needs_node
def test_the_worker_tells_the_read_key_its_switches_and_nobody_else(tmp_path) -> None:
    """`make launch-check` must see whether the Worker's TRIAL_OPEN agrees
    with the site's (pre-launch review). GET ?status=1 answers the switches,
    only with the read key, and lists no row."""
    got = _node(tmp_path, """
      const kv = fakeKV();
      const ask = async (env, auth) => {
        const res = await worker.fetch(new Request("https://w.test/?status=1",
          { headers: auth ? { Authorization: "Bearer k" } : {} }), env);
        return [res.status, res.status === 200 ? await res.json() : null];
      };
      return { anon: await ask({ ROWS: kv, FORM_API_KEY: "k" }, false),
               off: await ask({ ROWS: kv, FORM_API_KEY: "k" }, true),
               on: await ask({ ROWS: kv, FORM_API_KEY: "k", TRIAL_OPEN: "true",
                               COUNTS: { writeDataPoint() {} } }, true),
               lists: kv.lists };
    """)
    assert got["anon"][0] == 401
    assert got["off"] == [200, {"trial_open": False, "counts": False}]
    assert got["on"] == [200, {"trial_open": True, "counts": True}]
    assert got["lists"] == 0


def test_the_launch_check_holds_the_three_trial_switches_together(monkeypatch) -> None:
    """The landing's TRIAL_OPEN, the join page's twin and the Worker's
    variable: any disagreement is a launch-check line, and a site that
    offers free reports over a Worker that refuses them FAILs."""
    import run.launch_check as lc
    gates = {g.name: g for g in lc.check_funnel_config()}
    assert gates["Landing and join page agree on whether free reports are open"].status == "PASS"
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.delenv("FORM_API_KEY", raising=False)
    [skip] = lc.check_worker_switches()
    assert skip.status == "SKIP"
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setenv("FORM_API_KEY", "k")
    real = lc.js_constants

    def site_on(page):
        found = real(page)
        return {**found, "TRIAL_OPEN": "true"} if "TRIAL_OPEN" in found else found
    for site, worker, want in ((False, False, "PASS"), (True, True, "PASS"),
                               (True, False, "FAIL"), (False, True, "WARN")):
        monkeypatch.setattr(lc, "js_constants", site_on if site else real)
        monkeypatch.setattr(lc, "worker_status", lambda e, k, w=worker: {"trial_open": w})
        assert lc.check_worker_switches()[0].status == want, (site, worker)
    monkeypatch.delenv("RESEND_READ_KEY", raising=False)
    assert lc.check_resend_read_key()[0].status == "OWNER"
    monkeypatch.setenv("RESEND_READ_KEY", "re_full")
    assert lc.check_resend_read_key()[0].status == "PASS"


def test_the_privacy_page_no_longer_says_a_seat_is_matched_by_the_buyers_address() -> None:
    """Reproduced (pre-launch review): privacy.html's seat bullet still said a
    seat is matched by "either the pass code in your league's own link ... or
    the email the pass was bought with" after contract C3 stopped the Worker
    storing any typed buyer address — describing data no longer collected."""
    import re
    text = re.sub(r"<[^>]+>", " ", (ROOT / "site" / "privacy.html").read_text(encoding="utf-8"))
    text = " ".join(text.split())
    bullet = text[text.index("If you claim a League Pass seat"):][:400]
    assert "the email the pass was bought with" not in bullet and " either " not in bullet
    assert "pass code in your league's own link" in bullet


@needs_node
def test_a_mistyped_buyer_domain_is_asked_about_once_before_checkout(tmp_path) -> None:
    """Critique #1, first half (reproduced): the join page handed the typed
    address straight to Stripe as `locked_prefilled_email`, so "gmial.com"
    was a buyer who paid, could not fix it at Stripe, and whose welcome and
    every report went nowhere. The page now reads the address back as it is
    typed and, for the commonest domain slips, asks once with a button that
    fixes it; a second press with the same spelling goes ahead (the address
    may be real). Never a silent rewrite. Checked in Chrome too: the typo's
    first press left nothing, a clean address handed off at once."""
    page = (ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    start = page.index("const DOMAIN_FIXES = {")
    end = page.index("\n}\n", page.index("function suggestedEmail(")) + 3
    (tmp_path / "s.mjs").write_text(page[start:end] + """
process.stdout.write(JSON.stringify(["a.b@gmial.com", "x@Hotmial.com", "x@yahoo.con",
  "x@example.cmo", "x@gmail.com", "x@example.com", "x@proton.me", "bad"].map(suggestedEmail)));
""", encoding="utf-8")
    done = subprocess.run([NODE, str(tmp_path / "s.mjs")], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["a.b@gmail.com", "x@hotmail.com", "x@yahoo.com",
                                       "x@example.com", "", "", "", ""]
    # One read-back on the page (the merge once carried two, and the second
    # declaration of the table stopped every script on it).
    assert page.count("const DOMAIN_FIXES") == 1 and "innerHTML" not in page[start:end]


# --------------------------------------------------------------------- #
# contract C1 — the visit counter
# --------------------------------------------------------------------- #

@needs_node
def test_the_counter_always_answers_204_and_writes_only_clean_rows(tmp_path) -> None:
    """Contract C1. POST /e {e,p,v,r,d,s} -> ALWAYS an empty 204 with CORS
    for the site and never a cookie; a row is written to Analytics Engine
    (COUNTS, never KV) only from the site's Origin, only when every field
    matches ^[a-z0-9.-]{0,40}$ and the event, device and checkout state are
    ones the contract names; the blobs are [e, p, v, r, d, s, country],
    doubles [1], indexes [e]. With COUNTS unbound, or throwing, still 204."""
    got = _node(tmp_path, """
      const points = [];
      const kv = fakeKV();
      const env = { ROWS: kv, SITE_ORIGIN: "https://x.test",
                    COUNTS: { writeDataPoint: (p) => points.push(p) } };
      const hit = async (body, headers = { Origin: "https://x.test" }, method = "POST", cf) => {
        const init = { method, headers };
        if (method === "POST") init.body = typeof body === "string" ? body : JSON.stringify(body);
        const req = new Request("https://w.test/e", init);
        if (cf) Object.defineProperty(req, "cf", { value: cf });
        const res = await worker.fetch(req, env);
        return [res.status, res.headers.get("Access-Control-Allow-Origin"),
                res.headers.get("Set-Cookie"), await res.text()];
      };
      const out = [];
      out.push(await hit({ e: "view", p: "join", v: "reply-kit", r: "t.co", d: "m", s: "closed" },
                         undefined, "POST", { country: "CA" }));
      out.push(await hit({ e: "checkout", p: "somewhere-new" }));
      out.push(await hit({ e: "view", p: "join", v: "Me@Example.com" }));
      out.push(await hit({ e: "view", p: "index", r: "x".repeat(41) }));
      out.push(await hit({ e: "view", p: "index", d: "phone" }));
      out.push(await hit({ e: "click", p: "index" }));
      out.push(await hit({ e: "view", p: "index", extra: { nested: 1 } }));
      out.push(await hit("not json"));
      out.push(await hit({ e: "view", p: "index" }, { Origin: "https://evil.example" }));
      out.push(await hit({ e: "view", p: "index" }, {}));
      out.push(await hit({ e: "view", p: "index" },
                         { Origin: "https://x.test", "Content-Length": "9000" }));
      out.push(await hit(null, { Origin: "https://x.test" }, "GET"));
      // Over 512 bytes with no Content-Length declared: the body is measured.
      out.push(await hit({ e: "view", p: "index", pad: "x".repeat(600) }));
      out.push(await hit({ e: "view", p: "index", v: 7 }));
      const before = points.length;
      delete env.COUNTS;
      out.push(await hit({ e: "view", p: "index" }));
      env.COUNTS = { writeDataPoint: () => { throw new Error("binding down"); } };
      out.push(await hit({ e: "view", p: "index" }));
      return { out, points, before, kvPuts: kv.puts };
    """)
    for status, acao, cookie, body in got["out"]:
        assert status == 204 and acao == SITE and cookie is None and body == ""
    assert got["kvPuts"] == 0, "a count touched the form's KV"
    assert got["before"] == len(got["points"]) == 3
    first, second, third = got["points"]
    assert first == {"blobs": ["view", "join", "reply-kit", "t.co", "m", "closed", "CA"],
                     "doubles": [1], "indexes": ["view"]}
    assert second["blobs"] == ["checkout", "other", "", "", "", "", ""]
    assert third["blobs"][0] == "view" and third["blobs"][1] == "index"


def test_the_counters_page_and_event_names_are_the_contracts() -> None:
    """The ANALYTICS agent's page script sends these exact keys (contract C1);
    a key the Worker does not know would be counted as "other" forever."""
    src = WORKER.read_text(encoding="utf-8")
    for name in ("view", "roster", "checkout", "waitlist", "trial"):
        assert f'"{name}"' in src.split("const COUNT_EVENTS")[1].split(";")[0]
    pages = src.split("const COUNT_PAGES")[1].split(";")[0]
    for key in ("index", "join", "join-pass", "join-try", "league-pass", "how-it-works",
                "thanks", "sample", "this-week", "first-week", "404", "other"):
        assert f'"{key}"' in pages, key
    assert 'blobs: [fields.e, page, fields.v, fields.r, fields.d, fields.s, where]' in src
    assert "COUNTS.writeDataPoint(row)" in src and "await env.COUNTS" not in src
    assert "byl_counts" in src.split("*/", 1)[0], "the dataset to bind is not documented"


# --------------------------------------------------------------------- #
# the readers ask only for their own kinds
# --------------------------------------------------------------------- #

def test_each_reader_asks_the_worker_for_its_own_kinds_only(monkeypatch) -> None:
    """The kind filter is what keeps a flood of one kind off another reader's
    walk; it must actually reach the URL, and each runner must pass it."""
    import urllib.request
    seen: list[str] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(request, timeout=30):
        seen.append(request.full_url)
        return _Response()
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert intake.fetch_seats("https://w.test", "k", kinds=intake.INTAKE_KINDS) == []
    intake.fetch_seats("https://w.test/?x=1", "k", kinds=("trial",))
    intake.fetch_seats("https://w.test", "k")
    assert seen == ["https://w.test?kinds=confirm,seat,update,update_request",
                    "https://w.test/?x=1&kinds=trial", "https://w.test"]
    def body(name: str, fn: str = "def main(") -> str:
        return (ROOT / "run" / name).read_text(encoding="utf-8").split(fn, 1)[1]
    assert "kinds=INTAKE_KINDS" in body("intake.py")
    assert "kinds=TRIAL_KINDS" in body("trials.py")
    assert (ROOT / "run" / "waitlist.py").read_text(encoding="utf-8") \
        .count("kinds=WAITLIST_KINDS") == 2
    assert set(intake.INTAKE_KINDS) == {"seat", "update", "update_request", "confirm"}


def test_the_operators_roster_change_carries_the_read_key(monkeypatch) -> None:
    """`make roster-update` posts from the owner's shell, with no Origin: the
    Worker now takes that only with the read key, and without one the
    operator is told so rather than a change being "queued" into a 403."""
    import urllib.request

    from run import updates
    seen = []

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout=30: seen.append(request) or _Response())
    monkeypatch.delenv("FORM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FORM_API_KEY"):
        updates.post_row("https://w.test", {"kind": "update"})
    monkeypatch.setenv("FORM_API_KEY", "k")
    updates.post_row("https://w.test", {"kind": "update"})
    assert seen[0].get_header("Authorization") == "Bearer k"


# --------------------------------------------------------------------- #
# APPSEC-3 — a form outage costs form posts, never sales
# --------------------------------------------------------------------- #

def test_a_form_outage_still_registers_payers_and_logged_seats_and_goes_red(
        tmp_path, monkeypatch, capsys) -> None:
    """Reproduced (worker_down.py on the real main()): with the Worker
    unreadable the intake printed "Refusing to write a registry" and returned
    1 BEFORE writing it, so no new buyer was registered, welcomed or sent a
    first report for as long as a flood lasted. The refusal guarded seats,
    and seats no longer need the Worker: confirmed ones are in the seat log.
    Now the payer AND the logged seat are written, and the run exits 1.

    Mutation-checked: restoring the early `return 1` fails the registry
    assertion; dropping `form_down` from `failing` fails the exit code."""
    from test_intake_sync import (PASS_SUB, SEAT_REF, SEAT_SECRET, _pass_session,
                                  _registry)
    _stripe_and_directory(monkeypatch)
    STRIPE["sessions"] = [_pass_session()]
    monkeypatch.setenv("UPDATE_SECRET", SEAT_SECRET)
    monkeypatch.setenv("FORM_ENDPOINT", "https://forms.example")
    claimed = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
    intake.append_seat_log([intake.SeatEntry(
        email="member@example.com", pass_id=PASS_SUB, payer="commish@example.com",
        ref=SEAT_REF, claimed_at=claimed, confirmed_at=claimed,
        customer="cus_commish01")], tmp_path / intake.SEAT_LOG_NAME)

    def down(*_a, **_k):
        raise intake.IntakeError("HTTP 503")
    monkeypatch.setattr(intake, "fetch_seats", down)
    assert intake.main(["--registry-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "could not read the form backend" in err and "Refusing" not in err
    emails = sorted(r["email"] for r in _registry(tmp_path))
    assert emails == ["commish@example.com", "member@example.com"]


# --------------------------------------------------------------------- #
# APPSEC-2 / contract C3 — seats only through each pass's own link
# --------------------------------------------------------------------- #

PASSES = [intake.PassInfo("commish@example.com", "sub_commish01", 12, "cus_commish01")]
SECRET = "test-secret-do-not-ship"


def _at(hours_ago: float, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=hours_ago)).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


def _ref() -> str:
    from test_intake_sync import SEAT_REF
    return SEAT_REF


def test_a_typed_buyer_address_never_takes_a_seat_and_is_never_answered() -> None:
    """Reproduced (seat_squat.py): 14 claims from outsider{i}@attacker.example
    naming covered_by=<the buyer's address> got 14 confirmation codes, and
    after each outsider pressed their own, 12 seats on the pass — the real
    league, claiming through the buyer's own link, was then "full". And the
    reply was an oracle: naming a buyer mailed a confirmation, naming anyone
    else a "no pass" note. Now such a claim is counted and nothing else: no
    code, no seat, no note — the reply itself would rebuild the oracle.

    Mutation-checked: restoring the `by_payer` lookup gives 12 awaiting."""
    claims = [{"email": f"outsider{i}@attacker.example", "ref": _ref(),
               "covered_by": "commish@example.com", "received_at": _at(3)}
              for i in range(14)]
    swept = intake.sweep_seats(claims, PASSES, None, SECRET)
    assert swept.awaiting == [] and swept.rows == [] and swept.unmatched == []
    assert swept.typed_payer == 14
    stranger = intake.sweep_seats([dict(claims[0], covered_by="nobody@example.com")],
                                  PASSES, None, SECRET)
    assert stranger.unmatched == [] and stranger.awaiting == [], \
        "a buyer and a non-buyer must look the same from outside"
    real = {"email": "mate@example.com", "ref": _ref(), "received_at": _at(3),
            "pass_token": seat_token("commish@example.com", SECRET, "sub_commish01")}
    assert [p.email for p in intake.sweep_seats([real], PASSES, None, SECRET).awaiting] \
        == ["mate@example.com"]


def test_the_seat_pages_offer_no_typed_address_route() -> None:
    """Contract C3 on the pages: the join page posts a seat only with a pass
    token and, opened without one, says where the league's link is and takes
    the form away; no page hands out the generic join/?pass=1 line."""
    import re
    join = (ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    assert "covered_by" not in join and 'id="pass-email"' not in join
    assert "const SEAT_LINK_MISSING = SEAT_MODE && !PASS_TOKEN;" in join
    branch = join.split("if (SEAT_LINK_MISSING) {")[1].split("\n  }\n")[0]
    assert 'seatLinkMissingWords()' in branch and 'for (const child of $("main").children) child.style.display = "none";' in branch
    assert '$("main").prepend(note);' in branch      # one main landmark stays
    words = join.split("function seatLinkMissingWords()")[1].split("\n}\n")[0]
    assert "welcome email" in words and "reports" in words
    for name in ("league-pass.html", "thanks.html", "join/index.html"):
        page = re.sub(r"<!--.*?-->", "", (ROOT / "site" / name).read_text(encoding="utf-8"),
                      flags=re.S)
        assert "?pass=1" not in page, name


# --------------------------------------------------------------------- #
# APPSEC-1 — the day's allowance
# --------------------------------------------------------------------- #

def test_per_address_allowances_count_mailboxes_not_spellings() -> None:
    """Reproduced (repro_unmatched.py): unmatched_due, full_due and the seat
    confirmation allowance bucketed on the raw lowercased address, so
    victim+1@gmail.com … victim+1000@gmail.com were a thousand buckets for ONE
    inbox — 1,000 notes. Mutation-checked: bucketing on the raw address again
    gives 5 of each."""
    now = datetime.now(timezone.utc)
    rows = [{"email": f"vic.tim+{i}@gmail.com", "ref": _ref(), "received_at": _at(8, now),
             "pass_token": "f" * 20} for i in range(5)]
    assert len(intake.unmatched_due(rows, now)) == intake.UNMATCHED_PER_DAY
    assert len(intake.full_due(rows, now)) == intake.UNMATCHED_PER_DAY
    token = seat_token("commish@example.com", SECRET, "sub_commish01")
    claims = [dict(r, pass_token=token, ref=_ref() if i == 0 else _ref()[:-1] + str(i % 9))
              for i, r in enumerate(rows)]
    from run.updates import CONFIRMS_PER_DAY
    swept = intake.sweep_seats(claims, PASSES, None, SECRET, now=now)
    assert len(swept.awaiting) <= CONFIRMS_PER_DAY


def _sent_codes(requests, at: datetime) -> list[dict]:
    return [{"key": intake.seat_confirmation_key(r), "provider": "resend",
             "message_id": f"id-{i}", "sent_at": at.isoformat(timespec="seconds")}
            for i, r in enumerate(requests)]


def test_a_pass_gets_at_most_its_seat_count_of_mailboxes_a_day() -> None:
    """A real claim is bounded by its league; 40 distinct addresses claiming
    through one forwarded link in a day is somebody spending the allowance.
    Codes past the pass's seat count of MAILBOXES are held, counted from what
    the send log shows went out today, and the next day's run sends them."""
    now = datetime(2026, 10, 27, 20, tzinfo=timezone.utc)
    token = seat_token("commish@example.com", SECRET, "sub_commish01")
    claims = [{"email": f"m{i}@example{i}.com", "ref": _ref(), "pass_token": token,
               "received_at": _at(2 + i / 100, now)} for i in range(40)]
    swept = intake.sweep_seats(claims, PASSES, None, SECRET, now=now)
    assert len(swept.awaiting) == 40 and swept.seat_caps == {"sub_commish01": 12}
    allowed, held = intake.per_pass_allowance(swept.awaiting, swept.seat_caps, [], now)
    assert len(allowed) == 12 and held == 28
    # The same run again, after those 12 went out: nothing new leaves today.
    sent = _sent_codes(allowed, now)
    again, held_again = intake.per_pass_allowance(swept.awaiting, swept.seat_caps, sent, now)
    assert held_again == 28 and {r.code for r in again} == {r.code for r in allowed}
    # Tomorrow: yesterday's codes free nothing up for today but no longer count.
    tomorrow = now + timedelta(days=1)
    later, held_later = intake.per_pass_allowance(swept.awaiting, swept.seat_caps, sent,
                                                  tomorrow)
    assert held_later == 16 and len(later) == 24


def test_a_held_seat_code_goes_out_on_a_later_day_and_a_resubmission_costs_no_slot(
        tmp_path, monkeypatch, capsys) -> None:
    """Reproduced (pre-launch review): the per-pass cap counted CLAIMS in the
    bucket (pass, the claim's own date), so a claim held on its day was held
    on every later run until it expired, and it only added a line to
    `problems` — the run stayed green. 12 leaguemates plus one corrected
    resubmission on one evening stranded the 12th person, who had been told
    "Your seat request is in": +0, +1, +2 and +5 days all printed
    `held_per_pass=1 held_emails=['mate11@example11.com']`. Now the allowance
    counts distinct mailboxes against the codes actually SENT today, so the
    whole league is mailed at once; and a code held for a real flood is sent
    the next day, with the holding run exiting non-zero."""
    day = datetime(2026, 10, 27, 18, tzinfo=timezone.utc)
    token = seat_token("commish@example.com", SECRET, "sub_commish01")
    claims = [{"email": f"mate{i}@example{i}.com", "ref": _ref(), "pass_token": token,
               "received_at": _at(-i / 60, day)} for i in range(12)]
    from run.refs import encode_roster
    from test_intake_sync import PLAYERS, SLOTS
    other = encode_roster("season", "ppr", list(SLOTS), PLAYERS)   # a corrected roster
    # The correction arrives after the whole league has claimed: by then 12
    # mailboxes hold codes, and it must still cost no slot.
    claims.append({"email": "mate3@example3.com", "ref": other, "pass_token": token,
                   "received_at": _at(-0.5, day)})
    now = day + timedelta(hours=1)
    swept = intake.sweep_seats(claims, PASSES, None, SECRET, now=now)
    allowed, held = intake.per_pass_allowance(swept.awaiting, swept.seat_caps, [], now)
    assert held == 0 and len(allowed) == 13
    assert {r.email for r in allowed} == {c["email"] for c in claims}
    # A pass of 2 seats with 3 mailboxes: one held today, sent tomorrow.
    small = {"sub_commish01": 2}
    first, held_first = intake.per_pass_allowance(swept.awaiting[:3], small, [], now)
    assert held_first == 1 and len(first) == 2
    log = _sent_codes(first, now)
    tomorrow = now + timedelta(days=1)
    second, held_second = intake.per_pass_allowance(swept.awaiting[:3], small, log, tomorrow)
    assert held_second == 0 and len(second) == 3
    # The holding run is red: _send_seat_notes reports the hold as a failure.
    monkeypatch.setattr(intake, "_sent_entries", lambda: [])
    monkeypatch.setattr(intake, "_send_notes", lambda label, messages: 0)
    monkeypatch.setattr(intake, "_seat_confirmation_messages",
                        lambda awaiting, data: [_Msg(intake.seat_confirmation_key(r))
                                                for r in awaiting])
    held_sweep = intake.SeatSweep(awaiting=list(swept.awaiting[:3]), seat_caps=small)
    assert intake._send_seat_notes(held_sweep, None, now, "2026") is True
    assert held_sweep.held_per_pass == 1
    assert "SEAT CONFIRMATIONS HELD: 1" in capsys.readouterr().err


def test_a_buyer_can_reset_their_seats_and_the_old_link_stops_working(tmp_path) -> None:
    """APPSEC-2, the payer-side control the review found unbuilt: the seat
    link is forwardable and the buyer's report shows a count only (C2), so a
    pass whose seats were taken by people outside the league had no remedy —
    only the operator could release a seat, by the holder's address, which
    nobody had. A reset (`make seat-reset`) rotates the pass's link (the
    token takes the reset's stamp) and releases every seat claimed before
    it; claims through the old link are ignored, never answered, and never
    read as a dead signing secret. Count-only is kept: nobody is named."""
    from run import seat_resets
    from run.updates import seat_url
    resets_file = tmp_path / "seat-resets.txt"
    stamp = seat_resets.add_reset("sub_commish01", now=datetime(2026, 10, 27, 12,
                                                              tzinfo=timezone.utc),
                                  path=resets_file)
    assert stamp == "2026-10-27T12:00:00Z"
    text = resets_file.read_text(encoding="utf-8")
    assert "sub_commish01" not in text and seat_resets.pass_code("sub_commish01") in text
    assert seat_resets.load_resets(resets_file) == {seat_resets.pass_code("sub_commish01"): stamp}
    with pytest.raises(ValueError):
        seat_resets.add_reset("buyer@example.com", path=resets_file)
    resets_file.write_text(text + "not a line\n", encoding="utf-8")
    with pytest.raises(seat_resets.SeatResetError):
        seat_resets.load_resets(resets_file)

    now = datetime(2026, 10, 27, 15, tzinfo=timezone.utc)
    old = seat_token("commish@example.com", SECRET, "sub_commish01")
    new = seat_token("commish@example.com", SECRET, "sub_commish01", stamp)
    assert new != old
    link = seat_url("https://x.test", SECRET, "commish@example.com", None,
                    pass_id="sub_commish01", nonce=stamp)
    assert link == f"https://x.test/join/?pass={new}"
    squatter = intake.SeatEntry(email="stranger@example.com", pass_id="sub_commish01",
                                payer="commish@example.com", ref=_ref(),
                                claimed_at=_at(30, now), confirmed_at=_at(29, now))
    claims = [{"email": "again@example.com", "ref": _ref(), "pass_token": old,
               "received_at": _at(1, now)},
              {"email": "mate@example.com", "ref": _ref(), "pass_token": new,
               "received_at": _at(1, now)}]
    before = intake.sweep_seats(claims[:1], PASSES, None, SECRET, log=[squatter], now=now)
    assert [r["email"] for r in before.rows] == ["stranger@example.com"]
    after = intake.sweep_seats(claims, PASSES, None, SECRET, log=[squatter], now=now,
                               resets={"sub_commish01": [stamp]})
    assert after.rows == [] and after.reset_released == 1
    assert after.reset_stale == 1 and not after.unmatched and not after.links_dead
    assert [r.email for r in after.awaiting] == ["mate@example.com"]
    # A second reset retires the first reset's link too.
    later = "2026-10-28T09:00:00Z"
    newer = seat_token("commish@example.com", SECRET, "sub_commish01", later)
    twice = intake.sweep_seats(
        [{**claims[1], "received_at": _at(1, datetime(2026, 10, 28, 12, tzinfo=timezone.utc))},
         {"email": "x@example.com", "ref": _ref(), "pass_token": newer,
          "received_at": _at(1, datetime(2026, 10, 28, 12, tzinfo=timezone.utc))}],
        PASSES, None, SECRET, now=datetime(2026, 10, 28, 12, tzinfo=timezone.utc),
        resets={"sub_commish01": [stamp, later]})
    assert twice.reset_stale == 1 and [r.email for r in twice.awaiting] == ["x@example.com"]


def test_the_payers_report_says_how_to_reset_seats_they_dont_recognize(monkeypatch) -> None:
    """The control has to be findable by the one person who can use it: the
    payer's seat count line says to reply "reset seats" once any seat is
    claimed — and never on a pass with none, or on anybody else's report."""
    import render.report as rr
    link = "https://x.test/join/?pass=" + "a" * 20
    some = rr.seats_text({"plan": "pass", "seat_link": link,
                          "seats_claimed": {"claimed": 3, "size": 12}})
    full = rr.seats_text({"plan": "pass", "seat_link": link, "seats_full": True,
                          "seats_claimed": {"claimed": 12, "size": 12}})
    none = rr.seats_text({"plan": "pass", "seat_link": link,
                          "seats_claimed": {"claimed": 0, "size": 12}})
    assert some.endswith(rr.SEAT_RESET_LINE) and full.endswith(rr.SEAT_RESET_LINE)
    assert "reset seats" not in none and ": " not in rr.SEAT_RESET_LINE
    assert "@" not in rr.SEAT_RESET_LINE
    assert rr.seats_text({"plan": "league_pass", "seat_link": link,
                          "seats_claimed": {"claimed": 3, "size": 12}}) == ""


class _Msg:
    def __init__(self, key: str) -> None:
        self.key = key


def _entries(keys: list[str], at: datetime) -> list[dict]:
    return [{"key": k, "provider": "resend", "message_id": f"id-{i}",
             "sent_at": at.isoformat(timespec="seconds")} for i, k in enumerate(keys)]


def test_seat_notes_are_capped_confirmations_first_strays_last() -> None:
    """The caps, as a pure plan: confirmations before the stray notes, the
    strays inside their own small cap, everything inside the day's cap on
    seat notes and the day's headroom on ALL sends; a message already in the
    log costs nothing; anything held is counted (the run then exits 1)."""
    now = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
    confirms = [_Msg(f"seat-confirm-{i}") for i in range(25)]
    strays = [_Msg(f"seat-unmatched-{i}") for i in range(25)]
    plan = intake.plan_notes(confirms, strays, [], now)
    assert len(plan.confirmations) == 25
    assert len(plan.strays) == intake.SEAT_NOTES_DAILY_CAP - 25 == 5
    assert plan.held == 20 and plan.reason
    plan = intake.plan_notes([], strays, [], now)
    assert len(plan.strays) == intake.STRAY_NOTES_DAILY_CAP
    # Already sent today: counted against the caps, and skipped themselves.
    sent = _entries([f"seat-unmatched-{i}" for i in range(10)], now)
    plan = intake.plan_notes([], strays, sent, now)
    assert plan.strays == [] and plan.held == 15
    yesterday = _entries([f"seat-unmatched-{i}" for i in range(10)], now - timedelta(days=1))
    assert len(intake.plan_notes([], strays[10:], yesterday, now).strays) == 10
    # The day's headroom on every send: paid reports keep what is left.
    busy = _entries([f"2026-w07-slug{i}" for i in range(intake.DAY_HEADROOM)], now)
    plan = intake.plan_notes(confirms, strays, busy, now)
    assert plan.confirmations == [] and plan.strays == [] and plan.held == 50
    assert "allowance" in plan.reason


def test_the_day_headroom_follows_the_provider_plan(monkeypatch) -> None:
    """Sized for the free 100 a day; a paid plan raises it with
    EMAIL_DAILY_HEADROOM, or a big Tuesday would hold every seat note."""
    now = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
    busy = _entries([f"2026-w07-slug{i}" for i in range(intake.DAY_HEADROOM)], now)
    confirms = [_Msg(f"seat-confirm-{i}") for i in range(3)]
    assert intake.plan_notes(confirms, [], busy, now).held == 3
    monkeypatch.setenv("EMAIL_DAILY_HEADROOM", "500")
    assert len(intake.plan_notes(confirms, [], busy, now).confirmations) == 3
    monkeypatch.setenv("EMAIL_DAILY_HEADROOM", "lots")
    assert intake.day_headroom() == intake.DAY_HEADROOM


def test_claims_inside_a_flood_are_never_answered() -> None:
    """More than UNMATCHED_FLOOD unmatched claims within 24 hours of each
    other is a flood: none of them is ever answered — not now, and not
    trickled out at the daily cap over the next two weeks."""
    now = datetime.now(timezone.utc)
    flood = [{"email": f"x{i}@junk{i}.example", "ref": _ref(), "pass_token": "e" * 20,
              "received_at": _at(7 + i / 60, now)} for i in range(intake.UNMATCHED_FLOOD + 1)]
    lone = {"email": "typo@example.com", "ref": _ref(), "pass_token": "d" * 20,
            "received_at": _at(24 * 5, now)}
    assert intake.flooded(flood, now)
    assert intake._unmatched_messages([*flood, lone], now) and \
        [m.to for m in intake._unmatched_messages([*flood, lone], now)] == ["typo@example.com"]
    later = now + timedelta(days=3)
    assert not intake.flooded(flood, later)
    assert [m.to for m in intake._unmatched_messages(flood, later)] == []


def _stripe_and_directory(monkeypatch):
    """test_intake_sync's fake Stripe and stand-in directory, by hand (they
    are fixtures there)."""
    import run.checkout as checkout
    import run.subscriptions as subscriptions
    from engine.roster import Player, PlayerDirectory
    from test_intake_sync import (MONTHLY_LINK, PASS_LINK, PLAYERS, SEASON_LINK,
                                  _page, _subscriptions)
    STRIPE.clear()
    STRIPE.update({"sessions": [], "posts": []})
    monkeypatch.setattr(checkout, "_stripe_get", lambda url, key: _page(STRIPE["sessions"]))
    monkeypatch.setattr(subscriptions, "_stripe_get",
                        lambda url, key: _subscriptions(STRIPE, url))
    monkeypatch.setattr(intake, "_stripe_post",
                        lambda url, key, form: STRIPE["posts"].append((url, form)) or {})
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS",
                       f"s:{SEASON_LINK},m:{MONTHLY_LINK},p:{PASS_LINK}")
    people = [Player(pid, f"Player {i}", "WR", "KC") for i, pid in enumerate(PLAYERS, start=1)]

    class _Data:
        directory = PlayerDirectory(people)

    monkeypatch.setattr(intake, "load_week_data", lambda *a, **k: _Data())
    return _Data


STRIPE: dict = {}


class _Quota:
    """Resend's free tier: `room` messages, then 429 for the rest of the day."""

    name = "resend"

    def __init__(self, room: int) -> None:
        self.room, self.sent = room, []

    def send(self, message, sender, reply_to):
        from run.delivery import DeliveryError
        if len(self.sent) >= self.room:
            raise DeliveryError("HTTP 429 from provider: daily quota")
        self.sent.append(message)
        return f"id-{len(self.sent)}"


def _mailing_run(tmp_path, monkeypatch, provider, claims):
    """One real intake run: a buyer who has just paid, a pass, the given seat
    claims, ``provider`` doing the sending into a send log of the test's own,
    and the first report stood in for by one message through the same
    provider (the stand-in directory cannot build a real one). -> (code,
    order of keys sent)."""
    import run.delivery as delivery
    from run.delivery import Message, send_all
    from test_intake_sync import REF, SEAT_SECRET, _pass_session, _session
    _stripe_and_directory(monkeypatch)
    STRIPE["sessions"] = [_pass_session(), _session(REF, sid="cs_buyer", email="buyer@example.com",
                                                    customer="cus_buyer001")]
    monkeypatch.setenv("UPDATE_SECRET", SEAT_SECRET)
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("FORM_ENDPOINT", "https://forms.example")
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setattr(intake, "build_provider", lambda *a, **k: provider)
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: list(claims))
    monkeypatch.setattr(intake, "bounce_alarm", lambda now: False)

    def first_files(signups, *a, **k):
        messages = [Message(to=s.email, subject="Week 7", html="<p>x</p>", text="x",
                            key=f"2026-w07-{s.slug}") for s in signups]
        return sum(1 for r in send_all(messages, provider=provider) if not r.ok)
    monkeypatch.setattr(intake, "_send_first_files", first_files)
    code = intake.main(["--registry-dir", str(tmp_path / "reg")])
    return code, [m.key for m in provider.sent]


def test_forged_claims_can_no_longer_starve_a_buyers_first_report(
        tmp_path, monkeypatch, capsys) -> None:
    """APPSEC-1, the verifier's end-to-end reproduction on the real main():
    a buyer who has just paid, 150 forged seat claims 7 hours old, and a
    provider that accepts 100 then answers 429. It sent the welcome, then 99
    "no pass" notes to one inbox, then REFUSED the buyer's first report — and
    exited 0. Now paid mail goes first, a flood is never answered, and the run
    is red while the flood lasts.

    Mutation-checked: moving the seat notes back before the first reports, or
    dropping the flood rule, puts the buyer's first report behind the notes."""
    from test_intake_sync import SEAT_SECRET
    now = datetime.now(timezone.utc)
    real = {"kind": "seat", "email": "mate@example.com", "ref": _ref(), "received_at": _at(7, now),
            "pass_token": seat_token("commish@example.com", SEAT_SECRET, "sub_commish01")}
    forged = [{"kind": "seat", "email": f"victim+{i}@gmail.com", "ref": _ref(),
               "pass_token": f"{i:020x}", "received_at": _at(7 + i / 600, now)}
              for i in range(150)]
    provider = _Quota(room=100)
    code, keys = _mailing_run(tmp_path, monkeypatch, provider, [real, *forged])
    err = capsys.readouterr().err
    assert code == 1 and "SEAT CLAIM FLOOD" in err
    weekly = [k for k in keys if k.startswith("2026-w07-")]
    assert len(weekly) == 2, "a paid buyer's first report did not go out"
    assert not [k for k in keys if k.startswith("seat-unmatched-")], "a flood was answered"
    welcomes = [i for i, k in enumerate(keys) if k.startswith("welcome-")]
    notes = [i for i, k in enumerate(keys) if k.startswith("seat-")]
    assert welcomes and max(welcomes) < min(i for i, k in enumerate(keys)
                                            if k.startswith("2026-w07-"))
    assert all(i > max(keys.index(k) for k in weekly) for i in notes), \
        "a seat note went out before the paid mail"


def test_the_real_intake_honours_a_seat_reset_and_refuses_an_unreadable_list(
        tmp_path, monkeypatch, capsys) -> None:
    """End to end on the real main(): after a reset, a claim through the
    pass's OLD link gets no confirmation (and no "no pass" note), a claim
    through the NEW link gets its code, and a seat-reset list the run cannot
    read refuses the registry rather than hand released seats back."""
    from run import seat_resets
    from test_intake_sync import SEAT_SECRET
    now = datetime.now(timezone.utc)
    resets = tmp_path / "seat-resets.txt"
    stamp = seat_resets.add_reset("sub_commish01", now=now - timedelta(hours=3), path=resets)
    monkeypatch.setattr(seat_resets, "RESETS_FILE", resets)
    old = seat_token("commish@example.com", SEAT_SECRET, "sub_commish01")
    new = seat_token("commish@example.com", SEAT_SECRET, "sub_commish01", stamp)
    claims = [{"kind": "seat", "email": "squat@example.com", "ref": _ref(),
               "received_at": _at(1, now), "pass_token": old},
              {"kind": "seat", "email": "mate@example.com", "ref": _ref(),
               "received_at": _at(1, now), "pass_token": new}]
    code, keys = _mailing_run(tmp_path, monkeypatch, _Quota(room=100), claims)
    out = capsys.readouterr().out
    assert [k for k in keys if k.startswith("seat-confirm-")] and \
        not [k for k in keys if k.startswith("seat-unmatched-")]
    assert len([k for k in keys if k.startswith("seat-confirm-")]) == 1
    assert "1 old-link claim(s) ignored by a buyer's seat reset" in out
    resets.write_text("garbage\n", encoding="utf-8")
    code, _keys = _mailing_run(tmp_path / "again", monkeypatch, _Quota(room=100), claims)
    assert code == 1 and "seat-reset list" in capsys.readouterr().err


def test_a_burst_under_the_flood_line_is_capped_and_goes_red(
        tmp_path, monkeypatch, capsys) -> None:
    """Fifteen unmatched claims from fifteen inboxes in a day — under the
    flood line — get STRAY_NOTES_DAILY_CAP notes; the rest wait, unlogged,
    and the run exits 1 so the hold is seen."""
    from test_intake_sync import SEAT_SECRET
    now = datetime.now(timezone.utc)
    real = {"kind": "seat", "email": "mate@example.com", "ref": _ref(), "received_at": _at(7, now),
            "pass_token": seat_token("commish@example.com", SEAT_SECRET, "sub_commish01")}
    stray = [{"kind": "seat", "email": f"m{i}@site{i}.example", "ref": _ref(),
              "pass_token": f"{i + 1:020x}", "received_at": _at(7 + i / 60, now)}
             for i in range(15)]
    provider = _Quota(room=100)
    code, keys = _mailing_run(tmp_path, monkeypatch, provider, [real, *stray])
    assert code == 1 and "SEAT NOTES HELD" in capsys.readouterr().err
    assert len([k for k in keys if k.startswith("seat-unmatched-")]) == \
        intake.STRAY_NOTES_DAILY_CAP
    assert len([k for k in keys if k.startswith("seat-confirm-")]) == 1


def test_a_first_report_or_welcome_that_fails_to_send_fails_the_run(
        tmp_path, monkeypatch, capsys) -> None:
    """Observed in the reproduction: a quota-starved buyer's refused first
    report left the run at exit 0. A welcome or first report owed to a paid
    signup that did not go out now makes the run exit 1 (it retries next run
    either way). Mutation-checked: ignoring `unsent` gives exit 0."""
    provider = _Quota(room=0)
    code, keys = _mailing_run(tmp_path, monkeypatch, provider, [])
    assert code == 1 and keys == []
    assert "did not go out" in capsys.readouterr().err


# --------------------------------------------------------------------- #
# the waitlist launch send — same dedupe, an owner-set ceiling
# --------------------------------------------------------------------- #

def test_the_waitlist_is_one_message_per_mailbox_and_a_send_needs_a_ceiling(
        tmp_path, monkeypatch, capsys) -> None:
    """APPSEC-1's waitlist half: the list was deduped on the raw address, had
    no cap, and nothing showed what it looked like before --send. Now one
    message per mailbox, the preview prints the mailbox count and the
    commonest domains (domains only), and --send refuses without --max (or
    WAITLIST_MAX) and when more than that are still to be announced."""
    import run.waitlist as wl
    rows = [{"kind": "waitlist", "email": e} for e in
            ("john.doe@gmail.com", "johndoe+launch@gmail.com", "a@junk.example",
             "b@junk.example", "c@junk.example", "fan@example.com")]
    assert wl.waitlist_addresses(rows) == ["john.doe@gmail.com", "a@junk.example",
                                           "b@junk.example", "c@junk.example",
                                           "fan@example.com"]
    assert wl.top_domains(wl.waitlist_addresses(rows))[0] == ("junk.example", 3)
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setattr(wl, "fetch_seats", lambda *a, **k: rows)
    import run.delivery as delivery
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    assert wl.main([]) == 0
    out = capsys.readouterr().out
    assert "5 mailbox(es)" in out and "junk.example 3" in out and "@" not in \
        out.split("commonest domains:")[1].split("\n")[0].replace("junk.example", "")
    for name, value in (("EMAIL_PROVIDER", "resend"), ("RESEND_API_KEY", "re_x"),
                        ("EMAIL_FROM", "B <b@x.test>"), ("SENDER_POSTAL_ADDRESS", "PO Box 1")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("WAITLIST_MAX", raising=False)
    assert wl.main(["--send"]) == 1
    assert "--max" in capsys.readouterr().err
    sent: list = []
    monkeypatch.setattr(wl, "send_all", lambda msgs, provider: sent.extend(msgs) or [])
    assert wl.main(["--send", "--max", "4"]) == 1 and sent == []
    assert "above --max 4" in capsys.readouterr().err
    monkeypatch.setenv("WAITLIST_MAX", "5")
    assert wl.main(["--send"]) == 0 and len(sent) == 5


# --------------------------------------------------------------------- #
# SEC-06 + critique #3 — the free report
# --------------------------------------------------------------------- #

def test_the_runner_reads_the_sites_own_free_report_switch(tmp_path) -> None:
    """SEC-06: run/trials.py never checked site/index.html's TRIAL_OPEN, so a
    request sent straight to the form was mailed with the button off. One
    `const TRIAL_OPEN = true;` opens it; anything else is closed."""
    from run.trials import free_reports_open
    page = tmp_path / "index.html"
    for text, want in (("const TRIAL_OPEN = true;\n", True),
                       ("const TRIAL_OPEN = false;\n", False),
                       ("nothing here\n", False),
                       ("const TRIAL_OPEN = true;\nconst TRIAL_OPEN = true;\n", False),
                       ("// const TRIAL_OPEN = true;\nconst TRIAL_OPEN = false;\n", False)):
        page.write_text(text, encoding="utf-8")
        assert free_reports_open(page) is want, text
    assert free_reports_open(tmp_path / "missing.html") is False
    shipped = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert free_reports_open() is ("const TRIAL_OPEN = true;" in shipped)


def test_with_the_switch_off_a_request_is_never_built_or_mailed(
        tmp_path, monkeypatch, capsys) -> None:
    """SEC-06 end to end: the same pending request is mailed with the site's
    switch on and neither built nor mailed with it off — waiting, exit 0
    (the requests expire on their own). Mutation-checked: removing the
    free_reports_open() gate mails it."""
    from test_trials import THURSDAY, _drive, _fixture_ref, _row
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    rows = [_row("fan@example.com", ref=_fixture_ref())]
    code, out, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=THURSDAY,
                                  trial_open=False)
    assert code == 0 and mailed == [] and "does not offer the free report" in out
    code, _, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=THURSDAY)
    assert code == 0 and [m.to for m in mailed] == ["fan@example.com"]


def test_free_reports_keep_the_days_headroom_and_wait_for_saturdays_check(
        tmp_path, monkeypatch, capsys) -> None:
    """Reproduced (pre-launch review): only the seat notes honoured the day's
    headroom (DAY_HEADROOM, 60) — `grep day_headroom run/` matched only
    run/intake.py, and run/trials.py's room was TRIAL_DAILY_CAP minus
    today's free reports and nothing else. On a Saturday, 40 hourly free
    reports plus the seat notes left about 40 of Resend's free 100 for the
    16:17 final check and that day's welcomes and first reports. Free
    reports now stop once the day's whole send count reaches the headroom,
    and on a Saturday wait for the final check's run marker, as they do on
    Tuesday. Mutation-checked: dropping either bound mails the request."""
    from run.watchdog import run_key
    from test_solo_run import SEASON, WEEK
    from test_trials import THURSDAY, _drive, _fixture_ref, _row
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("EMAIL_DAILY_HEADROOM", raising=False)
    rows = [_row("fan@example.com", ref=_fixture_ref())]
    busy = [(f"2026-w{WEEK:02d}-{i:04x}", THURSDAY) for i in range(intake.DAY_HEADROOM)]
    code, out, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=THURSDAY,
                                  sent=busy)
    assert code == 0 and mailed == [] and "allowance for unpaid mail is spent" in out
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=THURSDAY,
                        sent=busy[:-1])
    assert len(mailed) == 1
    saturday = "2026-01-03T13:00:00+00:00"
    code, out, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=saturday)
    assert code == 0 and mailed == [] and "Saturday check goes out first" in out
    done = [(run_key("saturday", SEASON, WEEK), saturday)]
    *_, mailed = _drive(tmp_path, monkeypatch, capsys, rows=rows, now=saturday, sent=done)
    assert len(mailed) == 1


def test_one_roster_gets_one_free_report_a_season_whatever_the_inbox() -> None:
    """Critique #3, reproduced: the limit was per address only, so a second
    inbox (an alias, Hide My Email, a catch-all) got the same roster's report
    every week. Rosters sharing 80% of the smaller one's players — and at
    least five — are one team."""
    from run.trials import ROSTER_OVERLAP_MIN_SHARED, too_close
    a = {f"p{i}" for i in range(15)}
    assert too_close(a, a)
    assert too_close(a, {f"p{i}" for i in range(12)} | {"x1", "x2", "x3"})
    assert not too_close(a, {f"p{i}" for i in range(11)} | {"x1", "x2", "x3", "x4"})
    assert too_close(a, {f"p{i}" for i in range(9)}), "a subset is the same team"
    assert not too_close({"p1", "p2", "p3"}, {"p1", "p2", "p3"}), \
        f"under {ROSTER_OVERLAP_MIN_SHARED} shared players is never refused"
    assert not too_close(set(), a)


def test_a_second_inbox_with_the_same_roster_is_refused_and_only_digests_are_kept(
        tmp_path, monkeypatch, capsys) -> None:
    """End to end through run.trials.main: the first request is served and its
    roster remembered as keyed digests beside the registry; a request from
    another inbox (same run or a later one) with that roster is refused and
    never mailed; the stored file holds no player id and no address.
    Mutation-checked: dropping the `served` check mails both."""
    import run.trials as trials
    from test_trials import THURSDAY, _drive, _fixture_ref, _row
    from test_tuesday import ROSTER_IDS
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    first = [_row("fan@example.com", ref=_fixture_ref()),
             _row("fan.alias@icloud.example", ref=_fixture_ref())]
    code, out, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=first, now=THURSDAY,
                                  roster_rule=True)
    assert code == 0 and [m.to for m in mailed] == ["fan@example.com"]
    assert "1 request(s) refused" in out
    stored = (tmp_path / "reg" / trials.TRIAL_ROSTERS_NAME).read_text(encoding="utf-8")
    assert stored.count("\n") == 1
    assert not any(pid in stored for pid in ROSTER_IDS) and "@" not in stored
    later = [_row("third@example.org", ref=_fixture_ref())]
    code, out, _, mailed = _drive(tmp_path, monkeypatch, capsys, rows=later, now=THURSDAY,
                                  roster_rule=True)
    assert code == 0 and mailed == [] and "refused" in out


def test_a_subscribers_roster_is_never_a_free_report(tmp_path, monkeypatch, capsys) -> None:
    """A subscriber's own address is already excluded; a different inbox
    asking for the subscriber's roster is refused too."""
    from test_trials import THURSDAY, _drive, _fixture_ref, _row
    from test_tuesday import REF, ROSTER_IDS, SLOTS
    registry = json.dumps([{"email": "paid@example.com", "ref": REF,
                            "player_ids": list(ROSTER_IDS), "slots": list(SLOTS),
                            "scoring": "ppr", "plan": "season"}])
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    code, out, err, mailed = _drive(tmp_path, monkeypatch, capsys,
                                    rows=[_row("friend@example.com", ref=_fixture_ref())],
                                    now=THURSDAY, registry=registry, roster_rule=True)
    assert code == 0, err
    assert mailed == [] and "refused" in out


# --------------------------------------------------------------------- #
# critique #2 — disputes
# --------------------------------------------------------------------- #

def _disputed_session(pi, disputed=False):
    charge = {"id": "ch_" + pi[3:], "payment_intent": pi, "amount": 2900,
              "amount_refunded": 0, "refunded": False, "disputed": disputed}
    from test_one_time_passes import PAID
    return {"id": "cs_" + pi, "mode": "payment", "payment_status": "paid",
            "created": PAID, "customer_details": {"email": f"{pi}@example.com"},
            "payment_intent": {"id": pi, "latest_charge": charge}}


def test_a_lost_chargeback_ends_entitlement_and_an_open_one_is_an_alarm(monkeypatch) -> None:
    """Reproduced: `_charge_refunded` returned False for a charge whose
    dispute was LOST — Stripe leaves `refunded` false and `amount_refunded`
    0 — so the buyer kept every report. A lost dispute now counts as refunded;
    one waiting on our response is listed (still entitled: it can be won);
    one closed in our favour is nothing; one whose status cannot be read is
    "unknown". The status comes from GET /v1/disputes?charge=…, asked only
    for a charge Stripe marks `disputed`. Mutation-checked: dropping the lost
    branch keeps pi_lost entitled."""
    from run import subscriptions
    from test_one_time_passes import ENDS

    status = {"ch_lost": ["lost"], "ch_open": ["needs_response"],
              "ch_review": ["warning_closed", "under_review"], "ch_won": ["won"],
              "ch_nothing": []}
    rows = [_disputed_session("pi_clean"), _disputed_session("pi_lost", True),
            _disputed_session("pi_open", True), _disputed_session("pi_review", True),
            _disputed_session("pi_won", True), _disputed_session("pi_nothing", True)]
    urls: list[str] = []

    def get(url, key):
        urls.append(url)
        if url.startswith(subscriptions.DISPUTES_API):
            charge = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["charge"][0]
            return {"data": [{"status": s} for s in status[charge]], "has_more": False}
        return {"data": rows, "has_more": False}
    monkeypatch.setattr(subscriptions, "_stripe_get", get)
    disputes: list = []
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    ids, _emails, refunded = subscriptions._one_time_purchases(
        "sk", now=now, season_ends=ENDS, disputes=disputes)
    assert "pi_lost" not in ids and "pi_lost" in refunded
    assert {"pi_clean", "pi_open", "pi_review", "pi_won", "pi_nothing"} <= ids
    assert sorted(disputes) == [("pi_nothing", "unknown"), ("pi_open", "needs_response"),
                                ("pi_review", "under_review")]
    # One dispute read per DISPUTED charge, none for the clean one.
    asked = [u for u in urls if u.startswith(subscriptions.DISPUTES_API)]
    assert len(asked) == 5 and not any("ch_clean" in u for u in asked)
    listed = subscriptions.PaidList(emails=frozenset(), source="stripe", status_column=None,
                                    disputes=tuple(disputes))
    assert set(listed.disputes_needing_response) == {"pi_open"}


def test_the_entitlement_read_expands_no_dispute(monkeypatch) -> None:
    """Reproduced (pre-launch review, blocker): the fix for critique #2
    expanded `data.payment_intent.latest_charge.dispute` and
    `data.latest_invoice.charge.dispute`. At the pinned Stripe-Version
    (2024-06-20) a Charge has NO `dispute` property — stripe-node v16 types
    only `disputed: boolean`, and v13's changelog removed `dispute` — and the
    cron key had no Disputes permission, so the request fails, `_stripe_get`
    raises, and `load_paid_from_stripe` fails for every runner: Tuesday mails
    nobody. Now no request expands a dispute, and a dispute read that fails
    (here a 403) is a warning: entitlement still loads, the disputed charge is
    "unknown" and stays served."""
    from run import subscriptions
    rows = [_disputed_session("pi_ok"), _disputed_session("pi_hurt", True)]
    urls: list[str] = []

    def get(url, key):
        urls.append(url)
        if url.startswith(subscriptions.DISPUTES_API):
            raise subscriptions.SubscriptionError("Stripe returned HTTP 403.")
        if "checkout/sessions" in url:
            return {"data": rows, "has_more": False}
        return {"data": [], "has_more": False}
    monkeypatch.setattr(subscriptions, "_stripe_get", get)
    from test_one_time_passes import ENDS
    monkeypatch.setattr("run.solo.season_ends", lambda *a, **k: ENDS)
    paid = subscriptions.load_paid_from_stripe("rk_test")
    for url in urls:
        expands = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("expand[]", [])
        assert not any(e.endswith(".dispute") for e in expands), url
    assert {"pi_ok", "pi_hurt"} <= set(paid.subscription_ids)
    assert ("pi_hurt", "unknown") in paid.disputes
    assert paid.dispute_errors and "403" in paid.dispute_errors[0]
    src = Path(subscriptions.__file__).read_text(encoding="utf-8")
    assert ".dispute\")" not in src


def test_a_lost_subscription_chargeback_ends_entitlement(monkeypatch) -> None:
    """The subscription half: a lost chargeback on the latest invoice's charge
    drops the subscription like a full refund, read through the same lookup."""
    from run import subscriptions
    charge = {"id": "ch_sub", "amount": 3900, "amount_refunded": 0, "disputed": True}
    sub = {"id": "sub_lost", "customer": {"email": "a@example.com"},
           "latest_invoice": {"charge": charge}}

    def get(url, key):
        if url.startswith(subscriptions.DISPUTES_API):
            return {"data": [{"status": "lost"}]}
        if "status=active" in url:
            return {"data": [sub], "has_more": False}
        return {"data": [], "has_more": False}
    monkeypatch.setattr(subscriptions, "_stripe_get", get)
    paid = subscriptions.load_paid_from_stripe("rk_test")
    assert "sub_lost" in paid.refunded and not paid.covers("a@example.com")


def test_a_dispute_waiting_on_us_turns_the_intake_red(monkeypatch, capsys) -> None:
    from run import subscriptions
    listed = subscriptions.PaidList(emails=frozenset(), source="stripe", status_column=None,
                                    disputes=(("pi_open", "needs_response"),
                                              ("pi_review", "under_review")))
    monkeypatch.setattr(subscriptions, "load_paid_from_stripe", lambda key: listed)
    assert intake.dispute_alarm("sk") is True
    err = capsys.readouterr().err
    assert "DISPUTE NEEDS A RESPONSE: pi_open" in err and "@" not in err
    calm = subscriptions.PaidList(emails=frozenset(), source="stripe", status_column=None,
                                  disputes=(("pi_review", "under_review"),))
    monkeypatch.setattr(subscriptions, "load_paid_from_stripe", lambda key: calm)
    assert intake.dispute_alarm("sk") is False


# --------------------------------------------------------------------- #
# critique #1 — bounces
# --------------------------------------------------------------------- #

def test_a_bounced_paid_email_is_found_and_said_without_an_address(monkeypatch, capsys) -> None:
    """Reproduced: grepping run/ render/ infra/ for bounce|complain|webhook
    found nothing — a mistyped buyer address got its welcome and every report
    "sent". After each mailing run the intake now asks Resend for the recent
    message ids already in the send log: first contact first, unpaid mail
    last, a bounce or complaint on paid mail an alarm (exit 1), printed by
    send-log key only."""
    from run import delivery
    now = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    old = (now - timedelta(days=4)).isoformat(timespec="seconds")
    entries = [
        {"key": "2026-w07-aaaa", "provider": "resend", "message_id": "m1", "sent_at": recent},
        {"key": "welcome-1761200000-bbbb", "provider": "resend", "message_id": "m2",
         "sent_at": recent},
        {"key": "trial-2026-cccc", "provider": "resend", "message_id": "m3", "sent_at": recent},
        {"key": "welcome-old-dddd", "provider": "resend", "message_id": "m4", "sent_at": old},
        {"key": "preseason-x-eeee", "provider": "resend", "message_id": "resend:accepted",
         "sent_at": recent},
        {"key": "renewal-x-ffff", "provider": "postmark", "message_id": "m6", "sent_at": recent},
    ]
    order = [e["key"] for e in delivery.lookup_order(entries, now)]
    assert order == ["welcome-1761200000-bbbb", "2026-w07-aaaa", "trial-2026-cccc"]
    events = {"m1": "delivered", "m2": "bounced", "m3": "complained"}
    report = delivery.check_bounces(entries, now, lookup=events.get, pause=0)
    assert report.paid == [("welcome-1761200000-bbbb", "bounced")]
    assert report.unpaid == [("trial-2026-cccc", "complained")] and report.checked == 3
    assert delivery.check_bounces(entries, now, api_key="").skipped
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(intake, "_sent_entries", lambda: entries)
    real_check = delivery.check_bounces
    monkeypatch.setattr(delivery, "check_bounces",
                        lambda e, n: real_check(e, n, lookup=events.get, pause=0))
    assert intake.bounce_alarm(now) is True
    err = capsys.readouterr().err
    assert "PAID EMAIL BOUNCED: welcome-1761200000-bbbb" in err and "@" not in err
    events["m2"] = "delivered"
    assert intake.bounce_alarm(now) is False


def test_a_send_only_resend_key_is_found_in_one_request_and_said_once(
        monkeypatch, capsys) -> None:
    """Reproduced (pre-launch review): LAUNCH.md has the owner create the
    Resend key with Sending access, which "can only send emails", so every
    GET /emails/{id} was refused. check_bounces counted 30 errors, slept
    about 16 s doing it, checked 0, and the run printed one stderr line and
    exited 0 — a buyer with a mistyped address stayed invisible, the case the
    check exists for. Now the first 401/403 stops the lookups and the run
    says, once, as an OWNER line, which key is missing; the lookup prefers
    RESEND_READ_KEY over the sending key."""
    from run import delivery
    now = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    entries = [{"key": f"welcome-{i}-abcd", "provider": "resend",
                "message_id": f"m{i}", "sent_at": recent} for i in range(5)]
    calls: list[str] = []

    def refused(message_id):
        calls.append(message_id)
        raise delivery.KeyCannotRead("HTTP 401 from Resend")
    report = delivery.check_bounces(entries, now, api_key="re_x", lookup=refused, pause=0)
    assert len(calls) == 1, "one refusal answers for every lookup"
    assert report.key_cannot_read and report.checked == 0 and not report.paid
    used: list[str] = []
    monkeypatch.setattr(delivery, "resend_last_event",
                        lambda message_id, key: used.append(key) or "delivered")
    monkeypatch.setenv("RESEND_API_KEY", "re_send_only")
    monkeypatch.setenv("RESEND_READ_KEY", "re_full")
    delivery.check_bounces(entries[:1], now, pause=0)
    assert used == ["re_full"]
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(intake, "_sent_entries", lambda: entries)
    real_check = delivery.check_bounces
    monkeypatch.setattr(delivery, "check_bounces",
                        lambda e, n: real_check(e, n, lookup=refused, pause=0))
    capsys.readouterr()
    assert intake.bounce_alarm(now) is False
    out = capsys.readouterr().out
    assert out.count("OWNER: bounces are not checked") == 1 and "RESEND_READ_KEY" in out


def test_the_resend_lookup_never_echoes_the_key(monkeypatch) -> None:
    import urllib.error
    import urllib.request

    from run import delivery

    def refuse(request, timeout=20):
        assert request.full_url == "https://api.resend.com/emails/abc%2F1"
        raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(delivery.DeliveryError) as caught:
        delivery.resend_last_event("abc/1", "re_secret_key")
    assert "re_secret_key" not in str(caught.value)
