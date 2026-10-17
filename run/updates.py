"""Self-serve roster updates — the change a season forces every week.

A subscriber types a roster in late August; week-1 waivers run the
following Wednesday; by the SECOND report the file describes a team they no
longer own — recommending a dropped player, blind to the pickup — and it
compounds every week for the rest of the season. A stale-but-confident
report is worse than an honest thin one, and it lands inside the refund
window.

The mechanism reuses what the League Pass seats already proved: the picker
posts a small row to the form backend, and the intake validates it before a
single byte reaches the registry. Three rules, each bought with a failure
elsewhere in this repo:

- **The form is public, so an update must be AUTHENTICATED, not merely
  addressed.** A seat claim is honoured only when its payer bought a pass;
  an update is honoured only when it carries the subscriber's TOKEN — an
  HMAC of their address under a repo secret — which reaches them inside
  their own reports and nowhere else. Without it, anyone who knows a
  leaguemate's email could set their lineup for them.
- **An update names the row it replaces.** One customer can legitimately
  hold two rosters (two teams). ``replaces`` is the slug of the row being
  changed, so an update is never applied to the wrong team and never merges
  two subscriptions into one.
- **Order is stamped on receipt, never read from the row.** Public-form
  timestamps are attacker-supplied (the seat sweep learned this: a row dated
  9999 outranks every later one forever). An update is logged the first time
  the intake sees it, and the newest FIRST-SEEN row per target wins.

The registry row keeps its plan, its payer and its Stripe customer; only the
roster — both the encoded ref and the expanded copy, from one object — moves.
Nothing here touches the signup log, so the welcome email (keyed on the
ORIGINAL ref) is never sent twice.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from run.refs import RefError, decode_roster

UPDATE_LOG_NAME = "roster-updates.jsonl"
TOKEN_LENGTH = 20
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def update_token(email: str, secret: str) -> str:
    """The per-subscriber credential. Deterministic, so no state is kept and
    every report carries the same link; rotating the secret invalidates all."""
    if not secret:
        raise ValueError("an update token needs a secret")
    digest = hmac.new(secret.encode("utf-8"), email.strip().lower().encode("utf-8"),
                      hashlib.sha256).hexdigest()
    return digest[:TOKEN_LENGTH]


def slug_of(ref: str) -> str:
    """The same digest the registry and the send log use for a ref."""
    return hashlib.sha256(ref.encode("utf-8")).hexdigest()[:10]


# --------------------------------------------------------------------- #
# the per-pass seat link (LP-I1, contract C4, Oct 15 2026)
# --------------------------------------------------------------------- #
#
# Every League Pass used to share ONE link (join/?pass=1), and a seat was
# matched to its pass by the payer's address, typed by the leaguemate from a
# group-chat message. A typo, a swapped field or the wrong address (anyone in
# the league may buy the pass, not only the commissioner) dropped the seat
# with nothing said to anyone (LP-D1). The link now names the pass itself: a
# digest of the payer's address under UPDATE_SECRET, so it keeps the address
# out of the group chat, cannot be mistyped, and is recomputed at intake over
# the addresses that really bought a pass — never trusted from the row.

SEAT_TOKEN_LENGTH = 20
# The join page's scoring radio values. With the size and the lineup
# (template_code), a seat link carries the payer's own setup so eleven
# leaguemates do not each re-pick it (LP-I3) — still editable on the page.
_SCORING_PARAMS = ("ppr", "half_ppr", "standard")


def seat_token(payer_email: str, secret: str, pass_id: str = "") -> str:
    """hmac_sha256(UPDATE_SECRET, b"seat:" + canonical(payer) [+ b"|" + pass])
    as hex, first 20. Canonical as the free report canonicalises a mailbox
    (run/trials), so a payer's `+tag` or Gmail dots never make two passes out
    of one.

    ``pass_id`` binds the PASS as well as the payer (LP2-D4): hashing the
    address alone gave a buyer of two leagues' passes one token for both, so
    a leaguemate in both leagues lost a seat to a "roster change" and each
    pass counted the other league's seats. A pass with no identity (the
    generic fallback) keeps the address-only token."""
    if not secret:
        raise ValueError("a seat token needs a secret")
    from run.trials import canonical_email
    message = b"seat:" + canonical_email(payer_email).encode("utf-8")
    if pass_id:
        message += b"|" + pass_id.encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message,
                    hashlib.sha256).hexdigest()[:SEAT_TOKEN_LENGTH]


def signing_secrets(current: str, previous: str = "") -> list[str]:
    """The secret new links and codes are signed with, then any it replaced.

    UPDATE_SECRET signs seat links that live in a season of forwarded reports
    and in a welcome email nobody can recall. Rotating it re-read every
    stored claim made through an old link as "matches no League Pass", dropped
    every seat from the registry and exited 0 (reproduced, OPS-R10). So a
    rotation names the old value in UPDATE_SECRET_PREVIOUS (comma-separated)
    for as long as its links are out there: claims are MATCHED against every
    secret here, while everything new is signed with ``current`` alone.
    Confirmed seats never need a secret again — the intake keeps the pass
    they were confirmed on (run/intake.py's seat log)."""
    out = [current] if current else []
    out += [s.strip() for s in (previous or "").split(",")
            if s.strip() and s.strip() != current]
    return out


def template_code(slots: Iterable[str]) -> str | None:
    """The join page's radio value for a lineup shape, or None for a shape the
    page does not offer (the link then leaves the template for them to pick)."""
    from run.trial import TEMPLATES
    shape = tuple(slots)
    return next((code for code, slots_of in TEMPLATES.items()
                 if tuple(slots_of) == shape), None)


def seat_url(site_url: str, secret: str, payer_email: str, roster,
             pass_id: str = "") -> str | None:
    """The one link a pass payer shares: SITE_URL/join/?pass=<token>&s=&n=&t=
    with the payer's own scoring, league size and lineup. None without a site
    or a secret — then the welcome keeps the generic link and the email
    instruction, rather than printing a link that cannot be matched.
    ``pass_id`` is the pass's own identity (``seat_token``)."""
    site = (site_url or "").rstrip("/")
    if not site or not secret:
        return None
    params = [f"pass={seat_token(payer_email, secret, pass_id)}"]
    if roster.scoring in _SCORING_PARAMS:
        params.append(f"s={roster.scoring}")
    params.append(f"n={int(roster.league_size)}")
    code = template_code(roster.slots)
    if code:
        params.append(f"t={code}")
    return f"{site}/join/?" + "&".join(params)


def update_url(site_url: str, email: str, slug: str, secret: str) -> str | None:
    """Where a subscriber changes their roster — or None, so a report never
    carries a dead link. Gated on both the site and the secret existing.
    ``slug`` is the subscription's ORIGIN slug, which does not move when the
    roster does, so every report a subscriber ever receives carries the same
    link."""
    site = (site_url or "").rstrip("/")
    if not site or not secret:
        return None
    return f"{site}/join/?update={slug}&token={update_token(email, secret)}"


@dataclass
class RosterUpdate:
    """One validated change, as logged."""

    email: str
    replaces: str            # slug of the registry row being changed
    ref: str                 # the new roster
    seen_at: str             # first seen by the intake, ISO
    # What makes two updates to the SAME roster two updates. A confirmed
    # request carries its own code; a kind:"update" row (the operator's
    # `make roster-update`, or a legacy token update) carries the Worker's
    # stamp, as "rx:<received_at>". Two changes back to one roster (A -> B ->
    # A) are two updates; without a nonce the second collided with the first
    # in the log, was deduped away, and the roster silently stayed B — while
    # the intake printed "1 roster(s) changed" and the operator had been told
    # "their next report uses it" (OPS-R8, reproduced for operator rows after
    # it was fixed for confirmed ones).
    nonce: str = ""
    request_ts: str = ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.email.lower(), self.replaces, self.ref, self.nonce)


