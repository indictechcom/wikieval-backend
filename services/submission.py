import urllib.parse
from datetime import datetime, timezone

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.exc import IntegrityError

from model import ContestStatus, Submission, SubmissionStatus, User, db
from services import editor_prose_delta, mediawiki
from services.audit import log_review, log_stats_update
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


TAKEN_BY_OTHER = ("This article has already been submitted to this contest by "
                  "another participant. Each article can be submitted by one "
                  "participant only.")


def _existing_submission(contest, link):
    """The single submission (any participant) of `link` in `contest`, or None.
    One article per contest is enforced by uq_submission_contest_article."""
    return Submission.query.filter_by(contest_id=contest.id, article_link=link).first()


def _existing_summary(submission):
    """Compact view of a participant's own earlier submission of the same
    article, returned from /evaluate so the UI can offer ignore-or-update."""
    return {
        "id": submission.id,
        "status": submission.status,
        "score": submission.score,
        "already_reviewed": submission.reviewed_at is not None,
        "reviewed_by_username": (submission.reviewer.username
                                 if submission.reviewer else None),
        "reviewed_at": (submission.reviewed_at.isoformat()
                        if submission.reviewed_at else None),
        "submitted_at": (submission.submitted_at.isoformat()
                         if submission.submitted_at else None),
    }


def evaluate_article(contest, article_link, submitter=None, submitter_id=None):
    """Step 1 of the submit flow. Besides the eligibility checks this enforces
    one-article-one-participant: if another participant already submitted the
    link, evaluation fails. If `submitter_id` already submitted it, the result
    carries `existing_submission` so the client can offer to keep the existing
    entry or refresh its stats (see create_submission(update_existing=True))."""
    if contest.status != ContestStatus.ACTIVE.value:
        raise ValueError("Contest is not open for submissions")
    if _submissions_closed(contest):
        raise ValueError("Contest has ended; submissions are closed")
    if not article_link or not article_link.strip():
        raise ValueError("Article link is required")

    link = _normalize_link(article_link)
    existing = _existing_submission(contest, link)
    if (existing is not None and submitter_id is not None
            and existing.user_id != submitter_id):
        raise ValueError(TAKEN_BY_OTHER)

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
    result = {"article_link": link, "article_metadata": metadata, "hash": token}
    if existing is not None and submitter_id is not None:
        result["existing_submission"] = _existing_summary(existing)
    return result


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


def _reset_review(submission):
    """Clear a submission's jury review so it goes back to the pending queue.
    Returns the previous (status, score, parameter_scores, reviewed_by) tuple
    for the audit trail, or None if it had not been reviewed."""
    previous = None
    if submission.status != SubmissionStatus.PENDING.value or submission.reviewed_by:
        previous = (submission.status, submission.score,
                    submission.parameter_scores, submission.reviewed_by)
    submission.status = SubmissionStatus.PENDING.value
    submission.score = 0
    submission.parameter_scores = None
    submission.evaluation_reason = None
    submission.score_breakdown = None
    submission.reviewed_by = None
    submission.reviewed_at = None
    submission.review_comment = None
    return previous


def create_submission(user_id, contest, token, update_existing=False):
    """Step 2 of the submit flow. Creates the submission from the signed
    evaluation. If `user_id` already submitted this article to the contest:
    with update_existing=False this is an error (the client should first show
    the participant the ignore-or-update choice); with update_existing=True the
    existing row's article stats are replaced by the fresh evaluation and any
    jury review is removed, so the article is reviewed again from scratch."""
    data = _load_evaluation(token, contest)

    if contest.status != ContestStatus.ACTIVE.value:
        raise ValueError("Contest is not open for submissions")
    if _submissions_closed(contest):
        raise ValueError("Contest has ended; submissions are closed")

    link = data["article_link"]
    existing = _existing_submission(contest, link)
    if existing is not None:
        if existing.user_id != user_id:
            raise ValueError(TAKEN_BY_OTHER)
        if not update_existing:
            raise ValueError("You have already submitted this article to this contest")
        previous = _reset_review(existing)
        existing.article_metadata = data["article_metadata"]
        db.session.commit()
        log_stats_update(existing, previous)
        return existing

    submission = Submission(
        user_id=user_id,
        contest_id=contest.id,
        article_link=link,
        article_metadata=data["article_metadata"],
        status=SubmissionStatus.PENDING.value,
    )
    db.session.add(submission)
    try:
        db.session.commit()
    except IntegrityError:
        # Another participant submitted the same article between our check and
        # the commit — the (contest, article) unique constraint fired.
        db.session.rollback()
        raise ValueError(TAKEN_BY_OTHER)
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
    existing = _existing_submission(contest, link)
    if existing is not None:
        if existing.user_id != submitter.id:
            raise ValueError(TAKEN_BY_OTHER)
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
        # Concurrent import of the same article — the (contest, article) unique
        # constraint fired after our duplicate pre-check. Treat as a duplicate.
        db.session.rollback()
        raise ValueError("This article has already been submitted to this contest")
    return submission


def add_submission_for(contest, username, article_link):
    """Organizer/superadmin: add a submission on behalf of a participant who
    missed submitting during the campaign. Unlike the normal flow this ignores
    the closed submission window (so missed articles can be added after the end
    date WITHOUT changing the contest dates), but it DOES enforce the contest's
    eligibility rules — so an added article must still qualify. The words-added
    contribution stays scoped to the contest window, so a late add only ever
    credits in-window work."""
    if not username or not username.strip():
        raise ValueError("A submitter username is required")
    if not article_link or not article_link.strip():
        raise ValueError("An article link is required")

    ensure_users([username.strip()])
    submitter = User.query.filter_by(username=username.strip()).first()

    link = _normalize_link(article_link)
    existing = _existing_submission(contest, link)
    if existing is not None:
        if existing.user_id != submitter.id:
            raise ValueError(TAKEN_BY_OTHER)
        raise ValueError("This participant has already submitted this article to this contest")

    metadata = mediawiki.process_article(link, contest)
    check_eligibility(contest, metadata, submitter=submitter.username)
    metadata["submitter_contribution"] = _submitter_contribution(
        contest, link, submitter.username)

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
        db.session.rollback()
        raise ValueError("This article has already been submitted to this contest")
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
