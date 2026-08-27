"""Tests for the contest routes (public list/detail, create, edit, start)."""

from model import User
from services.contest import create_contest, start_contest

CREATOR = "Creator"
SUPERADMIN = "Jayprakash12345"   # hard-coded in auth.SUPERADMINS


def _make_creator(db, username=CREATOR, can_create=True):
    user = User(username=username, can_create_contest=can_create)
    db.session.add(user)
    db.session.commit()
    return user


def _make_contest(db, creator, name="X", project_name="commons"):
    return create_contest(creator.id, name, project_name,
                          start_date="2026-01-01", marks_setting_accepted=10)


# --- public list / detail ---

def test_public_list_shows_only_active(client, db):
    creator = _make_creator(db)
    _make_contest(db, creator, name="Draft")               # pending
    active = _make_contest(db, creator, name="Live")
    start_contest(active)

    resp = client.get("/api/contests")                     # no login
    names = [c["name"] for c in resp.get_json()["contests"]]

    assert resp.status_code == 200
    assert names == ["Live"]                               # pending hidden


def test_creator_sees_own_pending_but_not_others(client, db, login_as):
    creator = _make_creator(db)
    other = _make_creator(db, "Other")
    _make_contest(db, creator, name="MyDraft")             # pending, mine
    _make_contest(db, other, name="OthersDraft")           # pending, someone else's
    active = _make_contest(db, creator, name="Live")
    start_contest(active)
    login_as(client, CREATOR)

    resp = client.get("/api/contests")
    names = {c["name"] for c in resp.get_json()["contests"]}

    assert resp.status_code == 200
    assert names == {"MyDraft", "Live"}                    # own pending + active only


def test_superadmin_list_shows_pending_too(client, db, login_as):
    creator = _make_creator(db)
    _make_contest(db, creator, name="Draft")               # pending
    active = _make_contest(db, creator, name="Live")
    start_contest(active)
    login_as(client, SUPERADMIN)

    resp = client.get("/api/contests")
    names = {c["name"] for c in resp.get_json()["contests"]}

    assert resp.status_code == 200
    assert names == {"Draft", "Live"}                      # both visible


def test_get_one_and_404(client, db):
    creator = _make_creator(db)
    c = _make_contest(db, creator)

    assert client.get(f"/api/contests/{c.id}").status_code == 200
    assert client.get("/api/contests/9999").status_code == 404


# --- create ---

def test_create_requires_login(client):
    resp = client.post("/api/contests", json={"name": "X", "project_name": "commons"})
    assert resp.status_code == 401


def test_create_requires_rights(client, db, login_as):
    _make_creator(db, "NoRights", can_create=False)
    login_as(client, "NoRights")

    resp = client.post("/api/contests", json={"name": "X", "project_name": "commons"})

    assert resp.status_code == 403


def test_superadmin_can_create_without_flag(client, db, login_as):
    login_as(client, SUPERADMIN)   # superadmin, no can_create_contest flag

    resp = client.post("/api/contests", json={
        "name": "SA Contest", "project_name": "commons",
        "start_date": "2026-09-01", "marks_setting_accepted": 10,
    })

    assert resp.status_code == 201


def test_creator_can_create(client, db, login_as):
    _make_creator(db)
    login_as(client, CREATOR)

    resp = client.post(
        "/api/contests",
        json={"name": "Photo", "project_name": "commons", "start_date": "2026-09-01",
              "marks_setting_accepted": 10, "eligibility_rules": {"min_byte_count": 100}},
    )
    body = resp.get_json()

    assert resp.status_code == 201
    assert body["status"] == "pending"
    assert body["creator_username"] == CREATOR
    assert body["eligibility_rules"]["min_byte_count"] == 100


def test_create_requires_start_date(client, db, login_as):
    _make_creator(db)
    login_as(client, CREATOR)

    resp = client.post("/api/contests", json={"name": "X", "project_name": "commons"})

    assert resp.status_code == 400


# --- edit ---

def test_update_requires_login(client, db):
    creator = _make_creator(db)
    c = _make_contest(db, creator)

    resp = client.put(f"/api/contests/{c.id}", json={"name": "X"})

    assert resp.status_code == 401


def test_creator_can_edit_while_pending(client, db, login_as):
    creator = _make_creator(db)
    c = _make_contest(db, creator)
    login_as(client, CREATOR)

    resp = client.put(f"/api/contests/{c.id}", json={"name": "Renamed"})

    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Renamed"


def test_organizer_can_edit(client, db, login_as):
    creator = _make_creator(db)
    c = create_contest(creator.id, "X", "commons", start_date="2026-01-01",
                       marks_setting_accepted=10, organizers=["Helper"])
    login_as(client, "Helper")   # an organizer, not the creator

    resp = client.put(f"/api/contests/{c.id}", json={"name": "Edited by organizer"})

    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Edited by organizer"


def test_non_creator_cannot_edit(client, db, login_as):
    creator = _make_creator(db)
    c = _make_contest(db, creator)
    _make_creator(db, "Other", can_create=False)
    login_as(client, "Other")

    resp = client.put(f"/api/contests/{c.id}", json={"name": "Hijack"})

    assert resp.status_code == 403


# --- start / lock ---

def test_start_locks_editing(client, db, login_as):
    creator = _make_creator(db)
    c = _make_contest(db, creator)
    login_as(client, CREATOR)

    started = client.post(f"/api/contests/{c.id}/start")
    assert started.status_code == 200
    assert started.get_json()["status"] == "active"

    # Editing a started contest is now locked.
    locked = client.put(f"/api/contests/{c.id}", json={"name": "Too late"})
    assert locked.status_code == 409


def test_non_creator_cannot_start(client, db, login_as):
    creator = _make_creator(db)
    c = _make_contest(db, creator)
    _make_creator(db, "Other", can_create=False)
    login_as(client, "Other")

    resp = client.post(f"/api/contests/{c.id}/start")

    assert resp.status_code == 403
