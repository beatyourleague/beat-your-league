"""Final review (Oct 24 2026) — the report branch's guards.

One test (or a small group) per finding, each docstring stating the
reproduction it was written against. Nothing here touches the network:
schedules are written to a temporary cache, and the real cache is read only
where the test says so.
"""

from __future__ import annotations

import ast
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import render.report as rr
import run.solo as solo
from engine.availability import Status

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"


# --------------------------------------------------------------------- #
# PIPE-1 — team-defense rows are not box scores
# --------------------------------------------------------------------- #

GAME_FIELDS = ["season", "game_type", "week", "gameday", "gametime", "away_team",
               "home_team", "away_score", "home_score"]
WEEK7 = [(7, "2026-10-22", "20:15", "NE", "CHI"),
         (7, "2026-10-25", "13:00", "SF", "ATL"),
         (7, "2026-10-26", "20:15", "DAL", "PHI"),
         (8, "2026-10-29", "20:15", "NE", "SF"),
         (8, "2026-11-01", "13:00", "CHI", "ATL"),
         (8, "2026-11-02", "20:15", "DAL", "PHI"),
         (18, "2027-01-10", "13:00", "NE", "CHI")]
TUESDAY = datetime(2026, 10, 27, 16, 17, tzinfo=timezone.utc)


def _games(tmp_path: Path, games=WEEK7) -> Path:
    cache = tmp_path / "nflverse"
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "games.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GAME_FIELDS)
        writer.writeheader()
        for week, day, clock, away, home in games:
            writer.writerow({"season": "2026", "game_type": "REG", "week": week,
                             "gameday": day, "gametime": clock, "away_team": away,
                             "home_team": home, "away_score": 17, "home_score": 24})
    return cache


def test_defense_rows_do_not_pass_for_missing_player_box_scores(tmp_path) -> None:
    """Reproduction (final review PIPE-1): week-6 rows removed from
    stats_player_week_2026.csv for every team but SEA/DEN, stats_team_week
    left intact — load_week_data PASSED the completeness guard, because
    merge_defenses had already folded a DEF-<team> row (carrying its team)
    into weekly[W-1] for all 28 teams. Drake Maye's projection went 18.2 ->
    15.1 and the report still said "Box scores through Week 6, every game."
    Only PLAYER rows count now, as in engine/ledger.py's twin check."""
    cache = _games(tmp_path)
    teams = ("NE", "CHI", "SF", "ATL", "DAL", "PHI")
    players_for = ("NE", "CHI", "SF", "ATL")              # DAL/PHI player rows lost
    weekly = {7: {**{f"00-{t}": {"team": t} for t in players_for},
                  **{f"DEF-{t}": {"team": t} for t in teams}}}
    with pytest.raises(solo.SoloError, match="DAL@PHI"):
        solo.assert_week_is_complete(cache, "2026", 8, weekly, now=TUESDAY)
    # Every player row in: the same week passes, defenses or not.
    weekly[7].update({"00-DAL": {"team": "DAL"}, "00-PHI": {"team": "PHI"}})
    solo.assert_week_is_complete(cache, "2026", 8, weekly, now=TUESDAY)


# --------------------------------------------------------------------- #
# PIPE-3 — a toss-up is not also "decided" by the rising hold
# --------------------------------------------------------------------- #

class _Everyone:
    def classify(self, _pid):
        return SimpleNamespace(status=Status.ACTIVE)


def _pick(slot, pid, mean, alt, alt_mean):
    from engine.week_report import SlotPick
    return SlotPick(slot=slot, slot_index=0, player_id=pid,
                    projection=SimpleNamespace(mean=mean, games=6),
                    status=None, confidence=None,
                    confidence_gate="held: the bench option's role is growing (Kyle Pitts)",
                    alternative_id=alt,
                    alternative_projection=SimpleNamespace(mean=alt_mean, games=6),
                    flags=[])


