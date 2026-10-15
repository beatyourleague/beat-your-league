"""The roster registry and the Tuesday run that reads it.

Between the payment and the inbox there was nothing: the intake collected a
roster and ``engine/solo_report.py`` could build a report from one, and no code
joined them. ``run/rosters.py`` is the registry that shape needs and
``run/tuesday.py`` is the runner. These tests cover the joins, which is where
this kind of pipeline actually breaks — a row that loads but describes the wrong
roster, a seat entitled by nobody, a failure that takes the whole run down with
it.

The fixture cache comes from ``test_solo_run``, including its offline session:
any download means the fixture is incomplete, not that the test is slow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import run.rosters as rosters
import run.tuesday as tuesday
from run.refs import encode_roster
from test_solo_run import OFFLINE, SEASON, SLOTS, WEEK, _cache, _pid, _spec

ROSTER_IDS = [_pid(i) for i in range(1, 9)]
REF = encode_roster("season", "ppr", list(SLOTS), ROSTER_IDS)


def _row(**overrides) -> dict:
    row = {"email": "fan@example.com", "ref": REF,
           "player_ids": list(ROSTER_IDS), "slots": list(SLOTS),
           "scoring": "ppr", "league_size": 12, "label": "Your Team"}
    row.update(overrides)
    return row


def _registry(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / "rosters.json"
    path.write_text(json.dumps(list(rows)), encoding="utf-8")
    return path


# --------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------- #

def test_a_row_is_rejected_when_its_roster_disagrees_with_its_ref(tmp_path) -> None:
    """The roster is stored expanded AND encoded, written from one object by one
    sync — so a disagreement is corruption or a hand edit. Taking the expanded
    copy on trust means mailing somebody a confident report about a roster they
    do not own, which is the failure with no natural alarm."""
    swapped = list(ROSTER_IDS)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    with pytest.raises(rosters.RosterRegistryError, match="disagree"):
        rosters.load_rosters(_registry(tmp_path, _row(player_ids=swapped)))
    with pytest.raises(rosters.RosterRegistryError, match="scoring"):
        rosters.load_rosters(_registry(tmp_path, _row(scoring="standard")))


def test_a_seat_must_name_the_payer_and_only_a_seat_may(tmp_path) -> None:
    """A seat naming no payer is an unpaid report waiting to be sent — the seat
    form is public, so this is the only thing standing between it and a
    free-report generator."""
    with pytest.raises(rosters.RosterRegistryError, match="covered_by"):
        rosters.load_rosters(_registry(tmp_path, _row(plan="league_pass")))
    with pytest.raises(rosters.RosterRegistryError, match="covered_by"):
        rosters.load_rosters(_registry(tmp_path, _row(plan="league_pass",
                                                      covered_by="not an email")))
    with pytest.raises(rosters.RosterRegistryError, match="only meaningful"):
        rosters.load_rosters(_registry(tmp_path, _row(covered_by="payer@example.com")))
    seats = rosters.load_rosters(_registry(
        tmp_path, _row(plan="league_pass", covered_by="payer@example.com")))
    assert seats[0].is_league_seat


def test_a_json_true_never_becomes_a_one_team_league(tmp_path) -> None:
    """``isinstance(True, int)`` is True in Python, which is how a `true` in a
    JSON file silently becomes the number 1 — and league_size is a denominator
    printed to the buyer ("8 of the other 11 teams can cover that")."""
    # The MESSAGE matters, not just the refusal: without the bool guard, True
    # sails past the isinstance check and is caught by the bounds instead
    # (1 < 4), so the test passed with the guard deleted — green for the wrong
    # reason, which proves nothing about the guard it is named after.
    with pytest.raises(rosters.RosterRegistryError, match="must be a number"):
        rosters.load_rosters(_registry(tmp_path, _row(league_size=True)))
    for bad in (0, 3, 33, "twelve"):
        with pytest.raises(rosters.RosterRegistryError, match="league_size"):
            rosters.load_rosters(_registry(tmp_path, _row(league_size=bad)))
    assert rosters.load_rosters(_registry(tmp_path, _row(league_size="10")))[0]\
        .league_size == 10


def test_the_same_roster_twice_for_one_address_fails_the_load(tmp_path) -> None:
    with pytest.raises(rosters.RosterRegistryError, match="twice"):
        rosters.load_rosters(_registry(tmp_path, _row(), _row()))
    # Two DIFFERENT rosters for one person is legitimate — two teams, two
    # subscriptions — and rejecting it would take every other subscriber's
    # Tuesday down with it, because the loader fails the whole file.
    second = encode_roster("season", "half_ppr", list(SLOTS), ROSTER_IDS)
    both = rosters.load_rosters(_registry(
        tmp_path, _row(), _row(ref=second, scoring="half_ppr")))
    assert len(both) == 2 and both[0].slug != both[1].slug


def test_the_filename_slug_carries_no_email(tmp_path) -> None:
    """These names outlive the run: they land on disk and in CI artifacts. There
    is no Sleeper username to fall back on any more."""
    sub = rosters.load_rosters(_registry(tmp_path, _row()))[0]
    assert "fan" not in sub.slug and "@" not in sub.slug
    assert sub.slug == rosters.load_rosters(_registry(tmp_path, _row()))[0].slug


def test_a_seat_never_evicts_a_paid_subscription(tmp_path) -> None:
    """One person holding both a payment and a seat for the same roster: the
    payment wins in either order. (The hijack case — a stranger claiming a seat
    on somebody else's roster — arrives under a different address, which is a
    different key and never collides here.)"""
    paid, seat = _row(), _row(plan="league_pass", covered_by="payer@example.com")
    for order in ([paid, seat], [seat, paid]):
        kept, problems = rosters.drop_unloadable(order)
        assert len(kept) == 1
        assert kept[0].get("plan") in (None, "season")
        assert any("keeping the paid one" in p for p in problems)


def test_one_bad_row_is_dropped_before_it_can_take_the_file_down(tmp_path) -> None:
    """The loader fails the WHOLE file on any invalid entry, so anything able to
    write one bad row is a total outage rather than one subscriber's problem."""
    kept, problems = rosters.drop_unloadable(
        [_row(), {"email": "nope", "ref": REF}, _row(email="two@example.com")])
    assert len(kept) == 2 and len(problems) == 1
    path = _registry(tmp_path)
    path.write_text(json.dumps(kept), encoding="utf-8")
    assert len(rosters.load_rosters(path)) == 2


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def _week_data(tmp_path):
    return tuesday.load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE)


