"""Render ``week_report.json`` as email-safe HTML — what actually gets sent.

The browser report (``render/report.py``) is the archival artifact; THIS is
the deliverable that lands in an inbox. Email clients are a hostile rendering
target — Outlook uses Word's engine, Gmail strips ``<style>`` in forwards,
and none of them can be trusted with grid, flexbox, custom properties or
loaded fonts. So this module speaks the only dialect they all render:

- tables (``role="presentation"``) for all layout, never grid/flex;
- every style inline, every color a literal hex from the template's palette;
- web-safe font stacks only (the brand's Barlow degrades to Arial);
- self-contained — per-subscriber reports are private, so there is no hosted
  copy to link to; the email must carry the whole report.

Content decisions are NOT re-made here. Every sentence that is pinned by a
test — the cancel/unsubscribe distinction, the no-betting line, the data-age
basis, the as-set explainer — is imported from ``render.report`` so the two
surfaces can never drift apart. All data is escaped on the way in.
"""

from __future__ import annotations

from typing import Any, Mapping

from render.report import (
    AS_SET_BODY,
    AS_SET_HEAD,
    BRAND_LINE,
    CANCEL_BODY,
    CANCEL_HEAD,
    NO_BETTING_LINE,
    NO_CALL,
    NOT_CALLING_IT,
    SECTION_MARK,
    source_line,
    _forward_line,
    _generated_stamp,
    _pct,
    availability_basis,
    edge_phrase,
    esc,
    no_call_explainer,
    number_sections,
    who_can_cover,
)

# The template's palette (:root in rival-report-template.html), as literals —
# email clients do not resolve var().
NAVY = "#101E33"
PAPER = "#F6F4EE"
CARD = "#FFFFFF"
LINE = "#D8D3C6"
SLATE = "#5A6B80"
TURF = "#1E7A46"
BRICK = "#B3402F"
FLAG = "#F2C230"
FLAG_TINT = "#FBF3D9"
BRICK_TINT = "#F7E3DE"
TURF_TINT = "#DFF0E4"

FONT = "Arial,Helvetica,sans-serif"
DISPLAY = "'Arial Narrow',Arial,Helvetica,sans-serif"
BASE = f"font-family:{FONT};font-size:14px;line-height:1.55;color:{NAVY};"
SMALL = f"font-family:{FONT};font-size:12px;line-height:1.5;color:{SLATE};"


def _sec(number: int, title: str, body: str) -> str:
    """One report section: numbered case-file title bar, then the body.

    ``number`` says only WHETHER the section is numbered; the value is filled
    in positionally by number_sections() once the page is assembled, so the
    two surfaces cannot disagree and a merged section cannot leave a hole.
    """
    marker = (f'<span style="color:{SLATE};">{SECTION_MARK}</span> · '
              if number else "")
    return (
        f'<tr><td style="padding:26px 28px 0 28px;">'
        f'<div style="font-family:{DISPLAY};font-size:14px;font-weight:bold;'
        f'letter-spacing:2.5px;text-transform:uppercase;color:{NAVY};'
        f'border-bottom:2px solid {NAVY};padding-bottom:6px;">'
        f'{marker}{esc(title)}</div></td></tr>'
        f'<tr><td style="padding:12px 28px 0 28px;">{body}</td></tr>'
    )


def _gate(reason: str) -> str:
    """A withheld number, in the one honest form (principle 3)."""
    return (
        f'<div style="{BASE}font-size:13px;background:{FLAG_TINT};'
        f'border-left:3px solid {FLAG};padding:10px 12px;margin:8px 0 0 0;">'
        f'<b>{esc(NOT_CALLING_IT)}:</b> {esc(reason)}</div>'
    )


def _note(inner_html: str) -> str:
    return (
        f'<div style="{BASE}font-size:13px;background:{PAPER};'
        f'border-left:3px solid {LINE};padding:10px 12px;margin:10px 0 0 0;">'
        f'{inner_html}</div>'
    )


# --------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------- #

