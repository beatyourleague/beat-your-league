"""Last week, closed out — the part of the week the report kept skipping.

Everything else here looks FORWARD: set this lineup, bid this much, watch that
guy. But the thing a fantasy manager actually feels is the resolution — the
result, the near-miss, the guy who went off on their bench. A product that only
ever hands out homework is a utility. Closing the week is what makes it part of
the season.

Two rules, and the second one is the reason this module is worth building:

RULE R1 — every figure is a COUNT of something that already happened. Real
points from real box scores, so nothing here carries a calibration burden and
nothing here is a prediction. The whole section is safe under principle 1
precisely because it never forecasts.

RULE R2 — ABSOLUTION IS THE POINT, NOT THE GUILT. "You left 31 points on your
bench" is the easy line and it is half the story: it implies the loss was your
fault. When the best lineup available STILL loses, that is the more useful
truth and the report says so plainly. Regret is only reported when a different
choice would genuinely have changed the result — which is what ``flipped_by``
measures. A winning week never gets a regret line at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.history import FLEX_ELIGIBILITY, PlayerIndex, Season, TeamWeek


def _slot_width(slot: str) -> int:
    """Single-position slots claim their player before flexes."""
    allowed = FLEX_ELIGIBILITY.get(slot)
    return len(allowed) if allowed else 1


@dataclass(frozen=True)
class Miss:
    """One bench player who outscored the starter he could have replaced."""

    slot: str
    started_name: str
    started_points: float
    bench_name: str
    bench_points: float

    @property
    def cost(self) -> float:
        return round(self.bench_points - self.started_points, 1)


@dataclass(frozen=True)
class LastWeek:
    """What happened, and whether anything could have been done about it."""

    week: int
    points: float
    opponent_label: str
    opponent_points: float
    best_possible: float
    biggest_miss: Miss | None
    flipped_by: Miss | None      # a single swap that would have won it
    winnable: bool               # the best available lineup beats their score

    @property
    def won(self) -> bool:
        return self.points > self.opponent_points

    @property
    def margin(self) -> float:
        return round(self.points - self.opponent_points, 1)

    @property
    def left_on_bench(self) -> float:
        return round(self.best_possible - self.points, 1)


def _eligible(players: PlayerIndex, slot: str, player_id: str) -> bool:
    """Could this player have filled this slot? Uses PlayerInfo.eligible_for,
    the same rule the lineup builder applies, so the counterfactual is one the
    league would actually have allowed rather than one we invented."""
    info = players.get(player_id)
    return bool(info and info.eligible_for(slot))


def _best_lineup_points(season: Season, team_week: TeamWeek,
                        players: PlayerIndex) -> float:
    """The highest total the roster could have scored, greedily by slot
    restrictiveness — the same assignment order optimal_lineup uses."""
    available = {p for p in team_week.players}
    total = 0.0
    slots = sorted(enumerate(season.starting_slots),
                   key=lambda item: _slot_width(item[1]))
    for _, slot in slots:
        best_id, best_pts = None, None
        for pid in available:
            if not _eligible(players, slot, pid):
                continue
            pts = team_week.actual_points(pid)
            if pts is None:
                continue
            if best_pts is None or pts > best_pts:
                best_id, best_pts = pid, pts
        if best_id is not None:
            available.discard(best_id)
            total += best_pts or 0.0
    return round(total, 1)


def summarise(season: Season, team_week: TeamWeek, opponent: TeamWeek,
              opponent_label: str, players: PlayerIndex) -> LastWeek | None:
    """Close out one completed week, or None when it has not been played.

    A 0.0-vs-0.0 matchup means the week has not happened yet, never a tie —
    the same rule the matchup backtest froze as RULE M1.
    """
    if team_week.points <= 0 and opponent.points <= 0:
        return None

    best = _best_lineup_points(season, team_week, players)
    bench = [p for p in team_week.bench() if team_week.actual_points(p) is not None]

    biggest: Miss | None = None
    flipped: Miss | None = None
    for index, slot in enumerate(season.starting_slots):
        started_id = (team_week.starters[index]
                      if index < len(team_week.starters) else None)
        if not started_id:
            continue
        started_pts = team_week.actual_points(started_id) or 0.0
        for pid in bench:
            if not _eligible(players, slot, pid):
                continue
            pts = team_week.actual_points(pid) or 0.0
            if pts <= started_pts:
                continue
            miss = Miss(slot=slot,
                        started_name=players.name(started_id),
                        started_points=round(started_pts, 1),
                        bench_name=players.name(pid),
                        bench_points=round(pts, 1))
            if biggest is None or miss.cost > biggest.cost:
                biggest = miss
            # RULE R2: a swap is only REGRET if it would have won the game.
            # Every other "you left points on the bench" line is hindsight
            # with no decision attached to it.
            if (team_week.points + miss.cost) > opponent.points and (
                    flipped is None or miss.cost < flipped.cost):
                flipped = miss

    return LastWeek(
        week=team_week.week,
        points=round(team_week.points, 1),
        opponent_label=opponent_label,
        opponent_points=round(opponent.points, 1),
        best_possible=best,
        biggest_miss=biggest,
        flipped_by=flipped,
        winnable=best > opponent.points,
    )


def headline(last: LastWeek) -> str:
    """One sentence. The result, and what it was worth arguing about.

    Absolution beats accusation when the evidence supports it: a week nothing
    could have saved is reported as a week nothing could have saved.
    """
    if last.won:
        return (f"You beat {last.opponent_label} {last.points:.1f}–"
                f"{last.opponent_points:.1f}.")
    if not last.winnable:
        return (f"{last.opponent_label} beat you {last.opponent_points:.1f}–"
                f"{last.points:.1f}. Nothing on your bench saves that one — your "
                f"best possible lineup still loses. You were beaten on scoring, "
                f"not on selection.")
    if last.flipped_by:
        m = last.flipped_by
        return (f"{last.opponent_label} beat you {last.opponent_points:.1f}–"
                f"{last.points:.1f}. {m.bench_name} ({m.bench_points:.1f}) for "
                f"{m.started_name} ({m.started_points:.1f}) at {m.slot} would "
                f"have won it.")
    return (f"{last.opponent_label} beat you {last.opponent_points:.1f}–"
            f"{last.points:.1f}.")
