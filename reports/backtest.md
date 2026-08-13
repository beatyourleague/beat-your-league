# Backtest & calibration report

Generated 2026-08-13 05:12 UTC from cached Sleeper data in `data/raw/`. No network calls, no LLM calls, no estimates: every number below is reproducible by re-running `python -m engine.backtest`.

## Leagues graded

| Season | League | Teams | Scoring | Weeks cached | Status |
| --- | --- | --- | --- | --- | --- |
| 2018 | Sleeper Friends League | 12 | Full PPR | 1-17 (17) | complete |
| 2017 | Sleeperbot Friends League | 12 | Full PPR | 1-17 (17) | complete |

## What a graded call is

For every roster, every week, every starting slot, the engine compares the player who was actually started against the **highest-projected eligible bench player** at that slot, and recommends whichever it projects higher. That head-to-head is then graded on real box-score points.

- **Starting slots:** QB, RB, RB, WR, WR, TE, FLEX, FLEX, DEF
- **Projection:** trailing-form mean shrunk toward the league-wide positional mean (K = 4 pseudo-games), built **only from weeks before the graded week**. No lookahead: `tests/test_engine.py` asserts a projection is unchanged when future weeks are altered.
- **Confidence** = P(recommended outscores that specific alternative), independent normals. This is the published unit (CLAUDE.md principle 5) — not a generic 'good start' score.
- **Minimum evidence:** both players need ≥ 3 prior appearances or the engine declines to make a call at all.
- **Standard-deviation floor:** 2 points, so a three-game low-variance sample cannot manufacture a 99% confidence.
- **Hit** = recommended scored more than the alternative. **Tie** = exactly equal, excluded from hit rates and reported separately.

Rules are frozen in `engine/decisions.py` and were written before these numbers were computed (CLAUDE.md principle 2).

## Headline

| Set | Graded | Decided | Hits | Hit rate |
| --- | ---: | ---: | ---: | ---: |
| All calls | 2056 | 2013 | 1077 | 53.5% |
| Coin-flip calls (confidence < 60%) | 1156 | 1133 | 602 | 53.1% |
| Both players scored | 1152 | 1142 | 714 | 62.5% |
| Engine overrules the manager | 890 | 861 | 207 | 24.0% |

Ties excluded from every hit rate above: 43 of 2056 calls ended exactly level.

On the 890 calls where the engine would have overruled the human, following the engine would have changed the score by **-5670.6 points** in total (-6.37 per call).

## Finding: the model's problem is availability, not scoring

This is the result that should drive the next build phase, so it is stated before the detailed tables.

- **Starters score exactly 0.0 3.3% of the time. Bench players score 0.0 34.5% of the time.** A manager benching a player is overwhelmingly a statement that the player is not going to play — a bye, an inactive, an injury. That signal is roughly a 11x difference in the odds of scoring nothing, and cached Sleeper league data contains none of the underlying facts.
- **The engine cannot see it, and pays for it.** On the 890 calls where the engine would have overruled the human, 56.7% of the players it wanted to promote scored zero. That one blind spot, not bad scoring math, is what produces the poor headline numbers above.
- **Where both players actually played, the same model is well calibrated.** Brier improves from 0.2582 to 0.2310, hit rate from 53.5% to 62.5%, and the most-confident decile from 55.7% to 77.2%.

The conditional table below is a **diagnostic, not a result to publish**: it conditions on an outcome (both players scored), which is not knowable when the call is made. It answers one specific question — is the scoring and probability math sound, or is it broken independently of availability? — and the answer is that it is sound.

## Calibration

The test that matters (CLAUDE.md principle 1): when the engine says 64%, do roughly 64% of those calls hit? *Observed* is the real hit rate; the interval is a 95% Wilson score interval.

| Stated confidence | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 50-55% | 617 | 608 | 9 | 52.4% | 53.3% | 49% – 57% | calibrated |
| 55-60% | 539 | 525 | 14 | 57.4% | 53.0% | 49% – 57% | off |
| 60-65% | 399 | 390 | 9 | 62.2% | 52.6% | 48% – 57% | off |
| 65-70% | 249 | 245 | 4 | 67.3% | 54.3% | 48% – 60% | off |
| 70-80% | 214 | 208 | 6 | 73.8% | 56.2% | 49% – 63% | off |
| 80-90% | 38 | 37 | 1 | 83.6% | 54.1% | 38% – 69% | off |

- **Brier score:** 0.2582 (0.25 = always guessing 50%; lower carries information).
- **Expected calibration error:** 7.2% — the sample-weighted average gap between stated and observed.
- **Resolution:** least-confident decile hits 55.2%, most-confident decile hits 55.7%. Calibration without this gap would mean the number sorts nothing.
- **Buckets with enough data to judge:** 6; 1 calibrated, 5 off.

