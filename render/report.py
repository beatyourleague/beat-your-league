"""Render ``week_report.json`` into the v2 report design.

Usage:
    python -m render.report [--input data/processed/week_report.json] [--output PATH]

The design is not re-implemented here: the ``<style>`` block and font links are
lifted verbatim from ``rival-report-template.html`` at render time, so the
template file stays the single source of the product's look. This module only
generates the *content* markup, using the template's own class names.

Two rules enforced throughout (CLAUDE.md security + principle 3):
- Every data-derived string passes through ``html.escape`` — fetched data is
  untrusted and flows into markup escaped, never executed.
- A gap in the JSON (``*_gate`` / ``meta.gaps``) renders as an explicit
  *coming in v0.3* marker. The renderer never fills a hole with a plausible
  number; it can only display what the engine computed.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "rival-report-template.html"
V03 = "coming in v0.3"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _pct(value: float) -> int:
    return max(0, min(100, round(value * 100)))


def extract_design(template_html: str) -> tuple[str, str]:
    """Pull the <style> block and font <link> tags out of the template."""
    style = re.search(r"<style>(.*?)</style>", template_html, re.DOTALL)
    if not style:
        raise ValueError(f"no <style> block found in {TEMPLATE_PATH}")
    links = "\n".join(re.findall(r'<link[^>]+>', template_html))
    return style.group(1), links


def gate_note(reason: str) -> str:
    """The one honest way a missing number renders (principle 3)."""
    return (f'<div class="benchnote"><b>{esc(V03)}:</b> {esc(reason)}</div>')


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

def header(meta: Mapping[str, Any]) -> str:
    chips = [
        f'<span class="chip"><b>{esc(meta["league_name"])}</b>'
        f' · {esc(meta["num_teams"])} teams'
        + (f' · {esc(meta["scoring"])}' if meta.get("scoring") else "") + "</span>",
        f'<span class="chip">This week: <b>{esc(meta["rival_label"])}</b></span>',
        f'<span class="chip">{esc(_generated_stamp(meta))}</span>',
    ]
    if meta.get("rivalry_week"):
        chips.insert(1, '<span class="chip" style="border-color:var(--flag);'
                        'color:var(--flag)"><b>RIVALRY WEEK</b></span>')
    elif meta.get("named_rival_label"):
        chips.insert(2, f'<span class="chip">Rival: '
                        f'<b>{esc(meta["named_rival_label"])}</b></span>')
    banner = ""
    if meta.get("historical_demo"):
        banner = (
            '<div class="regret-note" style="margin:0;border-left:none;">'
            f'HISTORICAL DEMONSTRATION — real data from the {esc(meta["season"])} season of '
            f'{esc(meta["league_name"])}, rendered as the report would have looked before '
            f'week {esc(meta["week"])}. Availability snapshots did not exist then, so '
            'probability numbers are gated per our calibration policy.</div>'
        )
    return (
        f'<header class="bug"><div class="brand">Beat Your League</div>'
        f'<h1>Week {esc(meta["week"])} · Rival Report</h1>'
        f'<div class="chips">{"".join(chips)}</div></header>{banner}'
    )


def _generated_stamp(meta: Mapping[str, Any]) -> str:
    raw = meta.get("generated_at", "")
    try:
        stamp = datetime.fromisoformat(raw).astimezone(timezone.utc)
        return stamp.strftime("Generated %a %b %d · %H:%M UTC")
    except (TypeError, ValueError):
        return "Generated (timestamp unavailable)"


def section_checklist(items: list[Mapping[str, Any]]) -> str:
    tasks = []
    for item in items:
        klass = "dl ok" if item.get("urgency") in ("now", "done") else "dl"
        tasks.append(
            f'<div class="task"><div class="box"></div><div>'
            f'<div class="do">{esc(item["action"])}</div>'
            f'<div class="{klass}">{esc(item["deadline"])}</div></div></div>'
        )
    return _section("The 30-Second Game Plan", 1, f'<div class="plan">{"".join(tasks)}</div>')


def section_matchup(matchup: Mapping[str, Any]) -> str:
    you, rival = matchup["you"], matchup["rival"]
    board = (
        f'<div class="board">'
        f'<div class="team you"><div class="name">{esc(you["label"])}</div>'
        f'<div class="sub">Engine-optimal lineup</div>'
        f'<div class="pts">{you["projected_total"]:.1f} <small>PROJ</small></div></div>'
        f'<div class="vs">VS</div>'
        f'<div class="team rival"><div class="name">{esc(rival["label"])}</div>'
        f'<div class="sub">Lineup as currently set</div>'
        f'<div class="pts">{rival["projected_total"]:.1f} <small>PROJ</small></div></div>'
        f'</div>'
    )
    prob = matchup.get("win_probability")
    if prob is not None:
        # Higher win probability drives the ball INTO rival territory (right);
        # the template's sample pairs 61% with left:61%.
        ball_left = _pct(prob)
        field = (
            f'<div class="field-wrap"><div class="field-label">'
            f'<span class="l">Your territory</span><span class="r">Rival territory</span></div>'
            f'<div class="field"><div class="endzone l"></div><div class="endzone r"></div>'
            f'<div class="ball" style="left:{ball_left}%"></div></div>'
            f'<p class="field-read"><b class="win">{_pct(prob)}% win probability.</b> '
            f'P(your optimal total beats their set total) under our projection model.</p></div>'
        )
    else:
        field = gate_note(f'win probability — {matchup.get("win_probability_gate", "gated")}')

    # Ranges carry their own backtest evidence (band coverage), so they render
    # independently of the win-probability gate.
    lo = min(you["floor"], rival["floor"])
    hi = max(you["ceiling"], rival["ceiling"])
    span = (hi - lo) or 1.0

    def band(team: Mapping[str, Any], side: str) -> str:
        left = _pct((team["floor"] - lo) / span)
        right = 100 - _pct((team["ceiling"] - lo) / span)
        med = _pct((team["projected_total"] - lo) / span)
        return (
            f'<div class="range {side}"><div class="rl">'
            f'<span>{esc(team["label"])} — realistic range</span>'
            f'<span>proj {team["projected_total"]:.1f}</span></div>'
            f'<div class="track"><span class="band" style="left:{left}%;right:{right}%"></span>'
            f'<span class="med" style="left:{med}%"></span></div>'
            f'<div class="nums"><span>floor {team["floor"]:.0f}</span>'
            f'<span>ceiling {team["ceiling"]:.0f}</span></div></div>'
        )
    basis = matchup.get("range_basis")
    basis_html = (f'<div class="yards" style="justify-content:flex-end">'
                  f'{esc(basis)}</div>' if basis else "")
    ranges = f'<div class="ranges">{band(you, "you")}{band(rival, "rival")}</div>{basis_html}'

    market = (f'<p class="mkt"><b>Market check:</b> {esc(V03)} — '
              f'{esc(matchup.get("market_context_gate", ""))}</p>')
    return _section("The Matchup", 2, board + field + ranges + market)


def _lineup_row(slot: Mapping[str, Any]) -> str:
    name = slot.get("player_name") or "(empty)"
    meta_bits = [b for b in (slot.get("position"),
                             f'{slot["form_games"]} games of form' if slot.get("form_games") is not None else None)
                 if b]
    flags = slot.get("flags") or []
    flip = ' flip' if flags else ""
    fliptags = "".join(f'<span class="fliptag">{esc(f["text"])}</span>' for f in flags)
    projected = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
    confidence = slot.get("confidence")
    if confidence is not None:
        conf_cell = (f'<span class="cwrap"><span class="cbar">'
                     f'<i style="width:{_pct(confidence)}%"></i></span>'
                     f'<span class="clab">{_pct(confidence)} · vs {esc(slot.get("alternative_name") or "bench")}</span></span>')
    else:
        conf_cell = f'<span class="cwrap"><span class="clab">{esc(V03)}</span></span>'
    return (
        f'<div class="lrow{flip}"><span class="slot">{esc(slot["slot"])}</span>'
        f'<span class="pl"><span class="pname">{esc(name)}</span>'
        f'<span class="pmeta">{esc(" · ".join(meta_bits))}</span>{fliptags}</span>'
        f'<span class="proj">{projected}</span>{conf_cell}</div>'
    )


def _lineup_grid(slots: list[Mapping[str, Any]], total: float, total_label: str,
                 note_html: str = "") -> str:
    """``total`` comes from the matchup section so the board and the grid can
    never disagree (summing per-row rounded values drifts)."""
    head = ('<div class="lrow head"><span>Slot</span><span>Player</span>'
            '<span style="text-align:right">Proj</span>'
            '<span style="text-align:right">Conf</span></div>')
    rows = "".join(_lineup_row(s) for s in slots)
    total_row = (
        f'<div class="lrow total"><span class="slot"></span>'
        f'<span class="pl"><span class="pname">Projected Total</span></span>'
        f'<span class="proj">{total:.1f}</span>'
        f'<span class="cwrap"><span class="clab">{esc(total_label)}</span></span></div>'
    )
    return f'<div class="lineup">{head}{rows}{total_row}{note_html}</div>'


def section_rival_watch(watch: Mapping[str, Any] | None) -> str:
    """The named rival's weekly strip. Empty string when not configured."""
    if watch is None:
        return ""
    if "gate" in watch:
        return _section("Rival Watch", 0, gate_note(watch["gate"]))
    h2h = watch.get("head_to_head") or {}
    chips = [
        f'<span class="drv">their record <b>{esc(watch.get("their_record", "—"))}</b></span>',
        f'<span class="drv">you vs them all-time '
        f'<b>{esc(h2h.get("wins", 0))}-{esc(h2h.get("losses", 0))}</b></span>',
    ]
    if watch.get("rivalry_week"):
        body = (
            f'<p class="field-read"><b class="win">It\'s Rivalry Week.</b> '
            f'{esc(watch["label"])} is this week\'s opponent — the whole report '
            f'above is the scouting file.</p>'
            f'<div class="drivers">{"".join(chips)}</div>'
        )
    else:
        lines = []
        if watch.get("their_opponent"):
            lines.append(f'They play {esc(watch["their_opponent"])} this week.')
        if watch.get("fragile_spots"):
            top = watch.get("top_fragility")
            lines.append(f'{esc(watch["fragile_spots"])} fragile spot'
                         f'{"s" if watch["fragile_spots"] != 1 else ""} in their '
                         f'current lineup'
                         + (f' — e.g. {esc(top)}' if top else "") + ".")
        elif watch.get("fragile_spots") == 0:
            lines.append("No fragile spots visible in their current lineup.")
        evidence = h2h.get("evidence", "")
        body = (
            f'<p class="field-read"><b>{esc(watch["label"])}</b> — '
            f'{" ".join(lines) if lines else "no matchup data for them this week."}</p>'
            f'<div class="drivers">{"".join(chips)}</div>'
            f'<p class="mkt">{esc(evidence)} · record {esc(watch.get("record_evidence", ""))}</p>'
        )
    return _section("Rival Watch", 0, body)