def test_the_rising_hold_line_names_only_the_slots_it_decides() -> None:
    """Reproduction (final review PIPE-3, roster H, Week 7 as of Oct 20): the
    preheader and plan item 1 read "Travis Kelce or Kyle Pitts at TE — a
    toss-up, keep whichever you have", and item 3 read "Travis Kelce and
    Jonathan Taylor start — no odds against Kyle Pitts … the lineup stands".
    The toss-up stays (it is the honest reading of 9.7 vs 9.4 against a
    riser); the hold line drops the slot the toss-up already covers, so it
    reads "Jonathan Taylor starts". Wording only: no seat or number moves."""
    from engine.solo_report import rising_hold_items, row_is_tossup

    te = _pick("TE", "kelce", 9.66, "pitts", 9.4)
    flex = _pick("FLEX", "taylor", 14.1, "pitts", 9.4)
    nobody = SimpleNamespace(name=lambda pid: {"kelce": "Travis Kelce", "taylor":
                                               "Jonathan Taylor", "pitts": "Kyle Pitts"}[pid])
    assert row_is_tossup(te, _Everyone()) and not row_is_tossup(flex, _Everyone())
    # A bench player with no game this season prints no figure, so no toss-up.
    te.alternative_projection = SimpleNamespace(mean=9.4, games=0)
    assert not row_is_tossup(te, _Everyone())
    te.alternative_projection = SimpleNamespace(mean=9.4, games=6)

    cand = {"recent": 6.5, "earlier": 2.2, "earlier_weeks": [1, 2, 3, 4]}
    held = [(te, cand), (flex, cand)]
    kept = [(p, c) for p, c in held if not row_is_tossup(p, _Everyone())]
    [item] = rising_hold_items(kept, nobody)
    assert item["action"].startswith("Jonathan Taylor starts")
    assert "Kelce" not in item["action"]

    # And build_solo_report really filters with it (mutation: passing
    # `rising_held` straight through brings the contradiction back).
    source = (REPO / "engine" / "solo_report.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and getattr(node.func, "id", "") == "rising_hold_items"]
    assert calls, "build_solo_report no longer builds the hold line"
    for call in calls:
        first = call.args[0]
        assert isinstance(first, ast.ListComp), "the hold line takes every held pick"
        assert "row_is_tossup" in ast.unparse(first)


# --------------------------------------------------------------------- #
# PIPE-5 / PIPE-6 — the row says what happened
# --------------------------------------------------------------------- #

def test_a_stale_alternative_hold_never_names_a_flex_swap() -> None:
    """Reproduction (final review PIPE-5, roster B, half-PPR 10-team wr3): the
    gate read "held: the bench changed around this slot (Rome Odunze starts at
    WR)" — a RULE-3 re-seat at the third WR slot, FLEX was Kenneth Walker —
    and the note said "a flex swap changed who your best bench player there
    is", a swap that never happened."""
    phrase = rr.gate_phrase("held: the bench changed around this slot "
                            "(Rome Odunze starts at WR)")
    assert "flex" not in phrase.lower()
    assert phrase == "a later swap in your lineup changed who your best bench player there is"


def test_a_defense_that_cannot_play_claims_no_projection() -> None:
    """Reproduction (final review PIPE-6, roster E, Week 7): "DEF Buffalo
    Bills — projection only / OUT — BUF on bye this week" beside a dash, on
    all three surfaces. A certainly-out defense prints no tag, as an on-bye
    QB doesn't; a playing one says it carries no odds."""
    gate = "we don't put odds on defenses — a defense gets its projection"
    assert rr.row_label({"confidence_gate": gate, "status": "out",
                         "projected": None}) == ""
    assert rr.row_label({"confidence_gate": gate, "status": "active"}) == "no odds on defenses"
    # A blank label is not a marked row (the note carries the reason).
    assert not rr.row_marked({"confidence_gate": gate, "status": "out"}, True)


# --------------------------------------------------------------------- #
# PIPE-7, C5 — the text half carries the data age; one betting line
# --------------------------------------------------------------------- #

def test_the_text_half_dates_its_data_like_the_html_does() -> None:
    """Reproduction (final review PIPE-7, Week 7 roster A): `grep -c 'Box
    scores'` = 0 in the .txt and 1 in each HTML; no "Injury and inactive data
    as of" either — and the text is what `run.trial --print` pastes into a
    group chat (principle 3)."""
    from render.email import text_summary
    from tests.test_email import _solo_report

    report = _solo_report()
    basis = rr.availability_basis(report["meta"])
    assert basis in text_summary(report)
    report["meta"]["trial"] = True
    assert basis in text_summary(report)


def test_the_betting_line_is_the_one_phrase_contract_c5_allows() -> None:
    """Reproduction (final review FUN-6/COPY-8): every report, both samples,
    the ledger page and every email carried "no betting picks, no staking
    advice" — a betting word in denial — and render/email.py kept two copies
    of its own. Contract C5: "Projections are analysis, not guarantees — not
    betting picks." with no "staking", from one constant."""
    assert rr.NO_BETTING_LINE.startswith(
        "Projections are analysis, not guarantees — not betting picks.")
    for path in [*(REPO / "render").glob("*.py"), REPO / "rival-report-template.html"]:
        text = path.read_text(encoding="utf-8").lower()
        assert "staking" not in text, f"{path.name} still says 'staking'"
        assert "no betting picks" not in text, f"{path.name} keeps a second wording"
    from render.email import text_summary
    from tests.test_email import _solo_report
    report = _solo_report()
    assert rr.NO_BETTING_LINE in text_summary(report)
    report["meta"]["trial"] = True
    assert rr.NO_BETTING_LINE in text_summary(report)


def test_the_free_report_says_how_to_stop_it() -> None:
    """Reproduction (final review COPY-2): the free report ended "Didn't ask
    for it? Ignore it — you won't hear from us again." — untrue across
    seasons (one per address per SEASON) and silent on the reply-"stop" route
    terms §4 promises. The stop list is checked before every send."""
    from render.email import TRIAL_ONLY
    assert 'Reply "stop"' in TRIAL_ONLY
    assert "won't hear from us again" not in TRIAL_ONLY
    assert re.search(r"Cancel|Reply \"stop\"|only email we.ll send you", TRIAL_ONLY)


# --------------------------------------------------------------------- #
# PIPE-8 — the proving run never empties a directory it did not make
# --------------------------------------------------------------------- #

def _proving(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "run.proving", *args], cwd=REPO,
                          capture_output=True, text=True, timeout=120)


