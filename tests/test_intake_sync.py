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


def test_the_run_refuses_without_a_stripe_key(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert _run(tmp_path) == 1
    assert "STRIPE_API_KEY" in capsys.readouterr().err
