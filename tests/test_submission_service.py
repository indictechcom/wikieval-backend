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


def test_evaluate_skips_reference_rule_when_count_unavailable(db, monkeypatch):
    # XTools (the source of reference counts) is optional: when it is down the
    # counts are None and the min_reference_count rule must NOT block submission.
    _creator, contest = active_contest(db, eligibility_rules={"min_reference_count": 5})
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "ref_new_count": None, "ref_reused_count": None},
    )

    result = evaluate_article(contest, ARTICLE)
    assert result["article_metadata"]["ref_new_count"] is None


def test_evaluate_enforces_reference_rule_when_count_known(db, monkeypatch):
    _creator, contest = active_contest(db, eligibility_rules={"min_reference_count": 5})
    monkeypatch.setattr(
        "services.mediawiki.process_article",
        lambda link, contest=None: {"namespace": 0, "ref_new_count": 2, "ref_reused_count": 1},
    )

    with pytest.raises(ValueError, match="at least 5 references"):
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


# --- one article per contest (any participant) ---

def test_evaluate_blocks_article_taken_by_another_participant(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    bob = make_user(db, "Bob")
    submit(contest, alice)

    with pytest.raises(ValueError, match="another participant"):
        evaluate_article(contest, ARTICLE, submitter="Bob", submitter_id=bob.id)


def test_evaluate_without_submitter_does_not_block(db):
    # No submitter identity → evaluate can't tell whose it is; create decides.
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    submit(contest, alice)

    assert evaluate_article(contest, ARTICLE)["hash"]


def test_create_blocks_article_taken_by_another_participant(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    bob = make_user(db, "Bob")
    submit(contest, alice)
    ev = evaluate_article(contest, ARTICLE)   # hash minted without identity

    with pytest.raises(ValueError, match="another participant"):
        create_submission(bob.id, contest, ev["hash"])
    assert Submission.query.count() == 1


def test_create_update_flag_cannot_take_over_another_participants_article(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    bob = make_user(db, "Bob")
    submit(contest, alice)
    ev = evaluate_article(contest, ARTICLE)

    with pytest.raises(ValueError, match="another participant"):
        create_submission(bob.id, contest, ev["hash"], update_existing=True)


def test_evaluate_reports_own_existing_submission(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    first = submit(contest, alice)
    review_submission(first, _creator.id, "accept", score=7)

    result = evaluate_article(contest, ARTICLE, submitter="Alice", submitter_id=alice.id)

    existing = result["existing_submission"]
    assert existing["id"] == first.id
    assert existing["status"] == "accepted"
    assert existing["score"] == 7
    assert existing["already_reviewed"] is True
    assert existing["reviewed_by_username"] == "Creator"
    assert result["hash"]   # still usable for the update


def test_evaluate_omits_existing_when_none(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")

    result = evaluate_article(contest, ARTICLE, submitter="Alice", submitter_id=alice.id)

    assert "existing_submission" not in result


def test_update_existing_refreshes_stats_and_removes_review(db, monkeypatch):
    from services import mediawiki as mediawiki_module

    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    first = submit(contest, alice)
    review_submission(first, _creator.id, "accept", score=7, review_comment="good",
                      parameter_scores={"Quality": 7})
    original_submitted_at = first.submitted_at

    # The article grew since the first submission.
    real = mediawiki_module.process_article
    monkeypatch.setattr(
        mediawiki_module, "process_article",
        lambda link, contest=None: {**real(link, contest), "word_count": 900})

    ev = evaluate_article(contest, ARTICLE, submitter="Alice", submitter_id=alice.id)
    updated = create_submission(alice.id, contest, ev["hash"], update_existing=True)

    assert updated.id == first.id                     # same row, no duplicate
    assert Submission.query.count() == 1
    assert updated.article_metadata["word_count"] == 900
    assert updated.status == SubmissionStatus.PENDING.value
    assert updated.score == 0
    assert updated.parameter_scores is None
    assert updated.review_comment is None
    assert updated.reviewed_by is None
    assert updated.reviewed_at is None
    assert updated.submitted_at == original_submitted_at


def test_update_existing_on_pending_submission_just_refreshes(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    first = submit(contest, alice)

    ev = evaluate_article(contest, ARTICLE, submitter="Alice", submitter_id=alice.id)
    updated = create_submission(alice.id, contest, ev["hash"], update_existing=True)

    assert updated.id == first.id
    assert updated.status == SubmissionStatus.PENDING.value
    assert Submission.query.count() == 1


def test_update_existing_without_prior_submission_creates_normally(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")

    ev = evaluate_article(contest, ARTICLE, submitter="Alice", submitter_id=alice.id)
    created = create_submission(alice.id, contest, ev["hash"], update_existing=True)

    assert created.id and Submission.query.count() == 1


def test_update_existing_is_audit_logged(db):
    import logging
    from services.audit import review_audit

    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Capture()
    review_audit.addHandler(handler)
    try:
        _creator, contest = active_contest(db)
        alice = make_user(db, "Alice")
        first = submit(contest, alice)
        review_submission(first, _creator.id, "accept", score=7)
        ev = evaluate_article(contest, ARTICLE, submitter="Alice", submitter_id=alice.id)
        create_submission(alice.id, contest, ev["hash"], update_existing=True)
    finally:
        review_audit.removeHandler(handler)

    line = next(m for m in captured if m.startswith("stats-update"))
    assert f"submission={first.id}" in line
    assert "review_removed=True" in line
    assert "'accepted'" in line and "7" in line   # previous review preserved in log


def test_same_user_different_article_still_allowed(db):
    _creator, contest = active_contest(db)
    alice = make_user(db, "Alice")
    submit(contest, alice, "https://en.wikipedia.org/wiki/Cat")
    submit(contest, alice, "https://en.wikipedia.org/wiki/Dog")
    assert Submission.query.count() == 2


def test_same_article_allowed_in_different_contests(db):
    _creator, contest1 = active_contest(db, "C1")
    _c2, contest2 = active_contest(db, "C2")
    alice = make_user(db, "Alice")
    bob = make_user(db, "Bob")
    submit(contest1, alice)
    submit(contest2, bob)
    assert Submission.query.count() == 2


# --- multiple jury reviews per article (contest.reviews_required > 1) ---

def _multi_contest(db, required=2, **fields):
    return active_contest(db, reviews_required=required, marks_setting_accepted=10, **fields)


def test_default_contest_requires_one_review(db):
    _creator, contest = active_contest(db)
    assert contest.reviews_required == 1
    assert contest.to_dict()["reviews_required"] == 1


def test_reviews_required_validation(db):
    user = make_user(db, "U", can_create=True)
    from services.contest import create_contest
    for bad in (0, -1, 1.5, "2", True):
        with pytest.raises(ValueError, match="reviews_required"):
            create_contest(user.id, "C", "commons", start_date="2026-01-01",
                           marks_setting_accepted=10, reviews_required=bad)


def test_single_review_contest_mirrors_entry(db):
    _creator, contest = active_contest(db)
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, _creator.id, "accept", score=7, review_comment="ok")
    d = s.to_dict()
    assert d["review_count"] == 1 and d["already_reviewed"] is True
    assert d["reviews"][0]["reviewer_username"] == "Creator"
    assert d["reviews"][0]["decision"] == "accept" and d["reviews"][0]["score"] == 7
    assert s.status == "accepted" and s.score == 7


def test_first_of_two_reviews_keeps_pending(db):
    creator, contest = _multi_contest(db)
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=8)

    assert s.status == SubmissionStatus.PENDING.value
    assert s.score == 0 and s.reviewed_at is None
    d = s.to_dict()
    assert d["review_count"] == 1 and d["already_reviewed"] is False


def test_two_accepts_average_the_score(db):
    creator, contest = _multi_contest(db)
    j2 = make_user(db, "J2")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=8)
    review_submission(s, j2.id, "accept", score=5)

    assert s.status == "accepted"
    assert s.score == 7            # 6.5 rounds half-up
    assert s.reviewed_at is not None
    assert s.to_dict()["already_reviewed"] is True


def test_average_rounding(db):
    creator, contest = _multi_contest(db, required=3)
    j2, j3 = make_user(db, "J2"), make_user(db, "J3")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=10)
    review_submission(s, j2.id, "accept", score=9)
    review_submission(s, j3.id, "accept", score=9)
    assert s.score == 9           # 28/3 = 9.33


def test_tie_stays_pending_until_a_third_review(db):
    creator, contest = _multi_contest(db)
    j2, j3 = make_user(db, "J2"), make_user(db, "J3")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=8)
    review_submission(s, j2.id, "reject")
    assert s.status == SubmissionStatus.PENDING.value and s.score == 0

    review_submission(s, j3.id, "accept", score=6)      # breaks the tie
    assert s.status == "accepted"
    assert s.score == 7                                  # avg of the two accepts only


def test_reject_majority_scores_rejected_marks(db):
    creator, contest = _multi_contest(db, required=3, marks_setting_rejected=-2)
    j2, j3 = make_user(db, "J2"), make_user(db, "J3")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=8)
    review_submission(s, j2.id, "reject")
    review_submission(s, j3.id, "reject")
    assert s.status == "rejected" and s.score == -2
    assert s.parameter_scores is None


def test_parameter_scores_are_averaged_over_agreeing_reviews(db):
    creator, contest = _multi_contest(db)
    j2 = make_user(db, "J2")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=7,
                      parameter_scores={"Quality": 4, "Sources": 3})
    review_submission(s, j2.id, "accept", score=5,
                      parameter_scores={"Quality": 3, "Sources": 2})
    assert s.parameter_scores == {"Quality": 3.5, "Sources": 2.5}
    assert s.score == 6