def test_the_proving_run_refuses_a_directory_it_did_not_make(tmp_path) -> None:
    """Reproduction (final review PIPE-8): `python -m run.proving victim 6-6`
    with victim/registry/rosters.json — victim/registry was gone, replaced by
    the proving output; `not-a-span` crashed on int('not') AFTER the rmtree
    had already emptied it; `--help` made a ./--help directory and exited 2.
    Arguments are parsed first, and a non-empty directory without the run's
    own marker is refused before a byte is deleted."""
    victim = tmp_path / "victim"
    (victim / "registry").mkdir(parents=True)
    (victim / "registry" / "rosters.json").write_text("[]")
    done = _proving(str(victim), "6-6")
    assert done.returncode != 0 and "refusing to empty" in done.stderr
    assert (victim / "registry" / "rosters.json").exists()

    fresh = tmp_path / "fresh"
    bad = _proving(str(fresh), "not-a-span")
    assert bad.returncode == 2 and not fresh.exists()
    bad = _proving(str(victim), "not-a-span")
    assert bad.returncode == 2 and (victim / "registry" / "rosters.json").exists()

    helped = _proving("--help")
    assert helped.returncode == 0 and "usage" in helped.stdout
    assert not (REPO / "--help").exists()


def test_a_directory_the_proving_run_made_is_reusable(tmp_path) -> None:
    """The marker is the only licence to empty: a directory an earlier proving
    run left behind (it carries .proving-root) is emptied and reused."""
    import importlib.util
    spec = importlib.util.find_spec("run.proving")
    source = Path(spec.origin).read_text(encoding="utf-8")
    head = source.split("_parser = argparse.ArgumentParser(")[0]
    scope: dict = {"__name__": "proving_head"}
    exec(compile(head, "proving_head", "exec"), scope)
    old = tmp_path / "old"
    old.mkdir()
    (old / scope["MARKER"]).write_text("x")
    (old / "leftover.json").write_text("{}")
    root = scope["scratch_root"](old)
    assert root == old and not (old / "leftover.json").exists()
    assert (old / scope["MARKER"]).exists()
    with pytest.raises(SystemExit):
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("mine")
        scope["scratch_root"](foreign)
    assert (tmp_path / "foreign" / "keep.txt").read_text() == "mine"


