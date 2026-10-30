"""One model of the weekly report, for every surface that draws it.

The email (render/email.py), the web report (render/report.py), the plain-text
half, the landing's phone and the How it works page all draw the SAME report
in the SAME order with the SAME words (contract C1/C2, Oct 2026). They used
to be mirrors: the email opened on a long checklist and the phone on a
one-screen lineup, so the thing sold and the thing delivered looked like two
products. Now each surface asks this module what a card says and only decides
how to draw it.

Pure: no I/O, and every value is a plain dict, list, tuple or UNESCAPED
string. Every renderer escapes. Nothing here computes a number — every figure
is the engine's, formatted the way every surface already printed it; the one
derived quantity is a bar's width, drawn from the PRINTED percentage
(render.report.bar_from_even) so that no two surfaces can draw one call two
lengths.

Order (C1): masthead, bands, alerts, then the numbered cards —
01 Your Lineup, Decided · 02 The Week's Closest Call · 03 Your Game Plan ·
04 If/Then for Gameday · 05 Slot by Slot · 06 Rising Roles · 07 The Receipts.
The order keeps the engine's own words true: "Your if/then below…" sits in
the game plan, above the if/then; "The lineup below flags who" (the range
gates) and "Every call below is your starter against your own bench" sit at
the top of card 01, above its rows; the receipts' "call above with odds…"
comes last.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from render import report as rr

SECTION_ORDER = ("lineup", "closest", "plan", "ifthen", "slots", "rising", "receipts")

TITLES = {
    "lineup": "Your Lineup, Decided",
    "closest": "The Week's Closest Call",
    "plan": "Your Game Plan",
    "ifthen": "If/Then for Gameday",
    "slots": "Slot by Slot",
    "rising": rr.RISING_HEAD,
    "receipts": "The Receipts",
}
# Week 1 carries an ORDERING, not a decision (render.email.solo_promise): the
# card's title says so, as the subject does.
OPENING_TITLE = "Your Opening Lineup"

# An action longer than this splits at its first " — " into a bold head and a
# plain rest, so a two-clause instruction reads as one instruction and its
# reason. Never at ". ": "Amon-Ra St. Brown" would break.
SPLIT_OVER = 80
NOTHING_TO_CHANGE = "nothing to change"
FIRST_KICKOFF = "before this week's first kickoff"
# A starter's game before Sunday's main slot gets its own plan item, dated
# (engine.solo_report.early_game_items): "before Thursday's kickoff", or
# "before Sunday's 9:30 AM ET kickoff" for London.
_EARLY = re.compile(r"^before (?:(?:Wednesday|Thursday|Friday|Saturday)'s"
                    r"|Sunday's \d{1,2}:\d\d [AP]M ET) kickoff$")


def early_week(report: Mapping[str, Any]) -> bool:
    """Does a starter kick off before Sunday's main slot? Then the week's first
    kickoff is that early too, so "before this week's first kickoff" is the
    same moment the early game's own item prints as due — one moment, one
    colour (review SLEEK-8: the lineup's chip read green on card 01 while
    "Thursday night: … set your lineup before then" read red on card 03,
    both Thursday 8:15 PM ET)."""
    return any(e.get("urgency") == "deadline" and _EARLY.match(str(e.get("deadline") or ""))
               for e in report.get("checklist") or [])


# --------------------------------------------------------------------- #
# small facts about a report
# --------------------------------------------------------------------- #

def _lineup(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(report.get("lineup") or [])


def any_odds(report: Mapping[str, Any]) -> bool:
    """Does any lineup row print a %? (the "mixed" week of the renderers)."""
    return any(s.get("confidence") is not None for s in _lineup(report))


def any_projection(report: Mapping[str, Any]) -> bool:
    """Week 1 has none: the lineup is an ordering (render.email.solo_promise)."""
    return any(s.get("projected") is not None for s in _lineup(report))


def is_set_lineup(item: Mapping[str, Any]) -> bool:
    """The game plan's "Set this lineup" item. Tagged by the engine
    (engine.week_report._set_lineup_item, "kind": "set_lineup"); a report
    built before the tag existed is recognised by its own words."""
    kind = item.get("kind")
    if kind:
        return kind == "set_lineup"
    return (str(item.get("action") or "").startswith("Set this lineup")
            and bool(item.get("detail")))


def is_certain_zero(item: Mapping[str, Any]) -> bool:
    """A spot that scores zero unless the reader acts (render.email.empty_spots)."""
    return bool((item.get("zero") or {}).get("certain"))


def _fmt(value: Any) -> str | None:
    return f"{value:.1f}" if value is not None else None


# --------------------------------------------------------------------- #
# the pieces every card is built from
# --------------------------------------------------------------------- #

def item(entry: Mapping[str, Any], early: bool = False) -> dict[str, Any]:
    """One checklist item: {head, rest, detail, deadline, tone, box}.

    ``tone`` is "ok" for a deadline already in hand (the web's .dl.ok, turf)
    and "due" for one still to meet (brick). ``box`` is False for an item
    with nothing to do ("nothing to change"): a box to tick beside it would
    ask for an action the item says is not needed. ``early`` (``early_week``):
    a starter kicks off before Sunday's main slot, so the week's first kickoff
    is a deadline still to meet and prints as one."""
    action = str(entry.get("action") or "")
    head, rest = action, ""
    if len(action) > SPLIT_OVER and " — " in action:
        first, after = action.split(" — ", 1)
        head, rest = first, f" — {after}"
    deadline = str(entry.get("deadline") or "")
    return {
        "head": head,
        "rest": rest,
        "detail": entry.get("detail") or None,
        "deadline": deadline,
        "tone": ("due" if early and deadline == FIRST_KICKOFF else
                 "ok" if entry.get("urgency") in ("now", "done") else "due"),
        "box": deadline != NOTHING_TO_CHANGE,
    }


def masthead(report: Mapping[str, Any]) -> dict[str, Any]:
    """The navy masthead: the lockup, what this is, the week, whose team, and
    when it was built."""
    meta = report["meta"]
    solo = bool(meta.get("solo"))
    team = rr.team_name(report) or meta.get("league_name") or ""
    bits = [f"{meta.get('num_teams')} teams"]
    if meta.get("scoring"):
        bits.append(str(meta["scoring"]))
    extra: list[tuple[str, str]] = []
    if not solo:
        # The retired league product's lines, kept for its archive renders.
        if meta.get("rivalry_week"):
            extra.append(("", "RIVALRY WEEK"))
        if meta.get("rival_label"):
            extra.append(("This week: ", str(meta["rival_label"])))
        if meta.get("named_rival_label") and not meta.get("rivalry_week"):
            extra.append(("Rival: ", str(meta["named_rival_label"])))
    return {
        "brand": "Beat Your League",
        "label": "Your Report" if solo else "Rival Report",
        "week": f"Week {meta.get('week')}",
        "team": str(team),
        "meta": " · ".join(bits),
        "stamp": rr._generated_stamp(meta),
        "extra": extra,
    }


def bands(report: Mapping[str, Any]) -> list[dict[str, str]]:
    """The notices above the cards, with today's words byte for byte: the
    sample's (or this week's) banner, the free report's, the season's end.

    {kind, head, text}: a renderer prints ``head`` bold, then a space, then
    ``text``; an empty head prints the text alone. A free report's band also
    carries its price line and the join link (``price``, ``link``)."""
    meta = report["meta"]
    out: list[dict[str, Any]] = []
    if meta.get("live_demo"):
        if meta.get("rebuilt_after_kickoff"):
            out.append({"kind": "sample", "head": "THIS WEEK'S REPORT", "text": (
                f"— Week {meta['week']} of the {meta['season']} season for a "
                f"sample roster, rebuilt {rr._built_on(meta)} from this week's "
                f"Tuesday information (the week {int(meta['week']) - 1} injury "
                f"report); later injury news is not in it.")})
        else:
            out.append({"kind": "sample", "head": "THIS WEEK'S REPORT", "text": (
                f"— Week {meta['week']} of the {meta['season']} season, built "
                f"{rr._built_on(meta)} for a sample roster, exactly the way yours "
                f"is built. Rebuilt every Tuesday of the season.")})
    elif meta.get("historical_demo") and meta.get("solo"):
        scoring = str(meta.get("scoring") or "")
        scored = (f"scored {scoring[:1].lower()}{scoring[1:]}" if scoring
                  else "one scoring setting")
        if meta.get("first_week_demo"):
            text = (f"— Week 1 of the {meta['season']} NFL season, built the way "
                    f"yours will be: one roster, {scored}. Before Week 1 no game "
                    f"has been played and no injury report exists, so the slots "
                    f"are ordered by last season's scoring and no odds print.")
        else:
            text = (f"— a real week from the {meta['season']} NFL season, built "
                    f"the way yours will be: one roster, {scored}, from the box "
                    f"scores and injury report out before that week's games.")
        out.append({"kind": "sample", "head": "SAMPLE REPORT", "text": text})
    elif meta.get("historical_demo"):
        out.append({"kind": "sample", "head": "", "text": (
            f"SAMPLE REPORT — real data from the {meta['season']} season of "
            f"{meta['league_name']}, built to show exactly what lands in your inbox "
            f"on a Tuesday. Because it's a past season we can't check who was hurt or "
            f"inactive back then, so the confidence numbers are left off — in a live week "
            f"you get them on every slot where both players are confirmed active."
            + (" Team and manager names here are placeholders; every number is that "
               "league's real record." if meta.get("anonymized_demo") else ""))})
    if meta.get("trial") and not meta.get("historical_demo"):
        from render.email import (TRIAL_BUTTON, TRIAL_HEAD, TRIAL_INTRO,
                                  trial_join_url, trial_price_line)
        price = trial_price_line(meta)
        url = trial_join_url(meta) if price else None
        out.append({"kind": "trial", "head": f"{TRIAL_HEAD}.", "text": TRIAL_INTRO,
                    "price": price, "link": (url, TRIAL_BUTTON) if url else None})
    season_end = rr.season_end_lines(meta)
    if season_end:
        out.append({"kind": "season_end", "head": f"{rr.SEASON_END_HEAD}.",
                    "text": " ".join(season_end)})
    return out


def alerts(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The checklist items that leave a spot empty for certain: they lead the
    report, above the lineup, in the alert tint. Still tasks to tick."""
    early = early_week(report)
    return [item(i, early) for i in report.get("checklist") or [] if is_certain_zero(i)]


