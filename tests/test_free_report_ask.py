"""The free report's ask (Nov 4 2026): its buy links carry the reader's own
roster, its button says what it starts, its subject and masthead name the
team, the refund sits beside the button, and three lines that stay OFF until
the owner sets SENDER_POSTAL_ADDRESS. Plus `make stats`' paid-by-channel line.
"""

from __future__ import annotations

import copy
import html
import re
from datetime import datetime, timedelta, timezone

import pytest

import render.email as em
import render.report as rr
from render.email import (TRIAL_BUTTON, TRIAL_ONLY, TRIAL_REFUND, render_email,
                          text_summary, trial_join_url, trial_subject)
from run.refs import MONTHLY, decode_roster, encode_roster, split_via

SITE = "https://example.com"
SENDER = "PO Box 1, Testville"


def _trial(**meta) -> dict:
    from test_presentation import _subscriber
    report = _subscriber(trial=True)
    report["meta"].update(meta)
    return report


def _ask_box(page: str) -> str:
    """The free report's ask box: from its head to the end of its table."""
    start = page.index(html.escape(em.TRIAL_ASK_HEAD, quote=True))
    return page[start:page.index("</table></td></tr>", page.index(
        html.escape(TRIAL_ONLY, quote=True), start))]


# ------------------------------------------------------------ item 1: links

def test_the_buy_links_carry_the_requested_roster_as_a_monthly_ref(
        tmp_path, monkeypatch, capsys) -> None:
    """Reproduction: both buy links were SITE/join/?via=trial, so a reader who
    pressed them pasted their roster again, and the post that brought them
    was lost. Now each opens join/ on the roster the free report was built
    from, as a MONTHLY ref (so the $14.99 click never lands on another
    plan's card) tagged with the request's own channel — inside the ref,
    never as a URL ?via= (the join page reads that first and it would
    overwrite the tag). Never try=1, never an address."""
    from test_trials import THURSDAY, _drive, _fixture_ref, _row
    monkeypatch.setenv("SITE_URL", SITE)
    asked = decode_roster(_fixture_ref())
    tagged = dict(_row("fan@fans.mail", ref=_fixture_ref()), via="reddit-oct28")
    plain = _row("other@fans.mail", ref=_fixture_ref())
    junk = dict(_row("third@fans.mail", ref=_fixture_ref()), via="Not A Tag!")
    code, out, err, mailed = _drive(tmp_path, monkeypatch, capsys,
                                    rows=[tagged, plain, junk], now=THURSDAY)
    assert code == 0, (out, err)
    by_to = {m.to: m for m in mailed}
    for to, tag in (("fan@fans.mail", "reddit-oct28"), ("other@fans.mail", "trial"),
                    ("third@fans.mail", "trial")):
        message = by_to[to]
        links = set(re.findall(r'href="([^"]*/join/[^"]*)"', message.html))
        links |= set(re.findall(r"(https://\S*/join/\S*)", message.text))
        assert links, to
        for link in links:
            link = html.unescape(link)
            assert link.startswith(f"{SITE}/join/?ref="), link
            assert "via=" not in link.split("?", 1)[1].split("ref=", 1)[0], link
            assert "&" not in link and "try=1" not in link and "@" not in link, link
            back = decode_roster(link.split("ref=", 1)[1])
            assert back.plan == MONTHLY
            assert back.via == tag, (to, link)
            assert (back.player_ids, back.slots, back.scoring, back.league_size,
                    back.league_type) == (asked.player_ids, asked.slots, asked.scoring,
                                          asked.league_size, asked.league_type)
        # Both places: the price line at the top and the button.
        assert message.html.count(f'href="{SITE}/join/?ref=') == 2
        assert f"{TRIAL_BUTTON}: {SITE}/join/?ref=" in message.text


