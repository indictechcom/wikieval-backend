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
    reason = db.Column(db.Text, nullable=False)

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
                
