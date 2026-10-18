"""The billing agent's promise fixes (Oct 18 2026): D2 entitlement per
subscription, D4 keyed codes, D5 the privacy tool, D6 the change notice, D7
Reply-To, D17 unmapped payment links, the consent record, and the launch gates.

Each test names the promise it holds true. run/billing.py's D1 tests live in
tests/test_billing.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import run.intake as intake
from run.delivery import DryRunProvider, Message, send_all
from run.refs import encode_roster
from run.rosters import RosterRegistryError, RosterSubscriber, _parse_entry
from run.subscriptions import PaidList

from test_solo_run import SLOTS, _pid

PLAYERS = [_pid(i) for i in range(1, 9)]
REF = encode_roster("season", "ppr", list(SLOTS), PLAYERS)
REF_B = encode_roster("season", "ppr", list(SLOTS), [_pid(i) for i in range(2, 10)])


def _row(**over) -> RosterSubscriber:
    base = dict(email="fan@example.com", ref=REF, player_ids=tuple(PLAYERS),
                slots=tuple(SLOTS), scoring="ppr", stripe_customer_id="cus_aaaa1111")
    base.update(over)
    return RosterSubscriber(**base)


def _paid(**over) -> PaidList:
    base = dict(emails=frozenset({"fan@example.com"}), source="stripe",
                status_column=None, customer_ids=frozenset({"cus_bbbb2222"}),
                subscription_ids=frozenset({"sub_bbbb2222"}))
    base.update(over)
    return PaidList(**base)


# --------------------------------------------------------------------- #
# D2 — reports follow the row's own subscription
# --------------------------------------------------------------------- #

def test_a_cancelled_team_stops_while_the_same_address_pays_for_another() -> None:
    """LEGAL-41 / LANDING-86, reproduced: team A's subscription ended, team B's
    is live on the same address, and team A's reports kept coming through the
    email route — "then they stop on their own" was false."""
    paid = _paid()
    team_a = _row(subscription_ids=("sub_aaaa1111",))
    team_b = _row(ref=REF_B, stripe_customer_id="cus_bbbb2222",
                  subscription_ids=("sub_bbbb2222",))
    assert not paid.entitles(team_a), "a cancelled subscription kept its reports"
    assert paid.entitles(team_b)


def test_a_merged_row_is_served_while_any_of_its_subscriptions_is() -> None:
    row = _row(subscription_ids=("sub_aaaa1111", "sub_bbbb2222"))
    assert _paid().entitles(row)


def test_rows_without_a_subscription_still_use_the_old_routes() -> None:
    """Hand-added rows and the CSV path name no subscription."""
    assert _paid().entitles(_row(stripe_customer_id="cus_bbbb2222"))
    assert _paid(subscription_ids=None).entitles(_row(subscription_ids=("sub_x1234",)))


def test_the_registry_carries_and_checks_the_subscription_ids() -> None:
    raw = {"email": "fan@example.com", "ref": REF, "player_ids": PLAYERS,
           "slots": list(SLOTS), "scoring": "ppr", "plan": "season",
           "subscription_ids": ["sub_aaaa1111"]}
    assert _parse_entry(raw, 0).subscription_ids == ("sub_aaaa1111",)
    with pytest.raises(RosterRegistryError):
        _parse_entry({**raw, "subscription_ids": ["cus_nope"]}, 0)


def test_intake_stamps_every_paid_row_with_its_subscriptions() -> None:
    one = intake.RosterSignup(email="fan@example.com", ref=REF, plan="season",
                              seen_at="1792087200", subscription_id="sub_aaaa1111")
    two = intake.RosterSignup(email="fan@example.com",
                              ref=encode_roster("monthly", "ppr", list(SLOTS), PLAYERS),
                              plan="monthly", seen_at="1792090000",
                              subscription_id="sub_bbbb2222")
    [row] = intake.to_rows(intake.merge_same_roster([one, two]).signups)
    assert row["subscription_ids"] == ["sub_aaaa1111", "sub_bbbb2222"]
    [alone] = intake.to_rows([one])
    assert alone["subscription_ids"] == ["sub_aaaa1111"]


# --------------------------------------------------------------------- #
# D4 — keyed codes, never a plain hash of an address
# --------------------------------------------------------------------- #

def _plain(email: str, n: int) -> str:
    return hashlib.sha256(email.encode()).hexdigest()[:n]


def test_every_address_code_in_the_public_logs_is_keyed(monkeypatch) -> None:
    """LEGAL-89/103/117: a plain sha256 of an address lets anybody who knows it
    test membership. Every code must change when the key does."""
    from run import suppress, trials, updates, waitlist
    from run.renewals import notice_key
    from render.renewal import Renewal

    email = "fan@example.com"
    request = updates.PendingRequest(email=email, replaces="0123456789", ref=REF,
                                     code="c" * 24, ts="2026-10-18T00:00:00Z")
    renewal = Renewal(email=email, amount="$39.00 USD", renews_on=date(2027, 9, 1),
                      interval="year")

    def codes() -> list[str]:
        return [suppress.address_digest(email), trials.trial_key("2026", email),
                waitlist.messages([email], "https://example.com/join/")[0].key,
                intake.unmatched_key({"email": email, "received_at": "x"}),
                intake.full_key({"email": email, "received_at": "x"}),
                notice_key(renewal), updates.confirmation_key(request)]

    monkeypatch.setenv("LOG_SECRET", "one")
    first = codes()
    monkeypatch.setenv("LOG_SECRET", "two")
    second = codes()
    for a, b in zip(first, second):
        assert a != b, f"{a} does not depend on LOG_SECRET"
    canon = "fan@example.com"
    for code in first:
        for n in (8, 10, 12):
            assert _plain(canon, n) not in code, f"{code} carries a plain hash"


def test_no_key_means_no_code_and_no_real_send(monkeypatch, tmp_path) -> None:
    from run.digest import DigestError, address
    monkeypatch.delenv("LOG_SECRET", raising=False)
    with pytest.raises(DigestError):
        address("fan@example.com")

    class Real(DryRunProvider):
        name = "resend"

    sent = send_all([Message(to="fan@example.com", subject="s", html="<p>x</p>",
                             text="x", key="k1")], provider=Real(tmp_path),
                    sent_log=tmp_path / "sent.jsonl",
                    suppress_file=tmp_path / "none.txt")
    assert not sent[0].ok and "LOG_SECRET" in sent[0].detail
    # A dry preview with an empty stop list checks nothing and still drafts.
    dry = send_all([Message(to="fan@example.com", subject="s", html="<p>x</p>",
                            text="x", key="k2")], provider=DryRunProvider(tmp_path),
                   sent_log=tmp_path / "sent.jsonl", suppress_file=tmp_path / "none.txt")
    assert dry[0].ok


# --------------------------------------------------------------------- #
# D7 — a reply reaches hello@
# --------------------------------------------------------------------- #

def test_every_email_carries_reply_to_hello_when_none_is_set(monkeypatch, tmp_path) -> None:
    """EMAILS-135, LEGAL-49: "reply stop" went to reports@, which nobody reads."""
    monkeypatch.delenv("EMAIL_REPLY_TO", raising=False)
    send_all([Message(to="fan@example.com", subject="s", html="<p>x</p>", text="x",
                      key="k")], provider=DryRunProvider(tmp_path),
             sent_log=tmp_path / "sent.jsonl", suppress_file=tmp_path / "none.txt")
    [draft] = list(tmp_path.glob("*.eml"))
    assert "Reply-To: hello@beatyourleague.com" in draft.read_text()


# --------------------------------------------------------------------- #
# D17 and the consent record
# --------------------------------------------------------------------- #

def _session(link: str | None = "plink_S", **over) -> dict:
    row = {"id": "cs_1", "created": 1792087200, "payment_status": "paid",
           "status": "complete", "client_reference_id": REF, "payment_link": link,
           "customer": {"id": "cus_aaaa1111", "email": "fan@example.com", "metadata": {}},
           "customer_details": {"email": "fan@example.com"}, "subscription": "sub_aaaa1111"}
    row.update(over)
    return row


def _sweep(monkeypatch, sessions, plans=None):
    monkeypatch.setattr(intake, "sweep_sessions", lambda *a, **k: (sessions, 1))
    return intake.sweep("sk_test", None, plans if plans is not None else
                        {"plink_S": "season", "plink_M": "monthly"}, promote=False)


def test_an_unmapped_payment_link_is_unattributed_never_a_season_pass(monkeypatch) -> None:
    """LEGAL-6 / JOIN-161: `plan or "season"` welcomed a $14.99 monthly buyer
    on an unmapped link with $39 yearly terms."""
    signups, _, problems = _sweep(monkeypatch, [_session(link="plink_OLD")])
    assert signups == []
    assert any(p.startswith("PAID-UNATTRIBUTED") for p in problems)
    signups, _, problems = _sweep(monkeypatch, [_session()], plans={})
    assert signups == [] and "STRIPE_PAYMENT_LINKS is not set" in problems[0]
    signups, _, _ = _sweep(monkeypatch, [_session(link="plink_M")])
    assert [s.plan for s in signups] == ["monthly"]


def test_a_forgotten_customer_is_never_re_read(monkeypatch, tmp_path) -> None:
    import run.privacy as privacy
    path = tmp_path / "forgotten.txt"
    path.write_text(privacy.forgotten_code("cus_aaaa1111") + "\n")
    monkeypatch.setattr(privacy, "FORGOTTEN_FILE", path)
    signups, _, problems = _sweep(monkeypatch, [_session()])
    assert signups == [] and problems == []


def test_consent_records_the_version_in_force_at_checkout_and_never_moves() -> None:
    """LEGAL-100/144, reproduced: a re-sweep after a terms change rewrote a
    buyer's recorded version to one that did not exist when they ticked."""
    oct16 = int(datetime(2026, 10, 16, 18, tzinfo=timezone.utc).timestamp())
    record = intake._consent(_session(created=oct16, consent={"terms_of_service": "accepted"}))
    assert record["byl_terms_version"] == "2026-10-15"
    assert record["byl_terms_accepted_at"] == str(oct16)
    held = _session(created=oct16, consent={"terms_of_service": "accepted"})
    held["customer"]["metadata"] = {"byl_terms_accepted": "yes",
                                    "byl_terms_version": "2026-10-15"}
    assert intake._consent(held) == {}, "an existing consent record was rewritten"