def load_update_log(path: Path) -> list[RosterUpdate]:
    if not Path(path).is_file():
        return []
    out: list[RosterUpdate] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict) and raw.get("email") and raw.get("ref"):
            fields = {f: raw[f] for f in RosterUpdate.__dataclass_fields__ if f in raw}
            out.append(RosterUpdate(**fields))
    return out


def _already_logged_bare(update: RosterUpdate,
                         bare: Mapping[tuple[str, str, str], list[str]]) -> bool:
    """Is this Worker-stamped update the same row as one logged before rows
    carried a nonce? The Worker keeps every row ~400 days and the intake
    re-reads them all every hour, so a row logged bare would otherwise be
    logged AGAIN under its new nonce — with a NEW first-seen stamp, making a
    months-old change the newest and undoing everything after it. It is the
    same row exactly when the bare entry was first seen at or after the
    Worker received this one; a later row with the same roster (A -> B -> A)
    was received after it and is a new update."""
    if not update.nonce.startswith("rx:"):
        return False
    received = _parse_ts(update.nonce[3:])
    if received is None:
        return False
    received = received if received.tzinfo else received.replace(tzinfo=timezone.utc)
    for seen in bare.get((update.email.lower(), update.replaces, update.ref), []):
        at = _parse_ts(seen)
        if at is not None and (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) >= received:
            return True
    return False


