"""Promise fixes in the engine and its runners (Oct 18 2026).

Each test names the confirmed mismatch it closes (EMAILS-/INFO-/JOIN-/
LANDING- ids) or the binding product decision (D8, D10-D13). The
reproductions are in the confirmed lists; these pin the fixed behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import render.report as rr
import run.intake as intake
import run.saturday as saturday
import run.trial as trial
import run.tuesday as tuesday
import run.updates as updates
from engine.availability import Status
from engine.history import PlayerIndex, PlayerInfo
from engine.own_record import (EMPTY_NOTE, LAST_NOTE, NEXT_STAMP, NO_ODDS_NOTE,
                               SAMPLE_NOTE, call_line, own_record)
from engine.scoring import preset
from engine.solo_report import (STALE_ALTERNATIVE_GATE, hold_stale_alternatives,
                                hold_unconfirmed, pivots_note)
from engine.week_report import SlotPick
from run.refs import encode_roster
from run.rosters import RosterSubscriber
from test_intake_seats import (NEWER_SEAT_REF, PASSES, SECRET, _at, _claim,
                               _code)
from test_intake_sync import PASS_SUB, PLAYERS, SEAT_REF, SLOTS


# --------------------------------------------------------------------- #
# D11 — odds whose bench option ends up starting are withheld
# --------------------------------------------------------------------- #

def _index(**positions: str) -> PlayerIndex:
    index = PlayerIndex.__new__(PlayerIndex)
    index._players = {pid: PlayerInfo(pid, pid.upper(), frozenset({pos}))
                      for pid, pos in positions.items()}
    return index


class _Model:
    def __init__(self, means):
        self.means = means

    def project(self, pid, week):
        return SimpleNamespace(mean=self.means[pid]) if pid in self.means else None


class _Avail:
    def __init__(self, out=()):
        self.out = set(out)

    def classify(self, pid):
        return SimpleNamespace(status=Status.OUT if pid in self.out else Status.ACTIVE)


def _pick(slot, index, pid, mean, conf, alt, alt_mean, gate=None):
    return SlotPick(slot, index, pid, SimpleNamespace(mean=mean), None, conf, gate,
                    alt, SimpleNamespace(mean=alt_mean) if alt else None, [])


def test_odds_against_a_bench_player_who_ends_up_starting_are_withheld() -> None:
    """EMAILS-3/4/13/19/20: a later FLEX swap seated the WR row's comparison
    (Deebo Samuel 78% "over J. Michael Sturdivant on your bench" while
    Sturdivant started at FLEX). The odds go, never recomputed, and the row
    names the real best bench player so "on your bench" stays true."""
    players = _index(a="WR", c="WR", h="WR", x="RB")
    model = _Model({"a": 10.0, "c": 6.0, "h": 2.5, "x": 7.0})
    picks = [_pick("WR", 0, "a", 10.0, 0.78, "c", 6.0),
             _pick("FLEX", 1, "c", 6.0, 0.55, "x", 7.0)]
    out = hold_stale_alternatives(picks, ["a", "c", "h", "x"], model, 6, _Avail(),
                                  players)
    wr, flex = out
    assert wr.confidence is None and wr.confidence_gate.startswith(STALE_ALTERNATIVE_GATE)
    assert "C starts at FLEX" in wr.confidence_gate
    assert wr.alternative_id == "h", "the row still names a starter as its bench"
    assert flex.confidence == 0.55, "a row whose comparison is on the bench lost its odds"
    assert rr.row_label({"confidence_gate": wr.confidence_gate}) == "held this week"
    assert "flex swap" in rr.gate_phrase(wr.confidence_gate)


def test_a_player_the_swap_moved_to_the_bench_outranking_the_comparison_withholds() -> None:
    """The displaced FLEX starter is now the best bench RB, above the one the
    RB row's odds were figured against."""
    players = _index(r1="RB", r3="RB", x="RB", c="WR")
    model = _Model({"r1": 12.0, "r3": 5.0, "x": 7.0, "c": 6.0})
    picks = [_pick("RB", 0, "r1", 12.0, 0.7, "r3", 5.0),
             _pick("FLEX", 1, "c", 6.0, 0.55, "x", 7.0)]
    rb, _ = hold_stale_alternatives(picks, ["r1", "r3", "x", "c"], model, 6,
                                    _Avail(), players)
    assert rb.confidence is None and rb.alternative_id == "x"


