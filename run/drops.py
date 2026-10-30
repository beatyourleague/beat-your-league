"""Tuesday's public posts, drafted from the live sample report.

Usage:
    python -m run.drops [--out content/this-week.md]

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
  that moves somebody — else the report's own "check his status" line. No
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
  Discords and no-links-in-replies rules tolerate best.
- **Each week's link is its own URL** (``this-week.html?w=<week>``), so X
  fetches a fresh preview card every week instead of last week's.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from render.report import SITE_ORIGIN

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "content" / "this-week.md"
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
            f"Tuesday for our sample roster, so Sunday isn't a scramble.")


# A row's game as render prints it: "vs NE · Thu 8:15 PM ET".
_THURSDAY = re.compile(r"^(vs|@) ([A-Z]{2,3}) · Thu(?: (\d{1,2}:\d\d [AP]M) ET)?$")


def _thursday_post(report: Mapping[str, Any]) -> tuple[str, str] | None:
    """(post, card) for the first starter whose game is Thursday night, or
    None. His if/then — a printed plan ABOUT him that moves somebody, and not
    the one Tuesday's if/then post already quotes — when it fits, else the
    report's own instruction to check his status before kickoff."""
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
            tries.append((f"{head} The if/then we set on Tuesday for our sample "
                          f"roster: if {plan['condition']}, {action}.",
                          "If/Then for Gameday"))
        tries.append((f"{head} Our sample roster's Tuesday report flags it: check "
                      f"his status before then.", CARDS["Thursday night"]))
        return next(((t, c) for t, c in tries if len(t) <= LIMIT), None)
    return None


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
    nothing."""
    return f"Check your own roster's byes through Week {PLANNER_LAST_WEEK}, free, no login: {url}"


def sample_planner_url(site: str = SITE_ORIGIN) -> str:
    """The planner opened on the sample roster (the same v4 roster code a
    signup carries), so "check it yourself" starts from the roster the post
    is about."""
    from render.live_sample import LIVE_ROSTER
    from render.sample import SLOTS
    from run.refs import encode_roster
    ref = encode_roster("season", "ppr", SLOTS, LIVE_ROSTER, 12)
    return f"{site}/{PLANNER_PATH}?ref={ref}"


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
    """The first reply under every post: where the whole report is."""
    return f"The whole report, rebuilt every Tuesday for our sample roster: {url}"


def _fits(draft: Mapping[str, str]) -> bool:
    return (len(draft["text"]) <= LIMIT
            and not any(w in draft["text"].lower() for w in BANNED))


def drafts(report: Mapping[str, Any], site: str = SITE_ORIGIN) -> list[dict[str, str]]:
    """The week's candidate posts from the report, in the order worth posting
    them. Each is the post itself (``text``, no link), its first reply
    (``reply``, the link) and the card to screenshot and attach (``card``); a
    draft meant for another day says which (``when``). The schedule's bye
    drafts join them through ``with_bye_drafts``."""
    week = report["meta"]["week"]
    # Its own URL each week, so X fetches this week's card, not last week's.
    url = f"{site}/this-week.html?w={week}"
    call = _call_post(report)
    rising = _rising_post(report, week)
    thursday = _thursday_post(report)
    out = [{"name": name, "text": text, "reply": reply_text(url), "card": CARDS[name]}
           for name, text in (
        ("The closest call", call),
        ("The if/then", _pivot_post(report)),
        ("Rising roles", rising),
        # Only when the week has neither a call nor a riser: a facts-only
        # post rather than an empty file.
        ("Workloads", None if (call or rising)
         else _workload_post(report, week)),
    ) if text]
    if thursday:
        out.append({"name": "Thursday night", "text": thursday[0], "reply": reply_text(url),
                    "card": thursday[1], "when": WHEN["Thursday night"]})
    return [d for d in out if _fits(d)]


def bye_drafts(report: Mapping[str, Any], byes: Mapping[str, int] | None,
               site: str = SITE_ORIGIN) -> list[dict[str, str]]:
    """The two schedule drafts (G3): "NFL byes left" from the season's bye
    table (team -> week, engine.preseason.bye_by_team) and "Bye check" from
    the report's own ``byes_ahead``. Their first reply is the free planner;
    neither carries a number to grade. No table, no "NFL byes left" and no
    "every bye covered"."""
    meta = report["meta"]
    out = []
    for name, text, link in (
            ("NFL byes left", _byes_left_post(byes, meta["week"]),
             lambda: f"{site}/{PLANNER_PATH}"),
            ("Bye check", _bye_check_post(report, byes),
             lambda: sample_planner_url(site))):
        if not text:
            continue
        draft = {"name": name, "text": text, "reply": planner_reply(link())}
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
                    site: str = SITE_ORIGIN) -> list[dict[str, str]]:
    """``posts`` with the bye drafts placed after the report's own call,
    if/then and rising roles — before the facts-only fallback and the
    Thursday post."""
    lead = ("The closest call", "The if/then", "Rising roles")
    at = max((i + 1 for i, post in enumerate(posts) if post["name"] in lead), default=0)
    return posts[:at] + bye_drafts(report, byes, site) + posts[at:]


def render(report: Mapping[str, Any], posts: list[dict[str, str]]) -> str:
    meta = report["meta"]
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
             "link goes.", ""]
    if not posts:
        lines.append("_Nothing to draft this week: the sample report had no "
                     "closest call, if/then, rising role, bye, workload or "
                     "Thursday starter to quote._")
    for i, post in enumerate(posts, 1):
        lines += [f"## {i}. {post['name']} ({len(post['text'])}/{LIMIT})", ""]
        if post.get("when"):
            lines += [f"Post it: {post['when']}.", ""]
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
    args = parser.parse_args(argv)
    try:
        from render.live_sample import (CACHE_DIR, PROCESSED_DIR, published_report,
                                        recorded_only)
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
    posts = with_bye_drafts(drafts(report), report,
                            _season_byes(str(report["meta"]["season"])))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report, posts), encoding="utf-8")
    print(f"{len(posts)} draft(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