## Calibration, availability controlled (diagnostic)

The same calls, restricted to head-to-heads where **both players actually played**. This isolates the scoring and probability math from the availability blind spot. It is not a publishable accuracy claim — it conditions on an outcome — it is the evidence that the confidence number becomes trustworthy once the engine can see who is active.

| Stated confidence | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 50-55% | 375 | 373 | 2 | 52.4% | 57.4% | 52% – 62% | calibrated |
| 55-60% | 307 | 302 | 5 | 57.3% | 58.6% | 53% – 64% | calibrated |
| 60-65% | 212 | 209 | 3 | 62.1% | 63.6% | 57% – 70% | calibrated |
| 65-70% | 123 | 123 | 0 | 67.3% | 69.1% | 60% – 77% | calibrated |
| 70-80% | 120 | 120 | 0 | 73.9% | 78.3% | 70% – 85% | calibrated |
| 80-90% | 15 | 15 | 0 | 83.8% | 73.3% | 48% – 89% | too few (< 30) |

- **Brier score:** 0.2310 (0.25 = always guessing 50%; lower carries information).
- **Expected calibration error:** 3.1% — the sample-weighted average gap between stated and observed.
- **Resolution:** least-confident decile hits 60.5%, most-confident decile hits 77.2%. Calibration without this gap would mean the number sorts nothing.
- **Buckets with enough data to judge:** 5; 5 calibrated, 0 off.

## What this means for Phase 3

1. **Ship an availability feed before shipping a confidence number.** Bye weeks come from the free public NFL schedule and injury designations are already on Sleeper's player records — they simply have to be captured weekly, since the players table only ever holds today's status. This is the highest-value change available to the engine, and it is cheap.
2. **The probability math itself passes.** On the availability-controlled set, 5 of 5 judgeable buckets are calibrated. A stated 64% is worth publishing once the engine knows who is playing — and not before (CLAUDE.md principle 1).
3. **Until then, the report must not print a confidence for a player whose status is unknown.** Per the Phase 3 spec, that slot renders as *coming in v0.3*, never as a number. The honest version of this engine declines more calls than it makes.
4. **The rival's bench is where the edge is.** A rival starting a player who will not play is the single most exploitable event in this data, and it is visible to us the moment an availability feed exists — this is exactly the "where the rival is fragile" section the product promises.

## By season

| Season | Graded | Decided | Hit rate | Brier |
| --- | ---: | ---: | ---: | ---: |
| 2018 | 998 | 974 | 52.8% | 0.2583 |
| 2017 | 1058 | 1039 | 54.2% | 0.2580 |

Two seasons is a small out-of-sample check, not a validation. The model has no fitted parameters, so there is nothing overfit to a single season — but a hit rate that swings hard between seasons is a warning, and it is printed here rather than averaged away.

## By slot

Where the engine earns its keep, and where it does not.

| Slot | Graded | Decided | Hit rate | Avg stated |
| --- | ---: | ---: | ---: | ---: |
| RB | 581 | 573 | 56.2% | 61.9% |
| FLEX | 570 | 550 | 43.5% | 59.6% |
| WR | 566 | 560 | 60.5% | 59.9% |
| QB | 151 | 151 | 55.0% | 57.0% |
| TE | 129 | 126 | 54.0% | 61.3% |
| DEF | 59 | 53 | 49.1% | 58.4% |

## Manager profiles

Rival profiles for Phase 3. Every line cites the season and week span it was computed from.

### 2018 — Sleeper Friends League (transaction log: weeks 1-16)

| Rank | Team | Waiver style | FAAB spent | Bids (won/placed) | Top bid | Median bid | FA adds | Trades | Moves/wk | Game-day adds |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1/12 | Manager 15 (Manager 23) | very aggressive | 140/100 ⚠ | 28/109 | 39 | 0 | 28 | 3 | 3.69 | 25% |
| 2/12 | Manager 06 (Manager 26) | very aggressive | 101/100 ⚠ | 19/42 | 36 | 2 | 21 | 1 | 2.56 | 33% |
| 3/12 | Manager 31 | very aggressive | 100/100 | 22/47 | 25 | 1 | 34 | 0 | 3.50 | 12% |
| 4/12 | Manager 10 (Manager 25) | aggressive | 100/100 | 14/34 | 37 | 4 | 28 | 5 | 2.94 | 31% |
| 5/12 | Manager 04 (Manager 24) | aggressive | 90/100 | 14/33 | 33 | 3 | 37 | 2 | 3.31 | 28% |
| 6/12 | Manager 16 (Manager 13) | selective | 89/100 | 23/51 | 40 | 0 | 42 | 4 | 4.31 | 26% |
| 7/12 | Manager 11 (Manager 22) | selective | 89/100 | 13/20 | 51 | 1 | 23 | 1 | 2.31 | 23% |
| 8/12 | Manager 05 (Manager 30) | selective | 80/100 | 12/28 | 38 | 4 | 22 | 1 | 2.19 | 16% |
| 9/12 | Manager 36 (Manager 14) | quiet | 72/100 | 11/16 | 21 | 4 | 9 | 1 | 1.31 | 27% |
| 10/12 | Manager 02 (Manager 35) | quiet | 52/100 | 5/12 | 29 | 10 | 7 | 0 | 0.75 | 25% |
| 11/12 | Manager 20 | quiet | 21/100 | 4/23 | 12 | 2 | 13 | 2 | 1.19 | 77% |
| 12/12 | Manager 33 | quiet | 12/100 | 2/6 | 7 | 2 | 11 | 0 | 0.81 | 38% |

