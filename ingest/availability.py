"""Weekly availability snapshots — the feed the Phase 2 backtest demanded.

Sleeper's ``/players/nfl`` carries exactly one *current* ``injury_status`` per
player, with no history. So the only way to ever know "what was his status in
week 6" is to have written it down during week 6. This module extracts the
availability-relevant slice of the (already fetched) players table into a
small dated snapshot under ``data/raw/availability/``, every time ingestion
runs. Costs zero extra HTTP requests.

Snapshots accumulate: one file per (season, season_type, week), overwritten
within the week so it always holds the freshest status, with ``as_of`` embedded
so a report can say "injury data as of Tue 9am" (CLAUDE.md principle 3).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Players table fields that matter for availability. ``active`` is Sleeper's
# "on an NFL roster at all" flag; ``injury_status`` is the game designation.
_KEEP_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})

_VALID_SEASON_TYPES = ("regular", "pre", "post", "off")


def snapshot_path(raw_dir: Path, season: str, season_type: str, week: int) -> Path:
    return (Path(raw_dir) / "availability" / str(season)
            / f"{season_type}_week_{week:02d}.json")


def build_snapshot(players: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Extract the availability slice for fantasy-relevant players."""
    # season/season_type flow into a filesystem path; API data is untrusted
    # (CLAUDE.md security), so validate before any path is built.
    season = str(state.get("season", ""))
    season_type = str(state.get("season_type", ""))
    if not re.fullmatch(r"\d{4}", season):
        raise ValueError(f"invalid season from /state/nfl: {season!r}")
    if season_type not in _VALID_SEASON_TYPES:
        raise ValueError(f"invalid season_type from /state/nfl: {season_type!r}")
    statuses: dict[str, dict[str, Any]] = {}
    for player_id, record in players.items():
        if not isinstance(record, dict):
            continue
        positions = set(record.get("fantasy_positions") or [])
        if record.get("position"):
            positions.add(record["position"])
        if not positions & _KEEP_POSITIONS:
            continue
        statuses[str(player_id)] = {
            "injury_status": record.get("injury_status"),
            "active": bool(record.get("active")),
            "team": record.get("team"),
            "position": record.get("position"),
        }
    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season,
        "season_type": season_type,
        "week": int(state.get("week") or 0),
        "source": "/v1/players/nfl (current snapshot, written at pull time)",
        "statuses": statuses,
    }


def write_snapshot(raw_dir: Path, players: dict[str, Any],
                   state: dict[str, Any]) -> tuple[Path, int]:
    """Write the availability snapshot for the current NFL week.

    Returns the path written and the number of players captured.
    """
    snapshot = build_snapshot(players, state)
    path = snapshot_path(raw_dir, snapshot["season"], snapshot["season_type"],
                         snapshot["week"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp_path, path)
    return path, len(snapshot["statuses"])
