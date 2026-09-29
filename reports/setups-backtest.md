# Other setups, graded one setting at a time

Generated 2026-09-29 10:11 UTC from commit `d4cfe73`. Method frozen in advance:
`reports/setups-method.md`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.setups_backtest`.

Each arm changes one setting from the published run (full PPR, 12 teams, the
standard lineup, weeks 4–16, which keeps its own Grade C) and is graded alone,
by the same rule and the same code. Combined settings are not graded as
combinations: a report prints a numeral only if every setting of its setup
graded C or better (method §3).

## Summary

| Arm | Setting | Calls | Decided | Hit rate | ECE | Judgeable | Calibrated | Resolution (pts) | Grade |
|---|---|---|---|---|---|---|---|---|---|
| S1 | scoring: half_ppr | 10004 | 9674 | 65.9% | 4.7% | 6 | 1 | 34.9 | **C** |
| S2 | scoring: standard | 10062 | 9730 | 66.1% | 5.1% | 6 | 1 | 31.4 | **C** |
| L10 | league size: 10 | 8654 | 8409 | 64.0% | 3.1% | 6 | 2 | 34.9 | **C** |
| L14 | league size: 14 | 11488 | 11050 | 67.1% | 5.2% | 6 | 1 | 38.5 | **C** |
| L8 | league size: 8 | 6979 | 6809 | 64.0% | 3.6% | 6 | 1 | 30.1 | **C** |
| TSF | lineup shape: superflex | 11703 | 11349 | 65.3% | 3.9% | 6 | 2 | 39.0 | **C** |
| TNKD | lineup shape: no K or DEF | 9010 | 8753 | 65.3% | 3.9% | 6 | 2 | 35.9 | **C** |
| W17 | weeks: 17-18 | 1168 | 1087 | 65.6% | 3.7% | 6 | 5 | 20.4 | **B** |

Grade A is unreachable in these runs by construction (seed 0 only; method §2).
Hit rate and ECE are measured facts about past seasons, not a claim that any
number in a report is right. The banned words stay banned at every grade here.

## By arm

### S1 — scoring: half_ppr

**Grade C: no accuracy claim on any surface. The numeral prints as a recorded prediction only.** Decision under method §3: numeral prints as a recorded prediction only.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 2720 | 2635 | 85 | 52.4% | 54.0% | 52%–56% | calibrated |
| 55%–60% | 2412 | 2310 | 102 | 57.4% | 60.4% | 58%–62% | **off** |
| 60%–65% | 1873 | 1818 | 55 | 62.4% | 67.6% | 66%–70% | **off** |
| 65%–70% | 1490 | 1451 | 39 | 67.4% | 76.3% | 74%–79% | **off** |
| 70%–80% | 1313 | 1268 | 45 | 73.8% | 82.5% | 80%–85% | **off** |
| 80%–90% | 195 | 191 | 4 | 82.4% | 90.6% | 86%–95% | **off** |

Calls per season: 2014 946, 2015 967, 2016 858, 2017 883, 2018 907, 2019 882, 2020 930, 2021 890, 2022 940, 2023 859, 2024 942.

### S2 — scoring: standard

**Grade C: no accuracy claim on any surface. The numeral prints as a recorded prediction only.** Decision under method §3: numeral prints as a recorded prediction only.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 2764 | 2652 | 112 | 52.4% | 54.1% | 52%–56% | calibrated |
| 55%–60% | 2407 | 2324 | 83 | 57.4% | 63.1% | 61%–65% | **off** |
| 60%–65% | 2018 | 1956 | 62 | 62.5% | 68.3% | 66%–71% | **off** |
| 65%–70% | 1433 | 1401 | 32 | 67.3% | 72.9% | 70%–75% | **off** |
| 70%–80% | 1270 | 1231 | 39 | 73.9% | 83.1% | 81%–85% | **off** |
| 80%–90% | 162 | 158 | 4 | 83.1% | 92.4% | 88%–97% | **off** |

Calls per season: 2014 954, 2015 990, 2016 860, 2017 897, 2018 935, 2019 891, 2020 928, 2021 891, 2022 918, 2023 867, 2024 931.

### L10 — league size: 10

**Grade C: no accuracy claim on any surface. The numeral prints as a recorded prediction only.** Decision under method §3: numeral prints as a recorded prediction only.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 2479 | 2401 | 78 | 52.6% | 53.1% | 51%–55% | calibrated |
| 55%–60% | 2143 | 2076 | 67 | 57.4% | 59.0% | 57%–61% | calibrated |
| 60%–65% | 1651 | 1611 | 40 | 62.3% | 65.0% | 63%–68% | **off** |
| 65%–70% | 1117 | 1090 | 27 | 67.4% | 72.8% | 70%–75% | **off** |
| 70%–80% | 1065 | 1039 | 26 | 74.2% | 83.3% | 81%–86% | **off** |
| 80%–90% | 188 | 182 | 6 | 82.9% | 89.6% | 85%–94% | **off** |

Calls per season: 2014 772, 2015 813, 2016 742, 2017 794, 2018 773, 2019 766, 2020 815, 2021 777, 2022 800, 2023 774, 2024 828.

### L14 — league size: 14

**Grade C: no accuracy claim on any surface. The numeral prints as a recorded prediction only.** Decision under method §3: numeral prints as a recorded prediction only.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 3057 | 2921 | 136 | 52.4% | 53.9% | 52%–56% | calibrated |
| 55%–60% | 2593 | 2490 | 103 | 57.5% | 61.7% | 60%–64% | **off** |
| 60%–65% | 2090 | 1995 | 95 | 62.4% | 68.1% | 66%–70% | **off** |
| 65%–70% | 1569 | 1517 | 52 | 67.4% | 74.8% | 72%–77% | **off** |
| 70%–80% | 1780 | 1733 | 47 | 74.1% | 83.8% | 82%–85% | **off** |
| 80%–90% | 392 | 387 | 5 | 83.2% | 90.2% | 87%–93% | **off** |

Calls per season: 2014 1112, 2015 1088, 2016 990, 2017 1020, 2018 1035, 2019 1023, 2020 1038, 2021 1037, 2022 1051, 2023 1002, 2024 1092.

### L8 — league size: 8

**Grade C: no accuracy claim on any surface. The numeral prints as a recorded prediction only.** Decision under method §3: numeral prints as a recorded prediction only.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 2070 | 2019 | 51 | 52.4% | 54.1% | 52%–57% | calibrated |
| 55%–60% | 1779 | 1739 | 40 | 57.4% | 59.9% | 58%–62% | **off** |
| 60%–65% | 1329 | 1292 | 37 | 62.4% | 65.9% | 63%–69% | **off** |
| 65%–70% | 908 | 884 | 24 | 67.3% | 72.9% | 70%–76% | **off** |
| 70%–80% | 784 | 767 | 17 | 73.8% | 81.5% | 79%–85% | **off** |
| 80%–90% | 109 | 108 | 1 | 82.4% | 95.4% | 91%–99% | **off** |

Calls per season: 2014 661, 2015 630, 2016 607, 2017 608, 2018 660, 2019 606, 2020 643, 2021 616, 2022 650, 2023 625, 2024 673.

### TSF — lineup shape: superflex

**Grade C: no accuracy claim on any surface. The numeral prints as a recorded prediction only.** Decision under method §3: numeral prints as a recorded prediction only.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 3168 | 3070 | 98 | 52.4% | 52.3% | 50%–54% | calibrated |
| 55%–60% | 2752 | 2667 | 85 | 57.4% | 59.2% | 57%–61% | calibrated |
| 60%–65% | 2248 | 2182 | 66 | 62.5% | 68.2% | 66%–70% | **off** |
| 65%–70% | 1613 | 1561 | 52 | 67.3% | 73.2% | 71%–75% | **off** |
| 70%–80% | 1565 | 1514 | 51 | 74.1% | 83.9% | 82%–86% | **off** |
| 80%–90% | 345 | 343 | 2 | 83.5% | 91.5% | 89%–94% | **off** |

Calls per season: 2014 1103, 2015 1080, 2016 961, 2017 1045, 2018 1074, 2019 1060, 2020 1078, 2021 1025, 2022 1087, 2023 1058, 2024 1132.

### TNKD — lineup shape: no K or DEF

**Grade C: no accuracy claim on any surface. The numeral prints as a recorded prediction only.** Decision under method §3: numeral prints as a recorded prediction only.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 2294 | 2235 | 59 | 52.4% | 51.7% | 49%–54% | calibrated |
| 55%–60% | 2024 | 1963 | 61 | 57.4% | 59.0% | 57%–61% | calibrated |
| 60%–65% | 1776 | 1728 | 48 | 62.5% | 66.6% | 65%–69% | **off** |
| 65%–70% | 1323 | 1277 | 46 | 67.4% | 74.4% | 72%–77% | **off** |
| 70%–80% | 1350 | 1310 | 40 | 74.1% | 82.5% | 80%–85% | **off** |
| 80%–90% | 241 | 238 | 3 | 82.9% | 91.6% | 88%–95% | **off** |

Calls per season: 2014 867, 2015 848, 2016 754, 2017 820, 2018 833, 2019 793, 2020 858, 2021 801, 2022 831, 2023 762, 2024 843.

### W17 — weeks: 17-18

**Grade B: the measured figures may be stated as facts, alongside the failures.** Decision under method §3: numeral prints as a recorded prediction; the confidence page may state this setting's figures as facts beside its failures.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 270 | 256 | 14 | 52.5% | 53.1% | 46%–60% | calibrated |
| 55%–60% | 247 | 231 | 16 | 57.5% | 61.9% | 54%–70% | calibrated |
| 60%–65% | 194 | 179 | 15 | 62.5% | 65.4% | 58%–73% | calibrated |
| 65%–70% | 168 | 155 | 13 | 67.6% | 72.3% | 64%–80% | calibrated |
| 70%–80% | 214 | 201 | 13 | 74.3% | 78.6% | 69%–86% | calibrated |
| 80%–90% | 74 | 64 | 10 | 83.1% | 71.9% | 63%–80% | **off** |

Calls per season: 2014 76, 2015 81, 2016 78, 2017 84, 2018 77, 2019 77, 2020 79, 2021 154, 2022 156, 2023 145, 2024 161.

Diagnostic, not graded separately (method §1): week 17: 858 calls, hit rate 65.1%; week 18: 310 calls, hit rate 66.9%.
