# Beat Your League — Master Plan (0 → Automated)

Owner: solo operator + Claude Code. Budget hard cap: **$100** (plan below uses ≤ $53 through launch).
Calendar anchor: today is **Tue Aug 12, 2026**. NFL kickoff **Thu Sep 10**. Peak draft weekend **Sep 4–7**.
This file is the business plan. `CLAUDE.md` is the engineering spec. When they conflict, fix whichever is wrong.

---

## 1. Thesis & positioning

40M Americans play fantasy football (~7 hrs/week each); 81% of fantasy players also bet on sports.
We sell a weekly **Rival Report**: personalized analysis to beat one named opponent.
Positioning line: **"Beat your league, not the books."** Analysis, never picks. Receipts, never hype.
Emotional core: rivalry, regret-avoidance, group-chat bragging rights.

## 2. Budget

| Item | Cost | Notes |
|---|---|---|
| Claude Pro (Aug + Sep) | $40 | powers Claude Code build + language layer |
| Sleeper API, GitHub, GitHub Actions, GH Pages | $0 | free tiers cover everything |
| Substack (list + payments) | $0 upfront | 10% of revenue; swap to Stripe later if it earns it |
| Domain (optional, can wait) | $12 | skip until 100 emails |
| Capafy listing (optional side bet) | $0.99 | closed-source skill version |
| **Total through launch** | **≤ $53** | leaves buffer inside the $100 cap |

## 3. Build & launch timeline

