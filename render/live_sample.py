"""This week's report, for a 2026 sample roster — site/this-week.html.

Usage:
    python -m render.live_sample [--out PATH] [--force] [--no-record]

The published sample (render/sample.py) is a 2024 week: reproducible and
pinned, and silently saying "this product isn't running yet" to anyone who
notices the year. This page is its live twin: a 2026 sample roster
(LIVE_ROSTER, chosen by a stated pre-season rule), rebuilt every
Tuesday by the weekly cron for the week being played, through the same
pipeline a subscriber's report goes through, and the page says plainly what
it is.

**Its odds are on the record (principle 2, G04, Oct 15 2026).** This page
prints probabilities in public every week, the landing links it, and the
Tuesday post drafts (run/drops.py) quote it — and none of it was recorded, so
none of it could ever be graded, while section 07 of the page promised
"Results · from next week" forever. A % posted in public is a published
probability (the rule `make ask` already follows). So a build made before the
week's first kickoff RECORDS every odds it prints in the public ledger, in the
same store a subscriber with this setup uses (typed-ppr-12-<season>): the same
call made for a subscriber is the same row (RULE L4, idempotent by call id),
and the Monday run grades both by the same rules. The ledger is written FIRST
and the page only after — a page whose odds could not be recorded is not
published.

**A week that has kicked off is not rebuilt.** A rebuild after Thursday's
kickoff would print "predictions" about a game underway, and would move odds
already on the record. It is refused and the published page stays; ``--force``
rebuilds anyway (a rendering fix) and then records NOTHING, saying so.
``--no-record`` previews without recording.

When the week cannot be built (a data outage, the offseason) the previous page
stays up and this exits 0: a stale-but-labelled sample beats a cron failure
that files an issue every week of the offseason.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.subscriber import RosterSpec
from render.report import TEMPLATE_PATH, esc, render
from render.sample import SLOTS
from run.solo import CACHE_DIR, SoloError, load_week_data, report_for

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

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
    report["meta"]["thin_week_note"] = thin_week_line(report, absences(data, roster))
    return report


# --------------------------------------------------------------------- #
# a thin week says why (BE-I8, I17)
# --------------------------------------------------------------------- #

def absences(data, roster: tuple[str, ...]) -> list[tuple[str, str]]:
    """(name, why) for each sample player who cannot play this week: his
    team's bye (the NFL schedule) or a roster status that rules him out
    (injured reserve, PUP, suspended, released — today's players release,
    live week only). Facts the checklist already acts on ("Bench X — he can't
    play this week"); a last-week injury designation is NOT one of them,
    because this week's status is not announced yet and the page says so."""
    statuses = getattr(data.availability, "statuses", None) or {}
    byes = getattr(data.availability, "bye_teams", None) or frozenset()
    out: list[tuple[str, str]] = []
    for pid in roster:
        team = (statuses.get(pid) or {}).get("team")
        why = ("on bye" if team and team in byes
               else str((getattr(data, "roster_out", None) or {}).get(pid) or ""))
        if why:
            out.append((data.players.name(pid), why))
    return out


def _listed(names: list[str]) -> str:
    return (names[0] if len(names) == 1
            else f"{', '.join(names[:-1])} and {names[-1]}")


def thin_week_line(report: Mapping[str, Any],
                   missing: list[tuple[str, str]]) -> str | None:
    """One line for the banner when byes or roster moves leave the page with
    fewer than SHOWCASE_MIN_ODDS odds: who can't play and why, and how many
    slots carry odds. Both halves are counts the build computed; nothing is
    said about what the week would otherwise have shown. None on a full week,
    or when nobody is missing (then thinness has another cause and a line
    blaming byes would be false)."""
    lineup = report.get("lineup") or []
    odds = sum(1 for slot in lineup if slot.get("confidence") is not None)
    if odds >= SHOWCASE_MIN_ODDS or not missing:
        return None
    groups: dict[str, list[str]] = {}
    for name, why in missing:
        groups.setdefault(why, []).append(name)
    who = "; ".join(f"{_listed(names)} ({why})" for why, names in groups.items())
    players = "player" if len(missing) == 1 else "players"
    return (f"Why this week is thin: {len(missing)} of this roster's {players} "
            f"can't play — {who} — and {odds} of its {len(lineup)} slots "
            f"carry odds.")


_BANNER = re.compile(r'(<div class="regret-note"[^>]*>THIS WEEK.{1,8}S REPORT.*?</div>)',
                     re.S)


def with_thin_week(page: str, line: str | None) -> str:
    """The thin-week line, as its own row directly under the page's banner
    (or at the top of the report if the banner moved)."""
    if not line:
        return page
    note = ('<div class="regret-note" style="margin:0;border-left:none;">'
            f'{esc(line)}</div>')
    if _BANNER.search(page):
        return _BANNER.sub(lambda m: m.group(1) + note, page, count=1)
    return page.replace('<div class="report">', '<div class="report">' + note, 1)


# --------------------------------------------------------------------- #
# the share card names the week (GTM-9)
# --------------------------------------------------------------------- #

def share_text(report: Mapping[str, Any]) -> tuple[str, str]:
    """(og:title, description) for this week's page. Every link to it used to
    preview as "a real weekly report" with a 2024 description while the page
    itself was Week 6 of 2026 — a preview that contradicted the page."""
    meta = report["meta"]
    lineup = report.get("lineup") or []
    odds = sum(1 for slot in lineup if slot.get("confidence") is not None)
    title = f"Beat Your League — this week's report, Week {meta['week']} of {meta['season']}"
    desc = (f"Week {meta['week']} of the {meta['season']} NFL season, for a sample "
            f"roster: the lineup we'd set, with odds on {odds} of its "
            f"{len(lineup)} slots. Rebuilt every Tuesday.")
    return title, desc


def with_week_meta(page: str, report: Mapping[str, Any]) -> str:
    """The rendered page with its og:title, og:description and description
    naming this week. Replaced in place; a tag that is missing is added
    before </head> rather than silently left generic."""
    title, desc = share_text(report)
    for attr, name, value in (("property", "og:title", title),
                              ("property", "og:description", desc),
                              ("name", "description", desc)):
        tag = f'<meta {attr}="{name}" content="{esc(value)}">'
        pattern = re.compile(rf'<meta {attr}="{re.escape(name)}" content="[^"]*">')
        if pattern.search(page):
            page = pattern.sub(lambda _m: tag, page, count=1)
        else:
            page = page.replace("</head>", tag + "\n</head>", 1)
    return page


# --------------------------------------------------------------------- #
# the odds it prints are on the record (G04)
# --------------------------------------------------------------------- #

def record(report: Mapping[str, Any], processed_dir: Path) -> int:
    """Put every probability the page prints in the public ledger, in the
    store a subscriber with this setup uses. -> rows added (0 when the same
    calls are already there: RULE L4 makes recording idempotent by call id).
    Raises on a store that cannot be written — the caller then publishes
    nothing, because a printed % with no record is what this exists to end."""
    from engine.ledger import extract_published_calls, ledger_path, record_calls
    calls = extract_published_calls(report)
    if not calls:
        return 0
    store = str(report["meta"]["league_id"])
    return record_calls(ledger_path(Path(processed_dir), store), calls)


def recorded_only(report: dict, processed_dir: Path = PROCESSED_DIR) -> dict:
    """The report with every probability that is NOT on the record withheld —
    what a public post may quote (run/drops.py drafts from the live sample).
    A % counts as recorded only when its call is in the ledger at the same
    value; anything else (a rebuild after the record was made, an unwritable
    store) is withheld rather than posted. Withholds, never adds or moves."""
    from engine.ledger import LedgerError, extract_published_calls, ledger_path, load_ledger
    store = str(report["meta"].get("league_id") or "")
    try:
        held = {call.call_id: call.confidence
                for call in load_ledger(ledger_path(Path(processed_dir), store))}
    except LedgerError:
        held = {}
    on_record = {(c.slot, c.pick_id, c.over_id) for c in extract_published_calls(report)
                 if c.call_id in held and abs(held[c.call_id] - c.confidence) < 1e-9}
    for slot in report.get("lineup") or []:
        if slot.get("confidence") is None:
            continue
        if (str(slot.get("slot")), str(slot.get("player_id")),
                str(slot.get("alternative_id"))) not in on_record:
            slot["confidence"] = None
    regret = report.get("regret") or {}
    if regret.get("confidence") is not None and (
            str(regret.get("slot")), str(regret.get("start_id")),
            str(regret.get("over_id"))) not in on_record:
        regret["confidence"] = None
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


def write_week_json(report: dict, path: Path, lands_on: str | None = None,
                    first_kickoff: str | None = None) -> None:
    """The season clock the landing page reads (site/week.json): the week this
    report covers, the season's last week, and the day the next report lands,
    so the hero can say "Week 7's report lands Tuesday" from the schedule
    rather than from a sentence somebody typed in September. Written beside
    the live page by the same build, committed by the same persist step. The
    page shows the line only in the days just before ``lands_on``.

    ``first_kickoff`` (ISO-8601 UTC) is the instant this week starts: the join
    page says a buyer's first weekly report comes "today" only before it, and
    "your roster report today, your first weekly report next Tuesday" after
    (panel review PC-02). Absent, the page keeps the sentence true either way."""
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
        "first_kickoff": first_kickoff,
    }, separators=(",", ":")) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=LIVE_OUT)
    parser.add_argument("--season")
    parser.add_argument("--week", type=int)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR,
                        help="where the public ledger lives")
    parser.add_argument("--force", action="store_true",
                        help="rebuild a week that has kicked off; records nothing")
    parser.add_argument("--no-record", action="store_true",
                        help="a preview: build the page, record nothing")
    parser.add_argument("--now", help="ISO time to judge kickoff against (tests)")
    args = parser.parse_args(argv)
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    try:
        report = build(season=args.season, week=args.week)
    except (SoloError, Exception) as exc:  # noqa: BLE001 — keep the last page
        print(f"this week's sample was not rebuilt ({exc}); the previous page "
              f"stays up.")
        return 0
    meta = report["meta"]
    from run.solo import week_has_kicked_off
    kicked_off = week_has_kicked_off(CACHE_DIR, str(meta["season"]), int(meta["week"]),
                                     now=now)
    if kicked_off and not args.force:
        # The page already published for this week carries the odds that are
        # on the record; a rebuild now could print different ones about games
        # underway. Not a failure: the cron simply has nothing to do.
        print(f"this week's sample was not rebuilt: week {meta['week']} has "
              f"kicked off, so its published page and recorded odds stand. "
              f"--force rebuilds it and records nothing.")
        return 0
    recording = not (kicked_off or args.no_record)
    if recording:
        try:
            added = record(report, args.processed_dir)
        except Exception as exc:  # noqa: BLE001 — publish nothing unrecorded
            print(f"this week's sample was NOT published: its odds could not be "
                  f"recorded ({exc}). The previous page stays up.", file=sys.stderr)
            return 1
        print(f"recorded the sample's odds on the public ledger: {added} new "
              f"row(s) in {meta['league_id']}")
    else:
        print("nothing recorded: "
              + ("the week has kicked off (--force)" if kicked_off else "--no-record"))
    page = render(report, TEMPLATE_PATH.read_text(encoding="utf-8"))
    page = with_thin_week(with_week_meta(page, report), meta.get("thin_week_note"))
    args.out.write_text(with_via_carry(page), encoding="utf-8")
    try:
        lands_on = next_report_day(CACHE_DIR, report["meta"]["season"],
                                   report["meta"]["week"])
    except Exception:  # noqa: BLE001 — no date means the page says nothing new
        lands_on = None
    try:
        from run.saturday import kickoffs
        starts = kickoffs(CACHE_DIR, report["meta"]["season"], report["meta"]["week"])
        first = min(starts.values()).astimezone(timezone.utc) if starts else None
        first_kickoff = first.strftime("%Y-%m-%dT%H:%M:%SZ") if first else None
    except Exception:  # noqa: BLE001 — no instant means the either-way sentence
        first_kickoff = None
    write_week_json(report, args.out.with_name("week.json"), lands_on, first_kickoff)
    called = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    print(f"this week's sample -> {args.out} · {report['meta']['season']} week "
          f"{report['meta']['week']} · {called}/{len(report['lineup'])} with odds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
