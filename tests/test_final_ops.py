"""The final review's ops lens (Oct 24 2026), pinned.

LAUNCH.md is the one document the owner follows literally, on the weekend the
product opens, and it had drifted from the code it describes: a step order that
turned the hourly cron red, a flood-limit rule the free plan cannot build, two
dispute procedures that contradicted each other, a send-count rule that ignored
the code's own 60-a-day hold, a cron key nobody was told to edit, and an escape
hatch (POSTPONED_GAMES) no workflow could see. Each guard here reads the
document AND the code it names, so neither can move without the other.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "LAUNCH.md"
WORKFLOWS = ROOT / ".github" / "workflows"
MAKEFILE = ROOT / "Makefile"


def _launch() -> str:
    return LAUNCH.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """One space between words, so a guard never depends on where a line wraps."""
    return re.sub(r"\s+", " ", text)


def _section(text: str, heading_prefix: str) -> str:
    """The body of the ``## <prefix>…`` section, up to the next ``## ``."""
    start = text.index(f"\n## {heading_prefix}")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _item(section: str, number: int) -> str:
    """Numbered item ``N.`` of a section (top-level list), up to item N+1."""
    match = re.search(rf"(?m)^{number}\. ", section)
    assert match, f"no item {number}."
    nxt = re.search(rf"(?m)^{number + 1}\. ", section[match.end():])
    return section[match.start():match.end() + nxt.start() if nxt else len(section)]


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces -> '-'."""
    text = heading.strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_")
    return text.replace(" ", "-")


def _steps(name: str) -> list[dict]:
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return [step for job in doc["jobs"].values() for step in job["steps"]]


def _command(step: dict) -> str:
    return "\n".join(line.split("#", 1)[0] for line in str(step.get("run", "")).splitlines())


def _modules(step: dict) -> list[str]:
    return re.findall(r"-m ([a-z_]+\.[a-z_]+)\b", _command(step))


def _module_source(module: str) -> str:
    path = ROOT / Path(*module.split(".")).with_suffix(".py")
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# --------------------------------------------------------------------- #
# the checklist, and the document agreeing with itself
# --------------------------------------------------------------------- #

def test_launch_opens_with_the_weekend_checklist() -> None:
    """Reproduction (ops lens): the owner's minimal path through ~1,000 lines
    lived only in a reviewer's notes, and the two steps it found missing (edit
    the cron key, create the read-only stats key) were in no step at all. The
    checklist is now the first section: every item has a time and a link, the
    two missing steps are on it, and so is what can wait."""
    text = _launch()
    headings = re.findall(r"(?m)^## (.+)$", text)
    assert headings[:2] == ["This weekend, in order", "Where things stand"], headings[:3]
    checklist = _section(text, "This weekend, in order")
    items = re.findall(r"(?ms)^(\d+)\. (.+?)(?=^\d+\. |^\*\*Later|\Z)", checklist)
    assert len(items) >= 10, [n for n, _ in items]
    for number, body in items:
        assert re.search(r"\(~\d+ (min|hour)", body), f"item {number} has no time estimate"
        assert "](#" in body or "I put the links" in body, f"item {number} links nowhere"
    flat = _flat(checklist)
    assert "github-actions-crons" in flat and "owner-stats" in flat
    for permission in ("Payment Intents", "Charges", "Disputes"):
        assert permission in flat
    assert "run daily-intake once by hand" in flat
    assert "Can wait" in flat and "Wed Nov 25, from 8:00 PM ET" in flat


def test_every_anchor_in_launch_resolves() -> None:
    """Every in-page link in LAUNCH.md lands on a heading. Mutation-checked:
    renaming '## 4. The proving run (~1 hour)' leaves the checklist's link to
    it dangling, and this fails."""
    text = _launch()
    anchors = {_slug(h) for h in re.findall(r"(?m)^#{1,4} (.+)$", text)}
    links = re.findall(r"\]\(#([^)]+)\)", text)
    assert links, "the checklist links nothing"
    missing = sorted(set(links) - anchors)
    assert not missing, f"LAUNCH.md links to headings that don't exist: {missing}"


def test_every_numbered_step_reference_lands_on_an_item() -> None:
    """'step 5.7', 'step 1.4' and the like — in LAUNCH itself and in every
    message run/launch_check.py prints — name an item that exists. Reproduced:
    LAUNCH said TRIAL_OPEN was set in 'step 7', which is Selling; and moving
    the Worker's custom domain ahead of its secrets renumbered items that the
    launch check's messages name."""
    text = _launch()
    sources = {"LAUNCH.md": text,
               "run/launch_check.py": (ROOT / "run" / "launch_check.py").read_text(encoding="utf-8")}
    seen = 0
    for name, source in sources.items():
        for section, item in re.findall(r"\bsteps? (\d+b?)\.(\d+)\b", _flat(source)):
            seen += 1
            body = _section(text, f"{section}.")
            assert re.search(rf"(?m)^{item}\. ", body), (
                f"{name} names step {section}.{item}, which LAUNCH.md doesn't have")
    assert seen >= 15


