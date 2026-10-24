/**
 * The form backend — one Cloudflare Worker, pasted into the dashboard.
 *
 * It exists for the three kinds of row the static site cannot store itself:
 * League Pass SEAT claims, self-serve roster UPDATES, and the launch WAITLIST.
 * All three post from the site and are read back by their own runners —
 * run/intake.py validates seats and updates before anything reaches the
 * registry (a seat claim is honoured only if it names a pass that was bought
 * and is still active, AND the claimed address confirms it from its own inbox;
 * an update only once its subscriber confirms it), and run/waitlist.py sends
 * the single promised launch email. This Worker therefore holds nothing secret
 * and decides nothing: it is a mailbox.
 *
 * Why a Worker and not a form vendor: free-tier form products cap at ~50
 * submissions a month or offer no machine-readable read-back, and this is the
 * same Cloudflare account the domain's DNS and email routing already live in.
 * The mailbox is ~60 lines, costs nothing at this scale (KV free tier: 1,000
 * writes and 100,000 reads a day), and the whole file — the scheduler below
 * included — is readable in one sitting.
 *
 * Setup (LAUNCH.md step 5): Workers & Pages → Create → paste this file →
 * Settings → Bindings → KV namespace, variable name ROWS → (optional, for the
 * visit counter) Analytics Engine dataset "byl_counts", variable name COUNTS →
 * Variables:
 *   SITE_ORIGIN   = https://<domain>        (the only page allowed to POST;
 *                                           https://beatyourleague.com is
 *                                           always allowed too)
 *   FORM_API_KEY  = <random>                (secret; the intake's read key)
 *   TRIAL_OPEN    = true                    (ONLY once the free report is
 *                                           switched on on the site; unset,
 *                                           a free-report request is refused)
 * Then FORM_ENDPOINT = the Worker URL, in both the page and the GitHub secret.
 * Also (owner, Cloudflare dashboard): one free rate-limiting rule on the
 * Worker's route for POST, a few a minute per IP, and the workers.dev route
 * switched OFF so the rule cannot be walked around.
 *
 * Abuse, and what bounds it (pre-launch review APPSEC-3, INFRA-03):
 * - A POST must come from the site (its Origin) or carry the read key (the
 *   operator's `make roster-update`). A page elsewhere cannot make a visitor's
 *   browser post here, and every refusal still answers with CORS headers.
 * - Rows are stored under a KIND PREFIX ("seat:", "trial:", …), and a reader
 *   asks only for the kinds it reads (GET ?kinds=seat,confirm). A flood of one
 *   kind never makes the hourly intake walk it.
 * - A waitlist or free-report row is ONE row per (kind, mailbox, UTC day):
 *   its key is derived from the canonical address (run/trials.canonical_email,
 *   ported below), so a repeat overwrites rather than piling up — and a
 *   waitlist row carrying a roster keeps its own key, so an email-only row
 *   the same day never erases the roster the launch email restores. Never for a
 *   seat claim, a roster request or a confirmation: overwriting by address
 *   would let a stranger's request replace the real one and move the stamp
 *   its emailed code is bound to.
 * - Free-plan KV allows 1,000 writes a day. A determined stranger can still
 *   exhaust them and make new posts refuse until tomorrow (each answers 503,
 *   never a silent drop). Nothing already stored is lost, and the intake
 *   still registers every Stripe payer and every logged seat while the read
 *   fails (run/intake.py) — a form outage costs form posts, never sales.
 *
 * Contract (matches run/intake.py fetch_seats + run/updates.py):
 *   POST JSON  {kind:"seat",     email, ref, pass_token}   (a seat names its
 *                                pass ONLY by the per-pass seat link's code —
 *                                contract C3; a typed buyer address is no
 *                                longer a way in, and is not stored)
 *   POST JSON  {kind:"update",   email, ref, token, replaces?}  (no replaces:
 *                                the operator's emailed change, run/updates.py;
 *                                accepted ONLY with the read key — 403 from the
 *                                site's own Origin, final review SEC-1)
 *   POST JSON  {kind:"update_request", email, ref, replaces?}  (confirm-by-
 *                                email, step 1; replaces = the link's &o= tag,
 *                                12 hex — run/updates.py origin_tag)
 *   POST JSON  {kind:"confirm",  code}                (step 2: the inbox's code —
 *                                for a roster request OR a seat claim; the
 *                                intake knows which by recomputing both)
 *   POST JSON  {kind:"trial",    email, ref}          (the free first report;
 *                                refused unless TRIAL_OPEN is "true")
 *   POST JSON  {kind:"waitlist", email, ref?}         (ref: the roster checked
 *                                while checkout was closed, run/waitlist.py)
 *   Any other kind is refused (400). Every refusal is a 4xx/5xx with CORS.
 *   GET  + Authorization: Bearer <FORM_API_KEY>  →  JSON array of stored rows,
 *                                each carrying its storage key as `_key`,
 *                                oldest first; ?kinds=a,b limits it to those;
 *                                ?status=1 answers {trial_open, counts} instead
 *   DELETE ?key=<_key> + Authorization: Bearer <FORM_API_KEY>  →  removes one
 *                                row (a deletion request, run/privacy.py)
 *   POST /e  text/plain {e, p, v, r, d, s}  →  ALWAYS 204, never a cookie: one
 *                                anonymous visit count (contract C1) written to
 *                                Analytics Engine (COUNTS), never to KV. Every
 *                                field must match ^[a-z0-9.-]{0,40}$ or the
 *                                count is dropped; only the site's Origin
 *                                counts; with COUNTS unbound it does nothing.
 *                                Blob order: event, page, via, referrer host,
 *                                device, checkout state, country.
 * Every kind may also carry an optional `via` (^[a-z0-9-]{1,24}$, e.g. "x" or
 * "reply-kit"): where the visitor came from, read off the page's own URL, so
 * the owner can see which channel brings people without a cookie or a
 * tracker anywhere. Anything else in that field is dropped, never refused —
 * a bad attribution tag must not cost a signup.
 *
 * Rows EXPIRE (ROW_TTL_SECONDS for the waitlist, SHORT_ROW_TTL_SECONDS for
 * everything else). The privacy page says form entries delete themselves
 * within about 13 months of arriving, and these TTLs are the only thing that
 * makes that true. A waitlist address waits at most one offseason for its
 * launch email, so it keeps ~400 days; every other kind is acted on within
 * two weeks or never — a seat claim is needed only until its address
 * confirms it (7 days at most; a confirmed seat is copied into the intake's
 * own seat log, so no seat depends on a row here, OPS-R6), a confirmed roster
 * update is copied into the intake's own log, a confirmation code dies after
 * 7 days, and a trial request is mailed within 14 days of arriving or never
 * (run/trials.py TRIAL_MAX_AGE). So those keep 30 days, which also caps how
 * much a flood can leave behind for the hourly reads to walk.
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
 *     17,47 * * * *       (UTC — every half hour, off the top of the hour; the
 *                          handler picks what is due)
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

// The same set the join page and run/rosters.py accept (anything@anything.tld,
// apostrophes and non-ASCII included): a stricter Worker answered 400 to an
// address the page had passed and a subscription could hold (JOIN-129).
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// A LONE UTF-16 surrogate (JSON "\ud800") is one character to EMAIL above,
// so the row was stored — and Python's json.loads rebuilt it, and the first
// .encode("utf-8") in every reader raised: one anonymous POST stopped every
// intake run, the free report, the launch email and the privacy tool for the
// row's whole life (final review SEC-1). Refused here, beside EMAIL rather
// than in it: EMAIL is the one rule the page and run/rosters.py share
// (JOIN-129). Emoji, accents and apostrophes are whole code points and pass.
const LONE_SURROGATE = /\p{Cs}/u;
const REF =/^[A-Za-z0-9_-]{1,200}$/;
const SLUG = /^[0-9a-f]{10}$/;
// The update link's &o= (run/updates.py origin_tag, ORIGIN_TAG_LENGTH = 12):
// an HMAC of the subscription's origin slug, posted back as `replaces` on an
// update_request. SLUG above is the raw 10-hex origin the operator's
// kind:"update" carries; a 10-hex test here dropped every report link's tag
// (pre-launch review APPSEC-5).
const ORIGIN_TAG = /^[0-9a-f]{12}$/;
const TOKEN = /^[0-9a-f]{20}$/;
const CODE = /^[0-9a-f]{24}$/;
const VIA = /^[a-z0-9-]{1,24}$/;
// BYTES, not characters: KV's metadata limit is 1,024 bytes, and a row of
// non-ASCII characters passed a character count and then threw inside put()
// with no CORS header (APPSEC-3).
const MAX_BODY = 2048;
const MAX_ROW_BYTES = 1000;
const ROW_TTL_SECONDS = 400 * 24 * 60 * 60;
const SHORT_ROW_TTL_SECONDS = 30 * 24 * 60 * 60;
// Every kind a row may be. Anything else is refused: an unknown kind used to
// be stored as a seat.
const KINDS = ["seat", "update", "update_request", "confirm", "trial", "waitlist"];
// One row per (kind, mailbox, UTC day) for these two — see the header.
const ONE_A_DAY = ["trial", "waitlist"];
// Where a POST may come from, besides the site's own SITE_ORIGIN.
const HOME_ORIGIN = "https://beatyourleague.com";
const encoder = new TextEncoder();
const bytes = (text) => encoder.encode(text).length;

// run/trials.py canonical_email, line for line (tests/test_prelaunch_worker.py
// runs both on the same addresses): lowercase, no `+tag`, and no dots in a
// Gmail local part.
function canonicalEmail(email) {
  const address = String(email || "").trim().toLowerCase();
  const at = address.indexOf("@");
  let local = at === -1 ? address : address.slice(0, at);
  let domain = at === -1 ? "" : address.slice(at + 1);
  local = local.split("+", 1)[0];
  if (domain === "gmail.com" || domain === "googlemail.com") {
    local = local.replace(/\./g, "");
    domain = "gmail.com";
  }
  return `${local}@${domain}`;
}

async function sha256hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// The storage key. Every kind sits under its own prefix, so a reader lists
// only what it reads. A waitlist or trial row is keyed by its mailbox and day
// (a repeat overwrites); every other row by its arrival, which orders them.
// A waitlist row that carries a roster (`ref`, contract C6) has a key of its
// own (":r"): the landing's email-only capture posted the same day used to
// overwrite it and erase the roster the launch email restores (pre-launch
// review). run/waitlist.py saved_refs takes the newest ref per mailbox.
async function storageKey(row, now) {
  if (ONE_A_DAY.includes(row.kind)) {
    const day = now.toISOString().slice(0, 10);
    const box = (await sha256hex(canonicalEmail(row.email))).slice(0, 32);
    return `${row.kind}:${day}:${box}${row.kind === "waitlist" && row.ref ? ":r" : ""}`;
  }
  return `${row.kind}:${now.getTime().toString().padStart(14, "0")}-${crypto.randomUUID()}`;
}

function sanitizeKind(body) {
  const kind = body.kind;
  if (!KINDS.includes(kind)) return null;
  if (kind === "confirm") {
    // Only the code. It means something only if it matches a request the
    // intake itself signed and mailed to the subscriber's own address.
    const code = String(body.code || "").trim().toLowerCase();
    return CODE.test(code) ? { kind, code } : null;
  }
  const email = String(body.email || "").trim().toLowerCase();
  if (!EMAIL.test(email) || email.length > 254 || LONE_SURROGATE.test(email)) return null;
  if (kind === "waitlist") {
    // The launch list holds the address (plus the optional via tag sanitize()
    // adds to every kind) and, when checkout was closed for the plan picked
    // AFTER a roster was checked (contract C6), the ref that checkout would
    // have used — so the one launch email can bring the roster back instead
    // of asking for fifteen names again. A ref that is not that shape is
    // dropped, never a refused row: a bad ref must not cost a sign-up.
    const saved = String(body.ref || "").trim();
    return REF.test(saved) ? { kind, email, ref: saved } : { kind, email };
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
    // `replaces` is the origin slug the report's update link carried (&o=):
    // it picks which of the address's teams, never authorises one. A
    // malformed slug is dropped, never refused — the intake can still choose.
    const replaces = String(body.replaces || "").trim().toLowerCase();
    return ORIGIN_TAG.test(replaces) ? { kind, email, ref, replaces } : { kind, email, ref };
  }
  if (kind === "seat") {
    // A seat names its pass ONLY by the per-pass seat link's `pass_token`
    // (contracts C3/C4) — a digest the intake recomputes over the passes
    // really bought, so the buyer's address is never typed, shared or
    // guessed. The typed `covered_by` route let anyone who knew a buyer's
    // address take every seat on the pass, and its replies told a stranger
    // whether that address had bought one (APPSEC-2): it is not stored. A
    // claim is only a request: the intake mails the claimed address a code,
    // and the seat exists once {kind:"confirm", code} comes back (OPS-R1).
    const passToken = String(body.pass_token || "").trim().toLowerCase();
    return TOKEN.test(passToken) ? { kind, email, ref, pass_token: passToken } : null;
  }
  // An update names the subscription it replaces — except the OPERATOR's
  // (`make roster-update`, run/updates.py), sent for a subscriber who emailed
  // a new roster: the token authenticates it, and the intake picks the team.
  const replaces = String(body.replaces || "").trim();
  const token = String(body.token || "").trim();
  if (!TOKEN.test(token) || (replaces && !SLUG.test(replaces))) return null;
  return replaces ? { kind, email, ref, replaces, token } : { kind, email, ref, token };
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

// The read key, compared without an early exit (APPSEC-3: remote timing is
// not practical here, and this costs nothing).
function sameSecret(given, expected) {
  const a = encoder.encode(String(given));
  const b = encoder.encode(String(expected));
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    diff |= (a[i] || 0) ^ (b[i] || 0);
  }
  return diff === 0;
}

function authorized(request, env) {
  return Boolean(env.FORM_API_KEY) && sameSecret(
    request.headers.get("Authorization") || "", `Bearer ${env.FORM_API_KEY}`);
}

function siteOrigins(env) {
  return [env.SITE_ORIGIN, HOME_ORIGIN].filter(Boolean);
}

// The Origin this request came from, when it is the site; null otherwise.
function siteOrigin(request, env) {
  const origin = request.headers.get("Origin") || "";
  return siteOrigins(env).includes(origin) ? origin : null;
}

// ── the visit counter (contract C1) ──────────────────────────────────────

const COUNT_FIELD = /^[a-z0-9.-]{0,40}$/;
const COUNT_EVENTS = ["view", "roster", "checkout", "waitlist", "trial"];
const COUNT_PAGES = ["index", "join", "join-pass", "join-try", "league-pass",
  "how-it-works", "thanks", "sample", "this-week", "first-week", "404", "other"];
const MAX_COUNT_BODY = 512;

// One count row, or null to drop the request. Pure.
function countRow(text, country) {
  if (bytes(text) > MAX_COUNT_BODY) return null;
  let body;
  try { body = JSON.parse(text); } catch { return null; }
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const fields = {};
  for (const name of ["e", "p", "v", "r", "d", "s"]) {
    const value = body[name] === undefined ? "" : body[name];
    if (typeof value !== "string" || !COUNT_FIELD.test(value)) return null;
    fields[name] = value;
  }
  if (!COUNT_EVENTS.includes(fields.e)) return null;
  if (!["m", "d", ""].includes(fields.d) || !["open", "closed", ""].includes(fields.s)) {
    return null;
  }
  const page = COUNT_PAGES.includes(fields.p) ? fields.p : "other";
  const where = /^[A-Z]{2}$/.test(String(country || "")) ? String(country) : "";
  return {
    blobs: [fields.e, page, fields.v, fields.r, fields.d, fields.s, where],
    doubles: [1],
    indexes: [fields.e],
  };
}

// ALWAYS an empty 204 with CORS for the site, never a cookie, and nothing a
// visitor's browser can be made to wait on: writeDataPoint is not awaited and
// a failure inside it is swallowed. A count never touches ROWS.
async function count(request, env) {
  const origin = siteOrigin(request, env);
  const headers = {
    "Access-Control-Allow-Origin": origin || env.SITE_ORIGIN || HOME_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
    "Vary": "Origin",
  };
  const done = () => new Response(null, { status: 204, headers });
  if (request.method !== "POST" || !origin || !env.COUNTS) return done();
  if (Number(request.headers.get("Content-Length") || "0") > MAX_COUNT_BODY) return done();
  try {
    const row = countRow(await request.text(), request.cf && request.cf.country);
    if (row) env.COUNTS.writeDataPoint(row);
  } catch { /* a counter never fails a request */ }
  return done();
}

