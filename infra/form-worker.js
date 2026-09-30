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
 * It is ~60 lines, costs nothing at this scale (KV free tier: 1,000 writes and
 * 100,000 reads a day), and the whole thing is readable in one sitting.
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
 */

const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
const REF = /^[A-Za-z0-9_-]{1,200}$/;
const SLUG = /^[0-9a-f]{10}$/;
const TOKEN = /^[0-9a-f]{20}$/;
const CODE = /^[0-9a-f]{24}$/;
const MAX_BODY = 2048;

function sanitize(body) {
  if (!body || typeof body !== "object") return null;
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
    // The launch list holds the address and nothing else.
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
      // seat: two addresses and a ref) is ~750 bytes.
      if (JSON.stringify(stored).length > 1000) return json({ error: "too large" }, 413);
      await env.ROWS.put(key, "1", { metadata: stored });
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
};
