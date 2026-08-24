"""Publish the product's grading report as ``site/backtest.html``.

The page is the proof asset a skeptical buyer checks: it publishes the record
WHOLE, including every failing band and the grade's own refusal to claim more.
The page says it cannot be edited by hand — this module is what makes that
structurally true instead of a promise somebody has to keep.

``SOURCE`` is ``reports/nflverse-backtest.md``: the LIVE product's grading. It
used to be ``reports/backtest.md``, the Sleeper-era study of a stack the
product no longer runs, and the frozen method's per-surface mapping
(``reports/nflverse-backtest-method.md`` §1) requires the repoint at every
grade — a buyer sent to "our backtest" was reading a measurement of a
different product answering a different question. The retired study is still
generated and unedited, and says so in its own first line; it simply is not
the page anyone is sent to as evidence.

The faithfulness promise broke once already, exactly as you would expect:
regenerating the source moved its timestamp, the published page did not
follow, and the page sat there claiming a generation date older than its own
source. That is a small thing that costs a lot on the one page whose entire
value is being verifiably faithful. Everything ``verify()`` requires is read
FROM the source for the same reason — hardcoding one study's figures is how a
generator quietly stops applying to the document it publishes.

Design notes:

* The shell (CSS, masthead, footer) is a constant here, lifted verbatim from
  the hand-built page so the published design does not change.
* The converter handles only the constructs the report generators actually emit
  — headings, pipe tables, bullets, ordered lists, paragraphs, and inline
  bold/italic/code. It is deliberately not a general Markdown implementation:
  a small converter whose failures are visible beats a dependency whose
  rendering drifts. ``verify()`` is the backstop — it fails loudly if any
  figure in the source is missing from the output.

Usage::

    python -m render.backtest_site        # after python -m engine.nflverse_backtest
"""

from __future__ import annotations

import argparse
import html
import math
import re
import sys
from pathlib import Path

from render.report import mark_svg

REPO_ROOT = Path(__file__).resolve().parent.parent
# The frozen method's per-surface mapping (reports/nflverse-backtest-method.md
# §1) repoints this page at the LIVE product's grading, at every grade. The
# Sleeper-era study it used to publish measured a stack the product no longer
# runs, against human managers, in one league — it stays generated and
# unedited in reports/backtest.md, carrying its own header saying so, because
# a retired measurement is part of the record; it is simply no longer the page
# a buyer is sent to as the product's evidence.
SOURCE = REPO_ROOT / "reports" / "nflverse-backtest.md"
OUTPUT = REPO_ROOT / "site" / "backtest.html"

