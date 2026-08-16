"""Phase 1 ingestion: pull a league's current + previous season into data/raw/.

Usage:
    python -m ingest.pull [--league <ID>] [--skip-players]

Pulls, for the configured league and the season before it (via
``previous_league_id``): league settings, users, rosters, every week's
matchups and transactions, plus the NFL players table. Everything lands as
raw JSON under ``data/raw/`` and the run ends with a verification summary.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ingest.availability import write_snapshot
from ingest.config import resolve_league_id
from ingest.sleeper import SleeperClient, SleeperError, SleeperNotFound, is_valid_league_id

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"

# NFL fantasy seasons run through week 17 (up to 2020) or 18 (2021+),
# and Sleeper playoff matchups live in the same weekly endpoint.
def last_week_of_season(season: str) -> int:
    try:
        return 18 if int(season) >= 2021 else 17
    except ValueError:
        return 18


@dataclass
class SeasonPull:
    """Everything retrieved for one league-season, for the summary."""

    league: dict[str, Any]
    users: list[dict[str, Any]]
    rosters: list[dict[str, Any]]
    weeks_with_matchups: list[int] = field(default_factory=list)
    weeks_with_transactions: list[int] = field(default_factory=list)
    transaction_count: int = 0

    @property
    def season(self) -> str:
        return str(self.league.get("season", "?"))

    @property
    def name(self) -> str:
        return str(self.league.get("name", "?"))


def scoring_label(scoring_settings: dict[str, Any]) -> str:
    """Human name for the league's reception scoring. Units defined: this is
    points per reception, the axis that most changes start/sit math."""
    rec = scoring_settings.get("rec", 0) or 0
    if rec == 1:
        return "Full PPR (1.0/reception)"
    if rec == 0.5:
        return "Half PPR (0.5/reception)"
    if rec == 0:
        return "Standard (0/reception)"
    return f"Custom ({rec}/reception)"


def team_table(users: list[dict[str, Any]], rosters: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    """(roster_id, team name, owner display name), sorted by roster_id.

    Team name falls back to the owner's display name (Sleeper leaves
    ``metadata.team_name`` unset until the owner customizes it).
    """
    users_by_id = {u.get("user_id"): u for u in users}
    rows: list[tuple[int, str, str]] = []
    for roster in rosters:
        owner = users_by_id.get(roster.get("owner_id")) or {}
        display_name = owner.get("display_name") or "(no owner)"
        metadata = owner.get("metadata") or {}
        team_name = metadata.get("team_name") or display_name
        rows.append((int(roster.get("roster_id", 0)), team_name, display_name))
    return sorted(rows)


def pull_history(client: SleeperClient, current: dict[str, Any]) -> SeasonPull | None:
    """Pull the most recent completed season via previous_league_id, if any.

    The field comes from an API response body, so it's untrusted: anything that
    doesn't look like a Sleeper ID (or 404s) is skipped with a note, never a crash.
    """
    raw_previous_id = current.get("previous_league_id")
    if not raw_previous_id:
        print("No previous_league_id on this league — first season, no history to pull.")
        return None
    previous_id = str(raw_previous_id)
    if not is_valid_league_id(previous_id):
        print(f"  previous_league_id {raw_previous_id!r} is not a valid Sleeper ID; skipping history")
        return None
    print(f"Pulling previous season (league {previous_id})...")
    try:
        previous = client.league(previous_id, max_age_hours=None)
        if previous.get("status") != "complete":
            # The cached snapshot may predate season completion (e.g. weekly
            # runs stopped before Sleeper flipped the status). Revalidate so
            # the never-expire policy is driven by real status, not cache age.
            previous = client.league(previous_id, max_age_hours=6.0)
        return pull_season(client, previous)
    except SleeperNotFound:
        print(f"  previous league {previous_id} not found on Sleeper; skipping")
        return None


def pull_season(client: SleeperClient, league: dict[str, Any]) -> SeasonPull:
    """Pull users, rosters, and every week's matchups + transactions."""
    league_id = league["league_id"]
    completed = league.get("status") == "complete"
    # History never changes; live-season data refreshes after 6h (client default).
    max_age: float | None = None if completed else 6.0

    result = SeasonPull(
        league=league,
        users=client.users(league_id, max_age_hours=max_age),
        rosters=client.rosters(league_id, max_age_hours=max_age),
    )
    for week in range(1, last_week_of_season(result.season) + 1):
        matchups = client.matchups(league_id, week, max_age_hours=max_age)
        transactions = client.transactions(league_id, week, max_age_hours=max_age)
        if matchups:
            result.weeks_with_matchups.append(week)
        if transactions:
            result.weeks_with_transactions.append(week)
            result.transaction_count += len(transactions)
        # Counted usage for the same week. A completed season's stats are final,
        # so they cache forever; the live season revalidates on the normal
        # window. Failures here are not fatal — usage enriches the report, it
        # is never load-bearing, and a report without it is still correct.
        if matchups:
            try:
                client.stats(result.season, week,
                             max_age_hours=None if completed else max_age)
            except Exception:  # noqa: BLE001 — usage is optional enrichment
                pass
    return result


