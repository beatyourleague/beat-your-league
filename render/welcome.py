"""The welcome email — the acknowledgment a subscription legally owes its buyer.

California's auto-renewal law (and ROSCA's practice) requires a post-purchase
acknowledgment the customer can retain, carrying the auto-renewal terms and how
to cancel. Stripe's receipt states the charge but not our cancellation method,
so this email is where the obligation is met — and it doubles as the honest
"here is what happens next" a first Tuesday deserves.

Everything here is plan-aware because the renewal terms differ by what was
bought: a $39 season pass renews yearly, a $14.99 monthly bills until the season
ends, a $99 League Pass renews yearly and covers seats, and a SEAT bills nobody
at all. Sending a seat holder renewal terms for money they never spent would be
its own small dishonesty.

It is also the first thing a buyer reads after paying, when they are most
anxious about it, and it used to be Arial paragraphs with no masthead, no
preview line and nothing that looked like the product they bought (panel
review I6). It wears the weekly email's navy masthead now, names the plan and
the purchase date, and links the terms they agreed to (launch audit L5).

Prices are constants here and a test ties them to the live pages, because two
surfaces stating two prices is the drift this repo keeps finding.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from render.email import (BASE, CARD, DISPLAY, FLAG, FLAG_TINT, FONT, LINE, NAVY,
                          PAPER, SLATE, SMALL)
from render.report import (CANCEL_HEAD, CANCEL_PERIOD, EMAIL_META, ONCE_STOP_BODY, SEAT_STOP_BODY,
                           TWO_PURCHASES, cancel_destination, esc, preheader_html,
                           reply_update_works, seat_stop_href)
from render.sender import CONTACT, sender_line
from run.delivery import Message

# One test asserts these equal the landing page's own numbers.
# 2026 prices (owner decision, Oct 31 2026): monthly plans that stop on their
# own. The one-time passes are retired; PLAYOFF_PRICE words a purchase that was
# never made. SEASON_PRICE is the working plan for 2027's full-season pass, one
# price for everyone, and no page promises it (owner decision, Oct 31 2026).
SEASON_PRICE = "$39"
PLAYOFF_PRICE = "$19"
MONTHLY_PRICE = "$14.99"
PASS_PRICE = "$34.99"
# The 2027 Season Pass (owner decision, Oct 30 2026): off until the lawyer has
# seen it, and a test ties these to run/checkout's two cents figures. It renews
# at the season pass's price.
SEASON_2027_PRICE = "$49"
SEASON_2027_RENEWAL = "$39"
# The terms a buyer ticks at checkout. Equal to the "Last updated" date on
# site/terms.html (tested), and stamped on every Customer with their consent
# (run/intake._consent) so a renewal can always be tied to the words agreed to.
TERMS_VERSION = "2026-10-31"

# The distinction every commercial email must carry (and the reports do).
UNSUB_LINE = ("Unsubscribing from emails alone does not stop a subscription — "
              "cancel from your billing page if you want the charges to end.")


# One route, defined in render/report.py so every surface agrees.
_cancel_destination = cancel_destination
# With no site address configured the email still names the page, so the
# route is one a reader can type (EMAILS-102).
TERMS_STEPS = "beatyourleague.com/terms.html#cancel"


# The refund window is PURCHASE-relative, never a calendar week: "through
# Week 2" gave anyone who bought from Week 3 on no window at all, while every
# selling page kept promising one. The terms page defines a weekly report; this
# is the retainable copy of the same promise, so it states when it closes —
# at kickoff, before the first report's lineup can be played and then returned
# (owner decision, Oct 30 2026; it used to be the second report's kickoff, which
# left the first report's whole week to watch before asking). Terms §5's two
# later closes ride along (EMAILS-95/96): our own late send never shuts the
# window before the report arrives, and a season that ends with no weekly report
# delivered still has an end date in the copy the buyer keeps.
_REFUND_WINDOW = ("Refunds are no-questions until your first weekly report's "
                  "week kicks off (a roster report on the day you join isn't a "
                  "weekly report). If your first weekly report reaches you late, "
                  "the window closes a week after it arrives; if the season ends "
                  "before one reaches you, a week after the season's last game.")
# "A second purchase", never "a re-subscription" (contract C5, final review
# COPY-9): one rule for every plan, whichever a buyer holds.
REFUND_TERMS = (_REFUND_WINDOW + " One per person, and a second purchase after "
                "a refund is final.")
REFUND_TERMS_LEAGUE = _REFUND_WINDOW + " One per league."

# The plan words this module takes. The welcome has its own vocabulary, older
# than the registry's: "league_pass" here is the PAYER (on a registry row it
# is a seat — render/report.SEAT_PLAN), and "pass" is accepted as the same
# payer, the registry's word for it since Oct 2026.
PAYER_PLANS = ("league_pass", "pass")

# What a League Pass payer sends their league. Paste-ready, because the
# commissioner's one job after paying is getting eleven people to claim a seat
# (panel review LP-I6): it used to be the third paragraph of the terms, as
# untappable text. {link} is the league's own seat link (run/intake signs it,
# C4) — with it nobody types anybody's address.
SHARE_MESSAGE = ("I got us the League Pass from Beat Your League: everyone gets "
                 "their own lineup report every Tuesday, built from their own "
                 "roster. Nothing to pay. Claim your seat here: {link}")
# Seats ride the pass: what the payer ends, every seat loses (LP-I6).
SEATS_END = ("Your league's seats last as long as your pass does: if you cancel "
             "it, a payment fails or you take a refund, every seat's reports stop "
             "too.")


# The 2026 rest-of-season passes (owner decision, Oct 18 2026) are ONE
# payment, no renewal: the disclosures are that nothing renews and the refund
# window, and the way out is a stop request (render.report.ONCE_STOP_BODY).
ONCE_LINE = ("It's one payment: nothing renews, and nothing more is ever "
             "charged for it.")
ONCE_TWICE = ("This address already bought a pass for this same roster, so you "
              "get one report a week, not two. Both were one payment and nothing "
              "more is charged; to be refunded for one, reply while its refund "
              "window is open.")
SEATS_END_ONCE = ("Your league's seats last through this season with your pass; "
                  "if you take a refund, every seat's reports stop too.")
# A pass buyer can reset every seat (run/seat_resets.py) and the released
# holders are deliberately not told, so a squatter learns nothing — which left
# a legitimate seat holder able to go quiet mid-season with nothing they had
# read saying it could happen (final review COPY-7). Said once, up front.
SEAT_RESET_NOTE = ("If whoever paid for your league's pass resets its seats, "
                   "yours is released; claim it again with the new link they "
                   "share.")


# What stops a monthly plan, and why it isn't a surprise (run/billing,
# LAST_CHARGE_WEEK). "Won't renew", never "nothing is charged": a buyer after
# that report still pays once, at purchase.
BILLING_STOPS = ("billing stops on its own: it won't renew after Week 16's report "
                 "goes out, and your reports still run through the season's last "
                 "week.")


def first_renewal_words() -> str:
    """The 2027 Season Pass's first renewal, as a buyer reads it: the date
    run/billing.py writes to Stripe, on the buyer's clock, from the one
    constant. ('August 15, 2028'.)"""
    from zoneinfo import ZoneInfo

    from run.checkout import SEASON_2027_FIRST_RENEWAL
    day = SEASON_2027_FIRST_RENEWAL.astimezone(ZoneInfo("America/New_York"))
    return f"{day:%B} {day.day}, {day.year}"


# The two sentences a purchase of one roster owes when a 2027 Season Pass is in
# the pair (LP2-D1). The stock lines are both false here: "both were one
# payment" of a pass that renews, "it keeps billing" of one that never bills.
SEASON_2027_TWICE = ("This address already holds a pass for this same roster, so "
                     "you get one report a week, not two. Your 2027 Season Pass "
                     "covers everything the older pass does. If the older one was "
                     "a one-time pass, it was one payment and nothing more is "
                     "charged for it: to be refunded for it, reply while its "
                     "refund window is open. If it renews, it keeps doing so until "
                     "you cancel it: your billing page shows only your newest "
                     "purchase, so reply to this email and we'll do it for you.")
ONCE_BESIDE_2027 = ("This address also holds a 2027 Season Pass for this same "
                    "roster, so you get one report a week, not two. This purchase "
                    "was one payment and nothing more is charged for it; to be "
                    "refunded for it, reply while its refund window is open. Your "
                    "2027 Season Pass keeps its own terms: it still covers 2027 and "
                    "still renews as your welcome for it says, until you cancel it.")


def _season_2027_terms() -> tuple[str, list[str]]:
    """(what you bought, its disclosures): the retainable notice California's
    ARL requires for this purchase. Everything it states comes from the
    constants the charge and the renewal are made from."""
    price, when = SEASON_2027_PRICE, first_renewal_words()
    return (f"the 2027 Season Pass — {price} USD for the rest of the 2026 season "
            "and all of the 2027 season",
            [f"You paid {price} USD today. That covers every weekly report for the "
             "rest of the 2026 season and all of the 2027 season, and nothing more "
             f"is charged before {when}.",
             f"It renews at {SEASON_2027_RENEWAL} USD on {when}, before the 2028 season, and each "
             "August after that, until you cancel. We email you 15 to 45 days before "
             "each renewal, with the date and the amount.",
             "Cancelling takes about a minute from the link at the bottom of any "
             "report. It stops the renewal and doesn't end the pass early: your "
             "reports continue through the 2027 season, then stop.",
             f"Your billing page may call the time until {when} a trial, because "
             "that is how Stripe holds the date. It isn't one: you've paid.",
             REFUND_TERMS])


def _plan_terms(plan: str, one_time: bool = False, playoff: bool = False,
                season_2027: bool = False) -> tuple[str, list[str]]:
    """(what you bought, the disclosures that purchase legally requires).

    ``playoff``: bought through the $19 Playoff Pass link (contract C4: the
    ``o:`` entry in STRIPE_PAYMENT_LINKS, a season row in the registry). The
    retainable copy must name the product the buyer paid for — "You bought
    the Rest-of-Season Pass" on a $19 purchase named one they did not (final
    review COPY-4). Always one payment, so it implies ``one_time``.

    ``season_2027``: bought through the ``y:`` link. A season row with a
    subscription, so without it the purchase falls through to the bottom of
    this function: "$29, renews on the anniversary", two false statements in
    the disclosure the law requires."""
    if season_2027 and plan not in ("monthly", "seat", *PAYER_PLANS):
        return _season_2027_terms()
    if one_time and plan in PAYER_PLANS:
        return ("the League Pass for the rest of this season — one payment for "
                "your whole league",
                [ONCE_LINE, REFUND_TERMS_LEAGUE, SEATS_END_ONCE])
    if playoff and plan not in ("monthly", "seat", *PAYER_PLANS):
        return (f"the Playoff Pass — {PLAYOFF_PRICE} USD, one payment for every "
                "weekly report from now through this season's last",
                [ONCE_LINE, REFUND_TERMS])
    if one_time and plan not in ("monthly", "seat"):
        return ("the Rest-of-Season Pass — every weekly report from now through "
                "this season's last, for one payment",
                [ONCE_LINE, REFUND_TERMS])
    if plan == "monthly":
        return (
            f"the monthly plan — {MONTHLY_PRICE} USD a month",
            [f"It bills {MONTHLY_PRICE} USD each month until you cancel, and "
             f"{BILLING_STOPS}",
             REFUND_TERMS],
        )
    if plan in PAYER_PLANS:
        return (
            f"the League Pass — {PASS_PRICE} USD a month for your whole league",
            [f"It bills {PASS_PRICE} USD each month until you cancel, and "
             f"{BILLING_STOPS}",
             REFUND_TERMS_LEAGUE,
             SEATS_END],
        )
    if plan == "seat":
        return (
            "a seat on your league's League Pass",
            # "Your league's pass", never "your commissioner's": any manager
            # may buy the pass (panel review LP-D7).
            ["Nothing bills you for this seat. Your league's pass covers it. "
             "If the pass lapses, your reports stop and nothing is charged.",
             SEAT_RESET_NOTE],
        )
    return (
        f"the season pass — {SEASON_PRICE} USD for the season",
        [f"It renews once a year at {SEASON_PRICE} USD unless you cancel, on "
         "the anniversary of the day you bought it. We email you before it "
         "bills.",
         REFUND_TERMS],
    )


def _site() -> str:
    return os.environ.get("SITE_URL", "").rstrip("/")


# What each plan is called in a sentence about it (LP2-D1).
_PLAN_NAME = {"season": "season pass", "monthly": "monthly plan",
              "league_pass": "League Pass", "pass": "League Pass",
              "season_2027": "2027 Season Pass"}
TWICE_HEAD = "One report for this roster"
TWICE_SUBJECT = "You're in. One report a week for this roster, not two"


def duplicate_line(plan: str, duplicate: str | None) -> str | None:
    """The sentence a purchase gets when this address ALSO bought another
    subscription for the same roster (LP2-D1), or None.

    A commissioner who had the $39 season pass and then bought the $99 League
    Pass for the same team was charged for both and got two identical reports
    every Tuesday, with nothing anywhere saying so. The intake now sends one
    report; this tells them, once, in the acknowledgment of the newer
    purchase, that the other subscription may still bill and that cancelling
    it is theirs to do from the billing page. It cancels nothing and promises
    no refund: both are the subscriber's call, under the terms they agreed to.

    The intake judges "the same roster" from the purchase LOG, which also
    holds a subscription cancelled or refunded long ago — so the older one is
    "if it is still active", never "it keeps billing", which would be a false
    statement about somebody's money whenever they had already cancelled it.
    Two League Passes are two leagues' seats and are never merged."""
    if not duplicate or (plan in PAYER_PLANS and duplicate in PAYER_PLANS):
        return None
    other = _PLAN_NAME.get(duplicate, "subscription")
    mine = _PLAN_NAME.get(plan, "subscription")
    if this_is_the_spare(plan, duplicate):
        # The pass already covers the buyer's own team: THIS purchase is the
        # spare, and it is certainly active — it was just bought. It is also
        # the NEWEST, so the billing page (which opens only the newest
        # purchase at an address, D3) is where it cancels.
        bills = (f"bills each month until you cancel it or the season's last "
                 f"weekly report goes out" if plan == "monthly" else
                 "bills on its own until you cancel it")
        return (f"Your League Pass already covers this same roster, so you get one "
                f"report a week, not two. This {mine} {bills}, which you can do "
                f"yourself on your billing page.")
    earlier = f"an earlier {other}" if duplicate == plan else f"the {other}"
    covered = (" Your League Pass covers your own team too, so you get one report "
               "a week, not two." if plan in PAYER_PLANS else
               " You get one report a week for it, not two.")
    bills = ("it bills each month until you cancel it or the season's last "
             "weekly report goes out" if duplicate == "monthly" else
             "it keeps billing until you cancel it")
    # The OLDER purchase sits on an older Stripe customer, which the billing
    # page — opened by email, newest customer only — can't show (D3).
    return (f"This address also bought {earlier} for this same roster.{covered} "
            f"If that one is still active, {bills}. Your billing page shows only "
            f"your newest purchase, so to cancel the older one, reply to this "
            f"email and we'll do it for you.")


