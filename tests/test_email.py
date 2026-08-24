"""Tests for the email-safe renderer — the HTML that actually gets sent.

The properties here are the reason the module exists: email clients cannot
render the browser report, and the pinned consumer protections must survive
the translation. Content decisions are imported from render.report, so most
honesty rules are inherited — these tests pin the email-specific surface.
"""

from __future__ import annotations

import re
from pathlib import Path

import test_week_report as twr
from engine.week_report import build_week_report
from render.email import render_email
from render.report import (
    CANCEL_BODY,
    CANCEL_HEAD,
    NO_BETTING_LINE,
    edge_phrase,
    esc,
)


def _report(tmp_path: Path) -> dict:
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    return build_week_report(raw, season.league_id, twr.REPORT_WEEK, 1)


def test_email_contains_no_email_unsafe_constructs(tmp_path: Path) -> None:
    """Outlook renders with Word; Gmail strips <style> on forward. Anything
    on this list degrades to soup in at least one major client."""
    html_out = render_email(_report(tmp_path))
    for construct in ("display:grid", "display:flex", "var(--", "@media",
                      "fonts.googleapis", "<link", "<style",
                      "position:absolute", "position:fixed"):
        assert construct not in html_out, f"email-unsafe construct: {construct}"


def test_email_layout_is_tables_with_inline_styles(tmp_path: Path) -> None:
    html_out = render_email(_report(tmp_path))
    assert 'role="presentation"' in html_out
    assert re.search(r'font-family:Arial,Helvetica,sans-serif', html_out), \
        "email must use a web-safe font stack"


def test_email_carries_every_section(tmp_path: Path) -> None:
    """Per-subscriber reports are private — there is no hosted copy to link
    to, so the email must BE the report, not a teaser for one."""
    html_out = render_email(_report(tmp_path))
    for title in ("The 30-Second Game Plan", "The Matchup", "Lineup",
                  "Is Fragile", "Your Regret Score", "Pivot Plan",
                  "Waiver Hype Meter", "The Receipts"):
        assert title in html_out, f"email dropped section: {title}"
    assert "http" not in html_out.split("</title>")[1].split("Beat Your League</b>")[0], \
        "the report body must be self-contained (no hosted-report links)"


def test_email_carries_the_way_out(tmp_path: Path) -> None:
    """The cancel/unsubscribe distinction is pinned language: stopping emails
    while billing continues is how you earn a chargeback and deserve it."""
    html_out = render_email(_report(tmp_path))
    assert CANCEL_HEAD in html_out
    assert "Unsubscribing from emails alone does not stop a subscription" in html_out
    assert CANCEL_BODY.split(" — ")[0] in html_out


def test_email_carries_the_disclaimers(tmp_path: Path) -> None:
    html_out = render_email(_report(tmp_path))
    assert NO_BETTING_LINE.split(" — ")[0] in html_out
    assert "no betting picks" in html_out
    # Data-age basis (principle 3): the email says what it couldn't confirm.
    # (Apostrophes render escaped, so match the apostrophe-free phrase.)
    assert re.search(r"Injury and inactive data as of|confirm injuries or inactives",
                     html_out)


def test_email_escapes_hostile_names(tmp_path: Path) -> None:
    report = _report(tmp_path)
    html_out = render_email(report)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_email_gates_render_honestly(tmp_path: Path) -> None:
    """A withheld number says "no call"/"Not calling it" — never a version
    number, never a fabricated zero."""
    html_out = render_email(_report(tmp_path))
    assert "Not calling it" in html_out
    assert "v0.3" not in html_out and "v0." not in html_out


def test_batch_sends_the_email_rendering_not_the_browser_one(
        tmp_path, monkeypatch) -> None:
    """The Message.html a provider receives must be the email-safe form; the
    browser-grade file on disk is the archival artifact."""
    import json as _json

    import run.batch as batch
    from run.registry import Subscriber
    season = twr._season()
    raw = twr._write_cache(tmp_path, season)
    monkeypatch.setattr(batch, "RAW_DIR", raw)
    monkeypatch.setattr(batch, "SUBSCRIBER_REPORTS", tmp_path / "out")
    rosters_file = raw / "league" / season.league_id / "rosters.json"
    rosters_file.write_text(_json.dumps([
        {"roster_id": 1, "owner_id": "1"},
        {"roster_id": 2, "owner_id": "2"},
    ]), encoding="utf-8")
    subscriber = Subscriber(
        email="fan@example.com", user_id="1", league_id=season.league_id,
        rival_owner_id=None, rival_roster_id=2, sleeper_username="kevin_fan")
    result = batch.run_subscriber(subscriber, twr.REPORT_WEEK, twr._template())
    assert result.ok, result.detail
    assert result.message is not None
    assert "var(--" not in result.message.html, \
        "batch mailed the browser-grade HTML"
    assert 'role="presentation"' in result.message.html
    # The archival file on disk stays the full browser rendering.
    assert "var(--" in result.html_path.read_text(encoding="utf-8")


