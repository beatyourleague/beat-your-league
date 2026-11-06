"""Tuesday's public posts, drafted from the live sample report.

Usage:
    python -m run.drops [--out content/this-week.md] [--week-json site/week.json]

The graded public record (run/posts.py) is the honest long game, and it stays
thin until October. What exists EVERY Tuesday is the sample roster's real
report (render/live_sample.py): a closest call with its odds, an if/then for
late news, and the players whose roles are growing. This turns those into
posts ready to paste — one file, overwritten each week, so the owner reads a
single page on a phone and copies what they like.

Rules, each because a post is the one place we speak without a report around it:
- **Every post says what it is.** "our sample roster" — never a subscriber's
  team (those are private) and never implied to be yours.
- **Facts and the report's own calls, no promises.** No outcome claim, no
  betting language, none of the grade-C banned words (calibrated, tested,
  proven, accurate). Pinned by tests/test_drops.py.
- **Fits the post.** Each is at most 280 characters; a post that cannot fit
  is dropped rather than truncated mid-thought.
- **The link goes in the first reply, never the post** (launch review M8).
  Each draft carries the post, a first reply holding the link, and the card
  to screenshot and attach — the real report's own card, never a mock-up.
  The post stands on its own; the link is one tap below it.
- **The call leads with the question, then a reason, then the number**
  (launch audit). It used to open with the % and a link, and the closest call
  is by construction near a coin flip — a bare "55%" explained nothing. Now it
  is the question a manager actually asks, in their words and with the slot
  ("Start Odunze or Shaheed at FLEX this week?"), ONE line of facts the
  report itself prints for that pair, and the % last.
- **Like with like** (G23, Oct 2026). The fact line once set one player's
  targets beside the other's points ("Odunze, 26 targets. Shaheed's last
  three games: 3.4, 12.3 and 4.3 points"), which compares nothing. Both
  sides now get the SAME measure: last games' points when the report prints
  them for both, else their counted usage when both have it, else the
  projection the report prints on both rows.
- **From the page, never a second build** (CRON-1). The drafts read the
  report this run's live-sample page was rendered from
  (``render.live_sample.published_report``); a run that kept the page
  (the 16:17 retry, a late backup) leaves the drafts written with it, and
  after the week's first kickoff nothing is drafted at all.
- **Only a % that is on the record** (G04). A % posted in public is a
  published probability, so the drafts are built from the live sample with
  every odds NOT in the public ledger at the same value withheld
  (`render.live_sample.recorded_only`): a post can never quote a number that
  Monday's grading will not settle.
- **An if/then that changes no seat is not news.** "If X (bench) is cleared:
  keep Y" was drafted as a plan; only plans that move somebody are drafted.
- **A Thursday starter gets his own post, for Thursday** (launch review M8).
  The one game the Saturday check is too late for: his kickoff as his row
  prints it, and the if/then the report printed for him when there is one
  that moves somebody — else the report's own line for him ("set your
  lineup before then", or "check his status" when it asks that). No
  number of any kind. Drafted with the rest on Tuesday, marked for Thursday.
- **A week with no call still says something true.** No call means no
  number, never an empty page: the rising roles, or failing those the
  workloads the report already prints — counts, no %.
- **Nothing is posted for you.** Automated posting needs paid API access this
  project's budget does not include (CLAUDE.md, Phase 5); these are drafts.
- **Two bye drafts, pure schedule fact** (G3, Oct 2026). Bye and playoff
  questions peak mid-week and are the one topic a post can answer with no %,
  nothing for Monday to grade and nothing near a bet: "NFL byes left" (every
  team still to have one, by week, off the published schedule) and "Bye
  check" (what the sample roster's own report found, ``byes_ahead``). Their
  first reply is the free bye-week planner, which sells nothing — the link
  Discords and no-links-in-replies rules tolerate best. It is the PLAIN
  planner (site review, Nov 2026): the reply says "check your own roster",
  and a planner opened on our sample roster carried that roster into its
  free-report and checkout links.
- **A reply links this week's page only when the site does** (site review,
  Nov 2026). The landing, footer.js and How it works reveal a link to
  this-week.html only in a current week with 3+ odds, a closest call, the
  card layout and a projected total (site/week.json). Week 9 of 2026 had no
  total, the site hid the page, and the drafts still sent X readers to it.
  ``this_week_hidden`` is the landing's rule, read from the clock this run's
  page build wrote; when it fails, every reply links the home page instead,
  and the file says why. A clock it cannot read fails the same way.
- **Every draft says when it goes stale** ("Good until", the first kickoff
  it is about): both players' for the call, the player and his cover for an
  if/then, the named players' for rising roles and workloads, his for the
  Thursday post. The bye drafts are about the week's schedule, so they hold
  until its last game kicks off. A kickoff it cannot place makes it the
  week's first, never later than the truth, and a draft already past its
  time is left out of the file.
- **Every link carries its own ?via= tag** (``x-wNN-<draft>``), so
  ``make stats`` counts what each post brought. Each week's this-week link
  is still its own URL (``this-week.html?w=<week>``), so X fetches a fresh
  preview card every week instead of last week's.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from render.report import SITE_ORIGIN, eastern, regret_tossup

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "content" / "this-week.md"
# The season clock the landing reads, written beside this-week.html by the
# same run's page build (render.live_sample.write_week_json).
WEEK_JSON = REPO_ROOT / "site" / "week.json"
ET = ZoneInfo("America/New_York")
LIMIT = 280
BANNED = ("calibrated", "tested", "proven", "accurate", "guarantee", "lock ",
          "bet ", "wager", "spread", "parlay")

# Name suffixes, and the particles that belong to a surname, so "Marvin
# Harrison Jr." is asked about as "Harrison" and "Amon-Ra St. Brown" as
# "St. Brown".
_SUFFIXES = frozenset({"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"})
_PARTICLES = frozenset({"st.", "st", "van", "von", "de", "del", "da", "la", "le"})


def surname(name: str) -> str:
    """The word a manager calls a player by: "Harrison" for Marvin Harrison
    Jr., "St. Brown" for Amon-Ra St. Brown."""
    parts = name.split()
    while len(parts) > 1 and parts[-1].lower() in _SUFFIXES:
        parts.pop()
    if len(parts) >= 3 and parts[-2].lower() in _PARTICLES:
        return " ".join(parts[-2:])
    return parts[-1] if parts else name


def short_names(a: str, b: str) -> tuple[str, str]:
    """How a manager says the pair: surnames — unless that makes them the
    same word (two St. Browns), when only the full names say which is which.
    ONE rule for every surface that shortens a pair: these drafts and the
    season clock's closest call (render.live_sample.closest_for_clock), which
    the landing and the weekly share card read."""
    short_a, short_b = surname(a), surname(b)
    return (a, b) if short_a.lower() == short_b.lower() else (short_a, short_b)


# The names these had before the season clock shared them.
_surname, _short_names = surname, short_names


def _listed(values: list[str]) -> str:
    return values[0] if len(values) == 1 else f"{', '.join(values[:-1])} and {values[-1]}"


def _row(report: Mapping[str, Any], player_id: str | None) -> Mapping[str, Any]:
    """The player's row, lineup first then bench ({} when he has none)."""
    for key in ("lineup", "bench"):
        for row in report.get(key) or []:
            if player_id and row.get("player_id") == player_id:
                return row
    return {}