def test_the_current_terms_version_is_in_the_history() -> None:
    from render.welcome import TERMS_VERSION
    assert TERMS_VERSION in intake.TERMS_HISTORY
    assert list(intake.TERMS_HISTORY) == sorted(intake.TERMS_HISTORY)


# --------------------------------------------------------------------- #
# D5 — the privacy tool
# --------------------------------------------------------------------- #

def _registry(tmp_path: Path) -> Path:
    reg = tmp_path / "registry"
    reg.mkdir()
    them = {"email": "Fan@Example.com", "ref": REF, "plan": "season", "seen_at": "1",
            "stripe_customer_id": "cus_aaaa1111"}
    other = {"email": "other@example.com", "ref": REF_B, "plan": "season", "seen_at": "2"}
    (reg / intake.SIGNUP_LOG_NAME).write_text(
        "".join(json.dumps(r) + "\n" for r in (them, other)))
    (reg / intake.REGISTRY_NAME).write_text(json.dumps([
        {**them, "player_ids": PLAYERS, "slots": list(SLOTS), "scoring": "ppr"},
        {**other, "player_ids": PLAYERS, "slots": list(SLOTS), "scoring": "ppr"}]))
    slug = hashlib.sha256(REF.encode()).hexdigest()[:10]
    plans = tmp_path / "plans" / "2026"
    plans.mkdir(parents=True)
    (plans / f"w06-{slug}.json").write_text("{}")
    (plans / "w06-ffffffffff.json").write_text("{}")
    return reg


