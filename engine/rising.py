"""Rising roles — who is getting more of the ball lately, as facts.

After the lineup, the question managers ask most is who to go and get. The
product cannot see a league, so it cannot say who is free; what it CAN say is
who, anywhere in the league, is being given noticeably more than he was — and
leave "is he on my league's free-agent list" to the one person who can see it.

RULE U1 (engine/usage.py) governs: this is a REPORT of counted usage, never a
projection and never a probability. Nothing here is a call, so nothing is
graded and nothing enters the ledger. The line a reader gets is a sentence
about what already happened: "9.5 touches a game over his last two games, up
from 3.0 before."

Definitions, frozen here and pinned by tests:
- **touches** = targets + carries, from the weekly stat rows.
- A player is RISING when, over the two most recent completed weeks, he
  appeared in both, averaged at least MIN_RECENT touches, and averaged at
  least MIN_JUMP more than in his earlier appearances this season (he needs at
  least one). Quarterbacks and kickers are out: their touches mean nothing.
- Sorted by the size of the jump, then by id, so a report is byte-identical
  across runs. Starters last season (the top of his position, under the
  subscriber's own scoring) are left out — nobody needs telling a top-24 back
  is "rising" — as are players already on the subscriber's roster.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

MIN_RECENT = 6.0          # touches a game over the last two weeks
MIN_JUMP = 3.0            # ... and this many more than before
KEEP = 3                  # lines in a report
POOL = 40                 # candidates kept per week before per-roster filtering
POSITIONS = frozenset({"RB", "WR", "TE"})
# Last season's rank cut-offs (per position, under the subscriber's scoring):
# past these he is not a name everybody already holds.
STARTER_CUT = {"RB": 24, "WR": 24, "TE": 12}


def _f(value: Any) -> float:
    try:
        return float(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def touches(row: Mapping[str, Any]) -> float:
    return _f(row.get("targets")) + _f(row.get("carries"))


def candidates(weekly: Mapping[int, Mapping[str, Mapping[str, Any]]],
               week: int) -> list[dict[str, Any]]:
    """The week's risers league-wide, biggest jump first. Needs week >= 4:
    two recent weeks and at least one before them."""
    recent_weeks = (week - 2, week - 1)
    if week < 4:
        return []
    out: list[dict[str, Any]] = []
    for pid, last in (weekly.get(week - 1) or {}).items():
        if not pid.startswith("00-"):
            continue
        position = str(last.get("position") or "").upper()
        prev = (weekly.get(week - 2) or {}).get(pid)
        if position not in POSITIONS or prev is None:
            continue
        recent = [touches(last), touches(prev)]
        earlier = [touches(rows[pid]) for w, rows in weekly.items()
                   if w < recent_weeks[0] and pid in rows]
        if not earlier:
            continue
        recent_avg = sum(recent) / 2
        earlier_avg = sum(earlier) / len(earlier)
        if recent_avg < MIN_RECENT or recent_avg - earlier_avg < MIN_JUMP:
            continue
        out.append({"player_id": pid, "position": position,
                    "team": str(last.get("team") or ""),
                    "recent": round(recent_avg, 1),
                    "earlier": round(earlier_avg, 1),
                    "jump": round(recent_avg - earlier_avg, 1)})
    out.sort(key=lambda c: (-c["jump"], c["player_id"]))
    return out[:POOL]


def for_roster(pool: Sequence[Mapping[str, Any]], roster: Sequence[str],
               ranks: Mapping[str, tuple[str, int, int]],
               names: Any) -> list[dict[str, Any]]:
    """The lines one subscriber sees: not on their roster, not last season's
    starters under their scoring."""
    held = set(roster)
    out: list[dict[str, Any]] = []
    for cand in pool:
        pid = cand["player_id"]
        if pid in held:
            continue
        ranked = ranks.get(pid)
        if ranked and ranked[1] <= STARTER_CUT.get(cand["position"], 0):
            continue
        out.append({**cand, "name": names.name(pid),
                    "line": line(names.name(pid), cand)})
        if len(out) == KEEP:
            break
    return out


def line(name: str, cand: Mapping[str, Any]) -> str:
    return (f"{name} ({cand['team']}, {cand['position']}): "
            f"{cand['recent']:.1f} touches a game over his last two, "
            f"up from {cand['earlier']:.1f} before.")
