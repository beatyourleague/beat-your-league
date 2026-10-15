/**
 * The form backend — one Cloudflare Worker, pasted into the dashboard.
 *
 * It exists for the three kinds of row the static site cannot store itself:
 * League Pass SEAT claims, self-serve roster UPDATES, and the launch WAITLIST.
 * All three post from the site and are read back by their own runners —
 * run/intake.py validates seats and updates before anything reaches the
 * registry (a seat is honoured only if its payer bought a pass, an update only
 * if it carries the subscriber's token), and run/waitlist.py sends the single
 * promised launch email. This Worker therefore holds nothing secret and
 * decides nothing: it is a mailbox.
 *
 * Why a Worker and not a form vendor: free-tier form products cap at ~50
 * submissions a month or offer no machine-readable read-back, and this is the
 * same Cloudflare account the domain's DNS and email routing already live in.
 * The mailbox is ~60 lines, costs nothing at this scale (KV free tier: 1,000
 * writes and 100,000 reads a day), and the whole file — the scheduler below
 * included — is readable in one sitting.
 *
 * Setup (LAUNCH.md step 5): Workers & Pages → Create → paste this file →
 * Settings → Bindings → KV namespace, variable name ROWS → Variables:
 *   SITE_ORIGIN   = https://<domain>        (CORS; the only page allowed to POST)
 *   FORM_API_KEY  = <random>                (secret; the intake's read key)
 * Then FORM_ENDPOINT = the Worker URL, in both the page and the GitHub secret.
 *
 * Limits worth knowing (Cloudflare free tier): 1,000 KV writes a day, so a
 * determined stranger can exhaust the day's writes and make seats, updates and
 * the waitlist refuse until tomorrow — nothing is lost that was already stored,
 * and the intake (which only READS) is unaffected.
 *
 * Contract (matches run/intake.py fetch_seats + run/updates.py):
 *   POST JSON  {kind:"seat",     email, covered_by, ref}
 *   POST JSON  {kind:"update",   email, ref, replaces, token}
 *   POST JSON  {kind:"update_request", email, ref}   (confirm-by-email, step 1)
 *   POST JSON  {kind:"confirm",  code}                (step 2: the inbox's code)
 *   POST JSON  {kind:"trial",    email, ref}          (the free first report)
 *   POST JSON  {kind:"waitlist", email}
 *   GET  + Authorization: Bearer <FORM_API_KEY>  →  JSON array of stored rows
 * Every kind may also carry an optional `via` (^[a-z0-9-]{1,24}$, e.g. "x" or
 * "reply-kit"): where the visitor came from, read off the page's own URL, so
 * the owner can see which channel brings people without a cookie or a
 * tracker anywhere. Anything else in that field is dropped, never refused —
 * a bad attribution tag must not cost a signup.
 *
 * Rows EXPIRE about 400 days after they arrive (ROW_TTL_SECONDS). The privacy
 * page says form entries delete themselves within about 13 months of
 * arriving, and this TTL is the only thing that makes that true — before it,
 * nothing here ever deleted anything; every row
 * lived in KV forever. 400 days is the longest any row is needed: a
 * seat claim is re-read every week of the season it was made for (the roster
 * it names is that season's), a waitlist address waits at most one offseason
 * for its launch email, and everything else is acted on within days — a
 * confirmed roster update is copied into the intake's own log, a confirmation
 * code dies after 7 days, and a trial request is mailed within 14 days of
 * arriving or never (run/trials.py TRIAL_MAX_AGE, which also refuses one from
 * before the current season's first game). The row itself keeps the shared
 * TTL, which is harmless only because of that refusal: the trial key is per
 * SEASON, so a runner that re-read every stored row once mailed last
 * October's request again the next June.
 *
 * ── THE SCHEDULER (Oct 2026) ──────────────────────────────────────────────
 * GitHub's own cron is best-effort, and in practice it was not good enough:
 * it started the Tuesday runs 5-7 hours late on Oct 6 and Oct 13 2026 and
 * dropped most of the hourly ones, so "Tuesday morning" and "within the hour"
 * were promises nothing kept. Cloudflare's Cron Triggers are free and fire on
 * time, so this Worker also starts the workflows itself, through GitHub's
 * workflow_dispatch API, at exactly the UTC times the workflows' own
 * `schedule:` blocks name (SCHEDULE below — tests/test_scheduling.py fails if
 * the two lists ever disagree). The GitHub schedules stay as the backup.
 *
 * Firing a workflow twice is safe, and that is checked rather than hoped: each
 * workflow queues in its own concurrency group (never cancelling a run in
 * progress), checks out the branch TIP rather than the commit it was
 * triggered on (so a queued second run reads the send log the first one
 * pushed), and every message carries a key in data/processed/sent.jsonl that
 * a second run finds and skips.
 *
 * Setup for the scheduler (after the steps above):
 *   Worker → Settings → Triggers → Cron Triggers → add ONE trigger:
 *     0,30 * * * *        (UTC — every half hour; the handler picks what is due)
 *   Worker → Settings → Variables → add, marked SECRET:
 *     GH_DISPATCH_TOKEN = a fine-grained GitHub token: Resource owner
 *                         beatyourleague, Repository access "Only select
 *                         repositories" → beat-your-league, Repository
 *                         permissions → Actions: Read and write. Nothing else.
 *                         It expires (a year at most) — diary the date.
 * With GH_DISPATCH_TOKEN unset the scheduler does nothing at all and the
 * GitHub schedules carry on alone. A failed dispatch shows as an error under
 * the Worker's Cron Events; the next tick and the GitHub backup both still run.
 */

