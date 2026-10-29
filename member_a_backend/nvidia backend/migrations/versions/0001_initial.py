"""Initial users, consent, permissions, and audit schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users", sa.Column("id", sa.String(64), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("consent_records", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False), sa.Column("scope", sa.String(100), nullable=False), sa.Column("granted", sa.Boolean(), nullable=False), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_consent_records_user_id", "consent_records", ["user_id"])
    op.create_index("ix_consent_records_scope", "consent_records", ["scope"])
    op.create_table("tool_permissions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False), sa.Column("tool_name", sa.String(100), nullable=False), sa.Column("allowed", sa.Boolean(), nullable=False), sa.UniqueConstraint("user_id", "tool_name"))
    op.create_index("ix_tool_permissions_user_id", "tool_permissions", ["user_id"])
    op.create_table("audit_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.String(64), nullable=True), sa.Column("event_type", sa.String(100), nullable=False), sa.Column("outcome", sa.String(30), nullable=False), sa.Column("detail", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

def downgrade():
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_tool_permissions_user_id", table_name="tool_permissions")
    op.drop_table("tool_permissions")
    op.drop_index("ix_consent_records_scope", table_name="consent_records")
    op.drop_index("ix_consent_records_user_id", table_name="consent_records")
    op.drop_table("consent_records")
    op.drop_table("users")
