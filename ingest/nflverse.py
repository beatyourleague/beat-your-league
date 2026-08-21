"""NFL data under a licence that permits what this business does.

WHY THIS EXISTS. Sleeper's Terms of Use (§11.1, §11.3 — quoted verbatim in
PLAN §0) prohibit a third party retrieving data from their service without a
separate written agreement, "whether directly, through automated means, or
through any account, credential, or authentication mechanism belonging to a
user" — and §11.2's first remedy is terminating the SUBSCRIBER's account. There
is no architecture that routes around that sentence: browser-side compute, a
local CLI, an extension and a user-forked cron were all researched and all fail
it. So the paid product moves onto data whose licence affirmatively permits
commercial use, and stops needing anyone's permission.

  https://github.com/nflverse/nflverse-data — CC-BY-4.0.

Three rules travel with this module.

RULE N1 — ATTRIBUTION IS A LICENCE TERM, NOT A COURTESY. CC-BY-4.0 grants
commercial use *in exchange for* credit and an indication of changes. Ship the
credit or the grant does not apply, which would put us right back where Sleeper
left us. ``ATTRIBUTION`` is imported by the renderers and pinned by a test, for
the same reason the no-betting line is: a footer nobody is looking at is exactly
what gets deleted in a redesign.

RULE N2 — FIRST-PARTY OUTPUTS ONLY. The CC-BY grant covers nflverse's own
compilation; some upstream feeds carry their own terms. Snap counts are
Pro-Football-Reference-derived and FTN charting is CC-BY-SA (a share-alike term
we cannot accept in a closed product), so neither is read here. This costs us
snap counts, which is cheap: RULE U2 already made snaps live-only and therefore
unbacktestable, so they were never load-bearing.

RULE N3 — GSIS IDS, THE SAME JOIN KEY THE INJURY ARCHIVE USES.
``stats_player``'s ``player_id`` column is the GSIS id (``00-0023459``), which
is what ``ingest/injuries.py`` already keys on. One id space across every
public-data feed, and no mapping table to drift.

Note ``stats_player`` is the current release. ``player_stats`` still exists and
is deprecated upstream; reading it would silently give stale schemas.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path

import requests

RELEASE = ("https://github.com/nflverse/nflverse-data/releases/download/"
           "{release}/{asset}")

# RULE N1. Rendered on every report and every public page.
ATTRIBUTION = ("NFL data: nflverse (nflverse-data), CC-BY-4.0. "
               "Aggregated and scored to your league's settings by us.")

# A completed season never changes, so it is cached forever. The live season is
# revalidated on the same 6h window the rest of the ingest layer uses — nflverse
# rebuilds during and after games.
LIVE_MAX_AGE_SECONDS = 6 * 60 * 60


class NflverseError(RuntimeError):
    """A fetch failed in a way the caller has to decide about."""


@dataclass(frozen=True)
class Usage:
    """One player's counted production in one week.

    Every field is a COUNT of something that already happened, so nothing here
    carries a calibration burden (RULE U1, engine/usage.py). An absent value is
    None and renders absent — never as 0.0, which would read as "he played and
    got nothing" when the truth is "we have no line for him".
    """

    gsis_id: str
    name: str
    position: str | None
    team: str | None
    season: str
    week: int
    targets: int | None
    receptions: int | None
    receiving_yards: float | None
    air_yards: float | None
    target_share: float | None
    carries: int | None
    rushing_yards: float | None
    passing_yards: float | None
    fantasy_points_ppr: float | None


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def fetch(release: str, asset: str, cache_dir: Path, *, live: bool = False,
          session: requests.Session | None = None) -> Path:
    """Download one release asset, or reuse the cached copy.

    ``live=True`` revalidates on the 6h window; anything else is treated as
    final and cached forever, the same policy the Sleeper ingest applied to
    completed seasons. A zero-byte cache file is always refetched — an empty
    CSV that got frozen would silently mean "nobody played this week".
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / asset
    if path.is_file() and path.stat().st_size > 0:
        if not live or (time.time() - path.stat().st_mtime) < LIVE_MAX_AGE_SECONDS:
            return path
    client = session or requests
    url = RELEASE.format(release=release, asset=asset)
    try:
        response = client.get(url, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        # A cached copy beats an outage: stale counted data is still a real
        # record of games that were actually played, and the report flags its
        # age (principle 3). Only a cold cache is fatal.
        if path.is_file() and path.stat().st_size > 0:
            return path
        raise NflverseError(f"could not fetch {url}: {exc}") from exc
    if not response.content:
        raise NflverseError(f"{url} returned an empty body")
    path.write_bytes(response.content)
    return path


def usage_week(cache_dir: Path, season: str, week: int, *, live: bool = False,
               session: requests.Session | None = None) -> dict[str, Usage]:
    """Counted production for one week, keyed by GSIS id.

    Regular season only: ``season_type`` also carries POST and PRE rows, and a
    week number means a different thing in each. Mixing them would put a
    playoff game and a week-1 game in the same bucket.
    """
    path = fetch("stats_player", f"stats_player_week_{season}.csv", cache_dir,
                 live=live, session=session)
    out: dict[str, Usage] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("season_type") or "REG").upper() != "REG":
                continue
            if _int(row.get("week")) != week:
                continue
            gsis = (row.get("player_id") or "").strip()
            if not gsis:
                continue
            out[gsis] = Usage(
                gsis_id=gsis,
                name=(row.get("player_display_name") or "").strip(),
                position=(row.get("position") or "").strip() or None,
                team=(row.get("team") or "").strip() or None,
                season=str(season),
                week=week,
                targets=_int(row.get("targets")),
                receptions=_int(row.get("receptions")),
                receiving_yards=_float(row.get("receiving_yards")),
                air_yards=_float(row.get("receiving_air_yards")),
                target_share=_float(row.get("target_share")),
                carries=_int(row.get("carries")),
                rushing_yards=_float(row.get("rushing_yards")),
                passing_yards=_float(row.get("passing_yards")),
                fantasy_points_ppr=_float(row.get("fantasy_points_ppr")),
            )
    return out


