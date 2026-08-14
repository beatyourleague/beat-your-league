"""Shared test guards.

The one below exists because it already happened: a run of the pipeline wrote
over the real subscriber registry. Nothing was lost — the file held a single
demo entry — but on a machine with paying subscribers in it, a test that writes
to ``data/registry/`` destroys the list of who gets a report, and the failure is
invisible until the following Tuesday.

So the suite is not allowed to touch it, and this fixture fails the test that
tries rather than trusting everyone to remember to pass ``tmp_path``.
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
