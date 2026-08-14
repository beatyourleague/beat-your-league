"""The waiver market: what a player costs in YOUR league, and who can pay it.

This is the edge no ranking site can reach. A rankings page tells everyone the
same "add this guy"; it cannot tell you that only two teams in your league can
still afford him, or that the manager you're bidding against showed he'll go to
40 when he lost a claim in week 6. Both facts are sitting in the league's own
transaction log.

Two honesty constraints shape everything here:

RULE W1  ``settings.waiver_budget`` is NOT a trustworthy denominator. Measured
         on real data, two managers in the sample league spent 140 and 101
         against a stated budget of 100 — commissioners raise budgets mid-season
         and the setting only reports its current value. So when any manager's
         spend exceeds the stated budget, we refuse to publish "remaining" for
         anyone and fall back to relative spend, saying why.
RULE W2  Only settled weeks count. Everything here reads transactions from weeks
         STRICTLY BEFORE the report week, so a live report can never quote a
         claim that hasn't processed and a historical render can never see the
         future.

Nothing here is a probability, so nothing here goes through the calibration
gate — these are observed facts from the league log plus a threshold derived
from them, and every line carries the evidence it rests on.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from engine.history import Season

COMPLETE = "complete"
FAILED = "failed"


@dataclass(frozen=True)
class ManagerBudget:
    """One manager's position in the league's waiver economy."""

    roster_id: int
    spent: int
    remaining: int | None      # None when RULE W1 voids the budget setting
    top_bid_shown: int | None  # highest bid they have ever placed (won OR lost)
    claims_won: int
    claims_lost: int

    @property
    def has_shown_appetite(self) -> bool:
        return self.top_bid_shown is not None and self.top_bid_shown > 0


@dataclass(frozen=True)
class WaiverMarket:
    """The league's waiver economy as of a given week."""

    week: int
    weeks_counted: tuple[int, ...]
    budget_setting: int | None
    budget_reliable: bool
    managers: dict[int, ManagerBudget]
    winning_bids: tuple[int, ...]

    # ---- market-wide reads ------------------------------------------- #

    @property
    def going_rate(self) -> int | None:
        """Median winning bid — what a claim has actually cost in this league."""
        return int(statistics.median(self.winning_bids)) if self.winning_bids else None

    @property
    def top_winning_bid(self) -> int | None:
        return max(self.winning_bids) if self.winning_bids else None

    def rivals_who_can_pay(self, amount: int, exclude: int) -> int | None:
        """How many OTHER teams could still cover ``amount``.

        Counted, never named: the actionable fact is "two teams can answer you",
        and naming eleven managers would both bury that and drag other people's
        identities onto any page this report is shown on.
        """
        if not self.budget_reliable:
            return None
        return sum(1 for rid, m in self.managers.items()
                   if rid != exclude and m.remaining is not None and m.remaining >= amount)

    def bid_to_beat(self, exclude: int) -> int | None:
        """The highest bid a still-funded rival has actually shown they'll pay.

        Revealed willingness, not a guess: every number here is a bid that
        manager really placed. Beat it and you have out-bid the appetite the
        league has demonstrated so far.
        """
        shown = [
            m.top_bid_shown for rid, m in self.managers.items()
            if rid != exclude and m.has_shown_appetite
            and (not self.budget_reliable or m.remaining is None
                 or m.remaining >= (m.top_bid_shown or 0))
        ]
        return max(shown) if shown else None


def build_waiver_market(season: Season, week: int) -> WaiverMarket:
    """Read the league's settled waiver history into a market picture."""
    weeks = tuple(w for w in sorted(season.transactions) if w < week)

    spent: dict[int, int] = {rid: 0 for rid in season.teams}
    top_bid: dict[int, int] = {}
    won: dict[int, int] = {rid: 0 for rid in season.teams}
    lost: dict[int, int] = {rid: 0 for rid in season.teams}
    winning_bids: list[int] = []

    for w in weeks:
        for txn in season.transactions[w]:
            if txn.get("type") != "waiver":
                continue
            bid = (txn.get("settings") or {}).get("waiver_bid")
            status = txn.get("status")
            for rid in (txn.get("roster_ids") or []):
                if not isinstance(rid, int):
                    continue
                spent.setdefault(rid, 0)
                won.setdefault(rid, 0)
                lost.setdefault(rid, 0)
                if isinstance(bid, int):
                    # A losing bid still reveals the price they were willing to
                    # pay — often more informative than what they actually paid.
                    top_bid[rid] = max(top_bid.get(rid, 0), bid)
                if status == COMPLETE:
                    won[rid] += 1
                    if isinstance(bid, int):
                        spent[rid] += bid
                        winning_bids.append(bid)
                elif status == FAILED:
                    lost[rid] += 1

    budget = season.waiver_budget
    # RULE W1: one manager over the stated budget voids the setting for everyone.
    reliable = bool(budget) and all(v <= budget for v in spent.values())

    managers = {
        rid: ManagerBudget(
            roster_id=rid,
            spent=spent.get(rid, 0),
            remaining=(budget - spent.get(rid, 0)) if reliable else None,
            top_bid_shown=top_bid.get(rid),
            claims_won=won.get(rid, 0),
            claims_lost=lost.get(rid, 0),
        )
        for rid in sorted(set(spent) | set(season.teams))
    }
    return WaiverMarket(
        week=week, weeks_counted=weeks, budget_setting=budget,
        budget_reliable=reliable, managers=managers,
        winning_bids=tuple(winning_bids),
    )


def market_json(market: WaiverMarket, my_roster_id: int,
                rival_roster_id: int, rival_label: str) -> dict[str, Any]:
    """The report-facing view: my position, my rival's, and the market rate."""
    mine = market.managers.get(my_roster_id)
    rival = market.managers.get(rival_roster_id)
    span = (f"weeks {min(market.weeks_counted)}-{max(market.weeks_counted)}"
            if market.weeks_counted else "no settled waiver weeks yet")

    out: dict[str, Any] = {
        "evidence": f"your league's waiver log, {span}",
        "budget_reliable": market.budget_reliable,
        "going_rate": market.going_rate,
        "top_winning_bid": market.top_winning_bid,
        "bid_to_beat": market.bid_to_beat(exclude=my_roster_id),
        "my_remaining": mine.remaining if mine else None,
        "my_spent": mine.spent if mine else 0,
        "rival_label": rival_label,
        "rival_remaining": rival.remaining if rival else None,
        "rival_top_bid_shown": rival.top_bid_shown if rival else None,
        "rival_claims_lost": rival.claims_lost if rival else 0,
    }
    if not market.budget_reliable:
        out["budget_note"] = (
            "Someone in your league has spent more than the league's stated "
            "budget, so the budget number can't be trusted as a denominator — "
            "we show what people have actually spent instead of guessing at "
            "what's left.")
    return out