def append_update_log(updates: Iterable[RosterUpdate], path: Path) -> int:
    """Append the updates not already logged; a logged update keeps its
    first-seen stamp forever, which is what makes the sweep idempotent."""
    logged = load_update_log(path)
    known = {u.key for u in logged}
    bare: dict[tuple[str, str, str], list[str]] = {}
    for u in logged:
        if not u.nonce:
            bare.setdefault((u.email.lower(), u.replaces, u.ref), []).append(u.seen_at)
    fresh = [u for u in updates
             if u.key not in known and not _already_logged_bare(u, bare)]
    if not fresh:
        return 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as handle:
        for update in fresh:
            handle.write(json.dumps(asdict(update), separators=(",", ":")) + "\n")
    return len(fresh)


def validate_updates(rows: Iterable[Mapping], registry_rows: Iterable[Mapping],
                     known_ids: set[str] | None, secret: str,
                     now: str | None = None) -> tuple[list[RosterUpdate], list[str]]:
    """Turn form rows into validated updates against the rows about to be written.

    ``registry_rows`` are the rows the intake is about to write (payers and
    honoured seats): the only rosters an update may change. ``known_ids`` is
    None when the directory could not be loaded — "not checked", never
    "nothing is known".
    """
    problems: list[str] = []
    out: list[RosterUpdate] = []
    if not secret:
        rows = list(rows)
        if rows:
            problems.append(f"{len(rows)} roster update(s) arrived but UPDATE_SECRET "
                            f"is not set — none applied, because an update that "
                            f"cannot be authenticated is anyone's to forge")
        return out, problems
    targets: dict[tuple[str, str], Mapping] = {
        (str(row.get("email", "")).lower(),
         str(row.get("origin") or slug_of(str(row.get("ref", ""))))): row
        for row in registry_rows
    }
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen: set[tuple[str, str, str, str]] = set()
    # Oldest first by the Worker's stamp, so rows first seen in the same run
    # land in the log in the order they were sent, and the newest of them is
    # the one latest_per_target keeps (it breaks a first-seen tie by position).
    for row in sorted(rows, key=lambda r: str(r.get("received_at") or "")):
        email = str(row.get("email") or "").strip().lower()
        token = str(row.get("token") or "").strip()
        replaces = str(row.get("replaces") or "").strip()
        ref = str(row.get("ref") or "").strip()
        if not _EMAIL_RE.match(email):
            problems.append("a roster update arrived with an unusable address")
            continue
        # ASCII-only BEFORE compare_digest: it raises TypeError rather than
        # returning False when either str argument is non-ASCII, and this value
        # came straight off a public form backend with no character validation.
        # One anonymous row killed the whole intake — no registry written, no
        # welcomes sent, no watermark advanced — and repeated every run until
        # somebody deleted it by hand. The governing rule here is that one
        # person's problem must not become everybody's; an attacker's problem
        # certainly must not. Found Aug 24 2026.
        if not token.isascii() or not hmac.compare_digest(
                token, update_token(email, secret)):
            # Said without the address: the summary lands in a CI log.
            problems.append("a roster update carried a token that does not match "
                            "its address — not applied")
            continue
        try:
            roster = decode_roster(ref)
        except RefError as exc:
            problems.append(f"a roster update for {_mask(email)} carries an "
                            f"unreadable roster ({exc}) — not applied")
            continue
        if not replaces:
            # The OPERATOR's update (`make roster-update`, below): a subscriber
            # emailed a new roster, which is names and nothing else. Which of
            # their teams it changes is decided here, by overlap, and the new
            # ref keeps that team's own scoring, lineup and size — the person
            # typing it cannot know them, and guessing would quietly change
            # how every player is valued.
            target = _operator_target(email, roster.player_ids, targets.values())
            if target is None:
                problems.append(f"an operator roster update for {_mask(email)} "
                                f"matches none, or more than one, of their teams "
                                f"— not applied")
                continue
            replaces = str(target.get("origin") or slug_of(str(target.get("ref", ""))))
            try:
                ref, roster = _with_settings_of(target, roster.player_ids)
            except RefError as exc:
                problems.append(f"an operator roster update for {_mask(email)} "
                                f"does not fit that team's lineup ({exc}) — not "
                                f"applied")
                continue
        if (email, replaces) not in targets:
            problems.append(f"a roster update for {_mask(email)} names a subscription "
                            f"it does not hold — not applied")
            continue
        missing = ([pid for pid in roster.player_ids if pid not in known_ids]
                   if known_ids else [])
        if missing:
            problems.append(f"a roster update for {_mask(email)} names "
                            f"{len(missing)} player id(s) the directory does not "
                            f"have — not applied")
            continue
        received = str(row.get("received_at") or "").strip()
        nonce = f"rx:{received}" if received else ""
        key = (email, replaces, ref, nonce)
        if key in seen:
            continue
        seen.add(key)
        out.append(RosterUpdate(email=email, replaces=replaces, ref=ref,
                                seen_at=stamp, nonce=nonce))
    return out, problems


