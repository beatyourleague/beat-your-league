"""Payments becoming subscribers, for the roster product.

``run/intake.py`` is the last link in the chain the buyer actually travels:
picker -> Stripe -> registry -> report -> inbox. Until it existed the registry
had to be written by hand, which is why checkout could not open.

Everything here runs against a fake Stripe. The properties are the ones where a
mistake costs somebody money or silence: a claim trusted as a fact, a payment
swept and forgotten, a row that loads for nobody.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import run.checkout as checkout
import run.intake as intake
from engine.roster import Player, PlayerDirectory
from run.refs import encode, encode_roster
from run.rosters import load_rosters
from test_solo_run import SLOTS, _pid

PLAYERS = [_pid(i) for i in range(1, 9)]
REF = encode_roster("season", "ppr", list(SLOTS), PLAYERS)
PASS_REF = encode_roster("league_pass", "ppr", list(SLOTS), PLAYERS)
MONTHLY_LINK, SEASON_LINK, PASS_LINK = "plink_M", "plink_S", "plink_P"


def _session(ref: str | None, *, sid: str = "cs_1", email: str = "fan@example.com",
             created: int = 1000, link: str | None = SEASON_LINK,
             customer: str | None = "cus_abcd1234", paid: str = "paid") -> dict:
    return {
        "id": sid, "created": created, "payment_status": paid,
        "client_reference_id": ref, "payment_link": link,
        "customer": {"id": customer, "email": email} if customer else None,
        "customer_details": {"email": email},
    }


def _page(sessions: list[dict]) -> dict:
    return {"data": sessions, "has_more": False}


@pytest.fixture
def stripe(monkeypatch):
    """A fake Stripe whose session list the test sets, and a record of writes."""
    state: dict = {"sessions": [], "posts": []}
    monkeypatch.setattr(checkout, "_stripe_get",
                        lambda url, key: _page(state["sessions"]))
    monkeypatch.setattr(intake, "_stripe_post",
                        lambda url, key, form: state["posts"].append((url, form)) or {})
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test")
    monkeypatch.delenv("STRIPE_PAYMENT_LINKS", raising=False)
    return state


@pytest.fixture
def directory(monkeypatch):
    """The published directory, containing exactly the fixture roster."""
    people = [Player(pid, f"Player {i}", "WR", "KC")
              for i, pid in enumerate(PLAYERS, start=1)]

    class _Data:
        directory = PlayerDirectory(people)

    monkeypatch.setattr(intake, "load_week_data", lambda *a, **k: _Data())
    return _Data


def _run(tmp_path: Path, *extra: str) -> int:
    return intake.main(["--registry-dir", str(tmp_path), *extra])


def _registry(tmp_path: Path) -> list[dict]:
    path = tmp_path / intake.REGISTRY_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


# --------------------------------------------------------------------- #
# the sweep
# --------------------------------------------------------------------- #

def test_a_payment_becomes_a_loadable_subscriber(tmp_path, stripe, directory,
                                                 capsys) -> None:
    """The whole point. And the registry it writes must LOAD — written and
    unloadable is the worst outcome, because every subscriber's Tuesday is down
    and nothing says so until the run that was meant to mail them."""
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path) == 0, capsys.readouterr().err
    subscribers = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert len(subscribers) == 1
    assert subscribers[0].email == "fan@example.com"
    assert subscribers[0].player_ids == tuple(PLAYERS)
    assert subscribers[0].stripe_customer_id == "cus_abcd1234"


def test_a_sleeper_ref_is_left_for_the_other_intake(tmp_path, stripe, directory,
                                                    capsys) -> None:
    """Both intakes run against one Stripe account during the migration. If each
    reported the other's refs as unreadable, every run would file a
    PAID-UNATTRIBUTED alarm for a payment that is being handled correctly — and
    an alarm that fires every week for nothing trains you to ignore the real
    one."""
    stripe["sessions"] = [_session(encode("season", "123456789012345",
                                          "987654321098765",
                                          rival_owner_id="111111111111111"))]
    assert _run(tmp_path) == 0
    captured = capsys.readouterr()
    assert "PAID-UNATTRIBUTED" not in captured.err
    assert _registry(tmp_path) == []


def test_an_unpaid_session_is_not_a_subscriber(tmp_path, stripe, directory) -> None:
    """A session can be status=complete and still unpaid with a
    delayed-notification method. Entitlement follows the money."""
    stripe["sessions"] = [_session(REF, paid="unpaid")]
    assert _run(tmp_path) == 0
    assert _registry(tmp_path) == []


def test_a_payment_with_no_reference_is_reported_not_swallowed(
        tmp_path, stripe, directory, capsys) -> None:
    """Somebody paid and we cannot say for what. Silence there is a customer
    being charged for nothing, with no trace anywhere."""
    stripe["sessions"] = [_session(None)]
    _run(tmp_path)
    assert "PAID-UNATTRIBUTED" in capsys.readouterr().err


def test_an_unattributable_payment_is_reported_every_run(tmp_path, stripe,
                                                         directory, capsys) -> None:
    """The watermark moves past the session within days, so a once-only message
    meant the third run forgot a customer who is still being charged."""
    stripe["sessions"] = [_session(None)]
    _run(tmp_path)
    capsys.readouterr()
    stripe["sessions"] = []                      # the session is behind us now
    _run(tmp_path)
    assert "still open" in capsys.readouterr().err
    # And it can be cleared deliberately.
    _run(tmp_path, "--clear-unresolved")
    assert "still open" not in capsys.readouterr().err


# --------------------------------------------------------------------- #
# the plan is a fact, not a claim
# --------------------------------------------------------------------- #

def test_the_plan_comes_from_the_link_that_took_the_money(tmp_path, stripe,
                                                          directory, monkeypatch,
                                                          capsys) -> None:
    """Every payment link is visible in the page source and client_reference_id
    is a URL parameter, so a "p" prefix is a claim. Trusting it lets anyone pay
    the monthly link and receive the League Pass."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS",
                       f"s:{SEASON_LINK},m:{MONTHLY_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_session(PASS_REF, link=MONTHLY_LINK)]
    _run(tmp_path)
    captured = capsys.readouterr()
    assert "claims a League Pass" in captured.err
    assert "monthly link" in captured.err
    # They still get the report they paid for.
    assert len(load_rosters(tmp_path / intake.REGISTRY_NAME)) == 1


