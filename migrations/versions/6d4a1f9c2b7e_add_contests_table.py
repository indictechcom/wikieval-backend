"""Add contests table (core fields only)

Revision ID: 6d4a1f9c2b7e
Revises: 25066b6f7958
Create Date: 2026-08-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6d4a1f9c2b7e'
down_revision = '25066b6f7958'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('contests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('project_name', sa.String(length=100), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('min_byte_count', sa.Integer(), nullable=False),
    sa.Column('min_reference_count', sa.Integer(), nullable=False),
    sa.Column('template_link', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contests_created_by_id'), ['created_by_id'], unique=False)


def downgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contests_created_by_id'))

    op.drop_table('contests')
