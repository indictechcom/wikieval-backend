#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, session, jsonify, render_template
from flask_mwoauth import MWOAuth
from flask_migrate import Migrate
from utils import getHeader
from flask_cors import CORS
import requests_oauthlib
import os
import yaml
from model import db
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


if __name__ == "__main__":
    app.run()