"""`make signups` — the owner's private view of the addresses people entered.

The one tool that prints addresses, so its guards are the point: it never
runs in CI (the repository is public), never writes a CSV where it could be
committed or published, shows one line per mailbox, says the one use each
group of addresses was given for, and marks anyone who asked us to stop.
No test here touches the network: the Worker read is a stub.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import run.rosters as rosters
import run.signups as signups

NOW = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
SECRET = "test-log-secret"

ROWS = [
    {"kind": "waitlist", "email": "Fan.One+x@gmail.com", "via": "reddit",
     "received_at": "2026-10-20T03:00:00Z", "_key": "waitlist:a"},
    {"kind": "waitlist", "email": "fanone@gmail.com", "ref": "s3-pc12abc",
     "received_at": "2026-10-28T12:00:00Z", "_key": "waitlist:b"},
    {"kind": "waitlist", "email": "late@example.com",
     "received_at": "2026-11-02T12:00:00Z", "_key": "waitlist:c"},
    {"kind": "trial", "email": "kim@example.com", "ref": "s3-x", "via": "x",
     "received_at": "2026-10-01T08:00:00Z"},
    {"kind": "rookie_ask", "email": "rook@example.com", "received_at": "2026-10-02T08:00:00Z"},
    {"kind": "team_add", "email": "kim@example.com", "ref": "s3-y",
     "received_at": "2026-10-03T08:00:00Z"},
    {"kind": "seat", "email": "seat@example.com", "ref": "s3-z", "pass_token": "t" * 24,
     "received_at": "2026-10-04T08:00:00Z"},
    {"kind": "trade_check", "email": "trader@example.com", "ref": "s3-w",
     "received_at": "2026-10-05T08:00:00Z"},
    {"kind": "update_request", "email": "sub@example.com", "ref": "s3-v",
     "received_at": "2026-10-06T08:00:00Z"},
    {"kind": "confirm", "code": "0" * 24, "received_at": "2026-10-06T09:00:00Z"},
]


@pytest.fixture(autouse=True)
def _no_registry(monkeypatch):
    """A developer machine may hold a real registry; no test here reads it
    unless it installs one itself."""
    def missing(path=None):
        raise rosters.RosterRegistryError("no roster registry")
    monkeypatch.setattr(rosters, "load_rosters", missing)


def run(argv, capsys, rows=ROWS, settings=None, suppress_file=None, gitignored=None):
    settings = {"FORM_ENDPOINT": "https://w.test", "FORM_API_KEY": "k",
                **(settings or {})}
    code = signups.main(argv + ["--now", NOW.isoformat()], settings=settings,
                        fetch=lambda endpoint, key: list(rows),
                        gitignored=gitignored or (lambda p: True),
                        suppress_file=suppress_file or Path("/nonexistent/suppressed.txt"))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_it_refuses_in_ci(capsys) -> None:
    for environ in ({"CI": "true"}, {"GITHUB_ACTIONS": "true"}):
        assert signups.cli([], environ=environ, env_file=Path("/nonexistent")) == 2
        err = capsys.readouterr().err
        assert "does not run in CI" in err and "public" in err


def test_one_mailbox_is_one_line_and_its_first_spelling_shows(capsys) -> None:
    """Gmail dots and +tags are one inbox (run.trials.canonical_email): the
    two waitlist rows above are one person, seen twice, first on Oct 19 in
    Eastern time (03:00 UTC on the 20th), with the roster the second carried."""
    code, out, _ = run([], capsys)
    assert code == 0
    section = out.split("WAITLIST: TELL ME WHEN IT OPENS")[1].split("\n\n")[0]
    assert "— 2 people" in section
    assert section.count("Fan.One+x@gmail.com") == 1 and "fanone@gmail.com" not in section
    line = next(l for l in section.splitlines() if "Fan.One" in l)
    assert line.split()[:2] == ["2026-10-19", "2"]
    assert "reddit" in line and " yes " in line


def test_rows_are_grouped_by_what_was_asked_for_each_with_its_one_use(capsys) -> None:
    code, out, _ = run([], capsys)
    assert code == 0
    for heading, address in (("FREE REPORT REQUESTS", "kim@example.com"),
                             ("ROOKIE REPORT REQUESTS", "rook@example.com"),
                             ("EXTRA TEAM REQUESTS", "kim@example.com"),
                             ("LEAGUE PASS SEAT CLAIMS", "seat@example.com"),
                             ("TRADE CHECK REQUESTS", "trader@example.com"),
                             ("ROSTER-UPDATE REQUESTS", "sub@example.com")):
        section = out.split(heading)[1].split("\n\n")[0]
        assert address in section
    assert "For the one launch email only" in out
    # kim asked for two things and is one person in the total.
    assert "7 people in all" in out
    assert "Don't add them to a mailing list" in out
    # A seat's pass token and a confirm code are never printed.
    assert "t" * 24 not in out and "0" * 24 not in out


def test_kind_and_since_narrow_the_view(capsys) -> None:
    _, out, _ = run(["--kind", "waitlist"], capsys)
    assert "kim@example.com" not in out and "late@example.com" in out
    _, out, _ = run(["--since", "3"], capsys)
    assert "late@example.com" in out and "Fan.One" not in out and "kim@" not in out


def test_an_address_that_asked_to_stop_is_marked_and_left_out_of_the_csv(
        tmp_path, capsys, monkeypatch) -> None:
    """run/suppress.py: someone on the stop list is never emailed again. The
    view still shows they signed up, marked, and the CSV — the copy most
    likely to reach a mailer — leaves them out. The keyed code matches the
    one the stop list itself writes (run.digest.address)."""
    from run.digest import address
    monkeypatch.setenv("LOG_SECRET", SECRET)
    assert signups.stop_code("Late@Example.com", SECRET) == address("late@example.com")
    stop = tmp_path / "suppressed.txt"
    stop.write_text(f"# header\n{address('late@example.com')}\n", encoding="utf-8")
    monkeypatch.delenv("LOG_SECRET")
    target = tmp_path / "signups.csv"
    code, out, err = run(["--csv", str(target)], capsys,
                         settings={"LOG_SECRET": SECRET}, suppress_file=stop)
    assert code == 0
    line = next(l for l in out.splitlines() if "late@example.com" in l)
    assert "asked us to stop" in line
    assert "asked us to stop" not in next(l for l in out.splitlines() if "kim@" in l)
    with target.open(encoding="utf-8") as handle:
        written = list(csv.DictReader(handle))
    assert "late@example.com" not in {r["address"] for r in written}
    assert "leaving out 1" in err and "personal data" in err
    assert target.stat().st_mode & 0o077 == 0


def test_a_stop_list_nobody_can_check_marks_everyone_and_refuses_a_csv(
        tmp_path, capsys) -> None:
    stop = tmp_path / "suppressed.txt"
    stop.write_text("0123456789ab\n", encoding="utf-8")
    code, out, _ = run([], capsys, suppress_file=stop)
    assert code == 0
    assert "LOG_SECRET is not in" in out
    assert "stop list not checked" in next(l for l in out.splitlines() if "kim@" in l)
    target = tmp_path / "signups.csv"
    code, _, err = run(["--csv", str(target)], capsys, suppress_file=stop)
    assert code == 2 and not target.exists() and "LOG_SECRET" in err


def test_an_unreadable_stop_list_shows_nothing(tmp_path, capsys) -> None:
    stop = tmp_path / "suppressed.txt"
    stop.write_bytes(b"\xff\xfe\x00bad")
    code, out, err = run([], capsys, suppress_file=stop)
    assert code == 1 and "@" not in out and "stop list" in err


def test_the_csv_goes_only_to_a_gitignored_path_outside_site(tmp_path, capsys,
                                                              monkeypatch) -> None:
    target = tmp_path / "signups.csv"
    code, _, err = run(["--csv", str(target)], capsys, gitignored=lambda p: False)
    assert code == 2 and not target.exists() and "not gitignored" in err
    # A stand-in site/, so a broken guard can't leave a file in the real one.
    monkeypatch.setattr(signups, "SITE_DIR", tmp_path / "site")
    inside = signups.SITE_DIR / "signups.csv"
    code, _, err = run(["--csv", str(inside)], capsys)
    assert code == 2 and not inside.exists() and "inside site/" in err


def test_the_real_gitignore_check_refuses_a_tracked_path(capsys) -> None:
    """The default check is git's own (run.stats._gitignored): a path in the
    repo that is not ignored — the README's folder — is refused."""
    from run.stats import _gitignored
    assert not _gitignored(signups.REPO_ROOT / "run" / "signups.csv")
    assert _gitignored(signups.REPO_ROOT / "data" / "signups.csv")


