"""
Service layer for Contest Creator Request workflow.
Contains business logic for creating, approving, and rejecting
requests for Contest Creator rights. Kept separate from routes
and models so each piece stays testable and focused.
"""

from datetime import datetime, timezone

from model import db, ContestRequest, User


# ------------------------------------------------------------------
# CREATE REQUEST
# ------------------------------------------------------------------

def create_contest_request(user_id, reason, edit_count=None):
    """
    Create a new Contest Creator rights request.
    """
    user = User.query.get(user_id)
    if not user:
        raise ValueError("User not found")

    existing_pending = ContestRequest.query.filter_by(
        user_id=user_id, status="pending"
    ).first()
    if existing_pending:
        raise ValueError("User already has a pending request")

    if not reason or not reason.strip():
        raise ValueError("Reason is required")

    new_request = ContestRequest(
        user_id=user_id,
        reason=reason.strip(),
        edit_count=edit_count,
        status="pending",
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