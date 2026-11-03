"""one article per contest (application-enforced; no schema change)

Revision ID: b7c4e1f9a2d3
Revises: 9a066c38170e
Create Date: 2026-10-30 12:00:00.000000

This revision originally replaced the (user_id, contest_id, article_link)
unique constraint with (contest_id, article_link). Production already held
articles submitted by two participants in finished contests, and those past
results must stay as they are, so the rule is enforced by the application
only (services/submission.py checks every new submission, import and
add-on-behalf) and the schema is left unchanged. The revision is kept as a
no-op so environments that already applied it stay on the same history.
"""
from alembic import op  # noqa: F401  (kept for Alembic's import conventions)

# revision identifiers, used by Alembic.
revision = 'b7c4e1f9a2d3'
down_revision = '9a066c38170e'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