def test_a_csv_cell_never_becomes_a_formula(tmp_path, capsys) -> None:
    rows = [{"kind": "waitlist", "email": "=cmd@example.com",
             "received_at": "2026-10-20T03:00:00Z"}]
    target = tmp_path / "s.csv"
    assert run(["--csv", str(target)], capsys, rows=rows)[0] == 0
    with target.open(encoding="utf-8") as handle:
        assert next(csv.DictReader(handle))["address"] == "'=cmd@example.com"


def test_an_address_with_a_control_character_is_counted_never_printed(capsys) -> None:
    rows = [{"kind": "waitlist", "email": "a\x1b[2J@example.com",
             "received_at": "2026-10-20T03:00:00Z"}]
    code, out, _ = run([], capsys, rows=rows)
    assert code == 0 and "\x1b" not in out and "1 row(s) held an address" in out


def test_subscribers_are_marked_from_a_registry_copy(monkeypatch, capsys) -> None:
    registry = [SimpleNamespace(email="fanone@gmail.com", plan="season", billing="monthly"),
                SimpleNamespace(email="seat@example.com", plan="league_pass", billing=None)]
    monkeypatch.setattr(rosters, "load_rosters", lambda path=None: registry)
    code, out, _ = run(["--registry", "/x/rosters.json"], capsys)
    assert code == 0
    assert "monthly" in next(l for l in out.splitlines() if "Fan.One" in l)
    assert "seat" in next(l for l in out.splitlines()
                          if "seat@example.com" in l).split("seat@example.com")[0]
    assert "subscriber" in out


