"""Phase 5: draft the public content formats from graded data.

Usage:
    python -m run.content receipts [--league ID] [--week N]
    python -m run.content hype     [--league ID] [--week N]
    python -m run.content coinflip [--league ID] [--week N] [--roster R]
    python -m run.content replykit [--league ID] [--week N] [--roster R] [--date YYYY-MM-DD]
    python -m run.content all      [...]

Drafts land in ``content/`` for human editing before posting (PLAN.md §5 —
the pipeline drafts, the human edits voice and approves). Everything here is
deterministic: every number is computed from cached data and cited; when a
number can't be defended the draft SAYS so instead of improvising. No LLM
calls (cost NFR: the language layer is a later, optional polish).

Receipts Monday additionally settles the ledger, renders receipt cards, and
regenerates the public ledger page under ``site/ledger/``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any

import render.ledger_site as ledger_site
from engine.behavior import profile_season, rank_by_aggression
from engine.history import HistoryError, load_players, load_season_chain
from engine.ledger import (GRADED, HIT, MISS, LedgerCall, grade_ledger,
                           ledger_path, ledger_summary, load_all_ledgers,
                           load_ledger, public_entries)
from engine.week_report import (PROCESSED_DIR, RAW_DIR, WeekReportError,
                                build_week_report, hype_meter)
from ingest.config import resolve_league_id
from render.cards import write_receipt_cards
from render.ledger_site import write_ledger_site
from run.week import _resolve_roster

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = REPO_ROOT / "content"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _latest_cached_week(league_id: str) -> int:
    seasons = load_season_chain(RAW_DIR, league_id, max_seasons=1)
    weeks = seasons[0].graded_weeks
    if not weeks:
        raise WeekReportError(f"league {league_id} has no cached matchup weeks")
    return max(weeks)


# --------------------------------------------------------------------- #
# Receipts Monday
# --------------------------------------------------------------------- #

def _guard_ledger_shrink(new_entries: list[dict]) -> None:
    """Fail closed if the regenerated public page would LOSE settled entries.

    The ledger is append-only and graded entries are immutable (RULE L4), so
    the only way the public list shrinks is data loss (e.g. a CI cache-restore
    miss). Publishing a wiped page would silently rewrite the public record —
    refuse, exit nonzero, and let a human recover the ledger instead.
    """
    committed = ledger_site.DEFAULT_OUT_DIR / "data.json"
    if not committed.is_file():
        return
    try:
        old_entries = json.loads(committed.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return  # no trustworthy baseline to guard against
    if not isinstance(old_entries, list):
        return

    def key(entry: dict) -> tuple:
        return (entry.get("season"), entry.get("week"), entry.get("slot"),
                entry.get("pick"), entry.get("over"))

    # Multisets, for the same reason as run/monday.py: two rows sharing a key,
    # one of which disappears, is a loss a set comparison cannot see.
    missing = (Counter(key(e) for e in old_entries)
               - Counter(key(e) for e in new_entries))
    if missing:
        raise WeekReportError(
            f"REFUSING to regenerate the public ledger: {len(missing)} "
            "previously published entr(ies) would disappear (e.g. "
            f"{sorted(str(m) for m in missing.elements())[0]}). The ledger store "
            "has lost data — restore "
            "data/processed/ledger/ from the artifact backup, then re-run.")


def receipts_monday(league_id: str, week: int | None) -> tuple[Path, str]:
    path = ledger_path(PROCESSED_DIR, league_id)
    graded_now, pending = grade_ledger(path, RAW_DIR)
    calls = load_ledger(path)
    settled = [c for c in calls if c.status != "pending"]
    target_week = week if week is not None else (
        max((c.week for c in settled), default=None))

    # The PUBLIC page covers every league's published calls, not just this
    # one's — grade the others too, then aggregate.
    all_calls = load_all_ledgers(PROCESSED_DIR)
    for other in {c.league_id for c in all_calls} - {league_id}:
        grade_ledger(ledger_path(PROCESSED_DIR, other), RAW_DIR)
    all_calls = load_all_ledgers(PROCESSED_DIR)
    entries = public_entries(all_calls)
    _guard_ledger_shrink(entries)
    site_page = write_ledger_site(entries, ledger_summary(all_calls))
    # The thread's "season to date" line cites the same aggregate the public
    # page shows, so the post and the page can never disagree.
    summary_all = ledger_summary(all_calls)

    season_label = ""
    week_calls: list[LedgerCall] = []
    if target_week is not None:
        week_calls = [c for c in settled if c.week == target_week]
        if week_calls:
            season_label = week_calls[0].season
    cards = write_receipt_cards(week_calls, CONTENT_DIR / "cards")
    week_summary = ledger_summary(week_calls)

    lines = [
        f"# Receipts Monday — draft" + (f" · {season_label} week {target_week}" if week_calls else ""),
        "",
        "> Human edits before posting. Every number below is from the ledger;",
        f"> grading run settled {graded_now} call(s), {pending} still awaiting final games.",
        f"> Public ledger page regenerated: {site_page.relative_to(REPO_ROOT)}",
        "",
    ]
    if not week_calls:
        lines += [
            "## No graded calls to post",
            "",
            "The ledger has no settled calls for this week — either nothing passed the",
            "publication gate (an honest quiet week) or games aren't final yet. The honest",
            "post, if you want one:",
            "",
            "> No graded calls this week — nothing cleared the bar we set before the season.",
            "> The grading rules were locked before Week 1, and the ledger only counts",
            "> calls we actually sent. See the method: [ledger link]",
        ]
    else:
        record = f"{week_summary['hits']}-{week_summary['misses']}"
        if week_summary["ties"]:
            record += f"-{week_summary['ties']}"
        season_summary = summary_all
        season_record = f"{season_summary['hits']}-{season_summary['misses']}"
        best, worst = week_summary.get("best"), week_summary.get("worst")
        lines += [
            f"## The record",
            "",
            f"- This week: **{record}** on published calls"
            + (f" ({week_summary['hit_rate']:.0%})" if week_summary["hit_rate"] is not None else ""),
            f"- Season to date: **{season_record}**"
            + (f" ({season_summary['hit_rate']:.0%} on {season_summary['hits'] + season_summary['misses']} decided)"
               if season_summary["hit_rate"] is not None else ""),
            f"- Voids shown, not hidden: {week_summary['void']} this week",
            "",
            "## Thread draft (edit voice, then post)",
            "",
            f"**1/** Receipts Monday. Every call we published last week, graded against",
            f"the real box score: **{record}**. Wins AND misses below. \U0001F9FE",
            "",
        ]
        post_number = 2
        for call in week_calls:
            if call.status != GRADED:
                continue
            verdict = "HIT" if call.outcome == HIT else ("MISS" if call.outcome == MISS else "TIE")
            margin = call.margin
            margin_text = (f"{'+' if (margin or 0) >= 0 else ''}{margin:.1f}"
                           if margin is not None else "—")
            lines += [
                f"**{post_number}/** {verdict}: started {call.pick_name} over "
                f"{call.over_name} at {call.confidence:.0%} — "
                f"{call.pick_points:.1f} vs {call.over_points:.1f} ({margin_text}). "
                f"[attach card: content/cards/receipt-{call.season}-w{call.week:02d}-{call.call_id}.svg]",
                "",
            ]
            post_number += 1
        lines += [
            f"**{post_number}/** The full ledger — every call since Week 1, nothing edited",
            "after grading — is public: [ledger link]. Analysis, not picks.",
            "",
            f"## Receipt cards rendered ({len(cards)})",
            "",
        ]
        lines += [f"- {p.relative_to(REPO_ROOT)}" for p in cards]
    lines += ["", "---", "LLM tokens used to draft this: 0 (deterministic templating)."]
    out = _write(
        CONTENT_DIR / (f"receipts-monday-{season_label}-w{target_week:02d}.md"
                       if week_calls else "receipts-monday-empty.md"),
        "\n".join(lines) + "\n")
    return out, f"{len(week_calls)} settled call(s); {len(cards)} card(s)"


# --------------------------------------------------------------------- #
# Hype Meter Wednesday
# --------------------------------------------------------------------- #

def hype_wednesday(league_id: str, week: int | None) -> tuple[Path, str]:
    seasons = load_season_chain(RAW_DIR, league_id, max_seasons=1)
    season = seasons[0]
    players = load_players(RAW_DIR)
    target_week = week if week is not None else _latest_cached_week(league_id)
    entries = hype_meter(season, target_week, players, season.waiver_budget)

    lines = [
        f"# Hype Meter Wednesday — draft · {season.season} week {target_week}",
        "",
        "> Human edits before posting. Chase numbers are from the league transaction",
        "> log; the real-or-mirage verdict needs usage data we don't ingest yet, so",
        "> the honest angle is the CHASE itself — who's paying, and what that reveals.",
        "",
    ]
    if not entries:
        lines += [
            "## No league-wide chase this window",
            "",
            "No player drew multiple chasers in the log. Honest post option:",
            "",
            "> Quietest waiver week of the season — nobody's chasing anybody.",
            "> Sometimes the hype meter reads zero, and saying so is the product.",
        ]
    else:
        lines += ["## Post drafts", ""]
        for entry in entries:
            bid_line = (f"top bid {entry['top_bid']}"
                        + (f" of {entry['faab_budget']} FAAB" if entry.get("faab_budget") else "")
                        if entry.get("top_bid") is not None else "no FAAB bids recorded")
            lines += [
                f"### {entry['player_name']} ({entry['position']})",
                "",
                f"- Managers chasing: **{entry['managers_chasing']}** · claims filed: "
                f"{entry['bids']} · completed: {entry['completed_adds']} · {bid_line}",
                f"- Evidence: {entry['evidence']}",
                f"- What we can't see yet (say so if asked): {entry['verdict_gate']}",
                "",
                "Draft:",
                "",
                f"> Hype check: {entry['managers_chasing']} managers in one league chased "
                f"{entry['player_name']} this week ({bid_line}). The chase is real. Whether",
                f"> the usage is — routes, snaps — is the question that decides if this is",
                f"> an add or a donation. What's your league paying?",
                "",
            ]
    lines += ["---", "LLM tokens used to draft this: 0 (deterministic templating)."]
    out = _write(CONTENT_DIR / f"hype-wednesday-{season.season}-w{target_week:02d}.md",
                 "\n".join(lines) + "\n")
    return out, f"{len(entries)} chase(s) found"


# --------------------------------------------------------------------- #
# Coin-Flip Friday
# --------------------------------------------------------------------- #

def coinflip_friday(league_id: str, week: int | None, roster_id: int) -> tuple[Path, str]:
    """The Friday post comes FROM the ledger, never from a fresh computation.

    That makes its promise literally true: the number posted is the number
    that was recorded when the report shipped, and Monday's grading run will
    settle exactly that entry. If nothing is on the ledger for the week, the
    honest draft says so — a fresh unrecorded number never ships.
    """
    target_week = week if week is not None else _latest_cached_week(league_id)
    report = build_week_report(RAW_DIR, league_id, target_week, roster_id)
    regret = report["regret"]
    season = report["meta"]["season"]

    recorded = [
        c for c in load_ledger(ledger_path(PROCESSED_DIR, league_id))
        if c.is_regret and c.week == target_week and c.roster_id == roster_id
    ]
    call = recorded[0] if recorded else None

    lines = [
        f"# Coin-Flip Friday — draft · {season} week {target_week}",
        "",
        "> Human edits before posting. The call below is read from the LEDGER —",
        "> the number recorded when the report shipped, graded Monday like",
        "> everything else. Never a freshly computed, unrecorded number.",
        "",
    ]
    if call is None:
        reason = regret.get("gate") if "gate" in regret else (
            "no recorded regret call on the ledger for this week — run "
            "`python -m run.week` first so Friday quotes what actually shipped")
        lines += [
            "## No publishable coin flip this week",
            "",
            f"Why: {reason}",
            "",
            "Honest post option (the pass IS the brand):",
            "",
            "> Coin-Flip Friday, except: not one close call cleared our bar",
            "> this week, so we're not publishing one. A confidence number we can't",
            "> stand behind is a vibe, and vibes are free elsewhere. Back next week.",
        ]
        status = "gated"
    else:
        # Drivers add color only when the recomputed call still matches the
        # recorded pair; the pair and the number ALWAYS come from the ledger.
        drivers = ""
        if ("gate" not in regret and regret.get("start_id") == call.pick_id
                and regret.get("over_id") == call.over_id):
            drivers = " · ".join(f"{d['label']}: {d['value']}" for d in regret["drivers"])
        lines += [
            f"## The call, as recorded: {call.pick_name} over {call.over_name} "
            f"({call.confidence:.0%})",
            "",
            f"- Slot: {call.slot} · recorded {call.recorded_at}",
        ]
        if drivers:
            lines += [f"- Drivers: {drivers}"]
        lines += [
            "- Definition (cite if asked): confidence = the odds this start",
            "  outscores that specific bench alternative. Graded Monday either way.",
            "",
            "Draft:",
            "",
            f"> Coin-Flip Friday \U0001FA99 The closest call we published this week:",
            f"> **{call.pick_name} over {call.over_name}, {call.confidence:.0%}.**",
        ]
        if drivers:
            lines += [f"> Not a vibe — {drivers}."]
        lines += [
            "> Recorded when it shipped; graded Monday against the real box score,",
            "> hit or miss, on the public ledger.",
            "",
            "Monday follow-up (pre-draft the quote-tweet):",
            "",
            "> [HIT/MISS]: box score attached. The ledger keeps score either way. [card]",
        ]
        status = f"{call.confidence:.0%} call drafted from ledger"
    lines += ["", "---", "LLM tokens used to draft this: 0 (deterministic templating)."]
    out = _write(CONTENT_DIR / f"coinflip-friday-{season}-w{target_week:02d}.md",
                 "\n".join(lines) + "\n")
    return out, status


# --------------------------------------------------------------------- #
# Daily reply kit
# --------------------------------------------------------------------- #

def reply_kit(league_id: str, week: int | None, roster_id: int,
              kit_date: str) -> tuple[Path, str]:
    target_week = week if week is not None else _latest_cached_week(league_id)
    report = build_week_report(RAW_DIR, league_id, target_week, roster_id)
    seasons = load_season_chain(RAW_DIR, league_id, max_seasons=2)

    items: list[tuple[str, str]] = []  # (number line, reasoning)

    for slot in report["lineup"]:
        if slot.get("confidence") is not None:
            items.append((
                f"{slot['player_name']} {slot['confidence']:.0%} over {slot['alternative_name']} ({slot['slot']})",
                f"published slot call — P(outscores that specific alternative), availability-verified",
            ))
    for item in report.get("fragility", []):
        items.append((item["title"], f"{item['detail']} ({item['evidence']})"))
    for entry in report.get("hype", []):
        bid = f", top bid {entry['top_bid']}" if entry.get("top_bid") is not None else ""
        items.append((
            f"{entry['player_name']}: {entry['managers_chasing']} managers chasing{bid}",
            f"waiver chase from the league log ({entry['evidence']}) — usage verdict withheld, say so",
        ))
    if len(seasons) > 1:
        history = seasons[1]
        profiles = rank_by_aggression(profile_season(history).values())
        if profiles:
            top = profiles[0]
            # Anonymized on purpose: this goes into PUBLIC replies, and a real
            # manager's Sleeper handle plus their behavioral profile would make
            # the league identifiable (privacy NFR: collect and reveal minimum).
            items.append((
                f"One league's top waiver spender: {top.faab_spent} FAAB, "
                f"{top.waiver_bids_placed} claims in a season",
                f"most aggressive manager in that league, {top.season} "
                f"{top.week_span} — never name the account",
            ))
    ledger = load_ledger(ledger_path(PROCESSED_DIR, league_id))
    summary = ledger_summary(ledger)
    if summary["hit_rate"] is not None:
        items.append((
            f"Our ledger: {summary['hits']}-{summary['misses']} on published calls",
            "live public record — every call graded, link the ledger page",
        ))

    items = items[:8]
    lines = [
        f"# Reply kit — {kit_date}",
        "",
        "> 6–8 sharpest numbers of the day, one line of reasoning each, reply",
        "> templates ready to paste-and-adapt. Selection is the human's job;",
        "> never link the product in replies (PLAN.md channel rules).",
        "",
    ]
    for number, why in items:
        lines += [
            f"## {number}",
            f"- Why it's true: {why}",
            f"- Reply template: \"The receipts say: {number}.\"",
            f"- Softer variant: \"FWIW, the numbers here say: {number}. Happy to be wrong Sunday.\"",
            "",
        ]
    if len(items) < 6:
        lines += [
            f"> Only {len(items)} defensible numbers today — the gate held the rest back.",
            "> Fewer, harder numbers beat filler; do not pad this list.",
            "",
        ]
    lines += ["---", "LLM tokens used to draft this: 0 (deterministic templating)."]
    out = _write(CONTENT_DIR / f"reply-kit-{kit_date}.md", "\n".join(lines) + "\n")
    return out, f"{len(items)} number(s)"


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["receipts", "hype", "coinflip", "replykit", "all"])
    parser.add_argument("--league", help="Sleeper league ID (overrides CLAUDE.md)")
    parser.add_argument("--week", type=int, help="target week (default: latest cached / graded)")
    parser.add_argument("--roster", type=int, help="my roster_id (or SLEEPER_ROSTER_ID)")
    parser.add_argument("--date", help="reply-kit date YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)

    league_id = resolve_league_id(args.league, REPO_ROOT)
    kit_date = args.date or _date.today().isoformat()

    jobs = (["receipts", "hype", "coinflip", "replykit"]
            if args.kind == "all" else [args.kind])
    try:
        results: list[tuple[str, Path, str]] = []
        for kind in jobs:
            if kind == "receipts":
                path, note = receipts_monday(league_id, args.week)
            elif kind == "hype":
                path, note = hype_wednesday(league_id, args.week)
            elif kind == "coinflip":
                path, note = coinflip_friday(league_id, args.week,
                                             _resolve_roster(args.roster))
            else:
                path, note = reply_kit(league_id, args.week,
                                       _resolve_roster(args.roster), kit_date)
            results.append((kind, path, note))
    except (WeekReportError, HistoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    line = "=" * 62
    print(f"\n{line}\nCONTENT DRAFTS\n{line}")
    for kind, path, note in results:
        print(f"  {kind:<9} {path.relative_to(REPO_ROOT)}  ({note})")
    print("  Drafts are for HUMAN editing before posting (PLAN.md §5).")
    print("  LLM tokens this run: 0 (deterministic layer only)")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
