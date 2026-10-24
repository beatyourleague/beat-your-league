# LAUNCH.md — opening mid-season

Every owner action left before a stranger's payment becomes a Tuesday email, in order, with
the exact strings. The code is done and tested; nothing here is engineering. Updated Oct 23
2026, in Week 7 of 18, after the pre-launch review: 2026 sells **one-time passes** ($29
Rest-of-Season, $19 Playoff, $69 League Pass — one payment each, nothing renews), and every
step below is written for them. The subscription steps that come back in 2027 are kept under
their own "2027" headings.

---

## Where things stand

**Run `make launch-check`** (about 8 minutes; `make launch-check-fast` takes one). Every
remaining item shows as OWNER (yours) or FAIL (code), and it says READY when nothing is left.
It reads more when you give it more, all read-only:
- `gh auth login` once: secrets, cron timing, the fork-PR setting.
- `RESEND_API_KEY` in the shell: whether Resend says the domain is verified.
- `STRIPE_API_KEY` (the read-only key from section 8): public details, refund and dispute
  rates, sales against the tax threshold.
- The accessibility gate needs axe-core once: `npm install --no-save axe-core@4.11.4`.

**The order — the same everywhere in this file:**
0. **Step 0, lock the accounts (~45 min, today).** Before anything else depends on them.
1. **Step 5, the form Worker.** First of the setup: it needs nothing else.
2. **Steps 1–3:** fresh payment links, Resend, GitHub secrets. Under an hour, one sitting.
3. **I put the new links on the join page.** Only once the Worker URL is in: the launch check
   FAILs a checkout opened without it, because then every roster change is a reply you apply
   by hand.
4. **Step 4:** your own purchase, watched end to end.
5. **Opening (step 6):** everyone can buy, and the waitlist gets its one email.
6. **Before the first launch post:** the site moves to Cloudflare Pages (section 11, steps
   1–5). Making the repo private comes later, in that section's order.

**The date.** Week 7 (Oct 20) passed with checkout closed. Aim to do steps 0, 5 and 1–3 this
weekend, make the proving purchase on **Saturday Oct 24** (step 4 — a weekend buyer gets the
welcome and the roster report that day, which is exactly what it tests), and open on **Sunday
Oct 25 or Monday Oct 26**, so the Week 8 Tuesday send (Oct 27) carries the first buyers.
Anyone who buys before Thursday's 8:15pm ET kickoff gets Week 8's report. Each closed week now
costs about a tenth of what's left of 2026 (`.venv/bin/python -m run.economics` shows the
arithmetic; its `OPENS` date is the assumption to move if this slips).

Done:
- `beatyourleague.com` on GitHub Pages (moving: section 11);
  `hello@beatyourleague.com` forwards to your inbox.
- Terms (Ontario law) and privacy pages.
- Three Stripe products from August — $39 season pass, $14.99 monthly, $99 League Pass. They
  are 2027's; 2026's one-time prices are step 1.
- The Stripe customer portal is on; its login link is in the terms. It matters again in 2027:
  a one-time pass has nothing in it to cancel.
- The restricted key `github-actions-crons` exists.

**Checkout has been closed since Sep 29.** The join page's links are empty and the buttons
say "Checkout opens at launch", because nothing read Stripe without step 3's key.

**Two checks first:**
- **Stripe → Payments, anything since Aug 27?** Any payment from then was never processed.
  Tell me: the first run after step 3 sends that buyer their welcome and first report, and
  they're owed an apology and the offer of a refund.
