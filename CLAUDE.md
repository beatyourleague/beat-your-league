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

**Status:** Phases 1-4 complete + Phase 6 subscriber mechanism built early (147 tests passing).
Phase 6 mechanism: signup picker (`site/join/`, live-tested against real Sleeper accounts —
username → leagues → own-roster auto-resolved → rival tapped from real team names), subscriber
registry (`run/registry.py`, gitignored data), batch runner (`python -m run.batch`: one ingest
per league, one report per subscriber, failures contained per-subscriber), and the Rival Watch
strip (named rival tracked weekly; Rivalry Week when the schedule pairs you). Remaining for
launch: plug a free-tier form backend endpoint into the picker (mailto fallback works today)
and connect the Substack list. Phase 5 (content system) is untouched and next in order. Phase 3 built the availability feed
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