Waiver style is a rank **within this league**, not an absolute grade: league cultures differ too much for a fixed threshold to separate anyone. Bids counted include failed claims, which reveal intent and price; only winning bids spend FAAB. *Game-day adds* is a proxy for engagement (share of adds made Thu/Sun/Mon, US Eastern), not lineup-setting time.

⚠ 2 manager(s) spent more FAAB than the league's recorded budget of 100. That setting reports only its current value, so a commissioner raising budgets mid-season makes the *percentage* meaningless — raw spend is still accurate, and the ranking above uses raw spend for exactly this reason.

**Start/sit accuracy, 2018** — measured on the same graded head-to-heads. This scores the human, not the engine: how often the player they started outscored the best bench alternative.

These numbers look flattering, and they are: roughly a third of bench players score nothing, so "beat the best bench option" is a low bar that a manager clears simply by starting someone on a bye. Read the column as *engagement* — did they set a lineup at all — not as skill, and do not publish it to a subscriber as a rival's accuracy. Points left on the bench is the more honest column, and it is the one the Regret Score should build on.

| Team | Decided calls | Manager right | Accuracy | Points left on bench |
| --- | ---: | ---: | ---: | ---: |
| Manager 15 (Manager 23) | 79 | 75 | 94.9% | 24.2 |
| Manager 11 (Manager 22) | 76 | 69 | 90.8% | 39.4 |
| Manager 06 (Manager 26) | 63 | 56 | 88.9% | 41.1 |
| Manager 05 (Manager 30) | 97 | 79 | 81.4% | 114.7 |
| Manager 16 (Manager 13) | 69 | 56 | 81.2% | 95.8 |
| Manager 20 | 82 | 65 | 79.3% | 108.8 |
| Manager 10 (Manager 25) | 82 | 64 | 78.0% | 130.0 |
| Manager 04 (Manager 24) | 93 | 72 | 77.4% | 117.3 |
| Manager 31 | 81 | 60 | 74.1% | 196.2 |
| Manager 02 (Manager 35) | 84 | 62 | 73.8% | 139.5 |
| Manager 33 | 97 | 68 | 70.1% | 288.0 |
| Manager 36 (Manager 14) | 71 | 48 | 67.6% | 128.9 |

### 2017 — Sleeperbot Friends League (transaction log: weeks 1-16)

| Rank | Team | Waiver style | FAAB spent | Bids (won/placed) | Top bid | Median bid | FA adds | Trades | Moves/wk | Game-day adds |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1/12 | Manager 27 | very aggressive | 119/100 ⚠ | 15/38 | 35 | 2 | 8 | 0 | 1.44 | 12% |
| 2/12 | Manager 03 (Manager 24) | very aggressive | 100/100 | 14/35 | 37 | 1 | 51 | 1 | 4.12 | 34% |
| 3/12 | Manager 09 (Manager 13) | very aggressive | 100/100 | 19/38 | 45 | 3 | 28 | 3 | 3.12 | 42% |
| 4/12 | Manager 08 (Manager 26) | aggressive | 100/100 | 12/36 | 41 | 8 | 29 | 4 | 2.81 | 17% |
| 5/12 | Manager 21 (Manager 34) | aggressive | 100/100 | 11/20 | 36 | 4 | 17 | 0 | 1.75 | 14% |
| 6/12 | Manager 18 (Manager 12) | selective | 100/100 | 4/8 | 39 | 18 | 11 | 1 | 1.00 | 47% |
| 7/12 | Manager 22 | selective | 83/100 | 14/36 | 47 | 1 | 17 | 2 | 2.06 | 21% |
| 8/12 | Manager 19 (Manager 25) | selective | 80/100 | 19/43 | 38 | 1 | 33 | 5 | 3.56 | 32% |
| 9/12 | Manager 07 (Manager 20) | quiet | 59/100 | 13/52 | 18 | 3 | 18 | 3 | 2.12 | 42% |
| 10/12 | Manager 01 (Manager 35) | quiet | 35/100 | 5/7 | 20 | 3 | 11 | 0 | 1.00 | 0% |
| 11/12 | Manager 17 | quiet | 27/100 | 5/11 | 9 | 5 | 9 | 0 | 0.88 | 40% |
| 12/12 | Manager 28 (Manager 33) | quiet | 6/100 | 4/6 | 13 | 2 | 13 | 1 | 1.12 | 47% |

