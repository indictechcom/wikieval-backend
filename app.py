#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, session, jsonify, render_template, request
from flask_mwoauth import MWOAuth
from flask_migrate import Migrate
from utils import getHeader, get_wikimedia_edit_count
from flask_cors import CORS
import requests_oauthlib
import os
import yaml
from model import db, ContestRequest
import services
import logging
from model import db, ContestRequest, User
import contest_services
import submission_services
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load configuration from YAML file
root_dir = os.path.dirname(__file__)
app.config.update(yaml.safe_load(open(os.path.join(root_dir, 'config.yaml'))))

# Get variables
ENV = app.config['ENV']
BASE_URL = app.config['OAUTH_MWURI']
API_ENDPOINT = BASE_URL + '/api.php'
CONSUMER_KEY = app.config['CONSUMER_KEY']
CONSUMER_SECRET = app.config['CONSUMER_SECRET']

# Enable CORS and Debugging in Dev mode
if ENV == 'dev':
    CORS(app, supports_credentials=True)
    app.config['DEBUG'] = True

# Create Database and Migration Object
db.init_app(app)
migrate = Migrate(app, db)

# Register blueprint to app
MW_OAUTH = MWOAuth(
    base_url=BASE_URL,
    consumer_key=CONSUMER_KEY,
    consumer_secret=CONSUMER_SECRET,
    user_agent= getHeader()['User-Agent']
)
app.register_blueprint(MW_OAUTH.bp)


@app.route('/index', methods=['GET'])
@app.route("/")
def index():
    return render_template('index.html')



@app.route('/api/user', methods=['GET'])
def get_base_variables():
    return jsonify({
        "logged": logged() is not None,
        "username": MW_OAUTH.get_current_user(True)
    }), 200


def authenticated_session():
    if 'mwoauth_access_token' in session:
        auth = requests_oauthlib.OAuth1(
            client_key=CONSUMER_KEY,
            client_secret=CONSUMER_SECRET,
            resource_owner_key=session['mwoauth_access_token']['key'],
            resource_owner_secret=session['mwoauth_access_token']['secret']
        )
        return auth

    return None


def logged():
    if MW_OAUTH.get_current_user(True) is not None:
        return MW_OAUTH.get_current_user(True)
    else:
        return None


def current_user():
    """Return the logged-in user's row, creating it on first login, or None."""
    username = logged()
    return services.get_or_create_user(username) if username else None


def require_admin():
    """Return (user, error_response). error_response is None if allowed."""
    user = current_user()
    if user is None:
        return None, (jsonify({"error": "Login required"}), 401)
    if user.role not in ('superadmin'):
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None

# CONTEST CREATOR REQUEST WORKFLOW

@app.route('/api/contest-requests', methods=['POST'])
def submit_contest_request():
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    reason = (request.get_json(silent=True) or {}).get('reason')
    edit_count = get_wikimedia_edit_count(user.username)

    try:
        contest_request = services.create_contest_request(user.id, reason, edit_count)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest_request.to_dict()), 201


@app.route('/api/contest-requests', methods=['GET'])
def list_contest_requests():
    _, error = require_admin()
    if error:
        return error

    query = ContestRequest.query
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)

    return jsonify([r.to_dict() for r in query.order_by(ContestRequest.created_at.desc())]), 200


@app.route('/api/contest-requests/<int:request_id>/approve', methods=['POST'])
def approve_contest_request_route(request_id):
    admin, error = require_admin()
    if error:
        return error

    try:
        contest_request = services.approve_contest_request(request_id, admin.id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest_request.to_dict()), 200


@app.route('/api/contest-requests/<int:request_id>/reject', methods=['POST'])
def reject_contest_request_route(request_id):
    admin, error = require_admin()
    if error:
        return error

    rejection_reason = (request.get_json(silent=True) or {}).get('rejection_reason')

    try:
        contest_request = services.reject_contest_request(request_id, admin.id, rejection_reason)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest_request.to_dict()), 200

# ADMIN — USER MANAGEMENT (read-only)


@app.route('/api/users', methods=['GET'])
def list_users():
    _, error = require_admin()
    if error:
        return error

    from model import User
    role_filter = request.args.get('role')
    query = User.query
    if role_filter:
        query = query.filter_by(role=role_filter)

    return jsonify([u.to_dict() for u in query.order_by(User.created_at.desc())]), 200


