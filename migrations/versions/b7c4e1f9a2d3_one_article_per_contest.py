"""one article per contest: unique (contest_id, article_link)

Revision ID: b7c4e1f9a2d3
Revises: 9a066c38170e
Create Date: 2026-10-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b7c4e1f9a2d3'
down_revision = '9a066c38170e'
branch_labels = None
depends_on = None

OLD = 'uq_submission_user_contest_article'   # (user_id, contest_id, article_link)
NEW = 'uq_submission_contest_article'        # (contest_id, article_link)


def _duplicate_articles():
    """(contest_id, article_link, count) rows that would violate the new
    constraint — the same article submitted to one contest by several users."""
    rows = op.get_bind().execute(sa.text(
        "SELECT contest_id, article_link, COUNT(*) AS n FROM submissions "
        "GROUP BY contest_id, article_link HAVING COUNT(*) > 1"
    ))
    return [tuple(r) for r in rows]


def upgrade():
    # Refuse (with a readable listing) rather than fail mid-DDL if the data
    # already contains cross-user duplicates. Resolve them manually — deciding
    # which participant keeps the article is an organizer call, not a migration's.
    dupes = _duplicate_articles()
    if dupes:
        listing = "\n".join(f"  contest={c} article={a!r} submissions={n}"
                            for c, a, n in dupes)
        raise RuntimeError(
            "Cannot enforce one-article-per-contest: these articles were "
            "submitted by more than one participant. Remove the extra "
            f"submissions, then re-run the upgrade:\n{listing}")

    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.drop_constraint(OLD, type_='unique')
        batch_op.create_unique_constraint(NEW, ['contest_id', 'article_link'])


def downgrade():
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.drop_constraint(NEW, type_='unique')
        batch_op.create_unique_constraint(OLD, ['user_id', 'contest_id', 'article_link'])
