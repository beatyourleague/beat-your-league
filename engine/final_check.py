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
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Sequence

from engine.history import FLEX_ELIGIBILITY

# The inactive list is posted 90 minutes before each kickoff — the moment a
# player still questionable on his final report is ruled in or out. Tuesday's
# if/then (engine.solo_report) imports this one: the same clock on both days.
INACTIVES_LEAD = timedelta(minutes=90)
NFL_TIME = "America/New_York"

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
    # When that game kicks off (timezone-aware). None when unknown, which never
    # rules anybody out of a plan — an unknown clock is not an early one.
    kickoff: datetime | None = None
    # On the practice squad (players.csv DEV, method §15 C9). He plays only if
    # elevated, as late as Saturday 4 PM ET — after this check goes out — so
    # he stays an option, ranked after everyone confirmed, and a plan naming
    # him says to check (recheck ENG-3: Saturday named Lew Nichols III, DEV,
    # with no caveat where Tuesday ranked him last and said to check).
    practice_squad: bool = False

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


def rank_covers(index: int, slots: Sequence[tuple[str, str | None]],
                bench: Iterable[str], *,
                eligible_for: Callable[[str, str], bool],
                value: Callable[[str], float | None],
                questionable: Callable[[str], bool],
                practice_squad: Callable[[str], bool],
                incoming_ok: Callable[[str], bool],
                mover_ok: Callable[[str], bool]) -> list[tuple[str, int | None]]:
    """Every way to fill ``slots[index]`` if its starter can't play, best
    first: (bench player, index of the flex starter who slides across to make
    room — None for a straight swap).

    ONE ranking for Tuesday's if/then (``engine.solo_report.covers``) and this
    check (recheck ENG-4). Each day had its own, so the same Friday news named
    different covers: Tuesday refused a questionable starter as the one
    sliding across, Saturday slid him ("Move Keenan Allen to WR and start
    Alvin Kamara at FLEX", both questionable, where Tuesday had said Ladd
    McConkey). The order: everyone confirmed before a practice-squad player
    (he plays only if elevated, method §15 C9); then the higher printed
    projection, a player with none (no games this season) after everyone with
    one; a healthy player before a questionable one; a straight swap before a
    slide; then the ids, so every run gives the same answer.

    Never the one sliding across: a questionable starter or a practice-squad
    one — a plan built on a second doubt is not a plan. ``incoming_ok`` and
    ``mover_ok`` carry each day's own facts (out, locked, already named)."""
    slot = slots[index][0]
    bench = list(bench)
    found: list[tuple[tuple, tuple[str, int | None]]] = []

    def add(incoming: str, via: int | None) -> None:
        number = value(incoming)
        key = (practice_squad(incoming), number is None, -(number or 0.0),
               questionable(incoming), via is not None, incoming,
               slots[via][1] if via is not None else "")
        found.append((key, (incoming, via)))

    for pid in bench:
        if eligible_for(pid, slot) and incoming_ok(pid):
            add(pid, None)
    for via, (other, mover) in enumerate(slots):
        if (via == index or not mover or other not in FLEX_ELIGIBILITY
                or not eligible_for(mover, slot) or questionable(mover)
                or practice_squad(mover) or not mover_ok(mover)):
            continue
        for pid in bench:
            if eligible_for(pid, other) and incoming_ok(pid):
                add(pid, via)
    return [cover for _, cover in sorted(found, key=lambda item: item[0])]


def elevation_note(name: str) -> str:
    """The one clause, both days, for a cover on the practice squad."""
    return f"{name} is on the practice squad: check he's been elevated"


