from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    # Primary key
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    username = db.Column(db.String(50), unique=True, nullable=False, index=True)

    user_language = db.Column(db.String(20), default='en')

    # Role-based access control: 'user', 'trusted_member', 'jury', or 'superadmin'
    role = db.Column(db.String(20), nullable=False, default="user")

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
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        """String representation of User instance"""
        return f"<User {self.username}>"


class ContestRequest(db.Model):
    __tablename__ = 'contest_requests'

    # Primary key
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Who is requesting Contest Creator rights
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Why they want the rights
    reason = db.Column(db.Text, nullable=True)  # required only when edit_count < 300

    # Cached Wikimedia edit count at time of request (for 300+ eligibility check)
    edit_count = db.Column(db.Integer, nullable=True)

    # Request workflow status
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)

    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    requester = db.relationship('User', foreign_keys=[user_id], backref='contest_creator_requests')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_contest_creator_requests')

    def to_dict(self):
        """Serialize this contest request for API responses."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.requester.username if self.requester else None,
            "reason": self.reason,
            "edit_count": self.edit_count,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        """String representation of ContestRequest instance"""
        return f"<ContestRequest user_id={self.user_id} status={self.status}>"


class Contest(db.Model):
    __tablename__ = 'contests'

    # Primary key
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Core identity
    name = db.Column(db.String(200), nullable=False)
    project_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Creator (references the user row, not the username -
    # consistent with how ContestRequest.user_id already works)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Schedule
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    # Article eligibility requirements
    min_byte_count = db.Column(db.Integer, nullable=False, default=0)
    min_reference_count = db.Column(db.Integer, nullable=False, default=0)

    # 'new', 'expansion', or 'both'
    allowed_submission_type = db.Column(db.String(20), nullable=False, default='both')

    # Simple fixed-points scoring (always available)
    marks_setting_accepted = db.Column(db.Integer, nullable=False, default=0)
    marks_setting_rejected = db.Column(db.Integer, nullable=False, default=0)

    # Optional multi-parameter scoring config, e.g.
    # {"enabled": true, "parameters": [{"name": "Quality", "weight": 40}, ...]}
    # Uses the DB's native JSON type instead of hand-rolled json.dumps/loads
    # helpers - SQLAlchemy handles the (de)serialization for us.
    scoring_parameters = db.Column(db.JSON, nullable=True)

    # Optional list of MediaWiki category URLs an article must belong to
    categories = db.Column(db.JSON, nullable=True)

    # Optional list of user ids who may organize/jury this contest.
    # Stored as JSON for now (not a join table) to keep this first PR small;
    # can be normalized into proper association tables in a follow-up once
    # routes/permissions for organizers & jury are actually being built.
    organizer_ids = db.Column(db.JSON, nullable=True)
    jury_ids = db.Column(db.JSON, nullable=True)

    template_link = db.Column(db.Text, nullable=True)
    outreach_dashboard_url = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    creator = db.relationship('User', foreign_keys=[created_by], backref='contests_created')

    def __repr__(self):
        """String representation of Contest instance"""
        return f"<Contest {self.name}>"

class Submission(db.Model):
    __tablename__ = 'submissions'

    # Primary key
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Which contest this submission belongs to
    contest_id = db.Column(
        db.Integer,
        db.ForeignKey('contests.id'),
        nullable=False,
        index=True
    )

    # Which user submitted the article
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=False,
        index=True
    )

    # Submitted MediaWiki article URL
    article_url = db.Column(db.Text, nullable=False)

    # Article title extracted/verified from the URL
    article_title = db.Column(db.String(255), nullable=True)

    # Submission lifecycle status
    # pending_validation / pending_review / reviewed / rejected
    status = db.Column(
        db.String(30),
        nullable=False,
        default='pending_validation',
        index=True
    )

    # Pre-validation results
    validation_passed = db.Column(db.Boolean, nullable=False, default=False)
    validation_errors = db.Column(db.JSON, nullable=True)

    # Snapshot of article metrics at submission/validation time
    byte_count = db.Column(db.Integer, nullable=True)
    reference_count = db.Column(db.Integer, nullable=True)

    # Jury review
    reviewed_by = db.Column(
        db.Integer,
        db.ForeignKey('users.id'),
        nullable=True,
        index=True
    )
    reviewed_at = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    # Score awarded after review
    score = db.Column(db.Float, nullable=True)

    # Optional jury feedback/comments
    review_comment = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    contest = db.relationship(
        'Contest',
        foreign_keys=[contest_id],
        backref='submissions'
    )

    participant = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref='submissions'
    )

    reviewer = db.relationship(
        'User',
        foreign_keys=[reviewed_by],
        backref='reviewed_submissions'
    )

    def to_dict(self):
        """Serialize submission for API responses."""
        return {
            "id": self.id,
            "contest_id": self.contest_id,
            "user_id": self.user_id,
            "username": self.participant.username if self.participant else None,
            "article_url": self.article_url,
            "article_title": self.article_title,
            "status": self.status,
            "validation_passed": self.validation_passed,
            "validation_errors": self.validation_errors,
            "byte_count": self.byte_count,
            "reference_count": self.reference_count,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": (
                self.reviewed_at.isoformat()
                if self.reviewed_at else None
            ),
            "score": self.score,
            "review_comment": self.review_comment,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if self.updated_at else None
            ),
        }

    def __repr__(self):
        return f"<Submission id={self.id} contest_id={self.contest_id} user_id={self.user_id}>"    