def test_the_withholding_only_ever_removes() -> None:
    """Nothing stale: every number and name is untouched. A no-odds row with
    a structural reason keeps it; only its stale name moves."""
    players = _index(a="WR", c="WR", d="DEF")
    model = _Model({"a": 9.0, "c": 4.0})
    fine = [_pick("WR", 0, "a", 9.0, 0.7, "c", 4.0)]
    assert hold_stale_alternatives(fine, ["a", "c"], model, 6, _Avail(),
                                   players)[0].confidence == 0.7
    structural = [_pick("WR", 0, "a", 9.0, None, "c", 4.0,
                        gate="odds once this lineup shape is graded"),
                  _pick("FLEX", 1, "c", 4.0, None, None, None)]
    row = hold_stale_alternatives(structural, ["a", "c"], model, 6, _Avail(),
                                  players)[0]
    assert row.confidence_gate == "odds once this lineup shape is graded"
    assert row.alternative_id is None


def test_a_practice_squad_pair_short_of_games_names_the_practice_squad() -> None:
    """EMAILS-21: "odds once Devin Neal has 3 games" while Neal was on the
    practice squad — three games would not bring odds."""
    players = _index(j="RB", n="RB")
    pick = _pick("RB", 0, "j", 9.1, None, "n", 4.0,
                 gate="not enough games on record yet (5 and 0; we want at least 3)")
    [held] = hold_unconfirmed([pick], {"n": "on the practice squad"}, players)
    assert held.confidence_gate.startswith("not confirmed to play (N:")
    assert rr.row_label({"confidence_gate": held.confidence_gate}) == "N on practice squad"


# --------------------------------------------------------------------- #
# EMAILS-33 — a starter ruled out last week is named, not denied
# --------------------------------------------------------------------- #

def test_the_quiet_pivots_note_names_a_starter_ruled_out_last_week() -> None:
    players = _index(lamar="QB")
    out = SimpleNamespace(status=Status.OUT, reason="designated Out (ankle)")
    pick = SlotPick("QB", 0, "lamar", SimpleNamespace(mean=17.0), out, None, None,
                    None, None, [])
    avail = SimpleNamespace(has_snapshot=True)
    note = pivots_note([], {}, avail, [pick], players)
    assert "LAMAR was out on it" in note
    assert "no bench player's news would change" not in note


# --------------------------------------------------------------------- #
# D12 — the Results section is this report's own
# --------------------------------------------------------------------- #

def test_the_results_section_promises_only_what_follows() -> None:
    """EMAILS-35/36, INFO-109: "every call shows up … Results · from next week"
    in a week with no odds, on the season's last report and on the samples."""
    rule = preset("ppr")
    assert own_record([], {}, rule, 2, calls_now=0) == {
        "record": None, "note": NO_ODDS_NOTE, "stamp": None}
    assert own_record([], {}, rule, 18, calls_now=4, last_report=True) == {
        "record": None, "note": LAST_NOTE, "stamp": None}
    assert own_record([], {}, rule, 6, calls_now=4)["stamp"] == NEXT_STAMP
    assert "from next week" not in rr.section_receipts(
        {"record": None, "note": NO_ODDS_NOTE, "stamp": None})
    assert "from next week" not in rr.section_receipts(
        {"record": None, "note": SAMPLE_NOTE, "stamp": None})
    assert "from next week" in rr.section_receipts(
        {"record": None, "note": EMPTY_NOTE, "stamp": NEXT_STAMP})


def test_a_void_and_a_tie_are_listed_never_dropped() -> None:
    """EMAILS-37, INFO-20/25, LANDING-96: a 0.0-0.0 pair and an exact tie
    vanished, so "5 of 9" undercounted the calls the subscriber was sent."""
    rule = preset("ppr")
    row = lambda rec: {"receptions": 0, "receiving_yards": rec * 10}  # noqa: E731
    plans = [{"week": 5, "calls": [
        {"slot": "WR", "pick": "a", "over": "b", "pick_name": "A", "over_name": "B",
         "confidence": 0.6},
        {"slot": "RB", "pick": "c", "over": "d", "pick_name": "C", "over_name": "D",
         "confidence": 0.53},
        {"slot": "TE", "pick": "e", "over": "f", "pick_name": "E", "over_name": "F",
         "confidence": 0.55}]}]
    weekly = {5: {"a": row(9), "b": row(2), "e": row(4), "f": row(4)}}
    got = own_record(plans, weekly, rule, 6)
    assert len(got["last_week_calls"]) == 3
    assert got["record"]["graded"] == 1
    assert "1 of 1 came in, plus 2 with no result" in got["note"]
    lines = [call_line(c) for c in got["last_week_calls"]]
    assert "C over D at RB · 53% — 0.0 to 0.0, no result" in lines
    assert "E over F at TE · 55% — 4.0 to 4.0, no result" in lines


