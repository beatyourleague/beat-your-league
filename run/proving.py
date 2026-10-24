"""The proving run — `make proving`: weeks 4-8 of 2025, twelve subscribers, every runner.

`python -m run.proving <new dir> 14-18` runs other weeks (the season's end). The
directory must be new, empty, or one an earlier proving run made: anything else
is refused before a byte is deleted.

Every serious bug in this repo lived in a path nobody had executed, so this
executes all of them in sequence on a real past season.

Tuesday -> Saturday -> Monday -> next Tuesday, with a fake mail provider, a
scratch registry, scratch plans, scratch ledger and scratch send log. A
mid-season roster change lands between week 5 and week 6's Saturday.
"""
import csv, json, sys, shutil, datetime as dt
from collections import Counter
from pathlib import Path

import argparse, re, tempfile

# The marker this run writes into its own scratch directory. A directory is
# only ever emptied when it is missing, empty, or carries this file — final
# review PIPE-8: ROOT came straight from sys.argv and was rmtree'd before
# anything else, so `python -m run.proving data 14-18` (a natural reading of
# the documented "<dir>") wiped data/ — registry, ledger, plans, raw cache —
# and a rejected span ("not-a-span") still wiped it first, because the span
# was parsed after the delete. `--help` made a ./--help directory.
MARKER = ".proving-root"


def _span(text: str) -> list[int]:
    found = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?", text.strip())
    if not found:
        raise argparse.ArgumentTypeError(f"weeks must read like 4-8, not {text!r}")
    first, last = int(found.group(1)), int(found.group(2) or found.group(1))
    if not 1 <= first <= last <= 18:
        raise argparse.ArgumentTypeError(f"weeks must be within 1-18, first <= last: {text!r}")
    return list(range(first, last + 1))


def scratch_root(path: Path | None) -> Path:
    """Make (or reuse) the scratch directory, refusing anything this run did
    not create itself. Nothing is deleted before this check passes."""
    if path is None:
        root = Path(tempfile.mkdtemp(prefix="proving-"))
    else:
        root = path
        if root.exists() and not root.is_dir():
            raise SystemExit(f"run.proving: {root} is a file, not a scratch directory")
        if root.is_dir() and any(root.iterdir()) and not (root / MARKER).exists():
            raise SystemExit(
                f"run.proving: refusing to empty {root} — it is not empty and was "
                f"not made by a proving run (no {MARKER} in it). Pass a new "
                f"directory, or leave it out for a fresh temporary one.")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
    (root / MARKER).write_text("written by run.proving; safe to delete\n")
    return root


_parser = argparse.ArgumentParser(
    prog="python -m run.proving",
    description="Drive a past season through every runner into a scratch "
                "directory (never the real registry, ledger, plans or send log).")
_parser.add_argument("root", nargs="?", type=Path, default=None,
                     help="a NEW scratch directory (default: a fresh temporary one)")
_parser.add_argument("weeks", nargs="?", type=_span, default=_span("4-8"),
                     help="the weeks to run, e.g. 4-8 (default) or 14-18")
_args = _parser.parse_args()
# Everything is written under ROOT; the real registry, ledger, plans and send
# log are never touched.
ROOT = scratch_root(_args.root)
SEASON = "2025"
WEEKS = _args.weeks

import run.delivery as delivery
import run.tuesday as tuesday
import run.saturday as saturday
import run.monday as monday
from run.refs import encode_roster
from engine.nflverse_backtest import (build_universe, allocate, TEMPLATE_T1, RAW_DIR)
from engine.scoring import preset
from ingest.nflverse import season_rows, season_teams

# Every send below goes to Fake, so the send-log keys (run/digest.py) may use a
# throwaway LOG_SECRET when the owner's isn't in this shell.
import os as _os
_os.environ.setdefault("LOG_SECRET", "proving-simulation-only")

SENT = []
class Fake:
    name = "fake"
    def send(self, m, sender, reply_to):
        SENT.append(m); return f"id-{len(SENT)}"
delivery.SENT_LOG = ROOT / "sent.jsonl"
tuesday.build_provider = lambda *a, **k: Fake()
saturday.build_provider = lambda *a, **k: Fake()

SF = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF")
NKD = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")
SETUPS = [("ppr", 12, TEMPLATE_T1), ("half_ppr", 12, TEMPLATE_T1),
          ("standard", 12, TEMPLATE_T1), ("ppr", 10, TEMPLATE_T1),
          ("ppr", 14, TEMPLATE_T1), ("ppr", 8, TEMPLATE_T1),
          ("ppr", 12, SF), ("half_ppr", 12, NKD), ("ppr", 12, TEMPLATE_T1),
          ("half_ppr", 10, TEMPLATE_T1), ("standard", 14, SF), ("ppr", 12, TEMPLATE_T1)]

