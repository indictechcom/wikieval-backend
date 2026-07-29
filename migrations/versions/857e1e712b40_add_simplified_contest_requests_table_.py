"""Add simplified contest_requests table (permission request only)

Revision ID: 857e1e712b40
Revises: baeae0ab2536
Create Date: 2026-07-26 00:12:23.912827

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '857e1e712b40'
down_revision = 'baeae0ab2536'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('contest_requests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('edit_count', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contest_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contest_requests_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_contest_requests_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('contest_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contest_requests_user_id'))
        batch_op.drop_index(batch_op.f('ix_contest_requests_status'))

    op.drop_table('contest_requests')
    # ### end Alembic commands ###
