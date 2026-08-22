<!-- PREREGISTRATION. Committed BEFORE any number was computed, which is the
     whole point: CLAUDE.md principle 2 says grading rules are defined before
     the season, in code, and never adjusted after results. Changing anything
     below after reading an output voids the run.

     Three of its load-bearing claims were verified independently against this
     repo before adoption, and are recorded here with what was found:

     1. "all_calls yields 0 calls on a subscriber-shaped Season" — VERIFIED by
        running it. engine/subscriber.py sets starters=(), and decisions.py
        breaks out of the slot loop immediately. The harness must therefore
        drive optimal_lineup directly.
     2. "15.4% of fantasy rows score exactly 0.00" — VERIFIED at 15.2% on 2024
        (WR 20.5%, TE 21.7%, RB 12.4%, QB 1.2%, K 1.3%). 9.9% of all rows carry
        no recorded touch, so roughly 5 points of that is players who were on
        the field. RULE B1 currently reads every one of them as "did not play".
     3. "row-presence is a clean appearance signal" — VERIFIED: the maximum REG
        rows any 2024 fantasy player has is 17 in an 18-week season (a season
        minus the bye), and no player has more. No duplicates to confuse it.
-->

I have verified every load-bearing claim against the code and the cached data. Here is the frozen method.

---

# FROZEN METHOD — re-measuring the published confidence on nflverse

**Status: preregistration. Written before any number is computed (CLAUDE.md principle 2).**
Target module `engine/nflverse_backtest.py`; output `reports/nflverse-backtest.md`.
Nothing below may be changed after the first output is read. Changing anything voids the run and requires a new preregistration with a new commit.

**Why this exists, in one sentence:** `engine/subscriber.py:49-55` states that the point source and the prior population both changed, so the evidence in `reports/backtest.md` does not transfer — and until this run lands, every confidence numeral the product prints is unsupported by any nflverse measurement.

---

## 1. THE PUBLICATION RULE (written first, on purpose)

All quantities are computed at **seed 0, headline configuration, pooled across all graded seasons**, using the **clustered** intervals of §8. Definitions:

- **J** = buckets (`engine/calibration.py:24` `DEFAULT_EDGES`, unchanged) with ≥ 30 decided calls (`:74`).
- **C** = of those, how many contain their stated mean inside the clustered 95% interval.
- **ECE** = `expected_calibration_error` over those buckets (`engine/calibration.py:144`).
- **R** = top-decile hit rate − bottom-decile hit rate, in points (`engine/calibration.py:160`).
- **Stability** = max−min of C across the 20 preregistered seeds; and C under each preregistered arm (§9).

| Grade | Condition (all clauses required) | What the product may claim |
|---|---|---|
| **A — calibrated** | J ≥ 4 **and** C = J **and** ECE ≤ 3.0% **and** R ≥ 10.0 pts **and** seed stability ≤ 1 **and** every arm returns C ≥ J−1 with ECE ≤ 4.0% | A **bucket-level** claim, with the §12 disclosures in the same visual block. Never a headline accuracy percentage. Never a comparison to a human manager. |
| **B — measured, unproven** | J ≥ 4 **and** C ≥ ⌈J/2⌉ **and** ECE ≤ 5.0% **and** R ≥ 5.0 pts | The measured figures may be **stated as facts** (n calls, ECE, which buckets failed) in the same sentence as the failures. No word from the banned list below. |
| **C — no claim** | anything not A, B, or D | The numeral still prints, as a **recorded prediction only**. Every accuracy implication is removed from every surface. |
| **D — no confidence at all this season** | R ≤ 0 **or** any judgeable bucket whose clustered CI **upper** bound < 0.50 **or** the gate cannot be evaluated on the publication-time information set (§6) | `may_publish_confidence` returns False unconditionally for the season. The report prints points gaps, availability facts and counted usage only. `reports/nflverse-backtest.md` says so, `site/index.html` says so, and the ledger records nothing for confidence. |

**Banned at grades B, C and D, on every surface:** "calibrated", "tested", "proven", "accurate", "we hit X%", and any reuse of the availability-controlled row set (62.1% → 63.6% and its siblings). CLAUDE.md already carries this as a standing order; this run does not lift it.

**At every grade, these are unaffected and remain publishable**, because they are arithmetic on events that already happened rather than forecasts: counted usage (RULE U1), `hype[].league_others` counts with denominators, fragility flags, availability and data-age lines, `matchup.margin` / `margin_swing` / `as_set_total` / `swap_value`, and `lineup[].edge`.

**Per-surface mapping**

