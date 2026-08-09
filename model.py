import json
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ContestMixin:
    """
    Get/set helpers for Contest's JSON/CSV-encoded fields: rules,
    categories, and scoring_parameters as JSON; jury_members and
    organizers as comma-separated usernames. Ported from wikicontest's
    contest_mixin.py, trimmed to the fields Contest actually has here
    (no automated_settings — that's deferred to the automated-scoring
    engine, which isn't being migrated yet).
    """

    def set_rules(self, rules_dict):
        self.rules = json.dumps(rules_dict) if isinstance(rules_dict, dict) else json.dumps({})

    def get_rules(self):
        if not self.rules:
            return {}
        try:
            return json.loads(self.rules)
        except json.JSONDecodeError:
            return {}

    def set_categories(self, categories_list):
        self.categories = json.dumps(categories_list) if isinstance(categories_list, list) else json.dumps([])

    def get_categories(self):
        if not self.categories:
            return []
        try:
            return json.loads(self.categories)
        except json.JSONDecodeError:
            return []

    def set_scoring_parameters(self, params):
        self.scoring_parameters = json.dumps(params) if isinstance(params, dict) else None

    def get_scoring_parameters(self):
        if not self.scoring_parameters:
            return None
        try:
            return json.loads(self.scoring_parameters)
        except json.JSONDecodeError:
            return None

    def set_jury_members(self, jury_list):
        self.jury_members = ",".join(jury_list) if isinstance(jury_list, list) else ""

    def get_jury_members(self):
        if not self.jury_members:
            return []
        return [username.strip() for username in self.jury_members.split(",") if username.strip()]

    def set_organizers(self, organizers_list):
        """Set organizers from list. The contest creator is always included."""
        unique_organizers = []
        seen = set()
        if isinstance(organizers_list, list):
            for username in organizers_list:
                username = (username or "").strip()
                if username and username not in seen:
                    seen.add(username)
                    unique_organizers.append(username)

        creator_username = self.creator.username if getattr(self, "creator", None) else None
        if creator_username and creator_username not in seen:
            unique_organizers.insert(0, creator_username)

        self.organizers = ",".join(unique_organizers)

    def get_organizers(self):
        if not self.organizers:
            return []
        return [username.strip() for username in self.organizers.split(",") if username.strip()]


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


class Contest(db.Model, ContestMixin):
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

    # JSON dict of contest rules, managed via ContestMixin.set_rules/get_rules
    rules = db.Column(db.Text, nullable=True)

    # JSON array of category URLs, managed via ContestMixin.set_categories/get_categories
    categories = db.Column(db.Text, nullable=True)

    # JSON dict of scoring config, managed via ContestMixin.set_scoring_parameters/get_scoring_parameters
    scoring_parameters = db.Column(db.Text, nullable=True)

    # Comma-separated usernames, managed via ContestMixin.set_jury_members/get_jury_members
    jury_members = db.Column(db.Text, nullable=True)

    # Comma-separated usernames (always includes the creator), managed via ContestMixin.set_organizers/get_organizers
    organizers = db.Column(db.Text, nullable=True)

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
            "rules": self.get_rules(),
            "categories": self.get_categories(),
            "scoring_parameters": self.get_scoring_parameters(),
            "jury_members": self.get_jury_members(),
            "organizers": self.get_organizers(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
