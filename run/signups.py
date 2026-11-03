"""Who entered an email on the site — `make signups`. The owner's terminal only.

Usage:
    python -m run.signups [--kind KIND] [--since DAYS] [--registry PATH] [--csv PATH]

`make stats` and the dashboard count people and never print an address, on
purpose: their output gets pasted into chats and notes. This is the one view
that shows the addresses themselves, so the owner can see who is on the
waitlist and who asked for what. Everything about it follows from that:

- **The form Worker is the source** (``FORM_ENDPOINT`` + ``FORM_API_KEY``,
  from this shell or the gitignored ``.env``, read the way ``make stats``
  reads them). One GET of every row (``run.intake.fetch_seats``); nothing is
  ever written to the Worker, Stripe or anywhere else.
- **Grouped by what the person asked for** (``KINDS``), each group with the
  one use the privacy policy (section 1) allows for those addresses. The
  waitlist is for the one launch email; a free-report address is for that one
  report; and so on. The output says so under every group, because an address
  list on a screen is an invitation to email it, and those people were
  promised nothing else.
- **One mailbox, one line** (``run.trials.canonical_email``: case, ``+tags``
  and Gmail dots fold away), shown with the first spelling the Worker kept,
  the first day it arrived (Eastern), how many rows it sent, its channel
  (``via``) tags, and, on the waitlist, whether it carried a saved roster.
- **Subscribers are marked** when a registry copy is here (``--registry``,
  default ``data/registry/rosters.json``, as ``make stats``;
  ``make signups-registry`` opens the sealed backup in a temporary folder).
- **The stop list is honoured.** An address on it
  (``data/processed/suppressed.txt``, keyed codes under ``LOG_SECRET``) is
  marked "asked us to stop" and is left out of the CSV. When the list holds
  entries and ``LOG_SECRET`` is not in this shell or ``.env``, nobody can be
  checked against it: every line says so and ``--csv`` refuses, since a CSV
  is the copy most likely to end up in a mailer.
- **The forgotten list cannot be matched here, and need not be:**
  ``data/processed/forgotten.txt`` holds keyed Stripe customer ids, never
  addresses, and ``make privacy ... delete`` removes the person's Worker rows
  itself. A row the Worker could not delete is listed in that request's email
  to hello@ as a step for the owner.
- **It never runs in CI** (the repository is public, so a job log would
  publish every address), and ``--csv`` writes only to a gitignored path
  outside ``site/`` (checked on the disk, so ``SITE/`` on a Mac is caught),
  with owner-only permissions, and never over a file it did not write:
  ``.env``, the books and the registry are gitignored too.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
EASTERN = ZoneInfo("America/New_York")

# (kind, heading, the one use the privacy policy allows). Every Worker kind
# that carries an address (infra/form-worker.js KINDS); "confirm" carries only
# a code. A kind the Worker learns later prints under OTHER until it is added.
KINDS = (
    ("waitlist", "Waitlist: tell me when it opens",
     "For the one launch email only (make waitlist-send)."),
    ("trial", "Free report requests",
     "For that one free report only. Nothing else goes to them unless they sign up."),
    ("rookie_ask", "Rookie report requests",
     "For the one rookie report after the NFL Draft only."),
    ("team_add", "Extra team requests",
     "For confirming and adding that team only."),
    ("update_request", "Roster-update requests",
     "For confirming that roster change only."),
    ("update", "Roster updates (operator path)",
     "For applying that roster change only."),
    ("seat", "League Pass seat claims",
     "For confirming that seat only."),
    ("trade_check", "Trade Check requests",
     "For sending that comparison only."),
)
OTHER = ("other", "Other rows",
         "A kind this tool doesn't know yet. Check what its form promised before using these.")
LABELS = {kind: (heading, use) for kind, heading, use in KINDS}

# A row is external input whatever the Worker promises. An address is printed
# only when it looks like one and holds no control character, so a row cannot
# put a terminal escape sequence on the owner's screen.
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
VIA_RE = re.compile(r"^[a-z0-9-]{1,24}$")
BAD_VIA = "(unreadable tag)"


@dataclass
class Entry:
    """One mailbox within one kind."""

    address: str                    # the first spelling the Worker kept
    first: datetime | None = None
    last: datetime | None = None
    times: int = 0
    vias: list[str] = field(default_factory=list)
    saved_roster: bool = False
    subscriber: str = ""            # the plan on the subscriber list, if any
    stop: str = ""                  # "" | "stopped" | "unknown"


def _when(value: object) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def readable_address(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 254 or not text.isprintable() or not EMAIL_RE.match(text):
        return None
    return text


def group(rows: Iterable[Mapping]) -> tuple[dict[str, dict[str, Entry]], int]:
    """kind -> canonical mailbox -> Entry, oldest row first, and how many rows
    carried an address that could not be shown. Rows with no address field at
    all (a "confirm" code) are not counted: they never held one."""
    from run.trials import canonical_email
    out: dict[str, dict[str, Entry]] = {}
    unreadable = 0
    ordered = sorted(rows, key=lambda r: (_when(r.get("received_at"))
                                          or datetime.max.replace(tzinfo=timezone.utc)))
    for row in ordered:
        if not row.get("email"):
            continue
        address = readable_address(row.get("email"))
        if address is None:
            unreadable += 1
            continue
        kind = str(row.get("kind") or "seat")
        kind = kind if kind in LABELS else OTHER[0]
        box = canonical_email(address)
        entry = out.setdefault(kind, {}).setdefault(box, Entry(address=address))
        entry.times += 1
        stamp = _when(row.get("received_at"))
        if stamp is not None:
            entry.first = entry.first if entry.first and entry.first <= stamp else stamp
            entry.last = entry.last if entry.last and entry.last >= stamp else stamp
        via = row.get("via")
        if via not in (None, ""):
            tag = via if isinstance(via, str) and VIA_RE.fullmatch(via) else BAD_VIA
            if tag not in entry.vias:
                entry.vias.append(tag)
        if kind == "waitlist" and str(row.get("ref") or "").strip():
            entry.saved_roster = True
    return out, unreadable


def since_filter(groups: dict[str, dict[str, Entry]], days: int | None,
                 now: datetime) -> dict[str, dict[str, Entry]]:
    """Only mailboxes with a row in the last ``days`` days (their first-seen
    date and count still cover every row the Worker holds)."""
    if days is None:
        return groups
    cutoff = now - timedelta(days=days)
    return {kind: {box: e for box, e in boxes.items() if e.last and e.last > cutoff}
            for kind, boxes in groups.items()}


def stop_code(address: str, secret: str) -> str:
    """The stop list's keyed code for a mailbox: run.digest.address, computed
    with the secret this tool read (the shell or .env) rather than this
    process's environment. tests/test_signups.py holds the two equal."""
    from run.digest import LENGTH
    from run.trials import canonical_email
    return hmac.new(secret.encode("utf-8"), canonical_email(address).encode("utf-8"),
                    hashlib.sha256).hexdigest()[:LENGTH]


