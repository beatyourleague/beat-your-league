# Combined settings and team defenses, graded as they ship

Generated 2026-09-29 10:44 UTC from commit `6833098`. Method frozen in advance:
`reports/round-two-method.md`, committed with this runner before it was run. Reproduce with
`.venv/bin/python -m engine.round_two_backtest`.

Graded on 2020–2024 only, every confidence through the published recalibration
(b = 1.3714), weeks 4–16. The raw grade beside each is a diagnostic and
decides nothing.

## Decisions

- Combined settings withheld (grade D): none.
- Team defenses: recalibrated grade **D** on 5 judgeable
  bands — **DOES NOT SHIP**: the defense gate stays closed (method §2 requires C or
  better and at least 2 judgeable bands).

## Summary

| Arm | Setup | Calls | Decided | Grade (as shipped) | ECE | Raw grade | Raw ECE | Judgeable |
|---|---|---|---|---|---|---|---|---|
| X1 | half_ppr, 10 teams, standard | 3962 | 3849 | **B** | 1.6% | B | 3.0% | 6 |
| X2 | half_ppr, 14 teams, standard | 5236 | 5051 | **B** | 1.5% | C | 5.1% | 7 |
| X3 | standard, 10 teams, standard | 3953 | 3844 | **B** | 2.2% | C | 3.5% | 6 |
| X4 | standard, 14 teams, standard | 5123 | 4919 | **B** | 2.1% | C | 5.5% | 7 |
| X5 | half_ppr, 12 teams, superflex | 5325 | 5146 | **B** | 1.7% | C | 5.2% | 7 |
| X6 | ppr, 10 teams, superflex | 4647 | 4526 | **B** | 1.6% | B | 2.6% | 7 |
| X7 | ppr, 14 teams, superflex | 6047 | 5801 | **B** | 2.1% | C | 5.9% | 7 |
| X8 | half_ppr, 12 teams, no K or DEF | 4104 | 3977 | **B** | 2.0% | C | 5.5% | 6 |
| X9 | half_ppr, 8 teams, standard | 3196 | 3105 | **B** | 1.7% | B | 1.9% | 6 |
| DEF | team defenses, full PPR, 12 teams, standard | 667 | 624 | **D** | 9.5% | D | 5.6% | 5 |

## Team defenses

#### DEF recalibrated, 2020–2024 — Grade D

667 calls, 624 decided, hit rate 52.9%, ECE 9.5%, 5 judgeable
bands, 2 calibrated, resolution -1.6 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 155 | 145 | 10 | 52.4% | 46.2% | 39%–54% | calibrated |
| 55%–60% | 168 | 154 | 14 | 57.6% | 59.7% | 53%–67% | calibrated |
| 60%–65% | 137 | 129 | 8 | 62.4% | 51.9% | 43%–61% | **off** |
| 65%–70% | 110 | 104 | 6 | 67.2% | 53.8% | 45%–62% | **off** |
| 70%–80% | 90 | 85 | 5 | 73.1% | 51.8% | 42%–64% | **off** |

#### DEF raw, 2020–2024 (diagnostic) — Grade D

667 calls, 624 decided, hit rate 52.9%, ECE 5.6%, 4 judgeable
bands, 2 calibrated, resolution -1.6 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 208 | 194 | 14 | 52.4% | 49.5% | 43%–56% | calibrated |
| 55%–60% | 218 | 202 | 16 | 57.4% | 55.9% | 49%–63% | calibrated |
| 60%–65% | 145 | 137 | 8 | 62.3% | 53.3% | 45%–61% | **off** |
| 65%–70% | 82 | 77 | 5 | 67.1% | 53.2% | 43%–64% | **off** |

#### DEF raw, 2014–2024 (diagnostic) — Grade C

1466 calls, 1375 decided, hit rate 54.0%, ECE 3.7%, 5 judgeable
bands, 3 calibrated, resolution 1.5 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 535 | 507 | 28 | 52.3% | 52.3% | 48%–56% | calibrated |
| 55%–60% | 486 | 451 | 35 | 57.3% | 55.7% | 51%–60% | calibrated |
| 60%–65% | 279 | 261 | 18 | 62.2% | 53.6% | 48%–60% | **off** |
| 65%–70% | 133 | 124 | 9 | 67.1% | 53.2% | 45%–62% | **off** |
| 70%–80% | 33 | 32 | 1 | 72.2% | 62.5% | 47%–77% | calibrated |

