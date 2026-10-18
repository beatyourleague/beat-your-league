"""The emails a League Pass seat CLAIM gets, before it is a seat.

Three of them, all sent by run/intake.py to the address that made the claim
and nowhere else:

- **The confirmation** (OPS-R1). A claim is a request: the seat link rides on
  every pass report and those are written to be forwarded, so holding it
  proves nothing about who is claiming. Honoured on sight, it let anyone
  enrol a stranger's address for weekly mail, or replace a seat holder's
  roster with nobody told. So the claimed address gets one button, and
  nothing happens until it is pressed — a new seat, or a roster change to a
  seat they hold, alike.
- **No pass matched** (LP-D1). A leaguemate who claimed was told on the page
  "Your seat request is in" — and when the address they typed was not the one
  the pass was bought with, the claim was dropped with a line in a CI log and
  nobody ever told them.
- **The pass is full** (OPS-R7). A pass covers as many seats as its league
  has teams, and no more.

Each has two readers: the leaguemate who did claim, who needs to know what
happens or what to check, and somebody whose address a stranger typed, who
needs to know in one line that ignoring it is safe. None names anybody or
says anything about anyone's purchase beyond what the claimer already typed.
Each says who sent it, with the postal address once one is configured — the
one email that reaches an address a stranger can type, and it links a sales
page, so it carries the identification every other email does (COPY:F3).
"""

from __future__ import annotations

from typing import Sequence

from render.email import BASE, CARD, DISPLAY, FLAG, FONT, NAVY, PAPER, SMALL
from render.report import EMAIL_META, esc, preheader_html
from render.sender import CONTACT, sender_line

SUBJECT = "Your League Pass seat isn't set up yet"
LEDE = ("You asked for a seat on a League Pass with this address, and the claim "
        "didn't match a League Pass purchase, so no seat was set up and no "
        "reports are coming yet.")
CHECK = ("Ask whoever bought your league's pass for their seat link and claim "
         "again with it — the link is matched to the pass for you. If you typed "
         "their email instead, it has to be the exact address the pass was "
         "bought with.")
IGNORE = "Didn't ask for this? Ignore this email — nothing happens."

CONFIRM_SUBJECT = "Confirm your League Pass seat"
CONFIRM_LEDE = ("Someone asked for a seat on your league's League Pass with this "
                "address. If that was you, confirm it: your seat is set up, "
                "usually within the hour, and your reports are built from this "
                "roster.")
CHANGE_SUBJECT = "Confirm the roster change on your League Pass seat"
CHANGE_LEDE = ("Someone asked to change the roster on your League Pass seat. If "
               "that was you, confirm it within 7 days. It takes effect usually "
               "within the hour, and every report built after that uses it. If "
               "you asked more than once, the newest change you confirm is the "
               "one that counts.")
CONFIRM_LIMIT = "The button works for 7 days after the claim was made."
CONFIRM_IGNORE = ("Didn't ask for this? Ignore this email — nothing is set up or "
                  "changed unless you confirm.")

# A claim that matched a League Pass that is not active right now (refunded,
# lapsed, or its payment failed) — D10, JOIN-103: the join page promises an
# email when a claim can't be matched to a League Pass, and this one was only
# a log line.
INACTIVE_LEDE = ("You asked for a seat on a League Pass with this address. That "
                 "League Pass isn't active right now, so no seat was set up and "
                 "no reports are coming.")
INACTIVE_CHECK = ("Ask whoever bought your league's pass to check it. Once it's "
                  "active again, claim your seat with the same link.")

FULL_SUBJECT = "That League Pass has no seats left"
FULL_LEDE = ("You asked for a seat on a League Pass with this address. That pass "
             "covers as many seats as its league has teams, and they are all "
             "taken, so no seat was set up and no reports are coming.")
FULL_CHECK = (f"If one of those seats should be yours, ask whoever bought your "
              f"league's pass to write to {CONTACT} — we can free a seat that's "
              f"no longer used.")


def _shell(subject: str, preheader: str, body_html: str) -> str:
    """The navy masthead, the body, and the sender block — one document a
    phone lays out, held to every email client's rules."""
    sender = sender_line()
    return (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'{EMAIL_META}<title>{esc(subject)}</title></head>'
        f'<body style="margin:0;padding:0;background:{PAPER};">'
        f'{preheader_html(preheader)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{PAPER};"><tr><td align="center" '
        f'style="padding:18px 8px;"><table role="presentation" width="560" '
        f'cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:560px;width:100%;background:{CARD};">'
        f'<tr><td style="background:{NAVY};padding:20px 26px;border-left:4px solid {FLAG};">'
        f'<div style="font-family:{DISPLAY};font-size:13px;font-weight:bold;'
        f'letter-spacing:4px;text-transform:uppercase;color:{FLAG};">Beat Your League</div>'
        f'<div style="font-family:{DISPLAY};font-size:24px;font-weight:bold;'
        f'text-transform:uppercase;color:{CARD};padding-top:6px;">'
        f'{esc(subject)}</div></td></tr>'
        f'<tr><td style="padding:22px 26px;">{body_html}</td></tr>'
        f'<tr><td style="background:{PAPER};padding:16px 26px 22px 26px;">'
        f'<p style="{SMALL}margin:0;"><b>Beat Your League</b> — questions? '
        f'Write to {esc(CONTACT)}.'
        + (f'<br>{esc(sender)}' if sender else "")
        + '</p></td></tr></table></td></tr></table></body></html>\n')


