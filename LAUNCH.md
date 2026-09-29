# LAUNCH.md — opening mid-season

Every owner action left before a stranger's payment becomes a Tuesday email, in order, with
the exact strings. The code is done and tested; nothing here is engineering. Rewritten Sep 29
2026, in Week 4 of 18 — the Sep 8 launch plan it replaces is in git history.

**Why speed matters now:** a buyer who joins today gets a full file on the day they pay. By
Week 4 the season has three games on record, so the odds print for every league setup, not
only the one we graded early. Every week spent on steps 1–4 is a week of the season nobody
can buy.

---

## Where things stand

Done:
- `beatyourleague.com` on GitHub Pages; `hello@beatyourleague.com` forwards to your inbox.
- Terms (Ontario law) and privacy pages. The refund window is counted from each buyer's own
  purchase and closes when their second weekly file's week kicks off.
- Three Stripe products and payment links — $39 season pass, $14.99 monthly, $99 League
  Pass — wired into the join page.
- The Stripe customer portal is on; its login link is in the terms and in every report.
- The restricted key `github-actions-crons` exists.

**Heads-up: the join page can already take money.** The pricing buttons lead to it and its
payment links are live, but nothing reads Stripe until step 3's key is set. A buyer who pays
before then gets no welcome and no file until it is. Nothing is lost — the first run after
step 3 sweeps every payment ever made — but a late first file is the likeliest refund there
is. Steps 1–3 take under an hour; do them in one sitting.

---

## 1. Finish the payment links (~15 min)

1. Open https://dashboard.stripe.com/payment-links in **live** mode. For each of the three
   links: open it → **Edit** → switch **Enable Managed Payments** off → **Save**.
2. While each one is open, check it matches:

   | Setting | Should be | Why |
   |---|---|---|
   | Enable Managed Payments | Off | 3.5% on top of the normal fee, and it makes Stripe the seller, which contradicts the terms. Revisit only if EU sales stop being incidental |
   | Require customers to accept your terms of service | On | |
   | Collect customer addresses | On | Tax thresholds count per country and per state. The address stays in Stripe; a test keeps it out of everything that builds reports |
   | Customer names, business names, phone | Off | Nothing uses them |
   | Collect tax automatically | Off | We're registered for tax nowhere yet |
   | Let customers adjust quantity | Off | One purchase is one roster; a quantity of 2 charges twice for one report |
   | Include a free trial | Off | The refund window is the trial |
   | Limit the number of payments | Off | `run/billing.py` ends monthly billing at season's end from the real schedule |
   | Promotion codes | Off | The founding rate is the discount, and the terms promise it at every renewal |
   | After payment | Redirect to `https://beatyourleague.com/thanks.html` | |

   If Managed Payments can't be switched off on an existing link, make a replacement link for
   that product with the settings above, **deactivate** the old one, and send me the new URL
   and its `plink_` id.
3. **Settings → Business → Public details:** Terms of service URL
   `https://beatyourleague.com/terms.html`, Privacy policy URL
   `https://beatyourleague.com/privacy.html`.
4. **Put the renewal terms above Stripe's Pay button.** It's API-only, with no Dashboard
   field. In Terminal, from the repo folder, paste this whole line:
   ```bash
   STRIPE_PAYMENT_LINKS='s:plink_1U8yWRQN4gk9bpTQAg1FZS1o,m:plink_1U8yVmQN4gk9bpTQ0Tk89BjH,p:plink_1U8yTVQN4gk9bpTQydWBQFIB' .venv/bin/python infra/stripe_paylink_text.py
   ```
   At the prompt, paste the `setup-payment-link-text` key (Developers → API keys → **Reveal
   live key**; it starts `rk_live_`). **Nothing appears as you paste** — that's normal. Never
   type your Mac password there.
   - Success is three `[ok ]` lines, then "All three set and verified."
   - `You cannot use custom_text with Managed Payments` — that link still has it on; redo 1.
   - `HTTP 401` — the key was cut off; copy it again. `HTTP 403` — the key lacks Payment
     Links **Write**.
   - If Stripe won't reveal the key, create a new restricted key with Payment Links **Write**
     and everything else None, and use that.

   The sentences come from `render/welcome.py`, which a test ties to the pricing page, so
   Stripe's page can't disagree with ours.
5. **Delete the `setup-payment-link-text` key.** A key that can edit payment links can change
   what buyers pay, and nothing needs it again.

**Tell me** what Terminal printed (it never shows the key).

## 2. Resend — the sender (~20 min)

1. Free account at resend.com → **Domains → Add domain** → `beatyourleague.com`.
2. Add every record it shows in **Cloudflare → DNS**, each set to **DNS only** (grey cloud).
   They sit on subdomains, so they don't collide with the email forwarding. Wait for Resend to
   show **Verified** (minutes, sometimes an hour).
3. **API Keys → Create:** permission **Sending access**, domain `beatyourleague.com`. Paste it
   straight into the GitHub secret in step 3 — nowhere else.

