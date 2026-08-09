"""
Service layer for Contest Creator Request workflow.
Contains business logic for creating, approving, and rejecting
requests for Contest Creator rights. Kept separate from routes
and models so each piece stays testable and focused.
"""

from datetime import datetime, timezone

from model import db, Contest, ContestRequest, User


# ------------------------------------------------------------------
# CREATE REQUEST
# ------------------------------------------------------------------

def create_contest_request(user_id, reason, edit_count=None):
    """
    Create a new Contest Creator rights request.

    If edit_count >= 300, the request is auto-approved immediately
    (no superadmin review needed) and the user's role is upgraded.
    Otherwise, the request is created as 'pending' for manual review,
    and a reason is required.
    """
    user = User.query.get(user_id)
    if not user:
        raise ValueError("User not found")

    existing_pending = ContestRequest.query.filter_by(
        user_id=user_id, status="pending"
    ).first()
    if existing_pending:
        raise ValueError("User already has a pending request")

    is_auto_eligible = edit_count is not None and edit_count >= 300

    if not is_auto_eligible and (not reason or not reason.strip()):
        raise ValueError("Reason is required for users with fewer than 300 edits")

    if is_auto_eligible:
        status = "approved"
        user.role = "trusted_member"
    else:
        status = "pending"

    new_request = ContestRequest(
        user_id=user_id,
        reason=reason.strip() if reason else None,
        edit_count=edit_count,
        status=status,
    )

    db.session.add(new_request)
    db.session.commit()

    return new_request

# ------------------------------------------------------------------
# APPROVE REQUEST
# ------------------------------------------------------------------

def approve_contest_request(request_id, reviewer_id):
    """
    Approve a pending Contest Creator rights request.
    """
    contest_request = ContestRequest.query.get(request_id)
    if not contest_request:
        raise ValueError("Request not found")

    if contest_request.status != "pending":
        raise ValueError(f"Request has already been {contest_request.status}")

    requester = User.query.get(contest_request.user_id)
    if not requester:
        raise ValueError("Requesting user not found")

    requester.role = "trusted_member"

    contest_request.status = "approved"
    contest_request.reviewed_by = reviewer_id
    contest_request.reviewed_at = datetime.now(timezone.utc)

    db.session.commit()

    return contest_request


# ------------------------------------------------------------------
# REJECT REQUEST
# ------------------------------------------------------------------

def reject_contest_request(request_id, reviewer_id, rejection_reason=None):
    """
    Reject a pending Contest Creator rights request.
    """
    contest_request = ContestRequest.query.get(request_id)
    if not contest_request:
        raise ValueError("Request not found")

    if contest_request.status != "pending":
        raise ValueError(f"Request has already been {contest_request.status}")

    contest_request.status = "rejected"
    contest_request.reviewed_by = reviewer_id
    contest_request.reviewed_at = datetime.now(timezone.utc)
    contest_request.rejection_reason = rejection_reason

    db.session.commit()

    return contest_request


# ------------------------------------------------------------------
# CONTEST CRUD (core fields only)
# ------------------------------------------------------------------

def _parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def can_create_contests(user):
    return user.role in ("trusted_member", "admin", "superadmin")


def can_manage_contest(user, contest):
    """True if the user may update/delete this contest (admin or organizer)."""
    return user.role in ("admin", "superadmin") or user.username in contest.get_organizers()


def create_contest(creator, data):
    name = (data.get("name") or "").strip()
    project_name = (data.get("project_name") or "").strip()
    if not name or not project_name:
        raise ValueError("name and project_name are required")

    if data.get("min_byte_count") is None:
        raise ValueError("min_byte_count is required")

    start_date = _parse_date(data.get("start_date"))
    end_date = _parse_date(data.get("end_date"))
    if start_date and end_date and start_date >= end_date:
        raise ValueError("end_date must be after start_date")

    contest = Contest(
        name=name,
        project_name=project_name,
        creator=creator,
        description=data.get("description"),
        start_date=start_date,
        end_date=end_date,
        min_byte_count=int(data["min_byte_count"]),
        min_reference_count=int(data.get("min_reference_count") or 0),
        template_link=data.get("template_link"),
    )
    contest.set_rules(data.get("rules", {}))
    contest.set_categories(data.get("categories", []))
    contest.set_scoring_parameters(data.get("scoring_parameters"))
    contest.set_jury_members(data.get("jury_members", []))
    contest.set_organizers(data.get("organizers", []))

    db.session.add(contest)
    db.session.commit()

    return contest


def update_contest(contest, data):
    for field in ("name", "project_name"):
        if field in data:
            setattr(contest, field, (data[field] or "").strip())

    for field in ("description", "template_link"):
        if field in data:
            setattr(contest, field, data[field])

    for field in ("min_byte_count", "min_reference_count"):
        if field in data:
            setattr(contest, field, int(data[field]))

    if "start_date" in data:
        contest.start_date = _parse_date(data["start_date"])
    if "end_date" in data:
        contest.end_date = _parse_date(data["end_date"])
    if contest.start_date and contest.end_date and contest.start_date >= contest.end_date:
        raise ValueError("end_date must be after start_date")

    if "rules" in data:
        contest.set_rules(data["rules"])
    if "categories" in data:
        contest.set_categories(data["categories"])
    if "scoring_parameters" in data:
        contest.set_scoring_parameters(data["scoring_parameters"])
    if "jury_members" in data:
        contest.set_jury_members(data["jury_members"])
    if "organizers" in data:
        contest.set_organizers(data["organizers"])

    db.session.commit()

    return contest


def delete_contest(contest):
    db.session.delete(contest)
    db.session.commit()