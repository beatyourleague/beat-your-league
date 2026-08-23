/**
 * The form backend — one Cloudflare Worker, pasted into the dashboard.
 *
 * It exists for exactly two kinds of row the static site cannot store itself:
 * League Pass SEAT claims and self-serve roster UPDATES. Both are posted from
 * site/join/ and read back by run/intake.py, which validates every row before
 * anything reaches the registry — a seat is honoured only if its payer bought
 * a pass, an update only if it carries the subscriber's token. This Worker
 * therefore holds nothing secret and decides nothing: it is a mailbox.
 *
 * Why a Worker and not a form vendor: free-tier form products cap at ~50
 * submissions a month or offer no machine-readable read-back, and this is the
 * same Cloudflare account the domain's DNS and email routing already live in.
 * It is ~60 lines, costs nothing at this scale (KV free tier: 1,000 writes and
 * 100,000 reads a day), and the whole thing is readable in one sitting.
 *
 * Setup (LAUNCH.md step 5b): Workers & Pages → Create → paste this file →
 * Settings → Bindings → KV namespace, variable name ROWS → Variables:
 *   SITE_ORIGIN   = https://<domain>        (CORS; the only page allowed to POST)
 *   FORM_API_KEY  = <random>                (secret; the intake's read key)
 * Then FORM_ENDPOINT = the Worker URL, in both the page and the GitHub secret.
 *
 * Contract (matches run/intake.py fetch_seats + run/updates.py):
 *   POST JSON  {kind:"seat",   email, covered_by, ref}
 *   POST JSON  {kind:"update", email, ref, replaces, token}
 *   GET  + Authorization: Bearer <FORM_API_KEY>  →  JSON array of stored rows
 */

const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
const REF = /^[A-Za-z0-9_-]{1,200}$/;
const SLUG = /^[0-9a-f]{10}$/;
const TOKEN = /^[0-9a-f]{20}$/;
const MAX_BODY = 2048;

function sanitize(body) {
  if (!body || typeof body !== "object") return null;
  const kind = body.kind === "update" ? "update" : "seat";
  const email = String(body.email || "").trim().toLowerCase();
  const ref = String(body.ref || "").trim();
  if (!EMAIL.test(email) || email.length > 254 || !REF.test(ref)) return null;
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
      // The key orders rows by arrival; the intake re-stamps on first sight
      // anyway, so nothing downstream trusts this clock.
      const key = `${Date.now().toString().padStart(14, "0")}-${crypto.randomUUID()}`;
      await env.ROWS.put(key, JSON.stringify({ ...row, received_at: new Date().toISOString() }));
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
          const value = await env.ROWS.get(entry.name);
          if (value) rows.push(JSON.parse(value));
        }
        cursor = page.list_complete ? undefined : page.cursor;
      } while (cursor);
      return json(rows);
    }

    return json({ error: "method" }, 405);
  },
};