def test_delete_removes_one_person_and_nobody_else(tmp_path, monkeypatch) -> None:
    """LEGAL-128/130/133: no deletion path existed for the cached registry."""
    import run.privacy as privacy
    from run.digest import address
    from run.suppress import add, load_suppressed
    reg = _registry(tmp_path)
    stop = tmp_path / "suppressed.txt"
    add(["fan@example.com", "other@example.com"], stop)
    code = address("fan@example.com")
    found = privacy.find(code, reg, [tmp_path / "plans"], stop,
                         worker_rows=[{"email": "FAN@example.com", "kind": "trial"}])
    counts = found.counts()
    assert counts["signups"] == 1 and counts["registry rows"] == 1
    assert counts["stored weekly plans"] == 1 and counts["form rows"] == 1
    assert counts["on the stop list"] == 1
    done = privacy.forget(code, found, reg, stop, tmp_path / "forgotten.txt")
    assert done["signups"] == 1 and done["registry rows"] == 1
    left = privacy.find(code, reg, [tmp_path / "plans"], stop)
    assert all(v == 0 for k, v in left.counts().items()), left.counts()
    assert "other@example.com" in (reg / intake.SIGNUP_LOG_NAME).read_text()
    assert len(load_suppressed(stop)) == 1
    assert privacy.load_forgotten(tmp_path / "forgotten.txt") == {privacy.forgotten_code("cus_aaaa1111")}
    assert "cus_aaaa1111" not in (tmp_path / "forgotten.txt").read_text()
    assert (tmp_path / "plans" / "2026" / "w06-ffffffffff.json").exists()


