"""The 2027 Season Pass: $39 now for the rest of 2026 and all of 2027, a
subscription whose first renewal is moved to August 2028.

Off until a lawyer has seen it, so the first thing held true here is that with
no ``y:`` in STRIPE_PAYMENT_LINKS nothing has changed for anybody. Everything
runs against a stand-in for Stripe written from Stripe's documentation: this
path has never met the real thing (LAUNCH.md section 13, step 3, is where it
does). Each test names the failure it prevents.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import run.billing as billing
import run.checkout as checkout
import run.intake as intake
import run.launch_check as launch_check
import run.renewals as renewals
import run.stats as stats
import run.subscriptions as subscriptions
from render.renewal import renewal_day
from render.report import season_end_lines
from render.welcome import (ONCE_BESIDE_2027, SEASON_2027_PRICE, SEASON_2027_TWICE,
                            first_renewal_words, welcome_message)
from run.billing import (DEFER_METADATA_KEY, MAX_TRIAL_DAYS, ROSTER_METADATA_KEY, YEARLY,
                         apply_deferral, money_returned, needs_deferral, needs_stop)
from run.checkout import (SEASON_2027_FIRST_RENEWAL, SEASON_2027_PRICE_CENTS,
                          link_map_problems, parse_link_plans, playoff_links,
                          season_2027_links)
from run.rosters import SEASON_2027, RosterSubscriber, load_rosters
from run.subscriptions import SubscriptionError, load_paid_from_stripe, purchase_view
from test_intake_sync import (PASS_LINK, PLAYERS, REF, SEASON_LINK, _registry, _run,
                              _session, directory, stripe)  # noqa: F401 — fixtures

PASS_2027_LINK = "plink_Y"
MAP_2026 = f"s:{SEASON_LINK},o:plink_O,p:{PASS_LINK}"
MAP_2027 = f"{MAP_2026},y:{PASS_2027_LINK}"
BOUGHT = int(datetime(2026, 10, 30, 15, tzinfo=timezone.utc).timestamp())
TARGET = int(SEASON_2027_FIRST_RENEWAL.timestamp())
NOW = datetime(2026, 10, 31, 14, tzinfo=timezone.utc)
SUB = "sub_pass0001"
FINAL = datetime(2027, 1, 5, 12, 17, tzinfo=timezone.utc)


def _charge(**over) -> dict:
    return {"id": "ch_1", "amount": 3900, "amount_refunded": 0, "refunded": False,
            "disputed": False, **over}


def bought(**over) -> dict:
    """A pass as the checkout leaves it: active, its $39 on the latest invoice."""
    row = {
        "id": SUB, "status": "active", "cancel_at": None, "cancel_at_period_end": False,
        "billing_cycle_anchor": BOUGHT, "schedule": None, "trial_end": None,
        "current_period_end": BOUGHT + 365 * 86400,
        "customer": {"id": "cus_abcd1234", "email": "fan@example.com",
                     "metadata": {ROSTER_METADATA_KEY: REF, "byl_plan": "season"}},
        "items": {"data": [{"price": {"unit_amount": SEASON_2027_PRICE_CENTS, "currency": "usd",
                                      "recurring": {"interval": YEARLY}}}]},
        "latest_invoice": {"id": "in_paid", "amount_paid": 3900, "charge": _charge()},
    }
    row.update(over)
    return row


def moved(**over) -> dict:
    """The same pass after the move. Stripe's documented shape: trialing, with
    a 0 USD invoice on top that carries no charge."""
    row = bought(status="trialing", trial_end=TARGET, current_period_end=TARGET,
                 billing_cycle_anchor=TARGET,
                 latest_invoice={"id": "in_zero", "amount_paid": 0, "charge": None})
    row.update(over)
    return row


def _stripe_reads(monkeypatch, subs: list[dict], charge: dict | None = None) -> list[str]:
    """Stripe's reads for entitlement. ``charge`` is what the paid invoice
    holds; returns the URLs asked for."""
    asked: list[str] = []

    def get(url, key):
        asked.append(url)
        path, query = urlsplit(url).path, parse_qs(urlsplit(url).query)
        if path.endswith("/invoices"):
            assert query["subscription"] == [SUB] and query["status"] == ["paid"]
            return {"data": [{"id": "in_zero", "charge": None},
                             {"id": "in_paid", "charge": charge or _charge()}]}
        if path.endswith("/disputes"):
            return {"data": [{"status": "lost"}]}
        if path.endswith("/subscriptions"):
            return {"data": [s for s in subs if s["status"] == query["status"][0]],
                    "has_more": False}
        return {"data": [], "has_more": False}

    monkeypatch.setattr(subscriptions, "_stripe_get", get)
    return asked


@pytest.fixture
def sold_2027(stripe, directory, monkeypatch, tmp_path):  # noqa: F811
    """The fake account with the y: link in its map."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2027)
    monkeypatch.setattr(intake, "_send_welcomes", lambda *a, **k: 0)
    return stripe


def _pass_session(**over) -> dict:
    fields = {"sid": "cs_y", "link": PASS_2027_LINK, "created": BOUGHT, "subscription": SUB}
    fields.update(over)
    return {**_session(REF, **fields), "mode": "subscription"}


# --------------------------------------------------------------------- #
# with no y: link, nothing has changed for anybody
# --------------------------------------------------------------------- #

def test_the_map_without_y_reads_exactly_as_it_did() -> None:
    """Today's production path. The offer does not exist until it is named."""
    assert season_2027_links(MAP_2026) == frozenset()
    assert parse_link_plans(MAP_2026) == {SEASON_LINK: "season", "plink_O": "season",
                                          PASS_LINK: "league_pass"}
    assert playoff_links(MAP_2026) == {"plink_O"}
    assert link_map_problems(MAP_2026) == []


