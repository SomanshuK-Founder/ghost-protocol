"""Trusted tasks and digest-only agent credentials. Not applied during Step 6."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0002_agent_identity"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def timestamp():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade():
    op.create_table(
        "gateway_tasks",
        sa.Column("task_ref", identity_string(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("expires_at", timestamp(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("authorization_scope", sa.JSON(), nullable=False),
        sa.Column("credential_epoch", sa.Integer(), nullable=False),
        sa.Column("revoked_at", timestamp(), nullable=True),
        sa.UniqueConstraint("task_ref", "owner_id", name="uq_gateway_task_owner"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'COMPLETED', 'CANCELLED', 'EXPIRED')", name="ck_task_status"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_task_expiry"),
        sa.CheckConstraint("credential_epoch >= 0", name="ck_task_epoch"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_gateway_tasks_owner_id", "gateway_tasks", ["owner_id"])
    op.create_table(
        "agent_credentials",
        sa.Column("credential_ref", identity_string(64), primary_key=True),
        sa.Column("token_digest", identity_string(64), nullable=False, unique=True),
        sa.Column("task_ref", identity_string(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("credential_epoch", sa.Integer(), nullable=False),
        sa.Column("issued_at", timestamp(), nullable=False),
        sa.Column("expires_at", timestamp(), nullable=False),
        sa.Column("revoked_at", timestamp(), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_agent_credential_task_owner",
        ),
        sa.CheckConstraint("expires_at > issued_at", name="ck_credential_expiry"),
        sa.CheckConstraint("credential_epoch > 0", name="ck_credential_epoch"),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_agent_credentials_task_ref", "agent_credentials", ["task_ref"])


def downgrade():
    op.drop_index("ix_agent_credentials_task_ref", table_name="agent_credentials")
    op.drop_table("agent_credentials")
    op.drop_index("ix_gateway_tasks_owner_id", table_name="gateway_tasks")
    op.drop_table("gateway_tasks")
