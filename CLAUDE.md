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

- **nflverse** (`ingest/nflverse.py`, `ingest/injuries.py`) — **the licensed source the paid
  product is being rebuilt on.** CC-BY-4.0: commercial use permitted *in exchange for* attribution,
  which makes `ATTRIBUTION` a licence term rather than a courtesy (RULE N1 — ship it or the grant
  does not apply). Releases used: `stats_player` (weekly counted usage — `stats_player_week_{season}.csv`,
  `player_id` IS the GSIS id, so it joins the injury archive with no mapping table), `schedules`
  (`games.csv` → byes), `injuries`, `players`. **RULE N2 — first-party outputs only:** snap counts
  are Pro-Football-Reference-derived and FTN charting is CC-BY-SA, so neither is read; losing snaps
  is cheap because RULE U2 already made them live-only and unbacktestable. Regular season only
  (`season_type`/`game_type` = REG — a POST row at week 10 is a different game). An unknown week
  returns `None` for byes, never an empty set, or the availability gate silently reads "everyone is
  playing". Completed seasons cache forever, the live season on the 6h window, an outage falls back
  to cache and only a cold cache is fatal.
- **Sleeper API** — **BEING REMOVED FROM THE PAID PRODUCT (owner decision, Aug 18 2026).** Rather
  than ask Sleeper for a commercial licence, the dependency goes: NFL-wide data moves to nflverse
  above, and league context (scoring, roster slots, players, opponent) comes from the subscriber
  typing it. `test_no_sleeper_in_the_paid_path` walks the imports reachable from `run/batch.py` and
  fails if checkout is live while any of them still reaches Sleeper — today that set is exactly
  `ingest/sleeper.py`. The historical backtest keeps its Sleeper code deliberately: that is research
  against a public sample league, not a commercial service.
  **PROHIBITED BY SLEEPER'S TERMS OF USE WITHOUT WRITTEN CONSENT — the full verbatim clauses and
  the decision live in PLAN §0.** The docs page says
  non-commercial use only; the *binding* document is Sleeper's General Terms of Use (Blitz Studios,
  Last Updated Jul 24 2026), verified by raw fetch + exact-string match on Aug 18 2026 — a
  summarised fetch of that 145k-char page silently drops these clauses, so check it that way:
  §11.1 bars crawling/scraping and automated access "without the express written consent of
  Sleeper"; §11.3 says **no third-party is authorized** to retrieve data "whether directly, through
  automated means, or through any account… belonging to a user," and that a **user's authorization
  is not Sleeper's authorization**; §11.1 also bars the USER from connecting to a third-party
  product that uses league/roster/transaction/scoring data "for that third-party's commercial or
  business purposes," with §11.2's remedy being termination of **their** account.
  **Engineering consequence: there is no architecture that fixes this.** Browser-side compute, a
  local CLI, an extension, a BYO-data POST, and a subscriber-forked Actions cron were all researched
  and all fail §11.3 — do not propose them as a workaround again. What DOES help is reducing
  surface: move the schedule, weekly stats and projections to nflverse (CC-BY-4.0, commercial use
  permitted with attribution), which removes all three undocumented feeds and leaves only documented
  `/v1` league endpoints. Projections move AFTER launch — swapping them invalidates the band's 77.9%
  coverage evidence until the matchup backtest is re-run.
  This spec previously recorded only "public, no auth" and the whole build proceeded on that
  reading. Nothing technical changes; the rate limit (1,000/min) is far above our handful of calls
  per league per week.
  Public, no auth, JSON: base `https://api.sleeper.app/v1/`. Key endpoints:
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

