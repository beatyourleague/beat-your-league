"""The end-of-season monthly stop (run/billing.py, D1).

Every test here names the failure it prevents, because each one was found by
reproducing that failure against a design that looked right.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from run import billing
from run.billing import (REPORTABLE, ROSTER_METADATA_KEY, STOP_METADATA_KEY,
                         WRITABLE, YEARLY, _is_ours, apply_stop, final_send,
                         last_send, needs_stop)
from run.solo import season_ends
from run.watchdog import tuesday_due_at

# The same directory run/billing.py reads. These MUST name one path: when the
# guard checked data/raw/nflverse/games.csv while the argument passed data/raw,
# the tests exercised a cache that only ever existed because they downloaded it.
CACHE = Path(__file__).resolve().parent.parent / "data" / "raw" / "nflverse"
HAVE_SCHEDULE = (CACHE / "games.csv").is_file()
needs_schedule = pytest.mark.skipif(
    not HAVE_SCHEDULE,
    reason="no cached nflverse schedule (data/ is gitignored); "
           "run `python -m ingest.pull` to populate it")

# The instant the last report a charge may pay for is due: Week 17's, Tue Dec 29
# 2026 (owner decision, Oct 31 2026; Week 18's goes out a week later, unbilled).
FINAL = datetime(2026, 12, 29, 12, 17, tzinfo=timezone.utc)
AFTER = int(FINAL.timestamp()) + 6 * 86400       # a period ending after it
BEFORE = int(FINAL.timestamp()) - 3600            # a period ending before it


def sub(period_end: int = AFTER, interval: str = "month", **over):
    """A monthly subscription of ours, in the shape Stripe returns."""
    row = {
        "id": "sub_1", "status": "active", "cancel_at": None,
        "cancel_at_period_end": False,
        "customer": {"id": "cus_1", "metadata": {ROSTER_METADATA_KEY: "r3-pc-x"}},
        "items": {"data": [{"price": {"recurring": {"interval": interval}},
                            "current_period_end": period_end}]},
    }
    row.update(over)
    return row


def yearly(**over):
    return sub(interval=YEARLY, **over)


# --------------------------------------------------------------------- #
# D1 / RULE B3 — the final paid period, and not one day before it
# --------------------------------------------------------------------- #

def test_a_period_that_ends_before_the_last_report_is_left_alone() -> None:
    """The promise that broke (LEGAL-33/34/38): a stop written months ahead
    made Stripe's billing page show the plan as already cancelled, with a
    Reactivate button and NO Cancel button, so a monthly subscriber could not
    stop November and December themselves. A period that renews into the
    month the last report falls in carries nothing, and keeps its Cancel."""
    due, notes = needs_stop([sub(period_end=BEFORE)], FINAL)
    assert due == [] and notes == [], "stamped before its final paid period"


def test_the_final_paid_period_is_ended_at_its_own_end() -> None:
    """A period ending after the last report is due is the final one: the next
    renewal would start a month with no weekly report in it."""
    due, _ = needs_stop([sub(period_end=AFTER)], FINAL)
    assert [s["id"] for s in due] == ["sub_1"]


def test_the_write_is_period_end_never_a_date_and_never_a_proration(monkeypatch) -> None:
    """`cancel_at` a few days after the season prorated a stub for days after
    the last game (LEGAL-31, EMAILS-94); `cancel_at_period_end` charges
    nothing more and refunds nothing, which is what "your last charge is the
    month the last report falls in" means."""
    seen: dict = {}

    def fake(url, key, form, what="", needs=""):
        seen.update(url=url, form=form, what=what, needs=needs)
        return {}

    monkeypatch.setattr(billing, "_stripe_post", fake)
    apply_stop("sk_test", sub())
    assert seen["form"] == {"cancel_at_period_end": "true",
                            f"metadata[{STOP_METADATA_KEY}]": str(AFTER)}
    assert "sub_1" in seen["url"]
    assert "Subscriptions" in seen["needs"], (
        "a 403 here would tell the operator to grant Customers access — the "
        "wrong permission, while the promise stays broken")


