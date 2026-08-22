# Confidence, re-measured on nflverse

Generated 2026-08-22 02:47 UTC. Method frozen in advance: `reports/nflverse-backtest-method.md`,
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
| Calls graded | 10041 |
| Decided (ties excluded) | 9721 |
| Ties | 320 |
| Hit rate | 64.6% |
| Expected calibration error | 3.6% |
| Brier score | 0.2178 (0.25 = a constant 50% guess) |
| Resolution — bottom decile | 50.5% |
| Resolution — top decile | 86.1% |
| Resolution spread | 35.6 points |
| Judgeable buckets | 6 |
| Calibrated | 2 |

## Calibration

Intervals are a cluster bootstrap over (season, week), 2000
resamples. A per-call interval would assume calls are independent, and they are
not — inside one roster-week the same benched player is the alternative at
several slots, and across rosters one real game drives many outcomes. Wilson
intervals are computed too, and a bucket where the two disagree is recorded as
undecided and counts against the calibrated total.

| Stated | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 50%–55% | 2714 | 2627 | 87 | 52.4% | 51.6% | 50%–54% | calibrated |
| 55%–60% | 2311 | 2233 | 78 | 57.4% | 58.9% | 57%–61% | calibrated |
| 60%–65% | 1946 | 1887 | 59 | 62.5% | 66.3% | 64%–68% | **off** |
| 65%–70% | 1407 | 1357 | 50 | 67.3% | 74.1% | 72%–77% | **off** |
| 70%–80% | 1417 | 1375 | 42 | 74.1% | 82.3% | 80%–84% | **off** |
| 80%–90% | 244 | 240 | 4 | 82.9% | 91.2% | 88%–95% | **off** |

**The failure is one-directional.** Every bucket above the lowest outperforms
its stated number. The model is not noisy here — it is systematically
underconfident, which is the correctable kind of wrong and the reason resolution
is strong while calibration is not.

## Per season

| Season | Calls |
| --- | ---: |
| 2014 | 953 |
| 2015 | 947 |
| 2016 | 872 |
| 2017 | 893 |
| 2018 | 925 |
| 2019 | 900 |
| 2020 | 929 |
| 2021 | 885 |
| 2022 | 943 |
| 2023 | 838 |
| 2024 | 956 |

## What this is not

It is **not comparable to `reports/backtest.md`**. That measured a different
estimand on a different data stack: a human's actual starter against the model's
best bench option, over one twelve-team league. There are no humans here, so
this grades the model's first choice against its own second. The two numbers
must never be placed side by side.

It says **nothing about win probability**, which stays gated. The published unit
there is P(your total beats their set lineup), and the product no longer sees
any rival's lineup, so no source exists to compute it live or to grade it.

Team defenses hold roster spots and produce **zero calls** — and the reason
printed here was wrong. It said DST scoring "needs points and yards allowed,
which this product does not compute". The product computes it: `engine/scoring.py`
RULE S4 scores a defense from the team's own week plus the schedule's final
score, and `engine/subscriber.py` calls it. What is true is narrower and worse:
this HARNESS never merges the team rows in, so every `DEF-` id misses, scores as
an absence, and is gated out before a call exists.

So the live product scored defenses, projected them and published a confidence
on one — 0.627 on a real 2024 week-10 report — against zero graded DEF calls
anywhere in this table. That is a published probability with no method behind
it, which principle 1 forbids, so **the product now withholds the numeral on any
DEF slot** (`TEAM_DEFENSE_CONFIDENCE_CALIBRATED = False`) while still showing the
projection, exactly as it already does for win probability.

Folding defenses into the run above was not an option: §3 of the frozen method
excludes them and says in terms that nothing in it may change once an output has
been read. Grading them needs a new preregistration and a new commit. The data
is there when that happens — `stats_team_week_{season}.csv` resolves for every
season in this window, at about 0.2 MB each.

## Excluded, and why

- **Weeks 1–3**: three prior appearances are required before a call exists.
  Arithmetic, not a choice.
- **Weeks 17–18**: fantasy seasons are over and week-18 resting is a different
  population.
- **Pre- and post-season rows**: a week number means a different game.
- **The availability-controlled split**: it conditions on both players having
  scored, which nobody knows at call time. `reports/backtest.md` already calls
  that a diagnostic rather than a result, and this run does not recompute it.
