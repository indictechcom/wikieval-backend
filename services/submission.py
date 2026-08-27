import urllib.parse
from datetime import datetime, timezone

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.exc import IntegrityError

from model import ContestStatus, Submission, SubmissionStatus, User, db
from services import editor_prose_delta, mediawiki
from services.audit import log_review
from services.eligibility import check_eligibility
from services.user import ensure_users

_EVALUATION_SALT = "article-evaluation"


def _normalize_link(article_link):
    return urllib.parse.unquote(article_link.strip())


def _submitter_contribution(contest, article_link, submitter):
    """Words the submitter authored in this article *during the contest window*
    (start_date → end_date), via the editor-prose delta engine. Returns a
    {'words_added': gross, 'words_net': net} dict, or None on any failure so it
    never blocks submission. This is the per-user contribution — distinct from
    the article's total word_count."""
    if not submitter:
        return None
    try:
        start = contest.start_date.isoformat() if contest.start_date else None
        end = contest.end_date.isoformat() if contest.end_date else None
        report = editor_prose_delta.analyze(
            article_link, start=start, end=end, user=submitter)
        users = report.get("users") or []
        if not users:  # submitter made no edits in the window
            return {"words_added": 0, "words_net": 0}
        u = users[0]
        return {"words_added": u.get("words_added", 0),
                "words_net": u.get("words_net", 0)}
    except Exception:  # noqa: BLE001 — enrichment must never break submission
        return None


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


def evaluate_article(contest, article_link, submitter=None):
    if contest.status != ContestStatus.ACTIVE.value:
        raise ValueError("Contest is not open for submissions")
    if _submissions_closed(contest):
        raise ValueError("Contest has ended; submissions are closed")
    if not article_link or not article_link.strip():
        raise ValueError("Article link is required")

    link = _normalize_link(article_link)
    metadata = mediawiki.process_article(link, contest)
    check_eligibility(contest, metadata, submitter=submitter)

    # Words the submitter authored during the contest window (the per-user delta,
    # not the article's total). Baked into the signed hash like the rest.
    metadata["submitter_contribution"] = _submitter_contribution(contest, link, submitter)

    token = _serializer().dumps({
        "contest_id": contest.id,
        "article_link": link,
        "article_metadata": metadata,
    })
    return {"article_link": link, "article_metadata": metadata, "hash": token}


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
    metadata["submitter_contribution"] = _submitter_contribution(
        contest, link, username.strip())

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
