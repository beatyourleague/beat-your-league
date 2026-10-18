"""League Pass seats and the subscription lifecycle, through the real intake.

The seat path is the one signup with no payment behind it, and it failed in
silence three ways (LP-D1/D3/D4): a claim that matched no pass vanished, a
re-claim became a second seat, and the registry flattened a pass payer and a
monthly buyer to "season", so their last report described somebody else's
billing. These tests drive run.intake end to end against the fake Stripe and
form backend in test_intake_sync, plus the per-pass seat link (contract C4),
the channel tag a payment carries (C5) and the first email a seat earns
(LP-I4).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import run.intake as intake
from run.refs import encode_roster
from run.rosters import load_rosters
from run.updates import seat_token, seat_url, slug_of
from test_intake_sync import (MONTHLY_LINK, PASS_LINK, PASS_REF, PASS_SUB, PLAYERS,
                              REF, SEASON_LINK, SEAT_REF, SLOTS, _capture_sends,
                              _confirmed_seats, _pass_session, _registry, _run,
                              _seat, _seat_confirm, _seats, _session, directory,
                              stripe)  # noqa: F401 — fixtures

LINKS = f"s:{SEASON_LINK},m:{MONTHLY_LINK},p:{PASS_LINK}"
SECRET = "test-secret-do-not-ship"
NOW = datetime.now(timezone.utc)
LINK = "https://x.test/join/?pass=0123456789abcdef0123&s=ppr&n=10&t=nokd"


def _at(hours_ago: float) -> str:
    """A Worker stamp (`new Date().toISOString()`), ``hours_ago`` before now."""
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


def _notes(sends):
    return [m for m in sends if m.key.startswith("seat-unmatched-")]


# --------------------------------------------------------------------- #
# LP-D1 — a claim that matches no pass is told so, once
# --------------------------------------------------------------------- #

def test_a_claim_that_matches_no_pass_is_told_once_and_counted(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Reproduced (LP-D1): a leaguemate typed 'comish@example.com' for a pass
    bought as 'commish@example.com'. The page said "Your seat request is in",
    seats_to_rows returned no row and a CI-log line, the intake exited 0, and
    nobody — not the leaguemate, not the buyer — ever heard another word. Now
    the claimer gets one note per claim saying it matched no pass and what to
    check, the intake counts unmatched claims, and the buyer hears nothing
    about anybody (a stranger's claim is not their business)."""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    # D10: a League Pass on file without UPDATE_SECRET exits non-zero.
    monkeypatch.setenv("UPDATE_SECRET", "test-secret-do-not-ship")
    stripe["sessions"] = [_pass_session()]
    _seats(monkeypatch, _seat(covered_by="comish@example.com", received_at=_at(8)))
    assert _run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "1 matched no League Pass" in out
    [note] = _notes(sends)
    assert note.to == "member@example.com"
    assert "didn't match a League Pass" in note.text and "seat link" in note.text
    assert "@" not in note.key
    assert not any(r.get("plan") == "league_pass" for r in _registry(tmp_path))
    for message in sends:
        if message.to == "commish@example.com":
            assert "member" not in message.text and "match" not in message.text
    assert _run(tmp_path) == 0
    assert len(_notes(sends)) == 1, "the same claim was told twice"


def test_the_unmatched_note_is_held_to_every_email_clients_rules() -> None:
    """The new email is held to what tests/test_email_safety.py holds every
    other one to: nothing Outlook or Gmail cannot render, absolute https links
    only, light-only colour scheme, a padded preview line, a title and a
    language — and it names nobody, says "report" (never "file") and carries
    no betting or banned words."""
    import re

    from render.seat_claim import unmatched_email
    from test_email_safety import FORBIDDEN
    subject, html, text = unmatched_email("https://x.test/")
    hits = [p for p in FORBIDDEN if re.search(p, html, re.I)]
    assert not hits, hits
    assert not re.findall(r'<table(?![^>]*role="presentation")', html)
    assert all(h.startswith("https://") for h in re.findall(r'href="([^"]*)"', html))
    assert '<meta name="color-scheme" content="light only">' in html
    assert "&#847;&zwnj;&nbsp;" in html and "<title>" in html and 'lang="en"' in html
    assert "https://x.test/league-pass.html" in text
    from render.sender import CONTACT
    for words in (subject, text.replace(CONTACT, "")):
        assert "@" not in words and " file" not in words.lower()
        for banned in ("calibrated", "tested", "proven", "accurate", "bet ", "odds"):
            assert banned not in words.lower(), banned
    assert "https://" not in unmatched_email("")[2], "no site, no link"


def test_a_note_waits_out_the_grace_period_skips_stale_claims_and_is_capped() -> None:
    """A leaguemate can claim minutes before the buyer's payment is swept, so
    "no pass" is said only after UNMATCHED_GRACE; a claim older than
    UNMATCHED_MAX_AGE (Worker rows live ~400 days) is never answered; an
    unstamped one cannot be shown fresh; and because the form is public, at
    most UNMATCHED_PER_DAY notes reach one address a day."""
    claim = {"email": "m@example.com", "covered_by": "x@example.com", "ref": SEAT_REF}
    fresh = dict(claim, received_at=_at(1))
    ready = dict(claim, received_at=_at(8))
    stale = dict(claim, received_at=_at(24 * 30))
    unstamped = dict(claim)
    assert intake.unmatched_due([fresh, stale, unstamped], NOW) == []
    assert intake.unmatched_due([ready], NOW) == [ready]
    burst = [dict(claim, received_at=_at(8 + i / 60), ref=SEAT_REF) for i in range(4)]
    due = intake.unmatched_due(burst, NOW)
    assert len(due) == intake.UNMATCHED_PER_DAY
    assert len({intake.unmatched_key(r) for r in burst}) == 4, "one key per claim"


# --------------------------------------------------------------------- #
# LP-D4 — a re-claim is a roster change, never a second seat
# --------------------------------------------------------------------- #

NEWER_SEAT_REF = encode_roster("season", "ppr", list(SLOTS),
                               PLAYERS[1:] + PLAYERS[:1])


