"""Child-campaign requests: a local organizer asks, from a group campaign's
page, for a child campaign under it. The group's organizers review the
request; approving creates the child with the group's defaults and grants the
requester contest-creation rights."""

from datetime import datetime, timezone

from model import ChildCampaignRequest, RequestStatus, User, db
from services.audit import log_hierarchy
from services.contest import create_contest
from services.user import ensure_users


def list_child_campaign_requests(parent, user_id=None):
    """Requests for a group campaign, newest first. With `user_id`, only that
    user's own requests (what a requester may see)."""
    query = ChildCampaignRequest.query.filter_by(parent_id=parent.id)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    return query.order_by(
        ChildCampaignRequest.created_at.desc(),
        ChildCampaignRequest.id.desc(),
    ).all()


def get_child_campaign_request(request_id):
    return db.session.get(ChildCampaignRequest, request_id)


def _clean_usernames(values, label):
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{label} must be a list of usernames")
    out = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a list of usernames")
        name = value.strip()
        if name and name not in out:
            out.append(name)
    return out


def create_child_campaign_request(parent, user_id, name, organizers=None,
                                  jury_members=None):
    if parent is None or not parent.is_group:
        raise ValueError("Child campaigns can only be requested under a group campaign")
    user = db.session.get(User, user_id)
    if user is None:
        raise ValueError("User not found")
    if not name or not str(name).strip():
        raise ValueError("Child campaign name is required")
    name = str(name).strip()
    if len(name) > 200:
        raise ValueError("Child campaign name must be at most 200 characters")

    organizers = _clean_usernames(organizers, "organizers")
    if not organizers:
        raise ValueError("At least one local organizer is required")
    jury_members = _clean_usernames(jury_members, "jury_members")

    lowered = name.lower()
    if any((c.name or "").strip().lower() == lowered for c in parent.children):
        raise ValueError("A child campaign with this name already exists")
    for pending in ChildCampaignRequest.query.filter_by(
            parent_id=parent.id, status=RequestStatus.PENDING.value).all():
        if pending.name.strip().lower() == lowered:
            raise ValueError("A pending request with this name already exists")

    child_request = ChildCampaignRequest(
        parent_id=parent.id,
        user_id=user_id,
        name=name,
        organizers=organizers,
        jury_members=jury_members,
        status=RequestStatus.PENDING.value,
    )
    db.session.add(child_request)
    db.session.commit()
    return child_request


def approve_child_campaign_request(child_request, reviewer_id, organizers=None,
                                   jury_members=None):
    """Approve: create the child campaign under the group with the group's
    defaults (project, dates, timezone, eligibility rules, scoring) and the
    request's name/organizers/jury — the reviewer may pass edited organizers or
    jury. The requester becomes the child's creator (and so an organizer of
    it) and is granted contest-creation rights. The child starts as a draft so
    its local organizers can adjust it before starting it."""
    child_request = _require_pending(child_request)
    parent = child_request.parent

    if organizers is not None:
        organizers = _clean_usernames(organizers, "organizers")
        if not organizers:
            raise ValueError("At least one local organizer is required")
        child_request.organizers = organizers
    if jury_members is not None:
        child_request.jury_members = _clean_usernames(jury_members, "jury_members")

    jury = list(child_request.jury_members or []) or list(parent.jury_members or [])
    contest = create_contest(
        child_request.user_id, child_request.name, parent.project_name,
        parent_id=parent.id,
        start_date=parent.start_date,
        end_date=parent.end_date,
        timezone=parent.timezone,
        eligibility_rules=parent.eligibility_rules,
        marks_setting_accepted=parent.marks_setting_accepted,
        marks_setting_rejected=parent.marks_setting_rejected,
        scoring_parameters=parent.scoring_parameters,
        reviews_required=parent.reviews_required,
        organizers=list(child_request.organizers or []),
        jury_members=jury,
    )

    child_request.status = RequestStatus.APPROVED.value
    child_request.reviewed_by = reviewer_id
    child_request.reviewed_at = datetime.now(timezone.utc)
    child_request.rejection_reason = None
    child_request.contest_id = contest.id
    # The actual grant of contest-creation rights.
    child_request.requester.can_create_contest = True
    db.session.commit()

    ensure_users(child_request.organizers or [])
    log_hierarchy(contest, reviewer_id, "create-child", parent_id=parent.id)
    return child_request


def reject_child_campaign_request(child_request, reviewer_id, rejection_reason):
    if not rejection_reason or not rejection_reason.strip():
        raise ValueError("A rejection reason is required")
    child_request = _require_pending(child_request)

    child_request.status = RequestStatus.REJECTED.value
    child_request.reviewed_by = reviewer_id
    child_request.reviewed_at = datetime.now(timezone.utc)
    child_request.rejection_reason = rejection_reason.strip()
    db.session.commit()
    return child_request


def _require_pending(child_request):
    if child_request is None:
        raise ValueError("Request not found")
    if child_request.status != RequestStatus.PENDING.value:
        raise ValueError("Request has already been reviewed")
    return child_request
