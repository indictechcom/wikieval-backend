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
