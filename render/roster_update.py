"""The roster-change confirmation email (run/updates.py, confirm-by-email).

It goes ONLY to the address on the subscription, and it has to work for two
readers: the subscriber who just asked, who wants one button, and the
subscriber who did not ask, who needs to know in one line that ignoring it is
safe. Both are served by saying plainly what changes and that nothing happens
without the button.

"What changes" includes the SETTINGS (FUNNEL F1 / COPY:F2): an update replaces
the scoring, league size and lineup on file with the ones the page posted
(run/updates.apply_updates), and the email listed only the players — so a
subscriber who left the page on its defaults confirmed a re-scoring of every
later report without being shown it. The settings are printed, a changed one
as old → new, and so is how long the button works (run/updates.EXPIRY_DAYS),
which the confirm page already said and the email did not.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from render.email import BASE, CARD, DISPLAY, FLAG, FONT, NAVY, PAPER, SMALL
from render.report import EMAIL_META, esc, preheader_html
from run.updates import EXPIRY_DAYS

SUBJECT = "Confirm your roster change"
IGNORE = ("Didn't ask for this? Ignore this email — nothing changes unless "
          "you confirm.")
LIMIT = f"The button works for {EXPIRY_DAYS} days after the change was asked for."

# The join page's words for the same settings (site/join/index.html
# SCORING_WORDS / shapeWords), so the email names them as the page did.
SCORING_WORDS = {"ppr": "Full PPR", "half_ppr": "Half PPR", "standard": "Standard scoring"}


def _get(setup: Any, name: str) -> Any:
    return setup.get(name) if isinstance(setup, Mapping) else getattr(setup, name, None)


def _lineup_words(slots: Sequence[str]) -> str:
    """"Two FLEX lineup, no K" — the shape's own label (engine.subscriber),
    with "lineup" after the base as the join page writes it; a shape the page
    does not offer is listed slot by slot."""
    from engine.subscriber import LINEUP_SHAPES
    shape = next((s for s in LINEUP_SHAPES.values() if tuple(s.slots) == tuple(slots)), None)
    if shape is None:
        return "Lineup " + ", ".join(slots)
    base, _, rest = shape.label.partition(", ")
    return f"{base} lineup" + (f", {rest}" if rest else "")


def setting_words(setup: Any) -> tuple[str, str, str]:
    """(scoring, league size, lineup) in the buyer's words. ``setup`` is
    anything with scoring, league_size and slots — a decoded ref or a
    registry row."""
    scoring = str(_get(setup, "scoring") or "")
    size = _get(setup, "league_size")
    return (SCORING_WORDS.get(scoring, scoring),
            f"{int(size)} teams" if size else "",
            _lineup_words(tuple(_get(setup, "slots") or ())))


def settings_line(settings: Any, on_file: Any = None) -> str:
    """"Half PPR → Full PPR · 12 teams · Standard lineup": every setting the
    change applies, each one that differs from the subscription on file shown
    as old → new."""
    new = setting_words(settings)
    old = setting_words(on_file) if on_file is not None else new
    parts = [f"{was} → {now}" if was and was != now else now
             for was, now in zip(old, new) if now]
    return " · ".join(parts)


def confirm_email(url: str, names: Sequence[str], settings: Any = None,
                  on_file: Any = None) -> tuple[str, str, str]:
    """(subject, html, text). ``settings`` is the requested roster (its
    scoring, size and lineup); ``on_file`` the subscription as it stands, so a
    setting the change would move reads old → new."""
    listed = ", ".join(names) if names else ""
    roster_html = (f'<p style="{BASE}margin:0 0 14px 0;"><b>New roster:</b> '
                   f'{esc(listed)}</p>' if listed else "")
    setup = settings_line(settings, on_file) if settings is not None else ""
    setup_html = (f'<p style="{BASE}margin:0 0 14px 0;"><b>Settings:</b> '
                  f'{esc(setup)}</p>' if setup else "")
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
        f'uses it.</p>{roster_html}{setup_html}'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="background:{FLAG};border-radius:4px;">'
        f'<a href="{esc(url)}" style="display:inline-block;padding:12px 22px;'
        f'font-family:{FONT};font-size:15px;font-weight:bold;color:{NAVY};'
        f'text-decoration:none;">Review and confirm</a></td></tr></table>'
        f'<p style="{SMALL}margin:14px 0 0 0;">{esc(LIMIT)}</p>'
        f'<p style="{SMALL}margin:8px 0 0 0;">{esc(IGNORE)}</p>'
        f'</td></tr></table></td></tr></table></body></html>\n')
    text = "\n".join([
        SUBJECT.upper(), "",
        "Someone asked to change the roster your reports are built from. If that "
        "was you, confirm it and your next report uses it.", "",
        *([f"New roster: {listed}", ""] if listed else []),
        *([f"Settings: {setup}", ""] if setup else []),
        f"Review and confirm: {url}", "", LIMIT, "", IGNORE, ""])
    return SUBJECT, html, text