def test_without_a_registry_it_says_so_and_has_no_subscriber_column(capsys) -> None:
    code, out, _ = run([], capsys)
    assert code == 0 and "No subscriber list on this machine" in out
    assert "  subscriber  " not in out


def test_an_unreadable_worker_fails(capsys) -> None:
    from run.intake import IntakeError

    def broken(endpoint, key):
        raise IntakeError("seat backend returned HTTP 503")
    code = signups.main(["--now", NOW.isoformat()], settings={"FORM_ENDPOINT": "https://w"},
                        fetch=broken, suppress_file=Path("/nonexistent"))
    assert code == 1 and "Could not read the form Worker" in capsys.readouterr().err


def test_the_worker_settings_come_from_dotenv_and_the_shell_wins(tmp_path, monkeypatch,
                                                                  capsys) -> None:
    import run.intake as intake
    asked = []
    monkeypatch.setattr(intake, "fetch_seats",
                        lambda endpoint, key=None: asked.append((endpoint, key)) or [])
    env = tmp_path / ".env"
    env.write_text("FORM_ENDPOINT=https://w.file\nFORM_API_KEY='file-key'\n", encoding="utf-8")
    assert signups.cli(["--now", NOW.isoformat()], environ={}, env_file=env) == 0
    assert signups.cli(["--now", NOW.isoformat()], environ={"FORM_ENDPOINT": "https://w.shell"},
                       env_file=env) == 0
    assert asked == [("https://w.file", "file-key"), ("https://w.shell", "file-key")]
    assert "No address to show." in capsys.readouterr().out


