"""Unit tests for services.contest."""

from datetime import date, datetime, timezone

import pytest

from model import Contest, ContestStatus, User
from services.contest import (
    ContestLocked,
    create_contest,
    get_contest,
    list_contests,
    start_contest,
    update_contest,
)


def _naive_utc(dt):
    """Drop tzinfo for comparison (DB backends return stored instants naive)."""
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


def make_user(db, username="Creator"):
    user = User(username=username, can_create_contest=True)
    db.session.add(user)
    db.session.commit()
    return user


# --- create ---

def test_create_makes_pending_contest(db):
    user = make_user(db)

    c = create_contest(user.id, "Photo Contest", "commons", start_date="2026-01-01",
                       marks_setting_accepted=10,
                       eligibility_rules={"min_byte_count": 500}, jury_members=["A", "B"])

    assert c.id is not None
    assert c.status == ContestStatus.PENDING.value
    assert c.created_by == user.id
    assert c.rule("min_byte_count") == 500
    assert c.jury_members == ["A", "B"]
    assert Contest.query.count() == 1


def test_create_requires_name_and_project(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="name is required"):
        create_contest(user.id, "  ", "commons")
    with pytest.raises(ValueError, match="Project name is required"):
        create_contest(user.id, "X", "")


def test_create_requires_start_date(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="[Ss]tart date is required"):
        create_contest(user.id, "X", "commons")   # no start_date


def test_create_rejects_end_before_start(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="End date must be on or after"):
        create_contest(user.id, "X", "commons", start_date="2026-12-01",
                       end_date="2026-01-01", marks_setting_accepted=10)


def test_create_allows_past_dates(db):
    # Past start/end is allowed on purpose (campaigns start before setup; the
    # words-added metric relies on the start date).
    user = make_user(db)

    c = create_contest(user.id, "Past", "commons", start_date="2020-01-01",
                       end_date="2020-02-01", marks_setting_accepted=10)

    assert c.start_date.year == 2020 and c.end_date.year == 2020


def test_create_allows_equal_start_and_end(db):
    user = make_user(db)

    c = create_contest(user.id, "Same", "commons", start_date="2026-01-01",
                       end_date="2026-01-01", marks_setting_accepted=10)

    assert c.start_date.date() == c.end_date.date()


def test_update_rejects_end_before_existing_start(db):
    # A locked contest can only edit end_date — the new end is checked against
    # the contest's existing start.
    user = make_user(db, "Creator")
    c = create_contest(user.id, "X", "commons", start_date="2026-06-01",
                       marks_setting_accepted=10)
    start_contest(c)  # now active/locked

    with pytest.raises(ValueError, match="End date must be on or after"):
        update_contest(c, end_date="2026-01-01")


def test_create_adds_creator_as_organizer(db):
    user = make_user(db, "Creator")

    c = create_contest(user.id, "X", "commons", start_date="2026-01-01",
                       marks_setting_accepted=10)

    assert c.organizers == ["Creator"]
    assert c.is_organizer("Creator")


def test_create_inserts_organizer_and_jury_users(db):
    creator = make_user(db, "Creator")

    create_contest(creator.id, "X", "commons", start_date="2026-01-01",
                   marks_setting_accepted=10,
                   organizers=["OrgA"], jury_members=["JuryB", "JuryC"])

    names = {u.username for u in User.query.all()}
    assert {"Creator", "OrgA", "JuryB", "JuryC"} <= names


def test_create_keeps_provided_organizers_with_creator(db):
    user = make_user(db, "Creator")

    c = create_contest(user.id, "X", "commons", start_date="2026-01-01",
                       marks_setting_accepted=10, organizers=["Bob"])

    assert set(c.organizers) == {"Creator", "Bob"}


def test_create_requires_accepted_marks(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="marks_setting_accepted is required"):
        create_contest(user.id, "X", "commons", start_date="2026-01-01")   # no marks


def test_create_rejects_non_positive_accepted_marks(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="marks_setting_accepted must be a positive"):
        create_contest(user.id, "X", "commons", start_date="2026-01-01",
                       marks_setting_accepted=0)
    with pytest.raises(ValueError, match="marks_setting_accepted must be a positive"):
        create_contest(user.id, "X", "commons", start_date="2026-01-01",
                       marks_setting_accepted=-5)


def test_create_rejects_positive_rejected_marks(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="marks_setting_rejected must be zero or negative"):
        create_contest(user.id, "X", "commons", start_date="2026-01-01",
                       marks_setting_accepted=10, marks_setting_rejected=5)


def test_create_accepts_valid_marks(db):
    user = make_user(db)

    c = create_contest(user.id, "X", "commons", start_date="2026-01-01",
                       marks_setting_accepted=10, marks_setting_rejected=-2)

    assert c.marks_setting_accepted == 10
    assert c.marks_setting_rejected == -2


