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


# --- campaign hierarchy ---

def _group(db, creator, name="Group"):
    return create_contest(creator.id, name, "commons", start_date="2026-01-01",
                          marks_setting_accepted=10, is_group=True)


def test_create_child_requires_parent_organizer(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    _make_creator(db, "Stranger")
    login_as(client, "Stranger")

    resp = client.post("/api/contests", json={
        "name": "Child", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "parent_id": group.id})

    assert resp.status_code == 403


def test_parent_organizer_creates_child(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    login_as(client, CREATOR)

    resp = client.post("/api/contests", json={
        "name": "Child", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "parent_id": group.id})
    body = resp.get_json()

    assert resp.status_code == 201
    assert body["parent_id"] == group.id and body["parent_name"] == "Group"
    assert body["is_group"] is False


def test_create_group_via_route(client, db, login_as):
    _make_creator(db)
    login_as(client, CREATOR)
    resp = client.post("/api/contests", json={
        "name": "G", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "is_group": True})
    assert resp.status_code == 201 and resp.get_json()["is_group"] is True


def test_is_group_is_fixed_after_creation(client, db, login_as):
    owner = _make_creator(db)
    plain = _make_contest(db, owner)
    login_as(client, CREATOR)
    resp = client.put(f"/api/contests/{plain.id}", json={"is_group": True})
    assert resp.status_code == 200 and resp.get_json()["is_group"] is False


def test_children_endpoint(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    live = create_contest(owner.id, "Live", "hi", start_date="2026-01-01",
                          marks_setting_accepted=10, parent_id=group.id)
    create_contest(owner.id, "Draft", "hi", start_date="2026-01-01",
                   marks_setting_accepted=10, parent_id=group.id)
    start_contest(live)

    public = client.get(f"/api/contests/{group.id}/children").get_json()["children"]
    assert [c["name"] for c in public] == ["Live"]
    assert {"submission_count", "accepted_count", "rejected_count",
            "pending_count", "participant_count"} <= set(public[0])

    login_as(client, CREATOR)
    mine = client.get(f"/api/contests/{group.id}/children").get_json()["children"]
    assert [c["name"] for c in mine] == ["Live", "Draft"]


def test_children_endpoint_rejects_non_group(client, db):
    owner = _make_creator(db)
    plain = _make_contest(db, owner)
    assert client.get(f"/api/contests/{plain.id}/children").status_code == 400


def test_attach_requires_organizer_of_both(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    other = _make_creator(db, "Other")
    theirs = _make_contest(db, other, name="Theirs")

    login_as(client, "Other")      # organizes the child, not the group
    resp = client.put(f"/api/contests/{theirs.id}", json={"parent_id": group.id})
    assert resp.status_code == 403

    login_as(client, CREATOR)      # organizes the group, not the child
    resp = client.put(f"/api/contests/{theirs.id}", json={"parent_id": group.id})
    assert resp.status_code == 403


def test_parent_organizer_can_detach_child_they_do_not_organize(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    other = _make_creator(db, "Other")
    child = create_contest(other.id, "Theirs", "hi", start_date="2026-01-01",
                           marks_setting_accepted=10, parent_id=group.id)
    login_as(client, CREATOR)

    # Parent organizers implicitly manage the child, so they can edit it...
    resp = client.put(f"/api/contests/{child.id}", json={"end_date": "2026-12-31"})
    assert resp.status_code == 200

    # ...and detach it. Afterwards they no longer manage it.
    resp = client.put(f"/api/contests/{child.id}", json={"parent_id": None})
    assert resp.status_code == 200 and resp.get_json()["parent_id"] is None
    resp = client.put(f"/api/contests/{child.id}", json={"end_date": "2026-12-30"})
    assert resp.status_code == 403


def test_submit_to_group_campaign_rejected(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)          # active from creation
    login_as(client, CREATOR)
    resp = client.post(f"/api/contests/{group.id}/submissions/evaluate",
                       json={"article_link": "https://en.wikipedia.org/wiki/Cat"})
    assert resp.status_code == 400
    assert "group campaign" in resp.get_json()["error"]


def test_child_organizer_cannot_detach_alone(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    other = _make_creator(db, "Other")
    child = create_contest(other.id, "Theirs", "hi", start_date="2026-01-01",
                           marks_setting_accepted=10, parent_id=group.id)
    login_as(client, "Other")

    resp = client.put(f"/api/contests/{child.id}", json={"parent_id": None})

    assert resp.status_code == 403
    assert "parent campaign" in resp.get_json()["error"]


def test_parent_organizer_sees_child_submissions_and_can_add(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    other = _make_creator(db, "Other")
    child = create_contest(other.id, "Theirs", "hi", start_date="2026-01-01",
                           marks_setting_accepted=10, parent_id=group.id)
    start_contest(child)
    login_as(client, CREATOR)                      # group organizer only

    resp = client.post(f"/api/contests/{child.id}/submissions/add",
                       json={"username": "Bob", "article_link": "https://en.wikipedia.org/wiki/Cat"})
    assert resp.status_code == 201

    resp = client.get(f"/api/contests/{child.id}/submissions")
    assert resp.status_code == 200
    assert [s["username"] for s in resp.get_json()["submissions"]] == ["Bob"]


def test_group_organizer_without_creation_rights_can_create_child(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    helper = _make_creator(db, "Helper", can_create=False)
    from services.contest import update_contest
    update_contest(group, organizers=["Creator", "Helper"])
    login_as(client, "Helper")

    resp = client.post("/api/contests", json={
        "name": "Child", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "parent_id": group.id})
    assert resp.status_code == 201

    # ...but still not a standalone contest.
    resp = client.post("/api/contests", json={
        "name": "Solo", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10})
    assert resp.status_code == 403


def test_group_cannot_be_started_via_route(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    login_as(client, CREATOR)
    resp = client.post(f"/api/contests/{group.id}/start")
    assert resp.status_code == 409


def test_hierarchy_changes_are_audit_logged(client, db, login_as):
    import logging
    from services.audit import review_audit
    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    owner = _make_creator(db)
    group = _group(db, owner)
    plain = _make_contest(db, owner, name="Plain")
    login_as(client, CREATOR)
    handler = _Capture()
    review_audit.addHandler(handler)
    try:
        client.post("/api/contests", json={
            "name": "Child", "project_name": "hi", "start_date": "2026-01-01",
            "marks_setting_accepted": 10, "parent_id": group.id})
        client.put(f"/api/contests/{plain.id}", json={"parent_id": group.id})
        client.put(f"/api/contests/{plain.id}", json={"parent_id": None})
        client.put(f"/api/contests/{plain.id}", json={"parent_id": None})   # no-op: not logged
    finally:
        review_audit.removeHandler(handler)

    lines = [m for m in captured if m.startswith("hierarchy")]
    assert [l.split("action=")[1].split()[0] for l in lines] == ["create-child", "attach", "detach"]
    assert f"contest={plain.id}" in lines[1] and f"parent={group.id}" in lines[1]
    assert f"previous_parent={group.id}" in lines[2]


# --- gaps: hierarchy edge cases via the API ---

def test_create_group_with_parent_is_rejected(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    login_as(client, CREATOR)
    resp = client.post("/api/contests", json={
        "name": "G2", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "is_group": True, "parent_id": group.id})
    assert resp.status_code == 400
    assert "cannot itself be a child" in resp.get_json()["error"]


def test_create_child_with_missing_parent_is_400(client, db, login_as):
    _make_creator(db)
    login_as(client, CREATOR)
    resp = client.post("/api/contests", json={
        "name": "Child", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "parent_id": 424242})
    assert resp.status_code == 400
    assert "not found" in resp.get_json()["error"]


def test_attach_to_non_group_is_400(client, db, login_as):
    owner = _make_creator(db)
    a = _make_contest(db, owner, name="A")
    b = _make_contest(db, owner, name="B")
    login_as(client, CREATOR)
    resp = client.put(f"/api/contests/{a.id}", json={"parent_id": b.id})
    assert resp.status_code == 400
    assert "must be a group" in resp.get_json()["error"]


def test_parent_organizer_can_start_child(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    other = _make_creator(db, "Other")
    child = create_contest(other.id, "Theirs", "hi", start_date="2026-01-01",
                           marks_setting_accepted=10, parent_id=group.id)
    login_as(client, CREATOR)
    resp = client.post(f"/api/contests/{child.id}/start")
    assert resp.status_code == 200 and resp.get_json()["status"] == "active"


def test_parent_organizer_is_not_jury_of_child(client, db, login_as):
    from services.submission import create_submission, evaluate_article
    owner = _make_creator(db)
    group = _group(db, owner)
    other = _make_creator(db, "Other")
    child = create_contest(other.id, "Theirs", "hi", start_date="2026-01-01",
                           marks_setting_accepted=10, parent_id=group.id,
                           jury_members=["Other"])
    start_contest(child)
    alice = _make_creator(db, "Alice", can_create=False)
    s = create_submission(alice.id, child,
                          evaluate_article(child, "https://en.wikipedia.org/wiki/Cat")["hash"])
    login_as(client, CREATOR)
    resp = client.post(f"/api/submissions/{s.id}/review", json={"decision": "accept"})
    assert resp.status_code == 403


def test_children_endpoint_superadmin_sees_drafts(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    create_contest(owner.id, "Draft", "hi", start_date="2026-01-01",
                   marks_setting_accepted=10, parent_id=group.id)
    _make_creator(db, SUPERADMIN, can_create=False)
    login_as(client, SUPERADMIN)
    names = [c["name"] for c in client.get(f"/api/contests/{group.id}/children").get_json()["children"]]
    assert names == ["Draft"]


def test_public_list_includes_groups_without_start(client, db):
    owner = _make_creator(db)
    _group(db, owner, name="Umbrella")
    names = [c["name"] for c in client.get("/api/contests").get_json()["contests"]]
    assert names == ["Umbrella"]


def test_import_into_child_counts_on_group(client, db, login_as):
    owner = _make_creator(db)
    group = _group(db, owner)
    child = create_contest(owner.id, "Child", "hi", start_date="2026-01-01",
                           marks_setting_accepted=10, parent_id=group.id)
    start_contest(child)
    _make_creator(db, SUPERADMIN, can_create=False)
    login_as(client, SUPERADMIN)
    resp = client.post(f"/api/contests/{child.id}/submissions/import",
                       json={"username": "Bob", "article_link": "https://en.wikipedia.org/wiki/Cat"})
    assert resp.status_code == 201
    assert client.get(f"/api/contests/{group.id}").get_json()["submission_count"] == 1
    assert client.get(f"/api/contests/{group.id}/children").get_json()["children"][0]["submission_count"] == 1


def test_contest_payload_includes_reviews_required(client, db, login_as):
    _make_creator(db)
    login_as(client, CREATOR)
    resp = client.post("/api/contests", json={
        "name": "C", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "reviews_required": 2})
    assert resp.status_code == 201 and resp.get_json()["reviews_required"] == 2

    bad = client.post("/api/contests", json={
        "name": "C2", "project_name": "hi", "start_date": "2026-01-01",
        "marks_setting_accepted": 10, "reviews_required": 0})
    assert bad.status_code == 400
