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
from test_intake_sync import (MONTHLY_LINK, PASS_LINK, PASS_REF, PLAYERS, REF,
                              SEASON_LINK, SEAT_REF, SLOTS, _capture_sends,
                              _pass_session, _registry, _run, _seat, _seats,
                              _session, directory, stripe)  # noqa: F401 — fixtures

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
    for words in (subject, text):
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
    pass): the newest claim's roster stands, under the slug it was FIRST
    claimed with, so its send keys, plans and link never move, and it is
    welcomed once."""
    sends = _capture_sends(monkeypatch, tmp_path)
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", LINKS)
    stripe["sessions"] = [_pass_session()]
    first = _seat(received_at=_at(48))
    _seats(monkeypatch, first)
    assert _run(tmp_path) == 0
    _seats(monkeypatch, first, _seat(ref=NEWER_SEAT_REF, received_at=_at(2)))
    assert _run(tmp_path) == 0
    seats = [s for s in load_rosters(tmp_path / intake.REGISTRY_NAME) if s.is_league_seat]
    assert len(seats) == 1, "a re-claim became a second seat"
    assert "1 re-claimed with a new roster" in capsys.readouterr().out
    [seat] = seats
    assert seat.ref == NEWER_SEAT_REF and seat.slug == slug_of(SEAT_REF)
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
    _seats(monkeypatch, _seat(received_at=_at(3)))
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
    assert payer_meta["seats_claimed"] == {"claimed": 3, "size": 10}
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
            "pass_token": seat_token("commish@example.com", SECRET), "received_at": _at(1)}
    forged = {"email": "other@example.com", "ref": SEAT_REF,
              "pass_token": seat_token("nobody@example.com", SECRET), "received_at": _at(1)}
    _seats(monkeypatch, good, forged)
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
                         seen_at="1791500000")
    season = RosterSignup(email="fan@example.com", ref=REF, plan="season", seen_at="1")
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    assert pass_seat_link(payer).startswith("https://x.test/join/?pass=")
    assert pass_seat_link(season) is None
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
    token = seat_token("commish@example.com", SECRET)
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
    _seats(monkeypatch, _seat(received_at=_at(1)),
           _seat(email="stray@example.com", covered_by="nobody@example.com",
                 received_at=_at(1)))
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
    assert plans["pass"]["seats_claimed"] == {"claimed": 2, "size": 12}
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
