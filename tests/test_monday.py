"""Grading the receipts ledger from nflverse — the half that was Sleeper-shaped.

``run/tuesday.py`` records every published probability; nothing settled them.
``engine/ledger.grade_ledger`` decided finality from a cached Sleeper schedule
plus the weekly availability snapshots that only ``ingest.pull`` writes, and the
roster path writes neither — so every ``typed-*`` call would have stayed PENDING
forever. Green cron, empty public record, principle 2 quietly voided.

The rules being tested are the ones a premature or flattering grade would break.
RULES L1-L4 are NOT reimplemented for nflverse: one function applies them and
this only swaps where finality and points come from, so these tests exist to
prove the swap did not change a rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import run.monday as monday
from engine.ledger import (GRADED, PENDING, VOID, LedgerCall,
                           grade_ledger_nflverse, ledger_path, load_ledger,
                           record_calls, scoring_of)
from test_solo_run import OFFLINE, SEASON, _cache, _pid

# The fixture cache writes final scores for weeks 1-5 and leaves 6-8 unplayed.
FINAL_WEEK, UNPLAYED_WEEK = 3, 7


def _call(week: int, pick: str, over: str, *, scoring: str = "ppr",
          cid: str | None = None, season: str = SEASON) -> LedgerCall:
    return LedgerCall(
        call_id=cid or f"{scoring}-{week}-{pick}-{over}", source="slot",
        league_id=f"typed-{scoring}-12-{season}", season=season, week=week,
        roster_id=1, slot="WR", pick_id=pick, pick_name=f"pick {pick}",
        over_id=over, over_name=f"over {over}", confidence=0.61,
        is_regret=False, recorded_at="2026-01-01T00:00:00+00:00")


def _store(tmp_path: Path, *calls: LedgerCall, scoring: str = "ppr") -> Path:
    path = ledger_path(tmp_path / "processed", f"typed-{scoring}-12-{SEASON}")
    record_calls(path, list(calls))
    return path


# --------------------------------------------------------------------- #
# RULE L1 — never premature
# --------------------------------------------------------------------- #

def test_a_call_does_not_grade_before_the_games_are_final(tmp_path) -> None:
    """The receipts brand dies on one premature grade. A week whose games carry
    no final score must stay PENDING, not be settled against nothing."""
    cache = _cache(tmp_path)
    path = _store(tmp_path, _call(UNPLAYED_WEEK, _pid(1), _pid(2)))
    graded, pending = grade_ledger_nflverse(path, cache)
    assert (graded, pending) == (0, 1)
    assert load_ledger(path)[0].status == PENDING


def test_a_call_grades_once_its_week_is_final(tmp_path) -> None:
    cache = _cache(tmp_path)
    path = _store(tmp_path, _call(FINAL_WEEK, _pid(1), _pid(2)))
    graded, pending = grade_ledger_nflverse(path, cache)
    assert (graded, pending) == (1, 0)
    assert load_ledger(path)[0].status == GRADED


def test_an_unknown_week_is_not_final(tmp_path) -> None:
    """Conservative on every unknown. A week the schedule has never heard of is
    not a week whose games are all done."""
    cache = _cache(tmp_path)
    path = _store(tmp_path, _call(99, _pid(1), _pid(2)))
    assert grade_ledger_nflverse(path, cache) == (0, 1)


def test_a_stats_outage_leaves_calls_pending_rather_than_voiding_them(
        tmp_path, monkeypatch) -> None:
    """The worst bug this module could have, reproduced before it was fixed.

    Finality comes from the schedule and points come from the weekly stat
    release — two files, fetched independently. Checking only the schedule meant
    that with the stats download failed, BOTH players scored "absent" = 0.0,
    RULE L3 voided the call as a non-event, and RULE L4 made that permanent. One
    outage silently erased every real hit and miss in the season from the public
    record, which is the exact failure a receipts product cannot survive.
    """
    import ingest.nflverse as nflv
    cache = _cache(tmp_path)

    def outage(*_a, **_k):
        raise nflv.NflverseError("simulated outage")
    monkeypatch.setattr(nflv, "season_rows", outage)
    monkeypatch.setattr(nflv, "defense_rows", outage)

    path = _store(tmp_path, _call(FINAL_WEEK, _pid(5), _pid(2)))
    assert grade_ledger_nflverse(path, cache) == (0, 1)
    call = load_ledger(path)[0]
    assert call.status == PENDING, "an outage was recorded as a result"
    assert call.void_reason is None


def test_a_week_whose_box_scores_have_not_landed_is_not_gradeable(
        tmp_path) -> None:
    """The subtler half: the stats file EXISTS but lags the schedule. Every
    player then looks absent, and a real miss publishes as a void — or worse, a
    partially-published week makes one player look absent against another's real
    points, fabricating an outcome.

    So a week is gradeable only when every team the schedule calls final
    actually appears in that week's stat rows. Then "no row" unambiguously means
    "did not play", which is what makes scoring him 0.0 honest.
    """
    import csv as _csv
    cache = _cache(tmp_path)
    stats = cache / f"stats_player_week_{SEASON}.csv"
    rows = [r for r in _csv.DictReader(stats.open(encoding="utf-8"))
            if int(r["week"] or 0) != FINAL_WEEK]
    with stats.open("w", encoding="utf-8", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    path = _store(tmp_path, _call(FINAL_WEEK, _pid(5), _pid(2)))
    assert grade_ledger_nflverse(path, cache) == (0, 1)
    assert load_ledger(path)[0].status == PENDING


# --------------------------------------------------------------------- #
# RULES L2/L3 — the outcome, and the rule this data source forced
# --------------------------------------------------------------------- #

def test_the_outcome_matches_the_points_it_records(tmp_path) -> None:
    cache = _cache(tmp_path)
    # In the fixture a player's receiving yards rise with his index, so a
    # higher-numbered pick outscores a lower-numbered alternative.
    path = _store(tmp_path, _call(FINAL_WEEK, _pid(5), _pid(2), cid="a"),
                  _call(FINAL_WEEK, _pid(2), _pid(5), cid="b"))
    grade_ledger_nflverse(path, cache)
    by_id = {c.call_id: c for c in load_ledger(path)}
    assert by_id["a"].outcome == "hit" and by_id["a"].pick_points > by_id["a"].over_points
    assert by_id["b"].outcome == "miss" and by_id["b"].pick_points < by_id["b"].over_points


def test_a_player_with_no_stat_row_scored_zero_not_nothing(tmp_path) -> None:
    """THE grading rule this data source forced, stated before any row was
    graded (principle 2).

    Sleeper wrote an explicit 0.0 for a rostered player who did not play, so a
    call whose pick sat while the alternative scored was a MISS. nflverse simply
    has no row for him. Mapping that to "no scoring record" would VOID every one
    of those calls — real misses, removed from the record, flattering it in
    exactly the direction nobody should trust us on. Absence scores 0.0.
    """
    cache = _cache(tmp_path)
    ghost = "00-0009999"                       # nobody: no row in any week
    path = _store(tmp_path, _call(FINAL_WEEK, ghost, _pid(4)))
    grade_ledger_nflverse(path, cache)
    call = load_ledger(path)[0]
    assert call.status == GRADED, "a real miss was voided out of the record"
    assert call.outcome == "miss"
    assert call.pick_points == 0.0 and call.over_points > 0.0


def test_both_players_at_zero_is_void_not_a_tie(tmp_path) -> None:
    """RULE L3. 0.0 is the absence signal, and a non-event must not enter the
    record as a tie — that would make a week nobody played look like a week we
    got exactly right."""
    cache = _cache(tmp_path)
    path = _store(tmp_path, _call(FINAL_WEEK, "00-0009998", "00-0009999"))
    grade_ledger_nflverse(path, cache)
    call = load_ledger(path)[0]
    assert call.status == VOID and call.outcome is None
    assert "0.0" in (call.void_reason or "")


# --------------------------------------------------------------------- #
# RULE L4 — immutable once graded
# --------------------------------------------------------------------- #

def test_grading_twice_changes_nothing(tmp_path) -> None:
    cache = _cache(tmp_path)
    path = _store(tmp_path, _call(FINAL_WEEK, _pid(5), _pid(2)))
    assert grade_ledger_nflverse(path, cache) == (1, 0)
    first = path.read_text(encoding="utf-8")
    assert grade_ledger_nflverse(path, cache) == (0, 0)
    assert path.read_text(encoding="utf-8") == first


# --------------------------------------------------------------------- #
# the scoring preset is part of a call's identity
# --------------------------------------------------------------------- #

def test_each_scoring_preset_is_graded_under_its_own_rule(tmp_path) -> None:
    """A ledger that cannot tell PPR from standard cannot be graded correctly
    for either: "did the pick outscore the alternative" has a different answer
    under each. The store name carries the preset, which is how grading knows."""
    assert scoring_of("typed-ppr-12-2026") == "ppr"
    assert scoring_of("typed-half_ppr-10-2026") == "half_ppr"
    assert scoring_of("289646328504385536") is None, "a league id is not a preset"
    # League size is part of the identity too: it sets the positional prior's
    # depth, so it moves the published probability (measured: 0.022 spread
    # across sizes 4-32, and 1 call in 3 crossing a calibration bucket).
    from engine.ledger import league_size_of
    assert league_size_of("typed-ppr-14-2026") == 14
    assert league_size_of("typed-ppr-2026") is None, "the old shape must not parse"

    cache = _cache(tmp_path)
    scored: dict[str, float] = {}
    for scoring in ("ppr", "standard"):
        path = _store(tmp_path, _call(FINAL_WEEK, _pid(5), _pid(2),
                                      scoring=scoring), scoring=scoring)
        assert grade_ledger_nflverse(path, cache) == (1, 0)
        call = load_ledger(path)[0]
        assert call.status == GRADED
        scored[scoring] = call.pick_points

    # The same player, the same week, graded under two rules. Every fixture
    # player catches 4 passes, so full PPR must credit exactly 4.0 more than
    # standard. Asserting the GAP is what makes this a test of the rule rather
    # than of the plumbing: if both stores were graded under one preset — the
    # bug this whole split exists to prevent — the gap would be zero.
    assert scored["ppr"] - scored["standard"] == pytest.approx(4.0, abs=1e-6)


def test_a_ledger_that_is_not_a_roster_store_is_left_alone(tmp_path) -> None:
    """A Sleeper-era ledger has no preset in its name and is not this grader's
    to settle. Guessing a rule for it would grade somebody's league under a
    scoring system they never used."""
    cache = _cache(tmp_path)
    path = ledger_path(tmp_path / "processed", "289646328504385536")
    call = _call(FINAL_WEEK, _pid(5), _pid(2))
    record_calls(path, [LedgerCall(**{**call.__dict__,
                                      "league_id": "289646328504385536"})])
    assert grade_ledger_nflverse(path, cache) == (0, 1)
    assert load_ledger(path)[0].status == PENDING


# --------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------- #

def test_the_monday_runner_settles_every_roster_store(tmp_path, capsys) -> None:
    processed = tmp_path / "processed"
    for scoring in ("ppr", "standard"):
        record_calls(ledger_path(processed, f"typed-{scoring}-12-{SEASON}"),
                     [_call(FINAL_WEEK, _pid(5), _pid(2), scoring=scoring)])
    assert monday.typed_stores(processed) == [
        f"typed-ppr-12-{SEASON}", f"typed-standard-12-{SEASON}"]
    code = monday.main(["--processed-dir", str(processed),
                        "--cache", str(_cache(tmp_path)),
                        "--out", str(tmp_path / "site")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "1 settled this run" in out
    assert (tmp_path / "site" / "index.html").is_file()


def test_a_dry_run_grades_nothing(tmp_path, capsys) -> None:
    processed = tmp_path / "processed"
    record_calls(ledger_path(processed, f"typed-ppr-12-{SEASON}"),
                 [_call(FINAL_WEEK, _pid(5), _pid(2))])
    monday.main(["--processed-dir", str(processed),
                 "--cache", str(_cache(tmp_path)),
                 "--out", str(tmp_path / "site"), "--dry-run"])
    assert "dry run" in capsys.readouterr().out
    assert load_ledger(ledger_path(processed, f"typed-ppr-12-{SEASON}"))[0].status \
        == PENDING
    assert not (tmp_path / "site").exists()


def test_the_public_page_is_never_shrunk(tmp_path, capsys) -> None:
    """The ledger is append-only and graded entries are immutable, so the only
    way the published list gets shorter is data loss. Publishing that would
    silently rewrite the public record."""
    out = tmp_path / "site"
    out.mkdir()
    (out / "data.json").write_text(json.dumps([
        {"season": SEASON, "week": 1, "slot": "WR", "pick": "Someone",
         "over": "Someone Else"}]), encoding="utf-8")
    processed = tmp_path / "processed"
    record_calls(ledger_path(processed, f"typed-ppr-12-{SEASON}"),
                 [_call(FINAL_WEEK, _pid(5), _pid(2))])
    code = monday.main(["--processed-dir", str(processed),
                        "--cache", str(_cache(tmp_path)), "--out", str(out)])
    assert code == 1
    assert "REFUSING" in capsys.readouterr().err


def test_an_empty_record_does_not_publish_an_empty_page(tmp_path, capsys) -> None:
    """Nothing settled yet is a real state in September, and overwriting a good
    page with an empty one is the same failure as shrinking it."""
    processed = tmp_path / "processed"
    record_calls(ledger_path(processed, f"typed-ppr-12-{SEASON}"),
                 [_call(UNPLAYED_WEEK, _pid(5), _pid(2))])
    code = monday.main(["--processed-dir", str(processed),
                        "--cache", str(_cache(tmp_path)),
                        "--out", str(tmp_path / "site")])
    assert code == 0
    assert "left as it stands" in capsys.readouterr().out
    assert not (tmp_path / "site" / "index.html").exists()


def test_the_monday_runner_cannot_reach_sleeper_at_all() -> None:
    """Same guarantee as run/tuesday.py, by import reachability rather than a
    grep of one file — the way a dependency comes back is through something it
    imports."""
    import ast

    repo = Path(__file__).resolve().parent.parent
    seen: set[str] = set()
    queue = ["run.monday"]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = repo / (name.replace(".", "/") + ".py")
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                queue += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                queue.append(node.module)
    assert "ingest.sleeper" not in seen, sorted(n for n in seen if "sleeper" in n)


# --------------------------------------------------------------------- #
# two crons write this file
# --------------------------------------------------------------------- #

def test_a_union_merged_duplicate_collapses_to_one_call(tmp_path) -> None:
    """The Monday and Tuesday runs each commit and push their own copy of the
    ledger, so a push race is routine. `git pull --rebase` on a normal text file
    turns that into a conflict, which fails the persist step and LOSES published
    probabilities — and a call is recorded at the moment it is published or not
    at all. .gitattributes marks these logs `merge=union`, which concatenates
    instead of conflicting; the cost is duplicated lines, which the reader must
    collapse or the public page shows one call twice and counts it as two pieces
    of evidence.
    """
    path = ledger_path(tmp_path / "processed", f"typed-ppr-12-{SEASON}")
    call = _call(FINAL_WEEK, _pid(5), _pid(2), cid="dup")
    record_calls(path, [call])
    # What union merge leaves behind: the same call from both sides, one graded.
    graded = LedgerCall(**{**call.__dict__, "status": GRADED, "outcome": "hit",
                           "pick_points": 20.0, "over_points": 10.0})
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(graded.__dict__, separators=(",", ":")) + "\n")

    calls = load_ledger(path)
    assert len(calls) == 1, "one call published twice on the public record"
    assert calls[0].status == GRADED, "the settled copy lost to the pending one"


def test_two_different_outcomes_for_one_call_is_corruption_not_a_merge(
        tmp_path) -> None:
    """A pending duplicate losing to a graded one is just the other cron having
    settled it. Two DIFFERENT graded outcomes is real corruption, and "which of
    these answers did we publish" is exactly the question nobody should answer
    automatically — the module's rule is that a public record is fixed by hand,
    never silently repaired."""
    from engine.ledger import LedgerError

    path = ledger_path(tmp_path / "processed", f"typed-ppr-12-{SEASON}")
    call = _call(FINAL_WEEK, _pid(5), _pid(2), cid="dup")
    rows = [LedgerCall(**{**call.__dict__, "status": GRADED, "outcome": out})
            for out in ("hit", "miss")]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r.__dict__, separators=(",", ":")) + "\n"
                            for r in rows), encoding="utf-8")
    with pytest.raises(LedgerError, match="different outcomes"):
        load_ledger(path)


def test_the_append_only_logs_are_union_merged() -> None:
    """Without this the push race is a rebase conflict, and the fix in
    engine/ledger.py has nothing to protect against."""
    attrs = (Path(__file__).resolve().parent.parent / ".gitattributes")
    assert attrs.is_file(), ".gitattributes is missing"
    text = attrs.read_text(encoding="utf-8")
    assert "merge=union" in text
    assert "data/processed/ledger" in text and "sent.jsonl" in text


def test_a_lost_duplicate_row_is_still_a_loss(tmp_path) -> None:
    """The shrink guard counts rows, it does not compare sets of keys.

    Adding scoring and league_size to the key made the collision that was found
    distinguishable; counting is what makes the guard robust to the NEXT one.
    Two rows that legitimately share a key, one of which disappears, is a real
    loss — and a set comparison cannot see it, because the key is still present.
    """
    out = tmp_path / "site"
    out.mkdir()
    row = {"season": SEASON, "week": 10, "slot": "WR", "pick": "A",
           "over": "B", "scoring": "ppr", "league_size": 12}
    (out / "data.json").write_text(json.dumps([row, dict(row)]), encoding="utf-8")
    with pytest.raises(monday.MondayError, match="would disappear"):
        monday.guard_shrink([row], out)
    monday.guard_shrink([row, dict(row)], out)          # unchanged: fine


def test_the_public_record_shows_which_setup_decided_each_call() -> None:
    """public_entries has carried `scoring` and `league_size` since the store
    split, and its docstring says exactly why — "without the preset the two
    render as identical duplicate rows" — but _row never displayed either, so
    they rendered as identical duplicate rows.

    The picker offers 3 scoring presets x 4 league sizes, so ONE real
    head-to-head can publish as up to 12 rows on the public page, all decided
    by one game, with nothing telling them apart. A reader counting rows would
    read twelve pieces of evidence where there is one. Found Aug 24 2026."""
    from render.ledger_site import _row

    base = dict(season="2024", week=10, slot="WR", pick="Ja'Marr Chase",
                over="Courtland Sutton", status="graded", outcome="hit",
                margin=36.4, void_reason=None, regret=False)
    ppr = _row({**base, "scoring": "ppr", "league_size": 12, "confidence": 0.647})
    std = _row({**base, "scoring": "standard", "league_size": 8, "confidence": 0.632})
    assert "PPR" in ppr and "12-team" in ppr
    assert "Standard" in std and "8-team" in std
    assert ppr != std, "two cohorts' rows are still indistinguishable"
    # A pre-split store carries neither and must not render "None".
    old = _row({**base, "scoring": None, "league_size": None, "confidence": 0.6})
    assert "None" not in old


def test_the_public_record_does_not_sell_a_rival_the_product_has_not_got() -> None:
    """The generator closed every Monday republish with "Your league's version
    starts when you pick a rival" above a "Pick your rival" button. The product
    reads no league and has no rival (PLAN §0), and the join page it points at
    contains the word only in a leftover CSS class. The landing links this page
    twice as its proof asset, so the funnel routed a skeptical buyer here and
    then promised what the destination cannot deliver — verbatim the failure
    test_the_funnel_never_promises_what_the_product_cannot_see exists to catch,
    on the one page that test does not cover."""
    import re
    from render.ledger_site import render_ledger
    from engine.ledger import ledger_summary

    page = render_ledger([], ledger_summary([]))
    prose = re.sub(r"<[^>]+>", " ", page)
    for banned in ("rival", "opponent", "waiver"):
        assert banned not in prose.lower(), \
            f"the public record promises {banned!r}, which this product cannot see"


def test_one_unreadable_store_does_not_stop_the_others(tmp_path, capsys) -> None:
    """load_ledger -> _collapse raises when a call_id carries two different
    graded outcomes, and nothing caught it: the process died partway through
    the store loop, stores sorted after the poisoned one were never graded,
    and the public page was never regenerated.

    That duplicate is an ANTICIPATED state, not a freak one — .gitattributes
    sets merge=union on the ledger so a Monday/Tuesday push race concatenates
    instead of conflicting, which is the very thing _collapse resolves. So its
    unresolvable case meant a total outage recurring every Monday until a human
    hand-edited a JSONL, while new pending calls piled up behind it.

    Contained, but never swallowed: the run still goes red so the cron files
    its issue. A store nobody can read is calls that will never settle."""
    import run.monday as monday
    from engine.ledger import GRADED, LedgerCall, ledger_path, record_calls

    def call(store, cid, outcome):
        return LedgerCall(
            call_id=cid, source="slot", league_id=store, season="2024", week=10,
            roster_id=1, slot="WR", pick_id="p", pick_name="Pick",
            over_id="o", over_name="Over", confidence=0.65,
            recorded_at="2024-11-05T12:00:00+00:00", status=GRADED,
            outcome=outcome, pick_points=20.0, over_points=5.0,
            graded_at="2024-11-12T12:00:00+00:00")

    good = "typed-ppr-12-2024"
    bad = "typed-standard-12-2024"       # sorts BEFORE the good one
    record_calls(ledger_path(tmp_path, good), [call(good, "g1", "hit")])
    # Two different graded outcomes for one call_id — what merge=union can make.
    path = ledger_path(tmp_path, bad)
    record_calls(path, [call(bad, "x1", "hit")])
    with path.open("a", encoding="utf-8") as handle:
        import dataclasses, json
        handle.write(json.dumps(dataclasses.asdict(call(bad, "x1", "miss"))) + "\n")

    code = monday.main(["--processed-dir", str(tmp_path), "--dry-run",
                        "--out", str(tmp_path / "site")])
    out = capsys.readouterr()
    assert good in out.out, "a readable store was skipped because another was not"
    assert "UNREADABLE" in out.err
    assert code == 1, "an unreadable store must still turn the run red"


def test_a_stuck_call_is_reported_even_when_nothing_new_is_recorded() -> None:
    """Staleness was max(week of any call this season) - call.week, so it only
    grew while the TUESDAY run kept recording. Every situation that actually
    strands calls also stops recording — a broken send cron, total churn, the
    end of the season — so those calls stayed "0 weeks old" and were never
    reported. Week 17-18 calls were structurally unreportable. That is exactly
    the silence the alarm exists to break."""
    from run.monday import _weeks_old

    class _C:
        def __init__(self, season, week):
            self.season, self.week = season, week

    stranded = _C("2024", 10)
    calls = [stranded]                     # nothing newer ever recorded
    assert _weeks_old(stranded, calls) == 0, "the old ledger-relative behaviour"
    # Against the calendar it is correctly six weeks old.
    assert _weeks_old(stranded, calls, now_week=16, now_season="2024") == 6
    # A different season falls back rather than subtracting across seasons.
    assert _weeks_old(stranded, calls, now_week=3, now_season="2025") == 0
