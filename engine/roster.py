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
            return "we don't have anybody by that name"
        noun = "team" if all(c.is_defense for c in self.candidates) else "player"
        return (f"more than one {noun} goes by that name — "
                f"{', '.join(c.name for c in self.candidates)}")


class PlayerDirectory:
    """Every player and defense a subscriber may name, indexed for lookup."""

    def __init__(self, players: list[Player]) -> None:
        self.players = players
        self._teams = {p.team for p in players if p.team}
        self._by_name: dict[str, list[Player]] = {}
        # (first initial, normalised surname) -> players. Sleeper's mobile
        # roster writes "J. Mixon"; a UNIQUE initial-plus-surname match is a
        # lookup, not a guess (two of them come back as a choice, RULE R3).
        self._by_initial: dict[tuple[str, str], list[Player]] = {}
        for player in players:
            self._by_name.setdefault(normalize(player.name), []).append(player)
            if not player.is_defense and " " in player.name.strip():
                first, _, rest = player.name.strip().partition(" ")
                key = (first[:1].lower(), normalize(rest))
                if key[1]:
                    self._by_initial.setdefault(key, []).append(player)
        # Defenses are matched separately: a manager writes them a dozen ways
        # ("Ravens", "BAL DEF", "Baltimore Ravens D/ST"), and none of those is
        # the display name of a person.
        #
        # This is a dict of LISTS, and that is not defensive coding. As a plain
        # dict it was last-writer-wins, and shipped: "Rams" resolved to the ST.
        # LOUIS Rams, "Chargers" to San Diego, "Raiders" to Oakland — a guess,
        # silently, which is exactly what RULE R3 forbids. Restricting to the
        # current 32 teams fixes those three; it does NOT fix "New York" or
        # "Los Angeles", which are genuinely ambiguous between two live teams
        # and must come back as a choice.
        self._defense_alias: dict[str, list[Player]] = {}
        for player in players:
            if player.is_defense and player.team:
                for alias in _defense_aliases(player):
                    self._defense_alias.setdefault(alias, []).append(player)

    def __len__(self) -> int:
        return len(self.players)

    def resolve(self, typed: str) -> Match:
        """One typed line -> a Match. Never guesses (RULE R3).

        Three shapes beyond a plain name, each a lookup that must come back
        unique: "Last, First" (CBS), "Name, Team Name" (a comma then a full
        team name) and "J. Mixon" (initial + surname). The plain reading always
        goes first, so nothing that resolved before resolves differently."""
        first = self._resolve_plain(typed)
        if first.resolved or first.candidates:
            return first
        if "," in typed:
            left, _, right = typed.partition(",")
            a = _strip_decoration(left, self._teams)
            b = _strip_decoration(right, self._teams)
            if a and b:
                if normalize(b) in self._defense_alias:
                    retry = self._resolve_plain(a)         # "Chase Brown, Cincinnati Bengals"
                    if retry.resolved:
                        return Match(typed=typed, player=retry.player)
                found = self._by_name.get(normalize(f"{b} {a}"), [])
                if len(found) == 1:                        # "Kittle, George"
                    return Match(typed=typed, player=found[0])
        cleaned = _strip_decoration(typed, self._teams)
        # NFL.com leads a kicker's row with the position: "K Jake Bates". A
        # bare leading K followed by TWO more words is a tag; "K Walker" (one
        # word after) stays an initial.
        tag = re.match(r"^K\s+(\S+\s+\S.*)$", cleaned)
        if tag:
            found = self._by_name.get(normalize(tag.group(1)), [])
            if len(found) == 1:
                return Match(typed=typed, player=found[0])
        m = re.match(r"^([A-Za-z])\.?\s+(.+)$", cleaned)
        if m:
            found = self._by_initial.get((m.group(1).lower(), normalize(m.group(2))), [])
            if len(found) == 1:
                return Match(typed=typed, player=found[0])
            if found:
                return Match(typed=typed, player=None, candidates=tuple(found))
        return first

    def _resolve_plain(self, typed: str) -> Match:
        cleaned = _strip_decoration(typed, self._teams)
        if not cleaned:
            return Match(typed=typed, player=None)
        key = normalize(cleaned)
        if not key:
            return Match(typed=typed, player=None)
        defenses = self._defense_alias.get(key, [])
        if len(defenses) == 1:
            return Match(typed=typed, player=defenses[0])
        if defenses:
            return Match(typed=typed, player=None, candidates=tuple(defenses))
        found = self._by_name.get(key, [])
        if len(found) == 1:
            return Match(typed=typed, player=found[0])
        return Match(typed=typed, player=None, candidates=tuple(found))

    def resolve_all(self, lines: list[str]) -> list[Match]:
        """Every non-blank line, in order. Blank means nothing survives
        stripping WITH the team set — a "Buf - QB" line is a player's team and
        position, not a roster entry. The same player on consecutive lines is
        one entry: Yahoo prints a defense's name and then its "Den - DEF" row."""
        out: list[Match] = []
        for line in lines:
            if not _strip_decoration(line, self._teams):
                continue
            match = self.resolve(line)
            if (match.resolved and out and out[-1].resolved
                    and out[-1].player.player_id == match.player.player_id):
                continue
            out.append(match)
        return out


def _defense_aliases(player: Player) -> set[str]:
    """Every way a manager writes a team defense, normalised."""
    nick = player.name.split()[-1] if player.name else ""
    city = " ".join(player.name.split()[:-1]) if player.name else ""
    forms = {player.team or "", nick, player.name, city,
             f"{player.team} {DEFENSE}", f"{nick} {DEFENSE}",
             f"{player.name} {DEFENSE}"}
    forms |= {alias for alias, team in TEAM_ALIASES.items() if team == player.team}
    return {normalize(f) for f in forms if normalize(f)}


