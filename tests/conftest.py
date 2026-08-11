"""
Shared pytest fixtures for all tests.
Provides a fresh, isolated in-memory database for every test function,
so tests never touch the real local_test.db and never interfere
with each other.
"""

import pytest

from app import app as flask_app
from model import db as _db


@pytest.fixture()
def app():
    """Configure the Flask app to use an in-memory SQLite DB for tests."""
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })

    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    """Give tests direct access to the db session within the app context."""
    return _db