def test_an_existing_purchase_writes_the_same_row_and_log_line(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:  # noqa: F811
    """No marker on a row, no marker on a log line, nothing for the loader to
    read: a purchase on today's map is byte-for-byte a purchase on today's map."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2026)
    monkeypatch.setattr(intake, "_send_welcomes", lambda *a, **k: 0)
    stripe["sessions"] = [_session(REF, created=BOUGHT, subscription="sub_plain001")]
    assert _run(tmp_path) == 0, capsys.readouterr().err
    assert "season_2027" not in _registry(tmp_path)[0]
    assert "season_2027" not in (tmp_path / intake.SIGNUP_LOG_NAME).read_text(encoding="utf-8")
    assert load_rosters(tmp_path / intake.REGISTRY_NAME)[0].report_plan == "season"


def test_the_welcome_is_byte_identical_without_the_marker() -> None:
    """The keyword changes nothing when it is not passed."""
    args = ("fan@example.com", "season", "abcdef0123", "2026")
    plain = welcome_message(*args, purchased_at=str(BOUGHT), now=NOW)
    off = welcome_message(*args, purchased_at=str(BOUGHT), now=NOW, season_2027=False)
    assert (plain.subject, plain.html, plain.text) == (off.subject, off.html, off.text)


def _billing_env(monkeypatch, raw: str, subs: list[dict], sessions: list[dict] | None = None,
                 final=(FINAL, "2026")) -> dict:
    """billing.main against the stand-in. Returns what it read and wrote."""
    log: dict = {"loads": [], "sweeps": 0, "posts": []}

    def load(key, *, charges=False):
        log["loads"].append(charges)
        return subs

    def sweep(key, since, links):
        log["sweeps"] += 1
        return (sessions or []), None

    def post(url, key, form, what="", needs=""):
        log["posts"].append((url, form))
        return moved()

    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", raw)
    monkeypatch.setattr(billing, "load_subscriptions", load)
    monkeypatch.setattr(billing, "sweep_sessions", sweep)
    monkeypatch.setattr(billing, "_stripe_post", post)
    monkeypatch.setattr(billing, "final_send", lambda *a, **k: final)
    monkeypatch.setattr(billing, "money_returned", lambda *a, **k: None)
    return log


def test_the_billing_run_never_reads_a_thing_more_without_y(monkeypatch, capsys) -> None:
    """No sessions walked, no second subscription read, not a line printed."""
    log = _billing_env(monkeypatch, MAP_2026, [bought()])
    assert billing.main(["--send", "--today", "2026-10-31"]) == 0
    assert log == {"loads": [False], "sweeps": 0, "posts": []}
    assert "SEASON PASS" not in capsys.readouterr().out


# --------------------------------------------------------------------- #
# the map
# --------------------------------------------------------------------- #

def test_y_is_a_season_plan_named_by_its_link() -> None:
    assert parse_link_plans(MAP_2027)[PASS_2027_LINK] == "season"
    assert season_2027_links(MAP_2027) == {PASS_2027_LINK}
    assert link_map_problems(MAP_2027) == []


@pytest.mark.parametrize("raw, words", [
    (f"{MAP_2026},y:", "names no payment link"),
    (f"{MAP_2026},y:plink_A,y:plink_B", "2 y: links"),
    (f"{MAP_2026},y:{SEASON_LINK}", "listed as both"),
])
def test_a_mistake_in_the_y_entry_is_said_in_words(raw: str, words: str) -> None:
    """The map is the whole of "which plan did this payment buy", and its
    mistakes fail quietly."""
    assert any(words in problem for problem in link_map_problems(raw))


def test_a_y_with_no_link_is_not_a_filter_on_a_link_called_y() -> None:
    """A bare entry is a filter, so "y:" would have put payment_link=y on a
    Stripe query, a 400 on every hourly sweep."""
    assert "y" not in parse_link_plans(f"{MAP_2026},y:")


# --------------------------------------------------------------------- #
# intake
# --------------------------------------------------------------------- #

def test_a_y_session_is_a_season_row_with_its_marker(tmp_path, sold_2027, capsys) -> None:
    sold_2027["sessions"] = [_pass_session()]
    assert _run(tmp_path) == 0, capsys.readouterr().err
    row = _registry(tmp_path)[0]
    assert row["plan"] == "season" and row["billing"] == "season"
    assert row["subscription_ids"] == [SUB] and row["season_2027"] is True
    subscriber = load_rosters(tmp_path / intake.REGISTRY_NAME)[0]
    assert subscriber.season_2027 and not subscriber.one_time
    assert subscriber.report_plan == SEASON_2027


def test_the_plan_comes_from_the_link_never_the_ref(tmp_path, sold_2027, capsys) -> None:
    """The ref is a claim in a URL. A "p" ref through the y: link buys a season
    row and no League Pass."""
    from test_intake_sync import PASS_REF
    sold_2027["sessions"] = [{**_pass_session(), "client_reference_id": PASS_REF}]
    _run(tmp_path)
    row = _registry(tmp_path)[0]
    assert row["plan"] == "season" and row["billing"] == "season" and row["season_2027"]
    assert "pass_id" not in row
    assert "claims a League Pass" in capsys.readouterr().err


def test_a_ref_never_earns_the_marker(tmp_path, sold_2027) -> None:
    """Only the link that took the money does. The same ref through the $29
    link is a $29 purchase."""
    sold_2027["sessions"] = [_session(REF, link=SEASON_LINK, created=BOUGHT)]
    _run(tmp_path)
    assert "season_2027" not in _registry(tmp_path)[0]


def test_an_unpaid_session_is_nobody(tmp_path, sold_2027) -> None:
    sold_2027["sessions"] = [_pass_session(paid="unpaid")]
    _run(tmp_path)
    assert _registry(tmp_path) == []


def test_a_y_link_in_payment_mode_is_unattributed_not_welcomed(tmp_path, sold_2027,
                                                               capsys) -> None:
    """A $39 payment with no subscription behind it: the welcome would promise
    2027 and a renewal, and entitlement would end with 2026. Nothing assumed."""
    session = {**_session(REF, sid="cs_bad", link=PASS_2027_LINK, created=BOUGHT),
               "mode": "payment", "payment_intent": "pi_abcd1234"}
    sold_2027["sessions"] = [session]
    assert _run(tmp_path) == 1
    assert _registry(tmp_path) == []
    assert "PAID-UNATTRIBUTED session cs_bad" in capsys.readouterr().err


def test_a_y_session_through_an_unmapped_link_is_still_unattributed(tmp_path, sold_2027,
                                                                    capsys) -> None:
    """D17 stands: before y: is in the secret, a purchase through the link is
    a plan nobody knows, and nobody is told $29 terms."""
    sold_2027["sessions"] = [_pass_session(link="plink_unmapped")]
    assert _run(tmp_path) == 1
    assert "not in STRIPE_PAYMENT_LINKS" in capsys.readouterr().err


def test_two_s_links_still_fail_the_run(tmp_path, sold_2027, monkeypatch, capsys) -> None:
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},s:plink_S2,p:{PASS_LINK},"
                                               f"y:{PASS_2027_LINK}")
    sold_2027["sessions"] = [_session(REF, created=BOUGHT)]
    assert _run(tmp_path) == 1
    assert "s: links" in capsys.readouterr().err


def test_the_pass_is_not_a_league_pass_and_carries_no_seats(tmp_path, sold_2027) -> None:
    """Seats are entitled through a pass subscription (RULE E2). A $39 row must
    not start offering them."""
    sold_2027["sessions"] = [_pass_session()]
    _run(tmp_path)
    assert load_rosters(tmp_path / intake.REGISTRY_NAME)[0].pass_key is None
    signup = intake.load_log(tmp_path / intake.SIGNUP_LOG_NAME)[0]
    assert signup.pass_of is None and intake.pass_seat_link(signup) is None


def test_a_re_sweep_adds_nothing(tmp_path, sold_2027) -> None:
    sold_2027["sessions"] = [_pass_session()]
    _run(tmp_path)
    _run(tmp_path, "--full")
    log = (tmp_path / intake.SIGNUP_LOG_NAME).read_text(encoding="utf-8").splitlines()
    assert len(log) == 1 and json.loads(log[0])["season_2027"] is True


PI = "pi_abcd1234"


def _rest_of_season(created: int) -> dict:
    """The $29 one-time pass, with the same ref: the join page's prefix is "s"
    on both links, so an upgrade with the same roster is the same string."""
    return {**_session(REF, sid="cs_29", created=created, link=SEASON_LINK),
            "mode": "payment", "payment_intent": PI}


def _live(monkeypatch, *ids: str) -> None:
    """What Stripe says is paid for right now: the answer run/intake reads when
    two purchases share a roster (run/subscriptions has its own tests)."""
    monkeypatch.setattr(intake, "_live_subscriptions", lambda *a, **k: set(ids))


@pytest.mark.parametrize("first, second", [(BOUGHT, BOUGHT + 86400), (BOUGHT + 86400, BOUGHT)])
def test_a_29_buyer_who_takes_the_39_pass_keeps_one_row_on_both(tmp_path, sold_2027, first,
                                                                second, capsys,
                                                                monkeypatch) -> None:
    """The natural upgrade, and it collided twice: (email, ref, plan) is equal,
    so append_log dropped the second purchase, and the row went on naming a
    payment that ends with 2026 while a $39 subscription billed for nothing;
    then two rows on one ref fail the whole registry load. Either order, one
    row on both purchases, so losing one never loses the other."""
    sold_2027["sessions"] = [_rest_of_season(first), _pass_session(created=second)]
    _live(monkeypatch, PI, SUB)
    assert _run(tmp_path) == 0, capsys.readouterr().err
    assert len(intake.load_log(tmp_path / intake.SIGNUP_LOG_NAME)) == 2
    rows = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert len(rows) == 1
    assert set(rows[0].subscription_ids) == {PI, SUB} and rows[0].season_2027
    assert not rows[0].one_time, "a row with a renewing purchase on it is not one-time"


def test_a_refunded_29_never_costs_the_paid_39_its_row(tmp_path, sold_2027, capsys,
                                                       monkeypatch) -> None:
    """A dead purchase is never merged (EMAILS-109), which left two rows on one
    ref, and drop_unloadable keeps the later: the refunded one could win."""
    sold_2027["sessions"] = [_rest_of_season(BOUGHT + 86400), _pass_session()]
    _live(monkeypatch, SUB)
    assert _run(tmp_path) == 0, capsys.readouterr().err
    row = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert len(row) == 1 and row[0].subscription_ids == (SUB,) and row[0].season_2027


def test_a_refunded_39_never_costs_the_paid_29_its_row(tmp_path, sold_2027, capsys,
                                                       monkeypatch) -> None:
    """The other way round, with the $39 the newer of the two."""
    sold_2027["sessions"] = [_rest_of_season(BOUGHT), _pass_session(created=BOUGHT + 86400)]
    _live(monkeypatch, PI)
    assert _run(tmp_path) == 0, capsys.readouterr().err
    row = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert len(row) == 1 and row[0].subscription_ids == (PI,) and not row[0].season_2027


# --------------------------------------------------------------------- #
# the welcome: the retainable notice California's ARL requires
# --------------------------------------------------------------------- #

def _pass_welcome(**over):
    return welcome_message("fan@example.com", "season", "abcdef0123", "2026",
                           purchased_at=str(BOUGHT), now=NOW, season_2027=True, **over)


def test_the_welcome_states_what_the_law_wants_on_both_halves(monkeypatch) -> None:
    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/x")
    message = _pass_welcome()
    assert first_renewal_words() == "August 15, 2028"
    for half in (message.text, message.html):
        half = half.replace("&#x27;", "'")
        assert "2027 Season Pass" in half
        assert "$39 USD" in half and SEASON_2027_PRICE == "$39"
        assert "the rest of the 2026 season and all of the 2027 season" in half
        assert "August 15, 2028" in half and "each August after that" in half
        assert "15 to 45 days before" in half
        assert "billing.stripe.com/p/login/x" in half
        assert "first weekly report" in half, "the refund window"
        assert "until you cancel" in half


def test_nothing_in_it_describes_the_purchase_they_did_not_make() -> None:
    """The fall-through bottom of _plan_terms says $29 and the anniversary, and
    the one-time branch says nothing renews. Either is a false disclosure."""
    message = _pass_welcome().text
    for wrong in ("$29", "anniversary", "Nothing renews", "One payment", "one payment",
                  'reply "stop"'):
        assert wrong not in message


def test_the_marker_reaches_the_welcome_from_the_signup(tmp_path, sold_2027, monkeypatch) -> None:
    """Built from the signup, never the registry row, which is an ordinary
    season row. Unwired, this buyer is told "$29, on the anniversary"."""
    sold_2027["sessions"] = [_pass_session()]
    _run(tmp_path)
    signup = intake.load_log(tmp_path / intake.SIGNUP_LOG_NAME)[0]
    assert signup.season_2027
    text = intake._welcome(signup, "2026").text
    assert "$39 USD" in text and "August 15, 2028" in text and "$29" not in text


def test_a_seat_never_gets_it() -> None:
    """Only a season purchase. A seat pays nothing and has no renewal."""
    seat = welcome_message("fan@example.com", "seat", "abcdef0123", "2026", now=NOW,
                           season_2027=True)
    assert "$39" not in seat.text and "2028" not in seat.text


def test_the_pair_of_purchases_gets_the_true_sentence() -> None:
    """"Both were one payment" of a renewing pass and "it keeps billing" of one
    that never bills are the two lines this replaces."""
    upgrade = _pass_welcome(duplicate="season").text
    assert SEASON_2027_TWICE in upgrade and "Both were one payment" not in upgrade
    beside = welcome_message("fan@example.com", "season", "abcdef0123", "2026", now=NOW,
                             purchased_at=str(BOUGHT), one_time=True,
                             duplicate=SEASON_2027).text
    assert ONCE_BESIDE_2027 in beside and "Both were one payment" not in beside


def test_the_older_purchase_is_named_for_the_newer_welcome() -> None:
    older, newer = [
        intake.RosterSignup(email="fan@example.com", ref=REF, plan="season",
                            seen_at=str(BOUGHT), subscription_id=SUB, season_2027=True),
        intake.RosterSignup(email="fan@example.com", ref=REF, plan="season",
                            seen_at=str(BOUGHT + 9), subscription_id=PI)]
    assert intake.merge_same_roster([older, newer]).duplicates[newer.key] == SEASON_2027


# --------------------------------------------------------------------- #
# the first renewal
# --------------------------------------------------------------------- #

def test_the_date_is_an_august_date_on_the_buyers_clock() -> None:
    """Noon ET, so the date a buyer reads and the date Stripe bills are one."""
    assert renewal_day(TARGET) == date(2028, 8, 15)
    assert SEASON_2027_FIRST_RENEWAL.date() == date(2028, 8, 15)


def test_the_date_is_inside_stripes_two_years_for_every_sale_since_it_could_be_sold() -> None:
    """`trial_end` "can be at most two years from `billing_cycle_anchor`"."""
    earliest = datetime(2026, 10, 30, tzinfo=timezone.utc)
    assert (SEASON_2027_FIRST_RENEWAL - earliest).days < MAX_TRIAL_DAYS == 730


def test_a_paid_pass_is_due_to_be_moved() -> None:
    plan = needs_deferral([bought()], {SUB}, now=NOW)
    assert [s["id"] for s in plan.due] == [SUB] and plan.notes == [] and plan.done == 0


def test_the_write_is_stripes_recipe_exactly(monkeypatch) -> None:
    """Without proration_behavior=none, starting a trial credits the unused
    part of a year we owe them in full."""
    seen: dict = {}

    def post(url, key, form, what="", needs=""):
        seen.update(url=url, form=form, needs=needs)
        return moved()

    monkeypatch.setattr(billing, "_stripe_post", post)
    apply_deferral("sk_test", bought())
    assert seen["form"] == {"trial_end": str(TARGET), "proration_behavior": "none",
                            f"metadata[{DEFER_METADATA_KEY}]": "2028-08-15"}
    assert seen["url"].endswith(f"/subscriptions/{SUB}")
    assert "Subscriptions" in seen["needs"]


@pytest.mark.parametrize("answer", [bought(), moved(trial_end=TARGET + 86400), {}])
def test_a_write_stripe_did_not_apply_is_a_failure(monkeypatch, answer) -> None:
    """A 200 says Stripe took the request, not that the subscription now says
    what the welcome told the buyer."""
    monkeypatch.setattr(billing, "_stripe_post", lambda *a, **k: answer)
    with pytest.raises(SubscriptionError):
        apply_deferral("sk_test", bought())


def test_the_run_is_dry_by_default(monkeypatch, capsys) -> None:
    log = _billing_env(monkeypatch, MAP_2027, [bought()],
                       [_pass_session()])
    assert billing.main(["--today", "2026-10-31"]) == 0
    out = capsys.readouterr().out
    assert log["posts"] == [] and f"[would move] {SUB}" in out and "dry run" in out


def test_send_moves_it_and_says_so(monkeypatch, capsys) -> None:
    log = _billing_env(monkeypatch, MAP_2027, [bought()], [_pass_session()])
    assert billing.main(["--send", "--today", "2026-10-31"]) == 0
    assert len(log["posts"]) == 1 and f"[moved] {SUB}" in capsys.readouterr().out
    assert log["loads"] == [False, True], "the monthly read is unchanged; the pass step adds one"


def test_a_second_run_writes_nothing(monkeypatch, capsys) -> None:
    """Idempotent: the daily run sees what the last one did."""
    log = _billing_env(monkeypatch, MAP_2027, [moved()], [_pass_session()])
    assert billing.main(["--send", "--today", "2026-11-01"]) == 0
    assert log["posts"] == [] and "1 already moved, 0 to move" in capsys.readouterr().out


def test_the_offseason_still_moves_a_pass(monkeypatch) -> None:
    """The monthly stop returns early when no season is left to serve, which
    is exactly when a pass bought in January still needs moving."""
    log = _billing_env(monkeypatch, MAP_2027, [bought()], [_pass_session()], final=(None, None))
    assert billing.main(["--send", "--today", "2027-02-10"]) == 0
    assert len(log["posts"]) == 1


def test_a_pass_needing_a_person_fails_the_run_and_keeps_the_monthly_result(monkeypatch) -> None:
    _billing_env(monkeypatch, MAP_2027, [bought(cancel_at_period_end=True)], [_pass_session()])
    assert billing.main(["--send", "--today", "2026-10-31"]) == 1


@pytest.mark.parametrize("subscription, words", [
    (bought(cancel_at_period_end=True), "cancelled before its first renewal"),
    (bought(cancel_at=BOUGHT + 86400), "cancelled before its first renewal"),
    (bought(status="past_due"), "is past_due"),
    (bought(status="paused"), "is paused"),
    (bought(schedule="sub_sched_1"), "subscription schedule"),
    (moved(trial_end=TARGET - 86400), "in a trial ending"),
    (bought(billing_cycle_anchor=None), "no readable billing anchor"),
    (bought(billing_cycle_anchor=TARGET - 731 * 86400), "Stripe's two years"),
    (bought(items={"data": [{"price": {"unit_amount": 3900,
                                       "recurring": {"interval": "month"}}}]}), "every month"),
    (bought(items={"data": [{"price": {"unit_amount": 2900,
                                       "recurring": {"interval": YEARLY}}}]}), "2900 cents"),
    (bought(items={"data": []}), "every None"),
    (bought(customer={"id": "cus_x", "metadata": {}}), "no roster stamp"),
])
def test_rule_d2_what_it_cannot_say_it_reports_and_leaves(subscription, words) -> None:
    """Failing loudly rather than guessing. Each is a sentence on stderr and a
    red run, and none is a write."""
    plan = needs_deferral([subscription], {SUB}, now=NOW)
    assert plan.due == [] and plan.done == 0
    assert any(words in note for note in plan.notes), plan.notes


def test_past_the_stated_date_it_refuses() -> None:
    late = datetime(2028, 8, 16, tzinfo=timezone.utc)
    plan = needs_deferral([bought()], {SUB}, now=late)
    assert plan.due == [] and "after the stated first renewal" in plan.notes[0]


def test_a_finished_subscription_has_nothing_to_say() -> None:
    plan = needs_deferral([bought(status="canceled"), ], {SUB}, now=NOW)
    assert (plan.due, plan.done, plan.notes) == ([], 0, [])


def test_a_session_stripe_cannot_find_is_said() -> None:
    assert "does not list it" in needs_deferral([], {SUB}, now=NOW).notes[0]


def test_the_39_yearly_pass_sold_through_any_other_link_is_never_moved() -> None:
    """RULE D1. The future $39 yearly pass and the League Pass renew on their
    anniversaries; moving one is an unasked-for year of free service."""
    plan = needs_deferral([bought(id="sub_ordinary1")], {SUB}, now=NOW)
    assert plan.due == [] and plan.done == 0


def test_only_the_y_links_paid_sessions_count_as_sold(monkeypatch) -> None:
    sessions = [_pass_session(),
                _pass_session(sid="cs_unpaid", paid="unpaid", subscription="sub_unpaid01"),
                _session(REF, sid="cs_29", link=SEASON_LINK, subscription="sub_other001")]
    monkeypatch.setattr(billing, "sweep_sessions", lambda *a: (sessions, None))
    assert billing.season_2027_sold("sk", {PASS_2027_LINK}) == {SUB}


def test_the_monthly_sweep_can_never_touch_one() -> None:
    """RULE B2: the interval on the price, before anything else is read, in
    every state a pass can be in."""
    for subscription in (bought(), moved(), moved(status="unpaid"), moved(status="past_due")):
        assert needs_stop([subscription], FINAL) == ([], [])


def test_a_moved_pass_is_no_part_of_the_monthly_census(monkeypatch, capsys) -> None:
    _billing_env(monkeypatch, MAP_2026, [moved()], final=(None, None))
    assert billing.main(["--send", "--today", "2027-02-10"]) == 0
    assert "0 monthly" in capsys.readouterr().out


def test_a_refunded_pass_is_never_moved_and_is_never_silent() -> None:
    """A refund does not stop a subscription: it would still bill in 2027 (or
    2028), so the run stays red until a person cancels it."""
    plan = needs_deferral([bought()], {SUB}, now=NOW, returned=lambda s: "refunded")
    assert plan.due == [] and plan.notes[0].startswith("REFUNDED-STILL-LIVE")
    assert "cancel it in the Stripe Dashboard" in plan.notes[0]


def test_the_alarm_clears_once_it_is_cancelled() -> None:
    plan = needs_deferral([moved(cancel_at_period_end=True)], {SUB}, now=NOW,
                          returned=lambda s: "lost")
    assert (plan.due, plan.done, plan.notes) == ([], 0, [])


def test_a_disputed_pass_waits() -> None:
    plan = needs_deferral([bought()], {SUB}, now=NOW, returned=lambda s: "disputed")
    assert plan.due == [] and "open dispute" in plan.notes[0]


@pytest.mark.parametrize("charge, answer", [
    (_charge(refunded=True, amount_refunded=3900), "refunded"),
    (_charge(amount_refunded=3900), "refunded"),
    (_charge(amount_refunded=1000), None),
    (_charge(disputed=True), "lost"),
])
def test_money_returned_reads_the_purchase_not_the_zero_invoice(monkeypatch, charge, answer) -> None:
    _stripe_reads(monkeypatch, [], charge)
    assert money_returned(moved(), "sk") == answer


def test_no_address_reaches_a_line_of_the_run(monkeypatch, capsys) -> None:
    """Run output lands in a CI log."""
    _billing_env(monkeypatch, MAP_2027, [bought(cancel_at_period_end=True), ], [_pass_session()])
    billing.main(["--send", "--today", "2026-10-31"])
    captured = capsys.readouterr()
    assert "@" not in captured.out + captured.err


def test_a_provider_error_is_redacted_before_it_is_printed(monkeypatch, capsys) -> None:
    """Stripe's error bodies are quoted into run output, and those logs are
    public. What went wrong survives; who it was about does not."""
    log = _billing_env(monkeypatch, MAP_2027, [bought()], [_pass_session()])

    def refuse(*a, **k):
        raise SubscriptionError("HTTP 400 for fan@example.com with sk_live_abcdefghijkl")

    monkeypatch.setattr(billing, "_stripe_post", refuse)
    assert billing.main(["--send", "--today", "2026-10-31"]) == 1
    err = capsys.readouterr().err
    assert "fan@example.com" not in err and "sk_live_abcdefghijkl" not in err
    assert "HTTP 400" in err and log["posts"] == []


def test_a_moved_pass_stays_in_view_after_its_session_ages_out(monkeypatch, capsys) -> None:
    """Stripe documents no retention for old Checkout Sessions. The stamp is
    what keeps a refund on a two-year-old pass from going quiet."""
    stamped = moved(metadata={DEFER_METADATA_KEY: "2028-08-15"})
    _billing_env(monkeypatch, MAP_2027, [stamped], sessions=[])
    monkeypatch.setattr(billing, "money_returned", lambda *a, **k: "refunded")
    assert billing.main(["--send", "--today", "2027-09-01"]) == 1
    assert "REFUNDED-STILL-LIVE" in capsys.readouterr().err


def test_the_daily_workflow_hands_the_step_the_map() -> None:
    """Without it the step sees no y: link, moves nothing and stays green, and
    a buyer is charged again mid-2027 for a season the $39 covers."""
    text = (Path(__file__).resolve().parent.parent
            / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    step = text[text.index("id: billing"):]
    step = step[:step.index("run.billing --send")]
    assert "STRIPE_PAYMENT_LINKS: ${{ secrets.STRIPE_PAYMENT_LINKS }}" in step


# --------------------------------------------------------------------- #
# the notice
# --------------------------------------------------------------------- #

@pytest.fixture
def notices(monkeypatch):
    state: dict = {"subs": []}

    def get(url, key):
        status = parse_qs(urlsplit(url).query)["status"][0]
        return {"data": [s for s in state["subs"] if s["status"] == status], "has_more": False}

    monkeypatch.setattr(renewals, "_stripe_get", get)
    return state


@pytest.mark.parametrize("today, listed", [
    (date(2028, 6, 30), False),      # 46 days out: too early to be the notice
    (date(2028, 7, 1), True),        # 45 days
    (date(2028, 7, 31), True),       # 15 days
    (date(2028, 8, 1), False),       # 14 days: late
])
def test_the_notice_counts_from_the_charge_date(notices, today, listed) -> None:
    """`trial_end`, and only that. Its period end disagrees here on purpose:
    a sweep reading it would notify on the wrong day, or never."""
    notices["subs"] = [moved(current_period_end=BOUGHT + 365 * 86400)]
    found, problems = renewals.upcoming("sk_test", today)
    assert problems == [] and bool(found) is listed
    if listed:
        assert found[0].renews_on == date(2028, 8, 15) and found[0].amount == "$39.00 USD"


def test_the_amount_is_stripes_never_our_constant(notices) -> None:
    pass_ = moved(items={"data": [{"price": {"unit_amount": 4900, "currency": "usd",
                                             "recurring": {"interval": YEARLY}}}]})
    notices["subs"] = [pass_]
    assert renewals.upcoming("sk_test", date(2028, 7, 1))[0][0].amount == "$49.00 USD"


@pytest.mark.parametrize("cancel", [{"cancel_at_period_end": True}, {"cancel_at": TARGET}])
def test_a_cancelling_pass_is_never_told_it_renews(notices, cancel) -> None:
    """Stripe's portal writes either field, depending on billing mode."""
    notices["subs"] = [moved(**cancel)]
    assert renewals.upcoming("sk_test", date(2028, 7, 1)) == ([], [])


def test_a_trial_with_no_readable_end_is_reported_never_guessed(notices) -> None:
    """Falling back to the period end would state a date nobody knows."""
    notices["subs"] = [moved(trial_end=None)]
    found, problems = renewals.upcoming("sk_test", date(2028, 7, 1))
    assert found == [] and "no readable renewal date" in problems[0]


def test_a_pass_we_cannot_price_is_reported_not_notified(notices) -> None:
    notices["subs"] = [moved(items={"data": [{"price": {"recurring": {"interval": YEARLY}}}]})]
    found, problems = renewals.upcoming("sk_test", date(2028, 7, 1))
    assert found == [] and "no notice sent" in problems[0]


def test_a_monthly_trial_gets_no_annual_notice(notices) -> None:
    notices["subs"] = [moved(items={"data": [{"price": {
        "unit_amount": 1499, "currency": "usd", "recurring": {"interval": "month"}}}]})]
    assert renewals.upcoming("sk_test", date(2028, 7, 1)) == ([], [])


def test_an_active_subscription_still_reads_its_period_end(notices) -> None:
    """The yearly pass path. A stray trial_end on an active subscription (one
    that came out of a trial) is history, not the next charge."""
    day = int(datetime(2027, 8, 1, 16, tzinfo=timezone.utc).timestamp())
    notices["subs"] = [bought(current_period_end=day, trial_end=BOUGHT)]
    found, _ = renewals.upcoming("sk_test", date(2027, 7, 1))
    assert found[0].renews_on == date(2027, 8, 1)


# --------------------------------------------------------------------- #
# entitlement
# --------------------------------------------------------------------- #

def _row(**over) -> RosterSubscriber:
    fields = dict(email="fan@example.com", ref=REF, player_ids=tuple(PLAYERS), slots=(),
                  scoring="ppr", subscription_ids=(SUB,))
    fields.update(over)
    return RosterSubscriber(**fields)


def test_a_moved_pass_is_entitled_the_whole_way_through(monkeypatch) -> None:
    """`trialing` is what Stripe calls it for 22 months, the offseason of 2027
    included: no date arithmetic of ours decides this."""
    _stripe_reads(monkeypatch, [moved()])
    paid = load_paid_from_stripe("sk")
    assert SUB in paid.subscription_ids and paid.entitles(_row())


def test_a_refund_ends_it_even_with_the_zero_invoice_on_top(monkeypatch) -> None:
    """The bug this offer would have shipped. The 0 USD invoice the move leaves
    is `latest_invoice`, RULE E1 read a charge-less invoice and said "not
    refunded", and a refunded buyer stayed `trialing` and served until 2028."""
    _stripe_reads(monkeypatch, [moved()], _charge(refunded=True, amount_refunded=3900))
    paid = load_paid_from_stripe("sk")
    assert SUB not in paid.subscription_ids and SUB in paid.refunded
    assert not paid.entitles(_row())
    assert "fan@example.com" not in paid.emails, "the address route must close too"


def test_a_refund_before_the_move_ends_it_too(monkeypatch) -> None:
    pass_ = bought(latest_invoice={"id": "in_paid",
                                   "charge": _charge(refunded=True, amount_refunded=3900)})
    _stripe_reads(monkeypatch, [pass_])
    assert not load_paid_from_stripe("sk").entitles(_row())


def test_a_lost_dispute_ends_it(monkeypatch) -> None:
    """A lost chargeback is not a refund in Stripe's data, and it sat on the
    same invisible charge."""
    _stripe_reads(monkeypatch, [moved()], _charge(disputed=True))
    paid = load_paid_from_stripe("sk")
    assert SUB in paid.refunded and not paid.entitles(_row())


def test_a_partial_refund_does_not(monkeypatch) -> None:
    """RULE E1: a pro-rata goodwill adjustment is not goodbye."""
    _stripe_reads(monkeypatch, [moved()], _charge(amount_refunded=1000))
    assert load_paid_from_stripe("sk").entitles(_row())


def test_a_cancelled_pass_keeps_its_season(monkeypatch) -> None:
    """Stripe keeps it live until the period they paid for ends. Ending it is
    Stripe's word, so nothing here computes a date."""
    _stripe_reads(monkeypatch, [moved(cancel_at_period_end=True)])
    assert load_paid_from_stripe("sk").entitles(_row())
    _stripe_reads(monkeypatch, [moved(status="canceled")])
    assert not load_paid_from_stripe("sk").entitles(_row())


def test_no_extra_read_for_anybody_else(monkeypatch) -> None:
    """Only a trial with a charge-less latest invoice costs a request, so an
    account with no pass makes exactly the calls it made."""
    asked = _stripe_reads(monkeypatch, [bought()])
    load_paid_from_stripe("sk")
    assert not any("/invoices" in url for url in asked)


def test_a_real_free_trial_took_no_money_and_stays_entitled(monkeypatch) -> None:
    """Nothing paid, nothing to have refunded. "trialing counts" stands."""
    monkeypatch.setattr(subscriptions, "_stripe_get", lambda url, key: {"data": []})
    view = purchase_view(moved(), "sk")
    assert view["latest_invoice"]["id"] == "in_zero"
    assert subscriptions.fully_refunded(view) is False


def test_a_failed_read_refuses_rather_than_guessing_not_refunded(monkeypatch) -> None:
    """A run that cannot tell does not get to serve. 403 names the permission
    (run/intake.py dispute_alarm)."""
    def get(url, key):
        if "/invoices" in url:
            raise SubscriptionError("HTTP 403", status=403)
        return {"data": [moved()] if "status=trialing" in url else [], "has_more": False}

    monkeypatch.setattr(subscriptions, "_stripe_get", get)
    with pytest.raises(SubscriptionError):
        load_paid_from_stripe("sk")


def test_an_unreadable_invoice_list_is_not_an_empty_one(monkeypatch) -> None:
    monkeypatch.setattr(subscriptions, "_stripe_get", lambda url, key: {"oops": True})
    with pytest.raises(SubscriptionError):
        purchase_view(moved(), "sk")


# --------------------------------------------------------------------- #
# what a report says
# --------------------------------------------------------------------- #

def test_the_last_report_says_nothing_false_about_the_renewal() -> None:
    """"Renews once a year, on the day you bought it" is the season plan's
    sentence, and false of this pass, which has its own."""
    meta = {"solo": True, "week": 18, "last_week": 18, "plan": _row().report_plan}
    assert meta["plan"] == "season"
    pass_meta = {**meta, "plan": _row(season_2027=True).report_plan}
    assert pass_meta["plan"] == SEASON_2027
    assert "on the day you bought it" in " ".join(season_end_lines(meta))
    words = " ".join(season_end_lines({**pass_meta, "update_url": "https://x.test/u"}))
    assert "on the day you bought it" not in words
    assert "Unless you cancel, your pass renews each August 15, starting in 2028" in words
    assert "This is the season's last report" in words and "After your draft" in words
    from render.report import PASS_2027_PLAN
    assert PASS_2027_PLAN == SEASON_2027
    # One-time wording is a one-time pass's: this one renews.
    assert "nothing renews" not in words


def test_a_pass_payers_plan_word_is_not_taken_over() -> None:
    """A merged League Pass payer keeps "pass": their seats depend on it."""
    assert _row(season_2027=True, billing="pass").report_plan == "pass"


def test_the_marker_survives_the_registry_round_trip() -> None:
    from run.rosters import _parse_entry, to_json
    subscriber = _row(season_2027=True, slots=("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K"))
    from test_solo_run import SLOTS
    subscriber = replace(subscriber, slots=tuple(SLOTS))
    assert _parse_entry(to_json([subscriber])[0], 0).season_2027 is True
    plain = replace(subscriber, season_2027=False)
    assert "season_2027" not in to_json([plain])[0]


# --------------------------------------------------------------------- #
# the words on Stripe's own page
# --------------------------------------------------------------------- #

def test_a_y_link_gets_the_renewal_words_never_the_one_payment_words() -> None:
    """Read off the plan alone, the script writes "Nothing renews" onto the one
    link that renews, over the disclosure a buyer must see."""
    from infra.stripe_paylink_text import (SEASON_2027_PLAN, SEASON_2027_TOS, MESSAGES,
                                           STRIPE_TEXT_LIMIT, fields, targets)
    links = dict(targets(MAP_2027))
    assert links[PASS_2027_LINK] == SEASON_2027_PLAN and links[SEASON_LINK] == "season"
    form = fields(links[PASS_2027_LINK])
    words = form["custom_text[submit][message]"]
    assert words != MESSAGES["season"] and "Nothing renews" not in words
    for needed in ("$39 USD", "August 15, 2028", "each August", "15 to 45 days",
                   "cancel any time", "one per person"):
        assert needed in words
    tick = form["custom_text[terms_of_service_acceptance][message]"]
    assert tick == SEASON_2027_TOS and "$39 USD" in tick and "August 15, 2028" in tick
    assert "18 or older" in tick and "[Terms](" in tick
    assert form["consent_collection[terms_of_service]"] == "required"
    assert max(len(words), len(tick)) <= STRIPE_TEXT_LIMIT


def test_a_subscription_link_is_not_sent_a_payment_mode_field() -> None:
    from infra.stripe_paylink_text import SEASON_2027_PLAN, fields
    assert "customer_creation" not in fields(SEASON_2027_PLAN)


def test_the_map_without_y_targets_what_it_did() -> None:
    from infra.stripe_paylink_text import targets
    assert targets(MAP_2026) == [(SEASON_LINK, "season"), ("plink_O", "season"),
                                 (PASS_LINK, "league_pass")]


def test_the_price_on_every_surface_is_one_figure() -> None:
    from run.economics import SEASON
    assert SEASON_2027_PRICE_CENTS == round(SEASON * 100)
    assert SEASON_2027_PRICE == f"${SEASON_2027_PRICE_CENTS // 100}"


# --------------------------------------------------------------------- #
# the launch gate
# --------------------------------------------------------------------- #

@pytest.fixture
def site(tmp_path, monkeypatch):
    """A site the other builder's constants can be written into."""
    (tmp_path / "join").mkdir()

    def write(landing: str = "", join: str = "", terms: str = "<p>Nothing here.</p>"):
        (tmp_path / "index.html").write_text(landing, encoding="utf-8")
        (tmp_path / "join" / "index.html").write_text(join, encoding="utf-8")
        (tmp_path / "terms.html").write_text(terms, encoding="utf-8")

    monkeypatch.setattr(launch_check, "SITE", tmp_path)
    monkeypatch.delenv("STRIPE_PAYMENT_LINKS", raising=False)
    write()
    return write


ON = "const SEASON_2027_READY = true;"
OFF = "const SEASON_2027_READY = false;"
OFFER_TERMS = "<p>The <b>2027 Season Pass</b> renews on August 15, 2028.</p>"


def _statuses(gates) -> dict[str, str]:
    return {gate.name: gate.status for gate in gates}


def test_the_gate_skips_and_says_so_until_the_constants_exist(site) -> None:
    gates = launch_check.check_season_2027()
    assert [g.status for g in gates] == ["SKIP"]
    assert "not on the page yet" in gates[0].detail
    assert "SEASON_2027_READY" in gates[0].detail and "STRIPE_LINK_2027" in gates[0].detail


def test_todays_real_pages_do_not_fail_the_gate() -> None:
    assert all(g.status != "FAIL" for g in launch_check.check_season_2027())


@pytest.mark.parametrize("line", [
    'const SEASON_2027_READY = true;', '    const SEASON_2027_READY = true;',
    'let SEASON_2027_READY = true', "var SEASON_2027_READY = 'true';",
    'window.SEASON_2027_READY = true;', 'const FLAGS = { SEASON_2027_READY: true };',
    '"SEASON_2027_READY": true,',
])
def test_the_flag_is_read_wherever_it_is_kept(line) -> None:
    """js_constants' `[A-Z_]+` cannot match a digit, so through it this gate
    would skip with the offer on sale."""
    assert launch_check.js_constants(line) .get("SEASON_2027_READY") is None
    assert launch_check.site_constant(line, "SEASON_2027_READY") == "true"


@pytest.mark.parametrize("line", ["// SEASON_2027_READY = true when the link exists",
                                  " * SEASON_2027_READY: true flips the card"])
def test_a_comment_naming_the_flag_does_not_set_it(line) -> None:
    assert launch_check.site_constant(line, "SEASON_2027_READY") is None


def test_flag_on_with_no_link_fails(site) -> None:
    site(ON, 'const STRIPE_LINK_2027 = "";')
    assert "FAIL" in _statuses(launch_check.check_season_2027()).values()


def test_a_link_with_the_flag_off_fails(site) -> None:
    site(OFF, 'const STRIPE_LINK_2027 = "https://buy.stripe.com/x";')
    assert _statuses(launch_check.check_season_2027())[
        "The 2027 Season Pass switches agree"] == "FAIL"


def test_y_in_the_secret_with_no_link_fails(site, monkeypatch) -> None:
    site(OFF, 'const STRIPE_LINK_2027 = "";')
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2027)
    gates = launch_check.check_season_2027()
    bad = [g for g in gates if g.status == "FAIL"]
    assert bad and "STRIPE_LINK_2027 is empty" in bad[0].detail


