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
from engine.projection import printed_percent
from engine.scoring import ScoringRule, score

# D12: the section is built from this report's OWN calls. It promised "every
# call shows up … from next week" in a week that printed no odds (Week 1 for
# everyone, so Week 2 said it again), on the season's last report (no next
# report exists) and on the samples (nobody's record), and it dropped voids
# and ties without a word.
EMPTY_NOTE = ("Your results start here: once this week's games are final, every "
              "call above with odds shows up in your next report with how it "
              "played out.")
NO_ODDS_NOTE = "No odds this week, so nothing to grade."
LAST_NOTE = ("This is the season's last report, so this week's calls aren't "
             "graded here.")
SAMPLE_NOTE = ("In a subscriber's report, this section lists the calls from "
               "their earlier reports and how each one finished.")
NEXT_STAMP = "Results · from next week"
NO_RESULT = "no result"
ASK = ("Good week? Reply and tell us how it went — we read every one, and with "
       "your OK we may quote you.")


def _points(rows: Mapping[str, Mapping[str, Any]], player_id: str,
            rule: ScoringRule) -> float:
    row = rows.get(player_id)
    return score(row, rule) if row else 0.0


def empty_section(calls_now: int | None, last_report: bool = False
                  ) -> dict[str, Any]:
    """The section with no earlier calls of this subscriber's to grade.

    ``calls_now`` is how many odds THIS report prints; None means no subscriber
    record exists at all (a sample, a free report), which promises nothing."""
    if calls_now is None:
        return {"record": None, "note": SAMPLE_NOTE, "stamp": None}
    if not calls_now:
        return {"record": None, "note": NO_ODDS_NOTE, "stamp": None}
    if last_report:
        return {"record": None, "note": LAST_NOTE, "stamp": None}
    return {"record": None, "note": EMPTY_NOTE, "stamp": NEXT_STAMP}


def own_record(plans: Sequence[Mapping[str, Any]],
               weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
               rule: ScoringRule, before_week: int, *,
               calls_now: int = 1, last_report: bool = False) -> dict[str, Any]:
    """The receipts section for one subscriber, from their stored plans.

    ``calls_now`` (odds this report prints) and ``last_report`` decide what
    the empty section may promise (``empty_section``). A void (neither player
    scored) or a tie is listed as "no result" and counted apart, so every call
    a report printed shows up once its week is graded."""
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
            # A void (RULE L3) or a tie decides nothing: listed, never counted.
            outcome = (NO_RESULT if got == 0.0 and other == 0.0
                       else grade(got, other))
            if outcome not in (HIT, MISS):
                outcome = NO_RESULT
            graded.append({**call, "week": week, "got": round(got, 1),
                           "other": round(other, 1), "outcome": outcome})
    if not graded:
        return empty_section(calls_now, last_report)
    decided = [c for c in graded if c["outcome"] != NO_RESULT]
    hits = sum(1 for c in decided if c["outcome"] == HIT)
    weeks = sorted({c["week"] for c in graded})
    span = (f"week {weeks[0]}" if len(weeks) == 1
            else f"weeks {weeks[0]}–{weeks[-1]}")
    last = weeks[-1]
    last_calls = [c for c in graded if c["week"] == last]
    last_decided = [c for c in last_calls if c["outcome"] != NO_RESULT]
    last_hits = sum(1 for c in last_decided if c["outcome"] == HIT)
    note = (f"Your calls so far: {hits} of {len(decided)} came in"
            f"{_plus(decided, graded)} ({span}). Week {last}: {last_hits} of "
            f"{len(last_decided)}{_plus(last_decided, last_calls)}.")
    return {
        "record": {"graded": len(decided), "hits": hits,
                   "first_week": weeks[0], "last_week": last},
        "note": note,
        "stamp": None,
        "last_week": last,
        "last_week_calls": [
            {"text": f"{c['pick_name']} over {c['over_name']} at {c['slot']}",
             "confidence": c.get("confidence"), "got": c["got"],
             "other": c["other"], "outcome": c["outcome"]}
            for c in last_calls],
        "ask": ASK if last_hits > len(last_decided) - last_hits else None,
    }


def _plus(decided: Sequence[Any], listed: Sequence[Any]) -> str:
    """", plus 1 with no result" when a void or tie is listed beside them."""
    voids = len(listed) - len(decided)
    return f", plus {voids} with no result" if voids else ""


def call_line(call: Mapping[str, Any]) -> str:
    """One graded call, the same words on every surface."""
    pct = (f" · {printed_percent(call['confidence'])}%"
           if call.get("confidence") is not None else "")
    verdict = ("came in" if call["outcome"] == HIT
               else "missed" if call["outcome"] == MISS else NO_RESULT)
    return (f"{call['text']}{pct} — {call['got']:.1f} to {call['other']:.1f}, "
            f"{verdict}")