CHECKED_HEAD = "Checked for you:"


def checked_line(report: Mapping[str, Any]) -> str | None:
    """What this report checked for this roster, in counts the report itself
    holds (Oct 25 2026: the weakest answer to "why pay when rankings are
    free" was that the work was invisible). Facts only: the roster it read,
    the slots it filled, the kickoffs it timed, the injury report it read
    and, on a live week, the byes ahead. Never a claim about the outcome."""
    rows = list(_lineup(report))
    bench = list(report.get("bench") or [])
    if not rows:
        return None
    players = sum(1 for r in rows if r.get("player_name")) + \
        sum(1 for b in bench if b.get("name") or b.get("player_name"))
    parts = [f"{players} players", f"{len(rows)} slots", "every kickoff time"]
    found = re.search(r"the week (\d+) injury report",
                      str((report.get("meta") or {}).get("availability_as_of") or ""))
    if found:
        parts.append(f"the Week {found.group(1)} injury report")
    if not (report.get("meta") or {}).get("historical_demo"):
        parts.append("the byes still ahead")
    return ", ".join(parts[:-1]) + " and " + parts[-1] + "."


def lineup(report: Mapping[str, Any]) -> dict[str, Any]:
    """Card 01: every starter, decided — his projection, the odds where they
    are earned, the week's total and range, and one box to tick."""
    rows_in = _lineup(report)
    mixed = any_odds(report)
    projected = any_projection(report)
    matchup = report.get("matchup") or {}
    you = matchup.get("you") or {}
    gate = matchup.get("range_gate") or None
    week = None
    if not gate and you.get("projected_total") is not None \
            and you.get("floor") is not None and you.get("ceiling") is not None:
        week = {"total": f"{you['projected_total']:.1f}",
                "range": rr.range_text(you),
                "range_label": rr.RANGE_LABEL}
    rows = []
    for i, slot in enumerate(rows_in):
        conf = slot.get("confidence")
        pct = rr._pct(conf) if conf is not None else None
        label, tone = None, None
        out_flag = next((f.get("text") for f in slot.get("flags") or []
                         if f.get("kind") == "out" and f.get("text")), None)
        if out_flag:
            label, tone = str(out_flag), "flag"
        elif conf is None and slot.get("player_name") and rr.row_marked(slot, mixed):
            label = rr.row_label(slot) or None
            alarming = any(f.get("kind") != "seeded" for f in slot.get("flags") or [])
            # The starter's own doubt leads his row (review SLEEK-2): a
            # questionable starter whose bench option is held read only
            # "De'Von Achane can't play", in red, so the colour accused the
            # row while the words named somebody else, and his own status
            # was nowhere on the card. Card 05 and the plain-text half print
            # the flag itself.
            own = any(f.get("kind") == "questionable" for f in slot.get("flags") or [])
            if own and label and not label.startswith(("questionable", "status open")):
                label = f"questionable · {label}"
            tone = "flag" if alarming else "muted"
        elif not projected and slot.get("usage"):
            label, tone = str(slot["usage"]), "basis"
        if label and tone != "basis":
            # Sentence case on every surface (web, email, phone): the reason
            # used to print in tracked capitals ("NO BENCH QB") and read as an
            # error code. Casing only; the words are row_label's.
            label = label[:1].upper() + label[1:]
        rows.append({
            "i": i,
            "slot": rr.SLOT_DISPLAY.get(slot.get("slot"), slot.get("slot")),
            "name": slot.get("player_name") or "—",
            "proj": _fmt(slot.get("projected")),
            "pct": pct,
            "bar": rr.bar_from_even(pct) if pct is not None else None,
            "label": label,
            "tone": tone if label else None,
        })
    task = next((item(i, early_week(report)) for i in report.get("checklist") or []
                 if is_set_lineup(i)), None)
    legend: list[dict[str, Any]] = []
    if mixed:
        legend.append({"head": None, "text": rr.ODDS_DEFINITION})
    if week:
        legend.append({"head": f"{rr.RANGE_LABEL.capitalize()}:",
                       "text": rr.RANGE_DEFINITION})
    checked = checked_line(report)
    if checked:
        legend.append({"head": CHECKED_HEAD, "text": checked})
    return {
        "title": TITLES["lineup"] if projected else OPENING_TITLE,
        "week": week,
        "gate": gate,
        "basis": matchup.get("range_basis") or None,
        "note": (report.get("no_opponent") or None) if not mixed else None,
        "heads": None if not projected else ("proj+odds" if mixed else "proj"),
        "rows": rows,
        "task": task,
        "legend": legend,
    }


