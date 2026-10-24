# LAUNCH.md — opening mid-season

Every owner action left before a stranger's payment becomes a Tuesday email, in order, with
the exact strings. The code is done and tested; nothing here is engineering. Updated Oct 16
2026, in Week 6 of 18.

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
1. **Step 5, the form Worker.** First: it needs nothing else.
2. **Steps 1–3:** fresh payment links, Resend, GitHub secrets. Under an hour, one sitting.
3. **I put the new links on the join page.** Only once the Worker URL is in: the launch check
   FAILs a checkout opened without it, because then every roster change is a reply you apply
   by hand.
4. **Step 4:** your own purchase, watched end to end.
5. **Opening morning (step 6):** everyone can buy, and the waitlist gets its one email.

Aim for the Week 7 Tuesday (Oct 20). Each closed week costs about an eighth of what's left of
2026 (`.venv/bin/python -m run.economics` shows the arithmetic).

Done:
- `beatyourleague.com` on GitHub Pages (see the hosting decision, section 10);
  `hello@beatyourleague.com` forwards to your inbox.
- Terms (Ontario law) and privacy pages.
- Three Stripe products: $39 season pass, $14.99 monthly, $99 League Pass.
- The Stripe customer portal is on; its login link is in the terms and in every report.
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

---

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
   | Collect customer addresses | On | Tax thresholds count per country and state; the address stays in Stripe |
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
   these print on receipts, so they decide whether you stay anonymous.

   **Settings → Billing → Customer portal:** **Cancel subscriptions** allowed, **Cancellation
   mode: At end of billing period**, proration **none**, **Cancellation reason: Off** (the
   thanks page promises we don't ask why), and no retention coupon. `make launch-check` reads
   these back once `STRIPE_API_KEY` can read the portal settings.

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
4. **DMARC (5 min):** Cloudflare → **Email → DMARC Management** → enable, or a TXT record
   `_dmarc` = `v=DMARC1; p=none; rua=mailto:hello@beatyourleague.com`. After a few clean
   weeks, `p=quarantine`.
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

**Also (1 min, important):** Settings → Actions → General → **Fork pull request workflows
from outside collaborators** → **Require approval for all outside collaborators**. The repo
is public; without this a stranger's pull request could read the automation's cache, which
holds subscribers' emails and rosters.

`github-actions-crons` needs exactly: Checkout Sessions **Read**, Payment Intents **Read**
and Charges **Read** (a one-time pass is entitled while its payment isn't refunded),
Disputes **Read** (a lost chargeback ends a purchase like a refund; without it a disputed
payment shows as "status unknown" and the run goes red until you look), Customers **Write**,
Subscriptions **Write**, everything else None. Subscriptions must be Write: `run/billing.py`
ends each monthly subscription when its final paid period ends (the month the season's last
weekly report falls in).

Keys go only into these boxes — never into chat, a note or a file.

**Tell me when all ten are in.** With step 5's Worker live too, I put the new links on the
join page and switch the pricing buttons on; it's live on the next push.

## 4. The proving run (~1 hour)

Nobody else's money moves until you've watched your own go all the way through.

1. **Between a Tuesday morning and that week's first kickoff** (table in section 8), buy the
   **$39 season pass** at https://beatyourleague.com/join/ with your own email, a real card
   and your real roster.
2. **Actions → daily-intake → Run workflow**, or wait up to an hour. It should go green.
3. **Two emails:**
   - **The welcome:** $39, renews yearly at $39, refunds until your second weekly report's
     week kicks off, and a cancel link that opens your Stripe billing page.
   - **Your first report:** this week's, because you bought before kickoff.
   - Open both in Gmail (phone in dark mode, and web), Apple Mail and Outlook if you have
     them. Look for a header that lost its navy, vanished tick boxes, a cluttered preview
     line, or "View entire message". Tell me what you see.
4. **Tell me both arrived.** I turn on `CHECKOUT_CAN_COMPLETE` (step 6).
5. **Next Tuesday:** the new week's report by about 8:30am ET, weekly-report green in Actions.
6. **The monthly billing page, in test mode (15 min).** Your purchase is a season pass, which
   never shows the monthly path. In Stripe **test** mode: buy the monthly link with a test
   card (4242 4242 4242 4242), then open the test billing page. It must show **Cancel plan**
   — not "Cancels on…" and Reactivate. Then, with the test key in your shell,
   `.venv/bin/python -m run.billing --today 2026-12-20` (dry): it lists the subscription as
   in its final paid period only when that period ends after Jan 5, 2027 12:17 UTC. Press
   Cancel on the test page and confirm "no further charges".

Then decide about your subscription (section 10). A refund doesn't return Stripe's fee: about
$2.72 on a $39 pass from a Canadian account, or about $1.94 with a USD payout account.

## 5. The form Worker (~20 min) — do this first

It needs nothing from steps 1–4. One Cloudflare Worker (in the same account as the domain)
switches on:
- **The email list** on the homepage and join page. Until then the form opens the visitor's
  own email app, and does nothing on a computer without one.
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
2. **Talk to five managers this week.** Before anyone pays, find out whether they would. Ask
   five managers you already know (your leagues, a Discord you're in) for their roster, and
   send each this week's report on it, free:
   ```bash
   pbpaste | .venv/bin/python -m run.trial --email them@example.com --roster - --print
   ```
   Nothing is emailed from your Mac: it prints a text version to paste back. Add
   `--scoring half_ppr`, `--template sf` or `--size 10` to match their league; a name it
   can't place stops and names the line (ask, don't guess). Ask each: *Would you have set your
   lineup differently? What would make you pay? How many teams do you run?* Put their words
   (no names) under "What managers said" in IDEAS.md.
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

**A roster change sent by email** (until the Worker is live, or a subscriber who'd rather
reply): put the names they sent in a file, one per line, then
```bash
make roster-update EMAIL=fan@example.com ROSTER=names.txt
```
It needs `UPDATE_SECRET`, `FORM_ENDPOINT` and `FORM_API_KEY` in the shell (the Worker takes
a post from outside the site only with the read key). `ARGS=--dry-run` resolves the names and
posts nothing. The next hourly intake applies it.

**When someone asks to stop** (mail to hello@ saying stop or unsubscribe; a League Pass
seat's unsubscribe button arrives with the subject "stop"):
- If they **pay**, reply with the billing-page link — stopping a payer's emails while
  billing continues is the one wrong answer.
- Otherwise run this (with `LOG_SECRET` in your shell — the list holds keyed codes), then
  commit and push within 10 business days:
  ```bash
  .venv/bin/python -m run.suppress their@example.com
  ```
  Someone who signs up again: `.venv/bin/python -m run.suppress --remove their@example.com`.

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

**Two subscriptions on one address, and they can't see the older one.** Stripe's billing
page opens only the NEWEST customer for an email, so someone with two teams, or a season pass
then a League Pass, can't reach the first one there. When they reply: Customers → search the
email → the older subscription → **Cancel subscription → At period end**, and tell them it's
done. Same day; never ask them to do it themselves.

**A privacy request** (to hello@: what do you have, correct it, export it, delete it). Answer
within 30 days:
1. `make privacy-code EMAIL=their@example.com` on your Mac (needs `LOG_SECRET`). It prints a
   12-character code. Never put the address itself into GitHub.
2. Actions → **privacy-request** → Run workflow → action **show**, **export** or **delete**,
   and the code. The result lands in hello@, never in the log. A **correction** to a roster is
   `make roster-update`; to an email address, cancel and re-buy, or ask me.
3. For **delete**: the email lists what's left by hand — the Stripe customer (cancel any live
   subscription first, then delete the customer), form rows the Worker couldn't delete, and the
   hello@ threads. Run **show** the next day: every count should be 0. Reply to them saying
   what was done.

**Changing the terms or the privacy policy.** Publish the new page with a new date (and the
new `TERMS_VERSION` / `TERMS_HISTORY` entry, which I add), then before the date it takes
effect: Actions → **change-notice** → page, effective date, a one-or-two-sentence summary of
what changes; run it once unticked (dry), then ticked. Everyone entitled today gets one email.

**How's demand?** Pull, then `make stats`: counts only (waitlist, free-report requests,
roster updates, seat claims, sends by week, paid signups by `?via=` tag), never an address.
It needs `FORM_ENDPOINT` and `FORM_API_KEY` for the form rows and, for payments, a separate
restricted key in `STRIPE_API_KEY` with **Read** on Subscriptions, Checkout Sessions, Charges
and Refunds (the cron key can't read refunds).

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
3. **Issue it:** their subscription → **Cancel subscription → Immediately**, then refund
   **every paid invoice on that subscription** in full (a monthly buyer can have paid twice
   inside the window). The reports stop by themselves.

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

**Reset the targets to a proof season** (PLAN §6, §8). The Oct 11 gates and "~100 paying
subscribers by January" were written for a September launch. *Recommend:* stop feature work
except launch blockers and defects a paying customer would hit, and adopt PLAN §6's proposed
proof-season gates — by Nov 10, at least 30 free reports sent and at least 10 paid; by Dec 22
(Week 16), about 30 purchases plus 2 League Passes and the first graded rows on the public
record. Under 5 paid from 30 free reports on Nov 10 means stop selling hours and spend the
rest of the season on the 2027 work below.

**A USD payout account.** Stripe converts every US-dollar sale to Canadian dollars at 2%:
$0.78 of each $39 pass, and it keeps that on a refund. *Recommend:* add a USD bank account in
Stripe → Settings → Payouts before the first sale (check your bank's fees for it). Then
`STRIPE_PAYOUT_CURRENCY=usd` in your shell clears the launch-check line.

**Hosting, and the public repo.** GitHub's terms say Pages isn't for running an online
business or a site mainly for commercial transactions, and this site exists to sell a
subscription. The repo is public too, so the selling strategy in CLAUDE.md, the status in
PLAN and this file are one search from the brand name. *Recommend:* make the repo private and
serve `site/` from Cloudflare Pages (free plan; the domain is already on Cloudflare). What it
costs: a private repo gets 2,000 free Actions minutes a month, and the hourly intake alone is
about 720 runs (twice that while GitHub's backup cron fires too), so drop GitHub's hourly
backup once the Worker has a few on-time weeks, then check Settings → Billing after the first
month — paid minutes need a PLAN §2 line. Steps, when you say go: Cloudflare → Workers &
Pages → Create → Pages → connect the repo, no build command, output `site`, build watch path
`site/*` (so the crons' hourly commits don't rebuild it — the free plan allows 500 builds a
month); add `beatyourleague.com` as its custom domain; then I retire `pages.yml` and you
switch GitHub Pages off and the repo to private.

**A list you own.** Every lead today gets one email, ever, so nobody from 2026 can be reached
in August 2027. *Recommend:* one unticked box — "Email me when the 2027 season opens" — on the
free-report form, the waitlist, the last report and your cancel replies, stored as its own
form row and held to the waitlist's one-email rule. Build it before the last report (Jan 5).

**The renewal date, and next season's roster.** A pass renews on its purchase anniversary, so
an October buyer renews mid-season 2027 still holding a 2026 roster (rosters don't roll to a
new season yet). *Recommend:* nobody has paid yet, so anchor every pass to one late-August
renewal date before the first sale (the notice lands in July), stated on the card and in the
terms; and build the roster roll — hold reports until a post-draft roster is confirmed —
before July 2027 either way.

**A price for a second team.** Each team is its own subscription today, so a manager with
three leagues stops at one. *Recommend:* not before the first ten buyers; then a "+$19 per
extra team, same renewal date" add-on on one checkout (one payment, several rosters). The FAQ
already says each team is its own subscription, which stays true until then.

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

**Counting visits.** No analytics, by promise, so visits → free report → paid can't be
measured, only the end of the funnel. *Recommend:* once on Cloudflare, use its own traffic
counts for the domain (no script on the page, no cookie) and reword privacy §3 to say exactly
that; otherwise drop any target based on visits.

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

**Keep your own subscription.** The public record holds **no rows yet**: the live sample's
recording landed after Week 6's last pre-kickoff build, and the Oct 16 rebuild was forced
after kickoff, which records nothing. The Week 7 Tuesday build (Oct 20) is the first that can
record its odds; after it runs, check that `data/processed/ledger/typed-ppr-12-2026` was
committed. *Recommend:* keep your step-4 subscription anyway — it adds a real roster's calls
to the record, graded every Monday.

**A sender postal address.** US (CAN-SPAM) and Canadian (CASL) law both want one in
commercial email; every email now prints it, and the launch announcement refuses to send
without it. *Recommend:* rent a virtual mailbox or PO box before step 3, never a home address,
and book one Ontario-lawyer question on online-sale disclosures before scale (not legal
advice).