def _header(meta: Mapping[str, Any]) -> str:
    scoring = f' · {esc(meta["scoring"])}' if meta.get("scoring") else ""
    lines = [
        f'<b>{esc(meta["league_name"])}</b> · {esc(meta["num_teams"])} teams{scoring}',
    ]
    # A solo report has no opponent, so there is nothing to name here. The line
    # used to render "This week: None" — an absent value printed as a word.
    if not meta.get("solo"):
        lines.append(f'This week: <b>{esc(meta["rival_label"])}</b>')
    if meta.get("rivalry_week"):
        lines.insert(1, f'<span style="color:{FLAG};font-weight:bold;'
                        f'letter-spacing:1px;">RIVALRY WEEK</span>')
    elif meta.get("named_rival_label"):
        lines.append(f'Rival: <b>{esc(meta["named_rival_label"])}</b>')
    lines.append(esc(_generated_stamp(meta)))
    banner = ""
    if meta.get("historical_demo"):
        banner = (
            f'<tr><td style="padding:0 28px;">'
            f'<div style="{BASE}font-size:13px;background:{FLAG_TINT};'
            f'border-left:3px solid {FLAG};padding:10px 12px;margin-top:16px;">'
            f'SAMPLE REPORT — real data from the {esc(meta["season"])} season of '
            f'{esc(meta["league_name"])}, built to show exactly what lands in your '
            f'inbox on a Tuesday.</div></td></tr>'
        )
    return (
        f'<tr><td style="background:{NAVY};padding:26px 28px;'
        f'border-left:4px solid {FLAG};">'
        f'<div style="font-family:{DISPLAY};font-size:13px;font-weight:bold;'
        f'letter-spacing:4px;text-transform:uppercase;color:{FLAG};">'
        f'Beat Your League</div>'
        f'<div style="font-family:{DISPLAY};font-size:32px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;'
        f'color:{CARD};padding:6px 0 10px 0;">Week {esc(meta["week"])} · '
        f'{"Your Report" if meta.get("solo") else "Rival Report"}</div>'
        f'<div style="font-family:{FONT};font-size:12px;color:#B9C2D0;">'
        f'{" &nbsp;—&nbsp; ".join(lines)}</div></td></tr>{banner}'
    )


