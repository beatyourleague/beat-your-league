"""Sealed state: the subscriber registry and the stored plans, encrypted before
they leave the runner, with a durable encrypted copy beside the cache.

Usage (the crons run these; the owner runs them by hand to restore):
    python -m run.statebox open registry [--backup]   # data/sealed/registry.enc -> data/registry/
    python -m run.statebox seal registry              # data/registry/ -> data/sealed/registry.enc
    python -m run.statebox prune registry plans --keep-run <run id>   # privacy deletes

Why (INFRA-02, pre-launch review Oct 2026). ``data/registry`` (every
subscriber's address, roster and Stripe ids) and ``data/plans`` (the lineups
they were sent) lived in plain text in an Actions cache. In a public repo a
pull-request run can restore the caches its base branch made, so code a
stranger's PR adds — a new workflow, or a changed test — could print every
subscriber into a public log the moment the owner pressed "Approve and run".
And the cache was the ONLY copy: GitHub evicts an entry after 7 days unused,
and ``seat-log.jsonl`` and the roster-update log cannot be rebuilt from Stripe.

So, four rules:

- **RULE S1 — nothing leaves the runner in plain text.** ``seal`` writes
  ``data/sealed/<name>.enc`` and only that file is cached or uploaded. Without
  ``CACHE_KEY`` (or with a short one) it REFUSES and exits 1 when there is
  anything to seal: a red run, never a plaintext cache. Fork and pull-request
  runs get no secrets, so a stolen ``.enc`` is ciphertext.
- **RULE S2 — a file that fails its check is never used.** Encrypt-then-MAC:
  AES-256-CBC (``openssl enc`` with a raw key, so OpenSSL and LibreSSL agree)
  under one PBKDF2-derived key and HMAC-SHA256 over every byte before the tag
  under another. ``open`` verifies the tag before decrypting anything, and a
  wrong key, a truncated download and a tampered file all read the same way:
  exit 1, nothing written, and the workflow saves nothing over the good copy.
- **RULE S3 — losing the cache is not losing customers.** Every run that seals
  something new also uploads it as an artifact (``sealed-<name>``, kept 90
  days, the longest a public repo allows), and the once-a-day run uploads even
  when nothing changed, so a quiet offseason still keeps a fresh copy. ``open
  --backup`` reaches for the newest one when the cache comes back empty —
  only artifacts made on this repo's own branch, newest first, the first that
  passes RULE S2. An API failure exits 1 rather than carrying on as if there
  were nothing to restore: a run that then wrote a fresh registry would make
  the partial one the newest copy.
- **RULE S4 — a deletion reaches every copy.** The privacy workflow's delete
  seals the edited state, uploads it, then ``prune`` deletes every older
  ``sealed-<name>`` artifact, the same way it deletes the older caches. An
  encrypted backup still holds the person's rows, and the privacy policy says
  deleted means deleted.

``CACHE_KEY`` is a GitHub secret (``openssl rand -hex 32``) with a copy in the
owner's password manager. Losing it makes every sealed copy unreadable; the
registry can then be rebuilt from Stripe, but confirmed seats and roster
updates cannot. Never change it (LAUNCH.md step 3).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NAMES = ("registry", "plans")
ENV = "CACHE_KEY"
MIN_KEY_LENGTH = 32
MAGIC = b"BYLSEAL1"
ITERATIONS = 200_000
MIN_ITERATIONS = 10_000
SALT_LEN = IV_LEN = 16
TAG_LEN = 32
# The newest few backups are tried in turn: a planted or truncated artifact
# fails its tag and the next one is used (RULE S2), never a guess.
BACKUP_CANDIDATES = 5
MAX_BACKUP_BYTES = 50 * 1024 * 1024
API = "https://api.github.com"


class SealError(RuntimeError):
    """Sealing or opening refused. Carries no key and no file contents."""


class NoKeyError(SealError):
    """CACHE_KEY is not set at all (a short one is a plain SealError)."""


def data_dir(name: str, root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / "data" / name


def sealed_path(name: str, root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / "data" / "sealed" / f"{name}.enc"


def artifact_name(name: str) -> str:
    return f"sealed-{name}"


def cache_key() -> str:
    """CACHE_KEY from the environment, or SealError. Never echoed."""
    value = os.environ.get(ENV, "").strip()
    if not value:
        raise NoKeyError(f"{ENV} is not set (LAUNCH.md step 3: openssl rand -hex 32)")
    if len(value) < MIN_KEY_LENGTH:
        raise SealError(f"{ENV} is shorter than {MIN_KEY_LENGTH} characters — make a new "
                        f"one with `openssl rand -hex 32` before anything is sealed")
    return value


def _keys(secret: str, salt: bytes, iterations: int) -> tuple[bytes, bytes]:
    material = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt,
                                   iterations, dklen=64)
    return material[:32], material[32:]


def _openssl(args: list[str], data: bytes) -> bytes:
    exe = shutil.which("openssl")
    if not exe:
        raise SealError("openssl is not installed, so nothing can be sealed or opened")
    done = subprocess.run([exe, "enc", *args], input=data, capture_output=True, check=False)
    if done.returncode != 0:
        # stderr names the failure (bad decrypt, wrong length), never the key.
        raise SealError("openssl refused: "
                        + done.stderr.decode("utf-8", "replace").strip()[:200])
    return done.stdout


def encrypt(plain: bytes, secret: str, iterations: int = ITERATIONS) -> bytes:
    salt, iv = os.urandom(SALT_LEN), os.urandom(IV_LEN)
    enc_key, mac_key = _keys(secret, salt, iterations)
    body = _openssl(["-aes-256-cbc", "-K", enc_key.hex(), "-iv", iv.hex()], plain)
    head = MAGIC + iterations.to_bytes(4, "big") + salt + iv
    tag = hmac.new(mac_key, head + body, hashlib.sha256).digest()
    return head + body + tag


def decrypt(blob: bytes, secret: str) -> bytes:
    """The plaintext, or SealError — the tag is checked before any decryption."""
    head_len = len(MAGIC) + 4 + SALT_LEN + IV_LEN
    if len(blob) < head_len + TAG_LEN + 16 or not blob.startswith(MAGIC):
        raise SealError("not a sealed file (wrong format or truncated)")
    iterations = int.from_bytes(blob[len(MAGIC):len(MAGIC) + 4], "big")
    if iterations < MIN_ITERATIONS:
        raise SealError("sealed file failed its integrity check")
    salt = blob[len(MAGIC) + 4:len(MAGIC) + 4 + SALT_LEN]
    iv = blob[len(MAGIC) + 4 + SALT_LEN:head_len]
    body, tag = blob[head_len:-TAG_LEN], blob[-TAG_LEN:]
    enc_key, mac_key = _keys(secret, salt, iterations)
    expected = hmac.new(mac_key, blob[:-TAG_LEN], hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise SealError("sealed file failed its integrity check — the wrong CACHE_KEY, "
                        "or the file was cut short or altered")
    return _openssl(["-d", "-aes-256-cbc", "-K", enc_key.hex(), "-iv", iv.hex()], body)


def _files(src: Path) -> list[Path]:
    if not src.is_dir():
        return []
    return sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink())


def content_digest(src: Path) -> str:
    """sha256 over every file's relative path and bytes. Stays on the runner:
    it only answers "did this run change anything?"."""
    h = hashlib.sha256()
    for path in _files(src):
        rel = path.relative_to(src).as_posix().encode("utf-8")
        data = path.read_bytes()
        h.update(len(rel).to_bytes(4, "big") + rel + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def pack(src: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in _files(src):
            info = tar.gettarinfo(str(path), arcname=path.relative_to(src).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as handle:
                tar.addfile(info, handle)
    return buffer.getvalue()


def unpack(data: bytes, dest: Path) -> None:
    """Regular files only, every path inside ``dest`` (tarfile's data filter
    plus a second look of our own)."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            name = Path(member.name)
            if not (member.isfile() or member.isdir()) or name.is_absolute() \
                    or ".." in name.parts:
                raise SealError(f"sealed file holds an unexpected entry: {member.name!r}")
        tar.extractall(dest, members=members, filter="data")