@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    _, error = require_admin()
    if error:
        return error

    from model import User
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify(user.to_dict()), 200



# CONTEST MANAGEMENT


@app.route('/api/contests', methods=['POST'])
def create_contest_route():
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    name = data.get('name')
    project_name = data.get('project_name')

    def parse_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return "INVALID"

    start_date = parse_date(data.get('start_date'))
    end_date = parse_date(data.get('end_date'))
    if start_date == "INVALID" or end_date == "INVALID":
        return jsonify({"error": "Dates must be in YYYY-MM-DD format"}), 400

    if not name or not project_name:
        return jsonify({"error": "name and project_name are required"}), 400

    try:
        contest = contest_services.create_contest(
            user.id,
            name,
            project_name,
            description=data.get('description'),
            start_date=start_date,
            end_date=end_date,
            min_byte_count=data.get('min_byte_count', 0),
            min_reference_count=data.get('min_reference_count', 0),
            allowed_submission_type=data.get('allowed_submission_type', 'both'),
            marks_setting_accepted=data.get('marks_setting_accepted', 0),
            marks_setting_rejected=data.get('marks_setting_rejected', 0),
            scoring_parameters=data.get('scoring_parameters'),
            categories=data.get('categories'),
            organizer_ids=data.get('organizer_ids'),
            jury_ids=data.get('jury_ids'),
            template_link=data.get('template_link'),
            outreach_dashboard_url=data.get('outreach_dashboard_url'),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest.to_dict()), 201


@app.route('/api/contests', methods=['GET'])
def list_contests_route():
    result = contest_services.list_contests()
    return jsonify({
        "current": [c.to_dict() for c in result["current"]],
        "upcoming": [c.to_dict() for c in result["upcoming"]],
        "past": [c.to_dict() for c in result["past"]],
    }), 200


@app.route('/api/contests/<int:contest_id>', methods=['GET'])
def get_contest_route(contest_id):
    try:
        contest = contest_services.get_contest(contest_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify(contest.to_dict()), 200


@app.route('/api/contests/<int:contest_id>', methods=['PUT'])
def update_contest_route(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}

    def parse_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return "INVALID"

    if 'start_date' in data:
        parsed = parse_date(data['start_date'])
        if parsed == "INVALID":
            return jsonify({"error": "start_date must be in YYYY-MM-DD format"}), 400
        data['start_date'] = parsed

    if 'end_date' in data:
        parsed = parse_date(data['end_date'])
        if parsed == "INVALID":
            return jsonify({"error": "end_date must be in YYYY-MM-DD format"}), 400
        data['end_date'] = parsed

    try:
        contest = contest_services.update_contest(contest_id, user.id, **data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest.to_dict()), 200


@app.route('/api/contests/<int:contest_id>', methods=['DELETE'])
def delete_contest_route(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    try:
        contest_services.delete_contest(contest_id, user.id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"message": "Contest deleted successfully"}), 200


# SUBMISSION MANAGEMENT


@app.route('/api/contests/<int:contest_id>/submissions', methods=['POST'])
def create_submission_route(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True) or {}
    article_url = data.get('article_url')

    try:
        submission = submission_services.create_submission(user.id, contest_id, article_url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(submission.to_dict()), 201


@app.route('/api/contests/<int:contest_id>/submissions', methods=['GET'])
def list_submissions_route(contest_id):
    try:
        submissions = submission_services.list_submissions_for_contest(contest_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify([s.to_dict() for s in submissions]), 200


@app.route('/api/submissions/<int:submission_id>', methods=['GET'])
def get_submission_route(submission_id):
    try:
        submission = submission_services.get_submission(submission_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify(submission.to_dict()), 200


@app.route('/api/submissions/<int:submission_id>/review', methods=['POST'])
def review_submission_route(submission_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    if user.role not in ('jury', 'superadmin'):
        return jsonify({"error": "Only jury members or superadmins can review submissions"}), 403

    data = request.get_json(silent=True) or {}
    score = data.get('score')
    review_comment = data.get('review_comment')

    try:
        submission = submission_services.review_submission(submission_id, user.id, score, review_comment)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(submission.to_dict()), 200


if __name__ == "__main__":
    app.run()