# --------------------------------------------------------------------- #
# D10 — seats: counted the way the cap is enforced
# --------------------------------------------------------------------- #

def _sub(**over) -> RosterSubscriber:
    ref = encode_roster("season", "ppr", list(SLOTS), list(PLAYERS))
    base = dict(email="payer@example.com", ref=ref, player_ids=tuple(PLAYERS),
                slots=tuple(SLOTS), scoring="ppr", league_size=12)
    base.update(over)
    return RosterSubscriber(**base)


def test_the_payer_counts_seats_only_against_the_cap(monkeypatch) -> None:
    """EMAILS-50: the count added the payer and compared with the league size,
    so one seat still open read "12 of 12" with the link gone."""
    payer = _sub(billing="pass", pass_id=PASS_SUB)
    meta = tuesday.subscriber_meta(payer, {PASS_SUB: 11}, "https://x.test/s", 12)
    assert meta["seats_claimed"] == {"claimed": 11, "size": 12}
    assert "seats_full" not in meta
    full = tuesday.subscriber_meta(payer, {PASS_SUB: 12}, "https://x.test/s", 12)
    assert full["seats_full"] is True
    seat = _sub(email="m@example.com", plan="league_pass",
                covered_by="payer@example.com", pass_id=PASS_SUB)
    assert tuesday.subscriber_meta(seat, {PASS_SUB: 12}, "https://x.test/s",
                                   12)["seats_full"] is True
    assert tuesday.pass_seat_cap(seat, {PASS_SUB: payer}) == 12
    assert rr.seats_text({**full, "plan": "pass"}) == ("League Pass: Every seat is claimed."
                                                        + rr.SEAT_RESET_LINE)


def test_no_seat_is_offered_without_a_signed_link_or_once_the_pass_is_full(
        monkeypatch) -> None:
    """EMAILS-47/48: the generic ?pass=1 line rendered only without
    UPDATE_SECRET, when no claim can be confirmed; and a full pass still
    told leaguemates their seat was covered."""
    monkeypatch.setenv("SITE_URL", "https://x.test")
    for meta in ({"plan": "league_pass"},
                 {"plan": "league_pass", "seat_link": "https://x.test/s",
                  "seats_full": True}):
        words = rr._forward_text(meta)
        assert "covers your seat" not in words and "pass=1" not in words
        assert "Every manager gets their own report" in words
    assert "covers your seat" in rr._forward_text(
        {"plan": "league_pass", "seat_link": "https://x.test/s"})


def test_a_seat_holder_on_the_stop_list_frees_the_seat() -> None:
    """EMAILS-144, D10: a manager who left and replied "stop" held a seat for
    the season, and nobody could free it."""
    one = [intake.PassInfo("commish@example.com", PASS_SUB, 1, "cus_commish01")]
    first = _claim(email="gone@example.com", hours=40)
    seated = intake.sweep_seats([first], one, None, SECRET,
                                confirm_codes=[_code(first)])
    log = seated.confirmed
    newcomer = _claim(email="new@example.com", ref=NEWER_SEAT_REF, hours=2)
    kept = intake.sweep_seats([first, newcomer], one, None, SECRET, log=log)
    assert [r["email"] for r in kept.full] == ["new@example.com"]
    freed = intake.sweep_seats([first, newcomer], one, None, SECRET, log=log,
                               stopped=lambda e: e == "gone@example.com")
    assert freed.released == 1 and freed.rows == [] and not freed.full
    assert [p.email for p in freed.awaiting] == ["new@example.com"]


