"""rename outreach_dashboard_url to project_link

Revision ID: d2818b636157
Revises: 1f682c76ff9e
Create Date: 2026-08-14 20:37:57.260706

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'd2818b636157'
down_revision = '1f682c76ff9e'
branch_labels = None
depends_on = None


def upgrade():
    # Rename in place so existing URLs are preserved (autogenerate proposed a
    # drop+add, which would have discarded the data).
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column(
            'outreach_dashboard_url',
            new_column_name='project_link',
            existing_type=mysql.TEXT(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column(
            'project_link',
            new_column_name='outreach_dashboard_url',
            existing_type=mysql.TEXT(),
            existing_nullable=True,
        )
