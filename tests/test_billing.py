"""The offseason billing stop (run/billing.py).

Every test here names the failure it prevents, because each one was found by
reproducing that failure against a design that looked right.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from run import billing
from run.billing import (REPORTABLE, RETRY_DAYS, ROSTER_METADATA_KEY,
                         STOP_METADATA_KEY, WRITABLE, YEARLY, _interval,
                         _is_ours, apply_stop, last_send, needs_stop, stop_for)
from run.solo import season_ends

# The same directory run/billing.py reads. These MUST name one path: when the
# guard checked data/raw/nflverse/games.csv while the argument passed data/raw,
# the tests exercised a cache that only ever existed because they downloaded it.
CACHE = Path(__file__).resolve().parent.parent / "data" / "raw" / "nflverse"
HAVE_SCHEDULE = (CACHE / "games.csv").is_file()
needs_schedule = pytest.mark.skipif(
    not HAVE_SCHEDULE,
    reason="no cached nflverse schedule (data/ is gitignored); "
           "run `python -m ingest.pull` to populate it")


def sub(**over):
    """A monthly subscription of ours, in the shape Stripe returns."""
    row = {
        "id": "sub_1", "status": "active", "cancel_at": None,
        "cancel_at_period_end": False,
        "customer": {"id": "cus_1", "metadata": {ROSTER_METADATA_KEY: "r3-pc-x"}},
        "items": {"data": [{"price": {"recurring": {"interval": "month"}},
                            "current_period_end": 2000000000}]},
    }
    row.update(over)
    return row


def yearly(**over):
    return sub(items={"data": [{"price": {"recurring": {"interval": YEARLY}},
                                "current_period_end": 2000000000}]}, **over)


AT = datetime(2027, 1, 13, tzinfo=timezone.utc)


# --------------------------------------------------------------------- #
# RULE B2 — the plan comes from the price
# --------------------------------------------------------------------- #

def test_a_yearly_subscription_is_never_given_a_stop_date() -> None:
    """The $39 season pass and the $99 League Pass renew yearly by design.

    Cancelling one would end a subscription the buyer expects to continue and
    cannot be undone. The interval comes off the subscription's own price, never
    off our `plan` field: a ref's prefix is a claim, and STRIPE_PAYMENT_LINKS
    exists precisely because claims are not facts.
    """
    due, _notes = needs_stop([yearly(id="sub_season")], AT)
    assert due == []


def test_the_interval_is_read_from_the_price_not_from_our_own_plan_field() -> None:
    """Mutation guard: a subscription whose METADATA claims monthly but whose
    price is yearly must still be left alone. Reading the claim would cancel a
    season pass on the strength of a string we wrote ourselves."""
    row = yearly(id="sub_liar")
    row["customer"]["metadata"]["byl_plan"] = "monthly"
    row["metadata"] = {"byl_plan": "monthly"}
    due, _ = needs_stop([row], AT)
    assert due == [], "a yearly PRICE was cancelled because metadata said monthly"


def test_a_subscription_with_no_readable_interval_is_reported_not_guessed() -> None:
    row = sub(id="sub_odd", items={"data": [{"price": {}}]})
    due, notes = needs_stop([row], AT)
    assert due == []
    assert any("billing interval" in n for n in notes)


# --------------------------------------------------------------------- #
# RULE B4 — ours only
# --------------------------------------------------------------------- #

def test_a_subscription_that_is_not_ours_is_untouched() -> None:
    """The sweep walks every subscription on the Stripe account, not every
    subscriber of this product. Without the roster stamp it would attach a
    season-end cancel date to anything else ever sold from the same account."""
    stranger = sub(id="sub_other", customer={"id": "cus_x", "metadata": {}})
    assert not _is_ours(stranger)
    assert needs_stop([stranger], AT)[0] == []


def test_an_unexpanded_customer_is_not_treated_as_ours() -> None:
    """Fails closed. If the expand ever stops working the customer comes back as
    an id STRING, and reading that as "no metadata, so not ours" is right —
    reading it as ours would cancel strangers' subscriptions."""
    assert not _is_ours(sub(customer="cus_1"))


# --------------------------------------------------------------------- #
# idempotence and prior state
# --------------------------------------------------------------------- #

def test_setting_the_same_stop_twice_writes_nothing_the_second_time() -> None:
    """The intake cron runs hourly. A sweep that rewrote the same date every
    hour would be 24 pointless money-mutating calls a day."""
    already = sub(cancel_at=int(AT.timestamp()))
    assert needs_stop([already], AT)[0] == []


