"""Build the public sample report — the funnel's proof asset.

Usage:
    python -m render.sample                     # site/sample-report.html (week 10)
    python -m render.sample --week 1 --out ...  # the first-week companion

``make sample`` is the only way to rebuild this page, for the same reason
``make demo`` was the only way to rebuild the old one: the published sample is
the launch proof, and an ad-hoc rebuild is how it once drifted from the engine
that claims to have produced it.

Everything here runs through the REAL pipeline — ``run/solo.py`` builds the
report exactly as a Tuesday run would, and ``render/report.py`` renders it with
the same template a subscriber's archival copy uses. The one difference is two
meta flags: ``historical_demo`` (the banner says what this is) and
``anonymized_demo`` (the closing ask renders). No number on the page can exist
unless the product computed it.

The roster is FIXED and documented so the page is reproducible: well-known
2024 players a visitor will recognize, in the product's default 12-team PPR
shape, at week 10 — far enough into a season that form, usage and confidences
all publish. That makes it the mixed week the real product ships: three slots
carry a number, three carry an explained hold ("status unconfirmed"), and the
QB, K and DEF rows carry none at all, because their reason is STRUCTURAL (no
bench alternative; defenses ungraded) and lives in the note under the table
rather than on a row that would repeat it every week — see
render.report.is_structural_gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

from engine.subscriber import RosterSpec
from render.report import TEMPLATE_PATH, render
from run.solo import CACHE_DIR, SoloError, load_week_data, report_for

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "site" / "sample-report.html"
FIRST_WEEK_OUT = REPO_ROOT / "site" / "sample-first-week.html"

SEASON, WEEK = "2024", 10
# The companion page. A buyer decides on a mid-season file and then receives a
# WEEK ONE file, which by design carries no number anywhere — no week-0 injury
# report exists, so nothing is confirmable and nothing prints. That gap between
# what was sold and what arrives is a Week-2 refund with a stamp on it, and the
# honest fix is to publish the first file too, through the same pipeline.
FIRST_WEEK = 1

# GSIS ids, resolved once from the directory and pinned. Names in comments so a
# reader can check the page against this list.
SAMPLE_ROSTER = (
    "00-0034857",  # Josh Allen          QB
    "00-0034844",  # Saquon Barkley      RB
    "00-0038542",  # Bijan Robinson      RB
    "00-0036900",  # Ja'Marr Chase       WR
    "00-0036963",  # Amon-Ra St. Brown   WR
    "00-0033288",  # George Kittle       TE
    "00-0039146",  # Jayden Reed         WR (bench)
    "00-0038597",  # Chase Brown         RB (bench)
    "DEF-BAL",     # Ravens              DEF (bench)
    "00-0039172",  # Jake Bates          K
    "00-0035261",  # Tony Pollard        RB (flex)
    "00-0034348",  # Courtland Sutton    WR (bench)
    "00-0039065",  # Sam LaPorta         TE (bench)
    "00-0039919",  # Rome Odunze         WR (bench)
    "DEF-DEN",     # Broncos             DEF
)
SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")


def build(week: int = WEEK) -> dict:
    data = load_week_data(CACHE_DIR, SEASON, week)
    spec = RosterSpec(player_ids=SAMPLE_ROSTER, slots=SLOTS, scoring="ppr",
                      label="Your Team")
    report = report_for(spec, data, league_size=12)
    report["meta"]["historical_demo"] = True
    report["meta"]["anonymized_demo"] = True
    # Which of the two published samples this is, so each page points at the
    # other rather than at itself.
    report["meta"]["first_week_demo"] = week == FIRST_WEEK
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, default=WEEK)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    out = args.out or (FIRST_WEEK_OUT if args.week == FIRST_WEEK else DEFAULT_OUT)
    try:
        report = build(args.week)
    except SoloError as exc:
        print(f"could not build the sample: {exc}", file=sys.stderr)
        return 1
    html = render(report, TEMPLATE_PATH.read_text(encoding="utf-8"))
    out.write_text(html, encoding="utf-8")

    published = [s for s in report["lineup"] if s.get("confidence") is not None]
    print("=" * 62)
    print(f"sample report -> {out}")
    print(f"  {report['meta']['season']} week {report['meta']['week']} · "
          f"{len(published)}/{len(report['lineup'])} confidences published")
    for slot in report["lineup"]:
        conf = (f"{slot['confidence']:.3f}" if slot.get("confidence") is not None
                else "no call")
        print(f"    {slot['slot']:5s} {str(slot['player_name'])[:22]:22s} "
              f"proj={slot.get('projected')} conf={conf}")
    regret = report.get("regret") or {}
    if regret.get("confidence") is not None:
        print(f"  regret: {regret['start_name']} over {regret['over_name']} "
              f"({regret['confidence']:.3f}) at {regret['slot']}")
    you = report.get("matchup", {}).get("you", {})
    if you.get("projected_total") is not None:
        print(f"  total {you['projected_total']} "
              f"({you.get('floor')}–{you.get('ceiling')})")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
