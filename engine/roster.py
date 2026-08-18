"""The subscriber's roster, resolved to ids we can actually score.

WHY THIS EXISTS. Sleeper's terms forbid us reading the league (PLAN §0), so the
league half of the product now comes from the only party entitled to hand it
over: the subscriber, typing it. That makes NAME RESOLUTION the correctness
heart of the product. A wrong match does not fail loudly — it produces a
complete, confident report about a player the subscriber does not own, which is
the worst failure this product can have (principle 3).

MEASURED, NOT ASSUMED. Against nflverse's players release (Aug 18 2026):
- 6,079 of 25,040 rows carry a ``gsis_id`` that is NOT GSIS-format (``ABB498348``
  and similar — players with no GSIS id yet). They duplicate real humans: Layne
  Pryor appears as both ``00-0040792`` and ``PRY456541``. **RULE R1: only
  ``00-#######`` ids are eligible.** Skipping this filter silently doubles
  people.
- Restricted to fantasy positions with a GSIS id and ``last_season >= 2024``,
  the pool is 1,327 players with **ZERO normalised-name collisions**. Across all
  time it is 156 collisions (two Adrian Petersons, an Alex Smith at QB and
  another at TE), so **RULE R2: recency is what makes exact matching safe.** The
  window is a parameter, not a constant, because it is the load-bearing
  assumption.
- Name shapes to survive: 64 periods (A.J. Brown), 62 suffixes (Kenneth Walker
  III), 32 apostrophes (Ja'Marr Chase), 23 hyphens (Amon-Ra St. Brown), 1
  non-ASCII.

**RULE R3 — AMBIGUITY IS RETURNED, NEVER RESOLVED.** When a name matches more
than one eligible player, or none, this module says so and names the candidates.
It does not pick. Guessing here is indistinguishable from working right up until
the report goes out, and the person who knows the answer is the one typing.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# RULE R1. Anything else in that column is a player without a GSIS id, and the
# same human usually appears again WITH one.
GSIS_RE = re.compile(r"^00-\d{7}$")

# Positions a fantasy roster can hold. FB is included because leagues that use
# it slot it at RB, and excluding it would make a real roster unresolvable.
FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "FB"})

# Suffixes are dropped: managers type "Kenneth Walker" for "Kenneth Walker III"
# far more often than the reverse, and no eligible pair differs ONLY by suffix.
_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")

DEFENSE = "DEF"


def normalize(name: str) -> str:
    """Fold a typed name to its comparison form: letters only, no spaces.

    Order matters: accents are stripped before the alphabetic filter (so "José"
    becomes "jose" rather than "jos"), and suffixes go before punctuation (so
    "Jr." is caught while it still has its period).

    **Spaces and punctuation are DELETED, not collapsed.** Keeping them meant
    "JAMARR CHASE" missed "Ja'Marr Chase" and "AJ Brown" missed "A.J. Brown" —
    people do not reproduce apostrophes and periods, and a miss here is a
    subscriber who cannot finish signup. This is safe on measurement, not on
    hope: over the eligible pool (1,327 players) a letters-only key produces
    **zero collisions**, the same as the spaced form. ``test_roster.py`` asserts
    that against the real directory so the day it stops being true is loud.
    """
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    folded = _SUFFIX_RE.sub(" ", folded)
    return re.sub(r"[^a-z]", "", folded)


@dataclass(frozen=True)
class Player:
    """One rosterable entity: a real player, or a team defense."""

    player_id: str          # GSIS id, or "DEF-BAL" for a team defense
    name: str
    position: str
    team: str | None

    @property
    def is_defense(self) -> bool:
        return self.position == DEFENSE


@dataclass(frozen=True)
class Match:
    """What resolution concluded about one typed line.

    ``player`` is set only when exactly one eligible player matched. Otherwise
    ``candidates`` carries what we found so the human can choose — RULE R3.
    """

    typed: str
    player: Player | None
    candidates: tuple[Player, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.player is not None

    @property
    def reason(self) -> str | None:
        """Buyer-facing, in the report's own register — no ids, no jargon."""
        if self.resolved:
            return None
        if not self.candidates:
            return "we don't have a player by that name"
        return f"more than one player goes by that name ({len(self.candidates)})"