def test_the_privacy_tool_takes_a_code_never_an_address(monkeypatch, capsys) -> None:
    import run.privacy as privacy
    assert privacy.main(["show", "fan@example.com"]) == 2
    assert "fan@example.com" not in capsys.readouterr().err
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert privacy.main(["code", "fan@example.com"]) == 2


def test_results_never_go_to_the_log(monkeypatch, tmp_path, capsys) -> None:
    import run.privacy as privacy
    from run.digest import address
    reg = _registry(tmp_path)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("FORM_ENDPOINT", raising=False)
    code = address("fan@example.com")
    assert privacy.main(["export", code, "--send", "--registry-dir", str(reg),
                         "--plans-dir", str(tmp_path / "plans")]) == 1
    out = capsys.readouterr()
    assert "example.com" not in out.out + out.err
    assert "NOT DONE" in out.err


# --------------------------------------------------------------------- #
# D6 — the change notice
# --------------------------------------------------------------------- #

def test_a_notice_goes_before_the_change_never_after(capsys) -> None:
    from run import notice
    assert notice.main(["--page", "terms", "--effective", "2026-10-18",
                        "--summary", "x", "--today", "2026-10-18"]) == 2


def test_one_notice_per_entitled_mailbox_with_a_way_out(monkeypatch) -> None:
    from run import notice
    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/test")
    rows = [_row(subscription_ids=("sub_bbbb2222",)),
            _row(email="Fan+2@Example.com", subscription_ids=("sub_bbbb2222",)),
            _row(email="gone@example.com", subscription_ids=("sub_gone1111",))]
    people = notice.recipients(rows, _paid())
    assert [p.email for p in people] == ["fan@example.com"]
    message = notice.notice_message(people[0], "terms", date(2026, 11, 1),
                                    "Refunds now cover two weekly reports.",
                                    "https://beatyourleague.com")
    assert message.key.startswith("notice-terms-2026-11-01-")
    assert "example.com" not in message.key
    assert "terms.html" in message.text and "November 1, 2026" in message.subject
    assert message.unsubscribe


# --------------------------------------------------------------------- #
# launch gates and workflows
# --------------------------------------------------------------------- #

def test_the_portal_audit_wants_period_end_and_no_reason() -> None:
    from run.launch_check import audit_portal
    good = {"features": {"subscription_cancel": {
        "enabled": True, "mode": "at_period_end", "proration_behavior": "none",
        "cancellation_reason": {"enabled": False}}}}
    assert audit_portal(good) == []
    asked = json.loads(json.dumps(good))
    asked["features"]["subscription_cancel"]["cancellation_reason"]["enabled"] = True
    assert any("asks why" in p for p in audit_portal(asked))
    now = json.loads(json.dumps(good))
    now["features"]["subscription_cancel"]["mode"] = "immediately"
    assert audit_portal(now)


