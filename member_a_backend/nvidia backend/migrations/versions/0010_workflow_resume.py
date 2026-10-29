"""Add workflow-only admission; preserve execution and approval consumption."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0010_workflow_resume"
down_revision = "0009_mailpit_email"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def upgrade():
    timestamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "workflow_checkpoints",
        sa.Column("binding_ref", identity_string(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("task_ref", identity_string(64), nullable=False),
        sa.Column("operation_ref", identity_string(64), nullable=False),
        sa.Column("approval_ref", identity_string(64), nullable=False),
        sa.Column("request_id", identity_string(128), nullable=False),
        sa.Column("idempotency_key", identity_string(128), nullable=False),
        sa.Column("canonical_request_digest", identity_string(64), nullable=False),
        sa.Column("thread_id", identity_string(64), nullable=False, unique=True),
        sa.Column("checkpoint_id", identity_string(64), nullable=True),
        sa.Column("workflow_version", sa.String(32), nullable=False),
        sa.Column("registration_authorization_version", sa.Integer(), nullable=False),
        sa.Column("admitted_authorization_version", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.Column("expires_at", timestamp, nullable=True),
        sa.Column("audit_event_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_ref", "task_ref", "owner_id"],
            [
                "gateway_operations.operation_ref",
                "gateway_operations.task_ref",
                "gateway_operations.owner_id",
            ],
            name="fk_workflow_operation_binding",
        ),
        sa.ForeignKeyConstraint(["approval_ref"], ["pending_approvals.approval_ref"]),
        sa.ForeignKeyConstraint(["audit_event_id"], ["audit_events.id"]),
        sa.UniqueConstraint("operation_ref", name="uq_workflow_operation"),
        sa.UniqueConstraint("thread_id", "checkpoint_id", name="uq_workflow_checkpoint"),
        sa.CheckConstraint(
            "phase IN ('PREPARING','PAUSED','ADMITTED','RESUMING','RESUMED','DENIED')",
            name="ck_workflow_phase",
        ),
        sa.CheckConstraint("registration_authorization_version >= 0", name="ck_workflow_version"),
        sa.CheckConstraint(
            "phase = 'PREPARING' OR checkpoint_id IS NOT NULL", name="ck_workflow_paused"
        ),
        sa.CheckConstraint(
            "phase NOT IN ('ADMITTED','RESUMING','RESUMED') OR "
            "(admitted_authorization_version IS NOT NULL AND expires_at IS NOT NULL)",
            name="ck_workflow_admission",
        ),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_workflow_checkpoints_task_ref", "workflow_checkpoints", ["task_ref"])


def downgrade():
    op.drop_index("ix_workflow_checkpoints_task_ref", table_name="workflow_checkpoints")
    op.drop_table("workflow_checkpoints")
