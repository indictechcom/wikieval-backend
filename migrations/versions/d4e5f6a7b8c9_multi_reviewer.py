"""multiple jury reviews per article: contests.reviews_required + submissions.reviews

Revision ID: d4e5f6a7b8c9
Revises: c3d9f0a1b2e4
Create Date: 2026-11-03 12:00:00.000000

"""
import json

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d9f0a1b2e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        # Every existing contest keeps single-reviewer behaviour.
        batch_op.add_column(sa.Column('reviews_required', sa.Integer(),
                                      nullable=False, server_default='1'))
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reviews', sa.JSON(), nullable=True))

    # Backfill: each already-reviewed submission becomes a one-entry review
    # list mirroring its current aggregate, so edits keep working.
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT s.id, s.reviewed_by, u.username, s.status, s.score, "
        "s.parameter_scores, s.review_comment, s.reviewed_at "
        "FROM submissions s LEFT JOIN users u ON u.id = s.reviewed_by "
        "WHERE s.reviewed_by IS NOT NULL"
    )).fetchall()
    for sid, reviewer_id, username, status, score, params, comment, reviewed_at in rows:
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = None
        entry = {
            "reviewer_id": reviewer_id,
            "reviewer_username": username,
            "decision": "accept" if status == "accepted" else "reject",
            "score": score,
            "parameter_scores": params if status == "accepted" else None,
            "review_comment": comment,
            "reviewed_at": (reviewed_at.isoformat() if hasattr(reviewed_at, "isoformat")
                            else str(reviewed_at)),
        }
        bind.execute(sa.text("UPDATE submissions SET reviews = :r WHERE id = :id"),
                     {"r": json.dumps([entry]), "id": sid})


def downgrade():
    # The aggregate columns were kept in sync, so dropping the list loses only
    # the per-reviewer breakdown of multi-review contests.
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.drop_column('reviews')
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.drop_column('reviews_required')
