"""Durable owner approval foundation. Not applied during Step 15."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0005_durable_approvals"
down_revision = "0004_operation_ledger"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def timestamp():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade():
    with op.batch_alter_table("gateway_operations") as batch:
        batch.alter_column(
            "decision", existing_type=sa.String(8), type_=sa.String(32), existing_nullable=False
        )
        batch.create_unique_constraint(
            "uq_operation_binding", ["operation_ref", "task_ref", "owner_id"]
        )
        batch.drop_constraint("ck_operation_state_decision", type_="check")
        batch.create_check_constraint(
            "ck_operation_state_decision",
            "(operation_status = 'DENIED' AND decision = 'DENY') OR "
            "(operation_status IN ('PENDING_APPROVAL','READY') AND decision = "
            "'APPROVAL_REQUIRED') OR "
            "(operation_status IN ('ADMITTED','DISPATCHING','SUCCEEDED','FAILED','UNKNOWN') "
            "AND decision = 'ALLOW')",
        )
        batch.drop_constraint("ck_operation_execution_times", type_="check")
        batch.create_check_constraint(
            "ck_operation_execution_times",
            "(operation_status IN ('ADMITTED','DENIED','PENDING_APPROVAL','READY') AND "
            "execution_started_at IS NULL AND execution_finished_at IS NULL) OR "
            "(operation_status IN ('DISPATCHING','UNKNOWN') AND execution_started_at >= "
            "created_at AND execution_started_at IS NOT NULL AND execution_finished_at IS "
            "NULL) OR "
            "(operation_status IN ('SUCCEEDED','FAILED') AND execution_started_at >= "
            "created_at AND execution_started_at IS NOT NULL AND execution_finished_at >= "
            "execution_started_at AND execution_finished_at IS NOT NULL)",
        )
    with op.batch_alter_table("scoped_consents") as batch:
        batch.add_column(sa.Column("bound_operation_ref", identity_string(64), nullable=True))
        batch.create_foreign_key(
            "fk_consent_operation", "gateway_operations", ["bound_operation_ref"], ["operation_ref"]
        )
        batch.create_unique_constraint("uq_consent_operation", ["bound_operation_ref"])
    op.create_table(
        "pending_approvals",
        sa.Column("approval_ref", identity_string(64), primary_key=True),
        sa.Column("operation_ref", identity_string(64), nullable=False, unique=True),
        sa.Column("task_ref", identity_string(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("request_id", identity_string(128), nullable=False),
        sa.Column("idempotency_key", identity_string(128), nullable=False),
        sa.Column("canonical_request_digest", identity_string(64), nullable=False),
        sa.Column("binding_digest", identity_string(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("resource_versions", sa.JSON(), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("expires_at", timestamp(), nullable=False),
        sa.Column("decided_at", timestamp(), nullable=True),
        sa.Column("authorization_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column(
            "consent_ref",
            identity_string(64),
            sa.ForeignKey("scoped_consents.consent_ref"),
            nullable=True,
            unique=True,
        ),
        sa.Column("resume_ref", identity_string(128), nullable=True, unique=True),
        sa.Column("audit_event_id", sa.Integer(), sa.ForeignKey("audit_events.id"), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_ref", "task_ref", "owner_id"],
            [
                "gateway_operations.operation_ref",
                "gateway_operations.task_ref",
                "gateway_operations.owner_id",
            ],
            name="fk_approval_operation_binding",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXPIRED','REVOKED')",
            name="ck_approval_status",
        ),
        sa.CheckConstraint(
            "action IN ('files.list_authorized','files.read','tasks.list') AND recipient IS NULL",
            name="ck_approval_nonemail",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_approval_expiry"),
        sa.CheckConstraint(
            "authorization_version >= 0 AND revision >= 0", name="ck_approval_versions"
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL) OR (status <> 'PENDING' AND "
            "decided_at IS NOT NULL)",
            name="ck_approval_decision",
        ),
        sa.CheckConstraint(
            "(status = 'APPROVED' AND consent_ref IS NOT NULL AND resume_ref IS NOT NULL) OR "
            "(status <> 'APPROVED' AND resume_ref IS NULL)",
            name="ck_approval_grant",
        ),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_pending_approvals_task_ref", "pending_approvals", ["task_ref"])


def downgrade():
    raise RuntimeError(
        "Approval and operation tombstones require an explicit retention-aware rollback"
    )
