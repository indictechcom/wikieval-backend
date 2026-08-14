"""Unit tests for services.contest_creation_request."""

import pytest

from model import ContestCreationRequest, RequestStatus, User
from services.contest_creation_request import (
    approve_contest_creation_request,
    create_contest_creation_request,
    reject_contest_creation_request,
)


def make_user(db, username="Alice"):
    user = User(username=username)
    db.session.add(user)
    db.session.commit()
    return user


# --- create ---

def test_create_makes_pending_request(db):
    user = make_user(db)

    req = create_contest_creation_request(user.id, "I organize edit-a-thons")

    assert req.id is not None
    assert req.user_id == user.id
    assert req.status == RequestStatus.PENDING.value
    assert req.reason == "I organize edit-a-thons"
    assert ContestCreationRequest.query.count() == 1


def test_create_strips_reason(db):
    user = make_user(db)

    req = create_contest_creation_request(user.id, "  spaced out  ")

    assert req.reason == "spaced out"


def test_create_raises_for_missing_user(db):
    with pytest.raises(ValueError, match="User not found"):
        create_contest_creation_request(9999, "reason")


def test_create_requires_non_empty_reason(db):
    user = make_user(db)

    with pytest.raises(ValueError, match="reason is required"):
        create_contest_creation_request(user.id, "   ")

    assert ContestCreationRequest.query.count() == 0


def test_create_blocks_duplicate_pending_request(db):
    user = make_user(db)
    create_contest_creation_request(user.id, "first")

    with pytest.raises(ValueError, match="pending request"):
        create_contest_creation_request(user.id, "second")

    assert ContestCreationRequest.query.count() == 1


def test_create_blocks_when_user_already_has_rights(db):
    user = make_user(db)
    user.can_create_contest = True
    db.session.commit()

    with pytest.raises(ValueError, match="already have contest-creation rights"):
        create_contest_creation_request(user.id, "reason")


# --- approve ---

def test_approve_grants_rights_and_stamps_review(db):
    requester = make_user(db, "Alice")
    reviewer = make_user(db, "Admin")
    req = create_contest_creation_request(requester.id, "reason")

    approved = approve_contest_creation_request(req.id, reviewer.id)

    assert approved.status == RequestStatus.APPROVED.value
    assert approved.reviewed_by == reviewer.id
    assert approved.reviewed_at is not None
    assert requester.can_create_contest is True      # the actual grant


def test_approve_raises_for_missing_request(db):
    with pytest.raises(ValueError, match="Request not found"):
        approve_contest_creation_request(9999, 1)


def test_approve_raises_if_already_reviewed(db):
    requester = make_user(db, "Alice")
    reviewer = make_user(db, "Admin")
    req = create_contest_creation_request(requester.id, "reason")
    approve_contest_creation_request(req.id, reviewer.id)

    with pytest.raises(ValueError, match="already been reviewed"):
        approve_contest_creation_request(req.id, reviewer.id)


# --- reject ---

def test_reject_sets_reason_without_granting_rights(db):
    requester = make_user(db, "Alice")
    reviewer = make_user(db, "Admin")
    req = create_contest_creation_request(requester.id, "reason")

    rejected = reject_contest_creation_request(req.id, reviewer.id, "insufficient activity")

    assert rejected.status == RequestStatus.REJECTED.value
    assert rejected.reviewed_by == reviewer.id
    assert rejected.rejection_reason == "insufficient activity"
    assert requester.can_create_contest is False     # rights NOT granted


def test_reject_requires_reason(db):
    requester = make_user(db, "Alice")
    reviewer = make_user(db, "Admin")
    req = create_contest_creation_request(requester.id, "reason")

    with pytest.raises(ValueError, match="rejection reason is required"):
        reject_contest_creation_request(req.id, reviewer.id, "  ")


def test_reject_raises_if_already_reviewed(db):
    requester = make_user(db, "Alice")
    reviewer = make_user(db, "Admin")
    req = create_contest_creation_request(requester.id, "reason")
    reject_contest_creation_request(req.id, reviewer.id, "no")

    with pytest.raises(ValueError, match="already been reviewed"):
        reject_contest_creation_request(req.id, reviewer.id, "no again")
