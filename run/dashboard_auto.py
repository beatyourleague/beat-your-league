"""The dashboard's background updater — `make dashboard-auto`.

Usage:
    python -m run.dashboard_auto install     (make dashboard-auto)
    python -m run.dashboard_auto uninstall   (make dashboard-auto-off)
    python -m run.dashboard_auto status      (make dashboard-auto-status)

`make dashboard-live` keeps the page fresh only while its Terminal tab stays
open and the Mac stays awake. This installs a per-user LaunchAgent instead:
launchd runs one `python -m run.dashboard --auto` build every 15 minutes, and
once more after the Mac wakes if a build was missed. The open tab keeps
reloading itself, as it does in live mode. Each build is a new process, so a
key added to .env counts at the next build.

The decisions, each for a reason:

- **No server of ours.** launchd is the Mac's own scheduler; the page is
  still a file on this disk, read-only everywhere (run/dashboard.py).
- **The plist is generated at install time** from where this repository
  sits, and written only into the LaunchAgents folder. No committed file
  carries a path from this Mac.
- **It holds no secret.** The only environment it sets is PATH (with
  Homebrew's folders, or the launch check can't find `gh`). Keys stay in
  .env, which each build reads itself; the plist never copies one.
- **Its log is gitignored** (data/dashboard-updater.log) and holds one line a
  build: the time and whether it worked. It is rotated at about 512 KB.
- **It refuses in CI**, like the dashboard itself, and off macOS.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import run.stats as stats

LABEL = "com.beatyourleague.dashboard"
AUTO_MINUTES = 15
REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
# launchd starts a job with a bare PATH. Homebrew's folders come first so the
# launch check finds `gh` (check_secrets) and never reports a false owner step.
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
LOG_REL = "data/dashboard-updater.log"
LOG_MAX_BYTES = 512_000
PAGE_REL = "data/dashboard.html"

Runner = Callable[[list[str]], "tuple[int, str]"]


def plist_path(agent_dir: Path | None = None) -> Path:
    return (agent_dir or LAUNCH_AGENTS) / f"{LABEL}.plist"


def installed(agent_dir: Path | None = None) -> bool:
    return plist_path(agent_dir).is_file()


def venv_python(repo: Path = REPO_ROOT) -> Path:
    """The repository's own venv python, as a path (never resolved: the
    venv's symlink is what makes it the venv)."""
    candidate = repo / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else Path(sys.executable).absolute()


def plist_dict(repo: Path, python: Path, minutes: int = AUTO_MINUTES) -> dict:
    log = str(repo / LOG_REL)
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "run.dashboard", "--auto",
                             "--every", str(minutes)],
        "WorkingDirectory": str(repo),
        "StartInterval": minutes * 60,
        "RunAtLoad": True,
        "EnvironmentVariables": {"PATH": PATH_VALUE},
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def plist_bytes(repo: Path, python: Path, minutes: int = AUTO_MINUTES) -> bytes:
    return plistlib.dumps(plist_dict(repo, python, minutes), fmt=plistlib.FMT_XML, sort_keys=True)


