# Recalibration, fitted on 2014–2019 and graded on 2020–2024

Generated 2026-09-29 10:27 UTC from commit `5846734`. Method frozen in advance:
`reports/recalibration-method.md`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.recalibration`.

The map is `p' = σ(b · logit(p))`: it keeps every pick and changes only the
number printed beside it. `b` was fitted on 5490 calls from
2014–2019 and never saw 2020–2024.

## Decision

- **b = 1.3714** (log-likelihood on the fit seasons: -3306.8
  at b, -3331.2 at b = 1).
- Headline on 2020–2024: raw **Grade C** (ECE 3.9%),
  recalibrated **Grade B** (ECE 1.1%).
- **SHIPS.** All three clauses of method §4 hold: reports apply the map in weeks 4–16, in every setting whose recalibrated grade is not D.

The measured figures may be stated as facts, alongside the failures — at the recalibrated grade.

## Headline, 2020–2024

#### Raw, 2020–2024 — Grade C

4551 calls, 4396 decided, hit rate 64.7%, ECE 3.9%, 6 judgeable
bands, 2 calibrated, resolution 34.9 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1290 | 1247 | 43 | 52.4% | 51.6% | 49%–54% | calibrated |
| 55%–60% | 1043 | 1005 | 38 | 57.4% | 59.9% | 56%–63% | calibrated |
| 60%–65% | 864 | 833 | 31 | 62.5% | 66.4% | 63%–70% | **off** |
| 65%–70% | 604 | 583 | 21 | 67.3% | 73.2% | 69%–77% | **off** |
| 70%–80% | 666 | 645 | 21 | 74.4% | 84.5% | 81%–88% | **off** |
| 80%–90% | 84 | 83 | 1 | 82.7% | 90.4% | 84%–96% | undecided |

#### Recalibrated, 2020–2024 — Grade B

4551 calls, 4396 decided, hit rate 64.7%, ECE 1.1%, 6 judgeable
bands, 6 calibrated, resolution 34.9 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 978 | 950 | 28 | 52.4% | 51.9% | 49%–55% | calibrated |
| 55%–60% | 823 | 789 | 34 | 57.5% | 55.5% | 52%–60% | calibrated |
| 60%–65% | 731 | 704 | 27 | 62.3% | 61.8% | 58%–66% | calibrated |
| 65%–70% | 663 | 640 | 23 | 67.5% | 67.5% | 64%–71% | calibrated |
| 70%–80% | 885 | 853 | 32 | 74.5% | 76.6% | 73%–80% | calibrated |
| 80%–90% | 445 | 434 | 11 | 83.9% | 85.3% | 82%–88% | calibrated |

## Setup arms, 2020–2024, same b

| Arm | Setting | Raw grade | Raw ECE | Recalibrated grade | Recalibrated ECE |
|---|---|---|---|---|---|
| S1 | scoring: half_ppr | C | 5.1% | B | 1.9% |
| S2 | scoring: standard | C | 5.2% | B | 1.7% |
| L10 | league size: 10 | B | 2.1% | B | 1.6% |
| L14 | league size: 14 | C | 5.2% | B | 1.4% |
| L8 | league size: 8 | C | 3.3% | B | 2.0% |
| TSF | lineup shape: superflex | C | 4.7% | B | 1.8% |
| TNKD | lineup shape: no K or DEF | C | 4.4% | B | 1.3% |

Weeks 17–18 and weeks 2–3 are not recalibrated (method §3).

### S1 — scoring: half_ppr

#### S1 raw — Grade C

4561 calls, 4405 decided, hit rate 66.2%, ECE 5.1%, 6 judgeable
bands, 0 calibrated, resolution 34.8 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1263 | 1216 | 47 | 52.4% | 55.9% | 53%–59% | **off** |
| 55%–60% | 1094 | 1043 | 51 | 57.4% | 62.1% | 59%–65% | **off** |
| 60%–65% | 853 | 829 | 24 | 62.3% | 65.9% | 63%–69% | **off** |
| 65%–70% | 683 | 661 | 22 | 67.4% | 74.3% | 71%–78% | **off** |
| 70%–80% | 587 | 575 | 12 | 73.9% | 82.8% | 80%–86% | **off** |
| 80%–90% | 81 | 81 | 0 | 82.4% | 91.4% | 85%–97% | **off** |

