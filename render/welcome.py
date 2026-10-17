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
from render.report import (CANCEL_HEAD, CANCEL_PERIOD, EMAIL_META, SEAT_STOP_BODY,
                           cancel_destination, esc, preheader_html, seat_stop_href)
from render.sender import CONTACT, sender_line
from run.delivery import Message

# One test asserts these equal the landing page's own numbers.
SEASON_PRICE = "$39"
MONTHLY_PRICE = "$14.99"
PASS_PRICE = "$99"
# The terms a buyer ticks at checkout. Equal to the "Last updated" date on
# site/terms.html (tested), and stamped on every Customer with their consent
# (run/intake._consent) so a renewal can always be tied to the words agreed to.
TERMS_VERSION = "2026-10-15"

# The distinction every commercial email must carry (and the reports do).
UNSUB_LINE = ("Unsubscribing from emails alone does not stop a subscription — "
              "cancel from your billing page if you want the charges to end.")


# One route, defined in render/report.py so every surface agrees.
_cancel_destination = cancel_destination


# The refund window is PURCHASE-relative, never a calendar week: "through
# Week 2" gave anyone who bought from Week 3 on no window at all, while every
# selling page kept promising one. The terms page defines a weekly file; this
# is the retainable copy of the same promise, so it states when it closes —
# at kickoff, before the second file's lineup can be played and then returned.
REFUND_TERMS = ("Refunds are no-questions until your second weekly report's "
                "week kicks off — one per person, and a re-subscription after "
                "a refund is final.")
REFUND_TERMS_LEAGUE = ("Refunds are no-questions until your second weekly "
                       "report's week kicks off — one per league.")

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
             "it or take a refund, every seat's reports stop too.")


def _plan_terms(plan: str) -> tuple[str, list[str]]:
    """(what you bought, the disclosures that purchase legally requires)."""
    if plan == "monthly":
        return (
            f"the monthly plan — {MONTHLY_PRICE} USD a month",
            [f"It bills {MONTHLY_PRICE} USD each month until you cancel, and "
             "billing stops on its own when the season ends — we don't charge "
             "through the offseason, because we aren't sending you anything.",
             REFUND_TERMS],
        )
    if plan in PAYER_PLANS:
        return (
            f"the League Pass — {PASS_PRICE} USD for your whole league's season",
            # terms.html §3: the renewal falls on the purchase anniversary. This
            # used to say "before the season it covers", which nothing in Stripe
            # enforces — a wrong date in the acknowledgment the law requires.
            [f"It renews once a year at {PASS_PRICE} USD unless you cancel, on "
             "the anniversary of the day you bought it. We email you before it "
             "bills.",
             REFUND_TERMS_LEAGUE,
             SEATS_END],
        )
    if plan == "seat":
        return (
            "a seat on your league's League Pass",
            # "Your league's pass", never "your commissioner's": any manager
            # may buy the pass (panel review LP-D7).
            ["Nothing bills you for this seat, ever — your league's pass "
             "covers it. If the pass lapses, your reports stop; they never "
             "quietly convert into a charge."],
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
              "league_pass": "League Pass", "pass": "League Pass"}
TWICE_HEAD = "One report for this roster"
TWICE_SUBJECT = "You're in — one report a week for this roster, not two"


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
    if plan not in PAYER_PLANS and duplicate in PAYER_PLANS:
        # The pass already covers the buyer's own team: THIS purchase is the
        # spare, and it is certainly active — it was just bought.
        return (f"Your League Pass already covers this same roster, so you get one "
                f"report a week, not two. This {mine} bills on its own until you "
                f"cancel it, which you can do yourself on your billing page.")
    earlier = f"an earlier {other}" if duplicate == plan else f"the {other}"
    covered = (" Your League Pass covers your own team too, so you get one report "
               "a week, not two." if plan in PAYER_PLANS else
               " You get one report a week for it, not two.")
    return (f"This address also bought {earlier} for this same roster.{covered} "
            f"If that one is still active, it keeps billing until you cancel it, "
            f"which you can do yourself on your billing page.")


