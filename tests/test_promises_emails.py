"""The emails say only what the product does (promise audit, Oct 18 2026).

Each test names the EMAILS-n item it pins. Copy tests pin the true sentence
and the absence of the false one; the preseason roster-status check is a
product change and is pinned on both sides (in-season it counts, pre-season
and without the list nothing moves).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from engine.final_check import BACK, NO_FILL, SWAP, Change
from engine.preseason import build_preseason_report
from engine.roster import Player, PlayerDirectory
from engine.subscriber import RosterSpec
from render import report as rr
from render.email import TRIAL_BUTTON, TRIAL_LAST_BUTTON, _trial_cta_lines
from render.final_check import checked_line, subject_for_check
from render.preseason import FORM_BASIS, bye_none, text_summary as pre_text
from render.renewal import Renewal, renewal_day, renewal_message
from render.roster_update import LEDE, PREHEADER
from render.seat_claim import CONFIRM_LEDE, FULL_CHECK
from render.welcome import (NEXT_TUESDAY, REFUND_TERMS, REFUND_TERMS_LEAGUE,
                            duplicate_line, welcome_message)

NOW = datetime(2026, 10, 17, 16, 5, tzinfo=timezone.utc)


# ------------------------------------------------------------ final check
def _c(kind: str) -> Change:
    return Change(kind=kind, action="Start Someone at RB", detail="why")


def test_every_hole_is_counted_in_the_subject() -> None:
    """EMAILS-73/74: two empty slots read as "a hole"."""
    assert subject_for_check(6, [_c(SWAP), _c(NO_FILL), _c(NO_FILL)]) == \
        "Week 6: 1 change and 2 holes in your lineup before kickoff"
    assert subject_for_check(6, [_c(NO_FILL), _c(NO_FILL)]) == \
        "Week 6: 2 holes in your lineup before kickoff"
    assert subject_for_check(6, [_c(NO_FILL)]) == \
        "Week 6: a hole in your lineup before kickoff"
    assert "hole" not in subject_for_check(6, [_c(SWAP), _c(BACK)])


def test_the_stamp_says_when_we_checked_not_how_old_the_data_is() -> None:
    """EMAILS-77: the run's clock dated data that carries no clock."""
    line = checked_line(NOW)
    assert line.startswith("Checked Sat Oct 17, 12:05 PM ET")
    assert "latest published injury report" in line
    assert "as of" not in line


# ------------------------------------------------------------ welcome
def test_an_offseason_welcome_promises_no_report_today() -> None:
    """EMAILS-80/81/89: SeasonOver means nothing goes out until the next
    schedule exists."""
    for plan, head in (("season", "You're in"), ("seat", "Your seat is in")):
        msg = welcome_message("a@example.com", plan, "abc123def0", "2026",
                              season_over=True)
        assert msg.subject.startswith(head)
        assert "on its way" not in msg.subject
        assert "next season's schedule" in msg.subject
        assert "Today:" not in msg.text
        assert "When next season's schedule is out: Your first report" in msg.text
    live = welcome_message("a@example.com", "season", "abc123def0", "2026")
    assert live.subject == "You're in — your first report is on its way"
    assert "Today: Your first report" in live.text


def test_the_tuesday_row_says_what_a_report_is() -> None:
    """EMAILS-90: ninety seconds was the game plan; odds start in Week 4
    (Week 2 for the measured setup)."""
    assert "ninety" not in NEXT_TUESDAY.lower()
    assert "game plan at the top takes about a minute" in NEXT_TUESDAY
    assert "from Week 4" in NEXT_TUESDAY and "Week 2" in NEXT_TUESDAY


def test_the_monthly_terms_match_the_stop() -> None:
    """EMAILS-94 / D1: the last charge is the month the last report is in."""
    text = welcome_message("a@example.com", "monthly", "abc123def0", "2026").text
    assert "billing stops on its own after the season's last weekly report" in text
    assert "your last charge is for the month that report falls in" in text
    assert "when the season ends" not in text


