"""What a membership covers, in one place.

A membership is priced by TEAMS, never by kind of league or by sport: redraft,
keeper and dynasty are settings on a team, and a second sport will be too. So
everything a future product needs to change lives here rather than in the
runners:

- ``TEAMS_INCLUDED``: how many teams one subscription carries (run/teams.py).
- ``SPORTS``: what a team can be, and the months each one delivers something.
- ``EXTRAS``: anything else a member receives in a month of its own, such as
  an off-season report. Empty today.
- ``YEAR_ROUND_BILLING``: whether plans keep renewing all year.

PLAN §4 bans billing a month with nothing in it, so year-round billing is a
switch with a condition: ``bills_all_year`` answers True only when every month
of the year delivers something. Until then run/billing.py stops every plan
after the season. Flipping the switch also needs new words: terms §3 and every
page that says a plan won't renew after Week 16's report.
"""

from __future__ import annotations

from dataclasses import dataclass

TEAMS_INCLUDED = 3

FOOTBALL = "football"


@dataclass(frozen=True)
class Sport:
    key: str
    name: str
    months: tuple[int, ...]     # calendar months a member receives reports


SPORTS: dict[str, Sport] = {
    # September's first report to Week 18's in January.
    FOOTBALL: Sport(FOOTBALL, "NFL", (9, 10, 11, 12, 1)),
}

# Month -> what a member receives in it that no sport covers.
EXTRAS: dict[int, str] = {}

YEAR_ROUND_BILLING = False


def months_covered() -> set[int]:
    """The calendar months with something in them for a member."""
    covered = {month for sport in SPORTS.values() for month in sport.months}
    return covered | set(EXTRAS)


def empty_months() -> list[int]:
    """The months a year-round charge would buy nothing. PLAN §4 forbids
    billing these."""
    return [month for month in range(1, 13) if month not in months_covered()]


def bills_all_year() -> bool:
    return YEAR_ROUND_BILLING and not empty_months()