**The shipping gate, measured (`engine/gate_backtest.py`, Aug 16 2026) — an honest negative
result.** The product publishes a confidence only when both players are confirmed active, and
that rule had never been tested because live availability snapshots start this season. nflverse's
historical injury archive (CC-BY-4.0, plain CSV, joined to Sleeper through `gsis_id`) closes it:
an injury report is published BEFORE kickoff, so conditioning on it is legitimate, unlike the
availability-controlled diagnostic which conditions on both players having scored.
Result on the frozen 2017-18 call set: the gate keeps 1,597 of 2,056 calls (77.7%), and
calibrated buckets go from **1 of 6 to 2 of 5 — an improvement, not a rescue**. Observed rates
barely move (53.3 -> 54.2, 53.0 -> 53.2, 52.6 -> 52.5) and resolution stays flat at a 6.0-point
spread. **So the gate does NOT earn a published accuracy claim and `reports/gate-backtest.md`
makes none.** The reason is the useful part: most of what the availability-controlled table was
really selecting for is not injury at all, it is healthy players who were never going to get the
ball — a backup in a committee carries no designation. Keep the gate as an honesty measure; do
not upgrade the marketing on the back of it. Limits that must travel with the number: byes are
not modelled (a player's historical team is not recoverable from today's players table), so this
is the injury half of the gate only. Reconstructed weeks are written to their own directory and
NEVER into `data/raw/availability/`, which holds only snapshots observed live.

**Counted usage (`engine/usage.py`, Aug 16 2026) — the market's vocabulary, from a feed we
already had.** The report said in print that routes, snaps and target share "isn't something we
track yet"; two thirds of that was closable for free. Sleeper's own
`/v1/stats/nfl/{type}/{season}/{week}` — same public no-auth family as the projections feed,
keyed by Sleeper player id so there is NO id mapping — carries `rec_tgt`, `off_snp`,
`rec_air_yd`, `rec_rz_tgt` and `rush_att`. `ingest.pull` caches it per week alongside matchups
(completed seasons forever, live season on the 6h window) and a failure there is swallowed:
usage enriches the report, it is never load-bearing.
Two rules, measured not assumed, against rostered skill players who actually played:
- **RULE U1 — reported, never projected.** Every value is a count of something that already
  happened, so it carries no calibration burden. Using one to PREDICT needs its own backtest.
- **RULE U2 — snaps are live-only.** `off_snp` is 100% populated for 2024 and **0% for 2018**, so
  a snap figure can ship in a live report but can never be validated against the 2017-18 call
  set. Targets (81%/66%) and air yards (76%/66%) exist in both eras; the shortfall there is
  rushers and QBs with no receiving line, an honest zero rather than a hole.
An absent field renders absent, never as 0, and weeks the player did not play do not dilute the
per-game rate — that would understate exactly the returning starter worth flagging. The hype
verdict gate no longer claims we track nothing; it now shows what he was given and withholds
only the part we genuinely cannot judge (whether it holds up behind a different offence).

**Units: points lead, dollars act, probability supports (Aug 16 2026).** A 64% call and a 58%
call feel identical to a human, and the backtest says we may not be entitled to that precision
anyway — unconditional resolution is nearly flat (least-confident decile 55.2%, most-confident
55.7%). So the report now leads with magnitudes a manager has spent years calibrating:
- `matchup.margin` + `matchup.margin_swing` — the gap and how far the week actually moves. They
  are serialised together and a test fails if either ships alone: the sample week's gap is 5.3
  against a swing of ±53 (z·sqrt(sd_you²+sd_rival²)), so a bare gap in a verdict colour would
  claim with size what the gated win probability refuses to claim in words. No odds word may be
  attached — the matchup backtest found favourites won MORE often than stated.
- `matchup.as_set_total` / `swap_value` — what doing nothing costs. The report used to say the
  optimal lineup wins by 5.3 and never that the lineup as set LOSES by 3.1. Both totals must
  pass `_team_range`'s gate or neither is quoted (a partial sum is a fabricated total).
- `lineup[].edge` / `alternative_projected` — computed on every SlotPick and previously never
  serialised. The point gap does not depend on availability, so a gated row carries it honestly;
  nine rows reading only "no call" was withholding something that never needed withholding.
  The number sits in the narrow column, the name it beats in the 1fr player column — a real name
  in a 62px cell grows every row to three lines and the grid stops reading as a table.
- Counts carry denominators (`hype[].league_others`): "8 of the other 11 teams can cover that".
- The checklist DECIDES rather than asking — "Skip Mike Davis (RB), it takes 18 and you have 10"
  rather than "Decide on Mike Davis", since the engine already knew the answer.
