"""Unit tests for services.submission (evaluate + submit flow)."""

import pytest

from model import Submission, SubmissionStatus, User
from services.contest import create_contest, start_contest
from services.submission import (
    create_submission,
    evaluate_article,
    list_contest_submissions,
    review_submission,
)

ARTICLE = "https://en.wikipedia.org/wiki/Cat"


def make_user(db, username, can_create=False):
    user = User(username=username, can_create_contest=can_create)
    db.session.add(user)
    db.session.commit()
    return user


def active_contest(db, creator_name="Creator", **fields):
    creator = make_user(db, creator_name, can_create=True)
    fields.setdefault("start_date", "2026-01-01")
    fields.setdefault("marks_setting_accepted", 10)
    contest = create_contest(creator.id, "C", "commons", **fields)
    start_contest(contest)
    return creator, contest


def submit(contest, user, link=ARTICLE):
    """Full flow: evaluate, then create from the returned hash."""
    ev = evaluate_article(contest, link)
    return create_submission(user.id, contest, ev["hash"])


# --- evaluate ---

def test_evaluate_returns_info_and_hash(db):
    _creator, contest = active_contest(db)

    result = evaluate_article(contest, ARTICLE)

    assert result["hash"]
    assert result["article_link"] == ARTICLE
    assert result["article_metadata"]["article_title"] == "Cat"


def test_evaluate_decodes_link(db):
    _creator, contest = active_contest(db)
    encoded = "https://hi.wikipedia.org/wiki/%E0%A4%AD%E0%A4%BE%E0%A4%B0%E0%A4%A4"

    result = evaluate_article(contest, encoded)

    assert result["article_link"] == "https://hi.wikipedia.org/wiki/भारत"


def test_evaluate_rejects_inactive_contest(db):
    creator = make_user(db, "Creator", can_create=True)
    contest = create_contest(creator.id, "C", "commons", start_date="2026-01-01",
                             marks_setting_accepted=10)   # pending

    with pytest.raises(ValueError, match="not open for submissions"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_requires_link(db):
    _creator, contest = active_contest(db)

    with pytest.raises(ValueError, match="link is required"):
        evaluate_article(contest, "   ")


def test_evaluate_includes_revision_id_and_namespace(db):
    _creator, contest = active_contest(db)

    result = evaluate_article(contest, ARTICLE)

    assert result["article_metadata"]["revision_id"] == 999
    assert result["article_metadata"]["namespace"] == 0


def test_evaluate_rejects_below_min_byte_count(db):
    # stub returns byte_count=1234; require more.
    _creator, contest = active_contest(db, rules={"min_byte_count": 5000})

    with pytest.raises(ValueError, match="at least 5000 bytes"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_rejects_below_min_reference_count(db):
    # stub returns 3 new + 1 reused = 4 references; require more.
    _creator, contest = active_contest(db, rules={"min_reference_count": 10})

    with pytest.raises(ValueError, match="at least 10 references"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_accepts_when_minimums_met(db):
    _creator, contest = active_contest(db, rules={"min_byte_count": 1000, "min_reference_count": 3})

    result = evaluate_article(contest, ARTICLE)   # 1234 bytes, 4 refs -> OK

    assert result["hash"]


def test_evaluate_rejects_non_mainspace(db, monkeypatch):
    _creator, contest = active_contest(db)
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 1, "created_at": "2020-01-01T00:00:00Z"},
    )

    with pytest.raises(ValueError, match="main-namespace"):
        evaluate_article(contest, "https://en.wikipedia.org/wiki/Talk:Cat")


def test_evaluate_new_contest_rejects_article_created_before_start(db, monkeypatch):
    creator = make_user(db, "Creator", can_create=True)
    contest = create_contest(creator.id, "C", "commons",
                             rules={"allowed_submission_type": "new"}, start_date="2026-01-01",
                             marks_setting_accepted=10)
    start_contest(contest)
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "created_at": "2020-05-01T00:00:00Z"},
    )

    with pytest.raises(ValueError, match="created before the contest start"):
        evaluate_article(contest, "https://en.wikipedia.org/wiki/Old")


def test_evaluate_new_contest_accepts_article_created_after_start(db, monkeypatch):
    creator = make_user(db, "Creator", can_create=True)
    contest = create_contest(creator.id, "C", "commons",
                             rules={"allowed_submission_type": "new"}, start_date="2026-01-01",
                             marks_setting_accepted=10)
    start_contest(contest)
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "created_at": "2026-06-01T00:00:00Z"},
    )

    result = evaluate_article(contest, "https://en.wikipedia.org/wiki/New")

    assert result["hash"]