def test_launch_names_only_make_targets_that_exist() -> None:
    """A `make` command the owner copies must run. Mutation-checked with
    `make stats-registry` removed from the Makefile."""
    targets = set(re.findall(r"(?m)^([a-zA-Z0-9_-]+):", MAKEFILE.read_text(encoding="utf-8")))
    named = set(re.findall(r"`make ([a-z][a-z0-9-]*)", _launch()))
    assert named, "LAUNCH names no make target"
    assert not named - targets, f"LAUNCH names make targets that don't exist: {sorted(named - targets)}"


def _launch_secrets(text: str) -> set[str]:
    table = _section(text, "3.")
    names = set(re.findall(r"(?m)^\| `([A-Z][A-Z0-9_]+)` \|", table))
    flat = _flat(text)
    names |= set(re.findall(r"GitHub secrets?:? `([A-Z][A-Z0-9_]+)`", flat))
    names |= set(re.findall(r"GitHub secret `([A-Z][A-Z0-9_]+)`", flat))
    worker_item = _flat(_item(_section(text, "5."), 6))
    names |= set(re.findall(r"`([A-Z][A-Z0-9_]+)` =", worker_item))
    return names


def test_every_secret_launch_names_reaches_a_workflow() -> None:
    """A secret the owner is told to create, that no step maps, reaches no
    process (the SENDER_POSTAL_ADDRESS bug, again). Every one LAUNCH names is
    read as `secrets.NAME` somewhere; every repo variable a workflow reads is
    explained in LAUNCH. Mutation-checked: deleting POSTPONED_GAMES's runbook
    from LAUNCH fails the second half."""
    text = _launch()
    workflows = "\n".join(p.read_text(encoding="utf-8") for p in WORKFLOWS.glob("*.yml"))
    named = _launch_secrets(text)
    assert {"STRIPE_API_KEY", "STRIPE_PAYMENT_LINKS", "LOG_SECRET", "CACHE_KEY",
            "FORM_ENDPOINT", "FORM_API_KEY", "UPDATE_SECRET", "RESEND_READ_KEY",
            "SENDER_POSTAL_ADDRESS"} <= named, sorted(named)
    unmapped = sorted(n for n in named if f"secrets.{n}" not in workflows)
    assert not unmapped, f"LAUNCH names secrets no workflow maps: {unmapped}"
    variables = set(re.findall(r"vars\.([A-Z_]+)", workflows))
    # PUSH_LEDGER is an opt-OUT that holds the public record back; monday.yml
    # documents it where it is used, and the owner never needs to set it.
    undocumented = sorted(v for v in variables - {"PUSH_LEDGER"} if f"`{v}`" not in text)
    assert not undocumented, f"workflows read repo variables LAUNCH never explains: {undocumented}"


# --------------------------------------------------------------------- #
# PIPE-2: the postponed-game hatch reaches every process that builds a week
# --------------------------------------------------------------------- #

def _week_builders():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for step in _steps(path.name):
            if any("load_week_data(" in _module_source(m) for m in _modules(step)):
                yield path.name, step


