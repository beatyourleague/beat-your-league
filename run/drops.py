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
- **Fits the post.** Each is at most 280 characters, links included; a post
  that cannot fit is dropped rather than truncated mid-thought.
- **The call leads with the question, then a reason, then the number**
  (launch audit). It used to open with the % and a link, and the closest call
  is by construction near a coin flip — a bare "55%" explained nothing. Now it
  is the question a manager actually asks ("LaPorta or Odunze this week?"),
  ONE line of facts the report itself prints for that pair, and the % last.
- **An if/then that changes no seat is not news.** "If X (bench) is cleared:
  keep Y" was drafted as a plan; only plans that move somebody are drafted.
- **A week with no call still says something true.** No call means no
  number, never an empty page: the rising roles, or failing those the
  workloads the report already prints — counts, no %.
- **Nothing is posted for you.** Automated posting needs paid API access this
  project's budget does not include (CLAUDE.md, Phase 5); these are drafts.
"""

from __future__ import annotations

import argparse
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


def _surname(name: str) -> str:
    parts = name.split()
    while len(parts) > 1 and parts[-1].lower() in _SUFFIXES:
        parts.pop()
    if len(parts) >= 3 and parts[-2].lower() in _PARTICLES:
        return " ".join(parts[-2:])
    return parts[-1] if parts else name


def _short_names(a: str, b: str) -> tuple[str, str]:
    """How a manager says the pair: surnames — unless that makes them the
    same word (two St. Browns), when only the full names say which is which."""
    short_a, short_b = _surname(a), _surname(b)
    return (a, b) if short_a.lower() == short_b.lower() else (short_a, short_b)


def _games_clause(short: str, games: list[float]) -> str | None:
    shown = [f"{g:.1f}" for g in games[-3:]]
    if not shown:
        return None
    label = {1: "only game", 2: "last two games"}.get(len(shown), "last three games")
    listed = (shown[0] if len(shown) == 1
              else f"{', '.join(shown[:-1])} and {shown[-1]}")
    return f"{short}'s {label}: {listed} points."


def _fact_clauses(report: Mapping[str, Any], player_id: str | None,
                  short: str) -> list[str]:
    """What the report prints about one player, best first: the counted usage
    on his lineup row (quoted verbatim, so the post can never say more than the
    report did), then his recent games from the bench block."""
    out: list[str] = []
    for row in report.get("lineup") or []:
        if player_id and row.get("player_id") == player_id and row.get("usage"):
            out.append(f"{short}, {row['usage']}.")
    for row in report.get("bench") or []:
        if player_id and row.get("player_id") == player_id:
            clause = _games_clause(short, list(row.get("games") or []))
            if clause:
                out.append(clause)
    return out


def _call_post(report: Mapping[str, Any], url: str) -> str | None:
    """Question, one line of facts, then the number. None when no version of
    it fits, rather than a post cut off mid-thought."""
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
            + f". Full report: {url}")
    clauses = (_fact_clauses(report, regret.get("start_id"), a)[:1]
               + _fact_clauses(report, regret.get("over_id"), b)[:1])
    # Both players' facts if they fit; failing that, one of them. A call with
    # no fact at all is the bare number this template exists to replace.
    for chosen in (clauses, clauses[1:], clauses[:1]):
        if not chosen:
            continue
        text = f"{a} or {b} this week? {' '.join(chosen)} {tail}"
        if len(text) <= LIMIT:
            return text
    return None


def _changes_a_seat(plan: Mapping[str, str]) -> bool:
    """Only "Move X into …" (a starter ruled out) and "Start X at …" (a bench
    player cleared AND projecting higher) put somebody different in the
    lineup. "Keep …" is a non-event, and anything unrecognised is treated as
    one: a draft that announces nothing is worse than no draft."""
    return str(plan.get("action") or "").startswith(("Move ", "Start "))


def _pivot_post(report: Mapping[str, Any], url: str) -> str | None:
    plan = next((p for p in report.get("pivots") or [] if _changes_a_seat(p)), None)
    if plan is None:
        return None
    # The engine's action is a sentence of its own ("… If he's out, nothing
    # changes.") and the template supplies the full stop: strip it once, or
    # the post reads "changes.. That's".
    action = str(plan["action"]).strip().rstrip(".")
    action = action[:1].lower() + action[1:]
    return (f"If {plan['condition']}: {action}. That's the if/then we set on "
            f"Tuesday for our sample roster, so Sunday isn't a scramble. {url}")


def _short_rising(row: Mapping[str, Any]) -> str:
    return (f"{row['name']} ({row['team']} {row['position']}) "
            f"{row['recent']:.1f} touches a game, up from {row['earlier']:.1f}")


def _rising_post(report: Mapping[str, Any], week: int, url: str) -> str | None:
    rows = list(report.get("rising") or [])
    while rows:
        text = (f"Getting more of the ball lately (Week {week}): "
                + "; ".join(_short_rising(r) for r in rows)
                + f". Box-score facts, not picks. Check who's free in your "
                  f"league. {url}")
        if len(text) <= LIMIT:
            return text
        rows = rows[:-1]
    return None


def _workload_post(report: Mapping[str, Any], week: int, url: str) -> str | None:
    """The facts-only post for a week with no call and no riser: the counted
    usage the lineup rows already print, as many as fit. Counts of what
    happened, nothing about who will score."""
    rows = [r for r in report.get("lineup") or []
            if r.get("usage") and r.get("player_name")]
    while rows:
        text = (f"Who's getting the ball on our sample roster (Week {week}): "
                + "; ".join(f"{_surname(r['player_name'])}, {r['usage']}"
                            for r in rows)
                + f". Box-score counts, not picks. {url}")
        if len(text) <= LIMIT:
            return text
        rows = rows[:-1]
    return None


def drafts(report: Mapping[str, Any], site: str = SITE_ORIGIN) -> list[dict[str, str]]:
    """The week's candidate posts, in the order worth posting them."""
    week = report["meta"]["week"]
    url = f"{site}/this-week.html"
    call = _call_post(report, url)
    rising = _rising_post(report, week, url)
    out = [{"name": name, "text": text} for name, text in (
        ("The closest call", call),
        ("The if/then", _pivot_post(report, url)),
        ("Rising roles", rising),
        # Only when the week has neither a call nor a riser: a facts-only
        # post rather than an empty file.
        ("Workloads", None if (call or rising)
         else _workload_post(report, week, url)),
    ) if text]
    return [d for d in out if len(d["text"]) <= LIMIT
            and not any(w in d["text"].lower() for w in BANNED)]


def render(report: Mapping[str, Any], posts: list[dict[str, str]]) -> str:
    meta = report["meta"]
    lines = [f"# Week {meta['week']} posts — drafts, not posted",
             "",
             "Built from the live sample roster's report "
             f"({SITE_ORIGIN}/this-week.html). Read before posting: each says "
             "it's a sample roster, makes no promise about results and no "
             "betting claim. Nothing here posts itself.", ""]
    if not posts:
        lines.append("_Nothing to draft this week: the sample report had no "
                     "closest call, if/then, rising role or workload to quote._")
    for i, post in enumerate(posts, 1):
        lines += [f"## {i}. {post['name']} ({len(post['text'])}/{LIMIT})", "",
                  post["text"], ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    try:
        from render.live_sample import build
        report = build()
    except Exception as exc:  # noqa: BLE001 — keep last week's drafts
        print(f"this week's drafts were not rebuilt ({exc}); the previous file "
              f"stays.")
        return 0
    posts = drafts(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report, posts), encoding="utf-8")
    print(f"{len(posts)} draft(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
