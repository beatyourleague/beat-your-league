"""The note a League Pass seat claim gets when it matches no pass (LP-D1).

A leaguemate who claimed a seat was told on the page "Your seat request is
in" — and when the address they typed was not the one the pass was bought
with (a typo, two fields swapped, a pass bought by somebody other than the
commissioner), the claim was dropped with a line in a CI log and nobody ever
told them. This is that one message. It goes to the address that made the
claim (run/intake.py), once per claim, and it has two readers: the
leaguemate who did claim, who needs to know what to check, and somebody whose
address a stranger typed, who needs to know in one line that ignoring it is
safe. It names nobody and says nothing about anyone's purchase beyond what
the claimer already typed.
"""

from __future__ import annotations

from render.email import BASE, CARD, DISPLAY, FLAG, NAVY, PAPER, SMALL
from render.report import EMAIL_META, esc, preheader_html

SUBJECT = "Your League Pass seat isn't set up yet"
LEDE = ("You asked for a seat on a League Pass with this address, and the claim "
        "didn't match a League Pass purchase, so no seat was set up and no "
        "reports are coming yet.")
CHECK = ("Ask whoever bought your league's pass for their seat link and claim "
         "again with it — the link is matched to the pass for you. If you typed "
         "their email instead, it has to be the exact address the pass was "
         "bought with.")
IGNORE = "Didn't ask for this? Ignore this email — nothing happens."


def unmatched_email(site_url: str = "") -> tuple[str, str, str]:
    """(subject, html, text). ``site_url`` adds the League Pass page, which
    says who can buy a pass and how seats work; without it the note stands on
    its own."""
    site = (site_url or "").rstrip("/")
    page = f"{site}/league-pass.html" if site else ""
    more_html = (f'<p style="{BASE}margin:0 0 14px 0;">How seats work: '
                 f'<a href="{esc(page)}" style="color:{NAVY};">{esc(page)}</a></p>'
                 if page else "")
    html = (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'{EMAIL_META}<title>{esc(SUBJECT)}</title></head>'
        f'<body style="margin:0;padding:0;background:{PAPER};">'
        f'{preheader_html("Your seat claim did not match a League Pass. Here is what to check.")}'
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
        f'{esc(SUBJECT)}</div></td></tr>'
        f'<tr><td style="padding:22px 26px;">'
        f'<p style="{BASE}margin:0 0 14px 0;">{esc(LEDE)}</p>'
        f'<p style="{BASE}margin:0 0 14px 0;">{esc(CHECK)}</p>'
        f'{more_html}'
        f'<p style="{SMALL}margin:18px 0 0 0;">{esc(IGNORE)}</p>'
        f'</td></tr></table></td></tr></table></body></html>\n')
    text = "\n".join([SUBJECT.upper(), "", LEDE, "", CHECK, "",
                      *([f"How seats work: {page}", ""] if page else []),
                      IGNORE, ""])
    return SUBJECT, html, text
