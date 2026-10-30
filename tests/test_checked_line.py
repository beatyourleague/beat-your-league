"""The report shows its work (Oct 25 2026): card 01 says what it checked for
this roster. The cold-buyer review scored "why pay when rankings are free"
6/10 because the work a ranking never does was invisible. Counts the report
holds, never an outcome."""
import re

from render import anatomy, sample
from render.email import render_email, text_summary


def test_the_checked_line_counts_what_the_report_read() -> None:
    w10 = sample.build(10)
    line = anatomy.checked_line(w10)
    assert line == "15 players, 9 slots, every kickoff time and the Week 9 injury report."
    # A replayed week has no byes ahead to check, so it does not claim one;
    # week 1 has no injury report before it, so it names none.
    assert "byes" not in line
    assert "injury report" not in anatomy.checked_line(sample.build(1))


def test_the_checked_line_rides_every_surface_and_claims_nothing() -> None:
    w10 = sample.build(10)
    line = anatomy.checked_line(w10)
    assert line in render_email(w10) and line in text_summary(w10)
    assert not re.search(r"%|\bwin|\bbetter\b|\bmore\b|guarantee", line, re.I)


def test_a_live_week_names_the_byes_it_checked() -> None:
    live = sample.build(10)
    live["meta"] = {**live["meta"], "historical_demo": False}
    assert anatomy.checked_line(live).endswith("and the byes still ahead.")
