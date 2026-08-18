# Beat Your League — Master Plan (0 → Automated)

Owner: solo operator + Claude Code. Budget hard cap: **$100** (plan below uses ≤ $68 through launch).
Calendar anchor: today is **Mon Aug 17, 2026**. Launch **Tue Sep 8**. NFL kickoff **Thu Sep 10**.
Peak *draft* weekend **Aug 29–Sep 7** — note this is BEFORE launch; see §3.
This file is the business plan. `CLAUDE.md` is the engineering spec. When they conflict, fix whichever is wrong.

**Revised Aug 17 2026** after a 27-agent market study (five research lenses, three rival strategies,
nine independent judges). What changed: positioning, price, a free door, the channel order, the
decision gates, and the definition of success. What did not change: the honesty rules, the
retention/refund policy, and the Stripe+Resend stack. Evidence and its limits are in §9.

---

## 0. THE BLOCKER THAT OUTRANKS EVERY DECISION BELOW

**SLEEPER_LICENCE_STATUS: not-required**

*(Machine-read by `test_checkout_cannot_open_while_the_sleeper_question_is_unresolved`. Legal
values: `unresolved` · `granted` · `refused` · `proceeding-with-disclosure` · `not-required`.
Checkout cannot open while this says `unresolved`. Set to **not-required** on Aug 18 2026: the
owner chose to remove the dependency rather than ask for permission, so there is no licence to
resolve. This value is only honest once the paid pipeline genuinely stops reading Sleeper — which
is why `test_no_sleeper_in_the_paid_path` exists and must pass before checkout opens.)*

**Sleeper's Terms of Use forbid what this product does, and no architecture routes around it.**

The docs page is the mild document and it is NOT the binding one. `sleeper.com/terms` redirects to
Sleeper's General Terms of Use (Blitz Studios, Inc., **Last Updated July 24 2026** — three weeks
before this was written). Fetched raw and exact-string matched on Aug 18 2026, because a summarised
fetch of a 145,000-character document silently dropped every clause below. **Verbatim:**

> **§11.1** "Crawl or scrape the Services in any way, shape, or form, for any purpose whatsoever,
> without the express written consent of Sleeper"
>
> **§11.1** "Access, query, extract, or receive any data or content from the Services through any
> automated means, bot, script, spider, robot, and/or other technology, or through manual means
> performed at a scale, frequency, or systematic pattern inconsistent with ordinary individual
> human use, without the express written consent of Sleeper"
>
> **§11.1** "**Use, enroll in, or connect your account to any third-party product**, application,
> platform, or service that accesses, syncs, retrieves, aggregates, stores, or displays data from
> the Services, **including but not limited to league, roster, transaction, scoring**, and/or other
> account data, **for that third-party's commercial or business purposes**, without the express
> written consent of Sleeper"
>
> **§11.2** "…we may, in addition to any other remedy available to us, **immediately suspend or
> terminate your account**, revoke any active sessions or authentication credentials associated
> with your account, and/or take technical measures to block or restrict access by that
> third-party, whether or not that third-party is itself a user of the Services."
>
> **§11.3** "**No third-party is authorized** to access, use, scrape, crawl, query, or retrieve any
> data or content from the Services, **whether directly, through automated means, or through any
> account, credential, or authentication mechanism belonging to a user**, except pursuant to a
> separate written agreement executed by Sleeper… **A user's provision of credentials, tokens, or
> authorization to a third-party does not constitute authorization from Sleeper**, and Sleeper's
> authorization must be obtained independently and directly from Sleeper."

**Two consequences that were not priced.**

**§11.3 forecloses every workaround in advance.** "Is there a way to do this independent of
Sleeper?" was researched properly (13 agents, four lenses, adversarial verification) and the answer
is **no**. Moving the fetch into the subscriber's browser, a CLI they install, an extension, a
BYO-data POST, or a repo they fork in their own GitHub Actions — §11.3 reaches the operator
directly, covers retrieval "through any account… belonging to a user," and says the user's consent
is not Sleeper's consent. Every one of those designs costs 40–200+ founder hours, most of them
delete the Tuesday email (a closed browser cannot mail anyone), and **none of them changes the
sentence that applies to us.** The full option table is in the workflow output; the short version
is that the cheapest workaround is forty times the cost of the email and does not work.

**The remedy lands on the CUSTOMER first.** §11.1's third-party bullet binds the subscriber and
§11.2's first remedy is terminating *their* account — the account their league and its history live
in — mid-season, because they bought our product. Note the verb is "**Use**": our credential-free,
league-ID-only design does not escape it, since no account connection is required for that bullet
to bite.

**That is what makes this un-ignorable for THIS business.** A product that publishes its own
failing calibration buckets cannot decline to mention that buying it puts the buyer's Sleeper
account in scope for termination. So there are two doors: don't disclose it — the exact failure
mode CLAUDE.md's principles exist to prevent — or disclose it, and have just written the worst
sentence on the sales page. **The email is not a compliance chore; it is the only thing that
deletes that sentence.**

**What everyone else does is not permission.** No Sleeper tool found claims partner status, Sleeper
publishes no partner list, and there is no public record of any tool being blocked or sued. That is
*unenforced so far*, observed three weeks after Sleeper rewrote these very clauses, and a quiet IP
block or private email leaves no public trace. It is also weaker cover for us than for an anonymous
scraper: we hold a Sleeper account and accepted these Terms, so the never-assented defence is
unavailable.

### THE DECISION (owner, Aug 18 2026): NO EMAIL. THE PRODUCT LEAVES SLEEPER.

Asked whether the business could stand without Sleeper's permission, the owner's answer was to
build the version that needs nobody's — no licence request, no gatekeeper, no waiting on a reply
that may never come. **That is buildable, and this section is now the plan for it rather than a
plan to ask.**