def section_lineup(report: Mapping[str, Any]) -> str:
    slots = report["lineup"]
    gates = {s["confidence_gate"] for s in slots if s.get("confidence_gate")}
    note = ""
    if gates:
        listed = " · ".join(sorted(gates))
        note = (f'<div class="benchnote"><b>Why some slots show no confidence:</b> '
                f'{esc(listed)}. Confidence = probability the start outscores the best '
                f'bench alternative at that slot; it prints only when availability is '
                f'known for both players (calibration policy).</div>')
    matchup = report["matchup"]
    grid = _lineup_grid(slots, matchup["you"]["projected_total"],
                        f'vs {matchup["rival"]["projected_total"]:.1f}',
                        note_html=note)
    return _section("Your Optimal Lineup", 3, grid)


def section_rival_lineup(report: Mapping[str, Any]) -> str:
    matchup = report["matchup"]
    grid = _lineup_grid(report["rival_lineup"], matchup["rival"]["projected_total"],
                        f'vs you {matchup["you"]["projected_total"]:.1f}')
    return _section(f'{report["meta"]["rival_label"]} — Lineup As Set', 4, grid)


def section_fragility(items: list[Mapping[str, Any]], rival_label: str) -> str:
    if not items:
        body = gate_note("no fragile spots identified from cached data this week")
    else:
        rows = "".join(
            f'<div class="srow"><div class="x">{i + 1}</div><div>'
            f'<div class="who">{esc(item["title"])}</div>'
            f'<div class="why">{esc(item["detail"])} '
            f'<em>({esc(item["evidence"])})</em></div></div></div>'
            for i, item in enumerate(items)
        )
        body = f'<div class="scout">{rows}</div>'
    return _section(f"Where {rival_label} Is Fragile", 5, body)


