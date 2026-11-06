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
            "reviewed_at": _iso_utc(self.reviewed_at),
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        """String representation of ContestCreationRequest instance"""
        return f"<ContestCreationRequest user_id={self.user_id} status={self.status}>"


class ChildCampaignRequest(db.Model):
    """A request, made on a group campaign's page, to create a child campaign
    under it. The requester supplies only the child's name, its local
    organizers and (optionally) its jury; everything else (project, dates,
    eligibility rules, scoring) is copied from the group on approval. Reviewed
    by the group's organizers, not by superadmins."""
    __tablename__ = 'child_campaign_requests'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('contests.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    organizers = db.Column(db.JSON, nullable=True)
    jury_members = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20), nullable=False,
                       default=RequestStatus.PENDING.value, index=True)

    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'),
                            nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    # The child campaign created on approval.
    contest_id = db.Column(db.Integer, db.ForeignKey('contests.id', ondelete='SET NULL'),
                           nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN (" + ", ".join(f"'{s.value}'" for s in RequestStatus) + ")",
            name='ck_child_campaign_requests_status',
        ),
    )

    parent = db.relationship('Contest', foreign_keys=[parent_id],
                             backref=db.backref('child_requests', cascade='all, delete-orphan'))
    contest = db.relationship('Contest', foreign_keys=[contest_id])
    requester = db.relationship('User', foreign_keys=[user_id],
                                backref='child_campaign_requests')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])

    def to_dict(self):
        """Serialize this child-campaign request for API responses."""
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "parent_name": self.parent.name if self.parent else None,
            "user_id": self.user_id,
            "username": self.requester.username if self.requester else None,
            "name": self.name,
            "organizers": list(self.organizers or []),
            "jury_members": list(self.jury_members or []),
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewer_username": self.reviewer.username if self.reviewer else None,
            "reviewed_at": _iso_utc(self.reviewed_at),
            "rejection_reason": self.rejection_reason,
            "contest_id": self.contest_id,
            "contest_name": self.contest.name if self.contest else None,
            "created_at": _iso_utc(self.created_at),
        }

    def __repr__(self):
        """String representation of ChildCampaignRequest instance"""
        return f"<ChildCampaignRequest parent_id={self.parent_id} name={self.name!r} status={self.status}>"


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

    # Article-submission ELIGIBILITY rules, as a JSON dict {rule_key: value}
    # (see services/eligibility.py for the catalog). Enforced at /evaluate.
    # Separate from scoring (marks_setting_* / scoring_parameters).
    #   e.g. {"min_byte_count": 500, "min_word_count": 300,
    #         "allowed_submission_type": "new", "author_only": true}
    eligibility_rules = db.Column(db.JSON, nullable=True)
    marks_setting_accepted = db.Column(db.Integer, nullable=False, default=0)
    marks_setting_rejected = db.Column(db.Integer, nullable=False, default=0)
    scoring_parameters = db.Column(db.JSON, nullable=True)
    # How many jury reviews an article needs before its result is final.
    # 1 (default, and every pre-existing contest) = a single jury member's
    # review is final, as before. 2+ = each article collects that many
    # independent reviews; the majority decision wins (a tie stays pending for
    # one more reviewer) and the score is the average of the agreeing reviews.
    reviews_required = db.Column(db.Integer, nullable=False, default=1,
                                 server_default="1")

    jury_members = db.Column(db.JSON, nullable=True)
    organizers = db.Column(db.JSON, nullable=True)
    project_link = db.Column(db.Text, nullable=True)

    # Campaign hierarchy (two levels). A *group* campaign is a parent that takes
    # no submissions itself; it holds child campaigns (one per community,
    # language or project) and shows their aggregated progress. A child is an
    # ordinary contest with `parent_id` set. Contests with neither (the
    # pre-existing ones) are standalone "individual" campaigns, so older rows
    # need no backfill: is_group defaults to false and parent_id to NULL.
    is_group = db.Column(db.Boolean, nullable=False, default=False,
                         server_default=db.false())
    parent_id = db.Column(db.Integer,
                          db.ForeignKey('contests.id', ondelete='SET NULL'),
                          nullable=True, index=True)

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
    parent = db.relationship('Contest', remote_side=[id], backref='children',
                             foreign_keys=[parent_id])

    def rule(self, key, default=None):
        """Read an eligibility rule value (e.g. min_byte_count)."""
        return (self.eligibility_rules or {}).get(key, default)

    def is_organizer(self, username):
        """Whether a username manages this contest (creator is always included).
        Organizers of a group campaign implicitly manage every child under it,
        so a child's organizer can't lock the group's organizers out."""
        if username is None:
            return False
        if username in (self.organizers or []):
            return True
        return self.parent is not None and self.parent.is_organizer(username)

    def effective_organizers(self):
        """Own organizers plus (for a child) the parent group's organizers."""
        own = list(self.organizers or [])
        if self.parent is not None:
            own += [u for u in (self.parent.organizers or []) if u not in own]
        return own

    def children_window(self):
        """(earliest start, latest end) across a group's children, or (None,
        None). Lets the UI place a group in Current/Upcoming/Past by what its
        children are actually doing rather than its own informational dates."""
        if not self.is_group or not self.children:
            return None, None
        starts = [c.start_date for c in self.children if c.start_date]
        ends = [c.end_date for c in self.children if c.end_date]
        # Open-ended child (no end) → the group is open-ended too.
        open_ended = any(c.end_date is None for c in self.children)
        return (min(starts) if starts else None,
                None if open_ended else (max(ends) if ends else None))

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
            "eligibility_rules": self.eligibility_rules,
            "marks_setting_accepted": self.marks_setting_accepted,
            "marks_setting_rejected": self.marks_setting_rejected,
            "scoring_parameters": self.scoring_parameters,
            "reviews_required": self.reviews_required or 1,
            "jury_members": self.jury_members,
            "organizers": self.organizers,
            "project_link": self.project_link,
            "is_group": bool(self.is_group),
            "parent_id": self.parent_id,
            "parent_name": self.parent.name if self.parent else None,
            "child_count": len(self.children) if self.is_group else 0,
            "effective_organizers": self.effective_organizers(),
            "children_start_date": _iso_utc(self.children_window()[0]),
            "children_end_date": _iso_utc(self.children_window()[1]),
            # A group's count is the sum over its children (it has none itself).
            "submission_count": self._submission_count(),
            "created_at": _iso_utc(self.created_at),
        }

    def _submission_count(self):
        count = db.session.query(db.func.count(Submission.id))
        if self.is_group:
            return count.filter(Submission.contest_id.in_(
                db.session.query(Contest.id).filter(Contest.parent_id == self.id)
            )).scalar()
        return count.filter(Submission.contest_id == self.id).scalar()

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
    # 766 keeps the (user_id, contest_id, article_link) unique index within
    # MySQL's 3072-byte key limit under utf8mb4 (766*4 + 2 ints).
    # Percent-encoded international titles are long; decode links on write to
    # keep the stored value short.
    article_link = db.Column(db.String(766), nullable=False)

    # Article-derived metadata as a single JSON blob: MediaWiki stats (author,
    # byte count, page id, expansion, links, refs, ...) plus enforcement info
    # such as categories_added and template_added.
    article_metadata = db.Column(db.JSON, nullable=True)

    # Every jury review of this submission, one entry per jury member:
    #   {reviewer_id, reviewer_username, decision, score, parameter_scores,
    #    review_comment, reviewed_at}
    # The status/score/reviewed_* columns below are the AGGREGATE derived from
    # these (services.submission._recompute_review): with the contest's
    # reviews_required == 1 the aggregate simply mirrors the single entry.
    reviews = db.Column(db.JSON, nullable=True)

    # Status & scoring (aggregate of `reviews`)
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

    # One article per contest, by one participant only, is enforced by the
    # application (services/submission.py) for every new submission, so past
    # contests that already contain cross-user duplicates are left untouched.
    # The DB constraint only guards the per-user case (a submitter may
    # re-evaluate their article to refresh its stats, never add a second row).
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
            "reviewed_by_username": self.reviewer.username if self.reviewer else None,
            "reviewed_at": _iso_utc(self.reviewed_at),
            "review_comment": self.review_comment,
            # Final (enough reviews, no tie). Pending-with-some-reviews shows as
            # already_reviewed=false with review_count > 0.
            "already_reviewed": self.reviewed_at is not None,
            "reviews": list(self.reviews or []),
            "review_count": len(self.reviews or []),
            "reviews_required": (self.contest.reviews_required or 1) if self.contest else 1,
            # _iso_utc: DB backends hand back naive instants; serialize with an
            # explicit UTC offset so the browser doesn't read them as local time.
            "submitted_at": _iso_utc(self.submitted_at),
        }

    def __repr__(self):
        """String representation of Submission instance"""
        return f"<Submission {self.id} contest={self.contest_id} status={self.status}>"