# Decoration a paste carries: slot labels, "- BYE 10", "(KC)", projections.
# Stripped rather than parsed, because every platform writes them differently
# and the name is the only thing they all agree on.
# How the league apps spell teams whose nflverse code differs (ESPN, Yahoo and
# Sleeper write the Rams "LAR", the Commanders "WSH"/"WAS", and so on), plus
# the long forms some exports use. Stripped like a team code, and accepted as a
# defense on their own. Found Sep 29 2026: "Puka Nacua LAR WR" pasted from ESPN
# failed to resolve and stopped the signup.
TEAM_ALIASES = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "LVR": "LV", "ARZ": "ARI",
                "GNB": "GB", "KAN": "KC", "NOR": "NO", "NWE": "NE", "SFO": "SF",
                "TAM": "TB", "HST": "HOU", "BLT": "BAL", "CLV": "CLE"}


# "Bench", "Starters", "Reserve(s)" are the section headers every league app
# copies out with the roster; left in, each became an "unknown player" line.
# Also stripped (Sep 29 2026, a battery of Yahoo / CBS / NFL.com / Sleeper /
# ESPN pastes): multi-position slot labels ("W/R/T"), injury and status tags
# ("OUT", "DTD", "SSPD"), matchup and kickoff text ("vs. MIA", "@ NYG",
# "Sun 1:00 PM", "AM"/"PM") and the punctuation those carry.
_DECORATION = re.compile(
    r"\b(?:W/R/T|R/W/T|W/R|W/T|OP)\b"
    r"|\b(?:QB|RB|WR|TE|DEF|DST|D/ST|FLEX|BN|BE|IR|TAXI|SUPER_FLEX|SFLEX"
    r"|BENCH|STARTERS?|RESERVES?|OUT|DTD|SSPD|SUSP|PUP|NFI|INJ|NA|AM|PM)\b"
    r"|\bVS\.?(?=\s|$)"
    r"|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b.*$"
    r"|\bBYE\b.*$|\([^)]*\)|\[[^\]]*\]|[-–—•|,:*@+]+|\d+(?:\.\d+)?",
    re.I)

_POSITION_TAG = re.compile(r"\b(?:QB|RB|WR|TE|K)\b", re.I)
_DEFENSE_TAG = re.compile(r"\b(?:DEF|DST|D/ST)\b", re.I)


def _strip_decoration(line: str, teams: set[str] | None = None) -> str:
    """Pull the human name out of one pasted line.

    Team abbreviations are stripped LAST, and only if something survives:
    "Patrick Mahomes QB KC - BYE 10" must lose the KC, while a line that is
    only "KC" IS a team defense and must come through untouched. The
    ``if kept`` guard is what draws that line — dropping it silently deletes
    every defense a subscriber enters by abbreviation.

    Note "K" is deliberately NOT in the slot-label list: it would eat the K of
    a name like "K. Walker". But a NON-LEADING bare K is a position tag —
    "Jake Bates K DET" is how a kicker's row pastes out of every league app,
    and refusing it made every pasted kicker an unresolved line. An initial
    only ever leads a name, so position matters more than the letter.
    """
    text = re.sub(r"\s+", " ", _DECORATION.sub(" ", line or "")).strip()
    text = re.sub(r"(?<=[^\s.]) K(?= |$)", "", text, flags=re.I).strip()
    # Single-letter injury tags (Q, O, D, P) trail a name or stand alone on a
    # line, and a lone "K" is a kicker slot header; an INITIAL leads a name
    # and carries its dot, so neither is touched.
    tokens = text.split()
    tokens = [t for i, t in enumerate(tokens)
              if not (re.fullmatch(r"[QODPqodp]", t) and (i > 0 or len(tokens) == 1))]
    if len(tokens) == 1 and tokens[0].upper() == "K":
        tokens = []
    text = " ".join(tokens)
    if teams:
        def is_team(word: str) -> bool:
            return word.upper() in teams or word.upper() in TEAM_ALIASES
        # A team code beside a position tag is a PLAYER's team line ("Buf - QB",
        # "QB - BUF", "Den - WR" — how Yahoo and Sleeper lay a roster out), not
        # a defense: read as one it silently added a defense the subscriber
        # does not own. A defense carries DEF/DST or stands alone ("KC").
        if (len(tokens) == 1 and is_team(tokens[0]) and _POSITION_TAG.search(line or "")
                and not _DEFENSE_TAG.search(line or "")):
            return ""
        kept = [w for w in text.split() if not is_team(w)]
        if kept:
            text = " ".join(kept)
    return text


def load_directory(players_csv: Path, teams_csv: Path, min_last_season: int,
                   eligible_teams: frozenset[str] | set[str]) -> PlayerDirectory:
    """Build the directory from nflverse's players + teams releases.

    Both filters are REQUIRED ARGUMENTS on purpose — each one is load-bearing
    and each one shipped a real bug the first time it was implicit.

    ``min_last_season`` is RULE R2: exact-name matching is only safe inside a
    recent window (all-time there are two Adrian Petersons). Pass the current
    season minus one.

    ``eligible_teams`` is the set that actually plays this season, from
    ``ingest.nflverse.season_teams``. The teams release keeps relocated
    franchises forever — 36 rows for 32 teams — so without it a subscriber is
    offered the St. Louis Rams.
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
            if abbr not in eligible_teams:
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