#### S1 recalibrated — Grade B

4561 calls, 4405 decided, hit rate 66.2%, ECE 1.9%, 6 judgeable
bands, 5 calibrated, resolution 34.8 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 916 | 885 | 31 | 52.3% | 53.8% | 50%–57% | calibrated |
| 55%–60% | 880 | 835 | 45 | 57.4% | 61.9% | 58%–66% | **off** |
| 60%–65% | 786 | 756 | 30 | 62.5% | 62.6% | 58%–66% | calibrated |
| 65%–70% | 622 | 606 | 16 | 67.4% | 66.3% | 62%–70% | calibrated |
| 70%–80% | 993 | 967 | 26 | 74.5% | 76.8% | 74%–79% | calibrated |
| 80%–90% | 343 | 335 | 8 | 84.1% | 84.8% | 80%–89% | calibrated |

### S2 — scoring: standard

#### S2 raw — Grade C

4535 calls, 4379 decided, hit rate 66.1%, ECE 5.2%, 6 judgeable
bands, 2 calibrated, resolution 30.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1261 | 1200 | 61 | 52.4% | 54.5% | 51%–58% | calibrated |
| 55%–60% | 1095 | 1056 | 39 | 57.5% | 64.8% | 62%–68% | **off** |
| 60%–65% | 899 | 867 | 32 | 62.4% | 66.9% | 64%–70% | **off** |
| 65%–70% | 612 | 603 | 9 | 67.3% | 71.5% | 68%–75% | **off** |
| 70%–80% | 613 | 600 | 13 | 73.9% | 83.7% | 80%–87% | **off** |
| 80%–90% | 54 | 52 | 2 | 83.1% | 84.6% | 75%–94% | calibrated |

#### S2 recalibrated — Grade B

4535 calls, 4379 decided, hit rate 66.1%, ECE 1.7%, 6 judgeable
bands, 5 calibrated, resolution 30.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 944 | 903 | 41 | 52.4% | 53.5% | 50%–57% | calibrated |
| 55%–60% | 834 | 794 | 40 | 57.5% | 61.8% | 58%–66% | **off** |
| 60%–65% | 782 | 755 | 27 | 62.4% | 64.2% | 61%–68% | calibrated |
| 65%–70% | 692 | 668 | 24 | 67.4% | 68.4% | 65%–72% | calibrated |
| 70%–80% | 918 | 902 | 16 | 74.5% | 75.4% | 72%–78% | calibrated |
| 80%–90% | 345 | 338 | 7 | 83.6% | 83.7% | 80%–87% | calibrated |

### L10 — league size: 10

#### L10 raw — Grade B

3994 calls, 3869 decided, hit rate 62.9%, ECE 2.1%, 6 judgeable
bands, 5 calibrated, resolution 34.2 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1132 | 1092 | 40 | 52.6% | 52.7% | 50%–56% | calibrated |
| 55%–60% | 991 | 958 | 33 | 57.3% | 57.4% | 54%–61% | calibrated |
| 60%–65% | 768 | 744 | 24 | 62.3% | 65.7% | 62%–70% | calibrated |
| 65%–70% | 543 | 525 | 18 | 67.3% | 69.9% | 66%–74% | calibrated |
| 70%–80% | 469 | 463 | 6 | 74.0% | 81.2% | 78%–85% | **off** |
| 80%–90% | 90 | 86 | 4 | 82.5% | 88.4% | 81%–95% | calibrated |

#### L10 recalibrated — Grade B

