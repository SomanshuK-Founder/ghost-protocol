"""Add target-bound application mutations; preserve all historical commands."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0013_application_interfaces"
down_revision = "0012_application_commands"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_approval_owner_binding", "pending_approvals", ["approval_ref", "task_ref", "owner_id"]
    )
    op.create_unique_constraint(
        "uq_workflow_owner_binding", "workflow_checkpoints", ["binding_ref", "task_ref", "owner_id"]
    )
    for column, table in (
        ("planning_task_ref", "gateway_tasks.task_ref"),
        ("creation_task_ref", "gateway_tasks.task_ref"),
        ("continuation_binding_ref", "workflow_checkpoints.binding_ref"),
        ("approval_ref", "pending_approvals.approval_ref"),
    ):
        identity = sa.String(64).with_variant(mysql.VARCHAR(64, collation="ascii_bin"), "mysql")
        op.add_column("application_commands", sa.Column(column, identity, nullable=True))
        target, reference = table.split(".")
        op.create_foreign_key(
            "fk_app_" + column, "application_commands", target, [column], [reference]
        )
    op.execute("UPDATE application_commands SET planning_task_ref=task_ref WHERE kind='PLANNING'")
    op.execute(
        "UPDATE application_commands SET creation_task_ref=task_ref WHERE kind='TASK_CREATE'"
    )
    op.create_foreign_key(
        "fk_app_approval_owner",
        "application_commands",
        "pending_approvals",
        ["approval_ref", "task_ref", "owner_id"],
        ["approval_ref", "task_ref", "owner_id"],
    )
    op.create_foreign_key(
        "fk_app_workflow_owner",
        "application_commands",
        "workflow_checkpoints",
        ["continuation_binding_ref", "task_ref", "owner_id"],
        ["binding_ref", "task_ref", "owner_id"],
    )
    op.create_check_constraint(
        "ck_app_command_task", "application_commands", "task_ref IS NOT NULL"
    )
    for column, name in (
        ("planning_task_ref", "uq_app_planning_task"),
        ("creation_task_ref", "uq_app_creation_task"),
        ("continuation_binding_ref", "uq_app_continuation_binding"),
    ):
        op.create_unique_constraint(name, "application_commands", [column])
    op.drop_constraint("uq_app_task_command", "application_commands", type_="unique")
    op.drop_constraint("ck_app_command_kind", "application_commands", type_="check")
    op.alter_column(
        "application_commands",
        "kind",
        existing_type=sa.String(16),
        type_=sa.String(32),
        existing_nullable=False,
    )
    checks = {
        "ck_app_command_kind": (
            "kind IN "
            "('TASK_CREATE','PLANNING','APPROVAL_DECISION','APPROVAL_REVOKE','CONTINUE','CANCEL')"
        ),
        "ck_app_planning_identity": (
            "(kind='PLANNING' AND planning_task_ref IS NOT NULL AND "
            "planning_task_ref=task_ref) OR (kind<>'PLANNING' AND "
            "planning_task_ref IS NULL)"
        ),
        "ck_app_creation_identity": (
            "(kind='TASK_CREATE' AND creation_task_ref IS NOT NULL AND "
            "creation_task_ref=task_ref) OR (kind<>'TASK_CREATE' AND "
            "creation_task_ref IS NULL)"
        ),
        "ck_app_continuation_identity": (
            "(kind='CONTINUE' AND continuation_binding_ref IS NOT NULL) OR "
            "(kind<>'CONTINUE' AND continuation_binding_ref IS NULL)"
        ),
        "ck_app_approval_identity": (
            "(kind IN ('APPROVAL_DECISION','APPROVAL_REVOKE') AND "
            "approval_ref IS NOT NULL) OR (kind NOT IN "
            "('APPROVAL_DECISION','APPROVAL_REVOKE') AND approval_ref IS "
            "NULL)"
        ),
    }
    for name, condition in checks.items():
        op.create_check_constraint(name, "application_commands", condition)


def downgrade():
    raise RuntimeError("Application mutation tombstones require a retention-aware rollback")
