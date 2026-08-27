from flask import Blueprint, jsonify, request

from services.contest import get_contest
from services.submission import (
    create_submission,
    evaluate_article,
    get_submission,
    import_submission,
    list_contest_submissions,
    review_submission,
)
from utils.auth import current_user, is_superadmin

bp = Blueprint('submission', __name__)


def _is_jury(user, contest):
    return user.username in (contest.jury_members or [])


def _can_see_all(user, contest):
    return (
        is_superadmin(user.username)
        or contest.is_organizer(user.username)
        or _is_jury(user, contest)
    )


@bp.route('/api/contests/<int:contest_id>/submissions/evaluate', methods=['POST'])
def evaluate(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        result = evaluate_article(contest, data.get('article_link'),
                                  submitter=user.username)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Echo the contest's eligibility rules so the UI can show the article's stats
    # against the requirements without a separate contest fetch.
    result["eligibility_rules"] = contest.eligibility_rules
    return jsonify(result), 200


@bp.route('/api/contests/<int:contest_id>/submissions', methods=['POST'])
def create(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        submission = create_submission(user.id, contest, data.get('hash'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(submission.to_dict()), 201


@bp.route('/api/contests/<int:contest_id>/submissions/import', methods=['POST'])
def import_one(contest_id):
    """Superadmin-only: restore one submission from an exported CSV row. The
    client sends rows one at a time (with progress), so each request re-fetches
    a single article's metadata without risking a bulk timeout."""
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    if not is_superadmin(user.username):
        return jsonify({"error": "Superadmin rights required"}), 403
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        submission = import_submission(
            contest, data.get('username'), data.get('article_link'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(submission.to_dict()), 201


@bp.route('/api/contests/<int:contest_id>/submissions', methods=['GET'])
def list_for_contest(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    contest = get_contest(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404

    submissions = list_contest_submissions(
        contest_id, viewer_id=user.id, all_submissions=_can_see_all(user, contest)
    )
    # Include the contest's eligibility rules so jury/organizers can see each
    # submission's stats against the requirements.
    return jsonify({
        "eligibility_rules": contest.eligibility_rules,
        "submissions": [s.to_dict() for s in submissions],
    }), 200


@bp.route('/api/submissions/<int:submission_id>/review', methods=['POST'])
def review(submission_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    submission = get_submission(submission_id)
    if submission is None:
        return jsonify({"error": "Submission not found"}), 404
    if not _is_jury(user, submission.contest):
        return jsonify({"error": "Only a contest jury member can review submissions"}), 403

    data = request.get_json(silent=True) or {}
    try:
        submission = review_submission(
            submission, user.id, data.get('decision'),
            score=data.get('score'),
            review_comment=data.get('review_comment'),
            parameter_scores=data.get('parameter_scores'),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(submission.to_dict()), 200