def _subscriber(**overrides) -> rosters.RosterSubscriber:
    spec = _spec()
    ref = encode_roster(overrides.pop("plan_ref", "season"), spec.scoring,
                        list(spec.slots), list(spec.player_ids))
    return rosters.RosterSubscriber(
        email=overrides.pop("email", "fan@example.com"), ref=ref,
        player_ids=spec.player_ids, slots=spec.slots, scoring=spec.scoring,
        **overrides)


def test_a_paid_roster_becomes_an_email(tmp_path) -> None:
    result = tuesday.run_subscriber(
        _subscriber(), _week_data(tmp_path),
        Path("rival-report-template.html").read_text(encoding="utf-8"),
        out_dir=tmp_path / "out", processed_dir=tmp_path / "processed")
    assert result.ok, result.detail
    assert result.html_path is not None and result.html_path.is_file()
    assert result.message is not None
    assert result.message.to == "fan@example.com"
    assert "your lineup, decided" in result.message.subject
    # The email body is the email-safe rendering; the browser-grade file on disk
    # is the archive. Mailing the latter ships soup through Word's engine.
    assert "var(--" not in result.message.html
    assert 'role="presentation"' in result.message.html
    assert "var(--" in result.html_path.read_text(encoding="utf-8")
    # The idempotency key is per (season, week, subscription) and carries no
    # address, because it is also the draft's filename.
    assert result.message.key.startswith(f"{SEASON}-w{WEEK:02d}-")
    assert "@" not in result.message.key


