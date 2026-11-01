"""Up to three teams on one plan (owner decision, Oct 31 2026): run/teams.py and
the catalogue behind it, run/plans.py."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from render.team_mail import team_added_message, team_confirm_email, team_full_email
from run import billing, plans
from run.intake import RosterSignup, team_signups, to_rows
from run.refs import decode_roster, encode_roster
from run.rosters import load_rosters
from run.subscriptions import PaidList
from run.teams import (TEAM_LOG_NAME, PendingTeam, TeamEntry, add_names, add_team_url,
                       append_team_log, clean_name, load_team_log, sweep_teams, team_code,
                       team_counts, team_mail_key, team_origin, team_row_open, teams_held)
from run.updates import (RosterUpdate, confirm_code, latest_names, origin_tag,
                         validate_requests)

from test_intake_sync import stripe  # noqa: F401 — the fake Stripe fixture

ROOT = Path(__file__).resolve().parent.parent
SECRET = "s" * 40
NOW = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
PLAYERS = [p[1] for p in json.loads(
    (ROOT / "site" / "join" / "players.json").read_text(encoding="utf-8"))["players"]
    if str(p[1]).startswith("00-")]


def ref(start: int, league_type: str = "redraft", plan: str = "monthly") -> str:
    return encode_roster(plan, "ppr", SLOTS, PLAYERS[start:start + 15], 12,
                         league_type=league_type)


def row(start: int = 0, email: str = "a@example.com", sub: str = "sub_AAAA1", **extra) -> dict:
    roster = decode_roster(ref(start))
    return {"email": email, "ref": ref(start), "player_ids": list(roster.player_ids),
            "slots": list(roster.slots), "scoring": "ppr", "league_size": 12,
            "label": "Your Team", "plan": "monthly", "billing": "monthly",
            "subscription_ids": [sub], **extra}


def request(start: int = 40, email: str = "a@example.com", hours: int = 1, **extra) -> dict:
    return {"kind": "team_add", "email": email, "ref": ref(start, "dynasty"),
            "received_at": (NOW - timedelta(hours=hours)).isoformat(), **extra}


def sweep(rows, held=None, live=("sub_AAAA1",), confirm=(), **kw):
    return sweep_teams(rows, [row()] if held is None else held, set(PLAYERS), SECRET,
                       None if live is None else set(live), confirm_rows=confirm,
                       now=NOW, **kw)


def code_of(req: dict) -> str:
    return team_code(req["email"], req["ref"], req["received_at"], SECRET,
                     clean_name(req.get("name")))


# --------------------------------------------------------------------- #
# a request grants nothing
# --------------------------------------------------------------------- #

def test_a_request_is_mailed_a_code_and_adds_nothing() -> None:
    result = sweep([request()])
    assert [p.ref for p in result.pending] == [ref(40, "dynasty")] and not result.confirmed


def test_an_address_with_no_plan_gets_silence() -> None:
    """The page is public: answering would reveal who subscribes."""
    result = sweep([request(email="stranger@example.com")])
    assert not result.pending and not result.full and not result.problems


def test_a_cancelled_plan_cannot_add_a_team() -> None:
    assert not sweep([request()], live=()).pending


def test_a_seat_holder_has_no_plan_to_add_to() -> None:
    seat = row()
    seat.pop("subscription_ids")
    assert not sweep([request()], held=[seat]).pending


def test_with_stripe_unreadable_the_request_waits() -> None:
    result = sweep([request()], live=None)
    assert not result.pending and result.problems


def test_only_the_recomputed_code_confirms() -> None:
    req = request()
    assert not sweep([req], confirm=[{"code": "0" * 24}]).confirmed
    press = {"code": code_of(req), "received_at": NOW.isoformat()}
    entry = sweep([req], confirm=[press]).confirmed[0]
    assert (entry.subscription_id, entry.ref) == ("sub_AAAA1", req["ref"])


def test_the_code_binds_the_name() -> None:
    assert (team_code("a@b.co", "r", "t", SECRET, "One")
            != team_code("a@b.co", "r", "t", SECRET, "Two"))


def test_a_team_code_is_not_a_roster_code() -> None:
    assert team_code("a@b.co", "r", "t", SECRET) != confirm_code("a@b.co", "", "r", SECRET, "t")


def test_a_request_expires_unless_it_was_pressed_in_time() -> None:
    old = request(hours=24 * 8)
    assert not sweep([old]).pending
    pressed = {"code": code_of(old), "received_at": (NOW - timedelta(days=2)).isoformat()}
    assert sweep([old], confirm=[pressed]).confirmed


def test_a_used_code_does_nothing_twice() -> None:
    req = request()
    press = {"code": code_of(req), "received_at": NOW.isoformat()}
    entry = sweep([req], confirm=[press]).confirmed[0]
    result = sweep([req], confirm=[press], log=[entry])
    assert not result.confirmed and not result.pending


def test_a_stranger_cannot_flood_an_inbox() -> None:
    assert len(sweep([request(hours=h) for h in range(1, 9)]).pending) == 3


# --------------------------------------------------------------------- #
# three teams, and only three
# --------------------------------------------------------------------- #

def test_the_third_team_fits_and_the_fourth_does_not() -> None:
    two = [row(), row(20)]
    assert sweep([request()], held=two).pending
    three = [row(), row(20), row(60)]
    result = sweep([request()], held=three)
    assert not result.pending and [p.ref for p in result.full] == [ref(40, "dynasty")]


def test_two_presses_cannot_pass_the_cap() -> None:
    first, second = request(40, hours=2), request(80, hours=1)
    presses = [{"code": code_of(r), "received_at": NOW.isoformat()} for r in (first, second)]
    result = sweep([first, second], held=[row(), row(20)], confirm=presses)
    assert [e.ref for e in result.confirmed] == [first["ref"]]
    assert [p.ref for p in result.full] == [second["ref"]]


def test_the_same_roster_is_one_report() -> None:
    same = {**request(), "ref": ref(0, plan="season")}
    assert not sweep([same]).pending


def test_a_cancelled_plans_roster_can_come_back() -> None:
    """Review: rows are never pruned, so a returning dynasty manager re-adding
    a team from a lapsed plan got silence while the page promised an email."""
    held = [row(), row(40, sub="sub_DEAD1")]
    held[1]["ref"] = ref(40, "dynasty")
    assert sweep([request()], held=held).pending


def test_a_request_older_than_its_button_costs_no_stripe_read() -> None:
    assert team_row_open(request(hours=24), NOW)
    assert not team_row_open(request(hours=24 * 10), NOW)
    assert not team_row_open({}, NOW)


def test_an_update_cannot_make_one_team_into_another() -> None:
    """Review: two rows with one ref collide at the writer, which drops the
    older, and that row can be the League Pass itself."""
    held = [row(origin="aaaaaaaaaa"), row(20, origin="bbbbbbbbbb")]
    same = {"email": "a@example.com", "ref": ref(20), "replaces": origin_tag("aaaaaaaaaa", SECRET),
            "received_at": (NOW - timedelta(hours=1)).isoformat()}
    pending, problems = validate_requests([same], held, set(PLAYERS), SECRET, now=NOW)
    assert pending == [] and problems


def test_a_confirmation_shows_the_name_it_applies() -> None:
    """Review: a stranger who saw a forwarded report could post that roster
    with a name, and the email showed none of it before the press."""
    from render.roster_update import confirm_email
    subject, html_, text = confirm_email("https://x.test/c", ["A"], name="Cheater")
    assert "Cheater" in html_ and "Team name: Cheater" in text


def test_saturday_tells_two_teams_apart() -> None:
    from render.final_check import subject_for_check
    assert subject_for_check(9, [], "Work league").startswith("Week 9 — Work league")
    assert subject_for_check(9, []).startswith("Week 9")


def test_the_watchdog_dates_a_team_from_its_plan() -> None:
    """Review: unknown purchases count as owed, so a team row meant no alarm
    could ever be quieted by "nobody was owed"."""
    from run.watchdog import purchase_times

    class Team:
        covered_by, slug, subscription_ids = None, "teamteam00", ("sub_AAAA1",)
    assert purchase_times([Team()], [parent()])[0] is not None


def test_keeper_and_redraft_with_the_same_players_are_two_teams() -> None:
    assert sweep([{**request(), "ref": ref(0, "keeper")}]).pending


def test_a_second_plan_on_the_address_takes_the_overflow() -> None:
    held = [row(), row(20), row(60), row(80, sub="sub_BBBB2")]
    result = sweep([request(100)], held=held, live=("sub_AAAA1", "sub_BBBB2"))
    assert [p.subscription_id for p in result.pending] == ["sub_BBBB2"]


def test_the_report_link_names_the_plan() -> None:
    held = [row(sub="sub_AAAA1", origin="aaaaaaaaaa"), row(20, sub="sub_BBBB2", origin="bbbbbbbbbb")]
    tag = origin_tag("bbbbbbbbbb", SECRET)
    result = sweep([request(owner=tag)], held=held, live=("sub_AAAA1", "sub_BBBB2"))
    assert result.pending[0].subscription_id == "sub_BBBB2"


def test_a_counted_team_names_its_subscription_and_a_seat_counts_nowhere() -> None:
    assert team_counts([row(), row(20), {"email": "seat@x.co"}]) == {"sub_AAAA1": 2}


def test_teams_held_is_the_count_on_the_plan() -> None:
    class Sub:
        subscription_ids = ("sub_AAAA1",)
    assert teams_held(Sub(), {"sub_AAAA1": 2}) == 2


# --------------------------------------------------------------------- #
# a team is a row on the same subscription
# --------------------------------------------------------------------- #

def parent(plan: str = "monthly", **extra) -> RosterSignup:
    return RosterSignup(email="a@example.com", ref=ref(0), plan=plan, seen_at="1793000000",
                        stripe_customer_id="cus_AAAA1", subscription_id="sub_AAAA1", **extra)


def entry(start: int = 40, name: str = "") -> TeamEntry:
    return TeamEntry("a@example.com", "sub_AAAA1", ref(start, "dynasty"),
                     team_origin("sub_AAAA1", "t"), "2026-11-03T15:00:00+00:00", "c" * 24,
                     name=name)


def test_a_team_row_lives_on_its_parents_subscription(tmp_path) -> None:
    rows = to_rows(team_signups([entry(name="Dynasty")], [parent()]))
    path = tmp_path / "rosters.json"
    path.write_text(json.dumps(to_rows([parent()]) + rows), encoding="utf-8")
    team = load_rosters(path)[1] if load_rosters(path)[1].label == "Dynasty" else load_rosters(path)[0]
    assert team.subscription_ids == ("sub_AAAA1",) and team.league_type == "dynasty"
    assert team.origin == team_origin("sub_AAAA1", "t")


@pytest.mark.parametrize("ids,entitled", [(frozenset({"sub_AAAA1"}), True), (frozenset(), False)])
def test_cancelling_or_refunding_ends_every_team(tmp_path, ids, entitled) -> None:
    path = tmp_path / "rosters.json"
    path.write_text(json.dumps(to_rows([parent(), *team_signups([entry()], [parent()])])),
                    encoding="utf-8")
    paid = PaidList(emails=frozenset({"a@example.com"}), source="stripe", status_column=None,
                    customer_ids=frozenset({"cus_AAAA1"}), subscription_ids=ids)
    assert [paid.entitles(s) for s in load_rosters(path)] == [entitled, entitled]


def test_a_pass_buyers_team_is_no_second_pass() -> None:
    rows = to_rows(team_signups([entry()], [parent("league_pass")]))
    assert rows[0]["plan"] == rows[0]["billing"] == "monthly"
    assert rows[0].get("pass_id") is None and rows[0]["subscription_ids"] == ["sub_AAAA1"]


def test_a_team_later_bought_outright_gives_way_to_the_purchase() -> None:
    bought = RosterSignup(email="a@example.com", ref=ref(40, "dynasty"), plan="monthly",
                          seen_at="1793000000", subscription_id="sub_BBBB2")
    assert team_signups([entry()], [parent(), bought]) == []


def test_a_team_moved_off_a_roster_keeps_its_row() -> None:
    """Review: the check read the roster the team was ADDED with, so a team
    updated away from B while its parent moved onto B vanished with no row, no
    mail and no alarm."""
    team = team_signups([entry()], [parent()])[0]
    moved = {("a@example.com", team.slug): ref(80), ("a@example.com", parent().slug): ref(40, "dynasty")}
    assert len(team_signups([entry()], [parent()], moved)) == 1


def test_a_team_on_a_folded_purchase_lives_on_both() -> None:
    both = parent(group_subscriptions=("sub_AAAA1", "sub_BBBB2"))
    assert to_rows(team_signups([entry()], [both]))[0]["subscription_ids"] == ["sub_AAAA1", "sub_BBBB2"]


def test_a_team_with_no_parent_is_not_written() -> None:
    assert team_signups([entry()], []) == []


def test_the_log_is_append_only_and_idempotent(tmp_path) -> None:
    path = tmp_path / TEAM_LOG_NAME
    assert append_team_log([entry()], path) == 1
    assert append_team_log([entry()], path) == 0
    assert load_team_log(path) == [entry()]


# --------------------------------------------------------------------- #
# names
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,name", [("Work league", "Work league"), ("  A   B ", "A B"),
                                      ("<b>x</b>", ""), ("a\nBcc: x@y.z", "a Bcc: x@y.z"[:0]),
                                      ("x" * 25, ""), ("", ""), (None, "")])
def test_a_name_cannot_carry_markup_or_a_line_break(raw, name) -> None:
    assert clean_name(raw) == name


def test_a_name_set_later_survives_a_later_update_without_one() -> None:
    log = [RosterUpdate("a@b.co", "aaaaaaaaaa", "r1", "t1", name="Work"),
           RosterUpdate("a@b.co", "aaaaaaaaaa", "r2", "t2")]
    assert latest_names(log) == {("a@b.co", "aaaaaaaaaa"): "Work"}
    rows = add_names([{"email": "a@b.co", "origin": "aaaaaaaaaa", "label": "Your Team"}],
                     latest_names(log))
    assert rows[0]["label"] == "Work"


def test_a_new_name_alone_is_a_change_worth_confirming() -> None:
    held = [row(origin="aaaaaaaaaa")]
    same = {"email": "a@example.com", "ref": ref(0), "name": "Work",
            "received_at": (NOW - timedelta(hours=1)).isoformat()}
    pending, _ = validate_requests([same], held, set(PLAYERS), SECRET, now=NOW)
    assert [p.name for p in pending] == ["Work"]
    pending, _ = validate_requests([{**same, "name": ""}], held, set(PLAYERS), SECRET, now=NOW)
    assert pending == []


def test_no_name_leaves_a_roster_code_as_it_was() -> None:
    assert confirm_code("a@b.co", "s", "r", SECRET, "t") == confirm_code("a@b.co", "s", "r", SECRET, "t", "")


# --------------------------------------------------------------------- #
# the links and the mail
# --------------------------------------------------------------------- #

def test_the_add_link_appears_only_when_the_flow_works() -> None:
    assert add_team_url("", SECRET, "https://f") is None
    assert add_team_url("https://s", "", "https://f") is None
    assert add_team_url("https://s", SECRET, "") is None
    assert add_team_url("https://s/", SECRET, "https://f") == "https://s/join/?add=1"


def test_the_confirmation_says_what_it_adds_and_that_it_is_free() -> None:
    subject, html, text = team_confirm_email("https://s/c", ["A", "B"],
                                             decode_roster(ref(0, "dynasty")), "Work")
    for words in (html, text):
        assert "no extra charge" in words and "Dynasty" in words and "Work" in words
        assert "Ignore this email" in words and "12 teams" in words
    assert subject == "Confirm your new team"


def test_the_full_note_charges_nothing() -> None:
    assert "Nothing was charged" in team_full_email()[2]


def test_the_added_note_goes_once_per_team() -> None:
    team = team_signups([entry(name="Work")], [parent()])[0]
    message = team_added_message(team)
    assert message.key == f"team-added-{team.slug}" and message.subject == "Work is set up"
    assert "a@example.com" not in message.key


def test_no_mail_key_carries_an_address(monkeypatch) -> None:
    monkeypatch.setenv("LOG_SECRET", "x" * 32)
    key = team_mail_key("confirm", PendingTeam("a@example.com", "sub_1", "r", "c" * 24, "t"))
    assert "@" not in key and "example" not in key


# --------------------------------------------------------------------- #
# the catalogue: more sports and year-round billing later
# --------------------------------------------------------------------- #

def _plan(end: datetime) -> dict:
    return {"id": "sub_1", "status": "active", "cancel_at": None, "cancel_at_period_end": False,
            "customer": {"id": "cus_1", "metadata": {billing.ROSTER_METADATA_KEY: "r3-mc-x"}},
            "items": {"data": [{"price": {"recurring": {"interval": "month"}},
                                "current_period_end": int(end.timestamp())}]}}


FINAL = datetime(2026, 12, 23, 22, 17, tzinfo=timezone.utc)
LATE = _plan(FINAL + timedelta(days=5))


def test_today_a_plan_stops_because_months_are_empty() -> None:
    assert plans.empty_months() == [2, 3, 4, 5, 6, 7, 8]
    assert not plans.bills_all_year()
    assert billing.needs_stop([LATE], FINAL)[0]


def test_the_switch_alone_cannot_bill_an_empty_month(monkeypatch) -> None:
    """PLAN §4: nobody pays for a month with nothing in it."""
    monkeypatch.setattr(plans, "YEAR_ROUND_BILLING", True)
    assert not plans.bills_all_year()
    assert billing.needs_stop([LATE], FINAL)[0]


def test_with_every_month_filled_the_switch_keeps_plans_running(monkeypatch) -> None:
    monkeypatch.setattr(plans, "YEAR_ROUND_BILLING", True)
    monkeypatch.setattr(plans, "EXTRAS", {m: "something real" for m in range(2, 9)})
    assert plans.bills_all_year()
    assert billing.needs_stop([LATE], FINAL)[0] == []


def test_a_refund_ends_a_plan_even_all_year(monkeypatch) -> None:
    monkeypatch.setattr(plans, "YEAR_ROUND_BILLING", True)
    monkeypatch.setattr(plans, "EXTRAS", {m: "something real" for m in range(2, 9)})
    assert billing.needs_stop([LATE], FINAL, lambda _s: "refunded")[0]


def test_an_unknown_sport_cannot_load(tmp_path) -> None:
    path = tmp_path / "rosters.json"
    path.write_text(json.dumps([{**row(), "sport": "curling"}]), encoding="utf-8")
    with pytest.raises(Exception, match="sport"):
        load_rosters(path)


def test_the_page_and_the_catalogue_agree() -> None:
    page = (ROOT / "site" / "join" / "index.html").read_text(encoding="utf-8")
    assert f"const TEAMS_INCLUDED = {plans.TEAMS_INCLUDED};" in page


# --------------------------------------------------------------------- #
# the Worker
# --------------------------------------------------------------------- #

node = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")


def _worker(row_json: str) -> dict | None:
    source = (ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
    start = source.index("const EMAIL")
    end = source.index("// The read key, compared without")
    script = re.sub(r"^export ", "", source[start:end], flags=re.M) + (
        f"\nconsole.log(JSON.stringify(sanitize({row_json})));\n")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@node
def test_the_worker_takes_a_team_and_cleans_it() -> None:
    row_ = _worker('{kind:"team_add",email:"a@b.co",ref:"m4-abc",name:"Work league",'
                   'owner:"0123456789ab",extra:"x"}')
    assert row_ == {"kind": "team_add", "email": "a@b.co", "ref": "m4-abc",
                    "name": "Work league", "owner": "0123456789ab"}


@node
def test_the_worker_drops_a_bad_name_and_a_bad_owner() -> None:
    row_ = _worker('{kind:"team_add",email:"a@b.co",ref:"m4-abc",name:"<b>",owner:"nope"}')
    assert row_ == {"kind": "team_add", "email": "a@b.co", "ref": "m4-abc"}


# --------------------------------------------------------------------- #
# through the real intake
# --------------------------------------------------------------------- #

def test_a_team_goes_from_a_request_to_its_own_report(tmp_path, stripe, monkeypatch) -> None:
    """The wiring, end to end: a buyer pays once, asks for a team, is mailed a
    button and presses it. No second payment. The team lands on the registry
    under the same subscription, gets its note and its own report that run."""
    import run.intake as intake
    import run.tuesday as tuesday
    from test_intake_sync import MONTHLY_LINK, PASS_REF, _first_email_env, _seats, _session, _Sink
    first = decode_roster(PASS_REF)
    team_ref = encode_roster("monthly", "ppr", list(first.slots), list(first.player_ids),
                             league_type="keeper")
    up = _Sink()
    data, season, week = _first_email_env(tmp_path, monkeypatch, up)
    monkeypatch.setattr(intake, "load_week_data", lambda *a, **k: data)
    monkeypatch.setattr("run.tuesday.PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setenv("STRIPE_PAYMENT_LINKS", f"m:{MONTHLY_LINK}")
    monkeypatch.setenv("UPDATE_SECRET", SECRET)
    monkeypatch.setenv("SITE_URL", "https://x.test")
    monkeypatch.setenv("LOG_SECRET", "x" * 32)
    monkeypatch.setattr(intake, "_team_live", lambda *a, **k: {"sub_TEAM0001"})
    monkeypatch.setattr(intake, "_live_subscriptions", lambda *a, **k: None)
    stripe["sessions"] = [_session(
        encode_roster("monthly", "ppr", list(first.slots), list(first.player_ids)),
        sid="cs_m", email="fan@example.com", link=MONTHLY_LINK,
        subscription="sub_TEAM0001")]
    stamp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    ask = {"kind": "team_add", "email": "fan@example.com", "ref": team_ref, "name": "Work league",
           "received_at": stamp}
    reg = tmp_path / "reg"
    _seats(monkeypatch, ask)
    seen: list[dict] = []
    real = tuesday.text_summary
    monkeypatch.setattr(tuesday, "text_summary",
                        lambda report: seen.append(report) or real(report))

    assert intake.main(["--registry-dir", str(reg)]) == 0
    assert len(load_rosters(reg / intake.REGISTRY_NAME)) == 1, "a request added a team"
    confirm = [m for m in up.sent if m.key.startswith("team-confirm-")]
    assert len(confirm) == 1 and confirm[0].to == "fan@example.com"
    assert "k=team" in confirm[0].text

    press = {"kind": "confirm", "received_at": datetime.now(timezone.utc).isoformat(),
             "code": team_code("fan@example.com", team_ref, stamp, SECRET, "Work league")}
    _seats(monkeypatch, ask, press)
    up.sent.clear()
    assert intake.main(["--registry-dir", str(reg)]) == 0
    rows = load_rosters(reg / intake.REGISTRY_NAME)
    team = next(r for r in rows if r.label == "Work league")
    assert len(rows) == 2 and team.subscription_ids == ("sub_TEAM0001",)
    assert [m.subject for m in up.sent if m.key == f"team-added-{team.slug}"] == ["Work league is set up"]
    weekly = [m for m in up.sent if team.slug in m.key and "-w" in m.key]
    assert len(weekly) == 1 and "Work league" in weekly[0].subject
    assert seen[-1]["meta"]["teams"]["held"] == 2 and seen[-1]["meta"]["teams"]["cap"] == 3
    assert seen[-1]["meta"]["teams"]["add_url"].startswith("https://x.test/join/?add=1&o=")

    # A later run sends nothing twice and adds nothing twice.
    up.sent.clear()
    assert intake.main(["--registry-dir", str(reg)]) == 0
    assert len(load_rosters(reg / intake.REGISTRY_NAME)) == 2
    assert not [m for m in up.sent if m.key.startswith("team-")]


@pytest.mark.parametrize("held,says,links", [
    (1, "Your plan covers up to 3 teams at no extra charge. Add another here:", True),
    (2, "You have 2. Add another here:", True),
    (3, "Your plan's 3 teams are all in use.", False)])
def test_every_report_says_where_the_plan_stands(held, says, links) -> None:
    from render.report import team_line, team_lines
    meta = {"week": 6, "last_week": 18, "solo": True,
            "teams": {"held": held, "cap": 3, "add_url": "https://x.test/join/?add=1"}}
    assert says in html.unescape(team_line(meta)) and says in " ".join(team_lines(meta))
    assert ("https://x.test/join/?add=1" in team_line(meta)) is links


def test_the_last_report_and_a_free_report_offer_no_team() -> None:
    from render.report import team_line, team_lines
    teams = {"held": 1, "cap": 3, "add_url": "https://x.test/join/?add=1"}
    assert team_line({"week": 18, "last_week": 18, "solo": True, "teams": teams}) == ""
    assert team_lines({"week": 6, "last_week": 18, "solo": True, "trial": True,
                       "teams": teams}) == []
    assert team_line({"week": 6, "last_week": 18, "solo": True}) == ""