def closest(report: Mapping[str, Any]) -> dict[str, Any]:
    """Card 02: the week's closest call with odds, explained — or, with no
    call, the one line that says so and names the closest decision."""
    regret = report.get("regret") or {}
    if "gate" in regret or regret.get("confidence") is None:
        return {"title": TITLES["closest"], "gate": rr.no_call_line(regret)}
    pct = rr._pct(regret["confidence"])
    return {
        "title": TITLES["closest"],
        "label": regret.get("label") or None,
        "start": regret.get("start_name"),
        "over": regret.get("over_name"),
        "verdict": rr.regret_verdict(regret),
        "tossup": rr.regret_tossup(regret),
        "pct": pct,
        "bar": rr.bar_from_even(pct),
        "drivers": [(str(d["label"]), str(d["value"])) for d in regret.get("drivers") or []],
        "lines": [str(regret[key]) for key in ("definition", "reason") if regret.get(key)],
        "closer": regret.get("closer") or None,
    }


def plan(report: Mapping[str, Any]) -> dict[str, Any]:
    """Card 03: what to do and by when — every checklist item except the
    lineup itself (card 01 carries it) and the certain zeros (the alerts)."""
    early = early_week(report)
    items = [item(i, early) for i in report.get("checklist") or []
             if not is_set_lineup(i) and not is_certain_zero(i)]
    return {"title": TITLES["plan"], "items": items,
            "saturday": rr.SATURDAY_LINE if rr.saturday_line(report.get("meta")) else None}


