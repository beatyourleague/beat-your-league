"""Recent usage — what a player is actually being GIVEN, from the league's feed.

Points tell you what happened. Usage tells you whether it is likely to happen
again, and it is the vocabulary the fantasy market argues in: targets, snaps,
air yards, red-zone looks. The report used to say in print that we did not
track any of it.

Source is Sleeper's own ``/v1/stats/nfl/{type}/{season}/{week}`` — the same
public, no-auth family as the projections feed, keyed by Sleeper player id, so
it joins to everything else here with no id mapping and no new dependency.

TWO HONESTY RULES, measured rather than assumed (verified Aug 2026 against the
cached sample league, counting only rostered skill players who actually played
that week):

RULE U1 — usage is REPORTED, never projected. Everything here is a count of
something that already happened, so it carries no calibration burden and makes
no claim about next week. The moment a usage number is used to *predict*, it
needs its own backtest first (principle 1).

RULE U2 — snaps are live-only. ``off_snp`` covers 100% of 2024 players who
played and 0% of 2018's, so a snap figure can be shown in a live report but
can never be validated against the 2017-18 call set. Targets (81% / 66%) and
air yards (76% / 66%) are present in both eras; the shortfall in those is
overwhelmingly rushers and quarterbacks with no receiving line at all, which
is an honest zero rather than a hole. A field that is absent is reported as
absent — never silently as 0 (principle 3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class Usage:
    """One player's counted usage over a window of completed weeks."""

    weeks: int                    # weeks with a game on record in the window
    targets: int | None
    air_yards: float | None
    rz_targets: int | None
    snaps: int | None
    carries: int | None

    @property
    def has_anything(self) -> bool:
        return any(v is not None for v in
                   (self.targets, self.air_yards, self.rz_targets,
                    self.snaps, self.carries))

    def per_game(self, value: int | float | None) -> float | None:
        if value is None or self.weeks <= 0:
            return None
        return value / self.weeks


def load_week(raw_dir: Path, season: str, week: int) -> dict[str, Any] | None:
    """One cached stats file, or None if it was never fetched."""
    path = raw_dir / "stats" / f"nfl_regular_{season}_w{week:02d}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _num(record: Mapping[str, Any], key: str) -> float | None:
    value = record.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def recent_usage(raw_dir: Path, player_id: str, season: str,
                 before_week: int, window: int = 4) -> Usage:
    """Counted usage over the ``window`` completed weeks before ``before_week``.

    Strictly BEFORE the report week: a live report must never read the week it
    is about, the same rule the waiver market follows (RULE W2). Weeks with no
    cached file, and weeks the player did not play, simply do not contribute —
    they are not counted as zeros, which would understate a returning starter.
    """
    weeks = [w for w in range(max(1, before_week - window), before_week)]
    totals: dict[str, float] = {}
    present: set[str] = set()
    played = 0
    for week in weeks:
        data = load_week(raw_dir, season, week)
        if not data:
            continue
        record = data.get(player_id)
        if not isinstance(record, dict) or not record.get("gp"):
            continue
        played += 1
        for key in ("rec_tgt", "rec_air_yd", "rec_rz_tgt", "off_snp", "rush_att"):
            value = _num(record, key)
            if value is not None:
                totals[key] = totals.get(key, 0.0) + value
                present.add(key)

    def got(key: str) -> float | None:
        return totals.get(key) if key in present else None

    targets = got("rec_tgt")
    rz = got("rec_rz_tgt")
    snaps = got("off_snp")
    carries = got("rush_att")
    return Usage(
        weeks=played,
        targets=int(targets) if targets is not None else None,
        air_yards=got("rec_air_yd"),
        rz_targets=int(rz) if rz is not None else None,
        snaps=int(snaps) if snaps is not None else None,
        carries=int(carries) if carries is not None else None,
    )


def usage_line(usage: Usage) -> str | None:
    """The one-line read a buyer gets, or None when there is nothing to say.

    Counts with their window attached, because "18 targets" means nothing
    without knowing over how long. No verdict is attached: this states what
    the player was given, and the reader draws the conclusion.
    """
    if usage.weeks <= 0 or not usage.has_anything:
        return None
    span = f"last {usage.weeks} game{'s' if usage.weeks != 1 else ''}"
    bits: list[str] = []
    if usage.targets is not None:
        per = usage.per_game(usage.targets)
        bits.append(f"{usage.targets} target{'' if usage.targets == 1 else 's'}"
                    f" ({per:.1f} a game)")
    if usage.carries is not None:
        bits.append(f"{usage.carries} carr{'y' if usage.carries == 1 else 'ies'}")
    if usage.rz_targets:
        bits.append(f"{usage.rz_targets} inside the 20")
    if usage.snaps is not None:
        bits.append(f"{usage.snaps} snaps")
    if not bits:
        return None
    return f"{span}: " + ", ".join(bits)
