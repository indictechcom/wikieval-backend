"""Unit tests for services.submission (evaluate + submit flow)."""

from datetime import datetime, timezone

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


def test_evaluate_rejects_ended_contest(db):
    # End instant is in the past -> the submission window is closed.
    _creator, contest = active_contest(
        db, start_date="2020-01-01", end_date="2020-02-01T00:00:00+00:00"
    )

    with pytest.raises(ValueError, match="Contest has ended"):
        evaluate_article(contest, ARTICLE)


def test_submit_rejects_ended_contest(db):
    # Guard again at submit time, not just evaluate: evaluate while open, then
    # the contest ends before the hash is submitted.
    _creator, contest = active_contest(db, start_date="2020-01-01")
    user = make_user(db, "Editor")
    ev = evaluate_article(contest, ARTICLE)

    contest.end_date = datetime(2020, 2, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="Contest has ended"):
        create_submission(user.id, contest, ev["hash"])


def test_evaluate_allows_future_end_date(db):
    _creator, contest = active_contest(
        db, end_date="2999-01-01T00:00:00+00:00"
    )

    result = evaluate_article(contest, ARTICLE)

    assert result["hash"]


def test_evaluate_requires_link(db):
    _creator, contest = active_contest(db)

    with pytest.raises(ValueError, match="link is required"):
        evaluate_article(contest, "   ")


def test_evaluate_includes_revision_id_and_namespace(db):
    _creator, contest = active_contest(db)

    result = evaluate_article(contest, ARTICLE)

    assert result["article_metadata"]["revision_id"] == 999
    assert result["article_metadata"]["namespace"] == 0


def test_evaluate_includes_submitter_contribution(db):
    # The per-user words-added delta (from the stubbed engine) is attached to
    # the metadata and thus baked into the signed hash.
    _creator, contest = active_contest(db)

    result = evaluate_article(contest, ARTICLE, submitter="Alice")

    contrib = result["article_metadata"]["submitter_contribution"]
    assert contrib == {"words_added": 250, "words_net": 220}


def test_submitter_contribution_zero_when_no_edits_in_window(db, monkeypatch):
    # The engine returns no users (submitter made no edits) -> {added:0, net:0}.
    _creator, contest = active_contest(db)
    monkeypatch.setattr("services.editor_prose_delta.analyze",
                        lambda link, **kw: {"users": []})

    result = evaluate_article(contest, ARTICLE, submitter="Alice")

    assert result["article_metadata"]["submitter_contribution"] == {
        "words_added": 0, "words_net": 0}


def test_submitter_contribution_is_best_effort(db, monkeypatch):
    # If the delta engine raises (network down, article gone), submission must
    # still succeed with submitter_contribution = None (never blocked).
    _creator, contest = active_contest(db)

    def boom(link, **kw):
        raise RuntimeError("engine unavailable")
    monkeypatch.setattr("services.editor_prose_delta.analyze", boom)

    result = evaluate_article(contest, ARTICLE, submitter="Alice")

    assert result["hash"]  # evaluation still succeeded
    assert result["article_metadata"]["submitter_contribution"] is None


def test_evaluate_rejects_below_min_byte_count(db):
    # stub returns byte_count=1234; require more.
    _creator, contest = active_contest(db, eligibility_rules={"min_byte_count": 5000})

    with pytest.raises(ValueError, match="at least 5000 bytes"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_rejects_below_min_reference_count(db):
    # stub returns 3 new + 1 reused = 4 references; require more.
    _creator, contest = active_contest(db, eligibility_rules={"min_reference_count": 10})

    with pytest.raises(ValueError, match="at least 10 references"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_rejects_below_min_word_count(db):
    # stub returns word_count=500; require more.
    _creator, contest = active_contest(db, eligibility_rules={"min_word_count": 1000})

    with pytest.raises(ValueError, match="at least 1000 words"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_hard_fails_when_word_count_unavailable(db, monkeypatch):
    # Contest requires a word minimum but the stat couldn't be fetched (XTools down).
    _creator, contest = active_contest(db, eligibility_rules={"min_word_count": 100})
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "word_count": None},
    )

    with pytest.raises(ValueError, match="[Cc]ould not determine.*word count"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_hard_fails_when_reference_count_unavailable(db, monkeypatch):
    _creator, contest = active_contest(db, eligibility_rules={"min_reference_count": 5})
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "ref_new_count": None, "ref_reused_count": None},
    )

    with pytest.raises(ValueError, match="[Cc]ould not determine.*reference count"):
        evaluate_article(contest, ARTICLE)


