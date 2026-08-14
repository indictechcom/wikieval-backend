from flask import Blueprint, jsonify, request

from services.contest_creation_request import (
    approve_contest_creation_request,
    create_contest_creation_request,
    get_latest_contest_creation_request,
    list_contest_creation_requests,
    reject_contest_creation_request,
)
from utils.auth import current_user, is_superadmin, may_create_contest

bp = Blueprint('contest_creation_request', __name__)


@bp.route('/api/contest-creation-requests', methods=['GET'])
def list_requests():
    reviewer = current_user()
    if reviewer is None:
        return jsonify({"error": "Login required"}), 401
    if not is_superadmin(reviewer.username):
        return jsonify({"error": "Superadmin rights required"}), 403

    requests = list_contest_creation_requests()
    return jsonify({"requests": [r.to_dict() for r in requests]}), 200


@bp.route('/api/contest-creation-request', methods=['GET'])
def my_request():
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    contest_request = get_latest_contest_creation_request(user.id)
    return jsonify({
        "can_create_contest": may_create_contest(user),
        "request": contest_request.to_dict() if contest_request else None,
    }), 200


@bp.route('/api/contest-creation-request', methods=['POST'])
def submit():
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    reason = data.get('reason')

    try:
        contest_request = create_contest_creation_request(user.id, reason)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest_request.to_dict()), 201


@bp.route('/api/contest-creation-request/<int:request_id>/review', methods=['POST'])
def review(request_id):
    reviewer = current_user()
    if reviewer is None:
        return jsonify({"error": "Login required"}), 401
    if not is_superadmin(reviewer.username):
        return jsonify({"error": "Superadmin rights required"}), 403

    data = request.get_json(silent=True) or {}
    decision = data.get('decision')

    try:
        if decision == 'approve':
            contest_request = approve_contest_creation_request(request_id, reviewer.id)
        elif decision == 'reject':
            contest_request = reject_contest_creation_request(
                request_id, reviewer.id, data.get('rejection_reason')
            )
        else:
            return jsonify({"error": "decision must be 'approve' or 'reject'"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest_request.to_dict()), 200
