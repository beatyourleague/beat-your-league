"""One person's data: show it, export it, or delete it (D5).

Usage:
    python -m run.privacy code <email>             LOCAL ONLY: the keyed code to pass on
    python -m run.privacy show   <code> [--send]   what we hold, as counts
    python -m run.privacy export <code> [--send]   everything, readable, to hello@
    python -m run.privacy delete <code> [--send]   remove it, then report

``site/privacy.html`` promises access, correction, deletion and portability
within 30 days. Before this, deletion was impossible (LEGAL-128/130/133): the
registry lives in the GitHub Actions cache, which cannot be edited by hand, and
deleting the cache wholesale drops every other subscriber's seats and roster
updates — after which a full Stripe re-sweep re-adds the person anyway.

Rules:

- **A keyed code goes in, never an address.** The workflow that runs this
  (``.github/workflows/privacy.yml``, workflow_dispatch) is in a public repo,
  and dispatch inputs are printed in its log. The operator makes the code
  locally (``code <email>``, needs LOG_SECRET in the shell) and passes that;
  the run matches every stored address by computing the same code
  (run/digest.py).
- **Results go to the hello@ inbox, never to a log.** stdout carries counts
  and nothing else; the rows themselves are mailed to CONTACT only, and a
  ``--send`` without an email provider refuses rather than printing them.
- **Delete covers what we hold** — the signup log, seat log, roster-update log,
  the registry, every stored weekly plan, the stop list and the form Worker's
  rows — and records the person's Stripe customer id(s) in
  ``data/processed/forgotten.txt`` (committed; ids only), which the intake's
  sweep skips, so re-reading old payments cannot bring them back. A new
  purchase creates a new customer and is served normally.
- **What it cannot reach is said, by name:** the Stripe customer and its
  payments (deleted in the Dashboard), the hello@ mailbox, and Worker rows
  when the Worker has no delete route — each listed in the email as a step
  for the operator, so the 30-day promise is met by a checklist, not memory.
- **Rows that merely NAME the person** (a seat whose payer they are) are
  reported, not deleted: they are somebody else's subscription.

Dry by default. ``delete`` without ``--send`` changes nothing and says what it
would remove.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_DIR = REPO_ROOT / "data" / "registry"
PLANS_DIR = REPO_ROOT / "data" / "plans"
FORGOTTEN_FILE = REPO_ROOT / "data" / "processed" / "forgotten.txt"
ACTIONS = ("show", "export", "delete")
_CODE = re.compile(r"^[0-9a-f]{12}$")
_CUSTOMER_ID = re.compile(r"^cus_[A-Za-z0-9]{4,}$")
_FORGOTTEN_CODE = re.compile(r"^[0-9a-f]{16}$")
FORGOTTEN_HEADER = (
    "# Stripe customers whose data was deleted on request (run/privacy.py).\n"
    "# The intake's sweep skips their old payments so a re-read cannot restore\n"
    "# them. Keyed codes of customer ids (run/digest.py, LOG_SECRET) - never an\n"
    "# id or an address, since this file is in a public repository.\n")


class PrivacyError(RuntimeError):
    pass


@dataclass
class Found:
    """Everything held about one code. Rows are kept for the email only."""

    signups: list[dict] = field(default_factory=list)
    seats: list[dict] = field(default_factory=list)
    updates: list[dict] = field(default_factory=list)
    registry: list[dict] = field(default_factory=list)
    named_as_payer: int = 0
    plans: list[Path] = field(default_factory=list)
    stop_list: bool = False
    worker: list[dict] = field(default_factory=list)
    worker_error: str = ""

    def counts(self) -> dict[str, int]:
        return {"signups": len(self.signups), "seat claims": len(self.seats),
                "roster updates": len(self.updates), "registry rows": len(self.registry),
                "stored weekly plans": len(self.plans),
                "on the stop list": int(self.stop_list),
                "form rows": len(self.worker),
                "seats naming them as payer (kept)": self.named_as_payer}

    @property
    def customers(self) -> set[str]:
        ids = {str(r.get(k) or "") for r in (*self.signups, *self.registry)
               for k in ("stripe_customer_id",)}
        return {i for i in ids if _CUSTOMER_ID.match(i)}


# --------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------- #

def _matches(code: str):
    from run.digest import address

    def test(value: object) -> bool:
        text = str(value or "").strip()
        return bool(text) and "@" in text and address(text) == code
    return test


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _slugs(rows: list[dict]) -> set[str]:
    import hashlib
    out: set[str] = set()
    for row in rows:
        for key in ("origin", "replaces"):
            if re.fullmatch(r"[0-9a-f]{10}", str(row.get(key) or "")):
                out.add(str(row[key]))
        if row.get("ref"):
            out.add(hashlib.sha256(str(row["ref"]).encode("utf-8")).hexdigest()[:10])
    return out


def fetch_worker_rows(endpoint: str, api_key: str | None) -> list[dict]:
    from run.intake import fetch_seats
    return fetch_seats(endpoint, api_key)


def find(code: str, registry_dir: Path, plans_dirs: list[Path],
         suppress_file: Path | None = None, worker_rows: list[dict] | None = None,
         ) -> Found:
    from run.intake import REGISTRY_NAME, SEAT_LOG_NAME, SIGNUP_LOG_NAME
    from run.suppress import load_suppressed
    from run.updates import UPDATE_LOG_NAME
    hit = _matches(code)
    found = Found()
    found.signups = [r for r in _jsonl(registry_dir / SIGNUP_LOG_NAME) if hit(r.get("email"))]
    found.seats = [r for r in _jsonl(registry_dir / SEAT_LOG_NAME) if hit(r.get("email"))]
    found.updates = [r for r in _jsonl(registry_dir / UPDATE_LOG_NAME) if hit(r.get("email"))]
    registry = registry_dir / REGISTRY_NAME
    rows = json.loads(registry.read_text(encoding="utf-8")) if registry.is_file() else []
    rows = rows if isinstance(rows, list) else []
    found.registry = [r for r in rows if isinstance(r, dict) and hit(r.get("email"))]
    found.named_as_payer = sum(1 for r in rows if isinstance(r, dict)
                               and hit(r.get("covered_by")) and not hit(r.get("email")))
    slugs = _slugs([*found.signups, *found.seats, *found.updates, *found.registry])
    for root in plans_dirs:
        for slug in slugs:
            found.plans.extend(sorted(Path(root).glob(f"*/w??-{slug}.json")))
    found.stop_list = code in load_suppressed(suppress_file)
    found.worker = [r for r in (worker_rows or []) if hit(r.get("email"))]
    return found


# --------------------------------------------------------------------- #
# deleting
# --------------------------------------------------------------------- #

def _rewrite_jsonl(path: Path, keep) -> int:
    rows = _jsonl(path)
    kept = [r for r in rows if keep(r)]
    if len(kept) != len(rows):
        path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in kept),
                        encoding="utf-8")
    return len(rows) - len(kept)


def forget(code: str, found: Found, registry_dir: Path,
           suppress_file: Path | None = None, forgotten_file: Path | None = None,
           ) -> dict[str, int]:
    """Remove every row found. Returns counts. Writes only what changes."""
    from run.intake import REGISTRY_NAME, SEAT_LOG_NAME, SIGNUP_LOG_NAME
    from run.suppress import SUPPRESS_FILE, _write, load_suppressed
    from run.updates import UPDATE_LOG_NAME
    hit = _matches(code)
    keep = lambda r: not hit(r.get("email"))  # noqa: E731
    done = {"signups": _rewrite_jsonl(registry_dir / SIGNUP_LOG_NAME, keep),
            "seat claims": _rewrite_jsonl(registry_dir / SEAT_LOG_NAME, keep),
            "roster updates": _rewrite_jsonl(registry_dir / UPDATE_LOG_NAME, keep)}
    registry = registry_dir / REGISTRY_NAME
    removed = 0
    if registry.is_file():
        rows = json.loads(registry.read_text(encoding="utf-8"))
        kept = [r for r in rows if not (isinstance(r, dict) and hit(r.get("email")))]
        removed = len(rows) - len(kept)
        if removed:
            from run.intake import write_registry
            write_registry(kept, registry)
    done["registry rows"] = removed
    for plan in found.plans:
        plan.unlink(missing_ok=True)
    done["stored weekly plans"] = len(found.plans)
    stop = suppress_file or SUPPRESS_FILE
    held = set(load_suppressed(stop))
    done["on the stop list"] = int(code in held)
    if code in held:
        _write(stop, held - {code})
    customers = found.customers
    if customers:
        path = forgotten_file or FORGOTTEN_FILE
        known = load_forgotten(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        codes = {forgotten_code(c) for c in customers}
        path.write_text(FORGOTTEN_HEADER + "".join(f"{c}\n" for c in sorted(known | codes)),
                        encoding="utf-8")
    done["customers recorded as forgotten"] = len(customers)
    return done


def forgotten_code(customer_id: str) -> str:
    """The keyed code a forgotten customer is recorded under: the file is
    committed to a public repository, and a raw Stripe id there would tie a
    deletion request to a customer for anyone reading it."""
    from run.digest import keyed
    return keyed(customer_id, 16)


def is_forgotten(customer_id: str | None, codes: set[str]) -> bool:
    return bool(customer_id and codes) and forgotten_code(customer_id) in codes


def load_forgotten(path: Path | None = None) -> set[str]:
    """Keyed codes of customers whose old payments the intake must never re-read."""
    path = path or FORGOTTEN_FILE
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if _FORGOTTEN_CODE.match(line.strip())}


def delete_worker_rows(rows: list[dict], endpoint: str, api_key: str) -> tuple[int, int]:
    """(deleted, left for the operator). A row can be deleted only when the
    Worker gave its storage key (``_key``) and answers DELETE; otherwise it is
    left and the email says so — never a silent skip."""
    deleted = 0
    for row in rows:
        key = str(row.get("_key") or "")
        if not key:
            continue
        request = urllib.request.Request(
            f"{endpoint}?{urllib.parse.urlencode({'key': key})}", method="DELETE",
            headers={"Authorization": f"Bearer {api_key}"})
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    deleted += int(200 <= response.status < 300)
                break
            except urllib.error.HTTPError as exc:
                # The /rows flood limit counts every request, so back-to-back
                # deletes can meet a 429: wait out its 10-second block once.
                if exc.code == 429 and attempt == 1:
                    time.sleep(11)
                    continue
                break
            except OSError:
                break
    return deleted, len(rows) - deleted


# --------------------------------------------------------------------- #
# the email to hello@ — the only place the rows themselves ever go
# --------------------------------------------------------------------- #

MANUAL = (
    "Stripe: open the customer(s) listed and delete them (their payments stay "
    "in Stripe's own records as the law requires); cancel any live subscription "
    "first.",
    "The hello@ mailbox: delete this person's threads, including this email "
    "once the request is answered.",
    "Reply to the person within 30 days of their request, saying what was done.",
)


def report_email(action: str, code: str, found: Found, done: dict[str, int] | None,
                 worker_left: int, sent_at: str):
    from render.report import esc
    from render.seat_claim import _footer_lines, _para, _shell
    from render.sender import CONTACT
    from run.delivery import Message
    lines = [f"Privacy request · {action} · code {code} · {sent_at}", ""]
    lines += [f"{k}: {v}" for k, v in found.counts().items()]
    if found.worker_error:
        lines.append(f"form rows could not be read: {found.worker_error}")
    if done is not None:
        lines += ["", "Deleted:"] + [f"  {k}: {v}" for k, v in done.items()]
        if worker_left:
            lines.append(f"  form rows left for you to delete in the Cloudflare KV "
                         f"browser: {worker_left} (received_at: "
                         + ", ".join(str(r.get("received_at")) for r in found.worker[:10])
                         + ")")
        lines += ["", "Still to do by hand:"] + [f"  - {m}" for m in MANUAL]
        if found.customers:
            lines.append("  Stripe customer(s): " + ", ".join(sorted(found.customers)))
    if action == "export":
        from run.refs import RefError, decode_roster
        decoded = []
        for row in found.registry:
            try:
                roster = decode_roster(str(row.get("ref")))
                decoded.append({"scoring": roster.scoring, "league_size": roster.league_size,
                                "slots": list(roster.slots), "players": list(roster.player_ids)})
            except RefError:
                continue
        export = {"signups": found.signups, "seat_claims": found.seats,
                  "roster_updates": found.updates, "registry": found.registry,
                  "rosters_decoded": decoded,
                  "weekly_plans": [json.loads(p.read_text(encoding="utf-8"))
                                   for p in found.plans if p.is_file()],
                  "form_rows": found.worker, "on_stop_list": found.stop_list}
        lines += ["", "Everything held, as JSON (send the person this part):",
                  json.dumps(export, indent=1, default=str)]
    text = "\n".join(lines) + "\n\n" + "\n".join(_footer_lines()) + "\n"
    subject = f"Privacy request: {action} ({code})"
    html = _shell(subject, f"{action} for code {code}",
                  "".join(_para(line) for line in lines if line.strip())
                  if action != "export" else
                  "".join(_para(line) for line in lines[:-1] if line.strip())
                  + f'<pre style="font-size:12px;white-space:pre-wrap;">{esc(lines[-1])}</pre>')
    return Message(to=CONTACT, subject=subject, html=html, text=text,
                   key=f"privacy-{action}-{sent_at}", unsubscribe=None)


# --------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("code", *ACTIONS))
    parser.add_argument("value", help="an email (code) or a 12-hex keyed code")
    parser.add_argument("--send", action="store_true",
                        help="mail the result to hello@ (and, for delete, apply it)")
    parser.add_argument("--registry-dir", type=Path, default=REGISTRY_DIR)
    parser.add_argument("--plans-dir", type=Path, default=PLANS_DIR)
    args = parser.parse_args(argv)

    from run.digest import DigestError, address
    if args.action == "code":
        if os.environ.get("GITHUB_ACTIONS"):
            # The address would land in a public log.
            print("Make the code on your own machine, never in CI.", file=sys.stderr)
            return 2
        try:
            print(address(args.value))
        except DigestError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    code = args.value.strip().lower()
    if not _CODE.match(code):
        # Never echoed: it might be an address pasted by mistake.
        print("That is not a 12-hex code. Make one locally with "
              "`python -m run.privacy code <email>`; never pass an address.",
              file=sys.stderr)
        return 2
    try:
        address("probe@example.com")
    except DigestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    endpoint = os.environ.get("FORM_ENDPOINT", "").strip()
    api_key = os.environ.get("FORM_API_KEY", "").strip()
    worker: list[dict] = []
    error = ""
    if endpoint:
        try:
            worker = fetch_worker_rows(endpoint, api_key or None)
        except Exception as exc:  # noqa: BLE001 — reported, never fatal to the rest
            error = type(exc).__name__
    from run.saturday import FIRST_PLANS_NAME
    found = find(code, args.registry_dir,
                 [args.plans_dir, args.registry_dir / FIRST_PLANS_NAME],
                 worker_rows=worker)
    found.worker_error = error

    print(f"Privacy · {args.action} · code {code}")
    for name, count in found.counts().items():
        print(f"  {name}: {count}")
    if error:
        print(f"  ! the form Worker could not be read ({error})", file=sys.stderr)

    if not args.send:
        print("(dry run — nothing changed and nothing mailed. Pass --send.)")
        return 0

    from run.delivery import DRY_PROVIDER, build_provider, send_all
    provider = build_provider(None)
    if provider.name == DRY_PROVIDER:
        print("NOT DONE: EMAIL_PROVIDER is not set, and the results may only go "
              "to the hello@ inbox — never to this log.", file=sys.stderr)
        return 1
    done = worker_left = None
    if args.action == "delete":
        done = forget(code, found, args.registry_dir)
        deleted, worker_left = delete_worker_rows(found.worker, endpoint, api_key) \
            if endpoint and api_key else (0, len(found.worker))
        done["form rows"] = deleted
        for name, count in done.items():
            print(f"  deleted {name}: {count}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result = send_all([report_email(args.action, code, found, done, worker_left or 0,
                                    stamp)], provider=provider)[0]
    if not result.ok:
        print(f"The report to hello@ failed: {result.detail}", file=sys.stderr)
        return 1
    print("Report mailed to the hello@ inbox."
          + (" Commit data/processed/forgotten.txt and suppressed.txt."
             if args.action == "delete" else ""))
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