def test_every_step_that_can_mail_has_the_log_key() -> None:
    yaml = pytest.importorskip("yaml")
    root = Path(__file__).resolve().parent.parent / ".github" / "workflows"
    found = 0
    for path in root.glob("*.yml"):
        for job in (yaml.safe_load(path.read_text())["jobs"] or {}).values():
            for step in job.get("steps") or []:
                env = step.get("env") or {}
                if "EMAIL_PROVIDER" in env:
                    found += 1
                    assert env.get("LOG_SECRET") == "${{ secrets.LOG_SECRET }}", \
                        f"{path.name}: {step.get('name')!r} cannot key a send"
    assert found >= 7


def test_the_privacy_workflow_is_fed_a_code_and_never_runs_beside_the_sweep() -> None:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((Path(__file__).resolve().parent.parent / ".github" / "workflows"
                          / "privacy.yml").read_text())
    assert doc["concurrency"]["group"] == "daily-intake"
    inputs = doc[True]["workflow_dispatch"]["inputs"]
    assert "never an address" in inputs["code"]["description"]


@pytest.fixture
def site(tmp_path, monkeypatch):
    import shutil
    import run.launch_check as lc
    copy = tmp_path / "site"
    shutil.copytree(Path(__file__).resolve().parent.parent / "site", copy)
    monkeypatch.setattr(lc, "SITE", copy)
    return copy


def _set(page: Path, old: str, new: str) -> None:
    text = page.read_text()
    assert old in text, old
    page.write_text(text.replace(old, new))


def _gate(gates, part):
    hits = [g for g in gates if part.lower() in g.name.lower()]
    assert hits, [g.name for g in gates]
    return hits[0].status


def test_the_launch_gates_this_round_added(site, monkeypatch) -> None:
    """JOIN-151/152 (confirm page posts nowhere), INFO-64 (the pass "opens the
    day seats can be claimed"), D4 (no LOG_SECRET while selling) and
    JOIN-161/169 (late crons while selling) — each FAILs only when it should."""
    import run.launch_check as lc
    worker = "https://forms.beatyourleague.com"
    _set(site / "join/index.html", 'const FORM_ENDPOINT = "";',
         f'const FORM_ENDPOINT = "{worker}";')
    assert _gate(lc.check_funnel_config(), "confirm page posts") == "FAIL"
    _set(site / "join/confirm.html", 'const FORM_ENDPOINT = "";',
         f'const FORM_ENDPOINT = "{worker}";')
    assert _gate(lc.check_funnel_config(), "confirm page posts") == "PASS"

    assert _gate(lc.check_funnel_config(), "opens the day seats") == "PASS"
    _set(site / "index.html", "const CHECKOUT_OPEN = false;", "const CHECKOUT_OPEN = true;")
    _set(site / "join/index.html", 'const STRIPE_LINK_PASS = "";',
         'const STRIPE_LINK_PASS = "https://buy.stripe.com/x";')
    assert _gate(lc.check_funnel_config(), "opens the day seats") == "FAIL"

    assert [g.status for g in lc.log_secret_gate({"EMAIL_PROVIDER"})] == ["FAIL"]
    assert [g.status for g in lc.log_secret_gate({"LOG_SECRET"})] == ["PASS"]

    late = {"late": ["weekly.yml Oct 13 5h late"], "ok": [], "daily": []}
    monkeypatch.setattr(lc, "_runs", lambda w: [])
    monkeypatch.setattr(lc, "audit_cron_runs", lambda runs, now: late)
    assert lc.check_cron_timing()[0].status == "FAIL"
    _set(site / "index.html", "const CHECKOUT_OPEN = true;", "const CHECKOUT_OPEN = false;")
    assert lc.check_cron_timing()[0].status == "WARN"
    assert lc.log_secret_gate({"EMAIL_PROVIDER"}) == []
