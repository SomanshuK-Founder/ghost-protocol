"""Authorization-only scoped consent. This revision is not applied by Step 8."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0003_scoped_consent"
down_revision = "0002_agent_identity"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def timestamp():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade():
    op.add_column(
        "gateway_tasks",
        sa.Column("authorization_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_task_authorization_version", "gateway_tasks", "authorization_version >= 0"
    )
    op.create_table(
        "scoped_consents",
        sa.Column("consent_ref", identity_string(64), primary_key=True),
        sa.Column("task_ref", identity_string(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("resource_versions", sa.JSON(), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=True),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("valid_from", timestamp(), nullable=False),
        sa.Column("expires_at", timestamp(), nullable=False),
        sa.Column("revoked_at", timestamp(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_scoped_consent_task_owner",
        ),
        sa.CheckConstraint(
            "action IN ('files.list_authorized', 'files.read', 'tasks.list')",
            name="ck_scoped_consent_action",
        ),
        sa.CheckConstraint(
            "purpose IN ('summarize_document', 'prepare_email', 'summarize_and_prepare_email', "
            "'morning_brief', 'answer_question')",
            name="ck_scoped_consent_purpose",
        ),
        sa.CheckConstraint("recipient IS NULL", name="ck_scoped_consent_no_email"),
        sa.CheckConstraint("expires_at > valid_from", name="ck_scoped_consent_expiry"),
        sa.CheckConstraint("valid_from >= created_at", name="ck_scoped_consent_creation"),
        sa.CheckConstraint("version > 0", name="ck_scoped_consent_version"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_scoped_consents_task_ref", "scoped_consents", ["task_ref"])


def downgrade():
    op.drop_index("ix_scoped_consents_task_ref", table_name="scoped_consents")
    op.drop_table("scoped_consents")
    op.drop_constraint("ck_task_authorization_version", "gateway_tasks", type_="check")
    op.drop_column("gateway_tasks", "authorization_version")