def test_extra_reviewer_blocked_once_final(db):
    creator, contest = _multi_contest(db)
    j2, j3 = make_user(db, "J2"), make_user(db, "J3")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=8)
    review_submission(s, j2.id, "accept", score=6)
    with pytest.raises(ValueError, match="already has its 2 required reviews"):
        review_submission(s, j3.id, "reject")


def test_reviewer_edits_own_entry_not_a_second_one(db):
    creator, contest = _multi_contest(db)
    j2 = make_user(db, "J2")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=8)
    review_submission(s, creator.id, "accept", score=4)      # edit
    assert s.to_dict()["review_count"] == 1
    assert s.status == SubmissionStatus.PENDING.value       # still needs J2

    review_submission(s, j2.id, "accept", score=4)
    assert s.status == "accepted" and s.score == 4
    review_submission(s, creator.id, "reject")                # edit after final → tie
    assert s.status == SubmissionStatus.PENDING.value


def test_stats_update_clears_all_reviews(db):
    creator, contest = _multi_contest(db)
    alice = make_user(db, "Alice")
    first = submit(contest, alice)
    review_submission(first, creator.id, "accept", score=8)
    ev = evaluate_article(contest, ARTICLE, submitter="Alice", submitter_id=alice.id)
    updated = create_submission(alice.id, contest, ev["hash"], update_existing=True)
    assert updated.reviews is None and updated.to_dict()["review_count"] == 0


