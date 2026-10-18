"""Shared test guards, and the skips for data that is not in git.

The registry guard below exists because it already happened: a run of the
pipeline wrote over the real subscriber registry. Nothing was lost — the file
held a single demo entry — but on a machine with paying subscribers in it, a
test that writes to ``data/registry/`` destroys the list of who gets a report,
and the failure is invisible until the following Tuesday.

So the suite is not allowed to touch it, and this fixture fails the test that
tries rather than trusting everyone to remember to pass ``tmp_path``.

The second half is about ``data/``, which is gitignored in its entirety. Six
tests read artifacts that only exist once somebody has run `make demo` or
`ingest.pull` locally, so on a fresh checkout — which is what CI is — they
failed rather than skipped. A test that cannot run should say so; failing makes
a red suite mean "somebody has not run the demo" as often as it means "the
software is broken", and a red suite that usually means nothing is a suite
people stop reading.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# run/digest.py: every address-derived code in the send log and the stop list
# is keyed under LOG_SECRET and refuses without it. Tests get a fixed stand-in
# (a test that needs it unset deletes it with monkeypatch).
os.environ.setdefault("LOG_SECRET", "test-log-secret")

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "data" / "registry"
# The public record (Oct 2026): every published probability, append-only and
# immutable once graded (RULES L1-L4), committed and graded every Monday. The
# live sample now RECORDS its odds there before kickoff (render/live_sample.py),
# so a test that builds the page without pointing the ledger at tmp_path would
# put a row on the public record that no report ever carried — and RULE L4
# makes a row impossible to take back.
LEDGER_DIR = REPO_ROOT / "data" / "processed" / "ledger"
# Each off-limits tree, with why — the failure names the one that was touched.
OFF_LIMITS = {
    REGISTRY_DIR: ("holds subscriber emails and decides who gets mailed on "
                   "Tuesday", "Build a registry under tmp_path and pass the "
                   "path explicitly instead."),
    LEDGER_DIR: ("is the public record — append-only, and a graded row can "
                 "never be taken back", "Pass a processed/ledger directory "
                 "under tmp_path (every recorder takes one) instead."),
}


def _snapshot(root: Path = REGISTRY_DIR) -> dict[str, float]:
    if not root.is_dir():
        return {}
    # Recursive: data/registry/first-plans/<season>/ (Oct 2026) is a write
    # path too, and a top-level-only snapshot could not see it. A ledger's
    # flock file is not part of the record (gitignored, zero bytes, touched by
    # any recorder that finds nothing new to write) — the rows are; so locks
    # are left out and a single recorded row is still caught.
    return {str(p.relative_to(root)): p.stat().st_mtime_ns
            for p in root.rglob("*") if p.is_file() and p.suffix != ".lock"}


@pytest.fixture(autouse=True)
def registry_is_off_limits():
    """No test may create, modify or delete anything under data/registry/ or
    data/processed/ledger/.

    The registry holds subscriber emails and drives who gets mailed; the ledger
    is the public record. Tests that need either build one under tmp_path and
    pass the path explicitly — every function in run/sync.py, run/registry.py
    and engine/ledger.py accepts one for this reason.
    """
    before = {root: _snapshot(root) for root in OFF_LIMITS}
    yield
    for root, (why, instead) in OFF_LIMITS.items():
        after = _snapshot(root)
        if before[root] == after:
            continue
        created = sorted(set(after) - set(before[root]))
        removed = sorted(set(before[root]) - set(after))
        changed = sorted(n for n in set(before[root]) & set(after)
                         if before[root][n] != after[n])
        raise AssertionError(
            f"this test wrote to the real {root.relative_to(REPO_ROOT)}/ — that "
            f"directory {why}.\n"
            f"  created: {created or 'none'}\n"
            f"  modified: {changed or 'none'}\n"
            f"  deleted: {removed or 'none'}\n"
            f"{instead}")


# --------------------------------------------------------------------- #
# artifacts that are not in git
# --------------------------------------------------------------------- #

RAW_DIR = REPO_ROOT / "data" / "raw"
DEMO_REPORT = REPO_ROOT / "data" / "processed" / "week_report.json"
SAMPLE_LEAGUE = "289646328504385536"

requires_demo_report = pytest.mark.skipif(
    not DEMO_REPORT.is_file(),
    reason="demo report not built — run `make demo`",
)

# reports/ is gitignored in full — those renders name real league members — so
# the demo pair exists only where somebody has run `make demo`.
DEMO_TEXT = REPO_ROOT / "reports" / "rival-report-2018-w10-r1.txt"

requires_demo_render = pytest.mark.skipif(
    not DEMO_TEXT.is_file(),
    reason="local demo render not present — run `make demo`",
)

requires_sample_league = pytest.mark.skipif(
    not (RAW_DIR / "league" / SAMPLE_LEAGUE / "league.json").is_file()
    or not (RAW_DIR / "players" / "nfl.json").is_file(),
    reason="sample-league cache not present — run `python -m ingest.pull`",
)


def demo_report() -> dict:
    """The rendered sample week, or a skip.

    Read by tests that assert on real engine output rather than a fixture —
    which is the point of them, and also why they cannot run without it.
    """
    import json
    if not DEMO_REPORT.is_file():
        pytest.skip("demo report not built — run `make demo`")
    return json.loads(DEMO_REPORT.read_text(encoding="utf-8"))
