# Early-season confidence — preregistered method (weeks 2–3, prior-season seeded)

**Status: FROZEN on commit. Nothing below may be changed after the first output
is read. Corrections are appended to §9, dated, with the original wording left
standing — the same rule as `reports/nflverse-backtest-method.md` §15, and for
the same reason: a frozen document that can be quietly fixed is not frozen.**

This is a NEW preregistration, not an edit to the parent method
(`reports/nflverse-backtest-method.md`, "the parent"). The parent excludes
weeks 1–3 with "arithmetic, not a choice": `MIN_GAMES_FOR_CALL = 3` makes a
call impossible before week 4 when the only admissible evidence is
current-season appearances. This document preregisters a different evidence
rule for weeks 2–3 only, and the test that decides whether the product may use
it. This draft was adversarially reviewed against the code before freezing
(four lenses; the findings are folded in below rather than appended, because
nothing had been run yet).

## 1. The question

The product launches Tue Sep 8, 2026 — week 1. Under the shipping rules, the
entire refund window (through week 2) carries no confidence number anywhere.
Week 1 is unreachable by ANY model: the availability gate requires the week
W−1 injury report (parent §6, correction C3), and week 1 has no W−1 report, so
everyone classifies UNKNOWN and no confidence prints. That is accepted and not
at issue here. The question is weeks 2 and 3:

> If a player's own prior-season record is admitted as discounted evidence,
> does the confidence number printed in weeks 2–3 mean what it says, to the
> same standard the parent demanded of weeks 4–16?

There is no baseline arm: the unseeded model produces zero publishable calls
in weeks 2–3 by arithmetic, so this arm is judged against the parent's
absolute thresholds, not against a comparison.

