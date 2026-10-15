"""This week's report, for a 2026 sample roster — site/this-week.html.

Usage:
    python -m render.live_sample [--out PATH]

The published sample (render/sample.py) is a 2024 week: reproducible and
pinned, and silently saying "this product isn't running yet" to anyone who
notices the year. This page is its live twin: a 2026 sample roster
(LIVE_ROSTER, chosen by a stated pre-season rule), rebuilt every
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
from render.sample import SLOTS
from run.solo import CACHE_DIR, SoloError, load_week_data, report_for

REPO_ROOT = Path(__file__).resolve().parent.parent

# The live sample's own roster (Oct 2026). It used to be the pinned 2024
# sample's roster, which had three Lions and two Bengals: in their shared bye
# week the bench emptied and the page the landing links as proof printed no
# odds, no closest call and no if/then (launch audit). Chosen ONCE by a stated
# pre-season rule and never by this season's results, so it cannot flatter:
# a mid-round 12-team PPR team — for each target rank, the player at that
# 2025 PPR points-per-game rank (8+ games) who has a 2026 team, moving down a
# rank while the roster already holds that position's bye week or two players
# on it; one defense, the 5th-best by 2025 points allowed per game, by the same
# bye rule. Targets: QB 6, 16 · RB 5, 14, 26, 38, 50 · WR 4, 13, 25, 37, 49 ·
# TE 7, 19 · K 8 · DEF 5. Pinned, because a trade would otherwise reshuffle it.
LIVE_ROSTER = (
    "00-0037834",  # Brock Purdy         QB  SF  (QB6)
    "00-0034796",  # Lamar Jackson       QB  BAL (QB16)
    "00-0039040",  # De'Von Achane       RB  MIA (RB5)
    "00-0036973",  # Travis Etienne      RB  NO  (RB14)
    "00-0040784",  # Quinshon Judkins    RB  CLE (RB26)
    "00-0039032",  # Tyjae Spears        RB  TEN (RB38)
    "00-0040202",  # Devin Neal          RB  WAS (RB50)
    "00-0036963",  # Amon-Ra St. Brown   WR  DET (WR4)
    "00-0039064",  # Zay Flowers         WR  BAL (WR13)
    "00-0039919",  # Rome Odunze         WR  CHI (WR25)
    "00-0037261",  # Khalil Shakir       WR  BUF (WR40)
    "00-0037545",  # Rashid Shaheed      WR  SEA (WR50)
    "00-0030506",  # Travis Kelce        TE  KC  (TE9)
    "00-0030061",  # Zach Ertz           TE  PHI (TE19)
    "00-0031136",  # Chris Boswell       K   PIT (K12)
    "DEF-KC",      # Chiefs              DEF (6th by points allowed)
)
# Below this many printed odds the page doesn't show what the landing sells,
# and the landing's hero stops linking it that week (week.json "odds").
SHOWCASE_MIN_ODDS = 3
LIVE_OUT = REPO_ROOT / "site" / "this-week.html"

# The ?via= channel tag, carried onto this page's links into the funnel. The
# Tuesday posts link THIS page, and its "set it up" link dropped the tag, so a
# signup from a tagged post was counted nowhere (launch audit F2). carryVia is
# the funnel pages' own function, character for character (tests/test_site.py
# compares every copy and runs it under node). URL only — nothing is stored.
VIA_SCRIPT = r"""<script>
"use strict";
// A cookie-free source tag (?via=<channel>), carried onto the links below.
const VIA = (new URLSearchParams(location.search).get("via") || "")
  .toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 24) || undefined;
