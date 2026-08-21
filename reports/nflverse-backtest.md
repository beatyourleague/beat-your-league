# Confidence, re-measured on nflverse

Generated 2026-08-21 07:58 UTC. Method frozen in advance: `reports/nflverse-backtest-method.md`,
committed before this harness existed. Reproduce with
`python -m engine.nflverse_backtest`.

## Grade C

**no accuracy claim on any surface. The numeral prints as a recorded prediction only.**

The grade comes from a rule written before any number was computed, and its
clauses are required rather than weighted. This run cleared the error and
resolution thresholds for a stronger grade and failed on the bucket count, so
the stronger grade is not available. That is the rule working, not a
technicality: the whole reason it was written first is that this is the moment
it would otherwise be argued with.

## Headline

| | |
|---|---|
| Calls graded | 9073 |
| Decided (ties excluded) | 8760 |
| Ties | 313 |
| Hit rate | 63.9% |
| Expected calibration error | 3.2% |
| Brier score | 0.2208 (0.25 = a constant 50% guess) |
| Resolution — bottom decile | 50.8% |
| Resolution — top decile | 84.0% |
| Resolution spread | 33.2 points |
| Judgeable buckets | 6 |
| Calibrated | 1 |

## Calibration

Intervals are a cluster bootstrap over (season, week), 2000
resamples. A per-call interval would assume calls are independent, and they are
not — inside one roster-week the same benched player is the alternative at
several slots, and across rosters one real game drives many outcomes. Wilson
intervals are computed too, and a bucket where the two disagree is recorded as
undecided and counts against the calibrated total.

| Stated | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 50%–55% | 2445 | 2360 | 85 | 52.4% | 51.4% | 49%–54% | calibrated |
| 55%–60% | 2157 | 2084 | 73 | 57.4% | 59.8% | 58%–62% | **off** |
| 60%–65% | 1742 | 1683 | 59 | 62.4% | 65.8% | 64%–68% | **off** |
| 65%–70% | 1299 | 1246 | 53 | 67.4% | 73.2% | 71%–76% | **off** |
| 70%–80% | 1241 | 1205 | 36 | 74.1% | 79.6% | 77%–82% | **off** |
| 80%–90% | 185 | 178 | 7 | 82.9% | 90.4% | 85%–95% | **off** |

**The failure is one-directional.** Every bucket above the lowest outperforms
its stated number. The model is not noisy here — it is systematically
underconfident, which is the correctable kind of wrong and the reason resolution
is strong while calibration is not.

## Per season

| Season | Calls |
| --- | ---: |
| 2014 | 870 |
| 2015 | 845 |
| 2016 | 788 |
| 2017 | 810 |
| 2018 | 839 |
| 2019 | 807 |
| 2020 | 836 |
| 2021 | 807 |
| 2022 | 853 |
| 2023 | 757 |
| 2024 | 861 |

## What this is not

It is **not comparable to `reports/backtest.md`**. That measured a different
estimand on a different data stack: a human's actual starter against the model's
best bench option, over one twelve-team league. There are no humans here, so
this grades the model's first choice against its own second. The two numbers
must never be placed side by side.

It says **nothing about win probability**, which stays gated. The published unit
there is P(your total beats their set lineup), and the product no longer sees
any rival's lineup, so no source exists to compute it live or to grade it.

Team defenses hold roster spots and produce **zero calls**: DST scoring needs
points and yards allowed, which this product does not compute.

## Excluded, and why

- **Weeks 1–3**: three prior appearances are required before a call exists.
  Arithmetic, not a choice.
- **Weeks 17–18**: fantasy seasons are over and week-18 resting is a different
  population.
- **Pre- and post-season rows**: a week number means a different game.
- **The availability-controlled split**: it conditions on both players having
  scored, which nobody knows at call time. `reports/backtest.md` already calls
  that a diagnostic rather than a result, and this run does not recompute it.
