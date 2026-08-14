"""Unit tests for services.user.get_or_create_user."""

from model import User
from services.user import get_or_create_user


def test_creates_user_when_missing(db):
    user = get_or_create_user("Alice")

    assert user.id is not None
    assert user.username == "Alice"
    assert user.user_language == "en"          # column default applied on insert
    assert User.query.count() == 1


def test_returns_existing_user_without_duplicating(db):
    first = get_or_create_user("Bob")
    again = get_or_create_user("Bob")

    assert again.id == first.id
    assert User.query.count() == 1             # second call did not insert


def test_distinct_usernames_create_distinct_rows(db):
    alice = get_or_create_user("Alice")
    bob = get_or_create_user("Bob")

    assert alice.id != bob.id
    assert User.query.count() == 2