def _games(row: Mapping[str, Any]) -> list[str]:
    return [f"{g:.1f}" for g in list(row.get("games") or [])[-3:]]


def _usage_kind(usage: str) -> str | None:
    """What a usage line counts first — "targets" or "carries" — so two lines
    are compared only when they count the same thing."""
    match = re.search(r"\d+ (targets|carries)", usage or "")
    return match.group(1) if match else None


def _projections(regret: Mapping[str, Any]) -> tuple[str, str] | None:
    for driver in regret.get("drivers") or []:
        if driver.get("label") == "proj":
            match = re.fullmatch(r"\s*([\d.]+)\s+vs\s+([\d.]+)\s*", str(driver.get("value") or ""))
            if match:
                return match.group(1), match.group(2)
    return None


def _like_for_like(report: Mapping[str, Any], regret: Mapping[str, Any],
                   a: str, b: str) -> list[str]:
    """One line of facts about BOTH players in the same unit, best first:
    their last games' points, then their counted usage when both lines count
    the same thing (quoted verbatim, so the post never says more than the
    report did), then the projection the report prints on both rows. A line
    that sets one player's targets beside the other's points compares nothing
    (G23), so a measure only one of them has is never used."""
    start, over = _row(report, regret.get("start_id")), _row(report, regret.get("over_id"))
    out: list[str] = []
    ga, gb = _games(start), _games(over)
    if len(ga) >= 2 and len(gb) >= 2:
        out.append(f"Last games, in points: {a} {_listed(ga)}; {b} {_listed(gb)}.")
    ua, ub = start.get("usage"), over.get("usage")
    if ua and ub and _usage_kind(ua) and _usage_kind(ua) == _usage_kind(ub):
        out.append(f"{a}, {ua}; {b}, {ub}.")
    projected = _projections(regret)
    if projected:
        out.append(f"{a} projects {projected[0]} points this week, {b} {projected[1]}.")
    return out


def _question(regret: Mapping[str, Any], a: str, b: str) -> str:
    """What a manager types into a group chat: both names and the slot."""
    slot = str(regret.get("slot") or "").replace("SUPER_FLEX", "superflex")
    return f"Start {a} or {b}" + (f" at {slot}" if slot else "") + " this week?"