| Surface | A | B | C | D |
|---|---|---|---|---|
| `render/report.py:120-125` `no_call_explainer` | may add one calibration sentence | definition + "every one goes on the public record and gets graded" | same as B; delete "otherwise we'd be guessing, and you can guess for free" (it asserts a shown number is not a guess) | replaced by the no-number explanation |
| `engine/week_report.py:68` `TEAM_RANGE_BASIS` | governed by §10.8, not by this table | " | " | " |
| `site/index.html:806-822` (lede + 5-row table) | table replaced by the **new** bucket table with the simulation caption | lede rewritten to the measured result; **the 5-row availability-controlled table is deleted regardless of grade** | as B | as B, plus an explicit statement that no confidence ships |
| `reports/backtest.md` | gains a header: this document describes a data stack the product no longer runs | " | " | " |
| `site/backtest.html` via `render/backtest_site.py:42` | `SOURCE` repointed at `reports/nflverse-backtest.md`; `verify()` applies to it | " | " | " |
| ledger page | individual graded rows + raw counts; aggregate rate only once a bucket clears 30 decided | same | same | nothing to record |

**Win probability is out of reach of this run, at every grade.** `engine/week_report.py:60` stays `False`. The published unit is "P(your total beats **their set lineup's** total)", and `engine/subscriber.py:42-47` (RULE B3) says we no longer see any rival's lineup — so no source exists to compute it live or to grade it, and a simulated opponent whose lineup we set optimally is a different quantity wearing the same name (`engine/matchup_backtest.py:23-25` is explicit that grading against *actual set* lineups is what made the old number worth anything). Consequence to act on: `WIN_PROBABILITY_GATE` (`:62`) currently implies a retest is pending. It is not pending; the copy should say we would need lineups we cannot get.

---

## 2. THE UNIT

**Confidence N% = P(the player this report seats at a slot outscores the best eligible alternative left on the bench at that slot), under our model, conditioned on the two not both failing to play.**

The graded pair is produced by calling **`engine/week_report.py:102 optimal_lineup` itself** — not a reimplementation — and taking, for every `SlotPick` with `confidence is not None`, the pair `(pick.player_id, pick.alternative_id)` with `pick.confidence`, including the RULE 3 flip at `:199-208`.

Two consequences, frozen:

1. **`engine/decisions.py:209 all_calls` may not be used.** `engine/subscriber.py:274` sets `starters=()` and `engine/decisions.py:143-144` breaks out of the slot loop immediately. **Verified by running it: a subscriber-shaped `Season` yields exactly 0 calls.** The harness reuses `engine/decisions.py:109 grade` and the `StartSitCall` record, nothing else from that module.
2. **The estimand changed and is not comparable to the published one.** `reports/backtest.md:14` graded *a human's actual starter* against the model's best bench option. This grades *the model's first choice* against *its own second*. Manager-derived fields (`agreed_with_manager`, `disagreements`, `manager_points_left_on_bench`) are not computed and not reported.

---

## 3. THE POPULATION

**Seasons graded: 2014–2024 inclusive (11).** Field for season S is built from S−1, so stat releases 2013–2024 and injury releases 2014–2024 are required. The window is frozen now; it may not be extended, trimmed or reordered after any output is read.

**The universe for season S is built entirely from `stats_player_week_{S-1}.csv`.** `data/raw/nflverse/players.csv` is **never read by this harness**. That single decision eliminates four leaks at once (§11: L1–L4).

- A player enters season S's universe iff he has ≥ 1 REG row in S−1.
- His **name** and **position** come from his **last REG row in S−1**. Fixed for the whole of season S, knowable before week 1.
- FB maps to `{RB, FB}`, exactly as `engine/subscriber.py:125-135` does live.
- Team defenses come from `ingest/nflverse.py:256 season_teams(S)` as `DEF-<abbr>`. They are unscoreable (`engine/scoring.py:26-32`, `engine/subscriber.py:282-290`), so they occupy roster spots and produce **zero calls**. This is reported, not hidden.

**Field:** `engine/subscriber.py:219 rosterable_field` called unchanged, with the prior-season mapping and the arm's depth multiplier. The harness **asserts** the mapping's season is S−1 and every row is REG — `rosterable_field:240-243` sums whatever it is handed and checks neither.

Measured for S=2024 (PPR, 12 teams, template T1): field 276 = RB 72, WR 72, TE 48, QB 24, K 24, DEF 24, FB 12. Marginal prior-season points at the cut: QB 149.7, WR 95.7, TE 48.4, RB 42.8, K 121.0.

**Rosters — positional serpentine allocation.** For each position, walk that position's ranked field list dealing seats 1…12, 12…1, 1…12 …. Seed *s* permutes the seat order independently per position via `random.Random(s * 1000 + position_index)`.

- This **exactly partitions** the field: 276 = 12 × 23, verified.
- No draft-strategy parameter is introduced, because a global snake with need heuristics would be one more unvalidated knob.
- **A seed re-pairs; it does not add data.** More leagues from one field are re-partitions of the same player-weeks. Sample comes from **seasons**, never from seeds. Enforced in §8.

