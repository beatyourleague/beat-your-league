"""Rising roles — who is getting more of the ball lately, as facts.

After the lineup, the question managers ask most is who to go and get. The
product cannot see a league, so it cannot say who is free; what it CAN say is
who, anywhere in the league, is being given noticeably more than he was — and
leave "is he on my league's free-agent list" to the one person who can see it.

RULE U1 (engine/usage.py) governs: this is a REPORT of counted usage, never a
projection and never a probability. Nothing here is a call, so nothing is
graded and nothing enters the ledger. The line a reader gets is a sentence
about what already happened: "9.5 touches a game over his last two, up from
3.0 in Weeks 1–3."

Definitions, frozen here and pinned by tests:
- **touches** = targets + carries, from the weekly stat rows — printed as
  "targets + carries" (pre-launch review F10): to an expert "touches" means
  catches + carries, which is a different, smaller number.
- A player is RISING when, over the two most recent completed weeks, he
  appeared in both, averaged at least MIN_RECENT touches, and averaged at
  least MIN_JUMP more than in his earlier appearances this season (he needs at
  least one). Quarterbacks and kickers are out: their touches mean nothing.
- Sorted by the size of the jump, then by id, so a report is byte-identical
  across runs. Starters last season (the top of his position, under the
  subscriber's own scoring) are left out — nobody needs telling a top-24 back
  is "rising" — and so are this season's (pre-launch review P8): Malik Nabers,
  hurt for most of 2025, was offered as a pickup "to check whether he's free"
  while a top-five receiver this year.
- "Before" names its weeks (launch review SS-I13, Oct 2026): "up from 0.0
  before" read as a role grown from nothing, with no way to tell which weeks
  it covered — and a player with weeks out of the box score (his team played,
  he had no row) says so, rather than passing a return off as a bigger role.
- A riser ON the subscriber's roster comes first, marked "on your roster"
  (launch review BE-I7): his projection is built on the old role, so the
  counted change is news the manager can use this week. One who shares a team
  and position with a rostered player says so — "same team and position as
  your Breece Hall" — which is usually why he is rising.
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
    # Which teams played each week, read off the same rows: a week his team
    # sat out is a bye, never a game he missed.
    played: dict[int, set[str]] = {}
    for w, rows in weekly.items():
        for row in rows.values():
            if row.get("team"):
                played.setdefault(w, set()).add(str(row["team"]))
    out: list[dict[str, Any]] = []
    for pid, last in (weekly.get(week - 1) or {}).items():
        if not pid.startswith("00-"):
            continue
        position = str(last.get("position") or "").upper()
        prev = (weekly.get(week - 2) or {}).get(pid)
        if position not in POSITIONS or prev is None:
            continue
        recent = [touches(last), touches(prev)]
        earlier_weeks = sorted(w for w, rows in weekly.items()
                               if w < recent_weeks[0] and pid in rows)
        earlier = [touches(weekly[w][pid]) for w in earlier_weeks]
        if not earlier:
            continue
        recent_avg = sum(recent) / 2
        earlier_avg = sum(earlier) / len(earlier)
        if recent_avg < MIN_RECENT or recent_avg - earlier_avg < MIN_JUMP:
            continue
        team = str(last.get("team") or "")
        out.append({"player_id": pid, "position": position, "team": team,
                    "recent": round(recent_avg, 1),
                    "earlier": round(earlier_avg, 1),
                    "jump": round(recent_avg - earlier_avg, 1),
                    "earlier_weeks": earlier_weeks,
                    # Weeks his team played and he did not, before the recent
                    # two: a return, not a bigger role.
                    "missed": [w for w in range(1, recent_weeks[0])
                               if w not in earlier_weeks
                               and team in played.get(w, set())]})
    out.sort(key=lambda c: (-c["jump"], c["player_id"]))
    return out[:POOL]


def for_roster(pool: Sequence[Mapping[str, Any]], roster: Sequence[str],
               ranks: Mapping[str, tuple[str, int, int]],
               names: Any, teams: Mapping[str, str] | None = None,
               this_season: Mapping[str, tuple[str, int, int]] | None = None
               ) -> list[dict[str, Any]]:
    """The lines one subscriber sees, never last season's starters under
    their scoring: their own risers first, marked "on your roster", then up
    to KEEP others — each tied, when ``teams`` (player -> team) says so, to a
    rostered player at his team and position."""
    held = list(roster)
    teams = teams or {}
    mine: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for cand in pool:
        pid = cand["player_id"]
        ranked = ranks.get(pid)
        if ranked and ranked[1] <= STARTER_CUT.get(cand["position"], 0):
            continue
        # A PICKUP suggestion only: one of their own players stays, because
        # his counted change is news about a projection built on the old role.
        now = (this_season or {}).get(pid)
        if (pid not in held and now
                and now[1] <= STARTER_CUT.get(cand["position"], 0)):
            continue
        name = names.name(pid)
        if pid in held:
            if len(mine) < KEEP:
                mine.append({**cand, "name": name, "on_roster": True,
                             "line": line(name, cand, on_roster=True)})
            continue
        if len(out) == KEEP:
            continue
        mate = next((names.name(other) for other in held
                     if teams.get(other) == cand["team"]
                     and names.position(other) == cand["position"]), None)
        out.append({**cand, "name": name, "line": line(name, cand, teammate=mate)})
    return mine + out


def _weeks(weeks: Sequence[int]) -> str:
    """[1, 2, 3] -> "Weeks 1–3"; [2] -> "Week 2"; [1, 3] -> "Weeks 1 and 3"."""
    weeks = sorted(weeks)
    if len(weeks) == 1:
        return f"Week {weeks[0]}"
    if weeks == list(range(weeks[0], weeks[-1] + 1)):
        return f"Weeks {weeks[0]}–{weeks[-1]}"
    return "Weeks " + ", ".join(str(w) for w in weeks[:-1]) + f" and {weeks[-1]}"


def line(name: str, cand: Mapping[str, Any], *, on_roster: bool = False,
         teammate: str | None = None) -> str:
    earlier = cand.get("earlier_weeks")
    before = f"in {_weeks(earlier)}" if earlier else "before"
    missed = cand.get("missed") or []
    # "Not in the box score", not "didn't play": a stat row is the fact, and a
    # player who only covered kicks has none.
    back = f" He wasn't in the box score in {_weeks(missed)}." if missed else ""
    mark = ", on your roster" if on_roster else ""
    tie = f" Same team and position as your {teammate}." if teammate else ""
    return (f"{name} ({cand['team']}, {cand['position']}){mark}: "
            f"{cand['recent']:.1f} targets + carries a game over his last two, "
            f"up from {cand['earlier']:.1f} {before}.{back}{tie}")
