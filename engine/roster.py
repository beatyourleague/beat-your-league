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
    # The candidates fit PART of what was typed ("Hurts" -> Jalen Hurts): a
    # choice even when there is one, never a pick (RULE R3). The browser's
    # reason "partial".
    partial: bool = False

    @property
    def resolved(self) -> bool:
        return self.player is not None

    @property
    def reason(self) -> str | None:
        """Buyer-facing, in the report's own register — no ids, no jargon."""
        if self.resolved:
            return None
        if not self.candidates:
            # Not "we don't have anybody by that name": a misspelling or a
            # nickname is somebody we may well have (FUNNEL F9).
            return "we couldn't find that name — check the spelling"
        names = ", ".join(c.name for c in self.candidates)
        if self.partial:
            return (f"did you mean {names}?" if len(self.candidates) == 1
                    else f"that's part of more than one player's name — {names}")
        noun = "team" if all(c.is_defense for c in self.candidates) else "player"
        return f"more than one {noun} goes by that name — {names}"


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
        # Part of a name typed on its own ("Hurts", "St. Brown", "Puka"): the
        # lookup of last resort, and its answer is always a choice (RULE R3).
        self._by_part: dict[str, list[Player]] = {}
        for player in players:
            if not player.is_defense:
                for key in _name_part_keys(player.name):
                    self._by_part.setdefault(key, []).append(player)
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
        # What may follow a comma as a team ANNOTATION on a player's line: a
        # full team name or a code. A bare nickname ("Josh Allen, Ravens") is a
        # second roster entry and must not be swallowed.
        self._team_annotation_keys: set[str] = set()
        for player in players:
            if player.is_defense and player.team:
                for alias in _defense_aliases(player):
                    self._defense_alias.setdefault(alias, []).append(player)
                self._team_annotation_keys |= {
                    normalize(player.name), normalize(player.team),
                    *(normalize(a) for a, t in TEAM_ALIASES.items() if t == player.team)}

    def __len__(self) -> int:
        return len(self.players)

    def resolve(self, typed: str) -> Match:
        """One typed line -> a Match. Never guesses (RULE R3).

        Shapes beyond a plain name, each a lookup that must come back unique:
        "Last, First" (CBS), "Name, Team Name" (a comma then a FULL team name or
        code — a bare nickname after a comma is a second roster entry, not an
        annotation), a leading team code that is really part of a name ("KC
        Concepcion"), NFL.com's leading "K Jake Bates", and "J. Mixon" (initial
        + surname). The plain reading always goes first, so nothing that
        resolved before resolves differently."""
        typed = _tidy(typed)
        first = self._resolve_plain(typed)
        if first.resolved or first.candidates:
            return first
        if "," in typed:
            left, _, right = typed.partition(",")
            a = _strip_decoration(left, self._teams)
            b = _strip_decoration(right, self._teams)
            if a and b:
                if normalize(b) in self._team_annotation_keys:
                    retry = self._resolve_plain(left)      # "Chase Brown, Cincinnati Bengals"
                    if retry.resolved:
                        return Match(typed=typed, player=retry.player)
                found = self._by_name.get(normalize(f"{b} {a}"), [])
                if len(found) == 1:                        # "Kittle, George"
                    return Match(typed=typed, player=found[0])
        # A team code that leads a NAME ("KC Concepcion WR CLE") is stripped as
        # decoration by the plain reading; keep the lead and try once more.
        retry = self._resolve_plain(typed, keep_lead=True)
        if retry.resolved:
            return retry
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
        # Last: part of a name. Never a pick, even when one player fits — a
        # pasted "Allen" with one Allen in the directory is still a guess at
        # which Allen (RULE R3). Every fit, by name: this side has no scoring
        # to rank on, and the browser's eight-by-points list is a display cap,
        # not a different answer — both say "choose", neither picks.
        part = normalize(cleaned)
        fits = self._by_part.get(part, []) if len(part) >= 3 else []
        if fits:
            return Match(typed=typed, player=None, partial=True,
                         candidates=tuple(sorted(fits, key=lambda p: (p.name, p.player_id))))
        return first

    def _resolve_plain(self, typed: str, keep_lead: bool = False) -> Match:
        cleaned = _strip_decoration(typed, self._teams, keep_lead=keep_lead)
        key = normalize(cleaned)
        if not key:
            return Match(typed=typed, player=None)
        # Defense aliases and display names are ONE pool, like the browser's
        # index: an alias that collides with a player's name comes back as a
        # choice on both sides, never a silent pick of the defense.
        pool: dict[str, Player] = {}
        for candidate in self._defense_alias.get(key, []) + self._by_name.get(key, []):
            pool.setdefault(candidate.player_id, candidate)
        found = list(pool.values())
        if len(found) == 1:
            return Match(typed=typed, player=found[0])
        return Match(typed=typed, player=None, candidates=tuple(found))

    def _resolve_row(self, line: str) -> Match | None:
        """One pasted row -> a Match, or None for a blank row.

        A desktop copy of a roster table arrives tab-separated, and the name is
        one cell among several ("Josh Allen QB BUF vs. Miami Dolphins ..."). The
        longest cell used to win, which made an OPPONENT cell into a phantom
        defense and silently dropped the player. Every cell is resolved; a
        player beats a defense (the defense cell is the player's team or
        opponent), and the longest of the resolved cells breaks a tie."""
        cells = [c for c in (part.strip() for part in line.split("\t")) if c]
        if len(cells) <= 1:
            text = cells[0] if cells else line.strip()
            if _is_blank(_strip_decoration(text, self._teams)):
                return None
            return self.resolve(text)
        results = [(cell, self.resolve(cell)) for cell in cells
                   if not _is_blank(_strip_decoration(cell, self._teams))]
        if not results:
            return None
        resolved = [(c, m) for c, m in results if m.resolved]
        players = [(c, m) for c, m in resolved if not m.player.is_defense]
        # BE-D1 (Oct 2026): "PhiQB<tab>CAR<tab>Sun 1:00 PM" — the player's
        # team-and-position cell, his OPPONENT's code, his kickoff — read as
        # the Panthers defense, because a lone code cell resolves to one. When
        # nothing but bare codes resolved, the row is judged whole, the way a
        # one-line row is: codes beside a position tag or matchup text and no
        # DEF tag are a player's team or opponent, not a roster entry.
        if not players and resolved and all(
                self._code_only(cell) for cell, _ in resolved):
            if _is_blank(_strip_decoration(" ".join(cells), self._teams)):
                return None
        pool = players or resolved or results
        return max(pool, key=lambda pair: len(pair[0]))[1]

    def _code_only(self, line: str) -> str | None:
        """The team (nflverse code) when this row reads as a defense ONLY
        because it is a bare team code — "PHI", "Phi", "LAR" — with no DEF tag
        anywhere on it; otherwise None. Those are the rows a table copy makes
        out of a player's team column or his opponent's, so they are the only
        ones whose meaning depends on the lines around them."""
        cells = [c for c in (part.strip() for part in line.split("\t")) if c]
        raw = _unglue(_tidy(" ".join(cells)), self._teams)
        if _DEFENSE_TAG.search(raw):
            return None
        tokens = _strip_decoration(" ".join(cells), self._teams).split()
        if len(tokens) != 1:
            return None
        word = tokens[0].upper()
        if word not in self._teams and word not in TEAM_ALIASES:
            return None
        return TEAM_ALIASES.get(word, word)

    def resolve_all(self, lines: list[str]) -> list[Match]:
        """Every non-blank line, in order. Blank means no LETTER survives
        stripping WITH the team set — a "Buf - QB" line is a player's team and
        position, not a roster entry, and a line of emoji or bullets is not
        one either; but a line of letters in ANY script is reported back, never
        dropped. The same player on consecutive lines is one entry: Yahoo prints
        a defense's name and then its "Den - DEF" row.

        **A bare team code is read in context (BE-D1, Oct 2026).** ESPN's
        roster table copies out one cell per line — "Jalen Hurts / Phi / QB /
        CAR" — and every team-code line became a team defense: a real copy
        produced eleven defenses for a roster that owned one, the tally said
        "Looks right", and the report started the Broncos. After an entry, a
        bare code is that entry's TEAM line when it is his team or the next
        line is a position tag (a player whose team moved since our list was
        built), and once his own position line has been read a bare code is
        his OPPONENT. Neither is a roster entry. A bare code anywhere else is
        still a defense, as typed."""
        lines = list(lines)
        out: list[Match] = []
        # What has been read since the last entry: its team line, its own
        # position line. None before the first entry.
        block: dict[str, bool] | None = None
        for index, line in enumerate(lines):
            match = self._resolve_row(line)
            if match is None:
                tags = _position_line(line, self._teams)
                if block is not None and tags and _plays(out[-1].player, tags):
                    block["position"] = True
                continue
            code = self._code_only(line)
            if code and block is not None:
                last = out[-1].player
                if not block["team"] and not block["position"] and (
                        (last is not None and _canonical(last.team) == code)
                        or _position_line(_next_line(lines, index), self._teams)):
                    block["team"] = True
                    continue
                if block["position"]:
                    continue
            if (match.resolved and out and out[-1].resolved
                    and out[-1].player.player_id == match.player.player_id):
                continue
            out.append(match)
            block = {"team": False, "position": False}
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
    r"|\b(?:QB|RB|WR|TE|FB|DEF|DST|D/ST|FLEX|BN|BE|IR|TAXI|SUPER_FLEX|SFLEX"
    r"|BENCH|STARTERS?|RESERVES?|OUT|DTD|SSPD|SUSP|PUP|NFI|INJ|NA|AM|PM)\b"
    # ESPN's roster table copies its column headings and totals row out with
    # the players (BE-D1, a real copy, Oct 2026): each one stopped the signup
    # as "we don't have anybody by that name". "%ST" and "%ROST" only with
    # their percent sign — a bare ST is the St. of Amon-Ra St. Brown.
    r"|\b(?:SLOT|PLAYERS?|OPP|STATUS|PROJ|SCORE|OPRK|PRK|FPTS|AVG|LAST|TOTALS?"
    r"|NFL|WEEK|SEASON)\b|%\s*(?:ST|ROST)\b|\b\d+(?:ST|ND|RD|TH)\b"
    r"|\bVS\.?(?=\s|$)"
    r"|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b.*$"
    r"|\bBYE\b.*$|\([^)]*\)|\[[^\]]*\]|[-–—•|,:*@+%]+|\d+(?:\.\d+)?",
    # ASCII: the browser's \b is ASCII-only, and the two parsers must agree
    # character for character on what a word boundary is.
    re.I | re.A)

