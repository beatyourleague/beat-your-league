"""The crons, pinned.

A workflow is the one kind of code nobody runs locally and nobody reviews twice.
Every property here is one where being wrong is silent: a cron that keeps
calling the Sleeper-era module, an artifact that starts publishing subscriber
addresses, a cache that freezes the player directory, a rename that quietly
disconnects the public ledger's republish.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _text(name: str) -> str:
    path = WORKFLOWS / name
    assert path.is_file(), f"{name} is missing"
    return path.read_text(encoding="utf-8")


def _steps(name: str) -> list[dict]:
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    doc = yaml.safe_load(_text(name))
    job = list(doc["jobs"].values())[0]
    return job["steps"]


def _commands(name: str) -> str:
    """Only what the workflow RUNS — YAML prose AND shell comments excluded.

    Matching the whole file would let a comment mentioning `run.batch` pass or
    fail these tests, which is how a test ends up measuring documentation. The
    first version of this only stripped the YAML comments and was promptly
    caught by a `#` comment INSIDE a run: block explaining why ingest.pull was
    removed — a test that reads its own explanation as evidence.
    """
    lines: list[str] = []
    for step in _steps(name):
        for line in str(step.get("run", "")).splitlines():
            body = line.split("#", 1)[0]
            if body.strip():
                lines.append(body)
    return "\n".join(lines)


# --------------------------------------------------------------------- #
# the Tuesday cron drives the roster product
# --------------------------------------------------------------------- #

def test_the_tuesday_cron_runs_the_roster_pipeline() -> None:
    commands = _commands("weekly.yml")
    assert "run.intake" in commands and "run.tuesday" in commands
    for retired in ("run.batch", "run.sync", "run.week", "ingest.pull"):
        assert retired not in commands, (
            f"the Tuesday cron still runs {retired}, which reads a league")


def test_no_cron_step_carries_a_sleeper_secret() -> None:
    """PLAN §0 is only real when the automation stops asking for one."""
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    for name in ("weekly.yml", "monday.yml"):
        doc = yaml.safe_load(_text(name))
        for step in list(doc["jobs"].values())[0]["steps"]:
            env = step.get("env") or {}
            leaked = [k for k in env if "SLEEPER" in k.upper()]
            assert not leaked, f"{name} step {step.get('name')!r} passes {leaked}"


def test_the_artifact_never_publishes_subscriber_data() -> None:
    """An artifact is downloadable by anyone who can read the Actions tab.
    reports/subscribers/ holds personalised reports and reports/outbox/ holds
    the drafts with real addresses on them."""
    upload = [s for s in _steps("weekly.yml")
              if "upload-artifact" in str(s.get("uses", ""))]
    assert upload, "the Tuesday cron uploads no artifact at all"
    paths = str(upload[0]["with"]["path"])
    assert "reports/" in paths
    assert "!reports/subscribers/" in paths, "subscriber reports would be published"
    assert "!reports/outbox/" in paths, "email drafts would be published"


def test_a_blocked_signup_fails_the_run_but_only_after_delivery() -> None:
    """run.intake exits 1 when a paid roster cannot be served. Under
    continue-on-error that becomes a green run with a buried log line — but
    failing immediately would hold up every subscriber already in the registry.
    So the send happens either way and the job is failed afterwards.

    On the EXIT CODE specifically: 2 means STRIPE_API_KEY is unset, which is the
    expected state until checkout opens. Gating on `outcome == failure` caught
    that too and would have filed a bug issue every week before launch."""
    steps = _steps("weekly.yml")
    names = [s.get("name") or s.get("uses") for s in steps]
    intake = next(s for s in steps if s.get("id") == "intake")
    assert intake.get("continue-on-error") is True
    guard = [s for s in steps
             if "steps.intake.outputs.code == '1'" in str(s.get("if", ""))]
    assert guard, "nothing converts a blocked signup into a failed run"
    assert names.index(guard[0].get("name")) > names.index("Send subscriber reports"), \
        "the run is failed before subscribers are mailed"


def test_the_send_step_cannot_be_skipped_by_an_earlier_failure() -> None:
    """A step with no `if:` defaults to `if: success()`. That is what once let
    one failing step skip the send for everybody."""
    send = next(s for s in _steps("weekly.yml")
                if s.get("name") == "Send subscriber reports")
    assert "always()" in str(send.get("if", ""))


# --------------------------------------------------------------------- #
# the caches, and the hazard in them
# --------------------------------------------------------------------- #

def test_the_published_player_directory_is_refreshed_weekly() -> None:
    """Nothing regenerated site/join/players.json. A stale copy does not break a
    build — it blocks one specific customer's signup, weeks later, surfacing
    only as a BLOCKED line in an intake log."""
    commands = _commands("weekly.yml")
    assert "render.player_index" in commands
    assert "current_season" in commands, (
        "the season is hardcoded; it goes stale every September")


# --------------------------------------------------------------------- #
# the Monday cron, and the string that must not change
# --------------------------------------------------------------------- #

def test_the_monday_cron_grades_from_nflverse() -> None:
    commands = _commands("monday.yml")
    assert "run.monday" in commands
    for retired in ("run.content", "ingest.pull"):
        assert retired not in commands, (
            f"the Monday cron still runs {retired}, which grades through Sleeper")


def test_both_crons_can_redeploy_the_site() -> None:
    """pages.yml triggers on `workflow_run` matching LITERAL workflow names, and
    a push made with GITHUB_TOKEN deliberately does not fire `on: push`.

    So renaming either cron silently stops the site redeploying. And leaving the
    Tuesday run off the list did the same thing quietly: its refreshed
    site/join/players.json — the directory the picker downloads — reached the
    live site only when Monday happened to redeploy, up to six days later, and a
    stale directory blocks a paying customer's signup.
    """
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    pages = yaml.safe_load(_text("pages.yml"))
    # `on` parses as the boolean True in YAML 1.1, which is a real trap here.
    triggers = pages.get("on") or pages.get(True)
    watched = triggers["workflow_run"]["workflows"]
    for cron in ("monday.yml", "weekly.yml"):
        name = yaml.safe_load(_text(cron))["name"]
        assert name in watched, (
            f"pages.yml watches {watched}; {cron} is named {name!r}, so its "
            f"commits never reach the live site")


def test_the_public_record_publishes_by_default() -> None:
    """The page was regenerated every Monday and thrown away: committing it was
    gated on a repo variable that is undocumented and unset. Principle 2 is
    "grade everything publicly", and a record that never publishes is not a
    record — so the gate is now an opt-OUT."""
    persist = [s for s in _steps("monday.yml")
               if "Persist" in str(s.get("name", ""))][0]
    run = str(persist["run"])
    assert "site/ledger/" in run
    assert 'PUSH_LEDGER }}" != "false"' in run, (
        "publishing the public record is opt-in; it must be opt-out")


def test_the_monday_cron_needs_no_secrets() -> None:
    """Grading reads public data only. A cron that needs no credential cannot
    fail for want of one."""
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    doc = yaml.safe_load(_text("monday.yml"))
    for step in list(doc["jobs"].values())[0]["steps"]:
        if str(step.get("if", "")).strip() == "failure()":
            continue                        # the issue-filing step needs a token
        env = step.get("env") or {}
        assert not env, f"{step.get('name')!r} needs {sorted(env)}"


# --------------------------------------------------------------------- #
# the suite itself
# --------------------------------------------------------------------- #

def test_ci_runs_the_test_suite() -> None:
    """The two tests that mechanically enforce PLAN §0 are worth nothing if
    nothing runs them."""
    commands = _commands("test.yml")
    assert "pytest" in commands
    assert "node" in _text("test.yml").lower(), (
        "without node, test_intake.py skips — and that is the file where "
        "roster.js is actually run against the Python that decodes it")


# --------------------------------------------------------------------- #
# the daily sweep
# --------------------------------------------------------------------- #

def test_the_daily_sweep_runs_intake_and_only_intake() -> None:
    """Its two jobs are the welcome email and the blocked-signup alarm, both of
    which the weekly cadence serves six days late. It must never build or send
    reports — that is Tuesday's job, with Tuesday's guards."""
    commands = _commands("daily.yml")
    assert "run.intake" in commands
    for heavy in ("run.tuesday", "run.monday", "run.batch", "run.week",
                  "render.player_index"):
        assert heavy not in commands, f"the daily sweep runs {heavy}"


def test_the_daily_sweep_persists_the_send_log() -> None:
    """sent.jsonl is the only record of who was welcomed; losing it
    double-welcomes everyone on the next run."""
    persist = [s for s in _steps("daily.yml")
               if "Persist" in str(s.get("name", ""))]
    assert persist, "the daily sweep never persists sent.jsonl"
    assert "sent.jsonl" in str(persist[0]["run"])
    assert "git push" in str(persist[0]["run"])


def test_the_daily_sweep_carries_the_welcome_env() -> None:
    """Without EMAIL_PROVIDER the sweep reports welcomes as pending forever —
    a legally-owed acknowledgment that silently never sends."""
    sweep = next(s for s in _steps("daily.yml") if s.get("id") == "intake")
    env = sweep.get("env") or {}
    for needed in ("STRIPE_API_KEY", "EMAIL_PROVIDER", "SITE_URL",
                   "BILLING_PORTAL_URL"):
        assert needed in env, f"daily sweep is missing {needed}"
    # And the same not-configured-is-not-a-failure contract as Tuesday.
    guard = [s for s in _steps("daily.yml")
             if "steps.intake.outputs.code == '1'" in str(s.get("if", ""))]
    assert guard, "a blocked paid signup would not fail the daily sweep"


def test_the_weekly_intake_step_can_send_welcomes_too() -> None:
    """Belt over the daily braces: if the daily cron is ever disabled, Tuesday
    still delivers the acknowledgment (idempotently)."""
    steps = _steps("weekly.yml")
    intake = next(s for s in steps if s.get("id") == "intake")
    env = intake.get("env") or {}
    assert "EMAIL_PROVIDER" in env and "BILLING_PORTAL_URL" in env
