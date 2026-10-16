"""The public content drafts, rebuilt on the roster product's own record.

Usage:
    python -m run.posts receipts     # Monday: what the record settled
    python -m run.posts coinflip     # Friday: the closest call we published
    python -m run.posts replykit     # daily: numbers you can defend in a reply
    python -m run.posts all

``run/content.py`` drafted these from a Sleeper league — its own history, its
transaction log, its manager behaviour — so it produces nothing for the
product that ships. This module is the port, and porting forced two decisions
worth stating plainly rather than discovering later.

**ONE SOURCE: THE PUBLIC LEDGER.** In the league product the drafts drew on
the owner's own team. There is no owner team here — there are subscribers,
and their files are private. A public post quoting a subscriber's lineup
would publish the roster they paid us to keep, so nothing here reads a
subscriber report, a registry row, or anything under `reports/subscribers/`.
The ledger is already the anonymised view (`engine.ledger.public_entries`:
NFL players and results, no league, no roster, no address) and it is the only
input. Pinned by `tests/test_posts.py`, which walks imports rather than
grepping.

**HYPE WEDNESDAY IS GONE, not ported.** It ranked waiver chases out of the
league's transaction log. The product reads no league, so there is no log, no
FAAB, no chase — and RULE W1 already refused to trust the budget figure even
when we had one. Drafting it from anything else would be inventing the number
the post exists to report. Two formats survive honestly; the third does not,
and pretending otherwise would put a fabricated column in the one place the
brand is "we publish what we can defend".

**ONE CALL AT A TIME, NEVER A TALLY** (GTM-4, AFTER-6, Oct 2026). The
selling rule is "sell the win, keep the record off the pitch": no win-loss
totals, no hit rates, no "we went 7-3" anywhere a stranger reads. Principle 2
is kept by the public record itself (the ledger page, graded every Monday,
misses included); these drafts may quote a recorded call one at a time, each
with the number it was published at and the box score that settled it, and
never sum them. Whether the graded record is ever marketed socially is an
owner decision (LAUNCH.md section 10), not a template default.

**Nothing here grades.** `run/monday.py` owns settlement (RULE L1-L4, the
box-scores-in finality rule, the shrink guard). These drafts READ what it
settled. A second grader is how a public record starts answering the same
question two ways.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.ledger import GRADED, LedgerCall, load_all_ledgers, scoring_of
from render.cards import write_receipt_cards

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
CONTENT_DIR = REPO_ROOT / "content"
FOOT = "LLM tokens used to draft this: 0 (deterministic templating)."


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def ours(processed_dir: Path) -> list[LedgerCall]:
    """Every call in THIS product's record, settled or not.

    Scoped to the `typed-{scoring}-{size}-{season}` stores, which is what a
    roster subscription writes. The processed directory also holds Sleeper-era
    stores keyed by league id, and `run/monday.py` already grades only the
    typed ones — so without the same scope here a retired product's calls
    would appear in a public post as this product's receipts, with an empty
    scoring column where the preset should be.
    """
    return [call for call in load_all_ledgers(processed_dir)
            if scoring_of(call.league_id) is not None]


def settled(processed_dir: Path) -> list[LedgerCall]:
    """Every call the Monday run has settled.

    Pending calls are excluded here rather than filtered by each caller: a
    draft that quotes an ungraded call is a claim about a game that has not
    finished, which is the one thing the ledger exists to prevent.
    """
    return [call for call in ours(processed_dir) if call.status == GRADED]


def latest_week(calls: list[LedgerCall]) -> tuple[str, int] | None:
    """The most recent (season, week) with settled calls, or None."""
    weeks = {(call.season, call.week) for call in calls}
    return max(weeks) if weeks else None


# --------------------------------------------------------------------- #
# Receipts Monday
# --------------------------------------------------------------------- #

def _settled_line(call: LedgerCall) -> str:
    got = "" if call.pick_points is None else (
        f" — {call.pick_points:.1f} to {call.over_points:.1f}")
    return (f"- **{call.outcome.upper()}** · {call.pick_name} over "
            f"{call.over_name} at {call.confidence:.0%} ({call.slot}, "
            f"{scoring_of(call.league_id)}){got}")


def _one_call_post(call: LedgerCall) -> str:
    """One recorded call, as a post: the call as it was published and the box
    score that settled it. Never a tally (GTM-4)."""
    got = ("" if call.pick_points is None else
           f" {call.pick_name} {call.pick_points:.1f}, {call.over_name} "
           f"{call.over_points:.1f}.")
    return (f"> Week {call.week}, recorded before kickoff: {call.pick_name} over "
            f"{call.over_name}, {call.confidence:.0%}.{got}")


def receipts_monday(processed_dir: Path = PROCESSED_DIR,
                    out_dir: Path = CONTENT_DIR,
                    week: tuple[str, int] | None = None) -> tuple[Path, str]:
    """What the record settled, one call at a time — from the ledger only.

    The owner's notes list every settled call, misses included, so the
    choice of what to post is made knowing all of it; each draft quotes ONE
    call. No line sums them: a win-loss total or a hit rate is the record on
    the pitch, which the selling rule keeps off every public surface."""
    calls = settled(processed_dir)
    target = week or latest_week(calls)
    week_calls = ([c for c in calls
                   if (c.season, c.week) == target] if target else [])

    lines = [
        "# Receipts Monday — draft"
        + (f" · {target[0]} week {target[1]}" if target else ""),
        "",
        "> Human edits before posting. Every number is read from the public",
        "> ledger — the calls we actually sent, graded against real box scores.",
        "> Nothing here comes from a subscriber's report.",
        "",
    ]
    if not week_calls:
        lines += [
            "## Nothing settled this week",
            "",
            "Either no call cleared the bar (an honest quiet week) or the games",
            "aren't final yet. Nothing to post today.",
            "",
            "---",
            FOOT,
        ]
        return (_write(out_dir / "receipts-monday.md", "\n".join(lines) + "\n"),
                "nothing settled")

    cards = write_receipt_cards(week_calls, out_dir / "cards")
    lines += [
        f"## Week {target[1]}, as settled (your notes, not a post)",
        "",
        *[_settled_line(call) for call in week_calls],
        "",
        "Every call is on the public record either way. Post one at a time,",
        "never a total or a rate.",
        "",
        "Drafts, one per call:",
        "",
    ]
    for call in week_calls:
        lines += [_one_call_post(call), ""]
    lines += [
        f"Cards rendered: {len(cards)}, one per call.",
        "",
        "---",
        FOOT,
    ]
    verdict = f"{len(week_calls)} call(s) week {target[1]}"
    return (_write(out_dir / "receipts-monday.md", "\n".join(lines) + "\n"),
            verdict)


# --------------------------------------------------------------------- #
# Coin-Flip Friday
# --------------------------------------------------------------------- #

def coinflip_friday(processed_dir: Path = PROCESSED_DIR,
                    out_dir: Path = CONTENT_DIR) -> tuple[Path, str]:
    """The closest call we PUBLISHED, quoted from the ledger.

    Unchanged in spirit from the league version, and for the same reason: the
    post's promise is only true if the number was recorded when the report
    shipped. A freshly computed number would be a claim nobody received.
    """
    regrets = [c for c in ours(processed_dir) if c.is_regret]
    target = max({(c.season, c.week) for c in regrets}, default=None)
    week_calls = [c for c in regrets if (c.season, c.week) == target]
    # The closest call is the one nearest a coin flip.
    call = min(week_calls, key=lambda c: abs(c.confidence - 0.5)) if week_calls else None

    lines = [
        "# Coin-Flip Friday — draft"
        + (f" · {target[0]} week {target[1]}" if target else ""),
        "",
        "> Human edits before posting. The call below is read from the LEDGER —",
        "> the number recorded when the report shipped, graded Monday like",
        "> everything else. Never a freshly computed, unrecorded number.",
        "",
    ]
    if call is None:
        lines += [
            "## No publishable coin flip this week",
            "",
            "No close call was recorded — either nothing cleared the bar, or no",
            "report has shipped yet this week.",
            "",
            "Honest post option (the pass IS the brand):",
            "",
            "> Coin-Flip Friday, except: not one close call cleared our bar this",
            "> week, so we're not publishing one. A number we can't stand behind",
            "> is a vibe, and vibes are free elsewhere. Back next week.",
            "",
            "---",
            FOOT,
        ]
        return (_write(out_dir / "coinflip-friday.md", "\n".join(lines) + "\n"),
                "gated")

    lines += [
        f"## As recorded: {call.pick_name} over {call.over_name} "
        f"({call.confidence:.0%})",
        "",
        f"- Slot {call.slot} · {scoring_of(call.league_id)} scoring · recorded "
        f"{call.recorded_at}",
        "- Definition (cite if asked): the odds this start outscores that",
        "  specific bench alternative. Graded Monday either way.",
        "",
        "Draft:",
        "",
        "> Coin-Flip Friday. The closest call we published this week:",
        f"> **{call.pick_name} over {call.over_name}, {call.confidence:.0%}.**",
        "> Recorded when it shipped; settled Monday against the box score.",
        "",
        "---",
        FOOT,
    ]
    return (_write(out_dir / "coinflip-friday.md", "\n".join(lines) + "\n"),
            f"{call.confidence:.0%} call drafted from the ledger")


# --------------------------------------------------------------------- #
# The daily reply kit
# --------------------------------------------------------------------- #

def reply_kit(processed_dir: Path = PROCESSED_DIR,
              out_dir: Path = CONTENT_DIR,
              kit_date: str | None = None) -> tuple[Path, str]:
    """The day's defensible numbers, all of them from the public record.

    Thinner than the league version by design: that one drew on fragility,
    the waiver log and a manager's behavioural profile, none of which exist
    without a league — and the slot calls it quoted came from the OWNER's own
    report, which here would be a subscriber's private file. What remains is
    what we can say in public without borrowing anyone's roster.
    """
    stamp = kit_date or datetime.now(timezone.utc).date().isoformat()
    calls = settled(processed_dir)
    items: list[tuple[str, str]] = []
    # No "our record: 7-3" item. A tally is the record on the pitch (GTM-4);
    # a reply quotes one recorded call, with the box score that settled it.
    target = latest_week(calls)
    if target:
        week_calls = [c for c in calls if (c.season, c.week) == target]
        for call in sorted(week_calls,
                           key=lambda c: abs(c.confidence - 0.5))[:5]:
            got = ("" if call.pick_points is None else
                   f" ({call.pick_points:.1f} to {call.over_points:.1f})")
            items.append((
                f"{call.pick_name} over {call.over_name} at "
                f"{call.confidence:.0%} — {call.outcome}{got}",
                f"week {call.week} call, recorded before kickoff and graded "
                f"after; {scoring_of(call.league_id)} scoring",
            ))

    lines = [
        f"# Reply kit — {stamp}",
        "",
        "> The day's defensible numbers, one line of reasoning each. Selection",
        "> is the human's job; never link the product in replies.",
        "> Every number here is from the PUBLIC record — no subscriber's report",
        "> is ever quoted, no number appears before it has been graded, and no",
        "> reply sums the record: one call at a time.",
        "",
    ]
    for number, why in items:
        lines += [
            f"## {number}",
            f"- Why it's true: {why}",
            f"- Reply template: \"We had {number}, recorded before kickoff.\"",
            "",
        ]
    if not items:
        lines += [
            "No graded calls on the record yet, so there is nothing here to",
            "defend in public. The first calls settle in week 2 for the scoring",
            "we have measured and week 4 for the rest — until then, reply with",
            "questions rather than numbers.",
            "",
        ]
    elif len(items) < 6:
        lines += [
            f"> Only {len(items)} defensible number(s) today — the record is",
            "> young and the gate held the rest back. Fewer, harder numbers beat",
            "> filler; do not pad this list.",
            "",
        ]
    lines += ["---", FOOT]
    return (_write(out_dir / f"reply-kit-{stamp}.md", "\n".join(lines) + "\n"),
            f"{len(items)} number(s)")


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("what", choices=["receipts", "coinflip", "replykit",
                                         "all"])
    parser.add_argument("--processed", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--out", type=Path, default=CONTENT_DIR)
    parser.add_argument("--date", help="ISO date for the reply kit")
    args = parser.parse_args(argv)

    jobs = {
        "receipts": lambda: receipts_monday(args.processed, args.out),
        "coinflip": lambda: coinflip_friday(args.processed, args.out),
        "replykit": lambda: reply_kit(args.processed, args.out, args.date),
    }
    wanted = list(jobs) if args.what == "all" else [args.what]

    line = "=" * 62
    print(f"{line}\nCONTENT DRAFTS\n{line}")
    for name in wanted:
        path, verdict = jobs[name]()
        # Relative when it can be — an --out outside the repo is legitimate
        # (a test, a scratch run) and must not crash the summary line.
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path
        print(f"  {name:9s} -> {shown}  ({verdict})")
    print("Drafts are for human editing before posting. Hype Wednesday is not "
          "here:\nit ranked waiver chases from a league's transaction log, and "
          "this product\nreads no league — drafting it would mean inventing the "
          "number it reports.")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
