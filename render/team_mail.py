"""The emails an extra team sends (run/teams.py). Each goes only to the address
on the subscription. The confirmation has two readers, like a roster change's:
the subscriber who asked, and the one who didn't, who needs to know in one line
that ignoring it is safe.
"""

from __future__ import annotations

from typing import Any, Sequence

from render.email import BASE, FLAG, FONT, NAVY, SMALL
from render.report import esc
from render.roster_update import setting_words
from run.delivery import Message
from run.plans import TEAMS_INCLUDED
from run.updates import EXPIRY_DAYS

CONFIRM_SUBJECT = "Confirm your new team"
IGNORE = ("Didn't ask for this? Ignore this email. Nothing is added unless you "
          "confirm, and nothing is charged either way.")
LIMIT = f"The button works for {EXPIRY_DAYS} days after the team was added."
CONFIRM_LEDE = ("Someone asked to add a team to your plan. If that was you, confirm "
                "it and the team starts getting its own report. It's included in "
                "your plan at no extra charge.")
FULL_SUBJECT = "Your plan's teams are all in use"
FULL_BODY = (f"Your plan covers up to {TEAMS_INCLUDED} teams and all of them are in "
             f"use, so this one wasn't added. Nothing was charged. To swap a team, "
             f"use the roster link in that team's report.")
ADDED_SUBJECT = "Your new team is set up"
ADDED_BODY = ("It's included in your plan at no extra charge. It gets its own report "
              "every Wednesday and its own Saturday check when it needs one. "
              "Your first report for it is on its way. Cancelling your plan ends "
              "all of your teams together, so there's nothing extra to keep track of.")


def _shell(subject: str, preheader: str, body: str) -> str:
    """The report's masthead over the body (render.email.note_html)."""
    from render.email import note_html
    return note_html(subject, preheader, body)


def _setup_words(settings: Any) -> str:
    league = str(getattr(settings, "league_type", "redraft") or "redraft").capitalize()
    return " · ".join(part for part in (league, *setting_words(settings)) if part)


def team_confirm_email(url: str, names: Sequence[str], settings: Any,
                       name: str = "") -> tuple[str, str, str]:
    """(subject, html, text)."""
    listed = ", ".join(names)
    setup = _setup_words(settings)
    lines = [("Team name", name), ("Roster", listed), ("Settings", setup)]
    facts = "".join(f'<p style="{BASE}margin:0 0 14px 0;"><b>{esc(head)}:</b> {esc(value)}</p>'
                    for head, value in lines if value)
    body = (f'<p style="{BASE}margin:0 0 14px 0;">{esc(CONFIRM_LEDE)}</p>{facts}'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="background:{FLAG};border-radius:4px;">'
            f'<a href="{esc(url)}" style="display:inline-block;padding:12px 22px;'
            f'font-family:{FONT};font-size:15px;font-weight:bold;color:{NAVY};'
            f'text-decoration:none;">Review and confirm</a></td></tr></table>'
            f'<p style="{SMALL}margin:14px 0 0 0;">{esc(LIMIT)}</p>'
            f'<p style="{SMALL}margin:8px 0 0 0;">{esc(IGNORE)}</p>')
    html = _shell(CONFIRM_SUBJECT, "A team was added to your plan. Nothing changes "
                  "unless you confirm it.", body)
    text = "\n".join([CONFIRM_SUBJECT.upper(), "", CONFIRM_LEDE, "",
                      *[f"{head}: {value}\n" for head, value in lines if value],
                      f"Review and confirm: {url}", "", LIMIT, "", IGNORE, ""])
    return CONFIRM_SUBJECT, html, text


def team_full_email() -> tuple[str, str, str]:
    """(subject, html, text): the request that found no room."""
    html = _shell(FULL_SUBJECT, "This team wasn't added. Nothing was charged.",
                  f'<p style="{BASE}margin:0;">{esc(FULL_BODY)}</p>')
    return FULL_SUBJECT, html, "\n".join([FULL_SUBJECT.upper(), "", FULL_BODY, ""])


def team_added_message(signup) -> Message:
    """The note once a team is on the plan. Keyed on the team, so it goes once."""
    name = "" if signup.label == "Your Team" else signup.label
    subject = f"{name} is set up" if name else ADDED_SUBJECT
    html = _shell(subject, "Your new team is on your plan at no extra charge.",
                  f'<p style="{BASE}margin:0;">{esc(ADDED_BODY)}</p>')
    return Message(to=signup.email, subject=subject, html=html,
                   text="\n".join([subject.upper(), "", ADDED_BODY, ""]),
                   key=f"team-added-{signup.slug}")
