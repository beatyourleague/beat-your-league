"""Seat resets — the League Pass buyer's one control over who holds the seats.

A pass's seat link is written to be forwarded (it rides in the buyer's welcome
and on every one of their reports), so once it leaves the league anybody who
holds it can claim a seat, and the buyer's report shows only a count (contract
C2: a count, never who). Before this, a buyer whose count said "11 of 11
seats claimed" while their own leaguemates were told the pass was full had no
remedy at all: only the operator could release a seat, and only by the
holder's address, which nobody had (pre-launch review APPSEC-2).

A RESET, done by the operator when the buyer replies "reset seats":

- **rotates the pass's seat link.** The link's code (``run.updates.seat_token``)
  takes the reset's stamp as a nonce, so every copy of the old link stops
  matching the pass. Claims made through it afterwards are neither honoured
  nor answered (an answer would tell a squatter the link was ever good).
- **releases every seat claimed before it.** The leaguemates the buyer wants
  re-claim through the new link — about a minute each, the same confirm-by-
  email step — and the count starts again from zero.

The new link reaches the buyer in their next report, and the command prints
it so the operator can reply with it at once.

The file (``data/processed/seat-resets.txt``) is committed, like the stop
list, because the crons read the committed copy. One line per reset:
``<code> <UTC stamp>``, where the code is sha256 of the pass's Stripe id
(``pi_…`` / ``sub_…``) cut to 16 hex. A Stripe id is random and not derived
from an address, so nothing in the file can be matched back to a person;
the newest stamp per pass stands.

    python -m run.seat_resets pi_123…              # reset, print the new link
    python -m run.seat_resets pi_123… --email buyer@example.com   # with the link
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESETS_FILE = REPO_ROOT / "data" / "processed" / "seat-resets.txt"
HEADER = (
    "# League Pass seat resets (run/seat_resets.py): one line per reset, the\n"
    "# pass's code (sha256 of its Stripe id, 16 hex) and when it was reset (UTC).\n"
    "# A reset rotates that pass's seat link and releases every seat claimed\n"
    "# before it. Add with `make seat-reset PASS=pi_…`, then commit it.\n"
)
_LINE = re.compile(r"^([0-9a-f]{16})\s+(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)$")
_PASS_ID = re.compile(r"^(pi|sub)_[A-Za-z0-9]{6,}$")


class SeatResetError(RuntimeError):
    """The resets file exists and cannot be read. Carries no identifier."""


def pass_code(pass_id: str) -> str:
    return hashlib.sha256(str(pass_id).encode("utf-8")).hexdigest()[:16]


def load_history(path: Path | None = None) -> dict[str, list[str]]:
    """pass code -> every reset's stamp, oldest first. See ``load_resets``."""
    path = path or RESETS_FILE
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SeatResetError(f"the seat-reset list could not be read "
                             f"({type(exc).__name__})") from None
    out: dict[str, list[str]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found = _LINE.match(line)
        if not found:
            raise SeatResetError("the seat-reset list has a line this code cannot read")
        code, stamp = found.groups()
        out.setdefault(code, []).append(stamp)
    return {code: sorted(set(stamps)) for code, stamps in out.items()}


def load_resets(path: Path | None = None) -> dict[str, str]:
    """pass code -> the newest reset's stamp (ISO, UTC, ``Z``). A missing file
    is no resets; a file that exists and cannot be read raises — a reset
    quietly ignored would hand the old link's holders their seats back."""
    return {code: stamps[-1] for code, stamps in load_history(path).items()}


def reset_for(pass_id: str, resets: dict[str, str] | None = None) -> str:
    """The stamp of ``pass_id``'s newest reset, or "" when it was never reset.
    ``resets`` from ``load_resets``; read from the committed file if omitted."""
    if not pass_id:
        return ""
    resets = load_resets() if resets is None else resets
    return resets.get(pass_code(pass_id), "")


def reset_time(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def add_reset(pass_id: str, now: datetime | None = None, path: Path | None = None) -> str:
    """Append one reset for ``pass_id``. -> its stamp."""
    if not _PASS_ID.match(pass_id or ""):
        raise ValueError("a pass is named by its Stripe id (pi_… or sub_…)")
    path = path or RESETS_FILE
    load_resets(path)                     # refuse to append to a file we cannot read
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else HEADER
    path.write_text(text + f"{pass_code(pass_id)} {stamp}\n", encoding="utf-8")
    return stamp


def main(argv: list[str] | None = None) -> int:
    import os
    parser = argparse.ArgumentParser(
        prog="python -m run.seat_resets",
        description="Reset a League Pass's seats when its buyer asks: the seat link "
                    "changes and every seat claimed before now is released.")
    parser.add_argument("pass_id", help="the pass's Stripe id (pi_… or sub_…)")
    parser.add_argument("--email", default="",
                        help="the buyer's address, to print their new seat link")
    parser.add_argument("--file", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        stamp = add_reset(args.pass_id.strip(), path=args.file)
    except (ValueError, SeatResetError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Reset recorded ({stamp}). Commit and push data/processed/seat-resets.txt "
          f"BEFORE you send the buyer the new link: the next hourly run releases "
          f"every seat claimed before now and starts matching the new link, and "
          f"the buyer's next report carries it.")
    if args.email:
        from run.updates import seat_url
        link = seat_url(os.environ.get("SITE_URL", ""), os.environ.get("UPDATE_SECRET", ""),
                        args.email.strip(), None, pass_id=args.pass_id.strip(), nonce=stamp)
        if link:
            print(f"Reply to the buyer with their league's new seat link: {link}")
        else:
            print("Set SITE_URL and UPDATE_SECRET in this shell to print the new link.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