## Combined settings

### X1 — half_ppr, 10 teams, standard

#### X1 recalibrated — Grade B

3962 calls, 3849 decided, hit rate 63.8%, ECE 1.6%, 6 judgeable
bands, 5 calibrated, resolution 28.6 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 821 | 791 | 30 | 52.4% | 54.7% | 52%–58% | calibrated |
| 55%–60% | 805 | 781 | 24 | 57.5% | 57.4% | 54%–61% | calibrated |
| 60%–65% | 669 | 651 | 18 | 62.5% | 61.4% | 58%–65% | calibrated |
| 65%–70% | 598 | 580 | 18 | 67.4% | 67.2% | 64%–71% | calibrated |
| 70%–80% | 761 | 747 | 14 | 74.3% | 70.4% | 67%–74% | **off** |
| 80%–90% | 286 | 277 | 9 | 84.0% | 85.9% | 82%–90% | calibrated |

#### X1 raw (diagnostic) — Grade B

3962 calls, 3849 decided, hit rate 63.8%, ECE 3.0%, 6 judgeable
bands, 4 calibrated, resolution 28.6 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1119 | 1081 | 38 | 52.5% | 54.8% | 52%–58% | calibrated |
| 55%–60% | 989 | 959 | 30 | 57.4% | 60.4% | 57%–64% | calibrated |
| 60%–65% | 789 | 767 | 22 | 62.4% | 65.6% | 63%–68% | undecided |
| 65%–70% | 549 | 538 | 11 | 67.4% | 69.3% | 65%–73% | calibrated |
| 70%–80% | 442 | 433 | 9 | 74.0% | 79.9% | 77%–83% | **off** |
| 80%–90% | 73 | 70 | 3 | 82.6% | 85.7% | 76%–94% | calibrated |

### X2 — half_ppr, 14 teams, standard

#### X2 recalibrated — Grade B

5236 calls, 5051 decided, hit rate 66.7%, ECE 1.5%, 7 judgeable
bands, 4 calibrated, resolution 35.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1036 | 999 | 37 | 52.5% | 52.6% | 49%–56% | calibrated |
| 55%–60% | 979 | 943 | 36 | 57.5% | 57.4% | 54%–61% | calibrated |
| 60%–65% | 825 | 793 | 32 | 62.5% | 63.2% | 60%–66% | calibrated |
| 65%–70% | 699 | 678 | 21 | 67.4% | 71.1% | 68%–74% | **off** |
| 70%–80% | 1177 | 1130 | 47 | 74.7% | 77.9% | 75%–81% | **off** |
| 80%–90% | 463 | 451 | 12 | 84.1% | 85.4% | 82%–88% | calibrated |
| 90%–100% | 57 | 57 | 0 | 91.7% | 96.5% | 92%–100% | undecided |

#### X2 raw (diagnostic) — Grade C

5236 calls, 5051 decided, hit rate 66.7%, ECE 5.1%, 6 judgeable
bands, 2 calibrated, resolution 35.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1395 | 1345 | 50 | 52.4% | 53.5% | 50%–57% | calibrated |
| 55%–60% | 1213 | 1168 | 45 | 57.4% | 59.8% | 57%–62% | calibrated |
| 60%–65% | 935 | 904 | 31 | 62.4% | 70.2% | 67%–73% | **off** |
| 65%–70% | 785 | 753 | 32 | 67.4% | 77.7% | 75%–81% | **off** |
| 70%–80% | 751 | 726 | 25 | 73.8% | 80.4% | 77%–84% | **off** |
| 80%–90% | 157 | 155 | 2 | 82.8% | 94.8% | 91%–98% | **off** |

### X3 — standard, 10 teams, standard

#### X3 recalibrated — Grade B