The free tier sends 3,000 a month but only **100 a day**, which the Tuesday run outgrows at
about 100 subscribers. The $20/month plan goes into PLAN §2's budget table the week that
happens.

## 3. GitHub secrets (~10 min)

Open https://github.com/beatyourleague/beat-your-league/settings/secrets/actions → **New
repository secret**, once per row. Names exactly as written.

| Name | Value |
|---|---|
| `STRIPE_API_KEY` | the `github-actions-crons` key (Reveal live key) |
| `STRIPE_PAYMENT_LINKS` | `s:plink_1U8yWRQN4gk9bpTQAg1FZS1o,m:plink_1U8yVmQN4gk9bpTQ0Tk89BjH,p:plink_1U8yTVQN4gk9bpTQydWBQFIB` |
| `EMAIL_PROVIDER` | `resend` |
| `EMAIL_FROM` | `Beat Your League <reports@beatyourleague.com>` |
| `EMAIL_REPLY_TO` | `hello@beatyourleague.com` |
| `RESEND_API_KEY` | from step 2 |
| `SITE_URL` | `https://beatyourleague.com` |
| `BILLING_PORTAL_URL` | `https://billing.stripe.com/p/login/cNi4gB3Nx3zkcXt1IKaMU00` |

`github-actions-crons` needs exactly three permissions: Checkout Sessions **Read**, Customers
**Write**, Subscriptions **Write**; everything else None. If Stripe won't reveal it, recreate
it with those three. Subscriptions must be **Write**: `run/billing.py` sets every monthly
subscription to stop at season's end, and with Read only, monthly buyers would be billed
through the offseason (the daily run goes red if it can't write, so you'd hear about it).

Keys go only into these boxes — never into chat, a note or a file. The three remaining
secrets (`FORM_ENDPOINT`, `FORM_API_KEY`, `UPDATE_SECRET`) come in step 5; until then the
features that need them stay off rather than half-working.

## 4. The proving run (~1 hour)

This repo's history includes a cron that could never have mailed anybody and still looked
green. Nobody else's money moves until you've watched your own go all the way through.

1. **Between a Tuesday morning and that week's first kickoff** (table in section 7), buy the
   **$39 season pass** at https://beatyourleague.com/join/ with your own email and a real
   card. Enter your real roster.
2. **Actions → daily-intake → Run workflow**, or wait up to an hour. It should finish green.
3. **Check your inbox for two emails:**
   - **The welcome:** $39, renews yearly at $39, refunds "until your second weekly file's
     week kicks off", and the cancel link opens your Stripe billing page.
   - **Your first file:** this week's report, because you bought before kickoff. Open it on
     your phone and on a computer.
4. **Tell me both arrived.** I turn on `CHECKOUT_CAN_COMPLETE`, which retires the "leave your
   email" box and tells visitors their first file lands today. It's live on the next push.
5. **Next Tuesday,** confirm the new week's file arrives by about 8:30am ET and the
   weekly-report run in Actions is green.

Then decide what happens to your subscription (section 9): keep it and it starts the public
record, or cancel and refund it as section 7 describes. A refund doesn't return Stripe's fee
(about $1.43).

## 5. The form Worker (~20 min) — League Pass and roster updates

Two features wait on one Cloudflare Worker:
- **League Pass seats.** The League Pass page's button stays hidden until then.
- **"Roster changed?" links in every report.** Without them, a subscriber's file drifts out of
  date as waivers change their roster, and they have no way to fix it themselves.

The Worker ([infra/form-worker.js](infra/form-worker.js), about 60 lines) holds nothing secret
and decides nothing: every row is checked before it reaches the subscriber list.

1. Cloudflare → **Workers & Pages → Create → Worker** → paste `infra/form-worker.js` →
   **Deploy**.
2. **Storage & Databases → KV** → create a namespace (any name). Worker → **Settings →
   Bindings → KV namespace**, variable name **`ROWS`**.
3. Worker → **Settings → Variables:** `SITE_ORIGIN` = `https://beatyourleague.com`, and
   `FORM_API_KEY` = a random string, marked secret. Make one with:
   ```bash
   openssl rand -hex 24
   ```
4. Make the roster-update secret:
   ```bash
   openssl rand -hex 32
   ```
5. GitHub secrets: `FORM_ENDPOINT` = the Worker URL, `FORM_API_KEY` = step 3's value,
   `UPDATE_SECRET` = step 4's value.
