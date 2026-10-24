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

**A week is recorded ONCE: by its first build before kickoff (OPS-R3).** The
Tuesday cron runs twice (12:17 and the 16:17 retry) and GitHub's backups can
run hours late, and games.csv (market lines) and players.csv (a Tuesday IR
move) revalidate in between — so every later build could record a SECOND set
of calls for the same slots, or print a % that is not the recorded one
(record_calls keeps the first row per call id). site/week.json now says the
week was recorded (``recorded``), and a later build before kickoff keeps the
published page; ``--force`` rebuilds it through ``recorded_only`` — nothing
new recorded, no odds that are not on the record.

**A week that has kicked off is not rebuilt** unless ``--force``, and a forced
rebuild after kickoff (a rendering fix) is a different page, said plainly
(FUNNEL:F3, COPY:F1, G24, R1, SS2-D1, BE2-D3, OPS-R11). It records nothing;
it prints only odds already on the record from before kickoff, and none on a
pair whose game has started (a % beside a game that is already final reads as
a prediction about it); it says under the banner when it was rebuilt and that
the week had begun; its lineup steps are "for the games still to play", never
"before this week's first kickoff"; a game already played is "played", and an
if/then about a player whose game has started is dropped. Withholding only —
nothing here adds or moves a number. ``--no-record`` previews before kickoff
without recording.

When the week cannot be built (a data outage, the offseason) the previous page
stays up and this exits 0: a stale-but-labelled sample beats a cron failure
that files an issue every week of the offseason.
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.subscriber import RosterSpec
from render.report import (JOIN_PROMISE, SAMPLE_CTA_CLOSED, TEMPLATE_PATH,
                           before_counter, esc, render, sample_cta)
from render.sample import SLOTS
from run.solo import CACHE_DIR, SeasonOver, SoloError, load_week_data, report_for

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
  const funnel = /^(?:\.\.\/)?(?:index\.html|join\/(?:index\.html)?|this-week\.html|league-pass\.html|how-it-works\.html|sample-report\.html|sample-first-week\.html)(?:\?|$)/;
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
    """The rendered page with VIA_SCRIPT at the end of its body (so every link
    it decorates already exists), before the page counter, which stays the
    last thing on every public page (render.report.COUNT_TAG)."""
    return before_counter(page, VIA_SCRIPT)


def build(cache_dir: Path = CACHE_DIR, season: str | None = None,
          week: int | None = None, context: dict | None = None) -> dict:
    """This week's sample report. ``context``, when given, is filled with the
    facts a later step needs and the report does not carry: ``teams`` (each
    rostered player's team this week, for which games have started) and
    ``missing`` (who can't play, for the thin-week line)."""
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
    missing = absences(data, roster)
    report["meta"]["thin_week_note"] = thin_week_line(report, missing)
    if context is not None:
        from run.solo import _row_teams
        context["teams"] = _row_teams(spec, data)
        context["missing"] = missing
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
        # The reserve list first (INFO-102): Achane on injured reserve with
        # Miami on bye read "on bye" here while the checklist said IR.
        why = (str((getattr(data, "roster_out", None) or {}).get(pid) or "")
               or ("on bye" if team and team in byes else ""))
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


# The banner is the first notice inside <main> (render/report.py; it was a
# .regret-note before the panel-review chrome, which left the thin-week line
# anchored to nothing and outside every landmark).
_BANNER = re.compile(r'(<div class="(?:notice|regret-note)"[^>]*>(?:<b>)?THIS WEEK.{1,8}S REPORT.*?</div>)',
                     re.S)


def with_thin_week(page: str, line: str | None) -> str:
    """The thin-week line, as its own row directly under the page's banner
    (or at the top of the report if the banner moved)."""
    if not line:
        return page
    note = f'<div class="notice">{esc(line)}</div>'
    if _BANNER.search(page):
        return _BANNER.sub(lambda m: m.group(1) + note, page, count=1)
    if '<main id="main">' in page:
        return page.replace('<main id="main">', '<main id="main">' + note, 1)
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
    when = ("Rebuilt after this week's first kickoff." if meta.get("rebuilt_after_kickoff")
            else "Rebuilt every Tuesday of the season.")
    desc = (f"Week {meta['week']} of the {meta['season']} NFL season, for a sample "
            f"roster: the lineup we'd set, with odds on {odds} of its "
            f"{len(lineup)} slots. {when}")
    return title, desc