def test_with_no_map_configured_nothing_grants_a_pass(tmp_path, stripe,
                                                      directory, capsys) -> None:
    """Fail closed. An unconfigured map is an operator problem, and the run says
    which case it was rather than quietly honouring the claim."""
    stripe["sessions"] = [_session(PASS_REF)]
    _run(tmp_path)
    assert "no plan map is configured" in capsys.readouterr().err


def test_a_registry_row_is_never_written_as_a_seat(tmp_path, stripe, directory,
                                                   capsys) -> None:
    """`league_pass` on a registry row means a SEAT, and a seat needs
    covered_by. A pass PAYER is an ordinary subscriber who also covers other
    people — recording them as a seat would fail the load for everybody."""
    stripe["sessions"] = [_session(PASS_REF)]
    _run(tmp_path)
    assert all(row.get("plan") != "league_pass" for row in _registry(tmp_path))
    load_rosters(tmp_path / intake.REGISTRY_NAME)


# --------------------------------------------------------------------- #
# servability
# --------------------------------------------------------------------- #

def test_a_roster_we_cannot_serve_is_blocked_loudly_not_written(
        tmp_path, stripe, directory, capsys) -> None:
    """A ref decodes to ids, not to players. One unresolvable row fails the
    registry load for EVERY subscriber, because the loader is whole-file on
    purpose — so this person's problem must not become everybody's."""
    unknown = ["00-9999999"] + PLAYERS[1:]
    bad = encode_roster("season", "ppr", list(SLOTS), unknown)
    stripe["sessions"] = [_session(REF, sid="cs_1"),
                          _session(bad, sid="cs_2", email="two@example.com",
                                   customer="cus_two9876", created=1100)]
    code = _run(tmp_path)
    captured = capsys.readouterr()
    assert code == 1, "a paid-but-unservable signup must not exit clean"
    assert "BLOCKED" in captured.err and "has PAID" in captured.err
    # The good one still ships.
    assert len(load_rosters(tmp_path / intake.REGISTRY_NAME)) == 1


def test_a_directory_outage_writes_the_rows_rather_than_stranding_them(
        tmp_path, stripe, monkeypatch, capsys) -> None:
    """Refusing to write a registry because a data release is briefly
    unavailable strands every paid signup for a week. The check is a guard, not
    a gate."""
    def _boom(*_a, **_k):
        raise intake.SoloError("games.csv unavailable")
    monkeypatch.setattr(intake, "load_week_data", _boom)
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path) == 0
    assert "written unchecked" in capsys.readouterr().err
    assert len(load_rosters(tmp_path / intake.REGISTRY_NAME)) == 1


# --------------------------------------------------------------------- #
# idempotence and ordering
# --------------------------------------------------------------------- #

def test_running_twice_changes_nothing(tmp_path, stripe, directory) -> None:
    stripe["sessions"] = [_session(REF)]
    _run(tmp_path)
    first = _registry(tmp_path)
    log = (tmp_path / intake.SIGNUP_LOG_NAME).read_text(encoding="utf-8")
    _run(tmp_path)
    assert _registry(tmp_path) == first
    assert (tmp_path / intake.SIGNUP_LOG_NAME).read_text(encoding="utf-8") == log