def test_an_empty_y_in_the_secret_fails(site, monkeypatch) -> None:
    site(OFF, 'const STRIPE_LINK_2027 = "";')
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"{MAP_2026},y:")
    bad = [g for g in launch_check.check_season_2027() if g.status == "FAIL"]
    assert bad and "names no payment link" in bad[0].detail


def test_a_link_with_no_y_in_the_secret_fails(site, monkeypatch) -> None:
    """Every purchase would be PAID-UNATTRIBUTED."""
    site(ON, 'const STRIPE_LINK_2027 = "https://buy.stripe.com/x";', OFFER_TERMS)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2026)
    bad = [g for g in launch_check.check_season_2027() if g.status == "FAIL"]
    assert bad and "PAID-UNATTRIBUTED" in bad[0].detail


def test_on_sale_while_the_terms_dont_describe_it_fails(site, monkeypatch) -> None:
    """Buyers tick a box agreeing to terms that don't describe what they bought."""
    site(ON, 'const STRIPE_LINK_2027 = "https://buy.stripe.com/x";')
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2027)
    assert _statuses(launch_check.check_season_2027())[
        "The terms describe the 2027 Season Pass before it is sold"] == "FAIL"


def test_every_switch_agreeing_passes(site, monkeypatch) -> None:
    site(ON, ON + '\nconst STRIPE_LINK_2027 = "https://buy.stripe.com/x";', OFFER_TERMS)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2027)
    assert set(_statuses(launch_check.check_season_2027()).values()) == {"PASS"}