def rotate_log(path: Path | None = None, max_bytes: int | None = None) -> None:
    """Keep the log small: past the limit it becomes .1 (replacing the old
    one) and the next build starts a new file. A rename, never a truncate,
    because launchd holds the file open while this build writes to it."""
    path = path or (REPO_ROOT / LOG_REL)
    try:
        if path.stat().st_size > (max_bytes or LOG_MAX_BYTES):
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def _launchctl(args: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, type(exc).__name__
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _say(text: str) -> None:
    print(text, file=sys.stderr)


def install(repo: Path, agent_dir: Path | None = None, run: Runner | None = None,
            uid: int | None = None, python: Path | None = None,
            wait: Callable[[float], None] | None = None) -> int:
    run = run or _launchctl
    uid = os.getuid() if uid is None else uid
    target = plist_path(agent_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Replacing an installed agent: unload the old one first (fails quietly
    # when there is none).
    run(["bootout", f"gui/{uid}/{LABEL}"])
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_bytes(plist_bytes(repo, python or venv_python(repo)))
    os.replace(tmp, target)
    code, out = 1, ""
    for _attempt in range(3):
        code, out = run(["bootstrap", f"gui/{uid}", str(target)])
        if code == 0:
            break
        (wait or time.sleep)(1)     # a bootout can take a moment to finish
    if code != 0:
        _say(f"launchd wouldn't start the updater ({out.strip()[:200] or code}). "
             f"Run make dashboard-auto-off, then make dashboard-auto again.")
        return 1
    _say(f"The dashboard now rebuilds itself every {AUTO_MINUTES} minutes in the background, "
         f"also after the Mac wakes. The first build runs now and takes about a minute.\n"
         f"Open it with make dashboard; the tab then reloads itself.\n"
         f"If macOS shows \"Background Items Added\", leave it allowed.\n"
         f"make dashboard-auto-status shows how it's doing; make dashboard-auto-off stops it.")
    return 0


def uninstall(agent_dir: Path | None = None, run: Runner | None = None,
              uid: int | None = None) -> int:
    run = run or _launchctl
    uid = os.getuid() if uid is None else uid
    target = plist_path(agent_dir)
    code, _out = run(["bootout", f"gui/{uid}/{LABEL}"])
    had = target.is_file()
    if had:
        target.unlink()
    if not had and code != 0:
        _say("The background updater isn't installed. Nothing to stop.")
        return 0
    _say("The background updater is off. The page keeps its last numbers and says how old they "
         "are; make dashboard builds it again.")
    return 0


def _print_field(text: str, name: str) -> str | None:
    for line in text.splitlines():
        key, sep, value = line.strip().partition(" = ")
        if sep and key == name:
            return value.strip()
    return None


def _ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / 86400:.0f} days ago"


def status(repo: Path, agent_dir: Path | None = None, run: Runner | None = None,
           uid: int | None = None, now: float | None = None) -> int:
    run = run or _launchctl
    uid = os.getuid() if uid is None else uid
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    if not installed(agent_dir):
        _say("The background updater is off. make dashboard-auto turns it on.")
        code = 0
    else:
        code, out = run(["print", f"gui/{uid}/{LABEL}"])
        if code != 0:
            _say("The updater is installed but launchd hasn't loaded it. "
                 "Run make dashboard-auto again to reload it.")
            code = 1
        else:
            state = _print_field(out, "state") or "unknown"
            last = _print_field(out, "last exit code")
            runs = _print_field(out, "runs")
            words = {"running": "building now", "not running": "waiting for its next build"}
            _say(f"The background updater is on, every {AUTO_MINUTES} minutes: "
                 f"{words.get(state, state)}.")
            if runs:
                _say(f"Builds since it was loaded: {runs}.")
            if last is not None:
                ok = last in ("0", "(never exited)")
                _say("The last build worked." if last == "0" else
                     "No build has finished yet." if last == "(never exited)" else
                     f"The last build failed (exit {last}). The log below says why.")
                code = 0 if ok else 1
    page = repo / PAGE_REL
    if page.is_file():
        _say(f"The page was written {_ago(now - page.stat().st_mtime)}.")
    log = repo / LOG_REL
    try:
        lines = [ln for ln in log.read_text(encoding="utf-8", errors="replace").splitlines() if ln]
    except OSError:
        lines = []
    if lines:
        _say("Last lines of " + LOG_REL + ":")
        for line in lines[-3:]:
            _say("  " + line[:300])
    return code


def main(argv: list[str] | None = None, environ=None, agent_dir: Path | None = None,
         run: Runner | None = None, repo: Path = REPO_ROOT) -> int:
    environ = os.environ if environ is None else environ
    argv = sys.argv[1:] if argv is None else argv
    if stats.in_ci(environ):
        _say("make dashboard-auto does not run in CI: it is for your own Mac.")
        return 2
    if sys.platform != "darwin" and run is None:
        _say("make dashboard-auto uses launchd, which is macOS only. "
             "Use make dashboard-live instead.")
        return 2
    command = argv[0] if argv else ""
    if command == "install":
        if not stats._gitignored(repo / LOG_REL) or not stats._gitignored(repo / PAGE_REL):
            _say(f"{LOG_REL} or {PAGE_REL} is not gitignored, so the updater won't write there.")
            return 2
        return install(repo, agent_dir, run)
    if command == "uninstall":
        return uninstall(agent_dir, run)
    if command == "status":
        return status(repo, agent_dir, run)
    _say("Usage: python -m run.dashboard_auto install | uninstall | status")
    return 2


if __name__ == "__main__":
    sys.exit(main())