class PlayerDirectory:
    """Every player and defense a subscriber may name, indexed for lookup."""

    def __init__(self, players: list[Player]) -> None:
        self.players = players
        self._teams = {p.team for p in players if p.team}
        self._by_name: dict[str, list[Player]] = {}
        for player in players:
            self._by_name.setdefault(normalize(player.name), []).append(player)
        # Defenses are matched separately: a manager writes them a dozen ways
        # ("Ravens", "BAL DEF", "Baltimore Ravens D/ST"), and none of those is
        # the display name of a person.
        self._defense_alias: dict[str, Player] = {}
        for player in players:
            if player.is_defense and player.team:
                for alias in _defense_aliases(player):
                    self._defense_alias[alias] = player

    def __len__(self) -> int:
        return len(self.players)

    def resolve(self, typed: str) -> Match:
        """One typed line -> a Match. Never guesses (RULE R3)."""
        cleaned = _strip_decoration(typed, self._teams)
        if not cleaned:
            return Match(typed=typed, player=None)
        key = normalize(cleaned)
        if not key:
            return Match(typed=typed, player=None)
        defense = self._defense_alias.get(key)
        if defense is not None:
            return Match(typed=typed, player=defense)
        found = self._by_name.get(key, [])
        if len(found) == 1:
            return Match(typed=typed, player=found[0])
        return Match(typed=typed, player=None, candidates=tuple(found))

    def resolve_all(self, lines: list[str]) -> list[Match]:
        return [self.resolve(line) for line in lines if _strip_decoration(line)]


def _defense_aliases(player: Player) -> set[str]:
    """Every way a manager writes a team defense, normalised."""
    nick = player.name.split()[-1] if player.name else ""
    city = " ".join(player.name.split()[:-1]) if player.name else ""
    forms = {player.team or "", nick, player.name, city,
             f"{player.team} {DEFENSE}", f"{nick} {DEFENSE}",
             f"{player.name} {DEFENSE}"}
    return {normalize(f) for f in forms if normalize(f)}


# Decoration a paste carries: slot labels, "- BYE 10", "(KC)", projections.
# Stripped rather than parsed, because every platform writes them differently
# and the name is the only thing they all agree on.
_DECORATION = re.compile(
    r"\b(?:QB|RB|WR|TE|DEF|DST|D/ST|FLEX|BN|BE|IR|TAXI|SUPER_FLEX|SFLEX)\b"
    r"|\bBYE\b.*$|\([^)]*\)|\[[^\]]*\]|[-–—•|,]+|\d+(?:\.\d+)?",
    re.I)


def _strip_decoration(line: str, teams: set[str] | None = None) -> str:
    """Pull the human name out of one pasted line.

    Team abbreviations are stripped LAST, and only if something survives:
    "Patrick Mahomes QB KC - BYE 10" must lose the KC, while a line that is
    only "KC" IS a team defense and must come through untouched. The
    ``if kept`` guard is what draws that line — dropping it silently deletes
    every defense a subscriber enters by abbreviation.

    Note "K" is deliberately NOT in the slot-label list: it would eat the K of
    a name like "K. Walker", and a kicker's line is identifiable without it.
    """
    text = re.sub(r"\s+", " ", _DECORATION.sub(" ", line or "")).strip()
    if teams:
        kept = [w for w in text.split() if w.upper() not in teams]
        if kept:
            text = " ".join(kept)
    return text


def load_directory(players_csv: Path, teams_csv: Path,
                   min_last_season: int) -> PlayerDirectory:
    """Build the directory from nflverse's players + teams releases.

    ``min_last_season`` is RULE R2 made explicit: it is what keeps exact-name
    matching safe, so it is a required argument rather than a default somebody
    can forget. Pass the current season minus one — wide enough for a returning
    player, narrow enough that the historical Adrian Petersons stay out.
    """
    players: list[Player] = []
    with players_csv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            gsis = (row.get("gsis_id") or "").strip()
            if not GSIS_RE.match(gsis):
                continue                                   # RULE R1
            position = (row.get("position") or "").strip().upper()
            if position not in FANTASY_POSITIONS:
                continue
            last = (row.get("last_season") or "").strip()
            if not last.isdigit() or int(last) < min_last_season:
                continue                                   # RULE R2
            name = (row.get("display_name") or "").strip()
            if not name:
                continue
            players.append(Player(player_id=gsis, name=name, position=position,
                                  team=(row.get("latest_team") or "").strip() or None))

    with teams_csv.open(encoding="utf-8", newline="") as handle:
        seen: set[str] = set()
        for row in csv.DictReader(handle):
            abbr = (row.get("team_abbr") or "").strip().upper()
            name = (row.get("team_name") or "").strip()
            if not abbr or not name or abbr in seen:
                continue
            seen.add(abbr)
            players.append(Player(player_id=f"{DEFENSE}-{abbr}", name=name,
                                  position=DEFENSE, team=abbr))
    return PlayerDirectory(players)


def index_payload(directory: PlayerDirectory) -> list[list[str]]:
    """The compact form the browser downloads: [name, id, position, team].

    Measured at 1,148 players -> 47 KB raw, 15 KB gzipped, so the whole
    directory ships as a static asset and name resolution happens in front of
    the subscriber — which is the only place ambiguity can honestly be settled.
    """
    return [[p.name, p.player_id, p.position, p.team or ""]
            for p in sorted(directory.players, key=lambda p: p.name)]
