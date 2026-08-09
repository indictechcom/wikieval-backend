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
    if user.role not in ('admin', 'superadmin'):
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None


# ------------------------------------------------------------------
# CONTEST CREATOR REQUEST WORKFLOW
# ------------------------------------------------------------------

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


if __name__ == "__main__":
    app.run()