3953 calls, 3844 decided, hit rate 64.1%, ECE 2.2%, 6 judgeable
bands, 5 calibrated, resolution 30.2 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 838 | 813 | 25 | 52.6% | 53.9% | 50%–57% | calibrated |
| 55%–60% | 776 | 746 | 30 | 57.4% | 61.3% | 57%–65% | **off** |
| 60%–65% | 754 | 736 | 18 | 62.5% | 61.5% | 58%–65% | calibrated |
| 65%–70% | 550 | 536 | 14 | 67.4% | 65.5% | 62%–69% | calibrated |
| 70%–80% | 742 | 724 | 18 | 74.2% | 71.4% | 68%–75% | calibrated |
| 80%–90% | 279 | 275 | 4 | 84.0% | 85.8% | 81%–90% | calibrated |

#### X3 raw (diagnostic) — Grade C

3953 calls, 3844 decided, hit rate 64.1%, ECE 3.5%, 6 judgeable
bands, 2 calibrated, resolution 30.2 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1134 | 1101 | 33 | 52.5% | 55.3% | 53%–58% | undecided |
| 55%–60% | 1010 | 974 | 36 | 57.5% | 62.7% | 59%–66% | **off** |
| 60%–65% | 775 | 757 | 18 | 62.2% | 63.3% | 60%–67% | calibrated |
| 65%–70% | 542 | 527 | 15 | 67.3% | 69.4% | 65%–74% | calibrated |
| 70%–80% | 426 | 420 | 6 | 74.0% | 81.0% | 76%–85% | **off** |
| 80%–90% | 66 | 65 | 1 | 82.0% | 90.8% | 85%–97% | undecided |

### X4 — standard, 14 teams, standard

#### X4 recalibrated — Grade B

5123 calls, 4919 decided, hit rate 66.7%, ECE 2.1%, 7 judgeable
bands, 5 calibrated, resolution 30.8 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1070 | 1033 | 37 | 52.5% | 56.7% | 54%–59% | **off** |
| 55%–60% | 1019 | 966 | 53 | 57.3% | 56.9% | 53%–60% | calibrated |
| 60%–65% | 799 | 769 | 30 | 62.5% | 65.0% | 62%–68% | calibrated |
| 65%–70% | 714 | 685 | 29 | 67.3% | 68.5% | 65%–72% | calibrated |
| 70%–80% | 995 | 960 | 35 | 74.6% | 77.2% | 74%–80% | calibrated |
| 80%–90% | 463 | 444 | 19 | 83.8% | 84.2% | 81%–88% | calibrated |
| 90%–100% | 63 | 62 | 1 | 92.0% | 96.8% | 92%–100% | undecided |

#### X4 raw (diagnostic) — Grade C

5123 calls, 4919 decided, hit rate 66.7%, ECE 5.5%, 6 judgeable
bands, 0 calibrated, resolution 30.8 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1488 | 1433 | 55 | 52.5% | 55.7% | 53%–58% | **off** |
| 55%–60% | 1185 | 1123 | 62 | 57.4% | 62.6% | 60%–65% | **off** |
| 60%–65% | 934 | 902 | 32 | 62.4% | 67.4% | 64%–71% | **off** |
| 65%–70% | 679 | 653 | 26 | 67.5% | 75.2% | 71%–79% | **off** |
| 70%–80% | 692 | 667 | 25 | 74.0% | 81.9% | 79%–85% | **off** |
| 80%–90% | 145 | 141 | 4 | 83.3% | 95.0% | 91%–98% | **off** |

### X5 — half_ppr, 12 teams, superflex

#### X5 recalibrated — Grade B

5325 calls, 5146 decided, hit rate 66.7%, ECE 1.7%, 7 judgeable
bands, 5 calibrated, resolution 35.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1082 | 1043 | 39 | 52.4% | 52.4% | 50%–55% | calibrated |
| 55%–60% | 985 | 933 | 52 | 57.4% | 60.5% | 57%–64% | calibrated |
| 60%–65% | 868 | 839 | 29 | 62.4% | 64.6% | 61%–68% | calibrated |
| 65%–70% | 730 | 709 | 21 | 67.4% | 68.1% | 65%–71% | calibrated |
| 70%–80% | 1158 | 1130 | 28 | 74.5% | 77.0% | 75%–79% | undecided |
| 80%–90% | 444 | 436 | 8 | 84.1% | 84.4% | 82%–87% | calibrated |
| 90%–100% | 58 | 56 | 2 | 92.8% | 100.0% | 100%–100% | **off** |

