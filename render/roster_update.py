"""The roster-change confirmation email (run/updates.py, confirm-by-email).

It goes ONLY to the address on the subscription, and it has to work for two
readers: the subscriber who just asked, who wants one button, and the
subscriber who did not ask, who needs to know in one line that ignoring it is
safe. Both are served by saying plainly what changes and that nothing happens
without the button.
"""

from __future__ import annotations

from typing import Sequence

from render.email import BASE, CARD, DISPLAY, FLAG, FONT, NAVY, PAPER, SMALL
from render.report import EMAIL_META, esc, preheader_html

SUBJECT = "Confirm your roster change"
IGNORE = ("Didn't ask for this? Ignore this email — nothing changes unless "
          "you confirm.")


def confirm_email(url: str, names: Sequence[str]) -> tuple[str, str, str]:
    """(subject, html, text)."""
    listed = ", ".join(names) if names else ""
    roster_html = (f'<p style="{BASE}margin:0 0 14px 0;"><b>New roster:</b> '
                   f'{esc(listed)}</p>' if listed else "")
    html = (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'{EMAIL_META}<title>{esc(SUBJECT)}</title></head>'
        f'<body style="margin:0;padding:0;background:{PAPER};">'
        f'{preheader_html("Confirm the roster change you asked for. Nothing changes unless you do.")}'
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
        f'Confirm your roster change</div></td></tr>'
        f'<tr><td style="padding:22px 26px;">'
        f'<p style="{BASE}margin:0 0 14px 0;">Someone asked to change the roster your '
        f'reports are built from. If that was you, confirm it and your next report '
        f'uses it.</p>{roster_html}'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="background:{FLAG};border-radius:4px;">'
        f'<a href="{esc(url)}" style="display:inline-block;padding:12px 22px;'
        f'font-family:{FONT};font-size:15px;font-weight:bold;color:{NAVY};'
        f'text-decoration:none;">Review and confirm</a></td></tr></table>'
        f'<p style="{SMALL}margin:18px 0 0 0;">{esc(IGNORE)}</p>'
        f'</td></tr></table></td></tr></table></body></html>\n')
    text = "\n".join([
        SUBJECT.upper(), "",
        "Someone asked to change the roster your reports are built from. If that "
        "was you, confirm it and your next report uses it.", "",
        *( [f"New roster: {listed}", ""] if listed else [] ),
        f"Review and confirm: {url}", "", IGNORE, ""])
    return SUBJECT, html, text
