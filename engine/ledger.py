"""The published-calls ledger: record at publish time, grade when games end.

This is principle 2 made durable. The weekly pipeline APPENDS every probability
it actually published (slot confidences + the regret call) the moment a report
is built; a separate grading pass later settles each call against the real box
score. Nothing enters retroactively, nothing is edited after grading, and the
public ledger page is generated only from graded entries — so the record shown
to the world is, by construction, the record of what was published.

Grading safety (the receipts brand dies on one premature grade):
    RULE L1  A call is gradeable only when BOTH players' games for that week
             are final. Teams come from the week's availability snapshot —
             which exists for every published call by construction, because
             confidence only publishes when availability was known. Game
             finality comes from the cached NFL schedule (status "complete").
             A completed season (league status "complete") is always final.
    RULE L2  HIT = published pick outscored the alternative; MISS = it didn't;
             TIE = exactly equal, excluded from the record, shown separately.
    RULE L3  A player absent from the week's scoring record grades VOID, shown
             separately — never silently dropped, never guessed. Both players
             at exactly 0.0 is also VOID: per the Phase 2 data finding, 0.0
             means "did not play", and a non-event must not count as a tie.
    RULE L4  Once graded, an entry is immutable. Re-running any pipeline step
             must not change it (append is idempotent by call_id).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from engine.availability import load_week_availability
from engine.roster import DEFENSE


class LedgerError(ValueError):
    """A ledger file that cannot be trusted. Raised loudly with file+line —
    a public record must never be silently repaired or partially read."""

PENDING = "pending"
GRADED = "graded"
VOID = "void"

HIT = "hit"
MISS = "miss"
TIE = "tie"


@dataclass
class LedgerCall:
    """One published call. Identity is (league, season, week, roster, slot,
    pick, over) — re-publishing the same call is the same call."""

    call_id: str
    source: str                # "slot" (report lineup) | "coinflip" (public Friday call)
    league_id: str
    season: str
    week: int
    roster_id: int
    slot: str
    pick_id: str
    pick_name: str
    over_id: str
    over_name: str
    confidence: float
    is_regret: bool = False    # this slot call was also the week's Regret Score
    recorded_at: str = ""
    status: str = PENDING
    outcome: str | None = None
    pick_points: float | None = None
    over_points: float | None = None
    graded_at: str | None = None
    void_reason: str | None = None

    @property
    def margin(self) -> float | None:
        if self.pick_points is None or self.over_points is None:
            return None
        return self.pick_points - self.over_points


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _call_id(league_id: str, season: str, week: int, roster_id: int,
             slot: str, pick_id: str, over_id: str) -> str:
    key = f"{league_id}|{season}|{week}|{roster_id}|{slot}|{pick_id}|{over_id}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def ledger_path(processed_dir: Path, league_id: str) -> Path:
    return Path(processed_dir) / "ledger" / league_id / "calls.jsonl"


# --------------------------------------------------------------------- #
# recording
# --------------------------------------------------------------------- #

def extract_published_calls(report: Mapping[str, Any]) -> list[LedgerCall]:
    """Every probability the report actually published, from its JSON.

    Slots whose confidence was gated contribute nothing — the ledger records
    what subscribers saw, not what the engine privately computed.
    """
    meta = report["meta"]
    regret = report.get("regret") or {}
    regret_pair = (regret.get("start_id"), regret.get("over_id"))
    calls: list[LedgerCall] = []
    for slot in report.get("lineup", []):
        if slot.get("confidence") is None:
            continue
        pick_id = slot.get("player_id")
        over_id = slot.get("alternative_id")
        if not pick_id or not over_id:
            continue
        calls.append(LedgerCall(
            call_id=_call_id(meta["league_id"], meta["season"], meta["week"],
                             meta["my_roster_id"], slot["slot"],
                             str(pick_id), str(over_id)),
            source="slot",
            league_id=str(meta["league_id"]),
            season=str(meta["season"]),
            week=int(meta["week"]),
            roster_id=int(meta["my_roster_id"]),
            slot=str(slot["slot"]),
            pick_id=str(pick_id),
            pick_name=str(slot.get("player_name") or pick_id),
            over_id=str(over_id),
            over_name=str(slot.get("alternative_name") or over_id),
            confidence=float(slot["confidence"]),
            is_regret=(pick_id, over_id) == regret_pair,
            recorded_at=_now_iso(),
        ))
    return calls


_KNOWN_FIELDS = {f.name for f in fields(LedgerCall)}


def load_ledger(path: Path) -> list[LedgerCall]:
    if not path.is_file():
        return []
    calls: list[LedgerCall] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            # Unknown fields from a newer schema are dropped, not fatal;
            # missing required fields ARE fatal — that's corruption.
            calls.append(LedgerCall(**{k: v for k, v in raw.items()
                                       if k in _KNOWN_FIELDS}))
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise LedgerError(
                f"ledger {path} line {line_no} is unreadable ({exc}) — "
                "the public record must be fixed by hand, never skipped") from exc
    return _collapse(calls, path)


def _collapse(calls: list["LedgerCall"], path: Path) -> list["LedgerCall"]:
    """One row per call_id, because two crons can both append to this file.

    The Monday and Tuesday runs each commit and push their own copy, and an
    append-only JSONL is merged with git's `union` driver (.gitattributes) so a
    push race concatenates rather than conflicting — otherwise a rebase failure
    loses published probabilities, which cannot be recorded retroactively.
    Union merge duplicates the overlapping lines, so the reader has to collapse
    them or the public page shows one call twice and the summary counts it as
    two pieces of evidence.

    A PENDING duplicate loses to a graded one — that is just the other cron
    having settled it. Two DIFFERENT graded outcomes for one call_id is real
    corruption and raises: the module's rule is that a public record is fixed by
    hand, never silently repaired, and "which of these two answers do you want"
    is exactly the question nobody should answer automatically.
    """
    seen: dict[str, LedgerCall] = {}
    for call in calls:
        held = seen.get(call.call_id)
        if held is None:
            seen[call.call_id] = call
            continue
        if held.status == GRADED and call.status == GRADED \
                and held.outcome != call.outcome:
            raise LedgerError(
                f"ledger {path} records call {call.call_id} twice with "
                f"different outcomes ({held.outcome} and {call.outcome}) — "
                f"the public record must be fixed by hand, never guessed")
        if call.status != PENDING and held.status == PENDING:
            seen[call.call_id] = call
    return list(seen.values())


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    """Exclusive lock spanning a read-modify-write. Two pipelines writing the
    same league's ledger concurrently must serialize, or one silently erases
    the other's published calls (RULE L4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("w", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write_ledger(path: Path, calls: Iterable[LedgerCall]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for call in calls:
            fh.write(json.dumps(asdict(call), separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def record_calls(path: Path, new_calls: Iterable[LedgerCall]) -> int:
    """Append calls not already present (RULE L4: idempotent). Returns count added."""
    with _ledger_lock(path):
        existing = load_ledger(path)
        known = {c.call_id for c in existing}
        added = [c for c in new_calls if c.call_id not in known]
        if added:
            _write_ledger(path, existing + added)
        return len(added)


# --------------------------------------------------------------------- #
# grading
# --------------------------------------------------------------------- #

def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _week_game_status(raw_dir: Path, season: str) -> dict[int, dict[str, str]]:
    """week -> {team: game status} from the cached schedule."""
    games = _load_json(Path(raw_dir) / "schedule" / f"nfl_regular_{season}.json")
    table: dict[int, dict[str, str]] = {}
    for game in games if isinstance(games, list) else []:
        if not isinstance(game, dict) or not isinstance(game.get("week"), int):
            continue
        status = str(game.get("status") or "")
        for side in ("home", "away"):
            team = game.get(side)
            if isinstance(team, str) and team:
                table.setdefault(game["week"], {})[team] = status
    return table


def _league_complete(raw_dir: Path, league_id: str) -> bool:
    doc = _load_json(Path(raw_dir) / "league" / league_id / "league.json")
    return isinstance(doc, dict) and doc.get("status") == "complete"


def _call_is_final(call: LedgerCall, raw_dir: Path,
                   games: dict[int, dict[str, str]],
                   league_complete: bool) -> bool:
    """RULE L1. Conservative on every unknown: not final."""
    if league_complete:
        return True
    availability = load_week_availability(raw_dir, call.season, call.week)
    if not availability.has_snapshot:
        return False
    assert availability.statuses is not None
    week_games = games.get(call.week, {})
    for player_id in (call.pick_id, call.over_id):
        record = availability.statuses.get(player_id)
        team = record.get("team") if isinstance(record, dict) else None
        if not team or week_games.get(team) != "complete":
            return False
    return True


# The roster product's ledger store is named for the rule its calls were made
# under: `typed-{scoring}-{season}` (engine/subscriber.py). That is not
# decoration — "did the pick outscore the alternative" has a DIFFERENT answer
# under PPR and standard, so a ledger that cannot tell them apart cannot be
# graded correctly for either. Measured on real 2024 week-10 data before the id
# carried the preset: 5 of 6 calls collided across presets while publishing
# different probabilities.
TYPED_LEDGER_RE = re.compile(
    r"^typed-(?P<scoring>[a-z_]+)-(?P<size>\d+)-(?P<season>\d{4})$")


def scoring_of(league_id: str) -> str | None:
    """The scoring preset a `typed-*` ledger's calls were made under."""
    match = TYPED_LEDGER_RE.match(league_id or "")
    return match.group("scoring") if match else None


def league_size_of(league_id: str) -> int | None:
    """The league size those calls were made in. Part of the identity because
    it moves the published probability (see engine/subscriber.py)."""
    match = TYPED_LEDGER_RE.match(league_id or "")
    return int(match.group("size")) if match else None


def grade_ledger_nflverse(path: Path, cache_dir: Path) -> tuple[int, int]:
    """Grade a roster-product ledger against nflverse. No league is read.

    RULES L1-L4 are unchanged and are not reimplemented here — this supplies
    only where finality and points come from, and `_grade_locked` applies the
    same decision it applies to the league path.

    **The one grading rule this data source forces us to state, stated before a
    single row is graded (principle 2).** A rostered player with no stat row for
    a final week scored **0.0**, not "no record". Sleeper wrote an explicit 0.0
    for exactly that player, so this keeps the two stacks identical: 0.0-vs-0.0
    is still VOID by RULE L3 (the absence signal, not a result), and
    0.0-vs-12.3 is still a MISS. Mapping absence to "no record" instead would
    VOID every call whose pick did not play while the alternative scored —
    which is a real miss, and voiding it would flatter the published record in
    precisely the direction nobody should trust us on.
    """
    from engine.scoring import preset, score, score_defense
    from ingest.nflverse import NflverseError, defense_rows, season_rows

    seasons: dict[str, dict] = {}

    def load(season: str) -> dict:
        if season not in seasons:
            try:
                weekly = season_rows(cache_dir, season, live=True)
            except NflverseError:
                weekly = {}
            try:
                defenses = defense_rows(cache_dir, season, live=True)
            except NflverseError:
                defenses = {}
            # Which teams we have actually OBSERVED a box score for, per week.
            # This is the presence check `is_final` needs; it is not the same
            # question as "did the schedule say the game finished".
            observed: dict[int, set[str]] = {}
            for week, rows in weekly.items():
                for row in rows.values():
                    team = (row.get("team") or "").strip()
                    if team:
                        observed.setdefault(week, set()).add(team)
            seasons[season] = {"weekly": weekly, "defenses": defenses,
                               "observed": observed,
                               "final": _final_teams(cache_dir, season)}
        return seasons[season]

    def team_of(call: LedgerCall, player_id: str, data: dict) -> str | None:
        if player_id.startswith(f"{DEFENSE}-"):
            return player_id[len(DEFENSE) + 1:]
        row = (data["weekly"].get(call.week) or {}).get(player_id)
        team = (row or {}).get("team")
        return str(team).strip() if team else None

    def is_final(call: LedgerCall) -> bool:
        """RULE L1, against TWO sources that can disagree about freshness.

        Finality comes from the schedule and points come from the weekly stat
        release — different files, fetched independently. Checking only the
        schedule was a reproduced record-corrupting bug: with the stats
        download failed or merely lagging, both players scored "absent" = 0.0,
        RULE L3 voided the call as a non-event, and RULE L4 made that permanent.
        One outage silently erased real hits and misses from the public record.

        So a week is gradeable only when its BOX SCORES ARE IN: every team whose
        game the schedule calls final must actually appear in the week's stat
        rows. Then, and only then, does "this player has no row" unambiguously
        mean he did not play — which is what makes scoring him 0.0 honest
        rather than a guess about missing data.
        """
        data = load(call.season)
        final = data["final"].get(call.week)
        if not final:
            return False                      # week not in the schedule: unknown
        played = {team for team in final if team != "__all__"}
        if not played or not (played <= data["observed"].get(call.week, set())):
            return False                      # the box scores have not landed
        for player_id in (call.pick_id, call.over_id):
            team = team_of(call, player_id, data)
            # A player with no row is a player who did not play, now that the
            # week's box scores are known to be complete.
            if team is not None and team not in final:
                return False
        return True

    def points_of(call: LedgerCall, player_id: str, data: dict, rule) -> float:
        if player_id.startswith(f"{DEFENSE}-"):
            row = (data["defenses"].get(call.week) or {}).get(
                player_id[len(DEFENSE) + 1:])
            if row is None:
                return 0.0
            scored = score_defense(row, row.get("points_allowed"))
            return 0.0 if scored is None else float(scored)
        row = (data["weekly"].get(call.week) or {}).get(player_id)
        # See the docstring: no row means he produced nothing, not that we have
        # no record of him.
        return 0.0 if row is None else float(score(row, rule))

    def points_for(call: LedgerCall) -> tuple[Any, Any] | None:
        scoring = scoring_of(call.league_id)
        if scoring is None:
            return None       # not a roster-product ledger; leave it alone
        try:
            rule = preset(scoring)
        except Exception:     # noqa: BLE001 - an unknown preset is not gradeable
            return None
        data = load(call.season)
        return (points_of(call, call.pick_id, data, rule),
                points_of(call, call.over_id, data, rule))

    with _ledger_lock(path):
        return _grade_locked(path, _Sources(is_final=is_final,
                                            points_for=points_for))


def _final_teams(cache_dir: Path, season: str) -> dict[int, dict[str, bool]]:
    """week -> teams whose REG game has a final score, plus an `__all__` flag.

    A game with either score missing has not been played (or not been posted),
    and RULE L1 is conservative on every unknown.
    """
    import csv as _csv

    from ingest.nflverse import NflverseError, fetch

    try:
        path = fetch("schedules", "games.csv", cache_dir, live=True)
    except NflverseError:
        return {}
    weeks: dict[int, dict[str, bool]] = {}
    played: dict[int, int] = {}
    total: dict[int, int] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in _csv.DictReader(handle):
            if str(row.get("season") or "") != str(season):
                continue
            if (row.get("game_type") or "REG").upper() != "REG":
                continue
            try:
                week = int(row.get("week") or 0)
            except ValueError:
                continue
            if not week:
                continue
            total[week] = total.get(week, 0) + 1
            home, away = (row.get("home_team") or ""), (row.get("away_team") or "")
            done = bool((row.get("home_score") or "").strip()
                        and (row.get("away_score") or "").strip())
            if done:
                played[week] = played.get(week, 0) + 1
                for team in (home, away):
                    if team:
                        weeks.setdefault(week, {})[team] = True
    for week, count in total.items():
        if count and played.get(week, 0) == count:
            weeks.setdefault(week, {})["__all__"] = True
    return weeks


def grade_ledger(path: Path, raw_dir: Path) -> tuple[int, int]:
    """Grade every pending call whose games are final, from the LEAGUE cache.

    Returns (graded_count, still_pending_count). Already-graded entries are
    never touched (RULE L4).
    """
    with _ledger_lock(path):
        return _grade_locked(path, _sleeper_sources(raw_dir))


def _sleeper_sources(raw_dir: Path) -> "_Sources":
    """Finality and points as read from a cached league. The original path."""
    games_by_season: dict[str, dict[int, dict[str, str]]] = {}
    complete_by_league: dict[str, bool] = {}

    def is_final(call: LedgerCall) -> bool:
        if call.season not in games_by_season:
            games_by_season[call.season] = _week_game_status(raw_dir, call.season)
        if call.league_id not in complete_by_league:
            complete_by_league[call.league_id] = _league_complete(raw_dir, call.league_id)
        return _call_is_final(call, raw_dir, games_by_season[call.season],
                              complete_by_league[call.league_id])

    def points_for(call: LedgerCall) -> tuple[Any, Any] | None:
        matchups = _load_json(Path(raw_dir) / "league" / call.league_id
                              / "matchups" / f"week_{call.week:02d}.json")
        for record in matchups if isinstance(matchups, list) else []:
            if isinstance(record, dict) and record.get("roster_id") == call.roster_id:
                points = record.get("players_points") or {}
                return points.get(call.pick_id), points.get(call.over_id)
        # Matchup record missing entirely: stay pending and retry later, which
        # is not the same as "he did not score" and must not grade as one.
        return None

    return _Sources(is_final=is_final, points_for=points_for)


@dataclass(frozen=True)
class _Sources:
    """Where finality and points come from. The RULES do not live here.

    Two data stacks now feed the same grader — a cached league, and nflverse for
    the roster product — and RULES L1-L4 must be identical under both. A second
    copy of the hit/miss/void decision is exactly how a public record starts
    grading two ways.
    """

    is_final: Any            # (LedgerCall) -> bool
    points_for: Any          # (LedgerCall) -> tuple[float | None, float | None] | None


def _grade_locked(path: Path, sources: "_Sources") -> tuple[int, int]:
    calls = load_ledger(path)
    if not calls:
        return 0, 0
    graded_now = 0

    for call in calls:
        if call.status != PENDING:
            continue
        if not sources.is_final(call):
            continue

        got = sources.points_for(call)
        if got is None:
            continue  # scoring record missing entirely: stay pending, retry later
        pick_points, over_points = got
        call.graded_at = _now_iso()
        if not isinstance(pick_points, (int, float)) or not isinstance(over_points, (int, float)):
            call.status = VOID
            missing = call.pick_name if not isinstance(pick_points, (int, float)) else call.over_name
            call.void_reason = f"no scoring record for {missing} (RULE L3)"
        elif pick_points == 0.0 and over_points == 0.0:
            call.status = VOID
            call.void_reason = ("both players scored exactly 0.0 — the absence "
                                "signal, not a result (RULE L3)")
        else:
            call.status = GRADED
            call.pick_points = float(pick_points)
            call.over_points = float(over_points)
            if pick_points > over_points:
                call.outcome = HIT
            elif pick_points < over_points:
                call.outcome = MISS
            else:
                call.outcome = TIE
        graded_now += 1

    if graded_now:
        _write_ledger(path, calls)
    still_pending = sum(1 for c in calls if c.status == PENDING)
    return graded_now, still_pending


# --------------------------------------------------------------------- #
# summaries — the numbers every public surface cites
# --------------------------------------------------------------------- #

def load_all_ledgers(processed_dir: Path) -> list[LedgerCall]:
    """Every league's ledger, combined — the public page must reflect every
    published call, not just the configured league's."""
    root = Path(processed_dir) / "ledger"
    calls: list[LedgerCall] = []
    if root.is_dir():
        for path in sorted(root.glob("*/calls.jsonl")):
            calls.extend(load_ledger(path))
    return calls


def ledger_summary(calls: list[LedgerCall]) -> dict[str, Any]:
    graded = [c for c in calls if c.status == GRADED]
    decided = [c for c in graded if c.outcome in (HIT, MISS)]
    hits = [c for c in decided if c.outcome == HIT]
    buckets: list[dict[str, Any]] = []
    for low, high in ((0.50, 0.55), (0.55, 0.60), (0.60, 0.65),
                      (0.65, 0.70), (0.70, 0.80), (0.80, 1.01)):
        rows = [c for c in decided if low <= c.confidence < high]
        if not rows:
            continue
        buckets.append({
            "label": f"{low:.0%}–{min(high, 1.0):.0%}",
            "decided": len(rows),
            "stated": sum(c.confidence for c in rows) / len(rows),
            "observed": sum(1 for c in rows if c.outcome == HIT) / len(rows),
        })
    best = max(decided, key=lambda c: c.margin or 0.0, default=None)
    worst = min(decided, key=lambda c: c.margin or 0.0, default=None)
    return {
        "recorded": len(calls),
        "pending": sum(1 for c in calls if c.status == PENDING),
        "void": sum(1 for c in calls if c.status == VOID),
        "graded": len(graded),
        "hits": len(hits),
        "misses": len(decided) - len(hits),
        "ties": len(graded) - len(decided),
        "hit_rate": len(hits) / len(decided) if decided else None,
        "buckets": buckets,
        "best": best,
        "worst": worst,
    }


def public_entries(calls: list[LedgerCall]) -> list[dict[str, Any]]:
    """The anonymized view for site/ledger — no league ids, no roster ids.

    Player names and results are public NFL facts; which league the call was
    made in is a subscriber's business and stays private.

    ``scoring`` IS published, and it is not decoration. The same head-to-head
    published to a PPR subscriber and a standard-scoring one is two different
    probabilities resolved by one real game; without the preset the two render
    as identical duplicate rows, and the shrink guard — which keys on what it
    can see here — cannot tell a whole store disappearing from a coincidence.
    It is buyer vocabulary, not implementation: "we called this in a PPR league"
    is a fact a reader of the record is entitled to.

    KNOWN LIMITATION, stated rather than hidden: those rows are CORRELATED —
    one game decides all of them — so the aggregate below counts them as
    separate evidence when they are not fully independent. That is the same
    dependence reports/nflverse-backtest.md handles with a cluster bootstrap
    over (season, week), and the public summary does not. Revisit before the
    ledger is promoted back into the funnel; it cannot mislead much while the
    subscriber base is small enough that duplicate head-to-heads are rare.
    """
    rows = []
    for call in sorted(calls, key=lambda c: (c.season, c.week, c.slot)):
        if call.status == PENDING:
            continue
        rows.append({
            "season": call.season,
            "week": call.week,
            "slot": call.slot,
            "scoring": scoring_of(call.league_id),
            "league_size": league_size_of(call.league_id),
            "pick": call.pick_name,
            "over": call.over_name,
            "confidence": round(call.confidence, 3),
            "status": call.status,
            "outcome": call.outcome,
            "margin": round(call.margin, 1) if call.margin is not None else None,
            "void_reason": call.void_reason,
            "regret": call.is_regret,
        })
    return rows
