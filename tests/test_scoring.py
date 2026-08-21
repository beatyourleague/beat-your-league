"""Tests for fantasy scoring — the base of every number downstream.

The product used to read points from the league. It now computes them, so a
systematic error here does not crash: it produces a projection model that is
confidently wrong about every player, every week. The most valuable test in this
file is therefore the ORACLE — nflverse publishes its own PPR total, and our PPR
preset must reproduce it across a full real season.
"""

from __future__ import annotations

import collections
import csv
from pathlib import Path

import pytest

from engine.scoring import (HALF_PPR, PPR, PRESETS, STANDARD, ScoringError,
                            ScoringRule, _kicking, preset, score)

SEASON_CSV = (Path(__file__).resolve().parent.parent / "data" / "raw" /
              "nflverse" / "stats_player_week_2024.csv")


# --------------------------------------------------------------------- #
# RULE S2 — the pre-baked total is an oracle, never an input
# --------------------------------------------------------------------- #

def test_our_ppr_reproduces_nflverses_own_total_for_every_offensive_player() -> None:
    """MEASURED: 18,130 regular-season player-weeks of 2024, and every offensive
    position matches to the cent. This is what makes RULE S1 safe to follow —
    we compute from stat lines rather than reading their column, and this proves
    the arithmetic agrees where the two overlap.

    Rows with KICKING points are excluded, because nflverse's
    fantasy_points_ppr is an offence-only formula and kicking is not a
    comparable quantity. Note the exclusion is MECHANICAL — "does kicking
    contribute to our score" — not categorical ("is the position K"). The
    categorical version passed 17,586 of 17,587 rows and failed on Mitch
    Wishnowsky, a PUNTER who kicked an emergency 26-yard field goal in week 5.
    Our score was right and the test was wrong; a label-based exclusion hides
    exactly the edge cases a label does not cover. The next test proves the
    excluded rows differ by their kicking and nothing else."""
    if not SEASON_CSV.is_file():
        pytest.skip("nflverse cache not present — run `make index`")
    rule = preset(PPR)
    mismatches: list[str] = []
    compared = 0
    with SEASON_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("season_type") or "REG").upper() != "REG":
                continue
            theirs = row.get("fantasy_points_ppr")
            if theirs in (None, "", "NA") or _kicking(row, rule):
                continue
            compared += 1
            if abs(score(row, rule) - float(theirs)) > 0.011:
                mismatches.append(
                    f"{row['player_display_name']} ({row['position']}) "
                    f"wk{row['week']}: {score(row, rule)} vs {theirs}")
    assert compared > 10_000, f"only {compared} rows compared — cache looks thin"
    assert not mismatches, (
        f"{len(mismatches)} of {compared} disagree with nflverse's own PPR "
        f"total: {mismatches[:5]}")


def test_every_kicker_difference_is_exactly_our_kicking_terms() -> None:
    """The honest half of the test above. If those rows were excluded because
    they were merely inconvenient, this would fail — the residual after removing
    our kicking points must be zero, proving the gap is nflverse's offence-only
    formula and not a bug of ours. Covers every row that kicks, punters
    included, not just those labelled K."""
    if not SEASON_CSV.is_file():
        pytest.skip("nflverse cache not present — run `make index`")
    rule = preset(PPR)
    residuals: list[float] = []
    with SEASON_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("season_type") or "REG").upper() != "REG":
                continue
            theirs = row.get("fantasy_points_ppr")
            if theirs in (None, "", "NA") or not _kicking(row, rule):
                continue
            residuals.append(score(row, rule) - float(theirs) - _kicking(row, rule))
    assert len(residuals) > 400, f"only {len(residuals)} kicking rows found"
    assert max(abs(r) for r in residuals) <= 0.011, (
        "a kicker difference is NOT explained by our kicking terms, so the "
        "exclusion above is hiding a real disagreement")


# --------------------------------------------------------------------- #
# the presets
# --------------------------------------------------------------------- #

