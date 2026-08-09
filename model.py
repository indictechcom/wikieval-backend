from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    # Primary key
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    username = db.Column(db.String(50), unique=True, nullable=False, index=True)

    user_language = db.Column(db.String(20), default='en')

    # Role-based access control: 'user', 'admin', or 'superadmin'
    role = db.Column(db.String(20), nullable=False, default="user")

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

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

    def __repr__(self):
        """String representation of ContestRequest instance"""
        return f"<ContestRequest user_id={self.user_id} status={self.status}>"


class Contest(db.Model):
    __tablename__ = 'contests'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    name = db.Column(db.String(200), nullable=False)
    project_name = db.Column(db.String(100), nullable=False)

    # References users.id (not username, unlike wikicontest's Contest.created_by)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    min_byte_count = db.Column(db.Integer, nullable=False, default=0)
    min_reference_count = db.Column(db.Integer, nullable=False, default=0)
    template_link = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    creator = db.relationship('User', foreign_keys=[created_by_id], backref='created_contests')

    def __repr__(self):
        """String representation of Contest instance"""
        return f"<Contest {self.id}: {self.name}>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "project_name": self.project_name,
            "created_by_id": self.created_by_id,
            "created_by_username": self.creator.username if self.creator else None,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "min_byte_count": self.min_byte_count,
            "min_reference_count": self.min_reference_count,
            "template_link": self.template_link,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