def test_the_join_page_disagreeing_with_the_landing_fails(site) -> None:
    site(OFF, ON + '\nconst STRIPE_LINK_2027 = "";')
    assert _statuses(launch_check.check_season_2027())[
        "Landing and join page agree on the 2027 Season Pass"] == "FAIL"


def test_a_renewal_after_the_opener_is_an_alarm_for_a_person(monkeypatch) -> None:
    import run.solo as solo
    monkeypatch.setattr(solo, "season_ends", lambda *a, **k: {"2028": "2029-01-07"})
    monkeypatch.setattr(solo, "week_first_kickoff",
                        lambda *a, **k: datetime(2028, 8, 1, tzinfo=timezone.utc))
    gate = launch_check._renewal_date_gates(SEASON_2027_FIRST_RENEWAL)[0]
    assert gate.status == "FAIL" and "a person must decide" in gate.detail


def test_no_2028_schedule_is_no_gate(monkeypatch) -> None:
    import run.solo as solo
    monkeypatch.setattr(solo, "season_ends", lambda *a, **k: {"2026": "2027-01-10"})
    assert launch_check._renewal_date_gates(SEASON_2027_FIRST_RENEWAL) == []


def test_the_billing_page_must_not_be_able_to_end_a_trial() -> None:
    """Stripe: customer modifications to a `trialing` subscription end the free
    trial and create an invoice for immediate payment."""
    audit = launch_check.audit_portal_for_trials
    assert audit({"features": {"subscription_update": {"enabled": False}}}) == []
    assert audit({"features": {"subscription_update": {
        "enabled": True, "trial_update_behavior": "continue_trial"}}}) == []
    assert audit({"features": {"subscription_update": {"enabled": True}}})


