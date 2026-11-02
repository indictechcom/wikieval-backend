"""campaign hierarchy: contests.is_group + contests.parent_id

Revision ID: c3d9f0a1b2e4
Revises: b7c4e1f9a2d3
Create Date: 2026-11-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c3d9f0a1b2e4'
down_revision = 'b7c4e1f9a2d3'
branch_labels = None
depends_on = None


def upgrade():
    # Both columns are additive with safe defaults, so every existing contest
    # stays a standalone (individual) campaign: is_group=false, parent_id=NULL.
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_group', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_contests_parent_id', ['parent_id'])
        batch_op.create_foreign_key('fk_contests_parent_id', 'contests',
                                    ['parent_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.drop_constraint('fk_contests_parent_id', type_='foreignkey')
        batch_op.drop_index('ix_contests_parent_id')
        batch_op.drop_column('parent_id')
        batch_op.drop_column('is_group')
