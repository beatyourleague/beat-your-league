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

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "data" / "registry"


def _snapshot() -> dict[str, float]:
    if not REGISTRY_DIR.is_dir():
        return {}
    return {p.name: p.stat().st_mtime_ns for p in REGISTRY_DIR.iterdir() if p.is_file()}


@pytest.fixture(autouse=True)
def registry_is_off_limits():
    """No test may create, modify or delete anything under data/registry/.

    It holds subscriber emails and drives who gets mailed. Tests that need a
    registry build one under tmp_path and pass the path explicitly — every
    function in run/sync.py and run/registry.py accepts one for this reason.
    """
    before = _snapshot()
    yield
    after = _snapshot()
    if before == after:
        return
    created = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(n for n in set(before) & set(after) if before[n] != after[n])
    raise AssertionError(
        "this test wrote to the real data/registry/ — that directory holds "
        "subscriber emails and decides who gets mailed on Tuesday.\n"
        f"  created: {created or 'none'}\n"
        f"  modified: {changed or 'none'}\n"
        f"  deleted: {removed or 'none'}\n"
        "Build a registry under tmp_path and pass the path explicitly instead.")


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