def _checklist(items: list[Mapping[str, Any]]) -> str:
    rows = []
    for i, item in enumerate(items, 1):
        color = TURF if item.get("urgency") in ("now", "done") else SLATE
        rows.append(
            f'<tr><td style="{BASE}font-weight:bold;color:{SLATE};'
            f'padding:7px 10px 7px 0;vertical-align:top;width:22px;">{i}</td>'
            f'<td style="{BASE}padding:7px 0;border-bottom:1px solid {LINE};">'
            f'<b>{esc(item["action"])}</b><br>'
            f'<span style="{SMALL}color:{color};">{esc(item["deadline"])}</span>'
            f'</td></tr>'
        )
    body = (f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{"".join(rows)}</table>')
    return _sec(1, "The 30-Second Game Plan", body)


def _last_week(last: Mapping[str, Any] | None) -> str:
    """Same section, email-safe. The scoreline leads; the counts follow."""
    if not last:
        return ""
    chips = " &nbsp;·&nbsp; ".join([
        f'you <b>{last["points"]:.1f}</b>',
        f'them <b>{last["opponent_points"]:.1f}</b>',
        f'best you had <b>{last["best_possible"]:.1f}</b>',
    ])
    return _sec(2, f'Week {esc(last["week"])} — How It Ended',
                f'<p style="{BASE}margin:0;">{esc(last["headline"])}</p>'
                f'<p style="{SMALL}margin:8px 0 0 0;">{chips}</p>')


def _gap_cell(matchup: Mapping[str, Any]) -> str:
    """The gap and its swing, exactly as the browser report states them: the
    gap never travels without the swing, and never in a verdict colour."""
    margin, swing = matchup.get("margin"), matchup.get("margin_swing")
    if matchup.get("range_gate") or margin is None or swing is None:
        return (f'<td width="10%" style="{BASE}font-weight:bold;color:{SLATE};'
                f'text-align:center;">VS</td>')
    side = "ahead" if margin >= 0 else "behind"
    return (
        f'<td width="10%" style="text-align:center;padding:12px 2px;">'
        f'<div style="font-family:{DISPLAY};font-size:22px;font-weight:bold;'
        f'color:#33445C;">{abs(margin):.1f}</div>'
        f'<div style="font-family:{FONT};font-size:9px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{SLATE};">'
        f'projected {side}</div>'
        f'<div style="font-family:{FONT};font-size:9px;color:{SLATE};">'
        f'swings &plusmn;{swing}</div></td>'
    )


def _matchup(matchup: Mapping[str, Any]) -> str:
    you, rival = matchup["you"], matchup["rival"]
    gated = matchup.get("range_gate")

    def side(team: Mapping[str, Any], sub: str, align: str,
             tone: str = NAVY) -> str:
        pts = ("" if gated or "projected_total" not in team else
               f'<div style="font-family:{DISPLAY};font-size:34px;font-weight:bold;'
               f'color:{tone};padding-top:4px;">{team["projected_total"]:.1f} '
               f'<span style="font-size:11px;color:{SLATE};">PROJ</span></div>')
        return (
            f'<td width="45%" style="text-align:{align};padding:12px;'
            f'background:{PAPER};">'
            f'<div style="{BASE}font-weight:bold;">{esc(team["label"])}</div>'
            f'<div style="{SMALL}">{esc(sub)}</div>{pts}</td>'
        )

    board = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0"><tr>{side(you, "Your best lineup this week", "left", TURF)}'
        f'{_gap_cell(matchup)}'
        f'{side(rival, "Lineup as currently set", "right", BRICK)}</tr></table>'
    )
    prob = matchup.get("win_probability")
    if prob is not None:
        field = (f'<p style="{BASE}margin:12px 0 0 0;">'
                 f'<b style="color:{TURF};">{_pct(prob)}% win probability.</b> '
                 f'The odds your best lineup outscores the lineup they have set.</p>')
    else:
        # The gate sentence names its own subject; prefixing it repeated the
        # words and read as a field label with an error in it.
        field = _gate(matchup.get("win_probability_gate", "gated"))

    if gated:
        return _sec(2, "The Matchup", board + field
                    + _gate(f"projected totals and ranges — {gated}"))

    def band(team: Mapping[str, Any]) -> str:
        return (f'<tr><td style="{BASE}padding:5px 0;border-bottom:1px solid {LINE};">'
                f'<b>{esc(team["label"])}</b> — realistic range</td>'
                f'<td style="{BASE}padding:5px 0;border-bottom:1px solid {LINE};'
                f'text-align:right;white-space:nowrap;">floor {team["floor"]:.0f} · '
                f'proj <b>{team["projected_total"]:.1f}</b> · '
                f'ceiling {team["ceiling"]:.0f}</td></tr>')

    basis = matchup.get("range_basis")
    basis_html = f'<p style="{SMALL}margin:6px 0 0 0;">{esc(basis)}</p>' if basis else ""
    ranges = (f'<table role="presentation" width="100%" cellpadding="0" '
              f'cellspacing="0" border="0" style="margin-top:10px;">'
              f'{band(you)}{band(rival)}</table>{basis_html}')
    return _sec(2, "The Matchup", board + field + ranges)


def _rival_watch(watch: Mapping[str, Any] | None) -> str:
    if watch is None:
        return ""
    if "gate" in watch:
        return _sec(0, "Rival Watch", _gate(watch["gate"]))
    h2h = watch.get("head_to_head") or {}
    stats = (f'their record <b>{esc(watch.get("their_record", "—"))}</b> · '
             f'you vs them all-time <b>{esc(h2h.get("wins", 0))}-'
             f'{esc(h2h.get("losses", 0))}</b>')
    if watch.get("rivalry_week"):
        body = (f'<p style="{BASE}margin:0;"><b style="color:{TURF};">It\'s Rivalry '
                f'Week.</b> {esc(watch["label"])} is this week\'s opponent — the '
                f'whole report above is the scouting file.</p>'
                f'<p style="{SMALL}margin:8px 0 0 0;">{stats}</p>')
    else:
        # Mirrors render.report.section_rival_watch's line construction exactly.
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
        text = (" ".join(lines) if lines
                else "no matchup data for them this week.")
        body = (f'<p style="{BASE}margin:0;"><b>{esc(watch["label"])}</b> — '
                f'{text}</p>'
                f'<p style="{SMALL}margin:8px 0 0 0;">{stats} · '
                f'{esc(h2h.get("evidence", ""))} · '
                f'record {esc(watch.get("record_evidence", ""))}</p>')
    return _sec(0, "Rival Watch", body)