def test_the_email_carries_the_design_system(tmp_path: Path) -> None:
    """The email is the surface a subscriber actually sees — roughly 17 sends a
    season against one or two visits to the marketing site. It rendered in flat
    Arial with both scores in navy, so the brand lived on the pages bought once
    and was absent from the product delivered every week."""
    html_out = render_email(_report(tmp_path))
    # A condensed display face that survives Word's engine (Arial Narrow ships
    # with Windows and macOS); no webfont, so nothing is fetched.
    assert "'Arial Narrow'" in html_out
    assert "fonts.googleapis" not in html_out
    # green-you / red-them, the coding every fantasy platform trains readers on
    assert "#1E7A46" in html_out and "#B3402F" in html_out
    # the masthead rule that carries the identity where SVG cannot go
    assert "border-left:4px solid #F2C230" in html_out


def test_the_email_gap_never_ships_without_its_swing(tmp_path: Path) -> None:
    """Same rule as the browser report: the gap is the numerator of a gated
    quantity, so it never appears alone or in a verdict colour."""
    report = _report(tmp_path)
    html_out = render_email(report)
    if report["matchup"].get("margin") is not None:
        assert "swings" in html_out
        assert "projected ahead" in html_out or "projected behind" in html_out


def test_a_dead_heat_edge_never_prints_as_negative_zero() -> None:
    """A hair-thin gap rounds to 0.0, and "+.1f" formatting turns the negative
    side of it into "-0.0 over" — found in the published sample report, where
    the one artifact meant to prove polish carried what reads as a bug. A gap
    inside rounding distance of zero is a dead heat and says so."""
    slot = {"edge": -0.04, "alternative_name": "Chase Brown"}
    assert edge_phrase(slot) == "even with Chase Brown on your bench"
    slot["edge"] = 0.04
    assert edge_phrase(slot) == "even with Chase Brown on your bench"
    slot["edge"] = -0.6
    assert edge_phrase(slot) == "-0.6 over Chase Brown on your bench"
    slot["edge"] = 1.55
    assert "+1.5" in edge_phrase(slot) or "+1.6" in edge_phrase(slot)


def test_a_gated_row_says_why_in_its_own_cell() -> None:
    """Three of nine rows in the published sample read "no call" with every
    reason pooled into one line under the table, so a reader could not tell
    which applied to their QB. The call column now carries the reason, short:
    the only QB on a roster is not a defect."""
    from render.report import short_gate
    assert short_gate("nobody on your bench is eligible here", "QB") == "no call · no bench QB"
    assert short_gate("not enough games on record yet (1 and 2; we want at least 3)",
                      "RB") == "no call · too few games yet"
    assert short_gate("we don't put a number on defenses yet — we haven't checked our "
                      "defense calls against enough real weeks", "DEF") \
        == "no call · defenses not graded yet"
    assert short_gate("availability in doubt (questionable)", "WR") \
        == "no call · status unconfirmed"
    assert short_gate(None, "K") == "no call"


def test_the_explainer_makes_no_claim_a_shown_number_is_not_a_guess() -> None:
    """Grade C of the frozen method deletes 'otherwise we'd be guessing, and
    you can guess for free' from the no-call explainer — it asserts that a
    printed number is not a guess, which is the claim the grade withholds —
    and keeps the public-record sentence."""
    from render.report import no_call_explainer
    text = no_call_explainer("nobody on your bench is eligible here")
    assert "guess for free" not in text
    assert "public record and gets graded" in text


def test_the_email_carries_what_the_browser_report_carries(tmp_path: Path) -> None:
    """The email IS the product; the browser file is the archive. Usage and the
    per-row point gap were added to the browser renderer only, so the free demo
    briefly showed more than the thing subscribers pay for. This pins parity on
    the fields most likely to be added to one renderer and forgotten in the
    other."""
    from render.report import TEMPLATE_PATH, render
    report = _report(tmp_path)
    email_html = render_email(report)
    browser_html = render(report, TEMPLATE_PATH.read_text(encoding="utf-8"))

    if any(h.get("usage") for h in report.get("hype", [])):
        assert "targets" in email_html, "email dropped counted usage"
    for slot in report.get("lineup", []):
        phrase = edge_phrase(slot)
        if phrase:
            assert esc(phrase) in email_html, f"email dropped the point gap: {phrase}"
            assert esc(phrase) in browser_html
    # the sentence that used to exist in three diverging copies
    if "of the other" in browser_html:
        assert "of the other" in email_html, \
            "the who-can-cover denominator drifted between surfaces"


# --------------------------------------------------------------------- #
# the solo product — no league, no opponent
# --------------------------------------------------------------------- #

