"""Tests for the login / persistence flow.

Covers the `sync_logged_in_user` before_request hook (lazy user persistence)
and what the `/api/user` endpoint reports. MWOAuth is mocked so no real
MediaWiki OAuth handshake is needed.
"""

from model import User

USERNAME = "Jayprakash12345"


def test_anonymous_is_not_logged_and_not_persisted(client):
    resp = client.get("/api/user")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["logged"] is False
    assert body["username"] is None
    assert body["is_superadmin"] is False
    assert body["can_create_contest"] is False
    assert User.query.count() == 0             # nothing written for anon


def test_login_reports_user_and_persists_row(client, login_as):
    login_as(client, USERNAME)

    resp = client.get("/api/user")
    body = resp.get_json()

    assert body["logged"] is True
    assert body["username"] == USERNAME
    assert body["is_superadmin"] is True       # USERNAME is a hard-coded superadmin
    assert body["can_create_contest"] is True  # superadmins may always create
    # before_request hook lazily created the row...
    assert User.query.filter_by(username=USERNAME).count() == 1
    # ...and cached its id in the session.
    with client.session_transaction() as sess:
        assert sess["uid"] is not None


def test_regular_user_is_not_superadmin(client, login_as):
    login_as(client, "RegularUser")

    body = client.get("/api/user").get_json()

    assert body["logged"] is True
    assert body["is_superadmin"] is False
    assert body["can_create_contest"] is False


def test_reports_can_create_contest(client, db, login_as):
    db.session.add(User(username="Creator", can_create_contest=True))
    db.session.commit()
    login_as(client, "Creator")   # hook resolves the existing user + flag

    body = client.get("/api/user").get_json()

    assert body["can_create_contest"] is True


def test_stale_uid_is_re_resolved(client, login_as):
    # Logged in, but the session's cached uid points to a non-existent user
    # (e.g. the row was deleted / DB reset). The hook must recover, not 401.
    login_as(client, USERNAME)
    with client.session_transaction() as sess:
        sess["uid"] = 9999   # no such user

    body = client.get("/api/user").get_json()

    assert body["logged"] is True
    assert body["username"] == USERNAME
    assert User.query.filter_by(username=USERNAME).count() == 1   # re-created
    with client.session_transaction() as sess:
        assert sess["uid"] != 9999                                # uid refreshed


def test_login_persists_user_only_once(client, login_as):
    login_as(client, USERNAME)
    client.get("/api/user")
    client.get("/api/user")

    assert User.query.filter_by(username=USERNAME).count() == 1


def test_logout_clears_cached_uid(client, login_as):
    login_as(client, USERNAME)
    client.get("/api/user")

    # Simulate logout: MWOAuth clears the access token from the session.
    with client.session_transaction() as sess:
        sess["mwoauth_access_token"] = None

    client.get("/api/user")
    with client.session_transaction() as sess:
        assert "uid" not in sess
