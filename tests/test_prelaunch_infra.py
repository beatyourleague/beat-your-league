"""Pre-launch infrastructure review (Oct 23 2026), pinned.

Each test's docstring is the reproduction it guards. Areas:

- sealed state (INFRA-02): the registry and the stored plans leave the runner
  only encrypted, and a durable encrypted copy survives a lost cache;
- the workflows (INFRA-06/07/14): actions pinned to a commit, least-privilege
  tokens, no expression pasted into a shell, hash-locked installs, a change
  notice that a dispatch token alone cannot send;
- provider errors (SEC-11 / INFRA-15): no address reaches a public log;
- security headers (SEC-10 / INFRA-04/10/12): site/_headers is current;
- the money model (BIZ-03): 2026 is priced as what it sells.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest

import run.statebox as sb

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
KEY = "k" * 40
FAST = sb.MIN_ITERATIONS
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None,
                                   reason="openssl is not installed")


def _registry(root: Path) -> Path:
    reg = root / "data" / "registry"
    (reg / "first-plans" / "2026").mkdir(parents=True)
    (reg / "rosters.json").write_text(json.dumps(
        [{"email": "fan@example.com", "roster": "s3-pc..."}]), encoding="utf-8")
    (reg / "seat-log.jsonl").write_text('{"seat": "pal@example.com"}\n', encoding="utf-8")
    (reg / "first-plans" / "2026" / "w08-abc.json").write_text("{}", encoding="utf-8")
    return reg


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------- #
# sealed state (INFRA-02)
# --------------------------------------------------------------------- #

@needs_openssl
def test_the_registry_round_trips_and_never_leaves_in_plain_text(tmp_path, monkeypatch) -> None:
    """Reproduced (INFRA-02): daily.yml, weekly.yml, saturday.yml, privacy.yml
    and notice.yml cached `data/registry` — addresses, rosters, Stripe ids —
    in plain text, and a pull-request run can restore its base branch's
    caches. Sealed, the cached file holds no address, and opening it gives
    back exactly what went in."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    reg = _registry(tmp_path)
    before = _tree(reg)
    result = sb.seal("registry", tmp_path, iterations=FAST)
    assert result["sealed"] and result["changed"]
    blob = sb.sealed_path("registry", tmp_path).read_bytes()
    for secret in (b"fan@example.com", b"pal@example.com", b"rosters", b"seat-log"):
        assert secret not in blob
    shutil.rmtree(reg)
    assert sb.open_sealed("registry", tmp_path)["opened"]
    assert _tree(reg) == before


def test_no_key_means_no_cache_entry_at_all(tmp_path, monkeypatch) -> None:
    """Fail closed (RULE S1): with CACHE_KEY unset — or too short to be a key —
    a registry with anything in it is never written anywhere, a stale sealed
    copy from the restore is removed so the save step cannot ride it, and the
    CLI exits 1 so the run goes red. With nothing to seal (before launch) it
    is not an error."""
    monkeypatch.delenv("CACHE_KEY", raising=False)
    assert sb.seal("registry", tmp_path)["sealed"] is False          # nothing yet
    assert sb.main(["seal", "registry", "--root", str(tmp_path)]) == 0
    _registry(tmp_path)
    stale = sb.sealed_path("registry", tmp_path)
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    with pytest.raises(sb.SealError, match="CACHE_KEY is not set"):
        sb.seal("registry", tmp_path)
    assert not stale.exists()
    assert sb.main(["seal", "registry", "--root", str(tmp_path)]) == 1
    monkeypatch.setenv("CACHE_KEY", "short")
    with pytest.raises(sb.SealError, match="shorter than"):
        sb.seal("registry", tmp_path)


@needs_openssl
@pytest.mark.parametrize("damage", ["flip", "truncate", "wrong-key", "garbage"])
def test_a_sealed_file_that_fails_its_check_is_never_used(tmp_path, monkeypatch, damage) -> None:
    """RULE S2. A wrong CACHE_KEY, a download cut short and a tampered byte
    all refuse BEFORE anything is decrypted or written — mutation-checked:
    dropping the tag comparison lets the flipped byte through as garbage
    plaintext (tarfile then fails, or worse, a planted archive extracts)."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    reg = _registry(tmp_path)
    sb.seal("registry", tmp_path, iterations=FAST)
    shutil.rmtree(reg)
    path = sb.sealed_path("registry", tmp_path)
    blob = bytearray(path.read_bytes())
    if damage == "flip":
        blob[len(blob) // 2] ^= 0x01
    elif damage == "truncate":
        del blob[-40:]
    elif damage == "garbage":
        blob = bytearray(b"not a sealed file at all")
    else:
        monkeypatch.setenv("CACHE_KEY", "z" * 40)
    path.write_bytes(bytes(blob))
    with pytest.raises(sb.SealError):
        sb.open_sealed("registry", tmp_path)
    assert not reg.exists()
    assert sb.main(["open", "registry", "--root", str(tmp_path)]) == 1


@needs_openssl
def test_the_tag_is_what_refuses_a_flipped_byte(tmp_path, monkeypatch) -> None:
    """The flipped-byte case above, with the decryption itself watched: the
    tag check refuses before openssl is ever asked to decrypt."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    _registry(tmp_path)
    sb.seal("registry", tmp_path, iterations=FAST)
    path = sb.sealed_path("registry", tmp_path)
    blob = bytearray(path.read_bytes())
    blob[60] ^= 0x01
    calls = []
    real = sb._openssl
    monkeypatch.setattr(sb, "_openssl", lambda args, data: calls.append(args) or real(args, data))
    with pytest.raises(sb.SealError, match="integrity"):
        sb.decrypt(bytes(blob), KEY)
    assert calls == []


@needs_openssl
def test_opening_never_overwrites_a_registry_already_there(tmp_path, monkeypatch) -> None:
    """The owner restoring by hand on a machine that already has a registry
    must not lose it to an older sealed copy."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    reg = _registry(tmp_path)
    sb.seal("registry", tmp_path, iterations=FAST)
    (reg / "rosters.json").write_text("newer", encoding="utf-8")
    with pytest.raises(sb.SealError, match="already holds files"):
        sb.open_sealed("registry", tmp_path)
    assert (reg / "rosters.json").read_text(encoding="utf-8") == "newer"


@needs_openssl
def test_a_run_that_changed_nothing_says_so(tmp_path, monkeypatch) -> None:
    """The artifact upload is gated on `changed` (RULE S3) so 24 hourly runs
    a day do not each leave a backup; a run that edits a file says changed."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    reg = _registry(tmp_path)
    sb.seal("registry", tmp_path, iterations=FAST)
    shutil.rmtree(reg)
    sb.open_sealed("registry", tmp_path)
    assert sb.seal("registry", tmp_path, iterations=FAST)["changed"] is False
    (reg / "seat-log.jsonl").write_text("another seat\n", encoding="utf-8")
    assert sb.seal("registry", tmp_path, iterations=FAST)["changed"] is True


class _Response:
    def __init__(self, status: int, payload=None, content: bytes = b"") -> None:
        self.status_code, self._payload, self.content = status, payload, content

    def json(self):
        return self._payload


class _FakeGitHub:
    """GET/DELETE for the four Actions endpoints statebox uses."""

    def __init__(self, artifacts: list[dict], zips: dict[int, bytes], repo_id: int = 7,
                 fail: bool = False) -> None:
        self.artifacts, self.zips, self.repo_id, self.fail = artifacts, zips, repo_id, fail
        self.deleted: list[int] = []

    def get(self, url, headers=None, timeout=None, params=None, allow_redirects=True):
        assert headers["Authorization"] == "Bearer tok"
        if self.fail:
            return _Response(503)
        if url.endswith("/repos/o/r"):
            return _Response(200, {"id": self.repo_id})
        if url.endswith("/actions/artifacts"):
            return _Response(200, {"artifacts": [a for a in self.artifacts
                                                 if a["name"] == params["name"]]})
        artifact_id = int(url.rsplit("/", 2)[-2])
        return _Response(200, content=self.zips[artifact_id])

    def delete(self, url, headers=None, timeout=None):
        self.deleted.append(int(url.rsplit("/", 1)[-1]))
        return _Response(204)


def _artifact(aid: int, created: str, repo: int = 7, head_repo: int = 7,
              branch: str = "main", run: int = 100, name: str = "sealed-registry") -> dict:
    return {"id": aid, "name": name, "expired": False, "created_at": created,
            "size_in_bytes": 1000,
            "archive_download_url": f"https://api.github.com/repos/o/r/actions/artifacts/{aid}/zip",
            "workflow_run": {"id": run, "repository_id": repo, "head_repository_id": head_repo,
                             "head_branch": branch}}


def _zip(name: str, blob: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}.enc", blob)
    return buffer.getvalue()


@needs_openssl
def test_a_lost_cache_restores_from_this_repos_own_backup(tmp_path, monkeypatch) -> None:
    """RULE S3, reproduced as the failure it prevents: the cache entry is
    evicted (7 days unused) and the registry is gone — confirmed seats and
    roster updates with it, which Stripe cannot rebuild. `open --backup`
    takes the newest backup made on this repo's own branch that passes its
    check: a NEWER artifact a fork's pull request uploaded under the same
    name is never a candidate, and a corrupt newest one of ours falls back to
    the next rather than stopping the run."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    reg = _registry(tmp_path)
    before = _tree(reg)
    sb.seal("registry", tmp_path, iterations=FAST)
    good = sb.sealed_path("registry", tmp_path).read_bytes()
    shutil.rmtree(tmp_path / "data")
    planted = _registry(tmp_path / "attacker")
    (planted / "rosters.json").write_text('[{"email": "evil@example.com"}]', encoding="utf-8")
    sb.seal("registry", tmp_path / "attacker", iterations=FAST)
    evil = sb.sealed_path("registry", tmp_path / "attacker").read_bytes()
    gh = _FakeGitHub(
        [_artifact(1, "2026-10-20T00:00:00Z"),
         _artifact(2, "2026-10-22T00:00:00Z"),                         # ours, corrupt
         _artifact(3, "2026-10-23T00:00:00Z", head_repo=99),           # a fork's PR
         _artifact(4, "2026-10-23T05:00:00Z", branch="feature")],      # another branch
        {1: _zip("registry", good), 2: _zip("registry", good[:-5]),
         3: _zip("registry", evil), 4: _zip("registry", evil)})
    github = sb.GitHub("o/r", "tok", session=gh)
    result = sb.restore_backup("registry", github, tmp_path, branch="main")
    assert result["opened"] and "2026-10-20" in result["detail"]
    assert _tree(tmp_path / "data" / "registry") == before
    assert sb.sealed_path("registry", tmp_path).read_bytes() == good


@needs_openssl
def test_a_github_outage_during_restore_is_a_red_run_not_an_empty_registry(
        tmp_path, monkeypatch) -> None:
    """An API failure must not read as "nothing to restore": the runners
    would then write a fresh, partial registry and the seal step would make
    it the newest copy. It exits 1, which gates every save step."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "tok")
    gh = _FakeGitHub([], {}, fail=True)
    real = sb.GitHub.from_env
    monkeypatch.setattr(sb.GitHub, "from_env",
                        classmethod(lambda cls, session=None: real.__func__(cls, session=gh)))
    assert sb.main(["open", "registry", "--backup", "--root", str(tmp_path)]) == 1
    assert not (tmp_path / "data" / "registry").exists()
    # And with no backup ever made, it is simply the first run.
    monkeypatch.setattr(sb.GitHub, "from_env", classmethod(
        lambda cls, session=None: real.__func__(cls, session=_FakeGitHub([], {}))))
    assert sb.main(["open", "registry", "--backup", "--root", str(tmp_path)]) == 0