def ifthen(report: Mapping[str, Any]) -> dict[str, Any]:
    """Card 04: the plan if a questionable starter sits. Each "then" is split
    after its first sentence that closes a bracket ("…(projects 9.5).") so the
    move reads first and its reason after."""
    meta = report.get("meta") or {}
    plans = []
    for entry in report.get("pivots") or []:
        action = rr.pivot_action(entry, meta)
        cut = action.find("). ")
        then, rest = (action[:cut + 2], action[cut + 3:]) if cut >= 0 else (action, "")
        plans.append({"if": f"If {entry['condition']}", "then": then, "rest": rest})
    return {"title": TITLES["ifthen"], "plans": plans,
            "empty": report.get("pivots_note") or rr.NO_PIVOTS}


def slots(report: Mapping[str, Any]) -> dict[str, Any]:
    """Card 05: the reasoning behind every slot, one fact a line, and the
    rest of the roster. No % here: the odds are card 01's."""
    rows_in = _lineup(report)
    mixed = any_odds(report)
    meta = report.get("meta") or {}
    rows, shown_marker = [], False
    for i, slot in enumerate(rows_in):
        marked = (slot.get("confidence") is None and bool(slot.get("player_name"))
                  and rr.row_marked(slot, mixed))
        shown_marker = shown_marker or marked
        label = rr.row_label(slot) if marked else ""
        call = " · ".join(b for b in [label, *rr.call_bits(slot)] if b)
        rows.append({
            "i": i,
            "slot": rr.SLOT_DISPLAY.get(slot.get("slot"), slot.get("slot")),
            "name": slot.get("player_name") or "—",
            "game": slot.get("game") or None,
            "flags": [str(f["text"]) for f in slot.get("flags") or [] if f.get("text")],
            "call": call or None,
            "form": rr.form_phrase(slot) or None,
            "usage": short_usage(slot.get("usage")) or None,
            "usage_full": slot.get("usage") or None,
            "reason": slot.get("reason") or None,
            "proj": _fmt(slot.get("projected")),
        })
    bench = []
    for entry in report.get("bench") or []:
        out = bool(entry.get("out"))
        rank = entry.get("last_season_rank")
        bench.append({
            "position": rr.SLOT_DISPLAY.get(entry.get("position"), entry.get("position")),
            "name": entry.get("name") or "—",
            "game": entry.get("game") or None,
            "form": rr.bench_form(entry) if rr.bench_shows_form(entry) else None,
            "note": (rr.bench_phrase(entry) if out else entry.get("note")) or None,
            "rank": (f"{rank} last season" if (not out and entry.get("notable") and rank)
                     else None),
            "proj": _fmt(entry.get("projected")),
        })
    notes: list[dict[str, Any]] = []
    gates = rr.note_gates(rows_in)
    if gates:
        notes.append({"head": rr.no_call_head(shown_marker and mixed, mixed),
                      "text": f"{rr.ODDS_RULE} Rows without odds this week: "
                              f"{rr.gate_list(gates)}."})
    hot = rr.projection_note(rows_in)
    if hot:
        notes.append({"head": None, "text": hot})
    if meta.get("seeded"):
        notes.append({"head": None, "text": rr.SEEDED_SECTION_LINE})
    return {"title": TITLES["slots"], "rows": rows, "bench": bench,
            "bench_head": rr.BENCH_HEAD, "notes": notes}


