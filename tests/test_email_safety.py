"""What an email client will do to our HTML — checked without the clients.

Outlook renders with Word's engine, Gmail strips <style> in forwards and clips
a message over ~102 KB, Apple Mail and Outlook.com invert an email that does
not say it is light-only, and every one of them ignores flex, grid, var() and
loaded fonts. So every HTML email we send is held to what they all render:
tables for layout, inline styles, no external assets, absolute https links, a
declared colour scheme, a padded preview line, and under Gmail's clip.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from engine.final_check import Change
from render.email import render_email
from render.final_check import render_final_check
from render.roster_update import confirm_email
from render.welcome import welcome_message

FORBIDDEN = [r"<style", r"@media", r"display\s*:\s*(flex|grid)", r"var\(--",
             r"position\s*:\s*(absolute|fixed|sticky)", r"background-image",
             r"url\(", r"<link", r"<script", r"<img", r"calc\(", r"<svg",
             r"@import", r"<iframe", r"onclick"]
GMAIL_CLIP = 102 * 1024


def _report_email() -> str:
    import render.sample as sample
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    report["meta"].pop("historical_demo", None)
    report["meta"].pop("anonymized_demo", None)
    return render_email(report)


def _all_emails() -> dict[str, str]:
    out = {"report": _report_email(),
           "final check": render_final_check(
               {"week": 10, "players": {}},
               [Change("swap", "Start X at RB", "Y is out.")],
               datetime(2024, 11, 9, 16, tzinfo=timezone.utc)),
           "roster confirmation": confirm_email(
               "https://x.test/join/confirm.html?c=" + "a" * 24, ["A", "B"])[1]}
    for plan in ("season", "monthly", "league_pass", "seat"):
        out[f"welcome {plan}"] = welcome_message(
            "a@b.co", plan, "abc123", "2026",
            purchased_at="2026-09-29T12:00:00+00:00").html
    return out


@pytest.fixture(scope="module")
def emails() -> dict[str, str]:
    return _all_emails()


def test_no_email_uses_what_email_clients_cannot_render(emails) -> None:
    for name, html in emails.items():
        hits = [p for p in FORBIDDEN if re.search(p, html, re.I)]
        assert not hits, f"{name} uses {hits}"
        bare = re.findall(r'<table(?![^>]*role="presentation")', html)
        assert not bare, f"{name} has a layout table without role=presentation"


def test_every_link_is_absolute_https(emails) -> None:
    for name, html in emails.items():
        for href in re.findall(r'href="([^"]*)"', html):
            assert href.startswith("https://"), f"{name} links {href!r}"


def test_every_email_declares_it_is_light_only_and_has_a_padded_preview(emails) -> None:
    """Apple Mail and Outlook.com invert an email that doesn't say otherwise;
    and a preview line with no filler continues into the body text."""
    for name, html in emails.items():
        assert '<meta name="color-scheme" content="light only">' in html, name
        assert '<meta name="supported-color-schemes" content="light only">' in html, name
        assert "<title>" in html and 'lang="en"' in html, name
    for name in ("report", "final check", "roster confirmation"):
        assert "&#847;&zwnj;&nbsp;" in emails[name] and "mso-hide:all" in emails[name], name


def test_the_checklist_box_is_a_table_not_a_sized_div(emails) -> None:
    """Outlook's Word engine ignores a div's height and draws it a line tall."""
    for name in ("report", "final check"):
        html = emails[name]
        assert 'width="14" height="14"' in html, name
        assert not re.search(r'<div style="width:14px;height:14px', html), name


def test_a_full_report_stays_far_under_gmails_clip() -> None:
    """A message over ~102 KB is cut off with "View entire message" — losing
    the receipts and the footer with the cancel link. Measured on the largest
    roster the product accepts (30 players) with a full bench."""
    import render.sample as sample
    try:
        report = sample.build(10)
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"sample data not cached: {exc}")
    report["meta"].pop("historical_demo", None)
    template = report["bench"][0]
    report["bench"] = [dict(template, name=f"Bench Player {i}") for i in range(22)]
    size = len(render_email(report).encode("utf-8"))
    assert size < GMAIL_CLIP * 0.6, f"{size / 1024:.0f} KB is too close to Gmail's clip"