def _solo_report() -> dict:
    """A minimal solo report, built through the real builders."""
    from engine.projection import ProjectionModel
    from engine.availability import WeekAvailability
    from engine.roster import Player, PlayerDirectory
    from engine.solo_report import build_solo_report
    from engine.subscriber import RosterSpec, build_season, player_index

    people = [Player(f"00-000000{i}", n, p, "KC") for i, (n, p) in enumerate(
        [("Star QB", "QB"), ("Bell Cow", "RB"), ("Committee RB", "RB"),
         ("Alpha WR", "WR"), ("Slot WR", "WR"), ("Starting TE", "TE"),
         ("Deep WR", "WR")], start=1)]
    directory = PlayerDirectory(people)
    ids = tuple(p.player_id for p in people)
    weekly = {w: {pid: {"receiving_yards": 80 + 10 * i}
                  for i, pid in enumerate(ids)} for w in (1, 2, 3, 4)}
    spec = RosterSpec(player_ids=ids, scoring="ppr", label="Your Team",
                      slots=("QB", "RB", "WR", "TE", "FLEX"))
    season = build_season(spec, weekly, directory, "2026", 5, league_size=12)
    players = player_index(directory)
    model = ProjectionModel(season, players)
    statuses = {pid: {"team": "KC", "position": players.position(pid),
                      "active": True, "injury_status": None} for pid in ids}
    availability = WeekAvailability(season="2026", week=5,
                                    snapshot_as_of="2026-w4",
                                    statuses=statuses, bye_teams=frozenset())
    return build_solo_report(spec, season, players, model, availability, 5,
                             Path("/nonexistent"))


def test_the_solo_email_names_no_opponent_anywhere() -> None:
    """The product cannot see one (PLAN §0). The header used to print
    "This week: None" — an absent value rendered as a word — and the title band
    still said "Rival Report" on a report with no rival."""
    report = _solo_report()
    html_out = render_email(report)
    assert "This week:" not in html_out
    assert "None" not in html_out
    assert "Rival Report" not in html_out
    assert "Your Report" in html_out


def test_the_two_surfaces_carry_the_same_solo_sections() -> None:
    """The renderers speak different dialects — one has CSS, the other cannot —
    so they are mirrors rather than shared code. The SECTION LIST is the thing
    that must not diverge: an email quietly missing a section the archived HTML
    carries is exactly the drift this file exists to catch."""
    import re as _re
    from render.report import TEMPLATE_PATH, render
    report = _solo_report()
    browser = render(report, TEMPLATE_PATH.read_text(encoding="utf-8"))
    email = render_email(report)

    in_browser = _re.findall(r'<span class="tag">([^<]+)</span>', browser)
    in_email = _re.findall(
        r'padding-bottom:6px;">(?:<span[^>]*>\d+</span> · )?([^<]+)</div>', email)
    assert in_browser == in_email, f"browser {in_browser} vs email {in_email}"
    # and the sections that need a league are in neither
    for gone in ("Is Fragile", "Waiver Hype Meter", "How It Ended", "The Tape"):
        assert gone not in browser and gone not in email, gone


def test_the_solo_email_stays_email_safe() -> None:
    html_out = render_email(_solo_report())
    for construct in ("display:grid", "display:flex", "var(--", "@media",
                      "fonts.googleapis", "<link", "<style"):
        assert construct not in html_out, f"email-unsafe construct: {construct}"


def test_the_preheader_is_true_of_the_report_it_previews() -> None:
    """The preheader is the preview line an inbox shows BEFORE the mail is
    opened, which makes it the most-read sentence the product ships — and the
    easiest to forget, because it is invisible in the rendered page.

    The solo version read "The file on None: your lineup, their fragile spots,
    and the one call that matters": an absent value printed as a word, plus two
    promises this product does not keep. Caught by a test asserting no report
    anywhere says "None"."""
    solo = render_email(_solo_report())
    preview = solo.split('max-height:0;overflow:hidden;">')[1].split("</div>")[0]
    assert "None" not in preview
    for absent in ("fragile", "rival", "opponent"):
        assert absent not in preview.lower(), \
            f"the inbox preview promises {absent!r}, which a solo report has not got"


def test_the_solo_subject_names_no_rival() -> None:
    """"the file on None" would be the subject line — the single most visible
    string the product produces."""
    from render.email import subject_for as _subject
    report = _solo_report()
    subject = _subject(report)
    assert "None" not in subject and "file on" not in subject
    assert str(report["meta"]["week"]) in subject


def test_the_week_one_subject_does_not_call_an_ordering_a_decision() -> None:
    """Week 1 seats players in last season's scoring order and says in its own
    body that this is 'not a forecast'. A subject reading 'your lineup,
    decided' on that body is the product overselling itself in the one line
    everybody reads — and the buyer who bought off a week-10 sample with
    percentages on it reads the gap as a broken product."""
    from render.email import subject_for as _subject
    report = _solo_report()
    for slot in report["lineup"]:
        slot["projected"] = None
        slot["confidence"] = None
    assert _subject(report) == f"Week {report['meta']['week']}: your opening lineup"
    report["lineup"][0]["projected"] = 12.3
    assert "your lineup, decided" in _subject(report)