def test_create_parses_bare_date_as_utc_midnight(db):
    user = make_user(db)

    c = create_contest(user.id, "X", "commons", start_date="2026-09-01",
                       marks_setting_accepted=10)

    # A bare date is anchored to the start of that day in UTC. (The DB returns
    # the stored instant naive; the wall-clock value is what matters.)
    assert _naive_utc(c.start_date) == datetime(2026, 9, 1)


def test_create_parses_iso_datetime_with_offset(db):
    user = make_user(db)

    # Aug 24 23:59 in IST (UTC+5:30) -> Aug 24 18:29 UTC.
    c = create_contest(user.id, "X", "commons",
                       start_date="2026-08-24T00:00:00+05:30",
                       end_date="2026-08-24T23:59:00+05:30",
                       timezone="Asia/Kolkata",
                       marks_setting_accepted=10)

    assert _naive_utc(c.start_date) == datetime(2026, 8, 23, 18, 30)
    assert _naive_utc(c.end_date) == datetime(2026, 8, 24, 18, 29)
    assert c.timezone == "Asia/Kolkata"


def test_create_rejects_bad_date(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="ISO date or datetime"):
        create_contest(user.id, "X", "commons", start_date="not-a-date")


def test_create_rejects_unknown_timezone(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="Unknown timezone"):
        create_contest(user.id, "X", "commons", start_date="2026-09-01",
                       timezone="Mars/Olympus", marks_setting_accepted=10)


# --- list / get ---

def test_list_defaults_to_active_only(db):
    user = make_user(db)
    pending = create_contest(user.id, "Pending", "commons", start_date="2026-01-01", marks_setting_accepted=10)
    active = create_contest(user.id, "Active", "commons", start_date="2026-01-01", marks_setting_accepted=10)
    start_contest(active)

    # Default: only active contests.
    assert [x.id for x in list_contests()] == [active.id]
    # include_all: pending too.
    assert {x.id for x in list_contests(include_all=True)} == {pending.id, active.id}


def test_list_includes_viewers_own_pending(db):
    a = make_user(db, "A")
    b = make_user(db, "B")
    create_contest(a.id, "ADraft", "commons", start_date="2026-01-01", marks_setting_accepted=10)   # pending, A's
    create_contest(b.id, "BDraft", "commons", start_date="2026-01-01", marks_setting_accepted=10)   # pending, B's
    active = create_contest(a.id, "Active", "commons", start_date="2026-01-01", marks_setting_accepted=10)
    start_contest(active)

    assert {x.name for x in list_contests()} == {"Active"}                       # anon
    assert {x.name for x in list_contests(viewer_id=a.id)} == {"Active", "ADraft"}  # A sees own pending
    assert {x.name for x in list_contests(include_all=True)} == {"ADraft", "BDraft", "Active"}


def test_get_returns_any_contest(db):
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01", marks_setting_accepted=10)   # pending

    assert get_contest(c.id).id == c.id           # get is not status-filtered
    assert get_contest(9999) is None


# --- update ---

def test_update_while_pending(db):
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01", marks_setting_accepted=10)

    updated = update_contest(c, name="Renamed", eligibility_rules={"min_byte_count": 1000})

    assert updated.name == "Renamed"
    assert updated.rule("min_byte_count") == 1000


def test_update_rejects_empty_name(db):
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01", marks_setting_accepted=10)

    with pytest.raises(ValueError, match="name cannot be empty"):
        update_contest(c, name="   ")


def test_update_locked_after_start(db):
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01", marks_setting_accepted=10)
    start_contest(c)

    with pytest.raises(ContestLocked):
        update_contest(c, name="Too late")


def test_update_end_date_allowed_after_start(db):
    # A running contest can be extended (or closed early) by editing end_date.
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01",
                       end_date="2026-06-01T23:59:59+00:00", marks_setting_accepted=10)
    start_contest(c)

    update_contest(c, end_date="2026-09-01T23:59:59+00:00")

    assert _naive_utc(c.end_date) == datetime(2026, 9, 1, 23, 59, 59)


def test_update_start_date_still_locked_after_start(db):
    # Only end_date is unlocked; start_date (and other config) stays locked.
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01", marks_setting_accepted=10)
    start_contest(c)

    with pytest.raises(ContestLocked):
        update_contest(c, start_date="2026-02-01")


# --- start ---

def test_start_transitions_to_active(db):
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01", marks_setting_accepted=10)

    started = start_contest(c)

    assert started.status == ContestStatus.ACTIVE.value


def test_start_twice_raises(db):
    user = make_user(db)
    c = create_contest(user.id, "X", "commons", start_date="2026-01-01", marks_setting_accepted=10)
    start_contest(c)

    with pytest.raises(ContestLocked, match="already been started"):
        start_contest(c)
