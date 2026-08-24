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
founding subscriber renews at the price they joined at (legal §3), which our
constants do not know.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date

from render.report import CANCEL_HEAD, esc
from render.welcome import UNSUB_LINE, _cancel_destination
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


@dataclass(frozen=True)
class Renewal:
    """One subscription about to renew, as Stripe reports it."""

    email: str
    amount: str                  # formatted, e.g. "$39.00 USD"
    renews_on: date
    interval: str                # "year" — monthly never reaches here
    customer_id: str | None = None

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
        "If you'd rather not renew, cancel it yourself in about fifteen "
        "seconds — "
        + (f'<a href="{esc(href)}" style="color:#B3402F">{esc(label)}</a>. '
           if href else "the steps are on our site's legal page. ")
        + "Cancel before that date and you are not charged."
    )
    cancel_text = (
        "If you'd rather not renew, cancel it yourself in about fifteen "
        "seconds — "
        + (f"{label}: {href}. " if href else
           "the steps are on our site's legal page. ")
        + "Cancel before that date and you are not charged.")

    lede = (f"Your subscription renews on {when}, and the card on file will be "
            f"charged {renewal.amount}. Nothing is due before then, and this "
            f"is the only notice we send about it.")
    what = ("Renewing keeps the Tuesday file coming for the season ahead — "
            "the lineup we'd set for your roster under your scoring, with "
            "every call graded in public afterwards.")

    html = (
        f'<div style="{_BODY}max-width:560px;margin:0 auto;padding:8px 4px;">'
        f'<p style="{_HEAD}margin-top:0;">Your renewal is coming up</p>'
        f'<p style="{_BODY}margin:0 0 10px;">{esc(lede)}</p>'
        f'<p style="{_BODY}margin:0 0 10px;">{esc(what)}</p>'
        f'<p style="{_HEAD}">{esc(CANCEL_HEAD)}</p>'
        f'<p style="{_BODY}margin:0 0 8px;">{cancel_line} {esc(UNSUB_LINE)}</p>'
        f'</div>'
    )
    text = "\n".join([
        "YOUR RENEWAL IS COMING UP",
        "",
        lede,
        what,
        "",
        CANCEL_HEAD.upper(),
        f"{cancel_text} {UNSUB_LINE}",
    ]) + "\n"

    return Message(to=renewal.email,
                   subject=f"Heads up: your subscription renews {when}",
                   html=html, text=text, key=renewal.key)