prior = season_rows(RAW_DIR, "2024")
rows, subs = [], []
POS = {}
for i, (scoring, size, template) in enumerate(SETUPS):
    universe = build_universe(prior, preset(scoring), season_teams(RAW_DIR, SEASON))
    rosters = allocate(universe, template, size, i, 2.0)
    POS.update(universe.positions)
    full = list(rosters[i % len(rosters)])
    want = {"QB": 3 if "SUPER_FLEX" in template else 2, "RB": 5, "WR": 5, "TE": 2,
            "K": 0 if template == NKD else 1, "DEF": 0 if template == NKD else 1}
    roster = []
    for pos, n in want.items():
        roster += [p for p in full if POS.get(p) == pos or (pos == "DEF" and p.startswith("DEF-"))][:n]
    print(i, scoring, size, len(template), Counter(POS.get(p, p[:3]) for p in roster))
    plan = "league_pass" if i == 11 else "season"
    ref = encode_roster("season", scoring, list(template), roster, league_size=size)
    row = {"email": f"sub{i}@example.com", "ref": ref, "player_ids": roster,
           "slots": list(template), "scoring": scoring, "league_size": size,
           "label": "Your Team", "plan": plan}
    if plan == "league_pass":
        row["covered_by"] = "sub0@example.com"
    rows.append(row)
REG = ROOT / "rosters.json"
REG.write_text(json.dumps(rows))

weekly = season_rows(RAW_DIR, SEASON)
def team_before(pid, week):
    for w in range(week - 1, 0, -1):
        r = (weekly.get(w) or {}).get(pid)
        if r and r.get("team"):
            return r["team"]
    return None

games = [g for g in csv.DictReader(open(RAW_DIR / "games.csv"))
         if g["season"] == SEASON and g["game_type"] == "REG"]
def saturday_of(week):
    days = Counter(g["gameday"] for g in games if int(g["week"]) == week)
    sunday = max(days, key=days.get)
    return dt.datetime.fromisoformat(sunday) - dt.timedelta(days=1) + dt.timedelta(hours=16)

common = ["--registry", str(REG), "--no-paid-check", "--season", SEASON]
log = []
for week in WEEKS:
    n0 = len(SENT)
    code = tuesday.main(common + ["--week", str(week), "--out", str(ROOT / "out"),
                                  "--processed-dir", str(ROOT / "processed"),
                                  "--plans-dir", str(ROOT / "plans")])
    log.append(("tuesday", week, code, len(SENT) - n0))

    if week == 5:
        # A confirmed self-serve update lands midweek: sub0 swaps two players.
        from run.refs import decode_roster
        r0 = rows[0]
        taken = {p for r in rows for p in r["player_ids"]}
        free = sorted((pid for pid, row in (weekly.get(4) or {}).items()
                if POS.get(pid) == "WR" and pid not in taken),
                key=lambda pid: -float((weekly[4][pid].get("targets") or 0)))[:1]
        wr_out = next(p for p in r0["player_ids"] if POS.get(p) == "WR")
        new = [free[0] if p == wr_out else p for p in r0["player_ids"]]
        origin = __import__("hashlib").sha256(r0["ref"].encode()).hexdigest()[:10]
        r0.update(ref=encode_roster("season", "ppr", r0["slots"], new),
                  player_ids=new, origin=origin)
        REG.write_text(json.dumps(rows))
        log.append(("roster change", week, f"{wr_out} -> {free[0]}", ""))

    at = saturday_of(week)
    saturday.roster_statuses = lambda cache, w=week: {
        pid: ("ACT", team_before(pid, w)) for r in rows for pid in r["player_ids"]}
    n0 = len(SENT)
    code = saturday.main(common + ["--week", str(week), "--plans-dir", str(ROOT / "plans"),
                                   "--now", at.isoformat() + "+00:00"])
    log.append(("saturday", week, code, len(SENT) - n0))

    code = monday.main(["--processed-dir", str(ROOT / "processed"),
                        "--out", str(ROOT / "ledger-site")])
    log.append(("monday", week, code, ""))

print("\n\n=========== PROVING RUN SUMMARY ===========")
for entry in log:
    print(*entry)
(ROOT / "sent.json").write_text(json.dumps(
    [{"key": m.key, "to": m.to, "subject": m.subject, "text": m.text} for m in SENT], indent=1))
print("messages:", len(SENT), "· everything under", ROOT)
bad = [e for e in log if e[0] in ("tuesday", "saturday", "monday") and e[2] != 0]
leaks = [m.key for m in SENT if "SUPER_FLEX" in m.text + m.subject]
if bad or leaks:
    print("PROVING RUN FAILED:", bad, leaks[:5])
    sys.exit(1)
