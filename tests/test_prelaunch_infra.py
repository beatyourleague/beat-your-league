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
            deletes = "gh cache delete" in commands or "statebox prune" in commands
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
    assert checkouts == len(_docs()) and pushers == 6


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
            assert "statebox seal" in _command(seal) and which in _command(seal)
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
        opens = [s for s in steps if "statebox open" in _command(s)]
        assert len(opens) == 1, name
        [opener] = opens
        assert "--backup" in _command(opener)
        assert opener["env"]["CACHE_KEY"] == "${{ secrets.CACHE_KEY }}"
        assert opener["env"]["GH_TOKEN"] == "${{ github.token }}"
        for restore in restores:
            which = re.search(r"(registry|plans)", restore["with"]["path"]).group(1)
            assert which in _command(opener), (name, which)
            assert steps.index(restore) < steps.index(opener)
        for seal in (s for s in steps if "statebox seal" in _command(s)):
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
    assert 'statebox prune registry plans --keep-run "$GITHUB_RUN_ID"' in command
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
    assert installs == len(_docs()) - 1          # pages.yml installs nothing


def test_the_crons_that_rebuild_a_page_commit_its_fresh_headers() -> None:
    """The Tuesday run rebuilds this-week.html and the Monday run the ledger
    page; each re-derives site/_headers and commits it with them, so a page
    whose script changed never meets a stale policy on Cloudflare Pages."""
    for name, page in (("weekly.yml", "site/this-week.html"), ("monday.yml", "site/ledger/")):
        steps = list(_docs()[name]["jobs"].values())[0]["steps"]
        commands = [_command(s) for s in steps]
        refresh = next(i for i, c in enumerate(commands) if "-m render.headers" in c)
        persist = next(i for i, c in enumerate(commands) if PUSH in c)
        assert refresh <= persist, name
        assert re.search(rf"git add[^\n]*{re.escape(page)}[^\n]*site/_headers", commands[persist]) \
            or re.search(r"git add[^\n]*site/_headers", commands[persist]), name


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
    never `/*`, because Cloudflare joins two matching values with a comma
    and two CSPs are enforced together — every script would stop."""
    from render.headers import MAX_LINE, MAX_RULES, OUT, SITE, paths_for
    text = OUT.read_text(encoding="utf-8")
    rules = _rules(text)
    common = rules["/*"]
    assert common["Strict-Transport-Security"].startswith("max-age=31536000")
    assert common["X-Content-Type-Options"] == "nosniff"
    assert common["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert common["X-Frame-Options"] == "DENY"
    assert "camera=()" in common["Permissions-Policy"]
    assert "Content-Security-Policy" not in common
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