# Lifted verbatim from the hand-built page: same palette and type as every
# other surface (CLAUDE.md design NFR — one brand, one design system).
HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>@@TITLE@@</title>
<meta name="description" content="Eleven seasons of graded calls — hits, misses, and the bands that failed, published whole. The complete record behind the number in your report.">
<meta property="og:title" content="@@TITLE@@">
<meta property="og:description" content="Eleven seasons of graded calls — hits, misses, and the bands that failed, published whole. The complete record behind the number in your report.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Beat Your League">
<meta name="twitter:card" content="summary">
<!-- og:image needs the live absolute URL. After the domain exists, add:
     <meta property="og:image" content="https://YOUR-DOMAIN/og.png"> -->
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E%3Cdefs%3E%3ClinearGradient id=%22b%22 x1=%22.10%22 y1=%220%22 x2=%22.74%22 y2=%221%22%3E%3Cstop offset=%220%22 stop-color=%22%23E0A264%22/%3E%3Cstop offset=%22.28%22 stop-color=%22%23B4692F%22/%3E%3Cstop offset=%22.62%22 stop-color=%22%237A3F1D%22/%3E%3Cstop offset=%221%22 stop-color=%22%233A1C0D%22/%3E%3C/linearGradient%3E%3CradialGradient id=%22s%22 cx=%22.32%22 cy=%22.22%22 r=%22.45%22%3E%3Cstop offset=%220%22 stop-color=%22%23FFE2B8%22 stop-opacity=%22.72%22/%3E%3Cstop offset=%221%22 stop-color=%22%23FFE2B8%22 stop-opacity=%220%22/%3E%3C/radialGradient%3E%3CradialGradient id=%22v%22 cx=%22.5%22 cy=%22.5%22 r=%22.62%22%3E%3Cstop offset=%22.40%22 stop-color=%22%231E0E06%22 stop-opacity=%220%22/%3E%3Cstop offset=%221%22 stop-color=%22%231E0E06%22 stop-opacity=%22.70%22/%3E%3C/radialGradient%3E%3C/defs%3E%3Crect width=%2232%22 height=%2232%22 rx=%226%22 fill=%22%23101E33%22/%3E%3Cg transform=%22translate(16 16) rotate(-18)%22%3E%3Cpath id=%22p%22 d=%22M-12.6 0A14.11 14.11 0 0 1 12.6 0A14.11 14.11 0 0 1-12.6 0Z%22 fill=%22url(%23b)%22 stroke=%22%23F2C230%22 stroke-width=%221.05%22/%3E%3Cuse href=%22%23p%22 fill=%22url(%23s)%22 stroke=%22none%22/%3E%3Cuse href=%22%23p%22 fill=%22url(%23v)%22 stroke=%22none%22/%3E%3Cg stroke=%22%23F8F5EE%22 stroke-linecap=%22round%22 fill=%22none%22%3E%3Cpath d=%22M-8.2 .35Q0-1.05 8.2 .35%22 stroke-width=%221.15%22 opacity=%22.95%22/%3E%3Cpath d=%22M-3.5-1.5L-3.1 1.0M-1.2-1.9L-1.0 1.25M1.2-1.9L1.0 1.25M3.5-1.5L3.1 1.0%22 stroke-width=%221.35%22/%3E%3C/g%3E%3C/g%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;800&family=Barlow:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
  :root{--navy:#101E33;--paper:#F6F4EE;--card:#FFF;--turf:#1E7A46;--flag:#F2C230;
    --brick:#B3402F;--slate:#5A6B80;--ink2:#33445C;--line:#D8D3C6;}
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:#E7E4DA;font-family:'Barlow',sans-serif;color:var(--navy);padding:14px 8px 44px;}
  .sheet{max-width:860px;margin:0 auto;background:var(--paper);border:1px solid var(--line);
    box-shadow:0 2px 18px rgba(16,30,51,.10);}
  header{background:linear-gradient(180deg,#182A45,var(--navy));color:var(--paper);padding:26px 28px;}
  header .brand{display:inline-flex;align-items:center;gap:9px;font-family:'Barlow Condensed';font-weight:800;font-size:15px;letter-spacing:.24em;
    text-transform:uppercase;color:var(--flag);}
  header .brand a{color:inherit;text-decoration:none;}
  header .brand svg.mark{width:22px;height:15px;flex:none;}
  header h1{font-family:'Barlow Condensed';font-weight:800;font-size:40px;text-transform:uppercase;margin-top:6px;}
  header p{margin-top:8px;font-size:14px;color:#C9D4E2;line-height:1.55;max-width:620px;}
  main{padding:8px 28px 34px;}
  main h1{display:none;}
  h2{font-family:'Barlow Condensed';font-weight:800;font-size:25px;text-transform:uppercase;
    margin:28px 0 8px;padding-top:14px;border-top:3px double var(--line);}
  h3{font-family:'Barlow Condensed';font-weight:800;font-size:19px;text-transform:uppercase;margin:20px 0 6px;}
  p{font-size:14.5px;line-height:1.6;color:var(--ink2);margin:8px 0;}
  ul{margin:8px 0 8px 20px;} li{font-size:14.5px;line-height:1.6;color:var(--ink2);margin:3px 0;}
  /* The page's own claim, drawn. */
  .calfig{margin:22px 0 6px;}
  .calfig svg{width:100%;height:auto;border:1px solid var(--line);background:#fff;}
  .calfig figcaption{margin-top:9px;font-size:13px;line-height:1.6;color:var(--slate);}
  table{width:100%;border-collapse:collapse;background:var(--card);border:2px solid var(--navy);
    font-size:13.5px;margin:12px 0;font-variant-numeric:tabular-nums;}
  th{background:var(--navy);color:#C9D4E2;font-family:'Barlow Condensed';font-weight:800;
    font-size:11.5px;letter-spacing:.1em;text-transform:uppercase;padding:8px 9px;text-align:left;}
  td{padding:8px 9px;border-top:1px solid #EDEAE1;}
  b{color:var(--navy);}
  footer{padding:18px 28px 26px;font-size:12px;color:var(--slate);line-height:1.6;
    border-top:3px double var(--line);}
</style>
</head>
<body>
<div class="sheet">
  <header>
    <div class="brand">""" + mark_svg("bylb") + """<a href="index.html">Beat Your League</a></div>
    <h1>@@HEADING@@</h1>
    <p>@@LEDE@@</p>
  </header>
"""

TAIL = """</main>
  <div style="padding:26px 28px;border-top:3px double var(--line);text-align:center;">
    <p style="margin:0 0 12px;font-size:15px;">That's the record, failures included.
    Your reports get graded the same way, in public, every Monday.</p>
    <a href="join/index.html" style="display:inline-block;background:var(--turf);color:#fff;
      text-decoration:none;font-family:'Barlow Condensed';font-weight:800;font-size:17px;
      letter-spacing:.1em;text-transform:uppercase;padding:13px 26px;">Set up your team</a>
  </div>
  <footer><b>Beat Your League</b> — analysis, not picks. Every number here is reproducible
  from public NFL data; the live record is on the public ledger.
  NFL data: nflverse (nflverse-data), CC-BY-4.0.@@SIBLING@@</footer>
</div>
</body>
</html>
"""


def _inline(text: str) -> str:
    """Escape, then apply the inline markup the report generators emit.

    Escaping happens FIRST and the replacements insert their own tags, so a
    stray ``<`` in the source can never become markup — the report is generated
    from league data, and league data is somebody else's text.
    """
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<em>\1</em>", out)
    return out


# The first column of a calibration table, across both report generators —
# `engine.backtest` writes "Stated confidence", `engine.nflverse_backtest`
# writes "Stated".
CALIBRATION_HEADERS = frozenset({"Stated confidence", "Stated"})


# The ONLY section whose calibration table may be charted. An allowlist, not a
# denylist, because the two are not symmetric here: guessing "not a diagnostic"
# from prose fails OPEN — a diagnostic worded in a way the pattern misses gets
# drawn as accuracy, and if it also comes first it takes the chart and
# suppresses the real one (reproduced in review). An unrecognised heading now
# means NO chart, which is visible (a test requires the chart to exist) instead
# of silently wrong. Both report generators head this section "Calibration".
PUBLISHABLE_SECTION = "Calibration"

# The retired Sleeper-era study lives in the REPO (reports/backtest.md,
# generated, with a first-line header saying what it is) and is NOT published
# as a page. Owner decision, Aug 24 2026: archival deep pages confuse buyers
# and invite scrutiny of a product that no longer exists; the live page's own
# "What this is not" section names the study and its non-comparability, which
# keeps the acknowledgment without keeping the destination. The record
# survives — in the repository, where the diligent can still find it.
# REFUSED, not exempted: when this was merely a grade exemption, the old
# invocation `--source reports/backtest.md` (the Makefile's own, until the
# unpublish) still built the retired study's figures under the live masthead
# and wrote them over site/backtest.html — one shell-history recall from
# publishing 53.5% as the record behind today's numbers.
RETIRED_SOURCES = frozenset({"backtest.md"})


def _shell(source: Path) -> tuple[str, str, str]:
    """(title, masthead heading, masthead lede) for the published page."""
    return (
        "Beat Your League — The Full Grading Record",
        "The Full Grading Record",
        "Regenerated from the grading run's own output, never hand-edited: the "
        "failing bands and the refusal to claim more are in it because the run "
        "wrote them there. Reproduce it with "
        "<code>python -m engine.nflverse_backtest</code>.",
    )


def _is_publishable_section(section: str) -> bool:
    """May this section's calibration table be charted?

    Only the section that IS the published calibration result. Anything else —
    the availability-controlled diagnostic, a per-position split, a section
    this module has never seen — is tabulated with its own caveat and never
    drawn as if it were accuracy.
    """
    return section.strip() == PUBLISHABLE_SECTION


def _calibration_chart(head: list[str], body: list[list[str]]) -> str:
    """Draw the page's own claim.

    The whole argument of this document is "when we say 64%, roughly 64% of
    those calls hit" — and it was only ever tabulated. Rows of percentages do
    not show a reader how far from the diagonal the numbers sit; one picture
    does.

    Two invariants, both learned the hard way. The caller charts only the
    PUBLISHED calibration table: the availability-controlled one conditions on
    an outcome unknowable at call time and may never be drawn as if it were
    accuracy. And everything this function says in words — the caption, the
    aria-label, the axis window — is DERIVED from the points it is drawing,
    because hardcoded prose about one study's picture is a false statement the
    moment the page is pointed at another.
    """
    try:
        i_stated = head.index("Stated avg")
        i_obs = head.index("Observed")
        i_int = head.index("95% interval")
        i_n = head.index("Decided")
    except ValueError:
        return ""

    def num(cell: str) -> float | None:
        m = re.search(r"-?\d+(?:\.\d+)?", cell)
        return float(m.group(0)) if m else None

    points = []
    for row in body:
        if len(row) <= max(i_stated, i_obs, i_int, i_n):
            continue
        stated, obs, n = num(row[i_stated]), num(row[i_obs]), num(row[i_n])
        bounds = re.findall(r"\d+(?:\.\d+)?", row[i_int])
        if stated is None or obs is None or len(bounds) < 2:
            continue
        points.append((stated, obs, float(bounds[0]), float(bounds[1]),
                       int(n or 0), row[0]))
    if len(points) < 3:
        return ""

    # The window is DERIVED, not fixed. It used to be a hardcoded 45-90% sized
    # for one study, and repointing the page at another drew the top band's dot
    # and its whole error bar outside the frame — a chart silently omitting its
    # most extreme result. Both axes share it so the diagonal stays a true 45
    # degrees and distance from it reads directly.
    edges = [v for p in points for v in (p[0], p[1], p[2], p[3])]
    lo = min(45.0, math.floor(min(edges) / 5.0) * 5.0)
    hi = max(90.0, math.ceil(max(edges) / 5.0) * 5.0)
    W, H, PAD = 560, 300, 42
    def x(v: float) -> float: return PAD + (v - lo) / (hi - lo) * (W - PAD - 14)
    def y(v: float) -> float: return H - PAD - (v - lo) / (hi - lo) * (H - PAD - 16)

    grid = []
    for tick in range(int(lo) + (10 - int(lo) % 10) % 10, int(hi) + 1, 10):
        grid.append(f'<line x1="{x(tick):.1f}" y1="{y(lo):.1f}" x2="{x(tick):.1f}" '
                    f'y2="{y(hi):.1f}" stroke="#D8D3C6" stroke-width="1"/>')
        grid.append(f'<line x1="{x(lo):.1f}" y1="{y(tick):.1f}" x2="{x(hi):.1f}" '
                    f'y2="{y(tick):.1f}" stroke="#D8D3C6" stroke-width="1"/>')
        grid.append(f'<text x="{x(tick):.1f}" y="{H - PAD + 15:.1f}" text-anchor="middle" '
                    f'font-size="10" fill="#5A6B80">{tick}%</text>')
        grid.append(f'<text x="{PAD - 8:.1f}" y="{y(tick) + 3:.1f}" text-anchor="end" '
                    f'font-size="10" fill="#5A6B80">{tick}%</text>')

    marks = []
    for stated, obs, lo_i, hi_i, n, label in points:
        cx = x(stated)
        marks.append(f'<line x1="{cx:.1f}" y1="{y(lo_i):.1f}" x2="{cx:.1f}" '
                     f'y2="{y(hi_i):.1f}" stroke="#B3402F" stroke-width="2" '
                     f'stroke-linecap="round" opacity=".5"/>')
        # area scales with the bucket's sample size, so a 37-call bucket cannot
        # look as solid as a 608-call one
        r = max(3.0, min(9.0, (n ** 0.5) / 3.0))
        marks.append(f'<circle cx="{cx:.1f}" cy="{y(obs):.1f}" r="{r:.1f}" '
                     f'fill="#B3402F" stroke="#F6F4EE" stroke-width="1.5">'
                     f'<title>stated {stated}% \u2192 observed {obs}% '
                     f'({n} decided calls, {label})</title></circle>')

    # The caption is DERIVED, never asserted. It used to be hardcoded prose
    # about a flat line — true of the Sleeper-era study it was written for and
    # false of any other, which is the same failure as a stale figure: a
    # sentence the page states about a picture it is drawing from other data.
    # Branch on the PER-BAND residuals, never on their mean. A mean cancels:
    # errors of +12,+11,+8,-7,-12,-13 average to nearly zero and would have
    # described a wildly miscalibrated chart as tracking the diagonal, and a
    # positive mean with one band below it published "above at every bucket"
    # about a picture whose LARGEST band sat below. Both were reproduced
    # against this function before this rewrite.
    observed = [p[1] for p in points]
    residuals = [p[1] - p[0] for p in points]
    sorts = max(observed) - min(observed)
    above = [r for r in residuals if r > 0.5]
    below = [r for r in residuals if r < -0.5]
    worst = max(abs(r) for r in residuals)
    n = len(residuals)

    if sorts < 8.0:
        verdict = (f"Ours run flat near {sum(observed) / len(observed):.0f}% while "
                   f"stated climbs to {max(p[0] for p in points):.0f}% \u2014 the "
                   f"number barely sorts")
        aria = (f"Observed stays near {sum(observed) / len(observed):.0f}% while "
                f"stated climbs, so the number barely sorts.")
    elif worst < 2.0:
        verdict = (f"Ours track the diagonal \u2014 no band is off by more than "
                   f"{worst:.0f} points \u2014 across a {sorts:.0f}-point spread")
        aria = "Observed tracks stated closely at every band."
    elif not below:
        verdict = (f"Ours sit ABOVE the diagonal at all {n} bands \u2014 the calls "
                   f"land more often than the number says, by as much as "
                   f"{max(above):.0f} points, across a {sorts:.0f}-point spread")
        aria = (f"Observed sits above stated at all {n} bands: the number is "
                f"systematically low.")
    elif not above:
        verdict = (f"Ours sit BELOW the diagonal at all {n} bands \u2014 the calls "
                   f"land less often than the number claims, by as much as "
                   f"{abs(min(below)):.0f} points")
        aria = (f"Observed sits below stated at all {n} bands: the number claims "
                f"more than it delivers.")
    else:
        verdict = (f"Ours sit above the diagonal at {len(above)} of {n} bands and "
                   f"below it at {len(below)} \u2014 the largest gap either way is "
                   f"{worst:.0f} points")
        aria = (f"Observed sits above stated at {len(above)} of {n} bands and below "
                f"it at {len(below)}.")

    return (
        f'<figure class="calfig">'
        f'<svg viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="Stated confidence against observed hit rate. Perfect '
        f'calibration is the diagonal. {aria}">'
        f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>'
        f'{"".join(grid)}'
        f'<line x1="{x(lo):.1f}" y1="{y(lo):.1f}" x2="{x(hi):.1f}" y2="{y(hi):.1f}" '
        f'stroke="#1E7A46" stroke-width="2" stroke-dasharray="6 4"/>'
        f'<text x="{x(78):.1f}" y="{y(82):.1f}" font-size="10" font-weight="700" '
        f'fill="#1E7A46">perfect calibration</text>'
        f'{"".join(marks)}'
        f'<text x="{W / 2:.1f}" y="{H - 6:.1f}" text-anchor="middle" font-size="10.5" '
        f'font-weight="700" fill="#33445C">stated confidence</text>'
        f'<text x="12" y="{H / 2:.1f}" text-anchor="middle" font-size="10.5" '
        f'font-weight="700" fill="#33445C" '
        f'transform="rotate(-90 12 {H / 2:.1f})">observed hit rate</text>'
        f'</svg>'
        f'<figcaption>Each dot is a confidence bucket, sized by how many calls it '
        f'holds; the bar is its 95% interval. On the diagonal, stated equals '
        f'observed. {verdict}. What the report does about it is stated in the '
        f'text above, not softened here.</figcaption>'
        f'</figure>'
    )


# A line that continues the list item above it, rather than starting anything
# new. Markdown hard-wraps: `engine.backtest` emits one bullet per line so this
# never mattered, and `engine.nflverse_backtest` wraps at ~78 columns, so
# repointing the page split every wrapped bullet into a one-line <li> plus an
# orphaned <p> — publishing "week-18 resting is a different" and "population."
# as separate blocks. verify() could not see it: every FIGURE was still
# present, which is why the check below counts items too.
_STARTS_A_BLOCK = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+|#{1,6}\s+|\|)")


def _verdict_counts(markdown: str) -> dict[str, int]:
    """How many bands the source records under each verdict.

    Read from the last column of every calibration table, so the check follows
    whatever vocabulary the report generator uses rather than one hardcoded
    word. `**off**` and `off` are the same verdict.
    """
    counts: dict[str, int] = {}
    in_table = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = _split_row(line)
        if _is_divider(cells):
            continue
        if cells and cells[0] in CALIBRATION_HEADERS:
            in_table = True
            continue
        if in_table and len(cells) >= 2:
            verdict = cells[-1].strip().strip("*").strip()
            if verdict:
                counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def _source_items(markdown: str) -> list[str]:
    """Every list item in the source, continuations joined, markers stripped —
    the text that must appear on the page for the item to have survived."""
    lines = markdown.splitlines()
    items: list[str] = []
    i = 0
    while i < len(lines):
        match = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", lines[i])
        if not match:
            i += 1
            continue
        i, item = _continued(lines, i + 1, match.group(1))
        # The inline markers become tags, which the page comparison strips.
        item = re.sub(r"[*`]", "", item)
        items.append(re.sub(r"\s+", " ", item).strip())
    return items


def _continued(lines: list[str], i: int, item: str) -> tuple[int, str]:
    """Absorb wrapped continuation lines into the item that owns them."""
    while (i < len(lines) and lines[i].strip()
           and not _STARTS_A_BLOCK.match(lines[i])):
        item = f"{item} {lines[i].strip()}"
        i += 1
    return i, item


def _alignment(cell: str) -> str:
    """Markdown's divider row carries the column alignment: `---:` is right,
    `:---:` is centre. Numbers belong right-aligned so their digits line up."""
    cell = cell.strip()
    if cell.endswith(":"):
        return "center" if cell.startswith(":") else "right"
    return "left"


def _is_divider(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells)


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def to_html(markdown: str) -> str:
    """Convert the backtest report body to HTML."""
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    section = ""
    charted = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = min(len(heading.group(1)), 3)
            section = heading.group(2)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if stripped.startswith("|"):
            rows = []
            aligns: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = _split_row(lines[i])
                if _is_divider(cells):
                    # The divider row IS the alignment spec. Discarding it left
                    # every figure on the page ragged-left, so columns of
                    # numbers could not be compared down their digits.
                    aligns = [_alignment(c) for c in cells]
                else:
                    rows.append(cells)
                i += 1
            if rows:
                head, *body = rows
                # Phones: a wide table scrolls inside its own container —
                # never the page body sideways.
                out.append('<div style="overflow-x:auto;-webkit-overflow-scrolling:touch">')
                out.append("<table>")
                def _style(idx: int) -> str:
                    align = aligns[idx] if idx < len(aligns) else "left"
                    return "" if align == "left" else f' style="text-align:{align}"'

                out.append("<tr>" + "".join(f"<th{_style(n)}>{_inline(c)}</th>"
                                            for n, c in enumerate(head)) + "</tr>")
                for row in body:
                    out.append("<tr>" + "".join(f"<td{_style(n)}>{_inline(c)}</td>"
                                                for n, c in enumerate(row)) + "</tr>")
                out.append("</table></div>")
                # The chart draws the page's own claim — and ONLY the
                # publishable table. The availability-controlled table
                # conditions on an outcome unknowable at call time, so drawing
                # it plots the most flattering possible picture of the one
                # table CLAUDE.md's standing order says may never be shown as
                # accuracy. This module's docstring always said so; the code
                # keyed on the header row alone, both tables carry that header,
                # and the page shipped the diagnostic as a second chart.
                if (head and head[0] in CALIBRATION_HEADERS
                        and _is_publishable_section(section) and not charted):
                    chart = _calibration_chart(head, body)
                    out.append(chart)
                    charted = bool(chart)
            continue

        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet:
            out.append("<ul>")
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                item = re.sub(r"^\s*[-*]\s+", "", lines[i])
                i += 1
                i, item = _continued(lines, i, item)
                out.append(f"<li>{_inline(item)}</li>")
            out.append("</ul>")
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            out.append("<ol>")
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                item = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                i += 1
                i, item = _continued(lines, i, item)
                out.append(f"<li>{_inline(item)}</li>")
            out.append("</ol>")
            continue

        # Paragraph: consume until a blank line or the start of another block.
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|\||\s*[-*]\s|\s*\d+\.\s)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def verify(markdown: str, page: str) -> list[str]:
    """Every figure in the source must survive into the page.

    This is the whole point of the module: the page claims to be a faithful
    publication, so a conversion that silently dropped a row — especially a
    FAILING row — would be worse than no generator at all.
    """
    problems: list[str] = []
    text = re.sub(r"<[^>]+>", " ", page)
    figures = set(re.findall(r"-?\d+\.\d+%?|\b\d{3,5}\b", markdown))
    missing = sorted(f for f in figures if f not in text)
    if missing:
        problems.append(f"{len(missing)} figure(s) missing from the page: {missing[:8]}")
    # The failures specifically: this page exists to publish them. Both report
    # generators mark a failing band in the verdict column — `engine.backtest`
    # writes "off", `engine.nflverse_backtest` writes "**off**" — and the count
    # must survive, not merely the word: a conversion that dropped three of
    # four failing rows would still contain ">off<".
    # Anchored on the verdict COLUMN, not on the literal word "off": keying on
    # one word means a source that reworded its verdicts silently disables the
    # guard, and this is the check that stops a laundered publication. Every
    # verdict the source records must appear as a cell on the page, counted.
    for verdict, wanted in _verdict_counts(markdown).items():
        # Escaped as the page escapes it: a verdict like "too few (< 30)"
        # renders as "too few (&lt; 30)", and comparing the raw string would
        # report a faithful page as broken.
        published = len(re.findall(
            r">\s*(?:<b>)?" + re.escape(html.escape(verdict, quote=False))
            + r"(?:</b>)?\s*<", page))
        if published < wanted:
            problems.append(
                f"{wanted} band(s) recorded {verdict!r} in the source, "
                f"{published} on the page — verdicts did not survive conversion")
    # Structure, not only figures. A conversion that split every wrapped bullet
    # into an <li> plus an orphaned <p> kept every NUMBER and passed the sweep
    # above while publishing sentences cut in half ("week-18 resting is a
    # different" / "population."). Counting items does not catch it either —
    # the halves land in <p>, so the <li> count still matches. The item's TEXT
    # has to survive intact, so that is what is checked.
    # Compared against the <li> CONTENTS, not against the page's flattened
    # text: flattening rejoins the halves ("...is a different" + "population.")
    # into a string that reads correct while the markup is broken.
    published_items = {
        html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", block))).strip()
        for block in re.findall(r"<li>(.*?)</li>", page, re.S)
    }
    for item in _source_items(markdown):
        if item not in published_items:
            problems.append(
                f"a list item did not survive whole: {item[:70]!r}")
            break

    # The grade and its refusal are the source's own verdict on itself and the
    # thing a laundered publication would quietly lose. Required whenever the
    # source states one, checked against the source rather than hardcoded, so
    # this holds for whichever report the page is pointed at.
    grade = re.search(r"^#{1,3}\s+Grade\s+([A-D])\b", markdown, re.M)
    if grade is None:
        # The source is contractually required to carry one (the frozen
        # method's grade table). A missing heading used to SKIP the check,
        # which meant renaming the heading disabled the guard rather than
        # failing it.
        problems.append("the source states no grade, which the method requires")
    elif f"Grade {grade.group(1)}" not in text:
        problems.append(f"the source's own grade ({grade.group(1)}) is not on the page")
    # <ol> draws its own numbers, so a source list that does not start at 1 and
    # run consecutively would be silently RENUMBERED on the published page —
    # a faithful-publication failure that looks like nothing at all.
    groups, current = [], []
    for line in markdown.splitlines():
        match = re.match(r"^\s*(\d+)\.\s", line)
        if match:
            current.append(int(match.group(1)))
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    for group in groups:
        if group != list(range(1, len(group) + 1)):
            problems.append(
                f"ordered list {group} does not run 1..n, so <ol> would renumber it")
    return problems


def build(source: Path = SOURCE) -> str:
    if source.name in RETIRED_SOURCES:
        raise SystemExit(
            f"{source.name} is the retired study and is never published as a "
            f"page (owner decision, Aug 24 2026). The record stays in the "
            f"repository; the live page's 'What this is not' section carries "
            f"the acknowledgment.")
    markdown = source.read_text(encoding="utf-8")
    title, heading, lede = _shell(source)
    # Token substitution rather than str.format: the shell carries a CSS block
    # full of braces, and formatting it raises on the first `{--navy...}`.
    shell = (HEAD.replace("@@TITLE@@", html.escape(title, quote=True))
                 .replace("@@HEADING@@", html.escape(heading, quote=False))
                 .replace("@@LEDE@@", lede))
    page = shell + "  <main>\n" + to_html(markdown) + "\n" + TAIL.replace(
        "@@SIBLING@@", "")
    problems = verify(markdown, page)
    if problems:
        raise SystemExit("refusing to publish an unfaithful backtest page:\n  "
                         + "\n  ".join(problems))
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true",
                        help="fail if the published page is stale, without writing")
    args = parser.parse_args(argv)

    if args.output is None:
        args.output = OUTPUT
    if not args.source.is_file():
        print(f"{args.source} not found — run `python -m engine.nflverse_backtest` first",
              file=sys.stderr)
        return 1
    page = build(args.source)

    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if current != page:
            print(f"{args.output} is out of date with {args.source.name} — "
                  f"run `python -m render.backtest_site`", file=sys.stderr)
            return 1
        print(f"{args.output.name} is up to date with {args.source.name}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(f"Wrote {args.output.relative_to(REPO_ROOT)} from "
          f"{args.source.relative_to(REPO_ROOT)} ({len(page):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
