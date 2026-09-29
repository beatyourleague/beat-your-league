# Recalibrating the confidence number — preregistered method

**Status: preregistration. Written and committed before any number from this run exists
(CLAUDE.md principle 2).** Target module `engine/recalibration.py`; output
`reports/recalibration-backtest.md`. Nothing below may change after the first output is read.
Changing anything voids the run and needs a new preregistration with a new commit.

**Why this exists.** The published grading (`reports/nflverse-backtest.md`, Grade C) and every
setup arm (`reports/setups-backtest.md`) show one systematic error: in weeks 4–16, every band
that fails lands ABOVE its stated rate. The model ranks calls well (resolution ~35 points) and
understates how often its picks win. Grade B needs half the judgeable bands calibrated; the
headline has 2 of 6. A correction that keeps the ranking and moves the stated number toward
what calls like it have won is the honest fix — but a correction fitted and graded on the same
seasons would grade itself. So it is fitted on the early seasons and graded only on the late
ones, and the split, the map and the decision are fixed here first.

---

## 1. The map

    p' = σ(b · logit(p)),   p clipped to [0.001, 0.999]

One parameter, `b > 0`. It is monotone (the order of calls never changes), symmetric
(`g(1−p) = 1 − g(p)`), and fixes 0.5, so a call above 50% stays above 50% and **no pick, no
seat and no recommendation ever changes** — only the number printed beside it. `b > 1`
spreads numbers away from 50%, `b < 1` pulls them toward it, `b = 1` is the identity.

One parameter on purpose: the error is one systematic direction, and a flexible map (isotonic,
per-bucket) fitted on six seasons would fit their noise.

## 2. The split

- **Fit:** seasons **2014–2019** (6), headline configuration (full PPR, 12 teams, lineup T1,
  weeks 4–16, seed 0), decided calls only (ties excluded, as everywhere).
- **Grade:** seasons **2020–2024** (5), never seen by the fit.
- Calls come from the parent harness's `calls_for_season` unchanged; the map is applied to each
  call's confidence after the fact, which is exact because it changes no pick (§1).

`b` = the maximum-likelihood value on the fit seasons: golden-section search over [0.25, 4.0]
to a tolerance of 1e-4, deterministic. It is printed to four decimals in the report.

## 3. The grade

On the grade seasons, graded by the parent method's §1 rule through the parent's own
`evaluate` (clustered intervals, clusters = (season, week), 2,000 resamples, seed 20260821):

- **raw** — the model as it ships today, on 2020–2024;
- **recalibrated** — the same calls with `p' = g(p)`, on 2020–2024.

The raw 2020–2024 grade is computed so the comparison is like for like: same seasons, same
calls, one difference. Grade A stays unreachable (seed 0 only, as in the setups method).

The setup arms S1, S2, L10, L14, L8, TSF and TNKD (`reports/setups-method.md`) are re-graded on
2020–2024 raw and recalibrated with the **same** `b` — none gets its own fit. Weeks 17–18 (arm
W17) are **not recalibrated**: their one failing band landed BELOW stated, the opposite
direction, so a map fitted on weeks 4–16 must not be pushed onto them. Weeks 2–3 (the
early-season arm) are not recalibrated either; they keep their own Grade B.

## 4. The decision — frozen before the run

**Ship the recalibration if and only if all three hold on the headline, 2020–2024:**

1. the recalibrated grade is not D;
2. the recalibrated grade is at least the raw grade (D < C < B);
3. the recalibrated expected calibration error is strictly lower than the raw one.

**If it ships:**
- Every report applies `g` with the fitted `b` to every confidence in weeks 4–16, in every
  setting, and records the recalibrated number in the ledger (the number printed is the number
  graded).
- Per setting, the recalibrated 2020–2024 grade governs as in `reports/setups-method.md` §3: a
  setting that grades D withholds the numeral.
- The confidence page leads with the recalibrated **held-out** grade and says which seasons it
  was graded on and which it was fitted on. The full 2014–2024 raw grading stays published as
  the record of the model before the correction.
- At Grade B the measured figures may be stated as facts beside the failures. The banned words
  ("calibrated", "tested", "proven", "accurate", "we hit X%") stay banned below Grade A.

**If it does not ship:** the product is unchanged, and the report and the confidence page say
the correction was tried, what it did, and why the rule kept it out.

**What it may not do.** No second fit, other split, other map or other search range after an
output is read. A result that narrowly misses is not re-run.

## 5. What invalidates this exercise

- Any change to §1–§4 after an output has been read.
- Any use of a 2020–2024 outcome in fitting `b`.
- Calls computed by anything other than the parent's `calls_for_season`, or grades by anything
  other than its `evaluate`.

## 6. Outputs

`reports/recalibration-backtest.md`, generated, never hand-edited: the commit sha; `b`; the
fit-season log-likelihood at `b` and at `b = 1`; the headline raw and recalibrated tables and
grades on 2020–2024; the same for each setup arm; the §4 decision, stated.

## 7. Freeze procedure

1. This document and `engine/recalibration.py` are committed together, before the first run.
2. The runner is run once. §4 is applied, and only then are product changes made.
3. Corrections, if ever needed, are appended below with a date, never edited into the text.

## 8. CORRECTIONS — appended, never edited into the text above

*(none)*