# --------------------------------------------------------------------- #
# COPY-1 / GROWTH-1 / GROWTH-2 — the roster report as a first email
# --------------------------------------------------------------------- #

def _roster_report(**over):
    from tests.test_preseason import _report
    return _report(**over)


def test_a_one_time_buyers_roster_report_has_nothing_to_cancel(monkeypatch) -> None:
    """Reproduction (final review COPY-1 / GROWTH-1): a pi_ signup paying after
    Week 7's kickoff got the roster report as its first email, with "Cancel it
    yourself from your own billing page … Unsubscribing from emails alone does
    not stop a subscription … Reports continue to the end of the period
    you've already paid for", and List-Unsubscribe pointed at the Stripe
    portal, where a one-payment buyer has nothing to cancel — beside a welcome
    saying "nothing renews". Every 2026 purchase is one payment, so that is
    the default; one_time=True and seat=ONCE say it explicitly, and a
    subscription (one_time=False) keeps its billing route."""
    from render.preseason import preseason_message

    monkeypatch.setenv("BILLING_PORTAL_URL", "https://billing.stripe.com/p/test")
    report = _roster_report()
    for message in (preseason_message("fan@example.com", "abcdef0123", report),
                    preseason_message("fan@example.com", "abcdef0123", report,
                                      one_time=True),
                    preseason_message("fan@example.com", "abcdef0123", report,
                                      seat=rr.ONCE)):
        assert message.unsubscribe.startswith("mailto:") and "subject=stop" in message.unsubscribe
        for body in (message.html, message.text):
            assert "Nothing renews" in body
            assert "billing" not in body.lower()
            assert "subscription" not in body.lower()
            assert "period you've already paid for" not in body.replace("&#x27;", "'")
    paid = preseason_message("fan@example.com", "abcdef0123", report, one_time=False)
    assert paid.unsubscribe == "https://billing.stripe.com/p/test"
    assert "billing.stripe.com/p/test" in paid.text and "Nothing renews" not in paid.text
    assert "one_time" not in report["meta"], "the caller's report was mutated"


def test_a_bye_hole_names_only_the_players_who_play_it() -> None:
    """Reproduction (final review GROWTH-2, the live sample roster, Week 7):
    "Week 9: no one to start at K / on bye: Chris Boswell, Tyjae Spears" — a
    running back under a kicker hole. The weekly report already names only
    `short`; all three roster-report surfaces do now."""
    from render.preseason import email_html, render, text_summary

    report = _roster_report()
    report["collisions"] = [{"week": 9, "slots": ["K"],
                             "players": ["Chris Boswell", "Tyjae Spears"],
                             "short": ["Chris Boswell"], "out": []}]
    template = rr.TEMPLATE_PATH.read_text(encoding="utf-8")
    for page in (text_summary(report), email_html(report), render(report, template)):
        assert "on bye: Chris Boswell" in page
        assert "Tyjae Spears" not in page.split("on bye:")[1].split("\n")[0][:80]


