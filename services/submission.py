import urllib.parse
from datetime import datetime, timezone

from flask import current_app
from itsdangerous import BadData, URLSafeSerializer

from model import ContestStatus, Submission, SubmissionStatus, db
from services import mediawiki

_EVALUATION_SALT = "article-evaluation"


def _normalize_link(article_link):
    return urllib.parse.unquote(article_link.strip())


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_EVALUATION_SALT)


def evaluate_article(contest, article_link):
    if contest.status != ContestStatus.ACTIVE.value:
        raise ValueError("Contest is not open for submissions")
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

    # Minimum references (new + reused).
    min_refs = contest.rule("min_reference_count", 0)
    if min_refs:
        total_refs = (metadata.get("ref_new_count") or 0) + (metadata.get("ref_reused_count") or 0)
        if total_refs < min_refs:
            raise ValueError(f"Article must have at least {min_refs} references")

    # Enforce the contest's submission type against the article's creation date:
    # 'new'       -> created on/after the start date;
    # 'expansion' -> existed (created) before the start date.
    sub_type = contest.rule("allowed_submission_type", "both")
    if sub_type in ("new", "expansion") and contest.start_date:
        created = _created_date(metadata.get("created_at"))
        if created is not None:
            if sub_type == "new" and created < contest.start_date:
                raise ValueError(
                    "This contest only accepts newly created articles; this "
                    "article was created before the contest start date"
                )
            if sub_type == "expansion" and created >= contest.start_date:
                raise ValueError(
                    "This contest only accepts expansions of existing articles; "
                    "this article was created on or after the contest start date"
                )


def _created_date(timestamp):
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    except ValueError:
        return None


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


def review_submission(submission, reviewer_id, decision, score=None,
                      review_comment=None, parameter_scores=None):
    if submission.status != SubmissionStatus.PENDING.value:
        raise ValueError("Submission has already been reviewed")

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
    return submission