What that costs and what it does not is set out below. The one thing it is NOT is a workaround:
we do not keep reading Sleeper and hope, we stop reading Sleeper. Every design that kept the data
and dodged the terms was researched and fails §11.3, and all of them leave the *subscriber's*
account exposed under §11.2 to a risk they were never told about. A product that publishes its own
failing calibration buckets does not ship that.

**The paid product is rebuilt on data licensed for commercial use.**

| Half of the product | Source | Licence | Status |
|---|---|---|---|
| NFL-wide: weekly stats, targets, air yards, schedule/byes, injuries, player table | **nflverse** | **CC-BY-4.0 — commercial use permitted with attribution** | **BUILT** (`ingest/nflverse.py`, `ingest/injuries.py`) |
| League-specific: your roster, scoring, opponent | **the subscriber tells us** | theirs to give | to build (§3) |

**The league half is not replaceable by any feed.** Sleeper's own support docs confirm there is no
export, no CSV, no digest — "the only way to get any data is to use our public API." No vendor
sells another company's private league data. So the league context comes from the only party
entitled to hand it over: **the subscriber, typing it.** They tell us their scoring format, their
roster slots, and their players. We never touch Sleeper, from our servers or their browser.

**Precedent that this is a shippable shape, not a consolation prize:** Scoutcast ($49.99/season)
already asks its users to supply their opponent's lineup by hand, and sells the result as "H2H
opponent edge". Manual league context is a normal thing to ask a fantasy manager for.

### What survives, what dies, and what gets better