def test_a_privacy_delete_prunes_every_older_backup() -> None:
    """RULE S4: an encrypted backup still holds a deleted person's rows.
    Everything but this run's own upload goes, for both names."""
    gh = _FakeGitHub([_artifact(1, "a", run=10), _artifact(2, "b", run=11),
                      _artifact(3, "c", run=12, name="sealed-plans"),
                      _artifact(4, "d", run=11, name="sealed-plans")], {})
    assert sb.prune(("registry", "plans"), sb.GitHub("o/r", "tok", session=gh), 11) == 2
    assert sorted(gh.deleted) == [1, 3]


def test_before_launch_an_unkeyed_seal_caches_nothing_and_stays_green(tmp_path, monkeypatch) -> None:
    """The not-set-up-yet convention: with no Stripe key AND no CACHE_KEY,
    nobody has paid, so a registry file (should one exist) is simply not
    cached — exit 0, sealed=false, nothing written. Once the Stripe key is
    set, the same missing CACHE_KEY is a red run."""
    monkeypatch.delenv("CACHE_KEY", raising=False)
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    _registry(tmp_path)
    monkeypatch.setenv("STRIPE_KEY_SET", "false")
    assert sb.main(["seal", "registry", "--root", str(tmp_path)]) == 0
    assert "registry_sealed=false" in out.read_text()
    assert not sb.sealed_path("registry", tmp_path).exists()
    monkeypatch.setenv("STRIPE_KEY_SET", "true")
    assert sb.main(["seal", "registry", "--root", str(tmp_path)]) == 1
    monkeypatch.setenv("CACHE_KEY", "short")              # never excused
    monkeypatch.setenv("STRIPE_KEY_SET", "false")
    assert sb.main(["seal", "registry", "--root", str(tmp_path)]) == 1


# --------------------------------------------------------------------- #
# the workflows (INFRA-02/06/07/14)
# --------------------------------------------------------------------- #

def _docs() -> dict[str, dict]:
    yaml = pytest.importorskip("yaml", reason="pyyaml not installed")
    return {p.name: yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in sorted(WORKFLOWS.glob("*.yml"))}


def _all_steps():
    for name, doc in _docs().items():
        for job_name, job in doc["jobs"].items():
            for index, step in enumerate(job.get("steps") or []):
                yield name, job_name, job, index, step


def _command(step: dict) -> str:
    return "\n".join(line.split("#", 1)[0] for line in str(step.get("run", "")).splitlines())


PUSH = "git" + " push"          # spelled apart: a literal here reads as a command to some tools
# Every statebox call in a workflow: the runner's own interpreter, isolated, no
# site-packages — the open and prune steps hold the job's token (INFRA-07).
STATEBOX = "python -I -S run/statebox.py"


def test_every_action_is_pinned_to_a_commit_with_its_tag_beside_it() -> None:
    """Reproduced (INFRA-06): every `uses:` named a movable tag (@v4, @v5), so
    whoever controls a tag decides what runs beside STRIPE_API_KEY and
    RESEND_API_KEY. Pinned to the full commit those tags pointed at on
    Oct 23 2026 — no behaviour changed — with the tag in a comment so
    Dependabot can still propose updates."""
    count = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*(\S+)(.*)$", line)
            if not match:
                continue
            count += 1
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", match.group(1)), \
                f"{path.name}: {match.group(1)} is not pinned to a commit"
            assert re.search(r"#\s*v\d+\.\d+\.\d+\s*$", match.group(2)), \
                f"{path.name}: {match.group(1)} has no version comment"
    assert count >= 30


def test_every_workflow_grants_nothing_by_default_and_each_job_only_what_it_uses() -> None:
    """INFRA-14: four workflows granted contents/issues write at the top
    level, so a job added later inherited them. Now `permissions: {}` at the
    top and each job asks for what its steps do: contents: write only where
    something pushes, issues: write only where an issue is filed, actions
    only where a backup is read (read) or a cache/backup is deleted (write)."""
    for name, doc in _docs().items():
        assert doc.get("permissions") == {}, f"{name}: top-level permissions are not empty"
        for job_name, job in doc["jobs"].items():
            perms = job.get("permissions")
            assert isinstance(perms, dict) and perms, f"{name}/{job_name} declares nothing"
            assert "write-all" not in str(perms) and "read-all" not in str(perms)
            commands = "\n".join(_command(s) for s in job.get("steps") or [])
            pushes = PUSH in commands
            files_issues = "gh issue" in commands
            deletes = "gh cache delete" in commands or "statebox.py prune" in commands
            reads_backup = "--backup" in commands
            assert (perms.get("contents") == "write") == pushes, (name, perms)
            assert (perms.get("issues") == "write") == files_issues, (name, perms)
            if deletes:
                assert perms.get("actions") == "write", (name, perms)
            elif reads_backup:
                assert perms.get("actions") == "read", (name, perms)
            else:
                assert "actions" not in perms, (name, perms)


def test_no_expression_is_pasted_into_a_shell() -> None:
    """INFRA-14: `${{ github.ref_name }}`, `${{ vars.PUSH_LEDGER }}` and the
    run URL were interpolated into `run:` scripts, where a crafted branch
    name or variable becomes shell. Every value now reaches a script through
    `env:` and is quoted there."""
    for name, _job, _j, _i, step in _all_steps():
        assert "${{" not in str(step.get("run", "")), \
            f"{name}: {step.get('name')!r} pastes an expression into its shell"


def test_checkout_never_leaves_the_push_token_behind() -> None:
    """INFRA-07: actions/checkout left the contents:write token in .git/config
    for every step, so any installed package could push to main (and so to
    the live site). Every checkout now says persist-credentials: false, and
    the one step that pushes gets the job's token in its own env and reads it
    through a credential helper — the helper text, never the token, is what
    lands in .git/config."""
    checkouts = pushers = 0
    helper = ("credential.helper '!f() { echo username=x-access-token; "
              "echo \"password=${GH_TOKEN}\"; }; f'")
    for name, _job, _j, _i, step in _all_steps():
        if "actions/checkout" in str(step.get("uses", "")):
            checkouts += 1
            assert (step.get("with") or {}).get("persist-credentials") is False, name
        if PUSH in _command(step):
            pushers += 1
            assert (step.get("env") or {}).get("GH_TOKEN") == "${{ github.token }}", name
            run = str(step["run"])
            assert helper in run, name
            assert run.index("credential.helper") < run.index("pull --rebase"), name
    # weekly.yml checks out four times (week, commit-record, share-card,
    # commit-card) and pushes twice, both from its commit jobs (SEC-1).
    assert checkouts == len(_docs()) + 3 and pushers == 7


GIT_WRAPPER = ('git() { command git -c core.hooksPath=/dev/null -c core.fsmonitor=false '
               '"$@"; }')


def test_no_hook_an_earlier_step_left_runs_beside_the_push_token(tmp_path) -> None:
    """SEC-1, reproduced locally as two steps: step A (no token, the share-card
    job's pip packages and Chrome, or any venv step) writes .git/hooks/
    pre-commit and a core.fsmonitor command; step B, the persist step's exact
    script, runs `git add` and `git commit` with GH_TOKEN in its environment
    — and the hook ran, reading the token ("GH_TOKEN visible: yes"). INFRA-07's
    "no third-party code beside a token" held per step, not per job. Every
    pushing step now first wraps git so config given on the command line
    (outranking .git/config and every other config file) runs no hook and no
    fsmonitor, for every git call it makes — and the script, run against a
    planted hook and fsmonitor, leaks nothing. (The wrapper closes hooks and
    fsmonitor only: an earlier step can still reach a later one through
    $GITHUB_ENV, $GITHUB_PATH or other config keys. weekly.yml has the full
    fix — its pushes come from commit jobs that install and run nothing,
    pinned below; the other five pushers have the wrapper alone.)"""
    import subprocess
    pushers = []
    for name, job_name, _j, _i, step in _all_steps():
        if PUSH not in _command(step):
            continue
        lines = [line.strip() for line in _command(step).splitlines() if line.strip()]
        assert lines[0] == GIT_WRAPPER, (name, job_name, step.get("name"))
        pushers.append((name, step))
    assert len(pushers) == 7
    if shutil.which("git") is None or shutil.which("bash") is None:
        pytest.skip("git or bash is not installed")
    # Step B, as weekly.yml's commit-card job runs it, up to the network calls.
    [(_n, card)] = [(n, s) for n, s in pushers if "site/og" in _command(s)]
    script = "\n".join(line for line in str(card["run"]).splitlines()
                       if not re.search(r"git (?:pull|push)\b", line))
    work = tmp_path / "work"
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(tmp_path)}
    subprocess.run(["git", "init", "-q", str(work)], check=True, env=env)
    (work / "site").mkdir()
    (work / "site" / "this-week.html").write_text("page", encoding="utf-8")
    leak = tmp_path / "leak.txt"
    hook = work / ".git" / "hooks" / "pre-commit"
    hook.write_text(f'#!/bin/sh\necho "hook: $GH_TOKEN" >> "{leak}"\n', encoding="utf-8")
    hook.chmod(0o755)
    subprocess.run(["git", "-C", str(work), "config", "core.fsmonitor",
                    f'sh -c \'echo "fsmonitor: $GH_TOKEN" >> "{leak}"\''], check=True, env=env)
    (work / "site" / "og").mkdir()
    (work / "site" / "og" / "card.png").write_bytes(b"png")
    done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                          cwd=work, capture_output=True, text=True,
                          env={**env, "GH_TOKEN": "ghs_dummy_token_123", "GITHUB_REF_NAME": "main"})
    assert done.returncode == 0, done.stderr
    log = subprocess.run(["git", "-C", str(work), "log", "--oneline"], capture_output=True,
                         text=True, env=env).stdout
    assert "share card" in log, "the script did not commit, so it proved nothing"
    assert not leak.exists() or "ghs_dummy" not in leak.read_text(), leak.read_text()


# --------------------------------------------------------------------- #
# SEC-1, the full fix: weekly.yml pushes only from jobs that run nothing
# --------------------------------------------------------------------- #

