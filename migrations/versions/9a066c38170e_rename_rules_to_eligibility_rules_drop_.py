"""rename rules to eligibility_rules, drop automated_settings

Revision ID: 9a066c38170e
Revises: 1a0023d3a504
Create Date: 2026-08-23 21:21:43.253205

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '9a066c38170e'
down_revision = '1a0023d3a504'
branch_labels = None
depends_on = None


def upgrade():
    # Rename rules -> eligibility_rules IN PLACE so existing rule data is
    # preserved (autogenerate proposed a drop+add, which would discard it).
    # automated_settings was always unused, so drop it.
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column('rules', new_column_name='eligibility_rules',
                              existing_type=mysql.JSON(), existing_nullable=True)
        batch_op.drop_column('automated_settings')


def downgrade():
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column('eligibility_rules', new_column_name='rules',
                              existing_type=mysql.JSON(), existing_nullable=True)
        batch_op.add_column(sa.Column('automated_settings', mysql.JSON(), nullable=True))
