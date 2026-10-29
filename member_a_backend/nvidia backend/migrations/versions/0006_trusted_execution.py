"""Single synthetic execution attempt and one-use approval consumption; not applied."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0006_trusted_execution"
down_revision = "0005_durable_approvals"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def timestamp():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade():
    with op.batch_alter_table("pending_approvals") as batch:
        batch.add_column(sa.Column("consumed_at", timestamp(), nullable=True))
        batch.drop_constraint("ck_approval_grant", type_="check")
        batch.create_check_constraint(
            "ck_approval_grant",
            "(status = 'APPROVED' AND consent_ref IS NOT NULL AND "
            "((consumed_at IS NULL AND resume_ref IS NOT NULL) OR "
            "(consumed_at IS NOT NULL AND resume_ref IS NULL))) OR "
            "(status <> 'APPROVED' AND resume_ref IS NULL)",
        )
        batch.create_check_constraint(
            "ck_approval_consumption",
            "consumed_at IS NULL OR (status IN ('APPROVED','EXPIRED','REVOKED') AND "
            "consumed_at >= created_at AND consumed_at < expires_at)",
        )
    op.create_table(
        "execution_attempts",
        sa.Column("attempt_ref", identity_string(64), primary_key=True),
        sa.Column(
            "operation_ref",
            identity_string(64),
            sa.ForeignKey("gateway_operations.operation_ref"),
            nullable=False,
            unique=True,
        ),
        sa.Column("dispatch_nonce", identity_string(64), nullable=False, unique=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("dispatch_at", timestamp(), nullable=False),
        sa.Column("completed_at", timestamp(), nullable=True),
        sa.Column("sanitized_error_code", sa.String(64), nullable=True),
        sa.Column("result_json", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("result_expires_at", timestamp(), nullable=True),
        sa.Column("audit_event_id", sa.Integer(), sa.ForeignKey("audit_events.id"), nullable=False),
        sa.CheckConstraint("mode = 'SIMULATED'", name="ck_attempt_simulated"),
        sa.CheckConstraint(
            "state IN ('DISPATCHING','SUCCEEDED','FAILED','UNKNOWN')", name="ck_attempt_state"
        ),
        sa.CheckConstraint(
            "(state IN ('DISPATCHING','UNKNOWN') AND completed_at IS NULL) OR "
            "(state IN ('SUCCEEDED','FAILED') AND completed_at IS NOT NULL AND "
            "completed_at >= dispatch_at)",
            name="ck_attempt_times",
        ),
        sa.CheckConstraint(
            "(state = 'SUCCEEDED' AND result_json IS NOT NULL AND result_expires_at IS NOT NULL "
            "AND result_expires_at > completed_at) OR (state <> 'SUCCEEDED' AND "
            "result_json IS NULL AND result_expires_at IS NULL)",
            name="ck_attempt_result",
        ),
        mysql_engine="InnoDB",
    )


def downgrade():
    raise RuntimeError("Execution tombstones require a retention-aware rollback")