def test_evaluate_no_word_rule_ignores_missing_word_count(db, monkeypatch):
    # No min_word_count rule -> a missing word_count must NOT fail.
    _creator, contest = active_contest(db)   # no rules
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "word_count": None, "ref_new_count": None},
    )

    assert evaluate_article(contest, ARTICLE)["hash"]


def test_evaluate_accepts_when_minimums_met(db):
    _creator, contest = active_contest(
        db, eligibility_rules={"min_byte_count": 1000, "min_reference_count": 3, "min_word_count": 300})

    result = evaluate_article(contest, ARTICLE)   # 1234 bytes, 4 refs, 500 words -> OK

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
                             eligibility_rules={"allowed_submission_type": "new"}, start_date="2026-01-01",
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
                             eligibility_rules={"allowed_submission_type": "new"}, start_date="2026-01-01",
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
                             eligibility_rules={"allowed_submission_type": "expansion"}, start_date="2026-01-01",
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
                             eligibility_rules={"allowed_submission_type": "expansion"}, start_date="2026-01-01",
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


def test_same_reviewer_can_edit_their_review(db):
    _creator, contest = active_contest(db, marks_setting_accepted=10)
    user = make_user(db, "Sub")
    s = submit(contest, user)
    review_submission(s, _creator.id, "accept", score=7)
    assert s.status == SubmissionStatus.ACCEPTED.value and s.score == 7

    # the same jury member re-reviews (edits) their decision
    edited = review_submission(s, _creator.id, "reject")
    assert edited.status == SubmissionStatus.REJECTED.value
    assert edited.reviewed_by == _creator.id


def test_review_actions_are_audit_logged(db):
    import logging

    from services.audit import review_audit

    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Capture()
    review_audit.addHandler(handler)
    try:
        _creator, contest = active_contest(db, marks_setting_accepted=10)
        user = make_user(db, "Sub")
        s = submit(contest, user)
        review_submission(s, _creator.id, "accept", score=7)   # first review
        review_submission(s, _creator.id, "reject")            # edit by same jury
    finally:
        review_audit.removeHandler(handler)

    assert any("action=new" in m and "decision=accept" in m for m in captured)
    edit = next(m for m in captured if "action=edit" in m)
    assert "decision=reject" in edit and "previous=" in edit  # keeps the prior state


def test_multi_parameter_review_logs_the_breakdown(db):
    import logging

    from services.audit import review_audit

    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Capture()
    review_audit.addHandler(handler)
    try:
        _creator, contest = active_contest(db, marks_setting_accepted=10)
        user = make_user(db, "Sub")
        s = submit(contest, user)
        review_submission(s, _creator.id, "accept", score=7,
                          parameter_scores={"Quality": 5, "Sources": 2})
    finally:
        review_audit.removeHandler(handler)

    line = next(m for m in captured if "action=new" in m)
    assert "params=" in line and "Quality" in line and "Sources" in line  # breakdown kept


def test_different_jury_cannot_override_review(db):
    _creator, contest = active_contest(db)
    other_juror = make_user(db, "Juror2")
    user = make_user(db, "Sub")
    s = submit(contest, user)
    review_submission(s, _creator.id, "accept")

    with pytest.raises(ValueError, match="another jury member"):
        review_submission(s, other_juror.id, "reject")