def _call_post(report: Mapping[str, Any]) -> str | None:
    """Question, one like-for-like line of facts, then the number. None when
    no version of it fits, rather than a post cut off mid-thought."""
    regret = report.get("regret") or {}
    if regret.get("confidence") is None:
        return None
    # A toss-up is "either is fine" on the card this post links, the
    # landing's strip and the share card (render.report.regret_tossup); a post
    # saying "starts X: 52%" would make the pick the report declined to make
    # (sweep OPS-2).
    if regret_tossup(regret):
        return None
    a, b = _short_names(regret["start_name"], regret["over_name"])
    # The preregistered disclosure travels with a seeded call on every surface
    # (reports/early-season-method.md §5); a post quoting one is a surface.
    seeded = any(d.get("label") == "seeded" for d in regret.get("drivers") or [])
    tail = (f"Our sample roster's report starts {a}: "
            f"{round(regret['confidence'] * 100)}% to outscore {b}"
            + (" (last season counted in)" if seeded else "")
            + ".")
    # The best like-for-like fact that fits. A call with no fact at all is the
    # bare number this template exists to replace.
    for fact in _like_for_like(report, regret, a, b):
        text = f"{_question(regret, a, b)} {fact} {tail}"
        if len(text) <= LIMIT:
            return text
    return None


def _changes_a_seat(plan: Mapping[str, str]) -> bool:
    """Only "Move X into …" (a starter ruled out) and "Start X at …" (a bench
    player cleared AND projecting higher) put somebody different in the
    lineup. "Keep …" is a non-event, and anything unrecognised is treated as
    one: a draft that announces nothing is worse than no draft."""
    return str(plan.get("action") or "").startswith(("Move ", "Start "))


def _pivot_post(report: Mapping[str, Any]) -> str | None:
    plan = next((p for p in report.get("pivots") or [] if _changes_a_seat(p)), None)
    if plan is None:
        return None
    # The engine's action is a sentence of its own ("… If he's out, nothing
    # changes.") and the template supplies the full stop: strip it once, or
    # the post reads "changes.. That's".
    action = str(plan["action"]).strip().rstrip(".")
    action = action[:1].lower() + action[1:]
    return (f"If {plan['condition']}: {action}. That's the if/then we set on "
            f"Wednesday for our sample roster, so Sunday isn't a scramble.")


# A row's game as render prints it: "vs NE · Thu 8:15 PM ET".
_THURSDAY = re.compile(r"^(vs|@) ([A-Z]{2,3}) · Thu(?: (\d{1,2}:\d\d [AP]M) ET)?$")


def _thursday_post(report: Mapping[str, Any]) -> tuple[str, str, list[str | None]] | None:
    """(post, card, the players it is about) for the first starter whose game
    is Thursday night, or None. His if/then — a printed plan ABOUT him that
    moves somebody, and not the one Tuesday's if/then post already quotes —
    when it fits, else the report's own early-kickoff instruction for him
    (``_early_ask``)."""
    for row in report.get("lineup") or []:
        found = _THURSDAY.match(str(row.get("game") or ""))
        if not (found and row.get("player_name")):
            continue
        name, slot = row["player_name"], str(row.get("slot") or "").replace(
            "SUPER_FLEX", "SFLEX")
        where, team, clock = found.groups()
        when = f" at {clock} ET" if clock else ""
        head = f"Thursday night: {name} ({slot}, {where} {team}) kicks off{when}."
        tuesday = next((p for p in report.get("pivots") or [] if _changes_a_seat(p)), None)
        plan = next((p for p in report.get("pivots") or []
                     if p.get("about") == row.get("player_id") and _changes_a_seat(p)
                     and p is not tuesday), None)
        tries = []
        if plan is not None:
            action = str(plan["action"]).strip().rstrip(".")
            action = action[:1].lower() + action[1:]
            tries.append((f"{head} The if/then we set on Wednesday for our sample "
                          f"roster: if {plan['condition']}, {action}.",
                          "If/Then for Gameday", _plan_ids(report, plan)))
        tries.append((f"{head} Our sample roster's Wednesday report flags it: "
                      f"{_early_ask(report, name)}.", CARDS["Thursday night"], []))
        return next(((t, c, [row.get("player_id"), *ids]) for t, c, ids in tries
                     if len(t) <= LIMIT), None)
    return None


