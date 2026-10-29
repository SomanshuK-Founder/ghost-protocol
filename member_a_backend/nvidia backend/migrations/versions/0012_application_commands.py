"""Durable application command identity; no duplicate task authority or prompt storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0012_application_commands"
down_revision = "0011_controlled_execution"
branch_labels = None
depends_on = None


def upgrade():
    def identity(length):
        return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")

    time = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "application_commands",
        sa.Column("command_ref", identity(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_ref", identity(64), nullable=True),
        sa.Column("scope_digest", identity(64), nullable=False),
        sa.Column("client_key", identity(36), nullable=False),
        sa.Column("request_digest", identity(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("runtime_ref", identity(64), nullable=True),
        sa.Column("safe_result", sa.JSON(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("failure_http_status", sa.Integer(), nullable=True),
        sa.Column("created_at", time, nullable=False),
        sa.Column("updated_at", time, nullable=False),
        sa.ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_app_command_task_owner",
        ),
        sa.UniqueConstraint("owner_id", "scope_digest", "client_key", name="uq_app_command_key"),
        sa.UniqueConstraint("task_ref", "kind", name="uq_app_task_command"),
        sa.CheckConstraint("kind IN ('TASK_CREATE','PLANNING')", name="ck_app_command_kind"),
        sa.CheckConstraint(
            "state IN ('CLAIMED','SUCCEEDED','FAILED','UNCERTAIN')", name="ck_app_command_state"
        ),
        sa.CheckConstraint(
            "kind != 'PLANNING' OR task_ref IS NOT NULL", name="ck_app_planning_task"
        ),
        sa.CheckConstraint(
            "length(scope_digest)=64 AND length(request_digest)=64", name="ck_app_command_digests"
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_app_command_time"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_application_commands_task_ref", "application_commands", ["task_ref"])


def downgrade():
    raise RuntimeError("Application command tombstones require a retention-aware rollback")