# commit job -> (the job whose files it pushes, its artifact, the folder under
# $RUNNER_TEMP both sides use).
COMMIT_JOBS = {"commit-record": ("week", "weekly-record", "record"),
               "commit-card": ("share-card", "share-card", "card")}
# Nothing a commit job runs may be installed or interpreted: git and the
# shell's own tools only.
_RUNS_SOMETHING = re.compile(r"\b(?:python\d*|pip\d*|node|npm|npx|make|curl|wget|gh|source|"
                             r"bash|sh|eval|exec|perl|ruby)\b|\.venv|\./")


def _shell(step: dict) -> str:
    """A step's script without its comment lines (a `#` inside a line, as in
    `${#files[@]}`, is shell, not a comment)."""
    return "\n".join(line for line in str(step.get("run", "")).splitlines()
                     if not line.strip().startswith("#"))


def _weekly_step(job: str, name: str) -> dict:
    return next(s for s in _docs()["weekly.yml"]["jobs"][job]["steps"] if s.get("name") == name)


def test_weekly_pushes_only_from_jobs_that_install_and_run_nothing() -> None:
    """SEC-1 (Oct 25 2026): the share-card job ran pip-installed packages and
    Chrome on a page built from third-party data, then handed GH_TOKEN —
    contents: write on main, the branch that serves the payment pages — to a
    step of the SAME job, and the week job's persist step had the same shape.
    The wrapper above closes hooks and fsmonitor; an earlier step could still
    reach the push through $GITHUB_ENV (BASH_ENV, LD_PRELOAD), $GITHUB_PATH (a
    fake git), or a filter driver, credential.helper, include.path or
    http.proxy in a git config file. Now the jobs that run anything installed
    hold contents: read and push nothing, and the only jobs with contents:
    write are the two commit jobs: a fresh checkout, a download of the other
    job's artifact, and git and the shell — no setup action, no package, no
    interpreter. The starting commit they lay the artifact on is the checkout
    action's own output, fixed before any step of the other job runs."""
    jobs = _docs()["weekly.yml"]["jobs"]
    writers = sorted(n for n, j in jobs.items() if j["permissions"].get("contents") == "write")
    assert writers == sorted(COMMIT_JOBS)
    for name, (builder, artifact, folder) in COMMIT_JOBS.items():
        job, source = jobs[name], jobs[builder]
        assert job["needs"] == builder and job["permissions"] == {"contents": "write"}
        uses = [str(s["uses"]).split("@")[0] for s in job["steps"] if "uses" in s]
        assert uses == ["actions/checkout", "actions/download-artifact"], (name, uses)
        checkout, download, check, persist = job["steps"]
        assert checkout["with"] == {"ref": "${{ github.ref_name }}", "fetch-depth": 0,
                                    "persist-credentials": False}
        assert download["with"] == {"name": artifact, "path": f"${{{{ runner.temp }}}}/{folder}"}
        assert check.get("env") == {"BASE": f"${{{{ needs.{builder}.outputs.base }}}}"}
        assert persist.get("env") == {"GH_TOKEN": "${{ github.token }}"}
        assert "if" not in check and "if" not in persist
        for step in (check, persist):
            found = _RUNS_SOMETHING.search(_shell(step))
            assert not found, (name, step.get("name"), found and found.group(0))
        # The other side: it pushes nothing, holds no push token, and hands
        # over the commit it started from as the checkout reported it.
        assert source["permissions"].get("contents") == "read"
        assert PUSH not in "\n".join(_command(s) for s in source["steps"]), builder
        assert source["outputs"] == {"base": "${{ steps.checkout.outputs.commit }}"}
        assert source["steps"][0].get("id") == "checkout"
        assert "actions/checkout" in source["steps"][0]["uses"]
        [upload] = [s for s in source["steps"]
                    if "upload-artifact" in str(s.get("uses", "")) and s["with"]["name"] == artifact]
        assert upload["with"]["path"] == f"${{{{ runner.temp }}}}/{folder}/"
        assert upload["with"]["if-no-files-found"] == "error"
        assert upload["with"]["overwrite"] is True        # a re-run replaces, never fails
    # The record keeps the persist step's `if: always()`: a failed or
    # cancelled send still records who WAS mailed. The card keeps its
    # persist step's success-only gate.
    assert jobs["commit-record"]["if"] == "always()" and "if" not in jobs["commit-card"]
    assert _weekly_step("week", "Hand the record to its commit job")["if"] == "always()"
    assert _weekly_step("week", "Upload the record")["if"] == "always()"


def _pathspecs(hand_off: str) -> list[str]:
    spec = hand_off.split("--exclude-standard --", 1)[1].split("|", 1)[0]
    return spec.replace("\\", " ").split()


def _added(persist: str) -> set[str]:
    paths: set[str] = set()
    for line in persist.splitlines():
        match = re.search(r"git add (?:-A )?(.+?)(?: \|\| true)?$", line.strip())
        if match:
            paths |= set(match.group(1).split())
    return paths


def test_the_hand_off_the_check_and_the_commit_name_the_same_paths() -> None:
    """Three lists in two jobs that must agree: what the week job stages,
    what commit-record accepts, and what it adds. A path staged but refused
    fails the push (and loses the send log with it); a path accepted but not
    staged is never persisted. Each staged path is accepted by the check's
    own `case` (exactly, or as a folder), and is exactly what the persist step
    adds — the send log on its own guarded line, as before."""
    for builder, hand_off_name, commit, check_name, persist_name in (
            ("week", "Hand the record to its commit job", "commit-record",
             "Check the record and lay it on the week job's commit", "Persist the record"),
            ("share-card", "Hand the card to its commit job", "commit-card",
             "Check the card and lay it on the share-card job's commit", "Persist the card")):
        staged = _pathspecs(str(_weekly_step(builder, hand_off_name)["run"]))
        check = str(_weekly_step(commit, check_name)["run"])
        patterns = {p.strip() for arm in re.findall(r"^\s*(/[^)]*)\) bad= ;;$", check, re.M)
                    for p in arm.split("|")}
        assert patterns, commit
        for path in staged:
            assert f"/{path}" in patterns or f"/{path}/*" in patterns \
                or any(p.startswith(f"/{path}/") for p in patterns), (commit, path)
        assert _added(str(_weekly_step(commit, persist_name)["run"])) == set(staged), commit
    record = _pathspecs(str(_weekly_step("week", "Hand the record to its commit job")["run"]))
    assert {"data/processed/ledger", "data/processed/sent.jsonl"} <= set(record)


# The record's files on a fresh repo, as the branch holds them.
_RECORD = {"data/processed/ledger/typed-ppr-12-2026/calls.jsonl": '{"call_id": "a"}\n',
           "data/processed/sent.jsonl": '{"key": "2026-w07-seed"}\n',
           "site/this-week.html": "<p>week 7</p>\n", "site/week.json": '{"week": 7}\n',
           "site/_headers": "/*\n", "content/this-week.md": "drafts\n",
           "site/join/players.json": "[]\n", "site/join/byes.json": "{}\n",
           "site/byes/index.html": "<p>byes</p>\n",
           # Beside the record, and never the record's to change.
           "site/index.html": "<p>landing</p>\n", "site/join/index.html": "<p>join</p>\n",
           ".github/workflows/weekly.yml": "name: weekly-report\n",
           "site/og/this-week-2026-w07.png": "png 7"}


class _Repos:
    """A bare remote (the branch on GitHub) and the clones each job makes."""

    def __init__(self, root: Path) -> None:
        import subprocess
        self.root, self.run = root, subprocess.run
        self.env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                    "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1"}
        self.git("init", "-q", "--bare", "-b", "main", str(root / "remote.git"))
        seed = self.clone("seed")
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=seed)
        for name in (".gitignore", ".gitattributes"):
            shutil.copy(REPO / name, seed / name)
        self.write(seed, _RECORD)
        self.commit(seed, "seed")

    def git(self, *args: str, cwd: Path | None = None) -> str:
        done = self.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                        cwd=cwd, env=self.env, capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    def clone(self, name: str) -> Path:
        self.git("clone", "-q", str(self.root / "remote.git"), str(self.root / name))
        return self.root / name

    @staticmethod
    def write(repo: Path, files: dict[str, str]) -> None:
        for path, text in files.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text, encoding="utf-8")

    def commit(self, repo: Path, message: str) -> str:
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-q", "-m", message, cwd=repo)
        self.git("push", "-q", "origin", "main", cwd=repo)
        return self.git("rev-parse", "HEAD", cwd=repo)

    def script(self, step: dict, cwd: Path, **env: str):
        """A step's `run:` as the runner runs it (`bash -e`), no git identity
        but what the script sets itself."""
        return self.run(["bash", "--noprofile", "--norc", "-e", "-c", str(step["run"])],
                        cwd=cwd, capture_output=True, text=True,
                        env={**self.env, "GITHUB_REF_NAME": "main", **env})

    def shown(self, path: str, ref: str = "main") -> str | None:
        done = self.run(["git", "show", f"{ref}:{path}"], cwd=self.root / "remote.git",
                        env=self.env, capture_output=True, text=True)
        return done.stdout if done.returncode == 0 else None


needs_git_and_bash = pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None,
                                        reason="git or bash is not installed")


