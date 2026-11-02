from flask import Blueprint, jsonify, request

from services.contest import (
    ContestLocked,
    create_contest,
    get_contest,
    get_leaderboard,
    list_children,
    list_contests,
    start_contest,
    update_contest,
)
from services.audit import log_hierarchy
from services.eligibility import catalog as eligibility_catalog
from utils.auth import current_user, is_superadmin, may_create_contest

bp = Blueprint('contest', __name__)


@bp.route('/api/eligibility-rules', methods=['GET'])
def eligibility_rules_catalog():
    """The catalog of eligibility rules a creator can add (drives the form)."""
    return jsonify({"rules": eligibility_catalog()}), 200

# Fields accepted from the client on create/update.
_BODY_FIELDS = (
    "name", "project_name", "description", "start_date", "end_date", "timezone",
    "eligibility_rules",
    "marks_setting_accepted", "marks_setting_rejected", "scoring_parameters",
    "reviews_required",
    "jury_members", "organizers",
    "project_link",
    "is_group", "parent_id",
)


def _body_fields():
    data = request.get_json(silent=True) or {}
    return {k: data[k] for k in _BODY_FIELDS if k in data}


def _manages(user, contest):
    return is_superadmin(user.username) or contest.is_organizer(user.username)


def _parent_forbidden(user, parent_id):
    """Attaching a child under a group campaign needs that group's organizer
    (or a superadmin). Returns an error message, or None when allowed. A
    missing/non-group parent is left for the service to report as 400."""
    if parent_id is None:
        return None
    parent = get_contest(parent_id)
    if parent is not None and parent.is_group and not _manages(user, parent):
        return "Only an organizer of the parent campaign can add campaigns to it"
    return None


@bp.route('/api/contests/<int:contest_id>/children', methods=['GET'])
def children(contest_id):
    """A group campaign's child campaigns with per-child aggregates. Public
    (like GET /api/contests/<id>); draft children are hidden from outsiders."""
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    if not contest.is_group:
        return jsonify({"error": "Not a group campaign"}), 400
    user = current_user()
    rows = list_children(contest, viewer=user,
                         is_superadmin=user is not None and is_superadmin(user.username))
    return jsonify({"children": rows}), 200


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

    fields = _body_fields()
    name = fields.pop("name", None)
    project_name = fields.pop("project_name", None)
    parent_id = fields.get("parent_id")
    forbidden = _parent_forbidden(user, parent_id)
    if forbidden:
        return jsonify({"error": forbidden}), 403
    # Organizers of a group campaign may create its children without holding
    # the global contest-creation right (they already manage the group).
    parent = get_contest(parent_id) if parent_id is not None else None
    manages_parent = parent is not None and parent.is_group and _manages(user, parent)
    if not (may_create_contest(user) or manages_parent):
        return jsonify({"error": "You do not have contest-creation rights"}), 403
    try:
        contest = create_contest(user.id, name, project_name, **fields)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if contest.parent_id is not None:
        log_hierarchy(contest, user.id, "create-child", parent_id=contest.parent_id)
    return jsonify(contest.to_dict()), 201


@bp.route('/api/contests/<int:contest_id>', methods=['PUT'])
def update(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    fields = _body_fields()
    fields.pop("is_group", None)   # fixed at creation
    # is_organizer() includes the parent group's organizers for a child.
    if not contest.is_organizer(user.username):
        return jsonify({"error": "Only a contest organizer can edit it"}), 403
    previous_parent_id = contest.parent_id
    if "parent_id" in fields:
        # Attaching needs the target group's organizer; detaching needs the
        # current group's organizer (a child can't quietly leave a group).
        forbidden = _parent_forbidden(user, fields["parent_id"])
        if forbidden:
            return jsonify({"error": forbidden}), 403
        if (fields["parent_id"] is None and contest.parent is not None
                and not _manages(user, contest.parent)):
            return jsonify({"error": "Only an organizer of the parent campaign "
                                     "can detach a campaign from it"}), 403

    try:
        contest = update_contest(contest, **fields)
    except ContestLocked as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if "parent_id" in fields and contest.parent_id != previous_parent_id:
        log_hierarchy(contest, user.id,
                      "attach" if contest.parent_id is not None else "detach",
                      parent_id=contest.parent_id, previous_parent_id=previous_parent_id)
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