def _early_ask(report: Mapping[str, Any], name: str) -> str:
    """What the report's own early-kickoff item asks about ``name``
    (engine.solo_report.early_kickoff_items: "Thursday night: X kicks off at
    8:15 PM ET — set your lineup before then."), so the post never gives an
    instruction the report did not (sweep OPS-4: a healthy Thursday starter's
    post said "check his status", while the report said to set the lineup).
    "Check his status" only when the report asks for HIS status; an item that
    asks about somebody else in the same game, or no item at all, is the
    lock-time note."""
    lock = "set your lineup before then"
    for entry in report.get("checklist") or []:
        action = str(entry.get("action") or "")
        if not action.startswith("Thursday night:") or " — " not in action:
            continue
        who, ask = action.split(" — ", 1)
        if name not in who:
            continue
        ask = ask.strip().rstrip(".")
        if not ask.startswith("check "):
            return lock
        if ask in ("check his status before then", "check their status before then") \
                or name in ask:
            return "check his status before then"
        return lock
    return lock


def _short_rising(row: Mapping[str, Any]) -> str:
    return (f"{row['name']} ({row['team']} {row['position']}) "
            f"{row['recent']:.1f} targets + carries a game, up from {row['earlier']:.1f}")


def _rising_post(report: Mapping[str, Any], week: int) -> str | None:
    rows = list(report.get("rising") or [])
    while rows:
        text = (f"Getting more of the ball lately (Week {week}): "
                + "; ".join(_short_rising(r) for r in rows)
                + ". Box-score facts, not picks. Check who's free in your league.")
        if len(text) <= LIMIT:
            return text
        rows = rows[:-1]
    return None


def _workload_post(report: Mapping[str, Any], week: int) -> str | None:
    """The facts-only post for a week with no call and no riser: the counted
    usage the lineup rows already print, as many as fit. Counts of what
    happened, nothing about who will score."""
    rows = [r for r in report.get("lineup") or []
            if r.get("usage") and r.get("player_name")]
    while rows:
        text = (f"Who's getting the ball on our sample roster (Week {week}): "
                + "; ".join(f"{_surname(r['player_name'])}, {r['usage']}"
                            for r in rows)
                + ". Box-score counts, not picks.")
        if len(text) <= LIMIT:
            return text
        rows = rows[:-1]
    return None


# --------------------------------------------------------------------- #
# where a reply points, its tag, and when a draft goes stale
# --------------------------------------------------------------------- #

# Each draft's part of its ?via= tag, ``x-wNN-<slug>`` (run.refs.VIA_RE).
SLUGS = {"The closest call": "closest", "The if/then": "ifthen", "Rising roles": "rising",
         "Workloads": "workloads", "Thursday night": "thursday", "NFL byes left": "byes",
         "Bye check": "byecheck"}
_DAY = re.compile(r"^\d{4}-\d\d-\d\d$")


def via_tag(week: int | str, name: str) -> str:
    """The draft's ?via= tag: x (the channel these are drafted for), the
    week and the draft, so ``make stats`` counts each post on its own."""
    return f"x-w{int(week):02d}-{SLUGS[name]}"


def _tagged(url: str, tag: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}via={tag}"