def this_is_the_spare(plan: str, duplicate: str | None) -> bool:
    """A season or monthly purchase whose roster a League Pass already covers:
    the new purchase is the one to cancel, and it is on the billing page."""
    return plan not in PAYER_PLANS and duplicate in PAYER_PLANS


SEAT_LINK_PENDING = ("Every manager in your league gets their own report at no "
                     "charge to them. Your league's seat link isn't ready yet. "
                     "It goes on your weekly reports as soon as it is.")


def _share(plan: str, seat_link: str | None) -> tuple[str, str, str] | None:
    """(the lead-in, the link, the message to paste) a League Pass payer sends
    their league; None for anybody else.

    With the league's own seat link (C4) the message is complete — and it is
    the only way a seat is claimed (contract C3: the generic page that matched
    a seat by the payer's typed address is closed). Without it there is no
    link to give, and the email says something true instead of a dead href."""
    if plan not in PAYER_PLANS:
        return None
    if seat_link and seat_link.startswith("https://"):
        return ("Every manager in your league gets their own report at no charge "
                "to them. This link is your league's own, so they need only "
                "their roster:", seat_link, SHARE_MESSAGE.format(link=seat_link))
    # No signed link means no seat can be confirmed yet (the codes come from
    # the same secret), so the generic "?pass=1 plus my email" route printed
    # here never worked in the only state that printed it (EMAILS-106/107).
    # The intake goes red until it is fixed; this says only what is true.
    return (SEAT_LINK_PENDING, "", "")


