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
import re
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


# --------------------------------------------------------------------- #
# the welcome email rides the sweep
# --------------------------------------------------------------------- #

def _capture_sends(monkeypatch, tmp_path):
    """A real provider double: send_all runs for real against a tmp sent log,
    so idempotency is the actual mechanism under test, not a mock of one."""
    import run.delivery as delivery

    sent: list = []

    class _Provider:
        name = "test"

        def send(self, message, sender, reply_to):
            sent.append(message)
            return "mid-1"

    monkeypatch.setenv("EMAIL_PROVIDER", "resend")   # explicit, not implicit-dry
    monkeypatch.setattr(intake, "build_provider", lambda _n=None: _Provider())
    real_send_all = delivery.send_all
    monkeypatch.setattr(
        intake, "send_all",
        lambda messages, provider: real_send_all(
            messages, provider=provider, sent_log=tmp_path / "sent.jsonl"))
    return sent


def test_a_new_subscriber_is_welcomed_once_and_only_once(
        tmp_path, stripe, directory, monkeypatch) -> None:
    """The acknowledgment is legally owed on purchase — and owed exactly once.
    Re-running the sweep (which happens weekly forever) must not re-send it."""
    sent = _capture_sends(monkeypatch, tmp_path)
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path) == 0
    assert len(sent) == 1
    assert sent[0].to == "fan@example.com"
    assert "You're in" in sent[0].subject
    assert "@" not in sent[0].key

    _run(tmp_path)                                    # the next weekly sweep
    assert len(sent) == 1, "a re-run welcomed the same subscriber twice"


def test_a_pass_payer_is_welcomed_with_pass_terms_not_season_terms(
        tmp_path, stripe, directory, monkeypatch) -> None:
    """The registry flattens a pass payer to a season row on purpose; the
    welcome must be built from the SIGNUP, whose plan is the purchase that
    actually happened. $39 renewal terms on a $99 purchase is a wrong legal
    disclosure."""
    sent = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_pass_session()]
    _run(tmp_path)
    assert len(sent) == 1
    assert "$99 USD" in sent[0].text
    assert "$39 USD" not in sent[0].text


def test_a_seat_is_welcomed_without_billing_terms(tmp_path, stripe, directory,
                                                  monkeypatch) -> None:
    sent = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"s:{SEASON_LINK},p:{PASS_LINK}")
    stripe["sessions"] = [_pass_session()]
    _seats(monkeypatch, _seat())
    _run(tmp_path)
    by_to = {m.to: m for m in sent}
    assert set(by_to) == {"commish@example.com", "member@example.com"}
    seat_msg = by_to["member@example.com"]
    assert "Nothing bills you" in seat_msg.text
    assert "$" not in seat_msg.text