def test_a_tag_that_would_overflow_stripes_limit_is_dropped_never_the_roster() -> None:
    from run.trials import trial_ref
    ids = [f"00-00{n:05d}" for n in range(1, 41)]                 # 40 players
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    roster = decode_roster(encode_roster("season", "ppr", slots, ids))
    ref = trial_ref(roster, "a" * 24)
    assert len(f"{ref}_via-{'a' * 24}") > 200
    back = decode_roster(ref)
    assert back.player_ids == tuple(ids) and back.plan == MONTHLY
    assert split_via(ref)[1] is None
    # A short tag still fits, and an unusable one becomes "trial".
    small = decode_roster(encode_roster("season", "ppr", ["QB"], ids[:5]))
    assert decode_roster(trial_ref(small, "x")).via == "x"
    assert decode_roster(trial_ref(small, "BAD TAG")).via == "trial"


def test_the_link_without_a_ref_and_in_the_last_week_is_as_before(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", SITE)
    assert trial_join_url({"week": 9}) == f"{SITE}/join/?via=trial"
    assert trial_join_url({"week": 9, "trial_ref": "not a ref!"}) == f"{SITE}/join/?via=trial"
    ref = encode_roster("monthly", "ppr", ["QB"], ["00-0000001"], via="trial")
    assert trial_join_url({"week": 9, "trial_ref": ref}) == f"{SITE}/join/?ref={ref}"
    assert trial_join_url({"week": 18, "last_week": 18, "trial_ref": ref}) == \
        f"{SITE}/?via=trial#watch-form"


# ------------------------------------------------------------ item 2: button

def test_the_button_says_what_it_starts() -> None:
    """Reproduction: "Get next Wednesday's report" was false on a Wednesday,
    when a buyer before kickoff gets THIS week's report."""
    assert TRIAL_BUTTON == "Start my plan"
    assert "next" not in TRIAL_BUTTON.lower()


# ------------------------------------------------- item 3: subject, masthead

def test_the_subject_and_masthead_name_the_team(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", SITE)
    report = _trial()
    lead = report["meta"]["team_lead"]
    assert trial_subject(report) == f"Your free report: Week {report['meta']['week']}, {lead}'s team"
    page = html.unescape(render_email(report))
    assert f"{lead}'s team</b> · 12 teams" in page
    assert f"{lead}'s team · 12 teams" in text_summary(report)
    no_lead = copy.deepcopy(report)
    no_lead["meta"].pop("team_lead")
    assert trial_subject(no_lead) == f"Your free report: Week {report['meta']['week']}"
    # The subscriber-only chrome stays off a free report.
    assert not rr.is_subscriber_report(report["meta"])
    for absent in ("Roster changed?", "ROSTER CHANGED?", "billing page"):
        assert absent not in page and absent not in text_summary(report)


def test_the_hourly_run_mails_the_named_subject(tmp_path, monkeypatch, capsys) -> None:
    from test_trials import THURSDAY, _drive, _fixture_ref, _row
    code, out, err, mailed = _drive(tmp_path, monkeypatch, capsys,
                                    rows=[_row("fan@fans.mail", ref=_fixture_ref())],
                                    now=THURSDAY)
    assert code == 0 and len(mailed) == 1, (out, err)
    assert re.fullmatch(r"Your free report: Week \d+, .+'s team", mailed[0].subject), \
        mailed[0].subject


def test_a_free_report_carries_the_glossary_link(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", SITE)
    report = _trial()
    assert f"{SITE}/how-it-works.html#read" in render_email(report)
    assert f"{SITE}/how-it-works.html#read" in text_summary(report)
    # Never on a sample.
    sample = _trial(historical_demo=True)
    assert rr.read_line(sample["meta"]) == "" and rr.read_lines(sample["meta"]) == []


# ------------------------------------------------------ item 4: refund order

def test_the_refund_sits_between_the_button_and_the_only_email_promise(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", SITE)
    report = _trial()
    box = _ask_box(render_email(report))
    button = box.index(html.escape(TRIAL_BUTTON))
    refund = box.index(html.escape(TRIAL_REFUND, quote=True))
    only = box.index(html.escape(TRIAL_ONLY, quote=True))
    assert button < refund < only
    # TRIAL_ONLY is its own block, word for word.
    assert re.search(r'<div style="[^"]*">' + re.escape(html.escape(TRIAL_ONLY, quote=True))
                     + "</div>", box)
    text = text_summary(report)
    ask = text[text.index(em.TRIAL_ASK_HEAD.upper()):]
    lines = ask.splitlines()
    assert lines.index(TRIAL_REFUND) == lines.index(TRIAL_ONLY) - 1
    assert lines[lines.index(TRIAL_REFUND) - 1].startswith(f"{TRIAL_BUTTON}: ")
    # The season's last week sells nothing, so no refund line in its ask.
    last = _trial(week=18, last_week=18)
    assert TRIAL_REFUND not in "\n".join(em._trial_cta_lines(last["meta"], last))
    assert TRIAL_ONLY in "\n".join(em._trial_cta_lines(last["meta"], last))


# ---------------------------------------------- item 5: off without a sender

def _with_everything(**meta) -> dict:
    report = _trial(**meta)
    report["meta"]["first_kickoff"] = (datetime.now(timezone.utc)
                                       + timedelta(days=2)).isoformat()
    report["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["byes_ahead"] = [{"week": 15, "slots": ["TE"], "players": ["Starting TE"]}]
    report["pivots"] = [{"condition": "Bell Cow is cleared", "action": "Start him at RB",
                         "saturday": True, "about": "00-0000002"}]
    return report


def _docs(report: dict) -> tuple[str, str]:
    return html.unescape(render_email(report)), text_summary(report)


EXTRAS = ("Join well before", "this week's report usually comes too",
          rr.TRIAL_SATURDAY_NOTE, "bye above stays on every Wednesday report")


def test_with_no_sender_address_the_ask_is_todays(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", SITE)
    monkeypatch.delenv("SENDER_POSTAL_ADDRESS", raising=False)
    for doc in _docs(_with_everything()):
        for extra in EXTRAS:
            assert extra not in doc, extra
        assert em.TRIAL_ASK in doc
        assert rr.SATURDAY_FOLLOWUP not in doc


def test_with_a_sender_address_the_three_lines_appear_on_both_halves(monkeypatch) -> None:
    monkeypatch.setenv("SITE_URL", SITE)
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", SENDER)
    report = _with_everything()
    page, text = _docs(report)
    line = em.trial_this_week_line(report["meta"])
    assert re.fullmatch(r"Join well before the \w{3} \w{3} \d{1,2} · \d{1,2}:\d\d [AP]M ET "
                        r"kickoff and this week's report usually comes too\.", line), line
    byes = "The Week 15 bye above stays on every Wednesday report until it's covered."
    for doc in (page, text):
        assert line in doc
        assert rr.TRIAL_SATURDAY_NOTE in doc
        assert byes in doc
        assert em.TRIAL_ASK not in doc         # the ask points at their team instead
        # Never about this reader's row, never a promise to email them.
        assert rr.SATURDAY_FOLLOWUP not in doc
    for word in ("we'll email", "plans around", "handles"):
        assert word not in byes + rr.TRIAL_SATURDAY_NOTE + line
    # The Saturday sentence sits in the game plan, the bye ask in the ask box.
    assert text.index("YOUR GAME PLAN") < text.index(rr.TRIAL_SATURDAY_NOTE) \
        < text.index("IF/THEN FOR GAMEDAY")
    assert byes in html.unescape(_ask_box(render_email(report)))
    # Two byes ahead.
    report["byes_ahead"].append({"week": 12})
    assert em.trial_byes_ask(report) == ("The Week 12 and Week 15 byes above stay on every "
                                         "Wednesday report until they're covered.")


def test_the_this_week_line_needs_a_week_not_yet_kicked_off(monkeypatch) -> None:
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", SENDER)
    report = _with_everything()
    meta = report["meta"]
    assert em.trial_this_week_line(meta)
    # Built at or after the first kickoff: no line.
    meta["generated_at"] = meta["first_kickoff"]
    assert em.trial_this_week_line(meta) is None
    # No kickoff on the report, or the season's last week: no line.
    meta = _with_everything()["meta"]
    assert em.trial_this_week_line(dict(meta, first_kickoff=None)) is None
    assert em.trial_this_week_line(dict(meta, week=18, last_week=18)) is None
    # Formatted on the buyer's clock: 01:15 UTC Friday is 8:15 PM ET Thursday.
    nov = dict(meta, first_kickoff="2026-11-06T01:15:00+00:00",
               generated_at="2026-11-04T23:00:00+00:00")
    assert em.trial_this_week_line(nov) == (
        "Join well before the Thu Nov 5 · 8:15 PM ET kickoff and this week's report "
        "usually comes too.")


def test_the_this_week_line_prints_the_kickoff_on_the_reports_own_clock(monkeypatch) -> None:
    """Review: the line had a formatter of its own ("Thu Nov 5, 8:15 PM ET")
    beside render.report.eastern ("Thu Nov 5 · 8:15 PM ET"), the clock every
    kickoff in the report is printed in. One clock, one format."""
    from datetime import datetime
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", SENDER)
    meta = dict(_with_everything()["meta"], first_kickoff="2026-11-06T01:15:00+00:00",
                generated_at="2026-11-04T23:00:00+00:00")
    stamp = rr.eastern(datetime.fromisoformat(meta["first_kickoff"]))
    assert em.trial_this_week_line(meta) == em.TRIAL_THIS_WEEK.format(kickoff=stamp)


def test_the_saturday_sentence_promises_no_more_than_the_check_does() -> None:
    """Review: "every lineup is checked again on Saturday" was untrue of a
    buyer with no stored plan (joined after Wednesday's send) and of a week
    whose injury reports aren't in, when the check refuses. It says what the
    landing FAQ already promises, in its words."""
    note = rr.TRIAL_SATURDAY_NOTE.lower()
    assert "every" not in note
    assert "saturday check" in note and "friday's final injury" in note
    assert "tells you if" in note


def test_the_saturday_sentence_needs_a_plan_that_waits_on_saturday(monkeypatch) -> None:
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", SENDER)
    report = _with_everything()
    assert rr.trial_saturday_note(report) == rr.TRIAL_SATURDAY_NOTE
    report["pivots"][0]["saturday"] = False
    assert rr.trial_saturday_note(report) is None
    # Never on a subscriber's report, which has its own standing line.
    sub = _with_everything()
    sub["meta"].pop("trial")
    assert rr.trial_saturday_note(sub) is None
    # And no bye ask without a bye ahead.
    none = _with_everything()
    none["byes_ahead"] = []
    assert em.trial_byes_ask(none) is None


def test_the_run_puts_the_first_kickoff_on_the_report(tmp_path, monkeypatch, capsys) -> None:
    from test_trials import THURSDAY, _drive, _fixture_ref, _row
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", SENDER)
    code, out, err, mailed = _drive(tmp_path, monkeypatch, capsys,
                                    rows=[_row("fan@fans.mail", ref=_fixture_ref())],
                                    now=THURSDAY)
    assert code == 0 and mailed, (out, err)
    # _drive's week kicks off 2099-01-01 00:00 UTC: 7:00 PM ET on Dec 31.
    assert "Join well before the Wed Dec 31 · 7:00 PM ET kickoff" in mailed[0].text


# ------------------------------------------- make stats: channels grouped

def test_paid_signups_by_channel_group_a_posts_tag_under_its_channel() -> None:
    import run.stats as stats
    ref = encode_roster("monthly", "ppr", ["QB"], ["00-0000001"])

    def session(i, via):
        tagged = ref if via is None else encode_roster("monthly", "ppr", ["QB"],
                                                       ["00-0000001"], via=via)
        return {"id": f"cs_{i}", "status": "complete", "payment_status": "paid",
                "mode": "subscription", "client_reference_id": tagged}
    line = stats._paid_by_channel_line([session(1, "reddit-oct28"), session(2, "reddit"),
                                        session(3, "x-nov1"), session(4, None)])
    assert line == "  Paid signups by channel (ever): reddit 2, x 1, (no tag) 1"


if __name__ == "__main__":                                  # pragma: no cover
    pytest.main([__file__])