#### X5 raw (diagnostic) — Grade C

5325 calls, 5146 decided, hit rate 66.7%, ECE 5.2%, 6 judgeable
bands, 1 calibrated, resolution 35.0 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1466 | 1408 | 58 | 52.4% | 54.0% | 52%–57% | calibrated |
| 55%–60% | 1242 | 1186 | 56 | 57.4% | 62.4% | 59%–66% | **off** |
| 60%–65% | 964 | 937 | 27 | 62.4% | 68.4% | 65%–71% | **off** |
| 65%–70% | 806 | 787 | 19 | 67.5% | 76.5% | 74%–79% | **off** |
| 70%–80% | 711 | 695 | 16 | 74.0% | 81.0% | 78%–84% | **off** |
| 80%–90% | 128 | 125 | 3 | 83.2% | 92.0% | 87%–96% | **off** |

### X6 — ppr, 10 teams, superflex

#### X6 recalibrated — Grade B

4647 calls, 4526 decided, hit rate 63.3%, ECE 1.6%, 7 judgeable
bands, 7 calibrated, resolution 36.5 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 974 | 946 | 28 | 52.5% | 53.1% | 50%–56% | calibrated |
| 55%–60% | 1000 | 971 | 29 | 57.4% | 54.6% | 51%–58% | calibrated |
| 60%–65% | 747 | 723 | 24 | 62.5% | 60.7% | 57%–65% | calibrated |
| 65%–70% | 642 | 629 | 13 | 67.4% | 65.5% | 61%–70% | calibrated |
| 70%–80% | 888 | 866 | 22 | 74.4% | 73.7% | 70%–77% | calibrated |
| 80%–90% | 338 | 333 | 5 | 84.0% | 86.2% | 82%–90% | calibrated |
| 90%–100% | 58 | 58 | 0 | 92.5% | 94.8% | 88%–100% | calibrated |

#### X6 raw (diagnostic) — Grade B

4647 calls, 4526 decided, hit rate 63.3%, ECE 2.6%, 6 judgeable
bands, 4 calibrated, resolution 36.5 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1358 | 1318 | 40 | 52.5% | 53.4% | 50%–56% | calibrated |
| 55%–60% | 1139 | 1106 | 33 | 57.3% | 57.1% | 54%–60% | calibrated |
| 60%–65% | 873 | 851 | 22 | 62.3% | 64.9% | 61%–69% | calibrated |
| 65%–70% | 622 | 606 | 16 | 67.4% | 71.0% | 67%–75% | calibrated |
| 70%–80% | 530 | 522 | 8 | 73.8% | 83.0% | 79%–86% | **off** |
| 80%–90% | 122 | 120 | 2 | 83.6% | 91.7% | 86%–97% | **off** |

### X7 — ppr, 14 teams, superflex

#### X7 recalibrated — Grade B

6047 calls, 5801 decided, hit rate 68.1%, ECE 2.1%, 7 judgeable
bands, 4 calibrated, resolution 37.9 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1114 | 1051 | 63 | 52.5% | 53.9% | 51%–56% | calibrated |
| 55%–60% | 1048 | 1002 | 46 | 57.5% | 60.6% | 57%–64% | calibrated |
| 60%–65% | 966 | 921 | 45 | 62.4% | 62.4% | 59%–65% | calibrated |
| 65%–70% | 831 | 796 | 35 | 67.5% | 69.5% | 66%–73% | calibrated |
| 70%–80% | 1356 | 1315 | 41 | 74.6% | 77.5% | 75%–80% | **off** |
| 80%–90% | 627 | 613 | 14 | 84.2% | 86.9% | 84%–89% | undecided |
| 90%–100% | 105 | 103 | 2 | 92.3% | 96.1% | 93%–99% | undecided |

#### X7 raw (diagnostic) — Grade C