def _opened_marker(name: str, root: Path | None) -> Path:
    return sealed_path(name, root).with_suffix(".opened")


def seal(name: str, root: Path | None = None, iterations: int = ITERATIONS) -> dict:
    """data/<name>/ -> data/sealed/<name>.enc. Returns {"sealed", "changed"}."""
    src, out = data_dir(name, root), sealed_path(name, root)
    if not _files(src):
        out.unlink(missing_ok=True)
        return {"sealed": False, "changed": False, "detail": f"nothing in data/{name} to seal"}
    try:
        secret = cache_key()
    except SealError:
        out.unlink(missing_ok=True)      # a stale copy must not ride the save step
        raise
    digest = content_digest(src)
    marker = _opened_marker(name, root)
    before = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    blob = encrypt(pack(src), secret, iterations)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(out)
    return {"sealed": True, "changed": digest != before,
            "detail": f"data/{name} sealed ({len(_files(src))} files)"}


def open_sealed(name: str, root: Path | None = None, blob: bytes | None = None) -> dict:
    """data/sealed/<name>.enc (or ``blob``) -> data/<name>/. Refuses to write
    over a directory that already holds files."""
    src = sealed_path(name, root)
    if blob is None:
        if not src.is_file():
            return {"opened": False, "detail": f"no sealed {name} to open"}
        blob = src.read_bytes()
    dest = data_dir(name, root)
    if _files(dest):
        raise SealError(f"data/{name} already holds files; move them aside first "
                        f"(nothing was overwritten)")
    plain = decrypt(blob, cache_key())
    with tempfile.TemporaryDirectory(dir=dest.parent if dest.parent.is_dir() else None) as tmp:
        staging = Path(tmp) / name
        staging.mkdir()
        unpack(plain, staging)
        if dest.exists():
            shutil.rmtree(dest)          # holds no files, checked above
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(dest))
    marker = _opened_marker(name, root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(content_digest(dest) + "\n", encoding="utf-8")
    return {"opened": True, "detail": f"data/{name} opened ({len(_files(dest))} files)"}


# --------------------------------------------------------------------- #
# the durable copy: this repo's own artifacts (RULE S3, S4)
# --------------------------------------------------------------------- #

class GitHub:
    """The few Actions REST calls this needs, with the job's own token."""

    def __init__(self, repo: str, token: str, session=None) -> None:
        import requests
        self.repo, self.http = repo, session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"}

    @classmethod
    def from_env(cls, session=None) -> "GitHub | None":
        repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
        return cls(repo, token, session) if repo and token else None

    def _get(self, url: str, **kw):
        response = self.http.get(url, headers=self.headers, timeout=30, **kw)
        if response.status_code != 200:
            raise SealError(f"GitHub answered {response.status_code} for {url.split('?')[0]}")
        return response

    def repository_id(self) -> int:
        return int(self._get(f"{API}/repos/{self.repo}").json()["id"])

    def artifacts(self, name: str) -> list[dict]:
        data = self._get(f"{API}/repos/{self.repo}/actions/artifacts",
                         params={"name": name, "per_page": 100}).json()
        return [a for a in data.get("artifacts") or [] if a.get("name") == name]

    def download(self, artifact: dict) -> bytes:
        if int(artifact.get("size_in_bytes") or 0) > MAX_BACKUP_BYTES:
            raise SealError("backup artifact is larger than any sealed state could be")
        return self._get(artifact["archive_download_url"], allow_redirects=True).content

    def delete(self, artifact: dict) -> None:
        response = self.http.delete(f"{API}/repos/{self.repo}/actions/artifacts/{artifact['id']}",
                                    headers=self.headers, timeout=30)
        if response.status_code not in (204, 404):
            raise SealError(f"GitHub answered {response.status_code} deleting a backup")


def _ours(artifacts: list[dict], repo_id: int, branch: str) -> list[dict]:
    """Unexpired backups a run on THIS repo's branch made, newest first. A
    fork's pull-request run can upload an artifact with any name; it is
    never a candidate."""
    keep = []
    for a in artifacts:
        run = a.get("workflow_run") or {}
        if a.get("expired"):
            continue
        if run.get("head_repository_id") != repo_id or run.get("repository_id") != repo_id:
            continue
        if branch and run.get("head_branch") != branch:
            continue
        keep.append(a)
    return sorted(keep, key=lambda a: a.get("created_at") or "", reverse=True)


def _enc_from_zip(raw: bytes, name: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            return archive.read(f"{name}.enc")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise SealError(f"backup artifact does not hold {name}.enc") from exc


def restore_backup(name: str, gh: GitHub, root: Path | None = None,
                   branch: str | None = None) -> dict:
    """Open the newest of this repo's own backups that passes its check."""
    branch = branch if branch is not None else os.environ.get("GITHUB_REF_NAME", "")
    candidates = _ours(gh.artifacts(artifact_name(name)), gh.repository_id(), branch)
    if not candidates:
        return {"opened": False, "detail": f"no backup of {name} exists yet"}
    failures = []
    for artifact in candidates[:BACKUP_CANDIDATES]:
        try:
            blob = _enc_from_zip(gh.download(artifact), name)
            result = open_sealed(name, root, blob=blob)
        except SealError as exc:
            failures.append(str(exc))
            continue
        sealed = sealed_path(name, root)
        sealed.parent.mkdir(parents=True, exist_ok=True)
        sealed.write_bytes(blob)
        return {**result, "detail": result["detail"]
                + f" from the backup of {artifact.get('created_at', '?')}"}
    raise SealError(f"no backup of {name} passed its check ({failures[0]})")


def prune(names: tuple[str, ...], gh: GitHub, keep_run: int) -> int:
    """Delete every sealed-<name> backup except those this run uploaded."""
    deleted = 0
    for name in names:
        for artifact in gh.artifacts(artifact_name(name)):
            if (artifact.get("workflow_run") or {}).get("id") == keep_run:
                continue
            gh.delete(artifact)
            deleted += 1
    return deleted


def _output(**values: object) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("open", "seal", "prune"))
    parser.add_argument("names", nargs="+", choices=NAMES)
    parser.add_argument("--backup", action="store_true",
                        help="open: on a cache miss, restore the newest artifact backup")
    parser.add_argument("--keep-run", type=int, default=None,
                        help="prune: the run whose backups stay")
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    names = tuple(dict.fromkeys(args.names))
    try:
        if args.action == "prune":
            gh = GitHub.from_env()
            if gh is None or args.keep_run is None:
                raise SealError("prune needs GITHUB_REPOSITORY, a token and --keep-run")
            print(f"Deleted {prune(names, gh, args.keep_run)} older backup(s).")
            return 0
        for name in names:
            if args.action == "seal":
                try:
                    result = seal(name, args.root)
                except NoKeyError:
                    # Before launch — no Stripe key either, so nobody has paid —
                    # nothing is cached and that is not an alarm. Still never
                    # plain text: the save step sees sealed=false and skips.
                    if os.environ.get("STRIPE_KEY_SET", "").strip().lower() != "false":
                        raise
                    result = {"sealed": False, "changed": False,
                              "detail": f"before launch (no Stripe key, no {ENV}): "
                                        f"data/{name} is not cached"}
                # Step outputs <name>_sealed / <name>_changed gate the cache
                # save and the backup upload; a refused name writes neither.
                _output(**{f"{name}_sealed": result["sealed"],
                           f"{name}_changed": result["changed"]})
            else:
                result = open_sealed(name, args.root)
                if not result["opened"] and args.backup:
                    gh = GitHub.from_env()
                    if gh is None:
                        result["detail"] += "; no GitHub token, so no backup was looked for"
                    else:
                        result = restore_backup(name, gh, args.root)
            print(result["detail"])
    except SealError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, tarfile.TarError, json.JSONDecodeError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — a network library's own error
        if type(exc).__module__.startswith("requests"):
            print(f"REFUSED: could not reach GitHub ({type(exc).__name__})", file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