def _share(plan: str, seat_link: str | None) -> tuple[str, str, str] | None:
    """(the lead-in, the link, the message to paste) a League Pass payer sends
    their league; None for anybody else.

    With the league's own seat link (C4) the message is complete. Without it,
    the generic seat page matches a seat by the payer's address, so the
    payer is told to give it out; with no site at all there is no link to
    give, and the email says something true instead of a dead href."""
    if plan not in PAYER_PLANS:
        return None
    if seat_link and seat_link.startswith("https://"):
        return ("Every manager in your league gets their own report at no charge "
                "to them. This link is your league's own, so they need only "
                "their roster:", seat_link, SHARE_MESSAGE.format(link=seat_link))
    site = _site()
    if site:
        link = f"{site}/join/?pass=1"
        return ("Every manager who claims a seat gets their own report at no "
                "charge to them. Send them this link — each enters their own "
                "roster — and tell them the email you paid with (this one), "
                "which is how their seat is matched to your pass:", link,
                SHARE_MESSAGE.format(link=link)
                + " — when it asks for my email, it's the one I paid with.")
    return ("Every manager who claims a seat gets their own report at no "
            "charge to them; share your league's signup link whenever you're "
            "ready.", "", "")


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
# thanks.html), so the page and the email describe one sequence. A matched
# seat gets its first email the day it is claimed, by the same rules as a
# purchase (run/intake.py, LP-I4), so a seat has a "today" too.
NEXT_TODAY = ("Your first report. This week's lineup if the week's games "
              "haven't started, otherwise your roster report: the byes that "
              "leave you short and last season under your scoring.")
# "The odds on the close calls", never "every": a slot gets odds only when both
# players are confirmed to play, and a bye-heavy week can have few (PE-11).
NEXT_TUESDAY = ("The week's report: the lineup we'd set for your roster under "
                "your scoring, with the odds on the close calls. About ninety "
                "seconds to read.")
NEXT_SATURDAY = ("A short final check, only when Friday's injury report "
                 "changes your lineup. No news, no email.")


def _next_rows(seat: bool, carries_on: bool = False) -> list[tuple[str, str]]:
    """``carries_on``: a second purchase of a roster this address already
    gets reports for (LP2-D1). Its reports simply continue, so "Today: your
    first report" would promise something the intake does not send."""
    today = [] if carries_on else [("Today", NEXT_TODAY)]
    return [*today, ("Every Tuesday", NEXT_TUESDAY),
            ("Saturday, if needed", NEXT_SATURDAY)]


# A seat link is one long unbroken string; unwrapped, it pushed the email
# 17px past a 390px phone (Oct 2026).
_WRAP = "overflow-wrap:anywhere;word-break:break-word;"


def _masthead(subhead: str) -> str:
    """The weekly email's navy band (render/email._header), so the first email
    after paying looks like the product it bought."""
    return (
        f'<tr><td style="background:{NAVY};padding:24px 26px;'
        f'border-left:4px solid {FLAG};">'
        f'<div style="font-family:{DISPLAY};font-size:13px;font-weight:bold;'
        f'letter-spacing:4px;text-transform:uppercase;color:{FLAG};">'
        f'Beat Your League</div>'
        f'<div style="font-family:{DISPLAY};font-size:32px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{CARD};'
        f'padding:6px 0 2px 0;">You&#x27;re in.</div>'
        f'<div style="font-family:{FONT};font-size:15px;font-weight:bold;'
        f'color:{FLAG};padding:2px 0 0 0;">{esc(subhead)}</div></td></tr>')


def _block(title: str, inner: str) -> str:
    """One titled block, in the weekly email's section style."""
    return (
        f'<tr><td style="padding:22px 26px 0 26px;">'
        f'<div style="font-family:{DISPLAY};font-size:14px;font-weight:bold;'
        f'letter-spacing:2.5px;text-transform:uppercase;color:{NAVY};'
        f'border-bottom:2px solid {NAVY};padding-bottom:6px;">{esc(title)}</div>'
        f'<div style="padding-top:10px;">{inner}</div></td></tr>')