**Expected size, stated in advance** (the parent's §3 habit): the parent
produced ~70 calls per season-week; 22 season-weeks here caps the arm near
~1,500 calls, and gates will take a share, so **roughly 1,000–1,500 calls**
is the expectation. At that size the 80–90% bucket is not expected to be
judgeable. A gross shortfall against this expectation is a finding to
explain, not a detail to pass over.

## 2. The model change — exact, inert everywhere else

`engine/projection.py ProjectionModel` gains two optional inputs, defaulting
to inert: `prior_self` (player id → the list of his own prior-season
per-appearance points) and `prior_self_weight` λ. With either input absent the
model is byte-identical to the frozen one.

**The seed's construction, frozen.** An S−1 appearance is **an S−1 REG stat
row existing** — 0.00 rows included (the parent's own headline convention:
15.4% of fantasy rows score exactly 0.00 and most belong to players who took
the field), and **all S−1 REG weeks count, 17 and 18 included**. For each such
row, the points are `score(row, rule)` under the subscriber's own scoring
rule. `engine/nflverse_backtest.py prior_self_observations` implements exactly
this, reading the same S−1 rows the universe is already built from.

**The blend.** For a player with n current-season appearances (mean x̄, sample
variance s²), m prior-season appearances (mean p̄, sample variance s²ₚ),
positional prior (mean μ, variance σ², K = 4 as frozen), and **w = λ·m**:

- **mean** = (n·x̄ + w·p̄ + K·μ) / (n + w + K)
- **variance** = (n·s² + w·s²ₚ + K·σ²) / (n + w + K), floored at MIN_SD = 2.0
- **Exception, stated:** K enters the blend only when the positional prior
  has ≥ 1 sample. With none, the blend is (n·x̄ + w·p̄)/(n + w) — shrinking
  toward a placeholder 0.0 would be a bug, not a prior. The availability
  line's own K fallback (which has a real default rate) is unchanged.
- **evidence** = n + w. The publish gate becomes evidence ≥
  MIN_GAMES_FOR_CALL (= 3, unchanged). `Projection.games` stays the count of
  REAL current-season appearances; w is carried separately as
  `seeded_games`.

**Where the gate lives, named** (the review found four `.games` readers with
different required fates): the evidence gate replaces the two-sided comparison
in `engine/week_report.py optimal_lineup` **only** — the one path both the
harness and the product call. `engine/decisions.py` (the retired Sleeper
study's path) and `rival_lineup` (league-path fragility, unreachable in the
solo product) are **unchanged**. `Projection.confident_enough` follows
evidence for coherence but is not the gate site — it has no callers on this
path. The arm's runner calls `calls_for_season` with a threaded
`prior_self_weight` parameter; re-implementing that loop is forbidden for the
same reason the parent's §14 forbids re-implementation.

**Week restriction, structural.** The seed is consulted only when the
projected week is in `SEEDED_WEEKS = {2, 3}`, enforced **inside
`project()`** — a model constructed with a seed still answers week 1 and
weeks 4+ exactly as the frozen model would, so no wiring mistake can leak
last season into them. In particular, `project()` still returns None at week
1 when n = 0 and the positional prior is empty, which is what keeps the
frozen week-1 placement branch (`_place_without_projections`) reachable.
Pinned by test before this document froze.

What is deliberately NOT seeded: **availability** (`appear_probability` keeps
its frozen form — last season's durability is not this season's, and the
injury-report gate is the availability instrument), **the positional prior**
(current-season weeks strictly before W, thin in week 2 because that is the
truth), **the universe, rosters and field** (parent construction, S−1 rows
only), and **team defenses** (excluded as in the parent; DEF slots stay gated
regardless of this arm).

A player with no prior season (a rookie, or anyone absent from S−1's rows)
has m = 0, evidence = n ≤ 2 in weeks 2–3, and stays gated. This arm admits a
player's own record; a player without one is who the original gate exists
for.

**λ = 0.5, fixed here, before any output.** One prior-season appearance
counts as half a current-season one. Anchors, so the choice is inspectable
rather than tuned: the frozen model already prices K = 4 pseudo-games as
equivalent to the positional average, and public year-over-year per-game
scoring correlations sit around the same order — an order-of-magnitude
anchor, not a measured in-repo fact, and one whose underlying data overlaps
this window; the sensitivity arms are the control for that. A full 17-game
prior season contributes w = 8.5 — deliberately more than the 1–2 real games
beside it, because it is more evidence than 1–2 games. Two sensitivity arms,
**λ = 0.25 and λ = 1.0**, are run and reported. They are §4's arm set and
§6.6's invalidation input; they never substitute — the headline is λ = 0.5 no
matter which number looks best, and reporting a sensitivity arm as the result
is the tuning this paragraph exists to forbid.

## 3. The graded set

Everything not named here is the parent's headline configuration, unchanged:
PPR, 12 teams, template T1, seed 0, depth multiplier 2.0, the same
universe/allocation/season-assembly code paths, ties set aside, REG rows
only, `MIN_DECIDED_TO_JUDGE = 30`.

- **Weeks: 2 and 3.** Week 1 excluded (§1). Weeks 4+ are the parent's
  territory and are not re-graded here.
- **Seasons: 2014–2024, exactly the parent's.** The seed needs S−1 stat rows
  (2013's exist); the gate needs season S's own week-1 and week-2 reports.
  Verified before freezing: every season 2014–2024 has a **non-empty**
  week-1 report (176–221 rows) and week-2 report (all present) — and the
  runner does not take this document's word for it: it asserts a non-empty
  W−1 report per graded week and refuses the season otherwise.
- **The availability gate: parent §6 as implemented by
  `nflverse_backtest.availability_for`, with C3's fail-closed branch added
  before this freeze** — a missing W−1 report now yields NO snapshot
  (everyone UNKNOWN, every call gated), never an empty designations map read
  as a league-wide clean bill of health. Carry-forward team from the most
  recent stat row strictly before W; for week 2 that is week 1 only.
- **The induced population, stated** (the parent's "costs nothing" argument
  does not transfer): a week-2 call requires both players to have a week-1
  stat row (else no carry-forward team → UNKNOWN → gated); a week-3 call
  requires at least one appearance in weeks 1–2 on both sides. The graded
  population therefore conditions on early-season participation. Byes do not
  occur in weeks 1–3 under the modern schedule, but the gate still checks
  the schedule rather than assuming it.
- **Grading:** the parent's `_call` verbatim — the model's first choice
  against its own second, real box-score points under the same rule, no stat
  row = 0.0.

## 4. Statistics and the grade

The parent's §8 machinery verbatim — same bucket edges, ≥ 30 decided to
judge, clustered bootstrap over (season, week) with 2,000 resamples and the
same seed, Wilson agreement rule, ECE, resolution R — with three additions
this arm's shape demands, all frozen now:

1. **The cluster count is 22** (2 weeks × 11 seasons), against the parent's
   143. Intervals will be materially wider and less reliable; the report
   states the per-bucket contributing-cluster count in its calibration
   table.
2. **Precision clause:** a bucket whose clustered 95% interval spans more
   than **15 percentage points** is recorded *undecided*, never calibrated —
   at these widths the parent's own observed failures would "pass", and
   agreement inside an enormous interval is not evidence. This makes a
   hollow Grade B unreachable; it can only move the result toward C.
3. **Effective-sample outputs** (the parent's §8 final bullet, extended):
   raw calls, distinct (pick, alternative, slot) triples, distinct players,
   cluster count, median calls per cluster, and **the share of week-3 calls
   whose (roster, slot, pick, alternative) pairing repeats from week 2** —
   the seed barely moves between the two graded weeks, so recurrence is the
   dependence the clustering must carry. If these diverge badly from the raw
   count, the intervals are decoration and the report says so.

The grade is the parent's §1 table applied to this call set by the program.
"Every arm" in its Grade-A clause means **this run's arm set**: the two λ
arms and the 20 allocation seeds (seeds 0–19, C spread > 1 → unstable, Grade
A unreachable). The parent's own A–F arms are not re-run here.

## 5. The decision — frozen before the run

| This run's grade | What the product does in weeks 2–3 |
|---|---|
| **A or B** | The seeded model runs for weeks 2–3. Confidence prints under the parent's per-grade claim rules for those weeks (B: figures statable as facts beside failures; the banned words stay banned). |
| **C** | The seeded model runs for weeks 2–3. The numeral prints **as a recorded prediction only**, exactly as the parent's Grade C already governs weeks 4+ — no accuracy implication anywhere, every call recorded and graded. |
| **D** (parent §1's D-clauses on this set) | No seeded confidence ships. Weeks 2–3 remain as they are today. The result is still published as an evidence page — an honest negative, like `reports/gate-backtest.md`. |

Consequences that ship with ANY passing grade (A, B or C):

- **Scope of the wiring:** the product constructs a seeded model only for
  weeks 2–3 under (PPR, 12, T1)-measured settings; other presets and sizes
  ship no week-2–3 numbers until their own arms run — the parent's §9
  per-preset scoping. The model's own week restriction (§2) is the backstop
  either way, and week 4+ byte-identity is pinned by test.
- **Disclosure, with its surfaces named** (principle 5): every lineup row
  whose published confidence has w > 0 on either side carries a `seeded`
  entry in `SlotPick.flags` — "last season counted in" — rendered by both
  the browser Tape and the email tape; the regret section carries the same
  as a driver chip. And because the seed also moves numbers that are not
  calls (seating order, `projected`, `edge`, totals), **the weeks-2–3 report
  carries one section-level line on the lineup section stating that last
  season is counted into this week's numbers.** A seeded number that hides
  its seeding violates this preregistration. The gate-failure message copy
  (what a still-gated row says) is product wording outside the frozen text.
- **Ledger identity:** seeded calls record to the same
  `typed-{scoring}-{size}-{season}` store and grade by the same rules; week
  ∈ {2, 3} identifies the regime because the unseeded model cannot produce a
  call there. Any change to λ or the seed formula requires a new
  preregistration and may not record into a store already holding calls
  under the old value for that season.
- **`Projection.games` keeps meaning real current-season appearances** on
  every surface (`form_games`, driver chips); last season never masquerades
  as this one.

## 6. What invalidates this exercise

1. Any §2 formula, λ, the week set, the season set, or the gate is changed
   after any output is read.
2. The headline is reported from a sensitivity arm (λ ≠ 0.5) or any
   allocation seed other than 0.
3. A seeded number ships without its §5 disclosure, or seeding leaks outside
   weeks 2–3 (week 1 included — it ships a number under no grade).
4. The parent's outputs move under this code change. **Checked before the
   arm's first run, and specified:** season 2024, seed 0, headline
   configuration; equality = the identical ordered set of (season, week,
   roster, slot, pick, alternative) with confidence equal at 10 decimal
   places and outcomes equal — 956 calls, hash-compared, unchanged. Noted:
   the parent's own tests are blind to the seeded paths at their defaults,
   so this check and this arm's tests are the sole enforcement.
5. A bucket verdict that flips between the λ = 0.25 and λ = 1.0 arms belongs
   to λ, not the model: Grade A is unreachable and the report says which
   bucket decided it.

## 7. Leakage and bias

Inherited whole from the parent: universe and rosters from S−1 rows only,
projections filtered strictly before W, `players.csv` never read, the injury
report used published before the graded games. New surface: the seed itself —
it reads only S−1 stat rows, scored under the same rule; nothing in it can
encode season S. One bias named beyond the parent's §12: **the recommended
side is the argmax over the seed, the same statistic that built the
rosters**, and its noise persists across both graded weeks rather than
regressing as n grows — so the winner's-curse inflation the parent describes
does not average out between weeks 2 and 3. The report carries this
disclosure at every grade.

## 8. Outputs

`python -m engine.early_season_backtest` writes
`reports/early-season-backtest.md`: header (config, λ, seasons, weeks, the
§6.4 inertness statement), per-season call counts against §1's stated
expectation, the headline table (calls, decided, ties, hit rate, ECE, Brier,
deciles, J/C), the calibration table with per-bucket clusters and the
precision clause applied, the effective-sample block of §4.3, the
seed-stability line, both sensitivity arms, the computed grade with §5's
decision spelled out, and the §7 disclosure.

## 9. CORRECTIONS — appended, never edited into the text above