def test_stripes_side_is_read_only_when_a_y_link_is_here(monkeypatch) -> None:
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2026)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    assert launch_check.check_season_2027_stripe() == []


def test_stripes_side_fails_a_link_at_the_wrong_price(monkeypatch) -> None:
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", MAP_2027)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")

    def get(url, key):
        if "line_items" in url:
            return 200, {"data": [{"price": {"unit_amount": 2900,
                                             "recurring": {"interval": "year"}}}]}
        if "configurations" in url:
            return 200, {"data": [{"features": {}}]}
        return 403, None

    monkeypatch.setattr(launch_check, "_get_json", get)
    gates = _statuses(launch_check.check_season_2027_stripe())
    assert gates["The 2027 Season Pass link sells the yearly $39 price"] == "FAIL"
    assert gates["Stripe's billing page cannot end a 2027 Season Pass's trial"] == "PASS"
    assert gates["This key can read invoices, which a deferred pass's refund needs"] == "FAIL"


def test_the_gate_is_registered_in_every_run() -> None:
    source = Path(launch_check.__file__).read_text(encoding="utf-8")
    assert '("2027 Season Pass", check_season_2027)' in source
    assert '("2027 Season Pass in Stripe", check_season_2027_stripe)' in source


# --------------------------------------------------------------------- #
# what the owner sees
# --------------------------------------------------------------------- #