Kept deliberately: the confidence NUMERAL. Coarsening it to labels ("clear call" / "lean") was
rejected on a structural ground, not taste — `engine/ledger.py` grades probabilities, and a word
records nothing gradeable, so labels would silently destroy the receipts ledger, which is the
only mechanism that can turn the shipping availability gate into measured evidence.

**The Tape — one grid, not two (Aug 17 2026).** Sections 03 and 04 were your nine slots and then
their nine slots, stacked, so comparing a slot meant holding your RB in your head while scrolling.
Sleeper's own matchup screen — the one this buyer already lives in — is a centre spine with no
prose at all. `section_tape()` in `render/report.py` and `_tape()` in `render/email.py` render one
row per slot (your player | position | their player) with the leading half tinted; **the tint is
the verdict, so no sentence restates the grid**. Rules that travel with it:
- **One bench player is the fix for exactly ONE slot** (`_assign_alternatives`, engine). Picking
  each rival slot's best alternative independently named the same benched receiver at WR, WR,
  FLEX and FLEX — four exploitable spots where the roster held one, and he cannot start twice.
  Greedy by gain, ties broken on ids so a report is byte-identical across runs. This inflated the
  fragile-spot COUNT, which is why `section_fragility` had been grouping the duplicates back into
  one sentence. MY side is deliberately unchanged: "confidence = beats the best bench alternative
  **at that slot**" is the calibrated unit, so per-slot independence is its definition, not a bug.
