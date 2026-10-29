"""Permit actual synthetic reads with no persisted result bytes. Not applied to MySQL."""

from alembic import op

revision = "0008_secure_document_reading"
down_revision = "0007_document_catalog"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("execution_attempts") as batch:
        batch.drop_constraint("ck_attempt_simulated", type_="check")
        batch.create_check_constraint("ck_attempt_mode", "mode IN ('SIMULATED','SYNTHETIC_READ')")
        batch.drop_constraint("ck_attempt_result", type_="check")
        batch.create_check_constraint(
            "ck_attempt_result",
            "(mode = 'SIMULATED' AND state = 'SUCCEEDED' AND result_json IS NOT NULL "
            "AND result_expires_at IS NOT NULL AND result_expires_at > completed_at) OR "
            "((mode = 'SYNTHETIC_READ' OR state <> 'SUCCEEDED') AND "
            "result_json IS NULL AND result_expires_at IS NULL)",
        )


def downgrade():
    raise RuntimeError("Execution tombstones require a retention-aware rollback")
