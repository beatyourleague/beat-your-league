"""The owner's own books: costs, hours and marketing posts, for the dashboard.

Three small CSV files under the gitignored ``data/`` folder, written by hand
or by the make targets below, read by ``run/dashboard.py`` to turn revenue
into profit and traffic into "which post sold":

    data/costs.csv   date,item,amount,repeats    (repeats: once | monthly | yearly)
    data/hours.csv   date,hours,note
    data/posts.csv   date,tag,where,note         (tag: the ?via= value on the link)

Rules:

- **Private by location.** Everything lives under ``data/``, which is
  gitignored; nothing here is committed or sent anywhere.
- **A line that can't be read is reported, never guessed.** A typo in one
  line skips that line and the dashboard lists it; the rest still counts.
- **A cost is counted on the day it's charged.** A monthly cost dated Oct 3
  counts on Oct 3, Nov 3, Dec 3… up to today; a yearly one each anniversary.
  A day past the month's end lands on its last day (Jan 31 → Feb 28).
- **A post tag is the link's own ``?via=`` value** — the same 24-character
  ``[a-z0-9-]`` rule the site, the Worker and the intake apply, so a tag made
  here survives all the way to the payment. The channel is the part before
  the first hyphen: ``reddit-oct28`` is a reddit post.

Commands (each has a make target):

    make cost ITEM="Domain" AMOUNT=12 REPEATS=yearly   [DATE=2026-08-01]
    make hours H=1.5                                    [NOTE="replied to emails"]
    make link TAG=reddit-oct28 WHERE="r/fantasyfootball" [PAGE=byes/]
    make books                                          (show what's recorded)
"""

from __future__ import annotations

import argparse
import calendar
import csv
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
COSTS = DATA / "costs.csv"
HOURS = DATA / "hours.csv"
POSTS = DATA / "posts.csv"
SITE = "https://beatyourleague.com/"
ET = ZoneInfo("America/New_York")

REPEATS = ("once", "monthly", "yearly")
TAG_RE = re.compile(r"^[a-z0-9-]{1,24}$")          # run.refs.VIA_RE, count.js, carryVia
PAGE_RE = re.compile(r"^(?:[a-z0-9-]+/|[a-z0-9-]+\.html)?$")
HEADERS = {COSTS.name: ("date", "item", "amount", "repeats"),
           HOURS.name: ("date", "hours", "note"),
           POSTS.name: ("date", "tag", "where", "note")}


@dataclass(frozen=True)
class Cost:
    day: date
    item: str
    amount: float
    repeats: str


@dataclass(frozen=True)
class Hours:
    day: date
    hours: float
    note: str


@dataclass(frozen=True)
class Post:
    day: date
    tag: str
    where: str
    note: str

    @property
    def channel(self) -> str:
        return channel_of(self.tag)


@dataclass
class Books:
    costs: list[Cost]
    hours: list[Hours]
    posts: list[Post]
    problems: list[str]
    found: tuple[str, ...]           # which files exist


def channel_of(tag: str) -> str:
    """``reddit-oct28`` → ``reddit``; an untagged visit stays as it is."""
    return tag.split("-", 1)[0] if tag else tag


