"""
Service layer for Submission management.
Contains business logic for submitting articles to a contest
(with pre-validation) and for jury review of submissions.
"""

from datetime import date, datetime, timezone

from model import db, Submission, Contest, User
from utils import get_article_info



# CREATE — submit an article, with pre-validation


def create_submission(user_id, contest_id, article_url):
    """
    Submit an article to a contest. Performs pre-validation:
    - contest exists
    - contest is currently active (within start_date/end_date)
    - article URL is well-formed and the article exists
    - article meets the contest's min_byte_count / min_reference_count
    - user hasn't already submitted this exact article to this contest

    The submission is always created (so there's a record of the attempt),
    but its status reflects whether validation passed:
    - validation fails -> status='rejected', validation_errors populated
    - validation passes -> status='pending_review'
    """
    user = db.session.get(User, user_id)
    if not user:
        raise ValueError("User not found")

    contest = db.session.get(Contest, contest_id)
    if not contest:
        raise ValueError("Contest not found")

    if not article_url or not article_url.strip():
        raise ValueError("Article URL is required")
    article_url = article_url.strip()

    # Contest must currently be active
    today = date.today()
    if contest.start_date and today < contest.start_date:
        raise ValueError("This contest has not started yet")
    if contest.end_date and today > contest.end_date:
        raise ValueError("This contest has already ended")

    # No duplicate submissions of the same article by the same user
    # to the same contest
    existing = Submission.query.filter_by(
        contest_id=contest_id, user_id=user_id, article_url=article_url
    ).first()
    if existing:
        raise ValueError("You have already submitted this article to this contest")

    # Fetch article info from MediaWiki for pre-validation
    article_info = get_article_info(article_url)

    validation_errors = []
    article_title = None
    byte_count = None
    reference_count = None

    if article_info is None:
        validation_errors.append("Could not parse or reach the article URL")
    elif not article_info["exists"]:
        validation_errors.append("Article does not exist")
    else:
        article_title = article_info["title"]
        byte_count = article_info["byte_count"]
        reference_count = article_info["reference_count"]

        if contest.min_byte_count and byte_count < contest.min_byte_count:
            validation_errors.append(
                f"Article size ({byte_count} bytes) is below the contest minimum "
                f"({contest.min_byte_count} bytes)"
            )

        if contest.min_reference_count and reference_count < contest.min_reference_count:
            validation_errors.append(
                f"Reference count ({reference_count}) is below the contest minimum "
                f"({contest.min_reference_count})"
            )

    validation_passed = len(validation_errors) == 0
    status = "pending_review" if validation_passed else "rejected"

    submission = Submission(
        contest_id=contest_id,
        user_id=user_id,
        article_url=article_url,
        article_title=article_title,
        status=status,
        validation_passed=validation_passed,
        validation_errors=validation_errors if validation_errors else None,
        byte_count=byte_count,
        reference_count=reference_count,
    )

    db.session.add(submission)
    db.session.commit()

    return submission



# READ


def get_submission(submission_id):
    submission = db.session.get(Submission, submission_id)
    if not submission:
        raise ValueError("Submission not found")
    return submission


def list_submissions_for_contest(contest_id):
    contest = db.session.get(Contest, contest_id)
    if not contest:
        raise ValueError("Contest not found")

    return Submission.query.filter_by(contest_id=contest_id).order_by(
        Submission.created_at.desc()
    ).all()



# REVIEW — jury scores a submission

def _calculate_multi_parameter_score(scoring_config, parameter_scores, max_score):
    """
    Calculate a weighted score from individual parameter scores.

    scoring_config: {"enabled": true, "parameters": [{"name": "Quality", "weight": 40}, ...]}
    parameter_scores: {"Quality": 8, "Sources": 7, ...}  (each 0-10)
    max_score: the contest's marks_setting_accepted, used to scale the final result

    Returns: (final_score: float, error: str or None)
    """
    parameters = scoring_config.get("parameters", [])
    if not parameters:
        return None, "Contest has no scoring parameters configured"

    required_names = [p["name"] for p in parameters]

    for name in required_names:
        if name not in parameter_scores:
            return None, f"Missing score for parameter: {name}"
        value = parameter_scores[name]
        if not isinstance(value, (int, float)):
            return None, f"Score for {name} must be a number"
        if value < 0 or value > 10:
            return None, f"Score for {name} must be between 0 and 10"

    total_weight = sum(p.get("weight", 0) for p in parameters)
    if total_weight == 0:
        return None, "Contest scoring parameters have no valid weights"

    weighted_sum = 0.0
    for p in parameters:
        name = p["name"]
        weight = p.get("weight", 0)
        weighted_sum += parameter_scores[name] * (weight / total_weight)

    # weighted_sum is on a 0-10 scale; scale it to the contest's max_score
    final_score = round(weighted_sum * (max_score / 10), 2)
    return final_score, None


def review_submission(submission_id, reviewer_id, status, score=None, parameter_scores=None, review_comment=None):
    """
    Record a jury review for a submission.

    Supports two scoring modes, based on the contest's configuration:
    - Simple scoring (default): reviewer provides a single score (0 to
      contest.marks_setting_accepted) when accepting.
    - Multi-parameter scoring (when contest.scoring_parameters.enabled is
      True): reviewer provides parameter_scores, and the final score is
      calculated as a weighted average, scaled to marks_setting_accepted.

    In both modes, status='rejected' always uses contest.marks_setting_rejected.
    """
    submission = db.session.get(Submission, submission_id)
    if not submission:
        raise ValueError("Submission not found")

    reviewer = db.session.get(User, reviewer_id)
    if not reviewer:
        raise ValueError("Reviewer not found")

    if submission.status != "pending_review":
        raise ValueError(f"Submission is not awaiting review (current status: {submission.status})")

    if status not in ("accepted", "rejected"):
        raise ValueError("Status must be 'accepted' or 'rejected'")

    contest = db.session.get(Contest, submission.contest_id)
    if not contest:
        raise ValueError("Associated contest not found")

    scoring_config = contest.scoring_parameters or {}
    is_multi_parameter = scoring_config.get("enabled") is True

    if status == "accepted":
        if is_multi_parameter:
            if not parameter_scores or not isinstance(parameter_scores, dict):
                raise ValueError("parameter_scores is required for this contest's scoring mode")

            final_score, error = _calculate_multi_parameter_score(
                scoring_config, parameter_scores, contest.marks_setting_accepted
            )
            if error:
                raise ValueError(error)
            score = final_score
        else:
            if score is None:
                raise ValueError("Score is required when accepting a submission")
            try:
                score = float(score)
            except (TypeError, ValueError):
                raise ValueError("Score must be a number")

            max_score = contest.marks_setting_accepted
            if score < 0 or score > max_score:
                raise ValueError(f"Score must be between 0 and {max_score}")
    else:
        # Rejected submissions always get the contest's configured rejection score
        score = float(contest.marks_setting_rejected)

    submission.status = status
    submission.score = score
    submission.review_comment = review_comment
    submission.reviewed_by = reviewer_id
    submission.reviewed_at = datetime.now(timezone.utc)

    db.session.commit()

    return submission