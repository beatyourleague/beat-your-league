# Who he plays, and whether he was really missing — results

Generated 2026-09-29 23:51 UTC by `engine/context_backtest.py` at commit 3f224ae, under the
preregistration in `reports/context-method.md` (frozen before this ran).

## Decision

**Arm AV ships** in weeks 4–16 with b′ = 1.2289, in the headline setup and every setup marked below.

## 1. The choice, made on 2014–2019 only (method §3.1)

Each arm's lineups against the shipped lineups, where they differed.

| Arm | W–L–T | Margin |
|---|---|---|
| A | 195–191–17 | +4 |
| AM | 296–321–13 | -25 |
| AV | 279–258–16 | +21 |
| AMV | 331–328–9 | +3 |

Chosen: **AV**.

## 2. The confirmation, on held-out 2020–2024

- **C1 (lineups):** won **243**, lost **226**, tied 16 of the
  485 differing team-weeks (of 780). Exact two-sided
  sign test p = 0.4601. Mean points per differing team-week +0.74
  (95% interval -0.35 to +1.89, clustered by season-week).
  **Held.**
- **C2 (the number):** corrected grade **B**.
  **Held.**

| Model | Calls | Hit rate | ECE | Judgeable bands | Calibrated | Resolution | Grade |
|---|---|---|---|---|---|---|---|
| Shipped (anchor), b = 1.467 | 4750 | 65.3% | 1.2% | 7 | 7 | 35.8 | **B** |
| Arm AV, b′ = 1.2289 | 4712 | 66.1% | 1.9% | 7 | 7 | 35.9 | **B** |

Star benchings (reported): shipped benched 870 available stars, who
outscored the weakest starter they could have replaced 297 times; the arm
benched 831 (268 outscored).

## 3. The other arms on 2020–2024 (printed after the decision; never substituted)

| Arm | W–L–T | Sign test p |
|---|---|---|
| A | 144–138–14 | 0.7660 |
| AM | 243–253–18 | 0.6862 |
| AMV | 290–294–13 | 0.9012 |

## 4. The setups (method §4d), with b′ = 1.2289

| Arm | Setting | Lineups W–L–T | Sign test p | Calls | ECE | Grade | Decision |
|---|---|---|---|---|---|---|---|
| S1 | scoring: half_ppr | 228–220–14 | 0.741 | 4720 | 1.9% | **B** | ships |
| S2 | scoring: standard | 220–202–19 | 0.408 | 4718 | 2.3% | **B** | ships |
| L10 | league size: 10 | 240–225–11 | 0.516 | 4120 | 2.0% | **B** | ships |
| L14 | league size: 14 | 277–263–17 | 0.576 | 5365 | 1.3% | **B** | ships |
| L8 | league size: 8 | 194–164–4 | 0.125 | 3381 | 2.6% | **B** | ships |
| TSF | lineup shape: superflex | 293–270–22 | 0.354 | 5591 | 2.7% | **B** | ships |
| TNKD | lineup shape: no K or DEF | 212–196–15 | 0.458 | 4256 | 1.8% | **B** | ships |

## What this is not

The backtest reads CLOSING lines; the product reads Tuesday's (method §6). The
harness never trades or drops.
