"""Tests for child-campaign requests: a local organizer asks, from a group
campaign's page, for a child campaign; the group's organizers review it."""

from model import ChildCampaignRequest, Contest, User
from services.child_campaign_request import create_child_campaign_request
from services.contest import create_contest

SUPERADMIN = "Jayprakash12345"   # hard-coded in utils.auth.SUPERADMINS
OWNER = "GroupOwner"
LOCAL = "LocalOrg"


def _user(db, username, can_create=False):
    user = User(username=username, can_create_contest=can_create)
    db.session.add(user)
    db.session.commit()
    return user


def _group(db, owner, **extra):
    fields = dict(
        start_date="2026-01-01", end_date="2026-12-31", timezone="Asia/Kolkata",
        marks_setting_accepted=10, marks_setting_rejected=-2,
        eligibility_rules={"min_word_count": 10, "min_image_count": 2},
        scoring_parameters={"enabled": True, "max_score": 10,
                            "parameters": [{"name": "Quality", "points": 10}]},
        reviews_required=2, jury_members=["DefaultJuror"], is_group=True,
    )
    fields.update(extra)
    return create_contest(owner.id, "Asian Month", "wikipedia", **fields)


def _url(group, request_id=None):
    base = f"/api/contests/{group.id}/child-requests"
    return base if request_id is None else f"{base}/{request_id}/review"


def _submit(client, group, **body):
    payload = {"name": "Asian Month India", "organizers": [LOCAL],
               "jury_members": ["JurorA"]}
    payload.update(body)
    return client.post(_url(group), json=payload)


# --- submit ---

def test_submit_requires_login(client, db):
    group = _group(db, _user(db, OWNER, True))
    assert _submit(client, group).status_code == 401


def test_submit_creates_pending_request(client, db, login_as):
    group = _group(db, _user(db, OWNER, True))
    login_as(client, LOCAL)

    resp = _submit(client, group)
    body = resp.get_json()

    assert resp.status_code == 201
    assert body["status"] == "pending"
    assert body["name"] == "Asian Month India"
    assert body["organizers"] == [LOCAL]
    assert body["jury_members"] == ["JurorA"]
    assert body["username"] == LOCAL
    assert body["parent_id"] == group.id
    assert body["contest_id"] is None
    # Nothing is created until approval, and no rights are granted.
    assert Contest.query.filter_by(parent_id=group.id).count() == 0
    assert User.query.filter_by(username=LOCAL).one().can_create_contest is False


def test_submit_does_not_need_creation_rights(client, db, login_as):
    group = _group(db, _user(db, OWNER, True))
    login_as(client, "Nobody")
    assert _submit(client, group, organizers=["Nobody"]).status_code == 201


def test_submit_requires_name_and_an_organizer(client, db, login_as):
    group = _group(db, _user(db, OWNER, True))
    login_as(client, LOCAL)

    assert _submit(client, group, name="  ").status_code == 400
    assert _submit(client, group, organizers=[]).status_code == 400
    assert _submit(client, group, organizers=["", "  "]).status_code == 400
    assert _submit(client, group, organizers="LocalOrg").status_code == 400
    # Jury is optional.
    assert _submit(client, group, jury_members=None).status_code == 201


def test_submit_only_on_a_group_campaign(client, db, login_as):
    owner = _user(db, OWNER, True)
    plain = create_contest(owner.id, "Plain", "hi", start_date="2026-01-01",
                           marks_setting_accepted=10)
    login_as(client, LOCAL)

    resp = client.post(f"/api/contests/{plain.id}/child-requests",
                       json={"name": "X", "organizers": [LOCAL]})
    assert resp.status_code == 400
    assert client.post("/api/contests/424242/child-requests",
                       json={"name": "X", "organizers": [LOCAL]}).status_code == 404