_POSITION_TAG = re.compile(r"\b(?:QB|RB|WR|TE|FB|K)\b", re.I | re.A)
_DEFENSE_TAG = re.compile(r"\b(?:DEF|DST|D/ST)\b", re.I | re.A)
# Words and marks that only ever sit on a PLAYER's row or a status line: matchup
# ("vs.", "@"), kickoff time, bye, an injury tag, a projection number. A lone
# team code beside any of them is that team as an OPPONENT or a bye note, never
# a roster entry ("vs. MIA", "BUF (Bye 7)", "Buf - Q").
_NOISE = re.compile(
    r"\bVS\b|@|\bBYE\b|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b"
    r"|\b(?:OUT|DTD|SSPD|SUSP|PUP|NFI|INJ|NA)\b|\d", re.I | re.A)
# Every kind of whitespace the browser's \s does not know about is a plain space.
_WHITESPACE = re.compile(r"[\s\u0085\u001c-\u001f\u00a0\u2028\u2029\ufeff]+")


def _name_part_keys(name: str) -> set[str]:
    """The parts of a name a manager types on its own (FUNNEL F9, BE2-D2): the
    first name and every tail — "Brown" and "St. Brown" from "Amon-Ra St.
    Brown", "Walker" from "Kenneth Walker III" (the suffix folds away). Under
    three letters is too little to go on. Mirrors roster.js namePartKeys."""
    words = [w for w in re.split(r"[\s-]+", (name or "").strip()) if w]
    if len(words) < 2:
        return set()
    keys = {normalize(words[0])} | {normalize(" ".join(words[i:]))
                                    for i in range(1, len(words))}
    return {key for key in keys if len(key) >= 3}


