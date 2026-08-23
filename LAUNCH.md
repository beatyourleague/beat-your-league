# LAUNCH.md — every owner action, in order, with the exact strings

The code is done and tested; nothing below is engineering. Each step says what to click, what
to paste, and what to tell me so I can wire the result in. Steps 1–4 are the weekend; 5–7 are
the sell window; 8 is launch week. Strategy and dates live in the "Road to Sep 8" plan — this
file is the hands-on-keyboard half.

---

## 1. Domain (~30 min, ~$15 — start first, DNS is wall-clock time)

1. Buy the domain (Cloudflare Registrar sells at cost and its DNS is free).
2. DNS records for GitHub Pages (type → name → value):
   - `A` → `@` → `185.199.108.153`
   - `A` → `@` → `185.199.109.153`
   - `A` → `@` → `185.199.110.153`
   - `A` → `@` → `185.199.111.153`
   - `CNAME` → `www` → `<your-github-username>.github.io`
   If Cloudflare: set these records to **DNS only** (grey cloud), not proxied.
3. Cloudflare **Email Routing** (free): create `hello@<domain>` forwarding to your real
   inbox. That address becomes `CONTACT_EMAIL` and the reply-to on every report.
4. **Tell me:** the domain and the chosen contact address, plus your legal jurisdiction
   (state/country). I fill `legal.html`'s two placeholders, `CONTACT_EMAIL` on both funnel
   pages, and add `site/CNAME`.

## 2. GitHub (~30 min)

1. Create a **public** repo (Pages on the free plan requires public — safe by design:
   subscriber data lives only in gitignored `data/registry/`, tests block real names and
   personal addresses from every tracked file, and CI runs the suite on every push).
2. Push:
   ```bash
   git remote add origin git@github.com:<you>/<repo>.git
   ```
   ```bash
   git push -u origin main
   ```
3. Settings → Pages → Source: **GitHub Actions**. Then Custom domain: your domain →
   Enforce HTTPS.
4. Settings → Secrets and variables → Actions → **Secrets**. Create these names exactly
   (fill values as later steps produce them — an unset secret degrades safely):

   | Secret | From step | Notes |
   |---|---|---|
   | `STRIPE_API_KEY` | 5 | restricted key, never the full secret key |
   | `STRIPE_PAYMENT_LINKS` | 5 | `s:plink_…,m:plink_…,p:plink_…` |
   | `EMAIL_PROVIDER` | 4 | literally `resend` |
   | `EMAIL_FROM` | 4 | e.g. `reports@<domain>` |
   | `EMAIL_REPLY_TO` | 1 | `hello@<domain>` |
   | `RESEND_API_KEY` | 4 | |
   | `SITE_URL` | 1 | `https://<domain>` |
   | `BILLING_PORTAL_URL` | 5 | Stripe customer-portal login link |

## 3. Loops — the waitlist (~30 min)

1. Free account at loops.so → Settings → Domain: add the DNS records it shows (DKIM/SPF —
   required even on free).
2. Create a Form (Audience → Forms). Copy the **form ID** from its endpoint
   (`https://app.loops.so/api/newsletter-form/<FORM_ID>`).
3. **Tell me the form ID.** I wire `NOTIFY_LIST_ENDPOINT` on both pages and verify the
   capture end to end in a browser.

## 4. Resend — the report sender (~20 min)

