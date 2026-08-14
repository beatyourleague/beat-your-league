"""Tests for the automatic signup pipeline: ref codec, Stripe sweep, seats,
verification, season roll, and the registry projection.

Nothing here touches the network. The Stripe and Sleeper layers are faked at
their seams so every branch — including the ones that only happen when a vendor
is having a bad day — is reachable offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import run.sync as sync
from run.refs import (LEAGUE_PASS, MONTHLY, SEASON, RefError, decode, encode)
from run.registry import RegistryError, Subscriber, load_registry
from run.subscriptions import PaidList

USER = "457511950237696"
LEAGUE = "289646328504385536"
RIVAL = "189140835533586432"


# --------------------------------------------------------------------- #
# the ref codec — the contract between the browser and Tuesday
# --------------------------------------------------------------------- #

def test_round_trip_carries_the_whole_signup() -> None:
    ref = encode(SEASON, USER, LEAGUE, rival_owner_id=RIVAL)
    assert ref == f"s-{USER}-{LEAGUE}-{RIVAL}"
    back = decode(ref)
    assert (back.plan, back.user_id, back.league_id, back.rival_owner_id) == \
        (SEASON, USER, LEAGUE, RIVAL)
    assert back.rival_roster_id is None


def test_the_ref_fits_stripes_limits_with_room_to_spare() -> None:
    """200 chars and [A-Za-z0-9_-]. Stripe drops anything else SILENTLY while
    still showing a working payment page, so this is the constraint that must
    never be violated."""
    for plan in (SEASON, MONTHLY, LEAGUE_PASS):
        ref = encode(plan, "9" * 20, "8" * 20, rival_owner_id="7" * 20)
        assert len(ref) <= 200
        assert sync.__name__ and __import__("re").fullmatch(r"[A-Za-z0-9_-]+", ref)


def test_orphan_team_rivals_survive_as_roster_numbers() -> None:
    ref = encode(SEASON, USER, LEAGUE, rival_roster_id=6)
    assert ref.endswith("-r6")
    back = decode(ref)
    assert back.rival_roster_id == 6 and back.rival_owner_id is None


def test_a_league_pass_ref_is_also_an_individual_signup() -> None:
    """One purchase, two meanings: the commissioner's own report AND the
    league's coverage."""
    back = decode(encode(LEAGUE_PASS, USER, LEAGUE, rival_owner_id=RIVAL))
    assert back.is_league_pass
    assert back.user_id == USER and back.rival_owner_id == RIVAL
    # Their own seat is an individual entry — they paid for it themselves, so
    # it must not be recorded as a covered seat with no payer.
    assert back.registry_plan == "season"


@pytest.mark.parametrize("bad", [
    "", "nonsense", "s-1-2", "s-abc-{}-{}".format(LEAGUE, RIVAL),
    "x-{}-{}-{}".format(USER, LEAGUE, RIVAL),        # unknown plan
    "s-{}-{}-{}".format(USER, "12", RIVAL),          # league too short
    "s-{}-{}-r0".format(USER, LEAGUE),               # roster 0 is not a team
    "s-{}-{}-notarival".format(USER, LEAGUE),
    "s-{}-{}-{}-extra".format(USER, LEAGUE, RIVAL),  # too many fields
    "s-{}-{}-{}!".format(USER, LEAGUE, RIVAL),       # outside Stripe's charset
])
def test_an_unreadable_ref_is_refused_not_guessed(bad: str) -> None:
    """A guessed league id mails somebody another manager's team."""
    with pytest.raises(RefError):
        decode(bad)


def test_encode_refuses_to_build_something_stripe_would_drop() -> None:
    with pytest.raises(RefError):
        encode(SEASON, "not-an-id", LEAGUE, rival_owner_id=RIVAL)
    with pytest.raises(RefError):
        encode(SEASON, USER, LEAGUE)          # no rival at all


def test_the_browser_and_python_agree_on_the_format() -> None:
    """The picker builds this string in JavaScript and we decode it in Python;
    nothing type-checks across that gap, so pin it with the real page."""
    join = (Path(__file__).resolve().parent.parent / "site" / "join" /
            "index.html").read_text(encoding="utf-8")
    assert 'REF_PREFIX + "-" + state.user.user_id + "-" + state.league.league_id +' in join
    assert '"-" + (state.rival.owner_id ? state.rival.owner_id : "r" + state.rival.roster_id)' in join
    for prefix in ('WANTS_PASS ? "p"', '(WANTS_MONTHLY ? "m" : "s")'):
        assert prefix in join, f"picker lost the {prefix} plan prefix"