@needs_git_and_bash
def test_the_record_survives_a_push_between_the_send_and_its_commit(tmp_path) -> None:
    """The reason the record could move at all: sent.jsonl is the only thing
    that stops the next run mailing everyone again, and it is now pushed by
    another job, minutes later, from another checkout. Run end to end with
    the workflow's own scripts against a local remote: the week job sends
    (appends to the send log and the ledger, rebuilds the page) and also
    touches files outside the record and leaves a hook behind; the hourly
    intake pushes ITS send-log line in between; commit-record checks out the
    new tip, lays the record on the week job's starting commit and rebases.
    Both runs' send-log lines survive (merge=union, as when the week job
    pushed itself), the ledger's lock file and everything outside the record
    stay behind, and the hook never runs."""
    repos = _Repos(tmp_path)
    week = repos.clone("week")
    base = repos.git("rev-parse", "HEAD", cwd=week)
    with (week / "data/processed/sent.jsonl").open("a", encoding="utf-8") as log:
        log.write('{"key": "2026-w08-week"}\n')
    repos.write(week, {
        "data/processed/ledger/typed-ppr-12-2026/calls.jsonl": '{"call_id": "a"}\n{"call_id": "b"}\n',
        "data/processed/ledger/typed-ppr-12-sf-2026/calls.jsonl": '{"call_id": "c"}\n',
        "data/processed/ledger/typed-ppr-12-2026/calls.jsonl.lock": "",
        "site/this-week.html": "<p>week 8</p>\n",
        # What a hostile step in the week job might also write.
        "site/join/index.html": '<a href="https://pay.example.net">Pay</a>\n',
        ".github/workflows/weekly.yml": "name: something else\n",
        "site/join/evil.js": "steal()\n"})
    leak = tmp_path / "leak.txt"
    hook = week / ".git" / "hooks" / "pre-commit"
    hook.write_text(f'#!/bin/sh\necho "$GH_TOKEN" >> "{leak}"\n', encoding="utf-8")
    hook.chmod(0o755)
    runner = tmp_path / "runner-week"
    runner.mkdir()
    done = repos.script(_weekly_step("week", "Hand the record to its commit job"), week,
                        RUNNER_TEMP=str(runner))
    assert done.returncode == 0, done.stderr
    staged = sorted(p.relative_to(runner / "record").as_posix()
                    for p in (runner / "record").rglob("*") if p.is_file())
    assert "data/processed/sent.jsonl" in staged and "site/this-week.html" in staged
    assert not any(p.endswith(".lock") or p.startswith((".github", "site/join/index", "site/join/evil"))
                   or "/.git" in f"/{p}" for p in staged), staged

    daily = repos.clone("daily")                       # the hourly intake, in between
    with (daily / "data/processed/sent.jsonl").open("a", encoding="utf-8") as log:
        log.write('{"key": "welcome-2026-10-25-daily"}\n')
    tip = repos.commit(daily, "Daily run: send log")

    commit = repos.clone("commit")
    for name in ("Check the record and lay it on the week job's commit", "Persist the record"):
        done = repos.script(_weekly_step("commit-record", name), commit, RUNNER_TEMP=str(runner),
                            BASE=base, GH_TOKEN="ghs_dummy_token_123")
        assert done.returncode == 0, (name, done.stdout, done.stderr)
    sent = repos.shown("data/processed/sent.jsonl")
    for line in ("2026-w07-seed", "welcome-2026-10-25-daily", "2026-w08-week"):
        assert line in sent, sent
    assert repos.shown("data/processed/ledger/typed-ppr-12-2026/calls.jsonl").count("call_id") == 2
    assert repos.shown("data/processed/ledger/typed-ppr-12-sf-2026/calls.jsonl")
    assert repos.shown("site/this-week.html") == "<p>week 8</p>\n"
    for path in ("site/join/index.html", ".github/workflows/weekly.yml"):
        assert repos.shown(path) == _RECORD[path], path
    assert repos.shown("site/join/evil.js") is None
    assert repos.shown("data/processed/ledger/typed-ppr-12-2026/calls.jsonl.lock") is None
    changed = repos.git("diff", "--name-only", tip, "main", cwd=tmp_path / "remote.git").split()
    assert sorted(changed) == ["data/processed/ledger/typed-ppr-12-2026/calls.jsonl",
                               "data/processed/ledger/typed-ppr-12-sf-2026/calls.jsonl",
                               "data/processed/sent.jsonl", "site/this-week.html"]
    assert not leak.exists()


@needs_git_and_bash
def test_the_card_commit_replaces_the_card_folder_and_nothing_else(tmp_path) -> None:
    """The card's pair, end to end: the draw deleted last week's card and
    wrote this week's; commit-card makes the folder exactly that, beside the
    page, and nothing else share-card touched reaches the branch."""
    repos = _Repos(tmp_path)
    card = repos.clone("card")
    base = repos.git("rev-parse", "HEAD", cwd=card)
    (card / "site/og/this-week-2026-w07.png").unlink()
    repos.write(card, {"site/og/this-week-2026-w08.png": "png 8",
                       "site/this-week.html": '<meta property="og:image" content="w08">\n',
                       "site/index.html": "<p>defaced</p>\n"})
    runner = tmp_path / "runner-card"
    runner.mkdir()
    done = repos.script(_weekly_step("share-card", "Hand the card to its commit job"), card,
                        RUNNER_TEMP=str(runner))
    assert done.returncode == 0, done.stderr
    commit = repos.clone("commit")
    for name in ("Check the card and lay it on the share-card job's commit", "Persist the card"):
        done = repos.script(_weekly_step("commit-card", name), commit, RUNNER_TEMP=str(runner),
                            BASE=base, GH_TOKEN="ghs_dummy_token_123")
        assert done.returncode == 0, (name, done.stdout, done.stderr)
    assert repos.shown("site/og/this-week-2026-w08.png") == "png 8"
    assert repos.shown("site/og/this-week-2026-w07.png") is None
    assert repos.shown("site/this-week.html").startswith("<meta")
    assert repos.shown("site/index.html") == _RECORD["site/index.html"]


@needs_git_and_bash
@pytest.mark.parametrize("attack", ["workflow", "join-page", "attributes", "link", "card-name",
                                    "other-branch", "not-a-commit", "empty"])
def test_a_commit_job_refuses_an_artifact_that_reaches_past_its_paths(tmp_path, attack) -> None:
    """What the check refuses, each before anything is laid down: a file
    outside the record (a workflow, the join page with its payment links), a
    git attributes file inside it (a merge driver or eol rule the push would
    then obey), a link where a page should be, a card that is not this
    week's card name, a starting commit that is not on the branch (rebasing
    from another branch's commit pushes that branch's commits) or not a
    commit at all, and an empty artifact. Refused means exit non-zero, a
    message, and the checkout exactly as it was."""
    repos = _Repos(tmp_path)
    other = repos.clone("other")
    repos.git("checkout", "-q", "-b", "feature", cwd=other)
    repos.write(other, {".github/workflows/weekly.yml": "name: planted\n"})
    repos.git("commit", "-q", "-am", "planted", cwd=other)
    repos.git("push", "-q", "origin", "feature", cwd=other)
    planted = repos.git("rev-parse", "HEAD", cwd=other)
    commit = repos.clone("commit")
    tip = repos.git("rev-parse", "HEAD", cwd=commit)
    job, folder, name = "commit-record", "record", "Check the record and lay it on the week job's commit"
    files = {"data/processed/sent.jsonl": _RECORD["data/processed/sent.jsonl"] + '{"key": "x"}\n'}
    base = tip
    if attack == "workflow":
        files[".github/workflows/weekly.yml"] = "name: planted\n"
    elif attack == "join-page":
        files["site/join/index.html"] = '<a href="https://pay.example.net">Pay</a>\n'
    elif attack == "attributes":
        files["data/processed/ledger/.gitattributes"] = "*.jsonl merge=planted\n"
    elif attack == "card-name":
        job, folder, name = "commit-card", "card", \
            "Check the card and lay it on the share-card job's commit"
        files = {"site/this-week.html": "<p>page</p>\n", "site/og/payment.png": "png"}
    elif attack == "other-branch":
        base = planted
    elif attack == "not-a-commit":
        base = "main"
    elif attack == "empty":
        files = {}
    root = tmp_path / "runner" / folder
    root.mkdir(parents=True)
    repos.write(root, files)
    if attack == "link":
        (root / "site").mkdir()
        (root / "site" / "this-week.html").symlink_to("/etc/hosts")
    done = repos.script(_weekly_step(job, name), commit, RUNNER_TEMP=str(tmp_path / "runner"),
                        BASE=base)
    assert done.returncode != 0, (attack, done.stdout)
    assert "::error::" in done.stdout and "nothing was persisted" in done.stdout
    assert repos.git("rev-parse", "HEAD", cwd=commit) == tip
    assert repos.git("status", "--porcelain", cwd=commit) == ""
    # Without the attack, the same check lays the send log down: the refusal
    # is the attack's, not the check's.
    if job == "commit-record" and attack != "empty":
        clean = tmp_path / "clean" / "record"
        repos.write(clean, {"data/processed/sent.jsonl": files["data/processed/sent.jsonl"]})
        done = repos.script(_weekly_step(job, name), commit, RUNNER_TEMP=str(clean.parent),
                            BASE=tip)
        assert done.returncode == 0, done.stderr
        assert '"x"' in (commit / "data/processed/sent.jsonl").read_text(encoding="utf-8")


def test_subscriber_state_is_cached_and_uploaded_only_sealed() -> None:
    """INFRA-02: data/registry and data/plans were cached in plain text. Now
    no cache or artifact step names either directory; the only state paths
    are data/sealed/<name>.enc under `sealed-` keys, every backup of one is
    kept 90 days, and every sealed save is gated on a seal step that ran."""
    sealed_saves = 0
    for name, _job, job, index, step in _all_steps():
        uses = str(step.get("uses", ""))
        if "actions/cache" not in uses and "upload-artifact" not in uses:
            continue
        paths = str((step.get("with") or {}).get("path", ""))
        for line in paths.splitlines():
            line = line.split("#", 1)[0].strip()
            assert not re.match(r"!?data/(registry|plans)\b", line), \
                f"{name}: {step.get('name')!r} caches or uploads {line} in plain text"
        if "data/sealed/" not in paths:
            continue
        sealed = re.fullmatch(r"data/sealed/(registry|plans)\.enc", paths.strip())
        assert sealed, (name, paths)
        which = sealed.group(1)
        if "actions/cache" in uses:
            assert step["with"]["key"] == f"sealed-{which}-${{{{ github.run_id }}}}", name
            if "restore" in uses:
                assert step["with"]["restore-keys"] == f"sealed-{which}-", name
        if "cache/save" in uses or "upload-artifact" in uses:
            sealed_saves += 1
            assert f"steps.seal.outputs.{which}_sealed == 'true'" in str(step.get("if")), \
                f"{name}: {step.get('name')!r} saves without a successful seal"
            seal = next(s for s in job["steps"] if s.get("id") == "seal")
            assert job["steps"].index(seal) < index
            assert STATEBOX + " seal" in _command(seal) and which in _command(seal)
        if "upload-artifact" in uses:
            assert step["with"]["name"] == f"sealed-{which}"
            assert step["with"]["retention-days"] == 90
    assert sealed_saves >= 10


