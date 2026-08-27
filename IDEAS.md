# IDEAS.md — parking lot

New feature ideas land here, never in the current sprint (see PLAN.md §7,
scope creep). One line each; promote to a phase only at a sprint boundary.


## Ranked after the Aug 16 2026 market research

Ordered by (customer value) / (build cost + breakage risk), against the stated
objectives: automated, stable, cheap, useful, market-conventional. Nothing here
is in the current sprint.

### Launch-critical, owner only
- Paste the real league ID + SLEEPER_ROSTER_ID and run `make week` on your own
  league. Everything in this repo is verified against Sleeper's public sample
  league; the product has never run on yours.
- A project inbox: `CONTACT_EMAIL` is empty on both funnel pages and legal.html
  still says "[contact address — added before launch]". A paid subscription
  needs a working route for refund and deletion requests.
- Stripe products + Payment Links -> the three link constants + CHECKOUT_OPEN.
- Decide the billing platform. legal.html names Substack as the cancel
  destination; if the money lands on Stripe that is exactly the ambiguity
  PLAN §4 exists to prevent.
- Push to GitHub (private) and set Pages source to "GitHub Actions". Until then
  the crons cannot run and this code exists on one disk.

### Highest value next, buildable from data we already have
- **Backtest the shipping availability gate.** nflverse publishes a historical
  injury archive (CC-BY-4.0, plain CSV, verified: 5,133 rows for 2018 with
  report_status by week and gsis_id; Sleeper carries gsis_id for 100% of
  rostered skill players). Reconstructing the known-active gate over 2017-18 is
  the only way to turn the currently-unpublishable calibration into a real
  claim — or to learn honestly that the gate does not help. This is the single
  biggest evidence gap in the product.
- Usage on the rival's fragile spots, not just waiver targets. "Hopkins: 33
  targets in 4 games, 4 inside the 20" makes the bench case far harder to
  argue with than a projection alone. engine/usage.py already computes it.
- ~~Tiers as the display unit for slot calls.~~ **STRUCK Aug 16 2026 by our own
  evidence.** The gate backtest measured resolution at a 6.0-point spread across
  the entire stated range, so labelling calls "clear" versus "lean" would assert
  a discrimination we have just shown we do not have. The market convention is
  real; we have not earned it. Revisit only if resolution improves.
- Side-by-side rosters instead of two stacked lineup tables — Yahoo lists it as
  a headline matchup feature and it is what the market expects.
- ~~FAAB as a percentage of budget.~~ **STRUCK — RULE W1 already voids it.**
  `waiver_budget` is not a trustworthy denominator (two sample managers spent
  140 and 101 against a stated 100), so the market's percentage cannot be
  computed honestly here. The existing phrasing — "it takes 18 and you have 10
  left" — is clearer than a percentage anyway.

### Stability and automation
- Re-run the automation audit properly: one of three agents in the Aug 16 run
  returned placeholder output, so that lens was never actually done.
- Deliverability: SPF/DKIM/DMARC on the sending domain before the first real
  send, or Tuesday's report lands in spam and the failure is invisible.
- A canary: assert the Tuesday run produced N reports for N paid subscribers
  and fail loudly on a mismatch, rather than trusting exit codes.
- Prune `data/raw/stats` and `projections` for seasons nobody reports on, so
  the tracked repo does not grow without bound.

### Market-conventional features worth considering
- A free sample report keyed to the visitor's own league — every direct
  competitor offers a free way in, and ours is paid from first contact.
- Trade analyser. Frequently requested, and LeagueVision leads with it.
- Weekly recap of what actually happened (Monday), which is the format
  STACKED and Scoutcast both open their week with.
- Power rankings / playoff odds — conventional, but both need calibration
  evidence before they can carry a number under principle 1.
- A multi-league price. Per-league-only pricing is where the most engaged
  prospect's purchase dies.

### Pricing and positioning
- $29 is at the floor of this market (4for4 Lite $39, Footballguys Pro $59.99,
  Fantasy Life+ $99.99, ETR draft kit $54.99). Consider $34-39 before the
  founding rate locks.
- Reconsider the Week-2 refund window: Footballguys gives 30 days, Draft Sharks
  refunds through December.
- Retire "Beat your league, not the books." It puts betting in the buyer's head
  purely to disclaim it, in a product whose principle 4 forbids betting content.
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
- Whether the projections feed should be adopted as a blend (reports/
  projections-eval.md: 68.8% vs 64.4% on 368 shared calls, but no opinion on
  626 of 994). Needs the matchup band re-backtested under the blend first.

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
- **Season review (Jan–Feb).** `engine/ledger.py` already holds every published
  call, graded, and the box scores are cached. "Your season, every call graded,
  the points you left on the bench" is close to free to build and lands exactly
  when a manager is still thinking about it.
- **Draft prep (Jun–Aug).** `engine/preseason.py` already produces it — byes,
  positional ranks under the subscriber's own scoring, slots that cannot be
  filled. It ships today as the purchase-day file; it is a product on its own.
- **Mar–May: nothing honest.** Free agency and the draft are what move value
  then, nflverse carries no news, and there is no free source that does. Do not
  sell those months.

So the reachable shape is ~7 months of product, not 12. Sequence: build the
season review, then the draft-prep file as its own artifact, and only then
price a twelve-month tier. Selling the months before they contain something is
the one move that cannot be undone cheaply — it is the review that follows you.