def test_the_mid_season_roster_report_is_a_useful_first_email(monkeypatch) -> None:
    """Final review, business #2: for every Thursday-to-Monday buyer the roster
    report is the only email between paying and Tuesday, and it read like the
    August template — De'Von Achane listed as "RB5 of 97 · 20.2 a game" with no
    IR note. In-season it now opens with the day the weekly report lands,
    names who can't play today (the reserve list), and carries this season's
    record beside last season's — the figures the weekly row prints. Facts
    only: no %, no projection, nothing recorded."""
    from engine.preseason import build_preseason_report
    from render.preseason import email_html, render, text_summary
    from tests.test_preseason import _directory, _prior, _spec

    weekly = {w: {"p-qb": {"passing_yards": "250", "passing_tds": "2"},
                  "p-wr1": {"receptions": "6", "receiving_yards": "70"}}
              for w in range(1, 7)}
    weekly[7] = {"p-qb": {"passing_yards": "400", "passing_tds": "5"}}  # in progress
    report = build_preseason_report(
        _spec(), _directory(), _prior({"p-rookie"}), "2026",
        REPO / "data" / "raw" / "nflverse", season_started=True, from_week=7,
        byes={"BAL": 13}, roster_out={"p-rb1": "on injured reserve"}, weekly=weekly)
    report["meta"]["next_report"] = {"week": 8, "lands_on": "2026-10-27"}
    qb = next(r for r in report["roster"] if r["player_id"] == "p-qb")
    assert qb["season_so_far"]["games"] == 6, "an unfinished week counted"
    assert report["roster"][-1]["season_so_far"] is None        # rookie: absent, never 0
    assert report["meta"]["through_week"] == 6
    assert report["cant_play"] == [{"name": "Bruiser One", "position": "RB",
                                    "team": "BAL", "why": "on injured reserve"}]
    template = rr.TEMPLATE_PATH.read_text(encoding="utf-8")
    surfaces = {"text": text_summary(report), "email": email_html(report),
                "browser": render(report, template)}
    for name, page in surfaces.items():
        prose = re.sub(r"<style\b.*?</style>|<[^>]+>", " ", page, flags=re.S)
        assert "Your Week 8 report lands Tuesday, Oct 27." in prose, name
        assert "right now" in prose.lower() and "on injured reserve" in prose, name
        # A count is glued to its number on the HTML halves (a no-break space).
        assert re.search(r"2026: \d+\.\d a game over\s6", prose), name
        assert "%" not in prose, f"{name} carries a percentage"
        assert prose.index("Your Week 8 report lands") < prose.index("standing report"), name
    assert "projected" not in json.dumps(report) and "confidence" not in json.dumps(report)


def test_the_next_weekly_report_is_named_only_when_certain(tmp_path, monkeypatch) -> None:
    """The lede is a promise about a date, so it is said only when the
    schedule makes it certain: the week has kicked off (otherwise the buyer's
    first email is THIS week's report), and it is not the last week."""
    from engine.preseason import next_weekly_report

    cache = _games(tmp_path)
    saturday = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
    assert next_weekly_report(cache, "2026", 7, saturday) == {"week": 8, "lands_on": "2026-10-27"}
    before = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
    assert next_weekly_report(cache, "2026", 7, before) is None
    assert next_weekly_report(cache, "2026", 18,
                              datetime(2027, 1, 11, tzinfo=timezone.utc)) is None
    # An unreadable schedule names nothing (never a guessed Tuesday).
    def unreadable(*_a, **_k):
        raise solo.SoloError("no schedule")
    monkeypatch.setattr(solo, "week_first_kickoff", unreadable)
    assert next_weekly_report(cache, "2026", 7, saturday) is None
    monkeypatch.undo()
    # The same Tuesday the season clock names (one rule, run.solo).
    from render.live_sample import next_report_day
    assert next_report_day(cache, "2026", 7) == solo.next_report_day(cache, "2026", 7)


# --------------------------------------------------------------------- #
# COPY-4 / COPY-7 / COPY-9 / business #6 — the welcome email
# --------------------------------------------------------------------- #

def test_a_playoff_pass_welcome_names_the_playoff_pass() -> None:
    """Reproduction (final review COPY-4): welcome_message(..., one_time=True)
    printed "You bought the Rest-of-Season Pass" for a $19 Playoff Pass
    purchase — the legally owed acknowledgment naming a product the buyer did
    not buy. Contract C4: playoff=True names the Playoff Pass and its $19."""
    from render.welcome import PLAYOFF_PRICE, welcome_message

    message = welcome_message("a@example.com", "season", "abcdef0123", "2026",
                              playoff=True, week=13)
    for body in (message.text, message.html):
        assert "the Playoff Pass" in body and PLAYOFF_PRICE in body
        assert "Rest-of-Season" not in body
        assert "Nothing renews" in body or "nothing renews" in body
    default = welcome_message("a@example.com", "season", "abcdef0123", "2026",
                              one_time=True, week=8)
    assert "the Rest-of-Season Pass" in default.text and "Playoff" not in default.text


