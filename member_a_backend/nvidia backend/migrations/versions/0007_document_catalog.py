"""Backend-owned synthetic document metadata. Not applied during Step 21."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0007_document_catalog"
down_revision = "0006_trusted_execution"
branch_labels = None
depends_on = None


def identity_string(length):
    return sa.String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


def timestamp():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade():
    op.create_table(
        "document_resources",
        sa.Column("resource_ref", identity_string(64), primary_key=True),
        sa.Column("owner_ref", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("storage_reference", identity_string(96), nullable=False),
        sa.Column("content_digest", identity_string(64), nullable=False),
        sa.Column("version_ref", identity_string(64), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("updated_at", timestamp(), nullable=False),
        sa.UniqueConstraint("owner_ref", "storage_reference", name="uq_document_owner_storage"),
        sa.CheckConstraint("resource_type = 'SYNTHETIC_TEXT'", name="ck_document_type"),
        sa.CheckConstraint(
            "classification IN ('PRIVATE_ORIGINAL','SHAREABLE')", name="ck_document_classification"
        ),
        sa.CheckConstraint(
            "length(resource_ref) = 41 AND substr(resource_ref,1,9) = 'resource_'",
            name="ck_document_reference",
        ),
        sa.CheckConstraint(
            "length(version_ref) = 40 AND substr(version_ref,1,8) = 'version_'",
            name="ck_document_version",
        ),
        sa.CheckConstraint("length(content_digest) = 64", name="ck_document_digest"),
        sa.CheckConstraint("active IN (0,1)", name="ck_document_active"),
        sa.CheckConstraint("updated_at >= created_at", name="ck_document_updated"),
        sa.CheckConstraint(
            "storage_reference IN ('ghost_demo_v1_doc_tax_2026','ghost_demo_v1_doc_bank_oct',"
            "'ghost_demo_v1_doc_personal_notes','ghost_demo_v1_doc_project_report',"
            "'ghost_demo_v1_doc_meeting_oct','ghost_demo_v1_doc_schedule')",
            name="ck_document_storage",
        ),
        mysql_engine="InnoDB",
    )
    op.create_index("ix_document_resources_owner_ref", "document_resources", ["owner_ref"])


def downgrade():
    raise RuntimeError("Resource tombstones require an explicit retention-aware rollback")