def welcome_message(email: str, plan: str, slug: str, season: str,
                    purchased_at: str = "", seat_link: str | None = None,
                    duplicate: str | None = None) -> Message:
    """Build the acknowledgment. ``plan`` is season|monthly|league_pass|seat
    (``pass`` is the League Pass payer too). ``seat_link`` is the payer's own
    league seat link (C4), or None to fall back to the generic seat page.
    ``duplicate`` is the plan of another subscription this address already
    holds for the same roster (``duplicate_line``)."""
    bought, terms = _plan_terms(plan)
    # A seat CLAIMED a place on somebody else's pass and has no Stripe
    # subscription, so "you bought" and a billing-page cancel were both false
    # for it: the portal finds no customer at that address, which left a seat
    # with no way out at all (launch audit C4, Oct 15 2026). Its way out is a
    # stop request, backed by the suppression list (run/suppress.py).
    seat = plan == "seat"
    verb = "claimed" if seat else "bought"
    if seat:
        stop_html, stop_text = esc(SEAT_STOP_BODY), SEAT_STOP_BODY
    else:
        href, label = _cancel_destination()
        cancel_line = (
            "Cancel any time, yourself, in about a minute — "
            + (f'<a href="{esc(href)}" style="color:#B3402F">{esc(label)}</a>.'
               if href else "the steps are on our site's terms page.")
        )
        cancel_text = ("Cancel any time, yourself, in about a minute — "
                       + (f"{label}: {href}" if href else
                          "the steps are on our site's terms page."))
        stop_html = f"{cancel_line} {esc(UNSUB_LINE)} {esc(CANCEL_PERIOD)}"
        stop_text = f"{cancel_text} {UNSUB_LINE} {CANCEL_PERIOD}"

    when = None if seat else _purchase_date(purchased_at)
    opener = f"You {verb} {bought}." + (f" Purchased {when}." if when else "")
    roster_line = ("Trades and pickups happen — reply to any report with your "
                   "updated roster and your report follows it from the next "
                   "Tuesday.")
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

    # ---------------------------------------------------------------- html
    para = f'<p style="{BASE}font-size:15px;margin:0 0 10px 0;">'
    rows_html = "".join(
        f'<tr><td style="{SMALL}color:{NAVY};font-weight:bold;'
        f'text-transform:uppercase;letter-spacing:1px;padding:9px 12px 9px 0;'
        f'vertical-align:top;width:30%;border-top:1px solid {LINE};">'
        f'{esc(when_)}</td><td style="{BASE}padding:9px 0;'
        f'border-top:1px solid {LINE};">{esc(what)}</td></tr>'
        for when_, what in _next_rows(seat, carries_on=bool(twice)))
    blocks = []
    twice_text = None
    if twice:
        # First, before anything else: it is about money being spent. The
        # route is its own sentence — a bare lowercase link label trailing
        # "your billing page." read as a fragment.
        href, label = _cancel_destination()
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
                f'<td style="background:{FLAG};border-radius:3px;">'
                f'<a href="{esc(link)}" style="display:inline-block;padding:12px 20px;'
                f'font-family:{DISPLAY};font-size:15px;font-weight:bold;'
                f'letter-spacing:1.5px;text-transform:uppercase;color:{NAVY};'
                f'text-decoration:none;">Your league&#x27;s seat link</a></td></tr>'
                f'</table>'
                f'<p style="{SMALL}margin:0 0 6px 0;">Or paste this into your '
                f'league chat:</p>'
                f'<div style="{BASE}background:{FLAG_TINT};border-left:3px solid '
                f'{FLAG};padding:10px 12px;{_WRAP}">{esc(paste)}</div>')
        blocks.append(_block("Send your league this", inner))
    blocks.append(_block(
        "What happens next",
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0">{rows_html}</table>'))
    terms_html = "".join(f'{para}{esc(term)}</p>' for term in terms)
    terms_html += (f'<p style="{SMALL}margin:4px 0 0 0;">{esc(terms_ref)}: '
                   + (f'<a href="{esc(terms_url)}" style="color:{NAVY};">'
                      f'{esc(terms_url)}</a>.' if terms_url else
                      "on our site's terms page.")
                   + '</p>')
    blocks.append(_block("The terms, in writing", terms_html))
    blocks.append(_block(CANCEL_HEAD, f'{para}{stop_html}</p>'))
    footer = (
        f'<tr><td style="padding:18px 26px 0 26px;"><p style="{BASE}font-size:13px;'
        f'color:{SLATE};margin:0;">{esc(roster_line)}</p></td></tr>'
        f'<tr><td style="padding:12px;"></td></tr>'
        f'<tr><td style="background:{PAPER};padding:18px 26px 24px 26px;">'
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
        f'style="padding:18px 8px;">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'border="0" style="max-width:600px;width:100%;background:{CARD};">'
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
                     in _next_rows(seat, carries_on=bool(twice))],
                   "", "THE TERMS, IN WRITING", *terms,
                   f"{terms_ref}: " + (terms_url or "on our site's terms page."),
                   "", CANCEL_HEAD.upper(), stop_text,
                   "", roster_line,
                   "", f"Beat Your League — questions? Write to {CONTACT}.",
                   *([sender] if sender else [])]
    text = "\n".join(text_lines) + "\n"

    # A first report goes out the day they pay or claim (run/intake.py; a
    # seat since LP-I4), so both subjects say it is on its way — except a
    # second purchase of a roster already served, whose reports carry on.
    subject = ("Your seat is in — your first report is on its way" if seat else
               TWICE_SUBJECT if twice else
               "You're in — your first report is on its way")
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
