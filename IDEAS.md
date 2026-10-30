# IDEAS.md — parking lot

New feature ideas land here, never in the current sprint (see PLAN.md §7,
scope creep). One line each; promote to a phase only at a sprint boundary.


## Ranked after the Aug 16 2026 market research

Ordered by (customer value) / (build cost + breakage risk), against the stated
objectives: automated, stable, cheap, useful, market-conventional. Nothing here
is in the current sprint.

### Launch-critical, owner only
Moved to `LAUNCH.md` (Sep 29 2026). The inbox, the billing platform (Stripe),
the Stripe products and the GitHub repo are done; what is left is there.

### Highest value next, buildable from data we already have
- ~~**Backtest the shipping availability gate.**~~ **DONE Aug 16 2026 — an
  honest negative, `reports/gate-backtest.md`.** nflverse publishes a historical
  injury archive (CC-BY-4.0, plain CSV, verified: 5,133 rows for 2018 with
  report_status by week and gsis_id; Sleeper carries gsis_id for 100% of
  rostered skill players). Reconstructing the known-active gate over 2017-18 is
  the only way to turn the currently-unpublishable calibration into a real
  claim — or to learn honestly that the gate does not help. This is the single
  biggest evidence gap in the product.
- ~~Usage on the rival's fragile spots, not just waiver targets.~~ **Retired
  with the rival and the waiver market (Aug 18 2026).**
- ~~Tiers as the display unit for slot calls.~~ **STRUCK Aug 16 2026 by our own
  evidence.** The gate backtest measured resolution at a 6.0-point spread across
  the entire stated range, so labelling calls "clear" versus "lean" would assert
  a discrimination we have just shown we do not have. The market convention is
  real; we have not earned it. Revisit only if resolution improves.
- ~~Side-by-side rosters instead of two stacked lineup tables.~~ **Moot: the
  roster product has no opponent to put beside you.**
- ~~FAAB as a percentage of budget.~~ **STRUCK — RULE W1 already voids it.**
  `waiver_budget` is not a trustworthy denominator (two sample managers spent
  140 and 101 against a stated 100), so the market's percentage cannot be
  computed honestly here. The existing phrasing — "it takes 18 and you have 10
  left" — is clearer than a percentage anyway.

### Stability and automation
- Re-run the automation audit properly: one of three agents in the Aug 16 run
  returned placeholder output, so that lens was never actually done.
- Deliverability: SPF and DKIM come with Resend's domain setup (LAUNCH.md
  step 2). DMARC is still worth adding before the first real send, or Tuesday's
  report can land in spam and the failure is invisible.
- A canary: assert the Tuesday run produced N reports for N paid subscribers
  and fail loudly on a mismatch, rather than trusting exit codes.
- Prune `data/raw/stats` and `projections` for seasons nobody reports on, so
  the tracked repo does not grow without bound.

### Market-conventional features worth considering
- A free sample report on the visitor's own roster, self-serve — every direct
  competitor offers a free way in. The manual version exists (`run/trial.py`,
  LAUNCH.md section 6); this would be the automatic one.
- Trade analyser. Frequently requested, and LeagueVision leads with it.
- Weekly recap of what actually happened (Monday), which is the format
  STACKED and Scoutcast both open their week with.
- ~~Power rankings / playoff odds.~~ **Not possible: both need every team in
  the league, and the roster product reads no league.**
- A multi-roster price. One purchase covers one roster, which is where the
  most engaged prospect (three leagues, three teams) buys once and stops.

### Pricing and positioning
- ~~$29 is at the floor of this market.~~ **DONE: the season pass is $39.**
- Reconsider the refund window's LENGTH (now purchase-relative since Sep 29 2026,
  closing when the second weekly file's week kicks off): Footballguys gives 30
  days, Draft Sharks refunds through December.
- ~~Retire "Beat your league, not the books."~~ **DONE: it is on no page.**
- The three landing feature cards share one internal anatomy and all three
  captions open with "Real" — the repetition protests rather than demonstrates,
  and repeated equal-weight cards are the structural tell of AI-generated pages.

### Research still worth doing
- Whether a weekly email is the right form factor at all: the market ships web
  tools plus Discord, and we ship an email. That is a bigger deviation than
  anything in the analysis.
- Whether FantasyPros' third-party accuracy competition can be entered. The
  market's accepted accuracy currency is third-party adjudicated; Draft Sharks
  sells "third-party, data-driven results" against "self-proclaimed titles",
  which is the credibility discount a self-published ledger carries.
- ~~Whether the projections feed should be adopted as a blend.~~ **Out of
  scope: it is Sleeper's feed, and the paid product left Sleeper (Aug 18 2026).**
  An nflverse-licensed projection source would reopen the question.

