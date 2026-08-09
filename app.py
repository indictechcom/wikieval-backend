#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, session, jsonify, render_template, request
from flask_mwoauth import MWOAuth
from flask_migrate import Migrate
from utils import getHeader
from flask_cors import CORS
import requests_oauthlib
import os
import yaml
from model import db, Contest
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


# ------------------------------------------------------------------
# CONTEST CRUD
# ------------------------------------------------------------------

@app.route('/api/contests', methods=['POST'])
def create_contest():
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401
    if not services.can_create_contests(user):
        return jsonify({"error": "Only trusted members can create contests"}), 403

    try:
        contest = services.create_contest(user, request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest.to_dict()), 201


@app.route('/api/contests', methods=['GET'])
def list_contests():
    if current_user() is None:
        return jsonify({"error": "Login required"}), 401

    contests = Contest.query.order_by(Contest.created_at.desc()).all()
    return jsonify([c.to_dict() for c in contests]), 200


@app.route('/api/contests/<int:contest_id>', methods=['GET'])
def get_contest(contest_id):
    if current_user() is None:
        return jsonify({"error": "Login required"}), 401

    contest = Contest.query.get(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404

    return jsonify(contest.to_dict()), 200


@app.route('/api/contests/<int:contest_id>', methods=['PUT'])
def update_contest_route(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    contest = Contest.query.get(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    if not services.can_manage_contest(user, contest):
        return jsonify({"error": "You are not allowed to update this contest"}), 403

    try:
        contest = services.update_contest(contest, request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(contest.to_dict()), 200


@app.route('/api/contests/<int:contest_id>', methods=['DELETE'])
def delete_contest_route(contest_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "Login required"}), 401

    contest = Contest.query.get(contest_id)
    if contest is None:
        return jsonify({"error": "Contest not found"}), 404
    if not services.can_manage_contest(user, contest):
        return jsonify({"error": "You are not allowed to delete this contest"}), 403

    services.delete_contest(contest)
    return jsonify({"message": "Contest deleted"}), 200


if __name__ == "__main__":
    app.run()