"""Durable metadata-only operation admission; not applied during Step 12."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0004_operation_ledger"
down_revision = "0003_scoped_consent"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def timestamp():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade():
    op.create_table(
        "gateway_operations",
        sa.Column("operation_ref", identity_string(64), primary_key=True),
        sa.Column("task_ref", identity_string(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("request_id", identity_string(128), nullable=False),
        sa.Column("idempotency_key", identity_string(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("canonical_request_digest", identity_string(64), nullable=False),
        sa.Column("binding_digest", identity_string(64), nullable=False),
        sa.Column("authorization_version", sa.Integer(), nullable=False),
        sa.Column("operation_status", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("updated_at", timestamp(), nullable=False),
        sa.Column("execution_started_at", timestamp(), nullable=True),
        sa.Column("execution_finished_at", timestamp(), nullable=True),
        sa.Column("sanitized_error_code", sa.String(64), nullable=True),
        sa.Column(
            "audit_event_id",
            sa.Integer(),
            sa.ForeignKey("audit_events.id"),
            nullable=True,
            unique=True,
        ),
        sa.ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_operation_task_owner",
        ),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_operation_owner_request"),
        sa.UniqueConstraint(
            "owner_id", "task_ref", "idempotency_key", name="uq_operation_task_key"
        ),
        sa.UniqueConstraint(
            "task_ref", "canonical_request_digest", name="uq_operation_task_digest"
        ),
        sa.CheckConstraint(
            "authorization_version >= 0 AND revision >= 0", name="ck_operation_versions"
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_operation_updated"),
        sa.CheckConstraint(
            "action IN ('files.list_authorized', 'files.read', 'email.draft', "
            "'email.send', 'tasks.list')",
            name="ck_operation_action",
        ),
        sa.CheckConstraint(
            "(operation_status = 'DENIED' AND decision = 'DENY') OR "
            "(operation_status IN ('ADMITTED', 'DISPATCHING', 'SUCCEEDED', 'FAILED', 'UNKNOWN') "
            "AND decision = 'ALLOW')",
            name="ck_operation_state_decision",
        ),
        sa.CheckConstraint(
            "(operation_status IN ('ADMITTED', 'DENIED') AND execution_started_at IS NULL "
            "AND execution_finished_at IS NULL) OR "
            "(operation_status IN ('DISPATCHING', 'UNKNOWN') "
            "AND execution_started_at >= created_at "
            "AND execution_started_at IS NOT NULL AND execution_finished_at IS NULL) OR "
            "(operation_status IN ('SUCCEEDED', 'FAILED') AND execution_started_at >= created_at "
            "AND execution_started_at IS NOT NULL "
            "AND execution_finished_at >= execution_started_at "
            "AND execution_finished_at IS NOT NULL)",
            name="ck_operation_execution_times",
        ),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_gateway_operations_task_ref", "gateway_operations", ["task_ref"])


def downgrade():
    op.drop_index("ix_gateway_operations_task_ref", table_name="gateway_operations")
    op.drop_table("gateway_operations")
