# Projections feed evaluation — Sleeper/Rotowire vs trailing-form model

Generated 2026-08-15 17:55 UTC from cached data in `data/raw/`. No estimates: every number is reproducible by re-running `python -m engine.projections_eval`.

**The question:** should the report's projections come from Sleeper's own free feed (Rotowire-sourced, archived, fetched through the same public API) instead of the trailing-form model? Rule: the feed is graded on the **same frozen call set** the incumbent was backtested on — identical head-to-heads, identical box scores, decision rule held fixed.

**Archive honesty:** the feed has no usable records for 2017 (records exist but carry no stat lines — verified). Those seasons are excluded rather than counted as zeros. Whether Rotowire ever revised archived projections after the fact is unknowable from here; treat the feed's numbers as as-archived, not as-published.

## Paired decisions (the number that matters)

| Season | Head-to-heads | Model hit rate | Feed hit rate | Feed right / model wrong | Model right / feed wrong | Feed had no opinion |
|---|---|---|---|---|---|---|
| 2018 | 368 | 64.4% | 68.8% | 47 | 31 | 626 |

## Projection accuracy (diagnostic — decisions above outrank this)

| Season | Player-weeks | Model MAE | Feed MAE | Model RMSE | Feed RMSE |
|---|---|---|---|---|---|
| 2018 | 1494 | 6.61 | 6.39 | 8.58 | 8.11 |

## Early-week coverage (the launch-week gap)

| Week | Graded starters | Model can project | Feed can project |
|---|---|---|---|
| 1 | 108 | 0 | 92 |
| 2 | 108 | 108 | 98 |
| 3 | 108 | 108 | 98 |

## Verdict inputs

- Across 368 identical head-to-heads where BOTH could speak: model 64.4%, feed 68.8%. Where they disagreed, the feed was right 47 times and the model 31 (exact McNemar two-sided p = 0.089 — suggestive, NOT conclusive on one season; do not quote the gap without the p-value).
- **The feed cannot replace the model.** It had no opinion on 626 of 994 incumbent head-to-heads: its projection universe is a fixed ~400-520 players per week in EVERY era (2018: ~513, 2022: 383, 2024: 370, 2025: 383 — verified live Aug 2026), while a 12-team league's best-bench alternatives regularly sit outside it. Any adoption is a BLEND: feed where it speaks, trailing-form where it does not.
- Survivorship check (passed): the usable subset is NOT filtered by who is still active today — 85 of 513 usable 2018-w10 records are players inactive in 2026, and 8,139 currently-active players are husks. The paired design also conditions both models on the same subset, so the comparison is fair even though the subset is selected.
- The one unambiguous win is week 1: the feed projects most starters where the trailing-form model is structurally silent. That is the launch-week gap closed with real numbers instead of a gate.
- Adoption caveat (principle 1): the floor/ceiling band's 77.9% coverage evidence was measured under TRAILING-FORM means. Swapping or blending means invalidates that evidence — re-run the matchup backtest under the blend before the band publishes on feed numbers, and leave every availability/confidence gate exactly where it is.
- One league, one usable season. Enough to decide direction, not enough to claim a universal number — say so wherever this is quoted.