def test_submit_rejects_duplicate_names(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    create_contest(owner.id, "Asian Month Nepal", "hi", start_date="2026-01-01",
                   marks_setting_accepted=10, parent_id=group.id)
    login_as(client, LOCAL)

    # Clashes with an existing child (case-insensitive) ...
    resp = _submit(client, group, name="asian month nepal")
    assert resp.status_code == 400
    assert "already exists" in resp.get_json()["error"]
    # ... or with a pending request. A rejected one may be re-requested.
    assert _submit(client, group).status_code == 201
    assert _submit(client, group).status_code == 400


# --- list ---

def test_list_requires_login(client, db):
    group = _group(db, _user(db, OWNER, True))
    assert client.get(_url(group)).status_code == 401


def test_requester_sees_only_own_requests(client, db, login_as):
    group = _group(db, _user(db, OWNER, True))
    other = _user(db, "Other")
    create_child_campaign_request(group, other.id, "Other's", organizers=["Other"])
    login_as(client, LOCAL)
    _submit(client, group)

    body = client.get(_url(group)).get_json()

    assert body["can_review"] is False
    assert [r["name"] for r in body["requests"]] == ["Asian Month India"]


def test_group_organizer_sees_all_requests(client, db, login_as):
    group = _group(db, _user(db, OWNER, True))
    other = _user(db, "Other")
    create_child_campaign_request(group, other.id, "Other's", organizers=["Other"])
    local = _user(db, LOCAL)
    create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])
    login_as(client, OWNER)

    body = client.get(_url(group)).get_json()

    assert body["can_review"] is True
    assert sorted(r["name"] for r in body["requests"]) == ["Mine", "Other's"]


def test_superadmin_can_review(client, db, login_as):
    group = _group(db, _user(db, OWNER, True))
    login_as(client, SUPERADMIN)
    assert client.get(_url(group)).get_json()["can_review"] is True


def test_child_organizer_is_not_a_group_reviewer(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    create_contest(owner.id, "Child", "hi", start_date="2026-01-01",
                   marks_setting_accepted=10, parent_id=group.id,
                   organizers=["ChildOrg"])
    login_as(client, "ChildOrg")
    assert client.get(_url(group)).get_json()["can_review"] is False


# --- review ---

def test_review_requires_group_organizer(client, db, login_as):
    group = _group(db, _user(db, OWNER, True))
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])

    assert client.post(_url(group, req.id), json={"decision": "approve"}).status_code == 401
    login_as(client, LOCAL)   # the requester can't approve their own request
    assert client.post(_url(group, req.id), json={"decision": "approve"}).status_code == 403
    assert req.status == "pending"


def test_approve_creates_child_with_group_defaults_and_grants_rights(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Asian Month India",
                                        organizers=[LOCAL, "Helper"],
                                        jury_members=["JurorA"])
    login_as(client, OWNER)

    resp = client.post(_url(group, req.id), json={"decision": "approve"})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "approved"
    assert body["reviewer_username"] == OWNER
    child = db.session.get(Contest, body["contest_id"])
    assert body["contest_name"] == child.name == "Asian Month India"
    assert child.parent_id == group.id and child.is_group is False
    assert child.status == "pending"            # a draft the locals start
    assert child.created_by == local.id
    # Group defaults inherited without any extra input ...
    assert child.project_name == "wikipedia"
    assert child.timezone == "Asia/Kolkata"
    assert child.start_date.date() == group.start_date.date()
    assert child.end_date.date() == group.end_date.date()
    assert child.eligibility_rules == {"min_word_count": 10, "min_image_count": 2}
    assert child.marks_setting_accepted == 10
    assert child.marks_setting_rejected == -2
    assert child.scoring_parameters["enabled"] is True
    assert child.reviews_required == 2
    # ... with the request's organizers and jury.
    assert child.organizers == [LOCAL, "Helper"]
    assert child.jury_members == ["JurorA"]
    # The requester now holds contest-creation rights.
    assert db.session.get(User, local.id).can_create_contest is True
    # Rows exist for the named organizers/jury.
    assert User.query.filter_by(username="Helper").count() == 1
    assert User.query.filter_by(username="JurorA").count() == 1