def rising(report: Mapping[str, Any]) -> dict[str, Any] | None:
    """Card 06, or None when nobody is rising (an empty card would advertise
    a feature that found nothing)."""
    rows = list(report.get("rising") or [])
    if not rows:
        return None
    return {"title": TITLES["rising"], "intro": rr.rising_intro(rows),
            "rows": [rr.rising_parts(r) for r in rows]}


def receipts(report: Mapping[str, Any]) -> dict[str, Any] | None:
    """Card 07, today's data passed through — or None on a free report."""
    if (report.get("meta") or {}).get("trial"):
        return None
    return {"title": TITLES["receipts"], "data": dict(report.get("receipts") or {})}


MODELS = {"lineup": lineup, "closest": closest, "plan": plan, "ifthen": ifthen,
          "slots": slots, "rising": rising, "receipts": receipts}


def sections(report: Mapping[str, Any]) -> list[str]:
    """The keys of the numbered cards this report carries, in order."""
    keys = []
    for key in SECTION_ORDER:
        if key == "plan":
            model = plan(report)
            if not model["items"] and not model["saturday"]:
                continue
        elif key in ("rising", "receipts") and MODELS[key](report) is None:
            continue
        keys.append(key)
    return keys


def cards(report: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """[(key, model)] for every card this report carries, in order."""
    return [(key, MODELS[key](report)) for key in sections(report)]


# --------------------------------------------------------------------- #
# usage, said in a phone's width
# --------------------------------------------------------------------- #

_USAGE_LINE = re.compile(r"last (\d+) games?: (.+)")

# A clause below this per-game rate is dropped from the SHORT line when
# another clause remains: "1 carry" over four games printed "0.2 car/g" on a
# receiver's row, clutter that reads as a role (panel review I11). The full
# line, every clause, stays on the browser report.
MIN_SHOWN_RATE = 0.5


def short_usage(text: str | None) -> str | None:
    """engine.usage.usage_line, said in a phone's width and a buyer's words:
    "last 4 games: 34 targets (8.5 a game), 21 carries" ->
    "last 4: 8.5 targets · 5.2 carries a game".

    The same counts over the same window, as per-game rates (launch audit F6),
    spelled out: "tgt/g" and "car/g" were our shorthand, not the reader's
    (panel review I11). A clause it does not recognise returns the whole line
    unchanged. A clause under MIN_SHOWN_RATE goes only when another stays, so
    a line never empties. Week 1's "last season: ..." basis is not a usage
    line and passes through untouched."""
    match = _USAGE_LINE.fullmatch(text or "")
    if not match:
        return text
    games = int(match.group(1))
    parts: list[tuple[float, str]] = []
    for clause in match.group(2).split(", "):
        targets = re.fullmatch(r"\d+ targets? \(([\d.]+) a game\)", clause)
        attempts = re.fullmatch(r"\d+ pass attempts? \(([\d.]+) a game\)", clause)
        carries = re.fullmatch(r"(\d+) carr(?:y|ies)", clause)
        if targets:
            rate = float(targets.group(1))
            parts.append((rate, f"{targets.group(1)} targets"))
        elif attempts:
            # A quarterback's volume (RQ-07): his throws, not a trick-play target.
            rate = float(attempts.group(1))
            parts.append((rate, f"{attempts.group(1)} pass attempts"))
        elif carries and games:
            rate = int(carries.group(1)) / games
            parts.append((rate, f"{rate:.1f} carries"))
        else:
            return text
    shown = [words for rate, words in parts if rate >= MIN_SHOWN_RATE]
    if not shown:
        shown = [max(parts)[1]]
    return f"last {games}: " + " · ".join(shown) + " a game"
