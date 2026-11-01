"""One team's season, from the reports it was sent.

Everything here is what happened: the calls its reports printed, graded by the
same rules as the weekly results (engine/own_record.py), and how its starters
scored in the lineups we set. Misses sit beside hits. Nothing predicts next
season, and no new probability is computed.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from engine.decisions import HIT, MISS
from engine.own_record import NO_RESULT, graded_calls
from engine.projection import printed_percent
from engine.scoring import ScoringRule, score

# The bands a buyer can read: what we said, and how those landed.
BANDS = (("70% or higher", 70, 101), ("60–69%", 60, 70), ("Under 60%", 0, 60))
TOP_SCORERS = 3


def _band_rows(calls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for label, low, high in BANDS:
        inside = [c for c in calls
                  if low <= printed_percent(c["confidence"]) < high]
        if inside:
            rows.append({"label": label, "calls": len(inside),
                         "hits": sum(1 for c in inside if c["outcome"] == HIT)})
    return rows


def _margin(call: Mapping[str, Any]) -> float:
    return abs(float(call["got"]) - float(call["other"]))


def _call(call: Mapping[str, Any]) -> dict[str, Any]:
    return {"week": call["week"], "pick": call["pick_name"], "over": call["over_name"],
            "got": call["got"], "other": call["other"],
            "percent": printed_percent(call["confidence"])}


def _top_scorers(plans: Sequence[Mapping[str, Any]],
                 weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
                 rule: ScoringRule) -> list[dict[str, Any]]:
    """Who scored most in the lineups we set. A team defense is scored by its
    own rule and is left out rather than scored as a player."""
    totals: dict[str, dict[str, Any]] = {}
    for plan in plans:
        rows = weekly.get(int(plan["week"]))
        if not rows:
            continue
        names = plan.get("players") or {}
        for slot in plan.get("slots") or []:
            pid = slot.get("player_id")
            if not pid or slot.get("slot") == "DEF" or pid not in names:
                continue
            row = rows.get(pid)
            entry = totals.setdefault(pid, {"name": names[pid].get("name") or pid,
                                            "points": 0.0, "starts": 0})
            entry["points"] += score(row, rule) if row else 0.0
            entry["starts"] += 1
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1]["points"], kv[0]))
    return [{**entry, "points": round(entry["points"], 1)}
            for _pid, entry in ranked[:TOP_SCORERS] if entry["points"] > 0]


def review_team(plans: Sequence[Mapping[str, Any]],
                weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
                rule: ScoringRule) -> dict[str, Any] | None:
    """One team's review, or None when no report of it reached a graded week."""
    played = sorted(int(p["week"]) for p in plans if weekly.get(int(p["week"])))
    if not played:
        return None
    graded = graded_calls(plans, weekly, rule, max(played) + 1)
    decided = [c for c in graded if c["outcome"] != NO_RESULT]
    hits = [c for c in decided if c["outcome"] == HIT]
    misses = [c for c in decided if c["outcome"] == MISS]
    return {"weeks": len(played), "first_week": played[0], "last_week": played[-1],
            "calls": len(decided), "hits": len(hits), "no_result": len(graded) - len(decided),
            "bands": _band_rows(decided),
            "best_call": _call(max(hits, key=_margin)) if hits else None,
            "worst_miss": _call(max(misses, key=_margin)) if misses else None,
            "top_scorers": _top_scorers(plans, weekly, rule)}
