from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, or_

from model import Contest, ContestStatus, Submission, SubmissionStatus, User, db
from services.user import ensure_users


class ContestLocked(Exception):
    """Raised when editing/starting a contest that is no longer 'pending'."""


_SETTABLE_FIELDS = (
    "description", "start_date", "end_date", "timezone", "rules",
    "marks_setting_accepted", "marks_setting_rejected",
    "scoring_parameters", "automated_settings",
    "jury_members", "organizers", "project_link",
)
_DATE_FIELDS = ("start_date", "end_date")


def _coerce_dates(fields):
    """Normalize incoming contest fields:

    - start_date/end_date: parse an ISO datetime (or bare date) into a
      timezone-aware UTC datetime. The client converts the organizer's local
      wall-clock time to a UTC instant, so we just anchor and store it.
    - timezone: validate it's a real IANA zone; blank falls back to 'UTC'.
    """
    out = dict(fields)
    for key in _DATE_FIELDS:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = _parse_utc(key, value)

    tz = out.get("timezone")
    if isinstance(tz, str):
        out["timezone"] = tz.strip() or "UTC"
        _validate_timezone(out["timezone"])
    return out


def _parse_utc(key, value):
    """Parse an ISO datetime (or bare YYYY-MM-DD) as a UTC-aware datetime."""
    text = value.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            raise ValueError(f"{key} must be an ISO date or datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_timezone(name):
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown timezone: {name}")


def _validate_marks(fields):
    accepted = fields.get("marks_setting_accepted")
    if accepted is not None and (not isinstance(accepted, (int, float)) or accepted <= 0):
        raise ValueError("marks_setting_accepted must be a positive number")

    rejected = fields.get("marks_setting_rejected")
    if rejected is not None and (not isinstance(rejected, (int, float)) or rejected > 0):
        raise ValueError("marks_setting_rejected must be zero or negative")


def list_contests(include_all=False, viewer_id=None):
    query = Contest.query
    if not include_all:
        visible = [Contest.status == ContestStatus.ACTIVE.value]
        if viewer_id is not None:
            visible.append(Contest.created_by == viewer_id)
        query = query.filter(or_(*visible))
    return query.order_by(
        Contest.created_at.desc(), Contest.id.desc()
    ).all()


def get_contest(contest_id):
    return db.session.get(Contest, contest_id)


def get_leaderboard(contest):
    reviewed_count = func.sum(
        case((Submission.reviewed_at.isnot(None), 1), else_=0)
    )
    pending_count = func.sum(
        case((Submission.status == SubmissionStatus.PENDING.value, 1), else_=0)
    )
    rows = (
        db.session.query(
            Submission.user_id,
            User.username,
            func.count(Submission.id),
            func.coalesce(func.sum(Submission.score), 0),
            reviewed_count,
            pending_count,
        )
        .join(User, User.id == Submission.user_id)
        .filter(Submission.contest_id == contest.id)
        .group_by(Submission.user_id, User.username)
        .order_by(func.lower(User.username))
        .all()
    )
    return [
        {
            "user_id": user_id,
            "username": username,
            "total_submissions": int(total),
            "total_marks": int(marks),
            "reviewed_count": int(reviewed),
            "pending_count": int(pending),
        }
        for user_id, username, total, marks, reviewed, pending in rows
    ]


def create_contest(user_id, name, project_name, **fields):
    if not name or not name.strip():
        raise ValueError("Contest name is required")
    if not project_name or not project_name.strip():
        raise ValueError("Project name is required")

    fields = _coerce_dates(fields)
    if not fields.get("start_date"):
        raise ValueError("Start date is required")
    if fields.get("marks_setting_accepted") is None:
        raise ValueError("marks_setting_accepted is required")
    _validate_marks(fields)

    contest = Contest(
        name=name.strip(),
        project_name=project_name.strip(),
        created_by=user_id,
        status=ContestStatus.PENDING.value,
    )
    for key in _SETTABLE_FIELDS:
        if fields.get(key) is not None:
            setattr(contest, key, fields[key])

    # The creator is always an organizer; keep any provided ones too.
    creator = db.session.get(User, user_id)
    contest.organizers = _with_creator(fields.get("organizers"), creator)

    db.session.add(contest)
    db.session.commit()

    # Ensure organizers and jury exist as User rows (even pre-login).
    ensure_users((contest.organizers or []) + (contest.jury_members or []))
    return contest


def _with_creator(organizers, creator):
    result = list(organizers or [])
    if creator and creator.username not in result:
        result.insert(0, creator.username)
    return result


# Fields that stay editable after a contest has started (its config is locked).
# end_date is included so a running contest can be extended (or closed early);
# the contest's timezone is not, so the deadline instant stays interpreted in the
# zone it was created with.
_EDITABLE_WHEN_LOCKED = {"organizers", "jury_members", "end_date"}


def update_contest(contest, **fields):
    if contest.status != ContestStatus.PENDING.value and set(fields) - _EDITABLE_WHEN_LOCKED:
        raise ContestLocked(
            "Contest is locked; only organizers, jury members and the end date "
            "can be edited"
        )

    fields = _coerce_dates(fields)

    if "name" in fields:
        if not fields["name"] or not str(fields["name"]).strip():
            raise ValueError("Contest name cannot be empty")
        contest.name = fields["name"].strip()
    if "project_name" in fields:
        if not fields["project_name"] or not str(fields["project_name"]).strip():
            raise ValueError("Project name cannot be empty")
        contest.project_name = fields["project_name"].strip()
    if "start_date" in fields and not fields["start_date"]:
        raise ValueError("Start date is required")
    _validate_marks(fields)

    for key in _SETTABLE_FIELDS:
        if key in fields:
            setattr(contest, key, fields[key])

    # The creator can't be removed from organizers on edit.
    if "organizers" in fields:
        contest.organizers = _with_creator(contest.organizers, contest.creator)

    db.session.commit()

    # New organizers/jury may need User rows too.
    if "organizers" in fields or "jury_members" in fields:
        ensure_users((contest.organizers or []) + (contest.jury_members or []))
    return contest


def start_contest(contest):
    if contest.status != ContestStatus.PENDING.value:
        raise ContestLocked("Contest has already been started")

    contest.status = ContestStatus.ACTIVE.value
    db.session.commit()
    return contest