def section_regret(regret: Mapping[str, Any]) -> str:
    if "gate" in regret:
        body = (f'<div class="call"><div class="verdict">No coin-flip call published</div>'
                f'{gate_note(regret["gate"])}</div>')
        return _section("Your Regret Score", 6, body)
    confidence = _pct(regret["confidence"])
    drivers = "".join(
        f'<span class="drv">{esc(d["label"])} <b>{esc(d["value"])}</b></span>'
        for d in regret["drivers"]
    )
    body = (
        f'<div class="call"><div class="verdict">Start {esc(regret["start_name"])} '
        f'<span class="over">over</span> {esc(regret["over_name"])}</div>'
        f'<div class="conf"><div class="bar"><i style="width:{confidence}%"></i></div>'
        f'<div class="num">{confidence}%</div></div>'
        f'<div class="drivers">{drivers}</div>'
        f'<p class="why">{esc(regret["definition"])}</p></div>'
    )
    return _section("Your Regret Score", 6, body)


def section_pivots(plans: list[Mapping[str, Any]]) -> str:
    if not plans:
        body = gate_note("no conditional pivots this week — no questionable "
                         "statuses among the starters the engine can see")
    else:
        rows = "".join(
            f'<div class="pivot"><div class="if">If</div>'
            f'<div class="cond">{esc(p["condition"])}</div>'
            f'<div class="then">{esc(p["action"])}</div></div>'
            for p in plans
        )
        body = f'<div class="pivots">{rows}</div>'
    return _section("Pivot Plan — Set It, Forget It", 7, body)


