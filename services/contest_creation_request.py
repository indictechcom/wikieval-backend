from datetime import datetime, timezone

from model import ContestCreationRequest, RequestStatus, User, db


def get_latest_contest_creation_request(user_id):
    return (
        ContestCreationRequest.query
        .filter_by(user_id=user_id)
        .order_by(
            ContestCreationRequest.created_at.desc(),
            ContestCreationRequest.id.desc(),
        )
        .first()
    )


def list_contest_creation_requests():
    return ContestCreationRequest.query.order_by(
        ContestCreationRequest.created_at.desc(),
        ContestCreationRequest.id.desc(),
    ).all()


def create_contest_creation_request(user_id, reason):
    user = db.session.get(User, user_id)
    if user is None:
        raise ValueError("User not found")

    if user.can_create_contest:
        raise ValueError("You already have contest-creation rights")

    if not reason or not reason.strip():
        raise ValueError("A reason is required")

    existing = ContestCreationRequest.query.filter_by(
        user_id=user_id, status=RequestStatus.PENDING.value
    ).first()
    if existing is not None:
        raise ValueError("You already have a pending request")

    contest_request = ContestCreationRequest(
        user_id=user_id,
        reason=reason.strip(),
        status=RequestStatus.PENDING.value,
    )
    db.session.add(contest_request)
    db.session.commit()
    return contest_request


def approve_contest_creation_request(request_id, reviewer_id):
    contest_request = _get_pending_request(request_id)

    contest_request.status = RequestStatus.APPROVED.value
    contest_request.reviewed_by = reviewer_id
    contest_request.reviewed_at = datetime.now(timezone.utc)
    contest_request.rejection_reason = None

    # The actual grant.
    contest_request.requester.can_create_contest = True

    db.session.commit()
    return contest_request


def reject_contest_creation_request(request_id, reviewer_id, rejection_reason):
    if not rejection_reason or not rejection_reason.strip():
        raise ValueError("A rejection reason is required")

    contest_request = _get_pending_request(request_id)

    contest_request.status = RequestStatus.REJECTED.value
    contest_request.reviewed_by = reviewer_id
    contest_request.reviewed_at = datetime.now(timezone.utc)
    contest_request.rejection_reason = rejection_reason.strip()

    db.session.commit()
    return contest_request


def _get_pending_request(request_id):
    contest_request = db.session.get(ContestCreationRequest, request_id)
    if contest_request is None:
        raise ValueError("Request not found")
    if contest_request.status != RequestStatus.PENDING.value:
        raise ValueError("Request has already been reviewed")
    return contest_request
