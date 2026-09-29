# Last season, all season — preregistered method (weeks 4–16)

**Status: FROZEN on commit. Nothing below may be changed after the first output
is read. Corrections are appended to §8, dated, with the original wording left
standing — the rule every method in `reports/` follows.**

This is a new arm against the shipped product. The shipped product is: the
parent model (`reports/nflverse-backtest-method.md`), the confirmed-alternative
fallback (`reports/fallback-method.md`) and the recalibration b = 1.3714
(`reports/recalibration-method.md`), in weeks 4–16. Weeks 2–3 keep their own
arm (`reports/early-season-method.md`) and are not touched here; weeks 1 and
17–18 are not touched either.

## 1. The question

In weeks 4–16 a player is projected from his current-season appearances,
shrunk toward his position's average with K = 4 pseudo-games. Last season
does not enter at all. So a proven starter who opens with three slow games is
projected like a replacement-level player, and the report benches him.
Observed on real data, 2026 week 4 (Sep 29 2026): Saquon Barkley, RB15 last
season, games of 9.0, 3.0 and 9.0, projected 7.6 and benched for Sam LaPorta
at 9.0. An experienced manager reads that call, disagrees, and stops trusting
the report — whether or not the call is right.

> If a player's own prior-season record is admitted as discounted evidence in
> weeks 4–16, do the lineups it sets score more than the shipped lineups, and
> does the number it prints still mean what it says?

## 2. The model change — exact, inert everywhere else

`ProjectionModel` gains one optional input, `late_self_weight` λ_L, default
0.0 (inert: byte-identical to the shipped model). It uses the same
`prior_self` observations the early-season arm defined (early-season method
§2: every S−1 REG stat row is an appearance, 0.00 rows and weeks 17–18
included, scored under the subscriber's own rule), and the same blend:

    w    = λ_L · m          (m = the player's S−1 appearances)
    mean = (n·x̄ + w·p̄ + K·μ) / (n + w + K)
    var  = (n·s² + w·s²ₚ + K·σ²) / (n + w + K)

It applies **only in weeks 4–16**, enforced inside `project()` by a constant
`LATE_SEEDED_WEEKS`, exactly as `SEEDED_WEEKS` enforces weeks 2–3. Two
deliberate differences from the early-season seed:

1. **It moves the projection, never the publish gate.** In weeks 4–16 the
   seed's pseudo-games do NOT count toward `MIN_GAMES_FOR_CALL`; `evidence`
   stays the real appearance count, and `seeded_games` stays 0. So the set of
   slots that CAN carry a call is the shipped set; only who is seated and the
   number printed can move. (It also means no row carries the "last season
   counted in" flag in weeks 4–16 — the flag marks evidence admitted to the
   gate, which this is not.)
2. **The availability line is untouched.** Appearance probability is computed
   from current-season opportunities exactly as shipped.

A rookie has m = 0, so w = 0 and he is projected exactly as shipped.

**λ_L = 0.25 is the primary arm**, fixed now. A full prior season (m ≈ 16)
then carries w ≈ 4 pseudo-games — the same weight as the positional prior —
so by week 10 a player's own nine games outweigh last season about two to one.
**Sensitivity arms λ_L = 0.125 and 0.5 are run and reported, and never
substituted** for the primary, whatever they show.

## 3. Harness

Everything comes from the parent harness: `calls_for_season` (template T1, 12
teams, PPR, allocation seed 0, the W−1 availability gate), with
`confirmed_fallback=True` because the shipped product has it in weeks 4–16.
Seasons are split as the recalibration split them: **fit 2014–2019, grade
2020–2024**, and nothing from 2020–2024 is used to choose anything.

## 4. Measures

**(a) Lineups — the primary measure.** For every team-week of 2020–2024,
weeks 4–16, seat the shipped lineup and the arm's lineup with
`optimal_lineup` on identical inputs (same roster, same availability, same
fallback). Seating does not depend on the recalibration, which is applied
after the seat is decided. A lineup's score is the sum of its seated players'
actual PPR points (no stat row = 0.0, the parent's convention). Where the two
lineups differ, record which scored more: a win, loss or tie for the arm.
Report W–L–T, the exact two-sided sign test, and the mean points per
differing team-week with a 95% interval resampling (season, week) clusters
(2,000 resamples, the parent's seed).

**(b) The number.** The arm's calls on 2014–2019 fit a new b′ by
`engine.recalibration.fit_b` (same search, same tolerance). b′ is applied to
the arm's 2020–2024 calls and graded by the parent's `evaluate`. Also report
the shipped product's own 2020–2024 grade beside it, recomputed the same way,
so the two sit on one page.

**(c) Star benchings — reported, not a clause.** A "star" is a player who
ranked starter-calibre at his position last season within the backtest's own
universe (by S−1 total points under PPR: top 12 QB and TE, top 24 RB and WR).
For each model: how often an AVAILABLE star (not OUT on the W−1 report, not
on bye) sits on the bench, per 1,000 team-weeks, and how often a benched star
outscored the seated player with the lowest projection among the slots he
could have filled.

**(d) The other setups.** Measures (a) and (b) repeated for the setups the
product already grades (`engine/setups_backtest.py` arms S1, S2, L10, L14,
L8, TSF, TNKD — every arm but W17), with b′ from (b) applied as the
recalibration is applied today: one b for every setup.

## 5. Decision — frozen

The arm ships at λ_L = 0.25 in weeks 4–16 **in the headline setup only if
both hold**:

- **C1 (lineups).** On 2020–2024 the arm's lineups win more differing
  team-weeks than they lose. Significance is reported, not required: the
  point of the change is a report a manager can trust, and "no worse on the
  record, easier to believe" is enough. A lineup that loses more often than
  it wins does not ship, however much better it looks.
- **C2 (the number).** The corrected 2020–2024 grade is B or better.

**In any other setup** it ships only if that setup's arm passes C1 and its
corrected grade is C or better (the rule the setups method uses: a D
withholds the numeral), AND the headline passed.

If it ships, the product changes in exactly three places: `run/solo.py`
passes λ_L to the model in weeks 4–16 (never 2–3, never 17–18), the
published recalibration b becomes b′ from (b), and `SETTING_GRADES` records
the arm's corrected grades. If the headline fails, nothing changes, the
report is published in `reports/` as it is, and the Barkley call stands as
what the measured model does.

## 6. What this cannot show

- It measures a fixed-roster league (the parent harness never trades or
  drops), so it cannot see a player who lost his job to a trade mid-season —
  exactly the case where last season is the worst guide. The sign test on
  real seasons includes those players; it cannot isolate them.
- A pick that scored more in one week is not a better decision in every
  case. Over five seasons of differing team-weeks it is the right aggregate.
- Players whose team changed over the summer carry last season's role from a
  different offence. The seed does not know that. Reported as a limitation,
  not modelled.

## 7. Considered and not tested

A guard that refuses to bench a proven starter unless the replacement
projects some fixed margin higher. Not tested because its margin is a knob —
any value is a choice that could be tuned to the outcome — and because it
treats the symptom: the projection itself is what ignores last season.

## 8. Corrections

**Note 1 (Sep 29 2026, after the run — an interpretation, not a change).**
§5 names single-setting arms; a subscriber's setup combines three settings
(scoring, league size, lineup shape). The product reads it the conservative
way: a setup is anchored only if EVERY one of its settings shipped. So a
10-team half-PPR league is not anchored, because 10 teams did not ship. And a
setup that is not anchored keeps the shipped recalibration b = 1.3714, since
b′ was fitted to the anchored model and describes nothing else.