def test_a_subscriber_who_cancelled_is_never_un_cancelled() -> None:
    """The worst possible bug in this module: `cancel_at` and
    `cancel_at_period_end` are alternative ways of saying the same thing, and
    writing `cancel_at` onto a subscription the CUSTOMER cancelled would clear
    their cancellation and charge somebody who had left."""
    assert needs_stop([sub(cancel_at_period_end=True)], AT)[0] == []


def test_a_hand_set_stop_date_outranks_the_computed_one() -> None:
    other = int((AT - timedelta(days=30)).timestamp())
    due, notes = needs_stop([sub(cancel_at=other)], AT)
    assert due == []
    assert any("already stops at" in n for n in notes)


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_a_dead_subscription_is_skipped(status: str) -> None:
    """Stripe accepts only metadata on a canceled subscription, so writing
    cancel_at would be a guaranteed error every run."""
    assert needs_stop([sub(status=status)], AT)[0] == []


@pytest.mark.parametrize("status", REPORTABLE)
def test_a_paused_or_unpaid_subscription_is_said_out_loud(status: str) -> None:
    """Not writable, but not harmless either: a paused subscription resumes
    billing on its own, so one left with no stop date is a charge nobody is
    expecting. Silence here is how it would be discovered by the customer."""
    due, notes = needs_stop([sub(status=status)], AT)
    assert due == []
    assert any(status in n for n in notes), f"{status} passed through in silence"


@pytest.mark.parametrize("status", REPORTABLE)
def test_a_yearly_subscription_in_dunning_is_not_an_alarm(status: str) -> None:
    """RULE B2 outranks status, and the filter order used to have it backwards.

    Reproduced: one $39 season pass in Stripe's `unpaid` dunning end-state and
    zero monthly subscriptions produced a note, and `main` returns 1 on any
    note, so daily.yml fired "::error::A monthly subscription is billing with
    no end-of-season stop date" and filed a bug issue — EVERY DAY, about a
    subscription RULE B2 forbids ever giving a stop date to. There is no action
    a human could take, which makes it a permanent false alarm on the only
    alarm guarding an irreversible money promise.

    The old test parametrized REPORTABLE over the monthly fixture only, so the
    ordering was pinned by nothing.
    """
    due, notes = needs_stop([yearly(status=status)], AT)
    assert due == []
    assert notes == [], (
        f"a yearly subscription in {status} raised {notes} — the daily cron "
        f"goes red forever over a plan that must renew")


def test_a_reportable_note_does_not_call_an_unpaid_subscription_paused() -> None:
    _due, notes = needs_stop([sub(status="unpaid")], AT)
    assert notes and "paused" not in notes[0], (
        "the note describes every REPORTABLE status as paused")


@pytest.mark.parametrize("status", WRITABLE)
def test_every_live_status_gets_a_stop_date(status: str) -> None:
    assert len(needs_stop([sub(status=status)], AT)[0]) == 1


def test_the_alarm_ignores_subscriptions_that_already_have_a_stop_date(
        monkeypatch, capsys) -> None:
    """The two days between a season's last game and its stop date firing.

    On 2027-01-11 and 01-12 no season satisfies `ends >= today`, so `stop_for`
    answers None — while every monthly subscriber already carries a perfectly
    good 2027-01-13 stop date set months earlier. The census counted them as
    "billing with nothing to stop them", so the cron went red and filed a bug
    issue about a date we set ourselves.
    """
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "stop_for", lambda *a, **k: (None, "2026"))
    monkeypatch.setattr(billing, "load_subscriptions",
                        lambda key: [sub(cancel_at=int(AT.timestamp()))])
    assert billing.main(["--send"]) == 0, capsys.readouterr().err
    # ...but one with NO stop date still fails the run.
    monkeypatch.setattr(billing, "load_subscriptions", lambda key: [sub()])
    assert billing.main(["--send"]) == 1


# --------------------------------------------------------------------- #
# the write
# --------------------------------------------------------------------- #

def test_the_write_sends_cancel_at_and_stamps_where_it_came_from(monkeypatch) -> None:
    seen: dict = {}

    def fake(url, key, form, what="", needs=""):
        seen.update(url=url, form=form, what=what, needs=needs)
        return {}

    monkeypatch.setattr(billing, "_stripe_post", fake)
    apply_stop("sk_test", sub(), AT)
    assert seen["form"]["cancel_at"] == str(int(AT.timestamp()))
    assert seen["form"][f"metadata[{STOP_METADATA_KEY}]"] == str(int(AT.timestamp()))
    assert "sub_1" in seen["url"]
    assert "Subscriptions" in seen["needs"], (
        "a 403 here would tell the operator to grant Customers access — the "
        "wrong permission, while the promise stays broken")