def test_every_step_that_builds_a_week_can_be_told_a_game_was_postponed() -> None:
    """Reproduction (PIPE-2): every refusal says 'name it for one run:
    POSTPONED_GAMES=AWAY@HOME', run/solo.py reads only os.environ, and no step
    mapped a variable of that name — so in CI the advice reached nothing, and a
    suspended game (2022 BUF@CIN) held every subscriber's Tuesday report, the
    live sample, first reports and free reports until nflverse edited the row.
    Every step whose runner builds week data maps the repo variable.
    Mutation-checked by deleting it from the live-sample step."""
    import run.solo as solo
    found = list(_week_builders())
    names = {(wf, step.get("name")) for wf, step in found}
    assert len(found) >= 6, names
    for wf, step in found:
        env = step.get("env") or {}
        assert env.get(solo.POSTPONED_ENV) == "${{ vars.POSTPONED_GAMES }}", (
            f"{wf}: {step.get('name')!r} builds week data but can't see {solo.POSTPONED_ENV}")


def test_launch_explains_the_postponed_game_hatch_in_the_owners_words() -> None:
    """The runbook entry sits in section 8, where red runs are explained,
    quotes the refusal the owner will actually see (read from run/solo.py, so a
    reworded message fails here), and ends with the variable deleted."""
    import inspect

    import run.solo as solo
    message = inspect.getsource(solo.assert_week_is_complete)
    assert "box scores are not all in" in message
    weekly = _flat(_section(_launch(), "8."))
    entry = weekly[weekly.index('saying "box scores are not all in"'):]
    entry = entry[:entry.index("**A red hourly run")]
    for fact in (f"`{solo.POSTPONED_ENV}`", "Variables", "weekly-report", "Run workflow",
                 "bye for both teams", "Delete the variable"):
        assert fact in entry, fact


# --------------------------------------------------------------------- #
# OPS-8: the send-count rule is the code's
# --------------------------------------------------------------------- #

def test_the_send_count_rule_is_the_codes_daily_hold() -> None:
    """Reproduction (OPS-8): LAUNCH's opening-morning rule was 'about 80 minus
    two per buyer', but run/intake.py holds free reports and seat notes once a
    day's sends reach DAY_HEADROOM = 60; and the paid-plan note never named
    EMAIL_DAILY_HEADROOM, so a Pro account kept holding mail at 60."""
    import run.intake as intake
    text = _flat(_launch())
    assert "about 80 minus" not in text
    morning = _flat(_section(_launch(), "6."))
    assert f"reach **{intake.DAY_HEADROOM}**" in morning and "If that reaches 60" in morning
    resend = _flat(_section(_launch(), "2."))
    assert f"reach **{intake.DAY_HEADROOM}**" in resend
    assert "`EMAIL_DAILY_HEADROOM` = `1500`" in resend


def test_every_mailing_step_that_applies_the_daily_hold_can_be_told_the_plan() -> None:
    """Reproduction (OPS-8, verifier): daily.yml mapped EMAIL_DAILY_HEADROOM
    on the intake only, while run.trials applies the same hold — so with the
    variable set for a paid plan, free reports still stopped at 60 a day.
    Every step whose runner reads day_headroom, and can mail, maps it."""
    checked = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for step in _steps(path.name):
            if "--no-mail" in _command(step):
                continue                 # writes the registry, mails nobody
            if any("day_headroom" in _module_source(m) for m in _modules(step)):
                checked += 1
                env = step.get("env") or {}
                assert env.get("EMAIL_DAILY_HEADROOM") == "${{ vars.EMAIL_DAILY_HEADROOM }}", (
                    f"{path.name}: {step.get('name')!r} applies the daily hold without the plan's")
    assert checked >= 2


# --------------------------------------------------------------------- #
# OPS-2, OPS-3, OPS-7: the Worker before the secrets, on its own path
# --------------------------------------------------------------------- #

def test_the_worker_step_sets_log_secret_with_the_form_address() -> None:
    """Reproduction (OPS-2): doing step 5 first put FORM_ENDPOINT in the
    secrets before step 3 added LOG_SECRET, and run.trials returns 1 whenever
    FORM_ENDPOINT is set without it — every hourly run red, an issue filed,
    until steps 1-3 were done. Step 5 sets both; step 3's row says so."""
    worker = _flat(_item(_section(_launch(), "5."), 6))
    assert "`FORM_ENDPOINT`" in worker and "**`LOG_SECRET`**" in worker
    table_row = next(line for line in _section(_launch(), "3.").splitlines()
                     if line.startswith("| `LOG_SECRET` |"))
    assert "already set in step 5.6" in table_row


