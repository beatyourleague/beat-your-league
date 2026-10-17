# Lineup shapes — preregistered method

**Status: frozen by commit before the first run.** This document and `engine/shapes_backtest.py`
are committed together, before the runner has ever run (CLAUDE.md principle 2). Output
`reports/lineup-shapes-backtest.md`. Nothing below may change after the first output is read;
changing anything after that voids the run and needs a new preregistration with a new commit.

**Why this exists.** The signup page offered three lineups: standard (QB, 2 RB, 2 WR, TE,
FLEX, K, DEF), superflex, and no K or DEF — the three `reports/setups-method.md` graded
(`run.solo.SETTING_GRADES`). Sleeper's default lineup has two FLEX spots and Yahoo's has three
WR with a W/R/T FLEX, so those buyers either picked a lineup that is not theirs or could not
sign up. The page now offers four bases (standard, two FLEX, three WR, superflex), each with
and without a K and a DEF (`engine.subscriber.LINEUP_SHAPES`). Reports in a shape no arm has
graded print **no odds** (contract C8): the lineup, projections, the if/then plan and the
Saturday check all work, and each row says the shape is not graded yet. This run grades the two
new offenses.

**Graded is judged on the offense** (`engine.subscriber.graded_slots`, Oct 16 2026). A shape
is its offense — the slots other than K and DEF, as a multiset — plus at most one K and one
DEF. A kicker or defense slot stands alone: nobody else can play there and they play nowhere
else, so having one or not changes no other slot's candidates and therefore no other slot's
call, and a defense call is never graded. So the standard and superflex offenses are already
graded in every K/DEF variant, and an offense this run grades is graded in every variant too.
The ledger store carries the offense (`engine.subscriber.ledger_store_id`), so two offenses
that publish different numbers for one pair never share a call id.

---

## 1. The arms — two per new offense

The arms are derived in code from `LINEUP_SHAPES`: for every base whose offense is not graded
(`two FLEX`, `three WR`), the shape WITH a K and a DEF — one setting away from the headline,
the way the setups run graded superflex — and the shape with NEITHER, the way it graded "no K
or DEF". Each arm changes only the lineup from the headline configuration (§2) and is graded
alone.

