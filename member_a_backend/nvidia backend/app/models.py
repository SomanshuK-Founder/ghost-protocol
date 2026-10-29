from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    consents: Mapped[list["ConsentRecord"]] = relationship(back_populates="user")
    permissions: Mapped[list["ToolPermission"]] = relationship(back_populates="user")


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scope: Mapped[str] = mapped_column(String(100), index=True)
    granted: Mapped[bool] = mapped_column(Boolean)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    user: Mapped[User] = relationship(back_populates="consents")


class ToolPermission(Base):
    __tablename__ = "tool_permissions"
    __table_args__ = (UniqueConstraint("user_id", "tool_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    user: Mapped[User] = relationship(back_populates="permissions")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    outcome: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class UTCDateTime(TypeDecorator):
    """MySQL DATETIME has no timezone; persist naive UTC and restore aware UTC."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(
            mysql.DATETIME(fsp=6) if dialect.name == "mysql" else DateTime()
        )

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An aware UTC timestamp is required")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


def identity_string(length: int):
    return String(length).with_variant(mysql.VARCHAR(length, collation="ascii_bin"), "mysql")


class ApplicationCommand(Base):
    """Application idempotency/metadata only; GatewayTask remains authoritative."""

    __tablename__ = "application_commands"
    __table_args__ = (
        UniqueConstraint("owner_id", "scope_digest", "client_key", name="uq_app_command_key"),
        UniqueConstraint("planning_task_ref", name="uq_app_planning_task"),
        UniqueConstraint("creation_task_ref", name="uq_app_creation_task"),
        UniqueConstraint("continuation_binding_ref", name="uq_app_continuation_binding"),
        ForeignKeyConstraint(
            ["approval_ref", "task_ref", "owner_id"],
            [
                "pending_approvals.approval_ref",
                "pending_approvals.task_ref",
                "pending_approvals.owner_id",
            ],
            name="fk_app_approval_owner",
        ),
        ForeignKeyConstraint(
            ["continuation_binding_ref", "task_ref", "owner_id"],
            [
                "workflow_checkpoints.binding_ref",
                "workflow_checkpoints.task_ref",
                "workflow_checkpoints.owner_id",
            ],
            name="fk_app_workflow_owner",
        ),
        CheckConstraint("task_ref IS NOT NULL", name="ck_app_command_task"),
        ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_app_command_task_owner",
        ),
        CheckConstraint(
            (
                "kind IN "
                "('TASK_CREATE','PLANNING','APPROVAL_DECISION','APPROVAL_REVOKE','CONTINUE','CANCEL')"
            ),
            name="ck_app_command_kind",
        ),
        CheckConstraint(
            (
                "(kind='PLANNING' AND planning_task_ref IS NOT NULL AND "
                "planning_task_ref=task_ref) OR (kind<>'PLANNING' AND "
                "planning_task_ref IS NULL)"
            ),
            name="ck_app_planning_identity",
        ),
        CheckConstraint(
            (
                "(kind='TASK_CREATE' AND creation_task_ref IS NOT NULL AND "
                "creation_task_ref=task_ref) OR (kind<>'TASK_CREATE' AND "
                "creation_task_ref IS NULL)"
            ),
            name="ck_app_creation_identity",
        ),
        CheckConstraint(
            (
                "(kind='CONTINUE' AND continuation_binding_ref IS NOT NULL) OR "
                "(kind<>'CONTINUE' AND continuation_binding_ref IS NULL)"
            ),
            name="ck_app_continuation_identity",
        ),
        CheckConstraint(
            (
                "(kind IN ('APPROVAL_DECISION','APPROVAL_REVOKE') AND "
                "approval_ref IS NOT NULL) OR (kind NOT IN "
                "('APPROVAL_DECISION','APPROVAL_REVOKE') AND approval_ref IS "
                "NULL)"
            ),
            name="ck_app_approval_identity",
        ),
        CheckConstraint(
            "state IN ('CLAIMED','SUCCEEDED','FAILED','UNCERTAIN')", name="ck_app_command_state"
        ),
        CheckConstraint("kind != 'PLANNING' OR task_ref IS NOT NULL", name="ck_app_planning_task"),
        CheckConstraint(
            "length(scope_digest)=64 AND length(request_digest)=64", name="ck_app_command_digests"
        ),
        CheckConstraint("updated_at >= created_at", name="ck_app_command_time"),
        {"mysql_engine": "InnoDB"},
    )
    command_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    task_ref: Mapped[str | None] = mapped_column(identity_string(64), nullable=True, index=True)
    scope_digest: Mapped[str] = mapped_column(identity_string(64))
    client_key: Mapped[str] = mapped_column(identity_string(36))
    request_digest: Mapped[str] = mapped_column(identity_string(64))
    kind: Mapped[str] = mapped_column(String(32))
    planning_task_ref: Mapped[str | None] = mapped_column(
        ForeignKey("gateway_tasks.task_ref"), nullable=True
    )
    creation_task_ref: Mapped[str | None] = mapped_column(
        ForeignKey("gateway_tasks.task_ref"), nullable=True
    )
    continuation_binding_ref: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_checkpoints.binding_ref"), nullable=True
    )
    approval_ref: Mapped[str | None] = mapped_column(
        ForeignKey("pending_approvals.approval_ref"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16))
    runtime_ref: Mapped[str | None] = mapped_column(identity_string(64), nullable=True)
    safe_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class GatewayTask(Base):
    __tablename__ = "gateway_tasks"
    __table_args__ = (
        UniqueConstraint("task_ref", "owner_id", name="uq_gateway_task_owner"),
        CheckConstraint(
            "status IN ('OPEN', 'COMPLETED', 'CANCELLED', 'EXPIRED')", name="ck_task_status"
        ),
        CheckConstraint("expires_at > created_at", name="ck_task_expiry"),
        CheckConstraint("credential_epoch >= 0", name="ck_task_epoch"),
        CheckConstraint("authorization_version >= 0", name="ck_task_authorization_version"),
        {"mysql_engine": "InnoDB"},
    )
    task_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    authorization_scope: Mapped[dict] = mapped_column(JSON)
    credential_epoch: Mapped[int] = mapped_column(default=0)
    authorization_version: Mapped[int] = mapped_column(default=0, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AgentCredential(Base):
    __tablename__ = "agent_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_agent_credential_task_owner",
        ),
        CheckConstraint("expires_at > issued_at", name="ck_credential_expiry"),
        CheckConstraint("credential_epoch > 0", name="ck_credential_epoch"),
        {"mysql_engine": "InnoDB"},
    )
    credential_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    token_digest: Mapped[str] = mapped_column(identity_string(64), unique=True)
    task_ref: Mapped[str] = mapped_column(identity_string(64), index=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    credential_epoch: Mapped[int]
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ScopedConsent(Base):
    __tablename__ = "scoped_consents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_scoped_consent_task_owner",
        ),
        CheckConstraint(
            "action IN ('files.list_authorized', 'files.read', 'tasks.list',"
            "'email.draft','email.send')",
            name="ck_scoped_consent_action",
        ),
        CheckConstraint(
            "purpose IN ('summarize_document', 'prepare_email', 'summarize_and_prepare_email', "
            "'morning_brief', 'answer_question')",
            name="ck_scoped_consent_purpose",
        ),
        CheckConstraint(
            "(action IN ('email.draft','email.send') AND recipient IS NOT NULL AND "
            "payload_digest IS NOT NULL AND bound_operation_ref IS NOT NULL) OR "
            "(action NOT IN ('email.draft','email.send') AND recipient IS NULL AND "
            "payload_digest IS NULL)",
            name="ck_scoped_consent_email_scope",
        ),
        CheckConstraint("expires_at > valid_from", name="ck_scoped_consent_expiry"),
        CheckConstraint("valid_from >= created_at", name="ck_scoped_consent_creation"),
        CheckConstraint("version > 0", name="ck_scoped_consent_version"),
        {"mysql_engine": "InnoDB"},
    )
    consent_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    task_ref: Mapped[str] = mapped_column(identity_string(64), index=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(64))
    resource_versions: Mapped[list] = mapped_column(JSON)
    recipient: Mapped[str | None] = mapped_column(String(254), nullable=True)
    payload_digest: Mapped[str | None] = mapped_column(identity_string(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    bound_operation_ref: Mapped[str | None] = mapped_column(
        ForeignKey("gateway_operations.operation_ref"), nullable=True, unique=True
    )


class GatewayOperation(Base):
    __tablename__ = "gateway_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_ref", "owner_id"],
            ["gateway_tasks.task_ref", "gateway_tasks.owner_id"],
            name="fk_operation_task_owner",
        ),
        UniqueConstraint("owner_id", "request_id", name="uq_operation_owner_request"),
        UniqueConstraint("owner_id", "task_ref", "idempotency_key", name="uq_operation_task_key"),
        UniqueConstraint("task_ref", "canonical_request_digest", name="uq_operation_task_digest"),
        UniqueConstraint("operation_ref", "task_ref", "owner_id", name="uq_operation_binding"),
        CheckConstraint(
            "authorization_version >= 0 AND revision >= 0", name="ck_operation_versions"
        ),
        CheckConstraint("updated_at >= created_at", name="ck_operation_updated"),
        CheckConstraint(
            "send_slot_task_ref IS NULL OR "
            "(action = 'email.send' AND send_slot_task_ref = task_ref)",
            name="ck_operation_send_slot",
        ),
        CheckConstraint(
            "action IN ('files.list_authorized', 'files.read', 'email.draft', "
            "'email.send', 'tasks.list')",
            name="ck_operation_action",
        ),
        CheckConstraint(
            "(operation_status = 'DENIED' AND decision = 'DENY') OR "
            "(operation_status IN ('PENDING_APPROVAL','READY') AND decision = "
            "'APPROVAL_REQUIRED') OR "
            "(operation_status IN ('ADMITTED', 'DISPATCHING', 'SUCCEEDED', 'FAILED', 'UNKNOWN') "
            "AND decision = 'ALLOW')",
            name="ck_operation_state_decision",
        ),
        CheckConstraint(
            "(operation_status IN ('ADMITTED', 'DENIED', 'PENDING_APPROVAL', 'READY') AND "
            "execution_started_at IS NULL "
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
        {"mysql_engine": "InnoDB"},
    )
    operation_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    task_ref: Mapped[str] = mapped_column(identity_string(64), index=True)
    send_slot_task_ref: Mapped[str | None] = mapped_column(
        ForeignKey("gateway_tasks.task_ref"), nullable=True, unique=True
    )
    owner_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(identity_string(128))
    idempotency_key: Mapped[str] = mapped_column(identity_string(128))
    action: Mapped[str] = mapped_column(String(32))
    canonical_request_digest: Mapped[str] = mapped_column(identity_string(64))
    binding_digest: Mapped[str] = mapped_column(identity_string(64))
    authorization_version: Mapped[int] = mapped_column(Integer)
    operation_status: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    execution_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    execution_finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sanitized_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("audit_events.id"), nullable=True, unique=True
    )

    @property
    def audit_event_ref(self) -> str | None:
        return f"event_{self.audit_event_id}" if self.audit_event_id is not None else None


class PendingApproval(Base):
    __tablename__ = "pending_approvals"
    __table_args__ = (
        UniqueConstraint("approval_ref", "task_ref", "owner_id", name="uq_approval_owner_binding"),
        ForeignKeyConstraint(
            ["operation_ref", "task_ref", "owner_id"],
            [
                "gateway_operations.operation_ref",
                "gateway_operations.task_ref",
                "gateway_operations.owner_id",
            ],
            name="fk_approval_operation_binding",
        ),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXPIRED','REVOKED')",
            name="ck_approval_status",
        ),
        CheckConstraint(
            "(action IN ('files.list_authorized','files.read','tasks.list') AND recipient IS NULL "
            "AND template_ref IS NULL) OR (action IN ('email.draft','email.send') AND "
            "recipient IS NOT NULL AND template_ref IS NOT NULL "
            "AND template_ref = 'synthetic_mail_v1')",
            name="ck_approval_email_scope",
        ),
        CheckConstraint("expires_at > created_at", name="ck_approval_expiry"),
        CheckConstraint(
            "authorization_version >= 0 AND revision >= 0", name="ck_approval_versions"
        ),
        CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL) OR (status <> 'PENDING' AND "
            "decided_at IS NOT NULL)",
            name="ck_approval_decision",
        ),
        CheckConstraint(
            "(status = 'APPROVED' AND consent_ref IS NOT NULL AND "
            "((consumed_at IS NULL AND resume_ref IS NOT NULL) OR "
            "(consumed_at IS NOT NULL AND resume_ref IS NULL))) OR "
            "(status <> 'APPROVED' AND resume_ref IS NULL)",
            name="ck_approval_grant",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR (status IN ('APPROVED','EXPIRED','REVOKED') AND "
            "consumed_at >= created_at AND consumed_at < expires_at)",
            name="ck_approval_consumption",
        ),
        {"mysql_engine": "InnoDB"},
    )
    approval_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    operation_ref: Mapped[str] = mapped_column(identity_string(64), unique=True)
    task_ref: Mapped[str] = mapped_column(identity_string(64), index=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(identity_string(128))
    idempotency_key: Mapped[str] = mapped_column(identity_string(128))
    canonical_request_digest: Mapped[str] = mapped_column(identity_string(64))
    binding_digest: Mapped[str] = mapped_column(identity_string(64))
    action: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(64))
    resource_versions: Mapped[list] = mapped_column(JSON)
    recipient: Mapped[str | None] = mapped_column(String(254), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    template_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    authorization_version: Mapped[int]
    revision: Mapped[int] = mapped_column(default=0)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_ref: Mapped[str | None] = mapped_column(
        ForeignKey("scoped_consents.consent_ref"), nullable=True, unique=True
    )
    resume_ref: Mapped[str | None] = mapped_column(identity_string(128), nullable=True, unique=True)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    audit_event_id: Mapped[int] = mapped_column(ForeignKey("audit_events.id"))


class WorkflowCheckpoint(Base):
    """Workflow admission only; never an execution attempt or bearer capability."""

    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint("binding_ref", "task_ref", "owner_id", name="uq_workflow_owner_binding"),
        ForeignKeyConstraint(
            ["operation_ref", "task_ref", "owner_id"],
            [
                "gateway_operations.operation_ref",
                "gateway_operations.task_ref",
                "gateway_operations.owner_id",
            ],
            name="fk_workflow_operation_binding",
        ),
        UniqueConstraint("operation_ref", name="uq_workflow_operation"),
        UniqueConstraint("thread_id", "checkpoint_id", name="uq_workflow_checkpoint"),
        CheckConstraint(
            "phase IN ('PREPARING','PAUSED','ADMITTED','RESUMING','RESUMED','DENIED')",
            name="ck_workflow_phase",
        ),
        CheckConstraint("registration_authorization_version >= 0", name="ck_workflow_version"),
        CheckConstraint(
            "phase = 'PREPARING' OR checkpoint_id IS NOT NULL", name="ck_workflow_paused"
        ),
        CheckConstraint(
            "phase NOT IN ('ADMITTED','RESUMING','RESUMED') OR "
            "(admitted_authorization_version IS NOT NULL AND expires_at IS NOT NULL)",
            name="ck_workflow_admission",
        ),
        {"mysql_engine": "InnoDB"},
    )
    binding_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    task_ref: Mapped[str] = mapped_column(identity_string(64), index=True)
    operation_ref: Mapped[str] = mapped_column(identity_string(64))
    approval_ref: Mapped[str] = mapped_column(ForeignKey("pending_approvals.approval_ref"))
    request_id: Mapped[str] = mapped_column(identity_string(128))
    idempotency_key: Mapped[str] = mapped_column(identity_string(128))
    canonical_request_digest: Mapped[str] = mapped_column(identity_string(64))
    thread_id: Mapped[str] = mapped_column(identity_string(64), unique=True)
    checkpoint_id: Mapped[str | None] = mapped_column(identity_string(64), nullable=True)
    workflow_version: Mapped[str] = mapped_column(String(32))
    registration_authorization_version: Mapped[int]
    admitted_authorization_version: Mapped[int | None] = mapped_column(nullable=True)
    phase: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    audit_event_id: Mapped[int] = mapped_column(ForeignKey("audit_events.id"))


class EmailArtifact(Base):
    """Private draft/acceptance metadata only; a draft rehydrates the fixed synthetic template."""

    __tablename__ = "email_artifacts"
    __table_args__ = (
        CheckConstraint("kind IN ('EMAIL_DRAFT','MAILPIT_SEND')", name="ck_email_artifact_kind"),
        CheckConstraint("template_ref = 'synthetic_mail_v1'", name="ck_email_artifact_template"),
        {"mysql_engine": "InnoDB"},
    )
    artifact_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    operation_ref: Mapped[str] = mapped_column(
        ForeignKey("gateway_operations.operation_ref"), unique=True
    )
    attempt_ref: Mapped[str] = mapped_column(
        ForeignKey("execution_attempts.attempt_ref"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    template_ref: Mapped[str] = mapped_column(String(32))
    payload_digest: Mapped[str] = mapped_column(identity_string(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ExecutionAttempt(Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        CheckConstraint(
            "(workflow_binding_ref IS NULL AND resume_hint_digest IS NULL) OR "
            "(workflow_binding_ref IS NOT NULL AND resume_hint_digest IS NOT NULL AND "
            "length(resume_hint_digest) = 64)",
            name="ck_attempt_controlled",
        ),
        CheckConstraint(
            "mode IN ('SIMULATED','SYNTHETIC_READ','EMAIL_DRAFT','MAILPIT_SEND')",
            name="ck_attempt_mode",
        ),
        CheckConstraint(
            "state IN ('DISPATCHING','SUCCEEDED','FAILED','UNKNOWN')", name="ck_attempt_state"
        ),
        CheckConstraint(
            "(state IN ('DISPATCHING','UNKNOWN') AND completed_at IS NULL) OR "
            "(state IN ('SUCCEEDED','FAILED') AND completed_at IS NOT NULL AND "
            "completed_at >= dispatch_at)",
            name="ck_attempt_times",
        ),
        CheckConstraint(
            "(mode IN ('SIMULATED','EMAIL_DRAFT','MAILPIT_SEND') AND state = 'SUCCEEDED' "
            "AND result_json IS NOT NULL "
            "AND result_expires_at IS NOT NULL AND result_expires_at > completed_at) OR "
            "((mode = 'SYNTHETIC_READ' OR state <> 'SUCCEEDED') AND "
            "result_json IS NULL AND result_expires_at IS NULL)",
            name="ck_attempt_result",
        ),
        {"mysql_engine": "InnoDB"},
    )
    attempt_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    operation_ref: Mapped[str] = mapped_column(
        ForeignKey("gateway_operations.operation_ref"), unique=True
    )
    dispatch_nonce: Mapped[str] = mapped_column(identity_string(64), unique=True)
    mode: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    workflow_binding_ref: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_checkpoints.binding_ref"), nullable=True
    )
    resume_hint_digest: Mapped[str | None] = mapped_column(identity_string(64), nullable=True)
    dispatch_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sanitized_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    result_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    audit_event_id: Mapped[int] = mapped_column(ForeignKey("audit_events.id"))


class DocumentResource(Base):
    __tablename__ = "document_resources"
    __table_args__ = (
        UniqueConstraint("owner_ref", "storage_reference", name="uq_document_owner_storage"),
        CheckConstraint("resource_type = 'SYNTHETIC_TEXT'", name="ck_document_type"),
        CheckConstraint(
            "classification IN ('PRIVATE_ORIGINAL','SHAREABLE')", name="ck_document_classification"
        ),
        CheckConstraint(
            "length(resource_ref) = 41 AND substr(resource_ref,1,9) = 'resource_'",
            name="ck_document_reference",
        ),
        CheckConstraint(
            "length(version_ref) = 40 AND substr(version_ref,1,8) = 'version_'",
            name="ck_document_version",
        ),
        CheckConstraint("length(content_digest) = 64", name="ck_document_digest"),
        CheckConstraint("active IN (0,1)", name="ck_document_active"),
        CheckConstraint(
            "storage_reference IN ('ghost_demo_v1_doc_tax_2026','ghost_demo_v1_doc_bank_oct',"
            "'ghost_demo_v1_doc_personal_notes','ghost_demo_v1_doc_project_report',"
            "'ghost_demo_v1_doc_meeting_oct','ghost_demo_v1_doc_schedule')",
            name="ck_document_storage",
        ),
        CheckConstraint("updated_at >= created_at", name="ck_document_updated"),
        {"mysql_engine": "InnoDB"},
    )
    resource_ref: Mapped[str] = mapped_column(identity_string(64), primary_key=True)
    owner_ref: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(120))
    classification: Mapped[str] = mapped_column(String(32))
    storage_reference: Mapped[str] = mapped_column(identity_string(96))
    content_digest: Mapped[str] = mapped_column(identity_string(64))
    version_ref: Mapped[str] = mapped_column(identity_string(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