Waiver style is a rank **within this league**, not an absolute grade: league cultures differ too much for a fixed threshold to separate anyone. Bids counted include failed claims, which reveal intent and price; only winning bids spend FAAB. *Game-day adds* is a proxy for engagement (share of adds made Thu/Sun/Mon, US Eastern), not lineup-setting time.

⚠ 1 manager(s) spent more FAAB than the league's recorded budget of 100. That setting reports only its current value, so a commissioner raising budgets mid-season makes the *percentage* meaningless — raw spend is still accurate, and the ranking above uses raw spend for exactly this reason.

**Start/sit accuracy, 2017** — measured on the same graded head-to-heads. This scores the human, not the engine: how often the player they started outscored the best bench alternative.

These numbers look flattering, and they are: roughly a third of bench players score nothing, so "beat the best bench option" is a low bar that a manager clears simply by starting someone on a bye. Read the column as *engagement* — did they set a lineup at all — not as skill, and do not publish it to a subscriber as a rival's accuracy. Points left on the bench is the more honest column, and it is the one the Regret Score should build on.

| Team | Decided calls | Manager right | Accuracy | Points left on bench |
| --- | ---: | ---: | ---: | ---: |
| Manager 28 (Manager 33) | 101 | 78 | 77.2% | 158.2 |
| Manager 07 (Manager 20) | 65 | 50 | 76.9% | 112.8 |
| Manager 22 | 83 | 63 | 75.9% | 138.7 |
| Manager 19 (Manager 25) | 88 | 65 | 73.9% | 140.9 |
| Manager 17 | 88 | 64 | 72.7% | 233.0 |
| Manager 27 | 79 | 57 | 72.2% | 180.2 |
| Manager 21 (Manager 34) | 92 | 66 | 71.7% | 208.4 |
| Manager 03 (Manager 24) | 84 | 60 | 71.4% | 120.3 |
| Manager 01 (Manager 35) | 92 | 65 | 70.7% | 197.6 |
| Manager 09 (Manager 13) | 97 | 68 | 70.1% | 202.9 |
| Manager 18 (Manager 12) | 90 | 61 | 67.8% | 269.9 |
| Manager 08 (Manager 26) | 80 | 53 | 66.2% | 317.9 |

## Limitations — read before quoting any number above

1. **No availability signal** — quantified in the finding section above, and the dominant error source by a wide margin. The engine infers availability only from a player's own appearance history, which catches a lingering injury but cannot catch a bye week: a player on bye played last week and will play next week, so nothing in cached league data flags it in advance.
2. **Zero means absent.** A player scoring exactly 0.0 is treated as not having played and dropped from form. Real PPR scoring lands on exactly 0.0 only rarely for an active player, but this does discard genuine zeros.
3. **Correlated calls.** One strong bench player can be the best alternative at several slots in a week. Duplicate head-to-heads are removed, but the remaining calls are not independent, so the Wilson intervals are narrower than the truth.
4. **Independence assumption.** P(A beats B) treats two players as independent; teammates and players in the same game are not.
5. **Position drift.** The players table is a current snapshot, so a player who changed listed position since the graded season is classified by today's position.
6. **Declined calls.** 1,616 slot-weeks produced no call because a player lacked the required prior appearances. Early-season weeks are therefore under-represented, and the measured hit rate describes the part of the season the engine is willing to speak about.

Metrics deliberately **not** computed, rather than approximated:

- **questionable-start rate** — Sleeper's players table carries only a current injury_status, not per-week history, so a past season has no injury state to read. Starts accumulating once weekly snapshots begin.
- **lineup-setting lateness** — Lineup changes are not transactions and are not exposed by the public API; no cached data recovers them.

## Run verification

- Seasons loaded: 2 (2018, 2017)
- Roster-weeks examined: 408
- Players table: 12,218 entries
- Calls graded: 2,056; slot-weeks declined for thin evidence: 1,616
- HTTP requests: 0 (cache only)
- LLM tokens: 0 (deterministic layer — no language calls in the backtest)
