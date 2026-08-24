"""One subscriber's week, built from their own roster and nflverse alone.

This is the Tuesday path for the product PLAN §0 describes: the subscriber
types their roster, the payment carries it, and nothing here ever asks a league
platform for anything. ``engine/solo_report.py`` already knew how to build the
report; what did not exist was anything that fed it real data, so
``build_solo_report`` was reachable only from a test while every runnable entry
point still went through Sleeper.

Three things this module is responsible for:

**The calendar, without asking anyone.** ``current_season`` / ``current_week``
read the schedule release. The Sleeper path took both from ``/v1/state/nfl``,
which is exactly the sort of small convenient call that keeps a licence
dependency alive.

**The shared per-week load.** Everything that does not depend on WHOSE roster
it is — the directory, the season's stat rows, team defenses, the injury
report, byes, last season for the positional prior — is fetched once into
``WeekData`` and reused across every subscriber. The cost NFR is per-week, not
per-subscriber: a hundred subscribers cost the same downloads as one.

**Availability, honestly.** ``WeekAvailability`` was written against weekly
Sleeper snapshots. The nflverse injury archive is a different shape and one
difference is load-bearing: it holds a row only for players who APPEARED ON A
REPORT. Building statuses from it alone would leave every healthy player
UNKNOWN; building them from the directory alone would call a week with no
published report a clean bill of health for the entire league. So statuses are
built from the directory and overlaid with the week's designations, and a week
the archive does not cover yields NO snapshot at all (principle 1: unknowable
never means cleared).
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

from engine.availability import WeekAvailability
from engine.history import PlayerIndex, Season
from engine.projection import ProjectionModel
from engine.roster import PlayerDirectory, load_directory
from engine.solo_report import build_solo_report
from engine.subscriber import (RosterSpec, build_season, merge_defenses,
                               player_index, rosterable_field)
from engine.usage import Usage, usage_line
from ingest import injuries as injuries_feed
from ingest.nflverse import (ATTRIBUTION, SCORING_COLUMNS, NflverseError,
                             _float, _int, fetch, season_rows, season_teams)
from run.refs import RosterRef

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "nflverse"

# How many completed weeks the counted-usage line looks back over. Same window
# the Sleeper-era report used, so the sentence a subscriber reads is unchanged.
USAGE_WINDOW = 4

# What one parse of the season has to carry: everything engine.scoring reads,
# plus the counted-usage columns. Reading the season twice — once for points and
# once for usage — doubles both the parse and the memory for no gain, and the
# second read was the full 150-column row.
USAGE_COLUMNS = frozenset({"targets", "receiving_air_yards", "carries"})
SEASON_COLUMNS = SCORING_COLUMNS | USAGE_COLUMNS


class SoloError(RuntimeError):
    """The week could not be built for this roster."""


# --------------------------------------------------------------------- #
# the calendar, from the schedule release
# --------------------------------------------------------------------- #

def _schedule(cache_dir: Path, *, live: bool = True,
              session: requests.Session | None = None) -> list[dict[str, str]]:
    path = fetch("schedules", "games.csv", cache_dir, live=live, session=session)
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle)
                if (row.get("game_type") or "REG").upper() == "REG"]


def _weeks(rows: list[dict[str, str]], season: str) -> dict[int, list[str]]:
    """week -> the gamedays in it, for one season."""
    out: dict[int, list[str]] = {}
    for row in rows:
        if str(row.get("season") or "") != str(season):
            continue
        week = _int(row.get("week"))
        day = (row.get("gameday") or "").strip()
        if week and day:
            out.setdefault(week, []).append(day)
    return out


def current_season(cache_dir: Path, today: date | None = None, *,
                   session: requests.Session | None = None) -> str:
    """The season we are in or about to play.

    The latest season whose last regular-season game has not been played yet;
    failing that, the latest season in the file. The fallback only fires in the
    offseason gap before a schedule is published, when there is no product
    anyway — and returning the season that just ended is far safer than
    guessing the next one, because a report about a season that is over is the
    quietest principle-3 violation in the codebase (CLAUDE.md).
    """
    rows = _schedule(cache_dir, session=session)
    seasons = sorted({str(row.get("season") or "") for row in rows if row.get("season")})
    if not seasons:
        raise SoloError("the schedule release carries no regular-season games")
    when = today or datetime.now(timezone.utc).date()
    for season in seasons:                       # ascending: earliest match wins
        days = [d for week in _weeks(rows, season).values() for d in week]
        if days and max(days) >= when.isoformat():
            return season
    return seasons[-1]


def current_week(cache_dir: Path, season: str, today: date | None = None, *,
                 session: requests.Session | None = None) -> int:
    """The week a report written today is ABOUT.

    The first week whose last game has not been played. Run on a Tuesday that
    is the week ahead, which is what the product delivers; run mid-week it is
    still the current one, which is what someone re-running the pipeline means.
    """
    weeks = _weeks(_schedule(cache_dir, session=session), season)
    if not weeks:
        raise SoloError(f"the schedule release carries no {season} regular season")
    when = (today or datetime.now(timezone.utc).date()).isoformat()
    for week in sorted(weeks):
        if max(weeks[week]) >= when:
            return week
    return max(weeks)                            # season over: the last week


# --------------------------------------------------------------------- #
# the per-week load, shared across every subscriber
# --------------------------------------------------------------------- #

@dataclass(frozen=True)
class WeekData:
    """Everything one week needs that does not depend on whose roster it is."""

    season: str
    week: int
    directory: PlayerDirectory
    players: PlayerIndex
    weekly: dict[int, dict[str, Mapping[str, object]]]
    prior: dict[int, dict[str, dict[str, str]]]
    availability: WeekAvailability
    usage: dict[str, Usage]
    attribution: str = ATTRIBUTION


def _statuses(directory: PlayerDirectory,
              injury: injuries_feed.InjuryWeek | None,
              weekly: Mapping[int, Mapping[str, Mapping[str, Any]]] | None = None,
              week: int | None = None) -> dict[str, dict[str, Any]] | None:
    """One record per player whose team is known, or None for no report.

    None is the whole point. The archive holds rows only for players who were
    listed, so "not in the file" means "nothing was wrong with him" — but only
    if the report EXISTS. Before it is published, the same emptiness means we
    have not looked yet, and calling that a clean bill of health for every
    player in the league is precisely the bypass principle 1 forbids.

    The team is the CARRY-FORWARD team — the one on his most recent stat row
    strictly before the report week, within this season — exactly as the
    frozen method reconstructs it (reports/nflverse-backtest-method.md §6). A
    player with no such row is omitted, which classifies him UNKNOWN and gates
    the call: fail closed. That costs nothing on the publishable population,
    because three prior appearances are required for a call and an appearance
    is a row with a team. When no season rows are supplied at all (a unit test
    of the report alone), the report's own team column stands in.
    """
    if injury is None or not injury.teams:
        return None
    out: dict[str, dict[str, Any]] = {}
    for player in directory.players:
        if weekly is not None and week is not None:
            team = _team_before(player.player_id, week, weekly)
            if team is None:
                team = injury.teams.get(player.player_id)
        else:
            team = injury.teams.get(player.player_id) or player.team
        if not team:
            continue                      # -> UNKNOWN -> gated
        out[player.player_id] = {
            "team": team,
            "position": player.position,
            "active": True,
            "injury_status": injury.by_gsis.get(player.player_id),
        }
    return out


def _team_before(player_id: str, week: int,
                 weekly: Mapping[int, Mapping[str, Mapping[str, Any]]]) -> str | None:
    """The team on the player's most recent stat row strictly before ``week``
    — the same lookup the backtest harness uses, so the live gate and the
    measured gate agree on who is even classifiable."""
    for earlier in range(week - 1, 0, -1):
        row = (weekly.get(earlier) or {}).get(player_id)
        if row:
            team = str(row.get("team") or "").strip()
            if team:
                return team
    return None


def _nflverse_usage(rows: Mapping[int, Mapping[str, Mapping[str, str]]],
                    before_week: int, window: int = USAGE_WINDOW) -> dict[str, Usage]:
    """Counted usage over the completed weeks before ``before_week``.

    Strictly before, like the Sleeper-era version: a live report must never
    read the week it is about. Weeks the player did not appear in do not
    contribute — they are not counted as zeros, which would understate exactly
    the returning starter worth flagging.

    RULE N2: snaps are Pro-Football-Reference-derived and are not read, so they
    are absent here rather than zero. RULE U1 still holds — every value is a
    count of something that already happened.
    """
    if before_week <= 1:
        return {}
    weeks = range(max(1, before_week - window), before_week)
    totals: dict[str, dict[str, float]] = {}
    played: dict[str, int] = {}
    present: dict[str, set[str]] = {}
    for week in weeks:
        for gsis, row in (rows.get(week) or {}).items():
            # Team defenses share this dict once merge_defenses has run, and a
            # team row carries the OFFENSE's counts — the Broncos defense read
            # "128 targets (32.0 a game), 115 carries", which is a real
            # sentence about the wrong team entirely. Usage is a player stat.
            if not gsis.startswith("00-"):
                continue
            played[gsis] = played.get(gsis, 0) + 1
            for key, column in (("targets", "targets"),
                                ("air_yards", "receiving_air_yards"),
                                ("carries", "carries")):
                value = _float(row.get(column))
                if value is None:
                    continue
                totals.setdefault(gsis, {})[key] = \
                    totals.setdefault(gsis, {}).get(key, 0.0) + value
                present.setdefault(gsis, set()).add(key)

    def counted(got: dict[str, float], seen: set[str], key: str) -> float | None:
        """A zero window total says nothing and is not reported.

        nflverse writes a real 0 where Sleeper wrote nothing at all, so a
        quarterback's line read "0 targets (0.0 a game), 21 carries" — true,
        and pure noise next to the count that is the story. When EVERY stat is
        zero the line disappears entirely, which is the honest render of a
        player who was given nothing: the appearance itself is already carried
        by form_games, and CLAUDE.md's rule is that an absent field renders
        absent rather than as a 0.
        """
        value = got.get(key) if key in seen else None
        return value if value else None

    out: dict[str, Usage] = {}
    for gsis, appearances in played.items():
        got = totals.get(gsis, {})
        seen = present.get(gsis, set())
        targets = counted(got, seen, "targets")
        carries = counted(got, seen, "carries")
        out[gsis] = Usage(
            weeks=appearances,
            targets=int(targets) if targets is not None else None,
            air_yards=counted(got, seen, "air_yards"),
            # Neither is first-party: red-zone targets are not in stats_player
            # and snaps are PFR-derived (RULE N2). Absent, never zero.
            rz_targets=None,
            snaps=None,
            carries=int(carries) if carries is not None else None,
        )
    return out


def load_week_data(cache_dir: Path = CACHE_DIR, season: str | None = None,
                   week: int | None = None, *, live: bool = True,
                   session: requests.Session | None = None) -> WeekData:
    """Fetch and assemble one week. Costs the same for one subscriber or a
    hundred — nothing in here depends on a particular roster."""
    cache_dir = Path(cache_dir)
    season = str(season) if season else current_season(cache_dir, session=session)
    week = int(week) if week else current_week(cache_dir, season, session=session)
    if week < 1:
        raise SoloError(f"week {week} is not a week")

    try:
        # live=True on BOTH. The directory is not static — players sign, get
        # cut and get traded every week — and a subscriber who rosters someone
        # the directory has never heard of is BLOCKED at intake with a paid,
        # undeliverable row. Fetched with live=False these froze at whatever day
        # the cache was first written.
        #
        # This is why the fix belongs here and not in the cron. Deleting the
        # cached copies before each run also forced a refresh, but it threw away
        # `fetch`'s deliberate "a cached copy beats an outage" fallback — so one
        # nflverse outage on a Tuesday meant a cold cache and NO REPORTS FOR
        # ANYONE. live=True revalidates on the 6h window and still falls back to
        # the cache when the download fails, which is both halves at once.
        players_csv = fetch("players", "players.csv", cache_dir, live=True,
                            session=session)
        teams_csv = fetch("teams", "teams_colors_logos.csv", cache_dir,
                          live=True, session=session)
        teams = season_teams(cache_dir, season, live=live, session=session)
    except NflverseError as exc:
        raise SoloError(f"could not load the player directory: {exc}") from exc
    if not teams:
        raise SoloError(f"the schedule release carries no {season} teams")
    directory = load_directory(players_csv, teams_csv,
                               min_last_season=int(season) - 1,
                               eligible_teams=teams)

    # The season's own stat rows. Before kickoff this release does not exist
    # yet, which is a real state and not an error: there is simply no form to
    # project from, and build_solo_report says so rather than inventing one.
    try:
        weekly: dict[int, dict[str, Any]] = season_rows(
            cache_dir, season, live=live, columns=SEASON_COLUMNS,
            session=session)
    except NflverseError:
        # Pre-kickoff this is a real state. MID-SEASON it is an outage wearing
        # week 1's clothes: an empty dict sends build_solo_report down the
        # week-1 branch, which tells the subscriber in their own words that the
        # season has not played its first games — a confident false statement,
        # exit 0, with the same report contradicting itself two lines later
        # ("no scored weeks for DEF-BAL before week 10"). One asset failing is
        # enough: a renamed release, a placeholder file, an actions/cache miss
        # on the eviction cycle the weekly cron sits on. Found Aug 24 2026.
        if week > 1:
            raise SoloError(
                f"the {season} weekly stat rows could not be loaded, and it is "
                f"week {week} — without them every number in this report would "
                f"be missing and the report would say the season has not "
                f"started, which is false. Refusing to build it.") from None
        weekly = {}
    if weekly:
        try:
            from ingest.nflverse import defense_rows
            merge_defenses(weekly, defense_rows(cache_dir, season, live=live,
                                                session=session))
        except NflverseError:
            # A defense with no rows scores as an absence, never as a shutout
            # (RULE S4) — the lineup still builds.
            pass
    try:
        prior = season_rows(cache_dir, str(int(season) - 1), session=session)
    except NflverseError as exc:
        raise SoloError(
            f"could not load {int(season) - 1} for the positional prior: {exc}"
        ) from exc

    return WeekData(
        season=season,
        week=week,
        directory=directory,
        players=player_index(directory),
        weekly=weekly,
        prior=prior,
        availability=_availability(cache_dir, season, week, directory,
                                   live=live, session=session, weekly=weekly),
        # Read off the rows already parsed above rather than re-reading the
        # whole season: the counted-usage columns are in SEASON_COLUMNS for
        # exactly this reason.
        usage=_nflverse_usage(weekly, week),
    )


def _availability(cache_dir: Path, season: str, week: int,
                  directory: PlayerDirectory, *, live: bool = True,
                  session: requests.Session | None = None,
                  weekly: Mapping[int, Mapping[str, Mapping[str, Any]]] | None = None,
                  ) -> WeekAvailability:
    """The injury report and byes, in the shape the gate reads — on the
    information set that exists when the report goes out.

    THE DESIGNATION USED IS WEEK W-1's, NOT WEEK W's. The product ships on
    Tuesday and week W's injury report is published Wednesday through Friday.
    Measured on the real 2024 archive: by the Tuesday send, week W held 0-2
    rows out of 200-385 in every week but one, while week W-1's report was
    100% complete every single week. Reading week W on a Tuesday therefore
    meant one of two wrong things — no snapshot at all, so no confidence
    anywhere in the product, or a two-row file treated as a complete clean
    bill of health. The frozen method (reports/nflverse-backtest-method.md
    §6) calls the W-1 rule "the single most consequential rule in this
    section", and it is what the Grade-C numbers were measured under; a live
    gate on any other information set is a gate nothing has measured.

    Week 1 has no W-1 report and yields no snapshot: everyone UNKNOWN, no
    number anywhere, which is already true of week 1 for evidence reasons.
    """
    from ingest.nflverse import bye_teams

    try:
        byes = bye_teams(cache_dir, season, week, live=live, session=session)
    except NflverseError:
        byes = None                      # unknowable, which classify() honours

    injury: injuries_feed.InjuryWeek | None = None
    try:
        # Through nflverse.fetch rather than injuries.fetch: the latter caches
        # forever, which is right for a finished season and wrong for the one
        # being played — week 5's report would be read out of a file downloaded
        # in week 2 and find no week-5 rows at all.
        path = fetch("injuries", f"injuries_{season}.csv", cache_dir, live=live,
                     session=session)
        injury = injuries_feed.load_weeks(path, season).get(week - 1)
    except (NflverseError, OSError):
        pass

    statuses = _statuses(directory, injury, weekly, week)
    basis = (f"the week {week - 1} injury report, the last complete one before "
             f"this file goes out") if statuses else None
    return WeekAvailability(season=season, week=week, snapshot_as_of=basis,
                            statuses=statuses, bye_teams=byes)


# --------------------------------------------------------------------- #
# one subscriber
# --------------------------------------------------------------------- #

# The early-season regime (reports/early-season-method.md §5, Grade B). The
# arm measured PPR, 12 teams, template T1 across weeks 2-3 of 2014-2024; the
# product seeds ONLY that. Other presets, sizes and lineup shapes ship no
# week-2-3 number until their own arms run.
EARLY_SEASON_LAMBDA = 0.5
MEASURED_TEMPLATE = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")


def seeded_scope(spec: RosterSpec, league_size: int, week: int) -> bool:
    """May this report use the prior-season seed? Every clause is the frozen
    method's, and the model's own SEEDED_WEEKS restriction backstops the week
    clause structurally."""
    from engine.projection import SEEDED_WEEKS
    return (week in SEEDED_WEEKS
            and spec.scoring == "ppr"
            and int(league_size) == 12
            and tuple(spec.slots) == MEASURED_TEMPLATE)


def spec_from_ref(ref: RosterRef, label: str = "Your Team") -> RosterSpec:
    return RosterSpec(player_ids=tuple(ref.player_ids), slots=tuple(ref.slots),
                      scoring=ref.scoring, label=label)


def report_for(spec: RosterSpec, data: WeekData, league_size: int = 12,
               cache_dir: Path = CACHE_DIR,
               processed_dir: Path | None = None) -> dict[str, Any]:
    """Build one subscriber's report from the shared week load."""
    # Against the DIRECTORY, not the PlayerIndex: `position()` answers "UNK"
    # for an id it has never seen rather than None, so the guard it was written
    # against never fired once and an unknown id would have rendered as a blank
    # row in a report somebody paid for.
    known = {player.player_id for player in data.directory.players}
    unknown = [pid for pid in spec.player_ids if pid not in known]
    if unknown:
        # A ref decodes to ids, not to players. An id the directory has never
        # heard of would render as a blank row in a paid report, so it fails
        # here where the operator can see whose signup is broken.
        raise SoloError(
            f"{len(unknown)} player id(s) on this roster are not in the "
            f"{data.season} directory: {', '.join(unknown[:5])}")

    field = rosterable_field(data.directory, data.prior, spec.rule, spec.slots,
                             league_size=league_size)
    season: Season = build_season(spec, data.weekly, data.directory,
                                  data.season, data.week,
                                  league_size=league_size, field=field)
    # The early-season seed (reports/early-season-method.md, Grade B): in
    # weeks 2-3, under exactly the settings the arm measured, a player's own
    # prior-season record enters at half weight so a call can exist before
    # three real games do. The model itself refuses to seed any other week,
    # so this wiring can only ever narrow the regime, never widen it.
    seeded = seeded_scope(spec, league_size, data.week)
    if seeded:
        from engine.nflverse_backtest import prior_self_observations
        model = ProjectionModel(season, data.players,
                                prior_self=prior_self_observations(
                                    data.prior, spec.rule),
                                prior_self_weight=EARLY_SEASON_LAMBDA)
    else:
        model = ProjectionModel(season, data.players)

    # Last season's per-game scoring, under THIS subscriber's rule. Used for two
    # things in week 1 and nothing else: which of two eligible players takes a
    # slot, and a line saying so. It is a record of what happened, never a
    # projection for this week — see _place_without_projections.
    prior_form = _prior_form(data.prior, spec.rule)

    def usage_lookup(player_id: str) -> str | None:
        line = data.usage.get(player_id)
        if line:
            return usage_line(line)
        # Week 1: no counted usage exists yet, and an empty row leaves the
        # reader no way to check why this player is starting over that one.
        return _prior_form_line(player_id, data.prior, spec.rule)

    report = build_solo_report(spec, season, data.players, model,
                               data.availability, data.week, Path(cache_dir),
                               usage_lookup=usage_lookup, prior_form=prior_form,
                               early_calls=seeded_scope(spec, league_size,
                                                        data.week + 1),
                               processed_dir=processed_dir)
    if seeded:
        # §5's section-level disclosure: the seed moves every number in the
        # lineup (seating, projections, edges), not only the calls that carry
        # a row-level flag, so the section says so once.
        report["meta"]["seeded"] = True
    return report


