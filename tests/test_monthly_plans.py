"""Monthly pricing (owner decision, Oct 31 2026): a monthly plan in place of the
one-time passes, because a fixed price buys less every week.

What these hold:
- billing ends with Week 17's report, and no renewal follows it;
- a plan WE stopped still gets the season's last report, and one its buyer
  cancelled does not;
- a refund ends the plan, so a buyer is never billed for reports that stopped;
- no page sells a one-time pass, and every price card says when billing stops.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import run.subscriptions as subs
from render.report import SEASON_END_BILLING
from render.welcome import MONTHLY_PRICE, PASS_PRICE, welcome_message
from run import economics
from run.billing import (ROSTER_METADATA_KEY, STOP_METADATA_KEY, final_send, last_send,
                         needs_stop, title_send)
from run.checkout import link_map_problems, parse_link_plans
from run.subscriptions import (SEASON_STOP_GRACE_DAYS, SEASON_STOP_KEY, load_paid_from_stripe,
                               stopped_for_season)

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
CACHE = ROOT / "data" / "raw" / "nflverse"
needs_schedule = pytest.mark.skipif(not (CACHE / "games.csv").is_file(),
                                    reason="no cached nflverse schedule (data/ is gitignored)")
TITLE_DUE = datetime(2026, 12, 29, 12, 17, tzinfo=timezone.utc)


def sub(period_end: datetime, **over) -> dict:
    row = {"id": "sub_1", "status": "active", "cancel_at": None, "cancel_at_period_end": False,
           "customer": {"id": "cus_1", "metadata": {ROSTER_METADATA_KEY: "r3-mc-x"}},
           "items": {"data": [{"price": {"recurring": {"interval": "month"}},
                               "current_period_end": int(period_end.timestamp())}]}}
    row.update(over)
    return row


# --------------------------------------------------------------------- #
# billing ends with Week 17's report
# --------------------------------------------------------------------- #

@needs_schedule
def test_billing_ends_with_week_17s_report_not_the_last() -> None:
    assert last_send(CACHE, "2026") == date(2027, 1, 5)
    assert title_send(CACHE, "2026") == date(2026, 12, 29)
    at, season = final_send(CACHE, date(2026, 11, 1))
    assert season == "2026" and at.date() == date(2026, 12, 29)


def test_a_january_renewal_never_happens() -> None:
    """The fix the owner approved: a Dec 1 buyer's period ends Jan 1. Renewing
    there took $14.99 just before the one report left."""
    due, notes = needs_stop([sub(datetime(2027, 1, 1, 15, tzinfo=timezone.utc))], TITLE_DUE)
    assert [s["id"] for s in due] == ["sub_1"] and not notes


def test_a_renewal_before_week_17s_report_still_happens() -> None:
    due, _ = needs_stop([sub(datetime(2026, 12, 10, 15, tzinfo=timezone.utc))], TITLE_DUE)
    assert due == []


@pytest.mark.parametrize("joined,charges", [
    (date(2026, 11, 3), 2),     # used to be 3, the last on title-game weekend
    (date(2026, 11, 10), 2),
    (date(2026, 12, 1), 1),     # used to be 2, the last on Jan 1
    (date(2026, 12, 29), 1),
])
def test_what_a_buyer_pays_by_the_day_they_join(joined, charges) -> None:
    assert economics.monthly_charges(joined, date(2026, 12, 29))[0] == charges


# --------------------------------------------------------------------- #
# a plan we stopped keeps the last report
# --------------------------------------------------------------------- #

NOW = datetime(2027, 1, 5, 12, tzinfo=timezone.utc)
ENDED = int(datetime(2026, 12, 30, 15, tzinfo=timezone.utc).timestamp())


def ended(**over) -> dict:
    row = {"status": "canceled", "ended_at": ENDED, "metadata": {SEASON_STOP_KEY: "1"}}
    row.update(over)
    return row


def test_the_metadata_key_is_the_one_billing_writes() -> None:
    assert STOP_METADATA_KEY == SEASON_STOP_KEY


def test_a_plan_we_stopped_is_owed_week_18() -> None:
    assert stopped_for_season(ended(), NOW)


@pytest.mark.parametrize("plan", [
    ended(metadata={}),                     # its buyer cancelled it
    ended(metadata=None),
    ended(ended_at=None),
    ended(status="active"),
])
def test_anything_else_is_not(plan) -> None:
    assert not stopped_for_season(plan, NOW)


def test_the_grace_runs_out_by_itself() -> None:
    late = datetime.fromtimestamp(ENDED, timezone.utc) + timedelta(days=SEASON_STOP_GRACE_DAYS, hours=1)
    assert not stopped_for_season(ended(), late)


def test_grace_covers_week_18s_tuesday_and_saturday_from_the_earliest_end() -> None:
    assert SEASON_STOP_GRACE_DAYS * 86400 >= (
        datetime(2027, 1, 9, 17, tzinfo=timezone.utc) - TITLE_DUE).total_seconds()


def _stripe(monkeypatch, plans: list[dict]) -> None:
    def get(url, key):
        path, query = urlsplit(url).path, parse_qs(urlsplit(url).query)
        if path.endswith("/subscriptions"):
            return {"data": [p for p in plans if p["status"] == query["status"][0]],
                    "has_more": False}
        return {"data": [], "has_more": False}
    monkeypatch.setattr(subs, "_stripe_get", get)


def _customer() -> dict:
    return {"id": "cus_1", "email": "buyer@example.com", "metadata": {}}


def _paid(refunded: bool = False) -> dict:
    return {"id": "in_1", "amount_paid": 1499,
            "charge": {"id": "ch_1", "amount": 1499, "refunded": refunded,
                       "amount_refunded": 1499 if refunded else 0}}


def test_entitlement_reads_a_stopped_plan_and_only_that(monkeypatch) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    _stripe(monkeypatch, [
        {"id": "sub_stopped", "status": "canceled", "ended_at": now - 86400,
         "metadata": {SEASON_STOP_KEY: "1"}, "customer": _customer(), "latest_invoice": _paid()},
        {"id": "sub_cancelled", "status": "canceled", "ended_at": now - 86400, "metadata": {},
         "customer": _customer(), "latest_invoice": _paid()},
    ])
    assert load_paid_from_stripe("sk_test").subscription_ids == frozenset({"sub_stopped"})


def test_a_refund_beats_the_grace(monkeypatch) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    _stripe(monkeypatch, [
        {"id": "sub_refunded", "status": "canceled", "ended_at": now - 86400,
         "metadata": {SEASON_STOP_KEY: "1"}, "customer": _customer(),
         "latest_invoice": _paid(refunded=True)}])
    paid = load_paid_from_stripe("sk_test")
    assert paid.subscription_ids == frozenset() and "sub_refunded" in paid.refunded


# --------------------------------------------------------------------- #
# a refund ends the plan
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("state", ["refunded", "lost"])
def test_a_refunded_plan_gets_its_stop_whatever_the_calendar_says(state) -> None:
    """Refund alone stops the reports and leaves Stripe billing next month."""
    plan = sub(datetime(2026, 12, 10, 15, tzinfo=timezone.utc))
    due, _ = needs_stop([plan], TITLE_DUE, lambda _s: state)
    assert [s["id"] for s in due] == ["sub_1"]


@pytest.mark.parametrize("state", [None, "disputed"])
def test_an_open_dispute_or_a_paid_plan_is_left_alone(state) -> None:
    plan = sub(datetime(2026, 12, 10, 15, tzinfo=timezone.utc))
    assert needs_stop([plan], TITLE_DUE, lambda _s: state)[0] == []


def test_a_plan_already_ending_is_not_read_again() -> None:
    asked = []
    plan = sub(datetime(2026, 12, 10, 15, tzinfo=timezone.utc), cancel_at_period_end=True)
    needs_stop([plan], TITLE_DUE, lambda s: asked.append(s) or "refunded")
    assert asked == []


# --------------------------------------------------------------------- #
# the payment-link map
# --------------------------------------------------------------------- #

def test_the_2026_map_is_monthly_and_the_league_pass() -> None:
    raw = "m:plink_month,p:plink_league"
    assert link_map_problems(raw) == []
    assert parse_link_plans(raw) == {"plink_month": "monthly", "plink_league": "league_pass"}


@pytest.mark.parametrize("raw,words", [
    ("p:plink_league", "no m: link"),
    ("m:plink_month", "no p: link"),
    ("m:plink_a,m:plink_b,p:plink_c", "2 m: links"),
])
def test_a_map_missing_a_plan_is_named(raw, words) -> None:
    assert any(words in problem for problem in link_map_problems(raw))


# --------------------------------------------------------------------- #
# what a buyer reads
# --------------------------------------------------------------------- #

def _pages() -> list[Path]:
    return sorted(SITE.rglob("*.html"))


def _visible(path: Path) -> str:
    page = path.read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", page, flags=re.S)


@pytest.mark.parametrize("retired", ["Rest-of-Season", "Playoff Pass", "One payment", "one payment",
                                     "othing renews", "othing to cancel"])
def test_no_page_sells_a_one_time_pass(retired) -> None:
    pages = _pages()
    assert len(pages) > 15
    for path in pages:
        if path.name == "terms.html":
            continue                     # "the one exception" is about a seat
        assert retired not in _visible(path), (path.name, retired)


@pytest.mark.parametrize("price", [r"\$29\b", r"\$69\b", r"\$19\b(?!\d)(?!\.)"])
def test_no_page_quotes_a_retired_price(price) -> None:
    for path in _pages():
        if path.parts[-2] == "compare":
            continue                     # other people's prices
        assert not re.search(price, _visible(path)), (path.name, price)


def test_every_price_card_says_when_billing_stops() -> None:
    landing = (SITE / "index.html").read_text(encoding="utf-8")
    card = landing.split('id="pass-card"')[1].split("</ul>")[0]
    assert f"{MONTHLY_PRICE} <small>/ month" in card
    assert "Stops on its own after your title game" in card
    league = (SITE / "league-pass.html").read_text(encoding="utf-8")
    assert f'class="amt">{PASS_PRICE} <small>a month for the whole league' in league
    assert "Stops on its own after the title game. Cancel any time." in league


def test_the_buy_page_discloses_above_the_button() -> None:
    join = (SITE / "join" / "index.html").read_text(encoding="utf-8")
    block = re.sub(r"\s+", " ", join.split('id="terms-line"')[1].split("</p>")[0])
    assert f"{MONTHLY_PRICE} USD a month until you cancel" in block
    assert "billing stops on its own after your title game" in block
    assert "nothing is charged after Week 17's report goes out" in block
    assert "Refunds are no-questions" in block
    assert f'Unlock my lineups — {MONTHLY_PRICE}/mo' in join


@pytest.mark.parametrize("plan,price", [("monthly", MONTHLY_PRICE), ("league_pass", PASS_PRICE)])
def test_the_welcome_states_the_charge_and_when_it_stops(plan, price) -> None:
    text = welcome_message("x@example.com", plan, "abcdef0123", "2026").text
    flat = re.sub(r"\s+", " ", text)
    assert f"{price} USD" in flat and "billing stops on its own after your title game" in flat
    assert "renews once a year" not in flat and "one payment" not in flat


def test_the_last_report_says_nothing_else_will_bill() -> None:
    for plan in ("monthly", "pass"):
        assert "stopped billing on its own" in SEASON_END_BILLING[plan]
    assert "renews" not in SEASON_END_BILLING["pass"]


def test_stripes_pay_button_text_says_when_it_stops() -> None:
    import infra.stripe_paylink_text as text
    for plan, price, per in (("monthly", MONTHLY_PRICE, "person"),
                             ("league_pass", PASS_PRICE, "league")):
        assert f"{price} USD a month" in text.SUBMIT_TEXT[plan]
        assert "Billing stops on its own" in text.SUBMIT_TEXT[plan]
        assert f"one per {per}" in text.SUBMIT_TEXT[plan]
        assert f"{price} USD every month" in text.TOS_TEXT[plan]
        # customer_creation is refused on a subscription link.
        assert "customer_creation" not in text.fields(plan)


# --------------------------------------------------------------------- #
# the money
# --------------------------------------------------------------------- #

def test_the_prices_on_the_pages_are_the_ones_modelled() -> None:
    assert MONTHLY_PRICE == f"${economics.MONTHLY}"
    assert PASS_PRICE == f"${economics.LEAGUE_MONTHLY}"


def test_a_buyer_is_worth_more_than_one_charge_and_less_than_two() -> None:
    one = economics.MONTHLY - economics.stripe_fee(economics.MONTHLY)
    assert 1 < economics.expected_charges() < 2
    assert economics.net_per_sale(economics.MONTHLY) < economics.net_per_buyer(economics.MONTHLY) < 2 * one


def test_leaving_early_costs_what_it_should(monkeypatch) -> None:
    before = economics.expected_charges()
    monkeypatch.setattr(economics, "LEAVE_AFTER_FIRST", 0.5)
    assert economics.expected_charges() < before
