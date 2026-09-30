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


def _short_rising(row: Mapping[str, Any]) -> str:
    return (f"{row['name']} ({row['team']} {row['position']}) "
            f"{row['recent']:.1f} touches a game, up from {row['earlier']:.1f}")


def drafts(report: Mapping[str, Any], site: str = SITE_ORIGIN) -> list[dict[str, str]]:
    """The week's candidate posts, in the order worth posting them."""
    meta = report["meta"]
    week = meta["week"]
    url = f"{site}/this-week.html"
    out: list[dict[str, str]] = []

    regret = report.get("regret") or {}
    if regret.get("confidence") is not None:
        proj = next((d["value"] for d in (regret.get("drivers") or [])
                     if d.get("label") == "proj"), "")
        out.append({"name": "The closest call", "text": (
            f"Week {week}'s closest call on our sample roster: start "
            f"{regret['start_name']} over {regret['over_name']}, "
            f"{round(regret['confidence'] * 100)}%"
            + (f" (projected {proj})" if proj else "") + ". Every close call in "
            f"your report gets a side and a number. Full report: {url}")})

    plans = report.get("pivots") or []
    if plans:
        plan = plans[0]
        out.append({"name": "The if/then", "text": (
            f"If {plan['condition']}: {plan['action']}. That's the if/then "
            f"we set on Tuesday for our sample roster, so Sunday isn't a "
            f"scramble. {url}")})

    rows = list(report.get("rising") or [])
    while rows:
        text = (f"Getting more of the ball lately (Week {week}): "
                + "; ".join(_short_rising(r) for r in rows)
                + f". Box-score facts, not picks. Check who's free in your "
                  f"league. {url}")
        if len(text) <= LIMIT:
            out.append({"name": "Rising roles", "text": text})
            break
        rows = rows[:-1]

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
                     "closest call, if/then or rising role to quote._")
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