def test_a_claim_on_a_pass_that_is_not_active_is_told_so() -> None:
    """JOIN-103/123: a claim naming a refunded or lapsed pass was only a log
    line, while the page promised an email."""
    lapsed = [intake.PassInfo("commish@example.com", PASS_SUB, 12, "cus_commish01",
                              entitled=False)]
    claim = _claim(hours=8)
    swept = intake.sweep_seats([claim], lapsed, None, SECRET)
    [row] = swept.unmatched
    assert row["inactive"] is True and row["email"] == "m@example.com"
    from render.seat_claim import inactive_email
    subject, _html, text = inactive_email("https://x.test")
    assert "isn't set up" in subject and "isn't active right now" in text


def test_co_managers_with_one_roster_get_their_own_slug() -> None:
    """EMAILS-146: identical rosters on one pass shared a slug, so the second
    co-manager's reports were skipped as already sent."""
    a, b = _claim(email="a@example.com", hours=30), _claim(email="b@example.com", hours=20)
    swept = intake.sweep_seats([a, b], PASSES, None, SECRET,
                               confirm_codes=[_code(a), _code(b)])
    origins = {r["email"]: r["origin"] for r in swept.rows}
    assert len(set(origins.values())) == 2, origins
    assert updates.slug_of(SEAT_REF) not in origins.values()


def test_a_pass_on_file_without_the_secret_is_not_a_green_tuesday(
        tmp_path, monkeypatch) -> None:
    """D10: every pass report goes out without a seat link, so no leaguemate
    can claim a seat — the run sends, then exits non-zero."""
    payer = _sub(billing="pass", pass_id=PASS_SUB)
    monkeypatch.delenv("UPDATE_SECRET", raising=False)
    monkeypatch.setattr(tuesday, "not_configured", lambda *_: False)
    monkeypatch.setattr(tuesday, "load_rosters", lambda *_: [payer])
    monkeypatch.setattr(tuesday, "paid_subscribers", lambda subs, *_: subs)
    monkeypatch.setattr(tuesday, "_week_one_due", lambda args: True)
    monkeypatch.setattr(tuesday, "load_week_data",
                        lambda *a, **k: SimpleNamespace(season="2026", week=7,
                                                        attribution=""))
    monkeypatch.setattr(tuesday, "week_has_kicked_off", lambda *a, **k: False)
    monkeypatch.setattr(tuesday, "_mails_for_real", lambda args: False)
    monkeypatch.setattr(tuesday, "run_subscriber",
                        lambda s, *a, **k: tuesday.RunResult(s, ok=True, detail=""))
    assert tuesday.main(["--no-send", "--out", str(tmp_path)]) == 1
    monkeypatch.setenv("UPDATE_SECRET", "s")
    assert tuesday.main(["--no-send", "--out", str(tmp_path)]) == 0


# --------------------------------------------------------------------- #
# D8 / EMAILS-7 — no report about a week that isn't due or is underway
# --------------------------------------------------------------------- #

def test_a_derived_week_one_is_not_built_before_it_is_due(monkeypatch, capsys) -> None:
    monkeypatch.setattr(tuesday, "not_configured", lambda *_: False)
    monkeypatch.setattr(tuesday, "load_rosters", lambda *_: [_sub()])
    monkeypatch.setattr(tuesday, "paid_subscribers", lambda subs, *_: subs)
    monkeypatch.setattr(tuesday, "current_season", lambda *a, **k: "2027")
    monkeypatch.setattr(tuesday, "current_week", lambda *a, **k: 1)
    monkeypatch.setattr(tuesday, "week_one_due", lambda *a, **k: False)

    def never(*a, **k):
        raise AssertionError("built a Week 1 that is not due")
    monkeypatch.setattr(tuesday, "load_week_data", never)
    assert tuesday.main([]) == 0
    assert "Week 1 isn't due yet" in capsys.readouterr().out

    monkeypatch.setattr(saturday, "not_configured", lambda *_: False)
    monkeypatch.setattr(saturday, "load_rosters", lambda *_: [_sub()])
    monkeypatch.setattr(tuesday, "paid_subscribers", lambda subs, *_: subs)
    monkeypatch.setattr(saturday, "current_season", lambda *a, **k: "2027")
    monkeypatch.setattr(saturday, "season_over", lambda *a, **k: False)
    monkeypatch.setattr(saturday, "current_week", lambda *a, **k: 1)
    monkeypatch.setattr(saturday, "week_one_due", lambda *a, **k: False)
    monkeypatch.setattr(saturday, "kickoffs", never)
    assert saturday.main([]) == 0
    assert "Week 1 isn't due yet" in capsys.readouterr().out