@needs_schedule
@pytest.mark.parametrize("bought", [date(2026, 9, 1), date(2026, 10, 18),
                                    date(2026, 11, 30), date(2026, 12, 29),
                                    date(2027, 1, 6)])
def test_every_billing_day_pays_through_the_last_report_and_never_after(
        bought: date) -> None:
    """The whole promise, simulated against the real 2026 calendar for every
    billing day a month has: the daily run is applied at each renewal, and
    then (a) the last charge starts a period the last report falls in, and
    (b) no charge ever starts after the last report is due. The old design
    failed (b) for billing days Jan 11-12 and its stamp failed the Cancel
    button for all of them."""
    final, season = final_send(CACHE, bought, live=False)
    assert season == "2026" and final == FINAL
    for day in range(1, 29):
        start = datetime(bought.year, bought.month, day, 9, tzinfo=timezone.utc)
        charges = [start]
        while True:
            month = charges[-1].month % 12 + 1
            year = charges[-1].year + (charges[-1].month == 12)
            end = charges[-1].replace(year=year, month=month,
                                      day=min(day, calendar.monthrange(year, month)[1]))
            due, _ = needs_stop([sub(period_end=int(end.timestamp()))], final)
            if due:
                break                            # stamped: it ends at `end`
            charges.append(end)                  # it renews
            assert len(charges) < 8, "never stopped"
        renewals = charges[1:]
        assert all(c <= final for c in renewals), (
            f"billing day {day}: a renewal on {renewals[-1]:%b %d} started a "
            f"period with no weekly report in it")
        assert end > final, f"billing day {day}: cut off before the last report"


# --------------------------------------------------------------------- #
# RULE B2 — the plan comes from the price
# --------------------------------------------------------------------- #

def test_a_yearly_subscription_is_never_given_a_stop() -> None:
    """The $39 season pass and the $99 League Pass renew yearly by design."""
    due, _notes = needs_stop([yearly(id="sub_season")], FINAL)
    assert due == []


def test_the_interval_is_read_from_the_price_not_from_our_own_plan_field() -> None:
    row = yearly(id="sub_liar")
    row["customer"]["metadata"]["byl_plan"] = "monthly"
    row["metadata"] = {"byl_plan": "monthly"}
    due, _ = needs_stop([row], FINAL)
    assert due == [], "a yearly PRICE was stopped because metadata said monthly"


def test_a_subscription_with_no_readable_interval_is_reported_not_guessed() -> None:
    row = sub(id="sub_odd", items={"data": [{"price": {}}]})
    due, notes = needs_stop([row], FINAL)
    assert due == [] and any("billing interval" in n for n in notes)


def test_a_subscription_with_no_readable_period_end_is_reported_not_guessed() -> None:
    row = sub(items={"data": [{"price": {"recurring": {"interval": "month"}}}]})
    due, notes = needs_stop([row], FINAL)
    assert due == [] and any("period end" in n for n in notes)


# --------------------------------------------------------------------- #
# RULE B4 — ours only; RULE B5 — a cancel already there is done
# --------------------------------------------------------------------- #

def test_a_subscription_that_is_not_ours_is_untouched() -> None:
    stranger = sub(id="sub_other", customer={"id": "cus_x", "metadata": {}})
    assert not _is_ours(stranger)
    assert needs_stop([stranger], FINAL)[0] == []


def test_an_unexpanded_customer_is_not_treated_as_ours() -> None:
    assert not _is_ours(sub(customer="cus_1"))


@pytest.mark.parametrize("ending", [{"cancel_at_period_end": True},
                                    {"cancel_at": AFTER - 86400}])
def test_a_cancellation_already_on_the_subscription_is_never_touched(ending) -> None:
    """Stripe's portal stores a customer's cancel as `cancel_at`; the Dashboard
    may set either. Each already ends the billing — writing over one could
    move a date the customer chose, and an hourly re-write is pointless."""
    due, notes = needs_stop([sub(**ending)], FINAL)
    assert due == [] and notes == []