- **"no call" renders per row only in a MIXED week.** Where some rows carry a percentage, silence
  on the others reads as a call we forgot; where NO row does, nine identical markers say nothing
  the note under the table does not say once, with the reason (the note's head switches too).
- The rival half may carry a fragility flag — that is the product — but never a confidence, a
  gate note, or our per-row point gap. Pinned by `test_the_rival_grid_carries_no_calls_of_any_kind`.
- `edge_phrase()` is shared by both renderers, like `who_can_cover()` before it. They had written
  the same fact in different words and the email's longer form wrapped every row onto two lines.
- **`make demo` is the only way to rebuild the sample.** It was ad-hoc commands, which is how the
  published demo came to be re-rendered from a stale `week_report.json` — engine fixes never
  reached it. The target runs `engine.week_report` first, then `render.report --public`
  (anonymize_for_public), the local pair, and the plain-text summary.
- **Both halves carry availability flags.** `optimal_lineup` deliberately seats an OUT player when
  nothing eligible remains (a bye-week DEF is routine), so reading `flags` on the rival branch only
  meant we flagged THEIR unavailable starter and rendered yours as a clean projection, tinted as
  winning the slot. After the merge, my-side flags had no render surface at all.
- **The two halves are the same width, via a `<colgroup>`** whose widths live in the template CSS.
  `table-layout:fixed` alone reads its widths off the header's `colspan`; inline `<col>` styles beat
  the mobile media query and clipped "123.2" out of both points columns at 375px.

**A 28-agent adversarial audit (Aug 17 2026) — 16 confirmed, 5 refuted.** Findings worth keeping
as rules, beyond the Tape items above:
- **Section numbers come from POSITION** (`number_sections()`, both renderers). Hardcoded per
  section, the sequence was only correct until one was added or merged: last week's result
  duplicated 02 and the Tape took 04 and orphaned 03, so the shipped report, the email and the
  sales page all read 01, 02, 02, 04. Pinned contiguous with and without the last-week section.
- **My own report must never gate a subscriber's.** A `weekly.yml` step with no `if:` defaults to
  `if: success()`, so any non-zero exit from `run.week` skipped sync AND send for everyone while
  `run.batch` was perfectly able to run. `if: always()` on both; the job still goes red and still
  files the issue.
- **Dry-run is the right default and never the right accident.** With `EMAIL_PROVIDER` unset,
  `run.batch` wrote drafts to an ephemeral runner, printed "N sent" and exited 0. It now prints
  NOTHING WAS SENT and exits 1 unless `--allow-dry` (what `make dry-send` passes).
- **`STRIPE_PAYMENT_LINKS` is not a filter.** It doubled as the Stripe sweep's query filter, so a
  tier missing from the map was never swept — that buyer paid, never entered the registry, never
  got a report, kept being charged. `sweep_stripe` always ends with an unfiltered query;
  `seen_sessions` dedupes and the plan still comes from the session's own `payment_link`.
- **Seat timestamps are stamped on receipt, not read from the row.** The seat form is public, so
  `added_at` is attacker-supplied: "9999-12-31" outranks every later seat for that key forever and
  a member re-picking their rival silently never takes effect. `event_key` ignores timestamps, so a
  seat already logged keeps its first-seen stamp and the sweep stays idempotent.
- **The League Pass seat link appears on the way to Stripe, not at league-pick.** Shown at step 2
  it was shareable before checkout, so an abandoned payment left eleven managers each told their
  seat was claimed while every claim is dropped on Tuesday. The seat holder is now told their
  request is in and depends on the pass.
- **Every figure a "Real find" card quotes must exist in the published sample** (`test_site.py`).
  The landing page is hand-written and the report is generated, so they drift: the page advertised
  "above four of their set starters" for weeks after the engine stopped producing that count.
- **`reports/backtest.md` may not promise what the gate backtest disproved.** It said "a stated 64%
  is worth publishing once the engine knows who is playing"; the gate has since been measured on
  exactly that population (1 of 6 → 2 of 5, rates nearly unchanged). Improvement, not rescue.
Deliberately NOT fixed: `_assign_alternatives` is greedy, not maximum-weight matching, so it can
report one fragile spot where an optimal pairing exposes two. It errs toward under-claiming, which
is the safe direction; revisit post-launch.

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
**A dry run records NOTHING in `data/processed/sent.jsonl`** — found by running the delivery
path end to end. `send_all` used to log every successful send including the dry provider, so
`make dry-send` (documented as a safe preview) marked every subscriber as already sent and the
real send then skipped them all: a green run with empty inboxes. It applied to the cron too,
which runs dry until `EMAIL_PROVIDER` is set, so the first real send would have skipped
everyone the dry runs had "sent". Both halves are now tested: dry drafts every time and logs
nothing; a real provider logs once and skips on re-run.
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
- **The receipts page is demoted at launch, not deleted (owner decision, Aug 16 2026).** The
  ledger was the site's designated proof asset — hero pill, ~14 buyer-visible mentions, five
  outbound links — pointing at a page whose stamp read "NOTHING TO HIDE · YET NOTHING TO SHOW".
  Worse, "Judge us on the record, then decide" sat between the honesty section and the pricing:
  a verbatim instruction not to buy, aimed at a record that does not exist. **A call needs three
  prior appearances from both players (`MIN_GAMES_FOR_CALL = 3`), so weeks 1-3 publish no
  confidences at all and the first rows cannot be graded before early October** — the Week-2
  refund window closes before a single row exists. Any copy promising September grades is false.
  So: the machinery, the page, the principle and the footer link all stay; the ledger stops
  being the launch proof and the **backtest** becomes it (it is the thing a buyer can check
  today). Buyer-visible mentions went ~14 -> 1, miss-vocabulary 6 -> 0. Promote it back into the
  funnel once it holds real rows. The public noun is now **"the receipts"** — the buyer's
  group-chat word aimed at their rivalry, not an accounting word aimed at our honesty; it also
  matches report section 09, Receipts Monday and the receipt cards. Kept exactly one honesty
  statement ("No moving the goalposts", frozen rules) per the state-once-then-demonstrate rule.
  **Do not "fix" this by quoting the availability-controlled calibration numbers** (62.1% ->
  63.6% etc.): backtest.md calls that table a diagnostic, not a result to publish, because it
  conditions on an outcome unknowable at call time. The publishable calibration is the weak one
  (ECE 7.2%, 1 of 6 buckets), so the honest sellable claim is the **discipline** — we found the
  availability blind spot ourselves and switched the number off there.
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
- **`site/backtest.html` is GENERATED from `reports/backtest.md`** by
  `render/backtest_site.py` (`make backtest` runs both; `python -m render.backtest_site --check`
  fails if the page is stale, and a test asserts generator output == published page). It used to
  be hand-maintained under a header claiming "never hand-edited", and it drifted — the published
  page carried a generation timestamp older than its own source. `verify()` refuses to publish if
  any figure in the source is missing from the page, if the failing `off` buckets vanish, or if an
  ordered list would be silently renumbered by `<ol>`. It publishes `reports/backtest.md` whole — failing buckets, 53.5%
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
- **`render/email.py` is what actually lands in the inbox (Aug 16 2026).** The browser
  report leans on grid/flex/`var()`/loaded fonts — Outlook renders email with Word's engine and
  Gmail strips `<style>` on forward, so mailing that file shipped soup. The batch now mails a
  table-based, inline-styled, web-safe rendering of the same `week_report.json`; it must be
  self-contained because per-subscriber reports are private (no hosted copy to link). Every
  pinned sentence — cancel/unsubscribe distinction, no-betting, data-age basis, the as-set
  explainer — is a shared constant in `render/report.py` imported by both renderers, so the two
  surfaces cannot drift. The browser HTML still goes to disk as the archival artifact.
  Mutation-tested: rewiring batch to mail the browser HTML fails the suite.
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
- **Section markers are `01`-`09`, never `§n`.** The section sign is legal/academic citation
  register — wrong for a fantasy product, and it reads as a flourish rather than a design
  element. Zero-padded numbers read like a case file, which is the register the product sells
  ("the file on Mike", "this buys the scouting file"). Set in `render/report.py` and mirrored in
  `rival-report-template.html`. Prose never cites a section number at all (an earlier pass had
  already stripped `§`-references from action items as legalese, and they dangle in the
  plain-text email, which has no sections) — name the section instead: "the matchup section".
- **Money is disclosure, never argument (owner direction, Aug 15 2026).** The
  high-probability buyer is not making a logical money decision — they are buying
  reassurance (due diligence done without becoming the spreadsheet guy), absolution (the
  defensible call, receipts if it goes wrong), and identity (the manager with the file).
  Price-justification math ("under $2 a week", "about $40 across a season", "the cheaper
  road") primes analytical thinking, and analytical buyers defer. So: prices appear plainly
  at decision points and in the legally required disclosures (renewal amounts, refund
  terms) — and are never argued, itemized per-unit, or compared. The ONE exception is the
  League Pass page: a commissioner justifying spend to eleven leaguemates is a genuinely
  deliberative buyer, and the $348-vs-$99 arithmetic is their language. Emotional value is
  sold through specific scenarios in the buyer's own life (Tuesday morning, the group chat,
  the call you would have regretted), never through adjectives — and never through invented
  behavior claims ("most people..."), because there are no customers to cite yet.
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

**Data learnings — Sleeper projections feed (verified live Aug 2026):**
- `/v1/projections/nfl/{type}/{season}/{week}` — public, no auth, Rotowire-sourced,
  OUTSIDE the documented API but stable (same family as the schedule feed). Serves
  historical seasons, which is what made `engine/projections_eval.py` possible: the feed
  was graded on the frozen 2018 call set BEFORE any adoption decision (principle 1).
- **The archive's usable universe is a fixed ~400-520 players per week in every era**
  (2018: ~513, 2022: 383, 2024: 370, 2025: 383). Every other record is a husk holding only
  `adp_dd_ppr` — including 2018 Derek Carr, all 17 weeks. 2017 is entirely husks. A husk
  must parse as "no projection", NEVER as 0.0 points (`feed_points`, mutation-tested).
- Not survivorship-filtered: 85 of 513 usable 2018-w10 records are players inactive in
  2026, and 8,139 currently-active players are husks.
- Eval verdict (reports/projections-eval.md): on 368 identical head-to-heads the feed hit
  68.8% vs the model's 64.4% (McNemar p=0.089 — suggestive, not conclusive), better
  MAE/RMSE, and it projects most week-1 starters where trailing-form is structurally
  silent. But it had NO OPINION on 626 of 994 calls, so it can only ever be a BLEND (feed
  where it speaks, trailing-form fallback). Blending invalidates the band's 77.9%
  coverage evidence — re-run the matchup backtest under the blend before the band
  publishes on feed numbers. Feed points are computed from stat lines x the league's own
  `scoring_settings` (2017-style husks and non-PPR leagues both demand it), never from
  the pre-baked `pts_ppr` fields.

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