def test_proration_is_disabled_only_when_the_stop_lands_inside_this_period(
        monkeypatch) -> None:
    """Stripe documents that prorations CANNOT be disabled when the cancel date
    is outside the current period. Sending the parameter there is an untested
    guess on the one field that decides whether the call succeeds at all."""
    forms: list[dict] = []
    monkeypatch.setattr(billing, "_stripe_post",
                        lambda url, key, form, what="", needs="": forms.append(form))

    inside = sub(items={"data": [{"price": {"recurring": {"interval": "month"}},
                                  "current_period_end": int(AT.timestamp()) + 60}]})
    outside = sub(items={"data": [{"price": {"recurring": {"interval": "month"}},
                                   "current_period_end": int(AT.timestamp()) - 60}]})
    apply_stop("sk", inside, AT)
    apply_stop("sk", outside, AT)
    assert forms[0].get("proration_behavior") == "none"
    assert "proration_behavior" not in forms[1]


# --------------------------------------------------------------------- #
# RULE B1 — never guess a season, never act on a past date
# --------------------------------------------------------------------- #

@needs_schedule
def test_the_stop_clears_the_final_send_and_a_whole_retry_tuesday() -> None:
    """RULE B3, checked against every season in the archive rather than against
    an assumption. A fired cancel_at cannot be undone, so being one day early
    costs a subscriber a report they paid for, permanently.

    This is the test that catches a fixed "+3 days because the finale is a
    Sunday" rule: 4 of the 28 cached seasons end on a Monday, and 2010's final
    send lands two days AFTER its last game because a week-16 makeup held
    current_week back.

    The first version of this test asserted `send + RETRY_DAYS > send + 7`,
    which is the claim 8 > 7 and never reads the schedule at all. It ran the
    calendar and then checked arithmetic. Now every assertion is against
    `current_week`, which is what `last_send` claims to be derived from.
    """
    from run.solo import current_week

    ends = season_ends(CACHE, live=False)
    assert len(ends) > 20, "the archive should cover many seasons"
    for season in sorted(ends):
        final = date.fromisoformat(ends[season])
        last_week = current_week(CACHE, season, final, session=None)
        send = last_send(CACHE, season, live=False)
        assert send is not None, f"{season}: no send date"
        assert send.weekday() == 1, f"{season}: {send} is not a Tuesday"
        # The final week really is mailed on that day...
        assert current_week(CACHE, season, send, session=None) >= last_week, (
            f"{season}: week {last_week} is not the one mailed on {send}, so a "
            f"stop derived from it cuts the subscriber off before their last "
            f"report — and a fired cancel_at cannot be undone")
        # ...and not a week earlier, or the stop is a week later than it needs
        # to be and somebody is billed into the offseason.
        assert current_week(CACHE, season, send - timedelta(days=7),
                            session=None) < last_week, (
            f"{season}: week {last_week} was already mailed by "
            f"{send - timedelta(days=7)}; {send} is not the FIRST such Tuesday")
        # The stop clears a whole retry Tuesday PAST the real final send.
        stop = send + timedelta(days=RETRY_DAYS)
        assert (stop - final).days >= 1, f"{season}: stop {stop} precedes {final}"
        assert stop >= send + timedelta(days=8), f"{season}: no retry margin"


@needs_schedule
def test_the_offseason_gap_refuses_instead_of_cancelling_everybody() -> None:
    """The defect that made an earlier design dangerous.

    `current_season` answers the season that just ENDED once the next schedule
    is unpublished, so a stop date derived from it is in the PAST for roughly
    four months a year — and an earlier design's response to a past date was to
    cancel the subscription immediately. With checkout deliberately open in
    draft season, that would have deleted a just-paid monthly subscription
    within the hour, every hour.
    """
    ends = season_ends(CACHE, live=False)
    latest = date.fromisoformat(ends[sorted(ends)[-1]])
    for days in (2, 40, 100, 160):
        at, _season = stop_for(CACHE, latest + timedelta(days=days), live=False)
        assert at is None, (
            f"{days} days past the last cached game, a stop date was still "
            f"produced ({at}) — every monthly subscription would be acted on")


@needs_schedule
def test_a_stop_date_is_always_in_the_future_when_one_is_given() -> None:
    ends = season_ends(CACHE, live=False)
    for season in sorted(ends):
        end = date.fromisoformat(ends[season])
        at, _ = stop_for(CACHE, end - timedelta(days=30), live=False)
        if at is None:
            continue
        assert at > datetime.now(timezone.utc) or at.date() > end - timedelta(days=30)