const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
const REF = /^[A-Za-z0-9_-]{1,200}$/;
const SLUG = /^[0-9a-f]{10}$/;
const TOKEN = /^[0-9a-f]{20}$/;
const CODE = /^[0-9a-f]{24}$/;
const VIA = /^[a-z0-9-]{1,24}$/;
const MAX_BODY = 2048;
const ROW_TTL_SECONDS = 400 * 24 * 60 * 60;

function sanitizeKind(body) {
  const kind = ["update", "update_request", "confirm", "waitlist", "trial"]
    .includes(body.kind) ? body.kind : "seat";
  if (kind === "confirm") {
    // Only the code. It means something only if it matches a request the
    // intake itself signed and mailed to the subscriber's own address.
    const code = String(body.code || "").trim().toLowerCase();
    return CODE.test(code) ? { kind, code } : null;
  }
  const email = String(body.email || "").trim().toLowerCase();
  if (!EMAIL.test(email) || email.length > 254) return null;
  if (kind === "waitlist") {
    // The launch list holds the address (plus the optional via tag sanitize()
    // adds to every kind).
    return { kind, email };
  }
  const ref = String(body.ref || "").trim();
  if (!REF.test(ref)) return null;
  if (kind === "trial") {
    // One free report per address per season, enforced by run/trials.py.
    return { kind, email, ref };
  }
  if (kind === "update_request") {
    // Grants nothing by itself: the intake mails a confirmation to the
    // address on the subscription, and only that inbox can finish it.
    return { kind, email, ref };
  }
  if (kind === "seat") {
    const payer = String(body.covered_by || "").trim().toLowerCase();
    if (!EMAIL.test(payer) || payer.length > 254) return null;
    return { kind, email, ref, covered_by: payer };
  }
  const replaces = String(body.replaces || "").trim();
  const token = String(body.token || "").trim();
  if (!SLUG.test(replaces) || !TOKEN.test(token)) return null;
  return { kind, email, ref, replaces, token };
}

function sanitize(body) {
  if (!body || typeof body !== "object") return null;
  const row = sanitizeKind(body);
  if (!row) return null;
  // Attribution rides along on any kind and decides nothing. Validated to a
  // shape that cannot carry an address or markup into the owner's stats.
  const via = String(body.via || "").trim().toLowerCase();
  return VIA.test(via) ? { ...row, via } : row;
}

// ── the scheduler ────────────────────────────────────────────────────────

const REPO = "beatyourleague/beat-your-league";
const BRANCH = "main";

// Each `cron` is the LITERAL string from that workflow's own `schedule:` block
// (UTC). Only daily.yml takes an input: its once-a-day steps (stopping monthly
// billing at season's end, the missed-run watchdog) run on the 14:00 dispatch
// and never on the hourly ones — a dispatch has no `github.event.schedule` to
// tell them apart, so the input does.
const SCHEDULE = [
  { cron: "0 12 * * 2", workflow: "weekly.yml" },     // Tuesday's reports
  { cron: "0 16 * * 2", workflow: "weekly.yml" },     // ...the same-morning retry
  { cron: "0 14 * * *", workflow: "daily.yml", inputs: { daily: "true" } },
  { cron: "30 * * * *", workflow: "daily.yml", inputs: { daily: "false" } },
  { cron: "0 16 * * 6", workflow: "saturday.yml" },   // the final check
  { cron: "0 13 * * 1", workflow: "monday.yml" },     // grading
];