def _sold(sid: str, charge: dict | None = None, **over) -> dict:
    return {"id": sid, "status": "complete", "payment_status": "paid", "payment_link": PASS_2027_LINK,
            "client_reference_id": REF, "currency": "usd", "amount_total": 3900,
            "invoice": {"id": "in_1", "charge": charge or _charge()}, **over}


TODAY = date(2026, 11, 1)


def test_the_obligation_counts_what_is_still_owed() -> None:
    sessions = [_sold("cs_1"), _sold("cs_2"),
                _sold("cs_3", _charge(refunded=True, amount_refunded=3900)),
                _sold("cs_4", _charge(amount_refunded=1000)),
                _sold("cs_5", payment_link=SEASON_LINK),
                _sold("cs_6", payment_status="unpaid"),
                _sold("cs_7", currency="cad")]
    summary = stats.season_2027_summary(sessions, {PASS_2027_LINK}, TODAY)
    assert summary == {"held": 4, "refunded": 1, "other_currency": 1, "collected": 107.0,
                       "deferred": 107.0, "delivered": False}
    line = stats.season_2027_line(summary)
    assert "4 held, 1 refunded" in line
    assert "$107.00 collected for 2027 seasons not yet delivered" in line
    assert "@" not in line


def test_a_lost_chargeback_owes_nothing() -> None:
    lost = _sold("cs_1", _charge(disputed=True))
    summary = stats.season_2027_summary([lost], {PASS_2027_LINK}, TODAY, lookup=lambda c: "lost")
    assert (summary["held"], summary["refunded"], summary["deferred"]) == (0, 1, 0.0)