def test_the_retained_refund_terms_carry_every_close_in_terms_5() -> None:
    """EMAILS-95/96: the season-end and late-send closes."""
    for terms in (REFUND_TERMS, REFUND_TERMS_LEAGUE):
        assert "second weekly report's week kicks off" in terms
        assert "If the season ends first" in terms
        assert "a week after your last report" in terms
        assert "reaches you late" in terms
    assert "One per person" in REFUND_TERMS and "One per league" in REFUND_TERMS_LEAGUE


def test_every_paid_cancel_route_carves_out_the_older_purchase(monkeypatch) -> None:
    """EMAILS-55/56/101/117 / D3: the billing page opens only the newest
    purchase, and every route says what to do about the older one."""
    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.example/p")
    for plan in ("season", "monthly", "league_pass"):
        msg = welcome_message("a@example.com", plan, "abc123def0", "2026")
        for doc in (msg.html, msg.text):
            assert rr.TWO_PURCHASES.replace("'", "&#x27;") in doc or \
                rr.TWO_PURCHASES in doc, plan
    assert rr.TWO_PURCHASES in rr.CANCEL_BODY and rr.TWO_PURCHASES in rr.CANCEL_TEXT
    note = renewal_message(Renewal(email="a@example.com", amount="$39.00 USD",
                                   renews_on=date(2027, 10, 16), interval="year",
                                   plan="season"))
    assert rr.TWO_PURCHASES in note.text
    seat = welcome_message("a@example.com", "seat", "abc123def0", "2026")
    assert rr.TWO_PURCHASES not in seat.text, "a seat has nothing to cancel"


def test_without_any_route_configured_the_welcome_names_the_page(monkeypatch) -> None:
    """EMAILS-102."""
    monkeypatch.delenv("BILLING_PORTAL_URL", raising=False)
    monkeypatch.delenv("SITE_URL", raising=False)
    text = welcome_message("a@example.com", "season", "abc123def0", "2026").text
    assert "beatyourleague.com/terms.html#cancel" in text


def test_the_pass_welcome_offers_no_seat_route_that_cannot_work(monkeypatch) -> None:
    """EMAILS-106/107: without a signed link no claim can be confirmed."""
    for site in ("https://example.com", ""):
        monkeypatch.setenv("SITE_URL", site)
        msg = welcome_message("a@example.com", "league_pass", "abc123def0", "2026")
        for doc in (msg.html, msg.text):
            assert "?pass=1" not in doc
            assert "email you paid with" not in doc
            assert "signup link" not in doc
            assert re.search(r"seat link isn(?:'|&#x27;)t ready yet", doc)


def test_the_older_purchase_cancels_by_reply_the_spare_on_the_billing_page(
        monkeypatch) -> None:
    """EMAILS-109/110/111 / D1 / D3."""
    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.example/p")
    older = welcome_message("a@example.com", "league_pass", "abc123def0", "2026",
                            duplicate="season")
    assert "shows only your newest purchase" in older.text
    assert "reply to this email and we'll do it for you" in older.text
    assert "Where to cancel" not in older.text
    monthly = duplicate_line("league_pass", "monthly")
    assert "season's last weekly report" in monthly
    spare = welcome_message("a@example.com", "monthly", "abc123def0", "2026",
                            duplicate="pass")
    assert "Where to cancel: your billing page: https://billing.example/p" in spare.text
    assert "season's last weekly report goes out" in spare.text