def _when(value: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def this_week_hidden(clock: Mapping[str, Any], meta: Mapping[str, Any],
                     now: datetime) -> str | None:
    """None when the landing itself would link this week's page; else why
    not, in the owner's words. The landing's rule (site/index.html, and
    footer.js, How it works and the 404 page with it), read from the clock
    the same run wrote: a season week that is still current in Eastern time,
    at least three odds, a closest call, the report's card layout and a
    projected total. A clock that is missing, unreadable or about another
    week fails, like everything the landing cannot vouch for."""
    if not isinstance(clock, Mapping) or not clock:
        return "the season clock, site/week.json, can't be read"
    if (str(clock.get("season")), str(clock.get("week"))) != (
            str(meta.get("season")), str(meta.get("week"))):
        return "the season clock, site/week.json, is for another week"
    phase = clock.get("phase") or "season"
    if phase != "season":
        return f"the season clock says the season is {phase}"
    today = now.astimezone(ET).date().isoformat()
    lands, ends = clock.get("lands_on"), clock.get("week_ends")
    lands_ok = isinstance(lands, str) and bool(_DAY.match(lands))
    fresh = lands_ok and today <= lands
    week, last_week = clock.get("week"), clock.get("last_week")
    last = (isinstance(week, int) and isinstance(last_week, int) and week >= last_week)
    kick = _when(clock.get("first_kickoff")) if clock.get("first_kickoff") else None
    if last and ((lands_ok and not fresh) or (kick is not None and now >= kick)):
        return "the season's last week has kicked off"
    if not (lands_ok and isinstance(ends, str) and _DAY.match(ends)):
        return "the season clock has no dates for this week"
    if not (fresh and today <= ends):
        return "this week's games are over"
    odds = clock.get("odds")
    if not (isinstance(odds, int) and odds >= 3):
        return "it shows fewer than 3 odds"
    if not clock.get("closest_call"):
        return "it has no closest call with odds"
    if clock.get("cards") is not True:
        return "it isn't in the report's card layout"
    if clock.get("total") is False:
        return "its lineup has no projected total"
    return None


# A row's game as render prints it ("vs NE · Thu 8:15 PM ET"): the opponent's
# code finds the game in the week's kickoffs, which list both of its teams.
_OPPONENT = re.compile(r"^(?:vs|@) ([A-Z]{2,3})(?: ·|$)")
# The player a plan moves: "Move X into …" or "Start X at …".
_MOVER = re.compile(r"^(?:Move|Start) (.+?) (?:into|at) ")


def _ids_by_name(report: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in report.get("lineup") or []:
        for pid, name in ((row.get("player_id"), row.get("player_name")),
                          (row.get("alternative_id"), row.get("alternative_name"))):
            if pid and name:
                out.setdefault(str(name), str(pid))
    for row in report.get("bench") or []:
        if row.get("player_id") and row.get("name"):
            out.setdefault(str(row["name"]), str(row["player_id"]))
    return out


def _plan_ids(report: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str | None]:
    """The players an if/then is about: the one it watches and the one it
    moves (None for either it cannot name, which ``_until`` reads as unknown)."""
    found = _MOVER.match(str(plan.get("action") or ""))
    mover = _ids_by_name(report).get(found.group(1)) if found else None
    return [plan.get("about"), mover]


def _kickoff(report: Mapping[str, Any], starts: Mapping[str, datetime],
             player_id: str | None) -> datetime | None:
    found = _OPPONENT.match(str(_row(report, player_id).get("game") or ""))
    return starts.get(found.group(1)) if found else None


def _stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _until(kicks: list[datetime | None], starts: Mapping[str, datetime]) -> str | None:
    """The first of ``kicks``, or the week's first kickoff when any of them
    is unknown (never later than the truth); None with no schedule at all."""
    if kicks and all(kicks):
        return _stamp(min(kicks))      # type: ignore[type-var]
    return _stamp(min(starts.values())) if starts else None


def still_good(posts: list[dict[str, str]], now: datetime
               ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(drafts still good at ``now``, drafts past their time). A draft with no
    time stays: the run that writes the file refuses after the week's first
    kickoff anyway."""
    kept, gone = [], []
    for post in posts:
        until = _when(post["until"]) if post.get("until") else None
        (gone if until is not None and now >= until else kept).append(post)
    return kept, gone


def _week_kickoffs(season: str, week: int) -> dict[str, datetime]:
    """team -> kickoff (UTC) this week off the cached schedule, or {} when it
    cannot be read (each draft is then good until "this week's first
    kickoff", the earliest it could be)."""
    try:
        from run.saturday import kickoffs
        from run.solo import CACHE_DIR
        return dict(kickoffs(CACHE_DIR, str(season), int(week)))
    except Exception:  # noqa: BLE001 — no schedule, no time to give
        return {}


# --------------------------------------------------------------------- #
# the bye drafts (G3): schedule facts, no number to grade
# --------------------------------------------------------------------- #

# The free planner (contract C7: it lives at /byes/). Every bye draft's first
# reply links it, never the sale.
PLANNER_PATH = "byes/"
# ESPN's, Yahoo's and Sleeper's default fantasy playoffs (the weeks
# engine.solo_report.DEFAULT_PLAYOFF_WEEKS names), and the last week the
# planner checks.
PLAYOFF_WEEKS = range(15, 18)
PLANNER_LAST_WEEK = 17
PLAYOFFS_CLEAR = (" No byes in Weeks 15–17, the fantasy playoffs under "
                  "ESPN's, Yahoo's and Sleeper's defaults.")
# nflverse spells the Rams "LA"; the apps a manager reads (and the paste
# reader's engine.roster.TEAM_ALIASES) spell them "LAR". A bare "LA" reads as
# a city with two teams.
_APP_CODES = {"LA": "LAR"}


def _app_code(team: str) -> str:
    return _APP_CODES.get(team, team)


def _byes_left_post(byes: Mapping[str, int] | None, week: int) -> str | None:
    """Every team still to have its bye this week or later, by week, off the
    published schedule (engine.preseason.bye_by_team). This week's own teams
    are in it: the draft is posted on the week's Wednesday, before they sit
    out that Sunday, and leaving them off implied their bye was already
    behind them (C7-1). The playoff sentence
    only when no team is off in Weeks 15–17 — and it is the first thing to
    go when the post would not fit. None when no bye remains, or when even
    the list alone is over the limit (never cut mid-list)."""
    ahead: dict[int, list[str]] = {}
    for team, bye in (byes or {}).items():
        if isinstance(bye, int) and bye >= int(week):
            ahead.setdefault(bye, []).append(_app_code(str(team)))
    if not ahead:
        return None
    listed = " · ".join(f"Week {w}: {', '.join(sorted(set(codes)))}"
                        for w, codes in sorted(ahead.items()))
    text = f"NFL byes left this season. {listed}."
    if not any(w in PLAYOFF_WEEKS for w in ahead):
        if len(text + PLAYOFFS_CLEAR) <= LIMIT:
            return text + PLAYOFFS_CLEAR
    return text if len(text) <= LIMIT else None


# The slot words a manager reads (render.report.SLOT_DISPLAY's spellings).
_SLOT_WORDS = {"SUPER_FLEX": "SFLEX", "WRRB_FLEX": "W/R", "REC_FLEX": "W/T"}


def _bye_check_post(report: Mapping[str, Any],
                    byes: Mapping[str, int] | None = None) -> str | None:
    """What the sample roster's own report found about the byes ahead
    (``byes_ahead``, live weeks only), through Week 17: the first week a bye
    empties a starting spot, naming only the players on bye who play it.
    "Every bye covered" is said only when the report's check demonstrably ran
    — a live week (the report dates its box scores) with a readable schedule
    that still has byes before Week 17 — because an absent list is also what
    a week with no schedule looks like, and "covered" would then be a guess."""
    week = int(report["meta"]["week"])
    hits = [hit for hit in report.get("byes_ahead") or []
            if int(hit.get("week") or 0) <= PLANNER_LAST_WEEK and hit.get("slots")]
    head = "Bye check for the playoff push: our sample roster's report"
    if hits:
        hit = hits[0]
        names = list(hit.get("short") or hit.get("players") or [])
        if not names:
            return None
        who = _listed(names)
        verb = "is" if len(names) == 1 else "are"
        slots = list(dict.fromkeys(_SLOT_WORDS.get(s, s) for s in hit["slots"]))
        if slots == ["K"]:
            return (f"{head} flags Week {hit['week']}, when {who} {verb} on bye and "
                    f"nobody else on the roster can kick.")
        return (f"{head} flags Week {hit['week']}, when {who} {verb} on bye and "
                f"nobody else on the roster can start at {_listed(slots)}.")
    live = bool(report["meta"].get("box_scores_as_of"))
    ahead = any(isinstance(b, int) and week < b <= PLANNER_LAST_WEEK
                for b in (byes or {}).values())
    if live and ahead:
        return (f"{head} finds every bye from Week {week + 1} through "
                f"{PLANNER_LAST_WEEK} covered.")
    return None


def planner_reply(url: str) -> str:
    """The first reply under a bye draft: the free planner, which sells
    nothing, opened empty for the reader's own roster."""
    return f"Check your own roster's byes through Week {PLANNER_LAST_WEEK}, free, no login: {url}"


# The card on this-week.html each post describes, by the heading the report
# prints over it: the owner's screenshot to attach.
CARDS = {"The closest call": "The Week's Closest Call",
         "The if/then": "If/Then for Gameday",
         "Rising roles": "Rising Roles",
         "Workloads": "Slot by Slot",
         "Bye check": "Your Game Plan",
         "Thursday night": "Your Game Plan"}
# A card on another page, by the heading that page prints over it, and the
# page: "NFL byes left" is the planner's own bye table (contract C7).
PAGE_CARDS = {"NFL byes left": ("Every {season} NFL bye week",
                                f"the bye-week planner ({SITE_ORIGIN}/{PLANNER_PATH})")}
# When a draft is meant to go up, if not Tuesday with the rest.
WHEN = {"Thursday night": "Thursday, before his kickoff",
        "NFL byes left": "Wednesday"}


def reply_text(url: str) -> str:
    """The first reply under every post, in a week the site links this
    week's page: where the whole report is."""
    return f"The whole report, rebuilt every Wednesday for our sample roster: {url}"


def landing_reply(url: str) -> str:
    """The first reply in a week the site does not link this week's page:
    the home page, which every week can show."""
    return f"What it is, with a full sample report: {url}"


def _fits(draft: Mapping[str, str]) -> bool:
    return (len(draft["text"]) <= LIMIT
            and not any(w in draft["text"].lower() for w in BANNED))


def drafts(report: Mapping[str, Any], site: str = SITE_ORIGIN, *,
           live_page: bool = False,
           starts: Mapping[str, datetime] | None = None) -> list[dict[str, str]]:
    """The week's candidate posts from the report, in the order worth posting
    them. Each is the post itself (``text``, no link), its first reply
    (``reply``, the link, tagged ``via``), the card to screenshot and attach
    (``card``) and the moment it goes stale (``until``, ISO UTC, None with no
    schedule); a draft meant for another day says which (``when``). The
    schedule's bye drafts join them through ``with_bye_drafts``.

    ``live_page``: the landing links this week's page (``this_week_hidden``
    found nothing against it), so the replies may too; otherwise they link
    the home page. ``starts``: team -> kickoff this week
    (run.saturday.kickoffs)."""
    week = report["meta"]["week"]
    starts = dict(starts or {})
    # Its own URL each week, so X fetches this week's card, not last week's.
    page = f"{site}/this-week.html?w={week}"

    def draft(name: str, text: str, card: str, kicks: list[datetime | None]) -> dict:
        tag = via_tag(week, name)
        reply = (reply_text(_tagged(page, tag)) if live_page
                 else landing_reply(_tagged(f"{site}/", tag)))
        return {"name": name, "text": text, "reply": reply, "card": card, "via": tag,
                "until": _until(kicks, starts)}

    def kicks(ids: list[str | None]) -> list[datetime | None]:
        return [_kickoff(report, starts, pid) for pid in ids]

    regret = report.get("regret") or {}
    plan = next((p for p in report.get("pivots") or [] if _changes_a_seat(p)), None)
    call = _call_post(report)
    rising = _rising_post(report, week)
    # Only when the week has neither a call nor a riser: a facts-only post
    # rather than an empty file.
    workloads = None if (call or rising) else _workload_post(report, week)
    thursday = _thursday_post(report)
    out = [draft(name, text, CARDS[name], at) for name, text, at in (
        ("The closest call", call, kicks([regret.get("start_id"), regret.get("over_id")])),
        ("The if/then", _pivot_post(report), kicks(_plan_ids(report, plan)) if plan else []),
        # Each riser the post names, by his team's game.
        ("Rising roles", rising,
         [starts.get(str(r.get("team") or "")) for r in report.get("rising") or []
          if rising and _short_rising(r) in rising]),
        ("Workloads", workloads,
         kicks([r.get("player_id") for r in report.get("lineup") or []
                if workloads and r.get("usage") and r.get("player_name")
                and f"{_surname(r['player_name'])}, {r['usage']}" in workloads])),
    ) if text]
    if thursday:
        text, card, ids = thursday
        out.append({**draft("Thursday night", text, card, kicks(ids)),
                    "when": WHEN["Thursday night"]})
    return [d for d in out if _fits(d)]


def bye_drafts(report: Mapping[str, Any], byes: Mapping[str, int] | None,
               site: str = SITE_ORIGIN, *,
               starts: Mapping[str, datetime] | None = None) -> list[dict[str, str]]:
    """The two schedule drafts (G3): "NFL byes left" from the season's bye
    table (team -> week, engine.preseason.bye_by_team) and "Bye check" from
    the report's own ``byes_ahead``. Their first reply is the free planner,
    plain and tagged; neither carries a number to grade. No table, no "NFL
    byes left" and no "every bye covered". Both are about the week's
    schedule, so both are good until its last game kicks off."""
    meta = report["meta"]
    starts = dict(starts or {})
    last = _stamp(max(starts.values())) if starts else None
    out = []
    for name, text in (("NFL byes left", _byes_left_post(byes, meta["week"])),
                       ("Bye check", _bye_check_post(report, byes))):
        if not text:
            continue
        tag = via_tag(meta["week"], name)
        draft = {"name": name, "text": text, "via": tag, "until": last,
                 "reply": planner_reply(_tagged(f"{site}/{PLANNER_PATH}", tag))}
        if name in PAGE_CARDS:
            card, page = PAGE_CARDS[name]
            draft.update(card=card.format(season=meta.get("season", "")), card_page=page)
        else:
            draft["card"] = CARDS[name]
        if name in WHEN:
            draft["when"] = WHEN[name]
        out.append(draft)
    return [d for d in out if _fits(d)]


def with_bye_drafts(posts: list[dict[str, str]], report: Mapping[str, Any],
                    byes: Mapping[str, int] | None,
                    site: str = SITE_ORIGIN, *,
                    starts: Mapping[str, datetime] | None = None) -> list[dict[str, str]]:
    """``posts`` with the bye drafts placed after the report's own call,
    if/then and rising roles — before the facts-only fallback and the
    Thursday post."""
    lead = ("The closest call", "The if/then", "Rising roles")
    at = max((i + 1 for i, post in enumerate(posts) if post["name"] in lead), default=0)
    return posts[:at] + bye_drafts(report, byes, site, starts=starts) + posts[at:]


def _good_until(post: Mapping[str, Any]) -> str:
    until = _when(post["until"]) if post.get("until") else None
    return f"Good until {eastern(until)}." if until else "Good until this week's first kickoff."


def render(report: Mapping[str, Any], posts: list[dict[str, str]], *,
           hidden: str | None = None, gone: Sequence[Mapping[str, Any]] = ()) -> str:
    """The drafts file. ``hidden``: why the replies link the home page
    (``this_week_hidden``); ``gone``: drafts left out, past their time."""
    meta = report["meta"]
    week = int(meta["week"])
    lines = [f"# Week {meta['week']} posts — drafts, not posted",
             "",
             "Built from the live sample roster's report "
             f"({SITE_ORIGIN}/this-week.html) and the NFL schedule. Read before "
             "posting: each post about the report says it's a sample roster, "
             "none makes a promise about results or a betting claim. Nothing "
             "here posts itself.", "",
             "How to post one: the post goes up with no link in it. Attach a "
             "phone screenshot of the card named under it, from this week's "
             "page unless it names another — the real page, never a mock-up. "
             "Then put the first reply under your own post: that is where the "
             "link goes.", "",
             "Each draft says how long it's good for. Don't post one after that. "
             f"Each link carries its own tag (x-w{week:02d}-…), so `make stats` "
             "counts what each post brought. Posting one somewhere other than X? "
             f"Change the x at the front, like discord-w{week:02d}-byes.", ""]
    if hidden:
        lines += ["This week's page isn't linked. The site doesn't show it this week "
                  f"({hidden}), so each reply links the home page.", ""]
    if gone:
        lines += [f"Left out, past their time: {', '.join(p['name'] for p in gone)}.", ""]
    if not posts and gone:
        lines.append("_Nothing left to post this week: every draft is past its time._")
    elif not posts:
        lines.append("_Nothing to draft this week: the sample report had no "
                     "closest call, if/then, rising role, bye, workload or "
                     "Thursday starter to quote._")
    for i, post in enumerate(posts, 1):
        lines += [f"## {i}. {post['name']} ({len(post['text'])}/{LIMIT})", ""]
        when = f"Post it: {post['when']}. " if post.get("when") else ""
        lines += [when + _good_until(post), ""]
        page = f", from {post['card_page']}" if post.get("card_page") else ""
        lines += [post["text"], "",
                  f"Attach: a screenshot of the \"{post['card']}\" card{page}.", "",
                  f"First reply: {post['reply']}", ""]
    return "\n".join(lines) + "\n"


def _season_byes(season: str) -> dict[str, int] | None:
    """team -> bye week off the cached schedule, or None when it cannot be
    read (then no bye-table draft is made, never one built on a guess)."""
    try:
        from engine.preseason import bye_by_team
        from run.solo import CACHE_DIR
        return bye_by_team(CACHE_DIR, season) or None
    except Exception:  # noqa: BLE001 — no table means no bye-table draft
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--processed-dir", type=Path, default=None,
                        help="where the public ledger lives (default: data/processed)")
    parser.add_argument("--week-json", type=Path, default=WEEK_JSON,
                        help="the season clock the landing reads (default: site/week.json)")
    args = parser.parse_args(argv)
    try:
        from render.live_sample import (CACHE_DIR, PROCESSED_DIR, published_report,
                                        read_week_json, recorded_only)
        from run.solo import week_has_kicked_off
        processed = args.processed_dir or PROCESSED_DIR
        # Drafted from the report THIS run's page was published from, never a
        # second build (CRON-1): on the 16:17 retry, a late backup or a hand
        # re-run the page keeps its first build, and a fresh build had moved
        # — the recorded closest call withheld, a projection 0.1 off the
        # page's. No page published in this run: the drafts written with the
        # page stand.
        published = published_report(processed)
        if published is None:
            print("this week's drafts were not rebuilt: this run published no sample "
                  "page, so the drafts written with the published page stay.")
            return 0
        meta = published["meta"]
        if week_has_kicked_off(CACHE_DIR, str(meta["season"]), int(meta["week"])):
            print(f"this week's drafts were not rebuilt: week {meta['week']} has kicked "
                  f"off, and a draft now would be about games underway; the previous "
                  f"file stays.")
            return 0
        # Every % the ledger does not hold at the same value is withheld
        # before a single post is drafted (G04): the posts are public, so a
        # number in one must be a number Monday's grading will settle.
        report = recorded_only(published, processed)
    except Exception as exc:  # noqa: BLE001 — keep last week's drafts
        print(f"this week's drafts were not rebuilt ({exc}); the previous file "
              f"stays.")
        return 0
    now = datetime.now(timezone.utc)
    meta = report["meta"]
    # The landing's own rule, on the clock the page build of this run wrote
    # beside the page: link this week's page only when the site does.
    hidden = this_week_hidden(read_week_json(args.week_json), meta, now)
    starts = _week_kickoffs(str(meta["season"]), int(meta["week"]))
    posts = with_bye_drafts(drafts(report, live_page=hidden is None, starts=starts),
                            report, _season_byes(str(meta["season"])), starts=starts)
    posts, gone = still_good(posts, now)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report, posts, hidden=hidden, gone=gone), encoding="utf-8")
    print(f"{len(posts)} draft(s) -> {args.out}"
          + (f"; the replies link the home page ({hidden})" if hidden else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