**The Season object carries the 12 rosters and nothing else.** `engine/subscriber.py:138 build_season` is **not** used: it always adds a `FIELD_ROSTER_ID` team alongside the subscriber, and with 12 rosters already partitioning the field that would double every player-week — the documented failure at `engine/subscriber.py:166-174` (doubled `games`, players pushed past `MIN_GAMES_FOR_CALL`, halved standard deviation). The harness builds `TeamWeek`s directly with `engine/subscriber.py:260 _team_week` and **asserts `max(rostered_weeks) ≤ number of graded weeks`**. Verified in a dry run: max = 16 over weeks 1–16.

**Lineup templates (frozen):**
- **T1 — headline:** `QB RB RB WR WR TE FLEX K DEF`. The product's default shape; DEF contributes 0 calls.
- **T2 — band only:** `QB RB RB WR WR TE FLEX K`. `engine/week_report.py:339 _team_range` gates on filled picks lacking projections but silently **drops an unfilled slot from the total**, so under T1 the "team total" would be 8 slots quoted under a 9-slot band. T2 makes the total a real total. *The T1 behaviour is a defect the run must report as a finding.*

**Graded weeks: 4 through 16.**
- Weeks 1–3 are arithmetically impossible: `MIN_GAMES_FOR_CALL = 3` (`engine/projection.py:46`) needs three prior appearances. This is not a choice.
- Weeks 17–18 are excluded from the headline (fantasy seasons are over; week-18 resting is a different population) and are **computed and reported separately** so nothing is hidden.
- REG only, asserted on every row read (`ingest/nflverse.py:213`, `:243`). `ingest/injuries.py:102-115` does **not** filter `game_type`; the harness asserts injury weeks ≤ 18 and drops anything else.

**League size: 12 headline; 10 and 14 as arms. Scoring: PPR headline; half-PPR and standard as arms.**

Sizing, measured on a 2024 dry run (availability forced open, weeks 4–16, one league): **1,132 calls, 1,132 distinct (player, player, week) triples, 0 repeats.** At the gate's historical keep rate that is ≈ 880/season → ≈ 9,700 headline calls across 11 seasons.

---

## 4. WHAT IS PROJECTED FROM WHAT

`engine/projection.py ProjectionModel`, unchanged, one model per (season, arm). Every lookup already filters on `before_week` (`:222-233`, `:235-268`, `:295`). No model parameter is fitted or tuned in this exercise: `DEFAULT_SHRINKAGE_K = 4.0` (`:42`), `MIN_GAMES_FOR_CALL = 3` (`:46`), `MIN_SD = 2.0` (`:50`), `DEFAULT_APPEARANCE_RATE = 0.80` (`:62`) are frozen at their shipped values.

**One change is made to the shipping path before the run, on data-fidelity grounds, and the run measures the changed path.**

`engine/subscriber.py:266-268` collapses "no nflverse row" and "a row scoring exactly 0.00" into the same `0.0`, and `engine/projection.py:204-210` then reads `0.0` as "did not appear". Under Sleeper that conflation was forced by the feed. Under nflverse it is a knowing falsehood about a measured share of rows:

| | rows | score exactly 0.00 | |
|---|---:|---:|---|
| WR | 2,441 | 500 | 20.5% |
| TE | 1,223 | 265 | 21.7% |
| RB | 1,536 | 191 | 12.4% |
| QB | 664 | 8 | 1.2% |
| K | 543 | 7 | 1.3% |
| **all fantasy positions, 2024** | **6,478** | **999** | **15.4%** |

Only 10.2% of rows carry no recorded touch at all, so most of those zeros are players who were on the field. The misread is **position-dependent** (appearance rate gap: WR 11.8pp, TE 11.6pp, RB 7.2pp, QB 0.6pp, K 0.9pp) and **preset-dependent** (15.4% PPR vs 15.7% standard — the same player-week is "absent" in one subscriber's league and "present" in another's).

Row-presence is a clean signal: **the maximum rows any 2024 player has is 17 in an 18-week season** — a full season minus the bye.

**Frozen:**
- **Appearance = an nflverse REG stat row exists for that player-week.** Carried on the `TeamWeek` as an explicit appearance record; `ProjectionModel` derives `_rostered` from `team_week.players` (roster membership) and `_appearances` from the appearance record — never from a points value.
- **`players_points` stays complete, absent = 0.0**, so grading and `TeamWeek.actual_points` are unchanged. This matters: `engine/decisions.py:159-161` skips candidates whose actual points are `None`, which would reintroduce an outcome-conditioned filter on alternative selection. `optimal_lineup` selects on projections only and never touches actual points, so it is immune — and the harness keeps it that way.
- The old convention runs as **arm A**, to quantify the distortion the published evidence carried. Neither may be swapped after results.

---

## 5. THE DECISION, STEP BY STEP

For each (season S, week W ∈ 4…16, roster r ∈ 1…12):