def test_the_refund_terms_name_a_second_purchase_never_a_re_subscription() -> None:
    """Reproduction (final review COPY-9): every one-time welcome ended its
    terms "One per person, and a re-subscription after a refund is final." —
    subscription vocabulary under a one-payment pass. Contract C5."""
    from render.welcome import REFUND_TERMS, welcome_message
    assert "a second purchase after a refund is final" in REFUND_TERMS
    text = welcome_message("a@example.com", "season", "abcdef0123", "2026",
                           one_time=True, week=8).text
    assert "re-subscription" not in text and "second purchase after a refund" in text


def test_a_seat_holder_is_told_a_reset_can_release_the_seat() -> None:
    """Reproduction (final review COPY-7): a pass buyer can reset every seat
    (run/seat_resets.py) and released holders are deliberately not told — and
    nothing a seat holder read said it could happen."""
    from render.welcome import SEAT_RESET_NOTE, welcome_message
    message = welcome_message("seat@example.com", "seat", "abcdef0123", "2026", week=8)
    assert SEAT_RESET_NOTE in message.text
    assert "resets" in SEAT_RESET_NOTE and "claim it again" in SEAT_RESET_NOTE


def test_odds_from_week_4_is_promised_only_before_week_4() -> None:
    """Final review, business #6: a Week-8 buyer's welcome promised "odds on
    the close calls from Week 4 (Week 2 for a 12-team PPR standard lineup)" —
    a start already behind them. From Week 4 on it says odds on the close
    calls, full stop; before it (and when the week can't be read) the
    original promise stands."""
    from render.welcome import NEXT_TUESDAY, NEXT_TUESDAY_LIVE, welcome_message

    late = welcome_message("a@example.com", "season", "abcdef0123", "2026",
                           one_time=True, week=8).text
    assert NEXT_TUESDAY_LIVE in late and "from Week 4" not in late
    early = welcome_message("a@example.com", "season", "abcdef0123", "2026",
                            one_time=True, week=2).text
    assert NEXT_TUESDAY in early
    unknown = welcome_message("a@example.com", "season", "abcdef0123", "2026",
                              one_time=True).text            # no purchase clock
    assert NEXT_TUESDAY in unknown


# --------------------------------------------------------------------- #
# The launch email (copy improvements)
# --------------------------------------------------------------------- #

CLOCK = {"season": "2026", "week": 7, "last_week": 18, "lands_on": "2026-10-27",
         "first_kickoff": "2026-10-23T00:15:00Z", "phase": "season"}


def test_the_launch_email_names_the_week_and_states_its_terms(monkeypatch) -> None:
    """Final review copy improvement: the one message the whole waitlist gets
    was generic — no mid-season frame, no price, no risk reversal — and said
    "You type your roster once", which roster updates contradict. It now names
    the week the buyer's first lineup is for (the join page's rule: this week
    before its kickoff, next week after), the three things the report does,
    and the price with its one-payment and refund terms."""
    monkeypatch.setenv("LOG_SECRET", "x")
    import run.waitlist as wl

    sunday = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
    subject, body, preview = wl.compose("https://x/join/", "S", CLOCK, sunday)
    assert subject == "It's open: your Week 8 lineup lands Tuesday"
    assert "in time for Week 8" in body and "Week 8" in preview
    flat = " ".join(body.split())
    for term in ("$29, one payment", "nothing renews",
                 "Refunds are no-questions until your first weekly report's week kicks off",
                 "every slot decided, every close call explained", "if/then",
                 "only email you'll get", 'reply "unsubscribe"'):
        assert term in flat, term
    assert "type your roster once" not in flat.lower()
    assert body.count("http") == 1
    for claim in wl.FORBIDDEN_CLAIMS:
        assert claim not in flat.lower(), claim
    # Before the week's kickoff the buyer gets THIS week's lineup.
    tuesday = {**CLOCK, "week": 8, "lands_on": "2026-11-03",
               "first_kickoff": "2026-10-30T00:15:00Z"}
    assert wl.compose("u", "S", tuesday, datetime(2026, 10, 28, tzinfo=timezone.utc))[0] \
        == "It's open: get your Week 8 lineup before kickoff"
    # A clock nobody rebuilt, or out of season: no week named.
    stale = datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert wl.compose("u", "S", CLOCK, stale)[0] == wl.SUBJECT
    assert wl.compose("u", "S", {**CLOCK, "phase": "over"}, sunday)[0] == wl.SUBJECT
    # From Week 13, with the $19 link on the join page, the offer is the Playoff Pass.
    late = {**CLOCK, "week": 13, "lands_on": "2026-12-08",
            "first_kickoff": "2026-12-11T01:15:00Z"}
    monkeypatch.setattr(wl, "_playoff_link_live", lambda: True)
    assert "The Playoff Pass is $19" in wl.compose("u", "S", late,
                                                   datetime(2026, 12, 2, tzinfo=timezone.utc))[1]
    monkeypatch.setattr(wl, "_playoff_link_live", lambda: False)
    assert "Rest-of-Season Pass is $29" in wl.compose(
        "u", "S", late, datetime(2026, 12, 2, tzinfo=timezone.utc))[1]