def test_every_restore_is_opened_with_the_key_and_every_seal_waits_for_it() -> None:
    """The other half: a workflow that restores a sealed file opens it (with
    the backup fallback and CACHE_KEY), and its seal step runs only when that
    open succeeded — a restore that failed its check must never be followed
    by a save that makes a fresh, partial registry the newest copy."""
    checked = 0
    for name, doc in _docs().items():
        steps = list(doc["jobs"].values())[0]["steps"]
        restores = [s for s in steps if "cache/restore" in str(s.get("uses", ""))
                    and "data/sealed/" in str(s["with"]["path"])]
        if not restores:
            continue
        checked += 1
        opens = [s for s in steps if STATEBOX + " open" in _command(s)]
        assert len(opens) == 1, name
        [opener] = opens
        assert "--backup" in _command(opener)
        assert opener["env"]["CACHE_KEY"] == "${{ secrets.CACHE_KEY }}"
        assert opener["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert opener["env"]["ALLOW_EMPTY_REGISTRY"] == "${{ vars.ALLOW_EMPTY_REGISTRY }}"
        assert opener.get("id") == "open", name
        for restore in restores:
            which = re.search(r"(registry|plans)", restore["with"]["path"]).group(1)
            assert which in _command(opener), (name, which)
            assert steps.index(restore) < steps.index(opener)
        for seal in (s for s in steps if STATEBOX + " seal" in _command(s)):
            assert seal["env"]["CACHE_KEY"] == "${{ secrets.CACHE_KEY }}"
            assert seal["env"]["STRIPE_KEY_SET"] == "${{ secrets.STRIPE_API_KEY != '' }}"
            if name != "privacy.yml":       # gated on its own action == 'delete'
                assert "steps.open.outcome == 'success'" in seal["if"], name
                assert opener.get("id") == "open", name
    assert checked == 5


def test_a_privacy_delete_reaches_every_copy() -> None:
    """RULE S4 in the workflow: fresh sealed copies are saved and backed up
    FIRST, then every older sealed cache, every pre-sealing plaintext cache,
    and every older backup artifact is deleted."""
    steps = list(_docs()["privacy.yml"]["jobs"].values())[0]["steps"]
    names = [s.get("name") for s in steps]
    delete = next(s for s in steps if "gh cache delete" in _command(s))
    command = _command(delete)
    for prefix in ("sealed-registry-", "sealed-plans-", "registry-", "plans-"):
        assert f'"{prefix}"' in command or f" {prefix}" in command, prefix
    assert STATEBOX + ' prune registry plans --keep-run "$GITHUB_RUN_ID"' in command
    # Re-listed until empty, never read once to a --limit (100 left a week of
    # hourly entries behind), and a failed delete stops the step red.
    assert "--limit 100 " not in command and "set -euo pipefail" in command
    assert re.search(r"while :; do", command)
    assert names.index("Back up the edited registry") < names.index(delete["name"])
    assert names.index("Back up the edited plans") < names.index(delete["name"])


def test_the_crons_install_only_the_hash_locked_runtime_set() -> None:
    """INFRA-07: every cron ran `pip install -r requirements.txt` — three pins,
    no hashes, transitive packages floating, and pytest/PyYAML installed
    beside the live secrets. Each install now names a lock file with
    --require-hashes; the crons get the runtime lock, only the test job the
    dev lock."""
    installs = 0
    for name, _job, _j, _i, step in _all_steps():
        command = _command(step)
        if "pip install" not in command:
            continue
        installs += 1
        assert "requirements.txt" not in command, name
        assert "--require-hashes" in command, name
        lock = "requirements-dev.lock" if name == "test.yml" else "requirements.lock"
        assert f"-r {lock}" in command, (name, command)
    # pages.yml installs nothing; weekly.yml's share-card job installs too.
    assert installs == len(_docs())


def test_the_crons_that_rebuild_a_page_commit_its_fresh_headers() -> None:
    """The Tuesday run rebuilds this-week.html and the Monday run the ledger
    page; each re-derives site/_headers and commits it with them, so a page
    whose script changed never meets a stale policy on Cloudflare Pages. The
    Tuesday run's commit is commit-record's (SEC-1), so the refresh comes
    before the week job hands the record over, and both files are in it."""
    commands = [_command(s) for s in _docs()["monday.yml"]["jobs"]["receipts"]["steps"]]
    refresh = next(i for i, c in enumerate(commands) if "-m render.headers" in c)
    persist = next(i for i, c in enumerate(commands) if PUSH in c)
    assert refresh <= persist
    assert re.search(r"git add[^\n]*site/_headers", commands[persist])
    jobs = _docs()["weekly.yml"]["jobs"]
    commands = [_command(s) for s in jobs["week"]["steps"]]
    refresh = next(i for i, c in enumerate(commands) if "-m render.headers" in c)
    hand_off = next(i for i, c in enumerate(commands) if "RUNNER_TEMP/record" in c)
    assert refresh < hand_off
    assert "site/this-week.html" in commands[hand_off] and "site/_headers" in commands[hand_off]
    persist = next(_command(s) for s in jobs["commit-record"]["steps"] if PUSH in _command(s))
    assert re.search(r"git add[^\n]*site/this-week\.html[^\n]*site/_headers", persist)


# --------------------------------------------------------------------- #
# the change notice needs the owner (INFRA-06)
# --------------------------------------------------------------------- #

def test_a_real_change_notice_needs_the_owners_code() -> None:
    """Reproduced (INFRA-06): GH_DISPATCH_TOKEN (Actions: write, held by the
    form Worker) could dispatch change-notice.yml with send=true and any
    summary, and every entitled subscriber was mailed that text from our
    domain. A real send now first verifies an HMAC under LOG_SECRET over the
    exact page, date and summary — a code the token cannot make."""
    steps = list(_docs()["notice.yml"]["jobs"].values())[0]["steps"]
    names = [s.get("name") for s in steps]
    check = next(s for s in steps if "run.approval verify" in _command(s))
    assert check["if"] == "github.event.inputs.send == 'true'"
    assert check["env"]["LOG_SECRET"] == "${{ secrets.LOG_SECRET }}"
    assert check["env"]["APPROVAL"] == "${{ github.event.inputs.approval }}"
    assert 'verify notice "$APPROVAL" "$PAGE" "$EFFECTIVE" "$SUMMARY"' in check["run"]
    send = next(s for s in steps if "run.notice" in _command(s))
    assert names.index(check["name"]) < names.index(send["name"])
    assert "if" not in send, "a failed approval must stop the send"


def test_the_approval_code_binds_the_exact_words(monkeypatch) -> None:
    """Whitespace is normalised (a paste gains a line break); any other change
    to the page, the date or the words is a different code."""
    import run.approval as approval
    monkeypatch.setenv("LOG_SECRET", "owner-secret")
    code = approval.code("notice", "terms", "2026-11-15", "Refunds now close at kickoff.")
    assert re.fullmatch(r"[0-9a-f]{20}", code)
    assert approval.verify("notice", code, "terms", "2026-11-15",
                           "  Refunds now close\nat kickoff. ")
    assert not approval.verify("notice", code, "terms", "2026-11-15",
                               "Refunds now close at kickoff. Click here.")
    assert not approval.verify("notice", code, "privacy", "2026-11-15",
                               "Refunds now close at kickoff.")
    assert approval.main(["verify", "notice", code, "terms", "2026-11-15",
                          "Something else"]) == 1
    assert approval.main(["verify", "notice", code, "terms", "2026-11-15",
                          "Refunds now close at kickoff."]) == 0
    monkeypatch.setenv("LOG_SECRET", "a-stolen-guess")
    assert not approval.verify("notice", code, "terms", "2026-11-15",
                               "Refunds now close at kickoff.")
    monkeypatch.delenv("LOG_SECRET")
    assert approval.main(["notice", "terms", "2026-11-15", "x"]) == 1


# --------------------------------------------------------------------- #
# hash-locked dependencies (INFRA-07)
# --------------------------------------------------------------------- #

def _lock_problems(source: str, runtime_lock: str, dev_lock: str) -> list[str]:
    from infra.lock_requirements import parse_lock, parse_source
    runtime, dev = parse_source(source)
    run_entries, dev_entries = parse_lock(runtime_lock), parse_lock(dev_lock)
    problems = []
    for pins, entries, label in ((runtime, run_entries, "requirements.lock"),
                                 ({**runtime, **dev}, dev_entries, "requirements-dev.lock")):
        for package, version in pins.items():
            if entries.get(package, (None,))[0] != version:
                problems.append(f"{label}: {package} is not {version}")
        for package, (_version, digests) in entries.items():
            if not digests or not all(re.fullmatch(r"[0-9a-f]{64}", d) for d in digests):
                problems.append(f"{label}: {package} has no sha256")
    for package in dev:
        if package in run_entries:
            problems.append(f"requirements.lock carries the dev tool {package}")
    for package, entry in run_entries.items():
        if dev_entries.get(package) != entry:
            problems.append(f"requirements-dev.lock disagrees with the runtime lock on {package}")
    return problems


def test_the_locks_match_requirements_txt() -> None:
    """The locks are generated (`make lock`); a pin bumped in requirements.txt
    — by hand or by Dependabot — without regenerating them fails here, rather
    than installing something nobody hashed. The three mutations below are
    the failures this exists to catch."""
    source = (REPO / "requirements.txt").read_text(encoding="utf-8")
    runtime_lock = (REPO / "requirements.lock").read_text(encoding="utf-8")
    dev_lock = (REPO / "requirements-dev.lock").read_text(encoding="utf-8")
    assert _lock_problems(source, runtime_lock, dev_lock) == []
    from infra.lock_requirements import parse_lock
    names = set(parse_lock(runtime_lock))
    assert {"requests", "urllib3", "idna", "certifi", "charset-normalizer"} <= names
    assert not names & {"pytest", "pyyaml", "pluggy", "pygments"}
    assert runtime_lock.startswith("# GENERATED by `make lock`")
    bumped = source.replace("requests==2.34.2", "requests==2.35.0")
    assert _lock_problems(bumped, runtime_lock, dev_lock)
    unhashed = re.sub(r"--hash=sha256:[0-9a-f]{64}", "--hash=sha256:", runtime_lock)
    assert _lock_problems(source, unhashed, dev_lock)
    leaky = runtime_lock + "pytest==9.1.1 \\\n    --hash=sha256:" + "a" * 64 + "\n"
    assert _lock_problems(source, leaky, dev_lock)


# --------------------------------------------------------------------- #
# provider errors in public logs (SEC-11 / INFRA-15)
# --------------------------------------------------------------------- #

def test_a_provider_error_never_carries_an_address_into_the_log(monkeypatch) -> None:
    """Reproduced shape (INFRA-14 in the review): run/delivery.py raised
    `HTTP {code} from provider: {first 300 chars of the body}` and every runner
    printed it into a public Actions log. Postmark's 406 names the inactive
    recipient; Resend's testing-mode refusal names the account login. The
    status and the reason survive; the addresses and anything key-shaped do
    not. Mutation-checked: dropping the redaction from DeliveryError fails."""
    import urllib.error
    import run.delivery as delivery
    body = (b'{"ErrorCode":406,"Message":"You tried to send to recipient(s) that have been '
            b'marked as inactive. Found inactive addresses: fan.one+ff@gmail.com, '
            b'Pal <pal@example.co.uk>. Key re_AbCdEf123456789 was used."}')

    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 406, "Not Acceptable", {},
                                     io.BytesIO(body))

    monkeypatch.setattr(delivery.urllib.request, "urlopen", refuse)
    with pytest.raises(delivery.DeliveryError) as caught:
        delivery._post_json("https://api.postmarkapp.com/email", {}, {})
    text = str(caught.value)
    assert "HTTP 406" in text and "inactive" in text
    for leaked in ("fan.one", "gmail.com", "pal@", "example.co.uk", "re_AbCdEf"):
        assert leaked not in text, text
    assert "<address>" in text and "<key>" in text