def section_hype(entries: list[Mapping[str, Any]]) -> str:
    if not entries:
        body = gate_note("no waiver FOMO detected in the league transaction log "
                         "for this window")
    else:
        cards = []
        for entry in entries:
            bid = entry.get("top_bid")
            bid_text = f'top bid {bid}' + (
                f' of {entry["faab_budget"]} FAAB' if entry.get("faab_budget") else ""
            ) if bid is not None else "no FAAB bids recorded"
            # Visual only; the honest number (managers chasing) is in the label.
            fomo = min(100, entry["managers_chasing"] * 20)
            cards.append(
                f'<div class="hcard"><div class="top">'
                f'<span class="player">{esc(entry["player_name"])} · {esc(entry["position"])}</span>'
                f'<span class="badge mirage">{esc(V03)}</span></div>'
                f'<div class="gauge g2"><i style="width:{fomo}%"></i></div>'
                f'<div class="gauge-label"><span>League-wide FOMO</span>'
                f'<span>{esc(entry["managers_chasing"])} managers chasing</span></div>'
                f'<p class="read">{esc(entry["bids"])} claims filed, '
                f'{esc(entry["completed_adds"])} completed, {esc(bid_text)} '
                f'({esc(entry["evidence"])}).</p>'
                f'<div class="action no">→ {esc(entry["verdict_gate"])}</div></div>'
            )
        body = f'<div class="hype">{"".join(cards)}</div>'
    return _section("Waiver Hype Meter", 8, body)