# --------------------------------------------------------------------- #
# a rebuild after kickoff is a different page, and says so
# --------------------------------------------------------------------- #

# The checklist's deadline once the week has begun: "before this week's
# first kickoff" had passed, and the forced Week 6 rebuild still printed it
# under "Set this lineup" a day after Thursday night's game (COPY:F1, R1).
STILL_TO_PLAY = "for the games still to play"
# Said by the closest-call section when no call with odds survives the
# rebuild (render.report's one-line no-call form).
# Says why THIS week's closest call is missing, not that no odds survive:
# another row may still print a recorded % (INFO-105).
AFTER_KICKOFF_CLOSEST = ("This week's closest call isn't shown on this rebuild: "
                         "its game has started, or its odds weren't on the "
                         "record before kickoff.")
AFTER_KICKOFF_PIVOTS = ("No if/then on this rebuild: it was built after this "
                        "week's first kickoff, and the games it turned on have "
                        "started.")
# The same, for a forced rebuild BEFORE kickoff of a week already recorded:
# its closest call printed a % the record does not hold (OPS-R3).
REBUILT_CLOSEST = ("This week's closest call isn't shown on this rebuild: its "
                   "odds weren't the ones this week's first build recorded.")


def hold_closest(report: dict, sentence: str) -> dict:
    """A closest call whose % was withheld becomes the one-line no-call form.
    ``recorded_only`` sets the number to None and leaves the card, which the
    renderer cannot draw without one (it raised on the forced rebuild)."""
    regret = report.get("regret") or {}
    if "gate" not in regret and regret.get("confidence") is None:
        report["regret"] = {"gate": sentence}
    return report


def kickoff_split(teams: Mapping[str, str], starts: Mapping[str, datetime],
                  now: datetime) -> tuple[set[str], set[str]]:
    """(players whose game is still to come, players whose game has kicked
    off) at ``now``. A player whose team or kickoff is unknown is in NEITHER:
    he is never "still to come", so a % about him does not print (if we cannot
    tell, we must not publish — the rule week_has_kicked_off follows), and he
    is never said to have "played". Pure."""
    upcoming: set[str] = set()
    played: set[str] = set()
    for pid, team in teams.items():
        start = starts.get(team)
        if start is None:
            continue
        (upcoming if start > now else played).add(pid)
    return upcoming, played


def _past_tense(text: str, names: list[str]) -> str:
    """"Rashid Shaheed (7.6) plays Thursday" -> "played Thursday", for the
    players whose game is behind us; nothing else in the sentence moves."""
    for name in names:
        who = rf"({re.escape(name)}(?: \([0-9.]+\))?)"
        # The engine's timing sentence, whole: "X (7.6) plays Thursday,
        # before Y's status is known" — both halves are behind us.
        text = re.sub(rf"{who} plays (\w+), before (.+?)'s status is known",
                      r"\1 played \2, before \3's status was known", text)
        text = re.sub(rf"{who} plays\b", r"\1 played", text)
    return text


