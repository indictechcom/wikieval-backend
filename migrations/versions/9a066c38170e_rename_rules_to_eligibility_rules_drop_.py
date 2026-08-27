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


def _strip_json_check(column):
    """Remove the inline CHECK(json_valid(col)) that MariaDB attaches to a JSON
    column (it's part of the column definition, can't be dropped by name, and
    blocks renaming the column). Redefine the column as plain longtext to drop
    the check; the caller then renames it back to JSON, which re-establishes it.
    Harmless on native-JSON MySQL. Runs only on MySQL/MariaDB — verified on
    MariaDB 10.6."""
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    op.execute(
        "ALTER TABLE contests MODIFY `%s` "
        "longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL" % column)


def upgrade():
    # Strip MariaDB's inline json_valid check on `rules` first, then rename in
    # place to eligibility_rules as JSON (preserving the data; autogenerate had
    # proposed a lossy drop+add). automated_settings was always unused, so drop.
    _strip_json_check("rules")
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column('rules', new_column_name='eligibility_rules',
                              existing_type=mysql.JSON(), existing_nullable=True)
        batch_op.drop_column('automated_settings')


def downgrade():
    _strip_json_check("eligibility_rules")
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column('eligibility_rules', new_column_name='rules',
                              existing_type=mysql.JSON(), existing_nullable=True)
        batch_op.add_column(sa.Column('automated_settings', mysql.JSON(), nullable=True))