6047 calls, 5801 decided, hit rate 68.1%, ECE 5.9%, 6 judgeable
bands, 1 calibrated, resolution 37.9 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1495 | 1411 | 84 | 52.4% | 54.1% | 51%–56% | calibrated |
| 55%–60% | 1379 | 1324 | 55 | 57.4% | 63.1% | 60%–66% | **off** |
| 60%–65% | 1088 | 1038 | 50 | 62.4% | 68.1% | 65%–71% | **off** |
| 65%–70% | 917 | 883 | 34 | 67.4% | 75.4% | 73%–78% | **off** |
| 70%–80% | 924 | 906 | 18 | 74.0% | 84.0% | 82%–86% | **off** |
| 80%–90% | 241 | 236 | 5 | 83.3% | 92.8% | 89%–96% | **off** |

### X8 — half_ppr, 12 teams, no K or DEF

#### X8 recalibrated — Grade B

4104 calls, 3977 decided, hit rate 67.0%, ECE 2.0%, 6 judgeable
bands, 5 calibrated, resolution 33.2 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 765 | 742 | 23 | 52.4% | 54.6% | 51%–59% | calibrated |
| 55%–60% | 779 | 742 | 37 | 57.4% | 61.6% | 58%–65% | **off** |
| 60%–65% | 699 | 675 | 24 | 62.5% | 63.6% | 59%–67% | calibrated |
| 65%–70% | 568 | 557 | 11 | 67.4% | 67.0% | 63%–71% | calibrated |
| 70%–80% | 939 | 914 | 25 | 74.6% | 77.0% | 74%–80% | calibrated |
| 80%–90% | 333 | 326 | 7 | 84.2% | 84.4% | 80%–89% | calibrated |

#### X8 raw (diagnostic) — Grade C

4104 calls, 3977 decided, hit rate 67.0%, ECE 5.5%, 6 judgeable
bands, 0 calibrated, resolution 33.2 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 1068 | 1034 | 34 | 52.5% | 56.7% | 53%–60% | **off** |
| 55%–60% | 973 | 929 | 44 | 57.4% | 62.2% | 59%–66% | **off** |
| 60%–65% | 774 | 757 | 17 | 62.3% | 66.6% | 63%–70% | **off** |
| 65%–70% | 647 | 626 | 21 | 67.4% | 74.4% | 71%–78% | **off** |
| 70%–80% | 561 | 550 | 11 | 73.9% | 82.7% | 80%–86% | **off** |
| 80%–90% | 81 | 81 | 0 | 82.4% | 91.4% | 85%–97% | **off** |

### X9 — half_ppr, 8 teams, standard

#### X9 recalibrated — Grade B

3196 calls, 3105 decided, hit rate 62.2%, ECE 1.7%, 6 judgeable
bands, 6 calibrated, resolution 29.4 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 671 | 648 | 23 | 52.5% | 50.6% | 47%–54% | calibrated |
| 55%–60% | 690 | 673 | 17 | 57.5% | 57.8% | 54%–61% | calibrated |
| 60%–65% | 569 | 554 | 15 | 62.4% | 62.8% | 58%–67% | calibrated |
| 65%–70% | 473 | 460 | 13 | 67.4% | 64.3% | 60%–69% | calibrated |
| 70%–80% | 593 | 575 | 18 | 74.0% | 71.3% | 68%–75% | calibrated |
| 80%–90% | 186 | 181 | 5 | 83.8% | 80.7% | 74%–86% | calibrated |

#### X9 raw (diagnostic) — Grade B

3196 calls, 3105 decided, hit rate 62.2%, ECE 1.9%, 6 judgeable
bands, 5 calibrated, resolution 29.4 points.

| Bucket | Graded | Decided | Ties | Stated | Observed | Clustered 95% | Verdict |
|---|---|---|---|---|---|---|---|
| 50%–55% | 931 | 903 | 28 | 52.5% | 52.6% | 50%–56% | calibrated |
| 55%–60% | 848 | 824 | 24 | 57.4% | 60.2% | 56%–64% | calibrated |
| 60%–65% | 628 | 612 | 16 | 62.4% | 64.1% | 60%–68% | calibrated |
| 65%–70% | 425 | 412 | 13 | 67.1% | 69.7% | 65%–74% | calibrated |
| 70%–80% | 319 | 309 | 10 | 73.6% | 77.0% | 73%–81% | calibrated |
| 80%–90% | 43 | 43 | 0 | 82.5% | 93.0% | 85%–100% | undecided |