def test_the_operator_free_report_refuses_a_week_underway(tmp_path, monkeypatch,
                                                          capsys) -> None:
    """EMAILS-7: run.trial printed "before this week's first kickoff" and odds
    on Thursday's game, after it was played."""
    roster = tmp_path / "r.txt"
    roster.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(trial, "load_week_data",
                        lambda *a, **k: SimpleNamespace(season="2026", week=6))
    monkeypatch.setattr(trial, "week_has_kicked_off", lambda *a, **k: True)
    assert trial.main(["--email", "a@example.com", "--roster", str(roster)]) == 1
    assert "week 6 is underway" in capsys.readouterr().err


# --------------------------------------------------------------------- #
# D13 — roster updates
# --------------------------------------------------------------------- #

def _row(email, ref, origin, players=PLAYERS, scoring="ppr", slots=SLOTS):
    return {"email": email, "ref": ref, "origin": origin, "player_ids": list(players),
            "slots": list(slots), "scoring": scoring}


def test_an_update_expires_at_the_press_never_at_the_intakes_clock() -> None:
    """EMAILS-154, JOIN-145: a press inside 7 days, read by the next hourly
    intake just past the 7th day, was lost silently."""
    now = datetime(2026, 10, 17, 12, 47, tzinfo=timezone.utc)
    asked = "2026-10-10T12:00:00.000Z"
    new_ref = encode_roster("season", "ppr", list(SLOTS), PLAYERS[1:] + PLAYERS[:1])
    old_ref = encode_roster("season", "ppr", list(SLOTS), list(PLAYERS))
    rows = [_row("fan@example.com", old_ref, "abcdef0123")]
    request = {"email": "fan@example.com", "ref": new_ref, "received_at": asked}
    code = updates.confirm_code("fan@example.com", "abcdef0123", new_ref, "s", asked)
    pressed = {"code": code, "received_at": "2026-10-17T11:50:00.000Z"}
    pending, _ = updates.validate_requests([request], rows, None, "s", now=now,
                                           confirm_rows=[pressed])
    assert [p.code for p in pending] == [code]
    assert updates.confirmed_updates(pending, [pressed], "s")
    late = {"code": code, "received_at": "2026-10-17T12:10:00.000Z"}
    assert updates.validate_requests([request], rows, None, "s", now=now,
                                     confirm_rows=[late])[0] == []


def test_a_keep_request_withdraws_nothing_and_the_link_names_the_team() -> None:
    """EMAILS-152: anyone's same-as-current request silently killed a pending
    change. JOIN-104: an address with two teams could not change scoring or
    lineup, and the update link now names which team (opaque)."""
    now = datetime.now(timezone.utc)
    ts = lambda h: (now - timedelta(hours=h)).isoformat(timespec="milliseconds")  # noqa: E731
    a = encode_roster("season", "ppr", list(SLOTS), list(PLAYERS))
    b = encode_roster("season", "ppr", list(SLOTS), PLAYERS[1:] + PLAYERS[:1])
    rows = [_row("fan@example.com", a, "aaaaaaaaaa")]
    reqs = [{"email": "fan@example.com", "ref": b, "received_at": ts(5)},
            {"email": "fan@example.com", "ref": a, "received_at": ts(1)}]
    pending, _ = updates.validate_requests(reqs, rows, None, "s", now=now)
    assert [p.ref for p in pending] == [b]

    half = encode_roster("season", "half_ppr", list(SLOTS), list(PLAYERS))
    two = [_row("fan@example.com", a, "aaaaaaaaaa"),
           _row("fan@example.com", a, "bbbbbbbbbb", players=PLAYERS[:-1])]
    assert updates._target_for("fan@example.com", updates.decode_roster(half),
                               two) == "aaaaaaaaaa"
    tag = updates.origin_tag("bbbbbbbbbb", "s")
    named = [{"email": "fan@example.com", "ref": half, "received_at": ts(2),
              "replaces": tag}]
    [request] = updates.validate_requests(named, two, None, "s", now=now)[0]
    assert request.replaces == "bbbbbbbbbb"
    link = updates.public_update_url("https://x.test", "s", "https://w.test",
                                     roster=SimpleNamespace(scoring="ppr",
                                                            league_size=12,
                                                            slots=SLOTS,
                                                            slug="bbbbbbbbbb"))
    assert f"&o={tag}" in link and "bbbbbbbbbb" not in link