### Sprint 0 — Core engine (Aug 12–16)
- Day 1: Phase 1 ingestion (Sleeper client, league history pulled, verification summary). Post Day-1 receipt on X.
- Days 2–4: Phase 2 backtest grader + calibration report + rival behavioral profiles from real league history.
- Day 5: Phase 3 renderer — first REAL rival report for my own league from the template.
- Content: publish the backtest thread ("I graded every start/sit call in my league's 2025 season — here's what a
  calibrated engine finds"). This is launch asset #1 and the proof the skeptic demanded.

### Sprint 1 — Audience wedge (Aug 17–23)
- Free **Draft Kit** lead magnet: personalized draft cheat sheet + "how to draft against YOUR league" guide
  (engine-generated from league history). Delivered by email → Substack list is born.
- Substack live (free tier only): landing copy from template screenshots + backtest numbers.
- Daily X cadence begins (formats in §5). Mirror to LinkedIn.
- Beta: my own league + 2–3 friends' leagues get Week 1 reports free, in exchange for testimonial screenshots.

### Sprint 2 — Founding offer (Aug 24–30)
- Open paid tier: **Founding season pass $29** (first 50 only) or **$5.99/month**. Anchor against $100+ league buy-ins.
- Personalized upsell listed: **$19 Rival Deep-Dive** (custom one-off report, fulfilled ~20 min with engine).
- Optional: publish Capafy skill version (Run Online, $4.99/week) — capped side bet, zero extra engine work.

### Sprint 3 — Draft-weekend push (Aug 31–Sep 7)
- Daily draft content peaks; every post ends with the free Draft Kit link.
- Onboarding automation v1: signup form collects Sleeper league ID + rival name → registry the pipeline reads.
- Labor Day weekend (Sep 4–7): highest-volume posting window of the year. Ship the "draft war room" thread live.

### Season operations (Sep 8 → Jan)
Weekly loop (hours shown = after automation matures / before):
- **Tue:** pipeline generates all subscriber reports + drafts week's content → human QA sample → send. (30m / 90m)
- **Wed:** Hype Meter public post (from pipeline draft). (15m)
- **Thu–Sun:** 20 min/day replies on X. Non-negotiable; this is growth.
- **Mon:** auto-grading runs vs box scores → ledger page updates → receipt cards render → post Receipts thread. (30m)

### Automation milestones
- Week 2: GitHub Actions cron replaces manual pipeline runs.
- Week 4: receipt-card image generator + public ledger page fully automatic.
- Week 6: subscriber onboarding fully self-serve (form → registry → next Tuesday's run, no human touch).
- Week 8: content drafting automated end-to-end; human role = edit voice + approve + reply only.

## 4. Offer ladder & monetization rules

**Decision (owner, Aug 13 2026): charge from day one — no public free tier.** The site sells
the founding pass from launch; pre-checkout signups are founding-price *reservations*, never
free access, and reports go only to paid subscribers from the first issue. (The private
beta-for-testimonials leagues in §3 Sprint 1 are a personal arrangement, not a public offer —
cut them too if they conflict with this.) The risk-reversal replacing "free" is the public
ledger + the Week-2 refund promise.

**At checkout, exactly one decision:** Founding Season Pass **$29** (first 50 — honest capacity limit)
shown beside **$9.99/mo** (the anchor that makes the pass obvious). Refunds no-questions through Week 2.

**Prices are USD** (owner decision, Aug 14 2026) — the paying fantasy market is overwhelmingly US
and Substack bills in USD by default. Every price shown to a buyer must carry the currency; an
unlabelled "$29" is ambiguous for buyers and a support burden. Confirm the currency setting in
Substack before launch so the charge matches the page.

**Why $9.99 and not $6.99** (corrected Aug 14 2026): a paid season runs Sep 8 -> late Dec = 111
days ≈ 3.65 months ≈ 16 weekly reports. At $6.99 a full season cost **$25.49 — LESS than the $29
pass** ($1.61 vs $1.83 per report), so the "anchor" made the pass look like the worse buy and
invited exactly the month-to-month churn this pricing exists to prevent. At $9.99 a season runs
$36.43, so the pass visibly saves ~20% and a monthly subscriber who stays all season is worth more
than a pass buyer. Rule to keep: **monthly x 3.65 must always exceed the season pass**, or the
ladder inverts again.
Copy anchors price to the league pot ("your buy-in is $100; the edge is $29"), never to media subscriptions.
Implementation: Substack monthly + annual tiers (annual = season pass). One-offs via Stripe payment links.

**Upsells appear only post-purchase, in-product, in this order:**
1. Week 3 — **Rival Deep-Dive $19** (custom one-off report; ~20 min fulfillment with engine; offered as
   one line inside subscriber reports only).
2. Week 13 — **Playoff Gauntlet $12** (weeks 14–17 intensity package, offered only to alive teams —
   monetizes the elimination churn cliff instead of suffering it).
3. **League Pass $99** — BUILT Aug 2026 (`site/league-pass.html`; `plan:"league_pass"` seats in the
   registry; seat-coverage reporting in `run/batch.py`). Commissioner pays once; every manager who
   signs up gets their own report aimed at their own rival. Deliberately NOT a third card in the
   pricing section — one quiet link instead, so the individual buyer still faces exactly one
   decision. Wire `LEAGUE_PASS_URL` on that page when the Substack tier exists. Arms-dealer
   dynamics make the league itself the marketing channel.
4. Off-season — **NBA fantasy module** (Oct) to bridge revenue between football seasons.
   (The old "Season 2 earlybird renewal (Feb)" is REMOVED: the pass already auto-renews at its
   anniversary, so selling the same person a renewal in February would either double-charge them
   or require cancelling a subscription they already have. Reposition it only as a win-back offer
   to people who actually cancelled.)

### Recurring revenue without charging for months we don't deliver (owner decision, Aug 14 2026)

The goal is continuous billing with no repurchase friction. **The annual auto-renewing season pass
already is that** — bought once, it renews every year until cancelled, and the renewal lands
shortly before the season it covers. That is a season ticket, not a trick, and it collects the
whole season's revenue upfront, ahead of the Week 10-12 elimination cliff.

What we will NOT do is bill monthly through Feb-Aug. There is no product in those months: no
games, no waivers, no rival to scout. Charging there fails four ways at once — it is the
forget-to-cancel revenue this plan already rules out, it invites chargebacks, several states'
auto-renewal statutes expect the service to actually be delivered, and a subscriber looking at a
publication that hasn't posted since December cancels anyway. So **monthly billing stops at season
end automatically**, and both the pricing card and the terms say so.

**The only honest route to 12 months of billing is 12 months of product.** If that is wanted
later, the candidates in rough order of realism:
- **Dynasty/keeper leagues** — genuinely year-round (rookie drafts, offseason trades). The engine
  already reads league history, so this is the most plausible offseason product.
- **Draft Kit / draft-week product** (Aug) — already in Sprint 1, and the highest-demand offseason
  moment of the year.
- **NBA module** (Oct-Apr) — a different sport on the same engine, per item 4 above.
Until one of those ships, the honest model is: charge for the season, renew for the next one, and
make the renewal easy to say yes to by having a public ledger that argues for itself.

**Launch blockers before the site goes public** (each is a one-line edit once the account exists):
a project contact inbox (never a personal address) into `CONTACT_EMAIL` on both funnel pages and
into `legal.html`; the Substack URL into `SUBSTACK_URL`; a form backend into `FORM_ENDPOINT` and
`LEDGER_LIST_ENDPOINT`; and the free-list page into `LEDGER_FREE_URL`. Until the inbox exists the
signup forms honestly say signups aren't open — which is correct, but it also means zero
conversions, so this is the first thing to fix.

### Payment → delivery: how a purchase becomes a Tuesday email (decided Aug 14 2026)

Requirement: someone pays, and reports start arriving and keep arriving every Tuesday for as long
as they are paid up — with no human step anywhere, at near-zero cost.

**Recommended stack: Stripe (billing + entitlement) + Resend (sending).** Both are wired and
tested; both are config, not code, so switching either is a secret change.

| Piece | Choice | Cost at 100 subscribers | Why |
|---|---|---|---|
| Billing | Stripe Checkout/Payment Links | 2.9% + 30¢ | vs Substack's 10%, saves ~$4.60 per $29 pass |
| Entitlement | Stripe Subscriptions API | $0 | answers "is this person paid up right now" natively |
| Sending | Resend | $0 (3,000 emails/mo free) | ~1,700 sends/season for 100 subs fits the free tier |
| Sending at scale | Amazon SES | ~$0.17/season | if the list outgrows the free tier |
| Scheduling | GitHub Actions cron | $0 | already the weekly runner |

**The property that makes this work without date arithmetic on our side:** when a subscriber
cancels, Stripe does *not* delete the subscription — it stays `status:"active"` with
`cancel_at_period_end:true` until the period they paid for actually ends. So "still paying, or paid
for a period we're still inside" is one API query, and the pipeline stops on its own the week their
period lapses. `trialing` counts as entitled; `past_due` deliberately does not (the card bounced
and Stripe is retrying — it flips back to `active` by itself if it clears).

Implementation: `run/subscriptions.py` (`resolve_paid_list()` — Stripe when `STRIPE_API_KEY` is
set, CSV export otherwise) and `run/delivery.py` (dry/resend/postmark/ses/smtp, idempotency-keyed
so a re-run or a double-fired cron cannot mail the same week twice). With no entitlement source
configured the run **refuses and sends nothing** rather than mailing a stale list — a cancelled
person receiving a paid report is the failure that becomes a chargeback.

Substack stays the fallback and the free-list home. If it is used for billing instead, the CSV
export path covers it; the 10% fee is the price of not running the checkout.

New launch blockers from this decision: `STRIPE_API_KEY` (a **restricted** key, read access to
subscriptions + customers only), `EMAIL_PROVIDER` + that provider's key, and `EMAIL_FROM` on a
domain with SPF/DKIM configured — an unauthenticated From address goes to spam, which at this
volume is indistinguishable from not sending at all.

### How a signup reaches the Tuesday run (decided Aug 14 2026)

The question asked: is a published Google Sheet CSV the sustainable long-run answer? **No.**
Recorded here so it is not re-litigated next August:

- **It is a store, not a receiver.** A static GH Pages page cannot write to a Sheet. Getting a row
  in requires either an Apps Script web app open to anonymous writes (a server we run, with none
  of a form vendor's abuse protection) or a form backend that also writes to Sheets — in which
  case the form backend does the work and the Sheet is a middleman. It removes zero manual steps.
- **"Publish to the web" is a public, unauthenticated, cached URL** with no expiry and no access
  log. The rows would carry subscriber emails *and* `rival_owner_id`, which resolves to a third
  party's real display name in one unauthenticated Sleeper call — breaking both the
  no-emails-on-a-public-surface rule and the no-naming-league-members rule. Obscurity is not
  access control.
- **It does nothing about the actual problem**, which was two lists joined by a typed email, and
  nothing at all for League Pass.
- (A *private* Sheet via Sheets API v4 clears the privacy objection but costs a GCP project and a
  service-account key with no natural rotation, to buy a store we do not need.)

**Decision: the payment carries the signup.** The picker sends buyers to a Stripe Payment Link
with their picks in `client_reference_id` and a locked prefilled email, so entitlement and
configuration live in one system — the one that already has to be correct. League Pass seats,
which produce no payment of their own, are the single exception and use one free-tier form
backend. Mechanics and the verified Stripe facts are in CLAUDE.md.

Deferred deliberately, and worth revisiting: `run/sync.py` (sweep Checkout Sessions → materialise
the registry) and the August season auto-roll would take this to zero touches including seats.
Until then seats are an annual hand-export, which is a once-a-year chore rather than a weekly one.
**Revisit a small server (Cloudflare Worker) as a §7 risk item if either trigger fires: League
Pass passes ~5 leagues, or the form backend proves flaky twice.**

New launch blockers from this decision:
- Create the Stripe products/prices and **Payment Links**, then paste them into
  `STRIPE_LINK_SEASON` / `STRIPE_LINK_MONTHLY` and set `CHECKOUT_OPEN = true`.
- Make the **$99 League Pass a recurring annual price, not a one-time charge** — a one-time
  payment creates no Subscription, leaving the Checkout Session (whose retention Stripe does not
  document) as the only record of an entitlement that must survive a season. If it becomes
  recurring it also needs the same renewal disclosure the $29 card carries.
- **`legal.html` still names Substack as the place to cancel.** Whichever platform actually takes
  the money, the cancel instructions must name *that* one. Shipping checkout on Stripe with cancel
  steps pointing at Substack is exactly the ambiguity §4 exists to prevent.
- A restricted `STRIPE_API_KEY` (read: subscriptions, customers, checkout sessions). Create it in
  a sandbox first and confirm the permission labels against the request log rather than guessing.

### Retention & refund policy (owner decision, Aug 14 2026)

Goal: recurring revenue that sticks, with as little refunded as possible. The structure below
reaches that **without** dark patterns, which are ruled out here permanently — not on taste, but
because this product's growth channel is twelve people in a group chat vetting us for each other,
and its entire moat is a public ledger that says *we publish our misses*. A "can't cancel"
screenshot kills both. Cancellation also lives inside Substack, so obstructing it is not even
technically available to us; ROSCA and state auto-renewal laws require clear terms and easy exit;
and chargebacks cost more than a retained month while endangering the payment account.

**Closing the refund-cycling loop (decided Aug 14 2026).** The exposure: buy the pass, take two
weeks of reports, refund inside the no-questions window, re-subscribe later, refund again — a free
season. The honest close is a policy stated *before* purchase, not friction added after it:

> **One no-questions refund per person.** The window runs through Week 2 of your first season
> pass. Re-subscribe after a refund and that purchase is final — you keep every report either way.

Why this is the right shape: it is disclosed pre-purchase (so it is a term, not a trap), it costs
an honest customer nothing, and it removes the only version of the loop worth running. Note the
operator eats the payment-processing fee on every refund — roughly $1–1.50 a cycle — so even
without abuse, refunds are never free; that is a reason to prevent the *causes* of refunds, not to
obstruct the refunds themselves. Enforcement is manual and trivial at this scale: Substack refunds
are issued by the operator, who can see prior refunds against the same email before granting one.
Do not attempt device/IP fingerprinting or any other tracking to detect repeat refunders — it is
disproportionate, hostile, and would collect exactly the data this project promises never to hold.

**Where the non-refundable money legitimately comes from:**
1. **Season pass, paid upfront.** $29 lands on day one. The no-questions window closes at
   Week 2; everything after is earned revenue, not float.
2. **Value must land before that window shuts.** Weeks 1 and 2 reports are the highest-stakes
   deliverables of the season — a missed or thin Week 1 is a refund request with a stamp on it.
3. **Reduce refunds by removing their causes, never their availability:** set expectations about
   gated numbers up front ("when we don't show a number, that's the product working"), frame the
   first miss before it happens (a calibrated 64% call misses 36% of the time — Receipts Monday
   is the mechanism), and make Week 1 land on time.

**Stickiness comes from engagement, not entrapment:** the rivalry (a named nemesis tracked all
season), the ledger streak (a running public record they're part of), Rivalry Week, and the
receipt cards they screenshot into their group chat. A subscriber who forgets they're subscribed
is a chargeback and a bad review waiting to happen; a subscriber who opens Tuesday's email
because they want to beat Mike renews without being asked.

**Renewal disclosure (non-negotiable).** The $29 pass is a Substack **annual tier**, so it
auto-renews — which is fine revenue and NOT fine to leave unsaid. Both decision points (landing
pricing card + picker confirmation) must state "renews once a year at $29 unless you cancel", and
a reminder email must go out **before** it bills. An undisclosed annual auto-renewal is the
forget-to-cancel pattern with better manners, and it is ruled out here. `tests/test_site.py`
enforces the on-page half of this.
*Consequence to keep straight:* an auto-renewing pass cannot also be sold a "Season 2 earlybird
renewal" (§4 upsell 4) — for renewing subscribers that offer becomes a thank-you//loyalty credit,
not a second charge.

**Seasonality rule:** the monthly tier must not silently auto-renew through the Feb–Aug offseason
when no product ships. Cancel or pause monthly subscribers at season end and invite them back for
Season 2 — the alternative is a spring of chargebacks and the exact reputation this plan avoids.

**Rules:** never more than one offer visible to a non-customer; never raise complexity before trust;
Season 1 optimizes for renewals, referrals, and list growth — not maximum extraction. Rationale: monthly-only
revenue collapses at the Week 10–12 elimination cliff; season-pass-led pricing collects value before it.

## 5. Marketing system (detailed)

**Budget rule: paid spend = $0.** No ads, no paid shoutouts, no engagement tools. Cold traffic to an unproven
$29 product incinerates money; CAC here is daily minutes. Every channel below consumes engine output (numbers,
backtest, graded calls) — which is why marketing cannot start before Phases 1–2 exist.

### Channel 1 — X (primary, daily)
- **Setup, once in launch week:** bio + pinned backtest thread. Build a list of 25–30 fantasy accounts:
  2–3 giants (e.g., Matthew Berry, FantasyPros) for reach-surfing, the rest mid-size grinders (5–50K followers)
  because they actually engage back. Turn on notifications for the 10 most active.
- **Data-replies — the core growth mechanic (20 min/day):** 15–20 replies daily to start/sit questions and hot
  takes, each carrying a number plus one line of reasoning ("Engine: Achane 64/36 over Hall — 71% route rate is
  the tiebreaker"). A calibrated number in a sea of vibes-replies is a free product demo. Never link in replies.
- **Posting windows:** Tue morning (waiver panic), Thu evening + Sun morning (lineup dread). Use the three
  formats below.
- **Signature move:** every Monday, quote-tweet Friday's own call with the box score attached — hit or miss.
  Public self-grading is rare enough to be a spectacle; it is also the brand.

### Channel 2 — Reddit (daily, rules-first)
- r/fantasyfootball plus 2–3 smaller subs. Read each sub's rules page first; message mods before ever
  mentioning a tool — one permission ask beats one ban.
- 5–10 genuinely good, data-backed answers per day in the daily start/sit threads. Zero links in posts or
  comments; the product lives in the profile only. Highest purchase-intent channel on this list: it demos the
  product at the exact moment of need.

### Channel 3 — Discords & league group chats (highest conversion)
- Sleeper communities and podcast Discords, same value-first conduct as Reddit.
- Beta leagues (mine + 2–3 friends'): source of testimonial screenshots and the gift-a-rival mechanic. One
  league group chat that adopts receipts culture = twelve warm prospects locked in a room with money on the
  line. Expect most of the founding 50 to come from here.

### Later — only once the ledger has a record
- **Facebook fantasy groups:** large, older, underserved by data content. Weekly repost of the week's
  best-performing post, 15 min/week, optional.
- **Podcast / newsletter pitches (from ~mid-Oct):** "a solo builder's engine went X% on coin-flip calls through
  October" is a bookable story; an August pitch with no track record is not.

**Three recurring public formats (pipeline-drafted, human-edited):**
1. **Receipts Monday** — graded ledger, wins AND misses, receipt cards.
2. **Hype Meter Wednesday** — "the waiver player everyone's chasing: real or mirage," with usage data.
3. **Coin-Flip Friday** — one genuinely hard start/sit, our call, our confidence, our reasoning.

**Launch levers:** backtest thread (proof) · build-in-public numbers (trust) · league-mate testimonials (social
proof) · mischief referral: subscribers can gift their rival a free week — "may the best analyst win." (The gift
is the ad.)

**Proof assets:** public prediction ledger on GH Pages, linked in bio. Every claim traceable.

**Time budget:** ~30–40 min/day in season (replies + one post), consistent with the §3 ops loop. If a day
slips, replies beat posts.

## 6. Metrics & decision gates (pre-committed — no moving these later)

| Date | Gate | If missed |
|---|---|---|
| Sep 1 | 100 emails on list | change lead magnet/content angle, push 1 more week before any pivot talk |
| Sep 20 (Wk 2) | 20 paying subscribers | test price ($3.99) and offer copy; interview 5 non-buyers |
| Oct 11 (Wk 5) | 40 paying subs & churn <15%/mo | keep running lean BUT begin crypto-voices tracker on same engine |
| Jan (season end) | ≥$1K total revenue | if yes: NBA module + season 2 earlybird. If no: engine pivots fully, Feb project begins |

Leading indicators watched weekly: email signups, follower growth, reply-rate on formats, free→paid conversion.
Vanity metrics ignored: impressions, likes.

## 7. Risks & mitigations

- **Bad accuracy stretch** → pre-committed grading rules + publish misses; sell discipline, not clairvoyance.
- **Seasonality** → NBA fantasy module Oct; engine reusable (crypto tracker queued Feb).
- **Platform dependence (X)** → email list is the asset; every post drives to it.
- **Solo burnout** → automation milestones above; if a week slips, subscriber reports ship and content skips.
- **Scope creep** → nothing gets built that isn't in a phase. New ideas go to IDEAS.md, not the sprint.

## 8. Definition of success

By Jan: an automated system producing recurring revenue with ≤3 hrs/week human input, a 1,000+ email list,
a public track record, and an engine + audience reusable for the next product. That is "money online,
autonomously, as an individual" — built, not bought.
