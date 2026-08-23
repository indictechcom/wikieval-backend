import urllib.parse
from datetime import datetime, timezone

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.exc import IntegrityError

from model import ContestStatus, Submission, SubmissionStatus, User, db
from services import mediawiki
from services.audit import log_review
from services.user import ensure_users

_EVALUATION_SALT = "article-evaluation"


def _normalize_link(article_link):
    return urllib.parse.unquote(article_link.strip())


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_EVALUATION_SALT)


def _as_utc(dt):
    """Treat a naive datetime as UTC; return aware datetimes unchanged."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _submissions_closed(contest):
    """Whether the contest window has closed (its end instant has passed)."""
    end = _as_utc(contest.end_date)
    return end is not None and datetime.now(timezone.utc) > end


def evaluate_article(contest, article_link):
    if contest.status != ContestStatus.ACTIVE.value:
        raise ValueError("Contest is not open for submissions")
    if _submissions_closed(contest):
        raise ValueError("Contest has ended; submissions are closed")
    if not article_link or not article_link.strip():
        raise ValueError("Article link is required")

    link = _normalize_link(article_link)
    metadata = mediawiki.process_article(link, contest)
    _check_eligibility(contest, metadata)

    token = _serializer().dumps({
        "contest_id": contest.id,
        "article_link": link,
        "article_metadata": metadata,
    })
    return {"article_link": link, "article_metadata": metadata, "hash": token}


def _check_eligibility(contest, metadata):
    # Only main-namespace (article) pages — reject Talk:, User:, Category:, etc.
    if metadata.get("namespace") != 0:
        raise ValueError("Only main-namespace (article) pages can be submitted")

    # Minimum article size (bytes).
    min_bytes = contest.rule("min_byte_count", 0)
    if min_bytes and (metadata.get("byte_count") or 0) < min_bytes:
        raise ValueError(f"Article must be at least {min_bytes} bytes")

    # Minimum references (total = unique + reused). If the stat can't be
    # determined (e.g. XTools unavailable), fail hard rather than let it through.
    min_refs = contest.rule("min_reference_count", 0)
    if min_refs:
        if metadata.get("ref_new_count") is None:
            raise ValueError("Could not determine the article's reference count; please try again")
        total_refs = (metadata.get("ref_new_count") or 0) + (metadata.get("ref_reused_count") or 0)
        if total_refs < min_refs:
            raise ValueError(f"Article must have at least {min_refs} references")

    # Minimum readable-prose word count.
    min_words = contest.rule("min_word_count", 0)
    if min_words:
        word_count = metadata.get("word_count")
        if word_count is None:
            raise ValueError("Could not determine the article's word count; please try again")
        if word_count < min_words:
            raise ValueError(f"Article must have at least {min_words} words")

    # Enforce the contest's submission type against the article's creation date:
    # 'new'       -> created on/after the start date;
    # 'expansion' -> existed (created) before the start date.
    sub_type = contest.rule("allowed_submission_type", "both")
    start = _as_utc(contest.start_date)
    if sub_type in ("new", "expansion") and start:
        created = _created_instant(metadata.get("created_at"))
        if created is not None:
            if sub_type == "new" and created < start:
                raise ValueError(
                    "This contest only accepts newly created articles; this "
                    "article was created before the contest start date"
                )
            if sub_type == "expansion" and created >= start:
                raise ValueError(
                    "This contest only accepts expansions of existing articles; "
                    "this article was created on or after the contest start date"
                )


def _created_instant(timestamp):
    """The article's creation timestamp as a UTC-aware datetime."""
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(dt)


def _load_evaluation(token, contest):
    if not token:
        raise ValueError("Evaluate the article before submitting")
    try:
        data = _serializer().loads(token)
    except BadData:
        raise ValueError("Invalid evaluation hash. Re-evaluate the article.")
    if data.get("contest_id") != contest.id:
        raise ValueError("Evaluation hash does not match this contest")
    return data


def get_submission(submission_id):
    return db.session.get(Submission, submission_id)


