import enum
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _iso_utc(dt):
    """ISO-8601 with an explicit UTC offset.

    Timezone-aware columns come back naive on some backends (MySQL), which would
    serialize without an offset and be misread as *local* time by JS clients.
    Treat any naive value as UTC so the wire format is always unambiguous.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ContestStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"


class SubmissionStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # MediaWiki usernames can be up to 255 chars.
    username = db.Column(db.String(255), unique=True, nullable=False, index=True)
    user_language = db.Column(db.String(20), nullable=False, default='en')
    can_create_contest = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self):
        """Serialize this user for API responses."""
        return {
            "id": self.id,
            "username": self.username,
            "user_language": self.user_language,
            "can_create_contest": self.can_create_contest,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        """String representation of User instance"""
        return f"<User {self.username}>"


class ContestCreationRequest(db.Model):
    __tablename__ = 'contest_creation_requests'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False,
                       default=RequestStatus.PENDING.value, index=True)

    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                            nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN (" + ", ".join(f"'{s.value}'" for s in RequestStatus) + ")",
            name='ck_contest_creation_requests_status',
        ),
    )

    requester = db.relationship('User', foreign_keys=[user_id], backref='contest_creation_requests')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_contest_creation_requests')

    def to_dict(self):
        """Serialize this contest-creation request for API responses."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.requester.username if self.requester else None,
            "reason": self.reason,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        """String representation of ContestCreationRequest instance"""
        return f"<ContestCreationRequest user_id={self.user_id} status={self.status}>"


class Contest(db.Model):
    __tablename__ = 'contests'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    name = db.Column(db.String(200), nullable=False)
    project_name = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False,
                       default=ContestStatus.PENDING.value, index=True)
    description = db.Column(db.Text, nullable=True)
    # Contest window, stored as absolute UTC instants. `timezone` is the IANA
    # zone (e.g. 'Asia/Kolkata') the organizer picked when setting them, so the
    # deadline can be displayed back in that zone. See _iso_utc() for how these
    # serialize with an explicit offset. (This instance attribute shadows nothing
    # — the datetime.timezone import lives in module scope.)
    start_date = db.Column(db.DateTime(timezone=True), nullable=True)
    end_date = db.Column(db.DateTime(timezone=True), nullable=True)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")

    # Contest rules, as a JSON blob. Well-known keys (read via rule()):
    #   min_byte_count (int), min_reference_count (int), min_word_count (int),
    #   allowed_submission_type ('new' | 'expansion' | 'both').
    rules = db.Column(db.JSON, nullable=True)
    marks_setting_accepted = db.Column(db.Integer, nullable=False, default=0)
    marks_setting_rejected = db.Column(db.Integer, nullable=False, default=0)
    scoring_parameters = db.Column(db.JSON, nullable=True)
    automated_settings = db.Column(db.JSON, nullable=True)

    jury_members = db.Column(db.JSON, nullable=True)
    organizers = db.Column(db.JSON, nullable=True)
    project_link = db.Column(db.Text, nullable=True)

    # Metadata
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN (" + ", ".join(f"'{s.value}'" for s in ContestStatus) + ")",
            name='ck_contests_status',
        ),
    )

    creator = db.relationship('User', backref='contests_created')

    def rule(self, key, default=None):
        """Read a rule from the rules JSON blob (e.g. min_byte_count)."""
        return (self.rules or {}).get(key, default)

    def is_organizer(self, username):
        """Whether a username manages this contest (creator is always included)."""
        return username is not None and username in (self.organizers or [])

    def to_dict(self):
        """Serialize this contest for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "project_name": self.project_name,
            "status": self.status,
            "created_by": self.created_by,
            "creator_username": self.creator.username if self.creator else None,
            "description": self.description,
            "start_date": _iso_utc(self.start_date),
            "end_date": _iso_utc(self.end_date),
            "timezone": self.timezone,
            "rules": self.rules,
            "marks_setting_accepted": self.marks_setting_accepted,
            "marks_setting_rejected": self.marks_setting_rejected,
            "scoring_parameters": self.scoring_parameters,
            "automated_settings": self.automated_settings,
            "jury_members": self.jury_members,
            "organizers": self.organizers,
            "project_link": self.project_link,
            "submission_count": db.session.query(db.func.count(Submission.id))
                                          .filter(Submission.contest_id == self.id)
                                          .scalar(),
            "created_at": _iso_utc(self.created_at),
        }

    def __repr__(self):
        """String representation of Contest instance"""
        return f"<Contest {self.name}>"


class Submission(db.Model):
    """A user's article submission to a contest."""
    __tablename__ = 'submissions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Core: who, which contest, and the article. The article title is derived
    # from the link, so only the link is stored.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    contest_id = db.Column(db.Integer, db.ForeignKey('contests.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    # 766 is the max that keeps the (user_id, contest_id, article_link) unique
    # index within MySQL's 3072-byte key limit under utf8mb4 (766*4 + 2 ints).
    # Percent-encoded international titles are long; decode links on write to
    # keep the stored value short.
    article_link = db.Column(db.String(766), nullable=False)

    # Article-derived metadata as a single JSON blob: MediaWiki stats (author,
    # byte count, page id, expansion, links, refs, ...) plus enforcement info
    # such as categories_added and template_added.
    article_metadata = db.Column(db.JSON, nullable=True)

    # Status & scoring
    status = db.Column(db.String(20), nullable=False,
                       default=SubmissionStatus.PENDING.value, index=True)
    score = db.Column(db.Integer, nullable=False, default=0)
    parameter_scores = db.Column(db.JSON, nullable=True)
    evaluation_reason = db.Column(db.Text, nullable=True)
    score_breakdown = db.Column(db.JSON, nullable=True)

    # Review metadata
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                            nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    review_comment = db.Column(db.Text, nullable=True)

    # Metadata
    submitted_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # A user cannot submit the same article to the same contest twice (but may
    # submit different articles).
    __table_args__ = (
        db.UniqueConstraint('user_id', 'contest_id', 'article_link',
                            name='uq_submission_user_contest_article'),
        db.CheckConstraint(
            "status IN (" + ", ".join(f"'{s.value}'" for s in SubmissionStatus) + ")",
            name='ck_submissions_status',
        ),
    )

    submitter = db.relationship('User', foreign_keys=[user_id], backref='submissions')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_submissions')
    contest = db.relationship('Contest', backref='submissions')

    def to_dict(self):
        """Serialize this submission for API responses."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.submitter.username if self.submitter else None,
            "contest_id": self.contest_id,
            "article_link": self.article_link,
            "article_metadata": self.article_metadata,
            "status": self.status,
            "score": self.score,
            "parameter_scores": self.parameter_scores,
            "evaluation_reason": self.evaluation_reason,
            "score_breakdown": self.score_breakdown,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_comment": self.review_comment,
            "already_reviewed": self.reviewed_at is not None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
        }

    def __repr__(self):
        """String representation of Submission instance"""
        return f"<Submission {self.id} contest={self.contest_id} status={self.status}>"