3994 calls, 3869 decided, hit rate 62.9%, ECE 1.6%, 6 judgeable
bands, 6 calibrated, resolution 34.2 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 792 | 763 | 29 | 52.5% | 52.8% | 49%–56% | calibrated |
| 55%–60% | 867 | 841 | 26 | 57.4% | 54.2% | 51%–58% | calibrated |
| 60%–65% | 673 | 650 | 23 | 62.5% | 61.1% | 57%–65% | calibrated |
| 65%–70% | 557 | 538 | 19 | 67.4% | 66.2% | 62%–71% | calibrated |
| 70%–80% | 752 | 733 | 19 | 74.3% | 72.6% | 69%–76% | calibrated |
| 80%–90% | 325 | 316 | 9 | 83.9% | 83.2% | 79%–87% | calibrated |

### L14 — league size: 14

#### L14 raw — Grade C

5220 calls, 5011 decided, hit rate 67.3%, ECE 5.2%, 6 judgeable
bands, 1 calibrated, resolution 36.5 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1296 | 1237 | 59 | 52.5% | 54.6% | 52%–57% | calibrated |
| 55%–60% | 1212 | 1163 | 49 | 57.5% | 62.5% | 60%–65% | **off** |
| 60%–65% | 964 | 919 | 45 | 62.4% | 67.1% | 64%–70% | **off** |
| 65%–70% | 756 | 725 | 31 | 67.4% | 75.2% | 72%–78% | **off** |
| 70%–80% | 817 | 794 | 23 | 74.0% | 82.0% | 79%–84% | **off** |
| 80%–90% | 172 | 170 | 2 | 83.1% | 90.6% | 86%–95% | **off** |

#### L14 recalibrated — Grade B

5220 calls, 5011 decided, hit rate 67.3%, ECE 1.4%, 7 judgeable
bands, 7 calibrated, resolution 36.5 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 957 | 911 | 46 | 52.5% | 53.2% | 50%–57% | calibrated |
| 55%–60% | 891 | 856 | 35 | 57.5% | 60.4% | 57%–64% | calibrated |
| 60%–65% | 887 | 852 | 35 | 62.4% | 62.7% | 60%–66% | calibrated |
| 65%–70% | 732 | 695 | 37 | 67.5% | 69.1% | 65%–73% | calibrated |
| 70%–80% | 1149 | 1108 | 41 | 74.7% | 76.6% | 74%–79% | calibrated |
| 80%–90% | 533 | 519 | 14 | 84.2% | 85.0% | 82%–88% | calibrated |
| 90%–100% | 71 | 70 | 1 | 92.3% | 94.3% | 88%–99% | calibrated |

### L8 — league size: 8

#### L8 raw — Grade C

3207 calls, 3134 decided, hit rate 63.5%, ECE 3.3%, 6 judgeable
bands, 2 calibrated, resolution 28.8 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 967 | 944 | 23 | 52.5% | 54.4% | 51%–58% | calibrated |
| 55%–60% | 840 | 826 | 14 | 57.4% | 58.1% | 55%–61% | calibrated |
| 60%–65% | 593 | 578 | 15 | 62.4% | 68.0% | 64%–72% | **off** |
| 65%–70% | 417 | 405 | 12 | 67.3% | 72.1% | 67%–77% | undecided |
| 70%–80% | 341 | 333 | 8 | 73.6% | 79.6% | 75%–84% | **off** |
| 80%–90% | 49 | 48 | 1 | 82.7% | 95.8% | 89%–100% | **off** |

#### L8 recalibrated — Grade B

3207 calls, 3134 decided, hit rate 63.5%, ECE 2.0%, 6 judgeable
bands, 5 calibrated, resolution 28.8 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 711 | 694 | 17 | 52.5% | 55.3% | 52%–59% | calibrated |
| 55%–60% | 674 | 661 | 13 | 57.5% | 53.6% | 51%–57% | **off** |
| 60%–65% | 560 | 551 | 9 | 62.4% | 62.8% | 58%–67% | calibrated |
| 65%–70% | 451 | 438 | 13 | 67.5% | 68.5% | 64%–73% | calibrated |
| 70%–80% | 607 | 589 | 18 | 74.4% | 73.3% | 69%–77% | calibrated |
| 80%–90% | 190 | 187 | 3 | 84.0% | 85.6% | 80%–90% | calibrated |