def _rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    """(line number, row) for every non-blank, non-comment line."""
    text = path.read_text(encoding="utf-8")
    lines = [(n, line) for n, line in enumerate(text.splitlines(), 1)
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return []
    reader = csv.DictReader([line for _n, line in lines])
    out = []
    for (n, _line), row in zip(lines[1:], reader):
        if None in row:                  # more fields than the header: an unquoted comma
            out.append((n, {"__extra__": "too many commas (put quotes around a value that has one)"}))
            continue
        out.append((n, {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}))
    return out


def _day(value: str) -> date:
    return date.fromisoformat(value)


def _money(value: str) -> float:
    amount = float(value.replace("$", "").replace(",", ""))
    if amount < 0 or amount != amount or amount > 1_000_000:
        raise ValueError("amount out of range")
    return round(amount, 2)


def load(root: Path = REPO_ROOT) -> Books:
    data = root / "data"
    books = Books([], [], [], [], ())
    found = []
    for name, parse in ((COSTS.name, _cost), (HOURS.name, _hour), (POSTS.name, _post)):
        path = data / name
        if not path.exists():
            continue
        found.append(name)
        try:
            rows = _rows(path)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            books.problems.append(f"data/{name} couldn't be read ({type(exc).__name__}).")
            continue
        for n, row in rows:
            try:
                if "__extra__" in row:
                    raise ValueError(row["__extra__"])
                item = parse(row)
            except (ValueError, KeyError, TypeError) as exc:
                books.problems.append(f"data/{name} line {n} was skipped: {exc}.")
                continue
            {COSTS.name: books.costs, HOURS.name: books.hours, POSTS.name: books.posts}[name].append(item)
    books.found = tuple(found)
    return books


def _cost(row: dict[str, str]) -> Cost:
    repeats = (row.get("repeats") or "once").lower()
    if repeats not in REPEATS:
        raise ValueError(f"repeats must be once, monthly or yearly, not {repeats!r}")
    item = row.get("item", "")
    if not item:
        raise ValueError("no item")
    return Cost(_day(row["date"]), item[:60], _money(row["amount"]), repeats)


def _hour(row: dict[str, str]) -> Hours:
    hours = float(row["hours"])
    if not 0 < hours <= 24:
        raise ValueError("hours must be between 0 and 24")
    return Hours(_day(row["date"]), hours, row.get("note", "")[:80])


def _post(row: dict[str, str]) -> Post:
    tag = row.get("tag", "").lower()
    if not TAG_RE.fullmatch(tag):
        raise ValueError("tag must be 1-24 lowercase letters, digits or hyphens")
    return Post(_day(row["date"]), tag, row.get("where", "")[:60], row.get("note", "")[:80])


# --------------------------------------------------------------------- #
# costs over time
# --------------------------------------------------------------------- #

def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def charges(cost: Cost, until: date) -> list[date]:
    """Every day ``cost`` is charged, from its first date up to ``until``."""
    if cost.day > until:
        return []
    if cost.repeats == "once":
        return [cost.day]
    step = 1 if cost.repeats == "monthly" else 12
    out, k = [], 0
    while True:
        d = _add_months(cost.day, k * step)
        if d > until:
            return out
        out.append(d)
        k += 1


def spent(costs: list[Cost], start: date | None, end: date) -> float:
    """Costs charged in (start, end] — ``start`` None means since the first."""
    return round(sum(c.amount for c in costs for d in charges(c, end)
                     if start is None or d > start), 2)


def next_charges(costs: list[Cost], today: date, days: int = 30) -> list[tuple[date, Cost]]:
    """Recurring charges due in the next ``days`` days, soonest first."""
    from datetime import timedelta
    horizon = today + timedelta(days=days)
    out = []
    for c in costs:
        if c.repeats == "once":
            continue
        for d in charges(c, horizon):
            if d > today:
                out.append((d, c))
                break
    return sorted(out, key=lambda dc: (dc[0], dc[1].item))


def monthly_run_rate(costs: list[Cost]) -> float:
    """What the recurring costs come to per month."""
    return round(sum(c.amount for c in costs if c.repeats == "monthly")
                 + sum(c.amount / 12 for c in costs if c.repeats == "yearly"), 2)


# --------------------------------------------------------------------- #
# writing (the make targets)
# --------------------------------------------------------------------- #

def append(path: Path, row: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or not path.read_text(encoding="utf-8").strip()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(HEADERS[path.name])
        writer.writerow(row)


def tagged_link(tag: str, page: str = "") -> str:
    return f"{SITE}{page}?via={tag}"


def today_et() -> date:
    return datetime.now(timezone.utc).astimezone(ET).date()


def cli(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cost", help="record a cost")
    c.add_argument("item")
    c.add_argument("amount")
    c.add_argument("--repeats", default="once", choices=REPEATS)
    c.add_argument("--date", default="")
    hh = sub.add_parser("hours", help="record time spent on the business")
    hh.add_argument("hours")
    hh.add_argument("--note", default="")
    hh.add_argument("--date", default="")
    ln = sub.add_parser("link", help="make a tagged link for a post and log it")
    ln.add_argument("tag")
    ln.add_argument("--where", default="")
    ln.add_argument("--page", default="")
    ln.add_argument("--note", default="")
    ln.add_argument("--date", default="")
    sub.add_parser("show", help="print what's recorded")
    args = parser.parse_args(argv)
    data = root / "data"

    def when(value: str) -> str:
        try:
            return (date.fromisoformat(value) if value else today_et()).isoformat()
        except ValueError:
            raise SystemExit(f"DATE must look like 2026-10-28, not {value!r}")

    if args.cmd == "cost":
        try:
            amount = _money(args.amount)
        except ValueError:
            print(f"AMOUNT must be a dollar figure like 12 or 12.50, not {args.amount!r}", file=sys.stderr)
            return 2
        if not args.item.strip():
            print("ITEM is empty: name the cost, e.g. ITEM=\"Domain\"", file=sys.stderr)
            return 2
        append(data / COSTS.name, (when(args.date), args.item.strip()[:60], f"{amount:.2f}", args.repeats))
        every = {"once": "", "monthly": ", every month", "yearly": ", every year"}[args.repeats]
        print(f"Recorded ${amount:.2f} for {args.item.strip()}{every}. It shows on the dashboard's "
              f"Money section.")
        return 0
    if args.cmd == "hours":
        try:
            hours = float(args.hours)
            assert 0 < hours <= 24
        except (ValueError, AssertionError):
            print(f"H must be hours between 0 and 24, like 1.5, not {args.hours!r}", file=sys.stderr)
            return 2
        append(data / HOURS.name, (when(args.date), f"{hours:g}", args.note.strip()[:80]))
        print(f"Recorded {hours:g} h.")
        return 0
    if args.cmd == "link":
        tag = args.tag.strip().lower()
        if not TAG_RE.fullmatch(tag):
            print("TAG must be 1-24 lowercase letters, digits or hyphens, starting with the channel: "
                  "reddit-oct28, x-thread1, discord-myleague.", file=sys.stderr)
            return 2
        page = args.page.strip().lstrip("/")
        if not PAGE_RE.fullmatch(page):
            print("PAGE must be a page of the site such as byes/ or sample-report.html "
                  "(empty for the home page).", file=sys.stderr)
            return 2
        existing = {p.tag for p in load(root).posts}
        if tag in existing:
            print(f"{tag} is already logged — reusing it would merge two posts' numbers. "
                  f"Pick a new tag, e.g. {tag}-2.", file=sys.stderr)
            return 2
        append(data / POSTS.name, (when(args.date), tag, args.where.strip()[:60], args.note.strip()[:80]))
        print(f"Logged {tag} ({channel_of(tag)}). Use this link in the post (or its first reply):\n")
        print(f"  {tagged_link(tag, page)}\n")
        return 0
    books = load(root)
    print(f"Costs: {len(books.costs)} recorded · ${spent(books.costs, None, today_et()):.2f} so far · "
          f"${monthly_run_rate(books.costs):.2f}/month recurring")
    for c in books.costs:
        print(f"  {c.day}  {c.item:<30} ${c.amount:>8.2f}  {c.repeats}")
    print(f"Hours: {sum(h.hours for h in books.hours):g} h over {len(books.hours)} entries")
    print(f"Posts: {len(books.posts)} logged")
    for p in books.posts:
        print(f"  {p.day}  {p.tag:<24} {p.where}")
    for problem in books.problems:
        print(f"  ! {problem}")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
