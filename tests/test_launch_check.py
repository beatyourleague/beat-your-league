"""`make launch-check` (run/launch_check.py): the gates catch what they claim to.

A readiness check that reports PASS over a broken funnel is worse than none,
because it is the thing the owner reads on launch morning. Each test copies
site/ to a temp folder, breaks one thing on purpose, and requires the gate
that owns it to say so — then requires the real tree to raise no FAIL.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import run.launch_check as lc

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def site(tmp_path, monkeypatch):
    copy = tmp_path / "site"
    shutil.copytree(REPO / "site", copy)
    monkeypatch.setattr(lc, "SITE", copy)
    return copy


def _status(gates, name_part):
    hits = [g for g in gates if name_part.lower() in g.name.lower()]
    assert hits, f"no gate named like {name_part!r}: {[g.name for g in gates]}"
    return hits[0].status


def test_selling_a_closed_checkout_fails(site) -> None:
    page = site / "index.html"
    page.write_text(page.read_text().replace("const CHECKOUT_OPEN = false;",
                                             "const CHECKOUT_OPEN = true;"))
    gates = lc.check_funnel_config()
    assert _status(gates, "never sells a checkout") == "FAIL"
    assert _status(gates, "agree on whether checkout is open") == "FAIL"


def test_a_free_report_button_with_nowhere_to_post_fails(site) -> None:
    page = site / "index.html"
    page.write_text(page.read_text().replace("const TRIAL_OPEN = false;",
                                             "const TRIAL_OPEN = true;"))
    assert _status(lc.check_funnel_config(), "free-report button") == "FAIL"


def test_a_banned_word_or_betting_word_on_a_selling_page_fails(site) -> None:
    page = site / "league-pass.html"
    page.write_text(page.read_text().replace("<h2>Fair play</h2>",
                                             "<h2>Fair play, proven</h2><p>no sportsbook</p>"))
    gates = lc.check_selling_copy()
    assert _status(gates, "banned claim words") == "FAIL"
    assert _status(gates, "betting language") == "FAIL"


def test_a_one_click_cancel_claim_in_the_terms_fails(site) -> None:
    """Reproduction (launch audit C2, Oct 15 2026): terms §3 still said
    "cancelling takes one / click from your billing page" — hand-wrapped
    across two lines — after §4 and every other surface had moved to the real
    flow (an emailed link, about a minute). The gate read only the selling
    pages, so the retired claim survived in the operative contract."""
    page = site / "terms.html"
    text = page.read_text(encoding="utf-8")
    fixed = "you can cancel\n      yourself from your billing page in about a minute (section 4)."
    assert fixed in text
    page.write_text(text.replace(
        fixed, "cancelling takes one\n      click from your billing page."))
    assert _status(lc.check_selling_copy(), "audit retired") == "FAIL"
    # Either order, any phrasing in between, and on the privacy page too.
    page.write_text(text)
    privacy = site / "privacy.html"
    privacy.write_text(privacy.read_text(encoding="utf-8").replace(
        "</main>", "<p>One-click   cancelling, whenever you like.</p></main>"))
    assert _status(lc.check_selling_copy(), "audit retired") == "FAIL"


def test_one_click_that_is_not_about_cancelling_is_not_a_retired_claim(site) -> None:
    """"Our terms are always one click away" is true and says nothing about
    leaving; the gate is about the cancel flow, not the phrase."""
    page = site / "terms.html"
    page.write_text(page.read_text(encoding="utf-8").replace(
        "</main>", "<p>This page is always one click away.</p></main>"))
    assert _status(lc.check_selling_copy(), "audit retired") == "PASS"


def test_a_broken_link_and_a_bad_anchor_fail(site) -> None:
    page = site / "how-it-works.html"
    page.write_text(page.read_text().replace(
        "</main>", '<a href="nowhere.html">x</a><a href="terms.html#no-such-id">y</a></main>', 1))
    gate = lc.check_links()[0]
    assert gate.status == "FAIL"
    assert "nowhere.html" in gate.detail and "no-such-id" in gate.detail


def test_a_price_that_disagrees_with_the_welcome_email_fails(site) -> None:
    page = site / "league-pass.html"
    page.write_text(page.read_text().replace('class="amt">$99', 'class="amt">$89'))
    assert lc.check_prices()[0].status == "FAIL"


def test_a_personal_address_anywhere_fails(site) -> None:
    page = site / "privacy.html"
    page.write_text(page.read_text().replace("</body>", "someone@gmail.com</body>"))
    assert _status(lc.check_selling_copy(), "personal email") == "FAIL"


def test_a_script_that_does_not_parse_fails(site) -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    page = site / "index.html"
    page.write_text(page.read_text().replace("const CHECKOUT_OPEN = false;",
                                             "const CHECKOUT_OPEN = = false;"))
    assert _status(lc.check_scripts(), "script parses") == "FAIL"


def test_the_real_tree_raises_no_failure() -> None:
    """The static gates over the committed site: a FAIL here is a launch bug."""
    gates = (lc.check_links() + lc.check_page_basics() + lc.check_scripts()
             + lc.check_selling_copy() + lc.check_prices() + lc.check_funnel_config()
             + lc.check_compliance())
    failing = [f"{g.name}: {g.detail}" for g in gates if g.status == "FAIL"]
    assert not failing, failing


def test_the_report_reads_and_the_verdict_follows_the_gates() -> None:
    gates = [lc.Gate("Site", "a", "PASS"), lc.Gate("Owner", "b", "OWNER", "do it")]
    assert "waiting on owner setup" in lc.render(gates)
    gates.append(lc.Gate("Site", "c", "FAIL", "broken"))
    assert "fix the failures" in lc.render(gates)
    assert "READY" in lc.render([lc.Gate("Site", "a", "PASS")]).splitlines()[-1]