// ── the scheduler ────────────────────────────────────────────────────────

const REPO = "beatyourleague/beat-your-league";
const BRANCH = "main";

// Each `cron` is the LITERAL string from that workflow's own `schedule:` block
// (UTC). Only daily.yml takes an input: its once-a-day steps (stopping monthly
// billing at season's end, the missed-run watchdog) run on the 14:00 dispatch
// and never on the hourly ones — a dispatch has no `github.event.schedule` to
// tell them apart, so the input does.
//
// Every cron sits at minute :17 or :47, never :00 (OPS-01): the top of the
// hour is when GitHub's scheduler is busiest and most often late, so the
// backups land off-peak, and the Worker's one trigger (17,47 * * * *) fires
// at the same minutes so both sides keep one time per job. The half hour
// between :17 and :47 is what keeps the hourly intake from ever starting
// beside the Tuesday or Saturday runs.
const SCHEDULE = [
  { cron: "17 12 * * 2", workflow: "weekly.yml" },     // Tuesday's reports
  { cron: "17 16 * * 2", workflow: "weekly.yml" },     // ...the same-morning retry
  { cron: "17 14 * * *", workflow: "daily.yml", inputs: { daily: "true" } },
  { cron: "47 * * * *", workflow: "daily.yml", inputs: { daily: "false" } },
  { cron: "17 16 * * 6", workflow: "saturday.yml" },   // the final check
  { cron: "17 13 * * 1", workflow: "monday.yml" },     // grading
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
    const url = new URL(request.url);
    if (url.pathname === "/e") return count(request, env);

    const origin = siteOrigin(request, env);
    // CORS names the site, never "*" (fail closed when SITE_ORIGIN is unset).
    const cors = {
      "Access-Control-Allow-Origin": origin || env.SITE_ORIGIN || HOME_ORIGIN,
      "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
      "Vary": "Origin",
    };
    const json = (value, status = 200) =>
      new Response(JSON.stringify(value), {
        status, headers: { ...cors, "Content-Type": "application/json" },
      });

    if (request.method === "OPTIONS") return new Response(null, { headers: cors });

    if (request.method === "POST") {
      // From the site's own pages, or from the operator holding the read key.
      if (!origin && !authorized(request, env)) return json({ error: "origin" }, 403);
      if (Number(request.headers.get("Content-Length") || "0") > MAX_BODY) {
        return json({ error: "too large" }, 413);
      }
      const text = await request.text();
      if (bytes(text) > MAX_BODY) return json({ error: "too large" }, 413);
      let body;
      try { body = JSON.parse(text); } catch { return json({ error: "bad json" }, 400); }
      const row = sanitize(body);
      if (!row) return json({ error: "bad row" }, 400);
      // A roster UPDATE is the operator's route alone (`make roster-update`,
      // run/updates.py post_row, which sends the read key). No report link
      // has ever carried a token, and the public door to it is how one
      // anonymous row reached the intake's update validator (final review
      // SEC-1): from the site's Origin it is refused, whatever it carries.
      if (row.kind === "update" && !authorized(request, env)) {
        return json({ error: "unauthorized" }, 403);
      }
      // SEC-06: a free report is served only while the site offers one. The
      // runner checks the site too (run/trials.py); this keeps a request sent
      // straight here from being stored at all.
      if (row.kind === "trial" && env.TRIAL_OPEN !== "true") {
        return json({ error: "free reports are not open" }, 403);
      }
      // `received_at` is stamped HERE, by this Worker's own clock —
      // sanitize() drops any field the caller invents, so a request cannot
      // choose its own timestamp — and it is what a roster-update or seat
      // confirmation code binds to (run/updates.py).
      const now = new Date();
      const stored = { ...row, received_at: now.toISOString() };
      // The whole row lives in the key's METADATA (1 KB), not in a value that
      // must be fetched one row at a time: reading N rows was N+1 KV calls per
      // hourly intake. One list() call per kind returns everything. The
      // longest legitimate row (a seat: an address, a ref, a code and a
      // `via`) is well under the limit.
      if (bytes(JSON.stringify(stored)) > MAX_ROW_BYTES) {
        return json({ error: "too large" }, 413);
      }
      const options = row.kind === "waitlist"
        ? { metadata: stored, expirationTtl: ROW_TTL_SECONDS }
        : { metadata: stored, expirationTtl: SHORT_ROW_TTL_SECONDS };
      try {
        await env.ROWS.put(await storageKey(row, now), "1", options);
      } catch {
        // The day's free-tier writes are spent, or KV is down: said, with
        // CORS, so the page can tell the visitor rather than guess.
        return json({ error: "storage unavailable" }, 503);
      }
      return json({ ok: true });
    }

    if (request.method === "GET") {
      if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
      // The Worker's own switches, for `make launch-check` (read-only, no
      // rows): the site's TRIAL_OPEN must agree with this one, or every free
      // report request is refused while the page offers it.
      if (url.searchParams.get("status") === "1") {
        return json({ trial_open: env.TRIAL_OPEN === "true", counts: Boolean(env.COUNTS) });
      }
      const asked = (url.searchParams.get("kinds") || "").split(",")
        .map((kind) => kind.trim()).filter(Boolean);
      if (asked.some((kind) => !KINDS.includes(kind))) {
        return json({ error: "unknown kind" }, 400);
      }
      // No filter: every row (the privacy export, the owner's stats).
      const prefixes = asked.length ? [...new Set(asked)].map((kind) => `${kind}:`) : [""];
      const rows = [];
      try {
        for (const prefix of prefixes) {
          let cursor;
          do {
            const page = await env.ROWS.list(prefix ? { prefix, cursor } : { cursor });
            for (const entry of page.keys) {
              if (entry.metadata) rows.push({ ...entry.metadata, _key: entry.name });
            }
            cursor = page.list_complete ? undefined : page.cursor;
          } while (cursor);
        }
      } catch {
        return json({ error: "storage unavailable" }, 503);
      }
      // Oldest first, whatever the key shape: the readers judge order by the
      // Worker's own stamp.
      rows.sort((a, b) => String(a.received_at || "").localeCompare(String(b.received_at || ""))
        || String(a._key).localeCompare(String(b._key)));
      return json(rows);
    }

    // One row, on a deletion request: same key as the read, never from a
    // browser (no CORS for it), so a stranger can't erase anybody's rows.
    if (request.method === "DELETE") {
      if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);
      const key = url.searchParams.get("key") || "";
      if (!key || key.length > 512) return json({ error: "bad key" }, 400);
      try {
        await env.ROWS.delete(key);
      } catch {
        return json({ error: "storage unavailable" }, 503);
      }
      return json({ deleted: true });
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