def test_the_launch_email_keeps_the_saved_roster_line(monkeypatch) -> None:
    """The saved-roster line, the stop line and the subject all survive the
    rewrite, in both halves."""
    monkeypatch.setenv("LOG_SECRET", "x")
    import run.waitlist as wl
    from engine.nflverse_backtest import TEMPLATE_T1
    from run.refs import encode_roster

    from render.live_sample import LIVE_ROSTER
    ref = encode_roster("season", "ppr", list(TEMPLATE_T1), list(LIVE_ROSTER))
    sunday = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
    plain, saved = wl.messages(["a@example.com", "b@example.com"], "https://x/join/",
                               {"b@example.com": ref}, clock=CLOCK, now=sunday)
    assert plain.subject == saved.subject == "It's open: your Week 8 lineup lands Tuesday"
    assert wl.SAVED_LINE in saved.text and wl.SAVED_LINE not in plain.text
    assert "<title>It&#x27;s open: your Week 8 lineup lands Tuesday</title>" in saved.html
    assert plain.unsubscribe.endswith("?subject=unsubscribe")


# --------------------------------------------------------------------- #
# COPY-4's site surfaces, and the template's phone rule
# --------------------------------------------------------------------- #

def _node(script: str):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_league_pass_comparison_leaves_with_the_29_dollar_pass() -> None:
    """Reproduction (final review COPY-4): league-pass.html argued "Twelve
    Rest-of-Season Passes would cost $348" with no week logic, so from Week 13
    — when the only individual pass on sale can be $19 — it compared against a
    price that isn't offered. The sentence goes from Week 13 (the landing's
    first-weekly-report rule); the $69 sentence after it is true at any price."""
    page = (SITE / "league-pass.html").read_text(encoding="utf-8")
    assert '<span id="lp-compare">Twelve Rest-of-Season Passes would cost $348' in page
    start = page.index("if (window.fetch) {\n  fetch(\"week.json\"")
    snippet = page[start:page.index("// AFTER every href", start)]

    def removed(clock: dict, now: str) -> bool:
        return _node(f"""
let gone = false;
const document = {{ getElementById: () => ({{ remove() {{ gone = true; }} }}) }};
const RealDate = Date;
globalThis.Date = class extends RealDate {{
  constructor(...a) {{ super(...(a.length ? a : ["{now}"])); }} }};
const window = {{ fetch: true }};
const fetch = () => Promise.resolve({{ ok: true, json: () => ({json.dumps(clock)}) }});
{snippet}
setTimeout(() => console.log(JSON.stringify(gone)), 20);
""")
    week7 = {"week": 7, "first_kickoff": "2026-10-23T00:15:00Z", "phase": "season"}
    assert removed(week7, "2026-10-24T12:00:00Z") is False
    week12 = {"week": 12, "first_kickoff": "2026-11-26T01:20:00Z"}
    assert removed(week12, "2026-11-25T12:00:00Z") is False     # first report: Week 12
    assert removed(week12, "2026-11-27T12:00:00Z") is True      # first report: Week 13
    assert removed({**week12, "phase": "over"}, "2026-11-27T12:00:00Z") is False


