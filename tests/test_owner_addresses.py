"""The owner's own addresses (run/owner.py, OWNER_EMAILS, owner request Nov 3 2026).

The owner tests the live product with their own inbox. Two things change for
those addresses and nothing else: room to test (the free report again and
again, higher daily caps that still cap), and being left out of every number
the owner reads. Entitlement, the stop list, refunds and the team limit are
the same for everybody. Example addresses only: the owner's real ones live in
a secret and in .env, never here.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import run.owner as owner
import run.stats as stats
import run.trials as trials
from run.owner import (OWNER_DAILY_CAP, count_not_counted, daily_cap, is_owner_address,
                       is_owner_purchase, not_counted, owner_addresses, owners_line)

# Fake addresses at a domain nothing answers for, so the TEST-domain rule
# (example.com and friends) can't be what leaves them out: every exclusion
# below has to come from OWNER_EMAILS.
OWNER = "boss@owner-inbox.mail"
OWNER_GMAIL = "the.boss.byl@gmail.com"
BUYER = "fan@fans.mail"
ENV = {"OWNER_EMAILS": f"{OWNER}, {OWNER_GMAIL}"}
OWNERS = owner_addresses(ENV)
NOW = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)


# --------------------------------------------------------------------- #
# one source, matched by mailbox, fail closed
# --------------------------------------------------------------------- #

def test_matching_is_by_mailbox_and_unset_is_nobody(monkeypatch, tmp_path) -> None:
    assert len(OWNERS) == 2
    for spelling in ("BOSS@Owner-Inbox.mail", " boss+stripe-test@owner-inbox.mail ",
                     "theboss.byl@gmail.com", "T.H.E.B.O.S.S.B.Y.L+x@googlemail.com"):
        assert is_owner_address(spelling, owners=OWNERS), spelling
    for other in (BUYER, "boss@owner-inbox.mail.evil", "", None, "not an address"):
        assert not is_owner_address(other, owners=OWNERS), other
    # Unset, empty, or nothing shaped like an address: nobody is the owner.
    for raw in ({}, {"OWNER_EMAILS": ""}, {"OWNER_EMAILS": " , ;"},
                {"OWNER_EMAILS": "not-an-address"}):
        assert owner_addresses(raw) == frozenset()
        assert not is_owner_address(OWNER, raw)
    # The process environment first (a set variable, even empty, wins) ...
    monkeypatch.setenv("OWNER_EMAILS", OWNER)
    assert is_owner_address(OWNER)
    env_file = tmp_path / ".env"
    env_file.write_text(f"OWNER_EMAILS={OWNER_GMAIL}\n", encoding="utf-8")
    monkeypatch.setattr(owner, "ENV_FILE", env_file)
    monkeypatch.setenv("OWNER_EMAILS", "")
    assert owner_addresses() == frozenset()
    # ... then the gitignored .env on the owner's machine.
    monkeypatch.delenv("OWNER_EMAILS")
    assert owner_addresses() == {"thebossbyl@gmail.com"}
    monkeypatch.setattr(owner, "ENV_FILE", tmp_path / "missing.env")
    assert owner_addresses() == frozenset()


def test_nothing_prints_the_addresses_only_a_count() -> None:
    assert owners_line(OWNERS) == "2 owner addresses set (OWNER_EMAILS)"
    assert "@" not in owners_line(OWNERS) and "@" not in owners_line(frozenset())


# --------------------------------------------------------------------- #
# room to test: caps raised, never removed
# --------------------------------------------------------------------- #

def test_the_raised_cap_still_caps() -> None:
    assert OWNER_DAILY_CAP == 20
    assert daily_cap(BUYER, 3, OWNERS) == 3
    assert daily_cap(OWNER, 3, OWNERS) == OWNER_DAILY_CAP
    assert daily_cap(OWNER, 3, frozenset()) == 3, "unset: the owner is anybody"
    assert daily_cap(OWNER, 50, OWNERS) == 50, "never lower than the base"


def test_trade_checks_get_the_owners_cap_and_no_more() -> None:
    from run.trades import asks_from

    def rows(email, n):
        return [{"email": email, "ref": f"r{i}", "received_at":
                 (NOW - timedelta(minutes=i + 1)).isoformat()} for i in range(n)]
    assert len(asks_from(rows(BUYER, 25), NOW, owners=OWNERS)) == 3
    assert len(asks_from(rows(OWNER, 6), NOW, owners=OWNERS)) == 6
    assert len(asks_from(rows(OWNER, 25), NOW, owners=OWNERS)) == OWNER_DAILY_CAP
    assert len(asks_from(rows(OWNER, 25), NOW, owners=frozenset())) == 3


def test_roster_update_confirmations_get_the_owners_cap() -> None:
    import run.updates as updates
    from test_intake_sync import PLAYERS, SLOTS
    from run.refs import encode_roster
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    on_file = encode_roster("season", "ppr", list(SLOTS), list(PLAYERS))

    def run(email, n, owners):
        registry = [{"email": email, "ref": on_file, "origin": "aaaaaaaaaa",
                     "player_ids": list(PLAYERS), "slots": list(SLOTS), "scoring": "ppr"}]
        requests = [{"email": email, "received_at": (now - timedelta(minutes=50 - i)).isoformat(),
                     "ref": encode_roster("season", "half_ppr", list(SLOTS),
                                          PLAYERS[i:] + PLAYERS[:i])} for i in range(n)]
        return updates.validate_requests(requests, registry, None, "s", now=now,
                                         owners=owners)[0]
    assert len(run(BUYER, 8, OWNERS)) == updates.CONFIRMS_PER_DAY
    assert len(run(OWNER, 8, OWNERS)) == 8
    assert len(run(OWNER, 8, frozenset())) == updates.CONFIRMS_PER_DAY


def test_extra_team_confirmations_get_the_owners_cap_and_the_team_limit_holds() -> None:
    from test_teams import request, row, sweep
    asks = [request(40 + i, email=OWNER, hours=1 + i) for i in range(6)]
    held = [row(email=OWNER)]
    assert len(sweep(asks, held=held, owners=frozenset()).pending) == 3
    assert len(sweep(asks, held=held, owners=OWNERS).pending) == 6
    # The three-team limit is the same for the owner: a full plan is told so.
    full = [row(email=OWNER), row(20, email=OWNER), row(60, email=OWNER)]
    result = sweep(asks, held=full, owners=OWNERS)
    assert not result.pending and result.full


def test_seat_notes_get_the_owners_cap(monkeypatch) -> None:
    import run.intake as intake
    from test_prelaunch_worker import _at, _ref
    now = datetime.now(timezone.utc)
    rows = [{"email": f"the.boss.byl+{i}@gmail.com", "ref": _ref(), "received_at": _at(8, now),
             "pass_token": "f" * 20} for i in range(5)]
    assert len(intake.unmatched_due(rows, now)) == intake.UNMATCHED_PER_DAY
    monkeypatch.setenv("OWNER_EMAILS", OWNER_GMAIL)
    assert len(intake.unmatched_due(rows, now)) == 5
    assert len(intake.full_due(rows, now)) == 5


# --------------------------------------------------------------------- #
# the free report, again and again
# --------------------------------------------------------------------- #

FRESH = "2025-12-31T12:00:00.000Z"
SINCE = datetime(2025, 12, 20, tzinfo=timezone.utc)
THURSDAY = "2026-01-01T15:00:00+00:00"


def _trial(email, ref, stamp=FRESH):
    return {"kind": "trial", "email": email, "ref": ref, "received_at": stamp}


def test_the_owner_skips_one_per_season_and_the_subscriber_refusal() -> None:
    from test_trials import REF
    served = {trials.trial_key("2026", OWNER)}
    rows = [_trial(OWNER, REF, "2025-12-31T10:00:00.000Z"),
            _trial(OWNER, REF, "2025-12-31T12:00:00.000Z"), _trial(BUYER, REF)]
    # Without the owner list: one a season, and never a subscriber.
    assert trials.pending(rows, {OWNER}, served, "2026", since=SINCE) == [(BUYER, REF)]
    mine = trials.owner_pending(rows, OWNERS, served, "2026", since=SINCE, now=NOW)
    assert [(e, r) for e, r, _k in mine] == [(OWNER.lower(), REF)] * 2
    # Each request is its own key, none of them the season's one key, no address.
    keys = [k for _e, _r, k in mine]
    assert len(set(keys)) == 2 and served.isdisjoint(keys)
    assert all(trials.is_owner_trial_key(k) and "@" not in k for k in keys)
    # The normal path never also serves an owner's request.
    assert trials.pending(rows, set(), set(), "2026", since=SINCE, owners=OWNERS) == \
        [(BUYER, REF)]
    # A double-fired run: a request already in the send log is never mailed twice.
    assert trials.owner_pending(rows, OWNERS, set(keys), "2026", since=SINCE, now=NOW) == []
    # Unset: nobody is the owner.
    assert trials.owner_pending(rows, frozenset(), set(), "2026", since=SINCE, now=NOW) == []


def test_the_owner_keeps_every_honesty_rule_and_a_daily_cap() -> None:
    from test_trials import REF
    stale = _trial(OWNER, REF, "2025-10-20T18:00:00.000Z")
    unstamped = {"kind": "trial", "email": OWNER, "ref": REF}
    junk = _trial(OWNER, "garbage")
    assert trials.owner_pending([stale, unstamped, junk], OWNERS, set(), "2026",
                                since=SINCE, now=NOW) == []
    assert trials.owner_pending([_trial(OWNER, REF)], OWNERS, set(), "2026",
                                since=None, now=NOW) == [], "season start unknown: nothing"
    many = [_trial(OWNER, REF, f"2025-12-31T{h:02d}:00:00.000Z") for h in range(24)]
    assert len(trials.owner_pending(many, OWNERS, set(), "2026", since=SINCE,
                                    now=NOW)) == OWNER_DAILY_CAP
    prefix = trials.owner_trial_prefix("2026", OWNER)
    today = [{"key": f"{prefix}{i:010x}", "sent_at": NOW.isoformat()} for i in range(19)]
    assert len(trials.owner_pending(many, OWNERS, set(), "2026", since=SINCE,
                                    entries=today, now=NOW)) == 1
    yesterday = [dict(e, sent_at=(NOW - timedelta(days=1)).isoformat()) for e in today]
    assert len(trials.owner_pending(many, OWNERS, set(), "2026", since=SINCE,
                                    entries=yesterday, now=NOW)) == OWNER_DAILY_CAP


def _drive(tmp_path, monkeypatch, capsys, *, rows, registry_rows=(), sent=(),
           underway=datetime(2099, 1, 1, tzinfo=timezone.utc), owners=ENV["OWNER_EMAILS"]):
    """run.trials.main end to end on the fixture week, the same stubs as
    tests/test_trials.py, with the one-roster rule ON."""
    import run.delivery as delivery
    import run.intake as intake
    from test_solo_run import SEASON, WEEK, _cache
    monkeypatch.setenv("OWNER_EMAILS", owners)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.setenv("FORM_ENDPOINT", "https://w.test")
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: list(rows))
    log = tmp_path / "sent.jsonl"
    log.write_text("".join(json.dumps({"key": k, "provider": "resend", "message_id": "x",
                                       "sent_at": at}) + "\n" for k, at in sent))
    monkeypatch.setattr(delivery, "SENT_LOG", log)
    mailed = []

    class Fake:
        name = "fake"

        def send(self, message, sender, reply_to):
            mailed.append(message)
            return "id"
    monkeypatch.setattr(delivery, "build_provider", lambda *a, **k: Fake())
    monkeypatch.setattr("run.solo.current_season", lambda *a, **k: SEASON)
    monkeypatch.setattr("run.solo.current_week", lambda *a, **k: WEEK)
    monkeypatch.setattr("run.solo.season_over", lambda *a, **k: False)
    monkeypatch.setattr(trials, "week_underway_from", lambda *a: underway)
    monkeypatch.setattr(trials, "season_start", lambda *a: SINCE)
    monkeypatch.setattr(trials, "free_reports_open", lambda *a, **k: True)
    monkeypatch.setattr("run.solo.CACHE_DIR", _cache(tmp_path))
    reg = tmp_path / "reg" / "rosters.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps(list(registry_rows)))
    capsys.readouterr()
    code = trials.main(["--registry", str(reg), "--now", THURSDAY])
    captured = capsys.readouterr()
    return code, captured.out + captured.err, mailed, reg


def _subscriber(email, ref):
    from run.intake import RosterSignup, to_rows
    return to_rows([RosterSignup(email=email, ref=ref, plan="monthly", seen_at="1793000000",
                                 stripe_customer_id="cus_AAAA1",
                                 subscription_id="sub_AAAA1")])[0]


def test_end_to_end_the_owner_is_mailed_where_a_buyer_is_refused(
        tmp_path, monkeypatch, capsys) -> None:
    """An owner on the registry, asking for the roster they already subscribe
    with, after a free report this season: three refusals for anybody else,
    a report for the owner. And the owner's roster is not remembered, so it
    can never refuse a real buyer later."""
    from test_trials import _fixture_ref
    ref = _fixture_ref()
    registry = [_subscriber(OWNER, ref)]
    served = [(trials.trial_key("2025", OWNER), "2025-12-30T10:00:00+00:00")]
    code, out, mailed, reg = _drive(tmp_path, monkeypatch, capsys,
                                    rows=[_trial(OWNER, ref)], registry_rows=registry,
                                    sent=served)
    assert code == 0, out
    assert [m.to for m in mailed] == [OWNER.lower()]
    assert trials.is_owner_trial_key(mailed[0].key)
    assert not (reg.parent / trials.TRIAL_ROSTERS_NAME).exists(), "a test roster was remembered"
    assert OWNER.lower() not in out.lower() and "@" not in out
    # Mutation of the guard: with OWNER_EMAILS unset the same request is refused.
    code, out, mailed, _ = _drive(tmp_path, monkeypatch, capsys, rows=[_trial(OWNER, ref)],
                                  registry_rows=registry, sent=served, owners="")
    assert code == 0 and mailed == []
    # A buyer with the owner's roster is refused as the same team.
    code, out, mailed, _ = _drive(tmp_path, monkeypatch, capsys, rows=[_trial(BUYER, ref)],
                                  registry_rows=registry, owners="")
    assert mailed == [] and "refused" in out


def test_the_owner_never_gets_a_report_about_games_underway(
        tmp_path, monkeypatch, capsys) -> None:
    from test_trials import _fixture_ref
    code, out, mailed, _ = _drive(tmp_path, monkeypatch, capsys,
                                  rows=[_trial(OWNER, _fixture_ref())],
                                  underway=datetime(2025, 12, 31, tzinfo=timezone.utc))
    assert code == 0 and mailed == [] and "underway" in out


# --------------------------------------------------------------------- #
# left out of the numbers
# --------------------------------------------------------------------- #

ROWS = [
    {"kind": "waitlist", "email": OWNER, "received_at": "2026-11-02T05:00:00Z", "via": "x"},
    {"kind": "waitlist", "email": "Boss+2@owner-inbox.mail", "received_at": "2026-11-02T06:00:00Z"},
    {"kind": "trial", "email": OWNER_GMAIL, "ref": "r", "received_at": "2026-10-01T07:00:00Z"},
    {"kind": "waitlist", "email": BUYER, "received_at": "2026-11-02T07:00:00Z", "via": "reddit"},
    {"kind": "waitlist", "email": "t@example.com", "received_at": "2026-11-02T07:00:00Z"},
]


def test_make_stats_leaves_owner_rows_out_of_every_form_count() -> None:
    form = stats.form_summary(ROWS, NOW, OWNERS)
    assert form == {"waitlist": {"total": 1, "week": 1, "day": 0, "people": 1}}
    assert stats.channel_summary(ROWS, OWNERS) == {"waitlist": {"reddit": 1}}
    assert stats.conversions(ROWS, [OWNER, BUYER], OWNERS) == {"waitlist": (1, 1)}
    assert count_not_counted(ROWS, OWNERS) == 4
    assert stats.left_out_line(4) == ("4 owner/test rows not counted (your own addresses, "
                                      "our own domain or a reserved test domain).")
    # Without the owner list only the test domain is left out.
    assert stats.form_summary(ROWS, NOW, frozenset())["waitlist"]["total"] == 3
    assert not_counted("t@example.com") and not not_counted(BUYER, OWNERS)


def test_the_owners_free_reports_are_not_counted_as_sent() -> None:
    prefix = trials.owner_trial_prefix("2026", OWNER)
    entries = [{"key": k, "sent_at": "2026-10-06T12:00:00+00:00"} for k in (
        "trial-2026-0123456789ab", f"{prefix}0123456789", f"{prefix}abcdefabcd")]
    other = stats.send_summary(entries, "2026")["other"]
    assert other["free reports"] == 1
    assert other["free reports to your own addresses (tests, not counted above)"] == 2


def _session(i, email, ref, refunded=False):
    return {"id": f"cs_{i}", "mode": "subscription", "status": "complete",
            "payment_status": "paid", "client_reference_id": ref,
            "created": int(NOW.timestamp()) - 3600 * (i + 1), "amount_total": 1499,
            "amount_subtotal": 1499, "currency": "usd", "customer_details": {"email": email},
            "invoice": {"charge": {"id": f"ch_{i}", "refunded": refunded,
                                   "amount_refunded": 1499 if refunded else 0}}}


def _fake_stripe(monkeypatch, ref):
    """Per path: two purchases (the owner's refunded), a refund of the owner's
    charge, a subscription each, and a renewal each."""
    seen = []
    data = {
        "checkout/sessions": [_session(0, BUYER, ref), _session(1, OWNER, ref, refunded=True)],
        "refunds": [{"id": "re_1", "status": "succeeded",
                     "charge": {"billing_details": {"email": OWNER}}}],
        "subscriptions": [{"id": "sub_1", "customer": {"email": BUYER}},
                          {"id": "sub_2", "customer": {"email": OWNER_GMAIL}}],
        "invoices": [{"billing_reason": "subscription_cycle", "amount_paid": 1499,
                      "currency": "usd", "customer_email": e} for e in (BUYER, OWNER)],
    }

    def fake(path, params, key):
        seen.append((path, tuple(params)))
        return [dict(o) for o in data.get(path, [])]
    monkeypatch.setattr(stats, "_stripe_list", fake)
    return seen


def test_make_stats_leaves_the_owners_purchases_out(monkeypatch) -> None:
    from test_dashboard import _a_roster_ref
    seen = _fake_stripe(monkeypatch, _a_roster_ref())
    lines = stats.stripe_summary("rk_test", NOW, link_plans={}, owners=OWNERS, one_time=False)
    text = "\n".join(lines)
    assert "Plans sold, ever: 1 — Monthly 1" in text
    assert "Refund rate: 0% (0 of 1 refunded in full)" in text
    assert "1 purchase from your own addresses (OWNER_EMAILS) not counted." in text
    assert "Refunds, last 30 days: 0" in text
    assert f"{stats.SUBSCRIPTIONS_LABEL}: 1" in text
    assert "Monthly renewals paid: 1," in text
    assert "@" not in text
    # The customer and the refund's charge are expanded so they can be matched.
    assert ("subscriptions", (("status", "active"), ("expand[]", "data.customer"))) in seen
    assert any(p == "refunds" and ("expand[]", "data.charge") in q for p, q in seen)
    # Mutation of the guard: with no owner addresses everything counts again,
    # and no extra expansion is asked for.
    seen.clear()
    text = "\n".join(stats.stripe_summary("rk_test", NOW, link_plans={}, owners=frozenset(),
                                          one_time=False))
    assert "Plans sold, ever: 2" in text and "Refunds, last 30 days: 1" in text
    assert "not counted" not in text
    assert ("subscriptions", (("status", "active"),)) in seen


def test_free_report_to_paid_leaves_the_owners_requests_out() -> None:
    from test_dashboard import _a_roster_ref
    asked = NOW - timedelta(days=20)
    rows = [{"kind": "trial", "email": e, "received_at": asked.isoformat()}
            for e in (OWNER_GMAIL, BUYER)]
    bought = [dict(_session(0, BUYER, _a_roster_ref()),
                   created=int((asked + timedelta(days=2)).timestamp()))]
    assert stats.free_to_paid_line(rows, bought, NOW, owners=OWNERS) == \
        "  Free report → paid within 14 days: 1 of 1"
    assert stats.free_to_paid_line(rows, bought, NOW, owners=frozenset()) == \
        "  Free report → paid within 14 days: 1 of 2"


def test_make_stats_leaves_the_owners_teams_out_and_prints_no_address(
        tmp_path, monkeypatch, capsys) -> None:
    import run.delivery as delivery
    from test_trials import _fixture_ref
    from run.intake import RosterSignup, to_rows
    ref = _fixture_ref()
    registry = tmp_path / "rosters.json"
    registry.write_text(json.dumps(to_rows([
        RosterSignup(email=OWNER, ref=ref, plan="monthly", seen_at="1793000000",
                     stripe_customer_id="cus_OOOO1", subscription_id="sub_OOOO1"),
        RosterSignup(email=BUYER, ref=ref, plan="monthly", seen_at="1793000001",
                     stripe_customer_id="cus_BBBB1", subscription_id="sub_BBBB1")])))
    monkeypatch.setattr(delivery, "SENT_LOG", tmp_path / "sent.jsonl")
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert stats.main(["--registry", str(registry), "--now", NOW.isoformat()],
                      owners=OWNERS) == 0
    out = capsys.readouterr().out
    assert "1 on the registry" in out
    assert "1 team on your own addresses (OWNER_EMAILS) not counted." in out
    assert "@" not in out
    # The command line reads OWNER_EMAILS from .env like the rest.
    env = tmp_path / ".env"
    env.write_text(f"OWNER_EMAILS={OWNER}\n", encoding="utf-8")
    assert stats.cli(["--registry", str(registry), "--now", NOW.isoformat()],
                     environ={}, env_file=env) == 0
    out = capsys.readouterr().out
    assert "1 on the registry" in out and "@" not in out


def test_the_dashboard_leaves_the_owner_out_of_forms_money_and_subscribers(
        monkeypatch, tmp_path) -> None:
    import run.dashboard as dash
    import run.intake as intake
    from run.dashboard import Context
    from test_dashboard import _a_roster_ref
    monkeypatch.setattr(intake, "fetch_seats", lambda *a, **k: ROWS)
    _fake_stripe(monkeypatch, _a_roster_ref())
    env = {**ENV, "FORM_ENDPOINT": "https://w.test", "STRIPE_API_KEY": "rk_test"}
    ctx = Context(env=env, now=NOW)
    forms = dash.collect_forms(ctx)
    assert [r["kind"] for r in forms.data["rows"]] == ["waitlist"]
    assert forms.data["left_out"] == 4
    money = dash.collect_stripe(ctx)
    assert len(money.data["sessions"]) == 1 and money.data["owner_left_out"] == 1
    assert len(money.data["renewals"]) == 1
    metrics = dash.money_metrics(money, "all", NOW)
    assert metrics["count"] == 1 and metrics["full_refunds"] == 0
    # The registry: the owner's team is not a subscriber.
    from test_trials import _fixture_ref
    from run.intake import RosterSignup, to_rows
    registry = tmp_path / "rosters.json"
    registry.write_text(json.dumps(to_rows([
        RosterSignup(email=OWNER_GMAIL, ref=_fixture_ref(), plan="monthly", seen_at="1793000000",
                     stripe_customer_id="cus_OOOO1", subscription_id="sub_OOOO1")])))
    reg = dash.collect_registry(Context(env=env, now=NOW, registry=registry))
    assert reg.data["total"] == 0 and reg.data["owner_left_out"] == 1
    # Mutation of the guard: without OWNER_EMAILS they all count.
    bare = Context(env={k: v for k, v in env.items() if k != "OWNER_EMAILS"}, now=NOW)
    assert len(dash.collect_stripe(bare).data["sessions"]) == 2
    assert dash.collect_forms(bare).data["left_out"] == 1
    assert dash.collect_registry(Context(env=bare.env, now=NOW,
                                         registry=registry)).data["total"] == 1
    assert "OWNER_EMAILS" in dash.ENV_NAMES


def test_the_plan_gate_counts_no_free_report_the_owner_sent_themselves() -> None:
    import run.dashboard as dash
    from test_dashboard import rich_sources
    S = rich_sources(NOW)
    prefix = trials.owner_trial_prefix("2026", OWNER)
    stamp = NOW.isoformat()
    sends = {"season": "2026", "entries": [
        {"key": f"trial-2026-{i:012x}", "sent_at": stamp} for i in range(3)] + [
        {"key": f"{prefix}{i:010x}", "sent_at": stamp} for i in range(7)]}
    page = dash.gates_html(S, NOW, sends, None, S["registry"])
    row = next(r for r in page.split("<tr>") if "Free reports sent" in r)
    assert '<td class="num">3</td>' in row, row


def test_the_launch_checks_refund_rate_leaves_the_owners_charges_out(monkeypatch) -> None:
    import run.launch_check as lc

    def charge(email, refunded):
        return {"paid": True, "status": "succeeded", "refunded": refunded,
                "amount_refunded": 1499 if refunded else 0, "disputed": False,
                "amount": 1499, "billing_details": {"email": email}}
    charges = [charge(OWNER, True), charge(OWNER, True)] + [charge(BUYER, False)] * 18
    assert lc.audit_charge_rates(charges)[:2] == (20, 0.1)
    assert lc.audit_charge_rates(charges, OWNERS)[:2] == (18, 0.0)
    monkeypatch.setenv("STRIPE_API_KEY", "rk_test")
    monkeypatch.setattr(lc, "_stripe_charges", lambda key, days: charges + [charge(OWNER, True)])
    monkeypatch.setenv("OWNER_EMAILS", "")
    assert lc.check_refund_rates()[0].status == "WARN"
    monkeypatch.setenv("OWNER_EMAILS", OWNER)
    [gate] = lc.check_refund_rates()
    assert gate.status == "PASS" and "3 of your own charges" in gate.detail
    assert "@" not in gate.detail


def test_the_launch_email_never_goes_to_the_owner(tmp_path) -> None:
    import run.waitlist as wl
    assert wl.waitlist_addresses(ROWS, OWNERS) == [BUYER]
    assert wl.waitlist_addresses(ROWS, frozenset()) == [OWNER, BUYER]
    export = tmp_path / "list.csv"
    export.write_text(f"email\n{OWNER_GMAIL}\n{BUYER}\n", encoding="utf-8")
    addresses, problems = wl.load_list(export, OWNERS)
    assert addresses == [BUYER]
    assert problems == ["row 2: one of your own addresses (OWNER_EMAILS)"]


def test_make_signups_marks_the_owner(capsys) -> None:
    from test_signups import run
    rows = [{"kind": "waitlist", "email": OWNER, "received_at": "2026-11-02T05:02:58Z"},
            {"kind": "waitlist", "email": BUYER, "received_at": "2026-11-02T06:00:00Z"}]
    code, out = run([], capsys, rows=rows, settings=dict(ENV))[:2]
    assert code == 0
    assert next(l for l in out.splitlines() if OWNER in l).endswith("[owner]")
    assert "[owner]" not in next(l for l in out.splitlines() if BUYER in l)
    assert "1 of them is your own (OWNER_EMAILS), marked [owner] below." in out
    code, out = run([], capsys, rows=rows)[:2]
    assert "[owner]" not in out


# --------------------------------------------------------------------- #
# unchanged on purpose
# --------------------------------------------------------------------- #

@pytest.mark.parametrize("ids,entitled", [(frozenset({"sub_OOOO1"}), True), (frozenset(), False)])
def test_an_owner_address_is_entitled_only_by_a_paid_plan(tmp_path, monkeypatch, ids,
                                                         entitled) -> None:
    """A weekly report still needs a paid plan: an owner address with its
    subscription refunded or cancelled is not entitled."""
    from test_trials import _fixture_ref
    from run.intake import RosterSignup, to_rows
    from run.rosters import load_rosters
    from run.subscriptions import PaidList
    monkeypatch.setenv("OWNER_EMAILS", OWNER)
    path = tmp_path / "rosters.json"
    path.write_text(json.dumps(to_rows([RosterSignup(
        email=OWNER, ref=_fixture_ref(), plan="monthly", seen_at="1793000000",
        stripe_customer_id="cus_OOOO1", subscription_id="sub_OOOO1")])))
    paid = PaidList(emails=frozenset({OWNER}), source="stripe", status_column=None,
                    customer_ids=frozenset({"cus_OOOO1"}), subscription_ids=ids)
    assert [paid.entitles(s) for s in load_rosters(path)] == [entitled]


def test_the_owner_flag_reaches_no_published_number() -> None:
    """Nothing that records or grades a call, or builds a report, reads it."""
    root = Path(__file__).resolve().parent.parent
    for rel in ("engine", "render"):
        for path in (root / rel).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "run.owner" not in text and "OWNER_EMAILS" not in text, path
    for rel in ("run/tuesday.py", "run/saturday.py", "run/solo.py", "run/monday.py",
                "run/suppress.py", "run/billing.py", "run/subscriptions.py",
                "run/delivery.py", "run/rosters.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "run.owner" not in text and "OWNER_EMAILS" not in text, rel


def test_every_step_running_affected_code_maps_the_secret() -> None:
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    root = Path(__file__).resolve().parent.parent / ".github" / "workflows"
    found = 0
    for name in ("daily.yml", "weekly.yml"):
        doc = yaml.safe_load((root / name).read_text(encoding="utf-8"))
        for job in doc["jobs"].values():
            for step in job.get("steps") or []:
                command = "\n".join(line.split("#", 1)[0]
                                    for line in str(step.get("run", "")).splitlines())
                if any(f"-m {m}" in command for m in ("run.intake", "run.trials", "run.trades")):
                    found += 1
                    assert (step.get("env") or {}).get("OWNER_EMAILS") == \
                        "${{ secrets.OWNER_EMAILS }}", f"{name}: {step.get('name')!r}"
    assert found == 4
