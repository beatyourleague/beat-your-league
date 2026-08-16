"""Receipt cards: one graded call rendered as a shareable SVG.

Same paper design system as the report (navy/turf/gold/brick, Barlow), sized
for social (1200x675). SVG keeps the pipeline dependency-free; posting works
by opening the card in any browser and screenshotting, and a PNG export step
can be added later without touching this module.

Honesty rules carry over: cards are generated ONLY from graded ledger entries
(a pending call has no card), ties and voids render with their own stamps, and
every card carries the week, the stated confidence, and the real points.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from engine.ledger import GRADED, HIT, MISS, TIE, VOID, LedgerCall

WIDTH, HEIGHT = 1200, 675

_STAMP = {
    HIT: ("HIT", "#1E7A46"),
    MISS: ("MISS", "#B3402F"),
    TIE: ("TIE", "#5A6B80"),
    "void": ("VOID", "#5A6B80"),
}

_FONT = "'Barlow Condensed','Arial Narrow',sans-serif"
_BODY_FONT = "'Barlow','Helvetica Neue',Arial,sans-serif"


def _points(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "—"


def receipt_card_svg(call: LedgerCall, sample: bool = False) -> str:
    """Render one graded/void call. Raises on pending calls — no card exists
    for a result that doesn't."""
    if call.status not in (GRADED, VOID):
        raise ValueError(f"call {call.call_id} is {call.status}; only settled "
                         "calls get receipt cards")
    outcome = call.outcome if call.status == GRADED else "void"
    stamp_text, stamp_color = _STAMP[outcome or "void"]

    pick = escape(call.pick_name)
    over = escape(call.over_name)
    week_line = escape(f"{call.season} · WEEK {call.week} · {call.slot}")
    confidence = f"{call.confidence:.0%}"
    margin = call.margin
    if call.status == VOID:
        result_line = escape(call.void_reason or "no scoring record")
    elif outcome == TIE:
        result_line = f"{_points(call.pick_points)} — a dead heat. Ties don't count either way."
    else:
        sign = "+" if (margin or 0) >= 0 else ""
        result_line = (f"{pick} {_points(call.pick_points)} · {over} "
                       f"{_points(call.over_points)}  ({sign}{margin:.1f})")

    sample_mark = ""
    if sample:
        sample_mark = (
            f'<text x="600" y="360" text-anchor="middle" font-family={_FONT!r} '
            f'font-size="150" font-weight="800" fill="rgba(90,107,128,.14)" '
            f'transform="rotate(-18 600 337)">SAMPLE · DESIGN PREVIEW</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">
  <rect width="{WIDTH}" height="{HEIGHT}" fill="#E7E4DA"/>
  <rect x="40" y="40" width="{WIDTH - 80}" height="{HEIGHT - 80}" fill="#F6F4EE" stroke="#D8D3C6" stroke-width="2"/>
  <rect x="40" y="40" width="{WIDTH - 80}" height="86" fill="#101E33"/>
  <text x="76" y="95" font-family={_FONT!r} font-size="26" font-weight="800" letter-spacing="6" fill="#F2C230">BEAT YOUR LEAGUE · THE RECEIPTS</text>
  <text x="{WIDTH - 76}" y="95" text-anchor="end" font-family={_FONT!r} font-size="24" font-weight="700" letter-spacing="3" fill="#C9D4E2">{week_line}</text>

  <text x="76" y="205" font-family={_FONT!r} font-size="30" font-weight="800" letter-spacing="4" fill="#5A6B80">THE CALL, AS PUBLISHED</text>
  <text x="76" y="285" font-family={_FONT!r} font-size="64" font-weight="800" fill="#101E33">START {pick}</text>
  <text x="76" y="352" font-family={_FONT!r} font-size="44" font-weight="700" fill="#5A6B80">over {over}</text>

  <rect x="76" y="395" width="360" height="14" fill="#EAE7DE" stroke="#D8D3C6"/>
  <rect x="76" y="395" width="{int(360 * min(max(call.confidence, 0.0), 1.0))}" height="14" fill="#1E7A46"/>
  <text x="452" y="409" font-family={_FONT!r} font-size="30" font-weight="800" fill="#1E7A46">{confidence} stated</text>

  <text x="76" y="490" font-family={_BODY_FONT!r} font-size="30" font-weight="600" fill="#33445C">{result_line}</text>

  <g transform="rotate(-7 {WIDTH - 250} 300)">
    <rect x="{WIDTH - 400}" y="230" width="300" height="120" fill="none" stroke="{stamp_color}" stroke-width="8"/>
    <text x="{WIDTH - 250}" y="315" text-anchor="middle" font-family={_FONT!r} font-size="84" font-weight="800" letter-spacing="8" fill="{stamp_color}">{stamp_text}</text>
  </g>
  {sample_mark}
  <line x1="76" y1="532" x2="{WIDTH - 76}" y2="532" stroke="#D8D3C6" stroke-width="2" stroke-dasharray="8 6"/>
  <text x="76" y="576" font-family={_BODY_FONT!r} font-size="22" fill="#5A6B80">Graded against the real box score. Wins and misses alike — the full ledger is public.</text>
  <text x="76" y="616" font-family={_FONT!r} font-size="24" font-weight="800" letter-spacing="3" fill="#B3402F">ANALYSIS, NOT PICKS</text>
</svg>
'''


def write_receipt_cards(calls: list[LedgerCall], out_dir: Path,
                        sample: bool = False) -> list[Path]:
    """Write a card per settled call; returns paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for call in calls:
        if call.status not in (GRADED, VOID):
            continue
        path = out_dir / f"receipt-{call.season}-w{call.week:02d}-{call.call_id}.svg"
        path.write_text(receipt_card_svg(call, sample=sample), encoding="utf-8")
        written.append(path)
    return written