def _tape_cells(slot: Mapping[str, Any], mine: bool, tint: str,
                mixed: bool = False) -> str:
    """One half of a tape row: name over its sub-line, then the projection.

    The sub-line carries scouting facts — the point gap on your side, the
    fragility flag on theirs — never our methodology.
    """
    name = slot.get("player_name") or "—"
    proj = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
    # Both halves — see render.report._tape_side. A bye-week starter of YOUR
    # own is the flag the reader can still act on.
    flags = [esc(f["text"]) for f in (slot.get("flags") or [])]
    bits: list[str] = []
    if mine:
        edge = edge_phrase(slot)
        if edge:
            bits.append(esc(edge))
        confidence = slot.get("confidence")
        if confidence is not None:
            bits.append(f"{_pct(confidence)}%")
        elif mixed and slot.get("player_name") and slot.get("confidence_gate"):
            # Mixed weeks only — see render.report._tape_side for the reason.
            bits.append(esc(NO_CALL))
    align = "left" if mine else "right"
    cell = (f'{BASE}padding:7px 8px;border-bottom:1px solid {LINE};'
            f'text-align:{align};background-color:{tint};')
    flag = (f'<br><span style="{SMALL}color:{BRICK};font-weight:bold;">'
            f'{" · ".join(flags)}</span>' if flags else "")
    sub = (f'<br><span style="{SMALL}">{" · ".join(bits)}</span>' if bits else "")
    return (f'<td style="{cell}"><b>{esc(name)}</b>{flag}{sub}</td>'
            f'<td style="{cell}white-space:nowrap;font-weight:bold;'
            f'text-align:right;">{proj}</td>')


def _tape(report: Mapping[str, Any]) -> str:
    """Both lineups on one centre spine — the same grid the browser renders.

    Two stacked nine-row tables made the reader hold your RB in their head
    while scrolling to find theirs. Here the comparison is the row, and the
    tint says who wins the slot so no sentence has to.
    """
    mine, theirs = report["lineup"], report["rival_lineup"]
    as_set = report["meta"].get("lineup_as_set")
    mixed = any(s.get("confidence") is not None for s in mine)
    rows = []
    for index, slot in enumerate(mine):
        other = theirs[index] if index < len(theirs) else {}
        a, b = slot.get("projected"), other.get("projected")
        # Only claimed when BOTH sides have a projection — tinting a row on
        # one number would call a slot we could not compare.
        atint = TURF_TINT if (a is not None and b is not None and a > b) else CARD
        btint = BRICK_TINT if (a is not None and b is not None and b > a) else CARD
        rows.append(
            f'<tr>{_tape_cells(slot, True, atint, mixed)}'
            f'<td style="{SMALL}padding:7px 4px;border-bottom:1px solid {LINE};'
            f'text-align:center;font-weight:bold;color:{SLATE};'
            f'white-space:nowrap;">{esc(slot["slot"])}</td>'
            f'{_tape_cells(other, False, btint)}</tr>'
        )
    matchup = report["matchup"]
    you_total = matchup["you"].get("projected_total")
    rival_total = matchup["rival"].get("projected_total")
    total = ""
    if you_total is not None and rival_total is not None:
        tcell = f'{BASE}font-weight:bold;padding:9px 8px;border-top:2px solid {NAVY};'
        total = (f'<tr><td style="{tcell}">TOTAL</td>'
                 f'<td style="{tcell}text-align:right;">{you_total:.1f}</td>'
                 f'<td style="{tcell}"></td><td style="{tcell}"></td>'
                 f'<td style="{tcell}text-align:right;">{rival_total:.1f}</td></tr>')
    th = (f'{SMALL}font-weight:bold;text-transform:uppercase;letter-spacing:1px;'
          f'color:{NAVY};padding:0 8px 5px 8px;border-bottom:2px solid {NAVY};')
    head = (f'<tr><td style="{th}" colspan="2">You</td><td style="{th}"></td>'
            f'<td style="{th}text-align:right;" colspan="2">'
            f'{esc(report["meta"]["rival_label"])}</td></tr>')
    note = ""
    if as_set:
        note = _note(f'<b>{esc(AS_SET_HEAD)}</b> {esc(AS_SET_BODY)}')
    else:
        gates = {s["confidence_gate"] for s in mine if s.get("confidence_gate")}
        if gates:
            head_text = (f'Why some slots say "{NO_CALL}":' if mixed
                         else f'{NO_CALL.capitalize()} on any slot this week:')
            note = _note(f'<b>{esc(head_text)}</b> '
                         f'{esc(no_call_explainer(" · ".join(sorted(gates))))}')
    table = (f'<table role="presentation" width="100%" cellpadding="0" '
             f'cellspacing="0" border="0">{head}{"".join(rows)}{total}</table>')
    return _sec(4, "The Tape — As Set" if as_set else "The Tape", table + note)


