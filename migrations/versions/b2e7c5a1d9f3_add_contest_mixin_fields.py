"""Add contest rules/categories/scoring_parameters/jury_members/organizers columns

Revision ID: b2e7c5a1d9f3
Revises: 6d4a1f9c2b7e
Create Date: 2026-08-09 00:00:00.000001

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2e7c5a1d9f3'
down_revision = '6d4a1f9c2b7e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rules', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('categories', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('scoring_parameters', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('jury_members', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('organizers', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.drop_column('organizers')
        batch_op.drop_column('jury_members')
        batch_op.drop_column('scoring_parameters')
        batch_op.drop_column('categories')
        batch_op.drop_column('rules')