## Year-round revenue (owner question, Aug 27 2026) — product first, then price

The monthly tier stops at season's end (`run/billing.py`), and the obvious
commercial thought is to bill through the offseason instead. Measured against
the real 2026 calendar: the product delivers **18 weekly files over 119 days —
33% of the year**, and is silent for the other **246 days**. Billing $14.99 ×
12 would be **$179.88 for 18 files**, with 246 days of charging for nothing.
That is the pattern PLAN §4 bans and five surfaces promise against, including
the operative contract, and commercially it converts a returning customer into
a chargeback ($15 plus the amount plus ratio damage) and a public complaint.

**The recurring revenue already exists**: the season pass renews annually at
$39 and the League Pass at $99, and RULE B2 in `run/billing.py` exists
specifically to protect both from the offseason stop. The gap is not recurring
billing, it is offseason PRODUCT.

What the data we already hold could honestly support, in order of cheapness:
- **Season review (Jan–Feb).** `engine/ledger.py` records every published
  call and grades it, and the box scores are cached (the ledger is empty until
  the first subscriber is mailed). "Your season, every call graded,
  the points you left on the bench" is close to free to build and lands exactly
  when a manager is still thinking about it.
- **Draft prep (Jun–Aug).** `engine/preseason.py` already produces it — byes,
  positional ranks under the subscriber's own scoring, slots that cannot be
  filled. It ships today as the purchase-day file; it is a product on its own.
- **Mar–May: nothing honest.** Free agency and the draft are what move value
  then, nflverse carries no news, and there is no free source that does. Do not
  sell those months.

**Reviewed Aug 27 2026 (4 lenses + 2 adversarial challenges, one tasked with building
the strongest case FOR year-round billing).** The case for was built honestly and it
fails, on a point that VALIDATES the owner's own framing rather than dismissing it.
Corrections to the paragraphs above, which were written before the review:

- **"33% of the year" is not by itself the argument.** The $39 pass charges for the same
  246 silent days and nobody calls it deceptive. The defensible ground is UNIT COHERENCE:
  a season is the unit we sell, a month is not a season. That survives a sharp buyer;
  "we only bill for months we deliver" does not, because the pass does not.
- **The decisive point is that nothing is IN FORCE in a charged offseason month.** A gym
  is open, an insurance policy would pay out, a software seat can be logged into — each
  has state in the month it bills. This product has no account, no login, no server (a
  hard constraint), and `site/terms.html` §4 hands over every report already sent, on
  cancellation, forever. So an offseason charge preserves nothing and a cancelling
  subscriber forfeits nothing. The owner's instinct — that an active account is what
  justifies recurring billing — is exactly right, and it is precisely why this fails here.
- **The market split is clean, from our own verified comparison page:** every product sold
  BY THE SEASON charges once per season; every product billed MONTHLY has a continuously
  available account. Nothing in the repo records what any competitor does in the offseason,
  so no claim about that may be published.
- **Do not repeat the card-network argument as stated.** Visa's dispute-monitoring program
  carries an absolute-count condition as well as a ratio, so "one February dispute exceeds
  the threshold" is not a fact we checked. The dispute risk is real; that framing of it is
  not sourced.
- **This section is not independent corroboration.** It was written hours before the
  review, from the same brief, so three of the four lenses citing it back are circular.

So the reachable shape is ~7 months of product, not 12. Sequence: build the
season review, then the draft-prep file as its own artifact, and only then
price a twelve-month tier. Selling the months before they contain something is
the one move that cannot be undone cheaply — it is the review that follows you.


## From the launch-readiness audit (Oct 15 2026)

Confirmed findings that are bigger than a launch fix or belong to the off-season.
The report is `reports/launch-readiness.md`; `make launch-check` holds the rest true.

- **Lineup controls (flex count 1–2, superflex, K yes/no, DEF yes/no) in a v4 ref.**
  Two-FLEX lineups (common on Sleeper) can't be set up today; the FAQ says so. Intake +
  ref + roster.js work, with a cross-language test. Highest-value product gap for Sleeper users.
- **Season roll before Aug 2027.** A pass bought in Oct 2026 runs to Oct 2027, and the
  Tuesday run would build Sep 2027 reports from a 2026 roster. Hold reports for a
  prior-season roster until a post-draft roster is confirmed; one pre-season "paste your new
  roster" email. Only then state the pass's 12-month coverage on the pricing card.
- **A multi-team price.** 23% of players run 3+ leagues; today each team is its own
  subscription (the FAQ says so).