def _footer_lines() -> list[str]:
    sender = sender_line()
    return [f"Beat Your League — questions? Write to {CONTACT}.",
            *([sender] if sender else [])]


def _para(text: str) -> str:
    return f'<p style="{BASE}margin:0 0 14px 0;">{esc(text)}</p>'


def _page_link(site_url: str) -> tuple[str, str]:
    """(html, url) for the League Pass page, which says who can buy a pass
    and how seats work; empty without a site."""
    site = (site_url or "").rstrip("/")
    page = f"{site}/league-pass.html" if site.startswith("https://") else ""
    html = (f'<p style="{BASE}margin:0 0 14px 0;">How seats work: '
            f'<a href="{esc(page)}" style="color:{NAVY};">{esc(page)}</a></p>'
            if page else "")
    return html, page


def unmatched_email(site_url: str = "") -> tuple[str, str, str]:
    """(subject, html, text) for a claim that matched no pass."""
    more_html, page = _page_link(site_url)
    html = _shell(SUBJECT,
                  "Your seat claim did not match a League Pass. Here is what to check.",
                  _para(LEDE) + _para(CHECK) + more_html
                  + f'<p style="{SMALL}margin:18px 0 0 0;">{esc(IGNORE)}</p>')
    text = "\n".join([SUBJECT.upper(), "", LEDE, "", CHECK, "",
                      *([f"How seats work: {page}", ""] if page else []),
                      IGNORE, "", *_footer_lines(), ""])
    return SUBJECT, html, text


def inactive_email(site_url: str = "") -> tuple[str, str, str]:
    """(subject, html, text) for a claim on a pass that is not active."""
    more_html, page = _page_link(site_url)
    html = _shell(SUBJECT,
                  "That League Pass isn't active right now, so no seat was set up.",
                  _para(INACTIVE_LEDE) + _para(INACTIVE_CHECK) + more_html
                  + f'<p style="{SMALL}margin:18px 0 0 0;">{esc(IGNORE)}</p>')
    text = "\n".join([SUBJECT.upper(), "", INACTIVE_LEDE, "", INACTIVE_CHECK, "",
                      *([f"How seats work: {page}", ""] if page else []),
                      IGNORE, "", *_footer_lines(), ""])
    return SUBJECT, html, text


def full_email(site_url: str = "") -> tuple[str, str, str]:
    """(subject, html, text) for a claim on a pass whose seats are taken."""
    more_html, page = _page_link(site_url)
    html = _shell(FULL_SUBJECT,
                  "Every seat on that League Pass is taken, so no seat was set up.",
                  _para(FULL_LEDE) + _para(FULL_CHECK) + more_html
                  + f'<p style="{SMALL}margin:18px 0 0 0;">{esc(IGNORE)}</p>')
    text = "\n".join([FULL_SUBJECT.upper(), "", FULL_LEDE, "", FULL_CHECK, "",
                      *([f"How seats work: {page}", ""] if page else []),
                      IGNORE, "", *_footer_lines(), ""])
    return FULL_SUBJECT, html, text


def confirm_email(url: str | None, names: Sequence[str],
                  change: bool = False) -> tuple[str, str, str]:
    """(subject, html, text) for a claim waiting on this address. ``change``
    is a re-claim by somebody who already holds a seat on the pass: a roster
    change, said as one."""
    subject = CHANGE_SUBJECT if change else CONFIRM_SUBJECT
    lede = CHANGE_LEDE if change else CONFIRM_LEDE
    listed = ", ".join(names) if names else ""
    roster_html = (f'<p style="{BASE}margin:0 0 14px 0;"><b>Roster:</b> '
                   f'{esc(listed)}</p>' if listed else "")
    button = ""
    if url and url.startswith("https://"):
        button = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td style="background:{FLAG};border-radius:4px;">'
            f'<a href="{esc(url)}" style="display:inline-block;padding:12px 22px;'
            f'font-family:{FONT};font-size:15px;font-weight:bold;color:{NAVY};'
            f'text-decoration:none;">Review and confirm</a></td></tr></table>')
    html = _shell(subject,
                  "Confirm it was you. Nothing is set up unless you do.",
                  _para(lede) + roster_html + button
                  + f'<p style="{SMALL}margin:14px 0 0 0;">{esc(CONFIRM_LIMIT)}</p>'
                  + f'<p style="{SMALL}margin:8px 0 0 0;">{esc(CONFIRM_IGNORE)}</p>')
    text = "\n".join([
        subject.upper(), "", lede, "",
        *([f"Roster: {listed}", ""] if listed else []),
        *([f"Review and confirm: {url}", ""] if url else []),
        CONFIRM_LIMIT, "", CONFIRM_IGNORE, "", *_footer_lines(), ""])
    return subject, html, text
