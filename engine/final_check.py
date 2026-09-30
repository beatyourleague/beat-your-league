"""The Saturday final check: what changed since Tuesday, decided.

The weekly report goes out on Tuesday, built on the last complete injury report
(week W-1's — see ``run/solo._availability``). The league's own week-W reports
come out Wednesday to Friday, so by Sunday a report can be telling somebody to
start a player who was ruled out on Friday. The subscriber paid for their
lineup to be decided; a Tuesday snapshot that goes stale in their inbox is the
gap between what they hoped for and what they got.

This module closes it WITHOUT publishing anything new. It takes the lineup that
was sent (the ``plan`` written by ``run/tuesday.py``) and what is known now
(one :class:`Now` per rostered player), and applies the same rule the Tuesday
report already states: when a starter can't play, the best eligible player on
the bench takes his slot, in the order Tuesday's projections already printed.
No probability is computed or shown, so nothing here enters the ledger or
carries a calibration burden — the confidences on Tuesday's rows remain the
product's only graded claims.

Three rules, each one a way this could have been confidently wrong:

- **RULE F1 — a locked player is never moved.** Once a player's game kicks off
  every league app locks him; telling somebody to start a Thursday player on
  Saturday is advice they cannot take. A locked starter keeps his slot and a
  locked bench player is never offered.
- **RULE F2 — "cleared" needs the FINAL report.** Out and Doubtful are acted on
  whenever they appear. But "he's off the injury report" is only true once his
  team has filed its final report for the week (two days before the game), so a
  Monday-night player on a Saturday is not called cleared — the absence of a
  designation there means "not filed yet", and principle 1 says unknowable
  never means cleared.
- **RULE F3 — quiet unless something changed.** An email that arrives every
  Saturday saying "no changes" teaches people to stop opening it, which is how
  the one that matters gets missed. Only a swap, a slot we can't fill, or a
  starter newly in doubt sends anything; reminders ride along only when it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from engine.history import FLEX_ELIGIBILITY

# A designation that means he is not playing. Doubtful players almost never
# suit up, and the product has always read it this way (ingest/injuries.py).
RULED_OUT = frozenset({"out", "doubtful"})
QUESTIONABLE = "questionable"

SWAP = "swap"            # a starter can't play and someone takes his slot
NO_FILL = "no_fill"      # a starter can't play and nobody on the bench can cover
BACK = "back"            # a bench player is back and beats a starter
WATCH = "watch"          # a starter is newly questionable: the plan if he sits
REMINDER = "reminder"    # still questionable, as on Tuesday
CLEARED = "cleared"      # questionable on Tuesday, off the report now

# The kinds that are worth an email on their own (RULE F3). A starter newly
# QUESTIONABLE is not one: most questionable players play, and the proving run
# (2025 weeks 4-8, twelve subscribers) mailed half of all Saturday emails for
# questionable-only news that changed nothing. It rides along when a real
# change sends the email anyway.
TRIGGERS = frozenset({SWAP, NO_FILL, BACK})


@dataclass(frozen=True)
class Now:
    """One rostered player, as of the check."""

    designation: str | None = None   # "out", "doubtful", "questionable" or None
    reason: str | None = None        # buyer-facing: "listed out (ankle)"
    playing: bool = True             # his team has a game this week
    locked: bool = False             # that game has kicked off (RULE F1)
    final: bool = True               # his team's final report is in (RULE F2)

    @property
    def ruled_out(self) -> bool:
        return self.designation in RULED_OUT

    @property
    def available(self) -> bool:
        return self.playing and not self.locked and not self.ruled_out


@dataclass(frozen=True)
class Change:
    kind: str
    action: str       # what to do, one line: "Start Tony Pollard at RB"
    detail: str       # why, in facts: "Saquon Barkley is listed out (ankle)..."


def eligible(position: str | None, slot: str) -> bool:
    allowed = FLEX_ELIGIBILITY.get(slot)
    if allowed is not None:
        return position in allowed
    return position == slot


def _value(info: Mapping[str, Any], basis: str) -> float | None:
    value = info.get("projected" if basis == "projected" else "last_season")
    return float(value) if value is not None else None


def _number(info: Mapping[str, Any], basis: str) -> str:
    value = _value(info, basis)
    if value is None:
        return "has no projection yet"
    if basis == "projected":
        return f"projects {value:.1f}"
    return f"averaged {value:.1f} a game last season"


def final_check(plan: Mapping[str, Any], now: Mapping[str, Now]) -> list[Change]:
    """The changes to make before kickoff, most important first.

    ``plan`` is what ``run/tuesday.py`` stored when the report went out:
    ``slots`` (slot + starter id, in lineup order) and ``players`` (every
    rostered player: name, position, Tuesday's projection, last season's
    per-game figure, and Tuesday's availability status). ``now`` has one entry
    per rostered player; a player missing from it is treated as unknown —
    never moved, never called cleared.
    """
    players: Mapping[str, Mapping[str, Any]] = plan["players"]
    slots = [(s["slot"], s.get("player_id")) for s in plan["slots"]]
    lineup = {i: pid for i, (_, pid) in enumerate(slots)}
    starters = {pid for pid in lineup.values() if pid}
    unknown = Now(playing=False, final=False)

    def state(pid: str) -> Now:
        return now.get(pid, unknown)

    def name(pid: str) -> str:
        return str(players.get(pid, {}).get("name") or pid)

    def position(pid: str) -> str | None:
        return players.get(pid, {}).get("position")

    # Tuesday's order is the projection it printed; in week 1, before any
    # projection exists, it was last season's per-game scoring, and the check
    # uses the same basis the report did.
    basis = ("projected" if any(p.get("projected") is not None
                                for p in players.values()) else "last_season")

    def value(pid: str) -> float | None:
        return _value(players.get(pid, {}), basis)

    # A roster changed since Tuesday (run/saturday.py folds the update in): a
    # dropped player is gone from the bench and vacates any slot he held; a
    # pickup joins the bench and can win a slot like a player back from injury.
    dropped = {pid for pid, info in players.items() if info.get("dropped")}
    bench = [pid for pid in players if pid not in starters and pid not in dropped]
    used: set[str] = set()

    def best(slot: str) -> str | None:
        candidates = [pid for pid in bench
                      if pid not in used and state(pid).available
                      and eligible(position(pid), slot)]
        # Highest projection first; a player the model has no number on (a
        # rookie) sorts LAST but is still an option — dropping him told a
        # subscriber "nobody on your bench can cover" while a healthy player
        # sat there. A questionable player loses a tie to a healthy one, and
        # the id keeps the answer the same on every run.
        candidates.sort(key=lambda pid: (value(pid) is None, -(value(pid) or 0.0),
                                         state(pid).designation == QUESTIONABLE, pid))
        return candidates[0] if candidates else None

    def fill(index: int) -> tuple[str, int | None] | None:
        """Who takes slot ``index``: straight off the bench, or by sliding a
        flex starter across and filling the flex from the bench — whichever
        puts the higher-projected bench player in. (bench id, flex index)."""
        slot = slots[index][0]
        options: list[tuple[float, str, int | None]] = []
        direct = best(slot)
        if direct:
            options.append((-1.0 if value(direct) is None else value(direct), direct, None))
        for j, (other, pid) in enumerate(slots):
            if (j == index or not pid or pid in dropped or other not in FLEX_ELIGIBILITY
                    or not state(pid).available or not eligible(position(pid), slot)):
                continue
            via = best(other)
            if via:
                options.append((-1.0 if value(via) is None else value(via), via, j))
        if not options:
            return None
        options.sort(key=lambda o: (-o[0], o[2] is not None, o[1]))
        return options[0][1], options[0][2]

    def also_questionable(pid: str) -> str:
        return (f" He's questionable too, so check on him Sunday morning."
                if state(pid).designation == QUESTIONABLE else "")

    changes: list[Change] = []

    # 1. Starters who can't play. Most restrictive slots first, the same order
    # the lineup was built in, so a QB is covered before a flex borrows anyone.
    order = sorted(range(len(slots)),
                   key=lambda i: (len(FLEX_ELIGIBILITY.get(slots[i][0], ())) or 1, i))
    for index in order:
        slot, pid = slots[index]
        if not pid:
            continue
        current = state(pid)
        if pid in dropped:
            current = Now("out", "no longer on your roster")
        if current.locked or not current.ruled_out:
            continue
        placed = fill(index)
        if placed is None:
            changes.append(Change(
                NO_FILL,
                f"Nobody on your bench can cover {slot}",
                f"{name(pid)} is {current.reason or 'ruled out'}, and every "
                f"{slot} option on your roster is out, on bye or already "
                f"playing. If you can add one before kickoff, do."))
            continue
        incoming, via = placed
        used.add(incoming)
        number = _number(players[incoming], basis)
        if via is None:
            lineup[index] = incoming
            action = f"Start {name(incoming)} at {slot}"
            detail = (f"{name(pid)} is {current.reason or 'ruled out'}. "
                      f"{name(incoming)} {number}, the best {slot} option you have.")
        else:
            flex_slot, mover = slots[via]
            lineup[index], lineup[via] = mover, incoming
            slots[via] = (flex_slot, incoming)
            action = (f"Move {name(mover)} to {slot} and start {name(incoming)} "
                      f"at {flex_slot}")
            detail = (f"{name(pid)} is {current.reason or 'ruled out'}. "
                      f"{name(incoming)} {number}, the best way to fill the gap.")
        slots[index] = (slot, lineup[index])
        changes.append(Change(SWAP, action, detail + also_questionable(incoming)))

    # 2. Bench players back in time. Tuesday could only plan around last
    # week's report; one who was out then and is fully cleared now takes the
    # slot of the weakest starter he beats (RULE F2: cleared needs the final).
    back = sorted(
        (pid for pid in bench
         if pid not in used and (players[pid].get("tuesday") == "out"
                                 or players[pid].get("added"))
         and state(pid).available and state(pid).final
         and state(pid).designation is None and value(pid) is not None),
        key=lambda pid: (-(value(pid) or 0.0), pid))
    for incoming in back:
        target: int | None = None
        for index, (slot, pid) in enumerate(slots):
            if not pid or not eligible(position(incoming), slot):
                continue
            if state(pid).locked:
                continue
            gain = (value(incoming) or 0.0) - (value(pid) or 0.0)
            if gain < 0.1:
                continue
            if target is None or (value(pid) or 0.0) < (value(slots[target][1]) or 0.0):
                target = index
        if target is None:
            continue
        slot, displaced = slots[target]
        used.add(incoming)
        lineup[target] = incoming
        slots[target] = (slot, incoming)
        why = ("is new on your roster" if players[incoming].get("added")
               else "is off the injury report")
        changes.append(Change(
            BACK,
            f"Start {name(incoming)} at {slot} over {name(displaced)}",
            f"{name(incoming)} {why} and "
            f"{_number(players[incoming], basis)}, to {name(displaced)}'s "
            f"{(value(displaced) or 0.0):.1f}."
            if basis == "projected" else
            f"{name(incoming)} {why} and "
            f"{_number(players[incoming], basis)}, more than {name(displaced)}."))

    # 3. Starters in doubt, and 4. starters cleared since Tuesday.
    for index, (slot, pid) in enumerate(slots):
        if not pid or pid in dropped:
            continue
        current = state(pid)
        if current.locked or not current.playing:
            continue
        was = players.get(pid, {}).get("tuesday")
        if current.designation == QUESTIONABLE:
            placed = fill(index)
            if placed:
                # Named once: two questionable starters must not both be
                # told the same bench player is their cover.
                used.add(placed[0])
            # The mover and the slot the newcomer takes are both named: "start
            # X and move Y to WR — he projects 12.3" left "he" and X's slot
            # to guesswork (proving run, 2025 week 4).
            plan_b = ((f"If he's ruled out, move {name(slots[placed[1]][1])} to "
                       f"{slot} and start {name(placed[0])} at "
                       f"{slots[placed[1]][0]}"
                       if placed[1] is not None else
                       f"If he's ruled out, start {name(placed[0])} at {slot}")
                      + f" ({_number(players[placed[0]], basis)})."
                      if placed else
                      f"Every other {slot} option on your roster is out or "
                      f"on bye, so keep him in.")
            kind = REMINDER if was == QUESTIONABLE else WATCH
            changes.append(Change(
                kind, f"Check on {name(pid)} ({slot}) before kickoff",
                f"{name(pid)} is {current.reason or 'listed questionable'}. "
                + plan_b))
        elif (was == QUESTIONABLE and current.designation is None
              and current.final):
            changes.append(Change(
                CLEARED, f"{name(pid)} is cleared — keep him at {slot}",
                f"He was questionable on Tuesday and is off the injury report now."))

    rank = {SWAP: 0, NO_FILL: 0, BACK: 1, WATCH: 2, REMINDER: 3, CLEARED: 4}
    return sorted(changes, key=lambda c: rank[c.kind])


def worth_sending(changes: list[Change]) -> bool:
    """RULE F3."""
    return any(c.kind in TRIGGERS for c in changes)
