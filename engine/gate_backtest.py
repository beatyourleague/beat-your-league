"""Does the SHIPPING gate actually produce calibrated numbers?

This is the product's biggest open question. The report publishes a confidence
only when both players are confirmed active, and that rule has never been
measured, because live availability snapshots start this season. So the only
figure we may honestly publish is the unconditional one — ECE 7.2%, 1 of 6
buckets calibrated — which describes a model with NO gate, i.e. not the product
anyone receives.

The tempting substitute is the availability-controlled table in
reports/backtest.md, and it is forbidden as a claim for a specific reason: it
keeps head-to-heads where both players *ended up scoring*, which nobody knows
when the call is made. Conditioning on the outcome flatters the model.

An injury REPORT is published before kickoff, so conditioning on it is fair.
This module reconstructs the gate from nflverse's archive and re-measures the
frozen 2017-18 call set under it.

WHAT THE RECONSTRUCTION IS. A player carrying Out / Doubtful / IR / PUP that
week is OUT; Questionable or Limited is IN DOUBT; anyone not on the report is
ACTIVE, because an injury report lists who is in question, not who is fine.

WHAT IT IS NOT. It does not model byes — the live gate resolves those from the
NFL schedule, and a player's historical team is not recoverable from today's
players table. So this measures the injury half of the gate only, and a bye
would have been caught separately. Stated here rather than buried, because the
number this produces is only worth publishing if its limits travel with it.

Reconstructed weeks never enter data/raw/availability/: that store holds
snapshots observed live and is the one dataset the product cannot rebuild.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from engine.calibration import MIN_DECIDED_TO_JUDGE, bucket_calls
from engine.decisions import StartSitCall
from ingest.injuries import ATTRIBUTION, fetch, load_weeks

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"

IN_DOUBT = {"Out", "Questionable"}


@dataclass(frozen=True)
class GateResult:
    """The same call set, before and after the gate."""

    total: int
    kept: int
    dropped_out: int
    dropped_doubt: int
    unknown_player: int

    @property
    def kept_share(self) -> float:
        return self.kept / self.total if self.total else 0.0


def designations_by_player(
    season: str, players: Mapping[str, object], raw_dir: Path = RAW_DIR,
) -> dict[int, dict[str, str]]:
    """``{week: {sleeper_player_id: designation}}`` for one season."""
    path = fetch(season, raw_dir / "injuries")
    gsis_to_sleeper = {
        record["gsis_id"]: pid
        for pid, record in players.items()
        if isinstance(record, dict) and record.get("gsis_id")
    }
    out: dict[int, dict[str, str]] = {}
    for week, injury_week in load_weeks(path, season).items():
        mapped: dict[str, str] = {}
        for gsis, designation in injury_week.by_gsis.items():
            pid = gsis_to_sleeper.get(gsis)
            if pid:
                mapped[pid] = designation
        out[week] = mapped
    return out


def apply_gate(
    calls: Sequence[StartSitCall],
    designations: Mapping[str, Mapping[int, Mapping[str, str]]],
) -> tuple[list[StartSitCall], GateResult]:
    """Keep only calls where NEITHER player was in doubt before kickoff."""
    kept: list[StartSitCall] = []
    dropped_out = dropped_doubt = unknown = 0
    for call in calls:
        season_map = designations.get(call.season)
        if season_map is None:
            unknown += 1
            continue
        week_map = season_map.get(call.week, {})
        marks = [week_map.get(call.started_id), week_map.get(call.alternative_id)]
        if any(m == "Out" for m in marks):
            dropped_out += 1
            continue
        if any(m == "Questionable" for m in marks):
            dropped_doubt += 1
            continue
        kept.append(call)
    return kept, GateResult(
        total=len(calls), kept=len(kept), dropped_out=dropped_out,
        dropped_doubt=dropped_doubt, unknown_player=unknown,
    )


def compare(before: Sequence[StartSitCall],
            after: Sequence[StartSitCall]) -> list[str]:
    """A markdown section: the same buckets, ungated then gated."""
    lines = [
        "",
        "## Calibration under the shipping gate",
        "",
        "The product publishes a confidence only when both players are confirmed "
        "active. That rule had never been measured — live snapshots start this "
        "season — so the headline table above describes a model with no gate, "
        "which is not the product anyone receives.",
        "",
        "The gate is reconstructed here from the pre-kickoff injury report, which "
        "is legitimate to condition on: it is published before the games. This is "
        "NOT the availability-controlled diagnostic elsewhere in this document, "
        "which keeps head-to-heads where both players ended up scoring and so "
        "conditions on the result.",
        "",
        "| Stated confidence | Decided (ungated) | Observed | Decided (gated) | Observed | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    gated = {r.bucket.label: r for r in bucket_calls(after)}
    for report in bucket_calls(before):
        if report.bucket.graded == 0:
            continue
        g = gated.get(report.bucket.label)
        verdict = "too few" if not g or g.calibrated is None else (
            "calibrated" if g.calibrated else "off")
        before_rate = report.bucket.hit_rate
        after_rate = g.bucket.hit_rate if g else None
        lines.append(
            f"| {report.bucket.label} | {report.bucket.decided} | "
            f"{f'{before_rate * 100:.1f}%' if before_rate is not None else 'n/a'} | "
            f"{g.bucket.decided if g else 0} | "
            f"{f'{after_rate * 100:.1f}%' if after_rate is not None else 'n/a'} | "
            f"{verdict} |"
        )
    lines += ["", f"Buckets need {MIN_DECIDED_TO_JUDGE} decided calls to be judged. "
                  f"{ATTRIBUTION}"]
    lines += _verdict(before, after)
    return lines


def _verdict(before: Sequence[StartSitCall],
             after: Sequence[StartSitCall]) -> list[str]:
    """State the finding in words, so a skim cannot mistake it for a pass."""
    def judged(calls: Sequence[StartSitCall]) -> tuple[int, int]:
        reports = [r for r in bucket_calls(calls) if r.calibrated is not None]
        return sum(1 for r in reports if r.calibrated), len(reports)

    ok_before, n_before = judged(before)
    ok_after, n_after = judged(after)
    rates = [r.bucket.hit_rate for r in bucket_calls(after)
             if r.bucket.decided >= MIN_DECIDED_TO_JUDGE and r.bucket.hit_rate]
    spread = (max(rates) - min(rates)) * 100 if len(rates) > 1 else 0.0
    return [
        "",
        "### What this settles",
        "",
        f"- The gate keeps {len(after)} of {len(before)} calls "
        f"({len(after) / len(before):.1%}); the rest had a player carrying a "
        f"designation before kickoff.",
        f"- Calibrated buckets go from {ok_before} of {n_before} to "
        f"{ok_after} of {n_after}. **It is an improvement, not a rescue.**",
        f"- Resolution stays flat: judged buckets span {spread:.1f} points of "
        f"observed hit rate across the whole stated range, so the number still "
        f"barely sorts good calls from bad ones.",
        "",
        "The conclusion is uncomfortable and it is the one the evidence supports: "
        "filtering on the injury report does NOT recover the calibration seen in "
        "the availability-controlled diagnostic. That table conditions on both "
        "players having scored, and most of what it was really selecting for is "
        "not injury at all — it is healthy players who were never going to get "
        "the ball. A backup in a committee carries no designation.",
        "",
        "So the shipping gate is worth keeping as an honesty measure — it stops "
        "us printing a number about someone who is doubtful — but it does not by "
        "itself earn a published accuracy claim, and this document does not make "
        "one.",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    from engine.decisions import all_calls
    from engine.history import load_players, load_season_chain
    from engine.projection import ProjectionModel

    seasons = load_season_chain(args.raw_dir, args.league, max_seasons=2)
    players = load_players(args.raw_dir)
    players_raw = json.loads(
        (args.raw_dir / "players" / "nfl.json").read_text(encoding="utf-8"))

    calls: list[StartSitCall] = []
    for season in seasons:
        calls.extend(all_calls(season, ProjectionModel(season, players), players))
    if not calls:
        print("no graded calls in the cache", file=sys.stderr)
        return 1

    designations = {
        season.season: designations_by_player(season.season, players_raw, args.raw_dir)
        for season in seasons
    }
    kept, result = apply_gate(calls, designations)
    print(f"call set: {result.total}")
    print(f"  dropped, a player was OUT:          {result.dropped_out}")
    print(f"  dropped, a player was QUESTIONABLE: {result.dropped_doubt}")
    print(f"  kept under the shipping gate:       {result.kept} "
          f"({result.kept_share:.1%})")
    print()
    body = compare(calls, kept)
    header = [
        "# The shipping gate, measured",
        "",
        f"Generated from cached data by `python -m engine.gate_backtest "
        f"--league {args.league}`. The call set is the same frozen 2017-18 set "
        f"the main backtest grades; the only thing added is the pre-kickoff "
        f"injury report.",
        "",
        f"- call set: **{result.total}**",
        f"- dropped, a player was OUT: {result.dropped_out}",
        f"- dropped, a player was QUESTIONABLE: {result.dropped_doubt}",
        f"- kept under the shipping gate: **{result.kept}** "
        f"({result.kept_share:.1%})",
        "",
        "The reconstruction covers the INJURY half of the gate only. Byes are "
        "resolved live from the NFL schedule and a player's historical team is "
        "not recoverable from today's players table, so a bye would have been "
        "caught separately and is not modelled here.",
    ]
    out = REPO_ROOT / "reports" / "gate-backtest.md"
    out.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    print("\n".join(body))
    print(f"\nwritten to {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