- **Free post-draft roster check (Aug 2027 lead magnet).** The facts-only roster report
  through the trial pipeline (`join/?check=1`, one per address), upselling the pass.
- **"Tell me next August", with consent**, on the season's last report and at cancel —
  the cheapest 2027 revenue there is, held to the waitlist's one-email rule.
- **January stub charges.** About 23% of monthly buyers pay a small January charge after
  their last report. Decide: stop on Jan 10 after the last Saturday check, or disclose it.
- **A weekly share card for this-week.html** (closest call + rising roles as a PNG og:image),
  and a dated archive of past live-sample weeks a skeptic can check against box scores.
- **Retention clean-out.** The privacy policy now promises only what happens (form rows
  expire after ~13 months; the rest is deleted on request). A small `run/prune` over the
  signup log and registry (Stripe-checked) would let it promise deletion a set time after a
  subscription ends, which is the better policy.
- **Drop GitHub's backup schedule for the weekly run** once the Worker dispatch has a few
  weeks of on-time starts. It is the last path to a duplicate first email: a failed on-time
  Tuesday run whose 5–7 h late backup overlaps an hourly intake (CLAUDE.md, final review).
- **A one-click stop for League Pass seats** (LP-I12). Today a leaguemate replies "stop", the
  owner runs `run.suppress`, and up to two more Tuesday reports can arrive within the 10
  business days. Instead: a `kind:"stop"` row on the form Worker carrying a per-seat code
  signed with `UPDATE_SECRET` (the seat token's key), printed in each seat's footer, applied
  by the next hourly intake. No owner in the loop, which is the "cancelling costs the
  operator nothing" rule applied to seats.
- **Re-pin the published sample to a genuinely close call (52–62%)**, chosen by a stated rule
  before outcomes are looked at — the current flagship close call (70%) reads as "start your
  studs" to a savvy buyer. Moves every pinned landing figure, so it's a deliberate decision.
- ~~**Encrypt the registry and plans before caching**~~ — **built Oct 23 2026**
  (`run/statebox.py`): sealed under `CACHE_KEY` before every cache save, opened after every
  restore, with a 90-day encrypted backup artifact the open step falls back to.
- **Move the site to Cloudflare Pages and the repo to private** (AFTER-10, G08). GitHub's
  Pages terms don't fit a site that sells a subscription, and the public repo shows internal
  strategy. The decision and the steps are in LAUNCH §11; `site/_headers` is ready for the
  host. After the move: point canonical links and the sitemap at the pretty URLs Cloudflare
  serves (`/terms`, not `/terms.html`), which today redirect.


## From the pre-launch review (Oct 23 2026)

Confirmed or sharpened by the review, and bigger than its fixes:

- **A typo'd buyer address pays and receives nothing.** The join page sends the address
  straight to Stripe as a locked email, nothing reads it back, and no code reads bounces.
  Show "Reports go to <address> — right?" with common-domain typo suggestions before the
  redirect, and have the next intake check each Resend message id (already in `sent.jsonl`)
  for a bounce or complaint, exit 1 and tell the owner so a refund comes first.
- ~~**A lost dispute keeps the reports coming.**~~ — **built Oct 24 2026**: a lost (or
  accepted) dispute ends entitlement like a full refund (`run/subscriptions.py`), and one
  waiting on our evidence turns the hourly intake red (`run/intake.dispute_alarm`). LAUNCH §8
  has the one dispute procedure.
- **The free report repeats per inbox, not per roster.** One per address per season; a second
  inbox gets the same roster again. Also limit by a keyed digest of the roster (refuse at 80%+
  overlap with one already served, or with a subscriber's).
- **Drop GitHub's hourly backup cron** once the Worker has run a week or two on time — the
  first step of making the repo private (LAUNCH §11): it halves the billed Actions minutes,
  which a private repo on the Free plan would otherwise run out of mid-month.
- **Publish the ledger's own JSONL beside `site/ledger/`** before the repo goes private, so the
  "never edited" record keeps an outside copy anyone can diff.
- **The nflverse cache is saved under a new key every hourly run** (~110 MB each), churning
  the repo's 10 GB cache budget. Save it only when the download changed.
- ~~**Launch-check gates for the owner's hardening**~~ (INFRA-15) — **built Oct 24 2026**:
  `check_hardening` reads the verified Pages domain, DNSSEC, the main ruleset and the live
  HSTS/CSP (OWNER lines; CAA a WARN until the host settles), `CACHE_KEY` is in the secrets
  list, and `site/.well-known/security.txt` exists with `check_security_txt` watching its
  expiry.
- **A sealed copy out of the dispatch token's reach** (INFRA-06 remainder). The Worker's
  `GH_DISPATCH_TOKEN` (Actions: write) can delete the caches AND the backup artifacts. A run
  now goes red rather than rebuild a registry once the send log shows anyone was served
  (RULE S3), but the copy itself is still within that token's reach. A weekly sealed copy
  somewhere else the owner controls would put one beyond it — a new service needs a PLAN §2
  line first.


## From the final review's ops lens (Oct 24 2026)

- **A cron key short a permission should go red within the hour, not on Tuesday.** The cron
  key was made Sep 29 with three permissions and the code now needs six. With the old key the
  hourly intake still registers and welcomes a buyer (its sweep expands only the customer),
  prints one stderr note from the dispute check, and stays green — and the Tuesday send then
  reads no paid list and mails nobody. Make the intake exit 1 when the paid-list read is
  refused with HTTP 403, naming the missing permission. **Built** (final review, Oct 24:
  `dispute_alarm` exits 1 with "STRIPE KEY IS MISSING A PERMISSION").
- **The launch check reads `www` once the host moves.** After section 11's move, a GET on
  `https://www.beatyourleague.com/join/` must answer 301 to the bare domain; served directly,
  every form post from it is refused by the Worker's origin check and the counter is silent.
  LAUNCH A1.4 has the curl; a live gate would keep it true after the next DNS change.
- **The flood limit is one free rule, and the forms took it.** Cloudflare's Free plan allows
  one rate-limiting rule, matched on the path only, and `/rows` uses it. Anything else that
  wants one (a future `/e` cap) needs Pro, which needs a PLAN §2 line first.

## Model ideas that need a preregistered arm first

Each would move a published probability or the projection behind it, so each needs its own
frozen method, run once, before any of it ships (CLAUDE.md, principle 1). None is in a sprint.

- **Lighter or role-aware shrinkage, and an "if he plays" figure** (RQ-11). K=4 shrinkage
  toward the field plus a ~0.9 appearance prior drags hot starters below what platforms
  project: Derrick Henry at 22.4 PPR a game projected 15.2; Nico Collins benched for Javonte
  Williams in a half-PPR superflex report. Arm: shrinkage strength (and a role term) chosen on
  2014–2019, confirmed on 2020–2024; separately, print an "if he plays" figure beside the
  expected value, which is display, not a new probability.
- **Suspension returns and zero-game veterans** (RQ-12). Suspension and not-on-a-team weeks
  count as missed games, so Jordan Addison read "no games this season yet" in his first
  eligible week (WR24 the year before; scored 15.4), then projected 6.9. Arm: excuse those
  weeks in the availability prior, and seed a zero-game veteran from his prior season at the
  anchor's weight.
- **Role changes the report already sees** (RQ-17). Braelon Allen projected 6.3 half-PPR
  while Rising Roles listed him at 22.0 touches a game with Breece Hall out. Arm: recent
  usage share and teammate absences as projection inputs.
- **Evidence against the free projections every buyer already has** (G07). The published
  evaluation leads with Sleeper's free feed beating the old model (68.8% vs 64.4% on 368
  head-to-heads, p = 0.089), and the model has changed since (anchor, context). Arm: the
  shipped model against a free consensus source available for commercial reference, on the
  same 2020–2025 slot decisions. If it loses, preregister a licensed blend. Until then the
  value claim rests on format — the report arriving, decided — not on beating free numbers.


## What managers said

Answers from the five-manager conversations (LAUNCH 7.2), in their words, no names. Three
questions each: would you have set your lineup differently, what would make you pay, how many
teams do you run.

- *(none yet)*

## A/B testing (owner question, Oct 30 2026) — held until traffic exists
- **Cookieless A/B tests, built when the dashboard shows ~1,000 landing views a week.** Below
  that a test reads noise (landing → buy-page click at ~40% needs ~3,000 landing views across
  both arms; landing → paid at ~1% needs ~15,000). Design agreed: the landing picks A/B per page
  load in an inline script before paint (nothing stored, so the privacy page's no-cookies claim
  holds); the arm rides funnel links like `?via=` (one `carryVia`) and the Stripe ref like
  `_via-`; count.js gains one field the Worker re-validates (owner redeploy); the dashboard gets
  an Experiments panel with a two-proportion readout and a "need N more" line. Rules written
  before a test starts: one hypothesis, one primary metric, a fixed sample size, no peeking,
  one test at a time; both arms pass every site copy test. Test order: hero headline/CTA, phone
  story vs static report shot, the roster-paste step's explanation, free report on/off. Never
  test price (fairness, refunds, law) — change it for everyone between seasons instead.