def _fragility(items: list[Mapping[str, Any]], rival_label: str) -> str:
    if not items:
        body = _gate("nothing in their lineup we can call fragile this week")
    else:
        rows = "".join(
            f'<tr><td style="{BASE}font-weight:bold;color:{BRICK};'
            f'padding:8px 10px 8px 0;vertical-align:top;width:20px;">{i + 1}</td>'
            f'<td style="{BASE}padding:8px 0;border-bottom:1px solid {LINE};">'
            f'<b>{esc(item["title"])}</b><br>{esc(item["detail"])} '
            f'<i style="color:{SLATE};">({esc(item["evidence"])})</i></td></tr>'
            for i, item in enumerate(items)
        )
        body = (f'<table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0">{rows}</table>')
    return _sec(5, f"Where {rival_label} Is Fragile", body)


def _regret(regret: Mapping[str, Any]) -> str:
    if "gate" in regret:
        body = (f'<p style="{BASE}font-weight:bold;margin:0 0 6px 0;">'
                f'No coin-flip call published</p>{_gate(regret["gate"])}')
        return _sec(6, "Your Regret Score", body)
    confidence = _pct(regret["confidence"])
    drivers = " · ".join(
        f'{esc(d["label"])} <b>{esc(d["value"])}</b>' for d in regret["drivers"])
    body = (
        f'<div style="background:{PAPER};padding:14px 16px;">'
        f'<div style="font-family:{FONT};font-size:18px;font-weight:bold;'
        f'color:{NAVY};">Start {esc(regret["start_name"])} '
        f'<span style="color:{SLATE};font-weight:normal;">over</span> '
        f'{esc(regret["over_name"])}</div>'
        f'<div style="font-family:{FONT};font-size:24px;font-weight:bold;'
        f'color:{TURF};padding:6px 0;">{confidence}%</div>'
        f'<p style="{SMALL}margin:0 0 6px 0;">{drivers}</p>'
        f'<p style="{SMALL}margin:0;">{esc(regret["definition"])}</p></div>'
    )
    return _sec(6, "Your Regret Score", body)


def _pivots(plans: list[Mapping[str, Any]]) -> str:
    if not plans:
        body = _gate("no pivots this week — no starter we can check is "
                     "listed questionable")
    else:
        rows = "".join(
            f'<tr><td style="{BASE}font-weight:bold;color:{SLATE};'
            f'padding:7px 10px 7px 0;vertical-align:top;">If</td>'
            f'<td style="{BASE}padding:7px 0;border-bottom:1px solid {LINE};">'
            f'{esc(p["condition"])}<br><b>→ {esc(p["action"])}</b></td></tr>'
            for p in plans
        )
        body = (f'<table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0">{rows}</table>')
    return _sec(7, "Pivot Plan — Set It, Forget It", body)


def _bid_line(entry: Mapping[str, Any]) -> str:
    bid = entry.get("bid_to_beat")
    if not bid:
        return ""
    who = who_can_cover(entry.get("rivals_who_can_pay"),
                        entry.get("league_others"))
    if entry.get("affordable") is False:
        left = entry.get("my_remaining")
        return (f'<p style="{BASE}color:{BRICK};margin:6px 0 0 0;">→ It takes '
                f'<b>{esc(bid)}</b> to top the highest bid he\'s drawn, and you '
                f'have <b>{esc(left)}</b> left. You can\'t win this one — keep '
                f'your budget for a player you can actually land.</p>')
    appetite = entry.get("league_top_appetite")
    tail = ""
    if appetite and appetite > bid:
        tail = (f' If someone really wants him, the biggest bid anyone still '
                f'funded has ever made is {esc(appetite)}.')
    return (f'<p style="{BASE}color:{TURF};margin:6px 0 0 0;">→ Bid '
            f'<b>{esc(bid)}</b> or more to top the highest bid he has drawn '
            f'here — {esc(who)}.{tail}</p>')


