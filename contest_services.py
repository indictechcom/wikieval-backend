"""
Service layer for Contest management.
Contains business logic for creating, listing, updating, and
deleting contests. Kept separate from routes so it stays testable.
"""

from datetime import date, datetime, timezone

from model import db, Contest, User



# CREATE


def create_contest(user_id, name, project_name, **kwargs):
    """
    Create a new contest. Only trusted_members and superadmins may create
    contests (Contest Creator rights, granted via the ContestRequest flow).
    """
    user = db.session.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    if user.role not in ("trusted_member", "superadmin"):
        raise ValueError("Only trusted members or superadmins can create contests")

    if not name or not name.strip():
        raise ValueError("Contest name is required")
    if not project_name or not project_name.strip():
        raise ValueError("Project name is required")

    start_date = kwargs.get("start_date")
    end_date = kwargs.get("end_date")
    if start_date and end_date and start_date >= end_date:
        raise ValueError("End date must be after start date")

    contest = Contest(
        name=name.strip(),
        project_name=project_name.strip(),
        created_by=user_id,
        description=kwargs.get("description"),
        start_date=start_date,
        end_date=end_date,
        min_byte_count=kwargs.get("min_byte_count", 0),
        min_reference_count=kwargs.get("min_reference_count", 0),
        allowed_submission_type=kwargs.get("allowed_submission_type", "both"),
        marks_setting_accepted=kwargs.get("marks_setting_accepted", 0),
        marks_setting_rejected=kwargs.get("marks_setting_rejected", 0),
        scoring_parameters=kwargs.get("scoring_parameters"),
        categories=kwargs.get("categories"),
        organizer_ids=kwargs.get("organizer_ids"),
        jury_ids=kwargs.get("jury_ids"),
        template_link=kwargs.get("template_link"),
        outreach_dashboard_url=kwargs.get("outreach_dashboard_url"),
    )

    db.session.add(contest)
    db.session.commit()

    return contest


# READ

def get_contest(contest_id):
    contest = db.session.get(Contest, contest_id)
    if not contest:
        raise ValueError("Contest not found")
    return contest


def list_contests():
    """
    Return all contests grouped by status: current, upcoming, past.
    """
    today = date.today()
    contests = Contest.query.order_by(Contest.created_at.desc()).all()

    current, upcoming, past = [], [], []

    for c in contests:
        if c.start_date and c.end_date and c.start_date <= today <= c.end_date:
            current.append(c)
        elif c.start_date and c.start_date > today:
            upcoming.append(c)
        elif c.end_date and c.end_date < today:
            past.append(c)
        else:
            current.append(c)

    return {"current": current, "upcoming": upcoming, "past": past}


# UPDATE

def update_contest(contest_id, user_id, **kwargs):
    """
    Update a contest. Only the creator, an organizer, or a superadmin may edit.
    """
    contest = db.session.get(Contest, contest_id)
    if not contest:
        raise ValueError("Contest not found")

    user = db.session.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    is_creator = contest.created_by == user_id
    is_organizer = contest.organizer_ids and user_id in contest.organizer_ids
    is_superadmin = user.role == "superadmin"

    if not (is_creator or is_organizer or is_superadmin):
        raise ValueError("You do not have permission to edit this contest")

    for field in (
        "name", "project_name", "description", "start_date", "end_date",
        "min_byte_count", "min_reference_count", "allowed_submission_type",
        "marks_setting_accepted", "marks_setting_rejected",
        "scoring_parameters", "categories", "organizer_ids", "jury_ids",
        "template_link", "outreach_dashboard_url",
    ):
        if field in kwargs:
            setattr(contest, field, kwargs[field])

    if contest.start_date and contest.end_date and contest.start_date >= contest.end_date:
        raise ValueError("End date must be after start date")

    db.session.commit()
    return contest


# DELETE

def delete_contest(contest_id, user_id):
    contest = db.session.get(Contest, contest_id)
    if not contest:
        raise ValueError("Contest not found")

    user = db.session.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    is_creator = contest.created_by == user_id
    is_superadmin = user.role == "superadmin"

    if not (is_creator or is_superadmin):
        raise ValueError("Only the creator or a superadmin can delete this contest")

    db.session.delete(contest)
    db.session.commit()