1. Build `WeekAvailability` for (S, W) per §6.
2. `picks = optimal_lineup(season, team_week, model, players, availability)`.
3. Every pick with `confidence is not None` is one **call**: recommended = `pick.player_id`, alternative = `pick.alternative_id`, confidence = `pick.confidence`.
4. Actual points = `engine/scoring.py:109 score(row, rule)` where a REG row exists for (S, W, player), else `0.0` — a player who did not play produced nothing in a real lineup, and that is what a real manager's slot scored.
5. Outcome = `engine/decisions.py:109 grade(...)`: HIT / MISS / TIE, ties excluded from hit rates and reported separately.
6. Recorded as a `StartSitCall` so `engine/calibration.py` consumes it unchanged.

**Pairs are not deduplicated.** In one roster-week the same bench player can be the alternative at several slots — the correlation `engine/decisions.py:24-30` warns about survives, and it is handled in the intervals (§8), not by discarding calls. The per-slot pair *is* the published unit. The dry run confirms `optimal_lineup` produces no duplicate `(a, b, week)` triples, because the seated player differs per slot; the shared *alternative* is the correlation, and it is measured and reported (§10.3).

---

## 6. THE AVAILABILITY GATE — reconstructed on the information set that exists at publication time

`engine/availability.py:123 may_publish_confidence` is called unchanged, through `optimal_lineup:198`. The `WeekAvailability` fed to it is reconstructed as:

- `bye_teams` = `ingest/nflverse.py:226 bye_teams(cache, S, W)` — the schedule is published before the season. Byes are therefore **fully modelled**, which closes the limitation `reports/gate-backtest.md:10` had to disclaim.
- `statuses[pid]` = `{"team": carry-forward team, "position": pos, "active": True, "injury_status": designation or None}` for every player on that roster whose team is known.
- **Carry-forward team** = the team on his most recent REG stat row **strictly before W**, within season S. No prior-season fallback. A player with no such row is **omitted from `statuses`**, which makes `classify` return UNKNOWN (`engine/availability.py:76-79`) and gates the call. Fail-closed.
  - This costs nothing on the graded population: `MIN_GAMES_FOR_CALL = 3` already requires three prior appearances, and an appearance implies a row, and a row carries a team. Measured: 95.7% of week-2+ fantasy player-weeks have a team recoverable from a strictly earlier week; the graded subset is 100% by construction.
- **Designations** come from `ingest/injuries.py:92 load_weeks`, joined on GSIS id with no mapping table (RULE N3, `ingest/nflverse.py:31-35`). A player absent from the report is ACTIVE — an injury report lists who is in doubt, not who is fine (`ingest/injuries.py:44-48`). Note `ingest/injuries.py:18-27` forbids handing a report-shaped snapshot to `engine/availability.py`'s loader; the harness therefore builds the `statuses` map itself, for *every* rostered player, with the correct inversion.

**The designation used is the one from week W−1, not week W.** This is the single most consequential rule in this section and it is new. The product ships **Tuesday** (`.github/workflows/weekly.yml`, CLAUDE.md), and week W's injury report is published Wednesday–Friday. `engine/gate_backtest.py:100` keys on `call.week`, so `reports/gate-backtest.md`'s 77.7% describes an information set the Tuesday product does not have. Using it here would be lookahead relative to publication.

- **Headline: the W−1 report** — the shipping gate.
- **Arm D: the W report**, labelled *not available at publication time*, computed only to price a later send slot. It may never be quoted as the shipping gate.

**Also frozen:** the live product currently snapshots availability from Sleeper's players table (`ingest/availability.py:1-13`, `:59-64`), which is the feed being removed. The live gate must be rebuilt on **nflverse injuries + schedule byes** — the same two sources this reconstruction uses. That is what makes this measurement transfer at all, and it is a launch dependency, not a nicety. If the nflverse injuries release cannot supply the completed W−1 report by Tuesday of week W, the live gate cannot run and **Grade D applies**.

**The availability-controlled table is not computed by this run at all.** `reports/backtest.md:46` calls it a diagnostic, not a result, because it conditions on both players having scored. Recomputing it invites exactly the misuse CLAUDE.md's standing order forbids. Its honest replacement is §10.10.

---

## 7. WHAT IS EXCLUDED, AND WHY

| Excluded | Reason |
|---|---|
| Weeks 1–3 | `MIN_GAMES_FOR_CALL = 3` makes a call impossible. Arithmetic, not a choice. |
| Weeks 17–18 | Fantasy seasons are over; week-18 rest is a different population. **Reported separately.** |
| PRE / POST rows | A week number means a different game (`ingest/nflverse.py:204-207`). Asserted. |
| DEF calls | `engine/scoring.py:26-32` deliberately does not score DST. The slot exists; the calls are zero; both are reported. |
| The availability-controlled split | §6. |
| Manager-comparison metrics | There is no manager. `reports/backtest.md:161` already bans publishing the human accuracy column; under simulation it would be a fabricated opponent. |
| Win probability | §1. No rival set lineup exists (RULE B3). |
| Snap counts | RULE N2 (PFR-derived) and RULE U2 (live-only, unbacktestable). |