def test_the_reply_route_is_offered_only_where_it_can_be_applied(monkeypatch) -> None:
    """EMAILS-45: an emailed roster is applied by `make roster-update`, which
    needs UPDATE_SECRET and FORM_ENDPOINT."""
    meta = {"solo": True, "update_url": None, "roster_as_of": "2026-10-03",
            "plan": "season", "season": "2026", "week": 6, "last_week": 18}
    for name in ("UPDATE_SECRET", "FORM_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    assert "Reply" not in rr.update_line(meta)
    assert not any("Reply" in line for line in rr.update_lines(meta))
    assert "Reply" not in welcome_message("a@example.com", "season", "abc123def0",
                                          "2026").text
    monkeypatch.setenv("UPDATE_SECRET", "s")
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    assert "Reply to this email" in rr.update_line(meta)
    assert "reply to any report" in welcome_message("a@example.com", "season",
                                                    "abc123def0", "2026").text


def test_the_update_deadline_is_one_the_pipeline_meets() -> None:
    """EMAILS-43/44: two hourly intakes before Saturday's 16:17 UTC check."""
    for body in (rr.UPDATE_BODY, rr.UPDATE_BODY_LAST):
        assert "by Friday night (ET)" in body
        assert "Saturday morning" not in body


# ------------------------------------------------------------ season end
def _end(**meta):
    base = {"solo": True, "week": 18, "last_week": 18, "season": "2026"}
    return rr.season_end_lines({**base, **meta})


def test_a_free_report_is_never_promised_a_tuesday_report() -> None:
    """EMAILS-58."""
    [line] = _end(week=17, trial=True)
    assert "next Tuesday" not in line and "subscribers get a report" in line
    [paid] = _end(week=17, plan="season")
    assert "next Tuesday's report covers it" in paid


def test_the_last_report_asks_for_next_seasons_roster_where_it_can() -> None:
    """EMAILS-62 / D8: Week 1 is built from the roster on file."""
    url = "https://example.com/join/?update=1"
    for plan in ("season", rr.PASS_PLAN):
        assert rr.NEW_ROSTER in " ".join(_end(plan=plan, update_url=url)), plan
        assert rr.NEW_ROSTER not in " ".join(_end(plan=plan)), plan
    monthly = " ".join(_end(plan="monthly", update_url=url))
    assert "last paid month" in monthly and rr.NEW_ROSTER not in monthly


def test_the_seeded_line_does_not_say_last_season_stops_counting_at_week_4() -> None:
    """EMAILS-27: the anchor counts it in weeks 4-16."""
    assert "stand on this season alone" not in rr.SEEDED_SECTION_LINE
    assert "From Week 4 it counts for less" in rr.SEEDED_SECTION_LINE
    assert "from Week 17 this season stands alone" in rr.SEEDED_SECTION_LINE


def test_the_last_weeks_free_report_asks_about_next_season(monkeypatch) -> None:
    """EMAILS-69: no next Tuesday's report after the last week."""
    monkeypatch.setenv("SITE_URL", "https://example.com")
    last = "\n".join(_trial_cta_lines({"week": 18, "last_week": 18}))
    assert TRIAL_BUTTON not in last and TRIAL_LAST_BUTTON in last
    assert "https://example.com/?via=trial#watch-form" in last
    mid = "\n".join(_trial_cta_lines({"week": 17, "last_week": 18}))
    assert f"{TRIAL_BUTTON}: https://example.com/join/?via=trial" in mid


# ------------------------------------------------------------ renewal
def test_the_renewal_date_is_on_the_buyers_clock() -> None:
    """EMAILS-112-117: 01:30 UTC Oct 17 is 9:30 PM ET Oct 16."""
    end = int(datetime(2027, 10, 17, 1, 30, tzinfo=timezone.utc).timestamp())
    assert renewal_day(end) == date(2027, 10, 16)
    noon = int(datetime(2027, 10, 17, 16, 0, tzinfo=timezone.utc).timestamp())
    assert renewal_day(noon) == date(2027, 10, 17)


# ------------------------------------------------------------ seats, updates
def test_the_seat_notes_point_at_a_remedy_and_hedge_the_hour() -> None:
    """EMAILS-144 / D10, EMAILS-146 / D19."""
    assert "hello@beatyourleague.com" in FULL_CHECK and "free a seat" in FULL_CHECK
    assert "usually within the hour" in CONFIRM_LEDE


def test_the_roster_change_email_never_says_the_reader_asked() -> None:
    """EMAILS-151/152."""
    assert "you asked" not in PREHEADER.lower()
    assert "Nothing changes unless you confirm it" in PREHEADER
    assert "within 7 days" in LEDE and "usually within the hour" in LEDE
    assert "newest change you confirm is the one that counts" in LEDE


# ------------------------------------------------------------ roster report
SLOTS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")
ROSTER = [
    Player("p-qb", "Ace Passer", "QB", "BAL"),
    Player("p-qb2", "Back Passer", "QB", "KC"),
    Player("p-rb1", "Bruiser One", "RB", "LA"),
    Player("p-rb2", "Bruiser Two", "RB", "NYG"),
    Player("p-rb3", "Bruiser Three", "RB", "MIA"),
    Player("p-wr1", "Speedy One", "WR", "MIN"),
    Player("p-wr2", "Speedy Two", "WR", "SEA"),
    Player("p-wr3", "Speedy Three", "WR", "DAL"),
    Player("p-te", "Sure Hands", "TE", "LV"),
    Player("p-te2", "Spare Hands", "TE", "PHI"),
    Player("p-k", "Toe Punter", "K", "NO"),
    Player("DEF-CLE", "Cleveland Browns", "DEF", "CLE"),
]
BYES = {"BAL": 7, "KC": 10, "LA": 11, "NYG": 8, "MIA": 12, "MIN": 6, "SEA": 9,
        "DAL": 10, "LV": 13, "PHI": 9, "NO": 8, "CLE": 11}
OUT = {"p-te2": "on injured reserve"}


def _roster_report(tmp_path, *, started=True, out=OUT):
    spec = RosterSpec(player_ids=tuple(p.player_id for p in ROSTER), slots=SLOTS,
                      scoring="ppr", label="Your Team")
    return build_preseason_report(spec, PlayerDirectory(list(ROSTER)), {}, "2026",
                                  tmp_path, season_started=started, byes=BYES,
                                  from_week=6 if started else None,
                                  roster_out=out)


def test_a_reserve_list_backup_is_not_cover_in_season(tmp_path) -> None:
    """EMAILS-119/126/128/130: the injured-reserve TE covered the starter's
    bye and the one-deep list; the weekly report shows him OUT."""
    report = _roster_report(tmp_path)
    w13 = [hit for hit in report["collisions"] if hit["week"] == 13]
    assert w13 and w13[0]["slots"] == ["TE"]
    assert w13[0]["out"] == ["Spare Hands (on injured reserve)"]
    [te] = [spot for spot in report["thin"] if spot["slot"] == "TE"]
    assert te["players"] == ["Sure Hands"] and te["have"] == 1
    assert te["out"] == ["Spare Hands (on injured reserve)"]
    text = pre_text(report)
    assert "out today: Spare Hands (on injured reserve)" in text
    assert "injured reserve, suspended or released today" in text
    assert "1 week ahead" in text or "one week ahead" in text or "Week 13" in text


def test_the_reserve_list_never_reaches_a_pre_season_report(tmp_path) -> None:
    """Today's list says nothing about a week months away (principle 3), and
    with no list passed nothing moves."""
    for report in (_roster_report(tmp_path, started=False),
                   _roster_report(tmp_path, out=None)):
        assert not any(hit["week"] == 13 for hit in report["collisions"])
        assert not any(spot["slot"] == "TE" for spot in report["thin"])
        assert "today doesn't count" not in pre_text(report)
    pre = _roster_report(tmp_path, started=False)
    assert bye_none(pre["meta"]).endswith("who plays that position.")


def test_the_form_basis_names_the_scoring_picked() -> None:
    """EMAILS-131: one of three presets, not the league's own settings."""
    assert "the scoring you picked" in FORM_BASIS
    assert "league's own settings" not in FORM_BASIS
