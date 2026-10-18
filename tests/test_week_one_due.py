"""run.solo.week_one_due — a derived Week 1 is never built months early."""
from datetime import datetime, timedelta, timezone

import pytest

from run import solo


@pytest.fixture
def kickoff(monkeypatch):
    at = datetime(2027, 9, 10, 0, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(solo, "week_first_kickoff", lambda cache, season, week: at)
    return at


def test_week_one_is_not_due_when_the_schedule_lands_in_may(kickoff):
    """Promise audit EMAILS-62: with next season's schedule published,
    current_week answers 1 and the Tuesday run mailed a "Week 1" report in May,
    built from last season's roster."""
    assert not solo.week_one_due(solo.CACHE_DIR, "2027", 1,
                                 datetime(2027, 5, 18, 13, tzinfo=timezone.utc))


def test_week_one_is_due_from_the_lead_before_kickoff(kickoff):
    assert solo.week_one_due(solo.CACHE_DIR, "2027", 1, kickoff - solo.WEEK_ONE_LEAD)
    assert not solo.week_one_due(solo.CACHE_DIR, "2027", 1,
                                 kickoff - solo.WEEK_ONE_LEAD - timedelta(minutes=1))


def test_an_unknown_kickoff_is_not_due(monkeypatch):
    monkeypatch.setattr(solo, "week_first_kickoff", lambda *a: None)
    assert not solo.week_one_due(solo.CACHE_DIR, "2027", 1)


def test_every_other_week_is_due(monkeypatch):
    monkeypatch.setattr(solo, "week_first_kickoff", lambda *a: None)
    assert solo.week_one_due(solo.CACHE_DIR, "2027", 2)