def _operator_target(email: str, player_ids: Iterable[str],
                     registry_rows: Iterable[Mapping]) -> Mapping | None:
    """The one subscription of ``email`` an emailed roster changes: the only
    one, or the one whose players it overlaps most. A tie is refused —
    changing the wrong team is worse than changing none, and the operator can
    ask which team they meant."""
    held = [row for row in registry_rows
            if str(row.get("email", "")).lower() == email]
    if len(held) <= 1:
        return held[0] if held else None
    new = set(player_ids)
    ranked = sorted(held, key=lambda r: -len(new & set(r.get("player_ids") or [])))
    first, second = (len(new & set(r.get("player_ids") or [])) for r in ranked[:2])
    return ranked[0] if first > second else None


def _with_settings_of(row: Mapping, player_ids: Iterable[str]):
    """A ref for ``player_ids`` under the row's own plan, scoring, lineup and
    league size. -> (ref, decoded). Raises RefError when the players cannot
    fill that lineup."""
    from run.refs import encode_roster
    held = decode_roster(str(row.get("ref", "")))
    ref = encode_roster(held.plan, held.scoring, held.slots, tuple(player_ids),
                        league_size=held.league_size)
    return ref, decode_roster(ref)


def latest_per_target(log: Iterable[RosterUpdate]) -> dict[tuple[str, str], RosterUpdate]:
    """Newest first-seen update per (email, replaces)."""
    latest: dict[tuple[str, str], RosterUpdate] = {}
    for update in log:
        target = (update.email.lower(), update.replaces)
        held = latest.get(target)
        if held is None or update.seen_at >= held.seen_at:
            latest[target] = update
    return latest


