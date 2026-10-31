"""The pre-renewal reminder — the notice five surfaces already promise.

California's auto-renewal law requires, for any term of a year or longer, a
reminder **15 to 45 days before the renewal charge** stating that the
subscription renews, what it will cost, and how to cancel (Cal. B&P
§17602(b)). Independently of the statute, this site promises it in seven
places — the pricing card, the join page three times, the legal terms, the
League Pass page and the welcome email all say some form of "we email you
before it bills". A promise made at the point of sale and never kept is
deceptive from the moment of the first sale, which is why this exists before
the first renewal cycle rather than after it.

Two rules that decide who gets one, and they are the whole compliance
surface:

- **Only terms of a year or longer.** The monthly plan bills monthly and
  stops on its own at season's end; the statute does not reach it, and a
  "your subscription is about to renew" email to a monthly subscriber would
  describe a charge that is not coming in the form it describes.
- **Only subscriptions that will actually renew.** A subscription set to
  cancel at period end is ending, not renewing. Telling that person we are
  about to charge them £/$X is a false statement about their money — the
  worst possible one to send — so `cancel_at_period_end` is excluded, and
  the exclusion is tested.

The amount and the date come from Stripe, never from our own price
constants: the buyer is owed the figure that will actually be charged, and a
subscriber renews at the price on their own subscription, which our constants
do not know. A 2027 Season Pass is no exception: it is first charged
when its trial ends, in August 2028, and run/renewals.charge_date hands that
date to the same notice, so its 15-to-45-day window is counted from the charge.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone

from render.report import CANCEL_HEAD, EMAIL_META, TWO_PURCHASES, esc, preheader_html
from render.sender import CONTACT, sender_line
from render.welcome import PAYER_PLANS, TERMS_STEPS, UNSUB_LINE, _cancel_destination
from run.delivery import Message

_BODY = ("font-family:Arial,Helvetica,sans-serif;font-size:15px;"
         "line-height:1.55;color:#101E33;")
_HEAD = ("font-family:'Arial Narrow',Arial,sans-serif;font-weight:bold;"
         "font-size:17px;color:#101E33;margin:16px 0 6px;")

# The statutory window: no earlier than 45 days before the charge, no later
# than 15. Both ends matter — a reminder sent two months out is not the notice
# the law describes, and one sent a week out is late.
LEAD_MIN_DAYS = 15
LEAD_MAX_DAYS = 45


def renewal_day(period_end: int) -> date:
    """The renewal's date on the buyer's clock — America/New_York, the clock
    the welcome dates the purchase in. Stripe charges at the anniversary
    INSTANT, so a 9:30 PM ET purchase renews on the evening of the same ET
    date; the UTC date named the day after the charge, and "cancel before
    that date" then came too late (EMAILS-112-117)."""
    from zoneinfo import ZoneInfo
    stamp = datetime.fromtimestamp(int(period_end), timezone.utc)
    return stamp.astimezone(ZoneInfo("America/New_York")).date()


@dataclass(frozen=True)
class Renewal:
    """One subscription about to renew, as Stripe reports it."""

    email: str
    amount: str                  # formatted, e.g. "$39.00 USD"
    renews_on: date
    interval: str                # "year" — monthly never reaches here
    customer_id: str | None = None
    # What is renewing, when the sweep can tell: "season" (the $39 pass) or
    # "pass" (the League Pass payer). None names neither — "your
    # subscription" — rather than guess, the same rule as the amount.
    plan: str | None = None

    @property
    def product(self) -> str:
        """The plan by name (launch audit L5: the notice never said which
        product was renewing, and a League Pass payer renews a different
        thing — their whole league's seats ride on it)."""
        if self.plan in PAYER_PLANS:
            return "League Pass"
        if self.plan == "season":
            return "season pass"
        return "subscription"

    @property
    def slug(self) -> str:
        """Address-free identity for the send log, which is committed."""
        return hashlib.sha256(self.email.strip().lower().encode()).hexdigest()[:10]

    @property
    def key(self) -> str:
        """One reminder per subscriber per renewal DATE. Keyed on the date so
        next year's renewal gets its own notice rather than being suppressed
        as a duplicate of this one."""
        return f"renewal-{self.renews_on.isoformat()}-{self.slug}"