def test_a_reclaim_is_a_roster_change_not_a_second_seat(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Reproduced (LP-D4): two claims by mate@ under the same pass, refs one
    player apart, produced two seat rows — two weekly reports, old roster and
    new, forever (Worker rows live 400 days). Now one seat per (address,
    pass): the newest CONFIRMED claim's roster stands, under the slug it was
    FIRST claimed with, so its send keys, plans and link never move, and it
    is welcomed once."""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    stripe["sessions"] = [_pass_session()]
    first = _seat(received_at=_at(48))
    _confirmed_seats(monkeypatch, first)
    assert _run(tmp_path) == 0
    newer = _seat(ref=NEWER_SEAT_REF, received_at=_at(2))
    _confirmed_seats(monkeypatch, first, newer)
    assert _run(tmp_path) == 0
    seats = [s for s in load_rosters(tmp_path / intake.REGISTRY_NAME) if s.is_league_seat]
    assert len(seats) == 1, "a re-claim became a second seat"
    assert "1 with a confirmed new roster" in capsys.readouterr().out
    [seat] = seats
    assert seat.ref == NEWER_SEAT_REF and seat.slug == _origin(first)
    assert seat.roster_as_of == (NOW - timedelta(hours=2)).date().isoformat()
    welcomes = [m for m in sends if m.key.startswith("welcome-") and m.to == seat.email]
    assert len(welcomes) == 1, [m.key for m in welcomes]


def test_a_newer_claim_is_not_undone_by_an_older_update() -> None:
    """A seat re-claimed through its link after a confirmed update: the claim
    is the newer roster, and replaying the older update over it every run
    would silently ignore the claim — LP-D4's failure by another door."""
    from run.updates import RosterUpdate, apply_updates
    row = {"email": "m@example.com", "ref": NEWER_SEAT_REF, "origin": slug_of(SEAT_REF)}
    update = RosterUpdate(email="m@example.com", replaces=slug_of(SEAT_REF), ref=REF,
                          seen_at=(NOW - timedelta(days=1)).isoformat(timespec="seconds"))
    latest = {("m@example.com", slug_of(SEAT_REF)): update}
    claimed = {("m@example.com", slug_of(SEAT_REF)): NOW - timedelta(hours=2)}
    [kept], applied = apply_updates([row], latest, since=claimed)
    assert applied == 0 and kept["ref"] == NEWER_SEAT_REF
    [moved], applied = apply_updates([row], latest)
    assert applied == 1 and moved["ref"] == REF
    assert moved["roster_as_of"] == update.seen_at[:10]


# --------------------------------------------------------------------- #
# LP-D3 + contract C1 — the registry keeps what was bought
# --------------------------------------------------------------------- #

def test_a_payer_and_a_monthly_buyer_are_no_longer_flattened_to_season(
        tmp_path, stripe, directory, monkeypatch) -> None:
    """Reproduced (LP-D3): to_rows wrote plan "season" for every paid signup,
    so a monthly buyer — whose billing stops itself — and a $99 League Pass
    buyer were each told in their Week 18 report "Your season pass renews once
    a year". The row now carries its billing, and a report's meta["plan"]
    (contract C1) is season | monthly | pass | league_pass (a seat)."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    monthly = encode_roster("monthly", "ppr", list(SLOTS), PLAYERS[::-1])
    stripe["sessions"] = [
        _session(REF),
        _session(monthly, sid="cs_m", email="month@example.com",
                 link=MONTHLY_LINK, customer="cus_month001"),
        _pass_session()]
    _confirmed_seats(monkeypatch, _seat(received_at=_at(3)))
    assert _run(tmp_path) == 0
    plans = {s.email: s.report_plan for s in load_rosters(tmp_path / intake.REGISTRY_NAME)}
    assert plans == {"fan@example.com": "season", "month@example.com": "monthly",
                     "commish@example.com": "pass", "member@example.com": "league_pass"}


def test_a_report_carries_the_plan_the_seat_count_and_the_roster_day(tmp_path) -> None:
    """Contracts C1-C4 on the report itself: the plan; a pass payer's seat
    count — their own team plus every seat the pass carries — out of their
    own league size (a count, never who); the day the roster in use was set;
    and, in a pass league only, the league's seat link, so a forwarded report
    points a leaguemate at the seat already paid for (LP-D2). Built through
    run.tuesday.run_subscriber."""
    import run.tuesday as tuesday
    from run.rosters import RosterSubscriber
    from test_solo_run import OFFLINE, SEASON, WEEK, _cache
    data = tuesday.load_week_data(_cache(tmp_path), SEASON, WEEK, session=OFFLINE)
    seen: list[dict] = []
    real = tuesday.text_summary

    def capture(report):
        seen.append(report)
        return real(report)
    template = tuesday.render_report.TEMPLATE_PATH.read_text(encoding="utf-8")
    base = dict(email="commish@example.com", ref=REF, player_ids=tuple(PLAYERS),
                slots=SLOTS, scoring="ppr", league_size=10)
    payer = RosterSubscriber(**base, billing="pass", roster_as_of="2026-09-02")
    seat = RosterSubscriber(**dict(base, email="m@example.com"), plan="league_pass",
                            covered_by="commish@example.com")
    monthly = RosterSubscriber(**dict(base, email="mo@example.com"), plan="monthly")
    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(tuesday, "text_summary", capture)
        for sub in (payer, seat, monthly):
            result = tuesday.run_subscriber(sub, data, template, out_dir=tmp_path / "o",
                                            processed_dir=tmp_path / "p", record=False,
                                            seat_counts={"commish@example.com": 2},
                                            seat_link=LINK)
            assert result.ok, result.detail
    payer_meta, seat_meta, monthly_meta = (r["meta"] for r in seen)
    assert payer_meta["plan"] == "pass"
    assert payer_meta["seats_claimed"] == {"claimed": 2, "size": 10}
    assert payer_meta["seat_link"] == seat_meta["seat_link"] == LINK
    assert "seat_link" not in monthly_meta
    assert payer_meta["roster_as_of"] == "2026-09-02"
    assert seat_meta["plan"] == "league_pass" and "seats_claimed" not in seat_meta
    assert monthly_meta["plan"] == "monthly" and "seats_claimed" not in monthly_meta
    assert "roster_as_of" not in seat_meta, "a day nobody recorded was printed"


def test_the_registry_rejects_billing_that_contradicts_the_plan(tmp_path) -> None:
    """The two fields overlap and must agree, or the season-end sentence
    describes somebody else's money: a seat bills nobody, and monthly is
    billed monthly and nothing else is. A malformed roster day fails too —
    the loader is whole-file on purpose, so the writer validates first."""
    from run.rosters import RosterRegistryError, drop_unloadable
    row = {"email": "a@example.com", "ref": REF, "player_ids": list(PLAYERS),
           "slots": list(SLOTS), "scoring": "ppr"}
    for bad in (dict(row, plan="league_pass", covered_by="p@example.com", billing="pass"),
                dict(row, plan="monthly", billing="season"),
                dict(row, plan="season", billing="monthly"),
                dict(row, billing="lifetime"),
                dict(row, roster_as_of="Sept 2")):
        kept, problems = drop_unloadable([bad])
        assert not kept and problems, bad
    kept, _ = drop_unloadable([dict(row, billing="pass", roster_as_of="2026-09-02")])
    assert kept


# --------------------------------------------------------------------- #
# contract C4 — the per-pass seat link
# --------------------------------------------------------------------- #

def test_the_seat_link_names_the_pass_and_carries_its_setup() -> None:
    """LP-I1/LP-I3: every pass shared join/?pass=1 and each leaguemate typed
    the buyer's address and re-picked scoring, size and lineup. The link now
    carries a digest of the payer under UPDATE_SECRET (one mailbox, one
    token: +tags and Gmail dots canonicalised as the free report does) and
    the payer's own settings as the join page's radio values."""
    token = seat_token("commish@example.com", SECRET)
    assert len(token) == 20 and int(token, 16) >= 0
    assert seat_token("Commish+league@Example.com", SECRET) == token
    assert seat_token("com.mish@gmail.com", SECRET) == seat_token("commish@gmail.com", SECRET)
    assert seat_token("commish@example.com", "other") != token
    from run.refs import decode_roster
    url = seat_url("https://x.test/", SECRET, "commish@example.com", decode_roster(PASS_REF))
    assert url == f"https://x.test/join/?pass={token}&s=ppr&n=12&t=nokd"
    assert "commish" not in url and "@" not in url
    assert seat_url("", SECRET, "commish@example.com", decode_roster(PASS_REF)) is None
    assert seat_url("https://x.test", "", "commish@example.com", decode_roster(PASS_REF)) is None


def test_a_claim_through_the_seat_link_is_matched_without_any_address_typed(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The token is recomputed over the addresses that really bought a pass —
    never trusted from the row — and a matched one is a seat exactly like a
    typed covered_by. A token that matches no pass is unmatched (LP-D1)."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    stripe["sessions"] = [_pass_session()]
    good = {"email": "member@example.com", "ref": SEAT_REF,
            "pass_token": seat_token("commish@example.com", SECRET, PASS_SUB),
            "received_at": _at(1)}
    forged = {"email": "other@example.com", "ref": SEAT_REF,
              "pass_token": seat_token("nobody@example.com", SECRET), "received_at": _at(1)}
    _seats(monkeypatch, good, forged, _seat_confirm(good))
    assert _run(tmp_path) == 0
    seats = [s for s in load_rosters(tmp_path / intake.REGISTRY_NAME) if s.is_league_seat]
    assert [(s.email, s.covered_by) for s in seats] == [
        ("member@example.com", "commish@example.com")]
    err = capsys.readouterr().err
    assert "seat link that matches no League Pass" in err


def test_only_a_pass_payer_gets_a_seat_link(monkeypatch) -> None:
    """None without a site or a secret: the welcome then keeps the generic
    link and the email instruction rather than a link nothing can match."""
    from run.intake import RosterSignup, pass_seat_link
    payer = RosterSignup(email="commish@example.com", ref=PASS_REF, plan="league_pass",
                         seen_at="1791500000", subscription_id=PASS_SUB)
    season = RosterSignup(email="fan@example.com", ref=REF, plan="season", seen_at="1")
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    assert pass_seat_link(payer).startswith("https://x.test/join/?pass=")
    assert pass_seat_link(season) is None
    # A pass that started no subscription can carry no seat (RULE E2), so a
    # link printed for it would match nothing.
    assert pass_seat_link(RosterSignup(email="commish@example.com", ref=PASS_REF,
                                       plan="league_pass", seen_at="1")) is None
    monkeypatch.delenv("UPDATE_SECRET")
    assert pass_seat_link(payer) is None


def test_the_pass_welcome_carries_its_seat_link(tmp_path, stripe, directory,
                                                monkeypatch) -> None:
    """Contract C4, both halves: the intake passes render.welcome a seat_link
    for a pass payer, and the welcome shows it as the one link to share. (The
    welcome half is render/welcome.py's; this fails until it takes
    ``seat_link``.)"""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    stripe["sessions"] = [_pass_session()]
    assert _run(tmp_path) == 0
    [welcome] = [m for m in sends if m.key.startswith("welcome-")]
    token = seat_token("commish@example.com", SECRET, PASS_SUB)
    assert f"https://x.test/join/?pass={token}" in welcome.text


# --------------------------------------------------------------------- #
# contract C5 — a purchase says which channel it came from
# --------------------------------------------------------------------- #

def test_a_payments_channel_tag_is_kept_off_the_roster_and_on_the_customer(
        tmp_path, stripe, directory, monkeypatch) -> None:
    """G09: ?via= reached only free form rows, never the purchase, so sales by
    channel could not be counted. The join page appends "_via-<tag>" to the
    reference; the intake strips it BEFORE anything reads the ref (the slug,
    send keys, filenames and the registry must not move with a channel) and
    stamps byl_via on the Customer. A ref whose tail only looks like a tag is
    left whole for the normal checks."""
    stripe["sessions"] = [_session(REF + "_via-reddit")]
    assert _run(tmp_path) == 0
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.ref == REF and row.slug == slug_of(REF)
    [(_url, form)] = stripe["posts"]
    assert form["metadata[byl_via]"] == "reddit"
    assert form["metadata[byl_roster_ref]"] == REF
    assert intake.split_via(REF) == (REF, None)
    assert intake.split_via(REF + "_via-Bad Tag") == (REF + "_via-Bad Tag", None)
    assert intake.split_via("s3-zz_via-x") == ("s3-zz_via-x", None)


# --------------------------------------------------------------------- #
# LP-I4 — a seat's first email, the day it is claimed
# --------------------------------------------------------------------- #

def test_a_seat_claimed_before_kickoff_gets_that_weeks_report_the_same_day(
        tmp_path, monkeypatch) -> None:
    """Reproduced (LP-I4): _send_first_files iterated paid signups only, so a
    leaguemate claiming from the group chat on a Wednesday waited until next
    Tuesday — group-chat momentum gone. A seat is now served by the paid
    rules: between Tuesday's send and kickoff, that week's report, built as a
    SEAT (no billing lines; its stop route, not a billing page) and keyed on
    the slug it was first claimed under. Purchase-keyed: never twice."""
    from test_intake_sync import _Sink, _first_email_env
    up = _Sink()
    data, season, week = _first_email_env(tmp_path, monkeypatch, up)
    claimed = NOW - timedelta(hours=1)
    rows = [{"email": "member@example.com", "ref": NEWER_SEAT_REF, "plan": "league_pass",
             "covered_by": "commish@example.com", "origin": slug_of(SEAT_REF)}]
    seats = intake.seat_signups_from(rows, {("member@example.com", slug_of(SEAT_REF)):
                                            claimed})
    assert [s.slug for s in seats] == [slug_of(SEAT_REF)]
    for _ in range(2):
        intake._send_first_files(seats, data, season, processed_dir=tmp_path / "p",
                                 first_plans=tmp_path / "first", out_dir=tmp_path / "out")
    assert [m.key for m in up.sent] == [f"{season}-w{week:02d}-{slug_of(SEAT_REF)}"]
    [message] = up.sent
    assert message.to == "member@example.com"
    assert message.unsubscribe and message.unsubscribe.startswith("mailto:"), \
        "a seat's report pointed its way out at a billing page"
    assert "billing page" not in message.text.lower()


def test_the_intake_mails_a_new_seat_its_first_report_in_the_same_run(
        tmp_path, stripe, monkeypatch) -> None:
    """The wiring, end to end: one hourly intake sees the pass payment and a
    seat claimed through it, and BOTH get that week's report before kickoff —
    the payer's carrying their seat count (contract C2), the seat's built as
    a seat. A payer's report counts only seats that were honoured."""
    from test_intake_sync import _Sink, _first_email_env
    up = _Sink()
    data, season, week = _first_email_env(tmp_path, monkeypatch, up)
    monkeypatch.setattr(intake, "load_week_data", lambda *a, **k: data)
    # A delivered week's report records its calls: into a ledger of the
    # test's own, never the repo's public record.
    monkeypatch.setattr("run.tuesday.PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    stripe["sessions"] = [_pass_session()]
    claim = _seat(received_at=_at(1))
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    _seats(monkeypatch, claim,
           _seat(email="stray@example.com", covered_by="nobody@example.com",
                 received_at=_at(1)), _seat_confirm(claim))
    seen: list[dict] = []
    import run.tuesday as tuesday
    real = tuesday.text_summary
    monkeypatch.setattr(tuesday, "text_summary",
                        lambda report: seen.append(report) or real(report))
    assert intake.main(["--registry-dir", str(tmp_path / "reg")]) == 0
    weekly = {m.to: m for m in up.sent if m.key.startswith(f"{season}-w{week:02d}-")}
    assert set(weekly) == {"commish@example.com", "member@example.com"}
    assert list((tmp_path / "processed").rglob("calls.jsonl")), \
        "the delivered reports recorded nothing"
    plans = {r["meta"]["plan"]: r["meta"] for r in seen}
    assert plans["pass"]["seats_claimed"] == {"claimed": 1, "size": 12}
    assert "seats_claimed" not in plans["league_pass"]


def test_a_seats_link_is_its_payers_with_the_payers_setup(monkeypatch) -> None:
    """The link a seat's report carries is the PASS's (its payer's token), in
    the payer's scoring, size and lineup — not a link of its own, which would
    match no pass — and a season subscriber's report carries none."""
    import run.tuesday as tuesday
    from run.rosters import RosterSubscriber
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    base = dict(ref=REF, player_ids=tuple(PLAYERS), slots=SLOTS, scoring="ppr")
    payer = RosterSubscriber(email="commish@example.com", **dict(base, scoring="ppr"),
                             league_size=10, billing="pass")
    seat = RosterSubscriber(email="m@example.com", **base, plan="league_pass",
                            covered_by="Commish@example.com")
    season = RosterSubscriber(email="fan@example.com", **base)
    payers = {"commish@example.com": payer}
    token = seat_token("commish@example.com", SECRET)
    expected = f"https://x.test/join/?pass={token}&s=ppr&n=10&t=nokd"
    assert tuesday.league_seat_link(payer, payers) == expected
    assert tuesday.league_seat_link(seat, payers) == expected
    assert tuesday.league_seat_link(season, payers) is None


# --------------------------------------------------------------------- #
# OPS-R1 — a claim is a request: the claimed address confirms it
# --------------------------------------------------------------------- #

from dataclasses import replace  # noqa: E402

from run.updates import seat_code  # noqa: E402

PASSES = [intake.PassInfo("commish@example.com", PASS_SUB, 12, "cus_commish01")]


def _origin(first: dict, pass_id: str = PASS_SUB) -> str:
    """A seat's slug: its FIRST confirmed claim (EMAILS-146)."""
    return intake.seat_origin(intake.SeatEntry(
        email=first["email"], pass_id=pass_id, payer="", ref=first["ref"],
        claimed_at=first["received_at"], confirmed_at=""))


def _claim(email="m@example.com", ref=SEAT_REF, hours=2.0, **over) -> dict:
    row = {"email": email, "covered_by": "commish@example.com", "ref": ref,
           "received_at": _at(hours)}
    row.update(over)
    return row


def _code(row: dict, secret: str = SECRET, pass_id: str = PASS_SUB) -> str:
    return seat_code(row["email"], pass_id, row["ref"], row["received_at"], secret)


def _seat_rows(tmp_path) -> list:
    return [s for s in load_rosters(tmp_path / intake.REGISTRY_NAME) if s.is_league_seat]


def test_a_seat_claim_is_a_request_until_the_claimed_address_confirms_it(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Reproduced (OPS-R1): a second POST through the per-pass seat link
    carrying {email: victim, ref: roster D} swapped the victim's seat to
    roster D on the next intake — "1 re-claimed with a new roster" — and
    nobody was told; the same POST naming a stranger enrolled that stranger
    for weekly mail. The seat link rides on every pass report, written to be
    forwarded, so holding it proves nothing. Now a claim is mailed a code at
    the CLAIMED address only, and becomes a seat (or a roster change) only
    when that code comes back through the confirm page's button."""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    monkeypatch.setenv("SITE_URL", "https://x.test")
    stripe["sessions"] = [_pass_session()]
    token = seat_token("commish@example.com", SECRET, PASS_SUB)
    claim = {"email": "member@example.com", "ref": SEAT_REF, "pass_token": token,
             "received_at": _at(3)}
    _seats(monkeypatch, claim)
    assert _run(tmp_path) == 0
    assert _seat_rows(tmp_path) == [], "a claim became a seat with nobody confirming it"
    [ask] = [m for m in sends if m.key.startswith("seat-confirm-")]
    assert ask.to == "member@example.com" and "@" not in ask.key
    code = _code(claim)
    assert f"https://x.test/join/confirm.html?c={code}&k=seat" in ask.text
    assert not [m for m in sends if m.to == "member@example.com"
                and m.key.startswith("welcome-")]

    pressed = {"kind": "confirm", "code": code, "received_at": _at(2)}
    _seats(monkeypatch, claim, pressed)
    assert _run(tmp_path) == 0
    [seat] = _seat_rows(tmp_path)
    assert seat.ref == SEAT_REF and seat.slug == _origin(claim)
    assert len([m for m in sends if m.key.startswith("welcome-")
                and m.to == "member@example.com"]) == 1

    # The attack: the same link, the victim's address, another roster.
    forged = dict(claim, ref=NEWER_SEAT_REF, received_at=_at(1))
    stranger = dict(claim, email="stranger@example.com", received_at=_at(1))
    _seats(monkeypatch, claim, pressed, forged, stranger)
    assert _run(tmp_path) == 0
    seats = {s.email: s for s in _seat_rows(tmp_path)}
    assert set(seats) == {"member@example.com"}, "a stranger was enrolled by a link"
    assert seats["member@example.com"].ref == SEAT_REF, \
        "a seat's roster was replaced with nobody confirming it"
    change = [m for m in sends if m.key == intake.seat_confirmation_key(
        intake.PendingSeat("member@example.com", PASS_SUB, NEWER_SEAT_REF,
                           _code(forged), forged["received_at"], change=True))]
    assert [m.to for m in change] == ["member@example.com"]
    assert "change the roster on your League Pass seat" in change[0].text
    before = len(sends)
    assert _run(tmp_path) == 0
    assert len(sends) == before, "a confirmation was mailed twice"


def test_a_seat_code_is_bound_to_its_claim_expires_and_is_single_use() -> None:
    """The code binds (address, pass, roster, the Worker's stamp on the claim)
    and the signing secret; it works for EXPIRY_DAYS after the claim, judged
    by when the button was PRESSED (not by when an intake happened to run);
    and once a newer claim for the seat is confirmed, an older one's code is
    dead — a stale email can never put an old roster back."""
    a = _claim(hours=48)
    b = _claim(ref=NEWER_SEAT_REF, hours=24)
    swept = intake.sweep_seats([a, b], PASSES, None, SECRET, confirm_codes=[_code(a)])
    assert [r["ref"] for r in swept.rows] == [SEAT_REF]
    assert [p.ref for p in swept.awaiting] == [NEWER_SEAT_REF]
    assert intake.sweep_seats([a], PASSES, None, SECRET,
                              confirm_codes=[_code(a, "other")]).rows == []
    log = swept.confirmed
    newer = intake.sweep_seats([a, b], PASSES, None, SECRET,
                               confirm_codes=[_code(b)], log=log)
    assert [r["ref"] for r in newer.rows] == [NEWER_SEAT_REF]
    assert newer.rows[0]["origin"] == _origin(a), "the seat's slug moved"
    replay = intake.sweep_seats([a, b], PASSES, None, SECRET,
                                confirm_codes=[_code(a), _code(b)],
                                log=[*log, *newer.confirmed])
    assert [r["ref"] for r in replay.rows] == [NEWER_SEAT_REF] and not replay.confirmed
    # An OLDER claim's email pressed after a newer claim was confirmed: dead.
    stale = intake.sweep_seats([a, b], PASSES, None, SECRET,
                               confirm_codes=[_code(a)], log=newer.confirmed)
    assert not stale.confirmed, "a stale code was honoured after a newer claim"
    assert stale.rows[0]["origin"] == _origin(b)
    old = _claim(hours=24 * 8)
    late = intake.sweep_seats([old], PASSES, None, SECRET,
                              confirm_codes=[{"code": _code(old), "received_at": _at(0)}])
    assert late.rows == [] and late.awaiting == [], "an expired claim was honoured"
    in_time = intake.sweep_seats(
        [old], PASSES, None, SECRET,
        confirm_codes=[{"code": _code(old), "received_at": _at(24 * 8 - 1)}])
    assert len(in_time.rows) == 1, "a code pressed in time was lost to a late run"


# --------------------------------------------------------------------- #
# OPS-R4 / OPS-R5 / LP2-D2 — a seat lives on its PASS
# --------------------------------------------------------------------- #

def _seat_sub(**over):
    from run.rosters import RosterSubscriber
    base = dict(email="m@example.com", ref=SEAT_REF, player_ids=tuple(PLAYERS[::-1]),
                slots=tuple(SLOTS), scoring="ppr", plan="league_pass",
                covered_by="commish@example.com", pass_id=PASS_SUB)
    base.update(over)
    return RosterSubscriber(**base)


def test_a_seat_is_entitled_by_its_pass_subscription_not_its_payers_address() -> None:
    """Reproduced (OPS-R4, LP2-D2): PaidList.entitles asked whether the
    payer's ADDRESS held any entitled subscription, so a refunded or
    cancelled $99 pass kept every seat served while the payer kept a $14.99
    monthly. And (OPS-R5) a payer who changed their billing email in the
    portal dropped every seat, because the seat named the purchase-time
    address. A seat now names the pass subscription itself (RULE E2)."""
    from pathlib import Path

    from run.subscriptions import PaidList
    seat = _seat_sub()
    refunded = PaidList(emails=frozenset({"commish@example.com"}), source="stripe",
                        status_column="active", customer_ids=frozenset({"cus_commish01"}),
                        subscription_ids=frozenset({"sub_monthly01"}))
    assert not refunded.entitles(seat), "a refunded pass kept its seats"
    moved = PaidList(emails=frozenset({"commish.new@example.com"}), source="stripe",
                     status_column="active", customer_ids=frozenset({"cus_commish01"}),
                     subscription_ids=frozenset({PASS_SUB}))
    assert moved.entitles(seat), "a billing-email change dropped the seat"
    assert not moved.entitles(replace(seat, pass_id=None)), \
        "on Stripe, a seat naming no pass must not be entitled"
    csv = PaidList(emails=frozenset({"commish@example.com"}), source=Path("x.csv"),
                   status_column="status")
    assert csv.entitles(replace(seat, pass_id=None)), "the CSV path lost its route"


def test_stripe_names_only_entitled_unrefunded_subscriptions(stripe) -> None:
    """load_paid_from_stripe collects the ids RULE E2 reads: active or
    trialing, and never one whose latest charge went back in full."""
    from run.subscriptions import load_paid_from_stripe
    customer = {"id": "cus_commish01", "email": "commish@example.com"}
    refunded = {"charge": {"refunded": True, "amount": 9900, "amount_refunded": 9900}}
    stripe["subscriptions"] = [
        {"id": PASS_SUB, "status": "active", "customer": customer,
         "latest_invoice": refunded},
        {"id": "sub_monthly01", "status": "active", "customer": customer},
        {"id": "sub_trial0001", "status": "trialing", "customer": customer},
        {"id": "sub_late00001", "status": "past_due", "customer": customer}]
    paid = load_paid_from_stripe("sk_test")
    assert paid.subscription_ids == {"sub_monthly01", "sub_trial0001"}
    assert paid.refunded == {PASS_SUB}


def test_a_refunded_pass_ends_its_seats_and_welcomes_no_new_one(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Reproduced (OPS-R4): with the pass refunded and the payer still on a
    $39 season plan, the intake welcomed a newly claimed seat, sent it the
    week's report and recorded its calls; only Tuesday then dropped it. The
    intake now reads which passes are ACTIVE before a seat is confirmed,
    welcomed or written: a confirmed seat on a lapsed pass leaves the
    registry, and a new claim on one is not even sent a confirmation."""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    monkeypatch.setenv("SITE_URL", "https://x.test")
    stripe["sessions"] = [_pass_session()]
    first = _seat(received_at=_at(5))
    _confirmed_seats(monkeypatch, first)
    assert _run(tmp_path) == 0
    assert len(_seat_rows(tmp_path)) == 1
    customer = {"id": "cus_commish01", "email": "commish@example.com"}
    stripe["subscriptions"] = [
        {"id": PASS_SUB, "status": "active", "customer": customer,
         "latest_invoice": {"charge": {"refunded": True}}},
        {"id": "sub_season001", "status": "active", "customer": customer}]
    newcomer = _seat(email="new@example.com", received_at=_at(1))
    _confirmed_seats(monkeypatch, first, newcomer)
    capsys.readouterr()
    assert _run(tmp_path) == 0
    assert _seat_rows(tmp_path) == [], "a seat outlived its refunded pass"
    out = capsys.readouterr()
    assert "1 on a pass not active now" in out.out
    assert "not active" in out.err
    assert not [m for m in sends if m.to == "new@example.com"], \
        "a claim on a refunded pass was mailed"


def test_the_intake_refuses_rather_than_guess_which_passes_are_active(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Which passes are active is the whole seat question. When Stripe cannot
    answer it, the run refuses to write: serving seats on a refunded pass and
    dropping every seat on a paid one are both worse than one late hour."""
    import run.subscriptions as subscriptions
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    stripe["sessions"] = [_pass_session()]
    _confirmed_seats(monkeypatch, _seat())

    def _down(url, key):
        raise subscriptions.SubscriptionError("HTTP 500")
    monkeypatch.setattr(subscriptions, "_stripe_get", _down)
    assert _run(tmp_path) == 1
    assert "Refusing to write" in capsys.readouterr().err
    assert not (tmp_path / intake.REGISTRY_NAME).exists()


# --------------------------------------------------------------------- #
# OPS-R6 — a seat's identity is ours, not the Worker's
# --------------------------------------------------------------------- #

def test_a_seats_identity_survives_its_worker_rows_expiring(
        tmp_path, stripe, directory, monkeypatch) -> None:
    """Reproduced (OPS-R6): the seat's slug and first-claim time were
    re-derived every run from Worker rows that expire after ~400 days, so
    when the first claim expired the same seat got a new slug, a second
    "Your seat is in" and a second copy of the week's report. Confirmed
    seats now live in the intake's own seat log: with every Worker row gone,
    the seat, its slug and its one welcome stand."""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    stripe["sessions"] = [_pass_session()]
    first = _seat(received_at=_at(30))
    newer = _seat(ref=NEWER_SEAT_REF, received_at=_at(10))
    _confirmed_seats(monkeypatch, first, newer)
    assert _run(tmp_path) == 0
    [before] = _seat_rows(tmp_path)
    _seats(monkeypatch)                                  # the Worker's rows expired
    assert _run(tmp_path) == 0
    [after] = _seat_rows(tmp_path)
    assert (after.slug, after.ref) == (before.slug, before.ref) == \
        (_origin(first), NEWER_SEAT_REF)
    welcomes = [m for m in sends if m.key.startswith("welcome-") and m.to == after.email]
    assert len(welcomes) == 1
    assert len(intake.load_seat_log(tmp_path / intake.SEAT_LOG_NAME)) == 2


# --------------------------------------------------------------------- #
# LP2-D3 — a seat is claimed again each season
# --------------------------------------------------------------------- #

def test_last_seasons_claims_and_seats_are_retired_at_the_season_roll() -> None:
    """Reproduced (LP2-D3): a claim from last October was honoured at the
    next Week 1 and built "Week 1 — your opening lineup" from last season's
    roster, while the seat's own Week 18 report had said "claim your seat
    again next season". Claims and logged seats from before this season's
    start are retired; a claim from the offseason is this season's."""
    start = NOW - timedelta(days=20)
    last = _claim(hours=24 * 30)
    swept = intake.sweep_seats([last], PASSES, None, SECRET,
                               confirm_codes=[_code(last)], season_from=start)
    assert swept.rows == [] and swept.retired == 1 and swept.awaiting == []
    confirmed = intake.sweep_seats([last], PASSES, None, SECRET,
                                   confirm_codes=[{"code": _code(last),
                                                   "received_at": _at(24 * 29)}]).confirmed
    assert confirmed
    rolled = intake.sweep_seats([], PASSES, None, SECRET, log=confirmed,
                                season_from=start)
    assert rolled.rows == [] and rolled.retired == 1
    fresh = _claim(hours=24 * 5)
    assert len(intake.sweep_seats([fresh], PASSES, None, SECRET,
                                  confirm_codes=[_code(fresh)],
                                  season_from=start).rows) == 1


def test_a_season_starts_the_day_after_the_last_ones_final_game() -> None:
    """The cut is read from the schedule (the previous season's last REG
    game), never typed: a claim in August belongs to the season ahead."""
    from run.solo import CACHE_DIR, season_ends
    try:
        end = season_ends(CACHE_DIR, live=False).get("2025")
    except Exception as exc:                            # pragma: no cover
        pytest.skip(f"schedule not cached: {exc}")
    if not end:                                         # pragma: no cover
        pytest.skip("2025 schedule not cached")
    start = intake._season_from(CACHE_DIR, "2026")
    assert start == datetime.fromisoformat(end).replace(tzinfo=timezone.utc) \
        + timedelta(days=1)
    assert datetime(2026, 8, 20, tzinfo=timezone.utc) >= start


# --------------------------------------------------------------------- #
# OPS-R7 — as many seats as the league has teams
# --------------------------------------------------------------------- #

def test_a_pass_carries_as_many_seats_as_its_league_has_teams() -> None:
    """Reproduced (OPS-R7): twenty addresses claiming through one 12-team
    pass's link were all honoured — twenty-one reports a week on one $99
    purchase. A pass carries at most as many seats as its league has teams
    (every other team plus a co-manager), the first confirmed first; a
    confirmed seat past the cap and any new claim on a full pass are told
    the league's seats are taken (never mailed a confirmation), while a seat
    holder's roster change still is."""
    small = [intake.PassInfo("commish@example.com", PASS_SUB, 3, "cus_commish01")]
    assert intake.PassInfo("p@example.com", PASS_SUB, 12).seat_cap == 12
    claims = [_claim(email=f"m{i}@example.com", hours=40 - i) for i in range(5)]
    swept = intake.sweep_seats(claims, small, None, SECRET,
                               confirm_codes=[_code(c) for c in claims])
    assert [r["email"] for r in swept.rows] == ["m0@example.com", "m1@example.com",
                                                "m2@example.com"]
    assert swept.overflow == 2
    assert {r["email"] for r in swept.full} == {"m3@example.com", "m4@example.com"}
    log = swept.confirmed
    late = _claim(email="late@example.com", hours=1)
    change = _claim(email="m0@example.com", ref=NEWER_SEAT_REF, hours=1)
    again = intake.sweep_seats([*claims, late, change], small, None, SECRET, log=log)
    assert [r for r in again.full if r["email"] == "late@example.com"]
    assert [p.email for p in again.awaiting] == ["m0@example.com"]
    assert again.awaiting[0].change


def test_a_served_seat_is_never_displaced_by_an_older_claim_confirmed_later() -> None:
    """Reproduced in the end-to-end run against the real Worker: the cap
    ordered seats by when they were CLAIMED, so a claim made early and
    confirmed days later took the place of a seat already welcomed and
    served — which then dropped mid-season with a "no seats left" note. A
    pass's seats are ordered by when each was CONFIRMED (the moment it
    existed); a seat skipped for one run never lets one past the cap in."""
    small = [intake.PassInfo("commish@example.com", PASS_SUB, 2, "cus_commish01")]
    early = _claim(email="early@example.com", hours=50)     # claimed first ...
    a = _claim(email="a@example.com", hours=40)
    b = _claim(email="b@example.com", hours=30)
    first = intake.sweep_seats([early, a, b], small, None, SECRET,
                               confirm_codes=[_code(a), _code(b)],
                               now=NOW - timedelta(hours=20))
    assert sorted(r["email"] for r in first.rows) == ["a@example.com", "b@example.com"]
    later = intake.sweep_seats([early, a, b], small, None, SECRET,   # ... confirmed last
                               confirm_codes=[_code(early)], log=first.confirmed)
    assert sorted(r["email"] for r in later.rows) == ["a@example.com", "b@example.com"], \
        "a seat already served was displaced by an older claim confirmed later"
    assert [r["email"] for r in later.full] == ["early@example.com"]
    # A served seat this run cannot build (its player left the directory)
    # still holds its place: nobody past the cap is let in for one run.
    from run.refs import decode_roster
    seat_players = set(decode_roster(SEAT_REF).player_ids)
    gone = sorted(seat_players)[0]
    held = intake.sweep_seats([early, a, b], small, (set(PLAYERS) | seat_players) - {gone},
                              SECRET, log=[*first.confirmed, *later.confirmed])
    assert held.rows == [] and [r["email"] for r in held.full] == ["early@example.com"]


def test_the_full_note_is_held_to_the_seat_notes_rules() -> None:
    """One note per refused claim, capped per address per day like the
    unmatched note (the form is public), and never for a stale claim."""
    row = {"email": "x@example.com", "ref": SEAT_REF, "pass_id": PASS_SUB}
    burst = [dict(row, received_at=_at(1 + i / 60)) for i in range(4)]
    assert len(intake.full_due(burst, NOW)) == intake.UNMATCHED_PER_DAY
    assert intake.full_due([dict(row, received_at=_at(24 * 30))], NOW) == []
    assert len({intake.full_key(r) for r in burst}) == 4
    assert all("@" not in intake.full_key(r) for r in burst)


# --------------------------------------------------------------------- #
# OPS-R9 — a matched claim is never also told it matched nothing
# --------------------------------------------------------------------- #

def test_an_address_whose_claim_matched_is_never_told_its_typo_matched_nothing() -> None:
    """Reproduced (OPS-R9): a claim typed with the payer's address misspelt,
    then a claim through the seat link an hour later, and one intake mailed
    the same address "Your seat is in" AND "Your League Pass seat isn't set
    up yet … no reports are coming". An address with a matched claim in the
    sweep is dropped from the unmatched notes."""
    typo = _claim(email="seat@example.com", covered_by="paye@example.com", hours=8)
    token = seat_token("commish@example.com", SECRET, PASS_SUB)
    good = _claim(email="seat@example.com", covered_by="", pass_token=token, hours=7)
    swept = intake.sweep_seats([typo, good], PASSES, None, SECRET,
                               confirm_codes=[_code(good)])
    assert len(swept.rows) == 1 and swept.unmatched == []
    alone = intake.sweep_seats([typo], PASSES, None, SECRET)
    assert alone.unmatched, "a claim that matched nothing stopped being told"


# --------------------------------------------------------------------- #
# OPS-R10 — rotating the secret must not orphan seats
# --------------------------------------------------------------------- #

def test_a_rotated_secret_orphans_no_seat_and_a_dead_link_is_loud() -> None:
    """Reproduced (OPS-R10): seat links are HMACs under UPDATE_SECRET, so
    rotating it (or a run without it) read every link claim as "matches no
    League Pass", dropped every seat and exited 0 — and mailed recent
    claimers "isn't set up yet". Confirmed seats now need no secret at all
    (the seat log holds the pass they were confirmed on); an old link is
    matched while UPDATE_SECRET_PREVIOUS names the old value; and link claims
    that match nothing at all are a loud failure with nobody told."""
    from run.updates import signing_secrets
    token = seat_token("commish@example.com", "old-secret", PASS_SUB)
    claim = _claim(covered_by="", pass_token=token, hours=3)
    swept = intake.sweep_seats([claim], PASSES, None, "old-secret",
                               confirm_codes=[_code(claim, "old-secret")])
    assert len(swept.rows) == 1
    kept = intake.sweep_seats([claim], PASSES, None, (), log=swept.confirmed)
    assert len(kept.rows) == 1, "a confirmed seat needed the secret again"
    rotated = intake.sweep_seats([dict(claim, received_at=_at(2))], PASSES, None,
                                 signing_secrets("new-secret", "old-secret"))
    assert not rotated.links_dead and rotated.awaiting, \
        "an old link was not matched under UPDATE_SECRET_PREVIOUS"
    dead = intake.sweep_seats([claim], PASSES, None, "new-secret")
    assert dead.links_dead and dead.unmatched == []
    assert any("SEAT LINKS MATCH NO PASS" in p for p in dead.problems)
    assert signing_secrets("a", " b, a ,c") == ["a", "b", "c"]


def test_seat_links_matching_nothing_fail_the_intake(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """The loud half, end to end: the intake still writes the registry (the
    paying subscribers' Tuesday is not held hostage) and exits 1, so the
    daily cron files its issue."""
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    monkeypatch.setenv("UPDATE_SECRET", "rotated-secret")
    stripe["sessions"] = [_pass_session()]
    token = seat_token("commish@example.com", SECRET, PASS_SUB)
    _seats(monkeypatch, {"email": "member@example.com", "ref": SEAT_REF,
                         "pass_token": token, "received_at": _at(2)})
    assert _run(tmp_path) == 1
    assert "SEAT LINKS MATCH NO PASS" in capsys.readouterr().err
    assert (tmp_path / intake.REGISTRY_NAME).is_file()


# --------------------------------------------------------------------- #
# LP2-D4 — two passes on one address are two leagues
# --------------------------------------------------------------------- #

def test_two_passes_bought_with_one_address_are_two_leagues(monkeypatch) -> None:
    """Reproduced (LP2-D4): the seat token hashed only the payer's address,
    so one buyer's two passes printed the same link; a leaguemate in both
    leagues lost one seat to a "roster change", and each pass counted the
    other league's seats against its own size. The token binds the pass, a
    seat is one per (address, pass), and seats are counted per pass."""
    import run.tuesday as tuesday
    from run.rosters import RosterSubscriber
    second = "sub_commish02"
    passes = [*PASSES, intake.PassInfo("commish@example.com", second, 10, "cus_commish01")]
    one, two = (seat_token("commish@example.com", SECRET, p.pass_id) for p in passes)
    assert len({one, two, seat_token("commish@example.com", SECRET)}) == 3
    in_one = _claim(email="mate@example.com", covered_by="", pass_token=one, hours=3)
    in_two = _claim(email="mate@example.com", covered_by="", pass_token=two,
                    ref=NEWER_SEAT_REF, hours=2)
    swept = intake.sweep_seats([in_one, in_two], passes, None, SECRET,
                               confirm_codes=[_code(in_one),
                                              _code(in_two, pass_id=second)])
    assert sorted((r["pass_id"], r["ref"]) for r in swept.rows) == sorted(
        [(PASS_SUB, SEAT_REF), (second, NEWER_SEAT_REF)])
    assert intake.seat_counts(swept.rows) == {PASS_SUB: 1, second: 1}
    payer = RosterSubscriber(email="commish@example.com", ref=PASS_REF,
                             player_ids=tuple(PLAYERS), slots=tuple(SLOTS),
                             scoring="ppr", billing="pass", pass_id=second,
                             league_size=10)
    meta = tuesday.subscriber_meta(payer, {PASS_SUB: 4, second: 1})
    assert meta["seats_claimed"] == {"claimed": 1, "size": 10}
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    assert f"pass={two}" in tuesday.league_seat_link(payer, {second: payer})


# --------------------------------------------------------------------- #
# LP2-D1 — one roster bought twice is one report
# --------------------------------------------------------------------- #

def test_one_roster_bought_twice_by_one_address_is_one_report_and_the_welcome_says_so(
        tmp_path, stripe, directory, monkeypatch, capsys) -> None:
    """Reproduced (LP2-D1): a commissioner with the $39 season pass who then
    bought the $99 League Pass with the same roster got two identical reports
    every Tuesday, both renewing, and nothing anywhere said so. Now one row
    (the pass, under the season pass's slug so its history continues), the
    operator log flags it, and the newer purchase's welcome says plainly that
    the season pass, if still active, keeps billing until they cancel it from
    their billing page — and promises no "first report today", because their
    reports simply carry on. Nothing is cancelled or refunded on anyone's
    behalf."""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    # D10: a League Pass on file without UPDATE_SECRET exits non-zero.
    monkeypatch.setenv("UPDATE_SECRET", "test-secret-do-not-ship")
    stripe["sessions"] = [
        _session(REF, sid="cs_own", email="commish@example.com",
                 customer="cus_commish01", created=900),
        _pass_session(created=2000)]
    assert _run(tmp_path) == 0
    [row] = load_rosters(tmp_path / intake.REGISTRY_NAME)
    assert row.is_pass_payer and row.pass_id == PASS_SUB
    assert row.slug == slug_of(REF), "the older subscription's history restarted"
    assert "one address holds 2 subscriptions for one roster" in capsys.readouterr().out
    welcomes = {m.key: m for m in sends if m.key.startswith("welcome-")}
    assert len(welcomes) == 2, "a purchase went unacknowledged"
    [upgrade] = [m for m in welcomes.values() if "$99" in m.text]
    assert "also bought the season pass for this same roster" in upgrade.text
    assert "If that one is still active, it keeps billing until you cancel it" \
        in upgrade.text
    assert "Today:" not in upgrade.text and "first report" not in upgrade.subject, \
        "an upgrade was promised a first report the intake does not send"
    [first] = [m for m in welcomes.values() if m is not upgrade]
    assert "Today:" in first.text and "one report" not in first.text
    assert all("/v1/subscriptions" not in url for url, _form in stripe["posts"]), \
        "something was cancelled on the subscriber's behalf"
    different = encode_roster("season", "half_ppr", list(SLOTS), PLAYERS)
    merged = intake.merge_same_roster([
        intake.RosterSignup("a@example.com", REF, "season", "1"),
        intake.RosterSignup("a@example.com", different, "season", "2")])
    assert len(merged.signups) == 2 and not merged.groups, \
        "two different setups were merged into one report"


def test_two_league_passes_are_never_merged_into_one_row() -> None:
    """Two League Passes on one roster are two leagues' seat links and seat
    counts (LP2-D4): merged, one league's seats would carry the other's link.
    Only a season or monthly purchase folds into a pass."""
    one = intake.RosterSignup("a@example.com", PASS_REF, "league_pass", "1",
                              subscription_id="sub_passone01")
    two = intake.RosterSignup("a@example.com", PASS_REF, "league_pass", "2",
                              subscription_id="sub_passtwo02")
    own = intake.RosterSignup("a@example.com", REF, "season", "3")
    merged = intake.merge_same_roster([one, two, own])
    assert sorted(s.subscription_id or "" for s in merged.signups) == \
        ["sub_passone01", "sub_passtwo02"], "two passes became one row"
    assert merged.duplicates == {own.key: "league_pass"}


def test_the_duplicate_line_names_the_other_subscription_and_cancels_nothing() -> None:
    """The purchase log keeps subscriptions cancelled or refunded long ago,
    so the OLDER one is "if it is still active" — "it keeps billing" was a
    false statement about money whenever they had already cancelled it. A
    second purchase of the same plan (a double purchase) is said too."""
    from render.welcome import duplicate_line
    assert duplicate_line("league_pass", None) is None
    assert duplicate_line("league_pass", "pass") is None
    again = duplicate_line("season", "season")
    assert "an earlier season pass" in again and "If that one is still active" in again
    upgrade = duplicate_line("league_pass", "monthly")
    assert "monthly plan" in upgrade and "billing page" in upgrade
    assert "If that one is still active" in upgrade
    later = duplicate_line("season", "league_pass")
    assert "League Pass already covers" in later and "This season pass bills" in later
    for line in (upgrade, later, again, duplicate_line("monthly", "season")):
        for word in ("refund", "we cancel", "cancelled", "calibrated", "tested",
                     "proven", "accurate", " file"):
            assert word not in line.lower(), (word, line)


# --------------------------------------------------------------------- #
# COPY:F3 — every seat note says who sent it
# --------------------------------------------------------------------- #

def test_every_seat_note_says_who_sent_it_and_renders_everywhere(monkeypatch) -> None:
    """Reproduced (COPY:F3): the failed-claim note — the one email that
    reaches an address a stranger can type, linking a sales page — carried
    no sender name, postal address or contact while every other email did.
    All three seat notes now carry the sender block, and the two new ones
    are held to every email client's rules."""
    import re

    from render.seat_claim import confirm_email, full_email, unmatched_email
    from test_email_safety import FORBIDDEN
    monkeypatch.setenv("SENDER_POSTAL_ADDRESS", "PO Box 123, Toronto ON M5V 1A1")
    line = "Beat Your League · PO Box 123, Toronto ON M5V 1A1 · hello@beatyourleague.com"
    notes = {"unmatched": unmatched_email("https://x.test"),
             "full": full_email("https://x.test"),
             "confirm": confirm_email("https://x.test/join/confirm.html?c=" + "a" * 24
                                      + "&k=seat", ["A", "B"]),
             "change": confirm_email("https://x.test/join/confirm.html?c=" + "a" * 24
                                     + "&k=seat", ["A"], change=True)}
    for name, (subject, html, text) in notes.items():
        assert line in html and line in text, name
        assert not [p for p in FORBIDDEN if re.search(p, html, re.I)], name
        assert not re.findall(r'<table(?![^>]*role="presentation")', html), name
        assert all(h.startswith("https://") for h in re.findall(r'href="([^"]*)"', html))
        assert '<meta name="color-scheme" content="light only">' in html, name
        assert "&#847;&zwnj;&nbsp;" in html and 'lang="en"' in html, name
        for words in (subject, text):
            assert " file" not in words.lower() and "odds" not in words.lower(), name
    assert "7 days" in notes["confirm"][2] and "nothing is set up" in notes["confirm"][2]