def _tidy(line: str) -> str:
    return _WHITESPACE.sub(" ", line or "").strip()


# Tags a table copy glues onto the cell before them when the cells carry no
# whitespace between them (BE-D1, a real ESPN copy): "PhiQB" (team + position),
# "Jalen HurtsQ" (name + injury status), "Eagles D/STD/ST" (the defense tag
# twice). Uppercase only, longest first; the browser twin is character-equal.
_GLUE_TAG = r"(?:D/ST|DST|DEF|SSPD|SUSP|DTD|OUT|PUP|NFI|IR|QB|RB|WR|TE|FB|K|Q|O|D|P)"
_GLUED_TO_NAME = re.compile(rf"^([A-Za-z.'-]*[a-z.'])((?:{_GLUE_TAG})+)$", re.A)
_GLUED_CODE = re.compile(rf"^([A-Z]{{2,3}})((?:{_GLUE_TAG})+)$", re.A)
_DOUBLED_DEFENSE = re.compile(r"^(?:D/ST|DST|DEF){2,}$", re.A)
_ONE_TAG = re.compile(_GLUE_TAG, re.A)


def _unglue(raw: str, teams: set[str] | None = None) -> str:
    """Put the missing space back between a cell and a tag glued onto it.

    Three shapes, each narrow on purpose, because a real name must never be
    split: a tag run after a LOWERCASE letter ("HurtsQ", "PhiQB" — no real
    name ends lowercase-then-capital), a tag run after a team code
    ("PHIQB", only when the code is a real team), and a doubled defense tag
    ("D/STD/ST"). "DK Metcalf" and "AJ Brown" are untouched: all-caps tokens
    split only behind a team code. ``test_no_directory_player_is_mangled``
    holds that across every name in the directory, in both languages."""
    words = []
    for word in raw.split(" "):
        glued = _GLUED_TO_NAME.match(word)
        # A token that IS a team code is never split: "SFO" is San Francisco,
        # not SF plus an "O" (out) tag.
        is_code = bool(teams) and (word.upper() in teams or word.upper() in TEAM_ALIASES)
        coded = None if is_code else _GLUED_CODE.match(word)
        if _DOUBLED_DEFENSE.match(word):
            words.extend(_ONE_TAG.findall(word))
        elif glued:
            words.extend([glued.group(1), *_ONE_TAG.findall(glued.group(2))])
        elif coded and teams and (coded.group(1) in teams
                                  or coded.group(1) in TEAM_ALIASES):
            words.extend([coded.group(1), *_ONE_TAG.findall(coded.group(2))])
        else:
            words.append(word)
    return " ".join(words)