def first_to_kick_off(moving: Sequence[str],
                      kickoff_of: Callable[[str], datetime | None]
                      ) -> tuple[str | None, datetime | None]:
    """(who, when) — the player in a plan whose game starts first, which is
    the clock the plan binds to (recheck ENG-1/RQ2-01: "Dontayvion Wicks kicks
    off at Sun 9:30 AM ET" named the incoming player for the 9:30 London
    kickoff of David Montgomery, the one sliding across)."""
    timed = [(when, pid) for pid in moving if (when := kickoff_of(pid)) is not None]
    if not timed:
        return None, None
    when, pid = min(timed)
    return pid, when


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
    # What a player is already doing in this check, for the true reason when
    # nobody is left (recheck ENG-2/RQ2-05): "Every other WR option on your
    # roster is out or on bye" was said with Jerry Jeudy healthy, playing and
    # already named as Ashton Jeanty's fallback.
    held_by: dict[str, str] = {}
    # Everyone a game-day plan moves — never moved by a second one.
    planned: set[str] = set()

    def starts_after(pid: str, after: datetime | None) -> bool:
        """RULE F1 at the moment the news lands, not only at the check: a
        player whose game kicks off before ``after`` is locked by then."""
        kick = state(pid).kickoff
        return after is None or kick is None or kick >= after

    def ranked(index: int, incoming_ok: Callable[[str], bool],
               mover_ok: Callable[[str], bool]) -> list[tuple[str, int | None]]:
        """Every way to fill slot ``index`` by the ranking Tuesday printed its
        plans by (``rank_covers``)."""
        return rank_covers(
            index, slots, bench,
            eligible_for=lambda pid, slot: eligible(position(pid), slot),
            value=value,
            questionable=lambda pid: state(pid).designation == QUESTIONABLE,
            practice_squad=lambda pid: state(pid).practice_squad,
            incoming_ok=incoming_ok,
            mover_ok=lambda pid: pid not in dropped and mover_ok(pid))

    def fill(index: int, after: datetime | None = None) -> tuple[str, int | None] | None:
        """Who takes slot ``index``: straight off the bench, or by sliding a
        flex starter across and filling the flex from the bench — the best
        by the shared ranking. (bench id, flex index). No bench player already
        placed or named, and nobody another game-day plan moves. ``after``:
        everyone moved must kick off no earlier (launch review RQ-01 — a plan
        for a game-day ruling can only move unlocked players)."""
        def ready(pid: str) -> bool:
            return state(pid).available and starts_after(pid, after)
        options = ranked(index, lambda pid: pid not in used and ready(pid),
                         lambda pid: pid not in planned and ready(pid))
        return options[0] if options else None

    def also_questionable(pid: str) -> str:
        if state(pid).practice_squad:
            return f" {elevation_note(name(pid))}."
        return (f" He's questionable too, so check on him Sunday morning."
                if state(pid).designation == QUESTIONABLE else "")

    def hold(placed: tuple[str, int | None], what: str) -> None:
        """Name everyone a game-day plan moves, once: two plans must never
        lean on the same player, because each is carried out alone, at the
        inactives, and both may be needed."""
        incoming, via = placed
        used.add(incoming)
        for pid in [incoming] + ([slots[via][1]] if via is not None else []):
            if pid:
                planned.add(pid)
                held_by.setdefault(pid, what)

    def nobody_left(index: int) -> str:
        """Why no cover was found, by name and true (recheck ENG-2/RQ2-05/
        BE2-D4): a healthy player already named for someone else, or one
        whose game has kicked off, is neither out nor on bye."""
        slot, own = slots[index]
        options = ranked(index, lambda pid: pid != own, lambda pid: True)
        named: list[str] = []
        rest = False
        for incoming, via in options:
            mover = slots[via][1] if via is not None else None
            for pid, taken in ((incoming, incoming in used),
                               (mover, mover in planned)):
                if not pid:
                    continue
                if taken and pid in held_by:
                    fact = f"{name(pid)} is already {held_by[pid]}"
                elif state(pid).locked:
                    fact = _played(name(pid), state(pid).kickoff)
                else:
                    rest = rest or not state(pid).available
                    continue
                if fact not in named:
                    named.append(fact)
        # A starter refused as the one sliding across is no option either, and
        # "out or on bye" would be false of him.
        for via, (other, mover) in enumerate(slots):
            if (via == index or not mover or mover in dropped
                    or other not in FLEX_ELIGIBILITY
                    or not eligible(position(mover), slot)
                    or not state(mover).available):
                continue
            if state(mover).designation == QUESTIONABLE:
                named.append(f"{name(mover)} is questionable too")
            elif state(mover).practice_squad:
                named.append(f"{name(mover)} is on the practice squad")
        others = f"every other {slot} option on your roster is out or on bye"
        if not named:
            return others if rest else f"nobody else on your roster can play {slot}"
        return clauses(named + ([others] if rest else []))

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
                f"{name(pid)} is {current.reason or 'ruled out'}, and "
                f"{nobody_left(index)}. If you can add one before kickoff, do."))
            continue
        incoming, via = placed
        used.add(incoming)
        held_by.setdefault(incoming, f"starting for {name(pid)}")
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
         and not state(pid).practice_squad
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
        held_by.setdefault(incoming, f"starting over {name(displaced)}")
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
            # Still questionable on the final report means a game-day call:
            # he is ruled in or out at the inactives, 90 minutes before HIS
            # kickoff, and only someone whose game has not started can go in
            # then (launch review RQ-01: "If he's ruled out, start Ladd
            # McConkey at FLEX" — a Sunday 4:25 PM player — about Terry
            # McLaurin on Monday night).
            news = (current.kickoff - INACTIVES_LEAD
                    if current.kickoff is not None else None)
            placed = fill(index, news)
            early = fill(index) if placed is None and news is not None else None
            # The reason is worked out BEFORE this plan names anyone, so it
            # never cites the plan's own cover.
            reason = nobody_left(index) if not (placed or early) else ""
            if placed or early:
                # Named once: two questionable starters must not both be
                # told the same bench player is their cover, nor slide the
                # same starter — each is carried out alone, at the inactives.
                hold(placed or early, f"{name(pid)}'s fallback")
            # The mover and the slot the newcomer takes are both named: "start
            # X and move Y to WR — he projects 12.3" left "he" and X's slot
            # to guesswork (proving run, 2025 week 4).
            plan_b = ((f"If he's ruled out, move {name(slots[placed[1]][1])} to "
                       f"{slot} and start {name(placed[0])} at "
                       f"{slots[placed[1]][0]}"
                       if placed[1] is not None else
                       f"If he's ruled out, start {name(placed[0])} at {slot}")
                      + f" ({_number(players[placed[0]], basis)})."
                      + (f" {elevation_note(name(placed[0]))}."
                         if state(placed[0]).practice_squad else "")
                      if placed else
                      _decide_first(name(pid), slot, early, slots, name, state, news)
                      if early else
                      f"{reason[:1].upper()}{reason[1:]}, so keep him in.")
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


