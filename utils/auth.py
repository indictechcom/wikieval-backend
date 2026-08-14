from flask import session

from model import User, db

# Bootstrap superadmins: MediaWiki usernames hard-coded as superadmins.
SUPERADMINS = {"Jayprakash12345"}


def is_superadmin(username):
    return username is not None and username in SUPERADMINS


def current_user():
    uid = session.get('uid')
    return db.session.get(User, uid) if uid else None


def may_create_contest(user):
    return bool(user and (user.can_create_contest or is_superadmin(user.username)))