def test_every_failed_send_result_is_redacted_whatever_raised_it() -> None:
    """The other paths into a log: an SMTP refusal quoting the recipient, and
    `unexpected: {exc!r}` from any exception. A successful result's detail is
    the provider's message id and is left alone (the send log records it)."""
    from run.delivery import Message, SendResult
    from run.redact import redact
    message = Message(to="fan@example.com", subject="s", html="h", text="t", key="k")
    failed = SendResult(message, ok=False,
                        detail="SMTP send failed: {'fan@example.com': (550, b'no such user')}")
    assert "fan@example.com" not in failed.detail and "550" in failed.detail
    unexpected = SendResult(message, ok=False,
                            detail=f"unexpected: {ValueError('Bearer sk_live_51abcdefghij for x@y.io')!r}")
    assert "sk_live" not in unexpected.detail and "x@y.io" not in unexpected.detail
    sent = SendResult(message, ok=True, detail="4f1c2b9e-0000-4c1a-9f00-1234567890ab")
    assert sent.detail == "4f1c2b9e-0000-4c1a-9f00-1234567890ab"
    assert redact("HTTP 429 from provider: rate limited") == "HTTP 429 from provider: rate limited"


# --------------------------------------------------------------------- #
# security headers (SEC-10 / INFRA-04/10/12)
# --------------------------------------------------------------------- #

def _rules(text: str) -> dict[str, dict[str, str]]:
    rules: dict[str, dict[str, str]] = {}
    current = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith(" "):
            assert line not in rules, f"{line} has two rules: Cloudflare would join them"
            current = line
            rules[current] = {}
        else:
            name, value = line.strip().split(":", 1)
            assert name not in rules[current], (current, name)
            rules[current][name] = value.strip()
    return rules


def test_the_security_headers_are_current() -> None:
    """site/_headers is generated from the pages (`make headers`). A page
    whose inline script changes without regenerating it would have that
    script BLOCKED once Cloudflare Pages serves the site — checkout, the
    roster check, the confirm button — so the suite fails first."""
    from render.headers import OUT, build
    assert OUT.read_text(encoding="utf-8") == build(), \
        "site/_headers is stale: run `make headers` and commit it"


def test_every_page_carries_its_own_policy_and_none_rides_the_splat() -> None:
    """Reproduced (INFRA-10): no HSTS, CSP, anti-framing, nosniff or
    Referrer-Policy on any response, and /join/ rendered inside a foreign
    page. The common headers ride `/*`; each page's CSP rides its own path,
    because Cloudflare joins two matching values with a comma and two CSPs
    are enforced together — a script-src on `/*` would stop every script.
    `/*` carries only the FLOOR (reviewer, Oct 24: the 404 Cloudflare serves
    at an unknown path matches only `/*`, so it carried no policy at all):
    directives that restrict no fetch, each word for word in every page's
    own policy, so the intersection on any page is that page's policy.
    Checked in headless Chrome with the two joined: /join/'s inline script
    ran (players.json fetched); with a planted wrong hash it did not."""
    from render.headers import MAX_LINE, MAX_RULES, OUT, SITE, paths_for
    text = OUT.read_text(encoding="utf-8")
    rules = _rules(text)
    common = rules["/*"]
    assert common["Strict-Transport-Security"].startswith("max-age=31536000")
    assert common["X-Content-Type-Options"] == "nosniff"
    assert common["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert common["X-Frame-Options"] == "DENY"
    assert "camera=()" in common["Permissions-Policy"]
    from render.headers import FLOOR
    floor = [d.strip() for d in common["Content-Security-Policy"].split(";")]
    assert floor == list(FLOOR)
    fetch = ("default-src", "script-src", "style-src", "img-src", "font-src",
             "connect-src", "manifest-src", "media-src", "frame-src", "worker-src")
    assert not any(d.split(" ", 1)[0] in fetch for d in floor), floor
    assert len(rules) <= MAX_RULES
    assert max(len(line) for line in text.splitlines()) <= MAX_LINE
    pages = sorted(SITE.rglob("*.html"))
    assert len(pages) >= 15
    for page in pages:
        for path in paths_for(page):
            policy = rules[path]["Content-Security-Policy"]
            directives = dict((d.strip().split(" ", 1) + [""])[:2] for d in policy.split(";"))
            assert directives["frame-ancestors"] == "'none'"
            assert directives["object-src"] == "'none'" and directives["base-uri"] == "'none'"
            assert directives["connect-src"] == "'self' https://forms.beatyourleague.com"
            assert "'unsafe-inline'" not in directives["script-src"]
            parts = [d.strip() for d in policy.split(";")]
            assert all(d in parts for d in floor), (path, "the floor would narrow it")
            assert "'unsafe-eval'" not in policy and "*" not in policy
    assert rules["/join/"] == rules["/join/index.html"]
    assert rules["/terms"] == rules["/terms.html"]


def test_each_policy_allows_exactly_that_pages_inline_scripts() -> None:
    """Hashed independently of the generator: sha256 of each executable inline
    script's exact text, base64 — the form Chrome itself prints when it
    blocks one (checked live: a broken hash on /join/ was refused with the
    hash this computes, and every page loaded clean under the real file).
    JSON-LD never executes and needs none."""
    import base64
    import hashlib
    from render.headers import OUT, SITE, paths_for
    rules = _rules(OUT.read_text(encoding="utf-8"))
    for page in sorted(SITE.rglob("*.html")):
        html = page.read_text(encoding="utf-8")
        expected = set()
        for match in re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S):
            attrs = match.group(1)
            if "src=" in attrs or "application/ld+json" in attrs:
                continue
            digest = base64.b64encode(hashlib.sha256(match.group(2).encode()).digest()).decode()
            expected.add(f"'sha256-{digest}'")
        policy = rules[paths_for(page)[0]]["Content-Security-Policy"]
        script_src = next(d for d in policy.split(";") if d.strip().startswith("script-src"))
        allowed = set(re.findall(r"'sha256-[^']+'", script_src))
        assert allowed == expected, page.name


def test_a_changed_script_makes_the_headers_stale(tmp_path, monkeypatch) -> None:
    """Mutation: one character changed in the join page's script, and the
    check fails — the drift the suite exists to catch before Cloudflare
    blocks the script."""
    import render.headers as headers
    copy = tmp_path / "site"
    shutil.copytree(headers.SITE, copy)
    monkeypatch.setattr(headers, "SITE", copy)
    monkeypatch.setattr(headers, "OUT", copy / "_headers")
    assert headers.main(["--check"]) == 0
    join = copy / "join" / "index.html"
    html = join.read_text(encoding="utf-8")
    assert "<script>\n" in html
    join.write_text(html.replace("<script>\n", "<script>\n// one edit\n", 1), encoding="utf-8")
    assert headers.main(["--check"]) == 1
    assert headers.main([]) == 0 and headers.main(["--check"]) == 0


def test_no_page_uses_an_inline_handler_or_a_javascript_url() -> None:
    """The policy hashes <script> elements only: an onclick="..." attribute or
    a javascript: link would be blocked on Cloudflare Pages (it would need
    'unsafe-hashes'). None exists; this keeps it that way."""
    from render.headers import SITE
    for page in sorted(SITE.rglob("*.html")):
        html = page.read_text(encoding="utf-8")
        tags = re.findall(r"<[a-zA-Z][^>]*>", re.sub(r"<script.*?</script>", "", html, flags=re.S))
        for tag in tags:
            assert not re.search(r"\son[a-z]+\s*=", tag), (page.name, tag[:80])
        assert "javascript:" not in html.lower().replace("text/javascript", ""), page.name


# --------------------------------------------------------------------- #
# the money model (BIZ-03)
# --------------------------------------------------------------------- #

def test_the_2026_base_case_is_priced_as_2026_sells(monkeypatch) -> None:
    """Reproduced (BIZ-03): base_case_net() priced 30 purchases at the retired
    $39 subscription and 2 at $99 (Billing fee included) — "$1,113.76 after
    fixed costs, about $17.40 an hour" — while 2026 sells $29 / $19 / $69
    one-time passes. Now the base case is those passes, split 20 / 10 by the
    stated playoff rule, and moving the 2027 prices moves nothing in it."""
    import run.economics as econ
    assert econ.base_case_mix() == {"Rest-of-Season Pass": 20, "Playoff Pass": 10,
                                    "League Pass (rest of season)": 2}
    expected = (20 * econ.net_per_sale(29, one_time=True) + 10 * econ.net_per_sale(19, one_time=True)
                + 2 * econ.net_per_sale(69, one_time=True) - sum(econ.FIXED_SEASON_COSTS.values()))
    assert econ.base_case_net() == round(expected, 2)
    assert 700 < econ.base_case_net() < 760
    before = econ.base_case_net()
    monkeypatch.setattr(econ, "SEASON", 1000.0)
    monkeypatch.setattr(econ, "LEAGUE_PASS", 1000.0)
    assert econ.base_case_net() == before
    assert econ.league_pass_per_manager() == "$5.75"


def test_the_weeks_left_and_the_hours_come_from_the_opening_date() -> None:
    """WEEKS_LEFT was a constant 12, "opening Oct 20" — a date that passed
    with checkout closed. It is derived from OPENS now: a Monday Oct 26
    opening sells Week 8 on (11 weekly reports, about 59 owner-hours); an
    opening on the Thursday of a kickoff sells the next week; an opening in
    Week 13 sells only Playoff Passes."""
    from datetime import date
    import run.economics as econ
    assert econ.OPENS == date(2026, 10, 26)
    assert econ.first_week_sold(date(2026, 10, 26)) == 8
    assert econ.first_week_sold(date(2026, 10, 28)) == 8
    assert econ.first_week_sold(date(2026, 10, 29)) == 9
    assert econ.WEEKS_LEFT == econ.weeks_left() == 11
    assert econ.owner_hours() == 58.9
    assert econ.owner_hours(date(2026, 11, 9)) < econ.owner_hours()
    assert econ.playoff_share(date(2026, 12, 1)) == 1.0
    assert econ.report_tuesday(18) == date(2027, 1, 5)


def test_a_2026_buyer_is_a_re_buy_never_a_renewal() -> None:
    """A one-time pass renews nothing: the two-season view for a 2026 buyer is
    their pass plus a stated chance of BUYING again at $39 — about $34.43 at
    30%, not the $42.81 a $39 renewal implied."""
    import run.economics as econ
    assert econ.rebuy_value(29, 39, 0.3) == round(
        econ.net_per_sale(29, one_time=True) + 0.3 * econ.net_per_sale(39), 2)
    lines = "\n".join(econ.customer_lines(calendar=None))
    assert "re-buy" in lines and "renew:" not in lines