def _prior_form(prior: Mapping[int, Mapping[str, Mapping[str, str]]],
                rule) -> dict[str, float]:
    """player -> last season's points per APPEARANCE, under this rule.

    Per appearance rather than per week on purpose: a player who missed half a
    season should not be ranked below a worse player who played every week, for
    the same reason engine/usage.py refuses to dilute a rate with weeks the
    player did not play.
    """
    from engine.scoring import score

    totals: dict[str, float] = {}
    games: dict[str, int] = {}
    for rows in prior.values():
        for player_id, row in rows.items():
            totals[player_id] = totals.get(player_id, 0.0) + score(row, rule)
            games[player_id] = games.get(player_id, 0) + 1
    return {pid: totals[pid] / games[pid] for pid in totals if games[pid]}


def _prior_form_line(player_id: str,
                     prior: Mapping[int, Mapping[str, Mapping[str, str]]],
                     rule) -> str | None:
    """The one-line basis a week-1 reader needs to check the ordering."""
    from engine.scoring import score

    points = [score(rows[player_id], rule)
              for rows in prior.values() if player_id in rows]
    if not points:
        return None
    per_game = sum(points) / len(points)
    return (f"last season: {per_game:.1f} a game over {len(points)} "
            f"game{'s' if len(points) != 1 else ''}")