@needs_schedule
def test_the_stop_belongs_to_a_season_still_to_be_played() -> None:
    """Not `current_season`, which is right for "which season is this report
    about" and wrong for scheduling anything in the future."""
    ends = season_ends(CACHE, live=False)
    for season in sorted(ends)[-3:]:
        start = date.fromisoformat(ends[season]) - timedelta(days=120)
        at, chosen = stop_for(CACHE, start, live=False)
        if at is None:
            continue
        assert ends[chosen] >= start.isoformat(), (
            f"chose {chosen}, whose season had already finished on {start}")


def test_a_broken_schedule_fails_closed_rather_than_raising(monkeypatch) -> None:
    """`_schedule` reaches ingest.nflverse, whose NflverseError is NOT a
    subclass of SoloError. An exception escaping here would kill the run before
    a single report was built or mailed — one data hiccup taking down everybody
    else's Tuesday, which is the blast radius this repo keeps refusing."""
    from ingest.nflverse import NflverseError

    def boom(*a, **k):
        raise NflverseError("cold cache")

    monkeypatch.setattr(billing, "season_ends", boom)
    assert stop_for(Path("/nonexistent"), date(2026, 10, 1)) == (None, None)


def test_no_delete_call_exists_anywhere_in_the_module() -> None:
    """RULE B1, pinned as text because it is a rule about what must NEVER be
    written. An unattended hourly sweep must not be able to end a subscription
    immediately: DELETE /v1/subscriptions/{id} takes effect at once, cannot be
    undone, and issues no refund.

    Matched against the AST, not the text: the first version of this test read
    the word "delete" inside RULE B1's own docstring — which is prose SAYING
    never to delete — as evidence of a delete. A guard that cannot tell code
    from the comment forbidding it is not a guard.
    """
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
            assert "delete" not in node.value.lower(), (
                f"a DELETE reaches the wire: {node.value!r}")
        if isinstance(node, ast.Attribute):
            assert "delete" not in node.attr.lower(), f"calls .{node.attr}"
        if isinstance(node, ast.Name):
            assert "delete" not in node.id.lower(), f"references {node.id}"


# --------------------------------------------------------------------- #
# the promise this exists to keep
# --------------------------------------------------------------------- #

def test_the_renewal_notice_skips_a_subscription_that_is_ending() -> None:
    """render/renewal.py's first rule: a subscription set to cancel is never
    told it will renew. run/renewals.py checked only `cancel_at_period_end`,
    which was harmless only while nothing set `cancel_at` — run/billing.py now
    does, so this became live the day it shipped."""
    source = (Path(billing.__file__).parent / "renewals.py").read_text(encoding="utf-8")
    assert 'subscription.get("cancel_at")' in source, (
        "renewals.py reads only cancel_at_period_end again — a subscription "
        "ending via cancel_at would be told it is about to be charged $39")


def test_dry_run_is_the_default(monkeypatch, capsys) -> None:
    """This is the first money-mutating call in the repo. A misconfigured cron
    must not cancel real subscriptions by accident — the same rule run/tuesday.py
    and run/batch.py were taught the hard way."""
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "load_subscriptions", lambda key: [sub()])
    monkeypatch.setattr(billing, "stop_for", lambda *a, **k: (AT, "2026"))
    written: list = []
    monkeypatch.setattr(billing, "apply_stop",
                        lambda *a, **k: written.append(a))
    assert billing.main([]) == 0
    assert written == [], "a run with no --send wrote to Stripe"
    assert "would set" in capsys.readouterr().out


def test_send_writes_and_a_failure_exits_non_zero(monkeypatch, capsys) -> None:
    """A subscription left with no stop date is a customer who WILL be charged
    through the offseason. That must fail the run, not print into a green cron —
    daily.yml files its issue only on failure."""
    from run.subscriptions import SubscriptionError

    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "load_subscriptions", lambda key: [sub()])
    monkeypatch.setattr(billing, "stop_for", lambda *a, **k: (AT, "2026"))

    def boom(*a, **k):
        raise SubscriptionError("HTTP 403")

    monkeypatch.setattr(billing, "apply_stop", boom)
    assert billing.main(["--send"]) == 1
    assert "still billing with no stop date" in capsys.readouterr().err


def test_monthly_subscriptions_with_no_computable_stop_fail_the_run(
        monkeypatch, capsys) -> None:
    """The offseason gap. Refusing is right; refusing SILENTLY is not — those
    subscriptions really are billing with nothing to stop them."""
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setattr(billing, "load_subscriptions", lambda key: [sub()])
    monkeypatch.setattr(billing, "stop_for", lambda *a, **k: (None, "2026"))
    assert billing.main(["--send"]) == 1
    assert "NO STOP DATE" in capsys.readouterr().err


def test_no_stripe_key_is_expected_not_an_error(monkeypatch) -> None:
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert billing.main([]) == billing.NOT_CONFIGURED
