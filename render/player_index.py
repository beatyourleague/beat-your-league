"""The player directory the intake page downloads.

The subscriber types names and we turn them into ids, and the ONLY honest place
to settle an ambiguous name is in front of the person who knows the answer
(RULE R3). That requires the directory to be in the browser, which requires it
to be small — measured at 1,363 entries, ~50 KB raw and ~16 KB gzipped, so it
ships as a static asset on a GitHub Pages site with no server involved.

Two things ride along with the names.

**Attribution (RULE N1).** CC-BY-4.0 grants commercial use in exchange for
credit. The credit is IN THE ASSET, not only on the page that renders it, so a
redesign of the page cannot quietly drop the licence term.

**Confusable pairs.** Exact matching is safe — the eligible pool has zero
normalised-name collisions — but "safe" only covers names that are equal. It
says nothing about names one keystroke apart, and the intake's real failure is
a subscriber who types a real name that is not the one they meant. Measured on
the live pool, the pairs within edit distance 2 are mostly separable by
position and team on sight. **Bijan Robinson and Brian Robinson are the same
position on the same team**, which is the one case a confirm row cannot
disambiguate visually — so the page shows the twin inline and the subscriber
resolves it deliberately rather than by not noticing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.roster import PlayerDirectory, load_directory, normalize
from ingest.nflverse import ATTRIBUTION, NflverseError, fetch, season_teams

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "nflverse"
DEFAULT_OUT = REPO_ROOT / "site" / "join" / "players.json"

# Two edits covers the realistic typo (a dropped letter, a swapped pair, a
# wrong vowel) without dragging in every short name that resembles every other.
MAX_EDITS = 2


def _display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise. run/batch.py learned
    this the same way: a cosmetic path in a summary line must never be the
    thing that raises at the end of a good run."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _within(a: str, b: str, limit: int = MAX_EDITS) -> bool:
    """Damerau-Levenshtein, bounded. True when a is within ``limit`` edits of b.

    Bounded because the answer is only ever used as a yes/no: computing an exact
    distance of 9 for two unrelated names is work nobody reads.
    """
    if abs(len(a) - len(b)) > limit:
        return False
    if a == b:
        return True
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        best = current[0]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(previous[j] + 1,       # deletion
                             current[j - 1] + 1,    # insertion
                             previous[j - 1] + cost)
            if (i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb):
                current[j] = min(current[j], previous2[j - 2] + cost)
            best = min(best, current[j])
        if best > limit:
            return False                            # no path can recover
        previous2, previous = previous, current
    return previous[len(b)] <= limit


def confusable_pairs(directory: PlayerDirectory) -> list[list[str]]:
    """Every pair of eligible names within MAX_EDITS, as id pairs.

    Restricted to same-position pairs: a quarterback and a kicker one edit
    apart are not a mistake a manager makes while reading their own roster, and
    including them buries the pairs that matter.
    """
    entries = [(p.player_id, normalize(p.name), p.position)
               for p in directory.players]
    entries.sort(key=lambda e: (e[2], len(e[1])))
    pairs: list[list[str]] = []
    for index, (id_a, key_a, pos_a) in enumerate(entries):
        for id_b, key_b, pos_b in entries[index + 1:]:
            if pos_b != pos_a:
                break                               # sorted by position
            if len(key_b) - len(key_a) > MAX_EDITS:
                break                               # then by length
            if _within(key_a, key_b):
                pairs.append(sorted((id_a, id_b)))
    return sorted(pairs)


def build(directory: PlayerDirectory, season: str,
          generated_at: str | None = None) -> dict:
    """The whole payload, deterministic given the same inputs."""
    return {
        "season": str(season),
        "generated": generated_at or datetime.now(timezone.utc)
                     .replace(microsecond=0).isoformat(),
        # RULE N1: the licence term travels with the data it licenses.
        "attribution": ATTRIBUTION,
        "players": [list(row) for row in _sorted_players(directory)],
        "confusable": confusable_pairs(directory),
    }


def _sorted_players(directory: PlayerDirectory) -> list[list[str]]:
    return [[p.name, p.player_id, p.position, p.team or ""]
            for p in sorted(directory.players, key=lambda p: (p.name, p.player_id))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True,
                        help="the season whose teams are eligible")
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed asset is stale, without writing")
    args = parser.parse_args(argv)

    # Fetch what THIS asset needs, rather than leaning on a weekly-stats pull.
    # The directory depends only on who exists and who plays, and those are
    # published year-round — the weekly stats file for an unstarted season is a
    # 404, which used to make `make index` impossible before kickoff.
    try:
        players_csv = fetch("players", "players.csv", args.raw)
        teams_csv = fetch("teams", "teams_colors_logos.csv", args.raw)
        fetch("schedules", "games.csv", args.raw, live=True)
    except NflverseError as exc:
        print(f"could not fetch the player directory's inputs: {exc}",
              file=sys.stderr)
        return 1

    teams = season_teams(args.raw, args.season)
    if len(teams) != 32:
        # Better to refuse than to publish a directory missing a defense: a
        # subscriber who rosters that team simply cannot complete signup.
        print(f"the {args.season} schedule reports {len(teams)} teams, not 32 — "
              f"refusing to build a directory from it", file=sys.stderr)
        return 1

    # RULE R2's window, measured rather than chosen: against the live data,
    # season-1 gives 1,538 entries and ZERO normalised-name collisions, while
    # season-2 admits four. One year back is therefore the widest window that
    # keeps exact matching unambiguous, and it is wide enough for a player who
    # missed a season. test_player_index pins both halves of that boundary.
    directory = load_directory(players_csv, teams_csv,
                               min_last_season=int(args.season) - 1,
                               eligible_teams=teams)
    payload = build(directory, args.season)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)

    if args.check:
        if not args.output.is_file():
            print(f"{args.output} does not exist", file=sys.stderr)
            return 1
        current = json.loads(args.output.read_text(encoding="utf-8"))
        # The timestamp always differs; everything else must not.
        fresh = {k: v for k, v in payload.items() if k != "generated"}
        current = {k: v for k, v in current.items() if k != "generated"}
        if current != fresh:
            print(f"{args.output} is stale — run `make index`", file=sys.stderr)
            return 1
        print(f"{args.output.name} is up to date "
              f"({len(payload['players'])} entries)")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body, encoding="utf-8")
    import gzip
    size = len(gzip.compress(body.encode("utf-8")))
    print("=" * 62)
    print(f"player directory -> {_display(args.output)}")
    print(f"  season          : {args.season} ({len(teams)} teams)")
    print(f"  entries         : {len(payload['players'])}")
    print(f"  confusable pairs: {len(payload['confusable'])}")
    print(f"  size            : {len(body) / 1024:.0f} KB raw, "
          f"{size / 1024:.0f} KB gzipped")
    print(f"  {ATTRIBUTION}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