def test_the_obligation_ends_when_the_season_has_been_played() -> None:
    summary = stats.season_2027_summary([_sold("cs_1")], {PASS_2027_LINK}, date(2028, 2, 1),
                                        ended=date(2028, 1, 9))
    assert summary["deferred"] == 0.0 and summary["collected"] == 39.0
    assert "nothing deferred" in stats.season_2027_line(summary)


def test_an_unknown_end_stays_owed() -> None:
    """No schedule means not delivered, never a quiet zero."""
    summary = stats.season_2027_summary([_sold("cs_1")], {PASS_2027_LINK}, date(2030, 1, 1))
    assert summary["deferred"] == 39.0 and not summary["delivered"]


def test_none_sold_says_so() -> None:
    assert "none yet" in stats.season_2027_line(
        stats.season_2027_summary([], {PASS_2027_LINK}, TODAY))


def _summary(monkeypatch, links) -> tuple[list[str], list[str]]:
    asked: list[str] = []

    def get(url, key):
        asked.append(url)
        return {"data": [_sold("cs_1")] if "data.invoice.charge" in url else [],
                "has_more": False}

    monkeypatch.setattr(subscriptions, "_stripe_get", get)
    monkeypatch.setattr(stats, "season_2027_end", lambda: None)
    lines = stats.stripe_summary("sk", datetime(2026, 11, 1, tzinfo=timezone.utc),
                                 one_time=True, season_2027=links)
    return lines, asked