# --------------------------------------------------------------------- #
# statuses
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_a_dead_subscription_is_skipped(status: str) -> None:
    assert needs_stop([sub(status=status)], FINAL)[0] == []


@pytest.mark.parametrize("status", REPORTABLE)
def test_a_paused_or_unpaid_subscription_is_said_out_loud(status: str) -> None:
    due, notes = needs_stop([sub(status=status)], FINAL)
    assert due == [] and any(status in n for n in notes)


@pytest.mark.parametrize("status", REPORTABLE)
def test_a_yearly_subscription_in_dunning_is_not_an_alarm(status: str) -> None:
    """RULE B2 outranks status: a $39 pass in `unpaid` once turned the daily
    cron red every day about a plan that must renew."""
    due, notes = needs_stop([yearly(status=status)], FINAL)
    assert due == [] and notes == []


def test_a_reportable_note_does_not_call_an_unpaid_subscription_paused() -> None:
    _due, notes = needs_stop([sub(status="unpaid")], FINAL)
    assert notes and "paused" not in notes[0]


@pytest.mark.parametrize("status", WRITABLE)
def test_every_live_status_in_its_final_period_is_stopped(status: str) -> None:
    assert len(needs_stop([sub(status=status)], FINAL)[0]) == 1


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def test_a_paused_subscription_is_not_silent_in_the_offseason_gap(
        monkeypatch, capsys) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "final_send", lambda *a, **k: (None, None))
    monkeypatch.setattr(billing, "load_subscriptions",
                        lambda key, **_: [sub(status="paused")])
    assert billing.main(["--send"]) == 1
    assert "NO SEASON TO SERVE" in capsys.readouterr().err


def test_the_gap_alarm_ignores_subscriptions_already_ending(monkeypatch, capsys) -> None:
    """After the season every monthly subscription carries its period-end stop
    (or the customer's own cancel): none of them is "billing with nothing to
    stop it", and a red cron about them is a false alarm."""
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "final_send", lambda *a, **k: (None, None))
    monkeypatch.setattr(billing, "load_subscriptions",
                        lambda key, **_: [sub(cancel_at_period_end=True)])
    assert billing.main(["--send"]) == 0, capsys.readouterr().err
    monkeypatch.setattr(billing, "load_subscriptions", lambda key, **_: [sub()])
    assert billing.main(["--send"]) == 1


def test_dry_run_is_the_default(monkeypatch, capsys) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "load_subscriptions", lambda key, **_: [sub()])
    monkeypatch.setattr(billing, "final_send", lambda *a, **k: (FINAL, "2026"))
    written: list = []
    monkeypatch.setattr(billing, "apply_stop", lambda *a, **k: written.append(a))
    assert billing.main([]) == 0
    assert written == [], "a run with no --send wrote to Stripe"
    assert "would set" in capsys.readouterr().out


def test_send_writes_only_final_periods(monkeypatch) -> None:
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "load_subscriptions",
                        lambda key, **_: [sub(id="sub_last"), sub(id="sub_more", period_end=BEFORE)])
    monkeypatch.setattr(billing, "final_send", lambda *a, **k: (FINAL, "2026"))
    written: list = []
    monkeypatch.setattr(billing, "apply_stop", lambda key, s: written.append(s["id"]))
    assert billing.main(["--send"]) == 0
    assert written == ["sub_last"]


def test_a_failed_write_exits_non_zero(monkeypatch, capsys) -> None:
    from run.subscriptions import SubscriptionError

    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "load_subscriptions", lambda key, **_: [sub()])
    monkeypatch.setattr(billing, "final_send", lambda *a, **k: (FINAL, "2026"))

    def boom(*a, **k):
        raise SubscriptionError("HTTP 403")

    monkeypatch.setattr(billing, "apply_stop", boom)
    assert billing.main(["--send"]) == 1
    assert "could not be stopped" in capsys.readouterr().err


