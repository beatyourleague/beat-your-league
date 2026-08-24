"""The public content drafts — the record is the only thing they may quote.

``run/content.py`` drafted these from a Sleeper league and produces nothing
for the product that ships. The port (``run/posts.py``) rests on two rules
that are properties of the code rather than of any one draft, so they are
pinned here: the drafts read the PUBLIC ledger and nothing else, and they
never grade — ``run/monday.py`` owns settlement, and a second grader is how a
public record starts answering the same question two ways.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import run.posts as posts
from engine.ledger import GRADED, PENDING, LedgerCall, ledger_path, record_calls

REPO = Path(__file__).resolve().parent.parent
STORE = "typed-ppr-12-2024"


def _call(**over) -> LedgerCall:
    fields = dict(
        call_id="c1", source="slot", league_id=STORE, season="2024", week=10,
        roster_id=1, slot="RB", pick_id="p1", pick_name="Saquon Barkley",
        over_id="o1", over_name="Tony Pollard", confidence=0.61,
        is_regret=False, recorded_at="2024-11-05T12:00:00+00:00",
        status=GRADED, outcome="hit", pick_points=22.4, over_points=9.1,
        graded_at="2024-11-12T12:00:00+00:00")
    fields.update(over)
    return LedgerCall(**fields)


@pytest.fixture
def ledger(tmp_path) -> Path:
    record_calls(ledger_path(tmp_path, STORE), [
        _call(),
        _call(call_id="c2", slot="WR", pick_name="Ja'Marr Chase",
              over_name="Courtland Sutton", confidence=0.65),
        _call(call_id="c3", slot="FLEX", pick_name="Tony Pollard",
              over_name="Chase Brown", confidence=0.50, is_regret=True,
              outcome="miss", pick_points=4.2, over_points=18.7),
    ])
    return tmp_path


# --------------------------------------------------------------------- #
# the rules that are properties of the code
# --------------------------------------------------------------------- #

def _reachable(root: str) -> set[str]:
    """Every repo module reachable from ``root`` by import."""
    seen: set[str] = set()
    queue = [root]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = REPO / (name.replace(".", "/") + ".py")
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                queue += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                queue.append(node.module)
    return {n for n in seen
            if (REPO / (n.replace(".", "/") + ".py")).is_file()}


def test_a_public_draft_cannot_reach_a_subscribers_file() -> None:
    """In the league product these drafts quoted the OWNER's own team. There
    is no owner team here — there are subscribers, and their reports are
    private. A post quoting one would publish the roster they paid us to
    keep, so the modules that read rosters, registries and per-subscriber
    reports must be unreachable from here. Import reachability, not a grep:
    the way a dependency comes back is through something it imports."""
    modules = _reachable("run.posts")
    for forbidden in ("run.rosters", "run.tuesday", "run.registry",
                      "run.batch", "engine.solo_report", "run.intake",
                      "ingest.sleeper", "ingest.pull"):
        assert forbidden not in modules, (
            f"run/posts.py reaches {forbidden} — a public draft must not be "
            f"able to read a subscriber's roster or report")
    source = (REPO / "run" / "posts.py").read_text(encoding="utf-8")
    assert "subscribers" not in source.replace("subscriber's", "").replace(
        "subscriber", ""), "a draft names the per-subscriber report directory"


def test_the_drafts_never_grade() -> None:
    """run/monday.py owns settlement — the finality rule, the shrink guard,
    RULES L1-L4. A draft that graded would be a second answer to "what
    happened", which is the failure the single-grader rule exists to
    prevent."""
    source = (REPO / "run" / "posts.py").read_text(encoding="utf-8")
    for grader in ("grade_ledger", "grade_ledger_nflverse", "write_ledger_site"):
        assert grader not in source, f"run/posts.py calls {grader}"


def test_a_pending_call_is_never_quoted(tmp_path) -> None:
    """A pending call is a claim about a game that has not finished. Quoting
    one in public is the one thing the ledger exists to prevent."""
    record_calls(ledger_path(tmp_path, STORE), [
        _call(call_id="p1", status=PENDING, outcome=None, pick_points=None,
              over_points=None, graded_at=None, pick_name="Bijan Robinson"),
    ])
    assert posts.settled(tmp_path) == []
    path, verdict = posts.receipts_monday(tmp_path, tmp_path / "out")
    assert "nothing settled" in verdict
    assert "Bijan Robinson" not in path.read_text(encoding="utf-8")


# --------------------------------------------------------------------- #
# what each draft says
# --------------------------------------------------------------------- #

def test_receipts_monday_publishes_the_misses_it_would_rather_not(ledger) -> None:
    """Principle 2: wins AND misses. A Receipts post that quietly reported
    only the hits would be the exact thing the ledger was built to make
    impossible."""
    path, verdict = posts.receipts_monday(ledger, ledger / "out")
    text = path.read_text(encoding="utf-8")
    assert verdict == "2-1 week 10"
    assert "2 hit, 1 miss" in text
    assert "MISS** · Tony Pollard over Chase Brown" in text
    assert "The one that hurt" in text, "the draft buried its own miss"
    # Every call carries the number it was published at and what it scored.
    assert "at 61%" in text and "22.4 to 9.1" in text
    # Cards are rendered for the week, the miss included.
    assert (ledger / "out" / "cards").is_dir()
    assert len(list((ledger / "out" / "cards").glob("*.svg"))) == 3


def test_coinflip_friday_quotes_the_closest_recorded_call(ledger) -> None:
    """It reads the LEDGER, so the number posted is the number that was
    recorded when the report shipped — which is what makes Monday's grade
    settle that exact claim."""
    path, verdict = posts.coinflip_friday(ledger, ledger / "out")
    text = path.read_text(encoding="utf-8")
    assert "Tony Pollard over Chase Brown, 50%" in text
    assert "50%" in verdict
    assert "recorded 2024-11-05" in text


def test_every_draft_has_an_honest_empty_state(tmp_path) -> None:
    """Week 1 has no record at all. Each draft must say so rather than
    padding, and must not invent a number to fill the slot."""
    out = tmp_path / "out"
    receipts, r_verdict = posts.receipts_monday(tmp_path, out)
    flip, f_verdict = posts.coinflip_friday(tmp_path, out)
    kit, k_verdict = posts.reply_kit(tmp_path, out, "2026-09-08")
    assert r_verdict == "nothing settled"
    assert "Nothing settled this week" in receipts.read_text(encoding="utf-8")
    assert f_verdict == "gated"
    assert "not one close call cleared our bar" in flip.read_text(encoding="utf-8")
    assert k_verdict == "0 number(s)"
    assert "nothing here to" in kit.read_text(encoding="utf-8")


def test_the_reply_kit_quotes_only_graded_public_calls(ledger) -> None:
    path, verdict = posts.reply_kit(ledger, ledger / "out", "2026-09-20")
    text = path.read_text(encoding="utf-8")
    assert "2-1 on 3 graded calls" in text
    assert "no subscriber's file" in text
    assert "do not pad this list" in text, \
        "a thin day must say it is thin rather than filling out"


# --------------------------------------------------------------------- #
# what did NOT survive the port, said out loud
# --------------------------------------------------------------------- #

def test_hype_wednesday_is_gone_and_the_runner_says_why(capsys, tmp_path) -> None:
    """It ranked waiver chases out of a league's transaction log. This product
    reads no league, so there is no log — drafting it anyway would mean
    inventing the number the post exists to report. The absence is stated
    where an operator will see it, not left to be discovered."""
    assert not hasattr(posts, "hype_wednesday")
    posts.main(["all", "--processed", str(tmp_path), "--out", str(tmp_path / "o"),
                "--date", "2026-09-08"])
    out = capsys.readouterr().out
    assert "Hype Wednesday is not here" in out
    assert "reads no league" in out


def test_a_retired_products_record_never_appears_as_ours(tmp_path) -> None:
    """The processed directory also holds Sleeper-era ledger stores, keyed by
    league id rather than `typed-{scoring}-{size}-{season}`. run/monday.py
    already grades only the typed ones, so without the same scope here a
    retired product's graded calls would be published as this product's
    receipts — with an empty scoring column where the preset should be."""
    record_calls(ledger_path(tmp_path, "289646328504385536"), [
        _call(call_id="old1", league_id="289646328504385536",
              pick_name="Somebody From 2018"),
    ])
    record_calls(ledger_path(tmp_path, STORE), [_call(call_id="new1")])
    assert [c.call_id for c in posts.settled(tmp_path)] == ["new1"]
    path, _ = posts.receipts_monday(tmp_path, tmp_path / "out")
    text = path.read_text(encoding="utf-8")
    assert "Somebody From 2018" not in text
    assert "Saquon Barkley" in text
    assert ", None)" not in text, "a call rendered with no scoring preset"