def test_every_worker_kind_with_an_address_has_a_group() -> None:
    """A kind the Worker stores with an email must not fall into "Other"
    unnoticed: every one in infra/form-worker.js KINDS but "confirm" is named."""
    import re
    worker = (signups.REPO_ROOT / "infra" / "form-worker.js").read_text(encoding="utf-8")
    block = re.search(r"const KINDS = \[(.*?)\];", worker, re.S).group(1)
    kinds = set(re.findall(r'"([a-z_]+)"', block)) - {"confirm"}
    assert kinds == {k for k, _h, _u in signups.KINDS}


def test_it_never_writes_to_the_worker() -> None:
    """Read-only: the module has no POST, DELETE or urlopen of its own."""
    source = Path(signups.__file__).read_text(encoding="utf-8")
    for word in ("urlopen", '"POST"', '"DELETE"', "delete_worker_rows"):
        assert word not in source


def test_a_differently_cased_site_path_is_still_inside_site(tmp_path, capsys,
                                                            monkeypatch) -> None:
    """A Mac's disk ignores case, so SITE/signups.csv IS site/signups.csv.
    The guard compared names, so SITE/x.pyc (gitignored by *.pyc) went
    straight into the published folder. It compares the file system now."""
    folder = tmp_path / "site"
    folder.mkdir()
    if not (tmp_path / "SITE").exists():
        pytest.skip("this disk is case-sensitive, so SITE/ is another folder here")
    monkeypatch.setattr(signups, "SITE_DIR", folder)
    target = tmp_path / "SITE" / "signups.csv"
    code, _, err = run(["--csv", str(target)], capsys)
    assert code == 2 and not (folder / "signups.csv").exists() and "inside site/" in err


def test_a_csv_name_hard_linked_to_a_page_never_writes_into_the_page(tmp_path) -> None:
    """The path checks read the NAME. If that name is a hard link to a page,
    writing through it would put every address into the page. The CSV is a
    new file moved into place, so the page keeps its own contents (even one
    that starts like an earlier copy, which the overwrite check lets by)."""
    page = tmp_path / "page.html"
    head = ",".join(signups.CSV_FIELDS) + "\n<p>public</p>"
    page.write_text(head, encoding="utf-8")
    target = tmp_path / "signups.csv"
    target.hardlink_to(page)
    groups, _ = signups.group(ROWS)
    signups.write_csv(target, groups)
    assert page.read_text(encoding="utf-8") == head
    assert "late@example.com" in target.read_text(encoding="utf-8")
    assert target.stat().st_mode & 0o077 == 0
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".signups-")] == []


def test_the_csv_never_replaces_a_file_it_did_not_write(tmp_path, capsys) -> None:
    """.env, the owner's books (data/costs.csv) and the registry are all
    gitignored, so the gitignore check lets them by, and none of them is kept
    anywhere else. Only an earlier copy of this CSV may be replaced."""
    books = tmp_path / "costs.csv"
    books.write_text("date,amount,what\n2026-10-01,12.00,domain\n", encoding="utf-8")
    code, _, err = run(["--csv", str(books)], capsys)
    assert code == 2 and "already holds something else" in err
    assert books.read_text(encoding="utf-8").startswith("date,amount")
    target = tmp_path / "signups.csv"
    assert run(["--csv", str(target)], capsys)[0] == 0
    assert run(["--csv", str(target)], capsys)[0] == 0


def test_a_test_address_is_marked_so_it_never_reads_as_a_real_signup(capsys) -> None:
    """Sweep TOOLS-2: the Worker's only waitlist row was the business's own
    address, and a list of one reads as one real person. make stats and the
    dashboard leave such rows out; this view keeps them but says so."""
    rows = [{"kind": "waitlist", "email": "hello@beatyourleague.com",
             "received_at": "2026-11-02T05:02:58Z"},
            {"kind": "waitlist", "email": "fan@gmail.com",
             "received_at": "2026-11-02T06:00:00Z"}]
    code, out = run([], capsys, rows=rows)[:2]
    assert code == 0
    line = next(l for l in out.splitlines() if "hello@beatyourleague.com" in l)
    assert line.endswith("[test]")
    assert "[test]" not in next(l for l in out.splitlines() if "fan@gmail.com" in l)
    assert "1 of them is a test address" in out
