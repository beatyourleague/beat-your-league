"""League ID resolution.

Precedence: explicit CLI argument > SLEEPER_LEAGUE_ID env var > CLAUDE.md.
CLAUDE.md is the spec and the single source of truth for *my* league; the env
var and CLI exist for testing other leagues without editing the spec.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ingest.sleeper import is_valid_league_id

PLACEHOLDER = "PASTE_LEAGUE_ID_HERE"

_CLAUDE_MD_RE = re.compile(r"\*\*My Sleeper league ID:\*\*\s*`([^`]+)`")


class LeagueIdError(SystemExit):
    """Exit with an actionable message instead of a traceback."""


def league_id_from_claude_md(claude_md_path: Path) -> str | None:
    """Extract the league ID from CLAUDE.md, or None if absent/placeholder."""
    try:
        text = claude_md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _CLAUDE_MD_RE.search(text)
    if not match:
        return None
    league_id = match.group(1).strip()
    if league_id == PLACEHOLDER:
        return None
    return league_id


def resolve_league_id(cli_value: str | None, repo_root: Path) -> str:
    """Return a validated league ID or exit with instructions."""
    league_id = (
        cli_value
        or os.environ.get("SLEEPER_LEAGUE_ID")
        or league_id_from_claude_md(repo_root / "CLAUDE.md")
    )
    if not league_id:
        raise LeagueIdError(
            "No league ID configured.\n"
            "Paste your Sleeper league ID into CLAUDE.md (the "
            "'**My Sleeper league ID:**' line — grab it from the URL at "
            "sleeper.com/leagues/<ID>/...),\n"
            "or run with --league <ID>, or set SLEEPER_LEAGUE_ID."
        )
    if not is_valid_league_id(league_id):
        raise LeagueIdError(
            f"League ID {league_id!r} doesn't look like a Sleeper league ID "
            "(expected a long numeric string, e.g. 289646328504385536)."
        )
    return league_id