1. Free account at resend.com → Domains → add `<domain>` → add the DNS records it shows.
   (Keep Loops and Resend on the same domain; both publish their own DKIM selectors, so
   they don't collide.)
2. API key → create. Set `RESEND_API_KEY` and `EMAIL_PROVIDER=resend` secrets.
3. Free tier is 3,000/month but **100/day** — the Tuesday batch breaks at ~100 subscribers.
   The $20/mo upgrade triggers at >$500 MRR, so it self-funds; a conditional line for it
   belongs in PLAN §2's budget table when it happens.

## 5. Stripe (~90 min) — links, terms checkbox, portal, key

1. **Public details** (Settings → Business → Public details): set Terms of service URL to
   `https://<domain>/legal.html` and Privacy policy URL to
   `https://<domain>/legal.html#privacy`.
2. **Customer portal** (Settings → Billing → Customer portal): activate, allow
   subscription cancellation. Copy the permanent login link (`https://billing.stripe.com/p/login/…`)
   → that is the `BILLING_PORTAL_URL` secret. Also paste it into `legal.html` at the marked
   comment (or tell me and I will).
3. **Three products/payment links** — on each link, toggle **"Require customers to accept
   your terms of service"**:
   - Season pass — subscription, **$39 USD / year**
   - Monthly — subscription, **$12.99 USD / month**
   - League Pass — subscription, **$99 USD / year**
4. **Custom text above the Pay button** (closes the disclosure gap on the one page we
   don't control). One API call per link — replace key and `plink_…`:
   ```bash
   curl https://api.stripe.com/v1/payment_links/plink_SEASON -u "rk_live_...:" -d "custom_text[submit][message]=Renews automatically each season at \$39 USD unless you cancel. We email you before any renewal, and you can cancel any time from your billing page — the link is in every report we send."
   ```
   ```bash
   curl https://api.stripe.com/v1/payment_links/plink_MONTHLY -u "rk_live_...:" -d "custom_text[submit][message]=Bills \$12.99 USD monthly until you cancel. Billing stops automatically when the season ends — we never charge through the offseason."
   ```
   ```bash
   curl https://api.stripe.com/v1/payment_links/plink_PASS -u "rk_live_...:" -d "custom_text[submit][message]=Renews automatically each season at \$99 USD unless you cancel. We email you before any renewal, and you can cancel any time from your billing page."
   ```
5. **Restricted API key** (Developers → API keys → Create restricted key):
   Checkout Sessions **Read** · Subscriptions **Read** · Customers **Write** (the sweep
   stamps signup metadata onto the customer). Everything else: None. This is
   `STRIPE_API_KEY` — the same key works in the curl commands above.
6. `STRIPE_PAYMENT_LINKS` secret: `s:<season plink id>,m:<monthly plink id>,p:<pass plink id>`
   (the `plink_…` id is in each link's dashboard URL).
7. **Tell me the three full payment-link URLs.** I paste them into `site/join/index.html`,
   flip `CHECKOUT_OPEN`, and the funnel goes live on the next push.

## 6. The proving run (~2 h, after 5) — non-negotiable

This repo's own history includes a cron that could never have mailed anybody and looked
green. Money does not move for strangers until each of these has been watched happening:

1. **One real $39 purchase, end to end:** buy through the live site with a real card →
   `make intake` → your row appears in `data/registry/rosters.json` → `make tuesday-preview`
   builds your report → refund yourself in the Stripe dashboard.
2. **Send rehearsal:** with the secrets set, run the Tuesday workflow by hand
   (Actions → weekly-report → Run workflow) and open the result in Gmail, Outlook, and
   Apple Mail. Check the images, the footer links, and that the billing-portal link works.
3. **Welcome check:** the purchase in (1) should also have produced the welcome email —
   confirm its renewal terms match what you bought.

## 7. The sell window (Aug 25 – Sep 3) — where season one's subscribers actually come from

- The free demo is one command — paste whatever they send you:
  ```bash
  .venv/bin/python -m run.trial --email them@example.com --roster - --print
  ```
  (`--print` gives a paste-ready text version for the group chat; add
  `--scoring half_ppr`, `--template sf`, `--size 10` to match their league.)
- The pitch pack is `content/pitches.md` — 16 verified targets, warmest first, template
  included. **Send only after the site is live**, all in the same week.
- The League Pass close for your own leagues is the one channel that can finish before
  Sep 8. Three passes is $297 and the first real demand evidence this product has ever had.

## 8. Launch week

- **Thu Sep 4:** code freeze.
- **Mon Sep 7:** waitlist broadcast from Loops' editor — one email, as promised on the page:
  checkout is open, first file lands tomorrow.
- **Tue Sep 8, ~7:00 ET:** the cron fires on its own. QA one report before opening the
  group chats.

---

*Kept out on purpose: the League Pass seat form backend (`FORM_ENDPOINT` stays empty until a
validated backend is chosen — pass buyers get their own report meanwhile, and seats are
refused loudly, never silently) and There's An AI For That's $49 listing (needs a PLAN §2
budget line first).*
