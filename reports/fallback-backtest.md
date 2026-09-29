# The confirmed-alternative fallback, graded as it would ship

Generated 2026-09-29 20:40 UTC from commit `6bacdc7`. Method frozen in advance: `reports/fallback-method.md`,
committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.fallback_backtest`.

Headline configuration (full PPR, 12 teams, the standard lineup), weeks 4–16, graded on
2020–2024 through the published recalibration (b = 1.3714). Raw grades are diagnostics.

## Decision

The fallback **SHIPS**. Method §3 requires NEW graded C or
better (got **C**) on at least 2 judgeable bands (got
3), and ALL graded B (got **B**).

## Summary

| Population | Calls | Decided | Grade (as shipped) | ECE | Raw grade | Raw ECE | Judgeable |
|---|---|---|---|---|---|---|---|
| NEW | 217 | 206 | **C** | 7.2% | C | 11.5% | 3 |
| ALL | 4768 | 4602 | **B** | 1.1% | C | 4.1% | 7 |

Diagnostics (decide nothing): frozen calls 2020–2024 **4551**, with the
fallback **4768** (217 new); share of slot-weeks carrying odds
64.8% → 67.9%; shared slot-weeks whose call
moved: 0.

## Bucket tables

#### NEW recalibrated, 2020–2024 — Grade C

217 calls, 206 decided, hit rate 81.1%, ECE 7.2%, 3
judgeable bands, 3 calibrated, resolution 20.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 65%–70% | 32 | 32 | 0 | 67.9% | 78.1% | 64%–90% | calibrated |
| 70%–80% | 73 | 67 | 6 | 74.5% | 79.1% | 69%–88% | calibrated |
| 80%–90% | 49 | 46 | 3 | 84.5% | 91.3% | 83%–98% | calibrated |

#### ALL recalibrated, 2020–2024 — Grade B

4768 calls, 4602 decided, hit rate 65.5%, ECE 1.1%, 7
judgeable bands, 7 calibrated, resolution 35.4 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 989 | 960 | 29 | 52.4% | 52.2% | 49%–55% | calibrated |
| 55%–60% | 833 | 799 | 34 | 57.5% | 55.7% | 52%–60% | calibrated |
| 60%–65% | 751 | 724 | 27 | 62.3% | 61.9% | 58%–66% | calibrated |
| 65%–70% | 695 | 672 | 23 | 67.5% | 68.0% | 64%–71% | calibrated |
| 70%–80% | 958 | 920 | 38 | 74.5% | 76.7% | 73%–80% | calibrated |
| 80%–90% | 494 | 480 | 14 | 84.0% | 85.8% | 83%–89% | calibrated |
| 90%–100% | 48 | 47 | 1 | 93.3% | 93.6% | 86%–100% | calibrated |

#### NEW raw, 2020–2024 (diagnostic) — Grade C

217 calls, 206 decided, hit rate 81.1%, ECE 11.5%, 3
judgeable bands, 1 calibrated, resolution 20.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 60%–65% | 37 | 37 | 0 | 63.1% | 78.4% | 66%–91% | undecided |
| 65%–70% | 45 | 42 | 3 | 67.3% | 81.0% | 68%–91% | undecided |
| 70%–80% | 65 | 59 | 6 | 74.3% | 84.7% | 74%–94% | calibrated |

#### ALL raw, 2020–2024 (diagnostic) — Grade C

4768 calls, 4602 decided, hit rate 65.5%, ECE 4.1%, 6
judgeable bands, 2 calibrated, resolution 35.4 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1304 | 1260 | 44 | 52.4% | 51.9% | 49%–55% | calibrated |
| 55%–60% | 1066 | 1028 | 38 | 57.4% | 60.0% | 57%–63% | calibrated |
| 60%–65% | 901 | 870 | 31 | 62.5% | 66.9% | 64%–70% | **off** |
| 65%–70% | 649 | 625 | 24 | 67.3% | 73.8% | 70%–78% | **off** |
| 70%–80% | 731 | 704 | 27 | 74.4% | 84.5% | 82%–87% | **off** |
| 80%–90% | 108 | 106 | 2 | 83.0% | 89.6% | 84%–95% | undecided |

#### NEW raw, 2014–2024 (diagnostic) — Grade C

542 calls, 521 decided, hit rate 79.8%, ECE 11.6%, 6
judgeable bands, 2 calibrated, resolution 21.2 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 50 | 46 | 4 | 52.9% | 73.9% | 59%–88% | **off** |
| 55%–60% | 69 | 67 | 2 | 57.8% | 61.2% | 49%–74% | calibrated |
| 60%–65% | 90 | 89 | 1 | 62.7% | 79.8% | 70%–88% | **off** |
| 65%–70% | 112 | 107 | 5 | 67.4% | 77.6% | 69%–85% | **off** |
| 70%–80% | 156 | 149 | 7 | 74.4% | 86.6% | 81%–92% | **off** |
| 80%–90% | 55 | 53 | 2 | 83.9% | 90.6% | 82%–98% | calibrated |
