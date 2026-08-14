from datetime import date

from sqlalchemy import case, func, or_

from model import Contest, ContestStatus, Submission, SubmissionStatus, User, db
from services.user import ensure_users


class ContestLocked(Exception):
    """Raised when editing/starting a contest that is no longer 'pending'."""


_SETTABLE_FIELDS = (
    "description", "start_date", "end_date", "rules",
    "marks_setting_accepted", "marks_setting_rejected",
    "scoring_parameters", "automated_settings",
    "jury_members", "organizers", "outreach_dashboard_url",
)
_DATE_FIELDS = ("start_date", "end_date")


def _coerce_dates(fields):
    """Parse ISO date strings (YYYY-MM-DD) into date objects."""
    out = dict(fields)
    for key in _DATE_FIELDS:
        value = out.get(key)
        if isinstance(value, str):
            try:
                out[key] = date.fromisoformat(value)
            except ValueError:
                raise ValueError(f"{key} must be an ISO date (YYYY-MM-DD)")
    return out


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
_EDITABLE_WHEN_LOCKED = {"organizers", "jury_members"}


def update_contest(contest, **fields):
    if contest.status != ContestStatus.PENDING.value and set(fields) - _EDITABLE_WHEN_LOCKED:
        raise ContestLocked(
            "Contest is locked; only organizers and jury members can be edited"
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
