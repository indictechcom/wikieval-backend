"""Extensive timezone tests for the contest window.

Covers the full path a deadline travels:
  client ISO string -> services.contest parsing/validation -> UTC storage
  -> model serialization -> submission end-date guard.

Key invariant under test: the timezone *string* need not be canonical or stable
across systems (Asia/Kolkata vs its alias Asia/Calcutta), but the stored UTC
*instant* must always be correct and unambiguous. See also the frontend suite
(wikieval-frontend/tests/timezone.test.js) and scripts/verify_timezone_parity.py
which checks that the two engines agree on the same wall-clock -> UTC math.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from model import Contest, User
from services.contest import create_contest, start_contest, update_contest
from services.submission import create_submission, evaluate_article

ARTICLE = "https://en.wikipedia.org/wiki/Cat"


def make_user(db, username="Creator"):
    user = User(username=username, can_create_contest=True)
    db.session.add(user)
    db.session.commit()
    return user


def _naive_utc(dt):
    """Drop tzinfo for comparison — DB backends return stored instants naive."""
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


def new_contest(db, **fields):
    user = make_user(db, fields.pop("username", "Creator"))
    fields.setdefault("start_date", "2020-01-01")
    fields.setdefault("marks_setting_accepted", 10)
    return create_contest(user.id, "C", "commons", **fields)


# ---------------------------------------------------------------------------
# Parsing: client ISO string -> UTC-aware datetime
# ---------------------------------------------------------------------------

def test_bare_date_anchors_to_utc_midnight(db):
    c = new_contest(db, start_date="2026-09-01")
    assert _naive_utc(c.start_date) == datetime(2026, 9, 1, 0, 0, 0)


def test_offset_datetime_converts_to_utc(db):
    # Aug 24 23:59 IST (+05:30) -> Aug 24 18:29 UTC.
    c = new_contest(db, start_date="2026-08-24T23:59:00+05:30",
                    timezone="Asia/Kolkata")
    assert _naive_utc(c.start_date) == datetime(2026, 8, 24, 18, 29, 0)


def test_z_suffix_is_utc(db):
    c = new_contest(db, start_date="2026-08-24T06:15:00Z")
    assert _naive_utc(c.start_date) == datetime(2026, 8, 24, 6, 15, 0)


def test_naive_datetime_treated_as_utc(db):
    c = new_contest(db, start_date="2026-08-24T10:00:00")
    assert _naive_utc(c.start_date) == datetime(2026, 8, 24, 10, 0, 0)


def test_end_seconds_are_preserved(db):
    # The frontend sends the end at :59 seconds to include the final minute.
    c = new_contest(db, end_date="2026-12-31T23:59:59+00:00")
    assert _naive_utc(c.end_date) == datetime(2026, 12, 31, 23, 59, 59)


def test_negative_offset_converts_to_utc(db):
    # Jul 1 12:00 in New York (EDT, -04:00) -> 16:00 UTC.
    c = new_contest(db, start_date="2026-07-01T12:00:00-04:00",
                    timezone="America/New_York")
    assert _naive_utc(c.start_date) == datetime(2026, 7, 1, 16, 0, 0)


def test_bad_datetime_rejected(db):
    with pytest.raises(ValueError, match="ISO date or datetime"):
        new_contest(db, start_date="not-a-date")


# ---------------------------------------------------------------------------
# Timezone validation & alias handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tz", [
    "UTC",
    "Asia/Kolkata",
    "Asia/Calcutta",       # legacy alias of Asia/Kolkata
    "Asia/Kathmandu",      # +05:45
    "America/New_York",
    "US/Eastern",          # legacy alias
    "Europe/Berlin",
    "Etc/UTC",
])
def test_valid_timezones_accepted(db, tz):
    c = new_contest(db, timezone=tz)
    assert c.timezone == tz  # stored verbatim, not silently rewritten


@pytest.mark.parametrize("tz", ["Mars/Olympus", "Not/AZone", "XYZ", "GMT+5"])
def test_invalid_timezones_rejected(db, tz):
    with pytest.raises(ValueError, match="Unknown timezone"):
        new_contest(db, timezone=tz)


def test_blank_timezone_defaults_to_utc(db):
    c = new_contest(db, timezone="   ")
    assert c.timezone == "UTC"


def test_default_timezone_is_utc(db):
    c = new_contest(db)  # no timezone provided
    assert c.timezone == "UTC"


def test_alias_and_canonical_are_the_same_zone(db):
    # The heart of the Kolkata/Calcutta concern: the two names must resolve to
    # the identical offset, so the stored instant is the same regardless of which
    # spelling a client happens to use.
    kolkata = new_contest(db, username="A",
                          start_date="2026-08-24T23:59:00+05:30",
                          timezone="Asia/Kolkata")
    calcutta = new_contest(db, username="B",
                           start_date="2026-08-24T23:59:00+05:30",
                           timezone="Asia/Calcutta")
    assert _naive_utc(kolkata.start_date) == _naive_utc(calcutta.start_date)

    # And their zoneinfo offsets agree for that date.
    when = datetime(2026, 8, 24, 12)
    assert (when.replace(tzinfo=ZoneInfo("Asia/Kolkata")).utcoffset()
            == when.replace(tzinfo=ZoneInfo("Asia/Calcutta")).utcoffset())


# ---------------------------------------------------------------------------
# Serialization: stored instant -> API JSON
# ---------------------------------------------------------------------------

def test_to_dict_emits_explicit_utc_offset(db):
    c = new_contest(db, start_date="2026-08-24T23:59:00+05:30",
                    end_date="2026-12-31T23:59:59+00:00",
                    timezone="Asia/Kolkata")
    d = c.to_dict()
    # Must carry a UTC offset so a JS client never misreads it as local time.
    assert d["start_date"] == "2026-08-24T18:29:00+00:00"
    assert d["end_date"] == "2026-12-31T23:59:59+00:00"
    assert d["timezone"] == "Asia/Kolkata"


def test_to_dict_handles_missing_dates(db):
    c = new_contest(db, start_date="2026-01-01")  # end_date omitted
    d = c.to_dict()
    assert d["end_date"] is None
    assert d["start_date"].endswith("+00:00")


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------

def test_update_changes_timezone_and_dates(db):
    c = new_contest(db, timezone="UTC")
    update_contest(c, timezone="Europe/Berlin",
                   end_date="2027-01-01T00:00:00+01:00")
    assert c.timezone == "Europe/Berlin"
    # 2027-01-01 00:00 CET (+01:00) -> 2026-12-31 23:00 UTC.
    assert _naive_utc(c.end_date) == datetime(2026, 12, 31, 23, 0, 0)


def test_update_rejects_invalid_timezone(db):
    c = new_contest(db)
    with pytest.raises(ValueError, match="Unknown timezone"):
        update_contest(c, timezone="Nowhere/Land")


# ---------------------------------------------------------------------------
# Submission end-date guard
# ---------------------------------------------------------------------------

def _active(db, **fields):
    c = new_contest(db, **fields)
    start_contest(c)
    return c


def test_evaluate_blocked_after_end(db):
    # A past window (start 2020-01-01 default, end after it but still past).
    c = _active(db, end_date="2020-06-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="Contest has ended"):
        evaluate_article(c, ARTICLE)


def test_submit_blocked_after_end(db):
    # Open at evaluate time, then the window closes before submit.
    c = _active(db)
    user = make_user(db, "Editor")
    ev = evaluate_article(c, ARTICLE)
    c.end_date = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Contest has ended"):
        create_submission(user.id, c, ev["hash"])


def test_open_before_end(db):
    c = _active(db, end_date="2999-12-31T23:59:59+00:00")
    assert evaluate_article(c, ARTICLE)["hash"]


def test_no_end_date_never_closes(db):
    c = _active(db)  # end_date omitted
    assert evaluate_article(c, ARTICLE)["hash"]


def test_guard_handles_naive_end_datetime(db):
    # A naive end (as some DB backends return) is treated as UTC, not crashed on.
    c = _active(db)
    c.end_date = datetime(2000, 1, 1)  # naive, in the past
    with pytest.raises(ValueError, match="Contest has ended"):
        evaluate_article(c, ARTICLE)


def test_guard_boundary_is_inclusive_of_end_instant(db):
    # now > end closes it; a far-future end a second away stays open.
    c = _active(db)
    now = datetime.now(timezone.utc)
    c.end_date = now.replace(year=now.year + 1)
    assert evaluate_article(c, ARTICLE)["hash"]
