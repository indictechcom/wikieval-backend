from flask import Blueprint, jsonify, request

from services.child_campaign_request import (
    approve_child_campaign_request,
    create_child_campaign_request,
    get_child_campaign_request,
    list_child_campaign_requests,
    reject_child_campaign_request,
)
from services.contest import get_contest
from utils.auth import current_user, is_superadmin

bp = Blueprint('child_campaign_request', __name__)


def _reviews(user, parent):
    """Who reviews requests for a group: its organizers (and superadmins)."""
    return is_superadmin(user.username) or parent.is_organizer(user.username)


def _load_group(contest_id):
    """(parent, error_response). The parent must exist and be a group."""
    parent = get_contest(contest_id)
    if parent is None:
        return None, (jsonify({"error": "Contest not found"}), 404)
    if not parent.is_group:
        return None, (jsonify({"error": "Not a group campaign"}), 400)
    return parent, None


@bp.route('/api/contests/<int:contest_id>/child-requests', methods=['GET'])
def list_requests(contest_id):
    """A group's child-campaign requests. The group's organizers see them all
    (with `can_review: true`); any other logged-in user sees only their own."""
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    parent, err = _load_group(contest_id)
    if err:
        return err

    can_review = _reviews(user, parent)
    rows = list_child_campaign_requests(parent, user_id=None if can_review else user.id)
    return jsonify({
        "requests": [r.to_dict() for r in rows],
        "can_review": can_review,
    }), 200


@bp.route('/api/contests/<int:contest_id>/child-requests', methods=['POST'])
def submit(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    parent, err = _load_group(contest_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        child_request = create_child_campaign_request(
            parent, user.id, data.get('name'),
            organizers=data.get('organizers'),
            jury_members=data.get('jury_members'),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(child_request.to_dict()), 201


@bp.route('/api/contests/<int:contest_id>/child-requests/<int:request_id>/review',
          methods=['POST'])
def review(contest_id, request_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    parent, err = _load_group(contest_id)
    if err:
        return err
    if not _reviews(user, parent):
        return jsonify({"error": "Only an organizer of this group campaign "
                                 "can review its requests"}), 403

    child_request = get_child_campaign_request(request_id)
    if child_request is None or child_request.parent_id != parent.id:
        return jsonify({"error": "Request not found"}), 404

    data = request.get_json(silent=True) or {}
    decision = data.get('decision')
    try:
        if decision == 'approve':
            child_request = approve_child_campaign_request(
                child_request, user.id,
                organizers=data.get('organizers'),
                jury_members=data.get('jury_members'),
            )
        elif decision == 'reject':
            child_request = reject_child_campaign_request(
                child_request, user.id, data.get('rejection_reason'))
        else:
            return jsonify({"error": "decision must be 'approve' or 'reject'"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(child_request.to_dict()), 200
