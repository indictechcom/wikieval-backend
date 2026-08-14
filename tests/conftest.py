"""
Shared pytest fixtures for all tests.

CRITICAL: DATABASE_URL is set to an in-memory SQLite DB *before* importing the
app, because Flask-SQLAlchemy binds the engine at import time (db.init_app).
This guarantees tests never connect to — or drop_all() — the real database.
"""

import os

# Must be set before `from app import ...` triggers db.init_app().
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest

import app as app_module
from app import app as flask_app
from model import db as _db
from services import mediawiki as mediawiki_module

# `sqlite://` uses SQLAlchemy's SingletonThreadPool (one connection per thread),
# so the schema created below is visible to the single-threaded test client.
flask_app.config["TESTING"] = True

# Safety backstop: refuse to run against anything but SQLite. If the DATABASE_URL
# override in app.py is ever removed, the app binds to the real (MySQL) database
# and the fixtures' create_all()/drop_all() would destroy it. Fail loudly at
# collection time instead — before any test runs.
_db_uri = flask_app.config["SQLALCHEMY_DATABASE_URI"]
if not _db_uri.startswith("sqlite"):
    raise RuntimeError(
        f"Tests must run on SQLite, but the app is bound to {_db_uri!r}. "
        "Aborting so the real database is never touched. Ensure app.py honors "
        "the DATABASE_URL env override."
    )


@pytest.fixture()
def app():
    """Fresh schema per test on the in-memory SQLite DB."""
    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    """Give tests direct access to the db session within the app context."""
    return _db


@pytest.fixture()
def client(app):
    """Flask test client for exercising routes and the before_request hook."""
    return app.test_client()


@pytest.fixture(autouse=True)
def stub_mediawiki(monkeypatch):
    """Stub the MediaWiki fetch so tests never hit the network.

    Returns deterministic metadata derived from the link.
    """
    def fake_process_article(article_link, contest=None):
        _base, title = mediawiki_module.title_from_link(article_link)
        return {
            "article_title": title,
            "display_title": title,
            "article_url": article_link,
            "page_id": 1000,
            "revision_id": 999,
            "namespace": 0,
            "byte_count": 1234,
            "creator": "MockCreator",
            "creator_id": 1,
            "created_at": "2001-01-01T00:00:00Z",
            "ref_new_count": 3,
            "ref_reused_count": 1,
            "image_count": 2,
            "outgoing_links": 10,
            "incoming_links": 5,
        }
    monkeypatch.setattr(mediawiki_module, "process_article", fake_process_article)


@pytest.fixture()
def login_as(monkeypatch):
    """Return a helper that fakes an authenticated MWOAuth session.

    MWOAuth.get_current_user is what the login hook and routes rely on, and the
    hook only acts when an OAuth token is present in the session.
    """
    def _login(client, username="TestUser"):
        monkeypatch.setattr(
            app_module.MW_OAUTH, "get_current_user",
            lambda cached=True: username,
        )
        with client.session_transaction() as sess:
            sess["mwoauth_access_token"] = {"key": "k", "secret": "s"}
            # Drop any cached id so the hook re-resolves for this username
            # (lets a test switch between users on the same client).
            sess.pop("uid", None)
    return _login