def after_kickoff(report: dict, upcoming: set[str], played_ids: set[str],
                  names: Mapping[str, str]) -> dict:
    """The report as a page rebuilt after the week's first kickoff may show
    it. ``upcoming`` / ``played_ids`` are ``kickoff_split``'s; ``names`` maps
    id -> name for the tense fix.

    Withholds, never adds or moves (owner rule): a % stays only when BOTH
    players' games are still to come, otherwise it goes and its row says
    nothing in the call column (the notice under the banner says why, once);
    a closest call that goes becomes the one-line no-call form; an if/then
    about a player whose game is not still to come goes, and a game already
    played is "played". Run AFTER ``recorded_only``, which has already
    removed every % not on the record."""
    def live(*ids) -> bool:
        return all(str(pid) in upcoming for pid in ids)

    for slot in report.get("lineup") or []:
        if slot.get("confidence") is not None and not live(
                slot.get("player_id"), slot.get("alternative_id")):
            slot["confidence"] = None
            slot["confidence_gate"] = ""
    regret = report.get("regret") or {}
    if "gate" not in regret and (regret.get("confidence") is None
                                 or not live(regret.get("start_id"), regret.get("over_id"))):
        report["regret"] = {"gate": AFTER_KICKOFF_CLOSEST}
    for item in report.get("checklist") or []:
        if "first kickoff" in str(item.get("deadline") or ""):
            item["deadline"] = STILL_TO_PLAY
    played = [names[pid] for pid in sorted(played_ids) if pid in names]
    plans = report.get("pivots") or []
    kept = [dict(plan, action=_past_tense(str(plan.get("action") or ""), played),
                 condition=_past_tense(str(plan.get("condition") or ""), played))
            for plan in plans if live(plan.get("about"))]
    if plans and not kept:
        report["pivots_note"] = AFTER_KICKOFF_PIVOTS
    report["pivots"] = kept
    # A checklist step that sends the reader to a dropped if/then ("check
    # his status — your if/then below has the answer") goes with it.
    gone = [names[str(plan.get("about"))] for plan in plans
            if not live(plan.get("about")) and str(plan.get("about")) in names]
    report["checklist"] = [
        dict(item, action=_past_tense(str(item.get("action") or ""), played),
             detail=_past_tense(str(item.get("detail") or ""), played))
        for item in report.get("checklist") or []
        if not (any(name in str(item.get("action") or "") for name in gone)
                and "if/then" in str(item.get("detail") or ""))]
    report["meta"]["rebuilt_after_kickoff"] = True
    report["meta"]["thin_week_note"] = None
    return _reworded(report, NOT_ANNOUNCED, NOT_READ)


# A row built from last week's designation says this week's status is "not
# announced yet" — true on a Tuesday, false on a rebuild after kickoff, which
# still reads Tuesday's information while the week's own reports are out
# (INFO-117). Reworded, never re-derived: the rebuild adds no new fact.
NOT_ANNOUNCED = "status not announced yet"
NOT_READ = "status not read on this rebuild"


def _reworded(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_reworded(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _reworded(item, old, new) for key, item in value.items()}
    return value


def _eastern(at: datetime) -> str:
    """'Fri Oct 16, 8:03 PM ET' — the clock the site prints every time in."""
    from zoneinfo import ZoneInfo
    local = at.astimezone(ZoneInfo("America/New_York"))
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local:%a %b} {local.day}, {hour}:{local:%M %p} ET"


def after_kickoff_line(report: Mapping[str, Any], built: datetime,
                       first_kickoff: datetime | None) -> str:
    """The notice under the banner of a page rebuilt after kickoff: when it
    was built, that the week had begun, and how many slots still show odds.
    Facts the build computed, nothing else."""
    lineup = report.get("lineup") or []
    odds = sum(1 for slot in lineup if slot.get("confidence") is not None)
    began = (f" ({_eastern(first_kickoff)})" if first_kickoff else "")
    return (f"Rebuilt {_eastern(built)}, after this week's first kickoff{began}. "
            f"It shows odds only where they were on the record before kickoff "
            f"and neither player's game has started — {odds} of its "
            f"{len(lineup)} slots — and its lineup steps are for the games still "
            f"to play.")


def rebuilt_line(report: Mapping[str, Any], built: datetime) -> str:
    """The notice under the banner of a forced rebuild BEFORE kickoff of a
    week already recorded (INFO-107): a row whose % was not the recorded one
    shows none, and this says why, once."""
    lineup = report.get("lineup") or []
    odds = sum(1 for slot in lineup if slot.get("confidence") is not None)
    return (f"Rebuilt {_eastern(built)}, after this week's first build recorded "
            f"its odds. It shows odds only where they match that record — "
            f"{odds} of its {len(lineup)} slots.")


