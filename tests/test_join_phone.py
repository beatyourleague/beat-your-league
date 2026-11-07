"""The buy page tells a phone what a phone can do.

Promotion review (Nov 2026): step 1 said "Paste it from ESPN, Yahoo, Sleeper
or CBS". Most visitors from Reddit and X are on phones, and those apps' phone
versions mostly can't copy a roster, so the first instruction sent people out
of the browser to fail. The app pages already say "on a phone, type each
name". Now the join page does too, at phone width, and keeps the paste
guidance for wider screens. Typing works: the first suggestion was the right
player for every name the review tried.
"""

from __future__ import annotations

import re
from pathlib import Path

from render.platforms import STEPS

SITE = Path(__file__).resolve().parent.parent / "site"
JOIN = (SITE / "join" / "index.html").read_text(encoding="utf-8")
CSS = JOIN.split("<style>", 1)[1].split("</style>", 1)[0]
SCRIPT = JOIN.split("<script>\n", 1)[1].split("</script>", 1)[0]

WIDE = "Paste it from ESPN, Yahoo, Sleeper or CBS, extra text and all. Or type a name to add one player."
PHONE = ("On a phone, type each name into “Add a player” and tap him. Any part of his name "
         "finds him. Copied a roster page? Paste it into the roster box, extra text and all.")


def _note() -> str:
    step = JOIN.split('<section id="step-roster">', 1)[1].split("<form", 1)[0]
    note = re.search(r'<div class="note" id="roster-how">(.*?)</div>', step, re.S)
    assert note, "step 1's note is gone"
    return note.group(1)


def _flat(markup: str) -> str:
    return re.sub(r"\s+", " ", markup).strip()


def test_step_one_says_type_on_a_phone_and_paste_on_a_computer() -> None:
    note = _note()
    wide = re.search(r'<span class="how-wide">(.*?)</span>', note, re.S)
    phone = re.search(r'<span class="how-phone">(.*?)</span>', note, re.S)
    assert wide and phone, note
    assert _flat(wide.group(1)) == WIDE
    assert _flat(phone.group(1)) == PHONE


def test_only_one_of_the_two_shows_at_any_width() -> None:
    """Hidden by CSS, never by script, so it holds in every mode and on a page
    whose script never ran. display:none also keeps the hidden one away from a
    screen reader, so nobody hears both."""
    assert ".how-phone{display:none;}" in CSS
    # Narrow OR a touch screen without hover: a phone held sideways is wider
    # than 600px (iPhone SE 667, Pro Max 932) and must still read the phone
    # words (promotion review, Nov 6 2026).
    phone_rules = re.search(r"@media \(max-width:600px\), \(hover:none\) and \(pointer:coarse\)\{"
                            r"\s*\.how-wide\{display:none;\}"
                            r"\s*\.how-phone\{display:inline;\}\s*\}", CSS)
    assert phone_rules, "the phone swap needs its own block: 600px, or a touch screen"
    # The page's own phone width: its 600px layout block is the same query.
    assert CSS.count("@media (max-width:600px){") >= 3
    assert "roster-how" not in SCRIPT and "how-phone" not in SCRIPT and "how-wide" not in SCRIPT


def test_the_phone_words_name_what_is_on_the_page() -> None:
    """"Add a player" is the field's own placeholder, and the roster box is the
    one that says to paste. The sentence is the app pages' own, so the two
    surfaces say the same thing."""
    assert 'placeholder="Add a player — start typing a name"' in JOIN
    assert '<textarea id="roster-text" spellcheck="false" placeholder="Paste your roster here' in JOIN
    app_words = STEPS[2].removeprefix("Or ")
    assert app_words in PHONE
    # The note comes first, then the field it names, then the roster box.
    step = JOIN.split('<section id="step-roster">', 1)[1]
    assert step.index('id="roster-how"') < step.index('id="player-search"') < step.index(
        'id="roster-text"')
