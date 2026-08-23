"""One free report for one roster — the sell window's demo, as one command.

Usage:
    python -m run.trial --email fan@example.com --roster roster.txt
    pbpaste | python -m run.trial --email fan@example.com --roster -
    python -m run.trial --email ... --roster ... --scoring half_ppr --print

The close that works in a group chat is not a link, it is THEIR team: "send me
your roster, tonight you get this week's file on it, free." This turns that
promise into ninety seconds of operator work: paste whatever they sent —
positions, bye weeks, app junk and all — and out comes the same report a
subscriber gets, mailed (or drafted) plus printed to the console so the text
version can go straight back into the chat they asked in.

Rules that carry over from the paid path, because a free report is still a
report:
- RULE R3 — nothing is guessed. An unresolved or ambiguous name stops the run
  and says exactly which line, because the person who typed it is one message
  away and a confident report about the wrong player is worse than a delay.
- Nothing touches the LEDGER. The public record holds published subscriber
  calls only; grading trial calls into it would pad the receipts with rows no
  paying reader ever saw.
- Nothing touches the REGISTRY. A trial creates no subscription and no state
  beyond one line in the send log.
- Sends are idempotent (one trial email per roster+address per week) and dry
  by default: with no EMAIL_PROVIDER set, a draft lands in reports/outbox/ and
  the console says so plainly.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from engine.subscriber import RosterSpec
from render.email import render_email, subject_for, text_summary
from run.delivery import DRY_PROVIDER, DeliveryError, Message, build_provider, send_all
from run.solo import CACHE_DIR, SoloError, load_week_data, report_for

# The same lineup shapes the signup page offers, so a trial mirrors what the
# person would actually buy.
TEMPLATES = {
    "std": ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"),
    "sf": ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"),
    "nokd": ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX"),
}


class TrialError(RuntimeError):
    """The trial could not be built; the message says which line to fix."""


def resolve_roster(text: str, directory) -> list[str]:
    """Typed lines -> GSIS ids, refusing to guess (RULE R3).

    Every failure names the exact line, because the fix is one message to the
    person who sent it — and a report about the wrong player costs the sale.
    """
    ids: list[str] = []
    problems: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = directory.resolve(line)
        if match.resolved:
            ids.append(match.player.player_id)
        elif match.candidates:
            names = ", ".join(f"{c.name} ({c.team or '?'})"
                              for c in match.candidates[:4])
            problems.append(f"{line!r} is ambiguous — could be {names}. "
                            f"Ask which, then retype with the team name.")
        else:
            problems.append(f"{line!r} — no current player by that name. "
                            f"Check the spelling with them.")
    if problems:
        raise TrialError("The roster needs a human first:\n  " +
                         "\n  ".join(problems))
    if len(ids) != len(set(ids)):
        raise TrialError("The same player appears twice in that roster.")
    return ids


def trial_key(email: str, ids: list[str], season: str, week: int) -> str:
    """One trial per roster+address per week. The digest keeps the address out
    of the committed send log, same rule as every other key."""
    raw = email.strip().lower() + "|" + "|".join(sorted(ids))
    return f"trial-{season}-w{week:02d}-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True,
                        help="where the free report goes")
    parser.add_argument("--roster", required=True,
                        help="a text file of pasted names, or '-' for stdin")
    parser.add_argument("--scoring", default="ppr",
                        choices=["ppr", "half_ppr", "standard"])
    parser.add_argument("--template", default="std", choices=sorted(TEMPLATES))
    parser.add_argument("--size", type=int, default=12, help="league size")
    parser.add_argument("--week", type=int, help="default: the current week")
    parser.add_argument("--season", help="default: the current season")
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--print", dest="print_text", action="store_true",
                        help="also print the plain-text report, ready to paste "
                             "into the chat they asked in")
    parser.add_argument("--resend", action="store_true",
                        help="send again even if this week's trial already went")
    args = parser.parse_args(argv)

    text = (sys.stdin.read() if args.roster == "-"
            else Path(args.roster).read_text(encoding="utf-8"))

    try:
        data = load_week_data(args.cache, args.season, args.week)
        ids = resolve_roster(text, data.directory)
        slots = TEMPLATES[args.template]
        if len(ids) < len(slots):
            raise TrialError(f"{len(slots)} starting slots but only {len(ids)} "
                             f"players — ask for the rest of the roster.")
        spec = RosterSpec(player_ids=tuple(ids), slots=slots,
                          scoring=args.scoring, label="Your Team")
        report = report_for(spec, data, league_size=args.size,
                            cache_dir=args.cache)
    except (SoloError, TrialError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    plain = text_summary(report)
    message = Message(
        to=args.email,
        subject="Your free file — " + subject_for(report),
        html=render_email(report),
        text=plain,
        key=trial_key(args.email, ids, data.season, data.week),
    )

    try:
        provider = build_provider(None)
    except DeliveryError as exc:
        print(f"Delivery not configured: {exc}", file=sys.stderr)
        return 1
    sends = send_all([message], provider=provider, resend_anyway=args.resend)
    result = sends[0]

    line = "=" * 62
    print(f"{line}\nFREE TRIAL — {data.season} week {data.week} · "
          f"{len(ids)} players, {args.scoring}\n{line}")
    if not result.ok:
        print(f"SEND FAILED: {result.detail}", file=sys.stderr)
        return 1
    if result.skipped:
        print("Already sent this week's trial to this address for this roster "
              "— nothing sent twice. Pass --resend to override.")
    elif provider.name == DRY_PROVIDER:
        print("DRAFT ONLY — no EMAIL_PROVIDER set, so nothing was mailed. "
              "The .eml draft is in reports/outbox/.")
    else:
        print(f"Sent via {provider.name}.")
    if args.print_text:
        print(f"\n--- paste-ready ---\n{plain}")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