def read_week_json(path: Path) -> dict:
    """The season clock the last build wrote, or {} (absent or unreadable).
    Its ``recorded`` flag is how a later build knows the week's odds are
    already on the record (OPS-R3)."""
    import json
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def recorded_this_week(prior: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    """Did a build of this same week already record its odds?"""
    return (bool(prior.get("recorded"))
            and str(prior.get("season")) == str(meta.get("season"))
            and str(prior.get("week")) == str(meta.get("week")))


def with_week_meta(page: str, report: Mapping[str, Any]) -> str:
    """The rendered page with its og:title, og:description and description
    naming this week. Replaced in place; a tag that is missing is added
    before </head> rather than silently left generic."""
    title, desc = share_text(report)
    return _with_share(page, title, desc)


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
                    first_kickoff: str | None = None, *, recorded: bool = False,
                    after_kickoff: bool = False, phase: str = "season") -> None:
    """The season clock the landing page reads (site/week.json): the week this
    report covers, the season's last week, and the day the next report lands,
    so the hero can say "Week 7's report lands Tuesday" from the schedule
    rather than from a sentence somebody typed in September. Written beside
    the live page by the same build, committed by the same persist step. The
    page shows the line only in the days just before ``lands_on``.

    ``first_kickoff`` (ISO-8601 UTC) is the instant this week starts: the join
    page says a buyer's first weekly report comes "today" only before it, and
    "your roster report today, your first weekly report next Tuesday" after
    (panel review PC-02). Absent, the page keeps the sentence true either way.

    ``recorded``: this week's odds are on the record (by this build or an
    earlier one of the same week), so no later build may record again
    (OPS-R3). ``after_kickoff``: this page was rebuilt after the week began.
    Each is written only when true, so an ordinary week's clock is unchanged.

    ``phase`` is "season" here: a week was built. The two offseason clocks are
    written by ``write_clock`` (D9)."""
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
        **({"recorded": True} if recorded else {}),
        **({"after_kickoff": True} if after_kickoff else {}),
        "phase": phase,
    }, separators=(",", ":")) + "\n", encoding="utf-8")


# --------------------------------------------------------------------- #
# the offseason (D9): no week to build, and the page says so
# --------------------------------------------------------------------- #

# The Tuesday run's last send of the day (weekly.yml's 16:17 UTC retry); a
# derived Week 1 that becomes due later that Tuesday goes out a week later.
LAST_TUESDAY_SEND = time(16, 17)


def write_clock(path: Path, clock: Mapping[str, Any]) -> None:
    import json
    path.write_text(json.dumps(dict(clock), separators=(",", ":")) + "\n",
                    encoding="utf-8")


def week_one_lands_on(first_kickoff: datetime) -> str:
    """The Tuesday a derived Week 1 report first goes out: the first Tuesday
    send at or after ``run.solo.week_one_due`` turns true (WEEK_ONE_LEAD
    before the first kickoff), as its date (the send is mid-morning ET, so
    the UTC and ET dates agree)."""
    from run.solo import WEEK_ONE_LEAD
    due = first_kickoff.astimezone(timezone.utc) - WEEK_ONE_LEAD
    day = due.date()
    while day.weekday() != 1 or datetime.combine(
            day, LAST_TUESDAY_SEND, timezone.utc) < due:
        day += timedelta(days=1)
    return day.isoformat()


