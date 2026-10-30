"""The landing's hero phone and its real-report cards — generated, never typed.

The phone on the landing page used to be hand-written: a one-screen summary
that read better than the email a subscriber actually receives and quoted it
only in part, so the page sold one design and the inbox delivered another. It
is now a faithful copy of that email's first screens, built from the pinned
2024 Week 10 sample (render/sample.py) with the same model (render/anatomy.py)
and the same card markup (render.report.card_html) as the web report and the
email itself. No word or figure on the phone is typed here: the notification
is the email's own subject and inbox preview, the mail row its subject, the
body its masthead, card 01 complete and card 02 through its drivers line.

``make sample`` writes the sample report to tests/fixtures/sample-report-w10.json
and injects:

    site/index.html         phone   — the whole inner HTML of the hero's .screen
                            shot    — "What you get": cards 03 and 04, the
                                      same email scrolled on past the phone,
                                      annotated by the page's callouts
    site/how-it-works.html  hiw-*   — cards 01–05, annotated by the page

A test rebuilds every block from the fixture and requires it to equal what the
page carries, so a page edited by hand, or a sample rebuilt without
re-injecting, fails the suite rather than drifting.

    python -m render.phone            # re-inject from the committed fixture
    python -m render.phone --pages index
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from render import anatomy
from render.email import preheader_for, subject_for
from render.report import card_html, esc

REPO_ROOT = Path(__file__).resolve().parent.parent
LANDING = REPO_ROOT / "site" / "index.html"
HOW = REPO_ROOT / "site" / "how-it-works.html"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "sample-report-w10.json"

# The lock screen and the mail row are the phone's own chrome: the day, the
# time and the sender are the illustration, never a figure from the report.
LOCK_DAY = "Tuesday"
LOCK_TIME = "9:41"
MAIL_TIME = "9:41 AM"
SENDER = "Beat Your League"

# The plan items How it works and the landing annotate, and the one Slot by
# Slot row How it works shows.
# Pinned to the sample: a selection whose target is gone RAISES, so a rebuilt
# sample that no longer says these things cannot ship a blank card.
HIW_PLAN = ("Bench Sam LaPorta", "Sunday morning")
# The landing's close-up keeps the plan items a buyer acts on and drops the
# long "no odds this week" explainer (How it works and the sample show it).
SHOT_PLAN = ("Bench Sam LaPorta", "Thursday night", "Sunday morning")
SLOT_ROW = "Amon-Ra St. Brown"


class SelectionError(ValueError):
    """The pinned sample no longer contains what a card was built to show."""


def number(report: Mapping[str, Any], key: str) -> str:
    """A section's number, by its position among the sections this report has
    (the report's own rule, render.report.number_sections)."""
    return f"{anatomy.sections(report).index(key) + 1:02d}"


def real_tag(report: Mapping[str, Any]) -> str:
    """The data-real marker the figure-drift guard reads: "2024-w10"."""
    meta = report["meta"]
    return f'{meta["season"]}-w{meta["week"]}'


def filecard(report: Mapping[str, Any], inner: str, extra: str = "") -> str:
    """One real-output card, in the wrapper the figure-drift guard sweeps."""
    return (f'<div class="filecard"{extra} data-real="{real_tag(report)}">'
            f'{inner}</div><!--/card-->')


# ------------------------------------------------------------------ the phone

_SIGNAL = ('<svg viewBox="0 0 18 12"><rect x="0" y="8" width="3" height="4" rx="1"/>'
           '<rect x="5" y="5.5" width="3" height="6.5" rx="1"/><rect x="10" y="3" '
           'width="3" height="9" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1"/></svg>')
_WIFI = ('<svg viewBox="0 0 16 12"><path d="M8 11.5 5.6 9a3.4 3.4 0 0 1 4.8 0zM3.2 '
         '6.6a6.8 6.8 0 0 1 9.6 0l-1.4 1.4a4.8 4.8 0 0 0-6.8 0zM.8 4.2a10.2 10.2 0 0 1 '
         '14.4 0l-1.4 1.4a8.2 8.2 0 0 0-11.6 0z"/></svg>')


def _battery(stroke: str) -> str:
    return (f'<svg viewBox="0 0 27 12"><rect x=".5" y=".5" width="23" height="11" rx="3.2" '
            f'fill="none" stroke="{stroke}" opacity=".4"/><rect x="2" y="2" width="17" '
            f'height="8" rx="2"/><rect x="24.5" y="4" width="1.8" height="4" rx=".9" '
            f'opacity=".4"/></svg>')


# A plain outline envelope on a neutral tile: the phone's mail app, drawn
# generically — never Apple's Mail icon, and never our mark (the sender's
# logo does not ride on a notification).
_ENVELOPE = ('<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.7" '
             'stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="6" '
             'width="17" height="12" rx="2"/><path d="M4 7l8 6 8-6"/></svg>')
_TORCH = ('<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" '
          'stroke-linecap="round" stroke-linejoin="round"><path d="M8 3h8l-1 5H9z"/>'
          '<path d="M9 8h6v12a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1z"/><path d="M12 12v3"/></svg>')
_CAMERA = ('<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" '
           'stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h3l2-2.5h6L17 '
           '8h3v11H4z"/><circle cx="12" cy="13.5" r="3.5"/></svg>')


def masthead_html(report: Mapping[str, Any]) -> str:
    """The email's masthead, four lines: the lockup with "Your Report" beside
    it, the week, the team and league, and the stamp (contract C4)."""
    m = anatomy.masthead(report)
    brand = str(m["brand"])
    lead, _, last = brand.rpartition(" ")
    lockup = (f'{esc(lead)} <span class="lg">{esc(last)}</span>' if lead
              else esc(brand))
    return (f'<div class="mh"><div class="mh-top"><span class="mh-brand">{lockup}</span>'
            f'<span class="mh-label">{esc(m["label"])}</span></div>'
            f'<div class="mh-week">{esc(m["week"])}</div>'
            f'<div class="mh-meta"><b>{esc(m["team"])}</b> · {esc(m["meta"])}</div>'
            f'<div class="mh-stamp">{esc(m["stamp"])}</div></div>')


def closest_through_drivers(report: Mapping[str, Any]) -> dict:
    """Card 02 as far as its drivers line: the label, the verdict, the bar and
    its figure, the projections. The definition, reason and closer follow in
    the report; the phone and How it works crop above them."""
    model = copy.deepcopy(anatomy.closest(report))
    model["lines"] = []
    model["closer"] = None
    return model


def phone_screen(report: Mapping[str, Any]) -> str:
    """The whole inner HTML of the hero's ``.screen``.

    At rest — and under reduced motion, without a script, in print — the
    screen is the opened email at its top: the mail row, the masthead and card
    01 through its task. The lock screen is a layer the storyline cross-fades
    in and out over it; every keyframe starts and ends on this rest state."""
    subject = subject_for(report)
    preheader = preheader_for(report)
    body = (masthead_html(report)
            + card_html("lineup", anatomy.lineup(report), number(report, "lineup"),
                        interactive=False)
            + card_html("closest", closest_through_drivers(report),
                        number(report, "closest"), interactive=False))
    status = (f'<span class="icons">{_SIGNAL}{_WIFI}{_battery("#000")}</span>')
    lock_status = (f'<span class="icons">{_SIGNAL}{_WIFI}{_battery("#fff")}</span>')
    return (
        '<div class="island"><i></i></div>'
        f'<div class="statusbar"><span>{LOCK_TIME}</span>{status}</div>'
        '<div class="mailview">'
        f'<div class="mailrow"><span class="av">{esc(SENDER[:1])}</span>'
        f'<span class="mfrom"><b>{esc(SENDER)}</b><span class="subj">{esc(subject)}</span></span>'
        f'<time>{esc(MAIL_TIME)}</time></div>'
        + filecard(report, body, ' id="hero-card"')
        + '</div>'
        '<div class="lock">'
        f'<div class="lk-status">{lock_status}</div>'
        '<div class="lk-fg"><span class="lk-pad"><i></i></span>'
        f'<div class="lk-day">{esc(LOCK_DAY)}</div><div class="lk-time">{esc(LOCK_TIME)}</div>'
        f'<div class="lnote"><span class="av">{_ENVELOPE}</span>'
        f'<span class="ltext"><b class="lfrom">{esc(SENDER)}</b>'
        f'<span class="lsub">{esc(subject)}</span>'
        f'<span class="lpre">{esc(preheader)}</span></span>'
        '<time>now</time><span class="lk-tap"></span></div>'
        f'<div class="lk-tools"><span>{_TORCH}</span><span>{_CAMERA}</span></div>'
        '</div></div>'
        '<div class="glass"><i></i></div>'
        '<div class="homebar"></div>'
    )


# ------------------------------------------------------- the cards that follow

def _items(model: dict, starts: tuple[str, ...]) -> dict:
    """The plan with only the items whose action starts with one of
    ``starts``, in the report's order — each must be found."""
    def action(item: Mapping[str, Any]) -> str:
        return str(item["head"]) + str(item.get("rest") or "")

    for prefix in starts:
        found = [m for m in model["items"] if action(m).startswith(prefix)]
        if len(found) != 1:
            raise SelectionError(f"the sample's game plan has {len(found)} items "
                                 f"starting {prefix!r}; the card shows exactly one")
    model = copy.deepcopy(model)
    model["items"] = [m for m in model["items"] if action(m).startswith(starts)]
    return model


def _slot_row(model: dict, name: str = SLOT_ROW) -> dict:
    """Slot by Slot cut to one starter's row: no bench, no notes."""
    rows = [r for r in model["rows"] if r.get("name") == name]
    if len(rows) != 1:
        raise SelectionError(f"the sample's Slot by Slot has {len(rows)} rows "
                             f"for {name!r}; the landing shows exactly one")
    model = copy.deepcopy(model)
    model["rows"], model["bench"], model["notes"] = rows, [], []
    return model


def _card(report: Mapping[str, Any], key: str, model: dict) -> str:
    return filecard(report, card_html(key, model, number(report, key), interactive=False))


def shot(report: Mapping[str, Any]) -> str:
    """The landing's "What you get": the same email the phone opens, scrolled
    on past it — card 03 (Your Game Plan) and card 04 (If/Then for Gameday),
    on one sheet of paper, for the page's callouts to point at. The phone
    above already shows the masthead, card 01 and card 02, so nothing here
    repeats it. The plan keeps three of its items (SHOT_PLAN) exactly as the
    report prints them, and its standing Saturday line; card 04 is whole."""
    if not report.get("pivots"):
        raise SelectionError("the sample carries no if/then; the landing shows one")
    body = (card_html("plan", _items(anatomy.plan(report), SHOT_PLAN),
                      number(report, "plan"), interactive=False)
            + card_html("ifthen", anatomy.ifthen(report), number(report, "ifthen"),
                        interactive=False))
    return filecard(report, body, ' id="shot-card"')


def hiw_cards(report: Mapping[str, Any]) -> dict[str, str]:
    """How it works annotates cards 01–05 of the same sample."""
    return {
        "hiw-lineup": _card(report, "lineup", anatomy.lineup(report)),
        "hiw-closest": _card(report, "closest", closest_through_drivers(report)),
        "hiw-plan": _card(report, "plan", _items(anatomy.plan(report), HIW_PLAN)),
        "hiw-ifthen": _card(report, "ifthen", anatomy.ifthen(report)),
        "hiw-slot": _card(report, "slots", _slot_row(anatomy.slots(report))),
    }


# ------------------------------------------------- the League Pass's stack

# "One pass, a report for every team" (review, Oct 30 2026): three paper
# reports, masthead up, fanned out from a stack. Each is the masthead of a
# REAL generated report — the pinned 2024 Week 10 sample, the first-week
# sample and a week of the live sample — named the way the product names a
# subscriber's team (render.report.team_name: its roster's lead, fixed by last
# season). Nothing on a card is typed here: each entry is stack_entry() of the
# report that built its page, kept in a small fixture so the page can be
# re-injected without the data cache, and a test holds the sample entries to
# their pages' own mastheads.
PASS_STACK = REPO_ROOT / "tests" / "fixtures" / "pass-stack.json"
LEAGUE_PASS = REPO_ROOT / "site" / "league-pass.html"
# The pages, in the stack's order front to back.
STACK_SOURCES = ("this-week.html", "sample-report.html", "sample-first-week.html")
STACK_CAPTION = ("Real reports from our samples, mastheads up. With the League Pass, "
                 "every manager who claims a seat gets one like these, built from "
                 "their own roster.")


def stack_entry(report: Mapping[str, Any], source: str) -> dict[str, str]:
    """One card of the stack: the report's own masthead, with its team named
    by the roster's lead as a subscriber's report names it."""
    m = anatomy.masthead(report)
    lead = (report.get("meta") or {}).get("team_lead")
    return {"source": source, "label": str(m["label"]), "week": str(m["week"]),
            "team": f"{lead}'s team" if lead else str(m["team"]),
            "meta": str(m["meta"]), "stamp": str(m["stamp"])}


def load_stack(path: Path | None = None) -> list[dict[str, str]]:
    path = path or PASS_STACK
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")))


def write_stack_entry(entry: Mapping[str, str], path: Path | None = None) -> None:
    """Replace (or add) the entry for ``entry["source"]``, kept in
    STACK_SOURCES order."""
    path = path or PASS_STACK
    entries = {e["source"]: e for e in load_stack(path)}
    entries[entry["source"]] = dict(entry)
    ordered = [entries[s] for s in STACK_SOURCES if s in entries]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ordered, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def pass_stack(entries: list[Mapping[str, str]]) -> str:
    """The stack's markup. Raises unless every source has its entry."""
    have = [e.get("source") for e in entries]
    if have != list(STACK_SOURCES):
        raise SelectionError(f"the pass stack needs {list(STACK_SOURCES)}, has {have}")
    cards = []
    for e in entries:
        cards.append(
            '<div class="fcard"><div class="mh"><div class="mh-top"><span class="mh-brand">'
            'Beat Your <span class="lg">League</span></span>'
            f'<span class="mh-label">{esc(e["label"])}</span></div>'
            f'<div class="mh-week">{esc(e["week"])}</div>'
            f'<div class="mh-meta"><b>{esc(e["team"])}</b> · {esc(e["meta"])}</div>'
            f'<div class="mh-stamp">{esc(e["stamp"])}</div></div>'
            '<div class="fpaper" aria-hidden="true"><span class="ftag">Your Lineup, '
            'Decided</span><i></i><i></i><i></i></div></div>')
    names = ", ".join(f'{e["team"]} ({e["week"]})' for e in entries)
    return (f'<figure class="passfan"><div class="fan" data-reveal role="img" '
            f'aria-label="{esc("Three real reports: " + names)}">{"".join(cards)}</div>'
            f'<figcaption>{esc(STACK_CAPTION)}</figcaption></figure>')


# ------------------------------------------------------------------ injection

def markers(name: str) -> tuple[str, str]:
    return f"<!-- {name}:start -->", f"<!-- {name}:end -->"


def block(page: str, name: str) -> str:
    """What a page carries between a block's markers (stripped). Raises when
    the markers are missing or repeated: a page that lost them would
    otherwise keep its stale copy forever."""
    start, end = markers(name)
    if page.count(start) != 1 or page.count(end) != 1:
        raise ValueError(f"expected one {start!r} and one {end!r}")
    inner = page.split(start, 1)[1].split(end, 1)[0]
    return inner.strip()


def inject(path: Path, name: str, html: str) -> None:
    """Replace what sits between ``<!-- name:start -->`` and
    ``<!-- name:end -->`` in ``path``. Raises when the markers are missing."""
    page = path.read_text(encoding="utf-8")
    block(page, name)          # raises on missing or repeated markers
    start, end = markers(name)
    head, rest = page.split(start, 1)
    _, tail = rest.split(end, 1)
    path.write_text(f"{head}{start}\n{html}\n{end}{tail}", encoding="utf-8")


def landing_blocks(report: Mapping[str, Any]) -> dict[str, str]:
    return {"phone": phone_screen(report), "shot": shot(report)}


def write_fixture(report: Mapping[str, Any], path: Path | None = None) -> None:
    path = path or FIXTURE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True, indent=1, ensure_ascii=False)
                    + "\n", encoding="utf-8")