def test_no_report_ever_carries_a_roster_write_credential(
        tmp_path, monkeypatch) -> None:
    """This test used to assert the OPPOSITE — that the tokenised update link
    reached all three surfaces. It was codifying a vulnerability.

    The link rendered directly beneath _forward_line(), which invites the
    subscriber to forward this very file to their league ("Got this from a
    leaguemate?"). The token is an HMAC of their address, and run/updates.py
    rests its entire safety argument on that token reaching them "inside their
    own reports and nowhere else". So the product asked people to forward a
    document containing a credential that lets the recipient rewrite the
    sender's lineup for every remaining Tuesday — in a product framed around
    league rivalry, where the recipient is the most motivated adversary in the
    threat model. run/updates.py applies newest-first-seen per target with no
    confirmation step, so the change would be silent.

    It never shipped: update_url is None until SITE_URL and UPDATE_SECRET are
    both set. Removing it costs nothing today either — FORM_ENDPOINT is empty,
    so self-serve updates were not running, and the FAQ already answers roster
    changes with "reply to any file".

    Restoring the feature safely means CONFIRMING the change rather than
    authenticating it with a forwardable secret: accept the submission, mail
    the address already on the registry row, apply only when clicked. Then a
    forwarded report grants nothing and the real subscriber is told when
    somebody tries. Found Aug 27 2026.
    """
    template = Path("rival-report-template.html").read_text(encoding="utf-8")
    # WITH every launch secret set — the state that used to produce the leak.
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("UPDATE_SECRET", "s3")
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    result = tuesday.run_subscriber(_subscriber(origin="abc123def0"),
                                    _week_data(tmp_path), template,
                                    out_dir=tmp_path / "out",
                                    processed_dir=tmp_path / "processed")
    assert result.ok, result.detail

    surfaces = {
        "email html": result.message.html,
        "plain text": result.message.text,
        "archived html": result.html_path.read_text(encoding="utf-8"),
    }
    for name, body in surfaces.items():
        assert "token=" not in body, f"{name} carries a roster-write token"
        assert "abc123def0" not in body, f"{name} names the subscription"
        # The confirm-by-email link (Sep 29 2026) is the safe replacement:
        # public, the same for everyone, and useless without the inbox.
        assert "https://x.test/join/?update=1" in body, \
            f"{name} lost the roster update route"

    # The forward invitation stays — it is the one organic acquisition line,
    # and it is safe precisely because the file carries no secret.
    assert "leaguemate" in surfaces["email html"], \
        "the forward line went with it; only the credential should have"