// Plain numbers, comma lists and `*` — the only syntax the workflows use. A
// field this does not understand matches nothing, and the test that compares
// SCHEDULE with the workflows refuses any such field before it can ship.
function fieldMatches(field, value) {
  return field === "*" || field.split(",").some((part) => Number(part) === value);
}

function due(at) {
  return SCHEDULE.filter(({ cron }) => {
    const [minute, hour, day, month, weekday] = cron.split(" ");
    return fieldMatches(minute, at.getUTCMinutes())
      && fieldMatches(hour, at.getUTCHours())
      && fieldMatches(day, at.getUTCDate())
      && fieldMatches(month, at.getUTCMonth() + 1)
      && fieldMatches(weekday, at.getUTCDay());
  });
}

async function dispatch(entry, env) {
  const repo = env.GH_REPO || REPO;
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${entry.workflow}/dispatches`;
  // Inputs are strings: the API refuses a JSON boolean for a boolean input.
  const body = entry.inputs ? { ref: BRANCH, inputs: entry.inputs } : { ref: BRANCH };
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_DISPATCH_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      // GitHub's API refuses a request that names no User-Agent.
      "User-Agent": "beat-your-league-scheduler",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${entry.workflow} (${entry.cron}): HTTP ${response.status}`);
  }
  return `${entry.workflow} (${entry.cron})`;
}

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.SITE_ORIGIN || "*",
      "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    };
    const json = (value, status = 200) =>
      new Response(JSON.stringify(value), {
        status, headers: { ...cors, "Content-Type": "application/json" },
      });

    if (request.method === "OPTIONS") return new Response(null, { headers: cors });

    if (request.method === "POST") {
      const text = await request.text();
      if (text.length > MAX_BODY) return json({ error: "too large" }, 413);
      let body;
      try { body = JSON.parse(text); } catch { return json({ error: "bad json" }, 400); }
      const row = sanitize(body);
      if (!row) return json({ error: "bad row" }, 400);
      // The key orders rows by arrival. `received_at` is stamped HERE, by this
      // Worker's own clock — sanitize() drops any field the caller invents, so a
      // request cannot choose its own timestamp — and it is what a roster-update
      // confirmation code binds to (run/updates.py).
      const key = `${Date.now().toString().padStart(14, "0")}-${crypto.randomUUID()}`;
      const stored = { ...row, received_at: new Date().toISOString() };
      // The whole row lives in the key's METADATA (1 KB), not in a value that
      // must be fetched one row at a time: reading N rows was N+1 KV calls per
      // hourly intake, which a free-tier Worker may refuse past ~50 — and a
      // failed read makes run/intake.py refuse to write the registry at all.
      // One list() call now returns everything. The longest legitimate row (a
      // seat: two addresses, a ref and a `via`) is ~790 bytes.
      if (JSON.stringify(stored).length > 1000) return json({ error: "too large" }, 413);
      await env.ROWS.put(key, "1", { metadata: stored, expirationTtl: ROW_TTL_SECONDS });
      return json({ ok: true });
    }

    if (request.method === "GET") {
      const auth = request.headers.get("Authorization") || "";
      if (!env.FORM_API_KEY || auth !== `Bearer ${env.FORM_API_KEY}`) {
        return json({ error: "unauthorized" }, 401);
      }
      const rows = [];
      let cursor;
      do {
        const page = await env.ROWS.list({ cursor });
        for (const entry of page.keys) {
          if (entry.metadata) rows.push(entry.metadata);
        }
        cursor = page.list_complete ? undefined : page.cursor;
      } while (cursor);
      return json(rows);
    }

    return json({ error: "method" }, 405);
  },

  // The Cron Trigger. `scheduledTime` is the minute the trigger was due, not
  // when this invocation happened to start, so a slow start can never shift a
  // run into the wrong slot.
  async scheduled(controller, env) {
    if (!env.GH_DISPATCH_TOKEN) {
      console.log("scheduler: GH_DISPATCH_TOKEN is not set; nothing dispatched "
        + "(the GitHub schedules still run)");
      return;
    }
    const entries = due(new Date(controller.scheduledTime));
    const results = await Promise.allSettled(entries.map((entry) => dispatch(entry, env)));
    const failed = results.filter((r) => r.status === "rejected").map((r) => String(r.reason));
    for (const r of results) {
      if (r.status === "fulfilled") console.log(`scheduler: dispatched ${r.value}`);
    }
    // Thrown, so the miss shows as an error under the Worker's Cron Events
    // rather than as a quiet log line. The GitHub schedule is still the backup.
    if (failed.length) throw new Error(`scheduler: ${failed.join("; ")}`);
  },
};