def test_parameter_average_ignores_reviews_without_breakdown(db):
    creator, contest = _multi_contest(db)
    j2 = make_user(db, "J2")
    s = submit(contest, make_user(db, "Sub"))
    review_submission(s, creator.id, "accept", score=6, parameter_scores={"Quality": 6})
    review_submission(s, j2.id, "accept", score=4)              # simple review, no breakdown
    assert s.parameter_scores == {"Quality": 6}
    assert s.score == 5


def test_leaderboard_with_multiple_reviews(db):
    from services.contest import get_leaderboard
    creator, contest = _multi_contest(db)
    j2 = make_user(db, "J2")
    alice = make_user(db, "Alice")
    partial = submit(contest, alice, "https://en.wikipedia.org/wiki/A")
    done = submit(contest, alice, "https://en.wikipedia.org/wiki/B")
    review_submission(partial, creator.id, "accept", score=8)    # 1 of 2 → still pending
    review_submission(done, creator.id, "accept", score=8)
    review_submission(done, j2.id, "accept", score=5)            # final: avg 6.5 → 7

    [row] = get_leaderboard(contest)
    assert row["username"] == "Alice"
    assert row["total_submissions"] == 2
    assert row["reviewed_count"] == 1        # only the final one
    assert row["pending_count"] == 1
    assert row["total_marks"] == 7           # pending contributes 0