def _ledger_rows(processed: Path) -> list[dict]:
    return [json.loads(line) for path in sorted(processed.rglob("calls.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_published_calls_are_recorded_the_week_they_are_published(
        tmp_path, monkeypatch) -> None:
    """Principle 2. A call not recorded at publication cannot be recovered
    later — there is no record of what the subscriber was shown. Publication
    is DELIVERY: building a report records nothing; the run that delivers it
    records every call it carried."""
    import run.delivery as delivery
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    processed = tmp_path / "processed"
    built = tuesday.run_subscriber(
        _subscriber(), _week_data(tmp_path),
        Path("rival-report-template.html").read_text(encoding="utf-8"),
        out_dir=tmp_path / "out", processed_dir=processed)
    assert built.ok and built.calls, built.detail
    assert not _ledger_rows(processed), "building a report wrote to the ledger"

    monkeypatch.setattr(tuesday, "build_provider", lambda *a: _Fake())
    assert tuesday.main(_main_args(tmp_path, _registry(tmp_path, _row()))
                        + ["--plans-dir", str(tmp_path / "plans")]) == 0
    calls = _ledger_rows(processed)
    assert calls, "a delivered report recorded nothing"
    assert all(call["status"] == "pending" for call in calls)
    assert all(call["confidence"] is not None for call in calls)


def test_the_same_call_from_two_subscribers_is_one_ledger_row(tmp_path) -> None:
    """Without a league the calls ARE league-agnostic — "this player beat that
    one at this slot" — so two subscribers who made the same call made one call.
    Recording it twice would inflate the public record with duplicates."""
    processed = tmp_path / "processed"
    data = _week_data(tmp_path)
    template = Path("rival-report-template.html").read_text(encoding="utf-8")
    first = tuesday.run_subscriber(_subscriber(), data, template,
                                   out_dir=tmp_path / "out",
                                   processed_dir=processed)
    second = tuesday.run_subscriber(_subscriber(email="other@example.com",
                                                origin="0123456789"), data,
                                    template, out_dir=tmp_path / "out",
                                    processed_dir=processed)
    assert first.ok and second.ok
    added, problems = tuesday.record_delivered(
        [first, second], [first.message.key, second.message.key], processed)
    assert not problems
    assert added == len(first.calls) > 0, "the same call was recorded twice"
    assert len(_ledger_rows(processed)) == len(first.calls)


def test_one_broken_roster_never_sinks_the_others(tmp_path) -> None:
    """The batch contract. A subscriber whose roster the directory has lost is
    one failed report, reported — not everybody else's Tuesday."""
    data = _week_data(tmp_path)
    template = Path("rival-report-template.html").read_text(encoding="utf-8")
    broken = _subscriber(email="broken@example.com")
    broken = rosters.RosterSubscriber(
        email=broken.email, ref=broken.ref,
        player_ids=("00-9999999",) + broken.player_ids[1:],
        slots=broken.slots, scoring=broken.scoring)
    results = [tuesday.run_subscriber(s, data, template, out_dir=tmp_path / "out",
                                      processed_dir=tmp_path / "processed")
               for s in (broken, _subscriber())]
    assert not results[0].ok and "00-9999999" in results[0].detail
    # The operator reads this in a CI log, so it says which ids were not found
    # rather than the repr of whatever was raised.
    assert "unexpected failure" not in results[0].detail
    assert "not in the" in results[0].detail
    assert results[1].ok


def test_a_run_with_a_failure_in_it_exits_non_zero(tmp_path, capsys) -> None:
    good, bad = _row(), _row(email="second@example.com",
                             player_ids=list(ROSTER_IDS))
    # A ref whose roster is real but whose players the directory never had.
    missing = [f"00-99999{i:02d}" for i in range(len(ROSTER_IDS))]
    bad["ref"] = encode_roster("season", "ppr", list(SLOTS), missing)
    bad["player_ids"] = missing
    code = tuesday.main(["--registry", str(_registry(tmp_path, good, bad)),
                         "--season", SEASON, "--week", str(WEEK),
                         "--cache", str(_cache(tmp_path)), "--no-paid-check",
                         "--no-send", "--out", str(tmp_path / "out"),
                         "--processed-dir", str(tmp_path / "processed")])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "1 reports written, 1 failed" in out


def test_an_unconfigured_send_says_nothing_was_sent_and_fails(tmp_path, capsys,
                                                              monkeypatch) -> None:
    """Dry-run is the right DEFAULT — a misconfigured cron must never mail
    people by accident — and never the right ACCIDENT. Asked to deliver with
    nothing configured it used to write drafts to an ephemeral runner, print
    "N sent" and exit 0: a green Tuesday with empty inboxes."""
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    code = tuesday.main(["--registry", str(_registry(tmp_path, _row())),
                         "--season", SEASON, "--week", str(WEEK),
                         "--cache", str(_cache(tmp_path)), "--no-paid-check",
                         "--out", str(tmp_path / "out"),
                         "--processed-dir", str(tmp_path / "processed")])
    captured = capsys.readouterr()
    assert code == 1
    assert "NOTHING WAS SENT" in captured.err


def test_a_league_pass_seat_is_entitled_through_its_payer(tmp_path,
                                                          monkeypatch) -> None:
    """A seat holder never paid us a cent — their commissioner did. Checking the
    seat's own address drops every seat, in the words meant for a cancellation,
    and leaves the $99 tier undeliverable."""
    from run.subscriptions import load_paid_list
    export = tmp_path / "paid.csv"
    export.write_text("email,active_subscription\npayer@example.com,true\n",
                      encoding="utf-8")
    paid = load_paid_list(export)
    seat = rosters.load_rosters(_registry(tmp_path, _row(
        email="seat@example.com", plan="league_pass",
        covered_by="payer@example.com")))[0]
    assert paid.entitles(seat)
    # And it dies with the pass that bought it: a lapsed commissioner must not
    # leave a league of people receiving a product nobody is paying for.
    export.write_text("email,active_subscription\npayer@example.com,false\n",
                      encoding="utf-8")
    assert not load_paid_list(export).entitles(seat)


def test_the_run_refuses_rather_than_mailing_people_who_cancelled(tmp_path,
                                                                  capsys) -> None:
    """With no entitlement source configured, nothing is sent. Silently mailing
    people who cancelled is the failure that becomes a chargeback."""
    code = tuesday.main(["--registry", str(_registry(tmp_path, _row())),
                         "--season", SEASON, "--week", str(WEEK),
                         "--cache", str(_cache(tmp_path)),
                         "--paid-list", str(tmp_path / "absent.csv"),
                         "--out", str(tmp_path / "out"),
                         "--processed-dir", str(tmp_path / "processed")])
    assert code == 1
    assert "will not mail anyone" in capsys.readouterr().err


def test_everyone_failing_the_paid_check_at_once_is_an_error(tmp_path,
                                                             capsys) -> None:
    """Far more likely a broken entitlement source than a business that lost
    every customer in one week. Exiting 0 made it a green cron with an empty
    inbox — the failure nobody notices until somebody asks where it went."""
    export = tmp_path / "paid.csv"
    export.write_text("email,active_subscription\nfan@example.com,false\n",
                      encoding="utf-8")
    code = tuesday.main(["--registry", str(_registry(tmp_path, _row())),
                         "--season", SEASON, "--week", str(WEEK),
                         "--cache", str(_cache(tmp_path)),
                         "--paid-list", str(export),
                         "--out", str(tmp_path / "out"),
                         "--processed-dir", str(tmp_path / "processed")])
    assert code == 1
    assert "NOTHING TO SEND" in capsys.readouterr().err


def test_a_preview_never_writes_to_the_public_record(tmp_path, capsys,
                                                     monkeypatch) -> None:
    """A call is PUBLISHED when it reaches a subscriber. The ledger is the
    record of what was published, and RULE L4 makes a graded entry immutable —
    so a preview that records claims we published calls nobody received, and
    there is no way to take it back.

    Reproduced before the fix: `--no-send` on an arbitrary week wrote 4 rows
    into the real store. Both preview paths are covered because they are
    different code paths: --no-send skips delivery, `make tuesday-preview` runs
    the dry PROVIDER.
    """
    processed = tmp_path / "processed"
    for extra in (["--no-send"], ["--allow-dry"]):
        monkeypatch.setenv("EMAIL_PROVIDER", "dry")
        code = tuesday.main(["--registry", str(_registry(tmp_path, _row())),
                             "--season", SEASON, "--week", str(WEEK),
                             "--cache", str(_cache(tmp_path)), "--no-paid-check",
                             "--out", str(tmp_path / "out"),
                             "--processed-dir", str(processed), *extra])
        assert code == 0, capsys.readouterr().err
        assert "nothing recorded" in capsys.readouterr().out
    assert not list(processed.rglob("calls.jsonl")), \
        "a preview wrote permanent rows into the public record"


def test_a_real_send_still_records_every_published_call(tmp_path, monkeypatch,
                                                        capsys) -> None:
    """The other half — the gate must not silence the record itself. And a
    report built with record=False carries no calls, so nothing downstream
    could record them even if it tried."""
    import run.delivery as delivery
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.setattr(tuesday, "build_provider", lambda *a: _Fake())
    processed = tmp_path / "processed"
    assert tuesday.main(_main_args(tmp_path, _registry(tmp_path, _row()))
                        + ["--plans-dir", str(tmp_path / "plans")]) == 0
    assert "new ledger row(s) from 1 delivered report(s)" in capsys.readouterr().out
    assert _ledger_rows(processed)
    preview = tuesday.run_subscriber(
        _subscriber(), _week_data(tmp_path),
        Path("rival-report-template.html").read_text(encoding="utf-8"),
        out_dir=tmp_path / "out", processed_dir=processed, record=False)
    assert preview.ok and preview.calls == [] and preview.store is None


# --------------------------------------------------------------------- #
# what a retry may and may not put on the record (launch review OPS-1)
# --------------------------------------------------------------------- #

def _flip_first_call(report: dict) -> dict:
    """A line move's worth of difference: the first published call reversed —
    the pick becomes the alternative — as a Tuesday market update or a stat
    correction overnight can do to a close call."""
    for slot in report["lineup"]:
        if slot.get("confidence") is not None and slot.get("alternative_id"):
            slot["player_id"], slot["alternative_id"] = (slot["alternative_id"],
                                                         slot["player_id"])
            slot["player_name"], slot["alternative_name"] = (
                slot["alternative_name"], slot["player_name"])
            slot["confidence"] = 0.509
            return report
    raise AssertionError("the fixture week publishes no call to flip")


def _flipping(monkeypatch) -> list:
    """Make every report built from now on carry a reversed first call, and
    count the builds."""
    real = tuesday.report_for
    builds: list = []

    def flipped(*a, **k):
        builds.append(1)
        return _flip_first_call(real(*a, **k))
    monkeypatch.setattr(tuesday, "report_for", flipped)
    return builds


def test_a_retry_puts_nothing_on_the_record_it_did_not_deliver(
        tmp_path, monkeypatch, capsys) -> None:
    """Launch review OPS-1, reproduced: run 1 mailed "Drake Maye over Dak
    Prescott 0.501" and recorded it. The 16:00 retry — or GitHub's backup,
    routinely 5-7 hours late — rebuilt every report after a normal Tuesday
    line move (NYJ@NE total 43.5 -> 42.0), sent nothing ("0 sent, 1 already
    sent"), and still wrote "1 new ledger row": "Dak Prescott over Drake Maye
    0.509". The inbox held one call; the public record held both, and one of
    them was bound to hit. `record_calls` ran inside the build, before
    `send_all` decided to skip. Now the record follows the inbox exactly."""
    import run.delivery as delivery
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    mailed = []

    class Sink(_Fake):
        def send(self, message, sender, reply_to):
            mailed.append(message)
            return "id-1"
    monkeypatch.setattr(tuesday, "build_provider", lambda *a: Sink())
    args = _main_args(tmp_path, _registry(tmp_path, _row())) + [
        "--plans-dir", str(tmp_path / "plans")]
    processed = tmp_path / "processed"

    assert tuesday.main(args) == 0
    first = {row["call_id"] for row in _ledger_rows(processed)}
    assert first and len(mailed) == 1

    _flipping(monkeypatch)
    assert tuesday.main(args) == 0
    assert "already sent" in capsys.readouterr().out
    assert len(mailed) == 1, "the retry mailed again"
    assert {row["call_id"] for row in _ledger_rows(processed)} == first, \
        "the retry recorded calls that no email carried"


def test_a_report_already_sent_this_week_is_not_rebuilt_unless_asked(
        tmp_path, monkeypatch, capsys) -> None:
    """Guard one of two (OPS-1): a subscriber whose report key is in the send
    log is skipped BEFORE the build — no archive, no plan, no calls — because
    the rebuild is a different report from the one in their inbox. A
    deliberate --resend rebuilds, re-sends and records what it sent."""
    import run.delivery as delivery
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    monkeypatch.setattr(tuesday, "build_provider", lambda *a: _Fake())
    args = _main_args(tmp_path, _registry(tmp_path, _row())) + [
        "--plans-dir", str(tmp_path / "plans")]
    sub = rosters.load_rosters(_registry(tmp_path, _row()))[0]
    log.write_text(json.dumps({"key": tuesday.report_key(SEASON, WEEK, sub.slug),
                               "provider": "fake", "message_id": "x",
                               "sent_at": "2026-10-13T12:05:00+00:00"}) + "\n")
    builds = _flipping(monkeypatch)
    assert tuesday.main(args) == 0
    assert builds == [], "a report already in an inbox was rebuilt"
    assert "1 already sent this week (not rebuilt)" in capsys.readouterr().out
    assert not _ledger_rows(tmp_path / "processed")

    assert tuesday.main(args + ["--resend"]) == 0
    assert builds == [1]
    flipped = _ledger_rows(tmp_path / "processed")
    assert any(row["confidence"] == 0.509 for row in flipped), \
        "a deliberate resend delivered a report and recorded nothing"


def test_a_send_that_fails_records_nothing(tmp_path, monkeypatch, capsys) -> None:
    """Guard two of two (OPS-1): only messages DELIVERED in this run reach the
    ledger. A provider outage used to leave every call recorded at build time
    with no email behind any of them. The run still leaves its marker (it ran,
    and says what failed) and exits 1, which files the issue."""
    import run.delivery as delivery
    from run.delivery import DeliveryError
    from run.watchdog import run_key
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)

    class Down(_Fake):
        def send(self, message, sender, reply_to):
            raise DeliveryError("provider down")
    monkeypatch.setattr(tuesday, "build_provider", lambda *a: Down())
    code = tuesday.main(_main_args(tmp_path, _registry(tmp_path, _row()))
                        + ["--plans-dir", str(tmp_path / "plans")])
    assert code == 1
    assert not _ledger_rows(tmp_path / "processed"), \
        "a report that never left recorded its calls"
    [marker] = [json.loads(line) for line in log.read_text().splitlines()]
    assert marker["key"] == run_key("tuesday", SEASON, WEEK)
    assert "send failed 1" in marker["message_id"]


# --------------------------------------------------------------------- #
# before launch, and the marker the watchdog reads (Oct 2026)
# --------------------------------------------------------------------- #

def _main_args(tmp_path, registry: Path) -> list[str]:
    return ["--registry", str(registry), "--season", SEASON, "--week", str(WEEK),
            "--cache", str(_cache(tmp_path)), "--no-paid-check",
            "--out", str(tmp_path / "out"),
            "--processed-dir", str(tmp_path / "processed")]


def test_before_launch_a_missing_registry_is_not_a_failure(tmp_path, capsys,
                                                          monkeypatch) -> None:
    """With no registry file and no Stripe key nobody can have paid, and the
    Tuesday cron failed on every run anyway — 16 "failed" issues about a
    checkout that was simply not open, which is how the one real failure gets
    ignored. Narrow on purpose: once a Stripe key exists a missing registry is
    a lost cache and fails, and a registry that exists but cannot be read
    fails whatever the key."""
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    absent = tmp_path / "nowhere" / "rosters.json"
    assert tuesday.main(_main_args(tmp_path, absent)) == 0
    assert "not set up yet" in capsys.readouterr().out
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    assert tuesday.main(_main_args(tmp_path, absent)) == 1
    monkeypatch.delenv("STRIPE_API_KEY")
    corrupt = tmp_path / "rosters.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert tuesday.main(_main_args(tmp_path, corrupt)) == 1
    assert "not valid JSON" in capsys.readouterr().err


class _Fake:
    name = "fake"

    def send(self, message, sender, reply_to):
        return "id-1"


def test_a_real_run_leaves_the_marker_with_its_counts_and_a_preview_does_not(
        tmp_path, monkeypatch) -> None:
    """The watchdog tells "Tuesday ran" from "GitHub never started it" by the
    send log, and only by the marker (launch review OPS-2: a report key there
    is shared with a new buyer's first email, so it proved nothing). A run
    that got as far as sending for real leaves `run-tuesday-<season>-wNN` —
    once, however many retries. A preview must not (it proves nothing about
    the real run, the same rule that keeps a dry run out of the ledger).

    A run with a report that could not be built DOES leave it now, saying so
    in its counts: it ran, it exits 1, and that files "Weekly run failed".
    The old rule (no marker on any failure) made the marker's absence mean two
    different things, and with report keys no longer evidence, one subscriber's
    broken roster would have read as a Tuesday GitHub never started."""
    import run.delivery as delivery
    from run.watchdog import run_key
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    marker = run_key("tuesday", SEASON, WEEK)
    args = _main_args(tmp_path, _registry(tmp_path, _row()))

    monkeypatch.setenv("EMAIL_PROVIDER", "dry")
    assert tuesday.main(args + ["--allow-dry"]) == 0
    assert marker not in delivery.load_sent(log)

    monkeypatch.setattr(tuesday, "build_provider", lambda *a: _Fake())
    assert tuesday.main(args + ["--plans-dir", str(tmp_path / "plans")]) == 0
    assert marker in delivery.load_sent(log)
    assert tuesday.main(args + ["--plans-dir", str(tmp_path / "plans")]) == 0
    assert sum(marker in line for line in log.read_text().splitlines()) == 1
    entry = next(json.loads(line) for line in log.read_text().splitlines()
                 if marker in line)
    assert entry["message_id"] == ("sent 1, already sent 0, send failed 0, "
                                   "not built 0")

    log.unlink()
    missing = [f"00-99999{i:02d}" for i in range(len(ROSTER_IDS))]
    bad = _row(email="second@example.com", player_ids=missing,
               ref=encode_roster("season", "ppr", list(SLOTS), missing))
    args = _main_args(tmp_path, _registry(tmp_path, _row(), bad))
    assert tuesday.main(args + ["--plans-dir", str(tmp_path / "plans")]) == 1
    entry = next(json.loads(line) for line in log.read_text().splitlines()
                 if marker in line)
    assert "not built 1" in entry["message_id"]


def test_a_tuesday_with_nobody_to_mail_still_says_it_ran(tmp_path, monkeypatch) -> None:
    """The first subscriber who joins after a week's kickoff gets the roster
    report, not that week's — so the send log holds no week-W report, and
    without this marker the watchdog would call a Tuesday that ran (to an
    empty registry) a Tuesday that never happened."""
    import run.delivery as delivery
    from run.watchdog import run_key
    log = tmp_path / "sent.jsonl"
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    monkeypatch.setattr(tuesday, "build_provider", lambda *a: _Fake())
    assert tuesday.main(_main_args(tmp_path, _registry(tmp_path))) == 0
    assert run_key("tuesday", SEASON, WEEK) in delivery.load_sent(log)


def test_the_tuesday_run_never_reports_on_a_week_already_underway(tmp_path, capsys,
                                                                  monkeypatch) -> None:
    """Launch audit (ops): the Worker starts the Tuesday run on time and
    GitHub's schedule is the backup, which can fire hours late; a hand re-run
    after Thursday's kickoff would publish and permanently record calls about
    a game being played. A DERIVED week that has kicked off sends nothing and
    exits 0; an explicit --week is a deliberate rebuild and still builds."""
    import run.tuesday as t
    monkeypatch.setattr(t, "week_has_kicked_off", lambda *a, **k: True)
    real = t.load_week_data
    monkeypatch.setattr(t, "load_week_data",
                        lambda cache, season, week, **k: real(cache, SEASON, WEEK, session=OFFLINE))
    args = ["--registry", str(_registry(tmp_path, _row())), "--cache", str(_cache(tmp_path)),
            "--no-paid-check", "--no-send", "--out", str(tmp_path / "out"),
            "--processed-dir", str(tmp_path / "processed")]
    assert t.main(args) == 0
    assert "already kicked off" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()
    # Explicit week: built (a backfill or the proving run).
    assert t.main(args + ["--season", SEASON, "--week", str(WEEK)]) == 0
    assert (tmp_path / "out").exists()