def test_make_stats_shows_it_only_when_the_offer_is_on(monkeypatch) -> None:
    lines, asked = _summary(monkeypatch, {PASS_2027_LINK})
    assert any("$39.00 collected for 2027 seasons" in line for line in lines)
    lines, asked = _summary(monkeypatch, ())
    assert not any("2027 Season Pass" in line for line in lines)
    assert not any("data.invoice.charge" in url for url in asked)


def test_the_dashboard_card_appears_only_with_the_offer() -> None:
    from run import dashboard
    from run.dashboard import season_2027_card

    def source(data):
        return dashboard._source("stripe", data=data, read_at=NOW)

    assert season_2027_card({"stripe": source({"sessions": []})}) == ""
    summary = stats.season_2027_summary([_sold("cs_1")], {PASS_2027_LINK}, TODAY)
    card = season_2027_card({"stripe": source({"season_2027": summary})})
    assert "$39.00 collected for 2027 seasons not yet delivered" in card
    failed = season_2027_card({"stripe": source({"season_2027": {"error": "HTTP 403"}})})
    assert "Invoices: Read" in failed and "HTTP 403" in failed


def test_the_model_states_the_trade() -> None:
    """Prepaid, the pass adds a little today and gives up a year if the buyer
    would have come back, so the break-even is the number worth keeping."""
    from run.economics import (REBUY_RATES, REST_OF_SEASON, SEASON, net_per_sale, rebuy_value,
                               season_2027_prepay, summary_lines)
    prepay = season_2027_prepay()
    assert prepay["net"] == net_per_sale(SEASON)
    assert prepay["rest_of_season_net"] == net_per_sale(REST_OF_SEASON, one_time=True)
    assert prepay["extra"] > 0 and 0 < prepay["break_even"] < min(REBUY_RATES)
    # At exactly the break-even rate the two are worth the same, to the cent.
    even = rebuy_value(REST_OF_SEASON, SEASON, prepay["break_even"])
    assert abs(even - prepay["net"]) < 0.02
    assert any("2027 Season Pass" in gate for gate, _s, _d in summary_lines())


def test_the_terms_stay_unpublished() -> None:
    """Consent is to what the page says. The wording waits in LAUNCH.md for the
    lawyer, and nothing about this offer reaches terms.html before then."""
    root = Path(__file__).resolve().parent.parent
    launch = (root / "LAUNCH.md").read_text(encoding="utf-8")
    assert "## 13. Turning on the 2027 Season Pass" in launch
    section = launch[launch.index("## 13. Turning on"):]
    for needed in ("§3", "§4", "§5", "TERMS_VERSION", "TERMS_HISTORY",
                   "tests/test_promises_legal.py", "Invoices: Read", "trial"):
        assert needed in section
    order = [section.index(step) for step in ("### Step 1: the lawyer", "### Step 2: the terms",
                                              "### Step 3: Stripe, in test mode",
                                              "### Step 6: the secret", "### Step 7: send me")]
    assert order == sorted(order), "the owner's checklist runs in this order"


def test_a_stored_timestamp_is_not_this_test_files_clock() -> None:
    """The fixtures buy on Oct 30 2026, inside every window they name."""
    assert timedelta(seconds=TARGET - BOUGHT).days < 730