---

## 8. STATISTICS

- **Headline = seed 0, pooled over the 11 seasons.** Seed 0 is preregistered; picking a seed after seeing ECE would be selection.
- **Clusters = (season, week)**, 11 × 13 = 143. This absorbs the shared-alternative correlation inside a roster-week and the same-game correlation across rosters.
- **Cluster bootstrap:** 2,000 resamples of clusters with replacement, `random.Random(20260821)`. Per-bucket 95% interval = the 2.5/97.5 percentiles of the bootstrap hit-rate distribution.
- **Verdicts use the clustered interval.** `wilson_interval` (`engine/calibration.py:77`) is printed alongside for comparison, and **any bucket where the two verdicts disagree is reported as undecided and counts against C.** A per-call Wilson interval over correlated re-pairings reports precision that does not exist.
- **Seed spread:** seeds 0–19, all run, reporting min / median / max of hit rate, ECE, C, and R. If C varies by more than 1 across seeds, bucket verdicts are declared unstable and Grade A is unreachable.
- **Effective sample is reported explicitly:** raw call count, distinct (a, b, week) triples, distinct players, cluster count, median calls per cluster. If those diverge badly the intervals are decoration, and the report says so.

---

## 9. PREREGISTERED ARMS (all run, all published; arms only downgrade, never promote)

| Arm | Varies | Values (headline in bold) |
|---|---|---|
| A | appearance signal | **row-presence**, 0.0-means-absent (the shipped Sleeper-era convention) |
| B | bench depth multiplier at `engine/subscriber.py:254` | 1.5, **2.0**, 3.0 (1.0 is degenerate: no bench, no alternative, zero calls) |
| C | scoring preset | **ppr**, half_ppr, standard |
| D | gate information set | **W−1 report**, W report (diagnostic only, §6) |
| E | league size | 10, **12**, 14 |
| F | positional prior | **as shipped** (`engine/projection.py:245-256` includes the player in his own prior), leave-one-out |

**Claim scoping is mechanical:** a claim may be shown only for the presets and league sizes that *individually* reach the required grade. If PPR passes and standard does not, the claim renders for PPR subscribers only, via an explicit map in code. If an arm flips a bucket verdict, the verdict belongs to that parameter and not to the model — Grade A is unreachable and the report says which parameter decided it.

Arms F and A are diagnostics about *our own choices*: if either materially moves the verdict, that is a model change to be made and then re-measured, and it does not retroactively license publishing the better arm's numbers.

---

## 10. FIGURES THE RUN MUST OUTPUT

Per configuration (headline plus every arm), into `reports/nflverse-backtest.md`:

1. **Header:** config hash, frozen-commit sha, seeds, seasons, weeks, template, preset, league size, depth multiplier, gate information set, rows read per release, HTTP requests, nflverse + injury attribution (RULE N1).
2. **Universe and field:** per position — universe size, field depth, per-team depth, marginal prior-season points at the cut, median.
3. **Call structure:** roster-weeks examined; slot-decisions examined; calls published; **declines by reason** (thin evidence / no eligible alternative / gate UNKNOWN / gate QUESTIONABLE / gate OUT / gate bye), summing to the total; distinct (a, b, week) triples; distinct players; clusters; median calls per cluster; **maximum share of a roster-week's calls that share one alternative**.
4. **Headline:** graded, decided, hits, hit rate, ties.
5. **Calibration table** on `DEFAULT_EDGES`: graded, decided, ties, stated mean, observed, Wilson CI, **clustered CI**, verdict; then J, C, and the count of undecided-by-disagreement buckets.
6. **ECE, Brier, resolution** (bottom decile, top decile, spread R).
7. **Breakdowns:** by season; by slot (including the K row — **this run produces the first K evidence the product has ever had**, and the DEF row reading zero); by week-of-season (the staleness curve — calibration as the frozen roster ages); by position of the recommended player.
8. **Band (template T2):** 80% coverage of the optimal-lineup total, pooled and per season. **The rule for `engine/week_report.py:68` `TEAM_RANGE_BASIS` is frozen now:** publish its coverage sentence only if pooled coverage ∈ [77%, 83%] **and** no season falls outside [72%, 88%]; otherwise the sentence is removed and the band renders with no coverage claim. Its current "about 78%" is Sleeper-era evidence over real set lineups and is **gated from now until this table exists**.
9. **Gate diagnostics:** keep rate; drops by reason; carry-forward team staleness (share of graded player-weeks where the carried-forward team differs from the week's actual team — **measured and reported, never used as an input**); share of graded weeks where the bye flag fired.
10. **The residual blind spot, replacing the banned diagnostic:** share of ACTIVE-classified recommended players who scored 0.0, and the same for alternatives, split by "row exists, scored 0.00" vs "no row at all". This is the honest analogue of `reports/backtest.md:42`'s 3.3% / 34.5% asymmetry and conditions on nothing.
11. **Defects found:** at minimum, the T1 band gap of §3 (`_team_range` silently omitting an unfilled DEF slot from a total quoted under a coverage sentence).
12. **Seed spread table** (§8) and the **arm comparison table** (§9).
13. **The grade**, computed by the §1 rule, printed by the program — not chosen by a human after reading the tables.

---

## 11. LEAKAGE — eliminated, and bounded

**Eliminated**

| # | Leak | Where | How it is eliminated | Measured size |
|---|---|---|---|---|
| L1 | Survivorship: directory filtered on `last_season` (a fact from a 2026 snapshot) | `engine/roster.py:234`, called with `season − 1` at `render/player_index.py:163` | `players.csv` is never read; the universe is S−1 stat rows | shipped window drops ~14% of the graded season's scorers, precisely the ones who left the league |
| L2 | Players who did not exist yet: no `rookie_season` bound | `engine/roster.py:208-240` | same | 428 of 1,538 directory members (28.4%) have `rookie_season > 2024`; 1 reaches the field today — luck of the cut, not a guarantee |
| L3 | `latest_team` used for the bye check | `engine/roster.py:240` → `engine/availability.py:80-84` | carry-forward team from rows strictly before W | **2,646 of 6,478 (40.8%)** of 2024 fantasy player-weeks have team ≠ `latest_team` |
| L4 | Today's position labels | `engine/roster.py:230` → `engine/history.py:57-61` | position from his last S−1 row | 0 at 1–2 years' distance; unmeasured at 10, eliminated by construction |
| L5 | Alternative selection skipping players with no actual points | `engine/decisions.py:159-161` | that selection path is unused; `optimal_lineup` ranks on projections only | — |
| L6 | Same-week injury report | `engine/gate_backtest.py:100` | W−1 report (§6) | the whole difference between a Tuesday product and a Sunday one |
| L7 | Model reading later weeks | `engine/projection.py` | filters already correct; plus a **required assertion**: for one full season, a model built over weeks 1…W−1 must produce byte-identical projections at week W to the full-season model, for every call |
| L8 | POST/PRE rows and out-of-season rows | `ingest/injuries.py:102-115` has no `game_type` filter | assert every stat row is REG and belongs to the intended season; assert injury weeks ≤ 18 | latent today |
| L9 | Field selected on the graded season | `engine/subscriber.py:240-243` checks no season | assert the prior-season mapping is S−1 | — |

**Bounded, not eliminated**

| # | Item | Bound |
|---|---|---|
| B1 | Self-shrinkage: a player sits inside his own positional prior (`engine/projection.py:245-256`, `:288`) | ≈ `k/(n+k)` × his share of the position's observations — at week 4, ~3% of his own projected mean; thin positions (QB 24, K 24, FB 12) are the exposed ones. **Arm F measures it.** |
| B2 | Frozen roster vs real churn | Not a bias against the live product: `run/refs.py:137-193` packs the whole roster into the payment ref at signup and nothing re-reads it, so **live rosters are static too**. What differs is that staleness grows to 13 weeks. Bounded by the week-of-season calibration curve (§10.7) and by reporting how many field members never appear in S. |
| B3 | Carry-forward team staleness (trades, signings) | Measured and reported (§10.9). **If it exceeds 5% of graded player-weeks, the bye half of the gate is withdrawn** and the run reverts to reporting the injury half only, with `reports/gate-backtest.md:10`'s limitation restored. |
| B4 | Independence of the two players (`engine/projection.py:141`) | Unchanged limitation, restated. |
| B5 | Seeds are not sample | §8: seed-0 headline, clustered intervals, seed spread reported. |
| B6 | A player inactive for non-injury reasons (healthy scratch, unlisted suspension) classifies ACTIVE | Quantified directly by §10.10 — the one number that says what the gate still misses. |

---

## 12. BIASES ACCEPTED — direction, and the disclosure each requires

Every disclosure below is **mandatory in `reports/nflverse-backtest.md` regardless of grade**, and the starred ones must also appear in the same visual block as any figure quoted on a public surface.

| # | Bias | Direction | Required disclosure |
|---|---|---|---|
| 1★ | Field selected on prior-season volume: no rookies, no breakouts, no returning-from-injury | **Optimistic** — the graded population is stable veterans whose trailing form is unusually predictable | "Rosters were built from players who produced the previous season. Measured for 2024, that field misses 5 of the top 12 QBs, 8 of the top 36 WRs, 4 of the top 36 RBs and 1 of the top 12 TEs — the ascending-role players a real roster holds and this test does not." |
| 2★ | Bench depth 2× starters: 23-man rosters against a real 15–16 | **Optimistic** on hit rate; likely **underconfident** on calibration | "Each simulated team carried a deeper bench than a real one. The last drafted RB had scored 42.8 points across the whole prior season, the last TE 48.4 — nobody rosters those players in a real league." |
| 3 | Slot mix: 2 QBs and 4 TEs per team; QB/TE calls over-represented, and a backup QB is a near-certain loss | **Optimistic** | Publish the slot mix beside the per-slot table and say QB/TE are over-represented. |
| 4★ | Model-vs-model pairing: the winner's-curse inflates *both* projections, and the recommended side is the argmax | **Overconfident** — the opposite sign to the old set, where only the alternative was argmax-selected | The verbatim non-comparability paragraph below. |
| 5★ | No human ever benched anyone | **Optimistic ceiling** — `reports/backtest.md:42-43`'s adverse selection (bench players score 0.0 34.5% of the time; on 890 overrules the engine hit 24.0%) is absent by construction | "The hardest case for us in a real league is a bench player a human deliberately sat because he knew something we didn't. A simulated league contains none of those. Treat this as our ceiling, not our record — the record is the ledger." **Corollary, frozen: no result here licenses relaxing or removing `may_publish_confidence`.** |
| 6 | Roster strength equalized by construction | **Unknown — stated, not signed** | "Every simulated team is roughly as strong as every other. A real league has a stacked team and a bad one, and we have not measured how that changes the mix of easy and hard calls." |
| 7 | Net of 1–5 is not derivable | — | "Some of these push the number up and some push it down. We are not going to tell you which wins; that is what the table is for." |
| 8 | PPR headline; presets differ in who is even rosterable (`engine/scoring.py:41-43`) | — | Name the preset. A claim measured under one preset is shown only under that preset. |
| 9 | 12-team, one fixed template, every season | — | Name the template and size; claim scoped to sizes that passed. |
| 10★ | DEF unmeasurable, K measured for the first time | — | "This covers QB, RB, WR, TE, FLEX and K. Defense slots publish under no measured calibration and will keep publishing no confidence until we score defenses." |
| 11 | Sample scales with seasons, not leagues | — | Print raw calls, distinct triples, clusters, and the seed spread together. |
| 12 | One league per season per seed; the 11 seasons are the independent units | — | Per-season table, never averaged away. |

**Verbatim, required in `reports/nflverse-backtest.md` and beside any figure quoted publicly:**

> These calls are not the calls in the previous report. The old set graded a human's start against the model's best bench option; this one grades the model's own first choice against its own second, on points we compute ourselves from a different data source, over a different pool of players. The two hit rates are not comparable and no difference between them is evidence of improvement.

**Also required, once:**

> Four things changed at the same time — the point source, the player pool, the way we tell whether a player appeared, and which decision we grade. So this run can tell you what the number is worth now. It cannot tell you which of those four moved it.

*(If a decomposition is wanted, the way to get it is three extra runs against the frozen 2017-18 Sleeper call set — nflverse points on Sleeper rosters, then the field prior, then the live pairing. That is out of scope here and is not a substitute for this run.)*

---

## 13. WHAT MAKES THE EXERCISE INVALID

Any of these and the run is **void** — not patched and reported, void — requiring a fresh preregistration:

1. **Any leak discovered after the fact.** Specifically: the harness is found to read any value derived from week ≥ W, or from a season > S−1 for field selection, or `players.csv` at all.
2. **The no-lookahead assertion (L7) fails** for any call.
3. **A frozen parameter is changed after any output is read** — seasons, weeks, seeds, edges, `MIN_DECIDED_TO_JUDGE`, the field rule, the depth multiplier, the template, the gate information set, the bootstrap seed, or the §1 thresholds.
4. **N is turned up after seeing an interval.** Seeds are 0–19 and the headline is seed 0, decided here.
5. **Fewer than 4 judgeable buckets after the full 11-season run.** Nothing to judge; no claim at any grade above C.
6. **C varies by more than 1 across seeds** — the verdict belongs to the pairing.
7. **A bucket verdict flips across the depth arms** — the verdict belongs to the field rule (`engine/subscriber.py:53-55` already calls it "a defensible default, not a validated one").
8. **Arm A and the headline disagree on bucket verdicts** — the appearance encoding, not the model, is deciding.
9. **Carry-forward staleness > 5%** — bye modelling withdrawn (B3), and the run is re-reported as the injury half only.

**And the honest answer "publish no confidence at all this season" is Grade D, whose conditions are frozen in §1:** the top decile fails to out-hit the bottom (R ≤ 0), or any judgeable bucket's clustered interval sits entirely below a coin flip, or the gate cannot be evaluated on Tuesday's information set. In that case `may_publish_confidence` returns False for the season, the report ships points gaps and availability facts only, and the site says so.

**The result that must be reportable as a result, not a setback:** given biases 1, 2, 3 and 5 all pointing optimistic and bias 4 pointing the other way, the most likely honest outcome is *"the table reads better than the published 53.5% for population reasons we can name, and we still do not publish an accuracy claim."* `reports/nflverse-backtest.md` is to be drafted so it can say exactly that without rewriting. The product's stated position already is that "the honest version of this engine declines more calls than it makes" (`reports/backtest.md:88`).

---

## 14. FREEZE PROCEDURE

1. `engine/nflverse_backtest.py` is written with the configuration as a module-level frozen dataclass, the §1 thresholds as module constants, and the grade computed by the program.
2. It is **committed before the first run**, and the commit sha is printed in the report header.
3. The harness **calls** `engine/week_report.py:102 optimal_lineup`, `engine/projection.py ProjectionModel` / `probability_outscores`, `engine/availability.py may_publish_confidence` + `WeekAvailability.classify`, `engine/scoring.py:109 score`, `engine/subscriber.py:219 rosterable_field` / `:260 _team_week`, `engine/decisions.py:109 grade`, and `engine/calibration.py` — none of them reimplemented. **A mutation test per function:** perturb it, the backtest output must move.
4. Required assertions, each its own test: the no-lookahead equality (L7); `max(rostered_weeks) ≤ graded weeks` (no double-counted field, `engine/subscriber.py:166-174`); REG-and-season on every row (L8, L9); no player in season S's field lacks an S−1 row; the decline table sums to slot-decisions examined.
5. It is run **once**. Then the §1 table is read off, and the copy changes it dictates are made — in that order.
---

## 15. CORRECTIONS — appended, never edited into the text above

The method above is frozen (§0: "Nothing below may be changed after the first
output is read"). A frozen document that turns out to contain a false statement
cannot be quietly fixed, because then nobody can tell what was actually
preregistered. So corrections are appended here, dated, and the original wording
stands untouched.

### C1 — "Team defenses are unscoreable" is false (2026-08-22)

§3 excludes team defenses from the graded set with this justification:

> Team defenses come from `ingest/nflverse.py:256 season_teams(S)` as
> `DEF-<abbr>`. They are unscoreable (`engine/scoring.py:26-32`,
> `engine/subscriber.py:282-290`), so they occupy roster spots and produce
> **zero calls**. This is reported, not hidden.

Both citations now say the opposite of what they are cited for.
`engine/scoring.py:26-32` is RULE S4 — *a team defense IS scored, from the
team's own week plus the schedule's final score*. `engine/subscriber.py:282-290`
is the code that calls `score_defense`. Whether the spans moved under the
citation or the claim was wrong when written, the effect is the same: an
operator reading this method concludes the product prints no DEF numeral, and
the product printed one.

**What follows, and what does not.**

- The exclusion of defenses from the graded set STANDS. Correcting a
  justification is not licence to change the population after reading an
  output; that is the one thing §0 exists to prevent. Grading defenses requires
  a new preregistration and a new commit.
- The **product** was changed instead, immediately:
  `TEAM_DEFENSE_CONFIDENCE_CALIBRATED = False` in `engine/week_report.py`
  withholds the confidence numeral on any DEF slot while still showing the
  projection — the same shape as the existing win-probability gate. A published
  probability with zero graded calls behind it is what principle 1 forbids, and
  the honest response to "no evidence" is to stop publishing, not to go looking
  for evidence that suits.
- The data for a future defense arm exists:
  `stats_team_week_{season}.csv` resolves for every season in this window at
  roughly 0.2 MB each, and `ingest/nflverse.py defense_rows` already joins it to
  the schedule's final scores.

**How it was found:** an audit comparing, regime by regime, what the shipping
product can publish a confidence for against what this harness actually graded.
The DEF case was reproduced end to end — 0.627 on the Denver defense in a real
2024 week-10 report, against 0 DEF calls in 10,041.

### C2 — other regimes the audit surfaced, not yet resolved (2026-08-22)

Recorded so they are not rediscovered as if new. Each is a regime the product
can publish in and this harness never graded. None is fixed by this correction:

- **SUPER_FLEX slots.** The picker offers a Superflex template and the ref
  encodes it; `TEMPLATE_T1` has no such slot, so zero graded calls. Its defining
  comparison — a quarterback against a bench skill player — is structurally
  absent from the graded set (QB-vs-non-QB is 0 of 956 in 2024).
- **half-PPR and standard scoring.** The intake accepts all three presets; the
  published run is PPR only, via `main()`'s default, and the report does not say
  so.
- **Weeks 17-18.** `GRADED_WEEKS` is `range(4, 17)`, but `run/solo.current_week`
  returns 17 or 18 at the end of a season.
- **League sizes other than 12**, and roster templates other than T1.
- **Rookies**, structurally: the universe for season S is built only from S−1
  stat rows, so a first-year player cannot enter it — while the live product
  publishes on him from week 4 once he has three appearances.
- **The availability information set.** The harness gates on week W−1's injury
  report; the product gates on week W's, which on a Tuesday is partial.

The cheap ones are harness arguments rather than new code —
`calls_for_season` already takes `template` and `main()` already takes
`--scoring` — but each still needs its own preregistered arm before any number
from it is published.