def test_evaluate_expansion_contest_rejects_article_created_after_start(db, monkeypatch):
    creator = make_user(db, "Creator", can_create=True)
    contest = create_contest(creator.id, "C", "commons",
                             rules={"allowed_submission_type": "expansion"}, start_date="2026-01-01",
                             marks_setting_accepted=10)
    start_contest(contest)
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "created_at": "2026-06-01T00:00:00Z"},
    )

    with pytest.raises(ValueError, match="created on or after the contest start"):
        evaluate_article(contest, "https://en.wikipedia.org/wiki/BrandNew")


def test_evaluate_expansion_contest_accepts_article_created_before_start(db, monkeypatch):
    creator = make_user(db, "Creator", can_create=True)
    contest = create_contest(creator.id, "C", "commons",
                             rules={"allowed_submission_type": "expansion"}, start_date="2026-01-01",
                             marks_setting_accepted=10)
    start_contest(contest)
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "created_at": "2020-05-01T00:00:00Z"},
    )

    result = evaluate_article(contest, "https://en.wikipedia.org/wiki/Existing")

    assert result["hash"]


# --- submit (create from hash) ---

def test_submit_creates_pending_with_evaluated_metadata(db):
    _creator, contest = active_contest(db)
    user = make_user(db, "Sub")

    s = submit(contest, user)

    assert s.status == SubmissionStatus.PENDING.value
    assert s.article_link == ARTICLE
    assert s.article_metadata["article_title"] == "Cat"
    assert Submission.query.count() == 1


def test_submit_rejects_missing_hash(db):
    _creator, contest = active_contest(db)
    user = make_user(db, "Sub")

    with pytest.raises(ValueError, match="Evaluate the article"):
        create_submission(user.id, contest, None)


def test_submit_rejects_invalid_hash(db):
    _creator, contest = active_contest(db)
    user = make_user(db, "Sub")

    with pytest.raises(ValueError, match="Invalid evaluation hash"):
        create_submission(user.id, contest, "not-a-real-token")


def test_submit_rejects_hash_from_another_contest(db):
    _c1, contest1 = active_contest(db, "C1")
    _c2, contest2 = active_contest(db, "C2")
    user = make_user(db, "Sub")
    ev = evaluate_article(contest1, ARTICLE)      # token bound to contest1

    with pytest.raises(ValueError, match="does not match this contest"):
        create_submission(user.id, contest2, ev["hash"])


def test_submit_blocks_duplicate_article(db):
    _creator, contest = active_contest(db)
    user = make_user(db, "Sub")
    submit(contest, user)

    with pytest.raises(ValueError, match="already submitted"):
        submit(contest, user)
    assert Submission.query.count() == 1


# --- list ---

def test_list_all_vs_own(db):
    _creator, contest = active_contest(db)
    a = make_user(db, "A")
    b = make_user(db, "B")
    submit(contest, a, "https://en.wikipedia.org/wiki/A")
    submit(contest, b, "https://en.wikipedia.org/wiki/B")

    assert len(list_contest_submissions(contest.id, all_submissions=True)) == 2
    own = list_contest_submissions(contest.id, viewer_id=a.id)
    assert [s.user_id for s in own] == [a.id]


# --- review ---

def test_review_accept_uses_contest_default_score(db):
    _creator, contest = active_contest(db, marks_setting_accepted=10)
    user = make_user(db, "Sub")
    s = submit(contest, user)

    reviewed = review_submission(s, _creator.id, "accept")

    assert reviewed.status == SubmissionStatus.ACCEPTED.value
    assert reviewed.score == 10
    assert reviewed.reviewed_by == _creator.id
    assert reviewed.reviewed_at is not None


def test_review_accept_with_explicit_score(db):
    _creator, contest = active_contest(db, marks_setting_accepted=10)
    user = make_user(db, "Sub")
    s = submit(contest, user)

    reviewed = review_submission(s, _creator.id, "accept", score=7, review_comment="ok")

    assert reviewed.score == 7
    assert reviewed.review_comment == "ok"


def test_review_reject_uses_rejected_score(db):
    _creator, contest = active_contest(db, marks_setting_rejected=0)
    user = make_user(db, "Sub")
    s = submit(contest, user)

    reviewed = review_submission(s, _creator.id, "reject")

    assert reviewed.status == SubmissionStatus.REJECTED.value
    assert reviewed.score == 0


def test_review_rejects_invalid_decision(db):
    _creator, contest = active_contest(db)
    user = make_user(db, "Sub")
    s = submit(contest, user)

    with pytest.raises(ValueError, match="accept.*reject"):
        review_submission(s, _creator.id, "maybe")


def test_review_blocks_double_review(db):
    _creator, contest = active_contest(db)
    user = make_user(db, "Sub")
    s = submit(contest, user)
    review_submission(s, _creator.id, "accept")

    with pytest.raises(ValueError, match="already been reviewed"):
        review_submission(s, _creator.id, "reject")