def test_no_stripe_key_is_expected_not_an_error(monkeypatch) -> None:
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert billing.main([]) == billing.NOT_CONFIGURED


# --------------------------------------------------------------------- #
# RULE B1 — never guess a season; the calendar the stop is read from
# --------------------------------------------------------------------- #

@needs_schedule
def test_the_last_send_is_the_first_tuesday_that_mails_the_last_week() -> None:
    """Checked against every season in the archive: 4 of 28 end on a Monday,
    and 2010's final send lands two days AFTER its last game."""
    from run.solo import current_week

    ends = season_ends(CACHE, live=False)
    assert len(ends) > 20
    for season in sorted(ends):
        final = date.fromisoformat(ends[season])
        last_week = current_week(CACHE, season, final, session=None)
        send = last_send(CACHE, season, live=False)
        assert send is not None and send.weekday() == 1, f"{season}: {send}"
        assert current_week(CACHE, season, send, session=None) >= last_week
        assert current_week(CACHE, season, send - timedelta(days=7),
                            session=None) < last_week


@needs_schedule
def test_the_cutoff_is_the_tuesday_runs_due_minute() -> None:
    at, season = final_send(CACHE, date(2026, 10, 18), live=False)
    assert at == tuesday_due_at(billing.title_send(CACHE, season, live=False))


@needs_schedule
def test_the_offseason_gap_refuses_instead_of_acting() -> None:
    ends = season_ends(CACHE, live=False)
    latest = date.fromisoformat(ends[sorted(ends)[-1]])
    for days in (2, 40, 100, 160):
        assert final_send(CACHE, latest + timedelta(days=days), live=False) == (None, None)


@needs_schedule
def test_the_cutoff_belongs_to_a_season_still_to_be_played() -> None:
    ends = season_ends(CACHE, live=False)
    for season in sorted(ends)[-3:]:
        start = date.fromisoformat(ends[season]) - timedelta(days=120)
        at, chosen = final_send(CACHE, start, live=False)
        if at is not None:
            assert ends[chosen] >= start.isoformat()


def test_a_broken_schedule_fails_closed_rather_than_raising(monkeypatch) -> None:
    from ingest.nflverse import NflverseError

    def boom(*a, **k):
        raise NflverseError("cold cache")

    monkeypatch.setattr(billing, "season_ends", boom)
    assert final_send(Path("/nonexistent"), date(2026, 10, 1)) == (None, None)


def test_no_delete_call_exists_anywhere_in_the_module() -> None:
    """RULE B1, matched against the AST (a docstring SAYING never to delete is
    not a delete): DELETE /v1/subscriptions/{id} takes effect at once."""
    import ast

    tree = ast.parse(Path(billing.__file__).read_text(encoding="utf-8"))
    docstrings = {ast.get_docstring(node, clean=False)
                  for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef,
                                       ast.AsyncFunctionDef, ast.ClassDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            assert "delete" not in node.value.lower()
        if isinstance(node, ast.Attribute):
            assert "delete" not in node.attr.lower()
        if isinstance(node, ast.Name):
            assert "delete" not in node.id.lower()


def test_no_cancel_at_date_is_ever_written() -> None:
    """The months-ahead `cancel_at` is what took the Cancel button away. The
    only cancel field this module may send is `cancel_at_period_end`."""
    import ast

    tree = ast.parse(Path(billing.__file__).read_text(encoding="utf-8"))
    sent = {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.startswith("cancel_at")}
    assert sent <= {"cancel_at_period_end", "cancel_at"}
    source = Path(billing.__file__).read_text(encoding="utf-8")
    assert 'form = {"cancel_at_period_end": "true"}' in source
    assert '"cancel_at": ' not in source


def test_the_renewal_notice_skips_a_subscription_that_is_ending() -> None:
    """A subscription set to cancel is never told it will renew — Stripe's
    portal records a customer's cancel as `cancel_at`."""
    source = (Path(billing.__file__).parent / "renewals.py").read_text(encoding="utf-8")
    assert 'subscription.get("cancel_at")' in source