def list_contest_submissions(contest_id, viewer_id=None, all_submissions=False):
    query = Submission.query.filter_by(contest_id=contest_id)
    if not all_submissions:
        query = query.filter_by(user_id=viewer_id)
    return query.order_by(
        Submission.submitted_at.desc(), Submission.id.desc()
    ).all()


def create_submission(user_id, contest, token):
    data = _load_evaluation(token, contest)

    if contest.status != ContestStatus.ACTIVE.value:
        raise ValueError("Contest is not open for submissions")
    if _submissions_closed(contest):
        raise ValueError("Contest has ended; submissions are closed")

    link = data["article_link"]
    existing = Submission.query.filter_by(
        user_id=user_id, contest_id=contest.id, article_link=link
    ).first()
    if existing is not None:
        raise ValueError("You have already submitted this article to this contest")

    submission = Submission(
        user_id=user_id,
        contest_id=contest.id,
        article_link=link,
        article_metadata=data["article_metadata"],
        status=SubmissionStatus.PENDING.value,
    )
    db.session.add(submission)
    db.session.commit()
    return submission


def import_submission(contest, username, article_link):
    """Superadmin restore: create one submission for `username` from an exported
    row. Unlike the normal flow this bypasses the tamper-proof hash and
    eligibility checks (it restores already-accepted data), always lands as
    `pending` (reviews are re-done), and re-fetches the article's metadata so the
    imported submission is fully functional. One article per call keeps each
    request fast (no bulk timeout)."""
    if not username or not username.strip():
        raise ValueError("A submitter username is required")
    if not article_link or not article_link.strip():
        raise ValueError("An article link is required")

    # Create the submitter's User row if it doesn't exist yet (e.g. after a DB
    # reset, before they log in), then resolve their id.
    ensure_users([username.strip()])
    submitter = User.query.filter_by(username=username.strip()).first()

    link = _normalize_link(article_link)
    existing = Submission.query.filter_by(
        user_id=submitter.id, contest_id=contest.id, article_link=link
    ).first()
    if existing is not None:
        raise ValueError("This article was already imported for this submitter")

    metadata = mediawiki.process_article(link, contest)

    submission = Submission(
        user_id=submitter.id,
        contest_id=contest.id,
        article_link=link,
        article_metadata=metadata,
        status=SubmissionStatus.PENDING.value,
    )
    db.session.add(submission)
    try:
        db.session.commit()
    except IntegrityError:
        # Concurrent import of the same (submitter, article) — the unique
        # constraint fired after our duplicate pre-check. Treat as a duplicate.
        db.session.rollback()
        raise ValueError("This article was already imported for this submitter")
    return submission


def review_submission(submission, reviewer_id, decision, score=None,
                      review_comment=None, parameter_scores=None):
    # A pending submission can be reviewed by any jury member; an already-reviewed
    # one may be edited only by the jury member who reviewed it (not overridden
    # by a different jury member).
    already_reviewed = submission.status != SubmissionStatus.PENDING.value
    if (already_reviewed and submission.reviewed_by is not None
            and submission.reviewed_by != reviewer_id):
        raise ValueError("This submission was already reviewed by another jury member")

    # Capture the pre-edit state for the audit trail (an edit overwrites it) —
    # includes parameter_scores so multi-parameter reviews keep their breakdown.
    previous = ((submission.status, submission.score,
                 submission.parameter_scores, submission.reviewed_by)
                if already_reviewed else None)

    contest = submission.contest
    if decision == "accept":
        submission.status = SubmissionStatus.ACCEPTED.value
        submission.score = score if score is not None else (contest.marks_setting_accepted or 0)
    elif decision == "reject":
        submission.status = SubmissionStatus.REJECTED.value
        submission.score = contest.marks_setting_rejected or 0
    else:
        raise ValueError("decision must be 'accept' or 'reject'")

    submission.parameter_scores = parameter_scores
    submission.review_comment = review_comment
    submission.reviewed_by = reviewer_id
    submission.reviewed_at = datetime.now(timezone.utc)
    db.session.commit()
    log_review(submission, reviewer_id, decision, is_edit=already_reviewed, previous=previous)
    return submission
