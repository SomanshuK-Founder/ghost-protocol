"""Exact synthetic email scope and Mailpit receipt metadata; not applied to MySQL."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0009_mailpit_email"
down_revision = "0008_secure_document_reading"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def upgrade():
    with op.batch_alter_table("scoped_consents") as batch:
        batch.add_column(sa.Column("payload_digest", identity_string(64), nullable=True))
        batch.drop_constraint("ck_scoped_consent_action", type_="check")
        batch.drop_constraint("ck_scoped_consent_no_email", type_="check")
        batch.create_check_constraint(
            "ck_scoped_consent_action",
            "action IN ('files.list_authorized','files.read','tasks.list',"
            "'email.draft','email.send')",
        )
        batch.create_check_constraint(
            "ck_scoped_consent_email_scope",
            "(action IN ('email.draft','email.send') AND recipient IS NOT NULL AND "
            "payload_digest IS NOT NULL AND bound_operation_ref IS NOT NULL) OR "
            "(action NOT IN ('email.draft','email.send') AND recipient IS NULL "
            "AND payload_digest IS NULL)",
        )
    with op.batch_alter_table("pending_approvals") as batch:
        batch.add_column(sa.Column("template_ref", sa.String(32), nullable=True))
        batch.drop_constraint("ck_approval_nonemail", type_="check")
        batch.create_check_constraint(
            "ck_approval_email_scope",
            "(action IN ('files.list_authorized','files.read','tasks.list') AND recipient IS NULL "
            "AND template_ref IS NULL) OR (action IN ('email.draft','email.send') AND "
            "recipient IS NOT NULL AND template_ref IS NOT NULL "
            "AND template_ref = 'synthetic_mail_v1')",
        )
    with op.batch_alter_table("gateway_operations") as batch:
        batch.add_column(sa.Column("send_slot_task_ref", identity_string(64), nullable=True))
        batch.create_foreign_key(
            "fk_operation_send_slot", "gateway_tasks", ["send_slot_task_ref"], ["task_ref"]
        )
        batch.create_unique_constraint("uq_operation_send_slot", ["send_slot_task_ref"])
        batch.create_check_constraint(
            "ck_operation_send_slot",
            "send_slot_task_ref IS NULL OR "
            "(action = 'email.send' AND send_slot_task_ref = task_ref)",
        )
    with op.batch_alter_table("execution_attempts") as batch:
        batch.drop_constraint("ck_attempt_mode", type_="check")
        batch.create_check_constraint(
            "ck_attempt_mode", "mode IN ('SIMULATED','SYNTHETIC_READ','EMAIL_DRAFT','MAILPIT_SEND')"
        )
        batch.drop_constraint("ck_attempt_result", type_="check")
        batch.create_check_constraint(
            "ck_attempt_result",
            "(mode IN ('SIMULATED','EMAIL_DRAFT','MAILPIT_SEND') AND state = 'SUCCEEDED' AND "
            "result_json IS NOT NULL AND result_expires_at IS NOT NULL "
            "AND result_expires_at > completed_at) OR "
            "((mode = 'SYNTHETIC_READ' OR state <> 'SUCCEEDED') "
            "AND result_json IS NULL AND result_expires_at IS NULL)",
        )
    op.create_table(
        "email_artifacts",
        sa.Column("artifact_ref", identity_string(64), primary_key=True),
        sa.Column(
            "operation_ref",
            identity_string(64),
            sa.ForeignKey("gateway_operations.operation_ref"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "attempt_ref",
            identity_string(64),
            sa.ForeignKey("execution_attempts.attempt_ref"),
            nullable=False,
            unique=True,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("template_ref", sa.String(32), nullable=False),
        sa.Column("payload_digest", identity_string(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False
        ),
        sa.CheckConstraint("kind IN ('EMAIL_DRAFT','MAILPIT_SEND')", name="ck_email_artifact_kind"),
        sa.CheckConstraint("template_ref = 'synthetic_mail_v1'", name="ck_email_artifact_template"),
        mysql_engine="InnoDB",
    )


def downgrade():
    raise RuntimeError("Email effect tombstones require a retention-aware rollback")