# --------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------- #

def _session(ref, email="buyer@example.com", customer="cus_ABCD1234",
             created=1_700_000_000, sid="cs_1"):
    return {"id": sid, "created": created, "client_reference_id": ref,
            "customer": {"id": customer, "email": email, "metadata": {}}}


def _page(items, has_more=False):
    return {"data": items, "has_more": has_more}


class FakeSleeper:
    """Just enough of SleeperClient for verification and the season roll."""

    def __init__(self, rosters=None, leagues=None, seasons=None):
        self._rosters = rosters if rosters is not None else [
            {"roster_id": 1, "owner_id": USER},
            {"roster_id": 6, "owner_id": RIVAL},
        ]
        self._leagues = leagues or {}
        self._seasons = seasons or {LEAGUE: "2026"}
        self.calls = []

    def rosters(self, league_id, **kw):
        self.calls.append(("rosters", league_id))
        if league_id not in self._seasons:
            from ingest.sleeper import SleeperNotFound
            raise SleeperNotFound(league_id)
        return self._rosters

    def league(self, league_id, **kw):
        if league_id not in self._seasons:
            from ingest.sleeper import SleeperError
            raise SleeperError(league_id)
        return {"league_id": league_id, "season": self._seasons[league_id],
                "previous_league_id": self._leagues.get(league_id)}

    def user_leagues(self, user_id, season, **kw):
        return [{"league_id": lid, "previous_league_id": prev}
                for lid, prev in self._leagues.items()
                if self._seasons.get(lid) == season]

    def state(self, sport="nfl"):
        return {"league_season": "2026"}


def _signup(**over):
    base = dict(email="buyer@example.com", user_id=USER, league_id=LEAGUE,
                rival_owner_id=RIVAL, rival_roster_id=None, plan="season",
                source="stripe", seen_at="1700000000")
    base.update(over)
    return sync.Signup(**base)


# --------------------------------------------------------------------- #
# the Stripe sweep
# --------------------------------------------------------------------- #

def test_a_completed_checkout_becomes_a_signup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = encode(SEASON, USER, LEAGUE, rival_owner_id=RIVAL)
    monkeypatch.setattr(sync, "_stripe_get", lambda url, key: _page([_session(ref)]))
    monkeypatch.setattr(sync, "_promote", lambda *a: None)
    signups, watermark, problems = sync.sweep_stripe("sk")
    assert not problems
    assert len(signups) == 1
    assert signups[0].league_id == LEAGUE
    assert signups[0].stripe_customer_id == "cus_ABCD1234"
    assert watermark == 1_700_000_000


def test_a_payment_we_cannot_attribute_is_reported_never_dropped(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Somebody paid. Silence here means they get nothing and nobody knows."""
    monkeypatch.setattr(sync, "_stripe_get", lambda url, key: _page([
        _session(None, email="noref@example.com", sid="cs_noref"),
        _session("garbage-ref", email="bad@example.com", sid="cs_bad"),
    ]))
    monkeypatch.setattr(sync, "_promote", lambda *a: None)
    signups, _, problems = sync.sweep_stripe("sk")
    assert signups == []
    assert len(problems) == 2
    assert any("NO reference" in p and "noref@example.com" in p for p in problems)
    assert any("unreadable reference" in p for p in problems)
    assert all("paid" in p or "undeliverable" in p for p in problems)


def test_the_sweep_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    ref1 = encode(SEASON, USER, LEAGUE, rival_owner_id=RIVAL)
    ref2 = encode(SEASON, "111111111111", LEAGUE, rival_owner_id=RIVAL)
    pages = [_page([_session(ref1, sid="cs_1")], has_more=True),
             _page([_session(ref2, sid="cs_2", customer="cus_EFGH5678")])]
    seen = {"n": 0}

    def fake_get(url, key):
        page = pages[seen["n"]]
        seen["n"] += 1
        return page

    monkeypatch.setattr(sync, "_stripe_get", fake_get)
    monkeypatch.setattr(sync, "_promote", lambda *a: None)
    signups, _, _ = sync.sweep_stripe("sk")
    assert {s.user_id for s in signups} == {USER, "111111111111"}


def test_a_failed_promotion_does_not_lose_the_signup(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Promotion is durability, not the signup itself. Losing a paying customer
    because a metadata write 403'd would be absurd."""
    from run.subscriptions import SubscriptionError
    ref = encode(SEASON, USER, LEAGUE, rival_owner_id=RIVAL)
    monkeypatch.setattr(sync, "_stripe_get", lambda url, key: _page([_session(ref)]))

    def boom(*a):
        raise SubscriptionError("needs WRITE access to Customers")

    monkeypatch.setattr(sync, "_promote", boom)
    signups, _, problems = sync.sweep_stripe("sk")
    assert len(signups) == 1
    assert any("could not stamp" in p for p in problems)


def test_promotion_never_puts_the_key_in_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}
    monkeypatch.setattr(sync, "_stripe_post",
                        lambda url, key, form: seen.update(url=url, form=form) or {})
    sync._promote("sk_live_secret", "cus_X",
                  decode(encode(LEAGUE_PASS, USER, LEAGUE, rival_owner_id=RIVAL)))
    assert "sk_live_secret" not in seen["url"]
    assert seen["form"]["metadata[byl_rival]"] == RIVAL
    # Coverage is NOT stamped here — see the next test for why.
    assert "metadata[byl_pass_league]" not in seen["form"]


