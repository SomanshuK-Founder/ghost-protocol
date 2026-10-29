"""Bind controlled execution attempts without changing existing attempt semantics."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0011_controlled_execution"
down_revision = "0010_workflow_resume"
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.String(64).with_variant(mysql.VARCHAR(64, collation="ascii_bin"), "mysql")
    with op.batch_alter_table("execution_attempts") as batch:
        batch.add_column(sa.Column("workflow_binding_ref", identity, nullable=True))
        batch.add_column(sa.Column("resume_hint_digest", identity, nullable=True))
        batch.create_foreign_key(
            "fk_attempt_workflow", "workflow_checkpoints", ["workflow_binding_ref"], ["binding_ref"]
        )
        batch.create_check_constraint(
            "ck_attempt_controlled",
            "(workflow_binding_ref IS NULL AND resume_hint_digest IS NULL) OR "
            "(workflow_binding_ref IS NOT NULL AND resume_hint_digest IS NOT NULL "
            "AND length(resume_hint_digest) = 64)",
        )


def downgrade():
    raise RuntimeError("Execution tombstones require a retention-aware rollback")