def _hype(entries: list[Mapping[str, Any]],
          market: Mapping[str, Any] | None) -> str:
    if not entries:
        body = _gate("a quiet waiver week — no sign of a league-wide chase "
                     "in your league's transaction log")
    else:
        gates = [entry.get("verdict_gate") for entry in entries]
        shared_gate = gates[0] if len(set(gates)) == 1 and gates[0] else None
        cards = []
        for entry in entries:
            bid = entry.get("top_bid")
            bid_text = (f'top bid {bid}' + (
                f' of {entry["faab_budget"]} FAAB'
                if entry.get("faab_budget") else "")
                if bid is not None else "no FAAB bids recorded")
            gate_line = ("" if shared_gate else
                         f'<p style="{BASE}margin:6px 0 0 0;">'
                         f'→ {esc(entry["verdict_gate"])}</p>')
            usage_html = (f'<p style="{BASE}margin:6px 0 0 0;font-weight:bold;">'
                          f'{esc(entry["usage"])}</p>' if entry.get("usage") else "")
            cards.append(
                f'<div style="background:{PAPER};padding:12px 14px;'
                f'margin-top:10px;">'
                f'<div style="{BASE}font-weight:bold;">'
                f'{esc(entry["player_name"])} · {esc(entry["position"])} '
                f'<span style="{SMALL}font-weight:normal;">— '
                f'{esc(entry["managers_chasing"])} managers chasing</span></div>'
                f'<p style="{BASE}margin:6px 0 0 0;">{esc(entry["bids"])} claims '
                f'filed, {esc(entry["completed_adds"])} completed, '
                f'{esc(bid_text)} ({esc(entry["evidence"])}).</p>'
                f'{usage_html}{gate_line}{_bid_line(entry)}</div>'
            )
        note = _note(esc(shared_gate)) if shared_gate else ""
        body = "".join(cards) + note
    return _sec(8, "Waiver Hype Meter", body) + _waiver_market(market)


def _waiver_market(market: Mapping[str, Any] | None) -> str:
    if not market:
        return ""
    bits = []
    if market.get("going_rate") is not None:
        bits.append(f'Going rate <b>{esc(market["going_rate"])} FAAB</b>')
    if market.get("top_winning_bid") is not None:
        bits.append(f'Priciest win <b>{esc(market["top_winning_bid"])}</b>')
    if market.get("my_remaining") is not None:
        bits.append(f'You have <b>{esc(market["my_remaining"])}</b> left')
    if market.get("rival_remaining") is not None:
        bits.append(f'{esc(market["rival_label"])} has '
                    f'<b>{esc(market["rival_remaining"])}</b>')
    if market.get("rival_top_bid_shown"):
        bits.append(f'They\'ve gone as high as '
                    f'<b>{esc(market["rival_top_bid_shown"])}</b>')
    if not bits:
        return ""
    parts = [f'<p style="{BASE}margin:0;">{" · ".join(bits)}</p>']
    lost = market.get("rival_claims_lost") or 0
    if lost:
        parts.append(
            f'<p style="{BASE}margin:8px 0 0 0;">{esc(market["rival_label"])} '
            f'has lost <b>{esc(lost)}</b> claim{"s" if lost != 1 else ""} this '
            f'season — every one of those is a price they were willing to pay '
            f'and didn\'t get.</p>')
    if market.get("budget_note"):
        parts.append(f'<p style="{SMALL}margin:8px 0 0 0;">'
                     f'{esc(market["budget_note"])}</p>')
    parts.append(f'<p style="{SMALL}margin:8px 0 0 0;">'
                 f'{esc(market.get("evidence", ""))}</p>')
    return _sec(0, "The Waiver Market In Your League", "".join(parts))


