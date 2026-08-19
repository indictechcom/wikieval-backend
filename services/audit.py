"""Audit logging for review actions.

A submission's review (decision, score, comment) is stored only as its *current*
state — editing a review overwrites the previous values. To keep a trail for
conflict investigation, every review action (a first review OR an edit, with the
previous values) is appended to a persistent, human-readable audit log.

Log destination: the ``REVIEW_LOG_PATH`` env var if set, else
``<repo>/logs/reviews.log`` (rotated). Falls back to stdout if that directory
isn't writable (e.g. a read-only deploy), so review actions are never silently
dropped.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

_LOGGER_NAME = "wikieval.reviews"


def _build_logger():
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # keep the audit trail out of the app's stdout logs
    if logger.handlers:  # configure exactly once
        return logger

    path = os.environ.get("REVIEW_LOG_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "logs", "reviews.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5,
                                      encoding="utf-8")
    except OSError:  # directory not writable — don't lose the trail
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    return logger


review_audit = _build_logger()


def log_review(submission, reviewer_id, decision, is_edit, previous=None):
    """Append a review action to the audit log.

    Records both scoring systems: the aggregate `score` (simple scoring) and the
    per-parameter `params` breakdown (multi-parameter scoring), plus the comment.
    `previous` is the (status, score, parameter_scores, reviewed_by) tuple
    captured BEFORE the change — logged only for edits, so a dispute shows the
    full before/after (including which parameter changed) and who changed it.
    """
    review_audit.info(
        "review submission=%s contest=%s reviewer=%s action=%s decision=%s "
        "status=%s score=%s params=%s comment=%r%s",
        submission.id, submission.contest_id, reviewer_id,
        "edit" if is_edit else "new", decision,
        submission.status, submission.score, submission.parameter_scores,
        submission.review_comment or "",
        f" previous={previous}" if (is_edit and previous is not None) else "",
    )