# The fields engine.scoring reads, plus the identity columns. Loading only
# these turns a 150-column row into a 25-column one, which matters when the
# backtest holds a whole season in memory at once.
SCORING_COLUMNS = frozenset({
    "player_id", "player_display_name", "position", "team", "season", "week",
    "season_type", "receptions", "passing_yards", "passing_tds",
    "passing_interceptions", "passing_2pt_conversions", "rushing_yards",
    "rushing_tds", "rushing_2pt_conversions", "receiving_yards",
    "receiving_tds", "receiving_2pt_conversions", "special_teams_tds",
    "sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost",
    "fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49",
    "fg_made_50_59", "fg_made_60_", "fg_missed", "pat_made",
})


def season_rows(cache_dir: Path, season: str, *, live: bool = False,
                columns: frozenset[str] | None = SCORING_COLUMNS,
                session: requests.Session | None = None,
                ) -> dict[int, dict[str, dict[str, str]]]:
    """A whole regular season, keyed week -> gsis id -> stat row.

    This is the shape ``engine.subscriber.build_season`` consumes. Regular
    season only, for the same reason ``usage_week`` filters: a POST row at week
    10 is a different game, and mixing them would put a playoff performance in a
    week-10 bucket.

    ``columns`` trims each row to the fields scoring actually reads. Pass None
    to keep everything — useful for exploration, wasteful for a backtest that
    holds twenty-six seasons.
    """
    path = fetch("stats_player", f"stats_player_week_{season}.csv", cache_dir,
                 live=live, session=session)
    weeks: dict[int, dict[str, dict[str, str]]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("season_type") or "REG").upper() != "REG":
                continue
            week = _int(row.get("week"))
            gsis = (row.get("player_id") or "").strip()
            if not week or not gsis:
                continue
            kept = ({k: v for k, v in row.items() if k in columns}
                    if columns is not None else dict(row))
            weeks.setdefault(week, {})[gsis] = kept
    return weeks


def bye_teams(cache_dir: Path, season: str, week: int, *, live: bool = False,
              session: requests.Session | None = None) -> frozenset[str] | None:
    """Teams NOT playing in this week — the availability half we can still see.

    Returns None when the week is not in the schedule at all, which classifies
    as UNKNOWN upstream rather than "everybody is playing". The gate has always
    required knowing a player is not on bye; guessing here would be a
    principle-1 bypass wearing a different data source.
    """
    path = fetch("schedules", "games.csv", cache_dir, live=live, session=session)
    playing: set[str] = set()
    all_teams: set[str] = set()
    seen_week = False
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season") or "") != str(season):
                continue
            if (row.get("game_type") or "REG").upper() != "REG":
                continue
            home = (row.get("home_team") or "").strip()
            away = (row.get("away_team") or "").strip()
            all_teams.update(t for t in (home, away) if t)
            if _int(row.get("week")) == week:
                seen_week = True
                playing.update(t for t in (home, away) if t)
    if not seen_week or not all_teams:
        return None
    return frozenset(all_teams - playing)


def season_teams(cache_dir: Path, season: str, *, live: bool = False,
                 session: requests.Session | None = None) -> frozenset[str]:
    """The team abbreviations that actually play this season.

    The teams release carries relocated franchises forever — LAR *and* STL,
    LAC *and* SD, LV *and* OAK, 36 rows for 32 teams. Anything keyed off that
    file without this filter offers a subscriber teams that have not existed
    for a decade. The schedule is the authority on who exists, and it is also
    the spelling the stats feed uses (the Rams are ``LA``).
    """
    path = fetch("schedules", "games.csv", cache_dir, live=live, session=session)
    teams: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("season") or "") != str(season):
                continue
            if (row.get("game_type") or "REG").upper() != "REG":
                continue
            for side in ("home_team", "away_team"):
                value = (row.get(side) or "").strip()
                if value:
                    teams.add(value)
    return frozenset(teams)


def main(argv: list[str] | None = None) -> int:
    """Verification summary — the same shape ingest.pull prints."""
    import argparse
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2024")
    parser.add_argument("--week", type=int, default=10)
    parser.add_argument("--cache", type=Path,
                        default=repo_root / "data" / "raw" / "nflverse")
    args = parser.parse_args(argv)

    try:
        usage = usage_week(args.cache, args.season, args.week)
        byes = bye_teams(args.cache, args.season, args.week)
    except NflverseError as exc:
        print(f"nflverse ingest failed: {exc}", file=sys.stderr)
        return 1

    with_targets = sum(1 for u in usage.values() if u.targets)
    with_air = sum(1 for u in usage.values() if u.air_yards is not None)
    print("=" * 62)
    print(f"nflverse — {args.season} week {args.week} (regular season)")
    print(f"  players with a stat line : {len(usage)}")
    print(f"  with targets             : {with_targets}")
    print(f"  with air yards           : {with_air}")
    print(f"  teams on bye             : "
          + (", ".join(sorted(byes)) if byes else "unknown"))
    print(f"  cache                    : {args.cache}")
    print(f"  {ATTRIBUTION}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
