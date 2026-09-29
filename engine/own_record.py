"""The Receipts, made personal: the calls in THIS subscriber's reports, graded.

The section used to promise "Your results start here" and then, once the
ledger filled, report every call recorded under that scoring preset — the
calls in every subscriber's report, counted as if they were yours. The shared
ledger is the right PUBLIC record (principle 2); it is the wrong thing to
call somebody's own.

Each Tuesday the run stores the calls a report printed (``run/saturday.py``
``build_plan``). This reads those back for the weeks before the current one
and grades each against that week's box score under the subscriber's own
scoring rule, by the ledger's rules: a player with no stat row scored 0.0 (he
did not play, which is what his slot produced), a 0.0-0.0 pair is a void, not
a result, and a tie decides nothing. Misses are shown beside hits, every week.
Only weeks whose box scores are in are graded — the caller passes weeks the
Tuesday run has already checked are complete.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from engine.decisions import HIT, MISS, grade
from engine.scoring import ScoringRule, score

EMPTY_NOTE = ("Your results start here: once this week's games are final, every "
              "call shows up with how it played out.")
ASK = ("Good week? Reply and tell us how it went — we read every one, and with "
       "your OK we may quote you.")


def _points(rows: Mapping[str, Mapping[str, Any]], player_id: str,
            rule: ScoringRule) -> float:
    row = rows.get(player_id)
    return score(row, rule) if row else 0.0


def own_record(plans: Sequence[Mapping[str, Any]],
               weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
               rule: ScoringRule, before_week: int) -> dict[str, Any]:
    """The receipts section for one subscriber, from their stored plans."""
    graded: list[dict[str, Any]] = []
    for plan in sorted(plans, key=lambda p: int(p["week"])):
        week = int(plan["week"])
        if week >= before_week:
            continue
        rows = weekly.get(week)
        if not rows:
            continue                       # no box scores: nothing to grade
        for call in plan.get("calls") or []:
            got = _points(rows, call["pick"], rule)
            other = _points(rows, call["over"], rule)
            if got == 0.0 and other == 0.0:
                continue                   # a void, never a result (RULE L3)
            outcome = grade(got, other)
            if outcome not in (HIT, MISS):
                continue
            graded.append({**call, "week": week, "got": round(got, 1),
                           "other": round(other, 1), "outcome": outcome})
    if not graded:
        return {"record": None, "note": EMPTY_NOTE}
    hits = sum(1 for c in graded if c["outcome"] == HIT)
    weeks = sorted({c["week"] for c in graded})
    span = (f"week {weeks[0]}" if len(weeks) == 1
            else f"weeks {weeks[0]}–{weeks[-1]}")
    last = weeks[-1]
    last_calls = [c for c in graded if c["week"] == last]
    last_hits = sum(1 for c in last_calls if c["outcome"] == HIT)
    note = (f"Your calls so far: {hits} of {len(graded)} came in ({span}). "
            f"Week {last}: {last_hits} of {len(last_calls)}.")
    return {
        "record": {"graded": len(graded), "hits": hits,
                   "first_week": weeks[0], "last_week": last},
        "note": note,
        "last_week": last,
        "last_week_calls": [
            {"text": f"{c['pick_name']} over {c['over_name']} at {c['slot']}",
             "confidence": c.get("confidence"), "got": c["got"],
             "other": c["other"], "outcome": c["outcome"]}
            for c in last_calls],
        "ask": ASK if last_hits > len(last_calls) - last_hits else None,
    }


def call_line(call: Mapping[str, Any]) -> str:
    """One graded call, the same words on every surface."""
    pct = (f" · {round(call['confidence'] * 100)}%"
           if call.get("confidence") is not None else "")
    verdict = "came in" if call["outcome"] == HIT else "missed"
    return (f"{call['text']}{pct} — {call['got']:.1f} to {call['other']:.1f}, "
            f"{verdict}")
