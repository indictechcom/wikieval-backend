#!/usr/bin/env python3

import logging
import os

import yaml
from flask import Flask, jsonify, render_template, request, session
from flask_cors import CORS
from flask_migrate import Migrate
from flask_mwoauth import MWOAuth
from sqlalchemy.exc import SQLAlchemyError

from model import User, db
from routes.contest import bp as contest_bp
from routes.contest_creation_request import bp as contest_creation_request_bp
from routes.submission import bp as submission_bp
from services.user import get_or_create_user
from utils.auth import current_user, is_superadmin, may_create_contest
from utils.wiki import getHeader

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load configuration from YAML file
root_dir = os.path.dirname(__file__)
app.config.update(yaml.safe_load(open(os.path.join(root_dir, 'config.yaml'))))

# Allow the database URL to be overridden via env (used by tests/CI so they
# never touch the real database). Must be applied before db.init_app below.
if os.environ.get('DATABASE_URL'):
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']

# MySQL closes idle connections after `wait_timeout`, so a pooled connection
# can be dead by the next request ("MySQL server has gone away", error 2006).
# pool_pre_ping validates each connection before handing it out; pool_recycle
# proactively discards connections older than the timeout window.
app.config.setdefault('SQLALCHEMY_ENGINE_OPTIONS', {}).update({
    'pool_pre_ping': True,
    'pool_recycle': 280,
})

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
    # Dev runs over plain HTTP, so a Secure session cookie is dropped by the
    # browser (Safari strictly; Chrome allows it on localhost). That loses the
    # session across the OAuth redirect. Keep it Secure in prod (HTTPS) only.
    app.config['SESSION_COOKIE_SECURE'] = False

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
app.register_blueprint(contest_creation_request_bp)
app.register_blueprint(contest_bp)
app.register_blueprint(submission_bp)


@app.before_request
def sync_logged_in_user():
    """Lazily persist the logged-in MediaWiki user."""
    # Static assets (JS/CSS/favicon) don't need a user; skip the DB lookup so
    # every asset request isn't gated on a database round-trip.
    if request.endpoint == 'static':
        return

    token = session.get('mwoauth_access_token')
    if not token:
        # Logged out (or never logged in) — drop any stale id.
        session.pop('uid', None)
        return

    # Fast path: a cached id that still resolves to a real user. Re-resolve if
    # the row is gone (e.g. the user was deleted or the DB was reset), so a
    # stale uid can't leave a valid session stuck at 401.
    uid = session.get('uid')
    if uid and db.session.get(User, uid) is not None:
        return

    username = MW_OAUTH.get_current_user(True)
    if not username:
        return

    try:
        user = get_or_create_user(username)
        session['uid'] = user.id
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Failed to sync logged-in user %s", username)


@app.route('/index', methods=['GET'])
@app.route("/")
def index():
    return render_template('index.html')


@app.route('/<path:path>')
def spa_fallback(path):
    """Serve the SPA for client-side routes (e.g. /contests) on hard refresh.

    Vue Router handles these in the browser, but a page reload hits Flask
    directly. API paths still 404 as JSON; static assets are served by Flask's
    (more specific) static route and never reach here.
    """
    if path.startswith('api/'):
        return jsonify({"error": "Not found"}), 404
    return render_template('index.html')



@app.route('/api/user', methods=['GET'])
def get_base_variables():
    username = logged()
    user = current_user()
    return jsonify({
        "logged": username is not None,
        "username": username,
        "is_superadmin": is_superadmin(username),
        "can_create_contest": may_create_contest(user),
    }), 200


def logged():
    """Return the logged-in MediaWiki username, or None if not authenticated."""
    return MW_OAUTH.get_current_user(True)