// The tag rides every link into the funnel pages that read it (launch audit
// F2): each page takes it from its OWN address only, so a tag that stopped at
// the page it was posted to was counted nowhere. URL only, never stored. The
// same function, character for character, is on every funnel page and in the
// live sample (tests/test_site.py compares them and runs it under node).
function carryVia(href, via) {
  if (!via || !/^[a-z0-9-]{1,24}$/.test(via) || !href) return href;
  const cut = href.indexOf("#");
  const base = cut < 0 ? href : href.slice(0, cut);
  const hash = cut < 0 ? "" : href.slice(cut);
  const funnel = /^(?:\.\.\/)?(?:index\.html|join\/(?:index\.html)?|this-week\.html|league-pass\.html|how-it-works\.html)(?:\?|$)/;
  if (!funnel.test(base) || /[?&]via=/.test(base)) return href;
  return base + (base.indexOf("?") < 0 ? "?" : "&") + "via=" + via + hash;
}
if (VIA) {
  document.querySelectorAll("a[href]").forEach((a) => {
    a.setAttribute("href", carryVia(a.getAttribute("href"), VIA));
  });
}
</script>
"""


def with_via_carry(page: str) -> str:
    """The rendered page with VIA_SCRIPT just before its closing body tag (at
    the end, so every link it decorates already exists)."""
    head, tag, tail = page.rpartition("</body>")
    if not tag:
        return page + VIA_SCRIPT
    return head + VIA_SCRIPT + tag + tail


def build(cache_dir: Path = CACHE_DIR, season: str | None = None,
          week: int | None = None) -> dict:
    data = load_week_data(cache_dir, season, week)
    known = {p.player_id for p in data.directory.players}
    # A sample player who has left the league since 2024 is dropped rather
    # than failing the page; the roster stays well past a full lineup.
    roster = tuple(pid for pid in LIVE_ROSTER if pid in known)
    spec = RosterSpec(player_ids=roster, slots=SLOTS, scoring="ppr",
                      label="Sample roster")
    report = report_for(spec, data, league_size=12)
    report["meta"]["live_demo"] = True
    report["meta"]["anonymized_demo"] = True
    return report


def next_report_day(cache_dir: Path, season: str, week: int) -> str | None:
    """The Tuesday the NEXT weekly report goes out: the first Tuesday after the
    last game of ``week`` (the week this build's report covers), as an ISO
    date. None when the schedule cannot say."""
    from datetime import date, timedelta
    from run.solo import _schedule, _weeks
    days = (_weeks(_schedule(cache_dir), season).get(int(week)) or [])
    if not days:
        return None
    last = date.fromisoformat(max(days))
    ahead = (1 - last.weekday()) % 7 or 7            # Tuesday is weekday 1
    return (last + timedelta(days=ahead)).isoformat()


def write_week_json(report: dict, path: Path, lands_on: str | None = None) -> None:
    """The season clock the landing page reads (site/week.json): the week this
    report covers, the season's last week, and the day the next report lands,
    so the hero can say "Week 7's report lands Tuesday" from the schedule
    rather than from a sentence somebody typed in September. Written beside
    the live page by the same build, committed by the same persist step. The
    page shows the line only in the days just before ``lands_on``."""
    import json
    meta = report["meta"]
    odds = sum(1 for slot in report.get("lineup") or []
               if slot.get("confidence") is not None)
    path.write_text(json.dumps({
        "season": meta["season"], "week": meta["week"],
        "last_week": meta.get("last_week"), "lands_on": lands_on,
        "built_at": meta.get("generated_at"),
        # What the live page shows this week, so the landing links it only
        # when it actually shows the product (launch audit: a bye week once
        # left it with nothing).
        "odds": odds, "closest_call": "gate" not in (report.get("regret") or {"gate": 1}),
    }, separators=(",", ":")) + "\n", encoding="utf-8")


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
    args.out.write_text(
        with_via_carry(render(report, TEMPLATE_PATH.read_text(encoding="utf-8"))),
        encoding="utf-8")
    try:
        lands_on = next_report_day(CACHE_DIR, report["meta"]["season"],
                                   report["meta"]["week"])
    except Exception:  # noqa: BLE001 — no date means the page says nothing new
        lands_on = None
    write_week_json(report, args.out.with_name("week.json"), lands_on)
    called = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    print(f"this week's sample -> {args.out} · {report['meta']['season']} week "
          f"{report['meta']['week']} · {called}/{len(report['lineup'])} with odds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