def section_receipts(receipts: Mapping[str, Any]) -> str:
    record = receipts.get("record")
    if not record:
        inner = (f'{esc(receipts.get("note", ""))}'
                 f'<br><span class="stamp">Ledger opens · this week</span>')
    else:
        parts = [esc(receipts.get("note", ""))]
        best, worst = receipts.get("best_call"), receipts.get("worst_call")
        if best:
            parts.append(
                f' Best call: <b>{esc(best["recommended"])} over {esc(best["over"])}</b> '
                f'(week {esc(best["week"])}, +{best["margin"]:.1f}).')
        if worst:
            parts.append(
                f' Worst: {esc(worst["recommended"])} over {esc(worst["over"])} '
                f'(week {esc(worst["week"])}, {worst["margin"]:.1f}). '
                f'Both stay on the ledger.')
        inner = "".join(parts) + '<br><span class="stamp">Graded on real box scores</span>'
    return _section("The Receipts", 9, f'<div class="ledger">{inner}</div>')


def footer(meta: Mapping[str, Any]) -> str:
    availability = meta.get("availability_as_of")
    basis = (f"Availability data as of {availability}." if availability
             else "No availability snapshot for this week — probability numbers gated.")
    demo = ("Historical demonstration on real cached league data. "
            if meta.get("historical_demo") else "")
    gaps = meta.get("gaps") or []
    gap_line = (f" Known gaps this run: {len(gaps)} (listed in week_report.json)."
                if gaps else "")
    return (
        f'<footer><b>Beat Your League</b> — the weekly edge report built around your '
        f'rival, not just your roster.<br>{esc(demo)}{esc(basis)}{esc(gap_line)}<br>'
        f'Projections are analysis, not guarantees — no betting picks, no staking '
        f'advice. Fantasy decisions are yours to make (that\'s the fun part).<br>'
        f'Generated deterministically from cached league data · LLM tokens: '
        f'{esc(meta.get("llm_tokens", 0))}</footer>'
    )


def _section(title: str, n: int, body: str) -> str:
    marker = f'<span class="n">§{n}</span>' if n else ""
    return (
        f'<section><div class="eyebrow"><span class="tag">{esc(title)}</span>'
        f'{marker}</div>{body}</section>'
    )


# --------------------------------------------------------------------- #
# page assembly
# --------------------------------------------------------------------- #

def render(report: Mapping[str, Any], template_html: str) -> str:
    style, links = extract_design(template_html)
    meta = report["meta"]
    body = "".join([
        header(meta),
        section_checklist(report["checklist"]),
        section_matchup(report["matchup"]),
        section_rival_watch(report.get("rival_watch")),
        section_lineup(report),
        section_rival_lineup(report),
        section_fragility(report["fragility"], meta["rival_label"]),
        section_regret(report["regret"]),
        section_pivots(report["pivots"]),
        section_hype(report["hype"]),
        section_receipts(report["receipts"]),
        footer(meta),
    ])
    title = (f'Beat Your League — {meta["season"]} Week {meta["week"]} '
             f'Rival Report')
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>{esc(title)}</title>\n{links}\n<style>{style}</style>\n'
        f'</head>\n<body>\n<div class="report">\n{body}\n</div>\n</body>\n</html>\n'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=REPO_ROOT / "data" / "processed" / "week_report.json")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"{args.input} not found — run `python -m engine.week_report` first",
              file=sys.stderr)
        return 1
    report = json.loads(args.input.read_text(encoding="utf-8"))
    template_html = TEMPLATE_PATH.read_text(encoding="utf-8")

    meta = report["meta"]
    output = args.output or (
        REPO_ROOT / "reports" /
        f'rival-report-{meta["season"]}-w{int(meta["week"]):02d}-r{meta["my_roster_id"]}.html'
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(report, template_html), encoding="utf-8")
    print(f"report rendered to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
