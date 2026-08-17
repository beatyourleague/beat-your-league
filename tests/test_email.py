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
from render.report import CANCEL_BODY, CANCEL_HEAD, NO_BETTING_LINE


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
    if any(s.get("edge") is not None for s in report.get("lineup", [])):
        assert "on our numbers vs" in email_html, "email dropped the point gap"
    # the sentence that used to exist in three diverging copies
    if "of the other" in browser_html:
        assert "of the other" in email_html, \
            "the who-can-cover denominator drifted between surfaces"