def test_saturday_rebuilds_a_plan_whose_settings_changed(monkeypatch) -> None:
    """JOIN-105, D13: a scoring or lineup change was ignored on Saturday — the
    old plan was checked under the old settings."""
    sub = _sub(scoring="half_ppr")
    plan = {"players": {pid: {} for pid in PLAYERS}, "slots": [],
            "setup": {"scoring": "ppr", "slots": list(SLOTS), "league_size": 12}}
    monkeypatch.setattr(saturday, "load_plan", lambda *a, **k: plan)
    args = SimpleNamespace(plans_dir=None, registry=None)
    seen = {}

    def data():
        seen["loaded"] = True
        raise RuntimeError("no data in this test")
    kind, why = saturday._check_one(sub, args, "2026", 7, None, {}, {}, set(), {},
                                    data)
    assert seen and kind == "unreadable" and "settings changed" in why
    assert saturday.plan_setup(sub)["scoring"] == "half_ppr"


# --------------------------------------------------------------------- #
# INFO-86 / EMAILS-109 — one roster, merged only while both subscriptions live
# --------------------------------------------------------------------- #

def _signup(ref, plan, sub, seen):
    return intake.RosterSignup(email="fan@example.com", ref=ref, plan=plan,
                               seen_at=str(seen), subscription_id=sub)


def test_the_same_roster_in_another_order_or_after_an_update_merges() -> None:
    a = encode_roster("season", "ppr", list(SLOTS), list(PLAYERS))
    reordered = encode_roster("league_pass", "ppr", list(SLOTS), list(reversed(PLAYERS)))
    merged = intake.merge_same_roster([_signup(a, "season", "sub_s", 1),
                                       _signup(reordered, "league_pass", "sub_p", 2)])
    assert len(merged.signups) == 1
    b = encode_roster("league_pass", "ppr", list(SLOTS), PLAYERS[:-1])
    season = _signup(a, "season", "sub_s", 1)
    current = {("fan@example.com", season.slug): encode_roster(
        "season", "ppr", list(SLOTS), PLAYERS[:-1])}
    assert len(intake.merge_same_roster(
        [season, _signup(b, "league_pass", "sub_p", 2)], current=current).signups) == 1


def test_a_dead_subscription_is_never_merged_into_a_live_one() -> None:
    a = encode_roster("season", "ppr", list(SLOTS), list(PLAYERS))
    signups = [_signup(a, "league_pass", "sub_p", 1), _signup(a, "season", "sub_s", 2)]
    merged = intake.merge_same_roster(signups, live={"sub_s"})
    assert len(merged.signups) == 2 and not merged.duplicates


# --------------------------------------------------------------------- #
# LANDING-96 — a player with no stat row waits for the whole week
# --------------------------------------------------------------------- #

def test_a_call_on_a_player_whose_game_has_not_been_played_stays_pending(
        tmp_path, monkeypatch) -> None:
    """Grading ran Monday morning, before Monday night: "Josh Allen over Jared
    Goff" settled as a MISS at 0.0 for a game not yet played, permanently."""
    import engine.ledger as ledger
    weekly = {6: {"p": {"team": "KC", "receptions": 5}, "q": {"team": "LV"}}}
    schedule = {6: {"KC": True, "LV": True, "BUF": False, "LA": False}}
    monkeypatch.setattr("ingest.nflverse.season_rows", lambda *a, **k: weekly)
    monkeypatch.setattr("ingest.nflverse.defense_rows", lambda *a, **k: {})
    monkeypatch.setattr(ledger, "_final_teams", lambda *a, **k: schedule)
    store = "typed-ppr-12-2026"
    path = ledger.ledger_path(tmp_path, store)
    ledger.record_calls(path, [ledger.LedgerCall(
        call_id="c1", source="slot", league_id=store, season="2026", week=6,
        roster_id=1, slot="QB", pick_id="p", pick_name="P", over_id="allen",
        over_name="Allen", confidence=0.6, recorded_at="2026-10-13T00:00:00+00:00")])
    assert ledger.grade_ledger_nflverse(path, tmp_path)[0] == 0, \
        "a player with no stat row was graded before his game was played"
    schedule[6].update(BUF=True, LA=True)
    weekly[6].update(b={"team": "BUF"}, l={"team": "LA"})
    assert ledger.grade_ledger_nflverse(path, tmp_path)[0] == 1
