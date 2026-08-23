# Early-season confidence — weeks 2–3, prior-season seeded

Generated 2026-08-23 20:38 UTC. Method frozen in advance:
`reports/early-season-method.md`, committed before this runner's first
execution. Reproduce with `python -m engine.early_season_backtest`.
Configuration: λ = 0.5, weeks 2 and 3,
seasons 2014–2024, PPR, 12 teams,
template T1, seed 0 headline. The availability gate is the parent's §6 with
correction C3: week W−1's injury report, carry-forward teams, fail closed.
Inertness check (§6.4): with the seed disabled, the parent's 2024 season
reproduced call-for-call (956 calls, identical hash) before this arm was run.

## Grade B

**the measured figures may be stated as facts, alongside the failures.**

**The frozen decision (§5):** The seeded model ships for weeks 2–3. Its figures may be stated as facts beside the failures; the banned words stay banned.

## Headline

| | |
|---|---|
| Calls graded | 1692 |
| Decided (ties excluded) | 1669 |
| Ties | 23 |
| Hit rate | 61.2% |
| Expected calibration error | 2.5% |
| Brier score | 0.2325 (0.25 = a constant 50% guess) |
| Resolution — bottom decile | 56.6% |
| Resolution — top decile | 79.5% |
| Resolution spread | 22.9 points |
| Judgeable buckets | 5 |
| Calibrated | 4 |

## Calibration

Same machinery as the parent report: cluster bootstrap over (season, week),
Wilson agreement required, a disagreement recorded as undecided and counted
against the calibrated total — plus this arm's preregistered precision clause:
a bucket whose clustered interval spans more than 15
percentage points is undecided, never calibrated, because agreement inside an
enormous interval is not evidence. The cluster count here is small
(22 season-weeks against the parent's 143), so intervals are wide;
that width is the honest price of the question, and the clusters column says
how much each bucket really rests on.

| Stated | Graded | Decided | Ties | Stated avg | Observed | 95% interval | Clusters | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| 50%–55% | 564 | 555 | 9 | 52.5% | 53.2% | 49%–57% | 22 | calibrated |
| 55%–60% | 515 | 507 | 8 | 57.3% | 59.2% | 55%–63% | 22 | calibrated |
| 60%–65% | 344 | 339 | 5 | 62.3% | 66.4% | 62%–71% | 22 | calibrated |
| 65%–70% | 182 | 182 | 0 | 67.2% | 70.3% | 63%–76% | 22 | calibrated |
| 70%–80% | 85 | 84 | 1 | 73.2% | 84.5% | 78%–91% | 22 | **off** |

## Effective sample

The calls are not independent, and this arm doubly so: the seed barely moves
between weeks 2 and 3, so many head-to-heads recur across the two graded
weeks. What the counts really rest on:

| | |
|---|---|
| Raw calls | 1692 |
| Distinct (pick, alternative, slot) triples | 1147 |
| Distinct players involved | 541 |
| Clusters (season, week) | 22 |
| Median calls per cluster | 77 |
| Week-3 calls repeating their week-2 pairing | 60.7% |

If the distinct-triple or cluster counts diverge badly from the raw count, the
intervals are decoration — which is why the precision clause above exists.

## Seed stability

Seeds 0–19: C min 3, median 3, max 4 — spread 1.

## Sensitivity — reported, never substituted

The headline is λ = 0.5 regardless of what this table shows
(method §2: reporting a sensitivity arm as the result is the tuning the
preregistration forbids).

| Arm | Calls | Hit rate | ECE | Resolution | Judgeable | Calibrated | Grade |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| λ = 0.25 | 1700 | 60.6% | 3.0% | 35.9 | 5 | 2 | C |
| λ = 1.0 | 1670 | 61.4% | 2.7% | 33.5 | 5 | 4 | B |

## Per season

Method §1 stated an expectation of roughly 1,000–1,500 calls before the run;
the arm produced 1692, slightly above it — the gates took less
than the sizing allowed for, not more.

| Season | Calls |
| --- | ---: |
| 2014 | 155 |
| 2015 | 145 |
| 2016 | 155 |
| 2017 | 156 |
| 2018 | 157 |
| 2019 | 154 |
| 2020 | 154 |
| 2021 | 159 |
| 2022 | 157 |
| 2023 | 137 |
| 2024 | 163 |

## The bias this arm carries (§7)

The recommended side of every call is the argmax over the seed — the same
statistic that built the rosters — and its noise persists across both graded
weeks rather than regressing as real games accumulate. The winner's-curse
inflation the parent describes does not average out between weeks 2 and 3.
This disclosure travels with the result at every grade.

## Scope, stated

Week 1 is out of reach for any model: there is no week-0 injury report, so the
gate classifies everyone UNKNOWN and no number prints. Rookies and anyone
absent from the prior season's stat rows stay gated in weeks 2–3 — this arm
admits a player's own record, and a player without one is who the original
gate exists for. The run covers PPR, 12-team, template T1 only; other presets
and sizes ship no week 2–3 numbers until their own arms run. Every call whose
gate passes through the seed carries "last season counted in" on its row —
a seeded call that hides its seeding violates the preregistration.
