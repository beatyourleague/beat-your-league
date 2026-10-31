"""Is the weekly run due in this slot? Run with ``python -I -S``.

Reports go out Wednesday evening: waivers have cleared, so a manager has had the
day to update the roster, and a day is left before Thursday's game. The one
exception is a week with a game ON Wednesday (Thanksgiving eve, an opener, a
Christmas Wednesday), whose report goes that morning instead. So weekly.yml
fires a morning slot every Wednesday and this says whether it is a real one:
the evening slots always run, and the morning slot runs only when a regular
season game is on today's schedule.

Standard library only, in a job with no secrets and nothing installed. A
schedule it cannot read leaves the morning slot off: the evening run still
comes, and the watchdog says so if that was too late.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

GAMES = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
NFL_TIME = "America/New_York"


def game_today(rows, today: str) -> bool:
    return any(row.get("game_type") == "REG" and row.get("gameday") == today for row in rows)


def due(morning: bool, read_games, today: str) -> bool:
    """Pure. ``read_games`` is called only for the morning slot."""
    if not morning:
        return True
    try:
        return game_today(read_games(), today)
    except Exception as exc:  # noqa: BLE001 — never fail the job: the evening run still comes
        print(f"Could not read the schedule ({exc!r}), so the morning slot stays off.")
        return False


def read_games() -> list[dict]:
    with urllib.request.urlopen(GAMES, timeout=30) as response:
        return list(csv.DictReader(io.StringIO(response.read().decode("utf-8"))))


def main() -> int:
    today = datetime.now(ZoneInfo(NFL_TIME)).date().isoformat()
    run = due(os.environ.get("MORNING_SLOT") == "true", read_games, today)
    print(f"Weekly run {'is' if run else 'is not'} due in this slot ({today}).")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