**Survives intact** — everything the differentiator actually rests on: the projection model, the
calibration machinery, the backtest, the **receipts ledger**, the Tape (your starters against the
opponent's, from typed rosters), start/sit calls with gated confidence, counted usage, the if/then
pivot plan, Stripe, delivery, the whole renderer.

**Dies:** the FAAB waiver market (priced from the league's own transaction log — that log is
Sleeper's), the rival's behavioural profile (built from league history), the automatic
zero-touch signup that read the league for you, and the live scouting demo in `join/`.

**Gets better, genuinely:** the receipts ledger. Calls are no longer scattered across private
leagues — they are league-agnostic player calls, so **one public ledger grades every call we make,
and a stranger can check it.** That is the inclusion handle §1 says the whole discovery strategy
depends on, and it was previously fragmented across leagues nobody outside can see.

### Actions
1. **BUILT: `ingest/nflverse.py`** — weekly counted usage, schedule byes, cached, outage-tolerant,
   with `ATTRIBUTION` as a shipped licence term (RULE N1) and first-party outputs only (RULE N2:
   no PFR snap counts, no CC-BY-SA FTN charting). 12 tests, three mutations checked.
2. **Next: the roster intake.** Replace the Sleeper picker with a paste-your-roster flow — scoring
   format, roster slots, 15 player names matched to GSIS ids. This is the piece the product now
   stands on, and its friction is the main product risk (see §6).
3. **Then: cut the Sleeper path out of the paid pipeline.** `ingest/pull.py`, `run/sync.py`'s
   verification, `site/join/`'s live calls. Keep the Sleeper code paths only for the historical
   backtest, which is research on a public sample league, not a commercial service.
4. **`site/legal.html`:** the Sleeper-dependency clause becomes an nflverse attribution + a
   data-source note. The subscriber-account risk disappears with the dependency.
5. **Two minutes still worth spending:** diff §11 on web.archive.org against a pre-July-2026
   capture. Not to decide anything now — to know whether Sleeper wrote those clauses *at* this
   product category, which tells you what the rest of the market is walking into.

**The strongest argument against this decision, recorded honestly:** typing a roster is real
friction against competitors who sync in one tap, and the FAAB market was a genuinely uncopyable
edge that no rankings site has. This trades a differentiator and some conversion for independence
from a gatekeeper who can say no at any time. That is a legitimate trade, and it is the owner's to
make — but §6's gates should now watch intake completion rate as the first thing that can kill it.

**Not legal advice — I am not a lawyer and neither is the owner.** What the documents *say* is not
in dispute (three independent primary-source fetches, exact-string matched). What they *mean* and
whether they are enforceable is a one-hour conversation with a real lawyer, and the four narrow
questions worth asking are: whether §11.3 reaches `api.sleeper.app` (a hostname not named in the
"Services" definition — the one textual argument in our favour, and a weak one); whether holding a
Sleeper account weakens us versus an anonymous scraper; what disclosure is owed to subscribers
about §11.2; and §14's arbitration and class-action waiver. **Do not be reassured by anyone citing
*hiQ v. LinkedIn*** — the CFAA is not the live question here, and hiQ still LOST on contract, with
a stipulated $500,000 judgment and a permanent injunction.

## 1. Thesis & positioning

**The call: SLIGHTLY DIFFERENT.** Converge on everything used to *place* the product — the
category noun, the table-stakes vocabulary, the price band — and diverge on exactly **one**
pasteable clause. Not "different": three of four assumed differentiators are already occupied, two
of them by free products (§9). Not a "blend": a compound identity is unpasteable, and the unit of
inclusion in a roundup or an AI answer is one sentence a stranger can copy.

**The split that makes it work — never swap these:**
- **To buyers, sell the file arriving.** It shows up Tuesday, about the specific human you're
  playing, with your league's own numbers. Delivery and specificity.
- **To editors, directories and answer engines, sell the published test.** That is the inclusion
  handle — the thing pasted into a list. It is also the only differentiator that survived
  verification, because no competitor has a commercial incentive to publish a weak number.

**The one sentence — used verbatim and identically everywhere** (meta description, JSON-LD, every
pitch email, README, directory submission). Identical phrasing across independent domains is the
co-occurrence signal that forms an entity; varying it destroys the only mechanism available:

> Beat Your League is a weekly start/sit and waiver tool for Sleeper leagues: every Tuesday it
> emails one decided file — your nine starters against your opponent's nine, what a waiver claim
> actually costs in your league, and the week's coin-flip call — and it publishes its own accuracy
> test, including the buckets it failed.

Directory listing name: **Beat Your League — weekly Sleeper league report**. File under the
conventional category (*fantasy football tools / league-sync tools*).

**On the "AI" label — decided, not open.** Accept it on third-party surfaces (roundups, directory
listings, meta description); the highest-value listicle in the vertical is titled "Fantasy Football
AI Tools" and already includes an indie. Refusing the taxonomy word costs inclusion in the exact
pages engines quote, for zero benefit. **The label goes outward, never inward** — buyer surfaces
(landing, report, emails, join) stay AI-free, which is a genuine wedge against LeagueVision's
messaging. `_DEV_SPEAK` keeps enforcing that; this is not a licence to loosen it.

Kept: **"Beat your league, not the books."** Analysis, never picks. Receipts, never hype.
Rivalry stays in the *name*, the subject line and the Rival Watch strip — and comes **out of the
value argument**, because H2H/rivalry data is free at Sleeper native, ffwrapped and My Fantasy
Analyzer. It is flavour, not the reason to pay.

## 2. Budget

| Item | Cost | Notes |
|---|---|---|
| Claude Pro (Aug + Sep) | $40 | powers Claude Code build + language layer |
| Sleeper API, GitHub, GitHub Actions, GH Pages | $0 | free tiers — see §0 on the licence |
| Domain + DNS | $15 | **no longer optional**: SPF/DKIM on a real domain is what keeps the send out of spam, and DNS propagation is wall-clock time. Buy it day one |
| Stripe | 2.9% + 30¢ per charge | no fixed cost |
| Resend | $0 | free tier: 3,000/month **but 100/day, 1 domain** |
| Resend Pro | $20/mo | **trigger: when subscribers + trials exceed 90.** A Tuesday batch fires everything at once, so the 100/day ceiling binds on launch morning, not at 3,000 |
| Capafy listing (optional side bet) | $0.99 | closed-source skill version |
| **Total through launch** | **≤ $68** | leaves buffer inside the $100 cap |

## 3. Build & launch timeline

Sprints 0–3 as originally written are **superseded**. Phases 1–6 of the engineering spec are all
built (417 tests); what remains is not engineering. The 22 days to Sep 8 hold roughly **56 hours**
of work, sequenced so the riskiest assumption is tested first.

**The sequencing principle, adopted from every judge independently: SELL BEFORE YOU BUILD.**
Everything previously planned was build-then-hope, in a strategy whose research could not read a
single customer's words. Three closed League Passes is $297 and the first real demand evidence this
business has ever had; zero closes after five honest attempts tells you the bundle isn't wanted at
any price — *before* thirty hours go into pages.

### A. Unblock (11h) — nothing else can ship until these land
| # | Task | Size |
|---|---|---|
| 1 | **Email Sleeper about commercial licensing** (§0) | S (1h) |
| 2 | Sample your own leagues: what % actually use FAAB, and how many settled weeks the waiver section can carry — before writing a word of copy about it | S (0.5h) |
| 3 | Project inbox live; fill `CONTACT_EMAIL` (empty on both funnel pages) and the `legal.html` jurisdiction placeholders | S (1h) |
| 4 | Domain + `site/CNAME` + DNS + SPF/DKIM. **Start day one** — propagation is wall-clock | M (3h) |
| 5 | Real league ID + roster ID; one full `make week` against the real league. Nothing has ever run against it | M (3h) |
| 6 | Stripe: three payment links, `STRIPE_PAYMENT_LINKS`, `CHECKOUT_OPEN`. One live purchase end to end (picker → `client_reference_id` → sweep → verify → registry → batch → send-to-self), then refund | M (4h) |
| 7 | **Send rehearsal — non-negotiable.** `EMAIL_PROVIDER=resend`, real send to self, opened in Gmail + Outlook + Apple Mail, then a full dry batch | M (5h) |

Item 7 does not get cut. This repo's own history is a cron gated on a gitignored path that could
never have mailed anybody, and a dry run that logged sends and would have skipped every real
recipient. The failure mode is a green run with empty inboxes, invisible until Tuesday.

### B. Sell (6.5h) — late August, before another line of code
| # | Task | Size |
|---|---|---|
| 8 | Reword `site/league-pass.html`: **any manager** can buy the pass, not just the commissioner | S (0.5h) |
| 9 | **Take the existing sample report to 5+ real leagues and try to close $99 League Passes and $39 season passes** | M (6h) |

**Pull this into Aug 23–Sep 3, not launch week.** That is when drafts run, leaguemates are engaged
and wallets are open. Sep 8 is *after* peak intent — a real cost of the launch date that no amount
of site work fixes. If three leagues say yes at $99 without hesitating, $39 is too low.

### C. Then, in this order (32h)
| # | Task | Size | Note |
|---|---|---|---|
| 10 | **Free first week — manual runbook** | S (2.5h) | Collect email + username, render, send from the project inbox. No `FORM_ENDPOINT`, no registry schema change, no new entitlement route, no tests rewritten. ~45 min/week at ≤50 trials |
| 11 | Prior-season fallback in `build_waiver_market` + tests | M (4h) | `engine/waivers.py` reads only the current season's settled weeks, so Week 1 renders "no settled waiver weeks yet". `load_season_chain()` already exists — this is wiring |
| 12 | Price change to $39 + tests + legal renewal disclosure | S (2h) | |
| 13 | Positioning rewrite across `index` / `join` / `league-pass` | M (6h) | Entity sentence, delivery lead, omissions block, Regret Score demoted, rivalry out of the value argument |
| 14 | Publish `projections-eval.md` + `gate-backtest.md` via `render/backtest_site.py` | M (5h) | Includes translating operator register into buyer-neutral language **and adding both pages to the parametrized `_DEV_SPEAK` / no-betting / no-personal-contact sweeps** — new pages under `site/` escape those guards by default |
| 15 | `site/compare/` — one honest comparison page | M (7h) | Real prices for ten products, free ones included, our own weaknesses in the table, founder authorship disclosed in line one, dated "prices checked" stamp |
| 16 | Third-party mention campaign: 12–15 pitches | M (4h) | §5 |
| 17 | `sitemap.xml`, `robots.txt`, JSON-LD Product/Offer/FAQ, canonical | S (1.5h) | Hygiene, not a lever |

**~56h against ~60h available.** If real capacity is 45h, cut in this order: trim `compare/` to a
table-only page (−3h), scope the waiver fallback to the season only (−4h), hygiene to 1h (−0.5h),
pitches to 8 (−2h). Blocking, selling, the free week and the positioning rewrite survive at every
level.

### Season operations (Sep 8 → Jan)
Weekly loop (hours shown = after automation matures / before):
- **Tue:** pipeline generates all subscriber reports + drafts week's content → human QA sample → send. (30m / 90m)
- **Wed:** Hype Meter public post (from pipeline draft). (15m)
- **Thu–Sun:** 20 min/day replies on X. Non-negotiable; this is growth.
- **Mon:** auto-grading runs vs box scores → ledger page updates → receipt cards render → post Receipts thread. (30m)

### In-season additions (revised Aug 17 2026)
| When | Task | Size |
|---|---|---|
| Sep 8–15 | **Stand up the public content feed.** `run/content.py` already drafts Receipts Monday, Hype Wednesday and Coin-Flip Friday from graded data at zero marginal cost, and none of it is published. Free Substack (for its internal recommendation network), mirrored to `site/` for crawlability | M (3h setup, then ~30 min/week) |
| Week 3–4 | **Sunday "Final Call" send** — a short 10am email printing only what *changed* since Tuesday, plus the now-live if/then branches | M (8h) |
| Sep 15 → | Discord participation, 2h/week. Reddit **only after** personally reading Rule 1 and the self-promo rule | recurring |
| October | Automate the trial (`plan:"trial"`, one-send entitlement route, paywall follow-up) — **only if manual conversion clears the §6 bar** | M (8h) |
| October | **Promote the receipts back into the funnel** once ≥30 graded rows exist, and re-pitch every roundup with a checkable number attached | S (2h) |
| Oct–Nov | Open-source the league-FAAB calculator on GitHub + ship a **stdio MCP** on npx/PyPI, product named in the README | L (10h) |

**Why the Sunday send is Week 3 and not pre-launch:** it is the right feature — the injury gap is
real and cadence is a table stake we lose badly (Scoutcast ships four briefings a week, STACKED
two, we ship one on the wrong side of the news cycle). But it is a second cron, a diff renderer, a
new idempotency suffix and a second template that must not drift from `render/report.py`'s shared
constants. Ship it when Tuesday is boring.

**Why the MCP is honest and cheap:** a *stdio* MCP runs on the user's own machine and takes a
username or league ID as an argument, so with Sleeper's no-auth API it needs no server, no OAuth,
no secret store and no identity layer. Its value is a checkbox in every comparison table, a reason
for a roundup to include us, and a GitHub page (a heavily-cited domain) that is a third-party
surface we fully control — **not** an acquisition channel. Say that out loud rather than counting
subscribers from it.

### Automation milestones
- Week 2: GitHub Actions cron replaces manual pipeline runs. *(Built.)*
- Week 4: receipt-card image generator + public ledger page fully automatic. *(Built.)*
- Week 6: subscriber onboarding fully self-serve. *(Built — `run/sync.py`.)*
- Week 8: content drafting automated end-to-end; human role = edit voice + approve + reply only.

### Next off-season — and the real launch

**August 2027 is the actual launch.** Intent to pay peaks with drafts in the last week of August.
Season 1 is a proof season: ~100 subscribers, a ledger holding real rows, a renewal cohort, an aged
and indexed corpus, and hopefully a signed Sleeper licence. Judge 2026 against that, not a revenue
number.

| Task | Size |
|---|---|
| **Aggregate FAAB corpus across subscriber leagues** — "across N real Sleeper leagues, the median winning Week-3 bid was $X." Uncopyable by rankings sites, and the causality runs subscribers → asset, never the reverse (league IDs are not enumerable) | L |
| Relaunch into the draft peak with a year-old domain, real receipts, and an aged comparison hub | M |
| Sleeper Mini — **only if §0's licensing conversation went well** | L |
| ESPN / Yahoo — **only if** Sleeper-only proved to be the ceiling rather than the wedge | L |

## 4. Offer ladder & monetization rules

**REVISED Aug 17 2026 — the price rises and a free door opens.** The Aug 13 decision was "charge
from day one, no free tier," with the public ledger and the Week-2 refund as the risk-reversal.
Two things break that: **the ledger cannot hold a single graded row before October** (a call needs
three prior appearances from both players, so weeks 1–3 publish no confidences at all), and **every
competitor has a free door** — GridIQ free with no card, LeagueVision a 3-day no-card trial,
ffwrapped and My Fantasy Analyzer free outright. Paid-from-day-one, with no trial, no free artifact
and no gradeable record until October, is the sharpest self-inflicted disadvantage in the analysis.

1. **Free first week.** Their league, their rival, their numbers. It is also the *only* September
   proof asset that exists, which is the sequencing problem nothing else solved. **Run it manually
   for the first four weeks** — collect email + username, render, send. Zero code, zero vendor
   dependency, ships day one. Automate in October only if it converts (§6).
2. **Season pass $39, not $29.** The market clusters $39–$99 (4for4 $39/$59/$99, Fantasy Life+
   $39.99, Scoutcast $49.99, FantasyPros $47.88/yr) while AI entrants sit at $4.99–$9.99/mo. $29
   is *below the market floor* and reads as a confession about the weak backtest. **$39 with a free
   first week beats $29 with no door.** Price was never this business's problem; discovery and
   credibility are.
3. **Do not cut price to compete with free.** You cannot win a price war against $0. Compete on
   the thing arriving in the inbox and on the published test.

**At checkout, still exactly one decision:** Founding Season Pass **$39** shown beside **$9.99/mo**.
Refunds no-questions through Week 2. The monthly×3.65 > season-pass rule below still holds at $39
(3.65 × $9.99 = $36.43 — **this now INVERTS**; see the corrected rule).

**CORRECTION forced by the price change:** at $39 the season pass is no longer cheaper than paying
monthly all season, so the ladder inverts and the monthly tier becomes the rational buy. Fix by
raising monthly to **$12.99** (3.65 × $12.99 = $47.41, so the pass saves ~18%) when the $39 price
ships. Whichever numbers are chosen, the invariant stands: **monthly × 3.65 must exceed the season
pass, or the anchor argues against the product you want sold.**

**Code consequences of the price change** (do them together, item 12 in §3): `site/index.html`,
`site/join/index.html`, `site/league-pass.html`, the renewal-disclosure strings, and the
`tests/test_site.py` assertions that pin "$29" and the renewal terms. A price on a page that
disagrees with the Stripe link is an honesty failure no test currently catches.

**"First 50" framing is retired.** A count implies fewer than 50 customers exist, which is true and
not worth announcing. The CTA says what actually happens: *"Get this week's report — free."*

**Prices are USD** (owner decision, Aug 14 2026) — the paying fantasy market is overwhelmingly US.
Every price shown to a buyer must carry the currency; an unlabelled "$39" is ambiguous for buyers
and a support burden. Confirm the currency setting in Stripe before launch so the charge matches
the page.

**The ladder invariant** (established Aug 14 2026, re-derived Aug 17 at the new price): a paid
season runs Sep 8 → late Dec = 111 days ≈ 3.65 months ≈ 16 weekly reports. **Monthly × 3.65 must
always exceed the season pass**, or the anchor argues against the product we want sold and invites
exactly the month-to-month churn this pricing exists to prevent. At $6.99 against the old $29 pass
the ladder was inverted ($25.49 < $29); $9.99 fixed it ($36.43). **At $39 it inverts again**
($36.43 < $39), which is why the monthly tier rises to $12.99 alongside the price change
($47.41, so the pass saves ~18%). Re-check this arithmetic on any future price move.

**Copy does not argue the price** (owner direction, Aug 15 2026, recorded in CLAUDE.md — this
supersedes the earlier "anchor to the league pot" instruction, which was still written here and is
now removed). Prices appear plainly at decision points and in the legally required disclosures, and
are never itemized per-unit or compared, because price-justification math primes analytical
thinking and analytical buyers defer. **The one exception is `site/league-pass.html`**, where a
commissioner justifying spend to eleven leaguemates is a genuinely deliberative buyer and the
$468-vs-$99 arithmetic is their language.

Implementation: Stripe recurring prices — annual (season pass) + monthly. One-offs via payment links.

**Upsells appear only post-purchase, in-product, in this order:**
1. Week 3 — **Rival Deep-Dive $19** (custom one-off report; ~20 min fulfillment with engine; offered as
   one line inside subscriber reports only).
2. Week 13 — **Playoff Gauntlet $12** (weeks 14–17 intensity package, offered only to alive teams —
   monetizes the elimination churn cliff instead of suffering it).
3. **League Pass $99** — BUILT Aug 2026 (`site/league-pass.html`; `plan:"league_pass"` seats in the
   registry; seat-coverage reporting in `run/batch.py`). One payment covers the league; every
   manager who signs up gets their own report aimed at their own rival. Deliberately NOT a third
   card in the pricing section — one quiet link instead, so the individual buyer still faces
   exactly one decision. Arms-dealer dynamics make the league itself the marketing channel.
   **REVISED Aug 17 2026: any manager can buy it, not only the commissioner.** Precedent exists,
   and requiring the commissioner makes every league sale depend on one specific person agreeing.
   Copy edit, not architecture. This is also the **best-supported tier in the research**
   (commissioner-buys-for-league is an established shape; CBS charges $99.95/league) and the only
   motion that can close inside 22 days — §3B sells it before anything else gets built.
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

**Launch blockers before the site goes public** — the operative list is now §3A; this records the
constants and the one that must deliberately stay EMPTY. Each is a one-line edit once the account
exists: a project contact inbox (never a personal address) into `CONTACT_EMAIL` on both funnel
pages and into `legal.html`; `STRIPE_LINK_SEASON` / `_MONTHLY` / `_PASS` plus `CHECKOUT_OPEN`;
`LEDGER_LIST_ENDPOINT` and `LEDGER_FREE_URL` for the watch-the-ledger capture. `SUBSTACK_URL` is
superseded by the Stripe decision below and is only relevant if Substack takes the money after all.
Until the inbox exists the signup forms honestly say signups aren't open — correct, but it also
means zero conversions, so it is the first thing to fix.

**`FORM_ENDPOINT` stays EMPTY until seat provenance is fixed** (found in the Aug 17 audit). The
League Pass seat path validates that a pass covers the league, but nothing binds a claim to the
person making it. Sleeper user ids are public and the seat link is necessarily public, so with a
live form backend anyone could POST a paying member's user id with their own address and
permanently receive that manager's personalised report — roster, named rival, leaguemates' fragile
spots — while the subscriber, still being charged, silently stopped getting it. Seats are the only
path needing a form backend, so leaving it empty costs seats, never sales. The fix needs a design
call: a per-seat token in the commissioner's link, or a confirmation to the claimed address, plus
first-claim-wins per (league, user) unless the email matches.

### Payment → delivery: how a purchase becomes a Tuesday email (decided Aug 14 2026)

Requirement: someone pays, and reports start arriving and keep arriving every Tuesday for as long
as they are paid up — with no human step anywhere, at near-zero cost.

**Recommended stack: Stripe (billing + entitlement) + Resend (sending).** Both are wired and
tested; both are config, not code, so switching either is a secret change.

| Piece | Choice | Cost at 100 subscribers | Why |
|---|---|---|---|
| Billing | Stripe Checkout/Payment Links | 2.9% + 30¢ | vs Substack's 10%, saves ~$3.60 per $39 pass |
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

**Built (Aug 14 2026): `run/sync.py` and the season auto-roll**, so the flow is zero-touch
end to end including League Pass seats. A stranger picks their rival, pays, and receives a report
every Tuesday with no human step anywhere. Mechanics in CLAUDE.md; the operator-visible facts:
- Runs before the batch in `weekly.yml`, `continue-on-error` — a sync that cannot reach Stripe
  must not stop last week's known-good registry from being delivered.
- With `STRIPE_API_KEY` unset it is a no-op, so enabling the whole pipeline is a secret, not a
  deploy.
- `make sync-preview` shows what the next run would change without writing or stamping anything.
- The restricted Stripe key needs **write** on Customers as well as read, for the metadata
  promotion. Nothing else needs write.
- **`STRIPE_PAYMENT_LINKS` is a launch blocker, not an optimisation.** Set it to
  `s:<season link id>,m:<monthly link id>,p:<pass link id>`. It is what makes the purchased plan
  a fact about the payment instead of a claim in the buyer's URL — without it, no purchase can
  grant League Pass coverage (deliberate: fail closed). Adversarial review found that trusting the
  URL let anyone buy the $99 pass for $9.99, for any league; see CLAUDE.md for the three rules
  that now hold.
- Make the **$99 League Pass a recurring annual price**, not a one-time charge. A one-time payment
  creates no Subscription, so there would be nothing for entitlement to read next season. As an
  annual subscription it renews like the $39 pass and gets the same self-serve portal cancel —
  and `site/league-pass.html` already discloses "renews once a year at $99 unless you cancel", so
  the term is stated where it is sold.

**Revisit a small server (Cloudflare Worker) as a §7 risk item if either trigger fires: League
Pass passes ~5 leagues, or the form backend proves flaky twice.** The form backend is now the
only external dependency in the signup path and only affects seats, which is what makes that
threshold the right one.

New launch blockers from this decision:
- Create the Stripe products/prices and **Payment Links**, then paste them into
  `STRIPE_LINK_SEASON` / `STRIPE_LINK_MONTHLY` and set `CHECKOUT_OPEN = true`.
- Make the **$99 League Pass a recurring annual price, not a one-time charge** — a one-time
  payment creates no Subscription, leaving the Checkout Session (whose retention Stripe does not
  document) as the only record of an entitlement that must survive a season. If it becomes
  recurring it also needs the same renewal disclosure the $39 card carries.
- **`legal.html` still names Substack as the place to cancel.** Whichever platform actually takes
  the money, the cancel instructions must name *that* one. Shipping checkout on Stripe with cancel
  steps pointing at Substack is exactly the ambiguity §4 exists to prevent.
- A restricted `STRIPE_API_KEY` (read: subscriptions, customers, checkout sessions). Create it in
  a sandbox first and confirm the permission labels against the request log rather than guessing.
- **Set the pass Payment Link's confirmation-page message** to remind the commissioner about the
  seat link: "Your league's seat link was shown on the page where you picked your rival — it's
  beatyourleague's join page plus `?pass=<your league id>`. Send it to your leaguemates; each
  picks their own rival and claims a free seat." Stripe confirmation messages are static per
  link, so the exact URL can only be shown pre-checkout — the picker displays it the moment the
  commissioner selects their league (built Aug 2026), and this message is the backstop for the
  one who paid without noticing it.

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
1. **Season pass, paid upfront.** $39 lands on day one. The no-questions window closes at
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

**Renewal disclosure (non-negotiable).** The $39 pass is an **annual tier**, so it
auto-renews — which is fine revenue and NOT fine to leave unsaid. Both decision points (landing
pricing card + picker confirmation) must state "renews once a year at $39 unless you cancel", and
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
$39 product incinerates money; CAC here is daily minutes. Every channel below consumes engine output (numbers,
backtest, graded calls) — which is why marketing cannot start before Phases 1–2 exist.

### 5.0 The honest headline: search will not deliver this season

**AI search and SEO will produce approximately zero subscribers before January.** Not because the
tactics are wrong — because of arithmetic. Roughly 1.7% of new pages reach the top 10 within a
year; 72.9% of top-10 pages are 3+ years old; the realistic floor for a new domain to rank for any
non-branded term is 4–6 months. The season is 18 weeks. Anything ranked matures in February, when
fantasy demand collapses until August. On the AI side, all chatbots combined send ~0.3% of web
referral traffic against ~25% for organic search, and ~85% of brand mentions in AI answers come
from **third-party** pages rather than your own domain.

**Consequence for the plan: everything on the site is a 2027 asset that happens to double as a
sales page today.** Build it now, at near-zero cost, and expect it to pay next August. Fund *this*
season from people, not pages.

**One more thing worth knowing:** Gemini — the engine named in the original question — reportedly
cites Reddit least of all the major engines (~0.1%) while Google's AI surfaces lean YouTube
(~18.8% of AI Overview top-10 citations). So "go win Reddit" is ChatGPT/Perplexity advice that
does little for Gemini. The Gemini-shaped play is YouTube, and **declining it is the right call for
a solo part-timer — but name the cost:** we are not buying Gemini visibility this season.

### 5.1 Channel order, by subscribers per hour of founder time

1. **Your own league and the leagues you're already in.** The only channel where the League Pass
   closes inside 22 days. Twelve managers who already know you, in a group chat you already post
   in. It does not scale and does not need to. *(§3B — do this first.)*
2. **Discords and league group chats.** Human mods you can actually ask permission from.
3. **Founder-disclosed comparison content** (`site/compare/`). Verified working right now by a
   direct competitor: Scoutcast's co-founder wrote a "best fantasy football apps" piece, disclosed
   authorship, and it ranks live — while omitting LeagueVision, STACKED and FantasyPros. **The
   complete, honest one is more useful, and it is this product's honesty principle applied to
   marketing rather than a new posture.** It is also a page you can paste into a Discord reply today.
4. **Third-party mention campaign.** 12–15 identical pitches, same week, same sentence (§1). The
   door is verifiably open — FantasyPros' own AI-tools listicle already includes two indies. One
   email is a lottery ticket; twelve identical ones is a channel, and repeated identical phrasing
   across independent domains is the co-occurrence signal that forms an entity.
5. **The weekly content feed you already built and are not publishing.** `run/content.py` drafts
   Receipts Monday, Hype Wednesday and Coin-Flip Friday from graded data at zero marginal cost.
   Publishing them is **~50 dated, number-dense, self-contained pages by January**, every one
   already in the passage shape retrieval chunks well *because the honesty rules force it*. Biggest
   missed asset in the whole plan; costs 3 hours plus 30 minutes a week.
6. **`reports/projections-eval.md`** (written, unpublished). "How accurate are Sleeper's own
   projections?" has no published answer anywhere in the research, and we have one graded on a
   frozen call set. It is the **proof link on every pitch email** — verifiable in thirty seconds.
7. **X replies.** Kept below, demoted: it is a real channel but slower per hour than 1–3.

### Query shapes to target — and the one to refuse
Target question and comparison shapes, not commercial ones: *"how do I scout my fantasy football
opponent," "is there a free alternative to LeagueVision," "how accurate are Sleeper's projections,"
"how much FAAB should I bid in my league," "sleeper fantasy tools compared."*

**Do not build branded `/vs/` pages.** Neither side of "LeagueVision vs Beat Your League" has
search volume — those competitors have essentially no third-party review footprint. Comparison
*shapes* trigger AI Overviews often; that describes shape, not demand.

### Explicitly do NOT do (hours saved, and why)
| Don't | Why |
|---|---|
| `llms.txt` | Google's own docs say no effect; ~408 requests observed across 500M+ AI bot visits. No major AI company reads it |
| Schema as a *strategy* | A 1,885-page causal test found AI Overviews −4.6%, ChatGPT +2.2%. Do the 1h of hygiene, then stop |
| Chase "best fantasy football tools" | Publisher-owned and self-ranking (FantasyPros puts its own tool #1; Draft Sharks scores itself 95/100). Pitch for a *mention*; don't build for the query |
| Branded `/vs/` pages | Above (~5h saved) |
| Build a trade analyzer | Needs a server. Disclose the gap and point at a free one (~20h saved) |
| Real-time injury alerts | Structurally wrong for a weekly email. Sell the if/then plan as the answer (~15h saved) |
| Any remote/OAuth MCP or credential-holding service | Inverts the security posture for unproven acquisition value |
| Sleeper Mini this season | React Native + approval gate + §0 unresolved |
| YouTube | Right to decline solo — but it is the Gemini play, so name the cost |
| Post to r/fantasyfootball before reading its rules yourself | A ban from 3.4M members is unrecoverable; the check takes ten minutes. **Every crawler in the research was blocked, so these rules are UNVERIFIED** |
| Loosen the honesty gates to look more like competitors | They are the tiebreaker inside the comparison, and they're tested in code |
| Publish the availability-controlled calibration table as accuracy | `backtest.md` itself calls it a diagnostic. Already decided; do not undo it |

### Detail — X (ranked 7th; see §5.1 for the order)
- **Setup, once in launch week:** bio + pinned backtest thread. Build a list of 25–30 fantasy accounts:
  2–3 giants (e.g., Matthew Berry, FantasyPros) for reach-surfing, the rest mid-size grinders (5–50K followers)
  because they actually engage back. Turn on notifications for the 10 most active.
- **Data-replies — the core growth mechanic (20 min/day):** 15–20 replies daily to start/sit questions and hot
  takes, each carrying a number plus one line of reasoning ("Achane 64/36 over Hall — 71% route rate is
  the tiebreaker"). A calibrated number in a sea of vibes-replies is a free product demo. Never link in replies.
- **Posting windows:** Tue morning (waiver panic), Thu evening + Sun morning (lineup dread). Use the three
  formats below.
- **Signature move:** every Monday, quote-tweet Friday's own call with the box score attached — hit or miss.
  Public self-grading is rare enough to be a spectacle; it is also the brand.

### Detail — Reddit (rules-first; read them yourself before posting)
- r/fantasyfootball plus 2–3 smaller subs. Read each sub's rules page first; message mods before ever
  mentioning a tool — one permission ask beats one ban.
- 5–10 genuinely good, data-backed answers per day in the daily start/sit threads. Zero links in posts or
  comments; the product lives in the profile only. Highest purchase-intent channel on this list: it demos the
  product at the exact moment of need.

### Detail — Discords & league group chats (ranked 1st–2nd)
- Sleeper communities and podcast Discords, same value-first conduct as Reddit.
- Beta leagues (mine + 2–3 friends'): source of testimonial screenshots and the gift-a-rival mechanic. One
  league group chat that adopts receipts culture = twelve warm prospects locked in a room with money on the
  line. **Expect nearly all of season 1's subscribers to come from here** — §5.1 ranks this first,
  and §3B sells into it before anything else gets built.

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

Same rule the grading code already enforces on the model, applied to the business: written down
before the season, never adjusted after results.

| Read by | Metric | Green | Red → do this |
|---|---|---|---|
| **Aug 31** | League Passes closed from personal selling | ≥2 | 0 after five honest attempts → the bundle isn't wanted. **Stop building pages; interview the five who said no** |
| **Oct 6** | Tuesday open rate (3 sends) | ≥40% | <30% → format problem, not discovery problem. Fix the email before another marketing hour |
| **Oct 11** | Trial → paid conversion | ≥10% | <5% → stop building; interview five trial users |
| **Oct 11** | Paid subscribers | ≥40 | Hold this gate; do not move it because the positioning changed |
| **Oct 11** | Trials from **non-personal** channels | ≥30% | <10% → this is a friends-and-family business, not a product. **Decide that in October, not January** |
| **Oct 20** | Ledger rows + first calibration | ≥30 rows | Rows exist but calibration is bad → **publish it anyway**, that is the brand. But stop selling on calibration and sell on the file |
| **Oct 31** | Search Console impressions on any new page | any | **Zero → stop all SEO/AEO hours for the season.** Redirect them into Discord and leagues. Pre-committed |
| **Nov 1** | Week 4 → Week 8 retention | ≥85% | <70% → kill the monthly tier, sell only the season pass |

**The pivot rule.** If Oct 11 shows <25 subscribers and <5 from outside your network, stop building
product. Spend the rest of the season on exactly two things — generate graded ledger rows, and
publish the weekly content feed — then relaunch in August 2027. That is a materially better
position than any amount of feature work bought in October 2026.

Leading indicators watched weekly: trial signups, Tuesday open rate, free→paid conversion, League
Pass seats claimed vs league size. Vanity metrics ignored: impressions, likes, follower count.

## 7. Risks & mitigations

- **Sleeper licensing (§0)** → the single existential risk. Email this week; every other item is
  conditional. Sleeper's terms also grant safe harbour only to approved integration partners, which
  means exposure can land on a *subscriber's* account, not only ours.
- **Free substitutes** → ffwrapped (free, no login, "manager profiles & rivalries"), GridIQ (free,
  weekly grades and points-left-on-bench), My Fantasy Analyzer (free FAAB suggestions), and
  Sleeper's own matchup screen. Mitigation: compete on the file *arriving* and on the published
  test; never on rivalry data or FAAB pricing as positioning.
- **Direct paid competitors are closer than assumed** → Scoutcast sells "H2H opponent edge"
  briefings for Sleeper at $49.99/season; STACKED emails a personalized Tuesday recap. Mitigation:
  §1's one sentence, and the omissions block that none of them can write back at us.
- **Bad accuracy stretch** → pre-committed grading rules + publish misses; sell discipline, not
  clairvoyance.
- **Weeks 1–3 have no confidences at all** → the free week, the waiver section (counted data,
  no calibration burden), and copy that frames the gate as the product working.
- **Seasonality** → dynasty/keeper or a draft-week product are the realistic year-round candidates;
  see §4. Do not bill through months with no product.
- **Solo burnout** → if a week slips, subscriber reports ship and content skips.
- **Scope creep** → nothing gets built that isn't in §3. New ideas go to IDEAS.md.

## 8. Definition of success

**Revised Aug 17 2026, downward and honestly.** The arithmetic: 40 season passes at $39 is $1,560;
three League Passes is $297; infra ~$15. **A realistic good outcome is $1,500–$3,000 for the
season, essentially all of it from channels that are people, not pages.**

If the threshold for "makes money" is higher than that, no strategy in five research lenses reaches
it this season, and the correct move is to run 2026 deliberately as **the paid pilot that builds the
2027 asset**: a real ledger, measured calibration, an aged corpus, a year-old domain, a renewal
cohort, and possibly a signed Sleeper licence — all pointed at the August 2027 draft peak.

So: by Jan, an automated system with ≤3 hrs/week human input, ~100 paying subscribers, a public
track record holding real graded rows, ~50 published dated pages, and a product a stranger can be
told about in one sentence. The old "1,000+ email list" target is retired — it was never measured
against a channel that could deliver it.

## 9. Evidence, and what is NOT verified

The product refuses to publish a number it cannot stand behind. The plan gets the same treatment.

**Verified directly against primary sources on Aug 17 2026:**
- Sleeper's non-commercial licence clause (docs.sleeper.com, fetched twice).
- Scoutcast: Sleeper support, "H2H opponent edge", $5.99/mo + $49.99/season NFL add-on.
- ffwrapped.com: free, no login, Sleeper + ESPN, "Manager profiles & rivalries", weekly reports.
- Resend's free tier limits (3,000/month, 100/day, 1 domain).
- All five empty launch constants in `site/`.

**Reported by research agents but NOT independently verified — treat as leads, not facts:**
- GridIQ's free tier and its "weekly grades / points left on bench" headline.
- My Fantasy Analyzer's free FAAB bid suggestions.
- STACKED's Tuesday recap + Friday preview cadence.
- Sleeper native showing opponent start/sit accuracy on the matchup screen.
- Every AEO and SEO percentage in §5.0 — several are vendor-published with no methodology. The
  directions are consistent across sources; **do not plan against a specific number and do not
  quote one to anyone.**
- LeagueVision's season-pass price and GridIQ Pro's price. **Verify both before either appears in
  `site/compare/`** — a stale price table on our own domain is an honesty failure no test catches.

**The largest gap: zero voice-of-customer.** Not one fantasy manager's own words were read; Reddit
was blocked at the tool level in every research lens. Every demand claim in this plan is revealed
preference from vendor pricing pages, and *"three competitors sell this"* is equally consistent
with *"three competitors are failing to sell this."* **This is exactly what §3B exists to fix, and
why selling comes before building.** No competitor's subscriber count, revenue or download figure
was confirmed anywhere.

**Unknowable from public data:** what share of Sleeper redraft leagues use FAAB (league IDs are not
enumerable — sample your own, §3A item 2), and free-to-paid conversion for this niche (no benchmark
exists; measure it, don't model it).