- **Close the old automatic issues (#6–#21)** once this code is pushed. Their titles are
  dated, so the new runs never comment on them:
  ```bash
  for n in $(seq 6 21); do gh issue close $n --comment "Fixed: runs exit quietly until launch."; done
  ```
- **Close the five Dependabot pull requests from Aug 26** (checkout, cache, upload-artifact,
  configure-pages, deploy-pages major-version jumps) **and delete their branches now**, not at
  section 11. They were written against the old `@v4`-style lines and still carry the old
  daily.yml and weekly.yml, and anyone with Actions access can dispatch a workflow on a branch
  — with its secrets. Every action is now pinned to a commit, and next month's Dependabot run
  proposes updates in that form. Merge none without a green test run — and from then on, one
  look a month (CLAUDE.md's dependency rule).
  ```bash
  git ls-remote --heads origin 'dependabot/*' | sed 's#.*refs/heads/##' |
    while read -r b; do git push origin --delete "$b"; done
  ```

---

## 0. Lock the accounts (~45 min, today)

Nobody can break into the site: it is static, and there is no server of ours. The way in is
one of your accounts — and one Cloudflare login holds the domain, its DNS, the hello@ mail
forwarding and (after step 5) the Worker. Whoever controls the mail can reset every other
account whose login is on the domain. Do these in this order, which is blast radius:

1. **A private login address.** The personal Gmail you used early on is in this repo's public
   history (section 11), so treat it as public from today: it must not be the login or the
   recovery address of any brand account. And a login ON `beatyourleague.com` is locked out
   the day the domain or its mail breaks. Make one new mailbox, published nowhere, used only
   to log in to Cloudflare, GitHub, Stripe and Resend, and protect it as in item 2.
2. **Google (the inbox hello@ forwards to).** Security → **Passkeys** (or two security
   keys); remove SMS as a second step; print the backup codes and keep them offline. Consider
   **Advanced Protection**.
3. **Cloudflare (registrar, DNS, mail routing, the Worker).** My Profile → Authentication:
   passkey or security-key 2FA, backup codes offline; change the login email to item 1's
   address if it is on the domain. Domain Registration → **auto-renew on** (it expires
   2027-08-26) and keep the transfer lock on. DNS → Settings → **DNSSEC: Enable** (Cloudflare
   Registrar publishes the DS record itself). My Profile → API Tokens: delete any you don't
   use. Notifications: turn on login alerts.
4. **Stripe.** Settings → Team and security: **require 2FA** (security key), and turn on the
   emails for new logins and for **payout-account changes**. Review team members and API keys
   (keep `github-actions-crons`; step 1.6 deletes the link-text key).
5. **GitHub.** Settings → Password and authentication: security key or passkey (2FA is likely
   already on). Review SSH keys, personal access tokens and authorised OAuth apps; put the
   `GH_DISPATCH_TOKEN` expiry (step 5.8) in your calendar. In the repo, Settings → Actions →
   General:
   - **Actions permissions: Allow actions created by GitHub** only — every action the
     workflows use is GitHub's own, pinned to a commit.
   - **Fork pull request workflows from outside collaborators: Require approval for all
     outside collaborators.** And never approve a stranger's pull request to run: ANY change
     it makes (a test file, not only a workflow) runs with this repo's cache in reach.
   - **Workflow permissions: Read repository contents** (each workflow asks for what it needs
     itself), and untick **Allow GitHub Actions to create and approve pull requests**.
   - Settings → Code security: **Secret scanning** with **push protection**, **Dependabot
     alerts**, and **Private vulnerability reporting** on. Settings → General: untick Wikis.
   - While the repo is public: Settings → Rules → **New branch ruleset** on `main` →
     **Restrict deletions** and **Block force pushes**, no bypass list. The crons only ever
     fast-forward, so nothing else changes; it stops a stolen job token rewriting the record.
     (A private repo on the Free plan loses rulesets — section 11.)
6. **Resend** (when you make it in step 2). 2FA on; the two keys are **Sending access** only
   (one for the crons, one for Gmail's Send mail as) — revoke anything else.
7. **The domain's verification for GitHub Pages (5 min).** GitHub → your account Settings →
   **Pages → Add a verified domain** → `beatyourleague.com` → add the TXT record it shows in
   Cloudflare DNS (DNS only, grey cloud) → Verify. While Pages serves the site nobody else can
   claim the domain; the moment it stops — a private repo unpublishes Pages at once on Free —
   somebody else's Pages site could, until DNS moves. Verified, they can't.
8. **DMARC (5 min) — now, not with step 2.** Cloudflare DNS → TXT `_dmarc` =
   `v=DMARC1; p=none; rua=mailto:hello@beatyourleague.com; adkim=s; aspf=r; sp=reject`.
   Anyone can send mail as hello@ until it exists. Read the reports for two clean weeks, then
   `p=quarantine`, and later `p=reject` (Resend signs as `beatyourleague.com`, so it aligns).

**Tell me** when these are done. `make launch-check` reads items 3 (DNSSEC), 5 (the ruleset),
7 (the verified domain) and 8 (DMARC) back from outside and shows each as owner setup until
it is. A CAA record is optional and waits for the host to settle (section 11), so it names the
authority that host's certificates come from.

## 1. Fresh payment links (~20 min)

The three links that were live Aug 27–Sep 29 are in this repo's public history, so anyone can
still open one. Make three new links and switch the old ones off.

1. https://dashboard.stripe.com/payment-links in **live** mode. Open each of the three old
   links (made Aug 27) → **Deactivate**.
2. **+ New** — 2026 sells **one-time passes** (decision Oct 18 2026), so make three links,
   each a **one-time price** (Product → Add price → **One-off**, not Recurring): the
   **$29 Rest-of-Season Pass**, the **$69 League Pass (rest of season)**, and the **$19
   Playoff Pass** (it switches on by itself once a buyer's first report would be Week 13,
   when its link is on the join page). No monthly link this season. Each set like this:

   | Setting | Should be | Why |
   |---|---|---|
   | Enable Managed Payments | Off | 3.5% on top, and it makes Stripe the seller, which contradicts the terms |
   | Require customers to accept your terms of service | On | |
   | Collect customer addresses | Off | A card payment already takes the card's country and, where the card needs one, its postal code — enough to place a buyer for the per-country and per-state tax thresholds. A full address is more than anything uses, and privacy §1 says checkout asks for one only if it is set to |
   | Customer names, business names, phone | Off | Nothing uses them |
   | Collect tax automatically | Off | Not registered for tax anywhere yet |
   | Let customers adjust quantity | Off | A quantity of 2 charges twice for one report |
   | Include a free trial | Off | The refund window is the trial |
   | Limit the number of payments | Off | |
   | Create customers (one-off payments) | Always | The intake keeps the consent record and roster on the Customer; `infra/stripe_paylink_text.py` sets it too |
   | Promotion codes | Off | The founding rate is the discount |
   | After payment | Redirect to `https://beatyourleague.com/thanks.html` — **League Pass link only:** `https://beatyourleague.com/thanks.html?plan=pass` | |

   Two account settings the links follow:
   - **Settings → Payment methods → Link: Off.** With it on, the checkout shows "Link's
     Terms" beside ours and offers to save the card with a third party.
   - **Settings → Payments → Adaptive Pricing (local currency): Off.** Every price, renewal
     amount and refund on our pages is in USD; a buyer shown euros or pounds would be charged
     an amount no disclosure names, and renew at whatever the rate is next year.

3. Copy each new link's URL and its `plink_` id. **Send me the three URLs** (not secret).
4. **Settings → Business → Public details:** Terms of service URL
   `https://beatyourleague.com/terms.html`, Privacy policy URL
   `https://beatyourleague.com/privacy.html`. Public business name **Beat Your League**,
   support email **hello@beatyourleague.com**, **no phone number and no personal address** —
   these print on receipts, so they decide whether you stay anonymous. (Before the first $69
   sale, section 12's Ontario question may change that for the League Pass.)

   **The card-statement name (2 min):** same page → **Statement descriptor**
   `BEATYOURLEAGUE.COM`, **shortened descriptor** `BYL`. It is what a buyer sees on their card
   statement; a name they don't recognise is how an honest sale becomes a C$15 dispute. While
   there, the business description: *"Weekly sports-analysis email reports for season-long
   fantasy football; no wagering, contests or prizes."* (Stripe's restricted list covers
   fantasy and forecasting only *with a prize*; terms §2 rules prizes out, and this sentence
   says so to whoever reviews the account.)

   **Settings → Billing → Customer portal (2027; leave it as it is):** **Cancel
   subscriptions** allowed, **Cancellation mode: At end of billing period**, proration
   **none**, **Cancellation reason: Off** (the thanks page promises we don't ask why), and no
   retention coupon. `make launch-check` reads these back once `STRIPE_API_KEY` can read the
   portal settings. A 2026 one-time buyer has nothing in it; their way out is a stop request
   (section 8).

   **Settings → Business → Branding:** icon `site/brand/icon.png`, logo
   `site/brand/logo.png`, brand color `#101E33`, accent `#B3402F` (not the gold: unreadable
   on white).
5. **The one-payment text above Stripe's Pay button** (API only). Replace the three `plink_…`
   placeholders with the NEW ids, then paste the whole line in Terminal from the repo folder:
   ```bash
   STRIPE_PAYMENT_LINKS='s:plink_NEW_29,s:plink_NEW_19,p:plink_NEW_69' .venv/bin/python infra/stripe_paylink_text.py
   ```
   At the prompt, paste the `setup-payment-link-text` key (it starts `rk_live_`; nothing
   shows as you paste — normal; never your Mac password).
   - Success: three `[ok ]` lines, then "All three set and verified."
   - `You cannot use custom_text with Managed Payments`: that link still has it on.
   - `HTTP 401`: the key was cut off. `HTTP 403`: it lacks Payment Links **Write**.
   - No key to reveal? Make a restricted key with Payment Links **Write**, everything else None.
6. **Delete the `setup-payment-link-text` key.** A key that edits payment links can change
   what buyers pay.

**Tell me** what Terminal printed (it never shows the key).

## 2. Resend — the sender (~20 min)

1. Free account at resend.com → **Domains → Add domain** → `beatyourleague.com`.
2. Add every record it shows in **Cloudflare → DNS**, each **DNS only** (grey cloud). Wait for
   **Verified** (minutes, sometimes an hour).
3. **API Keys → Create:** **Sending access**, domain `beatyourleague.com`. Straight into the
   GitHub secret in step 3, nowhere else.
   **And one for the bounce check:** after each mailing run the intake asks Resend whether
   recent emails bounced (a buyer who mistyped their address paid and gets nothing). A
   Sending access key "can only send emails" and cannot read one back, so create a second
   key, **Full access**, named `github-actions-bounces`, and save it only as the GitHub secret
   `RESEND_READ_KEY`. It is optional: without it every run prints one `OWNER:` line saying
   bounces are not checked, and the launch check lists it. It can do anything in your Resend
   account, so it goes nowhere but that secret.
4. **DMARC:** done in step 0.8 (it should not wait for Resend). Once Resend's records are
   verified, its mail aligns with that record as it stands.
5. **Reply as hello@, not as you (15 min):** Gmail → Settings → Accounts → **Send mail as** →
   `hello@beatyourleague.com`, SMTP `smtp.resend.com`, port 465, username `resend`, password
   = a second Resend key with Sending access. Your personal address never reaches a customer.
6. **A sender address (~US$10/month):** US and Canadian anti-spam law both want a postal
   address in commercial email. Rent a virtual mailbox or PO box — never your home — and put
   it in the GitHub secret `SENDER_POSTAL_ADDRESS` (step 3). Every email prints it; the launch
   announcement refuses to send without it.

The free tier sends 100 a day, which one Tuesday outgrows at about 85 recipients. Move to the
$20/month plan that week (PLAN §2), then `RESEND_PLAN=pro` in your shell tells the launch
check.

## 3. GitHub secrets (~10 min)

https://github.com/beatyourleague/beat-your-league/settings/secrets/actions → **New repository
secret**, once per row, names exactly as written:

| Name | Value |
|---|---|
| `STRIPE_API_KEY` | the `github-actions-crons` key (Reveal live key) |
| `STRIPE_PAYMENT_LINKS` | `s:<$29 plink id>,s:<$19 Playoff Pass plink id>,p:<$69 League Pass plink id>` (both passes for one person are the season plan `s`) |
| `EMAIL_PROVIDER` | `resend` |
| `EMAIL_FROM` | `Beat Your League <reports@beatyourleague.com>` |
| `EMAIL_REPLY_TO` | `hello@beatyourleague.com` (optional: unset means hello@ anyway) |
| `LOG_SECRET` | a long random value: `openssl rand -hex 32`. **Never change it** — it keys every code in the public send log and stop list, and a new one makes the stop list stop nothing. Keep a copy in your password manager; the stop list and privacy requests need it in your shell too |
| `RESEND_API_KEY` | from step 2 |
| `SITE_URL` | `https://beatyourleague.com` |
| `BILLING_PORTAL_URL` | `https://billing.stripe.com/p/login/cNi4gB3Nx3zkcXt1IKaMU00` |
| `SENDER_POSTAL_ADDRESS` | the mailbox address from step 2.6 (one line) |
| `CACHE_KEY` | a long random value: `openssl rand -hex 32`. It encrypts the subscriber list and the sent lineups before they leave each run (`run/statebox.py`), in the cache and in the backup copy the runs keep for 90 days. **Never change it, and keep a copy in your password manager** — without it every saved copy is unreadable, and confirmed League Pass seats and roster changes cannot be rebuilt from Stripe. Once `STRIPE_API_KEY` is set, a run without it goes red rather than saving anything in plain text |

**Also:** the fork pull-request setting and the rest of step 0.5. The repo is public, and a
stranger's pull request that you approve to run can read the automation's cache. Since Oct 23
that cache holds only ciphertext (`CACHE_KEY` never reaches a pull-request run), but the
approval setting is still the first line.

**Check once, after the secrets are in:** `gh cache list --key registry-` and
`gh cache list --key plans-` should list nothing. Those were the old plain-text cache names;
if either lists anything, `gh cache delete <key>` each one.

`github-actions-crons` needs exactly: Checkout Sessions **Read**, Payment Intents **Read**
and Charges **Read** (a one-time pass is entitled while its payment isn't refunded),
Disputes **Read** (a lost chargeback ends a purchase like a refund; without it a disputed
payment shows as "status unknown" and the run goes red until you look), Customers **Write**,
Subscriptions **Write**, everything else None. Subscriptions must be Write: `run/billing.py`
ends each monthly subscription when its final paid period ends (the month the season's last
weekly report falls in).

Keys go only into these boxes — never into chat, a note or a file.

**Tell me when all eleven are in.** With step 5's Worker live too, I put the new links on the
join page and switch the pricing buttons on; it's live on the next push.

## 4. The proving run (~1 hour)

Nobody else's money moves until you've watched your own go all the way through.

1. **Saturday Oct 24** (or any day; when matters only for which emails come — below), buy the
   **$29 Rest-of-Season Pass** at https://beatyourleague.com/join/ with your own email, a real
   card and your real roster. Stripe's page must show one payment of $29, the terms box, and
   no "renews" or "subscription" anywhere.
2. **Actions → daily-intake → Run workflow**, or wait up to an hour. It should go green, and
   its log should say the sealed registry was saved (the "Seal the registry" step).
3. **The emails:**
   - **The welcome:** $29, **one payment, nothing renews**, refunds until your second weekly
     report's week kicks off, and how to stop (reply "stop" to hello@; there is nothing to
     cancel).
   - **Bought Tuesday to Thursday before kickoff:** this week's report, too.
     **Bought Thursday night to Monday (a Saturday purchase):** the roster report that day,
     and the week's report the next Tuesday morning.
   - Open each in Gmail (phone in dark mode, and web), Apple Mail and Outlook if you have
     them. Look for a header that lost its navy, vanished tick boxes, a cluttered preview
     line, or "View entire message". Tell me what you see.
4. **Tell me they arrived.** I turn on `CHECKOUT_CAN_COMPLETE` (step 6). After a Saturday
   purchase that is the welcome plus the roster report; the weekly path is proven by
   Tuesday's send (item 5), which carries your own row first.
5. **Tuesday:** the new week's report by about 8:30am ET (7:30 from Nov 1), weekly-report
   green in Actions. The one case nothing has rehearsed is a Tuesday-to-Thursday buyer's
   same-day weekly report; if one fails, the hourly run retries it.
6. **Keep the pass** (section 10, "Keep your own pass"). If you refund it instead, it's the
   refund steps in section 8, and Stripe keeps its fee: about $1.87 on a $29 pass from a
   Canadian account, or about $1.29 with a USD payout account.

### 2027 only: the monthly billing page, in test mode (15 min)

Not for 2026 — nothing monthly is sold. Before monthly comes back: in Stripe **test** mode,
buy the monthly link with a test card (4242 4242 4242 4242), then open the test billing
page. It must show **Cancel plan** — not "Cancels on…" and Reactivate. Then, with the test
key in your shell, `.venv/bin/python -m run.billing --today 2027-12-20` (dry): it lists the
subscription as in its final paid period only when that period ends after the season's last
weekly report. Press Cancel on the test page and confirm "no further charges".

## 5. The form Worker (~20 min) — do this first

It needs nothing from steps 1–4. One Cloudflare Worker (in the same account as the domain)
switches on:
- **The email list** on the homepage and join page. Until then the form opens the visitor's
  own email app, or, on a computer without one, asks them to email hello@ by hand.
- **League Pass seats**, and each payer's own seat link.
- **"Roster changed?" in every report**, self-serve: the subscriber pastes the new roster, we
  email the address on the subscription a button to confirm, and the next report uses it.
  Without the Worker every change is a reply you apply yourself (`make roster-update`,
  section 8).

The Worker ([infra/form-worker.js](infra/form-worker.js)) holds nothing secret and decides
nothing: every row is checked before it reaches the subscriber list.

1. Cloudflare → **Workers & Pages → Create → Worker** → paste `infra/form-worker.js` →
   **Deploy**.
2. **Storage & Databases → KV** → create a namespace. Worker → **Settings → Bindings → KV
   namespace**, variable name **`ROWS`**.
3. Worker → **Settings → Variables:** `SITE_ORIGIN` = `https://beatyourleague.com`, and
   `FORM_API_KEY` = a random string, marked secret (and, later, `TRIAL_OPEN` — step 7):
   ```bash
   openssl rand -hex 24
   ```
4. The signing secret — it signs roster-update codes AND each League Pass payer's seat link:
   ```bash
   openssl rand -hex 32
   ```
   Set it once and keep it. If you ever change it, put the OLD value in a GitHub secret
   `UPDATE_SECRET_PREVIOUS` (comma-separate several) for the rest of the season: seat links
   already shared were signed with it. Seats already confirmed don't depend on it.
5. GitHub secrets: `FORM_ENDPOINT` = the Worker URL, `FORM_API_KEY` = step 3's value,
   `UPDATE_SECRET` = step 4's value. (`SITE_URL` from step 3 builds the seat links.)
6. **Your own domain (5 min):** Worker → **Settings → Domains & Routes → Add → Custom
   domain** → `forms.beatyourleague.com`. Use that as the Worker URL everywhere: a
   `*.workers.dev` address is easily blocked, and the launch check warns about it. Then, on
   the same screen, switch the **`workers.dev`** route **off**: left on, it is a second door
   that the flood limit below does not cover.
   - **A flood limit (5 min, free):** Cloudflare → `beatyourleague.com` → **Security → WAF
     → Rate limiting rules → Create**: name `form posts`; when the hostname equals
     `forms.beatyourleague.com` **and** the request method equals `POST`; same IP, more
     than **5 requests per 1 minute** (if the free plan offers only 10 seconds, use that with
     2 requests); action **Block** for the shortest duration offered. A real visitor posts
     once; this keeps one stranger from spending the day's free writes.
   - **The visit counter (2 min, optional):** **Storage & Databases → Analytics Engine** →
     create a dataset `byl_counts`; Worker → **Settings → Bindings → Analytics Engine**,
     variable name **`COUNTS`**, that dataset. Without it the counter does nothing and every
     page still works.
7. **Tell me the Worker URL** (not a secret). I wire it into the homepage form and the join,
   confirm and League Pass pages, switch on the League Pass button and the FAQ's roster
   answer, and — once email sends (step 2) — the "Try it free" button (`TRIAL_OPEN`, on the
   homepage and the join page). **The same day, set the Worker's own switch:** Worker →
   **Settings → Variables → Add** `TRIAL_OPEN` = `true` (plain text). The Worker refuses
   every free-report request while it is unset, and the launch check fails if the site and
   the Worker disagree.
8. **Start the crons on time (5 min, same Worker).** GitHub started the Tuesday runs 5–7
   hours late on Oct 6 and 13, so the Worker starts them and GitHub's own schedules stay as
   the backup.
   - GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained →
     Generate**: owner `beatyourleague`, only `beat-your-league`, **Actions: Read and
     write**, nothing else, the longest expiry — and put that date in your calendar.
   - Worker → **Settings → Variables and Secrets → Add**, type **Secret**,
     `GH_DISPATCH_TOKEN` = that token.
   - Worker → **Settings → Triggers → Cron Triggers → Add** → `17,47 * * * *`.

   Nothing is sent twice if both start a run: every email is keyed. Re-pasting the current
   worker also turns on deletion of form rows after about 400 days (the privacy policy
   promises it).

## 5b. The page counter (~10 min, right after step 5)

Without it you can see sign-ups and sales but not visits, where people come from, or where
the signup page loses them. `site/count.js` — on every public page, the generated ones too
(both samples, this week's sample, the ledger and the backtest page carry it from their next
build) — sends one anonymous line per page view and per signup step (which page or step, the
`?via=` tag, the referring site, phone or desktop, checkout open or closed) to the form
Worker's `/e`, which adds the country and writes it to **Cloudflare Analytics Engine** (free:
100,000 lines a day, kept three months). Not KV: KV's 1,000 writes a day belong to the forms, and running out makes seats and the
waitlist refuse. No cookie, no IP address, no email, and nothing at all from a browser that
sends Global Privacy Control or Do Not Track. Privacy §3 already says exactly this.

1. Cloudflare → **Workers & Pages → Analytics Engine** → enable it if asked (free).
2. Form Worker → **Settings → Bindings → Add → Analytics Engine**: variable name **`COUNTS`**,
   dataset **`byl_counts`** → **Deploy**. The dataset is created by the first line written.
   If the dashboard doesn't offer that binding, tell me: the fallback is a small
   `wrangler.toml`, and it has to declare the `ROWS` KV binding, the variables and the cron
   too, or the deploy drops them.
3. Paste the current `infra/form-worker.js` again → **Deploy** (it carries the `/e` route).
4. Worker → **Settings → Observability**: turn **Workers Logs** off (or at least invocation
   logs) if the dashboard offers it. Otherwise Cloudflare keeps each request's log for 3 days
   — the "ordinary request logs" privacy §3 already mentions. The cron alarm reads Cron
   Events, not logs, so nothing goes blind.
5. **Keep these off on the zone**, and keep the `beatyourleague.com` and `www` records
   **DNS only** (grey cloud):
   - **Security → Bots → Bot Fight Mode.** On the Free plan nothing can be exempted from it,
     and it may challenge the hourly intake's reads from GitHub's servers — a failed read
     makes the intake refuse to write the subscriber list, so new buyers stall. It also sets a
     `__cf_bm` cookie on `forms.` that privacy §3 says doesn't exist.
   - **Web Analytics automatic setup, Zaraz, Email Address Obfuscation, Rocket Loader.** Each
     injects a script into the pages, breaking privacy §3's "no request to any third party".
   The launch check's live gate turns red if a cookie or an injected script ever appears.
6. **My Profile → API Tokens → Create Token → Custom token**: permission **Account ·
   Account Analytics · Read**, account resources: this account only, TTL one year (put the
   date in your calendar). Copy the **Account ID** from the Workers & Pages overview.
7. In the repo folder on your own machine, put both in `.env` (gitignored, never committed):
   ```
   CF_ACCOUNT_ID=<the 32-character account id>
   CF_ANALYTICS_TOKEN=<the token>
   ```
   Not a GitHub secret: `make stats` never runs in CI (it refuses to), because on a public
   repo the job log — the counts and the sales — is public.
8. Turn on Do Not Track or Global Privacy Control in your own computer's browsers
   (Chrome: Settings → Privacy and security → Third-party cookies → Send a "Do Not Track"
   request; Firefox: Settings → Privacy & Security → Tell websites not to sell or share my
   data), so your own visits aren't counted. **On an iPhone, Safari and Chrome send
   neither**, so a visit from them counts like anybody's. To keep your phone out, open the
   site in DuckDuckGo's browser (it sends Global Privacy Control on its own), or in Firefox
   on Android with the same setting on — or accept that your own phone views are in the
   numbers, a handful a day at most.
9. **Tell me "counter on".** I set `ENDPOINT` in `site/count.js` to
   `https://forms.beatyourleague.com/e` and run the launch check ("The page counter answers
   204 with no cookie").
10. From the next day, `make stats` opens with a **TRAFFIC** block: landing views → buy-page
    views → rosters checked → buy presses (checkout open or closed), the free-report steps,
    and the week by channel, referrer, page, device and country.
    `.venv/bin/python -m run.stats --html data/stats.html` writes the same view as a page to
    open in a browser (only to a gitignored path). If two days pass with the counter on and
    nothing recorded, the launch check warns: a Worker missing its `COUNTS` binding still
    answers every line with a 204.

## 6. Opening morning

1. **After step 4's two emails arrive,** I turn on `CHECKOUT_CAN_COMPLETE`: the "leave your
   email" box retires and the page says the first report lands today.
2. **The same morning, the waitlist's one email.**
   - Copy every sign-up that came in by email (to hello@, subject about the launch) into a
     file `signups.csv` with one column headed `email`.
   - In Terminal, set the sending details for this window only (`read -s` keeps keys out of
     your history):
     ```bash
     read -s RESEND_API_KEY && export RESEND_API_KEY
     read -s FORM_API_KEY && export FORM_API_KEY
     export EMAIL_PROVIDER=resend EMAIL_FROM='Beat Your League <reports@beatyourleague.com>'
     export SITE_URL=https://beatyourleague.com FORM_ENDPOINT=https://forms.beatyourleague.com
     export SENDER_POSTAL_ADDRESS='<the mailbox address>'
     read -s LOG_SECRET && export LOG_SECRET
     ```
   - Preview both lists. Each preview prints how many mailboxes it would mail and the
     commonest domains: read both, and stop if a domain or a count looks wrong (a flood of
     sign-ups from one domain is not your audience). Then send each with its own ceiling, the
     count its preview printed:
     ```bash
     make waitlist-preview && make waitlist-preview LIST=signups.csv
     make waitlist-send MAX=<first count> && make waitlist-send LIST=signups.csv MAX=<second count>
     ```
     A send refuses without `MAX`, or if more are waiting than it says. Anyone on both lists
     gets one email.
   - **Count before you send.** Resend's free tier sends 100 a day, and opening morning's
     welcomes and first reports share it. If the two previews add up to more than about 80
     minus two per buyer you expect that day, send the waitlist in the evening, or the next
     morning, rather than paying for a month of Pro.
   - **Commit and push `data/processed/sent.jsonl`.** The crons read the committed copy; it
     is what stops a second send. Then delete `signups.csv`, **and delete the "Tell me when it
     opens" emails in Gmail** (and empty Gmail's Bin): the privacy policy says waitlist
     sign-ups expire, and before the Worker those sign-ups were emails that never would.

## 7. Selling

The order is PLAN §5.1's — subscribers per hour of your time.

1. **One handle, three places (30 min, once).** "Beat Your League" on X, Reddit and Discord —
   the same pseudonymous name, never your personal account. Bio: *"I make Beat Your League, a
   weekly start/sit report for your own roster"* and the link `beatyourleague.com`. Replies
   never carry the link; the bio does. In **Google Search Console**, add the domain and verify
   it with the TXT record it gives you (Cloudflare → DNS). After 2–3 weeks of posting, send me
   the handles: I add them to the site footer.
2. **Talk to five managers — Tuesday Oct 27, for Week 8.** Before anyone pays, find out
   whether they would. Ask five managers you already know (your leagues, a Discord you're in)
   for their roster, and send each this week's report on it, free. Build them Monday night to
   Thursday afternoon: `run.trial` refuses a week already underway, and before Monday night's
   game it builds from a week that isn't finished. It needs `LOG_SECRET` in the shell
   (`read -s LOG_SECRET && export LOG_SECRET`):
   ```bash
   pbpaste | .venv/bin/python -m run.trial --email them@example.com --roster - --print
   ```
   Nothing is emailed from your Mac: it prints a text version to paste back. Add
   `--scoring half_ppr`, `--template sf` or `--size 10` to match their league; a name it
   can't place stops and names the line (ask, don't guess). Ask each: *Would you have set your
   lineup differently? What would make you pay? How many teams do you run?* — and once
   checkout is open, send them the link: a purchase is the only real answer to "would you
   pay". Put their words (no names) under "What managers said" in IDEAS.md. None of it goes on
   a selling page unless `content/testimonials.md`'s consent rules are met.
3. **Your own leagues.** A season pass each, or the League Pass once seats are live.
4. **Commissioners, Discord mods, small podcasters — where you already are.** No cold email
   (your rule): a commissioner in a league you play in, a mod of a Discord you post in, a
   podcaster whose chat you're in. Offer their league a free week — a `run.trial` report per
   roster — and a link tagged for them, `beatyourleague.com/?via=<their-name>`, so
   `make stats` shows what came from them. A revenue share is section 10's call.
5. **Discords and group chats.** Ask a mod before mentioning the product. When someone asks
   what to use, paste this week's sample (`beatyourleague.com/this-week.html`) or the
   pinned one (`/sample-report.html`) with one line of answer.
6. **X replies, about 20 minutes a day.** Answer real start/sit questions with the product's
   own facts:
   ```bash
   make ask A="Jalen Hurts" B="Bo Nix"
   ```
   It prints both players' projection, last three games, usage, status and opponent. Quote a
   % only with `ARGS=--publish`: that records it on the public record before you post it, and
   Monday grades it. No links in replies.
7. **Reddit — answers, not posts.** r/fantasyfootball: answer in the daily start/sit threads
   only, no links, no self-promotion. r/Fantasy_Football and r/FFCommish: read each one's
   rules and ask the mods first. At most one post saying you built this every 2–3 weeks, and
   only where the rules allow it (r/FFCommish: framed as the League Pass for commissioners).
8. **The weekly drafts.** Tuesday's cron writes `content/this-week.md` from the live sample —
   the odds in it are only ones already on the public record. `make content` drafts the
   Monday and Friday posts from the record, one call at a time.

**Held back:** the mention campaign in `content/pitches.md` emails other sites, which you've
ruled out (Sep 2026).

Everything you post: no "accurate", "proven", "calibrated", "tested" or "we hit X%", no
win-loss totals, nothing about betting.

## 8. Every week from here

| When (ET until Nov 1) | What runs | What you do |
|---|---|---|
| Tuesday 8:17am, retry 12:17pm | **weekly-report:** new signups, every subscriber's report, this week's live sample (its odds are recorded before kickoff) | Open your own report |
| Daily 10:17am, plus every hour at :47 | **daily-intake:** purchases, welcomes, first reports, end-of-season dates on monthly plans, renewal notices | Nothing, unless it goes red |
| Saturday 12:17pm | **saturday-final-check:** Friday's injury report against each lineup sent; mails only those who must change something | Nothing, unless it goes red |
| Monday 9:17am | **monday-receipts:** grades last week's calls, republishes the record | Nothing, unless it goes red |

UTC: Tue 12:17 and 16:17, daily 14:17 and :47 hourly, Sat 16:17, Mon 13:17. The Worker
starts each on time (`17,47 * * * *`); GitHub's schedules are the backup. From Nov 1 the ET
times are an hour earlier.

A red run opens a GitHub issue and GitHub emails you. The same failure again comments on the
open issue instead, so close each once it's fixed.

**"A scheduled run did not happen"** names the run and the week. Before that week's first
kickoff, run that workflow by hand from Actions (nobody is mailed twice). After kickoff,
don't: the Tuesday run refuses a week already underway.

**Rebuilding the live sample by hand:** `make live-sample` before the week's first kickoff
records its odds on the public record — commit the ledger file with the page.
`make live-sample ARGS=--no-record` previews. After the first kickoff it refuses: leave the
page as it stands until Tuesday. A forced rebuild (`--force`) records nothing, so don't publish
one — Week 6's page was rebuilt that way on Oct 16 and printed odds that are on no record.

**If the sealed registry is lost** (an issue saying the send log shows sends to customers but
no sealed registry exists): every cache entry and every backup is gone — expired after 90 days
of failed runs, or deleted. Nothing is mailed until it's fixed, because a registry rebuilt from
Stripe alone drops every confirmed League Pass seat and roster change and would send those
people the wrong report. If you have a copy (`data/sealed/registry.enc` from a run's artifact),
ask me to restore it. If not: Settings → Secrets and variables → Actions → Variables → add
`ALLOW_EMPTY_REGISTRY` = `true`, run **daily-intake** once by hand, then **delete the
variable**. Seat holders and anyone who changed their roster then re-confirm through their
links; tell me first so I can list who.

**A roster change sent by email** (until the Worker is live, or a subscriber who'd rather
reply): put the names they sent in a file, one per line, then
```bash
make roster-update EMAIL=fan@example.com ROSTER=names.txt
```
It needs `UPDATE_SECRET`, `FORM_ENDPOINT` and `FORM_API_KEY` in the shell (the Worker takes
a post from outside the site only with the read key). `ARGS=--dry-run` resolves the names and
posts nothing. The next hourly intake applies it.

**When someone asks to stop** (mail to hello@ saying stop or unsubscribe; every 2026 report's
unsubscribe button arrives with the subject "stop"). Everyone in 2026 — a pass buyer, a
League Pass seat, a free-report reader — stops the same way, because a one-time pass has no
billing to cancel: run this (with `LOG_SECRET` in your shell — the list holds keyed codes),
then commit and push within 10 business days, as terms §4 promises:
```bash
.venv/bin/python -m run.suppress their@example.com
```
Reply that it's done. Stopping the emails doesn't refund anything; if they also ask for their
money back, that's the refund checks below. Someone who signs up again:
`.venv/bin/python -m run.suppress --remove their@example.com`.

**A League Pass buyer asks to reset seats** (their report's seat count shows seats they
don't recognize, usually because their link was forwarded outside the league): find the
pass's payment in Stripe (its id starts `pi_`), then
```bash
make seat-reset PASS=pi_… EMAIL=buyer@example.com
```
(`SITE_URL` and `UPDATE_SECRET` in your shell print the new link.) Commit and push
`data/processed/seat-resets.txt`, **then** reply to the buyer with the new link. The next
hourly run releases every seat claimed before the reset, and the old link stops working;
the leaguemates they want claim again with the new one.

*2027, once subscriptions are sold again:* a subscriber who says stop is sent the
billing-page link instead — stopping a payer's emails while billing continues is the one wrong
answer — and someone whose older subscription Stripe's billing page can't show (it opens only
the NEWEST customer for an email) is cancelled by you the same day: Customers → search the
email → the older subscription → **Cancel subscription → At period end**.

**A privacy request** (to hello@: what do you have, correct it, export it, delete it). Answer
within 30 days:
1. `make privacy-code EMAIL=their@example.com` on your Mac (needs `LOG_SECRET`). It prints a
   12-character code. Never put the address itself into GitHub.
2. Actions → **privacy-request** → Run workflow → action **show**, **export** or **delete**,
   and the code. The result lands in hello@, never in the log. A **delete** also replaces the
   encrypted cache and backup copies and deletes every older one, which still held the rows. A **correction** to a roster is
   `make roster-update`; to an email address, cancel and re-buy, or ask me.
3. For **delete**: the email lists what's left by hand — the Stripe customer (cancel any live
   subscription first, then delete the customer), form rows the Worker couldn't delete, and the
   hello@ threads. Run **show** the next day: every count should be 0. Reply to them saying
   what was done.

**Changing the terms or the privacy policy.** Publish the new page with a new date (and the
new `TERMS_VERSION` / `TERMS_HISTORY` entry, which I add), then before the date it takes
effect: Actions → **change-notice** → page, effective date, a one-or-two-sentence summary of
what changes; run it once unticked (dry). For the real send, first make its approval code on
your Mac (`LOG_SECRET` in the shell), with the same page, date and words:
```bash
make notice-approval PAGE=terms EFFECTIVE=2026-11-15
```
and paste the summary when it asks, exactly as it goes in the workflow's box (it prints back
the words it signed). Don't put the summary on the command line in double quotes: the shell
turns `$69` into `9`, the code is signed over other words, and the workflow refuses it.
then run it again ticked, with that code in the **approval** box. Everyone entitled today gets
one email. Without the code the run refuses and sends nothing — so the Worker's dispatch
token, which can start any workflow, can't mail every subscriber words of its own.

**How's demand?** Pull, then `make stats`: counts and dollars only, never an address —
traffic and the signup funnel (step 5b), waitlist, free-report requests, roster updates,
seat claims and seats filled per League Pass, sends by week, passes sold this season by type
with gross, refunded, net and the refund rate, free report → paid within 14 days, and paid
signups by `?via=` tag. It needs `FORM_ENDPOINT` and `FORM_API_KEY` for the form rows, the
step 5b pair in `.env` for traffic and, for payments, a separate restricted key in
`STRIPE_API_KEY` with **Read** on Subscriptions, Checkout Sessions, Payment Intents, Charges
and Refunds (the cron key can't read refunds). The Stripe Dashboard's phone app is the live
view of money; `make stats` is the funnel around it. It never runs in CI.

**The season's end.** Week 17's report says it's championship week on the big platforms'
defaults and a Week 18 report follows; Week 18's says it's the last and what the plan does
next. After the last game every weekly job exits quietly until the next schedule is out.

**A refund request, in three checks:**
1. **Inside the window?** Find the first week below whose kickoff comes after they paid
   (Stripe shows the time). That week's report was their first weekly report; their window
   closes at the kickoff **one row further down**. Paid within two hours of a kickoff? Start
   from the next row. *Example: paid Wed Oct 21 → first report Week 7 → closes Thu Oct 29,
   8:15pm ET.* If a send of ours ran late and their second report arrived after its week
   kicked off, they have a week from that send — ask me and I'll check the send log.
2. **Their first refund?** Search their email under **Customers**. One per person (one per
   league for a League Pass).
3. **Issue it:** **Payments** → their payment → **Refund** → the full amount. That is all: a
   one-time pass is entitled only while its payment is not refunded in full, so the next
   hourly run drops them and the reports stop by themselves (a League Pass refund ends its
   seats the same way). Reply saying it's refunded and that cards take 5–10 days to show it.
   Stripe keeps its fee (about $1.87 on a $29 pass). *2027:* a subscription is cancelled
   (**Immediately**) and every paid invoice on it refunded.

**A dispute (a chargeback).** Stripe emails you, and the payment shows **Disputed**. It costs
a C$15 fee whatever the outcome, and you have about a week to answer.
1. **Was it a buyer who never got anything?** Check `data/processed/sent.jsonl` for their
   week keys first. If a send failed, accept the dispute (or refund), apologise, and tell me.
2. **Otherwise, answer it** in the Dashboard (Respond → "Product or service was provided"):
   - **The consent record:** the Customer page's metadata — `byl_terms_accepted`,
     `byl_terms_version` (the terms in force when they paid) and `byl_terms_accepted_at` (the
     checkout's own time) — and the Checkout Session's "terms of service accepted".
   - **What they were told before paying:** the terms page as of that version
     (`https://beatyourleague.com/terms.html`), and the join page's line beside the price
     (one payment, nothing renews, the refund window).
   - **What was delivered:** the send-log lines for their reports — each key is
     `<season>-wNN-<code>` with `sent_at` and the email provider's message id; ask me to pull
     them, with the welcome. Never paste anybody else's lines.
   - Two or three sentences in plain words: what they bought, when, what arrived, and that
     the refund window was open until a stated kickoff and no refund was requested.
3. **A dispute you lose (or accept) does not stop the reports by itself** — the code ends a
   pass only on a refund — so add them to the stop list (`run.suppress`, above).

| Week | First kickoff (ET) |
|---|---|
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

From the published NFL schedule the product reads. A flexed game can move a row.

**When a payment is disputed** (a chargeback). Stripe emails you, and the next hourly run
goes red with `DISPUTE NEEDS A RESPONSE: <pi_… or sub_…>` until it is answered. The buyer is
still served while it is open (a dispute can be won); a LOST one ends their reports like a
full refund. Answer it before Stripe's deadline (it is lost by default after that): Stripe →
**Payments → Disputes** → the dispute → **Submit evidence**, product type *digital
service*, and attach:
- **The consent record:** the customer in Stripe → **Metadata**: `byl_terms_accepted`
  (they ticked the terms box at checkout), `byl_terms_accepted_at` and `byl_terms_version`,
  the date of the terms in force when they paid (the matching page is `site/terms.html` at
  that date in the repo's history).
- **What was delivered, and when:** their send-log lines in `data/processed/sent.jsonl` —
  each key carries the week and the subscription's code (never an address), with the time it
  was sent and Resend's message id. Resend → **Emails** → search the id shows it delivered.
  Ask me for the lines for one buyer if you can't find them.
- **The refund policy they agreed to:** terms §5, and whether they asked for a refund (they
  usually didn't).
Never refund a payment that is already disputed: the dispute takes the money back, and a
refund on top pays it twice.

## 9. The dates you pre-committed to (PLAN §6)

**Oct 11 was read on Oct 16, late and honestly: it measured nothing.** Checkout never opened:
0 subscribers, 0 free reports, 0 trials from outside your network. The pivot rule's words —
under 25 subscribers on Oct 11 means stop building product — were met by default, not by a
verdict from buyers. The proposal for what replaces it is the first decision below.

**The monthly January stub — built away (Oct 18, 2026).** The recommendation recorded here is
now how `run/billing.py` works: a monthly subscription is ended at the close of its final paid
period — the one the season's last weekly report (Tue Jan 5, 2027) falls in — so no charge
starts a period with no report in it and there is no part-month after the season. Until its
final period a monthly plan carries nothing, so its billing page keeps the normal Cancel
button. Nothing to decide.

## 10. Decisions waiting on you

Each has a recommendation. None is decided until you say so.

**Reset the targets to a proof season, counted from the day checkout opens** (PLAN §6, §8).
The Oct 11 gates and "~100 paying subscribers by January" were written for a September
launch, and the Nov 10 / Dec 22 proposal was written in fixed dates for an opening that
slipped. *Recommend:* stop feature work except launch blockers and defects a paying customer
would hit, and adopt PLAN §6's gates as rewritten Oct 23 — **D** is the day checkout opens:
by **D+14**, at least 20 free reports sent, at least 5 paid, at least 2 from outside your own
leagues; by **D+28**, refunds at 15% or less (25% or more: talk to every refunder before
another selling hour); each League Pass at least half its seats claimed within 14 days; and
by Week 16 (Dec 22), about 30 purchases plus 2 League Passes and at least 30 graded rows on
the public record. Weekly, read replies, roster-update requests, stop requests, refunds and
your hours against the ~59-hour budget — never an open rate, which the privacy promise rules
out measuring. Under 5 paid by D+14 means stop selling hours and spend the rest of the season
on the 2027 work below. Tell me the day you adopt them; I write D into PLAN §6.

**A USD payout account.** Stripe converts every US-dollar sale to Canadian dollars at 2%:
$0.58 of each $29 pass, and it keeps that on a refund. *Recommend:* add a USD bank account in
Stripe → Settings → Payouts before the first sale (check your bank's fees for it). Then
`STRIPE_PAYOUT_CURRENCY=usd` in your shell clears the launch-check line.

**Hosting, and the public repo** — now its own section, 11, with the steps in order.

**A list you own.** Every lead today gets one email, ever, so nobody from 2026 can be reached
in August 2027. *Recommend:* one unticked box — "Email me when the 2027 season opens" — on the
free-report form, the waitlist, the last report and your cancel replies, stored as its own
form row and held to the waitlist's one-email rule. Build it before the last report (Jan 5).

**2027: the renewal date, and next season's roster.** Moot for 2026 — a one-time pass renews
nothing. For the subscriptions 2027 brings back: a pass renews on its purchase anniversary, so
an October buyer would renew mid-season still holding the old roster (rosters don't roll to a
new season yet). *Recommend:* anchor every 2027 pass to one late-August renewal date, stated
on the card and in the terms, and build the roster roll — hold reports until a post-draft
roster is confirmed — before July 2027.

**The founding price, and how 2026 buyers hear about 2027.** The site promises a 2026 buyer
"your 2027 season pass is $39, never more", but nothing says how long "never" lasts, what a
2026 League Pass buyer gets, or that we may email them when 2027 opens — the privacy page
lists no such email, and a one-time buyer gets no renewal notice. *Recommend:* section 12's
proposed sentences, before the first sale. Stripe already holds every 2026 buyer, so the
2027 link can honour the price without new code now.

**A price for a second team.** Each team is its own pass today, so a manager with three
leagues stops at one. *Recommend:* not before the first ten buyers, and never at checkout
(one decision there, PLAN §4): offer a second team the way the League Pass is offered — its
own link, in the welcome or a report footer after a good week.

**A seat cap per League Pass — built (Oct 17 2026).** One $99 pass honoured unlimited seats,
so a payer's address leaked from a group chat was a free-report generator. Built: one seat
per team in the payer's league (`run/intake.PassInfo.seat_cap`), the first confirmed first —
a claim counts only once its own inbox confirms it — and a claim past the cap is told so by
email. Stated on the League Pass page and in the terms (§1, dated 17 October 2026).

**The League Pass refund window.** It closes when the payer's second report's week kicks off,
but seats start the Tuesday after they claim — leaguemates may have seen one report or none
when the commissioner loses the refund on the league's money. *Recommend:* count a pass's
window from the first seat's first weekly report. Terms §5 and the pass welcome change
together.

**Buyers from Thursday night to Sunday.** They get the roster report that day and no lineup
for this Sunday, while the card says "Your first report the day you sign up". *Recommend:* now,
say on the card which report lands today ("join before Thursday's kickoff for this week's
lineup"); a same-week lineup over games not yet played is a 2027 idea that needs its own
preregistered test.

**Late news: practice reports and gameday inactives.** Wednesday–Friday practice
participation is already in the injury file the product reads, unused until Saturday.
Gameday inactives (90 minutes before kickoff) have no free, licensed, timely source.
*Recommend:* add practice participation to the Saturday check's detail now (facts only, no
new email); a Thursday "practice watch" email only if Saturday checks show people act on
news; no inactives email without a paid source (PLAN §2 first).

**Re-pin the flagship sample.** The landing's closest call is Bijan Robinson over Chase Brown
at 70%, which reads as "start your studs". *Recommend:* re-pin by a rule written before
looking — the live sample's roster rule applied to 2024, week 10 — and quote whatever close
call it prints. Every pinned landing figure moves in one deliberate commit.

**The offseason.** Nothing carries a subscriber past the week 10–12 elimination cliff or into
the 2027 renewal. *Recommend:* a "your season, graded" email in January, built from each
subscriber's own record; a free post-draft roster check as the August lead magnet (IDEAS).

**Counting visits.** Built: the site's own page counter (step 5b) — our domain only, no
cookie, no ID, nothing under GPC or Do Not Track, and privacy §3 says so. Considered and
turned down: Cloudflare Web Analytics (a script from cloudflareinsights.com on the pages
where emails and rosters are typed, which EasyPrivacy blocks; no custom events, so no
funnel), Plausible ($9/mo) and Fathom ($15/mo) — paid, third-party, and blocked the same
way; Umami Cloud (third-party script, blocked); Counterscale (wrangler plus a public
dashboard, page views only); and Cloudflare's own zone counts, which need the site proxied
(today it isn't, and proxying is its own decision). Switching any of those on later is three
changes in one commit: a PLAN §2 line if it costs money, privacy §3 rewritten to name it and
drop "makes no request to any third party", and its host added to the site's origin
allowlist test.

**The look.** Navy and gold, slanted italic caps and stadium glows are the daily-fantasy and
betting apps' style, which works against "not a betting product". *Recommend:* after opening,
pilot an editorial version on one page (upright headlines, square buttons, no glows) and
compare before touching the rest.

**The graded record on social.** The drafts quote one recorded call at a time, never a total
or a rate. *Recommend:* keep it so until the record holds 30+ graded rows and you've read
them; marketing the record is a decision, not a default.

**A partner share.** Commissioners, mods and podcasters (section 7.4) may want something.
*Recommend:* a 30% first-year share paid by hand, counted from their `?via=` tag in
`make stats`, offered only once someone asks.

**Keep your own pass.** The public record started with Week 7: the Oct 20 Tuesday build
recorded the live sample's first three calls (`data/processed/ledger/typed-ppr-12-2026`,
committed by that run), and Monday grades them. *Recommend:* keep your step-4 pass — it adds
a real roster's calls to the record, graded every Monday.

**A sender postal address.** US (CAN-SPAM) and Canadian (CASL) law both want one in
commercial email; every email now prints it, and the launch announcement refuses to send
without it. *Recommend:* rent a virtual mailbox or PO box before step 3, never a home address.
Whether that mailbox is enough for Ontario's online-sale rules is section 12's first
question, and it comes before the first $69 sale, not "before scale".

## 11. The repo and the host — private, or a rewritten history

**What is public today** (checked Oct 23 2026). The repo is public, owned by a personal GitHub
account, with 0 forks and not yet archived by Software Heritage. Its history holds your
**personal Gmail address** — added to the join page in two August commits, removed later, and
still reachable from `main` (and from the five Dependabot branches until you delete them) — and one commit message carries a
local path with your **first name**; the test fixtures use the same name. The playbook is
public too (CLAUDE.md's selling strategy, PLAN's status, this file), as are the Actions logs,
artifacts and the auto-filed issues, and once sales start the committed send log shows how
many reports go out each week. And GitHub's Pages terms rule out a site "primarily directed
at … facilitating commercial transactions", which this site is.

Two ways to fix it. **Recommended: A — move the site to Cloudflare Pages now, make the repo
private once the Worker has proven itself.**

**A1. Before the first launch post (no cost, nothing else changes):**
1. **Verify the domain for GitHub Pages** — step 0.7. Do this before ANY change to hosting
   or visibility.
2. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → this repo only.
   Framework preset **None**, build command **empty**, build output directory **`site`**,
   and under Build watch paths include **`site/*`** only (the crons commit `data/` hourly; the
   free plan allows 500 builds a month).
3. On the new project → **Custom domains** → add `beatyourleague.com`, then
   `www.beatyourleague.com`. Cloudflare rewrites the two DNS records itself.
4. Check from Terminal: `curl -sI https://beatyourleague.com/join/` must show
   `server: cloudflare` and a `content-security-policy:` line, and
   `curl -sI https://beatyourleague.com/terms.html` a redirect to `/terms`. That is
   `site/_headers` taking effect: HSTS, no framing, nosniff, the referrer policy, and each
   page's script policy (`make headers` keeps it current; the suite fails if it isn't).
   Open the join page, check a roster and press the buy button once: it must reach Stripe.
5. **Tell me**, and I retire `pages.yml`; then GitHub → repo Settings → **Pages → Unpublish**.
   Don't put the orange cloud in front of GitHub Pages instead: it can break GitHub's
   certificate renewal, and Pages still couldn't send these headers.

**A2. Making the repo private — later, in this order** (the review's sequencing):
1. **Step 5's Worker runs the crons for a week or two on time** (its dispatches show in
   Actions as "workflow_dispatch").
2. **I drop GitHub's hourly backup cron** (`47 * * * *` in daily.yml). This comes first
   because a private repo on the Free plan gets 2,000 Actions minutes a month and bills every
   job at least one minute: the hourly intake fires twice an hour while both the Worker and
   GitHub's backup start it — about 1,440 billed minutes before tests and the weekly runs —
   and at the cap every cron stops mid-month. With the backup gone it is about 720 plus the
   daily, weekly, Saturday and Monday runs.
3. GitHub → Settings → **Billing and plans → Budgets and alerts**: a $0 Actions budget with an
   email alert at 75%, so the cap warns instead of surprising.
4. Settings → General → **Change visibility → Private**. Then close the old issues (the
   August Dependabot branches went in "Where things stand").
5. A week later, Settings → Billing: check the minutes used. Paid minutes need a PLAN §2 line
   first.

*What going private costs on the Free plan:* rulesets and branch protection (step 0.5's
ruleset goes) and environments with required reviewers stop working — GitHub Pro is $4 a
month and needs a PLAN §2 line if you want them back. The change-notice approval does not
depend on either (it is a code you make, `make notice-approval`). The public git history
stops being the outside proof that the record's calls were never edited; publishing the
ledger's own JSONL beside `site/ledger/` would restore it (IDEAS). And it hides nothing that
was already copied: treat the Gmail address as public for good (step 0.1).

**B — stay public and rewrite history** (not recommended). `git filter-repo --replace-text`
with a file kept outside the repo that maps the old address to `hello@beatyourleague.com`,
plus `--replace-message` for the path, then a force-push of `main` (with the Dependabot
branches already deleted), re-cloning every copy (including this machine's worktrees), renaming the test
fixtures, and asking GitHub Support to purge cached views of the old commits. What it costs:
**every commit id changes** — and the preregistrations this product's numbers rest on are
cited by commit id (CLAUDE.md: 6bacdc7, 6833098, 5846734, d4cfe73, cc98c2a, 3f224ae, a199a01),
so the proof that each method was frozen before its run would point at commits that no longer
exist. It also leaves the playbook public and the Pages terms unmet. Only if you must stay
public.

## 12. Questions for a lawyer, and the wording waiting on them

Book one Ontario consumer-law consult **before the first $69 sale** (not legal advice; these
are the questions, not answers). *Recommend in the meantime:* sell the $29 and $19 passes
(both under C$50) and hold the League Pass link back, or accept that a League Pass buyer may
have a statutory cancellation right on top of our refund.

1. **Ontario internet agreements over C$50 (CPA 2002 s.38, O.Reg 17/05).** The $69 League Pass
   is about C$95, and 2027's $39 pass about C$53. Before purchase the seller must disclose its
   name (and trading name), telephone, business address and the currency. (a) Does a numbered
   Ontario corporation trading as Beat Your League satisfy "name" without your own name on
   the site or receipts (its director records are public)? (b) Is the rented sender mailbox
   acceptable as the business address? (c) Is a VoIP number enough? (d) Is the welcome email
   an adequate copy within 15 days, given it carries no consumer name (names are off at
   checkout)? (e) Is the 2002 Act or the 2023 Act in force for sales this season? (f) Business
   Names Act registration versus incorporating.
2. **California B&P §17538(d)** — an internet seller's legal name and street address; does the
   same mailbox answer it for US buyers?
3. **Where we sell (EU, UK, the rest).** Terms §1 sells to anyone, and EU/UK VAT on an
   electronically supplied service from a non-resident seller applies from the first sale.
   Is "Sold to customers in the United States and Canada" plus refunding anyone else enough?
   (The intake flagging a paid session whose billing or card country is outside US/CA is a
   small code change once this is decided.) And Canada's provincial rules: QST for Quebec
   buyers, BC PST — at what point?
4. **Quebec.** Bill 96 is generally read as requiring a standard-form consumer contract to be
   offered in French first, and the terms are English only; Quebec's own distance-contract
   rules add disclosures. Sell to Quebec with a French version, or exclude it? Until
   answered, *recommend* treating a Quebec postal code (starting G, H or J) like a buyer from
   outside the US and Canada: refund, with an apology.
5. **The founding price and the 2027 email.** Is the proposed wording below enough to make
   "never more" definite, and is one email to 2026 buyers when 2027 opens covered by CASL's
   two-year existing business relationship (Canadians) and CAN-SPAM's opt-out (US)? And CASL
   express consent for the planned "Email me when 2027 opens" box: the sender's name, mailing
   address, a contact and a withdrawal statement beside it.

**Proposed wording, for you to approve or change — I have changed none of it.** Each needs a
new `TERMS_VERSION` and `TERMS_HISTORY` entry and new page digests, which I add with it, and
a change notice (section 8) if it reaches anyone who has already bought.
- **Terms §1 (where we sell):** "Beat Your League is sold to customers in the United States
  and Canada [outside Quebec, until a French version is published]. If you buy from anywhere
  else, we refund the full amount and send nothing further." The join page's terms line gets
  the same first sentence.
- **Terms §3 (the founding price):** "If you bought a 2026 pass, your 2027 season pass is $39
  USD, and stays $39 for every season you renew without a gap. [A 2026 League Pass buyer's
  2027 League Pass is $___ — your decision.]"
- **Privacy §1, a reason we email:** "If you bought a pass: one email when next season's pass
  opens, with your founding price. Reply stop to skip it."
- **Privacy, if checkout stops collecting addresses (step 1):** "Your country, and the postal
  code where your card needs it, entered on Stripe's checkout page" in place of "your billing
  address".
