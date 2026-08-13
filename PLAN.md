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
shown beside **$6.99/mo** (the anchor that makes the pass obvious). Refunds no-questions through Week 2.
Copy anchors price to the league pot ("your buy-in is $100; the edge is $29"), never to media subscriptions.
Implementation: Substack monthly + annual tiers (annual = season pass). One-offs via Stripe payment links.

**Upsells appear only post-purchase, in-product, in this order:**
1. Week 3 — **Rival Deep-Dive $19** (custom one-off report; ~20 min fulfillment with engine; offered as
   one line inside subscriber reports only).
2. Week 13 — **Playoff Gauntlet $12** (weeks 14–17 intensity package, offered only to alive teams —
   monetizes the elimination churn cliff instead of suffering it).
3. If traction — **League Pass $99** (commissioner buys; every team gets its own rival report; arms-dealer
   dynamics make the league itself the marketing channel).
4. Off-season — **Season 2 earlybird renewal** (Feb, higher price justified by the public ledger) +
   **NBA fantasy module** (Oct) to bridge revenue between football seasons.

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