def _et(moment: datetime) -> str:
    """"Sun 1:00 PM ET" for a timezone-aware moment."""
    from zoneinfo import ZoneInfo
    local = moment.astimezone(ZoneInfo(NFL_TIME)) if moment.tzinfo else moment
    return (f"{local.strftime('%a')} {local.hour % 12 or 12}:{local.minute:02d} "
            f"{'AM' if local.hour < 12 else 'PM'} ET")


def _decide_first(starter: str, slot: str, placed: tuple[str, int | None],
                  slots: list[tuple[str, str | None]], name, state,
                  news: datetime) -> str:
    """The only cover kicks off before the game-day ruling: the call an
    expert makes (RQ-01) — decide before that kickoff, with no number on
    either side."""
    incoming, via = placed
    moving = [incoming] + ([slots[via][1]] if via is not None else [])
    # The one whose game starts first binds the plan, and is the one named
    # (recheck ENG-1: the mover in a slide, not the incoming player).
    who, first = first_to_kick_off(moving, lambda pid: state(pid).kickoff)
    move = (f"start {name(incoming)}" if via is None else
            f"move {name(slots[via][1])} to {slot} and start {name(incoming)} "
            f"at {slots[via][0]}")
    when = f" at {_et(first)}" if first else " first"
    squad = (f" {elevation_note(name(incoming))}."
             if state(incoming).practice_squad else "")
    return (f"{name(who or incoming)} kicks off{when}, before {starter}'s inactives "
            f"(about {_et(news)}). Decide before then: {move}, or keep {starter} "
            f"and take a zero if he sits.{squad}")


def _played(who: str, kicked_off: datetime | None) -> str:
    """"Bo Nix played Thursday" — a cover whose game has already kicked off
    is neither out nor on bye (panel review BE2-D4)."""
    if kicked_off is None:
        return f"{who}'s game has already kicked off"
    from zoneinfo import ZoneInfo
    local = (kicked_off.astimezone(ZoneInfo(NFL_TIME)) if kicked_off.tzinfo
             else kicked_off)
    return f"{who} played {local.strftime('%A')}"


def clauses(parts: Sequence[str]) -> str:
    """Whole clauses joined as a sentence reads them: "A", "A, and B",
    "A, B, and C" — the comma keeps two facts about two players apart."""
    parts = list(parts)
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def worth_sending(changes: list[Change]) -> bool:
    """RULE F3."""
    return any(c.kind in TRIGGERS for c in changes)