def apply_updates(rows: list[dict], latest: Mapping[tuple[str, str], RosterUpdate],
                  since: Mapping[tuple[str, str], datetime] | None = None,
                  ) -> tuple[list[dict], int]:
    """Replace the roster on the targeted rows. Both copies move from one
    decoded object, so the registry's agreement rule holds by construction.

    Every row is written with its ``origin`` — the slug it was first written
    under — and an update targets that slug, because that is the slug every
    report the subscriber has ever received carries. So a chain of changes
    (A -> B -> C) resolves to the newest one against a target that never
    moved.

    ``since`` (email, origin) -> when that row's roster was last SET some other
    way: a League Pass seat re-claimed through its seat link (LP-D4). An
    update first seen before that moment is older than the roster it would
    replace, and applying it would silently undo the newer claim.

    An applied update stamps ``roster_as_of`` with the day it was first seen
    (contract C3: the date the roster in use was set)."""
    out: list[dict] = []
    applied = 0
    for row in rows:
        email = str(row.get("email", "")).lower()
        origin = str(row.get("origin") or slug_of(str(row.get("ref", ""))))
        update = latest.get((email, origin))
        newer_claim = (since or {}).get((email, origin))
        seen = _parse_ts(update.seen_at) if update is not None else None
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        if (update is None or update.ref == row.get("ref")
                or (newer_claim is not None and seen is not None and seen < newer_claim)):
            out.append({**row, "origin": origin})
            continue
        roster = decode_roster(update.ref)
        out.append({
            **row,
            "origin": origin,
            "ref": update.ref,
            "player_ids": list(roster.player_ids),
            "slots": list(roster.slots),
            "scoring": roster.scoring,
            # From the new ref, like scoring: the update page asks for the
            # size, and keeping the old one would value every player in a
            # league the subscriber said they are no longer in.
            "league_size": roster.league_size,
            **({"roster_as_of": update.seen_at[:10]}
               if re.match(r"^\d{4}-\d{2}-\d{2}", update.seen_at or "") else {}),
        })
        applied += 1
    return out, applied


