"""child campaign requests: local organizers request a child under a group campaign

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'child_campaign_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('organizers', sa.JSON(), nullable=True),
        sa.Column('jury_members', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('contest_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')",
                           name='ck_child_campaign_requests_status'),
        sa.ForeignKeyConstraint(['parent_id'], ['contests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['contest_id'], ['contests.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('child_campaign_requests', schema=None) as batch_op:
        batch_op.create_index('ix_child_campaign_requests_parent_id', ['parent_id'])
        batch_op.create_index('ix_child_campaign_requests_user_id', ['user_id'])
        batch_op.create_index('ix_child_campaign_requests_status', ['status'])


def downgrade():
    with op.batch_alter_table('child_campaign_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_child_campaign_requests_status')
        batch_op.drop_index('ix_child_campaign_requests_user_id')
        batch_op.drop_index('ix_child_campaign_requests_parent_id')
    op.drop_table('child_campaign_requests')
