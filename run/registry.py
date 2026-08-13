"""Subscriber registry: who gets a report, for which league, against which rival.

The registry is a JSON array at ``data/registry/subscribers.json`` (gitignored —
it contains emails; CLAUDE.md security says collect the minimum and keep it out
of the repo). Each entry:

    {
      "email": "fan@example.com",           # delivery address (Substack list)
      "sleeper_username": "TheirName",      # informational, for humans
      "user_id": "457511950237696",         # their Sleeper user id
      "league_id": "289646328504385536",
      "rival_owner_id": "189140835533586432",  # preferred: stable across seasons
      "rival_roster_id": 6,                 # fallback for orphaned rival teams
      "added_at": "2026-08-13"
    }

``rival_owner_id`` or ``rival_roster_id`` must be present (both is best).
Entries come from the signup picker (site/join/) — already validated there,
but everything is re-validated here because files are editable by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ingest.sleeper import is_valid_league_id

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_ROOT / "data" / "registry" / "subscribers.json"

# Deliberately loose: enough to catch registry typos, not an RFC gate.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegistryError(ValueError):
    """A registry entry that cannot drive a report run."""


@dataclass(frozen=True)
class Subscriber:
    email: str
    user_id: str
    league_id: str
    rival_owner_id: str | None
    rival_roster_id: int | None
    sleeper_username: str | None = None

    @property
    def slug(self) -> str:
        """Filename-safe identity that carries no email (PII stays out of
        report filenames and out of git)."""
        base = self.sleeper_username or self.user_id
        return re.sub(r"[^A-Za-z0-9_-]", "_", base)[:40] or self.user_id


def _parse_entry(raw: dict, index: int) -> Subscriber:
    where = f"registry entry {index}"
    email = str(raw.get("email", "")).strip()
    if not _EMAIL_RE.match(email):
        raise RegistryError(f"{where}: invalid email {email!r}")
    user_id = str(raw.get("user_id", "")).strip()
    if not user_id.isdigit():
        raise RegistryError(f"{where}: user_id must be a numeric Sleeper id, "
                            f"got {raw.get('user_id')!r}")
    league_id = str(raw.get("league_id", "")).strip()
    if not is_valid_league_id(league_id):
        raise RegistryError(f"{where}: invalid league_id {raw.get('league_id')!r}")
    rival_owner = raw.get("rival_owner_id")
    rival_owner_id = str(rival_owner).strip() if rival_owner else None
    if rival_owner_id is not None and not rival_owner_id.isdigit():
        raise RegistryError(f"{where}: rival_owner_id must be numeric, got {rival_owner!r}")
    rival_roster = raw.get("rival_roster_id")
    # JSON true/false satisfies isinstance(..., int) in Python — a `true` here
    # must not silently become roster 1. Accept real ints and digit strings.
    if isinstance(rival_roster, bool):
        raise RegistryError(f"{where}: rival_roster_id must be a number, got {rival_roster!r}")
    if isinstance(rival_roster, int):
        rival_roster_id: int | None = rival_roster
    elif isinstance(rival_roster, str) and rival_roster.strip().isdigit():
        rival_roster_id = int(rival_roster.strip())
    elif rival_roster in (None, ""):
        rival_roster_id = None
    else:
        raise RegistryError(f"{where}: rival_roster_id must be a number, got {rival_roster!r}")
    if rival_roster_id is not None and rival_roster_id < 1:
        raise RegistryError(f"{where}: rival_roster_id must be positive, got {rival_roster_id}")
    if rival_owner_id is None and rival_roster_id is None:
        raise RegistryError(f"{where}: needs rival_owner_id or rival_roster_id")
    username = raw.get("sleeper_username")
    return Subscriber(
        email=email,
        user_id=user_id,
        league_id=league_id,
        rival_owner_id=rival_owner_id,
        rival_roster_id=rival_roster_id,
        sleeper_username=str(username).strip() if username else None,
    )


def load_registry(path: Path = DEFAULT_REGISTRY) -> list[Subscriber]:
    """Load and validate every entry. A malformed entry fails the load loudly —
    silently skipping a paying subscriber is the one unacceptable failure."""
    if not path.is_file():
        raise RegistryError(
            f"no registry at {path} — create it from run/subscribers.example.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise RegistryError(f"registry {path} must be a JSON array")
    subscribers = [_parse_entry(entry, i) for i, entry in enumerate(raw)]
    emails = [s.email.lower() for s in subscribers]
    duplicates = {e for e in emails if emails.count(e) > 1}
    if duplicates:
        raise RegistryError(f"duplicate emails in registry: {sorted(duplicates)}")
    return subscribers
