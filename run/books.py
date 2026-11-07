"""The owner's own books: costs, hours and marketing posts, for the dashboard.

Costs and hours now live in HQ, the owner's Mac app for the books of every
business (``~/Code/hq``). HQ writes a read-only feed per business; when Beat
Your League's is present (``load_hq_feed``), costs and hours come from it, the
CSVs below are not read for them, and ``make cost`` / ``make hours`` refuse.
Stripe lines HQ booked from its own Stripe connection are skipped, because
this dashboard's revenue is already net of Stripe's fees. Without the feed
everything below works as before.

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
    make link TAG=league-nov10 WHERE="my league chat" PAGE='join/?try=1'
                                   (the free report; keep the quotes in zsh)
    make books                                          (show what's recorded)
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
COSTS = DATA / "costs.csv"
HOURS = DATA / "hours.csv"
POSTS = DATA / "posts.csv"
SITE = "https://beatyourleague.com/"
ET = ZoneInfo("America/New_York")

REPEATS = ("once", "monthly", "quarterly", "yearly")
STEP_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}

# HQ, the owner's Mac app for the books of every business, writes a read-only
# feed per business (HQ's SPEC section 9). When Beat Your League's feed is
# there, costs and hours come from it and data/costs.csv / hours.csv are not
# read: one place to enter them. Posts stay here (they are marketing tags).
HQ_SLUG = "beat-your-league"
HQ_FEED_SCHEMA = "hq-feed/1"
HQ_STALE_DAYS = 7
TAG_RE = re.compile(r"^[a-z0-9-]{1,24}$")          # run.refs.VIA_RE, count.js, carryVia
PAGE_RE = re.compile(r"^(?:[a-z0-9-]+/|[a-z0-9-]+\.html)?$")
# The pages a link may name WITH a query, and only these: the free report
# (join's try mode). Any other "?" stays refused, so a post's link can never
# carry a roster, a seat or somebody's settings.
PAGE_QUERIES = frozenset({"join/?try=1"})
HEADERS = {COSTS.name: ("date", "item", "amount", "repeats"),
           HOURS.name: ("date", "hours", "note"),
           POSTS.name: ("date", "tag", "where", "note")}


@dataclass(frozen=True)
class Cost:
    day: date
    item: str
    amount: float
    repeats: str
    until: date | None = None       # a repeating cost stops after this day
    template: bool = False          # HQ's repeating template: schedules, never counts


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
    found: tuple[str, ...]           # which files exist ("hq" when the HQ feed was read)
    hq: bool = False                 # costs and hours came from HQ's feed


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


def hq_feeds_dir() -> Path:
    """Where HQ writes its feeds: ``$HQ_HOME/feeds`` when set (HQ's own
    override, and what the tests point at an empty folder), else
    ``~/Library/Application Support/HQ/feeds``."""
    home = os.environ.get("HQ_HOME")
    base = Path(home) if home else Path.home() / "Library" / "Application Support" / "HQ"
    return base / "feeds"


def _hq_feed_path(feeds: Path) -> Path | None:
    """This business's feed, found by slug through HQ's index."""
    try:
        index = json.loads((feeds / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    bid = index.get(HQ_SLUG) if isinstance(index, dict) else None
    if not isinstance(bid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", bid):
        return None
    path = feeds / f"{bid}.json"
    return path if path.exists() else None


def _hq_amount(row: dict) -> float:
    value = row.get("amount_usd")
    if value is None:
        raise ValueError("no US-dollar amount yet (HQ has no exchange rate for it)")
    amount = float(str(value))
    if amount != amount or not 0 <= amount <= 1_000_000:
        raise ValueError("amount out of range")
    return round(amount, 2)


def load_hq_feed(path: Path, books: Books, today: date | None = None) -> None:
    """Fill ``books`` costs and hours from HQ's feed. A line that can't be
    read is reported, never guessed; an unreadable feed is one problem line
    and nothing else from it."""
    try:
        feed = json.loads(path.read_text(encoding="utf-8"))
        if feed.get("schema") != HQ_FEED_SCHEMA:
            raise ValueError(f"unknown schema {feed.get('schema')!r}")
    except (OSError, ValueError, AttributeError) as exc:
        books.problems.append(f"HQ's feed couldn't be read ({type(exc).__name__}). Open HQ to rewrite it.")
        return
    books.hq = True
    today = today or today_et()
    try:
        made = datetime.fromisoformat(str(feed.get("generated_at", "")).replace("Z", "+00:00")).date()
        if (today - made).days > HQ_STALE_DAYS:
            books.problems.append(f"HQ's feed is from {made.isoformat()}. Open HQ on this Mac to refresh it.")
    except ValueError:
        books.problems.append("HQ's feed has no date. Open HQ on this Mac to refresh it.")
    for problem in feed.get("problems") or []:
        books.problems.append(f"HQ: {str(problem)[:200]}")
    for n, row in enumerate(feed.get("costs") or [], 1):
        if row.get("source") == "stripe":
            continue                    # this dashboard already takes Stripe's fees off revenue
        try:
            amount = _hq_amount(row)
            books.costs.append(Cost(_day(row["date"]), str(row.get("item", ""))[:60] or "Cost",
                                    -amount if row.get("refund") else amount, "once"))
        except (ValueError, KeyError, TypeError) as exc:
            books.problems.append(f"HQ cost {n} was skipped: {exc}.")
    for n, row in enumerate(feed.get("repeating") or [], 1):
        try:
            every = str(row.get("every", ""))
            if every not in STEP_MONTHS:
                raise ValueError(f"repeats {every!r}")
            until = _day(row["until"]) if row.get("until") else None
            books.costs.append(Cost(_day(row["first"]), str(row.get("item", ""))[:60] or "Cost",
                                    _hq_amount(row), every, until, template=True))
        except (ValueError, KeyError, TypeError) as exc:
            books.problems.append(f"HQ repeating cost {n} was skipped: {exc}.")
    for n, row in enumerate(feed.get("hours") or [], 1):
        try:
            hours = float(row["hours"])
            if not 0 < hours <= 24:
                raise ValueError("hours must be between 0 and 24")
            books.hours.append(Hours(_day(row["date"]), hours, str(row.get("note", ""))[:80]))
        except (ValueError, KeyError, TypeError) as exc:
            books.problems.append(f"HQ hours line {n} was skipped: {exc}.")


def load(root: Path = REPO_ROOT, feeds: Path | None = None) -> Books:
    data = root / "data"
    books = Books([], [], [], [], ())
    found = []
    feed = _hq_feed_path(feeds if feeds is not None else hq_feeds_dir())
    if feed is not None:
        load_hq_feed(feed, books)
        found.append("hq")
    for name, parse in ((COSTS.name, _cost), (HOURS.name, _hour), (POSTS.name, _post)):
        if feed is not None and name != POSTS.name:
            continue                    # HQ owns costs and hours now
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
        raise ValueError(f"repeats must be once, monthly, quarterly or yearly, not {repeats!r}")
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
    """Every day ``cost`` is charged, from its first date up to ``until``
    (and never past the cost's own ``until``)."""
    end = min(until, cost.until) if cost.until else until
    if cost.day > end:
        return []
    if cost.repeats == "once":
        return [cost.day]
    step = STEP_MONTHS[cost.repeats]
    out, k = [], 0
    while True:
        d = _add_months(cost.day, k * step)
        if d > end:
            return out
        out.append(d)
        k += 1


def counted(costs: list[Cost]) -> list[Cost]:
    """The costs that count as money spent. HQ's repeating templates only
    schedule: each charge they made arrives in the feed as its own line."""
    return [c for c in costs if not c.template]


def spent(costs: list[Cost], start: date | None, end: date) -> float:
    """Costs charged in (start, end] — ``start`` None means since the first."""
    return round(sum(c.amount for c in counted(costs) for d in charges(c, end)
                     if start is None or d > start), 2)


def next_charges(costs: list[Cost], today: date, days: int = 30) -> list[tuple[date, Cost]]:
    """Recurring charges due in the next ``days`` days, soonest first."""
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


def monthly_run_rate(costs: list[Cost], today: date | None = None) -> float:
    """What the recurring costs still running come to per month."""
    today = today or today_et()
    live = [c for c in costs if c.repeats != "once" and not (c.until and c.until < today)]
    return round(sum(c.amount / STEP_MONTHS[c.repeats] for c in live), 2)


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
    """The post's link: ``page`` with ``?via=<tag>``, or ``&via=`` when the
    page already has a query ("join/?try=1?via=x" reads try as "1?via=x" and
    opens the buy page, untagged)."""
    return f"{SITE}{page}{'&' if '?' in page else '?'}via={tag}"


def today_et() -> date:
    return datetime.now(timezone.utc).astimezone(ET).date()


# Said wherever a cost is recorded (TOOLS-20): profit is Stripe's net less
# these costs, and Stripe's fees are already out of that net, so a fee logged
# here would count twice. The books keep one currency, US dollars.
COST_NOTE = ("Amounts in US dollars. Stripe's fees are already taken out of net "
             "revenue, so don't log them here.")


def cli(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cost", help="record a cost. " + COST_NOTE, description=COST_NOTE)
    c.add_argument("item")
    c.add_argument("amount", help="US dollars, like 12 or 12.50")
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
    if args.cmd in ("cost", "hours") and _hq_feed_path(hq_feeds_dir()) is not None:
        print("Add it in HQ: costs and time for Beat Your League live there now, and this "
              "dashboard reads them from HQ.", file=sys.stderr)
        return 2

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
        every = {"once": "", "monthly": ", every month", "quarterly": ", every 3 months",
                 "yearly": ", every year"}[args.repeats]
        print(f"Recorded ${amount:.2f} for {args.item.strip()}{every}. It shows on the dashboard's "
              f"Money section.\n{COST_NOTE}")
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
        if not PAGE_RE.fullmatch(page) and PAGE_RE.fullmatch(page + "/"):
            page += "/"                 # "byes" is the planner's folder, byes/
        if not (PAGE_RE.fullmatch(page) or page in PAGE_QUERIES):
            print("PAGE must be a page of the site such as byes/ or sample-report.html "
                  "(empty for the home page), or 'join/?try=1' for the free report.",
                  file=sys.stderr)
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
    if books.hq:
        print("Costs and hours: from HQ.")
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