def mark(groups: dict[str, dict[str, Entry]], suppressed: frozenset[str] | set[str],
         secret: str, subscribers: Mapping[str, str] | None) -> None:
    """Stop-list and subscriber marks, in place. A non-empty stop list with no
    secret marks everyone "unknown": nobody can be cleared against it."""
    for boxes in groups.values():
        for box, entry in boxes.items():
            if suppressed:
                entry.stop = (("stopped" if stop_code(entry.address, secret) in suppressed
                               else "") if secret else "unknown")
            if subscribers is not None:
                entry.subscriber = subscribers.get(box, "")


def subscriber_plans(registry: Iterable) -> dict[str, str]:
    """canonical mailbox -> the plan word of its team(s) on the subscriber list."""
    from run.refs import LEAGUE_PASS
    from run.trials import canonical_email
    out: dict[str, set[str]] = {}
    for row in registry:
        word = "seat" if row.plan == LEAGUE_PASS else (row.billing or row.plan)
        out.setdefault(canonical_email(row.email), set()).add(word)
    return {box: "+".join(sorted(words)) for box, words in out.items()}


def _day(stamp: datetime | None) -> str:
    return stamp.astimezone(EASTERN).date().isoformat() if stamp else "unknown"


def _ordered_kinds(groups: Mapping[str, Mapping]) -> list[tuple[str, str, str]]:
    known = [k for k in KINDS if k[0] in groups]
    return known + ([OTHER] if OTHER[0] in groups else [])