def _receipts(receipts: Mapping[str, Any]) -> str:
    record = receipts.get("record")
    if not record:
        inner = (f'{esc(receipts.get("note", ""))}<br>'
                 f'<span style="{SMALL}text-transform:uppercase;'
                 f'letter-spacing:1px;">Ledger opens · this week</span>')
    else:
        parts = [esc(receipts.get("note", ""))]
        best, worst = receipts.get("best_call"), receipts.get("worst_call")
        if best:
            parts.append(
                f' Best call: <b>{esc(best["recommended"])} over '
                f'{esc(best["over"])}</b> (week {esc(best["week"])}, '
                f'+{best["margin"]:.1f}).')
        if worst:
            parts.append(
                f' Worst: {esc(worst["recommended"])} over {esc(worst["over"])} '
                f'(week {esc(worst["week"])}, {worst["margin"]:.1f}). '
                f'Both stay on the ledger.')
        inner = ("".join(parts)
                 + f'<br><span style="{SMALL}text-transform:uppercase;'
                   f'letter-spacing:1px;">Graded on real box scores</span>')
    return _sec(9, "The Receipts", f'<p style="{BASE}margin:0;">{inner}</p>')


def _footer(meta: Mapping[str, Any]) -> str:
    basis = availability_basis(meta)
    return (
        f'<tr><td style="background:{PAPER};padding:20px 28px 26px 28px;'
        f'margin-top:24px;">'
        f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — '
        f'{esc(BRAND_LINE)}<br>{esc(basis)}<br>'
        f'{_forward_line()}'
        f'{esc(NO_BETTING_LINE)}<br>'
        f'{esc(source_line(meta))}<br>'
        f'<b>{esc(CANCEL_HEAD)}</b> {esc(CANCEL_BODY)}</p></td></tr>'
    )


def _your_week(matchup: Mapping[str, Any], no_opponent: str | None) -> str:
    """Your projected week. Half a scoreboard reads as a broken scoreboard, so
    a solo report shows one number and its range rather than an empty VS."""
    you = matchup["you"]
    gate = matchup.get("range_gate")
    if gate:
        body = _gate(gate)
    else:
        body = (
            f'<div style="{BASE}"><b>{esc(you["label"])}</b></div>'
            f'<div style="font-family:{DISPLAY};font-size:34px;font-weight:bold;'
            f'color:{TURF};line-height:1.1;">{you["projected_total"]:.1f}'
            f'<span style="{SMALL}font-size:12px;color:{SLATE};"> PROJ</span></div>'
            f'<div style="{SMALL}">{you["floor"]:.0f} – {you["ceiling"]:.0f} '
            f'realistic range</div>')
        if matchup.get("range_basis"):
            body += f'<div style="{SMALL}margin-top:6px;">{esc(matchup["range_basis"])}</div>'
    if no_opponent:
        body += f'<p style="{SMALL}margin:12px 0 0 0;">{esc(no_opponent)}</p>'
    return _sec(2, "Your Week", body)


