from flask import Blueprint, jsonify, request

from services.contest import (
    ContestLocked,
    create_contest,
    get_contest,
    get_leaderboard,
    list_contests,
    start_contest,
    update_contest,
)
from utils.auth import current_user, is_superadmin, may_create_contest

bp = Blueprint('contest', __name__)

# Fields accepted from the client on create/update.
_BODY_FIELDS = (
    "name", "project_name", "description", "start_date", "end_date", "rules",
    "marks_setting_accepted", "marks_setting_rejected", "scoring_parameters",
    "automated_settings", "jury_members", "organizers",
    "outreach_dashboard_url",
)


def _body_fields():
    data = request.get_json(silent=True) or {}
    return {k: data[k] for k in _BODY_FIELDS if k in data}


@bp.route('/api/contests', methods=['GET'])
def list_all():
    user = current_user()
    include_all = user is not None and is_superadmin(user.username)
    viewer_id = user.id if user is not None else None
    contests = list_contests(include_all=include_all, viewer_id=viewer_id)
    return jsonify({"contests": [c.to_dict() for c in contests]}), 200


@bp.route('/api/contests/<int:contest_id>', methods=['GET'])
def get_one(contest_id):
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    return jsonify(contest.to_dict()), 200


@bp.route('/api/contests/<int:contest_id>/leaderboard', methods=['GET'])
def leaderboard(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    return jsonify({"leaderboard": get_leaderboard(contest)}), 200


@bp.route('/api/contests', methods=['POST'])
def create():
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    if not may_create_contest(user):
        return jsonify({"error": "You do not have contest-creation rights"}), 403

    fields = _body_fields()
    name = fields.pop("name", None)
    project_name = fields.pop("project_name", None)
    try:
        contest = create_contest(user.id, name, project_name, **fields)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest.to_dict()), 201


@bp.route('/api/contests/<int:contest_id>', methods=['PUT'])
def update(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    if not contest.is_organizer(user.username):
        return jsonify({"error": "Only a contest organizer can edit it"}), 403

    try:
        contest = update_contest(contest, **_body_fields())
    except ContestLocked as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest.to_dict()), 200


@bp.route('/api/contests/<int:contest_id>/start', methods=['POST'])
def start(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    if not contest.is_organizer(user.username):
        return jsonify({"error": "Only a contest organizer can start it"}), 403

    try:
        contest = start_contest(contest)
    except ContestLocked as e:
        return jsonify({"error": str(e)}), 409

    return jsonify(contest.to_dict()), 200
