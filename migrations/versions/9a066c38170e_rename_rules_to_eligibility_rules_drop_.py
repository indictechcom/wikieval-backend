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


def _drop_json_valid_checks(columns):
    """Drop any auto CHECK(json_valid(col)) constraints on the given contests
    columns. MariaDB implements JSON as LONGTEXT + such a constraint, which
    blocks renaming/dropping the column; native-JSON MySQL has none (this is a
    no-op there). Runs only on MySQL/MariaDB."""
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    like = " OR ".join(["cc.CHECK_CLAUSE LIKE :c%d" % i for i in range(len(columns))])
    params = {"c%d" % i: "%%%s%%" % col for i, col in enumerate(columns)}
    try:
        rows = bind.execute(sa.text(
            "SELECT cc.CONSTRAINT_NAME "
            "FROM information_schema.CHECK_CONSTRAINTS cc "
            "JOIN information_schema.TABLE_CONSTRAINTS tc "
            "  ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
            " AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
            "WHERE tc.TABLE_NAME = 'contests' "
            "  AND tc.CONSTRAINT_SCHEMA = DATABASE() "
            "  AND (" + like + ")"
        ), params).fetchall()
    except Exception:  # information_schema shape differs / native JSON — nothing to drop
        return
    for (name,) in rows:
        op.execute("ALTER TABLE contests DROP CONSTRAINT `%s`" % name)


def upgrade():
    # Drop the MariaDB json_valid checks that pin `rules`/`automated_settings`
    # before renaming/dropping them (autogenerate proposed a drop+add, which
    # would discard the rule data — we rename in place instead).
    _drop_json_valid_checks(["rules", "automated_settings"])
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column('rules', new_column_name='eligibility_rules',
                              existing_type=mysql.JSON(), existing_nullable=True)
        batch_op.drop_column('automated_settings')


def downgrade():
    _drop_json_valid_checks(["eligibility_rules"])
    with op.batch_alter_table('contests', schema=None) as batch_op:
        batch_op.alter_column('eligibility_rules', new_column_name='rules',
                              existing_type=mysql.JSON(), existing_nullable=True)
        batch_op.add_column(sa.Column('automated_settings', mysql.JSON(), nullable=True))