def render(groups: dict[str, dict[str, Entry]], now: datetime, unreadable: int,
           has_registry: bool, notes: Iterable[str] = ()) -> str:
    stamp = now.astimezone(EASTERN).strftime("%a %b %-d %Y, %-I:%M %p ET")
    lines = [f"WHO SIGNED UP — form Worker rows, as of {stamp}",
             "Private: these are people's email addresses. Keep this in your terminal. Don't",
             "paste it into a chat, a doc, an issue or anything public.",
             "Each group says the one thing those addresses were given for (privacy policy",
             "section 1). Don't add them to a mailing list or email them anything else.",
             ""]
    notes = list(notes)
    if notes:
        lines += [f"  {n}" for n in notes] + [""]
    shown = _ordered_kinds(groups)
    if not any(groups.get(k) for k, _h, _u in shown):
        lines.append("No address to show.")
    else:
        everyone = {box for boxes in groups.values() for box in boxes}
        lines += [f"{len(everyone)} {'person' if len(everyone) == 1 else 'people'} in all "
                  f"(one mailbox counted once, however it was spelled).", ""]
    for kind, heading, use in shown:
        boxes = groups.get(kind) or {}
        if not boxes:
            continue
        people = len(boxes)
        lines.append(f"{heading.upper()} — {people} {'person' if people == 1 else 'people'}")
        lines.append(f"  {use}")
        head = f"  {'first seen':10}  {'times':>5}  {'via':14}"
        if kind == "waitlist":
            head += f"  {'roster':6}"
        if has_registry:
            head += f"  {'subscriber':12}"
        lines.append(head + "  address")
        for entry in sorted(boxes.values(),
                            key=lambda e: (e.first or now, e.address)):
            row = (f"  {_day(entry.first):10}  {entry.times:>5}  "
                   f"{(', '.join(entry.vias) or '-'):14}")
            if kind == "waitlist":
                row += f"  {('yes' if entry.saved_roster else '-'):6}"
            if has_registry:
                row += f"  {(entry.subscriber or '-'):12}"
            row += f"  {entry.address}"
            if entry.stop == "stopped":
                row += "   [asked us to stop: never email]"
            elif entry.stop == "unknown":
                row += "   [stop list not checked]"
            lines.append(row)
        lines.append("")
    if unreadable:
        lines.append(f"{unreadable} row(s) held an address this tool won't print "
                     f"(not shaped like one, or holding control characters).")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------- #
# the CSV copy
# --------------------------------------------------------------------- #

CSV_FIELDS = ("kind", "address", "first_seen_et", "last_seen_et", "times", "via",
              "saved_roster", "subscriber", "allowed_use")