def test_the_presets_differ_only_in_the_reception_term() -> None:
    """Reception value is the axis leagues actually vary. If a preset ever
    diverges elsewhere, two subscribers on "the same" scoring get different
    numbers for reasons nobody documented."""
    base = {k: v for k, v in PRESETS[STANDARD].__dict__.items() if k != "reception"}
    for name in (PPR, HALF_PPR):
        other = {k: v for k, v in PRESETS[name].__dict__.items() if k != "reception"}
        assert other == base, f"{name} diverges from standard beyond receptions"
    assert PRESETS[PPR].reception == 1.0
    assert PRESETS[HALF_PPR].reception == 0.5
    assert PRESETS[STANDARD].reception == 0.0


def test_the_preset_names_match_what_a_signup_ref_can_carry() -> None:
    """run/refs.py encodes exactly these three. A name here that the ref cannot
    express is a scoring nobody can actually sign up for."""
    from run.refs import SCORING
    assert set(PRESETS) == set(SCORING.values())


def test_an_unknown_scoring_raises_rather_than_defaulting() -> None:
    """Falling back to PPR would silently score a standard league as PPR —
    every receiver inflated, every ranking wrong, no error anywhere."""
    with pytest.raises(ScoringError):
        preset("superflex")


# --------------------------------------------------------------------- #
# the arithmetic
# --------------------------------------------------------------------- #

def test_a_receiving_line_scores_by_its_reception_rule() -> None:
    line = {"receptions": 8, "receiving_yards": 96, "receiving_tds": 1}
    assert score(line, preset(STANDARD)) == pytest.approx(15.6)
    assert score(line, preset(HALF_PPR)) == pytest.approx(19.6)
    assert score(line, preset(PPR)) == pytest.approx(23.6)


def test_a_passing_line_scores_at_a_point_per_twenty_five() -> None:
    line = {"passing_yards": 300, "passing_tds": 2, "passing_interceptions": 1}
    assert score(line, preset(PPR)) == pytest.approx(300 * 0.04 + 8 - 2)


def test_only_fumbles_LOST_are_penalised() -> None:
    """A fumble the offense recovers costs a league nothing. Summing
    fumbles_total would charge players for plays their own team kept."""
    kept = {"rushing_fumbles": 3, "fumbles_total": 3, "rushing_fumbles_lost": 0}
    assert score(kept, preset(PPR)) == 0.0
    lost = {"rushing_fumbles": 1, "rushing_fumbles_lost": 1}
    assert score(lost, preset(PPR)) == pytest.approx(-2.0)


def test_absent_stats_contribute_nothing_and_never_raise() -> None:
    """RULE S3. A rusher has no receiving line; nflverse writes "NA" and
    sometimes nothing at all."""
    assert score({}, preset(PPR)) == 0.0
    assert score({"receiving_yards": "NA", "rushing_yards": ""}, preset(PPR)) == 0.0
    assert score({"rushing_yards": "not a number"}, preset(PPR)) == 0.0


def test_kickers_score_by_distance() -> None:
    line = {"fg_made_20_29": 1, "fg_made_40_49": 1, "fg_made_50_59": 1,
            "pat_made": 3}
    rule = preset(PPR)
    assert score(line, rule) == pytest.approx(3 + 4 + 5 + 3)
    # 60+ rides with 50+ rather than inventing a tier no ruleset defines
    assert score({"fg_made_60_": 1}, rule) == pytest.approx(rule.fg_50_plus)


def test_a_custom_rule_can_express_a_real_league() -> None:
    """Six-point passing touchdowns and per-reception TE premium are common.
    The rule is a value object, so a league that is not one of the three
    presets is expressible without touching this module."""
    six_point = ScoringRule(reception=1.0, passing_td=6.0)
    line = {"passing_tds": 3, "receptions": 2}
    assert score(line, six_point) == pytest.approx(18 + 2)
    assert six_point.with_reception(1.5).reception == 1.5


def test_scores_are_rounded_so_two_runs_never_disagree_by_float_noise() -> None:
    line = {"receiving_yards": 33, "rushing_yards": 17}
    assert score(line, preset(PPR)) == round(score(line, preset(PPR)), 2)
