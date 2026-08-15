# Beat Your League — Project Brief

**One line:** A weekly NFL fantasy "Rival Report" built around beating one specific opponent,
generated automatically from live league data and delivered to paying subscribers.

**My Sleeper league ID:** `PASTE_LEAGUE_ID_HERE`  <!-- from sleeper.com/leagues/<ID>/... -->

---

## Product summary

Subscribers get one report every Tuesday (template: `rival-report-template.html`), with eight
sections: (1) 30-second action checklist with deadlines, (2) matchup + win probability +
floor/ceiling ranges, (3) full optimal lineup with per-slot confidence, (4) where the rival is
fragile, (5) the "Regret Score" — the week's one coin-flip call, decided, (6) if/then pivot plan
for late news, (7) waiver Hype Meter (is league-wide FOMO justified or not), (8) a public
receipts ledger where every call is graded against real box scores.

Positioning: **analysis, not picks.** Emotional core: rivalry, regret-avoidance, bragging rights.
Delivery: email/Substack at $5–8/month. The AI is invisible to the buyer.

**Business context:** the full go-to-market plan, calendar, budget, and decision gates live in
`PLAN.md` (repo root). Build phases below exist to serve that plan's dates — Sprint 0 runs
Aug 12–16, and Week 1 subscriber reports must ship Tue Sep 8. New feature ideas go to
`IDEAS.md`, never into the current sprint.

## Non-negotiable principles

1. **Calibration over confidence.** Every probability we publish must come from a method we can
   backtest. If we say 64%, roughly 64% of such calls should hit historically.
2. **Grade everything publicly.** Wins AND misses go on the ledger. Grading rules are defined
   before the season, in code, and never adjusted after results.