# --------------------------------------------------------------------- #
# CLI — one roster, for checking a real signup by hand
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    from run.refs import RefError, decode_roster

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref", help="a v2 roster reference (the client_reference_id)")
    parser.add_argument("--week", type=int, help="default: the current NFL week")
    parser.add_argument("--season", help="default: the current NFL season")
    parser.add_argument("--league-size", type=int, default=12)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--out", type=Path, help="write the report JSON here")
    args = parser.parse_args(argv)

    try:
        ref = decode_roster(args.ref)
    except RefError as exc:
        print(f"that reference does not decode: {exc}", file=sys.stderr)
        return 1
    try:
        data = load_week_data(args.cache, args.season, args.week)
        report = report_for(spec_from_ref(ref), data,
                            league_size=args.league_size, cache_dir=args.cache)
    except SoloError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    meta = report["meta"]
    published = sum(1 for slot in report["lineup"]
                    if slot.get("confidence") is not None)
    line = "=" * 62
    print(f"{line}\nSOLO REPORT — {meta['season']} week {meta['week']}\n{line}")
    print(f"  scoring        : {meta['scoring']}")
    print(f"  roster         : {len(ref.player_ids)} players, "
          f"{len(ref.slots)} starting slots")
    print(f"  confidences    : {published}/{len(report['lineup'])} published")
    print(f"  availability   : {meta['availability_as_of'] or 'no injury report'}")
    for gap in meta.get("gaps") or []:
        print(f"  gap · {gap['field']}: {gap['reason']}")
    print(f"  {data.attribution}")
    if args.out:
        import json
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  written        : {args.out}")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
