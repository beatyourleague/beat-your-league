"""The signup reference: a whole subscription, encoded to ride on a payment.

This is the contract between two places that never talk to each other — the
picker in the browser (``site/join/index.html``) writes it into Stripe's
``client_reference_id``, and ``run/sync.py`` reads it back on Tuesday. Nothing
in between stores it, which is the entire point: there is no second list.

Format — deliberately boring, because Stripe accepts only ``[A-Za-z0-9_-]`` and
at most 200 characters, and silently drops anything else while still showing a
working payment page:

    <plan>-<user_id>-<league_id>-<rival>

    plan   s = season pass, m = monthly, p = league pass (commissioner)
    rival  a Sleeper owner_id, or r<roster_id> for an orphaned team

    s-457511950237696-289646328504385536-189140835533586432   (55 chars)
    p-457511950237696-289646328504385536-r6

A league-pass ref is ALSO an individual signup: the commissioner gets their own
report aimed at their own rival, and separately their payment covers the
league. One purchase, two meanings, one string.

Every function here is pure and offline. That is on purpose — this codec is the
one component whose failure is silent (a mangled ref becomes a payment nobody
can attribute), so it must be exhaustively testable without a network.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

# What Stripe accepts on client_reference_id. Enforced on both sides: the
# browser refuses to navigate with a bad ref, and we refuse to decode one.
STRIPE_REF_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")

SEASON = "season"
MONTHLY = "monthly"
LEAGUE_PASS = "league_pass"

_PREFIX_TO_PLAN = {"s": SEASON, "m": MONTHLY, "p": LEAGUE_PASS}
_PLAN_TO_PREFIX = {plan: prefix for prefix, plan in _PREFIX_TO_PLAN.items()}

_ID_RE = re.compile(r"^\d{6,20}$")


class RefError(ValueError):
    """A reference we cannot turn back into a subscription."""


@dataclass(frozen=True)
class SignupRef:
    plan: str                      # season | monthly | league_pass
    user_id: str
    league_id: str
    rival_owner_id: str | None
    rival_roster_id: int | None

    @property
    def is_league_pass(self) -> bool:
        return self.plan == LEAGUE_PASS

    @property
    def registry_plan(self) -> str:
        """How run/registry.py spells this. Monthly and season are the same
        product to the pipeline — they differ only in how often it bills — and
        the commissioner's own seat is an individual entry, not a covered one:
        they paid for it themselves."""
        return "season"


def encode(plan: str, user_id: str, league_id: str,
           rival_owner_id: str | None = None,
           rival_roster_id: int | None = None) -> str:
    """Build the ref the picker puts on the checkout URL."""
    if plan not in _PLAN_TO_PREFIX:
        raise RefError(f"unknown plan {plan!r}")
    if not _ID_RE.match(str(user_id)):
        raise RefError(f"user_id must be a Sleeper id, got {user_id!r}")
    if not _ID_RE.match(str(league_id)):
        raise RefError(f"league_id must be a Sleeper id, got {league_id!r}")
    if rival_owner_id and _ID_RE.match(str(rival_owner_id)):
        rival = str(rival_owner_id)
    elif rival_roster_id is not None and int(rival_roster_id) >= 1:
        rival = f"r{int(rival_roster_id)}"
    else:
        raise RefError("a ref needs a rival owner_id or roster_id")
    ref = f"{_PLAN_TO_PREFIX[plan]}-{user_id}-{league_id}-{rival}"
    if not STRIPE_REF_RE.match(ref):
        # Unreachable given the checks above; kept because the consequence of
        # being wrong is a payment Stripe accepts and we cannot attribute.
        raise RefError(f"encoded ref is not Stripe-safe: {ref!r}")
    return ref


def decode(ref: str) -> SignupRef:
    """Turn a client_reference_id back into a subscription.

    Raises RefError on anything unrecognised. Callers treat that as "this
    payment needs a human", never as a reason to guess — an invented league id
    would mail someone another manager's team.
    """
    if not isinstance(ref, str) or not STRIPE_REF_RE.match(ref):
        raise RefError(f"not a Stripe-safe reference: {ref!r}")
    parts = ref.split("-")
    if len(parts) != 4:
        raise RefError(f"expected 4 dash-separated fields, got {len(parts)}: {ref!r}")
    prefix, user_id, league_id, rival = parts
    if prefix not in _PREFIX_TO_PLAN:
        raise RefError(f"unknown plan prefix {prefix!r} in {ref!r}")
    if not _ID_RE.match(user_id):
        raise RefError(f"bad user_id in {ref!r}")
    if not _ID_RE.match(league_id):
        raise RefError(f"bad league_id in {ref!r}")
    rival_owner_id: str | None = None
    rival_roster_id: int | None = None
    if rival.startswith("r"):
        if not rival[1:].isdigit() or int(rival[1:]) < 1:
            raise RefError(f"bad rival roster in {ref!r}")
        rival_roster_id = int(rival[1:])
    elif _ID_RE.match(rival):
        rival_owner_id = rival
    else:
        raise RefError(f"bad rival in {ref!r}")
    return SignupRef(
        plan=_PREFIX_TO_PLAN[prefix],
        user_id=user_id,
        league_id=league_id,
        rival_owner_id=rival_owner_id,
        rival_roster_id=rival_roster_id,
    )


# --------------------------------------------------------------------- #
# v2 — the roster ref, for the product that no longer reads Sleeper
# --------------------------------------------------------------------- #
#
# PLAN §0: the league half now comes from the subscriber typing it, so the ref
# has to carry a whole roster instead of two Sleeper ids. Same contract, same
# constraints — [A-Za-z0-9_-], 200 characters, silently dropped if malformed.
#
#     <plan>2-<scoring><slots>-<packed roster>
#
#     s2-pQRRWWTFKD-AAo1ugALQ8sACg7v...
#
# The "2" is a format marker, so a v1 and a v2 ref can never be mistaken for
# each other. The packed roster is LAST and is read with maxsplit, because
# base64url's alphabet includes "-" and "_" — using either as a field separator
# would corrupt exactly the payload it was meant to delimit. That is the whole
# reason the roster is not in the middle.
#
# MEASURED: each entity packs into 3 bytes, so 16 entities cost 64 characters
# and a full ref lands near 75 of the 200 available. Real GSIS numbers top out
# around 41,600 against a 16,777,215 ceiling, so the width is not close to
# tight and does not need revisiting for decades.

ROSTER_MARKER = "2"
# v3 adds the LEAGUE SIZE, which the picker had been asking for and throwing
# away: the page says "scoring and league size decide how every player in your
# roster is valued", the radios were never read, and RosterSignup.league_size
# defaulted to 12 for everyone. Size sets the positional prior's depth, so it
# moves every published probability, and it is part of the ledger store id
# (typed-{scoring}-{size}-{season}) — so a 14-team subscriber was both getting
# 12-team numbers and having them recorded in the 12-team bucket, corrupting
# the calibration table the ledger exists to produce. Found Aug 24 2026.
# Safe to change the format because checkout has never opened: no v2 ref has
# ever been issued to anybody. v2 still decodes, as 12, so nothing that exists
# breaks.
ROSTER_MARKER_V3 = "3"

# One char, at a FIXED position (settings[1]), so slots stay unambiguous:
# scoring codes are lowercase, slot codes uppercase, size codes lowercase.
SIZES = {"a": 8, "b": 10, "c": 12, "d": 14}
_SIZE_TO_CODE = {v: k for k, v in SIZES.items()}
DEFAULT_LEAGUE_SIZE = 12

# Scoring only has to distinguish what changes a projection's ranking. Anything
# finer belongs in a settings object the subscriber confirms, not in a URL.
SCORING = {"p": "ppr", "h": "half_ppr", "s": "standard"}
_SCORING_TO_CODE = {v: k for k, v in SCORING.items()}

# One letter per starting slot, in lineup order.
SLOTS = {"Q": "QB", "R": "RB", "W": "WR", "T": "TE", "F": "FLEX",
         "K": "K", "D": "DEF", "S": "SUPER_FLEX"}

# Defenses live in a reserved high range that no GSIS number can reach, with
# the team's letters encoded in place rather than an index into a list — an
# index would silently repoint at a different team the year a franchise moves,
# which is the same class of bug that made "Rams" mean St. Louis.
_DEFENSE_FLAG = 0xFF0000
# The real ceiling is the GSIS format itself: seven digits cannot exceed
# 9,999,999, which is comfortably below the defense flag. Written as what the
# format allows rather than as what 24 bits allow, so that widening the id
# format becomes a visible change here instead of a silent collision — a player
# packed at or above the flag would decode as a team defense.
# test_a_player_number_can_never_reach_the_defense_flag pins the gap.
_MAX_PLAYER = 9_999_999

MAX_ROSTER = 30          # a deep dynasty bench; 30 entities is 120 ref chars


@dataclass(frozen=True)
class RosterRef:
    """A whole league setup, decoded from one payment."""

    plan: str
    scoring: str                 # ppr | half_ppr | standard
    slots: tuple[str, ...]       # starting slots, in lineup order
    player_ids: tuple[str, ...]  # GSIS ids and DEF-<abbr>, roster order
    league_size: int = DEFAULT_LEAGUE_SIZE

    @property
    def is_league_pass(self) -> bool:
        return self.plan == LEAGUE_PASS

    @property
    def registry_plan(self) -> str:
        return "season"


def _pack_one(player_id: str) -> int:
    if player_id.startswith("DEF-"):
        abbr = player_id[4:].upper()
        if not (2 <= len(abbr) <= 3) or not abbr.isalpha():
            raise RefError(f"bad defense id {player_id!r}")
        value = 0
        for index in range(3):
            letter = abbr[index] if index < len(abbr) else None
            value = (value << 5) | (ord(letter) - 64 if letter else 0)
        return _DEFENSE_FLAG | value
    if not re.match(r"^00-\d{7}$", player_id):
        raise RefError(f"not a GSIS id {player_id!r}")
    number = int(player_id[3:])
    if number > _MAX_PLAYER:
        raise RefError(f"player id out of range {player_id!r}")
    return number


def _unpack_one(value: int) -> str:
    if value & _DEFENSE_FLAG == _DEFENSE_FLAG:
        letters = ""
        for shift in (10, 5, 0):
            code = (value >> shift) & 0x1F
            if code:
                letters += chr(code + 64)
        if not letters:
            raise RefError("defense entry carries no team")
        return f"DEF-{letters}"
    return f"00-{value:07d}"


def encode_roster(plan: str, scoring: str, slots: list[str] | tuple[str, ...],
                  player_ids: list[str] | tuple[str, ...],
                  league_size: int = DEFAULT_LEAGUE_SIZE) -> str:
    """Build the v3 ref the intake page puts on the checkout URL."""
    if plan not in _PLAN_TO_PREFIX:
        raise RefError(f"unknown plan {plan!r}")
    if scoring not in _SCORING_TO_CODE:
        raise RefError(f"unknown scoring {scoring!r}")
    if league_size not in _SIZE_TO_CODE:
        raise RefError(f"unsupported league size {league_size!r}")
    slot_codes = ""
    reverse = {v: k for k, v in SLOTS.items()}
    for slot in slots:
        if slot not in reverse:
            raise RefError(f"unknown slot {slot!r}")
        slot_codes += reverse[slot]
    if not slot_codes:
        raise RefError("a ref needs at least one starting slot")
    if not player_ids:
        raise RefError("a ref needs at least one player")
    if len(player_ids) > MAX_ROSTER:
        raise RefError(f"roster of {len(player_ids)} exceeds {MAX_ROSTER}")
    if len(set(player_ids)) != len(player_ids):
        # A duplicate would let one player fill two slots, which inflates a
        # lineup out of nothing. Rejected here AND on decode.
        raise RefError("the same player appears twice in this roster")
    if len(player_ids) < len(slot_codes):
        raise RefError(f"{len(slot_codes)} starting slots but only "
                       f"{len(player_ids)} players")
    blob = b"".join(_pack_one(pid).to_bytes(3, "big") for pid in player_ids)
    packed = base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")
    ref = (f"{_PLAN_TO_PREFIX[plan]}{ROSTER_MARKER_V3}-"
           f"{_SCORING_TO_CODE[scoring]}{_SIZE_TO_CODE[league_size]}{slot_codes}"
           f"-{packed}")
    if not STRIPE_REF_RE.match(ref):
        raise RefError(f"encoded ref is not Stripe-safe: {ref!r}")
    return ref


def is_roster_ref(ref: str) -> bool:
    """v1 and the roster refs are told apart on the marker, never on shape."""
    return bool(isinstance(ref, str) and re.match(r"^[a-z][23]-", ref))


def decode_roster(ref: str) -> RosterRef:
    """Turn a v2 client_reference_id back into a league setup.

    Every failure raises. A ref is a string a browser put in a URL, so a
    partially-readable one is a payment that needs a human — never a reason to
    guess, because a guessed roster is a confident report about players the
    subscriber does not own.
    """
    if not isinstance(ref, str) or not STRIPE_REF_RE.match(ref):
        raise RefError(f"not a Stripe-safe reference: {ref!r}")
    # maxsplit: the payload is base64url and legitimately contains "-".
    parts = ref.split("-", 2)
    if len(parts) != 3:
        raise RefError(f"expected 3 fields, got {len(parts)}: {ref!r}")
    head, settings, packed = parts
    if len(head) != 2 or head[1] not in (ROSTER_MARKER, ROSTER_MARKER_V3):
        raise RefError(f"not a roster reference: {ref!r}")
    version = head[1]
    if head[0] not in _PREFIX_TO_PLAN:
        raise RefError(f"unknown plan prefix {head[0]!r} in {ref!r}")
    if not settings:
        raise RefError(f"no scoring or slots in {ref!r}")
    scoring_code = settings[0]
    if scoring_code not in SCORING:
        raise RefError(f"unknown scoring code {scoring_code!r} in {ref!r}")
    if version == ROSTER_MARKER_V3:
        if len(settings) < 2 or settings[1] not in SIZES:
            raise RefError(f"unknown league-size code in {ref!r}")
        league_size, slot_codes = SIZES[settings[1]], settings[2:]
    else:
        # A v2 ref predates the size field. It decodes as 12 — the value the
        # engine used for every subscriber while the question was discarded —
        # so an old ref means exactly what it always meant.
        league_size, slot_codes = DEFAULT_LEAGUE_SIZE, settings[1:]
    if not slot_codes or any(c not in SLOTS for c in slot_codes):
        raise RefError(f"bad slot template in {ref!r}")
    try:
        blob = base64.urlsafe_b64decode(packed + "=" * (-len(packed) % 4))
    except (ValueError, TypeError) as exc:
        raise RefError(f"unreadable roster in {ref!r}") from exc
    if not blob or len(blob) % 3:
        raise RefError(f"roster is not a whole number of players in {ref!r}")
    count = len(blob) // 3
    if count > MAX_ROSTER:
        raise RefError(f"roster of {count} exceeds {MAX_ROSTER}")
    ids = tuple(_unpack_one(int.from_bytes(blob[i * 3:i * 3 + 3], "big"))
                for i in range(count))
    if len(set(ids)) != len(ids):
        raise RefError(f"the same player appears twice in {ref!r}")
    if count < len(slot_codes):
        raise RefError(f"{len(slot_codes)} starting slots but only {count} players")
    return RosterRef(
        plan=_PREFIX_TO_PLAN[head[0]],
        scoring=SCORING[scoring_code],
        slots=tuple(SLOTS[c] for c in slot_codes),
        player_ids=ids,
        league_size=league_size,
    )
