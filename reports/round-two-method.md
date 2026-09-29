# Combined settings and team defenses — preregistered method

**Status: preregistration. Written and committed before any number from these runs exists
(CLAUDE.md principle 2).** Target module `engine/round_two_backtest.py`; output
`reports/round-two-backtest.md`. Nothing below may change after the first output is read.
Changing anything voids the run and needs a new preregistration with a new commit.

**Why this exists.** Two gaps remain after `reports/setups-method.md` and
`reports/recalibration-method.md`:

1. Settings were graded one at a time. A report in, say, a 10-team half-PPR league prints a
   number that no run graded as that combination.
2. Team defenses carry no number at all (`TEAM_DEFENSE_CONFIDENCE_CALIBRATED = False`) because
   no graded call has ever involved a defense: the harness's weekly rows never contained a
   defense's stat line.

## 1. What is graded, and on which seasons

Everything is graded on **2020–2024** only, the seasons the recalibration's `b` never saw, and
graded **as it ships**: every confidence passed through the published map
`p' = σ(1.3714 · logit(p))` (`reports/recalibration-backtest.md`), weeks 4–16, seed 0, depth
multiplier 2.0, the W−1 availability gate. The raw (uncorrected) grade is reported beside it as
a diagnostic and decides nothing. Grades use the parent method's §1 rule through the parent's
`evaluate`, unchanged; Grade A is unreachable (seed 0 only) and is recorded as B.

### 1a. Combined settings — nine arms

| Arm | Scoring | League size | Lineup |
|---|---|---|---|
| X1 | half_ppr | 10 | standard |
| X2 | half_ppr | 14 | standard |
| X3 | standard | 10 | standard |
| X4 | standard | 14 | standard |
| X5 | half_ppr | 12 | superflex |
| X6 | ppr | 10 | superflex |
| X7 | ppr | 14 | superflex |
| X8 | half_ppr | 12 | no K or DEF |
| X9 | half_ppr | 8 | standard |

Calls come from the parent's `calls_for_season` with those three arguments; nothing else
differs from the headline.

### 1b. Team defenses — one arm

Arm DEF: the headline configuration (full PPR, 12 teams, the standard lineup), with the parent's
`calls_for_season` run under a new `defenses=True` switch that changes exactly four things and is
inert (`False`) everywhere else, so every frozen run reproduces:

1. each graded week's rows gain every team defense's line, joined exactly as the product joins
   them (`ingest.nflverse.defense_rows` + `engine.subscriber.merge_defenses`: `stats_team` for
   the counts, the schedule's final score for points allowed);
2. each defense's pre-season rank comes from its **previous** season's defense points under
   `score_defense`, the same information-set rule every player's rank already obeys;
3. a defense's points in a graded call are `score_defense`, never the player formula;
4. the product's defense gate is lifted inside the run only, so the number the product would
   print is the number graded.

Only calls at the DEF slot are kept. Defense scoring does not depend on the league's scoring
preset (`DEFENSE_RULE` is fixed), so one arm covers every preset. The full 2014–2024 raw grade
is reported as a diagnostic.

## 2. The decisions — frozen before the run

**Combined settings.** A combination whose recalibrated 2020–2024 grade is **D** withholds the
numeral in reports with exactly that combination. **C or B**: the numeral prints, as today.
Combinations not listed keep the existing rule (every setting C or better).

**Team defenses.** The defense numeral ships — `TEAM_DEFENSE_CONFIDENCE_CALIBRATED` becomes True
and defense calls print, are recalibrated in weeks 4–16 like every other call, and are recorded
in the ledger — **if and only if** the DEF arm's recalibrated 2020–2024 grade is C or better
**and** it has at least **two** judgeable bands (≥ 30 decided calls each). A grade computed on
fewer than two judgeable bands is a grade about almost nothing, and a number that prints must
have been measured. Otherwise the gate stays closed and the result is published anyway.

**What it may not do.** No re-run with other parameters, other seasons, a defense-specific
recalibration, or a different combination list after an output is read.

## 3. What invalidates this exercise

- Any change to §1–§2 after an output has been read.
- The `defenses` switch changing any output when False.
- Calls from anything other than the parent's `calls_for_season`, grades from anything other
  than its `evaluate`, or a recalibration other than the published `b`.

## 4. Outputs

`reports/round-two-backtest.md`, generated: the commit sha; one summary table (arm, settings,
calls, decided, recalibrated grade and ECE, raw grade and ECE, judgeable bands); the DEF arm's
bucket tables (recalibrated, raw, and the 2014–2024 raw diagnostic); the §2 decisions, stated.

## 5. Freeze procedure

1. This document, `engine/round_two_backtest.py` and the `defenses` switch are committed
   together, before the first run, with a test that the switch is inert when False.
2. The runner is run once. §2 is applied, and only then are product changes made.
3. Corrections, if ever needed, are appended below with a date, never edited into the text.

## 6. CORRECTIONS — appended, never edited into the text above

*(none)*