def load_fixture(path: Path | None = None) -> dict:
    return json.loads((path or FIXTURE).read_text(encoding="utf-8"))


def publish(report: Mapping[str, Any], pages: tuple[str, ...] = ("index", "hiw"),
            landing: Path | None = None, how: Path | None = None,
            league_pass: Path | None = None, stack: Path | None = None) -> None:
    """Inject every generated block into the pages that carry them. "lp" is
    the League Pass's stack, from its own fixture (``load_stack``)."""
    if "index" in pages:
        for name, html in landing_blocks(report).items():
            inject(landing or LANDING, name, html)
    if "hiw" in pages:
        for name, html in hiw_cards(report).items():
            inject(how or HOW, name, html)
    if "lp" in pages:
        inject(league_pass or LEAGUE_PASS, "pass-stack", pass_stack(load_stack(stack)))


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--pages", default="index,hiw,lp",
                        help="comma-separated: index, hiw, lp")
    parser.add_argument("--stack-live", type=Path, metavar="REPORT_JSON",
                        help="refresh the League Pass stack's this-week card from a "
                             "saved live-sample report (render.live_sample)")
    args = parser.parse_args(argv)
    report = load_fixture(args.fixture)
    pages = tuple(p for p in args.pages.split(",") if p)
    if args.stack_live:
        write_stack_entry(stack_entry(json.loads(args.stack_live.read_text(encoding="utf-8")),
                                      "this-week.html"))
    try:
        publish(report, pages)
    except (ValueError, SelectionError) as exc:
        print(f"could not inject: {exc}", file=sys.stderr)
        return 1
    print(f"injected {', '.join(pages)} from {args.fixture}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