def _fmt_weeks(weeks: list[int]) -> str:
    if not weeks:
        return "none"
    return f"{len(weeks)} (weeks {min(weeks)}-{max(weeks)})"


def print_summary(
    state: dict[str, Any],
    seasons: list[SeasonPull],
    player_count: int | None,
    players_bytes: int | None,
    client: SleeperClient,
) -> None:
    line = "=" * 62
    print(f"\n{line}\nPHASE 1 VERIFICATION SUMMARY\n{line}")
    print(f"NFL state: season {state.get('season')} ({state.get('season_type')}), "
          f"week {state.get('week')}; previous season {state.get('previous_season')}")

    for pull in seasons:
        league = pull.league
        print(f"\n--- {pull.name} · season {pull.season} "
              f"[{league.get('status', '?')}] (league_id {league.get('league_id')})")
        print(f"    Scoring: {scoring_label(league.get('scoring_settings') or {})} · "
              f"{(league.get('settings') or {}).get('num_teams', '?')} teams")
        positions = [p for p in (league.get('roster_positions') or []) if p != 'BN']
        if positions:
            print(f"    Starting slots: {', '.join(positions)}")
        print(f"    Teams (roster · team name · owner):")
        for roster_id, team_name, owner in team_table(pull.users, pull.rosters):
            print(f"      {roster_id:>2} · {team_name} · {owner}")
        print(f"    Matchup weeks: {_fmt_weeks(pull.weeks_with_matchups)}")
        print(f"    Transaction weeks: {_fmt_weeks(pull.weeks_with_transactions)} · "
              f"{pull.transaction_count} transactions")

    print(f"\nPlayers table: ", end="")
    if player_count is None:
        print("skipped (--skip-players)")
    else:
        size_mb = (players_bytes or 0) / 1_048_576
        print(f"{player_count} players cached ({size_mb:.1f} MB)")

    print(f"Cache: {client.files_written} files written this run, "
          f"{client.cache_hits} cache hits, {client.http_requests} HTTP requests")
    total_files = sum(1 for p in RAW_DIR.rglob("*.json") if p.name != "_manifest.json")
    print(f"Raw store: {total_files} JSON files under data/raw/")
    print("LLM tokens this run: 0 (deterministic layer only — no language calls in ingestion)")
    print(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", help="Sleeper league ID (overrides CLAUDE.md)")
    parser.add_argument("--skip-players", action="store_true",
                        help="skip the large players table (faster smoke runs)")
    args = parser.parse_args(argv)

    league_id = resolve_league_id(args.league, REPO_ROOT)
    client = SleeperClient(cache_dir=RAW_DIR)

    try:
        state = client.state()
        print(f"Pulling league {league_id} (current season)...")
        try:
            current = client.league(league_id)
        except SleeperNotFound:
            print(f"League {league_id} not found on Sleeper — check the ID in your "
                  "league's URL (sleeper.com/leagues/<ID>/...).", file=sys.stderr)
            return 1
        seasons = [pull_season(client, current)]

        history = pull_history(client, current)
        if history:
            seasons.append(history)

        player_count = players_bytes = None
        snapshot_players = None
        if not args.skip_players:
            print("Fetching players table (cached daily; large file)...")
            players = client.players()
            player_count = len(players)
            players_file = RAW_DIR / "players" / "nfl.json"
            players_bytes = players_file.stat().st_size if players_file.is_file() else 0
            # Availability snapshot: zero extra HTTP, but it can only ever be
            # captured live — /players/nfl has no history (Phase 2 finding).
            snapshot_file, snapshot_players = write_snapshot(RAW_DIR, players, state)
            print(f"Availability snapshot: {snapshot_players} players -> "
                  f"{snapshot_file.relative_to(REPO_ROOT)}")

        # NFL schedule for each pulled season: source of bye weeks. Completed
        # seasons never change; the live season refreshes daily.
        for pull in seasons:
            completed = pull.league.get("status") == "complete"
            games = client.schedule(pull.season,
                                    max_age_hours=None if completed else 24.0)
            print(f"Schedule {pull.season}: {len(games)} games cached")
    except SleeperError as exc:
        print(f"Sleeper API failure: {exc}\n"
              "Everything fetched so far is cached under data/raw/ — "
              "re-run to resume from there.", file=sys.stderr)
        return 1

    print_summary(state, seasons, player_count, players_bytes, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
