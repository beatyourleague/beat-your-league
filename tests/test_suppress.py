"""The stop list (run/suppress.py): what backs "you're off within 10 business
days", promised to every League Pass seat and the waitlist (launch audit C4).

The file is committed to a public repo, so the property that matters most is
that it never holds an address — and the second is that it agrees with the
free report's send-log digest about which mailbox an address is.
"""

from __future__ import annotations

import re
from pathlib import Path

from run.suppress import (SUPPRESS_FILE, add, address_digest, is_suppressed,
                          load_suppressed, main, remove)
from run.trials import trial_key


def test_the_committed_stop_list_holds_digests_never_addresses() -> None:
    """Every line a reader of the public repo can see is a comment or 12 hex.
    One plain address here would publish exactly the person who asked us to
    leave them alone."""
    assert SUPPRESS_FILE.is_file(), "the stop list must be committed, even empty"
    for line in SUPPRESS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert re.fullmatch(r"[0-9a-f]{12}", line), f"not a digest: {line[:3]}…"


def test_the_digest_is_the_free_reports_digest() -> None:
    """Same canonical form, same digest as the send log's trial key — one
    definition of "this mailbox", so the two lists can never disagree."""
    for email in ("fan@example.com", "F.an+x@Gmail.com", "  Someone@Example.COM "):
        assert trial_key("2026", email).endswith("-" + address_digest(email))
    assert address_digest("f.a.n+tag@gmail.com") == address_digest("fan@googlemail.com")


def test_add_check_and_remove(tmp_path: Path, capsys) -> None:
    path = tmp_path / "suppressed.txt"
    assert main(["seat@example.com", "--file", str(path)]) == 0
    assert "Added 1" in capsys.readouterr().out
    assert main(["Seat+x@Example.com", "--file", str(path)]) == 0
    assert "Added 0" in capsys.readouterr().out, "one mailbox is one entry"
    assert is_suppressed("seat@example.com", load_suppressed(path))
    text = path.read_text(encoding="utf-8")
    assert "seat" not in text and "example" not in text, "an address reached the file"

    assert main(["--check", "seat@example.com", "--file", str(path)]) == 0
    assert "on the list" in capsys.readouterr().out
    assert main(["--remove", "seat@example.com", "--file", str(path)]) == 0
    assert not is_suppressed("seat@example.com", load_suppressed(path))


def test_the_file_diffs_as_one_sorted_line_per_request(tmp_path: Path) -> None:
    path = tmp_path / "suppressed.txt"
    add(["b@example.com"], path)
    add(["a@example.com"], path)
    digests = [l for l in path.read_text().splitlines() if not l.startswith("#")]
    assert digests == sorted(digests) and len(digests) == 2
    assert remove(["nobody@example.com"], path) == 0


def test_a_bad_address_changes_nothing_and_is_never_echoed(tmp_path: Path, capsys) -> None:
    path = tmp_path / "suppressed.txt"
    assert main(["not-an-address", "--file", str(path)]) == 2
    out = capsys.readouterr()
    assert "not-an-address" not in out.out + out.err
    assert not path.exists()


def test_an_address_pasted_by_hand_is_still_honoured(tmp_path: Path) -> None:
    """The tool never writes one, and the committed-file test keeps one out —
    but a stop typed into the file by hand must stop the mail, not be
    silently ignored."""
    path = tmp_path / "suppressed.txt"
    path.write_text("# header\nfan+x@example.com\n", encoding="utf-8")
    assert is_suppressed("fan@example.com", load_suppressed(path))