def test_the_dispute_fee_is_counted(monkeypatch) -> None:
    """Stripe Canada charges C$15 a dispute; the model ignored it."""
    import run.economics as econ
    with_fee = econ.net_per_sale(29, one_time=True)
    monkeypatch.setattr(econ, "DISPUTE_FEE_USD", 0.0)
    assert econ.net_per_sale(29, one_time=True) > with_fee


def test_the_readiness_gate_fails_on_the_old_subscription_base_case(tmp_path) -> None:
    """Mutation: the launch-readiness money table as it stood (about $1,114,
    64 hours, $17 an hour) fails the gate — it used to PASS, because the gate
    pinned the document to the stale model."""
    import run.economics as econ
    stale = tmp_path / "launch-readiness.md"
    stale.write_text("about $1,114 after fixed costs; about 64 hours, so about $17 an hour",
                     encoding="utf-8")
    assert len(econ.readiness_base_case_mismatches(stale)) == 3
    assert econ.readiness_base_case_mismatches() == []


def test_a_one_time_fee_figure_counts_only_beside_its_own_price() -> None:
    """The one-time fees are small and close together; let into the general
    pool they excused a stale "$1-1.50 a cycle". A sentence may quote $4.15
    when it names the $69 pass, and not otherwise."""
    import run.economics as econ
    assert econ.doc_fee_mismatches(
        "A refund doesn't return Stripe's fee: about $4.15 on the $69 League Pass.", "x") == []
    assert econ.doc_fee_mismatches(
        "A refund doesn't return Stripe's fee: about $1.87 on a $29 pass, or about $1.29 "
        "with a USD payout account.", "x") == []
    assert econ.doc_fee_mismatches("A refund keeps Stripe's fee of about $4.15.", "x")


# --------------------------------------------------------------------- #
# the review of this branch (Oct 24 2026), pinned
# --------------------------------------------------------------------- #

from test_intake_sync import REF, _session, directory, stripe  # noqa: E402,F401 (fixtures)

import run.intake as intake  # noqa: E402

# Every runner that reads data/registry (or data/plans) as the truth.
REGISTRY_READERS = ("run.intake", "run.tuesday", "run.saturday", "run.notice",
                    "run.privacy", "run.trials")


def test_a_failed_open_stops_every_step_that_reads_the_registry() -> None:
    """Reproduced (review): weekly.yml's 'Turn payments into subscribers' and
    'Send subscriber reports' carried a bare `if: always()`, so both ran after
    `statebox open` refused — a rotated CACHE_KEY, a file failing its tag,
    GitHub down mid-restore. data/registry was then EMPTY: run.intake --no-mail
    swept Stripe from scratch into a registry with no seat-log.jsonl and no
    roster-updates.jsonl, and run.tuesday mailed every payer a report on their
    SIGNUP roster, logged in the committed send log so the right one never
    went. A step that reads the registry now runs only after a successful
    open: no `if:` (success() is implied), an `if:` with no always()/
    failure()/cancelled(), or one that names the open's outcome."""
    checked = 0
    for name, doc in _docs().items():
        steps = list(doc["jobs"].values())[0]["steps"]
        opener = next((s for s in steps if STATEBOX + " open" in _command(s)), None)
        for index, step in enumerate(steps):
            command = _command(step)
            if not any(re.search(rf"-m {re.escape(r)}(?![\w.])", command)
                       for r in REGISTRY_READERS):
                continue
            checked += 1
            assert opener is not None and steps.index(opener) < index, (name, step.get("name"))
            cond = str(step.get("if", ""))
            if re.search(r"always\(\)|failure\(\)|cancelled\(\)", cond):
                assert "steps.open.outcome == 'success'" in cond, \
                    f"{name}: {step.get('name')!r} runs after a failed open"
    assert checked == 7     # daily x2, weekly x2, saturday, notice, privacy


def test_no_step_holding_the_job_token_runs_a_third_party_package() -> None:
    """Reproduced (review, INFRA-07): every 'Open the registry' step handed
    GH_TOKEN — the job's token, contents: write in five of the six — to a venv
    Python that imports requests and its dependencies, the third-party code
    whose .pth startup hook was the INFRA-07 concern; privacy.yml's prune
    held Actions: write the same way, and monday.yml's persist step ran
    render.headers beside its push token. A step that holds a token now runs
    git, gh, or `python -I -S run/statebox.py` (no site-packages at all)."""
    holders = 0
    for name, _job, _j, _i, step in _all_steps():
        env = step.get("env") or {}
        if not any("github.token" in str(v) or "GITHUB_TOKEN" in str(v) for v in env.values()):
            continue
        holders += 1
        command = _command(step)
        assert ".venv/" not in command, (name, step.get("name"))
        for line in command.splitlines():
            if "python" in line:
                assert line.strip().startswith(STATEBOX), (name, step.get("name"), line)
    assert holders >= 15
    monday = list(_docs()["monday.yml"]["jobs"].values())[0]["steps"]
    refresh = next(s for s in monday if "-m render.headers" in _command(s))
    assert refresh.get("if") == "always() && vars.PUSH_LEDGER != 'false'"
    assert not refresh.get("env")


def test_statebox_runs_on_the_standard_library_alone(tmp_path) -> None:
    """The isolation above only holds if statebox needs nothing outside the
    standard library: every import it makes is a stdlib module, and a seal
    and an open really work under `-I -S` (no site-packages, no PYTHON*
    variables, no current directory on the path)."""
    import ast
    import subprocess
    import sys
    tree = ast.parse((REPO / "run" / "statebox.py").read_text(encoding="utf-8"))
    modules = {alias.name.split(".")[0] for node in ast.walk(tree)
               if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    assert modules <= set(sys.stdlib_module_names) | {"__future__"}, modules
    if shutil.which("openssl") is None:
        pytest.skip("openssl is not installed")
    _registry(tmp_path)
    before = _tree(tmp_path / "data" / "registry")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "CACHE_KEY": KEY}
    script = str(REPO / "run" / "statebox.py")
    for args in (["seal", "registry"], None, ["open", "registry"]):
        if args is None:
            shutil.rmtree(tmp_path / "data" / "registry")
            continue
        done = subprocess.run([sys.executable, "-I", "-S", script, *args, "--root", str(tmp_path)],
                              capture_output=True, text=True, env=env, cwd=tmp_path)
        assert done.returncode == 0, done.stderr
    assert _tree(tmp_path / "data" / "registry") == before


def test_the_token_never_follows_a_redirect_to_another_host(monkeypatch) -> None:
    """The artifact download answers 302 to blob storage. urllib's own
    redirect handler copies every header onto the next request, the job's
    Authorization included, so redirects come back to statebox, which drops
    the token when the host changes and keeps it when it does not."""
    calls: list[tuple[str, dict]] = []

    def send(self, method, url, headers, timeout):
        calls.append((url, dict(headers)))
        if url.startswith("https://api.github.com/"):
            return sb._Reply(302, b"", {"Location": "https://blob.example.net/a.zip?sig=x"})
        return sb._Reply(200, b"zip bytes", {})

    monkeypatch.setattr(sb._Http, "_send", send)
    gh = sb.GitHub("o/r", "tok")
    artifact = {"size_in_bytes": 9,
                "archive_download_url": "https://api.github.com/repos/o/r/actions/artifacts/1/zip"}
    assert gh.download(artifact) == b"zip bytes"
    assert calls[0][1]["Authorization"] == "Bearer tok"
    assert calls[1][0].startswith("https://blob.example.net/")
    assert "Authorization" not in calls[1][1]
    assert sb._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://x/") is None


@needs_openssl
def test_a_run_with_no_new_payment_leaves_no_new_backup(tmp_path, monkeypatch, stripe,
                                                       directory, capsys) -> None:
    """Reproduced (review): run.intake writes `last_run` into
    roster-sync-state.json on EVERY run, so content_digest differed every
    time, `registry_changed` was always true, and every hourly run uploaded a
    90-day backup — 24-48 a day, thousands retained, each a copy of every
    subscriber a privacy delete then had to reach. The stamp is left out of
    the change check (not out of the sealed copy): a real intake with no new
    payment between open and seal is `changed: False`; a new payment is
    `changed: True`."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    reg = tmp_path / "data" / "registry"
    stripe["sessions"] = [_session(REF)]
    assert intake.main(["--registry-dir", str(reg)]) == 0, capsys.readouterr().err
    state_path = reg / intake.STATE_NAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_run"] = "2026-11-02T14:47:00+00:00"          # the run an hour ago
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    sb.seal("registry", tmp_path, iterations=FAST)
    shutil.rmtree(reg)
    sb.open_sealed("registry", tmp_path)
    assert intake.main(["--registry-dir", str(reg)]) == 0, capsys.readouterr().err
    assert json.loads(state_path.read_text(encoding="utf-8"))["last_run"] != state["last_run"]
    assert sb.seal("registry", tmp_path, iterations=FAST)["changed"] is False
    stripe["sessions"].append(_session(REF, sid="cs_2", email="pal@example.com",
                                       customer="cus_efgh5678", created=2000))
    assert intake.main(["--registry-dir", str(reg)]) == 0, capsys.readouterr().err
    assert sb.seal("registry", tmp_path, iterations=FAST)["changed"] is True


class _PagedGitHub(_FakeGitHub):
    """The artifacts list as the REST API serves it: newest first, at most 100
    a page, `page` honoured, `total_count` beside it."""

    def __init__(self, *args, rate_limit_after: int | None = None, **kw) -> None:
        super().__init__(*args, **kw)
        self.pages: list[int] = []
        self.rate_limit_after = rate_limit_after

    def get(self, url, headers=None, timeout=None, params=None, allow_redirects=True):
        if url.endswith("/actions/artifacts"):
            per, page = min(int(params.get("per_page", 30)), 100), int(params.get("page", 1))
            named = sorted((a for a in self.artifacts if a["name"] == params["name"]),
                           key=lambda a: a["created_at"], reverse=True)
            self.pages.append(page)
            return _Response(200, {"total_count": len(named),
                                   "artifacts": named[(page - 1) * per:page * per]})
        return super().get(url, headers, timeout, params, allow_redirects)

    def delete(self, url, headers=None, timeout=None):
        if self.rate_limit_after is not None and len(self.deleted) >= self.rate_limit_after:
            response = _Response(403)
            response.headers = {"X-RateLimit-Remaining": "0"}
            return response
        return super().delete(url, headers, timeout)


def _hourly(count: int, name: str = "sealed-registry", start: int = 0, **kw) -> list[dict]:
    return [_artifact(start + i, f"2026-11-{1 + i // 48:02d}T{(i // 2) % 24:02d}:{17 + 30 * (i % 2)}:00Z",
                      run=10_000 + start + i, name=name, **kw) for i in range(count)]


def test_a_privacy_delete_prunes_every_older_backup_past_the_first_page() -> None:
    """Reproduced (review): `GitHub.artifacts()` made ONE request with
    per_page=100 and no page, so prune deleted the newest 100 backups and left
    every older encrypted copy of the deleted person for up to 90 days — on a
    week of hourly backups, 236 of 336. The list is now read to the end
    before anything is deleted (deleting while paging would shift the
    pages), for both names, and this run's own uploads stay."""
    registry = _hourly(336)
    plans = _hourly(130, name="sealed-plans", start=1000)
    keep_run = registry[-1]["workflow_run"]["id"]
    gh = _PagedGitHub(registry + plans, {})
    assert sb.prune(("registry", "plans"), sb.GitHub("o/r", "tok", session=gh), keep_run) == 465
    assert len(gh.deleted) == 465 and registry[-1]["id"] not in gh.deleted
    assert sorted(set(gh.pages)) == [1, 2, 3, 4]