| Arm | Lineup | Slots |
|---|---|---|
| flex2 | Two FLEX (Sleeper's default) | QB RB RB WR WR TE FLEX FLEX K DEF |
| flex2-nokd | Two FLEX, no K or DEF | QB RB RB WR WR TE FLEX FLEX |
| wr3 | Three WR (Yahoo's default; Yahoo's W/R/T is FLEX) | QB RB RB WR WR WR TE FLEX K DEF |
| wr3-nokd | Three WR, no K or DEF | QB RB RB WR WR WR TE FLEX |

## 2. Everything else — the headline, as the product ships it today

- Seasons **2020–2024 only** — the seasons the recalibration's `b` never saw
  (`engine.recalibration.GRADE_SEASONS`). Weeks 4–16.
- Full PPR, 12 teams, seed 0, depth multiplier 2.0, the W−1 availability gate, row-presence
  appearance signal — the parent method's settings, unchanged.
- The model as it ships in weeks 4–16: context arm AV, the anchor at 0.25 pseudo-games per
  game, the confirmed-alternative fallback (`calls_for_season(confirmed_fallback=True,
  late_self_weight=0.25, context="AV")`) — the configuration `engine/context_combos.py` grades.
- Every confidence through the **shipped** recalibration, `p' = σ(b · logit(p))` with
  b = `run.solo.CONTEXT_B` (1.2064), because that is the number a report prints.
- Calls from the parent's `calls_for_season`; grades from the parent's `evaluate` (§1 table,
  clustered intervals, clusters = (season, week), 2,000 resamples, seed 20260821). No threshold
  changes. Grade A is unreachable (seed 0 only) and is recorded as B.

## 3. The decision — frozen before the run, the same clause as every setting

| Arm grade | What the product does in that shape |
|---|---|
| **D** | No odds print in that shape. The lineup, projections, if/then and Saturday check still do — exactly today's behaviour. |
| **C** | Odds print, as recorded predictions only. No accuracy implication anywhere. |
| **B** | As C in reports. The confidence page may state that shape's measured figures as facts, in the same sentence as its failures. The banned words stay banned. |

**An offense prints when BOTH its arms grade better than D.** The decision is applied in code
by adding the base to `engine.subscriber.GRADED_BASES` and to `GRADED_BASES` in
`site/join/roster.js` (its twin), and the grades to `run.solo.SETTING_GRADES` under "lineup
shape", in a commit after the run that names the run's output. Every K/DEF variant of that
offense then prints. If either arm grades D, the offense stays ungraded in every variant and
keeps today's behaviour.

**Combined settings.** A shape that prints is still one setting of a setup; the existing rule
(`reports/setups-method.md` §3, `reports/round-two-method.md` §2) still applies to its other
settings (scoring, league size, weeks). Shapes are not graded in combination with half-PPR,
standard scoring or other league sizes; the every-setting-C-or-better rule covers those, as it
does for superflex today.

**What it may not do.** No arm is re-run with other parameters, other seasons, another `b` or
a shape-specific recalibration after an output is read. A shape graded D is not re-graded to
find a better result: that would be selection.

## 4. What is out of scope, and stays ungraded

- **Scoring modifiers** — six-point passing touchdowns, TE premium, −1 interceptions. The ledger
  store id is `typed-{scoring}-{size}-{season}` and Monday grading picks the scoring rule from
  it; a modifier would have to enter both before it can ship (it moves the published
  probability and the graded answer). The signup page says these are not scored yet.
- Shapes outside the table (2QB, two superflex spots, IDP, a FLEX that excludes TEs).
- Rookies, the live availability information set, team defenses, weeks 2–3 and 17–18 — as in
  the parent and `reports/setups-method.md` §4.
- **Ledger identity** is settled before this run: the store id carries the offense
  (`typed-ppr-12-flex2-2026`), so a shape's calls never share an id with the standard lineup's.

## 5. Outputs

`reports/lineup-shapes-backtest.md`, generated, never hand-edited:
- the commit sha of this document and the runner;
- the decisions §3 triggers, stated, per offense;
- one summary table: arm, lineup, calls graded, decided, hit rate, ECE, judgeable buckets,
  calibrated buckets, resolution spread, grade;
- per arm, the bucket table in the parent's format and calls per season.

The runner exits non-zero, and writes nothing, if any arm grades fewer seasons than §2 fixes.
It has no option to run a subset of the arms.

## 6. What invalidates this exercise

- Any change to §1–§3 after an output has been read.
- Running the runner more than once and keeping the preferred result.
- An arm computed by anything other than the parent's `calls_for_season` and `evaluate`.

## 7. Freeze procedure

1. This document and `engine/shapes_backtest.py` are committed together, before the first run.
2. The runner is run once. The summary table is read, and §3's decisions are made in code,
   in that order.
3. Corrections, if ever needed, are appended below with a date, never edited into the text.

## 8. CORRECTIONS — appended, never edited into the text above

**Oct 16 2026, after the run (no arm, setting or decision changed).** The runner derived its
arms from the offenses graded *at run time*. Once the run's decision was recorded in code
(both offenses graded B, so both added to `GRADED_BASES`), that derivation would find nothing
left to grade and `python -m engine.shapes_backtest` could no longer reproduce the run. The
derivation now reads the graded set as it stood at the freeze (`GRADED_AT_FREEZE` = standard and
superflex), which yields exactly the four arms that ran. Also recorded: when a week's context
input can't be read, the product falls back to the model before it, which these arms never
measured; in that week the two new offenses print no odds (`run.solo.MODEL_FALLBACK_BASES`) —
a rule that only withholds.
