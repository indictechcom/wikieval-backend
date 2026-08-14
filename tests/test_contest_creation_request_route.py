"""Tests for the contest-creation rights routes (status / submit / review)."""

from model import User
from services.contest_creation_request import create_contest_creation_request

SUPERADMIN = "Jayprakash12345"   # hard-coded in app.SUPERADMINS


def _make_pending_request(db, username="Alice"):
    """Create a requester + a pending request directly, for review tests."""
    user = User(username=username)
    db.session.add(user)
    db.session.commit()
    req = create_contest_creation_request(user.id, "I run contests")
    return user, req


# --- status (GET) ---

def test_status_requires_login(client):
    resp = client.get("/api/contest-creation-request")
    assert resp.status_code == 401


def test_status_when_no_request(client, login_as):
    login_as(client, "Alice")

    resp = client.get("/api/contest-creation-request")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["request"] is None
    assert body["can_create_contest"] is False


def test_status_reflects_pending_request(client, login_as):
    login_as(client, "Alice")
    client.post("/api/contest-creation-request", json={"reason": "I run contests"})

    resp = client.get("/api/contest-creation-request")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["can_create_contest"] is False
    assert body["request"]["status"] == "pending"
    assert body["request"]["reason"] == "I run contests"


def test_status_reflects_approval(client, db, login_as):
    user, req = _make_pending_request(db, "Alice")
    # Superadmin approves it.
    login_as(client, SUPERADMIN)
    client.post(
        f"/api/contest-creation-request/{req.id}/review",
        json={"decision": "approve"},
    )
    # Alice comes back and checks her status.
    login_as(client, "Alice")

    resp = client.get("/api/contest-creation-request")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["can_create_contest"] is True
    assert body["request"]["status"] == "approved"


# --- list (GET, superadmin) ---

def test_list_requires_login(client):
    resp = client.get("/api/contest-creation-requests")
    assert resp.status_code == 401


def test_list_requires_superadmin(client, db, login_as):
    _make_pending_request(db, "Alice")
    login_as(client, "NotAnAdmin")

    resp = client.get("/api/contest-creation-requests")

    assert resp.status_code == 403


def test_superadmin_lists_all_requests(client, db, login_as):
    _make_pending_request(db, "Alice")
    _make_pending_request(db, "Bob")
    login_as(client, SUPERADMIN)

    resp = client.get("/api/contest-creation-requests")
    body = resp.get_json()

    assert resp.status_code == 200
    assert len(body["requests"]) == 2
    assert {r["username"] for r in body["requests"]} == {"Alice", "Bob"}


# --- submit ---

def test_submit_requires_login(client):
    resp = client.post("/api/contest-creation-request", json={"reason": "let me in"})
    assert resp.status_code == 401


def test_logged_in_user_can_submit(client, login_as):
    login_as(client, "Alice")

    resp = client.post("/api/contest-creation-request", json={"reason": "I run contests"})
    body = resp.get_json()

    assert resp.status_code == 201
    assert body["status"] == "pending"
    assert body["username"] == "Alice"
    assert body["reason"] == "I run contests"


def test_submit_requires_reason(client, login_as):
    login_as(client, "Alice")

    resp = client.post("/api/contest-creation-request", json={})

    assert resp.status_code == 400


def test_submit_blocks_duplicate(client, login_as):
    login_as(client, "Alice")
    client.post("/api/contest-creation-request", json={"reason": "first"})

    resp = client.post("/api/contest-creation-request", json={"reason": "second"})

    assert resp.status_code == 400


# --- review (approve / reject) ---

def _review_url(request_id):
    return f"/api/contest-creation-request/{request_id}/review"


def test_review_requires_login(client, db):
    _user, req = _make_pending_request(db)

    resp = client.post(_review_url(req.id), json={"decision": "approve"})

    assert resp.status_code == 401


def test_non_superadmin_cannot_review(client, db, login_as):
    user, req = _make_pending_request(db)
    login_as(client, "NotAnAdmin")

    resp = client.post(_review_url(req.id), json={"decision": "approve"})

    assert resp.status_code == 403
    db.session.refresh(user)
    assert user.can_create_contest is False          # no grant leaked through


def test_review_rejects_invalid_decision(client, db, login_as):
    _user, req = _make_pending_request(db)
    login_as(client, SUPERADMIN)

    resp = client.post(_review_url(req.id), json={"decision": "maybe"})

    assert resp.status_code == 400


def test_superadmin_approve_grants_rights(client, db, login_as):
    user, req = _make_pending_request(db)
    login_as(client, SUPERADMIN)

    resp = client.post(_review_url(req.id), json={"decision": "approve"})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "approved"
    db.session.refresh(user)
    assert user.can_create_contest is True           # rights granted end-to-end


def test_superadmin_can_reject(client, db, login_as):
    user, req = _make_pending_request(db)
    login_as(client, SUPERADMIN)

    resp = client.post(
        _review_url(req.id),
        json={"decision": "reject", "rejection_reason": "insufficient activity"},
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "rejected"
    db.session.refresh(user)
    assert user.can_create_contest is False


def test_reject_requires_reason(client, db, login_as):
    _user, req = _make_pending_request(db)
    login_as(client, SUPERADMIN)

    resp = client.post(_review_url(req.id), json={"decision": "reject"})

    assert resp.status_code == 400
