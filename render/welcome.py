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

Prices are constants here and a test ties them to the live pages, because two
surfaces stating two prices is the drift this repo keeps finding.
"""

from __future__ import annotations

import os

from render.report import CANCEL_HEAD, cancel_destination, esc
from run.delivery import Message

# One test asserts these equal the landing page's own numbers.
SEASON_PRICE = "$39"
MONTHLY_PRICE = "$14.99"
PASS_PRICE = "$99"

_FONT = "font-family:Arial,Helvetica,sans-serif;"
_BODY = f"{_FONT}font-size:15px;line-height:1.6;color:#33445C;"
_HEAD = (f"{_FONT}font-weight:bold;font-size:17px;color:#16314A;"
         "margin:18px 0 4px;")

# The distinction every commercial email must carry (and the reports do).
UNSUB_LINE = ("Unsubscribing from emails alone does not stop a subscription — "
              "cancel from your billing page if you want the charges to end.")


# One route, defined in render/report.py so every surface agrees.
_cancel_destination = cancel_destination


def _plan_terms(plan: str) -> tuple[str, list[str]]:
    """(what you bought, the disclosures that purchase legally requires)."""
    if plan == "monthly":
        return (
            f"the monthly plan — {MONTHLY_PRICE} USD a month",
            [f"It bills {MONTHLY_PRICE} USD each month until you cancel, and "
             "billing stops on its own when the season ends — we don't charge "
             "through the offseason, because we aren't sending you anything.",
             "Refunds are no-questions through Week 2 — one per person, and a "
             "re-subscription after a refund is final."],
        )
    if plan == "league_pass":
        # The seat link ships HERE because the page cannot deliver it: the
        # browser renders it in the instant before navigating to Stripe, and
        # rendering it any earlier would leave a shareable claim link before any
        # payment exists. The welcome only sends after the payment, so this is
        # the first moment the link is safe to hand over.
        site = os.environ.get("SITE_URL", "").rstrip("/")
        seat_line = (
            f"Every manager who claims a seat gets their own report at no "
            f"charge to them. Send them this link — each enters their own "
            f"roster: {site}/join/?pass=1 — and tell them the email you paid "
            f"with, which is how their seat is matched to your pass."
            if site else
            "Every manager who claims a seat gets their own report at no "
            "charge to them; share your league's signup link whenever you're "
            "ready.")
        return (
            f"the League Pass — {PASS_PRICE} USD for your whole league's season",
            [f"It renews once a year at {PASS_PRICE} USD unless you cancel — "
             "charged before the season it covers, never during the offseason. "
             "We email you before it bills.",
             "Refunds are no-questions through Week 2 — one per league.",
             seat_line],
        )
    if plan == "seat":
        return (
            "a seat on your league's League Pass",
            ["Nothing bills you for this seat, ever — your commissioner's pass "
             "covers it. If the pass lapses, your reports stop; they never "
             "quietly convert into a charge."],
        )
    return (
        f"the season pass — {SEASON_PRICE} USD for the season",
        [f"It renews once a year at {SEASON_PRICE} USD unless you cancel — "
         "charged next August, before the season it covers, never during the "
         "offseason. We email you before it bills.",
         "Refunds are no-questions through Week 2 — one per person, and a "
         "re-subscription after a refund is final."],
    )


def welcome_message(email: str, plan: str, slug: str, season: str,
                    purchased_at: str = "") -> Message:
    """Build the acknowledgment. ``plan`` is season|monthly|league_pass|seat."""
    bought, terms = _plan_terms(plan)
    href, label = _cancel_destination()
    cancel_line = (
        "Cancel any time, yourself, in about fifteen seconds — "
        + (f'<a href="{esc(href)}" style="color:#B3402F">{esc(label)}</a>.'
           if href else "the steps are on our site's legal page.")
    )
    cancel_text = ("Cancel any time, yourself, in about fifteen seconds — "
                   + (f"{label}: {href}" if href else
                      "the steps are on our site's legal page."))

    what_next = ("Every Tuesday morning, one email: the lineup we'd set for "
                 "your roster under your scoring, the odds on every call worth "
                 "making, and last week's calls graded against the real box "
                 "score. Reading it takes about ninety seconds.")
    roster_line = ("Trades and pickups happen — reply to any report with your "
                   "updated roster and your file follows it from the next "
                   "Tuesday.")

    html = (
        f'<div style="{_BODY}max-width:560px;margin:0 auto;padding:8px 4px;">'
        f'<p style="{_HEAD}margin-top:0;">You&#x27;re in.</p>'
        f'<p style="{_BODY}margin:0 0 10px;">You bought {esc(bought)}. '
        f'{esc(what_next)}</p>'
        f'<p style="{_HEAD}">The terms, in writing</p>'
        + "".join(f'<p style="{_BODY}margin:0 0 8px;">{esc(term)}</p>'
                  for term in terms)
        + f'<p style="{_HEAD}">{esc(CANCEL_HEAD)}</p>'
        f'<p style="{_BODY}margin:0 0 8px;">{cancel_line} {esc(UNSUB_LINE)}</p>'
        f'<p style="{_BODY}margin:14px 0 0;color:#5A6B80;font-size:13px;">'
        f'{esc(roster_line)}</p>'
        f'</div>'
    )
    text = "\n".join([
        "YOU'RE IN.",
        "",
        f"You bought {bought}.",
        what_next,
        "",
        "THE TERMS, IN WRITING",
        *terms,
        "",
        CANCEL_HEAD.upper(),
        f"{cancel_text} {UNSUB_LINE}",
        "",
        roster_line,
    ]) + "\n"

    subject = ("Your seat is in — first file lands Tuesday morning"
               if plan == "seat" else
               "You're in — first file lands Tuesday morning")
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
    return Message(to=email, subject=subject, html=html, text=text,
                   key=f"welcome-{purchased_at or season}-{slug}")