def test_a_rate_limit_part_way_through_a_prune_is_red_and_says_how_to_finish() -> None:
    """Deleting hundreds of artifacts one call at a time can meet GITHUB_TOKEN's
    hourly limit; prune raises part-way (the step goes red) and says that
    running the same delete again finishes it — run.privacy finds the person
    already gone and the prune deletes the rest."""
    gh = _PagedGitHub(_hourly(150), {}, rate_limit_after=120)
    with pytest.raises(sb.SealError, match=r"after 120 of 150 .* run the same privacy delete"):
        sb.prune(("registry",), sb.GitHub("o/r", "tok", session=gh), keep_run=-1)


@needs_openssl
def test_a_restore_looks_past_the_first_page_for_this_repos_own_backup(
        tmp_path, monkeypatch) -> None:
    """The restore reads the same whole list: 150 newer artifacts a fork's
    pull requests uploaded under the same name push ours to page 2, and the
    restore still finds it (a one-page read said "no backup exists yet")."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    reg = _registry(tmp_path)
    before = _tree(reg)
    sb.seal("registry", tmp_path, iterations=FAST)
    good = sb.sealed_path("registry", tmp_path).read_bytes()
    shutil.rmtree(tmp_path / "data")
    ours = _artifact(1, "2026-10-01T00:00:00Z")
    forks = [_artifact(100 + i, f"2026-10-20T00:{i % 60:02d}:{i // 60:02d}Z", head_repo=99)
             for i in range(150)]
    gh = _PagedGitHub([ours, *forks], {1: _zip("registry", good)})
    result = sb.restore_backup("registry", sb.GitHub("o/r", "tok", session=gh), tmp_path,
                               branch="main")
    assert result["opened"] and _tree(tmp_path / "data" / "registry") == before


def test_no_sealed_registry_anywhere_is_red_once_a_customer_was_served(
        tmp_path, monkeypatch) -> None:
    """The INFRA-06 remainder: the Worker's dispatch token (Actions: write) can
    delete the caches AND the backups, and 90 days of failed runs expires
    them, after which `open --backup` said "no backup exists yet", exited 0,
    and the runs rebuilt a Stripe-only registry without the seats and roster
    changes Stripe never held. Nothing anywhere is still the first run while
    the committed send log holds only run markers, free reports, the waitlist
    and notices; once it shows a customer was served it is a lost copy and a
    red run, unless ALLOW_EMPTY_REGISTRY=true says to start fresh."""
    monkeypatch.setenv("CACHE_KEY", KEY)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.delenv("ALLOW_EMPTY_REGISTRY", raising=False)
    real = sb.GitHub.from_env
    monkeypatch.setattr(sb.GitHub, "from_env", classmethod(
        lambda cls, session=None: real.__func__(cls, session=_PagedGitHub([], {}))))
    log = tmp_path / "data" / "processed" / "sent.jsonl"
    log.parent.mkdir(parents=True)
    quiet = ["run-daily-2026-10-24", "run-tuesday-2026-w08", "trial-2026-abcdef123456",
             "launch-2026-abcdef12", "notice-terms-2026-11-15-abcdef123456"]
    log.write_text("".join(json.dumps({"key": k}) + "\n" for k in quiet), encoding="utf-8")
    args = ["open", "registry", "--backup", "--root", str(tmp_path)]
    assert sb.main(args) == 0
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"key": "2026-w08-ab12cd34ef"}) + "\n")
    assert sb.main(args) == 1
    assert not (tmp_path / "data" / "registry").exists()
    assert sb.main(["open", "plans", "--backup", "--root", str(tmp_path)]) == 0
    monkeypatch.setenv("ALLOW_EMPTY_REGISTRY", "true")
    assert sb.main(args) == 0
    for key in ("welcome-2026-10-24-abc", "preseason-2026-abc", "2026-w08-final-abc",
                "seat-confirm-ab-cd", "confirm-ab-cd"):
        assert sb.SERVED.match(key), key
    for key in quiet:
        assert not sb.SERVED.match(key), key


def test_the_approval_recipe_signs_exactly_the_words_typed(tmp_path) -> None:
    """Reproduced (review): `make notice-approval` interpolated "$(SUMMARY)"
    into a double-quoted shell word, so make expanded "$69" to "9" and the
    shell dropped embedded quotes — the code was signed over words nobody
    pasted and the workflow refused it, for any summary naming a price. The
    recipe now passes each variable's RAW text, single-quoted, and with no
    SUMMARY reads it from stdin; run here with a stand-in for Python that
    prints what it was given."""
    import subprocess
    import sys
    if shutil.which("make") is None:
        pytest.skip("make is not installed")
    fake = tmp_path / "fake_python.py"
    fake.write_text("import json, sys\nprint(json.dumps([sys.argv[1:], sys.stdin.read()]))\n",
                    encoding="utf-8")
    summary = "The League Pass is now $69 for the \"rest\" of it, isn't it `x` $(HOME) $$y."
    base = ["make", "-s", "-C", str(REPO), "notice-approval", f"PY={sys.executable} {fake}",
            "PAGE=terms", "EFFECTIVE=2026-11-15"]
    done = subprocess.run([*base, f"SUMMARY={summary}"], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stderr
    argv, _ = json.loads(done.stdout)
    assert argv == ["-m", "run.approval", "notice", "terms", "2026-11-15", summary]
    done = subprocess.run(base, capture_output=True, text=True, input=summary + "\n")
    argv, stdin = json.loads(done.stdout)
    assert argv[-1] == "-" and stdin == summary + "\n"


def test_a_summary_read_from_stdin_signs_the_same_code(monkeypatch, capsys) -> None:
    """`run.approval notice PAGE EFFECTIVE -` reads the words from stdin (what
    the make recipe does without SUMMARY), so no shell ever touches them;
    the code is the one the argument form makes, and the words it signed
    are echoed to the owner's own terminal."""
    import run.approval as approval
    monkeypatch.setenv("LOG_SECRET", "owner-secret")
    words = 'Now $69, "quoted".'
    monkeypatch.setattr("sys.stdin", io.StringIO(words + "\n"))
    assert approval.main(["notice", "terms", "2026-11-15", "-"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == approval.code("notice", "terms", "2026-11-15", words)
    assert words in out.err


def test_the_secrets_gate_counts_the_cache_key(monkeypatch) -> None:
    """Reproduced (review): this branch made CACHE_KEY a required secret —
    once STRIPE_API_KEY is set, a run without it goes red and keeps no
    registry, seat log or roster changes between runs — but the launch check
    still said "all 12 present" without it (the OPS-4 class)."""
    import subprocess
    import run.launch_check as lc
    assert "CACHE_KEY" in lc.REQUIRED_SECRETS
    names = [n for n in lc.REQUIRED_SECRETS if n != "CACHE_KEY"]
    monkeypatch.setattr(lc.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(lc.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, json.dumps([{"name": n} for n in names]), ""))
    [gate, *_] = lc.check_secrets()
    assert gate.status == "OWNER" and "CACHE_KEY" in gate.detail
    assert "Keeping subscribers, seats and roster changes between runs" in gate.detail


def test_the_owners_hardening_is_read_back_by_the_launch_check(monkeypatch) -> None:
    """INFRA-15: the verified Pages domain, DNSSEC, the main ruleset and the
    live HSTS/CSP were owner steps nothing read back. Each is an OWNER line
    until done (CAA a WARN: optional until the host settles), PASS after."""
    import run.launch_check as lc

    class Page:
        def __init__(self, headers, status=200, text="Contact: mailto:x\n"):
            self.headers, self.status_code, self.text = headers, status, text

    def run(dns, rules, headers):
        monkeypatch.setattr(lc, "_dig", lambda kind, name: dns.get(kind, []))
        monkeypatch.setattr(lc, "_gh_json", lambda path: rules)
        monkeypatch.setattr("requests.get", lambda url, timeout=None: Page(headers))
        return {g.name: g.status for g in lc.check_hardening()}

    bare = run({}, [], {"server": "GitHub.com"})
    assert bare["The domain is verified for GitHub Pages"] == "OWNER"
    assert bare["DNSSEC is on"] == "OWNER"
    assert bare["main can't be force-pushed or deleted"] == "OWNER"
    assert bare["The live site sends HSTS and a Content-Security-Policy"] == "OWNER"
    assert bare["CAA records limit who may issue the certificate"] == "WARN"
    done = run({"TXT": ["abc123"], "DS": ["2371 13 2 ABCD"], "CAA": ['0 issue "pki.goog"']},
               [{"type": "deletion"}, {"type": "non_fast_forward"}],
               {"Strict-Transport-Security": "max-age=31536000",
                "Content-Security-Policy": "default-src 'self'"})
    assert set(done.values()) == {"PASS"}, done


def test_security_txt_names_the_contact_and_its_expiry_is_watched() -> None:
    """INFRA-15: site/.well-known/security.txt (RFC 9116) tells a security
    reporter where to write. The launch check passes it, warns in its last
    30 days and fails once it has expired."""
    from datetime import date
    import run.launch_check as lc
    text = (REPO / "site" / ".well-known" / "security.txt").read_text(encoding="utf-8")
    assert "Contact: mailto:hello@beatyourleague.com" in text
    assert "Canonical: https://beatyourleague.com/.well-known/security.txt" in text
    assert [g.status for g in lc.check_security_txt(date(2026, 10, 24))] == ["PASS"]
    assert [g.status for g in lc.check_security_txt(date(2027, 9, 15))] == ["WARN"]
    assert [g.status for g in lc.check_security_txt(date(2027, 10, 2))] == ["FAIL"]


def test_the_daily_intake_maps_the_email_headroom_variable() -> None:
    """Routed from the delivery work: the daily intake reads
    EMAIL_DAILY_HEADROOM for when the email plan's daily cap changes; it
    arrives as a repo variable, never pasted into the shell."""
    steps = list(_docs()["daily.yml"]["jobs"].values())[0]["steps"]
    intake_step = next(s for s in steps if s.get("id") == "intake")
    assert intake_step["env"]["EMAIL_DAILY_HEADROOM"] == "${{ vars.EMAIL_DAILY_HEADROOM }}"
