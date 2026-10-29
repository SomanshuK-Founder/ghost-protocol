"""v1.2 owner-control metadata only; no tool/execution schema changes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.agent_schemas import IdentityModel
from app.gateway_contracts import OpaqueReference

VERSION = "approval-workflow-v1"


class WorkflowPrepare(IdentityModel):
    task_ref: OpaqueReference
    approval_ref: OpaqueReference
    request_id: OpaqueReference
    idempotency_key: OpaqueReference
    workflow_version: Literal["approval-workflow-v1"] = VERSION


class WorkflowPause(IdentityModel):
    checkpoint_id: OpaqueReference

    @field_validator("checkpoint_id")
    @classmethod
    def canonical_uuid(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("Canonical checkpoint identity required")
        return value


class WorkflowIdentity(WorkflowPrepare, WorkflowPause):
    operation_ref: OpaqueReference
    thread_id: OpaqueReference
    expected_authorization_version: int = Field(ge=0)


class WorkflowSnapshot(WorkflowPrepare):
    binding_ref: OpaqueReference
    owner_ref: OpaqueReference
    operation_ref: OpaqueReference
    canonical_request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    thread_id: OpaqueReference
    checkpoint_id: OpaqueReference | None
    registration_authorization_version: int = Field(ge=0)
    authorization_version: int = Field(ge=0)
    admitted_authorization_version: int | None
    phase: Literal["PREPARING", "PAUSED", "ADMITTED", "RESUMING", "RESUMED", "DENIED"]
    expires_at: datetime | None
    audit_event_ref: OpaqueReference