6. **Tell me the Worker URL** (it isn't a secret). I wire it into the join and League Pass
   pages, switch the League Pass button on, and change the FAQ's roster answer to the link.

Until then both fail closed: seat claims are refused with a reason, and the update link
simply doesn't appear in reports.

## 6. Selling from Week 4

The order is PLAN §5.1's — subscribers per hour of your time — with one channel held back.

1. **Your own leagues.** A season pass per manager, or the League Pass once step 5 is done.
   Anyone who sends you their roster can have this week's file on it, free. Copy the roster
   they sent, then run:
   ```bash
   pbpaste | .venv/bin/python -m run.trial --email them@example.com --roster - --print
   ```
   Nothing is emailed from your Mac: it writes a draft and prints a text version to paste
   back into the chat. Add `--scoring half_ppr`, `--template sf` or `--size 10` to match their
   league. A name it can't place stops the run and names the line — ask them, don't guess.
2. **Discords and league group chats.** Ask a mod before mentioning the product. The
   comparison page (`beatyourleague.com/compare/`) is the thing to paste when someone asks
   what to use.
3. **X replies, about 20 minutes a day.** A number and one line of reasoning in reply to
   start/sit questions. No links in replies — the product lives in your profile.
4. **Reddit.** Read each subreddit's rules yourself and ask the mods first. Answers only, no
   links.

**Held back:** the mention campaign in `content/pitches.md` emails other sites, which you've
ruled out for now (Sep 2026). It stays written for when that changes.

Everything you post follows the site's rule: no "accurate", "proven", "calibrated", "tested"
or "we hit X%" — the grading doesn't back any of them yet — and nothing about betting.

## 7. Every week from here

| When (ET) | What runs | What you do |
|---|---|---|
| Tuesday ~8am, retry at noon | **weekly-report:** new signups, then every subscriber's file | Open your own file |
| Daily ~10am, plus hourly | **daily-intake:** new purchases, welcomes, first files, end-of-season dates on monthly plans, renewal notices | Nothing, unless it goes red |
| Monday ~9am | **monday-receipts:** grades last week's calls and republishes the public record | Nothing, unless it goes red |

Times are an hour earlier from Nov 1, when the clocks change. A red run opens a GitHub issue,
and GitHub emails you about it.

**A refund request, in three checks:**
1. **Is it inside the window?** Find the first week below whose kickoff comes after they paid
   (Stripe shows the payment time). That week's report was their first weekly file, and their
   window closes at the kickoff **one row further down**. If they paid within two hours of a
   kickoff, start from the next row instead — their first file may have been the roster file.
   *Example: paid Wed Oct 7 → first file Week 5 → window closes Thu Oct 15, 8:15pm ET.*
   The one exception: if a send of ours ever ran late and their second file reached them after
   its week kicked off, they have a week from that send. A late send would have opened an
   issue; ask me and I'll check the send log.
2. **Is it their first refund?** Search their email under **Customers** for an earlier
   refund. One per person (one per league for a League Pass); if there's one, this purchase
   is final.
3. **Issue it:** their subscription → **Cancel subscription → Immediately**, and refund the
   last payment in full. A refund on its own leaves the subscription active, and it would bill
   again. The reports stop by themselves once a payment is fully refunded.

| Week | First kickoff (ET) |
|---|---|
| 4 | Thu Oct 1, 8:15pm |
| 5 | Thu Oct 8, 8:15pm |
| 6 | Thu Oct 15, 8:15pm |
| 7 | Thu Oct 22, 8:15pm |
| 8 | Thu Oct 29, 8:15pm |
| 9 | Thu Nov 5, 8:15pm |
| 10 | Thu Nov 12, 8:15pm |
| 11 | Thu Nov 19, 8:15pm |
| 12 | **Wed** Nov 25, 8:00pm |
| 13 | Thu Dec 3, 8:15pm |
| 14 | Thu Dec 10, 8:15pm |
| 15 | Thu Dec 17, 8:15pm |
| 16 | Thu Dec 24, 8:15pm |
| 17 | Thu Dec 31, 8:15pm |
| 18 | Sun Jan 10, 1:00pm — Saturday games are usually added late; recheck |

From the published NFL schedule the product itself reads. A flexed game can move a row.

## 8. Dates you pre-committed to (PLAN §6)

The gates were written before the season so results can't move them. Opening in Week 4 puts
the big one ten days after opening:
- **Oct 11:** at least 40 paid subscribers, and at least 30% of trials from outside your own
  network.
- **The pivot rule:** under 25 subscribers and under 5 from outside your network on Oct 11
  means stop building product. Spend the rest of the season building the graded public record
  and publishing the weekly posts, and relaunch in August 2027.

Opening this late makes Oct 11 hard to reach, and PLAN says not to move it. Your own test
subscription doesn't count toward it.

## 9. Decisions waiting on you

- **Start the public record.** Nothing has been recorded or graded yet, because a call is
  recorded only when a report is mailed to a subscriber, and there are none. Keeping your test
  subscription from step 4 starts it: it's a real subscription, so its calls are recorded
  before kickoff and graded every Monday like anyone's, and the weekly posts (`run/posts.py`)
  finally have graded rows to draft from.
- **The report changes from the Week-4 review:** confidence bars drawn from 50%, the Regret
  Score, the first screen, and "last three games" lines for starters. None of them blocks
  selling.
- **A postal address** is needed only if you ever email a list (US anti-spam law). Reports to
  paying subscribers don't need one, and there's no list today.
