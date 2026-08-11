"""
Tests for services.py — the Contest Creator Request workflow.
Covers create (auto-approve and manual-review paths), approve, and reject.
"""

import pytest

from model import User, ContestRequest
from services import (
    create_contest_request,
    approve_contest_request,
    reject_contest_request,
)


def make_user(db, username, role="user"):
    user = User(username=username, role=role)
    db.session.add(user)
    db.session.commit()
    return user


# CREATE — auto-approve path

def test_create_auto_approves_at_300_plus_edits(db):
    user = make_user(db, "AutoUser")

    req = create_contest_request(user.id, reason=None, edit_count=300)

    assert req.status == "approved"
    assert req.reason is None
    assert user.role == "trusted_member"


def test_create_auto_approves_above_300_edits(db):
    user = make_user(db, "AutoUser2")

    req = create_contest_request(user.id, reason=None, edit_count=1091)

    assert req.status == "approved"
    assert user.role == "trusted_member"


# CREATE — manual review path

def test_create_requires_reason_below_300_edits(db):
    user = make_user(db, "ManualUser")

    with pytest.raises(ValueError, match="Reason is required"):
        create_contest_request(user.id, reason=None, edit_count=100)


def test_create_pending_below_300_edits_with_reason(db):
    user = make_user(db, "ManualUser2")

    req = create_contest_request(user.id, reason="I contribute a lot", edit_count=50)

    assert req.status == "pending"
    assert req.reason == "I contribute a lot"
    assert user.role == "user"  # unchanged


# CREATE — validation

def test_create_raises_for_missing_user(db):
    with pytest.raises(ValueError, match="User not found"):
        create_contest_request(user_id=9999, reason="test", edit_count=100)


def test_create_blocks_duplicate_pending_request(db):
    user = make_user(db, "DupUser")
    create_contest_request(user.id, reason="first request", edit_count=50)

    with pytest.raises(ValueError, match="already has a pending request"):
        create_contest_request(user.id, reason="second request", edit_count=50)


# APPROVE

def test_approve_sets_status_and_role(db):
    user = make_user(db, "ToApprove")
    admin = make_user(db, "Admin1", role="superadmin")
    req = create_contest_request(user.id, reason="please", edit_count=50)

    approved = approve_contest_request(req.id, admin.id)

    assert approved.status == "approved"
    assert approved.reviewed_by == admin.id
    assert approved.reviewed_at is not None
    assert user.role == "trusted_member"


def test_approve_raises_for_missing_request(db):
    with pytest.raises(ValueError, match="Request not found"):
        approve_contest_request(9999, reviewer_id=1)


def test_approve_raises_if_not_pending(db):
    user = make_user(db, "AlreadyDone")
    admin = make_user(db, "Admin2", role="superadmin")
    req = create_contest_request(user.id, reason=None, edit_count=500)  # auto-approved

    with pytest.raises(ValueError, match="already been approved"):
        approve_contest_request(req.id, admin.id)


# REJECT

def test_reject_sets_status_and_reason(db):
    user = make_user(db, "ToReject")
    admin = make_user(db, "Admin3", role="superadmin")
    req = create_contest_request(user.id, reason="please", edit_count=50)

    rejected = reject_contest_request(req.id, admin.id, rejection_reason="Not enough history")

    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "Not enough history"
    assert user.role == "user"  # unchanged


def test_reject_raises_for_missing_request(db):
    with pytest.raises(ValueError, match="Request not found"):
        reject_contest_request(9999, reviewer_id=1)