### TSF — lineup shape: superflex

#### TSF raw — Grade C

5380 calls, 5187 decided, hit rate 66.0%, ECE 4.7%, 6 judgeable
bands, 2 calibrated, resolution 34.4 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1510 | 1458 | 52 | 52.4% | 54.3% | 52%–57% | calibrated |
| 55%–60% | 1270 | 1228 | 42 | 57.4% | 59.8% | 57%–63% | calibrated |
| 60%–65% | 997 | 958 | 39 | 62.5% | 68.3% | 64%–72% | **off** |
| 65%–70% | 700 | 673 | 27 | 67.3% | 73.4% | 70%–77% | **off** |
| 70%–80% | 754 | 722 | 32 | 74.3% | 85.2% | 82%–88% | **off** |
| 80%–90% | 142 | 141 | 1 | 83.3% | 90.1% | 86%–95% | **off** |

#### TSF recalibrated — Grade B

5380 calls, 5187 decided, hit rate 66.0%, ECE 1.8%, 7 judgeable
bands, 6 calibrated, resolution 34.4 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1147 | 1110 | 37 | 52.4% | 54.1% | 51%–57% | calibrated |
| 55%–60% | 988 | 945 | 43 | 57.5% | 57.7% | 54%–61% | calibrated |
| 60%–65% | 851 | 825 | 26 | 62.3% | 60.1% | 56%–64% | calibrated |
| 65%–70% | 784 | 757 | 27 | 67.5% | 70.4% | 66%–74% | calibrated |
| 70%–80% | 1024 | 979 | 45 | 74.5% | 75.9% | 73%–79% | calibrated |
| 80%–90% | 515 | 500 | 15 | 83.9% | 87.0% | 84%–90% | calibrated |
| 90%–100% | 71 | 71 | 0 | 92.4% | 97.2% | 94%–100% | undecided |

### TNKD — lineup shape: no K or DEF

#### TNKD raw — Grade C

4095 calls, 3967 decided, hit rate 65.5%, ECE 4.4%, 6 judgeable
bands, 2 calibrated, resolution 34.6 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1082 | 1054 | 28 | 52.4% | 51.5% | 48%–55% | calibrated |
| 55%–60% | 925 | 892 | 33 | 57.4% | 60.0% | 57%–63% | calibrated |
| 60%–65% | 790 | 765 | 25 | 62.5% | 67.3% | 64%–71% | **off** |
| 65%–70% | 573 | 553 | 20 | 67.3% | 73.6% | 69%–78% | **off** |
| 70%–80% | 641 | 620 | 21 | 74.4% | 84.5% | 81%–88% | **off** |
| 80%–90% | 84 | 83 | 1 | 82.7% | 90.4% | 84%–96% | undecided |

#### TNKD recalibrated — Grade B

4095 calls, 3967 decided, hit rate 65.5%, ECE 1.3%, 6 judgeable
bands, 6 calibrated, resolution 34.6 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 821 | 801 | 20 | 52.5% | 52.1% | 48%–56% | calibrated |
| 55%–60% | 717 | 693 | 24 | 57.5% | 54.8% | 51%–59% | calibrated |
| 60%–65% | 646 | 623 | 23 | 62.4% | 62.6% | 59%–67% | calibrated |
| 65%–70% | 612 | 593 | 19 | 67.5% | 68.5% | 65%–72% | calibrated |
| 70%–80% | 838 | 807 | 31 | 74.5% | 76.8% | 73%–80% | calibrated |
| 80%–90% | 435 | 424 | 11 | 84.0% | 85.1% | 82%–88% | calibrated |