_POSITION_WORDS = frozenset({"QB", "RB", "WR", "TE", "K", "FB", "DEF", "DST"})
_PLAYER_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "FB"})


def _position_line(line: str | None, teams: set[str] | None = None) -> frozenset[str]:
    """The position tags a line holds when it holds NOTHING else ("QB",
    "D/ST", "RB/WR") — the third cell of a table copy's player block — or
    an empty set."""
    raw = _unglue(_tidy(line or ""), teams).upper().replace("D/ST", "DST")
    words = [w for w in re.split(r"[\s/,]+", raw) if w]
    if words and all(w in _POSITION_WORDS for w in words):
        return frozenset(words)
    return frozenset()


def _plays(player: Player | None, tags: frozenset[str]) -> bool:
    """Is this position line the entry's OWN position? For an entry we could
    not resolve only a player position counts — a "DEF" header after an
    unknown name is as likely the next slot's label."""
    if player is None:
        return bool(tags & _PLAYER_POSITIONS)
    if player.is_defense:
        return bool(tags & {"DEF", "DST"})
    return player.position in tags or (player.position == "FB" and "RB" in tags)


def _canonical(team: str | None) -> str | None:
    team = (team or "").upper()
    return TEAM_ALIASES.get(team, team) or None


def _next_line(lines: list[str], index: int) -> str | None:
    """The next line with anything on it."""
    for line in lines[index + 1:]:
        if _tidy(line):
            return line
    return None


def exact_name(typed: str, name: str, teams: set[str] | None = None) -> bool:
    """Is what was typed this player's FULL name, letter for letter (case and
    spacing aside)? I15 (Oct 2026): "Bijan Robinson" pasted exactly still
    offered "not Brian Robinson? tap to swap", which reads as doubt about a
    household name. A near-name alternate is offered only when this is False.
    The browser's twin decides it the same way (tests/test_intake.py)."""
    def fold(text: str) -> str:
        return " ".join(text.lower().split())
    return fold(_strip_decoration(typed, teams)) == fold(name)


