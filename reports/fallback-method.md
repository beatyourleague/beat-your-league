# The confirmed-alternative fallback — preregistered method

**Status: preregistration. Written and committed before any number from this run exists
(CLAUDE.md principle 2).** Target module `engine/fallback_backtest.py`; output
`reports/fallback-backtest.md`. Nothing below may change after the first output is read.
Changing anything voids the run and needs a new preregistration with a new commit.

**Why this exists.** A slot's odds compare the starter with the best eligible bench player
at that slot, and print only when BOTH are confirmed to play (`may_publish_confidence`).
When the best bench player is listed questionable or is unconfirmed, the slot prints no
odds even though the starter is confirmed. One doubtful bench player can blank several
slots: in the published 2024 week-10 sample, Tony Pollard (questionable) blanked Saquon
Barkley, Bijan Robinson and Chase Brown, so only 3 of 9 slots carried odds.

## 1. The rule under test

In `optimal_lineup`, a new switch `confirmed_fallback` (default **False**, which reproduces
every frozen run exactly). With it True, and only when:

1. the starter's own status is ACTIVE (confirmed), and
2. the best eligible bench alternative is NOT ACTIVE (questionable or unknown — OUT players
   are already excluded from alternatives), and
3. the slot is not gated for any other reason (defense, too few games, no bench player),

the call is made against the **next-best bench alternative at that slot whose status is
ACTIVE**, is not a team defense, and has at least `MIN_GAMES_FOR_CALL` games of evidence —
taken in the same projection order `eligible()` already uses. If no such player exists, the
slot stays gated exactly as today. Everything downstream is unchanged: the probability,
RULE 3's seat swap, the published recalibration, the ledger record (which names the
confirmed alternative as the `over` player, so grading is well defined).

The doubtful player is kept on the pick (`doubtful_alternative_id`) so the report still
names him in the late-news item and the if/then plan; that is presentation, not graded.

## 2. What is graded, and on which seasons

Arm FB: the headline configuration (full PPR, 12 teams, template T1, seed 0, depth multiplier
2.0, weeks 4–16, the W−1 availability gate), run twice through the parent's
`calls_for_season` — once with `confirmed_fallback=False` (the frozen call set) and once with
it True. Graded on **2020–2024** through the published recalibration
`p' = σ(1.3714 · logit(p))`, as it would ship. Two populations:

- **NEW** — calls present under the fallback whose (season, week, roster, slot) had no call
  in the frozen set. This is what the rule adds.
- **ALL** — every call under the fallback.

Grades use the parent method's §1 rule through the parent's `evaluate`, unchanged; Grade A is
unreachable (seed 0 only) and is recorded as B. The raw (uncorrected) grades and the
2014–2024 raw grade of NEW are reported as diagnostics and decide nothing.

Also reported, deciding nothing: the count of NEW calls; the count of shared keys whose call
changed (a RULE 3 swap can re-seat a player and move a later slot); and the share of weeks-
4–16 slot-weeks that carry odds with and without the rule.

## 3. The decision — frozen before the run

The fallback ships — `run/solo.CONFIRMED_FALLBACK` becomes True and `run/solo.py` passes it
to `optimal_lineup` in weeks 4–16 only (never 1–3 or 17–18, which are other arms) — **if and
only if all three hold**:

1. NEW's recalibrated 2020–2024 grade is **C or better** (not D);
2. NEW has at least **two** judgeable bands (≥ 30 decided calls each) — a grade on fewer is a
   grade about almost nothing;
3. ALL's recalibrated 2020–2024 grade is **B** — the rule may not pull the headline below the
   grade the product currently states.

Otherwise the switch stays False and the result is published anyway.

**What it may not do.** No re-run with another fallback order, another evidence floor, other
seasons, other settings, or a rule-specific recalibration after an output is read.

## 4. What invalidates this exercise

- Any change to §1–§3 after an output has been read.
- The switch changing any output when False.
- Calls from anything other than the parent's `calls_for_season`, grades from anything other
  than its `evaluate`, or a recalibration other than the published `b`.

## 5. Outputs

`reports/fallback-backtest.md`, generated: the commit sha; a summary table (population, calls,
decided, recalibrated grade and ECE, raw grade and ECE, judgeable bands); bucket tables for
NEW and ALL (recalibrated) and NEW 2014–2024 (raw diagnostic); the diagnostics in §2; the §3
decision, stated.

## 6. Freeze procedure

1. This document, `engine/fallback_backtest.py` and the switch are committed together,
   before the first run, with a test that the switch is inert when False.
2. The runner is run once. §3 is applied, and only then are product changes made.
3. Corrections, if ever needed, are appended below with a date, never edited into the text.

## 7. CORRECTIONS — appended, never edited into the text above

*(none)*