3. **Never fabricate data.** If a feed is missing or stale, the report says so ("injury data as
   of Mon 6pm") rather than inventing a number.
4. **No betting instructions.** No picks against spreads/props, no staking advice. Calibrated
   analysis and context only; decisions belong to the user. Include the disclaimer footer from
   the template in every render.
5. **Define units.** "Confidence 64" = probability this start outscores the best bench
   alternative at that slot, under our model. Every score shown to users has a definition.

## Non-functional requirements

**Cost efficiency (target: near-zero infra + small LLM spend even at 100 subscribers).**
- The deterministic layer does everything it possibly can; LLM calls exist only for prose. One language-layer
  call per subscriber report and per content draft — never per section. Use the cheapest Claude model that
  passes the quality bar for templated prose; reserve stronger models for weekly one-off analysis.
- Cache every API response and rendered fragment; re-runs must cost approximately zero. Use batch endpoints
  where available. Log token usage per pipeline run in the verification summary so cost regressions are
  visible immediately.
- Infrastructure stays free-tier (GitHub Actions, GH Pages, Substack). Adding any paid service first requires
  a line in PLAN.md §2's budget table.

**Security (principle: the safest server is the one we don't run).**
- Keep the attack surface static: public pages are GH Pages static sites; payments and card data live entirely
  with Substack/Stripe — we never see, transmit, or store payment details.
- Collect the minimum: subscriber email, Sleeper league ID, rival name. No passwords, no accounts of our own —
  nothing to breach.
- Secrets live only in environment variables / GitHub Actions secrets, never in code or commits. `data/` and
  `.env` are gitignored from day one.
- Validate all external input (league IDs must match Sleeper's ID format; form fields sanitized). Treat all
  fetched data as untrusted: it flows into templates escaped, never executed.
- Pin dependency versions, enable Dependabot, review updates monthly. HTTPS everywhere (host default).
- Any future server, database, or credential-holding component is a PLAN.md risk-item decision first, not an
  implementation detail.

**Design.** Every public-facing surface — landing page, ledger site, emails — uses the report template's
design system (same palette, Barlow / Barlow Condensed type, same component style) so the brand reads as one
modern, professional product. Nothing ships with default or unstyled HTML.

## Architecture: two layers

- **Deterministic layer (Python, free to run):** data ingestion, caching, win-probability and
  confidence math, hype scoring, backtest grading, receipt generation. No LLM calls here.
- **Language layer (Claude API, pennies per report):** turns the deterministic layer's
  structured JSON into the report's prose (rival narrative, fragile-spot reasoning, Regret Score
  explanation). Prompted with strict instructions to only reference numbers present in the JSON.

## Data sources

- **Sleeper API** (public, no auth, JSON): base `https://api.sleeper.app/v1/`. Key endpoints:
  `/league/{id}`, `/league/{id}/rosters`, `/league/{id}/users`, `/league/{id}/matchups/{week}`,
  `/league/{id}/transactions/{week}`, `/state/nfl`, `/players/nfl` (large — cache to disk),
  `/user/{username-or-id}` and `/user/{user_id}/leagues/nfl/{season}` (onboarding),
  and the schedule feed at `api.sleeper.app/schedule/nfl/{type}/{season}` (outside /v1).
  CORS is open (`access-control-allow-origin: *`), which the signup picker relies on.
  League history: follow the `previous_league_id` field to walk back prior seasons.
  Verify current endpoint shapes against docs.sleeper.com before relying on them.
  Be polite: cache all raw responses under `data/raw/`, throttle requests, never hammer.
- **Later phases:** injuries/news and Vegas context (game totals/spreads) from legitimate free
  sources; flag data age in the report. Do not scrape sites that prohibit it.

## Repo layout

```
beat-your-league/
  CLAUDE.md
  PLAN.md                      # business plan: calendar, budget, marketing, decision gates
  rival-report-template.html   # render target (v2 design — do not redesign, populate it)
  ingest/        # Sleeper client + other fetchers
  engine/        # probabilities, confidence, hype score, backtest grader
  render/        # JSON -> HTML report using the template
  content/       # pipeline-drafted posts + receipt-card images (human edits before posting)
  site/          # public prediction ledger (GitHub Pages)
  data/raw/      # cached API responses (gitignored)
  data/processed/
  reports/       # generated weekly HTML
  tests/         # grading + math logic must be tested
```

Conventions: Python 3.11+, `requests`, small pure functions, type hints, no framework yet.
Raw JSON is cached so re-runs cost zero API calls. Everything reproducible from `data/raw/`.

## Build phases (in this order)

**Phase 1 — Sleeper ingestion (first session).**
Client that, given the league ID above, pulls: league settings, users, rosters, all matchups
and transactions for the current season and the most recent completed season (via
`previous_league_id`), plus the players table. Cache everything under `data/raw/`.
*Definition of done:* running `python -m ingest.pull` prints a verification summary — league
name, scoring type, all team names with owner display names, weeks of history retrieved,
and file counts written.

**Phase 2 — Backtest grader + receipts ledger.**
Using last season's data: for every week and every roster, reconstruct start/sit decisions the
engine would have flagged, grade them against actual points, and output a calibration report
(e.g., "coin-flip calls: 214 graded, 61% hit; stated 60–70% confidence bucket hit 64%").
Also compute each rival's behavioral profile from history: how often they started `questionable`
players, waiver aggressiveness (FAAB spent, claims/week), lineup-setting lateness if inferable.
*Definition of done:* `reports/backtest.md` with honest numbers, good or bad.

**Phase 3 — Report renderer.**
Populate `rival-report-template.html` from a single `week_report.json` produced by the engine
for MY roster vs my actual scheduled opponent. Requirements from the skeptic review:
(a) the rival's full lineup grid rendered opposite mine with fragile spots flagged inline;
(b) driver chips under key calls (route rate, Vegas game total, opponent matchup rank) so every
number teaches its own "why" — market data is shown as context only, per principle 4;
(c) rival behavioral lines cite their evidence ("started questionable players 7 of 9 chances,
league log weeks 3–14"). No invented stats: anything the engine can't yet compute renders as
"coming in v0.3", not a fake number.

**Phase 4 — Weekly orchestration.**
One command (`make week` or `python -m run.week`) that ingests, computes, renders, and drops
the report + a plain-text summary in `reports/`. Then a GitHub Actions cron for Tuesdays.

**Phase 5 — Content system (Season Weeks 2–4).**
Pipeline drafts the three recurring public formats from graded data — Receipts Monday,
Hype Meter Wednesday, Coin-Flip Friday — into `content/` for human editing. Receipt-card
image generator renders graded wins/misses as shareable cards. Public prediction ledger
publishes to `site/` via GitHub Pages on every Monday grading run.
Daily **reply kit**: each morning the pipeline writes `content/reply-kit-<date>.md` with the day's
6–8 sharpest engine numbers, one line of reasoning each, and ready reply templates — so replying on X
is paste-and-adapt, not composition. (Automated reply *targeting* would require paid X API access that
breaks the PLAN.md budget and is out of scope; the kit reduces human effort to selection only.)

**Phase 6 — Delivery + onboarding (Season Weeks 4–6; mechanism built Aug 2026).**
Subscriber registry drives the Tuesday batch run; per-subscriber reports emailed automatically.
Onboarding becomes self-serve: picker page → registry → included in next run with zero human
touch. Substack first; revisit Stripe direct only if its fees beat Substack's 10% at current
volume. See PLAN.md §3 for dates. Design decisions (verified against the live API):
- **Username-first onboarding, never raw IDs.** `/v1/user/{username}` → user_id →
  `/v1/user/{user_id}/leagues/nfl/{season}` lists their leagues; picking a league also
  identifies their own roster (owner match) — the subscriber never sees a roster ID.
- **Rival is selected, not typed:** a tap on one of the other teams' real names, keyed by
  owner_id (stable across seasons; roster_id kept only as orphan-team fallback).
- **Named rival ≠ weekly opponent.** The report's main matchup is always the actual scheduled
  opponent; the named rival gets a Rival Watch strip every week (their record, fragile spots,
  head-to-head history), and when the schedule pairs them it renders as Rivalry Week.
- **Static picker page** (`site/join/`) calls Sleeper's public API from the browser —
  `access-control-allow-origin: *` verified live — so no server of ours exists. Submission
  falls back to a prefilled email until a free-tier form backend is plugged in.
- Registry lives at `data/registry/subscribers.json` (gitignored — it holds emails); schema
  and loader in `run/registry.py`; batch runner in `run/batch.py` writes per-subscriber
  reports under `reports/subscribers/` (gitignored, filenames carry no emails).

## Working agreements for Claude Code sessions

- Show the plan before large changes; prefer several small verified steps over one big leap.
- After each phase, update the "Status" line below and note anything learned about the data.
- If an endpoint or assumption in this file turns out wrong, fix the file — it is the spec.

**Status:** Phases 1-5 complete + Phase 6 subscriber mechanism built early (172 tests passing).
Phase 5 content system: published-calls ledger (`engine/ledger.py` — records every published
probability at report time, grades only after both players' games are final, RULES L1-L4:
never premature, never edited after, 0.0-0.0 = void not tie, append-only under flock),
receipt-card SVGs (`render/cards.py`), public ledger page (`render/ledger_site.py` →
`site/ledger/`, aggregated across every league's ledger, anonymized, with a fail-closed
shrink guard so a data-lost store can never silently wipe the published record), and the
four content drafts (`python -m run.content all` / `make content`: Receipts Monday, Hype
Wednesday, Coin-Flip Friday — which quotes ONLY the recorded ledger entry, never a fresh
number — and the daily reply kit, which never names league members). `monday.yml` is the
Monday grading cron; both crons persist the ledger via actions/cache + artifacts. Phase 5
was adversarially reviewed: 10 confirmed findings fixed (incl. a reproduced cross-process
race that silently erased recorded calls), 2 refuted.
Phase 6 mechanism: signup picker (`site/join/`, live-tested against real Sleeper accounts —
username → leagues → own-roster auto-resolved → rival tapped from real team names), subscriber
registry (`run/registry.py`, gitignored data), batch runner (`python -m run.batch`: one ingest
per league, one report per subscriber, failures contained per-subscriber), and the Rival Watch
strip (named rival tracked weekly; Rivalry Week when the schedule pairs you). Remaining for
launch: plug a free-tier form backend endpoint into the picker (mailto fallback works today)
and connect the Substack list. All build phases are now complete.

**Payment → delivery (Aug 14 2026).** Nothing in the repo actually sent an email until now; that
was the largest automation gap. Two modules close it, both provider-agnostic so the platform
choice is a secret, never a rewrite (rationale + cost table in PLAN §4):
- `run/subscriptions.py` — *who is entitled to this week's report*. `resolve_paid_list()` asks
  **Stripe** directly when `STRIPE_API_KEY` is set, else parses a CSV export. The Stripe property
  that matters: a cancelled subscriber stays `status:"active"` with `cancel_at_period_end` until
  the period they paid for ends, so "they paid for a window and we're still in it" needs no date
  arithmetic of ours. `trialing` counts; `past_due` does not (the card bounced — Stripe retries and
  restores `active` itself). Stripe responses are parsed as untrusted input. With **no** entitlement
  source configured the run refuses and sends nothing: silently mailing people who cancelled is the
  one failure that becomes a chargeback.
- `run/delivery.py` — *the send*. Providers: `dry` (default — writes `.eml` drafts to
  `reports/outbox/`, gitignored, nothing leaves the machine), `resend`, `postmark`, `ses`, `smtp`.
  Every message carries an idempotency key (`league-season-week-slug`) checked against
  `data/processed/sent.jsonl`, so a re-run, a resumed workflow, or a double-fired cron cannot mail
  the same week twice. **Dry-run is the default on purpose**: a misconfigured cron must never mail
  real people by accident, so sending is opt-in via `EMAIL_PROVIDER`.
**The payment IS the signup (Aug 14 2026).** The picker used to be a dead end — it collected
picks and had nowhere to put them, so a signup and a payment were two records joined by an email
the buyer typed twice. Now `site/join/` packs the picks into Stripe's `client_reference_id` and
sends the buyer straight to a Payment Link:

    <payment link>?client_reference_id=s-<user_id>-<league_id>-<rival_owner_id>
                 &locked_prefilled_email=<their email>

Verified against Stripe's docs and in-browser: `client_reference_id` is settable as a URL
parameter (200 chars, `[A-Za-z0-9_-]`; our ref measures 55), it lands on the Checkout Session,
and `locked_prefilled_email` makes the payment address **non-editable** — so the address that
pays is the address that picked, by construction, and there is no mismatch left to reconcile.
Stripe **silently drops** an invalid `client_reference_id` while still showing a working payment
page, so the ref is asserted against `REF_RE` in the browser before we navigate: that is the only
place the failure can be made loud.

Consequences wired in code:
- `STRIPE_LINK_SEASON` / `STRIPE_LINK_MONTHLY` in `site/join/index.html` are the whole payment
  integration; empty means "not open" and the page says the picks are **not saved** rather than
  congratulating anyone on a reservation that does not exist. The mailto fallback is gone — it
  lost signups and looked like it worked.
- `CHECKOUT_OPEN` in `site/index.html` flips the pricing CTAs on, and **both point at `join/`**.
  A CTA that jumps straight to checkout takes the money with no picks attached; guarded by
  `test_every_paid_cta_routes_through_the_picker`, and no payment URL is ever published on a page.
- `?plan=monthly` selects the monthly link and rewrites the renewal line to monthly terms — the
  pass's "renews once a year" is not true of monthly and must not be shown to a monthly buyer.
- **League Pass seats cannot ride on this**: one $99 payment produces exactly ONE session with
  ONE `client_reference_id`, and the other eleven seat-holders never transact. `?pass=<league_id>`
  runs the picker in seat mode — no checkout, league-matched (a seat for another league is
  refused), posting to `FORM_ENDPOINT`. That is the ONLY path that needs a form backend, so a
  vendor outage costs seats, never sales.
- `SEASON` comes from `/v1/state/nfl`, not a constant that goes stale every September.

**Three delivery bugs found and fixed the same day (all reproduced before fixing, all
mutation-tested after):**
1. `run/batch.py` filtered on `paid.covers(s.email)` and never looked at `covered_by`, so **every
   League Pass seat was dropped** — reported in the words meant for a cancellation. The $99 tier
   was undeliverable except via `--no-paid-check`, which disables the gate for everyone.
2. `weekly.yml` gated the send step on `hashFiles('data/registry/subscribers.json')` — a path
   under the gitignored `data/`, which cannot exist on a fresh runner. **The cron had never been
   able to mail anybody.** The gate is gone (batch already handles an empty registry) and
   `data/registry` is now cached across runs.
3. The artifact upload took `reports/` wholesale, which would have published `subscribers/` and
   `outbox/` — real addresses and personalised reports — to anyone who can read the Actions tab.
   Both are excluded explicitly.
Plus a silent-success case: a non-empty registry where **everyone** fails the paid check now
exits non-zero. That is far more likely to be a broken entitlement source than every customer
cancelling in one week, and exiting 0 made it a green cron with an empty inbox.

**The signup pipeline (`python -m run.sync` / `make sync`) — zero touches, including seats.**
Runs before `run.batch` every Tuesday and turns payments into the registry:
1. **Sweep** completed Checkout Sessions since a watermark (`data/registry/sync-state.json`),
   decode each `client_reference_id` via `run/refs.py`.
2. **Promote** the picks onto the Stripe **Customer** as `byl_*` metadata. Stripe documents no
   retention guarantee for old Checkout Sessions, so this caps our dependence on session
   listability at one week instead of a season. Metadata writes merge — additive and idempotent.
3. **Seats** from `FORM_ENDPOINT` — the ONLY external dependency in the signup path, and it only
   ever affects League Pass seats. A seat is honoured only if a pass actually covers that league;
   the seat link is necessarily public, so an unvalidated endpoint would be a free-report
   generator. If the backend is unreadable the run **refuses** rather than writing a
   Stripe-only registry that silently drops every seat.
4. **Verify** every row against live Sleeper: does this user own a roster in this league, is the
   rival a real *different* team. A ref is a string a browser put in a URL; trusting it would mail
   someone another manager's team. A Sleeper **outage raises**, and the caller keeps the row —
   an outage must never look like a rejection.
5. **Roll the season** (see the data learning below). Ambiguous rolls change nothing and say so:
   a wrong league is worse than a missing one because it looks like it worked. A rival recorded
   only as a `roster_id` cannot be rolled at all — roster ids are not stable across seasons.
6. **Project** `subscribers.json` in the exact shape `run/registry.py` validates.

Storage under gitignored `data/registry/`: `signups.jsonl` (append-only event log),
`sync-state.json` (watermark), `subscribers.json` (the projection). `project()` is latest-wins per
`(league_id, user_id)`, which is what makes re-running the picker a **rival change** rather than a
duplicate, and what makes the whole sweep idempotent — verified end-to-end: run twice, identical
registry, no log growth; change a rival, still one entry with the new rival.

**Entitlement no longer joins on an email.** `PaidList.entitles()` tries, in order: the
subscriber's own `stripe_customer_id` (survives them changing their billing email in Stripe's
portal), their league appearing in `covered_leagues` (a League Pass, read from the payer's own
customer metadata so it lapses exactly when their billing does), then the email on file — the
fallback that keeps hand-added entries and the CSV path working.

**Plan prefixes are a JS↔Python contract with nothing type-checking across it**: the picker builds
`s|m|p-<user_id>-<league_id>-<rival>` in the browser, `run/refs.py` decodes it on Tuesday, and
`test_the_browser_and_python_agree_on_the_format` pins the literal JavaScript. A `p` ref is BOTH
the commissioner's own signup and the league's coverage — one purchase, two meanings. Payment
links: `STRIPE_LINK_SEASON` / `_MONTHLY` / `_PASS`, reached via `join/`, `join/?plan=monthly`,
`join/?plan=pass`; seats via `join/?pass=<league_id>`.

**The ref's plan prefix is a CLAIM, never a fact — this was a real hole, found in adversarial
review and fixed.** Every payment link is visible in the page source and `client_reference_id` is
a URL parameter, so a buyer could open the $9.99 monthly link by hand with a `p-` ref and receive
the $99 League Pass, *for any league id they cared to type* — collapsing every tier to the
cheapest. Three rules now hold, each mutation-tested:
- **The plan comes from the link that took the money.** `STRIPE_PAYMENT_LINKS` is a MAP
  (`s:plink_A,m:plink_B,p:plink_C`), and coverage is granted only when the session's own
  `payment_link` is the pass link. A mismatch still delivers the report they paid for, grants
  nothing, and is reported. **Fail closed**: with no map configured no purchase can grant coverage.
- **Coverage is stamped only after verification.** `byl_pass_league` is written by
  `stamp_pass_coverage()` from `main()` *after* Sleeper confirms the payer owns a roster in the
  league they are covering — never by `_promote()` during the sweep, and `covered` is built from
  verified payers, not the raw log. Otherwise an unverified claim hands twelve strangers a
  free product.
- **`payment_status` must be paid.** A session can be `status:"complete"` and still unpaid with
  delayed-notification methods.
Also fixed in the same review: the season roll now carries `pass_league_id` onto the new league id
(a pass pinned to last season's id means the commissioner keeps paying while every seat claim
finds no coverage), and `run/batch.py` no longer rebinds `failed` for send failures — that made a
run where somebody's report failed to build but every send succeeded exit 0.

**Second review pass (48 agents, 18 confirmed / 25 refuted) — the "one bad row stops everyone"
class.** `run/registry.py` fails the WHOLE file on any invalid entry, so anything that can put one
bad row in `subscribers.json` is a total outage, not a single-subscriber problem. Four ways in,
all fixed and mutation-tested:
- **Registry uniqueness is per (email, league), not per email.** `sync.project()` is keyed on
  `(league_id, user_id)` and deliberately emits one row per league, so a subscriber in two leagues
  — and *every* subscriber during a season rollover — made the registry unloadable. The old rule
  and the projection were a contract that disagreed, with `test_two_leagues_for_one_person` on one
  side and `load_registry` on the other.
- **A season roll writes a tombstone** (`Signup.retired`, `retire()`). The roll gives the
  subscriber a NEW `(league, user)` key, so without retiring the old one the projection carries
  both — two reports, one about a season that is over.
- **Seat emails are validated to `registry.py`'s own standard in `seats_to_signups()`.** The seat
  endpoint is public, so `"not an email"` from any stranger stopped every subscriber's Tuesday.
- **`drop_unloadable()` validates every projected row before it is written**, against both of the
  loader's whole-file rules. Defence in depth: a row we cannot parse is dropped and reported
  instead of taking the run down.

**A payment always beats an unpaid claim** (`project()`). Sleeper user ids are public and the seat
form must be public, so a stranger could POST a seat claim naming a paying subscriber's id with
their own address and receive that manager's report — while the subscriber, still being charged,
silently stopped getting it. Two seams had to be closed for this to hold: `main()` runs **one
combined projection** of payers and seats (projecting them separately never let the rule compare
them), and `payers` is built from **Stripe-sourced rows only** (projecting the whole log folded
seats into payers, so every legitimate seat was flagged as an attack on the next run — a security
warning that fires weekly for nothing trains you to ignore the real one).

Also fixed in that pass: `sweep_stripe` **sorts by Stripe's `created`** (Stripe lists newest-first
and `project()` is latest-by-position, so a changed rival lost to the pick they abandoned); the
new-event dedupe key includes `plan` and `pass_league_id` (an existing subscriber upgrading to a
League Pass changes neither rival nor email, so their upgrade was never logged and their league
stayed uncovered); unattributable payments **persist in `sync-state.json`** and are re-reported
every run until `--clear-unresolved` (the watermark moves past the session within days, so a
once-only message meant the third run forgot a customer who is still being charged); run output
uses `Signup.label` (Sleeper username) rather than the email, because summaries land in a CI log;
and `--dry-run` no longer writes Stripe customer metadata.

**Third review pass (fresh eyes on the second pass's own fixes) — ordering, precedence and
log hygiene.** `project()` is now **recency-aware**, not position-only: among same-source events
the newer `seen_at` wins, so a season roll (which carries last year's timestamp) can never revert a
subscriber who re-purchased with a new rival, and a rival changed via the seat form beats the older
logged claim. Other fixes, each mutation-tested: `drop_unloadable()` keeps the **payer** when a
shared inbox collides a paid signup with a seat (a seat must never evict a paying subscriber);
`verify_all()` tracks **outage-kept** keys separately so an unverified League Pass claim cannot
grant coverage during a Sleeper outage; the hijack warning fires only when the seat's address
**differs** from the payer's (a self-upgrade from seat to paid is not an attack and must not alarm
weekly); `--full` no longer discards the unresolved-payment memory (it ignores only the watermark);
`event_key` is module-level and tested directly (the old test pinned a copy); and every
operator-facing message routes addresses through `_no_email()` / uses `Signup.label` — run
summaries land in a CI log.

**Two known limitations, left in deliberately (documented, not fixed):**
- **League Pass seats are not season-rolled.** Payers roll via `roll_season`, but a seat comes
  from the live form each week carrying whatever league id was submitted. At a rollover the
  commissioner's coverage rolls to the new league while old seat submissions still name the old
  one, so those seats drop with "no League Pass covers that league" until members re-pick through
  `join/?pass=<new league id>`. Honest (no fabrication, it is reported) but not zero-touch for
  seats across seasons. Auto-rolling external form rows needs a design that keys seats to the
  payer's rolled league; out of scope here.
- **Entitlement is per Stripe customer, not per subscription.** `PaidList.entitles()` route 1 is
  "this customer has *an* active subscription", so a subscriber in two leagues who cancels ONE
  keeps both reports until the other lapses too. It errs toward giving product, never overcharging.
  A correct fix needs a subscription→league mapping (stamp the league on `subscription_data
  .metadata` at checkout and read entitlement per subscription); revisit if multi-league
  subscribers become common.

**Module path constants must never be default arguments** (`run/sync.py`, `run/delivery.py`):
a constant baked into a signature cannot be redirected by a caller or a test, which is what let a
pipeline run write over the real registry and a test poison the real send log. Paths are resolved
inside the function (`path = path or SENT_LOG`) or threaded from `main()` (`--registry-dir`).

**Tests may not touch `data/registry/`** — `tests/conftest.py` fails any test that writes there.
This exists because it happened: a pipeline run wrote over the real subscriber list. Nothing was
lost (one demo entry), but on a machine with paying subscribers that destroys the list of who gets
a report and stays invisible until the following Tuesday. Related: `run/sync.py` takes
`--registry-dir` and every function takes an explicit path, because module constants baked in as
default arguments cannot be redirected by a caller — which is what made that accident possible.

`make dry-send` builds every subscriber email without sending; `make send` is the real thing.
`make sync-preview` shows what the next sync would change without writing or stamping anything.
`weekly.yml` passes `STRIPE_API_KEY`/`EMAIL_*` as secrets and caches `sent.jsonl` across runners
(without it, an ephemeral runner would forget who it already mailed). Use a **restricted** Stripe
key — read access to subscriptions and customers is all this needs.

Public site (`site/`, GH Pages root): landing page (`index.html` — design-system CSS/SVG
visuals only, no stock imagery; every cited number is real backtest/demo output, labeled with
its source; pricing per PLAN §4 with checkout deferred to Substack links marked in comments;
art direction is the dark "floating receipts" theme — DFS-grade stadium-night shell, the
product's own paper reports as the floating visuals, gold plate/pill broadcast accents —
while join/ and the report itself stay paper-light on purpose: the dark page sells, the
paper product delivers),
`sample-report.html` (the real 2018 demo report), and `join/` (the picker). The buyer-facing
copy never mentions the implementation (product summary: the AI is invisible to the buyer).
Paid from day one (owner decision Aug 13 2026, recorded in PLAN §4): the picker takes
founding-price reservations, not free signups; reports go only to paid subscribers once
Substack checkout is live (set SUBSTACK_URL in site/index.html AND site/join/index.html to
activate it — one constant per page turns on real checkout).

Funnel additions (Aug 14 2026), built from a buyer-archetype review of the whole flow:
- **Live scouting demo** in `site/join/` — after picking a rival, the page computes one REAL
  number about them in-browser (points left on their bench = Sleeper's own `ppts - fpts`,
  plus record/FAAB), from the league record every member can already see. Verified against
  cached data: 228.4 for sample roster 1. The season label must come from the league actually
  read, never the page's SEASON default (a right number under the wrong year is fabrication).
  Leagues with no games played get an honest empty state, never an invented one.
- **"Watch the ledger" capture** on the landing page — the free off-ramp for buyers who
  reasonably want proof first (the paid-from-day-one decision had removed every non-purchase
  path, so intent leaked away with no way back). Wires to LEDGER_LIST_ENDPOINT, else Substack.
- **Retention/refund policy is in PLAN §4 and is a hard boundary:** no dark patterns, no
  cancellation friction, no designing for forgotten subscriptions. Non-refundable revenue comes
  from the upfront season pass plus delivering value before the Week-2 window closes.
  `tests/test_site.py` enforces the consumer-facing half of this (refund promise, cancellation
  language, unsubscribe promise, price honesty, no betting language, no innerHTML on
  stranger-supplied names) so the protections cannot be quietly removed later.
- **The $29 pass auto-renews** (it is a Substack annual tier), so both decision points state
  "renews once a year at $29 unless you cancel" and promise a pre-billing email. An undisclosed
  annual renewal is the forget-to-cancel pattern wearing a suit — `test_pass_states_its_renewal_terms`
  fails the build if the disclosure goes missing.
- **`site/backtest.html` publishes `reports/backtest.md` whole** — failing buckets, 53.5%
  headline, 7.2% ECE, the -5670.6 cost line. Regenerate it whenever backtest.md changes; the
  landing page links it and a test asserts the failures survive publication.
- **Delivery (`run/delivery.py`) is provider-agnostic and dry by default.** Until this existed
  the pipeline produced files a human had to mail — the largest automation gap in the product.
  `EMAIL_PROVIDER` picks the backend (`dry` | `resend` | `postmark` | `ses` | `smtp`); unset
  means **dry-run**, so a misconfigured cron writes `.eml` drafts to `reports/outbox/` instead
  of mailing anyone. Four properties are load-bearing and tested: sends are **idempotent** per
  (league, season, week, subscriber) so a re-run or resumed workflow never mails twice; **one
  failed send never stops the batch** and is not recorded, so it retries next run; provider
  errors **never echo credentials**; and the paid check in `run/batch.py` gates delivery, so
  nobody who cancelled is mailed. The send log (`data/processed/sent.jsonl`) is cached across
  CI runs — losing it would mean duplicate sends.
- **Platform note:** Substack cannot deliver this product. It broadcasts one post to everyone,
  while every subscriber needs a different report; it can only ever be payments + a CSV. The
  recommended end state is Stripe (checkout + customer portal + API-queried subscriber list)
  with a transactional email provider, both driven from the existing cron — no server, ~10% of
  revenue saved, and no manual export step. Substack's free tier still suits the *public*
  broadcast content (Receipts Monday, ledger posts). Decision not yet made; the delivery layer
  is deliberately independent of it.
- **Cancellation must cost the operator nothing (owner instruction, Aug 14 2026).** Substack
  already handles the cancel itself — the subscriber clicks, billing stops, we are not
  involved — so self-serve is the ONLY route the product advertises. Any copy promising
  "reply and we'll cancel it" creates an inbox someone has to read every day of the season and
  is banned by test (`test_cancelling_has_concrete_steps_not_just_a_promise`,
  `test_every_report_carries_a_way_out`). Because reports are personalised and therefore sent
  directly rather than as Substack posts, the pipeline learns who left from a Substack CSV
  export: `run/subscriptions.py` parses it (tolerant column matching; an unrecognised status is
  never treated as paid) and `run/batch.py` filters the run, refusing to proceed without either
  the export or an explicit `--no-paid-check`. Silently mailing people who cancelled is the
  failure that becomes a chargeback. Every report footer states that unsubscribing from emails
  does not stop a subscription — leaving that ambiguous is how honest businesses accidentally
  behave like dishonest ones.
- **League Pass ($99, commissioner buys) is built.** Registry seats carry `plan:"league_pass"`
  and `covered_by` (the payer's email — a seat naming no payer is rejected, since that is an
  unpaid report waiting to be sent); `run/batch.py` reports seats claimed vs league size, because
  an unclaimed seat is a promise the commissioner made that we aren't keeping. Every seat still
  gets its OWN report — the pass changes who paid, never what is delivered. The offer lives on
  `site/league-pass.html`, reached by one link, never as a third pricing card (PLAN §4: exactly
  one decision at checkout). Two entries for the same (league, Sleeper user) are rejected —
  that would mail one person another manager's team.
- **`site/legal.html` now carries the protective half too**, not just promises: liability capped
  at fees paid, no consequential/lost-winnings damages, as-is + implied-warranty disclaimer,
  refund as the exclusive remedy, no-redistribution (which is what makes League Pass defensible),
  Sleeper-dependency and force-majeure carve-outs, right to discontinue with pro-rata refund,
  changes-to-terms, governing law, severability — each with a consumer-rights savings clause so
  none of it strips protections buyers have by law. `test_legal_page_actually_protects_the_business`
  fails the build if any clause is deleted. Jurisdiction and contact are visible placeholders:
  **never guess them**.
- **Waiver-market intelligence (`engine/waivers.py`) is the edge rankings can't copy.** From
  the league's own transaction log: what a claim actually costs here (going rate, priciest
  win), how much FAAB each team has left, and — from *failed* bids — the price a manager was
  willing to pay and didn't get. Two rules are frozen in the module: RULE W1, one manager over
  the stated budget voids `waiver_budget` as a denominator for everyone (measured: two sample
  managers spent 140 and 101 against a stated 100), so it falls back to spend and says why;
  RULE W2, only weeks strictly before the report week count, so a live report can't quote an
  unprocessed claim. Bid guidance is derived from what THAT player has actually drawn, never
  the league-wide maximum, and is checked against what the reader can afford — recommending 38
  to someone holding 10 would burn their season. Rivals are **counted, never named** ("2 other
  teams can cover that"), which keeps other people's identities off any public surface.
- **Copy voice (Aug 15 2026, full-funnel pass against Underdog/ETR/Action Network):** a sharp
  leaguemate who did the homework — first person, short sentences, US spelling, group-chat
  vocabulary ("the file on Mike", "receipts"), numbers doing the selling. No template rhythms
  ("No X. No Y. No Z.", "One X. One Y:", em-dash triples), no "edge/unlock/elevate" filler, and
  honesty stated once then demonstrated, never preached. **"Engine" is now banned buyer
  vocabulary** (added to `_DEV_SPEAK`, swept across sample report + landing + join + the local
  live-report render): the machinery stays invisible, the honest register is "we tested
  everything against two seasons of real box scores". Email subject: "Week N: the file on
  <rival>" (rivalry weeks keep "RIVALRY WEEK vs"). Nothing is called "reserved" while checkout
  is closed — the CTA says what actually happens ("Pick your rival — first 50 get the founding
  price"). When editing render/report.py or engine/week_report.py strings, regenerate
  site/sample-report.html + the local demo pair + site/ledger/index.html through their real
  paths, never by hand.
- **Buyer copy and operator copy are different languages.** Version numbers ("v0.3"), file
  names, "LLM tokens", "pipeline", "availability snapshot", "calibration policy" are ours, not
  the customer's — a buyer reading "coming in v0.3" concludes they bought unfinished software.
  Withheld numbers say **"no call"** / **"Not calling it"** with a plain reason.
  `test_no_developer_vocabulary_in_buyer_copy` fails the build if any of it leaks back.
- **No real league member is ever named on a public surface.** `engine/backtest.py` aliases
  managers as "Manager A…L" (stable per roster across both tables) and
  `render.report.anonymize_for_public()` relabels the demo report; the live subscriber report
  still names the rival, because it goes only to the person entitled to see it. Guarded by
  `test_no_real_league_member_is_named_on_any_public_page`. Regenerate `site/backtest.html`
  and `site/sample-report.html` through those paths — never by hand.
- **`site/legal.html`** carries terms, renewal, refunds (one per person), privacy, 18+, and
  contact; both funnel pages link it. It is plain-language, not lawyer-reviewed — say so if
  asked, and recommend a real review before scale.
- **No personal contact details ship on the site (owner instruction, Aug 14 2026).**
  `CONTACT_EMAIL` is empty in both funnel pages and `legal.html` says "[contact address —
  added before launch]". With it empty the forms say signups aren't open rather than opening
  a dead `mailto:` that looks like it worked — verified in-browser. Setting a project inbox is
  a **launch blocker**: a paid subscription needs a working route for refund and deletion
  requests. `test_no_personal_contact_details_are_published` blocks any personal address
  (gmail/outlook/icloud/etc.) from re-entering any page under `site/`.
- **The landing page must never present the availability-controlled table as accuracy.**
  backtest.md itself says that table is "a diagnostic, not a result to publish"; the page now
  labels it as a hindsight filter, leads with the unconditional 53.5%, and explains that the
  shipping product's known-active gate has no backtest yet (snapshots start this season).
  Adversarial review caught this being published as five "calibrated" buckets — do not undo it. Phase 3 built the availability feed
(weekly injury snapshots + NFL schedule byes), `engine/week_report.py` (single JSON with every
number gated on its own calibration evidence), and `render/report.py` (template-faithful HTML,
all data escaped). Phase 4: `make week` / `python -m run.week` runs ingest→report→render→text
summary in one command; `.github/workflows/weekly.yml` is the Tuesday cron (activates on push
to GitHub with SLEEPER_LEAGUE_ID + SLEEPER_ROSTER_ID secrets; persists availability snapshots
via actions/cache). Both build phases were adversarially reviewed (12 confirmed findings fixed,
incl. two principle-1 gate bypasses). Demo artifacts from real 2018 sample-league data:
`reports/rival-report-2018-w10-r1.{html,txt}`.

What publishes vs gates (principle 1, wired in code, not prose):
- Slot confidence: publishes only when availability is KNOWN-ACTIVE for both players
  (snapshot + schedule); calibrated regime per backtest (ECE 3.1%, 5/5 buckets).
- Floor/ceiling band: publishes — matchup backtest coverage 77.9% vs 80% target.
- Win probability: GATED (`WIN_PROBABILITY_CALIBRATED = False` in engine/week_report.py) —
  matchup backtest shows it underconfident (stated ~52% bucket observed 64.5%). Un-gate only
  with fresh passing evidence in backtest.md; more seasons of history will firm this up.

Still waiting on TWO things: paste the real league ID at the top of this file, and my roster id
(env SLEEPER_ROSTER_ID). Then `make week` (in season) or
`.venv/bin/python -m run.week --week N` (explicit week) builds my real report.

**Session continuity — read this first if you are picking up on the desktop.**
Phases 1 and 2 were built in Claude Code sessions *other than* the machine I normally
work on, and committed from there on 2026-08-13. Practical consequences:

- **Check the code actually reached this machine before building on it.** The repo had no
  git remote when those commits were made, so they exist only in whichever checkout
  created them. `git log --oneline` should show the Phases 1-2 commit; if it does not, the
  work is in the other environment and needs a remote (or a copy) to get here.
- **Nothing under `data/` is in git** — it is gitignored, ~15 MB of cached Sleeper JSON.
  A fresh checkout has an empty cache, so the first `-m engine.backtest` will fail until
  `-m ingest.pull` repopulates it. That is one real pull against Sleeper; afterwards
  re-runs are 0 HTTP requests again.
- **The venv is not in git either.** Recreate with Python 3.11 and
  `pip install -r requirements.txt` (system `python3` here is 3.9 and lacks `requests`).
- **Git identity was unset** in the session that wrote these commits, so the author line
  may not match my usual one. Set `user.name`/`user.email` before committing from here.
- Everything in Phases 1-2 is verified against Sleeper's **public sample league**
  (289646328504385536), not mine, because the league ID above is still the placeholder.
  Every number in `reports/backtest.md` will change when the real league is pulled.

**Phase 2 headline finding — read before building Phase 3.** The engine's problem is
*availability*, not scoring. Starters score exactly 0.0 3.3% of the time; bench players
34.5% — benching a player is overwhelmingly a statement that he will not play, and cached
Sleeper data contains none of the underlying facts. So when the engine overrules a human it
hits 24% and 57% of the players it wants to promote score zero. Restricted to head-to-heads
where both players actually played, the *same* model is well calibrated: Brier 0.231 vs 0.258,
ECE 3.1%, and 5 of 5 judgeable confidence buckets calibrated (62.1% stated → 63.6% observed;
73.9% → 78.3%), with the top decile hitting 77.2% vs the bottom's 60.5%.

Conclusion: **the probability math passes; wire up an availability feed before publishing any
confidence number** (principle 1). Bye weeks come from the free public NFL schedule; injury
designations are already on Sleeper's player records but must be snapshotted weekly, because
`/players/nfl` only ever holds *today's* status. Until then a slot with unknown status renders
"coming in v0.3", never a number. This also *is* the "where the rival is fragile" feature — a
rival starting a player who will not play is the most exploitable event in the data.

**Data learnings (verified live, Aug 2026):**
- Endpoint shapes on docs.sleeper.com all confirmed against the live API. `/state/nfl` also
  carries `previous_season` — useful for sanity-checking the `previous_league_id` walk.
- `matchups/{week}` includes per-player scoring (`players_points`, `starters_points`), so
  Phase 2 can grade start/sit decisions from cached league data alone — no separate stats feed.
- `transactions/{week}` includes FAAB bids (`settings.waiver_bid`), failed claims, and
  millisecond timestamps — enough for the Phase 2 rival waiver-aggressiveness profile.
- `users[].metadata.team_name` is unset until an owner customizes it — fall back to
  `display_name`. Rosters can have `owner_id: null` (orphaned teams).
- `/players/nfl` is ~14 MB / ~12.2K players; cached daily per Sleeper's guidance.
- Cache policy (post-review): live-season data uses a 6h max-age and never caches empty
  responses (a pre-draft week's `[]` must not freeze); completed-season data never expires and
  caches empties too (an empty championship-week transaction log is final). A cached
  previous-season `league.json` whose status isn't `complete` is revalidated once, so a season
  rollover can't freeze a stale in-season snapshot. Responses are shape-validated before
  caching. Fetch times live in `data/raw/_manifest.json` for data-age flags in reports
  (principle 3).

**Data learnings (Phase 2, verified against 2018+2017 sample-league data):**
- `starters` is **positionally aligned** with `roster_positions` minus `BN` — `starters[3]`
  occupies `starting_slots[3]`. Verified across 1,836 slot-weeks, zero length mismatches.
  An unfilled slot is the string `"0"`. A starter is occasionally absent from `players`.
- A player who did not play is reported as exactly `0.0`, not omitted or null. There is no
  distinct "did not play" flag, so 0.0 is the only absence signal available — used to separate
  scoring form from availability. ~20% of RB/WR player-weeks are 0.0.
- **`settings.waiver_budget` is not trustworthy as a denominator.** Two sample-league managers
  spent 140 and 101 against a stated budget of 100 — commissioners can raise budgets mid-season
  and the setting only reports its current value. Rank managers on raw spend *within their own
  league* instead; a fixed threshold labelled 8 of 12 managers "very aggressive", separating
  nobody.
- `/players/nfl` carries one **current** `injury_status`, with no per-week history. It must
  never be applied to a past season — that would be fabrication (principle 3). Lineup-setting
  lateness is not recoverable at all: lineup changes are not transactions.
- Failed waiver claims are retained in the log with their bid, which reveals a manager's
  intended price, not just what they paid.
- Positions drift: ~10 of 1,836 sample slot-weeks show a player whose *current* position no
  longer matches the slot he filled in 2018. Use `fantasy_positions` ∪ `position` for
  eligibility.
- Measured on this data, the manager start/sit "accuracy" metric (started player beat the best
  bench alternative) runs 68–95% and is **inflated by the same availability asymmetry** — it
  measures engagement, not skill. Do not publish it as a rival's accuracy; points-left-on-bench
  is the honest version and the right basis for the Regret Score.

**Data learnings (Phase 3-4, verified live Aug 2026):**
- NFL schedule lives at `api.sleeper.app/schedule/nfl/{regular|pre|post}/{season}` — public,
  no auth, OUTSIDE /v1 (undocumented on docs.sleeper.com but stable and verified). Byes =
  teams absent from a week's games. Completed-season schedules cache forever.
- Availability snapshots (`data/raw/availability/`) can only be captured live — written on
  every `ingest.pull` from the players table at zero extra HTTP cost. They are the one
  unrecoverable dataset: the CI cron persists them via actions/cache + artifacts.
- "ACTIVE" requires knowing the player is NOT on bye: when the schedule is unavailable, a
  clean injury report classifies UNKNOWN, never active (review-confirmed gate bypass).
- Historical renders must not read the report week's own transaction log (waiver moves made
  after the games = lookahead); live weeks may (all transactions are in the past then).
- The receipts ledger grades only calls that passed the publication gate in their own week —
  not hypothetical engine calls — so it starts exactly when publishing starts.
- Cross-season rival joins go by owner_id, never roster_id (verified: sample-league roster 6
  changed owners between 2017 and 2018).
- A 0.0-vs-0.0 matchup total means "not played yet", never a tie (matchup backtest RULE M1).
- **Sleeper mints a NEW league_id every season**, and the old one keeps resolving forever — out of
  a cache that never expires once a season is `complete`. Nothing in the data marks it stale. So a
  renewed subscriber whose registry entry still carries last year's id renders a **complete,
  confident report about games played twelve months ago**: no gap, no warning, exit code 0. This
  is the quietest principle-3 violation in the codebase and it has no natural alarm, so
  `build_week_report(..., require_season=...)` makes it loud. `run/batch.py` — the only path that
  mails strangers — passes the current season from `/state/nfl`; historical and demo renders leave
  it unset. Re-resolving a subscriber's current league from their stable `user_id` through the
  `previous_league_id` chain each August is the fix that would make this self-healing — **built**,
  in `run/sync.py:roll_season()`. It walks each of the subscriber's current-season leagues back
  through its own `previous_league_id` chain (max 8 hops) looking for the league they signed up
  for. Exactly one match rolls silently; zero or several changes nothing and reports it, because a
  wrong league is worse than a missing one — it looks like it worked. The rival is carried by
  `owner_id` only and its `roster_id` is dropped, since roster ids are not stable across seasons;
  a rival recorded ONLY as a roster number cannot be rolled and the subscriber is asked to re-pick.