def test_coverage_is_never_stamped_straight_from_a_reference(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """byl_pass_league is what entitles a whole league. Writing it during the
    sweep would let an unverified claim hand twelve strangers a free product,
    so it is only written after Sleeper confirms the payer owns a roster in the
    league they are covering."""
    seen = []
    monkeypatch.setattr(sync, "_stripe_post",
                        lambda url, key, form: seen.append(form) or {})
    sync.stamp_pass_coverage("sk", "cus_X", LEAGUE)
    assert seen == [{"metadata[byl_pass_league]": LEAGUE}]


# --------------------------------------------------------------------- #
# the plan is a fact about the payment, not a claim in the buyer's URL
# --------------------------------------------------------------------- #

def _pass_session(link, ref_plan=LEAGUE_PASS, sid="cs_p"):
    session = _session(encode(ref_plan, USER, LEAGUE, rival_owner_id=RIVAL), sid=sid)
    session["payment_link"] = link
    return session


def test_paying_the_cheap_link_cannot_buy_a_league_pass(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ATTACK: every payment link is visible in the page source, and
    client_reference_id is a URL parameter. So a buyer opens the $9.99 monthly
    link by hand with a 'p-' ref and would otherwise receive the $99 League
    Pass — for any league id they care to type."""
    # The fake honours the payment_link filter, as Stripe does.
    monkeypatch.setattr(sync, "_stripe_get", lambda url, key: _page(
        [_pass_session("plink_MONTHLY")] if "plink_MONTHLY" in url else []))
    monkeypatch.setattr(sync, "_promote", lambda *a: None)
    signups, _, problems = sync.sweep_stripe(
        "sk", link_plans={"plink_SEASON": SEASON, "plink_MONTHLY": MONTHLY,
                          "plink_PASS": LEAGUE_PASS})
    assert len(signups) == 1                      # they still get their own report
    assert signups[0].pass_league_id is None      # but they cover nothing
    assert any("claims a League Pass" in p and "NOT granted" in p for p in problems)


def test_paying_the_pass_link_does_grant_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_stripe_get", lambda url, key: _page(
        [_pass_session("plink_PASS")]))
    monkeypatch.setattr(sync, "_promote", lambda *a: None)
    signups, _, problems = sync.sweep_stripe("sk", link_plans={"plink_PASS": LEAGUE_PASS})
    assert signups[0].pass_league_id == LEAGUE
    assert not problems


def test_with_no_plan_map_no_purchase_can_grant_coverage(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed: an unconfigured operator must not silently mean 'trust the
    reference'."""
    monkeypatch.setattr(sync, "_stripe_get", lambda url, key: _page(
        [_pass_session("plink_PASS")]))
    monkeypatch.setattr(sync, "_promote", lambda *a: None)
    signups, _, problems = sync.sweep_stripe("sk", link_plans=None)
    assert signups[0].pass_league_id is None
    assert any("no plan map is configured" in p for p in problems)


def test_an_unpaid_session_is_not_a_signup(monkeypatch: pytest.MonkeyPatch) -> None:
    """status=complete can still be unpaid with delayed-notification methods.
    Entitlement follows the money."""
    session = _session(encode(SEASON, USER, LEAGUE, rival_owner_id=RIVAL))
    session["payment_status"] = "unpaid"
    monkeypatch.setattr(sync, "_stripe_get", lambda url, key: _page([session]))
    monkeypatch.setattr(sync, "_promote", lambda *a: None)
    signups, _, _ = sync.sweep_stripe("sk")
    assert signups == []


def test_the_plan_map_parses_and_ignores_junk() -> None:
    plans = sync.parse_link_plans("s:plink_A, m:plink_B ,p:plink_C,,x:plink_D")
    assert plans["plink_A"] == SEASON and plans["plink_C"] == LEAGUE_PASS
    assert "plink_D" not in plans          # unknown prefix grants nothing
    # A bare link is a filter with no plan, which can never grant a pass.
    assert sync.parse_link_plans("plink_E") == {"plink_E": ""}


# --------------------------------------------------------------------- #
# the append-only log and its projection
# --------------------------------------------------------------------- #

def test_signing_up_again_is_a_rival_change_not_a_duplicate(tmp_path: Path) -> None:
    log = tmp_path / "signups.jsonl"
    sync.append_log([_signup(rival_owner_id=RIVAL)], log)
    sync.append_log([_signup(rival_owner_id="999999999999")], log)
    projected = sync.project(sync.load_log(log))
    assert len(projected) == 1                       # not two registry entries
    assert projected[0].rival_owner_id == "999999999999"   # the newer pick wins


def test_the_log_is_append_only(tmp_path: Path) -> None:
    log = tmp_path / "signups.jsonl"
    sync.append_log([_signup()], log)
    sync.append_log([_signup(rival_owner_id="999999999999")], log)
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_a_corrupt_line_costs_one_subscriber_not_everyone(
        tmp_path: Path, capsys) -> None:
    log = tmp_path / "signups.jsonl"
    sync.append_log([_signup()], log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    sync.append_log([_signup(user_id="111111111111")], log)
    loaded = sync.load_log(log)
    assert len(loaded) == 2
    assert "unreadable" in capsys.readouterr().err


def test_two_leagues_for_one_person_are_two_subscriptions(tmp_path: Path) -> None:
    """Keyed on (league, user), so somebody in two leagues gets two reports."""
    log = tmp_path / "signups.jsonl"
    sync.append_log([_signup(), _signup(league_id="123456789012345678")], log)
    assert len(sync.project(sync.load_log(log))) == 2


# --------------------------------------------------------------------- #
# League Pass seats
# --------------------------------------------------------------------- #

def test_a_seat_is_only_real_if_a_pass_covers_that_league() -> None:
    """The seat link is public by necessity, so an unvalidated form endpoint is
    a free-report generator for anyone who finds the URL."""
    rows = [{"email": "member@example.com", "user_id": "111111111111",
             "league_id": LEAGUE, "rival_owner_id": RIVAL},
            {"email": "stranger@example.com", "user_id": "222222222222",
             "league_id": "999999999999999999", "rival_owner_id": RIVAL}]
    seats, problems = sync.seats_to_signups(rows, {LEAGUE: "commish@example.com"})
    assert len(seats) == 1
    assert seats[0].email == "member@example.com"
    assert seats[0].covered_by == "commish@example.com"
    assert seats[0].plan == "league_pass"
    assert any("no League Pass covers" in p for p in problems)


def test_a_seat_always_names_its_payer() -> None:
    """registry.py rejects a seat with no covered_by — a seat naming no payer is
    an unpaid report waiting to be sent — so sync must always fill it."""
    seats, _ = sync.seats_to_signups(
        [{"email": "m@example.com", "user_id": "111111111111",
          "league_id": LEAGUE, "rival_owner_id": RIVAL}],
        {LEAGUE: "commish@example.com"})
    entries = sync.to_registry_entries(seats)
    assert entries[0]["covered_by"] == "commish@example.com"


@pytest.mark.parametrize("row", [
    {"email": "", "user_id": "111111111111", "league_id": LEAGUE, "rival_owner_id": RIVAL},
    {"email": "m@example.com", "user_id": "abc", "league_id": LEAGUE, "rival_owner_id": RIVAL},
    {"email": "m@example.com", "user_id": "111111111111", "league_id": "12", "rival_owner_id": RIVAL},
    {"email": "m@example.com", "user_id": "111111111111", "league_id": LEAGUE},
])
def test_unusable_seat_claims_are_rejected(row: dict) -> None:
    seats, problems = sync.seats_to_signups([row], {LEAGUE: "commish@example.com"})
    assert seats == [] and problems


# --------------------------------------------------------------------- #
# verification against live Sleeper
# --------------------------------------------------------------------- #

def test_a_signup_for_a_roster_you_do_not_own_is_refused() -> None:
    """The ref is a string a browser put in a URL. Trusting it would mail
    somebody another manager's team."""
    client = FakeSleeper()
    assert sync.verify(_signup(), client) is None
    assert "owns no roster" in sync.verify(_signup(user_id="999999999999"), client)


def test_a_rival_who_left_the_league_is_refused() -> None:
    assert "not a team in that league" in \
        sync.verify(_signup(rival_owner_id="999999999999"), FakeSleeper())


def test_you_cannot_be_your_own_rival() -> None:
    assert "themselves" in sync.verify(_signup(rival_owner_id=USER), FakeSleeper())


def test_a_league_that_does_not_exist_is_refused() -> None:
    assert "does not exist" in \
        sync.verify(_signup(league_id="999999999999999999"), FakeSleeper())


def test_a_sleeper_outage_is_not_a_rejection() -> None:
    """An outage that silently deletes paying subscribers from the registry is
    the worst possible failure mode, so verify() raises and the caller keeps
    the row."""
    from ingest.sleeper import SleeperError

    class Down(FakeSleeper):
        def rosters(self, league_id, **kw):
            raise SleeperError("503")

    with pytest.raises(SleeperError):
        sync.verify(_signup(), Down())


# --------------------------------------------------------------------- #
# the season roll
# --------------------------------------------------------------------- #

def _rolling_client():
    """2025 league 111... becomes 2026 league 222..., linked by the chain."""
    return FakeSleeper(
        leagues={"222222222222222222": "111111111111111111",
                 "111111111111111111": None},
        seasons={"111111111111111111": "2025", "222222222222222222": "2026"})


def test_a_renewed_subscriber_rolls_onto_this_seasons_league() -> None:
    rolled, note = sync.roll_season(
        _signup(league_id="111111111111111111"), _rolling_client(), "2026")
    assert rolled.league_id == "222222222222222222"
    assert "rolled from" in note
    # roster ids do NOT survive a season change (verified: sample-league roster
    # 6 changed owners between 2017 and 2018), so only the owner carries over.
    assert rolled.rival_roster_id is None
    assert rolled.rival_owner_id == RIVAL


def test_a_current_league_is_left_alone() -> None:
    client = _rolling_client()
    rolled, note = sync.roll_season(
        _signup(league_id="222222222222222222"), client, "2026")
    assert rolled.league_id == "222222222222222222" and note is None


def test_an_ambiguous_roll_changes_nothing_and_says_so() -> None:
    """A wrong league is worse than a missing one: it looks like it worked."""
    client = FakeSleeper(
        leagues={"222222222222222222": "111111111111111111",
                 "333333333333333333": "111111111111111111",
                 "111111111111111111": None},
        seasons={"111111111111111111": "2025", "222222222222222222": "2026",
                 "333333333333333333": "2026"})
    rolled, note = sync.roll_season(
        _signup(league_id="111111111111111111"), client, "2026")
    assert rolled.league_id == "111111111111111111"      # unchanged
    assert "ambiguous" in note and "re-pick" in note


def test_no_successor_league_is_reported_not_guessed() -> None:
    client = FakeSleeper(leagues={"111111111111111111": None},
                         seasons={"111111111111111111": "2025"})
    rolled, note = sync.roll_season(
        _signup(league_id="111111111111111111"), client, "2026")
    assert rolled.league_id == "111111111111111111"
    assert "no 2026 league" in note


def test_a_roster_only_rival_cannot_survive_a_roll() -> None:
    """roster_id is not stable across seasons, so carrying it would silently
    point the report at whoever holds that slot now."""
    rolled, note = sync.roll_season(
        _signup(league_id="111111111111111111", rival_owner_id=None,
                rival_roster_id=6), _rolling_client(), "2026")
    assert rolled.league_id == "111111111111111111"      # refused
    assert "re-pick" in note


# --------------------------------------------------------------------- #
# the projection registry.py has to accept
# --------------------------------------------------------------------- #

def test_the_projection_is_exactly_what_the_registry_validates(tmp_path: Path) -> None:
    """sync writes it, registry.py reads it — if these ever disagree the whole
    pipeline stops on a Tuesday morning."""
    seats, _ = sync.seats_to_signups(
        [{"email": "member@example.com", "user_id": "111111111111",
          "league_id": LEAGUE, "rival_owner_id": RIVAL,
          "sleeper_username": "Member"}],
        {LEAGUE: "commish@example.com"})
    entries = sync.to_registry_entries([_signup(stripe_customer_id="cus_ABCD1234")] + seats)
    path = tmp_path / "subscribers.json"
    sync.write_registry(entries, path)
    subscribers = load_registry(path)
    assert len(subscribers) == 2
    individual = next(s for s in subscribers if not s.is_league_seat)
    seat = next(s for s in subscribers if s.is_league_seat)
    assert individual.stripe_customer_id == "cus_ABCD1234"
    assert seat.covered_by == "commish@example.com"


def test_the_registry_rejects_a_bogus_customer_id(tmp_path: Path) -> None:
    path = tmp_path / "subscribers.json"
    path.write_text(json.dumps([{
        "email": "a@b.co", "user_id": USER, "league_id": LEAGUE,
        "rival_owner_id": RIVAL, "stripe_customer_id": "'; DROP TABLE--"}]),
        encoding="utf-8")
    with pytest.raises(RegistryError, match="cus_"):
        load_registry(path)


# --------------------------------------------------------------------- #
# entitlement: the join that is no longer an email
# --------------------------------------------------------------------- #

def _sub(**over):
    base = dict(email="buyer@example.com", user_id=USER, league_id=LEAGUE,
                rival_owner_id=RIVAL, rival_roster_id=None)
    base.update(over)
    return Subscriber(**base)


def test_entitlement_survives_a_subscriber_changing_their_email() -> None:
    """Stripe's portal lets people change their billing email. Joining on it
    means they silently stop receiving what they are paying for."""
    paid = PaidList(emails=frozenset({"new-address@example.com"}), source="stripe",
                    status_column="active", customer_ids=frozenset({"cus_ABCD1234"}))
    assert paid.entitles(_sub(stripe_customer_id="cus_ABCD1234"))
    assert not paid.covers("buyer@example.com")     # the old email is gone


def test_a_seat_is_entitled_by_its_league_being_covered() -> None:
    paid = PaidList(emails=frozenset({"commish@example.com"}), source="stripe",
                    status_column="active",
                    covered_leagues=frozenset({LEAGUE}))
    seat = _sub(email="member@example.com", plan="league_pass",
                covered_by="commish@example.com")
    assert paid.entitles(seat)


def test_a_seat_dies_when_the_pass_lapses() -> None:
    lapsed = PaidList(emails=frozenset(), source="stripe", status_column="active",
                      covered_leagues=frozenset(), customer_ids=frozenset())
    seat = _sub(email="member@example.com", plan="league_pass",
                covered_by="commish@example.com")
    assert not lapsed.entitles(seat)


def test_hand_added_entries_still_work_on_the_email_join() -> None:
    """The CSV path has no customer ids at all, so the email fallback has to
    keep working or switching platforms breaks everyone."""
    paid = PaidList(emails=frozenset({"buyer@example.com"}), source="csv",
                    status_column="status")
    assert paid.entitles(_sub())


def test_a_stranger_is_never_entitled() -> None:
    paid = PaidList(emails=frozenset({"someone@example.com"}), source="stripe",
                    status_column="active",
                    customer_ids=frozenset({"cus_OTHER999"}),
                    covered_leagues=frozenset({"999999999999999999"}))
    assert not paid.entitles(_sub(stripe_customer_id="cus_ABCD1234"))


def test_a_league_pass_follows_its_league_into_the_new_season() -> None:
    """The pass covers a LEAGUE, and Sleeper gives the league a new id every
    year. Leaving coverage on last season's id means the commissioner keeps
    paying while every seat claim finds no pass."""
    payer = _signup(league_id="111111111111111111",
                    pass_league_id="111111111111111111")
    rolled, note = sync.roll_season(payer, _rolling_client(), "2026")
    assert rolled.league_id == "222222222222222222"
    assert rolled.pass_league_id == "222222222222222222"


def test_rolling_a_non_payer_does_not_invent_coverage() -> None:
    rolled, _ = sync.roll_season(_signup(league_id="111111111111111111"),
                                _rolling_client(), "2026")
    assert rolled.pass_league_id is None