def test_the_projection_is_recency_aware_not_position_aware() -> None:
    """The log is appended in sweep order, and a re-sweep with a wider watermark
    can put an older event after a newer one. Position alone would then let a
    stale row win."""
    older = intake.RosterSignup(email="a@b.com", ref=REF, plan="season",
                                seen_at="100", label="Old")
    newer = intake.RosterSignup(email="a@b.com", ref=REF, plan="season",
                                seen_at="900", label="New")
    assert intake.project([newer, older])[0].label == "New"
    assert intake.project([older, newer])[0].label == "New"


def test_a_dry_run_writes_nothing_and_stamps_nothing(tmp_path, stripe,
                                                     directory, capsys) -> None:
    """`--dry-run` is what an operator reaches for before opening checkout. If
    it stamped customer metadata it would not be a preview."""
    stripe["sessions"] = [_session(REF)]
    _run(tmp_path, "--dry-run")
    assert not (tmp_path / intake.REGISTRY_NAME).is_file()
    assert not (tmp_path / intake.SIGNUP_LOG_NAME).is_file()
    assert not (tmp_path / intake.STATE_NAME).is_file()
    assert stripe["posts"] == []
    assert "dry run" in capsys.readouterr().out


def test_the_roster_is_promoted_onto_the_customer(tmp_path, stripe,
                                                  directory) -> None:
    """Stripe documents no retention guarantee for old Checkout Sessions, so
    this caps our dependence on session listability at one week."""
    stripe["sessions"] = [_session(REF)]
    _run(tmp_path)
    assert stripe["posts"], "nothing was stamped onto the customer"
    url, form = stripe["posts"][0]
    assert "cus_abcd1234" in url
    assert form[f"metadata[{intake.META_REF}]"] == REF


def test_two_rosters_for_one_customer_are_reported_not_silently_merged(
        tmp_path, stripe, directory, capsys) -> None:
    """Legitimate (two teams) and also what a roster CHANGE looks like, because
    re-running the picker builds a new ref and only a new payment carries it
    here. Picking one silently would drop a purchase; merging them would drop a
    team."""
    second = encode_roster("season", "half_ppr", list(SLOTS), PLAYERS)
    stripe["sessions"] = [_session(REF, sid="cs_1"),
                          _session(second, sid="cs_2", created=1100)]
    _run(tmp_path)
    out = capsys.readouterr().out
    assert "has 2 rosters" in out
    assert len(load_rosters(tmp_path / intake.REGISTRY_NAME)) == 2


def test_an_unconfigured_stripe_is_not_reported_as_a_failure(
        tmp_path, monkeypatch, capsys) -> None:
    """Exit 2, not 1. Before checkout opens this is the EXPECTED state, and a
    cron that files a bug issue every week for it teaches you to ignore bug
    issues — which is how the real one gets missed. Exit 1 stays reserved for
    "something is wrong"."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert _run(tmp_path) == intake.NOT_CONFIGURED
    assert intake.NOT_CONFIGURED != 1
    err = capsys.readouterr().err
    assert "STRIPE_API_KEY" in err and "expected" in err


# --------------------------------------------------------------------- #
# League Pass seats — the only signups with no payment behind them
# --------------------------------------------------------------------- #

SEAT_REF = encode_roster("season", "ppr", list(SLOTS), PLAYERS[::-1])


def _seat(**over) -> dict:
    row = {"email": "member@example.com", "covered_by": "commish@example.com",
           "ref": SEAT_REF}
    row.update(over)
    return row


def _seats(monkeypatch, *rows: dict) -> None:
    monkeypatch.setenv("FORM_ENDPOINT", "https://forms.example/seats")
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: list(rows))


def _pass_session(**over) -> dict:
    return _session(PASS_REF, sid="cs_pass", email="commish@example.com",
                    link=PASS_LINK, customer="cus_commish01", **over)


def test_a_seat_is_honoured_only_when_a_real_pass_covers_it(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The seat form is public by necessity, so without this check the endpoint
    is a free-report generator for anyone who finds the URL. The payer set is
    built from what the LINK took, never from what a seat claims."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_pass_session()]
    _seats(monkeypatch, _seat())
    assert _run(tmp_path) == 0, capsys.readouterr().err
    rows = {s.email: s for s in load_rosters(tmp_path / intake.REGISTRY_NAME)}
    assert set(rows) == {"commish@example.com", "member@example.com"}
    seat = rows["member@example.com"]
    assert seat.is_league_seat and seat.covered_by == "commish@example.com"
    # The PAYER is an ordinary subscriber, not a seat: a league_pass row needs
    # covered_by, and the buyer has nobody covering them.
    assert not rows["commish@example.com"].is_league_seat


def test_a_seat_naming_nobody_who_paid_is_refused(tmp_path, stripe, directory,
                                                  monkeypatch, capsys) -> None:
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_session(REF)]          # an ordinary season buyer
    _seats(monkeypatch, _seat(covered_by="stranger@example.com"))
    _run(tmp_path)
    assert "no League Pass" in capsys.readouterr().err
    assert all(r.get("plan") != "league_pass" for r in _registry(tmp_path))


def test_an_ordinary_subscriber_does_not_cover_seats(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The check is "did this address buy a LEAGUE PASS", not "did it pay us".
    Honouring any payer would hand eleven free reports to anyone who found the
    seat link and knew one $39 subscriber's address — the free-report generator
    the validation exists to prevent.

    Found by mutation: relaxing the check to `pass_payers = every payer` left
    the suite green, because the only refusal test named a stranger.
    """
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_session(REF)]          # a $39 season buyer, no pass
    _seats(monkeypatch, _seat(covered_by="fan@example.com"))
    _run(tmp_path)
    assert "no League Pass" in capsys.readouterr().err
    assert all(r.get("plan") != "league_pass" for r in _registry(tmp_path)), \
        "a season subscription was treated as covering seats"


