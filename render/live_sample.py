"""This week's report, for the published sample roster — site/this-week.html.

Usage:
    python -m render.live_sample [--out PATH]

The published sample (render/sample.py) is a 2024 week: reproducible and
pinned, and silently saying "this product isn't running yet" to anyone who
notices the year. This page is its live twin: the same roster, rebuilt every
Tuesday by the weekly cron for the week being played, through the same
pipeline a subscriber's report goes through. Nothing is recorded — it is not
a subscriber, so none of its calls enter the public ledger — and the page says
plainly what it is.

When the week cannot be built (a data outage, the offseason) the previous page
stays up and this exits 0: a stale-but-labelled sample beats a cron failure
that files an issue every week of the offseason.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from engine.subscriber import RosterSpec
from render.report import TEMPLATE_PATH, render
from render.sample import SAMPLE_ROSTER, SLOTS
from run.solo import CACHE_DIR, SoloError, load_week_data, report_for

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_OUT = REPO_ROOT / "site" / "this-week.html"


def build(cache_dir: Path = CACHE_DIR, season: str | None = None,
          week: int | None = None) -> dict:
    data = load_week_data(cache_dir, season, week)
    known = {p.player_id for p in data.directory.players}
    # A sample player who has left the league since 2024 is dropped rather
    # than failing the page; the roster stays well past a full lineup.
    roster = tuple(pid for pid in SAMPLE_ROSTER if pid in known)
    spec = RosterSpec(player_ids=roster, slots=SLOTS, scoring="ppr",
                      label="Sample roster")
    report = report_for(spec, data, league_size=12)
    report["meta"]["live_demo"] = True
    report["meta"]["anonymized_demo"] = True
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=LIVE_OUT)
    parser.add_argument("--season")
    parser.add_argument("--week", type=int)
    args = parser.parse_args(argv)
    try:
        report = build(season=args.season, week=args.week)
    except (SoloError, Exception) as exc:  # noqa: BLE001 — keep the last page
        print(f"this week's sample was not rebuilt ({exc}); the previous page "
              f"stays up.")
        return 0
    args.out.write_text(render(report, TEMPLATE_PATH.read_text(encoding="utf-8")),
                        encoding="utf-8")
    called = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    print(f"this week's sample -> {args.out} · {report['meta']['season']} week "
          f"{report['meta']['week']} · {called}/{len(report['lineup'])} with odds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
