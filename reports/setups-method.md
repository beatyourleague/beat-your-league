# Other setups — preregistered method (scoring, league size, lineup shape, weeks 17–18)

**Status: preregistration. Written and committed before any number from these runs exists
(CLAUDE.md principle 2).** Target module `engine/setups_backtest.py`; output
`reports/setups-backtest.md`. Nothing below may change after the first output is read.
Changing anything voids the run and needs a new preregistration with a new commit.

**Why this exists.** The published grading (`reports/nflverse-backtest.md`, Grade C) measured
one setup: full PPR, 12 teams, the standard lineup (T1), weeks 4–16. The product prints the
same numeral for every setup the signup page offers. The parent method's correction C2
(`reports/nflverse-backtest-method.md` §15) lists those setups as graded by nothing. This run
grades them, one setting at a time.

---

## 1. The arms

Every arm changes exactly ONE setting from the parent's headline configuration and keeps
everything else identical: seasons 2014–2024, seed 0, depth multiplier 2.0, the W−1
availability gate, row-presence appearance signal, the parent's positional prior, team
defenses excluded exactly as the parent excludes them.

| Arm | Setting varied | Value | Weeks | Status |
|---|---|---|---|---|
| S1 | scoring preset | half_ppr | 4–16 | **already preregistered** — parent §9 arm C |
| S2 | scoring preset | standard | 4–16 | **already preregistered** — parent §9 arm C |
| L10 | league size | 10 | 4–16 | **already preregistered** — parent §9 arm E |
| L14 | league size | 14 | 4–16 | **already preregistered** — parent §9 arm E |
| L8 | league size | 8 | 4–16 | new here (the signup page offers 8) |
| TSF | lineup shape | superflex: QB RB RB WR WR TE FLEX SUPER_FLEX K DEF | 4–16 | new here |
| TNKD | lineup shape | no K or DEF: QB RB RB WR WR TE FLEX | 4–16 | new here |
| W17 | weeks | 17 and 18, pooled | 17–18 | new here |

Lineup shapes are the product's own (`run/trial.py` `TEMPLATES`, `site/join/roster.js`), so
what is graded is what ships. Arms S1, S2, L10 and L14 were preregistered on Aug 21 2026 and
never run; this document fixes only their runner and output, not their definition.

**W17 is its own population.** Weeks 17–18 are fantasy championship weeks and the NFL's
resting weeks. Week 18 exists only from 2021 (17-game seasons); in 2014–2020 week 17 was the
final week. The two weeks are pooled for the grade and reported separately as diagnostics.

## 2. The grade — the parent's rule, unchanged, per arm

Each arm is graded **individually** by the parent method's §1 table, computed by the same
function (`engine.nflverse_backtest.evaluate` / `_grade`) on that arm's calls alone, with the
parent's clustered intervals (§8: clusters = (season, week), 2,000 resamples, seed 20260821).
No threshold is changed. No arm is pooled with another or with the headline.

**Grade A is unreachable here by construction:** the parent requires seed stability across 20
seeds and every arm passing, and these runs are seed 0 only. An arm that meets every other A
clause is recorded as B.

## 3. The decision — frozen before the run

The parent's claim-scoping rule (§9: "a claim may be shown only for the presets and league
sizes that individually reach the required grade") applied to every setting:

| Arm grade | What the product does in that setting |
|---|---|
| **D** | **No confidence numeral prints** in a report whose setup has that setting. Points gaps, availability facts and counted usage still print, exactly as the parent's grade D specifies. |
| **C** | The numeral prints as a recorded prediction only, as it does today. No accuracy implication anywhere. |
| **B** | As C in reports. The confidence page may state that setting's measured figures as facts, in the same sentence as its failures. The banned words stay banned. |

**Combined settings** (for example half-PPR *and* superflex *and* 10 teams) are not graded
as combinations; there are too many for eleven seasons to support. A report prints a numeral
only if **every** setting of its setup graded C or better. One D among its settings withholds
it. This errs toward printing nothing, which is the safe direction.

**The measured setup is unaffected.** PPR / 12 / T1 / weeks 4–16 keeps the parent's Grade C.
Nothing here can raise or lower it (parent §9: arms only downgrade, never promote, and the
headline is already C).

**What it may not do.** A setting that grades B does not license any wording on the landing
page beyond what the parent grade allows there. A setting that grades C or D is not re-run
with other parameters to find a better grade: that would be selection.

## 4. What is out of scope, and stays ungraded

- Rookies (parent C2): structural, the universe for season S is built from S−1 rows.
- The live availability information set (parent C2/C3).
- Team defenses: excluded exactly as the parent excludes them; their numeral is already
  withheld (`TEAM_DEFENSE_CONFIDENCE_CALIBRATED = False`).
- Weeks 2–3: governed by the early-season method, not this one.

## 5. Outputs

`reports/setups-backtest.md`, generated, never hand-edited:
- the commit sha of this document and the runner;
- one summary table: arm, setting, calls graded, decided, hit rate, ECE, judgeable buckets,
  calibrated buckets, resolution spread, grade;
- per arm, the bucket table in the parent's format;
- for W17, week 17 and week 18 hit rate and call counts separately (diagnostic);
- the decision each grade triggers under §3, stated.

The runner exits non-zero, and writes nothing, if any arm grades fewer seasons than §1 fixes.

## 6. What invalidates this exercise

- Any change to §1–§3 after an output has been read.
- Running any arm more than once and keeping the preferred result.
- An arm computed by anything other than the parent's `calls_for_season` and `evaluate`.

## 7. Freeze procedure

1. This document and `engine/setups_backtest.py` are committed together, before the first run.
2. The runner is run once. The summary table is read, and §3's decisions are made in code,
   in that order.
3. Corrections, if ever needed, are appended below with a date, never edited into the text.

## 8. CORRECTIONS — appended, never edited into the text above

*(none)*
