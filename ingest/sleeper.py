"""Sleeper API client with a polite, disk-first cache.

Every response is cached as raw JSON under ``data/raw/`` so re-runs cost
approximately zero API calls (CLAUDE.md cost requirement). A manifest file
records the fetch time of every cached file so later phases can flag data age
instead of fabricating freshness (CLAUDE.md principle 3).

Cache policy:
- Completed-season data (``max_age_hours=None``) never expires — history
  doesn't change — and its *empty* responses are cached too: an empty playoff
  week stays empty forever, so refetching it every run is pure waste.
- Live data expires on a per-call ``max_age_hours``, and its empty responses
  are never cached: a pre-season week with no matchups yet must stay fresh.
- Responses are shape-validated BEFORE they are written: a 200 with the wrong
  JSON shape must not poison a never-expiring cache entry, and a wrong-shape
  entry already on disk is treated like a corrupt one and refetched.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

BASE_URL = "https://api.sleeper.app/v1"
SCHEDULE_BASE = "https://api.sleeper.app"
USER_AGENT = "beat-your-league/0.1 (solo fantasy tool; disk-cached; throttled)"

# Sleeper IDs are numeric strings (snowflake-style). Validate before letting an
# ID anywhere near a URL: external input is untrusted (CLAUDE.md security).
_LEAGUE_ID_RE = re.compile(r"^\d{6,20}$")
# Sleeper usernames: word characters only. Anything fancier is rejected before
# it can reach a URL or a cache path.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")

_MANIFEST_NAME = "_manifest.json"


def is_valid_league_id(league_id: str) -> bool:
    """True if the string looks like a real Sleeper league/user ID."""
    return isinstance(league_id, str) and bool(_LEAGUE_ID_RE.match(league_id))


class SleeperError(RuntimeError):
    """Raised when the Sleeper API returns an unusable response."""


class SleeperNotFound(SleeperError):
    """Raised when Sleeper says the resource does not exist (HTTP 404)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SleeperClient:
    """Read-only Sleeper client. All fetches go through the disk cache."""

    def __init__(
        self,
        cache_dir: Path,
        session: requests.Session | None = None,
        throttle_seconds: float = 0.5,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.session = session or self._default_session()
        self.throttle_seconds = throttle_seconds
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._last_request_at = 0.0
        # Counters surfaced in the verification summary.
        self.http_requests = 0
        self.cache_hits = 0
        self.files_written = 0

    @staticmethod
    def _default_session() -> requests.Session:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        return session

    # ------------------------------------------------------------------ #
    # endpoints
    # ------------------------------------------------------------------ #

    def state(self, sport: str = "nfl") -> dict[str, Any]:
        """Current NFL state (season, week). Short cache: it changes weekly."""
        data = self._get(f"/state/{sport}", Path("state") / f"{sport}.json",
                         max_age_hours=1.0, expect=dict)
        if not isinstance(data, dict):
            raise SleeperError(f"/state/{sport} returned {type(data).__name__}, expected object")
        return data

    def league(self, league_id: str, max_age_hours: float | None = 6.0) -> dict[str, Any]:
        data = self._get_league(league_id, "league.json", "", max_age_hours, expect=dict)
        if not isinstance(data, dict):
            raise SleeperError(f"league {league_id} returned {type(data).__name__}, expected object")
        return data

    def users(self, league_id: str, max_age_hours: float | None = 6.0) -> list[dict[str, Any]]:
        return self._expect_list(
            self._get_league(league_id, "users.json", "/users", max_age_hours, expect=list),
            "users")

    def rosters(self, league_id: str, max_age_hours: float | None = 6.0) -> list[dict[str, Any]]:
        return self._expect_list(
            self._get_league(league_id, "rosters.json", "/rosters", max_age_hours, expect=list),
            "rosters")

    def matchups(self, league_id: str, week: int,
                 max_age_hours: float | None = 6.0) -> list[dict[str, Any]]:
        return self._expect_list(
            self._get_league(league_id, f"matchups/week_{week:02d}.json",
                             f"/matchups/{week}", max_age_hours, expect=list),
            f"matchups week {week}")

    def transactions(self, league_id: str, week: int,
                     max_age_hours: float | None = 6.0) -> list[dict[str, Any]]:
        return self._expect_list(
            self._get_league(league_id, f"transactions/week_{week:02d}.json",
                             f"/transactions/{week}", max_age_hours, expect=list),
            f"transactions week {week}")

    def players(self, sport: str = "nfl", max_age_hours: float | None = 24.0) -> dict[str, Any]:
        """Full players table (~large). Daily cache per Sleeper's own guidance."""
        data = self._get(f"/players/{sport}", Path("players") / f"{sport}.json",
                         max_age_hours=max_age_hours, timeout_seconds=180.0, expect=dict)
        if not isinstance(data, dict):
            raise SleeperError(f"/players/{sport} returned {type(data).__name__}, expected object")
        return data

    def user(self, username_or_id: str,
             max_age_hours: float | None = 6.0) -> dict[str, Any]:
        """Resolve a Sleeper username (or numeric user id) to the user record.

        Onboarding entry point: the subscriber types a username, everything
        else is derived. 404 -> SleeperNotFound ("no such user").
        """
        key = str(username_or_id).strip()
        if not (_LEAGUE_ID_RE.match(key) or _USERNAME_RE.match(key)):
            raise ValueError(f"invalid Sleeper username or user id: {username_or_id!r}")
        data = self._get(f"/user/{key}", Path("user") / f"{key.lower()}.json",
                         max_age_hours=max_age_hours, expect=dict)
        if not isinstance(data, dict):
            raise SleeperError(f"user {key} returned {type(data).__name__}, expected object")
        return data

    def user_leagues(self, user_id: str, season: str, sport: str = "nfl",
                     max_age_hours: float | None = 6.0) -> list[dict[str, Any]]:
        """Every league this user plays in for a season — the onboarding picker."""
        key = str(user_id).strip()
        if not _LEAGUE_ID_RE.match(key):
            raise ValueError(f"invalid Sleeper user id: {user_id!r}")
        if not re.match(r"^\d{4}$", str(season)):
            raise ValueError(f"invalid season: {season!r}")
        return self._expect_list(
            self._get(f"/user/{key}/leagues/{sport}/{season}",
                      Path("user") / key / f"leagues_{sport}_{season}.json",
                      max_age_hours=max_age_hours, expect=list),
            f"leagues for user {key}")

    def schedule(self, season: str, season_type: str = "regular",
                 max_age_hours: float | None = 24.0) -> list[dict[str, Any]]:
        """NFL game schedule for a season — the source for bye weeks.

        Lives at ``api.sleeper.app/schedule/...`` (same public host, outside
        /v1; verified live Aug 2026). Completed seasons should be fetched with
        ``max_age_hours=None`` — a finished schedule never changes.
        """
        if not re.match(r"^\d{4}$", str(season)):
            raise ValueError(f"invalid season: {season!r}")
        if season_type not in ("regular", "pre", "post"):
            raise ValueError(f"invalid season_type: {season_type!r}")
        data = self._get(
            f"{SCHEDULE_BASE}/schedule/{'nfl'}/{season_type}/{season}",
            Path("schedule") / f"nfl_{season_type}_{season}.json",
            max_age_hours=max_age_hours, expect=list)
        return self._expect_list(data, f"schedule {season_type} {season}")

    def projections(self, season: str, week: int, season_type: str = "regular",
                    max_age_hours: float | None = 24.0) -> dict[str, Any]:
        """Sleeper's own weekly player projections (Rotowire-sourced).

        ``/v1/projections/nfl/{type}/{season}/{week}`` — public, no auth,
        verified live Aug 2026 including HISTORICAL seasons back to at least
        2018, which is what makes the feed backtestable before it is ever
        adopted (principle 1). Returns ``{player_id: {stat: value, ...}}``
        with ``pts_ppr`` / ``pts_half_ppr`` / ``pts_std`` alongside the
        stat-level lines. Completed seasons should be fetched with
        ``max_age_hours=None`` — a finished week's projection archive is final.
        """
        if not re.match(r"^\d{4}$", str(season)):
            raise ValueError(f"invalid season: {season!r}")
        if season_type not in ("regular", "pre", "post"):
            raise ValueError(f"invalid season_type: {season_type!r}")
        if not isinstance(week, int) or not 1 <= week <= 22:
            raise ValueError(f"invalid week: {week!r}")
        data = self._get(
            f"/projections/nfl/{season_type}/{season}/{week}",
            Path("projections") / f"nfl_{season_type}_{season}_w{week:02d}.json",
            max_age_hours=max_age_hours, expect=dict)
        if not isinstance(data, dict):
            raise SleeperError(
                f"projections {season} w{week} returned "
                f"{type(data).__name__}, expected object")
        return data

    def stats(self, season: str, week: int, season_type: str = "regular",
              max_age_hours: float | None = 24.0) -> dict[str, Any]:
        """Actual weekly usage — what a player was GIVEN, not what he scored.

        ``/v1/stats/nfl/{type}/{season}/{week}`` — the same public, no-auth
        family as the projections feed and verified live against historical
        seasons. Carries the vocabulary the fantasy market actually argues in:
        ``rec_tgt`` (targets), ``off_snp`` (offensive snaps), ``rec_air_yd``
        (air yards) and ``rec_rz_tgt`` (red-zone targets), keyed by Sleeper
        player id — so it joins to everything else here with no id mapping.

        Usage is the half the report has been missing: a player's points tell
        you what happened, his snaps and targets tell you whether it is likely
        to happen again. Completed weeks should use ``max_age_hours=None``.
        """
        if not re.match(r"^\d{4}$", str(season)):
            raise ValueError(f"invalid season: {season!r}")
        if season_type not in ("regular", "pre", "post"):
            raise ValueError(f"invalid season_type: {season_type!r}")
        if not isinstance(week, int) or not 1 <= week <= 22:
            raise ValueError(f"invalid week: {week!r}")
        data = self._get(
            f"/stats/nfl/{season_type}/{season}/{week}",
            Path("stats") / f"nfl_{season_type}_{season}_w{week:02d}.json",
            max_age_hours=max_age_hours, expect=dict)
        if not isinstance(data, dict):
            raise SleeperError(
                f"stats {season} w{week} returned "
                f"{type(data).__name__}, expected object")
        return data

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _get_league(self, league_id: str, cache_name: str, suffix: str,
                    max_age_hours: float | None, expect: type) -> Any:
        if not is_valid_league_id(league_id):
            raise ValueError(f"invalid Sleeper league ID: {league_id!r}")
        return self._get(f"/league/{league_id}{suffix}",
                         Path("league") / league_id / cache_name,
                         max_age_hours=max_age_hours, expect=expect)

    @staticmethod
    def _expect_list(data: Any, what: str) -> list[dict[str, Any]]:
        if data is None:
            return []
        if not isinstance(data, list):
            raise SleeperError(f"{what} returned {type(data).__name__}, expected list")
        return data

    def _get(self, endpoint: str, rel_path: Path, max_age_hours: float | None,
             timeout_seconds: float | None = None, expect: type | None = None) -> Any:
        cache_path = self.cache_dir / rel_path
        url = endpoint if endpoint.startswith("http") else BASE_URL + endpoint
        cached = self._read_cache(cache_path, max_age_hours, expect)
        if cached is not None:
            self.cache_hits += 1
            # Heal a manifest that missed this file (e.g. Ctrl-C between the
            # cache write and the manifest write on some earlier run).
            self._ensure_manifest_entry(rel_path, url, cache_path)
            return cached["data"]

        data = self._request_json(url, timeout_seconds or self.timeout_seconds)
        # Validate BEFORE caching: a wrong-shape 200 must never poison the cache.
        if data is not None and expect is not None and not isinstance(data, expect):
            raise SleeperError(
                f"{endpoint} returned {type(data).__name__}, expected {expect.__name__}")
        # Immutable history caches everything (an empty completed week is final);
        # live data never caches emptiness (a week with no matchups *yet*).
        is_empty = data is None or data == [] or data == {}
        if data is not None and (not is_empty or max_age_hours is None):
            self._write_cache(cache_path, rel_path, url, data)
        return data

    def _read_cache(self, cache_path: Path, max_age_hours: float | None,
                    expect: type | None) -> dict[str, Any] | None:
        if not cache_path.is_file():
            return None
        if max_age_hours is not None:
            age_seconds = time.time() - cache_path.stat().st_mtime
            if age_seconds > max_age_hours * 3600:
                return None
        try:
            with cache_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None  # corrupt cache entry: refetch and overwrite
        if data is not None and expect is not None and not isinstance(data, expect):
            return None  # wrong-shape cache entry: treat as corrupt, refetch
        return {"data": data}

    def _write_cache(self, cache_path: Path, rel_path: Path, url: str, data: Any) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Unique tmp name so concurrent runs can't trample each other mid-write.
        tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        os.replace(tmp_path, cache_path)
        self.files_written += 1
        self._record_manifest(rel_path, url, cache_path.stat().st_size, _utc_now_iso())

    # ---- manifest: one locked read-modify-write per update ------------- #

    def _record_manifest(self, rel_path: Path, url: str, size_bytes: int,
                         fetched_at: str) -> None:
        def mutate(manifest: dict[str, Any]) -> bool:
            manifest[str(rel_path)] = {
                "url": url, "fetched_at": fetched_at, "bytes": size_bytes,
            }
            return True
        self._with_manifest(mutate)

    def _ensure_manifest_entry(self, rel_path: Path, url: str, cache_path: Path) -> None:
        def mutate(manifest: dict[str, Any]) -> bool:
            if str(rel_path) in manifest:
                return False
            stat = cache_path.stat()
            # The file's mtime IS its fetch time (os.replace preserves it), so
            # this backfill records truth, not a fabricated freshness.
            fetched_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(
                timespec="seconds")
            manifest[str(rel_path)] = {
                "url": url, "fetched_at": fetched_at, "bytes": stat.st_size,
            }
            return True
        self._with_manifest(mutate)

    def _with_manifest(self, mutate: Callable[[dict[str, Any]], bool]) -> None:
        """Run one locked read-modify-write against the manifest file."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.cache_dir / _MANIFEST_NAME
        lock_path = self.cache_dir / (_MANIFEST_NAME + ".lock")
        with lock_path.open("w", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                manifest: dict[str, Any] = {}
                if manifest_path.is_file():
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        manifest = {}
                if mutate(manifest):
                    tmp_path = manifest_path.with_name(
                        f"{_MANIFEST_NAME}.{os.getpid()}.tmp")
                    tmp_path.write_text(json.dumps(manifest, indent=1, sort_keys=True),
                                        encoding="utf-8")
                    os.replace(tmp_path, manifest_path)
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    # ---- HTTP ---------------------------------------------------------- #

    def _request_json(self, url: str, timeout_seconds: float) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                self.http_requests += 1
                response = self.session.get(url, timeout=timeout_seconds)
            except requests.RequestException as exc:
                last_error = exc
                self._backoff(attempt)
                continue
            if response.status_code == 404:
                raise SleeperNotFound(f"Sleeper returned 404 for {url}")
            if response.status_code == 429 or response.status_code >= 500:
                last_error = SleeperError(f"HTTP {response.status_code} from {url}")
                self._backoff(attempt)
                continue
            if response.status_code != 200:
                raise SleeperError(f"HTTP {response.status_code} from {url}")
            try:
                return response.json()
            except ValueError as exc:
                raise SleeperError(f"non-JSON response from {url}") from exc
        raise SleeperError(f"giving up on {url} after {self.max_retries + 1} attempts: {last_error}")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.throttle_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _backoff(self, attempt: int) -> None:
        if attempt < self.max_retries:
            time.sleep(min(8.0, 1.0 * (2 ** attempt)))