def test_approve_without_jury_uses_group_default_jury(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])
    login_as(client, OWNER)

    body = client.post(_url(group, req.id), json={"decision": "approve"}).get_json()

    assert db.session.get(Contest, body["contest_id"]).jury_members == ["DefaultJuror"]


def test_reviewer_can_edit_organizers_and_jury_before_approving(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL],
                                        jury_members=["JurorA"])
    login_as(client, OWNER)

    body = client.post(_url(group, req.id), json={
        "decision": "approve", "organizers": ["Lead"], "jury_members": ["JurorB", "JurorC"],
    }).get_json()

    child = db.session.get(Contest, body["contest_id"])
    # The requester is the child's creator, so always one of its organizers.
    assert child.organizers == [LOCAL, "Lead"]
    assert child.jury_members == ["JurorB", "JurorC"]
    assert body["organizers"] == ["Lead"] and body["jury_members"] == ["JurorB", "JurorC"]


def test_approve_with_empty_organizers_is_400(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])
    login_as(client, OWNER)

    resp = client.post(_url(group, req.id), json={"decision": "approve", "organizers": []})

    assert resp.status_code == 400
    assert req.status == "pending"
    assert Contest.query.filter_by(parent_id=group.id).count() == 0


def test_approved_child_shows_in_children_list(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])
    login_as(client, OWNER)
    assert client.get(f"/api/contests/{group.id}/children").get_json()["children"] == []

    client.post(_url(group, req.id), json={"decision": "approve"})

    names = [c["name"] for c in client.get(f"/api/contests/{group.id}/children").get_json()["children"]]
    assert names == ["Mine"]


def test_reject_requires_reason_and_grants_nothing(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])
    login_as(client, OWNER)

    assert client.post(_url(group, req.id), json={"decision": "reject"}).status_code == 400
    resp = client.post(_url(group, req.id),
                       json={"decision": "reject", "rejection_reason": "Too soon"})
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["status"] == "rejected" and body["rejection_reason"] == "Too soon"
    assert body["contest_id"] is None
    assert Contest.query.filter_by(parent_id=group.id).count() == 0
    assert db.session.get(User, local.id).can_create_contest is False
    # Already reviewed: a second decision is refused.
    assert client.post(_url(group, req.id), json={"decision": "approve"}).status_code == 400


def test_review_bad_decision_and_wrong_group(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    other_group = create_contest(owner.id, "Other", "hi", start_date="2026-01-01",
                                 marks_setting_accepted=10, is_group=True)
    local = _user(db, LOCAL)
    req = create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])
    login_as(client, OWNER)

    assert client.post(_url(group, req.id), json={"decision": "maybe"}).status_code == 400
    assert client.post(_url(other_group, req.id), json={"decision": "approve"}).status_code == 404
    assert client.post(_url(group, 9999), json={"decision": "approve"}).status_code == 404


def test_requester_sees_status_after_review(client, db, login_as):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    login_as(client, LOCAL)
    req_id = _submit(client, group).get_json()["id"]
    login_as(client, OWNER)
    client.post(_url(group, req_id), json={"decision": "approve"})
    login_as(client, LOCAL)

    body = client.get(_url(group)).get_json()

    assert body["can_review"] is False
    (row,) = body["requests"]
    assert row["status"] == "approved" and row["contest_id"] is not None
    assert client.get("/api/user").get_json()["can_create_contest"] is True


def test_deleting_group_removes_its_requests(db):
    owner = _user(db, OWNER, True)
    group = _group(db, owner)
    local = _user(db, LOCAL)
    create_child_campaign_request(group, local.id, "Mine", organizers=[LOCAL])

    db.session.delete(group)
    db.session.commit()

    assert ChildCampaignRequest.query.count() == 0