def _cell(value: str) -> str:
    """A spreadsheet runs a cell that starts with = + - @ as a formula. An
    address is typed by a stranger, so such a cell is written as text."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _inside(path: Path, folder: Path) -> bool:
    """Whether ``path`` is ``folder`` or under it. Compared by the file
    system, not by spelling: on a Mac's case-insensitive disk ``SITE/x.csv``
    is ``site/x.csv``, and a name comparison alone let it through."""
    resolved, target = path.resolve(), folder.resolve()
    if resolved.is_relative_to(target):
        return True
    for parent in (resolved, *resolved.parents):
        try:
            if parent.exists() and os.path.samefile(parent, target):
                return True
        except OSError:
            continue
    return False


def csv_refusal(path: Path, gitignored: Callable[[Path], bool]) -> str | None:
    """Why ``path`` may not hold the CSV, or None. Inside ``site/`` is
    published by the next deploy whatever .gitignore says; anything not
    gitignored could be committed to a public repository."""
    if _inside(path, SITE_DIR):
        return (f"{path} is inside site/, which is published to the web. Use a path such "
                f"as data/signups.csv.")
    if not gitignored(path):
        return (f"{path} is not gitignored, so these addresses could be committed to a "
                f"public repository. Use a path such as data/signups.csv.")
    if path.exists() and not _an_earlier_copy(path):
        return (f"{path} already holds something else, and writing the CSV would replace "
                f"it. Gitignored files such as .env, the books in data/ and the registry "
                f"are kept nowhere else. Use a new path such as data/signups.csv.")
    return None


def _an_earlier_copy(path: Path) -> bool:
    """Whether ``path`` is a CSV this tool wrote (its header row), so a re-run
    may replace it."""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.readline().rstrip("\r\n") == ",".join(CSV_FIELDS)
    except (OSError, UnicodeDecodeError):
        return False


def write_csv(path: Path, groups: dict[str, dict[str, Entry]]) -> tuple[int, int]:
    """(rows written, stopped addresses left out). Owner-only permissions.
    Written to a new file and moved into place, so an existing name that is a
    hard link to some other file (a page under site/, say) is replaced rather
    than written through."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".signups-", suffix=".tmp", dir=path.parent)
    os.chmod(temp, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            written, left_out = _write_rows(handle, groups)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return written, left_out


def _write_rows(handle, groups: dict[str, dict[str, Entry]]) -> tuple[int, int]:
    written = left_out = 0
    out = csv.writer(handle)
    out.writerow(CSV_FIELDS)
    for kind, _heading, use in _ordered_kinds(groups):
        for entry in sorted((groups.get(kind) or {}).values(),
                            key=lambda e: (e.first or datetime.max.replace(tzinfo=timezone.utc),
                                           e.address)):
            if entry.stop:
                left_out += 1
                continue
            out.writerow([_cell(v) for v in (
                kind, entry.address, _day(entry.first), _day(entry.last), str(entry.times),
                " ".join(entry.vias), "yes" if entry.saved_roster else "",
                entry.subscriber, use)])
            written += 1
    return written, left_out


# --------------------------------------------------------------------- #
# the command line
# --------------------------------------------------------------------- #

ENV_NAMES = ("FORM_ENDPOINT", "FORM_API_KEY", "LOG_SECRET")


def cli(argv: list[str] | None = None, environ: Mapping[str, str] | None = None,
        env_file: Path | None = None) -> int:
    """The command line (`make signups`). Refuses in CI, then reads the form
    Worker's address and key and LOG_SECRET from this shell, else the
    gitignored .env (make stats reads the same)."""
    from run.stats import ENV_FILE, in_ci, read_env_file
    environ = os.environ if environ is None else environ
    if in_ci(environ):
        print("make signups does not run in CI: the repository is public, so the job "
              "log would publish people's email addresses. Run it on your own machine.",
              file=sys.stderr)
        return 2
    found = read_env_file(env_file or ENV_FILE, ENV_NAMES)
    settings = {name: environ.get(name) or found.get(name, "") for name in ENV_NAMES}
    return main(argv, settings=settings)


def main(argv: list[str] | None = None, settings: Mapping[str, str] | None = None,
         fetch: Callable[[str, str | None], list[dict]] | None = None,
         gitignored: Callable[[Path], bool] | None = None,
         suppress_file: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m run.signups", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", action="append",
                        choices=[k for k, _h, _u in KINDS] + [OTHER[0]],
                        help="only this group (repeat for several)")
    parser.add_argument("--since", type=int, metavar="DAYS",
                        help="only addresses with a row in the last DAYS days")
    parser.add_argument("--registry", type=Path, default=None,
                        help="a subscriber-list copy, to mark who subscribes")
    parser.add_argument("--csv", type=Path, default=None,
                        help="also write a CSV, to a gitignored path such as data/signups.csv")
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    now = (_when(args.now) if args.now else None) or datetime.now(timezone.utc)
    if args.since is not None and args.since < 1:
        print("--since takes a whole number of days, 1 or more.", file=sys.stderr)
        return 2

    if args.csv is not None:
        from run.stats import _gitignored
        why = csv_refusal(args.csv, gitignored or _gitignored)
        if why:
            print(why, file=sys.stderr)
            return 2

    settings = settings or {}
    endpoint = settings.get("FORM_ENDPOINT", "")
    if not endpoint:
        print("FORM_ENDPOINT is not in this shell or .env, so there is nothing to read "
              "(LAUNCH.md step 5).", file=sys.stderr)
        return 2

    from run.suppress import SuppressionError, load_suppressed
    try:
        suppressed = load_suppressed(suppress_file)
    except SuppressionError as exc:
        print(f"{exc}. Nothing is shown: without it, an address that asked us to stop "
              f"would look like any other.", file=sys.stderr)
        return 1
    secret = settings.get("LOG_SECRET", "").strip()
    if suppressed and not secret and args.csv is not None:
        print(f"The stop list holds {len(suppressed)} entr{'y' if len(suppressed) == 1 else 'ies'} "
              f"and LOG_SECRET is not in this shell or .env, so no address can be checked "
              f"against it. No CSV is written: set LOG_SECRET first.", file=sys.stderr)
        return 2

    from run.intake import IntakeError, fetch_seats
    try:
        rows = (fetch or fetch_seats)(endpoint, settings.get("FORM_API_KEY") or None)
    except IntakeError as exc:
        print(f"Could not read the form Worker ({exc}).", file=sys.stderr)
        return 1

    notes: list[str] = []
    subscribers = None
    from run.rosters import RosterRegistryError, load_rosters
    try:
        subscribers = subscriber_plans(load_rosters(args.registry))
    except RosterRegistryError:
        if args.registry is not None:
            print(f"{args.registry} could not be read as a subscriber list.", file=sys.stderr)
            return 1
        notes.append("No subscriber list on this machine, so subscribers aren't marked "
                     "(make signups-registry).")
    if subscribers is not None:
        notes.append("subscriber = a team on the subscriber list under that plan. Whether a "
                     "plan is still live is Stripe's to say.")
    if suppressed and not secret:
        notes.append(f"The stop list holds {len(suppressed)} entr"
                     f"{'y' if len(suppressed) == 1 else 'ies'}, but LOG_SECRET is not in "
                     f"this shell or .env, so nobody below is checked against it.")

    groups, unreadable = group(rows)
    groups = since_filter(groups, args.since, now)
    if args.kind:
        groups = {k: v for k, v in groups.items() if k in args.kind}
    mark(groups, suppressed, secret, subscribers)
    print(render(groups, now, unreadable, subscribers is not None, notes), end="")

    if args.csv is not None:
        written, left_out = write_csv(args.csv, groups)
        print(f"\nWrote {written} row(s) to {args.csv}"
              + (f", leaving out {left_out} address(es) that asked us to stop" if left_out else "")
              + ".", file=sys.stderr)
        print("It holds personal data: keep it on this machine, never commit or share it, "
              "and delete it when you're done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(cli())