def test_with_no_provider_welcomes_are_reported_pending_not_sent(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Unlike the Tuesday send, an unconfigured welcome must NOT fail the run —
    the registry is intake's contract — but it must say what is pending, and
    record nothing, so the first configured run sends them all exactly once."""
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Welcomes: 1 pending" in out
    assert "none were sent and none were recorded" in out


# --------------------------------------------------------------------- #
# self-serve roster updates — authenticated, targeted, stamped on receipt
# --------------------------------------------------------------------- #

from run.updates import slug_of, update_token, update_url  # noqa: E402

NEW_REF = encode_roster("season", "half_ppr", list(SLOTS), PLAYERS[::-1])
SECRET = "test-secret-do-not-ship"


def _update(**over) -> dict:
    row = {"kind": "update", "email": "fan@example.com", "ref": NEW_REF,
           "replaces": slug_of(REF), "token": update_token("fan@example.com", SECRET)}
    row.update(over)
    return row


def _updates(monkeypatch, *rows: dict, secret: str | None = SECRET) -> None:
    _seats(monkeypatch, *rows)
    if secret is None:
        monkeypatch.delenv("UPDATE_SECRET", raising=False)
    else:
        monkeypatch.setenv("UPDATE_SECRET", secret)


def test_a_subscriber_can_change_their_own_roster(tmp_path, stripe, directory,
                                                  monkeypatch, capsys) -> None:
    """Rosters churn from the first waiver run; by the second report a file
    built from the signup roster recommends dropped players. An update from
    the subscriber, carrying their token, replaces the roster — both copies,
    from one object — and nothing else about the row."""
    stripe["sessions"] = [_session(REF)]
    _updates(monkeypatch, _update())
    assert _run(tmp_path) == 0, capsys.readouterr().err
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.ref == NEW_REF
    assert row.scoring == "half_ppr"
    assert row.player_ids == tuple(PLAYERS[::-1])
    assert row.stripe_customer_id == "cus_abcd1234" and row.plan == "season"
    # The identity everything is keyed on did not move with the roster.
    assert row.origin == slug_of(REF) and row.slug == slug_of(REF)


def test_an_update_without_the_subscribers_token_is_refused(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The form is public. Without the token, anyone who knows a leaguemate's
    address could set their lineup for them."""
    stripe["sessions"] = [_session(REF)]
    _updates(monkeypatch, _update(token="0" * 20))
    assert _run(tmp_path) == 0
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.ref == REF, "an unauthenticated update changed a paid roster"
    assert "does not match" in capsys.readouterr().err


def test_an_update_cannot_target_a_subscription_the_address_does_not_hold(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    stripe["sessions"] = [_session(REF),
                          _session(PASS_REF, sid="cs_2", email="other@example.com",
                                   customer="cus_other0001")]
    # A valid token for fan@, aimed at other@'s row.
    _updates(monkeypatch, _update(replaces=slug_of(PASS_REF)))
    assert _run(tmp_path) == 0
    rows = {s.email: s for s in load_rosters(tmp_path / intake.REGISTRY_NAME)}
    assert rows["other@example.com"].ref == PASS_REF
    assert rows["fan@example.com"].ref == REF
    assert "does not hold" in capsys.readouterr().err


def test_with_no_secret_configured_no_update_is_applied(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """An update that cannot be authenticated is anyone's to forge, so the
    absence of the secret fails closed and says so."""
    stripe["sessions"] = [_session(REF)]
    _updates(monkeypatch, _update(), secret=None)
    assert _run(tmp_path) == 0
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.ref == REF
    assert "UPDATE_SECRET" in capsys.readouterr().err


def test_the_newest_update_wins_by_when_we_first_saw_it(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Two runs, two updates to the same row: the later-seen one stands, and
    a re-run with the same backend contents changes nothing."""
    stripe["sessions"] = [_session(REF)]
    second = encode_roster("season", "standard", list(SLOTS), PLAYERS)
    _updates(monkeypatch, _update())
    assert _run(tmp_path) == 0
    _updates(monkeypatch, _update(), _update(ref=second))
    assert _run(tmp_path) == 0
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.ref == second and row.scoring == "standard"
    before = (tmp_path / intake.REGISTRY_NAME).read_text(encoding="utf-8")
    log_before = (tmp_path / intake.UPDATE_LOG_NAME).read_text(encoding="utf-8")
    assert _run(tmp_path) == 0
    assert (tmp_path / intake.REGISTRY_NAME).read_text(encoding="utf-8") == before
    assert (tmp_path / intake.UPDATE_LOG_NAME).read_text(encoding="utf-8") == log_before


def test_an_update_never_triggers_a_second_welcome(tmp_path, stripe, directory,
                                                   monkeypatch) -> None:
    """The welcome is keyed on the signup, and an update touches only the
    registry row — so a changed roster is never a second acknowledgment."""
    sends = _capture_sends(monkeypatch, tmp_path)
    stripe["sessions"] = [_session(REF)]
    assert _run(tmp_path) == 0
    _updates(monkeypatch, _update())
    assert _run(tmp_path) == 0
    welcomes = [m for m in sends if m.key.startswith("welcome-")]
    assert len(welcomes) == 1, [m.key for m in sends]


def test_an_update_naming_an_unknown_player_is_refused_not_written(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The registry loader fails the whole file on one bad row; an update is
    checked against the directory before it can take every subscriber down."""
    stripe["sessions"] = [_session(REF)]
    ghost = encode_roster("season", "ppr", list(SLOTS), PLAYERS[:-1] + ["00-0099999"])
    _updates(monkeypatch, _update(ref=ghost))
    assert _run(tmp_path) == 0
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.ref == REF
    assert "directory does not have" in capsys.readouterr().err


def test_the_update_link_is_stable_and_never_dead() -> None:
    """Every report a subscriber receives carries the same link (the origin
    slug, not the current ref), and with no site or no secret there is no
    link at all rather than a dead one."""
    assert update_url("", "fan@example.com", "abc123def0", SECRET) is None
    assert update_url("https://x.test", "fan@example.com", "abc123def0", "") is None
    url = update_url("https://x.test/", "fan@example.com", "abc123def0", SECRET)
    assert url == ("https://x.test/join/?update=abc123def0&token="
                   + update_token("fan@example.com", SECRET))
    assert update_token("Fan@Example.com ", SECRET) == update_token("fan@example.com", SECRET)
    assert update_token("fan@example.com", SECRET) != update_token("fan@example.com", "other")


def test_the_worker_the_picker_and_the_intake_agree_on_the_update_contract() -> None:
    """Three files, three languages, nothing type-checking across them: the
    Worker's sanitiser (infra/form-worker.js), the picker's UPDATE_MODE gate
    (site/join/index.html) and run/updates.py must agree on what a slug and a
    token look like, or a valid update is dropped at one of the three doors
    with no error anyone sees."""
    root = Path(__file__).resolve().parent.parent
    worker = (root / "infra" / "form-worker.js").read_text(encoding="utf-8")
    picker = (root / "site" / "join" / "index.html").read_text(encoding="utf-8")
    from run.updates import TOKEN_LENGTH
    slug_re = r"\^\[0-9a-f\]\{10\}\$"
    token_re = rf"\^\[0-9a-f\]\{{{TOKEN_LENGTH}\}}\$"
    for name, page in (("worker", worker), ("picker", picker)):
        assert re.search(slug_re, page), f"{name} does not gate the slug shape"
        assert re.search(token_re, page), f"{name} does not gate the token shape"
    assert len(slug_of(REF)) == 10 and len(update_token("a@b.co", SECRET)) == TOKEN_LENGTH
    # The Worker stores exactly the fields the intake reads, by name.
    for field in ('kind === "update"', "covered_by", "replaces", "token"):
        assert field in worker
    # And it never accepts an unauthenticated read.
    assert "Bearer ${env.FORM_API_KEY}" in worker and "401" in worker