def due(renewal: Renewal, today: date) -> bool:
    """Is this inside the statutory window today?"""
    days = (renewal.renews_on - today).days
    return LEAD_MIN_DAYS <= days <= LEAD_MAX_DAYS


def renewal_message(renewal: Renewal) -> Message:
    """The reminder. Everything the statute names, in the buyer's words."""
    href, label = _cancel_destination()
    when = renewal.renews_on.strftime("%B %-d, %Y")
    cancel_line = (
        "If you'd rather not renew, cancel it yourself in about a minute — "
        + (f'<a href="{esc(href)}" style="color:#B3402F">{esc(label)}</a>. '
           if href else f"the steps are at {esc(TERMS_STEPS)}. ")
        + "Cancel before that date and you are not charged. "
        + esc(TWO_PURCHASES)
    )
    cancel_text = (
        "If you'd rather not renew, cancel it yourself in about a minute — "
        + (f"{label}: {href}. " if href else
           f"the steps are at {TERMS_STEPS}. ")
        + "Cancel before that date and you are not charged. " + TWO_PURCHASES)

    # The product, how often it renews and a contact: what Cal. B&P §17602
    # names besides the date and amount, and what the first version left out
    # (launch audit L5). The amount is still Stripe's, never our constant.
    lede = (f"Your Beat Your League {renewal.product} renews on {when}, and "
            f"the card on file will be charged {renewal.amount} — it renews once "
            f"a year until you cancel. Nothing is due before then, and this is "
            f"the only notice we send about it.")
    what = ("Renewing keeps the Tuesday report coming for the season ahead — "
            "the lineup we'd set for your roster under your scoring, with "
            "the odds on the close calls.")
    if renewal.plan in PAYER_PLANS:
        # The seats ride on this charge, and each is claimed again with the
        # new season's roster rather than carried over (panel review LP-D5).
        what = ("Renewing keeps the Tuesday report coming for the season ahead, "
                "for you and every manager in your league: each claims their "
                "seat again with their new roster. Cancel, and every seat's "
                "reports stop with yours.")
    contact = f"Questions? Write to {CONTACT}."
    # Who sent it (CAN-SPAM, CASL; launch audit L3, GATE-9): the notice about
    # somebody's money carried no sender block, while the weekly report did.
    sender = sender_line()

    # A whole document, like every other email here: it was a bare <div>, so
    # a phone laid it out at a desktop's 980px and shrank the type to fit
    # (measured at 390px, Oct 2026), and it declared no colour scheme.
    html = (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'{EMAIL_META}<title>Your Beat Your League renewal</title>\n</head>\n'
        f'<body style="margin:0;padding:0;">\n'
        f'{preheader_html(f"Your {renewal.product} renews {when}, at {renewal.amount}. How to cancel, if you want to, is inside.")}'
        f'<div style="{_BODY}max-width:560px;margin:0 auto;padding:16px 12px;">'
        f'<p style="{_HEAD}margin-top:0;">Your renewal is coming up</p>'
        f'<p style="{_BODY}margin:0 0 10px;">{esc(lede)}</p>'
        f'<p style="{_BODY}margin:0 0 10px;">{esc(what)}</p>'
        f'<p style="{_HEAD}">{esc(CANCEL_HEAD)}</p>'
        f'<p style="{_BODY}margin:0 0 8px;">{cancel_line} {esc(UNSUB_LINE)}</p>'
        f'<p style="{_BODY}margin:0 0 8px;">{esc(contact)}</p>'
        + (f'<p style="{_BODY}margin:14px 0 0;color:#5A6B80;font-size:12px;">'
           f'{esc(sender)}</p>' if sender else "")
        + '</div>\n</body>\n</html>\n'
    )
    text = "\n".join([
        "YOUR RENEWAL IS COMING UP",
        "",
        lede,
        what,
        "",
        CANCEL_HEAD.upper(),
        f"{cancel_text} {UNSUB_LINE}",
        "",
        contact,
        *([sender] if sender else []),
    ]) + "\n"

    return Message(to=renewal.email,
                   subject=f"Beat Your League: your {renewal.product} renews {when}",
                   html=html, text=text, key=renewal.key)