def _your_lineup(report: Mapping[str, Any]) -> str:
    """The solo lineup: slot, player, projection, call. No tint, because a tint
    is a comparison and there is no opponent to compare against."""
    slots = report["lineup"]
    mixed = any(s.get("confidence") is not None for s in slots)
    rows = []
    for slot in slots:
        name = slot.get("player_name") or "—"
        proj = f'{slot["projected"]:.1f}' if slot.get("projected") is not None else "—"
        bits = [b for b in (edge_phrase(slot), slot.get("usage")) if b]
        flags = [esc(f["text"]) for f in (slot.get("flags") or [])]
        confidence = slot.get("confidence")
        if confidence is not None:
            call = f'<b style="color:{TURF};">{_pct(confidence)}%</b>'
        elif mixed and slot.get("player_name"):
            call = f'<span style="{SMALL}">{esc(NO_CALL)}</span>'
        else:
            call = ""
        cell = f'{BASE}padding:7px 8px;border-bottom:1px solid {LINE};'
        rows.append(
            f'<tr><td style="{cell}{SMALL}font-weight:bold;white-space:nowrap;">'
            f'{esc(slot["slot"])}</td>'
            f'<td style="{cell}"><b>{esc(name)}</b>'
            + (f'<br><span style="{SMALL}color:{BRICK};font-weight:bold;">'
               f'{" · ".join(flags)}</span>' if flags else "")
            + (f'<br><span style="{SMALL}">{esc(" · ".join(str(b) for b in bits))}'
               f'</span>' if bits else "")
            + f'</td><td style="{cell}text-align:right;font-weight:bold;'
            f'white-space:nowrap;">{proj}</td>'
            f'<td style="{cell}text-align:right;white-space:nowrap;">{call}</td></tr>')
    th = (f'{SMALL}font-weight:bold;text-transform:uppercase;letter-spacing:1px;'
          f'color:{NAVY};padding:0 8px 5px 8px;border-bottom:2px solid {NAVY};')
    head = (f'<tr><td style="{th}"></td><td style="{th}">Your lineup</td>'
            f'<td style="{th}text-align:right;">Proj</td>'
            f'<td style="{th}text-align:right;">Call</td></tr>')
    note = ""
    gates = {s["confidence_gate"] for s in slots if s.get("confidence_gate")}
    if gates:
        head_text = (f'Why some slots say "{NO_CALL}":' if mixed
                     else f'{NO_CALL.capitalize()} on any slot this week:')
        note = _note(f'<b>{esc(head_text)}</b> '
                     f'{esc(no_call_explainer(" · ".join(sorted(gates))))}')
    table = (f'<table role="presentation" width="100%" cellpadding="0" '
             f'cellspacing="0" border="0">{head}{"".join(rows)}</table>')
    return _sec(3, "The Lineup", table + note)


def _compose(report: Mapping[str, Any]) -> list[str]:
    """Sections in order, per product — the email twin of render.report.compose.

    Kept as a mirror rather than shared code because the two renderers speak
    different dialects (one has CSS, the other cannot), but the SECTION LIST
    must not diverge: a subscriber's email dropping a section the archived HTML
    carries is the drift `test_the_email_carries_what_the_browser_report_carries`
    exists to catch.
    """
    meta = report["meta"]
    if meta.get("solo"):
        return [
            _header(meta),
            _checklist(report["checklist"]),
            _your_week(report["matchup"], report.get("no_opponent")),
            _your_lineup(report),
            _regret(report["regret"]),
            _pivots(report["pivots"]),
            _receipts(report["receipts"]),
        ]
    return [
        _header(meta),
        _checklist(report["checklist"]),
        _last_week(report.get("last_week")),
        _matchup(report["matchup"]),
        _rival_watch(report.get("rival_watch")),
        _tape(report),
        _fragility(report["fragility"], meta["rival_label"]),
        _regret(report["regret"]),
        _pivots(report["pivots"]),
        _hype(report["hype"], report.get("waiver_market")),
        _receipts(report["receipts"]),
    ]


def render_email(report: Mapping[str, Any]) -> str:
    """The full report as a self-contained, email-safe HTML document."""
    meta = report["meta"]
    # The preheader is the preview line an inbox shows BEFORE the mail is
    # opened, so it is the most-read sentence the product ships. The solo
    # version used to read "The file on None: your lineup, their fragile
    # spots..." — an absent value printed as a word, promising two things this
    # product does not do.
    preheader = (
        'Your lineup for the week, the one call worth arguing about, and who is '
        'actually earning the ball.'
        if meta.get("solo") else
        f'The file on {meta["rival_label"]}: your lineup, their fragile spots, '
        f'and the one call that matters.')
    sections = "".join(_compose(report) + [
        # breathing room between the last section and the footer band
        '<tr><td style="padding:12px;"></td></tr>',
        _footer(meta),
    ])
    sections = number_sections(sections)
    title = (f'Beat Your League — Week {esc(meta["week"])} '
             f'{"Report" if meta.get("solo") else "Rival Report"}')
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>{title}</title>\n</head>\n'
        f'<body style="margin:0;padding:0;background:{PAPER};">\n'
        f'<div style="display:none;max-height:0;overflow:hidden;">'
        f'{esc(preheader)}</div>\n'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:18px 8px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:600px;width:100%;background:{CARD};">'
        f'{sections}</table></td></tr></table>\n</body>\n</html>\n'
    )
