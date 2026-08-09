"""Add contests table

Revision ID: 044c4a34027b
Revises: 857e1e712b40
Create Date: 2026-08-09 13:55:08.180109

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '044c4a34027b'
down_revision = '25066b6f7958'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('contests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('project_name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('min_byte_count', sa.Integer(), nullable=False),
    sa.Column('min_reference_count', sa.Integer(), nullable=False),
    sa.Column('allowed_submission_type', sa.String(length=20), nullable=False),
    sa.Column('marks_setting_accepted', sa.Integer(), nullable=False),
    sa.Column('marks_setting_rejected', sa.Integer(), nullable=False),
    sa.Column('scoring_parameters', sa.JSON(), nullable=True),
    sa.Column('categories', sa.JSON(), nullable=True),
    sa.Column('organizer_ids', sa.JSON(), nullable=True),
    sa.Column('jury_ids', sa.JSON(), nullable=True),
    sa.Column('template_link', sa.Text(), nullable=True),
    sa.Column('outreach_dashboard_url', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contests_created_by'), ['created_by'], unique=False)


def downgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contests_created_by'))

    op.drop_table('contests')
    # ### end Alembic commands ###