def test_the_landing_offer_in_structured_data_follows_the_playoff_switch() -> None:
    """Reproduction (final review COPY-4): showPlayoffPass relabelled the card
    to $19 and left the JSON-LD Offer at price "29" for every crawler that
    runs the page's script."""
    page = (SITE / "index.html").read_text(encoding="utf-8")
    start = page.index("function showPlayoffPass(")
    fn = page[start:page.index("\n}\n", start) + 2]
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
    out = _node(f"""
let PASS_LABEL = "";
const block = {{ textContent: {json.dumps(ld)} }};
const document = {{
  getElementById: () => null,
  querySelector: (sel) => (sel.includes("ld+json") ? block : null),
  createTextNode: () => ({{}}), createElement: () => ({{}}),
}};
{fn}
showPlayoffPass(13);
const data = JSON.parse(block.textContent);
console.log(JSON.stringify(data["@graph"].flatMap((n) => n.offers || [])));
""")
    assert [o["price"] for o in out] == ["19"]
    assert "Playoff Pass" in out[0]["description"] and "Week 13" in out[0]["description"]


def test_the_report_pages_lose_the_sheet_frame_on_a_phone() -> None:
    """Final review (funnel improvement, D15): thanks.html and how-it-works.html
    run the paper edge to edge at 480px and under, while every generated report
    page (both samples, this week's, the roster report) kept a 14px/8px grey
    frame and a bordered sheet at 390. The template carries the same rule."""
    template = rr.TEMPLATE_PATH.read_text(encoding="utf-8")
    # Moved with the card stack (contract C3, Oct 2026): the paper runs edge
    # to edge at EVERY width now — no grey desk, no bordered sheet — so the
    # phone needs no rule of its own to lose them.
    style = rr.extract_design(template)[0]
    assert re.search(r"body\{background:var\(--paper\);", style), \
        "the template lost its paper page"
    assert not re.search(r"\.report\{[^}]*(border|box-shadow|background:#)", style)
    assert "#E7E4DA" not in style, "the grey desk is back"
    from render.preseason import render
    page = render(_roster_report(), template)
    assert "body{background:var(--paper);" in page


def test_a_change_notice_gives_a_one_time_pass_the_stop_route_not_a_billing_page() -> None:
    """Final review COPY-1, second half (reproduced): run/notice.py chose the
    way out from is_league_seat alone, so a $29 one-payment buyer's terms
    notice told them to cancel from a billing page that has nothing to
    cancel, and its List-Unsubscribe pointed there too."""
    from datetime import date
    from types import SimpleNamespace
    from render.report import ONCE_STOP_BODY
    from run import notice
    sub = SimpleNamespace(email="fan@example.com", is_league_seat=False, one_time=True)
    message = notice.notice_message(sub, "terms", date(2026, 11, 1), "Wording.",
                                    "https://beatyourleague.com")
    assert ONCE_STOP_BODY in message.text and "billing page" not in message.text
    assert message.unsubscribe and message.unsubscribe.startswith("mailto:")


def test_the_note_names_no_reason_a_row_does_not_print() -> None:
    """Reviewer (report), reproduced: an OUT defense's row prints a dash and
    no "projection only" (PIPE-6), but the note under the lineup still said
    "defenses get a projection only". The note's reasons come from the rows."""
    from render.report import note_gates
    out_def = {"slot": "DEF", "status": "out", "confidence_gate": "we don't put odds on defenses yet"}
    live_def = {**out_def, "status": "active"}
    bench = {"slot": "QB", "status": "active", "confidence_gate": "no bench QB"}
    assert note_gates([out_def, bench]) == {"no bench QB"}
    assert note_gates([live_def]) == {"we don't put odds on defenses yet"}


def test_the_roster_report_way_out_follows_the_purchase() -> None:
    """Reviewer (report): the intake passed only `seat` to preseason_message,
    so its way out followed the site-wide SELLING_ONE_TIME flag rather than
    the purchase; a sub_ subscription would have been told its pass ends on
    its own. The call now passes one_time from the purchase id."""
    import inspect
    from run import intake
    source = inspect.getsource(intake._send_first_files)
    assert '{"one_time": (signup.subscription_id or "").startswith("pi_")}' in source