# What a copy of a whole page sweeps up: column heads, section labels, buttons,
# status words and game results, in normalize()'s form (decoration already off,
# so "Final W 24-17" arrives as "finalw"). Each used to come back "we can't read
# this line", so a buyer who selected the page had dozens to delete by hand
# before checkout. Only a WHOLE line matches: nothing that carries a name can.
# The browser twin in site/join/roster.js holds the same list, in the same order.
_PAGE_WORDS = frozenset("""
    offense defense defensespecialteams kickers kicker injured squad pos position
    opponent projected projection fanpts pts points rank start owned stats action
    actions add drop trade move editlineup setlineup startactive empty matchup myteam
    roster team standings scoreboard research videoforecast note nonewnotes nonewplayernotes
    newnote
    freeagent waivers waiverclaim gametimedecision questionable doubtful active inactive
    final finalw finall l w tnf mnf superflex super dl db idp hc mylineup waiverwire
    close save submit done lineuplocked espnfantasy yahoofantasy sleeper cbssports
""".split())


def _is_blank(cleaned: str) -> bool:
    """Nothing to resolve: no LETTER of any script survives (emoji and bullets
    are blank; a line of Cyrillic is not — it is reported back), or the whole
    line is the page around the roster, not a roster entry."""
    return not re.search(r"[^\W\d_]", cleaned or "") or normalize(cleaned) in _PAGE_WORDS


def _strip_decoration(line: str, teams: set[str] | None = None,
                      keep_lead: bool = False) -> str:
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

    ``keep_lead`` keeps a team code that LEADS the line: "KC Concepcion WR CLE"
    is a player named KC, and stripping both codes leaves "Concepcion".
    """
    raw = _unglue(_tidy(line), teams)
    text = re.sub(r"\s+", " ", _DECORATION.sub(" ", raw)).strip()
    text = re.sub(r"(?<=[^\s.]) K(?= |$)", "", text, flags=re.I).strip()
    # Single-letter injury tags (Q, O, D, P) trail a name or stand alone on a
    # line, and a lone "K" is a kicker slot header; an INITIAL leads a name
    # and carries its dot, so neither is touched.
    tokens = text.split()
    kept_tokens = [t for i, t in enumerate(tokens)
                   if not (re.fullmatch(r"[QODPqodp]", t) and (i > 0 or len(tokens) == 1))]
    removed_tag = len(kept_tokens) != len(tokens)
    tokens = kept_tokens
    if len(tokens) == 1 and tokens[0].upper() == "K":
        tokens = []
    text = " ".join(tokens)
    if teams:
        def is_team(word: str) -> bool:
            return word.upper() in teams or word.upper() in TEAM_ALIASES
        # A team code beside a position tag is a PLAYER's team line ("Buf - QB",
        # "QB - BUF", "Den - WR" — how Yahoo and Sleeper lay a roster out), and
        # beside matchup, bye, status or projection text it is an opponent or a
        # note ("vs. MIA", "BUF (Bye 7)", "Buf - Q") — not a defense. Read as
        # one it silently added a defense the subscriber does not own. A defense
        # carries DEF/DST/D/ST or stands alone ("KC").
        # Every word a team code counts the same way: "PhiQB CAR Sun 1:00 PM"
        # is a player's own team and his opponent (BE-D1), not two defenses.
        if (tokens and all(is_team(t) for t in tokens) and not _DEFENSE_TAG.search(raw)
                and (_POSITION_TAG.search(raw) or _NOISE.search(raw) or removed_tag)):
            return ""
        kept = [w for i, w in enumerate(tokens)
                if not (is_team(w) and not (keep_lead and i == 0))]
        # A bare K left once a team code is gone is a kicker's TEAM line, laid
        # out position-first the way Sleeper writes it ("K - PIT", "K DAL").
        # Read as a name it was an unknown player that blocked checkout. Only
        # when a team code was actually stripped: a lone "K" is already blank
        # above, and "K Walker" never loses a word here.
        if len(kept) < len(tokens) and [w.upper() for w in kept] == ["K"]:
            return ""
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