def _mask(email: str) -> str:
    return re.sub(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", r"***@\1", email)


# --------------------------------------------------------------------- #
# confirm-by-email requests (Sep 29 2026)
# --------------------------------------------------------------------- #
#
# The token link above was pulled out of every report (run/tuesday.py): a
# report is written to be forwarded to the league, and a forwarded credential
# hands the most motivated adversary in the product a way to set somebody's
# lineup. This replaces it with the pattern that survives forwarding:
#
#   1. Every report links a PUBLIC page (`join/?update=1`) that grants nothing.
#   2. The page posts {kind:"update_request", email, ref}. Anyone can do that;
#      the Worker stamps it (`received_at`, its own clock — the row cannot).
#   3. The intake mails a confirmation to the ADDRESS ON THE REGISTRY ROW —
#      never to anyone else — carrying a code only that inbox receives.
#   4. The subscriber opens `join/confirm.html?c=<code>` and PRESSES A BUTTON,
#      which posts {kind:"confirm", code}. A button, not a link that confirms
#      on load: mail security scanners open every link in an inbox.
#   5. The next intake sees the confirm, and the update is logged and applied.
#
# A forwarded report therefore grants nothing, a forged request reaches only
# the real subscriber's inbox, and ignoring it changes nothing.
#
# Rules bought by the adversarial review of Sep 29 2026 (each reproduced):
# - **Every request keeps its own code.** The newest request used to overwrite
#   the pending one, so a stranger's junk request killed the code already in the
#   subscriber's inbox. The code binds (address, subscription, roster) AND the
#   request's timestamp; all live requests stay valid until one is applied.
# - **A code is single-use and expires.** Once any request for a subscription is
#   applied, that request and every OLDER one is dead; a request is dead after
#   EXPIRY_DAYS. A stale or forwarded email can never re-apply an old roster.
# - **Requests are judged against the roster AS IT NOW STANDS**, compared by
#   content (players, slots, scoring, size — not the ref string, whose plan
#   prefix differs for a monthly subscriber). A request equal to the current
#   roster changes nothing and cancels every earlier pending request: it is how
#   a subscriber says "never mind, keep what I have".
# - **One confirmation email per request, ever** (not per day: a request row
#   never expires in the Worker, so a per-day key mailed the victim of one
#   forged request every day forever). The daily cap counts requests by the
#   Worker's own date.

CONFIRM_CODE_LENGTH = 24
# Confirmation emails per address per UTC day — a stranger posting requests
# in a loop can annoy an inbox a little, never flood it. Residual, stated: a
# stranger can spend the day's allowance, delaying the real subscriber's request
# to tomorrow (their earlier codes stay valid, and nothing else is harmed).
CONFIRMS_PER_DAY = 3
EXPIRY_DAYS = 7


@dataclass(frozen=True)
class PendingRequest:
    """A validated request waiting for its confirmation."""

    email: str
    replaces: str
    ref: str
    code: str
    ts: str = ""


def confirm_code(email: str, replaces: str, ref: str, secret: str, ts: str = "") -> str:
    if not secret:
        raise ValueError("a confirmation code needs a secret")
    message = f"confirm|{email.strip().lower()}|{replaces}|{ref}|{ts}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:CONFIRM_CODE_LENGTH]


def seat_code(email: str, pass_id: str, ref: str, ts: str, secret: str) -> str:
    """The code that turns one League Pass seat CLAIM into a seat (OPS-R1).

    The seat link rides on every pass report, and those reports are written to
    be forwarded, so holding the link proves nothing about who is claiming.
    Honouring a claim on sight let anyone with it enrol a stranger's address
    for weekly mail, or replace a seat holder's roster with nobody told — the
    "a leaguemate sets my lineup" attack the confirm-by-email update flow
    exists to stop. So a claim is mailed this code, at the claimed address
    only, and becomes a seat only when it comes back through the confirm
    page's button. It binds the address, the pass, the roster and the
    Worker's stamp on the claim, so every claim has its own and none can be
    replayed onto another. A different prefix from ``confirm_code`` keeps the
    two flows' codes apart over the one confirm page."""
    if not secret:
        raise ValueError("a seat confirmation code needs a secret")
    message = f"seat-confirm|{email.strip().lower()}|{pass_id}|{ref}|{ts}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:CONFIRM_CODE_LENGTH]


def seat_confirm_url(site_url: str, code: str) -> str | None:
    """The confirm page, told it is confirming a SEAT (``k=seat``) so it can
    say so; the POST it makes is the same {kind:"confirm", code}."""
    site = (site_url or "").rstrip("/")
    return f"{site}/join/confirm.html?c={code}&k=seat" if site else None


def same_roster(ref_a: str, ref_b: str) -> bool:
    """Do two refs describe the same roster? By CONTENT: a monthly subscriber
    re-submitting an identical roster builds a ref with a different plan prefix,
    which is not a change."""
    try:
        a, b = decode_roster(ref_a), decode_roster(ref_b)
    except RefError:
        return False
    return ((a.player_ids, a.slots, a.scoring, a.league_size)
            == (b.player_ids, b.slots, b.scoring, b.league_size))


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _target_for(email: str, roster, registry_rows: Iterable[Mapping]) -> str | None:
    """Which of this address's subscriptions a request changes, or None when
    that cannot be told. One subscription: that one. Several: the one in the
    same league setup whose roster overlaps the new one most — and a tie is
    refused, because changing the wrong team is worse than changing none."""
    held = [row for row in registry_rows
            if str(row.get("email", "")).lower() == email]
    if not held:
        return None
    if len(held) > 1:
        same = [row for row in held
                if list(row.get("slots") or []) == list(roster.slots)
                and row.get("scoring") == roster.scoring]
        new = set(roster.player_ids)
        ranked = sorted(same, key=lambda r: -len(new & set(r.get("player_ids") or [])))
        if not ranked or (len(ranked) > 1 and
                          len(new & set(ranked[0].get("player_ids") or []))
                          == len(new & set(ranked[1].get("player_ids") or []))):
            return None
        held = ranked[:1]
    row = held[0]
    return str(row.get("origin") or slug_of(str(row.get("ref", ""))))


def applied_request_ts(log: Iterable[RosterUpdate]) -> dict[tuple[str, str], str]:
    """Newest confirmed request already applied, per (address, subscription)."""
    out: dict[tuple[str, str], str] = {}
    for update in log:
        if update.request_ts:
            key = (update.email.lower(), update.replaces)
            out[key] = max(out.get(key, ""), update.request_ts)
    return out


def validate_requests(rows: Iterable[Mapping], registry_rows: Iterable[Mapping],
                      known_ids: set[str] | None, secret: str,
                      now: datetime | None = None,
                      applied: Mapping[tuple[str, str], str] | None = None,
                      ) -> tuple[list[PendingRequest], list[str]]:
    """Public-form requests -> requests worth a confirmation email.

    ``registry_rows`` must be the roster AS IT NOW STANDS (updates already
    applied): "nothing would change" is judged against that. Nothing here
    changes a roster. A request naming an address that holds no subscription is
    dropped in silence: the page is public, and answering it would let anybody
    learn who subscribes."""
    problems: list[str] = []
    rows = list(rows)
    if not secret:
        if rows:
            problems.append(f"{len(rows)} roster update request(s) arrived but "
                            f"UPDATE_SECRET is not set — no confirmations sent")
        return [], problems
    registry_rows = list(registry_rows)
    applied = dict(applied or {})
    now = now or datetime.now(timezone.utc)
    live: list[PendingRequest] = []
    cancelled: dict[tuple[str, str], str] = {}
    for row in sorted(rows, key=lambda r: str(r.get("received_at") or "")):
        email = str(row.get("email") or "").strip().lower()
        ref = str(row.get("ref") or "").strip()
        ts = str(row.get("received_at") or "")
        when = _parse_ts(ts)
        if not _EMAIL_RE.match(email) or when is None:
            continue                       # no Worker stamp: not a request we can identify
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if now - when > timedelta(days=EXPIRY_DAYS):
            continue
        try:
            roster = decode_roster(ref)
        except RefError:
            continue
        replaces = _target_for(email, roster, registry_rows)
        if replaces is None:
            if any(str(r.get("email", "")).lower() == email for r in registry_rows):
                problems.append(f"a roster update request for {_mask(email)} matches "
                                f"more than one of their teams equally — not sent")
            continue
        if known_ids and any(pid not in known_ids for pid in roster.player_ids):
            problems.append(f"a roster update request for {_mask(email)} names a "
                            f"player the directory does not have — not sent")
            continue
        current = next((r for r in registry_rows
                        if str(r.get("email", "")).lower() == email
                        and str(r.get("origin") or slug_of(str(r.get("ref", "")))) == replaces),
                       None)
        target = (email, replaces)
        if current is not None and same_roster(str(current.get("ref", "")), ref):
            # "Keep what I have": nothing to change, and every earlier pending
            # request for this subscription is withdrawn.
            cancelled[target] = max(cancelled.get(target, ""), ts)
            continue
        live.append(PendingRequest(email, replaces, ref,
                                   confirm_code(email, replaces, ref, secret, ts), ts))
    pending = [r for r in live
               if r.ts > applied.get((r.email, r.replaces), "")
               and r.ts > cancelled.get((r.email, r.replaces), "")]
    # The daily cap, by the Worker's own date, oldest first — deterministic.
    per_day: dict[tuple[str, str], int] = {}
    capped: list[PendingRequest] = []
    for request in sorted(pending, key=lambda r: r.ts):
        bucket = (request.email, request.ts[:10])
        per_day[bucket] = per_day.get(bucket, 0) + 1
        if per_day[bucket] <= CONFIRMS_PER_DAY:
            capped.append(request)
    return capped, problems


def confirmed_updates(pending: Iterable[PendingRequest],
                      confirm_rows: Iterable[Mapping], secret: str,
                      now: str | None = None) -> list[RosterUpdate]:
    """The pending requests whose code came back through the confirm page,
    oldest first (so that, if a subscriber pressed two buttons, the NEWEST
    request is the one that stands).

    The code is recomputed, never trusted: a confirm row is only a string, and
    it counts only when it equals the code of a request that is still live."""
    if not secret:
        return []
    codes = {str(r.get("code") or "").strip().lower() for r in confirm_rows}
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [RosterUpdate(email=p.email, replaces=p.replaces, ref=p.ref, seen_at=stamp,
                         nonce=p.code, request_ts=p.ts)
            for p in sorted(pending, key=lambda r: r.ts) if p.code in codes]


def confirmation_key(request: PendingRequest) -> str:
    """Send-log key: ONE confirmation per request, ever, and no address in it."""
    who = hashlib.sha256(request.email.encode("utf-8")).hexdigest()[:8]
    return f"confirm-{who}-{hashlib.sha256(request.code.encode('utf-8')).hexdigest()[:10]}"


def confirm_url(site_url: str, code: str) -> str | None:
    site = (site_url or "").rstrip("/")
    return f"{site}/join/confirm.html?c={code}" if site else None


def public_update_url(site_url: str, secret: str, endpoint: str) -> str | None:
    """The link every report carries. It grants nothing — which is why it may
    be forwarded — and it renders only when the whole flow can work: a site to
    land on, a backend to post to, a secret to sign confirmations with."""
    site = (site_url or "").rstrip("/")
    if not site or not secret or not endpoint:
        return None
    return f"{site}/join/?update=1"


# --------------------------------------------------------------------- #
# the operator's route: a roster change that arrived by email (G12, OPS-04)
# --------------------------------------------------------------------- #
#
# Every welcome, the thanks page and the landing FAQ say "reply with your
# updated roster and your report follows it", and nothing could apply that
# reply: the registry lives in the Actions cache, not on the owner's machine,
# and neither this module nor the intake had a command. This is the command.
# It does not write the registry — it cannot reach it — it posts the same
# authenticated kind:"update" row a self-serve update is, to the same form
# Worker, and the next hourly intake validates it on the same path (token,
# subscription held, every player in the directory) before a byte moves. The
# token is computed here from UPDATE_SECRET, which the owner holds; the
# subscriber's own email asking for the change is the authorisation.

def operator_row(email: str, player_ids: Iterable[str], secret: str) -> dict:
    """The form row for an emailed roster change. It names no subscription
    (``replaces``) and its ref's settings are placeholders: the intake picks
    the subscriber's team by overlap and keeps that team's scoring, lineup and
    size (``validate_updates``), because an emailed list of names says nothing
    about either."""
    from run.refs import encode_roster
    ids = tuple(player_ids)
    ref = encode_roster("season", "ppr", ("QB",), ids)
    address = email.strip().lower()
    return {"kind": "update", "email": address, "ref": ref,
            "token": update_token(address, secret)}


def post_row(endpoint: str, row: Mapping) -> None:
    """POST one row to the form Worker; raises RuntimeError on any refusal, so
    the operator is never told a change is on its way when it is not."""
    import urllib.error
    import urllib.request
    request = urllib.request.Request(
        endpoint, data=json.dumps(dict(row)).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"the form Worker refused the row (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"could not reach the form Worker: {exc}") from None
    if status >= 300:
        raise RuntimeError(f"the form Worker answered HTTP {status}")


def main(argv: list[str] | None = None) -> int:
    """`make roster-update EMAIL=... ROSTER=...`: queue an emailed roster
    change for the next intake. Prints no address."""
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(
        description="Apply a roster change a subscriber sent by email, through "
                    "the same validated path as a confirmed self-serve update.")
    parser.add_argument("--email", required=True,
                        help="the subscriber's address (the one on the subscription)")
    parser.add_argument("--roster", required=True,
                        help="a text file of the names they sent, or '-' for stdin")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve the names and show the change; post nothing")
    args = parser.parse_args(argv)

    secret = os.environ.get("UPDATE_SECRET", "")
    endpoint = os.environ.get("FORM_ENDPOINT", "")
    if not _EMAIL_RE.match(args.email.strip().lower()):
        print("That is not an address. Nothing was posted.", file=sys.stderr)
        return 1
    if not secret or not endpoint:
        # Said, never worked around: without the Worker and the secret there
        # is no authenticated path into the registry, and writing one by hand
        # is how a registry ends up unloadable for everybody.
        print("UPDATE_SECRET and FORM_ENDPOINT must both be set in this shell "
              "(the same values as the GitHub secrets). Nothing was posted.",
              file=sys.stderr)
        return 1

    from run.solo import CACHE_DIR, SoloError, load_week_data
    from run.trial import TrialError, resolve_roster
    text = (sys.stdin.read() if args.roster == "-"
            else Path(args.roster).read_text(encoding="utf-8"))
    try:
        data = load_week_data(CACHE_DIR)
        ids = resolve_roster(text, data.directory)
    except (SoloError, TrialError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not ids:
        print("No names in that roster. Nothing was posted.", file=sys.stderr)
        return 1
    row = operator_row(args.email, ids, secret)
    names = ", ".join(data.players.name(pid) for pid in ids)
    who = _mask(row["email"])
    if args.dry_run:
        print(f"Would queue a roster change for {who}: {len(ids)} players — {names}")
        return 0
    try:
        post_row(endpoint, row)
    except RuntimeError as exc:
        print(f"Not queued: {exc}", file=sys.stderr)
        return 1
    print(f"Queued a roster change for {who}: {len(ids)} players — {names}.\n"
          f"The next intake (within the hour) checks it against their "
          f"subscription and the player directory, keeps their team's scoring, "
          f"lineup and league size, and their next report uses it. If it is "
          f"refused, the intake's log says why.")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
