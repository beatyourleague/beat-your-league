# The shipping gate, measured

Generated from cached data by `python -m engine.gate_backtest --league 289646328504385536`. The call set is the same frozen 2017-18 set the main backtest grades; the only thing added is the pre-kickoff injury report.

- call set: **2056**
- dropped, a player was OUT: 173
- dropped, a player was QUESTIONABLE: 286
- kept under the shipping gate: **1597** (77.7%)

The reconstruction covers the INJURY half of the gate only. Byes are resolved live from the NFL schedule and a player's historical team is not recoverable from today's players table, so a bye would have been caught separately and is not modelled here.

## Calibration under the shipping gate

The product publishes a confidence only when both players are confirmed active. That rule had never been measured — live snapshots start this season — so the headline table above describes a model with no gate, which is not the product anyone receives.

The gate is reconstructed here from the pre-kickoff injury report, which is legitimate to condition on: it is published before the games. This is NOT the availability-controlled diagnostic elsewhere in this document, which keeps head-to-heads where both players ended up scoring and so conditions on the result.

| Stated confidence | Decided (ungated) | Observed | Decided (gated) | Observed | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| 50-55% | 608 | 53.3% | 483 | 54.2% | calibrated |
| 55-60% | 525 | 53.0% | 404 | 53.2% | calibrated |
| 60-65% | 390 | 52.6% | 303 | 52.5% | off |
| 65-70% | 245 | 54.3% | 191 | 53.9% | off |
| 70-80% | 208 | 56.2% | 166 | 58.4% | off |
| 80-90% | 37 | 54.1% | 25 | 48.0% | too few |

Buckets need 30 decided calls to be judged. Injury history: nflverse (nflverse-data), CC-BY-4.0.

### What this settles

- The gate keeps 1597 of 2056 calls (77.7%); the rest had a player carrying a designation before kickoff.
- Calibrated buckets go from 1 of 6 to 2 of 5. **It is an improvement, not a rescue.**
- Resolution stays flat: judged buckets span 6.0 points of observed hit rate across the whole stated range, so the number still barely sorts good calls from bad ones.

The conclusion is uncomfortable and it is the one the evidence supports: filtering on the injury report does NOT recover the calibration seen in the availability-controlled diagnostic. That table conditions on both players having scored, and most of what it was really selecting for is not injury at all — it is healthy players who were never going to get the ball. A backup in a committee carries no designation.

So the shipping gate is worth keeping as an honesty measure — it stops us printing a number about someone who is doubtful — but it does not by itself earn a published accuracy claim, and this document does not make one.
