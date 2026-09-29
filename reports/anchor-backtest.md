# Last season, all season — results (weeks 4–16, 2020–2024)

Generated 2026-09-29 22:48 UTC by `engine/anchor_backtest.py` at commit cc98c2a, under the
preregistration in `reports/anchor-method.md` (frozen before this ran). Every lineup is
the product's own `optimal_lineup`; every grade is the parent's `evaluate`.

## Decision

**It ships** in weeks 4–16 at λ_L = 0.25 with b′ = 1.4670, in the headline setup and every setup marked below.

- **C1 (lineups):** the arm's lineups won **179**, lost **176** and tied
  9 of the 364 team-weeks where the two lineups differed
  (of 780 in all). Exact two-sided sign test p = 0.9155.
  Mean points per differing team-week: +0.38 (95% interval
  -0.71 to +1.50, clustered by season-week). **Held.**
- **C2 (the number):** corrected held-out grade **B**.
  **Held.**

## The number, beside the shipped product's (2020–2024, corrected)

| Model | Calls | Hit rate | ECE | Judgeable bands | Calibrated | Resolution | Grade |
|---|---|---|---|---|---|---|---|
| Shipped, b = 1.3714 | 4768 | 65.5% | 1.1% | 7 | 7 | 35.4 | **B** |
| Arm λ_L = 0.25, b′ = 1.4670 | 4750 | 65.3% | 1.2% | 7 | 7 | 35.8 | **B** |

## Star benchings (method §4c — reported, not a clause)

A star ranked top 12 (QB, TE) or top 24 (RB, WR) at his position last season.
Counted only when he was available (not OUT on the Tuesday report, not on bye).

| Model | Stars benched | Per 1,000 team-weeks | Benched star outscored the weakest starter he could have replaced |
|---|---|---|---|
| Shipped | 1085 | 1391 | 399 of 1085 (37%) |
| Arm λ_L = 0.25 | 870 | 1115 | 297 of 870 (34%) |

## Sensitivity arms (reported, never substituted — method §2)

| Arm | Lineups W–L–T |
|---|---|
| λ_L = 0.125 | 113–118–7 (p = 0.7925) |
| λ_L = 0.5 | 225–262–10 (p = 0.1027) |

| Model | Calls | Hit rate | ECE | Judgeable bands | Calibrated | Resolution | Grade |
|---|---|---|---|---|---|---|---|
| λ_L = 0.125, b′ = 1.4767 | 4761 | 65.2% | 1.6% | 7 | 7 | 38.8 | **B** |
| λ_L = 0.5, b′ = 1.4474 | 4723 | 64.5% | 1.8% | 7 | 7 | 36.4 | **B** |

## The other setups (method §4d), with b′ = 1.4670

| Arm | Setting | Lineups W–L–T | Sign test p | Calls | ECE | Grade | Decision |
|---|---|---|---|---|---|---|---|
| S1 | scoring: half_ppr | 181–175–9 | 0.791 | 4774 | 1.5% | **B** | ships |
| S2 | scoring: standard | 165–144–11 | 0.255 | 4750 | 1.9% | **B** | ships |
| L10 | league size: 10 | 129–131–13 | 0.951 | 4161 | 1.7% | **B** | does not ship |
| L14 | league size: 14 | 170–180–19 | 0.631 | 5407 | 1.8% | **B** | does not ship |
| L8 | league size: 8 | 121–104–4 | 0.286 | 3391 | 1.1% | **B** | ships |
| TSF | lineup shape: superflex | 200–201–13 | 1.000 | 5646 | 1.2% | **B** | does not ship |
| TNKD | lineup shape: no K or DEF | 164–157–9 | 0.738 | 4294 | 1.3% | **B** | ships |

## What this is not

It is a fixed-roster league: no trades, drops or pickups, so it cannot isolate
the player who lost his job over the summer or mid-season — the case where last
season is the worst guide (method §6). A lineup that scored more in one week is
not a better decision every time; over five seasons of differing team-weeks it
is the right aggregate.
