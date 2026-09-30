# Who he plays, and whether he was really missing — preregistered method (weeks 4–16)

**Status: FROZEN on commit. Nothing below may be changed after the first output
is read. Corrections are appended to §8, dated, with the original wording left
standing.**

A new arm against the product as it ships today in weeks 4–16: the parent
model, the season-long anchor where it ships (`reports/anchor-method.md`), the
confirmed-alternative fallback, and the published recalibration.

## 1. The question

The model knows a player's games and last season. It does not know:

- **Why he missed a game.** Availability is his appearances over his rostered
  weeks, so a bye week and a week he was ruled out on the injury report both
  count against him. A starter back from a two-week injury is projected as
  unreliable in the week he is healthy. Seen in the 2025 proving run (Sep 29
  2026): Jayden Daniels, QB6 the season before, games of 20.1, 19.7 and 17.1,
  projected 10.6 and benched in superflex after missing weeks 3–4 hurt.
- **Who he plays.** A receiver facing the league's worst pass defense is
  projected the same as one facing its best.
- **What the game is expected to look like.** The betting market's total and
  spread say how many points each team is expected to score. They are public,
  and they are in the schedule file the product already reads.

> If availability forgives announced absences, and the projection is scaled
> by the opponent and the expected team score, do the lineups beat the shipped
> lineups, and does the number still mean what it says?

## 2. The three components — exact

All three apply **only in weeks 4–16**, only through new optional inputs to
`ProjectionModel` that are inert by default, and none changes the publish gate
(`MIN_GAMES_FOR_CALL` still counts real appearances).

**A — announced absences are not missed opportunities.** A player's
opportunities, and his position's, exclude every week w < W in which (i) his
team had a bye, or (ii) he carried an out designation (Out, Doubtful, IR, PUP,
suspended — `ingest.injuries` "Out") on week w's own injury report. His team in
week w is the team on his most recent stat row in weeks ≤ w, else his first
stat row after w. A week excluded this way is neither an appearance nor a
miss. Rationale: the product's gate already refuses to call a player announced
out, so availability should measure only the absences nobody saw coming.

**M — the opponent.** His team in week W is the carry-forward team (the one
the gate uses). His opponent O comes from the schedule. For his position P
(QB, RB, WR, TE, K; never DEF), `allowed(O, P)` is the fantasy points, under the
subscriber's rule, scored by players at P whose `opponent_team` was O in weeks
w < W, summed; `games(O)` is how many of those weeks O played; `league(P)` is
the mean of `allowed / games` over all teams with games. The multiplier is

    M = (allowed(O, P) + 6 · league(P)) / ((games(O) + 6) · league(P))

— six games of league average, so a week-4 multiplier moves little. No
opponent in the schedule, or no games yet: M = 1.

**V — the market's expected score.** From the schedule's `spread_line` (home
favoured when positive) and `total_line`: home implied = (total + spread) / 2,
away implied = (total − spread) / 2. With `mean` the average implied score of
every team playing week W,

    V = (implied / mean) ^ 0.5

for QB, RB, WR, TE, K; never DEF. Missing lines: V = 1. **The market is an
input to a projection, never advice**: nothing on any surface cites a line, a
spread, or a bet (principle 4).

M and V multiply the player's per-game scoring when he plays (`active_mean`);
the spread of outcomes and the appearance probability are untouched by them.

## 3. Arms, and how one is chosen without looking at the grade

Four arms, each ON TOP of the shipped model (anchor λ_L = 0.25 included):
**A**, **A+M**, **A+V**, **A+M+V**. Harness: the parent's (`calls_for_season`,
T1, 12 teams, PPR, seed 0, the W−1 gate, `confirmed_fallback=True`).

1. **Choose on 2014–2019 only.** Each arm's lineups are seated beside the
   shipped lineups for every team-week of 2014–2019 (the anchor method's §4a
   measure). The arm with the largest (wins − losses) is chosen. If none has
   wins > losses, nothing ships and the run stops at reporting.
2. **Fit b′** for the chosen arm on its 2014–2019 calls, by
   `engine.recalibration.fit_b`.
3. **Confirm on 2020–2024 held out.** Everything in §5 is judged there, for
   the chosen arm only. The other arms' held-out numbers are printed after the
   decision and never substitute for it.

## 4. Measures on the held-out seasons

(a) Lineups: W–L–T against the shipped lineups where they differ, the exact
two-sided sign test, and mean points per differing team-week with a 95%
interval clustered by season-week. (b) The number: the chosen arm's calls,
corrected with b′, graded by the parent's `evaluate`, beside the shipped
product's grade recomputed the same way. (c) Star benchings, as in the anchor
method §4c, reported. (d) Setups: the chosen arm (with the anchor, in every
setup) against whatever ships in that setup today, for the setups arms S1, S2,
L10, L14, L8, TSF, TNKD, with b′ applied throughout.

## 5. Decision — frozen

The chosen arm ships in the headline setup only if **C1** its held-out lineups
win more differing team-weeks than they lose, and **C2** its corrected held-out
grade is B or better. In another setup it ships only if the headline passed,
that setup's lineups win more than they lose, and its corrected grade is C or
better. Where it ships the report uses b′; where it does not, nothing changes.

## 6. What this cannot show

- **The backtest reads closing lines.** The schedule archive stores the final
  line, which moves with Friday's injury news; the product reads the line as
  it stands on Tuesday. So V is measured with a little more information than it
  will have live. Stated, not modelled.
- The harness never trades or drops, as before.
- M is a per-position average and cannot see a shadow cornerback or a
  specific injury on a defense.

## 7. Considered and not tested

Weather, home field, pace, and depth-chart changes. Each is another knob, and
the three above are the ones the product can compute honestly from data it
already reads.

## 8. Corrections

(none)

**Note 1 (Sep 29 2026, after the run — a data-vocabulary bug, not a change of
method).** An adversarial review found that `engine/context.py` compared the
schedule's team codes with the stat rows' without translating the three
relocated franchises (schedule: OAK until 2019, SD until 2016, STL until 2015;
stat rows: LV, LAC, LA). On 2014–2019 every player on those teams read as "on
bye" all season and the market lookup missed the team, so **the run in this
document's first results was fitted (§3.2) on flawed 2014–2019 inputs.** 2020–
2024, the held-out seasons, have no such mismatch and were unaffected. The
same review found that the harness's `team_in_week` could read a stat row from
a week AFTER the one being projected (which the product never has). Both are
fixed in code, with no change to §2's definitions, and **the run is repeated
under the same frozen §3–§5 rules** (report regenerated; the first results are
recorded in the git history at 3f224ae..c2b86e9). Not fixed here, and recorded
so it is not rediscovered as new: `ingest.nflverse.bye_teams` has the same code
mismatch in 2014–2019, so the SHIPPED baseline's own bye gate was blind for
relocated franchises in those fit seasons, and the earlier recalibrations
(`RECALIBRATION_B`, `ANCHOR_B`) were fitted through it. Changing that would
alter every earlier frozen run and needs its own preregistered refit.