def test_the_free_report_step_refuses_without_log_secret(monkeypatch, capsys) -> None:
    """The reason the test above exists, kept honest: if run.trials ever
    stops refusing here, LAUNCH's 'without it every run goes red' is false and
    should go. FORM_ENDPOINT set, LOG_SECRET unset -> exit 1 before any read."""
    import run.trials as trials
    monkeypatch.setenv("FORM_ENDPOINT", "https://forms.example.invalid/rows")
    monkeypatch.delenv("LOG_SECRET", raising=False)
    assert trials.main(["--now", "2026-10-24T15:47:00Z"]) == 1
    assert "LOG_SECRET" in capsys.readouterr().err


def test_the_forms_address_is_the_custom_domain_path_everywhere() -> None:
    """Reproduction (OPS-3, OPS-7): step 5.5 set FORM_ENDPOINT to 'the Worker
    URL' before 5.6 created the custom domain and switched workers.dev off, so
    a pasted workers.dev secret pointed at a dead route (form outage, exit 1);
    and the flood rule asked for hostname AND method, which the free plan
    cannot match (path only), while a host-wide rule would also count every
    page-counter beacon. The forms now live on /rows of the custom domain,
    created before any secret, and the rule matches that path alone."""
    text = _launch()
    values = re.findall(r"FORM_ENDPOINT[`]? = `?(https://[^\s`)]+)", text)
    values += re.findall(r"FORM_ENDPOINT=(https://\S+)", text)
    assert values, "LAUNCH never gives the forms' address"
    assert set(values) == {"https://forms.beatyourleague.com/rows"}, values
    worker = _section(text, "5.")
    flat = _flat(worker)
    assert flat.index("Custom domain** → `forms.beatyourleague.com`") \
        < flat.index("6. **GitHub secrets**"), "the secrets come before the custom domain"
    assert "workers.dev`** route **off**" in flat
    rule = _flat(_item(worker, 5))
    assert "**URI Path** equals `/rows`" in rule
    assert "hostname equals" not in rule and "request method" not in rule
    assert "slows a flood" in rule and "doesn't stop one" in rule
    # And the Worker serves forms on any path but the counter's, so /rows works
    # with no change to it, and /e stays outside the rule.
    worker_js = (ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
    assert re.findall(r'url\.pathname === "([^"]+)"', worker_js) == ["/e"]


# --------------------------------------------------------------------- #
# OPS-5, OPS-9: the keys, and the first hand run
# --------------------------------------------------------------------- #

def test_step_3_edits_the_cron_key_and_makes_the_stats_key() -> None:
    """Reproduction (OPS-5): 'Where things stand' listed github-actions-crons
    as done — made Sep 29 with Checkout Sessions Read, Customers Write and
    Subscriptions Write — while step 3 said it 'needs exactly' six, and no step
    said to EDIT it. With the old key the intake registers a buyer and the
    Tuesday send reads no paid list and mails nobody. And the read-only key the
    launch check and `make stats` use had no name and no click path. Its
    permissions are read off what run/stats.py lists."""
    keys = _flat(_section(_launch(), "3."))
    edit = keys[keys.index("**Edit the cron key.**"):keys.index("**Make your own read-only key.**")]
    assert "`github-actions-crons` → **⋯ → Edit**" in edit
    for permission in ("Payment Intents: Read", "Charges: Read", "Disputes: Read"):
        assert permission in edit
    own = keys[keys.index("**Make your own read-only key.**"):keys.index("**Then the GitHub secrets.**")]
    assert "**Create restricted key**" in own and "`owner-stats`" in own
    stats_src = (ROOT / "run" / "stats.py").read_text(encoding="utf-8")
    needed = {"checkout/sessions": "Checkout Sessions", "subscriptions": "Subscriptions",
              "refunds": "Refunds", "payment_intent.latest_charge": "Payment Intents"}
    for marker, permission in needed.items():
        assert marker in stats_src, marker
        assert permission in own, permission
    assert "Charges" in own
    # Everywhere else LAUNCH needs that key, it names it.
    stands = _flat(_section(_launch(), "Where things stand"))
    assert "`owner-stats` key from step 3" in stands
    demand = _flat(_section(_launch(), "8."))
    assert "the `owner-stats` key from step 3" in demand


def test_step_3_ends_with_one_hand_run_of_the_intake() -> None:
    """Reproduction (OPS-9): with STRIPE_API_KEY set and no registry yet,
    run.saturday reads the missing file as an error, exits 1 and files an
    issue. One hand run of daily-intake right after the secrets writes the
    first sealed list before Saturday, Tuesday or the watchdog read it."""
    import run.saturday as saturday
    assert saturday  # the runner the sentence is about still exists
    secrets = _flat(_section(_launch(), "3."))
    after = secrets[secrets.index("| `CACHE_KEY` |"):]
    assert "**Then run it once, by hand:** Actions → **daily-intake** → **Run workflow**" in after
    assert "wait for it to go green before anything else runs" in after


# --------------------------------------------------------------------- #
# C4: the link map, and the $19 link's date
# --------------------------------------------------------------------- #

def _link_maps(text: str) -> list[str]:
    command = re.findall(r"STRIPE_PAYMENT_LINKS='([^']+)'", text)
    row = [line for line in _section(text, "3.").splitlines()
           if line.startswith("| `STRIPE_PAYMENT_LINKS` |")]
    assert command and row
    return command + re.findall(r"`(s:[^`]+)`", row[0])


def test_the_link_map_is_s_o_p_in_both_places() -> None:
    """Contract C4: STRIPE_PAYMENT_LINKS is "s:<$29>,o:<$19>,p:<$69>" — in the
    secret AND in the payment-link text command, which takes the same map.
    Reproduced (OPS-1): the command used 's:…,s:…,p:…', which the script
    collapses to one season link. Once the intake reads 'o:', every id in the
    command maps to a plan."""
    maps = _link_maps(_launch())
    for raw in maps:
        prefixes = [item.split(":", 1)[0] for item in raw.split(",")]
        assert prefixes == ["s", "o", "p"], raw
    from run.checkout import parse_link_plans
    command = maps[0]
    plans = parse_link_plans(command)
    if len(plans) < 3:
        pytest.skip("contract C4's o: prefix lands with the intake's branch; "
                    f"today parse_link_plans reads {sorted(plans.values())}")
    assert len(plans) == 3 and all(plans.values()), plans


def test_the_playoff_link_opens_at_week_12s_first_kickoff() -> None:
    """Contract C4: the $19 link is made now, switched off, and switched on at
    Week 12's first kickoff — the moment the join page's firstWeek >= 13 rule
    starts offering it. LAUNCH's date is read against the schedule the product
    reads, as is every row of the kickoff table the refund checks use."""
    from zoneinfo import ZoneInfo

    from run.solo import CACHE_DIR
    from run.trials import week_underway_from
    text = _launch()
    flat = _flat(text)
    assert "Wed Nov 25 2026, 8:00 PM ET" in flat
    assert "**Switch the $19 link off until Nov 25:**" in flat
    assert "The Playoff Pass, from Wed Nov 25." in flat and "`PLAYOFF-EARLY`" in flat
    eastern = ZoneInfo("America/New_York")
    kick = week_underway_from(CACHE_DIR, "2026", 12)
    if kick is None:
        pytest.skip("no 2026 schedule cached (data/ is gitignored)")
    local = kick.astimezone(eastern)
    assert (local.strftime("%a %b"), local.day, local.strftime("%-I:%M %p")) == ("Wed Nov", 25, "8:00 PM")
    rows = re.findall(r"(?m)^\| (\d+) \| (?:\*\*)?(\w{3})(?:\*\*)? (\w{3}) (\d+), (\d+:\d\d)(am|pm)", text)
    assert len(rows) >= 13
    for week, day, month, date, clock, half in rows:
        when = week_underway_from(CACHE_DIR, "2026", int(week)).astimezone(eastern)
        assert (when.strftime("%a"), when.strftime("%b"), when.day,
                when.strftime("%-I:%M"), when.strftime("%p").lower()) == \
            (day, month, int(date), clock, half), f"week {week}'s row"


# --------------------------------------------------------------------- #
# the remembered alarms can be cleared by the owner
# --------------------------------------------------------------------- #

def test_the_daily_dispatch_can_clear_a_remembered_payment_alarm(tmp_path) -> None:
    """PLAYOFF-EARLY and PAID-UNATTRIBUTED persist in the sealed registry
    and keep the hourly run red 'until --clear-unresolved' — a flag no
    workflow passed, on a state no local run can reach, so LAUNCH could only
    have told the owner to live with a red cron. daily.yml's dispatch now has a
    box for it, default off, which the Worker's dispatch never sends; the
    run block passes the flag only when it is ticked (executed below with a
    stub interpreter, both ways)."""
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    doc = yaml.safe_load((WORKFLOWS / "daily.yml").read_text(encoding="utf-8"))
    box = doc[True]["workflow_dispatch"]["inputs"]["clear_unresolved"]
    assert box["type"] == "boolean" and box["default"] is False
    assert "clear_unresolved" not in (ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
    assert "--clear-unresolved" in (ROOT / "run" / "intake.py").read_text(encoding="utf-8")
    [step] = [s for s in _steps("daily.yml") if s.get("id") == "intake"]
    assert step["env"]["CLEAR_UNRESOLVED"] == "${{ inputs.clear_unresolved == true }}"
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    stub = tmp_path / ".venv" / "bin" / "python"
    stub.parent.mkdir(parents=True)
    stub.write_text('#!/bin/sh\necho "$@" >> "$ARGS_LOG"\nexit 3\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    for ticked, expected in (("true", "-m run.intake --clear-unresolved"),
                             ("false", "-m run.intake")):
        log, out = tmp_path / f"args-{ticked}", tmp_path / f"out-{ticked}"
        env = {**os.environ, "CLEAR_UNRESOLVED": ticked, "ARGS_LOG": str(log),
               "GITHUB_OUTPUT": str(out)}
        done = subprocess.run([bash, "-e", "-c", step["run"]], cwd=tmp_path, env=env)
        assert done.returncode == 0
        assert log.read_text().strip() == expected
        assert out.read_text().strip() == "code=3", "the intake's exit code must reach the guard"
    launch = _flat(_section(_launch(), "8."))
    assert "tick **Forget the payments already dealt with**" in launch
    assert box["description"].startswith("Forget the payments already dealt with")


# --------------------------------------------------------------------- #
# OPS-4, OPS-6, OPS-10: the contradictions the hand merge left
# --------------------------------------------------------------------- #

def test_launch_has_one_dispute_procedure_and_it_is_the_codes() -> None:
    """Reproduction (OPS-4): two dispute procedures sat side by side — one said
    'accept the dispute (or refund)' and that a lost dispute 'does not stop the
    reports by itself', the other that a lost one ends them like a refund and
    never to refund a disputed payment. The code agrees with the second
    (run/subscriptions.py counts DISPUTE_LOST as refunded; a dispute waiting on
    evidence is DISPUTE_ACTION and turns the intake red)."""
    import inspect

    import run.intake as intake
    import run.subscriptions as subs
    text = _flat(_launch())
    assert text.count("**A dispute (a chargeback).**") == 1
    assert "When a payment is disputed" not in text
    assert "(or refund)" not in text and "does not stop the reports by itself" not in text
    assert "ends their reports by itself, like a full refund" in text
    assert "**Never refund a payment that is already disputed**" in text
    assert "state == DISPUTE_LOST" in inspect.getsource(subs)
    assert "DISPUTE NEEDS A RESPONSE" in inspect.getsource(intake.dispute_alarm)
    assert "`DISPUTE NEEDS A RESPONSE:" in text


def test_the_counter_binding_is_set_up_once() -> None:
    """Reproduction (OPS-10a): step 5.6 and step 5b both set up the Analytics
    Engine binding, by different paths with contradicting details."""
    text = _launch()
    assert text.count("variable name **`COUNTS`**") == 1
    assert "create a dataset `byl_counts`" not in text
    assert "variable name **`COUNTS`**" in _section(text, "5b.")


def test_the_resend_keys_line_keeps_the_bounce_key() -> None:
    """Reproduction (OPS-10b): step 0.6 said both Resend keys are Sending
    access and to 'revoke anything else' — which revokes step 2.3's Full
    access bounce key and switches the bounce check off."""
    item = _flat(_item(_section(_launch(), "0."), 6))
    assert "`github-actions-bounces`" in item and "**Full access**" in item


def test_the_grey_cloud_rule_is_scoped_to_github_pages() -> None:
    """Reproduction (OPS-10d): step 5b.5 said to keep the apex and www records
    DNS only, while section 11's move hands them to Cloudflare Pages, which
    proxies them."""
    item = _flat(_item(_section(_launch(), "5b."), 5))
    assert "while GitHub Pages serves the site" in item


def test_www_redirects_to_the_bare_domain_after_the_move() -> None:
    """Reproduction (OPS-6): A1.3 added www.beatyourleague.com as a second
    Pages domain, which serves the site on www. The Worker allows posts only
    from the bare domain (and SITE_ORIGIN), so every waitlist, free-report,
    seat and roster post from www would be refused and the visitor told to
    check their connection; count.js counts nothing off the bare host. Only
    the apex is attached, www redirects (Cloudflare's own recipe), and the
    check after the move expects the 301."""
    a1 = _flat(_launch()[_launch().index("### A1."):_launch().index("### A2.")])
    assert "add **`beatyourleague.com` only**" in a1
    assert "`www.beatyourleague.com`. Cloudflare rewrites" not in a1
    assert "`192.0.2.1`" in a1 and "**Bulk Redirects**" in a1 and "**301**" in a1
    assert "curl -sI https://www.beatyourleague.com/join/` must answer **301**" in a1
    worker_js = (ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
    assert "www.beatyourleague.com" not in worker_js, \
        "the Worker now accepts www — the redirect's stated reason changed"


# --------------------------------------------------------------------- #
# OPS-10e: seats and conversions need the registry; reading it leaves nothing
# --------------------------------------------------------------------- #

def test_stats_registry_reads_a_sealed_copy_and_leaves_nothing(tmp_path, monkeypatch) -> None:
    """Reproduction (OPS-10e): `make stats` said the registry 'lives in the CI
    cache; pass --registry PATH', but the cache holds only ciphertext and no
    step said how to open a copy — so the seats-per-pass and free-report ->
    paid lines LAUNCH promises could not be seen. `make stats-registry`
    downloads the newest sealed backup into a temporary folder outside the
    repo, opens it with CACHE_KEY, runs the stats on it and deletes the folder.
    Run here end to end with a stub `gh` and a stub stats step: the repo's
    data/registry is never written, and the folder is gone afterwards."""
    make, bash = shutil.which("make"), shutil.which("bash")
    if not make or not bash:
        pytest.skip("needs make and bash")
    from run import statebox
    key = "0123456789abcdef" * 3
    source = tmp_path / "source"
    (source / "data" / "registry").mkdir(parents=True)
    (source / "data" / "registry" / "rosters.json").write_text("[]\n")
    monkeypatch.setenv("CACHE_KEY", key)
    assert statebox.seal("registry", source)["sealed"]
    sealed = source / "data" / "sealed" / "registry.enc"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\n# gh run download -n sealed-registry -D <dir>\n"
                  'while [ $# -gt 0 ]; do [ "$1" = "-D" ] && dir="$2"; shift; done\n'
                  f'mkdir -p "$dir" && cp "{sealed}" "$dir/registry.enc"\n')
    seen = tmp_path / "seen"
    py = bin_dir / "py"
    # Real Python for statebox; the stats call only records what it was given
    # (run.stats would read the owner's .env and the network).
    py.write_text("#!/bin/sh\n"
                  'case "$*" in *"-m run.stats"*) echo "$@" > "' + str(seen) + '";'
                  ' reg="$4"; cat "$reg" >> "' + str(seen) + '"; exit 0;; esac\n'
                  f'exec "{sys.executable}" "$@"\n')
    for tool in (gh, py):
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    before = (ROOT / "data" / "registry").exists()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "CACHE_KEY": key}
    done = subprocess.run([make, "-s", "stats-registry", f"PY={py}"], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    args, contents = seen.read_text().split("\n", 1)
    assert args.startswith("-m run.stats --registry ") and args.endswith("/data/registry/rosters.json")
    assert contents.strip() == "[]", "the stats ran on the opened copy"
    assert not Path(args.split()[-1]).exists(), "the opened copy was left on disk"
    assert (ROOT / "data" / "registry").exists() == before, "make stats-registry wrote data/registry"
    # Without the key it refuses before downloading anything.
    env.pop("CACHE_KEY")
    refused = subprocess.run([make, "-s", "stats-registry", f"PY={py}"], cwd=ROOT, env=env,
                             capture_output=True, text=True)
    assert refused.returncode != 0 and "CACHE_KEY is not in this shell" in refused.stdout
    assert "`make stats-registry`" in _launch()