def preseason_clock(cache_dir: Path, season: str, now: datetime) -> dict | None:
    """week.json for the weeks between the schedule's release and Week 1's
    first report, or None when ``season``'s derived week is buildable now.
    Nothing is built in this phase: a Week 1 page months before its games
    is the May report D8 retired."""
    from run.solo import current_week, last_week, week_first_kickoff, week_one_due
    if current_week(cache_dir, season, now.date()) != 1 or week_one_due(
            cache_dir, season, 1, now):
        return None
    first = week_first_kickoff(cache_dir, season, 1)
    if first is None:
        return None
    return {"season": str(season), "week": 1,
            "last_week": last_week(cache_dir, season),
            "lands_on": week_one_lands_on(first),
            "built_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "odds": 0, "closest_call": False,
            "first_kickoff": first.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phase": "preseason"}


def over_clock(prior: Mapping[str, Any], cache_dir: Path, today: date) -> dict:
    """week.json once the season is over: the last week's clock kept (season,
    week, last_week, lands_on), with nothing on the page to show."""
    keep = ("season", "week", "last_week", "lands_on", "built_at", "first_kickoff")
    if prior.get("season") and prior.get("week") and prior.get("phase") != "preseason":
        clock = {key: prior.get(key) for key in keep}
    else:
        from run.solo import current_season, last_week
        season = current_season(cache_dir, today)
        week = last_week(cache_dir, season)
        clock = {"season": season, "week": week, "last_week": week,
                 "lands_on": next_report_day(cache_dir, season, week) if week else None,
                 "built_at": None, "first_kickoff": None}
    return {**clock, "odds": 0, "closest_call": False, "phase": "over"}


_LIVE_BANNER = re.compile(
    r'<div class="notice"><b>THIS WEEK(?:\x27|&#x27;)S REPORT</b>(.*?)</div>', re.S)
_REBUILT_LINE = re.compile(
    r'<div class="notice">Rebuilt [^<]*after this week(?:\x27|&#x27;)s first '
    r'(?:kickoff|build)[^<]*</div>')


def last_report_text(season: str, week: str | int) -> tuple[str, str, str]:
    """(banner, og:title, description) for the kept page once its season is
    over (INFO-96, INFO-112): it is that season's last report, not this
    week's, and it is not rebuilt until the next season begins."""
    banner = (f"<b>THE {season} SEASON'S LAST REPORT</b> — Week {week}, for a "
              f"sample roster. This page is rebuilt every Tuesday of the season, "
              f"from Week 1 of the next one.")
    title = f"Beat Your League — the {season} season's last report"
    desc = (f"Week {week} of the {season} NFL season, the last of that season, "
            f"for a sample roster: the lineup we'd set. This page is rebuilt "
            f"every Tuesday of the season, from Week 1 of the next one.")
    return banner, title, desc


_LAST_BANNER = re.compile(
    r"<b>THE (\d{4}) SEASON(?:\x27|&#x27;)S LAST REPORT</b> — Week (\d+),")
_CTA = re.compile(
    r'<a class="btn" href="(?:join/index\.html|index\.html#watch-form)">[^<]*</a>')
_CARD = re.compile(r'(<div class="ctacard"><p>)(.*?)(</p>)', re.S)
# The kept page's closing card once the season is over: checkout is closed
# (D9), so it promises no "first report the day you join".
NEXT_SEASON = "Reports start again with next season's Week 1."


def restamp_last(page: str, *, season_over: bool = True) -> str:
    """The kept page, restamped as its season's last report: banner, closing
    card, its asks and share text. ``season_over``: checkout is closed (D9
    "over"), so the asks go to the email capture and the card promises no
    first report; otherwise (preseason) they follow the landing's flag.
    Idempotent for either mode; a page with neither banner is left alone."""
    match = _LIVE_BANNER.search(page)
    found = match and re.search(r"Week (\d+) of the (\d{4}) season", match.group(1))
    if found:
        week, season = found.groups()
    else:
        last = _LAST_BANNER.search(page)
        if not last:
            return page
        season, week = last.groups()
    banner, title, desc = last_report_text(season, week)
    if match:
        page = _LIVE_BANNER.sub(lambda _m: f'<div class="notice">{banner}</div>',
                                page, count=1)
    page = _REBUILT_LINE.sub("", page)
    cta = (f'<a class="btn" href="index.html#watch-form">{esc(SAMPLE_CTA_CLOSED)}</a>'
           if season_over else sample_cta())
    page = _CTA.sub(lambda _m: cta, page)
    card = (f"This is the {season} season&#x27;s last report, for a sample roster. "
            + esc(NEXT_SEASON if season_over else JOIN_PROMISE))
    page = _CARD.sub(lambda m: m.group(1) + card + m.group(3), page, count=1)
    return _with_share(page, title, desc)


def _with_share(page: str, title: str, desc: str) -> str:
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


def keep_last_page(out: Path, *, season_over: bool = True) -> None:
    """Restamp the published page in place, if there is one."""
    try:
        page = out.read_text(encoding="utf-8")
    except OSError:
        return
    stamped = restamp_last(page, season_over=season_over)
    if stamped != page:
        out.write_text(stamped, encoding="utf-8")


def _preseason(out: Path, week_json: Path, season: str | None,
               now: datetime) -> bool:
    """Write the preseason clock and restamp the kept page, when ``season``'s
    derived week is a Week 1 not yet due. False otherwise (or unreadable)."""
    try:
        from run.solo import current_season
        clock = preseason_clock(CACHE_DIR, season or current_season(
            CACHE_DIR, now.date()), now)
    except Exception:  # noqa: BLE001 — no clock means the build decides
        return False
    if not clock:
        return False
    keep_last_page(out, season_over=False)
    write_clock(week_json, clock)
    print(f"this week's sample was not rebuilt: {clock['season']} Week 1 is not "
          f"due until {clock['lands_on']}; the last report stays up, marked as "
          f"its season's last.")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=LIVE_OUT)
    parser.add_argument("--season")
    parser.add_argument("--week", type=int)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR,
                        help="where the public ledger lives")
    parser.add_argument("--force", action="store_true",
                        help="rebuild a week already published or kicked off; "
                             "records nothing and prints only recorded odds")
    parser.add_argument("--no-record", action="store_true",
                        help="a preview before kickoff: build the page, record nothing")
    parser.add_argument("--now", help="ISO time to judge kickoff against (tests)")
    args = parser.parse_args(argv)
    now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
           else datetime.now(timezone.utc))
    context: dict = {}
    week_json = args.out.with_name("week.json")
    try:
        report = build(season=args.season, week=args.week, context=context)
    except SeasonOver as exc:
        # D9 over: the season's last page stays, and says what it is.
        keep_last_page(args.out)
        write_clock(week_json, over_clock(read_week_json(week_json), CACHE_DIR,
                                          now.date()))
        print(f"this week's sample was not rebuilt ({exc}); the last page stays "
              f"up, marked as its season's last report.")
        return 0
    except (SoloError, Exception) as exc:  # noqa: BLE001 — keep the last page
        if not args.week and _preseason(args.out, week_json, args.season, now):
            return 0
        print(f"this week's sample was not rebuilt ({exc}); the previous page "
              f"stays up.")
        return 0
    # D9 preseason: a DERIVED Week 1 before run.solo.week_one_due is the May
    # report D8 retired, so it is never published; only the clock moves. Asked
    # only of a Week 1, so an ordinary week costs no extra schedule read.
    if (not args.week and int(report["meta"]["week"]) == 1
            and _preseason(args.out, week_json, str(report["meta"]["season"]), now)):
        return 0
    meta = report["meta"]
    from run.solo import week_has_kicked_off
    kicked_off = week_has_kicked_off(CACHE_DIR, str(meta["season"]), int(meta["week"]),
                                     now=now)
    already = recorded_this_week(read_week_json(week_json), meta)
    if kicked_off and not args.force:
        # Not a failure: the cron simply has nothing to do. Said from the
        # ledger, not assumed: "its recorded odds stand" was printed in a
        # week where nothing had been recorded at all (G24).
        held = sum(1 for s in recorded_only(copy.deepcopy(report),
                                            args.processed_dir)["lineup"]
                   if s.get("confidence") is not None)
        print(f"this week's sample was not rebuilt: week {meta['week']} has "
              f"kicked off, so the page published for it stands. The record holds "
              f"{held} of this week's odds; --force rebuilds the page showing only "
              f"those, on games not yet started, and records nothing.")
        return 0
    if already and not (args.force or args.no_record):
        print(f"this week's sample was already built and recorded before kickoff; "
              f"the published page stands. --force rebuilds it through the record "
              f"(no new odds, nothing recorded).")
        return 0
    starts = _kickoffs(str(meta["season"]), int(meta["week"]))
    first = min(starts.values()) if starts else None
    recorded = already
    if kicked_off:
        # Only odds already on the record, and none about a game underway.
        report = recorded_only(report, args.processed_dir)
        upcoming, played = kickoff_split(context.get("teams") or {}, starts, now)
        names = {str(s.get("player_id")): str(s.get("player_name"))
                 for s in [*(report.get("lineup") or []), *(report.get("bench") or [])]
                 if s.get("player_id") and s.get("player_name")}
        names.update({str(s.get("alternative_id")): str(s.get("alternative_name"))
                      for s in report.get("lineup") or []
                      if s.get("alternative_id") and s.get("alternative_name")})
        report = after_kickoff(report, upcoming, played, names)
        print("nothing recorded: the week has kicked off (--force); the page "
              "shows only odds on the record, on games not yet started")
    elif already:
        # A later build before kickoff, forced: the record made by the first
        # build stands, and the page may print nothing it does not hold.
        report = hold_closest(recorded_only(report, args.processed_dir),
                              REBUILT_CLOSEST)
        report["meta"]["thin_week_note"] = thin_week_line(
            report, context.get("missing") or [])
        print("nothing recorded: this week was recorded by its first build "
              "(--force); the page shows only those odds")
    elif args.no_record:
        print("nothing recorded: --no-record")
    else:
        try:
            added = record(report, args.processed_dir)
        except Exception as exc:  # noqa: BLE001 — publish nothing unrecorded
            print(f"this week's sample was NOT published: its odds could not be "
                  f"recorded ({exc}). The previous page stays up.", file=sys.stderr)
            return 1
        recorded = True
        print(f"recorded the sample's odds on the public ledger: {added} new "
              f"row(s) in {meta['league_id']}")
    page = render(report, TEMPLATE_PATH.read_text(encoding="utf-8"))
    page = with_thin_week(with_week_meta(page, report),
                          report["meta"].get("thin_week_note"))
    if kicked_off or already:
        # Stamped with the moment the report says it was built (the banner's
        # own clock), so the page states one build time, not two.
        try:
            built = datetime.fromisoformat(str(report["meta"].get("generated_at")))
        except ValueError:
            built = now
        built = built if built.tzinfo else built.replace(tzinfo=timezone.utc)
        page = with_thin_week(page, after_kickoff_line(report, built, first)
                              if kicked_off else rebuilt_line(report, built))
    args.out.write_text(with_via_carry(page), encoding="utf-8")
    try:
        lands_on = next_report_day(CACHE_DIR, report["meta"]["season"],
                                   report["meta"]["week"])
    except Exception:  # noqa: BLE001 — no date means the page says nothing new
        lands_on = None
    first_kickoff = first.strftime("%Y-%m-%dT%H:%M:%SZ") if first else None
    write_week_json(report, week_json, lands_on, first_kickoff,
                    recorded=recorded, after_kickoff=kicked_off)
    called = sum(1 for s in report["lineup"] if s.get("confidence") is not None)
    print(f"this week's sample -> {args.out} · {report['meta']['season']} week "
          f"{report['meta']['week']} · {called}/{len(report['lineup'])} with odds")
    return 0


def _kickoffs(season: str, week: int) -> dict[str, datetime]:
    """team -> kickoff (UTC) this week, or {} when the schedule cannot say —
    which every reader takes as "started" (a % is withheld) or "unknown"."""
    try:
        from run.saturday import kickoffs
        return {team: at.astimezone(timezone.utc)
                for team, at in kickoffs(CACHE_DIR, season, week).items()}
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    sys.exit(main())