def test_a_seat_survives_either_projection_order(monkeypatch) -> None:
    """The payer wins whether seats or payments are projected first. Pinned
    because the code comment used to claim the ordering was load-bearing."""
    from run.rosters import drop_unloadable
    payer = {"email": "c@example.com", "ref": REF, "player_ids": list(PLAYERS),
             "slots": list(SLOTS), "scoring": "ppr", "plan": "season"}
    seat = dict(payer, plan="league_pass", covered_by="other@example.com")
    for order in ([payer, seat], [seat, payer]):
        kept, _ = drop_unloadable(order)
        assert len(kept) == 1 and kept[0].get("plan") == "season"


def test_a_stranger_cannot_claim_a_seat_on_a_payers_address(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """A seat must never evict the person who actually paid. drop_unloadable
    resolves the collision in the payer's favour, and the payer is projected
    first so it can."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_pass_session()]
    _seats(monkeypatch, _seat(email="commish@example.com", ref=PASS_REF))
    _run(tmp_path)
    rows = load_rosters(tmp_path / intake.REGISTRY_NAME)
    payer = [r for r in rows if r.email == "commish@example.com"]
    assert len(payer) == 1 and not payer[0].is_league_seat, \
        "a seat claim replaced the subscription that paid for it"


def test_a_seat_with_an_unusable_address_cannot_take_the_registry_down(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The loader fails the WHOLE file on one bad row, so a stranger POSTing
    "not an email" would stop every subscriber's Tuesday."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_pass_session()]
    _seats(monkeypatch, _seat(email="not an email"), _seat())
    assert _run(tmp_path) == 0
    assert "unusable addresses" in capsys.readouterr().err
    load_rosters(tmp_path / intake.REGISTRY_NAME)        # still loadable


def test_an_unreadable_seat_backend_refuses_rather_than_dropping_seats(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Writing a Stripe-only registry would silently drop every seat and read
    as a quiet week."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_pass_session()]
    monkeypatch.setenv("FORM_ENDPOINT", "https://forms.example/seats")

    def _boom(*_a, **_k):
        raise intake.IntakeError("HTTP 503")
    monkeypatch.setattr(intake, "fetch_seats", _boom)
    assert _run(tmp_path) == 1
    assert "Refusing to write a registry" in capsys.readouterr().err


def test_with_no_seat_backend_the_tier_simply_does_not_deliver_seats(
        tmp_path, stripe, directory, monkeypatch) -> None:
    """PLAN §0 keeps FORM_ENDPOINT empty until a validated backend exists, and
    empty must mean no seats rather than unpaid ones."""
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_pass_session()]
    assert _run(tmp_path) == 0
    assert all(r.get("plan") != "league_pass" for r in _registry(tmp_path))


def test_a_directory_outage_does_not_reject_every_seat(monkeypatch) -> None:
    """`known_ids=None` means NOT CHECKED, never "nothing is known" — an empty
    set would reject every seat with a confident, wrong reason on the one day a
    data release is unavailable."""
    rows, problems = intake.seats_to_rows(
        [_seat()], {"commish@example.com"}, None)
    assert len(rows) == 1 and not problems
    rows, problems = intake.seats_to_rows(
        [_seat()], {"commish@example.com"}, set(PLAYERS))
    assert len(rows) == 1, problems