def _purchase_date(purchased_at: str) -> str | None:
    """'October 15, 2026' from Stripe's `created` (epoch seconds, as the
    intake passes it) or an ISO stamp; None when there is no readable clock.
    On the buyer's clock, the one the site's times are printed in."""
    raw = str(purchased_at or "").strip()
    if not raw:
        return None
    try:
        stamp = (datetime.fromtimestamp(int(raw), timezone.utc) if raw.isdigit()
                 else datetime.fromisoformat(raw))
    except (ValueError, OverflowError, OSError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    from zoneinfo import ZoneInfo
    local = stamp.astimezone(ZoneInfo("America/New_York"))
    return f"{local:%B} {local.day}, {local.year}"


def _terms_date() -> str:
    day = datetime.fromisoformat(TERMS_VERSION)
    return f"{day:%B} {day.day}, {day.year}"


# What happens next, row by row — the thanks page's three rows (site/
# thanks.html), so the page and the email describe one sequence. A seat gets
# its first email the day its claim is CONFIRMED from its own inbox — the run
# that sends this welcome — by the same rules as a purchase (run/intake.py,
# LP-I4, OPS-R1), so a seat has a "today" too.
# "Week 2 or later" because run/intake._first_file sends a week's report only
# when ``data.week > 1``; without it a Week-1 buyer was promised this week's
# lineup and sent the roster report. The same condition league-pass.html and
# the join seat note state (COPY:F5).
NEXT_TODAY = ("Your first report. This week's lineup if it's Week 2 or later "
              "and the week's games haven't started, otherwise your roster "
              "report: the byes that leave you short and last season under "
              "your scoring.")
# The same row as one true sentence, once the schedule says which applies
# (review, Oct 30 2026: the conditional above read as small print to the one
# buyer it described). Decided on the RUN's clock — the clock run/intake.
# _first_file chooses the first report by, in the same run — and only from the
# cached schedule; NEXT_TODAY stays the fallback when it cannot be read, since
# it is true whichever report goes out.
NEXT_TODAY_WEEK = "Your first report: this week's lineup, decided."
NEXT_TODAY_ROSTER = ("Your first report: the byes ahead on your roster and last "
                     "season under your scoring.")
NEXT_TODAY_THEN = "{day}: your Week {week} report."
# Where the reports come from, so the first Tuesday one is not filtered. The
# address is LAUNCH.md's EMAIL_FROM, the one thanks.html names too.
SENDER_ADDRESS = "reports@beatyourleague.com"
CONTACTS_LINE = "Add {address} to your contacts so Tuesday's report lands in your inbox."
# "The odds on the close calls", never "every": a slot gets odds only when both
# players are confirmed to play, and a bye-heavy week can have few (PE-11).
# "About ninety seconds to read" was the game plan, not the report (a Week-6
# report is ~1,200 words), and Weeks 1-3 print no odds outside the measured
# setup (run/solo.seeded_scope) — EMAILS-90.
NEXT_TUESDAY = ("The week's report: the lineup we'd set for your roster under "
                "your scoring, with odds on the close calls from Week 4 (Week 2 "
                "for a 12-team PPR standard lineup), and any bye ahead, "
                "playoff weeks included, that leaves a spot nobody on your "
                "roster can fill. Your lineup comes first, and setting it takes "
                "about a minute.")
# From Week 4 on, odds already print in every setup, so "odds ... from Week 4"
# told a Week-8 buyer about a start that is behind them (final review,
# business #6). The pre-Week-4 promise above stays exactly as it was.
NEXT_TUESDAY_LIVE = ("The week's report: the lineup we'd set for your roster "
                     "under your scoring, with odds on the close calls, and any "
                     "bye ahead, playoff weeks included, that leaves a "
                     "spot nobody on your roster can fill. Your lineup comes "
                     "first, and setting it takes about a minute.")
ODDS_EVERYWHERE_FROM = 4
NEXT_SATURDAY = ("If Friday's injury report changes your lineup, the Saturday "
                 "check tells you the swap. No news, no email.")


# Between the season's last game and next season's schedule the intake has no
# week to build (run.solo.SeasonOver), so nothing goes out "today": the first
# email is the roster report, once the schedule exists (EMAILS-80/81/89).
NEXT_SCHEDULE_WHEN = "When next season's schedule is out"
NEXT_SCHEDULE = ("Your first report: the byes that leave you short and last "
                 "season under your scoring.")
SEASON_OVER_SUBJECT = ("You're in. Your first report comes when next season's "
                       "schedule is out")
SEAT_SEASON_OVER_SUBJECT = ("Your seat is in. Your first report comes when next "
                            "season's schedule is out")


def _schedule_kickoff(season: str, week: int) -> datetime | None:
    """The week's first kickoff (UTC) from the CACHED schedule only — a
    welcome makes no network call (week_at's rule) — or None."""
    from zoneinfo import ZoneInfo

    from run.solo import CACHE_DIR, _schedule
    eastern = ZoneInfo("America/New_York")
    first = None
    for row in _schedule(CACHE_DIR, live=False):
        if str(row.get("season") or "") != str(season):
            continue
        try:
            if int(row.get("week") or 0) != int(week):
                continue
            local = datetime.strptime(
                f"{(row.get('gameday') or '').strip()} "
                f"{(row.get('gametime') or '').strip() or '13:00'}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        start = local.replace(tzinfo=eastern).astimezone(timezone.utc)
        first = start if first is None or start < first else first
    return first


def today_text(season: str, now: datetime | None = None) -> str:
    """The "Today" row as one true sentence, chosen the way run/intake.
    _first_file chooses the first report: this week's report from Week 2 on,
    before the week's first kickoff; otherwise the roster report, and the day
    the next weekly report lands. NEXT_TODAY when the schedule can't say."""
    now = now or datetime.now(timezone.utc)
    try:
        from run.solo import CACHE_DIR, current_week, next_report_day
        if not (CACHE_DIR / "games.csv").is_file():
            return NEXT_TODAY
        week = current_week(CACHE_DIR, str(season), now.date(), live=False)
        kickoff = _schedule_kickoff(str(season), week)
        if kickoff is None:
            return NEXT_TODAY
        if week > 1 and now < kickoff:
            return NEXT_TODAY_WEEK
        if week == 1:
            # The Week 1 report goes out on the Tuesday run before its games
            # (run.solo.week_one_due); which Tuesday a buyer lands on is not
            # this email's to promise, so the next row says "Every Tuesday".
            return NEXT_TODAY_ROSTER
        day = next_report_day(CACHE_DIR, str(season), week, live=False)
        from run.solo import last_week
        last = last_week(CACHE_DIR, str(season), live=False)
        if not day or (last is not None and week >= last):
            return NEXT_TODAY_ROSTER
        lands = datetime.fromisoformat(day)
        when = f"{lands:%A}, {lands:%b} {lands.day}"
        return f"{NEXT_TODAY_ROSTER} {NEXT_TODAY_THEN.format(day=when, week=week + 1)}"
    except Exception:               # no cache, no schedule, a bad clock
        return NEXT_TODAY


def contacts_line() -> str:
    """CONTACTS_LINE with the address reports are sent from: EMAIL_FROM's
    when it names a real one, else LAUNCH.md's."""
    raw = os.environ.get("EMAIL_FROM", "")
    address = raw.rsplit("<", 1)[-1].rstrip("> ").strip() if raw else ""
    if "@" not in address or address.endswith(".invalid"):
        address = SENDER_ADDRESS
    return CONTACTS_LINE.format(address=address)


def _next_rows(seat: bool, carries_on: bool = False,
               season_over: bool = False,
               week: int | None = None,
               today: str = NEXT_TODAY) -> list[tuple[str, str]]:
    """``carries_on``: a second purchase of a roster this address already
    gets reports for (LP2-D1). Its reports simply continue, so "Today: your
    first report" would promise something the intake does not send.
    ``season_over``: the offseason, when the first report waits for the
    next schedule."""
    today = ([] if carries_on else
             [(NEXT_SCHEDULE_WHEN, NEXT_SCHEDULE)] if season_over else
             [("Today", today)])
    tuesday = (NEXT_TUESDAY_LIVE if week is not None and not season_over
               and week >= ODDS_EVERYWHERE_FROM else NEXT_TUESDAY)
    return [*today, ("Every Tuesday", tuesday),
            ("Saturday, if needed", NEXT_SATURDAY)]


def week_at(season: str, purchased_at: str) -> int | None:
    """The week the purchase fell in, from the cached schedule — the week its
    first weekly report is about — or None when that can't be read (then the
    pre-Week-4 wording stands, which is never false: odds do start by Week 4).
    Derived from the PURCHASE clock, never today's, so a retried send says
    what was true when they paid."""
    raw = str(purchased_at or "").strip()
    if not raw:
        return None
    try:
        stamp = (datetime.fromtimestamp(int(raw), timezone.utc) if raw.isdigit()
                 else datetime.fromisoformat(raw))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        from run.solo import CACHE_DIR, current_week
        # The cached schedule only: with no cached copy, fetch(live=False)
        # would download it, a hidden network call per welcome (final review).
        if not (CACHE_DIR / "games.csv").is_file():
            return None
        return current_week(CACHE_DIR, str(season), stamp.date(), live=False)
    except Exception:               # no cache, no schedule, a bad clock
        return None


# A seat link is one long unbroken string; unwrapped, it pushed the email
# 17px past a 390px phone (Oct 2026).
_WRAP = "overflow-wrap:anywhere;word-break:break-word;"


def _masthead(subhead: str) -> str:
    """The weekly email's masthead (render.email.masthead_html), so the first
    email after paying opens the way every report does."""
    from render.email import masthead_html
    return masthead_html("", "You're in.",
                         f'<b style="color:#FFFFFF;">{esc(subhead)}</b>')


def _block(title: str, inner: str) -> str:
    """One titled block, as a card of the weekly email (render.email._card)."""
    from render.email import _card, _section_row
    return _section_row("welcome", _card(0, title, f'<div style="padding-top:10px;">'
                                                   f'{inner}</div>'))


def welcome_message(email: str, plan: str, slug: str, season: str,
                    purchased_at: str = "", seat_link: str | None = None,
                    duplicate: str | None = None,
                    season_over: bool = False, one_time: bool = False,
                    playoff: bool = False, week: int | None = None,
                    now: datetime | None = None,
                    season_2027: bool = False) -> Message:
    """Build the acknowledgment. ``plan`` is season|monthly|league_pass|seat
    (``pass`` is the League Pass payer too). ``seat_link`` is the payer's own
    league seat link (C4), or None to fall back to the generic seat page.
    ``duplicate`` is the plan of another subscription this address already
    holds for the same roster (``duplicate_line``). ``season_over``: sent in
    the offseason (run.solo.SeasonOver), when no first report goes out until
    next season's schedule exists. ``playoff``: bought through the Playoff
    Pass link (contract C4), so the email names the Playoff Pass and its price;
    it is one payment, so it implies ``one_time``. ``week``: the week the
    purchase fell in (``week_at`` reads it from the schedule when omitted),
    which decides whether "odds from Week 4" is still news. ``now``: the
    run's clock, which decides the "Today" row (``today_text``).
    ``season_2027``: bought through the 2027 Season Pass link, a subscription
    that renews each August, so the email states both seasons and the date."""
    if playoff and plan not in ("monthly", "seat", *PAYER_PLANS):
        one_time = True
    bought, terms = _plan_terms(plan, one_time, playoff, season_2027)
    if week is None and not season_over:
        week = week_at(season, purchased_at)
    today = NEXT_TODAY if season_over else today_text(season, now)
    contacts = contacts_line()
    # A seat CLAIMED a place on somebody else's pass and has no Stripe
    # subscription, so "you bought" and a billing-page cancel were both false
    # for it: the portal finds no customer at that address, which left a seat
    # with no way out at all (launch audit C4, Oct 15 2026). Its way out is a
    # stop request, backed by the suppression list (run/suppress.py).
    seat = plan == "seat"
    verb = "claimed" if seat else "bought"
    if seat:
        stop_html, stop_text = esc(SEAT_STOP_BODY), SEAT_STOP_BODY
    elif one_time:
        # Nothing to cancel: the pass ends with the season (ONCE_STOP_BODY).
        stop_html, stop_text = esc(ONCE_STOP_BODY), ONCE_STOP_BODY
    else:
        href, label = _cancel_destination()
        cancel_line = (
            "Cancel any time, yourself, in about a minute — "
            + (f'<a href="{esc(href)}" style="color:#B3402F">{esc(label)}</a>.'
               if href else f"the steps are at {esc(TERMS_STEPS)}.")
        )
        cancel_text = ("Cancel any time, yourself, in about a minute — "
                       + (f"{label}: {href}" if href else
                          f"the steps are at {TERMS_STEPS}."))
        stop_html = (f"{cancel_line} {esc(UNSUB_LINE)} {esc(CANCEL_PERIOD)} "
                     f"{esc(TWO_PURCHASES)}")
        stop_text = f"{cancel_text} {UNSUB_LINE} {CANCEL_PERIOD} {TWO_PURCHASES}"

    when = None if seat else _purchase_date(purchased_at)
    opener = f"You {verb} {bought}." + (f" Purchased {when}." if when else "")
    roster_line = ("Roster changed? Reply to any report with your updated roster "
                   "and your report follows it from the next Tuesday."
                   if reply_update_works() else "")
    share = _share(plan, seat_link)
    site = _site()
    terms_url = f"{site}/terms.html" if site.startswith("https://") else ""
    # A seat ticked no box at checkout — it never saw one.
    terms_ref = (f"Our terms (last updated {_terms_date()})" if seat else
                 f"The terms you agreed to (last updated {_terms_date()})")
    sender = sender_line()
    # The preview line an inbox shows before the mail is opened: the plan,
    # and that the terms are inside — never the filler-less run into the body.
    preheader = (f"You {verb} {bought.split(' — ')[0]}. What happens next, and "
                 + ("how to stop it." if seat else "your terms in writing."))

    twice = None if seat else duplicate_line(plan, duplicate)
    if twice and one_time:
        # Both purchases were single payments: nothing keeps billing, so the
        # subscription wording (and its cancel link) would describe a charge
        # that never comes.
        twice = ONCE_BESIDE_2027 if duplicate == "season_2027" else ONCE_TWICE
    elif twice and season_2027:
        twice = SEASON_2027_TWICE

    # ---------------------------------------------------------------- html
    para = f'<p style="{BASE}font-size:15px;margin:0 0 10px 0;">'
    rows_html = "".join(
        f'<tr><td style="{SMALL}color:{NAVY};font-weight:bold;'
        f'text-transform:uppercase;letter-spacing:1px;padding:9px 12px 9px 0;'
        f'vertical-align:top;width:30%;border-top:1px solid {LINE};">'
        f'{esc(when_)}</td><td style="{BASE}padding:9px 0;'
        f'border-top:1px solid {LINE};">{esc(what)}</td></tr>'
        for when_, what in _next_rows(seat, carries_on=bool(twice),
                                      season_over=season_over, week=week,
                                      today=today))
    blocks = []
    twice_text = None
    if twice:
        # First, before anything else: it is about money being spent. The
        # route is its own sentence — a bare lowercase link label trailing
        # "your billing page." read as a fragment.
        href, label = _cancel_destination()
        if one_time or season_2027 or not this_is_the_spare(plan, duplicate):
            href = ""  # the older purchase cancels by reply (D3), not there
        link_html = (f' Where to cancel: <a href="{esc(href)}" style="color:{NAVY};">'
                     f'{esc(label)}</a>.' if href else "")
        twice_text = twice + (f" Where to cancel: {label}: {href}" if href else "")
        blocks.append(_block(TWICE_HEAD, f"{para}{esc(twice)}{link_html}</p>"))
    if share:
        lead, link, paste = share
        inner = para + esc(lead) + "</p>"
        if link and not link.startswith("https://"):
            # Every href in an email is https (tests/test_email_safety.py);
            # a link that is not one is still given, as text.
            inner += (f'<p style="{BASE}font-size:15px;margin:0 0 10px 0;{_WRAP}">'
                      f'{esc(link)}</p>')
        elif link:
            inner += (
                f'<table role="presentation" cellpadding="0" cellspacing="0" '
                f'border="0" style="margin:4px 0 12px 0;"><tr>'
                f'<td style="background:{FLAG};border-radius:8px;">'
                f'<a href="{esc(link)}" style="display:inline-block;padding:12px 20px;'
                f'font-family:{DISPLAY};font-size:15px;font-weight:bold;'
                f'letter-spacing:1.5px;text-transform:uppercase;color:{NAVY};'
                f'text-decoration:none;">Your league&#x27;s seat link</a></td></tr>'
                f'</table>'
                f'<p style="{SMALL}margin:0 0 6px 0;">Or paste this into your '
                f'league chat:</p>'
                f'<div style="{BASE}background:{FLAG_TINT};border:1px solid #EBDDAE;'
                f'border-radius:8px;padding:10px 12px;{_WRAP}">{esc(paste)}</div>')
        blocks.append(_block("Send your league this", inner))
    blocks.append(_block(
        "What happens next",
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0">{rows_html}</table>'
        f'<p style="{BASE}font-size:14px;color:{SLATE};margin:10px 0 0 0;">'
        f'{esc(contacts)}</p>'))
    terms_html = "".join(f'{para}{esc(term)}</p>' for term in terms)
    terms_html += (f'<p style="{SMALL}margin:4px 0 0 0;">{esc(terms_ref)}: '
                   + (f'<a href="{esc(terms_url)}" style="color:{NAVY};">'
                      f'{esc(terms_url)}</a>.' if terms_url else
                      "on our site's terms page.")
                   + '</p>')
    blocks.append(_block("The terms, in writing", terms_html))
    blocks.append(_block(CANCEL_HEAD, f'{para}{stop_html}</p>'))
    footer = (
        (f'<tr><td style="padding:12px 4px 0 4px;"><p style="{BASE}font-size:13px;'
         f'color:{SLATE};margin:0;">{esc(roster_line)}</p></td></tr>'
         if roster_line else "")
        + f'<tr><td style="padding:12px;"></td></tr>'
        f'<tr><td style="background:{PAPER};padding:20px 4px 8px 4px;">'
        f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — questions? '
        f'Write to {esc(CONTACT)}.'
        + (f'<br>{esc(sender)}' if sender else "")
        + '</p></td></tr>')
    html = (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{EMAIL_META}<title>Welcome to Beat Your League</title>\n</head>\n'
        f'<body style="margin:0;padding:0;background:{PAPER};">\n'
        f'{preheader_html(preheader)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:12px 8px 24px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:600px;width:100%;background:{PAPER};">'
        f'{_masthead(opener)}'
        + "".join(blocks) + footer
        + '</table></td></tr></table>\n</body>\n</html>\n'
    )

    # ---------------------------------------------------------------- text
    text_lines = ["BEAT YOUR LEAGUE", "YOU'RE IN.", "", opener]
    if twice_text:
        text_lines += ["", TWICE_HEAD.upper(), twice_text]
    if share:
        lead, link, paste = share
        text_lines += ["", "SEND YOUR LEAGUE THIS", lead]
        if link:
            text_lines += [link, "", "Or paste this into your league chat:", paste]
    text_lines += ["", "WHAT HAPPENS NEXT",
                   *[f"{when_}: {what}" for when_, what
                     in _next_rows(seat, carries_on=bool(twice),
                                   season_over=season_over, week=week,
                                   today=today)],
                   contacts,
                   "", "THE TERMS, IN WRITING", *terms,
                   f"{terms_ref}: " + (terms_url or "on our site's terms page."),
                   "", CANCEL_HEAD.upper(), stop_text,
                   *(["", roster_line] if roster_line else []),
                   "", f"Beat Your League — questions? Write to {CONTACT}.",
                   *([sender] if sender else [])]
    text = "\n".join(text_lines) + "\n"

    # A first report goes out the day they pay or claim (run/intake.py; a
    # seat since LP-I4), so both subjects say it is on its way — except a
    # second purchase of a roster already served, whose reports carry on.
    subject = ((SEAT_SEASON_OVER_SUBJECT if season_over else
                "Your seat is in. Your first report is on its way") if seat else
               TWICE_SUBJECT if twice else
               SEASON_OVER_SUBJECT if season_over else
               "You're in. Your first report is on its way")
    # Keyed on the PURCHASE, not the calendar. `season` moved every August,
    # so the key moved with it and `servable` — the projection of an
    # append-only signup log that is never pruned and never entitlement-checked
    # — re-welcomed every subscriber the product ever had, cancelled ones
    # included, with renewal terms about money they do not owe. This email is
    # the legally-owed ARL acknowledgment; sending it to somebody with no
    # subscription is a false statement about their money, which is the exact
    # thing it exists to get right. Found Aug 24 2026.
    #
    # `bought` is Stripe's own created timestamp, so a genuine re-subscription
    # next season is a new purchase with a new key and IS acknowledged. It
    # falls back to the season only when the timestamp is missing, which is the
    # old behaviour for the one case that has no purchase clock.
    #
    # A seat's List-Unsubscribe is its stop request; a paid welcome carries
    # none, as before — it is the acknowledgment the law owes the buyer.
    return Message(to=email, subject=subject, html=html, text=text,
                   key=f"welcome-{purchased_at or season}-{slug}",
                   unsubscribe=seat_stop_href() if seat else None)
