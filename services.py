"""
Service layer for Contest Creator Request workflow.
Contains business logic for creating, approving, and rejecting
requests for Contest Creator rights. Kept separate from routes
and models so each piece stays testable and focused.
"""

from datetime import datetime, timezone

from model import db, ContestRequest, User


# ------------------------------------------------------------------
# USER LOOKUP
# ------------------------------------------------------------------

def get_or_create_user(username):
    """
    Look up a User by MediaWiki username, creating one on first login.
    Session auth only tells us who's logged in (via MWOAuth); there's
    no separate registration step, so the user row is created lazily.
    """
    user = User.query.filter_by(username=username).first()
    if user:
        return user

    user = User(username=username)
    db.session.add(user)
    db.session.commit()

    return user


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