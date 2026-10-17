# Lineup shapes, graded one shape at a time

Generated 2026-10-16 23:42 UTC from commit `a199a01`. Method frozen in advance:
`reports/lineup-shapes-method.md`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.shapes_backtest`.

Each arm is one lineup shape for an offense the signup page offers that had no
grade (with a K and a DEF, and with neither), graded alone on 2020–2024,
weeks 4–16, full PPR, 12 teams, as the product ships
(context arm AV, anchor 0.25, confirmed fallback), every confidence through the
shipped recalibration (b = 1.2064).

## Decisions

- Two FLEX (flex2): arms graded B and B — prints: odds print in every K/DEF variant of this lineup, as recorded predictions.
- Three WR (wr3): arms graded B and B — prints: odds print in every K/DEF variant of this lineup, as recorded predictions.

An offense that prints does so once its grade is recorded in code (method §3).

## Summary

| Arm | Lineup | Calls | Decided | Hit rate | ECE | Judgeable | Calibrated | Resolution (pts) | Grade |
|---|---|---|---|---|---|---|---|---|---|
| flex2 | Two FLEX | 5574 | 5369 | 66.7% | 2.1% | 7 | 6 | 38.1 | **B** |
| flex2-nokd | Two FLEX, no K or DEF | 5118 | 4940 | 67.5% | 2.1% | 7 | 6 | 37.9 | **B** |
| wr3 | Three WR | 5387 | 5191 | 67.4% | 2.3% | 7 | 5 | 35.8 | **B** |
| wr3-nokd | Three WR, no K or DEF | 4931 | 4762 | 68.4% | 2.3% | 7 | 5 | 35.5 | **B** |

Grade A is unreachable in these runs by construction (seed 0 only). Hit rate
and ECE are measured facts about past seasons, not a claim that any number in
a report is right. The banned words stay banned at every grade here.

## By arm

### flex2 — Two FLEX

`QB RB RB WR WR TE FLEX FLEX K DEF`

**Grade B: the measured figures may be stated as facts, alongside the failures.**

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1087 | 1027 | 60 | 52.5% | 49.9% | 47%–53% | calibrated |
| 55%–60% | 1012 | 973 | 39 | 57.4% | 58.6% | 56%–62% | calibrated |
| 60%–65% | 868 | 842 | 26 | 62.4% | 66.0% | 62%–70% | undecided |
| 65%–70% | 778 | 750 | 28 | 67.4% | 69.6% | 66%–73% | calibrated |
| 70%–80% | 1133 | 1096 | 37 | 74.7% | 76.2% | 74%–79% | calibrated |
| 80%–90% | 620 | 605 | 15 | 83.9% | 85.1% | 82%–88% | calibrated |
| 90%–100% | 76 | 76 | 0 | 92.1% | 90.8% | 84%–97% | calibrated |

Calls per season: 2020 1118, 2021 1072, 2022 1146, 2023 1087, 2024 1151.

### flex2-nokd — Two FLEX, no K or DEF

`QB RB RB WR WR TE FLEX FLEX`

**Grade B: the measured figures may be stated as facts, alongside the failures.**

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 930 | 879 | 51 | 52.6% | 50.4% | 47%–54% | calibrated |
| 55%–60% | 894 | 862 | 32 | 57.4% | 58.6% | 56%–62% | calibrated |
| 60%–65% | 800 | 778 | 22 | 62.4% | 66.5% | 62%–70% | **off** |
| 65%–70% | 726 | 702 | 24 | 67.4% | 69.5% | 66%–73% | calibrated |
| 70%–80% | 1077 | 1043 | 34 | 74.7% | 76.5% | 74%–79% | calibrated |
| 80%–90% | 615 | 600 | 15 | 84.0% | 85.5% | 82%–88% | calibrated |
| 90%–100% | 76 | 76 | 0 | 92.1% | 90.8% | 84%–97% | calibrated |

Calls per season: 2020 1047, 2021 988, 2022 1034, 2023 1011, 2024 1038.

### wr3 — Three WR

`QB RB RB WR WR WR TE FLEX K DEF`

**Grade B: the measured figures may be stated as facts, alongside the failures.**

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 999 | 945 | 54 | 52.5% | 49.8% | 46%–54% | calibrated |
| 55%–60% | 912 | 877 | 35 | 57.4% | 58.6% | 55%–62% | calibrated |
| 60%–65% | 845 | 818 | 27 | 62.5% | 66.7% | 63%–70% | **off** |
| 65%–70% | 752 | 728 | 24 | 67.4% | 71.2% | 68%–74% | **off** |
| 70%–80% | 1151 | 1112 | 39 | 74.6% | 76.1% | 74%–78% | calibrated |
| 80%–90% | 630 | 614 | 16 | 84.0% | 84.4% | 81%–87% | calibrated |
| 90%–100% | 98 | 97 | 1 | 92.2% | 90.7% | 84%–96% | calibrated |

Calls per season: 2020 1083, 2021 1031, 2022 1110, 2023 1049, 2024 1114.

### wr3-nokd — Three WR, no K or DEF

`QB RB RB WR WR WR TE FLEX`

**Grade B: the measured figures may be stated as facts, alongside the failures.**

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 842 | 797 | 45 | 52.5% | 50.4% | 47%–54% | calibrated |
| 55%–60% | 794 | 766 | 28 | 57.4% | 58.6% | 55%–62% | calibrated |
| 60%–65% | 777 | 754 | 23 | 62.5% | 67.2% | 64%–71% | **off** |
| 65%–70% | 700 | 680 | 20 | 67.4% | 71.2% | 68%–75% | **off** |
| 70%–80% | 1095 | 1059 | 36 | 74.7% | 76.4% | 74%–79% | calibrated |
| 80%–90% | 625 | 609 | 16 | 84.0% | 84.7% | 82%–88% | calibrated |
| 90%–100% | 98 | 97 | 1 | 92.2% | 90.7% | 84%–96% | calibrated |

Calls per season: 2020 1012, 2021 947, 2022 998, 2023 973, 2024 1001.
